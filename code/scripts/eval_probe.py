#!/usr/bin/env python3
"""eval_probe.py - measure reply variance/latency of the real LLM front door
(hop gateway 127.0.0.1:8083 -> Magnitude). Replaces the fictional proxy caching
claim: honest numbers for the ACTUAL stack."""
import json, time, urllib.request, statistics, sys

GATEWAY = "http://127.0.0.1:8083/v1/chat/completions"
MODEL = "haiku-4.5"
PROMPT = "Reply with exactly the word: pong"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3

def call():
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 32}).encode()
    req = urllib.request.Request(GATEWAY, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read())
    dt_ms = (time.time() - t0) * 1000
    text = payload["choices"][0]["message"]["content"].strip()
    return dt_ms, text

samples = []
for i in range(N):
    try:
        dt, text = call()
        samples.append({"latency_ms": round(dt, 1), "reply": text})
        print(f"[{i+1}/{N}] {round(dt,0):.0f}ms  reply={text!r}")
    except Exception as e:
        print(f"[{i+1}/{N}] ERROR: {e}")

if len(samples) >= 2:
    lats = [s["latency_ms"] for s in samples]
    replies = [s["reply"].lower() for s in samples]
    unique = len(set(replies))
    result = {
        "gateway": GATEWAY, "model": MODEL, "samples": samples,
        "latency_median_ms": round(statistics.median(lats), 1),
        "latency_p50_p90": [round(sorted(lats)[int(len(lats)*0.5)-1],1), round(sorted(lats)[int(len(lats)*0.9)-1],1)] if len(lats)>=2 else None,
        "reply_variance": f"{unique}/{len(replies)} unique ({(1-(unique-1)/len(replies))*100:.0f}% agreement)" if unique>1 else f"1/{len(replies)} unique (0% variance)",
    }
    with open("/home/rohit/.hermes/data/eval_probe.json", "w") as f:
        json.dump(result, f, indent=2)
    print("SAVED: ~/.hermes/data/eval_probe.json")
else:
    print("INSUFFICIENT_SAMPLES")
    sys.exit(1)
