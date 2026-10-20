import { html, supabase, errText, widget } from '../core.js'
import { Loading, Icon, Progress, SectionHead, Empty, Mascot } from '../ui.js'
import { istDate, addDays, fmtDate, fmtTime, fmtINR, financialYear, LSGD_TYPES, FLAG_TEXT } from '../lib.js'
import { followupWidget, FollowupList } from './followups.js'
import dayCard from './day.js'

export default {
  state: { data: null, err: '', fieldDay: undefined },
  widgets: { followup: followupWidget, day: dayCard },
  async init() { await this.actions.reload.call(this) },

  view(S, ctx) {
    const { profile } = ctx
    const data = S.data
    const today = istDate()
    const hour = Number(new Intl.DateTimeFormat('en-IN', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }).format(new Date()))
    const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
    const first = profile.full_name.split(' ')[0] || 'there'
    const done = data ? data.todayTasks.filter((t) => t.status === 'done').length : 0
    const total = data ? data.todayTasks.length : 0
    const next = data && data.todayTasks.find((t) => t.status === 'planned')

    return html`
      <header class="page-head home-head">
        <div class="grow">
          <span class="section-label">Kitchen Waste Digester</span>
          <h1>${greet}, ${first}</h1>
          <p class="muted">${new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })}</p>
        </div>
        ${Mascot({ mood: data && total > 0 && done === total ? 'cheer' : 'wave', size: 84, bob: true })}
      </header>
      ${data && total > 0 ? html`<div class="home-progress">
        <div class="row"><span>Today's plan</span><span><b>${done} of ${total}</b> visited</span></div>
        ${Progress({ value: done, max: total, label: "Today's plan progress" })}
      </div>` : ''}
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${widget(this, 'day', 'today')}
      ${!data ? Loading('Loading your day…') : html`
        ${next ? html`<div class="next-card key">
          <div class="eyebrow">Up next</div>
          <h3>${next.lsgds.name}</h3>
          <div class="muted small">${LSGD_TYPES[next.lsgds.type]} · ${next.lsgds.districts.name}</div>
          <p class="small" style="margin:8px 0 12px">${next.purpose}</p>
          <button class="btn block${S.fieldDay ? ' primary' : ''}" style="margin-top:0" data-act="start" data-lsgd="${next.lsgds.id}" data-task="${next.id}">${Icon('pin', 18)} Start visit</button>
        </div>` : html`<div class="next-card">
          <div class="eyebrow">${total ? 'Plan complete' : 'No plan today'}</div>
          <h3>${total ? 'Every planned visit is done' : 'Nothing planned by your manager'}</h3>
          <p class="small muted" style="margin:4px 0 12px">${total ? 'Great work. Clear your follow-ups next.' : 'You can still log any LSGD visit.'}</p>
          <button class="btn block" style="margin-top:0" data-act="logVisit">${Icon('plus', 18)} Log a visit</button>
        </div>`}

        ${data.noDetails.length > 0 ? html`${SectionHead({ title: 'Finish your visits', count: data.noDetails.length, tone: 'warn' })}
          <ul class="list">${data.noDetails.map((v) => html`<li>
            <button class="item" data-act="complete" data-lsgd="${v.lsgd_id}" data-visit="${v.id}">
              <span class="lead-ico warn">${Icon('clock', 20)}</span>
              <div class="grow">
                <div class="title">${v.lsgds.name}</div>
                <div class="muted small">Visited ${fmtDate(v.check_in_at)} · add details by ${fmtDate(new Date(new Date(v.check_in_at).getTime() + 3 * 864e5).toISOString())}</div>
              </div>
              <span class="pill warn">Add details</span>
            </button></li>`)}</ul>` : ''}

        <div class="mini-stats">
          <button class="mini" data-act="goto" data-page="visits"><b>${data.visits.length}</b><span>Visits today</span></button>
          <button class="mini${data.fus.length ? ' warn' : ''}" data-act="goto" data-page="followups"><b>${data.fus.length}</b><span>Follow-ups due</span></button>
          <div class="mini"><b>${fmtINR(data.weighted)}</b><span>Likely orders</span></div>
        </div>

        ${total > 0 ? html`${SectionHead({ title: "Today's plan", count: `${done}/${total}` })}
          <ol class="timeline">${data.todayTasks.map((t, i) => html`<li class="tl ${t.status}">
            <span class="tl-dot">${t.status === 'done' ? Icon('check', 14) : i + 1}</span>
            <div class="item">
              <div class="grow">
                <div class="title">${t.lsgds.name}</div>
                <div class="muted small">${LSGD_TYPES[t.lsgds.type]} · ${t.purpose}</div>
              </div>
              ${t.status === 'done' ? html`<span class="pill ok">Visited</span>` : html`<button class="btn sm" data-act="start" data-lsgd="${t.lsgds.id}" data-task="${t.id}">Start</button>`}
            </div></li>`)}</ol>` : ''}

        ${SectionHead({ title: 'Follow-ups due', count: data.fus.length, tone: data.fus.some((f) => f.due_on < today) ? 'bad' : data.fus.length ? 'warn' : '', action: html`<button class="link small" data-act="goto" data-page="followups">See all</button>` })}
        ${data.fus.length === 0 ? Empty('Nothing due today.') : FollowupList(this, data.fus)}

        ${data.missed.length > 0 ? html`${SectionHead({ title: 'Missed this week', count: data.missed.length, tone: 'bad' })}
          <ul class="list">${data.missed.map((t) => html`<li class="item">
            <span class="lead-ico bad">${Icon('clock', 20)}</span>
            <div class="grow">
              <div class="title">${t.lsgds.name}</div>
              <div class="muted small">Was planned for ${fmtDate(t.planned_date)} · ${t.purpose}</div>
            </div>
            <button class="btn sm" data-act="start" data-lsgd="${t.lsgds.id}">Visit</button>
          </li>`)}</ul>` : ''}

        ${data.visits.length > 0 ? html`${SectionHead({ title: 'Checked in today', count: data.visits.length })}
          <ul class="list">${data.visits.map((v) => html`<li class="item">
            <span class="lead-ico ${v.fraud_flags.length ? 'warn' : 'ok'}">${Icon(v.fraud_flags.length ? 'alert' : 'pin', 20)}</span>
            <div class="grow">
              <div class="title">${v.lsgds.name}</div>
              <div class="muted small">${fmtTime(v.check_in_at)}${v.fraud_flags.length > 0 ? ` · ${v.fraud_flags.map((f) => FLAG_TEXT[f] || f).join(', ')}` : ''}</div>
            </div></li>`)}</ul>` : ''}`}`
  },

  actions: {
    start(el) { this.ctx.go('visit', { lsgdId: el.dataset.lsgd, taskId: el.dataset.task }) },
    logVisit() { this.ctx.go('visit') },
    complete(el) { this.ctx.go('visit', { lsgdId: el.dataset.lsgd, completeVisit: el.dataset.visit }) },
    goto(el) { this.ctx.go(el.dataset.page) },
    async reload() {
      const { profile } = this.ctx
      const today = istDate()
      const startIST = new Date(today + 'T00:00:00+05:30').toISOString()
      const [tasks, fus, visits, opps, noDet] = await Promise.all([
        supabase.from('tasks').select('id, purpose, status, planned_date, lsgds(id, name, type, districts(name))')
          .eq('assigned_to', profile.id).gte('planned_date', addDays(today, -7)).lte('planned_date', today).order('planned_date'),
        supabase.from('followups').select('*, lsgds(name), contacts(name, designation, phone)').eq('assigned_to', profile.id)
          .is('done_at', null).lte('due_on', today).order('due_on'),
        supabase.from('visits').select('id, check_in_at, fraud_flags, lsgds(name)').eq('tso_id', profile.id)
          .gte('check_in_at', startIST).order('check_in_at', { ascending: false }),
        supabase.from('opportunities').select('stage, expected_value, probability').eq('owner_id', profile.id).eq('financial_year', financialYear()),
        supabase.from('visits').select('id, lsgd_id, check_in_at, lsgds(name)').eq('tso_id', profile.id).is('details_at', null)
          .eq('zm_status', 'pending').gte('check_in_at', new Date(Date.now() - 3 * 864e5).toISOString()).order('check_in_at'),
      ])
      const e = tasks.error || fus.error || visits.error || opps.error || noDet.error
      if (e) return this.set({ err: errText(e) })
      const open = opps.data.filter((o) => o.stage !== 'lost' && o.stage !== 'payment_received')
      this.set({
        data: {
          todayTasks: tasks.data.filter((t) => t.planned_date === today && t.status !== 'cancelled'),
          missed: tasks.data.filter((t) => t.planned_date < today && t.status === 'planned'),
          fus: fus.data, visits: visits.data, noDetails: noDet.data,
          weighted: open.reduce((s, o) => s + Number(o.expected_value) * o.probability / 100, 0),
        },
      })
    },
  },
}
