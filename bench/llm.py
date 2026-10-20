"""Minimal OpenAI-compatible chat client with tool calling (stdlib only)."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request

from .config import resolve


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ChatClient:
    def __init__(self, model: str, temperature: float = 0.0, timeout: int = 90):
        self.model = model
        self.base_url, self._key, self.model_id = resolve(model)
        self.temperature = temperature
        self.timeout = timeout

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
                detail = exc.read()[:300].decode(errors="ignore")
                # Free tiers rate-limit hard: back off on 429 and transient 5xx.
                if exc.code in (429, 500, 502, 503) and attempt < retries - 1:
                    wait = float(exc.headers.get("retry-after") or delay)
                    time.sleep(min(wait, 60))
                    delay *= 2
                    continue
                raise LLMError(f"HTTP {exc.code} from {self.model}: {detail}", status=exc.code) from exc
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
