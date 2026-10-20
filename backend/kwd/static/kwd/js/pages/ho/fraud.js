/* Head Office: who to look at first (risk score) and the audit trail. */
import { html, raw, supabase, errText, widget } from '../../core.js'
import { Loading, Empty, PageHead, Avatar } from '../../ui.js'
import { fmtDate, fmtTime } from '../../lib.js'

// how much each signal counts towards a TSO's risk score
const WEIGHT = { outside_geofence: 3, impossible_travel: 5, no_gps: 3, weak_gps: 1, unplanned: 1, high_volume_day: 2, rejected: 5, zmFlagged: 2, denied: 8, noCheckout: 0.5 }
const TABLE_LABEL = { visits: 'Visit', contacts: 'Contact', opportunities: 'Deal', tasks: 'Plan', lsgds: 'LSGD', profiles: 'Staff profile', followups: 'Follow-up', staff_admin: 'Login admin' }
const SKIP = new Set(['updated_at', 'created_at'])

const fmtVal = (v) => {
  if (v == null) return '—'
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—'
  if (typeof v === 'object') return '…'
  const s = String(v)
  return s.length > 40 ? s.slice(0, 40) + '…' : s
}

const risk = {
  state: { d: null, err: '' },
  async init() {
    const since = new Date(Date.now() - 30 * 864e5).toISOString()
    const [v, c, p, s] = await Promise.all([
      supabase.from('visits').select('id, tso_id, check_in_at, check_out_at, fraud_flags, zm_status, distance_from_office_m').gte('check_in_at', since),
      supabase.from('verification_calls').select('outcome, visits(tso_id)').gte('called_at', since),
      supabase.from('profiles').select('id, full_name, role, manager_id, is_active'),
      supabase.from('v_shared_contact_phones').select('*'),
    ])
    const e = v.error || c.error || p.error || s.error
    if (e) return this.set({ err: errText(e) })
    this.set({ d: { visits: v.data, calls: c.data, staff: p.data, shared: s.data } })
  },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    const d = S.d
    if (!d) return Loading('Working out risk…')
    const name = (id) => (d.staff.find((s) => s.id === id) || {}).full_name || '—'
    const rows = d.staff.filter((s) => s.role === 'tso').map((t) => {
      const V = d.visits.filter((v) => v.tso_id === t.id)
      const C = d.calls.filter((k) => k.visits && k.visits.tso_id === t.id)
      const count = (f) => V.filter((v) => v.fraud_flags.includes(f)).length
      const r = {
        id: t.id, name: t.full_name, zm: name(t.manager_id), active: t.is_active, visits: V.length,
        outside_geofence: count('outside_geofence'), impossible_travel: count('impossible_travel'),
        no_gps: count('no_gps'), weak_gps: count('weak_gps'), unplanned: count('unplanned'), high_volume_day: count('high_volume_day'),
        rejected: V.filter((v) => v.zm_status === 'rejected').length, zmFlagged: V.filter((v) => v.zm_status === 'flagged').length,
        denied: C.filter((k) => k.outcome === 'denied').length, confirmed: C.filter((k) => k.outcome === 'confirmed').length,
        noCheckout: V.filter((v) => !v.check_out_at).length,
      }
      const done = V.filter((v) => v.check_out_at)
      r.avgMin = done.length ? Math.round(done.reduce((s, v) => s + (new Date(v.check_out_at) - new Date(v.check_in_at)) / 60000, 0) / done.length) : null
      r.score = Object.entries(WEIGHT).reduce((s, [k, w]) => s + (r[k] || 0) * w, 0)
      return r
    }).sort((a, b) => b.score - a.score)
    const n = (x, tone = 'warn') => (x ? html`<span class="pill ${tone}">${x}</span>` : html`<span class="muted">0</span>`)
    return html`${d.shared.length > 0 ? html`<div class="notice warn"><b>Same phone number saved at more than one LSGD</b>
        <ul style="margin:4px 0 0;padding-left:18px">${d.shared.map((s) => html`<li>${s.phone}: ${s.names.join(', ')} (${s.lsgds} LSGDs)</li>`)}</ul></div>` : ''}
      ${rows.length === 0 ? Empty('No TSOs yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>TSO</th><th class="num">Risk</th><th class="num">Visits</th><th class="num">Away from office</th><th class="num">Impossible travel</th><th class="num">No / weak GPS</th><th class="num">Not in plan</th>
          <th class="num">ZM flagged</th><th class="num">ZM rejected</th><th class="num">Meeting denied</th><th class="num">Calls confirmed</th><th class="num">Avg time on site</th></tr></thead>
        <tbody>${rows.map((r) => html`<tr style="${r.active ? '' : 'opacity:.6'}">
          <td><div class="who-cell">${Avatar(r.name, 30)}<div><b>${r.name}</b><div class="muted small">ZM: ${r.zm}</div></div></div></td>
          <td class="num"><span class="pill ${r.score >= 10 ? 'bad' : r.score >= 4 ? 'warn' : 'ok'}">${r.score}</span></td>
          <td class="num">${r.visits}</td><td class="num">${n(r.outside_geofence)}</td><td class="num">${n(r.impossible_travel, 'bad')}</td>
          <td class="num">${n(r.no_gps + r.weak_gps)}</td><td class="num">${n(r.unplanned, '')}</td><td class="num">${n(r.zmFlagged)}</td>
          <td class="num">${n(r.rejected, 'bad')}</td><td class="num">${n(r.denied, 'bad')}</td>
          <td class="num">${r.confirmed || html`<span class="muted">0</span>`}</td>
          <td class="num">${r.avgMin != null ? `${r.avgMin} min` : '—'}${r.noCheckout ? html`<div class="muted small">${r.noCheckout} no check-out</div>` : ''}</td></tr>`)}</tbody></table></div>`}
      <p class="muted small">Risk score adds up the warning signs: a denied meeting counts 8, impossible travel 5, a rejected visit 5, a check-in away from the office or with no GPS 3. Look at the highest scores first; one flag alone can be an honest mistake.</p>`
  },
}

const audit = {
  state: { rows: null, names: {}, table: '', err: '' },
  async init() { await this.actions.load.call(this) },
  view(S) {
    const summary = (r) => {
      const n = r.new_data || {}, o = r.old_data || {}
      if (r.table_name === 'staff_admin') return `${r.action.replace('_', ' ').toLowerCase()}${n.email ? ': ' + n.email : ''}${n.profile && n.profile.role ? ' as ' + n.profile.role : ''}`
      const label = n.name || n.lsgd_name || n.purpose || o.name || ''
      if (r.action === 'INSERT') return `added${label ? ' ' + label : ''}`
      if (r.action === 'DELETE') return `deleted${label ? ' ' + label : ''}`
      const changed = Object.keys(n).filter((k) => !SKIP.has(k) && JSON.stringify(n[k]) !== JSON.stringify(o[k]))
      return changed.length ? changed.map((k) => `${k}: ${fmtVal(o[k])} → ${fmtVal(n[k])}`).join('; ') : 'no visible change'
    }
    return html`<div class="toolbar">
        <select data-bind="table" data-change="load" aria-label="What changed"><option value="">Everything</option>${Object.entries(TABLE_LABEL).map(([k, v]) => html`<option value="${k}" ${S.table === k ? raw('selected') : ''}>${v}</option>`)}</select>
        <span class="muted small">Latest 200 changes. Nobody can edit or delete this trail.</span>
      </div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading('Loading audit trail…') : S.rows.length === 0 ? Empty('No changes recorded.') : html`<div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Change</th></tr></thead>
        <tbody>${S.rows.map((r) => html`<tr>
          <td>${fmtDate(r.at)} ${fmtTime(r.at)}</td>
          <td>${r.actor ? S.names[r.actor] || 'Unknown user' : html`<span class="muted">System</span>`}</td>
          <td>${TABLE_LABEL[r.table_name] || r.table_name}</td>
          <td class="small" style="white-space:normal;min-width:280px">${summary(r)}</td></tr>`)}</tbody></table></div>`}`
  },
  actions: {
    async load() {
      this.set({ rows: null })
      let q = supabase.from('audit_log').select('*').order('at', { ascending: false }).limit(200)
      if (this.S.table) q = q.eq('table_name', this.S.table)
      const [a, p] = await Promise.all([q, supabase.from('profiles').select('id, full_name')])
      if (a.error) return this.set({ err: errText(a.error) })
      this.set({ names: Object.fromEntries((p.data || []).map((x) => [x.id, x.full_name])), rows: a.data })
    },
  },
}

export default {
  state: { tab: 'risk' },
  widgets: { risk, audit },
  view(S) {
    return html`${PageHead({ label: 'Fraud check', title: 'Risk and audit trail', sub: 'Who to look at first, and every change anyone has made.' })}
      <div class="toolbar"><div class="seg">
        <button class="${S.tab === 'risk' ? 'on' : ''}" data-act="tab" data-k="risk">TSO risk (30 days)</button>
        <button class="${S.tab === 'audit' ? 'on' : ''}" data-act="tab" data-k="audit">Audit trail</button>
      </div></div>
      ${widget(this, S.tab, 'x')}`
  },
  actions: { tab(el) { this.set({ tab: el.dataset.k }) } },
}
