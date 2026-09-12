# Agent Kits — 15-module autonomy pack deployed to Hermes (2026-09-12)

Status: **live and verified on homelab** (`~/.hermes/scripts`, scheduler daemon restarted).

## What was built (grokbot / instinct / meta-muse feature map → Hermes)

Modules (all stdlib + requests only, shared backbone `agent_kits.py`):

| Module | Function | Scheduler job |
|---|---|---|
| `sentinel_gate.py` | approval gate: propose → human `/approve /deny /always`, always-allow rules, executes approved | `sentinel_gate_poll` (every min) |
| `voice_ingest.py` | Telegram voice → ffmpeg wav → Groq whisper → transcript + auto-commitment scan → inbox | (payload via listener) |
| `memory_commands.py` | editable topics memory over the shared git memory repo: list/show/append/forget/search (backups before destructive edits) | (via `/memory…`) |
| `commands.py` | `/approve /deny /always /sentinel /remember /forget /memory /skills /run /brief /vault /commitments /help` | (via listener) |
| `skills_lib.py` | markdown skill files (front-matter, steps, approval), init/list/show/run/validate | `skills_smoke` (hourly) |
| `routine_watcher.py` | event triggers: url_change / cmd_contains / tg_keyword / interval → fire skill/shell/tg/sentinel | `routine_watcher` (every 5 min) |
| `meeting_prep.py` | 10-min-before meeting card w/ memory context to Telegram, dedup | `meeting_prep` (every 10 min) |
| `quiet_threads.py` | stale open commitments → sentinel-gated nudge proposals | `quiet_threads` (daily 09:00) |
| `commitment_smart.py` | calendar-aware (skip during meetings), 1/day dedupe, urgent-only nudges, summary | `commitment_smart` (every 15 min) |
| `agent_mailbox.py` | drop-folder email → classify order/commitment/other → actions + digest | `agent_mailbox_process` (every 30 min) |
| `brief_feed.py` | morning digest: commitments/calendar/capsules/career/health/ideas | `brief_feed_daily` (07:30) |
| `vault.py` | filesystem credential vault (chmod 600, value never printed to chat) | (via `/vault`) |
| `record_workflow.py` | "teach a task": capture stdin steps → `.skill.md` → replay with `{args}` | (via CLI) |
| `browser_agent.py` | page snapshot (playwright if present else urllib) for watch jobs; vision gated | — |
| `telegram_reply_listener.py` | patched: slash-command routing, voice handling, every inbound logged to `data/tg_inbox.jsonl` | (existing job) |
| `hermes_scheduler.py` | patched: 8 new jobs (119 total after restart) | — |

## Key implementation notes
- Canonical commitments store is `data/commitments.json` `{active, history, stats}` — normalized via
  `agent_kits.load_commitments()` (used by commitment_smart, quiet_threads, brief_feed).
- Voice token fallback added (`_bot_token` reads `~/.hermes/.env` / `~/.omniroute/.env` like `_groq_key`);
  GTOKEN confirmed present. playtimes: whisper CLI absent → Groq backend.
- `skills_lib` fixed: `_skills()` returned `str` from `glob.glob` and `.suffix` never matched `.skill.md`
  (double suffix). Now `iterdir` + `endswith(".skill.md")`; added `validate`.
- `sentinel_gate` missing `import json` (CLI `--run` crashed) — fixed, verified green via scheduler journal
  at 09:23:11 without a daemon restart (subprocess jobs pick up file changes each run).
- Listener command path: `commands.handle(text, update=update)` — full `/cmd` text passed through.

## Verification (all on homelab)
- `py_compile` all 17 files remote.
- Memory: append/search/show/forget roundtrip on scratch topic `kit-test` (non-git topdir) ✅
- Vault: save/list/rm roundtrip ✅ (masked; secret removed after test)
- Sentinel: propose→approve→`run_approved` executed `echo`, then deny; status report ✅
- Browser fetch example.com (urllib engine, no playwright) ✅
- Mailbox `--process` empty-inbox ok ✅ · Routine `--run` no triggers ok ✅ · meeting `--next` idle ✅
- Commitments summary renders from real store (schema-fixed) ✅ · Brief renders ✅ · quiet preview ✅
- Skills `init/list` + `record_workflow` teach-a-task (`echo step; hostname`) replayed ✅ · `validate` ok ✅
- Scheduler restart: 119 jobs, no dupes, all scheduled fields present; `sentinel_gate_poll` /
  `routine_watcher` / `tg_reply_listener` green in journal ✅
- End-to-end: `/help /memory list /skills /sentinel` routed `{"status":"command"}`; replies sent via
  n8n bridge to TG; `data/tg_inbox.jsonl` written ✅

## Notes / carry-overs
- Backups: `~/.hermes/scripts/{telegram_reply_listener,hermes_scheduler}.py.bak-preminkits`.
- Hermes mail provisioning (AGENT_MAILBOX_ADDR / Google OAuth or postfix catch-all) still a TODO; mailbox
  processes drops when folder exists.
- Browser vision/click automation (qwen mmproj + playwright) still gated behind approval (docs/todo).
- Test artifacts left on box: `~/.hermes/skills/{whoami-kit,kit-demo}.skill.md`, scratch topic
  `kit-test.md`, `data/tg_inbox.jsonl` (4 test entries), `data/sentinel.log.jsonl`, back-up files.