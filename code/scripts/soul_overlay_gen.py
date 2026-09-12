#!/usr/bin/env python3
"""
soul_overlay_gen.py — regenerate SOUL_*.md domain overlays from live state.

Philosophy: SOUL_*.md files are GENERATED overlays that reflect what's ACTUALLY
active in each domain. The core SOUL.md is hand-written identity; overlays are
runtime mirrors of active skills, configs, commitments, and entities.

Run:
    python3 soul_overlay_gen.py              # regenerate all overlays
    python3 soul_overlay_gen.py --domain infra  # single domain
    python3 soul_overlay_gen.py --dry-run    # preview

Schedule: daily 2:30am via hermes_scheduler (after claude_md_sync)
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

H = Path.home() / ".hermes"
SOUL_CORE = H / "SOUL.md"
OUT_DIR = H

# Domain -> (output filename, generator function)
DOMAINS = {
    "infra": ("SOUL_INFRA.md", "generate_infra"),
    "career": ("SOUL_CAREER.md", "generate_career"),
    "knowledge": ("SOUL_KNOWLEDGE.md", "generate_knowledge"),
    "media": ("SOUL_MEDIA.md", "generate_media"),
    "personal": ("SOUL_PERSONAL.md", "generate_personal"),
    "research": ("SOUL_RESEARCH.md", "generate_research"),
    "travel": ("SOUL_TRAVEL.md", "generate_travel"),
}

MARKER_START = "<!-- SOUL-OVERLAY:{} START -->"
MARKER_END = "<!-- SOUL-OVERLAY:{} END -->"


def run(cmd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"(error: {e})"


# ---------------------------------------------------------------------------
# Domain Generators
# ---------------------------------------------------------------------------

def generate_infra() -> str:
    """Infra overlay: running services, active skills, scheduler jobs, ports."""
    containers = run("docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}' | sort")
    user_svcs = run("systemctl --user list-units --type=service --state=running --no-legend | awk '{print $1}'")
    sys_svcs = run("systemctl list-units --type=service --state=running --no-legend | awk '{print $1}'")
    skills = run("ls -1 ~/.hermes/skills/ 2>/dev/null | wc -l")
    scheduler_jobs = run("grep -c 'Job(' ~/.hermes/scripts/hermes_scheduler.py 2>/dev/null")
    ports = run("docker ps --format '{{.Names}}:{{.Ports}}' | grep -E '0\\.0\\.0\\.0|127\\.0\\.0\\.1' | head -20")

    return f"""## Infra Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current live infra state*.

### 🐳 Running Containers ({len([l for l in containers.splitlines() if l])})
```
{containers if containers else 'none'}
```

### ⚙️ Active Services
**User ({len([l for l in user_svcs.splitlines() if l])}):**
```
{user_svcs if user_svcs else 'none'}
```

**System ({len([l for l in sys_svcs.splitlines() if l])}):**
```
{sys_svcs if sys_svcs else 'none'}
```

### 🎯 Active Skills: {skills}
### ⏰ Scheduler Jobs: {scheduler_jobs}

### 🔌 Exposed Ports
```
{ports if ports else 'none'}
```

### 📋 Operational Notes
- All services behind NPM (ports 80/443) + Pi-hole DNS (`*.home`)
- Telegram-first ops: use Hermes bot for deploy/fix/status
- Zero-cost LLM policy enforced via `unified_cost_guard.py`
- Backup: Kopia to `/mnt/usb/kopia-repo*` (verify with `verify_backups.sh`)
"""


def generate_career() -> str:
    """Career overlay: active commitments, pipeline state, recent activity."""
    commitments = run("python3 ~/.hermes/scripts/commitment_tracker.py status 2>/dev/null | head -30")
    pipeline = run("ls -la ~/.hermes/career_pipeline/ 2>/dev/null | head -10")
    recent_apps = run("find ~/.hermes/career_apps -name '*.json' -mtime -7 2>/dev/null | wc -l")

    return f"""## Career Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current career ops state*.

### 📋 Active Commitments
```
{commitments if commitments else 'none'}
```

### 🔄 Pipeline State
```
{pipeline if pipeline else 'no active pipeline'}
```

### 📊 Recent Activity (7 days)
- Applications processed: {recent_apps}
- Resume format: bullet-point summary, 15+ tech skills, quantified achievements
- Career-ops plugin: intercepts job URLs on Telegram, runs `auto_pipeline.py`

### 🎯 Current Focus
- Active job search via career_ops_pipeline (Telegram → auto_pipeline.py)
- Commitment tracking: `commitment_tracker.py` + `commitment_executor.py` (5min cron)
- Self-correction: `self_correction.py` verifies actions (10min cron)
"""


def generate_knowledge() -> str:
    """Knowledge overlay: temporal KG stats, claudemem, research index."""
    kg_stats = run("python3 ~/.hermes/scripts/temporal_kg.py stats 2>/dev/null")
    claudemem = run("sqlite3 ~/.hermes/claudemem.db 'select count(*) from memories' 2>/dev/null")
    research = run("find ~/.hermes/research_reports -name '*.md' 2>/dev/null | wc -l")

    return f"""## Knowledge Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current knowledge state*.

### 🧠 Temporal Knowledge Graph
```
{kg_stats if kg_stats else 'run: python3 ~/.hermes/scripts/temporal_kg.py stats'}
```

### 💾 ClaudeMem DB
- Memories: {claudemem if claudemem else 'query failed'}

### 📚 Research Index
- Reports in `~/.hermes/research_reports/`: {research}
- Use `temporal_kg.py query "topic"` instead of browsing files

### 🔍 Query Patterns
```bash
# Cross-domain patterns
python3 ~/.hermes/scripts/temporal_kg.py query "paperless failures"
python3 ~/.hermes/scripts/temporal_kg.py query "docker restart loops"

# Entity evolution
python3 ~/.hermes/scripts/temporal_kg.py entity "Paperless"
```
"""


def generate_media() -> str:
    """Media overlay: active downloads, library status."""
    return f"""## Media Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current media state*.

### 📚 Calibre-Web
- Library: `~/.hermes/calibre_library` (synced to OneDrive via `sync_calibre_to_onedrive.sh`)
- Sync: daily 8pm cron

### 🎬 Immich
- Photos: `docker exec immich_server` (port 2283)
- Auto-backup: camera uploads enabled

### 📺 Other
- Jellyfin: not deployed
- Plex: not deployed
- YouTube pipeline: `youtube_pipeline.py` (Wed 2pm cron)
"""


def generate_personal() -> str:
    """Personal overlay: habits, health, finance snapshot."""
    habits = run("python3 ~/.hermes/scripts/habit_gamification/check.py 2>/dev/null | head -20")
    health = run("cat ~/.hermes/data/health_latest.json 2>/dev/null | head -30")

    return f"""## Personal Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current personal state*.

### 🏃 Habits & Gamification
```
{habits if habits else 'run: python3 ~/.hermes/scripts/habit_gamification/check.py'}
```

### 💪 Health Dashboard (latest)
```
{health if health else 'run: python3 ~/.hermes/scripts/health_dashboard.py'}
```

### 💰 Finance
- Bill reminders: 7am cron (`cos_briefing.py`)
- Expense tracking: manual entry via Telegram

### 📅 Calendar
- Morning prep: 6am (`morning_prep.sh`)
- Career scan: 8am (`morning_pipeline.sh`)
- Evening briefing: 8pm (`evening_briefing.py`)
"""


def generate_research() -> str:
    """Research overlay: curious explorer topics, paper cache, active queries."""
    explorer = run("cat ~/.hermes/state/curious_seen.json 2>/dev/null | jq '. | length' 2>/dev/null")
    papers = run("find ~/.hermes/research_papers -name '*.pdf' 2>/dev/null | wc -l")

    return f"""## Research Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current research state*.

### 🔬 Curious Explorer
- Topics seen: {explorer if explorer else '0'}
- Runs: daily 9am (`curious_explorer.py`)
- Sources: arXiv, HN, GitHub trending, SearXNG

### 📄 Paper Cache
- PDFs in `~/.hermes/research_papers/`: {papers}
- Ingested into temporal_kg via `ingest-capsules` (6h cron)

### 🔍 Active Queries
```bash
python3 ~/.hermes/scripts/temporal_kg.py query "agent memory"
python3 ~/.hermes/scripts/temporal_kg.py query "local LLM inference"
python3 ~/.hermes/scripts/research_desk.py --topic "topic"
```
"""


def generate_travel() -> str:
    """Travel overlay: upcoming trips, packing lists, docs."""
    trips = run("cat ~/.hermes/travel/upcoming.json 2>/dev/null | jq -r '.[] | \"\\(.date) \\(.dest) \\(.purpose)\"' 2>/dev/null")

    return f"""## Travel Domain Overlay (auto-generated {datetime.now():%Y-%m-%d %H:%M})

**Core identity:** See `SOUL.md` — this overlay reflects *current travel state*.

### ✈️ Upcoming Trips
```
{trips if trips else 'none scheduled'}
```

### 📋 Packing / Docs
- Master packing list: `~/.hermes/travel/packing_list.md`
- Travel docs: `~/.hermes/travel/docs/` (passports, visas, insurance)
- Trip organizer: `~/My Drive/Travel/Trip Organizer/`

### 🎯 Travel Preferences
- Optimize for: direct flights, carry-on only, timezone overlap with work
- Base: Bellevue, WA (UTC-7/8)
- Preferred airports: SEA, PDX
"""


GENERATORS = {
    "infra": generate_infra,
    "career": generate_career,
    "knowledge": generate_knowledge,
    "media": generate_media,
    "personal": generate_personal,
    "research": generate_research,
    "travel": generate_travel,
}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_overlay(domain: str, dry_run: bool = False) -> bool:
    gen = GENERATORS[domain]
    filename, _ = DOMAINS[domain]
    path = OUT_DIR / filename

    body = gen()
    start_marker = MARKER_START.format(domain.upper())
    end_marker = MARKER_END.format(domain.upper())
    full_content = f"{start_marker}\n{body}\n{end_marker}"

    if dry_run:
        print(f"=== {filename} (dry-run) ===")
        print(full_content[:500] + ("..." if len(full_content) > 500 else ""))
        print()
        return True

    if path.exists():
        existing = path.read_text()
        if start_marker in existing:
            # Replace between markers
            import re
            pattern = rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}"
            new_text = re.sub(pattern, full_content, existing, flags=re.DOTALL)
            if new_text == existing:
                print(f"  {filename}: no change")
                return True
            path.write_text(new_text)
            print(f"  {filename}: updated")
            return True

    # First time: append to file (or create with core SOUL reference)
    header = f"""# {domain.upper()} Domain Overlay
<!-- Auto-generated from live state. DO NOT EDIT BETWEEN MARKERS. -->
<!-- Core identity in SOUL.md -->

"""
    path.write_text(header + full_content + "\n")
    print(f"  {filename}: created")
    return True


def main():
    dry = "--dry-run" in sys.argv
    single = None
    for arg in sys.argv[1:]:
        if arg in DOMAINS:
            single = arg

    targets = [single] if single else list(DOMAINS.keys())

    print(f"Generating SOUL overlays: {', '.join(targets)}")
    for d in targets:
        write_overlay(d, dry_run=dry)

    if not dry:
        print("Done. Overlays written to ~/.hermes/")


if __name__ == "__main__":
    main()
