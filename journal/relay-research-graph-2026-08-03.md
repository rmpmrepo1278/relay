# Relay — CRG/Graphify Wired into Research Pipeline (2026-08-03)

## What shipped
- **research_engine.py** — CRG blast-radius, architecture, and search injected into `evaluate_item()` for GitHub repos. Graph context (`_graph_context`) attached to each scored item including blast-radius impact, architecture snippet, and graph matches. Graph stats (nodes/edges) included in recommendation output.
- **daily_research.py** — CRG blast-radius check in `assess_impact()` appended to impact labels (e.g., "transformational [high blast-radius]"). Graph stats (nodes/edges/files) printed during daily run output.

## Commit
- `da3dd0b` on `chaguli/master` (pushed) — 2 files changed, 42 insertions, 4 deletions

## How it helps daily
- When the research engine scores a new repo, CRG auto-queries blast-radius and architecture — no manual graph lookup needed.
- High-blast-radius repos get flagged in the impact label so you can review before deploying.
- News articles about new tools are cross-referenced against the code graph to assess actual relevance to the homelab stack.
- Token savings: CRG returns structured data in milliseconds instead of sending raw repo text to the LLM for analysis.
