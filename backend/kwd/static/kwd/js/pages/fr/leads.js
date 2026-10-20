/* The franchisee's leads from Head Office: update status, close the sale, book a presentation. */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { fmtDate, istDate } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'
import { CUSTOMER_TYPES, customerShort, LEAD_STATUS, LEAD_OPEN, daysSince } from '../../fr.js'
import { LeadPill, saleForm } from './parts.js'
import { meetingForm } from './meetings.js'

const FILTERS = [['open', 'Open'], ['new', 'New'], ['follow', 'Follow-up due'], ['negotiating', 'Negotiating'], ['won', 'Closed'], ['lost', 'Lost'], ['all', 'All']]

// one lead in a sheet. props: { lead }. Parent actions: leadClose, leadChanged.
const leadSheet = {
  state: (ctx) => { const l = ctx.props.lead; return { lead: l, events: [], status: l.status, note: l.fr_note || '', next: l.next_followup_on || '', lost: l.lost_reason || '', busy: false, err: '', sub: null } },
  widgets: { saleform: saleForm, meeting: meetingForm },
  async init() { await this.actions.loadEvents.call(this) },
  view(S, ctx) {
    const { byId, districts } = ctx.data
    const lead = S.lead, closed = lead.status === 'won'
    const dName = (districts.find((d) => d.id === lead.district_id) || {}).name
    const choices = ['contacted', 'negotiating', 'lost']
    if (!choices.includes(lead.status) && lead.status !== 'won') choices.unshift(lead.status)
    return Sheet({ title: lead.customer_name, close: 'close', body: html`
      <div class="row wrap">${LeadPill(lead.status)}<span class="pill">${CUSTOMER_TYPES[lead.customer_type]}</span></div>
      <div class="summary" style="margin:12px 0">
        ${lead.contact_person ? html`<div class="summary-row"><span>Contact</span><span>${lead.contact_person}</span></div>` : ''}
        ${lead.phone ? html`<div class="summary-row"><span>Phone</span><span><a href="tel:${lead.phone}">${lead.phone}</a></span></div>` : ''}
        <div class="summary-row"><span>Where</span><span>${[lead.place, lead.address, dName].filter(Boolean).join(', ') || '—'}</span></div>
        ${lead.product_id ? html`<div class="summary-row"><span>Interested in</span><span>${lead.qty || 1} × ${byId[lead.product_id] && byId[lead.product_id].name}</span></div>` : ''}
        <div class="summary-row"><span>Assigned</span><span>${fmtDate(lead.assigned_at)}</span></div>
      </div>
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
      ${S.sub === 'meet' ? widget(this, 'meeting', 'lead', { lead }) : ''}` })
  },
  actions: {
    close() { const p = this.ctx.parent; p.actions.leadClose.call(p) },
    loadEvents() {
      return supabase.from('fr_lead_events').select('*').eq('lead_id', this.S.lead.id).order('at', { ascending: false }).then(({ data }) => this.set({ events: data || [] }))
    },
    setStatus(el) { this.set({ status: el.dataset.k }) },
    openSale() { this.set({ sub: 'sale' }) },
    openMeet() { this.set({ sub: 'meet' }) },
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
  state: (ctx) => ({ rows: null, err: '', f: ctx.route.filter || 'open', q: '', open: null }),
  widgets: { lead: leadSheet },
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
    const list = S.rows.filter((l) => test(S.f, l) && (!s || `${l.customer_name} ${l.place} ${l.phone} ${l.contact_person}`.toLowerCase().includes(s)))
    return html`${PageHead({ label: 'Given by Head Office', title: 'Leads', sub: 'Call, meet, update the status, and close the sale here when the customer says yes.' })}
      <div class="toolbar"><div class="search">${Icon('search', 18)}<input placeholder="Search name, place, phone" data-bind="q" data-live value="${S.q}"></div></div>
      <div class="chips" style="margin-bottom:12px">${FILTERS.map(([k, l]) => html`<button class="chip${S.f === k ? ' on' : ''}" aria-pressed="${S.f === k}" data-act="filter" data-k="${k}">${l} (${S.rows.filter((x) => test(k, x)).length})</button>`)}</div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No leads match.' : 'No leads yet. Head Office will assign leads to you.') : html`<ul class="list">${list.map((l) => html`<li data-key="${l.id}">
        <button class="item" data-act="open" data-id="${l.id}">
          <div class="grow">
            <div class="title">${l.customer_name}</div>
            <div class="muted small">${customerShort[l.customer_type]}${l.place || l.district_id ? ` · ${[l.place, dName(l.district_id)].filter(Boolean).join(', ')}` : ''}${l.product_id ? ` · ${l.qty || 1} × ${byId[l.product_id] && byId[l.product_id].name}` : ''}</div>
            <div class="muted small">${l.status === 'new' ? `Assigned ${daysSince(l.assigned_at) === 0 ? 'today' : `${daysSince(l.assigned_at)} d ago`}` : l.next_followup_on ? `Follow-up ${fmtDate(l.next_followup_on)}` : ''}${l.next_followup_on && l.next_followup_on < today && LEAD_OPEN.includes(l.status) ? html`<span class="text-bad"> · overdue</span>` : ''}</div>
          </div>
          ${LeadPill(l.status)}
        </button></li>`)}</ul>`}
      ${S.open ? widget(this, 'lead', S.open.id, { lead: S.open }) : ''}`
  },
  actions: {
    filter(el) { this.set({ f: el.dataset.k }) },
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
