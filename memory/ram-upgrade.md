---
created: 2026-08-01
confidence: high
source: live dmidecode (home-hp) + live-verified retailer pages
status: researched, decision pending — user confirmed US-based buyer
---

# Home-hp RAM Upgrade — 32GB → 64GB

## Hardware reality (verified live on home-hp via dmidecode)
- Machine: HP Pavilion 15z-eh000 (baseboard 87C5), Ryzen 7 4700U (Renoir)
- **2× SO-DIMM DDR4-3200 slots**, current config: **36GB = 32GB (Slot 1/A) + 4GB (Slot 2/B)** — asymmetric flex mode
- "Adding 32GB" = **swap the 4GB stick for a 32GB → symmetric 64GB dual-channel**
- SMBIOS "Maximum Capacity: 32GB" is a soft/HP-published cap — already disproven (36GB runs); Renoir officially supports 64GB
- HP community + Crucial confirm 2×16=32GB works; **2×32=64GB on this board is unverified** — plausible, but no confirmed report. Risk: no-POST.

## What 64GB buys on the homelab
- **Bigger LLMs**: qwen2.5:14b (~9-10GB resident) is current max; 64GB fits a 32B-class model (Q4 ~20GB) + all 5 resident models + DB cache.
- **But**: 4700U Vega iGPU has NO ROCm → big models = slow CPU inference only. Capacity up, not speed.
- **Page cache**: 21Gi now → 2×+ for the 4.6TB media library (Immich/Paperless reads).
- **DB buffers**: Immich/Paperless/Khoj Postgres can raise shared_buffers.
- Honest caveat: no current pressure (12Gi used, 21Gi available, not swapping). Headroom play, not a fix.

## Verified prices (read off retailer pages — standing rule)
### New, single 32GB DDR4-3200 SO-DIMM (what's actually needed — 1× 32GB to pair with existing 32GB)
| Stick | Price | Source |
|---|---|---|
| **Rimlance 32GB** | **$158.00** ← cheapest | Newegg |
| KingSpec 32GB | $189.99 | Newegg |
| Crucial CT32G4SFD832A 32GB | $215.10 | Newegg |
| Samsung 32GB | $219.99 | Newegg |
| SK hynix 32GB | $220.89 | Newegg |
| A-Tech 32GB | $242.49 | Amazon |
| Crucial 32GB (2×16 kit) | $213.00 / $190.99 TEAMGROUP / $188.99 Timetec / $185.88 NEMIX | Amazon/Newegg |

Note: 2×16 kits are cheaper but DO NOT satisfy the need (need single 32GB to replace the 4GB).

### Used / refurb
- **B&H Used dept (90-day warranty, free 2-day):** Crucial 32GB (2×16) kit **$201.95**; Crucial 64GB (2×32) kit **$438.95** — kits only, no single 32GB.
- **eBay search 403-blocked** from here → used-eBay single-32GB prices **unverified**, not quoted (standing rule).
- Newegg used: 0 matches for this part.

## Recommendation
- Cheapest verified path: **Rimlance 32GB $158 (Newegg)** — new, full warranty, less than any used price found.
- Used saves ~nothing vs Rimlance; skip unless a genuine eBay deal surfaces (verify on-page first).
- Low priority vs M6 purchase. If bought, buy from a returnable source (Amazon/Newegg) to test 2×32 64GB POST; if no-POST, return.
