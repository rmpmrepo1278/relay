# Relay: Heavy Lifter — full-Hermes one-shot core, approval-gated (2026-09-18)

User approved (Round-12 design): (a) fleet-initiated heavy jobs with human
approval = YES, (b) file write bounded to scratch workdir = YES. Built the
first capability-escalation path: the thin fleet stays the cadence layer, and
1+ full-Hermes one-shot cores now run on-demand for complex/human-present work.

## Engine: the `hermes -z` one-shot core
- Invocation: `PYTHONPATH=<repo> <runtime>/python -m hermes_cli.main -z "<prompt>" -t web,search,file,skills --usage-file <f>`.
- `run_oneshot()` (`hermes_cli/oneshot.py:202`) sets `HERMES_YOLO_MODE=1` +
  `HERMES_ACCEPT_HOOKS=1` → approval prompts are useless → the gate is
  STRUCTURAL: an explicit toolset allowlist is the only safety.
- Verified schema for the allowlist = exactly 9 tools: patch, read_file,
  search_files, skill_manage, skill_view, skills_list, web_extract, web_search,
  write_file. No terminal/execute_code/delegate_task/browser/cronjob, ever.
- `-z` takes the prompt as ITS argument (must immediately follow the flag).
- Usage file emits tokens/cost/model/session even on a usable run.
- `--in` semantics unverified — dispatcher instead sets the subprocess `cwd=` to
  the per-job scratch dir (`~/.hermes/heavy/<task_id>/`), which bounds file I/O.

## Runtime gap found + fixed
`~/.hermes/hermes-agent` is a symlink to a uid-10000(hermes)-owned
`/home/rohit/homelab/code/hermes-agent` (rohit can't write inside it). The
venv the gateway unit expected (`.venv/bin/python`) never existed there →
every `hermes` invocation was rc=127 and the gateway unit was stale/failed.
Built a rohit-owned runtime: `~/.hermes/hermes-runtime/.venv`
(`python3 -m venv` + `pip install` of the 26 non-win32 `pyproject` deps), then
run the LIVE repo code via `PYTHONPATH`. `hermes -z` verified live (haiku-4.5,
provider custom, rc=0, usage report).

## Dispatcher: `scripts/heavy_dispatcher.py`
Polls agentbus every 30s for `owner=hermes-heavy` tasks; state machine:
- `ready` → posts a human-approval proposal to the personal topic (10122) with
  `/heavy approve|deny <id>` buttons, sets `awaiting`.
- `awaiting` > 30 min → `cancelled` + expiry notice.
- `approved` → budget check (daily 500k tokens, `data/heavy_budget.json`) →
  `running` → run with cwd=scratch, 20-min timeout, usage file → `done|failed`
  with `proof`=spend summary, `result`=response tail (≤300 chars).
- Stale `running` (dispatcher died mid-job) → auto-recovered to `approved`,
  retried ≤3× then `failed`.
- Same-title dedup (6h), failures tracked; every decision + spend recorded in
  the unified agentscape ledger (A2 `record("hermes-heavy", ...)`).
- `--once` flag for tests; systemd `hermes-heavy.service` (user) runs the loop.

## Bridge: `/heavy` slash commands (`n8n_bridge_server.py`)
`_route_telegram_command` map + `_heavy_cmd`/`_heavy_status`: `propose
<title> [ | <prompt>]`, `approve|deny|cancel <id>`, `status`. Writes via the
existing `_bus_req`. Verified via module import against the live bus.

## Unit gotcha discovered
`RuntimeMaxSec=0` on this host's systemd = **zero-second** runtime limit, not
infinite → every start instantly SIGTERM'd (`Result: timeout`, MainPID=0,
"activating (auto-restart)"). Remove the line (default = infinity). Also:
the host `n8n-bridge.service` is a disabled leftover that exit-1s on start
(container owns 9199) — do not restart it; restart the `n8n-bridge` CONTAINER
to reload bridge code. The user-scope journal captures no stdout on this box
(journald/stdout gap) — rely on `systemctl is-active` + `ss` + scripts' own
logging/ledger rather than `journalctl --user -u <svc>`.

## Agentbus data race (pre-existing, observed)
tasks.json lost a batch of tasks midway through testing (returned to a stale
4-task snapshot; events kept flowing; board later healed to 17). No pruner in
agentbus/bus_monitor; `load→save` read-modify-write is not atomic. Dispatcher is
a clean consumer (writes only through the bus) and is unaffected. Flagged for a
future round (write-lock / single-writer reconcile), not fixed here.

## Verified end-state
- e2e: propose → `/heavy approve` → `done` (result `go`, proof tokens=8583, 1
  call, haiku-4.5); proposal path `awaiting` + real message to 10122; stale-
  running recovery implemented; budget file + per-job usage file + scratch dirs
  present; ledger entries land.
- `hermes-heavy.service` active (MainPID 1700024); n8n-bridge container
  restarted healthy with the new handler file (PID 1704129).
- Regression **9/9 PASS** (incl. real tg-egress send+delete, homelab kopia).
- Files changed: `scripts/heavy_dispatcher.py` (new), `scripts/n8n_bridge_server.py`
  (+`/heavy`), `agents/guardrails.yaml` (+`heavy_lifter:`), systemd
  `hermes-heavy.service` (new), `~/.hermes/hermes-runtime/.venv` (new).
- Notes: `RuntimeMaxSec` lesson + the user-journal stdout gap are worth an
  AGENTS.md footnote if we spin up more user units.