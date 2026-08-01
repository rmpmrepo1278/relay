# Mini-PC Purchase Decision — 2026-08-01

Follow-up to the agentHarness audit (journal/relay-audit-2026-08-01.md). Completing the mini-PC
purchase comparison: used/refurb/ITX options vs new prebuilts, with live-verified prices.

## Verified prices (read off retailer pages — standing rule)

| Option | Spec | Price | Source |
|---|---|---|---|
| BOSGAME M6 | HX370 / Radeon 890M / 32GB DDR5 / 1TB | **$969** (ground truth) / $999.99 | bosgame.com (user screenshot) / Newegg 2W1-003S-00006 |
| GEEKOM A9 Max | HX370 / 890M / 32GB / 1TB | **$1,189.99** | Newegg N82E16883985015 |
| Beelink SER8 | 8745HS / 780M / 32GB / 1TB | **$869** | Amazon B0D5BCLKYT |
| HP EliteDesk 705 G5 (refurb) | R5 3400GE / Vega 11 / 8GB / 256GB | **$179.99** | Newegg 1VK-001E-4TMB6 (BuyCoolGadgets) |
| Beelink SER9 (Amazon.in) | Ryzen H255 / 780M / 32GB LPDDR5X / 1TB | **₹1,38,783** (~$1,630) | Amazon.in B0FJ5HV1QQ (URL B0DZNHJ969 now resolves here) |
| Beelink SER8 (Amazon.in) | 8745HS / 780M / 32GB / 1TB | **₹1,26,109** (~$1,480) | Amazon.in B0F1D91CDR |

## Key architectural findings

- **Vega iGPUs have NO ROCm** (Vega 7/8/10/11: 5600G, 3400GE, 3550H, 3750H). Vulkan-only via
  llama.cpp → ~9–14 tok/s 8B Q4, CPU-inference territory. ROCm starts at RDNA2+ (780M).
  → Used AMD-Vega office minis are cheap docker/Jellyfin boxes, NOT LLM boxes. The $179.99
  refurb HP 705 G5 confirms this category is a dead end for the LLM role.
- **RDNA3 iGPU benchmarks**: 780M ≈ 18–22 tok/s 8B Q4; 890M (HX370, 16 CU) a step up. Discrete
  GPU (used RTX 4060 8GB) ≈ 35–40 tok/s — ~80% faster, but needs a tower + 200W.
- **RAM crisis**: prebuilts bundle RAM/SSD at OEM pricing; barebone + parts (X1 Pro-370 $695,
  MS-A1 AM5 route) lose badly when DDR5 SO-DIMM is $376–578 for 32GB. Buy prebuilt.
- **India availability**: BOSGAME A9 Max-class HX370 boxes not on Amazon.in (importer-only).
  Amazon.in SER8/SER9 carry a ~50% premium over US street price. If US shipping route exists,
  buy at US price.

## Honest recommendation

1. **BOSGAME M6 @ $969** — best fit for the assigned role (fast 9B via ROCm/890M + Jellyfin +
   Immich ML + Docker, dual 2.5GbE for exo + replication). Step up from the planned
   8745HS/16GB/780M config (890M > 780M, 32GB > 16GB).
2. SER8 @ $869 is close but same-CPU-class redundancy; A9 Max @ $1,189.99 adds $220 for the same
   SoC — skip unless the $999.99→$1,189.99 spread bothers you and brand/warranty (Amazon) matters.
3. Refurb HP 705 G5 @ $179.99 — only as a cheap secondary docker/Jellyfin box; not the LLM server.

## Next actions (blocked/unverified)

- bosgame.com direct webfetch still 429 → M6 $969 stands on user-screenshot ground truth.
- MS-A1 barebone $239.90 from a review (CraftRigs 2026-04) — NOT quoted per standing rule; store
  429s.
- Used RTX-4060 build (~$670–750) and eBay.de Xeon+3060 (~€795) are snippet numbers — unverified.
- India import math: SER8 US $869 + shipping (~$75) + GST 18% ≈ ₹94k — still beats Amazon.in ₹1,26,109.
