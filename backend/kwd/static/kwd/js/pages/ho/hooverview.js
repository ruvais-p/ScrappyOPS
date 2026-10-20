/* Head Office: statewide overview. */
import { html, supabase, errText, widget } from '../../core.js'
import { Loading, Stat, Icon, PageHead, SectionHead, Avatar } from '../../ui.js'
import { istDate, fmtINR, financialYear, STAGES, UNIT_PRICE } from '../../lib.js'
import { istStartISO, loadTeam } from '../../kit.js'
import missed from '../zm/missed.js'

const WON = ['work_order', 'supplied', 'payment_received']

export default {
  state: { d: null, err: '', team: null },
  widgets: { missed },
  async init() {
    loadTeam(this.ctx.profile).then((t) => this.set({ team: t.team }))
    const monthStart = istDate().slice(0, 8) + '01'
    const [dist, lsgds, visits, opps, staff, ud] = await Promise.all([
      supabase.from('districts').select('id, name').order('name'),
      supabase.from('lsgds').select('id, district_id, office_lat'),
      supabase.from('visits').select('id, tso_id, lsgd_id, check_in_at, fraud_flags, zm_status, zm_reviewed_by, ho_signed_at, lsgds(district_id)').gte('check_in_at', istStartISO(monthStart)),
      supabase.from('opportunities').select('lsgd_id, stage, expected_units, expected_value, probability, lsgds(district_id)').eq('financial_year', financialYear()),
      supabase.from('profiles').select('id, full_name, role, manager_id, is_active'),
      supabase.from('user_districts').select('user_id, district_id'),
    ])
    const e = [dist, lsgds, visits, opps, staff, ud].find((x) => x.error)
    if (e) return this.set({ err: errText(e.error) })
    // older pending reviews matter even before this month
    const backlog = await supabase.from('visits').select('id, check_in_at, lsgds(district_id)').eq('zm_status', 'pending')
    this.set({ d: { dist: dist.data, lsgds: lsgds.data, visits: visits.data, opps: opps.data, staff: staff.data, ud: ud.data, backlog: backlog.data || [] } })
  },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    const d = S.d
    if (!d) return Loading('Loading statewide numbers…')
    const today = istDate()
    const todayISO = istStartISO(today)
    const vToday = d.visits.filter((v) => v.check_in_at >= todayISO)
    const activeToday = new Set(vToday.map((v) => v.tso_id)).size
    const tsos = d.staff.filter((s) => s.role === 'tso' && s.is_active)
    const toSign = d.visits.filter((v) => v.zm_status === 'verified' && !v.ho_signed_at).length
    const open = d.opps.filter((o) => o.stage !== 'lost' && !WON.includes(o.stage))
    const won = d.opps.filter((o) => WON.includes(o.stage))
    const wonUnits = won.reduce((s, o) => s + o.expected_units, 0)
    const pipeline = open.reduce((s, o) => s + Number(o.expected_value), 0)
    const likely = open.reduce((s, o) => s + Number(o.expected_value) * o.probability / 100, 0)
    const oldestDays = d.backlog.length ? Math.floor((Date.now() - Math.min(...d.backlog.map((b) => +new Date(b.check_in_at)))) / 864e5) : 0

    const byDistrict = d.dist.map((x) => {
      const L = d.lsgds.filter((l) => l.district_id === x.id)
      const V = d.visits.filter((v) => v.lsgds.district_id === x.id)
      const O = d.opps.filter((o) => o.lsgds.district_id === x.id)
      const zm = d.staff.filter((s) => s.role === 'zonal_manager' && s.is_active && d.ud.some((u) => u.user_id === s.id && u.district_id === x.id))
      return {
        ...x, lsgds: L.length, noLoc: L.filter((l) => l.office_lat == null).length,
        visited: new Set(V.map((v) => v.lsgd_id)).size, visits: V.length, flagged: V.filter((v) => v.fraud_flags.length).length,
        pipeline: O.filter((o) => o.stage !== 'lost' && !WON.includes(o.stage)).reduce((s, o) => s + Number(o.expected_value), 0),
        wonUnits: O.filter((o) => WON.includes(o.stage)).reduce((s, o) => s + o.expected_units, 0),
        zm: zm.map((z) => z.full_name).join(', '),
      }
    })
    const zms = d.staff.filter((s) => s.role === 'zonal_manager').map((z) => {
      const team = d.staff.filter((s) => s.manager_id === z.id && s.role === 'tso' && s.is_active)
      const zDistricts = d.ud.filter((u) => u.user_id === z.id).map((u) => u.district_id)
      const V = d.visits.filter((v) => team.some((t) => t.id === v.tso_id))
      const pending = d.backlog.filter((b) => zDistricts.includes(b.lsgds.district_id))
      const reviewedByZ = d.visits.filter((v) => v.zm_reviewed_by === z.id)
      return {
        ...z, team: team.length, visits: V.length,
        flagRate: V.length ? Math.round(100 * V.filter((v) => v.fraud_flags.length).length / V.length) : 0,
        pending: pending.length,
        oldest: pending.length ? Math.floor((Date.now() - Math.min(...pending.map((b) => +new Date(b.check_in_at)))) / 864e5) : 0,
        // verified even though the system raised flags: worth a look
        verifiedFlagged: reviewedByZ.filter((v) => v.zm_status === 'verified' && v.fraud_flags.length).length,
      }
    })
    const byStage = STAGES.filter((s) => s.id !== 'lost').map((s) => {
      const os = d.opps.filter((o) => o.stage === s.id)
      return { ...s, n: os.length, value: os.reduce((a, o) => a + Number(o.expected_value), 0) }
    })
    const maxVal = Math.max(1, ...byStage.map((s) => s.value))

    return html`${PageHead({ label: 'Head Office · All Kerala', title: 'Statewide overview',
        sub: `${new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })} · visit numbers are for this month`,
        actions: html`<button class="btn" data-act="goto" data-page="fraud">${Icon('shield', 18)} Fraud check</button><button class="btn primary" data-act="goto" data-page="signoff">${Icon('check', 18)} Sign off visits</button>` })}
      <div class="stats">
        ${Stat({ label: 'Visits today', value: vToday.length, sub: `${activeToday} of ${tsos.length} TSOs in the field` })}
        ${Stat({ lead: true, label: 'Waiting for HO sign-off', value: toSign, tone: toSign ? 'warn' : '', sub: `${d.backlog.length} still with ZMs${oldestDays ? `, oldest ${oldestDays} d` : ''}` })}
        ${Stat({ label: `Open pipeline ${financialYear()}`, value: fmtINR(pipeline), sub: `Likely ${fmtINR(likely)}` })}
        ${Stat({ label: 'Units ordered', value: wonUnits.toLocaleString('en-IN'), sub: fmtINR(wonUnits * UNIT_PRICE), tone: 'ok' })}
      </div>

      <section>
        ${SectionHead({ title: 'Districts', count: byDistrict.length })}
        <div class="table-wrap"><table>
          <thead><tr><th>District</th><th>ZM</th><th class="num">LSGDs</th><th class="num">Visited this month</th><th class="num">Visits</th><th class="num">Flagged</th><th class="num">Pipeline</th><th class="num">Units ordered</th></tr></thead>
          <tbody>${byDistrict.map((x) => html`<tr>
            <td><b>${x.name}</b>${x.noLoc > 0 ? html`<div class="small text-warn">${x.noLoc} without location</div>` : ''}</td>
            <td>${x.zm || html`<span class="text-warn">None</span>`}</td>
            <td class="num">${x.lsgds}</td>
            <td class="num">${x.lsgds ? `${x.visited} (${Math.round(100 * x.visited / x.lsgds)}%)` : '—'}</td>
            <td class="num">${x.visits}</td>
            <td class="num">${x.flagged ? html`<span class="pill warn">${x.flagged}</span>` : 0}</td>
            <td class="num">${fmtINR(x.pipeline)}</td>
            <td class="num">${x.wonUnits}</td></tr>`)}</tbody></table></div>
      </section>

      <section>
        ${SectionHead({ title: 'Zonal Managers', count: zms.length })}
        <div class="table-wrap"><table>
          <thead><tr><th>ZM</th><th class="num">TSOs</th><th class="num">Team visits</th><th class="num">System-flag rate</th><th class="num">Reviews waiting</th><th class="num">Oldest waiting</th><th class="num">Verified despite flags</th></tr></thead>
          <tbody>${zms.length === 0 ? html`<tr><td colspan="7" class="muted">No Zonal Managers yet.</td></tr>` : zms.map((z) => html`<tr style="${z.is_active ? '' : 'opacity:.6'}">
            <td><div class="who-cell">${Avatar(z.full_name, 30)}<b>${z.full_name}</b></div></td>
            <td class="num">${z.team}</td><td class="num">${z.visits}</td><td class="num">${z.flagRate}%</td><td class="num">${z.pending}</td>
            <td class="num">${z.oldest > 2 ? html`<span class="text-bad">${z.oldest} days</span>` : z.pending ? `${z.oldest} days` : '—'}</td>
            <td class="num">${z.verifiedFlagged ? html`<span class="pill warn">${z.verifiedFlagged}</span>` : 0}</td></tr>`)}</tbody></table></div>
        <p class="muted small">"Verified despite flags" counts visits a ZM approved even though the system flagged them. Some are fine; a high number means the ZM may not be checking.</p>
      </section>

      ${S.team ? widget(this, 'missed', 'all', { team: S.team.map((t) => ({ id: t.id, full_name: t.full_name, email: t.email })) }) : ''}

      <section class="card">
        <h2>Pipeline by stage · ${financialYear()}</h2>
        ${d.opps.length === 0 ? html`<p class="muted">No deals yet.</p>` : html`<div class="bars">${byStage.map((s) => html`<div class="bar-row">
          <span>${s.label} <span class="muted">(${s.n})</span></span>
          <div class="bar-track"><div class="bar-fill" style="width:${(s.value / maxVal) * 100}%"></div></div>
          <span style="text-align:right">${fmtINR(s.value)}</span></div>`)}</div>`}
      </section>`
  },
  actions: {
    goto(el) { this.ctx.go(el.dataset.page) },
  },
}
