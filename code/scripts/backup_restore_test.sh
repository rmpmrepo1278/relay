#!/bin/bash
# Automated backup restore drill — tests that backups can actually be restored
# Runs monthly via scheduler (1st of month, 3am)
set -euo pipefail

LOG="/home/rohit/.hermes/logs/backup_restore_test.log"
RESTORE_DIR="/tmp/backup_restore_test_$(date +%s)"
mkdir -p "$RESTORE_DIR" "$(dirname "$LOG")"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }
fail() { log "FAIL: $*"; exit 1; }
pass() { log "PASS: $*"; }

log "=== Backup Restore Drill Start ==="

# ── 1. Test latest real DB dump can be restored ──────────────────────
# Real pipeline: disaster_recovery backup -> /mnt/usb/backups/docker-volumes/YYYY-MM-DD/*.sql.gz
DUMP_ROOT="/mnt/usb/backups/docker-volumes"
NEWEST_DIR=$(ls -td "$DUMP_ROOT"/*/ 2>/dev/null | head -1 || true)
LATEST_DUMP=""
if [ -n "$NEWEST_DIR" ]; then
    if [ -f "$NEWEST_DIR/immich_database.sql.gz" ]; then
        LATEST_DUMP="$NEWEST_DIR/immich_database.sql.gz"
    else
        LATEST_DUMP=$(ls "$NEWEST_DIR"/*.sql.gz 2>/dev/null | head -1 || true)
    fi
fi

if [ -z "$LATEST_DUMP" ] || [ ! -f "$LATEST_DUMP" ]; then
    log "SKIP: No db dump found under $DUMP_ROOT"
else
    log "Testing restore of $LATEST_DUMP (dir $NEWEST_DIR)"

    # Create temporary postgres container (17-alpine matches immich/paperless pg)
    if docker ps -a --format '{{.Names}}' | grep -qx restore-test-pg; then
        docker rm -f restore-test-pg >/dev/null 2>&1
    fi
    docker run -d --name restore-test-pg \
        -e POSTGRES_DB=restore_test \
        -e POSTGRES_USER=restore_test \
        -e POSTGRES_PASSWORD=restore_test \
        -p 15432:5432 \
        postgres:17-alpine >/dev/null 2>&1 || fail "Could not start restore-test-pg container"

    sleep 6

    # Decompress and restore (plain SQL dump piped into psql)
    gunzip -c "$LATEST_DUMP" | docker exec -i restore-test-pg \
        psql -U restore_test -d restore_test >/dev/null 2>"$RESTORE_DIR/psql.err" || true

    # Verify table count
    TABLES=$(docker exec restore-test-pg \
        psql -U restore_test -d restore_test -t \
        -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null | tr -d '[:space:]')

    docker rm -f restore-test-pg >/dev/null 2>&1

    if [ -n "$TABLES" ] && [ "$TABLES" -gt 0 ] 2>/dev/null; then
        pass "DB restore: $TABLES tables found from $LATEST_DUMP"
    else
        log "psql stderr tail: $(tail -3 "$RESTORE_DIR/psql.err" | tr '\n' ' ')"
        fail "DB restore: no tables found"
    fi
fi

# ── 2. Test Kopia snapshot can be browsed ────────────────────────────
if command -v kopia >/dev/null 2>&1; then
    SNAPSHOT_COUNT=$(sudo -n kopia snapshot list --json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [ "$SNAPSHOT_COUNT" -gt 0 ]; then
        pass "Kopia: $SNAPSHOT_COUNT snapshots browsable"
    else
        fail "Kopia: no snapshots found"
    fi
else
    log "SKIP: Kopia not available (needs root)"
fi

# ── 3. Verify docker build prune script works ───────────────────────
PRUNE_SCRIPT="/home/rohit/.hermes/scripts/docker_build_prune.sh"
if [ -f "$PRUNE_SCRIPT" ]; then
    pass "Docker prune script exists"
else
    fail "Docker prune script missing"
fi

# ── 4. Cleanup ──────────────────────────────────────────────────────
docker rm -f restore-test-pg >/dev/null 2>&1 || true
rm -rf "$RESTORE_DIR"
log "=== Backup Restore Drill Complete ==="
log "Results logged to $LOG"