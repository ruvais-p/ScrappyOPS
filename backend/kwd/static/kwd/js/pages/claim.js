/* One day's TA / DA request: the requester edits and submits it; a Zonal Manager / Head Office reviews it. */
import { html, raw, supabase, errText, toast } from '../core.js'
import { Loading, Icon, SectionHead, Avatar } from '../ui.js'
import { fmtDate, fmtTime, fmtINR, FLAG_TEXT, addDays } from '../lib.js'
import { Sheet, PhotoButton, photoActions, istStartISO, errLine } from '../kit.js'
import {
  TRAVEL_MODES, CATEGORIES, CLAIM_STATUS, EVENT_LABEL, EVENT_TONE, flagText, flagTone, loadPolicy, takePhoto, uploadPhoto,
  signedUrl, mapLink, kmText, payable,
} from '../expenses.js'

const longDate = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
const now = () => new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })

export const StatusPill = (status) => { const [label, tone] = CLAIM_STATUS[status]; return html`<span class="pill ${tone}">${label}</span>` }

export const FlagChips = (flags) => !flags || !flags.length ? '' :
  html`<div class="flags">${flags.map((f) => html`<span class="pill ${flagTone(f) === 'info' ? '' : flagTone(f)}">${flagText(f)}</span>`)}</div>`

// compact row used in claim lists (the screen around it handles data-act="openClaim" data-id)
export const ClaimRow = (d, { showPerson, ho } = {}) => html`<li><button class="item" data-act="openClaim" data-id="${d.id}">
  ${showPerson ? Avatar(d.person && d.person.full_name, 32) : html`<span class="lead-ico">${Icon('rupee', 18)}</span>`}
  <div class="grow">
    <div class="title">${showPerson ? `${d.person && d.person.full_name} · ` : ''}${fmtDate(d.day)}</div>
    <div class="muted small">${TRAVEL_MODES[d.travel_mode].short} · ${d.visits_count} visit${d.visits_count === 1 ? '' : 's'}${d.odo_km != null ? ` · ${kmText(d.odo_km)}` : ''}${d.gps_km != null ? ` (GPS ${kmText(d.gps_km)})` : ''}</div>
    ${d.ho_flag ? html`<div class="flags"><span class="pill ${ho ? 'bad' : 'warn'}">${ho ? 'Flagged by you' : 'Under Head Office review'}</span></div>` : ''}
    ${d.flags.some((f) => flagTone(f) === 'bad') ? html`<div class="flags">${d.flags.filter((f) => flagTone(f) === 'bad').map((f) => html`<span class="pill bad">${flagText(f)}</span>`)}</div>` : ''}
  </div>
  <div class="amt"><b>${fmtINR(d.approved_amount ?? d.total_claimed)}</b>${StatusPill(d.status)}</div>
</button></li>`

const Evidence = (title, at, lat, lng, acc, odo, url) => html`<div class="subcard ev">
  ${url ? html`<a href="${url}" target="_blank" rel="noreferrer"><img src="${url}" alt="${title} odometer"></a>` : ''}
  <div><b>${title} · ${fmtTime(at)}</b>
    ${odo != null ? html`<div class="small">Odometer ${odo.toLocaleString('en-IN')} km</div>` : ''}
    <div class="small muted">${lat != null ? html`<a href="${mapLink(lat, lng)}" target="_blank" rel="noreferrer">Location ±${Math.round(acc)} m</a>` : 'No GPS'}</div>
  </div></div>`

const BillRow = (i, urls, editable, label, act) => html`<li class="item exp-item">
  ${urls[i.bill_path] ? html`<a href="${urls[i.bill_path]}" target="_blank" rel="noreferrer" class="bill-thumb"><img src="${urls[i.bill_path]}" alt="Bill"></a>`
    : html`<span class="bill-thumb none" title="No bill">${Icon('x', 18)}</span>`}
  <div class="grow">${label}${FlagChips(i.flags)}</div>
  ${editable ? html`<button class="icon-btn" aria-label="Delete expense" data-act="removeItem" data-id="${i.id}">${Icon('x', 18)}</button>` : ''}
</li>`

function allowanceSection(S, d, editable, daLimit, daList) {
  const saved = Number(d.da_requested) > 0 ? String(Number(d.da_requested)) : ''
  const dirty = S.daText.trim() !== saved
  if (!editable && !daList.length && !(Number(d.da_requested) > 0)) {
    return html`<section>${SectionHead({ title: 'Allowance (DA)' })}<p class="muted small">No allowance requested for this day.</p></section>`
  }
  return html`<section class="${editable ? 'card' : ''}">
    ${editable ? html`<h2>Allowance (DA)</h2>` : SectionHead({ title: 'Allowance (DA)' })}
    ${editable ? html`
      <p class="small muted" style="margin-top:0">Type the allowance you are requesting for this day, then upload your bills. ${daLimit != null ? `Maximum ${fmtINR(daLimit)} a day${d.night_halt ? ' (night halt)' : ''}. ` : ''}TA is calculated for you.</p>
      <label>Allowance for the day (₹)<input data-bind="daText" data-change="decimal" data-oninput data-live value="${S.daText}" inputmode="decimal" placeholder="0"></label>
      ${dirty ? html`<button class="btn primary block" ${S.daBusy ? raw('disabled') : ''} data-act="saveDa">${S.daBusy ? 'Saving…' : 'Save allowance'}</button>` : ''}
      ${errLine(S.daErr)}`
    : html`<p style="margin-top:0">Requested <b>${fmtINR(d.da_amount)}</b></p>`}
    <div class="field-label">Bills ${daList.length ? `(${daList.length})` : ''}</div>
    ${daList.length === 0 ? html`<p class="muted small" style="margin-top:0">${editable ? 'No bills uploaded yet. Upload the bills for your food and other allowance costs.' : 'No bills uploaded.'}</p>`
      : html`<ul class="list">${daList.map((i) => html`<li class="item exp-item">
        ${S.urls[i.bill_path] ? html`<a href="${S.urls[i.bill_path]}" target="_blank" rel="noreferrer" class="bill-thumb"><img src="${S.urls[i.bill_path]}" alt="DA bill"></a>` : html`<span class="bill-thumb none">${Icon('x', 18)}</span>`}
        <div class="grow">
          <div class="title">DA bill${i.bill_no ? ` · ${i.bill_no}` : ''}</div>
          <div class="muted small">Uploaded ${fmtDate(i.created_at)} ${fmtTime(i.created_at)}</div>
          ${FlagChips(i.flags)}
        </div>
        ${editable ? html`<button class="icon-btn" aria-label="Remove bill" data-act="removeItem" data-id="${i.id}">${Icon('x', 18)}</button>` : ''}
      </li>`)}</ul>`}
    ${editable ? html`<button class="btn block" data-act="openDaBill">${Icon('camera', 18)} Upload a DA bill</button>` : ''}
  </section>`
}

function ownActions(S, d, policy) {
  const dirty = S.halt !== d.night_halt || S.place !== (d.halt_place || '') || S.note !== (d.tso_note || '')
  return html`<section class="card">
    <h2>Before you submit</h2>
    <label class="check"><input type="checkbox" data-bind="halt" data-live ${S.halt ? raw('checked') : ''}>
      <span>I stayed outstation tonight (night halt)${policy ? html`<span class="muted small"> · allowance maximum ${fmtINR(policy.da_outstation)} instead of ${fmtINR(policy.da_local)}</span>` : ''}</span></label>
    ${S.halt ? html`<label>Where did you stay?<input data-bind="place" value="${S.place}" placeholder="Town / hotel"></label>` : ''}
    <label>Note for your manager (optional)<textarea rows="2" data-bind="note" placeholder="e.g. extra trip to the block office">${S.note}</textarea></label>
    ${!d.end_at ? html`<p class="notice warn small">End your day on the Today screen before submitting.</p>` : ''}
    <div class="row wrap">
      ${dirty ? html`<button class="btn" ${S.busy ? raw('disabled') : ''} data-act="saveOwn">Save</button>` : ''}
      <button class="btn primary grow" ${S.busy || !d.end_at ? raw('disabled') : ''} data-act="submitOwn">Submit request</button>
    </div>
  </section>`
}

function reviewActions(S, d, ho) {
  const zmStep = d.status === 'submitted'
  const hoStep = ho && ['submitted', 'zm_approved'].includes(d.status)
  const payStep = ho && d.status === 'ho_approved'
  if (!zmStep && !hoStep && !payStep) return ''
  const amt = Number(S.amount)
  if (payStep) {
    return html`<p class="notice small">Approved for ${fmtINR(d.approved_amount)}. It will be paid in the monthly settlement for ${new Date(d.day + 'T00:00:00').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}.</p>`
  }
  return html`<section class="card">
    <h2>${ho ? 'Head Office approval' : 'Verify this request'}</h2>
    ${d.flags.length > 0 ? html`<p class="small muted">Check the flags above against the bills, photos and visits before ${ho ? 'approving' : 'verifying'}.</p>` : ''}
    <label>Amount to ${ho ? 'approve' : 'verify'} (₹)<input data-bind="amount" data-change="decimal" data-oninput data-live value="${S.amount}" inputmode="decimal"></label>
    <label>Remark ${amt < payable(d) ? '(required: why it was cut)' : '(needed to send back or reject)'}<textarea rows="2" data-bind="remark">${S.remark}</textarea></label>
    <div class="row wrap">
      <button class="btn primary grow" ${S.busy ? raw('disabled') : ''} data-act="review" data-status="${ho ? 'ho_approved' : 'zm_approved'}">${Icon('check', 18)} ${ho ? 'Approve' : 'Verify'} ${fmtINR(amt || 0)}</button>
      <button class="btn" ${S.busy ? raw('disabled') : ''} data-act="review" data-status="open">Send back</button>
      <button class="btn danger" ${S.busy ? raw('disabled') : ''} data-act="review" data-status="rejected">Reject</button>
    </div>
  </section>`
}

function timeline(events, ho) {
  if (!events.length) return ''
  return html`<section>${SectionHead({ title: ho ? 'Request history' : 'History', count: events.length })}
    <ul class="trail">${events.map((e) => {
      const tone = EVENT_TONE[e.event]
      return html`<li class="${tone ? 'tl-' + tone : ''}">
        <b>${EVENT_LABEL[e.event] || e.event}</b>${e.amount != null && Number(e.amount) > 0 ? html`<span> · ${fmtINR(e.amount)}</span>` : ''}
        <span class="muted small"> · ${(e.actor && e.actor.full_name) || 'System'} · ${fmtDate(e.at)} ${fmtTime(e.at)}</span>
        ${e.note ? html`<div class="small">${e.note}</div>` : ''}
        ${e.meta && e.meta.category ? html`<div class="small muted">${CATEGORIES[e.meta.category] && CATEGORIES[e.meta.category].label}${e.meta.bill === false ? ' · no bill photo' : ''}</div>` : ''}
      </li>`
    })}</ul></section>`
}

// Head Office: flag anything unusual. A flagged day is held back from payment until the flag is removed.
function flagBox(S, d) {
  const flagging = !d.ho_flag
  return html`<section class="card">
    <div class="row">
      <div class="grow"><b>${flagging ? 'Something unusual?' : 'Flagged by Head Office'}</b>
        <div class="small muted">${flagging ? 'Flag this request. It is held back from payment and the reason is kept in the history, visible to Head Office only.' : 'Payment is on hold.'}</div></div>
      ${!S.fOpen ? html`<button class="btn${flagging ? ' danger' : ''}" data-act="flagOpen">${Icon('flag', 18)} ${flagging ? 'Flag' : 'Remove flag'}</button>` : ''}
    </div>
    ${S.fOpen ? html`
      <label>${flagging ? 'Why is it unusual?' : 'Why is the flag removed?'}
        <textarea rows="2" data-bind="fReason" placeholder="${flagging ? 'e.g. The lunch bill looks edited' : 'e.g. Checked with the TSO, bill is genuine'}">${S.fReason}</textarea></label>
      ${errLine(S.fErr)}
      <div class="row wrap">
        <button class="btn grow${flagging ? ' danger' : ' primary'}" ${S.fBusy ? raw('disabled') : ''} data-act="flagGo">${S.fBusy ? 'Saving…' : flagging ? 'Flag this request' : 'Remove flag'}</button>
        <button class="btn" ${S.fBusy ? raw('disabled') : ''} data-act="flagCancel">Cancel</button>
      </div>` : ''}
  </section>`
}

function daBillSheet(S) {
  return Sheet({ title: 'Upload a DA bill', body: html`
    <p class="small muted">Photograph the bill (food, tea or any allowance cost). The amount you request is typed on the request, not here.</p>
    ${PhotoButton({ id: 'bill-photo', label: 'Photo of the bill', photo: S.photo, live: false })}
    <label>Bill number (if any)<input data-bind="billNo" value="${S.billNo}"></label>
    ${errLine(S.sErr)}
    <button class="btn primary block" ${S.sBusy ? raw('disabled') : ''} data-act="saveDaBill">${S.sBusy ? 'Uploading…' : 'Upload bill'}</button>` })
}

function expenseSheet(S, d, policy) {
  const c = CATEGORIES[S.cat]
  const needBill = policy && Number(S.amountX) > Number(policy.bill_required_above)
  return Sheet({ title: 'Add a travel, lodging or other bill', body: html`
    ${[['TA', 'Travel (TA)'], ['Lodging', 'Lodging'], ['Other', 'Other']].map(([g, label]) => html`<div>
      <div class="field-label">${label}</div>
      <div class="chips">${Object.entries(CATEGORIES).filter(([, x]) => x.group === g).map(([k, x]) => html`<button class="chip${S.cat === k ? ' on' : ''}" data-act="cat" data-k="${k}">${x.label}</button>`)}</div></div>`)}
    <label>Amount (₹)<input data-bind="amountX" data-change="decimal" data-oninput data-live value="${S.amountX}" inputmode="decimal"></label>
    <label>What was it for?<input data-bind="desc" value="${S.desc}" placeholder="${S.cat === 'lodging' ? 'e.g. Room at Manjeri, 1 night' : 'e.g. Bus to Kondotty'}"></label>
    ${c.route ? html`<div class="grid2"><label>From<input data-bind="from" value="${S.from}"></label><label>To<input data-bind="to" value="${S.to}"></label></div>` : ''}
    <label>Bill / ticket number (if any)<input data-bind="billNo" value="${S.billNo}"></label>
    ${PhotoButton({ id: 'bill-photo', label: needBill ? 'Photo of the bill (needed)' : 'Photo of the bill', photo: S.photo, live: false })}
    ${S.cat === 'lodging' && policy ? html`<p class="small muted">Policy limit ${fmtINR(policy.lodging_cap)} per night. Tick night halt on the request.</p>` : ''}
    ${S.cat === 'auto_taxi' && policy ? html`<p class="small muted">Policy limit ${fmtINR(policy.auto_taxi_cap_day)} per day.</p>` : ''}
    ${errLine(S.sErr)}
    <button class="btn primary block" ${S.sBusy ? raw('disabled') : ''} data-act="saveExpense">${S.sBusy ? 'Saving…' : 'Add'}</button>` })
}

// props: dayId, mode ('own' | 'review'), ho. The screen around it provides actions claimBack and claimChanged.
export default {
  state: () => ({
    d: null, visits: [], urls: {}, events: [], policy: null, err: '', busy: false, sheet: null,
    // the requester's own fields
    daText: '', daBusy: false, daErr: '', halt: false, place: '', note: '',
    // reviewer fields
    amount: '', remark: '', fOpen: false, fReason: '', fBusy: false, fErr: '',
    // bill sheets
    photo: null, billNo: '', cat: 'parking_toll', amountX: '', desc: '', from: '', to: '', sErr: '', sBusy: false,
  }),
  async init() {
    this.set({ policy: await loadPolicy() })
    await load(this, true)
  },

  view(S, ctx) {
    const { dayId, mode, ho } = ctx.props
    const d = S.d
    if (S.err && !d) return html`<p class="error">${S.err}</p>`
    if (!d) return Loading('Loading request…')
    const policy = S.policy
    const own = mode === 'own'
    const editable = own && d.status === 'open'
    const m = TRAVEL_MODES[d.travel_mode]
    const rate = policy ? (d.travel_mode === 'car' ? policy.rate_car : policy.rate_two_wheeler) : null
    const groups = { TA: 0, Lodging: 0, Other: 0, DA: 0 }
    d.expense_items.forEach((i) => { groups[CATEGORIES[i.category].group] += Number(i.amount) })
    const daList = d.expense_items.filter((i) => i.category === 'da_bill')
    const billList = d.expense_items.filter((i) => i.category !== 'da_bill')
    const daLimit = policy ? Number(d.night_halt ? policy.da_outstation : policy.da_local) : null
    const lastFlag = S.events.filter((e) => e.event === 'ho_flagged').at(-1)
    const vehicleTa = Number(d.ta_amount) - groups.TA
    const gpsLimit = d.gps_km != null && policy ? d.gps_km * (1 + policy.km_tolerance_pct / 100) + 5 : null

    return html`
      <div class="row" style="margin-bottom:8px"><button class="btn sm" data-act="back">${Icon('left', 16)} Back</button></div>
      <div class="page-head"><div class="grow">
        <div class="eyebrow">${own ? 'My request' : d.person && d.person.full_name}</div>
        <h1>${longDate(d.day)}</h1>
        <div class="row wrap" style="gap:8px">${StatusPill(d.status)}<span class="muted small">${m.short}${d.vehicle_no ? ` · ${d.vehicle_no}` : ''}</span></div>
      </div></div>

      ${d.status === 'open' && (d.zm_remark || d.ho_remark) ? html`<p class="notice warn"><b>Sent back:</b> ${d.ho_remark || d.zm_remark}</p>` : ''}
      ${d.status === 'rejected' ? html`<p class="notice bad"><b>Rejected:</b> ${d.ho_remark || d.zm_remark}</p>` : ''}
      ${own && d.status === 'zm_approved' ? html`<p class="notice ok"><span><b>Verified by your Zonal Manager</b> for ${fmtINR(d.approved_amount)}. Head Office approves it next, and it is paid in the monthly settlement.</span></p>` : ''}
      ${d.ho_flag ? (ho
        ? html`<p class="notice bad"><span><b>Flagged by you.</b> ${lastFlag && lastFlag.note} Payment is on hold until you remove the flag.</span></p>`
        : html`<p class="notice warn"><span><b>Head Office is reviewing this request.</b> Payment is on hold until they finish.</span></p>`) : ''}

      <section class="card claim-sum">
        <div class="sum-row"><span>Travel (TA)
          <small>${m.own ? `${kmText(d.ta_km)} × ${rate != null ? `₹${Number(rate).toFixed(2)}` : '…'}/km = ${fmtINR(vehicleTa)}` : 'Tickets and fares'}${groups.TA ? ` + bills ${fmtINR(groups.TA)}` : ''}</small></span>
          <b>${fmtINR(d.ta_amount)}</b></div>
        <div class="sum-row"><span>Allowance (DA)
          <small>${Number(d.da_amount) > 0 ? `requested by the TSO · ${daList.length} bill${daList.length === 1 ? '' : 's'} uploaded` : 'No allowance requested'}${daLimit != null ? ` · maximum ${fmtINR(daLimit)} a day${d.night_halt ? ' (night halt)' : ''}` : ''}</small></span>
          <b>${fmtINR(d.da_amount)}</b></div>
        <div class="sum-row"><span>Lodging</span><b>${fmtINR(d.lodging_amount)}</b></div>
        <div class="sum-row"><span>Other</span><b>${fmtINR(d.other_amount)}</b></div>
        <div class="sum-row total"><span>Total requested</span><b>${fmtINR(d.total_claimed)}</b></div>
        ${d.approved_amount != null ? html`<div class="sum-row total ok"><span>${d.status === 'zm_approved' ? 'Verified by ZM' : 'Approved'}${d.status === 'paid' ? ` · paid ${fmtDate(d.paid_at)} · ${d.paid_ref}` : ''}</span><b>${fmtINR(d.approved_amount)}</b></div>` : ''}
        ${FlagChips(d.flags)}
        ${editable ? html`<p class="small muted" style="margin-bottom:0">TA is worked out automatically from your odometer km and the rate. You type your DA for the day and upload the bills.</p>` : ''}
      </section>

      <section>
        ${SectionHead({ title: 'Day record' })}
        <div class="evidence">
          ${Evidence('Start', d.start_at, d.start_lat, d.start_lng, d.start_acc, d.start_odo, S.urls[d.start_photo])}
          ${d.end_at ? Evidence('End', d.end_at, d.end_lat, d.end_lng, d.end_acc, d.end_odo, S.urls[d.end_photo]) : html`<div class="subcard muted small">Day not ended yet.</div>`}
        </div>
        ${m.own ? html`<div class="card km-compare">
          <div class="sum-row"><span>Odometer</span><b>${kmText(d.odo_km)}</b></div>
          <div class="sum-row"><span>GPS route<small>start → ${S.visits.length} visit${S.visits.length === 1 ? '' : 's'} → end, by road (est.)</small></span><b>${kmText(d.gps_km)}</b></div>
          ${gpsLimit != null && d.odo_km != null ? html`<p class="small ${d.odo_km > gpsLimit ? 'text-bad' : 'muted'}" style="margin:0">${d.odo_km > gpsLimit ? `Odometer is ${Math.round(d.odo_km - d.gps_km)} km more than the route. Ask about the extra travel.` : 'Odometer km matches the route.'}</p>` : ''}
        </div>` : ''}
      </section>

      <section>
        ${SectionHead({ title: 'Visits that day', count: S.visits.length })}
        ${S.visits.length === 0 ? html`<p class="muted small">No LSGD visits logged on this day.</p>` : html`<ul class="list">${S.visits.map((v) => html`<li class="item">
          <span class="lead-ico">${Icon('pin', 18)}</span>
          <div class="grow">
            <div class="title">${v.lsgds.name}</div>
            <div class="muted small">${fmtTime(v.check_in_at)}${v.check_out_at ? `–${fmtTime(v.check_out_at)}` : ''} · ${v.lsgds.districts.name}${v.distance_from_office_m != null ? ` · ${Math.round(v.distance_from_office_m)} m from office` : ''}</div>
            ${v.fraud_flags.length > 0 ? html`<div class="flags">${v.fraud_flags.map((f) => html`<span class="pill warn">${FLAG_TEXT[f] || f}</span>`)}</div>` : ''}
          </div>
          ${v.zm_status === 'rejected' ? html`<span class="pill bad">Rejected</span>` : v.zm_status === 'verified' ? html`<span class="pill ok">Verified</span>` : ''}
        </li>`)}</ul>`}
      </section>

      ${allowanceSection(S, d, editable, daLimit, daList)}

      <section>
        ${SectionHead({ title: 'Travel, lodging and other bills', count: billList.length, action: editable ? html`<button class="btn sm" data-act="openExpense">${Icon('plus', 16)} Add</button>` : '' })}
        ${billList.length === 0 ? html`<p class="muted small">${editable ? 'Add tickets, auto fare, lodging or parking with a photo of each bill. Your own vehicle km is counted automatically.' : 'No bills added.'}</p>`
          : html`<ul class="list">${billList.map((i) => BillRow(i, S.urls, editable, html`
            <div class="title">${CATEGORIES[i.category].label} · ${fmtINR(i.amount)}</div>
            <div class="muted small">${i.description}${i.from_place ? ` · ${i.from_place} → ${i.to_place || '?'}` : ''}${i.bill_no ? ` · Bill ${i.bill_no}` : ''}</div>`))}</ul>`}
      </section>

      ${editable ? ownActions(S, d, policy) : ''}
      ${!own ? reviewActions(S, d, ho) : ''}
      ${ho ? flagBox(S, d) : ''}
      ${!editable && d.tso_note ? html`<p class="small"><b>Note from ${own ? 'you' : 'the TSO'}:</b> ${d.tso_note}</p>` : ''}
      ${timeline(S.events, ho)}
      ${S.err ? html`<p class="error" role="alert">${S.err}</p>` : ''}
      ${S.sheet === 'da' ? daBillSheet(S) : ''}${S.sheet === 'exp' ? expenseSheet(S, d, policy) : ''}`
  },

  actions: {
    ...photoActions,
    back() { const p = this.ctx.parent; p.actions.claimBack.call(p) },
    decimal(el) { el.value = el.value.replace(/[^\d.]/g, ''); setPathValue(this.S, el.dataset.bind, el.value) },
    async removeItem(el) {
      if (!confirm('Delete this expense?')) return
      const { error } = await supabase.from('expense_items').delete().eq('id', el.dataset.id)
      if (error) return this.set({ err: errText(error) })
      await changed(this)
    },
    // --- requester
    async saveDa() {
      const S = this.S, d = S.d, daLimit = S.policy ? Number(d.night_halt ? S.policy.da_outstation : S.policy.da_local) : null
      this.set({ daErr: '' })
      const v = S.daText.trim() === '' ? 0 : Number(S.daText)
      if (!(v >= 0)) return this.set({ daErr: 'Enter the allowance in rupees.' })
      if (daLimit != null && v > daLimit) return this.set({ daErr: `The maximum allowance for one day is ${fmtINR(daLimit)}${d.night_halt ? ' (with a night halt)' : ''}.` })
      this.set({ daBusy: true })
      const { error } = await supabase.from('field_days').update({ da_requested: v }).eq('id', d.id)
      this.set({ daBusy: false })
      if (error) return this.set({ daErr: errText(error) })
      toast(v ? 'Allowance saved' : 'Allowance removed')
      await changed(this)
    },
    saveOwn() { return updateDay(this, ownPatch(this.S), 'Saved') },
    submitOwn() {
      const S = this.S
      if (S.halt && !S.place.trim()) return alert('Write where you stayed.')
      if (confirm('Submit this request? You cannot change it after submitting.')) return updateDay(this, ownPatch(S, { status: 'submitted' }), 'Request submitted')
    },
    // --- reviewers
    review(el) {
      const S = this.S, d = S.d, status = el.dataset.status, { ho } = this.ctx.props
      const key = ho ? 'ho_remark' : 'zm_remark'
      const amt = Number(S.amount)
      if (status !== 'open' && status !== 'rejected') {
        if (!(amt >= 0 && amt <= Number(d.total_claimed))) return alert(`The amount must be between 0 and ${fmtINR(d.total_claimed)}.`)
        if (amt < payable(d) && !S.remark.trim()) return alert('Write why the amount was cut.')
      } else if (!S.remark.trim()) return alert('Write the reason so the TSO knows what to fix.')
      const patch = { status, [key]: S.remark.trim() || null }
      if (status === 'zm_approved' || status === 'ho_approved') patch.approved_amount = amt
      return updateDay(this, patch, { zm_approved: 'Verified, sent to Head Office', ho_approved: 'Approved for payment', open: 'Sent back to the TSO', rejected: 'Request rejected' }[status])
    },
    flagOpen() { this.set({ fOpen: true }) },
    flagCancel() { this.set({ fOpen: false, fErr: '' }) },
    async flagGo() {
      const S = this.S, flagging = !S.d.ho_flag
      if (!S.fReason.trim()) return this.set({ fErr: 'Write the reason.' })
      this.set({ fBusy: true, fErr: '' })
      const { error } = await supabase.rpc('flag_day', { p_day: S.d.id, p_flag: flagging, p_reason: S.fReason.trim() })
      this.set({ fBusy: false })
      if (error) return this.set({ fErr: errText(error) })
      toast(flagging ? 'Flagged. Payment is on hold.' : 'Flag removed', flagging ? 'bad' : 'ok')
      this.set({ fOpen: false, fReason: '' })
      await changed(this)
    },
    // --- sheets
    openDaBill() { this.set({ sheet: 'da', photo: null, billNo: '', sErr: '' }) },
    openExpense() { this.set({ sheet: 'exp', photo: null, billNo: '', cat: TRAVEL_MODES[this.S.d.travel_mode].own ? 'parking_toll' : 'bus_train', amountX: '', desc: '', from: '', to: '', sErr: '' }) },
    closeSheet() { this.set({ sheet: null }) },
    cat(el) { this.set({ cat: el.dataset.k }) },
    async photo(el) {
      const f = el.files && el.files[0]
      el.value = ''
      if (!f) return
      const S = this.S, { profile } = this.ctx
      this.set({ sErr: '' })
      try {
        // bills may be photographed later, so gallery photos are allowed; they are stamped with who added them
        const lines = S.sheet === 'da'
          ? [`DA bill · ${profile.full_name} · ${fmtDate(S.d.day)}`, `Added ${now()} IST`]
          : [`Bill · ${profile.full_name} · request ${fmtDate(S.d.day)}`, `Added ${now()} IST`]
        const blob = await takePhoto(f, { live: false, lines })
        this.set({ photo: { blob, url: URL.createObjectURL(blob) } })
      } catch (e) { this.set({ sErr: errText(e) }) }
    },
    async saveDaBill() {
      const S = this.S, { profile } = this.ctx
      if (!S.photo) return this.set({ sErr: 'Take a photo of the bill.' })
      this.set({ sBusy: true, sErr: '' })
      try {
        const bill_path = await uploadPhoto(profile.id, 'bills', S.photo.blob)
        const { error } = await supabase.from('expense_items').insert({ day_id: S.d.id, category: 'da_bill', amount: 0, description: 'DA bill', bill_no: S.billNo.trim() || null, bill_path })
        if (error) throw error
        toast('Bill uploaded')
        this.set({ sheet: null })
        await changed(this)
      } catch (e) { this.set({ sErr: errText(e) }) } finally { this.set({ sBusy: false }) }
    },
    async saveExpense() {
      const S = this.S, { profile } = this.ctx, c = CATEGORIES[S.cat], policy = S.policy
      this.set({ sErr: '' })
      const amt = Number(S.amountX)
      const needBill = policy && amt > Number(policy.bill_required_above)
      if (!(amt > 0)) return this.set({ sErr: 'Enter the amount.' })
      if (S.desc.trim().length < 3) return this.set({ sErr: 'Write what it was for.' })
      if (c.route && (!S.from.trim() || !S.to.trim())) return this.set({ sErr: 'Enter from and to.' })
      if (needBill && !S.photo && !confirm(`Bills are needed above ${fmtINR(policy.bill_required_above)}. Add without a bill? It will be flagged.`)) return
      this.set({ sBusy: true })
      try {
        const bill_path = S.photo ? await uploadPhoto(profile.id, 'bills', S.photo.blob) : null
        const { error } = await supabase.from('expense_items').insert({
          day_id: S.d.id, category: S.cat, amount: amt, description: S.desc.trim(),
          from_place: c.route ? S.from.trim() : null, to_place: c.route ? S.to.trim() : null, bill_no: S.billNo.trim() || null, bill_path,
        })
        if (error) throw error
        toast('Bill added')
        this.set({ sheet: null })
        await changed(this)
      } catch (e) { this.set({ sErr: errText(e) }) } finally { this.set({ sBusy: false }) }
    },
  },
}

const setPathValue = (S, path, v) => { S[path] = v }
const ownPatch = (S, extra = {}) => ({ night_halt: S.halt, halt_place: S.halt ? S.place.trim() || null : null, tso_note: S.note.trim() || null, ...extra })

async function updateDay(sc, patch, msg) {
  sc.set({ busy: true, err: '' })
  const { error } = await supabase.from('field_days').update(patch).eq('id', sc.S.d.id)
  sc.set({ busy: false })
  if (error) return sc.set({ err: errText(error) })
  if (msg) toast(msg)
  await changed(sc)
}

async function changed(sc) {
  await load(sc, false)
  const p = sc.ctx.parent
  if (p && p.actions.claimChanged) p.actions.claimChanged.call(p)
}

async function load(sc, first) {
  const { dayId } = sc.ctx.props
  const { data, error } = await supabase.from('field_days')
    .select('*, expense_items(*), person:profiles!field_days_tso_id_fkey(full_name, email)').eq('id', dayId).single()
  if (error) return sc.set({ err: errText(error) })
  data.expense_items.sort((a, b) => a.created_at.localeCompare(b.created_at))
  const patch = { d: data }
  if (first) {
    Object.assign(patch, {
      daText: Number(data.da_requested) > 0 ? String(Number(data.da_requested)) : '',
      halt: data.night_halt, place: data.halt_place || '', note: data.tso_note || '', amount: String(payable(data)),
    })
  }
  sc.set(patch)
  const ev = await supabase.from('claim_events').select('*, actor:profiles!claim_events_actor_fkey(full_name, role)').eq('day_id', dayId).order('at').order('id')
  const v = await supabase.from('visits')
    .select('id, check_in_at, check_out_at, distance_from_office_m, fraud_flags, zm_status, lsgds(name, districts(name))')
    .eq('tso_id', data.tso_id).gte('check_in_at', istStartISO(data.day)).lt('check_in_at', istStartISO(addDays(data.day, 1))).order('check_in_at')
  const paths = [data.start_photo, data.end_photo, ...data.expense_items.map((i) => i.bill_path)].filter(Boolean)
  const pairs = await Promise.all(paths.map(async (p) => [p, await signedUrl(p)]))
  sc.set({ events: ev.data || [], visits: v.data || [], urls: Object.fromEntries(pairs) })
}
