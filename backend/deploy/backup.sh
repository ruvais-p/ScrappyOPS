#!/usr/bin/env bash
# Nightly backup of the database and the PDF bills. Run it from cron on the machine that runs docker compose:
#   0 2 * * *  cd /opt/scrappy_backend && ./deploy/backup.sh /backups
# Keeps the last 30 days. Copy /backups somewhere else too (another machine or cloud storage): a backup on the same disk is not a backup.
set -euo pipefail
umask 077
command -v age >/dev/null 2>&1 || { echo "Install age before running backups." >&2; exit 1; }
: "${BACKUP_AGE_RECIPIENT:?Set BACKUP_AGE_RECIPIENT to an age public recipient in the environment.}"
DEST="${1:-./backups}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$DEST"
docker compose exec -T db pg_dump -U scrappy_admin -Fc scrappy | age -r "$BACKUP_AGE_RECIPIENT" -o "$DEST/scrappy_$STAMP.dump.age"
docker compose exec -T web tar -C /data -cf - media | age -r "$BACKUP_AGE_RECIPIENT" -o "$DEST/bills_$STAMP.tar.age"
find "$DEST" -name 'scrappy_*.dump.age' -mtime +30 -delete
find "$DEST" -name 'bills_*.tar.age' -mtime +30 -delete
echo "Backup written to $DEST ($STAMP)"
# Restore database: age -d -i /secure/path/age-key.txt scrappy_YYYY-MM-DD_HHMM.dump.age | docker compose exec -T db pg_restore -U scrappy_admin -d scrappy --clean --if-exists
# Restore media: age -d -i /secure/path/age-key.txt bills_YYYY-MM-DD_HHMM.tar.age | docker compose exec -T web tar -C /data -xf -
