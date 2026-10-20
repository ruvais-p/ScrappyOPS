/* Call-back checks: phone the officials TSOs say they met. */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { fmtDate, fmtTime } from '../../lib.js'

const OUTCOME = {
  confirmed: ['Confirmed the meeting', 'ok'],
  denied: ['Denied meeting', 'bad'],
  unreachable: ['Not reachable', ''],
}

// one contact to call. props: { c }
const callItem = {
  state: { remark: '', busy: false, err: '' },
  view(S, ctx) {
    const c = ctx.props.c
    const visits = c.visit_contacts.map((vc) => vc.visits).sort((a, b) => b.check_in_at.localeCompare(a.check_in_at))
    const tries = c.verification_calls.filter((k) => k.outcome === 'unreachable').length
    return html`<div class="row wrap">
        <div class="grow">
          <div class="title">${c.name} <span class="muted small">· ${c.designation}</span></div>
          <div class="muted small">${c.lsgds.name}, ${c.lsgds.districts.name}</div>
          <div class="small">Met by ${[...new Set(visits.map((v) => v.tso && v.tso.full_name))].join(', ')} on ${visits.map((v) => fmtDate(v.check_in_at)).join(', ')}</div>
          ${tries > 0 ? html`<div class="small text-warn">Not reachable ${tries} time${tries > 1 ? 's' : ''} before</div>` : ''}
        </div>
        ${c.phone ? html`<a class="btn" href="tel:${c.phone}">${Icon('phone', 18)} ${c.phone}</a>` : html`<span class="pill warn">No number</span>`}
      </div>
      <input placeholder="Remark (needed if they deny the meeting)" data-bind="remark" value="${S.remark}">
      <div class="row wrap">
        <button class="btn primary sm" ${S.busy ? raw('disabled') : ''} data-act="record" data-o="confirmed">${Icon('check', 16)} Confirmed</button>
        <button class="btn danger sm" ${S.busy ? raw('disabled') : ''} data-act="record" data-o="denied">${Icon('x', 16)} Denied meeting</button>
        <button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="record" data-o="unreachable">Not reachable</button>
      </div>
      ${S.err ? html`<p class="error small">${S.err}</p>` : ''}`
  },
  actions: {
    async record(el) {
      const outcome = el.dataset.o, S = this.S, c = this.ctx.props.c
      const visits = c.visit_contacts.map((vc) => vc.visits).sort((a, b) => b.check_in_at.localeCompare(a.check_in_at))
      if (outcome === 'denied' && !S.remark.trim()) return this.set({ err: 'Write what the official said.' })
      this.set({ busy: true, err: '' })
      try {
        const r1 = await supabase.from('verification_calls').insert({ contact_id: c.id, visit_id: visits[0] && visits[0].id, outcome, remark: S.remark.trim() || null })
        if (r1.error) throw r1.error
        if (outcome === 'confirmed') {
          const r2 = await supabase.from('contacts').update({ verified_at: new Date().toISOString() }).eq('id', c.id)
          if (r2.error) throw r2.error
        }
        if (outcome === 'denied') {
          const ids = visits.filter((v) => v.zm_status !== 'rejected').map((v) => v.id)
          if (ids.length) {
            const r3 = await supabase.from('visits').update({ zm_status: 'flagged', zm_remark: `Call-back: ${c.name} denied this meeting. ${S.remark.trim()}` }).in('id', ids)
            if (r3.error) throw r3.error
          }
        }
        toast({ confirmed: 'Meeting confirmed', denied: 'Meeting denied: visits flagged', unreachable: 'Noted: try again later' }[outcome], outcome === 'denied' ? 'bad' : 'ok')
        const p = this.ctx.parent
        p.actions.reload.call(p)
        if (this.ctx.refreshCounts) this.ctx.refreshCounts()
      } catch (e) { this.set({ err: errText(e), busy: false }) }
    },
  },
}

export default {
  state: { tab: 'todo', todo: null, done: null, shared: [], err: '' },
  widgets: { call: callItem },
  async init() { await this.actions.reload.call(this) },
  view(S) {
    return html`${PageHead({ label: 'Call-back checks', title: 'Confirm the meetings', sub: 'Call the officials TSOs say they met. A denied meeting flags those visits automatically.' })}
      ${S.shared.length > 0 ? html`<div class="notice warn"><b>Same number at more than one LSGD</b>
        <ul style="margin:4px 0 0;padding-left:18px">${S.shared.map((s) => html`<li>${s.phone}: saved as ${s.names.join(', ')} at ${s.lsgds} LSGDs</li>`)}</ul></div>` : ''}
      <div class="toolbar"><div class="seg">
        <button class="${S.tab === 'todo' ? 'on' : ''}" data-act="tab" data-k="todo">To call${S.todo ? ` (${S.todo.length})` : ''}</button>
        <button class="${S.tab === 'done' ? 'on' : ''}" data-act="tab" data-k="done">Call log</button>
      </div></div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${S.tab === 'todo' ? (!S.todo ? Loading('Loading contacts…') : S.todo.length === 0 ? Empty('Everyone met in visits has been called. Good work.')
        : html`<ul class="list">${S.todo.map((c) => widget(this, 'call', c.id, { c }, { tag: 'li', cls: 'item col' }))}</ul>`) : ''}
      ${S.tab === 'done' ? (!S.done ? Loading() : S.done.length === 0 ? Empty('No calls recorded yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Contact</th><th>LSGD</th><th>Result</th><th>Remark</th></tr></thead>
        <tbody>${S.done.map((k) => html`<tr>
          <td>${fmtDate(k.called_at)} ${fmtTime(k.called_at)}</td>
          <td><b>${k.contacts.name}</b><div class="muted small">${k.contacts.designation} · ${k.contacts.phone}</div></td>
          <td>${k.contacts.lsgds.name}</td>
          <td><span class="pill ${OUTCOME[k.outcome][1]}">${OUTCOME[k.outcome][0]}</span></td>
          <td style="white-space:normal">${k.remark}</td></tr>`)}</tbody></table></div>`) : ''}`
  },
  actions: {
    tab(el) { this.set({ tab: el.dataset.k }) },
    async reload() {
      const [c, v, s] = await Promise.all([
        supabase.from('contacts').select(`id, name, designation, phone, lsgd_id, lsgds(name, districts(name)),
          visit_contacts!inner(visits(id, check_in_at, zm_status, tso:profiles!visits_tso_id_fkey(full_name))),
          verification_calls(outcome, called_at, remark)`).is('verified_at', null).order('created_at', { ascending: false }).limit(100),
        supabase.from('verification_calls').select('id, outcome, remark, called_at, contacts(name, designation, phone, lsgds(name))').order('called_at', { ascending: false }).limit(50),
        supabase.from('v_shared_contact_phones').select('*'),
      ])
      const e = c.error || v.error || s.error
      if (e) return this.set({ err: errText(e) })
      // contacts already denied are done; unreachable ones stay in the queue
      this.set({ todo: c.data.filter((x) => !x.verification_calls.some((k) => k.outcome === 'denied')), done: v.data, shared: s.data })
    },
  },
}
