/* Entry point of the staff app: loads the profile, then starts the field / zone / Head Office / franchise shell for that role. */
import { supabase, session, Screen, patch, errText, watchSession, endSession, html, raw, when } from './core.js'
import { Loading, Icon } from './ui.js'
import { TopBar, TabBar, SideNav, Blocked } from './shell.js'

const TSO_TABS = [
  { id: 'home', label: 'Today', icon: 'home' },
  { id: 'lsgds', label: 'LSGDs', icon: 'building' },
  { id: 'visit', label: 'Visit', icon: 'plus', primary: true },
  { id: 'followups', label: 'Follow-ups', icon: 'followup' },
  { id: 'work', label: 'My work', icon: 'rupee' },
]
const ZM_TABS = [
  { id: 'overview', label: 'Overview', icon: 'dashboard' },
  { id: 'review', label: 'Review', icon: 'review', countKey: 'review' },
  { id: 'claims', label: 'TA / DA', icon: 'rupee', countKey: 'claims' },
  { id: 'plan', label: 'Plan', icon: 'calendar' },
  { id: 'zlsgds', label: 'LSGDs', icon: 'building' },
  { id: 'calls', label: 'Call-backs', icon: 'phone', countKey: 'calls' },
]
// Head Office: the phone tab bar shows the first five; the desktop sidebar shows all
const HO_TABS = [
  { id: 'overview', label: 'Overview', icon: 'dashboard' },
  { id: 'signoff', label: 'Sign-off', icon: 'check', countKey: 'signoff' },
  { id: 'claims', label: 'TA / DA', icon: 'rupee', countKey: 'claims' },
  { id: 'fraud', label: 'Fraud check', icon: 'alert' },
  { id: 'staff', label: 'Staff', icon: 'users' },
  { id: 'zlsgds', label: 'LSGDs', icon: 'building' },
  { id: 'review', label: 'ZM review queue', icon: 'review', countKey: 'review' },
  { id: 'plan', label: 'Visit plans', icon: 'calendar' },
  { id: 'calls', label: 'Call-backs', icon: 'phone', countKey: 'calls' },
]

// page id -> module. A module's default export is the screen definition; `detail` is the second screen some modules hold.
const def = (path, name = 'default') => () => import(path).then((m) => m[name])
const FIELD = {
  home: def('./pages/home.js'),
  visit: def('./pages/newvisit.js'),
  visits: def('./pages/visits.js'),
  work: def('./pages/work.js'),
  lsgds: def('./pages/lsgds.js'),
  lsgd: def('./pages/lsgds.js', 'detail'),
  followups: def('./pages/followups.js'),
}
const MANAGER = {
  review: def('./pages/zm/review.js'),
  plan: def('./pages/zm/plan.js'),
  zlsgds: def('./pages/zm/zmlsgds.js'),
  calls: def('./pages/zm/callbacks.js'),
  claims: def('./pages/zm/claims.js'),
  work: def('./pages/work.js'),
  visit: def('./pages/newvisit.js'),
  lsgd: def('./pages/lsgds.js', 'detail'),
  signoff: def('./pages/ho/signoff.js'),
  fraud: def('./pages/ho/fraud.js'),
  staff: def('./pages/ho/staff.js'),
  zlsgds: def('./pages/zm/zmlsgds.js'),
}

function startShell(root, { profile, kind, onSwitch }) {
  const ho = kind === 'ho'
  const mgr = kind !== 'field'
  const tabs = ho ? HO_TABS : mgr ? ZM_TABS : TSO_TABS
  const pages = mgr ? MANAGER : FIELD
  const home = mgr ? 'overview' : 'home'
  const roleLabel = ho ? 'Head Office' : 'Zonal Manager'
  const state = { route: { page: home }, counts: {}, screen: null, token: 0 }

  root.innerHTML = mgr
    ? `<div class="shell mgr"><div class="dc" data-r="top"></div><div class="desk"><div class="dc" data-r="side"></div><main class="content" data-r="page"></main></div><div class="dc" data-r="tabs"></div></div>`
    : `<div class="shell"><div class="dc" data-r="top"></div><main class="content" data-r="page"></main><div class="dc" data-r="tabs"></div></div>`
  const el = (n) => root.querySelector(`[data-r="${n}"]`)

  const activeTab = () => (state.route.page === 'lsgd' ? (mgr ? 'zlsgds' : 'lsgds') : state.route.page)

  function chrome() {
    const label = ho ? 'Staff monitoring|Head Office' : mgr ? 'Field|Zonal Manager' : 'Field|Territory Sales Officer'
    patch(el('top'), TopBar({ profile, label, onSwitch }))
    const active = activeTab()
    if (mgr) {
      const groups = ho
        ? [{ label: 'Head Office', items: HO_TABS.slice(0, 6) }, { label: 'Zone tools', items: HO_TABS.slice(6) }]
        : [{ label: 'My zone', items: [...ZM_TABS, { id: 'visit', label: 'Log my visit', icon: 'camera' }, { id: 'work', label: 'My day & requests', icon: 'clock' }] }]
      patch(el('side'), SideNav({ brand: `Field · ${roleLabel}`, groups, active, counts: state.counts, profile, roleLabel, onSwitch }))
    }
    patch(el('tabs'), TabBar({ tabs: tabs.slice(0, 5), active, counts: state.counts }))
  }

  async function refreshCounts() {
    if (!mgr) return
    const [r, c, s, x] = await Promise.all([
      supabase.from('visits').select('id', { count: 'exact', head: true }).eq('zm_status', 'pending'),
      supabase.from('visit_contacts').select('contact_id, contacts!inner(verified_at)', { count: 'exact', head: true }).is('contacts.verified_at', null),
      ho ? supabase.from('visits').select('id', { count: 'exact', head: true }).eq('zm_status', 'verified').is('ho_signed_at', null) : Promise.resolve({ count: 0 }),
      ho ? Promise.all([
        supabase.from('field_days').select('id', { count: 'exact', head: true }).eq('status', 'zm_approved'),
        // a Zonal Manager's own claim comes straight to Head Office
        supabase.from('field_days').select('id, person:profiles!field_days_tso_id_fkey!inner(role)', { count: 'exact', head: true }).eq('status', 'submitted').neq('person.role', 'tso'),
      ]).then(([a, b]) => ({ count: (a.count || 0) + (b.count || 0) }))
        : supabase.from('field_days').select('id', { count: 'exact', head: true }).eq('status', 'submitted').neq('tso_id', profile.id),
    ])
    state.counts = { review: r.count || 0, calls: c.count || 0, signoff: s.count || 0, claims: x.count || 0 }
    chrome()
  }

  async function go(page, params = {}) {
    state.route = { page, ...params }
    const mine = ++state.token
    if (state.screen) { state.screen.destroy(); state.screen = null }
    chrome()
    window.scrollTo(0, 0)
    const pageEl = el('page')
    let load = pages[page]
    if (mgr && (page === 'overview' || !load)) load = ho ? def('./pages/ho/hooverview.js') : def('./pages/zm/overview.js')
    if (!load) load = pages.home
    const d = await load()
    if (mine !== state.token) return
    const needsHo = ['signoff', 'fraud', 'staff'].includes(page) && !ho
    if (needsHo) { pageEl.innerHTML = ''; return }
    state.screen = new Screen(pageEl, d, { profile, go, route: state.route, refreshCounts, ho, kind })
    if (mgr) refreshCounts()
  }

  const onClick = (e) => {
    const g = e.target.closest('[data-go]')
    if (g && root.contains(g) && !g.closest('[data-r="page"]')) { go(g.dataset.go); return }
    const n = e.target.closest('[data-nav]')
    if (n && root.contains(n)) {
      if (n.dataset.nav === 'signout') endSession()
      else if (n.dataset.nav === 'switch' && onSwitch) { destroy(); onSwitch() }
    }
  }
  root.addEventListener('click', onClick)

  // the root is shared with whatever the app shows next, so this shell must let go of it completely
  function destroy() { state.token++; if (state.screen) state.screen.destroy(); root.removeEventListener('click', onClick); root.innerHTML = '' }
  go(home)
  return { destroy }
}

// Head Office signs in to a choice: staff monitoring or the franchise module
async function startHo(root, profile) {
  const back = () => startHo(root, profile)
  const chooser = (await import('./pages/ho/chooser.js')).default
  root.innerHTML = ''
  const screen = new Screen(root, chooser, {
    profile,
    onPick: async (m) => {
      screen.destroy()
      if (m === 'staff') startShell(root, { profile, kind: 'ho', onSwitch: back })
      else {
        patch(root, `<div class="center">${Loading('Loading franchise module…')}</div>`)
        const mod = await import('./pages/ho/fr/app.js?v=20261030-1')
        mod.start(root, { profile, onSwitch: back })
      }
    },
  })
}

async function boot() {
  const root = document.getElementById('app')
  const s = session.get()
  if (!s || !s.user) { location.replace('/logout/'); return }   // clears the page cookie too, so the login page does not bounce back here
  patch(root, `<div class="center">${Loading('Starting…')}</div>`)
  const { data: profile, error } = await supabase.from('profiles').select('*').eq('id', s.user.id).single()
  if (error) { patch(root, Blocked(errText(error))); return }
  if (!profile.is_active) { patch(root, Blocked('Your login is not active yet. Head Office will switch it on.')); return }
  watchSession()
  if (profile.role === 'tso') startShell(root, { profile, kind: 'field' })
  else if (profile.role === 'zonal_manager') startShell(root, { profile, kind: 'zm' })
  else if (profile.role === 'franchisee') (await import('./pages/fr/app.js?v=20261030-1')).start(root, { profile })
  else await startHo(root, profile)
}

// "Sign out" buttons on screens that are not part of a shell (Blocked, chooser)
document.addEventListener('click', (e) => { const n = e.target.closest('[data-nav="signout"]'); if (n && !n.closest('.shell')) endSession() })

boot().catch((e) => { console.error(e); patch(document.getElementById('app'), Blocked(errText(e))) })
