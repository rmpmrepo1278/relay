#!/usr/bin/env python3
"""
housekeep_agent_autonomous.py — Home maintenance autonomous agent.
"""

from __future__ import annotations
from autonomous_agent import AutonomousAgent
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, os


class HousekeepAgent(AutonomousAgent):
    """Home maintenance: maintenance tasks, warranties, chores."""
    
    def __init__(self):
        super().__init__(
            name="housekeep",
            domain="home",
            topic_id=10122,  # personal topic
            cycle_interval_minutes=60,
        )
        self.store_path = os.path.expanduser("~/.hermes/agents/housekeep/store.json")
    
    def _load_store(self) -> dict:
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"items": [], "meta": {}}
    
    def _next_due(self, item: dict):
        if item.get("kind") == "warranty" or not item.get("last_done"):
            return None
        try:
            last = datetime.fromisoformat(item["last_done"]).date()
            freq = item.get("frequency_months", 0)
            return last + timedelta(days=freq * 30)
        except Exception:
            return None
    
    def _is_overdue(self, item: dict) -> bool:
        nd = self._next_due(item)
        return nd and nd <= datetime.now().date()
    
    def _is_due_soon(self, item: dict, days: int = 7) -> bool:
        nd = self._next_due(item)
        return nd and nd <= datetime.now().date() + timedelta(days=days)
    
    def observe(self) -> dict:
        data = self._load_store()
        overdue = [i for i in data.get("items", []) if self._is_overdue(i)]
        due_soon = [i for i in data.get("items", []) if not self._is_overdue(i) and self._is_due_soon(i)]
        warranty_exp = []
        for item in data.get("items", []):
            if item.get("kind") == "warranty" and item.get("warranty_expiry"):
                try:
                    exp = datetime.fromisoformat(item["warranty_expiry"]).date()
                    if exp <= datetime.now().date() + timedelta(days=30):
                        warranty_exp.append(item)
                except Exception:
                    pass
        
        return {
            "overdue": overdue,
            "due_soon": due_soon,
            "warranty_expiring": warranty_exp,
            "total_items": len(data.get("items", [])),
            "timestamp": datetime.now().isoformat(),
        }
    
    def connect(self, signals: dict) -> list:
        insights = []
        for item in signals.get("overdue", []):
            insights.append({
                "type": "maintenance_overdue",
                "content": f"Overdue maintenance: {item['name']}",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": item,
            })
        for item in signals.get("due_soon", []):
            insights.append({
                "type": "maintenance_due_soon",
                "content": f"Maintenance due soon: {item['name']}",
                "action_suggested": "flag_board",
                "severity": "medium",
                "item": item,
            })
        for item in signals.get("warranty_expiring", []):
            insights.append({
                "type": "warranty_expiring",
                "content": f"Warranty expiring: {item['name']}",
                "action_suggested": "flag_board",
                "severity": "medium",
                "item": item,
            })
        return insights
    
    def anticipate(self, signals: dict, insights: list) -> list:
        return []
    
    def plan(self, signals: dict, insights: list, anticipations: list) -> list:
        plans = []
        for insight in insights:
            priority = 8 if insight.get("severity") == "high" else 5
            plans.append({
                "action": "flag_board",
                "item": insight.get("item"),
                "priority": priority,
                "confidence": 0.9,
            })
        return plans
    
    def act(self, plans: list, signals: dict) -> list:
        results = []
        for plan in plans:
            if plan["action"] == "flag_board":
                item = plan["item"]
                # Add to agentbus board
                import urllib.request, urllib.parse, json as _json
                try:
                    payload = {
                        "op": "add",
                        "key": f"housekeep-{item['name'].lower().replace(' ', '-')}",
                        "title": f"[housekeep] {item['name']}",
                        "area": "housekeep",
                        "status": "ready",
                        "owner": "housekeep",
                        "note": item.get("name", ""),
                    }
                    data = json.dumps(payload).encode()
                    req = urllib.request.Request("http://127.0.0.1:9107/task", data=data, method="POST",
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    
                    if hasattr(self, "send_to_own_topic"):
                        self.send_to_own_topic(f"🏠 Maintenance: {item['name']}")
                    
                    results.append({"action": "flag_board", "status": "ok", "item": item["name"]})
                except Exception as e:
                    results.append({"action": "flag_board", "status": "error", "error": str(e)})
        return results


if __name__ == "__main__":
    import sys
    agent = HousekeepAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(agent.run_cycle(), indent=2))