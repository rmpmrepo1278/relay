#!/usr/bin/env python3
"""Session handoff — save/resume Claude Code sessions with context.

Usage:
  session_handoff.py save "topic name"          # Save current context under a name
  session_handoff.py load "topic name"          # Load saved context as --context string
  session_handoff.py list                       # List saved sessions
  session_handoff.py resume "topic name"        # Resume: load context + start new session
  session_handoff.py clear "topic name"         # Clear a saved session
"""
import json, sys, os, argparse, subprocess, uuid
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = HERMES_HOME / "data" / "claude_sessions"
STATE_DIR.mkdir(parents=True, exist_ok=True)

def save_session(topic: str, context: str = "") -> dict:
    """Save a conversation context under a topic name."""
    # If no context provided, try to get it from the current agent session
    if not context:
        context = f"# Session topic: {topic}\n# Saved at: {datetime.now(timezone.utc).isoformat()}\n"
        # Try to pull context from unified_memory
        try:
            sys.path.insert(0, str(HERMES_HOME / "scripts"))
            from unified_memory import UnifiedMemory
            mem = UnifiedMemory()
            results = mem.search(topic, top_k=10)
            if results:
                context += f"\n## Relevant past context:\n"
                for r in results[:5]:
                    context += f"  - {r.content[:300]}\n"
        except Exception:
            pass

    session = {
        "topic": topic,
        "context": context,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(uuid.uuid4())[:8],
    }

    path = STATE_DIR / f"{topic.replace(' ', '_').replace('/', '_')}.json"
    with open(path, "w") as f:
        json.dump(session, f, indent=2)

    return {"success": True, "session_id": session["session_id"],
            "topic": topic, "path": str(path), "context_len": len(context)}

def load_session(topic: str) -> dict:
    """Load a saved session's context."""
    path = STATE_DIR / f"{topic.replace(' ', '_').replace('/', '_')}.json"
    if not path.exists():
        return {"success": False, "error": f"No saved session for topic: {topic}"}

    with open(path) as f:
        session = json.load(f)

    return {"success": True, "context": session["context"], "session_id": session["session_id"],
            "created_at": session["created_at"], "topic": session["topic"]}

def list_sessions() -> dict:
    """List all saved sessions."""
    sessions = []
    for path in sorted(STATE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        with open(path) as f:
            s = json.load(f)
        sessions.append({
            "topic": s["topic"],
            "session_id": s.get("session_id", "?"),
            "created_at": s["created_at"],
            "context_len": len(s.get("context", "")),
        })
    return {"success": True, "sessions": sessions}

def resume_session(topic: str, task: str = "", workdir=None, model="") -> dict:
    """Load saved context and start a new Claude Code session."""
    loaded = load_session(topic)
    if not loaded["success"]:
        return loaded

    context = loaded["context"]
    sid = loaded.get("session_id", "unknown")

    # Start a new Claude Code session with the saved context
    cmd = [
        sys.executable,
        str(HERMES_HOME / "hermes-agent" / "scripts" / "claude_code_delegate.py"),
        "--task", task or f"Continuing work on: {topic}",
        "--mode", "headless",
        "--json",
        "--context", context,
    ]

    if workdir:
        cmd += ["--workdir", workdir]
    if model:
        cmd += ["--model", model]

    try:
        env = {**os.environ, "CC_HEADLESS_TIMEOUT": "300"}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=360, env=env)
        if r.returncode == 0:
            result = json.loads(r.stdout.strip())
            if result.get("status") == "completed":
                return {"success": True, "summary": result.get("summary", ""),
                        "session_id": result.get("session_id", ""), "original_session": sid,
                        "text": f"🤖 Resumed session `{sid}` for '{topic}'\n\n{result.get('summary','')[:400]}"}
            return {"success": False, "error": result.get("error", "unknown"), "raw": r.stdout[:200]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="Claude Code session handoff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("save", help="Save current context")
    p.add_argument("topic")
    p.add_argument("--context", default="", help="Context text (auto-fetched from memory if empty)")
    p.set_defaults(func=lambda a: save_session(a.topic, a.context))

    p = sub.add_parser("load", help="Load saved context")
    p.add_argument("topic")
    p.set_defaults(func=lambda a: load_session(a.topic))

    p = sub.add_parser("list", help="List saved sessions")
    p.set_defaults(func=lambda a: list_sessions())

    p = sub.add_parser("resume", help="Resume: load context + start new Claude Code session")
    p.add_argument("topic")
    p.add_argument("--task", default="", help="Override task for the new session")
    p.add_argument("--workdir", default=None)
    p.add_argument("--model", default="")
    p.set_defaults(func=lambda a: resume_session(a.topic, a.task, a.workdir, a.model))

    p = sub.add_parser("clear", help="Clear a saved session")
    p.add_argument("topic")
    p.set_defaults(func=lambda a: _cmd_clear(a))

    args = parser.parse_args()
    result = args.func(args)
    if isinstance(result, dict) and "text" in result:
        print(result["text"])
    else:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))

def _cmd_clear(args):
    path = STATE_DIR / f"{args.topic.replace(' ', '_').replace('/', '_')}.json"
    if not path.exists():
        return {"success": False, "error": f"No saved session for topic: {args.topic}"}
    path.unlink()
    return {"success": True, "text": f"🗑 Cleared session '{args.topic}'"}

if __name__ == "__main__":
    main()
