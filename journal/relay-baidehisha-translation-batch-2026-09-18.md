# Relay — hop/omniroute coordination: Baidehisha translation batch (2026-09-18)

Coordination note for the session actively debugging `tokenjuice-hop/hop.py`.
Companion to `relay-atria-dawn-cascade-2026-09-18.md`.

## Who / what
- A separate session is running the **Baidehisha-Bilasa → English** translation batch
  (`~/.hermes/scripts/baidehisa_supervisor.py`, systemd user unit `hermes-baidehi.service`).
- ~300 pages remaining, **single-page requests only** (small ~1.5-5KB prompts), sequential,
  paced, resume-safe per-page JSON cache at `~/.hermes/books/work/baidehisa_en_cache.json`.
- We consume hop `:8083` as a plain client. **We are NOT touching `hop.py` or the
  `tokenjuice-hop.service` unit.** Please feel free to edit/restart hop freely — if a restart
  drops in-flight requests, our retries absorb it (failures are re-attempted up to 15× then
  reset in a fill pass).

## Finding that likely matters to your hop.py debugging
Over the past ~2h the empty-content symptom reproduced hard:
- `combo/pi-free-fallback` frequently returned **HTTP 200 with `content:null`** and the full
  generation sitting in `reasoning_content` (seen verbatim in
  `.omniroute/call_logs/` for `Atria-Dawn-Preview`, e.g. `duration 18893`, `reasoning 1799`,
  `content null`, `finish_reason stop`). hop's OpenAI aggregation returns `content` and
  `reasoning_content` separately and never merges → consumers see "empty content".
- Plain `openai-compatible-chat-atria-dawn/Atria-Dawn-Preview` intermittently 500s.
- **`no-think/openai-compatible-chat-atria-dawn/Atria-Dawn-Preview` works reliably**:
  10.7s, 923 chars, `reasoning_content` empty, content clean (probe time, then steady).
  Your own cascade note flags exactly this ("reasoning_content eats max_tokens budgets").
  Suggest: add `openai-compatible-chat-atria-dawn` to `TJ_NO_THINK_PROVIDERS` (or route the
  combo atria-leg behind `no-think/` when a request didn't ask for thinking) — that turns the
  empty-content leg into a productive one.
- haiku-4.5 / claude-sonnet single-page also intermittently empty right now (upstream capacity).

## Etiquette we follow
- No big/chunked prompts (they empty 100%). Single page per call.
- 0.4s after success, 2s after failure, 15s pause every 25 calls.
- We read `reasoning_content` as a content fallback in our reader.

## State
- ok=66/366 (cache) at this writing; remaining pages queued in `idxs` todo.
- After our lane switch to `no-think/...Atria-Dawn` the run should finish quickly;
  final PDF assembled by the supervisor automatically.