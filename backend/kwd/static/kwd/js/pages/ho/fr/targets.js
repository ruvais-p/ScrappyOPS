/* Head Office: monthly unit targets per product for each franchisee, product list prices, adding products and categories. */
import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, Icon, PageHead, SectionHead } from '../../../ui.js'
import { Sheet, errLine } from '../../../kit.js'
import { fmtINR } from '../../../lib.js'
import { achievement, monthStart, addMonths, monthName } from '../../../fr.js'

const num = (v) => (v === '' || v == null ? null : Number(v))
const NEW_CATEGORY = '__new'
const FALLBACK_CATEGORIES = [{ key: 'digester', name: 'Digester' }, { key: 'inoculum', name: 'Inoculum' }, { key: 'burner', name: 'Burner' }, { key: 'incinerator', name: 'Incinerator' }]
const blankProduct = (cats) => ({ name: '', code: '', category: (cats[0] || FALLBACK_CATEGORIES[0]).key, newcat: '', spec: '', unit: 'unit', hsn_sac: '', gst: '18', price: '', needs_install: false })

function addSheet(S) {
  const n = S.np, ex = Number(n.price), g = Number(n.gst) || 0
  return Sheet({ title: 'Add a product', close: 'closeAdd', body: html`
    <p class="muted small" style="margin-top:0">The HSN/SAC and GST rate are filled in automatically whenever this product is chosen on a bill.</p>
    <label>Product name<input data-bind="np.name" value="${n.name}" placeholder="e.g. Kitchen Waste Digester 480 L"></label>
    <div class="grid2">
      <label>Product code<input data-bind="np.code" value="${n.code}" placeholder="e.g. KWD-480" style="text-transform:uppercase"></label>
      <label>Category<select data-bind="np.category" data-live>${S.cats.map((c) => html`<option value="${c.key}" ${n.category === c.key ? raw('selected') : ''}>${c.name}</option>`)}<option value="${NEW_CATEGORY}" ${n.category === NEW_CATEGORY ? raw('selected') : ''}>+ Add a new category…</option></select></label>
      ${n.category === NEW_CATEGORY ? html`<label style="grid-column:1 / -1">New category name<input data-bind="np.newcat" value="${n.newcat}" placeholder="e.g. Solar dryer"></label>` : ''}
      <label>HSN/SAC code<input data-bind="np.hsn_sac" value="${n.hsn_sac}" inputmode="numeric" placeholder="4 to 8 digits"></label>
      <label>GST (%)<input type="number" min="0" max="100" step="0.01" inputmode="decimal" data-bind="np.gst" data-live value="${n.gst}"></label>
      <label>List price without GST (₹)<input type="number" min="0" inputmode="decimal" data-bind="np.price" data-live value="${n.price}"></label>
      <label>Unit<input data-bind="np.unit" value="${n.unit}"></label>
    </div>
    ${n.price !== '' && ex > 0 ? html`<p class="muted small" style="margin-top:0">With ${g}% GST the price is ${fmtINR(ex * (1 + g / 100))}.</p>` : ''}
    <label>Description (optional)<input data-bind="np.spec" value="${n.spec}"></label>
    <label class="check inline"><input type="checkbox" data-bind="np.needs_install" ${n.needs_install ? raw('checked') : ''}> Needs installation after delivery</label>
    ${errLine(S.nserr)}
    <button class="btn primary block" ${S.nbusy ? raw('disabled') : ''} data-act="saveNew">${S.nbusy ? 'Adding…' : 'Add product'}</button>` })
}
const rowOf = (S, fid, pid = null) => S.d && S.d.targets.find((t) => t.franchise_id === fid && t.month === S.month && (t.product_id || null) === pid)

// fill the editable boxes from what is saved for the chosen month / franchisee
function fill(sc) {
  const S = sc.S, active = sc.ctx.data.frs.filter((f) => f.is_active)
  if (!active.some((f) => f.id === S.pf)) S.pf = active.length ? active[0].id : ''
  S.pt = S.pf ? Object.fromEntries(sc.ctx.data.products.map((p) => { const r = rowOf(S, S.pf, p.id); return [p.id, r && r.target_units != null ? r.target_units : ''] })) : {}
  sc.render()
}

async function put(S, fid, pid, values) {
  const cur = rowOf(S, fid, pid)
  const empty = values.target_units === null && values.target_amount === null
  if (cur && empty) return supabase.from('fr_targets').delete().eq('id', cur.id)
  if (cur) return supabase.from('fr_targets').update(values).eq('id', cur.id)
  if (empty) return { error: null }
  return supabase.from('fr_targets').insert({ franchise_id: fid, month: S.month, product_id: pid, ...values })
}

export default {
  state: { month: monthStart(), d: null, err: '', pf: '', pt: {}, busy: false, prices: null, pbusy: '', cats: FALLBACK_CATEGORIES, add: false, np: blankProduct(FALLBACK_CATEGORIES), nserr: '', nbusy: false },
  async init() {
    this.S.prices = this.ctx.data.products.map((p) => ({ ...p, price: p.list_price ?? '', gst: p.gst_percent ?? 0 }))
    const c = await supabase.from('fr_product_categories').select('*').order('sort')
    if (!c.error && c.data && c.data.length) this.S.cats = c.data
    await this.actions.load.call(this)
  },
  view(S, ctx) {
    const { frs, products } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.d) return Loading('Loading targets…')
    const active = frs.filter((f) => f.is_active), month = S.month, live = products.filter((p) => p.is_active)
    const a = S.pf ? achievement(S.d.sold, S.d.targets, month, S.pf) : null
    const target = S.pf ? live.reduce((t, p) => t + (Number(S.pt[p.id]) || 0), 0) : 0
    const catName = (key) => (S.cats.find((c) => c.key === key) || {}).name || key
    return html`${PageHead({ label: 'Set up', title: 'Targets & prices', sub: 'Set how many units of each product a franchisee should sell each month. Achievement is counted from their recorded sales.',
        actions: html`<div class="seg"><button data-act="month" data-n="-1" aria-label="Previous month">${Icon('left', 16)}</button>
          <button class="on" style="min-width:140px">${monthName(month)}</button>
          <button data-act="month" data-n="1" aria-label="Next month">${Icon('right', 16)}</button></div>` })}
      <section>
        ${SectionHead({ title: 'Monthly unit targets per product', action: S.pf ? html`<button class="btn sm" data-act="copyLast">Copy last month</button>` : '' })}
        ${active.length === 0 ? html`<p class="muted">Add franchisees first.</p>` : html`
          <label style="max-width:360px">Franchisee<select data-bind="pf" data-change="pickFr">${active.map((f) => html`<option value="${f.id}" ${S.pf === f.id ? raw('selected') : ''}>${f.business_name}</option>`)}</select></label>
          <div class="grid2">${live.map((p) => html`<label>${p.name}<input type="number" min="0" inputmode="numeric" data-bind="pt.${p.id}" data-live value="${S.pt[p.id] ?? ''}"><span class="muted small">Sold this month: ${((a.perProduct[p.id] || {}).units) || 0}</span></label>`)}</div>
          <p class="muted small">Target ${target} unit${target === 1 ? '' : 's'} in ${monthName(month)} · sold ${a.units}${target > 0 ? ` (${Math.round((100 * a.units) / target)}%)` : ''}</p>
          <button class="btn primary" ${S.busy ? raw('disabled') : ''} data-act="saveProducts">${S.busy ? 'Saving…' : 'Save targets'}</button>`}
      </section>

      <section>
        ${SectionHead({ title: 'Products & list prices', action: html`<button class="btn sm primary" data-act="openAdd">${Icon('plus', 16)} Add product</button>` })}
        <p class="muted small" style="margin-top:0">The list price is shown to franchisees when they record a sale. A sale priced more than 10% below it is flagged for you.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Product</th><th>HSN/SAC</th><th>Unit</th><th>GST (%)</th><th>List price (₹)</th><th>Installation needed</th><th>Offered</th><th></th></tr></thead>
          <tbody>${S.prices.map((p, i) => html`<tr><td><b>${p.name}</b><div class="muted small">${p.code} · ${catName(p.category)}</div></td>
            <td><input style="width:110px" data-bind="prices.${i}.hsn_sac" value="${p.hsn_sac || ''}" aria-label="HSN/SAC for ${p.name}"></td>
            <td>${p.unit || 'unit'}</td>
            <td><input type="number" min="0" max="100" step="0.01" inputmode="decimal" style="width:85px" data-bind="prices.${i}.gst" value="${p.gst}" aria-label="GST rate for ${p.name}"></td>
            <td><input type="number" min="0" inputmode="decimal" style="width:140px" data-bind="prices.${i}.price" value="${p.price}" aria-label="List price of ${p.name}"></td>
            <td>${p.needs_install ? 'Yes' : 'No'}</td>
            <td><label class="check inline"><input type="checkbox" data-bind="prices.${i}.is_active" ${p.is_active ? raw('checked') : ''}> On</label></td>
            <td><button class="btn sm" ${S.pbusy === p.id ? raw('disabled') : ''} data-act="savePrice" data-i="${i}">Save</button></td></tr>`)}</tbody></table></div>
      </section>
      ${S.add ? addSheet(S) : ''}`
  },
  actions: {
    async load() {
      const [t, s] = await Promise.all([supabase.from('fr_targets').select('*'), supabase.from('v_fr_sold').select('*')])
      if (t.error || s.error) return this.set({ err: errText(t.error || s.error) })
      this.S.d = { targets: t.data, sold: s.data }
      fill(this)
    },
    month(el) { this.S.month = addMonths(this.S.month, Number(el.dataset.n)); fill(this) },
    pickFr() { fill(this) },
    copyLast() {
      const S = this.S, prev = addMonths(S.month, -1)
      S.pt = Object.fromEntries(this.ctx.data.products.map((p) => {
        const r = S.d.targets.find((t) => t.franchise_id === S.pf && t.month === prev && t.product_id === p.id)
        return [p.id, r && r.target_units != null ? r.target_units : '']
      }))
      this.render()
      toast('Copied from last month. Press Save to keep it.')
    },
    async saveProducts() {
      const S = this.S
      if (S.busy || !S.pf) return
      const products = this.ctx.data.products.filter((p) => p.is_active)
      if (products.some((p) => S.pt[p.id] !== '' && S.pt[p.id] != null && (!Number.isInteger(Number(S.pt[p.id])) || Number(S.pt[p.id]) < 0))) {
        return toast('Enter whole, non-negative target units.', 'bad')
      }
      this.set({ busy: true })
      for (const p of products) {
        const { error } = await put(S, S.pf, p.id, { target_units: num(S.pt[p.id]), target_amount: null })
        if (error) { this.set({ busy: false }); return toast(errText(error), 'bad') }
      }
      // Saving the new product targets replaces the now-hidden overall target, even when every box is cleared.
      const { error } = await put(S, S.pf, null, { target_units: null, target_amount: null })
      if (error) { this.set({ busy: false }); return toast(errText(error), 'bad') }
      this.set({ busy: false })
      toast('Targets saved')
      await this.actions.load.call(this)
    },
    openAdd() { this.set({ add: true, np: blankProduct(this.S.cats), nserr: '' }) },
    closeAdd() { this.set({ add: false }) },
    async saveNew() {
      const n = this.S.np
      const code = n.code.trim().toUpperCase(), name = n.name.trim(), hsn = n.hsn_sac.trim(), gst = n.gst === '' ? 0 : Number(n.gst)
      const bad = (m) => this.set({ nserr: m })
      if (name.length < 2) return bad('Enter the product name.')
      if (!/^[A-Z0-9][A-Z0-9._-]{1,29}$/.test(code)) return bad('Enter a product code of letters, numbers and dashes, for example KWD-480.')
      if (n.category === NEW_CATEGORY && (n.newcat.trim().length < 2 || n.newcat.trim().length > 40)) return bad('Enter the new category name (2 to 40 characters).')
      if (!/^\d{4,8}$/.test(hsn)) return bad('Enter the HSN/SAC code: 4 to 8 digits.')
      if (!Number.isFinite(gst) || gst < 0 || gst > 100) return bad('Enter a GST rate from 0 to 100%.')
      if (n.price !== '' && !(Number(n.price) >= 0)) return bad('Enter the list price without GST, or leave it empty.')
      this.set({ nbusy: true, nserr: '' })
      let category = n.category
      if (category === NEW_CATEGORY) {
        const c = await supabase.from('fr_product_categories').insert({ name: n.newcat.trim() }).select('*').single()
        if (c.error) { this.set({ nbusy: false }); return bad(errText(c.error)) }
        category = c.data.key
        this.S.cats = [...this.S.cats, c.data]
        this.S.np.category = category                     // if the product itself is refused below, the new category stays chosen
      }
      const { data, error } = await supabase.from('fr_products').insert({
        code, name, category, spec: n.spec.trim() || null, unit: n.unit.trim() || 'unit', hsn_sac: hsn, gst_percent: gst,
        list_price: n.price === '' ? null : Number(n.price), needs_install: Boolean(n.needs_install),
      }).select('*').single()
      this.set({ nbusy: false })
      if (error) return bad(errText(error))
      this.ctx.data.products = [...this.ctx.data.products, data]
      this.ctx.data.byId = Object.fromEntries(this.ctx.data.products.map((row) => [row.id, row]))
      this.set({ add: false, prices: [...this.S.prices, { ...data, price: data.list_price ?? '', gst: data.gst_percent ?? 0 }] })
      toast(`${data.name} added. It can now be chosen on bills.`)
    },
    async savePrice(el) {
      const p = this.S.prices[Number(el.dataset.i)]
      if (!Number.isFinite(Number(p.gst)) || Number(p.gst) < 0 || Number(p.gst) > 100) return toast('Enter a GST rate from 0 to 100%.', 'bad')
      this.set({ pbusy: p.id })
      const hsn = (p.hsn_sac || '').trim()
      if (!/^\d{4,8}$/.test(hsn)) { this.set({ pbusy: '' }); return toast('Enter the HSN/SAC code: 4 to 8 digits.', 'bad') }
      const product = { ...p, list_price: p.price === '' ? null : Number(p.price), hsn_sac: hsn, gst_percent: Number(p.gst), is_active: p.is_active }
      const { error } = await supabase.from('fr_products').update({ list_price: product.list_price, hsn_sac: product.hsn_sac, gst_percent: product.gst_percent, is_active: product.is_active }).eq('id', p.id)
      this.set({ pbusy: '' })
      if (error) return toast(errText(error), 'bad')
      this.ctx.data.products = this.ctx.data.products.map((row) => row.id === p.id ? { ...row, ...product } : row)
      this.ctx.data.byId = Object.fromEntries(this.ctx.data.products.map((row) => [row.id, row]))
      toast(`${p.name} saved`)
    },
  },
}
