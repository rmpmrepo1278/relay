# Mac File Organization Pass — 2026-09-15

Scope: local Mac only (no homelab changes). Rohit asked to find duplicates and reorganize so he
always knows where to search. Confirmed scope: dedupe everything incl. archive; reuse existing
folder structure as canonical homes; delete junk + secure the Google client secret.

## Canonical "where to look" map (source of truth = single copy)
- Personal/legal/immigration/finance/medical/tax  -> `~/Desktop/Rohit Documents/`
  (Tax Documents/, Finances/, Medical/, USCIS Documents/, Rohit and Sunayana - Master Documents/)
- Career/resumes/cover letters                     -> `~/My Drive/Job Hunt/Resumes/2026/` (+ Archive/)
- Travel itineraries                               -> `~/My Drive/Travel/{Upcoming-Trips,Completed-Trips}`
- Academic/book PDFs (Buddhism, Orissa, art)       -> `~/Downloads/Buddhism/`
- Homelab/dev tooling & configs                    -> `~/projects/homelab-configs/`
- Career automation (n8n, html refs)               -> `~/projects/career-ops/`
- Photos (incl. DJI Japan 2024 footage)            -> `~/Pictures/`
- Old laptop archive (T-Mobile 2016-2023)          -> `~/Downloads/Rohit's Documents/` (4.4GB, untouched layout)
- Downloads = inbox only (3 items left)

## What was done
- Home root cleaned: removed 0-byte junk incl. a file with newlines in its name; stray
  docker-compose.qwen.yml + n8n json + 1040 PDF filed/deleted. Home root now has no loose files.
- Google client_secret_*.json moved from Downloads to ~/.hermes/ (where the Gmail import agent
  looks); github-recovery-codes.txt moved to ~/.ssh/ (chmod 600).
- 61-item Downloads root reduced to 3 items (wallet pass, Buddhism, archive).
- Resumes consolidated into My Drive/Job Hunt/Resumes/2026 + Archive (7 files).
- Travel loose files moved to My Drive/Travel (Sep 2026 Asia, NZE Europe, DJI footage to Pictures).
- Taxes (11 PDFs) consolidated into Desktop/Rohit Documents/Tax Documents.
- Exact duplicates removed (moved to ~/Dedup-Trash-2026-09-15/, 51 files, ~26MB) keeping canonical
  copies; verified none lost vs source of truth (Desktop/My Drive/Documents copies retained).
- Office Laptop archive deduped without disturbing structure: 285 exact-duplicate files replaced
  with hardlinks to one copy -> ~321MB reclaimed (detail preserved via links).
- Pictures/Backup: 12 identical photo-pair files removed (1.2MB).

## Open items for Rohit
- `~/Dedup-Trash-2026-09-15/` holds all removed dupes + dedup-report.txt — review then delete.
- Two distinct 2024-tax-return PDFs kept (Tax Documents folder 654KB scan vs old 293KB copy) — differ.
- September_Asia_2026.html exports are near-dups, both kept. bp wallet pass kept as pkpass.
- Homelab .mobileconfig/.crt/pi-hole teleporter zips moved to ~/projects/homelab-configs/.

## Memory/relay note
Collaborator-memory repo had a rebase conflict on code/scripts/topic_gc.py during `git pull`;
resolved by keeping the newer upstream version (455-line script) and pushed. Mac-side cleanup is
purely local; nothing on home-hp was touched.