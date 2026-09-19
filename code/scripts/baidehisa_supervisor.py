#!/usr/bin/env python3
"""Full autonomous pipeline: batch translate -> fill passes -> assemble PDF.

Run as a systemd user service so the entire book translation completes even if
the originating session ends. Resume-safe (per-page JSON cache).
Phases:
  1. BATCH   : translate every not-yet-successful page (45s call cap).
  2. FILL    : repeated passes over still-failing pages (90s cap, backoff).
  3. ASSEMBLE: build the English PDF + txt from the finished cache.
Status written to work/baidehisa_status.json every phase.
"""
import importlib.util, json, os, subprocess, sys, time

ROOT = os.path.expanduser("~/.hermes/scripts")
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "baidehisa_translate.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

WORK = bt.WORK
STATUS = os.path.join(WORK, "baidehisa_status.json")
LOG = os.path.join(WORK, "baidehisa_supervisor.log")

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def status(**kw):
    base = {"ts": time.time()}
    base.update(kw)
    json.dump(base, open(STATUS, "w"))

def cache():
    if os.path.exists(bt.CACHE):
        return {str(k): v for k, v in json.load(open(bt.CACHE)).items()}
    return {}

def save_cache(c):
    json.dump(c, open(bt.CACHE, "w"))

def main():
    os.makedirs(WORK, exist_ok=True)
    log("supervisor start")
    pages = bt.split_pages(open(bt.SRC, encoding="utf-8", errors="replace").read())
    idxs = [i for i in range(len(pages)) if len(bt.clean(pages[i])) >= 8]
    target = len(idxs)
    c = cache()
    todo = [i for i in idxs if str(i) not in c or not c[str(i)].get("ok")]
    log(f"target={target} cached_ok={sum(1 for v in c.values() if v.get('ok'))} todo={len(todo)}")

    attempts = {}

    def translate_page(i, cap):
        text = "\n".join(bt.clean(pages[i]))
        if len(text) > 7000:
            text = text[:7000] + "\n[...]"
        return bt.translate(text)

    def run_pass(page_list, cap, label):
        ok_add, fail = 0, []
        for n, i in enumerate(page_list, 1):
            k = str(i)
            c = cache()
            if k in c and c[k].get("ok"):
                continue
            attempts[k] = attempts.get(k, 0) + 1
            try:
                en = translate_page(i, cap)
                c[k] = {"ok": True, "page": i, "printed": bt.page_header(pages[i]), "en": en}
                save_cache(c)
                ok_add += 1
                log(f"{label} ok p{i} ({ok_add}/{len(page_list)})")
            except Exception as e:
                c[k] = {"ok": False, "page": i, "err": str(e)[:200]}
                save_cache(c)
                fail.append(i)
                log(f"{label} FAIL p{i}: {str(e)[:80]}")
            if n % 5 == 0:
                status(phase=label, done=ok_add + len(idxs) - len(page_list), failed=len(fail))
                log(f"{label} progress {n}/{len(page_list)} ok_added={ok_add} fails={len(fail)}")
            time.sleep(0.4)
        return ok_add, fail

    # Phase 1: batch at 45s cap
    bt.TIMEOUT = 45
    added, fails = run_pass(todo, 45, "batch")

    # Phase 2: fill — repeat failing pages until stable or attempts exhausted
    still = fails
    for round in range(1, 6):
        if not still:
            break
        bt.TIMEOUT = 90
        log(f"fill round {round}/5 on {len(still)} pages")
        time.sleep(5)
        added2, still2 = run_pass(still, 90, f"fill{round}")
        log(f"fill round {round} added={added2} still_failing={len(still2)}")
        if not added2:
            break
        still = still2

    c = cache()
    final_ok = sum(1 for v in c.values() if v.get("ok"))
    # assemble if at least one page (prefer full target)
    log(f"phases done: ok={final_ok}/{target} failing={target - final_ok}")
    status(phase="assemble", ok=final_ok, target=target)
    res = subprocess.run([sys.executable, os.path.join(ROOT, "baidehisa_assemble.py")],
                         capture_output=True, text=True, timeout=600)
    log("assemble rc=%s out=%s" % (res.returncode, res.stdout.strip()[-200:]))
    if res.returncode != 0:
        log("assemble err: %s" % res.stderr.strip()[-400:])
    status(phase="done", ok=final_ok, target=target, assemble_rc=res.returncode)
    log(f"SUPERVISOR DONE ok={final_ok}/{target}")
    sys.exit(0 if final_ok == target else (2 if final_ok == 0 else 3))

if __name__ == "__main__":
    main()