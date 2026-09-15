#!/usr/bin/env python3
"""board_prune.py — Archive done tasks older than 7 days to prevent board bloat."""
import json, urllib.request, os, datetime
BUS="http://127.0.0.1:9107"
ARCHIVE=os.path.expanduser("~/.hermes/agentbus/data/board_archive.jsonl")
def bus(path, method="GET", payload=None):
    data=json.dumps(payload).encode() if payload else None
    req=urllib.request.Request(f"http://127.0.0.1:9107{path}", data=data, method=method, headers={"Content-Type":"application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    except Exception as e:
        return {"ok":False,"error":str(e)}
def prune(days=7):
    st=bus("/status")
    tasks=st.get("tasks",{})
    cutoff=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    to_archive=[]
    for k,v in list(tasks.items()):
        if v.get("status")!="done":
            continue
        ts=v.get("updated") or v.get("created") or 0
        try:
            dt=datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
        except:
            continue
        if dt < cutoff:
            to_archive.append((k,v))
    if not to_archive:
        total=len(tasks)
        done=sum(1 for v in tasks.values() if v.get("status")=="done")
        print(f"board_prune: no done tasks older than {days}d (total {total}, done {done})")
        return
    os.makedirs(os.path.dirname(ARCHIVE), exist_ok=True)
    with open(ARCHIVE,"a") as f:
        for k,v in to_archive:
            f.write(json.dumps({"archived_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "key":k, "task":v})+"\n")
    for k,v in to_archive:
        bus("/task", method="POST", payload={"op":"add","key":k,"title":v.get("title",""),"area":v.get("area",""),"owner":v.get("owner",""),"status":"archived","note":v.get("note","")})
    print(f"board_prune: archived {len(to_archive)} done tasks >{days}d to {ARCHIVE}")
if __name__=="__main__":
    import sys
    days=int(sys.argv[1]) if len(sys.argv)>1 else 7
    prune(days)
