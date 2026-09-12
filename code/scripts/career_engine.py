#!/usr/bin/env python3
"""
career_engine.py — Consolidated career-ops engine.

Combines: career_autonomous.py + find_fresh_jobs.py

Single autonomous engine for all career operations:
1. Job search (API scan + LinkedIn via SearXNG)
2. Auto-evaluate high-match jobs
3. Generate materials for 5/5 matches
4. Follow-up on stale applications
5. Pipeline status tracking
6. Telegram briefings

Usage:
    python3 career_engine.py              # Full autonomous cycle
    python3 career_engine.py --search     # Job search only
    python3 career_engine.py --evaluate   # Evaluate pending pipeline
    python3 career_engine.py --followup   # Follow-up on stale apps
    python3 career_engine.py --briefing   # Send daily briefing
    python3 career_engine.py --status     # Show pipeline status
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

# ─── Paths ────────────────────────────────────────────────────────────

CAREER_OPS_DIR = Path("/home/rohit/projects/career-ops")
HERMES_HOME = Path.home() / ".hermes"
STATE_FILE = HERMES_HOME / "state" / "career_engine.json"
LOG_FILE = HERMES_HOME / "logs" / "career_engine.log"
CAREER_DB = CAREER_OPS_DIR / "data" / "applications.db"
MIN_SCORE = 3.0
OUTPUT_FILE = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "data" / "career_briefing.json"
PIPELINE_FILE = CAREER_OPS_DIR / "data" / "pipeline.md"
SCAN_HISTORY_FILE = CAREER_OPS_DIR / "data" / "scan-history.tsv"
APPLICATIONS_FILE = CAREER_OPS_DIR / "data" / "applications.md"

SEARXNG_URL = "http://127.0.0.1:8118"

# Ensure directories exist
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# ─── Title scoring ────────────────────────────────────────────────────

SENIORITY_KW = [
    "director", "head of", "vp ", "vice president", "chief of staff",
    "senior director", "sr. director", "sr director"
]

DOMAIN_KW = [
    "program management", "technical program", "program manager",
    "transformation", "enterprise delivery", "strategic program",
    "strategic initiative", "delivery director", "delivery lead",
    "portfolio", "pmo", "operating model", "product delivery",
    "engineering operations", "product operations"
]

NEGATIVE_KW = [
    "account", "sales", "revenue", "recruit", "hr ", "human resources",
    "finance", "compensation", "benefits", "communications", "event",
    "support", "security", "privacy", "compliance", "industry solution",
    "customer success", "field", "expansion", "alliance", "partner",
    "data science", "data engineer", "marketing", "product manager",
    "software engineer", "developer", "architect", "intern", "analyst",
    "junior", "administrative", "assistant", "designer", "ux ",
    "content writer", "copywriter", "nurse", "physician", "clinical",
    "teacher", "professor", "chef", "bartender", "barista", "warehouse",
    "logistics", "supply chain", "help desk", "data entry", "cashier",
    "driver", "mechanical", "electrical", "hardware", "civil engineer",
    "chemical", "biomedical", "pharmaceutical", "research scientist",
    "postdoc", "lecturer", "tutor", "paralegal", "underwriter", "actuary",
    "financial advisor", "investment banking", "trader", "quantitative",
    "devops", "sre", "site reliability", "accountant", "accounting",
    "controller", "treasury", "audit", "tax", "localization",
]


def score_title(title: str) -> float:
    """Quick match score (0-5) for a job title."""
    tl = title.lower()

    # Negative check
    if any(k in tl for k in NEGATIVE_KW):
        return 0.0

    # Seniority check
    if not any(k in tl for k in SENIORITY_KW):
        return 0.0

    # Domain check
    domain_score = sum(1 for k in DOMAIN_KW if k in tl)
    if domain_score == 0:
        return 0.0

    # Map to 0-5
    if domain_score >= 4:
        return 5.0
    elif domain_score >= 3:
        return 4.5
    elif domain_score >= 2:
        return 4.0
    else:
        return 3.5


# ─── Dedup ────────────────────────────────────────────────────────────

def load_seen_urls() -> set[str]:
    seen = set()
    for fpath in [PIPELINE_FILE, SCAN_HISTORY_FILE, APPLICATIONS_FILE]:
        if not fpath.exists():
            continue
        text = fpath.read_text()
        urls = re.findall(r'https?://[^\s\)\]\}\|]+', text)
        seen.update(u.rstrip('.,;') for u in urls)
    return seen


# ─── Logging ──────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] career_engine: {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ─── State management ─────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "runs": 0,
        "jobs_evaluated": 0,
        "materials_generated": 0,
        "follow_ups_sent": 0,
        "last_briefing": None,
    }


def save_state(state: dict):
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ─── Telegram ─────────────────────────────────────────────────────────


# ─── Command runner ───────────────────────────────────────────────────

def run_cmd(cmd: list, timeout: int = 120) -> tuple[str, str, int]:
    """Run a command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(CAREER_OPS_DIR),
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Timed out", 1
    except Exception as e:
        return "", str(e), 1


# ─── Job Search ───────────────────────────────────────────────────────

def run_api_scan() -> list[dict]:
    """Run scan.mjs and return new job dicts from pipeline.md."""
    result = subprocess.run(
        ["node", str(CAREER_OPS_DIR / "scan.mjs")],
        capture_output=True, text=True, timeout=120,
        cwd=str(CAREER_OPS_DIR)
    )
    new_jobs = []
    in_new_offers = False
    for line in result.stdout.split('\n'):
        if line.startswith('New offers:'):
            in_new_offers = True
            continue
        if in_new_offers:
            if line.startswith('  + '):
                parts = line[4:].split(' | ')
                if len(parts) >= 2:
                    new_jobs.append({
                        'company': parts[0].strip(),
                        'title': parts[1].strip(),
                        'location': parts[2].strip() if len(parts) > 2 else '',
                        'source': 'api-scan',
                    })
            elif line.strip() == '' or line.startswith('Results'):
                in_new_offers = False
    return new_jobs


def search_linkedin() -> list[dict]:
    """Search LinkedIn for fresh job postings via SearXNG."""
    queries = [
        'site:linkedin.com/jobs/view "Director" "Program Management" "Seattle"',
        'site:linkedin.com/jobs/view "Director" "Technical Program" "Seattle"',
        'site:linkedin.com/jobs/view "Head of" "Program Management" "Seattle"',
        'site:linkedin.com/jobs/view "Director" "Program Management" "San Francisco Bay Area"',
        'site:linkedin.com/jobs/view "Director" "Program Management" "Remote" "United States"',
        'site:linkedin.com/jobs/view "Director" "Program Management"',
        'site:linkedin.com/jobs/view "Director" "Technical Program"',
        'site:linkedin.com/jobs/view "Director" "Transformation"',
        'site:linkedin.com/jobs/view "Director" "Enterprise Delivery"',
        'site:linkedin.com/jobs/view "VP" "Program Management"',
        'site:linkedin.com/jobs/view "Chief of Staff"',
        'site:linkedin.com/jobs/view "Director" "Strategic Initiatives"',
    ]

    results = []
    seen_urls = load_seen_urls()

    for query in queries:
        params = {
            "q": query, "format": "json", "categories": "general",
            "language": "en", "pageno": "1",
        }
        url = f"{SEARXNG_URL}/search?{urlencode(params)}"
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "10", url],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for r in data.get("results", []):
                    job_url = r.get("url", "")
                    if job_url and job_url not in seen_urls:
                        title = r.get("title", "")
                        snippet = r.get("content", "")
                        score = score_title(title)
                        if score > 0:
                            results.append({
                                "title": title,
                                "url": job_url,
                                "snippet": snippet[:200],
                                "score": score,
                                "source": "linkedin-search",
                            })
                            seen_urls.add(job_url)
        except Exception as e:
            log(f"LinkedIn search error for query '{query}': {e}")

    return results


def job_search(max_show: int = 6) -> list[dict]:
    """Search for fresh job postings."""
    log("Searching for fresh jobs...")

    # API scan
    api_jobs = run_api_scan()
    log(f"API scan found {len(api_jobs)} new jobs")

    # LinkedIn search
    linkedin_jobs = search_linkedin()
    log(f"LinkedIn search found {len(linkedin_jobs)} new jobs")

    # Combine and score
    all_jobs = api_jobs + linkedin_jobs

    # Add score for LinkedIn jobs
    for job in all_jobs:
        if "score" not in job:
            job["score"] = score_title(job.get("title", ""))

    # Sort by score descending
    all_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Show top matches
    shown = 0
    for job in all_jobs:
        if shown >= max_show:
            break
        title = job.get("title", job.get("info", "Unknown"))
        company = job.get("company", "Unknown")
        score = job.get("score", 0)
        source = job.get("source", "unknown")
        print(f"  [{score:.1f}] {title} @ {company} ({source})")
        shown += 1

    log(f"Total jobs found: {len(all_jobs)}, showing top {shown}")
    return all_jobs


# ─── Evaluation ───────────────────────────────────────────────────────


# ─── Follow-up ────────────────────────────────────────────────────────

def follow_up_stale(days_stale: int = 14) -> list[dict]:
    """Find and follow up on stale applications."""
    log(f"Checking for stale applications (>{days_stale} days)...")

    if not APPLICATIONS_FILE.exists():
        return []

    content = APPLICATIONS_FILE.read_text()
    rows = [l for l in content.split("\n") if l.startswith("|") and "---" not in l]

    stale = []
    for row in rows:
        cols = [c.strip() for c in row.split("|")]
        if len(cols) >= 9:
            date_str = cols[1] if len(cols) > 1 else ""
            status = cols[5] if len(cols) > 5 else ""
            company = cols[3] if len(cols) > 3 else ""
            role = cols[4] if len(cols) > 4 else ""

            if status == "Evaluated":
                try:
                    app_date = datetime.strptime(date_str, "%Y-%m-%d")
                    age_days = (datetime.now() - app_date).days
                    if age_days >= days_stale:
                        stale.append({
                            "company": company,
                            "role": role,
                            "date": date_str,
                            "days_old": age_days,
                        })
                except ValueError:
                    pass

    log(f"Found {len(stale)} stale applications")
    return stale


# ─── Pipeline Status ──────────────────────────────────────────────────

def get_pipeline_status() -> dict:
    """Get current pipeline status."""
    stats = {"applications": 0, "pending": 0, "by_status": {}}

    if APPLICATIONS_FILE.exists():
        rows = [l for l in APPLICATIONS_FILE.read_text().split("\n")
                if l.startswith("|") and "---" not in l]
        stats["applications"] = len(rows)
        for row in rows:
            cols = [c.strip() for c in row.split("|")]
            if len(cols) >= 6:
                status = cols[5]
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

    if PIPELINE_FILE.exists():
        pending = [l for l in PIPELINE_FILE.read_text().split("\n")
                   if l.strip().startswith("- [ ]")]
        stats["pending"] = len(pending)

    return stats


# ─── Main Cycle ───────────────────────────────────────────────────────

def _is_kept_url(url: str) -> bool:
    """Keep a job for the US-only briefing/digest.

    Only LinkedIn country-subdomain URLs are dropped (in./uk./ca./kr./mx./...);
    www.linkedin.com/linkedin.com and all non-LinkedIn career-site URLs
    (ashby/greenhouse/lever/etc.) are kept, since those are US/global company
    career pages. Replaces the stricter _is_us_linkedin at READ time so
    non-LinkedIn US jobs (e.g. ashby OpenAI, Stripe greenhouse) are no longer
    excluded from the briefing/digest while country-subdomain LinkedIn is still.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True
    if host in ("www.linkedin.com", "linkedin.com"):
        return True
    if host.endswith(".linkedin.com"):
        return False
    return True


def persist_new_jobs(jobs: list[dict]) -> int:
    """Insert scraped matches into job_postings (dedup by url; score >= MIN_SCORE).

    Without this, job_search() results are discarded (the old loop did `continue`
    on every URL job) and the daily briefing is always empty, so no jobs are
    ever notified on Telegram.
    """
    if not jobs:
        return 0
    seen = load_seen_urls()
    conn = sqlite3.connect(str(CAREER_DB))
    try:
        count = 0
        for job in jobs:
            url = job.get("url", "")
            if not url or url in seen:
                continue
            # Drop non-US LinkedIn jobs (country subdomains). US/global jobs
            # (www.linkedin.com) — incl. Seattle/remote-US — are kept.
            if job.get("source", "linkedin-search") == "linkedin-search" and not _is_kept_url(url):
                continue
            score = job.get("score") or score_title(job.get("title", ""))
            if score < MIN_SCORE:
                continue
            if conn.execute("SELECT 1 FROM job_postings WHERE url=?", (url,)).fetchone():
                seen.add(url)
                continue
            conn.execute(
                "INSERT INTO job_postings (url, company, title, jd_text, score, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (url, job.get("company", ""), job.get("title", ""),
                 job.get("snippet", ""), round(float(score), 2),
                 job.get("source", "linkedin-search")),
            )
            seen.add(url)
            count += 1
        conn.commit()
        return count
    except Exception as e:
        log(f"persist_new_jobs error: {e}")
        return 0
    finally:
        conn.close()


def run_full_cycle():
    """Run the full autonomous career cycle."""
    state = load_state()
    state.setdefault("runs", 0)
    state["runs"] += 1
    log(f"{'='*60}")
    log(f"Career Autonomous Cycle #{state['runs']}")
    log(f"{'='*60}")

    # 1. Job search
    jobs = job_search()

    # 1b. Persist fresh matches so the daily briefing has matches to surface.
    persisted = persist_new_jobs(jobs)
    log(f"Persisted {persisted} new job matches (>= {MIN_SCORE})")

    # 3. Follow-up on stale applications
    stale = follow_up_stale(14)
    evaluated = len(jobs)
    generated = persisted
    if stale:
        log(f"⚠️ {len(stale)} applications need follow-up")
        for s in stale[:3]:
            log(f"  Follow-up needed: {s['company']} — {s['role']} ({s['days_old']}d)")

    # 4. Send daily briefing (once per day)
    last_briefing = state.get("last_briefing")
    if not last_briefing or (datetime.now(timezone.utc) - datetime.fromisoformat(last_briefing)).total_seconds() > 20 * 3600:
        send_daily_briefing(state)
        state["last_briefing"] = datetime.now(timezone.utc).isoformat()

    save_state(state)
    log(f"Cycle complete. Evaluated: {evaluated}, Generated: {generated}, Stale: {len(stale)}")


def send_career_digest(recent_jobs: list[dict], stats: dict):
    """Push a one-message Telegram digest of fresh high-match jobs (once/day)."""
    today = datetime.now().strftime("%Y-%m-%d")
    sentinel = HERMES_HOME / "data" / f"career_digest_sent_{today}"
    if sentinel.exists():
        log("Career digest already sent today; skipping telegram")
        return
    try:
        top = recent_jobs[:5]
        lines = [f"📊 Career matches: {len(recent_jobs)} new in last 24h (score >= {MIN_SCORE})"]
        for j in top:
            lines.append(f"\u2022 [{j.get('score')}] {j.get('title','')} @ {j.get('company','')}")
            if j.get("url"):
                lines.append(f"  \u2193 {j.get('url')}")
        lines.append(f"\U0001f4ca {stats.get('total_applications', 0)} apps tracked \u00b7 {stats.get('identified', 0)} identified")
        text = "\n".join(lines)
        payload = json.dumps({"text": text, "category": "career", "priority": "normal"})
        r = subprocess.run(
            ["curl", "-s", "--max-time", "10", "-X", "POST", "http://127.0.0.1:9199/telegram-send",
             "-H", "Content-Type: application/json", "-d", payload],
            capture_output=True, text=True, timeout=15,
        )
        log(f"Career digest sent: {len(recent_jobs)} matches (top {len(top)}) -> {r.stdout.strip()[:120]}")
        sentinel.touch()
    except Exception as e:
        log(f"Career digest send failed: {e}")


def send_daily_briefing(state: dict):
    """Extract top career matches and save briefing JSON for the homelab digest."""
    log("Generating career briefing...")
    if not CAREER_DB.exists():
        log(f"Career DB not found: {CAREER_DB}")
        return

    try:
        conn = sqlite3.connect(str(CAREER_DB))
        conn.row_factory = sqlite3.Row
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        rows = conn.execute("""
            SELECT title, company, score, source, url, seen_at
            FROM job_postings
            WHERE seen_at > ? AND score >= ?
            ORDER BY score DESC
         """, (cutoff, MIN_SCORE)).fetchall()
        # US-only at READ: keep www/linkedin.com + non-LinkedIn career sites;
        # drop LinkedIn country subdomains (in./uk./ca./...). Count BEFORE slicing to 10.
        recent_jobs = [dict(r) for r in rows if _is_kept_url(r["url"] or "")]
        recent_jobs_24h = len(recent_jobs)
        recent_jobs = recent_jobs[:10]

        app_rows = conn.execute("""
            SELECT company, title, score, status, created_at, url
            FROM applications
            WHERE created_at > ?
            ORDER BY score DESC NULLS LAST
            LIMIT 5
        """, (cutoff,)).fetchall()
        recent_apps = [dict(r) for r in app_rows]

        pending_rows = conn.execute("""
            SELECT company, title, score, status, url
            FROM applications
            WHERE status IN ('identified')
            ORDER BY score DESC NULLS LAST
            LIMIT 5
        """).fetchall()
        pending = [dict(r) for r in pending_rows]

        stats = {
            "total_applications": conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
            "identified": conn.execute("SELECT COUNT(*) FROM applications WHERE status='identified'").fetchone()[0],
            "recent_jobs_24h": recent_jobs_24h,
            "top_score": conn.execute("SELECT MAX(score) FROM applications").fetchone()[0],
        }
        conn.close()

        briefing = {
            "generated_at": datetime.now().isoformat(),
            "stats": stats,
            "recent_matches": recent_jobs,
            "recent_applications": recent_apps,
            "pending_applications": pending,
        }

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(briefing, indent=2))
        log(f"Briefing saved to {OUTPUT_FILE}: {len(recent_jobs)} jobs, {len(pending)} pending")

        # Notify on a meaningful batch of fresh matches (>4 in last 24h) — once/day.
        if recent_jobs and len(recent_jobs) > 4:
            send_career_digest(recent_jobs, stats)
    except Exception as e:
        log(f"Briefing error: {e}")


# ─── CLI ──────────────────────────────────────────────────────────────

def main():
    if "--search" in sys.argv:
        jobs = job_search()
        for j in jobs:
            print(j)
    elif "--evaluate" in sys.argv:
        pipe_file = CAREER_OPS_DIR / "data" / "pipeline.md"
        if pipe_file.exists():
            pending = [l for l in pipe_file.read_text().split("\n")
                       if l.strip().startswith("- [ ]")]
            print(f"{len(pending)} pending jobs in pipeline")
            for p in pending[:5]:
                print(f"  {p.strip()}")
    elif "--followup" in sys.argv:
        stale = follow_up_stale()
        for s in stale:
            print(f"{s['company']} — {s['role']} ({s['days_old']}d old)")
    elif "--briefing" in sys.argv:
        state = load_state()
        state.setdefault("runs", 0)
        send_daily_briefing(state)
    elif "--status" in sys.argv:
        stats = get_pipeline_status()
        print(json.dumps(stats, indent=2))
    else:
        run_full_cycle()


if __name__ == "__main__":
    main()