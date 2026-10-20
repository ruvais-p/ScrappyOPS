/* Visit review: a list of visits and, beside it, the one being checked (photo, distance, people met, what was reported). */
import { html, raw, supabase, errText, toast, widget } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Avatar } from '../../ui.js'
import { fmtDate, fmtTime, FLAG_TEXT, INTEREST, stageLabel, fmtINR, distanceM, GEOFENCE_M, financialYear, LSGD_TYPES } from '../../lib.js'
import { loadTeam, errLine } from '../../kit.js'

const FLAG_HELP = {
  unplanned: 'This visit was not in the plan you made for this TSO today.',
  no_gps: 'The phone sent no GPS position.',
  lsgd_location_missing: 'The LSGD office location is not set, so distance could not be checked.',
  outside_geofence: `Check-in was more than ${GEOFENCE_M} m from the LSGD office.`,
  weak_gps: 'GPS accuracy was worse than 100 m.',
  impossible_travel: 'The distance from the previous check-in is too far for the time between them (over 80 km/h).',
  high_volume_day: 'This TSO checked in more than 8 times today.',
}
const STATUS = { pending: ['Waiting', ''], verified: ['Verified', 'ok'], flagged: ['Flagged', 'warn'], rejected: ['Rejected', 'bad'] }
const SELECT = `*, tso:profiles!visits_tso_id_fkey(full_name),
  lsgds(id, name, type, office_lat, office_lng, districts(name)),
  visit_contacts(contacts(id, name, designation, phone, verified_at))`
const maps = (lat, lng) => `https://maps.google.com/?q=${lat},${lng}`

// the visit open on the right-hand side. props: { v }
const visitReview = {
  state: (ctx) => ({ photo: '', opp: undefined, remark: ctx.props.v.zm_remark || '', busy: false, err: '', office: { lat: ctx.props.v.lsgds.office_lat, lng: ctx.props.v.lsgds.office_lng } }),
  async init() {
    const v = this.ctx.props.v
    // V / F / R decide the open visit
    this.onKey = (e) => {
      if (/input|textarea|select/i.test(e.target.tagName) || e.ctrlKey || e.metaKey) return
      if (e.key === 'v') this.actions.decide.call(this, { dataset: { status: 'verified' } })
      if (e.key === 'f') this.actions.decide.call(this, { dataset: { status: 'flagged' } })
      if (e.key === 'r') this.actions.decide.call(this, { dataset: { status: 'rejected' } })
    }
    window.addEventListener('keydown', this.onKey)
    supabase.storage.from('visit-photos').createSignedUrl(v.photo_path, 900).then(({ data }) => data && this.set({ photo: data.signedUrl }))
    supabase.from('opportunities').select('*').eq('lsgd_id', v.lsgd_id).eq('financial_year', financialYear()).maybeSingle().then(({ data }) => this.set({ opp: data }))
  },
  destroyed() { window.removeEventListener('keydown', this.onKey) },
  view(S, ctx) {
    const v = ctx.props.v, office = S.office
    const liveDist = v.distance_from_office_m ?? (v.check_in_lat != null && office.lat != null ? distanceM(v.check_in_lat, v.check_in_lng, office.lat, office.lng) : null)
    const mins = v.check_out_at ? Math.round((new Date(v.check_out_at) - new Date(v.check_in_at)) / 60000) : null
    const opp = S.opp
    return html`<article class="card accent" style="margin-top:0">
      <div class="row wrap">
        <div class="grow"><h2 style="margin-bottom:2px">${v.lsgds.name}</h2><div class="muted small">${LSGD_TYPES[v.lsgds.type]} · ${v.lsgds.districts.name}</div></div>
        <button class="btn sm" data-act="history">LSGD history</button>
      </div>
      <div class="kv" style="margin:12px 0">
        <div><span>TSO</span><b>${(v.tso && v.tso.full_name) || '—'}</b></div>
        <div><span>Checked in</span><b>${fmtDate(v.check_in_at)}, ${fmtTime(v.check_in_at)}</b></div>
        <div><span>Time spent</span><b>${mins != null ? `${mins} min` : 'No check-out'}</b></div>
        <div><span>From office</span><b class="${liveDist > GEOFENCE_M ? 'text-bad' : ''}">${liveDist != null ? (liveDist >= 1000 ? (liveDist / 1000).toFixed(1) + ' km' : Math.round(liveDist) + ' m') : 'Unknown'}</b></div>
        <div><span>GPS accuracy</span><b>${v.gps_accuracy_m != null ? `±${Math.round(v.gps_accuracy_m)} m` : '—'}</b></div>
      </div>
      ${v.fraud_flags.length > 0 ? html`<div class="notice warn"><b>System flags</b>
        <ul style="margin:4px 0 0;padding-left:18px">${v.fraud_flags.map((f) => html`<li><b>${FLAG_TEXT[f] || f}:</b> ${FLAG_HELP[f] || ''}</li>`)}</ul></div>`
        : html`<div class="notice ok">No system flags. Location and plan check out.</div>`}
      ${S.photo ? html`<a href="${S.photo}" target="_blank" rel="noreferrer"><img class="photo" src="${S.photo}" alt="Check-in photo at ${v.lsgds.name}"></a>` : Loading('Loading photo…')}
      <div class="row wrap small">
        ${v.check_in_lat != null ? html`<a href="${maps(v.check_in_lat, v.check_in_lng)}" target="_blank" rel="noreferrer">${Icon('pin', 16)} Check-in on map</a>` : ''}
        ${office.lat != null ? html`<a href="${maps(office.lat, office.lng)}" target="_blank" rel="noreferrer">${Icon('building', 16)} Office on map</a>` : ''}
      </div>
      ${office.lat == null && v.check_in_lat != null ? html`<div class="notice info">This LSGD has no office location yet.
        ${v.gps_accuracy_m <= 50 ? html` If the photo shows the office board, you can save this check-in as the office location. <button class="btn sm" data-act="useAsOffice">Use as office location</button>`
          : html` This check-in's GPS is too rough (±${Math.round(v.gps_accuracy_m)} m) to use. Set it under LSGDs.`}</div>` : ''}

      <h3 style="margin-top:16px">People met</h3>
      <ul class="list">${v.visit_contacts.map(({ contacts: c }) => html`<li class="item">
        <div class="grow"><div class="title">${c.name} ${c.verified_at ? html`<span class="pill ok tiny">confirmed</span>` : html`<span class="pill tiny">not called yet</span>`}</div>
          <div class="muted small">${c.designation}${c.phone ? ` · ${c.phone}` : ''}</div></div>
        ${c.phone ? html`<a class="btn sm" href="tel:${c.phone}">${Icon('phone', 16)} Call</a>` : ''}</li>`)}</ul>
      ${!v.visit_contacts.some(({ contacts: c }) => c.verified_at) && v.visit_contacts.length > 0 ? html`<p class="small muted">Tip: record the call result under Call-backs. A denied meeting flags this visit automatically.</p>` : ''}

      <h3 style="margin-top:16px">What the TSO reported</h3>
      ${v.details_at ? html`<p>${v.discussion}</p>` : html`<div class="notice warn"><div><b>Details not added yet.</b> The discussion and business details are still to be filled in. You can flag or reject this visit, but you can't verify it until they are added.</div></div>`}
      ${v.details_at && new Date(v.details_at) - new Date(v.check_in_at) > 12 * 36e5 ? html`<p class="small muted">Details were added ${fmtDate(v.details_at)} ${fmtTime(v.details_at)}, after the visit.</p>` : ''}
      ${v.outcome ? html`<p><b>Next step agreed:</b> ${v.outcome}</p>` : ''}
      <p class="small">${v.interest_level ? html`Interest: <b>${INTEREST[v.interest_level - 1]}</b> · ` : ''}${v.next_followup_on ? html`Next follow-up: <b>${fmtDate(v.next_followup_on)}</b>` : ''}</p>
      ${opp ? html`<p class="small">Deal: <b>${stageLabel(opp.stage)}</b> · ${opp.expected_units} units · ${fmtINR(opp.expected_value)} · ${opp.probability}% chance</p>` : ''}

      <label style="margin-top:16px">Your remark ${v.zm_status === 'pending' ? '(needed to flag or reject)' : ''}
        <textarea rows="2" data-bind="remark" placeholder="e.g. Photo does not show the office board">${S.remark}</textarea></label>
      ${errLine(S.err)}
      <div class="row wrap">
        <button class="btn primary" ${S.busy || !v.details_at ? raw('disabled') : ''} data-act="decide" data-status="verified">${Icon('check', 18)} Verify</button>
        <button class="btn" ${S.busy ? raw('disabled') : ''} data-act="decide" data-status="flagged">${Icon('flag', 18)} Flag</button>
        <button class="btn danger" ${S.busy ? raw('disabled') : ''} data-act="decide" data-status="rejected">${Icon('x', 18)} Reject</button>
      </div>
      ${v.zm_reviewed_at ? html`<p class="muted small">Last reviewed ${fmtDate(v.zm_reviewed_at)} ${fmtTime(v.zm_reviewed_at)}. Head Office sees every change.</p>` : ''}
    </article>`
  },
  actions: {
    history() { this.ctx.go('lsgd', { lsgdId: this.ctx.props.v.lsgd_id, back: 'review' }) },
    async decide(el) {
      const S = this.S, v = this.ctx.props.v, status = el.dataset.status
      if (S.busy) return
      if (status === 'verified' && !v.details_at) return this.set({ err: 'The visitor has not filled in the details yet. You can flag the visit, but not verify it.' })
      if (status !== 'verified' && !S.remark.trim()) return this.set({ err: 'Write a remark so the TSO knows why.' })
      this.set({ busy: true, err: '' })
      const { error } = await supabase.from('visits').update({ zm_status: status, zm_remark: S.remark.trim() || null }).eq('id', v.id)
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast({ verified: 'Visit verified', flagged: 'Visit flagged', rejected: 'Visit rejected' }[status], status === 'verified' ? 'ok' : 'bad')
      const p = this.ctx.parent
      p.actions.afterAction.call(p, v.id)
    },
    async useAsOffice() {
      const v = this.ctx.props.v
      if (!confirm(`Set the office location of ${v.lsgds.name} to where this visit was checked in?\n\nOnly do this if the photo clearly shows the LSGD office name board.`)) return
      const { error } = await supabase.from('lsgds').update({ office_lat: v.check_in_lat, office_lng: v.check_in_lng }).eq('id', v.lsgd_id)
      if (error) return this.set({ err: errText(error) })
      this.set({ office: { lat: v.check_in_lat, lng: v.check_in_lng } })
      toast('Office location saved')
    },
  },
}

export default {
  state: (ctx) => ({ team: [], filter: ctx.route.filter || 'pending', tso: '', rows: null, sel: null, err: '' }),
  widgets: { visit: visitReview },
  async init() {
    loadTeam(this.ctx.profile).then((t) => this.set({ team: t.team }))
    await this.actions.load.call(this)
    // J / K move through the list
    this.onKey = (e) => {
      const S = this.S
      if (/input|textarea|select/i.test(e.target.tagName) || !S.rows || !S.rows.length) return
      const i = S.rows.findIndex((r) => r.id === S.sel)
      if (e.key === 'j') this.set({ sel: S.rows[Math.min(S.rows.length - 1, i + 1)].id })
      if (e.key === 'k') this.set({ sel: S.rows[Math.max(0, i - 1)].id })
    }
    window.addEventListener('keydown', this.onKey)
  },
  destroyed() { window.removeEventListener('keydown', this.onKey) },
  view(S) {
    const current = S.rows && S.rows.find((r) => r.id === S.sel)
    return html`${PageHead({ label: 'Visit review', title: 'Check each visit', sub: 'Flagged visits come first. Look at the photo, the distance and who was met before you verify.',
        actions: html`<span class="muted small hide-sm">Shortcuts: <span class="kbd">J</span>/<span class="kbd">K</span> move · <span class="kbd">V</span> verify · <span class="kbd">F</span> flag · <span class="kbd">R</span> reject</span>` })}
      <div class="toolbar">
        <div class="seg" role="tablist">${[['pending', 'Waiting'], ['flagged', 'Flagged by system'], ['reviewed', 'Reviewed (30 days)']].map(([k, l]) =>
          html`<button role="tab" aria-selected="${S.filter === k}" class="${S.filter === k ? 'on' : ''}" data-act="filter" data-k="${k}">${l}</button>`)}</div>
        <select data-bind="tso" data-change="reloadList" aria-label="Filter by TSO">
          <option value="">All TSOs</option>
          ${S.team.map((t) => html`<option value="${t.id}" ${S.tso === t.id ? raw('selected') : ''}>${t.full_name || t.email}</option>`)}
        </select>
      </div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading('Loading visits…') : S.rows.length === 0
        ? Empty(S.filter === 'reviewed' ? 'No reviewed visits in the last 30 days.' : 'Nothing waiting. Every visit has been reviewed.')
        : html`<div class="review-grid">
          <ul class="list" style="align-content:start">${S.rows.map((v) => {
            const [label, tone] = STATUS[v.zm_status]
            return html`<li data-key="${v.id}"><button class="item${v.fraud_flags.length ? ' flagged' : ''}" data-act="pick" data-id="${v.id}" aria-current="${S.sel === v.id}">
              ${Avatar((v.tso && v.tso.full_name) || '?', 32)}
              <div class="grow">
                <div class="title">${v.lsgds.name}</div>
                <div class="muted small">${(v.tso && v.tso.full_name) || '—'} · ${fmtDate(v.check_in_at)} ${fmtTime(v.check_in_at)}</div>
                ${v.fraud_flags.length > 0 ? html`<div class="small text-warn">${v.fraud_flags.length} flag${v.fraud_flags.length > 1 ? 's' : ''}</div>` : ''}
                ${!v.details_at ? html`<div class="small text-warn">Details not added</div>` : ''}
              </div>
              <span class="pill ${tone}">${label}</span></button></li>`
          })}</ul>
          <div data-detail>${current ? widget(this, 'visit', current.id, { v: current }) : ''}</div>
        </div>`}`
  },
  actions: {
    filter(el) { this.set({ filter: el.dataset.k, rows: null }); this.actions.load.call(this) },
    reloadList() { this.set({ rows: null }); this.actions.load.call(this) },
    pick(el) {
      this.set({ sel: el.dataset.id })
      if (window.innerWidth < 760) setTimeout(() => { const d = this.root.querySelector('[data-detail]'); if (d) d.scrollIntoView({ behavior: 'smooth' }) }, 50)
    },
    async load(keepId) {
      const S = this.S, { profile } = this.ctx
      let q = supabase.from('visits').select(SELECT).order('check_in_at', { ascending: S.filter !== 'reviewed' }).limit(100)
      if (S.filter === 'reviewed') q = q.neq('zm_status', 'pending').gte('check_in_at', new Date(Date.now() - 30 * 864e5).toISOString())
      else q = q.eq('zm_status', 'pending')
      if (S.filter === 'flagged') q = q.neq('fraud_flags', '{}')
      if (S.tso) q = q.eq('tso_id', S.tso)
      q = q.neq('tso_id', profile.id) // your own visits are reviewed by Head Office
      const { data, error } = await q
      if (error) return this.set({ err: errText(error) })
      // flagged first while reviewing
      const sorted = S.filter === 'reviewed' ? data : [...data].sort((a, b) => (b.fraud_flags.length > 0) - (a.fraud_flags.length > 0))
      const keep = typeof keepId === 'string' ? keepId : null
      this.set({ rows: sorted, sel: (sorted.find((r) => r.id === keep) || sorted[0] || {}).id || null })
    },
    async afterAction(id) {
      if (this.ctx.refreshCounts) this.ctx.refreshCounts()
      const S = this.S
      const idx = S.rows.findIndex((r) => r.id === id)
      const next = S.filter === 'reviewed' ? id : (S.rows[idx + 1] || S.rows[idx - 1] || {}).id
      await this.actions.load.call(this, next)
    },
  },
}
