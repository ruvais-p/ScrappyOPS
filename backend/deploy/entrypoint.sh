#!/bin/sh
# Start-up: wait for the database, bring the tables up to date, make sure the first franchise and materials exist, then run.
set -e
python - <<'PY'
import os, sys, time, psycopg
url = os.environ.get("DATABASE_URL", "")
for i in range(40):
    try:
        psycopg.connect(url, connect_timeout=3).close()
        break
    except Exception as e:
        print("waiting for the database...", e, file=sys.stderr)
        time.sleep(2)
else:
    sys.exit("The database did not come up.")
PY
python manage.py migrate --noinput
python manage.py seed_defaults
exec "$@"
