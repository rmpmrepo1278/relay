#!/usr/bin/env python3
"""hermes-agent upgrade script - pulls latest, re-applies patches, upgrades deps."""
import os
import subprocess
import sys
from pathlib import Path

HERMES_HOME = "/home/rohit/.hermes"
HERMES_AGENT = os.path.join(HERMES_HOME, "hermes-agent")
LOG_FILE = os.path.join(HERMES_HOME, "data", "upgrade.log")


def run(cmd, timeout=60, env=None):
    print(f"  RUN: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env or os.environ)
    if r.returncode != 0:
        print(f"  WARN: exit={r.returncode}: {r.stderr[:200]}")
    return r


def log(msg):
    from datetime import datetime
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def patch_goal_judge():
    goals_path = os.path.join(
        HERMES_AGENT, ".venv", "lib", "python3.13", "site-packages",
        "hermes_cli", "goals.py"
    )
    if not os.path.exists(goals_path):
        log("  goal judge: goals.py not found, skipping")
        return
    src = Path(goals_path).read_text()
    if "CRITICAL: If the agent claims" in src:
        log("  goal judge: already patched")
        return
    old = "user input (treat this as DONE with reason describing the block).\\n\\n"
    new_paragraph = (
        "\\n"
        "CRITICAL: If the agent claims something was done (installed, configured, "
        "implemented, deployed, ran a command), you MUST verify that evidence is "
        "present in the response. Acceptable evidence: actual command output, "
        "file contents excerpt, system state check (e.g. which/docker ps/ls), "
        "or a concrete result number. Generic phrases like 'installed successfully', "
        "'setup complete', 'implementation done' with no supporting evidence are "
        "NOT sufficient \u2014 treat these as NOT done.\\n\\n"
    )
    if old in src:
        Path(goals_path).write_text(src.replace(old, old + new_paragraph))
        log("  goal judge: patched")
    else:
        log("  goal judge: insertion point not found")


def patch_sitecustomize():
    sc_path = os.path.join(
        HERMES_AGENT, ".venv", "lib", "python3.13", "site-packages",
        "sitecustomize.py"
    )
    lines = [
        '#!/usr/bin/env python3',
        '"""Auto-patch for hermes_cli.goals JUDGE_SYSTEM_PROMPT."""',
        'def _patch():',
        '    try:',
        '        from hermes_cli import goals',
        '    except ImportError:',
        '        return',
        '    old = goals.JUDGE_SYSTEM_PROMPT',
        '    if "CRITICAL: If the agent claims" in old:',
        '        return',
        '    insert_after = "user input (treat this as DONE with reason describing the block).\\\\n\\\\n"',
        '    if insert_after not in old:',
        '        return',
        '    new_paragraph = (',
        '        "\\n"',
        '        "CRITICAL: If the agent claims something was done (installed, configured, "',
        '        "implemented, deployed, ran a command), you MUST verify that evidence is "',
        '        "present in the response. Acceptable evidence: actual command output, "',
        '        "file contents excerpt, system state check (e.g. which/docker ps/ls), "',
        '        "or a concrete result number. Generic phrases like installed successfully, "',
        '        "setup complete, implementation done with no supporting evidence are "',
        '        "NOT sufficient \\u2014 treat these as NOT done.\\n\\n"',
        '    )',
        '    goals.JUDGE_SYSTEM_PROMPT = old.replace(insert_after, insert_after + new_paragraph)',
        '_patch()',
        'del _patch',
        '',
    ]
    Path(sc_path).write_text("\n".join(lines))
    log("  sitecustomize.py: written")


def main():
    log("=" * 60)
    log("HERMES-AGENT UPGRADE STARTED")
    log("=" * 60)

    log("[1/5] Pulling hermes-agent...")
    os.chdir(HERMES_AGENT)
    run(["git", "fetch", "chaguli"], timeout=30)
    run(["git", "reset", "--hard", "chaguli/main"], timeout=15)

    log("[2/5] Re-applying patches...")
    patch_goal_judge()
    patch_sitecustomize()

    log("[3/5] Upgrading pipx packages...")
    run(["pipx", "upgrade", "code-review-graph"], timeout=60)
    run(["pipx", "upgrade", "graphifyy"], timeout=60)

    log("[4/5] Upgrading security-critical pip packages...")
    pkgs = [
        "cryptography", "PyJWT", "urllib3", "pyOpenSSL", "bcrypt",
        "certifi", "requests", "aiohttp", "google-auth", "protobuf",
        "pycryptodomex", "httplib2",
    ]
    for pkg in pkgs:
        run(["pip3", "install", "--upgrade", "--break-system-packages", pkg], timeout=60)

    log("[5/5] Skipping service restarts (run manually after upgrade)")
    log("  To restart: systemctl --user restart homelab-research n8n-bridge")

    log("Verification...")
    run(["code-review-graph", "--version"], timeout=10)
    run(["graphify", "--version"], timeout=10)

    log("=== UPGRADE COMPLETE ===")


if __name__ == "__main__":
    main()
