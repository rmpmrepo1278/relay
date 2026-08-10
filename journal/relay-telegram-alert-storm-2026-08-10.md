# Relay: Telegram alert storm diagnosis + fixes (2026-08-10)

## Symptom
Hundreds of Telegram messages all morning: repeated "❌ Service Auto-Heal / unknown: failed - Job for hermes-upgrade.service failed", "🧠 MenteDB is DOWN (port 6677)", and AUTO-FIX sessions failing on a missing `claude_code_delegate`.

## Root causes (3)
1. **hermes-upgrade.service crash**: `hermes_upgrade.py:130` calls `code-review-graph --version` but the systemd user unit PATH didn't include `~/.local/bin` (binary lives there). Same latent issue for `graphify` at line 131. Every failure (manual or auto-heal-triggered) spawned another n8n "Service Auto-Heal" alert → the storm.
2. **MenteDB container absent**: `mentedb` (image `mentedb:fixed`, port 127.0.0.1:6677/6678, compose project `compose` at `/home/rohit/services/docker/compose/apps.yml`) was gone from docker entirely (not stopped). Health check pings failed → "MenteDB is DOWN".
3. **claude_code_delegate.py missing**: expected at `/home/rohit/.hermes/hermes-agent/scripts/claude_code_delegate.py`, but `scripts/` is **untracked** on all branches (incl. `chaguli/main`); file had been deleted from disk. Auto-fix `git checkout <sha>` rollbacks can't restore an untracked file and kept churning the repo.

## Fixes applied (homelab)
1. Added drop-in `~/.config/systemd/user/hermes-upgrade.service.d/path.conf` with `Environment=PATH=/usr/bin:/home/rohit/.local/bin:/home/rohit/.npm-global/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/bin`. `systemctl --user start hermes-upgrade.service` → **exit 0 SUCCESS**.
2. `docker compose -f /home/rohit/services/docker/compose/apps.yml up -d mentedb` → **Up 20s (healthy)**, `curl :6677/v1/health` → `{"status":"ok",...}`.
3. Restored delegate as **untracked** file via `git show 5877ac1a5:scripts/claude_code_delegate.py` (compile OK, `--help` works, 31KB, executable). Deliberately NOT committed: `git reset --hard chaguli/main` (run by the upgrade) deletes tracked files missing from chaguli/main, so a tracked restore would vanish again; untracked files survive resets.

## Verification
- `systemctl --user --failed` → 0 units. No failing services remain.
- hermes-upgrade.timer still scheduled (next Mon 2026-08-17 00:24).
- hermes-agent repo on main @ 3cb2203d1; `scripts/` untracked (by design now).

## Notes / follow-ups
- **Durability gap**: the delegate is only durable against `reset --hard` because it's untracked. Proper fix is to track `scripts/` on `chaguli/main` (or move it to a tracked location) — flag to Rohit; also add `graphify --version` PATH coverage (line 131) already covered by same drop-in.
- Email-digest repeats (Costco order / Apple subscription) are content-noise from `email_intelligence`, dedup throttled them; not a failure.
- n8n "Service Auto-Heal" workflows (`homelab_troubleshooter.py` comment) are the alerting engine; no cooldown edits made — roots fixed so alerts stop.
