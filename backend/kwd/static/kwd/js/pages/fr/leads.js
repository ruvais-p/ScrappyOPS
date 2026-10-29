/* The franchisee's leads, those from Head Office and those they found themselves: add, update status, close the sale, book a presentation. */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { fmtDate, istDate } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'
import { CUSTOMER_TYPES, customerShort, LEAD_STATUS, LEAD_OPEN, daysSince } from '../../fr.js'
import { LeadPill, saleForm } from './parts.js'
import { meetingForm } from './meetings.js'

const phone10 = (s) => { const d = (s || '').replace(/\D/g, ''); return d ? d.slice(-10) : null }
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`

// add a lead you found yourself, or correct one. props: { lead } (none to add). Parent actions: formClose, formDone.
const ownForm = {
  state: (ctx) => {
    const l = ctx.props.lead
    return { v: l ? { customer_name: l.customer_name, customer_type: l.customer_type, contact_person: l.contact_person || '', phone: l.phone || '', district_id: l.district_id || '', place: l.place || '', address: l.address || '', product_id: l.product_id || '', qty: l.qty || '' }
      : { customer_name: '', customer_type: 'private', contact_person: '', phone: '', district_id: '', place: '', address: '', product_id: '', qty: '' }, busy: false, err: '' }
  },
  view(S, ctx) {
    const { products, districts } = ctx.data, v = S.v, edit = !!ctx.props.lead
    return Sheet({ title: edit ? 'Edit lead details' : 'Add my own lead', close: 'close', body: html`
      ${edit ? '' : html`<p class="muted small" style="margin-top:0">A customer you found yourself. Head Office can see it, but it stays with you.</p>`}
      <label>Customer / LSGD name<input data-bind="v.customer_name" value="${v.customer_name}"></label>
      <div class="grid2">
        <label>Type<select data-bind="v.customer_type">${Object.entries(CUSTOMER_TYPES).map(([k, l]) => opt(k, v.customer_type, l))}</select></label>
        <label>Contact person<input data-bind="v.contact_person" value="${v.contact_person}"></label>
      </div>
      <div class="grid2">
        <label>Mobile<input type="tel" inputmode="numeric" data-bind="v.phone" value="${v.phone}"></label>
        <label>District<select data-bind="v.district_id"><option value="">Choose…</option>${districts.map((d) => opt(d.id, v.district_id, d.name))}</select></label>
      </div>
      <label>Place<input data-bind="v.place" value="${v.place}"></label>
      <label>Address<input data-bind="v.address" value="${v.address}"></label>
      <div class="grid2">
        <label>Interested in<select data-bind="v.product_id"><option value="">Not known</option>${products.filter((p) => p.is_active || p.id === v.product_id).map((p) => opt(p.id, v.product_id, p.name))}</select></label>
        <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="v.qty" value="${v.qty}"></label>
      </div>
      ${errLine(S.err)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : edit ? 'Save details' : 'Add lead'}</button>` })
  },
  actions: {
    close() { const p = this.ctx.parent; p.actions.formClose.call(p) },
    async save() {
      const S = this.S, v = S.v, lead = this.ctx.props.lead
      this.set({ err: '' })
      if (v.customer_name.trim().length < 2) return this.set({ err: 'Enter the customer name.' })
      if (v.phone && !/^[6-9]\d{9}$/.test(phone10(v.phone) || '')) return this.set({ err: 'Enter a valid 10-digit mobile number.' })
      const row = { customer_name: v.customer_name.trim(), customer_type: v.customer_type, contact_person: v.contact_person.trim() || null, phone: phone10(v.phone),
        district_id: v.district_id ? Number(v.district_id) : null, place: v.place.trim() || null, address: v.address.trim() || null,
        product_id: v.product_id || null, qty: v.qty ? Number(v.qty) : null }
      this.set({ busy: true })
      const { error } = lead ? await supabase.from('fr_leads').update(row).eq('id', lead.id)
        : await supabase.from('fr_leads').insert({ ...row, franchise_id: this.ctx.data.fr.id })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast(lead ? 'Details saved' : 'Lead added')
      const p = this.ctx.parent
      p.actions.formDone.call(p)
    },
  },
}

const FILTERS = [['open', 'Open'], ['new', 'New'], ['follow', 'Follow-up due'], ['negotiating', 'Negotiating'], ['won', 'Closed'], ['lost', 'Lost'], ['all', 'All']]

// one lead in a sheet. props: { lead }. Parent actions: leadClose, leadChanged.
const leadSheet = {
  state: (ctx) => { const l = ctx.props.lead; return { lead: l, events: [], status: l.status, note: l.fr_note || '', next: l.next_followup_on || '', lost: l.lost_reason || '', busy: false, err: '', sub: null } },
  widgets: { saleform: saleForm, meeting: meetingForm, edit: ownForm },
  async init() { await this.actions.loadEvents.call(this) },
  view(S, ctx) {
    const { byId, districts } = ctx.data
    const lead = S.lead, closed = lead.status === 'won'
    const dName = (districts.find((d) => d.id === lead.district_id) || {}).name
    const choices = ['contacted', 'negotiating', 'lost']
    if (!choices.includes(lead.status) && lead.status !== 'won') choices.unshift(lead.status)
    return Sheet({ title: lead.customer_name, close: 'close', body: html`
      <div class="row wrap">${LeadPill(lead.status)}<span class="pill">${CUSTOMER_TYPES[lead.customer_type]}</span>${lead.source === 'own' ? html`<span class="pill">My own lead</span>` : ''}</div>
      <div class="summary" style="margin:12px 0">
        ${lead.contact_person ? html`<div class="summary-row"><span>Contact</span><span>${lead.contact_person}</span></div>` : ''}
        ${lead.phone ? html`<div class="summary-row"><span>Phone</span><span><a href="tel:${lead.phone}">${lead.phone}</a></span></div>` : ''}
        <div class="summary-row"><span>Where</span><span>${[lead.place, lead.address, dName].filter(Boolean).join(', ') || '—'}</span></div>
        ${lead.product_id ? html`<div class="summary-row"><span>Interested in</span><span>${lead.qty || 1} × ${byId[lead.product_id] && byId[lead.product_id].name}</span></div>` : ''}
        <div class="summary-row"><span>${lead.source === 'own' ? 'Added' : 'Assigned'}</span><span>${fmtDate(lead.assigned_at)}</span></div>
      </div>
      ${lead.source === 'own' && !closed ? html`<button class="btn sm" style="margin-bottom:12px" data-act="openEdit">Edit details</button>` : ''}
      ${lead.hq_note ? html`<p class="notice info small"><span><b>From Head Office:</b> ${lead.hq_note}</span></p>` : ''}
      ${closed ? html`<p class="notice ok small"><span>The sale for this lead is recorded. Track delivery and installation under Sales.</span></p>` : html`
        <div class="row wrap" style="margin-bottom:12px">
          <button class="btn primary" data-act="openSale">${Icon('rupee', 18)} Close the sale</button>
          <button class="btn" data-act="openMeet">${Icon('present', 18)} Book a presentation</button>
        </div>
        <div class="field-label">Where is this lead now?</div>
        <div class="chips">${choices.map((c) => html`<button class="chip${S.status === c ? ' on' : ''}" aria-pressed="${S.status === c}" data-act="setStatus" data-k="${c}">${LEAD_STATUS[c].label}</button>`)}</div>
        ${S.status === 'lost' ? html`<label>Why was it lost?<input data-bind="lost" value="${S.lost}" placeholder="Price, no budget, chose another supplier…"></label>` : ''}
        <label>Note<textarea rows="3" data-bind="note" placeholder="What was discussed, what the customer wants next">${S.note}</textarea></label>
        ${S.status !== 'lost' ? html`<label>Next follow-up date<input type="date" min="${istDate()}" data-bind="next" value="${S.next}"></label>` : ''}
        ${errLine(S.err)}
        <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Save update'}</button>`}
      ${S.events.length > 0 ? html`<div class="field-label" style="margin-top:18px">History</div>
        <ul class="trail">${S.events.map((e) => html`<li><b>${LEAD_STATUS[e.to_status] && LEAD_STATUS[e.to_status].label}</b> <span class="muted small">${fmtDate(e.at)}${e.note ? ` · ${e.note}` : ''}</span></li>`)}</ul>` : ''}
      ${S.sub === 'sale' ? widget(this, 'saleform', 'lead', { lead }) : ''}
      ${S.sub === 'meet' ? widget(this, 'meeting', 'lead', { lead }) : ''}
      ${S.sub === 'edit' ? widget(this, 'edit', 'lead', { lead }) : ''}` })
  },
  actions: {
    close() { const p = this.ctx.parent; p.actions.leadClose.call(p) },
    loadEvents() {
      return supabase.from('fr_lead_events').select('*').eq('lead_id', this.S.lead.id).order('at', { ascending: false }).then(({ data }) => this.set({ events: data || [] }))
    },
    setStatus(el) { this.set({ status: el.dataset.k }) },
    openSale() { this.set({ sub: 'sale' }) },
    openMeet() { this.set({ sub: 'meet' }) },
    openEdit() { this.set({ sub: 'edit' }) },
    formClose() { this.set({ sub: null }) },
    async formDone() { const p = this.ctx.parent; await p.actions.leadChanged.call(p); p.actions.reopen.call(p, this.S.lead.id) },
    // the sale form and the meeting form call these on their parent (this sheet)
    saleClose() { this.set({ sub: null }) },
    async saleChanged() { const p = this.ctx.parent; await p.actions.leadChanged.call(p); await this.ctx.data.refresh(); this.actions.close.call(this) },
    subClose() { this.set({ sub: null }) },
    async subDone() { const p = this.ctx.parent; this.set({ sub: null }); await p.actions.leadChanged.call(p); this.actions.close.call(this) },
    async save() {
      const S = this.S
      this.set({ err: '' })
      if (S.status === 'lost' && S.lost.trim().length < 5) return this.set({ err: 'Say why this lead was lost.' })
      this.set({ busy: true })
      const { data: row, error } = await supabase.from('fr_leads')
        .update({ status: S.status, fr_note: S.note || null, next_followup_on: S.next || null, lost_reason: S.status === 'lost' ? S.lost.trim() : null })
        .eq('id', S.lead.id).select().single()
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ lead: row })
      toast('Lead updated')
      this.actions.loadEvents.call(this)
      const p = this.ctx.parent
      p.actions.leadChanged.call(p)
    },
  },
}

export default {
  state: (ctx) => ({ rows: null, err: '', f: ctx.route.filter || 'open', src: '', q: '', open: null, add: false }),
  widgets: { lead: leadSheet, add: ownForm },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { byId, districts } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading your leads…')
    const today = istDate()
    const dName = (id) => (districts.find((d) => d.id === id) || {}).name
    const test = (k, l) => k === 'open' ? LEAD_OPEN.includes(l.status) : k === 'all' ? true
      : k === 'follow' ? LEAD_OPEN.includes(l.status) && l.next_followup_on && l.next_followup_on <= today : l.status === k
    const s = S.q.trim().toLowerCase()
    const list = S.rows.filter((l) => test(S.f, l) && (!S.src || (l.source || 'ho') === S.src) && (!s || `${l.customer_name} ${l.place} ${l.phone} ${l.contact_person}`.toLowerCase().includes(s)))
    return html`${PageHead({ label: 'Head Office and your own', title: 'Leads', sub: 'Call, meet, update the status, and close the sale here when the customer says yes. Add the customers you find yourself too; Head Office can see them.',
        actions: html`<button class="btn primary" data-act="openAdd">${Icon('plus', 18)} Add my own lead</button>` })}
      <div class="toolbar"><div class="search">${Icon('search', 18)}<input placeholder="Search name, place, phone" data-bind="q" data-live value="${S.q}"></div></div>
      <div class="chips" style="margin-bottom:12px">${FILTERS.map(([k, l]) => html`<button class="chip${S.f === k ? ' on' : ''}" aria-pressed="${S.f === k}" data-act="filter" data-k="${k}">${l} (${S.rows.filter((x) => test(k, x)).length})</button>`)}</div>
      <div class="chips" style="margin-bottom:12px">${[['', 'All sources'], ['ho', 'From Head Office'], ['own', 'My own']].map(([k, l]) => html`<button class="chip${S.src === k ? ' on' : ''}" aria-pressed="${S.src === k}" data-act="source" data-k="${k}">${l}</button>`)}</div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No leads match.' : 'No leads yet. Head Office will assign leads to you, or add one you found yourself.') : html`<ul class="list">${list.map((l) => html`<li data-key="${l.id}">
        <button class="item" data-act="open" data-id="${l.id}">
          <div class="grow">
            <div class="title">${l.customer_name}${l.source === 'own' ? html` <span class="pill tiny">Own</span>` : ''}</div>
            <div class="muted small">${customerShort[l.customer_type]}${l.place || l.district_id ? ` · ${[l.place, dName(l.district_id)].filter(Boolean).join(', ')}` : ''}${l.product_id ? ` · ${l.qty || 1} × ${byId[l.product_id] && byId[l.product_id].name}` : ''}</div>
            <div class="muted small">${l.status === 'new' ? `Assigned ${daysSince(l.assigned_at) === 0 ? 'today' : `${daysSince(l.assigned_at)} d ago`}` : l.next_followup_on ? `Follow-up ${fmtDate(l.next_followup_on)}` : ''}${l.next_followup_on && l.next_followup_on < today && LEAD_OPEN.includes(l.status) ? html`<span class="text-bad"> · overdue</span>` : ''}</div>
          </div>
          ${LeadPill(l.status)}
        </button></li>`)}</ul>`}
      ${S.open ? widget(this, 'lead', S.open.id, { lead: S.open }) : ''}
      ${S.add ? widget(this, 'add', 'new', {}) : ''}`
  },
  actions: {
    filter(el) { this.set({ f: el.dataset.k }) },
    source(el) { this.set({ src: el.dataset.k }) },
    openAdd() { this.set({ add: true }) },
    formClose() { this.set({ add: false }) },
    async formDone() { this.set({ add: false }); await this.actions.load.call(this); await this.ctx.data.refresh() },
    reopen(id) { this.set({ open: this.S.rows.find((l) => l.id === id) || null }) },
    open(el) { this.set({ open: this.S.rows.find((l) => l.id === el.dataset.id) }) },
    leadClose() { this.set({ open: null }) },
    async leadChanged() { await this.actions.load.call(this); await this.ctx.data.refresh() },
    async load() {
      const { data, error } = await supabase.from('fr_leads').select('*').order('assigned_at', { ascending: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data })
    },
  },
}
