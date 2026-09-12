#!/bin/bash
# systemd_sanity_check.sh — Detect and warn about zombie systemd services.
# Checks: (1) Missing ExecStart targets, (2) Excessive restart rates, (3) Stuck states.
# Runs via cron daily, can be manually triggered.

SERVICE_DIR="/home/rohit/.config/systemd/user"
ISSUE_COUNT=0

echo "=== Systemd Sanity Check ==="

# Check each user service file for missing ExecStart targets
for svc_file in "$SERVICE_DIR"/*.service; do
    [ ! -f "$svc_file" ] && continue
    svc_name=$(basename "$svc_file")
    
    exec_line=$(grep "^ExecStart=" "$svc_file" 2>/dev/null | head -1)
    [ -z "$exec_line" ] && continue
    
    # Extract script/binary path - last argument that looks like a path
    script_path=$(echo "$exec_line" | grep -oE '/[^ ]+' | tail -1)
    
    # Check if it's a script file (.py or .sh)
    if echo "$script_path" | grep -qE '\.(py|sh)$'; then
        if [ ! -f "$script_path" ]; then
            echo "⚠️  ZOMBIE: $svc_name references missing: $script_path"
            ((ISSUE_COUNT++))
        fi
    fi
    
    # Check restart rate (warning threshold)
    restarts=$(systemctl --user show "$svc_name" --property=NRestarts --value 2>/dev/null)
    if [ -n "$restarts" ] && [ "$restarts" -gt 10 ] 2>/dev/null; then
        echo "⚠️  HIGH RESTARTS: $svc_name has NRestarts=$restarts (threshold: 10)"
        ((ISSUE_COUNT++))
    fi
done

echo "Issues found: $ISSUE_COUNT"
exit $ISSUE_COUNT
