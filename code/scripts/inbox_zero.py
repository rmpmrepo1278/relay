#!/usr/bin/env python3
"""inbox_zero.py — One-tap Inbox Zero for Gmail (complementary to jenny_gmail.py)."""
import json, urllib.request, os, time
BUS="http://127.0.0.1:9107"
BRIDGE="http://127.0.0.1:9198"
def bus(path, payload=None):
    import urllib.request, json
    data=json.dumps(payload).encode() if payload else None
    req=urllib.request.Request(f"http://127.0.0.1:9107{path}", data=data, method="POST" if payload else "GET", headers={"Content-Type":"application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    except Exception as e:
        return {"ok":False,"error":str(e)}
def propose(action, payload, thread_id=None, category=None):
    data={"action":action, "message_thread_id":thread_id, "category":category, **payload}
    try:
        req=urllib.request.Request(f"{BRIDGE}/propose", data=json.dumps(data).encode(), headers={"Content-Type":"application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    except Exception as e:
        return {"status":"error","error":str(e)}
def run():
    st=bus("/status")
    tasks=st.get("tasks",{})
    # Find Gmail tasks: owner=rohit or area in personal and status ready, created in last 24h
    candidates=[]
    for k,v in tasks.items():
        if v.get("owner")=="rohit" and v.get("status")=="ready":
            candidates.append((k,v))
    if not candidates:
        print("inbox-zero: no Gmail tasks to propose")
        return
    for k,v in candidates[:3]:
        title=v.get("title","")
        note=v.get("note","")[:200]
        area=v.get("area","other")
        # Create a proposal to reply or handle
        # For now, create a generic send_telegram proposal that will surface as /send /skip
        res=propose("send_telegram", {"content": f"Gmail: {title}\n{note}\n\nReply draft for {area}"}, thread_id=10122, category=area)
        print(f"proposed {k}: {res.get('proposal_id')}")

if __name__=="__main__":
    run()
