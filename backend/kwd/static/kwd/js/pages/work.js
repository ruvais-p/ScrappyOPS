/* "My work": TA/DA requests and visit history, with Excel download. Also shows one request when route.dayId is set. */
import { html, supabase, errText, widget } from '../core.js'
import { Loading, PageHead, Empty, SectionHead } from '../ui.js'
import { istDate, addDays, fmtINR, fmtDate } from '../lib.js'
import { loadPolicy } from '../expenses.js'
import { monthLabel } from './ho/settlement.js'
import visitsPage from './visits.js'
import claimDetail, { ClaimRow } from './claim.js'
import { reportWidget, ReportButton } from './report.js'

export default {
  state: (ctx) => ({ tab: ctx.route.tab || 'claims', days: null, payments: [], policy: null, err: '' }),
  widgets: { claim: claimDetail, visits: visitsPage, report: reportWidget },
  async init() {
    if (this.ctx.route.dayId) return
    this.set({ policy: await loadPolicy() })
    await this.actions.claimChanged.call(this)
  },
  view(S, ctx) {
    const { profile, route } = ctx
    if (route.dayId) return widget(this, 'claim', route.dayId, { dayId: route.dayId, mode: 'own' })
    return html`${PageHead({ label: 'History', title: 'My work', sub: 'Your requests, visits and a downloadable record of everything.', actions: ReportButton(this) })}
      <div class="seg" role="tablist">
        <button role="tab" aria-selected="${S.tab === 'claims'}" class="${S.tab === 'claims' ? 'on' : ''}" data-act="tab" data-k="claims">TA / DA requests</button>
        <button role="tab" aria-selected="${S.tab === 'visits'}" class="${S.tab === 'visits' ? 'on' : ''}" data-act="tab" data-k="visits">Visits</button>
      </div>
      ${S.tab === 'claims' ? claims(this, S) : widget(this, 'visits', 'mine', { embedded: true })}`
  },
  actions: {
    tab(el) { this.set({ tab: el.dataset.k }) },
    openClaim(el) { this.ctx.go('work', { dayId: el.dataset.id }) },
    claimBack() { this.ctx.go('work', { tab: 'claims' }) },
    async claimChanged() {
      const { profile } = this.ctx
      const today = istDate()
      const since = addDays(today.slice(0, 8) + '01', -150)
      const [d, p] = await Promise.all([
        supabase.from('field_days').select('*').eq('tso_id', profile.id).gte('day', since).order('day', { ascending: false }),
        supabase.from('expense_payments').select('*').eq('tso_id', profile.id).gte('month', since).order('month', { ascending: false }),
      ])
      if (d.error || p.error) return this.set({ err: errText(d.error || p.error) })
      this.set({ days: d.data, payments: p.data })
    },
  },
}

function claims(sc, S) {
  if (S.err) return html`<p class="error">${S.err}</p>`
  if (!S.days) return Loading()
  const { days, payments, policy } = S
  const today = istDate()
  const monthStart = today.slice(0, 8) + '01'
  const sum = (arr, f) => arr.reduce((s, d) => s + f(d), 0)
  const open = days.filter((d) => d.status === 'open' && d.end_at)
  const months = [...new Set(days.map((d) => d.day.slice(0, 7) + '-01'))].sort().reverse().map((m) => {
    const ds = days.filter((d) => d.day.slice(0, 7) + '-01' === m)
    const approved = ds.filter((d) => ['ho_approved', 'paid'].includes(d.status))
    return {
      m, ds, claimed: sum(ds, (d) => Number(d.total_claimed)), approved: sum(approved, (d) => Number(d.approved_amount)),
      waiting: ds.filter((d) => ['submitted', 'zm_approved'].includes(d.status)).length,
      unpaid: sum(ds.filter((d) => d.status === 'ho_approved'), (d) => Number(d.approved_amount)),
      pays: payments.filter((p) => p.month === m),
    }
  })
  return html`${SectionHead({ title: 'Monthly TA / DA' })}
    ${months.length ? html`<div class="month-cards">${months.map((x) => html`<div class="card month-card">
      <div class="row"><b class="grow">${monthLabel(x.m)}</b>${x.m === monthStart ? html`<span class="pill">In progress</span>` : ''}</div>
      <div class="month-nums">
        <div><span>Days</span><b>${x.ds.length}</b></div>
        <div><span>Requested</span><b>${fmtINR(x.claimed)}</b></div>
        <div><span>Approved</span><b>${fmtINR(x.approved)}</b></div>
      </div>
      <div class="small">
        ${x.pays.map((p) => html`<div><span class="pill ok">Paid ${fmtINR(p.amount)}</span> <span class="muted">${fmtDate(p.paid_at)} · ${p.paid_ref}</span></div>`)}
        ${x.unpaid > 0 ? html`<div class="muted">${fmtINR(x.unpaid)} approved, to be paid ${x.m === monthStart ? 'after the month ends' : 'in the monthly settlement'}</div>` : ''}
        ${x.waiting > 0 ? html`<div class="muted">${x.waiting} day${x.waiting > 1 ? 's' : ''} awaiting approval</div>` : ''}
      </div></div>`)}</div>` : ''}
    ${SectionHead({ title: 'Daily requests' })}
    ${open.length > 0 ? html`<p class="notice warn small">${open.length} ended day${open.length > 1 ? 's are' : ' is'} not submitted yet. Submit within ${(policy && policy.claim_window_days) ?? 7} days of the date.</p>` : ''}
    ${days.length === 0 ? Empty('No requests yet. Start your day on the Today screen; your request builds up from there.') : html`<ul class="list">${days.map((d) => ClaimRow(d))}</ul>`}
    <p class="small muted">TA/DA is paid monthly, after the month ends. Showing the last 5 months; use Download Excel for older history.</p>`
}
