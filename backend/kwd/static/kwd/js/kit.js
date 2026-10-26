/* Pieces shared by many screens: sheets, photo picker, GPS line, team loader, map-link helpers. */
import { html, raw, when, supabase, errText } from './core.js'
import { Icon } from './ui.js'
import { istDate, addDays, DISTRICT_CENTRE } from './lib.js'

/** A bottom sheet / dialog. `close` is the name of the screen action that closes it. */
export const Sheet = ({ title, body, close = 'closeSheet' }) => html`<div class="sheet-bg" data-act="${close}" data-bg>
  <div class="sheet" role="dialog" aria-modal="true" aria-label="${title}">
    <div class="row"><h2 class="grow" style="margin:0">${title}</h2><button class="icon-btn" data-act="${close}" aria-label="Close">✕</button></div>
    ${body}
  </div>
</div>`
// Escape closes the top-most sheet
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return
  const b = Array.from(document.querySelectorAll('.sheet-bg .icon-btn[aria-label="Close"]')).pop()
  if (b) b.click()
})

/** Camera button / preview. `id` links the hidden file input with the button; `act` is the action that receives the chosen file input. */
export function PhotoButton({ id, label, photo, live = true, change = 'photo' }) {
  // Ask supported browsers to capture directly from the camera instead of opening
  // the photo library. `environment` selects the rear camera on phones.
  const input = html`<input id="${id}" type="file" accept="image/*" capture="environment" hidden data-change="${change}">`
  return photo
    ? html`${input}<div class="stack"><img class="photo" src="${photo.url}" alt="${label}" style="max-height:220px;object-fit:cover"><button class="btn block" data-act="pickPhoto" data-for="${id}">${Icon('camera', 18)} Retake</button></div>`
    : html`${input}<button class="btn block photo-btn" data-act="pickPhoto" data-for="${id}">${Icon('camera', 20)} ${label}</button>`
}
/** The pickPhoto action every screen using PhotoButton gets. */
export const photoActions = {
  pickPhoto(el) { const i = document.getElementById(el.dataset.for); if (i) i.click() },
}

export function GpsLine(pos, err) {
  if (err) return html`<p class="notice bad small">${err}</p>`
  if (!pos) return html`<p class="small muted">${Icon('locate', 16)} Finding your location…</p>`
  return html`<p class="small ${pos.acc > 100 ? 'text-warn' : 'muted'}">${Icon('locate', 16)} Location found (±${pos.acc} m)${pos.acc > 100 ? '. Weak signal, it will be flagged.' : ''}</p>`
}

// ZM: TSOs reporting to them + their districts. HO: every TSO + every district.
export async function loadTeam(profile) {
  const isHO = profile.role === 'head_office'
  let q = supabase.from('profiles').select('id, full_name, email, phone, is_active, manager_id, user_districts(districts(id, name))').eq('role', 'tso').order('full_name')
  if (!isHO) q = q.eq('manager_id', profile.id)
  const teamP = q.then(({ data }) => (data || []).map((t) => ({ ...t, districts: t.user_districts.map((u) => u.districts) })))
  const distP = isHO
    ? supabase.from('districts').select('id, name').order('name').then(({ data }) => data || [])
    : supabase.from('user_districts').select('districts(id, name)').eq('user_id', profile.id)
      .then(({ data }) => (data || []).map((d) => d.districts).sort((a, b) => a.name.localeCompare(b.name)))
  const [team, districts] = await Promise.all([teamP, distP])
  return { team, districts }
}

// Call the Head Office staff-admin function and surface its error text
export async function adminUsers(body) {
  const { data, error } = await supabase.functions.invoke('admin-users', { body })
  if (error) {
    let msg = error.message
    try { msg = (await error.context.json()).error || msg } catch { /* keep generic */ }
    throw new Error(msg)
  }
  return data
}

// Monday of the week containing iso date (IST calendar dates)
export function weekStart(iso = istDate()) {
  const d = new Date(iso + 'T00:00:00Z')
  const dow = (d.getUTCDay() + 6) % 7
  return addDays(iso, -dow)
}
export const istStartISO = (iso) => new Date(iso + 'T00:00:00+05:30').toISOString()
export function taskState(t, today = istDate()) {
  if (t.status === 'planned' && t.planned_date < today) return 'missed'
  return t.status
}

// Share links (maps.app.goo.gl) and Plus Codes carry no coordinates the browser can read,
// so the server follows the link and decodes it. districtName gives the Plus Code reference.
export const needsResolving = (t) => /^https?:\/\//i.test(t.trim()) || /[23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{0,7}/i.test(t)
export async function resolveMapLink(text, districtName) {
  const c = DISTRICT_CENTRE[districtName]
  const { data, error } = await supabase.functions.invoke('resolve-map-link', { body: { url: text.trim(), ref: c ? { lat: c[0], lng: c[1] } : undefined } })
  if (error) {
    let msg = 'Could not read that link.'
    try { msg = (await error.context.json()).error || msg } catch { /* keep */ }
    throw new Error(msg)
  }
  return data
}

// Parse "lat, lng" or a Google Maps link into coordinates
export function parseLatLng(text) {
  let s = text || ''
  try { s = decodeURIComponent(s) } catch { /* keep as typed */ }
  // the place pin (!3d…!4d…) is more exact than the map view (@…)
  const m = s.match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/) || s.match(/[?&](?:q|query|ll)=(-?\d+\.\d+),\s*(-?\d+\.\d+)/) || s.match(/@(-?\d+\.\d+),\s*(-?\d+\.\d+)/)
    || s.match(/^\s*(-?\d+\.\d+)\s*[, ]\s*(-?\d+\.\d+)\s*$/)
  if (!m) return null
  const lat = Number(m[1]), lng = Number(m[2])
  if (lat < 8 || lat > 13 || lng < 74 || lng > 78) return { lat, lng, outside: true } // outside Kerala
  return { lat, lng }
}

/** Escape-free attribute helpers for templates */
export const sel = (cond) => (cond ? raw('selected') : '')
export const chk = (cond) => (cond ? raw('checked') : '')
export const dis = (cond) => (cond ? raw('disabled') : '')
export const options = (pairs, cur) => pairs.map(([k, l]) => html`<option value="${k}" ${sel(String(k) === String(cur))}>${l}</option>`)
export const errLine = (e) => (e ? html`<p class="error" role="alert">${e}</p>` : '')
export { errText }
