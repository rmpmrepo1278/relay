#!/usr/bin/env python3
"""
Unified Cost Guard — Single script replacing 3 separate cost guard cron jobs.

Checks:
  1. Claude Code model (settings.json) — must be free
  2. Hermes proxy providers (config.yaml) — must be free
  3. OpenRouter billing API — no new charges since baseline

All model classification via shared CostGuard library.

Usage:
  python3 unified_cost_guard.py check    # Full check (used by cron every 5 min)
  python3 unified_cost_guard.py status   # Show all model states + billing
  python3 unified_cost_guard.py init     # Reset billing baseline
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# --- Shared costguard library (self-healing: hermes-agent reinstalls can wipe lib/) ---
COSTGUARD_LIB = Path.home() / ".hermes" / "lib" / "costguard"
if not (COSTGUARD_LIB / "guard.py").exists():
    _alt = Path.home() / ".hermes" / "hermes-agent" / "costguard"
    if (_alt / "guard.py").exists():
        COSTGUARD_LIB.parent.mkdir(parents=True, exist_ok=True)
        try:
            if COSTGUARD_LIB.is_symlink() or COSTGUARD_LIB.exists():
                COSTGUARD_LIB.unlink()
        except OSError:
            pass
        COSTGUARD_LIB.symlink_to(_alt, target_is_directory=True)
sys.path.insert(0, str(COSTGUARD_LIB.parent))
from costguard.guard import CostGuard

guard = CostGuard()

# --- Paths ---
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CLAUDE_STATE = Path.home() / ".claude" / ".zero_cost_state.json"
CLAUDE_LOG = Path.home() / ".claude" / "logs" / "zero_cost_guard.log"
ORBIT_STATE = Path.home() / ".claude" / ".orbit_cost_state.json"
ORBIT_LOG = Path.home() / ".claude" / "logs" / "orbit_cost_monitor.log"
HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"
HERMES_STATE = Path.home() / ".hermes" / "shared" / "zero_cost_guard" / "state.json"
HERMES_LOG = Path.home() / ".hermes" / "logs" / "hermes_zero_cost_guard.log"
UNIFIED_LOG = Path.home() / ".hermes" / "logs" / "unified_cost_guard.log"

for p in [CLAUDE_LOG, ORBIT_LOG, HERMES_LOG, UNIFIED_LOG]:
    p.parent.mkdir(parents=True, exist_ok=True)


def log(msg, target="unified"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{target}] {msg}"
    with open(UNIFIED_LOG, "a") as f:
        f.write(line + "\n")
    print(line)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default or {}


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def get_openrouter_key():
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENROUTIC_API_KEY=") or line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("OPENROUTER_API_KEY", "")


# ── 1. Claude Code Model Check ──────────────────────────────────────────────

def check_claude_code():
    """Verify Claude Code is using a free model."""
    settings = load_json(CLAUDE_SETTINGS)
    if not settings:
        log("WARNING: Cannot read Claude Code settings.json", "claude")
        return True  # Don't fail on missing file

    # Check all three tier vars
    tiers = [
        ("haiku", settings.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")),
        ("sonnet", settings.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")),
        ("opus", settings.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "")),
    ]

    all_free = True
    for tier_name, model in tiers:
        if not model:
            continue
        if guard.is_blocklisted(model):
            log(f"BLOCKED: Claude Code {tier_name} model '{model}' is on blocklist!", "claude")
            all_free = False
        elif not guard.is_free(model):
            log(f"WARNING: Claude Code {tier_name} model '{model}' not in free list", "claude")
            all_free = False

    if all_free:
        log("OK: Claude Code models are all free", "claude")
    return all_free


# ── 2. Hermes Proxy Check ───────────────────────────────────────────────────

def check_hermes_proxy():
    """Verify Hermes proxy config uses free providers."""
    if not HERMES_CONFIG.exists():
        log("WARNING: Cannot read Hermes config.yaml", "hermes")
        return True

    try:
        import yaml
        config = yaml.safe_load(HERMES_CONFIG.read_text())
    except ImportError:
        # Fallback: basic text check
        text = HERMES_CONFIG.read_text()
        blocked = guard.get_blocked_models()
        for model in blocked:
            if model in text:
                log(f"BLOCKED: Hermes config references paid model '{model}'", "hermes")
                return False
        log("OK: Hermes config has no blocked models (text scan)", "hermes")
        return True

    # Check providers
    providers = config.get("providers", {})
    all_free = True
    for name, pconfig in providers.items():
        if isinstance(pconfig, dict) and pconfig.get("enabled", True):
            model = pconfig.get("model", "")
            if model and guard.is_blocklisted(model):
                log(f"BLOCKED: Hermes provider '{name}' uses paid model '{model}'", "hermes")
                all_free = False

    # Check fallback providers
    fallbacks = config.get("fallback_providers", [])
    for fb in fallbacks:
        if isinstance(fb, str) and guard.is_blocklisted(fb):
            log(f"BLOCKED: Hermes fallback references paid model '{fb}'", "hermes")
            all_free = False

    if all_free:
        log("OK: Hermes proxy providers are all free", "hermes")
    return all_free


# ── 3. OpenRouter Billing Check ─────────────────────────────────────────────

def check_billing():
    """Check OpenRouter for any new charges."""
    api_key = get_openrouter_key()
    if not api_key:
        log("SKIP: No OpenRouter API key found", "billing")
        return True

    state = load_json(ORBIT_STATE, {"baseline_usd": 0.0, "last_check": None})

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            total = float(data.get("data", {}).get("usage", 0))

        baseline = float(state.get("baseline_usd", 0))
        delta = total - baseline

        if delta > 0.001:  # Any non-zero spend
            log(f"CHARGE DETECTED: ${total:.4f} total, ${delta:.4f} since baseline", "billing")
            return False
        else:
            log(f"OK: OpenRouter spend ${total:.4f} (baseline ${baseline:.4f})", "billing")
            state["last_check"] = datetime.now().isoformat()
            state["last_total_usd"] = total
            save_json(ORBIT_STATE, state)
            return True

    except Exception as e:
        log(f"WARNING: OpenRouter API check failed: {e}", "billing")
        return True  # Don't fail on API errors


# ── Main ─────────────────────────────────────────────────────────────────────

def check():
    """Run all three checks."""
    log("=== Unified Cost Guard check starting ===")
    r1 = check_claude_code()
    r2 = check_hermes_proxy()
    r3 = check_billing()
    ok = r1 and r2 and r3
    log(f"=== Result: {'ALL OK' if ok else 'ISSUES DETECTED'} ===")
    return ok


def status():
    """Show current state of all three guards."""
    print("=== Claude Code ===")
    settings = load_json(CLAUDE_SETTINGS, {})
    for k in ["ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL"]:
        v = settings.get(k, "(not set)")
        status = "FREE" if (v and guard.is_free(v)) else ("BLOCKED" if guard.is_blocklisted(v) else "UNKNOWN")
        print(f"  {k}: {v} [{status}]")

    print("\n=== Hermes Proxy ===")
    if HERMES_CONFIG.exists():
        text = HERMES_CONFIG.read_text()
        blocked = guard.get_blocked_models()
        found_blocked = [m for m in blocked if m in text]
        if found_blocked:
            print(f"  WARNING: Found blocked models: {found_blocked}")
        else:
            print("  OK: No blocked models in config")
    else:
        print("  (config not found)")

    print("\n=== OpenRouter Billing ===")
    state = load_json(ORBIT_STATE, {})
    print(f"  Baseline: ${state.get('baseline_usd', 'not set')}")
    print(f"  Last total: ${state.get('last_total_usd', 'unknown')}")
    print(f"  Last check: {state.get('last_check', 'never')}")

    print("\n=== Free Models (top tier) ===")
    for m in guard.get_free_models()[:10]:
        print(f"  {m}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        ok = check()
        sys.exit(0 if ok else 1)
    elif cmd == "status":
        status()
    elif cmd == "init":
        state = {"baseline_usd": 0.0, "last_check": datetime.now().isoformat()}
        save_json(ORBIT_STATE, state)
        print("Billing baseline initialized to $0")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: unified_cost_guard.py [check|status|init]")
