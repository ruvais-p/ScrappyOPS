/* Head Office: read-only register of invoices entered against franchise sales. */
import { html, raw, supabase, errText, widget } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat, SectionHead } from '../../../ui.js'
import { fmtDate, fmtINR } from '../../../lib.js'
import { itemsText } from '../../../fr.js'
import { Sheet } from '../../../kit.js'
import { printSaleInvoice, saleForm } from '../../fr/parts.js?v=20261027-1'

const PAYMENT = { pending: 'Unpaid', unpaid: 'Unpaid', partial: 'Part paid', paid: 'Paid' }
const DELIVERY = { pending: 'To deliver', dispatched: 'Dispatched', delivered: 'Delivered' }
const INSTALL = { pending: 'To install', scheduled: 'Installation booked', installed: 'Installed' }
const CUSTOMER = { B2B: 'B2B', B2C: 'B2C', B2G: 'B2G' }

const METHOD = { cash: 'Cash', upi: 'UPI', bank_transfer: 'Bank transfer', cheque: 'Cheque', card: 'Card', other: 'Other' }

function invoiceDetail(sale, items, ctx, fname, receipts) {
  const { byId } = ctx.data
  const due = Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0))
  const lines = items.filter((i) => i.sale_id === sale.id)
  return html`<section class="detail">
    ${SectionHead({ title: 'Invoice details' })}
    <div class="row wrap" style="justify-content:flex-end;margin:8px 0">
      ${sale.status === 'active' && due > 0 ? html`<button class="btn" data-act="recordPayment">${Icon('plus', 18)} Settle due</button>` : ''}
      <button class="btn primary" data-act="printInvoice">${Icon('download', 18)} Print invoice</button></div>
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
      <thead><tr><th>Item name</th><th>HSN/SAC</th><th class="num">Quantity</th><th>Unit</th><th class="num">Price/Unit</th><th class="num">GST</th><th class="num">Amount</th></tr></thead>
      <tbody>${lines.map((i) => html`<tr><td>${byId[i.product_id]?.name || 'Product'}</td><td>${i.hsn_sac || '—'}</td><td class="num">${i.qty}</td><td>${byId[i.product_id]?.unit || 'unit'}</td><td class="num">${fmtINR(i.unit_price)}</td><td class="num">${Number(i.gst_percent || 0)}%</td><td class="num">${fmtINR(Number(i.line_total || 0) + Number(i.gst_amount || 0))}</td></tr>`)}
        ${lines.length ? '' : html`<tr><td colspan="7" class="muted">No item lines recorded.</td></tr>`}</tbody>
    </table></div>
    <div class="summary" style="margin-top:12px">
      <div class="summary-row"><span>Subtotal</span><span>${fmtINR(lines.reduce((sum, i) => sum + Number(i.line_total || 0), 0))}</span></div>
      <div class="summary-row"><span>GST</span><span>${fmtINR(lines.reduce((sum, i) => sum + Number(i.gst_amount || 0), 0))}</span></div>
      <div class="summary-row"><span>Invoice total</span><b>${fmtINR(sale.total)}</b></div>
      <div class="summary-row"><span>Received</span><span>${fmtINR(sale.amount_received)}</span></div>
      <div class="summary-row"><span>Balance due</span><b>${fmtINR(due)}</b></div>
    </div>
    ${receipts.length ? html`<section style="margin-top:18px">${SectionHead({ title: 'Payment history' })}
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>
        <tbody>${receipts.map((r) => html`<tr><td>${fmtDate(r.received_at)}</td><td>${METHOD[r.method] || r.method}</td><td>${r.reference || '—'}</td><td class="num">${fmtINR(r.amount)}</td></tr>`)}</tbody></table></div>
    </section>` : ''}
    <p class="muted small">Invoice record created by Head Office or the franchisee.</p>
  </section>`
}

export default {
  state: { rows: null, items: [], receipts: [], stockByFr: {}, err: '', fid: '', status: '', q: '', selected: '', create: false, payment: null, payForm: { amount: '', method: 'cash', reference: '' }, payErr: '' },
  widgets: { createBill: saleForm },
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
    return html`${PageHead({ label: 'Franchise', title: 'Billing', sub: 'Create and review franchise sales bills and payment balances.', actions: html`<button class="btn primary" data-act="openCreate" ${!S.stockReady ? raw('disabled') : ''}>${Icon('plus', 18)} Create bill</button>` })}
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
      ${selected ? invoiceDetail(selected, S.items, ctx, fname, S.receipts.filter((r) => r.sale_id === selected.id)) : ''}
      ${S.payment && selected ? Sheet({ title: 'Record payment', close: 'closePayment', body: html`
        <p class="muted">Balance due: <b>${fmtINR(Math.max(0, Number(selected.total || 0) - Number(selected.amount_received || 0)))}</b></p>
        <label>Amount received (₹)<input type="number" min="0.01" step="0.01" max="${Math.max(0, Number(selected.total || 0) - Number(selected.amount_received || 0))}" inputmode="decimal" data-bind="payForm.amount" value="${S.payForm.amount}"></label>
        <label>Payment method<select data-bind="payForm.method">${Object.entries(METHOD).map(([k, v]) => html`<option value="${k}" ${S.payForm.method === k ? raw('selected') : ''}>${v}</option>`)}</select></label>
        <label>Reference (optional)<input data-bind="payForm.reference" value="${S.payForm.reference}" placeholder="Transaction ID, cheque no., etc."></label>
        ${S.payErr ? html`<p class="error">${S.payErr}</p>` : ''}
        <button class="btn primary block" data-act="savePayment" ${S.payBusy ? raw('disabled') : ''}>${S.payBusy ? 'Saving…' : 'Record payment'}</button>` }) : ''}
      ${S.create ? widget(this, 'createBill', 'new', { ho: true, frs, stockByFr: S.stockByFr }) : ''}`
  },
  actions: {
    select(el) { this.set({ selected: el.dataset.id }) },
    openCreate() { this.set({ create: true }) },
    saleClose() { this.set({ create: false }) },
    recordPayment() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected)
      const due = sale ? Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0)) : 0
      this.set({ payment: true, payForm: { amount: due ? due.toFixed(2) : '', method: 'cash', reference: '' }, payErr: '' })
    },
    closePayment() { this.set({ payment: null, payErr: '' }) },
    async savePayment() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected), v = this.S.payForm
      const due = sale ? Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0)) : 0
      const amount = Number(v.amount)
      if (!Number.isFinite(amount) || amount <= 0) return this.set({ payErr: 'Enter an amount greater than zero.' })
      if (amount > due) return this.set({ payErr: `Payment cannot exceed the balance due (${fmtINR(due)}).` })
      this.set({ payBusy: true, payErr: '' })
      const { error } = await supabase.rpc('fr_receive_payment', {
        p_sale: sale.id, p_amount: amount, p_method: v.method, p_reference: v.reference.trim(),
      })
      if (error) return this.set({ payBusy: false, payErr: errText(error) })
      this.set({ payment: null, payBusy: false })
      await this.actions.load.call(this)
    },
    async saleChanged() { this.set({ create: false }); await this.actions.load.call(this) },
    printInvoice() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected)
      if (sale) printSaleInvoice(sale, this.S.items.filter((i) => i.sale_id === sale.id), this.ctx)
    },
    async load() {
      const [s, i, stock, receipts] = await Promise.all([
        supabase.from('fr_sales').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        supabase.from('fr_sale_items').select('*'),
        supabase.from('v_fr_stock').select('*'),
        supabase.from('fr_payment_receipts').select('*').order('received_at', { ascending: false }),
      ])
      if (s.error || i.error || stock.error || receipts.error) return this.set({ err: errText(s.error || i.error || stock.error || receipts.error) })
      const stockByFr = {}
      for (const row of stock.data) { stockByFr[row.franchise_id] ||= {}; stockByFr[row.franchise_id][row.product_id] = row.on_hand }
      this.set({ rows: s.data, items: i.data, receipts: receipts.data, stockByFr, stockReady: true, err: '' })
    },
  },
}
