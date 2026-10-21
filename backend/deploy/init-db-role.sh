#!/bin/sh
set -eu
: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD is required}"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE scrappy LOGIN PASSWORD %L', :'app_password') \gexec
GRANT CONNECT ON DATABASE scrappy TO scrappy;
GRANT USAGE, CREATE ON SCHEMA public TO scrappy;
SQL
