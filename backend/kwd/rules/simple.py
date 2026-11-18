"""The smaller tables: districts, staff profiles, LSGDs, contacts, LSGD updates, tasks, deals, follow-ups, verification calls,
expense policy."""
from core.services.common import ApiError, fetch_one
from kwd.rules.base import Rules
from kwd.rules.util import ist_today, now, trim
from kwd.scope import FR, HO, TSO, ZM


def uu(P, v):
    """A uuid value as a SQL piece."""
    return f"{P.add(v)}::uuid" if v is not None else "null::uuid"


class Districts(Rules):
    api = "districts"

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO

    def delete_using(self, ctx, S, a):
        return S.is_ho()


class Profiles(Rules):
    """Head Office edits people here. New logins are made by the admin-users function (kwd/admin_users.py)."""
    api = "profiles"
    audit = ("INSERT", "UPDATE", "DELETE")

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO


class UserDistricts(Rules):
    api = "user_districts"

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO

    def delete_using(self, ctx, S, a):
        return S.is_ho()


class Lsgds(Rules):
    api = "lsgds"
    audit = ("INSERT", "UPDATE", "DELETE")

    def _ok(self, S, expr):
        return f"({S.is_ho()} or ({S.is_zm()} and {S.in_my_districts(expr)}))"

    def insert_check(self, ctx, S, P, new):
        return self._ok(S, f"{P.add(new['district_id'])}::smallint")

    def update_using(self, ctx, S, a):
        return self._ok(S, a + ".district_id")

    def update_check(self, ctx, S, P, new):
        return self._ok(S, f"{P.add(new['district_id'])}::smallint")

    def delete_using(self, ctx, S, a):
        return self._ok(S, a + ".district_id")


class Contacts(Rules):
    api = "contacts"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"created_by": lambda c: c.uid, "created_at": lambda c: now(), "is_decision_maker": False}

    def insert_check(self, ctx, S, P, new):
        verified_ok = "true" if (ctx.role != TSO or new.get("verified_by") is None) else "false"
        return f"({S.can_see_lsgd(uu(P, new['lsgd_id']))} and {verified_ok})"

    def update_using(self, ctx, S, a):
        # a TSO corrects a person's details until a manager has confirmed them by phone; then they are evidence and stay as they are
        return f"(({S.role_in(ZM, HO)} or ({S.role_in(TSO)} and {a}.verified_at is null)) and {S.can_see_lsgd(a + '.lsgd_id')})"

    def update_check(self, ctx, S, P, new):
        return S.can_see_lsgd(uu(P, new["lsgd_id"]))

    def before_update(self, ctx, old, new, keys):
        new["created_by"], new["created_at"], new["lsgd_id"] = old["created_by"], old["created_at"], old["lsgd_id"]
        if not trim(new.get("name")):
            raise ApiError("Enter the person's name.")
        if ctx.role == TSO:
            new["verified_by"], new["verified_at"] = old["verified_by"], old["verified_at"]
        elif new.get("verified_at") is not None and old.get("verified_at") is None:
            new["verified_by"], new["verified_at"] = ctx.uid, now()
        elif old.get("verified_at") is not None:
            new["verified_by"], new["verified_at"] = old["verified_by"], old["verified_at"]
        return new


class LsgdUpdates(Rules):
    """Work on an LSGD recorded without a check-in: what was said and by whom, for work done before the app or by phone.
    It is a note for the LSGD's history, not a visit: no GPS, no TA / DA, no review."""
    api = "lsgd_updates"
    audit = ("INSERT",)
    defaults = {"tso_id": lambda c: c.uid, "mode": "visit", "contact_ids": [], "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return f"({S.role_in(TSO, ZM)} and {S.can_see_lsgd(uu(P, new['lsgd_id']))})"

    def before_insert(self, ctx, new):
        new["tso_id"], new["created_at"] = ctx.uid, now()
        new["discussion"], new["outcome"] = trim(new.get("discussion")), trim(new.get("outcome")) or None
        if len(new["discussion"]) < 20:
            raise ApiError("Write a few lines about what they said (at least 20 characters).")
        if new.get("happened_on") is None:
            raise ApiError("Enter the date it happened.")
        if new["happened_on"] > ist_today():
            raise ApiError("The date can't be in the future.")
        if new.get("interest_level") is not None and not 1 <= new["interest_level"] <= 5:
            raise ApiError("Choose how interested they are.")
        ids = list(dict.fromkeys(new.get("contact_ids") or []))
        if ids and fetch_one("select count(*) as n from kwd_contacts where id = any(%(i)s) and lsgd_id = %(l)s",
                             {"i": ids, "l": new["lsgd_id"]})["n"] != len(ids):
            raise ApiError("Pick people from this LSGD only.")
        new["contact_ids"] = ids
        return new


class Tasks(Rules):
    """A planned visit. 'Done' is set only by a visit (see visits.py), never by hand."""
    api = "tasks"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"status": "planned"}

    def _using(self, ctx, S, a):
        return f"({S.is_ho()} or ({S.is_zm()} and {S.can_see_lsgd(a + '.lsgd_id')}))"

    def insert_check(self, ctx, S, P, new):
        return (f"({S.is_ho()} or ({S.is_zm()} and {S.can_see_lsgd(uu(P, new['lsgd_id']))} and {S.is_my_tso(uu(P, new['assigned_to']))}))")

    def update_using(self, ctx, S, a):
        return self._using(ctx, S, a)

    def update_check(self, ctx, S, P, new):
        return self.insert_check(ctx, S, P, new)

    def delete_using(self, ctx, S, a):
        return self._using(ctx, S, a)

    def before_insert(self, ctx, new):
        new["assigned_by"] = ctx.uid
        new["created_at"] = now()
        new["status"] = "planned"
        return new

    def before_update(self, ctx, old, new, keys):
        new["assigned_by"], new["created_at"] = old["assigned_by"], old["created_at"]
        if new["status"] == "done" and old["status"] != "done":
            raise ApiError("A task is marked done only by a visit")
        return new


class Opportunities(Rules):
    api = "opportunities"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"owner_id": lambda c: c.uid, "financial_year": "2026-27", "stage": "new", "expected_units": 0,
                "unit_price": 5880, "probability": 10, "updated_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return S.can_see_lsgd(uu(P, new["lsgd_id"]))

    def update_using(self, ctx, S, a):
        return S.can_see_lsgd(a + ".lsgd_id")

    def update_check(self, ctx, S, P, new):
        return S.can_see_lsgd(uu(P, new["lsgd_id"]))

    def before_update(self, ctx, old, new, keys):
        new["updated_at"] = now()
        return new


class Followups(Rules):
    api = "followups"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"assigned_to": lambda c: c.uid, "mode": "visit", "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        mine = "true" if new["assigned_to"] == ctx.uid else "false"
        return f"({S.can_see_lsgd(uu(P, new['lsgd_id']))} and ({mine} or {S.role_in(ZM, HO)}))"

    def update_using(self, ctx, S, a):
        return f"({a}.assigned_to = {S.me} or ({S.role_in(ZM, HO)} and {S.can_see_lsgd(a + '.lsgd_id')}))"

    def update_check(self, ctx, S, P, new):
        return S.can_see_lsgd(uu(P, new["lsgd_id"]))

    def before_insert(self, ctx, new):
        new["created_at"] = now()
        if new.get("done_at") is not None:
            new["done_at"] = now()
        return new

    def before_update(self, ctx, old, new, keys):
        new["created_at"] = old["created_at"]
        if old.get("done_at") is not None:
            new["done_at"] = old["done_at"]
        elif new.get("done_at") is not None:
            new["done_at"] = now()
        return new


class VerificationCalls(Rules):
    """A manager phoned someone who was met on a visit and records what they said."""
    api = "verification_calls"
    defaults = {"outcome": "confirmed", "called_by": lambda c: c.uid, "called_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return (f"({S.role_in(ZM, HO)} and exists (select 1 from kwd_contacts c where c.id = {uu(P, new['contact_id'])} "
                f"and {S.can_see_lsgd('c.lsgd_id')}))")

    def before_insert(self, ctx, new):
        new["called_by"], new["called_at"] = ctx.uid, now()
        new["confirmed"] = {"confirmed": True, "denied": False}.get(new.get("outcome"))
        return new


class ExpensePolicy(Rules):
    """The one row of TA/DA rates and limits. Only Head Office changes it, and every change is logged."""
    api = "expense_policy"

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO

    def before_update(self, ctx, old, new, keys):
        new["id"], new["updated_by"], new["updated_at"] = 1, ctx.uid, now()
        return new

    def after_update(self, ctx, old, row, keys):
        from kwd.rules.util import to_json
        from psycopg.types.json import Jsonb
        from core.services.common import fetch_one
        fetch_one("insert into kwd_audit_log (table_name, row_id, action, old_data, new_data, actor) values ('expense_policy', null, 'UPDATE', %(o)s, %(n)s, %(u)s) returning id",
                  {"o": Jsonb(to_json(old)), "n": Jsonb(to_json(row)), "u": ctx.uid})
