/* The base layer of the staff app (plain JavaScript, no framework, no build step).
   1. `supabase`-style data client: the screens write  sb.from('visits').select('*, lsgds(name)').eq('id', x)  as before,
      and it posts a structured query to the server (which applies the security rules).
   2. A tiny screen runtime: each screen has state, a view() that returns HTML, and actions bound with data-act.
   3. html`` templates that escape everything by default. */

const SESSION_KEY = 'scrappy_kwd_session'

// ------------------------------------------------------------------------------------------------ safe HTML
export class Safe { constructor(s) { this.s = s } toString() { return this.s } }
export const raw = (s) => new Safe(String(s ?? ''))
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c])
function part(v) {
  if (v == null || v === false || v === true) return ''
  if (v instanceof Safe) return v.s
  if (Array.isArray(v)) return v.map(part).join('')
  return esc(v)
}
/** html`<b>${name}</b>`: every value is escaped unless it is already html (from another html`` or raw()). */
export function html(strings, ...vals) {
  let out = strings[0]
  for (let i = 0; i < vals.length; i++) out += part(vals[i]) + strings[i + 1]
  return new Safe(out)
}
export const when = (cond, v) => (cond ? v : '')

// ------------------------------------------------------------------------------------------------ session
export const session = {
  get() { try { return JSON.parse(localStorage.getItem(SESSION_KEY)) } catch { return null } },
  set(s) { localStorage.setItem(SESSION_KEY, JSON.stringify(s)) },
  clear() { localStorage.removeItem(SESSION_KEY) },
}
let cur = session.get()

function setFromTokens(d) {
  cur = { access_token: d.access_token, refresh_token: d.refresh_token, expires_at: Date.now() + (d.expires_in || 3600) * 1000, user: d.user }
  session.set(cur)
  return cur
}

async function tokenCall(grant, body) {
  const r = await fetch(`/auth/v1/token?grant_type=${grant}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(d.error_description || d.msg || d.message || 'Login failed')
  return setFromTokens(d)
}

let refreshing = null
async function ensureFresh() {
  if (cur && cur.expires_at - Date.now() < 300000) {
    refreshing = refreshing || tokenCall('refresh_token', { refresh_token: cur.refresh_token }).finally(() => { refreshing = null })
    try { await refreshing } catch (e) { endSession('You were logged out. This account may have been opened on another device, or the session expired.'); throw e }
  }
}

export function endSession(message) {
  const t = cur && cur.access_token
  cur = null
  session.clear()
  if (t) fetch('/auth/v1/logout?scope=local', { method: 'POST', headers: { Authorization: 'Bearer ' + t } }).catch(() => {})
  fetch('/logout/', { method: 'POST' }).catch(() => {}).finally(() => { location.replace('/login/' + (message ? '?m=' + encodeURIComponent(message) : '')) })
}

async function call(path, body, { raw: rawBody, headers } = {}, retry = true) {
  await ensureFresh()
  const res = await fetch(path, {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + (cur ? cur.access_token : ''), ...(rawBody ? {} : { 'Content-Type': 'application/json' }), ...headers },
    body: rawBody ? body : JSON.stringify(body),
  })
  if (res.status === 401 && retry && cur) {
    try { await tokenCall('refresh_token', { refresh_token: cur.refresh_token }) } catch (e) { endSession('You were logged out. This account may have been opened on another device, or the session expired.'); throw e }
    return call(path, body, { raw: rawBody, headers }, false)
  }
  const data = await res.json().catch(() => ({}))
  return { ok: res.ok, status: res.status, data }
}

// ------------------------------------------------------------------------------------------------ the data client
const unwrap = (r) => (r.ok ? r.data : { error: r.data.error || { message: 'Request failed' } })

class Query {
  constructor(table) {
    this.q = { table, op: 'select', select: '*', filters: [], order: [] }
    this._write = false
  }
  select(cols = '*', opts = {}) {
    this.q.select = cols
    if (!this._write) this.q.op = 'select'
    if (opts.count) this.q.count = opts.count
    if (opts.head) this.q.head = true
    return this
  }
  insert(values) { this.q.op = 'insert'; this.q.values = values; this._write = true; this.q.select = null; return this }
  update(values) { this.q.op = 'update'; this.q.values = values; this._write = true; this.q.select = null; return this }
  upsert(values, opts = {}) { this.q.op = 'upsert'; this.q.values = values; this.q.onConflict = opts.onConflict; this._write = true; this.q.select = null; return this }
  delete() { this.q.op = 'delete'; this._write = true; this.q.select = null; return this }
  eq(c, v) { this.q.filters.push(['eq', c, v]); return this }
  neq(c, v) { this.q.filters.push(['neq', c, v]); return this }
  gt(c, v) { this.q.filters.push(['gt', c, v]); return this }
  gte(c, v) { this.q.filters.push(['gte', c, v]); return this }
  lt(c, v) { this.q.filters.push(['lt', c, v]); return this }
  lte(c, v) { this.q.filters.push(['lte', c, v]); return this }
  in(c, v) { this.q.filters.push(['in', c, v]); return this }
  is(c, v) { this.q.filters.push(['is', c, v]); return this }
  not(c, op, v) { this.q.filters.push(['not', c, op, v]); return this }
  like(c, v) { this.q.filters.push(['like', c, v]); return this }
  ilike(c, v) { this.q.filters.push(['ilike', c, v]); return this }
  order(c, o = {}) { this.q.order.push([c, o.ascending !== false, o.nullsFirst == null ? null : !!o.nullsFirst]); return this }
  limit(n) { this.q.limit = n; return this }
  range(a, b) { this.q.range = [a, b]; return this }
  single() { this.q.single = true; return this }
  maybeSingle() { this.q.maybe = true; return this }
  then(resolve, reject) {
    return call('/kwd/api/q', this.q).then((r) => {
      if (!r.ok) return { data: null, error: r.data.error || { message: 'Request failed' }, count: null }
      return { data: r.data.data, error: null, count: r.data.count ?? null }
    }).then(resolve, reject)
  }
}

export const supabase = {
  from: (table) => new Query(table),
  async rpc(fn, args = {}) {
    const r = await call('/kwd/api/rpc/' + fn, args)
    return r.ok ? { data: r.data.data, error: null } : { data: null, error: r.data.error || { message: 'Request failed' } }
  },
  functions: {
    async invoke(name, { body } = {}) {
      const r = await call('/kwd/api/fn/' + name, body || {})
      if (r.ok) return { data: r.data, error: null }
      const err = new Error((r.data.error && r.data.error.message) || 'Request failed')
      err.context = { json: async () => ({ error: err.message }) }
      return { data: null, error: err }
    },
  },
  storage: {
    from: () => ({
      async upload(path, blob, opts = {}) {
        const r = await call('/kwd/api/storage/upload?path=' + encodeURIComponent(path), blob, { raw: true, headers: { 'Content-Type': opts.contentType || blob.type || 'image/jpeg' } })
        return r.ok ? { data: { path: r.data.path }, error: null } : { data: null, error: r.data.error || { message: 'Upload failed' } }
      },
      async createSignedUrl(path, seconds = 3600) {
        const r = await call('/kwd/api/storage/sign', { path, expiresIn: seconds })
        return r.ok ? { data: { signedUrl: r.data.signedUrl }, error: null } : { data: null, error: r.data.error || { message: 'Not found' } }
      },
    }),
  },
  auth: {
    getSession: async () => ({ data: { session: cur } }),
    signOut: async () => endSession(),
  },
}

export const errText = (e) => (e && e.message) || String(e)

// ------------------------------------------------------------------------------------------------ DOM patching
/** Update `root` so it shows `htmlString`, changing only what differs. Typing, focus, caret, scroll and playing media survive. */
export function patch(root, htmlString) {
  const t = document.createElement('template')
  t.innerHTML = String(htmlString)
  morphChildren(root, t.content)
}

function morphChildren(from, to) {
  const a = Array.from(from.childNodes), b = Array.from(to.childNodes)
  const keyed = new Map()
  a.forEach((n) => { if (n.nodeType === 1 && n.dataset && n.dataset.key) keyed.set(n.dataset.key, n) })
  let i = 0
  for (; i < b.length; i++) {
    const nb = b[i]
    let na = a[i]
    if (nb.nodeType === 1 && nb.dataset && nb.dataset.key && keyed.has(nb.dataset.key)) {
      const k = keyed.get(nb.dataset.key)
      if (k !== na) from.insertBefore(k, na || null)
      na = k
    }
    if (!na) { from.appendChild(nb.cloneNode(true)); continue }
    if (na.nodeType !== nb.nodeType || (na.nodeType === 1 && na.nodeName !== nb.nodeName)) { from.replaceChild(nb.cloneNode(true), na); continue }
    if (na.nodeType === 3 || na.nodeType === 8) { if (na.nodeValue !== nb.nodeValue) na.nodeValue = nb.nodeValue; continue }
    // a widget keeps its own content; it is rebuilt only when its key or its props changed
    if (na.dataset.widget || nb.dataset.widget) {
      if (na.dataset.widget === nb.dataset.widget && na.dataset.key === nb.dataset.key && na.dataset.sig === nb.dataset.sig) { syncAttrs(na, nb, true); continue }
      from.replaceChild(nb.cloneNode(true), na); continue
    }
    syncAttrs(na, nb)
    if (na.nodeName === 'TEXTAREA') { if (document.activeElement !== na && na.value !== nb.value) na.value = nb.value; continue }
    morphChildren(na, nb)
    if (na.nodeName === 'SELECT') { const v = nb.querySelector('option[selected]'); if (v && na.value !== v.value) na.value = v.value }
  }
  // remove whatever is left over
  const rest = Array.from(from.childNodes)
  for (let j = rest.length - 1; j >= b.length; j--) from.removeChild(rest[j])
}

function syncAttrs(a, b, shallow) {
  for (const at of Array.from(a.attributes)) if (!b.hasAttribute(at.name)) { a.removeAttribute(at.name); if (at.name === 'checked') a.checked = false; if (at.name === 'disabled') a.disabled = false }
  for (const at of Array.from(b.attributes)) {
    if (a.getAttribute(at.name) !== at.value) a.setAttribute(at.name, at.value)
  }
  if (shallow) return
  if (a.nodeName === 'INPUT') {
    const typ = (a.type || '').toLowerCase()
    if (typ === 'checkbox' || typ === 'radio') { if (a.checked !== b.hasAttribute('checked')) a.checked = b.hasAttribute('checked') }
    else if (typ !== 'file' && document.activeElement !== a) { const v = b.getAttribute('value') ?? ''; if (a.value !== v) a.value = v }
  }
  if (a.nodeName === 'OPTION') a.selected = b.hasAttribute('selected')
}

// ------------------------------------------------------------------------------------------------ screens
/** A screen: its own state, a view that returns html, and actions. Events are bound once on the root element:
      data-act="name"         click      -> actions.name(el, event)
      data-submit="name"      form submit -> actions.name(el, event)
      data-bind="field"       input/change -> state.field = value   (add data-live to re-draw as the person types)
      data-change="name"      input/change -> actions.name(el, event) after the value is stored
   actions are called with `this` = the screen, so they can use this.S (state), this.set({...}) and this.ctx. */
export class Screen {
  constructor(root, def, ctx = {}) {
    this.root = root
    this.def = def
    this.ctx = ctx
    this.S = typeof def.state === 'function' ? def.state(ctx) : { ...(def.state || {}) }
    this.alive = true
    this.actions = def.actions || {}
    this._h = {}
    const on = (type, fn) => { this._h[type] = fn; root.addEventListener(type, fn) }
    on('click', (e) => {
      const el = e.target.closest('[data-act]')
      if (!el || !root.contains(el) || !owns(root, el)) return
      if ('bg' in el.dataset && e.target !== el) return   // a click on the dimmed background, not on the sheet
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') return
      const f = this.actions[el.dataset.act]
      if (f) { if (el.tagName === 'A' || el.type === 'submit') e.preventDefault(); f.call(this, el, e) }
    })
    on('submit', (e) => {
      const el = e.target.closest('[data-submit]')
      if (!el || !owns(root, el)) return
      e.preventDefault()
      const f = this.actions[el.dataset.submit]
      if (f) f.call(this, el, e)
    })
    const bind = (e) => {
      const el = e.target
      if (!(el instanceof HTMLElement) || !owns(root, el)) return
      if (el.dataset.bind) {
        const typ = (el.type || '').toLowerCase()
        const v = typ === 'checkbox' ? el.checked : typ === 'file' ? el.files : el.value
        setPath(this.S, el.dataset.bind, v)
      }
      if (el.dataset.change && (e.type === 'change' || 'oninput' in el.dataset)) {
        const f = this.actions[el.dataset.change]
        if (f) f.call(this, el, e)
      }
      if (el.dataset.bind && 'live' in el.dataset) this.render()
    }
    on('input', (e) => { if (e.target.dataset && (e.target.dataset.bind || e.target.dataset.oninput !== undefined)) bind(e) })
    on('change', bind)
    this.children = new Set()
    this.render()
    if (def.init) Promise.resolve(def.init.call(this, this.S, ctx)).catch((e) => console.error(e))
  }
  set(patchObj) { Object.assign(this.S, patchObj); this.render() }
  render() {
    if (!this.alive) return
    const keep = saveFocus(this.root)
    patch(this.root, this.def.view.call(this, this.S, this.ctx))
    restoreFocus(this.root, keep)
    this.mountWidgets()
    if (this.def.after) this.def.after.call(this, this.S, this.ctx)
  }
  /** Start a Screen on every <… data-widget> placeholder (see widget()) that has none yet; drop the ones that left the page. */
  mountWidgets() {
    for (const c of Array.from(this.children)) if (!c.root.isConnected) { c.destroy(); this.children.delete(c) }
    this.root.querySelectorAll('[data-widget]').forEach((el) => {
      if (el._screen) return
      const owner = el.parentElement.closest('[data-widget]')
      if (owner && owner !== this.root) return
      const wdef = (this.def.widgets || {})[el.dataset.widget]
      if (!wdef) return
      const props = (this.wprops && this.wprops.get(el.dataset.key)) || {}
      const child = new Screen(el, wdef, { ...this.ctx, props, parent: this })
      el._screen = child
      this.children.add(child)
    })
  }
  destroy() {
    this.alive = false
    if (this.def.destroyed) this.def.destroyed.call(this)
    for (const c of this.children) c.destroy()
    this.children.clear()
    for (const [t, f] of Object.entries(this._h)) this.root.removeEventListener(t, f)
    this.root.innerHTML = ''
  }
}

// events inside a child widget belong to that widget, not to the screen around it
const owns = (root, el) => { const w = el.closest('[data-widget]'); return !w || w === root || !root.contains(w) }
const hashOf = (str) => { let h = 0; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return h }
/** A placeholder for a child screen with its own state (a list row with a form, a card with sheets).
    The parent's def lists it under `widgets: { name: def }`; its props arrive as ctx.props, and ctx.parent is the parent screen.
    The widget is rebuilt when `key` or the props change. */
export function widget(screen, name, key, props = {}, { tag = 'div', cls = '' } = {}) {
  const k = name + ':' + key
  if (!screen.wprops) screen.wprops = new Map()
  screen.wprops.set(k, props)
  return raw(`<${tag} class="${esc(cls)}" data-widget="${esc(name)}" data-key="${esc(k)}" data-sig="${hashOf(JSON.stringify(props) || '')}"></${tag}>`)
}

function setPath(o, path, v) {
  const parts = path.split('.')
  let t = o
  for (let i = 0; i < parts.length - 1; i++) t = t[parts[i]] = t[parts[i]] || {}
  t[parts[parts.length - 1]] = v
}
export const getPath = (o, path) => path.split('.').reduce((t, k) => (t == null ? t : t[k]), o)

function saveFocus(root) {
  const a = document.activeElement
  if (!a || !root.contains(a) || !a.dataset) return null
  const sel = a.dataset.bind ? `[data-bind="${a.dataset.bind}"]` : a.id ? '#' + a.id : null
  return sel ? { sel, start: a.selectionStart, end: a.selectionEnd } : null
}
function restoreFocus(root, k) {
  if (!k) return
  const el = root.querySelector(k.sel)
  if (el && document.activeElement !== el) { el.focus(); try { if (k.start != null) el.setSelectionRange(k.start, k.end) } catch { /* not a text field */ } }
}

// ------------------------------------------------------------------------------------------------ small helpers
export const $ = (sel, root = document) => root.querySelector(sel)
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel))
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Run an async action once at a time and keep the button from being pressed twice. */
export async function busy(screen, key, fn) {
  if (screen.S[key]) return
  screen.set({ [key]: true })
  try { return await fn() } finally { screen.set({ [key]: false }) }
}

export function toast(text, tone = 'ok') {
  let box = document.querySelector('.toaster')
  if (!box) { box = document.createElement('div'); box.className = 'toaster'; box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite'); document.body.appendChild(box) }
  const t = document.createElement('div')
  t.className = 'toast ' + tone
  t.innerHTML = `${icon(tone === 'bad' ? 'alert' : 'checkCircle', 18)} <span></span>`
  t.querySelector('span').textContent = ' ' + text
  box.appendChild(t)
  setTimeout(() => t.remove(), 3200)
}

// the icon set lives in ui.js, but toast() needs it here: ui.js registers it
let iconFn = () => ''
export const registerIcon = (f) => { iconFn = f }
const icon = (...a) => iconFn(...a)

// poll: has this person logged in somewhere else? (newest login wins)
export function watchSession() {
  setInterval(async () => {
    if (!cur || document.visibilityState !== 'visible') return
    try {
      const r = await fetch('/kwd/api/session', { headers: { Authorization: 'Bearer ' + cur.access_token } })
      if (r.ok && (await r.json()).valid === false) endSession('You were logged out because this account was opened on another device.')
    } catch { /* offline: try again later */ }
  }, 20000)
}
