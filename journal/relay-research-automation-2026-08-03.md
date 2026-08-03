# Relay — Automated Research Pipeline with CRG/Graphify (2026-08-03)

## What shipped
- **homelab_research_pipeline.py** — unified automated pipeline that chains:
  1. Discovery (daily_research.py + research_engine.py)
  2. CRG/graphify assessment for each discovered item
  3. Ranking and recommendation
  4. Telegram notification via bridge
- **homelab-research.service** — systemd oneshot service
- **homelab-research.timer** — daily timer at 06:00, persistent (catches missed runs)
- Timer enabled and active — first run scheduled for 2026-08-04 06:00

## Verified
- Pipeline ran manually: 20 items assessed with CRG/graphify in ~30 seconds
- Token savings: 87% (5026 tokens without CRG → 650 with CRG per assessment)
- CRG graph: 1148 nodes, 13637 edges across 3 registered repos
- Systemd timer active, will run daily at 06:00

## Commits
- `8b7c5b2` on `chaguli/master` (pipeline script)
- `ba89cd0` on `chaguli/master` (systemd service + timer)
