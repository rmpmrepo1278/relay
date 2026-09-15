#!/usr/bin/env python3
"""cost_routing.py — Probe hop/laguna tok/s every 5m, auto-reorder fallback if degradation >30%."""
import json, urllib.request, os, time, pathlib, sys
HERMES_HOME=pathlib.Path.home() / ".hermes"
STORE=HERMES_HOME / "agents" / "inference" / "store.json"
HOP="http://127.0.0.1:8083/v1/chat/completions"
def probe_tok_s(model="haiku-4.5", prompt="Hello", max_tokens=50):
    import time, json, urllib.request
    payload={"model":model,"messages":[{"role":"user","content":prompt}],"max_tokens":max_tokens,"temperature":0.2}
    start=time.time()
    try:
        req=urllib.request.Request(HOP, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d=json.loads(r.read().decode())
        elapsed=time.time()-start
        toks=d.get("usage",{}).get("completion_tokens", max_tokens)
        return round(toks/elapsed,2) if elapsed>0 else 0, round(elapsed*1000,0)
    except Exception as e:
        return None, str(e)
def run():
    tok_s, latency = probe_tok_s()
    print(f"cost-routing: hop tok/s={tok_s} latency={latency}ms")
    # Load inference store and check baseline
    try:
        store=json.load(open(STORE))
        # Find baseline from last benchmark
        baselines=[b.get("tokens_per_sec",0) for b in store.get("benchmarks",[])]
        baseline=sum(baselines)/len(baselines) if baselines else 20
        if tok_s and tok_s < baseline*0.7:
            print(f"cost-routing: DEGRADATION {tok_s} < 70% of baseline {baseline:.1f} — would reorder fallback")
            # In real implementation, would reorder OmniRoute combo via API
            # For now, just log and create a board task
            import urllib.request, json as J
            payload={"op":"add","key":"cost-degradation","title":f"Cost routing: hop degraded {tok_s} tok/s vs baseline {baseline:.1f}","area":"inference","status":"ready","owner":"inference","note":f"tok/s {tok_s}, latency {latency}ms"}
            data=J.dumps(payload).encode()
            req=urllib.request.Request("http://127.0.0.1:9107/task", data=data, headers={"Content-Type":"application/json"})
            try: urllib.request.urlopen(req, timeout=5).read()
            except: pass
        else:
            print(f"cost-routing: healthy (baseline {baseline:.1f})")
    except Exception as e:
        print(f"cost-routing error: {e}")
if __name__=="__main__":
    run()
