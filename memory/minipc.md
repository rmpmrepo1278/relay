---
created: 2026-08-01
confidence: high
source: live-verified retailer pages + homelab workload analysis
status: decision pending Rohit's buy (recommendation: BOSGAME M6)
---

# Mini-PC Augment — Purchase Decision

Decision record for the homelab mini-PC purchase. Full detail in
`journal/minipc-decision-2026-08-01.md`.

## Recommendation
**BOSGAME M6 — HX370 / Radeon 890M / 32GB DDR5 / 1TB — $969** (bosgame.com, user-screenshot
ground truth; $999.99 Newegg).

Rationale:
- Fits the assigned role from `setup_minipc.sh`: fast 9B inference via ROCm/Vulkan iGPU, Jellyfin
  transcoding, Immich ML, heavy Docker, dual 2.5GbE for exo + backup replication.
- Step up from the planned 8745HS/16GB/780M config: 890M > 780M, 32GB > 16GB.
- RAM-crisis math: prebuilts bundle RAM/SSD at OEM pricing. Barebone routes (X1 Pro-370 $695,
  MS-A1 AM5) lose badly when 32GB DDR5 SO-DIMM costs $376–578. Buy prebuilt.
- A9 Max @ $1,189.99 = +$220 for the same SoC — skip unless Amazon-brand warranty wins.
- SER8 @ $869 is close but same-CPU-class redundancy (8745HS).

## Verified prices (read off retailer pages — standing rule)
| Option | Spec | Price | Source |
|---|---|---|---|
| BOSGAME M6 | HX370/890M/32GB/1TB | $969 / $999.99 | bosgame.com / Newegg 2W1-003S-00006 |
| GEEKOM A9 Max | HX370/890M/32GB/1TB | $1,189.99 | Newegg N82E16883985015 |
| Beelink SER8 | 8745HS/780M/32GB/1TB | $869 | Amazon B0D5BCLKYT |
| HP 705 G5 refurb | R5 3400GE/Vega 11/8GB/256GB | $179.99 | Newegg 1VK-001E-4TMB6 |
| SER8 (India) | 8745HS/780M/32GB/1TB | ₹1,26,109 (~$1,480) | Amazon.in B0F1D91CDR |
| SER9 (India) | Ryzen H255/780M/32GB LPDDR5X/1TB | ₹1,38,783 (~$1,630) | Amazon.in B0FJ5HV1QQ |

## Architectural rules discovered
- **Vega iGPU (7/8/10/11: 5600G, 3400GE, 3550H, 3750H) = NO ROCm.** Vulkan-only via llama.cpp,
  ~9–14 tok/s 8B Q4. ROCm starts at RDNA2+ (780M). Used Vega office minis = docker boxes, not LLM
  boxes.
- RDNA3 iGPU: 780M ≈ 18–22 tok/s 8B Q4; 890M (16 CU) a step up. Discrete used RTX 4060 ≈
  35–40 tok/s but needs tower + 200W.
- India: HX370 boxes (M6/A9 Max) not on Amazon.in — importer only. Amazon.in SER8/SER9 carry ~50%
  premium over US street. If US shipping route exists, buy at US price (SER8 US $869 + shipping +
  GST ≈ ₹94k < ₹1,26,109).

## Pending / unverified
- bosgame.com direct fetch 429 → $969 stands on user-screenshot ground truth.
- MS-A1 barebone $239.90 (CraftRigs review) — unverified, store 429s. Not quoted as live.
- Used RTX-4060 build ($670–750) and eBay.de Xeon+3060 (€795) — snippet numbers, unverified.

## Next actions
1. Rohit confirmed: **US-based, buys in USA** → ignore India/import routes. Purchase BOSGAME M6
   (or Newegg $999.99 variant) from a US retailer with a return policy.
2. Draft updated `setup_minipc.sh`: fix subnet scan to `192.168.29.x` (home-hp), set MINIPC_IP +
   Tailscale before first run. Onboarding ready for arrival day.
