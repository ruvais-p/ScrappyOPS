/* Head Office: schedule and complete B2B, B2C and B2G meetings. */
import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../../ui.js'
import { Sheet } from '../../../kit.js'
import { fmtWhen } from '../../../fr.js'

const TYPES = { B2B: 'B2B', B2C: 'B2C', B2G: 'B2G' }

function localDateTime() {
  const d = new Date(), pad = (n) => String(n).padStart(2, '0')
  return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` }
}

function scheduleSheet(S) {
  return Sheet({ title: 'Schedule a meeting', close: 'closeSchedule', body: html`
    <label>Scheduled date<input type="date" data-bind="form.date" value="${S.form.date}" required></label>
    <label>Scheduled time<input type="time" data-bind="form.time" value="${S.form.time}" required></label>
    <label>Meeting type<select data-bind="form.meeting_type">${Object.entries(TYPES).map(([k, v]) => html`<option value="${k}" ${S.form.meeting_type === k ? raw('selected') : ''}>${v}</option>`)}</select></label>
    <label>Description<textarea rows="4" data-bind="form.description" placeholder="Meeting agenda or details" required>${S.form.description}</textarea></label>
    ${S.formErr ? html`<p class="error">${S.formErr}</p>` : ''}
    <button class="btn primary block" data-act="saveSchedule" ${S.busy ? raw('disabled') : ''}>${S.busy ? 'Saving…' : 'Create schedule'}</button>` })
}

export default {
  state: { rows: null, err: '', status: '', showSchedule: false, busy: false, formErr: '', form: { ...localDateTime(), meeting_type: 'B2B', description: '' } },
  async init() { await this.actions.load.call(this) },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading meetings…')
    const pending = S.rows.filter((m) => m.status === 'scheduled')
    const complete = S.rows.filter((m) => m.status === 'completed')
    const visible = S.rows.filter((m) => !S.status || m.status === S.status)
    return html`${PageHead({ label: 'Set up', title: 'Meetings', sub: 'Schedule B2B, B2C and B2G meetings, then mark them complete when they are over.', actions: html`<button class="btn primary" data-act="openSchedule">${Icon('plus', 18)} Create schedule</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Scheduled', value: pending.length, sub: 'awaiting completion' })}
        ${Stat({ label: 'Completed', value: complete.length, sub: 'meetings held' })}
        ${Stat({ label: 'Total meetings', value: S.rows.length, sub: 'all schedules' })}
      </div>
      <div class="toolbar"><select data-bind="status" data-live aria-label="Meeting status">
        <option value="">All meetings</option><option value="scheduled" ${S.status === 'scheduled' ? raw('selected') : ''}>Scheduled</option><option value="completed" ${S.status === 'completed' ? raw('selected') : ''}>Completed</option>
      </select></div>
      ${visible.length === 0 ? Empty('No meetings scheduled yet.', { action: html`<button class="btn" data-act="openSchedule">Create a schedule</button>` }) : html`<div class="table-wrap"><table>
        <thead><tr><th>Scheduled date & time</th><th>Type</th><th>Description</th><th>Status</th><th></th></tr></thead>
        <tbody>${visible.map((m) => html`<tr>
          <td>${fmtWhen(m.scheduled_at)}</td><td><b>${TYPES[m.meeting_type] || m.meeting_type}</b></td>
          <td style="white-space:normal;min-width:220px">${m.description}</td>
          <td>${m.status === 'completed' ? html`<span class="pill ok">Completed</span>` : html`<span class="pill warn">Scheduled</span>`}</td>
          <td>${m.status === 'scheduled' ? html`<button class="btn sm" data-act="complete" data-id="${m.id}">Complete</button>` : ''}</td>
        </tr>`)}</tbody></table></div>`}
      ${S.showSchedule ? scheduleSheet(S) : ''}`
  },
  actions: {
    openSchedule() {
      this.set({ showSchedule: true, formErr: '', form: { ...localDateTime(), meeting_type: 'B2B', description: '' } })
    },
    closeSchedule() { this.set({ showSchedule: false, formErr: '' }) },
    async saveSchedule() {
      const f = this.S.form
      if (!f.date || !f.time) return this.set({ formErr: 'Choose the meeting date and time.' })
      if (f.description.trim().length < 2) return this.set({ formErr: 'Enter a description for the meeting.' })
      const scheduledAt = new Date(`${f.date}T${f.time}`)
      if (Number.isNaN(scheduledAt.getTime())) return this.set({ formErr: 'Choose a valid date and time.' })
      this.set({ busy: true, formErr: '' })
      const { error } = await supabase.from('fr_meetings').insert({
        scheduled_at: scheduledAt.toISOString(), meeting_type: f.meeting_type, description: f.description.trim(),
      })
      if (error) return this.set({ busy: false, formErr: errText(error) })
      this.set({ showSchedule: false, busy: false })
      toast('Meeting scheduled')
      await this.actions.load.call(this)
    },
    async complete(el) {
      const { error } = await supabase.from('fr_meetings').update({ status: 'completed' }).eq('id', el.dataset.id)
      if (error) return toast(errText(error), 'bad')
      toast('Meeting marked complete')
      await this.actions.load.call(this)
    },
    async load() {
      const { data, error } = await supabase.from('fr_meetings').select('*').order('scheduled_at', { ascending: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data, err: '' })
    },
  },
}
