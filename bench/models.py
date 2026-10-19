"""List the models each configured API key can reach, then check the default
models with a real one-token call (keys are never printed).

Being listed is not enough: providers keep retired models in /models while
refusing calls to them. Each default model gets one of:
  OK                  a real call succeeded
  LISTED BUT REFUSED  the provider lists it but rejects calls (e.g. HTTP 404/403)
  RATE LIMITED        HTTP 429 on the check; retry later before trusting it
  UNAVAILABLE         HTTP 5xx after retries (overloaded or down); usually transient
  NOT LISTED          absent from the provider's /models list
  ERROR               anything else (network, missing key)

Usage:
  python3 -m bench.models                                  # check DEFAULT_MODELS; exit 1 if any is not OK
  python3 -m bench.models gemini/gemini-3.7-flash ...      # check these models instead
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import sys

from .config import DEFAULT_MODELS, PROVIDERS, load_env
from .llm import ChatClient, LLMError


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


def check_model(model: str, listed: list[str] | None) -> str:
    """Status of one '<provider>/<model id>' entry; listed is None if the listing failed."""
    _, _, model_id = model.partition("/")
    try:
        ChatClient(model).ping()
        return "OK"
    except SystemExit as exc:  # missing key or unknown provider, from config.resolve
        return f"ERROR ({exc})"
    except LLMError as exc:
        if exc.status == 429:
            return "RATE LIMITED"
        if exc.status is not None and exc.status >= 500:
            return f"UNAVAILABLE (HTTP {exc.status}, likely transient)"
        if listed is not None and model_id not in listed:
            return "NOT LISTED"
        if exc.status is not None:
            return f"LISTED BUT REFUSED (HTTP {exc.status})"
        return f"ERROR ({str(exc)[:80]})"


def main() -> None:
    load_env()
    targets = sys.argv[1:] or DEFAULT_MODELS
    listings: dict[str, list[str] | None] = {}
    for provider in PROVIDERS:
        try:
            ids = list_models(provider)
        except RuntimeError as exc:
            print(f"{provider}: skipped ({exc})")
            listings[provider] = None
            continue
        except urllib.error.HTTPError as exc:
            print(f"{provider}: HTTP {exc.code}")
            listings[provider] = None
            continue
        listings[provider] = ids
        print(f"{provider}: {len(ids)} models")
        for i in ids:
            print(f"   {i}")
    print("\nModels to check (real one-token call):" if sys.argv[1:] else "\nDefault models (real one-token call):")
    bad = 0
    for m in targets:
        status = check_model(m, listings.get(m.partition("/")[0]))
        bad += status != "OK"
        print(f"   {m:40s} {status}")
    if bad:
        print(f"\n{bad} model(s) not usable. UNAVAILABLE/RATE LIMITED: retry later; otherwise update DEFAULT_MODELS in bench/config.py.")
        sys.exit(1)


if __name__ == "__main__":
    main()
