/* Planned LSGD visits whose date passed without a visit (last 30 days), and whether they were picked up again. props: { team } */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, SectionHead, Avatar, Icon } from '../../ui.js'
import { istDate, addDays, fmtDate, LSGD_TYPES } from '../../lib.js'
import { Sheet, istStartISO, taskState, errLine } from '../../kit.js'

const DAYS = 30

export default {
  state: { rows: null, err: '', replan: null, showAll: false, tso: '', date: '', purpose: '', busy: false, rerr: '' },
  async init() { await this.actions.reload.call(this) },
  view(S, ctx) {
    const team = ctx.props.team || []
    const name = (id) => (team.find((t) => t.id === id) || {}).full_name || '—'
    const open = S.rows ? S.rows.filter((r) => r.open) : []
    const list = S.showAll ? S.rows || [] : open
    const today = istDate()
    const t = S.replan
    return html`<section>
      ${SectionHead({ title: 'Missed visits', count: open.length, tone: open.length ? 'bad' : '' })}
      ${S.err ? html`<p class="error">${S.err}</p>` : !S.rows ? Loading() : list.length === 0
        ? Empty(S.rows.length ? 'Every missed visit has been visited or planned again.' : `No missed visits in the last ${DAYS} days.`)
        : html`<ul class="list">${list.map((r) => html`<li><div class="item missed-item">
            ${Avatar(name(r.assigned_to), 32)}
            <button class="grow link-plain" data-act="open" data-id="${r.lsgd_id}">
              <div class="title">${r.lsgds.name}</div>
              <div class="muted small">${name(r.assigned_to)} · ${r.lsgds.districts.name} · planned ${fmtDate(r.planned_date)}</div>
              <div class="muted small">${r.purpose}</div>
            </button>
            ${r.visited ? html`<span class="pill ok">Visited ${fmtDate(r.visited)}</span>` : r.next ? html`<span class="pill ok">Planned again ${fmtDate(r.next)}</span>`
              : html`<button class="btn sm" data-act="replan" data-id="${r.id}">${Icon('calendar', 16)} Plan again</button>`}
          </div></li>`)}</ul>`}
      ${S.rows && S.rows.length > open.length ? html`<button class="btn sm" data-act="toggleAll">${S.showAll ? 'Show only ones needing action' : `Also show ${S.rows.length - open.length} already picked up`}</button>` : ''}
      <p class="muted small">Last ${DAYS} days. Missed = the planned date passed with no visit by the TSO.</p>
      ${t ? Sheet({ title: `Plan again · ${t.lsgds.name}`, close: 'closeReplan', body: html`
        <p class="muted small">${LSGD_TYPES[t.lsgds.type]} · ${t.lsgds.districts.name}. Missed on ${fmtDate(t.planned_date)}.</p>
        <label>TSO<select data-bind="tso">${team.map((m) => html`<option value="${m.id}" ${S.tso === m.id ? raw('selected') : ''}>${m.full_name || m.email}</option>`)}</select></label>
        <label>New date<input type="date" min="${today}" data-bind="date" value="${S.date}"></label>
        <label>Purpose<input data-bind="purpose" value="${S.purpose}"></label>
        ${errLine(S.rerr)}
        <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : 'Plan visit'}</button>` }) : ''}
    </section>`
  },
  actions: {
    open(el) { const p = this.ctx.route.page; this.ctx.go('lsgd', { lsgdId: el.dataset.id, back: p }) },
    toggleAll() { this.set({ showAll: !this.S.showAll }) },
    replan(el) {
      const t = this.S.rows.find((r) => r.id === el.dataset.id)
      this.set({ replan: t, tso: t.assigned_to, date: addDays(istDate(), 1), purpose: t.purpose, rerr: '' })
    },
    closeReplan() { this.set({ replan: null }) },
    async save() {
      const S = this.S, t = S.replan, today = istDate()
      if (!S.date || S.date < today) return this.set({ rerr: 'Pick today or a later date.' })
      if (!S.purpose.trim()) return this.set({ rerr: 'Write the purpose of the visit.' })
      this.set({ busy: true, rerr: '' })
      const ins = await supabase.from('tasks').insert({ lsgd_id: t.lsgd_id, assigned_to: S.tso, planned_date: S.date, purpose: S.purpose.trim() })
      // the old one stays on record as missed
      const upd = !ins.error && t.status === 'planned' ? await supabase.from('tasks').update({ status: 'missed' }).eq('id', t.id) : {}
      this.set({ busy: false })
      if (ins.error || upd.error) return this.set({ rerr: errText(ins.error || upd.error) })
      toast(`Visit planned for ${fmtDate(S.date)}`)
      this.set({ replan: null })
      await this.actions.reload.call(this)
    },
    async reload() {
      const today = istDate(), from = addDays(today, -DAYS)
      const [t, v] = await Promise.all([
        supabase.from('tasks').select('id, lsgd_id, assigned_to, planned_date, status, purpose, lsgds(name, type, districts(name))').gte('planned_date', from).order('planned_date', { ascending: false }),
        supabase.from('visits').select('lsgd_id, check_in_at').gte('check_in_at', istStartISO(from)),
      ])
      const e = t.error || v.error
      if (e) return this.set({ err: errText(e) })
      const missed = t.data.filter((x) => x.planned_date >= from && x.planned_date < today && taskState(x, today) === 'missed')
      this.set({
        rows: missed.map((m) => {
          // picked up again: a later visit at the LSGD, or a later visit planned there
          const visited = v.data.filter((x) => x.lsgd_id === m.lsgd_id && x.check_in_at >= istStartISO(addDays(m.planned_date, 1))).map((x) => x.check_in_at).sort()[0]
          const next = t.data.filter((x) => x.id !== m.id && x.lsgd_id === m.lsgd_id && x.planned_date > m.planned_date && x.status === 'planned' && x.planned_date >= today).map((x) => x.planned_date).sort()[0]
          return { ...m, visited, next, open: !visited && !next }
        }).sort((a, b) => b.open - a.open || b.planned_date.localeCompare(a.planned_date)),
      })
    },
  },
}
