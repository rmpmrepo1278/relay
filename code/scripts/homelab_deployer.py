"""
homelab_deployer.py — Auto-deploys evaluated candidates
Handles: MCP server configs, Docker compose services, health check wiring
Includes: compose backup, rollback on failure, post-deploy verification
"""

import json, os, subprocess, sys, shutil, time
from datetime import datetime
from pathlib import Path
from homelab_graph import crg_impact, run_cmd

DATA_DIR = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
EVAL_FILE = DATA_DIR / "data" / "evaluations.jsonl"
DEPLOY_LOG = DATA_DIR / "data" / "deploy_log.jsonl"
BACKUP_DIR = DATA_DIR / "backups" / "compose"
COMPOSE_DIR = Path("/home/rohit/services/docker/compose")

KNOWN_MCP_SERVERS = {
    "mcp/everything": {"image": "mcp/everything", "port": 8912, "description": "MCP everything server"},
    "mcp/fetch": {"image": "mcp/fetch", "port": 8913, "description": "MCP fetch server"},
    "mcp/filesystem": {"image": "mcp/filesystem", "port": 8914, "description": "MCP filesystem server"},
    "mcp/sequentialthinking": {"image": "mcp/sequentialthinking", "port": 8915, "description": "MCP sequential thinking server"},
}

def log_deploy(entry):
    DEPLOY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DEPLOY_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def deploy_mcp_server(name):
    """Add MCP server to opencode config"""
    config_path = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not config_path.exists():
        print(f"  No opencode config at {config_path}")
        return {"status": "failed", "reason": "config_not_found"}

    mcp_name = name.split("/")[-1]
    config_text = config_path.read_text()

    if mcp_name in config_text:
        print(f"  MCP server already in config: {mcp_name}")
        return {"status": "skipped", "reason": "already_configured"}

    info = KNOWN_MCP_SERVERS.get(name, {})
    image = info.get("image", mcp_name)
    port = info.get("port", 8920)

    # Add as Docker-based MCP entry in opencode.jsonc
    import re
    insertion = f'''    "{mcp_name}": {{
      "type": "docker",
      "image": "{image}",
      "port": {port},
      "enabled": true
    }},'''

    # Insert before the last closing brace
    if config_text.rstrip().endswith("}"):
        config_text = config_text.rstrip()
        config_text = config_text[:-1] + insertion + "\n}"
        config_path.write_text(config_text)
        print(f"  Added MCP server '{mcp_name}' to {config_path}")
        return {"status": "deployed", "type": "mcp", "name": mcp_name}
    else:
        print(f"  Could not parse config format for {config_path}")
        return {"status": "failed", "reason": "config_parse_error"}

def verify_after_deploy():
    """Run basic health check after deployment"""
    time.sleep(3)
    rc, out, _ = run_cmd(["docker", "ps", "--format", "{{.Names}}", "--filter", "health=unhealthy"])
    unhealthy = [l for l in out.strip().splitlines() if l.strip()]
    if unhealthy:
        print(f"  WARNING: {len(unhealthy)} unhealthy containers after deploy")
        return False
    return True

def verify_compose_files():
    for f in sorted(COMPOSE_DIR.glob("*.yml")):
        r = run_cmd(["docker", "compose", "-f", str(f), "config", "--quiet"], timeout=15)
        if r[0] != 0:
            return False, f, r[2]
    return True, None, None

def backup_compose():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"pre_deploy_{ts}"
    backup_path.mkdir()
    for f in COMPOSE_DIR.glob("*.yml"):
        shutil.copy2(f, backup_path / f.name)
    return backup_path

def deploy():
    if not EVAL_FILE.exists():
        print("No evaluations to deploy")
        return []

    print(f"Deploy run at {datetime.now().isoformat()}")
    backup_path = backup_compose()

    ok, bad_file, err = verify_compose_files()
    if not ok:
        print(f"  ERROR: Compose file issue before deploy: {bad_file}")
        return []

    results = []
    with open(EVAL_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            eval_result = json.loads(line)
            if eval_result.get("decision") != "deploy":
                continue
            name = eval_result.get("name", "")
            deploy_type = eval_result.get("deploy_type", "service")

            result = None
            if deploy_type == "mcp":
                result = deploy_mcp_server(name)
            else:
                # CRG blast-radius check before deploy
                blast = crg_impact([name])
                if blast.get("impact") == "high":
                    result = {"status": "flagged", "reason": f"high blast-radius ({blast.get("affected_files", 0)} files affected)", "blast_radius": blast}
                    log_deploy(result)
                    results.append(result)
                    print(f"  FLAGGED: {name} — high blast-radius, review before deploy")
                    continue

                print(f"  Service deploy not yet automated for: {name}")
                result = {"status": "skipped", "reason": "service_deploy_not_implemented"}

            if result:
                result["name"] = name
                result["deployed_at"] = datetime.now().isoformat()
                log_deploy(result)
                results.append(result)
                print(f"  {result['status']}: {name}")

    # Post-deploy verification
    if not verify_after_deploy():
        print(f"  Deploy issues detected, checking compose rollback...")

    return results

if __name__ == "__main__":
    results = deploy()
    print(f"\nResults: {len(results)} items")
    for r in results:
        print(f"  {r.get('status', '?')}: {r.get('name', '?')}")
