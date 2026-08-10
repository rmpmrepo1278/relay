#!/usr/bin/env python3
"""Benchmark an ollama model (generation tok/s + native tool-call) and append the result to the canonical store at memory/benchmarks/llm-benchmarks.json.

Usage:
  python3 bin/bench_llm.py gemma4:12b --ctx 8192 --note "post July-refresh weights"
  python3 bin/bench_llm.py qwen2.5:7b --reps 3 --think --host home-hp

Each run self-describes host + software so numbers stay comparable across hardware upgrades.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import httpx

STORE = Path(__file__).resolve().parent.parent / "memory" / "benchmarks" / "llm-benchmarks.json"
DEFAULT_BASE = "http://127.0.0.1:11434"

PROMPT = "Explain how tool calling works in large language models with three concrete agentic examples. Be detailed."
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}]
TOOL_MSG = {"role": "user", "content": "What is the weather in Paris right now? Use the tool."}


def ollama_version():
    for cmd in (["ollama", "--version"], ["docker", "exec", "ollama", "ollama", "--version"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split()[-1]
        except Exception:
            pass
    return None


def gen_bench(client, model, ctx, predict, thinking):
    body = {
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "options": {"num_ctx": ctx, "num_predict": predict, "temperature": 0},
    }
    if thinking is not None:
        body["think"] = thinking
    t0 = time.time()
    d = client.post("/api/generate", json=body, timeout=900).json()
    wall = time.time() - t0
    if "error" in d:
        raise RuntimeError(d["error"])
    ev = d.get("eval_count", 0)
    evd = d.get("eval_duration", 1) / 1e9
    pe = d.get("prompt_eval_count", 0)
    ped = d.get("prompt_eval_duration", 1) / 1e9
    return {
        "tok_per_s": round(ev / evd, 2) if evd else None,
        "eval_count": ev,
        "eval_duration_ms": round(d.get("eval_duration", 0) / 1e6, 1),
        "prompt_eval_tok_per_s": round(pe / ped, 1) if ped else None,
        "prompt_eval_count": pe,
        "load_duration_ms": round(d.get("load_duration", 0) / 1e6, 1),
        "wall_s": round(wall, 1),
    }


def tool_bench(client, model, ctx):
    body = {
        "model": model,
        "messages": [TOOL_MSG],
        "stream": False,
        "tools": TOOLS,
        "options": {"num_ctx": ctx, "temperature": 0},
        "think": False,
    }
    t0 = time.time()
    d = client.post("/api/chat", json=body, timeout=900).json()
    wall = time.time() - t0
    if "error" in d:
        raise RuntimeError(d["error"])
    calls = d.get("message", {}).get("tool_calls") or []
    return {
        "tool_call_correct": bool(calls),
        "tool_call_names": [c["function"]["name"] for c in calls],
        "tool_call_latency_s": round(wall, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model")
    ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--predict", type=int, default=120)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--think", action="store_true", default=None, help="enable thinking mode")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--host", default="home-hp")
    ap.add_argument("--runner", default="Vulkan")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-tool", action="store_true")
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base, timeout=900)
    store = json.loads(STORE.read_text())
    entry = {
        "id": time.strftime("%Y%m%d-%H%M%S") + "-" + args.model.replace(":", "-"),
        "date": date.today().isoformat(),
        "host": args.host,
        "software": {
            "ollama_version": ollama_version(),
            "runner": args.runner,
            "device": "iGPU",
            "quant": "Q4_K_M",
            "num_ctx": args.ctx,
            "num_predict": args.predict,
            "temperature": 0,
            "keep_alive": 0,
            "thinking": "on" if args.think else "off",
            "note": args.note,
        },
        "entries": [],
        "tool_call": {},
    }

    for rep in range(args.reps):
        try:
            g = gen_bench(client, args.model, args.ctx, args.predict, args.think)
            entry["entries"].append({"model": args.model, "run": rep + 1, **g})
            print(f"run {rep+1}: {g['tok_per_s']} tok/s (load {g['load_duration_ms']}ms, prompt {g['prompt_eval_tok_per_s']}/s)")
        except Exception as e:
            print(f"run {rep+1} FAILED: {e}", file=sys.stderr)

    if not args.no_tool:
        try:
            t = tool_bench(client, args.model, args.ctx)
            entry["tool_call"] = t
            print(f"tool: {t['tool_call_names'] or 'NONE'} {t['tool_call_latency_s']}s correct={t['tool_call_correct']}")
        except Exception as e:
            print(f"tool FAILED: {e}", file=sys.stderr)

    store["benchmarks"].append(entry)
    STORE.write_text(json.dumps(store, indent=2) + "\n")
    print(f"appended to {STORE}")


if __name__ == "__main__":
    main()
