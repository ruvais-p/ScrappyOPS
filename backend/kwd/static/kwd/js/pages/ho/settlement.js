/* Head Office: TA/DA is paid once a month per person, for days approved in a month that has ended. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, SectionHead, Avatar } from '../../ui.js'
import { istDate, addDays, fmtINR, fmtDate } from '../../lib.js'
import { Sheet, errLine } from '../../kit.js'

export const monthLabel = (iso) => new Date(iso.slice(0, 7) + '-01T00:00:00').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })
const monthKey = (day) => day.slice(0, 7) + '-01'
const nextMonth = (m) => { const [y, mo] = m.split('-').map(Number); return new Date(Date.UTC(y, mo, 1)).toISOString().slice(0, 10) }
const PENDING = ['submitted', 'zm_approved']

function build(S, today) {
  // one line per person per month that has approved days waiting for payment
  const groups = {}
  for (const d of S.days) {
    const k = d.tso_id + '|' + monthKey(d.day)
    const g = groups[k] = groups[k] || { key: k, tso_id: d.tso_id, person: d.person, month: monthKey(d.day), ready: [], held: 0, pending: 0, notSubmitted: 0 }
    if (d.status === 'ho_approved') { if (d.ho_flag) g.held++; else g.ready.push(d) }
    else if (PENDING.includes(d.status)) g.pending++
    else if (d.end_at) g.notSubmitted++
  }
  return Object.values(groups).filter((g) => g.ready.length || g.held)
    .map((g) => ({ ...g, amount: g.ready.reduce((s, d) => s + Number(d.approved_amount), 0), payableFrom: nextMonth(g.month) }))
    .sort((a, b) => a.month.localeCompare(b.month) || ((a.person && a.person.full_name) || '').localeCompare((b.person && b.person.full_name) || ''))
}

export default {
  state: { days: null, payments: [], err: '', paying: null, ref: '', note: '', busy: false, perr: '' },
  async init() { await this.actions.reload.call(this) },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.days) return Loading()
    const today = istDate()
    const lines = build(S, today)
    const due = lines.filter((l) => l.payableFrom <= today)
    const l = S.paying
    return html`<div class="notice small">TA/DA is paid monthly. Once a month is over, pay each person's approved days in one payment with one UTR. Days approved later are paid in a later settlement.</div>
      ${SectionHead({ title: 'Ready to pay', count: due.length ? fmtINR(due.reduce((s, x) => s + x.amount, 0)) : 0 })}
      ${lines.length === 0 ? Empty('No approved requests waiting for payment.') : html`<ul class="list">${lines.map((x) => html`<li class="item settle-item">
        ${Avatar(x.person && x.person.full_name, 34)}
        <div class="grow">
          <div class="title">${(x.person && (x.person.full_name || x.person.email))} · ${monthLabel(x.month)}</div>
          <div class="muted small">${x.ready.length} approved day${x.ready.length === 1 ? '' : 's'}${x.held ? ` · ${x.held} on hold (flagged by Head Office)` : ''}${x.pending ? ` · ${x.pending} still being approved` : ''}${x.notSubmitted ? ` · ${x.notSubmitted} not submitted` : ''}</div>
        </div>
        <div class="amt"><b>${fmtINR(x.amount)}</b>
          ${!x.ready.length ? html`<span class="pill bad">On hold</span>` : x.payableFrom <= today ? html`<button class="btn sm" data-act="pay" data-key="${x.key}">Pay</button>` : html`<span class="pill">Payable from ${fmtDate(x.payableFrom)}</span>`}
        </div></li>`)}</ul>`}

      ${SectionHead({ title: 'Payments made', count: S.payments.length })}
      ${S.payments.length === 0 ? html`<p class="muted small">No payments yet.</p>` : html`<div class="table-wrap"><table>
        <thead><tr><th>Month</th><th>Staff</th><th class="num">Days</th><th class="num">Amount</th><th>Reference</th><th>Paid on</th></tr></thead>
        <tbody>${S.payments.map((p) => html`<tr><td>${monthLabel(p.month)}</td><td>${p.person && p.person.full_name}</td><td class="num">${p.days}</td>
          <td class="num">${fmtINR(p.amount)}</td><td>${p.paid_ref}${p.note ? html`<div class="muted small">${p.note}</div>` : ''}</td><td>${fmtDate(p.paid_at)}</td></tr>`)}</tbody></table></div>`}
      ${l ? Sheet({ title: `Pay ${l.person && l.person.full_name}`, close: 'closePay', body: html`
        <div class="claim-sum card">
          <div class="sum-row"><span>Month</span><b>${monthLabel(l.month)}</b></div>
          <div class="sum-row"><span>Approved days</span><b>${l.ready.length}</b></div>
          <div class="sum-row total"><span>Amount to pay</span><b>${fmtINR(l.amount)}</b></div>
        </div>
        ${l.held > 0 ? html`<p class="notice warn small"><span>${l.held} day${l.held > 1 ? 's are' : ' is'} on hold (flagged by Head Office) and will not be paid now.</span></p>` : ''}
        ${l.pending > 0 ? html`<p class="notice warn small">${l.pending} more day${l.pending > 1 ? 's are' : ' is'} still being approved for this month. You can pay those in a later settlement.</p>` : ''}
        <label>Payment reference (UTR / voucher no)<input data-bind="ref" data-live value="${S.ref}"></label>
        <label>Note (optional)<input data-bind="note" value="${S.note}" placeholder="e.g. Bank transfer, SBI"></label>
        <p class="small muted">Pay the amount from your bank first, then record it here. This can't be undone.</p>
        ${errLine(S.perr)}
        <button class="btn primary block" ${S.busy || !S.ref.trim() ? raw('disabled') : ''} data-act="confirmPay">${S.busy ? 'Saving…' : `Record payment of ${fmtINR(l.amount)}`}</button>` }) : ''}`
  },
  actions: {
    async reload() {
      const today = istDate()
      const since = addDays(today.slice(0, 8) + '01', -400)
      const [d, p] = await Promise.all([
        supabase.from('field_days').select('id, tso_id, day, status, end_at, ho_flag, approved_amount, total_claimed, person:profiles!field_days_tso_id_fkey(full_name, email)')
          .gte('day', since).in('status', ['open', 'submitted', 'zm_approved', 'ho_approved']).order('day'),
        supabase.from('expense_payments').select('*, person:profiles!expense_payments_tso_id_fkey(full_name, email)').order('paid_at', { ascending: false }).limit(60),
      ])
      const e = d.error || p.error
      if (e) return this.set({ err: errText(e) })
      this.set({ days: d.data, payments: p.data })
    },
    pay(el) { this.set({ paying: build(this.S, istDate()).find((x) => x.key === el.dataset.key), ref: '', note: '', perr: '' }) },
    closePay() { this.set({ paying: null }) },
    async confirmPay() {
      const S = this.S, line = S.paying
      this.set({ busy: true, perr: '' })
      const { data, error } = await supabase.rpc('pay_month', { p_tso: line.tso_id, p_month: line.month, p_ref: S.ref.trim(), p_note: S.note.trim() || null })
      this.set({ busy: false })
      if (error) return this.set({ perr: errText(error) })
      toast(`Paid ${fmtINR((data && data.amount) ?? line.amount)} to ${line.person && line.person.full_name}`)
      this.set({ paying: null })
      await this.actions.reload.call(this)
    },
  },
}
