/* Plan the week: assign LSGD visits to each TSO. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { istDate, addDays, fmtDate, LSGD_TYPES, stageLabel, financialYear } from '../../lib.js'
import { loadTeam, weekStart, taskState, Sheet, errLine } from '../../kit.js'

const PURPOSES = [
  'Introduce KWD and the 90% subsidy scheme',
  'Product demo for President / Secretary',
  'Collect proposal / annual plan status',
  'Follow up on DPC approval',
  'Collect work order',
  'Plan supply and beneficiary list',
]
const STATE_LABEL = { planned: 'Planned', done: 'Visited', missed: 'Missed', cancelled: 'Cancelled' }

function addSheet(S) {
  const s = S.q.trim().toLowerCase()
  const tsoName = (S.team.find((t) => t.id === S.tso) || {}).full_name
  const list = (S.lsgds || [])
    .filter((l) => !s || l.name.toLowerCase().includes(s) || l.districts.name.toLowerCase().includes(s))
    .map((l) => ({ ...l, mine: l.assigned_tso === S.tso, opp: l.opportunities.find((o) => o.financial_year === financialYear()), last: l.visits.map((v) => v.check_in_at).sort().at(-1) }))
    .sort((a, b) => b.mine - a.mine || a.name.localeCompare(b.name))
  return Sheet({
    title: `Plan visits · ${new Date(S.adding + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })}`, close: 'closeAdd',
    body: html`<p class="muted small">For <b>${tsoName}</b>. LSGDs assigned to this TSO are listed first.</p>
      <input placeholder="Search LSGD or district" data-bind="q" data-live value="${S.q}">
      ${!S.lsgds ? Loading() : html`<ul class="checks pick">${list.map((l) => html`<li data-key="${l.id}"><label class="check">
        <input type="checkbox" data-change="togglePick" data-id="${l.id}" ${S.picked.includes(l.id) ? raw('checked') : ''}>
        <span><b>${l.name}</b> <span class="muted small">${LSGD_TYPES[l.type]} · ${l.districts.name}</span>
          <span class="small muted" style="display:block">${l.opp ? stageLabel(l.opp.stage) : 'No deal yet'} · ${l.last ? `last visit ${fmtDate(l.last)}` : 'never visited'}
            ${l.mine ? html`<span class="pill brand tiny">assigned</span>` : ''}</span></span></label></li>`)}</ul>`}
      <div class="field-label">Purpose</div>
      <div class="chips">${PURPOSES.map((p) => html`<button class="chip${S.purpose === p ? ' on' : ''}" data-act="purpose" data-p="${p}">${p}</button>`)}</div>
      <label>Or write your own<input data-bind="purpose" data-live value="${S.purpose}"></label>
      ${errLine(S.aerr)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="saveAdd">${S.busy ? 'Saving…' : `Plan ${S.picked.length || ''} visit${S.picked.length === 1 ? '' : 's'}`}</button>`,
  })
}

function taskSheet(S, today) {
  const t = S.open
  const st = taskState(t, today)
  return Sheet({ title: t.lsgds.name, close: 'closeTask', body: html`
    <p class="muted">${LSGD_TYPES[t.lsgds.type]} · ${t.lsgds.districts.name}</p>
    <div class="kv"><div><span>TSO</span><b>${t.tso && t.tso.full_name}</b></div><div><span>Date</span><b>${fmtDate(t.planned_date)}</b></div><div><span>Status</span><b>${STATE_LABEL[st]}</b></div></div>
    <p><b>Purpose:</b> ${t.purpose}</p>
    ${S.terr ? html`<p class="error">${S.terr}</p>` : ''}
    <div class="row wrap">
      <button class="btn" data-act="openLsgd">Open LSGD</button>
      ${t.status === 'planned' && t.planned_date >= today ? html`<button class="btn danger" ${S.busy ? raw('disabled') : ''} data-act="setStatus" data-status="cancelled">Cancel this visit</button>` : ''}
      ${st === 'missed' ? html`<button class="btn danger" ${S.busy ? raw('disabled') : ''} data-act="setStatus" data-status="missed">Confirm as missed</button>` : ''}
    </div>` })
}

export default {
  state: () => ({ team: null, wk: weekStart(istDate()), tso: '', tasks: null, err: '', adding: null, open: null,
    lsgds: null, q: '', picked: [], purpose: PURPOSES[0], aerr: '', terr: '', busy: false }),
  async init() {
    const { team } = await loadTeam(this.ctx.profile)
    this.set({ team, tso: team.length ? team[0].id : '' })
    if (team.length) await this.actions.load.call(this)
  },
  view(S) {
    const today = istDate()
    if (!S.team) return Loading('Loading your team…')
    const days = Array.from({ length: 7 }, (_, i) => addDays(S.wk, i))
    return html`${PageHead({ label: 'Visit planning', title: 'Plan the week', sub: 'Assign LSGD visits to each TSO. A planned visit turns green when the TSO checks in there that day.' })}
      ${S.team.length === 0 ? Empty('No TSOs report to you yet.') : html`
        <div class="toolbar">
          <select data-bind="tso" data-change="reload" aria-label="TSO">
            ${S.team.map((t) => html`<option value="${t.id}" ${S.tso === t.id ? raw('selected') : ''}>${t.full_name || t.email}</option>`)}
            <option value="all" ${S.tso === 'all' ? raw('selected') : ''}>Whole team</option>
          </select>
          <div class="row">
            <button class="icon-btn" data-act="week" data-n="-7" aria-label="Previous week">${Icon('left')}</button>
            <b>${fmtDate(S.wk)} – ${fmtDate(addDays(S.wk, 6))}</b>
            <button class="icon-btn" data-act="week" data-n="7" aria-label="Next week">${Icon('right')}</button>
            ${S.wk !== weekStart(today) ? html`<button class="btn sm" data-act="thisWeek">This week</button>` : ''}
          </div>
        </div>
        ${S.err ? html`<p class="error">${S.err}</p>` : ''}
        ${!S.tasks ? Loading('Loading plan…') : html`<div class="week">${days.map((d) => html`<div class="day${d === today ? ' today' : ''}">
          <div class="day-head"><span>${new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short' })}</span><span class="muted">${fmtDate(d)}</span></div>
          <div class="day-body">${S.tasks.filter((t) => t.planned_date === d).map((t) => {
            const st = taskState(t, today)
            return html`<button class="task ${st}" data-act="openTask" data-id="${t.id}" style="text-align:left;border:0;cursor:pointer;font:inherit;color:inherit">
              <b>${t.lsgds.name}</b>${S.tso === 'all' ? html`<span class="muted">${t.tso && t.tso.full_name} · </span>` : ''}<span class="muted">${STATE_LABEL[st]}</span></button>`
          })}</div>
          ${d >= today && S.tso !== 'all' ? html`<button class="btn sm day-add" data-act="add" data-d="${d}">${Icon('plus', 16)} Add</button>` : ''}
        </div>`)}</div>`}
        <p class="muted small">Choose one TSO to add visits. Past days can't be planned.</p>`}
      ${S.adding ? addSheet(S) : ''}${S.open ? taskSheet(S, today) : ''}`
  },
  actions: {
    reload() { this.set({ tasks: null }); this.actions.load.call(this) },
    week(el) { this.set({ wk: addDays(this.S.wk, Number(el.dataset.n)), tasks: null }); this.actions.load.call(this) },
    thisWeek() { this.set({ wk: weekStart(istDate()), tasks: null }); this.actions.load.call(this) },
    async load() {
      const S = this.S
      let q = supabase.from('tasks').select('*, lsgds(id, name, type, districts(name)), tso:profiles!tasks_assigned_to_fkey(full_name)')
        .gte('planned_date', S.wk).lte('planned_date', addDays(S.wk, 6)).order('created_at')
      if (S.tso !== 'all') q = q.eq('assigned_to', S.tso)
      const { data, error } = await q
      if (error) return this.set({ err: errText(error) })
      this.set({ tasks: data })
    },
    openTask(el) { this.set({ open: this.S.tasks.find((t) => t.id === el.dataset.id), terr: '' }) },
    closeTask() { this.set({ open: null }) },
    openLsgd() { this.ctx.go('lsgd', { lsgdId: this.S.open.lsgd_id, back: 'plan' }) },
    async setStatus(el) {
      const status = el.dataset.status
      this.set({ busy: true })
      const { error } = await supabase.from('tasks').update({ status }).eq('id', this.S.open.id)
      this.set({ busy: false })
      if (error) return this.set({ terr: errText(error) })
      toast(status === 'cancelled' ? 'Visit cancelled' : 'Marked as missed', 'bad')
      this.set({ open: null })
      await this.actions.load.call(this)
    },
    async add(el) {
      this.set({ adding: el.dataset.d, q: '', picked: [], purpose: PURPOSES[0], aerr: '' })
      if (!this.S.lsgds) {
        const { data, error } = await supabase.from('lsgds').select('id, name, type, assigned_tso, districts(name), opportunities(stage, financial_year), visits(check_in_at)').order('name')
        if (error) this.set({ aerr: errText(error) }); else this.set({ lsgds: data })
      }
    },
    closeAdd() { this.set({ adding: null }) },
    togglePick(el) { const id = el.dataset.id; this.set({ picked: el.checked ? [...this.S.picked, id] : this.S.picked.filter((x) => x !== id) }) },
    purpose(el) { this.set({ purpose: el.dataset.p }) },
    async saveAdd() {
      const S = this.S
      if (!S.picked.length) return this.set({ aerr: 'Pick at least one LSGD.' })
      if (!S.purpose.trim()) return this.set({ aerr: 'Write the purpose of the visit.' })
      this.set({ busy: true, aerr: '' })
      const { error } = await supabase.from('tasks').insert(S.picked.map((lsgd_id) => ({ lsgd_id, assigned_to: S.tso, planned_date: S.adding, purpose: S.purpose.trim() })))
      this.set({ busy: false })
      if (error) return this.set({ aerr: errText(error) })
      toast(`${S.picked.length} visit${S.picked.length > 1 ? 's' : ''} planned`)
      this.set({ adding: null })
      await this.actions.load.call(this)
    },
  },
}
