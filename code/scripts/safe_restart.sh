#!/usr/bin/env bash
# safe_restart.sh — Safely restart Hermes services with health checks
# This script runs ON the homelab itself (locally)

set -euo pipefail

SERVICES=("hermes-scheduler" "hermes-gateway" "hermes-mind-loop")
LOG_FILE="/home/rohit/.hermes/logs/service-restart.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_service_running() {
    local svc="$1"
    systemctl --user is-active "$svc" >/dev/null 2>&1
}

# Main restart logic
restart_services() {
    log "=== Starting safe restart ==="
    
    # Step 1: Stop services in reverse order
    for svc in $(printf '%s\n' "${SERVICES[@]}" | tac); do
        log "Stopping $svc..."
        systemctl --user stop "$svc" 2>&1 || log "WARN: $svc stop failed (may already be stopped)"
        sleep 2
    done
    
    # Step 2: Wait for clean stop
    log "Waiting for services to stop..."
    sleep 5
    
    # Step 3: Kill any lingering processes
    log "Killing any lingering hermes processes..."
    pkill -f hermes 2>/dev/null || true
    sleep 2
    
    # Step 4: Start services in order
    for svc in "${SERVICES[@]}"; do
        log "Starting $svc..."
        systemctl --user start "$svc" 2>&1 || {
            log "ERROR: Failed to start $svc"
            exit 1
        }
        sleep 2
        
        if check_service_running "$svc"; then
            log "$svc started successfully"
        else
            log "ERROR: $svc failed to start"
            exit 1
        fi
    done
    
    # Step 5: Wait and verify
    log "Waiting for services to stabilize..."
    sleep 15
    
    for svc in "${SERVICES[@]}"; do
        if check_service_running "$svc"; then
            log "OK: $svc is running"
        else
            log "FAIL: $svc is not running"
        fi
    done
    
    log "=== Safe restart complete ==="
}

restart_services
