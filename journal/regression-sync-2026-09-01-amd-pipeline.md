# AMD Pipeline Fix — State Sync for E2E Regression Session

Date: 2026-09-01 05:4x UTC  
Scope: career-ops AMD job pipeline via Hermes Telegram `pre_gateway_dispatch` hook.  
Owner session: this (opencode) — handing off to the E2E-Telegram suite session.

## Problems originally reported by user
- "Pasted JD text is too short (need >100 chars). Paste the full job description." (AMD URL)
- "nothing happens" after `Run job pipeline: <amd url>`
- Resume/cover PDF missing from GDrive (`Job Hunt/August 2026/...`)

## Root causes found + fixed (all verified)

### 1. Gateway crash-loop → "nothing happens"
- **Cause:** `/opt/data/logs/agent.log` was owned `rohit(1000):1000` mode 0600; the gateway runs as `hermes(10000)` → `PermissionError: /opt/data/logs/agent.log` right after hook-loading → crash → s6 restart loop → never bound Telegram listener.
- Plus: dozens of `/opt/data` DBs/logs (`state.db`, `unified_memory.db`, `agent.log`, `gateway-starts.log`, ...) were `1000:1000` mode 0600 → same denial on any of them.
- **Fix:** `chown -R hermes:hermes` all `/opt/data` runtime DBs/logs; `chmod 0664` `state.db`/`agent.log` family. Extended the image cont-init `015-supervise-perms` with a guarded, idempotent chown block so it survives `docker restart`.
- **Status:** gateway stable PID 94359 (05:33 boot), elapsed 40s+, STABLE=yes (same PID over 8s), 0 crash banners, hooks loading.

### 2. Stale plugin bytecode → "Pasted JD text is too short"
- **Cause:** the gateway imports `hermes_plugins.career_ops_pipeline` **once at boot** into `sys.modules` (never auto-reloads). The loaded copy lived at `/opt/hermes/.hermes/plugins/.../__init__.py` (a **second** location from the edited `/opt/data/plugins/...`). A stale `.pyc` + the gateway's long-lived in-memory module meant `_extract_job_urls` returned **0 URLs** for the AMD URL → the 88-char URL became `jd_text` → `pasted-jd` sentinel → line 110 error. Confirmed in `gateway.log`: "detected 0 job URL(s), pasted JD (88 chars)".
- **Fix:** the on-disk plugin (both copies now identical, current) has `_extract_job_urls` + `GENERIC_URL_PATTERN` which **do** return the AMD URL. Purged stale `__pycache__` in BOTH plugin dirs + touched source → forced recompile on next import. Restarted gateway so it re-imports the current module.
- **Verified (file-based, clean-literal):** gateway-loaded `/opt/hermes/.hermes/plugins/.../__init__.py`'s `_extract_job_urls("Run job pipeline: https://careers.amd.com/...88597...")` → `['https://careers.amd.com/...88597...']`, `routes_url_path=True`, `NOT_line110=True`.

### 3. AMD JD "too short" → JSON-LD extraction
- **Cause:** AMD embeds the full JD as JSON-LD `JobPosting` inside a `<script>` tag; `fetch_jd` stripped all scripts before extracting text → ~345-char placeholder.
- **Fix (committed `cc817e8`):** `_extract_jd_from_jsonld()` harvests `description` from `application/ld+json` before stripping; preserves `<p>/<br>/<li>` as newlines; decodes entities.
- **Verified:** `fetch_jd(AMD url)` → 4901 chars, `has responsibilities:True`, company=AMD, title="Principal Technical Program Manager". (Also added Playwright+Chromium host fallback for JS pages; committed `d6a0cc3`.)

### 4. Resume/cover PDF gate mismatch → no PDF generated
- **Cause:** `apply.conf` sets `APPLY_MIN_SCORE=52` (a 0–100 **%**), but `auto_pipeline.py` gated PDF gen with `score(2/5) >= args.min_score(default 3.0)` (0–5 scale). Plugin never passed `--min-score` → 2<3.0 → skipped. The 52% ATS keyword coverage (which SHOULD qualify) was ignored.
- **Fix (committed `5673650`):** `auto_pipeline.py` reads `APPLY_MIN_SCORE` from `apply.conf` as the `--min-score` default; when `min_score > 5` (percentage scale), the gate compares the **ATS coverage %** (`eval_data.ats_keyword_match.coverage_pct`) instead of the 0–5 score. Scale-aware labels.
- **Verified (dry-run):** AMD → `ATS keyword match: 52% coverage (40/77 terms)` → `Generating customized resume... (ATS coverage 52% >= 52.0)` → `✓ Customized resume PDF: Rohit Mishra - Resume (TITLE Principal Technical Program Manager).pdf` + `Cover Letter: ✅`.

### 5. GDrive "August 2026 missing" — not a bug
- The report was pushed to `gdrive:Job Hunt/August 2026/Careers - TITLE: Principal Technical Program Manager/176-careers-2026-08-31.md`. Confirmed via `rclone lsf` (5/5 files incl. resume + cover for run #180). If not visible, user is browsing a different Google account than `rohitmishra1278@gmail.com`. Also rclone NOTICE: shared client_id retiring in 2026 → switch to own client_id (non-blocking).

### 6. s6 launch flag
- `gateway-default` s6 service used `--replace` (which exits immediately under supervision → 3s banner crash-loop). Changed live `/run/service/gateway-default/run` to `--no-supervise` (foreground). ⚠️ `/run` is tmpfs → reverts on full `docker recreate`-from-image. The image template source (where `gateway-default/run` is generated — appears to be `profiles.py`'s `_seed_supervise_skeleton`, NOT a static commited file I located) is **not yet patched** — flagged as follow-up (boot-breaking risk to blind-edit; the `015-supervise-perms` chown now keeps the gateway stable regardless).

## Live evidence the gateway executed a SUCCESSFUL AMD run post-fix
`career_ops_pipeline_debug.log` latest entry:
```
[2026-09-01T05:07:45.032904] exit=0
URL: https://careers.amd.com/careers-home/jobs/88597?lang=en-us
[4/6] Generating customized resume, cover letter, LinkedIn messages (ATS coverage 52% >= 52.0)...
  ✓ Customized resume PDF: Rohit Mishra - Resume (TITLE Principal Technical Program Manager).pdf
RESULT_JSON {... "resume_path":".../output/Rohit Mishra - Resume (...).pdf", "cover_path":".../output/Cover_Letter_careers.pdf" ...}
Pipeline Complete — Score: 2/5 | Maybe
✓ Pushed: Rohit Mishra - Resume (...).pdf
✓ Pushed: Cover_Letter_careers.pdf
✓ Pushed: 180-careers-2026-08-31.md
✓ Pushed: linkedin_referral_connection.txt
✓ Pushed: linkedin_referral_cold.txt
GDrive: 5/5 files pushed to Job Hunt/August 2026/Careers - TITLE: Principal Technical Program Manager/
```
So the gateway's `_run_pipeline(AMD url)` → SSH to host → `auto_pipeline.py <url>` → `fetch_jd` (4901-char JSON-LD) → coverage-gated resume → GDrive push **already works end-to-end** (just not via the user's Telegram re-run window, which hit the stale-process window).

## Current gateway state (as of handoff)
- PID 94359, `hermes gateway run --no-supervise`, stable (not crash-looping), hooks loaded.
- Plugin on disk (both `/opt/hermes/.hermes/plugins/...` + `/opt/data/plugins/...`) identical + current; stale pycs purged; source touched so hermes recompiles on next import.
- `agent.log` + all `/opt/data` DBs/logs owned hermes; cont-init hardened to re-chown at boot.

## For the E2E Telegram suite session
- Trigger phrase the gateway's `pre_gateway_dispatch` matches: `Run job pipeline: <url>` or `job pipeline: <url>` or `run pipeline: <url>` (case-insensitive, `startswith`). The AMD URL alone (no trigger phrase) also works via `_extract_job_urls` GENERIC fallback.
- Plugin source: `hermes_plugins.career_ops_pipeline` namespace resolves to `/opt/hermes/.hermes/plugins/career_ops_pipeline/__init__.py`.
- Pipeline entry: host `/home/rohit/projects/career-ops/auto_pipeline.py <url>` (SSH from container as `rohit@127.0.0.1` via `/opt/data/.ssh/id_ed25519`).
- Gating: `APPLY_MIN_SCORE=52` (coverage %) — PDF generated iff ATS coverage ≥ 52%.
- Outputs: `output/Rohit Mishra - Resume (TITLE <title>).pdf` + `output/Cover_Letter_<slug>.pdf` + `reports/<NN>-<slug>-YYYY-MM-DD.md` + `output/linkedin_referral_*.txt` → pushed to `gdrive:Job Hunt/<Month YYYY>/<title>/`.
- Expected AMD result to assert: coverage 52%, score 2/5 (or 3/5 — LLM-proxy variance), resume_path + cover_path non-empty, 5/5 GDrive files, no "too short" error.

## Things still NOT done (optional follow-up)
- Persist `--no-supervise` into the image source (`profiles.py:_seed_supervise_skeleton` or wherever `gateway-default/run` is generated) so it survives `docker create`-from-image. (Not a current blocker — `/run` persists across restarts.)
- Switch rclone GDrive remote to a personal client_id (shared client_id retires 2026).

---
## UPDATE 2026-09-01 ~10:55 UTC — GDRIVE VISIBILITY RESOLVED

Context: user could not see the August 2026 folder in Google Drive.

Root cause: CLOUD side was always fine on rohitmishra1278@gmail.com.
  - `gdrive:/Job Hunt/August 2026/Careers - TITLE: Principal Technical Program Manager/`
    → verified via rclone (as user's token): all 7 files present
    (Rohit Mishra - Resume (TITLE...).pdf 17015B, Cover_Letter_careers.pdf 11206B,
     181/180/176-careers-2026-08-31.md, 2 referral txt).
    Folder ID = 1HyEZSACA-JqK1q-nNg9O12wjFgan9TKe
    Link      = https://drive.google.com/open?id=1HyEZSACA-JqK1q-nNg9O12wjFgan9TKe
  - Months present at Job Hunt/: June, July, August, September 2026.

The invisible gap = Google Drive for desktop on the Mac was STALE / partially synced:
  - Mac's `/Users/rohitmishra/My Drive/Job Hunt` listing shows only:
    Job Submissions/ June 2026/ May 2026/ Old/ Resumes/ + loose files.
    MISSING: July 2026, August 2026, September 2026 (all exist in cloud).
  - Mac's local rclone has NO token ("empty token found - please run rclone config reconnect gdrive:")
    → any Mac-side rclone read failed, reinforcing the illusion the folder is absent.

User-visible fix: open the folder link above in a browser signed in as
rohitmishra1278@gmail.com; OR (desktop) restart Google Drive + set Preferences→Sync to mirror all folders.

GDRIVE TOKEN STATE (both Mac + homelab gdrive: remote):
  - Re-authed to rohitmishra1278@gmail.com via Google Cloud project homelab-n8n-492218,
    desktop OAuth client "Chaguli Agent" (ID 1043252202614-ldm275e1022vtkf59eh80u3bk1uktp4i.apps.googleusercontent.com).
  - Shared rclone anonymous client is being retired 2026 → personal client_id REQUIRED. Flagged for suite.
  - rompecabezas: Mac's rclone conf still lacks a stored token (config create was run; authorize printed a blob
    but the local ~/.config/rclone/rclone.conf token is empty) → will need `rclone config reconnect gdrive:` on MAC.
