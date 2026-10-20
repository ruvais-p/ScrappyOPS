/* LSGDs of a zone: list, add / edit (with map-link reading), CSV import. */
import { html, raw, supabase, errText, toast } from '../../core.js'
import { Loading, Empty, Icon, PageHead } from '../../ui.js'
import { LSGD_TYPES, stageLabel, financialYear, fmtDate } from '../../lib.js'
import { loadTeam, Sheet, parseLatLng, needsResolving, resolveMapLink, errLine } from '../../kit.js'

const TYPE_WORDS = {
  grama_panchayat: ['grama panchayat', 'gram panchayat', 'panchayat', 'gp'],
  block_panchayat: ['block panchayat', 'block', 'bp'],
  district_panchayat: ['district panchayat', 'dp'],
  municipality: ['municipality', 'mun'],
  corporation: ['corporation', 'corp'],
}
const toType = (t) => {
  const s = (t || '').trim().toLowerCase().replace(/_/g, ' ')
  return Object.keys(TYPE_WORDS).find((k) => k.replace(/_/g, ' ') === s || TYPE_WORDS[k].includes(s))
}
function parseCsv(text) {
  return text.split(/\r?\n/).filter((l) => l.trim()).map((line) => {
    const out = []; let cur = ''; let q = false
    for (const ch of line) {
      if (ch === '"') q = !q
      else if (ch === ',' && !q) { out.push(cur.trim()); cur = '' }
      else cur += ch
    }
    out.push(cur.trim())
    return out
  })
}
const opt = (v, cur, label) => html`<option value="${v}" ${String(cur) === String(v) ? raw('selected') : ''}>${label}</option>`

function formSheet(S) {
  const f = S.f, l = S.edit, isNew = !l.id
  const parsed = f.loc.trim() ? parseLatLng(f.loc) : null
  const ls = S.linkState
  return Sheet({ title: isNew ? 'Add LSGD' : `Edit ${l.name}`, close: 'closeEdit', body: html`
    <label>Name<input data-bind="f.name" value="${f.name}" placeholder="e.g. Vazhakkad"></label>
    <div class="grid2">
      <label>Type<select data-bind="f.type">${Object.entries(LSGD_TYPES).map(([k, v]) => opt(k, f.type, v))}</select></label>
      <label>District<select data-bind="f.district_id" data-live>${S.districts.map((d) => opt(d.id, f.district_id, d.name))}</select></label>
    </div>
    <label>Assigned TSO<select data-bind="f.assigned_tso"><option value="">Not assigned</option>${(S.team || []).map((t) => opt(t.id, f.assigned_tso, t.full_name || t.email))}</select></label>
    <label>Office location<input data-bind="f.loc" data-change="locTyped" data-oninput data-live value="${f.loc}" inputmode="url" placeholder="Paste a Google Maps link, Plus Code or lat, lng"></label>
    ${ls && ls.busy ? html`<p class="small muted" role="status">Finding the location from your link…</p>` : ''}
    ${ls && ls.ok && parsed ? html`<p class="notice ok small" role="status">${ls.text}</p>` : ''}
    ${ls && ls.err && !parsed ? html`<p class="notice bad small" role="alert">${ls.err}</p>` : ''}
    <div class="row wrap small">
      <button class="btn sm" data-act="myLocation">${Icon('locate', 16)} I'm at the office now</button>
      ${parsed && !parsed.outside ? html`<a href="https://maps.google.com/?q=${parsed.lat},${parsed.lng}" target="_blank" rel="noreferrer">Check on map</a>` : ''}
    </div>
    ${S.gpsNote ? html`<p class="small muted">${S.gpsNote}</p>` : ''}
    <p class="small muted">TSO check-ins more than 300 m from this point are flagged. Every change is recorded for Head Office.</p>
    ${errLine(S.ferr)}
    <button class="btn primary block" ${S.busy ? raw('disabled') : ''} data-act="saveLsgd">${S.busy ? 'Saving…' : isNew ? 'Add LSGD' : 'Save changes'}</button>` })
}

function importSheet(S) {
  const done = S.result
  return Sheet({ title: 'Import LSGDs from CSV', close: done ? 'importDone' : 'closeImport', body: done
    ? html`<p class="notice ok">${done}</p><button class="btn primary block" data-act="importDone">Done</button>`
    : html`<p class="small">Columns: <b>name, type, district, lat, lng</b>. Location is optional. Type can be Grama Panchayat, Block Panchayat, District Panchayat, Municipality or Corporation.</p>
      <pre class="card small" style="margin:8px 0;overflow-x:auto">name,type,district,lat,lng\nVazhakkad,Grama Panchayat,Malappuram,11.2296,75.9504\nKondotty,Municipality,Malappuram,,</pre>
      <input type="file" accept=".csv,text/csv" data-change="csvFile">
      ${S.csvRows ? html`<p class="notice info">${S.csvRows.length} row${S.csvRows.length === 1 ? '' : 's'} ready to import.</p>` : ''}
      ${S.csvBad.length > 0 ? html`<div class="notice warn"><b>${S.csvBad.length} row${S.csvBad.length === 1 ? '' : 's'} skipped</b>
        <ul style="margin:4px 0 0;padding-left:18px;max-height:160px;overflow:auto">${S.csvBad.slice(0, 50).map((b) => html`<li>${b}</li>`)}</ul></div>` : ''}
      ${errLine(S.ferr)}
      <button class="btn primary block" ${S.busy || !(S.csvRows && S.csvRows.length) ? raw('disabled') : ''} data-act="runImport">${S.busy ? 'Importing…' : 'Import'}</button>
      <p class="muted small">LSGDs that already exist in the same district are not changed.</p>` })
}

export default {
  state: { team: null, districts: [], rows: null, q: '', district: '', show: 'all', edit: null, importing: false, err: '',
    f: null, ferr: '', busy: false, gpsNote: '', linkState: null, csvRows: null, csvBad: [], result: '' },
  async init() {
    loadTeam(this.ctx.profile).then((t) => this.set(t))
    await this.actions.reload.call(this)
  },
  view(S) {
    const s = S.q.trim().toLowerCase()
    const fy = financialYear()
    const list = (S.rows || [])
      .filter((l) => !S.district || String(l.district_id) === S.district)
      .filter((l) => !s || l.name.toLowerCase().includes(s))
      .filter((l) => S.show === 'all' || (S.show === 'noloc' ? l.office_lat == null : !l.assigned_tso))
      .map((l) => ({ ...l, opp: l.opportunities.find((o) => o.financial_year === fy), last: l.visits.map((v) => v.check_in_at).sort().at(-1) }))
    const noLoc = (S.rows || []).filter((l) => l.office_lat == null).length
    const noTso = (S.rows || []).filter((l) => !l.assigned_tso).length
    return html`${PageHead({ label: 'LSGDs in your districts', title: 'LSGDs', sub: S.rows ? `${S.rows.length} LSGDs` : null,
        actions: html`<button class="btn" data-act="openImport">${Icon('upload', 18)} Import CSV</button><button class="btn primary" data-act="add">${Icon('plus', 18)} Add LSGD</button>` })}
      ${noLoc > 0 || noTso > 0 ? html`<p class="notice warn">${noLoc > 0 ? `${noLoc} without an office location (their visits can't be location-checked). ` : ''}${noTso > 0 ? `${noTso} with no TSO assigned.` : ''}</p>` : ''}
      <div class="toolbar">
        <div class="search">${Icon('search', 18)}<input placeholder="Search name" data-bind="q" data-live value="${S.q}"></div>
        <select data-bind="district" data-live aria-label="District"><option value="">All districts</option>${S.districts.map((d) => opt(d.id, S.district, d.name))}</select>
        <div class="seg">${[['all', 'All'], ['noloc', 'No location'], ['notso', 'No TSO']].map(([k, l]) => html`<button class="${S.show === k ? 'on' : ''}" data-act="show" data-k="${k}">${l}</button>`)}</div>
      </div>
      ${S.err ? html`<p class="error">${S.err}</p>` : ''}
      ${!S.rows ? Loading('Loading LSGDs…') : list.length === 0 ? Empty('No LSGDs match.') : html`<div class="table-wrap"><table>
        <thead><tr><th>LSGD</th><th>District</th><th>TSO</th><th>Office location</th><th>Deal ${fy}</th><th>Last visit</th><th></th></tr></thead>
        <tbody>${list.map((l) => html`<tr data-key="${l.id}">
          <td><button class="link title" data-act="open" data-id="${l.id}">${l.name}</button><div class="muted small">${LSGD_TYPES[l.type]}</div></td>
          <td>${l.districts.name}</td>
          <td>${(l.tso && l.tso.full_name) || html`<span class="text-warn">Not assigned</span>`}</td>
          <td>${l.office_lat != null ? html`<a href="https://maps.google.com/?q=${l.office_lat},${l.office_lng}" target="_blank" rel="noreferrer">On map</a>` : html`<span class="pill warn">Not set</span>`}</td>
          <td>${l.opp ? html`<span class="pill stage-${l.opp.stage}">${stageLabel(l.opp.stage)}</span>` : html`<span class="muted">—</span>`}</td>
          <td>${l.last ? fmtDate(l.last) : html`<span class="muted">Never</span>`}</td>
          <td><button class="btn sm" data-act="edit" data-id="${l.id}">Edit</button></td></tr>`)}</tbody></table></div>`}
      ${S.importing ? importSheet(S) : ''}${S.edit ? formSheet(S) : ''}`
  },
  actions: {
    show(el) { this.set({ show: el.dataset.k }) },
    open(el) { this.ctx.go('lsgd', { lsgdId: el.dataset.id, back: 'zlsgds' }) },
    async reload() {
      const { data, error } = await supabase.from('lsgds')
        .select('*, districts(name), tso:profiles!lsgds_assigned_tso_fkey(full_name), opportunities(stage, financial_year), visits(check_in_at)').order('name')
      if (error) return this.set({ err: errText(error) })
      this.set({ rows: data })
    },
    // --- add / edit
    add() { this.set({ edit: {}, ferr: '', gpsNote: '', linkState: null, f: { name: '', type: 'grama_panchayat', district_id: (this.S.districts[0] || {}).id || '', assigned_tso: '', loc: '' } }) },
    edit(el) {
      const l = this.S.rows.find((r) => r.id === el.dataset.id)
      this.set({ edit: l, ferr: '', gpsNote: '', linkState: null, f: { name: l.name, type: l.type, district_id: l.district_id, assigned_tso: l.assigned_tso || '', loc: l.office_lat != null ? `${l.office_lat}, ${l.office_lng}` : '' } })
    },
    closeEdit() { this.set({ edit: null }) },
    // a pasted share link or Plus Code is turned into "lat, lng" automatically
    locTyped(el) {
      this.S.ferr = ''
      const t = el.value.trim()
      clearTimeout(this.locTimer)
      if (!t) return this.set({ linkState: null })
      if (parseLatLng(t) || !needsResolving(t)) return
      this.set({ linkState: { busy: true } })
      const district = this.S.districts.find((d) => String(d.id) === String(this.S.f.district_id))
      this.locTimer = setTimeout(async () => {
        try {
          const r = await resolveMapLink(t, district && district.name)
          if (this.S.f.loc.trim() !== t) return
          if (r.lat < 8 || r.lat > 13 || r.lng < 74 || r.lng > 78) return this.set({ linkState: { err: 'That link points outside Kerala. Check you copied the right place.' } })
          this.S.f.loc = `${r.lat.toFixed(6)}, ${r.lng.toFixed(6)}`
          this.set({ linkState: { ok: true, text: r.plusCode ? `Found from the map link (Plus Code ${r.plusCode}). Check it's the office.` : "Found from the map link. Check it's the office." } })
        } catch (e) { this.set({ linkState: { err: e.message } }) }
      }, 500)
    },
    myLocation() {
      this.set({ gpsNote: 'Getting your location…' })
      navigator.geolocation.getCurrentPosition(
        (p) => {
          this.S.f.loc = `${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)}`
          this.set({ gpsNote: p.coords.accuracy > 50 ? `Accuracy is ±${Math.round(p.coords.accuracy)} m. Stand outside the office and try again for a better fix.` : `Accuracy ±${Math.round(p.coords.accuracy)} m.` })
        },
        () => this.set({ gpsNote: 'Could not get your location. Allow location access and try again.' }),
        { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
      )
    },
    async saveLsgd() {
      const S = this.S, f = S.f, l = S.edit, isNew = !l.id
      const parsed = f.loc.trim() ? parseLatLng(f.loc) : null
      if (!f.name.trim()) return this.set({ ferr: 'Enter the LSGD name.' })
      if (S.linkState && S.linkState.busy) return this.set({ ferr: 'Still reading the map link. One moment.' })
      if (f.loc.trim() && (!parsed || parsed.outside)) return this.set({ ferr: (S.linkState && S.linkState.err) || 'That location is not a valid point in Kerala. Paste a Google Maps link, a Plus Code or "lat, lng".' })
      this.set({ busy: true, ferr: '' })
      const row = { name: f.name.trim(), type: f.type, district_id: Number(f.district_id), assigned_tso: f.assigned_tso || null, office_lat: parsed ? parsed.lat : null, office_lng: parsed ? parsed.lng : null }
      const { error } = isNew ? await supabase.from('lsgds').insert(row) : await supabase.from('lsgds').update(row).eq('id', l.id)
      this.set({ busy: false })
      if (error) return this.set({ ferr: error.code === '23505' ? 'This LSGD already exists in that district.' : errText(error) })
      toast(isNew ? 'LSGD added' : 'Changes saved')
      this.set({ edit: null })
      await this.actions.reload.call(this)
    },
    // --- CSV import
    openImport() { this.set({ importing: true, csvRows: null, csvBad: [], result: '', ferr: '' }) },
    closeImport() { this.set({ importing: false }) },
    importDone() { this.set({ importing: false }); this.actions.reload.call(this) },
    async csvFile(el) {
      const file = el.files && el.files[0]
      if (!file) return
      const lines = parseCsv(await file.text())
      const head = lines[0].map((h) => h.toLowerCase())
      const hasHead = head.includes('name')
      const col = (n, i) => (hasHead ? head.indexOf(n) : i)
      const ix = { name: col('name', 0), type: col('type', 1), district: col('district', 2), lat: col('lat', 3), lng: col('lng', 4) }
      const ok = [], problems = []
      lines.slice(hasHead ? 1 : 0).forEach((r, i) => {
        const name = (r[ix.name] || '').trim()
        const type = toType(r[ix.type])
        const d = this.S.districts.find((x) => x.name.toLowerCase() === (r[ix.district] || '').trim().toLowerCase())
        const lat = ix.lat >= 0 && r[ix.lat] ? Number(r[ix.lat]) : null
        const lng = ix.lng >= 0 && r[ix.lng] ? Number(r[ix.lng]) : null
        const why = !name ? 'no name' : !type ? `unknown type "${r[ix.type] || ''}"` : !d ? `district "${r[ix.district] || ''}" is not yours` :
          (lat != null && (isNaN(lat) || lat < 8 || lat > 13)) || (lng != null && (isNaN(lng) || lng < 74 || lng > 78)) ? 'location outside Kerala' : ''
        if (why) problems.push(`Row ${i + (hasHead ? 2 : 1)}: ${why}`)
        else ok.push({ name, type, district_id: d.id, office_lat: lat, office_lng: lng })
      })
      this.set({ csvRows: ok, csvBad: problems })
    },
    async runImport() {
      const rows = this.S.csvRows
      this.set({ busy: true, ferr: '' })
      let added = 0
      for (let i = 0; i < rows.length; i += 200) {
        const { data, error } = await supabase.from('lsgds').upsert(rows.slice(i, i + 200), { onConflict: 'name,district_id', ignoreDuplicates: true }).select('id')
        if (error) return this.set({ busy: false, ferr: errText(error) })
        added += data.length
      }
      this.set({ busy: false, result: `${added} new LSGD${added === 1 ? '' : 's'} added. ${rows.length - added} already existed and were left as they were.` })
    },
  },
}
