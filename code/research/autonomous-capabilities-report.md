# Autonomous Agent Capabilities — Research Report
> Generated: 2026-06-17 | Scope: Open-source agentic infrastructure for homelab deployment

---

## Executive Summary

Research across 100+ GitHub repos, papers, and projects identified **~40 concrete capabilities** that could enhance Hermes. Below are the top recommendations ranked by **impact × ease of integration** for our specific setup (Telegram-based agent, Docker homelab, LLM proxy, existing autonomous fixer + gene engine + capsule tracking).

**Key insight from the research:** The biggest gap in Hermes isn't monitoring — it's **compounding learning**. We detect issues and we fix them, but we don't systematically learn from successes/failures, evolve our own strategies, or build persistent knowledge that makes us smarter over time.

---

## Tier 1: Drop-In Enhancements (Low Effort, High Impact)

### 1. Reflexion Memory Buffer — Learn From Every Fix Attempt
- **Source:** [noahshinn/reflexion](https://github.com/noahshinn/reflexion) (NeurIPS 2023, 3.1K stars)
- **What:** After each fix attempt, generate a natural-language reflection on what worked/didn't. Store in a JSONL file. On next attempt, prepend relevant reflections to the prompt.
- **Why for us:** Our Capsule outcome tracking already records success/failure but doesn't feed it back into the reasoning loop. The autonomous_fixer keeps trying the same approaches (paper-agent has failed 3× with the same gene).
- **Integration:** Add a `reflexion_buffer.py` module. On each fix attempt, query past reflections for the same (issue_type, target) before acting. ~50 lines of Python.
- **Effort:** LOW | **Impact:** HIGH

### 2. DSPy + GEPA — Auto-Optimize Our Own Prompts
- **Source:** [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) (35K stars) + [gepa-ai/gepa](https://github.com/gepa-ai/gepa) (ICLR 2026 Oral)
- **What:** DSPy lets you define prompt "signatures" declaratively, then auto-compiles them with optimizers. GEPA uses evolutionary search over full execution traces to optimize prompts — 35x fewer evaluations than GRPO.
- **Why for us:** Our Hermes system prompt, skill files, and autonomous fixer prompts are all hand-written. DSPy could A/B test variants and evolve better ones automatically.
- **Integration:** Define DSPy signatures for key Hermes tasks (fix diagnosis, health assessment). Use GEPA to optimize. Can run on our local Ollama.
- **Effort:** MEDIUM | **Impact:** HIGH

### 3. Promptfoo — A/B Test Everything
- **Source:** [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) (22K stars)
- **What:** Local prompt testing framework. Define test cases + providers → run evaluations → side-by-side comparison. Supports 50+ providers including Ollama. Runs 100% locally.
- **Why for us:** Zero-cost way to validate prompt changes before deploying. Test Hermes skill triggers, autonomous fixer decision quality, etc.
- **Integration:** `npm install -g promptfoo`, define test YAML, run in CI or manually. No infrastructure changes.
- **Effort:** LOW | **Impact:** MEDIUM

### 4. CRITIC-Style Tool-Grounded Verification
- **Source:** [microsoft/CRITIC](https://github.com/microsoft/CRITIC)
- **What:** LLM uses external tools (search, code execution, API calls) to verify its own factual claims before responding. Grounds self-correction in reality, not just internal reasoning.
- **Why for us:** Hermes sometimes hallucinates service states. CRITIC pattern: before claiming "service X is healthy," actually `curl` it. Before saying "disk is fine," actually run `df`.
- **Integration:** Add a verification step to Hermes's response pipeline. Already have the tools (SearXNG, bash execution). Just need the discipline.
- **Effort:** LOW | **Impact:** HIGH (reduces hallucinations)

### 5. Self-Discover — Reasoning Structure Selection
- **Source:** [arxiv.org/abs/2402.03620](https://arxiv.org/abs/2402.03620)
- **What:** Before tackling a complex task, the LLM selects and composes atomic reasoning modules (critical thinking, step-by-step decomposition, etc.) into a task-specific reasoning structure. +32% on BigBench-Hard.
- **Why for us:** Different problems need different reasoning approaches. Infrastructure debugging ≠ career planning ≠ research. Self-Discover picks the right approach per-task.
- **Integration:** Add a "reasoning structure selection" step to Hermes's task processing. ~20 lines of prompt engineering.
- **Effort:** LOW | **Impact:** MEDIUM

---

## Tier 2: Architectural Upgrades (Medium Effort, High Impact)

### 6. MenteDB — Purpose-Built Cognitive Memory Engine
- **Source:** [nambok/mentedb](https://github.com/nambok/mentedb) (98 stars, Rust core)
- **What:** 14-step cognitive pipeline: embedding, speculative cache, hybrid search, pain signals, episodic storage, fact extraction, contradiction detection, sentiment analysis. Entity-centric memory with graph edges. Five cognitive tiers (Working/Episodic/Semantic/Procedural/Archival). Delta-aware serving (90% token reduction). MCP server.
- **Why for us:** Our claudemem.db is a flat SQLite store. MenteDB gives us structured, tiered, entity-centric memory with contradiction detection — Hermes would stop contradicting itself.
- **Integration:** `docker run -p 6677:6677 ghcr.io/nambok/mentedb:latest`. Replace or augment claudemem. MCP server means it integrates with our existing MCP gateway.
- **Effort:** MEDIUM | **Impact:** VERY HIGH

### 7. Immortal — Next-Gen Self-Healing Engine
- **Source:** [Nagendhra-web/Immortal](https://github.com/Nagendhra-web/Immortal) (23 stars, Go)
- **What:** Three healing modes: reactive (rule-based), predictive (anomaly detection), and agentic (ReAct Plan>Act>Observe>Re-plan for novel failures). Digital twin simulation before acting. Causal inference (PCMCI root-cause analysis). Auto-learn from successful heals. Single Go binary, zero dependencies.
- **Why for us:** Our autonomous_fixer.py is a Python script with basic gene selection. Immortal is a purpose-built self-healing engine with causal reasoning and simulation. Would be a major upgrade.
- **Integration:** Single binary. Could replace or augment autonomous_fixer.py. The auto-learn from successful heals directly improves our Gene Engine.
- **Effort:** MEDIUM | **Impact:** VERY HIGH

### 8. Graphiti — Temporal Knowledge Graph
- **Source:** [getzep/graphiti](https://github.com/getzep/graphiti) (4.7K stars)
- **What:** Every fact has `valid_at`/`invalid_at` timestamps. Entities evolve with updated summaries. Hybrid retrieval (semantic + keyword + graph traversal). Incremental updates. MCP server available.
- **Why for us:** Our Capsule outcomes are flat JSONL. A temporal knowledge graph would let Hermes reason about how the homelab changes over time — "paper-agent has been failing every 30min for 3 days" vs "paper-agent failed once last week."
- **Integration:** Python, self-hosted. Feed Capsule outcomes + health dashboard data into Graphiti. Query via MCP.
- **Effort:** MEDIUM | **Impact:** HIGH

### 9. Voyager Skill Library Pattern — Composable Fix Skills
- **Source:** [MineDojo/Voyager](https://github.com/MineDojo/Voyager) (7K stars, NVIDIA)
- **What:** Agent writes its own executable skills, stores them in an embedding-indexed library, retrieves and composes them for new tasks. Skills build on each other (3.3x capability compounding).
- **Why for us:** Our Gene Engine has 6 strategy templates but they're static. Voyager's pattern would let Hermes write new fix strategies as executable code, store them, and compose them for novel situations.
- **Integration:** Add a `skill_library/` directory. When autonomous_fixer succeeds with a novel approach, extract it as a reusable skill. Index with embeddings for retrieval.
- **Effort:** MEDIUM | **Impact:** HIGH

### 10. Hermes Self-Evolution — Evolve Our Own Skills
- **Source:** [NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) (4.1K stars)
- **What:** Uses DSPy + GEPA to evolve the agent's own skills, tool descriptions, system prompts, and code. Constraint gates (test suite, size limits, semantic preservation). PR review for all changes.
- **Why for us:** This is the endgame — Hermes improving its own skill files and prompts. The constraint gates prevent drift. The PR review means changes are auditable.
- **Integration:** Run as a weekly cron job. DSPy optimizes skill files against test cases. Changes go through git diff review.
- **Effort:** MEDIUM-HIGH | **Impact:** VERY HIGH

---

## Tier 3: Advanced Capabilities (Higher Effort, Transformative)

### 11. BabyAGI Task Queue — Autonomous Work Queue
- **Source:** [yoheinakajima/babyagi](https://github.com/yoheinakajima/babyagi) (22.3K stars)
- **What:** Simple but powerful: pull first task → execute via LLM+tools → store results in vector DB → generate new tasks → reprioritize. The agent creates its own work queue.
- **Why for us:** Our autonomous_work_session.py sends Hermes a prompt 3× daily, but the tasks are pre-defined. BabyAGI would let Hermes generate its own follow-up tasks based on what it discovers.
- **Integration:** Add a `task_queue.json` that persists between sessions. Each work session can add new tasks. Priority scoring based on urgency + impact.
- **Effort:** MEDIUM | **Impact:** HIGH

### 12. ACE — Evolving Playbook Context
- **Source:** [arxiv.org/abs/2510.04618](https://arxiv.org/abs/2510.04618)
- **What:** Treats context as an evolving playbook. Three components: Generator produces candidate updates, Reflector evaluates quality using execution feedback, Curator merges approved updates. Prevents context collapse. +10.6% on agent benchmarks.
- **Why for us:** Our SOUL.md and skill files are static. ACE would let Hermes incrementally update its own playbook based on what works, without losing core behaviors.
- **Integration:** Add a `playbook_updates/` directory. After each significant task, generate candidate updates. Review and merge weekly.
- **Effort:** MEDIUM | **Impact:** HIGH

### 13. SAHOO — Safeguarded Recursive Self-Improvement
- **Source:** [arxiv.org/abs/2603.06333](https://arxiv.org/abs/2603.06333)
- **What:** Goal Drift Index (GDI) monitors alignment during self-improvement. Constraint preservation + regression-risk quantification. +18.3% code, +16.8% reasoning.
- **Why for us:** If we implement self-evolution (#10), we need safety guardrails. GDI would detect when Hermes's self-modifications drift from intended behavior.
- **Integration:** Add GDI monitoring to the self-evolution pipeline. Run regression tests after each self-modification.
- **Effort:** MEDIUM | **Impact:** SAFETY CRITICAL

### 14. AI Scientist Pattern — Autonomous Research
- **Source:** [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist) (14K stars)
- **What:** Full autonomous research loop: ideation → experiment code → execution → analysis → report writing → peer review. Agent decides what to research and when to stop.
- **Why for us:** Could automate homelab research — "find better Docker healthcheck patterns," "research optimal Kopia retention policies," "evaluate new monitoring tools."
- **Integration:** Run as a weekly cron. Hermes picks a research question from pending items, runs experiments on the homelab, writes a report.
- **Effort:** HIGH | **Impact:** HIGH (long-term)

### 15. LangGraph — Durable Workflow Orchestration
- **Source:** [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) (35K stars)
- **What:** Graph-based orchestration with cycles, checkpointing, human-in-the-loop, and durable execution. Nodes = functions/LLMs, Edges = conditional transitions.
- **Why for us:** Our cron jobs are independent scripts. LangGraph would let us build complex multi-step workflows with state persistence, retry logic, and conditional branching.
- **Integration:** Python library. Model complex workflows (e.g., "full homelab audit" → "identify issues" → "prioritize" → "fix" → "verify" → "document").
- **Effort:** MEDIUM-HIGH | **Impact:** HIGH

---

## What We Already Have (No Duplicates)

| Our Component | Equivalent Research Project | Status |
|---|---|---|
| autonomous_fixer.py | Immortal, ARGOS | Working but basic — upgrade recommended |
| Gene Engine + Capsules | Voyager skill library, ExpeL | Working — could add reflexion layer |
| autonomous_work_session.py | BabyAGI, AI Scientist | Working — could add task queue |
| claudemem.db | MenteDB, Mem0, Graphiti | Basic — major upgrade available |
| meta-learning skill | DSPy, GEPA, OPRO | Basic — auto-optimization available |
| self-heal skill | Immortal, CRITIC | Basic — tool-grounded verification missing |
| conversation_processor.py | LangMem, Hindsight | Working — could add background extraction |
| health_dashboard.py | — | Unique to our setup |
| short_circuit.py | — | Unique to our setup |

---

## Recommended Implementation Order

1. **Week 1:** Reflexion buffer for autonomous_fixer (stops repeating failures)
2. **Week 1:** CRITIC-style verification (stops hallucinating service states)
3. **Week 2:** Promptfoo setup (validate all prompt changes going forward)
4. **Week 2:** Self-Discover reasoning selection (better task handling)
5. **Week 3:** MenteDB deployment (upgrade memory from flat SQLite to cognitive engine)
6. **Week 3:** BabyAGI task queue (autonomous work generation)
7. **Week 4:** DSPy + GEPA prompt optimization (auto-improve our prompts)
8. **Week 4:** Graphiti temporal knowledge graph (reason about changes over time)
9. **Week 5:** Immortal integration (upgrade self-healing)
10. **Week 5:** Voyager skill library pattern (composable fix strategies)
11. **Week 6:** Hermes self-evolution with SAHOO guardrails (the endgame)

---

## Key Architectural Patterns Across All Projects

1. **ReAct loops** — Plan > Act > Observe > Re-plan (universal)
2. **Verbal reinforcement** — Reflect on failures in NL, feed back (Reflexion, Self-Refine)
3. **Tiered memory** — Working/Episodic/Semantic/Procedural/Archival layers
4. **Skill libraries** — Executable, composable, embedding-indexed capabilities
5. **Evolutionary prompt optimization** — Generate variants, evaluate, keep best
6. **Tool-grounded verification** — Don't trust LLM claims, verify with tools
7. **Temporal knowledge graphs** — Facts with validity windows, entity evolution
8. **Self-generated curriculum** — Agent proposes its own next task
9. **Alignment guardrails** — Monitor drift during self-improvement
10. **Delta-aware context** — Only send what changed since last turn
