"""Minimal OpenAI-compatible chat client with tool calling (stdlib only)."""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request

from pathlib import Path

from .config import ROOT, resolve


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, raw: bytes | None = None):
        super().__init__(message)
        self.status = status
        self.raw = raw  # full provider response body (no headers), kept as evidence for model errors


class DailyQuotaError(LLMError):
    """The provider's daily quota for this model is spent; waiting minutes will not help."""


ERROR_CHARS = 2000  # provider error text kept in records (quota messages put the limit near the end)
LONG_DIGITS = re.compile(r"\d{8,}")


def clean_detail(raw: bytes) -> str:
    """Provider error body, cut to ERROR_CHARS, with long digit runs (project numbers) masked.

    Records are published, so account identifiers in quota messages must not reach them.
    """
    return LONG_DIGITS.sub("<masked>", raw[:ERROR_CHARS].decode(errors="ignore"))


ERROR_DIR = ROOT / "results" / "private" / "http-errors"  # gitignored


def save_full_error(model: str, code: int, headers, raw: bytes) -> Path:
    """Keep the whole body of a 429 (not cut to ERROR_CHARS) plus its rate-limit headers, so the
    limit the provider states can be read in full. Long digit runs are still masked; the file
    lives under results/private/, which is never committed."""
    ERROR_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = ERROR_DIR / f"{stamp}-{re.sub(r'[^A-Za-z0-9.-]+', '_', model)}-{code}.txt"
    kept = [f"{k}: {v}" for k, v in (headers.items() if headers else [])
            if k.lower() == "retry-after" or "ratelimit" in k.lower()]
    body = LONG_DIGITS.sub("<masked>", raw.decode(errors="ignore"))
    path.write_text(f"model: {model}\nHTTP {code}\n" + "\n".join(kept) + "\n\n" + body + "\n")
    return path


DAILY_MARKERS = ("tokens per day", "(tpd)", "requests per day", "(rpd)", "per day", "perday")


class ChatClient:
    def __init__(self, model: str, temperature: float = 0.0, timeout: int = 90):
        self.model = model
        self.base_url, self._key, self.model_id = resolve(model)
        self.temperature = temperature
        self.timeout = timeout
        self.tokens = 0  # total tokens reported by the provider across this client's calls

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Send one chat turn and return the assistant message dict."""
        body = {
            "model": self.model_id,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }
        data = self._post("/chat/completions", body)
        self.tokens += int((data.get("usage") or {}).get("total_tokens") or 0)
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected response: {json.dumps(data)[:300]}") from exc

    def ping(self, timeout: int = 30) -> str:
        """One tiny real call (no tools, short timeout) to check the model accepts requests."""
        body = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 8,
            "temperature": 0.0,
        }
        saved, self.timeout = self.timeout, timeout
        try:
            data = self._post("/chat/completions", body, retries=3)  # short backoff for transient 5xx/429
        finally:
            self.timeout = saved
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    def _post(self, path: str, body: dict, retries: int = 6) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                # Some providers sit behind Cloudflare, which blocks the default urllib agent.
                "User-Agent": "agent-j/0.1",
            },
        )
        delay = 5.0
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                detail = clean_detail(raw)
                if exc.code == 429:
                    save_full_error(self.model, exc.code, exc.headers, raw)
                if exc.code == 429 and any(m in detail.lower() for m in DAILY_MARKERS):
                    raise DailyQuotaError(f"Daily quota reached for {self.model}: {detail}", status=429) from exc
                # Free tiers rate-limit hard: back off on 429 and transient 5xx.
                if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                    wait = float(exc.headers.get("retry-after") or delay)
                    time.sleep(min(wait, 60))
                    delay *= 2
                    continue
                raise LLMError(f"HTTP {exc.code} from {self.model}: {detail}", status=exc.code, raw=raw) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
                # A read timeout surfaces as a bare TimeoutError, not URLError. Timeouts get at
                # most 2 retries: an overloaded provider otherwise stalls a run for ~15 minutes.
                timed_out = isinstance(exc, TimeoutError) or "timed out" in str(exc)
                if attempt < (min(retries, 3) if timed_out else retries) - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                kind = "Timeout" if isinstance(exc, TimeoutError) or "timed out" in str(exc) else "Network error"
                raise LLMError(f"{kind} calling {self.model}: {exc}") from exc
        raise LLMError("unreachable")
