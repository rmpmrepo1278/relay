# Relay — Yum! Brands Director PMO pipeline run (2026-09-10)

## Job
- **Director, Portfolio Delivery and PMO** @ Yum! Brands (Taco Bell Byte), Plano TX, hybrid. Salary $202.5K–$238.2K. url https://www.linkedin.com/jobs/view/4450171948/

## What ran
- Fetched JD from LinkedIn (webfetch worked, full JD captured). Saved to `jds/yum_pmo_jd.txt` (8,051 bytes).
- `run_pipeline.py` first pass: **evaluation proxy DOWN** (localhost:8080 refused; Hermes tool + OpenRouter fallback both failed) → score 0/N/A, resume generated WITHOUT ATS stitch (16,587 B). Caught & re-ran manually via auto_pipeline API with `_compute_ats_keyword_match` (ATSD coverage 47%, 12 missing) → proper build 16,658 B, both lint gates clean.
- Cover `Cover_Letter_yum-brands.pdf` 8,853 B. LinkedIn msgs regenerated with real URL.
- Pushed 4 files → `gdrive:Job Hunt/September 2026/Yum! Brands - Director, Portfolio Delivery and PMO/` @ 14:35.
- DB row 99 via `track_application` (status=applied, jd_snippet backfilled).

## Bug found & fixed (run_pipeline.py)
- `generate_linkedin_messages(company, title, jd_text, company_slug)` was passing the **full JD text into the url slot** → "Job URL:" line dumped 8KB of JD into the referral txts. Fixed: `run(..., url="")` kwarg + `--url` CLI arg, threaded through main. Verified import.
- Evaluation fallback note: when the OpenRouter proxy (localhost:8080) is down, run_pipeline degrades silently (score 0, no ATS stitch). Deterministic `_compute_ats_keyword_match` path via auto_pipeline API is the reliable route — same as the Paylocity/Fluence recipe.

## Regression suite unaffected (suite tests only resume_generation, not run_pipeline) — 6/6 green.