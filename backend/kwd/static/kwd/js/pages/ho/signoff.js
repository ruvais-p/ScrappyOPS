/* Head Office: sign off the visits a Zonal Manager verified. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead, Avatar } from '../../ui.js'
import { fmtDate, fmtTime, FLAG_TEXT, INTEREST } from '../../lib.js'

const SELECT = `id, check_in_at, check_out_at, distance_from_office_m, gps_accuracy_m, fraud_flags, photo_path,
  discussion, outcome, interest_level, zm_status, zm_remark, zm_reviewed_at, ho_signed_at, ho_remark,
  tso:profiles!visits_tso_id_fkey(full_name), zm:profiles!visits_zm_reviewed_by_fkey(full_name),
  lsgds(name, districts(id, name)), visit_contacts(contacts(name, designation, verified_at))`

function row(S, v, todo) {
  const open = !!S.open[v.id]
  const met = v.visit_contacts.map((x) => x.contacts)
  return html`<li class="item col${v.fraud_flags.length ? ' flagged' : ''}" data-key="${v.id}">
    <div class="row">
      ${todo ? html`<input type="checkbox" data-change="pick" data-id="${v.id}" ${S.picked.includes(v.id) ? raw('checked') : ''} aria-label="Select ${v.lsgds.name}" style="width:20px;height:20px;min-height:0;margin:0;flex:none;accent-color:var(--brand)">` : ''}
      ${Avatar((v.tso && v.tso.full_name) || '?', 32)}
      <button class="link-row grow" data-act="toggle" data-id="${v.id}" aria-expanded="${open}">
        <div class="title">${v.lsgds.name} <span class="muted small">· ${v.lsgds.districts.name}</span></div>
        <div class="muted small">${v.tso && v.tso.full_name} · ${fmtDate(v.check_in_at)} ${fmtTime(v.check_in_at)}${v.distance_from_office_m != null ? ` · ${Math.round(v.distance_from_office_m)} m from office` : ''} · verified by ${(v.zm && v.zm.full_name) || 'ZM'}</div>
      </button>
      ${v.fraud_flags.length > 0 ? html`<span class="pill warn">${v.fraud_flags.length} flag</span>` : ''}
      ${met.some((c) => c.verified_at) ? html`<span class="pill ok">call confirmed</span>` : ''}
      ${todo ? html`<button class="btn sm" ${S.busy ? raw('disabled') : ''} data-act="signOne" data-id="${v.id}">Sign</button>` : html`<span class="pill ok">Signed ${fmtDate(v.ho_signed_at)}</span>`}
    </div>
    ${open ? html`<div class="detail">
      ${v.fraud_flags.length > 0 ? html`<div class="flags">${v.fraud_flags.map((f) => html`<span class="pill warn tiny">${FLAG_TEXT[f] || f}</span>`)}</div>` : ''}
      ${S.photos[v.id] ? html`<img class="photo" style="max-width:420px" src="${S.photos[v.id]}" alt="Photo at ${v.lsgds.name}">` : ''}
      <p><b>Met:</b> ${met.map((c) => `${c.name} (${c.designation})${c.verified_at ? ' ✓' : ''}`).join(', ') || '—'}</p>
      <p><b>Discussion:</b> ${v.discussion || 'Not added'}</p>
      ${v.outcome ? html`<p><b>Next step:</b> ${v.outcome}</p>` : ''}
      ${v.interest_level ? html`<p><b>Interest:</b> ${INTEREST[v.interest_level - 1]}</p>` : ''}
      ${v.zm_remark ? html`<p><b>ZM remark:</b> ${v.zm_remark}</p>` : ''}
      ${todo ? html`<div class="row wrap">
        <input class="grow" placeholder="Reason to send back to ZM" data-bind="remarks.${v.id}" value="${S.remarks[v.id] || ''}">
        <button class="btn danger sm" data-act="sendBack" data-id="${v.id}">${Icon('flag', 16)} Send back</button></div>` : ''}
    </div>` : ''}
  </li>`
}

export default {
  state: { tab: 'todo', rows: null, district: '', picked: [], open: {}, photos: {}, remarks: {}, busy: false, err: '' },
  async init() { await this.actions.load.call(this) },
  view(S) {
    const districts = [...new Map((S.rows || []).map((r) => [r.lsgds.districts.id, r.lsgds.districts.name])).entries()].sort((a, b) => a[1].localeCompare(b[1]))
    const list = (S.rows || []).filter((r) => !S.district || String(r.lsgds.districts.id) === S.district)
    const clean = list.filter((r) => r.fraud_flags.length === 0)
    const todo = S.tab === 'todo'
    return html`${PageHead({ label: 'Head Office sign-off', title: 'Sign verified visits', sub: 'These visits were verified by a Zonal Manager. Sign them off, or send one back if something looks wrong.' })}
      <div class="toolbar">
        <div class="seg">
          <button class="${todo ? 'on' : ''}" data-act="tab" data-k="todo">To sign</button>
          <button class="${!todo ? 'on' : ''}" data-act="tab" data-k="done">Signed</button>
        </div>
        <select data-bind="district" data-live aria-label="District"><option value="">All districts</option>${districts.map(([id, n]) => html`<option value="${id}" ${S.district === String(id) ? raw('selected') : ''}>${n}</option>`)}</select>
        ${todo && list.length > 0 ? html`
          <button class="btn sm" data-act="selectClean" data-ids="${clean.map((r) => r.id).join(',')}">${S.picked.length ? 'Clear selection' : `Select ${clean.length} with no flags`}</button>
          <button class="btn primary sm" ${S.busy || !S.picked.length ? raw('disabled') : ''} data-act="signSelected">${Icon('check', 16)} Sign ${S.picked.length || ''} selected</button>` : ''}
      </div>
      ${S.err ? html`<p class="error" role="alert">${S.err}</p>` : ''}
      ${!S.rows ? Loading('Loading visits…') : list.length === 0
        ? Empty(todo ? 'Nothing to sign. All verified visits are signed off.' : 'No signed visits yet.')
        : html`<ul class="list">${list.map((v) => row(S, v, todo))}</ul>`}`
  },
  actions: {
    tab(el) { this.set({ tab: el.dataset.k }); this.actions.load.call(this) },
    async load() {
      const S = this.S
      this.set({ rows: null, picked: [] })
      let q = supabase.from('visits').select(SELECT).eq('zm_status', 'verified').limit(300)
      q = S.tab === 'todo' ? q.is('ho_signed_at', null).order('check_in_at') : q.not('ho_signed_at', 'is', null).order('ho_signed_at', { ascending: false }).limit(100)
      const { data, error } = await q
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data })
    },
    pick(el) { const id = el.dataset.id; this.set({ picked: el.checked ? [...this.S.picked, id] : this.S.picked.filter((x) => x !== id) }) },
    selectClean(el) { this.set({ picked: this.S.picked.length ? [] : el.dataset.ids.split(',').filter(Boolean) }) },
    signSelected() { return sign(this, this.S.picked) },
    signOne(el) { return sign(this, [el.dataset.id]) },
    async toggle(el) {
      const id = el.dataset.id, v = this.S.rows.find((r) => r.id === id)
      this.S.open[id] = !this.S.open[id]
      this.render()
      if (this.S.open[id] && !this.S.photos[id]) {
        const { data } = await supabase.storage.from('visit-photos').createSignedUrl(v.photo_path, 900)
        if (data) { this.S.photos[id] = data.signedUrl; this.render() }
      }
    },
    async sendBack(el) {
      const id = el.dataset.id, remark = (this.S.remarks[id] || '').trim()
      if (!remark) return this.set({ err: 'Write why you are sending it back.' })
      const { error } = await supabase.from('visits').update({ zm_status: 'flagged', ho_remark: remark }).eq('id', id)
      if (error) return this.set({ err: errText(error) })
      toast('Sent back to the Zonal Manager', 'bad')
      if (this.ctx.refreshCounts) this.ctx.refreshCounts()
      await this.actions.load.call(this)
    },
  },
}

async function sign(sc, ids) {
  if (!ids.length) return
  sc.set({ busy: true, err: '' })
  const { error } = await supabase.from('visits').update({ ho_signed_at: new Date().toISOString() }).in('id', ids)
  sc.set({ busy: false })
  if (error) return sc.set({ err: errText(error) })
  toast(`${ids.length} visit${ids.length > 1 ? 's' : ''} signed off`)
  if (sc.ctx.refreshCounts) sc.ctx.refreshCounts()
  await sc.actions.load.call(sc)
}
