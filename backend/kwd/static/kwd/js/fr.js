/* Franchise module: labels, small helpers and shared data loaders. */
import { supabase } from './core.js'
import { istDate, addDays } from './lib.js'

export const CUSTOMER_TYPES = { private: 'Private (home / person)', lsgd: 'LSGD', institution: 'Institution', business: 'Business / shop' }
export const customerShort = { private: 'Private', lsgd: 'LSGD', institution: 'Institution', business: 'Business' }

export const LEAD_STATUS = {
  new: { label: 'New', tone: 'brand' }, contacted: { label: 'Contacted', tone: '' },
  presentation_set: { label: 'Presentation set', tone: '' }, negotiating: { label: 'Negotiating', tone: 'warn' },
  won: { label: 'Sale closed', tone: 'ok' }, lost: { label: 'Lost', tone: 'bad' },
}
export const LEAD_OPEN = ['new', 'contacted', 'presentation_set', 'negotiating']

export const VENUES = { lsgd: 'LSGD office / hall', private: 'Private (home / site)', institution: 'Institution (school, hospital…)', other: 'Other' }
export const OUTCOMES = { interested: 'Interested', follow_up: 'Needs a follow-up', order_received: 'Order received', not_interested: 'Not interested' }
export const OUTCOME_TONE = { interested: 'ok', follow_up: 'warn', order_received: 'ok', not_interested: 'bad' }

export const DELIVERY = { pending: 'Not dispatched', dispatched: 'Dispatched', delivered: 'Delivered' }
export const INSTALL = { not_needed: 'No installation', pending: 'Installation pending', scheduled: 'Installation scheduled', installed: 'Installed' }
export const PAYMENT = { pending: 'Unpaid', partial: 'Part paid', paid: 'Paid' }
export const MOVE_KIND = {
  opening: 'Opening stock', received: 'Received from Head Office', sale: 'Sold', sale_cancel: 'Sale cancelled',
  damaged: 'Damaged or lost', returned: 'Returned to Head Office', count_adjust: 'Stock count correction',
}
export const SALE_FLAG = { backdated: 'Entered for an earlier date', below_list_price: 'Price well below list' }

export const monthStart = (iso = istDate()) => iso.slice(0, 8) + '01'
export const addMonths = (iso, n) => {
  const d = new Date(iso + 'T00:00:00Z'); d.setUTCMonth(d.getUTCMonth() + n, 1)
  return d.toISOString().slice(0, 10)
}
export const monthName = (iso, short) => new Date(iso + 'T00:00:00+05:30')
  .toLocaleDateString('en-IN', { month: short ? 'short' : 'long', year: 'numeric', timeZone: 'Asia/Kolkata' })

export const fmtWhen = (ts) => {
  const d = new Date(ts)
  const date = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }).format(d).replace(',', '')
  return `${date}, ${d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })}`
}
// <input type="datetime-local"> value for an ISO timestamp (IST) and back
export const toLocalInput = (ts) => new Date(new Date(ts).getTime() + 5.5 * 36e5).toISOString().slice(0, 16)
export const fromLocalInput = (v) => new Date(v + ':00+05:30').toISOString()
export const daysSince = (ts) => Math.floor((Date.now() - new Date(ts).getTime()) / 864e5)

/** All products, and a lookup by id. */
export async function loadProducts() {
  const { data } = await supabase.from('fr_products').select('*').order('sort')
  const products = data || []
  return { products, byId: Object.fromEntries(products.map((p) => [p.id, p])) }
}

export async function loadDistricts() {
  const { data } = await supabase.from('districts').select('id, name').order('name')
  return data || []
}

// Achievement of one franchise (or all, when franchiseId is null) for one month.
// sold = v_fr_sold rows, targets = fr_targets rows
export function achievement(sold, targets, month, franchiseId = null) {
  const inMonth = (r) => r.month === month && (!franchiseId || r.franchise_id === franchiseId)
  const S = sold.filter(inMonth)
  const T = targets.filter(inMonth)
  const overall = T.filter((t) => !t.product_id)
  const units = S.reduce((a, r) => a + r.qty, 0)
  const value = S.reduce((a, r) => a + Number(r.line_total), 0)
  // Head Office sets targets per product; the franchise's unit target is their total (an older overall target still counts if one was saved)
  const productUnits = T.filter((t) => t.product_id).reduce((a, t) => a + (t.target_units || 0), 0)
  const tUnits = overall.reduce((a, t) => a + (t.target_units || 0), 0) || productUnits
  const tValue = overall.reduce((a, t) => a + Number(t.target_amount || 0), 0)
  const perProduct = {}
  S.forEach((r) => { (perProduct[r.product_id] = perProduct[r.product_id] || { units: 0, value: 0, target: 0 }); perProduct[r.product_id].units += r.qty; perProduct[r.product_id].value += Number(r.line_total) })
  T.filter((t) => t.product_id).forEach((t) => { (perProduct[t.product_id] = perProduct[t.product_id] || { units: 0, value: 0, target: 0 }).target += t.target_units || 0 })
  const pct = (a, b) => (b > 0 ? Math.round((100 * a) / b) : null)
  return { units, value, tUnits, tValue, pctUnits: pct(units, tUnits), pctValue: pct(value, tValue), perProduct }
}

export const itemsText = (items, byId) => (items || []).map((i) => `${i.qty} × ${(byId[i.product_id] || {}).name || 'Item'}`).join(', ')

export { istDate, addDays }
