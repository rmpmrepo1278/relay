#!/usr/bin/env python3
"""
Hermes Zero-Cost Guard — shared version used by hermes_zero_cost_guard_wrapper.sh.

This is a SAFETY NET for the Hermes agent. It ensures Hermes never uses a paid model.
Imports all model classification from the shared costguard library at
~/.hermes/lib/costguard/ — NO hardcoded model lists here.

Usage:
  python3 zero_cost_guard.py check [--model <model_id>]
  python3 zero_cost_guard.py list
  python3 zero_cost_guard.py status
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

# --- Shared costguard library (self-healing: hermes-agent reinstalls can wipe lib/) ---
COSTGUARD_LIB = Path.home() / ".hermes" / "lib" / "costguard"
if not (COSTGUARD_LIB / "guard.py").exists():
    _alt = Path.home() / ".hermes" / "hermes-agent" / "costguard"
    if (_alt / "guard.py").exists():
        COSTGUARD_LIB.parent.mkdir(parents=True, exist_ok=True)
        try:
            if COSTGUARD_LIB.is_symlink() or COSTGUARD_LIB.exists():
                COSTGUARD_LIB.unlink()
        except OSError:
            pass
        COSTGUARD_LIB.symlink_to(_alt, target_is_directory=True)
sys.path.insert(0, str(COSTGUARD_LIB.parent))
from costguard.guard import CostGuard


class ZeroCostGuard:
    """Hermes-facing zero-cost guard. Delegates all model classification to shared CostGuard."""

    def __init__(self, config_path: Optional[str] = None):
        self._guard = CostGuard()
        self.state_file = Path.home() / '.hermes' / 'shared' / 'zero_cost_guard' / 'state.json'
        self.load_state()

    def is_model_free(self, model_id: str) -> bool:
        """Check if a model is allowed. Delegates to shared CostGuard.

        Checks blocklist first, then allowlist. No API calls — pure local lookup.
        """
        if not model_id:
            return False
        if self._guard.is_blocked(model_id):
            return False
        return self._guard.is_free(model_id)

    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                self.state = json.load(f)
        else:
            self.state = {'switches': [], 'last_check': None}

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def check_and_enforce(self, current_model: str) -> dict:
        """Check current model and return result with optional enforcement info.

        Uses the shared CostGuard's check_and_switch for Hermes target.
        """
        result = {
            'model': current_model,
            'is_free': False,
            'action': 'none',
            'switched_to': None,
        }

        if self.is_model_free(current_model):
            result['is_free'] = True
            return result

        # Model is NOT free — use shared guard to find replacement and switch
        result['action'] = 'blocked'

        try:
            switch_result = self._guard.check_and_switch(target="hermes")
            if switch_result.get('switched'):
                result['switched_to'] = switch_result.get('new_model')
                result['action'] = 'switched'
                self.state.setdefault('switches', []).append({
                    'from': current_model,
                    'to': switch_result['new_model'],
                    'timestamp': str(__import__('datetime').datetime.now()),
                })
                self.save_state()
            else:
                result['action'] = 'blocked_no_switch'
        except Exception as e:
            result['action'] = f'error: {e}'

        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="check", choices=["check", "list", "status"])
    parser.add_argument("--model", type=str, help="Model to check")
    args = parser.parse_args()

    guard = ZeroCostGuard()

    if args.action == "list":
        print("Allowed free models (from shared allowlist):")
        for i, m in enumerate(guard._guard.get_free_models(ranked=True), 1):
            print(f"  {i}. {m}")
        print(f"\nBlocked models:")
        for m in guard._guard.get_blocked_models():
            print(f"  ✗ {m}")
    elif args.action == "check":
        if args.model:
            model = args.model
        else:
            # Read actual model from Hermes config via CostGuard
            try:
                hermes_cfg = guard._guard.get_hermes_model()
                model = hermes_cfg.get("model", "")
                if not model:
                    print("⚠ Could not determine Hermes model from config.yaml")
                    sys.exit(1)
            except Exception as e:
                print(f"⚠ Error reading Hermes config: {e}")
                sys.exit(1)
        result = guard.check_and_enforce(model)
        if result['is_free']:
            print(f"✓ {model} is ALLOWED (free)")
        else:
            print(f"✗ {model} is NOT allowed!")
            if result['switched_to']:
                print(f"  SWITCHED TO FREE MODEL: {result['switched_to']}")
            else:
                print(f"  No replacement found! Action: {result['action']}")
    elif args.action == "status":
        print(f"State: {json.dumps(guard.state, indent=2)}")
