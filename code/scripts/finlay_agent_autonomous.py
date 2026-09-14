#!/usr/bin/env python3
"""
finlay_agent_autonomous.py — Finances autonomous agent.
"""

from __future__ import annotations
from autonomous_agent import AutonomousAgent, _log
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, subprocess, os


class FinlayAgent(AutonomousAgent):
    """Finances: bills, subscriptions, budget, anomalies."""
    
    def __init__(self):
        super().__init__(
            name="finlay",
            domain="finance",
            topic_id=10122,  # Finances topic,  # personal topic
            cycle_interval_minutes=60,
        )
        self.store_path = os.path.expanduser("~/.hermes/agents/finlay/store.json")
    
    def _load_store(self) -> dict:
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"items": [], "meta": {}}
    
    def _save_store(self, data: dict):
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        tmp = self.store_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.store_path)
    
    def observe(self) -> dict:
        data = self._load_store()
        today = datetime.now().date()
        
        bills_due = []
        subs_renewing = []
        
        for item in data.get("items", []):
            kind = item.get("kind")
            due = item.get("due", "")
            if not due:
                continue
            try:
                d = datetime.fromisoformat(due).date()
            except Exception:
                continue
            days = (d - datetime.now().date()).days
            
            if kind == "bill" and 0 <= days <= 2:
                bills_due.append({**item, "days_until_due": days})
            elif kind == "subscription" and 0 <= days <= 14:
                subs_renewing.append({**item, "days_until_renewal": days})
        
        return {
            "bills_due": bills_due,
            "subs_renewing": subs_renewing,
            "total_items": len(data.get("items", [])),
            "timestamp": datetime.now().isoformat(),
        }
    
    def connect(self, signals: dict) -> list:
        insights = []
        for bill in signals.get("bills_due", []):
            insights.append({
                "type": "bill_due",
                "content": f"Bill due: {bill['name']} (${bill.get('amount', 0)}) in {bill['days_until_due']} day(s)",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": bill,
            })
        for sub in signals.get("subs_renewing", []):
            insights.append({
                "type": "sub_renewal",
                "content": f"Subscription renewing: {sub['name']} (${sub.get('amount', 0)}) in {sub['days_until_renewal']} day(s)",
                "action_suggested": "flag_board",
                "severity": "medium",
                "item": sub,
            })
        return []
    
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
                        "key": f"finlay-{item['name'].lower().replace(' ', '-')}",
                        "title": f"[finlay] {item['name']} due (${item.get('amount', 0)})",
                        "area": "finlay",
                        "status": "ready",
                        "owner": "finlay",
                        "due": item.get("due", ""),
                        "note": item.get("name", ""),
                    }
                    data = _json.dumps(payload).encode()
                    req = urllib.request.Request("http://127.0.0.1:9107/task", data=data, method="POST",
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    
                    # Send to Telegram
                    if hasattr(self, "send_to_own_topic"):
                        self.send_to_own_topic(f"💰 Bill due: {item['name']} (${item.get('amount', 0)})")
                    
                    return [{"action": "flag_board", "status": "ok", "item": item["name"]}]
                except Exception as e:
                    return [{"action": "flag_board", "status": "error", "error": str(e)}]
        return []


if __name__ == "__main__":
    import sys
    agent = FinlayAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(agent.run_cycle(), indent=2))