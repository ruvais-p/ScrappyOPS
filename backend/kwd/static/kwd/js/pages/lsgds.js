import { html, raw, supabase, errText } from '../core.js'
import { Loading, Icon, PageHead, Empty, StageMeter, typeShort } from '../ui.js'
import { LSGD_TYPES, stageLabel, financialYear, fmtDate, fmtINR } from '../lib.js'
import { visitWidget, VisitList } from './visits.js'
import { followupWidget, FollowupList } from './followups.js'

const WON = ['work_order', 'supplied', 'payment_received']

// the LSGDs of my territory
export default {
  state: { rows: null, q: '', show: 'all', err: '' },
  async init() {
    const { data, error } = await supabase.from('lsgds')
      .select('id, name, type, assigned_tso, districts(name), opportunities(stage, expected_units, financial_year), visits(check_in_at)').order('name')
    if (error) return this.set({ err: errText(error) })
    this.set({ rows: data })
  },
  view(S) {
    const fy = financialYear()
    const s = S.q.trim().toLowerCase()
    const list = (S.rows || [])
      .filter((l) => !s || l.name.toLowerCase().includes(s) || l.districts.name.toLowerCase().includes(s))
      .map((l) => ({ ...l, opp: l.opportunities.find((o) => o.financial_year === fy), last: l.visits.map((v) => v.check_in_at).sort().at(-1) }))
      .filter((l) => S.show === 'all' || (S.show === 'never' ? !l.last : S.show === 'won' ? WON.includes(l.opp && l.opp.stage) : l.opp && !['lost', ...WON].includes(l.opp.stage)))
    return html`${PageHead({ label: 'Your territory', title: 'LSGDs', sub: S.rows ? `${S.rows.length} LSGDs in your districts` : null })}
      <div class="search">${Icon('search', 18)}<input placeholder="Search LSGD or district" data-bind="q" data-live value="${S.q}"></div>
      <div class="chips" style="margin:10px 0">${[['all', 'All'], ['never', 'Never visited'], ['open', 'In progress'], ['won', 'Ordered']].map(([k, l]) =>
        html`<button class="chip${S.show === k ? ' on' : ''}" data-act="filter" data-k="${k}">${l}</button>`)}</div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading() : list.length === 0 ? Empty('No LSGDs match.') : html`<ul class="list">${list.map((l) => html`<li data-key="${l.id}">
        <button class="item" data-act="open" data-id="${l.id}">
          <span class="lsgd-mark">${typeShort(l.type)}</span>
          <div class="grow">
            <div class="title">${l.name}</div>
            <div class="muted small">${l.districts.name} · ${l.last ? `visited ${fmtDate(l.last)}` : html`<span class="text-warn">never visited</span>`}</div>
            ${l.opp ? StageMeter(l.opp.stage) : ''}
          </div>
          <span class="pill ${l.opp ? 'stage-' + l.opp.stage : ''}">${l.opp ? stageLabel(l.opp.stage) : 'No deal'}</span>
        </button></li>`)}</ul>`}`
  },
  actions: {
    filter(el) { this.set({ show: el.dataset.k }) },
    open(el) { this.ctx.go('lsgd', { lsgdId: el.dataset.id }) },
  },
}

export const detail = {
  state: { d: null, err: '' },
  widgets: { followup: followupWidget, visit: visitWidget },
  async init() { await this.actions.reload.call(this) },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.d) return Loading()
    const d = S.d
    const opp = d.opps.find((o) => o.financial_year === financialYear())
    return html`<button class="link" data-act="back">← Back</button>
      <h1>${d.lsgd.name}</h1>
      <p class="muted">${LSGD_TYPES[d.lsgd.type]} · ${d.lsgd.districts.name}
        ${d.lsgd.office_lat != null ? html` · <a href="https://maps.google.com/?q=${d.lsgd.office_lat},${d.lsgd.office_lng}" target="_blank" rel="noreferrer">Office on map</a>` : ''}
      </p>
      <button class="btn primary block" data-act="visit">Start visit here</button>

      <section class="card">
        <h2>Deal ${financialYear()}</h2>
        ${opp ? html`<div class="kv">
          <div><span>Stage</span><b>${stageLabel(opp.stage)}</b></div>
          <div><span>Units</span><b>${opp.expected_units}</b></div>
          <div><span>Value</span><b>${fmtINR(opp.expected_value)}</b></div>
          <div><span>Chance</span><b>${opp.probability}%</b></div>
          ${opp.expected_close ? html`<div><span>Expected</span><b>${new Date(opp.expected_close).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</b></div>` : ''}
        </div>` : html`<p class="muted">No deal yet. It is created when you log a visit.</p>`}
      </section>

      <section class="card">
        <h2>Contacts</h2>
        ${d.contacts.length === 0 ? html`<p class="muted">No contacts yet.</p>` : html`<ul class="list">${d.contacts.map((c) => html`<li class="item">
          <div class="grow">
            <div class="title">${c.name} ${c.is_decision_maker ? html`<span class="pill tiny">decision maker</span>` : ''}${c.verified_at ? html`<span class="pill ok tiny">verified</span>` : ''}</div>
            <div class="muted small">${c.designation}${c.phone ? ` · ${c.phone}` : ''}</div>
          </div>
          ${c.phone ? html`<a class="btn" href="tel:${c.phone}">Call</a>` : ''}
        </li>`)}</ul>`}
      </section>

      ${d.fus.length > 0 ? html`<section class="card"><h2>Open follow-ups</h2>${FollowupList(this, d.fus)}</section>` : ''}

      <section class="card">
        <h2>Visit history</h2>
        ${d.visits.length === 0 ? html`<p class="muted">Never visited.</p>` : VisitList(this, d.visits)}
      </section>`
  },
  actions: {
    back() { this.ctx.go(this.ctx.route.back || (this.ctx.kind === 'field' ? 'lsgds' : 'zlsgds')) },
    visit() { this.ctx.go('visit', { lsgdId: this.ctx.route.lsgdId }) },
    async reload() {
      const id = this.ctx.route.lsgdId
      const [l, c, o, v, f] = await Promise.all([
        supabase.from('lsgds').select('*, districts(name)').eq('id', id).single(),
        supabase.from('contacts').select('*').eq('lsgd_id', id).order('created_at'),
        supabase.from('opportunities').select('*').eq('lsgd_id', id).order('financial_year', { ascending: false }),
        supabase.from('visits').select('*, lsgds(name, districts(name)), visit_contacts(contacts(name, designation))').eq('lsgd_id', id).order('check_in_at', { ascending: false }).limit(20),
        supabase.from('followups').select('*, lsgds(name), contacts(name, designation, phone)').eq('lsgd_id', id).is('done_at', null).order('due_on'),
      ])
      const e = l.error || c.error || o.error || v.error || f.error
      if (e) return this.set({ err: errText(e) })
      this.set({ d: { lsgd: l.data, contacts: c.data, opps: o.data, visits: v.data, fus: f.data } })
    },
  },
}
