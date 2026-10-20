/* Log a visit: a six-step wizard (LSGD, check-in, people, discussion, business, review). */
import { html, raw, supabase, errText } from '../core.js'
import { Loading, Icon, Empty, Mascot, typeShort } from '../ui.js'
import {
  STAGES, DESIGNATIONS, INTEREST, LSGD_TYPES, GEOFENCE_M, UNIT_PRICE, FLAG_TEXT,
  istDate, addDays, financialYear, distanceM, fmtINR, fmtDate, stageLabel,
} from '../lib.js'
import { watchPosition, takePhoto } from '../expenses.js'
import { PhotoButton, photoActions, options } from '../kit.js'

const emptyContact = () => ({ name: '', designation: DESIGNATIONS[0], phone: '', email: '', is_decision_maker: false })
const STEPS = ['LSGD', 'Check-in', 'People', 'Discussion', 'Business', 'Review']
const MODES = [['visit', 'Visit', 'pin'], ['call', 'Call', 'phone'], ['whatsapp', 'WhatsApp', 'message'], ['email', 'Email', 'mail']]
const validPhone = (p) => /^[6-9]\d{9}$/.test(p.replace(/\D/g, '').slice(-10))
const DETAILS_DAYS = 3 // days allowed to finish the details of a quick check-in

const lsgdOf = (S) => (S.lsgds || []).find((l) => l.id === S.lsgdId)
const namedNew = (S) => S.newContacts.filter((c) => c.name.trim())
const metPeople = (S) => [...S.contacts.filter((c) => S.met.includes(c.id)), ...namedNew(S)]
const distOf = (S) => { const l = lsgdOf(S); return S.pos && l && l.office_lat != null ? Math.round(distanceM(S.pos.lat, S.pos.lng, l.office_lat, l.office_lng)) : null }

function checkStep(S, i) {
  const lsgd = lsgdOf(S)
  if (i === 0 && !lsgd) return 'Choose the LSGD you are visiting.'
  if (i === 1 && !S.pos) return 'Waiting for your GPS location. Turn on location and wait a moment.'
  if (i === 1 && !S.photo) return 'Take a photo of the LSGD office name board.'
  if (i === 2) {
    if (metPeople(S).length === 0) return 'Add at least one person you met.'
    for (const c of namedNew(S)) if (!validPhone(c.phone)) return `Enter a valid 10-digit mobile number for ${c.name}.`
  }
  if (i === 3 && S.discussion.trim().length < 20) return 'Write a few lines about the discussion (at least 20 characters).'
  if (i === 4 && S.fuDate && S.fuDate < istDate()) return 'The follow-up date can’t be in the past.'
  return ''
}

function gotoStep(sc, n) {
  sc.set({ step: n, reached: Math.max(sc.S.reached, n), err: '' })
  window.scrollTo(0, 0)
}

async function loadLsgd(sc, id) {
  const S = sc.S
  if (!id) return
  if (!S.completeId) S.met = []
  S.newContacts = []; S.fuContact = ''
  sc.render()
  const [c, o] = await Promise.all([
    supabase.from('contacts').select('*').eq('lsgd_id', id).order('created_at'),
    supabase.from('opportunities').select('*').eq('lsgd_id', id).eq('financial_year', financialYear()).maybeSingle(),
  ])
  const data = o.data
  const patch = { contacts: c.data || [], opp: data }
  if (data) Object.assign(patch, { stage: data.stage, units: String(data.expected_units || ''), prob: data.probability, closeMonth: data.expected_close ? data.expected_close.slice(0, 7) : '' })
  else Object.assign(patch, { stage: 'first_meeting', units: '', prob: 10, closeMonth: '' })
  sc.set(patch)
}

// shared by a full submit and by completing details later
async function saveBusiness(sc, visitId, createdIds) {
  const S = sc.S, lsgd = lsgdOf(S)
  const { data: oppRow, error: oe } = await supabase.from('opportunities').upsert({
    lsgd_id: lsgd.id, financial_year: financialYear(), stage: S.stage,
    expected_units: Number(S.units) || 0, probability: Number(S.prob),
    expected_close: S.closeMonth ? S.closeMonth + '-01' : null,
  }, { onConflict: 'lsgd_id,financial_year' }).select().single()
  if (oe) throw oe
  if (S.fuDate) {
    const namedIdx = S.fuContact.startsWith('new:') ? Number(S.fuContact.slice(4)) : -1
    const fuContactId = namedIdx >= 0 ? createdIds[namedIdx] : S.fuContact || null
    const { error } = await supabase.from('followups').insert({
      lsgd_id: lsgd.id, opportunity_id: oppRow.id, visit_id: visitId, contact_id: fuContactId,
      due_on: S.fuDate, mode: S.fuMode, notes: S.fuNote.trim() || null,
    })
    if (error) throw error
  }
}

// quick = save only the check-in and the people met; the details are added later
async function submit(sc, quick) {
  const S = sc.S, { profile, route } = sc.ctx, lsgd = lsgdOf(S)
  const checks = S.completeId ? [3, 4] : quick ? [0, 1, 2] : [0, 1, 2, 3, 4]
  for (const i of checks) { const v = checkStep(S, i); if (v) return sc.set({ step: i, err: v }) }
  sc.set({ err: '', busy: true })
  try {
    if (S.completeId) {
      const { data: upd, error } = await supabase.from('visits').update({
        discussion: S.discussion.trim(), outcome: S.outcome.trim() || null, interest_level: S.interest, next_followup_on: S.fuDate || null,
      }).eq('id', S.completeId).select().single()
      if (error) throw error
      await saveBusiness(sc, S.completeId, [])
      return sc.set({ result: { ...S.visitRow, ...upd, completed: true } })
    }
    const path = `${profile.id}/${istDate()}/${crypto.randomUUID()}.jpg`
    const up = await supabase.storage.from('visit-photos').upload(path, S.photo.blob, { contentType: 'image/jpeg' })
    if (up.error) throw up.error

    const { data: visit, error: ve } = await supabase.from('visits').insert({
      lsgd_id: lsgd.id, task_id: route.taskId || null,
      check_in_lat: S.pos.lat, check_in_lng: S.pos.lng, gps_accuracy_m: S.pos.acc,
      photo_path: path, discussion: quick ? null : S.discussion.trim(), outcome: quick ? null : S.outcome.trim() || null,
      interest_level: quick ? null : S.interest, next_followup_on: quick ? null : S.fuDate || null,
    }).select().single()
    if (ve) throw ve

    const nc = namedNew(S).map((c) => ({
      lsgd_id: lsgd.id, name: c.name.trim(), designation: c.designation,
      phone: c.phone.replace(/\D/g, '').slice(-10), email: c.email.trim() || null, is_decision_maker: c.is_decision_maker,
    }))
    let createdIds = []
    if (nc.length) {
      const { data, error } = await supabase.from('contacts').insert(nc).select('id')
      if (error) throw error
      createdIds = data.map((d) => d.id)
    }
    const allMet = [...S.met, ...createdIds]
    if (allMet.length) {
      const { error } = await supabase.from('visit_contacts').insert(allMet.map((contact_id) => ({ visit_id: visit.id, contact_id })))
      if (error) throw error
    }
    await supabase.from('followups').update({ done_at: new Date().toISOString(), done_note: 'Visited' })
      .eq('lsgd_id', lsgd.id).eq('assigned_to', profile.id).eq('mode', 'visit').is('done_at', null)
    if (!quick) await saveBusiness(sc, visit.id, createdIds)
    sc.set({ result: { ...visit, quick } })
  } catch (ex) {
    sc.set({ err: 'Could not save: ' + errText(ex) })
  } finally { sc.set({ busy: false }) }
}

const StepTitle = (icon, title, help) => html`<div class="step-title"><span class="lead-ico">${Icon(icon, 20)}</span><h2>${title}</h2></div><p class="step-help">${help}</p>`

const FinishLater = (S, typed) => html`<div class="card finish-later">
  <b>No time for the rest now?</b>
  <p class="small muted" style="margin:4px 0 10px">Save the check-in and the people you met. Add the discussion and business details later, within ${DETAILS_DAYS} days. Your manager can't review the visit until you do.</p>
  <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="finishLater" data-typed="${typed ? '1' : ''}">${Icon('clock', 18)} ${S.busy ? 'Saving…' : 'Save and finish later'}</button>
</div>`

const Row = (k, v, step, hide) => html`<div class="summary-row"><span>${k}</span><span>${v || '—'} ${hide ? '' : html`<button class="link" data-act="step" data-n="${step}">Edit</button>`}</span></div>`

function ContactFields(c, i) {
  const p = `newContacts.${i}`
  return html`<label>Name<input data-bind="${p}.name" data-live value="${c.name}"></label>
    <label>Designation<select data-bind="${p}.designation">${DESIGNATIONS.map((d) => html`<option ${d === c.designation ? raw('selected') : ''}>${d}</option>`)}</select></label>
    <div class="grid2">
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="${p}.phone" value="${c.phone}" placeholder="10 digits"></label>
      <label>Email (optional)<input type="email" data-bind="${p}.email" value="${c.email}"></label>
    </div>
    <label class="check"><input type="checkbox" data-bind="${p}.is_decision_maker" ${c.is_decision_maker ? raw('checked') : ''}> Can decide on purchase</label>`
}

function resultView(S, ctx) {
  const { result } = S, { profile } = ctx, lsgd = lsgdOf(S)
  const flagged = (result.fraud_flags || []).length > 0
  const deadline = fmtDate(new Date(new Date(result.check_in_at).getTime() + DETAILS_DAYS * 864e5).toISOString())
  return html`<div class="card" style="text-align:center;padding:28px 18px;margin-top:24px">
    <div style="margin:0 auto 12px;width:fit-content">${Mascot({ mood: result.completed ? 'cheer' : result.quick ? 'wink' : flagged ? 'surprise' : 'laugh', size: 132, bob: true })}</div>
    <h1>${result.completed ? 'Details saved' : result.quick ? 'Checked in' : 'Visit saved'}</h1>
    ${result.completed
      ? html`<p>The discussion and business details for <b>${lsgd && lsgd.name}</b> are added. Your ${profile.role === 'zonal_manager' ? 'Head Office' : 'Zonal Manager'} can review the visit now.</p>`
      : html`<p>Checked in at <b>${lsgd && lsgd.name}</b>${result.distance_from_office_m != null ? `, ${Math.round(result.distance_from_office_m)} m from the office` : ''}.</p>`}
    ${result.quick ? html`<div class="notice warn" style="text-align:left"><div><b>Details still to add</b>
      <div class="small">Add what was discussed and the expected business by <b>${deadline}</b>. The visit can't be reviewed until then. You'll find it on your Today screen under "Finish your visits".</div></div></div>` : ''}
    ${!result.completed ? (flagged
      ? html`<div class="notice warn" style="text-align:left">Your Zonal Manager will take a closer look: ${result.fraud_flags.map((f) => FLAG_TEXT[f] || f).join(', ')}.</div>`
      : !result.quick ? html`<div class="notice ok">Location checked. Sent to your Zonal Manager for review.</div>` : '') : ''}
    ${S.fuDate && !result.quick && !result.completed ? html`<p class="muted small">Next follow-up: ${S.fuMode} on ${fmtDate(S.fuDate)}.</p>` : ''}
    <div class="row gap" style="justify-content:center">
      ${result.quick ? html`<button class="btn primary" data-act="addNow">Add details now</button>` : ''}
      <button class="btn${result.quick ? '' : ' primary'}" data-act="home">Back to today</button>
      ${!result.quick ? html`<button class="btn" data-act="myVisits">My visits</button>` : ''}
    </div>
  </div>`
}

export default {
  state: (ctx) => {
    const r = ctx.route
    const first = r.completeVisit ? 3 : r.lsgdId ? 1 : 0
    return {
      completeId: r.completeVisit || null, first, step: first, reached: first,
      lsgds: null, lsgdId: r.lsgdId || '', search: '', visitRow: null, contacts: [], opp: null,
      pos: null, geoErr: '', photo: null, photoErr: '', met: [], newContacts: [],
      discussion: '', outcome: '', interest: 3, stage: 'first_meeting', units: '', prob: 10, closeMonth: '',
      fuDate: addDays(istDate(), 7), fuMode: 'visit', fuNote: '', fuContact: '', busy: false, err: '', result: null, focused: false,
    }
  },
  async init(S, ctx) {
    if (!S.completeId) this.stopGps = watchPosition(({ pos, err }) => this.set({ pos, geoErr: err })) // no GPS needed to finish details
    supabase.from('lsgds').select('id, name, type, office_lat, office_lng, districts(name)').order('name')
      .then(({ data, error }) => (error ? this.set({ err: errText(error) }) : this.set({ lsgds: data })))
    if (S.completeId) {
      const { data, error } = await supabase.from('visits').select('*, visit_contacts(contact_id)').eq('id', S.completeId).single()
      if (error) return this.set({ err: errText(error) })
      if (data.details_at) return this.set({ err: 'The details of this visit are already filled in.' })
      this.set({ visitRow: data, lsgdId: data.lsgd_id, met: data.visit_contacts.map((x) => x.contact_id) })
    }
    await loadLsgd(this, S.lsgdId)
  },
  destroyed() { if (this.stopGps) this.stopGps() },
  after(S) {
    if (S.step === 0 && !S.focused && S.lsgds) { S.focused = true; const i = this.root.querySelector('[data-bind="search"]'); if (i) i.focus() }
  },

  view(S, ctx) {
    if (S.result) return resultView(S, ctx)
    const { step, first } = S
    const lsgd = lsgdOf(S)
    const dist = distOf(S)
    const shown = STEPS.slice(first)
    const q = S.search.trim().toLowerCase()
    const filtered = (S.lsgds || []).filter((l) => !q || l.name.toLowerCase().includes(q) || l.districts.name.toLowerCase().includes(q)).slice(0, 40)
    const nn = namedNew(S)

    let body = ''
    if (step === 0) {
      body = html`<section>${StepTitle('building', 'Which LSGD are you at?', 'Pick from the LSGDs in your districts.')}
        <div class="search">${Icon('search', 18)}<input placeholder="Search LSGD or district" data-bind="search" data-live value="${S.search}"></div>
        ${!S.lsgds ? Loading() : S.lsgds.length === 0 ? Empty('No LSGDs are assigned to you yet. Ask your Zonal Manager.') : html`<ul class="list" style="margin-top:10px">
          ${filtered.map((l) => html`<li><button class="item" data-act="pick" data-id="${l.id}" ${S.lsgdId === l.id ? raw('style="border-color:var(--brand)"') : ''}>
            <span class="lsgd-mark">${typeShort(l.type)}</span>
            <div class="grow"><div class="title">${l.name}</div><div class="muted small">${LSGD_TYPES[l.type]} · ${l.districts.name}</div></div>
            ${Icon('right', 18)}</button></li>`)}</ul>`}
      </section>`
    } else if (step === 1 && lsgd) {
      const ring = !S.pos ? 'wait' : lsgd.office_lat == null ? 'warn' : dist <= GEOFENCE_M ? 'ok' : 'bad'
      body = html`<section>${StepTitle('pin', 'Check in', 'Stand at the LSGD office. We check your location and you take one photo of the name board.')}
        <div class="card"><div class="geo">
          <span class="geo-ring ${ring}">${Icon(!S.pos ? 'locate' : dist != null && dist <= GEOFENCE_M ? 'checkCircle' : 'pin', 28)}</span>
          <div class="grow">
            ${!S.pos && !S.geoErr ? html`<b>Finding your location…</b><div class="muted small">Keep this screen open.</div>` : ''}
            ${S.geoErr ? html`<b class="text-bad">${S.geoErr}</b>` : ''}
            ${S.pos && lsgd.office_lat == null ? html`<b>Location found</b><div class="small text-warn">This LSGD’s office location isn’t set yet, so the visit will be marked for your ZM to check.</div>` : ''}
            ${S.pos && dist != null && dist <= GEOFENCE_M ? html`<b class="text-ok">You’re at the office</b><div class="muted small">${dist} m away · GPS ±${S.pos.acc} m</div>` : ''}
            ${S.pos && dist != null && dist > GEOFENCE_M ? html`<b class="text-bad">${dist >= 1000 ? (dist / 1000).toFixed(1) + ' km' : dist + ' m'} from the office</b>
              <div class="small muted">Visits more than ${GEOFENCE_M} m away are flagged. Move closer if you can.</div>` : ''}
            ${S.pos && S.pos.acc > 100 ? html`<div class="small text-warn">GPS is weak (±${S.pos.acc} m). Step into the open.</div>` : ''}
          </div></div></div>
        <input id="visit-photo" type="file" accept="image/*" capture="environment" hidden data-change="photo">
        ${S.photo ? html`<div class="card"><img class="photo" src="${S.photo.url}" alt="Check-in photo">
            <button class="btn block" data-act="pickPhoto" data-for="visit-photo">${Icon('camera', 18)} Retake photo</button></div>`
          : html`<button class="big-camera" data-act="pickPhoto" data-for="visit-photo">
            <span class="cam">${Icon('camera', 30)}</span>Take photo of the office name board
            <span class="small muted" style="font-weight:400">Time and GPS are printed on it automatically</span></button>`}
        ${S.photoErr ? html`<p class="error">${S.photoErr}</p>` : ''}
      </section>`
    } else if (step === 2) {
      body = html`<section>${StepTitle('users', 'Who did you meet?', 'Tick the people you met. Add anyone new with their mobile number. Head Office may call to confirm.')}
        ${S.contacts.length > 0 ? html`<div class="people">${S.contacts.map((c) => {
          const on = S.met.includes(c.id)
          return html`<label class="person${on ? ' on' : ''}"><input type="checkbox" data-change="toggleMet" data-id="${c.id}" ${on ? raw('checked') : ''}>
            <span class="grow"><b>${c.name}</b>${c.verified_at ? html`<span class="pill ok tiny">confirmed</span>` : ''}
            <span class="muted small" style="display:block">${c.designation}${c.phone ? ` · ${c.phone}` : ''}</span></span></label>`
        })}</div>` : ''}
        ${S.newContacts.map((c, i) => html`<div class="card">
          <div class="row"><b class="grow">New person</b><button class="icon-btn" data-act="removeNew" data-i="${i}" aria-label="Remove">${Icon('x', 18)}</button></div>
          ${ContactFields(c, i)}</div>`)}
        <button class="btn block" data-act="addNew">${Icon('plus', 18)} Add a new person</button>
        ${FinishLater(S, false)}
      </section>`
    } else if (step === 3) {
      const n = S.discussion.trim().length
      body = html`<section>${StepTitle('message', 'What was discussed?', 'Write it the way you’d tell your manager. Be specific.')}
        <label>Discussion
          <textarea rows="5" data-bind="discussion" data-live placeholder="e.g. Explained the KWD and 90% subsidy. Secretary asked for a proposal for 200 units in next year’s plan.">${S.discussion}</textarea>
        </label>
        <div class="small muted" style="text-align:right;margin-top:-6px">${n < 20 ? `${20 - n} more characters` : '✓'}</div>
        <label>Next step they agreed to<input data-bind="outcome" value="${S.outcome}" placeholder="e.g. Send proposal by Friday"></label>
        <div class="field-label">How interested are they?</div>
        <div class="chips" role="radiogroup" aria-label="Interest level">${INTEREST.map((t, i) => html`<button role="radio" aria-checked="${S.interest === i + 1}" class="chip${S.interest === i + 1 ? ' on' : ''}" data-act="interest" data-n="${i + 1}">${t}</button>`)}</div>
        ${!S.completeId ? FinishLater(S, !!(S.discussion.trim() || S.outcome.trim())) : ''}
      </section>`
    } else if (step === 4) {
      const value = (Number(S.units) || 0) * UNIT_PRICE
      body = html`<section>${StepTitle('trend', 'Expected business', `Your best estimate for ${financialYear()}. Update it on every visit.`)}
        <div class="card">
          ${S.opp ? html`<p class="muted small" style="margin-top:0">Last time: ${stageLabel(S.opp.stage)}, ${S.opp.expected_units} units</p>` : ''}
          <label style="margin-top:0">Where is this LSGD now?
            <select data-bind="stage" data-change="setStage">${STAGES.map((s) => html`<option value="${s.id}" ${s.id === S.stage ? raw('selected') : ''}>${s.label}</option>`)}</select>
          </label>
          <div class="grid2">
            <label>Expected units<input type="number" inputmode="numeric" min="0" data-bind="units" data-live value="${S.units}" placeholder="0"></label>
            <label>Chance of order %<input type="number" inputmode="numeric" min="0" max="100" data-bind="prob" data-live value="${S.prob}"></label>
          </div>
          <label>Expected order month<input type="month" data-bind="closeMonth" value="${S.closeMonth}"></label>
          <div class="notice info" style="margin-bottom:0">Order value <b>${fmtINR(value)}</b> · likely <b>${fmtINR(value * (Number(S.prob) || 0) / 100)}</b></div>
        </div>
        <div class="card">
          <h3>Next follow-up</h3>
          <div class="chips" role="radiogroup" aria-label="Follow-up type">${MODES.map(([k, l, ic]) => html`<button role="radio" aria-checked="${S.fuMode === k}" class="chip${S.fuMode === k ? ' on' : ''}" data-act="fuMode" data-k="${k}">${Icon(ic, 16)} ${l}</button>`)}</div>
          <div class="chips" style="margin-top:10px">${[[2, 'In 2 days'], [7, 'Next week'], [14, 'In 2 weeks']].map(([n, l]) => html`<button class="chip${S.fuDate === addDays(istDate(), n) ? ' on' : ''}" data-act="fuQuick" data-n="${n}">${l}</button>`)}</div>
          <div class="grid2">
            <label>Date<input type="date" min="${istDate()}" data-bind="fuDate" data-live value="${S.fuDate}"></label>
            <label>With
              <select data-bind="fuContact">
                <option value="">Anyone</option>
                ${S.contacts.map((c) => html`<option value="${c.id}" ${S.fuContact === c.id ? raw('selected') : ''}>${c.name}</option>`)}
                ${nn.map((c, i) => html`<option value="new:${i}" ${S.fuContact === 'new:' + i ? raw('selected') : ''}>${c.name}</option>`)}
              </select>
            </label>
          </div>
          <label>Note<input data-bind="fuNote" value="${S.fuNote}" placeholder="e.g. Ask about DPC approval"></label>
        </div>
        ${!S.completeId ? FinishLater(S, true) : ''}
      </section>`
    } else if (step === 5) {
      const vr = S.visitRow
      body = html`<section>${StepTitle('checkCircle', S.completeId ? 'Check and save details' : 'Check and submit', S.completeId ? 'After saving, your manager can review this visit.' : 'Once submitted, the check-in can’t be changed or deleted.')}
        ${S.photo ? html`<img class="photo" src="${S.photo.url}" alt="Check-in photo" style="max-height:220px;object-fit:cover">` : ''}
        <div class="summary">
          ${Row('LSGD', lsgd && lsgd.name, 0, !!ctx.route.lsgdId || !!S.completeId)}
          ${S.completeId
            ? Row('Checked in', vr ? `${fmtDate(vr.check_in_at)}${vr.distance_from_office_m != null ? ` · ${Math.round(vr.distance_from_office_m)} m from office` : ''}` : '…', 1, true)
            : Row('Location', dist != null ? `${dist} m from office` : S.pos ? 'Found (office not set)' : '—', 1)}
          ${Row('People met', metPeople(S).map((c) => c.name).join(', '), 2, !!S.completeId)}
          ${Row('Interest', INTEREST[S.interest - 1], 3)}
          ${Row('Stage', `${stageLabel(S.stage)} · ${Number(S.units) || 0} units`, 4)}
          ${Row('Follow-up', S.fuDate ? `${S.fuMode}, ${fmtDate(S.fuDate)}` : 'None', 4)}
        </div>
        <p class="small" style="margin-top:12px"><b>Discussion:</b> ${S.discussion}</p>
      </section>`
    }

    return html`<div class="wizard-top">
        <div class="row"><b>${lsgd ? lsgd.name : 'Log a visit'}</b><span class="muted">Step ${step - first + 1} of ${shown.length}</span></div>
        <div class="wizard-steps" role="list" aria-label="Visit steps">${shown.map((s, i) => {
          const idx = i + first
          return html`<button role="listitem" aria-label="${s}${idx === step ? ' (current)' : ''}" title="${s}" class="${idx === step ? 'cur' : idx < S.reached || idx < step ? 'done' : ''}" data-act="step" data-n="${idx}" ${idx > S.reached ? raw('disabled') : ''}></button>`
        })}</div>
      </div>
      ${body}
      ${S.err ? html`<p class="notice bad" role="alert">${S.err}</p>` : ''}
      <div class="wizard-space"></div>
      <div class="wizard-bar">
        <button class="btn" data-act="back">${Icon('left', 18)} ${step > first ? 'Back' : 'Cancel'}</button>
        ${step < 5 ? html`<button class="btn primary" data-act="next" ${step === 0 && !lsgd ? raw('disabled') : ''}>Next ${Icon('right', 18)}</button>`
          : html`<button class="btn primary" ${S.busy || (S.completeId && !S.visitRow) ? raw('disabled') : ''} data-act="submit">${S.busy ? 'Saving…' : S.completeId ? 'Save details' : 'Submit visit'}</button>`}
      </div>`
  },

  actions: {
    ...photoActions,
    async pick(el) {
      this.set({ lsgdId: el.dataset.id })
      gotoStep(this, 1)
      await loadLsgd(this, el.dataset.id)
    },
    step(el) { const n = Number(el.dataset.n); if (n <= this.S.reached) gotoStep(this, n) },
    next() {
      const v = checkStep(this.S, this.S.step)
      if (v) return this.set({ err: v })
      gotoStep(this, this.S.step + 1)
    },
    back() {
      const S = this.S
      if (S.step > S.first) gotoStep(this, S.step - 1)
      else this.ctx.go(S.completeId ? 'work' : 'home', S.completeId ? { tab: 'visits' } : {})
    },
    async photo(el) {
      const f = el.files && el.files[0]
      el.value = ''
      this.set({ photoErr: '' })
      if (!f) return
      const S = this.S, lsgd = lsgdOf(S)
      try {
        const blob = await takePhoto(f, { live: true, lines: [
          `${lsgd ? lsgd.name : ''} · ${this.ctx.profile.full_name}`,
          `${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST`,
          S.pos ? `GPS ${S.pos.lat.toFixed(5)}, ${S.pos.lng.toFixed(5)} (±${S.pos.acc} m)` : 'GPS not available',
        ] })
        if (S.photo) URL.revokeObjectURL(S.photo.url)
        this.set({ photo: { blob, url: URL.createObjectURL(blob) } })
      } catch (ex) { this.set({ photoErr: /older photo/.test(errText(ex)) ? errText(ex) : 'Could not read this photo: ' + errText(ex) }) }
    },
    toggleMet(el) {
      const id = el.dataset.id
      this.set({ met: el.checked ? [...this.S.met, id] : this.S.met.filter((x) => x !== id) })
    },
    addNew() { this.set({ newContacts: [...this.S.newContacts, emptyContact()] }) },
    removeNew(el) { this.set({ newContacts: this.S.newContacts.filter((_, j) => j !== Number(el.dataset.i)) }) },
    interest(el) { this.set({ interest: Number(el.dataset.n) }) },
    setStage(el) { const s = STAGES.find((x) => x.id === el.value); this.set({ stage: el.value, prob: s ? s.prob : this.S.prob }) },
    fuMode(el) { this.set({ fuMode: el.dataset.k }) },
    fuQuick(el) { this.set({ fuDate: addDays(istDate(), Number(el.dataset.n)) }) },
    finishLater(el) {
      if (el.dataset.typed && !confirm('Save the check-in now? What you typed on this page will not be saved.')) return
      submit(this, true)
    },
    submit() { submit(this, false) },
    addNow() { const r = this.S.result; this.ctx.go('visit', { lsgdId: r.lsgd_id, completeVisit: r.id }) },
    home() { this.ctx.go('home') },
    myVisits() { this.ctx.go('work', { tab: 'visits' }) },
  },
}
