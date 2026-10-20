/* Head Office lands here after sign-in and chooses which side of the business to open. ctx: { onPick('staff' | 'franchise') } */
import { html, supabase, endSession } from '../../core.js'
import { Icon, Mascot } from '../../ui.js'
import { fmtINR } from '../../lib.js'
import { monthStart } from '../../fr.js'

export default {
  state: { s: null },
  async init() {
    const month = monthStart()
    const r = await Promise.all([
      supabase.from('visits').select('id', { count: 'exact', head: true }).eq('zm_status', 'verified').is('ho_signed_at', null),
      supabase.from('field_days').select('id', { count: 'exact', head: true }).eq('status', 'zm_approved'),
      supabase.from('profiles').select('id', { count: 'exact', head: true }).eq('role', 'tso').eq('is_active', true),
      supabase.from('fr_franchises').select('id', { count: 'exact', head: true }).eq('is_active', true),
      supabase.from('fr_leads').select('id', { count: 'exact', head: true }).in('status', ['new', 'contacted', 'presentation_set', 'negotiating']),
      supabase.from('v_fr_sold').select('line_total').gte('month', month),
      supabase.from('fr_sales').select('id', { count: 'exact', head: true }).eq('status', 'active').neq('delivery_status', 'delivered'),
    ])
    this.set({ s: {
      sign: r[0].count || 0, claims: r[1].count || 0, tsos: r[2].count || 0, frs: r[3].count || 0, leads: r[4].count || 0,
      sales: (r[5].data || []).reduce((a, x) => a + Number(x.line_total), 0), deliver: r[6].count || 0,
    } })
  },
  view(S) {
    const s = S.s
    const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }).format(new Date()))
    const hello = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
    const dash = '—'
    return html`<div class="module-wrap">
      <div class="module-top">
        <img class="wordmark" src="/static/kwd/brand/scrappy-wordmark-oxblood.svg" alt="Scrappy" width="110" height="39">
        <button class="btn sm" data-act="signout">${Icon('logout', 16)} Sign out</button>
      </div>
      <div class="module-hello">
        ${Mascot({ mood: 'wave', size: 96, bob: true })}
        <div>
          <span class="section-label">Head Office</span>
          <h1>${hello}. What would you like to open?</h1>
          <p class="muted" style="margin:0">${new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })} · you can switch any time</p>
        </div>
      </div>
      <div class="module-grid">
        <button class="module-card" data-act="pick" data-m="staff">
          <span class="m-ico">${Icon('users', 28)}</span>
          <h2>Staff monitoring</h2>
          <p>Visits, GPS checks, TA / DA requests and fraud review for Zonal Managers and TSOs.</p>
          <div class="m-stats">
            <div><b>${s ? s.sign : dash}</b><span>visits to sign off</span></div>
            <div><b>${s ? s.claims : dash}</b><span>TA / DA to approve</span></div>
            <div><b>${s ? s.tsos : dash}</b><span>active TSOs</span></div>
          </div>
          <span class="m-open">Open staff monitoring ${Icon('right', 18)}</span>
        </button>
        <button class="module-card" data-act="pick" data-m="franchise">
          <span class="m-ico">${Icon('box', 28)}</span>
          <h2>Franchise</h2>
          <p>Leads, sales, stock, targets and presentation appointments across your franchisees.</p>
          <div class="m-stats">
            <div><b>${s ? s.frs : dash}</b><span>active franchisees</span></div>
            <div><b>${s ? s.leads : dash}</b><span>open leads</span></div>
            <div><b>${s ? fmtINR(s.sales) : dash}</b><span>sold this month</span></div>
            <div><b>${s ? s.deliver : dash}</b><span>to deliver</span></div>
          </div>
          <span class="m-open">Open franchise module ${Icon('right', 18)}</span>
        </button>
      </div>
    </div>`
  },
  actions: {
    pick(el) { this.ctx.onPick(el.dataset.m) },
    signout() { endSession() },
  },
}
