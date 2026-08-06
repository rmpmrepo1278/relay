# Relay Journal — 2026-08-06 (follow-up)

## CoS Briefing false alarms — fixed

User received a CoS briefing claiming two things were down:
- `⚠️ Local LLM: down on :18090`
- `📭 Calendar API unavailable.`

Both were **stale checks in `cos_briefing.py`**, not real outages:

1. **LLM port mismatch.** `get_llm_health()` checked `localhost:18090`, but the
   AgentHarness LLM proxy (`agentharness-llm-proxy.service`) actually runs on
   **:8080** and was healthy (`{"status":"ok"}`, PID 936386). Note: the systemd
   unit is `inactive (dead)` yet a process still listens on 8080 (orphaned from
   systemd since Aug 1, PPID 1, still serving). Hardcoded port updated 18090->8080.

2. **Calendar read a dead path.** `get_calendar()` called
   `skills/google-workspace/scripts/google_api.py` which **no longer exists**.
   The real calendar integration is `calendar_intelligence.py` which caches to
   `~/.hermes/state/calendar_events.json` (OAuth in `~/.hermes/calendar/token.json`,
   valid/refreshed today). Rewired to read that cache. Test: "✅ No meetings today".

Also confirmed: `get_email_unread()` references the same dead path but returns
`""` (silent) when it's missing, so it never fires a false alert. Needs wiring to
`~/.hermes/scripts/email_intelligence.py` eventually (not urgent).

### Other checks — clean
- `hermes_healthcheck.sh` already uses :8080 (consistent, no other stale 18090).
- No other `.py` in `~/.hermes` references the dead google_api.py path.

Commit: AgentChaguli `7eda9a7b3` — fix(briefing): LLM port 8080 + calendar cache

## Root cause pattern
Both false alarms were references to paths/ports that had drifted from reality
(script moved from `skills/google-workspace/` to `scripts/calendar_intelligence.py`;
LLM proxy port changed). When migrating a subsystem, its consumers (briefing,
healthchecks, scheduler) must be updated too — a real gap in the earlier cleanup
work. This is exactly the kind of "dead reference" to watch for.