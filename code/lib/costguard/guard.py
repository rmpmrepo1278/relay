"""
guard.py — CostGuard library for zero-cost LLM policy enforcement.

Classifies models as free/blocklisted/unreliable and checks provider configs.
"""

from __future__ import annotations
import json
from pathlib import Path

MODELS_FILE = Path(__file__).parent / "models.json"

# Fallback models list if models.json is missing
FREE_MODELS = {
    "openrouter/owl-alpha": {"provider": "openrouter", "cost": 0, "context": 1000000},
    "google/gemma-3-12b-it": {"provider": "ollama-local", "cost": 0, "context": 131072},
    "meta-llama/llama-3.2-3b": {"provider": "ollama-local", "cost": 0, "context": 8192},
    "qwen/qwen2.5-7b": {"provider": "ollama-local", "cost": 0, "context": 131072},
    "mistralai/mistral-7b": {"provider": "ollama-local", "cost": 0, "context": 32768},
}

BLOCKLISTED_MODELS = {
    "anthropic/claude-sonnet-4-6": {"reason": "paid tier, use only via Anthropic API key"},
    "anthropic/claude-opus-4-8": {"reason": "paid tier, use only via Anthropic API key"},
    "openai/gpt-4o": {"reason": "paid tier"},
    "openai/gpt-4o-mini": {"reason": "paid tier"},
    "google/gemini-2.5-pro": {"reason": "paid tier"},
}


class CostGuard:
    def __init__(self):
        self.models = dict(FREE_MODELS)
        self.blocklisted = dict(BLOCKLISTED_MODELS)
        if MODELS_FILE.exists():
            try:
                data = json.loads(MODELS_FILE.read_text())
                for name, info in data.get("free", {}).items():
                    self.models[name] = info
                for name, info in data.get("blocklisted", {}).items():
                    self.blocklisted[name] = info
            except Exception:
                pass

    def is_free(self, model_name: str) -> bool:
        """Check if a model is free."""
        if model_name in self.blocklisted:
            return False
        if model_name in self.models:
            return self.models[model_name].get("cost", 1) == 0
        # Unknown model — assume not free (safe default)
        return False

    def is_blocklisted(self, model_name: str) -> bool:
        return model_name in self.blocklisted

    def classify(self, model_name: str) -> str:
        if self.is_blocklisted(model_name):
            return "blocklisted"
        if self.is_free(model_name):
            return "free"
        return "unknown"

    def check_config(self, config: dict) -> list[str]:
        """Check a provider config for non-free models. Returns warnings."""
        warnings = []
        for key, value in config.items():
            if isinstance(value, str) and not self.is_free(value):
                warnings.append(f"Config {key}={value} may not be free")
        return warnings

    def get_blocked_models(self) -> list[str]:
        """Return names of all blocklisted models."""
        return sorted(self.blocklisted.keys())

    def get_free_models(self) -> list[str]:
        """Return names of all models classified free (cost == 0)."""
        return sorted(
            name for name, info in self.models.items() if info.get("cost", 1) == 0
        )