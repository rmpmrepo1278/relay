# Free-tier LLM capacity: estimate + quota tracker (2026-09-08)

## Objective
Answer "how many tokens/requests do the free cloud LLMs give" and then build a mechanism to track real free-tier usage against allowances.

## Estimate — free-tier limits (measured/published, as of 2026-09-08)

### Live-measured
- **Xkiro**: 5,000,000 free tokens/day, sliding 24h window. Live `/v1/usage` shows limits: `{"free_tokens":{"used_today":2317,"limit_per_day":5000000,"remaining":4997683},"wallet":{"balance_usd":"5.00"}}`. Biggest genuine free engine; wallet even has $5.
- **OVH AI Endpoints**: anonymous, no key, hard 2 RPM/IP. No usage API.
- **Apinex**: `/v1/balance` → `balance_usd=$0.000289`, `spent_usd=$0.10`. The free 500K "Telegram bonus credits" are essentially spent; the `free/*` legs still work because they proxy to backend free tiers (gemini/deepseek/glm free). Balance API shape: `{"object":"balance","balance_usd":...,"api_key":{"spent_usd":...,"spend_limit_usd":null,...}}`.

### Published/best-known
- Gemini (AI Studio): ~1M tokens/day, 15 RPM, ~1,000-1,500 RPD continuous. Best sustained free tier.
- Cerebras: ~1M tokens/day, ~30 RPM.
- Groq: ~6k tokens/min, ~1,000 RPD, 30 RPM (token-limited, not/day).
- OpenRouter: `:free` models, 20 RPM / 50 RPD (→1,000/day with $10 top-up).
- NVIDIA NIM: ~1,000 RPD.
- SambaNova: $5 trial credits (likely spent).
- freemodel-dev: dead ("Insufficient balance", 401).
- Mistral (not wired): ~1B tokens/month experiment tier.

### Bottom line
Combined theoretical ~7M tokens/day, but request caps (RPD 50–1,500) are the real ceiling. Practical sustained: ~2k–6k requests/day; Xkiro + Gemini + Groq do the heavy lifting. Bounded more by requests/day than tokens.

## Quota tracker — deployed
`/home/rohit/scripts/omniroute-quota-tracker.py` (stdlib-only, cron every 15 min → `/home/rohit/logs/omniroute-quota-tracker.log`).

Cron: `*/15 * * * * /home/rohit/scripts/omniroute-quota-tracker.py >> /home/rohit/logs/omniroute-quota-tracker.log 2>&1`

### What it does
1. Aggregates real usages from OmniRoute `call_logs` (storage.sqlite) per provider/day, last 7 days → requests/ok/err/tokens_in/tokens_out/duration.
2. Polls live usage endpoints: Xkiro `/v1/usage`, apinex `/v1/balance`.
3. Upserts history into `/home/rohit/.omniroute/tracker/usage.sqlite`:
   - `daily_usage(day, provider, requests, ok_requests, err_requests, tokens_in, tokens_out, duration_ms)`
   - `live_snapshots(ts, provider, raw)` — every poll even on error.
4. Prints a per-provider daily summary + 7-day totals.

### Keys
Added to `/home/rohit/.omniroute/.env`: `XKIRO_API_KEY`, `APINEX_API_KEY` (sourced for polls).

### Gotchas (learned)
- Xkiro/apinex sit behind **Cloudflare** — urllib default UA gets `403 error code: 1010`. Must send `User-Agent: curl/8.5.0` (or browser UA).
- `aggregate_call_logs` must query `storage.sqlite` (call_logs), NOT the tracker's own `usage.sqlite` — initial wiring bug.
- Providers without a usage/balance endpoint (OVH, groq, etc.) are tracked only via call_logs aggregation; no live ceiling value.

### First-run facts (2026-09-08)
Today via call_logs: apinex 117 req (102 ok, 47855 tok_in), openrouter 94 req (92526 tok_in), gemini 153 req (73 err — quota 429s), groq 107 req, cerebras 85 req, xkiro 14 req, ovh 11 req; local-gemma 53 req. felo-web/duckduckgo-web/auto/opencode rows are other non-LLM tools logging into call_logs — harmless.

## Status
Tracker live and verified. Future: alert when xkiro remaining <10%, add Gemini quota API if a key exists, keep journal updated on weekly spend.

Journal prev: relay-omniroute-free-capacity-2026-09-08.md. Next: relay-omniroute-quota-tracker.md.
---

## Addendum (2026-09-08 19:30Z — audit complete)

### Audit run summary (Claude Code, homelab, ~2 hrs)
- 1,513 total calls, 19.86M input tokens, 409k output tokens — **0 billable tokens paid**.
- Live polls: Xkiro 80,904/5,000,000 tok/day used (98.4% left) + $5 wallet; apinex balance $0.0003 (spent $0.10).
- Top winners: openrouter 389k out / apinex deepseek 16.5k / local gemma 1k / xkiro 1.08k.
- Error mix today: 123×429, 103×413 (groq input ceiling), 30×502 (transient), 22×402 (quota), 30×401 (freemodel dead).

### Re: circuit-breaker follow-up — already built-in
Proposed a custom circuit-breaker tracker. **It already exists in OmniRoute v3.8.49** (FSE-04 Resilience layer, `src/shared/utils/circuitBreaker.ts`):
- CLOSED → DEGRADED (~3 fails) → OPEN (5 fails) → HALF_OPEN → CLOSED.
- cooldowns: `rate_limit` 60,000 ms; `quota_exhausted` 3,600,000 ms.
- exponential backoff (16x max), 3 escalation cycles before backoff ramps.
- smart 429 classification `classify429FromError` distinguishes rate-limit vs quota-exhausted (avoids the "individual quota reached / 164h reset" misclassify bug referenced in source).
- DB-persisted via `domainState.ts`; readable by `healthReport` skill (`/api/health` shows per-provider state/failures/retryAfterMs).
- Local lifecycle errors (`Controller is already closed`, aborts) excluded from failure count (#4602), so bridge bugs don't blackhole a provider.

So no standalone tracker circuit was needed — OmniRoute's router already trip-cooldown-retry on dead legs. The audit's free-tier walk completed cleanly with no manual reroute.

### Tooling stays
- /home/rohit/scripts/omniroute-quota-tracker.py (cron */15, log at /home/rohit/logs/omniroute-quota-tracker.log, sqlite at /home/rohit/.omniroute/tracker/usage.sqlite).
- Journal next: none unless free-tier policy changes.
