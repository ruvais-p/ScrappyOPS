import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Empty, Icon, PageHead } from '../../../ui.js'
import { fmtINR, fmtDate } from '../../../lib.js'
import { Sheet, adminUsers, errLine } from '../../../kit.js'
import { achievement, monthStart } from '../../../fr.js'

function makePassword() {
  const a = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  const r = crypto.getRandomValues(new Uint32Array(10))
  return 'Sc-' + Array.from(r, (x) => a[x % a.length]).join('')
}
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`

function formSheet(S, districts) {
  const f = S.edit, v = S.v, isNew = !f.id
  if (S.done) {
    return Sheet({ title: 'Done', close: 'doneClose', body: html`<pre class="card" style="white-space:pre-wrap;font:500 1rem var(--body)">${S.done}</pre>
      <p class="muted small">This password is shown only once.</p>
      <div class="row wrap"><button class="btn" data-act="copy">Copy</button><button class="btn primary" data-act="doneClose">Close</button></div>` })
  }
  return Sheet({ title: isNew ? 'New franchisee' : `Edit ${f.business_name}`, close: 'closeEdit', body: html`
    <label>Business name<input data-bind="v.business_name" value="${v.business_name}"></label>
    <label>Owner’s full name<input data-bind="v.full_name" value="${v.full_name}"></label>
    <div class="grid2">
      <label>Email (login)${isNew ? html`<input type="email" data-bind="v.email" value="${v.email}">` : html`<input value="${v.email}" disabled>`}</label>
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="v.phone" value="${v.phone}" placeholder="10 digits"></label>
    </div>
    <div class="grid2">
      <label>District<select data-bind="v.district_id"><option value="">Choose…</option>${districts.map((d) => opt(d.id, v.district_id, d.name))}</select></label>
      <label>Territory covered<input data-bind="v.territory" value="${v.territory}" placeholder="e.g. Eranad and Nilambur taluks"></label>
    </div>
    <label>Address<input data-bind="v.address" value="${v.address}"></label>
    <label>GSTIN (optional)<input data-bind="v.gstin" value="${v.gstin}"></label>
    ${isNew ? html`<label>First password<div class="row"><input data-bind="v.password" value="${v.password}" class="grow"><button class="btn sm" data-act="newPw">New</button></div></label>` : ''}
    ${!isNew ? html`<label class="check" style="margin-top:14px"><input type="checkbox" data-bind="v.is_active" ${v.is_active ? raw('checked') : ''}> Franchise is active (untick to switch the login off)</label>` : ''}
    ${errLine(S.err)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : isNew ? 'Create login' : 'Save changes'}</button>
    ${!isNew ? html`<button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="reset">Reset password</button>` : ''}` })
}

export default {
  state: { sold: [], leads: [], edit: null, v: null, err: '', busy: false, done: '' },
  async init() {
    supabase.from('v_fr_sold').select('*').gte('month', monthStart()).then(({ data }) => this.set({ sold: data || [] }))
    supabase.from('fr_leads').select('franchise_id, status').then(({ data }) => this.set({ leads: data || [] }))
  },
  view(S, ctx) {
    const { frs, districts } = ctx.data
    const dName = (id) => (districts.find((d) => d.id === id) || {}).name
    return html`${PageHead({ label: 'Set up', title: 'Franchisees', sub: 'Create a login for each franchise partner, set their territory, and switch them off if they leave.',
        actions: html`<button class="btn primary" data-act="add">${Icon('plus', 18)} New franchisee</button>` })}
      ${frs.length === 0 ? Empty('No franchisees yet.', { action: html`<button class="btn" data-act="add">Add the first franchisee</button>` }) : html`<div class="table-wrap"><table>
        <thead><tr><th>Business</th><th>Owner / login</th><th>District</th><th>Status</th><th class="num">Leads</th><th class="num">Sold this month</th><th>Since</th><th></th></tr></thead>
        <tbody>${frs.map((f) => html`<tr style="${f.is_active ? '' : 'opacity:.6'}">
          <td><b>${f.business_name}</b>${f.territory ? html`<div class="muted small">${f.territory}</div>` : ''}</td>
          <td>${f.profile && f.profile.full_name}<div class="muted small">${f.profile && f.profile.email}${f.profile && f.profile.phone ? ` · ${f.profile.phone}` : ''}</div></td>
          <td>${dName(f.district_id) || '—'}</td>
          <td>${f.is_active ? html`<span class="pill ok">Active</span>` : html`<span class="pill bad">Off</span>`}</td>
          <td class="num">${S.leads.filter((l) => l.franchise_id === f.id).length}</td>
          <td class="num">${fmtINR(achievement(S.sold, [], monthStart(), f.id).value)}</td>
          <td>${fmtDate(f.created_at)}</td>
          <td class="row" style="gap:6px">
            <button class="btn sm" data-act="goto" data-page="leads" data-fid="${f.id}">Leads</button>
            <button class="btn sm" data-act="goto" data-page="sales" data-fid="${f.id}">Sales</button>
            <button class="btn sm" data-act="edit" data-id="${f.id}">Edit</button></td></tr>`)}</tbody></table></div>`}
      ${S.edit ? formSheet(S, districts) : ''}`
  },
  actions: {
    goto(el) { this.ctx.go(el.dataset.page, { franchiseId: el.dataset.fid }) },
    add() { this.set({ edit: {}, done: '', err: '', v: { full_name: '', email: '', phone: '', business_name: '', district_id: '', territory: '', address: '', gstin: '', is_active: true, password: makePassword() } }) },
    edit(el) {
      const f = this.ctx.data.frs.find((x) => x.id === el.dataset.id), p = f.profile || {}
      this.set({ edit: f, done: '', err: '', v: { full_name: p.full_name || '', email: p.email || '', phone: p.phone || '', business_name: f.business_name || '', district_id: f.district_id || '',
        territory: f.territory || '', address: f.address || '', gstin: f.gstin || '', is_active: f.is_active ?? true, password: '' } })
    },
    closeEdit() { this.set({ edit: null }) },
    doneClose() { this.set({ edit: null, done: '' }); this.ctx.data.reload() },
    copy() { if (navigator.clipboard) navigator.clipboard.writeText(this.S.done) },
    newPw() { this.set({ v: { ...this.S.v, password: makePassword() } }) },
    async save() {
      const S = this.S, v = S.v, f = S.edit, isNew = !f.id
      this.set({ err: '' })
      if (!v.full_name.trim()) return this.set({ err: 'Enter the owner’s full name.' })
      if (v.business_name.trim().length < 2) return this.set({ err: 'Enter the business name.' })
      if (isNew && !/^\S+@\S+\.\S+$/.test(v.email.trim())) return this.set({ err: 'Enter a valid email.' })
      if (v.phone && !/^[6-9]\d{9}$/.test(v.phone.replace(/\D/g, '').slice(-10))) return this.set({ err: 'Enter a valid 10-digit mobile number.' })
      if (isNew && v.password.length < 8) return this.set({ err: 'Password must be at least 8 characters.' })
      const profile = {
        role: 'franchisee', full_name: v.full_name.trim(), phone: v.phone ? v.phone.replace(/\D/g, '').slice(-10) : null,
        ...(isNew ? {} : { is_active: v.is_active }),
        franchise: { business_name: v.business_name.trim(), district_id: v.district_id ? Number(v.district_id) : null, territory: v.territory.trim(), address: v.address.trim(), gstin: v.gstin.trim() },
      }
      this.set({ busy: true })
      try {
        if (isNew) {
          await adminUsers({ action: 'create', email: v.email.trim(), password: v.password, full_name: profile.full_name, profile })
          this.set({ done: `Login created for ${v.business_name}. Send these details privately:\n\nEmail: ${v.email.trim().toLowerCase()}\nPassword: ${v.password}` })
        } else {
          await adminUsers({ action: 'update', id: f.user_id, profile })
          toast('Saved'); this.set({ edit: null }); this.ctx.data.reload()
        }
      } catch (e) { this.set({ err: errText(e) }) } finally { this.set({ busy: false }) }
    },
    async reset() {
      const f = this.S.edit, pw = makePassword()
      if (!confirm(`Set a new password for ${f.profile && f.profile.full_name}? The old one stops working.`)) return
      this.set({ busy: true, err: '' })
      try { await adminUsers({ action: 'reset_password', id: f.user_id, password: pw }); this.set({ done: `New password for ${f.business_name}. Send it privately:\n\nEmail: ${f.profile && f.profile.email}\nPassword: ${pw}` }) }
      catch (e) { this.set({ err: errText(e) }) } finally { this.set({ busy: false }) }
    },
  },
}
