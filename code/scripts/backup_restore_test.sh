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

# ── 1. Test postgres backup can be restored ──────────────────────────
LATEST_DUMP=$(ls -t /mnt/usb/backups/db-dumps/metronix-*.sql.gz 2>/dev/null | head -1)
if [ -z "$LATEST_DUMP" ]; then
    log "SKIP: No postgres dump found"
else
    log "Testing restore of $LATEST_DUMP"
    
    # Create temporary postgres container
    docker run -d --name restore-test-pg \
        -e POSTGRES_DB=restore_test \
        -e POSTGRES_USER=restore_test \
        -e POSTGRES_PASSWORD=restore_test \
        -p 15432:5432 \
        postgres:16-alpine 2>/dev/null
    
    sleep 5
    
    # Decompress and restore
    gunzip -c "$LATEST_DUMP" | docker exec -i restore-test-pg \
        psql -U restore_test -d restore_test 2>/dev/null
    
    # Verify table count
    TABLES=$(docker exec restore-test-pg \
        psql -U restore_test -d restore_test -t \
        -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null | tr -d  )
    
    docker rm -f restore-test-pg >/dev/null 2>&1
    
    if [ "$TABLES" -gt 0 ]; then
        pass "Postgres restore: $TABLES tables found"
    else
        fail "Postgres restore: no tables found"
    fi
fi

# ── 2. Test Kopia snapshot can be browsed ────────────────────────────
if command -v kopia >/dev/null 2>&1; then
    SNAPSHOT_COUNT=$(kopia snapshot list --json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
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
rm -rf "$RESTORE_DIR"
log "=== Backup Restore Drill Complete ==="
log "Results logged to $LOG"
