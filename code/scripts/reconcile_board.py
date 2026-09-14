#!/usr/bin/env python3
"""reconcile_board.py — one-shot board cleanup run on the homelab.

Three buckets:
1. Hallucinated junk from the early (unvalidated) review run → discard.
2. "Unknown command" failures (domain script can't parse title) → mark done
   with deferred_human proof + post a ready human-attention task on jenny.
3. Duplicate ready tasks (same area+title) → keep one, dedup the rest.

Safe: never deletes, only advances status + appends proof.
"""
import json, urllib.request, sys, os

BUS = "http://127.0.0.1:9107"

def req(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req_ = urllib.request.Request(BUS + path, data=data,
                                  method="POST" if payload else "GET",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req_, timeout=8) as r:
        return json.loads(r.read().decode())

def main():
    board = req("/board").get("tasks", {})
    done, human, deduped = 0, 0, 0

    # bucket 1 & 2
    for key, t in list(board.items()):
        status = t.get("status")
        proof = (t.get("proof") or "")
        title = t.get("title", key)
        area = t.get("area", "?")
        if status not in ("failed", "ready"):
            continue
        note = (t.get("note") or "").lower()

        # 1. hallucinated junk
        if ("reconciled: hallucinated" in proof
                or "reconciled: marketing" in proof
                or area in ("lab", "backup")
                or "drainage" in title.lower()
                or "board components" in title.lower()):
            req("/task", {"op": "set", "key": key, "status": "done",
                          "owner": "jenny",
                          "proof": "discarded: hallucinated by early review run"})
            done += 1
            continue

        # 2. Unknown-command failures → human attention
        if status == "failed" and ("Unknown command" in proof or "usage:" in proof):
            req("/task", {"op": "set", "key": key, "status": "done",
                          "owner": area,
                          "proof": "deferred_human: " + proof[:300]})
            human_title = ("\u2753 %s couldn't run: %s \u2014 needs input"
                           % (area, title[:35]))[:160]
            req("/task", {"op": "add", "area": "jenny",
                          "title": human_title, "owner": "rohit",
                          "status": "ready", "priority": "normal",
                          "note": "human-attention: %s task %s" % (area, key)})
            human += 1
            continue

    # 3. duplicate ready tasks -> keep one canonical per (area, title)
    ready = [(k, t) for k, t in board.items() if t.get("status") == "ready"]
    seen = {}
    for k, t in ready:
        canon = (t.get("area", "?"), t.get("title", ""))
        if canon in seen:
            req("/task", {"op": "set", "key": k, "status": "done",
                          "owner": t.get("area", "jenny"),
                          "proof": ("dedup: duplicate of " + seen[canon])[:200]})
            deduped += 1
        else:
            seen[canon] = k

    print("discarded=%d human_tasks=%d deduped=%d remaining_ready=%d"
          % (done, human, deduped,
             sum(1 for t in board.values() if t.get("status") == "ready")))

if __name__ == "__main__":
    main()