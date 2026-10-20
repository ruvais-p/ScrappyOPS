/* Franchise pieces shared by several screens: status pills, the "record a sale" form and the one-sale sheet.
   Both forms are widgets; the screen that opens them provides the actions saleClose and saleChanged (and data in ctx.data). */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Icon } from '../../ui.js'
import { fmtINR, fmtDate, istDate, addDays } from '../../lib.js'
import { Loading } from '../../ui.js'
import { Sheet, errLine } from '../../kit.js'
import { takePhoto, uploadPhoto, signedUrl } from '../../expenses.js'
import { CUSTOMER_TYPES, LEAD_STATUS, DELIVERY, INSTALL, PAYMENT, SALE_FLAG } from '../../fr.js'

export const LeadPill = (status) => html`<span class="pill ${(LEAD_STATUS[status] && LEAD_STATUS[status].tone) || ''}">${(LEAD_STATUS[status] && LEAD_STATUS[status].label) || status}</span>`

export const SalePills = (s) => s.status === 'cancelled' ? html`<span class="pill bad">Cancelled</span>` : html`<span class="row wrap" style="gap:6px">
  <span class="pill ${s.payment_status === 'paid' ? 'ok' : s.payment_status === 'partial' ? 'warn' : 'bad'}">${PAYMENT[s.payment_status]}</span>
  <span class="pill ${s.delivery_status === 'delivered' ? 'ok' : 'warn'}">${DELIVERY[s.delivery_status]}</span>
  ${s.needs_install ? html`<span class="pill ${s.installation_status === 'installed' ? 'ok' : 'warn'}">${INSTALL[s.installation_status]}</span>` : ''}
  ${s.ho_flag ? html`<span class="pill bad">Flagged</span>` : ''}</span>`

const opt = (v, cur, label, disabled) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''} ${disabled ? raw('disabled') : ''}>${label}</option>`
const parentCall = (sc, name, ...a) => { const p = sc.ctx.parent; return p.actions[name].call(p, ...a) }

// ---------------------------------------------------------------- record a sale (closes the lead). props: { lead }
export const saleForm = {
  state: (ctx) => {
    const lead = ctx.props.lead, byId = ctx.data.byId
    const first = lead && lead.product_id ? byId[lead.product_id] : null
    return {
      f: {
        customer_name: (lead && lead.customer_name) || '', customer_type: (lead && lead.customer_type) || 'private', phone: (lead && lead.phone) || '',
        district: (lead && lead.district_id) || '', place: (lead && lead.place) || '', sale_date: istDate(), invoice_no: '', received: '',
      },
      items: [{ product_id: first ? first.id : '', qty: (lead && lead.qty) || 1, unit_price: first ? first.list_price : '' }],
      busy: false, err: '',
    }
  },
  view(S, ctx) {
    const lead = ctx.props.lead, { products, byId, stock, districts } = ctx.data
    const f = S.f
    const total = S.items.reduce((a, x) => a + (Number(x.qty) || 0) * (Number(x.unit_price) || 0), 0)
    const onHand = (id) => stock[id] ?? 0
    return Sheet({ title: lead ? 'Close the sale' : 'Record a sale', close: 'close', body: html`
      ${lead ? html`<p class="notice info small"><span>This closes the lead for ${lead.customer_name}. Stock goes down by what you enter below.</span></p>` : ''}
      <label>Customer name<input data-bind="f.customer_name" value="${f.customer_name}"></label>
      <div class="grid2">
        <label>Customer type<select data-bind="f.customer_type">${Object.entries(CUSTOMER_TYPES).map(([k, v]) => opt(k, f.customer_type, v))}</select></label>
        <label>Mobile<input type="tel" inputmode="numeric" data-bind="f.phone" value="${f.phone}" placeholder="10 digits"></label>
      </div>
      <div class="grid2">
        <label>District<select data-bind="f.district"><option value="">Choose…</option>${districts.map((d) => opt(d.id, f.district, d.name))}</select></label>
        <label>Place / address<input data-bind="f.place" value="${f.place}"></label>
      </div>
      <div class="field-label">Products sold</div>
      ${S.items.map((x, i) => {
        const p = byId[x.product_id]
        const low = p && p.list_price && Number(x.unit_price) > 0 && Number(x.unit_price) < p.list_price * 0.9
        return html`<div class="subcard" style="margin-bottom:10px" data-key="item${i}">
          <label>Product<select data-bind="items.${i}.product_id" data-change="pickProduct" data-i="${i}">
            <option value="">Choose…</option>
            ${products.filter((q) => q.is_active).map((q) => opt(q.id, x.product_id, `${q.name} · ${onHand(q.id)} in stock`, onHand(q.id) <= 0))}</select></label>
          <div class="grid2">
            <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="items.${i}.qty" data-live value="${x.qty}"></label>
            <label>Selling price each (₹)<input type="number" min="0" inputmode="decimal" data-bind="items.${i}.unit_price" data-live value="${x.unit_price}"></label>
          </div>
          <div class="row">
            <span class="muted small grow">${p && p.list_price ? `List price ${fmtINR(p.list_price)}` : 'No list price set by Head Office'} · line ${fmtINR((Number(x.qty) || 0) * (Number(x.unit_price) || 0))}</span>
            ${S.items.length > 1 ? html`<button class="btn sm" data-act="removeItem" data-i="${i}">Remove</button>` : ''}
          </div>
          ${low ? html`<p class="notice warn small"><span>Priced more than 10% below the list price. Head Office will see this.</span></p>` : ''}
        </div>`
      })}
      <button class="btn sm" data-act="addItem">${Icon('plus', 16)} Add another product</button>
      <div class="summary" style="margin:14px 0"><div class="summary-row"><span>Total</span><span><b>${fmtINR(total)}</b></span></div></div>
      <div class="grid2">
        <label>Money received now (₹)<input type="number" min="0" inputmode="decimal" data-bind="f.received" value="${f.received}" placeholder="0"></label>
        <label>Invoice no.<input data-bind="f.invoice_no" value="${f.invoice_no}"></label>
      </div>
      <label>Sale date<input type="date" data-bind="f.sale_date" data-live value="${f.sale_date}" min="${addDays(istDate(), -7)}" max="${istDate()}"></label>
      ${f.sale_date < istDate() ? html`<p class="muted small">A sale dated before today is marked "entered for an earlier date".</p>` : ''}
      ${errLine(S.err)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Record sale'}</button>` })
  },
  actions: {
    close() { parentCall(this, 'saleClose') },
    pickProduct(el) {
      const q = this.ctx.data.byId[el.value], i = Number(el.dataset.i)
      this.S.items[i].unit_price = q ? q.list_price ?? '' : ''
      this.render()
    },
    addItem() { this.set({ items: [...this.S.items, { product_id: '', qty: 1, unit_price: '' }] }) },
    removeItem(el) { this.set({ items: this.S.items.filter((_, j) => j !== Number(el.dataset.i)) }) },
    async save() {
      const S = this.S, f = S.f, items = S.items, lead = this.ctx.props.lead, { byId, stock } = this.ctx.data
      this.set({ err: '' })
      const total = items.reduce((a, x) => a + (Number(x.qty) || 0) * (Number(x.unit_price) || 0), 0)
      if (f.customer_name.trim().length < 2) return this.set({ err: 'Enter the customer name.' })
      if (items.some((x) => !x.product_id || !(Number(x.qty) > 0) || !(Number(x.unit_price) > 0))) return this.set({ err: 'Choose each product and enter its quantity and selling price.' })
      for (const x of items) {
        const need = items.filter((y) => y.product_id === x.product_id).reduce((a, y) => a + Number(y.qty), 0)
        const have = stock[x.product_id] ?? 0
        if (need > have) return this.set({ err: `Only ${have} of ${byId[x.product_id].name} in stock. Add stock first.` })
      }
      if (Number(f.received || 0) > total) return this.set({ err: 'Money received cannot be more than the total.' })
      this.set({ busy: true })
      const { error } = await supabase.rpc('fr_record_sale', {
        p_lead: lead ? lead.id : null, p_customer_name: f.customer_name, p_customer_type: f.customer_type, p_phone: f.phone || null,
        p_district: f.district ? Number(f.district) : null, p_place: f.place || null, p_sale_date: f.sale_date, p_invoice_no: f.invoice_no || null,
        p_amount_received: Number(f.received || 0),
        p_items: items.map((x) => ({ product_id: x.product_id, qty: Number(x.qty), unit_price: Number(x.unit_price) })),
      })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Sale recorded. Stock updated.')
      parentCall(this, 'saleChanged')
      parentCall(this, 'saleClose')
    },
  },
}

// ---------------------------------------------------------------- one sale: payment, delivery, installation. props: { sale, ho }
export const saleSheet = {
  state: (ctx) => {
    const sale = ctx.props.sale
    return {
      s: sale, items: null, busy: false, err: '', pay: String(sale.amount_received), dDate: istDate(), dNote: sale.delivery_note || '',
      iDate: sale.install_planned_on || istDate(), iNote: sale.install_note || '', photo: null, photoUrl: '', reason: '',
    }
  },
  async init() {
    const sale = this.ctx.props.sale
    supabase.from('fr_sale_items').select('*').eq('sale_id', sale.id).then(({ data }) => this.set({ items: data || [] }))
    if (sale.install_photo) signedUrl(sale.install_photo).then((u) => this.set({ photoUrl: u }))
  },
  view(S, ctx) {
    const { byId } = ctx.data, ho = ctx.props.ho, s = S.s, today = istDate()
    const locked = ho || s.status === 'cancelled'
    const due = Number(s.total) - Number(s.amount_received)
    return Sheet({ title: s.customer_name, close: 'close', body: html`
      <div class="row wrap">${SalePills(s)}</div>
      <p class="muted small" style="margin:8px 0 0">${fmtDate(s.sale_date)}${s.invoice_no ? ` · Invoice ${s.invoice_no}` : ''}${s.place ? ` · ${s.place}` : ''}${s.phone ? html` · <a href="tel:${s.phone}">${s.phone}</a>` : ''}</p>
      ${s.flags && s.flags.length > 0 ? html`<p class="notice warn small"><span>${s.flags.map((f) => SALE_FLAG[f] || f).join(' · ')}</span></p>` : ''}
      ${s.ho_flag ? html`<p class="notice bad small"><span>Flagged by Head Office: ${s.ho_flag_reason}</span></p>` : ''}
      ${s.status === 'cancelled' ? html`<p class="notice bad small"><span>Cancelled by Head Office: ${s.cancel_reason}</span></p>` : ''}
      <div class="summary" style="margin:12px 0">
        ${!S.items ? Loading() : S.items.map((i) => html`<div class="summary-row"><span>${i.qty} × ${byId[i.product_id] && byId[i.product_id].name}</span><span>${fmtINR(i.line_total)}</span></div>`)}
        <div class="summary-row"><span><b>Total</b></span><span><b>${fmtINR(s.total)}</b></span></div>
        <div class="summary-row"><span>Received</span><span>${fmtINR(s.amount_received)}</span></div>
        ${due > 0 ? html`<div class="summary-row"><span>Still to collect</span><span class="text-bad">${fmtINR(due)}</span></div>` : ''}
      </div>

      ${!locked && due > 0 ? html`<div class="subcard" style="margin-bottom:12px">
        <label>Money received so far (₹)<input type="number" inputmode="decimal" min="${s.amount_received}" max="${s.total}" data-bind="pay" data-live value="${S.pay}"></label>
        <button class="btn sm" ${S.busy || Number(S.pay) === Number(s.amount_received) ? raw('disabled') : ''} data-act="savePay">Save payment</button></div>` : ''}

      <div class="field-label">Delivery</div>
      <div class="subcard" style="margin-bottom:12px">
        ${s.delivery_status === 'delivered' ? html`<p style="margin:0">Delivered on <b>${fmtDate(s.delivered_on)}</b>${s.delivery_note ? ` · ${s.delivery_note}` : ''}</p>` : html`
          <p class="muted small" style="margin-top:0">${DELIVERY[s.delivery_status]}${s.dispatched_on ? ` on ${fmtDate(s.dispatched_on)}` : ''}</p>
          ${!locked ? html`<div class="grid2">
              <label>Date<input type="date" data-bind="dDate" value="${S.dDate}" min="${s.sale_date}" max="${today}"></label>
              <label>Note (optional)<input data-bind="dNote" value="${S.dNote}" placeholder="Vehicle, receiver…"></label></div>
            <div class="row wrap">
              ${s.delivery_status === 'pending' ? html`<button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="dispatch">${Icon('truck', 16)} Mark dispatched</button>` : ''}
              <button class="btn sm primary" ${S.busy ? raw('disabled') : ''} data-act="deliver">Mark delivered</button></div>` : ''}`}
      </div>

      ${s.needs_install ? html`<div class="field-label">Installation</div>
        <div class="subcard" style="margin-bottom:12px">
          ${s.installation_status === 'installed' ? html`<p style="margin:0">Installed on <b>${fmtDate(s.installed_on)}</b>${s.install_note ? ` · ${s.install_note}` : ''}</p>
            ${S.photoUrl ? html`<a href="${S.photoUrl}" target="_blank" rel="noreferrer"><img src="${S.photoUrl}" alt="Installed unit" style="max-width:100%;border-radius:10px;margin-top:8px"></a>` : ''}`
          : s.delivery_status !== 'delivered' ? html`<p class="muted small" style="margin:0">Installation opens once the sale is marked delivered.</p>`
          : html`<p class="muted small" style="margin-top:0">${INSTALL[s.installation_status]}${s.install_planned_on && s.installation_status === 'scheduled' ? ` for ${fmtDate(s.install_planned_on)}` : ''}</p>
            ${!locked ? html`<label>Installation date<input type="date" data-bind="iDate" data-live value="${S.iDate}" min="${s.delivered_on}"></label>
              <label>Note (optional)<input data-bind="iNote" value="${S.iNote}" placeholder="Where it was placed, who was trained…"></label>
              <div class="row wrap">
                <input id="install-photo" type="file" accept="image/*" capture="environment" hidden data-change="photo">
                <button class="btn sm" data-act="pickPhoto">${Icon('camera', 16)} ${S.photo ? 'Retake photo' : 'Photo of installed unit'}</button>
                ${S.photo ? html`<span class="pill ok">Photo ready</span>` : ''}</div>
              <div class="row wrap" style="margin-top:10px">
                ${s.installation_status === 'pending' ? html`<button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="schedule">Schedule for this date</button>` : ''}
                <button class="btn sm primary" ${S.busy || S.iDate > today ? raw('disabled') : ''} data-act="installed">Mark installed</button></div>` : ''}`}
        </div>` : ''}

      ${ho && s.status === 'active' ? html`<div class="subcard">
        <label>Reason (needed to flag or cancel)<input data-bind="reason" value="${S.reason}" placeholder="Why?"></label>
        <div class="row wrap">
          ${s.ho_flag ? html`<button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="unflag">Remove flag</button>` : html`<button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="flag">${Icon('flag', 16)} Flag this sale</button>`}
          <button class="btn sm danger" ${S.busy ? raw('disabled') : ''} data-act="cancelSale">Cancel sale</button></div></div>` : ''}
      ${errLine(S.err)}` })
  },
  actions: {
    close() { parentCall(this, 'saleClose') },
    pickPhoto() { document.getElementById('install-photo').click() },
    async patchSale(values, msg) {
      this.set({ busy: true, err: '' })
      const { data, error } = await supabase.from('fr_sales').update(values).eq('id', this.S.s.id).select().single()
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ s: { ...this.S.s, ...data } })
      toast(msg || 'Saved')
      parentCall(this, 'saleChanged')
    },
    savePay() { return this.actions.patchSale.call(this, { amount_received: Number(this.S.pay) }, 'Payment updated') },
    dispatch() { return this.actions.patchSale.call(this, { delivery_status: 'dispatched', dispatched_on: this.S.dDate, delivery_note: this.S.dNote || null }, 'Marked dispatched') },
    deliver() { return this.actions.patchSale.call(this, { delivery_status: 'delivered', delivered_on: this.S.dDate, delivery_note: this.S.dNote || null }, 'Marked delivered') },
    schedule() { return this.actions.patchSale.call(this, { installation_status: 'scheduled', install_planned_on: this.S.iDate, install_note: this.S.iNote || null }, 'Installation scheduled') },
    async photo(el) {
      const file = el.files && el.files[0]
      el.value = ''
      if (!file) return
      try {
        const blob = await takePhoto(file, { live: true, lines: ['Installed · ' + this.S.s.customer_name, new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })] })
        this.set({ photo: blob })
      } catch (x) { this.set({ err: errText(x) }) }
    },
    async installed() {
      const S = this.S
      if (!S.photo) return this.set({ err: 'Take a photo of the installed unit.' })
      this.set({ busy: true, err: '' })
      try {
        const path = await uploadPhoto(this.ctx.profile.id, 'install', S.photo)
        const { data, error } = await supabase.from('fr_sales').update({ installation_status: 'installed', installed_on: S.iDate, install_photo: path, install_note: S.iNote || null }).eq('id', S.s.id).select().single()
        if (error) throw error
        this.set({ s: { ...S.s, ...data } })
        toast('Installation recorded')
        parentCall(this, 'saleChanged')
      } catch (x) { this.set({ err: errText(x) }) } finally { this.set({ busy: false }) }
    },
    flag() { return hoFlag(this, true) },
    unflag() { return hoFlag(this, false) },
    async cancelSale() {
      const S = this.S
      if (S.reason.trim().length < 5) return this.set({ err: 'Say why this sale is cancelled.' })
      if (!confirm('Cancel this sale? The stock goes back to the franchisee.')) return
      this.set({ busy: true, err: '' })
      const { error } = await supabase.rpc('fr_cancel_sale', { p_sale: S.s.id, p_reason: S.reason.trim() })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Sale cancelled')
      parentCall(this, 'saleChanged')
      parentCall(this, 'saleClose')
    },
  },
}

async function hoFlag(sc, flag) {
  if (flag && sc.S.reason.trim().length < 5) return sc.set({ err: 'Say why you are flagging this sale.' })
  await sc.actions.patchSale.call(sc, { ho_flag: flag, ho_flag_reason: flag ? sc.S.reason.trim() : null }, flag ? 'Sale flagged' : 'Flag removed')
}
