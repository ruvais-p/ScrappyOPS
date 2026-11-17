/* Telecalling module: labels and small helpers shared by the sales-leads, franchise-leads and follow-up screens. */

export const TC_STATUS = {
  new: { label: 'New', tone: 'brand' }, contacted: { label: 'Contacted', tone: '' },
  interested: { label: 'Interested', tone: 'ok' }, not_interested: { label: 'Not interested', tone: 'bad' },
  converted: { label: 'Converted', tone: 'ok' }, lost: { label: 'Lost', tone: 'bad' },
}
export const TC_OPEN = ['new', 'contacted', 'interested', 'not_interested']

export const TC_TEMP = {
  hot: { label: 'Hot', tone: 'bad' }, warm: { label: 'Warm', tone: 'warn' }, cold: { label: 'Cold', tone: '' },
}
export const TC_TEMP_RANK = { hot: 0, warm: 1, cold: 2 }
export const tempSort = (a, b) => (TC_TEMP_RANK[a.temperature] ?? 3) - (TC_TEMP_RANK[b.temperature] ?? 3)

export const KIND_LABEL = { sales: 'Sales lead', franchise: 'Franchise lead' }

export const daysSince = (ts) => Math.floor((Date.now() - new Date(ts).getTime()) / 864e5)
