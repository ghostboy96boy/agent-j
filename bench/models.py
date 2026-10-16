"""List the models each configured API key can reach (keys are never printed).

Usage: python3 -m bench.models
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .config import DEFAULT_MODELS, PROVIDERS, load_env


def list_models(provider: str) -> list[str]:
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg["key_env"], "")
    if not key:
        raise RuntimeError(f"{cfg['key_env']} not set")
    req = urllib.request.Request(
        cfg["base_url"] + "/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "agent-j/0.1"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    ids = [m.get("id", "") for m in data.get("data", [])]
    return sorted(i.removeprefix("models/") for i in ids if i)


def main() -> None:
    load_env()
    for provider in PROVIDERS:
        try:
            ids = list_models(provider)
        except RuntimeError as exc:
            print(f"{provider}: skipped ({exc})")
            continue
        except urllib.error.HTTPError as exc:
            print(f"{provider}: HTTP {exc.code}")
            continue
        print(f"{provider}: {len(ids)} models")
        for i in ids:
            print(f"   {i}")
    print("\nDefault models:")
    for m in DEFAULT_MODELS:
        provider, _, model_id = m.partition("/")
        try:
            ok = model_id in list_models(provider)
        except Exception:
            ok = False
        print(f"   {m:40s} {'OK' if ok else 'NOT AVAILABLE'}")


if __name__ == "__main__":
    main()
