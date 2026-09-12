"""OpenJarvis integration tools for Hermes Agent.

Lets the Hermes agent delegate a query to the local OpenJarvis agent
(``http://127.0.0.1:1377``, OpenAI-compatible server as ``openjarvis.service``).
OpenJarvis runs an orchestrator agent with its own tool surface (code
interpreter, web search, shell exec, file read, retrieval) and memory, routed
through the shared hop LLM gateway.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_OPENJARVIS_URL = "http://127.0.0.1:1377/v1/chat/completions"
_MODEL = "haiku-4.5"
_TIMEOUT = 120
_MAX_TOKENS = 2048


def _persist_reply(reply: str) -> None:
    """Best-effort: write a Jarvis reply into Hermes memory via the host bridge.

    Non-fatal: any failure is logged at debug and swallowed so the agent always
    receives the original reply.
    """
    if not reply or reply.startswith("Error:"):
        return
    payload = {
        "text": reply,
        "namespace": "jarvis",
        "domain": "JARVIS",
        "tags": ["jarvis_reply"],
    }
    try:
        req = urllib.request.Request(
            "http://172.18.0.1:9199/memory-write",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception:
        logger.debug("openjarvis memory-write skipped", exc_info=True)


def _ask(message: str, *, model: str = _MODEL) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": _MAX_TOKENS,
    }
    req = urllib.request.Request(
        _OPENJARVIS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return f"Error: OpenJarvis HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001 - surface connect errors to the agent
        return f"Error: OpenJarvis unreachable at {_OPENJARVIS_URL}: {exc}"
    try:
        return body["choices"][0]["message"]["content"] or ""
    except Exception:  # noqa: BLE001
        return f"Error: unexpected OpenJarvis response: {json.dumps(body)[:500]}"


def openjarvis_ask(args: dict, **_: Any) -> str:
    """Send a natural-language task to OpenJarvis and return its reply."""
    message = str(
        args.get("message") or args.get("query") or args.get("text") or ""
    ).strip()
    if not message:
        return "Error: 'message' is required."
    reply = _ask(message)
    _persist_reply(reply)
    return reply


_SCHEMAS = {
    "openjarvis_ask": {
        "type": "function",
        "function": {
            "name": "openjarvis_ask",
            "description": (
                "Delegate a task to the local OpenJarvis agent (orchestrator with its own "
                "tools: code interpreter, web search, shell exec, file read, retrieval, "
                "and its own memory). Use when the task fits OpenJarvis's specialized "
                "tools, or to get a second opinion from an independent agent. OpenJarvis "
                "runs on the same hop LLM gateway as Hermes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The task or question to send to OpenJarvis, in natural language.",
                    },
                },
                "required": ["message"],
            },
        },
    },
}

_HANDLERS = {"openjarvis_ask": openjarvis_ask}

_registered = False


def register_tools(ctx) -> None:
    """Register the OpenJarvis tools in the ``openjarvis`` toolset (idempotent)."""
    global _registered
    if _registered:
        return
    _registered = True
    for name, schema in _SCHEMAS.items():
        function_schema = schema["function"]
        ctx.register_tool(
            name=name,
            toolset="openjarvis",
            schema=function_schema,
            handler=_HANDLERS[name],
            description=function_schema["description"],
            emoji="\U0001f916",  # robot
        )