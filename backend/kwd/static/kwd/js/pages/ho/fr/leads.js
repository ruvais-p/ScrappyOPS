/* Head Office: give leads to franchisees (one, or a pasted list) and follow what they do with them. */
import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, Empty, Icon, PageHead, Stat } from '../../../ui.js'
import { fmtDate } from '../../../lib.js'
import { Sheet, errLine } from '../../../kit.js'
import { CUSTOMER_TYPES, customerShort, LEAD_STATUS, LEAD_OPEN, daysSince } from '../../../fr.js'
import { LeadPill } from '../../fr/parts.js'

const phone10 = (s) => { const d = (s || '').replace(/\D/g, ''); return d ? d.slice(-10) : null }
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`
const SAMPLE = 'customer_name,type,contact_person,phone,place,district,product_code,qty,note\nKondotty Municipality,lsgd,Fathima Beevi,9846011111,Kondotty,Malappuram,KWD-160,50,Annual plan meeting in March'
const emptyLead = (fid) => ({ franchise_id: fid || '', customer_name: '', customer_type: 'lsgd', contact_person: '', phone: '', district_id: '', place: '', product_id: '', qty: '', hq_note: '' })

function parseList(text, products, districts) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  if (!lines.length) return { rows: [], bad: [] }
  const split = (l) => { const o = []; let c = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { o.push(c.trim()); c = '' } else c += ch } o.push(c.trim()); return o }
  const head = split(lines[0]).map((h) => h.toLowerCase())
  const hasHead = head.includes('customer_name') || head.includes('name')
  const col = (r, k, alt) => { const i = head.indexOf(k) >= 0 ? head.indexOf(k) : head.indexOf(alt); return i >= 0 ? r[i] || '' : '' }
  const rows = [], bad = []
  lines.slice(hasHead ? 1 : 0).forEach((l, i) => {
    const r = split(l)
    const name = hasHead ? col(r, 'customer_name', 'name') : r[0]
    const type = (hasHead ? col(r, 'type') : r[1] || 'lsgd').toLowerCase()
    if (!name || name.length < 2) return bad.push(`Row ${i + 1}: no name`)
    if (!CUSTOMER_TYPES[type]) return bad.push(`Row ${i + 1} (${name}): type must be private, lsgd, institution or business`)
    const dn = hasHead ? col(r, 'district') : r[5]
    const d = dn ? districts.find((x) => x.name.toLowerCase() === dn.toLowerCase()) : null
    if (dn && !d) return bad.push(`Row ${i + 1} (${name}): district "${dn}" not found`)
    const pc = hasHead ? col(r, 'product_code', 'product') : r[6]
    const p = pc ? products.find((x) => x.code.toLowerCase() === pc.toLowerCase()) : null
    if (pc && !p) return bad.push(`Row ${i + 1} (${name}): product code "${pc}" not found`)
    const ph = phone10(hasHead ? col(r, 'phone') : r[3])
    if (ph && !/^[6-9]\d{9}$/.test(ph)) return bad.push(`Row ${i + 1} (${name}): phone is not a valid mobile number`)
    rows.push({ customer_name: name, customer_type: type, contact_person: (hasHead ? col(r, 'contact_person') : r[2]) || null, phone: ph,
      place: (hasHead ? col(r, 'place') : r[4]) || null, district_id: d ? d.id : null, product_id: p ? p.id : null,
      qty: Number(hasHead ? col(r, 'qty') : r[7]) || null, hq_note: (hasHead ? col(r, 'note') : r[8]) || null })
  })
  return { rows, bad }
}

function assignSheet(S, ctx) {
  const { frs, products, districts } = ctx.data, v = S.v
  return Sheet({ title: 'Assign a lead', close: 'closeForm', body: html`
    <label>Franchisee<select data-bind="v.franchise_id"><option value="">Choose…</option>${frs.filter((f) => f.is_active).map((f) => opt(f.id, v.franchise_id, f.business_name))}</select></label>
    <label>Customer / LSGD name<input data-bind="v.customer_name" value="${v.customer_name}"></label>
    <div class="grid2">
      <label>Type<select data-bind="v.customer_type">${Object.entries(CUSTOMER_TYPES).map(([k, l]) => opt(k, v.customer_type, l))}</select></label>
      <label>Contact person<input data-bind="v.contact_person" value="${v.contact_person}"></label>
    </div>
    <div class="grid2">
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="v.phone" value="${v.phone}"></label>
      <label>District<select data-bind="v.district_id"><option value="">Choose…</option>${districts.map((d) => opt(d.id, v.district_id, d.name))}</select></label>
    </div>
    <label>Place / address<input data-bind="v.place" value="${v.place}"></label>
    <div class="grid2">
      <label>Interested in<select data-bind="v.product_id"><option value="">Not known</option>${products.filter((p) => p.is_active).map((p) => opt(p.id, v.product_id, p.name))}</select></label>
      <label>Quantity<input type="number" min="1" inputmode="numeric" data-bind="v.qty" value="${v.qty}"></label>
    </div>
    <label>Note for the franchisee<input data-bind="v.hq_note" value="${v.hq_note}" placeholder="Who to ask for, what was promised…"></label>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="assign" data-another="">${S.busy ? 'Saving…' : 'Assign lead'}</button>
    <button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="assign" data-another="1">Assign and add another</button>` })
}

function importSheet(S, ctx) {
  const { frs, products, districts } = ctx.data
  const parsed = parseList(S.text, products, districts)
  return Sheet({ title: 'Import a list of leads', close: 'closeForm', body: html`
    <p class="muted small" style="margin-top:0">Paste rows from Excel or a CSV file. All of them go to one franchisee. Columns, in this order:</p>
    <pre class="card small" style="white-space:pre-wrap;margin:0 0 12px">${SAMPLE}</pre>
    <p class="muted small">Type is private, lsgd, institution or business. Product code is one of ${products.map((p) => p.code).join(', ')}.</p>
    <label>Give these leads to<select data-bind="fid"><option value="">Choose…</option>${frs.filter((f) => f.is_active).map((f) => opt(f.id, S.fid, f.business_name))}</select></label>
    <label>Rows<textarea rows="7" data-bind="text" data-live placeholder="${SAMPLE}">${S.text}</textarea></label>
    ${S.text ? html`<p class="notice small"><span>${parsed.rows.length} ready${parsed.bad.length ? `, ${parsed.bad.length} with a problem` : ''}.</span></p>` : ''}
    ${parsed.bad.slice(0, 6).map((b) => html`<p class="error small" style="margin:2px 0">${b}</p>`)}
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy || !parsed.rows.length ? raw('disabled') : ''} data-act="runImport">${S.busy ? 'Importing…' : `Assign ${parsed.rows.length || ''} leads`}</button>` })
}

function detailSheet(S, ctx) {
  const { frs, byId, districts } = ctx.data, lead = S.open
  const movable = ['new', 'contacted', 'lost'].includes(lead.status)
  return Sheet({ title: lead.customer_name, close: 'closeOpen', body: html`
    <div class="row wrap">${LeadPill(lead.status)}<span class="pill">${CUSTOMER_TYPES[lead.customer_type]}</span></div>
    <div class="summary" style="margin:12px 0">
      <div class="summary-row"><span>Contact</span><span>${[lead.contact_person, lead.phone].filter(Boolean).join(' · ') || '—'}</span></div>
      <div class="summary-row"><span>Where</span><span>${[lead.place, (districts.find((d) => d.id === lead.district_id) || {}).name].filter(Boolean).join(', ') || '—'}</span></div>
      <div class="summary-row"><span>Interest</span><span>${lead.product_id ? `${lead.qty || 1} × ${byId[lead.product_id] && byId[lead.product_id].name}` : '—'}</span></div>
      <div class="summary-row"><span>Assigned</span><span>${fmtDate(lead.assigned_at)}</span></div>
      ${lead.next_followup_on ? html`<div class="summary-row"><span>Next follow-up</span><span>${fmtDate(lead.next_followup_on)}</span></div>` : ''}
    </div>
    ${lead.fr_note ? html`<p class="notice info small"><span><b>Franchisee’s note:</b> ${lead.fr_note}</span></p>` : ''}
    ${lead.lost_reason ? html`<p class="notice bad small"><span><b>Lost because:</b> ${lead.lost_reason}</span></p>` : ''}
    <label>Franchisee<select data-bind="ofid" ${movable ? '' : raw('disabled')}>${frs.map((f) => opt(f.id, S.ofid, f.business_name))}</select></label>
    ${!movable ? html`<p class="muted small">A lead in progress or closed stays with its franchisee.</p>` : ''}
    <label>Note for the franchisee<input data-bind="onote" value="${S.onote}"></label>
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="saveOpen">Save</button>
    ${S.events.length > 0 ? html`<div class="field-label" style="margin-top:18px">History</div>
      <ul class="trail">${S.events.map((e) => html`<li><b>${LEAD_STATUS[e.to_status] && LEAD_STATUS[e.to_status].label}</b> <span class="muted small">${fmtDate(e.at)}${e.note ? ` · ${e.note}` : ''}</span></li>`)}</ul>` : ''}` })
}

export default {
  state: (ctx) => ({ rows: null, err: '', fid: ctx.route.franchiseId || '', st: '', q: '', form: ctx.route.assign ? 'one' : null, v: emptyLead(ctx.route.franchiseId),
    text: '', open: null, events: [], ofid: '', onote: '', busy: false }),
  async init() { await this.actions.load.call(this) },
  view(S, ctx) {
    const { frs, byId, districts } = ctx.data
    if (S.err && !S.rows) return html`<p class="error">${S.err}</p>`
    if (!S.rows) return Loading('Loading leads…')
    const fname = (id) => (frs.find((f) => f.id === id) || {}).business_name || '—'
    const dName = (id) => (districts.find((d) => d.id === id) || {}).name
    const q = S.q.trim().toLowerCase()
    const list = S.rows.filter((l) => (!S.fid || l.franchise_id === S.fid) && (!S.st || (S.st === 'open' ? LEAD_OPEN.includes(l.status) : l.status === S.st))
      && (!q || `${l.customer_name} ${l.place} ${l.phone} ${fname(l.franchise_id)}`.toLowerCase().includes(q)))
    const scoped = S.rows.filter((l) => !S.fid || l.franchise_id === S.fid)
    const won = scoped.filter((l) => l.status === 'won').length, lost = scoped.filter((l) => l.status === 'lost').length
    return html`${PageHead({ label: 'Franchise', title: 'Leads', sub: 'Give leads to franchisees and follow what they do with them. They update the status; you see every change.',
        actions: html`<button class="btn" data-act="openForm" data-k="csv">${Icon('upload', 18)} Import list</button><button class="btn primary" data-act="openForm" data-k="one">${Icon('plus', 18)} Assign a lead</button>` })}
      <div class="stats">
        ${Stat({ lead: true, label: 'Leads given', value: scoped.length })}
        ${Stat({ label: 'Open', value: scoped.filter((l) => LEAD_OPEN.includes(l.status)).length })}
        ${Stat({ label: 'Sale closed', value: won, tone: 'ok' })}
        ${Stat({ label: 'Lost', value: lost, sub: won + lost ? `${Math.round((100 * won) / (won + lost))}% of decided leads won` : '' })}
      </div>
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search customer, place, phone" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="fid" data-live aria-label="Franchisee"><option value="">All franchisees</option>${frs.map((f) => opt(f.id, S.fid, f.business_name))}</select>
        <select data-bind="st" data-live aria-label="Status"><option value="">Any status</option><option value="open" ${S.st === 'open' ? raw('selected') : ''}>All open</option>${Object.entries(LEAD_STATUS).map(([k, v]) => opt(k, S.st, v.label))}</select>
      </div>
      ${list.length === 0 ? Empty(S.rows.length ? 'No leads match.' : 'No leads assigned yet.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Customer</th><th>Franchisee</th><th>Where</th><th>Interest</th><th>Status</th><th>Follow-up</th><th>Assigned</th></tr></thead>
        <tbody>${list.map((l) => html`<tr data-act="openLead" data-id="${l.id}" style="cursor:pointer">
          <td><b>${l.customer_name}</b><div class="muted small">${customerShort[l.customer_type]}${l.phone ? ` · ${l.phone}` : ''}</div></td>
          <td>${fname(l.franchise_id)}</td>
          <td style="white-space:normal">${[l.place, dName(l.district_id)].filter(Boolean).join(', ') || '—'}</td>
          <td style="white-space:normal">${l.product_id ? `${l.qty || 1} × ${byId[l.product_id] && byId[l.product_id].name}` : '—'}</td>
          <td>${LeadPill(l.status)}${l.status === 'new' && daysSince(l.assigned_at) >= 3 ? html`<span class="pill warn tiny">${daysSince(l.assigned_at)} d untouched</span>` : ''}</td>
          <td>${l.next_followup_on ? fmtDate(l.next_followup_on) : '—'}</td><td>${fmtDate(l.assigned_at)}</td></tr>`)}</tbody></table></div>`}
      ${S.form === 'one' ? assignSheet(S, ctx) : ''}${S.form === 'csv' ? importSheet(S, ctx) : ''}${S.open ? detailSheet(S, ctx) : ''}`
  },
  actions: {
    async load() {
      const { data, error } = await supabase.from('fr_leads').select('*').order('assigned_at', { ascending: false })
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data })
    },
    openForm(el) { this.set({ form: el.dataset.k, err: '', text: '', v: emptyLead(this.S.fid) }) },
    closeForm() { this.set({ form: null }); this.actions.load.call(this) },
    async assign(el) {
      const S = this.S, v = S.v, another = !!el.dataset.another
      this.set({ err: '' })
      if (!v.franchise_id) return this.set({ err: 'Choose the franchisee.' })
      if (v.customer_name.trim().length < 2) return this.set({ err: 'Enter the customer name.' })
      if (v.phone && !/^[6-9]\d{9}$/.test(phone10(v.phone) || '')) return this.set({ err: 'Enter a valid 10-digit mobile number.' })
      this.set({ busy: true })
      const { error } = await supabase.from('fr_leads').insert({
        franchise_id: v.franchise_id, customer_name: v.customer_name.trim(), customer_type: v.customer_type, contact_person: v.contact_person.trim() || null,
        phone: phone10(v.phone), district_id: v.district_id ? Number(v.district_id) : null, place: v.place.trim() || null,
        product_id: v.product_id || null, qty: v.qty ? Number(v.qty) : null, hq_note: v.hq_note.trim() || null,
      })
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Lead assigned')
      if (another) this.set({ v: { ...v, customer_name: '', contact_person: '', phone: '', place: '', hq_note: '' } })
      else this.actions.closeForm.call(this)
    },
    async runImport() {
      const S = this.S, { products, districts } = this.ctx.data
      const parsed = parseList(S.text, products, districts)
      this.set({ err: '' })
      if (!S.fid) return this.set({ err: 'Choose the franchisee who gets these leads.' })
      if (!parsed.rows.length) return this.set({ err: 'Nothing to import yet.' })
      if (parsed.bad.length && !confirm(`${parsed.bad.length} row(s) will be skipped. Import the other ${parsed.rows.length}?`)) return
      this.set({ busy: true })
      const { error } = await supabase.from('fr_leads').insert(parsed.rows.map((r) => ({ ...r, franchise_id: S.fid })))
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast(`${parsed.rows.length} leads assigned`)
      this.actions.closeForm.call(this)
    },
    async openLead(el) {
      const lead = this.S.rows.find((l) => l.id === el.dataset.id)
      this.set({ open: lead, ofid: lead.franchise_id, onote: lead.hq_note || '', events: [], err: '' })
      const { data } = await supabase.from('fr_lead_events').select('*').eq('lead_id', lead.id).order('at', { ascending: false })
      this.set({ events: data || [] })
    },
    closeOpen() { this.set({ open: null }) },
    async saveOpen() {
      const S = this.S
      this.set({ busy: true, err: '' })
      const { error } = await supabase.from('fr_leads').update({ franchise_id: S.ofid, hq_note: S.onote.trim() || null }).eq('id', S.open.id)
      this.set({ busy: false })
      if (error) return this.set({ err: errText(error) })
      toast('Saved')
      this.set({ open: null })
      await this.actions.load.call(this)
    },
  },
}
