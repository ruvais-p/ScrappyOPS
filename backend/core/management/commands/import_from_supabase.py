"""Copy everything from the old Supabase database into this one: logins (with their passwords), people, franchises,
customers, leads, loads, bills, cash records, weighings, stock releases, the activity log. Ids and codes are kept, so
bill numbers (SB-000123), lead codes (SC-1026) and customer bill links stay the same.

    python manage.py import_from_supabase --source "postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres"
    (add --dry-run to check everything and change nothing)

The source database is only read. Run it on an EMPTY target (right after migrate); it refuses otherwise unless --force.
Passwords: Supabase keeps bcrypt hashes, and those work here unchanged, so nobody needs a new password."""
import psycopg
from psycopg.types.json import Jsonb
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# (target table, source table, order by). Order matters only for readability: foreign keys are checked at the end.
TABLES = [
    ("franchises", "public.franchises", "id"),
    ("profiles", "public.profiles", "created_at, id"),
    ("customers", "public.customers", "id"),
    ("scrap_items", "public.scrap_items", "id"),
    ("rates", "public.rates", "id"),
    ("leads", "public.leads", "id"),
    ("loads", "public.loads", "id"),
    ("bill_items", "public.bill_items", "id"),          # before bills on purpose: a bill that is already sent would refuse new items
    ("bills", "public.bills", "id"),
    ("cash_ledger", "public.cash_ledger", "id"),
    ("lead_import", "public.lead_import", "id"),
    ("load_weighings", "public.load_weighings", "id"),
    ("hq_requirements", "public.hq_requirements", "id"),
    ("hq_releases", "public.hq_releases", "id"),
    ("cash_settlements", "public.cash_settlements", "id"),
    ("settlement_resolutions", "public.settlement_resolutions", "id"),
    ("hq_audit", "public.hq_audit", "id"),
]
GENERATED = {"bill_items": {"amount"}, "cash_settlements": {"difference"}}
COUNTERS = [  # (counter, table, column, prefix, minimum)
    ("lead_code", "leads", "code", "SC-", 1000), ("load_code", "loads", "code", "LD-", 0), ("bill_no", "bills", "bill_no", "SB-", 0),
    ("requirement_code", "hq_requirements", "code", "RQ-", 0), ("release_code", "hq_releases", "code", "RL-", 300),
]


class Command(BaseCommand):
    help = "Copy all data from the old Supabase database (read only) into this database."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Postgres connection string of the Supabase database")
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then undo it")
        parser.add_argument("--force", action="store_true", help="Run even if this database already has data")

    def handle(self, *args, **o):
        with connection.cursor() as c:
            c.execute("select count(*) from users")
            if c.fetchone()[0] and not o["force"]:
                raise CommandError("This database already has logins. Import into an empty one (right after migrate), or use --force.")
        try:
            src = psycopg.connect(o["source"], autocommit=True)
        except Exception as e:
            raise CommandError(f"Could not connect to the source database: {e}")
        src.execute("set default_transaction_read_only = on")       # this command can never change the old database
        try:
            with transaction.atomic():
                self.copy_all(src)
                if o["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING("Dry run: everything checked, nothing was kept."))
        finally:
            src.close()

    # ------------------------------------------------------------------
    def target_columns(self, table):
        with connection.cursor() as c:
            c.execute("select column_name, is_generated, data_type from information_schema.columns where table_schema = 'public' and table_name = %s", [table])
            return {r[0]: (r[1] == "ALWAYS", r[2]) for r in c.fetchall()}

    def source_columns(self, src, schema, table):
        return [r[0] for r in src.execute("select column_name from information_schema.columns where table_schema = %s and table_name = %s order by ordinal_position", [schema, table]).fetchall()]

    def copy_all(self, src):
        with connection.cursor() as cur:
            all_tables = [t for t, _, _ in TABLES] + ["users"]
            for t in all_tables:                                   # the database's own guards would refuse some historic rows
                cur.execute(f'alter table "{t}" disable trigger user')
        try:
            self.copy_users(src)
            for target, source, order in TABLES:
                self.copy_table(src, target, source, order)
            self.fix_counters_and_sequences()
            with connection.cursor() as cur:
                cur.execute("set constraints all immediate")       # check now that every link between records is intact
        finally:
            with connection.cursor() as cur:
                cur.execute("set constraints all immediate")
                for t in all_tables:
                    cur.execute(f'alter table "{t}" enable trigger user')

    def copy_users(self, src):
        rows = src.execute("select id, lower(email), encrypted_password, created_at, last_sign_in_at from auth.users where email is not null order by created_at").fetchall()
        n = 0
        with connection.cursor() as cur:
            for uid, email, pw, created, last in rows:
                hashed = ("bcrypt$" + pw) if pw and pw.startswith("$2") else "!"      # '!' = no usable password: HQ resets it
                cur.execute("insert into users (id, email, password, is_active, created_at, last_login) values (%s, %s, %s, true, %s, %s)", [uid, email, hashed, created, last])
                n += 1
        self.stdout.write(f"users: {n}")

    def copy_table(self, src, target, source, order):
        schema, table = source.split(".")
        tcols = self.target_columns(target)
        scols = self.source_columns(src, schema, table)
        if not scols:
            self.stdout.write(self.style.WARNING(f"{target}: not found in the source, skipped"))
            return
        skip = GENERATED.get(target, set())
        cols = [c for c in scols if c in tcols and not tcols[c][0] and c not in skip]
        dropped = [c for c in scols if c not in cols and c not in skip]
        rows = src.execute(f'select {", ".join(chr(34) + c + chr(34) for c in cols)} from {source} order by {order}').fetchall()
        jsoncols = {i for i, c in enumerate(cols) if tcols[c][1] in ("jsonb", "json")}
        sql = f'insert into "{target}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) values ({", ".join(["%s"] * len(cols))})'
        with connection.cursor() as cur:
            batch = []
            for r in rows:
                r = list(r)
                for i in jsoncols:
                    if r[i] is not None and not isinstance(r[i], Jsonb):
                        r[i] = Jsonb(r[i])
                batch.append(r)
                if len(batch) >= 500:
                    cur.executemany(sql, batch)
                    batch = []
            if batch:
                cur.executemany(sql, batch)
        note = f" (not copied, no matching column: {', '.join(dropped)})" if dropped else ""
        self.stdout.write(f"{target}: {len(rows)}{note}")

    def fix_counters_and_sequences(self):
        with connection.cursor() as cur:
            for name, table, col, prefix, minimum in COUNTERS:
                cur.execute(f"select coalesce(max(nullif(regexp_replace({col}, '\\D', '', 'g'), '')::bigint), 0) from {table}")
                top = max(cur.fetchone()[0], minimum)
                cur.execute("update counters set value = %s where name = %s", [top, name])
            for t, _, _ in TABLES:
                cur.execute("select pg_get_serial_sequence(%s, 'id')", [f'"{t}"'])
                seq = cur.fetchone()[0]
                if seq:
                    cur.execute(f'select setval(%s, greatest((select coalesce(max(id), 0) from "{t}"), 1))', [seq])
        self.stdout.write("running numbers continue after the highest existing code")
