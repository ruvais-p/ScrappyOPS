/* TA / DA requests for a Zonal Manager (verify) or Head Office (final approval, settlement, activity log, rates). */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, PageHead, Empty, Stat, Icon } from '../../ui.js'
import { istDate, addDays, fmtINR, fmtDate } from '../../lib.js'
import { loadTeam, Sheet, errLine } from '../../kit.js'
import { loadPolicy, riskFlags } from '../../expenses.js'
import claimDetail, { ClaimRow } from '../claim.js'
import { reportWidget, ReportButton } from '../report.js'
import settlement from '../ho/settlement.js'
import activityLog from '../ho/activitylog.js'

const ZM_QUEUES = [
  ['todo', 'Waiting for you', (d) => d.status === 'submitted'],
  ['back', 'Sent back', (d) => d.status === 'open' && !!d.zm_remark],
  ['done', 'Verified', (d) => ['zm_approved', 'ho_approved', 'paid'].includes(d.status)],
  ['rejected', 'Rejected', (d) => d.status === 'rejected'],
  ['all', 'All', () => true],
]
const HO_QUEUES = [
  // a ZM's own request comes straight to Head Office
  ['todo', 'To approve', (d) => d.status === 'zm_approved' || (d.status === 'submitted' && (d.person && d.person.role) !== 'tso')],
  ['zm', 'With ZMs', (d) => d.status === 'submitted' && (d.person && d.person.role) === 'tso'],
  ['settle', 'Monthly settlement', (d) => d.status === 'ho_approved'],
  ['flagged', 'Flagged', (d) => d.ho_flag],
  ['log', 'Activity log', () => false],
  ['paid', 'Paid', (d) => d.status === 'paid'],
  ['rejected', 'Rejected', (d) => d.status === 'rejected'],
  ['all', 'All', () => true],
]
const POLICY_FIELDS = [
  ['rate_two_wheeler', 'Two-wheeler rate (₹ per km)'],
  ['rate_car', 'Car rate (₹ per km)'],
  ['da_local', 'DA maximum per day (₹)'],
  ['da_outstation', 'DA maximum per day with night halt (₹)'],
  ['lodging_cap', 'Lodging limit per night (₹)'],
  ['auto_taxi_cap_day', 'Auto / taxi limit per day (₹)'],
  ['bill_required_above', 'Bill photo needed above (₹)'],
  ['max_km_day', 'Daily km limit'],
  ['km_tolerance_pct', 'Allowed km above GPS route (%)'],
  ['road_factor', 'Road factor (road km ÷ straight-line km)'],
  ['claim_window_days', 'Days allowed to submit a request'],
]

export default {
  state: (ctx) => ({ team: null, days: null, err: '', q: ctx.route.queue || 'todo', who: 'all', range: 60, riskOnly: false,
    policy: null, policyOpen: false, pf: null, pbusy: false, perr: '' }),
  widgets: { claim: claimDetail, report: reportWidget, settle: settlement, log: activityLog },
  async init() {
    loadTeam(this.ctx.profile).then((t) => this.set({ team: t.team }))
    if (!this.ctx.route.dayId) await this.actions.load.call(this)
  },
  view(S, ctx) {
    const { profile, route, ho } = ctx
    if (route.dayId) return widget(this, 'claim', route.dayId, { dayId: route.dayId, mode: 'review', ho })
    const today = istDate()
    const queues = ho ? HO_QUEUES : ZM_QUEUES
    const days = S.days
    let body = ''
    if (S.err) body = html`<p class="error">${S.err}</p>`
    else if (!days || !S.team) body = Loading('Loading requests…')
    else {
      const f = queues.find((x) => x[0] === S.q)[2]
      const list = days.filter((d) => f(d) && (S.who === 'all' || d.tso_id === S.who) && (!S.riskOnly || riskFlags(d.flags).length))
      const monthStart = today.slice(0, 8) + '01'
      const month = days.filter((d) => d.day >= monthStart)
      const sum = (arr, k = 'total_claimed') => arr.reduce((s, d) => s + Number(d[k] || 0), 0)
      const waiting = days.filter(queues[0][2])
      const people = ho ? Object.values(Object.fromEntries(days.map((d) => [d.tso_id, { id: d.tso_id, full_name: d.person && d.person.full_name }]))) : S.team
      body = html`<div class="stats">
          ${Stat({ lead: true, label: queues[0][1], value: waiting.length, sub: fmtINR(sum(waiting)), tone: waiting.length ? 'warn' : '' })}
          ${Stat({ label: 'Flagged this month', value: month.filter((d) => riskFlags(d.flags).length).length, sub: fmtINR(sum(month.filter((d) => riskFlags(d.flags).length))) })}
          ${Stat({ label: ho ? 'Approved this month' : 'Verified this month', tone: 'ok', value: fmtINR(sum(month.filter((d) => ['zm_approved', 'ho_approved', 'paid'].includes(d.status)), 'approved_amount')) })}
          ${Stat({ label: 'Paid this month', value: fmtINR(sum(month.filter((d) => d.status === 'paid'), 'approved_amount')) })}
        </div>
        <div class="chips" role="tablist">${queues.map(([id, label, qf]) => {
          const c = days.filter(qf).length
          return html`<button role="tab" aria-selected="${S.q === id}" class="chip${S.q === id ? ' on' : ''}" data-act="queue" data-k="${id}">${label}${id !== 'all' && c ? ` (${c})` : ''}</button>`
        })}</div>
        ${S.q === 'settle' ? widget(this, 'settle', 'x') : S.q === 'log' ? widget(this, 'log', 'x') : html`
          <div class="toolbar">
            <select data-bind="who" data-live aria-label="Staff"><option value="all">All staff</option>${people.map((t) => html`<option value="${t.id}" ${S.who === t.id ? raw('selected') : ''}>${t.full_name || t.email}</option>`)}</select>
            <select data-bind="range" data-change="reload" aria-label="Period">${[[30, 'Last 30 days'], [60, 'Last 60 days'], [180, 'Last 6 months'], [400, 'Last 13 months']].map(([n, l]) => html`<option value="${n}" ${Number(S.range) === n ? raw('selected') : ''}>${l}</option>`)}</select>
            <label class="check inline"><input type="checkbox" data-bind="riskOnly" data-live ${S.riskOnly ? raw('checked') : ''}> <span>Flagged only</span></label>
          </div>
          ${list.length === 0 ? Empty(S.q === 'todo' ? 'Nothing waiting. All caught up.' : 'No requests here for this period.') : html`<ul class="list">${list.map((d) => ClaimRow(d, { showPerson: true, ho }))}</ul>`}`}`
    }
    return html`${PageHead({
        label: ho ? 'Head Office' : 'My zone', title: 'TA / DA requests',
        sub: ho ? 'Final approval and payment. Allowance (DA) is requested with bills. Check the history and flag anything unusual. A Zonal Manager\'s own request comes straight to you.'
          : 'Check each day against the bills, odometer photos, GPS route and visits, then verify, cut, send back or reject. Your own requests are under My own requests and go to Head Office.',
        actions: html`${!ho ? html`<button class="btn" data-act="mine">${Icon('rupee', 18)} My own requests</button>` : ''}
          ${ho ? html`<button class="btn" data-act="openPolicy">${Icon('sliders', 18)} Rates & limits</button>` : ''}
          ${S.team ? ReportButton(this, { team: S.team.map((t) => ({ id: t.id, full_name: t.full_name, email: t.email })) }) : ''}` })}
      ${body}
      ${S.policyOpen ? policySheet(S) : ''}`
  },
  actions: {
    queue(el) { this.set({ q: el.dataset.k }) },
    mine() { this.ctx.go('work') },
    openClaim(el) { this.ctx.go('claims', { dayId: el.dataset.id, queue: this.S.q }) },
    claimBack() { this.ctx.go('claims', { queue: this.ctx.route.queue }) },
    claimChanged() { if (this.ctx.refreshCounts) this.ctx.refreshCounts() },
    reload() { this.set({ days: null }); this.actions.load.call(this) },
    async load() {
      const { profile, ho } = this.ctx
      const { data, error } = await supabase.from('field_days')
        .select('*, person:profiles!field_days_tso_id_fkey(full_name, email, role)')
        .gte('day', addDays(istDate(), -Number(this.S.range))).order('day', { ascending: false })
      if (error) return this.set({ err: errText(error) })
      // a ZM's own requests are approved by Head Office, not shown in their queue
      this.set({ days: ho ? data : data.filter((d) => d.tso_id !== profile.id) })
    },
    // --- rates and limits (Head Office)
    async openPolicy() {
      this.set({ policyOpen: true, pf: null, perr: '' })
      const p = await loadPolicy()
      this.set({ policy: p, pf: Object.fromEntries(POLICY_FIELDS.map(([k]) => [k, String(p[k])])) })
    },
    closePolicy() { this.set({ policyOpen: false }) },
    decimal(el) { el.value = el.value.replace(/[^\d.]/g, ''); this.S.pf[el.dataset.k] = el.value },
    async savePolicy() {
      const S = this.S, patch = {}
      for (const [k, label] of POLICY_FIELDS) {
        const v = Number(S.pf[k])
        if (S.pf[k] === '' || !(v >= 0)) return this.set({ perr: `Check "${label}".` })
        patch[k] = v
      }
      this.set({ pbusy: true, perr: '' })
      // read the row back so a save that didn't land is never reported as saved
      const { data, error } = await supabase.from('expense_policy').update(patch).eq('id', 1).select().maybeSingle()
      this.set({ pbusy: false })
      if (error) return this.set({ perr: errText(error) })
      if (!data || POLICY_FIELDS.some(([k]) => Number(data[k]) !== patch[k])) return this.set({ perr: 'Not saved. Sign in again as Head Office and retry.' })
      toast('Rates and limits saved')
      this.set({ policyOpen: false })
    },
  },
}

function policySheet(S) {
  return Sheet({ title: 'Rates & limits', close: 'closePolicy', body: html`
    <p class="small muted">Applies to requests that are not yet approved. TA is calculated automatically from the rates. For DA the TSO types the amount and uploads bills; the two DA amounts are the most they can request in a day. Approved requests keep their amounts. Every change is recorded in the audit log.</p>
    ${!S.pf ? Loading() : html`<div class="grid2">${POLICY_FIELDS.map(([k, label]) => html`<label>${label}<input data-k="${k}" data-change="decimal" data-oninput value="${S.pf[k]}" inputmode="decimal"></label>`)}</div>`}
    ${S.policy && S.policy.updated_at ? html`<p class="small muted">Last changed ${fmtDate(S.policy.updated_at)}</p>` : ''}
    ${errLine(S.perr)}
    <button class="btn primary block" ${S.pbusy || !S.pf ? raw('disabled') : ''} data-act="savePolicy">${S.pbusy ? 'Saving…' : 'Save'}</button>` })
}
