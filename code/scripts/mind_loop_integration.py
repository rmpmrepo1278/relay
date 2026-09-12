#!/usr/bin/env python3
"""mind_loop_integration.py - Integration layer for autonomy modules into mind loop.

Hooks into the mind loop's observe/connect/anticipate/plan/act cycle
to add cross-database intelligence, failure learning, self-modeling,
and memory synthesis capabilities.
"""

import json
import sys
from pathlib import Path
from datetime import datetime



# Reinforcement learning
try:
    import reinforcement_learning
    _reinforcement_learning = True
except ImportError:
    _reinforcement_learning = False

# Disaster recovery
try:
    import disaster_recovery
    _disaster_recovery = True
except ImportError:
    _disaster_recovery = False

# Self-modification
try:
    import self_modifier
    _self_modifier = True
except ImportError:
    _self_modifier = False

# Circuit breaker
try:
    import circuit_breaker
    _circuit_breaker = True
except ImportError:
    _circuit_breaker = False

# Simulation
try:
    import simulation_engine
    _simulation = True
except ImportError:
    _simulation = False

# Personalization
try:
    import personalization
    _personalization = True
except ImportError:
    _personalization = False

# Adaptive parameters
try:
    import adaptive_params
    _adaptive_params = True
except ImportError:
    _adaptive_params = False

# Tier 1: Critical autonomy
try:
    import self_improvement_loop
    _self_improvement = True
except ImportError:
    _self_improvement = False

try:
    import goal_engine
    _goal_engine = True
except ImportError:
    _goal_engine = False

try:
    import uncertainty_engine
    _uncertainty = True
except ImportError:
    _uncertainty = False

try:
    import knowledge_curator
    _knowledge_curator = True
except ImportError:
    _knowledge_curator = False

# Tier 2: Leading edge
try:
    import metacognition
    _metacognition = True
except ImportError:
    _metacognition = False

try:
    import skill_acquisition
    _skill_acquisition = True
except ImportError:
    _skill_acquisition = False

try:
    import behavioral_monitor
    _behavioral_monitor = True
except ImportError:
    _behavioral_monitor = False

try:
    import adversarial_tester
    _adversarial = True
except ImportError:
    _adversarial = False

# Tier 3: Advanced
try:
    import causal_reasoner
    _causal_reasoner = True
except ImportError:
    _causal_reasoner = False

try:
    import agent_delegator
    _agent_delegator = True
except ImportError:
    _agent_delegator = False

HERMES_HOME = Path.home() / ".hermes"
SCRIPTS_DIR = HERMES_HOME / "scripts"

# Add scripts dir to path for imports
sys.path.insert(0, str(SCRIPTS_DIR))


def observe_intelligence(signals, cycle_num=1):
    """Enhanced observation: pull from unified memory index + behavioral metrics."""
    try:
        from unified_memory_index import get_cross_domain_summary
        summary = get_cross_domain_summary()
        signals["intelligence"] = {
            "knowledge_summary": summary,
            "observed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        signals["intelligence"] = {"error": str(e)}

    # Temporal KG entity health
    try:
        from memory_synthesizer import synthesize_entity_health
        entities = synthesize_entity_health()
        stale = [e for e in entities if e["freshness"] in ("stale", "aging")]
        if stale:
            signals["intelligence"]["stale_entities"] = [e["name"] for e in stale[:5]]
    except Exception:
        pass

    # Track user active time
    if _personalization:
        try:
            personalization.record_active_time()
        except Exception:
            pass

    # Disaster recovery health check (every 10th cycle)
    if _disaster_recovery and cycle_num % 10 == 0:
        try:
            health = disaster_recovery.check_service_health()
            unhealthy = [h for h in health if h.get("status") != "healthy"]
            if unhealthy:
                signals.setdefault("health_alerts", []).extend(unhealthy)
                # Auto-recover
                disaster_recovery.auto_recover()
        except Exception:
            pass

    # Record behavioral metrics
    if _behavioral_monitor:
        try:
            import time
            behavioral_monitor.record_metric("cycle_start", time.time())
        except Exception:
            pass

    return signals


def connect_intelligence(state, signals, insights, cycle_num=1):
    """Enhanced pattern detection: cross-DB synthesis."""
    try:
        from memory_synthesizer import synthesize_recurring_issues
        issues = synthesize_recurring_issues()
        if issues:
            insights.append({
                "type": "recurring_issues",
                "content": f"Found {len(issues)} recurring issues across systems",
                "severity": "warning",
                "details": issues[:5],
            })
    except Exception:
        pass

    try:
        from memory_synthesizer import synthesize_temporal_patterns
        temporal = synthesize_temporal_patterns()
        if temporal.get("peak_hour"):
            insights.append({
                "type": "temporal_pattern",
                "content": f"Peak activity at {temporal['peak_hour']}, busiest day: {temporal.get('peak_day', 'unknown')}",
                "severity": "info",
            })
    except Exception:
        pass

    # Knowledge curation (every 5th cycle)
    if _knowledge_curator and cycle_num % 5 == 0:
        try:
            curation = knowledge_curator.run_curation()
            if any(v > 0 for v in curation.values()):
                insights.append({
                    "type": "curation",
                    "content": f"Knowledge curation: {curation}",
                    "severity": "info",
                })
        except Exception:
            pass

    return insights


def anticipate_intelligence(state, signals, insights, anticipations):
    """Enhanced prediction: use self-model and temporal reasoning."""
    try:
        from temporal_self_reasoning import get_self_assessment
        assessment = get_self_assessment()
        if assessment.get("knowledge_freshness") == "stale":
            anticipations.append({
                "type": "stale_knowledge",
                "content": "Knowledge base is stale - consider refreshing key entities",
                "urgency": "medium",
            })
        if assessment.get("task_reliability") in ("poor", "needs_improvement"):
            anticipations.append({
                "type": "task_reliability_low",
                "content": "Task completion rate is below threshold - investigate root causes",
                "urgency": "high",
            })
    except Exception:
        pass

    try:
        from failure_learning_pipeline import apply_behavior_changes
        changes = apply_behavior_changes()
        if changes:
            anticipations.append({
                "type": "behavior_changes_needed",
                "content": f"{len(changes)} recurring failure patterns suggest behavior changes",
                "urgency": "medium",
                "details": changes,
            })
    except Exception:
        pass

    # Self-improvement loop
    if _self_improvement:
        try:
            improvement = self_improvement_loop.run_cycle()
            if improvement["proposed"] > 0:
                anticipations.append({
                    "type": "self_improvement",
                    "content": f"Applied {improvement["proposed"]} improvements from {improvement["pending"]} pending learnings",
                    "urgency": "low",
                })
        except Exception:
            pass

    # Uncertainty check
    if _uncertainty:
        try:
            unknowns = uncertainty_engine.get_open_unknowns()
            if unknowns:
                anticipations.append({
                    "type": "knowledge_gaps",
                    "content": f"{len(unknowns)} open questions - consider researching",
                    "urgency": "low",
                })
        except Exception:
            pass

    # Adversarial testing
    if _adversarial:
        try:
            untested = adversarial_tester.get_untested_assumptions()
            if untested:
                anticipations.append({
                    "type": "untested_assumptions",
                    "content": f"{len(untested)} assumptions untested - run stress tests",
                    "urgency": "low",
                })
        except Exception:
            pass

    return anticipations


def plan_intelligence(insights, anticipations, plans):
    """Enhanced planning: use cross-domain model for balance."""
    try:
        from cross_domain_model import get_balance_score
        balance = get_balance_score()
        if balance["overall"] < 0.5:
            plans.append({
                "action": "balance_focus",
                "content": f"Life balance score low ({balance['overall']}). {balance.get('recommendation', '')}",
                "priority": "medium",
            })
    except Exception:
        pass

    try:
        from temporal_self_reasoning import plan_next_actions
        suggested_actions = plan_next_actions()
        for action in suggested_actions[:3]:
            plans.append({
                "action": f"intelligent_{action.get('action', 'task')}",
                "content": action["reason"],
                "priority": action["priority"],
            })
    except Exception:
        pass

    # Simulate high-risk plans before committing
    if _simulation:
        simulated_plans = []
        for p in plans:
            action = p.get("content", p.get("action", ""))
            if any(kw in action.lower() for kw in ["restart", "delete", "remove", "config", "deploy"]):
                sim = simulation_engine.simulate(action)
                p["simulation"] = sim
                if not sim.get("recommended", True):
                    p["priority"] = "low"  # Downgrade risky actions
            simulated_plans.append(p)
        plans = simulated_plans

    # Goal-directed planning
    if _goal_engine:
        try:
            next_goal = goal_engine.get_next_actionable()
            if next_goal:
                plans.append({
                    "action": "pursue_goal",
                    "content": f"Next goal: {next_goal["title"]} ({next_goal["progress"]:.0%})",
                    "priority": "high",
                })

            suggestions = goal_engine.suggest_next_steps()
            for s in suggestions[:2]:
                plans.append({
                    "action": s["action"],
                    "content": s.get("title", s.get("reason", "")),
                    "priority": "medium",
                })
        except Exception:
            pass

    # Safety: ensure all plans have required keys
    safe_plans = []
    for p in plans:
        if not isinstance(p, dict):
            continue
        safe_p = {
            "action": p.get("action", "generic"),
            "content": p.get("content", ""),
            "priority": p.get("priority", "medium"),
        }
        # Preserve extra keys (like simulation data)
        for key in ("simulation", "goal_id", "reason", "source_insight"):
            if key in p:
                safe_p[key] = p[key]
        safe_plans.append(safe_p)

    return safe_plans


def act_intelligence(plan, context=None):
    """Enhanced action: record attempt in self-model for learning."""
    try:
        from self_model import record_attempt
        # Record that we attempted this plan
        cap_name = plan.get("action", "unknown")
        record_attempt(cap_name, "mind_loop", True, json.dumps(context or {}))
    except Exception:
        pass

    return True


def record_failure_intelligence(component, error, context=""):
    """Record a failure for the learning pipeline."""
    try:
        from failure_learning_pipeline import record_failure
        return record_failure(component, error, context)
    except Exception:
        return None


def get_intelligence_summary():
    """Get a comprehensive summary of all intelligence modules."""
    summary = {"timestamp": datetime.now().isoformat(), "modules": {}}

    # Unified memory
    try:
        from unified_memory_index import get_cross_domain_summary
        summary["modules"]["unified_memory"] = get_cross_domain_summary()
    except Exception as e:
        summary["modules"]["unified_memory"] = {"error": str(e)}

    # Self model
    try:
        from self_model import get_capability_summary, get_weak_areas, get_active_limitations
        caps = get_capability_summary()
        weak = get_weak_areas()
        limits = get_active_limitations()
        summary["modules"]["self_model"] = {
            "capabilities": len(caps),
            "weak_areas": len(weak),
            "limitations": len(limits),
        }
    except Exception as e:
        summary["modules"]["self_model"] = {"error": str(e)}

    # Failure learning
    try:
        from failure_learning_pipeline import get_learning_stats
        summary["modules"]["failure_learning"] = get_learning_stats()
    except Exception as e:
        summary["modules"]["failure_learning"] = {"error": str(e)}

    # Memory synthesizer
    try:
        from memory_synthesizer import generate_insight_report
        summary["modules"]["memory_synthesizer"] = generate_insight_report()
    except Exception as e:
        summary["modules"]["memory_synthesizer"] = {"error": str(e)}

    # Self assessment
    try:
        from temporal_self_reasoning import get_self_assessment
        summary["modules"]["self_assessment"] = get_self_assessment()
    except Exception as e:
        summary["modules"]["self_assessment"] = {"error": str(e)}

    # Cross-domain balance
    try:
        from cross_domain_model import get_balance_score
        summary["modules"]["balance"] = get_balance_score()
    except Exception as e:
        summary["modules"]["balance"] = {"error": str(e)}

    # Self-improvement stats
    if _self_improvement:
        try:
            summary["modules"]["self_improvement"] = self_improvement_loop.get_improvement_stats()
            summary["modules"]["improvement_rate"] = self_improvement_loop.get_improvement_rate()
        except Exception as e:
            summary["modules"]["self_improvement"] = {"error": str(e)}

    # Goal engine
    if _goal_engine:
        try:
            summary["modules"]["goals"] = goal_engine.get_goal_stats()
        except Exception as e:
            summary["modules"]["goals"] = {"error": str(e)}

    # Uncertainty
    if _uncertainty:
        try:
            summary["modules"]["uncertainty"] = uncertainty_engine.get_confidence_stats()
        except Exception as e:
            summary["modules"]["uncertainty"] = {"error": str(e)}

    # Knowledge curation
    if _knowledge_curator:
        try:
            summary["modules"]["knowledge_curation"] = knowledge_curator.get_curation_stats()
        except Exception as e:
            summary["modules"]["knowledge_curation"] = {"error": str(e)}

    # Metacognition
    if _metacognition:
        try:
            summary["modules"]["metacognition"] = metacognition.get_metacognition_summary()
        except Exception as e:
            summary["modules"]["metacognition"] = {"error": str(e)}

    # Skill acquisition
    if _skill_acquisition:
        try:
            summary["modules"]["skills"] = skill_acquisition.get_skill_stats()
        except Exception as e:
            summary["modules"]["skills"] = {"error": str(e)}

    # Behavioral drift
    if _behavioral_monitor:
        try:
            alerts = behavioral_monitor.check_drift()
            summary["modules"]["behavioral_drift"] = {"alerts": len(alerts)}
        except Exception as e:
            summary["modules"]["behavioral_drift"] = {"error": str(e)}

    # Adversarial testing
    if _adversarial:
        try:
            summary["modules"]["adversarial"] = adversarial_tester.get_testing_stats()
        except Exception as e:
            summary["modules"]["adversarial"] = {"error": str(e)}

    # Causal reasoning
    if _causal_reasoner:
        try:
            summary["modules"]["causal"] = causal_reasoner.get_causal_stats()
        except Exception as e:
            summary["modules"]["causal"] = {"error": str(e)}

    # Agent delegation
    if _agent_delegator:
        try:
            summary["modules"]["delegation"] = agent_delegator.get_delegation_stats()
        except Exception as e:
            summary["modules"]["delegation"] = {"error": str(e)}

    # Reinforcement learning
    if _reinforcement_learning:
        try:
            summary["modules"]["reinforcement_learning"] = reinforcement_learning.get_rl_stats()
        except Exception as e:
            summary["modules"]["reinforcement_learning"] = {"error": str(e)}

    # Disaster recovery
    if _disaster_recovery:
        try:
            summary["modules"]["disaster_recovery"] = disaster_recovery.get_recovery_stats()
        except Exception as e:
            summary["modules"]["disaster_recovery"] = {"error": str(e)}

    # Self-modification
    if _self_modifier:
        try:
            summary["modules"]["self_modification"] = self_modifier.get_modification_stats()
        except Exception as e:
            summary["modules"]["self_modification"] = {"error": str(e)}

    # Circuit breaker
    if _circuit_breaker:
        try:
            summary["modules"]["circuit_breaker"] = circuit_breaker.get_cb_stats()
        except Exception as e:
            summary["modules"]["circuit_breaker"] = {"error": str(e)}

    # Simulation
    if _simulation:
        try:
            summary["modules"]["simulation"] = simulation_engine.get_sim_stats()
        except Exception as e:
            summary["modules"]["simulation"] = {"error": str(e)}

    # Personalization
    if _personalization:
        try:
            summary["modules"]["personalization"] = personalization.get_personalization_summary()
        except Exception as e:
            summary["modules"]["personalization"] = {"error": str(e)}

    # Adaptive parameters
    if _adaptive_params:
        try:
            summary["modules"]["adaptive_params"] = adaptive_params.get_adaptive_stats()
        except Exception as e:
            summary["modules"]["adaptive_params"] = {"error": str(e)}

    return summary


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        print(json.dumps(get_intelligence_summary(), indent=2, default=str))
    elif cmd == "test":
        print("Testing all modules...")
        for mod_name in ["unified_memory_index", "failure_learning_pipeline",
                         "self_model", "memory_synthesizer",
                         "temporal_self_reasoning", "cross_domain_model"]:
            try:
                __import__(mod_name)
                print(f"  OK: {mod_name}")
            except Exception as e:
                print(f"  FAIL: {mod_name}: {e}")
        print("Done.")
