#!/usr/bin/env python3
"""Full autonomous pipeline: translate every page -> fill stragglers -> assemble PDF.

Run as a systemd user service so the ENTIRE book translation completes even if
the originating session ends. Resume-safe per-page JSON cache.

Farm reality (measured): hop lanes succeed fast (~1s) but return empty ~50-70%
of the time at random, and every big prompt empties. Design therefore:
  - ONE page per request (small prompts only).
  - Infinite retries per page (each attempt is cheap); a page parks after 15
    attempts so a genuinely dead lane can't wedge the loop, and is retried on
    the next global pass.
  - Lane rotation: combo/pi-free-fallback -> haiku-4.5 -> claude-sonnet.
  - Pacing: 0.4s after success, 2s after failure, 15s pause every 25 calls.
Phases: BATCH (unbounded passes) -> FILL (stragglers only) -> ASSEMBLE.
"""
import importlib.util, json, os, subprocess, sys, time

ROOT = os.path.expanduser("~/.hermes/scripts")
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "baidehisa_translate.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

WORK = bt.WORK
STATUS = os.path.join(WORK, "baidehisa_status.json")
LOG = os.path.join(WORK, "baidehisa_supervisor.log")

bt.MODELS = ["combo/pi-free-fallback", "haiku-4.5", "claude-sonnet-4-20250514"]
bt.TIMEOUT = 60
MAX_ATTEMPTS_PER_PAGE = 15


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


def clean(pages, i):
    return "\n".join(bt.clean(pages[i]))[:5000]


def pass_todo(pages, idxs, label):
    ok_add, fail, calls = 0, [], 0
    for i in idxs:
        k = str(i)
        c = cache()
        if k in c and c[k].get("ok"):
            continue
        n = (c.get(k) or {}).get("attempts", 0)
        if n >= MAX_ATTEMPTS_PER_PAGE:
            fail.append(i)
            continue
        calls += 1
        try:
            en = bt.translate(clean(pages, i))
            c[k] = {"ok": True, "page": i, "printed": bt.page_header(pages[i]),
                    "en": en, "attempts": n}
            save_cache(c)
            ok_add += 1
            time.sleep(0.4)
            log(f"{label} ok p{i} (attempt {n + 1})")
        except Exception as e:
            c[k] = {"ok": False, "page": i, "err": str(e)[:120], "attempts": n + 1}
            save_cache(c)
            fail.append(i)
            log(f"{label} FAIL p{i} ({type(e).__name__}): {str(e)[:60]}")
            time.sleep(2)
        status(phase=label,
               done=sum(1 for v in cache().values() if v.get("ok")),
               failed=sum(1 for v in cache().values() if not v.get("ok")))
        if calls % 25 == 0:
            log(f"{label} pacing pause")
            time.sleep(15)
    ok_now = sum(1 for v in cache().values() if v.get("ok"))
    log(f"{label} pass done ok_added={ok_add} ok_total={ok_now} fails={len(fail)}")
    return ok_add, fail


def unfinished(idxs):
    c = cache()
    return [i for i in idxs if str(i) not in c or not c[str(i)].get("ok")]


def main():
    os.makedirs(WORK, exist_ok=True)
    log("supervisor start (single-page, infinite retry)")
    pages = bt.split_pages(open(bt.SRC, encoding="utf-8", errors="replace").read())
    idxs = [i for i in range(len(pages)) if len(bt.clean(pages[i])) >= 8]
    target = len(idxs)
    log(f"target={target} ok={sum(1 for v in cache().values() if v.get('ok'))} "
        f"todo={len(unfinished(idxs))}")

    rounds = 0
    while rounds < 60:
        u = unfinished(idxs)
        if not u:
            log("all pages ok")
            break
        ok_add, fail = pass_todo(pages, u, "pass")
        rounds += 1
        if ok_add == 0 and not fail:
            log("no unfinished pages but no fails -> stop")
            break
        # stop looping only when a pass produced zero new successes
        if ok_add == 0:
            log(f"zero-progress pass {rounds}; parked attempts will reset in fill")
            break
    log("batch passes complete")

    still = unfinished(idxs)
    if still:
        reset = {k: dict(v, attempts=0) for k, v in cache().items()}
        save_cache(reset)
        for rnd in range(1, 4):
            s = unfinished(idxs)
            if not s:
                break
            time.sleep(5)
            a, f = pass_todo(pages, s, f"fill{rnd}")
            if not a:
                break
    still = unfinished(idxs)

    c = cache()
    final_ok = len(idxs) - len(still)
    log(f"phases done: ok={final_ok}/{target}")
    status(phase="assemble", ok=final_ok, target=target)
    res = subprocess.run([sys.executable, os.path.join(ROOT, "baidehisa_assemble.py")],
                         capture_output=True, text=True, timeout=600)
    log("assemble rc=%s out=%s" % (res.returncode, res.stdout.strip()[-200:]))
    if res.returncode != 0:
        log("assemble err: %s" % res.stderr.strip()[-400:])
    status(phase="done", ok=final_ok, target=target, assemble_rc=res.returncode,
           missing=still)
    log(f"SUPERVISOR DONE ok={final_ok}/{target}")
    sys.exit(0 if final_ok == target else 3)


if __name__ == "__main__":
    main()