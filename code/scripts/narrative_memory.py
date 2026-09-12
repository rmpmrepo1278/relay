#!/usr/bin/env python3
"""
narrative_memory.py — Hermes' episodic memory layer.

Persists every insight + action to a lightweight TSV (fast, no deps) and
provides TF-IDF vector retrieval for cross-cycle recall — solving the
"context loss between 30-min daemon cycles" and the "50 insights unacted on" gap.

Key functions:
  - store_episode(insight_or_action): append to memory
  - retrieve_similar(query, k=5): find relevant past episodes
  - summarise_periods(): hierarchical compression for long-term retention
  - decay_old_signals(): move stale signals to compressed archive

Uses scikit-learn TfidfVectorizer if available (CPU-only OK), else falls back
to a pure-Python unigram overlap ranker.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
DATA_DIR = HERMES_HOME / "data"
STATE_DIR = HERMES_HOME / "state"
LOG_DIR = HERMES_HOME / "logs"
EP_STORE = DATA_DIR / "episodic_memory.tsv"
EMBED_CACHE = DATA_DIR / "embedding_cache.json"
COMPRESS_STORE = DATA_DIR / "memory_compressed.jsonl"
LOG_DIR.mkdir(parents=True, exist_ok=True)
EP_STORE.parent.mkdir(parents=True, exist_ok=True)

_MAX_EPISODES = 5000  # cap before decay kicks in
_DECAY_DAYS = 7
_RETRIEVE_K = 10


def _log(msg: str):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_DIR / "narrative_memory.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower())]


def _try_vectorizer():
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        return True, TfidfVectorizer
    except ImportError:
        return False, None


def store_episode(event: dict) -> None:
    """
    Append an episode to the episodic memory TSV.
    event fields: type (insight/action/self_reflection), content, ts, metadata.
    """
    if not isinstance(event, dict) or "content" not in event:
        return

    ts = event.get("ts", datetime.now(timezone.utc).isoformat())
    etype = event.get("type", "generic")
    content = event.get("content", "")
    meta = json.dumps(event.get("metadata", {}), default=str)

    row = f"{ts}\t{etype}\t{content}\t{meta}\n"
    with open(EP_STORE, "a") as f:
        f.write(row)

    # Decay check (stat-based O(1) instead of O(n) line count)
    if EP_STORE.stat().st_size > 0:
        # ~200 bytes/episode avg; 5000 episodes ~= 1MB. Decay at ~1.1MB.
        if EP_STORE.stat().st_size > 1_100_000:
            _decay_old_episodes()

    _log(f"Stored episode: {etype} | {content[:80]}")


def _load_episodes() -> list[dict]:
    if not EP_STORE.exists():
        return []
    episodes = []
    with open(EP_STORE) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                episodes.append({
                    "ts": parts[0],
                    "type": parts[1],
                    "content": parts[2],
                    "metadata": json.loads(parts[3]) if len(parts) > 3 and parts[3] else {},
                })
    return episodes


def _ollama_embed(text: str) -> list[float] | None:
    """Get embedding from local Ollama nomic-embed-text model. Zero-cost, CPU-only."""
    try:
        import urllib.request
        payload = json.dumps({"model": "nomic-embed-text", "prompt": text}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except Exception:
        return None


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_similar(query: str, k: int = _RETRIEVE_K, types: list[str] | None = None) -> list[dict]:
    """
    Retrieve the top-k episodes most similar to the query text.
    Uses Ollama nomic-embed-text vector embeddings (CPU-only, zero-cost).
    Falls back to TF-IDF or unigram overlap if Ollama is unavailable.
    """
    episodes = _load_episodes()
    if types:
        episodes = [e for e in episodes if e["type"] in types]
    if not episodes:
        return []

    # Try Ollama embeddings first (cached)
    q_vec = _ollama_embed(query)
    if q_vec:
        ranked = []
        cache = {}
        if EMBED_CACHE.exists():
            try:
                cache = json.loads(EMBED_CACHE.read_text())
            except Exception:
                pass

        for ep in episodes:
            content_key = ep["content"][:120]
            ep_vec = cache.get(content_key)
            if ep_vec is None:
                ep_vec = _ollama_embed(ep["content"])
                if ep_vec:
                    cache[content_key] = ep_vec

            if ep_vec:
                score = _cosine_sim(q_vec, ep_vec)
                if score > 0.01:
                    ranked.append((score, ep))

        # Persist cache
        if cache:
            try:
                EMBED_CACHE.write_text(json.dumps(cache, default=str))
            except Exception:
                pass

        if ranked:
            ranked.sort(key=lambda x: x[0], reverse=True)
            return [e for s, e in ranked[:k]]

    # Fallback: TF-IDF
    corpus = [e["content"] for e in episodes]
    query_tokens = set(_tokenize(query))
    use_tfidf, Vectorizer = _try_vectorizer()
    if use_tfidf and len(corpus) > 5:
        try:
            vec = Vectorizer(stop_words="english", max_features=500)
            tfidf = vec.fit_transform(corpus)
            q_vec = vec.transform([query])
            scores = (tfidf @ q_vec.T).toarray().flatten()
            ranked = sorted(zip(scores, episodes), key=lambda x: x[0], reverse=True)
            return [e for s, e in ranked[:k] if s > 0]
        except Exception:
            pass

    # Last-resort fallback: unigram overlap
    ranked = []
    for ep in episodes:
        ep_tokens = set(_tokenize(ep["content"]))
        overlap = len(query_tokens & ep_tokens)
        score = overlap / max(len(query_tokens), 1) if query_tokens else 0
        if score > 0:
            ranked.append((score, ep))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [e for s, e in ranked[:k]]


def retrieve_recent(hours: int = 24, types: list[str] | None = None,
                    episodes: list[dict] | None = None) -> list[dict]:
    """
    Retrieve episodes from the last N hours.
    Optional episodes param avoids re-parsing the TSV when caller already has data.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    if episodes is None:
        episodes = _load_episodes()
    if types:
        episodes = [e for e in episodes if e["type"] in types]
    return [e for e in episodes if e["ts"] >= cutoff]


def _decay_old_episodes() -> None:
    """
    Move episodes older than _DECAY_DAYS into compressed archive,
    keeping only their vector summary for retrieval.
    """
    episodes = _load_episodes()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_DECAY_DAYS)).isoformat()

    keep = []
    archive = []
    for ep in episodes:
        if ep["ts"] < cutoff:
            archive.append(ep)
        else:
            keep.append(ep)

    if not archive:
        return

    # Summarize archived episodes into a single compressed entry
    summary = {
        "ts": cutoff,
        "type": "compressed_summary",
        "content": f"[Compressed] {len(archive)} episodes from prev {_DECAY_DAYS} days.",
        "metadata": {
            "type_counts": defaultdict(int),
            "sample_contents": [],
        },
    }

    type_counts = defaultdict(int)
    for ep in archive:
        type_counts[ep["type"]] += 1
        if len(summary["metadata"]["sample_contents"]) < 10:
            summary["metadata"]["sample_contents"].append(ep["content"][:120])
    summary["metadata"]["type_counts"] = dict(type_counts)

    with open(COMPRESS_STORE, "a") as f:
        f.write(json.dumps(summary, default=str) + "\n")

    # Rewrite the store with only recent episodes
    with open(EP_STORE, "w") as f:
        for ep in keep:
            row = f"{ep['ts']}\t{ep['type']}\t{ep['content']}\t{json.dumps(ep.get('metadata', {}), default=str)}\n"
            f.write(row)

    _log(f"Decayed {len(archive)} old episodes → compressed archive")


def compute_insight_action_gap(episodes: list[dict] | None = None) -> dict:
    """
    Measure the gap between insights generated and actions taken on them.
    Uses metadata linkage: actions tag the insight they're based on.
    """
    if episodes is None:
        episodes = _load_episodes()
    insights = [e for e in episodes if e["type"] == "insight"]
    actions = [e for e in episodes if e["type"] == "action"]

    acted_insight_ids = set()
    for a in actions:
        src = a["metadata"].get("source_insight_id")
        if src:
            acted_insight_ids.add(src)

    total = len(insights)
    acted = len(acted_insight_ids)
    gap = total - acted

    return {
        "total_insights": total,
        "acted_insights": acted,
        "gap": gap,
        "action_rate": round(acted / total, 3) if total else 1.0,
        "last_24h": {
            "insights": len(retrieve_recent(24, types=["insight"], episodes=episodes)),
            "actions": len(retrieve_recent(24, types=["action"], episodes=episodes)),
        },
    }


def mark_action_performed(content: str, source_insight_id: str | None = None,
                          outcome: str = "unknown") -> None:
    """
    Record that an action was performed, optionally linked to an insight.
    """
    store_episode({
        "type": "action",
        "content": content,
        "metadata": {
            "source_insight_id": source_insight_id,
            "outcome": outcome,
        },
    })


def top_themes(k: int = 5) -> list[tuple[str, int]]:
    """
    Return the top-k recurring content tokens across all episodes.
    Useful for agenda setting.
    """
    episodes = _load_episodes()
    token_counts: dict[str, int] = defaultdict(int)
    stop = {"the", "a", "an", "is", "was", "for", "to", "of", "and", "in", "on", "detected", "system"}

    for ep in episodes[-2000:]:
        for tok in _tokenize(ep["content"]):
            if len(tok) > 3 and tok not in stop:
                token_counts[tok] += 1

    return sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:k]


def suggest_gap_actions(episodes: list[dict] | None = None) -> list[dict]:
    """
    Find insights from the past 48h that never got an action linkage,
    and suggest a follow-up action for each.
    """
    recent = retrieve_recent(48, types=["insight"], episodes=episodes)
    acted = retrieve_recent(48, types=["action"], episodes=episodes)
    acted_contents = {a["content"].lower()[:60] for a in acted}

    suggestions = []
    for ins in recent:
        # Check if any action content references this insight
        ins_id = ins["metadata"].get("id") or ""
        ins_content_snippet = ins["content"].lower()[:50]
        already_acted = any(
            (ins_id and ins_id in (a["metadata"].get("source_insight_id") or ""))
            or ins_content_snippet in a["content"].lower()[:60]
            for a in acted
        )
        if not already_acted and ins.get("metadata", {}).get("action_suggested"):
            suggestions.append({
                "insight": ins,
                "suggested_action": _derive_action(ins),
                "confidence": 0.5,
            })

    return suggestions[:5]


def _derive_action(insight: dict) -> str:
    """Map an unacted insight to a concrete suggested action string."""
    suggestion = insight.get("metadata", {}).get("action_suggested", "")
    if not suggestion:
        suggestion = insight.get("action_suggested", "")

    mapping = {
        "investigate_and_fix": "Investigate and attempt self-heal on flagged issue",
        "run_maintenance_tasks": "Run scheduled maintenance tasks during quiet window",
        "send_morning_briefing": "Send morning briefing via Telegram",
        "surface_to_telegram": "Surface insight to Telegram",
        "prepare_fulfillment": "Prepare to fulfill deadline commitment",
        "fulfill_commitment": "Fulfill outstanding commitment immediately",
    }
    return mapping.get(suggestion, f"Follow up on: {insight['content'][:100]}")


def update_narratives() -> dict:
    """
    Called by mind_loop every 10th cycle.
    Consolidates recent episodes into narrative summaries and identifies
    recurring themes for goal-setting.
    """
    episodes = _load_episodes()
    if not episodes:
        return {"narratives": [], "themes": []}

    # Build narratives from recent actions grouped by domain
    recent = episodes[-200:] if len(episodes) > 200 else episodes
    narratives = []
    themes = top_themes(10)

    # Group by domain from metadata
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for ep in recent:
        domain = ep.get("metadata", {}).get("domain", "general")
        by_domain[domain].append(ep)

    for domain, eps in by_domain.items():
        if len(eps) < 3:
            continue
        latest = eps[-1]
        narratives.append({
            "domain": domain,
            "title": f"Ongoing: {domain} activity",
            "summary": f"{len(eps)} episodes in {domain} domain. Latest: {latest['content'][:100]}",
            "last_event": latest["ts"],
        })

    return {
        "narratives": narratives,
        "themes": [{"theme": t, "count": c} for t, c in themes],
        "episode_count": len(episodes),
        "recent_count": len(recent),
        # Write to temporal KG so facts/entities stay fresh
        "_tkg_updated": _update_tkg(narratives, themes),
    }


def _update_tkg(narratives: list[dict], themes: list[tuple[str, int]]) -> None:
    """Write consolidated narratives + top themes into temporal_kg.db.
    Called by update_narratives() every 10th cycle."""
    import sqlite3, hashlib
    from datetime import datetime, timezone
    tkg_path = HERMES_HOME / "temporal_kg.db"
    if not tkg_path.exists():
        return
    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(tkg_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # Insert narrative entities
        for nar in narratives:
            eid = "nar_" + hashlib.md5(f"{nar['domain']}:{nar['title']}".encode()).hexdigest()[:12]
            conn.execute("""
                INSERT OR REPLACE INTO entities (id, name, type, summary, created_at, updated_at)
                VALUES (?, ?, 'narrative', ?, ?, ?)
            """, (eid, nar["title"], nar["summary"], ts, ts))
            # Extract facts from narrative
            conn.execute("""
                INSERT OR IGNORE INTO facts (subject_id, predicate, object, valid_at, source, confidence)
                VALUES (?, ?, ?, ?, 'narrative_memory', 0.8)
            """, (eid, "domain", nar["domain"], ts))
            conn.execute("""
                INSERT OR IGNORE INTO facts (subject_id, predicate, object, valid_at, source, confidence)
                VALUES (?, ?, ?, ?, 'narrative_memory', 0.8)
            """, (eid, "episodes", str(nar.get("episode_count", 0)), ts))

        # Insert theme entities + facts
        for theme, count in themes:
            eid = "thm_" + hashlib.md5(theme.encode()).hexdigest()[:12]
            conn.execute("""
                INSERT OR REPLACE INTO entities (id, name, type, summary, created_at, updated_at)
                VALUES (?, ?, 'theme', ?, ?, ?)
            """, (eid, theme, f"Recurring theme with {count} mentions", ts, ts))
            conn.execute("""
                INSERT OR IGNORE INTO facts (subject_id, predicate, object, valid_at, source, confidence)
                VALUES (?, 'frequency', ?, ?, 'narrative_memory', 0.9)
            """, (eid, count, ts))

        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    if "--gap" in sys.argv:
        print(json.dumps(compute_insight_action_gap(), indent=2, default=str))
    elif "--themes" in sys.argv:
        print(json.dumps(top_themes(8), indent=2, default=str))
    elif "--gaps" in sys.argv:
        print(json.dumps(suggest_gap_actions(), indent=2, default=str))
    elif "--recent" in sys.argv:
        print(json.dumps(retrieve_recent(24), indent=2, default=str)[:2000])
    else:
        print(f"Episodic memory store: {EP_STORE}")
        print(f"Episodes: {len(_load_episodes())}")
        if os.path.exists(COMPRESS_STORE):
            comp = sum(1 for _ in open(COMPRESS_STORE))
            print(f"Compressed summaries: {comp}")
        print(json.dumps(compute_insight_action_gap(), indent=2))
