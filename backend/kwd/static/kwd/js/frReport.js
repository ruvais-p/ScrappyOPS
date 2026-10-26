// Excel report for the franchise module: Summary, Sales, Leads, Stock, Stock history, Presentations, Targets.
// ExcelJS is loaded only when someone downloads.
import { supabase } from './core.js'
import { istDate } from './lib.js'
import { loadExcelJS } from './report.js'
import {
  CUSTOMER_TYPES, LEAD_STATUS, DELIVERY, INSTALL, PAYMENT, VENUES, OUTCOMES, MOVE_KIND, SALE_FLAG, achievement, monthStart, monthName,
} from './fr.js'

const BILL_TYPES = { B2B: 'B2B', B2C: 'B2C', B2G: 'B2G' }

const OX = 'FF8B1E24', LINE = 'FFE4E1DC', BAND = 'FFFAFAF9'
const INR = '"₹"#,##0.00', INT = '#,##0'
const ist = (ts) => (ts ? new Date(new Date(ts).getTime() + 5.5 * 36e5) : null)
const day = (iso) => (iso ? new Date(iso + 'T00:00:00Z') : null)
const n = (v) => (v == null ? null : Number(v))

async function all(q) {
  const out = []
  for (let from = 0; ; from += 1000) {
    const { data, error } = await q().range(from, from + 999)
    if (error) throw new Error(error.message)
    out.push(...data)
    if (data.length < 1000) return out
  }
}

export async function downloadFranchiseReport({ franchiseIds = null, title = 'All franchisees' }) {
  const only = (q) => (franchiseIds ? q.in('franchise_id', franchiseIds) : q)
  const [frs, products, districts, leads, sales, items, moves, pres, targets] = await Promise.all([
    all(() => supabase.from('fr_franchises').select('id, business_name, district_id, territory, is_active, profile:profiles!fr_franchises_user_id_fkey(full_name, email, phone)').order('business_name')),
    all(() => supabase.from('fr_products').select('*').order('sort')),
    all(() => supabase.from('districts').select('id, name')),
    all(() => only(supabase.from('fr_leads').select('*').order('assigned_at', { ascending: false }))),
    all(() => only(supabase.from('fr_sales').select('*').order('sale_date', { ascending: false }))),
    all(() => supabase.from('fr_sale_items').select('*')),
    all(() => only(supabase.from('fr_stock_moves').select('*').order('created_at', { ascending: false }))),
    all(() => only(supabase.from('fr_presentations').select('*').order('scheduled_at', { ascending: false }))),
    all(() => only(supabase.from('fr_targets').select('*').order('month', { ascending: false }))),
  ])
  const fr = Object.fromEntries(frs.map((f) => [f.id, f]))
  const prod = Object.fromEntries(products.map((p) => [p.id, p]))
  const dist = Object.fromEntries(districts.map((d) => [d.id, d.name]))
  const fname = (id) => fr[id]?.business_name || ''
  const sold = items.map((i) => {
    const s = sales.find((x) => x.id === i.sale_id)
    return s && s.status === 'active' ? { franchise_id: s.franchise_id, month: s.sale_date.slice(0, 8) + '01', product_id: i.product_id, qty: i.qty, line_total: i.line_total } : null
  }).filter(Boolean)
  const scope = frs.filter((f) => !franchiseIds || franchiseIds.includes(f.id))
  const month = monthStart()

  const ExcelJS = await loadExcelJS()
  const wb = new ExcelJS.Workbook()
  wb.creator = 'Scrappy Field'; wb.created = new Date(); wb.company = 'Scrappy Innovations'

  function sheet(label, cols, rows) {
    const ws = wb.addWorksheet(label, { views: [{ state: 'frozen', ySplit: 1 }] })
    ws.columns = cols.map((c) => ({ header: c[0], key: c[0], width: c[1], style: c[2] ? { numFmt: c[2] } : {} }))
    const h = ws.getRow(1)
    h.height = 22
    h.eachCell((c) => { c.font = { bold: true, color: { argb: 'FFFFFFFF' } }; c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: OX } }; c.alignment = { vertical: 'middle', wrapText: true } })
    rows.forEach((r, i) => {
      const row = ws.addRow(r)
      if (i % 2) row.eachCell((c) => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BAND } } })
      row.eachCell((c) => { c.border = { bottom: { style: 'thin', color: { argb: LINE } } } })
    })
    if (rows.length) ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: cols.length } }
    return ws
  }

  // ---- Summary
  const sum = scope.map((f) => {
    const a = achievement(sold, targets, month, f.id)
    const L = leads.filter((l) => l.franchise_id === f.id)
    const S = sales.filter((s) => s.franchise_id === f.id && s.status === 'active')
    const stockUnits = moves.filter((m) => m.franchise_id === f.id).reduce((x, m) => x + m.qty, 0)
    return [f.business_name, f.profile?.full_name, dist[f.district_id] || '', f.is_active ? 'Active' : 'Off',
      L.length, L.filter((l) => l.status === 'won').length, L.filter((l) => l.status === 'lost').length, L.filter((l) => ['new', 'contacted', 'presentation_set', 'negotiating'].includes(l.status)).length,
      S.length, S.reduce((x, s) => x + Number(s.total), 0), S.reduce((x, s) => x + Number(s.amount_received), 0),
      a.units, a.value, a.tUnits || null, a.tValue || null, a.pctValue != null ? a.pctValue / 100 : null, stockUnits,
      pres.filter((p) => p.franchise_id === f.id && p.status === 'done').length]
  })
  sheet('Summary', [
    ['Franchisee', 28], ['Owner', 22], ['District', 16], ['Status', 9], ['Leads given', 11, INT], ['Leads won', 10, INT], ['Leads lost', 10, INT], ['Leads open', 10, INT],
    ['Sales (all time)', 12, INT], ['Sales value (all time)', 18, INR], ['Money received', 16, INR],
    [`Units ${monthName(month, true)}`, 12, INT], [`Value ${monthName(month, true)}`, 16, INR], [`Unit target`, 11, INT], [`Value target`, 16, INR], ['Target achieved', 12, '0%'], ['Units in stock', 12, INT], ['Presentations held', 14, INT],
  ], sum)

  // ---- Sales (one line per product sold)
  const lines = []
  sales.forEach((s) => {
    const its = items.filter((i) => i.sale_id === s.id)
    ;(its.length ? its : [null]).forEach((i) => lines.push([
      fname(s.franchise_id), day(s.sale_date), s.customer_name, BILL_TYPES[s.customer_type], s.phone, dist[s.district_id] || '', s.place, s.invoice_no,
      i ? prod[i.product_id]?.name : '', i?.qty ?? null, n(i?.unit_price), n(i?.line_total), n(s.total), n(s.amount_received), PAYMENT[s.payment_status],
      DELIVERY[s.delivery_status], day(s.delivered_on), s.needs_install ? INSTALL[s.installation_status] : 'Not needed', day(s.installed_on),
      s.status === 'cancelled' ? 'Cancelled' : 'Active', (s.flags || []).map((f) => SALE_FLAG[f] || f).join('; '), s.ho_flag ? s.ho_flag_reason : '',
    ]))
  })
  sheet('Sales', [
    ['Franchisee', 24], ['Sale date', 12, 'dd mmm yyyy'], ['Customer', 26], ['Type', 14], ['Phone', 13], ['District', 14], ['Place', 18], ['Invoice', 11],
    ['Product', 28], ['Qty', 6, INT], ['Unit price', 12, INR], ['Line total', 14, INR], ['Sale total', 14, INR], ['Received', 14, INR], ['Payment', 10],
    ['Delivery', 14], ['Delivered on', 12, 'dd mmm yyyy'], ['Installation', 20], ['Installed on', 12, 'dd mmm yyyy'], ['Status', 10], ['System flags', 26], ['HO flag', 24],
  ], lines)

  // ---- Leads
  sheet('Leads', [
    ['Franchisee', 24], ['Assigned', 12, 'dd mmm yyyy'], ['Customer', 26], ['Type', 14], ['Contact', 18], ['Phone', 13], ['District', 14], ['Place', 18],
    ['Product', 28], ['Qty', 6], ['Status', 16], ['Next follow-up', 13, 'dd mmm yyyy'], ['Lost reason', 24], ['HO note', 28], ['Franchisee note', 28],
  ], leads.map((l) => [fname(l.franchise_id), ist(l.assigned_at), l.customer_name, CUSTOMER_TYPES[l.customer_type], l.contact_person, l.phone, dist[l.district_id] || '', l.place,
    l.product_id ? prod[l.product_id]?.name : '', l.qty, LEAD_STATUS[l.status]?.label, day(l.next_followup_on), l.lost_reason, l.hq_note, l.fr_note]))

  // ---- Stock now + history
  const held = {}
  moves.forEach((m) => { const k = m.franchise_id + m.product_id; (held[k] ||= { f: m.franchise_id, p: m.product_id, q: 0 }).q += m.qty })
  sheet('Stock now', [['Franchisee', 26], ['Product', 30], ['In stock', 10, INT]],
    Object.values(held).sort((a, b) => fname(a.f).localeCompare(fname(b.f))).map((h) => [fname(h.f), prod[h.p]?.name, h.q]))
  sheet('Stock history', [['When (IST)', 18, 'dd mmm yyyy hh:mm'], ['Franchisee', 24], ['Product', 28], ['Change', 9, '+0;-0'], ['What', 24], ['Reference', 14], ['Note', 36]],
    moves.map((m) => [ist(m.created_at), fname(m.franchise_id), prod[m.product_id]?.name, m.qty, MOVE_KIND[m.kind], m.ref_no, m.note]))

  // ---- Presentations
  sheet('Presentations', [
    ['When (IST)', 18, 'dd mmm yyyy hh:mm'], ['Franchisee', 24], ['Venue type', 20], ['Place', 28], ['LSGD', 20], ['District', 14], ['Address', 24], ['Contact', 18], ['Phone', 13],
    ['Expected', 9], ['Attended', 9], ['Products', 34], ['Status', 11], ['Outcome', 16], ['Moved', 7], ['Notes', 34], ['Cancel reason', 24],
  ], pres.map((p) => [ist(p.scheduled_at), fname(p.franchise_id), VENUES[p.venue_type], p.venue_name, p.lsgd_name, dist[p.district_id] || '', p.address, p.contact_person, p.phone,
    p.expected_attendees, p.actual_attendees, (p.product_ids || []).map((i) => prod[i]?.name).filter(Boolean).join(', '), p.status, OUTCOMES[p.outcome] || '', p.reschedule_count, p.notes, p.cancel_reason]))

  // ---- Targets vs achievement by month
  const months = [...new Set([...targets.map((t) => t.month), ...sold.map((s) => s.month)])].sort().reverse()
  const trows = []
  months.forEach((m) => scope.forEach((f) => {
    const a = achievement(sold, targets, m, f.id)
    if (a.units || a.value || a.tUnits || a.tValue) trows.push([day(m), f.business_name, a.tUnits || null, a.units, a.tUnits ? a.units / a.tUnits : null, a.tValue || null, a.value, a.tValue ? a.value / a.tValue : null])
  }))
  sheet('Targets', [['Month', 12, 'mmm yyyy'], ['Franchisee', 26], ['Unit target', 11, INT], ['Units sold', 11, INT], ['Units %', 9, '0%'], ['Value target', 16, INR], ['Value sold', 16, INR], ['Value %', 9, '0%']], trows)

  const buf = await wb.xlsx.writeBuffer()
  const url = URL.createObjectURL(new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  const a = document.createElement('a')
  a.href = url; a.download = `Scrappy-Franchise-${title.replace(/[^a-z0-9]+/gi, '-')}-${istDate()}.xlsx`
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000)
}
