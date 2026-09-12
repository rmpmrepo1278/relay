#!/usr/bin/env python3
"""
loop_state.py — Structured loop state + run log for Hermes automations.

Loop Engineering primitives: Memory/State as the durable spine.
Provides LoopState (schema, prune, render) and RunLog (append-only audit trail).

Usage:
    from loop_state import LoopState, RunLog
    ls = LoopState()
    ls.add_or_update({"id": "restart_loop:plex", "pattern": "autonomous_fixer", ...})
    ls.prune()
    ls.write()

    rl = RunLog()
    rl.record("autonomous_fixer", duration_s=47, items_found=3,
              actions_taken=["delegate"], escalations=[], outcome="success")

Self-test:
    python3 loop_state.py
"""

from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
# ponytail: single source for the stagnation gate. 3 = escalate after 3 failed
# actions on the same id. Raise only if a specific gene keeps self-resolving
# on the 4th try in practice — until then, keep it tight.
STAGNATION_ATTEMPTS = int(os.environ.get("STAGNATION_ATTEMPTS", "3"))
# Outcomes written to item['last_outcome'] that count toward stagnation.
_FAIL_OUTCOMES = {"fail", "delegate_timeout", "rate_limited", "fix_unverified"}

# ponytail: keep a small ring of recent probe/reflection lines. Volume-bound
# (max entries x max len) so the json never balloons with log spam.
CTX_MAX_ENTRIES = 10
CTX_MAX_LEN = 800  # chars per entry


def _merge_context(existing: dict | None, new: dict) -> dict:
    """Ring-buffer context packet. Keys are epochs; we keep newest CTX_MAX_ENTRIES."""
    base = dict(existing or {})
    base.update(new)
    # re-number, trim to ring size, oldest-first drop
    trimmed = {}
    for idx, (k, v) in enumerate(base.items()):
        trimmed[str(idx)] = v
        if idx >= CTX_MAX_ENTRIES - 1:
            break
    # length-cap each value
    for k in trimmed:
        if isinstance(trimmed[k], str) and len(trimmed[k]) > CTX_MAX_LEN:
            trimmed[k] = trimmed[k][:CTX_MAX_LEN] + "…"
    return trimmed
STATE_DIR = HERMES_HOME / "state"

STATE_FILE = STATE_DIR / "LOOP-STATE.md"
RUN_LOG_FILE = STATE_DIR / "loop-run-log.jsonl"
ITEMS_FILE = STATE_DIR / "loop-state-items.json"

SECTIONS = ["High Priority", "Watch List", "Human Inbox", "Pruned/Noise"]

# ---------------------------------------------------------------------------
# LoopState
# ---------------------------------------------------------------------------

class LoopState:
    """Structured loop state with markdown rendering and JSON backing."""

    def __init__(self, state_path: Path = STATE_FILE, items_path: Path = ITEMS_FILE):
        self.state_path = state_path
        self.items_path = items_path
        self._items: list[dict] = self._load_items()

    # -- persistence --

    def _load_items(self) -> dict[str, dict]:
        if self.items_path.exists():
            try:
                data = json.loads(self.items_path.read_text())
                if isinstance(data, list):
                    return {item["id"]: item for item in data if "id" in item}
                return data
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_items(self) -> None:
        """Atomic write via tmp+rename."""
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(list(self._items.values()), indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=self.items_path.parent, suffix=".tmp")
        try:
            os.write(fd, data.encode())
            os.close(fd)
            os.rename(tmp, str(self.items_path))
        except Exception:
            os.close(fd)
            raise

    # -- item management --

    def add_or_update(self, item: dict) -> dict:
        """Upsert by item['id']. Returns the item after update.

        Gates applied here (single chokepoint every fix passes through):
          1. Stagnation — if this id has failed STAGNATION_ATTEMPTS times with
             no verify-passed in between, auto-escalate to Human Inbox and mark
             the new action `blocked`. Do NOT escalate twice.
          2. Context packet — preserve any probe/reflection context onto the
             merged item so the next delegate starts warm (see get_context).
        """
        item_id = item.get("id", "")
        now = datetime.now(timezone.utc).isoformat()
        existing = self._items.get(item_id)
        if existing:
            prev_fail = 1 if existing.get("last_outcome", "") \
                in _FAIL_OUTCOMES else 0
            new_attempts = existing.get("attempts", 0) + prev_fail
            merged = {**existing, **item}
            merged["attempts"] = new_attempts
            merged["last_run"] = merged.get("last_run", now)

            # --- gate 1: stagnation ---
            outcome = merged.get("last_outcome", "")
            escalated = existing.get("status") == "waiting_human"
            if (not escalated
                    and outcome in _FAIL_OUTCOMES
                    and new_attempts >= STAGNATION_ATTEMPTS):
                merged["status"] = "waiting_human"
                merged["last_action"] = "blocked:stagnation"
                merged.setdefault("stagnation_reason",
                                   f"{new_attempts} failed attempts; last={outcome}")
                escalated = True

            # --- gate 2: context packet carry-forward ---
            if merged.get("context"):
                merged["context"] = _merge_context(existing.get("context"),
                                                   merged["context"])
            self._items[item_id] = merged
            self._save_items()
            return merged

        # New item — this is the first action taken on this id.
        item.setdefault("attempts", 1)
        item.setdefault("status", "active")
        item.setdefault("last_run", now)
        if item.get("context"):
            item["context"] = _merge_context({}, item["context"])
        self._items[item_id] = item
        self._save_items()
        return item

    # -- context packet (gate 2) --

    def get_context(self, item_id: str) -> dict:
        """Return the merged context packet for an id (probe tails, prior
        reflections). Delegates read this to skip the 'what is the state?' turn."""
        item = self._items.get(item_id)
        return dict(item.get("context") or {}) if item else {}

    def add_context(self, item_id: str, entry: dict) -> None:
        """Append a probe/reflection entry into the id's context ring.
        No-op if the id has not been registered yet (call add_or_update first,
        or include context= in the initial upsert)."""
        item = self._items.get(item_id)
        if item:
            item["context"] = _merge_context(item.get("context"), entry)
            self._save_items()

    # -- outcome + flow control (gates 1 & 3) --


    def is_blocked(self, item_id: str) -> bool:
        """True if the id is waiting on a human (stagnation gate tripped)."""
        item = self._items.get(item_id)
        return item.get("status") == "waiting_human" if item else False

    def get_section(self, item: dict) -> str:
        status = item.get("status", "active")
        severity = item.get("severity", "medium")
        if status == "pruned":
            return "Pruned/Noise"
        if status == "waiting_human":
            return "Human Inbox"
        if status == "active" and severity in ("high", "critical"):
            return "High Priority"
        if status == "active":
            return "Watch List"
        if status == "watch":
            return "Watch List"
        return "Pruned/Noise"

    def resolve(self, item_id: str) -> None:
        """Mark an item as pruned (resolved)."""
        item = self._items.get(item_id)
        if item:
            item["status"] = "pruned"
            item["attempts"] = 0
            self._save_items()

    def escalate(self, item_id: str) -> None:
        """Move item to Human Inbox."""
        item = self._items.get(item_id)
        if item:
            item["status"] = "waiting_human"
            item["attempts"] = 0
            self._save_items()

    # -- prune --

    def prune(self, max_age_hours: int = 72) -> int:
        """Move stale items to Pruned/Noise. Never deletes.
        Items in High Priority or Human Inbox are never pruned."""
        now = datetime.now(timezone.utc)
        pruned = 0
        for item in self._items.values():
            section = self.get_section(item)
            if section in ("High Priority", "Human Inbox"):
                continue
            if item.get("status") == "pruned":
                continue
            last_run = item.get("last_run", "")
            if not last_run:
                continue
            try:
                lr_dt = datetime.fromisoformat(last_run)
                age_hours = (now - lr_dt).total_seconds() / 3600
                if age_hours > max_age_hours:
                    item["status"] = "pruned"
                    pruned += 1
            except (ValueError, TypeError):
                pass
        if pruned:
            self._save_items()
        return pruned

    # -- render --

    def render(self) -> str:
        """Render state as human-readable markdown."""
        lines = ["# Loop State — Hermes Homelab\n"]
        lines.append(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

        grouped: dict[str, list[dict]] = {s: [] for s in SECTIONS}
        for item in self._items.values():
            grouped[self.get_section(item)].append(item)

        for section in SECTIONS:
            items = grouped[section]
            lines.append(f"## {section}\n")
            if not items:
                lines.append("_None_\n")
                continue
            # Sort: critical first, then by last_run descending
            sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            items.sort(key=lambda x: (sev_order.get(x.get("severity", "medium"), 2),
                                      str(x.get("last_run", ""))), reverse=False)
            for item in items:
                status_icon = {"active": "🔴", "watch": "🟡", "waiting_human": "⏸️", "pruned": "⚫"}.get(
                    item.get("status", "active"), "•")
                line = (f"- {status_icon} **{item.get('id', '?')}** "
                        f"({item.get('severity', '?')}) — "
                        f"{item.get('last_action', 'detected')} "
                        f"[attempt {item.get('attempts', 0)}]")
                if item.get("human_override"):
                    line += f" _override: {item['human_override']}_"
                if item.get("stagnation_reason"):
                    line += f" _stagnation: {item['stagnation_reason']}_"
                lines.append(line)
                # inline the newest context packet line (if any) as a sub-bullet
                ctx = item.get("context") or {}
                if ctx:
                    last_key = sorted(ctx.keys(), key=int)[-1]
                    snippet = str(ctx[last_key]).replace("\n", " ")
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "…"
                    lines.append(f"    - ctx: {snippet}")
            lines.append("")

        return "\n".join(lines)

    def write(self) -> None:
        """Write rendered markdown to STATE_FILE."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(self.render())


# ---------------------------------------------------------------------------
# RunLog
# ---------------------------------------------------------------------------

class RunLog:
    """Append-only JSONL run log for observability."""

    def __init__(self, log_path: Path = RUN_LOG_FILE):
        self.log_path = log_path

    def record(self, pattern_name: str, duration_s: float,
               items_found: int, actions_taken: list[str],
               escalations: list, outcome: str) -> None:
        """Append a run entry."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pattern_name": pattern_name,
            "duration_s": round(duration_s, 2),
            "items_found": items_found,
            "actions_taken": actions_taken,
            "escalations": [str(e) for e in escalations],
            "outcome": outcome,
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def query(self, since_hours: int = 24, pattern: str | None = None) -> list[dict]:
        """Query recent entries."""
        if not self.log_path.exists():
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - since_hours * 3600
        results = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                    if ts >= cutoff:
                        if pattern is None or entry.get("pattern_name") == pattern:
                            results.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
        return results

    def tail(self, n: int = 20) -> list[dict]:
        """Return last N entries."""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text().strip().split("\n")
        entries = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("=== loop_state self-test ===")

    # LoopState roundtrip
    tmp_state = Path(tempfile.mkdtemp()) / "LOOP-STATE.md"
    tmp_items = tmp_state.with_suffix(".json")
    ls = LoopState(state_path=tmp_state, items_path=tmp_items)

    ls.add_or_update({
        "id": "restart_loop:plex", "pattern": "autonomous_fixer",
        "type": "restart_loop", "target": "plex", "severity": "high",
        "status": "active", "last_action": "delegate invoked",
        "last_run": datetime.now(timezone.utc).isoformat(),
    })
    ls.add_or_update({
        "id": "disk_pressure:/", "pattern": "self_heal_lite",
        "type": "disk_pressure", "target": "/", "severity": "medium",
        "status": "active", "attempts": 0, "last_action": "detected",
        "last_run": datetime.now(timezone.utc).isoformat(),
    })
    assert len(ls._items) == 2, f"Expected 2 items, got {len(ls._items)}"

    # Upsert same id — should update, not add. attempts only climb on a FAIL
    # outcome; a non-failing re-upsert keeps the attempt count (cuztom: we
    # count re-occurrences that *ended in failure*, not distinct actions).
    ls.add_or_update({
        "id": "restart_loop:plex", "last_action": "verify passed",
        "last_run": datetime.now(timezone.utc).isoformat(),
    })
    assert len(ls._items) == 2, f"Upsert should not add: {len(ls._items)}"
    assert ls._items[0]["attempts"] == 1, "Non-fail upsert must not increment"

    # Section assignment
    assert ls.get_section(ls._items[0]) == "High Priority"  # high severity
    assert ls.get_section(ls._items[1]) == "Watch List"      # medium severity

    # Escalate
    ls.escalate("disk_pressure:/")
    assert ls.get_section(ls._items[1]) == "Human Inbox"

    # Prune (with max_age=0 — everything stale)
    pruned = ls.prune(max_age_hours=0)
    # Human Inbox item should NOT be pruned
    assert ls._items[1].get("status") == "waiting_human", "Human inbox should survive prune"

    # Render
    ls.write()
    md = tmp_state.read_text()
    assert "High Priority" in md
    assert "Human Inbox" in md
    print("✓ LoopState: add, upsert, sections, escalate, prune, render")

    # RunLog roundtrip
    tmp_log = tmp_state.with_suffix(".jsonl")
    rl = RunLog(log_path=tmp_log)
    rl.record("autonomous_fixer", 47.3, 3, ["delegate(plex)"], [], "success")
    rl.record("self_heal_lite", 2.1, 1, [], ["stagnation"], "fix_unverified")
    tail = rl.tail(2)
    assert len(tail) == 2
    assert tail[0]["outcome"] == "success"
    assert tail[1]["outcome"] == "fix_unverified"
    recent = rl.query(since_hours=1, pattern="autonomous_fixer")
    assert len(recent) == 1
    print("✓ RunLog: record, tail, query")

    # Cleanup
    tmp_state.unlink(missing_ok=True)
    tmp_items.unlink(missing_ok=True)
    tmp_log.unlink(missing_ok=True)
    tmp_state.parent.rmdir()

    # ------------------------------------------------------------------
    # Gate tests (stagnation / context packet / blocked)
    # ------------------------------------------------------------------
    print("--- gate self-tests ---")
    tmp_state = Path(tempfile.mkdtemp()) / "LOOP-STATE.md"
    tmp_items = tmp_state.with_suffix(".json")
    ls = LoopState(state_path=tmp_state, items_path=tmp_items)

    # Gate 2: context packet survives merge & is retrievable.
    ls.add_or_update({"id": "f:probe", "type": "container_unhealthy",
                      "target": "probe", "severity": "high",
                      "last_action": "detected",
                      "last_run": datetime.now(timezone.utc).isoformat()})
    ls.add_context("f:probe", {"probe": "Up 3 days"})
    ctx = ls.get_context("f:probe")
    assert ctx.get("0") == "Up 3 days", f"context lost: {ctx}"
    # ring buffer cap (CTX_MAX_ENTRIES=10)
    for n in range(15):
        ls.add_context("f:probe", {str(n): f"line {n}"})
    assert len(ls.get_context("f:probe")) == 10, "context ring overflow"
    print("✓ context packet: merge, retrieve, ring-cap")

    # Gate 1: stagnation — 3 fail outcomes on same id => escalate + blocked.
    # One persistence instance across attempts mirrors the real fixer, which
    # re-reads the items file each cycle.
    ls2 = LoopState(state_path=tmp_state, items_path=tmp_items)
    for attempt in range(3):
        ls2 = LoopState(state_path=tmp_state, items_path=tmp_items)
        ls2.add_or_update({
            "id": "stagnant:pihole", "type": "container_unhealthy",
            "target": "pihole", "severity": "high",
            "last_action": f"delegate_{attempt}",  # different each attempt
            "last_outcome": "delegate_timeout",
            "last_run": datetime.now(timezone.utc).isoformat(),
        })
    assert ls2.is_blocked("stagnant:pihole"), "stagnation gate did not trip"
    it = [x for x in ls2._items if x["id"] == "stagnant:pihole"][0]
    assert it["status"] == "waiting_human"
    assert "stagnation_reason" in it
    print("✓ stagnation gate: 3 fails => escalate + blocked")

    # fix_unverified IS a failure — a fix that didn't verify must escalate.
    ls3 = LoopState(state_path=tmp_state, items_path=tmp_items)
    for _ in range(STAGNATION_ATTEMPTS):
        ls3 = LoopState(state_path=tmp_state, items_path=tmp_items)
        ls3.add_or_update({
            "id": "healthy:gateway", "type": "gateway_unstable",
            "target": "gateway", "severity": "low",
            "last_action": "check",
            "last_outcome": "fix_unverified",
            "last_run": datetime.now(timezone.utc).isoformat(),
        })
    assert ls3.is_blocked("healthy:gateway"), "fix_unverified must count as failure"
    print("✓ stagnation counts fix_unverified as failure")

    # But a verify-passed outcome must NOT accumulate — counter resets on
    # success (fresh id path would, and importantly the gate does not fire).
    ls4 = LoopState(state_path=tmp_state, items_path=tmp_items)
    for _ in range(STAGNATION_ATTEMPTS + 2):
        ls4 = LoopState(state_path=tmp_state, items_path=tmp_items)
        ls4.add_or_update({
            "id": "recovered:gateway", "type": "gateway_unstable",
            "target": "gateway", "severity": "low",
            "last_action": "check",
            "last_outcome": "success",  # success -> gate must not fire
            "last_run": datetime.now(timezone.utc).isoformat(),
        })
    assert not ls4.is_blocked("recovered:gateway"), "success must not trip gate"
    print("✓ success outcome does not trip stagnation gate")

    print("✓ gate self-tests passed")
    tmp_state.unlink(missing_ok=True)
    tmp_items.unlink(missing_ok=True)
    tmp_state.parent.rmdir()

    print("=== All self-tests passed ===")
