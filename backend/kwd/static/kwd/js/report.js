// Excel work-history report: Summary, Daily register (TA/DA), Expense bills, Visits, Follow-ups, Pipeline.
// ExcelJS is loaded only when someone downloads, so the app stays light.
import { supabase } from './core.js'
import { addDays, istDate, financialYear, FLAG_TEXT, LSGD_TYPES, INTEREST, stageLabel } from './lib.js'
import { istStartISO } from './kit.js'
import { TRAVEL_MODES, CATEGORIES, CLAIM_STATUS, flagText } from './expenses.js'

const OX = 'FF8B1E24', INK = 'FF2A2426', LINE = 'FFE4E1DC', SOFT = 'FFF7F2F2', BAND = 'FFFAFAF9'
const INR = '"₹"#,##0.00;[Red]-"₹"#,##0.00', KM = '#,##0.0', INT = '#,##0'
const REVIEW = { pending: 'Pending', verified: 'Verified', flagged: 'Flagged', rejected: 'Rejected' }
const ist = (ts) => ts ? new Date(new Date(ts).getTime() + 5.5 * 36e5) : null           // shows IST wall time in Excel
const isoDate = (iso) => iso ? new Date(iso + 'T00:00:00Z') : null
const time = (ts) => ts ? new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : ''
const istDay = (ts) => ts ? isoDate(ist(ts).toISOString().slice(0, 10)) : null  // calendar date in IST
const n = (v) => v == null ? null : Number(v)

// ExcelJS is a vendored script, loaded the first time someone downloads
function loadExcelJS() {
  if (window.ExcelJS) return Promise.resolve(window.ExcelJS)
  return new Promise((resolve, reject) => {
    const el = document.createElement('script')
    el.src = '/static/kwd/vendor/exceljs.min.js'
    el.onload = () => resolve(window.ExcelJS)
    el.onerror = () => reject(new Error('Could not load the Excel library.'))
    document.head.appendChild(el)
  })
}

async function all(q) {
  // page through results (PostgREST returns 1000 rows per request by default)
  const out = []
  for (let from = 0; ; from += 1000) {
    const { data, error } = await q().range(from, from + 999)
    if (error) throw new Error(error.message)
    out.push(...data)
    if (data.length < 1000) return out
  }
}

export async function fetchReport({ from, to, staffIds }) {
  const start = istStartISO(from), end = istStartISO(addDays(to, 1))
  const only = (q, col) => staffIds ? q.in(col, staffIds) : q
  const monthFrom = from.slice(0, 8) + '01'
  const [people, days, visits, fus, opps, pays, evs] = await Promise.all([
    all(() => only(supabase.from('profiles').select('id, full_name, email, phone, role, manager_id, user_districts(districts(name))').order('full_name'), 'id')),
    all(() => only(supabase.from('field_days').select('*, expense_items(*)').gte('day', from).lte('day', to).order('day'), 'tso_id')),
    all(() => only(supabase.from('visits')
      .select('id, tso_id, task_id, check_in_at, check_out_at, distance_from_office_m, gps_accuracy_m, details_at, discussion, outcome, interest_level, next_followup_on, fraud_flags, zm_status, zm_remark, zm_reviewed_at, ho_signed_at, ho_remark, lsgds(name, type, districts(name)), visit_contacts(contacts(name, designation, phone, verified_at))')
      .gte('check_in_at', start).lt('check_in_at', end).order('check_in_at'), 'tso_id')),
    all(() => only(supabase.from('followups').select('id, assigned_to, due_on, mode, notes, done_at, done_note, lsgds(name, districts(name)), contacts(name, phone)')
      .gte('due_on', from).lte('due_on', to).order('due_on'), 'assigned_to')),
    all(() => only(supabase.from('opportunities').select('owner_id, stage, expected_units, expected_value, probability, expected_close, work_order_no, updated_at, lsgds(name, type, districts(name))')
      .eq('financial_year', financialYear(to)).order('updated_at', { ascending: false }), 'owner_id')),
    all(() => only(supabase.from('expense_payments').select('*').gte('month', monthFrom).lte('month', to).order('month'), 'tso_id')),
    all(() => supabase.from('claim_events')
      .select('id, at, event, amount, note, actor:profiles!claim_events_actor_fkey(full_name), day:field_days!claim_events_day_id_fkey(day, tso_id)')
      .gte('at', start).lt('at', end).order('at')),
  ])
  const events = staffIds ? evs.filter((e) => staffIds.includes(e.day?.tso_id)) : evs
  return { from, to, people, days, visits, fus, opps, pays, events }
}

export async function buildWorkbook(data, { title, by }) {
  const ExcelJS = await loadExcelJS()
  const { from, to, people, days, visits, fus, opps, pays = [], events = [] } = data
  const name = Object.fromEntries(people.map((p) => [p.id, p.full_name || p.email]))
  const today = istDate()

  const wb = new ExcelJS.Workbook()
  wb.creator = 'Scrappy Field'; wb.created = new Date(); wb.company = 'Scrappy Innovations'

  // ---------- helpers
  function sheet(label, cols, rows, { totals = [], banner } = {}) {
    const ws = wb.addWorksheet(label, { properties: { tabColor: { argb: OX } }, pageSetup: { orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0, paperSize: 9 } })
    let r = 1
    ws.getCell(r, 1).value = banner || title
    ws.getCell(r, 1).font = { name: 'Calibri', size: 14, bold: true, color: { argb: OX } }
    r++
    ws.getCell(r, 1).value = `${label} · ${fmt(from)} to ${fmt(to)} · generated ${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST by ${by}`
    ws.getCell(r, 1).font = { size: 9, color: { argb: 'FF6B6563' } }
    r += 2
    const head = ws.getRow(r)
    cols.forEach((c, i) => {
      const cell = head.getCell(i + 1)
      cell.value = c.h
      cell.font = { bold: true, color: { argb: 'FFFFFFFF' } }
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: OX } }
      cell.alignment = { vertical: 'middle', horizontal: c.num ? 'right' : 'left', wrapText: true }
      cell.border = { bottom: { style: 'thin', color: { argb: INK } } }
      ws.getColumn(i + 1).width = c.w || 14
      if (c.fmt) ws.getColumn(i + 1).numFmt = c.fmt
    })
    head.height = 30
    const headRow = r
    rows.forEach((row, k) => {
      const xr = ws.getRow(++r)
      cols.forEach((c, i) => {
        const cell = xr.getCell(i + 1)
        cell.value = row[i] ?? null
        if (c.fmt) cell.numFmt = c.fmt
        cell.alignment = { vertical: 'top', wrapText: !!c.wrap, horizontal: c.num ? 'right' : undefined }
        if (k % 2) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BAND } }
        cell.border = { bottom: { style: 'hair', color: { argb: LINE } } }
      })
    })
    if (rows.length && totals.length) {
      const tr = ws.getRow(++r)
      tr.getCell(1).value = 'Total'
      totals.forEach((ci) => {
        const L = ws.getColumn(ci + 1).letter
        tr.getCell(ci + 1).value = { formula: `SUBTOTAL(9,${L}${headRow + 1}:${L}${r - 1})` }
        tr.getCell(ci + 1).numFmt = cols[ci].fmt
      })
      tr.eachCell({ includeEmpty: true }, (cell) => {
        cell.font = { bold: true }
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: SOFT } }
        cell.border = { top: { style: 'thin', color: { argb: INK } } }
      })
    }
    if (!rows.length) ws.getCell(r + 1, 1).value = 'No records in this period.'
    ws.views = [{ state: 'frozen', ySplit: headRow, xSplit: 1 }]
    if (rows.length) ws.autoFilter = { from: { row: headRow, column: 1 }, to: { row: headRow + rows.length, column: cols.length } }
    return ws
  }
  const fmt = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
  const D = { fmt: 'dd-mmm-yyyy' }, DT = { fmt: 'dd-mmm-yyyy hh:mm' }

  // ---------- Summary per person
  const staff = people.filter((p) => days.some((d) => d.tso_id === p.id) || visits.some((v) => v.tso_id === p.id) || fus.some((f) => f.assigned_to === p.id))
  const summary = staff.map((p) => {
    const ds = days.filter((d) => d.tso_id === p.id)
    const vs = visits.filter((v) => v.tso_id === p.id)
    const fs = fus.filter((f) => f.assigned_to === p.id)
    const sum = (k, arr = ds) => arr.reduce((s, d) => s + Number(d[k] || 0), 0)
    const approved = ds.filter((d) => ['zm_approved', 'ho_approved', 'paid'].includes(d.status))
    return [
      p.full_name || p.email, { tso: 'TSO', zonal_manager: 'Zonal Manager', head_office: 'Head Office' }[p.role],
      p.user_districts.map((u) => u.districts?.name).join(', '), name[p.manager_id] || '',
      ds.length, new Set(vs.map((v) => ist(v.check_in_at).toISOString().slice(0, 10))).size, vs.length,
      vs.filter((v) => v.zm_status === 'verified').length, vs.filter((v) => v.fraud_flags.length).length, vs.filter((v) => v.zm_status === 'rejected').length,
      new Set(vs.map((v) => v.lsgds?.name)).size,
      new Set(vs.flatMap((v) => v.visit_contacts.map((c) => c.contacts?.phone || c.contacts?.name))).size,
      fs.filter((f) => f.done_at).length, fs.filter((f) => !f.done_at && f.due_on < today).length,
      sum('ta_km'), ds.reduce((s, d) => s + Number(d.gps_km || 0), 0),
      sum('ta_amount'), sum('da_amount'), sum('lodging_amount'), sum('other_amount'), sum('total_claimed'),
      approved.reduce((s, d) => s + Number(d.approved_amount ?? 0), 0),
      ds.filter((d) => d.status === 'paid').reduce((s, d) => s + Number(d.approved_amount || 0), 0),
      ds.filter((d) => d.status === 'rejected').reduce((s, d) => s + Number(d.total_claimed), 0),
      ds.reduce((s, d) => s + d.flags.filter((f) => !['sunday', 'late_claim'].includes(f)).length, 0),
    ]
  })
  sheet('Summary', [
    { h: 'Name', w: 22 }, { h: 'Role', w: 14 }, { h: 'Districts', w: 22, wrap: true }, { h: 'Reports to', w: 18 },
    { h: 'Days started', num: 1, fmt: INT, w: 9 }, { h: 'Days with visits', num: 1, fmt: INT, w: 9 }, { h: 'Visits', num: 1, fmt: INT, w: 8 },
    { h: 'Verified', num: 1, fmt: INT, w: 9 }, { h: 'System-flagged', num: 1, fmt: INT, w: 9 }, { h: 'Rejected', num: 1, fmt: INT, w: 9 },
    { h: 'LSGDs covered', num: 1, fmt: INT, w: 9 }, { h: 'People met', num: 1, fmt: INT, w: 9 },
    { h: 'Follow-ups done', num: 1, fmt: INT, w: 10 }, { h: 'Follow-ups overdue', num: 1, fmt: INT, w: 10 },
    { h: 'KM claimed', num: 1, fmt: KM, w: 10 }, { h: 'GPS route KM', num: 1, fmt: KM, w: 10 },
    { h: 'TA ₹', num: 1, fmt: INR, w: 13 }, { h: 'Allowance (DA) ₹', num: 1, fmt: INR, w: 12 }, { h: 'Lodging ₹', num: 1, fmt: INR, w: 12 }, { h: 'Other ₹', num: 1, fmt: INR, w: 12 },
    { h: 'Total requested ₹', num: 1, fmt: INR, w: 14 }, { h: 'Approved ₹', num: 1, fmt: INR, w: 14 }, { h: 'Paid ₹', num: 1, fmt: INR, w: 14 },
    { h: 'Rejected ₹', num: 1, fmt: INR, w: 13 }, { h: 'Expense flags', num: 1, fmt: INT, w: 9 },
  ], summary, { totals: [4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] })

  // ---------- Monthly statement (TA/DA is paid monthly)
  const monthRows = []
  const keys = [...new Set(days.map((d) => d.tso_id + '|' + d.day.slice(0, 7)))].sort((a, b) => a.split('|')[1].localeCompare(b.split('|')[1]) || (name[a.split('|')[0]] || '').localeCompare(name[b.split('|')[0]] || ''))
  for (const k of keys) {
    const [id, ym] = k.split('|')
    const ds = days.filter((d) => d.tso_id === id && d.day.startsWith(ym))
    const s = (arr, f) => arr.reduce((t, d) => t + Number(f(d) || 0), 0)
    const pp = pays.filter((p) => p.tso_id === id && p.month.startsWith(ym))
    const approved = ds.filter((d) => ['ho_approved', 'paid'].includes(d.status))
    monthRows.push([
      new Date(ym + '-01T00:00:00').toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }), name[id], ds.length,
      ds.filter((d) => d.visits_count > 0).length, s(ds, (d) => d.ta_km),
      s(ds, (d) => d.ta_amount), s(ds, (d) => d.da_amount), s(ds, (d) => d.lodging_amount), s(ds, (d) => d.other_amount),
      s(ds, (d) => d.total_claimed), s(approved, (d) => d.approved_amount),
      s(ds.filter((d) => d.status === 'rejected'), (d) => d.total_claimed),
      s(ds.filter((d) => ['open', 'submitted', 'zm_approved'].includes(d.status)), (d) => d.total_claimed),
      s(pp, (p) => p.amount), s(ds.filter((d) => d.status === 'ho_approved'), (d) => d.approved_amount),
      pp.map((p) => p.paid_ref).join(', '), pp.length ? istDay(pp[pp.length - 1].paid_at) : null,
    ])
  }
  sheet('Monthly statement', [
    { h: 'Month', w: 11 }, { h: 'Name', w: 22 }, { h: 'Days requested', num: 1, fmt: INT, w: 9 }, { h: 'Days with visits (DA)', num: 1, fmt: INT, w: 10 },
    { h: 'KM paid', num: 1, fmt: KM, w: 9 }, { h: 'TA ₹', num: 1, fmt: INR, w: 13 }, { h: 'Allowance (DA) ₹', num: 1, fmt: INR, w: 12 },
    { h: 'Lodging ₹', num: 1, fmt: INR, w: 12 }, { h: 'Other ₹', num: 1, fmt: INR, w: 12 }, { h: 'Requested ₹', num: 1, fmt: INR, w: 14 },
    { h: 'Approved ₹', num: 1, fmt: INR, w: 14 }, { h: 'Rejected ₹', num: 1, fmt: INR, w: 13 }, { h: 'Awaiting approval ₹', num: 1, fmt: INR, w: 14 },
    { h: 'Paid ₹', num: 1, fmt: INR, w: 14 }, { h: 'Approved, not yet paid ₹', num: 1, fmt: INR, w: 15 }, { h: 'Payment ref', w: 16 }, { h: 'Paid on', w: 12, ...D },
  ], monthRows, { totals: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] })

  // ---------- Daily register (attendance + TA/DA)
  sheet('Daily TA-DA register', [
    { h: 'Date', w: 12, ...D }, { h: 'Day', w: 6 }, { h: 'Name', w: 20 }, { h: 'Travel', w: 14 }, { h: 'Vehicle', w: 13 },
    { h: 'Start', w: 7 }, { h: 'End', w: 7 }, { h: 'Start odo', num: 1, fmt: INT, w: 10 }, { h: 'End odo', num: 1, fmt: INT, w: 10 },
    { h: 'Odo KM', num: 1, fmt: KM, w: 8 }, { h: 'GPS KM', num: 1, fmt: KM, w: 8 }, { h: 'Visits', num: 1, fmt: INT, w: 7 },
    { h: 'LSGDs visited', w: 28, wrap: true }, { h: 'Night halt', w: 14 },
    { h: 'TA ₹', num: 1, fmt: INR, w: 12 }, { h: 'Allowance (DA) ₹', num: 1, fmt: INR, w: 11 }, { h: 'Lodging ₹', num: 1, fmt: INR, w: 11 }, { h: 'Other ₹', num: 1, fmt: INR, w: 11 },
    { h: 'Requested ₹', num: 1, fmt: INR, w: 13 }, { h: 'Approved ₹', num: 1, fmt: INR, w: 13 },
    { h: 'Status', w: 16 }, { h: 'ZM remark', w: 22, wrap: true }, { h: 'HO remark', w: 22, wrap: true }, { h: 'Paid on', w: 12, ...D }, { h: 'Payment ref', w: 14 },
    { h: 'System flags', w: 36, wrap: true }, { h: 'Under HO review', w: 10 },
  ], days.map((d) => {
    const vs = visits.filter((v) => v.tso_id === d.tso_id && ist(v.check_in_at).toISOString().slice(0, 10) === d.day)
    return [
      isoDate(d.day), new Date(d.day + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short' }), name[d.tso_id],
      TRAVEL_MODES[d.travel_mode].short, d.vehicle_no || '', time(d.start_at), time(d.end_at), d.start_odo, d.end_odo,
      n(d.odo_km), n(d.gps_km), d.visits_count, vs.map((v) => v.lsgds?.name).join(', '),
      d.night_halt ? `Yes${d.halt_place ? ' · ' + d.halt_place : ''}` : 'No',
      n(d.ta_amount), n(d.da_amount), n(d.lodging_amount), n(d.other_amount), n(d.total_claimed), n(d.approved_amount),
      CLAIM_STATUS[d.status][0], d.zm_remark || '', d.ho_remark || '', istDay(d.paid_at), d.paid_ref || '',
      d.flags.map(flagText).join('; '), d.ho_flag ? 'Yes' : '',
    ]
  }), { totals: [9, 10, 11, 14, 15, 16, 17, 18, 19] })

  // ---------- Request history (who did what, when)
  const EVL = { started: 'Day started', ended: 'Day ended', bill_added: 'Bill added', bill_removed: 'Bill removed', submitted: 'Request submitted',
    zm_verified: 'Verified by Zonal Manager', sent_back: 'Sent back', rejected: 'Rejected', ho_approved: 'Approved by Head Office', paid: 'Paid',
    ho_flagged: 'Flagged by Head Office', ho_unflagged: 'Flag removed by Head Office' }
  sheet('Request history', [
    { h: 'When', w: 17, ...DT }, { h: 'Request date', w: 12, ...D }, { h: 'Name', w: 20 }, { h: 'What happened', w: 28 }, { h: 'By', w: 20 },
    { h: 'Amount ₹', num: 1, fmt: INR, w: 13 }, { h: 'Note', w: 48, wrap: true },
  ], events.map((e) => [ist(e.at), isoDate(e.day?.day), name[e.day?.tso_id] || '', EVL[e.event] || e.event, e.actor?.full_name || 'System', n(e.amount), e.note || '']))

  // ---------- Bills / expense lines
  const items = days.flatMap((d) => d.expense_items.map((i) => ({ ...i, d })))
  sheet('Expense bills', [
    { h: 'Date', w: 12, ...D }, { h: 'Name', w: 20 }, { h: 'Category', w: 20 }, { h: 'Head', w: 9 }, { h: 'Description', w: 30, wrap: true },
    { h: 'From', w: 14 }, { h: 'To', w: 14 }, { h: 'Bill no', w: 12 }, { h: 'Bill photo', w: 10 }, { h: 'Amount ₹', num: 1, fmt: INR, w: 12 },
    { h: 'Request status', w: 16 }, { h: 'Flags', w: 24, wrap: true },
  ], items.map((i) => [
    isoDate(i.d.day), name[i.d.tso_id], CATEGORIES[i.category].label, CATEGORIES[i.category].group, i.description,
    i.from_place || '', i.to_place || '', i.bill_no || '', i.bill_path ? 'Yes' : 'No', n(i.amount),
    CLAIM_STATUS[i.d.status][0], i.flags.map(flagText).join('; '),
  ]), { totals: [9] })

  // ---------- Visits
  sheet('Visits', [
    { h: 'Check-in', w: 17, ...DT }, { h: 'Out', w: 7 }, { h: 'Name', w: 20 }, { h: 'District', w: 14 }, { h: 'LSGD', w: 22 }, { h: 'Type', w: 16 },
    { h: 'Planned', w: 8 }, { h: 'From office (m)', num: 1, fmt: INT, w: 10 }, { h: 'People met', w: 28, wrap: true }, { h: 'Phones', w: 16, wrap: true },
    { h: 'Details added', w: 17, ...DT }, { h: 'Discussion', w: 44, wrap: true }, { h: 'Outcome', w: 24, wrap: true }, { h: 'Interest', w: 9 }, { h: 'Next follow-up', w: 12, ...D },
    { h: 'System flags', w: 24, wrap: true }, { h: 'ZM review', w: 10 }, { h: 'ZM remark', w: 22, wrap: true }, { h: 'HO signed', w: 12, ...D },
  ], visits.map((v) => [
    ist(v.check_in_at), time(v.check_out_at), name[v.tso_id], v.lsgds?.districts?.name, v.lsgds?.name, LSGD_TYPES[v.lsgds?.type],
    v.task_id ? 'Yes' : 'No', v.distance_from_office_m == null ? null : Math.round(v.distance_from_office_m),
    v.visit_contacts.filter((c) => c.contacts).map((c) => `${c.contacts.name} (${c.contacts.designation})`).join('\n'),
    v.visit_contacts.map((c) => c.contacts?.phone).filter(Boolean).join('\n'),
    ist(v.details_at), v.details_at ? v.discussion || '' : '(details not added yet)', v.outcome || '', v.interest_level ? INTEREST[v.interest_level - 1] : '', isoDate(v.next_followup_on),
    v.fraud_flags.map((f) => FLAG_TEXT[f] || f).join('; '), REVIEW[v.zm_status], v.zm_remark || '',
    istDay(v.ho_signed_at),
  ]))

  // ---------- Follow-ups
  sheet('Follow-ups', [
    { h: 'Due', w: 12, ...D }, { h: 'Name', w: 20 }, { h: 'LSGD', w: 22 }, { h: 'District', w: 14 }, { h: 'How', w: 10 }, { h: 'Contact', w: 22 },
    { h: 'What to do', w: 34, wrap: true }, { h: 'Status', w: 10 }, { h: 'Done on', w: 12, ...D }, { h: 'Result', w: 34, wrap: true },
  ], fus.map((f) => [
    isoDate(f.due_on), name[f.assigned_to], f.lsgds?.name || '', f.lsgds?.districts?.name || '', f.mode,
    f.contacts ? `${f.contacts.name}${f.contacts.phone ? ' · ' + f.contacts.phone : ''}` : '',
    f.notes || '', f.done_at ? 'Done' : f.due_on < today ? 'Overdue' : 'Open',
    istDay(f.done_at), f.done_note || '',
  ]))

  // ---------- Pipeline
  sheet(`Pipeline ${financialYear(to)}`, [
    { h: 'LSGD', w: 24 }, { h: 'Type', w: 16 }, { h: 'District', w: 14 }, { h: 'Owner', w: 20 }, { h: 'Stage', w: 20 },
    { h: 'Units', num: 1, fmt: INT, w: 8 }, { h: 'Value ₹', num: 1, fmt: INR, w: 15 }, { h: 'Chance %', num: 1, fmt: INT, w: 9 },
    { h: 'Likely ₹', num: 1, fmt: INR, w: 15 }, { h: 'Expected close', w: 12, ...D }, { h: 'Work order', w: 14 }, { h: 'Updated', w: 12, ...D },
  ], opps.map((o) => [
    o.lsgds?.name, LSGD_TYPES[o.lsgds?.type], o.lsgds?.districts?.name, name[o.owner_id] || '', stageLabel(o.stage),
    o.expected_units, n(o.expected_value), o.probability, Number(o.expected_value) * o.probability / 100,
    isoDate(o.expected_close), o.work_order_no || '', istDay(o.updated_at),
  ]), { totals: [5, 6, 8] })

  return wb
}

export async function downloadReport({ from, to, staffIds, title, by, fileLabel }) {
  const data = await fetchReport({ from, to, staffIds })
  const wb = await buildWorkbook(data, { title, by })
  const buf = await wb.xlsx.writeBuffer()
  const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `Scrappy-${fileLabel}-${from}-to-${to}.xlsx`.replace(/[^\w.-]+/g, '-')
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 30000)
  return { visits: data.visits.length, days: data.days.length }
}
