"""Reading tables and views, in the same URL format the dashboards already use:
   GET /rest/v1/loads?select=id,code&driver_id=eq.<id>&status=in.(open,submitted)&order=id.desc&limit=10
Only the tables listed here can be read, only the columns listed, and each role sees only its own rows
(a collector: their own; warehouse and supervisor: their franchise; HQ: everything). Nothing here can write,
except HQ adding rows to the lead upload inbox."""
import re

from core.services.common import ApiError, fetch

MAX_ROWS = 5000

# column types: i integer, u uuid, t text, n numeric, b boolean, ts timestamptz, d date, j json
T = {"i": "integer", "u": "uuid", "t": "text", "n": "numeric", "b": "boolean", "ts": "timestamptz", "d": "date", "j": "jsonb"}


def cols(spec):
    return dict(p.split(":") for p in spec.split())


LOADS = cols("id:i code:t driver_id:u franchise_id:i vehicle_no:t status:t started_at:ts submitted_at:ts warehouse_kg:n checked_by:u "
             "weighed_at:ts weighing_note:t resolved_by:u resolved_at:ts resolution_note:t")
BILLS = cols("id:i bill_no:t lead_id:i load_id:i status:t sent_at:ts confirmed_at:ts payment_method:t upi_ref:t paid_at:ts created_at:ts "
             "confirm_proof_url:t whatsapp_opened_at:ts pdf_path:t share_token:u")

# scopes: a SQL condition on the table's own columns. :role, :uid, :fr are the caller's.
OWN_OR_FRANCHISE = "({own} or %(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and franchise_id = %(s_fr)s::integer))"
STAFF_FRANCHISE = "(%(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and franchise_id = %(s_fr)s::integer))"
LOAD_VISIBLE = "(select id from loads where driver_id = %(s_uid)s::uuid or %(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and franchise_id = %(s_fr)s::integer))"
ANY_LOGIN = "true"

TABLES = {
    "profiles": (cols("id:u full_name:t phone:t role:t territory:t vehicle_no:t active:b is_super_admin:b created_at:ts franchise_id:i"),
                 "(id = %(s_uid)s::uuid or %(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and (role = 'hq' or franchise_id = %(s_fr)s::integer)))"),
    "franchises": (cols("id:i code:t name:t district:t constituency:t active:b created_at:ts"),
                   "(%(s_role)s in ('hq','super_admin') or id = %(s_fr)s::integer)"),
    "scrap_items": (cols("id:i name:t active:b"), ANY_LOGIN),
    "rates": (cols("id:i item_id:i rate_per_kg:n effective_from:ts set_by:u"), ANY_LOGIN),
    "current_rates": (cols("item_id:i item_name:t rate_per_kg:n effective_from:ts"), ANY_LOGIN),
    "driver_cash_in_hand": (cols("driver_id:u full_name:t cash_in_hand:n"),
                            "(driver_id = %(s_uid)s::uuid or %(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and "
                            "driver_id in (select id from profiles where franchise_id = %(s_fr)s::integer)))"),
    "cash_ledger": (cols("id:i driver_id:u entry_type:t amount:n bill_id:i note:t created_by:u created_at:ts franchise_id:i"),
                    OWN_OR_FRANCHISE.format(own="driver_id = %(s_uid)s::uuid")),
    "loads": (LOADS, OWN_OR_FRANCHISE.format(own="driver_id = %(s_uid)s::uuid")),
    "load_item_totals": (cols("load_id:i load_code:t driver_id:u item_name:t total_kg:n total_value:n"), f"load_id in {LOAD_VISIBLE}"),
    "bill_totals": (cols("bill_id:i bill_no:t lead_id:i load_id:i status:t payment_method:t total_kg:n total_amount:n"), f"load_id in {LOAD_VISIBLE}"),
    "bills": (BILLS, f"load_id in {LOAD_VISIBLE}"),
    "bill_items": (cols("id:i bill_id:i item_id:i qty_kg:n rate_per_kg:n amount:n photo_url:t typed_by_hand:b"),
                   f"bill_id in (select id from bills where load_id in {LOAD_VISIBLE})"),
    "leads": (cols("id:i code:t customer_id:i driver_id:u franchise_id:i slot:ts items_said:t status:t created_by:u created_at:ts closed_at:ts "
                   "latitude:n longitude:n fail_reason:t fail_note:t failed_at:ts"), OWN_OR_FRANCHISE.format(own="driver_id = %(s_uid)s::uuid")),
    "load_weighings": (cols("id:i load_id:i item_id:i billed_kg:n warehouse_kg:n within_tolerance:b weighed_by:u weighed_at:ts superseded_at:ts franchise_id:i"),
                       "(%(s_role)s = 'hq' or (%(s_role)s in ('warehouse','supervisor') and franchise_id = %(s_fr)s::integer) "
                       "or load_id in (select id from loads where driver_id = %(s_uid)s::uuid))"),
    "hq_requirements": (cols("id:i code:t item_id:i required_kg:n due_date:d note:t status:t raised_by:u created_at:ts cancelled_at:ts cancel_note:t franchise_id:i"),
                        STAFF_FRANCHISE),
    "hq_requirement_progress": (cols("id:i code:t item_id:i item_name:t required_kg:n released_kg:n remaining_kg:n due_date:d raised_on:d note:t status:t is_overdue:b franchise_id:i"),
                                STAFF_FRANCHISE),
    "hq_releases": (cols("id:i code:t requirement_id:i item_id:i kg:n vehicle_no:t note:t released_by:u released_at:ts franchise_id:i"), STAFF_FRANCHISE),
    "wh_stock_movements": (cols("day:d kind:t item_id:i item_name:t kg:n ref:t happened_at:ts franchise_id:i"), STAFF_FRANCHISE),
    "cash_settlements": (cols("id:i load_id:i driver_id:u expected_cash:n counted_cash:n difference:n cash_paid:n upi_paid:n status:t counted_by:u counted_at:ts "
                              "count_note:t verified_by:u verified_at:ts verify_note:t franchise_id:i covered_load_ids:j"),
                         OWN_OR_FRANCHISE.format(own="driver_id = %(s_uid)s::uuid")),
    "settlement_resolutions": (cols("id:i settlement_id:i decision:t note:t resolved_by:u resolved_at:ts"),
                               "settlement_id in (select id from cash_settlements where driver_id = %(s_uid)s::uuid or %(s_role)s = 'hq' or "
                               "(%(s_role)s in ('warehouse','supervisor') and franchise_id = %(s_fr)s::integer))"),
    "hq_audit": (cols("id:i at:ts by_id:u action:t ref:t detail:j franchise_id:i"), "%(s_role)s = 'hq'"),
    "lead_import": (cols("id:i customer_name:t phone:t address:t area:t upi_id:t driver_email:t pickup_date:t pickup_time:t items:t status:t message:t "
                         "lead_code:t imported_at:ts latitude:t longitude:t franchise_code:t"), "%(s_role)s = 'hq'"),
}

OPS = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _bad(msg, code="PGRST100"):
    return ApiError(msg, status=400, code=code)


def query_table(ctx, table, params):
    """params: a dict of query-string values (name -> text). Returns a list of row dicts."""
    if not ctx.session_valid() or ctx.role is None:
        raise ApiError("Please log in again.", status=401, code="PGRST301")
    if table not in TABLES:
        raise ApiError(f"Could not find the table 'public.{table}' in the schema cache", status=404, code="PGRST205")
    columns, scope = TABLES[table]
    prm = {"s_role": ctx.role or "", "s_uid": str(ctx.uid), "s_fr": ctx.franchise_id}

    # select
    sel = params.get("select", "*")
    if sel.strip() in ("", "*"):
        chosen = list(columns)
    else:
        chosen = [c.strip() for c in sel.split(",") if c.strip()]
        for c in chosen:
            if c not in columns:
                raise ApiError(f"Could not find the '{c}' column of '{table}' in the schema cache", status=400, code="PGRST204")

    # filters
    where, n = [scope], 0
    for key, raw in params.items():
        if key in ("select", "order", "limit", "offset"):
            continue
        if key not in columns:
            raise _bad(f"column {table}.{key} does not exist", "42703")
        typ = T[columns[key]]
        m = re.match(r"^(not\.)?([a-z]+)\.(.*)$", raw, re.S)
        if not m:
            raise _bad(f"failed to parse filter ({raw})")
        neg, op, val = bool(m.group(1)), m.group(2), m.group(3)
        n += 1
        pn = f"f{n}"
        if op in OPS:
            where.append(f"{key} {OPS[op]} %({pn})s::{typ}")
            prm[pn] = val
            cond = where.pop()
            where.append(f"not ({cond})" if neg else cond)
        elif op == "is":
            v = val.lower()
            if v == "null":
                cond = f"{key} is null"
            elif v in ("true", "false"):
                cond = f"{key} is {v}"
            else:
                raise _bad(f"failed to parse filter ({raw})")
            where.append(f"not ({cond})" if neg else cond)
        elif op == "in":
            if not (val.startswith("(") and val.endswith(")")):
                raise _bad(f"failed to parse filter ({raw})")
            items = [x.strip().strip('"') for x in val[1:-1].split(",") if x.strip() != ""]
            prm[pn] = items
            cond = f"{key} = any(%({pn})s::{typ}[])"
            where.append(f"not ({cond})" if neg else cond)
        else:
            raise _bad(f"unsupported filter operator ({op})")

    # order
    order_sql = ""
    if params.get("order"):
        parts = []
        for item in params["order"].split(","):
            bits = item.strip().split(".")
            col = bits[0]
            if col not in columns:
                raise _bad(f"column {table}.{col} does not exist", "42703")
            direction = "desc" if "desc" in bits[1:] else "asc"
            nulls = " nulls first" if "nullsfirst" in bits[1:] else (" nulls last" if "nullslast" in bits[1:] else "")
            parts.append(f"{col} {direction}{nulls}")
        order_sql = " order by " + ", ".join(parts)

    # paging
    try:
        limit = min(int(params["limit"]), MAX_ROWS) if params.get("limit") else MAX_ROWS
        offset = max(int(params.get("offset", 0)), 0)
    except ValueError:
        raise _bad("invalid limit or offset")

    sql = f"select {', '.join(chosen)} from {table} where {' and '.join(where)}{order_sql} limit {limit} offset {offset}"
    return fetch(sql, prm)
