# Relay Journal — 2026-08-09 — Synapse recall wired into OpenCode

## Context

Earlier today deployed Danialsamadi/synapse (local-first personal memory OS) as
`synapse-mcp` on the homelab. Evaluated usefulness (high for durable typed
long-term memory; caveat: GPL-3.0, overlaps existing Hermes/MenteDB memory, keep
it as the fact store). Next step: wire it into OpenCode so agents get persistent
recall across sessions.

## What was done

1. **Recall bridge** `~/services/synapse/recall.sh` on homelab:
   takes a base64-encoded query, `docker exec`es into the running `synapse-mcp`
   container (`node --import tsx src/cli.ts query "<q>"`). Verified: returns the
   `{memories:[], stats:{...}}` JSON shape.

2. **Mac plugin** `~/.config/opencode/plugin/synapse-recall.ts`:
   auto-discovered by OpenCode (global plugin dir, matches existing
   `@opencode-ai/plugin@1.15.10` dep in `~/.config/opencode/package.json`).
   Adapted from the repo's `integrations/opencode/synapse-recall.ts` to SSH to
   the homelab bridge (base64 avoids quoting issues). On trigger phrases
   ("recall", "use synapse", "deep memory", "what do you know about X") it
   injects matched memories into the chat message BEFORE the model responds.

## Why the SSH bridge was needed

Host node on home-hp is 22.x; `better-sqlite3` in the synapse checkout was built
for NODE_MODULE_VERSION 115 (node:20). Running the CLI with host node fails
(`ERR_DLOPEN_FAILED`). The bridge routes through the container, which was
deployed on node:20. This is the same native-module/glibc constraint from the
MenteDB fix — synapse must stay on node:20 (debian), never alpine, and CLI
invocations go through the container.

## Notes

- Plugin env knobs: `SYNAPSE_HOST` (default `homelab-cmd`),
  `SYNAPSE_BRIDGE` (default `/home/rohit/services/synapse/recall.sh`).
- Retrieval failure is swallowed — never blocks chat; falls through to MCP.

## Next

- Test recall end-to-end in a fresh OpenCode session (needs OpenCode restart to
  load plugin).
- Consider routing Hermes consolidation into the same DB later; keep MenteDB and
  synapse as distinct stores for now.