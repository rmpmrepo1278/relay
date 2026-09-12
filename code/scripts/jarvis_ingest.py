#!/usr/bin/env python3
"""Jarvis ingest: read Hermes jobs_*.json -> write jars_*.json (deep-reasoning).

Runs as the host `rohit` process (same user that owns the shared dir), so no
special perms needed. It reads each day's Hermes job digest and appends a
synthetic deep-dive (analysis + recommended skills) so Jarvis and Hermes share
the same memory source without overlapping work.

Contract:
  IN   /home/rohit/.hermes/collaborator-memory/data/jobs_<date>.json
  OUT  /home/rohit/.hermes/collaborator-memory/data/jars_<date>.json

Usage:
    python3 jarvis_ingest.py [--dry-run]
"""
import json
import os
import sys
from datetime import datetime, date, timezone

SHARED_DIR = os.environ.get(
    "SHARED_DATA_DIR",
    "/home/rohit/.hermes/collaborator-memory/data",
)

SKILL_BY_KEYWORD = {
    "platform": "distributed-systems, terraform, kubernetes",
    "infrastructure": "linux, docker, IaC",
    "sre": "slo/sli, runbooks, observability",
    "devops": "ci/cd, gitops",
    "backend": "python/go, apis, databases",
    "distributed": "consensus, replication, scaling",
    "senior": "mentoring, architecture, system-design",
}


def _detect_skills(record):
    counts = {}
    for job in record.get("jobs", []):
        text = f"{job.get('title','')} {job.get('company','')}".lower()
        for kw, skills in SKILL_BY_KEYWORD.items():
            if kw in text:
                counts[kw] = counts.get(kw, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    return [SKILL_BY_KEYWORD[k] for k, _ in top], top


def _already_reasoned(today):
    out = os.path.join(SHARED_DIR, f"jars_{today}.json")
    return os.path.exists(out)


def main():
    dry = "--dry-run" in sys.argv
    today = date.today().isoformat()
    in_path = os.path.join(SHARED_DIR, f"jobs_{today}.json")

    if _already_reasoned(today) and not dry:
        print("[skip] jars_%s.json already exists" % today)
        return 0
    if not os.path.exists(in_path):
        print("[skip] no jobs_%s.json yet (run auto_pipeline first)" % today)
        return 1

    with open(in_path) as fh:
        record = json.load(fh)

    skills, top = _detect_skills(record)
    summary = {
        "agent": "jarvis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on": os.path.basename(in_path),
        "total_jobs": record.get("total_count"),
        "new_jobs": record.get("new_count"),
        "top_skills": skills,
        "keyword_trends": [{"keyword": k, "hits": c} for k, c in top],
        "recommendation": (
            "Focus applications on the highest-scored, keyword-matched roles; "
            "prepare tailored resumes for the detected skill clusters above."
        ),
    }

    out_path = os.path.join(SHARED_DIR, f"jars_{today}.json")
    if dry:
        print(json.dumps(summary, indent=2))
        return 0

    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"[write] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
