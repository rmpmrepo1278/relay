#!/usr/bin/env python3
"""
calendula_agent_autonomous.py — Schedule/Health autonomous agent.
"""

from __future__ import annotations
from autonomous_agent import AutonomousAgent
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import json, os


class CalendulaAgent(AutonomousAgent):
    """Schedule/Health: appointments, meds, fitness, travel, ID expiry."""
    
    def __init__(self):
        super().__init__(
            name="calendula",
            domain="schedule_health",
            topic_id=10028,  # schedule/health topic,
            cycle_interval_minutes=60,
        )
        self.store_path = os.path.expanduser("~/.hermes/agents/calendula/store.json")
    
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
        
        appt_due = []
        meds_due = []
        ids_expiring = []
        travel_upcoming = []
        fitness_stale = []
        
        for item in data.get("items", []):
            kind = item.get("kind")
            when = item.get("date", "")
            if not when:
                continue
            try:
                d = datetime.fromisoformat(when).date()
            except Exception:
                continue
            days = (d - datetime.now().date()).days
            
            if kind in ("appointment", "travel") and 0 <= days <= 1:
                appt_due.append({**item, "days": days})
            elif kind == "medication-renewal" and 0 <= days <= 14:
                meds_due.append({**item, "days": days})
            elif kind == "id-expiry" and 0 <= days <= 60:
                ids_expiring.append({**item, "days": days})
            elif kind == "fitness" and days < 0:
                fitness_stale.append({**item, "days": days})
        
        return {
            "appointments_due": appt_due,
            "meds_due": meds_due,
            "ids_expiring": ids_expiring,
            "fitness_stale": fitness_stale,
            "total_items": len(data.get("items", [])),
            "timestamp": datetime.now().isoformat(),
        }
    
    def connect(self, signals: dict) -> list:
        insights = []
        for item in signals.get("appointments_due", []):
            insights.append({
                "type": "appointment_due",
                "content": f"Appointment: {item['name']} in {item['days']} day(s)",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": item,
            })
        
        for item in signals.get("meds_due", []):
            insights.append({
                "type": "med_renewal",
                "content": f"Med renewal: {item['name']} in {item['days']} day(s)",
                "action_suggested": "flag_board",
                "severity": "high",
                "item": item,
            })
        
        for item in signals.get("ids_expiring", []):
            insights.append({
                "type": "id_expiring",
                "content": f"ID expiring: {item['name']} in {item['days']} day(s)",
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
                        "key": f"calendula-{item['name'].lower().replace(' ', '-')}",
                        "title": f"[calendula] {item['name']}",
                        "area": "calendula",
                        "status": "ready",
                        "owner": "calendula",
                        "due": item.get("date", ""),
                        "note": item.get("name", ""),
                    }
                    req = urllib.request.Request("http://127.0.0.1:9107/task", data=json.dumps(payload).encode(), method="POST",
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    
                    if hasattr(self, "send_to_own_topic"):
                        self.send_to_own_topic(f"📅 {item['name']} due")
                    
                    results.append({"action": "flag_board", "status": "ok", "item": item.get("name")})
                except Exception as e:
                    results.append({"action": "flag_board", "status": "error", "error": str(e)})
        return results


if __name__ == "__main__":
    import sys
    agent = CalendulaAgent()
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        agent.run_daemon()
    else:
        import json
        print(json.dumps(list(agent.run_cycle()), indent=2))