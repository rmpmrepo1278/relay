# relay-audit-automation-2026-08-18.md

## Weekly codebase audit automation (new capability)

Built and installed a weekly automated code-quality audit for the Hermes stack.

### Where it lives
- `/home/rohit/.hermes/audit/` (committed, main repo `56caa4e`):
  - `AUDIT_BRIEF.md` — parameterized per-subsystem review prompt (bounded workers, max 2 findings, AUTOFIX gating, evidence schema)
  - `COORD_BRIEF.md` — validation/dedup/priority pass
  - `FIX_BRIEF.md` — unattended fixer: applies only AUTOFIX=YES findings, runs VALIDATION, commits per finding, reverts on failure
  - `subsystems.tsv` — 14 ownership boundaries S01–S14
  - `run_audit.sh` — lock-protected orchestrator: review → coordination → fix phases; Telegram notify; portable mkdir lock
- systemd user units `hermes-codebase-audit.service` + `.timer` (gitignored, local-machine convention): weekly Sun 03:30 + RandomizedDelaySec=600. Next run: Sun 2026-08-23 03:34 PDT.

### How to use
- `bash run_audit.sh --list` — list subsystems
- `bash run_audit.sh --smoke` — verify briefs + file paths + claude CLI
- `bash run_audit.sh full` / `bash run_audit.sh --review-only` — run now
- Reports: `~/.hermes/audit/reports/audit_<ts>.md`, logs in `logs/`

### Key design decisions
- Driven by `claude -p --dangerously-skip-permissions --output-format text` (Claude Code 2.1.233 on homelab), sequential per-subsystem to bound concurrency.
- AUTOFIX gate: only high-confidence or small/medium-scope revertible findings are auto-applied; schema migrations and cross-subsystem ownership changes stay human.
- Fix phase never touches: .telegram_token, root-owned files, state/DB files, compose, systemd units.

### Prune incident fixed the same session (commit 4bab3e2)
- self_prune.py: replaced fragile regex scheduler rewrite (failed on nested parens `p(f"...")`, `$(cat ...)`) with AST-based enabled=False edit + deferred daemon restart via systemd-run. Disables now actually take effect (daemon reads jobs only at startup).
- capability_tracker.py: 14-day analysis window, failures counted only on status transitions, jobs no longer in scheduler dropped. Result: stale candidates 5→0 (boot_inbox_watcher 100%→1.2%, weekly_optimize dropped/renamed).

### Notes
- `gpt_researcher` optional (hybrid research mode) not installed; PEP 668 externally-managed Python.
- Audit is read-only until fix phase; fixer runs VALIDATION (py_compile + CLI entry) before committing.