import { html, supabase, errText, widget } from '../../core.js'
import { Loading, Stat, Empty, Icon, PageHead, SectionHead, Avatar } from '../../ui.js'
import { istDate, fmtDate, fmtINR, financialYear, STAGES } from '../../lib.js'
import { loadTeam, weekStart, istStartISO, taskState } from '../../kit.js'
import missed from './missed.js'
import dayCard from '../day.js'

export default {
  state: { team: null, districts: [], d: null, err: '' },
  widgets: { missed, day: dayCard },
  async init() {
    const { profile } = this.ctx
    const today = istDate(), wk = weekStart(today)
    loadTeam(profile).then((t) => this.set(t))
    const [v, t, f, o, s, own] = await Promise.all([
      supabase.from('visits').select('id, tso_id, check_in_at, fraud_flags, zm_status').gte('check_in_at', istStartISO(wk)),
      supabase.from('tasks').select('id, assigned_to, planned_date, status').gte('planned_date', wk).lte('planned_date', today),
      supabase.from('v_overdue_followups').select('id, assigned_to, due_on, mode, notes, lsgd_name, lsgd_id').order('due_on'),
      supabase.from('opportunities').select('stage, expected_units, expected_value, probability, owner_id').eq('financial_year', financialYear()),
      supabase.from('v_shared_contact_phones').select('phone'),
      supabase.from('visits').select('id').eq('tso_id', profile.id).is('details_at', null).eq('zm_status', 'pending'),
    ])
    const e = v.error || t.error || f.error || o.error || s.error || own.error
    if (e) return this.set({ err: errText(e) })
    this.set({ d: { visits: v.data, tasks: t.data, overdue: f.data, opps: o.data, sharedPhones: s.data.length, ownOpen: own.data.length } })
  },
  view(S, ctx) {
    const { profile } = ctx
    if (S.err) return html`<p class="error">${S.err}</p>`
    const { d, team, districts } = S
    if (!d || !team) return Loading('Loading your zone…')
    const today = istDate(), wk = weekStart(today)
    const todayStart = istStartISO(today)
    const visitsToday = d.visits.filter((v) => v.check_in_at >= todayStart)
    const pending = d.visits.filter((v) => v.zm_status === 'pending')
    const pendingFlagged = pending.filter((v) => v.fraud_flags.length > 0)
    const tasksToday = d.tasks.filter((t) => t.planned_date === today)
    const open = d.opps.filter((o) => !['lost', 'payment_received'].includes(o.stage))
    const weighted = open.reduce((s, o) => s + Number(o.expected_value) * o.probability / 100, 0)
    const total = open.reduce((s, o) => s + Number(o.expected_value), 0)
    const name = (id) => (team.find((t) => t.id === id) || {}).full_name || '—'
    const rows = team.map((t) => {
      const vs = d.visits.filter((v) => v.tso_id === t.id)
      const ts = d.tasks.filter((x) => x.assigned_to === t.id)
      return {
        ...t, visits: vs.length, flagged: vs.filter((v) => v.fraud_flags.length > 0).length, rejected: vs.filter((v) => v.zm_status === 'rejected').length,
        planned: ts.filter((x) => x.status !== 'cancelled').length, done: ts.filter((x) => x.status === 'done').length,
        missed: ts.filter((x) => taskState(x, today) === 'missed').length, overdue: d.overdue.filter((f) => f.assigned_to === t.id).length,
        pipeline: d.opps.filter((o) => o.owner_id === t.id && !['lost', 'payment_received'].includes(o.stage)).reduce((s, o) => s + Number(o.expected_value), 0),
      }
    })
    const byStage = STAGES.filter((s) => s.id !== 'lost').map((s) => {
      const os = d.opps.filter((o) => o.stage === s.id)
      return { ...s, n: os.length, value: os.reduce((a, o) => a + Number(o.expected_value), 0) }
    })
    const maxVal = Math.max(1, ...byStage.map((s) => s.value))

    return html`
      ${PageHead({
        label: `Your zone · ${districts.map((x) => x.name).join(', ') || 'no districts'}`, title: `Hello, ${profile.full_name.split(' ')[0] || 'there'}`,
        sub: new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' }),
        actions: html`<button class="btn" data-act="goto" data-page="plan">${Icon('calendar', 18)} Plan visits</button>
          <button class="btn primary" data-act="goto" data-page="review">${Icon('review', 18)} Review visits</button>`,
      })}
      <section class="own-day">
        ${SectionHead({ title: 'My field day' })}
        ${widget(this, 'day', 'today', { quiet: true })}
        <div class="row wrap">
          <button class="btn grow" data-act="goto" data-page="visit">${Icon('camera', 18)} Log my visit</button>
          <button class="btn grow" data-act="goto" data-page="work">${Icon('rupee', 18)} My requests</button>
        </div>
      </section>

      <div class="stats">
        ${Stat({ label: 'Visits today', value: visitsToday.length, sub: `${d.visits.length} this week` })}
        ${Stat({ lead: true, label: 'Waiting for your review', value: pending.length, sub: `${pendingFlagged.length} flagged by system`, tone: pendingFlagged.length ? 'warn' : '' })}
        ${Stat({ label: "Today's plan done", value: `${tasksToday.filter((t) => t.status === 'done').length}/${tasksToday.filter((t) => t.status !== 'cancelled').length}`, tone: 'ok' })}
        ${Stat({ label: `Pipeline ${financialYear()}`, value: fmtINR(total), sub: `Likely ${fmtINR(weighted)}` })}
      </div>

      ${pendingFlagged.length > 0 || d.sharedPhones > 0 || d.ownOpen > 0 ? html`<section>
        ${SectionHead({ title: 'Needs attention' })}
        ${d.ownOpen > 0 ? html`<div class="attention"><span class="lead-ico warn">${Icon('clock', 20)}</span>
          <div class="grow"><b>${d.ownOpen} of your own visit${d.ownOpen > 1 ? 's need' : ' needs'} details</b>
            <div class="muted small">Add what was discussed and the expected business within 3 days of the visit.</div></div>
          <button class="btn sm" data-act="goto" data-page="work" data-tab="visits">Finish</button></div>` : ''}
        ${pendingFlagged.length > 0 ? html`<div class="attention"><span class="lead-ico warn">${Icon('alert', 20)}</span>
          <div class="grow"><b>${pendingFlagged.length} flagged visit${pendingFlagged.length > 1 ? 's' : ''} waiting</b>
            <div class="muted small">The system spotted something: distance, GPS, plan or travel time.</div></div>
          <button class="btn sm" data-act="goto" data-page="review" data-filter="flagged">Review now</button></div>` : ''}
        ${d.sharedPhones > 0 ? html`<div class="attention"><span class="lead-ico bad">${Icon('phone', 20)}</span>
          <div class="grow"><b>${d.sharedPhones} phone number${d.sharedPhones > 1 ? 's' : ''} used at more than one LSGD</b>
            <div class="muted small">Could be a made-up contact. Call to check they are real.</div></div>
          <button class="btn sm" data-act="goto" data-page="calls">Check</button></div>` : ''}
      </section>` : ''}

      <section>
        ${SectionHead({ title: 'Team this week', count: team.length })}
        ${team.length === 0 ? Empty('No TSOs report to you yet. Head Office links TSOs to you when creating their login.') : html`<div class="table-wrap"><table>
          <thead><tr><th>TSO</th><th class="num">Visits</th><th class="num">Flagged</th><th class="num">Rejected</th><th class="num">Plan done</th><th class="num">Missed</th><th class="num">Overdue follow-ups</th><th class="num">Pipeline</th></tr></thead>
          <tbody>${rows.map((r) => html`<tr>
            <td><div class="who-cell">${Avatar(r.full_name || r.email, 32)}<div><b>${r.full_name || r.email}</b><div class="muted small">${r.districts.map((x) => x.name).join(', ')}</div></div></div></td>
            <td class="num">${r.visits}</td>
            <td class="num">${r.flagged ? html`<span class="pill warn">${r.flagged}</span>` : 0}</td>
            <td class="num">${r.rejected ? html`<span class="pill bad">${r.rejected}</span>` : 0}</td>
            <td class="num">${r.done}/${r.planned}</td>
            <td class="num">${r.missed ? html`<span class="text-bad">${r.missed}</span>` : 0}</td>
            <td class="num">${r.overdue ? html`<span class="text-bad">${r.overdue}</span>` : 0}</td>
            <td class="num">${fmtINR(r.pipeline)}</td></tr>`)}</tbody></table></div>`}
        <p class="muted small">Week from ${fmtDate(wk)}. Missed = planned visit date passed with no visit.</p>
      </section>

      ${widget(this, 'missed', 'all', { team: team.map((t) => ({ id: t.id, full_name: t.full_name, email: t.email })) })}

      <section class="card">
        <h2>Pipeline by stage · ${financialYear()}</h2>
        ${d.opps.length === 0 ? html`<p class="muted">No deals yet. They appear when TSOs log visits.</p>` : html`<div class="bars">${byStage.map((s) => html`<div class="bar-row">
          <span>${s.label} <span class="muted">(${s.n})</span></span>
          <div class="bar-track"><div class="bar-fill" style="width:${(s.value / maxVal) * 100}%"></div></div>
          <span class="num" style="text-align:right">${fmtINR(s.value)}</span></div>`)}</div>`}
      </section>

      <section>
        ${SectionHead({ title: 'Overdue follow-ups', count: d.overdue.length, tone: d.overdue.length ? 'bad' : '' })}
        ${d.overdue.length === 0 ? Empty('No overdue follow-ups in your districts.') : html`<ul class="list">${d.overdue.slice(0, 15).map((f) => html`<li>
          <button class="item" data-act="lsgd" data-id="${f.lsgd_id}">
            ${Avatar(name(f.assigned_to), 32)}
            <div class="grow"><div class="title">${f.lsgd_name}</div><div class="muted small">${name(f.assigned_to)} · ${f.mode}${f.notes ? ` · ${f.notes}` : ''}</div></div>
            <span class="pill bad">Due ${fmtDate(f.due_on)}</span></button></li>`)}</ul>`}
      </section>`
  },
  actions: {
    goto(el) {
      const params = {}
      if (el.dataset.tab) params.tab = el.dataset.tab
      if (el.dataset.filter) params.filter = el.dataset.filter
      this.ctx.go(el.dataset.page, params)
    },
    lsgd(el) { this.ctx.go('lsgd', { lsgdId: el.dataset.id, back: 'overview' }) },
  },
}
