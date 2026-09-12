#!/usr/bin/env python3
"""Hermes job pipeline: fetch -> dedupe -> score -> shared jobs_*.json -> Telegram.

Writes to the shared memory dir (collaborator-memory/data/jobs_YYYYMMDD.json)
and POSTs a concise digest to the agentchaguli bridge (/telegram-send).

Source-pluggable: configure $JOB_SOURCES or a `sources.json` next to this file.
Each source is a callable(name) -> list[dict{title,company,location,url,raw}].
If none configured, a self-test source runs so the wiring can be verified.

Usage:
    JOB_EMAIL=you@x.com python3 auto_pipeline.py [--dry-run]
"""
import json
import os
import re
import sys
import subprocess
import time
import urllib.request
import hashlib
from datetime import datetime, date, timezone

# --- shared memory + bridge wiring (agrees with Hermes container + host) ---
SHARED_DIR = os.environ.get(
    "SHARED_DATA_DIR",
    "/home/rohit/.hermes/collaborator-memory/data",
)
# Inside the Hermes container this path is /opt/data/collaborator-memory/data
if os.path.isdir("/opt/data/collaborator-memory") and not os.path.isdir(SHARED_DIR):
    SHARED_DIR = "/opt/data/collaborator-memory/data"

BRIDGE_URL = os.environ.get(
    "BRIDGE_URL",
    "http://127.0.0.1:9199/telegram-send",  # docker-bridge gateway (host runs bridge)
)
SOURCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources.json")

# --- self-test source (used when no real source is configured yet) ---
def _self_test_source(name: str):
    """Default source = LinkedIn guest job search (TPM/Director Program Mgmt).

    Prefers linkedin_jobs.py (real, on-target TPM/Program-Management roles);
    falls back to discovery_source.py (free feeds) only if LinkedIn fails.
    """
    import importlib.util
    _here = os.path.dirname(os.path.abspath(__file__))

    def _load(modname):
        spec = importlib.util.spec_from_file_location(modname, os.path.join(_here, modname + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    try:
        lj = _load("linkedin_jobs")
        rec = lj.discover(queries=lj.DEFAULT_QUERIES, per_query=5)
        jobs = rec.get("jobs", [])
        if jobs:
            print("[fetch] source=linkedin candidates=%s good_fit=%s" % (rec.get("candidate_count"), len(jobs)))
            return jobs
        print("[fetch] linkedin gave 0 good-fit; trying discovery_source")
    except Exception as e:
        print("[fetch] linkedin failed (%s); trying discovery_source" % e)

    mod = _load("discovery_source")
    rec = mod.discover()
    return rec.get("jobs", [])


def _load_sources():
    """Return list of (name, loader) available."""
    sources = {"selftest": _self_test_source}
    if os.path.exists(SOURCES_FILE):
        try:
            with open(SOURCES_FILE) as fh:
                cfg = json.load(fh)
            for name, spec in cfg.items():
                engine = spec.get("engine", "generic")
                if engine == "generic":
                    sources[name] = _make_generic_loader(spec)
        except Exception as e:
            print(f"[warn] sources.json invalid ({e}); falling back to selftest")
    return sources


def _make_generic_loader(spec):
    def loader(name):
        # A future real source would fetch here; generic just returns spec-provided rows.
        rows = spec.get("rows", [])
        return [dict(row, raw=row.get("raw", f"generic:{name}")) for row in rows]
    return loader


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _prior_keys():
    """Return hashes of already-seen jobs across prior jobs_*.json files."""
    seen = set()
    if not os.path.isdir(SHARED_DIR):
        return seen
    for fn in sorted(os.listdir(SHARED_DIR)):
        if not (fn.startswith("jobs_") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(SHARED_DIR, fn)) as fh:
                data = json.load(fh)
            for job in data.get("jobs", []):
                if job.get("hash"):
                    seen.add(job["hash"])
        except Exception:
            continue
    return seen


def _hash_job(job):
    # Drop query params (LinkedIn urls carry volatile ?position/refId/trackingId
    # that change every fetch). Use only the stable path so the same job always
    # hashes identically and dedup/auto-apply do not re-fire daily.
    url = (job.get("url") or "").split("?", 1)[0].split("#", 1)[0]
    key = f"{_norm(job.get('title'))}|{_norm(job.get('company'))}|{_norm(url)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _score(job):
    """Simple 0-100 score (higher = closer to 'senior/remote/platform')."""
    text = f"{job.get('title','')} {job.get('company','')}"
    s = 50
    for kw in ("senior", "sr", "staff", "principal"):
        if kw in text.lower():
            s += 10
    if "remote" in text.lower():
        s += 10
    for kw in ("platform", "infrastructure", "sre", "devops", "backend", "distributed"):
        if kw in text.lower():
            s += 5
    return min(100, s)


def _post_telegram(digest):
    payload = json.dumps({"message": digest, "priority": "normal", "sender": "hermes_job_pipeline"}).encode()
    req = urllib.request.Request(BRIDGE_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main():
    dry_run = "--dry-run" in sys.argv
    no_tg = "--no-telegram" in sys.argv
    sources = _load_sources()
    seen = _prior_keys()

    all_jobs, new_jobs = [], []
    for name, loader in sources.items():
        print(f"[fetch] source={name}")
        for raw_job in loader(name):
            job = dict(raw_job)
            job.setdefault("hash", _hash_job(job))
            job.setdefault("source", name)
            job.setdefault("score", _score(job))
            job.setdefault("fetched", datetime.now(timezone.utc).isoformat())
            all_jobs.append(job)
            if job["hash"] not in seen:
                new_jobs.append(job)
            seen.add(job["hash"])

    print(f"[dedupe] total={len(all_jobs)} new={len(new_jobs)}")

    today = date.today().isoformat()
    out_path = os.path.join(SHARED_DIR, f"jobs_{today}.json")
    record = {
        "generated_by": "auto_pipeline.py",
        "agent": "hermes",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "new_count": len(new_jobs),
        "total_count": len(all_jobs),
        "jobs": sorted(all_jobs, key=lambda j: -j["score"]),
    }

    if not dry_run:
        os.makedirs(SHARED_DIR, exist_ok=True)
        with open(out_path, "w") as fh:
            json.dump(record, fh, indent=2)
        print(f"[write] {out_path} ({len(all_jobs)} jobs)")

    # Build concise digest for agentchaguli
    lines = [f"🤖 AgentChaguli · Job digest {today}"]
    lines.append(f"Sources: {len(sources)} · New: {len(new_jobs)} / Total: {len(all_jobs)}")
    for j in new_jobs[:8]:
        lines.append(f"  • {j['score']} {j['company']} | {j['title']} ({j['location']})")
    if not new_jobs:
        lines.append("  (no new jobs since last run)")
    digest = "\n".join(lines)

    if dry_run:
        print("---- DIGEST (dry-run, not sent) ----")
        print(digest)
        return 0

    _run_auto_apply(new_jobs, dry_run)

    if no_tg:
        print("---- DIGEST (Telegram post skipped by --no-telegram) ----")
        print(digest)
        return 0

    result = _post_telegram(digest)
    ok = result.get("ok", True)
    print(f"[telegram] sent={ok}")
    return 0 if ok else 2




AUTO_APPLY_MIN_SCORE = int(os.environ.get("AUTO_APPLY_MIN_SCORE", "52"))
APPLY_SHIM = "/home/rohit/.hermes/scripts/run_apply.sh"


def _queue_host_apply(job: dict) -> bool:
    """Stand-in for run_apply.sh when this process runs inside a container.

    /home/rohit (host) is not reachable from the n8n-bridge container, so we
    queue the job for the host-side apply worker (apply_queue_worker.py) which
    owns the real host paths, creds and GDrive push.
    """
    try:
        base = "/opt/data" if os.path.isdir("/opt/data") else "/home/rohit/.hermes"
        qdir = os.path.join(base, "data", "apply_queue")
        os.makedirs(qdir, exist_ok=True)
        q = {
            "url": job.get("url", ""),
            "company": job.get("company", job.get("company_name", "Unknown")),
            "title": job.get("title", "Unknown"),
            "score": int(job.get("score", 0) or 0),
            "ts": round(time.time()),
        }
        rid = hashlib.sha1(str(q.get("url", "")).encode()).hexdigest()[:12]
        p = os.path.join(qdir, rid + ".json")
        if os.path.exists(p):
            return True
        with open(p, "w") as fh:
            json.dump(q, fh, indent=2)
        return True
    except Exception as e:
        print("[queue] ERROR: %s" % e)
        return False


def _auto_apply(job, dry_run: bool):
    """Run career-ops auto_pipeline for one high-fit job on the host.

    The discovery pipeline runs on the host as rohit (systemd user timer), so we
    normally invoke the run_apply.sh shim directly. When running inside a
    container (Telegram-triggered), queue for the host worker instead.
    """
    if os.path.isdir("/opt/data") and not os.path.isdir("/home/rohit"):
        print("[apply] queued for host worker (container path)")
        _queue_host_apply(job)
        return
    import base64 as _b64
    payload = _b64.b64encode(
        json.dumps({
            "url": job.get("url", ""),
            "company": job.get("company", job.get("company_name", "")),
            "title": job.get("title", ""),
            "score": int(job.get("score", 0) or 0),
        }).encode()
    ).decode()
    cmd = ["bash", APPLY_SHIM, payload]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        lines = (r.stdout + "\n" + r.stderr).strip().splitlines()
        print("[apply] rc=%s %s" % (r.returncode, lines[-1] if lines else ""))
        for line in lines[-6:]:
            print("         " + line)
    except Exception as e:
        print("[apply] ERROR: %s" % e)


def _run_auto_apply(new_jobs, dry_run: bool):
    """Apply to top-fit NEW jobs (score >= threshold), best candidates first."""
    hits = sorted(
        (j for j in new_jobs if (j.get("score", 0) or 0) >= AUTO_APPLY_MIN_SCORE),
        key=lambda j: - (j.get("score", 0) or 0),
    )
    print("[apply] candidates(>=%s)=%d" % (AUTO_APPLY_MIN_SCORE, len(hits)))
    for j in hits:
        _auto_apply(j, dry_run)


if __name__ == "__main__":
    sys.exit(main())
