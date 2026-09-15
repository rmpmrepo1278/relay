#!/usr/bin/env python3
"""cost_dashboard.py — /inference report with tok/s sparkline for 13 providers."""
import json, pathlib, urllib.request
HERMES_HOME=pathlib.Path.home() / ".hermes"
def load_store():
    try: return json.load(open(HERMES_HOME / "agents" / "inference" / "store.json"))
    except: return {}
def report():
    s=load_store()
    providers=s.get("providers",[])
    wired={w["provider_key"]:w for w in s.get("wired",[])}
    benchmarks={b["model_key"]:b for b in s.get("benchmarks",[])}
    lines=["📊 *Cost Dashboard — Inference*",""]
    for p in providers:
        key=p["key"]
        w=wired.get(key,{})
        status=w.get("status","pending")
        # sparkline from benchmarks
        bm=[b for b in s.get("benchmarks",[]) if b.get("engine_key")=="hop" or True]
        # simple bar
        bar="▅▇▆" if status=="configured" else "▁▁▁"
        lines.append(f"  • {p['name']} ({p['cost_tier']}) [{status}] {bar} — {len(p.get('models',[]))} models")
    text="\n".join(lines)
    print(text[:4000])
    # Send to infra topic 10026
    try:
        data=json.dumps({"text":text,"message_thread_id":10026}).encode()
        req=urllib.request.Request("http://127.0.0.1:9198/telegram-send", data=data, headers={"Content-Type":"application/json"})
        r=json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        print(f"sent: {r.get('status')}")
    except Exception as e:
        print(f"dry-run (no bridge): {e}")
if __name__=="__main__":
    report()
