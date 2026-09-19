#!/usr/bin/env python3
"""Full autonomous pipeline: batch (chunked) -> fill passes -> assemble PDF.

Run as a systemd user service so the entire book translation completes even if
the originating session ends. Resume-safe (per-page JSON cache).

Farm etiquette (learned the hard way): sustained single-page 45s-timeout calls
cause per-request stalls + empty-content, compounding through retries. Instead:
  - CHUNK=3 pages per LLM call  -> 3x fewer requests.
  - haiku-first then sonnet fallback (fleet-workhorse priority).
  - empty content -> immediate failover, no wasted wait.
  - cool-down after every call + a longer recovery pause every K calls.
Phases:
  1. BATCH   : translate every not-yet-successful page, chunked (70s call cap).
  2. FILL    : repeated passes over still-failing pages, chunked, gentler.
  3. ASSEMBLE: build the English PDF + txt from the finished cache.
Status written to work/baidehisa_status.json.
"""
import importlib.util, json, os, re, subprocess, sys, time

ROOT = os.path.expanduser("~/.hermes/scripts")
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "baidehisa_translate.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

WORK = bt.WORK
STATUS = os.path.join(WORK, "baidehisa_status.json")
LOG = os.path.join(WORK, "baidehisa_supervisor.log")

CHUNK = 3
CHUNK_INSTR = (
    "You translate Odia/Hindi devotional poetry (Upendra Bhanja, Baidehisha Bilasa) into "
    "simple, readable, accurate English prose. Translate the meaning faithfully; keep names "
    "transliterated; do NOT add commentary. Return ONLY the translations, each prefixed with "
    "exactly the same marker you received, on its own line.\n\n"
)

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

def chunks_of(idxs, n):
    for i in range(0, len(idxs), n):
        yield idxs[i:i + n]

def build_prompt(pages, chunk):
    parts = []
    for i in chunk:
        text = "\n".join(bt.clean(pages[i]))
        if len(text) > 7000:
            text = text[:7000] + "\n[...]"
        parts.append(f"---PAGE {i}---\n{text}")
    return CHUNK_INSTR + "\n\n".join(parts)

_MARK = re.compile(r"---PAGE\s+(\d+)---")

def run_chunk_pass(pages, idxs, label, timeout, cooldown, every_k):
    c = cache()
    todo = [i for i in idxs if str(i) not in c or not c[str(i)].get("ok")]
    ok_add, fail = 0, []
    calls = 0
    bt.TIMEOUT = timeout
    for chunk in chunks_of(todo, CHUNK):
        calls += 1
        c = cache()
        prompt = build_prompt(pages, chunk)
        try:
            out = bt.translate_raw(prompt)
            got = {}
            for m in _MARK.finditer(out):
                try:
                    got[int(m.group(1))] = out[m.end():next_mark_end(out, m.end())].strip()
                except Exception:
                    continue
            # salvage whichever pages came back; missing ones -> fail (refiled later)
            for i in chunk:
                k = str(i)
                en = got.get(i)
                if en:
                    c[k] = {"ok": True, "page": i, "printed": bt.page_header(pages[i]), "en": en}
                    ok_add += 1
                else:
                    c[k] = {"ok": False, "page": i, "err": "missing in chunk"}
                    fail.append(i)
            save_cache(c)
            log(f"{label} chunk {len(chunk)}p -> {len(got)} ok_added={ok_add}")
        except Exception as e:
            for i in chunk:
                k = str(i)
                c[k] = {"ok": False, "page": i, "err": str(e)[:160]}
                fail.append(i)
            save_cache(c)
            log(f"{label} chunk FAIL p{chunk[0]}-{chunk[-1]}: {str(e)[:70]}")
            time.sleep(8)
        time.sleep(cooldown)
        if calls % every_k == 0:
            time.sleep(20)
        if calls % 4 == 0:
            status(phase=label, done=ok_add + len(idxs) - len(todo), failed=len(fail))
            log(f"{label} progress calls={calls} ok_added={ok_add} fails={len(fail)}")
    return ok_add, [i for i in fail if str(i) not in cache() or not cache()[str(i)].get("ok")]

def next_mark_end(out, pos):
    m = _MARK.search(out, pos)
    return m.start() if m else len(out)

def main():
    os.makedirs(WORK, exist_ok=True)
    log("supervisor start (chunked)")
    pages = bt.split_pages(open(bt.SRC, encoding="utf-8", errors="replace").read())
    idxs = [i for i in range(len(pages)) if len(bt.clean(pages[i])) >= 8]
    target = len(idxs)
    c = cache()
    todo = [i for i in idxs if str(i) not in c or not c[str(i)].get("ok")]
    log(f"target={target} cached_ok={sum(1 for v in c.values() if v.get('ok'))} todo={len(todo)}")

    added, fail = run_chunk_pass(pages, todo, "batch", 70, 2.0, 4)

    still = fail
    for rnd in range(1, 6):
        if not still:
            break
        log(f"fill round {rnd}/5 on {len(still)} pages")
        time.sleep(6)
        a, f = run_chunk_pass(pages, still, f"fill{rnd}", 90, 3.0, 3)
        log(f"fill round {rnd} added={a} still_failing={len(f)}")
        if not a and len(f) == len(still):
            break
        still = f

    c = cache()
    final_ok = sum(1 for v in c.values() if v.get("ok"))
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