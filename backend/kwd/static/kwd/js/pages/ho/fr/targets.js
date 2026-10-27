/* Head Office: monthly targets per franchisee, product-wise targets, product list prices. */
import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, Icon, PageHead, SectionHead } from '../../../ui.js'
import { fmtINR } from '../../../lib.js'
import { achievement, monthStart, addMonths, monthName } from '../../../fr.js'

const num = (v) => (v === '' || v == null ? null : Number(v))
const rowOf = (S, fid, pid = null) => S.d && S.d.targets.find((t) => t.franchise_id === fid && t.month === S.month && (t.product_id || null) === pid)

// fill the editable boxes from what is saved for the chosen month / franchisee
function fill(sc) {
  const S = sc.S, active = sc.ctx.data.frs.filter((f) => f.is_active)
  S.ov = Object.fromEntries(active.map((f) => { const r = rowOf(S, f.id); return [f.id, { units: r && r.target_units != null ? r.target_units : '', amount: r && r.target_amount != null ? r.target_amount : '' }] }))
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
  state: { month: monthStart(), d: null, err: '', ov: {}, pf: '', pt: {}, busy: false, prices: null, pbusy: '' },
  async init() {
    this.S.prices = this.ctx.data.products.map((p) => ({ ...p, price: p.list_price ?? '', gst: p.gst_percent ?? 0 }))
    await this.actions.load.call(this)
  },
  view(S, ctx) {
    const { frs, products } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.d) return Loading('Loading targets…')
    const active = frs.filter((f) => f.is_active), month = S.month
    return html`${PageHead({ label: 'Set up', title: 'Targets & prices', sub: 'Set each franchisee’s monthly target. Achievement is counted from their recorded sales.',
        actions: html`<div class="seg"><button data-act="month" data-n="-1" aria-label="Previous month">${Icon('left', 16)}</button>
          <button class="on" style="min-width:140px">${monthName(month)}</button>
          <button data-act="month" data-n="1" aria-label="Next month">${Icon('right', 16)}</button></div>` })}
      <section>
        ${SectionHead({ title: 'Monthly target per franchisee', action: html`<button class="btn sm" data-act="copyLast">Copy last month</button>` })}
        ${active.length === 0 ? html`<p class="muted">Add franchisees first.</p>` : html`<div class="table-wrap"><table>
          <thead><tr><th>Franchisee</th><th>Target units</th><th>Target value (₹)</th><th class="num">Sold</th><th class="num">Achieved</th></tr></thead>
          <tbody>${active.map((f) => {
            const a = achievement(S.d.sold, S.d.targets, month, f.id), v = S.ov[f.id] || { units: '', amount: '' }
            return html`<tr><td><b>${f.business_name}</b></td>
              <td><input type="number" min="0" inputmode="numeric" style="width:110px" data-bind="ov.${f.id}.units" value="${v.units}" aria-label="Unit target for ${f.business_name}"></td>
              <td><input type="number" min="0" inputmode="decimal" style="width:150px" data-bind="ov.${f.id}.amount" value="${v.amount}" aria-label="Value target for ${f.business_name}"></td>
              <td class="num">${fmtINR(a.value)}<div class="muted small">${a.units} units</div></td>
              <td class="num">${a.pctValue != null ? `${a.pctValue}%` : a.pctUnits != null ? `${a.pctUnits}%` : '—'}</td></tr>`
          })}</tbody></table></div>`}
        <div class="row" style="margin-top:12px"><button class="btn primary" ${S.busy || !active.length ? raw('disabled') : ''} data-act="saveOverall">${S.busy ? 'Saving…' : 'Save targets'}</button></div>
      </section>

      <section class="card">
        <h2>Product-wise unit targets (optional)</h2>
        <label style="max-width:360px">Franchisee<select data-bind="pf" data-change="pickFr"><option value="">Choose…</option>${active.map((f) => html`<option value="${f.id}" ${S.pf === f.id ? raw('selected') : ''}>${f.business_name}</option>`)}</select></label>
        ${S.pf ? html`<div class="grid2">${products.filter((p) => p.is_active).map((p) => html`<label>${p.name}<input type="number" min="0" inputmode="numeric" data-bind="pt.${p.id}" value="${S.pt[p.id] ?? ''}"></label>`)}</div>
          <button class="btn" ${S.busy ? raw('disabled') : ''} data-act="saveProducts">Save product targets</button>` : ''}
      </section>

      <section>
        ${SectionHead({ title: 'Products & list prices' })}
        <p class="muted small" style="margin-top:0">The list price is shown to franchisees when they record a sale. A sale priced more than 10% below it is flagged for you.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Product</th><th>HSN/SAC</th><th>Unit</th><th>GST (%)</th><th>List price (₹)</th><th>Installation needed</th><th>Offered</th><th></th></tr></thead>
          <tbody>${S.prices.map((p, i) => html`<tr><td><b>${p.name}</b><div class="muted small">${p.code}</div></td>
            <td><input style="width:110px" data-bind="prices.${i}.hsn_sac" value="${p.hsn_sac || ''}" aria-label="HSN/SAC for ${p.name}"></td>
            <td>${p.unit || 'unit'}</td>
            <td><input type="number" min="0" max="100" step="0.01" inputmode="decimal" style="width:85px" data-bind="prices.${i}.gst" value="${p.gst}" aria-label="GST rate for ${p.name}"></td>
            <td><input type="number" min="0" inputmode="decimal" style="width:140px" data-bind="prices.${i}.price" value="${p.price}" aria-label="List price of ${p.name}"></td>
            <td>${p.needs_install ? 'Yes' : 'No'}</td>
            <td><label class="check inline"><input type="checkbox" data-bind="prices.${i}.is_active" ${p.is_active ? raw('checked') : ''}> On</label></td>
            <td><button class="btn sm" ${S.pbusy === p.id ? raw('disabled') : ''} data-act="savePrice" data-i="${i}">Save</button></td></tr>`)}</tbody></table></div>
      </section>`
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
      S.ov = Object.fromEntries(this.ctx.data.frs.filter((f) => f.is_active).map((f) => {
        const r = S.d.targets.find((t) => t.franchise_id === f.id && t.month === prev && !t.product_id)
        return [f.id, { units: r && r.target_units != null ? r.target_units : '', amount: r && r.target_amount != null ? r.target_amount : '' }]
      }))
      this.render()
      toast('Copied from last month. Press Save to keep it.')
    },
    async saveOverall() {
      const S = this.S
      this.set({ busy: true })
      for (const f of this.ctx.data.frs.filter((x) => x.is_active)) {
        const v = S.ov[f.id] || {}
        const { error } = await put(S, f.id, null, { target_units: num(v.units), target_amount: num(v.amount) })
        if (error) { this.set({ busy: false }); return toast(errText(error), 'bad') }
      }
      this.set({ busy: false })
      toast(`Targets saved for ${monthName(S.month)}`)
      await this.actions.load.call(this)
    },
    async saveProducts() {
      const S = this.S
      this.set({ busy: true })
      for (const p of this.ctx.data.products) {
        const { error } = await put(S, S.pf, p.id, { target_units: num(S.pt[p.id]), target_amount: null })
        if (error) { this.set({ busy: false }); return toast(errText(error), 'bad') }
      }
      this.set({ busy: false })
      toast('Product targets saved')
      await this.actions.load.call(this)
    },
    async savePrice(el) {
      const p = this.S.prices[Number(el.dataset.i)]
      if (!Number.isFinite(Number(p.gst)) || Number(p.gst) < 0 || Number(p.gst) > 100) return toast('Enter a GST rate from 0 to 100%.', 'bad')
      this.set({ pbusy: p.id })
      const product = { ...p, list_price: p.price === '' ? null : Number(p.price), hsn_sac: p.hsn_sac.trim() || null, gst_percent: Number(p.gst), is_active: p.is_active }
      const { error } = await supabase.from('fr_products').update({ list_price: product.list_price, hsn_sac: product.hsn_sac, gst_percent: product.gst_percent, is_active: product.is_active }).eq('id', p.id)
      this.set({ pbusy: '' })
      if (error) return toast(errText(error), 'bad')
      this.ctx.data.products = this.ctx.data.products.map((row) => row.id === p.id ? { ...row, ...product } : row)
      this.ctx.data.byId = Object.fromEntries(this.ctx.data.products.map((row) => [row.id, row]))
      toast(`${p.name} saved`)
    },
  },
}
