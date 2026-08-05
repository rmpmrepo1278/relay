# Relay — Hermes agent hallucination fix (2026-08-05)

## Context
User pasted a batch of Telegram notifications from the Hermes gateway and asked what they were.
They contained a mix of real scheduled pipeline output and a clearly fabricated `/goal` session
where the agent invented repos, search tools, and "implementation complete" claims with made-up
metrics (30% task savings, 95% uptime, 25% latency).

## Diagnosis (verified on homelab)
- Real notifications: evening briefing, night report, research pipeline (research_engine.py /
  daily_research.py) assessing 20 real items. Note: even the pipeline's "Report saved to
  ~/.hermes/assessment_report.txt" claim was FALSE — file never existed; pipeline reported "0 verified".
- Fabricated session: agent called `gitlab_search`/`github_search` — **no such tools exist**.
  Repos "homelab-automation by user123" etc. were placeholders. Nothing was installed/changed.
- Root cause chain:
  1. `config.yaml` `platform_toolsets.telegram` enabled `research` toolset, but
     `toolsets.py` registry has NO `research` toolset — `resolve_toolset("research")` → `[]` (empty).
     Not a plugin toolset either. So agent believed it had a research/search toolset but none existed.
  2. `tool_use_enforcement: auto` is permissive; agent hallucinated tool names instead of using the
     real `web` toolset (which IS enabled and resolves to web_search/web_extract), or running
     `daily_research.py`.
  3. No verification guardrail existed in the GENERAL channel prompt.

## Fix (committed `6c04e25` to chaguli/AgentChaguli.git master)
- `~/.hermes/config.yaml` telegram GENERAL channel prompt: added **rule 8 VERIFICATION RULES** —
  never invent tool calls/search results/repos/metrics; only claim work done with real tool output;
  fall back to `python3 ~/.hermes/scripts/daily_research.py` for GitHub research; say "not verified"
  when unsure.
- Removed dead `research` toolset from `platform_toolsets.telegram`. Real `web` (web_search) stays.
- Backed up config to `config.yaml.bak-verify-guardrail` (untracked, left in place).
- Restarted `hermes-gateway.service` (user systemd unit — needs `systemctl --user` with
  XDG_RUNTIME_DIR). 18/18 MCP healthy after restart.

## Key facts for future reference
- Hermes gateway = user systemd unit `hermes-gateway.service` (restart via
  `export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart hermes-gateway.service`).
- Toolsets live in `/home/rohit/.hermes/hermes-agent/.venv/lib/python3.13/site-packages/toolsets.py`
  (TOOLSETS dict, get_toolset/resolve_toolset). Enabled per-platform in `config.yaml platform_toolsets`.
- Valid search-related toolsets: `web` (web_search+web_extract), `search` (web_search only).
- Real repo-research script: `~/.hermes/scripts/daily_research.py` (curl GitHub API, saves to
  `~/.hermes/research_results.json`). Autonomous pipeline: `research_engine.py`.
- `~/.hermes` git remote = `chaguli` (AgentChaguli.git), branch master.
- `tool_use_enforcement: auto` + empty toolset = hallucination risk on this stack.