import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../ui.js'
import { fmtINR, fmtDate } from '../../lib.js'
import { monthStart, monthName, itemsText } from '../../fr.js'
import { SalePills, saleForm, saleSheet } from './parts.js'

const FILTERS = [['all', 'All'], ['deliver', 'To deliver'], ['install', 'To install'], ['unpaid', 'Money due'], ['done', 'Complete'], ['cancelled', 'Cancelled']]
const test = {
  all: (s) => s.status === 'active',
  deliver: (s) => s.status === 'active' && s.delivery_status !== 'delivered',
  install: (s) => s.status === 'active' && s.needs_install && s.delivery_status === 'delivered' && s.installation_status !== 'installed',
  unpaid: (s) => s.status === 'active' && s.payment_status !== 'paid',
  done: (s) => s.status === 'active' && s.payment_status === 'paid' && s.delivery_status === 'delivered' && (!s.needs_install || s.installation_status === 'installed'),
  cancelled: (s) => s.status === 'cancelled',
}

export default {
  state: (ctx) => ({ rows: null, items: [], err: '', f: ctx.route.filter || 'all', q: '', open: null, newSale: false, busy: false }),
  widgets: { saleform: saleForm, sale: saleSheet },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { fr, byId } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading your sales…')
    const month = monthStart()
    const itemsOf = {}
    S.items.forEach((i) => (itemsOf[i.sale_id] = itemsOf[i.sale_id] || []).push(i))
    const q = S.q.trim().toLowerCase()
    const list = S.rows.filter((s) => test[S.f](s) && (!q || `${s.customer_name} ${s.place} ${s.invoice_no}`.toLowerCase().includes(q)))
    const active = S.rows.filter((s) => s.status === 'active')
    const thisMonth = active.filter((s) => s.sale_date >= month)
    const collect = active.reduce((a, s) => a + Number(s.total) - Number(s.amount_received), 0)
    const allTime = active.reduce((a, s) => a + Number(s.total), 0)
    const toDeliver = S.rows.filter(test.deliver).length
    return html`${PageHead({ label: 'Sales history', title: 'Sales', sub: 'Every sale you have closed, with delivery, installation and payment.',
        actions: html`<button class="btn" ${S.busy ? raw('disabled') : ''} data-act="download">${Icon('download', 18)} ${S.busy ? 'Preparing…' : 'Excel'}</button>
          <button class="btn primary" data-act="newSale">${Icon('plus', 18)} Record a sale</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: monthName(month), value: fmtINR(thisMonth.reduce((a, s) => a + Number(s.total), 0)), sub: `${thisMonth.length} sale${thisMonth.length === 1 ? '' : 's'}` })}
        ${Stat({ label: 'All time', value: fmtINR(allTime), sub: `${active.length} sales` })}
        ${Stat({ label: 'To deliver', value: toDeliver, tone: toDeliver ? 'warn' : '' })}
        ${Stat({ label: 'Money to collect', value: fmtINR(collect), tone: collect ? 'warn' : '' })}
      </div>
      <div class="toolbar"><div class="search">${Icon('search', 18)}<input placeholder="Search customer, place, invoice" data-bind="q" data-live value="${S.q}"></div></div>
      <div class="chips" style="margin-bottom:12px">${FILTERS.map(([k, l]) => html`<button class="chip${S.f === k ? ' on' : ''}" aria-pressed="${S.f === k}" data-act="filter" data-k="${k}">${l} (${S.rows.filter(test[k]).length})</button>`)}</div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No sales in this view.' : 'No sales yet. Record your first sale when a customer says yes.') : html`<ul class="list">${list.map((s) => html`<li data-key="${s.id}">
        <button class="item col" data-act="open" data-id="${s.id}">
          <div class="row" style="width:100%"><div class="grow"><div class="title">${s.customer_name}</div>
            <div class="muted small">${fmtDate(s.sale_date)}${s.place ? ` · ${s.place}` : ''}${s.invoice_no ? ` · ${s.invoice_no}` : ''}</div></div><b>${fmtINR(s.total)}</b></div>
          <div class="muted small">${itemsText(itemsOf[s.id], byId)}</div>
          ${SalePills(s)}
        </button></li>`)}</ul>`}
      ${S.open ? widget(this, 'sale', S.open.id, { sale: S.open }) : ''}
      ${S.newSale ? widget(this, 'saleform', 'new', { lead: null }) : ''}`
  },
  actions: {
    filter(el) { this.set({ f: el.dataset.k }) },
    open(el) { this.set({ open: this.S.rows.find((s) => s.id === el.dataset.id) }) },
    newSale() { this.set({ newSale: true }) },
    saleClose() { this.set({ open: null, newSale: false }) },
    async saleChanged() { await this.actions.load.call(this); await this.ctx.data.refresh() },
    async load() {
      const [s, i] = await Promise.all([
        supabase.from('fr_sales').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        supabase.from('fr_sale_items').select('*'),
      ])
      if (s.error || i.error) return this.set({ err: errText(s.error || i.error) })
      this.set({ rows: s.data, items: i.data })
    },
    async download() {
      this.set({ busy: true })
      try {
        const { downloadFranchiseReport } = await import('../../frReport.js')
        const { fr } = this.ctx.data
        await downloadFranchiseReport({ franchiseIds: [fr.id], title: fr.business_name })
      } catch (e) { toast(errText(e), 'bad') } finally { this.set({ busy: false }) }
    },
  },
}
