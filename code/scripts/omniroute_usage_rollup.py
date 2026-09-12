#!/usr/bin/env python3
"""omniroute_usage_rollup.py — Roll call_logs into OmnriRoute usage summary tables.

The v0.16.2 build ships daily/hourly_usage_summary tables + settings
(aggregation.enabled) but the rollup path is unwired (no caller, source table
quota_snapshots is empty). This job gives real numbers going forward by
aggregating the accurate, flowing call_logs into those same tables using the
router's own schema, idempotently (full upsert each run).

Usage:
    python3 omniroute_usage_rollup.py            # rollup (idempotent)
    python3 omniroute_usage_rollup.py --status   # show summary tables
"""

import sqlite3
import sys
from datetime import datetime

DB = "/home/rohit/.omniroute/storage.sqlite"

HOURLY_SQL = """
INSERT INTO hourly_usage_summary
  (provider, model, date_hour, total_requests, total_input_tokens, total_output_tokens, total_cost)
SELECT
  COALESCE(provider, 'unknown'),
  COALESCE(model, 'unknown'),
  strftime('%Y-%m-%d %H:00:00', timestamp),
  COUNT(*),
  COALESCE(SUM(tokens_in), 0),
  COALESCE(SUM(tokens_out), 0),
  0.0
FROM call_logs
WHERE status >= 200 AND status < 300
GROUP BY provider, model, strftime('%Y-%m-%d %H:00:00', timestamp)
ON CONFLICT(provider, model, date_hour) DO UPDATE SET
  total_requests = excluded.total_requests,
  total_input_tokens = excluded.total_input_tokens,
  total_output_tokens = excluded.total_output_tokens,
  total_cost = excluded.total_cost
"""

DAILY_SQL = """
INSERT INTO daily_usage_summary
  (provider, model, date, total_requests, total_input_tokens, total_output_tokens, total_cost)
SELECT
  COALESCE(provider, 'unknown'),
  COALESCE(model, 'unknown'),
  date(timestamp),
  COUNT(*),
  COALESCE(SUM(tokens_in), 0),
  COALESCE(SUM(tokens_out), 0),
  0.0
FROM call_logs
WHERE status >= 200 AND status < 300
GROUP BY provider, model, date(timestamp)
ON CONFLICT(provider, model, date) DO UPDATE SET
  total_requests = excluded.total_requests,
  total_input_tokens = excluded.total_input_tokens,
  total_output_tokens = excluded.total_output_tokens,
  total_cost = excluded.total_cost
"""


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB, timeout=30)
    db.execute("PRAGMA busy_timeout = 30000")
    return db


def rollup() -> tuple[int, int]:
    db = connect()
    try:
        h = db.execute(HOURLY_SQL).rowcount
        d = db.execute(DAILY_SQL).rowcount
        db.commit()
    finally:
        db.close()
    return h, d


def totals() -> tuple[int, int, int, int]:
    db = connect()
    try:
        rows = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_requests),0), "
            "COALESCE(SUM(total_input_tokens),0), COALESCE(SUM(total_output_tokens),0) "
            "FROM daily_usage_summary"
        ).fetchone()
    finally:
        db.close()
    return rows


def status() -> None:
    n, r, tri, tro = totals()
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] daily rows={n} requests={r} in_tok={tri} out_tok={tro}")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        status()
        return 0
    h, d = rollup()
    n, r, tri, tro = totals()
    print(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] rollup ok "
        f"(hourly rows={h}, daily rows={d}); daily totals: requests={r} "
        f"in_tok={tri} out_tok={tro}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())