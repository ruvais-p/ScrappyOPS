/* Follow-up: every lead that has a next-call date, already-attended leads sorted hot first, then warm, then cold. */
import { html, supabase, errText, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead, SectionHead } from '../../ui.js'
import { fmtDate, istDate } from '../../lib.js'
import { TC_STATUS, TC_TEMP, KIND_LABEL } from '../../tc.js'
import { leadSheet } from './leads.js'

const GROUPS = [['hot', 'Hot'], ['warm', 'Warm'], ['cold', 'Cold'], ['none', 'Not rated yet']]

export default {
  state: () => ({ rows: null, err: '', open: null }),
  widgets: { lead: leadSheet },
  async init() { await this.actions.load.call(this) },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading your follow-ups…')
    const today = istDate()
    const groups = Object.fromEntries(GROUPS.map(([k]) => [k, S.rows.filter((l) => (l.temperature || 'none') === k)]))
    return html`${PageHead({ label: 'Telecalling', title: 'Follow-up', sub: 'Leads you have already called, with a next call date. Hottest first.' })}
      ${S.rows.length === 0 ? Empty('No follow-ups scheduled. Call a lead and set a next follow-up date.') : GROUPS.map(([k, label]) => {
        const rows = groups[k]
        if (!rows.length) return ''
        return html`${SectionHead({ title: label, count: rows.length })}
          <ul class="list" style="margin-bottom:18px">${rows.map((l) => html`<li data-key="${l.id}">
            <button class="item" data-act="open" data-id="${l.id}">
              <div class="grow">
                <div class="title">${l.customer_name}<span class="pill tiny" style="margin-left:6px">${KIND_LABEL[l.kind]}</span></div>
                <div class="muted small">${[l.place, l.phone].filter(Boolean).join(' · ') || '—'}</div>
                <div class="muted small">Follow-up ${fmtDate(l.next_followup_on)}${l.next_followup_on < today ? html`<span class="text-bad"> · overdue</span>` : ''}</div>
              </div>
              <span class="pill ${(TC_STATUS[l.status] || {}).tone || ''}">${(TC_STATUS[l.status] || {}).label || l.status}</span>
            </button></li>`)}</ul>`
      })}
      ${S.open ? widget(this, 'lead', S.open.id, { lead: S.open }) : ''}`
  },
  actions: {
    open(el) { this.set({ open: this.S.rows.find((l) => l.id === el.dataset.id) }) },
    leadClose() { this.set({ open: null }) },
    async leadChanged() { await this.actions.load.call(this) },
    async load() {
      const { data, error } = await supabase.from('v_tc_followups').select('*').order('temp_rank').order('next_followup_on')
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data })
    },
  },
}
