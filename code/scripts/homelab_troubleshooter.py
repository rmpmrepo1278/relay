#!/usr/bin/env python3
"""
homelab_troubleshooter.py — Diagnoses container failures.
Runs periodically and on-demand. Logs all diagnoses.

Fix logic is delegated to n8n Container Auto-Heal + Service Auto-Heal workflows.

Supports excluded containers:
  homelab_troubleshooter.py exclude add <name>
  homelab_troubleshooter.py exclude remove <name>
  homelab_troubleshooter.py exclude list
"""

import json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from homelab_graph import crg_search, crg_query, run_cmd

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
DIAG_LOG = DATA_DIR / "data" / "diagnosis_log.jsonl"
STATE_FILE = DATA_DIR / "data" / "troubleshooter_state.json"
EXCLUDED_FILE = DATA_DIR / "data" / "excluded_containers.json"

def log_diagnosis(container, state, diagnosis):
    DIAG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DIAG_LOG, "a") as f:
        f.write(json.dumps({
            "container": container,
            "state": state,
            "diagnosis": diagnosis,
            "timestamp": datetime.now().isoformat()
        }) + "\n")

def check_container(name):
    rc, out, err = run_cmd(["docker", "inspect", "--format",
                           "{{.State.Status}} {{.State.Health.Status}} {{.Name}}", name])
    if rc != 0:
        return "missing", ""
    parts = out.strip().split()
    status = parts[0] if len(parts) > 0 else "unknown"
    health = parts[1] if len(parts) > 1 else ""
    return status, health

def get_all_containers():
    rc, out, err = run_cmd(["docker", "ps", "-a", "--format",
                           "{{.Names}}|{{.State}}|{{.Image}}"])
    if rc != 0:
        return []
    containers = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|")
        if len(parts) >= 2:
            containers.append({"name": parts[0], "state": parts[1],
                              "image": parts[2] if len(parts) > 2 else ""})
    return containers

def diagnose_container(container):
    name = container["name"]
    state = container["state"]

    if state == "running":
        return None

    issues = []

    rc, out, err = run_cmd(["docker", "logs", "--tail", "20", name])
    if rc == 0 and out:
        last_line = out.strip().split("\n")[-1] if out.strip() else ""
        issues.append(f"last-log: {last_line[:200]}")

    rc, out, err = run_cmd(["docker", "inspect", name, "--format",
                           "{{json .HostConfig.PortBindings}}"])
    if rc == 0 and out.strip() and out.strip() != "null":
        import json as j
        try:
            ports = j.loads(out.strip())
            for container_port, host_bindings in ports.items():
                for binding in host_bindings:
                    host_port = binding.get("HostPort", "")
                    rc2, out2, _ = run_cmd(["ss", "-tlnp", f"sport = :{host_port}"])
                    if rc2 == 0 and out2.strip():
                        if name not in out2:
                            issues.append(f"port-{host_port}-in-use")
        except: pass

    rc, out, err = run_cmd(["docker", "inspect", name, "--format",
                           "{{json .Mounts}}"])
    if rc == 0 and out.strip() and out.strip() != "null":
        import json as j
        try:
            mounts = j.loads(out.strip())
            for m in mounts:
                if m.get("Type") == "bind" and not os.path.exists(m.get("Source", "")):
                    issues.append(f"missing-volume: {m.get('Source', '')}")
        except: pass

    # CRG dependency check
    dep_results = crg_query(name)
    if isinstance(dep_results, dict) and dep_results.get("results") and dep_results["results"] != "":
        issues.append("graph-deps: " + dep_results["results"][:200])

    return "; ".join(issues) if issues else "unknown"

def load_excluded() -> set:
    if EXCLUDED_FILE.exists():
        try:
            return set(json.loads(EXCLUDED_FILE.read_text()))
        except (json.JSONDecodeError, Exception):
            return set()
    return set()

def save_excluded(names: set):
    EXCLUDED_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXCLUDED_FILE.write_text(json.dumps(sorted(names), indent=2))

def diagnose_cycle():
    print(f"Diagnose cycle at {datetime.now().isoformat()}")
    results = []

    all_containers = get_all_containers()
    excluded = load_excluded()
    print(f"  Total containers: {len(all_containers)}, excluded: {len(excluded)}")

    for c in all_containers:
        if c["state"] == "running":
            continue
        if c["name"] in excluded:
            print(f"  Skipping {c['name']} ({c['state']}) — excluded")
            continue

        print(f"  Issue: {c['name']} is {c['state']}")
        diagnosis = diagnose_container(c)
        print(f"    Diagnosis: {diagnosis}")

        log_diagnosis(c["name"], c["state"], diagnosis)
        results.append({
            "name": c["name"],
            "state": c["state"],
            "diagnosis": diagnosis,
        })

    return results

def cmd_exclude_add(name: str):
    excluded = load_excluded()
    excluded.add(name)
    save_excluded(excluded)
    print(f"  {name} added to exclusion list")

def cmd_exclude_remove(name: str):
    excluded = load_excluded()
    excluded.discard(name)
    save_excluded(excluded)
    print(f"  {name} removed from exclusion list")

def cmd_exclude_list():
    excluded = load_excluded()
    if excluded:
        print("Excluded containers (auto-fix will skip):")
        for name in sorted(excluded):
            print(f"  - {name}")
    else:
        print("No containers excluded")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "exclude":
        if len(sys.argv) > 2:
            cmd = sys.argv[2]
            if cmd == "add" and len(sys.argv) > 3:
                cmd_exclude_add(sys.argv[3])
            elif cmd == "remove" and len(sys.argv) > 3:
                cmd_exclude_remove(sys.argv[3])
            elif cmd == "list":
                cmd_exclude_list()
            else:
                print("Usage: homelab_troubleshooter.py exclude <add|remove|list> [name]")
        else:
            cmd_exclude_list()
    else:
        results = diagnose_cycle()
        print(f"\nDiagnosed: {len(results)} failing containers")
        for r in results:
            print(f"  {r['name']}: {r['state']} — {r['diagnosis']}")
