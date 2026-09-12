---
name: session-handoff
description: Save and resume Claude Code sessions with conversation context between Telegram and laptop.
---

# Session Handoff Skill

## Purpose

Enables seamless context handoff between Telegram conversations and local
Claude Code sessions. Save your conversation context on Telegram, then resume
it on your laptop with a fresh Claude Code session that has all the context.

## Usage

From Telegram:
```
/claude-save-session "<topic>"     # Save current context to a named topic
/claude-load-session "<topic>"     # Load saved context (prints context)
/claude-resume-session "<topic>"   # Resume in a new Claude Code session
/claude-sessions                   # List saved sessions
```

## How It Works

1. **Save**: `/claude-save-session "nginx-fix"` captures the conversation
   context (pulling relevant memory from unified_memory.db) and saves it
   to `~/.hermes/data/claude_sessions/nginx-fix.json`

2. **Load**: `/claude-load-session "nginx-fix"` retrieves the saved context

3. **Resume**: `/claude-resume-session "nginx-fix"` loads the context and
   starts a new headless Claude Code session with `--context` parameter,
   so Claude has full background from the Telegram conversation

4. **List**: `/claude-sessions` shows all saved sessions

## Integration

- Bridge `/cmd`: `/claude-save-session`, `/claude-load-session`, `/claude-resume-session`, `/claude-sessions`
- Local CLI: `python3 ~/.hermes/skills/session-handoff/scripts/session_handoff.py <cmd>`
- Sessions persist in `~/.hermes/data/claude_sessions/` as JSON files

## Example

```
Telegram: /claude "Check why the n8n container is crashing"
Telegram: /claude-save-session "n8n-debug"
... (later, on laptop)
Laptop: /claude-resume-session "n8n-debug"
  → Claude Code starts with full context of the n8n debugging session
```
