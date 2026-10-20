import { html, supabase, errText } from '../../core.js'
import { Loading, PageHead, SectionHead, Stat, Icon } from '../../ui.js'
import { fmtINR } from '../../lib.js'
import { achievement, monthStart, addMonths, monthName } from '../../fr.js'

export default {
  state: { d: null, err: '', month: monthStart() },
  async init() {
    const [s, t] = await Promise.all([supabase.from('v_fr_sold').select('*'), supabase.from('fr_targets').select('*')])
    const e = s.error || t.error
    if (e) return this.set({ err: errText(e) })
    this.set({ d: { sold: s.data, targets: t.data } })
  },
  view(S, ctx) {
    const { fr, products } = ctx.data
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.d) return Loading('Loading targets…')
    const now = monthStart(), month = S.month
    const a = achievement(S.d.sold, S.d.targets, month)
    const has = a.tValue > 0 || a.tUnits > 0
    const history = Array.from({ length: 6 }, (_, i) => addMonths(now, -i)).map((m) => ({ m, ...achievement(S.d.sold, S.d.targets, m) }))
    const rows = products.filter((p) => a.perProduct[p.id])
    return html`${PageHead({ label: fr.business_name, title: 'Targets & achievement', sub: 'Set by Head Office each month. Your sales count automatically.',
        actions: html`<div class="seg">
          <button data-act="month" data-n="-1" aria-label="Previous month">${Icon('left', 16)}</button>
          <button class="on" style="min-width:140px">${monthName(month)}</button>
          <button data-act="month" data-n="1" ${month >= now ? 'disabled' : ''} aria-label="Next month">${Icon('right', 16)}</button></div>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Value achieved', value: a.pctValue != null ? `${a.pctValue}%` : '—', sub: a.tValue ? `${fmtINR(a.value)} of ${fmtINR(a.tValue)}` : fmtINR(a.value) })}
        ${Stat({ label: 'Units achieved', value: a.pctUnits != null ? `${a.pctUnits}%` : '—', sub: a.tUnits ? `${a.units} of ${a.tUnits}` : `${a.units} sold` })}
        ${Stat({ label: 'Still to go (value)', value: a.tValue ? fmtINR(Math.max(0, a.tValue - a.value)) : '—', tone: a.tValue && a.value < a.tValue ? 'warn' : 'ok' })}
        ${Stat({ label: 'Still to go (units)', value: a.tUnits ? Math.max(0, a.tUnits - a.units) : '—' })}
      </div>
      ${!has ? html`<p class="notice info"><span>No target is set for ${monthName(month)}. Your sales are still counted.</span></p>` : ''}
      ${rows.length > 0 ? html`<section>${SectionHead({ title: 'By product' })}<div class="table-wrap"><table>
        <thead><tr><th>Product</th><th class="num">Sold</th><th class="num">Target</th><th class="num">Achieved</th><th class="num">Value</th></tr></thead>
        <tbody>${rows.map((p) => { const r = a.perProduct[p.id]; return html`<tr><td><b>${p.name}</b></td><td class="num">${r.units}</td><td class="num">${r.target || '—'}</td>
          <td class="num">${r.target ? `${Math.round((100 * r.units) / r.target)}%` : '—'}</td><td class="num">${fmtINR(r.value)}</td></tr>` })}</tbody></table></div></section>` : ''}
      <section class="card"><h2>Last six months</h2><div class="bars">${history.map((h) => html`<div class="bar-row">
        <span>${monthName(h.m, true)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, h.tValue ? (100 * h.value) / h.tValue : h.value ? 100 : 0)}%"></div></div>
        <span style="text-align:right">${fmtINR(h.value)}${h.pctValue != null ? ` · ${h.pctValue}%` : ''}</span></div>`)}</div></section>`
  },
  actions: {
    month(el) { this.set({ month: addMonths(this.S.month, Number(el.dataset.n)) }) },
  },
}
