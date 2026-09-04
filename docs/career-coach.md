# Career Coach — Agent for Landing a Director Role

> Owner: Rohit. Goal: land the next growth-level (Director) role in the near future.
> Design v1 — built on homelab patterns: scheduler-driven host agent, Telegram-first interaction
> (OpenCode for deep-dive/synthesis work), state-as-JSON in `~/.hermes/state/`, JSONL stores,
> and the existing career-ops base (`scripts/auto_pipeline.py`, `plugins/career_ops_pipeline`,
> `state/career_engine.json`, `data/career_batch_results.tsv`, resume at `data/career/*.pdf`).
> Status: **design + v1 scaffold (story bank core); deeper tracks in progress.** Last updated 2026-09-04.

## Why an agent (vs. a list of tips)
Every Director interview is about *evidence*: stories + metrics + clear articulation. That requires a
repeatable capture→shape→practice→measure loop. The coach automates the loop and keeps a persistent
bank of the owner's material so nothing dies in a chat window.

## Interaction model
- **Telegram-first**: commands routed like the existing `/job` handler in `plugins/career_ops_pipeline`
  (Hermes owns the bot; do NOT long-poll the same token — see `docs/agent-parliament.md` conflict note).
- **OpenCode sessions** for deep-dive synthesis (mock-interview debriefs, competency maps, content drafts)
  with outputs committed to `collaborator-memory` so all tools (Hermes/Claude/opencode) share state.
- Host scheduler jobs keep cadence (daily prompt, weekly mock, weekly LinkedIn nudge).

## Modules (tracks)

### 1. Story bank (`story_bank`)
- Guided STAR capture via Telegram (`/story new` → coach asks situation/task/action/result/metrics).
- Each story: id, title, category, STAR fields, metrics, competency tags, last_used, confidence score.
- Store: `data/career/coach/stories.jsonl`; index `state/career_coach/stories_index.json`.
- Coach quality-gates each capture (concreteness, numbers, outcome) and asks for a re-write when weak.

### 2. Deep-dive content (`deep_dive`)
- Maps stories → competency model; builds "tell me about yourself", 60-second and 3-minute narratives;
  derives an "aha metric per story". Output lives in `collaborator-memory/` for review.
- Competency model is Director-shaped (see §Benchmarks below).

### 3. Mock interviews (`mock_interview`)
- Role-play via Telegram (question → typed answer → coach feedback on clarity/structure/impact; score 1-5 +
  rewrite suggestion). Question bank keyed to the competency model + the owner's gap list.
- Logs: `state/career_coach/interview_log.jsonl`; weekly/10-run aggregate: weakest competencies, overused
  words, talk-time, metric density.

### 4. Speaking/clarity coach (`speaking_coach`)
- Feedback dimensions: STAR structure, anchoring numbers, removing hedge words, one-idea-per-sentence,
  audibility of impact. Applied inside mock interviews and to story rewrites.

### 5. LinkedIn & networking (`linkedin`)
- Profile gap analysis vs. target (headline, summary, contributions, recommendations).
- Outreach drafts (2-3 lines) to 1st/2nd-degree targets; connection cadence tracker; content calendar
  (1 post/week idea from story bank). Logs in `state/career_coach/linkedin.jsonl`.

### 6. Cadence & growth tracking (`weekly_review`)
- Daily: one story-prompt or micro-refine (Tue: capture / Thu: refine weakest story).
- Weekly: 1 full mock interview + debrief; LinkedIn cadence check.
- Monthly: deep-dive refresh + progress (interviews, stories banked, score trends) vs. target plan.

## Benchmarks (Director competency model — v1 proposal)
Strategy & Vision · Delivery at Scale · Stakeholder & Executive Communication · Talent & Org Building ·
Financial/Commercial Acumen · Risk & Crisis Leadership. Each story tagged with 2-3; interview banks keyed
to these. Model can be tuned once the target role/industry is confirmed.

## Repo layout (v1 scaffold)
```
scripts/career_coach.py            # CLI: story bank + mock + coach + weekly ops (host, scheduler-driven)
scripts/career_coach_data.py       # state/instrumentation (keep *_coach.py free of flask)
state/career_coach/                # stories_index, interview_log, linkedin, weekly state
data/career/coach/                 # stories.jsonl, narrative drafts
plugins/career_ops_pipeline/       # Telegram command router: /story /mock /coach /linkedin /career
skills/career-ops/career-ops-bundle/  # docs/skill bundle for the coach
```
Design mapping to Rohit's ask: stories+deep dive → tracks 1-2; mock interviews + coaching on content,
style, clarity → tracks 3-4; LinkedIn connections → track 5; "steps needed to land the role" → track 6.

## Next steps (build order)
1. story_bank capture+quality gate (v1, role-agnostic) — IN PROGRESS
2. mock_interview Q&A loop + scoring
3. Telegram command router (`/story`, `/mock`, `/coach`)
4. scheduler cadence jobs
5. deep-dive + linkedin tracks (OpenCode-assisted)
6. weekly_review + metrics dashboard