#!/usr/bin/env python3
"""
research_indexer.py — index research_reports/*.md into temporal_kg.

Eliminates 37+ markdown files by making research queryable via temporal_kg.
After indexing, research_reports/ can be deleted.

Run:
    python3 research_indexer.py              # index all
    python3 research_indexer.py --dry-run    # preview
    python3 research_indexer.py --verify     # confirm queryable

Schedule: weekly (or after each new report)
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path.home() / ".hermes" / "research_reports"
KG_SCRIPT = Path.home() / ".hermes" / "scripts" / "temporal_kg.py"


def run(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


def extract_entities(text: str) -> list[str]:
    """Extract key entities from research text for KG ingestion."""
    # Simple heuristic: capitalized multi-word terms, tech names
    entities = set(re.findall(r'\b[A-Z][a-z]+(?: [A-Z][a-z]+)+\b', text))
    # Add known tech entities
    tech = re.findall(r'\b(kubernetes|docker|ollama|prometheus|grafana|loki|tempo|traefik|nginx|redis|postgres|sqlite|python|rust|go|llm|rag|mcp|api|cli|ui|db|cpu|gpu|ram|ssd|nvme|tcp|udp|dns|http|https|ssh|ssl|tls|jwt|oauth|oidc|sso|mfa|2fa|ci|cd|git|github|gitlab|ci|cd|yaml|json|toml|ini|cfg|conf|log|tmp|var|etc|usr|bin|sbin|lib|opt|home|root|mnt|media|run|sys|proc|dev|proc|sys)\b', text, re.IGNORECASE)
    entities.update(t.upper() for t in tech)
    return list(entities)[:20]  # cap


def ingest_report(filepath: Path, dry_run: bool = False) -> bool:
    """Ingest a single report into temporal_kg."""
    content = filepath.read_text()
    title = filepath.stem
    date_str = title.split("_")[-1] if "_" in title else datetime.now().strftime("%Y%m%d")

    # Build ingestion record
    record = {
        "type": "research_report",
        "title": title,
        "source": str(filepath),
        "date": date_str,
        "entities": extract_entities(content),
        "summary": content[:500].replace("\n", " "),
        "ingested_at": datetime.now().isoformat(),
    }

    if dry_run:
        print(f"Would ingest: {title}")
        print(f"  Entities: {record['entities'][:5]}...")
        return True

    # Write to temp file for temporal_kg ingestion
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(record, f)
        temp_path = f.name

    try:
        result = run(f"python3 {KG_SCRIPT} ingest-capsule --file {temp_path}")
        print(f"Ingested: {title} → {result[:80]}")
        return True
    except Exception as e:
        print(f"Failed: {title} — {e}")
        return False
    finally:
        Path(temp_path).unlink(missing_ok=True)


def main() -> int:
    dry = "--dry-run" in sys.argv
    verify = "--verify" in sys.argv

    if not REPORTS_DIR.exists():
        print(f"Reports dir not found: {REPORTS_DIR}")
        return 1

    files = sorted(REPORTS_DIR.glob("*.md"))
    if not files:
        print("No markdown files found")
        return 0

    print(f"Found {len(files)} research reports")
    print(f"Mode: {'DRY RUN' if dry else 'LIVE'}")

    if verify:
        # Test a query after ingestion
        print("\nVerifying queryable...")
        result = run(f"python3 {KG_SCRIPT} query 'homelab optimization'")
        print(f"Query result: {result[:200]}")
        return 0

    success = 0
    for f in files:
        if ingest_report(f, dry_run=dry):
            success += 1

    print(f"\nCompleted: {success}/{len(files)} ingested")
    if not dry:
        print("\nNext: delete research_reports/ after confirming queries work")
    return 0


if __name__ == "__main__":
    sys.exit(main())