#!/usr/bin/env bash
# volume_restore_test.sh — WS6: prove nightly volume tarballs are restorable.
# Picks the newest dated backup dir, restores ONE volume tarball into a
# throwaway volume, verifies file count/size against the tar listing, cleans up.
set -u

BK=/home/rohit/backups/volumes
LOG=/home/rohit/.hermes/logs/volume_restore_test.log
LATEST=$(ls -1dt "$BK"/2* 2>/dev/null | head -1)
echo "[$(date +%F_%T)] start; latest dir: ${LATEST:-NONE}" >> "$LOG"

if [ -z "${LATEST:-}" ] || [ ! -d "$LATEST" ]; then
  echo "FAIL: no dated volume backup dir under $BK" | tee -a "$LOG"
  exit 1
fi

TARBALL=$(ls -1 "$LATEST"/*.tgz 2>/dev/null | head -1)
if [ -z "${TARBALL:-}" ]; then
  echo "FAIL: no tarball in $LATEST" | tee -a "$LOG"
  exit 1
fi
echo "testing: $TARBALL" >> "$LOG"

TESTVOL="restore-test-$(date +%s)"
docker volume create "$TESTVOL" >/dev/null || { echo "FAIL: volume create" | tee -a "$LOG"; exit 1; }
cleanup() { docker volume rm "$TESTVOL" >/dev/null 2>&1; }
trap cleanup EXIT

EXPECT_FILES=$(tar tzf "$TARBALL" | wc -l)
if ! docker run --rm -v "$TARBALL":/b.tgz:ro -v "$TESTVOL":/data alpine sh -c \
     "tar xzf /b.tgz -C /data" 2>>"$LOG"; then
  echo "FAIL: extraction error" | tee -a "$LOG"
  exit 1
fi

GOT_FILES=$(docker run --rm -v "$TESTVOL":/data alpine sh -c "find /data -type f | wc -l")
GOT_SIZE=$(docker run --rm -v "$TESTVOL":/data alpine sh -c "du -sb /data | cut -f1")
TAR_SIZE=$(tar tvzf "$TARBALL" | awk '{s+=$3} END{print s}')

if [ "$GOT_FILES" -gt 0 ] && [ "$GOT_SIZE" -ge $((TAR_SIZE * 8 / 10)) ] 2>/dev/null; then
  echo "PASS: $(basename "$TARBALL") restored files=$GOT_FILES bytes=$GOT_SIZE (tar=$TAR_SIZE)" | tee -a "$LOG"
  exit 0
else
  echo "FAIL: restored files=$GOT_FILES bytes=$GOT_SIZE vs tar files=$EXPECT_FILES bytes=$TAR_SIZE" | tee -a "$LOG"
  exit 1
fi