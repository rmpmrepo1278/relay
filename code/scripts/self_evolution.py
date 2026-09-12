#!/usr/bin/env python3
"""
self_evolution.py — Self-evolving autonomous fix system.

Runs weekly (Sunday 4am via cron). Analyzes:
  1. Reflexion memory for recurring failure patterns
  2. Capsule outcomes for gene success/failure rates
  3. Successful L2 Claude fixes for extractable L1 strategies
  4. Auto-generates new gene templates for discovered patterns
  5. Updates existing gene parameters based on outcomes
  6. Extracts L1 bash remediation scripts from successful L2 fixes

Usage:
  python3 self_evolution.py [--dry-run] [--analyze-only] [--stats]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
GENES_DIR = HERMES_HOME / "genes"
CAPSULES_DIR = HERMES_HOME / "capsules"
SKILLS_DIR = HERMES_HOME / "skill_library"
LOG_DIR = HERMES_HOME / "logs"
REFLEXION_FILE = HERMES_HOME / "reflexion_memory.jsonl"
OUTCOMES_FILE = CAPSULES_DIR / "outcomes.jsonl"
EVOLUTION_LOG = LOG_DIR / "self_evolution.log"

# Patterns to mine from logs for new failure types
LOG_PATTERNS = [
    (r"connection refused.*(\d{4})", "port_dependency"),
    (r"out of memory|oom kill|oom_killed", "memory_oom"),
    (r"permission denied.*(/[\w/]+)", "permission_error"),
    (r"no such file or directory.*(/[\w/]+)", "missing_file"),
    (r"command not found|not a valid command|snapshot prune", "invalid_command"),
    (r"repository not connected|repository is not connected", "repo_not_connected"),
    (r"timeout after \d+s|timed out", "timeout"),
    (r"ssl.*expired|certificate.*expired", "ssl_expired"),
    (r"rate limit|429|too many requests", "rate_limited"),
    (r"health.*unhealthy|healthcheck.*fail", "healthcheck_fail"),
]


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] self-evolve: {msg}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_LOG, "a") as f:
        f.write(line + "\n")
    print(line, file=sys.stderr)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return items


def load_reflexions() -> list[dict]:
    return load_jsonl(REFLEXION_FILE)


def load_outcomes() -> list[dict]:
    return load_jsonl(OUTCOMES_FILE)


def gene_success_rates() -> dict[str, dict]:
    """Compute success rate per gene type from capsule outcomes."""
    outcomes = load_outcomes()
    by_gene: dict[str, list[dict]] = defaultdict(list)
    for o in outcomes:
        gene_id = o.get("gene_id", "")
        if gene_id:
            by_gene[gene_id].append(o)

    rates = {}
    for gene_id, records in by_gene.items():
        successes = sum(1 for r in records if r.get("outcome") == "success")
        failures = sum(1 for r in records if r.get("outcome") == "fail")
        total = len(records)
        rates[gene_id] = {
            "successes": successes,
            "failures": failures,
            "total": total,
            "rate": successes / total if total > 0 else 0.0,
        }
    return rates


def find_recurring_failures(reflexions: list[dict]) -> list[dict]:
    """Find patterns where the same issue type + target failed repeatedly."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in reflexions:
        gene_id = r.get("gene_id", "unknown")
        target = r.get("target", "unknown")
        key = f"{gene_id}:{target}"
        by_key[key].append(r)

    recurring = []
    for key, records in by_key.items():
        failures = sum(1 for r in records if r.get("outcome") == "fail")
        total = len(records)
        if failures >= 2 and failures / total >= 0.5:
            # This approach keeps failing — need a different gene strategy
            latest = records[-1]
            recurring.append({
                "key": key,
                "failures": failures,
                "total": total,
                "rate": failures / total,
                "last_reflection": latest.get("reflection", ""),
                "gene_id": latest.get("gene_id", ""),
                "target": latest.get("target", ""),
            })
    return recurring


def find_successful_l2_fixes(reflexions: list[dict]) -> list[dict]:
    """Find L2 Claude fixes that succeeded — candidates for L1 extraction."""
    successful = []
    for r in reflexions:
        if r.get("outcome") == "success":
            # Check if it was delegated (L2) vs a simple L1 bash fix
            reflection = r.get("reflection", "")
            if "status=completed" in reflection and "delegate" not in reflection.lower():
                # Likely an L1 fix — skip
                continue
            if "status=completed" in reflection:
                successful.append(r)
    return successful


def extract_l1_commands(reflection: str) -> list[str]:
    """Extract shell commands from a successful L2 fix reflection.

    Looks for lines that look like shell commands (start with common tools).
    """
    commands = []
    shell_prefixes = ("docker ", "sudo ", "kopia ", "systemctl ", "git ",
                      "bash ", "curl ", "rm ", "mkdir ", "cp ", "mv ")
    for line in reflection.splitlines():
        line = line.strip()
        if line.startswith(shell_prefixes):
            commands.append(line)
    return commands


def create_gene_template(issue_type: str, target: str | None = None,
                         strategy_steps: list[str] | None = None) -> dict:
    """Generate a new gene template JSON structure."""
    gene_id = f"gene_{issue_type}"
    return {
        "version": "1.0",
        "id": gene_id,
        "category": "repair",
        "description": f"Auto-generated gene for {issue_type} failures. "
                       f"Target: {target or 'any'}.",
        "signals_match": [issue_type.replace("_", " "), issue_type],
        "strategy": strategy_steps or [
            f"Check {issue_type} status",
            "Apply known remediation",
            "Verify fix",
        ],
        "constraints": {
            "max_files": 10,
            "max_runtime_seconds": 600,
            "requires_confirmation": False,
        },
        "validation": [
            f"Check {issue_type} is resolved",
        ],
        "anti_patterns": [
            f"repeating_same_approach_for_{issue_type}",
        ],
        "escalate_if_fails": True,
        "related_genes": [],
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def mine_logs_for_patterns() -> list[dict]:
    """Scan system and application logs for failure patterns not covered by genes."""
    patterns_found = []
    log_files = [
        HERMES_HOME / "logs" / "kopia_backup.log",
        HERMES_HOME / "logs" / "autonomous_fixer.log",
    ]

    for log_path in log_files:
        if not log_path.exists():
            continue
        try:
            content = log_path.read_text(errors="replace")
            for pattern, label in LOG_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    # Check if this pattern is already in a gene
                    gene_id = f"gene_{label}"
                    gene_file = GENES_DIR / f"{label}.json"
                    if not gene_file.exists():
                        patterns_found.append({
                            "pattern": pattern,
                            "label": label,
                            "match_count": len(matches),
                            "matches": matches[:5],
                            "log_file": str(log_path),
                        })
        except Exception:
            pass

    return patterns_found


def update_gene_from_outcomes(gene_file: Path, rates: dict) -> bool:
    """Update an existing gene's strategies based on capsule outcomes."""
    if not gene_file.exists():
        return False

    try:
        gene = json.loads(gene_file.read_text())
        gene_id = gene.get("id", "")
        rate_info = rates.get(gene_id, {})

        if rate_info.get("total", 0) == 0:
            return False  # No data

        rate = rate_info["rate"]
        if rate < 0.5:
            # This gene is failing frequently — flag for review
            gene["notes"] = gene.get("notes", "")
            warning = f"\n[EVOLUTION] Low success rate: {rate:.0%} ({rate_info['successes']}/{rate_info['total']}). "
            warning += "Consider alternative strategies or new anti-patterns."
            if "EVOLUTION" not in gene.get("notes", ""):
                gene["notes"] = (gene.get("notes", "") + warning).strip()
            else:
                # Update existing warning
                gene["notes"] = re.sub(
                    r'\[EVOLUTION\].*?(?=\n\[|$)',
                    warning.strip(),
                    gene["notes"],
                    flags=re.DOTALL,
                )
            gene_file.write_text(json.dumps(gene, indent=2))
            log(f"Updated gene {gene_id}: success rate {rate:.0%} — warnings added")
            return True
        elif rate > 0.8:
            # This gene is working well — reinforce it
            if gene.get("notes"):
                gene["notes"] += f"\n[EVOLUTION] High success rate: {rate:.0%}. Strategy validated."
            else:
                gene["notes"] = f"[EVOLUTION] High success rate: {rate:.0%}. Strategy validated."
            gene_file.write_text(json.dumps(gene, indent=2))
            log(f"Gene {gene_id}: success rate {rate:.0%} — validated")
            return True
    except Exception as e:
        log(f"Failed to update gene {gene_file.name}: {e}")
    return False


def auto_generate_genes(recurring: list[dict], patterns: list[dict]) -> list[Path]:
    """Create new gene templates for discovered failure patterns."""
    new_genes = []
    for rec in recurring:
        gene_id = rec["gene_id"]
        gene_file = GENES_DIR / f"{gene_id}.json"
        if gene_file.exists():
            continue  # Already have a gene for this

        # Extract strategy from the reflection
        reflection = rec.get("last_reflection", "")
        strategy = extract_l1_commands(reflection) or [
            f"Investigate {rec['target']} for {gene_id}",
            "Check logs and system state",
            "Apply targeted fix based on root cause",
            "Verify fix with post-fix check",
        ]

        gene = create_gene_template(gene_id.replace("gene_", ""), rec["target"], strategy)
        gene_file.write_text(json.dumps(gene, indent=2))
        new_genes.append(gene_file)
        log(f"New gene created: {gene_file.name} (failure rate: {rec['rate']:.0%})")

    for pattern in patterns:
        gene_file = GENES_DIR / f"{pattern['label']}.json"
        if gene_file.exists():
            continue

        gene = create_gene_template(
            pattern["label"],
            None,
            [
                f"Check for {pattern['label']} pattern",
                f"Found in {pattern['log_file']}: {pattern['match_count']} occurrences",
                "Apply remediation based on pattern type",
                "Verify fix",
            ],
        )
        gene_file.write_text(json.dumps(gene, indent=2))
        new_genes.append(gene_file)
        log(f"New gene from log mining: {gene_file.name} (pattern: {pattern['pattern']})")

    return new_genes


def extract_l1_skills(successful_l2: list[dict]) -> list[Path]:
    """Extract L1 bash remediation scripts from successful L2 Claude fixes."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    new_skills = []

    for fix in successful_l2:
        reflection = fix.get("reflection", "")
        gene_id = fix.get("gene_id", "unknown")
        target = fix.get("target", "unknown")

        commands = extract_l1_commands(reflection)
        if not commands:
            continue

        # Create a skill file from the successful commands
        skill_name = f"{gene_id}_{target}_{int(time.time())}"
        skill_file = SKILLS_DIR / f"{skill_name}.sh"
        if skill_file.exists():
            continue

        script_content = f"""#!/bin/bash
# Auto-extracted L1 skill from successful L2 Claude fix
# Gene: {gene_id}
# Target: {target}
# Date: {fix.get('timestamp', 'unknown')}
# Reflection: {reflection[:200]}

set -euo pipefail

"""
        for cmd in commands:
            script_content += f"{cmd}\n"

        skill_file.write_text(script_content)
        os.chmod(skill_file, 0o755)
        new_skills.append(skill_file)
        log(f"Extracted L1 skill: {skill_file.name} (from {gene_id} fix)")

    return new_skills


def run(dry_run: bool = False, analyze_only: bool = False):
    log("=" * 60)
    log(f"Self-evolution cycle starting (dry_run={dry_run})")

    reflexions = load_reflexions()
    rates = gene_success_rates()

    log(f"Loaded {len(reflexions)} reflexions, {len(rates)} gene types with outcomes")

    # 1. Update existing genes based on outcomes
    updated_genes = []
    for gene_file in GENES_DIR.glob("*.json"):
        if gene_file.name.startswith("_"):
            continue
        if update_gene_from_outcomes(gene_file, rates):
            updated_genes.append(gene_file.name)

    log(f"Updated {len(updated_genes)} gene(s): {updated_genes}")

    # 2. Find recurring failures (patterns where fixes keep failing)
    recurring = find_recurring_failures(reflexions)
    log(f"Found {len(recurring)} recurring failure pattern(s)")

    # 3. Mine logs for new failure patterns
    patterns = mine_logs_for_patterns()
    log(f"Found {len(patterns)} new pattern(s) from log mining")

    # 4. Auto-generate new genes
    if not dry_run and not analyze_only:
        new_genes = auto_generate_genes(recurring, patterns)
        log(f"Created {len(new_genes)} new gene(s)")
    else:
        new_genes = []

    # 5. Extract L1 skills from successful L2 fixes
    successful_l2 = find_successful_l2_fixes(reflexions)
    log(f"Found {len(successful_l2)} successful L2 fix(es) for skill extraction")

    if not dry_run and not analyze_only:
        new_skills = extract_l1_skills(successful_l2)
        log(f"Extracted {len(new_skills)} new L1 skill(s)")
    else:
        new_skills = []

    # 6. Summary
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "reflexions_loaded": len(reflexions),
        "genes_with_outcomes": len(rates),
        "genes_updated": len(updated_genes),
        "recurring_failures": len(recurring),
        "log_patterns_found": len(patterns),
        "new_genes_created": len(new_genes),
        "successful_l2_fixes": len(successful_l2),
        "new_skills_extracted": len(new_skills),
    }

    if not dry_run and not analyze_only:
        summary_file = DATA_DIR / "evolution_summary.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary, indent=2))

    log(f"Summary: {json.dumps(summary, indent=2)}")
    log("Self-evolution cycle complete")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Self-evolving autonomous fix system")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze but don't make changes")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Only analyze, don't generate genes or skills")
    parser.add_argument("--stats", action="store_true",
                        help="Show gene success rate statistics")
    args = parser.parse_args()

    if args.stats:
        rates = gene_success_rates()
        print("\nGene Success Rates:")
        print("-" * 60)
        for gene_id, info in sorted(rates.items(), key=lambda x: x[1]["rate"]):
            print(f"  {gene_id}: {info['rate']:.0%} "
                  f"({info['successes']}/{info['total']} success, "
                  f"{info['failures']} fail)")
        sys.exit(0)

    summary = run(dry_run=args.dry_run, analyze_only=args.analyze_only)
    if args.dry_run or args.analyze_only:
        print(json.dumps(summary, indent=2))
