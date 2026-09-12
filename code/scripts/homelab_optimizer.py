"""
homelab_optimizer.py — Self-optimization engine
Tunes resource limits, retention policies, alert thresholds, and config
based on observed usage patterns. Runs weekly.
"""

import json, os, subprocess, sys, re
from datetime import datetime
from pathlib import Path
from homelab_graph import crg_impact, crg_search, crg_status, run_cmd

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
METRICS_FILE = DATA_DIR / "data" / "metrics.json"
COMPOSE_DIR = Path("/home/rohit/services/docker/compose")

def get_docker_stats():
    """Get current resource usage per container"""
    rc, out, err = run_cmd(["docker", "stats", "--no-stream", "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}"])
    if rc != 0:
        return []
    containers = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|")
        if len(parts) >= 3:
            def parse_mem(s):
                s = s.strip().replace("GiB", "g").replace("MiB", "m").replace("KiB", "k")
                if s.endswith("g"):
                    return float(s[:-1]) * 1024
                elif s.endswith("m"):
                    return float(s[:-1])
                elif s.endswith("k"):
                    return float(s[:-1]) / 1024
                return 0
            containers.append({
                "name": parts[0],
                "cpu": parts[1].strip().rstrip("%"),
                "mem_pct": parts[2].strip().rstrip("%"),
                "mem_used_mb": parse_mem(parts[3].split("/")[0].strip()),
            })
    return containers

def get_system_metrics():
    """Collect system-wide metrics"""
    metrics = {}
    # CPU temp
    rc, out, _ = run_cmd(["cat", "/sys/class/thermal/thermal_zone0/temp"])
    if rc == 0 and out.strip():
        metrics["cpu_temp"] = float(out.strip()) / 1000
    # Load
    rc, out, _ = run_cmd(["cat", "/proc/loadavg"])
    if rc == 0:
        parts = out.strip().split()
        metrics["load_1m"] = float(parts[0])
        metrics["load_5m"] = float(parts[1])
        metrics["load_15m"] = float(parts[2])
    # Memory
    rc, out, _ = run_cmd(["free", "-m"])
    if rc == 0:
        lines = out.strip().split("\n")
        mem = lines[1].split()
        metrics["mem_total_mb"] = int(mem[1])
        metrics["mem_used_mb"] = int(mem[2])
        metrics["mem_pct"] = int(mem[2]) / int(mem[1]) * 100
    # Swap
    swap = lines[2].split() if len(lines) > 2 else [0, 0, 0]
    metrics["swap_used_mb"] = int(swap[2]) if len(swap) > 2 else 0
    # Disk
    rc, out, _ = run_cmd(["df", "/"])
    if rc == 0:
        parts = out.strip().split("\n")[1].split()
        metrics["disk_pct"] = int(parts[4].rstrip("%"))
    return metrics

def optimize_resource_limits(containers, system):
    """Suggest and apply resource limit changes"""
    suggestions = []
    mem_total = system.get("mem_total_mb", 34000)

    for c in containers:
        name = c["name"]
        mem_pct = float(c.get("mem_pct", 0))
        mem_used = c.get("mem_used_mb", 0)

        # CRG blast-radius check for high-impact containers
        blast = crg_impact([name])
        blast_note = ""
        if isinstance(blast, dict) and blast.get("impact") == "high":
            blast_note = f" [blast-radius: {blast.get("affected_files", 0)} files]"

        # If container uses >70% of memory with no limit, suggest limit
        if mem_pct > 70:
            suggested_limit = int(mem_used * 1.5)  # 50% headroom
            suggestions.append({
                "name": name,
                "type": "memory_limit",
                "current_mb": mem_used,
                "suggested_mb": suggested_limit,
                "reason": f"uses {mem_pct:.0f}% of total memory{blast_note}"
            })

        # If container uses <10% and has a limit, suggest reducing
        if mem_pct < 10 and "openwebui" not in name.lower():
            # Just note it
            pass

    return suggestions

def optimize_log_retention():
    """Optimize Docker log retention based on disk usage"""
    disk_pct = 0
    rc, out, _ = run_cmd(["df", "/"])
    if rc == 0:
        parts = out.strip().split("\n")[1].split()
        disk_pct = int(parts[4].rstrip("%"))

    if disk_pct > 75:
        # Aggressive log cleanup
        run_cmd(["docker", "system", "prune", "-f", "--volumes", "--filter", "until=24h"])
        print("  Aggressive Docker cleanup performed")
        return "aggressive_prune"
    elif disk_pct > 50:
        run_cmd(["docker", "system", "prune", "-f", "--filter", "until=72h"])
        print("  Moderate Docker cleanup performed")
        return "moderate_prune"
    return "none_needed"

def optimize_alert_thresholds(system):
    """Adjust Prometheus alert thresholds based on baseline"""
    # Read current alerts
    alert_file = COMPOSE_DIR / "prometheus-config.yaml"
    if not alert_file.exists():
        alert_file = Path("/home/rohit/services/prometheus/alerts.yml")

    if not alert_file.exists():
        return None

    content = alert_file.read_text()
    disk_pct = system.get("disk_pct", 50)

    # If disk is consistently near threshold, raise it slightly
    if disk_pct > 75:
        # Check if threshold is 80%
        new_content = re.sub(r'disk_usage_pct > (\d+)',
                            lambda m: f'disk_usage_pct > {min(int(m.group(1)) + 5, 95)}'
                            if int(m.group(1)) - disk_pct < 5 else m.group(0),
                            content)
        if new_content != content:
            alert_file.write_text(new_content)
            print(f"  Raised disk alert threshold (current usage: {disk_pct}%)")
            return "threshold_raised"

    return None

def optimize():
    print(f"Optimization run at {datetime.now().isoformat()}")
    containers = get_docker_stats()
    system = get_system_metrics()

    print(f"  System: {system.get('mem_pct', 0):.0f}% mem, "
          f"{system.get('disk_pct', 0)}% disk, "
          f"{system.get('cpu_temp', 0):.0f}C, "
          f"swap: {system.get('swap_used_mb', 0)}MB")

    # Resource limits
    suggestions = optimize_resource_limits(containers, system)
    if suggestions:
        print(f"  Resource suggestions: {len(suggestions)}")
        for s in suggestions[:3]:
            print(f"    {s['name']}: limit mem to {s['suggested_mb']}MB ({s['reason']})")

    # Log retention
    log_action = optimize_log_retention()
    if log_action != "none_needed":
        print(f"  Log retention: {log_action}")

    # Alert thresholds
    threshold_action = optimize_alert_thresholds(system)
    if threshold_action:
        print(f"  Alert thresholds: {threshold_action}")

    # Save metrics for trend analysis
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_FILE, "a") as f:
        f.write(json.dumps({"timestamp": datetime.now().isoformat(), **system}) + "\n")

    return {"suggestions": suggestions, "log_action": log_action, "threshold_action": threshold_action}

if __name__ == "__main__":
    result = optimize()
    print(f"\nOptimization complete")
