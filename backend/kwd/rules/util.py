import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.services.common import ApiError, fetch_one
from kwd import storage
from kwd.scope import Params, Scope

IST = ZoneInfo("Asia/Kolkata")


def now():
    return datetime.now(timezone.utc)


def ist_today():
    return datetime.now(IST).date()


def ist_date(ts):
    return ts.astimezone(IST).date()


def haversine_m(lat1, lng1, lat2, lng2):
    """Straight-line distance in metres between two GPS points."""
    return 2 * 6371000 * math.asin(math.sqrt(
        math.sin(math.radians(lat2 - lat1) / 2) ** 2 +
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lng2 - lng1) / 2) ** 2))


def check(ctx, build):
    """Evaluate a security rule for a row that is not in the table yet. build(S, P) returns True/False or SQL text."""
    P = Params(ctx)
    S = Scope(ctx, P)
    res = build(S, P)
    if isinstance(res, bool):
        return res
    return bool(fetch_one(f"select ({res}) as ok", P.values)["ok"])


def photo_ok(ctx, path):
    """A photo that the caller uploaded to their own folder and that really exists."""
    return bool(path) and str(path).split("/")[0] == str(ctx.uid) and storage.exists(path)


def to_json(row):
    from core.api.views import Encoder
    return json.loads(json.dumps(row, cls=Encoder))


def rls_error(table):
    return ApiError(f'new row violates row-level security policy for table "{table}"', status=403, code="42501")


def trim(s):
    return (s or "").strip()
