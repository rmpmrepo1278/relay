#!/usr/bin/env python3
"""
unified_memory_mcp.py — Single MCP server exposing ALL Hermes memory stores.
Consolidates: claudemem, temporal_kg, shared_facts, state, kanban, hermes_mem, reflexion, collab
All tools: opencode, Claude Code, Hermes connect to THIS single MCP.
"""
from __future__ import annotations
import json, sqlite3, asyncio, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── Paths ──────────────────────────────────────────────────────────────
H = Path.home() / ".hermes"
DB_CLAUDEMEM = H / "claudemem.db"
DB_TEMPORAL = H / "temporal_kg.db"
DB_SHARED_FACTS = H / "shared_facts.db"
DB_STATE = H / "state.db"
DB_KANBAN = H / "kanban.db"
DB_HERMES_MEM = H / "state" / "hermes_memory.db"
DB_REFLEXION = H / "reflexion_memory.jsonl"
COLLAB_MEMORY_DIR = H / "collaborator-memory" / "memory"

# ── Helpers ────────────────────────────────────────────────────────────
def exec_sql(db: Path, sql: str, params: tuple = ()) -> list[dict]:
    if not db.exists():
        return [{"error": f"DB not found: {db}"}]
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return [{"error": str(e)}]

# ── Tool Schemas ──────────────────────────────────────────────────────
TOOLS = [
    Tool(
        name="memory_query",
        description="Query any memory store with SQL. Stores: claudemem, temporal, facts, state, kanban, hermes_mem, reflexion, collab, all",
        inputSchema={
            "type": "object",
            "properties": {
                "store": {"type": "string", "enum": ["claudemem", "temporal", "facts", "state", "kanban", "hermes_mem", "reflexion", "collab", "all"], "default": "all"},
                "query": {"type": "string", "description": "SQL query or search term"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["store", "query"]
        }
    ),
    Tool(
        name="memory_store",
        description="Store a fact/observation in a specific memory store",
        inputSchema={
            "type": "object",
            "properties": {
                "store": {"type": "string", "enum": ["claudemem", "temporal", "facts", "state", "kanban", "hermes_mem", "collab"]},
                "data": {"type": "object", "description": "Key-value data to store (schema depends on store)"}
            },
            "required": ["store", "data"]
        }
    ),
    Tool(
        name="memory_recall",
        description="Semantic recall - find relevant info across stores by topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to search for"},
                "stores": {"type": "array", "items": {"type": "string"}, "default": ["all"]},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["topic"]
        }
    ),
    Tool(
        name="memory_stats",
        description="Get statistics about all memory stores",
        inputSchema={"type": "object", "properties": {}}
    ),
]

# ── Server Setup ───────────────────────────────────────────────────────
server = Server("unified-memory")

async def handle_query(args: dict) -> list[TextContent]:
    store = args.get("store", "all")
    query = args.get("query", "")
    limit = args.get("limit", 10)
    results = {}

    if store in ("claudemem", "all"):
        if query:
            results["claudemem"] = exec_sql(
                DB_CLAUDEMEM,
                "SELECT id, content, importance, category, timestamp FROM observations_fts WHERE observations_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit)
            )
        else:
            results["claudemem"] = exec_sql(DB_CLAUDEMEM, "SELECT COUNT(*) as count FROM observations")

    if store in ("temporal", "all"):
        if query:
            results["temporal"] = exec_sql(
                DB_TEMPORAL,
                """SELECT f.id, e.name as entity, f.predicate, f.object, f.valid_at, f.confidence
                   FROM facts f JOIN entities e ON f.subject_id = e.id
                   WHERE e.name LIKE ? OR f.predicate LIKE ? OR f.object LIKE ?
                   LIMIT ?""",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit)
            )
        else:
            results["temporal"] = {
                "facts": exec_sql(DB_TEMPORAL, "SELECT COUNT(*) as count FROM facts"),
                "entities": exec_sql(DB_TEMPORAL, "SELECT COUNT(*) as count FROM entities")
            }

    if store in ("facts", "all"):
        results["shared_facts"] = exec_sql(
            DB_SHARED_FACTS,
            "SELECT id, fact, category, confidence, source, created_at FROM shared_facts_fts WHERE shared_facts_fts MATCH ? LIMIT ?",
            (query, limit)
        )

    if store in ("state", "all"):
        results["state"] = {
            "sessions": exec_sql(DB_STATE, "SELECT id, source, model, started_at, message_count FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)),
            "goals": exec_sql(DB_STATE, "SELECT id, title, status, priority, progress_pct FROM goals WHERE title LIKE ? LIMIT ?", (f"%{query}%", limit)),
            "milestones": exec_sql(DB_STATE, "SELECT id, goal_id, title, status FROM milestones WHERE title LIKE ? LIMIT ?", (f"%{query}%", limit))
        }

    if store in ("kanban", "all"):
        results["kanban"] = exec_sql(
            DB_KANBAN,
            "SELECT id, title, status, priority, assignee, workspace_kind FROM tasks WHERE title LIKE ? LIMIT ?",
            (f"%{query}%", limit)
        )

    if store in ("hermes_mem", "all"):
        results["hermes_mem"] = exec_sql(
            DB_HERMES_MEM,
            "SELECT gene, action, outcome, count, last_seen FROM actions WHERE gene LIKE ? OR action LIKE ? ORDER BY count DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        )

    if store in ("reflexion", "all"):
        if Path(DB_REFLEXION).exists():
            lines = Path(DB_REFLEXION).read_text().splitlines()
            matches = [l for l in lines if query.lower() in l.lower()][:limit]
            results["reflexion"] = [json.loads(m) for m in matches if m.strip()]
        else:
            results["reflexion"] = []

    if store in ("collab", "all"):
        collab_dir = Path(COLLAB_MEMORY_DIR)
        if collab_dir.exists():
            files = list(collab_dir.glob("*.md"))
            matches = []
            for f in files:
                content = f.read_text()
                if query.lower() in content.lower():
                    matches.append({"file": f.name, "excerpt": content[:200]})
            results["collab"] = matches[:limit]

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]

async def handle_store(args: dict) -> list[TextContent]:
    store = args["store"]
    data = args["data"]
    ts = datetime.now(timezone.utc).isoformat()

    if store == "claudemem":
        conn = sqlite3.connect(str(DB_CLAUDEMEM))
        conn.execute(
            "INSERT INTO observations (id, session_id, timestamp, source, content, importance, category) VALUES (?,?,?,?,?,?,?)",
            (data.get("id", f"obs_{int(datetime.now().timestamp()*1000)}"),
             data.get("session_id", "mcp"), ts, data.get("source", "mcp"),
             data["content"], data.get("importance", 0.5), data.get("category", "context"))
        )
        conn.commit()
        conn.close()
        return [TextContent(type="text", text="Stored in claudemem")]

    elif store == "facts":
        conn = sqlite3.connect(str(DB_SHARED_FACTS))
        conn.execute(
            "INSERT INTO shared_facts (fact, category, confidence, source) VALUES (?,?,?,?)",
            (data["fact"], data.get("category", "context"), data.get("confidence", 0.8), data.get("source", "mcp"))
        )
        conn.commit()
        conn.close()
        return [TextContent(type="text", text="Stored in shared_facts")]

    elif store == "temporal":
        import tempfile
        capsule = {
            "type": "manual",
            "title": data.get("title", "mcp_entry"),
            "source": "unified_memory_mcp",
            "entities": data.get("entities", []),
            "facts": data.get("facts", []),
            "date": ts[:10],
            "ingested_at": ts
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(capsule, f)
            tmp = f.name
        import subprocess
        subprocess.run(f"python3 {Path.home() / '.hermes' / 'scripts' / 'temporal_kg.py'} ingest-capsule --file {tmp}", shell=True)
        os.unlink(tmp)
        return [TextContent(type="text", text="Ingested into temporal KG")]

    elif store == "state":
        conn = sqlite3.connect(str(DB_STATE))
        conn.execute(
            "INSERT INTO goals (id, title, description, category, status, priority, target_date) VALUES (?,?,?,?,?,?,?)",
            (data.get("id", f"goal_{int(datetime.now().timestamp())}"),
             data["title"], data.get("description", ""), data.get("category", "project"),
             data.get("status", "active"), data.get("priority", "high"), data.get("target_date"))
        )
        conn.commit()
        conn.close()
        return [TextContent(type="text", text="Stored goal in state.db")]

    elif store == "kanban":
        conn = sqlite3.connect(str(DB_KANBAN))
        conn.execute(
            """INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, workspace_kind)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (data.get("id", f"task_{int(datetime.now().timestamp())}"),
             data["title"], data.get("body", ""), data.get("assignee", "hermes"),
             data.get("status", "pending"), data.get("priority", 0), "mcp", int(datetime.now().timestamp()), "scratch")
        )
        conn.commit()
        conn.close()
        return [TextContent(type="text", text="Stored task in kanban")]

    elif store == "collab":
        collab_dir = Path(COLLAB_MEMORY_DIR)
        collab_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{data.get('title', 'note')}_{int(datetime.now().timestamp())}.md"
        (collab_dir / fname).write_text(data["content"])
        return [TextContent(type="text", text=f"Stored in collaborator memory: {fname}")]

    return [TextContent(type="text", text=f"Unknown store: {store}")]

async def handle_recall(args: dict) -> list[TextContent]:
    topic = args["topic"]
    stores = args.get("stores", ["all"])
    limit = args.get("limit", 10)

    all_results = {}
    for s in (stores if "all" not in stores else ["claudemem", "temporal", "facts", "state", "kanban", "hermes_mem", "reflexion", "collab"]):
        res = await handle_query({"store": s, "query": topic, "limit": limit})
        all_results[s] = json.loads(res[0].text) if res[0].text else {}

    return [TextContent(type="text", text=json.dumps(all_results, indent=2, default=str))]

async def handle_stats(args: dict) -> list[TextContent]:
    stats = {}
    stats["claudemem"] = {
        "obs": exec_sql(DB_CLAUDEMEM, "SELECT COUNT(*) as count FROM observations"),
        "sessions": exec_sql(DB_CLAUDEMEM, "SELECT COUNT(DISTINCT session_id) as count FROM observations")
    }
    stats["temporal"] = {
        "facts": exec_sql(DB_TEMPORAL, "SELECT COUNT(*) as count FROM facts"),
        "entities": exec_sql(DB_TEMPORAL, "SELECT COUNT(*) as count FROM entities")
    }
    stats["shared_facts"] = exec_sql(DB_SHARED_FACTS, "SELECT COUNT(*) as count FROM shared_facts")
    stats["state"] = {
        "sessions": exec_sql(DB_STATE, "SELECT COUNT(*) as count FROM sessions"),
        "goals": exec_sql(DB_STATE, "SELECT COUNT(*) as count FROM goals")
    }
    stats["kanban"] = exec_sql(DB_KANBAN, "SELECT COUNT(*) as tasks FROM tasks")
    stats["hermes_mem"] = exec_sql(DB_HERMES_MEM, "SELECT COUNT(*) as actions FROM actions")
    stats["reflexion"] = [{"lines": len(Path(DB_REFLEXION).read_text().splitlines())}] if Path(DB_REFLEXION).exists() else [{"lines": 0}]
    stats["collab"] = [{"files": len(list(Path(COLLAB_MEMORY_DIR).glob("*.md")))}] if Path(COLLAB_MEMORY_DIR).exists() else [{"files": 0}]
    return [TextContent(type="text", text=json.dumps(stats, indent=2, default=str))]

@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "memory_query":
        return await handle_query(arguments)
    elif name == "memory_store":
        return await handle_store(arguments)
    elif name == "memory_recall":
        return await handle_recall(arguments)
    elif name == "memory_stats":
        return await handle_stats(arguments)
    raise ValueError(f"Unknown tool: {name}")

# ── Entrypoint ─────────────────────────────────────────────────────────
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
