/* Finance: every sales bill from the franchise and telecaller dashboards, sorted together. Read-only - an accountant does not
   create or change a bill here, just looks it up, prints it or downloads its PDF. A scrap-purchase visit never shows up here;
   that is a field expense, not a sales invoice. */
import { html, raw, supabase, errText } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Stat, SectionHead } from '../../ui.js'
import { fmtDate, fmtINR } from '../../lib.js'
import { loadProducts, loadDistricts } from '../../fr.js'
import { downloadInvoicePdf, printSaleInvoice } from '../fr/parts.js?v=20261029-1'

const PAYMENT = { pending: 'Unpaid', partial: 'Part paid', paid: 'Paid' }
const CUSTOMER = { B2B: 'B2B', B2C: 'B2C', B2G: 'B2G' }
const SOURCE = { franchise: 'Franchise', telecaller: 'Telecaller' }
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`

function invoiceDetail(sale, items, S, receipts, downloading) {
  const { byId, districts } = S
  const due = Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0))
  const district = (districts.find((d) => d.id === sale.district_id) || {}).name
  return html`<section class="detail">
    ${SectionHead({ title: 'Invoice details' })}
    <div class="row wrap" style="justify-content:flex-end;margin:8px 0">
      <button class="btn primary" ${!items ? raw('disabled') : ''} data-act="printInvoice">Print invoice</button>
      <button class="btn" ${downloading ? raw('disabled') : ''} data-act="downloadPdf">${Icon('download', 18)} ${downloading ? 'Preparing…' : 'Download PDF'}</button></div>
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Invoice number</span><b>${sale.invoice_no || 'Not recorded'}</b></div>
      <div class="summary-row"><span>Source</span><span>${SOURCE[sale.source] || sale.source}</span></div>
      <div class="summary-row"><span>Billed by</span><span>${sale.seller_name || '—'}</span></div>
      <div class="summary-row"><span>Sale date</span><span>${fmtDate(sale.sale_date)}</span></div>
      <div class="summary-row"><span>Customer</span><span>${sale.customer_name || '—'}</span></div>
      <div class="summary-row"><span>Customer type</span><span>${CUSTOMER[sale.customer_type] || sale.customer_type || '—'}</span></div>
      <div class="summary-row"><span>Contact</span><span>${[sale.phone, sale.place, district].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Payment</span><span>${PAYMENT[sale.payment_status] || sale.payment_status || '—'}</span></div>
      ${sale.status === 'cancelled' ? html`<div class="summary-row"><span>Status</span><span>Cancelled</span></div>` : ''}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Item name</th><th>HSN/SAC</th><th class="num">Quantity</th><th>Unit</th><th class="num">Price/Unit</th><th class="num">GST</th><th class="num">Amount</th></tr></thead>
      <tbody>${!items ? html`<tr><td colspan="7">${Loading('Loading items…')}</td></tr>` : items.map((i) => html`<tr><td>${byId[i.product_id]?.name || 'Product'}</td><td>${i.hsn_sac || '—'}</td><td class="num">${i.qty}</td><td>${byId[i.product_id]?.unit || 'unit'}</td><td class="num">${fmtINR(i.unit_price)}</td><td class="num">${Number(i.gst_percent || 0)}%</td><td class="num">${fmtINR(Number(i.line_total || 0) + Number(i.gst_amount || 0))}</td></tr>`)}
        ${items && !items.length ? html`<tr><td colspan="7" class="muted">No item lines recorded.</td></tr>` : ''}</tbody>
    </table></div>
    ${items ? html`<div class="summary" style="margin-top:12px">
      <div class="summary-row"><span>Subtotal</span><span>${fmtINR(items.reduce((sum, i) => sum + Number(i.line_total || 0), 0))}</span></div>
      <div class="summary-row"><span>GST</span><span>${fmtINR(items.reduce((sum, i) => sum + Number(i.gst_amount || 0), 0))}</span></div>
      <div class="summary-row"><span>Invoice total</span><b>${fmtINR(sale.total)}</b></div>
      <div class="summary-row"><span>Received</span><span>${fmtINR(sale.amount_received)}</span></div>
      <div class="summary-row"><span>Balance due</span><b>${fmtINR(due)}</b></div>
    </div>` : ''}
    ${receipts && receipts.length ? html`<section style="margin-top:18px">${SectionHead({ title: 'Payment history' })}
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>
        <tbody>${receipts.map((r) => html`<tr><td>${fmtDate(r.received_at)}</td><td>${r.method}</td><td>${r.reference || '—'}</td><td class="num">${fmtINR(r.amount)}</td></tr>`)}</tbody></table></div>
    </section>` : ''}
  </section>`
}

export default {
  state: { rows: null, byId: {}, districts: [], company: null, err: '', q: '', status: '', source: '',
    selected: null, selItems: null, selReceipts: null, dl: false },
  async init() { await this.actions.load.call(this) },
  view(S) {
    if (S.err && !S.rows) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading bills…')
    const query = S.q.trim().toLowerCase()
    const list = S.rows.filter((s) => (!S.status || s.payment_status === S.status) && (!S.source || s.source === S.source)
      && (!query || `${s.invoice_no || ''} ${s.customer_name || ''} ${s.phone || ''} ${s.place || ''} ${s.seller_name || ''}`.toLowerCase().includes(query)))
    const live = S.rows.filter((s) => s.status !== 'cancelled')
    const received = live.reduce((a, s) => a + Number(s.amount_received || 0), 0)
    const due = live.reduce((a, s) => a + Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0)), 0)
    return html`${PageHead({ label: 'Finance', title: 'Bills', sub: 'Every sales bill from the franchise and telecaller dashboards, sorted together.' })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Bills', value: S.rows.length, sub: `${live.length} active` })}
        ${Stat({ label: 'Received', value: fmtINR(received), sub: 'Active bills' })}
        ${Stat({ label: 'Balance due', value: fmtINR(due), tone: due ? 'warn' : 'ok', sub: 'Active bills' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search invoice, customer, seller" aria-label="Search bills" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="source" data-live aria-label="Source"><option value="">Any source</option>${Object.entries(SOURCE).map(([k, v]) => opt(k, S.source, v))}</select>
        <select data-bind="status" data-live aria-label="Payment status"><option value="">Any payment status</option>${Object.entries(PAYMENT).map(([k, v]) => opt(k, S.status, v))}</select>
      </div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No bills match these filters.' : 'No bills created yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Invoice</th><th>Date</th><th>Source</th><th>Billed by</th><th>Customer</th><th class="num">Total</th><th class="num">Due</th><th>Payment</th></tr></thead>
        <tbody>${list.map((s) => html`<tr data-act="select" data-id="${s.id}" data-source="${s.source}" aria-selected="${S.selected && S.selected.id === s.id && S.selected.source === s.source}" style="cursor:pointer${S.selected && S.selected.id === s.id && S.selected.source === s.source ? ';background:var(--wash)' : ''}">
          <td><b>${s.invoice_no || 'No invoice no.'}</b></td><td>${fmtDate(s.sale_date)}</td>
          <td>${SOURCE[s.source] || s.source}</td><td>${s.seller_name || '—'}</td>
          <td>${s.customer_name || '—'}${s.place ? html`<div class="muted small">${s.place}</div>` : ''}</td>
          <td class="num"><b>${fmtINR(s.total)}</b></td><td class="num">${s.status === 'cancelled' ? '—' : fmtINR(Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0)))}</td>
          <td>${s.status === 'cancelled' ? 'Cancelled' : PAYMENT[s.payment_status] || '—'}</td></tr>`)}</tbody></table></div>`}
      ${S.selected ? invoiceDetail(S.selected, S.selItems, S, S.selReceipts, S.dl) : ''}`
  },
  actions: {
    async load() {
      const [bills, products, districts] = await Promise.all([
        supabase.from('v_finance_bills').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        loadProducts(), loadDistricts(),
      ])
      if (bills.error) return this.set({ err: errText(bills.error) })
      this.set({ rows: bills.data, byId: products.byId, districts, err: '' })
    },
    select(el) {
      const row = this.S.rows.find((r) => r.id === el.dataset.id && r.source === el.dataset.source)
      this.set({ selected: row, selItems: null, selReceipts: null })
      this.actions.loadDetail.call(this, row)
    },
    async loadDetail(row) {
      const itemsTable = row.source === 'franchise' ? 'fr_sale_items' : 'tc_sale_items'
      const receiptsTable = row.source === 'franchise' ? 'fr_payment_receipts' : 'tc_payment_receipts'
      const [items, receipts, company] = await Promise.all([
        supabase.from(itemsTable).select('*').eq('sale_id', row.id),
        supabase.from(receiptsTable).select('*').eq('sale_id', row.id).order('received_at', { ascending: false }),
        this.S.company ? Promise.resolve({ data: this.S.company }) : supabase.from('fr_company_settings').select('*').eq('id', 1).maybeSingle(),
      ])
      if (this.S.selected !== row) return
      this.set({ selItems: items.data || [], selReceipts: receipts.data || [], company: company.data || this.S.company })
    },
    printInvoice() {
      if (this.S.selItems) printSaleInvoice(this.S.selected, this.S.selItems, { data: { byId: this.S.byId, districts: this.S.districts, company: this.S.company } })
    },
    async downloadPdf() {
      if (this.S.selected) await downloadInvoicePdf(this, this.S.selected)
    },
  },
}
