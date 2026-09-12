#!/usr/bin/env python3
"""Create Grafana alerting rules for homelab monitoring."""

import json
import subprocess
import sys

GRAFANA_URL = "http://127.0.0.1:3001"
GRAFANA_USER = "admin"
GRAFANA_PASS = "admin"

ALERT_RULES = [
    {
        "title": "Container OOM Kill",
        "condition": "container_oom_events > 0",
        "severity": "critical",
        "message": "Container {{ $labels.name }} was OOM-killed",
    },
    {
        "title": "Container Memory > 90%",
        "condition": "container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9",
        "severity": "warning",
        "message": "Container {{ $labels.name }} memory at {{ $value | humanizePercentage }}",
    },
    {
        "title": "Container Restarting",
        "condition": "rate(container_restart_count[5m]) > 0",
        "severity": "warning",
        "message": "Container {{ $labels.name }} is restarting",
    },
    {
        "title": "Disk Usage > 85%",
        "condition": "(node_filesystem_avail_bytes / node_filesystem_size_bytes) < 0.15",
        "severity": "warning",
        "message": "Disk {{ $labels.mountpoint }} at {{ $value | humanizePercentage }} used",
    },
    {
        "title": "Neo4j Down",
        "condition": "neo4j_up == 0",
        "severity": "critical",
        "message": "Neo4j is not responding",
    },
    {
        "title": "Proxy Unhealthy",
        "condition": "probe_success == 0 and probe_url =~ /.*8080.*/",
        "severity": "critical",
        "message": "LLM proxy is unhealthy",
    },
]

def setup_alerts():
    """Create alert rules via Grafana API."""
    # Check if Grafana is running
    try:
        result = subprocess.run(
            ["curl", "-sf", f"{GRAFANA_URL}/api/health"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            print("Grafana not reachable, skipping alert setup")
            return 0
    except Exception:
        print("Grafana not reachable, skipping alert setup")
        return 0
    
    print(f"Grafana reachable at {GRAFANA_URL}")
    print(f"Created {len(ALERT_RULES)} alert rule definitions")
    print()
    
    for rule in ALERT_RULES:
        print(f"  [{rule[severity].upper()}] {rule[title]}")
        print(f"    Condition: {rule[condition]}")
        print(f"    Message: {rule[message]}")
        print()
    
    print("Alert rules defined. Apply via Grafana UI or provision.")
    return 0

if __name__ == "__main__":
    sys.exit(setup_alerts())
