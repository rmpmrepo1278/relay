# relay-career-ops-telegram-pipeline-2026-08-29.md

## Goal
Make the career-ops pipeline work via Telegram: sending a job URL in the
career-ops Telegram topic triggers resume + cover letter + LinkedIn referral
text generation and uploads the artefacts to Google Drive.

## Context
- Hermes gateway (container hermes) mounts /home/rohit/.hermes:/opt/data. The
  container does NOT have rclone, WeasyPrint or the host GDrive config, so the
  host-only script /home/rohit/projects/career-ops/auto_pipeline.py was
  invisible to the container plugin.
- User plugin plugins/career_ops_pipeline/__init__.py (pre_gateway_dispatch
  hook) was NOT enabled and pointed at a host-only path.

## Root causes
1. Plugin not enabled (plugins list showed "not enabled").
2. Plugin _run_pipeline referenced the host-only path inside the container
   (path does not exist in-container).
3. Container lacks rclone/weasyprint/gdrive config -> PDFs/GDrive cannot run
   in-container.

## Fix applied
- Enabled the plugin (hermes plugins enable career_ops_pipeline), persisted in
  config.yaml (plugins.enabled). Survives restarts.
- Set up SSH key (container hermes -> rohit@127.0.0.1) at /opt/data/.ssh/
  id_ed25519, added to host authorized_keys.
- Rewrote _run_pipeline to invoke auto_pipeline.py on the HOST via SSH.
  JD temp files -> host /tmp/career_jd_* via base64-over-SSH, cleaned up after;
  debug log at container-writable /opt/data/logs/career_ops_pipeline_debug.log.
- Restored two functions dropped during the rewrite: _extract_job_urls and
  _PROCESSED_URLS set.
- Fixed command construction bug: pipeline built as a list containing the shell
  operator &&, then shlex.quote-d and joined into one shell string. shlex.quote
  turns && into a literal token, so remote `cd` got 2 args ->
  "bash: line 1: cd: too many arguments" (exit 1). Fixed by passing run_cmd as
  a proper argv list (cmd = _SSH_BASE + run_cmd), so && stays an operator and
  the URL is a clean token.
- Added in-message URL dedup.

## Verification
- Plugin loads + hook registered: "career_ops_pipeline plugin loaded:
  pre_gateway_dispatch hook registered".
- Host pipeline via the plugin exact argv+SSH command (dry-run): JD fetched
  (8000 chars), Score 4/5, resume PDF + cover letter + LinkedIn messages
  generated. EXIT 0.
- Real Telegram end-to-end test (run #154): job URL in career-ops topic ->
  hook fired -> pipeline ran on host -> resume PDF, cover letter PDF,
  linkedin_referral_connection.txt, linkedin_referral_cold.txt and report md ALL
  pushed to Google Drive (user rohit) under gdrive:Job Hunt/August 2026/
  Job Boards - Job Application for Director, Technical Program Management/.
- Container->host SSH chain: SSH_CHAIN_OK.

## Notes / known quirks
- pre_gateway_dispatch fires only on a FRESH dispatch. If the gateway has a
  long-running turn in the same chat, a job-URL message is merged into the
  running turn (Redirected current run) and bypasses the hook. Send the URL
  when the gateway is idle (or after a fresh restart) so it is a fresh
  dispatch.
- Company name is derived from the URL when the page scrape does not surface a
  clean company. For job-boards.greenhouse.io/<co>/jobs/<id> the pipeline
  derives "Job Boards" instead of the real company (New Relic). Pre-existing
  auto_pipeline.py quirk, NOT an incident from this work. Scraped title is
  correct. Optional separate follow-up.

## Files
- Plugin: /home/rohit/.hermes/plugins/career_ops_pipeline/__init__.py
- Backups: __init__.py.bak (original), __init__.py.pre-ssh
- Host pipeline: /home/rohit/projects/career-ops/auto_pipeline.py
- Debug log: /opt/data/logs/career_ops_pipeline_debug.log
- Host rclone config: /home/rohit/.config/rclone/rclone.conf (gdrive:)
