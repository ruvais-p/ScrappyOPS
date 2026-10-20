import { html, raw, when, supabase, errText, toast, widget } from '../core.js'
import { Loading, Icon, MODE_ICON, PageHead, SectionHead, Empty } from '../ui.js'
import { istDate, addDays, fmtDate } from '../lib.js'
import { options, errLine } from '../kit.js'

const MODES = [['visit', 'Visit', 'pin'], ['call', 'Call', 'phone'], ['whatsapp', 'WhatsApp', 'message'], ['email', 'Email', 'mail']]
const QUICK = [[2, 'In 2 days'], [7, 'Next week'], [14, 'In 2 weeks'], [30, 'In a month']]

// One follow-up row, with its own "mark done / schedule the next one" form
export const followupWidget = {
  state: (ctx) => ({
    closing: false, note: '', next: true, nextDate: addDays(istDate(), 7), nextMode: ctx.props.f.mode, nextNote: '',
    busy: false, err: '', nextSaved: false, // nextSaved: so a retry never books the next one twice
  }),
  view(S, ctx) {
    const f = ctx.props.f
    const today = istDate()
    const overdue = f.due_on < today, due = f.due_on === today
    const tone = overdue ? 'bad' : due ? 'warn' : 'muted'
    const waLink = f.contacts && f.contacts.phone ? `https://wa.me/91${f.contacts.phone.slice(-10)}` : null
    return html`
      <div class="row">
        <span class="lead-ico ${tone}">${Icon(MODE_ICON[f.mode] || 'followup', 20)}</span>
        <div class="grow">
          <button class="link title" data-act="openLsgd">${f.lsgds && f.lsgds.name}</button>
          <div class="muted small">
            <span class="${overdue ? 'text-bad' : due ? 'text-warn' : ''}">${overdue ? `Overdue · ${fmtDate(f.due_on)}` : due ? 'Due today' : fmtDate(f.due_on)}</span>
            ${' · '}${f.mode}${f.contacts ? html` · ${f.contacts.name}` : ''}
          </div>
          ${f.notes ? html`<div class="small">${f.notes}</div>` : ''}
        </div>
      </div>
      ${!S.closing ? html`<div class="row wrap">
        ${f.contacts && f.contacts.phone ? (f.mode === 'whatsapp' && waLink
          ? html`<a class="btn sm" href="${waLink}" target="_blank" rel="noreferrer">${Icon('message', 16)} WhatsApp</a>`
          : html`<a class="btn sm" href="tel:${f.contacts.phone}">${Icon('phone', 16)} Call</a>`) : ''}
        ${f.mode === 'visit' ? html`<button class="btn sm primary" data-act="visit">${Icon('pin', 16)} Visit</button>` : ''}
        <button class="btn sm" data-act="startClose">${Icon('check', 16)} ${f.mode === 'visit' ? 'Close without visit' : 'Mark done'}</button>
      </div>` : html`<div class="close-form">
        <label>What happened? (required)
          <input data-bind="note" value="${S.note}" placeholder="e.g. Spoke to the Secretary, proposal received">
        </label>
        <div class="field-label">Next follow-up</div>
        <div class="chips" role="radiogroup" aria-label="Next follow-up">
          <button role="radio" aria-checked="${!S.next}" class="chip${!S.next ? ' on' : ''}" data-act="noNext">None</button>
          ${QUICK.map(([n, l]) => html`<button role="radio" aria-checked="${S.next && S.nextDate === addDays(today, n)}" class="chip${S.next && S.nextDate === addDays(today, n) ? ' on' : ''}" data-act="quick" data-n="${n}">${l}</button>`)}
        </div>
        ${S.next ? html`<div class="card next-fu">
          <div class="grid2">
            <label>Date<input type="date" min="${today}" data-bind="nextDate" data-live value="${S.nextDate}"></label>
            <label>How<select data-bind="nextMode">${options(MODES.map(([k, l]) => [k, l]), S.nextMode)}</select></label>
          </div>
          <label>Note (optional)<input data-bind="nextNote" value="${S.nextNote}" placeholder="e.g. Ask about DPC approval"></label>
          <p class="small muted" style="margin:0">With ${(f.contacts && f.contacts.name) || 'anyone at the LSGD'} · ${f.lsgds && f.lsgds.name}</p>
        </div>` : ''}
        <div class="row wrap">
          <button class="btn primary grow" ${S.busy ? raw('disabled') : ''} data-act="markDone">${S.busy ? 'Saving…' : S.next ? `Save and schedule ${fmtDate(S.nextDate)}` : 'Save, no next follow-up'}</button>
          <button class="btn" ${S.busy ? raw('disabled') : ''} data-act="cancel">Cancel</button>
        </div>
      </div>`}
      ${S.err ? html`<p class="error small">${S.err}</p>` : ''}`
  },
  actions: {
    openLsgd() { this.ctx.go('lsgd', { lsgdId: this.ctx.props.f.lsgd_id, back: this.ctx.route && this.ctx.route.page !== 'lsgd' ? this.ctx.route.page : undefined }) },
    visit() { this.ctx.go('visit', { lsgdId: this.ctx.props.f.lsgd_id }) },
    startClose() { this.set({ closing: true }) },
    cancel() { this.set({ closing: false, err: '' }) },
    noNext() { this.set({ next: false }) },
    quick(el) { this.set({ next: true, nextDate: addDays(istDate(), Number(el.dataset.n)) }) },
    async markDone() {
      const S = this.S, f = this.ctx.props.f, today = istDate()
      if (!S.note.trim()) return this.set({ err: 'Write what happened.' })
      if (S.next && (!S.nextDate || S.nextDate < today)) return this.set({ err: 'Pick a date from today onwards for the next follow-up.' })
      this.set({ busy: true, err: '' })
      try {
        if (S.next && !S.nextSaved) {
          const { error } = await supabase.from('followups').insert({
            lsgd_id: f.lsgd_id, opportunity_id: f.opportunity_id, contact_id: f.contact_id,
            due_on: S.nextDate, mode: S.nextMode, notes: S.nextNote.trim() || null,
          })
          if (error) throw error
          S.nextSaved = true
        }
        const { error } = await supabase.from('followups').update({ done_at: new Date().toISOString(), done_note: S.note.trim() }).eq('id', f.id)
        if (error) throw error
        toast(S.next ? `Done. Next follow-up on ${fmtDate(S.nextDate)}` : 'Follow-up closed')
        const p = this.ctx.parent
        if (p && p.actions.reload) p.actions.reload.call(p)
      } catch (e) {
        this.set({ err: errText(e) })
      } finally { this.set({ busy: false }) }
    },
  },
}

/** A list of follow-up rows: <ul class="list"> built from followup widgets. `screen` is the screen that owns the list. */
export const FollowupList = (screen, items) => html`<ul class="list">${items.map((f) => widget(screen, 'followup', f.id, { f }, { tag: 'li', cls: 'item col' }))}</ul>`

const Group = (screen, title, items, tone) => items.length
  ? html`<section>${SectionHead({ title, count: items.length, tone })}${FollowupList(screen, items)}</section>` : ''

export default {
  state: { open: null, done: [], err: '' },
  widgets: { followup: followupWidget },
  async init() { await this.actions.reload.call(this) },
  view(S) {
    const today = istDate()
    const open = S.open
    const overdue = open ? open.filter((f) => f.due_on < today) : []
    const due = open ? open.filter((f) => f.due_on === today) : []
    const upcoming = open ? open.filter((f) => f.due_on > today) : []
    return html`${PageHead({ label: 'Your follow-ups', title: 'Follow-ups', sub: 'Calls, WhatsApps and visits you promised. Overdue ones come first.' })}
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!open ? Loading() : html`
        ${Group(this, 'Overdue', overdue, 'bad')}
        ${Group(this, 'Due today', due, 'warn')}
        ${Group(this, 'Upcoming', upcoming, '')}
        ${open.length === 0 ? Empty('No open follow-ups. You add them at the end of each visit.') : ''}
        ${S.done.length > 0 ? html`<section>
          ${SectionHead({ title: 'Recently completed' })}
          <ul class="list">${S.done.map((f) => html`<li class="item dim"><div class="grow">
            <div class="title">${f.lsgds.name}</div>
            <div class="muted small">${f.mode} · done ${fmtDate(f.done_at)}${f.done_note ? ` · ${f.done_note}` : ''}</div>
          </div></li>`)}</ul>
        </section>` : ''}`}`
  },
  actions: {
    async reload() {
      const { profile } = this.ctx
      const [a, b] = await Promise.all([
        supabase.from('followups').select('*, lsgds(name), contacts(name, designation, phone)').eq('assigned_to', profile.id).is('done_at', null).order('due_on'),
        supabase.from('followups').select('*, lsgds(name)').eq('assigned_to', profile.id).not('done_at', 'is', null).order('done_at', { ascending: false }).limit(20),
      ])
      if (a.error || b.error) return this.set({ err: errText(a.error || b.error) })
      this.set({ open: a.data, done: b.data })
    },
  },
}
