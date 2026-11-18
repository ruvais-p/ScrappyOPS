import { html, raw, supabase, errText, toast } from '../core.js'
import { Loading, Icon, PageHead, Empty, StageMeter, typeShort, MODE_ICON } from '../ui.js'
import { LSGD_TYPES, STAGES, DESIGNATIONS, INTEREST, UNIT_PRICE, stageLabel, financialYear, fmtDate, fmtINR, istDate, addDays } from '../lib.js'
import { Sheet, errLine, chk, dis } from '../kit.js'
import { visitWidget, VisitList } from './visits.js'
import { followupWidget, FollowupList } from './followups.js'

const WON = ['work_order', 'supplied', 'payment_received']
const MODES = [['visit', 'Visit'], ['call', 'Call'], ['whatsapp', 'WhatsApp'], ['email', 'Email']]
const MODE_LABEL = Object.fromEntries(MODES)
const emptyContact = () => ({ id: null, name: '', designation: DESIGNATIONS[0], phone: '', email: '', is_decision_maker: false })
const cleanPhone = (p) => p.replace(/\D/g, '').slice(-10)
const validPhone = (p) => /^[6-9]\d{9}$/.test(cleanPhone(p))

// the LSGDs of my territory
export default {
  state: { rows: null, q: '', show: 'all', err: '' },
  async init() {
    const { data, error } = await supabase.from('lsgds')
      .select('id, name, type, assigned_tso, districts(name), opportunities(stage, expected_units, financial_year), visits(check_in_at), lsgd_updates(happened_on)').order('name')
    if (error) return this.set({ err: errText(error) })
    this.set({ rows: data })
  },
  view(S) {
    const fy = financialYear()
    const s = S.q.trim().toLowerCase()
    const list = (S.rows || [])
      .filter((l) => !s || l.name.toLowerCase().includes(s) || l.districts.name.toLowerCase().includes(s))
      .map((l) => ({ ...l, opp: l.opportunities.find((o) => o.financial_year === fy), last: l.visits.map((v) => v.check_in_at).sort().at(-1),
        updated: l.lsgd_updates.map((u) => u.happened_on).sort().at(-1) }))
      .filter((l) => S.show === 'all' || (S.show === 'never' ? !l.last : S.show === 'won' ? WON.includes(l.opp && l.opp.stage) : l.opp && !['lost', ...WON].includes(l.opp.stage)))
    return html`${PageHead({ label: 'Your territory', title: 'LSGDs', sub: S.rows ? `${S.rows.length} LSGDs in your districts` : null })}
      <div class="search">${Icon('search', 18)}<input placeholder="Search LSGD or district" data-bind="q" data-live value="${S.q}"></div>
      <div class="chips" style="margin:10px 0">${[['all', 'All'], ['never', 'Never visited'], ['open', 'In progress'], ['won', 'Ordered']].map(([k, l]) =>
        html`<button class="chip${S.show === k ? ' on' : ''}" data-act="filter" data-k="${k}">${l}</button>`)}</div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading() : list.length === 0 ? Empty('No LSGDs match.') : html`<ul class="list">${list.map((l) => html`<li data-key="${l.id}">
        <button class="item" data-act="open" data-id="${l.id}">
          <span class="lsgd-mark">${typeShort(l.type)}</span>
          <div class="grow">
            <div class="title">${l.name}</div>
            <div class="muted small">${l.districts.name} · ${l.last ? `visited ${fmtDate(l.last)}` : html`<span class="text-warn">never visited</span>`}${l.updated ? ` · updated ${fmtDate(l.updated)}` : ''}</div>
            ${l.opp ? StageMeter(l.opp.stage) : ''}
          </div>
          <span class="pill ${l.opp ? 'stage-' + l.opp.stage : ''}">${l.opp ? stageLabel(l.opp.stage) : 'No deal'}</span>
        </button></li>`)}</ul>`}`
  },
  actions: {
    filter(el) { this.set({ show: el.dataset.k }) },
    open(el) { this.ctx.go('lsgd', { lsgdId: el.dataset.id }) },
  },
}

// a person's details: used both to add someone to the LSGD and to correct them; `p` is the state path being bound
function ContactFields(c, p) {
  return html`<label>Name<input data-bind="${p}.name" data-live value="${c.name}"></label>
    <label>Designation<select data-bind="${p}.designation">${DESIGNATIONS.map((x) => html`<option ${raw(x === c.designation ? 'selected' : '')}>${x}</option>`)}</select></label>
    <div class="grid2">
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="${p}.phone" value="${c.phone}" placeholder="10 digits"></label>
      <label>Email (optional)<input type="email" data-bind="${p}.email" value="${c.email}"></label>
    </div>
    <label class="check"><input type="checkbox" data-bind="${p}.is_decision_maker" ${chk(c.is_decision_maker)}> Can decide on purchase</label>`
}

function contactError(c) {
  if (!c.name.trim()) return 'Enter the person\'s name.'
  if (!validPhone(c.phone)) return `Enter a valid 10-digit mobile number for ${c.name.trim()}.`
  return ''
}

function contactSheet(S) {
  const editing = !!S.c.id
  return Sheet({ title: editing ? 'Edit contact' : 'Add a contact', body: html`
    ${ContactFields(S.c, 'c')}
    ${editing ? html`<p class="small muted">Once your manager confirms this person by phone, the details are locked.</p>` : ''}
    ${errLine(S.sErr)}
    <button class="btn primary block" ${dis(S.busy)} data-act="saveContact">${S.busy ? 'Saving…' : editing ? 'Save changes' : 'Add contact'}</button>` })
}

function updateSheet(S, d) {
  const value = (Number(S.units) || 0) * UNIT_PRICE
  const named = S.newContacts.filter((c) => c.name.trim())
  return Sheet({ title: 'Update status', body: html`
    <p class="small muted" style="margin-top:0">Record work done on this LSGD without checking in: a meeting before the app, a phone call or a message. It goes into the LSGD's history. It is not a visit, so it does not count for TA / DA.</p>

    <div class="field-label">When did it happen?</div>
    <input type="date" max="${istDate()}" data-bind="uOn" data-live value="${S.uOn}" aria-label="Date it happened">
    <div class="field-label">How?</div>
    <div class="chips" role="radiogroup" aria-label="How">${MODES.map(([k, l]) => html`<button role="radio" aria-checked="${S.uMode === k}" class="chip${S.uMode === k ? ' on' : ''}" data-act="uMode" data-k="${k}">${Icon(MODE_ICON[k], 16)} ${l}</button>`)}</div>

    <div class="field-label">Who did you talk to?</div>
    ${d.contacts.length ? html`<div class="people">${d.contacts.map((c) => {
      const on = S.met.includes(c.id)
      return html`<label class="person${on ? ' on' : ''}"><input type="checkbox" data-change="toggleMet" data-id="${c.id}" ${chk(on)}>
        <span class="grow"><b>${c.name}</b><span class="muted small" style="display:block">${c.designation}${c.phone ? ` · ${c.phone}` : ''}</span></span></label>`
    })}</div>` : ''}
    ${S.newContacts.map((c, i) => html`<div class="card">
      <div class="row"><b class="grow">New person</b><button class="icon-btn" data-act="removeNew" data-i="${i}" aria-label="Remove">${Icon('x', 18)}</button></div>
      ${ContactFields(c, `newContacts.${i}`)}</div>`)}
    <button class="btn block" data-act="addNew">${Icon('plus', 18)} Add a new person</button>

    <label>What did they say?
      <textarea rows="4" data-bind="discussion" data-live placeholder="e.g. Met the secretary in June. They want 150 units in next year's plan and asked for a proposal.">${S.discussion}</textarea></label>
    <div class="small muted" style="text-align:right;margin-top:-6px">${S.discussion.trim().length < 20 ? `${20 - S.discussion.trim().length} more characters` : '✓'}</div>
    <label>Next step they agreed to<input data-bind="outcome" value="${S.outcome}" placeholder="e.g. Send proposal by Friday"></label>
    <div class="field-label">How interested are they?</div>
    <div class="chips" role="radiogroup" aria-label="Interest level">${INTEREST.map((t, i) => html`<button role="radio" aria-checked="${S.interest === i + 1}" class="chip${S.interest === i + 1 ? ' on' : ''}" data-act="interest" data-n="${i + 1}">${t}</button>`)}</div>

    <div class="card">
      <h3 style="margin-top:0">Deal ${financialYear()}</h3>
      <label style="margin-top:0">Where is this LSGD now?
        <select data-bind="stage" data-change="setStage">${STAGES.map((s) => html`<option value="${s.id}" ${raw(s.id === S.stage ? 'selected' : '')}>${s.label}</option>`)}</select></label>
      <div class="grid2">
        <label>Expected units<input type="number" inputmode="numeric" min="0" data-bind="units" data-live value="${S.units}" placeholder="0"></label>
        <label>Chance of order %<input type="number" inputmode="numeric" min="0" max="100" data-bind="prob" data-live value="${S.prob}"></label>
      </div>
      <label>Expected order month<input type="month" data-bind="closeMonth" value="${S.closeMonth}"></label>
      <div class="notice info" style="margin-bottom:0">Order value <b>${fmtINR(value)}</b> · likely <b>${fmtINR(value * (Number(S.prob) || 0) / 100)}</b></div>
    </div>

    <label class="check"><input type="checkbox" data-bind="fuOn" data-live ${chk(S.fuOn)}> Set a follow-up</label>
    ${S.fuOn ? html`<div class="card">
      <div class="chips" role="radiogroup" aria-label="Follow-up type">${MODES.map(([k, l]) => html`<button role="radio" aria-checked="${S.fuMode === k}" class="chip${S.fuMode === k ? ' on' : ''}" data-act="fuMode" data-k="${k}">${Icon(MODE_ICON[k], 16)} ${l}</button>`)}</div>
      <div class="grid2">
        <label>Date<input type="date" min="${istDate()}" data-bind="fuDate" data-live value="${S.fuDate}"></label>
        <label>With<select data-bind="fuContact"><option value="">Anyone</option>
          ${d.contacts.map((c) => html`<option value="${c.id}" ${raw(S.fuContact === c.id ? 'selected' : '')}>${c.name}</option>`)}
          ${named.map((c, i) => html`<option value="new:${i}" ${raw(S.fuContact === 'new:' + i ? 'selected' : '')}>${c.name}</option>`)}</select></label>
      </div>
      <label>Note<input data-bind="fuNote" value="${S.fuNote}" placeholder="e.g. Ask about DPC approval"></label>
    </div>` : ''}

    ${errLine(S.sErr)}
    <button class="btn primary block" ${dis(S.busy)} data-act="saveUpdate">${S.busy ? 'Saving…' : 'Save update'}</button>` })
}

function updateCheck(S) {
  if (!S.uOn) return 'Enter the date it happened.'
  if (S.uOn > istDate()) return 'The date can\'t be in the future.'
  const named = S.newContacts.filter((c) => c.name.trim())
  if (!S.met.length && !named.length) return 'Pick or add at least one person you talked to.'
  for (const c of named) { const e = contactError(c); if (e) return e }
  if (S.discussion.trim().length < 20) return 'Write a few lines about what they said (at least 20 characters).'
  if (S.fuOn && (!S.fuDate || S.fuDate < istDate())) return 'The follow-up date can\'t be in the past.'
  return ''
}

const UpdateList = (updates, contacts) => html`<ul class="trail">${updates.map((u) => {
  const people = u.contact_ids.map((id) => (contacts.find((c) => c.id === id) || {}).name).filter(Boolean)
  return html`<li>
    <b>${fmtDate(u.happened_on)} · ${MODE_LABEL[u.mode] || u.mode}</b>${u.interest_level ? html`<span class="pill tiny">${INTEREST[u.interest_level - 1]}</span>` : ''}
    <span class="muted small"> · ${(u.person && u.person.full_name) || ''}</span>
    ${people.length ? html`<div class="small muted">With ${people.join(', ')}</div>` : ''}
    <div class="small">${u.discussion}</div>
    ${u.outcome ? html`<div class="small"><b>Next step:</b> ${u.outcome}</div>` : ''}
  </li>`
})}</ul>`

export const detail = {
  state: {
    d: null, err: '', sheet: null, busy: false, sErr: '', c: emptyContact(),
    uOn: '', uMode: 'visit', met: [], newContacts: [], discussion: '', outcome: '', interest: 3,
    stage: 'first_meeting', units: '', prob: 10, closeMonth: '', fuOn: false, fuDate: '', fuMode: 'visit', fuNote: '', fuContact: '',
  },
  widgets: { followup: followupWidget, visit: visitWidget },
  async init() { await this.actions.reload.call(this) },
  view(S, ctx) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.d) return Loading()
    const d = S.d
    const opp = d.opps.find((o) => o.financial_year === financialYear())
    const field = ['tso', 'zonal_manager'].includes(ctx.profile.role)
    const tso = ctx.profile.role === 'tso'
    return html`<button class="link" data-act="back">← Back</button>
      <h1>${d.lsgd.name}</h1>
      <p class="muted">${LSGD_TYPES[d.lsgd.type]} · ${d.lsgd.districts.name}
        ${d.lsgd.office_lat != null ? html` · <a href="https://maps.google.com/?q=${d.lsgd.office_lat},${d.lsgd.office_lng}" target="_blank" rel="noreferrer">Office on map</a>` : ''}
      </p>
      <button class="btn primary block" data-act="visit">Start visit here</button>
      ${field ? html`<button class="btn block" data-act="openUpdate">${Icon('message', 18)} Update status · earlier work, call or message</button>` : ''}

      <section class="card">
        <h2>Deal ${financialYear()}</h2>
        ${opp ? html`<div class="kv">
          <div><span>Stage</span><b>${stageLabel(opp.stage)}</b></div>
          <div><span>Units</span><b>${opp.expected_units}</b></div>
          <div><span>Value</span><b>${fmtINR(opp.expected_value)}</b></div>
          <div><span>Chance</span><b>${opp.probability}%</b></div>
          ${opp.expected_close ? html`<div><span>Expected</span><b>${new Date(opp.expected_close).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</b></div>` : ''}
        </div>` : html`<p class="muted">No deal yet. It is created when you log a visit or update the status.</p>`}
      </section>

      <section class="card">
        <div class="row"><h2 class="grow">Contacts</h2>${field ? html`<button class="btn sm" data-act="openContact">${Icon('plus', 16)} Add</button>` : ''}</div>
        ${d.contacts.length === 0 ? html`<p class="muted">No contacts yet.</p>` : html`<ul class="list">${d.contacts.map((c) => html`<li class="item">
          <div class="grow">
            <div class="title">${c.name} ${c.is_decision_maker ? html`<span class="pill tiny">decision maker</span>` : ''}${c.verified_at ? html`<span class="pill ok tiny">verified</span>` : ''}</div>
            <div class="muted small">${c.designation}${c.phone ? ` · ${c.phone}` : ''}${c.email ? ` · ${c.email}` : ''}</div>
          </div>
          ${field && !(tso && c.verified_at) ? html`<button class="btn sm" data-act="editContact" data-id="${c.id}">Edit</button>` : ''}
          ${c.phone ? html`<a class="btn" href="tel:${c.phone}">Call</a>` : ''}
        </li>`)}</ul>`}
      </section>

      ${d.fus.length > 0 ? html`<section class="card"><h2>Open follow-ups</h2>${FollowupList(this, d.fus)}</section>` : ''}

      <section class="card">
        <h2>Status updates</h2>
        ${d.updates.length === 0 ? html`<p class="muted">No updates recorded yet.${field ? ' Use Update status to add work done before the app.' : ''}</p>` : UpdateList(d.updates, d.contacts)}
      </section>

      <section class="card">
        <h2>Visit history</h2>
        ${d.visits.length === 0 ? html`<p class="muted">Never visited.</p>` : VisitList(this, d.visits)}
      </section>
      ${S.sheet === 'update' ? updateSheet(S, d) : S.sheet === 'contact' ? contactSheet(S) : ''}`
  },
  actions: {
    back() { this.ctx.go(this.ctx.route.back || (this.ctx.kind === 'field' ? 'lsgds' : 'zlsgds')) },
    visit() { this.ctx.go('visit', { lsgdId: this.ctx.route.lsgdId }) },
    closeSheet() {
      if (this.S.sheet === 'update' && (this.S.discussion.trim() || this.S.newContacts.some((c) => c.name.trim()))
        && !confirm('Discard this update? What you entered will not be saved.')) return
      this.set({ sheet: null })
    },
    openContact() { this.set({ sheet: 'contact', c: emptyContact(), sErr: '' }) },
    editContact(el) {
      const c = this.S.d.contacts.find((x) => x.id === el.dataset.id)
      this.set({ sheet: 'contact', sErr: '', c: { id: c.id, name: c.name, designation: c.designation, phone: c.phone || '', email: c.email || '', is_decision_maker: c.is_decision_maker } })
    },
    async saveContact() {
      const { c } = this.S
      const e = contactError(c)
      if (e) return this.set({ sErr: e })
      this.set({ busy: true, sErr: '' })
      const row = { name: c.name.trim(), designation: c.designation, phone: cleanPhone(c.phone), email: c.email.trim() || null, is_decision_maker: c.is_decision_maker }
      const { error } = c.id
        ? await supabase.from('contacts').update(row).eq('id', c.id)
        : await supabase.from('contacts').insert({ ...row, lsgd_id: this.ctx.route.lsgdId })
      this.set({ busy: false })
      if (error) return this.set({ sErr: errText(error) })
      toast(c.id ? 'Contact updated' : 'Contact added')
      this.set({ sheet: null })
      await this.actions.reload.call(this)
    },
    openUpdate() {
      const opp = this.S.d.opps.find((o) => o.financial_year === financialYear())
      this.set({
        sheet: 'update', sErr: '', uOn: istDate(), uMode: 'visit', met: [], newContacts: [], discussion: '', outcome: '', interest: 3,
        stage: opp ? opp.stage : 'first_meeting', units: opp ? String(opp.expected_units || '') : '', prob: opp ? opp.probability : 10,
        closeMonth: opp && opp.expected_close ? opp.expected_close.slice(0, 7) : '',
        fuOn: false, fuDate: addDays(istDate(), 7), fuMode: 'visit', fuNote: '', fuContact: '',
      })
    },
    uMode(el) { this.set({ uMode: el.dataset.k }) },
    fuMode(el) { this.set({ fuMode: el.dataset.k }) },
    interest(el) { this.set({ interest: Number(el.dataset.n) }) },
    setStage(el) { const s = STAGES.find((x) => x.id === el.value); this.set({ stage: el.value, prob: s ? s.prob : this.S.prob }) },
    toggleMet(el) { const id = el.dataset.id; this.set({ met: el.checked ? [...this.S.met, id] : this.S.met.filter((x) => x !== id) }) },
    addNew() { this.set({ newContacts: [...this.S.newContacts, emptyContact()] }) },
    removeNew(el) { this.set({ newContacts: this.S.newContacts.filter((_, j) => j !== Number(el.dataset.i)) }) },
    async saveUpdate() {
      const S = this.S, lsgdId = this.ctx.route.lsgdId
      const v = updateCheck(S)
      if (v) return this.set({ sErr: v })
      this.set({ busy: true, sErr: '' })
      try {
        const named = S.newContacts.filter((c) => c.name.trim())
        let created = []
        if (named.length) {
          const { data, error } = await supabase.from('contacts').insert(named.map((c) => ({
            lsgd_id: lsgdId, name: c.name.trim(), designation: c.designation, phone: cleanPhone(c.phone), email: c.email.trim() || null, is_decision_maker: c.is_decision_maker,
          }))).select('id')
          if (error) throw error
          created = data.map((x) => x.id)
        }
        const { error: ue } = await supabase.from('lsgd_updates').insert({
          lsgd_id: lsgdId, happened_on: S.uOn, mode: S.uMode, contact_ids: [...S.met, ...created],
          discussion: S.discussion.trim(), outcome: S.outcome.trim() || null, interest_level: S.interest,
        })
        if (ue) throw ue
        const { data: opp, error: oe } = await supabase.from('opportunities').upsert({
          lsgd_id: lsgdId, financial_year: financialYear(), stage: S.stage, expected_units: Number(S.units) || 0, probability: Number(S.prob),
          expected_close: S.closeMonth ? S.closeMonth + '-01' : null,
        }, { onConflict: 'lsgd_id,financial_year' }).select().single()
        if (oe) throw oe
        if (S.fuOn) {
          const fuContact = S.fuContact.startsWith('new:') ? created[Number(S.fuContact.slice(4))] : S.fuContact || null
          const { error } = await supabase.from('followups').insert({
            lsgd_id: lsgdId, opportunity_id: opp.id, contact_id: fuContact, due_on: S.fuDate, mode: S.fuMode, notes: S.fuNote.trim() || null,
          })
          if (error) throw error
        }
        toast('Status updated')
        this.set({ sheet: null, newContacts: [], discussion: '' })
        await this.actions.reload.call(this)
      } catch (e) {
        this.set({ sErr: 'Could not save: ' + errText(e) })
      } finally { this.set({ busy: false }) }
    },
    async reload() {
      const id = this.ctx.route.lsgdId
      const [l, c, o, v, f, u] = await Promise.all([
        supabase.from('lsgds').select('*, districts(name)').eq('id', id).single(),
        supabase.from('contacts').select('*').eq('lsgd_id', id).order('created_at'),
        supabase.from('opportunities').select('*').eq('lsgd_id', id).order('financial_year', { ascending: false }),
        supabase.from('visits').select('*, lsgds(name, districts(name)), visit_contacts(contacts(name, designation))').eq('lsgd_id', id).order('check_in_at', { ascending: false }).limit(20),
        supabase.from('followups').select('*, lsgds(name), contacts(name, designation, phone)').eq('lsgd_id', id).is('done_at', null).order('due_on'),
        supabase.from('lsgd_updates').select('*, person:profiles!lsgd_updates_tso_id_fkey(full_name)').eq('lsgd_id', id)
          .order('happened_on', { ascending: false }).order('created_at', { ascending: false }),
      ])
      const e = l.error || c.error || o.error || v.error || f.error || u.error
      if (e) return this.set({ err: errText(e) })
      this.set({ d: { lsgd: l.data, contacts: c.data, opps: o.data, visits: v.data, fus: f.data, updates: u.data } })
    },
  },
}
