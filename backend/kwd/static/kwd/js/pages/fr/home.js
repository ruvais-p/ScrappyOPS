import { html, supabase, errText, widget } from '../../core.js'
import { Loading, Stat, Icon, PageHead, SectionHead, Progress, Empty } from '../../ui.js'
import { fmtINR, istDate } from '../../lib.js'
import { achievement, monthStart, monthName, fmtWhen, LEAD_OPEN } from '../../fr.js'
import { saleForm } from './parts.js'

const action = (page, filter, ico, tone, title, sub) => html`<li><button class="item" data-act="goto" data-page="${page}" data-filter="${filter || ''}"><span class="lead-ico ${tone}">${Icon(ico)}</span>
  <div class="grow"><div class="title">${title}</div><div class="muted small">${sub}</div></div>${Icon('right')}</button></li>`

export default {
  state: { d: null, err: '', sale: false },
  widgets: { saleform: saleForm },
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { fr, products, stock } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    const d = S.d
    if (!d) return Loading('Loading your dashboard…')
    const today = istDate(), month = monthStart()
    const a = achievement(d.sold, d.targets, month)
    const open = d.leads.filter((l) => LEAD_OPEN.includes(l.status))
    const fresh = d.leads.filter((l) => l.status === 'new')
    const won = d.leads.filter((l) => l.status === 'won').length
    const followDue = open.filter((l) => l.next_followup_on && l.next_followup_on <= today)
    const toDeliver = d.sales.filter((s) => s.delivery_status !== 'delivered')
    const toInstall = d.sales.filter((s) => s.needs_install && s.delivery_status === 'delivered' && s.installation_status !== 'installed')
    const unpaid = d.sales.filter((s) => s.payment_status !== 'paid')
    const overdueMeet = d.pres.filter((p) => new Date(p.scheduled_at) < new Date(Date.now() - 3 * 36e5))
    const nextMeet = d.pres.filter((p) => !overdueMeet.includes(p)).slice(0, 3)
    const unitsInStock = Object.values(stock).reduce((x, y) => x + y, 0)
    const lowStock = products.filter((p) => p.is_active && (stock[p.id] ?? 0) <= 2 && stock[p.id] != null)
    const noStock = Object.keys(stock).length === 0
    const todo = fresh.length + followDue.length + toDeliver.length + toInstall.length + overdueMeet.length
    const names = (arr, k) => arr.slice(0, 3).map((x) => x[k]).join(', ')

    return html`${PageHead({ label: fr.business_name, title: 'Dashboard', sub: new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' }),
        actions: html`<button class="btn primary" data-act="openSale">${Icon('plus', 18)} Record a sale</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: `Target · ${monthName(month)}`, value: a.pctValue != null ? `${a.pctValue}%` : a.pctUnits != null ? `${a.pctUnits}%` : '—',
          sub: a.tValue || a.tUnits ? `${fmtINR(a.value)} of ${a.tValue ? fmtINR(a.tValue) : `${a.tUnits} units`}` : 'No target set yet' })}
        ${Stat({ label: 'Leads from Head Office', value: d.leads.length, sub: `${fresh.length} new · ${open.length} open · ${won} closed` })}
        ${Stat({ label: 'Sales this month', value: fmtINR(a.value), sub: `${a.units} units`, tone: 'ok' })}
        ${Stat({ label: 'Units in stock', value: unitsInStock, sub: noStock ? 'Add your stock' : lowStock.length ? `${lowStock.length} running low` : 'All stocked', tone: lowStock.length || noStock ? 'warn' : '' })}
      </div>
      ${noStock ? html`<div class="next-card key"><span class="eyebrow">Start here</span><h3>Enter the stock you have</h3>
        <p>Sales take units out of stock, so add what is on your shelves first.</p><button class="btn" data-act="goto" data-page="stock">Update stock</button></div>` : ''}

      <section>
        ${SectionHead({ title: 'Needs your action', count: todo, tone: todo ? 'bad' : '' })}
        ${todo === 0 ? Empty('Nothing waiting. You are all caught up.') : html`<ul class="list">
          ${fresh.length > 0 ? action('leads', 'new', 'followup', '', `${fresh.length} new ${fresh.length === 1 ? 'lead' : 'leads'} from Head Office`, names(fresh, 'customer_name')) : ''}
          ${followDue.length > 0 ? action('leads', 'follow', 'clock', 'bad', `${followDue.length} follow-up${followDue.length === 1 ? '' : 's'} due`, names(followDue, 'customer_name')) : ''}
          ${overdueMeet.length > 0 ? action('meetings', '', 'present', 'bad', `${overdueMeet.length} presentation${overdueMeet.length === 1 ? '' : 's'} to update`, `Say how ${overdueMeet.length === 1 ? 'it' : 'they'} went`) : ''}
          ${toDeliver.length > 0 ? action('sales', 'deliver', 'truck', '', `${toDeliver.length} sale${toDeliver.length === 1 ? '' : 's'} to deliver`, names(toDeliver, 'customer_name')) : ''}
          ${toInstall.length > 0 ? action('sales', 'install', 'check', '', `${toInstall.length} installation${toInstall.length === 1 ? '' : 's'} to complete`, names(toInstall, 'customer_name')) : ''}
        </ul>`}
      </section>

      <div class="grid2" style="align-items:start">
        <section class="card">
          <h2>${monthName(month)} target</h2>
          ${a.tValue || a.tUnits ? html`
            ${a.tValue > 0 ? html`<div class="row"><span class="grow">Sales value</span><b>${fmtINR(a.value)} / ${fmtINR(a.tValue)}</b></div>${Progress({ value: a.value, max: a.tValue, label: 'Sales value target' })}` : ''}
            ${a.tUnits > 0 ? html`<div class="row" style="margin-top:12px"><span class="grow">Units sold</span><b>${a.units} / ${a.tUnits}</b></div>${Progress({ value: a.units, max: a.tUnits, label: 'Units target' })}` : ''}`
            : html`<p class="muted">Head Office has not set a target for this month.</p>`}
          <button class="btn sm" style="margin-top:14px" data-act="goto" data-page="targets">Full target report</button>
        </section>
        <section class="card">
          <h2>Next presentations</h2>
          ${nextMeet.length === 0 ? html`<p class="muted">No appointments booked.</p>` : html`<ul class="list">${nextMeet.map((p) => html`<li><div class="item col"><div class="title">${p.venue_name}</div><div class="muted small">${fmtWhen(p.scheduled_at)}${p.address ? ` · ${p.address}` : ''}</div></div></li>`)}</ul>`}
          <button class="btn sm" style="margin-top:14px" data-act="goto" data-page="meetings">Open meetings</button>
        </section>
      </div>

      ${unpaid.length > 0 ? html`<section class="card"><h2>Money to collect</h2>
        <p style="margin:0 0 6px"><b>${fmtINR(unpaid.reduce((x, s) => x + Number(s.total) - Number(s.amount_received), 0))}</b> across ${unpaid.length} sale${unpaid.length === 1 ? '' : 's'}</p>
        <button class="btn sm" data-act="goto" data-page="sales" data-filter="unpaid">See them</button></section>` : ''}
      ${S.sale ? widget(this, 'saleform', 'new', { lead: null }) : ''}`
  },
  actions: {
    goto(el) { this.ctx.go(el.dataset.page, el.dataset.filter ? { filter: el.dataset.filter } : {}) },
    openSale() { this.set({ sale: true }) },
    saleClose() { this.set({ sale: false }) },
    async saleChanged() { await this.actions.load.call(this); await this.ctx.data.refresh() },
    async load() {
      const month = monthStart()
      const [leads, sales, sold, targets, pres] = await Promise.all([
        supabase.from('fr_leads').select('*').order('assigned_at', { ascending: false }),
        supabase.from('fr_sales').select('*').eq('status', 'active').order('sale_date', { ascending: false }),
        supabase.from('v_fr_sold').select('*').gte('month', month),
        supabase.from('fr_targets').select('*').eq('month', month),
        supabase.from('fr_presentations').select('*').eq('status', 'scheduled').order('scheduled_at'),
      ])
      const e = [leads, sales, sold, targets, pres].find((x) => x.error)
      if (e) return this.set({ err: errText(e.error) })
      this.set({ d: { leads: leads.data, sales: sales.data, sold: sold.data, targets: targets.data, pres: pres.data } })
    },
  },
}
