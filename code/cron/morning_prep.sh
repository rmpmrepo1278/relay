#!/usr/bin/env bash
# =============================================================================
# morning_prep.sh — Batched 6am daily prep jobs
#
# Replaces 6 separate cron entries at 6:00-6:30:
#   6:00  tier_engine (twice daily)
#   6:00  reflective_phase
#   6:00  predictive_engine
#   6:15  cross_domain_correlator
#   6:30  session_debrief
#   6:30  commitment_tracker
#
# Run as single cron at 6am. Sequential execution avoids overlap.
# =============================================================================

set -uo pipefail

# Healthchecks ping
source /home/rohit/.hermes/scripts/hc_uuids.sh 2>/dev/null || true
/home/rohit/.hermes/scripts/hc_ping.sh "$HC_UUID_MORNING_PREP" start 2>/dev/null || true

HERMES_HOME="/home/rohit/.hermes"
AGENT_ROOT="$HERMES_HOME/hermes-agent"
LOG_DIR="$HERMES_HOME/logs"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] morning_prep: Starting daily prep run"

# 1. Reflective phase
echo "[$(date '+%H:%M:%S')] → Reflective phase"
"$HERMES_HOME/cron/reflective_phase.sh" >> "$LOG_DIR/reflective_phase.log" 2>&1 || true

# 2. Predictive engine (REMOVED — script deleted in ponytail cleanup)
# echo "[$(date '+%H:%M:%S')] → Predictive engine"
# "$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/predictive_engine.py" \
#     >> "$LOG_DIR/predictive_engine.log" 2>&1 || true

# 3. Cross-domain correlator
echo "[$(date '+%H:%M:%S')] → Cross-domain correlator"
"$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/cross_domain_correlator.py" \
    >> "$LOG_DIR/cross_domain_correlator.log" 2>&1 || true

# 4. Session debrief
echo "[$(date '+%H:%M:%S')] → Session debrief"
"$HERMES_HOME/cron/session_debrief.sh" >> "$LOG_DIR/session_debrief.log" 2>&1 || true

# 5. Commitment tracker
echo "[$(date '+%H:%M:%S')] → Commitment tracker"
"$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/commitment_tracker.py" \
    >> "$LOG_DIR/commitment_tracker.log" 2>&1 || true

# 6. Tier engine (morning run — evening run at 6pm stays separate)
echo "[$(date '+%H:%M:%S')] → Tier engine"
"$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/autonomous_tier_engine.py" \
    >> "$LOG_DIR/autonomous_tier.log" 2>&1 || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] morning_prep: Complete"
/home/rohit/.hermes/scripts/hc_ping.sh "$HC_UUID_MORNING_PREP" success 2>/dev/null || true
