# Relay — Magnitude local 8B install attempt (2026-09-08)

## Objective
Install the fast local 8B model (LFM2.5-8B-A1B) into magnitude so the pre-wired `local-executor-lite` lane can run interactive/fallback workloads locally ("run 1 — implement it").

## Outcome: BLOCKED (environment restored clean, nothing broken)
The 8B **is already file-complete and hash-correct** on disk, and magnitude's own `inventory.json` lists it (`LFM2.5 8B A1B DSpark Draft v1`, Q8_0, 64K ctx — the note in dict README said "registers it as Q4" is WRONG; it's Q8, which is why `:gguf:q4` and `:gguf:q8` both fail with "not installed"). Historically magnitude actually RAN it as a spec-decode **draft** (load-timings.json shows draft_model/draft_context@64K feeding a Nemotron-30B target).

But magnitude does **not** surface or load it standalone:
- `magnitude models load lfm2.5-8b-a1b:gguf:q8` → `model is not ready: catalog model ... is not installed`
- setup TUI only lists installed/installable catalog models; defaults to a 30GB Qwen3.6-35B on a wrong-row Enter (I aborted twice; cleaned the partial dirs).

## What I verified (so we don't re-do it)
- **Layouts identical**: LFM hub dir now mirrors gemma exactly — `blobs/lfs-sha256-<sha256>` + matching `.integrity` JSON, empty `snapshots/<commit>/`. Q8 blob `78c6edb3...` (356,491,104 B) + Q4 blob `017278ec...` (199,679,840 B).
- **Registry**: only `cache/indexes/inventory.json` references the model id; no separate acquisition ledger found; `coordination.sqlite` is just an owner row; `state/models.json` is slots only.
- **CLI/daemon**: CLI 0.0.13 BREAKS against daemon 0.0.11 (`{expected:1,actual:0,daemonVersion:0.0.11}`) — `magnitude update` only bumps the npm CLI, not the daemon, and there's no accepted noninteractive daemon upgrade. **Downgraded CLI back to 0.0.11** (working). `state/version.json` reset to 0.0.11.
- **Root cause**: the `Installed` vs `NotInstalled` decision for a catalog entry is computed in-memory by the minified `magnitude-service` bundle (`packages/release/src/acquisition.ts` area, `catalogAcquisition` reads `source.localState._tag`). The 8B was recorded as an internal draft, not via the standalone install flow, so it resolves NotInstalled. Getting it treated as installed needs the sanctioned interactive wizard (unsafe to pty-drive — defaults to huge Qwen) or deep reverse-engineering of the minified bundle (high effort, not yielding).

## State restored (clean)
- `magnitude-service` running, healthy, gemma listed Unloaded; bridged daemon/magnitude down; magnitude CLI 0.0.11.
- Stray partial Qwen3.6-35B dirs (magnitudedev–DFlash, unsloth–MTP) deleted; LFM Q8+Q4 blobs + integrity retained (dish intact, ~77G free).
- No active downloads.

## Next move (pick one)
1. **Upgrade the DAEMON** to 0.0.13 properly (the daemon is a separate release under `releases/acn/`; find the accepted mechanism — possibly `magnitude setup` after a CLI that can drive it, or check `MAGNITUDE_RELEASE_BASE_URL`/`acn` manifest). Newer daemon may fix variant resolution for the already-locally-present 8B. **Recommended** — lowest risk, might just work.
2. Accept the 8B as draft-only; keep `local-executor-lite` tied to gemma and ship the rest of the wiring (bind override for Mac/Tailscale, rotate apinex key, opencode + Hermes/Telegram).
3. Deep-reverse-engineer the magnitude-service acquisition resolver to flip LFM to Installed (heavy).
