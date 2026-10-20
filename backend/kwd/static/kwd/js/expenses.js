/* TA / DA: labels, flag texts, and the helpers around photos and GPS. */
import { supabase, errText } from './core.js'
import { stampPhoto } from './lib.js'

export const TRAVEL_MODES = {
  two_wheeler: { label: 'Own two-wheeler', short: 'Two-wheeler', own: true },
  car: { label: 'Own car', short: 'Car', own: true },
  public_transport: { label: 'Bus / train / auto', short: 'Public transport', own: false },
  none: { label: 'No travel (office / walk)', short: 'No travel', own: false },
}

export const CATEGORIES = {
  da_bill: { label: 'DA bill', group: 'DA' },
  meals: { label: 'Meals / food', group: 'DA' },
  da_other: { label: 'Other allowance bill', group: 'DA' },
  bus_train: { label: 'Bus / train ticket', group: 'TA', route: true },
  auto_taxi: { label: 'Auto / taxi', group: 'TA', route: true },
  parking_toll: { label: 'Parking / toll', group: 'TA' },
  lodging: { label: 'Lodging (hotel / room)', group: 'Lodging' },
  phone_internet: { label: 'Phone / internet', group: 'Other' },
  printing_courier: { label: 'Printing / courier', group: 'Other' },
  other: { label: 'Other', group: 'Other' },
}

export const CLAIM_STATUS = {
  open: ['Not submitted', ''],
  submitted: ['Waiting for ZM', 'warn'],
  zm_approved: ['Verified by ZM', 'ok'],
  rejected: ['Rejected', 'bad'],
  ho_approved: ['Approved · paid monthly', 'ok'],
  paid: ['Paid', 'ok'],
}

// tone: bad = money at risk, warn = check it, info = good to know
export const EXP_FLAGS = {
  km_above_gps: ['Odometer km well above GPS route', 'bad'],
  odometer_overlap: ['Odometer reading overlaps an earlier day', 'bad'],
  duplicate_bill: ['Same bill used before', 'bad'],
  no_field_work: ['No LSGD visit that day (no DA)', 'bad'],
  visits_rejected: ['A visit that day was rejected', 'bad'],
  km_over_daily_limit: ['Over the daily km limit', 'warn'],
  missing_bill: ['Bill photo missing', 'warn'],
  lodging_over_cap: ['Lodging above policy limit', 'warn'],
  da_over_cap: ['Allowance above the daily maximum', 'warn'],
  da_no_bill: ['Allowance without a bill', 'warn'],
  lodging_without_halt: ['Lodging without night halt', 'warn'],
  auto_taxi_over_cap: ['Auto / taxi above daily limit', 'warn'],
  odometer_missing: ['Odometer reading missing', 'warn'],
  no_gps_route: ['No GPS route to compare km', 'warn'],
  no_gps_start: ['No GPS at day start', 'warn'],
  no_gps_end: ['No GPS at day end', 'warn'],
  weak_gps: ['Weak GPS', 'warn'],
  late_start: ['Day started after the first visit', 'warn'],
  late_end: ['Day ended after midnight', 'warn'],
  day_not_ended: ['Day was never ended', 'warn'],
  late_claim: ['Submitted late', 'info'],
  sunday: ['Sunday', 'info'],
}
// history log (claim_events)
export const EVENT_LABEL = {
  da_set: 'Allowance requested', started: 'Day started', ended: 'Day ended', bill_added: 'Bill added', bill_removed: 'Bill removed',
  submitted: 'Request submitted', zm_verified: 'Verified by Zonal Manager', sent_back: 'Sent back', rejected: 'Rejected',
  ho_approved: 'Approved by Head Office', paid: 'Paid', ho_flagged: 'Flagged by Head Office', ho_unflagged: 'Flag removed by Head Office',
}
export const EVENT_TONE = { zm_verified: 'ok', ho_approved: 'ok', paid: 'ok', rejected: 'bad', sent_back: 'warn', ho_flagged: 'bad', ho_unflagged: 'ok' }
export const flagText = (f) => (EXP_FLAGS[f] || [])[0] ?? f
export const flagTone = (f) => (EXP_FLAGS[f] || [])[1] ?? 'warn'
export const riskFlags = (flags = []) => flags.filter((f) => flagTone(f) !== 'info')

export const MAX_PHOTO_AGE_MS = 3 * 60 * 1000

/** The TA/DA rates and limits Head Office set. */
export async function loadPolicy() {
  const { data } = await supabase.from('expense_policy').select('*').single()
  return data
}

/** Live GPS while a sheet is open. Calls onChange({pos, err}); returns a function that stops watching. */
export function watchPosition(onChange) {
  if (!navigator.geolocation) { onChange({ pos: null, err: 'This phone does not support GPS.' }); return () => {} }
  const id = navigator.geolocation.watchPosition(
    (p) => onChange({ err: '', pos: { lat: p.coords.latitude, lng: p.coords.longitude, acc: Math.round(p.coords.accuracy) } }),
    (e) => onChange({ pos: null, err: e.code === 1 ? 'Location is blocked. Allow location for this app in your browser settings.' : 'Still looking for GPS. Step outside or near a window.' }),
    { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 },
  )
  return () => navigator.geolocation.clearWatch(id)
}

// camera photo with a time/GPS stamp; refuses old gallery photos when live = true
export async function takePhoto(file, { live, lines }) {
  if (live && Date.now() - file.lastModified > MAX_PHOTO_AGE_MS) {
    throw new Error('This looks like an older photo from the gallery. Take a new one with the camera.')
  }
  return stampPhoto(file, lines)
}

export async function uploadPhoto(profileId, folder, blob) {
  const path = `${profileId}/${folder}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.jpg`
  if (!blob) throw new Error('Photo missing.')
  const { error } = await supabase.storage.from('visit-photos').upload(path, blob, { contentType: 'image/jpeg' })
  if (error) throw new Error(errText(error))
  return path
}

export async function signedUrl(path) {
  if (!path) return ''
  const { data } = await supabase.storage.from('visit-photos').createSignedUrl(path, 900)
  return (data && data.signedUrl) || ''
}

export const mapLink = (lat, lng) => `https://www.google.com/maps?q=${lat},${lng}`
export const kmText = (n) => (n == null ? '—' : `${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 1 })} km`)
export const payable = (d) => Number(d.approved_amount ?? d.total_claimed)
