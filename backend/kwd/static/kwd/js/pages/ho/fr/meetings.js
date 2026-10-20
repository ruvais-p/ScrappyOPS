/* Head Office: the presentation appointments franchisees have booked and how they went. */
import { html, raw, supabase, errText } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../../ui.js'
import { Sheet } from '../../../kit.js'
import { signedUrl, mapLink } from '../../../expenses.js'
import { VENUES, OUTCOMES, fmtWhen, monthStart } from '../../../fr.js'
import { PresPills } from '../../fr/meetings.js'

function detail(S, ctx) {
  const { frs, byId, districts } = ctx.data, p = S.open
  const fname = (id) => (frs.find((f) => f.id === id) || {}).business_name || '—'
  const dName = (id) => (districts.find((d) => d.id === id) || {}).name
  return Sheet({ title: p.venue_name, close: 'closeOpen', body: html`
    ${PresPills(p)}
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Franchisee</span><span>${fname(p.franchise_id)}</span></div>
      <div class="summary-row"><span>When</span><span>${fmtWhen(p.scheduled_at)}</span></div>
      <div class="summary-row"><span>Where</span><span>${[p.lsgd_name, dName(p.district_id), p.address].filter(Boolean).join(', ') || '—'}</span></div>
      <div class="summary-row"><span>Contact</span><span>${[p.contact_person, p.phone].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Presenting</span><span>${(p.product_ids || []).map((i) => byId[i] && byId[i].name).filter(Boolean).join(', ') || '—'}</span></div>
      ${p.purpose ? html`<div class="summary-row"><span>Purpose</span><span>${p.purpose}</span></div>` : ''}
      ${p.expected_attendees != null ? html`<div class="summary-row"><span>Expected</span><span>${p.expected_attendees}</span></div>` : ''}
      ${p.status === 'done' ? html`<div class="summary-row"><span>Attended</span><span>${p.actual_attendees}</span></div>
        <div class="summary-row"><span>Outcome</span><span>${OUTCOMES[p.outcome]}</span></div>
        ${p.notes ? html`<div class="summary-row"><span>Notes</span><span>${p.notes}</span></div>` : ''}
        <div class="summary-row"><span>Marked done</span><span>${fmtWhen(p.done_at)}</span></div>` : ''}
      ${p.status === 'cancelled' ? html`<div class="summary-row"><span>Cancelled because</span><span>${p.cancel_reason}</span></div>` : ''}
      ${p.reschedule_count > 0 ? html`<div class="summary-row"><span>Date changed</span><span>${p.reschedule_count} time${p.reschedule_count === 1 ? '' : 's'}</span></div>` : ''}
    </div>
    ${p.done_lat != null ? html`<a class="btn sm" href="${mapLink(p.done_lat, p.done_lng)}" target="_blank" rel="noreferrer">${Icon('pin', 16)} Where it was marked done</a>` : ''}
    ${S.photo ? html`<a href="${S.photo}" target="_blank" rel="noreferrer"><img src="${S.photo}" alt="Presentation" style="max-width:100%;border-radius:10px;margin-top:12px"></a>` : ''}` })
}

export default {
  state: { rows: null, err: '', fid: '', vt: '', st: '', open: null, photo: '' },
  async init() {
    const { data, error } = await supabase.from('fr_presentations').select('*').order('scheduled_at', { ascending: false })
    if (error) return this.set({ err: errText(error) })
    this.set({ rows: data })
  },
  view(S, ctx) {
    const { frs, districts } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading presentations…')
    const fname = (id) => (frs.find((f) => f.id === id) || {}).business_name || '—'
    const dName = (id) => (districts.find((d) => d.id === id) || {}).name
    const list = S.rows.filter((p) => (!S.fid || p.franchise_id === S.fid) && (!S.vt || p.venue_type === S.vt)
      && (!S.st || (S.st === 'late' ? p.status === 'scheduled' && new Date(p.scheduled_at) < new Date(Date.now() - 24 * 36e5) : p.status === S.st)))
    const scoped = S.rows.filter((p) => !S.fid || p.franchise_id === S.fid)
    const done = scoped.filter((p) => p.status === 'done'), month = monthStart()
    const att = done.reduce((a, p) => a + (p.actual_attendees || 0), 0)
    const orders = done.filter((p) => p.outcome === 'order_received').length
    const upcoming = scoped.filter((p) => p.status === 'scheduled' && new Date(p.scheduled_at) >= new Date())
    return html`${PageHead({ label: 'Franchise', title: 'Presentations', sub: 'Appointments franchisees have booked, where they are held, and how they went.' })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Coming up', value: upcoming.length, sub: 'booked from today' })}
        ${Stat({ label: 'Held this month', value: done.filter((p) => p.scheduled_at >= month).length, sub: `${done.length} in total` })}
        ${Stat({ label: 'People reached', value: att, sub: done.length ? `${Math.round(att / done.length)} per presentation` : '' })}
        ${Stat({ label: 'Led to an order', value: orders, tone: 'ok', sub: done.length ? `${Math.round((100 * orders) / done.length)}% of those held` : '' })}
      </div>
      <div class="toolbar">
        <select data-bind="fid" data-live aria-label="Franchisee"><option value="">All franchisees</option>${frs.map((f) => html`<option value="${f.id}" ${S.fid === f.id ? raw('selected') : ''}>${f.business_name}</option>`)}</select>
        <select data-bind="vt" data-live aria-label="Where"><option value="">Anywhere</option>${Object.entries(VENUES).map(([k, v]) => html`<option value="${k}" ${S.vt === k ? raw('selected') : ''}>${v}</option>`)}</select>
        <select data-bind="st" data-live aria-label="Status"><option value="">Any status</option>
          ${[['scheduled', 'Booked'], ['done', 'Held'], ['cancelled', 'Cancelled'], ['late', 'No outcome after a day']].map(([k, l]) => html`<option value="${k}" ${S.st === k ? raw('selected') : ''}>${l}</option>`)}</select>
      </div>
      ${list.length === 0 ? Empty('No presentations match.') : html`<div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Franchisee</th><th>Where</th><th>Contact</th><th class="num">People</th><th>Result</th></tr></thead>
        <tbody>${list.map((p) => html`<tr data-act="open" data-id="${p.id}" style="cursor:pointer">
          <td>${fmtWhen(p.scheduled_at)}</td><td>${fname(p.franchise_id)}</td>
          <td style="white-space:normal;max-width:260px"><b>${p.venue_name}</b><div class="muted small">${[p.lsgd_name, dName(p.district_id), p.address].filter(Boolean).join(', ')}</div></td>
          <td>${p.contact_person || '—'}${p.phone ? html`<div class="muted small">${p.phone}</div>` : ''}</td>
          <td class="num">${p.actual_attendees ?? p.expected_attendees ?? '—'}</td>
          <td style="white-space:normal">${PresPills(p)}</td></tr>`)}</tbody></table></div>`}
      ${S.open ? detail(S, ctx) : ''}`
  },
  actions: {
    open(el) {
      const p = this.S.rows.find((r) => r.id === el.dataset.id)
      this.set({ open: p, photo: '' })
      if (p.done_photo) signedUrl(p.done_photo).then((u) => this.set({ photo: u }))
    },
    closeOpen() { this.set({ open: null }) },
  },
}
