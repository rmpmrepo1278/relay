#!/usr/bin/env python3
"""hermes_scheduler.py — Unified job scheduler replacing 41 cron entries.

Features:
- Dependency DAG (B before A if A depends on B)
- Healthchecks pings per job
- Concurrency guard (no overlapping runs)
- Error handling with auto-retry
- Bundled and standalone job support
- SLA tracking (did the job run on time?)

Usage:
    python3 hermes_scheduler.py --run    # Run due jobs
    python3 hermes_scheduler.py --daemon # Run continuously
    python3 hermes_scheduler.py --list   # Show job definitions
    python3 hermes_scheduler.py --status # Show last run statuses
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE_FILE = HERMES_HOME / "data" / "scheduler_state.json"
HC_UUIDS_FILE = HERMES_HOME / "scripts" / "hc_uuids.sh"

def _load_healthcheck_uuids() -> dict:
    uuids = {}
    try:
        for line in HC_UUIDS_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("export HC_UUID_"):
                key, _, value = line[len("export "):].partition("=")
                uuids[key] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return uuids



@dataclass
class JobState:
    """Persistent state for a scheduled job."""
    last_status: str = "unknown"
    last_run: str = ""
    elapsed_seconds: float | None = None
    returncode: int | None = None
    error: str | None = None


@dataclass
class JobResult:
    """Result of a single job execution."""
    job: str = ""
    status: str = "unknown"
    elapsed: float = 0
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    reason: str | None = None
globals().update(_load_healthcheck_uuids())

_UID = os.getuid()
_DBUS_ENV = {
    "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{_UID}/bus",
    "XDG_RUNTIME_DIR": f"/run/user/{_UID}",
}


@dataclass
class Schedule:
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month: str = "*"


@dataclass
class Job:
    name: str
    command: str | list[str]
    schedule: Schedule
    timeout: int = 300
    depends_on: list[str] = field(default_factory=list)
    healthchecks_uuid: str = ""
    enabled: bool = True
    description: str = ""
    retry_on_fail: int = 0
    tags: list[str] = field(default_factory=lambda: ["general"])
    env: dict = field(default_factory=dict)
    shell: bool = False  # use shell=True (supports &&, |, $(), ;)

    def matches(self, dt: datetime) -> bool:
        return (self._matches_field(self.schedule.minute, dt.minute) and
                self._matches_field(self.schedule.hour, dt.hour) and
                self._matches_field(self.schedule.day_of_week, dt.weekday()) and
                self._matches_field(self.schedule.day_of_month, dt.day) and
                self._matches_field(self.schedule.month, dt.month))

    def _matches_field(self, pattern: str, value: int) -> bool:
        if pattern == "*":
            return True
        for part in pattern.split(","):
            if "/" in part:
                base, step = part.split("/")
                base_val = int(base) if base != "*" else 0
                if (value - base_val) % int(step) == 0:
                    return True
            elif "-" in part:
                lo, hi = part.split("-")
                if int(lo) <= value <= int(hi):
                    return True
            elif part.isdigit() and int(part) == value:
                return True
        return False


# ---------------------------------------------------------------------------
# Job Definitions — replaces ALL 41 cron entries
# ---------------------------------------------------------------------------

def define_jobs() -> list[Job]:
    h = "/home/rohit/.hermes"
    p = lambda pth: f"python3 {pth}"
    s = lambda pth: f"bash {pth}"
    return [

        # ── 5-min monitoring ──
        # DISABLED 2026-09-03: gateway_guardian is a legacy bare-metal guard (expects ~/.hermes/hermes-agent/.venv + systemd hermes-gateway.service). Gateway now runs as Docker hermes container, guarded by healthcheck + autoheal. See scheduler_state history. Job("gateway_guardian", p(f"{h}/scripts/gateway_guardian.py"),
#             Schedule(minute="*/5"), description="Gateway health recovery", tags=["monitor"]), # legacy-disabled by Relay 2026-09-03
        Job("proactive_engine", p(f"{h}/scripts/proactive_engine.py --once"),
            Schedule(minute="*"), timeout=320, description="State-change-triggered proactive engine", tags=["proactive", "autonomous"],
            env={"PROACTIVE_BRIEFING": "0"}),
        Job("capsule_verify", f"python3 {h}/scripts/capsule_verify.py",
            Schedule(minute="*/15"), timeout=60, description="Verify recent capsule outcomes", tags=["autonomous", "memory"]),
        Job("adaptive_thresholds", f"python3 {h}/scripts/adaptive_thresholds.py --adapt",
            Schedule(minute="0", hour="*/6"), timeout=60, description="Adapt thresholds from ledger history", tags=["autonomous", "learning"]),
        Job("predictive_signals_collect", f"python3 {h}/scripts/predictive_signals.py --collect",
            Schedule(minute="*/5"), timeout=30, description="Collect signals for trend analysis", tags=["autonomous", "predictive"]),
        Job("predictive_signals_analyze", f"python3 {h}/scripts/predictive_signals.py --analyze",
            Schedule(minute="0", hour="*" ), timeout=60, description="Analyze trends and generate predictions", tags=["autonomous", "predictive"]),
        Job("mcp_health_watchdog", f"python3 {h}/scripts/mcp_health_watchdog.py",
            Schedule(minute="*/2"), timeout=60, description="Monitor MCP server health; auto-restart + internet-outage switching", tags=["monitor"]),
        Job("omniroute_mesh_probe", p(f"{h}/scripts/omniroute_mesh_probe.py"),
            Schedule(minute="40", hour="13"), timeout=120, description="Daily OmniRoute free-mesh health probe + Telegram alert", tags=["monitor"]),
        Job('omniroute_usage_rollup', p(f'{h}/scripts/omniroute_usage_rollup.py'),
            Schedule(minute='10', hour='0'), timeout=300, description='Daily OmniRoute usage rollup: call_logs -> daily/hourly_usage_summary', tags=['usage', 'monitor']),
        Job("systemd_fix_watchdog", p(f"{h}/scripts/systemd_fix_watchdog.py"),
            Schedule(minute="*/2"), timeout=60, description="Auto-fix failed systemd units + assert critical containers alive", tags=["monitor"]),
        Job("core_patch", p(f"{h}/scripts/core_patch.py"),
            Schedule(minute="30", hour="4", day_of_week="6"), timeout=3600,
            description="Weekly hermes core rebuild with health-gated rollback",
            tags=["upgrade", "monitor"]),
        Job("health_ingest", f"python3 {h}/scripts/unified_memory.py ingest-health",
            Schedule(minute="*/5"), timeout=15, description="Ingest health metrics to temporal KG", tags=["memory"]),
        Job("duckdns_update", s(f"{h}/scripts/duckdns_update.sh"),
            Schedule(minute="*/5"), timeout=30, description="DuckDNS IP update", tags=["network"]),
        Job("dns_healthcheck", s(f"{h}/scripts/dns_healthcheck.sh"),
            Schedule(minute="*/5"), timeout=15, description="DNS resolution check", tags=["network"]),
        Job("db_integrity_check", p(f"{h}/scripts/db_integrity_check.py"),
            Schedule(minute="17", hour="*/6"), timeout=180, description="SQLite integrity check on all Hermes DBs, alert on corruption", tags=["maintenance", "database"]),
        Job("commitment_executor", p(f"{h}/scripts/commitment_executor.py"),
            Schedule(minute="*/5"), timeout=30, depends_on=["council_speaker"],
            description="Enforce commitments (gated by council approval)", tags=["autonomous"]),
        # ── Transformative experiences: verdict, avatar, governor, radiator ──
        Job("monthly_verdict", p(f"{h}/scripts/state_verdict.py"),
            Schedule(minute="30", hour="13", day_of_month="1"), timeout=120, depends_on=["council_speaker"],
            description="Board audit: 5 members score the month, page top correction", tags=["cognitive", "governance"]),
        Job("backup_restore_test", p(f"{h}/scripts/backup_restore_test.sh"),
            Schedule(minute="0", hour="14", day_of_month="1"), timeout=300, description="Monthly backup restore drill", tags=["maintenance", "backup"]),
        Job("soul_avatar", p(f"{h}/scripts/soul_avatar.py"),
            Schedule(minute="0", hour="13"), timeout=90,
            description="The conscience that argues with you from your own memory", tags=["cognitive", "personal"]),
        Job("override_scan", p(f"{h}/scripts/human_overrides.py --scan"),
            Schedule(minute="*/30"), timeout=60,
            description="Page undelivered human-approval ballots", tags=["governance", "monitor"]),
        Job("weekly_radiator", p(f"{h}/scripts/life_radiator.py"),
            Schedule(minute="15", hour="13", day_of_week="0"), timeout=120,
            description="Weekly second-brain narrative map + back-ref index", tags=["cognitive", "memory"]),
        # ── Agent Parliament: council Speaker proposes, vote-tally finalizes ──
        Job("council_speaker", p(f"{h}/scripts/decision_council.py"),
            Schedule(minute="0", hour="*/4"), timeout=60, description="Propose autonomous actions to the council", tags=["cognitive", "governance"]),
        Job("council_vote_tally", p(f"{h}/scripts/decision_council.py --vote"),
            Schedule(minute="*/5"), timeout=60, description="Tally council votes, finalize approved actions", tags=["cognitive", "governance"]),
        Job("council_member_votes", s(f"{h}/scripts/council_member_votes.sh"),
            Schedule(minute="*/5"), timeout=120, description="All 5 council members cast evidence-based ballots", tags=["cognitive", "governance"]),
        # Telegram reply listener: closes the human 6th-vote loop (reply to a ballot)
        Job("tg_reply_listener", p(f"{h}/scripts/telegram_reply_listener.py"),
            Schedule(minute="*/5"), timeout=45, description="Poll Telegram for the human 6th vote on council ballots", tags=["cognitive", "governance"]),
        # ── Agent kits: sentinel gate, voice, memory, routines, commits, mailbox ──
        Job("sentinel_gate_poll", f"python3 {h}/scripts/sentinel_gate.py --run",
            Schedule(minute="*"), timeout=60, description="Execute approved sentinel actions; page human for pending ones", tags=["governance", "autonomy"]),
        Job("skills_smoke", f"python3 {h}/scripts/skills_lib.py validate 3",
            Schedule(minute="10", hour="*"), timeout=90, description="Smoke-validate newest skills", tags=["skills"]),
        Job("routine_watcher", f"python3 {h}/scripts/routine_watcher.py --run",
            Schedule(minute="*/5"), timeout=90, description="Event-triggered routines (url/file/cmd watchers)", tags=["autonomy", "routines"]),
        Job("commitment_smart", f"python3 {h}/scripts/commitment_smart.py --run",
            Schedule(minute="*/15"), timeout=60, description="Calendar-aware commitment nudges", tags=["personal", "autonomy"]),
        Job("quiet_threads", f"python3 {h}/scripts/quiet_threads.py --run",
            Schedule(minute="0", hour="9"), timeout=60, description="Propose nudges for dropped threads (sentinel-gated)", tags=["personal", "proactive"]),
        Job("meeting_prep", f"python3 {h}/scripts/meeting_prep.py --run",
            Schedule(minute="*/10"), timeout=60, description="10-min-before meeting briefing to Telegram", tags=["personal"]),
        Job("meeting_after", f"python3 {h}/scripts/meeting_prep.py --after",
            Schedule(minute="*/15"), timeout=60, description="Post-meeting action-item capture nudges", tags=["personal"]),
        Job("meeting_conflicts", f"python3 {h}/scripts/meeting_prep.py --conflicts",
            Schedule(minute="0", hour="9,13"), timeout=60, description="Detect + report calendar overlaps", tags=["personal"]),
        Job("agent_mailbox_process", f"python3 {h}/scripts/agent_mailbox.py --process",
            Schedule(minute="*/30"), timeout=60, description="Process Hermes email drops -> orders/commitments", tags=["personal", "email"]),
        Job("brief_feed_daily", f"python3 {h}/scripts/brief_feed.py --send",
            Schedule(minute="30", hour="7"), timeout=90, description="Morning personal brief digest", tags=["personal", "proactive"]),
        Job("housekeeping", f"python3 {h}/scripts/housekeeping.py --run",
            Schedule(minute="15", hour="3"), timeout=60, description="Rotate unbounded jsonl logs + prune", tags=["maintenance"]),
        Job("intent_import", f"python3 {h}/scripts/intent_tracker.py import",
            Schedule(minute="15", hour="8"), timeout=60, description="Unified intent import (personal_tasks + commitments + goals)", tags=["cognitive"]),
        Job("cross_device_sync", f"python3 {h}/scripts/cross_device.py",
            Schedule(minute="30", hour="8"), timeout=60, description="Portable working-state snapshot -> memory repo (visible on any device)", tags=["sync", "memory"]),
        Job("intent_standup", f"python3 {h}/scripts/intent_tracker.py standup",
            Schedule(minute="40", hour="8"), timeout=60, description="Morning priorities digest to Telegram", tags=["personal", "proactive"]),
        Job("daily_review", f"python3 {h}/scripts/daily_review.py --send",
            Schedule(minute="30", hour="21"), timeout=120, description="Nightly self-evaluation + reliability report to Telegram", tags=["cognitive", "daily"]),
        Job("health_checkin", f"python3 {h}/scripts/health_tracker.py nudge",
            Schedule(minute="0", hour="22", day_of_week="0"), timeout=30, description="Weekly health check-in prompt (Sun)", tags=["personal", "health"]),
        Job("social_presence", f"python3 {h}/scripts/social_presence.py digest",
            Schedule(minute="30", hour="11", day_of_week="0"), timeout=60, description="Weekly social presence digest (GitHub activity)", tags=["social"]),
        Job("self_correction", p(f"{h}/scripts/self_correction.py"),
            Schedule(minute="*/10"), timeout=60, description="Verify proactive actions worked", tags=["autonomous"]),
        # Intentional drift: notice recurring topics you ask about & crystallize SOPs
        Job("intentional_drift", p(f"{h}/scripts/intentional_drift.py"),
            Schedule(minute="0", hour="*/2"), timeout=120, description="Crystallize recurring topics into SOPs", tags=["cognitive", "memory"]),
        Job("task_executor", p(f"{h}/scripts/task_executor.py"),
            Schedule(minute="*/15"), timeout=120, description="Execute highest-priority pending task", tags=["autonomous"]),
        Job("hermes_mind", p(f"{h}/scripts/hermes_mind.py"),
            Schedule(minute="*/3"), timeout=120, description="Autonomous brain cycle", tags=["autonomous"]),
        # ── 15-min periodic ──
        # ── Homelab autonomous pipeline ──
        Job("homelab_troubleshooter", p(f"{h}/scripts/homelab_troubleshooter.py"),
            Schedule(minute="*/15"), timeout=120, description="Auto-diagnose + fix failing containers", tags=["homelab"]),
        Job("homelab_discoverer", p(f"{h}/scripts/homelab_discoverer.py"),
            Schedule(minute="0", hour="12,18"), timeout=60, description="Discover new tools/repos/patterns", tags=["homelab"]),
        Job("homelab_evaluator", p(f"{h}/scripts/homelab_evaluator.py"),
            Schedule(minute="30", hour="12,18"), timeout=60, description="Evaluate discovered candidates", tags=["homelab"]),
        Job("homelab_deployer", p(f"{h}/scripts/homelab_deployer.py"),
            Schedule(minute="0", hour="14"), timeout=120, description="Auto-deploy evaluated candidates", tags=["homelab"]),
        Job("homelab_optimizer", p(f"{h}/scripts/homelab_optimizer.py"),
            Schedule(minute="0", hour="10", day_of_week="0"), timeout=120, description="Tune resource limits + retention", tags=["homelab"]),
        Job("career_briefing", p(f"{h}/scripts/career_engine.py --briefing"),
            Schedule(minute="30", hour="12"), timeout=30, description="Extract top career matches for daily digest", tags=["career"]),
        Job("career_coach_daily", p(f"{h}/scripts/career_coach.py daily-prompt"),
            Schedule(minute="5", hour="13"), timeout=60, description="Career coach daily prompt (Telegram)", tags=["career"]),
        Job("career_coach_weekly", p(f"{h}/scripts/career_coach.py weekly-send"),
            Schedule(minute="30", hour="13", day_of_week="0"), timeout=60, description="Career coach weekly review (Telegram)", tags=["career"]),

Job("homelab_reporter", p(f"{h}/scripts/homelab_reporter.py"),
            Schedule(minute="0", hour="13"), timeout=60, description="Generate daily Telegram digest", tags=["homelab"]),

        # ── Hourly ──
        Job("config_snapshot", p(f"{h}/scripts/config_snapshot.py save"),
            Schedule(minute="5"), timeout=30, description="Config snapshot", tags=["backup"]),
        Job("self_modifier", p(f"{h}/scripts/self_modifier.py"),
            Schedule(minute="0"), timeout=60, description="Self modification", tags=["autonomous"]),

        # ── Every 2h ──
        Job("package_tracker", p(f"{h}/scripts/package_tracker.py --daemon"),
            Schedule(minute="0", hour="*/2"), timeout=300, description="Package tracking", tags=["personal"]),
        Job("package_status", s(f"{h}/scripts/package_status_cron.sh"),
            Schedule(minute="0", hour="*/2"), timeout=30, description="Package status check", tags=["personal"]),

        # ── Every 3h (ingestion) ──

        # ── Every 4-6h (knowledge + cognitive) ──
        Job("insight_engine", p(f"{h}/scripts/insight_engine.py"),
            Schedule(minute="30", hour="*/4"), timeout=300, description="Insight engine — pattern mining", tags=["cognitive"]),
        Job("learning_integrator", p(f"{h}/scripts/learning_integrator.py"),
            Schedule(minute="0", hour="*/6"), timeout=300, description="Learning integration", tags=["cognitive"]),
        Job("memory_reflector", p(f"{h}/skills/chief-of-staff/scripts/memory_reflector.py"),
            Schedule(minute="0", hour="*/6"), timeout=60, description="Memory reflection", tags=["memory"]),
        Job("temporal_ingest", f"python3 {h}/scripts/unified_memory.py ingest-capsules",
            Schedule(minute="30", hour="*/6"), timeout=60, description="Temporal KG ingestion", tags=["memory"]),
        Job("gdrive_keepalive", s(f"{h}/scripts/gdrive_keepalive.sh"),
            Schedule(minute="45", hour="*/6"), timeout=120, description="GDrive token refresh", tags=["backup"]),
        Job("dedup", p(f"{h}/scripts/dedup_data.py"),
            Schedule(minute="0", hour="*/6"), timeout=120, description="Data deduplication", tags=["maintenance"]),
        Job("research_discover", p(f"{h}/scripts/research_engine.py discover"),
            Schedule(minute="0"), timeout=120, description="Research discovery", tags=["research"]),

        # ── Daily morning (6-9am) ──
        Job("morning_prep", s(f"{h}/cron/morning_prep.sh"),
            Schedule(minute="0", hour="12"), timeout=180, description="Morning preparation", tags=["daily"],
            healthchecks_uuid=HC_UUID_MORNING_PREP),
        Job("career_daily", p(f"{h}/scripts/career_engine.py"),
            Schedule(minute="0", hour="12"), timeout=120, description="Career daily scan (afternoon, internet guaranteed)", tags=["career"]),
        Job("cos_briefing", p(f"{h}/hermes-agent/scripts/cos_briefing.py"),
            Schedule(minute="30", hour="13"), timeout=120, description="CoS briefing", tags=["daily"]),
        Job("morning_pipeline", s(f"{h}/cron/morning_pipeline.sh"),
            Schedule(minute="0", hour="13"), timeout=300, description="Morning pipeline", tags=["daily"],
            healthchecks_uuid=HC_UUID_MORNING_PIPELINE),
        Job("curious_explorer", p(f"{h}/scripts/curious_explorer.py"),
            Schedule(minute="30", hour="13"), timeout=300, description="Curious exploration", tags=["research"]),
        Job("hermes_digest", p(f"{h}/scripts/hermes_digest.py"),
            Schedule(minute="0", hour="13"), timeout=60, description="Hermes daily digest", tags=["daily"]),

        # ── Daily midday/afternoon ──
        Job("daily_research", p(f"{h}/scripts/daily_research.py"),
            Schedule(minute="0", hour="13"), timeout=180, description="Daily research", tags=["research"]),

        Job("curiosity_engine", p(f"{h}/scripts/curiosity_engine.py"),
            Schedule(minute="0", hour="2"), timeout=600,
            description="Overnight curiosity-gap research + TL;DR into memory",
            tags=["research", "cognitive"]),

        # ── Work sessions ──
        Job("work_session_morning", p(f"{h}/scripts/autonomous_work_session.py --type morning"),
            Schedule(minute="0", hour="12"), timeout=180, tags=["work"]),
        Job("work_session_afternoon", p(f"{h}/scripts/autonomous_work_session.py --type afternoon"),
            Schedule(minute="0", hour="14"), timeout=180, tags=["work"]),
        Job("work_session_evening", p(f"{h}/scripts/autonomous_work_session.py --type evening"),
            Schedule(minute="0", hour="19"), timeout=180, tags=["work"]),

        # ── Evening ──
        Job("evening_briefing", p(f"{h}/hermes-agent/scripts/evening_briefing.py"),
            Schedule(minute="0", hour="20"), timeout=60, description="Evening briefing", tags=["daily"]),

        # ── Nightly (2-3am) ──
        Job("backup_databases", p(f"{h}/scripts/disaster_recovery.py backup"),
            Schedule(minute="0", hour="2"), timeout=2100, description="Nightly database backup via disaster_recovery", tags=["backup"]),
        Job("trip_countdown", p(f"{h}/scripts/trip_planner.py countdown"),
            Schedule(minute="0", hour="2"), timeout=30, tags=["personal"]),

        # ── Maintenance (3am) ──
        Job("logrotate", "bash -c 'if command -v logrotate &>/dev/null; then logrotate -s /home/rohit/.config/logrotate/status /home/rohit/.config/logrotate/hermes-logs.conf 2>/dev/null; fi; bash /home/rohit/.hermes/scripts/rotate_logs.sh'",
            Schedule(minute="0", hour="3"), timeout=60, description="Log rotation", tags=["maintenance"], shell=True),
        Job("docker_prune", "docker image prune -af --filter until=168h",
            Schedule(minute="0", hour="3"), timeout=120, description="Docker image prune", tags=["docker"]),

        # ── Code graph update (every 4h) ──
        Job("crg_update", "cd /home/rohit/.hermes && code-review-graph update 2>/dev/null; cd /home/rohit/projects/career-ops && code-review-graph update 2>/dev/null",
            Schedule(minute="15", hour="*/4"), timeout=300, description="Update code-review-graph knowledge graph", tags=["maintenance"], shell=True),

        # ── Weekly (Sunday) ──
        Job("weekly_review", p(f"{h}/hermes-agent/scripts/weekly_review.py"),
            Schedule(minute="0", hour="17", day_of_week="5"), timeout=180, description="Weekly review", tags=["weekly"]),
                # ── Maintenance ──
        Job("docker_build_prune", s("docker buildx prune -a -f"),
            Schedule(minute="30", hour="3", day_of_week="0"), timeout=120, description="Prune Docker build cache weekly", tags=["maintenance"]),
        Job("postgres_backup", s("docker exec -e PGPASSWORD=metronix-homelab metronix-full-postgres pg_dumpall -U metronix > /home/rohit/.hermes/backups/postgres_$(date +%Y%m%d).sql"),
            Schedule(minute="0", hour="13", day_of_month="1"), timeout=300, description="Monthly PostgreSQL dump backup", tags=["backup"]),

Job("weekly_audit", p(f"{h}/scripts/weekly_audit.py"),
            Schedule(minute="0", hour="13", day_of_week="0"), timeout=180, description="Weekly audit", tags=["weekly"]),
        Job("upgrade_claude", "sudo npm install -g @anthropic-ai/claude-code@latest",
            Schedule(minute="0", hour="14", day_of_week="6"), timeout=120, description="Claude upgrade", tags=["maintenance"]),
        Job("cert_renew", f"docker run --rm -v /home/rohit/services/traefik/certs:/certs -e DUCKDNS_TOKEN=$(cat /home/rohit/.duckdns_token 2>/dev/null) goacme/lego:v3.7.0 --path /certs --email rohitmishra1278@gmail.com --dns duckdns --domains '*.chagulihome.duckdns.org' renew --days 30",
            Schedule(minute="0", hour="4", day_of_week="0"), timeout=120, description="SSL cert renewal", tags=["security"], shell=True),

        # ── SQLite maintenance (Sunday 3am) ──
        Job("sqlite_vacuum", f"sqlite3 {h}/state.db VACUUM; sqlite3 {h}/data/unified_memory.db VACUUM",
            Schedule(minute="0", hour="3", day_of_week="0"), timeout=300, description="SQLite vacuum", tags=["maintenance"], shell=True),

        # ── Self-evolution (Sunday 4am) ──
        Job("self_evolution", p(f"{h}/scripts/self_evolution.py"),
            Schedule(minute="0", hour="4", day_of_week="0"), timeout=300, description="Self-evolving fix strategies", tags=["maintenance"]),
        Job("ace_curate", p(f"{h}/scripts/ace_playbook.py curate"),
            Schedule(minute="30", hour="4", day_of_week="0"), timeout=120, description="Curate ACE playbook candidates", tags=["maintenance"]),

        # ── Monthly ──
        Job("skill_gap", p(f"/home/rohit/projects/career-ops/scripts/skill_gap.py --output /home/rohit/projects/career-ops/output/skill_gap_report.md"),
            Schedule(minute="0", hour="13", day_of_month="1"), timeout=180, description="Skill gap analysis", tags=["career"]),
        Job("auto_followup", p(f"/home/rohit/projects/career-ops/scripts/auto_followup.py --days 14 --send"),
            Schedule(minute="30", hour="10", day_of_week="1"), timeout=120, description="Auto followup", tags=["career"]),
        Job("company_scan", p(f"/home/rohit/projects/career-ops/scripts/scan_companies.py 5 --json"),
            Schedule(minute="0", hour="14", day_of_week="1-5"), timeout=180, description="Company scan (afternoon, internet guaranteed)", tags=["career"]),

        # ── Calibre sync (Sunday 8pm) ──

        # ── Cloud backup sync (3pm daily) ──
        # ── New quality tracking jobs ──
        Job("memory_cleanup", p(f"{h}/scripts/unified_memory.py prune"),
            Schedule(minute="0", hour="4"), timeout=60, description="Memory cleanup", tags=["maintenance"]),
        Job("graphrag_extract", p(f"{h}/scripts/graphrag.py --extract"),
            Schedule(minute="0", hour="*/12"), timeout=120, description="GraphRAG entity extraction", tags=["memory"]),
        Job("gnap_prune", p(f"{h}/scripts/gnap.py --prune"),
            Schedule(minute="30", hour="4"), timeout=30, description="GNAP stale agent cleanup", tags=["autonomous"]),

# DISABLED         # Note: telegram_bot runs in screen session, not scheduled (daemon)

        # ── New: artifact reports after pipeline runs ──
        Job("artifact_report", f"python3 {h}/scripts/artifact_manager.py report",
            Schedule(minute="5", hour="13"), timeout=30, description="Save daily artifact report", tags=["homelab"]),

        # ── New: auto-evaluate digest quality ──
        Job("auto_evaluate", f"python3 {h}/scripts/evaluator.py list",
            Schedule(minute="10", hour="13"), timeout=30, description="Auto-evaluate pipeline output quality", tags=["homelab"]),

        # ── Proactive Intelligence Layer ──
        Job("calendar_cache", p(f"{h}/scripts/calendar_intelligence.py --cache"),
            Schedule(minute="0", hour="*/2"), timeout=30, description="Cache calendar events", tags=["calendar"]),
        Job("calendar_reminder", p(f"{h}/scripts/calendar_intelligence.py --remind"),
            Schedule(minute="*/15"), timeout=15, description="Check for upcoming events", tags=["calendar"]),
        Job("capability_tracker", p(f"{h}/scripts/capability_tracker.py"),
            Schedule(minute="0", hour="*/2"), timeout=30, description="Job usage tracking", tags=["self_improvement"]),
        Job("self_prune", p(f"{h}/scripts/self_prune.py"),
            Schedule(minute="0", hour="5"), timeout=60, description="Auto-disable unused capabilities", tags=["self_improvement"]),
        Job("memory_sync", p(f"{h}/scripts/memory_sync.py"),
            Schedule(minute="*/10"), timeout=30, description="Sync collaborator memory (outage-aware)", tags=["maintenance"]),
        Job("interest_model", p(f"{h}/scripts/proactive/interest_model.py"),
            Schedule(minute="0", hour="*/4"), timeout=120,
            description="Build weighted interest profile from signals", tags=["proactive"]),
        Job("proactive_orchestrator", p(f"{h}/scripts/proactive/proactive_orchestrator.py"),
            Schedule(minute="15", hour="*/4"), timeout=300,
            depends_on=["interest_model"],
            description="Coordinate proactive intelligence and push briefing", tags=["proactive"]),

        # ── Task queue maintenance ──
        Job("clean_task_queue", p(f"{h}/scripts/clean_task_queue.py"),
            Schedule(minute="0", hour="5"), timeout=30,
            description="Archive stale tasks (>7d old)", tags=["maintenance"]),

        # ── Telegram delivery ──
        Job("alerts_delivery", p(f"{h}/scripts/alerts_delivery.py"),
            Schedule(minute="*/3"), timeout=30,
            description="Deliver undelivered alerts to Telegram", tags=["telegram"]),
        Job("persona_morning", p(f"{h}/scripts/persona_engine.py morning"),
            Schedule(minute="0", hour="13"), timeout=30, description="Personality-driven morning check-in", tags=["persona", "telegram"]),
        Job("persona_evening", p(f"{h}/scripts/persona_engine.py evening"),
            Schedule(minute="0", hour="20"), timeout=30, description="Personality-driven evening reflection", tags=["persona", "telegram"]),
        Job("system_doctor", p(f"{h}/scripts/system_doctor.py"),
            Schedule(minute="*/30"), timeout=120, description="Self-healing health checks", tags=["maintenance"]),
        Job("debloat", s(f"{h}/scripts/debloat.sh"),
            Schedule(minute="0", hour="4", day_of_week="0"), timeout=300, description="Weekly debloat sweep", tags=["maintenance"]),
        Job("morning_briefing", p(f"{h}/scripts/morning_briefing.py"),
            Schedule(minute="0", hour="13"), timeout=30,
            description="Daily morning briefing from Relay", tags=["daily"]),
        Job("email_intelligence", p(f"{h}/scripts/email_intelligence.py"),
            Schedule(minute="0", hour="12"), timeout=120,
            description="Email digest — fetch, categorize, surface action items", tags=["email"]),
        Job("email_triage", f"python3 {h}/scripts/email_triage.py",
            Schedule(minute="15", hour="10,12,14,16,18,20"),
            timeout=90, description="Email triage autopilot — propose sentinel-gated auto-replies",
            tags=["email", "autonomy"]),

        # ── Anti-drift: keep docs honest ──
        Job("doc_sync", p(f"{h}/scripts/claude_md_sync.py"),
            Schedule(minute="0", hour="*/6"), timeout=60,
            description="Regenerate CLAUDE.md live sections from reality", tags=["maintenance"]),
        Job("doc_drift_check", p(f"{h}/scripts/doc_drift_check.py"),
            Schedule(minute="0", hour="13"), timeout=60,
            description="Verify CLAUDE.md matches reality; alert on drift", tags=["maintenance"]),

        # ── LLM proxy watchdog ──
        Job("proxy_watchdog", p(f"{h}/scripts/proxy_watchdog.py"),
            Schedule(minute="*/2"), timeout=60,
            description="Monitor LLM proxy health; auto-restart + circuit-breaker resets", tags=["maintenance"]),

         # ── Doc consolidation generators ──
        Job("soul_overlay_gen", p(f"{h}/scripts/soul_overlay_gen.py"),
            Schedule(minute="30", hour="2"), timeout=60,
            description="Regenerate SOUL_*.md domain overlays from live state", tags=["maintenance"]),
        Job("changelog_gen", p(f"{h}/scripts/changelog_gen.py"),
            Schedule(minute="0", hour="3"), timeout=60,
            description="Regenerate CHANGELOG.md from git + capsules", tags=["maintenance"]),
        Job("research_indexer", p(f"{h}/scripts/research_indexer.py"),
            Schedule(minute="0", hour="4", day_of_week="0"), timeout=120,
            description="Index research_reports into temporal_kg (weekly)", tags=["maintenance"]),
    
        # ── NEW AUTONOMOUS CAPABILITIES (added 2026-08-19) ──
        Job("disaster_recovery", p(f"{h}/scripts/disaster_recovery.py"),
            Schedule(minute="0", hour="*/6"), timeout=120, description="Backup state, detect failures, auto-recover", tags=["autonomous", "maintenance"]),
        Job("sync_compose_changes", p(f"{h}/scripts/sync_compose_changes.py"),
            Schedule(minute="*/30"), timeout=60, description="Detect and propagate compose file changes", tags=["autonomous", "homelab"]),
        Job("circuit_breaker", p(f"{h}/scripts/circuit_breaker.py"),
            Schedule(minute="*/5"), timeout=30, description="Protect external calls with circuit breaker", tags=["autonomous", "resilience"]),
        Job("memory_synthesizer", p(f"{h}/scripts/memory_synthesizer.py"),
            Schedule(minute="0", hour="*/4"), timeout=120, description="Cross-database pattern detection and insights", tags=["autonomous", "memory"]),
        Job("knowledge_curator", p(f"{h}/scripts/knowledge_curator.py"),
            Schedule(minute="0", hour="3"), timeout=180, description="Deduplicate, prune, validate knowledge base", tags=["autonomous", "memory"]),
        Job("behavioral_monitor", p(f"{h}/scripts/behavioral_monitor.py"),
            Schedule(minute="*/15"), timeout=60, description="Detect drift in agent behavior patterns", tags=["autonomous", "self_improvement"]),
        Job("skill_acquisition", p(f"{h}/scripts/skill_acquisition.py"),
            Schedule(minute="0", hour="*/6"), timeout=120, description="Learn new capabilities from successful tasks", tags=["autonomous", "self_improvement"]),
        Job("metacognition", p(f"{h}/scripts/metacognition.py"),
            Schedule(minute="0", hour="*/8"), timeout=120, description="Reflect on reasoning and cognitive patterns", tags=["autonomous", "self_improvement"]),
]


# ---------------------------------------------------------------------------
# Scheduler Engine
# ---------------------------------------------------------------------------

class Scheduler:
    def __init__(self, jobs: Optional[list[Job]] = None):
        self.jobs = jobs or define_jobs()
        self.state_path = STATE_FILE
        self._state: dict = self._load_state()
        self._running_jobs: dict[str, subprocess.Popen] = {}

    def run_due(self, now: Optional[datetime] = None) -> list[dict]:
        now = now or datetime.now()
        results = []
        due = [j for j in self.jobs if j.enabled and j.matches(now)]

        # Sort by dependency (no-deps first)
        ordered = self._topological_sort(due)

        for job in ordered:
            # Skip if dependency failed
            deps_ok = all(
                self._state.get(d, {}).get("last_status") != "failed"
                for d in job.depends_on
            )
            if not deps_ok:
                results.append({
                    "job": job.name, "status": "skipped",
                    "reason": f"Dependency failed: {', '.join(job.depends_on)}",
                })
                continue

            result = self._run_job(job)
            results.append(result)

        # Prune state entries for jobs no longer defined
        defined = {j.name for j in self.jobs if j.enabled}
        for key in [k for k in self._state if k not in defined and k not in ("last_run", "jobs_run_count")]:
            self._state.pop(key, None)

        # Update state
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["jobs_run_count"] = self._state.get("jobs_run_count", 0) + len(results)
        self._save_state()
        return results

    def run_job_by_name(self, name: str) -> Optional[dict]:
        for job in self.jobs:
            if job.name == name:
                result = self._run_job(job)
                self._save_state()
                return result
        return None

    def get_status(self) -> dict:
        return {
            "total_jobs": len(self.jobs),
            "enabled_jobs": sum(1 for j in self.jobs if j.enabled),
            "last_run": self._state.get("last_run", ""),
            "jobs_run_count": self._state.get("jobs_run_count", 0),
            "recent_results": {k: v for k, v in self._state.items()
                               if k not in ("last_run", "jobs_run_count")},
        }

    def _run_job(self, job: Job) -> dict:
        if job.name in self._running_jobs:
            return {"job": job.name, "status": "skipped", "reason": "Already running"}

        if job.shell:
            cmd = job.command if isinstance(job.command, str) else " ".join(job.command)
        else:
            cmd = job.command if isinstance(job.command, list) else job.command.split()
        pid = None
        start = time.time()
        healthcheck_started = False

        try:
            self._hc_ping(job.healthchecks_uuid, "start")
            healthcheck_started = True
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, **_DBUS_ENV, **job.env},
                shell=job.shell,
            )
            self._running_jobs[job.name] = proc
            pid = proc.pid
            stdout, stderr = proc.communicate(timeout=job.timeout)
            elapsed = time.time() - start
            success = proc.returncode == 0
            status = "success" if success else "failed"
            self._state[job.name] = asdict(JobState(
                last_status=status,
                last_run=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=round(elapsed, 2),
                returncode=proc.returncode,
            ))
            self._hc_ping(job.healthchecks_uuid, "success" if success else "fail")
            return {"job": job.name, "status": status, "elapsed": round(elapsed, 2),
                    "returncode": proc.returncode,
                    "stdout": stdout.decode(errors="replace")[-500:],
                    "stderr": stderr.decode(errors="replace")[-500:]}
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            elapsed = time.time() - start
            self._state[job.name] = asdict(JobState(
                last_status="timeout",
                last_run=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=round(elapsed, 2),
            ))
            if healthcheck_started:
                self._hc_ping(job.healthchecks_uuid, "fail")
            return {"job": job.name, "status": "timeout", "elapsed": round(elapsed, 2)}
        except Exception as e:
            elapsed = time.time() - start
            self._state[job.name] = asdict(JobState(
                last_status="error",
                last_run=datetime.now(timezone.utc).isoformat(),
                error=str(e),
            ))
            if healthcheck_started:
                self._hc_ping(job.healthchecks_uuid, "fail")
            return {"job": job.name, "status": "error", "error": str(e)}
        finally:
            self._running_jobs.pop(job.name, None)

    def _hc_ping(self, uuid: str, event: str = ""):
        if not uuid:
            return
        try:
            endpoint = {"" : "", "start": "/start", "fail": "/fail"}.get(event, "/fail" if event in ("timeout", "error") else "")
            subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "", f"http://localhost:8004/ping/{uuid}{endpoint}",
                           "-H", "Host: 100.122.58.40:8004"],
                           capture_output=True, timeout=5)
        except Exception:
            pass

    def _topological_sort(self, jobs: list[Job]) -> list[Job]:
        ordered = []
        visited = set()
        def visit(job: Job):
            if job.name in visited:
                return
            visited.add(job.name)
            for dep_name in job.depends_on:
                dep = next((j for j in self.jobs if j.name == dep_name), None)
                if dep:
                    visit(dep)
            ordered.append(job)
        for job in sorted(jobs, key=lambda j: len(j.depends_on)):
            visit(job)
        return ordered

    def _load_state(self) -> dict:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
        return {"last_run": "", "jobs_run_count": 0}

    def _save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self._state, indent=2, default=str))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Unified job scheduler")
    parser.add_argument("--run", action="store_true", help="Run due jobs now")
    parser.add_argument("--daemon", action="store_true", help="Run continuously (1-minute loop)")
    parser.add_argument("--list", action="store_true", help="List all jobs")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--job", type=str, help="Run specific job by name")
    args = parser.parse_args()

    sched = Scheduler()

    if args.run:
        results = sched.run_due()
        for r in results:
            icon = {"success": "✓", "failed": "✗", "skipped": "→", "timeout": "⌛", "error": "!"}.get(r["status"], "?")
            elapsed = r.get("elapsed", 0)
            print(f"  {icon} {r['job']}: {r['status']} ({elapsed}s)")
        if not results:
            print("  No jobs due now")

    elif args.job:
        result = sched.run_job_by_name(args.job)
        if result:
            icon = {"success": "✓", "failed": "✗", "error": "!"}.get(result["status"], "?")
            print(f"{icon} {result['job']}: {result['status']}")
            for key in ("stdout", "stderr", "error"):
                if result.get(key):
                    print(f"  {key}: {result[key][:300]}")
        else:
            print(f"  Job '{args.job}' not found")

    elif args.daemon:
        # Singleton guard: only ONE scheduler daemon may run. Two stray daemons
        # (one systemd, one orphaned) were posting every scheduled report to
        # Telegram twice ("Autonomous Work Session", "Night Report", ...).
        import fcntl
        _lock_path = Path(os.path.expanduser("~/.hermes")) / "state" / "hermes_scheduler.lock"
        _lock_path.parent.mkdir(parents=True, exist_ok=True)
        _lock_fd = open(_lock_path, "w")
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("hermes_scheduler daemon already running (lock held) — exiting", file=sys.stderr)
            sys.exit(0)
        _lock_fd.truncate(0)
        _lock_fd.write(str(os.getpid()) + "\n")
        _lock_fd.flush()
        print("Scheduler daemon starting...")
        while True:
            try:
                results = sched.run_due()
                for r in results:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {r['job']}: {r['status']}")
                    if r["status"] in ("failed", "error", "timeout"):
                        if r.get("error"):
                            print(f"  error: {r['error'][:300]}")
                        if r.get("stderr"):
                            print(f"  stderr: {r['stderr'][:300]}")
                        if r.get("stdout"):
                            print(f"  stdout: {r['stdout'][:300]}")
                time.sleep(60)
            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(60)

    elif args.list:
        print(f"{'Name':35s} {'Schedule':25s} {'Deps':20s} {'Tags'}")
        print("-" * 100)
        for j in sched.jobs:
            s = f"{j.schedule.minute} {j.schedule.hour} * {j.schedule.day_of_week}"
            deps = ",".join(j.depends_on) if j.depends_on else "-"
            print(f"{j.name:35s} {s:25s} {deps:20s} {','.join(j.tags)}")

    elif args.status:
        status = sched.get_status()
        print(f"Total jobs: {status['total_jobs']} ({status['enabled_jobs']} enabled)")
        print(f"Jobs run: {status['jobs_run_count']}")
        print(f"Last run: {status['last_run'] or 'never'}")
        print()
        for name, state in sorted(status.get("recent_results", {}).items()):
            if isinstance(state, dict):
                s = state.get("last_status", "?")
                elapsed = state.get("elapsed_seconds", 0)
                print(f"  [{s.upper():7s}] {name} ({elapsed}s)")


if __name__ == "__main__":
    main()
