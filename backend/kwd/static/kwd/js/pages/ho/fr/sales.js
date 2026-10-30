/* Head Office: every franchise sale; open one to flag or cancel it. */
import { html, raw, supabase, errText, toast, widget } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../../ui.js'
import { fmtINR, fmtDate } from '../../../lib.js'
import { monthStart, monthName, itemsText } from '../../../fr.js'
import { SalePills, saleSheet } from '../../fr/parts.js?v=20261029-1'

const FILTERS = [['all', 'All'], ['flagged', 'Flagged'], ['deliver', 'To deliver'], ['install', 'To install'], ['unpaid', 'Money due'], ['cancelled', 'Cancelled']]
const test = {
  all: (s) => s.status === 'active',
  flagged: (s) => s.status === 'active' && (s.ho_flag || (s.flags || []).length > 0),
  deliver: (s) => s.status === 'active' && s.delivery_status !== 'delivered',
  install: (s) => s.status === 'active' && s.needs_install && s.delivery_status === 'delivered' && s.installation_status !== 'installed',
  unpaid: (s) => s.status === 'active' && s.payment_status !== 'paid',
  cancelled: (s) => s.status === 'cancelled',
}

export default {
  state: (ctx) => ({ rows: null, items: [], err: '', fid: ctx.route.franchiseId || '', f: 'all', q: '', open: null, busy: false }),
  widgets: { sale: saleSheet },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { frs, byId } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading sales…')
    const fname = (id) => (frs.find((x) => x.id === id) || {}).business_name || '—'
    const itemsOf = {}
    S.items.forEach((i) => (itemsOf[i.sale_id] = itemsOf[i.sale_id] || []).push(i))
    const scoped = S.rows.filter((s) => !S.fid || s.franchise_id === S.fid)
    const q = S.q.trim().toLowerCase()
    const list = scoped.filter((s) => test[S.f](s) && (!q || `${s.customer_name} ${s.place} ${s.invoice_no} ${fname(s.franchise_id)}`.toLowerCase().includes(q)))
    const live = scoped.filter(test.all), month = monthStart(), mo = live.filter((s) => s.sale_date >= month)
    const nDel = scoped.filter(test.deliver).length, nFlag = scoped.filter(test.flagged).length
    return html`${PageHead({ label: 'Franchise', title: 'Sales', sub: 'Every franchise sale with its delivery, installation and payment. Open one to flag it or cancel it.',
        actions: html`<button class="btn" ${S.busy ? raw('disabled') : ''} data-act="download">${Icon('download', 18)} ${S.busy ? 'Preparing…' : 'Excel'}</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: monthName(month), value: fmtINR(mo.reduce((a, s) => a + Number(s.total), 0)), sub: `${mo.length} sales` })}
        ${Stat({ label: 'All time', value: fmtINR(live.reduce((a, s) => a + Number(s.total), 0)), sub: `${live.length} sales` })}
        ${Stat({ label: 'To deliver / install', value: `${nDel} / ${scoped.filter(test.install).length}`, tone: nDel ? 'warn' : '' })}
        ${Stat({ label: 'Flagged', value: nFlag, tone: nFlag ? 'warn' : '' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search customer, place, invoice" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="fid" data-live aria-label="Franchisee"><option value="">All franchisees</option>${frs.map((x) => html`<option value="${x.id}" ${S.fid === x.id ? raw('selected') : ''}>${x.business_name}</option>`)}</select>
      </div>
      <div class="chips" style="margin-bottom:12px">${FILTERS.map(([k, l]) => html`<button class="chip${S.f === k ? ' on' : ''}" aria-pressed="${S.f === k}" data-act="filter" data-k="${k}">${l} (${scoped.filter(test[k]).length})</button>`)}</div>
      ${list.length === 0 ? Empty('No sales in this view.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>Franchisee</th><th>Customer</th><th>Products</th><th class="num">Total</th><th>Status</th></tr></thead>
        <tbody>${list.map((s) => html`<tr data-act="open" data-id="${s.id}" style="cursor:pointer">
          <td>${fmtDate(s.sale_date)}</td><td>${fname(s.franchise_id)}</td>
          <td><b>${s.customer_name}</b><div class="muted small">${s.place || ''}${s.invoice_no ? ` · ${s.invoice_no}` : ''}</div></td>
          <td style="white-space:normal;max-width:260px">${itemsText(itemsOf[s.id], byId)}</td>
          <td class="num"><b>${fmtINR(s.total)}</b>${Number(s.amount_received) < Number(s.total) && s.status === 'active' ? html`<div class="muted small">${fmtINR(s.amount_received)} received</div>` : ''}</td>
          <td style="white-space:normal">${SalePills(s)}</td></tr>`)}</tbody></table></div>`}
      ${S.open ? widget(this, 'sale', S.open.id, { sale: S.open, ho: true }) : ''}`
  },
  actions: {
    filter(el) { this.set({ f: el.dataset.k }) },
    open(el) { this.set({ open: this.S.rows.find((s) => s.id === el.dataset.id) }) },
    saleClose() { this.set({ open: null }) },
    saleChanged() { return this.actions.load.call(this) },
    async load() {
      const [s, i] = await Promise.all([
        supabase.from('fr_sales').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        supabase.from('fr_sale_items').select('*'),
      ])
      if (s.error || i.error) return this.set({ err: errText(s.error || i.error) })
      this.set({ rows: s.data, items: i.data })
    },
    async download() {
      const S = this.S, { frs } = this.ctx.data
      this.set({ busy: true })
      try {
        const { downloadFranchiseReport } = await import('../../../frReport.js')
        const f = frs.find((x) => x.id === S.fid)
        await downloadFranchiseReport({ franchiseIds: S.fid ? [S.fid] : null, title: f ? f.business_name : 'All franchisees' })
      } catch (e) { toast(errText(e), 'bad') } finally { this.set({ busy: false }) }
    },
  },
}
