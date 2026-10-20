/* Constants and small helpers shared by every screen (dates in IST, money, distance, photo stamping). */
export const UNIT_PRICE = 5880

// approximate district centres: the reference point needed to read short Plus Codes (e.g. 56WM+G8F)
export const DISTRICT_CENTRE = {
  Thiruvananthapuram: [8.52, 76.94], Kollam: [8.89, 76.61], Pathanamthitta: [9.26, 76.79], Alappuzha: [9.50, 76.34],
  Kottayam: [9.59, 76.52], Idukki: [9.85, 76.97], Ernakulam: [10.00, 76.31], Thrissur: [10.52, 76.21],
  Palakkad: [10.78, 76.65], Malappuram: [11.07, 76.07], Kozhikode: [11.26, 75.78], Wayanad: [11.69, 76.08],
  Kannur: [11.87, 75.37], Kasaragod: [12.50, 75.00],
}
export const GEOFENCE_M = 300

export const STAGES = [
  { id: 'new', label: 'New lead', prob: 5 },
  { id: 'first_meeting', label: 'First meeting done', prob: 10 },
  { id: 'demo_done', label: 'Demo / presentation done', prob: 20 },
  { id: 'proposal_submitted', label: 'Proposal submitted', prob: 35 },
  { id: 'in_annual_plan', label: 'Included in annual plan', prob: 50 },
  { id: 'dpc_approved', label: 'DPC approved', prob: 70 },
  { id: 'work_order', label: 'Work order received', prob: 90 },
  { id: 'supplied', label: 'Supplied', prob: 95 },
  { id: 'payment_received', label: 'Payment received', prob: 100 },
  { id: 'lost', label: 'Lost', prob: 0 },
]
export const stageLabel = (id) => (STAGES.find((s) => s.id === id) || {}).label ?? id

export const DESIGNATIONS = [
  'President / Chairperson', 'Vice President', 'Secretary', 'Assistant Secretary',
  'Health Standing Committee Chair', 'Health Inspector', 'Village Extension Officer',
  'Ward Member', 'Haritha Karma Sena Coordinator', 'Other',
]

export const INTEREST = ['Cold', 'Low', 'Neutral', 'Warm', 'Hot']

export const LSGD_TYPES = {
  grama_panchayat: 'Grama Panchayat', block_panchayat: 'Block Panchayat',
  district_panchayat: 'District Panchayat', municipality: 'Municipality', corporation: 'Corporation',
}

export const FLAG_TEXT = {
  unplanned: 'Not in plan',
  no_gps: 'No GPS',
  lsgd_location_missing: 'Office location not set',
  outside_geofence: 'Away from LSGD office',
  weak_gps: 'Weak GPS',
  impossible_travel: 'Impossible travel',
  high_volume_day: 'Too many visits today',
}

// Dates in IST, as yyyy-mm-dd
export function istDate(d = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(d)
}
export function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
export function financialYear(iso = istDate()) {
  const [y, m] = iso.split('-').map(Number)
  const start = m >= 4 ? y : y - 1
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`
}
// brand book voice: dates as "Sat 14 Nov"
export const fmtDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00+05:30' : iso)
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' })
    .formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.weekday} ${p.day} ${p.month}`
}
export const fmtTime = (ts) =>
  new Date(ts).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })
// whole rupees for big figures; paise shown when an amount has them (TA/DA payments must be exact)
export const fmtINR = (n) => {
  const v = Math.round(Number(n || 0) * 100) / 100
  return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: Number.isInteger(v) ? 0 : 2, maximumFractionDigits: 2 })
}

export function distanceM(lat1, lng1, lat2, lng2) {
  const r = (x) => (x * Math.PI) / 180
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 +
    Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lng2 - lng1) / 2) ** 2
  return 2 * 6371000 * Math.asin(Math.sqrt(a))
}

// Resize, and burn time + GPS + LSGD into the photo as visible evidence
export async function stampPhoto(file, lines) {
  const img = await createImageBitmap(file, { imageOrientation: 'from-image' })
  const scale = Math.min(1, 1280 / Math.max(img.width, img.height))
  const c = document.createElement('canvas')
  c.width = Math.round(img.width * scale)
  c.height = Math.round(img.height * scale)
  const ctx = c.getContext('2d')
  ctx.drawImage(img, 0, 0, c.width, c.height)
  const fs = Math.max(14, Math.round(c.width / 42))
  const lh = fs * 1.35
  const band = lines.length * lh + fs * 0.8
  ctx.fillStyle = 'rgba(0,0,0,0.6)'
  ctx.fillRect(0, c.height - band, c.width, band)
  ctx.fillStyle = '#fff'
  ctx.font = `600 ${fs}px system-ui, sans-serif`
  lines.forEach((l, i) => ctx.fillText(l, fs * 0.6, c.height - band + fs * 0.4 + lh * (i + 0.8)))
  return new Promise((res) => c.toBlob(res, 'image/jpeg', 0.8))
}
