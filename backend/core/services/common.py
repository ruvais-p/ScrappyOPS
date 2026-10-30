"""Shared pieces for every action: the error type, who is calling, and small database helpers."""
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from django.db import connection
from django.utils import timezone

from core.models import AuthSession, HqAudit, Profile

SESSION_MSG = "You were logged out because this account was opened on another device."


class ApiError(Exception):
    """A problem the person should read. Becomes an HTTP 400 with {"message": ...}."""

    def __init__(self, message, status=400, code="P0001", details=None, hint=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details
        self.hint = hint


class Ctx:
    """Who is making this request. role/franchise come from the person's profile; an inactive person, or a login that
    was replaced by a newer one, has no role at all (so nothing works for them)."""

    def __init__(self, user_id, session_id=None):
        self.uid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))   # compared with ids in the database, which are UUIDs
        self.session_id = session_id
        self._valid = None
        self._profile = False

    def session_valid(self):
        if self._valid is None:
            if not self.session_id:
                self._valid = True
            else:
                self._valid = AuthSession.objects.filter(id=self.session_id, user_id=self.uid, expires_at__gt=timezone.now()).exists()
        return self._valid

    @property
    def profile(self):
        if self._profile is False:
            p = Profile.objects.filter(pk=self.uid, active=True).first() if self.session_valid() else None
            self._profile = p
        return self._profile

    @property
    def role(self):
        return self.profile.role if self.profile else None

    @property
    def franchise_id(self):
        return self.profile.franchise_id if self.profile else None

    # ---- the same helper names the database used ----
    def my_role(self):
        return self.role

    def my_franchise(self):
        return self.franchise_id

    def need_session(self):
        if not self.session_valid():
            raise ApiError(SESSION_MSG)

    def fr_ok(self, franchise_id):
        """May this person act on a row of this franchise? HQ: always. Warehouse/supervisor: only their own."""
        r = self.role
        if r == "hq":
            return True
        if r in ("warehouse", "supervisor"):
            return franchise_id is not None and franchise_id == self.franchise_id
        return False

    def fr_scope(self, requested):
        """The franchise a report covers: staff always get their own; HQ gets what it asked for (None = all)."""
        r = self.role
        if r == "hq":
            return requested
        if r in ("warehouse", "supervisor"):
            if self.franchise_id is None:
                raise ApiError("Your login is not assigned to a franchise.")
            return self.franchise_id
        raise ApiError("Not allowed.")


def hq_log(ctx, action, ref, detail=None, franchise_id=None):
    HqAudit.objects.create(by_id=ctx.uid, action=action, ref=ref, detail=detail, franchise_id=franchise_id)


# ---------------------------------------------------------------------------------------------- database helpers
def fetch(sql, params=None):
    """Run a query, return a list of dicts (column name -> value)."""
    with connection.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [c.name for c in cur.description]
        jsoncols = [i for i, c in enumerate(cur.description) if c.type_code in (114, 3802)]   # json / jsonb arrive as text
        out = []
        for row in cur.fetchall():
            if jsoncols:
                row = list(row)
                for i in jsoncols:
                    if isinstance(row[i], str):
                        row[i] = json.loads(row[i])
            out.append(dict(zip(cols, row)))
        return out


def fetch_one(sql, params=None):
    rows = fetch(sql, params)
    return rows[0] if rows else None


def scalar(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or {})
        row = cur.fetchone()
        return row[0] if row else None


def advisory_lock(a, b):
    """Only one release/re-weigh per material and franchise at a time (released at the end of the transaction)."""
    with connection.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(%s, %s)", [int(a), int(b)])


# ---------------------------------------------------------------------------------------------- small value helpers
def dec(v, field="value"):
    """Turn a number from the request into a Decimal, or fail with a plain message."""
    if v is None or isinstance(v, bool):
        raise ApiError(f"Enter the {field}.")
    try:
        d = Decimal(str(v).strip())
    except Exception:
        raise ApiError(f"Enter the {field}.")
    if not d.is_finite():
        raise ApiError(f"Enter the {field}.")
    return d


def round_half_up(d, places=2):
    return Decimal(d).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def fixed_decimal(value, field, places, digits):
    """Validate before calculations so the database cannot silently round an input."""
    value = dec(value, field)
    if abs(value) >= Decimal(10) ** (digits - places):
        raise ApiError(f"The {field} is too large.")
    try:
        rounded = round_half_up(value, places)
    except InvalidOperation:
        raise ApiError(f"Enter a valid {field}.")
    if rounded != value:
        raise ApiError(f"Enter the {field} with at most {places} decimal places.")
    return rounded


def show_num(d, places=None):
    """Print a number the way the database printed it inside messages."""
    d = Decimal(d)
    if places is not None:
        d = round_half_up(d, places)
    return format(d, "f")


def btrim(s):
    return (s or "").strip()


def blank(s):
    return len(btrim(s)) == 0


def nullify(s):
    s = btrim(s)
    return s or None


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
