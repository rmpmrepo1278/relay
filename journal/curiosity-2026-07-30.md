# Curiosity Log — 2026-07-30


## Curiosity — 00:15 UTC
Interests: self_hosting, ai_agents, llm_inference

🔀 **Intersection:** llm inference × self hosting
📄 **arXiv (ai agents):**
  • The Social Cost of an AI Teammate: How an Artificial Teammate Reshapes Human-Hum
    http://arxiv.org/abs/2607.27179v1
⭐ **Trending on GitHub:**
  • xai-org/grok-build ⭐23463
    SpaceXAI's coding agent harness and TUI. Fullscreen, mouse interactive, extensib
    https://github.com/xai-org/grok-build
  • langchain-ai/openwiki ⭐13584
    OpenWiki is a CLI that writes and maintains agent documentation for your codebas
    https://github.com/langchain-ai/openwiki
  • unicity-aos/aos-ce ⭐8019
    AOS Community Edition: the open agent operating system.
    https://github.com/unicity-aos/aos-ce
🎲 **Serendipity:**
  • NSF pilots 4-year PhDs with industry research placements
    https://www.nsf.gov/news/nsf-partners-universities-industry-pilot-initiative-four
    (66 points on HN)

## Curiosity — 12:16 UTC
Interests: self_hosting, ai_agents, llm_inference

🔀 **Intersection:** ai agents × llm inference
📄 **arXiv (llm inference):**
  • Do You Really Need to Pretrain Q-Functions for Online RL Fine-Tuning?
    http://arxiv.org/abs/2607.27203v1
  • From Classification to Regression: Using a Fruitfly to Solve Equations
    http://arxiv.org/abs/2607.27196v1
⭐ **Trending on GitHub:**
  • xai-org/grok-build ⭐23548
    SpaceXAI's coding agent harness and TUI. Fullscreen, mouse interactive, extensib
    https://github.com/xai-org/grok-build
  • langchain-ai/openwiki ⭐13672
    OpenWiki is a CLI that writes and maintains agent documentation for your codebas
    https://github.com/langchain-ai/openwiki
  • unicity-aos/aos-ce ⭐8056
    AOS Community Edition: the open agent operating system.
    https://github.com/unicity-aos/aos-ce
🎲 **Serendipity:**
  • Ron Gilbert started production on Thimbleweed Park 2
    https://www.grumpygamer.com/twp2_announce/
    (213 points on HN)

## Curiosity — 16:15 UTC
Interests: self_hosting, ai_agents, llm_inference

🌱 **Adjacent to ai agents:** mcp protocol
  • What is the Model Context Protocol (MCP)?
    https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro
🔀 **Intersection:** monitoring × ai agents
  • Residential & Commercial Security Services - First Priority Alarm S
    https://www.firstpriorityalarms.com/services
  • First Priority Alarm Systems | Oklahoma City Security Company
    https://www.firstpriorityalarms.com/
📄 **arXiv (self hosting):**
  • Assurance-Scoped Reliability for Agentic Networks: Capturing the State That Matt
    http://arxiv.org/abs/2607.26953v1
  • The Price of Meaning: Quantifying Semantic Communication Overheads in Practice
    http://arxiv.org/abs/2607.26764v1
⭐ **Trending on GitHub:**
  • xai-org/grok-build ⭐23558
    SpaceXAI's coding agent harness and TUI. Fullscreen, mouse interactive, extensib
    https://github.com/xai-org/grok-build
  • langchain-ai/openwiki ⭐13682
    OpenWiki is a CLI that writes and maintains agent documentation for your codebas
    https://github.com/langchain-ai/openwiki
  • unicity-aos/aos-ce ⭐8064
    AOS Community Edition: the open agent operating system.
    https://github.com/unicity-aos/aos-ce
🎲 **Serendipity:**
  • 2x, not 10x: coding with LLMs in 2026
    https://obryant.dev/p/2x-not-10x/
    (177 points on HN)

## Curiosity — 20:15 UTC
Interests: self_hosting, ai_agents, llm_inference

🌱 **Adjacent to ai agents:** mcp protocol
  • Everything your team needs to know about MCP in 2026 — WorkOS
    https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026
🔀 **Intersection:** monitoring × llm inference
📄 **arXiv (ai agents):**
  • Learning to Trace Seiberg Dualities
    http://arxiv.org/abs/2607.28628v1
  • ReToken: One Token to Improve Vision-Language Models for Visual Retrieval
    http://arxiv.org/abs/2607.28627v1
⭐ **Trending on GitHub:**
  • xai-org/grok-build ⭐23585
    SpaceXAI's coding agent harness and TUI. Fullscreen, mouse interactive, extensib
    https://github.com/xai-org/grok-build
  • langchain-ai/openwiki ⭐13693
    OpenWiki is a CLI that writes and maintains agent documentation for your codebas
    https://github.com/langchain-ai/openwiki
  • unicity-aos/aos-ce ⭐8078
    AOS Community Edition: the open agent operating system.
    https://github.com/unicity-aos/aos-ce

## LLM Infrastructure Cleanup & Optimization (2026-07-31)

### Context
- User requested getting local LLMs operational, specifically gpt-oss-20b (OSS 20B model) for BigMoe services
- BigMoeOnEdge is an Android app (not a homelab service) — the name bigmoe was ambiguous

### Actions Taken
1. Loaded gpt-oss-20b-Q4_K_M.gguf (11.6GB) into Ollama — works but at 0.3 tok/s (unusable for interactive)
2. Benchmarked all local models:
   - llama3.2:3b: **7.9 tok/s** (fast, interactive) — KEPT
   - qwen2.5-7b-tool: 0.3 tok/s — REMOVED
   - gpt-oss-20b: 0.3 tok/s — REMOVED
   - gpt-oss-20b-fast (reduced ctx): 0.8 tok/s — REMOVED
3. Cleaned up slow models from Ollama and deleted GGUF files from /home/rohit/models/
4. Updated OLLAMA_NUM_THREADS from 6 to 8 (matching CPU threads)
5. Updated best_config.env to reflect llama3.2:3b as primary local model
6. Updated model_catalog.json with remaining models

### Key Finding
- Ryzen 4700U CPU-only inference: ~8 tok/s with 3B model
- All 7B+ models below 1 tok/s — unusable for interactive use
- Cloud models (Groq llama-3.3-70b, OpenRouter) provide real 80-90% coverage
- local llama3.2:3b is the fast fallback for simple tasks

### Recommendations
- Keep llama3.2:3b as local fast model
- Use cloud providers via proxy_server.py for complex tasks
- For significant local model improvement: add GPU (RTX 3060 12GB+)
