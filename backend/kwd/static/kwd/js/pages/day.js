/* Today's attendance + allowance request card (start day, end day). */
import { html, raw, supabase, errText, toast } from '../core.js'
import { Icon } from '../ui.js'
import { istDate, fmtTime, fmtINR } from '../lib.js'
import { TRAVEL_MODES, watchPosition, takePhoto, uploadPhoto, kmText } from '../expenses.js'
import { Sheet, PhotoButton, photoActions, GpsLine, errLine } from '../kit.js'

const stampLines = (title, profile, pos) => [
  `${title} · ${profile.full_name}`, `${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST`,
  pos ? `GPS ${pos.lat.toFixed(5)}, ${pos.lng.toFixed(5)} (±${pos.acc} m)` : 'GPS not available',
]

function startSheet(S) {
  const own = TRAVEL_MODES[S.mode].own
  const body = html`${GpsLine(S.pos, S.gpsErr)}
    <div class="field-label">How are you travelling today?</div>
    <div class="chips">${Object.entries(TRAVEL_MODES).map(([k, m]) => html`<button class="chip${S.mode === k ? ' on' : ''}" data-act="setMode" data-mode="${k}">${m.label}</button>`)}</div>
    ${own ? html`
      <label>Vehicle number<input data-bind="vehicle" data-change="upper" data-oninput value="${S.vehicle}" placeholder="KL 10 AB 1234" autocapitalize="characters"></label>
      <label>Odometer reading (km)<input data-bind="odo" data-change="digits" data-oninput value="${S.odo}" inputmode="numeric" placeholder="e.g. 24518"></label>
      ${PhotoButton({ id: 'day-photo', label: 'Photo of the odometer', photo: S.photo })}
      ${S.photoErr ? html`<p class="error">${S.photoErr}</p>` : ''}
      <p class="small muted">TA is paid on odometer km and checked against your GPS route through the day's visits.</p>`
    : html`<p class="small muted">Type your allowance and upload your bills at the end of the day. TA is calculated for you.</p>`}
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="saveStart">${S.busy ? 'Starting…' : 'Start day'}</button>`
  return Sheet({ title: 'Start your day', body })
}

function endSheet(S) {
  const { day } = S
  const own = TRAVEL_MODES[day.travel_mode].own
  const km = own && S.odo ? Number(S.odo) - day.start_odo : null
  const body = html`${GpsLine(S.pos, S.gpsErr)}
    ${own ? html`
      <p class="small muted">Morning reading: <b>${day.start_odo.toLocaleString('en-IN')} km</b> · ${day.vehicle_no}</p>
      <label>Odometer reading now (km)<input data-bind="odo" data-change="digits" data-oninput data-live value="${S.odo}" inputmode="numeric"></label>
      ${km != null && km >= 0 ? html`<p class="small">Today: <b>${km} km</b></p>` : ''}
      ${PhotoButton({ id: 'day-photo', label: 'Photo of the odometer', photo: S.photo })}
      ${S.photoErr ? html`<p class="error">${S.photoErr}</p>` : ''}`
    : html`<p class="small muted">We record where and when you finished.</p>`}
    <p class="small muted">After this you can add your bills and submit the request. The day can't be restarted.</p>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="saveEnd">${S.busy ? 'Saving…' : 'End day'}</button>`
  return Sheet({ title: 'End your day', body })
}

export default {
  state: () => {
    let vehicle = ''
    try { vehicle = localStorage.getItem('scrappy-vehicle') || '' } catch { /* optional */ }
    return { day: undefined, sheet: null, pos: null, gpsErr: '', mode: 'two_wheeler', vehicle, odo: '', photo: null, photoErr: '', busy: false, err: '' }
  },
  async init() { await this.actions.load.call(this) },

  view(S, ctx) {
    const { day } = S
    if (day === undefined) return ''
    const quiet = ctx.props && ctx.props.quiet
    let body
    if (!day) {
      body = html`<div class="eyebrow">Attendance · TA / DA</div>
        <h3>Start your day</h3>
        <p class="small muted" style="margin:4px 0 12px">Record your odometer and location before the first visit. TA and DA are worked out from this.</p>
        <button class="btn block${quiet ? '' : ' primary'}" style="margin-top:0" data-act="openStart">${Icon('clock', 18)} Start day</button>`
    } else if (!day.end_at) {
      body = html`<div class="eyebrow">Day started ${fmtTime(day.start_at)}</div>
        <h3>${TRAVEL_MODES[day.travel_mode].short}${day.start_odo != null ? ` · ${day.start_odo.toLocaleString('en-IN')} km` : ''}</h3>
        <p class="small muted" style="margin:4px 0 12px">End your day when you finish the last visit, before you reach home.</p>
        <button class="btn block" style="margin-top:0" data-act="openEnd">${Icon('check', 18)} End day</button>`
    } else {
      body = html`<div class="eyebrow">Day ended ${fmtTime(day.end_at)}</div>
        <h3>Request ${fmtINR(day.total_claimed)}</h3>
        <p class="small muted" style="margin:4px 0 12px">
          ${day.visits_count} visit${day.visits_count === 1 ? '' : 's'} · ${kmText(day.odo_km ?? day.gps_km)}${day.status === 'open' ? ' · add bills and submit' : day.status === 'zm_approved' ? ' · verified by your ZM' : ''}
        </p>
        <button class="btn block" style="margin-top:0" data-act="openWork">${Icon('rupee', 18)} ${day.status === 'open' ? 'Open request' : 'View request'}</button>`
    }
    return html`<div class="next-card day-card">${body}</div>${S.sheet === 'start' ? startSheet(S) : ''}${S.sheet === 'end' ? endSheet(S) : ''}`
  },

  actions: {
    ...photoActions,
    async load() {
      const { profile } = this.ctx
      const { data } = await supabase.from('field_days').select('*').eq('tso_id', profile.id).eq('day', istDate()).maybeSingle()
      this.set({ day: data ?? null })
      if (this.ctx.parent) this.ctx.parent.set({ fieldDay: data ?? null })
    },
    openWork() { this.ctx.go('work', { dayId: this.S.day.id }) },
    openStart() { openSheet(this, 'start') },
    openEnd() { openSheet(this, 'end') },
    closeSheet() { closeSheet(this) },
    setMode(el) { this.set({ mode: el.dataset.mode }) },
    upper(el) { el.value = el.value.toUpperCase(); this.S.vehicle = el.value },
    digits(el) { el.value = el.value.replace(/\D/g, ''); this.S.odo = el.value },
    async photo(el) {
      const f = el.files && el.files[0]
      el.value = ''
      if (!f) return
      this.set({ photoErr: '' })
      try {
        const title = this.S.sheet === 'end' ? 'Day end odometer' : 'Day start odometer'
        const blob = await takePhoto(f, { live: true, lines: stampLines(title, this.ctx.profile, this.S.pos) })
        if (this.S.photo) URL.revokeObjectURL(this.S.photo.url)
        this.set({ photo: { blob, url: URL.createObjectURL(blob) } })
      } catch (e) { this.set({ photoErr: errText(e) }) }
    },
    async saveStart() {
      const S = this.S, { profile } = this.ctx
      const own = TRAVEL_MODES[S.mode].own
      this.set({ err: '' })
      if (!S.pos) return this.set({ err: 'Wait for your location.' })
      if (own) {
        if (!S.vehicle.trim()) return this.set({ err: 'Enter the vehicle number.' })
        if (!/^\d{1,7}$/.test(S.odo.trim())) return this.set({ err: 'Enter the odometer reading in km (numbers only).' })
        if (!S.photo) return this.set({ err: 'Take a photo of the odometer.' })
      }
      this.set({ busy: true })
      try {
        const start_photo = own ? await uploadPhoto(profile.id, 'days', S.photo.blob) : null
        const { error } = await supabase.from('field_days').insert({
          travel_mode: S.mode, vehicle_no: own ? S.vehicle.trim() : null, start_odo: own ? Number(S.odo) : null, start_photo,
          start_lat: S.pos.lat, start_lng: S.pos.lng, start_acc: S.pos.acc,
        })
        if (error) throw error
        try { if (own) localStorage.setItem('scrappy-vehicle', S.vehicle.trim()) } catch { /* optional */ }
        toast('Day started')
        closeSheet(this)
        await this.actions.load.call(this)
      } catch (e) {
        this.set({ err: /duplicate key/.test(errText(e)) ? 'Your day is already started.' : errText(e) })
      } finally { this.set({ busy: false }) }
    },
    async saveEnd() {
      const S = this.S, { profile } = this.ctx, day = S.day
      const own = TRAVEL_MODES[day.travel_mode].own
      const km = own && S.odo ? Number(S.odo) - day.start_odo : null
      this.set({ err: '' })
      if (!S.pos) return this.set({ err: 'Wait for your location.' })
      if (own) {
        if (!/^\d{1,7}$/.test(S.odo.trim())) return this.set({ err: 'Enter the odometer reading in km.' })
        if (km < 0) return this.set({ err: `The reading is lower than this morning's (${day.start_odo}).` })
        if (!S.photo) return this.set({ err: 'Take a photo of the odometer.' })
      }
      this.set({ busy: true })
      try {
        const end_photo = own ? await uploadPhoto(profile.id, 'days', S.photo.blob) : null
        const { error } = await supabase.from('field_days').update({
          end_at: new Date().toISOString(), end_odo: own ? Number(S.odo) : null, end_photo,
          end_lat: S.pos.lat, end_lng: S.pos.lng, end_acc: S.pos.acc,
        }).eq('id', day.id)
        if (error) throw error
        toast('Day ended')
        closeSheet(this)
        await this.actions.load.call(this)
      } catch (e) { this.set({ err: errText(e) }) } finally { this.set({ busy: false }) }
    },
  },
  destroyed() { if (this.stopGps) this.stopGps() },
}

function openSheet(sc, which) {
  sc.set({ sheet: which, odo: '', photo: null, photoErr: '', err: '', pos: null, gpsErr: '' })
  if (sc.stopGps) sc.stopGps()
  sc.stopGps = watchPosition(({ pos, err }) => sc.set({ pos, gpsErr: err }))
}
function closeSheet(sc) {
  if (sc.stopGps) sc.stopGps()
  sc.stopGps = null
  sc.set({ sheet: null })
}
