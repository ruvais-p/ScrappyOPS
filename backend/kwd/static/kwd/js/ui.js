/* The small visual kit: icons, mascot, loader, empty states, figures, page headers. Each returns html. */
import { html, raw, registerIcon, esc } from './core.js'

// Lucide-style line icons: 24px grid, 1.75 stroke, round caps (brand book §06)
const ICONS = {
  home: ['M3 10.5 12 3l9 7.5', 'M5 9.5V21h14V9.5', 'M9.5 21v-6h5v6'],
  dashboard: ['M3 3h7v9H3z', 'M14 3h7v5h-7z', 'M14 12h7v9h-7z', 'M3 16h7v5H3z'],
  review: ['M9 3h6v3H9z', 'M9 4.5H6a1 1 0 0 0-1 1V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V5.5a1 1 0 0 0-1-1h-3', 'm9 14 2 2 4-4'],
  calendar: ['M8 2v4', 'M16 2v4', 'M3 10h18', 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z'],
  followup: ['M8 2v4', 'M16 2v4', 'M3 10h18', 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z', 'm9 16 2 2 4-4'],
  building: ['M4 21V9l8-5 8 5v12', 'M9 21v-6h6v6', 'M2 21h20'],
  phone: ['M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.96.36 1.9.7 2.8a2 2 0 0 1-.45 2.1L8.1 9.9a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.1-.45c.9.34 1.85.6 2.8.7A2 2 0 0 1 22 16.9z'],
  pin: ['M12 22s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z', 'M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
  plus: ['M12 5v14', 'M5 12h14'],
  logout: ['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4', 'm16 17 5-5-5-5', 'M21 12H9'],
  users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2', 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M22 21v-2a4 4 0 0 0-3-3.87', 'M16 3.13a4 4 0 0 1 0 7.75'],
  alert: ['M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z', 'M12 9v4', 'M12 17h.01'],
  check: ['M20 6 9 17l-5-5'],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  flag: ['M4 22V4', 'M4 4h13l-2 4 2 4H4'],
  locate: ['M12 2v3', 'M12 19v3', 'M2 12h3', 'M19 12h3', 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z'],
  left: ['m15 18-6-6 6-6'],
  right: ['m9 18 6-6-6-6'],
  camera: ['M14.5 4h-5L7.5 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3.5z', 'M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'],
  list: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01'],
  message: ['M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 21l2.1-5.6A8.4 8.4 0 1 1 21 11.5z'],
  mail: ['M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z', 'm22 6-10 7L2 6'],
  clock: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 6v6l4 2'],
  trend: ['m22 7-8.5 8.5-5-5L2 17', 'M16 7h6v6'],
  rupee: ['M6 3h12', 'M6 8h12', 'm6 13 8.5 8', 'M6 13h3a5 5 0 0 0 0-10'],
  checkCircle: ['M22 11.1V12a10 10 0 1 1-5.9-9.1', 'm22 4-10 10-3-3'],
  user: ['M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2', 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z'],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'm21 21-4.3-4.3'],
  down: ['m6 9 6 6 6-6'],
  shield: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', 'm9 12 2 2 4-4'],
  download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm7 10 5 5 5-5', 'M12 15V3'],
  sliders: ['M4 21v-7', 'M4 10V3', 'M12 21v-9', 'M12 8V3', 'M20 21v-5', 'M20 12V3', 'M1 14h6', 'M9 8h6', 'M17 16h6'],
  upload: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm17 8-5-5-5 5', 'M12 3v12'],
  box: ['M21 8 12 3 3 8v8l9 5 9-5z', 'm3 8 9 5 9-5', 'M12 13v8'],
  target: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12z', 'M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z'],
  present: ['M2 4h20v12H2z', 'M8 21h8', 'M12 16v5'],
  truck: ['M1 4h13v12H1z', 'M14 8h4l3 3v5h-7z', 'M5.5 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M17.5 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z'],
  swap: ['M7 4 3 8l4 4', 'M3 8h14', 'm17 20 4-4-4-4', 'M21 16H7'],
  lock: ['M7 11V7a5 5 0 0 1 10 0v4', 'M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z'],
  eye: ['M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
  eyeOff: ['M9.9 4.2A10 10 0 0 1 12 4c6.4 0 10 8 10 8a17 17 0 0 1-2.2 3.2', 'M6.6 6.6A17 17 0 0 0 2 12s3.6 8 10 8a10 10 0 0 0 5.4-1.6', 'M9.9 9.9a3 3 0 0 0 4.2 4.2', 'm2 2 20 20'],
}

export const MODE_ICON = { visit: 'pin', call: 'phone', whatsapp: 'message', email: 'mail' }

export function icon(name, size = 22) {
  const paths = (ICONS[name] || []).map((d) => `<path d="${d}"/>`).join('')
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`
}
registerIcon(icon)
/** The icon as html, for use inside html`` templates. */
export const Icon = (name, size = 22) => raw(icon(name, size))

// Reduce · Reuse · Recycle (brand book §05). Always in this order; triangles never rotate.
const RS = {
  reduce: { vb: '0 0 111.6 100', vbo: '-3 -3 117.6 106', d: 'M99.10 0.00L12.50 0.00A12.50 12.50 0 0 0 1.67 18.75L44.98 93.75A12.50 12.50 0 0 0 66.63 93.75L109.93 18.75A12.50 12.50 0 0 0 99.10 0.00Z' },
  reuse: { vb: '0 0 100 100', vbo: '0 0 100 100', circle: true },
  recycle: { vb: '0 0 111.6 100', vbo: '-3 -3 117.6 106', d: 'M12.50 100.00L99.10 100.00A12.50 12.50 0 0 0 109.93 81.25L66.63 6.25A12.50 12.50 0 0 0 44.98 6.25L1.67 81.25A12.50 12.50 0 0 0 12.50 100.00Z' },
}
// mode: 'hop' (loader), 'solid' (done), 'outline' (waiting); h = shape height in px
export function ThreeRs({ mode = 'solid', h = 18, label } = {}) {
  const outline = mode === 'outline'
  const shapes = ['reduce', 'reuse', 'recycle'].map((k) => {
    const s = RS[k]
    const paint = outline ? 'fill="none" stroke="currentColor" stroke-width="4.5"' : 'fill="currentColor"'
    const body = s.circle ? `<circle cx="50" cy="50" r="${outline ? 47.75 : 50}" ${paint}/>` : `<path d="${s.d}" ${paint}/>`
    return `<svg viewBox="${outline ? s.vbo : s.vb}">${body}</svg>`
  }).join('')
  return raw(`<span class="three-rs${mode === 'hop' ? ' hop' : ''}" style="--h:${h}px;gap:${Math.round(h * 0.3)}px" ${label ? `role="img" aria-label="${esc(label)}"` : 'aria-hidden="true"'}>${shapes}</span>`)
}

// The loader shows only after 300 ms (brand book §09), always with text
export const Loading = (text = 'Loading…') => html`<div class="loading" role="status" aria-live="polite"><span class="late">${ThreeRs({ mode: 'hop', h: 16 })}<span>${text}</span></span></div>`

// Scrappy, the can: the brand mascot. Decorative only. moods: wave, laugh, wink, surprise, think, sad, tired, cheer, love, happy
export const Mascot = ({ mood = 'wave', size = 96, bob = false } = {}) =>
  raw(`<img class="mascot${bob ? ' bob' : ''}" src="/static/kwd/brand/mascot/${mood}.webp" alt="" aria-hidden="true" width="${Math.round(size * 0.76)}" height="${size}" style="--m:${size}px">`)

/** Empty state. `children` is the message (text or html); good news gets the happy pose, "nothing here" the thinking one. */
export function Empty(children, { action, mood } = {}) {
  const text = children instanceof Object && children.s !== undefined ? children.s : String(children ?? '')
  const m = mood || (/(caught up|good work|nothing (due|waiting|to sign)|no overdue|every )/i.test(text) ? 'happy' : 'think')
  return html`<div class="empty"><span class="empty-ico">${Mascot({ mood: m, size: 88 })}</span><p>${children}</p>${action || ''}</div>`
}

// lead = the one figure that answers the screen's question: shown on an Oxblood key surface
export const Stat = ({ label, value, sub, tone, lead }) =>
  html`<div class="stat${tone ? ' ' + tone : ''}${lead ? ' lead' : ''}"><div class="stat-val">${value}</div><div class="stat-label">${label}</div>${sub ? html`<div class="stat-sub">${sub}</div>` : ''}</div>`

// Page header: small label, title, optional subtitle and actions on the right
export const PageHead = ({ label, title, sub, actions }) =>
  html`<header class="page-head"><div class="grow">${label ? html`<span class="section-label">${label}</span>` : ''}<h1>${title}</h1>${sub ? html`<p class="muted">${sub}</p>` : ''}</div>${actions ? html`<div class="page-actions">${actions}</div>` : ''}</header>`

export const SectionHead = ({ title, count, tone, action }) =>
  html`<div class="section-head"><h2>${title}${count != null ? html`<span class="count-badge ${tone || ''}">${count}</span>` : ''}</h2>${action || ''}</div>`

// one brand tint for everyone: no colour per person (brand book: no side palettes)
export function Avatar(name = '', size = 34) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?'
  return html`<span class="avatar" style="width:${size}px;height:${size}px;font-size:${size * 0.38}px" aria-hidden="true">${initials}</span>`
}

export function Progress({ value, max, label }) {
  const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0
  return html`<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${value}" aria-label="${label || ''}"><span style="width:${pct}%"></span></div>`
}

const STAGE_ORDER = ['new', 'first_meeting', 'demo_done', 'proposal_submitted', 'in_annual_plan', 'dpc_approved', 'work_order', 'supplied', 'payment_received']
// 9 small segments showing how far along the purchase process an LSGD is
export function StageMeter(stage) {
  const n = stage === 'lost' ? 9 : STAGE_ORDER.indexOf(stage) + 1
  return raw(`<span class="stage-meter${stage === 'lost' ? ' lost' : ''}" aria-hidden="true">${STAGE_ORDER.map((s, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('')}</span>`)
}

export const typeShort = (t) => ({ grama_panchayat: 'GP', block_panchayat: 'BP', district_panchayat: 'DP', municipality: 'MUN', corporation: 'CORP' }[t] || '—')
