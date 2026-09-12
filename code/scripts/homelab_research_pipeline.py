#!/usr/bin/env python3
"""homelab_research_pipeline.py — Automated discovery + assessment pipeline.

Runs the full research pipeline:
  1. Discover new repos/articles (daily_research.py + research_engine.py)
  2. CRG/graphify assessment for each discovered item
  3. Rank and recommend top items for homelab + Hermes
  4. Send results to Telegram via bridge

Scheduled via systemd timer (runs daily at 06:00).
"""
import json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
if not os.environ.get("TELEGRAM_HOME_CHANNEL"):
    env_file = HERMES_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip(chr(34) + chr(39)))
DATA_DIR = HERMES_HOME / "data" / "research"
RESULTS_FILE = DATA_DIR / "pipeline_results.jsonl"
BRIDGE_URL = os.environ.get("TELEGRAM_BRIDGE_URL", "http://127.0.0.1:9199")
BRIDGE_AUTH = os.environ.get("BRIDGE_AUTH_KEY", "default-key-change-me")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_HOME_CHANNEL", "")

def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception:
        return -1, "", "command failed"

def _send_telegram(text):
    if not TELEGRAM_CHAT:
        return False
    import urllib.request
    payload = json.dumps({"chat_id": TELEGRAM_CHAT, "text": text[:4000]}).encode()
    try:
        req = urllib.request.Request(
            BRIDGE_URL + "/telegram-send",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {BRIDGE_AUTH}"},
        )
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False

def run_daily_research():
    """Run daily_research.py to discover new repos."""
    rc, out, err = _run(["python3", str(HERMES_HOME / "scripts" / "daily_research.py")], timeout=60)
    if rc != 0:
        print("daily_research failed:", err[:200])
        return []
    return out.strip().split("\n") if out.strip() else []

def run_research_engine():
    """Run research_engine.py discover + recommend."""
    rc, out, err = _run(["python3", str(HERMES_HOME / "scripts" / "research_engine.py"), "discover"], timeout=60)
    if rc != 0:
        print("research_engine discover failed:", err[:200])
    rc2, out2, _ = _run(["python3", str(HERMES_HOME / "scripts" / "research_engine.py"), "recommend"], timeout=30)
    if rc2 != 0:
        print("research_engine recommend failed:", out2[:200])
        return []
    return out2.strip() if out2.strip() else ""

def assess_item(item):
    """Run CRG/graphify assessment on a discovered item."""
    url = item.get("url", "")
    title = item.get("title", "")
    repo_name = ""

    # Extract repo name from GitHub URL
    import re
    m = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    if m:
        repo_name = m.group(1) + "/" + m.group(2)

    # CRG analysis
    crg_results = {}
    if repo_name:
        rc, out, _ = _run(["/home/rohit/.local/bin/code-review-graph", "search", repo_name], timeout=10)
        if rc == 0 and out.strip():
            try:
                search_data = json.loads(out)
                results = search_data.get("results", []) if isinstance(search_data, dict) else []
                crg_results["graph_match"] = len(results) > 0
            except (json.JSONDecodeError, TypeError):
                crg_results["graph_match"] = False
        else:
            crg_results["graph_match"] = False

        rc2, arch_out, _ = _run(["/home/rohit/.local/bin/code-review-graph", "architecture"], timeout=10)
        if rc2 == 0 and arch_out.strip():
            crg_results["architecture"] = arch_out.strip()[:200]

        rc3, blast_out, _ = _run(["/home/rohit/.local/bin/code-review-graph", "impact", "--files", repo_name], timeout=10)
        if rc3 == 0 and blast_out.strip():
            crg_results["blast_radius"] = blast_out.strip()[:200]

    # Build assessment summary
    graph_line = "CRG: matched" if crg_results.get("graph_match") else "CRG: no match"
    arch_line = ""
    if crg_results.get("architecture"):
        arch_line = " | architecture available"

    return {
        "title": title,
        "url": url,
        "crg_analysis": crg_results,
        "summary": graph_line + arch_line,
    }

def verify_claim(claim):
    """Verify a claim against actual system state. Returns (verified, evidence)."""
    import re
    
    # Check if a Docker service is running
    m = re.search(r'(?:install|deploy|setup|configure|enable)\s+(\S+)', claim, re.I)
    if m:
        svc = m.group(1)
        rc, out, _ = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=10)
        if rc == 0:
            running = [n.strip() for n in out.strip().split("\n") if n.strip()]
            if svc.lower() in [r.lower() for r in running]:
                return True, f"{svc} is running (docker ps confirms)"
            # Check if it's a compose service
            compose_files = list((Path.home() / "services" / "docker" / "compose").glob("*.yml")) if (Path.home() / "services" / "docker" / "compose").exists() else []
            for cf in compose_files:
                if svc.lower() in cf.read_text().lower():
                    return False, f"{svc} found in compose but not running: docker ps shows {len(running)} containers"
    
    elif re.search(r'(?:ran|executed)\s+[`\']?(\S+)', claim, re.I):
        # Check if a command was actually run
        m2 = re.search(r'(?:ran|executed)\s+[`\']?(\S+)', claim, re.I)
        cmd = m2.group(1)
        rc, out, _ = _run(["which", cmd], timeout=5)
        if rc == 0:
            return True, f"{cmd} is available on the system"
        return False, f"{cmd} not found on the system"
    elif re.search(r'(?:created|modified|wrote|saved)\s+(\S+)', claim, re.I):
        # Check if a file was created/modified
        m3 = re.search(r'(?:created|modified|wrote|saved)\s+(\S+)', claim, re.I)
        path = m3.group(1)
        if Path(path).exists():
            return True, f"{path} exists on disk"
        return False, f"{path} does not exist on disk"
    
    return None, "unable to verify claim automatically"

def verify_pipeline_results(results):
    """Verify that pipeline results are real, not hallucinated."""
    verified = []
    for r in results:
        v = verify_claim(r.get("summary", ""))
        r["_verified"] = v[0]
        r["_verification_evidence"] = v[1]
        verified.append(r)
    return verified

def _send_progress(stage, detail=""):
    """Progress updates to Telegram (gated — off by default to keep inbox actionable)."""
    if os.getenv("RESEARCH_PROGRESS", "0") != "1":
        return
    msg = "Research Pipeline\n\nStage: " + stage
    if detail:
        msg += "\n" + detail
    _send_telegram(msg)

def pipeline():
    print("=== Homelab Research Pipeline ===")
    print("Started at", datetime.now().isoformat())

    # Step 1: Discover
    print("\n[1/3] Discovering...")
    _send_progress("1/3 Discovering", "Fetching new repos and articles from GitHub, HN, Reddit...")
    daily_out = run_daily_research()
    engine_out = run_research_engine()
    _send_progress("1/3 Discovering", "Discovery complete. Moving to assessment...")

    # Step 2: Load findings and assess
    print("\n[2/3] Assessing with CRG/graphify...")
    _send_progress("2/3 Assessing", "Running CRG blast-radius and architecture analysis on discovered items...")
    findings = []

    # Load from daily_research results
    results_file = Path.home() / ".hermes" / "research_results.json"
    if results_file.exists():
        try:
            data = json.loads(results_file.read_text())
            for item in data[-20:]:  # last 20 findings
                assessed = assess_item(item)
                findings.append(assessed)
        except (json.JSONDecodeError, TypeError):
            pass

    # Load from research_engine recommendations
    rec_file = DATA_DIR / "recommendations.json"
    if rec_file.exists():
        try:
            recs = json.loads(rec_file.read_text())
            for item in recs[:10]:  # top 10 recommendations
                assessed = assess_item(item)
                findings.append(assessed)
        except (json.JSONDecodeError, TypeError):
            pass

    # Deduplicate by URL
    seen_urls = set()
    unique_findings = []
    for f in findings:
        if f["url"] not in seen_urls:
            seen_urls.add(f["url"])
            unique_findings.append(f)

    # Step 3: Rank and report
    print("\n[3/3] Ranking and reporting...")
    _send_progress("3/3 Ranking", "Ranking items by CRG graph relevance and homelab fit...")
    ranked = sorted(unique_findings, key=lambda x: len(x.get("crg_analysis", {}).get("architecture", "")), reverse=True)

    # Build Telegram message
    lines = ["🔬 *Homelab Research Pipeline*\n"]
    lines.append(f"Assessed {len(ranked)} items at {datetime.now().strftime('%H:%M')}")
    lines.append("")

    for i, f in enumerate(ranked[:10], 1):
        crg = f.get("crg_analysis", {})
        graph_tag = "📊" if crg.get("graph_match") else "📄"
        arch_tag = "🏗️" if crg.get("architecture") else "❌"
        blast_tag = "⚡" if crg.get("blast_radius") else ""
        lines.append(f"{graph_tag}{arch_tag}{blast_tag} {i}. {f['title']}")
        if f.get("summary"):
            lines.append(f"   {f['summary']}")
        lines.append("")

    msg = "\n".join(lines)

    # Save results
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_FILE, "a") as rf:
        rf.write(json.dumps({"timestamp": datetime.now().isoformat(), "findings": ranked}) + "\n")

    # Verify results are real, not hallucinated
    print("\n[Verification] Checking results against actual system state...")
    _send_progress("Verification", "Checking results against actual system state...")
    verified_results = verify_pipeline_results(ranked)
    verified_count = sum(1 for r in verified_results if r.get("_verified") is True)
    unverified_count = sum(1 for r in verified_results if r.get("_verified") is False)
    unverifiable_count = sum(1 for r in verified_results if r.get("_verified") is None)
    print(f"  Verified: {verified_count}, Unverified: {unverified_count}, Unverifiable: {unverifiable_count}")

    # Add verification note to Telegram message
    if unverified_count > 0:
        msg += "\n\n⚠️ " + str(unverified_count) + " result(s) could not be verified against actual system state."

    # Send to Telegram
    if _send_telegram(msg):
        print("Results sent to Telegram")
    else:
        print("Could not send to Telegram (no channel configured or bridge down)")

    print(f"\nPipeline complete. {len(ranked)} items assessed. {verified_count} verified.")
    _send_progress("Complete", str(len(ranked)) + " items assessed, " + str(verified_count) + " verified. See full report above.")
    return ranked

if __name__ == "__main__":
    pipeline()
