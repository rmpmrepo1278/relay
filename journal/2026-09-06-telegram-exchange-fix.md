# Telegram exchange fix — context bloat, notification noise, stale health (2026-09-06)

Status: DONE, verified live.

## Problem (reported by Rohit on the Chaguli Telegram
channel, 2026-09-06 night)
1. Context bloat: "Context is over the compression threshold (~400,357 tokens
   >= 98,304)", compression ineffective, "Request payload too large (413)",
   session auto-reset loop.
2. Leaky per-turn notifications in-channel: "✅ Agent turn done (telegram):
   💭 Reasoning…" and "⚠️ **Not verified** — agent described an action/result
   but no tool actually executed".
3. Stale/incorrect health data in agent replies: Ollama unreachable, proxy
   down, ~40 containers (actually 27), RAM 34Gi (actually 62Gi).
4. Career-ops hallucinations: fabricated "pieplie" pipeline, run_apply.sh,
   linkedin_jobs.py, Greenhouse auto-apply score >= 52.
5. Repeated "reinstall Ollama" suggestions after Ollama was removed.

## Root causes (all confirmed)
- `~/.hermes/HERMES.md` (loaded into the agent's system prompt; container
  `/opt/data/HERMES.md` is the same bind-mounted file) was a STALE ontology:
  claimed Arch Linux / HP Pavilion laptop / 34GB RAM / ~40 containers / Ollama
  (llama3.2:3b, qwen2.5:14b) / 85 scheduler jobs / west Panel etc. Hallucinated
  career pipeline came from the same stale picture + days-old session context.
- `~/.hermes/hooks/telegram-notify/handler.py` POSTED "✅ Agent turn done"
  (+ a response snippet incl. 💭 reasoning lines) into the SAME Telegram chat
  the gateway transcribes. Those posts re-entered the conversation context →
  the transcript grew to ~400K tokens, compression maxed out (max_attempts 3),
  413, session auto-reset. Rinse/repeat → recurring auto-resets (see
  state.db sessions with end_reason=session_reset, incl. 3624-message session
  20260929 ending 2026-09-05 22:28).
- `~/.hermes/hooks/verify-agent-claims/handler.py` posted "⚠️ Not verified"
  follow-ups into the same chat (same feedback loop).
- `~/.hermes/scripts/healthcheck.sh` (the exact script HERMES.md told the
  agent to run) still probed Ollama `:11434` and agentproxy `:8080` — both
  removed → agent faithfully reported "Ollama unreachable / Proxy down".
- `~/.hermes/scripts/autonomous_work_session.py` health snapshot asked
  `systemctl --user is-active hermes-gateway` — no such unit exists (gateway is
  s6-supervised inside the `hermes` container) → "Gateway: inactive".

## Fixes (all committed to the box; .bak-telegramfix copies kept)
1. `~/.hermes/HERMES.md` — full rewrite to current reality: host home-hp
   Debian 13, Ryzen 7 4700U, 62Gi RAM, 221G NVMe root (70%), 4.6T USB; 28
   containers (~27 running); gateway s6-supervised in `hermes` container
   (HOME=/opt/data); scheduler 106 jobs; LLM front door = hop :8083
   (alias haiku-4.5) → magnitude :20128 (auto/best-coding, 1M ctx); NO
   Ollama/agentproxy; career-ops reality = host `~/projects/career-ops`
   (no pieplie/greenhouse fabrication); GROUNDING RULE section (this file
   wins over stale memory).
2. `telegram-notify/handler.py` — agent:end completions are now LOG-ONLY
   (`~/.hermes/logs/telegram_notify.log`); no more per-turn posts. Bridge
   `/run` announcements kept.
3. `verify-agent-claims/handler.py` — "⚠️ Not verified" now recorded to
   `state/verify_agent_claims.jsonl` + stderr only; no Telegram post.
   Removed `_post_followup` + dead `_log` duplicate.
4. `healthcheck.sh` — Ollama/Proxy sections replaced with hop :8083 health +
   magnitude service/models (`auto/best-coding`); note that Ollama was removed.
5. `autonomous_work_session.py` — health_snapshot: gateway check → `hermes`
   container status + hop /health (no nonexistent user unit); added RAM line to
   snapshot and Telegram report.

## Verification (live)
- python3 -m py_compile all 3 edited .py OK; bash -n healthcheck.sh OK.
- `bash ~/.hermes/scripts/healthcheck.sh` → 62Gi Mem, 70% disk, 27 containers,
  hermes Up (healthy), hop OK, magnitude active (auto/best-coding), DNS good.
- `--health-only` snapshot → docker_total 27, disk 70, RAM 62Gi/8.7Gi,
  gateway "Up 26 hours (healthy)", hop ok.
- channel_directory.json + gateway_state.json untouched; gateway not restarted
  (hooks are re-read per event).

## No restart / next action
- Gateway reads hooks per-event, loads HERMES.md at session start: the next
  NEW session picks it up. Recommend sending `/new` in the Chaguli chat to
  drop the residual 43-message blown-up session (20260906) and start clean.
- The recurring auto-reset rows in state.db are historical (pre-fix) — no db
  surgery needed.