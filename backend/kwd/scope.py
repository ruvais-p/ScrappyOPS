"""Who is calling, and which rows they may read: the old database's row-level security rules, written as SQL pieces.
Every read of a table (and every table joined into a read) is cut down to what the caller may see."""
from core.models import AuthSession
from core.services.common import fetch, fetch_one, ApiError, SESSION_MSG

HO, ZM, TSO, FR = "head_office", "zonal_manager", "tso", "franchisee"


class KCtx:
    """The caller. Role and franchise come from the staff profile; an inactive person, or a login that was replaced by a
    newer one, has no role (so nothing works for them)."""

    def __init__(self, user_id, session_id=None):
        from uuid import UUID
        self.uid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))
        self.session_id = session_id
        self._valid = None
        self._prof = False
        self._fr = False

    def session_valid(self):
        if self._valid is None:
            self._valid = True if not self.session_id else AuthSession.objects.filter(id=self.session_id, user_id=self.uid).exists()
        return self._valid

    @property
    def profile(self):
        if self._prof is False:
            self._prof = fetch_one("select * from kwd_profiles where id = %(u)s", {"u": self.uid}) if self.session_valid() else None
        return self._prof

    @property
    def role(self):
        p = self.profile
        return p["role"] if p and p["is_active"] else None

    @property
    def franchise_id(self):
        if self._fr is False:
            self._fr = None
            if self.role == FR:
                row = fetch_one("select id from kwd_fr_franchises where user_id = %(u)s and is_active", {"u": self.uid})
                self._fr = row["id"] if row else None
        return self._fr

    def need_active(self):
        if not self.session_valid():
            raise ApiError(SESSION_MSG)
        if self.role is None:
            raise ApiError("Account inactive")


class Params:
    """Collects query values under generated names, so nothing from a request is ever pasted into SQL text."""

    def __init__(self, ctx):
        self.values = {"uid": ctx.uid}
        self.n = 0

    def add(self, v):
        self.n += 1
        k = f"p{self.n}"
        self.values[k] = v
        return f"%({k})s"


class Scope:
    def __init__(self, ctx, P):
        self.ctx, self.P = ctx, P
        self.role = ctx.role
        self.me = "%(uid)s::uuid"

    # ---- the helper functions the database had ----
    def my_districts(self):
        return f"(select district_id from kwd_user_districts where user_id = {self.me})"

    def in_my_districts(self, expr):
        return f"{expr} in {self.my_districts()}"

    def is_my_tso(self, expr):
        return f"exists (select 1 from kwd_profiles _t where _t.id = {expr} and _t.manager_id = {self.me})"

    def shares_district(self, expr):
        return (f"exists (select 1 from kwd_user_districts _a join kwd_user_districts _b on _a.district_id = _b.district_id "
                f"where _a.user_id = {self.me} and _b.user_id = {expr})")

    def can_see_lsgd(self, expr):
        if self.role == HO:
            return "true"
        if self.role == ZM:
            return f"exists (select 1 from kwd_lsgds _l where _l.id = {expr} and {self.in_my_districts('_l.district_id')})"
        if self.role == TSO:
            return (f"exists (select 1 from kwd_lsgds _l where _l.id = {expr} and "
                    f"(_l.assigned_tso = {self.me} or {self.in_my_districts('_l.district_id')}))")
        return "false"

    def can_see_day(self, expr):
        return (f"exists (select 1 from kwd_field_days _d where _d.id = {expr} and (_d.tso_id = {self.me} or {self.is_ho()} "
                f"or ({self.is_zm()} and {self.is_my_tso('_d.tso_id')})))")

    def fr_can_see(self, expr):
        if self.role == HO:
            return "true"
        fid = self.ctx.franchise_id
        return f"{expr} = {self.P.add(fid)}::uuid" if fid else "false"

    def is_ho(self):
        return "true" if self.role == HO else "false"

    def is_zm(self):
        return "true" if self.role == ZM else "false"

    def has_role(self):
        return "true" if self.role else "false"

    def role_in(self, *roles):
        return "true" if self.role in roles else "false"

    # ---- read rules, one per table ----
    def read(self, api, a):
        """SQL condition for rows of `api` (table alias `a`) the caller may see."""
        me = self.me
        r = {
            "audit_log": lambda: self.is_ho(),
            "claim_events": lambda: f"({self.can_see_day(a + '.day_id')} and ({a}.event not in ('ho_flagged','ho_unflagged') or {self.is_ho()}))",
            "contacts": lambda: self.can_see_lsgd(a + ".lsgd_id"),
            "districts": lambda: self.has_role(),
            "expense_items": lambda: self.can_see_day(a + ".day_id"),
            "expense_payments": lambda: f"({a}.tso_id = {me} or {self.is_ho()} or ({self.is_zm()} and {self.is_my_tso(a + '.tso_id')}))",
            "expense_policy": lambda: self.has_role(),
            "field_days": lambda: f"({a}.tso_id = {me} or {self.is_ho()} or ({self.is_zm()} and {self.is_my_tso(a + '.tso_id')}))",
            "followups": lambda: f"({a}.assigned_to = {me} or ({self.role_in(ZM, HO)} and {self.can_see_lsgd(a + '.lsgd_id')}))",
            "fr_franchises": lambda: self.fr_can_see(a + ".id"),
            "fr_company_settings": lambda: self.role_in(HO, FR),
            "fr_payment_receipts": lambda: self.is_ho(),
            "fr_lead_events": lambda: self.fr_can_see(a + ".franchise_id"),
            "fr_leads": lambda: self.fr_can_see(a + ".franchise_id"),
            "fr_presentations": lambda: self.fr_can_see(a + ".franchise_id"),
            "fr_products": lambda: self.role_in(HO, FR),
            "fr_sale_items": lambda: f"exists (select 1 from kwd_fr_sales _s where _s.id = {a}.sale_id and {self.fr_can_see('_s.franchise_id')})",
            "fr_sales": lambda: self.fr_can_see(a + ".franchise_id"),
            "fr_stock_moves": lambda: self.fr_can_see(a + ".franchise_id"),
            "fr_targets": lambda: self.fr_can_see(a + ".franchise_id"),
            "lsgds": lambda: self.can_see_lsgd(a + ".id"),
            "opportunities": lambda: self.can_see_lsgd(a + ".lsgd_id"),
            "profiles": lambda: f"({a}.id = {me} or {self.is_ho()} or ({self.is_zm()} and ({a}.manager_id = {me} or {self.shares_district(a + '.id')})))",
            "tasks": lambda: f"({a}.assigned_to = {me} or ({self.role_in(ZM, HO)} and {self.can_see_lsgd(a + '.lsgd_id')}))",
            "user_districts": lambda: f"({a}.user_id = {me} or {self.is_ho()} or ({self.is_zm()} and {self.is_my_tso(a + '.user_id')}))",
            "verification_calls": lambda: self.role_in(ZM, HO),
            "visit_contacts": lambda: f"exists (select 1 from kwd_visits _v where _v.id = {a}.visit_id and {self.read('visits', '_v')})",
            "visits": lambda: f"({a}.tso_id = {me} or ({self.role_in(ZM, HO)} and {self.can_see_lsgd(a + '.lsgd_id')}))",
        }
        if api not in r:
            return "false"
        return r[api]()

    # ---- views: computed only from rows the caller may see ----
    def view_sql(self, api):
        R = self.read
        if api == "v_pipeline":
            return (f"select d.name as district, o.stage, count(*) as lsgds, sum(o.expected_units) as units, sum(o.expected_value) as value, "
                    f"round(sum((o.expected_value * (o.probability)::numeric) / 100.0), 0) as weighted_value "
                    f"from kwd_opportunities o join kwd_lsgds l on l.id = o.lsgd_id join kwd_districts d on d.id = l.district_id "
                    f"where {R('opportunities', 'o')} and {R('lsgds', 'l')} and {R('districts', 'd')} group by d.name, o.stage")
        if api == "v_staff_daily":
            return (f"select v.tso_id, p.full_name, ((v.check_in_at at time zone 'Asia/Kolkata'))::date as day, count(*) as visits, "
                    f"count(distinct v.lsgd_id) as lsgds, count(*) filter (where cardinality(v.fraud_flags) > 0) as flagged, "
                    f"count(*) filter (where v.zm_status = 'verified') as verified, count(*) filter (where v.ho_signed_at is not null) as ho_signed "
                    f"from kwd_visits v join kwd_profiles p on p.id = v.tso_id where {R('visits', 'v')} and {R('profiles', 'p')} "
                    f"group by v.tso_id, p.full_name, ((v.check_in_at at time zone 'Asia/Kolkata')::date)")
        if api == "v_overdue_followups":
            return (f"select f.id, f.lsgd_id, f.opportunity_id, f.contact_id, f.visit_id, f.assigned_to, f.due_on, f.mode, f.notes, f.done_at, "
                    f"f.done_note, f.created_at, l.name as lsgd_name from kwd_followups f join kwd_lsgds l on l.id = f.lsgd_id "
                    f"where f.done_at is null and f.due_on < ((now() at time zone 'Asia/Kolkata')::date) and {R('followups', 'f')} and {R('lsgds', 'l')}")
        if api == "v_shared_contact_phones":
            return (f"select phone, count(distinct lsgd_id) as lsgds, array_agg(distinct name) as names from kwd_contacts c "
                    f"where phone is not null and {R('contacts', 'c')} group by phone having count(distinct lsgd_id) > 1")
        if api == "v_fr_sold":
            return (f"select s.franchise_id, s.id as sale_id, s.sale_date, (date_trunc('month', s.sale_date::timestamptz))::date as month, "
                    f"i.product_id, i.qty, i.line_total from kwd_fr_sale_items i join kwd_fr_sales s on s.id = i.sale_id "
                    f"where s.status = 'active' and {R('fr_sales', 's')} and {R('fr_sale_items', 'i')}")
        if api == "v_fr_stock":
            return (f"select franchise_id, product_id, (sum(qty))::integer as on_hand, "
                    f"(coalesce(sum(qty) filter (where kind in ('opening','received')), 0::bigint))::integer as received, "
                    f"(coalesce(-sum(qty) filter (where kind in ('sale','sale_cancel')), 0::bigint))::integer as sold, "
                    f"(coalesce(sum(qty) filter (where kind in ('damaged','returned','count_adjust')), 0::bigint))::integer as adjusted, "
                    f"max(created_at) as last_move_at from kwd_fr_stock_moves m where {R('fr_stock_moves', 'm')} group by franchise_id, product_id")
        raise ApiError(f"Unknown view {api}", 404)
