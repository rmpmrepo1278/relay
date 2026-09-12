import sqlite3
import logging
import threading
import time
import requests
import json
import hashlib
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Constants ---
DB_PATH = "/home/rohit/.hermes/claudemem.db"
COMPRESSION_THRESHOLD = 500  # Observations
LLM_PROXY_URL = "http://localhost:8080/v1/chat/completions"

# --- Globals ---
_db_conn = None
_db_lock = threading.Lock()

# --- DB Setup ---

def get_db_connection():
    """Establishes and returns a thread-safe DB connection."""
    global _db_conn
    if _db_conn is None:
        try:
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _db_conn.row_factory = sqlite3.Row
            logger.info("SimpleMem: Connected to ClaudeMem database.")
            setup_database(_db_conn)
        except sqlite3.Error as e:
            logger.error(f"SimpleMem: Database connection failed: {e}")
            return None
    return _db_conn

def setup_database(conn):
    """Creates the compressed_memories table if it doesn't exist."""
    with _db_lock:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compressed_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_observation_ids TEXT NOT NULL,
                    compressed_text TEXT NOT NULL,
                    embedding_hash TEXT,
                    created_at REAL NOT NULL
                )
            """)
            # For now, we won't add FTS to compressed memories to keep it simple.
            # A unified search will query both tables.
            conn.commit()
            logger.info("SimpleMem: `compressed_memories` table verified.")
        except sqlite3.Error as e:
            logger.error(f"SimpleMem: Database setup failed: {e}")

# --- Core Logic ---

def get_uncompressed_observations(limit=1000):
    """Fetches uncompressed observations from the claudemem DB."""
    conn = get_db_connection()
    if not conn:
        return []
    with _db_lock:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, content FROM observations WHERE compressed = 0 ORDER BY timestamp ASC LIMIT ?",
            (limit,)
        )
        return cursor.fetchall()

def compress_observations(observations):
    """Summarizes a batch of observations using the LLM proxy."""
    if not observations:
        return None, None

    # Create a digest for the LLM
    digest = "\n".join([f"- {obs['content']}" for obs in observations])
    prompt = (
        "You are a memory compression agent. Summarize the following observations "
        "into a single, dense, atomic memory. Preserve all key facts, decisions, "
        "and entities. Be concise and factual.\n\n"
        f"Observations to compress:\n{digest}"
    )

    try:
        response = requests.post(
            LLM_PROXY_URL,
            json={
                "model": "haiku-4.5", # Uses free-tier models first
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.2,
            },
            timeout=30,
        )
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"]

        # We'll skip embedding for now to keep it simple, as requested.
        embedding_hash = hashlib.sha256(summary.encode()).hexdigest()

        return summary.strip(), embedding_hash
    except requests.RequestException as e:
        logger.error(f"SimpleMem: LLM compression request failed: {e}")
        return None, None

def save_compressed_memory(summary, embedding_hash, source_ids):
    """Saves a new compressed memory and marks original observations."""
    conn = get_db_connection()
    if not conn:
        return
    with _db_lock:
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO compressed_memories
                   (source_observation_ids, compressed_text, embedding_hash, created_at)
                   VALUES (?, ?, ?, ?)""",
                (json.dumps(source_ids), summary, embedding_hash, time.time())
            )
            # Mark original observations as compressed
            placeholders = ",".join("?" * len(source_ids))
            cursor.execute(
                f"UPDATE observations SET compressed = 1 WHERE id IN ({placeholders})",
                source_ids
            )
            conn.commit()
            logger.info(f"SimpleMem: Compressed {len(source_ids)} observations into one memory.")
        except sqlite3.Error as e:
            logger.error(f"SimpleMem: Failed to save compressed memory: {e}")


def trigger_compression_if_needed():
    """Checks observation count and runs compression if threshold is met."""
    conn = get_db_connection()
    if not conn: return
    with _db_lock:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM observations WHERE compressed = 0")
        count = cursor.fetchone()[0]

    if count > COMPRESSION_THRESHOLD:
        logger.info(f"SimpleMem: Observation count ({count}) exceeds threshold ({COMPRESSION_THRESHOLD}). Compressing.")
        memory_compress_now()


# --- Tools ---

def memory_compress_now():
    """Manually triggers the memory compression process."""
    observations = get_uncompressed_observations()
    if not observations:
        return "No uncompressed observations to process."

    # Process in batches of 100
    batch_size = 100
    compressed_count = 0
    for i in range(0, len(observations), batch_size):
        batch = observations[i:i + batch_size]
        source_ids = [obs['id'] for obs in batch]

        summary, embedding_hash = compress_observations(batch)
        if summary:
            save_compressed_memory(summary, embedding_hash, source_ids)
            compressed_count += len(batch)

    return f"Successfully compressed {compressed_count} observations."


def memory_search(query: str, limit: int = 10):
    """Searches both raw and compressed memories for a query."""
    conn = get_db_connection()
    if not conn:
        return "Database connection not available."

    results = []
    with _db_lock:
        try:
            # Search raw observations via FTS5
            cursor = conn.cursor()
            cursor.execute(
                """SELECT content, timestamp FROM observations_fts
                   JOIN observations ON observations_fts.rowid = observations.rowid
                   WHERE observations_fts MATCH ? AND observations.compressed = 0
                   ORDER BY rank LIMIT ?""",
                (query, limit)
            )
            for row in cursor.fetchall():
                results.append(f"[RAW - {time.strftime('%Y-%m-%d', time.localtime(row['timestamp']))}] {row['content']}")

            # Search compressed memories via LIKE
            cursor.execute(
                """SELECT compressed_text, created_at FROM compressed_memories
                   WHERE compressed_text LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (f"%{query}%", limit)
            )
            for row in cursor.fetchall():
                 results.append(f"[COMPRESSED - {time.strftime('%Y-%m-%d', time.localtime(row['created_at']))}] {row['compressed_text']}")

        except sqlite3.Error as e:
            return f"Search failed: {e}"

    return "\n\n".join(results) if results else "No results found."


def memory_stats():
    """Returns statistics about the memory stores."""
    conn = get_db_connection()
    if not conn:
        return "Database connection not available."

    with _db_lock:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM observations WHERE compressed = 0")
        uncompressed_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM observations WHERE compressed = 1")
        raw_compressed_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM compressed_memories")
        compressed_mem_count = cursor.fetchone()[0]

    return (
        f"Uncompressed Observations: {uncompressed_count}\n"
        f"Raw Compressed Observations: {raw_compressed_count}\n"
        f"Compressed Memory Units: {compressed_mem_count}"
    )

# --- Plugin Registration ---

def register(ctx):
    """Registers the SimpleMem plugin."""

    # Initialize DB on start
    get_db_connection()

    ctx.register_tool(
        name="memory_search",
        toolset="simplemem",
        schema={
            "name": "memory_search",
            "description": "Unified search across raw and compressed long-term memory.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]},
        },
        handler=memory_search,
        description="Unified search across raw and compressed long-term memory."
    )
    ctx.register_tool(
        name="memory_compress_now",
        toolset="simplemem",
        schema={
            "name": "memory_compress_now",
            "description": "Manually trigger a compression cycle for long-term memory.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=memory_compress_now,
        description="Manually trigger a compression cycle for long-term memory."
    )
    ctx.register_tool(
        name="memory_stats",
        toolset="simplemem",
        schema={
            "name": "memory_stats",
            "description": "Get statistics about the state of long-term memory.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=memory_stats,
        description="Get statistics about the state of long-term memory."
    )

    # Hook to check for compression on session start
    ctx.register_hook("on_session_start", trigger_compression_if_needed)

    logger.info("SimpleMem plugin registered.")
