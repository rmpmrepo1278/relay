#!/usr/bin/env python3
"""LinkedIn guest-job discovery source for Hermes pipeline — TPM roles.

Primary real-world feed for Rohit's profile (Director/Sr Director Technical
Program Management, portfolio & delivery management). Uses LinkedIn's public
unauthenticated job-search endpoint (no cookies/keys).

Queries targeted to TPM / Program Management leadership, parses the returned
cards, normalizes, scores against the TPM-director profile, and emits the same
jobs_<date>.json contract the pipeline expects.

Usage:
    python3 linkedin_jobs.py [--queries "q1|q2"] [--dry-run] [--per-query N]

Programmatic use (imported by auto_pipeline.py):
    import linkedin_jobs as lj
    rec = lj.discover(per_query=5)   # returns {good_fit_count, jobs[]}
"""
import html as _html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import hashlib
from datetime import datetime, timezone, date

SHARED_DIR = os.environ.get(
    "SHARED_DATA_DIR",
    "/home/rohit/.hermes/collaborator-memory/data",
)
if os.path.isdir("/opt/data/collaborator-memory") and not os.path.isdir(SHARED_DIR):
    SHARED_DIR = "/opt/data/collaborator-memory/data"

GUEST_BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DEFAULT_QUERIES = [
    "Technical Program Manager",
    "Program Manager Director",
    "Technical Program Management Director",
    "Program Management Portfolio",
]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# --- TPM-director fit profile (matching discovery_source.py) ---
TITLE_REL_DIRECTOR = [
    "director", "sr director", "senior director", "vp", "head of",
    "senior program manager", "sr program manager", "staff program manager",
    "principal program manager", "program director", "engineering program manager",
]
TITLE_REL_MANAGER = [
    "program manager", "technical program manager", "project manager",
    "portfolio manager", "delivery manager", "pmo",
    "program lead", "delivery lead", "release manager",
]
INCLUDE_OR = [
    r"technical program manag", r"program manag", r"project manag",
    r"portfolio manag", r"delivery manag", r"tpms?",
    r"pmo", r"engineering program", r"program director",
    r"transformation", r"erp", r"platform program",
]
EXCLUDE_OR = [
    r"frontend", r"backend eng", r"full.?stack", r"devops", r"data engineer",
    r"machine learning engineer", r"ml engineer", r"qa engineer",
    r"software engineer", r"site reliability", r"sre", r"developer",
    r"ui\/ux", r"ux", r"graphic", r"content ?writer", r"recruiter",
    r"customer support", r"sales ", r"account executive", r"junior",
    r"intern", r"entry", r"data entry",
]
SENIOR_KW = {"director", "vp", "head", "sr", "senior", "staff", "principal", "lead", "executive", "chief", "manager"}


def _parse_cards(html_text):
    """Parse LinkedIn guest job-search result cards into raw job dicts."""
    jobs = []
    cards = re.findall(r'<li>(.*?)</li>', html_text, re.S)
    for c in cards:
        if "job-search-card" not in c:
            continue
        title = re.search(r'base-search-card__title"([^>]*)>(.*?)</h3>', c, re.S)
        company = re.search(r'base-search-card__subtitle"([^>]*)>(.*?)</h4>', c, re.S)
        location = re.search(r'job-search-card__location"([^>]*)>(.*?)</span>', c, re.S)
        link = re.search(r'<a[^>]*href="([^"]*)"[^>]*class="base-card__full-link', c)
        if not link:
            link = re.search(r'base-card__full-link[^>]*href="([^"]*)"', c)
        date_m = re.search(r'datetime="([^"]*)"', c)
        entity = re.search(r'data-entity-urn="[^"]*:(\d+)"', c)

        def _strip(s):
            return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

        j = {
            "title": _strip(title.group(2)) if title else "",
            "company_name": _strip(company.group(2)) if company else "",
            "candidate_required_location": _strip(location.group(2)) if location else "Remote",
            "url": (link.group(1).replace("&amp;", "&") if link else ""),
            "category": "Technical Program Management",
            "tags": [],
            "description": "",
            "id": entity.group(1) if entity else f"li-{abs(hash(_strip(title.group(2)) if title else ''))}",
            "job_type": "full_time",
            "publication_date": date_m.group(1) if date_m else "",
        }
        if j["title"]:
            jobs.append(j)
    return jobs


def _fetch(queries=None, per_query=5, start=0):
    "".join  # noqa
    jobs = []
    queries = queries or DEFAULT_QUERIES
    base_url = urllib.parse.urlparse(GUEST_BASE)
    for q in queries:
        params = urllib.parse.urlencode({
            "keywords": q,
            "location": "",
            "geoId": "",
            "f_TPR": "",  # any time
            "start": start,
        })
        url = f"{GUEST_BASE}?{params}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read().decode("utf-8", "ignore")
            got = _parse_cards(body)
            jobs.extend(got[:per_query])
            print(f"[li] {q!r}: {len(got)} cards")
        except Exception as e:
            print(f"[li][warn] query {q!r} failed: {e}")
        time.sleep(2)  # polite rate limit between queries
    return jobs


def _score(job):
    title = job.get("title", "")
    desc = job.get("description", "")[:1500]
    text = " ".join([title, job.get("category", ""), " ".join(job.get("tags", []) or []), desc]).lower()

    if any(e in text for e in EXCLUDE_OR):
        return 0
    low_title = title.lower()

    score = 0
    if any(d in low_title for d in TITLE_REL_DIRECTOR):
        score += 38
    elif any(m in low_title for m in TITLE_REL_MANAGER):
        score += 30
    else:
        score += 8
    dom_hits = sum(1 for k in INCLUDE_OR if k in text)
    score += min(dom_hits * 4, 24)
    if any(s in low_title for s in SENIOR_KW):
        score += 10
    if job.get("job_type") == "full_time":
        score += 5
    return min(100, score)


def _norm_job(job, source="linkedin"):
    url = (job.get("url", "") or "").split("?", 1)[0].split("#", 1)[0]
    j = {
        "title": job.get("title", ""),
        "company": job.get("company_name", ""),
        "location": job.get("candidate_required_location", "Remote") or "Remote",
        "url": url,
        "raw": f"{source}:{job.get('id')}",
        "category": job.get("category", ""),
        "tags": job.get("tags", []) or [],
        "description": job.get("description", ""),
        "published": job.get("publication_date", ""),
    }
    key = f"{re.sub(r'[^a-z0-9]+', '', j['title'].lower())}|{re.sub(r'[^a-z0-9]+', '', j['company'].lower())}|{url}"
    j["hash"] = hashlib.sha256(key.encode()).hexdigest()[:16]
    j["score"] = _score(j)
    j["source"] = source
    j["fetched"] = datetime.now(timezone.utc).isoformat()
    return j


def discover(queries=None, per_query=5, threshold=55, write=False):
    rows = _fetch(queries=queries, per_query=per_query)
    seen = set()
    hit_list = []
    for row in rows:
        j = _norm_job(row)
        if j["hash"] in seen:
            continue
        seen.add(j["hash"])
        if j["score"] >= threshold:
            hit_list.append(j)
    hit_list.sort(key=lambda j: -j["score"])
    today = date.today().isoformat()
    record = {
        "generated_by": "linkedin_jobs.py",
        "agent": "hermes",
        "source": "linkedin-guest",
        "profile": "Director/Sr Director Technical Program Management (TPM, portfolio, delivery)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "good_fit_count": len(hit_list),
        "jobs": hit_list,
    }
    if write:
        os.makedirs(SHARED_DIR, exist_ok=True)
        with open(os.path.join(SHARED_DIR, f"jobs_{today}.json"), "w") as fh:
            json.dump(record, fh, indent=2)
    return record


def main():
    dry = "--dry-run" in sys.argv
    queries = None
    if "--queries" in sys.argv:
        try:
            queries = [q.strip() for q in sys.argv[sys.argv.index("--queries") + 1].split("|")]
        except (ValueError, IndexError):
            pass
    per_query = 5
    if "--per-query" in sys.argv:
        try:
            per_query = int(sys.argv[sys.argv.index("--per-query") + 1])
        except (ValueError, IndexError):
            pass
    print(f"[li] queries={queries or DEFAULT_QUERIES} per_query={per_query}")
    record = discover(queries=queries, per_query=per_query, write=not dry)
    print(f"[li] candidates={record['candidate_count']} good-fit(>=55)={record['good_fit_count']}")
    if dry:
        for j in record["jobs"][:15]:
            print(f"  • {j['score']:>2} {j['company']} | {j['title']} — {j['url']}")
    else:
        out = os.path.join(SHARED_DIR, f"jobs_{date.today().isoformat()}.json")
        print(f"[li] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
