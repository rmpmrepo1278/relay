#!/usr/bin/env python3
"""decision_council.py - the Speaker of the Agent Parliament.

Agent Parliament: autonomous actions must win council approval before
commitment_executor runs them.

SPEAKER cycle:
  1. scans outcomes for repeat service failures (gene+target, >=2 fails/24h);
  2. writes a proposal into decision_register (status=pending, source=decision_council);
  3. seeds a vote slate in state/decision_votes.json;
  4. pages you with the proposal.

A separate vote-collector job (or a member agent) writes votes; run with --vote
to tally pending proposals, flip the register to completed/rejected, and emit the
APPROVED action to state/commitment_queue.json for commitment_executor.

--list-open  : list pending proposals.
--vote       : tally and finalize any proposal with quorum.
--dry-run    : propose only, no DB writes / no paging.
"""
import json, os, re, sys, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone

HERMES_HOME = Path.home() / ".hermes"
DB = HERMES_HOME / "data" / "unified_memory.db"
STATE = HERMES_HOME / "state"
STATE.mkdir(parents=True, exist_ok=True)
VOTES_FILE = STATE / "decision_votes.json"
QUEUE_FILE = STATE / "commitment_queue.json"
COMMITMENTS_FILE = HERMES_HOME / "data" / "commitments.json"
QUORUM = 3
MAJORITY = 2

sys.path.insert(0, str(HERMES_HOME / "hermes-agent" / "scripts" / "lib"))
import telegram_send  # type: ignore
def _safe_tg(text, dedup=True):
    """Telegram is best-effort: missing credentials must never abort autonomous work."""
    try:
        return telegram_send.send_telegram(text, dedup=dedup)
    except Exception:
        return False



DRY_RUN = "--dry-run" in sys.argv

COUNCIL_MEMBERS = ["learning_integrator", "insight_engine",
                   "adversarial_engine", "predictive_signals", "self_correction"]

ACTION_PROPOSERS = {
    "gene_container_crash": "restart container {target}",
    "gene_service_down": "start service {target}",
    "gene_healthcheck_fail": "investigate+patch service {target}",
    "gene_mcp_child_health": "restart mcp child {target}",
    "gene_restart_loop": "break restart loop on {target}",
    "gene_missing_script": "restore missing script {target}",
    "gene_memory_pressure": "free memory on {target}",
    "gene_dns_resolution": "investigate DNS resolution failures",
    "gene_backup_failure": "restore backup {target}",

}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_votes():
    if VOTES_FILE.exists():
        try:
            return json.loads(VOTES_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_votes(v):
    VOTES_FILE.write_text(json.dumps(v, indent=2))


def _existing_pending(c, action_key):
    return c.execute(
        "SELECT id FROM decision_register WHERE source='decision_council' "
        "AND status='pending' AND summary LIKE ? LIMIT 1",
        (f"%{action_key}%",),
    ).fetchone()


def _detect_proposals(c):
    """Recent failures grouped by gene+target (real services, last 24h).

    outcomes.timestamp stores ISO-8601 strings, so we compute the cutoff in
    Python and do a string compare (SQLite datetime() won't parse the +00:00
    suffix the same way)."""
    from datetime import timedelta
    hours = int(os.environ.get('COUNCIL_WINDOW_HOURS', '24'))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    proposals = []
    rows = c.execute(
        "SELECT gene_id, target, COUNT(*) AS n FROM outcomes "
        "WHERE outcome='fail' AND timestamp > ? "
        "AND target IS NOT NULL AND target != 'unknown' "
        "GROUP BY gene_id, target HAVING n>=2",
        (cutoff,)
    ).fetchall()
    for gene, target, n in rows:
        tmpl = ACTION_PROPOSERS.get(gene)
        if tmpl and target:
            proposals.append((gene, target, tmpl, n))
    seen = set(); uniq = []
    for g, t, tmpl, n in proposals:
        key = (g, t)
        if key in seen:
            continue
        seen.add(key); uniq.append((g, t, tmpl, n))
    return uniq


def _propose(c, gene, target, tmpl, n):
    action_key = tmpl.replace("{target}", target) if "{target}" in tmpl else tmpl
    action_key = action_key.replace("{target}", target)
    if _existing_pending(c, action_key):
        return None
    pid = "D" + _now().replace("-", "").replace(":", "").replace(".", "")[:14] + uuid.uuid4().hex[:4]
    now = _now()
    c.execute(
        "INSERT INTO decision_register (id,summary,context,owner,stakeholders,impact,domain,status,priority,"
        "due_date,outcome,follow_up,source,created_at,updated_at,completed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, action_key,
         f"gene={gene} target={target} recent_failures={n}",
         "hermes_mind/speaker", json.dumps(COUNCIL_MEMBERS),
         "high", "infrastructure", "pending", "high",
         None, None, None, "decision_council", now, now, None),
    )
    c.commit()
    votes = _load_votes()
    votes[pid] = {"action_key": action_key, "proposed_at": now,
                  "votes": {}, "members": COUNCIL_MEMBERS, "quorum": QUORUM,
                  "gene": gene, "target": target, "failures": n}
    _save_votes(votes)
    return pid


def _tally(pid):
    v = _load_votes().get(pid, {})
    if not v:
        return None
    y = sum(1 for vote in v["votes"].values() if vote in ("yes", "abstain-yes"))
    n = sum(1 for vote in v["votes"].values() if vote in ("no", "abstain-no"))
    abstain = sum(1 for vote in v["votes"].values() if str(vote).startswith("abstain"))
    voted = len(v["votes"])
    quorum_reached = voted >= QUORUM
    approved = quorum_reached and y >= MAJORITY
    return {"yes": y, "no": n, "abstain": abstain, "voted": voted,
            "quorum_reached": quorum_reached, "approved": approved}


def _enqueue(action_key):
    """Persist the approved action so an executor consumes it.
    1) commitment_queue.json  (parliament ledger)
    2) data/commitments.json   -> what commitment_executor actually reads
    """
    q = []
    if QUEUE_FILE.exists():
        try:
            q = json.loads(QUEUE_FILE.read_text())
        except Exception:
            q = []
    # idempotent: never queue the same action twice
    if any(x.get("action") == action_key for x in q if isinstance(x, dict)):
        return
    q.append({"action": action_key, "queued_at": _now(), "source": "decision_council"})
    QUEUE_FILE.write_text(json.dumps(q, indent=2))

    # write a compatible active commitment for commitment_executor
    try:
        cj = json.loads(COMMITMENTS_FILE.read_text()) if COMMITMENTS_FILE.exists() else {}
    except Exception:
        cj = {}
    active = cj.get("active", [])
    if not any(x.get("text") == action_key for x in active):
        active.append({
            "id": "council_" + _now().replace("-", "").replace(":", "").replace(".", "")[:16],
            "text": action_key,
            "deadline": datetime.now(timezone.utc).isoformat(),  # effectively due now
            "source": "council",
            "context": "approved by Agent Parliament",
            "status": "active",
            "created": _now(),
        })
    cj["active"] = active
    COMMITMENTS_FILE.write_text(json.dumps(cj, indent=2))


def _gate_and_enqueue(action_key):
    """Apply human-override jurisdiction before queueing.

    - personal action + no human vote  -> page ballot, do NOT enqueue (pending-human)
    - personal action + human 'no'      -> suppress (rejected-human)
    - personal action + human 'yes'     -> enqueue (human-approved)
    - infra action (auto)               -> enqueue with [trial] suffix (reversible)
    """
    try:
        import sys as _s
        _s.path.insert(0, str(HERMES_HOME / "scripts"))
        import human_overrides as _gov
        gate = _gov.human_vote_record(action_key)
        if gate["requires_human"] and not gate["human_vote"]:
            # no human verdict yet: honor the ballot lifecycle so we don't
            # page a fresh ballot every 5-minute tally (flood), but DO re-page
            # on the cadence and expire the action if it stays unanswered.
            lc = _gov.ballot_lifecycle(action_key)
            if lc["expired"]:
                _gov.expire_ballot(action_key)
                return ("rejected-human-expired", None)
            if lc["should_page"]:
                if lc["paged"]:
                    _gov.repage_ballot(action_key)
                else:
                    _gov._page_approval_ballot(action_key, gate)
                lc = _gov.ballot_lifecycle(action_key)
            return ("pending-human", lc)
        if gate["human_vote"] == "no":
            return ("rejected-human", None)
        if gate["is_personal"]:
            _enqueue(action_key)
            return ("enqueued-human-approved", action_key)
        # infra -> reversible trial suffix appended to the action
        suffix = gate.get("suffix")
        enq = f"{action_key} {suffix}".strip() if suffix else action_key
        _enqueue(enq)
        return ("enqueued-trial", enq)
    except Exception:
        _enqueue(action_key)
        return ("enqueued", action_key)


def _page_proposal(pid, action, gene, target, failures):
    msg = (f"🏛️ Council: propose *{action}*  (proposal {pid})\n\n"
           f"Reason: gene={gene} on {target} failed {failures}x in 24h.\n"
           f"Council members: {', '.join(COUNCIL_MEMBERS)}\n"
           f"Quorum={QUORUM}, needs {MAJORITY} YES to approve.\n"
           f"Votes are tallied automatically. Say nothing — or vote via your CoS.")
    _safe_tg(msg, dedup=True)


def _page_tally(pid, v, tally, gate_out=None):
    lines = [f"🏛️ Council tally: *{v['action_key']}*  (proposal {pid})"]
    votes = v.get("votes", {})
    for m in COUNCIL_MEMBERS:
        lines.append(f"  • {m}: {votes.get(m, '—')}")
    lines.append(f"  → YES={tally['yes']} NO={tally['no']} voted={tally['voted']}/{QUORUM}")
    if tally["approved"]:
        outcomes = {
            "enqueued-trial": "  ✅ APPROVED — queued for commitment_executor as a reversible [trial] action.",
            "enqueued-human-approved": "  ✅ APPROVED — queued (human 6th vote on personal action).",
            "enqueued": "  ✅ APPROVED — queued for commitment_executor.",
            "pending-human": "  🛑 HELD — personal action needs your 6th vote before it runs.",
            "rejected-human": "  ❌ REJECTED — you voted no on this personal action.",
            "rejected-human-expired": "  ⏰ EXPIRED — ballot unanswered after its pages; action not run.",
        }
        lines.append(outcomes.get(gate_out or "enqueued", "  ✅ APPROVED — queued."))
    elif not tally["quorum_reached"]:
        lines.append("  ⏳ Quorum not yet reached — keep voting.")
    else:
        lines.append("  ❌ REJECTED — action suppressed.")
    _safe_tg("\n".join(lines), dedup=False)


def run_vote():
    c = sqlite3.connect(DB)
    votes = _load_votes()
    acted = []
    for pid, v in list(votes.items()):
        if not v.get("votes"):
            continue
        tally = _tally(pid)
        if not tally["quorum_reached"]:
            continue
        if tally["approved"]:
            if DRY_RUN:
                status, gate_out = "completed", "enqueued"
            else:
                gate_out, _enq = _gate_and_enqueue(v["action_key"])
                status = {
                    "enqueued-trial": "completed",
                    "enqueued-human-approved": "completed",
                    "enqueued": "completed",
                    "pending-human": "pending",   # held for human; stays open
                    "rejected-human": "rejected",
                    "rejected-human-expired": "rejected",
                }.get(gate_out, "completed")
        else:
            status, gate_out = "rejected", None
        c.execute("UPDATE decision_register SET status=?, updated_at=? WHERE id=?",
                  (status, _now(), pid))
        c.commit()
        acted.append({"proposal": pid, "action": v["action_key"], "tally": tally, "gate": gate_out})
        if not DRY_RUN:
            _page_tally(pid, v, tally, gate_out)
        # finalized proposals leave the live slate (keeps re-tally churn out +
        # makes the listener's "pending keys" set exact)
        if status != "pending":
            votes.pop(pid, None)
            _save_votes(votes)
    # drop any ballots whose proposal no longer exists
    try:
        import sys as _s
        _s.path.insert(0, str(HERMES_HOME / "scripts"))
        import human_overrides as _gov
        _gov.cleanup_ballots()
    except Exception:
        pass
    c.close()
    return {"finalized": acted}


def list_open():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id,summary,status,created_at FROM decision_register "
        "WHERE source='decision_council' AND status='pending' ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    c.close()
    return {"open_proposals": [dict(r) for r in rows]}


def run_speaker():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    fired = []
    for gene, target, tmpl, n in _detect_proposals(c):
        pid = _propose(c, gene, target, tmpl, n)
        if pid:
            fired.append({"proposal_id": pid, "gene": gene, "target": target, "failures": n})
            if not DRY_RUN:
                action = tmpl.replace("{target}", target) if "{target}" in tmpl else tmpl
                _page_proposal(pid, action, gene, target, n)
    c.close()
    return {"proposed": fired}


if __name__ == "__main__":
    if "--list-open" in sys.argv:
        print(json.dumps(list_open(), indent=2))
    elif "--vote" in sys.argv:
        print(json.dumps(run_vote(), indent=2))
    else:
        print(json.dumps(run_speaker(), indent=2))
