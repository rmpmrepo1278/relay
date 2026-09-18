#!/usr/bin/env python3
"""Assemble the English page-translations of Baidehisha-Bilasa into one PDF."""
import os, json, html, re, subprocess, sys

ROOT = os.path.expanduser("~/.hermes/books")
WORK = os.path.join(ROOT, "work")
CACHE = os.path.join(WORK, "baidehisa_en_cache.json")
OUT_PDF = os.path.join(ROOT, "baidehisha-bilasa-english.pdf")
OUT_TXT = os.path.join(ROOT, "baidehisha-bilasa-english.txt")

cache = json.load(open(CACHE))
recs = []
for k in sorted(cache, key=int):
    v = cache[k]
    if v.get("ok"):
        recs.append(v)

def fmt(text):
    out = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            out.append("&nbsp;")
            continue
        out.append(html.escape(line))
    return "<br>\n".join(out)

def para(text):
    # group consecutive non-empty lines into paragraphs, blank line separates
    blocks = []
    cur = []
    for line in text.split("\n"):
        if line.strip():
            cur.append(line.strip())
        elif cur:
            blocks.append(" ".join(cur)); cur = []
    if cur:
        blocks.append(" ".join(cur))
    return "\n".join(f"<p>{html.escape(b)}</p>" for b in blocks)

parts = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Baidehisha-Bilasa — English Translation</title>
<style>
@page {{ size: A4; margin: 1.9cm 2.1cm; }}
body {{ font-family: "Georgia","DejaVu Serif","Noto Serif",serif; font-size: 11pt; line-height: 1.5; color: #1a1a1a; }}
h1 {{ font-size: 21pt; margin: 0 0 2pt 0; }}
.sub {{ color:#444; font-size: 10.5pt; margin-bottom: 2pt; }}
.small {{ color:#666; font-size: 9pt; }}
.cover {{ text-align:center; margin-top: 6cm; }}
.pages {{
  page-break-before: always;
}}
.pgheader {{ font-size: 9.5pt; color: #666; border-bottom: 0.5pt solid #bbb; margin-bottom: 8pt; }}
.verse {{ font-family:"Georgia",serif; font-style: normal; margin: 6pt 0 6pt 0; }}
p {{ margin: 4pt 0; text-align: justify; }}
</style></head><body>"""]

parts.append(f"""<div class="cover">
<h1>BAIDEHISHA-BILASA</h1>
<div class="sub">The Pleasure of Baidehisha (Sita) &mdash; by Kabi Samrat Upendra Bhanja</div>
<div class="sub">English translation, page by page, from the 1980 bilingual (Odia&ndash;Hindi, Devanagari script) edition,<br>Bhuvan Vani Trust, Lucknow.</div>
<div class="small">Vol. 1 reference: Baidehisha-Bilasa, bhaga 1, 1949 (Odia script) &mdash; retained as the primary text.<br>
Translation generated page-by-page via a local LLM (gemini-2.5-flash through the hop gateway);<br>
OCR/scan noise notwithstanding, numbered verses, saralarth (simple meaning) prose, and word glosses are preserved.</div>
<div class="small">Pages translated: {len(recs)} &nbsp;&middot;&nbsp; generated {__import__('datetime').date.today().isoformat()}</div>
</div>""")

for i, r in enumerate(recs):
    pg = r.get("printed")
    head = f"p&#8202;{r['page']}" + (f" &nbsp;&middot;&nbsp; folio {pg}" if pg else "")
    body = para(r["en"])
    parts.append(f"""<section class="pages">
<div class="pgheader">PAGE {head}</div>
{body}
</section>""")

parts.append("</body></html>")

html_doc = "".join(parts)
HTML = os.path.join(WORK, "baidehisha_en.html")
open(HTML, "w", encoding="utf-8").write(html_doc)

res = subprocess.run(["weasyprint", HTML, OUT_PDF], capture_output=True, text=True, timeout=300)
if res.returncode != 0:
    print("WEASYPRINT ERR:", res.stderr[:800]); sys.exit(1)

with open(OUT_TXT, "w", encoding="utf-8") as f:
    for r in recs:
        f.write(f"\n===== PAGE {r['page']}" + (f" (folio {r['printed']})" if r.get("printed") else "") + " =====\n\n")
        f.write(r["en"] + "\n")

size = os.path.getsize(OUT_PDF)
pgs = len(re.findall(rb"/Type\s*/Page[^s]", open(OUT_PDF, "rb").read())) if False else "?"
print(f"OK: {OUT_PDF} ({size:,} bytes) from {len(recs)} pages; txt at {OUT_TXT}")