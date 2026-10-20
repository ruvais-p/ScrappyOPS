#!/bin/sh
# Nightly backup of the database and the PDF bills. Run it from cron on the machine that runs docker compose:
#   0 2 * * *  cd /opt/scrappy_backend && ./deploy/backup.sh /backups
# Keeps the last 30 days. Copy /backups somewhere else too (another machine or cloud storage): a backup on the same disk is not a backup.
set -e
DEST="${1:-./backups}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$DEST"
docker compose exec -T db pg_dump -U scrappy -Fc scrappy > "$DEST/scrappy_$STAMP.dump"
docker compose exec -T web tar -C /data -cf - media > "$DEST/bills_$STAMP.tar"
find "$DEST" -name 'scrappy_*.dump' -mtime +30 -delete
find "$DEST" -name 'bills_*.tar' -mtime +30 -delete
echo "Backup written to $DEST ($STAMP)"
# Restore:  docker compose exec -T db pg_restore -U scrappy -d scrappy --clean --if-exists < scrappy_YYYY-MM-DD_HHMM.dump
