/* Telecaller: bill a customer directly - same tax invoice as the franchise module, picked from the shared product
   catalogue. No stock is tracked here and no product can be added; that stays with Head Office. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Stat, SectionHead } from '../../ui.js'
import { fmtDate, fmtINR, istDate, addDays } from '../../lib.js'
import { loadProducts, loadDistricts, itemsText } from '../../fr.js'
import { Sheet, errLine } from '../../kit.js'
import { downloadInvoicePdf, printSaleInvoice } from '../fr/parts.js?v=20261029-1'

const PAYMENT = { pending: 'Unpaid', partial: 'Part paid', paid: 'Paid' }
const CUSTOMER = { B2B: 'B2B', B2C: 'B2C', B2G: 'B2G' }
const METHOD = { cash: 'Cash', upi: 'UPI', bank_transfer: 'Bank transfer', cheque: 'Cheque', card: 'Card', other: 'Other' }

const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`
const round2 = (n) => Math.round(n * 100) / 100
const typedPrice = (x) => Number(x.unit_price) || 0
const gstFactor = (x) => 1 + (Number(x.gst_percent) || 0) / 100
const exPrice = (x) => (x.incl ? typedPrice(x) / gstFactor(x) : typedPrice(x))
const inclPrice = (x) => (x.incl ? typedPrice(x) : typedPrice(x) * gstFactor(x))
const lineTotal = (x) => (Number(x.qty) || 0) * inclPrice(x)
const emptyItem = () => ({ product_id: '', hsn_sac: '', qty: 1, unit_price: '', gst_percent: 0, incl: false })
const emptyForm = () => ({ customer_name: '', customer_type: 'B2C', phone: '', district_id: '', place: '', sale_date: istDate(), received: '' })

function billForm(S) {
  const { products, byId, districts } = S, f = S.f, items = S.items2
  const total = items.reduce((a, x) => a + lineTotal(x), 0)
  return Sheet({ title: 'Create bill', close: 'closeCreate', body: html`
    <label>Customer name<input data-bind="f.customer_name" value="${f.customer_name}"></label>
    <div class="grid2">
      <label>Customer type<select data-bind="f.customer_type">${Object.entries(CUSTOMER).map(([k, v]) => opt(k, f.customer_type, v))}</select></label>
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="f.phone" value="${f.phone}" placeholder="10 digits"></label>
    </div>
    <div class="grid2">
      <label>District<select data-bind="f.district_id"><option value="">Choose…</option>${districts.map((d) => opt(d.id, f.district_id, d.name))}</select></label>
      <label>Place / address<input data-bind="f.place" value="${f.place}"></label>
    </div>
    <div class="field-label">Products sold</div>
    ${items.map((x, i) => {
      const p = byId[x.product_id]
      return html`<div class="subcard" style="margin-bottom:10px" data-key="item${i}">
        <label>Product<select data-bind="items2.${i}.product_id" data-change="pickProduct" data-i="${i}">
          <option value="">Choose…</option>
          ${products.filter((q) => q.is_active).map((q) => opt(q.id, x.product_id, q.name))}</select></label>
        <div class="grid2">
          <label>HSN/SAC<input data-bind="items2.${i}.hsn_sac" value="${x.hsn_sac || ''}" placeholder="Enter HSN/SAC"></label>
          <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="items2.${i}.qty" data-live value="${x.qty}"></label>
          <label>Unit<input value="${p ? p.unit || 'unit' : '—'}" disabled></label>
          <label>Price/Unit ${x.incl ? 'with GST' : 'without GST'} (₹)<input type="number" min="0" inputmode="decimal" data-bind="items2.${i}.unit_price" data-live value="${x.unit_price}"></label>
          <label>GST (%)<input type="number" min="0" max="100" step="0.01" inputmode="decimal" data-bind="items2.${i}.gst_percent" data-live value="${x.gst_percent ?? 0}"></label>
        </div>
        <div class="row wrap" style="gap:10px;margin-bottom:6px">
          <div class="seg" role="group" aria-label="The price you typed is"><button class="${x.incl ? '' : 'on'}" data-act="priceMode" data-i="${i}" data-m="excl">Without GST</button><button class="${x.incl ? 'on' : ''}" data-act="priceMode" data-i="${i}" data-m="incl">With GST</button></div>
          <span class="muted small grow">${typedPrice(x) > 0 ? `Without GST ${fmtINR(exPrice(x))} · With GST ${fmtINR(inclPrice(x))} per unit` : 'Type the price with or without GST'}</span>
        </div>
        <div class="row">
          <span class="muted small grow">${p && p.list_price ? `List price ${fmtINR(p.list_price)} without GST` : ''} · line total ${fmtINR(lineTotal(x))}</span>
          ${items.length > 1 ? html`<button class="btn sm" data-act="removeItem" data-i="${i}">Remove</button>` : ''}
        </div>
      </div>`
    })}
    <button class="btn sm" data-act="addItem">${Icon('plus', 16)} Add another product</button>
    <div class="summary" style="margin:14px 0"><div class="summary-row"><span>Total</span><span><b>${fmtINR(total)}</b></span></div></div>
    <div class="grid2">
      <label>Money received now (₹)<input type="number" min="0" inputmode="decimal" data-bind="f.received" value="${f.received}" placeholder="0"></label>
      <label>Sale date<input type="date" data-bind="f.sale_date" data-live value="${f.sale_date}" min="${addDays(istDate(), -7)}" max="${istDate()}"></label>
    </div>
    ${f.sale_date < istDate() ? html`<p class="muted small">A sale dated before today is marked "entered for an earlier date".</p>` : ''}
    ${errLine(S.cErr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="createBill">${S.busy ? 'Saving…' : 'Create bill'}</button>` })
}

function invoiceDetail(sale, items, S, receipts, downloading = false) {
  const { byId, districts } = S
  const due = Math.max(0, Number(sale.total || 0) - Number(sale.amount_received || 0))
  const district = (districts.find((d) => d.id === sale.district_id) || {}).name
  return html`<section class="detail">
    ${SectionHead({ title: 'Invoice details' })}
    <div class="row wrap" style="justify-content:flex-end;margin:8px 0">
      ${sale.status === 'active' && due > 0 ? html`<button class="btn" data-act="recordPayment">${Icon('plus', 18)} Settle due</button>` : ''}
      <button class="btn primary" data-act="printInvoice">Print invoice</button>
      <button class="btn" ${downloading ? raw('disabled') : ''} data-act="downloadPdf">${Icon('download', 18)} ${downloading ? 'Preparing…' : 'Download PDF'}</button></div>
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Invoice number</span><b>${sale.invoice_no || 'Not recorded'}</b></div>
      <div class="summary-row"><span>Sale date</span><span>${fmtDate(sale.sale_date)}</span></div>
      <div class="summary-row"><span>Customer</span><span>${sale.customer_name || '—'}</span></div>
      <div class="summary-row"><span>Customer type</span><span>${CUSTOMER[sale.customer_type] || sale.customer_type || '—'}</span></div>
      <div class="summary-row"><span>Contact</span><span>${[sale.phone, sale.place, district].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Payment</span><span>${PAYMENT[sale.payment_status] || sale.payment_status || '—'}</span></div>
      ${sale.status === 'cancelled' ? html`<div class="summary-row"><span>Status</span><span>Cancelled${sale.cancel_reason ? ` · ${sale.cancel_reason}` : ''}</span></div>` : ''}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Item name</th><th>HSN/SAC</th><th class="num">Quantity</th><th>Unit</th><th class="num">Price/Unit</th><th class="num">GST</th><th class="num">Amount</th></tr></thead>
      <tbody>${items.map((i) => html`<tr><td>${byId[i.product_id]?.name || 'Product'}</td><td>${i.hsn_sac || '—'}</td><td class="num">${i.qty}</td><td>${byId[i.product_id]?.unit || 'unit'}</td><td class="num">${fmtINR(i.unit_price)}</td><td class="num">${Number(i.gst_percent || 0)}%</td><td class="num">${fmtINR(Number(i.line_total || 0) + Number(i.gst_amount || 0))}</td></tr>`)}
        ${items.length ? '' : html`<tr><td colspan="7" class="muted">No item lines recorded.</td></tr>`}</tbody>
    </table></div>
    <div class="summary" style="margin-top:12px">
      <div class="summary-row"><span>Subtotal</span><span>${fmtINR(items.reduce((sum, i) => sum + Number(i.line_total || 0), 0))}</span></div>
      <div class="summary-row"><span>GST</span><span>${fmtINR(items.reduce((sum, i) => sum + Number(i.gst_amount || 0), 0))}</span></div>
      <div class="summary-row"><span>Invoice total</span><b>${fmtINR(sale.total)}</b></div>
      <div class="summary-row"><span>Received</span><span>${fmtINR(sale.amount_received)}</span></div>
      <div class="summary-row"><span>Balance due</span><b>${fmtINR(due)}</b></div>
    </div>
    ${receipts.length ? html`<section style="margin-top:18px">${SectionHead({ title: 'Payment history' })}
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>
        <tbody>${receipts.map((r) => html`<tr><td>${fmtDate(r.received_at)}</td><td>${METHOD[r.method] || r.method}</td><td>${r.reference || '—'}</td><td class="num">${fmtINR(r.amount)}</td></tr>`)}</tbody></table></div>
    </section>` : ''}
  </section>`
}

export default {
  state: { rows: null, items: [], receipts: [], products: [], byId: {}, districts: [], err: '', q: '', status: '',
    selected: '', create: false, f: emptyForm(), items2: [emptyItem()], cErr: '', busy: false, dl: false,
    payment: null, payForm: { amount: '', method: 'cash', reference: '' }, payErr: '', payBusy: false },
  async init() { await this.actions.load.call(this) },
  view(S) {
    if (S.err && !S.rows) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading bills…')
    const query = S.q.trim().toLowerCase()
    const list = S.rows.filter((s) => (!S.status || s.payment_status === S.status)
      && (!query || `${s.invoice_no || ''} ${s.customer_name || ''} ${s.phone || ''} ${s.place || ''}`.toLowerCase().includes(query)))
    const live = S.rows.filter((s) => s.status === 'active')
    const invoiced = S.rows.filter((s) => Boolean(s.invoice_no))
    const received = live.reduce((a, s) => a + Number(s.amount_received || 0), 0)
    const due = live.reduce((a, s) => a + Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0)), 0)
    const selected = S.rows.find((s) => s.id === S.selected)
    const productSummary = (saleId) => itemsText(S.items.filter((i) => i.sale_id === saleId), S.byId) || '—'
    return html`${PageHead({ label: 'Telecalling', title: 'Billing', sub: 'Bill a customer directly and track what is still due. No stock is tracked here.',
        actions: html`<button class="btn primary" data-act="openCreate">${Icon('plus', 18)} Create bill</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Bills recorded', value: invoiced.length, sub: `of ${S.rows.length} sales` })}
        ${Stat({ label: 'Received', value: fmtINR(received), sub: 'Active sales' })}
        ${Stat({ label: 'Balance due', value: fmtINR(due), tone: due ? 'warn' : 'ok', sub: 'Active sales' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search invoice, customer, place" aria-label="Search invoices" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="status" data-live aria-label="Payment status"><option value="">Any payment status</option>${Object.entries(PAYMENT).map(([k, v]) => opt(k, S.status, v))}</select>
      </div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No bills match these filters.' : 'No bills created yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Products</th><th class="num">Total</th><th class="num">Due</th><th>Payment</th></tr></thead>
        <tbody>${list.map((s) => html`<tr data-act="select" data-id="${s.id}" aria-selected="${S.selected === s.id}" style="cursor:pointer${S.selected === s.id ? ';background:var(--wash)' : ''}">
          <td><b>${s.invoice_no || 'No invoice no.'}</b></td><td>${fmtDate(s.sale_date)}</td>
          <td>${s.customer_name || '—'}${s.place ? html`<div class="muted small">${s.place}</div>` : ''}</td>
          <td style="white-space:normal;max-width:240px">${productSummary(s.id)}</td>
          <td class="num"><b>${fmtINR(s.total)}</b></td><td class="num">${s.status === 'active' ? fmtINR(Math.max(0, Number(s.total || 0) - Number(s.amount_received || 0))) : '—'}</td>
          <td>${s.status === 'cancelled' ? 'Cancelled' : PAYMENT[s.payment_status] || '—'}</td></tr>`)}</tbody></table></div>`}
      ${selected ? invoiceDetail(selected, S.items.filter((i) => i.sale_id === selected.id), S, S.receipts.filter((r) => r.sale_id === selected.id), S.dl) : ''}
      ${S.payment && selected ? Sheet({ title: 'Record payment', close: 'closePayment', body: html`
        <p class="muted">Balance due: <b>${fmtINR(Math.max(0, Number(selected.total || 0) - Number(selected.amount_received || 0)))}</b></p>
        <label>Amount received (₹)<input type="number" min="0.01" step="0.01" max="${Math.max(0, Number(selected.total || 0) - Number(selected.amount_received || 0))}" inputmode="decimal" data-bind="payForm.amount" value="${S.payForm.amount}"></label>
        <label>Payment method<select data-bind="payForm.method">${Object.entries(METHOD).map(([k, v]) => opt(k, S.payForm.method, v))}</select></label>
        <label>Reference (optional)<input data-bind="payForm.reference" value="${S.payForm.reference}" placeholder="Transaction ID, cheque no., etc."></label>
        ${S.payErr ? html`<p class="error">${S.payErr}</p>` : ''}
        <button class="btn primary block" data-act="savePayment" ${S.payBusy ? raw('disabled') : ''}>${S.payBusy ? 'Saving…' : 'Record payment'}</button>` }) : ''}
      ${S.create ? billForm(S) : ''}`
  },
  actions: {
    async load() {
      const [s, i, products, districts, receipts] = await Promise.all([
        supabase.from('tc_sales').select('*').order('sale_date', { ascending: false }).order('created_at', { ascending: false }),
        supabase.from('tc_sale_items').select('*'),
        loadProducts(), loadDistricts(),
        supabase.from('tc_payment_receipts').select('*').order('received_at', { ascending: false }),
      ])
      if (s.error || i.error || receipts.error) return this.set({ err: errText(s.error || i.error || receipts.error) })
      this.set({ rows: s.data, items: i.data, receipts: receipts.data, products: products.products, byId: products.byId, districts, err: '' })
    },
    select(el) { this.set({ selected: el.dataset.id }) },
    openCreate() { this.set({ create: true, cErr: '', f: emptyForm(), items2: [emptyItem()] }) },
    closeCreate() { this.set({ create: false }) },
    pickProduct(el) {
      const q = this.S.byId[el.value], i = Number(el.dataset.i)
      const it = this.S.items2[i]
      it.hsn_sac = q ? q.hsn_sac || '' : ''
      it.gst_percent = q ? q.gst_percent ?? 0 : 0
      it.unit_price = q && q.list_price != null ? (it.incl ? round2(q.list_price * gstFactor(it)) : q.list_price) : ''
      this.render()
    },
    priceMode(el) {
      const x = this.S.items2[Number(el.dataset.i)], incl = el.dataset.m === 'incl'
      if (incl === Boolean(x.incl)) return
      const v = typedPrice(x)
      if (v > 0) x.unit_price = round2(incl ? v * gstFactor(x) : v / gstFactor(x))
      x.incl = incl
      this.render()
    },
    addItem() { this.set({ items2: [...this.S.items2, emptyItem()] }) },
    removeItem(el) { this.set({ items2: this.S.items2.filter((_, j) => j !== Number(el.dataset.i)) }) },
    async createBill() {
      const S = this.S, f = S.f, items = S.items2
      this.set({ cErr: '' })
      const total = items.reduce((a, x) => a + lineTotal(x), 0)
      if (f.customer_name.trim().length < 2) return this.set({ cErr: 'Enter the customer name.' })
      if (items.some((x) => !x.product_id || !(Number(x.qty) > 0) || !(Number(x.unit_price) > 0) || !Number.isFinite(Number(x.gst_percent)) || Number(x.gst_percent) < 0 || Number(x.gst_percent) > 100))
        return this.set({ cErr: 'Choose each product and enter its quantity, unit price and valid GST rate.' })
      if (Number(f.received || 0) > total) return this.set({ cErr: 'Money received cannot be more than the total.' })
      this.set({ busy: true })
      const { error } = await supabase.rpc('tc_record_sale', {
        p_customer_name: f.customer_name, p_customer_type: f.customer_type, p_phone: f.phone || null,
        p_district: f.district_id ? Number(f.district_id) : null, p_place: f.place || null, p_sale_date: f.sale_date,
        p_amount_received: Number(f.received || 0),
        p_items: items.map((x) => ({ product_id: x.product_id, hsn_sac: x.hsn_sac.trim(), qty: Number(x.qty),
          unit_price: x.incl ? Number(exPrice(x).toFixed(6)) : Number(x.unit_price), ...(x.incl ? { unit_price_incl: Number(x.unit_price) } : {}),
          gst_percent: Number(x.gst_percent) || 0 })),
      })
      this.set({ busy: false })
      if (error) return this.set({ cErr: errText(error) })
      toast('Bill created. Open it to print or download it.')
      this.set({ create: false })
      await this.actions.load.call(this)
    },
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
      const { error } = await supabase.rpc('tc_receive_payment', { p_sale: sale.id, p_amount: amount, p_method: v.method, p_reference: v.reference.trim() })
      if (error) return this.set({ payBusy: false, payErr: errText(error) })
      this.set({ payment: null, payBusy: false })
      await this.actions.load.call(this)
    },
    async downloadPdf() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected)
      if (sale) await downloadInvoicePdf(this, sale)
    },
    printInvoice() {
      const sale = this.S.rows.find((s) => s.id === this.S.selected)
      if (sale) printSaleInvoice(sale, this.S.items.filter((i) => i.sale_id === sale.id), { data: { byId: this.S.byId, districts: this.S.districts } })
    },
  },
}
