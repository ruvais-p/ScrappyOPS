/* Head Office: give leads to a telecaller (sales leads or franchise-partner leads) and see how the calls are going. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../ui.js'
import { fmtDate } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'
import { TC_STATUS, TC_TEMP, TC_OPEN, KIND_LABEL } from '../../tc.js'

const phone10 = (s) => { const d = (s || '').replace(/\D/g, ''); return d ? d.slice(-10) : null }
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`
const emptyLead = (tcId) => ({ kind: 'sales', customer_name: '', contact_person: '', phone: '', place: '', address: '', district_id: '', notes: '', assigned_to: tcId || '' })
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

function assignSheet(S) {
  const { tcs, districts } = S, v = S.v
  return Sheet({ title: 'Give a lead to a telecaller', close: 'closeForm', body: html`
    <label>Telecaller<select data-bind="v.assigned_to"><option value="">Choose…</option>${tcs.filter((t) => t.is_active).map((t) => opt(t.id, v.assigned_to, t.full_name))}</select></label>
    <label>Kind<select data-bind="v.kind">${Object.entries(KIND_LABEL).map(([k, l]) => opt(k, v.kind, l))}</select></label>
    <label>Name<input data-bind="v.customer_name" value="${v.customer_name}"></label>
    <div class="grid2">
      <label>Contact person<input data-bind="v.contact_person" value="${v.contact_person}"></label>
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="v.phone" value="${v.phone}"></label>
    </div>
    <div class="grid2">
      <label>Place<input data-bind="v.place" value="${v.place}"></label>
      <label>District<select data-bind="v.district_id"><option value="">Choose…</option>${districts.map((d) => opt(d.id, v.district_id, d.name))}</select></label>
    </div>
    <label>Address<input data-bind="v.address" value="${v.address}"></label>
    <label>Notes for the telecaller<input data-bind="v.notes" value="${v.notes}" placeholder="Where this lead came from, what they want…"></label>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="assign" data-another="">${S.busy ? 'Saving…' : 'Give lead'}</button>
    <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="assign" data-another="1">Give and add another</button>` })
}

function importSheet(S) {
  const { tcs, districts } = S
  const parsed = parseList(S.text, districts)
  return Sheet({ title: 'Import a list of leads', close: 'closeForm', body: html`
    <p class="muted small" style="margin-top:0">Paste rows from Excel or a CSV file. All of them go to one telecaller. Columns, in this order:</p>
    <pre class="card small" style="white-space:pre-wrap;margin:0 0 12px">${SAMPLE}</pre>
    <label>Kind<select data-bind="ikind">${Object.entries(KIND_LABEL).map(([k, l]) => opt(k, S.ikind, l))}</select></label>
    <label>Give these leads to<select data-bind="itc"><option value="">Choose…</option>${tcs.filter((t) => t.is_active).map((t) => opt(t.id, S.itc, t.full_name))}</select></label>
    <label>Rows<textarea rows="7" data-bind="text" data-live placeholder="${SAMPLE}">${S.text}</textarea></label>
    ${S.text ? html`<p class="notice small"><span>${parsed.rows.length} ready${parsed.bad.length ? `, ${parsed.bad.length} with a problem` : ''}.</span></p>` : ''}
    ${parsed.bad.slice(0, 6).map((b) => html`<p class="error small" style="margin:2px 0">${b}</p>`)}
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy || !parsed.rows.length ? raw('disabled') : ''} data-act="runImport">${S.busy ? 'Importing…' : `Give ${parsed.rows.length || ''} leads`}</button>` })
}

function detailSheet(S) {
  const { tcs, districts } = S, lead = S.open
  const tcName = (id) => (tcs.find((t) => t.id === id) || {}).full_name || '—'
  return Sheet({ title: lead.customer_name, close: 'closeOpen', body: html`
    <div class="row wrap"><span class="pill tiny">${KIND_LABEL[lead.kind]}</span>
      <span class="pill ${(TC_STATUS[lead.status] || {}).tone || ''}">${(TC_STATUS[lead.status] || {}).label || lead.status}</span>
      ${lead.temperature ? html`<span class="pill ${(TC_TEMP[lead.temperature] || {}).tone || ''}">${(TC_TEMP[lead.temperature] || {}).label}</span>` : ''}</div>
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Contact</span><span>${[lead.contact_person, lead.phone].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Where</span><span>${[lead.place, (districts.find((d) => d.id === lead.district_id) || {}).name].filter(Boolean).join(', ') || '—'}</span></div>
      <div class="summary-row"><span>Added</span><span>${fmtDate(lead.created_at)}</span></div>
      ${lead.next_followup_on ? html`<div class="summary-row"><span>Next follow-up</span><span>${fmtDate(lead.next_followup_on)}</span></div>` : ''}
    </div>
    ${lead.tc_note ? html`<p class="notice info small"><span><b>Telecaller's note:</b> ${lead.tc_note}</span></p>` : ''}
    ${lead.lost_reason ? html`<p class="notice bad small"><span><b>Lost because:</b> ${lead.lost_reason}</span></p>` : ''}
    <label>Telecaller<select data-bind="oto">${tcs.map((t) => opt(t.id, S.oto, t.full_name))}</select></label>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="reassign">Save</button>
    ${S.events.length > 0 ? html`<div class="field-label" style="margin-top:18px">Call history</div>
      <ul class="trail">${S.events.map((e) => html`<li><b>${(TC_STATUS[e.to_status] || {}).label || e.to_status}</b>${e.to_temperature ? ` · ${(TC_TEMP[e.to_temperature] || {}).label}` : ''} <span class="muted small">${fmtDate(e.at)}${e.note ? ` · ${e.note}` : ''}</span></li>`)}</ul>` : ''}` })
}

export default {
  state: (ctx) => ({ rows: null, tcs: [], districts: [], err: '', kind: '', tcId: ctx.route.telecallerId || '', st: '', q: '', form: null, v: emptyLead(ctx.route.telecallerId),
    text: '', ikind: 'sales', itc: ctx.route.telecallerId || '', importing: false, open: null, events: [], oto: '', busy: false }),
  async init() { await this.actions.load.call(this) },
  view(S) {
    if (S.err && !S.rows) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading leads…')
    const tcName = (id) => (S.tcs.find((t) => t.id === id) || {}).full_name || '—'
    const dName = (id) => (S.districts.find((d) => d.id === id) || {}).name
    const q = S.q.trim().toLowerCase()
    const list = S.rows.filter((l) => (!S.kind || l.kind === S.kind) && (!S.tcId || l.assigned_to === S.tcId) && (!S.st || (S.st === 'open' ? TC_OPEN.includes(l.status) : l.status === S.st))
      && (!q || `${l.customer_name} ${l.place} ${l.phone} ${tcName(l.assigned_to)}`.toLowerCase().includes(q)))
    const hot = S.rows.filter((l) => l.temperature === 'hot' && TC_OPEN.includes(l.status)).length
    return html`${PageHead({ label: 'Telecalling', title: 'Telecalling', sub: 'Give sales leads and franchise-partner leads to a telecaller, and see how the calls are going.',
        actions: html`<button class="btn" data-act="openImport">${Icon('upload', 18)} Import list</button><button class="btn primary" data-act="openForm">${Icon('plus', 18)} Give a lead</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Leads', value: S.rows.length })}
        ${Stat({ label: 'Open', value: S.rows.filter((l) => TC_OPEN.includes(l.status)).length })}
        ${Stat({ label: 'Hot, open', value: hot, tone: hot ? 'warn' : '' })}
        ${Stat({ label: 'Converted', value: S.rows.filter((l) => l.status === 'converted').length, tone: 'ok' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search name, place, phone, telecaller" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="kind" data-live aria-label="Kind"><option value="">Sales and franchise</option>${Object.entries(KIND_LABEL).map(([k, l]) => opt(k, S.kind, l))}</select>
        <select data-bind="tcId" data-live aria-label="Telecaller"><option value="">Every telecaller</option>${S.tcs.map((t) => opt(t.id, S.tcId, t.full_name))}</select>
        <select data-bind="st" data-live aria-label="Status"><option value="">Any status</option><option value="open" ${S.st === 'open' ? raw('selected') : ''}>All open</option>${Object.entries(TC_STATUS).map(([k, v]) => opt(k, S.st, v.label))}</select>
      </div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No leads match.' : 'No leads given yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Name</th><th>Kind</th><th>Telecaller</th><th>Where</th><th>Status</th><th>Temperature</th><th>Follow-up</th><th>Added</th></tr></thead>
        <tbody>${list.map((l) => html`<tr data-act="openLead" data-id="${l.id}" style="cursor:pointer">
          <td><b>${l.customer_name}</b><div class="muted small">${l.phone || ''}</div></td>
          <td><span class="pill tiny">${KIND_LABEL[l.kind]}</span></td>
          <td>${tcName(l.assigned_to)}</td>
          <td style="white-space:normal">${[l.place, dName(l.district_id)].filter(Boolean).join(', ') || '—'}</td>
          <td><span class="pill ${(TC_STATUS[l.status] || {}).tone || ''}">${(TC_STATUS[l.status] || {}).label || l.status}</span></td>
          <td>${l.temperature ? html`<span class="pill ${(TC_TEMP[l.temperature] || {}).tone || ''}">${(TC_TEMP[l.temperature] || {}).label}</span>` : html`<span class="muted">—</span>`}</td>
          <td>${l.next_followup_on ? fmtDate(l.next_followup_on) : '—'}</td><td>${fmtDate(l.created_at)}</td></tr>`)}</tbody></table></div>`}
      ${S.form ? assignSheet(S) : ''}${S.importing ? importSheet(S) : ''}${S.open ? detailSheet(S) : ''}`
  },
  actions: {
    async load() {
      const [l, p, d] = await Promise.all([
        supabase.from('tc_leads').select('*').order('created_at', { ascending: false }),
        supabase.from('profiles').select('id, full_name, is_active').eq('role', 'telecaller').order('full_name'),
        supabase.from('districts').select('id, name').order('name'),
      ])
      if (l.error || p.error || d.error) return this.set({ err: errText(l.error || p.error || d.error) })
      this.set({ rows: l.data, tcs: p.data, districts: d.data })
    },
    openForm() { this.set({ form: true, err: '', v: emptyLead(this.S.tcId) }) },
    closeForm() { this.set({ form: false }); this.actions.load.call(this) },
    openImport() { this.set({ importing: true, err: '', text: '', ikind: 'sales', itc: this.S.tcId || '' }) },
    closeImport() { this.set({ importing: false }); this.actions.load.call(this) },
    async runImport() {
      const S = this.S
      const parsed = parseList(S.text, S.districts)
      this.set({ err: '' })
      if (!S.itc) return this.set({ err: 'Choose the telecaller who gets these leads.' })
      if (!parsed.rows.length) return this.set({ err: 'Nothing to import yet.' })
      if (parsed.bad.length && !confirm(`${parsed.bad.length} row(s) will be skipped. Import the other ${parsed.rows.length}?`)) return
      this.set({ busy: true })
      const { error } = await supabase.from('tc_leads').insert(parsed.rows.map((r) => ({ ...r, kind: S.ikind, assigned_to: S.itc })))
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast(`${parsed.rows.length} leads given`)
      this.actions.closeImport.call(this)
    },
    async assign(el) {
      const S = this.S, v = S.v, another = !!el.dataset.another
      this.set({ err: '' })
      if (!v.assigned_to) return this.set({ err: 'Choose the telecaller.' })
      if (v.customer_name.trim().length < 2) return this.set({ err: 'Enter the name.' })
      if (v.phone && !/^[6-9]\d{9}$/.test(phone10(v.phone) || '')) return this.set({ err: 'Enter a valid 10-digit mobile number.' })
      this.set({ busy: true })
      const { error } = await supabase.from('tc_leads').insert({
        kind: v.kind, customer_name: v.customer_name.trim(), contact_person: v.contact_person.trim() || null, phone: phone10(v.phone),
        district_id: v.district_id ? Number(v.district_id) : null, place: v.place.trim() || null, address: v.address.trim() || null,
        notes: v.notes.trim() || null, assigned_to: v.assigned_to,
      })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Lead given')
      if (another) this.set({ v: { ...v, customer_name: '', contact_person: '', phone: '', place: '', address: '', notes: '' } })
      else this.actions.closeForm.call(this)
    },
    async openLead(el) {
      const lead = this.S.rows.find((l) => l.id === el.dataset.id)
      this.set({ open: lead, oto: lead.assigned_to, events: [], err: '' })
      const { data } = await supabase.from('tc_lead_events').select('*').eq('lead_id', lead.id).order('at', { ascending: false })
      this.set({ events: data || [] })
    },
    closeOpen() { this.set({ open: null }) },
    async reassign() {
      const S = this.S
      this.set({ busy: true, err: '' })
      const { error } = await supabase.from('tc_leads').update({ assigned_to: S.oto }).eq('id', S.open.id)
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Saved')
      this.set({ open: null })
      await this.actions.load.call(this)
    },
  },
}
