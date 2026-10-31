/* Page chrome: top bar (phones), tab bar (phones), side navigation (desktop). All return html. */
import { html, raw, when, supabase, endSession } from './core.js'
import { Icon, Avatar, Mascot } from './ui.js'

const WORDMARK = '/static/kwd/brand/scrappy-wordmark-oxblood.svg'

export function TopBar({ profile, label, onSwitch }) {
  const lines = label.split('|')
  return html`<header class="topbar">
    <div class="brand">
      <img class="wordmark" src="${WORDMARK}" alt="Scrappy" width="96" height="34">
      <span class="role">${lines.map((l, i) => html`${i > 0 ? raw('<br>') : ''}${l}`)}</span>
    </div>
    <div class="who">
      <span class="hide-sm">${profile.full_name}</span>
      ${onSwitch ? html`<button class="icon-btn" data-nav="switch" aria-label="Switch module" title="Switch module">${Icon('swap')}</button>` : ''}
      <button class="icon-btn" data-change-password aria-label="Change password" title="Change password">${Icon('key', 20)}</button>
      <button class="icon-btn" data-nav="signout" data-password-native aria-label="Sign out" title="Sign out">${Icon('logout')}</button>
    </div>
  </header>`
}

export function TabBar({ tabs, active, counts = {} }) {
  return html`<nav class="tabbar" aria-label="Main">${tabs.map((t) => html`
    <button class="tab${active === t.id ? ' active' : ''}${t.primary ? ' primary' : ''}" data-go="${t.id}" ${active === t.id ? raw('aria-current="page"') : ''}>
      <span class="tab-ico">${Icon(t.icon)}</span>
      <span>${t.label}${t.countKey && counts[t.countKey] ? ` (${counts[t.countKey]})` : ''}</span>
    </button>`)}</nav>`
}

// Desktop sidebar. groups = [{ label, items: [{ id, label, icon, countKey }] }]
export function SideNav({ brand, groups, active, counts = {}, profile, roleLabel, onSwitch, switchLabel = 'Switch module' }) {
  return html`<nav class="sidenav" aria-label="Main">
    <div class="side-brand">
      <img class="wordmark" src="${WORDMARK}" alt="Scrappy" width="96" height="34">
      <span>${brand}</span>
    </div>
    ${groups.map((g) => html`
      <div class="nav-label">${g.label}</div>
      ${g.items.map((t) => html`<button class="${active === t.id ? 'active' : ''}" data-go="${t.id}" ${active === t.id ? raw('aria-current="page"') : ''}>
        ${Icon(t.icon, 20)} ${t.label}
        ${when(t.countKey && counts[t.countKey] > 0, html`<span class="count">${counts[t.countKey]}</span>`)}
      </button>`)}`)}
    ${onSwitch ? html`<button data-nav="switch">${Icon('swap', 20)} ${switchLabel}</button>` : ''}
    <div class="me">
      ${Avatar(profile.full_name, 34)}
      <div><b>${profile.full_name}</b><small>${roleLabel}</small></div>
      <button class="icon-btn" data-change-password aria-label="Change password" title="Change password">${Icon('key', 18)}</button>
      <button class="icon-btn" data-nav="signout" data-password-native aria-label="Sign out" title="Sign out">${Icon('logout', 18)}</button>
    </div>
  </nav>`
}

export const Blocked = (text) => html`<div class="center">
  <div class="card accent narrow">
    <div style="margin:0 auto 8px;width:fit-content">${Mascot({ mood: 'sad', size: 120 })}</div>
    <p style="text-align:center">${text}</p>
    <button class="btn" data-nav="signout">Sign out</button>
  </div>
</div>`

export const signOut = () => supabase.auth.signOut()
export { endSession }
