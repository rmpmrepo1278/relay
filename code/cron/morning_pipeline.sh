#!/usr/bin/env bash
# =============================================================================
# morning_pipeline.sh — Batched 8am daily jobs
#
# Replaces 6 separate cron entries at 8:00-8:50:
#   8:00  birthday-reminder
#   8:20  daily-digest
#   8:35  email_triage
#   8:40  email_action_loop
#   8:50  autonomous_career_scan
#   8:00  monthly-finance (conditional)
#
# Run as single cron at 8am. Sequential execution avoids overlap.
# =============================================================================

set -uo pipefail

# Healthchecks ping
source /home/rohit/.hermes/scripts/hc_uuids.sh 2>/dev/null || true
/home/rohit/.hermes/scripts/hc_ping.sh "$HC_UUID_MORNING_PIPELINE" start 2>/dev/null || true

HERMES_HOME="/home/rohit/.hermes"
AGENT_ROOT="$HERMES_HOME/hermes-agent"
LOG_DIR="$HERMES_HOME/logs"
DATE=$(date +%Y%m%d)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] morning_pipeline: Starting daily morning run"

# 1. Birthday reminder
echo "[$(date '+%H:%M:%S')] → Birthday reminder"
HERMES_HOME="$HERMES_HOME" /usr/bin/python3 "$HERMES_HOME/cron/personal_agent_scheduler.py" \
    --mode birthday-reminder >> "$LOG_DIR/ei.log" 2>&1 || true

# 2. Daily digest
echo "[$(date '+%H:%M:%S')] → Daily digest"
/home/rohit/.hermes/cron/send_daily_digest.sh >> "$HERMES_HOME/cron/output/digest.log" 2>&1 || true

# 3. Habit check-in prompt
echo "[$(date '+%H:%M:%S')] → Habit daily prompt"
HABIT_PROMPT=$(/usr/bin/python3 "$HERMES_HOME/skills/habit-tracker/scripts/habit_tracker.py" daily-prompt 2>/dev/null || echo "📅 Daily habit check-in.")
# Send to Telegram General topic
curl -s -X POST http://localhost:9199/telegram-send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer default-key-change-me" \
  -d "{\"text\":\"$HABIT_PROMPT\",\"category\":\"general\"}" \
  >> "$LOG_DIR/habit_telemetry.log" 2>&1 || true

# 4. Memory scanner (proactive memory scan for stuck items/todos)
echo "[$(date '+%H:%M:%S')] → Memory scanner"
/usr/bin/python3 "$HERMES_HOME/skills/memory-scanner/scripts/memory_scanner.py" notify \
  >> "$LOG_DIR/memory_scanner.log" 2>&1 || true

# 5. Email triage (REMOVED — script deleted in ponytail cleanup)
# echo "[$(date '+%H:%M:%S')] → Email triage"
# "$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/email_triage.py" \
#     >> "$LOG_DIR/email_triage.log" 2>&1 || true

# 4. Email action loop (REMOVED — script deleted in ponytail cleanup)
# echo "[$(date '+%H:%M:%S')] → Email action loop"
# "$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/email_action_loop.py" \
#     >> "$LOG_DIR/email_action_loop.log" 2>&1 || true

# 5. Career scan (REMOVED — use career_autonomous.py via cron instead)
# echo "[$(date '+%H:%M:%S')] → Career scan"
# "$AGENT_ROOT/.venv/bin/python3" "$AGENT_ROOT/scripts/autonomous_career_scan.py" \
#     >> "$LOG_DIR/autonomous_career.log" 2>&1 || true

# 6. Monthly finance (only on 1st of month)
DAY=$(date +%d)
if [ "$DAY" = "01" ]; then
    echo "[$(date '+%H:%M:%S')] → Monthly finance report"
    HERMES_HOME="$HERMES_HOME" /usr/bin/python3 "$HERMES_HOME/cron/personal_agent_scheduler.py" \
        --mode monthly-finance >> "$LOG_DIR/personal_agent.log" 2>&1 || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] morning_pipeline: Complete"
/home/rohit/.hermes/scripts/hc_ping.sh "$HC_UUID_MORNING_PIPELINE" success 2>/dev/null || true
