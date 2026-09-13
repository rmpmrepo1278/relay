#!/bin/bash
# Paperless backup: pg_dump + data dir daily; media (originals) weekly on
# Sundays or forced with --with-media. Retention: daily 7d, media 60d.
# Fills a real gap (Sep 13 2026): paperless uses bind mounts, so the
# named-volume backup_volumes.sh never covered it.
set -euo pipefail
BASE=/home/rohit/backups/paperless
DATE=$(date +%F)
DOW=$(date +%u)
set -a; source /home/rohit/services/docker/compose/.env; set +a
DBPASS=${PAPERLESS_DB_PASS:?}
mkdir -p $BASE/daily/$DATE
PGPASSWORD=$DBPASS docker exec paperless-db pg_dump -U paperless -d paperless --no-owner --no-privileges | gzip > $BASE/daily/$DATE/paperless-db.sql.gz
tar czf $BASE/daily/$DATE/paperless-data.tgz -C /home/rohit/services/data/paperless data
if [ "${1:-}" = --with-media ] || [ $DOW = 7 ]; then
  mkdir -p $BASE/media/$DATE
  tar czf $BASE/media/$DATE/paperless-media.tgz -C /mnt/usb/files paperless-media
fi
find $BASE/daily -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
find $BASE/media -mindepth 1 -maxdepth 1 -type d -mtime +60 -exec rm -rf {} + 2>/dev/null || true
echo paperless backup complete
ls -lh $BASE/daily/$DATE $BASE/media/$DATE 2>/dev/null || true
