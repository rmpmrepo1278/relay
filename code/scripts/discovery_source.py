#!/usr/bin/env python3
"""Discovery source for Hermes job pipeline — Technical Program Management roles.

Fit profile built from Rohit's current CV (cv.md):
Director of Technical Program Management — Enterprise Transformation & FinTech.
20+ yrs. Sweet-spot titles: Director/Sr Director Technical Program Management,
Director of Program/Portfolio/Delivery Management, Senior Program Manager,
TPM leadership, Program Management (Director/VP/Head).

Sources: Remotive + WeWorkRemotely RSS (both free, no key).

Usage:
    python3 discovery_source.py [--max-jobs N] [--dry-run]

Programmatic use (imported by auto_pipeline.py):
    import discovery_source as ds
    rec = ds.discover(max_jobs=100)   # returns {good_fit_count, jobs[]}
"""
import json
import os
import re
import sys
import urllib.request
import hashlib
import calendar
from datetime import datetime, timezone, date

REMOTIVE_API = "https://remotive.com/api/remote-jobs?limit=100"
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

SHARED_DIR = os.environ.get(
    "SHARED_DATA_DIR",
    "/home/rohit/.hermes/collaborator-memory/data",
)
if os.path.isdir("/opt/data/collaborator-memory") and not os.path.isdir(SHARED_DIR):
    SHARED_DIR = "/opt/data/collaborator-memory/data"

# ---------------------------------------------------------------------------
# Fit profile — Director / Sr Director Technical Program Management
# ---------------------------------------------------------------------------
# Roles that are on-target for a 20-yr TPM/Portfolio/Delivery leader
TITLE_REL_DIRECTOR = [
    "director", "sr director", "senior director", "vp", "head of",
    "senior program manager", "sr program manager", "staff program manager",
    "principal program manager",
    "program director", "engineering program manager",
]
TITLE_REL_MANAGER = [
    "program manager", "technical program manager", "project manager",
    "portfolio manager", "delivery manager", "pmo",
    "program lead", "delivery lead", "release manager",
]
# Heavy-include keywords (any one strongly suggests the domain)
INCLUDE_OR = [
    r"technical program manag", r"program manag", r"project manag",
    r"portfolio manag", r"delivery manag", r"tpms?",
    r"pmo", r"engineering program", r"program director",
    r"transformation", r"erp", r"platform program", r"digital program",
]
# Hard exclusions — not Rohit's target
EXCLUDE_OR = [
    r"frontend", r"backend eng", r"full.?stack", r"devops", r"data engineer",
    r"machine learning engineer", r"ml engineer", r"qa engineer",
    r"software engineer", r"site reliability", r"sre", r"developer",
    r"ui\/ux", r"ux", r"graphic", r"content ?writer", r"recruiter",
    r"customer support", r"sales ", r"account executive", r"junior",
    r"intern", r"entry", r"data entry",
]
# Seniority words that add lift
SENIOR_KW = {"director", "vp", "head", "sr", "senior", "staff", "principal", "lead", "executive", "chief", "manager"}


def _fetch():
    jobs = []
    try:
        req = urllib.request.Request(REMOTIVE_API, headers={"User-Agent": "hermes-job-discovery/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            jobs.extend(json.loads(resp.read().decode()).get("jobs", []))
    except Exception as e:
        print(f"[warn] remotive fetch failed: {e}")

    for feed in WWR_FEEDS:
        try:
            req = urllib.request.Request(feed, headers={"User-Agent": "hermes-job-discovery/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml = resp.read().decode("utf-8", "ignore")
            items = re.findall(r"<item>(.*?)</item>", xml, re.S)
            for it in items:
                title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
                desc = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", it, re.S)
                link = re.search(r"<link>(.*?)</link>", it, re.S)
                jobs.append({
                    "title": title.group(1).strip() if title else "",
                    "company_name": "",
                    "candidate_required_location": "Remote",
                    "url": link.group(1).strip() if link else "",
                    "category": "Technical Program Management",
                    "tags": [],
                    "description": (desc.group(1).strip() if desc else "")[:1500],
                    "id": f"wwr-{abs(hash(it))}",
                    "job_type": "full_time",
                    "publication_date": "",
                })
        except Exception as e:
            print(f"[warn] weworkremotely fetch failed for {feed}: {e}")
    return jobs


def _score(job):
    title = job.get("title", "")
    desc = job.get("description", "")[:1500]
    text = " ".join([title, job.get("category", ""), " ".join(job.get("tags", []) or []), desc]).lower()

    # Hard exclusions
    if any(e in text for e in EXCLUDE_OR):
        return 0
    # Roles that mention engineering-IC stuff but ALSO PM — only count if title is PM
    low_title = title.lower()

    score = 0
    # Director/leadership-level titles are premium matches for a TPM director
    if any(d in low_title for d in TITLE_REL_DIRECTOR):
        score += 38
    elif any(m in low_title for m in TITLE_REL_MANAGER):
        score += 30
    else:
        # No manager/director in title — weak unless domain keywords dominate
        score += 8
    # Domain keywords in body
    dom_hits = sum(1 for k in INCLUDE_OR if k in text)
    score += min(dom_hits * 4, 24)
    # Seniority lift
    if any(s in low_title for s in SENIOR_KW):
        score += 10
    # Remote / FT discount (soft)
    if job.get("job_type") == "full_time":
        score += 5
    return min(100, score)


def _norm_job(job, source="remotive"):
    url = job.get("url", "")
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


def discover(max_jobs=100, threshold=55, write=False):
    """Fetch + filter good-fit jobs. If write, persist jobs_<date>.json."""
    rows = _fetch()[:max_jobs]
    hit_list = []
    for row in rows:
        j = _norm_job(row)
        if j["score"] >= threshold:
            hit_list.append(j)
    hit_list.sort(key=lambda j: -j["score"])
    today = date.today().isoformat()
    record = {
        "generated_by": "discovery_source.py",
        "agent": "hermes",
        "source": "remotive+weworkremotely",
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
    max_jobs = 100
    if "--max-jobs" in sys.argv:
        try:
            max_jobs = int(sys.argv[sys.argv.index("--max-jobs") + 1])
        except (ValueError, IndexError):
            pass
    print(f"[discover] fetching {REMOTIVE_API} + {len(WWR_FEEDS)} RSS feeds")
    record = discover(max_jobs=max_jobs, write=not dry)
    print(f"[discover] candidates={record['candidate_count']} good-fit(>=55)={record['good_fit_count']}")
    if dry:
        print(json.dumps({"good_fit_count": record["good_fit_count"]}, indent=2))
        for j in record["jobs"][:12]:
            print(f"  • {j['score']:>2} {j['company']} | {j['title']} — {j['url']}")
    else:
        out = os.path.join(SHARED_DIR, f"jobs_{date.today().isoformat()}.json")
        print(f"[discover] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())