#!/usr/bin/env python3
"""gnap.py — Git-Native Agent Protocol for Hermes sub-agents.

Implements GNAP (Git-Native Agent Protocol): each agent publishes capabilities
as a JSON file in a git repo. Agents discover each other by reading the repo.

Capabilities are defined by a JSON schema:
  {
    "agent": "hermes-mind-loop",
    "version": "1.0.0",
    "capabilities": [
      {"name": "health_check", "input": {}, "output": {"type": "object"}}
    ],
    "well_known": {"url": "http://localhost:8910"}
  }

Usage:
    from gnap import GNAPAgent, Capability

    agent = GNAPAgent("hermes-mind-loop", repo_path="/tmp/agent-registry")
    agent.register()
    results = agent.discover(["health", "monitor"])
"""

from __future__ import annotations
import json
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
GNAP_REPO = HERMES_HOME / "gnap-registry"
AGENTS_FILE = "agents.json"


@dataclass
class Capability:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    tool_provider: str = ""  # MCP server name if tool-based
    tool_name: str = ""      # MCP tool name


@dataclass
class AgentManifest:
    agent: str
    version: str = "1.0.0"
    capabilities: list[Capability] = field(default_factory=list)
    well_known: dict = field(default_factory=lambda: {"protocol": "gnap-v1"})
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    health_url: str = ""
    parent: str = ""

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "version": self.version,
            "last_seen": self.last_seen,
            "capabilities": [asdict(c) for c in self.capabilities],
            "well_known": self.well_known,
            "health_url": self.health_url,
            "parent": self.parent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentManifest":
        caps = [Capability(**c) if isinstance(c, dict) else c for c in data.get("capabilities", [])]
        data["capabilities"] = caps
        return cls(**data)


class GNAPAgent:
    def __init__(self, name: str, repo_path: Optional[Path] = None):
        self.name = name
        self.repo_path = repo_path or GNAP_REPO
        self.agents_file = self.repo_path / AGENTS_FILE
        self.manifest_path = self.repo_path / f"{name}.json"
        self.manifest = AgentManifest(agent=name)

    def add_capability(self, cap: Capability):
        self.manifest.capabilities.append(cap)

    def register(self):
        self.manifest.last_seen = datetime.now(timezone.utc).isoformat()
        self.repo_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest.to_dict(), indent=2))
        self._update_agents_index()
        return True

    def deregister(self):
        if self.manifest_path.exists():
            self.manifest_path.unlink()
        self._update_agents_index()

    def discover(self, keywords: Optional[list[str]] = None) -> list[dict]:
        agents = self._load_all()
        if not keywords:
            return agents
        kw_set = set(k.lower() for k in keywords)
        results = []
        for a in agents:
            for cap in a.get("capabilities", []):
                name = cap.get("name", "").lower()
                desc = cap.get("description", "").lower()
                if any(k in name or k in desc for k in kw_set):
                    results.append(a)
                    break
        return results


    def prune_stale(self, max_age_hours: int = 24):
        agents = self._load_all()
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
        stale = []
        for a in agents:
            try:
                ts = datetime.fromisoformat(a.get("last_seen", "")).timestamp()
                if ts < cutoff:
                    stale.append(a["agent"])
            except Exception:
                stale.append(a.get("agent", "unknown"))
        for name in stale:
            p = self.repo_path / f"{name}.json"
            if p.exists():
                p.unlink()
        self._update_agents_index()
        return stale

    def _load_all(self) -> list[dict]:
        if not self.agents_file.exists():
            return []
        try:
            data = json.loads(self.agents_file.read_text())
            return data.get("agents", [])
        except Exception:
            return []

    def _update_agents_index(self):
        agents = []
        for f in self.repo_path.glob("*.json"):
            if f.name == AGENTS_FILE:
                continue
            try:
                agents.append(json.loads(f.read_text()))
            except Exception:
                pass
        self.agents_file.write_text(json.dumps({"agents": agents, "updated": datetime.now(timezone.utc).isoformat()}, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GNAP agent protocol")
    parser.add_argument("--register", type=str, help="Register an agent")
    parser.add_argument("--deregister", type=str, help="Deregister an agent")
    parser.add_argument("--prune", action="store_true", help="Prune stale agents")
    parser.add_argument("--discover", nargs="*", help="Discover agents by keywords")
    parser.add_argument("--list", action="store_true", help="List all agents")
    args = parser.parse_args()

    agent = GNAPAgent("hermes-scheduler")

    if args.register:
        agent.manifest.agent = args.register
        agent.register()
        print(f"Registered {args.register}")
    elif args.deregister:
        agent.manifest.agent = args.deregister
        agent.deregister()
        print(f"Deregistered {args.deregister}")
    elif args.prune:
        stale = agent.prune_stale()
        print(f"Pruned {len(stale)} stale agents: {stale}")
    elif args.discover is not None:
        results = agent.discover(args.discover)
        for r in results:
            caps = ", ".join(c.get("name", "") for c in r.get("capabilities", []))
            print(f"  {r.get('agent', '?')}: {caps}")
    elif args.list:
        all_a = agent._load_all()
        for a in all_a:
            print(f"  {a.get('agent', '?')} v{a.get('version', '?')}")

if __name__ == "__main__":
    main()

__all__ = ["GNAPAgent", "Capability", "AgentManifest"]
