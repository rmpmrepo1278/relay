#!/usr/bin/env python3
"""topic_gc.py — Single writer for Telegram forum topics + weekly GC."""
import json, urllib.request, urllib.parse, os
HERMES_HOME=os.path.expanduser("~/.hermes")
def load_env():
    env={}
    for l in open(os.path.join(HERMES_HOME, ".env")):
        s=l.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1)
        env[k.strip()]=v.strip().strip('"').strip("'")
    return env
env=load_env()
tok=env["TELEGRAM_BOT_TOKEN"]
ch=env["TELEGRAM_HOME_CHANNEL"]
TMAP=os.path.join(HERMES_HOME, "agentbus", "topic_map.json")
def api(m, **p):
    url=f"https://api.telegram.org/bot{tok}/{m}"
    data=urllib.parse.urlencode(p).encode()
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url,data=data),timeout=10).read())
    except Exception as e:
        return {"ok":False,"description":str(e)}
def gc():
    import json as J
    with open(TMAP) as f:
        tmap=J.load(f)
    active=set(tmap.values())
    active.add(1)
    print(f"Active topics: {sorted(active)}")
    deleted=0
    for tid in list(range(1,30)) + list(range(10000,10250)):
        if tid in active:
            continue
        try:
            r=api("deleteForumTopic", chat_id=ch, message_thread_id=tid)
            if r.get("ok"):
                print(f"Deleted stale topic {tid}")
                deleted+=1
        except Exception:
            pass
    print(f"GC complete: deleted {deleted} stale topics")
if __name__=="__main__":
    gc()
