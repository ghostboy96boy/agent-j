"""Settings: .env loading and the model registry.

Models are reached through OpenAI-compatible chat endpoints, so one client
covers every provider. Phase 0 uses free tiers only (see docs/ROADMAP.md).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing vars."""
    if not path.exists():
        raise SystemExit("Missing .env. Run: cp .env.example .env")
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
    },
}

# Pinned model versions keep runs reproducible. Format: "<provider>/<model id>".
# Groq retired llama-3.3-70b-versatile on 2026-08-16; check `make models` before pinning.
DEFAULT_MODELS = [
    "groq/openai/gpt-oss-120b",
    "groq/qwen/qwen3.8-27b",
    "gemini/gemini-2.5-flash",
]


def resolve(model: str) -> tuple[str, str, str]:
    """Return (base_url, api_key, model_id) for "<provider>/<model id>"."""
    provider, _, model_id = model.partition("/")
    if provider not in PROVIDERS or not model_id:
        raise SystemExit(f"Unknown model '{model}'. Use <provider>/<model>, provider in {list(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        raise SystemExit(f"Set {cfg['key_env']} in .env to use {model}")
    return cfg["base_url"], key, model_id
