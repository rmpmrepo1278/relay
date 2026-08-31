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

## 2026-08-31 (fixes + auto-apply wiring)
### Hermes session-DB fix (2 bugs, one root cause)
- ROOT CAUSE: Hermes gateway runs as uid 10000 (hermes) via s6-setuidgid. The
  /opt/data/lib dir (host /home/rohit/.hermes/lib) was owned uid 1000 (rohit)
  mode 700 -> hermes could not traverse it -> PermissionError on
  libfts5_cjk.so -> session store fell back to JSONL -> scary logs + restarts.
- FIX: chown 10000:10000 + chmod 0755 on /home/rohit/.hermes/lib; then built
  the never-built CJK FTS extension in-container: cd /opt/hermes/native/fts5_cjk
  && bash build.sh /opt/data/lib  -> libfts5_cjk.so (mode 644, hermes-readable).
- VERIFIED: gateway restart shows NO permission warning; extension loads as
  hermes (CREATE VIRTUAL TABLE ... tokenize=cjk_unicode61 works); gateway stable.
- Do NOT rely on LinkedIn cookies (May cookies = 302 loop / dead). The public
  guest /jobs-guest/jobs/api/seeMoreJobPostings/search endpoint works keyless.

### Auto-apply wired (AgentChaguli -> career-ops)
- run_apply.sh: host shim, takes base64(job_json) arg (no quote issues). Gate:
  /home/rohit/.hermes/scripts/apply.conf AUTO_APPLY_REAL (0=dry-run default) +
  APPLY_MIN_SCORE (52). Runs /home/rohit/projects/career-ops/auto_pipeline.py
  --company --title --min-score 4.0.
- auto_pipeline.py (discovery) now calls _run_auto_apply(new_jobs) after the
  digest, for score>=52. Pipeline runs ON HOST as rohit (systemd user timer
  06:30; NOT in container) -> direct shim call, no SSH needed.
- DEDUP BUG FIX (critical): LinkedIn job urls carry volatile ?position/refId/
  trackingId that change EVERY fetch -> _hash_job(url) differed daily -> would
  re-apply same jobs. Fixed: strip query params from url in _hash_job AND in
  linkedin_jobs._norm_job (store clean url). Verified stable hashes across
  fetches + re-run dedup (new drops to 4-9 not 12).
- Verified end-to-end: discovery 12 TPM/Director jobs -> dedup -> digest to
  agentchaguli [telegram sent=True] -> auto-apply dry-run (reports 153.., cover
  letters, linkedin msgs; NO GDrive push while AUTO_APPLY_REAL=0).

## 2026-08-31 (part 2) — Real submission + tracking + automated follow-up (email-drop)
Decision (user): keep automated; FULL depth = submit + track + follow-up. Submission
mechanism chosen by user: EMAIL-DROP to recruiter (not Playwright — not installed,
fragile vs ATS/CAPTCHA).

### Email infra (was present but unused)
- email_intelligence.py send_email() uses Gmail API OAuth (scopes include gmail.send).
  Lives in Hermes CONTAINER venv (/opt/hermes/.venv). Tokens at ~/.hermes/gmail/{credentials,token}.json
  (mounted /opt/data/gmail). Key gotcha: module computes GMAIL_DIR from Path.home()/.hermes/gmail
  -> in container HOME=/root resolves wrong. FIX: create symlink /opt/data/.hermes -> /opt/data,
  and invoke with env HOME=/opt/data. Verified GMAIL_OK rohitmishra1278@gmail.com.
- host->container: rohit is in docker group, so host runs: docker cp payload to
  hermes:/tmp/email_payload.b64; docker exec hermes env HOME=/opt/data python send_email.py /tmp/email_payload.b64
- NEW container script /opt/data/scripts/send_email.py: takes base64 JSON payload
  {to,subject,body,attachments:[{name,content(b64-pdf)}]} -> sends multipart with PDFs.

### Host-side wiring (discovery pipeline runs on host as rohit, systemd timer)
- career-ops/auto_pipeline.py: added RESULT_JSON line (company,title,url,score,company_slug,
  report_path,resume_path,cover_path) for machine parsing.
- NEW /home/rohit/.hermes/scripts/email_drop.py: (1) ALWAYS records application via
  tracker.track_application(status="applied") + schedules 14d follow-up; (2) BEST-EFFORT
  email-drop ONLY when an EXPLICIT recruiter addr resolves; embeds resume+cover PDFs, sends via docker exec.
- run_apply.sh: captures full pipeline output, greps RESULT_JSON, calls email_drop.py.
- NEW /home/rohit/.hermes/scripts/recruiting_contacts.json: {"companies": {}}
  {company: addr} explicit map. fallback_guess=false => NEVER guess-send hr@company.com from a real Gmail.
  Add entries to enable sending per company.
- apply.conf AUTO_APPLY_REAL=1 (real GDrive push) + APPLY_MIN_SCORE=52.

### Follow-up automation (drafts now EMAIL)
- tracker.get_applications_needing_followup: rows status in (applied,interview), >=14d old,
  no follow_ups.sent_at. We set status=applied at apply time => now fed.
- career-ops/scripts/auto_followup.py: patched. On --send: reads recruiter from notes="recruiter=..."
  (stored by email_drop.py), EMAILS the follow-up via container sender instead of draft-only;
  marks follow_ups.sent_at. Also fixed None interview_stage crash. Real scheduled follow-ups
  stored when apply emails (notes=recruiter=<addr>).
- hermes_scheduler.py auto_followup job: now runs auto_followup.py --days 14 --send (Mon 10:30).
  Restarted hermes-scheduler.service to load new def.

### VERIFIED end-to-end (to own Gmail as safe test recipient)
1. REAL apply via shim: record app_id=75 status=applied + 14d followup; GDrive 4 files pushed;
   EMAIL_SENT "Application — Engineering Program Director".
2. DB: applications row 75 (Salesforce/Engineering Program Director/64/applied/report+cover paths);
   follow_ups row scheduled 2026-09-14.
3. Follow-up simulated (backdated 15d) : EMAILED "Follow-up — ... Salesforce"; follow_ups.sent_at set.
4. Gmail confirmed BOTH emails landed 21:40 + 21:44 (from rohitmishra1278@gmail.com).
Test state restored (app75 updated_at=now, notes=NULL, real follow-up re-armed sent_at=NULL).

### IMPORTANT operational notes
- LinkedIn guest feed gives company+url but NO recruiter email -> email-drop is GATED on explicit
  recruiting_contacts.json entries. Until populated, applies RECORD + schedule follow-up but don't
  send (by design, avoids spam from real Gmail). Populate map with real recruiter/talent addresses to activate emailing.
- Voice gate flags 2 issues on follow-up draft (still sent).
