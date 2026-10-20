import { html, raw, supabase, errText, widget } from '../core.js'
import { Loading, PageHead, Empty, Icon } from '../ui.js'
import { fmtDate, fmtTime, FLAG_TEXT, INTEREST } from '../lib.js'

const REVIEW = {
  pending: ['Awaiting ZM review', ''],
  verified: ['Verified by ZM', 'ok'],
  flagged: ['Flagged by ZM', 'warn'],
  rejected: ['Rejected by ZM', 'bad'],
}

// One visit row that opens to show the photo and what was reported
export const visitWidget = {
  state: { open: false, photoUrl: '', busy: false, err: '' },
  view(S, ctx) {
    const { v, mine, showTso } = ctx.props
    // a quick check-in waits for its discussion and business details (3 days)
    const noDetails = !v.details_at && v.zm_status === 'pending'
    const [label, tone] = noDetails ? ['Details needed', 'warn'] : REVIEW[v.zm_status]
    const detailsBy = new Date(new Date(v.check_in_at).getTime() + 3 * 864e5)
    const canAdd = mine && noDetails && detailsBy > new Date()
    const canCheckOut = !v.check_out_at && v.zm_status === 'pending' && Date.now() - new Date(v.check_in_at) < 12 * 36e5
    const mins = v.check_out_at ? Math.round((new Date(v.check_out_at) - new Date(v.check_in_at)) / 60000) : null
    const flags = v.fraud_flags || []
    return html`
      <button class="row link-row" data-act="toggle" aria-expanded="${S.open}">
        <span class="lead-ico ${tone === 'ok' ? 'ok' : tone === 'bad' ? 'bad' : flags.length ? 'warn' : 'muted'}">
          ${Icon(tone === 'ok' ? 'checkCircle' : tone === 'bad' ? 'x' : flags.length ? 'alert' : 'clock', 20)}</span>
        <div class="grow">
          <div class="title">${v.lsgds.name}</div>
          <div class="muted small">
            ${fmtDate(v.check_in_at)} · ${fmtTime(v.check_in_at)}${mins != null ? ` · ${mins} min` : ''}${v.distance_from_office_m != null ? ` · ${Math.round(v.distance_from_office_m)} m from office` : ''}
          </div>
          ${showTso ? html`<div class="small">${v.profiles && v.profiles.full_name}</div>` : ''}
        </div>
        <span class="pill ${tone}">${label}</span>
      </button>
      ${flags.length > 0 ? html`<div class="flags">${flags.map((f) => html`<span class="pill warn tiny">${FLAG_TEXT[f] || f}</span>`)}</div>` : ''}
      ${S.open ? html`<div class="detail">
        ${S.photoUrl ? html`<img class="photo" src="${S.photoUrl}" alt="Photo at ${v.lsgds.name}">` : ''}
        <p><b>Met:</b> ${v.visit_contacts.map((vc) => `${vc.contacts.name} (${vc.contacts.designation})`).join(', ') || '—'}</p>
        ${v.details_at ? html`<p><b>Discussion:</b> ${v.discussion}</p>` : html`<div class="notice warn small"><div>
          <b>Details not added yet.</b>
          ${canAdd ? `Add the discussion and business details by ${fmtDate(detailsBy.toISOString())}.` : noDetails ? 'The 3 days to add details are over. Ask your manager.' : ''}
          ${canAdd ? html`<div style="margin-top:8px"><button class="btn sm primary" data-act="addDetails">Add details now</button></div>` : ''}
        </div></div>`}
        ${v.details_at && new Date(v.details_at) - new Date(v.check_in_at) > 12 * 36e5 ? html`<p class="small muted">Details added ${fmtDate(v.details_at)} ${fmtTime(v.details_at)}, after the visit.</p>` : ''}
        ${v.outcome ? html`<p><b>Outcome:</b> ${v.outcome}</p>` : ''}
        ${v.interest_level ? html`<p><b>Interest:</b> ${INTEREST[v.interest_level - 1]}</p>` : ''}
        ${v.zm_remark ? html`<p><b>ZM remark:</b> ${v.zm_remark}</p>` : ''}
        <button class="link" data-act="openLsgd">Open LSGD →</button>
      </div>` : ''}
      ${canCheckOut ? html`<button class="btn" ${S.busy ? raw('disabled') : ''} data-act="checkOut">Check out (leaving LSGD)</button>` : ''}
      ${S.err ? html`<p class="error small">${S.err}</p>` : ''}`
  },
  actions: {
    async toggle() {
      const open = !this.S.open
      this.set({ open })
      const v = this.ctx.props.v
      if (open && !this.S.photoUrl && v.photo_path) {
        const { data } = await supabase.storage.from('visit-photos').createSignedUrl(v.photo_path, 600)
        if (data) this.set({ photoUrl: data.signedUrl })
      }
    },
    addDetails() { const v = this.ctx.props.v; this.ctx.go('visit', { lsgdId: v.lsgd_id, completeVisit: v.id }) },
    openLsgd() { this.ctx.go('lsgd', { lsgdId: this.ctx.props.v.lsgd_id, back: this.ctx.route && this.ctx.route.page !== 'lsgd' ? this.ctx.route.page : undefined }) },
    async checkOut() {
      this.set({ busy: true })
      const { error } = await supabase.from('visits').update({ check_out_at: new Date().toISOString() }).eq('id', this.ctx.props.v.id)
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      const p = this.ctx.parent
      if (p && p.actions.reload) p.actions.reload.call(p)
    },
  },
}

/** <ul> of visit rows owned by `screen` (which needs `widgets: { visit: visitWidget }` and a `reload` action). */
export const VisitList = (screen, visits, opts = {}) =>
  html`<ul class="list">${visits.map((v) => widget(screen, 'visit', v.id, { v, ...opts }, { tag: 'li', cls: 'item col' }))}</ul>`

export default {
  state: { visits: null, err: '' },
  widgets: { visit: visitWidget },
  async init() { await this.actions.reload.call(this) },
  view(S, ctx) {
    return html`${ctx.props && ctx.props.embedded ? '' : PageHead({ label: 'Last 30 days', title: 'My visits', sub: 'Tap a visit to see the photo and what you reported. Your Zonal Manager reviews each one.' })}
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.visits ? Loading() : S.visits.length === 0
        ? Empty('No visits yet.', { action: html`<button class="btn primary" data-act="log">Log a visit</button>` })
        : VisitList(this, S.visits, { mine: true })}`
  },
  actions: {
    log() { this.ctx.go('visit') },
    async reload() {
      const since = new Date(Date.now() - 30 * 864e5).toISOString()
      const { data, error } = await supabase.from('visits')
        .select('*, lsgds(name, districts(name)), visit_contacts(contacts(name, designation))')
        .eq('tso_id', this.ctx.profile.id).gte('check_in_at', since).order('check_in_at', { ascending: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ visits: data })
    },
  },
}
