"""How a write to one table works. The base class does the plumbing the database used to do: fill in defaults, run the
table's "trigger" (before_*), check the security rule, write the row, run the after-trigger, and add the audit entry.
Each table then overrides only what is special about it."""
from psycopg.types.json import Jsonb

from core.services.common import ApiError, fetch, fetch_one
from kwd import schema as S
from kwd.engine import coerce, pk_of
from kwd.rules.util import check, rls_error, to_json


class Rules:
    api = ""
    audit = ()                 # which of 'INSERT', 'UPDATE', 'DELETE' go to the audit log
    defaults = {}              # column -> value or callable(ctx)

    # ---- security rules (return True/False or SQL text) ----
    def insert_check(self, ctx, S_, P, new):
        return False

    def update_using(self, ctx, S_, a):
        return "false"

    def update_check(self, ctx, S_, P, new):
        return True

    def delete_using(self, ctx, S_, a):
        return "false"

    # ---- "triggers" ----
    def before_insert(self, ctx, new):
        return new

    def after_insert(self, ctx, row):
        pass

    def before_update(self, ctx, old, new, keys):
        return new

    def after_update(self, ctx, old, row, keys):
        pass

    def before_delete(self, ctx, old):
        pass

    def after_delete(self, ctx, old):
        pass

    # ---- plumbing ----
    @property
    def table(self):
        return S.table_of(self.api)

    @property
    def columns(self):
        return S.TABLES[self.api][1]

    @property
    def generated(self):
        return S.TABLES[self.api][2]

    def _coerce_values(self, values, for_update=False):
        out = {}
        for k, v in (values or {}).items():
            if k not in self.columns:
                raise ApiError(f"Could not find the '{k}' column of '{self.api}' in the schema cache", code="PGRST204")
            if k in self.generated:
                raise ApiError(f'column "{k}" can only be updated to DEFAULT', code="428C9")
            out[k] = coerce(v, self.columns[k], k)
        return out

    def _db_value(self, col, v):
        return Jsonb(v) if self.columns[col] == "j" and v is not None else v

    def _audit(self, ctx, op, old, new, row_id):
        if op not in self.audit:
            return
        fetch_one("insert into kwd_audit_log (table_name, row_id, action, old_data, new_data, actor) values (%(t)s, %(r)s, %(a)s, %(o)s, %(n)s, %(u)s) returning id",
                  {"t": self.api, "r": row_id, "a": op, "o": Jsonb(to_json(old)) if old is not None else None,
                   "n": Jsonb(to_json(new)) if new is not None else None, "u": ctx.uid})

    def _row_id(self, row):
        return row.get("id") if "id" in row and self.columns.get("id") == "u" else None

    # ---- operations ----
    def insert(self, ctx, values):
        if ctx.role is None:
            raise rls_error(self.api)
        new = self._coerce_values(values)
        for col, d in self.defaults.items():
            if col not in new:
                new[col] = d(ctx) if callable(d) else d
        new = self.before_insert(ctx, new) or new
        if not check(ctx, lambda S_, P: self.insert_check(ctx, S_, P, new)):
            raise rls_error(self.api)
        cols = list(new)
        sql = f"insert into {self.table} ({', '.join(cols)}) values ({', '.join('%(' + c + ')s' for c in cols)}) returning *"
        row = fetch_one(sql, {c: self._db_value(c, new[c]) for c in cols})
        self.after_insert(ctx, row)
        self._audit(ctx, "INSERT", None, row, self._row_id(row))
        return row

    def update(self, ctx, old, values):
        keys = list((values or {}).keys())
        patch = self._coerce_values(values)
        new = {**old, **patch}
        new = self.before_update(ctx, old, new, keys) or new
        if not check(ctx, lambda S_, P: self.update_check(ctx, S_, P, new)):
            raise rls_error(self.api)
        changed = [c for c in self.columns if c not in self.generated and new.get(c) != old.get(c)]
        row = old
        if changed:
            where = " and ".join(f"{c} = %(pk_{c})s" for c in pk_of(self.api))
            params = {c: self._db_value(c, new[c]) for c in changed}
            params.update({f"pk_{c}": old[c] for c in pk_of(self.api)})
            row = fetch_one(f"update {self.table} set {', '.join(c + ' = %(' + c + ')s' for c in changed)} where {where} returning *", params)
        self.after_update(ctx, old, row, keys)
        self._audit(ctx, "UPDATE", old, row, self._row_id(row))
        return row

    def delete(self, ctx, old):
        self.before_delete(ctx, old)
        where = " and ".join(f"{c} = %(pk_{c})s" for c in pk_of(self.api))
        fetch(f"delete from {self.table} where {where} returning 1", {f"pk_{c}": old[c] for c in pk_of(self.api)})
        self.after_delete(ctx, old)
        self._audit(ctx, "DELETE", old, None, self._row_id(old))
        return old

    def upsert(self, ctx, values, on_conflict, ignore_duplicates=False):
        from kwd.scope import Params, Scope
        if on_conflict is not None and not isinstance(on_conflict, str):
            raise ApiError("Invalid conflict columns.", code="PGRST100")
        cols = [c.strip() for c in (on_conflict or ",".join(pk_of(self.api))).split(",")]
        if not cols or len(set(cols)) != len(cols) or any(c not in self.columns or c in self.generated for c in cols):
            raise ApiError("Invalid conflict columns.", code="PGRST100")
        coerced = self._coerce_values(values)
        if ignore_duplicates:
            if not check(ctx, lambda S_, P_: self.insert_check(ctx, S_, P_, coerced)):
                raise rls_error(self.api)
        if all(c in coerced for c in cols):
            where = " and ".join(f"{c} = %({c})s" for c in cols)
            old = fetch_one(f"select * from {self.table} where {where} for update", {c: coerced[c] for c in cols})
            if old is not None:
                if ignore_duplicates:
                    return None
                P = Params(ctx)
                using = self.update_using(ctx, Scope(ctx, P), "t")
                ok = fetch_one(f"select ({using}) as ok from {self.table} t where " + " and ".join(f"t.{c} = %({c})s" for c in cols),
                               {**P.values, **{c: coerced[c] for c in cols}})
                if not ok or not ok["ok"]:
                    raise rls_error(self.api)
                return self.update(ctx, old, values)
        return self.insert(ctx, values)
