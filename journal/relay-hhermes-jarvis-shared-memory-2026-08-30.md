# Relay session — 2026-08-30: Hermes + Jarvis shared-memory integration

## Goal
User wanted a clean division of responsibilities between the two agents, both
using ONE common memory source:
- Hermes (Docker container, hermes-agent, "gateway run") = job pipeline, reports to
  agentchaguli (Telegram via n8n_bridge_server.py on 172.18.0.1:9199)
- Jarvis (host process, openjarvis .venv, systemd openjarvis.service, jarvis serve
  on 127.0.0.1:1377 -> AgentHarness proxy 100.122.58.40:8080/v1) = deep reasoning

## Architecture confirmed
- SHARED MEMORY = /home/rohit/.hermes/collaborator-memory/data/ (repo that pushes
  to relay.git). Both agents can read/write it:
  - Hermes container mounts host /home/rohit/.hermes -> /opt/data, so the repo is
    visible in-container at /opt/data/collaborator-memory/. Hermes uid runs as
    root(0) but repo owned by rohit(1000); data dir created 0700 rohit.
  - Jarvis is a host process (uid rohit) -> direct access.
- Bridge URL inside docker net: http://172.18.0.1:9199/telegram-send (the bridge
  binds N8N_BRIDGE_HOST=172.18.0.1, reachable from Hermes container nets; NOT on
  the tailnet IP — verified 100.122.58.40:9199 = 000).

## Built
1. /home/rohit/.hermes/scripts/auto_pipeline.py  (Hermes side)
   - source-pluggable (sources.json beside it; selftest fallback)
   - fetch -> dedupe (by hash across prior jobs_*.json) -> score -> write
     data/jobs_<date>.json -> POST concise digest to bridge /telegram-send
2. /home/rohit/.hermes/scripts/jarvis_ingest.py  (Jarvis side)
   - reads jobs_<date>.json -> detects skill clusters -> writes data/jars_<date>.json
3. systemd USER units:
   - agentchaguli-pipeline.service (oneshot: auto_pipeline.py then jarvis_ingest.py)
   - agentchaguli-pipeline.timer (daily 06:30, Persistent=true)
   Verified: both scripts run exit 0; timer armed; next run Mon 2026-08-31 06:30.

## Verified
- real auto_pipeline run: wrote jobs_2026-08-30.json AND posted to agentchaguli
  (sent=True) — evidence Telegram channel is alive again.
- real jarvis_ingest run: wrote jars_2026-08-30.json (skills/recommendation).
- Everything tailnet-only / host-local; no new public exposure.

## Division of responsibility
- Hermes = daily job fetch/dedupe/score/report + lightweight summary to Telegram.
- Jarvis = deep multi-step reasoning on the same job data (skills, trends, plans).
- Both read/write data/jobs_*.json + data/jars_*.json in the shared memory repo.

## Notes / next
- selftest source currently only; plug a real source in sources.json to make the
  digest meaningful (e.g., custom JSON feed or an API).
- data/ committed to relay.git; will accumulate one jobs_+jars_ pair per day.
