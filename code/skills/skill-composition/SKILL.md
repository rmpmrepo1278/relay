---
name: skill-composition
description: Skill orchestration library - sequence, parallel, branch, retry operators for chaining skills
---

# Skill Composition Skill

Orchestration layer for combining skills into workflows.

## Operators

### sequence(skills, data) → output
Run skills in order, passing output to next.
```python
result = sequence(["habit-tracker/check", "habit-gamification/check"], {"habit_id": "read"})
```

### parallel(skills, data) → [outputs]
Run skills concurrently, collect all results.
```python
results = parallel(["health_dashboard", "cost_guard"], data={})
```

### branch(conditions, default) → skill
Choose skill based on predicate.
```python
branch([("high_priority", "urgent-handler"), ("low_priority", "queue-it")])
```

### retry(skill, max_attempts=3, backoff=60) → output
Retry skill on failure with backoff.
```python
retry("gdrive_backup", max_attempts=3, backoff=120)
```

### with_verification(skill, verify_fn) → output
Run skill then verify result.
```python
with_verification("docker_restart", lambda r: docker ps | grep running)
```

## Integration

Used by autonomous_fixer.py and proactive_orchestrator.py. Skills are resolved via `~/.hermes/skills/` path.