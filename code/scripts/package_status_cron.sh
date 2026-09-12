#!/bin/bash
# package_status_cron.sh — Update package status file for model consumption
# Runs via cron every 2 hours. Writes output to a file the model can read.
set -e

OUTPUT_FILE="$HOME/.hermes/data/package_status.txt"
TRACKER="$HOME/.hermes/scripts/package_tracker.py"

cd "$HOME"
"$TRACKER" status 2>/dev/null > "$OUTPUT_FILE" 2>&1
echo "---" >> "$OUTPUT_FILE"
echo "Last updated: $(date '+%Y-%m-%d %H:%M:%S %Z')" >> "$OUTPUT_FILE"
