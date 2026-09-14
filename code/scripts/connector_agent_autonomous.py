#!/usr/bin/env python3
"""
connector_agent_autonomous.py — People/Relationships autonomous agent.
"""

from __future__ import annotations
from autonomous_agent import AutonomousAgent
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, os


class ConnectorAgent(AutonomousAgent):
    """People: birthdays, anniversaries, follow-ups."""
    
    def __init__(self):
        super().__init__(
            name="connector",
            domain="people",
            topic_id=10025,  # Memos topic,
            cycle_interval_minutes=60,
        )
        self.store_path = os.path.expanduser("~/.hermes/agents/connector/store.json")
    
    def _load_store(self) -> dict:
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"items": [], "meta": {}}
    
    def observe(self) -> dict:
        data = self._load_store()
        today = datetime.now().date()
        
        birthdays_due = []
        anniversaries_due = []
        followups_due = []
        
        for item in data.get("items", []):
            kind = item.get("kind")
            
            if kind in ("birthday", "anniversary"):
                when = item.get("date", "")
                if not when:
                    continue
                try:
                    d = datetime.fromisoformat(when).date()
                except Exception:
                    continue
                # Next occurrence
                this_year = d.replace(year=today.year)
                if this_year < today:
                    this_year = d.replace(year=today.year + 1)
                days = (this_year - today).days
                
                if 0 <= days <= 7:
                    if kind == "birthday":
                        birthdays_due.append({**item, "days": days, "occurrence": this_year.isoformat()})
                    else:
                        anniversaries_due.append({**item, "days": days, "occurrence": this_year.isoformat()})
            
            elif kind == "followup":
                interval = item.get("interval_days")
                last = item.get("last_contact", "")
                if not interval:
                    continue
                if last:
                    try:
                        last_d = datetime.fromisoformat(last).date()
                        gap = (today - last_d).days
                        if gap >= interval:
                            followups_due.append({**item, "gap": gap})
                    except Exception:
                        followups_due.append({**item, "gap": None})
                else:
                    followups_due.append({**item, "gap": None})
        
        return {
            "birthdays_due": birthdays_due,
            "anniversaries_due": anniversaries_due,
            "followups_due": followups_due,
            "total_items": len(data.get("items", [])),
            "timestamp": datetime.now().isoformat(),
        }
    
    def connect(self, signals: dict) -> list:
        insights = []
        for item in signals.get("birthdays_due", []):
            insights.append({
                "type": "birthday_due",
                "content": f"Birthday: {item['name']} in {item['days']} day(s) ({item['occurrence']})",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": item,
            })
        
        for item in signals.get("anniversaries_due", []):
            insights.append({
                "type": "anniversary_due",
                "content": f"Anniversary: {item['name']} in {item['days']} day(s) ({item['occurrence']})",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": item,
            })
        
        for item in signals.get("followups_due", []):
            gap = item.get("gap", "?")
            insights.append({
                "type": "followup_due",
                "content": f"Follow up with {item['name']} (gap: {gap}d)",
                "action_suggested": "flag_board",
                "severity": "medium",
                "item": item,
            })
        
        return insights

    def anticipate(self, signals, insights):
        return []

    def plan(self, signals, insights, anticipations):
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

    def act(self, plans, signals) -> list:
        results = []
        for plan in plans:
            if plan["action"] == "flag_board":
                item = plan["item"]
                import urllib.request, json
                try:
                    payload = {
                        "op": "add",
                        "key": f"connector-{item['name'].lower().replace(' ', '-')}",
                        "title": f"[connector] {item['name']}",
                        "area": "connector",
                        "status": "ready",
                        "owner": "connector",
                        "note": item.get("name", ""),
                    }
                    req = urllib.request.Request("http://127.0.0.1:9107/task", data=json.dumps(payload).encode(), method="POST",
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    
                    if hasattr(self, "send_to_own_topic"):
                        self.send_to_own_topic(f"👥 {item['name']} due")
                    
                    results.append({"action": "flag_board", "status": "ok", "item": item.get("name")})
                except Exception as e:
                    results.append({"action": "flag_board", "status": "error", "error": str(e)})
        return results


if __name__ == "__main__":
    import sys
    agent = ConnectorAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(list(agent.run_cycle()), indent=2))