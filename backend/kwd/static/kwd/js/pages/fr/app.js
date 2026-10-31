/* The franchisee's app: its own shell (tabs + sidebar) around the franchise screens. */
import { supabase, Screen, patch, errText, endSession } from '../../core.js'
import { Loading } from '../../ui.js'
import { TopBar, TabBar, SideNav, Blocked } from '../../shell.js?v=20261031-2'
import { loadProducts, loadDistricts } from '../../fr.js'

const TABS = [
  { id: 'home', label: 'Home', icon: 'home' },
  { id: 'leads', label: 'Leads', icon: 'followup', countKey: 'leads' },
  { id: 'sales', label: 'Sales', icon: 'rupee', countKey: 'sales' },
  { id: 'stock', label: 'Stock', icon: 'box' },
  { id: 'meetings', label: 'Meetings', icon: 'present' },
]
const SIDE = [{ label: 'My business', items: [...TABS, { id: 'targets', label: 'Targets', icon: 'target' }] }]
const PAGES = {
  home: () => import('./home.js?v=20261030-1'), leads: () => import('./leads.js?v=20261030-1'), sales: () => import('./sales.js'),
  stock: () => import('./stock.js'), targets: () => import('./targets.js'), meetings: () => import('./meetings.js'),
}

export async function start(root, { profile }) {
  patch(root, `<div class="center">${Loading('Loading your business…')}</div>`)
  const [frRes, { products, byId }, districts, company] = await Promise.all([
    supabase.from('fr_franchises').select('*').maybeSingle(), loadProducts(), loadDistricts(),
    supabase.from('fr_company_settings').select('*').eq('id', 1).maybeSingle(),
  ])
  if (frRes.error || !frRes.data) return patch(root, Blocked(frRes.error ? errText(frRes.error) : 'Your franchise account is not set up yet. Please contact Head Office.'))
  const fr = frRes.data
  if (!fr.is_active) return patch(root, Blocked('Your franchise account is switched off. Please contact Head Office.'))

  const state = { route: { page: 'home' }, counts: {}, screen: null, token: 0 }
  const data = { fr, products, byId, stock: {}, districts, company: company.data, refresh }

  root.innerHTML = `<div class="shell mgr"><div class="dc" data-r="top"></div><div class="desk"><div class="dc" data-r="side"></div><main class="content" data-r="page"></main></div><div class="dc" data-r="tabs"></div></div>`
  const el = (n) => root.querySelector(`[data-r="${n}"]`)
  const chrome = () => {
    const active = state.route.page
    patch(el('top'), TopBar({ profile, label: 'Franchise|Partner' }))
    patch(el('side'), SideNav({ brand: 'Franchise', groups: SIDE, active, counts: state.counts, profile, roleLabel: fr.business_name }))
    patch(el('tabs'), TabBar({ tabs: TABS, active: active === 'targets' ? 'home' : active, counts: state.counts }))
  }

  async function refresh() {
    const [s, l, d, i] = await Promise.all([
      supabase.from('v_fr_stock').select('product_id, on_hand'),
      supabase.from('fr_leads').select('id', { count: 'exact', head: true }).eq('status', 'new'),
      supabase.from('fr_sales').select('id', { count: 'exact', head: true }).eq('status', 'active').neq('delivery_status', 'delivered'),
      supabase.from('fr_sales').select('id', { count: 'exact', head: true }).eq('status', 'active').eq('delivery_status', 'delivered').in('installation_status', ['pending', 'scheduled']),
    ])
    data.stock = Object.fromEntries((s.data || []).map((r) => [r.product_id, r.on_hand]))
    state.counts = { leads: l.count || 0, sales: (d.count || 0) + (i.count || 0) }
    chrome()
    if (state.screen) state.screen.render()
  }

  async function go(page, params = {}) {
    state.route = { page: PAGES[page] ? page : 'home', ...params }
    const mine = ++state.token
    if (state.screen) { state.screen.destroy(); state.screen = null }
    chrome()
    window.scrollTo(0, 0)
    const def = (await PAGES[state.route.page]()).default
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
  go('home')
}
