#!/usr/bin/env python3
"""Generate an ASCII diagram showing the 16 database ecosystem."""

print(r"""
HERMES DATABASE ECOSYSTEM — 16 SQLite Databases

┌─────────────────────────────────────────────────────────────────────────────┐
│                           HERMES_HOME (.hermes/)                            │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                     │
│  │  state.db      │  │ temporal_kg.db │  │ claudemem.db   │                     │
│  │ (147 MB)       │  │ (13 MB)        │  │ (5.7 MB)       │                     │
│  │ ─────────       │  │ ───────────     │  │ ──────────     │                     │
│  │ sessions        │  │ entities       │  │ observations   │                     │
│  │ messages        │  │ facts          │  │ compressed_mem │                     │
│  │ goals           │  │ decisions       │  │ session_summ   │                     │
│  │ goal_log         │  │ (temporal DB)   │  │ sops           │                     │
│  └────┬─────────────┘  └──────────────┘  └──────────────┘                     │
│       │                                                                         │
│       │  unified_memory_index.py queries across all of these                    │
│       │                                                                         │
│  ┌──────────────┐  ┌──────────────┐                                             │
│  │ kanban.db      │  │ shared_facts.db│                                            │
│  │ (112 KB)       │  │ (52 KB)          │                                            │
│  │ ──────────      │  │ ────────────     │  (homelab)  (homelab)                     │
│  │ tasks            │  │ shared_facts     │                                            │
│  │ task_runs        │  │ (FST index)      │                                            │
│  │ task_events      │  │                  │                                            │
│  └──────────────────┘  └──────────────────┘                                            │
│                                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  data/ (application databases)                                       │    │
│  │                                                                       │    │
│  │  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐             │    │
│  │  │ unified_memory   │  │ decisions.db  │  │ personal.db   │             │    │
│  │  │ (60+ tables)     │  │ (6KB→)        │  │ (habits,      │             │    │
│  │  │ ──────────────── │  │ ───────────   │  │  projects,     │             │    │
│  │  │ memory_store      │  │ decisions     │  │  habits...)   │             │    │
│  │  │ kg_nodes/edges    │  │ risks         │  │ health_log    │             │    │
│  │  │ gene_actions       │  │ decisions      │  │ financial_items│            │    │
│  │  │ narratives         │  │ decision_log   │  │ emotional_dump │            │    │
│  │  └────────┬──────────┘  └──────────────┘  └──────────────┘             │    │
│  │           │                                                                  │    │
│  │  ┌────────┴─────────┐  ┌────────────────┐  ┌──────────────┐              │    │
│  │  │ self_improvement   │  │ failure_learning │  │ self_model    │              │    │
│  │  │ .db                 │ │ .db               │ │ .db            │              │    │
│  │  │ ─────────────────   │ │ ───────────────   │ │ ─────────────  │              │    │
│  │  │ improvement_cycles │ │ failures          │ │ capabilities   │              │    │
│  │  │ behavior_baselines  │ │ failure_patterns  │ │ capability_log │              │    │
│  │  │ improvement_log    │ │ learnings         │ │ limitations    │              │    │
│  │  └───────────────────┘  └─────────────────┘  └──────────────┘              │    │
│  │                                                                       │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │ uncertainty    │ │ metacognition  │ │ skill_acquis  │ │ causal_reason  │    │    │
│  │  │ .db             │ │ .db            │ │ .db           │ │ .db           │    │    │
│  │  │ ──────────────  │ │ ─────────────  │ │ ────────────  │ │ ─────────────  │    │    │
│  │  │ confidence_      │ │ reflections      │ │ skills        │ │ causal_chains  │    │    │
│  │  │ scores           │ │ cognitive_biases  │ │ skill_usage   │ │ interventions  │    │    │
│  │  │ unknowns         │ │ reasoning_chains  │ │ skill_rules   │ │ counterfactuals│    │    │
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘  └──────────────┘    │    │
│  │                                                                       │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │ behavioral_    │ │ simulation      │ │ personalization │ │ adaptive_params  ││    │    │
│  │  │ monitor.db      │ │ engine.db        │ │ .db            │ │ .db            │    │    │
│  │  │ ──────────────  │ │ ───────────────  │ │ ─────────────  │ │ ────────────────  ││    │    │
│  │  │ behavior_metr   │ │ simulations       │ │ user_pref       │ │ parameters       ││    │    │
│  │  │ baselines       │ │ simulation_rules  │ │ comm_patterns   │ │ parameter_hist   ││    │    │
│  │  │ drift_alerts    │ │                   │ │ topic_interests │ │ experiments      ││    │    │
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘  └──────────────┘    │    │
│  │                                                                       │    │
│  │  ┌──────────────┐  ┌────────────────┐                                   │    │
│  │  │ agent_deleg    │ │ knowledge_cura   │                                   │    │
│  │  │ tion.db         │ │ tion.db          │                                   │    │
│  │  │ ──────────────  │ │ ───────────────  │                                   │    │
│  │  │ delegations     │ │ curation_log     │                                   │    │
│  │  │ agent_capabi    │ │ fact_clusters    │                                   │    │
│  │  │ lities           │ │                   │                                   │    │
│  │  └─────────────────┘  └─────────────────┘                                   │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────┐                                                             │
│  │ entities.db   │ (empty — reserved for future use)                          │
│  │ (4 KB)        │                                                             │
│  └──────────────┘                                                             │
│                                                                              │
│  TOTAL: 16 databases, ~215 MB combined                                      │
└─────────────────────────────────────────────────────────────────────────────┘

DATA FLOW:
  External signals → OBSERVE → CONNECT → ANTICIPATE → PLAN → ACT
                          ↑                    │                  │
                          │                    │                  │
                    unified_memory_index    insights           plans + simulation
                          │                    │                  │
                    temporal_kg (read)   memory_synthesizer   circuit_breaker (guard)
                          │                    │                  │
                    state.db (read)        goal_engine        skill_acquisition
                                                                       │
                    LEARNING LOOP:                                        │
                    failures → failure_learning → self_improvement ──────┘
                    feedback → reinforcement_learning → adaptive_params
                    execution → skill_acquisition → skill_acquisition
                    decisions → metacognition → self_modification
                    metrics → behavioral_monitor → behavioral_drift
                    assumptions → adversarial_tester → metacognition
                    causes → causal_reasoner → causal_chains
                    tasks → agent_delegator → agent_delegation
                    knowledge → knowledge_curator → knowledge_curation
                    health → disaster_recovery → disaster_recovery
                    user → personalization → personalization.db

  State → mind_loop.json + loop_state.py
  Insights → mind_insights.jsonl
  Failures → failure_learning.db
  Learnings → self_improvement.db
  Feedback → reinforcement_learning.db
  Behavior → behavioral_drift.db
"""
)
