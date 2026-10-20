/* Head Office: everything that happened on every TA / DA request, newest first. */
import { html, raw, supabase, errText } from '../../core.js'
import { Loading, Empty, Avatar } from '../../ui.js'
import { fmtDate, fmtTime, fmtINR } from '../../lib.js'
import { EVENT_LABEL, EVENT_TONE, CATEGORIES } from '../../expenses.js'

const FILTERS = [
  ['all', 'Everything', () => true],
  ['flags', 'Flags', (e) => e.event.startsWith('ho_flag') || e.event.startsWith('ho_unflag')],
  ['review', 'Verified, approved, rejected', (e) => ['zm_verified', 'ho_approved', 'rejected', 'sent_back'].includes(e.event)],
  ['bills', 'Bills', (e) => e.event.startsWith('bill_')],
  ['paid', 'Payments', (e) => e.event === 'paid'],
]

export default {
  state: { rows: null, err: '', f: 'all', who: '' },
  async init() {
    const { data, error } = await supabase.from('claim_events')
      .select('*, actor:profiles!claim_events_actor_fkey(full_name), day:field_days!claim_events_day_id_fkey(id, day, ho_flag, tso_id, person:profiles!field_days_tso_id_fkey(full_name))')
      .order('at', { ascending: false }).limit(300)
    if (error) return this.set({ err: errText(error) })
    this.set({ rows: data })
  },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading()
    const m = {}
    S.rows.forEach((e) => { if (e.day) m[e.day.tso_id] = e.day.person && e.day.person.full_name })
    const people = Object.entries(m).sort((a, b) => (a[1] || '').localeCompare(b[1] || ''))
    const test = FILTERS.find((x) => x[0] === S.f)[2]
    const list = S.rows.filter((e) => test(e) && (!S.who || (e.day && e.day.tso_id === S.who)))
    return html`<p class="notice small"><span>Every step on every request: who did what, when, and for how much. Nothing here can be edited or deleted. The latest 300 steps are shown.</span></p>
      <div class="toolbar">
        <select data-bind="f" data-live aria-label="What happened">${FILTERS.map(([k, l]) => html`<option value="${k}" ${S.f === k ? raw('selected') : ''}>${l}</option>`)}</select>
        <select data-bind="who" data-live aria-label="Staff"><option value="">All staff</option>${people.map(([id, n]) => html`<option value="${id}" ${S.who === id ? raw('selected') : ''}>${n}</option>`)}</select>
      </div>
      ${list.length === 0 ? Empty('Nothing here yet.') : html`<ul class="list">${list.map((e) => html`<li><button class="item" data-act="open" data-id="${e.day_id}">
        ${Avatar(e.day && e.day.person && e.day.person.full_name, 32)}
        <div class="grow">
          <div class="title">${EVENT_LABEL[e.event] || e.event}${e.amount != null && Number(e.amount) > 0 ? ` · ${fmtINR(e.amount)}` : ''}</div>
          <div class="muted small">${e.day && e.day.person && e.day.person.full_name} · request of ${e.day ? fmtDate(e.day.day) : '—'} · by ${(e.actor && e.actor.full_name) || 'System'}</div>
          ${e.note ? html`<div class="small">${e.note}</div>` : ''}
          ${e.meta && e.meta.category ? html`<div class="small muted">${CATEGORIES[e.meta.category] && CATEGORIES[e.meta.category].label}${e.meta.bill === false ? ' · no bill photo' : ''}</div>` : ''}
        </div>
        <div class="amt"><span class="pill ${EVENT_TONE[e.event] || ''}">${fmtDate(e.at)}</span><span class="muted small">${fmtTime(e.at)}</span></div>
      </button></li>`)}</ul>`}`
  },
  actions: {
    open(el) { this.ctx.go('claims', { dayId: el.dataset.id, queue: 'log' }) },
  },
}
