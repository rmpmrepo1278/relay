---
created: 2026-08-14
confidence: high
source: relay session log
tags: [telegram, gateway, hermes, polling, 409, n8n-bridge, dedup, briefings]
---

# Relay: Telegram 409 polling conflict root-caused + fixed, notification noise reduced

## 1. Telegram errors (409 polling conflict loop) — FIXED
- Symptom: `hermes-gateway` looped on `409 Conflict: terminated by other getUpdates request`
  ~1/min (580+ in 24h). Counter always reset at 1/8, never escalated to 8/8.
- ROOT CAUSE (finally): `n8n_bridge_server.py` (`~/.hermes/scripts/`, n8n-bridge.service)
  had its OWN Telegram long-polling thread (`_telegram_poller()`, `_telegram_get_updates`,
  using the SAME `TELEGRAM_BOT_TOKEN` as hermes-gateway). Two concurrent getUpdates
  sessions on one bot token -> permanent 409. The gateway process itself was NOT the
  problem (was the victim of the second poller).
- Evidence: `ss -tnp | grep 149.154` showed TWO processes connected to api.telegram.org:
  the gateway (`hermes` binary) AND a second `python n8n_bridge_server.py`. The n8n-bridge
  process was later confirmed via `ps -p <pid>` + cgroup.
- FIX: bridge poller is now opt-in — only starts if `BRIDGE_TELEGRAM_POLLER=1`.
  Default off; hermes-gateway is the single getUpdates poller. Gateway restarted,
  reconnected cleanly at 13:45, ZERO conflicts since (~hours, verified).
- Files: `~/.hermes/scripts/n8n_bridge_server.py`. Committed to AgentChaguli repo
  (home dir) as 5becc9c. Note the home dir `/home/rohit` IS a git repo (remote: AgentChaguli).

## 2. Notification noise reductions
- `mind_loop.py` `observe_email()` called nonexistent `scripts/proactive/email_intelligence.py`
  every 30s cycle, silently no-op'd, but the pattern re-created digest re-runs. Now it
  only reflects the scheduler's once-daily digest (email_intelligence job at 12:00) from
  `data/alerts_inbox.jsonl`. Committed 5becc9c.
- Bridge no longer posts `🔕 Throttled N repeat notification(s)` summaries to Telegram
  (was itself adding noise). Committed 5becc9c.
- `hermes-agent/scripts/evening_briefing.py` now skips Telegram send when the briefing
  is empty (no goal activity + no wellness check-in + no system data). Committed to
  AgentRocki repo as 4490e3fcd.

## 3. Allowlist (user Q: "why closed list?")
- `TELEGRAM_ALLOWED_USERS=8607397452` in `~/.hermes/.env` + `.env.systemd` + master.env.
  Fail-closed by design: only allowlisted user IDs get LLM replies; gateway defaults to
  deny otherwise. `8607397452` IS Rohit's ID (his `[Rohit Mishra]` messages got LLM replies
  in state.db). The "can't send" issue was the polling conflict (messages not being received),
  not the allowlist. No config change needed.

## 4. Career India-jobs — no code bug
- The placeholder `script.sh` trail was a false lead; only a SKILL.md exists. India job
  postings in pasted chats were agent-fabricated output (no tool executed), not real
  pipeline data. career_engine.py already filters `in.linkedin.com` etc at read time.
