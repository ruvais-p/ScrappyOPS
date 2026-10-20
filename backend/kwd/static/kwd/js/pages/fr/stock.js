/* The franchisee's stock: what they hold, and recording stock received / damaged / counted. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead, SectionHead, Stat } from '../../ui.js'
import { fmtDate, fmtTime } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'
import { MOVE_KIND } from '../../fr.js'

const LOW = 2
const KINDS = [
  ['received', 'Stock received from Head Office'],
  ['opening', 'Opening stock (what I already had)'],
  ['damaged', 'Damaged or lost'],
  ['returned', 'Returned to Head Office'],
  ['count', 'Stock count correction'],
]

export default {
  state: { rows: null, moves: [], err: '', edit: null, kind: 'received', pid: '', qty: '', ref: '', note: '', busy: false, ferr: '' },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { products, byId, fr } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading your stock…')
    const rows = S.rows
    const active = products.filter((p) => p.is_active)
    const total = active.reduce((a, p) => a + ((rows[p.id] && rows[p.id].on_hand) ?? 0), 0)
    const low = active.filter((p) => rows[p.id] && rows[p.id].on_hand <= LOW)
    const none = active.filter((p) => !rows[p.id])
    const sum = (k) => Object.values(rows).reduce((a, r) => a + r[k], 0)
    return html`${PageHead({ label: 'What you hold', title: 'Stock', sub: 'Sales take units out automatically. Add what you receive, and note anything damaged or counted differently.',
        actions: html`<button class="btn primary" data-act="openEdit">${Icon('plus', 18)} Update stock</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Units in stock', value: total, sub: `${active.length - none.length} of ${active.length} products held` })}
        ${Stat({ label: 'Running low', value: low.length, tone: low.length ? 'warn' : '', sub: `${LOW} or fewer left` })}
        ${Stat({ label: 'Sold so far', value: sum('sold') })}
        ${Stat({ label: 'Received', value: sum('received') })}
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Product</th><th class="num">In stock</th><th class="num">Received</th><th class="num">Sold</th><th class="num">Adjusted</th><th></th></tr></thead>
        <tbody>${active.map((p) => {
          const r = rows[p.id]
          return html`<tr><td><b>${p.name}</b><div class="muted small">${p.code}</div></td>
            <td class="num"><b>${(r && r.on_hand) ?? 0}</b></td><td class="num">${(r && r.received) ?? 0}</td><td class="num">${(r && r.sold) ?? 0}</td>
            <td class="num">${r && r.adjusted ? (r.adjusted > 0 ? `+${r.adjusted}` : r.adjusted) : 0}</td>
            <td>${!r ? html`<span class="pill">Not held</span>` : r.on_hand <= 0 ? html`<span class="pill bad">Out</span>` : r.on_hand <= LOW ? html`<span class="pill warn">Low</span>` : html`<span class="pill ok">OK</span>`}
              ${' '}<button class="btn sm" data-act="openEdit" data-pid="${p.id}">Update</button></td></tr>`
        })}</tbody></table></div>
      <section>
        ${SectionHead({ title: 'Stock history', count: S.moves.length })}
        ${S.moves.length === 0 ? Empty('No stock movements yet.') : html`<ul class="list">${S.moves.map((m) => html`<li><div class="item">
          <div class="grow"><div class="title">${byId[m.product_id] && byId[m.product_id].name}</div>
            <div class="muted small">${MOVE_KIND[m.kind]}${m.ref_no ? ` · ${m.ref_no}` : ''}${m.note ? ` · ${m.note}` : ''}</div></div>
          <div style="text-align:right"><b class="${m.qty > 0 ? 'text-ok' : ''}">${m.qty > 0 ? `+${m.qty}` : m.qty}</b><div class="muted small">${fmtDate(m.created_at)}, ${fmtTime(m.created_at)}</div></div>
        </div></li>`)}</ul>`}
      </section>
      ${S.edit ? form(S, active, rows) : ''}`
  },
  actions: {
    async load() {
      const [v, m] = await Promise.all([
        supabase.from('v_fr_stock').select('*'),
        supabase.from('fr_stock_moves').select('*').order('created_at', { ascending: false }).limit(60),
      ])
      if (v.error || m.error) return this.set({ err: errText(v.error || m.error) })
      this.set({ rows: Object.fromEntries(v.data.map((r) => [r.product_id, r])), moves: m.data })
    },
    openEdit(el) { this.set({ edit: true, kind: 'received', pid: el.dataset.pid || '', qty: '', ref: '', note: '', ferr: '' }) },
    closeEdit() { this.set({ edit: null }) },
    async save() {
      const S = this.S, have = (S.rows[S.pid] && S.rows[S.pid].on_hand) ?? 0
      const needNote = ['damaged', 'returned', 'count'].includes(S.kind)
      this.set({ ferr: '' })
      if (!S.pid) return this.set({ ferr: 'Choose the product.' })
      const n = Number(S.qty)
      if (!Number.isInteger(n) || n < 0 || (S.kind !== 'count' && n === 0)) return this.set({ ferr: S.kind === 'count' ? 'Enter the number you counted.' : 'Enter how many.' })
      if (needNote && S.note.trim().length < 5) return this.set({ ferr: 'Add a short note (at least 5 characters).' })
      let row
      if (S.kind === 'count') {
        if (n === have) return this.set({ ferr: 'That matches what the app already shows. Nothing to correct.' })
        row = { product_id: S.pid, kind: 'count_adjust', qty: n - have, note: S.note.trim() }
      } else {
        if (['damaged', 'returned'].includes(S.kind) && n > have) return this.set({ ferr: `You only have ${have} in stock.` })
        row = { product_id: S.pid, kind: S.kind, qty: n, ref_no: S.ref.trim() || null, note: S.note.trim() || null }
      }
      this.set({ busy: true })
      const { error } = await supabase.from('fr_stock_moves').insert({ franchise_id: this.ctx.data.fr.id, ...row })
      this.set({ busy: false })
      if (error) return this.set({ ferr: errText(error) })
      toast('Stock updated')
      this.set({ edit: null })
      await this.actions.load.call(this)
      await this.ctx.data.refresh()
    },
  },
}

function form(S, products, rows) {
  const have = (rows[S.pid] && rows[S.pid].on_hand) ?? 0
  const needNote = ['damaged', 'returned', 'count'].includes(S.kind)
  const diff = Number(S.qty) - have
  return Sheet({ title: 'Update stock', close: 'closeEdit', body: html`
    <label>What happened<select data-bind="kind" data-live>${KINDS.map(([k, l]) => html`<option value="${k}" ${S.kind === k ? raw('selected') : ''}>${l}</option>`)}</select></label>
    <label>Product<select data-bind="pid" data-live><option value="">Choose…</option>${products.map((p) => html`<option value="${p.id}" ${S.pid === p.id ? raw('selected') : ''}>${p.name} · ${(rows[p.id] && rows[p.id].on_hand) ?? 0} in stock</option>`)}</select></label>
    <label>${S.kind === 'count' ? 'Number you counted on the shelf' : 'Quantity'}<input type="number" min="0" inputmode="numeric" data-bind="qty" data-live value="${S.qty}"></label>
    ${S.kind === 'count' && S.pid && S.qty !== '' ? html`<p class="muted small">The app shows ${have}. This records a correction of ${diff > 0 ? '+' : ''}${diff}. Head Office can see it.</p>` : ''}
    ${S.kind === 'received' ? html`<label>Challan / dispatch no. (optional)<input data-bind="ref" value="${S.ref}"></label>` : ''}
    <label>Note${needNote ? '' : ' (optional)'}<input data-bind="note" value="${S.note}" placeholder="${S.kind === 'damaged' ? 'What happened' : S.kind === 'count' ? 'Why the count differs' : ''}"></label>
    ${errLine(S.ferr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Save'}</button>` })
}
