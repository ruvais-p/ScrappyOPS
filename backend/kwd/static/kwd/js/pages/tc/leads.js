/* The telecaller's leads: a shared list + call sheet, used for both the sales-leads tab and the franchise-leads tab
   (one module, parameterised by `kind` so the two tabs don't duplicate this screen). */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { fmtDate, istDate } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'
import { TC_STATUS, TC_OPEN, TC_TEMP } from '../../tc.js'

const FILTERS = [['open', 'Open'], ['new', 'New'], ['follow', 'Follow-up due'], ['interested', 'Interested'], ['converted', 'Converted'], ['lost', 'Lost'], ['all', 'All']]
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`
const phone10 = (s) => { const d = (s || '').replace(/\D/g, ''); return d ? d.slice(-10) : null }
const emptyLead = (kind) => ({ kind, customer_name: '', contact_person: '', phone: '', place: '', address: '', district_id: '', notes: '' })
const SAMPLE = 'customer_name,contact_person,phone,place,district,address,notes\nBeena Stores,Beena,9847000111,Aluva,Ernakulam,Market Road,Asked about the monthly pickup plan'

function parseList(text, districts) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  if (!lines.length) return { rows: [], bad: [] }
  const split = (l) => { const o = []; let c = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { o.push(c.trim()); c = '' } else c += ch } o.push(c.trim()); return o }
  const head = split(lines[0]).map((h) => h.toLowerCase())
  const hasHead = head.includes('customer_name') || head.includes('name')
  const col = (r, k, alt) => { const i = head.indexOf(k) >= 0 ? head.indexOf(k) : head.indexOf(alt); return i >= 0 ? r[i] || '' : '' }
  const rows = [], bad = []
  lines.slice(hasHead ? 1 : 0).forEach((l, i) => {
    const r = split(l)
    const name = hasHead ? col(r, 'customer_name', 'name') : r[0]
    if (!name || name.length < 2) return bad.push(`Row ${i + 1}: no name`)
    const dn = hasHead ? col(r, 'district') : r[4]
    const d = dn ? districts.find((x) => x.name.toLowerCase() === dn.toLowerCase()) : null
    if (dn && !d) return bad.push(`Row ${i + 1} (${name}): district "${dn}" not found`)
    const ph = phone10(hasHead ? col(r, 'phone') : r[2])
    if (ph && !/^[6-9]\d{9}$/.test(ph)) return bad.push(`Row ${i + 1} (${name}): phone is not a valid mobile number`)
    rows.push({ customer_name: name, contact_person: (hasHead ? col(r, 'contact_person') : r[1]) || null, phone: ph,
      place: (hasHead ? col(r, 'place') : r[3]) || null, district_id: d ? d.id : null,
      address: (hasHead ? col(r, 'address') : r[5]) || null, notes: (hasHead ? col(r, 'notes', 'note') : r[6]) || null })
  })
  return { rows, bad }
}

function importSheet(S, kind) {
  const parsed = parseList(S.text, S.districts)
  return Sheet({ title: 'Import a list of leads', close: 'closeImport', body: html`
    <p class="muted small" style="margin-top:0">Paste rows from Excel or a CSV file. Columns, in this order:</p>
    <pre class="card small" style="white-space:pre-wrap;margin:0 0 12px">${SAMPLE}</pre>
    <label>Rows<textarea rows="7" data-bind="text" data-live placeholder="${SAMPLE}">${S.text}</textarea></label>
    ${S.text ? html`<p class="notice small"><span>${parsed.rows.length} ready${parsed.bad.length ? `, ${parsed.bad.length} with a problem` : ''}.</span></p>` : ''}
    ${parsed.bad.slice(0, 6).map((b) => html`<p class="error small" style="margin:2px 0">${b}</p>`)}
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy || !parsed.rows.length ? raw('disabled') : ''} data-act="runImport">${S.busy ? 'Importing…' : `Add ${parsed.rows.length || ''} leads`}</button>` })
}

function addSheet(S) {
  const v = S.v
  return Sheet({ title: 'Add a lead', close: 'closeForm', body: html`
    <label>Name<input data-bind="v.customer_name" value="${v.customer_name}"></label>
    <div class="grid2">
      <label>Contact person<input data-bind="v.contact_person" value="${v.contact_person}"></label>
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="v.phone" value="${v.phone}"></label>
    </div>
    <div class="grid2">
      <label>Place<input data-bind="v.place" value="${v.place}"></label>
      <label>District<select data-bind="v.district_id"><option value="">Choose…</option>${S.districts.map((d) => opt(d.id, v.district_id, d.name))}</select></label>
    </div>
    <label>Address<input data-bind="v.address" value="${v.address}"></label>
    <label>Notes<input data-bind="v.notes" value="${v.notes}" placeholder="Where this lead came from, what they want…"></label>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="add" data-another="">${S.busy ? 'Saving…' : 'Add lead'}</button>
    <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="add" data-another="1">Add and add another</button>` })
}

// one lead in a sheet: call, pick a status, pick a temperature, note, next follow-up. props: { lead }. Parent actions: leadClose, leadChanged.
export const leadSheet = {
  state: (ctx) => { const l = ctx.props.lead; return { lead: l, events: [], status: l.status, temperature: l.temperature || '', note: l.tc_note || '', next: l.next_followup_on || '', lost: l.lost_reason || '', busy: false, err: '' } },
  async init() { await this.actions.loadEvents.call(this) },
  view(S) {
    const lead = S.lead, closed = ['converted', 'lost'].includes(lead.status)
    const choices = ['contacted', 'interested', 'not_interested', 'converted', 'lost']
    return Sheet({ title: lead.customer_name, close: 'close', body: html`
      <div class="row wrap">${html`<span class="pill ${(TC_STATUS[lead.status] || {}).tone || ''}">${(TC_STATUS[lead.status] || {}).label || lead.status}</span>`}
        ${lead.temperature ? html`<span class="pill ${(TC_TEMP[lead.temperature] || {}).tone || ''}">${(TC_TEMP[lead.temperature] || {}).label}</span>` : ''}</div>
      <div class="summary" style="margin:12px 0">
        ${lead.contact_person ? html`<div class="summary-row"><span>Contact</span><span>${lead.contact_person}</span></div>` : ''}
        ${lead.phone ? html`<div class="summary-row"><span>Phone</span><span><a href="tel:${lead.phone}" class="btn sm primary">${Icon('phone', 16)} Call ${lead.phone}</a></span></div>` : ''}
        <div class="summary-row"><span>Where</span><span>${[lead.place, lead.address].filter(Boolean).join(', ') || '—'}</span></div>
        ${lead.notes ? html`<div class="summary-row"><span>Notes</span><span>${lead.notes}</span></div>` : ''}
        <div class="summary-row"><span>Added</span><span>${fmtDate(lead.created_at)}</span></div>
      </div>
      ${closed ? html`<p class="notice ${lead.status === 'converted' ? 'ok' : 'bad'} small"><span>This lead is closed${lead.status === 'lost' && lead.lost_reason ? `: ${lead.lost_reason}` : '.'}</span></p>` : html`
        <div class="field-label">How did the call go?</div>
        <div class="chips">${choices.map((c) => html`<button class="chip${S.status === c ? ' on' : ''}" aria-pressed="${S.status === c}" data-act="setStatus" data-k="${c}">${TC_STATUS[c].label}</button>`)}</div>
        <div class="field-label" style="margin-top:10px">How interested are they?</div>
        <div class="chips">${Object.entries(TC_TEMP).map(([k, v]) => html`<button class="chip${S.temperature === k ? ' on' : ''}" aria-pressed="${S.temperature === k}" data-act="setTemp" data-k="${k}">${v.label}</button>`)}</div>
        ${S.status === 'lost' ? html`<label>Why was it lost?<input data-bind="lost" value="${S.lost}" placeholder="Not interested, wrong number, already a customer…"></label>` : ''}
        <label>Note<textarea rows="3" data-bind="note" placeholder="What was discussed">${S.note}</textarea></label>
        ${!['converted', 'lost'].includes(S.status) ? html`<label>Next follow-up date<input type="date" min="${istDate()}" data-bind="next" value="${S.next}"></label>` : ''}
        ${errLine(S.err)}
        <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Save call'}</button>`}
      ${S.events.length > 0 ? html`<div class="field-label" style="margin-top:18px">Call history</div>
        <ul class="trail">${S.events.map((e) => html`<li><b>${(TC_STATUS[e.to_status] || {}).label || e.to_status}</b>${e.to_temperature ? ` · ${(TC_TEMP[e.to_temperature] || {}).label}` : ''} <span class="muted small">${fmtDate(e.at)}${e.note ? ` · ${e.note}` : ''}</span></li>`)}</ul>` : ''}` })
  },
  actions: {
    close() { const p = this.ctx.parent; p.actions.leadClose.call(p) },
    loadEvents() {
      return supabase.from('tc_lead_events').select('*').eq('lead_id', this.S.lead.id).order('at', { ascending: false }).then(({ data }) => this.set({ events: data || [] }))
    },
    setStatus(el) { this.set({ status: el.dataset.k }) },
    setTemp(el) { this.set({ temperature: el.dataset.k }) },
    async save() {
      const S = this.S
      this.set({ err: '' })
      if (S.status === 'lost' && S.lost.trim().length < 5) return this.set({ err: 'Say why this lead was lost.' })
      this.set({ busy: true })
      const { data: row, error } = await supabase.from('tc_leads')
        .update({ status: S.status, temperature: S.temperature || null, tc_note: S.note || null, next_followup_on: ['converted', 'lost'].includes(S.status) ? null : (S.next || null), lost_reason: S.status === 'lost' ? S.lost.trim() : null })
        .eq('id', S.lead.id).select().single()
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ lead: row })
      toast('Call saved')
      this.actions.loadEvents.call(this)
      const p = this.ctx.parent
      p.actions.leadChanged.call(p)
    },
  },
}

function page(kind, title, sub) {
  return {
    state: (ctx) => ({ rows: null, districts: [], err: '', f: ctx.route.filter || 'open', q: '', open: null, form: null, v: emptyLead(kind), text: '', importing: false, busy: false }),
    widgets: { lead: leadSheet },
    async init() { await this.actions.load.call(this) },
    view(S) {
      if (S.err && !S.rows) return html`<p class="error">${S.err}</p>`
      if (!S.rows) return Loading('Loading your leads…')
      const today = istDate()
      const test = (k, l) => k === 'open' ? TC_OPEN.includes(l.status) : k === 'all' ? true
        : k === 'follow' ? TC_OPEN.includes(l.status) && l.next_followup_on && l.next_followup_on <= today : l.status === k
      const s = S.q.trim().toLowerCase()
      const list = S.rows.filter((l) => test(S.f, l) && (!s || `${l.customer_name} ${l.place} ${l.phone} ${l.contact_person}`.toLowerCase().includes(s)))
      return html`${PageHead({ label: 'Telecalling', title, sub, actions: html`<button class="btn" data-act="openImport">${Icon('upload', 18)} Import list</button><button class="btn primary" data-act="openForm">${Icon('plus', 18)} Add lead</button>` })}
        <div class="toolbar"><div class="search">${Icon('search', 18)}<input placeholder="Search name, place, phone" data-bind="q" data-live value="${S.q}"></div></div>
        <div class="chips" style="margin-bottom:12px">${FILTERS.map(([k, l]) => html`<button class="chip${S.f === k ? ' on' : ''}" aria-pressed="${S.f === k}" data-act="filter" data-k="${k}">${l} (${S.rows.filter((x) => test(k, x)).length})</button>`)}</div>
        ${list.length === 0 ? Empty(S.rows.length ? 'No leads match.' : 'No leads yet. Head Office will assign you some to call.') : html`<ul class="list">${list.map((l) => html`<li data-key="${l.id}">
          <button class="item" data-act="open" data-id="${l.id}">
            <div class="grow">
              <div class="title">${l.customer_name}</div>
              <div class="muted small">${[l.place, l.phone].filter(Boolean).join(' · ') || '—'}</div>
              <div class="muted small">${l.status === 'new' ? 'Not called yet' : l.next_followup_on ? `Follow-up ${fmtDate(l.next_followup_on)}` : ''}${l.next_followup_on && l.next_followup_on < today && TC_OPEN.includes(l.status) ? html`<span class="text-bad"> · overdue</span>` : ''}</div>
            </div>
            <div class="col" style="align-items:flex-end;gap:4px">
              <span class="pill ${(TC_STATUS[l.status] || {}).tone || ''}">${(TC_STATUS[l.status] || {}).label || l.status}</span>
              ${l.temperature ? html`<span class="pill ${(TC_TEMP[l.temperature] || {}).tone || ''}">${(TC_TEMP[l.temperature] || {}).label}</span>` : ''}
            </div>
          </button></li>`)}</ul>`}
        ${S.open ? widget(this, 'lead', S.open.id, { lead: S.open }) : ''}
        ${S.form ? addSheet(S) : ''}${S.importing ? importSheet(S, kind) : ''}`
    },
    actions: {
      filter(el) { this.set({ f: el.dataset.k }) },
      open(el) { this.set({ open: this.S.rows.find((l) => l.id === el.dataset.id) }) },
      leadClose() { this.set({ open: null }) },
      async leadChanged() { await this.actions.load.call(this) },
      async load() {
        const [l, d] = await Promise.all([
          supabase.from('tc_leads').select('*').eq('kind', kind).order('created_at', { ascending: false }),
          supabase.from('districts').select('id, name').order('name'),
        ])
        if (l.error) return this.set({ err: errText(l.error) })
        this.set({ rows: l.data, districts: d.data || [] })
      },
      openForm() { this.set({ form: true, err: '', v: emptyLead(kind) }) },
      closeForm() { this.set({ form: false }) },
      async add(el) {
        const S = this.S, v = S.v, another = !!el.dataset.another
        this.set({ err: '' })
        if (v.customer_name.trim().length < 2) return this.set({ err: 'Enter the name.' })
        if (v.phone && !/^[6-9]\d{9}$/.test(phone10(v.phone) || '')) return this.set({ err: 'Enter a valid 10-digit mobile number.' })
        this.set({ busy: true })
        const { error } = await supabase.from('tc_leads').insert({
          kind, customer_name: v.customer_name.trim(), contact_person: v.contact_person.trim() || null, phone: phone10(v.phone),
          district_id: v.district_id ? Number(v.district_id) : null, place: v.place.trim() || null, address: v.address.trim() || null,
          notes: v.notes.trim() || null,
        })
        this.set({ busy: false })
        if (error) return this.set({ err: errText(error) })
        toast('Lead added')
        if (another) this.set({ v: emptyLead(kind) })
        else this.set({ form: false })
        await this.actions.load.call(this)
      },
      openImport() { this.set({ importing: true, err: '', text: '' }) },
      closeImport() { this.set({ importing: false }) },
      async runImport() {
        const S = this.S
        const parsed = parseList(S.text, S.districts)
        this.set({ err: '' })
        if (!parsed.rows.length) return this.set({ err: 'Nothing to import yet.' })
        if (parsed.bad.length && !confirm(`${parsed.bad.length} row(s) will be skipped. Import the other ${parsed.rows.length}?`)) return
        this.set({ busy: true })
        const { error } = await supabase.from('tc_leads').insert(parsed.rows.map((r) => ({ ...r, kind })))
        this.set({ busy: false })
        if (error) return this.set({ err: errText(error) })
        toast(`${parsed.rows.length} leads added`)
        this.set({ importing: false })
        await this.actions.load.call(this)
      },
    },
  }
}

export const salesLeads = page('sales', 'Sales leads', 'Customers to call about buying a scrap pickup plan.')
export const franchiseLeads = page('franchise', 'Franchise leads', 'People who asked about opening a Scrappy franchise.')
