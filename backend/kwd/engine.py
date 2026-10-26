"""The query engine. The pages send structured queries (the same shape the old data library built: select with nested
tables, filters, ordering, counts, single row, insert / update / delete / upsert). This runs them against the database,
cuts every read down to the rows the caller may see (scope.py) and sends every write through that table's rules
(kwd/rules/*.py: what the old database triggers did)."""
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from django.db import connection

from core.services.common import ApiError, fetch, fetch_one
from kwd import schema as S
from kwd.scope import Params, Scope

PKS = {"user_districts": ("user_id", "district_id"), "visit_contacts": ("visit_id", "contact_id")}
MAX_ROWS = 5000


def pk_of(api):
    return PKS.get(api, ("id",))


# ---------------------------------------------------------------------------------------------- value types
def coerce(v, typ, col="value"):
    if v is None:
        return None
    try:
        if typ == "u":
            return v if isinstance(v, UUID) else UUID(str(v))
        if typ == "ts":
            if isinstance(v, datetime):
                return v
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            if d.tzinfo is None:
                from datetime import timezone
                d = d.replace(tzinfo=timezone.utc)
            return d
        if typ == "d":
            return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])
        if typ == "n":
            return v if isinstance(v, Decimal) else Decimal(str(v))
        if typ == "i":
            if isinstance(v, bool):
                raise ValueError
            f = Decimal(str(v))
            if f != f.to_integral_value():
                raise ValueError
            return int(f)
        if typ == "f":
            return float(v)
        if typ == "b":
            if isinstance(v, bool):
                return v
            if str(v).lower() in ("true", "false"):
                return str(v).lower() == "true"
            raise ValueError
        if typ == "a":
            return [str(x) for x in v]
        if typ == "ua":
            return [x if isinstance(x, UUID) else UUID(str(x)) for x in v]
        if typ == "j":
            return v
        return str(v)
    except Exception:
        raise ApiError(f'invalid input for column "{col}"', code="22P02")


# ---------------------------------------------------------------------------------------------- select parsing
def _split_top(s):
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


EMBED_RE = re.compile(r"^(?:(\w+):)?(\w+)((?:![\w]+)*)\((.*)\)$", re.S)


def parse_select(s):
    nodes = []
    for item in _split_top(s or "*"):
        if item == "*":
            nodes.append(("star",))
            continue
        m = EMBED_RE.match(item)
        if m:
            alias, target, hints, inner = m.group(1), m.group(2), [h for h in m.group(3).split("!") if h], m.group(4)
            nodes.append(("embed", alias or target, target, [h for h in hints if h not in ("inner", "left")], "inner" in hints, parse_select(inner)))
        else:
            if not re.match(r"^\w+$", item):
                raise ApiError(f'failed to parse select "{item}"', code="PGRST100")
            nodes.append(("col", item))
    return nodes


def resolve_relation(parent, target, hints):
    """How is `target` linked to `parent`? Returns (kind, target api name, parent column, target column)."""
    for fk in S.FKS:
        child, ccol, par, name = fk
        if hints and name not in hints:
            continue
        if child == parent and par == target:                  # parent holds the link: one row
            return "one", target, ccol, "id"
        if par == parent and child == target:                  # target holds the link: many rows
            return "many", target, "id", ccol
        if hints and name in hints and child == parent == par:
            return "one", target, ccol, "id"
    if target in S.TABLES or target in S.VIEW_COLUMNS:
        pass
    raise ApiError(f"Could not find a relationship between '{parent}' and '{target}' in the schema cache", status=400, code="PGRST200")


# ---------------------------------------------------------------------------------------------- reading
class Reader:
    def __init__(self, ctx):
        self.ctx = ctx
        self.P = Params(ctx)
        self.scope = Scope(ctx, self.P)
        self.n = 0

    def alias(self):
        self.n += 1
        return f"e{self.n}"

    def source(self, api, alias):
        """FROM piece for a table or view, already cut down to what the caller may see."""
        if api in S.VIEW_COLUMNS:
            return f"({self.scope.view_sql(api)}) {alias}", "true"
        if api not in S.TABLES:
            raise ApiError(f"Could not find the table 'public.{api}' in the schema cache", status=404, code="PGRST205")
        return f"{S.table_of(api)} {alias}", self.scope.read(api, alias)

    def obj(self, api, nodes, a):
        columns = S.columns_of(api)
        has_star = any(n[0] == "star" for n in nodes)
        names = [n[1] for n in nodes if n[0] == "col"]
        for c in names:
            if c not in columns:
                raise ApiError(f"Could not find the '{c}' column of '{api}' in the schema cache", code="42703")
        if has_star:
            expr = f"to_jsonb({a})"
        elif names:
            expr = "jsonb_build_object(" + ", ".join(f"'{c}', {a}.{c}" for c in names) + ")"
        else:
            expr = "'{}'::jsonb"
        for n in nodes:
            if n[0] != "embed":
                continue
            _, key, target, hints, inner, children = n
            kind, tapi, pcol, tcol = resolve_relation(api, target, hints)
            e = self.alias()
            src, scope = self.source(tapi, e)
            inner_obj = self.obj(tapi, children, e)
            if kind == "one":
                sub = f"(select {inner_obj} from {src} where {e}.{tcol} = {a}.{pcol} and {scope} limit 1)"
            else:
                sub = f"coalesce((select jsonb_agg({inner_obj}) from {src} where {e}.{tcol} = {a}.{pcol} and {scope}), '[]'::jsonb)"
            expr += f" || jsonb_build_object('{key}', {sub})"
        return expr

    def cond(self, api, a, f, columns):
        """One filter -> SQL. f = [op, column, value] or ['not', column, op, value]."""
        neg = False
        if f[0] == "not":
            neg, f = True, [f[2], f[1], f[3]]
        op, col, val = f[0], f[1], f[2]
        if col not in columns:
            raise ApiError(f"column {api}.{col} does not exist", code="42703")
        typ = S.TYPES[columns[col]]
        ref = f"{a}.{col}"
        sql_op = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        if op in sql_op:
            if val is None:
                c = f"{ref} is null" if op == "eq" else f"{ref} is not null"
            else:
                c = f"{ref} {sql_op[op]} {self.P.add(coerce(val, columns[col], col))}::{typ}"
        elif op == "is":
            c = f"{ref} is null" if val is None else f"{ref} is {'true' if val else 'false'}"
        elif op == "in":
            if not isinstance(val, list):
                raise ApiError("in needs a list", code="PGRST100")
            c = "false" if not val else f"{ref} = any({self.P.add([coerce(x, columns[col], col) for x in val])}::{typ}[])"
        elif op in ("like", "ilike"):
            c = f"{ref} {op} {self.P.add(str(val))}"
        else:
            raise ApiError(f"unsupported filter {op}", code="PGRST100")
        return f"not ({c})" if neg else c

    def build_where(self, api, a, filters, nodes):
        columns = S.columns_of(api)
        conds = []
        embed_extra = {}
        for f in filters or []:
            col = f[1] if f[0] != "not" else f[1]
            if "." in col:
                alias, sub = col.split(".", 1)
                g = list(f)
                g[1] = sub
                embed_extra.setdefault(alias, []).append(g)
            else:
                conds.append(self.cond(api, a, f, columns))
        for n in nodes:
            if n[0] == "embed" and n[4]:                      # !inner: the parent needs a matching row
                _, key, target, hints, inner, children = n
                kind, tapi, pcol, tcol = resolve_relation(api, target, hints)
                e = self.alias()
                src, scope = self.source(tapi, e)
                tcols = S.columns_of(tapi)
                extra = "".join(" and " + self.cond(tapi, e, g, tcols) for g in embed_extra.get(key, []))
                conds.append(f"exists (select 1 from {src} where {e}.{tcol} = {a}.{pcol} and {scope}{extra})")
        return conds

    def select(self, api, select_str, filters=None, order=None, limit=None, offset=0, count=False, head=False, extra_where=None):
        nodes = parse_select(select_str)
        src, scope = self.source(api, "t")
        where = [scope] + self.build_where(api, "t", filters, nodes) + (extra_where or [])
        w = " and ".join(where)
        columns = S.columns_of(api)
        total = None
        if count:
            total = fetch_one(f"select count(*) as c from {src} where {w}", self.P.values)["c"]
            if head:
                return [], total
        order_sql = ""
        if order:
            parts = []
            for o in order:
                col, asc = o[0], o[1] if len(o) > 1 else True
                if col not in columns:
                    raise ApiError(f"column {api}.{col} does not exist", code="42703")
                nulls = ""
                if len(o) > 2 and o[2] is not None:
                    nulls = " nulls first" if o[2] else " nulls last"
                parts.append(f"t.{col} {'asc' if asc else 'desc'}{nulls}")
            order_sql = " order by " + ", ".join(parts)
        lim = min(int(limit), MAX_ROWS) if limit is not None else MAX_ROWS
        sql = f"select {self.obj(api, nodes, 't')} as j from {src} where {w}{order_sql} limit {lim} offset {int(offset or 0)}"
        rows = [r["j"] for r in fetch(sql, self.P.values)]
        return rows, total


def pk_condition(api, row, R):
    """'t.id = <value>' for one row, for re-reading what was just written."""
    return " and ".join(f"t.{c} = {R.P.add(row[c])}" for c in pk_of(api))


# ---------------------------------------------------------------------------------------------- the request
def run_query(ctx, q):
    """q: {table, op, select, filters, order, limit, range, single, maybe, count, head, values, onConflict, returning}
    Returns {"data": ..., "count": ...}."""
    from kwd.rules import RULES
    api, op = q.get("table"), q.get("op", "select")
    if api not in S.TABLES and api not in S.VIEW_COLUMNS:
        raise ApiError(f"Could not find the table 'public.{api}' in the schema cache", status=404, code="PGRST205")
    ctx.need_active() if op != "select" else None
    sel = q.get("select")
    filters = q.get("filters") or []

    if op == "select":
        R = Reader(ctx)
        limit, offset = q.get("limit"), 0
        if q.get("range"):
            offset, limit = int(q["range"][0]), int(q["range"][1]) - int(q["range"][0]) + 1
        rows, total = R.select(api, sel or "*", filters, q.get("order"), limit, offset, bool(q.get("count")), bool(q.get("head")))
        return finish(rows, total, q)

    rules = RULES.get(api)
    if rules is None:
        raise ApiError(f'permission denied for table {api}', status=403, code="42501")
    affected = []
    if op in ("insert", "upsert"):
        vals = q.get("values")
        for v in (vals if isinstance(vals, list) else [vals]):
            if op == "upsert":
                row = rules.upsert(ctx, v, q.get("onConflict"), bool(q.get("ignoreDuplicates")))
                if row is not None:
                    affected.append(row)
            else:
                affected.append(rules.insert(ctx, v))
    elif op in ("update", "delete"):
        R = Reader(ctx)
        # the rows the caller may touch: matching the filters and passing the table's USING rule
        using = rules.update_using(ctx, R.scope, "t") if op == "update" else rules.delete_using(ctx, R.scope, "t")
        nodes = []
        where = [using] + R.build_where(api, "t", filters, nodes)
        sql = f"select t.* from {S.table_of(api)} t where {' and '.join(where)} for update"
        olds = fetch(sql, R.P.values)
        for old in olds:
            affected.append(rules.update(ctx, old, q.get("values") or {}) if op == "update" else rules.delete(ctx, old))
    else:
        raise ApiError("unknown operation", code="PGRST100")

    if not sel and not q.get("returning"):
        return {"data": None, "count": len(affected)}
    R = Reader(ctx)
    if not affected:
        return finish([], None, q)
    if op == "delete":                                         # deleted rows are gone: give back what was removed
        return finish([jsonable_row(api, r) for r in affected], None, q)
    where = " or ".join("(" + pk_condition(api, r, R) + ")" for r in affected)
    rows, _ = R.select(api, sel or "*", None, None, None, 0, False, False, extra_where=[f"({where})"])
    return finish(rows, None, q)


def jsonable_row(api, row):
    return {k: v for k, v in row.items()}


def finish(rows, total, q):
    if q.get("single") or q.get("maybe"):
        if len(rows) == 1:
            return {"data": rows[0], "count": total}
        if not rows and q.get("maybe"):
            return {"data": None, "count": total}
        raise ApiError("JSON object requested, multiple (or no) rows returned", status=406, code="PGRST116")
    if q.get("head"):
        return {"data": None, "count": total}
    return {"data": rows, "count": total}
