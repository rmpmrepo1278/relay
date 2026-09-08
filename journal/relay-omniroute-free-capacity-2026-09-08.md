# OmniRoute free cloud capacity expansion (2026-09-08)

## Objective
Add more free cloud LLM capacity to the `pi-free-fallback` combo, on top of Xkiro (see relay-xkiro-omniroute-2026-09-08.md).

## Survey — what's wired vs usable
Already-connected provider_connections: cerebras, freemodel-dev, gemini, groq, nvidia, sambanova, openrouter, apinex (openai-compatible-chat-936e95e2...), xkiro (e58e7038...), ollama-local, magnitude, magnitude-lite.

Live tests (through router at 127.0.0.1:20128, x-api-key sk-79bf69b...) concluded:
- **apinex free legs WORK** (free 500K bonus credits): `free/deepseek-v4-flash-0731`, `free/deepseek-v4-pro-0813`, `free/gemini-3.8-flash`, `free/gemini-3.1-pro`, `free/gpt-5.6-luna`, `free/qwen-3.8-max`, `free/glm-5.3-flash`. BUT `claude/sonnet-5` and all premium Anthropic models ALWAYS 402: "Anthropic models are not available with the free 500,000 Telegram bonus credits. Please top up" — that combo leg was dead weight.
- **freemodel-dev is NOT usable** — `freemodel-dev/gpt-5.6-*` → "Insufficient balance" (401) even though provider status says active. Dead until topped up.
- **groq, cerebras, nvidia, gemini, sambanova, openrouter** show status active but their earlier 402/429 in call_logs were quota-credit-related, not structural. groq served fine during these tests.
- **New: OVH AI Endpoints** added as openai-compatible-chat-5392ae69-4caf-4a16-919c-dbaa1d3855f4 — ANONYMOUS, NO KEY. baseUrl `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`. Verified `Qwen3.6-27B`, `gpt-oss-120b`, `Meta-Llama-3_3-70B-Instruct`. Hard cap 2 RPM/IP, and routers treat cooldowns as model_cooldown; use as tail/emergency only.

## Combo changes (pi-free-fallback, now v8, 14 legs)
- Replaced dead `claude/sonnet-5` premium leg with `free/deepseek-v4-flash-0731` (pi-fb-0a).
- Added apinex free legs pi-fb-7/8/9 (deepseek-v4-pro-0813, gemini-3.1-pro, qwen-3.8-max).
- Kept xkiro legs (m3/dsf/sst/min8) + local executor tail.
- New leg `ovh-qwen` = Qwen3.6-27B via OVH (last cloud leg before local).
- Effective order: apinex-free (x4) → groq → openrouter → apinex-free (x3) → xkiro (x4) → ovh (x1) → local gemma.
- Verified: combo-as-model `pi-free-fallback` → 200 served by pi-fb-0a (free/deepseek-v4-flash-0731) with "WALK" text.

## Takeaways
- apinex = the single biggest free cloud source we already had wired but underused (7 working free legs, fast).
- OVH = free without signup but rate-critical (2 RPM/IP); bumped by router cooldown state.
- "connection-test" appears in call_logs after restart with status 200 = provider health re-test.
- Transient "No active credentials for provider" / empty-content reads during testing were model_cooldown windows, not config errors — re-test after ~30s.

## Status
Done. Combo healthy v8. Journal prev: relay-xkiro-omniroute-2026-09-08.md (Xkiro 4 legs). Backups: /home/rohit/.omniroute/db_backups/storage-pre-xkiro.sqlite.