#!/bin/bash
# gateway-preflight.sh — Pre-flight checks before starting hermes-gateway.
# Called by systemd ExecStartPre or before the main gateway process.

VENV_PYTHON="/home/rohit/.hermes/hermes-agent/.venv/bin/python"
SERVICE_DIR="/home/rohit/.config/systemd/user"
LOCK_FILE="/home/rohit/.hermes/state/telegram_polling.lock"

# Check 0: Prevent zombie services — any service with missing ExecStart target is fatal
for svc in hermes-watcher proactive-daemon; do
    svc_file="$SERVICE_DIR/${svc}.service"
    if [ -f "$svc_file" ]; then
        exec_line=$(grep "^ExecStart=" "$svc_file" 2>/dev/null | head -1)
        if [ -n "$exec_line" ]; then
            script_path=$(echo "$exec_line" | grep -oP 'python3 \K[^\s]+' | head -1)
            if [ -n "$script_path" ] && [ ! -f "$script_path" ]; then
                echo "FATAL: Service $svc references missing file: $script_path"
                echo "       Remove zombie service: rm $svc_file && systemctl --user daemon-reload"
                exit 1
            fi
        fi
    fi
done

# Check 0.5: Kill any rogue telegram_bot.py processes before starting
ROGUE_BOT_PIDS=$(pgrep -f "telegram_bot\.py" 2>/dev/null || true)
if [ -n "$ROGUE_BOT_PIDS" ]; then
    echo "KILL: Found rogue telegram_bot.py process(es): $ROGUE_BOT_PIDS — terminating"
    kill $ROGUE_BOT_PIDS 2>/dev/null || true
    sleep 1
    REMAINING=$(pgrep -f "telegram_bot\.py" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
        kill -9 $REMAINING 2>/dev/null || true
        echo "KILL: Force-killed remaining rogue processes"
    fi
fi

# Check 1: Module importable
if ! ${VENV_PYTHON} -c "import hermes_cli.main; import gateway.run" 2>/dev/null; then
    echo "FAIL: hermes_cli module not importable — attempting reinstall"
    ${VENV_PYTHON} -m pip install --force-reinstall "hermes-agent[all]" 2>&1
    if ! ${VENV_PYTHON} -c "import hermes_cli.main; import gateway.run" 2>/dev/null; then
        echo "FATAL: Cannot recover hermes_cli module"
        exit 1
    fi
fi

# Check 2: Telegram API reachable (fail-open: don't block start if API is temporarily down)
if ! curl -sf -o /dev/null --connect-timeout 5 https://api.telegram.org 2>/dev/null; then
    echo "WARN: Telegram API unreachable (likely ISP outage) — starting anyway, adapter will retry"
fi

# Check 3: Clear stale Telegram server-side sessions
# Doing a getUpdates with timeout=0 closes any lingering long-poll from a previous process.
TOKEN_FILE="/home/rohit/.hermes/.telegram_token"
if [ -f "$TOKEN_FILE" ]; then
    TOKEN=$(cat "$TOKEN_FILE" | tr -d ' \n\r')
    if [ -n "$TOKEN" ]; then
        curl -sf -o /dev/null --connect-timeout 5 \
            "https://api.telegram.org/bot${TOKEN}/getUpdates?offset=-1&timeout=0" \
            2>/dev/null && echo "CLEAR: Stale Telegram session cleared" \
            || echo "WARN: Could not clear Telegram session (non-fatal)"
    fi
fi

# Check 4: Acquire polling lock
mkdir -p "$(dirname "$LOCK_FILE")"
if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && [ -d "/proc/$OLD_PID" ]; then
        echo "FATAL: Telegram polling lock held by PID $OLD_PID — another gateway or bot is running"
        exit 1
    fi
    echo "WARN: Stale polling lock removed (PID $OLD_PID is dead)"
fi
echo $$ > "$LOCK_FILE"
# Double-check the lock was actually written
if [ ! -f "$LOCK_FILE" ]; then
    echo "FATAL: Could not write polling lock file at $LOCK_FILE"
    exit 1
fi
echo "LOCK: Acquired Telegram polling lock (PID $$)"

echo "gateway-preflight: OK"
exit 0
