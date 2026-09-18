#!/usr/bin/env python3
"""
homelab_agent_autonomous.py — Homelab Infrastructure autonomous agent.

Owns: Docker, systemd, backups, disk, updates, self-heal.

Mind loop:
  OBSERVE   ─ deterministic sensing (docker/systemd/disk/memory/backups/updates/agentbus)
  CONNECT   ─ deterministic insight extraction from signals
  ANTICIPATE─ deterministic forecasting (context only; LLM may override)
  PLAN      ─ LLM-decided action selection against a strict tool allowlist,
              validated against observed signals + risk cooldowns.
              Offline/unavailable/unsafe → deterministic fallback plan.
  ACT       ─ execute only allowlisted, re-validated actions (bounded dispatch,
              never arbitrary shell from the LLM).
  REFLECT/EVOLVE — as before.

Guardrails (enforced regardless of what the LLM asks):
  - Action allowlist: heal, verify_backups, clean_disk, apply_updates, notify, nothing.
  - No arbitrary commands: every executed action resolves to a fixed
    internal method; names/targets come from OBSERVED signals, never LLM text.
  - Per-action cooldowns prevent restart/prune/upgrade churn loops.
  - apply_updates "all" requires HOMELAB_ALLOW_FULL_UPGRADE=1 (security-only default).
  - clean_disk never uses --volumes (data-destructive).
  - notify is rate-limited + length-capped.
"""

from __future__ import annotations

from autonomous_agent import AutonomousAgent, _log
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, os, re, subprocess, time, urllib.request

HOP = os.environ.get("HOP_URL", "http://127.0.0.1:8083/v1/chat/completions")
HOP_MODEL = os.environ.get("HOP_MODEL", "haiku-4.5")

# ── Guardrail constants ──────────────────────────────────────────────────────
# Fail-closed: these built-ins are the defaults. An optional
# ~/.hermes/agents/guardrails.yaml [homelab] section can *add* to the
# allowlists (extra_*), retune per-action cooldowns (cooldown_min), or replace
# scalar knobs (see guardrails.py). Absent file/key ⇒ these values stand.
ALLOWED_ACTIONS = {"heal", "verify_backups", "clean_disk", "apply_updates", "notify", "nothing"}
HEAL_TARGETS = {"docker", "systemd", "agentbus"}
HIGH_RISK = {"apply_updates", "clean_disk"}
# per-action cooldown minutes
RISK_COOLDOWN_MIN = {
    "heal": 30,            # don't restart-loop a flapping container
    "apply_updates": 360,  # at most ~4/day
    "clean_disk": 120,
    "notify": 15,          # rate-limit Telegram spam (floor; transition policy on top)
    "verify_backups": 360, # kopia verify is heavy — max ~4/day, not every cycle
}
# Alerts are transition-only: same (domain,status) is never re-notified within
# this window even if the LLM asks. Keeps steady-state noise out of the topic.
NOTIFY_MIN_INTERVAL = 6 * 3600  # 6h floor for repeats on the same signature
DISK_WARN_PCT = 85
NOTIFY_MAX_LEN = 400
FULL_UPGRADE = os.environ.get("HOMELAB_ALLOW_FULL_UPGRADE", "").lower() in ("1", "true", "yes")
CLEAN_DISK_ALLOW_VOLUMES = False  # --volumes is data-destructive; stays off unless configured

try:
    from guardrails import load_guardrails
    _G = load_guardrails("homelab")
    if _G.get("extra_actions"):
        ALLOWED_ACTIONS |= set(_G["extra_actions"])
    if _G.get("extra_heal_targets"):
        HEAL_TARGETS |= set(_G["extra_heal_targets"])
    if _G.get("cooldown_min"):
        RISK_COOLDOWN_MIN.update({k: float(v) for k, v in _G["cooldown_min"].items()})
    if _G.get("disk_warn_pct"):
        DISK_WARN_PCT = _G["disk_warn_pct"]
    if _G.get("notify_max_len"):
        NOTIFY_MAX_LEN = _G["notify_max_len"]
    if _G.get("allow_full_upgrade"):
        FULL_UPGRADE = True  # env var OR config flag
    if _G.get("clean_disk_allow_volumes"):
        CLEAN_DISK_ALLOW_VOLUMES = True
    if _G:
        _log("homelab", "guardrails: active overrides %s" % sorted((k for k, _ in _G.items()), key=str))
except ImportError:
    _G = {}


class HomelabAgent(AutonomousAgent):
    """Homelab Infrastructure autonomous agent."""

    def __init__(self):
        super().__init__(
            name="homelab",
            domain="infrastructure",
            topic_id=10026,
            cycle_interval_minutes=15,  # More frequent for infra
        )
        if not (HOP.startswith("http") and HOP_MODEL):
            _log(self.name, "LLM decision layer disabled (no HOP gateway) — deterministic only", "WARN")

    # ─── OBSERVE ─────────────────────────────────────────────────────────────

    def observe(self) -> dict:
        """Gather infrastructure health signals."""
        signals = {}

        # Docker
        signals["docker"] = self._check_docker()

        # Systemd
        signals["systemd"] = self._check_systemd()

        # Disk
        signals["disk"] = self._check_disk()

        # Memory
        signals["memory"] = self._check_memory()

        # Backups
        signals["backups"] = self._check_backups()

        # Updates
        signals["updates"] = self._check_updates()

        # Agentbus
        signals["agentbus"] = self._check_agentbus()

        signals["timestamp"] = datetime.now(timezone.utc).isoformat()
        return signals

    def _check_docker(self) -> dict:
        try:
            r = subprocess.run(
                "docker ps --format '{{.Names}}|{{.Status}}'",
                shell=True, capture_output=True, text=True, timeout=10
            )
            containers = []
            unhealthy = []
            for line in r.stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    name, status = parts[0], parts[1]
                    containers.append({"name": name, "status": status})
                    if "unhealthy" in status.lower() or "dead" in status.lower() or "exited" in status.lower():
                        unhealthy.append(name)
            return {"status": "degraded" if unhealthy else "healthy", "total": len(containers), "unhealthy": unhealthy, "containers": containers}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_systemd(self) -> dict:
        try:
            services = ["agentbus", "agentbus-monitor", "hermes-mind-loop", "hermes-scheduler", "n8n-bridge", "tdai-gateway"]
            r = subprocess.run(f"systemctl --user --no-legend --plain list-units --type=service --state=failed --no-pager", shell=True, capture_output=True, text=True, timeout=10)
            failed = [line.split()[0] for line in r.stdout.splitlines() if line.strip()]
            failed = [s for s in failed if s in services]
            return {"status": "degraded" if failed else "healthy", "failed": failed}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_disk(self) -> dict:
        try:
            r = subprocess.run("df -h / /home /mnt/usb /var/lib/docker", shell=True, capture_output=True, text=True, timeout=10)
            issues = []
            for line in r.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    pct = int(parts[4].rstrip("%"))
                    if pct > DISK_WARN_PCT:
                        issues.append({"mount": parts[5], "usage_pct": pct, "avail": parts[3]})
            return {"status": "warning" if issues else "healthy", "issues": issues}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_memory(self) -> dict:
        try:
            r = subprocess.run("free -h", shell=True, capture_output=True, text=True, timeout=5)
            lines = r.stdout.splitlines()
            mem = lines[1].split()
            swap = lines[2].split()
            return {"status": "healthy", "total": mem[1], "used": mem[2], "available": mem[6], "swap_used": swap[2] if len(swap) > 2 else "0"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_backups(self) -> dict:
        try:
            # The Kopia repository lives under root's config (backup jobs run via
            # sudo -n); running plain `kopia` bellows "not connected" and we were
            # alerting on that as "not configured" — a false alarm.
            r = subprocess.run("sudo -n kopia repository status 2>&1", shell=True, capture_output=True, text=True, timeout=15)
            if "not connected" in (r.stdout + r.stderr).lower() or "not initialized" in (r.stdout + r.stderr).lower():
                return {"status": "error", "error": "Kopia repository not connected"}
            if r.returncode != 0 and "sudo" not in r.stderr:
                return {"status": "error", "error": (r.stderr or r.stdout)[:200]}
            r2 = subprocess.run("sudo -n kopia snapshot list --json 2>/dev/null", shell=True, capture_output=True, text=True, timeout=15)
            snaps = self._parse_json_stream(r2.stdout)
            if not snaps:
                return {"status": "error", "error": "no snapshots"}
            latest = max(
                snaps,
                key=lambda s: datetime.fromisoformat(
                    (s.get("startTime", "") or "").replace("Z", "+00:00"))
                if s.get("startTime") else datetime.min.replace(tzinfo=timezone.utc),
            )
            age_h = 0
            ts = latest.get("startTime", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                except Exception:
                    pass
            status = "healthy"
            if age_h > 48: status = "stale"
            elif age_h > 24: status = "aging"
            return {"status": status, "latest": latest.get("id", "")[:12], "age_h": round(age_h, 1), "total": len(snaps)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _parse_json_stream(text: str) -> list:
        """Parse kopia snapshot list --json: modern kopia prints ONE pretty-
        printed JSON array; some builds emit concatenated objects. Handle both."""
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass
        dec = json.JSONDecoder()
        data = text.lstrip()
        out = []
        while data:
            try:
                obj, idx = dec.raw_decode(data)
            except json.JSONDecodeError:
                break
            if isinstance(obj, list):
                out.extend(obj)
            else:
                out.append(obj)
            data = data[idx:].lstrip()
        return out

    def _check_updates(self) -> dict:
        try:
            r = subprocess.run("apt list --upgradable 2>/dev/null | grep -v 'Listing...'", shell=True, capture_output=True, text=True, timeout=30)
            updates = [l for l in r.stdout.splitlines() if l.strip()]
            security = [u for u in updates if "security" in u.lower()]
            return {"status": "updates_available" if updates else "current", "total": len(updates), "security": len(security), "packages": updates[:10]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_agentbus(self) -> dict:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9107/status", timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return {"status": "healthy" if data.get("ok") else "degraded", "claims": len(data.get("claims", {})), "presence": len(data.get("presence", {})), "objectives": len(data.get("objectives", {}))}
        except Exception as e:
            return {"status": "down", "error": str(e)}

    # ─── CONNECT ─────────────────────────────────────────────────────────────

    def connect(self, signals: dict) -> list:
        insights = []

        for name, check in signals.items():
            if name == "timestamp": continue
            status = check.get("status", "?")

            if status in ("down", "error", "stale", "aging", "warning", "degraded", "updates_available"):
                severity = "high" if status in ("down", "error") else "medium"
                detail = ""
                if name == "docker" and check.get("unhealthy"):
                    detail = f" — unhealthy: {', '.join(check['unhealthy'])}"
                elif name == "systemd" and check.get("failed"):
                    detail = f" — failed: {', '.join(check['failed'])}"
                elif name == "disk" and check.get("issues"):
                    parts = [f'{i["mount"]} {i["usage_pct"]}%' for i in check["issues"]]
                    detail = " — " + ", ".join(parts)
                elif name == "backups":
                    detail = f" — age: {check.get('age_h', '?')}h"
                elif name == "updates":
                    detail = f" — {check.get('total', 0)} updates ({check.get('security', 0)} security)"

                insights.append({
                    "type": "infra_alert",
                    "content": f"Infrastructure {name}: {status.replace('_', ' ')}{detail}",
                    "action_suggested": "heal" if status in ("down", "error", "stale", "degraded", "warning") else "maintain",
                    "severity": "high" if status in ("down", "error") else "medium",
                    "domain": name,
                })

        return insights

    def anticipate(self, signals: dict, insights: list) -> list:
        """Forecast maintenance needs. Context only — the LLM planner decides."""
        anticipations = []

        # If backups aging, anticipate verify
        backups = signals.get("backups", {})
        if backups.get("status") in ("aging", "stale"):
            anticipations.append({"type": "preventive", "content": "Backups aging — will verify Kopia snapshots", "action": "verify_backups"})

        # If disk warning, anticipate cleanup
        disk = signals.get("disk", {})
        if any(i.get("usage_pct", 0) > 90 for i in disk.get("issues", [])):
            anticipations.append({"type": "preventive", "content": "Disk critical — will clean caches", "action": "clean_disk"})

        # If updates available and it's Sunday, anticipate apply
        now = datetime.now()
        if now.weekday() == 6 and signals.get("updates", {}).get("status") == "updates_available":
            anticipations.append({"type": "scheduled", "content": "Sunday maintenance window — will apply updates", "action": "apply_updates", "scope": "all"})

        return anticipations

    # ─── PLAN (LLM-determined within guardrails, deterministic fallback) ─────

    def plan(self, signals: dict, insights: List[dict], anticipations: List[dict]) -> List[dict]:
        llm_plans = self._llm_decide(signals, insights, anticipations)
        if llm_plans:
            validated = []
            for p in llm_plans:
                ok, why = self._validate_action(p, signals)
                if ok:
                    p["confidence"] = p.get("confidence", 0.75)
                    p["priority"] = p.get("priority", 5)
                    p["_llm"] = True
                    validated.append(p)
                else:
                    _log(self.name, f"LLM plan REJECTED ({p.get('action')}): {why}", "WARN")
            if validated:
                _log(self.name, "LLM decided: " + ", ".join(str(v.get("action")) for v in validated))
                return validated
            _log(self.name, "LLM produced no valid action — deterministic fallback", "WARN")
        else:
            _log(self.name, "LLM planner unavailable — deterministic fallback", "WARN")
        return self._fallback_plan(signals, insights, anticipations)

    def _llm_decide(self, signals: dict, insights: List[dict], anticipations: List[dict]) -> List[dict]:
        """Ask the local LLM what to do this cycle. Returns raw plans or []."""
        if not (HOP.startswith("http") and HOP_MODEL):
            return []
        try:
            digest = self._signals_digest(signals)
            ins_txt = "\n".join(f"- {i.get('content')}" for i in insights[:8]) or "- (none)"
            ant_txt = "\n".join(f"- {a.get('content')}" for a in anticipations[:5]) or "- (none)"
            full_scope_note = "Full upgrade is enabled." if FULL_UPGRADE else "Full upgrade is DISABLED (security-only allowed)."
            prompt = (
                "You are the homelab infrastructure agent. Choose the minimal, safe set of actions for this cycle.\n\n"
                f"Observed signals:\n{digest}\n\n"
                f"Insights:\n{ins_txt}\n\n"
                f"Forecasts:\n{ant_txt}\n\n"
                "Available actions (ONLY these):\n"
                '  {"action": "heal", "target": "docker|systemd|agentbus"}  — restart observed-unhealthy items only\n'
                '  {"action": "verify_backups"}  — kopia repository verify\n'
                '  {"action": "clean_disk"}  — prune + apt clean + journal vacuum (only if disk > 85%)\n'
                '  {"action": "apply_updates", "scope": "security|<all>"}  — apt upgrade (gated)\n'
                '  {"action": "notify", "text": "..."}  — alert users via Telegram\n'
                '  {"action": "nothing"}  — all healthy\n'
                f"NOTE: {full_scope_note}\n"
                "Reply with ONLY valid JSON, a single array. No markdown fences, no prose.\n"
                'Example: [{"action": "heal", "target": "docker", "reason": "immich unhealthy"}]\n'
                'If nothing needs doing: [{"action": "nothing", "reason": "all healthy"}]'
            )
            text = self._hop_ask(prompt, max_tokens=400)
            if not text:
                return []
            return self._parse_plans(text)
        except Exception as e:
            _log(self.name, f"LLM decide error: {e}", "WARN")
            return []

    def _signals_digest(self, signals: dict) -> str:
        lines = []
        docker = signals.get("docker", {})
        lines.append(f"docker={docker.get('status')} total={docker.get('total')} unhealthy={docker.get('unhealthy') or []}")
        sd = signals.get("systemd", {})
        lines.append(f"systemd={sd.get('status')} failed={sd.get('failed') or []}")
        disk = signals.get("disk", {})
        lines.append(f"disk={disk.get('status')} issues={[{'m': i.get('mount'), 'pct': i.get('usage_pct')} for i in disk.get('issues', [])]}")
        mem = signals.get("memory", {})
        lines.append(f"memory={mem.get('status')} used={mem.get('used')}/{mem.get('total')} avail={mem.get('available')}")
        bk = signals.get("backups", {})
        lines.append(f"backups={bk.get('status')} age_h={bk.get('age_h')} latest={bk.get('latest')} total={bk.get('total')}")
        up = signals.get("updates", {})
        lines.append(f"updates={up.get('status')} count={up.get('total')} security={up.get('security')}")
        ab = signals.get("agentbus", {})
        lines.append(f"agentbus={ab.get('status')}")
        return "\n".join(lines)

    def _hop_ask(self, prompt: str, max_tokens: int = 500) -> str | None:
        payload = {
            "model": HOP_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            req = urllib.request.Request(
                HOP, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            return data["choices"][0]["message"].get("content") or None
        except Exception as e:
            _log(self.name, f"hop_ask error: {e}", "WARN")
            return None

    def _parse_plans(self, text: str) -> List[dict]:
        """Extract a JSON array of plans from the LLM reply. Robust to fences/extra text."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
        # fallback: extract first [...] block
        try:
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
        return []

    def _validate_action(self, plan: dict, signals: dict) -> tuple:
        """Unsafe/unobservable/cooldown-violating actions are rejected."""
        action = str(plan.get("action", ""))
        if action not in ALLOWED_ACTIONS:
            return False, f"action '{action}' not in allowlist"

        if action == "heal":
            target = str(plan.get("target", ""))
            if target not in HEAL_TARGETS:
                return False, f"heal target '{target}' invalid"
            sig = signals.get(target, {})
            if target == "docker" and not sig.get("unhealthy"):
                return False, "heal docker: no observed unhealthy containers"
            if target == "systemd" and not sig.get("failed"):
                return False, "heal systemd: no observed failed services"
            if target == "agentbus" and sig.get("status") in ("healthy", "ok"):
                return False, "heal agentbus: bus already healthy"

        elif action == "clean_disk":
            if not any(i.get("usage_pct", 0) > DISK_WARN_PCT for i in signals.get("disk", {}).get("issues", [])):
                return False, "clean_disk: disk not above threshold"

        elif action == "apply_updates":
            if signals.get("updates", {}).get("status") != "updates_available":
                return False, "apply_updates: no updates available"
            scope = str(plan.get("scope", "security"))
            if scope not in ("security", "all"):
                scope = "security"
            plan["scope"] = scope
            if scope == "all" and not FULL_UPGRADE:
                return False, "apply_updates(all) DISABLED unless HOMELAB_ALLOW_FULL_UPGRADE=1"

        cooldowns = self.state.setdefault("cooldowns", {})
        cd = cooldowns.get(action, 0)
        if time.time() < cd:
            return False, f"{action}: in cooldown"
        return True, ""

    def _apply_cooldown(self, action: str):
        self.state.setdefault("cooldowns", {})[action] = time.time() + RISK_COOLDOWN_MIN.get(action, 60) * 60

    def _notify_sig(self, plan: dict, signals: dict) -> str:
        """Stable alert signature = (domain, status) of the abnormal signal, so
        steady-state noise never re-fires and a transition always alerts once."""
        abnormal = {
            name: ch.get("status")
            for name, ch in signals.items()
            if name != "timestamp" and ch.get("status") in (
                "down", "error", "stale", "aging", "warning", "degraded",
                "updates_available", "not_configured")
        }
        if not abnormal:
            return "general|"
        content = str(plan.get("content") or plan.get("text") or "").lower()
        domain = str(plan.get("domain") or plan.get("source") or "").lower()
        if domain not in abnormal:
            # Match the abnormal signal the notify is actually about.
            for name in abnormal:
                if name in content:
                    domain = name
                    break
        if domain not in abnormal:
            # Unanchored alert — only allow if exactly one thing is wrong.
            if len(abnormal) == 1:
                domain = next(iter(abnormal))
            else:
                return "general|"
        return f"{domain}|{abnormal[domain]}"

    def _notify_policy(self, plan: dict, signals: dict) -> tuple:
        """Transition + silence-window alerting. Rejects empty prose (the old
        'infra update' fallback) and repeats of the same (domain,status)
        within NOTIFY_MIN_INTERVAL."""
        sig = self._notify_sig(plan, signals)
        if sig == "general|":
            return False, "no abnormal signal to report (or multiple unanchored)"
        now = time.time()
        notified = self.state.setdefault("notified", {})
        last = notified.get(sig)
        if last and (now - last) < NOTIFY_MIN_INTERVAL:
            return False, f"{sig} already alerted (6h window)"
        notified[sig] = now
        self.state.setdefault("last_signal_status", {})
        return True, ""

    def _fallback_plan(self, signals: dict, insights: List[dict], anticipations: List[dict]) -> List[dict]:
        """Deterministic fallback when the LLM planner is unavailable/rejected."""
        plans = []

        for insight in insights:
            severity = insight.get("severity", "medium")
            priority = {"critical": 10, "high": 8, "medium": 5, "low": 3}.get(severity, 5)

            if insight.get("action_suggested") == "heal":
                plans.append({
                    "action": "heal",
                    "domain": insight.get("domain"),
                    "target": insight.get("domain"),
                    "priority": priority,
                    "confidence": 0.8,
                    "source_insight": insight.get("content", "")[:80],
                })
            elif insight.get("action_suggested") == "maintain":
                plans.append({
                    "action": "notify",
                    "content": insight.get("content"),
                    "priority": priority,
                    "confidence": 0.6,
                })

        for ant in anticipations:
            plans.append({
                "action": ant.get("action"),
                "scope": ant.get("scope", "security"),
                "priority": 7,
                "confidence": 0.7,
            })

        return plans

    # ─── ACT ─────────────────────────────────────────────────────────────────

    def act(self, plans: list, signals: dict) -> list:
        results = []

        for plan in plans:
            action = plan.get("action")
            # Re-validate at execution time (defense in depth, even for fallback plans).
            ok, why = self._validate_action(plan, signals)
            if not ok:
                results.append({"action": action, "status": "skipped", "reason": why})
                continue
            try:
                if action == "heal":
                    target = plan.get("target") or plan.get("domain")
                    result = self._heal_domain(target, signals)
                    self._apply_cooldown(action)
                    results.append({"action": "heal", "target": target, "status": "ok", "detail": result})

                elif action == "verify_backups":
                    result = self._verify_backups()
                    self._apply_cooldown(action)
                    results.append({"action": "verify_backups", "status": "ok", "detail": result})

                elif action == "clean_disk":
                    result = self._clean_disk()
                    self._apply_cooldown(action)
                    results.append({"action": "clean_disk", "status": "ok", "detail": result})

                elif action == "apply_updates":
                    scope = plan.get("scope", "security")
                    self._apply_cooldown(action)
                    results.append({"action": "apply_updates", "scope": scope, "status": "ok", "detail": self._apply_updates(scope)})

                elif action == "notify":
                    content = str(plan.get("content") or plan.get("text") or "").strip()
                    if not content:
                        results.append({"action": "notify", "status": "skipped", "reason": "empty content"})
                        continue
                    ok, why = self._notify_policy(plan, signals)
                    if not ok:
                        _log(self.name, f"notify rejected: {why}", "WARN")
                        results.append({"action": "notify", "status": "skipped", "reason": why})
                        continue
                    self.send_to_own_topic(f"⚠️ {content[:NOTIFY_MAX_LEN]}")
                    self._apply_cooldown(action)
                    results.append({"action": "notify", "status": "ok", "text": content[:80]})

                elif action == "nothing":
                    results.append({"action": "nothing", "status": "ok"})

                else:
                    results.append({"action": action, "status": "unknown"})

            except Exception as e:
                results.append({"action": action, "status": "error", "error": str(e)})

        return results

    # ─── Bounded tools (dispatch targets — never arbitrary LLM shell) ───────

    def _heal_domain(self, domain: str, signals: dict) -> dict:
        if domain == "docker":
            check = signals.get("docker", {})
            healed = []
            for container in check.get("unhealthy", []):
                # observed-only: no LLM-supplied container names
                result = subprocess.run(f"docker restart {container}", shell=True, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    healed.append(container)
            return {"healed": healed}

        elif domain == "systemd":
            check = signals.get("systemd", {})
            healed = []
            for service in check.get("failed", []):
                result = subprocess.run(f"systemctl --user restart {service}", shell=True, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    healed.append(service)
            return {"healed": healed}

        elif domain == "agentbus":
            result = subprocess.run("systemctl --user restart agentbus", shell=True, capture_output=True, text=True, timeout=30)
            return {"restarted": result.returncode == 0}

        return {"error": f"Unknown domain: {domain}"}

    def _verify_backups(self) -> dict:
        # Share the same 6h file lock as homelab_agent.verify_backups() so the
        # LLM-picked verify and the 5-min mind_loop dispatch cannot stack.
        lock_file = STATE_DIR / "homelab_verify_lock.json"
        try:
            last = float(json.loads(lock_file.read_text()).get("last", 0.0))
        except Exception:
            last = 0.0
        if time.time() - last < 6 * 3600:
            return {"status": "skipped_throttled", "locked": True}
        lock_file.write_text(json.dumps({"last": time.time()}))
        result = subprocess.run("sudo -n kopia repository verify 2>/dev/null || echo 'verify failed'", shell=True, capture_output=True, text=True, timeout=600)
        return {"ok": "ERROR" not in result.stdout}

    def _clean_disk(self) -> dict:
        results = []
        cmds = ["docker system prune -f 2>/dev/null", "apt-get clean", "journalctl --vacuum-time=7d"]
        if CLEAN_DISK_ALLOW_VOLUMES:
            cmds.append("docker system prune --volumes -f 2>/dev/null")
        for cmd in cmds:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            results.append({"cmd": cmd, "ok": r.returncode == 0})
        return {"ok": all(r["ok"] for r in results), "results": results}

    def _apply_updates(self, scope: str = "security") -> dict:
        if scope == "all" and FULL_UPGRADE:
            cmd = "apt-get update && apt-get upgrade -y"
        else:
            cmd = "apt-get update && apt-get upgrade -y -t $(lsb_release -cs)-security"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        return {"ok": r.returncode == 0, "output": r.stdout[-500:]}

    def reflect(self, signals: dict, insights: list, plans: list, results: list) -> dict:
        reflection = super().reflect(signals, insights, plans, results)

        # Track health trends
        health = signals.get("docker", {}).get("status")
        if health:
            hist = self.state.get("health_history", [])
            hist.append({"ts": datetime.now(timezone.utc).isoformat(), "docker_status": health})
            self.state["health_history"] = hist[-100:]

        # Remember last-seen status per domain → notify becomes transition-only.
        lss = self.state.setdefault("last_signal_status", {})
        for name, check in signals.items():
            if name == "timestamp":
                continue
            lss[name] = check.get("status", "?")

        # Record planner provenance so we can audit deterministic vs LLM decisions.
        reflection["planner"] = {
            "cycle": self.cycle_count,
            "planned_by_llm": any(p.get("_llm", False) for p in plans),
            "actions": [r.get("action") for r in results],
            "skipped": [r.get("reason") for r in results if r.get("status") == "skipped"],
        }

        return reflection


if __name__ == "__main__":
    import sys
    agent = HomelabAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(agent.run_cycle(), indent=2))