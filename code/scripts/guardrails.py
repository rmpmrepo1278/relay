#!/usr/bin/env python3
"""guardrails.py — Shared fail-closed guardrail configuration for autonomous agents.

Reads a single optional YAML file (default ~/.hermes/agents/guardrails.yaml)
and merges overrides into each agent's built-in restrictive defaults.

Merging rules (all fail-closed):
  * A missing file, a missing agent section, or a missing key means: keep the
    built-in default. Nothing ever gets *looser* by accident.
  * ``*_extra`` list keys are ADDITIVE — the built-in allowlist is always
    retained and the extra entries are added to it.
  * ``*_min`` / cooldown dicts are MERGED per action — you can retune one
    cooldown without restating (or accidentally dropping) the others.
  * Scalar overrides (max_plans, allow_full_upgrade, brief_window, ...)
    REPLACE the default when present and are validated for sane ranges.

Example guardrails.yaml:

    homelab:
      extra_actions: ["purge_docker_volumes"]      # additive to allowlist
      extra_heal_targets: ["proxmox"]
      cooldown_min: {"heal": 10, "notify": 5}       # merge per action
      allow_full_upgrade: true                      # scalar replace
      clean_disk_allow_volumes: false
      disk_warn_pct: 80
      notify_max_len: 600
      max_plans: 6

    jenny:
      extra_delegate_targets: ["proxmox"]
      extra_plan_actions: []
      cooldown_min: {"send_telegram": 10, "reply_chat": 2}
      max_plans: 8
      brief_window: ["04:30", "05:30"]
      max_reply: 800

    jenny_llm:
      extra_tools: ["send_dashboard"]
      extra_intents: []
      max_delegations: 5
      max_steps: 8
      max_reply: 800
      max_args: 400
"""
import os

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_DEFAULT_PATH = os.path.expanduser("~/.hermes/agents/guardrails.yaml")
_CACHE = {}


def load_guardrails(agent: str, path=None) -> dict:
    """Return the merged override dict for one agent. {} when file absent.

    The returned dict holds only the *overrides* present in YAML for that
    section, already validated. Callers merge them into their defaults.
    """
    if path is None:
        path = _DEFAULT_PATH
    if path in _CACHE:
        data = _CACHE[path]
    elif yaml is None or not os.path.exists(path):
        data = {}
    else:
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
        _CACHE[path] = data
    section = data.get(agent) or {}
    if not isinstance(section, dict):
        return {}
    return _validate(agent, section)


def _validate(agent: str, section: dict) -> dict:
    out = {}
    for key in ("extra_actions", "extra_heal_targets", "extra_delegate_targets",
                "extra_plan_actions", "extra_tools", "extra_intents"):
        v = section.get(key, [])
        if isinstance(v, list):
            out[key] = [str(x) for x in v if isinstance(x, str)]

    for key in ("cooldown_min",):
        v = section.get(key, {})
        if isinstance(v, dict):
            out[key] = {k: _as_positive_num(k, x) for k, x in v.items()
                        if isinstance(x, (int, float)) and x > 0}

    for key in ("max_plans", "max_delegations", "max_steps", "max_reply",
                "max_args", "notify_max_len", "disk_warn_pct"):
        if key in section:
            v = section[key]
            if isinstance(v, (int, float)) and v > 0:
                out[key] = int(v)

    if "allow_full_upgrade" in section:
        v = section["allow_full_upgrade"]
        if isinstance(v, bool):
            out["allow_full_upgrade"] = v
    if "clean_disk_allow_volumes" in section:
        v = section["clean_disk_allow_volumes"]
        if isinstance(v, bool):
            out["clean_disk_allow_volumes"] = v

    v = section.get("brief_window")
    if isinstance(v, bool):
        out["brief_window"] = v
    elif isinstance(v, list) and len(v) == 2:
        try:
            out["brief_window"] = [str(t) for t in v]
        except Exception:
            pass

    v = section.get("shell_danger_extra")
    if isinstance(v, list):
        out["shell_danger_extra"] = [str(x) for x in v if isinstance(x, str)]
    return out


def _as_positive_num(k, v):
    return max(0.0, float(v))


def clear_cache():
    _CACHE.clear()