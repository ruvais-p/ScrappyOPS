import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, SectionHead } from '../../../ui.js'
import { fmtDate, fmtTime } from '../../../lib.js'
import { Sheet, errLine } from '../../../kit.js'
import { MOVE_KIND } from '../../../fr.js'

function dispatchSheet(S, frs, prods) {
  return Sheet({ title: 'Dispatch stock to a franchisee', close: 'closeSend', body: html`
    <p class="muted small" style="margin-top:0">This adds the units to their stock straight away.</p>
    <label>Franchisee<select data-bind="fid"><option value="">Choose…</option>${frs.filter((f) => f.is_active).map((f) => html`<option value="${f.id}" ${S.fid === f.id ? raw('selected') : ''}>${f.business_name}</option>`)}</select></label>
    ${S.rows.map((r, i) => html`<div class="grid2">
      <label>Product<select data-bind="rows.${i}.product_id"><option value="">Choose…</option>${prods.map((p) => html`<option value="${p.id}" ${r.product_id === p.id ? raw('selected') : ''}>${p.name}</option>`)}</select></label>
      <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="rows.${i}.qty" value="${r.qty}"></label></div>`)}
    <button class="btn sm" data-act="addRow">${Icon('plus', 16)} Another product</button>
    <label>Challan / dispatch no.<input data-bind="ref" value="${S.ref}"></label>
    ${errLine(S.serr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Add to their stock'}</button>` })
}

function hoAddSheet(S, prods) {
  return Sheet({ title: 'Add to Head Office stock', close: 'closeSend', body: html`
    <p class="muted small" style="margin-top:0">This stock backs telecallers' direct bills. It adds the units straight away.</p>
    ${S.rows.map((r, i) => html`<div class="grid2">
      <label>Product<select data-bind="rows.${i}.product_id"><option value="">Choose…</option>${prods.map((p) => html`<option value="${p.id}" ${r.product_id === p.id ? raw('selected') : ''}>${p.name}</option>`)}</select></label>
      <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="rows.${i}.qty" value="${r.qty}"></label></div>`)}
    <button class="btn sm" data-act="addRow">${Icon('plus', 16)} Another product</button>
    <label>Challan / purchase no.<input data-bind="ref" value="${S.ref}"></label>
    ${errLine(S.serr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Add to stock'}</button>` })
}

export default {
  state: { mode: 'franchise', stock: null, moves: [], err: '', send: false, only: 'adjust', ff: '', fid: '', rows: [{ product_id: '', qty: '' }], ref: '', busy: false, serr: '' },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { frs, products, byId } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.stock) return Loading('Loading stock…')
    const prods = products.filter((p) => p.is_active)
    const toggle = html`<button class="btn ${S.mode === 'ho' ? 'primary' : ''}" data-act="toggleMode">${Icon('box', 18)} ${S.mode === 'ho' ? 'Franchise stock' : 'HO stock'}</button>`
    if (S.mode === 'ho') {
      const cell = (pid) => S.stock.find((s) => s.product_id === pid)
      const shown = S.moves.filter((m) => (S.only === 'adjust' ? ['damaged', 'returned', 'count_adjust'].includes(m.kind) : S.only === 'in' ? ['opening', 'received'].includes(m.kind) : true))
      return html`${PageHead({ label: 'Franchise', title: 'Head Office stock', sub: 'What Head Office holds for telecallers to bill directly. No franchisee ever draws from this.',
          actions: html`<div class="row">${toggle}<button class="btn" data-act="refresh">Refresh</button><button class="btn primary" data-act="openSend">${Icon('truck', 18)} Add stock</button></div>` })}
        ${prods.length === 0 ? Empty('No products yet.') : html`<div class="table-wrap"><table>
          <thead><tr><th>Product</th><th class="num">On hand</th></tr></thead>
          <tbody>${prods.map((p) => { const c = cell(p.id); const n = c ? c.on_hand : 0
            return html`<tr><td><b>${p.name}</b></td><td class="num">${n <= 0 ? html`<span class="text-bad">0</span>` : n <= 2 ? html`<span class="text-warn">${n}</span>` : n}</td></tr>` })}</tbody></table></div>`}
        <section>
          ${SectionHead({ title: 'Movements', count: shown.length, action: html`<div class="seg">${[['adjust', 'Adjustments'], ['in', 'Stock in'], ['all', 'Everything']].map(([k, l]) => html`<button class="${S.only === k ? 'on' : ''}" data-act="only" data-k="${k}">${l}</button>`)}</div>` })}
          ${shown.length === 0 ? Empty('Nothing here.') : html`<ul class="list">${shown.map((m) => html`<li><div class="item">
            <div class="grow"><div class="title">${byId[m.product_id] && byId[m.product_id].name}</div>
              <div class="muted small">${MOVE_KIND[m.kind]}${m.ref_no ? ` · ${m.ref_no}` : ''}${m.note ? ` · ${m.note}` : ''}</div></div>
            <div style="text-align:right"><b>${m.qty > 0 ? `+${m.qty}` : m.qty}</b><div class="muted small">${fmtDate(m.created_at)}, ${fmtTime(m.created_at)}</div></div></div></li>`)}</ul>`}
        </section>
        ${S.send ? hoAddSheet(S, prods) : ''}`
    }
    const cell = (fid, pid) => S.stock.find((s) => s.franchise_id === fid && s.product_id === pid)
    const fname = (id) => (frs.find((f) => f.id === id) || {}).business_name || '—'
    const shown = S.moves.filter((m) => (!S.ff || m.franchise_id === S.ff) && (S.only === 'adjust' ? ['damaged', 'returned', 'count_adjust'].includes(m.kind) : S.only === 'in' ? ['opening', 'received'].includes(m.kind) : true))
    const rows = S.ff ? frs.filter((f) => f.id === S.ff) : frs
    return html`${PageHead({ label: 'Franchise', title: 'Stock', sub: 'What each franchisee holds. Corrections, damage and returns are listed below so you can question them.',
        actions: html`<div class="row">${toggle}<button class="btn" data-act="refresh">Refresh</button><button class="btn primary" data-act="openSend">${Icon('truck', 18)} Dispatch stock</button></div>` })}
      ${frs.length === 0 ? '' : html`<div class="toolbar">
        <select data-bind="ff" data-live data-change="reload" aria-label="Franchisee"><option value="">All franchisees</option>${frs.map((f) => html`<option value="${f.id}" ${S.ff === f.id ? raw('selected') : ''}>${f.business_name}${f.is_active ? '' : ' (inactive)'}</option>`)}</select>
      </div>`}
      ${frs.length === 0 ? Empty('No franchisees yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Franchisee</th>${prods.map((p) => html`<th class="num" title="${p.name}">${p.code}</th>`)}<th class="num">Total</th></tr></thead>
        <tbody>${rows.map((f) => {
          const tot = prods.reduce((a, p) => a + ((cell(f.id, p.id) || {}).on_hand ?? 0), 0)
          return html`<tr style="${f.is_active ? '' : 'opacity:.6'}"><td><b>${f.business_name}</b></td>
            ${prods.map((p) => { const c = cell(f.id, p.id); return html`<td class="num">${!c ? html`<span class="muted">–</span>` : c.on_hand <= 0 ? html`<span class="text-bad">0</span>` : c.on_hand <= 2 ? html`<span class="text-warn">${c.on_hand}</span>` : c.on_hand}</td>` })}
            <td class="num"><b>${tot}</b></td></tr>`
        })}</tbody></table></div>`}
      <p class="muted small">“–” means the franchisee has never held that product. Red is out of stock, amber is 2 or fewer.</p>
      <section>
        ${SectionHead({ title: S.ff ? `Movements · ${fname(S.ff)}` : 'Movements', count: shown.length, action: html`<div class="seg">${[['adjust', 'Adjustments'], ['in', 'Stock in'], ['all', 'Everything']].map(([k, l]) => html`<button class="${S.only === k ? 'on' : ''}" data-act="only" data-k="${k}">${l}</button>`)}</div>` })}
        ${shown.length === 0 ? Empty('Nothing here.') : html`<ul class="list">${shown.map((m) => html`<li><div class="item">
          <div class="grow"><div class="title">${fname(m.franchise_id)} · ${byId[m.product_id] && byId[m.product_id].name}</div>
            <div class="muted small">${MOVE_KIND[m.kind]}${m.ref_no ? ` · ${m.ref_no}` : ''}${m.note ? ` · ${m.note}` : ''}</div></div>
          <div style="text-align:right"><b>${m.qty > 0 ? `+${m.qty}` : m.qty}</b><div class="muted small">${fmtDate(m.created_at)}, ${fmtTime(m.created_at)}</div></div></div></li>`)}</ul>`}
      </section>
      ${S.send ? dispatchSheet(S, frs, prods) : ''}`
  },
  actions: {
    only(el) { this.set({ only: el.dataset.k }) },
    async refresh() { await this.actions.load.call(this) },
    async reload() { await this.actions.load.call(this) },        // the franchisee filter changed: fetch that franchisee's latest 150 movements
    async toggleMode() {
      this.set({ mode: this.S.mode === 'ho' ? 'franchise' : 'ho', stock: null, moves: [] })
      await this.actions.load.call(this)
    },
    openSend() { this.set({ send: true, fid: '', rows: [{ product_id: '', qty: '' }], ref: '', serr: '' }) },
    closeSend() { this.set({ send: false }) },
    addRow() { this.set({ rows: [...this.S.rows, { product_id: '', qty: '' }] }) },
    async load() {
      if (this.S.mode === 'ho') {
        const [s, m] = await Promise.all([
          supabase.from('v_tc_stock').select('*'),
          supabase.from('tc_stock_moves').select('*').order('created_at', { ascending: false }).limit(150),
        ])
        if (s.error || m.error) return this.set({ err: errText(s.error || m.error) })
        return this.set({ stock: s.data, moves: m.data })
      }
      let mq = supabase.from('fr_stock_moves').select('*').order('created_at', { ascending: false }).limit(150)
      if (this.S.ff) mq = mq.eq('franchise_id', this.S.ff)
      const [s, m] = await Promise.all([supabase.from('v_fr_stock').select('*'), mq])
      if (s.error || m.error) return this.set({ err: errText(s.error || m.error) })
      this.set({ stock: s.data, moves: m.data })
    },
    async save() {
      const S = this.S
      this.set({ serr: '' })
      if (S.mode !== 'ho' && !S.fid) return this.set({ serr: 'Choose the franchisee.' })
      const ok = S.rows.filter((r) => r.product_id && Number(r.qty) > 0)
      if (!ok.length) return this.set({ serr: 'Add at least one product with a quantity.' })
      this.set({ busy: true })
      const { error } = S.mode === 'ho'
        ? await supabase.from('tc_stock_moves').insert(ok.map((r) => ({ product_id: r.product_id, qty: Number(r.qty), kind: 'received', ref_no: S.ref.trim() || null, note: 'Added by Head Office' })))
        : await supabase.from('fr_stock_moves').insert(ok.map((r) => ({ franchise_id: S.fid, product_id: r.product_id, qty: Number(r.qty), kind: 'received', ref_no: S.ref.trim() || null, note: 'Dispatched by Head Office' })))
      this.set({ busy: false })
      if (error) return this.set({ serr: errText(error) })
      await this.actions.load.call(this)
      this.set({ send: false })
      toast(S.mode === 'ho' ? 'Stock added to Head Office' : 'Stock added to the franchisee')
    },
  },
}
