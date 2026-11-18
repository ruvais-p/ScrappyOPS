/* The accountant's app: a one-screen shell around the Finance bills list. */
import { Screen, patch, endSession } from '../../core.js'
import { TopBar, TabBar, SideNav } from '../../shell.js?v=20261031-2'

const TABS = [{ id: 'bills', label: 'Bills', icon: 'rupee' }]

export async function start(root, { profile }) {
  const state = { route: { page: 'bills' }, screen: null }

  root.innerHTML = `<div class="shell mgr"><div class="dc" data-r="top"></div><div class="desk"><div class="dc" data-r="side"></div><main class="content" data-r="page"></main></div><div class="dc" data-r="tabs"></div></div>`
  const el = (n) => root.querySelector(`[data-r="${n}"]`)
  patch(el('top'), TopBar({ profile, label: 'Finance|Accountant' }))
  patch(el('side'), SideNav({ brand: 'Finance', groups: [{ label: 'Accounts', items: TABS }], active: 'bills', profile, roleLabel: 'Accountant' }))
  patch(el('tabs'), TabBar({ tabs: TABS, active: 'bills' }))

  root.addEventListener('click', (e) => {
    const n = e.target.closest('[data-nav="signout"]')
    if (n) endSession()
  })

  const def = (await import('./bills.js?v=20261117-1')).default
  state.screen = new Screen(el('page'), def, { profile })
}
