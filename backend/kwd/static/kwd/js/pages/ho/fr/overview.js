import { html, supabase, errText, toast } from '../../../core.js'
import { Loading, Stat, Icon, PageHead, SectionHead } from '../../../ui.js'
import { fmtINR, istDate } from '../../../lib.js'
import { achievement, monthStart, monthName, LEAD_STATUS, LEAD_OPEN, daysSince } from '../../../fr.js'

export default {
  state: { d: null, err: '', busy: false },
  async init() {
    const r = await Promise.all([
      supabase.from('fr_leads').select('id, franchise_id, status, assigned_at, last_update_at, next_followup_on'),
      supabase.from('fr_sales').select('id, franchise_id, status, sale_date, total, amount_received, delivery_status, needs_install, installation_status, delivered_on, ho_flag, flags, created_at'),
      supabase.from('v_fr_sold').select('*'),
      supabase.from('fr_targets').select('*'),
      supabase.from('fr_presentations').select('id, franchise_id, status, scheduled_at, reschedule_count, outcome'),
      supabase.from('v_fr_stock').select('*'),
    ])
    const e = r.find((x) => x.error)
    if (e) return this.set({ err: errText(e.error) })
    this.set({ d: { leads: r[0].data, sales: r[1].data, sold: r[2].data, targets: r[3].data, pres: r[4].data, stock: r[5].data } })
  },
  view(S, ctx) {
    const { frs, products } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    const d = S.d
    if (!d) return Loading('Loading franchise numbers…')
    const month = monthStart()
    const active = frs.filter((f) => f.is_active)
    const all = achievement(d.sold, d.targets, month)
    const openLeads = d.leads.filter((l) => LEAD_OPEN.includes(l.status))
    const staleNew = d.leads.filter((l) => l.status === 'new' && daysSince(l.assigned_at) >= 3)
    const live = d.sales.filter((s) => s.status === 'active')
    const lateDeliver = live.filter((s) => s.delivery_status !== 'delivered' && daysSince(s.sale_date) >= 7)
    const lateInstall = live.filter((s) => s.needs_install && s.delivery_status === 'delivered' && s.installation_status !== 'installed' && daysSince(s.delivered_on) >= 14)
    const flagged = live.filter((s) => s.ho_flag || (s.flags || []).length)
    const dueMeet = d.pres.filter((p) => p.status === 'scheduled' && new Date(p.scheduled_at) < new Date(Date.now() - 24 * 36e5))
    const heldMonth = d.pres.filter((p) => p.status === 'done' && p.scheduled_at >= month).length
    const noStockEntered = active.filter((f) => !d.stock.some((s) => s.franchise_id === f.id))
    const collect = live.reduce((a, s) => a + Number(s.total) - Number(s.amount_received), 0)
    const board = active.map((f) => {
      const a = achievement(d.sold, d.targets, month, f.id)
      const L = d.leads.filter((l) => l.franchise_id === f.id)
      const won = L.filter((l) => l.status === 'won').length, lost = L.filter((l) => l.status === 'lost').length
      const units = d.stock.filter((s) => s.franchise_id === f.id).reduce((x, s) => x + s.on_hand, 0)
      return { f, a, leads: L.length, open: L.filter((l) => LEAD_OPEN.includes(l.status)).length, won, lost, conv: won + lost ? Math.round((100 * won) / (won + lost)) : null, units,
        pend: live.filter((s) => s.franchise_id === f.id && s.delivery_status !== 'delivered').length }
    }).sort((x, y) => (y.a.pctValue ?? -1) - (x.a.pctValue ?? -1) || y.a.value - x.a.value)
    const byStatus = Object.keys(LEAD_STATUS).map((k) => ({ k, label: LEAD_STATUS[k].label, n: d.leads.filter((l) => l.status === k).length }))
    const maxS = Math.max(1, ...byStatus.map((x) => x.n))
    const attention = [
      [staleNew.length, `new lead${staleNew.length === 1 ? '' : 's'} not touched for 3+ days`, 'leads'],
      [lateDeliver.length, `sale${lateDeliver.length === 1 ? '' : 's'} undelivered after 7+ days`, 'sales'],
      [lateInstall.length, `installation${lateInstall.length === 1 ? '' : 's'} pending 14+ days after delivery`, 'sales'],
      [flagged.length, `sale${flagged.length === 1 ? '' : 's'} flagged by the system or by you`, 'sales'],
      [dueMeet.length, `presentation${dueMeet.length === 1 ? '' : 's'} with no outcome after a day`, 'meetings'],
      [noStockEntered.length, `franchisee${noStockEntered.length === 1 ? '' : 's'} with no stock entered`, 'stock'],
    ].filter((x) => x[0] > 0)
    return html`${PageHead({ label: 'Head Office · Franchise', title: 'Franchise overview', sub: `${monthName(month)} · all franchisees together`,
        actions: html`<button class="btn" ${S.busy ? 'disabled' : ''} data-act="download">${Icon('download', 18)} ${S.busy ? 'Preparing…' : 'Excel'}</button>
          <button class="btn primary" data-act="goto" data-page="leads" data-assign="1">${Icon('plus', 18)} Assign leads</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Sold this month', value: fmtINR(all.value), sub: `${all.units} units${all.tValue ? ` · ${all.pctValue}% of ${fmtINR(all.tValue)}` : ''}` })}
        ${Stat({ label: 'Open leads', value: openLeads.length, sub: `${d.leads.length} given in total` })}
        ${Stat({ label: 'Active franchisees', value: active.length, sub: `${frs.length - active.length} switched off` })}
        ${Stat({ label: 'To collect', value: fmtINR(collect), tone: collect ? 'warn' : '', sub: `${live.filter((s) => s.delivery_status !== 'delivered').length} to deliver` })}
        ${Stat({ label: 'Presentations held', value: heldMonth, sub: 'this month' })}
      </div>
      ${attention.length > 0 ? html`<section>${SectionHead({ title: 'Needs a look', count: attention.reduce((a, x) => a + x[0], 0), tone: 'bad' })}
        <ul class="list">${attention.map(([n, text, page]) => html`<li><button class="item" data-act="goto" data-page="${page}"><span class="lead-ico bad">${Icon('alert')}</span>
          <div class="grow"><div class="title">${n} ${text}</div></div>${Icon('right')}</button></li>`)}</ul></section>` : ''}
      <section>
        ${SectionHead({ title: 'Franchisees this month', count: board.length, action: html`<button class="btn sm" data-act="goto" data-page="franchisees">Manage</button>` })}
        ${board.length === 0 ? html`<p class="muted">No franchisees yet. Add one under Franchisees.</p>` : html`<div class="table-wrap"><table>
          <thead><tr><th>Franchisee</th><th class="num">Leads</th><th class="num">Open</th><th class="num">Won / lost</th><th class="num">Conversion</th><th class="num">Sold</th><th class="num">Target</th><th class="num">Achieved</th><th class="num">Stock</th><th class="num">To deliver</th></tr></thead>
          <tbody>${board.map(({ f, a, leads, open, won, lost, conv, units, pend }) => html`<tr>
            <td><b>${f.business_name}</b><div class="muted small">${f.profile && f.profile.full_name}</div></td>
            <td class="num">${leads}</td><td class="num">${open}</td><td class="num">${won} / ${lost}</td><td class="num">${conv != null ? `${conv}%` : '—'}</td>
            <td class="num">${fmtINR(a.value)}<div class="muted small">${a.units} units</div></td>
            <td class="num">${a.tValue ? fmtINR(a.tValue) : html`<span class="text-warn">Not set</span>`}</td>
            <td class="num">${a.pctValue != null ? html`<span class="pill ${a.pctValue >= 100 ? 'ok' : a.pctValue >= 50 ? '' : 'warn'}">${a.pctValue}%</span>` : '—'}</td>
            <td class="num">${units === 0 ? html`<span class="text-warn">0</span>` : units}</td><td class="num">${pend || '—'}</td></tr>`)}</tbody></table></div>`}
      </section>
      <section class="card"><h2>Leads by status</h2><div class="bars">${byStatus.map((s) => html`<div class="bar-row"><span>${s.label}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(s.n / maxS) * 100}%"></div></div><span style="text-align:right">${s.n}</span></div>`)}</div></section>`
  },
  actions: {
    goto(el) { this.ctx.go(el.dataset.page, el.dataset.assign ? { assign: true } : {}) },
    async download() {
      this.set({ busy: true })
      try { const { downloadFranchiseReport } = await import('../../../frReport.js'); await downloadFranchiseReport({ title: 'All franchisees' }) }
      catch (e) { toast(errText(e), 'bad') } finally { this.set({ busy: false }) }
    },
  },
}
