# Relay — Jenny Greeting/Reply Fix

## Problem
User sent "hey jenny -" expecting a conversation. The `/jenny` bridge handler
queued it as a bus directive (correct), but Jenny treated *any* directive as a
delegation order — a greeting got routed to homelab via the keyword fallback.

## Fixes
1. `_looks_like_greeting(title)` — detects small-talk (hi/hey/how are you/thanks,
   mentions of jenny in ≤3 words) so Jenny replies instead of delegates.
2. `_friendly_reply(title)` — warm Chief-of-Staff responses (status/how-can-I-help/
   who-are-you/thanks/generic).
3. `plan()` user_directive branch now splits: greeting → `reply_chat`, else → delegate.
4. `act()` `reply_chat` handler: sends reply to own topic (10000), marks bus task done.
5. **Bug fixed**: `_mark_task_ended(key, status, proof)` — earlier code tried
   `GET /task?op=set&key=...` which the broker rejects ("no such endpoint").
   Broker only accepts POST JSON. Delegate branch now also uses it.

## Verified
- New greeting directive `jenny-1789407252-hello` ("hey jenny") → processed in
  cycle #25 → task `done` proof `replied_to_rohit` → Telegram send confirmed.
- All 11 services running, all 8 loops rc=0, no errors.

Note: earlier handled-marker TTL (24h) means the original "hey jenny -" won't
reply again; a fresh message works. Jenny remains always-on (daemon), replying
on next cycle (~30 min) or via `/jenny` brief.

## Commit
`2026-09-14` beyond orchestration-layer deployment (`045fcde`).