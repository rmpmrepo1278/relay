#!/bin/bash
# Host-side shim for auto-apply, invoked by AgentChaguli discovery pipeline
# (runs on host as rohit). Accepts base64(job_json) as arg (no &/%/= quoting).
#   bash run_apply.sh <base64job>
#
# Gating (from /home/rohit/.hermes/scripts/apply.conf unless overridden by env):
#   - APPLY_MIN_SCORE (default 52): skip jobs below this fit score
#   - AUTO_APPLY_REAL=1 => REAL run (GDrive push). Absent => --dry-run only.
#   - EMAIL_DROP (default 1): if 1, best-effort recruiter email-drop + recording.
#     Recording + follow-up scheduling ALWAYS happen; email only when an explicit
#     recruiter address is known (recruiting_contacts.json).
set -euo pipefail

CONF="/home/rohit/.hermes/scripts/apply.conf"
if [ -f "$CONF" ]; then
  # shellcheck disable=SC1090
  . "$CONF"
fi
MIN_SCORE="${APPLY_MIN_SCORE:-52}"
B64="${1:-}"

[ -n "$B64" ] || { echo "apply: missing base64 job arg"; exit 2; }
JOB_JSON="$(printf '%s' "$B64" | base64 -d 2>/dev/null || echo "$B64")"

URL="$(printf '%s' "$JOB_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("url",""))')"
COMPANY="$(printf '%s' "$JOB_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("company","Unknown"))')"
TITLE="$(printf '%s' "$JOB_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("title","Unknown"))')"
SCORE="$(printf '%s' "$JOB_JSON" | python3 -c 'import sys,json;print(int(json.load(sys.stdin).get("score",0)))')"
BYPASS="$(printf '%s' "$JOB_JSON" | python3 -c 'import sys,json;print(1 if json.load(sys.stdin).get("bypass_score") else 0)')"

[ -n "$URL" ] || { echo "apply: no url in job"; exit 2; }

if [ "$SCORE" -lt "$MIN_SCORE" ] && [ "$BYPASS" != "1" ]; then
  echo "apply: skip $COMPANY/$TITLE score=$SCORE < $MIN_SCORE"
  exit 0
fi

REAL=0
[ "${AUTO_APPLY_REAL:-0}" = "1" ] && REAL=1
EXTRA="--dry-run"
[ "$REAL" = "1" ] && EXTRA=""

cd /home/rohit/projects/career-ops
echo "[apply] score=$SCORE company=$COMPANY title=$TITLE mode=${EXTRA:-REAL}"

OUTLOG="$(mktemp)"
python3 auto_pipeline.py "$URL" --company "$COMPANY" --title "$TITLE" $EXTRA --min-score 4.0 >"$OUTLOG" 2>&1
RC=$?
tail -14 "$OUTLOG"
echo "--- pipeline rc=$RC ---"

# Structured result for recording + email-drop
RESULT_JSON="$(grep '^RESULT_JSON ' "$OUTLOG" | sed 's/^RESULT_JSON //' | tail -1 || true)"

if [ -n "$RESULT_JSON" ]; then
  RB64="$(printf '%s' "$RESULT_JSON" | base64 -w0)"
  echo "[post] recording + best-effort email-drop..."
  python3 /home/rohit/.hermes/scripts/email_drop.py "$B64" "$RB64" 2>&1 | sed 's/^/       /'
else
  echo "[post] NO RESULT_JSON — skipping record/email (pipeline did not complete apply)"
fi
rm -f "$OUTLOG"
exit "$RC"
