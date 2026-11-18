/* The telecaller's app: its own shell (tabs + sidebar) around the telecalling screens. */
import { Screen, patch, endSession, supabase } from '../../core.js'
import { TopBar, TabBar, SideNav } from '../../shell.js?v=20261031-2'

const TABS = [
  { id: 'sales', label: 'Sales leads', icon: 'followup', countKey: 'sales' },
  { id: 'franchise', label: 'Franchise leads', icon: 'building', countKey: 'franchise' },
  { id: 'followup', label: 'Follow-up', icon: 'phone', countKey: 'followup' },
  { id: 'billing', label: 'Billing', icon: 'rupee' },
]
const PAGES = {
  sales: () => import('./leads.js?v=20261117-2').then((m) => m.salesLeads),
  franchise: () => import('./leads.js?v=20261117-2').then((m) => m.franchiseLeads),
  followup: () => import('./followup.js?v=20261117-2').then((m) => m.default),
  billing: () => import('./billing.js?v=20261118-3').then((m) => m.default),
}

export async function start(root, { profile }) {
  const state = { route: { page: 'sales' }, counts: {}, screen: null, token: 0 }
  const data = { refresh }

  root.innerHTML = `<div class="shell mgr"><div class="dc" data-r="top"></div><div class="desk"><div class="dc" data-r="side"></div><main class="content" data-r="page"></main></div><div class="dc" data-r="tabs"></div></div>`
  const el = (n) => root.querySelector(`[data-r="${n}"]`)
  const chrome = () => {
    const active = state.route.page
    patch(el('top'), TopBar({ profile, label: 'Telecalling|Sales telecaller' }))
    patch(el('side'), SideNav({ brand: 'Telecalling', groups: [{ label: 'My calls', items: TABS }], active, counts: state.counts, profile, roleLabel: 'Telecaller' }))
    patch(el('tabs'), TabBar({ tabs: TABS, active, counts: state.counts }))
  }

  async function refresh() {
    const [s, f, u] = await Promise.all([
      supabase.from('tc_leads').select('id', { count: 'exact', head: true }).eq('kind', 'sales').eq('status', 'new'),
      supabase.from('tc_leads').select('id', { count: 'exact', head: true }).eq('kind', 'franchise').eq('status', 'new'),
      supabase.from('v_tc_followups').select('id', { count: 'exact', head: true }).eq('temperature', 'hot'),
    ])
    state.counts = { sales: s.count || 0, franchise: f.count || 0, followup: u.count || 0 }
    chrome()
  }

  async function go(page) {
    state.route = { page: PAGES[page] ? page : 'sales' }
    const mine = ++state.token
    if (state.screen) { state.screen.destroy(); state.screen = null }
    chrome()
    window.scrollTo(0, 0)
    const def = await PAGES[state.route.page]()
    if (mine !== state.token) return
    state.screen = new Screen(el('page'), def, { profile, go, route: state.route, data })
  }

  root.addEventListener('click', (e) => {
    const g = e.target.closest('[data-go]')
    if (g && root.contains(g) && !g.closest('[data-r="page"]')) { go(g.dataset.go); return }
    const n = e.target.closest('[data-nav="signout"]')
    if (n) endSession()
  })

  await refresh()
  go('sales')
}
