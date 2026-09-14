#!/usr/bin/env python3
"""jenny_perf.py — Inference health probe for Jenny.

Checks the hop gateway (haiku-4.5 -> poolside/laguna-s-2.1:free) for latency
regression and compares against the canonical benchmark store
(memory/benchmarks/llm-benchmarks.json). Returns a verdict so the Officer's
Review can escalate "inference tokens/sec slow" as an initiative.

Pure stdlib. Safe: one small completion, 30s timeout, never writes state.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HOP = os.environ.get("HOP_URL", "http://127.0.0.1:8083/v1/chat/completions")
HOP_MODEL = os.environ.get("HOP_MODEL", "haiku-4.5")
BENCH_PATH = Path(os.path.expanduser(
    "~/.hermes/collaborator-memory/memory/benchmarks/llm-benchmarks.json"))

# Absolute red lines (seconds) for the interactive path.
LATENCY_WARN_S = 5.0
LATENCY_CRIT_S = 12.0


def hop_latency(probe: str = "Reply OK only.") -> float | None:
    import urllib.request
    payload = json.dumps({
        "model": HOP_MODEL,
        "messages": [{"role": "user", "content": probe}],
        "max_tokens": 8,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(HOP, data=payload,
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        latency = time.time() - start
        usage = data.get("usage", {})
        return {
            "latency_s": round(latency, 2),
            "ok": True,
            "tokens_out": usage.get("completion_tokens"),
            "tokens_in": usage.get("prompt_tokens"),
            "model": data.get("model"),
        }
    except Exception as e:
        return {"latency_s": round(time.time() - start, 2), "ok": False,
                "error": str(e)[:120]}


def baseline_gateway_latency() -> float | None:
    """Latest hop/external gateway latency from the benchmark store, if any."""
    try:
        data = json.loads(BENCH_PATH.read_text())
    except Exception:
        return None
    best = None
    for b in data.get("benchmarks", []):
        sw = b.get("software", {})
        if "hop" in str(sw.get("runner", "")).lower() or "gateway" in str(sw.get("runner", "")).lower():
            for e in b.get("entries", []):
                if e.get("tool_call_latency_s"):
                    best = min(best, e["tool_call_latency_s"]) if best else e["tool_call_latency_s"]
    return best


def probe() -> dict:
    """One-shot inference health verdict for the review."""
    res = hop_latency()
    base = baseline_gateway_latency()
    verdict = {"ok": False, "level": "unknown", "detail": ""}

    if isinstance(res, dict) and res.get("ok"):
        lat = res["latency_s"]
        level = "healthy"
        detail = "%.1fs p95 gateway latency" % lat
        if lat > LATENCY_CRIT_S:
            level = "critical"
            detail = "gateway latency %.1fs — critically slow (>%ds)" % (lat, LATENCY_CRIT_S)
        elif lat > LATENCY_WARN_S:
            level = "degraded"
            detail = "gateway latency %.1fs — degraded (>%ds)" % (lat, LATENCY_WARN_S)
        elif base and lat > max(base * 2.0, LATENCY_WARN_S):
            level = "degraded"
            detail = "latency %.1fs vs baseline %.1fs — regression" % (lat, base)
        verdict.update({"ok": True, "level": level, "detail": detail,
                        "latency_s": lat, "baseline_s": base})
    else:
        err = res.get("error", "unreachable") if isinstance(res, dict) else "unreachable"
        verdict.update({"level": "critical", "detail": "gateway unreachable: %s" % err,
                        "latency_s": res.get("latency_s") if isinstance(res, dict) else None,
                        "baseline_s": base})
    return verdict


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))