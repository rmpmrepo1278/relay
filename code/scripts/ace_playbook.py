#!/usr/bin/env python3
"""
ace_playbook.py — Generator/Reflector/Curator evolution for the autonomous fix system.

Pattern:
  Generator: creates candidate gene/skill updates after each fix
  Reflector: scores candidate quality (would-have-prevented, specificity, generality)
  Curator: approves/denies updates to the gene/skill library

Usage:
  python3 ace_playbook.py generate --task "Container X restart loop" --outcome success --notes "..."
  python3 ace_playbook.py reflect --gene gene_container_crash
  python3 ace_playbook.py curate --pending  # review pending candidates
  python3 ace_playbook.py stats
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
GENES_DIR = HERMES_HOME / "genes"
SKILLS_DIR = HERMES_HOME / "skill_library"
PENDING_DIR = HERMES_HOME / "ace_pending"  # candidate updates awaiting curation
EVOLUTION_LOG = HERMES_HOME / "logs" / "ace_evolution.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] ace: {msg}"
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_LOG, "a") as f:
        f.write(line + "\n")
    print(line, file=sys.stderr)


# ─── Generator ───────────────────────────────────────────────────────────────

def generator(task: str, outcome: str, notes: str = "") -> dict:
    """Generate a candidate gene update from a fix outcome.

    Returns a candidate dict with proposed changes.
    """
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    # Extract issue type from task description
    issue_type = "unknown"
    for itype in ["restart_loop", "healthcheck_fail", "backup_failure",
                  "service_down", "memory_pressure", "dns_resolution",
                  "disk_space", "config_drift", "missing_config",
                  "invalid_script_command"]:
        if itype.replace("_", " ") in task.lower() or itype in task.lower():
            issue_type = itype
            break

    gene_id = f"gene_{issue_type}"

    # Extract L1 commands from notes
    commands = []
    shell_prefixes = ("docker ", "sudo ", "kopia ", "systemctl ", "git ",
                      "bash ", "curl ", "rm ", "mkdir ", "cp ", "mv ")
    for line in notes.splitlines():
        line = line.strip()
        if line.startswith(shell_prefixes):
            commands.append(line)

    candidate = {
        "id": f"cand_{int(time.time())}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gene_id": gene_id,
        "task": task[:200],
        "outcome": outcome,
        "proposed_commands": commands,
        "proposed_strategy": extract_strategy(task, notes, outcome),
        "proposed_validation": extract_validation(task, commands),
        "proposed_anti_patterns": extract_anti_patterns(notes, outcome),
        "status": "pending",
        "quality_score": 0.0,
    }

    # Score immediately
    candidate["quality_score"] = reflector(candidate)
    candidate["reflections"] = generate_reflections(candidate)

    # Save candidate
    cand_file = PENDING_DIR / f"{candidate['id']}.json"
    cand_file.write_text(json.dumps(candidate, indent=2))
    log(f"Generated candidate {candidate['id']} for {gene_id} (quality={candidate['quality_score']:.2f})")
    return candidate


def extract_strategy(task: str, notes: str, outcome: str) -> list[str]:
    """Extract or infer strategy steps from the fix description."""
    steps = []
    # Look for numbered or bulleted steps in notes
    for line in notes.splitlines():
        line = line.strip()
        if re.match(r'^\d+\.\s+', line) or line.startswith("- "):
            steps.append(line.lstrip("0123456789. -"))
    if not steps:
        # Infer from task type
        if "restart" in task.lower() or "crash" in task.lower():
            steps = [
                "Check container logs for OOM or error patterns",
                "Check if dependency containers are running",
                "Restart dependency containers if needed",
                "Restart the crashed container",
                "Verify container health after 30s",
            ]
        elif "backup" in task.lower() or "kopia" in task.lower():
            steps = [
                "Check if kopia repository config exists",
                "Verify kopia binary is accessible",
                "If config missing: reconnect repository",
                "Verify snapshots are being created",
                "Check backup log for errors",
            ]
        elif "dns" in task.lower():
            steps = [
                "Check DuckDNS token validity",
                "Run duckdns_update.sh manually",
                "Verify DNS resolution with dig",
                "Check Pi-hole status",
            ]
        else:
            steps = [
                "Investigate root cause via logs",
                "Apply targeted remediation",
                "Verify fix with post-fix check",
            ]
    return steps


def extract_validation(task: str, commands: list[str]) -> list[str]:
    """Infer validation steps from the fix."""
    validations = []
    if "docker" in task.lower() or any("docker" in c for c in commands):
        validations.append("docker ps --filter name=<container> --format '{{.Status}}'")
    if "kopia" in task.lower() or any("kopia" in c for c in commands):
        validations.append("kopia snapshot list --latest 5")
    if not validations:
        validations = ["Check that the issue described in the task is resolved"]
    return validations


def extract_anti_patterns(notes: str, outcome: str) -> list[str]:
    """Extract anti-patterns — approaches that didn't work."""
    anti = []
    if outcome == "fail":
        if "timeout" in notes.lower():
            anti.append("approaching_with_long_running_command")
        if "permission" in notes.lower():
            anti.append("approach_without_sudo_or_correct_user")
        if "not found" in notes.lower():
            anti.append("assuming_tool_or_path_exists")
        anti.append("repeating_same_approach_without_root_cause_analysis")
    return anti


# ─── Reflector ───────────────────────────────────────────────────────────────

def reflector(candidate: dict) -> float:
    """Score a candidate's quality (0.0 to 1.0).

    Factors:
      - Specificity: does it target a specific issue type? (0-0.3)
      - Generality: can it apply beyond the original target? (0-0.2)
      - Actionability: are the proposed commands concrete? (0.3)
      - Completeness: does it have validation steps? (0.2)
    """
    score = 0.0

    # Specificity
    if candidate.get("gene_id") != "gene_unknown":
        score += 0.3
    else:
        score += 0.1

    # Generality (commands that aren't overly specific to one target)
    commands = candidate.get("proposed_commands", [])
    if commands:
        generic_count = sum(1 for c in commands if not re.search(r'(\d{1,3}\.){3}\d', c))
        score += 0.2 * (generic_count / len(commands))

    # Actionability
    if len(commands) > 0:
        score += min(0.3, len(commands) * 0.1)

    # Completeness
    if candidate.get("proposed_validation"):
        score += 0.2

    return round(score, 2)


def generate_reflections(candidate: dict) -> list[str]:
    """Generate reflective questions about the candidate."""
    reflections = []
    score = candidate.get("quality_score", 0)

    if score < 0.3:
        reflections.append("Low quality candidate — too specific or incomplete")
    if score < 0.5:
        reflections.append("Medium quality — needs more validation or actionable commands")
    if not candidate.get("proposed_commands"):
        reflections.append("No concrete commands extracted — strategy may be too abstract")
    if not candidate.get("proposed_anti_patterns"):
        if candidate.get("outcome") == "fail":
            reflections.append("Failed fix but no anti-patterns identified — risk of repeating")

    return reflections


# ─── Curator ─────────────────────────────────────────────────────────────────

def curate(auto_approve_threshold: float = 0.7, max_to_approve: int = 5):
    """Review pending candidates and approve/reject based on quality score."""
    if not PENDING_DIR.exists():
        log("No pending candidates")
        return []

    candidates = []
    for f in sorted(PENDING_DIR.glob("*.json")):
        try:
            c = json.loads(f.read_text())
            c["_file"] = f
            candidates.append(c)
        except Exception:
            pass

    approved = []
    for c in candidates:
        status = c.get("status")
        if status != "pending":
            continue

        score = c.get("quality_score", 0)
        outcome = c.get("outcome", "")
        gene_id = c.get("gene_id", "")

        if score >= auto_approve_threshold and outcome == "success":
            # Auto-approve high-quality successful fixes
            _apply_candidate(c)
            approved.append(c)
            log(f"Auto-approved candidate {c['id']} (quality={score})")
        elif score >= 0.5 and outcome == "success":
            # Medium quality — flag for manual review
            c["status"] = "review"
            c["_file"].write_text(json.dumps({k:v for k,v in c.items() if k != "_file"}, indent=2))
            log(f"Flagged candidate {c['id']} for review (quality={score})")
        else:
            c["status"] = "rejected"
            c["_file"].write_text(json.dumps({k:v for k,v in c.items() if k != "_file"}, indent=2))
            log(f"Rejected candidate {c['id']} (quality={score})")

        # Clean up approved candidates
        if c.get("_file") and c.get("status") == "applied":
            c["_file"].unlink(missing_ok=True)

    return approved


def _apply_candidate(candidate: dict):
    """Apply a candidate's proposed changes to the gene file."""
    gene_id = candidate.get("gene_id", "")
    if not gene_id:
        return

    gene_file = GENES_DIR / f"{gene_id}.json"

    if not gene_file.exists():
        # Create new gene from candidate
        gene = {
            "version": "1.0",
            "id": gene_id,
            "category": "repair",
            "description": candidate.get("task", ""),
            "signals_match": [gene_id.replace("gene_", "").replace("_", " ")],
            "strategy": candidate.get("proposed_strategy", []),
            "constraints": {
                "max_files": 10,
                "max_runtime_seconds": 600,
                "requires_confirmation": False,
            },
            "validation": candidate.get("proposed_validation", []),
            "anti_patterns": candidate.get("proposed_anti_patterns", []),
            "escalate_if_fails": True,
            "related_genes": [],
            "auto_generated": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "curated_from": candidate.get("id", ""),
        }
    else:
        # Update existing gene
        gene = json.loads(gene_file.read_text())

        # Add new commands/steps to strategy if not already present
        for cmd in candidate.get("proposed_commands", []):
            if cmd not in gene.get("strategy", []):
                gene.setdefault("strategy", []).append(cmd)

        for step in candidate.get("proposed_strategy", []):
            if step not in gene.get("strategy", []):
                gene.setdefault("strategy", []).append(step)

        for ap in candidate.get("proposed_anti_patterns", []):
            if ap not in gene.get("anti_patterns", []):
                gene.setdefault("anti_patterns", []).append(ap)

        gene["updated_at"] = datetime.now(timezone.utc).isoformat()
        gene["curated_from"] = gene.get("curated_from", []) + [candidate.get("id", "")]

    gene_file.write_text(json.dumps(gene, indent=2))
    candidate["status"] = "applied"
    if candidate.get("_file"):
        candidate["_file"].write_text(json.dumps(candidate, indent=2))


def stats():
    """Show curation statistics."""
    print("\nACE Playbook Statistics")
    print("=" * 60)

    if not PENDING_DIR.exists():
        print("  No pending candidates directory")
        return

    all_candidates = list(PENDING_DIR.glob("*.json"))
    if not all_candidates:
        print("  No candidates pending")
        return

    statuses = {"pending": 0, "review": 0, "applied": 0, "rejected": 0}
    for f in all_candidates:
        try:
            c = json.loads(f.read_text())
            s = c.get("status", "pending")
            statuses[s] = statuses.get(s, 0) + 1
        except Exception:
            pass

    for status, count in sorted(statuses.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"  {status}: {count}")

    # Quality score distribution
    scores = []
    for f in all_candidates:
        try:
            c = json.loads(f.read_text())
            scores.append(c.get("quality_score", 0))
        except Exception:
            pass
    if scores:
        print(f"\n  Quality scores: {min(scores):.2f} - {max(scores):.2f} "
              f"(avg {sum(scores)/len(scores):.2f})")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ACE playbook evolution")
    sub = parser.add_parser("curate") if False else parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate candidate from fix outcome")
    gen.add_argument("--task", required=True)
    gen.add_argument("--outcome", required=True, choices=["success", "fail", "partial"])
    gen.add_argument("--notes", default="")

    refl = sub.add_parser("reflect", help="Reflect on a gene's quality")
    refl.add_argument("--gene", required=True)

    cur = sub.add_parser("curate", help="Review and apply pending candidates")
    cur.add_argument("--auto-approve-threshold", type=float, default=0.7)
    cur.add_argument("--max-to-approve", type=int, default=5)

    statsp = sub.add_parser("stats", help="Show curation statistics")

    args = parser.parse_args()

    if args.command == "generate":
        result = generator(args.task, args.outcome, args.notes)
        print(json.dumps(result, indent=2))
    elif args.command == "reflect":
        gene_file = GENES_DIR / f"{args.gene}.json"
        if not gene_file.exists():
            print(f"Gene file not found: {gene_file}")
            sys.exit(1)
        gene = json.loads(gene_file.read_text())
        print(json.dumps(gene, indent=2))
    elif args.command == "curate":
        approved = curate(args.auto_approve_threshold, args.max_to_approve)
        print(f"\nCurated {len(approved)} candidate(s).")
        for c in approved:
            print(f"  Applied: {c.get('gene_id', '?')} from {c.get('id', '?')}")
    elif args.command == "stats":
        stats()
