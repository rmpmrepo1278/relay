#!/bin/bash
# Backup metronix PostgreSQL database via pg_dump
# Runs monthly via Hermes scheduler (1st of month, 2am)
# Retention: 14 days

set -euo pipefail

BACKUP_DIR="/mnt/usb/backups/db-dumps"
CONTAINER="metronix-full-postgres"
DB_USER="metronix"
DB_NAME="metronix"
PGPASSWORD="${POSTGRES_PASSWORD:-metronix-homelab}"
DATE=$(date +%F)
BACKUP_FILE="${BACKUP_DIR}/metronix-${DATE}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Skip if today's backup already exists
if [[ -f "$BACKUP_FILE" ]]; then
    echo "metronix backup already exists for $DATE, skipping"
    exit 0
fi

echo "Dumping metronix database from $CONTAINER..."
PGPASSWORD="$PGPASSWORD" docker exec "$CONTAINER" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
    | gzip > "$BACKUP_FILE"

FILESIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "metronix backup complete: $BACKUP_FILE ($FILESIZE)"

# Prune backups older than 14 days
find "$BACKUP_DIR" -name "metronix-*.sql.gz" -mtime +14 -delete
echo "Pruned metronix backups older than 14 days"
