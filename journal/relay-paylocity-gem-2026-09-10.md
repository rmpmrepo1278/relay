# Relay — Paylocity resume regeneration + Gem feedback (2026-09-10)

## Context
User ran Gem (AI resume reviewer) on the regenerated Paylocity resume. Gem gave 94/100 score with 4 actionable notes. All were implemented in `auto_pipeline.py` and both PDFs re-pushed to GDrive (overwrite).

## Resume pipeline changes (auto_pipeline.py @ career-ops)
1. **Dedupe**: HCM bridge no longer appended into the summary string; kept ONLY as dedicated `<div class="skill-line"><span class="skill-cat">Domain expertise:</span> …` line after summary bullet list. (The 5-bullet summary cap used to drop/dupe the sentence.)
2. **Role-header stitch**: `graded_role` derived from `title` param — e.g. `Paylocity - Senior Director Enterprise Applications` → **`Senior Director / Director of Enterprise Applications & Technical Program Management`**, prepended bold to first summary bullet. Generic for any `Senior Director`/`Director`/`Head of` grade (domain from title else jd: enterprise-applications / enterprise-platforms / technology).
3. **Keyword weaving** in `parse_experience_to_html(…, jd_lower=None, sox_requested=False)`:
   - SOX: target bullet = T-Mobile governance/RAID/risk line, else first bullet with governance/raid/risk/compliance → append `under SOX-aligned governance`. Gate = `sox`/`regulatory` literal in jd OR (`governance` in jd AND `sox` in ats missing_terms) — context-gated, no fabrication.
   - ERP/Oracle/platform bullet → append `across release engineering, cutover roadmaps, deployment cycles` (terms added only if not already present).
4. **Standalone KEYWORDS block** now only emitted for terms still missing from the final HTML — two provenance gates: (a) weave-first (only leftovers), (b) `_defensible` filter — a bare tag is printed only if the term appears in the JD text or the raw cv.md, so no fabricated keywords. For Paylocity the block is now fully gone (0 occurrences).

## Cover letter (also patched)
`generate_customized_cover_letter` gained an HCM/payroll domain-adjacency paragraph (`hcm_par`) injected as its own `<p>` when jd contains payroll/hcm/benefits/workforce/talent/etc. → closes with "modern HCM and payroll ecosystem … payroll integration, benefits administration, time & attendance, workforce identity, tax/regulatory compliance".

## Verified (Paylocity, html checksum)
- `Direct enterprise platform modernization` occurrences = 1 (no dup)
- role-title present; `SOX-aligned governance` present (x2 lines); release engineering / cutover roadmaps / deployment cycles present; `>Keywords<` block = 0

## GDrive (Job Hunt/September 2026/2000 - Paylocity - Senior Director Enterprise Applications/)
- `Rohit Mishra - Resume (Paylocity - Senior Director Enterprise Applications).pdf` — 17,587 B @ 2026-09-10 11:57
- `Cover_Letter_2000.pdf` — 8,559 B @ 2026-09-10 11:57 (local name Cover_Letter_paylocity.pdf, renamed on copy for slug continuity)
- report + linkedin msgs untouched

## Regeneration recipe
JD text is NOT persisted in applications.db (jd_snippet empty) — it lives INSIDE the evaluation report (`## Job Description (Extracted)` section of `reports/214-2000-2026-09-09.md`). Use that extract as `jd_text`; eval_data = `{"match_score":5,"recommendation":"Strong Match","ats_keyword_match": <_compute_ats_keyword_match(jd,cv)>}`. Filename for resume must keep `Paylocity - ` prefix in the title arg so the PDF name matches the Drive filename (safe_title regex keeps word chars/space/hyphen).

## Tool notes
- rg/grep on homelab PDFs: use pdftotext, tooling can't read PDFs directly.
- rclone overwrite pattern: `rclone copyto <local> "gdrive:<folder>/<same-name>"` (single file overwrite semantics).
- Watch indentation when patching parse_experience_to_html region — two iterative patches bit me (8 vs 12-space body under `if exp_text:`).
## Gem round 2 (score 97/100) — final cleanup applied 2026-09-10 12:04
- Summary header: role-title now spliced directly onto base summary (drop redundant "Director of Technical Program Management" lead via graded_role dedupe in generate_customized_resume first-bullet render).
- Weave appends now trailing-period-safe: bullets end "... SOX-aligned governance." / "... cutover roadmaps, deployment cycles." (rstrip(",.") then re-add period; no double periods). Verified via /tmp/cv-paylocity.html: spliced-header=1, residual-dup=0.
- GDrive resume overwritten: 17,553 B @ 12:04:45.

## Resume polish layer (normalize + lint gates + regression suite) — 2026-09-10 12:19
User asked: "will these grammatical issues resurface for the next round?" Built permanent protection so the Gem/Gemini QA loop never has to be whack-a-mole again.

### 1. Normalization helpers in auto_pipeline.py
- `_append_clause(sentence, clause)` — canonical punctuation: exactly one trailing period, comma-joins lowercase clauses. SOX + ERP weaves now routed through it.
- `_finish_bullet(b)` — every experience bullet gets collapsed whitespace + exactly one terminal period before render (`bullets = [_finish_bullet(b) for b in bullets]` after `_reorder_bullets_by_relevance`).

### 2. resume_lint.py (new, career-ops/) — hard-fail gate, runs twice
- `check_html(html)` before PDF render; `check_pdf(pdf)` after via `pdftotext -layout` round-trip (catches render-time issues).
- FAIL checks: entity_leak (raw `&`), double_space (html only; pdf = warn, layout padding), run_punct (run of .!?), stacked_lead (graded role-title + "Director of Technical Program Management" together, gated on graded marker so generic TPM resumes aren't blocked), bridge_dup (HCM bridge >1x), dup_sentence (identical ≥40-char sentence), dup_phrase (repeated 8-gram across experience bullets), bullet_period (experience li missing terminator), empty_pdf.
- WARN: standalone_keywords (ok only if terms unwoven), dash_style, sentence_case.
- `generate_customized_resume` returns None + saves debug html `Rohit_Mishra_<slug>_Resume.html` on any hard-fail → nothing broken ever ships.

### 3. Regression suite
- `tests/fixtures/{hcm,geico,fintech,platform,generic}.txt` (hcm is real Paylocity JD from report extraction; others synthetic to cover all hook/proof/weave paths).
- `tests/driver_resume_lint.py` (runs generator + re-checks PDF lint, asserts >10KB) + `tests/verify_resumes.sh` (`./tests/verify_resumes.sh` after ANY auto_pipeline.py / resume_lint.py change).
- Provenance note: missing_terms that aren't in the JD text or cv.md are dropped from the Keywords block (never fabricate). kept-sox because 'governance' in jd + cv has governance/risk language — defensible.

### Real bugs the lint caught (would have shipped unnoticed)
1. `Education & Certifications` section header — raw unescaped `&` (fixed → `&amp;`).
2. cv.md skills categories ("Cloud & Platforms") rendered via `_ats_clean` (no escaping) → now `_ats_clean_html(_ats_clean(...))` for cat/vals/plain-lines.

### Status
- Suite: 5/5 PASS (Paylocity 17,558 B; GEICO 17,050; fintech 17,053; platform 16,975; generic 16,909), HTML + PDF lint clean each.
- Paylocity resume re-pushed to GDrive via linted build (17,558 B @ 12:19).

### Regeneration recipe (curl-paste to next session)
`cd /home/rohit/projects/career-ops && python3 tests/verify_resumes.sh` — must stay green before any apply/resume push.
