#!/usr/bin/env python3
"""Translate Baidehisha-Bilasa (1980 Devanagari bilingual edition) page-by-page to English.

Fetches per-page translation through the local hop gateway (text models) with a
resume-safe JSON cache, so interrupted runs continue where they left off.
"""
import os, re, sys, json, time, html, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

ROOT = os.path.expanduser("~/.hermes/books")
SRC = os.path.join(ROOT, "baidehisha-bilasa-1980-bilingual.txt")
WORK = os.path.join(ROOT, "work")
CACHE = os.path.join(WORK, "baidehisa_en_cache.json")
LOG = os.path.join(WORK, "baidehisa_progress.json")
HOP = os.environ.get("BAIDEHI_HOP", "http://127.0.0.1:8083/v1/chat/completions")
MODEL = os.environ.get("BAIDEHI_MODEL", "gemini/gemini-2.5-flash")
WORKERS = int(os.environ.get("BAIDEHI_WORKERS", "4"))
ONLY = [int(x) for x in os.environ.get("BAIDEHI_ONLY", "").split(",") if x.strip()]

WM = "Agamnigam Digital Presevation Foundation"

INSTR = (
    "You are translating the 1980 Devanagari-script bilingual edition of the Odia\n"
    "classic Baiddehisha-Bilasa (Bidehisha-Bilasa) by the poet Upendra Bhanja.\n"
    "Below is one BOOK PAGE from that edition. It contains some of: original Odia\n"
    "verse lines transliterated into Devanagari; Hindi 'saralarth' prose\n"
    "explanations of each stanza; lists of word-meaning glosses; running page\n"
    "headers. Translate EVERYTHING into clear, faithful, fluent English.\n"
    "Formatting rules:\n"
    "- Keep each original verse line as its own line (do not merge).\n"
    "- Translate the Hindi prose explanation as prose.\n"
    "- Word glosses: keep each as '- <Odia word>: <English meaning>'.\n"
    "- Keep verse ordinal numbers like '33.' at the end of the verse line.\n"
    "- Drop literals that are clearly OCR noise (stray glyphs, page furniture).\n"
    "- Output ONLY the English translation, no preamble.\n\n"
)

def split_pages(raw):
    return raw.split("CC-0. " + WM)

def clean(pg):
    out = []
    for l in pg.split("\n"):
        l = l.strip()
        if not l or len(l) < 3:
            continue
        if WM in l or "CC-0" in l:
            continue
        if re.fullmatch(r"[\W_\-|/\\=~]+", l):
            continue
        if re.fullmatch(r"[\u0900-\u097F]{1,4}", l):
            continue
        out.append(l)
    return out

def page_header(pg):
    m = re.search(r"^([०-९\d]{1,4})\s+ओड़िआ", pg, re.M)
    return m.group(1) if m else None

def translate(text, retries=3):
    body = INSTR + text
    for attempt in range(retries):
        payload = {"model": MODEL, "messages": [{"role": "user", "content": body}],
                   "max_tokens": 2000, "temperature": 0.2}
        req = urllib.request.Request(HOP, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            out = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not out.strip():
                raise RuntimeError("empty content")
            return out.strip()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")

def main():
    os.makedirs(WORK, exist_ok=True)
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE))
    pages = split_pages(open(SRC, encoding="utf-8", errors="replace").read())
    idxs = [i for i in range(len(pages)) if len(clean(pages[i])) >= 8]
    if ONLY:
        idxs = [i for i in idxs if i in ONLY]
    todo = [i for i in idxs if i not in cache or not cache[i].get("ok")]
    print(f"pages total={len(pages)} target={len(idxs)} done={len(cache)} todo={len(todo)}", flush=True)

    lock = threading.Lock()
    start = time.time()
    prog = {"done": 0}
    def work(i):
        pg = pages[i]
        text = "\n".join(clean(pg))
        if len(text) > 9000:
            text = text[:9000] + "\n[...]"
        try:
            en = translate(text)
            rec = {"ok": True, "page": i, "printed": page_header(pg), "en": en,
                   "secs": round(time.time() - start, 1)}
        except Exception as e:
            rec = {"ok": False, "page": i, "err": str(e)[:300],
                   "secs": round(time.time() - start, 1)}
        with lock:
            cache[str(i)] = rec
            json.dump(cache, open(CACHE, "w"))
            progressive = {"done": sum(1 for v in cache.values() if v.get("ok")),
                           "failed": sum(1 for v in cache.values() if not v.get("ok")),
                           "target": len(idxs), "model": MODEL,
                           "elapsed_s": round(time.time() - start, 1)}
            json.dump(progressive, open(LOG, "w"))
            prog["done"] += 1
            if prog["done"] % 10 == 0:
                print(f"  {prog['done']}/{len(todo)} @ {progressive['elapsed_s']}s", flush=True)
        return rec

    def go(idx):
        return work(idx)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(go, i): i for i in todo}
        recs, fails = [], 0
        for f in as_completed(futs):
            r = f.result()
            recs.append(r)
            if not r["ok"]:
                fails += 1
    ok = sum(1 for r in recs if r["ok"])
    print(f"DONE ok={ok} failed={fails} elapsed={int(time.time()-start)}s", flush=True)

if __name__ == "__main__":
    main()