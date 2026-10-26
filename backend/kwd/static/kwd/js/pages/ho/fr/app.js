/* Head Office's franchise module: its own shell around the franchise screens. */
import { supabase, Screen, patch, errText, endSession } from '../../../core.js'
import { Loading } from '../../../ui.js'
import { TopBar, TabBar, SideNav, Blocked } from '../../../shell.js'
import { loadProducts, loadDistricts } from '../../../fr.js'

const TABS = [
  { id: 'overview', label: 'Overview', icon: 'dashboard' },
  { id: 'leads', label: 'Leads', icon: 'followup' },
  { id: 'sales', label: 'Sales', icon: 'rupee' },
  { id: 'invoices', label: 'Billing', icon: 'rupee' },
  { id: 'stock', label: 'Stock', icon: 'box' },
  { id: 'meetings', label: 'Meetings', icon: 'present' },
  { id: 'franchisees', label: 'Franchisees', icon: 'users' },
  { id: 'targets', label: 'Targets & prices', icon: 'target' },
  { id: 'company-settings', label: 'Company settings', icon: 'sliders' },
]
const SIDE = [{ label: 'Franchise', items: TABS.slice(0, 5) }, { label: 'Set up', items: TABS.slice(5) }]
const PAGES = {
  overview: () => import('./overview.js'), leads: () => import('./leads.js'), sales: () => import('./sales.js'), invoices: () => import('./invoices.js'), stock: () => import('./stock.js'),
  meetings: () => import('./meetings.js'), franchisees: () => import('./franchisees.js'), targets: () => import('./targets.js'), 'company-settings': () => import('./company-settings.js'),
}

export async function start(root, { profile, onSwitch }) {
  patch(root, `<div class="center">${Loading('Loading franchise module…')}</div>`)
  const [fr, { products, byId }, districts, company] = await Promise.all([
    reloadFranchises(), loadProducts(), loadDistricts(), supabase.from('fr_company_settings').select('*').eq('id', 1).maybeSingle(),
  ])
  if (fr.error) return patch(root, Blocked(errText(fr.error)))

  const state = { route: { page: 'overview' }, screen: null, token: 0 }
  const data = { frs: fr.data, products, byId, districts, company: company.data, reload }
  async function reload() { const r = await reloadFranchises(); if (!r.error) data.frs = r.data; if (state.screen) state.screen.render() }

  root.innerHTML = `<div class="shell mgr"><div class="dc" data-r="top"></div><div class="desk"><div class="dc" data-r="side"></div><main class="content" data-r="page"></main></div><div class="dc" data-r="tabs"></div></div>`
  const el = (n) => root.querySelector(`[data-r="${n}"]`)
  const chrome = () => {
    const active = state.route.page
    patch(el('top'), TopBar({ profile, label: 'Franchise|Head Office', onSwitch }))
    patch(el('side'), SideNav({ brand: 'Franchise · Head Office', groups: SIDE, active, profile, roleLabel: 'Head Office', onSwitch }))
    patch(el('tabs'), TabBar({ tabs: TABS.slice(0, 5), active }))
  }
  async function go(page, params = {}) {
    state.route = { page: PAGES[page] ? page : 'overview', ...params }
    const mine = ++state.token
    if (state.screen) { state.screen.destroy(); state.screen = null }
    chrome()
    window.scrollTo(0, 0)
    const def = (await PAGES[state.route.page]()).default
    if (mine !== state.token) return
    state.screen = new Screen(el('page'), def, { profile, go, route: state.route, data })
  }
  const onClick = (e) => {
    const g = e.target.closest('[data-go]')
    if (g && root.contains(g) && !g.closest('[data-r="page"]')) { go(g.dataset.go); return }
    const n = e.target.closest('[data-nav]')
    if (!n) return
    if (n.dataset.nav === 'signout') endSession()
    else if (n.dataset.nav === 'switch' && onSwitch) { destroy(); onSwitch() }
  }
  root.addEventListener('click', onClick)
  function destroy() { state.token++; if (state.screen) state.screen.destroy(); root.removeEventListener('click', onClick); root.innerHTML = '' }
  go('overview')
}

function reloadFranchises() {
  return supabase.from('fr_franchises').select('*, profile:profiles!fr_franchises_user_id_fkey(full_name, email, phone, is_active)').order('business_name')
}
