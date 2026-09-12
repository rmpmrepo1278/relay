---
name: memory-scanner
description: Proactive episodic memory scanning — finds stuck items, forgotten decisions, pending todos across 14k+ messages
---

# Memory Scanner Skill

## Purpose

Periodically scans all episodic memory (14,658 messages across 1,784 sessions) to find:

- **Stuck items**: containers in crash loops, services that won't start, errors recurring
- **Forgotten decisions**: "need to decide", "should I", trade-off analysis left dangling
- **Pending todos**: "need to run/fix/check/verify" — action items that may have been forgotten
- **Feedback prompts**: "could be better", "missing feature" — improvement notes

## Commands

```
/memory scan                # Scan all categories, print report
/memory scan --categories stuck,todo  # Scan specific categories
/memory notify              # Scan + send report to Telegram (Infra topic)
/memory scan --limit 5      # Limit items per category
```

## Integration

- **Cron**: Runs as `/memory notify` daily at 9pm (via morning_pipeline or cron)
- **Bridge**: Accessible via `/cmd` with `/memory scan` or `/memory notify`
- **Data source**: `~/.hermes/data/unified_memory.db` (SQLite FTS5 + LIKE fallback)
- **Output**: Telegram Infra topic (7356) unless no category match → General digest

## Scan Patterns

| Category | Patterns |
|----------|----------|
| stuck | "stuck in/on/with", "crash", "won't start", "cycling" |
| decision | "need to decide", "should I", "trade-off", "pros and cons" |
| todo | "need to run/fix/check", "should run/fix", "todo:", "action item" |
| feedback | "feedback", "good/bad", "could be better", "missing feature" |

## Memory

The scanner stores findings as facts in the temporal KG for tracking resolution status.
Each finding gets a `status` predicate: `open` → `in_progress` → `resolved`.
