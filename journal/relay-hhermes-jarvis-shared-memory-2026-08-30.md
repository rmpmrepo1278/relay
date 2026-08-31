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

## 2026-08-30 (follow-up): real job-discovery source wired
- discovery_source.py: fetches Remotive (limit=100, ~19 real jobs) + WeWorkRemotely
  RSS (back-end + devops/sysadmin feeds, ~19 more). Filters against Rohit profile
  (platform/backend/sre + python/docker/k8s/AI-infra; excludes frontend/junior/sales).
  0-100 fit score; threshold 55 = good fit. Merged discovery: 38 candidates -> 10
  good-fit (Senior Backend Python, Senior DevOps, Platform.sh IT Systems Engineer,
  Senior Software AI Engineer, etc.).
- auto_pipeline.py default source now delegates to discovery_source.py (no more
  fake self-test). Dedupe across days via job hash (title|company|url).
- Run: real digest of 7 jobs (6 new) POSTed to agentchaguli (sent=True):
  jobs_2026-08-30.json (7 jobs, 38KB) + jars_2026-08-30.json (jarvis skills/trends)
  written to shared data dir. systemd timer daily 06:30 now yields real content.
- False positive noted: "Counsel, Product & Regulatory" (legal) scored 73 due to
  keyword overlap; acceptable for a digest, could be tightened with title-word
  negation if noisy.

## 2026-08-30 (correction): discovery source = LinkedIn guest TPM feed
- User corrected profile: NOT an engineer. Real fit = Director / Sr Director
  TECHNICAL PROGRAM MANAGEMENT, Program/Portfolio/Delivery management leader
  (20+ yrs; T-Mobile + Microsoft; PMP/CSM/SAFe; built from cv.md).
- discovery_source.py (free Remotive+WWR feeds) contains 0 TPM roles -> useless.
  Kept as fallback only.
- NEW linkedin_jobs.py: uses LinkedIn PUBLIC unauthenticated guest job-search
  endpoint (no cookies/key): /jobs-guest/jobs/api/seeMoreJobPostings/search.
  Queries: TPM, Program Manager Director, TPM Director, Program Mgmt Portfolio.
  Parses job cards (title/company/loc/url/date), scores vs TPM-director profile.
  Verified: 15 cand -> 10 good-fit in dry run (Salesforce Eng Program Director,
  Capital One Director TPM, Walmart Director TPM, Thermo Fisher Dir PM, etc.).
- auto_pipeline.py source now = LinkedIn primary, free-feed fallback.
  Real run: 12 good-fit TPM/Director jobs POSTed to agentchaguli (sent=True).
- NOTE: LinkedIn guest endpoint is public/short-lived-friendly; cookie-based
  vouyager session (May 5 cookies) is DEAD (302 loop). Do NOT rely on it.
- git is now a maintenance consideration: "sources.json" not used; selftest
  loader hardcodes source fallback chain.
