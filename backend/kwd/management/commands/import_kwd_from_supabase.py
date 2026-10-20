"""Copy the staff app's data (Scrappy Field / Kitchen Waste Digester monitoring) from its Supabase project into this database:
logins (with their passwords), staff profiles and districts, LSGDs, contacts, plans, visits, follow-ups, TA/DA requests and
their history, and the whole franchise module (franchisees, leads, sales, stock, presentations, targets). Ids are kept.

    python manage.py import_kwd_from_supabase --source "postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres" \\
        --supabase-url https://<project>.supabase.co --service-key <service role key>
    (add --dry-run to check everything and change nothing)

What it does and does not do
  - The source database is only read.
  - Run it on a database where the staff app is still empty (right after migrate). Logins go into the same `users` table the
    rest of Scrappy uses; if a source email already exists here the command stops and lists them, because a person must have
    one login only. Rename or remove the duplicate on one side and run again.
  - Supabase keeps bcrypt password hashes and those work here unchanged, so nobody needs a new password.
  - The rules that used to be database triggers are NOT replayed: history is copied exactly as it was.
  - Photos: pass --storage-dir (a folder holding a download of the `visit-photos` bucket, same relative paths) or
    --supabase-url + --service-key (downloaded one by one). Without either, the command lists what is missing.
"""
import importlib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg.types.json import Jsonb

from kwd import schema, storage

SEEDED = ["kwd_fr_products", "kwd_expense_policy", "kwd_districts"]           # the migration's starting rows; the source's own replace them
PHOTO_COLUMNS = [("kwd_visits", "photo_path"), ("kwd_field_days", "start_photo"), ("kwd_field_days", "end_photo"),
                 ("kwd_expense_items", "bill_path"), ("kwd_fr_sales", "install_photo"), ("kwd_fr_presentations", "done_photo")]


class Command(BaseCommand):
    help = "Copy the staff app's data from its Supabase database (read only) into this database."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Postgres connection string of the Supabase database")
        parser.add_argument("--schema", default="public", help="Schema holding the app's tables in the source (default public)")
        parser.add_argument("--auth-schema", default="auth", help="Schema holding the logins table (default auth)")
        parser.add_argument("--storage-dir", help="Folder with a download of the photo bucket (same relative paths)")
        parser.add_argument("--supabase-url", help="https://<project>.supabase.co, to download photos")
        parser.add_argument("--service-key", help="Service role key of the Supabase project, to download photos")
        parser.add_argument("--bucket", default="visit-photos")
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then undo it")

    def handle(self, *args, **o):
        with connection.cursor() as c:
            c.execute("select (select count(*) from kwd_profiles) + (select count(*) from kwd_lsgds)")
            if c.fetchone()[0]:
                raise CommandError("The staff app already has data here. Import into an empty one (right after migrate).")
        try:
            src = psycopg.connect(o["source"], autocommit=True)
        except Exception as e:
            raise CommandError(f"Could not connect to the source database: {e}")
        src.execute("set default_transaction_read_only = on")        # this command can never change the old database
        self.o = o
        try:
            with transaction.atomic():
                self.copy_all(src)
                if o["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING("Dry run: everything checked, nothing was kept."))
        finally:
            src.close()
        if not o["dry_run"]:
            self.copy_photos()
        self.stdout.write(self.style.SUCCESS("Staff app data imported."))

    # ------------------------------------------------------------------------------------------ database
    def target_columns(self, table):
        with connection.cursor() as c:
            c.execute("select column_name, is_generated, data_type from information_schema.columns where table_schema = 'public' and table_name = %s", [table])
            return {r[0]: (r[1] == "ALWAYS", r[2]) for r in c.fetchall()}

    def source_columns(self, src, table):
        return [r[0] for r in src.execute("select column_name from information_schema.columns where table_schema = %s and table_name = %s order by ordinal_position",
                                          [self.o["schema"], table]).fetchall()]

    def foreign_keys(self):
        with connection.cursor() as c:
            c.execute("""select cl.relname, con.conname from pg_constraint con join pg_class cl on cl.oid = con.conrelid
                         where con.contype = 'f' and cl.relname like 'kwd\\_%'""")
            return c.fetchall()

    def copy_all(self, src):
        fks = self.foreign_keys()
        with connection.cursor() as cur:
            for table, name in fks:                          # links between records are checked once, at the end
                cur.execute(f'alter table "{table}" alter constraint "{name}" deferrable initially deferred')
            for t in SEEDED:
                cur.execute(f'delete from "{t}"')
        self.copy_users(src)
        for api, (table, _cols, generated) in schema.TABLES.items():
            self.copy_table(src, api, table, generated)
        self.fix_sequences()
        with connection.cursor() as cur:
            try:
                cur.execute("set constraints all immediate")
            except Exception as e:
                raise CommandError(f"Some records point at records that are missing in the source data: {e}")
            for table, name in fks:
                cur.execute(f'alter table "{table}" alter constraint "{name}" not deferrable')

    def copy_users(self, src):
        s, a = self.o["schema"], self.o["auth_schema"]
        rows = src.execute(f"select id, lower(email), encrypted_password, created_at, last_sign_in_at from {a}.users "
                           f"where email is not null and id in (select id from {s}.profiles) order by created_at").fetchall()
        with connection.cursor() as cur:
            emails = [r[1] for r in rows]
            cur.execute("select email from users where email = any(%s) or id = any(%s)", [emails, [r[0] for r in rows]])
            clash = sorted({r[0] for r in cur.fetchall()})
            if clash:
                raise CommandError("These logins already exist here, and a person must have one login only. Rename or remove the duplicate on one side, "
                                   "then run again: " + ", ".join(clash))
            for uid, email, pw, created, last in rows:
                hashed = ("bcrypt$" + pw) if pw and pw.startswith("$2") else "!"          # '!' = no usable password: Head Office resets it
                cur.execute("insert into users (id, email, password, is_active, created_at, last_login) values (%s, %s, %s, true, %s, %s)",
                            [uid, email, hashed, created, last])
        self.stdout.write(f"users: {len(rows)}")

    def copy_table(self, src, api, table, generated):
        tcols = self.target_columns(table)
        scols = self.source_columns(src, api)
        if not scols:
            self.stdout.write(self.style.WARNING(f"{api}: not found in the source, skipped"))
            return
        cols = [c for c in scols if c in tcols and not tcols[c][0] and c not in generated]
        dropped = [c for c in scols if c not in cols and c not in generated]
        rows = src.execute(f'select {", ".join(chr(34) + c + chr(34) for c in cols)} from {self.o["schema"]}."{api}"').fetchall()
        jsoncols = {i for i, c in enumerate(cols) if tcols[c][1] in ("jsonb", "json")}
        sql = f'insert into "{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) overriding system value values ({", ".join(["%s"] * len(cols))})'
        with connection.cursor() as cur:
            batch = []
            for r in rows:
                batch.append([Jsonb(v) if i in jsoncols and v is not None else v for i, v in enumerate(r)])
                if len(batch) >= 500:
                    cur.executemany(sql, batch)
                    batch = []
            if batch:
                cur.executemany(sql, batch)
        note = f" (columns not carried over: {', '.join(dropped)})" if dropped else ""
        self.stdout.write(f"{api}: {len(rows)}{note}")

    def fix_sequences(self):
        """Rows were inserted with their own ids, so the counters that give out new ids must start after the highest one."""
        with connection.cursor() as cur:
            cur.execute("""select cl.relname, a.attname from pg_attribute a join pg_class cl on cl.oid = a.attrelid
                           where cl.relname like 'kwd\\_%' and cl.relkind = 'r' and a.attidentity <> ''""")
            for table, col in cur.fetchall():
                cur.execute(f'select pg_get_serial_sequence(\'"{table}"\', \'{col}\')')
                seq = cur.fetchone()[0]
                if seq:
                    cur.execute(f'select setval(%s, greatest((select coalesce(max("{col}"), 0) from "{table}"), 1))', [seq])

    # ------------------------------------------------------------------------------------------ photos
    def photo_paths(self):
        paths = set()
        with connection.cursor() as cur:
            for table, col in PHOTO_COLUMNS:
                cur.execute(f'select distinct "{col}" from "{table}" where "{col}" is not null')
                paths.update(r[0] for r in cur.fetchall())
        return sorted(paths)

    def copy_photos(self):
        paths = self.photo_paths()
        folder, url, key = self.o.get("storage_dir"), self.o.get("supabase_url"), self.o.get("service_key")
        if not paths:
            return
        if not folder and not (url and key):
            self.stdout.write(self.style.WARNING(f"{len(paths)} photo(s) are referenced. Run again with --storage-dir or --supabase-url and --service-key "
                                                 "(the data is already in; only the photos are missing)."))
            return
        done = skipped = missing = 0
        for p in paths:
            if not storage.valid_name(p):
                self.stdout.write(self.style.WARNING(f"skipped (name not allowed): {p}"))
                skipped += 1
                continue
            if storage.exists(p):
                skipped += 1
                continue
            data = self.fetch_photo(folder, url, key, p)
            if data is None:
                missing += 1
                continue
            try:
                storage.save(p, data)
                done += 1
            except FileExistsError:
                skipped += 1
        self.stdout.write(f"photos: {done} copied, {skipped} already here or skipped, {missing} not found in the source")

    def fetch_photo(self, folder, url, key, path):
        if folder:
            f = Path(folder) / path
            return f.read_bytes() if f.is_file() else None
        req = urllib.request.Request(f"{url.rstrip('/')}/storage/v1/object/{self.o['bucket']}/{urllib.parse.quote(path)}",
                                     headers={"Authorization": f"Bearer {key}", "apikey": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            raise CommandError(f"Could not download {path}: {e}")
