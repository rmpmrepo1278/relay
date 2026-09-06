# Humanizer patterns folded into career-ops voice guide (2026-09-05)

## What
Folded humanizer skill v2.11.2 (35 patterns, Wikipedia "Signs of AI writing") into the
career-ops machine-usable voice guide: `modes/_profile.md` → "## Writing Style" block
(the authoritative version per `rohit-voice-dna.md`; career-ops reads it first and it
overrides everything).

## Changes (in modes/_profile.md; backup `_profile.md.bak-prehumanizer-2026-09-05`)
1. **Extended AI-tell word list** (was 34 words) adding humanizer §7 words:
   actually, additionally, align with, vibrant, profound, rich (figurative), nestled,
   renowned, stunning, breathtaking, emphasizing, interplay, quietly, valuable, noteworthy.
2. **New "Humanizer anti-tell self-check" section** (16 structural rules, generation-time,
   placed before the "Self-check before any output ships" gate):
   vague sources (§5), qualifier-stacking (§24), not-only-but + clipped negatives (§9),
   false from-X-to-Y ranges (§12), announcing the next point (§28), fake-candid openers
   (§33), answering objections no one raised (§34), rejecting fake alternatives (§35),
   formulaic sayings (§32), forced drama fragments (§31), generic-optimism closers (§25),
   heading restated in first sentence (§29), curly→straight quotes (§19), filler phrases
   (§23), hyphen die-down (§26).
   Already-covered patterns left in place (no duplication): em dashes (§14), not-X-but-Y
   reframes, rule-of-three (§10), participle padding (§3), copula avoidance (§1/§8),
   assistant leakage (§20/§22), title case (§17), hedge stacks, generic openers.

## Effect
Patterns now apply at GENERATION time (the proxy drafts clean text), not post-processed.
career-ops reads _profile.md live; auto_pipeline.voice_gate.py still runs its lexicon
check as the final gate.

## Not committed upstream
career-ops repo left uncommitted (user repo; awaiting their commit). This memory journal
is committed as usual.