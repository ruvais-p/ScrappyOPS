/* Head Office: staff logins (create, edit roles and districts, switch off, reset password). */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Avatar } from '../../ui.js'
import { fmtDate } from '../../lib.js'
import { Sheet, adminUsers, errLine } from '../../kit.js'

const ROLE_LABEL = { tso: 'TSO', zonal_manager: 'Zonal Manager', head_office: 'Head Office' }

function makePassword() {
  const a = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  const r = crypto.getRandomValues(new Uint32Array(10))
  return 'Sc-' + Array.from(r, (x) => a[x % a.length]).join('')
}
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`

function formSheet(S, me) {
  const s = S.edit, f = S.f, isNew = !s.id, isSelf = s.id === me.id
  const zms = (S.rows || []).filter((r) => r.role === 'zonal_manager' && r.is_active)
  // when a ZM is chosen for a TSO, suggest that ZM's districts are the ones to pick from
  const zm = zms.find((z) => z.id === f.manager_id)
  const shown = f.role === 'tso' && zm ? S.districts.filter((d) => zm.district_ids.includes(d.id)) : S.districts
  if (S.done) {
    return Sheet({ title: 'Done', close: 'doneClose', body: html`
      <pre class="card" style="white-space:pre-wrap;font:500 1rem var(--body)">${S.done}</pre>
      <p class="muted small">This password is shown only once. It is not stored anywhere you can see it again.</p>
      <div class="row wrap"><button class="btn" data-act="copy">Copy</button><button class="btn primary" data-act="doneClose">Close</button></div>` })
  }
  return Sheet({ title: isNew ? 'New staff login' : `Edit ${s.full_name}`, close: 'closeEdit', body: html`
    <label>Full name<input data-bind="f.full_name" value="${f.full_name}"></label>
    <div class="grid2">
      <label>Email (login)${isNew ? html`<input type="email" data-bind="f.email" value="${f.email}">` : html`<input value="${f.email}" disabled>`}</label>
      <label>Mobile<input type="tel" inputmode="numeric" data-bind="f.phone" value="${f.phone}" placeholder="10 digits"></label>
    </div>
    <label>Role<select data-bind="f.role" data-live ${isSelf ? raw('disabled') : ''}>
      ${opt('tso', f.role, 'Territory Sales Officer (TSO)')}${opt('zonal_manager', f.role, 'Zonal Manager')}${opt('head_office', f.role, 'Head Office')}</select></label>
    ${f.role === 'tso' ? html`<label>Reports to (Zonal Manager)<select data-bind="f.manager_id" data-live><option value="">Choose…</option>${zms.map((z) => opt(z.id, f.manager_id, z.full_name))}</select></label>` : ''}
    ${f.role !== 'head_office' ? html`<div class="field-label">${f.role === 'zonal_manager' ? 'Jurisdiction (districts this ZM manages)' : 'Districts this TSO works in'}</div>
      ${f.role === 'tso' && zm ? html`<p class="small muted">Showing ${zm.full_name}'s districts.</p>` : ''}
      <div class="chips">${shown.map((d) => html`<button class="chip${f.district_ids.includes(d.id) ? ' on' : ''}" data-act="toggleD" data-id="${d.id}" aria-pressed="${f.district_ids.includes(d.id)}">${d.name}</button>`)}</div>` : ''}
    ${isNew ? html`<label>First password<div class="row"><input data-bind="f.password" value="${f.password}" class="grow"><button class="btn sm" data-act="newPw">New</button></div></label>` : ''}
    ${!isNew && !isSelf ? html`<label class="check" style="margin-top:14px"><input type="checkbox" data-bind="f.is_active" ${f.is_active ? raw('checked') : ''}> Login is active (untick when someone leaves; their phone is signed out)</label>` : ''}
    ${errLine(S.ferr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="save">${S.busy ? 'Saving…' : isNew ? 'Create login' : 'Save changes'}</button>
    ${!isNew ? html`<button class="btn block" ${S.busy ? raw('disabled') : ''} data-act="resetPw">Reset password</button>` : ''}` })
}

export default {
  state: { rows: null, districts: [], role: '', q: '', edit: null, f: null, ferr: '', busy: false, done: '', err: '' },
  async init() { await this.actions.reload.call(this) },
  view(S, ctx) {
    const dName = (id) => (S.districts.find((d) => d.id === id) || {}).name
    const byId = (id) => (S.rows || []).find((r) => r.id === id)
    const s = S.q.trim().toLowerCase()
    const list = (S.rows || []).filter((r) => (!S.role || r.role === S.role) && (!s || `${r.full_name} ${r.email} ${r.phone}`.toLowerCase().includes(s)))
    const coverage = S.districts.map((d) => ({
      ...d,
      zms: (S.rows || []).filter((r) => r.role === 'zonal_manager' && r.is_active && r.district_ids.includes(d.id)).length,
      tsos: (S.rows || []).filter((r) => r.role === 'tso' && r.is_active && r.district_ids.includes(d.id)).length,
    }))
    const gaps = coverage.filter((c) => !c.zms || !c.tsos)
    return html`${PageHead({ label: 'Staff & logins', title: 'Staff', sub: "Create logins, set each person's role and districts, and switch logins off when someone leaves.",
        actions: html`<button class="btn primary" data-act="add">${Icon('plus', 18)} New login</button>` })}
      ${gaps.length > 0 && S.rows ? html`<p class="notice warn">Districts not fully covered: ${gaps.map((g) => `${g.name} (${!g.zms ? 'no ZM' : ''}${!g.zms && !g.tsos ? ', ' : ''}${!g.tsos ? 'no TSO' : ''})`).join(' · ')}</p>` : ''}
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search name, email, phone" data-bind="q" data-live value="${S.q}"></div>
        <div class="seg">${[['', 'All'], ['tso', 'TSOs'], ['zonal_manager', 'ZMs'], ['head_office', 'HO']].map(([k, l]) => html`<button class="${S.role === k ? 'on' : ''}" data-act="role" data-k="${k}">${l}</button>`)}</div>
      </div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading('Loading staff…') : list.length === 0 ? Empty('No staff match.') : html`<div class="table-wrap"><table>
        <thead><tr><th>Name</th><th>Role</th><th>Districts</th><th>Reports to</th><th>Status</th><th>Since</th><th></th></tr></thead>
        <tbody>${list.map((r) => html`<tr style="${r.is_active ? '' : 'opacity:.6'}">
          <td><div class="who-cell">${Avatar(r.full_name || r.email, 32)}<div><b>${r.full_name || '—'}</b><div class="muted small">${r.email}${r.phone ? ` · ${r.phone}` : ''}</div></div></div></td>
          <td>${ROLE_LABEL[r.role]}</td>
          <td style="white-space:normal;max-width:260px">${r.role === 'head_office' ? html`<span class="muted">All</span>` : r.district_ids.map(dName).join(', ') || html`<span class="text-warn">None</span>`}</td>
          <td>${r.role === 'tso' ? ((byId(r.manager_id) || {}).full_name || html`<span class="text-warn">No ZM</span>`) : html`<span class="muted">—</span>`}</td>
          <td>${r.is_active ? html`<span class="pill ok">Active</span>` : html`<span class="pill bad">Off</span>`}</td>
          <td>${fmtDate(r.created_at)}</td>
          <td><button class="btn sm" data-act="edit" data-id="${r.id}">Edit</button></td></tr>`)}</tbody></table></div>`}
      ${S.edit ? formSheet(S, ctx.profile) : ''}`
  },
  actions: {
    role(el) { this.set({ role: el.dataset.k }) },
    async reload() {
      const [p, d] = await Promise.all([
        supabase.from('profiles').select('*, user_districts(district_id)').neq('role', 'franchisee').order('role').order('full_name'),
        supabase.from('districts').select('id, name').order('name'),
      ])
      if (p.error || d.error) return this.set({ err: errText(p.error || d.error) })
      this.set({ rows: p.data.map((x) => ({ ...x, district_ids: x.user_districts.map((u) => u.district_id) })), districts: d.data })
    },
    add() { this.set({ edit: {}, done: '', ferr: '', f: { full_name: '', email: '', phone: '', role: 'tso', manager_id: '', district_ids: [], is_active: true, password: makePassword() } }) },
    edit(el) {
      const s = this.S.rows.find((r) => r.id === el.dataset.id)
      this.set({ edit: s, done: '', ferr: '', f: { full_name: s.full_name || '', email: s.email || '', phone: s.phone || '', role: s.role, manager_id: s.manager_id || '', district_ids: [...s.district_ids], is_active: s.is_active ?? true, password: '' } })
    },
    closeEdit() { this.set({ edit: null }) },
    doneClose() { this.set({ edit: null, done: '' }); this.actions.reload.call(this) },
    copy() { if (navigator.clipboard) navigator.clipboard.writeText(this.S.done) },
    newPw() { this.set({ f: { ...this.S.f, password: makePassword() } }) },
    toggleD(el) {
      const id = Number(el.dataset.id), f = this.S.f
      this.set({ f: { ...f, district_ids: f.district_ids.includes(id) ? f.district_ids.filter((x) => x !== id) : [...f.district_ids, id] } })
    },
    async save() {
      const S = this.S, f = S.f, s = S.edit, isNew = !s.id
      if (!f.full_name.trim()) return this.set({ ferr: 'Enter the full name.' })
      if (isNew && !/^\S+@\S+\.\S+$/.test(f.email.trim())) return this.set({ ferr: 'Enter a valid email.' })
      if (f.phone && !/^[6-9]\d{9}$/.test(f.phone.replace(/\D/g, '').slice(-10))) return this.set({ ferr: 'Enter a valid 10-digit mobile number.' })
      if (f.role === 'tso' && !f.manager_id) return this.set({ ferr: 'Choose the Zonal Manager this TSO reports to.' })
      if (f.role !== 'head_office' && f.district_ids.length === 0) return this.set({ ferr: 'Pick at least one district.' })
      if (isNew && f.password.length < 8) return this.set({ ferr: 'Password must be at least 8 characters.' })
      this.set({ busy: true, ferr: '' })
      const p = {
        full_name: f.full_name.trim(), phone: f.phone ? f.phone.replace(/\D/g, '').slice(-10) : null, role: f.role,
        manager_id: f.role === 'tso' ? f.manager_id : null, district_ids: f.role === 'head_office' ? [] : f.district_ids,
        ...(isNew ? {} : { is_active: f.is_active }),
      }
      try {
        if (isNew) await adminUsers({ action: 'create', email: f.email.trim(), password: f.password, full_name: p.full_name, profile: p })
        else await adminUsers({ action: 'update', id: s.id, profile: p })
        if (isNew) this.set({ done: `Login created. Send ${f.full_name.split(' ')[0]} these details privately:\n\nEmail: ${f.email.trim().toLowerCase()}\nPassword: ${f.password}` })
        else { toast('Changes saved'); this.set({ edit: null }); await this.actions.reload.call(this) }
      } catch (e) { this.set({ ferr: errText(e) }) } finally { this.set({ busy: false }) }
    },
    async resetPw() {
      const s = this.S.edit, pw = makePassword()
      if (!confirm(`Set a new password for ${s.full_name}? Their old password stops working.`)) return
      this.set({ busy: true, ferr: '' })
      try {
        await adminUsers({ action: 'reset_password', id: s.id, password: pw })
        this.set({ done: `New password for ${s.full_name}. Send it privately:\n\nEmail: ${s.email}\nPassword: ${pw}` })
      } catch (e) { this.set({ ferr: errText(e) }) } finally { this.set({ busy: false }) }
    },
  },
}
