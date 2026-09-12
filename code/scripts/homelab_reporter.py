#!/usr/bin/env python3
"""homelab_reporter.py — Generates structured reports for n8n to deliver.

Container health + resource summaries are handled by n8n Daily Health Digest.
This script provides: career pipeline, LLM costs, deploy notifications, fix history.
Outputs JSON consumed by n8n workflows or the bridge server.
"""

import json
import hashlib
import pathlib, os, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
from homelab_graph import crg_status, run_cmd

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
REPORT_FILE = DATA_DIR / "data" / "latest_report.json"

def count_recent_logs(log_file, hours=168):
    if not log_file.exists():
        return 0, []
    cutoff = datetime.now() - timedelta(hours=hours)
    count = 0
    recent = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("timestamp") or entry.get("deployed_at") or \
                     entry.get("evaluated_at") or entry.get("discovered_at", "")
                if ts:
                    d = datetime.fromisoformat(ts)
                    if d > cutoff:
                        count += 1
                        recent.append(entry)
            except: pass
    return count, recent

def generate_report():
    print(f"Generating report at {datetime.now().isoformat()}")

    fix_count, fixes = count_recent_logs(DATA_DIR / "data" / "fix_log.jsonl", hours=168)
    deploy_count, deploys = count_recent_logs(DATA_DIR / "data" / "deploy_log.jsonl", hours=168)
    discover_count, discoveries = count_recent_logs(DATA_DIR / "data" / "discoveries.jsonl", hours=168)

    report = {
        "type": "structured_report",
        "generated_at": datetime.now().isoformat(),
        "sections": []
    }

    # Career briefing
    career_file = DATA_DIR / "data" / "career_briefing.json"
    if career_file.exists():
        try:
            career = json.loads(career_file.read_text())
            cstats = career.get("stats", {})
            recent = career.get("recent_matches", [])
            pending = career.get("pending_applications", [])

            if cstats:
                career_lines = []
                if cstats.get("total_applications"):
                    career_lines.append(f"Total applications: {cstats['total_applications']}")
                if cstats.get("pending"):
                    career_lines.append(f"Pending action: {cstats['pending']}")
                if cstats.get("applied"):
                    career_lines.append(f"Applied: {cstats['applied']}")
                if cstats.get("interviewing"):
                    career_lines.append(f"Interviewing: {cstats['interviewing']}")
                if cstats.get("recent_jobs_24h"):
                    career_lines.append(f"New jobs found (24h): {cstats['recent_jobs_24h']}")
                if career_lines:
                    report["sections"].append({
                        "header": "Career Pipeline",
                        "body": " | ".join(career_lines)
                    })

            if recent:
                lines = []
                for j in recent[:5]:
                    score = j.get("score", "?")
                    title = j.get("title", "?")
                    company = j.get("company", "?")
                    lines.append(f"  {score} -- {title} @ {company}")
                report["sections"].append({
                    "header": "Top Job Matches",
                    "body": "\n".join(lines)
                })

            if pending:
                lines = []
                for a in pending[:3]:
                    score = a.get("score")
                    if score is None:
                        continue
                    title = a.get("title", "")
                    company = a.get("company", "")
                    if not title or company in ("**", "") or len(company) < 3:
                        continue
                    lines.append(f"  {score} -- {title} @ {company}")
                if lines:
                    report["sections"].append({
                        "header": "Pending Applications",
                        "body": "\n".join(lines)
                    })
        except Exception as e:
            print(f"  Career briefing error: {e}")

    # LLM Cost summary
    cost_log_file = DATA_DIR / "cost_logs" / "index.json"
    if cost_log_file.exists():
        try:
            cost_data = json.loads(cost_log_file.read_text())
            today = datetime.now().strftime("%Y-%m-%d")
            if today in cost_data.get("daily_costs", {}):
                month_cost = sum(v for k, v in cost_data.get("daily_costs", {}).items() if k[:7] == today[:7])
                total_calls = sum(m.get("calls", 0) for m in cost_data.get("model_totals", {}).values())
                total_cost = cost_data.get("daily_costs", {}).get(today, 0)
                cost_line = f"Today: ${total_cost:.3f} | Month: ${month_cost:.3f} | Calls: {total_calls}"
                report["sections"].append({
                    "header": "LLM Costs",
                    "body": cost_line
                })
        except Exception as e:
            print(f"  Cost summary error: {e}")

    # CRG graph stats
    graph = crg_status()
    if isinstance(graph, dict) and "nodes" in graph:
        report["sections"].append({
            "header": "Code Graph",
            "body": f"Nodes: {graph.get("nodes", "?")} | Edges: {graph.get("edges", "?")} | Files: {graph.get("files", "?")} | Updated: {graph.get("last_updated", "?")}"
        })

    # Activity summary
    report["sections"].append({
        "header": "Activity (7d)",
        "body": f"Fixes: {fix_count} | Deploys: {deploy_count} | Discoveries: {discover_count}"
    })

    if fix_count > 0:
        report["sections"].append({
            "header": "Recent fixes",
            "body": "\n".join(
                f"  {f.get('service', '?')}: {f.get('action', '?')} -> {f.get('result', '?')}"
                for f in fixes[-5:]
            )
        })

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    print(f"  Report saved to {REPORT_FILE}")
    return report

def format_for_telegram(report):
    lines = [f"> Report — {report.get('generated_at', '')[:10]}"]
    for section in report.get("sections", []):
        lines.append(section.get("header", ""))
        lines.append("  " + section.get("body", ""))
    return "\n".join(lines)

if __name__ == "__main__":
    report = generate_report()
    tg_msg = format_for_telegram(report)
    print("\n" + tg_msg)
    print(f"\nReport saved to {REPORT_FILE}")
