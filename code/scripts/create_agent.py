#!/usr/bin/env python3
"""create_agent.py — Onboarding new agent in one command."""
import pathlib, json, os, sys, subprocess
HERMES_HOME=pathlib.Path.home() / ".hermes"
def create(name, archetype="Guardian"):
    if not name.replace("_","").replace("-","").isalnum() or not name[0].isalpha() or len(name)>20:
        print(f"Invalid name {name}: must match ^[a-z][a-z0-9_\\-]{{1,19}}$")
        sys.exit(1)
    agents_dir=HERMES_HOME / "agents"
    # Check no collision
    if (agents_dir / f"{name}.py").exists():
        print(f"Agent {name} already exists")
        sys.exit(1)
    # 1. Memory
    mem_dir=HERMES_HOME / "agentbus" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    mem_file=mem_dir / f"{name}.md"
    mem_file.write_text(f"# {name.title()} — {archetype}\n\n## Identity\nRole: {archetype} | Tagline: \"On guard.\"\n\n## Priorities\n1. Custom priorities for {name}\n\n## Evolution Log\n- {__import__('datetime').date.today()}: Created via onboarding\n")
    print(f"Created {mem_file}")
    # 2. Script (generic watchdog)
    script=agents_dir / f"{name}.py"
    script.write_text(f"#!/usr/bin/env python3\n\"\"\"{name}.py — {archetype} agent (scaffolded).\"\"\"\nimport sys\nsys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))\nimport agent_frame as F\nF.NAME=\"{name}\"\ndef check():\n    data=F.load_store()\n    print(\"{name}: check done — 0 alerts\")\ndef report():\n    print(\"{name}: report\")\nif __name__==\"__main__\":\n    import sys as _s\n    cmd=_s.argv[1] if len(_s.argv)>1 else \"check\"\n    F.main()\n    (check if cmd==\"check\" else report)()\n")
    script.chmod(0o755)
    print(f"Created {script}")
    # 3. Service
    svc_dir=pathlib.Path.home() / ".config" / "systemd" / "user"
    svc_dir.mkdir(parents=True, exist_ok=True)
    svc=svc_dir / f"agent-{name}.service"
    svc.write_text(f"[Unit]\nDescription=Autonomous agent loop - {name}\nAfter=network.target agentbus.service\n\n[Service]\nType=simple\nExecStart=/usr/bin/python3 {HERMES_HOME}/agents/agent_loop.py {name} --interval 300\nRestart=on-failure\nRestartSec=30\nEnvironment=AGENTBUS_URL=http://127.0.0.1:9107\nEnvironment=HOP_URL=http://127.0.0.1:8083/v1/chat/completions\nEnvironment=HOP_MODEL=haiku-4.5\n\n[Install]\nWantedBy=default.target\n")
    print(f"Created {svc}")
    # 4. Topic (via create_topics.py logic, but just note)
    print(f"Onboarding {name} complete — run: systemctl --user daemon-reload && systemctl --user enable --now agent-{name}.service")
    # 5. Board wiring is automatic via agent_loop
    return True

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--archetype", default="Guardian")
    args=p.parse_args()
    create(args.name, args.archetype)
