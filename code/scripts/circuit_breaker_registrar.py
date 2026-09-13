#!/usr/bin/env python3
"""circuit_breaker_registrar.py - register + exercise circuit breakers for key
external dependencies. Scheduler/watchdog jobs call record_success()/record_failure()
from circuit_breaker.py after each interaction with these endpoints."""
import sys
sys.path.insert(0, "/home/rohit/.hermes/scripts")
from circuit_breaker import get_or_create_circuit

CIRCUITS = {
    "telegram_bridge": {"failure_threshold": 5, "recovery_timeout": 60},
    "groq":            {"failure_threshold": 3, "recovery_timeout": 120},
    "openrouter":      {"failure_threshold": 3, "recovery_timeout": 300},
    "magnitude":       {"failure_threshold": 3, "recovery_timeout": 300},
    "healthchecks":    {"failure_threshold": 5, "recovery_timeout": 60},
}

def main():
    for name, cfg in CIRCUITS.items():
        get_or_create_circuit(name, cfg["failure_threshold"], cfg["recovery_timeout"])
    print("registered:", ", ".join(sorted(CIRCUITS)))

if __name__ == "__main__":
    main()
