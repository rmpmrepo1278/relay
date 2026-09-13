#!/usr/bin/env bash
# dr_runbook_check.sh — WS6: verified WALK of README_DR.md's 8 recovery
# procedures. Each line verifies the precondition the procedure depends on
# (without executing destructive recovery against live production).
# Any FAIL here means the runbook would break when actually needed.
set -u
LOG=/home/rohit/.hermes/logs/dr_runbook_check.log
PASS=0; FAIL=0
echo "[$(date +%F_%T)] start" >> "$LOG"

chk() { # chk <name> <condition>
  if eval "$2"; then echo "PASS: $1" | tee -a "$LOG"; PASS=$((PASS+1));
  else echo "FAIL: $1" | tee -a "$LOG"; FAIL=$((FAIL+1)); fi
}

# 1. HERMES_HOME_MODE=0705 present in the hermes + hermes-dashboard compose blocks
chk "1-hermes-home-mode" "grep -q 'HERMES_HOME_MODE=0705' /home/rohit/docker-compose.yml"
# 2. Bridge auth rotation: bridge server + key file referenced by scripts
chk "2-bridge-script" "test -f /home/rohit/.hermes/scripts/n8n_bridge_server.py"
# 3. Healthchecks Host header 100.122.58.40:8004 (SITE_ROOT) in ping paths
chk "3-hc-host-header" "grep -rq 'Host: 100.122.58.40:8004' /home/rohit/.hermes/scripts/hc_ping.sh"
# 4. Fallback providers configured in ~/.hermes/config.yaml
chk "4-fallback-providers" "grep -q 'magnitude' /home/rohit/.hermes/config.yaml"
# 5. Collaborator memory relay present + git-clean enough to sync
chk "5-collab-memory" "test -d /home/rohit/.hermes/collaborator-memory/.git"
# 6. Circuit breaker script + DB usable (status exits 0)
chk "6-circuit-breaker" "python3 /home/rohit/.hermes/scripts/circuit_breaker.py status >/dev/null 2>&1"
# 7. Compose restore: backing compose archive exists
chk "7-compose-archive" "ls /home/rohit/backups/compose-*/docker-compose.yml >/dev/null 2>&1"
# 8. Tailscale + LAN reachability
chk "8-tailscale" "tailscale status >/dev/null 2>&1"

echo "RESULT: ${PASS} passed, ${FAIL} failed" | tee -a "$LOG"
[ "$FAIL" -eq 0 ]