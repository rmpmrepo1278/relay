#!/bin/bash
# init_collaborator_memory.sh - sync shared collaborator memory (relay repo) before work.
# Referenced by AgentChaguli CLAUDE.md workflow: "collaborator sync" for opencode/Claude Code/Hermes.
set -u
MEM_DIR="$HOME/.hermes/collaborator-memory"
if [ ! -d "$MEM_DIR/.git" ]; then
  echo "ERROR: $MEM_DIR is not a git repo (clone https://github.com/rmpmrepo1278/relay into it)." >&2
  exit 2
fi
cd "$MEM_DIR" || exit 2
git pull --rebase --autostash 2>&1 | tail -3
if ! git diff --quiet; then
  git add -A
  git commit -m "sync: collaborator memory update $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1 || true
  git push 2>&1 | tail -1 || echo "push deferred (offline?)"
fi
echo "OK: collaborator memory synced at $(git rev-parse --short HEAD)"
