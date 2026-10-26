import { html, raw, supabase, errText, toast } from '../../../core.js'
import { Loading, PageHead, SectionHead } from '../../../ui.js'

const DEFAULTS = {
  id: 1,
  company_name: 'SCRAPPY INNOVATIONS PVT LTD.',
  address: 'HO. WP 18/108 - H,J,K\n1st FLOOR SAJ BUILDING\nMANJERI ROAD WANDOOR\nPIN 679328',
  phone: '+918592964750',
  gstin: '32ABFCS0169R1ZX',
  email: 'info@scrappyinnovations.com',
  state: 'Kerala',
}

export default {
  state: { company: null, busy: false, err: '' },
  async init() {
    const { data, error } = await supabase.from('fr_company_settings').select('*').eq('id', 1).maybeSingle()
    if (error) return this.set({ err: errText(error) })
    this.set({ company: { ...DEFAULTS, ...(data || {}) } })
  },
  view(S) {
    if (S.err) return html`<p class="error">${S.err}</p>`
    if (!S.company) return Loading('Loading company details…')
    const c = S.company
    return html`${PageHead({ label: 'Set up', title: 'Company settings', sub: 'These company details appear in the seller section of printed invoices.' })}
      <section class="card">
        ${SectionHead({ title: 'Invoice details' })}
        <label>Company name<input data-bind="company.company_name" value="${c.company_name}" required></label>
        <label>Address<textarea data-bind="company.address" rows="4" required>${c.address}</textarea></label>
        <div class="grid2">
          <label>Phone<input type="tel" data-bind="company.phone" value="${c.phone}"></label>
          <label>GSTIN<input data-bind="company.gstin" value="${c.gstin}"></label>
          <label>Email<input type="email" data-bind="company.email" value="${c.email}"></label>
          <label>State<input data-bind="company.state" value="${c.state}"></label>
        </div>
        <button class="btn primary" data-act="save" ${S.busy ? raw('disabled') : ''}>${S.busy ? 'Saving…' : 'Save company details'}</button>
      </section>`
  },
  actions: {
    async save() {
      const c = this.S.company
      if (!c.company_name.trim() || !c.address.trim()) return toast('Enter the company name and address.', 'bad')
      this.set({ busy: true })
      const { error } = await supabase.from('fr_company_settings').upsert({
        id: 1,
        company_name: c.company_name.trim(),
        address: c.address.trim(),
        phone: c.phone.trim(),
        gstin: c.gstin.trim(),
        email: c.email.trim(),
        state: c.state.trim(),
      }, { onConflict: 'id' })
      this.set({ busy: false })
      if (error) return toast(errText(error), 'bad')
      toast('Company details saved')
    },
  },
}
