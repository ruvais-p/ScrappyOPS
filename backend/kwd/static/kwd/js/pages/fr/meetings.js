/* Presentation appointments: book, move, mark as done, cancel. */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead, SectionHead } from '../../ui.js'
import { Sheet, errLine } from '../../kit.js'
import { takePhoto, uploadPhoto, watchPosition } from '../../expenses.js'
import { VENUES, OUTCOMES, OUTCOME_TONE, LEAD_OPEN, fmtWhen, toLocalInput, fromLocalInput } from '../../fr.js'

export const PresPills = (p) => html`<span class="row wrap" style="gap:6px">
  <span class="pill">${VENUES[p.venue_type]}</span>
  ${p.status === 'cancelled' ? html`<span class="pill bad">Cancelled</span>` : ''}
  ${p.status === 'done' ? html`<span class="pill ${OUTCOME_TONE[p.outcome] || ''}">${OUTCOMES[p.outcome]}</span>` : ''}
  ${p.reschedule_count > 0 ? html`<span class="pill warn">Moved ${p.reschedule_count}×</span>` : ''}</span>`

const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`
const parentCall = (sc, name, ...a) => { const p = sc.ctx.parent; return p.actions[name].call(p, ...a) }

// new, or edit/move while still scheduled. props: { meeting?, lead?, leads? }. Parent actions: subClose, subDone.
export const meetingForm = {
  state: (ctx) => {
    const { meeting: m, lead } = ctx.props
    return {
      f: {
        when: m ? toLocalInput(m.scheduled_at) : '',
        venue_type: (m && m.venue_type) || (lead && lead.customer_type === 'lsgd' ? 'lsgd' : lead && lead.customer_type === 'institution' ? 'institution' : 'private'),
        venue_name: (m && m.venue_name) || (lead && lead.customer_name) || '', lsgd_name: (m && m.lsgd_name) || '', district: (m && m.district_id) || (lead && lead.district_id) || '',
        address: (m && m.address) || (lead && lead.place) || '', contact_person: (m && m.contact_person) || (lead && lead.contact_person) || '', phone: (m && m.phone) || (lead && lead.phone) || '',
        expected: m && m.expected_attendees != null ? m.expected_attendees : '', purpose: (m && m.purpose) || '', lead_id: (m && m.lead_id) || (lead && lead.id) || '',
      },
      pids: (m && m.product_ids) || (lead && lead.product_id ? [lead.product_id] : []), busy: false, err: '',
    }
  },
  view(S, ctx) {
    const { meeting: m, lead, leads = [] } = ctx.props
    const { products, districts } = ctx.data
    const f = S.f
    return Sheet({ title: m ? 'Edit appointment' : 'New presentation appointment', close: 'close', body: html`
      <label>Date and time<input type="datetime-local" data-bind="f.when" value="${f.when}"></label>
      ${m && m.reschedule_count > 0 ? html`<p class="muted small">Moved ${m.reschedule_count} time${m.reschedule_count === 1 ? '' : 's'} already. Head Office can see changes of date.</p>` : ''}
      <label>Where is it<select data-bind="f.venue_type" data-live>${Object.entries(VENUES).map(([k, v]) => opt(k, f.venue_type, v))}</select></label>
      <label>${f.venue_type === 'private' ? 'Person / family name' : 'Place or organisation'}<input data-bind="f.venue_name" value="${f.venue_name}" placeholder="${f.venue_type === 'lsgd' ? 'e.g. Kondotty Municipality hall' : ''}"></label>
      ${f.venue_type === 'lsgd' ? html`<label>LSGD name<input data-bind="f.lsgd_name" value="${f.lsgd_name}" placeholder="Grama Panchayat / Municipality"></label>` : ''}
      <div class="grid2">
        <label>District<select data-bind="f.district"><option value="">Choose…</option>${districts.map((d) => opt(d.id, f.district, d.name))}</select></label>
        <label>Address / landmark<input data-bind="f.address" value="${f.address}"></label>
      </div>
      <div class="grid2">
        <label>Contact person<input data-bind="f.contact_person" value="${f.contact_person}"></label>
        <label>Contact phone<input type="tel" inputmode="numeric" data-bind="f.phone" value="${f.phone}"></label>
      </div>
      <label>People expected<input type="number" min="0" inputmode="numeric" data-bind="f.expected" value="${f.expected}"></label>
      <div class="field-label">Products to present</div>
      <div class="chips">${products.filter((p) => p.is_active).map((p) => html`<button class="chip${S.pids.includes(p.id) ? ' on' : ''}" aria-pressed="${S.pids.includes(p.id)}" data-act="togglePid" data-id="${p.id}">${p.name}</button>`)}</div>
      ${!m && !lead && leads.length > 0 ? html`<label>Linked lead (optional)<select data-bind="f.lead_id"><option value="">None</option>${leads.map((l) => opt(l.id, f.lead_id, l.customer_name))}</select></label>` : ''}
      <label>Purpose / notes<input data-bind="f.purpose" value="${f.purpose}" placeholder="Demo for the council, school staff briefing…"></label>
      ${errLine(S.err)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : m ? 'Save changes' : 'Book it'}</button>` })
  },
  actions: {
    close() { parentCall(this, 'subClose') },
    togglePid(el) { const id = el.dataset.id, p = this.S.pids; this.set({ pids: p.includes(id) ? p.filter((x) => x !== id) : [...p, id] }) },
    async save() {
      const S = this.S, f = S.f, m = this.ctx.props.meeting
      this.set({ err: '' })
      if (!f.when) return this.set({ err: 'Choose the date and time.' })
      if (f.venue_name.trim().length < 2) return this.set({ err: 'Enter where it is: the place or organisation name.' })
      if (!m && new Date(fromLocalInput(f.when)) < new Date(Date.now() - 36e5)) return this.set({ err: 'That time has already passed.' })
      const row = {
        scheduled_at: fromLocalInput(f.when), venue_type: f.venue_type, venue_name: f.venue_name.trim(), lsgd_name: f.lsgd_name.trim() || null,
        district_id: f.district ? Number(f.district) : null, address: f.address.trim() || null, contact_person: f.contact_person.trim() || null,
        phone: f.phone.trim() || null, expected_attendees: f.expected === '' ? null : Number(f.expected), product_ids: S.pids, purpose: f.purpose.trim() || null,
      }
      this.set({ busy: true })
      const { error } = m ? await supabase.from('fr_presentations').update(row).eq('id', m.id)
        : await supabase.from('fr_presentations').insert({ ...row, lead_id: f.lead_id || null })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast(m ? 'Appointment updated' : 'Appointment booked')
      parentCall(this, 'subDone')
    },
  },
}

const doneForm = {
  state: (ctx) => { const p = ctx.props.p; return { outcome: p.outcome || '', att: p.actual_attendees ?? '', notes: p.notes || '', photo: null, pos: null, busy: false, err: '' } },
  init() { if (this.ctx.props.p.status !== 'done') this.stopGps = watchPosition(({ pos }) => this.set({ pos })) },
  destroyed() { if (this.stopGps) this.stopGps() },
  view(S, ctx) {
    const p = ctx.props.p, finished = p.status === 'done'
    return Sheet({ title: finished ? 'How it went' : 'It happened', close: 'close', body: html`
      <p class="muted small" style="margin-top:0">${p.venue_name} · ${fmtWhen(p.scheduled_at)}</p>
      <div class="field-label">Outcome</div>
      <div class="chips">${Object.entries(OUTCOMES).map(([k, l]) => html`<button class="chip${S.outcome === k ? ' on' : ''}" aria-pressed="${S.outcome === k}" data-act="outcome" data-k="${k}">${l}</button>`)}</div>
      <label>People who attended<input type="number" min="0" inputmode="numeric" data-bind="att" value="${S.att}"></label>
      <label>Notes<textarea rows="3" data-bind="notes" placeholder="Questions asked, who decides, what happens next">${S.notes}</textarea></label>
      ${!finished ? html`<div class="row wrap">
          <input id="pres-photo" type="file" accept="image/*" capture="environment" hidden data-change="photo">
          <button class="btn sm" data-act="pickPhoto">${Icon('camera', 16)} ${S.photo ? 'Retake photo' : 'Photo of the session (optional)'}</button>
          ${S.photo ? html`<span class="pill ok">Photo ready</span>` : ''}</div>
        <p class="muted small">${S.pos ? `Your location is stamped (accuracy ${S.pos.acc} m).` : 'Looking for your location… it is stamped on the record if available.'}</p>` : ''}
      ${errLine(S.err)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Save'}</button>` })
  },
  actions: {
    close() { parentCall(this, 'subClose') },
    outcome(el) { this.set({ outcome: el.dataset.k }) },
    pickPhoto() { document.getElementById('pres-photo').click() },
    async photo(el) {
      const file = el.files && el.files[0]
      el.value = ''
      if (!file) return
      try { this.set({ photo: await takePhoto(file, { live: true, lines: [this.ctx.props.p.venue_name, new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })] }) }) } catch (x) { this.set({ err: errText(x) }) }
    },
    async save() {
      const S = this.S, p = this.ctx.props.p, finished = p.status === 'done'
      this.set({ err: '' })
      if (!S.outcome) return this.set({ err: 'Choose how it went.' })
      if (S.att === '' || Number(S.att) < 0) return this.set({ err: 'Enter how many people attended.' })
      this.set({ busy: true })
      try {
        const row = finished ? { outcome: S.outcome, actual_attendees: Number(S.att), notes: S.notes || null }
          : { status: 'done', outcome: S.outcome, actual_attendees: Number(S.att), notes: S.notes || null, done_lat: S.pos ? S.pos.lat : null, done_lng: S.pos ? S.pos.lng : null,
            done_photo: S.photo ? await uploadPhoto(this.ctx.profile.id, 'presentation', S.photo) : null }
        const { error } = await supabase.from('fr_presentations').update(row).eq('id', p.id)
        if (error) throw error
        toast('Saved')
        parentCall(this, 'subDone')
      } catch (x) { this.set({ err: errText(x) }) } finally { this.set({ busy: false }) }
    },
  },
}

const cancelForm = {
  state: { reason: '', busy: false, err: '' },
  view(S, ctx) {
    const p = ctx.props.p
    return Sheet({ title: 'Cancel appointment', close: 'close', body: html`
      <p class="muted small" style="margin-top:0">${p.venue_name} · ${fmtWhen(p.scheduled_at)}</p>
      <label>Why<input data-bind="reason" value="${S.reason}"></label>
      ${errLine(S.err)}
      <button class="btn danger block" ${S.busy ? raw('disabled') : ''} data-act="save">Cancel this appointment</button>` })
  },
  actions: {
    close() { parentCall(this, 'subClose') },
    async save() {
      if (this.S.reason.trim().length < 5) return this.set({ err: 'Say why it was cancelled.' })
      this.set({ busy: true })
      const { error } = await supabase.from('fr_presentations').update({ status: 'cancelled', cancel_reason: this.S.reason.trim() }).eq('id', this.ctx.props.p.id)
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Appointment cancelled')
      parentCall(this, 'subDone')
    },
  },
}

const row = (p, ctx) => {
  const { byId, districts } = ctx.data
  const dName = (id) => (districts.find((d) => d.id === id) || {}).name
  const where = [p.lsgd_name, dName(p.district_id)].filter(Boolean)
  const extra = [p.address, p.contact_person && `${p.contact_person}${p.phone ? ' ' + p.phone : ''}`].filter(Boolean)
  return html`<li data-key="${p.id}"><div class="item col">
    <div class="row" style="width:100%"><div class="grow"><div class="title">${p.venue_name}</div>
      <div class="muted small">${fmtWhen(p.scheduled_at)}${where.length ? ` · ${where.join(', ')}` : ''}</div></div></div>
    ${extra.length ? html`<div class="muted small">${extra.join(' · ')}</div>` : ''}
    ${p.product_ids && p.product_ids.length > 0 ? html`<div class="muted small">Presenting: ${p.product_ids.map((i) => byId[i] && byId[i].name).filter(Boolean).join(', ')}</div>` : ''}
    ${PresPills(p)}
    ${p.status === 'done' ? html`<div class="muted small">${p.actual_attendees} attended${p.notes ? ` · ${p.notes}` : ''}</div>` : ''}
    ${p.status === 'cancelled' ? html`<div class="muted small">Reason: ${p.cancel_reason}</div>` : ''}
    ${p.status === 'scheduled' ? html`<div class="row wrap" style="gap:8px">
      <button class="btn sm primary" data-act="done" data-id="${p.id}">It happened</button>
      <button class="btn sm" data-act="edit" data-id="${p.id}">Edit / move</button>
      <button class="btn sm" data-act="cancel" data-id="${p.id}">Cancel</button></div>` : ''}
    ${p.status === 'done' && p.outcome === 'order_received' && p.lead_id ? html`<button class="btn sm" data-act="toLeads">Close the sale from Leads</button>` : ''}
    ${p.status === 'done' ? html`<button class="btn sm" data-act="done" data-id="${p.id}">Update how it went</button>` : ''}
  </div></li>`
}

export default {
  state: { rows: null, leads: [], err: '', sub: null },
  widgets: { meeting: meetingForm, done: doneForm, cancel: cancelForm },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading your presentations…')
    const late = Date.now() - 3 * 36e5
    const due = S.rows.filter((p) => p.status === 'scheduled' && new Date(p.scheduled_at) < late)
    const next = S.rows.filter((p) => p.status === 'scheduled' && new Date(p.scheduled_at) >= late).reverse()
    const past = S.rows.filter((p) => p.status !== 'scheduled')
    const sub = S.sub
    return html`${PageHead({ label: 'Appointments', title: 'Presentations', sub: 'Every presentation you have booked, where it is, and how it went. Head Office sees these.',
        actions: html`<button class="btn primary" data-act="newMeeting">${Icon('plus', 18)} New appointment</button>` })}
      ${due.length > 0 ? html`<section>${SectionHead({ title: 'Tell us how these went', count: due.length, tone: 'bad' })}<ul class="list">${due.map((p) => row(p, ctx))}</ul></section>` : ''}
      <section>${SectionHead({ title: 'Coming up', count: next.length })}
        ${next.length === 0 ? Empty('No presentations booked.', { action: html`<button class="btn" data-act="newMeeting">Book one</button>` }) : html`<ul class="list">${next.map((p) => row(p, ctx))}</ul>`}</section>
      ${past.length > 0 ? html`<section>${SectionHead({ title: 'Past', count: past.length })}<ul class="list">${past.map((p) => row(p, ctx))}</ul></section>` : ''}
      ${sub && sub.kind === 'meeting' ? widget(this, 'meeting', sub.p ? sub.p.id : 'new', { meeting: sub.p || null, leads: S.leads }) : ''}
      ${sub && sub.kind === 'done' ? widget(this, 'done', sub.p.id, { p: sub.p }) : ''}
      ${sub && sub.kind === 'cancel' ? widget(this, 'cancel', sub.p.id, { p: sub.p }) : ''}`
  },
  actions: {
    newMeeting() { this.set({ sub: { kind: 'meeting' } }) },
    edit(el) { this.set({ sub: { kind: 'meeting', p: this.S.rows.find((r) => r.id === el.dataset.id) } }) },
    done(el) { this.set({ sub: { kind: 'done', p: this.S.rows.find((r) => r.id === el.dataset.id) } }) },
    cancel(el) { this.set({ sub: { kind: 'cancel', p: this.S.rows.find((r) => r.id === el.dataset.id) } }) },
    toLeads() { this.ctx.go('leads', { filter: 'open' }) },
    subClose() { this.set({ sub: null }) },
    async subDone() { this.set({ sub: null }); await this.actions.load.call(this) },
    async load() {
      const [p, l] = await Promise.all([
        supabase.from('fr_presentations').select('*').order('scheduled_at', { ascending: false }),
        supabase.from('fr_leads').select('id, customer_name, status').in('status', LEAD_OPEN),
      ])
      if (p.error) return this.set({ err: errText(p.error) })
      this.set({ rows: p.data, leads: l.data || [] })
    },
  },
}
