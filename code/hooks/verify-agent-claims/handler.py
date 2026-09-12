"""verify-agent-claims — anti-fabrication gateway hook.

Cross-checks an agent's completion claims against the tools that ACTUALLY ran
during that turn (collected from `agent:step` events).

Goal: stop the agent from claiming "I ran X / done / resolved" in its reply when
it never executed any tool to back the claim.

Design:
  - `agent:step`    → accumulate executed tool names per session (the gateway
                      exposes `tools` = [{name, result, arguments}] for each turn).
  - `agent:end`     → if the response text makes an action/result claim but ZERO
                      tools were executed in that session's turn, record it to
                      verify_agent_claims.jsonl and stderr. Deliberately does NOT
                      post anything to Telegram — a "⚠️ Not verified" follow-up
                      sent into the same chat the gateway transcribes becomes
                      part of the next turn's context and bloats it, which is the
                      same feedback loop that caused the 413 / session auto-resets.

Purely advisory (non-blocking): never rewrites or blocks the agent's reply, so it
cannot break the pipeline. It only surfaces fabrications for review.
"""
import json
import logging
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HOOK_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "state"
VERIFY_LOG = STATE_DIR / "verify_agent_claims.jsonl"

# Claim patterns: text implying a tool ran / state changed / work was completed.
# Broad enough to catch "Ran X", "executed", "deployed", "resolved", "created",
# "completed", "updated", "fixed", "installed", "started", etc. — but NOT pure
# Claim patterns: report of an action that should require a real tool execution.
# We require EITHER a backticked command / script path (strong sign the agent
# claims it ran something) OR a strong state-change verb (executed/deployed/
# resolved/created/completed/updated/wrote/installed/regenerated/...). Bare
# "ran"/"run" is too ambiguous ("I ran through the options"), so it only counts
# when followed by a command/path/backtick token.
CLAIM_RE = re.compile(
    r"(?:`[^`]+`|[\w./-]+\.(?:py|sh|js|ts|bash)\b|"
    r"\b(?:executed?|deployed?|resolved?|created?|completed?|updated?|wrote|"
    r"installed?|regenerated?|built|restarted?|removed?|deleted?|modified|"
    r"generated|synced|rebuilt|archived|migrated)\b|"
    r"\b(?:ran|run)\s+(?:`[^`]+`|[\w./-]+\.(?:py|sh|js|ts|bash)\b))",
    re.IGNORECASE,
)

# In-memory tool registry per session. Keyed by session_id so one hook instance
# (process) works correctly; periodic prune prevents unbounded growth.
_executed_tools: dict[str, list[str]] = {}


def _prune(max_age_s: float = 600) -> None:
    now = time.time()
    stale = [sid for sid, tools in _executed_tools.items() if not tools]
    for sid in stale:
        _executed_tools.pop(sid, None)


def _on_agent_step(ctx: dict) -> None:
    session = ctx.get("session_id")
    if not session:
        return
    tools = ctx.get("tools") or []
    names = []
    for t in tools:
        if isinstance(t, dict):
            names.append(str(t.get("name") or ""))
        else:
            names.append(str(t))
    names = [n for n in names if n]
    if names:
        _executed_tools.setdefault(session, []).extend(names)


def _record(record: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        record["ts"] = datetime.now(timezone.utc).isoformat()
        with open(VERIFY_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _on_agent_end(ctx: dict) -> None:
    session = ctx.get("session_id") or ""
    response = (ctx.get("response") or "").strip()[:500]

    executed = _executed_tools.pop(session, []) or []
    ran_real_tool = bool(executed)
    _prune()

    # No execution in the turn at all + the text claims action/completion =>
    # fabrication. A real action would have left tool-call evidence.
    is_claim = bool(CLAIM_RE.search(response))
    if not ran_real_tool and is_claim and response:
        snippet = response[:120].replace("\n", " ")
        _record({
            "event": "possible_fabrication",
            "session": session,
            "executed_tools": [],
            "response": response[:400],
        })
        print(
            f"[verify-agent-claims] ⚠️ possible fabrication: session={session} "
            f"tools_executed=0 response='{snippet}'",
            flush=True,
        )


def handle(event_type: str, context: dict) -> None:
    ctx = context or {}
    if event_type == "agent:step":
        _on_agent_step(ctx)
    elif event_type == "agent:end":
        _on_agent_end(ctx)