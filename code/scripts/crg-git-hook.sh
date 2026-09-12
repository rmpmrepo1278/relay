#!/bin/bash
# CRG + Graphify git hook — triggered on post-commit / post-merge
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$REPO_ROOT" ] && exit 0

# Debounce: skip if last rebuild was <60s ago
LOCK="/tmp/crg-rebuild.lock"
[ -f "$LOCK" ] && [ "$(find "$LOCK" -mmin -1 2>/dev/null)" ] && exit 0
touch "$LOCK"

# Code Review Graph rebuild (per-repo)
case "$REPO_ROOT" in
  /home/rohit/.hermes/hermes-agent)     REPO="hermes-agent" ;;
  /home/rohit/projects/career-ops)      REPO="career-ops" ;;
  *) REPO="" ;;
esac

if [ -n "$REPO" ]; then
  /usr/bin/nohup /home/rohit/.local/bin/code-review-graph build --repo "$REPO_ROOT" >> /home/rohit/.code-review-graph/logs/rebuild-${REPO}.log 2>&1 &
fi

# Graphify rebuild (only when scripts dir changes)
if [ "$REPO_ROOT" = "/home/rohit/.hermes" ] || [ "$REPO_ROOT" = "/home/rohit/.hermes/scripts" ]; then
  /usr/bin/nohup /home/rohit/.local/bin/graphify /home/rohit/.hermes/scripts >> /home/rohit/.hermes/scripts/graphify-out/rebuild.log 2>&1 &
fi
