/* "Download Excel" button + options sheet. props: { team?, label?, className? }; team = people the viewer may pick (omit for own report). */
import { html, raw, widget, toast, errText } from '../core.js'
import { Icon } from '../ui.js'
import { istDate, addDays } from '../lib.js'
import { Sheet, errLine } from '../kit.js'

function presets(today) {
  const [y, m] = today.split('-').map(Number)
  const monthStart = today.slice(0, 8) + '01'
  const lastStart = new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 10)
  const fyStart = `${m >= 4 ? y : y - 1}-04-01`
  return [
    ['This month', monthStart, today],
    ['Last month', lastStart, addDays(monthStart, -1)],
    ['Last 30 days', addDays(today, -29), today],
    ['This financial year', fyStart, today],
  ]
}

export const reportWidget = {
  state: () => { const today = istDate(); return { open: false, from: presets(today)[0][1], to: today, who: 'all', busy: false, err: '' } },
  view(S, ctx) {
    const { team, label = 'Download Excel', className = 'btn' } = ctx.props
    const today = istDate()
    const button = html`<button class="${className}" data-act="open">${Icon('download', 18)} ${label}</button>`
    if (!S.open) return button
    const body = html`
      <p class="small muted">One Excel file with sheets for the summary, daily TA/DA register, bills, visits, follow-ups and pipeline.</p>
      <div class="chips">${presets(today).map(([l, f, t]) => html`<button class="chip${S.from === f && S.to === t ? ' on' : ''}" data-act="preset" data-f="${f}" data-t="${t}">${l}</button>`)}</div>
      <div class="grid2">
        <label>From<input type="date" data-bind="from" data-live value="${S.from}" max="${S.to}"></label>
        <label>To<input type="date" data-bind="to" data-live value="${S.to}" max="${today}"></label>
      </div>
      ${team ? html`<label>Staff
        <select data-bind="who"><option value="all" ${S.who === 'all' ? raw('selected') : ''}>Everyone (${team.length})</option>
          ${team.map((t) => html`<option value="${t.id}" ${S.who === t.id ? raw('selected') : ''}>${t.full_name || t.email}</option>`)}</select></label>` : ''}
      ${errLine(S.err)}
      <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="go">${S.busy ? 'Preparing the file…' : 'Download .xlsx'}</button>`
    return html`${button}${Sheet({ title: 'Download work history', body, close: 'close' })}`
  },
  actions: {
    open() { this.set({ open: true, err: '' }) },
    close() { this.set({ open: false }) },
    preset(el) { this.set({ from: el.dataset.f, to: el.dataset.t }) },
    async go() {
      const S = this.S, { team } = this.ctx.props, { profile } = this.ctx
      if (!S.from || !S.to || S.from > S.to) return this.set({ err: 'Pick a valid date range.' })
      this.set({ busy: true, err: '' })
      try {
        const { downloadReport } = await import('../report.js')
        const person = team && team.find((t) => t.id === S.who)
        const staffIds = !team ? [profile.id] : S.who === 'all' ? null : [S.who]
        const r = await downloadReport({
          from: S.from, to: S.to, staffIds, by: profile.full_name,
          title: `Scrappy Innovations · Field work & TA/DA report${!team ? ` · ${profile.full_name}` : person ? ` · ${person.full_name}` : ''}`,
          fileLabel: !team ? profile.full_name : person ? person.full_name : 'team-report',
        })
        toast(`Excel downloaded · ${r.visits} visits, ${r.days} request days`)
        this.set({ open: false })
      } catch (e) { this.set({ err: errText(e) }) } finally { this.set({ busy: false }) }
    },
  },
}

/** Placeholder for the button; the screen needs `widgets: { report: reportWidget }`. */
export const ReportButton = (screen, props = {}) => widget(screen, 'report', 'btn', props, { tag: 'span' })
