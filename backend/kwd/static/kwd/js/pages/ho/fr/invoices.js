/* Head Office: read-only register of invoices entered against franchise sales. */
import { html, raw, supabase, errText } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat, SectionHead } from '../../../ui.js'
import { fmtDate, fmtINR } from '../../../lib.js'
import { itemsText } from '../../../fr.js'
import { printSaleInvoice } from '../../fr/parts.js'

const PAYMENT = { unpaid: 'Unpaid', partial: 'Part paid', paid: 'Paid' }
const DELIVERY = { pending: 'To deliver', dispatched: 'Dispatched', delivered: 'Delivered' }
const INSTALL = { pending: 'To install', scheduled: 'Installation booked', installed: 'Installed' }
const CUSTOMER = { private: 'Private', lsgd: 'LSGD', institution: 'Institution', business: 'Business' }

function invoiceDetail(sale, items, ctx, fname) {
  const { byId } = ctx.data
  const due = Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0))
  const lines = items.filter((i) => i.sale_id === sale.id)
  return html`<section class="detail">
    ${SectionHead({ title: 'Invoice details' })}
    <div class="row" style="justify-content:flex-end;margin:8px 0"><button class="btn primary" data-act="printInvoice">${Icon('download', 18)} Print invoice</button></div>
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Invoice number</span><b>${sale.invoice_no || 'Not recorded'}</b></div>
      <div class="summary-row"><span>Sale date</span><span>${fmtDate(sale.sale_date)}</span></div>
      <div class="summary-row"><span>Franchisee</span><span>${fname(sale.franchise_id)}</span></div>
      <div class="summary-row"><span>Customer</span><span>${sale.customer_name || '—'}</span></div>
      <div class="summary-row"><span>Customer type</span><span>${CUSTOMER[sale.customer_type] || sale.customer_type || '—'}</span></div>
      <div class="summary-row"><span>Contact</span><span>${[sale.phone, sale.place].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Payment</span><span>${PAYMENT[sale.payment_status] || sale.payment_status || '—'}</span></div>
      <div class="summary-row"><span>Delivery</span><span>${DELIVERY[sale.delivery_status] || sale.delivery_status || '—'}</span></div>
      ${sale.needs_install ? html`<div class="summary-row"><span>Installation</span><span>${INSTALL[sale.installation_status] || sale.installation_status || '—'}</span></div>` : ''}
      ${sale.status === 'cancelled' ? html`<div class="summary-row"><span>Sale status</span><span>Cancelled${sale.cancel_reason ? ` · ${sale.cancel_reason}` : ''}</span></div>` : ''}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Product</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Line total</th></tr></thead>
      <tbody>${lines.map((i) => html`<tr><td>${byId[i.product_id]?.name || 'Product'}</td><td class="num">${i.qty}</td><td class="num">${fmtINR(i.unit_price)}</td><td class="num">${fmtINR(i.line_total)}</td></tr>`)}
        ${lines.length ? '' : html`<tr><td colspan="4" class="muted">No item lines recorded.</td></tr>`}</tbody>
    </table></div>
    <div class="summary" style="margin-top:12px">
      <div class="summary-row"><span>Invoice total</span><b>${fmtINR(sale.total)}</b></div>
      <div class="summary-row"><span>Received</span><span>${fmtINR(sale.amount_received)}</span></div>
      <div class="summary-row"><span>Balance due</span><b>${fmtINR(due)}</b></div>
    </div>
    <p class="muted small">Read-only invoice record. The invoice number is entered by the franchisee when the sale is recorded.</p>
  </section>`
}

export default {
  state: { rows: null, items: [], err: '', fid: '', status: '', q: '', selected: '' },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { frs, byId } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading invoices…')
    const fname = (id) => (frs.find((f) => f.id === id) || {}).business_name || '—'
    const query = S.q.trim().toLowerCase()
    const scoped = S.rows.filter((s) => !S.fid || s.franchise_id === S.fid)
    const list = scoped.filter((s) => (!S.status || s.payment_status === S.status)
      && (!query || `${s.invoice_no || ''} ${s.customer_name || ''} ${s.phone || ''} ${s.place || ''} ${fname(s.franchise_id)}`.toLowerCase().includes(query)))
    const live = scoped.filter((s) => s.status === 'active')
    const invoiced = scoped.filter((s) => Boolean(s.invoice_no))
    const received = live.reduce((a, s) => a + Number(s.amount_received || 0), 0)
    const due = live.reduce((a, s) => a + Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0)), 0)
    const selected = S.rows.find((s) => s.id === S.selected)
    const productSummary = (saleId) => itemsText(S.items.filter((i) => i.sale_id === saleId), byId) || '—'
    return html`${PageHead({ label: 'Franchise', title: 'Sales invoices', sub: 'Invoice numbers, customer details and payment balances across franchise sales. View only.' })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Invoices recorded', value: invoiced.length, sub: `of ${scoped.length} sales` })}
        ${Stat({ label: 'Received', value: fmtINR(received), sub: 'Active sales' })}
        ${Stat({ label: 'Balance due', value: fmtINR(due), tone: due ? 'warn' : 'ok', sub: 'Active sales' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search invoice, customer, place" aria-label="Search invoices" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="fid" data-live aria-label="Franchisee"><option value="">All franchisees</option>${frs.map((f) => html`<option value="${f.id}" ${S.fid === f.id ? raw('selected') : ''}>${f.business_name}</option>`)}</select>
        <select data-bind="status" data-live aria-label="Payment status"><option value="">Any payment status</option>${Object.entries(PAYMENT).map(([k, v]) => html`<option value="${k}" ${S.status === k ? raw('selected') : ''}>${v}</option>`)}</select>
      </div>
      ${list.length === 0 ? Empty('No sales invoices match these filters.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Invoice</th><th>Date</th><th>Franchisee</th><th>Customer</th><th>Products</th><th class="num">Total</th><th class="num">Due</th><th>Payment</th></tr></thead>
        <tbody>${list.map((s) => html`<tr data-act="select" data-id="${s.id}" aria-selected="${S.selected === s.id}" style="cursor:pointer${S.selected === s.id ? ';background:var(--wash)' : ''}">
          <td><b>${s.invoice_no || 'No invoice no.'}</b></td><td>${fmtDate(s.sale_date)}</td><td>${fname(s.franchise_id)}</td>
          <td>${s.customer_name || '—'}${s.place ? html`<div class="muted small">${s.place}</div>` : ''}</td>
          <td style="white-space:normal;max-width:240px">${productSummary(s.id)}</td>
          <td class="num"><b>${fmtINR(s.total)}</b></td><td class="num">${s.status === 'active' ? fmtINR(Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0))) : '—'}</td>
          <td>${s.status === 'cancelled' ? 'Cancelled' : PAYMENT[s.payment_status] || '—'}</td></tr>`)}</tbody></table></div>`}
      ${selected ? invoiceDetail(selected, S.items, ctx, fname) : ''}`
  },
  actions: {
    select(el) { this.set({ selected: el.dataset.id }) },
    printInvoice() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected)
      if (sale) printSaleInvoice(sale, this.S.items.filter((i) => i.sale_id === sale.id), this.ctx)
    },
    async load() {
      const [s, i] = await Promise.all([
        supabase.from('fr_sales').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        supabase.from('fr_sale_items').select('*'),
      ])
      if (s.error || i.error) return this.set({ err: errText(s.error || i.error) })
      this.set({ rows: s.data, items: i.data, err: '' })
    },
  },
}
