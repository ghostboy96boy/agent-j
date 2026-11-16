"""Is a model's daily free quota likely back?  python3 -m bench.quota MODEL  (exit 0 ready, 1 wait)

Used by the hourly resume so a model whose daily quota is spent is not called every hour, which would
add one invalid (quota-cut) run per attempt. The answer comes from the last daily-quota error recorded
for the model in results/run-*.json, timed by that file's modification time (files are saved after
every run):
- Groq counts tokens per day over a rolling 24 h window. Its "try again in 21m" only covers the
  small request that hit the limit, not a whole run, so waiting that long led to one quota-cut run
  per hour. Instead the tokens this harness spent with the model in the last 24 h (record tokens,
  timed by file) are scaled to Groq's own "Used" figure at the last error, and the model is ready
  once Limit - estimated use leaves room for a large run (RUN_BUDGET tokens).
- Gemini resets daily quotas at midnight Pacific time: wait for the next one.
A model with no recorded daily-quota error is ready.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT

GROQ_USAGE = re.compile(r"Limit (\d+), Used (\d+), Requested (\d+)")
WINDOW = timedelta(hours=24)
RUN_BUDGET = 12000  # about the 90th percentile of tokens per Groq run in phase 0
TRY_AGAIN = re.compile(r"try again in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", re.I)
PACIFIC = ZoneInfo("America/Los_Angeles")


def parse_duration(text: str) -> timedelta:
    parts = dict((u, float(v)) for v, u in re.findall(r"([\d.]+)([hms])", text))
    return timedelta(hours=parts.get("h", 0), minutes=parts.get("m", 0), seconds=parts.get("s", 0))


def is_daily_quota(error: str) -> bool:
    return error.lower().startswith("daily quota reached") or "daily quota reached for" in error.lower()


def last_quota_error(model: str, results: Path) -> tuple[datetime, str] | None:
    """(time, error text) of the newest daily-quota error recorded for model, or None."""
    newest = None
    for path in results.glob("run-*.json"):
        try:
            records = json.loads(path.read_text()).get("records", [])
        except (OSError, ValueError):
            continue
        errors = [r.get("agent_error") or "" for r in records if r.get("model") == model]
        errors = [e for e in errors if is_daily_quota(e)]
        if errors:
            t = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if newest is None or t > newest[0]:
                newest = (t, errors[-1])
    return newest


def usage_events(model: str, results: Path) -> list[tuple[datetime, int]]:
    """(file time, tokens) of every run of model; a file's runs are timed at its last save."""
    events = []
    for path in results.glob("run-*.json"):
        try:
            records = json.loads(path.read_text()).get("records", [])
        except (OSError, ValueError):
            continue
        tokens = sum(r.get("tokens") or 0 for r in records if r.get("model") == model)
        if tokens:
            events.append((datetime.fromtimestamp(path.stat().st_mtime, timezone.utc), tokens))
    return sorted(events)


def used_in_window(events: list[tuple[datetime, int]], at: datetime) -> int:
    return sum(t for when, t in events if at - WINDOW < when <= at)


def groq_ready_at(model: str, when: datetime, error: str, results: Path) -> datetime | None:
    """Earliest time the rolling window should hold RUN_BUDGET free tokens, or None if the
    error carries no usage figures or no usage was recorded in the window."""
    m = GROQ_USAGE.search(error)
    if not m:
        return None
    limit, used = int(m.group(1)), int(m.group(2))
    events = usage_events(model, results)
    ours = used_in_window(events, when)
    if not ours:
        return None  # no recorded usage to scale: fall back to the stated wait
    scale = used / ours
    for t in [when] + [e + WINDOW for e, _ in events if e + WINDOW > when]:
        if limit - scale * used_in_window(events, t) >= RUN_BUDGET:
            return t
    return when + WINDOW


def ready_at(model: str, when: datetime, error: str, results: Path | None = None) -> datetime:
    if model.startswith("gemini/"):
        local = when.astimezone(PACIFIC)
        return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if results is not None:
        t = groq_ready_at(model, when, error, results)
        if t is not None:
            return t
    m = TRY_AGAIN.search(error)
    return when + (parse_duration(m.group(1)) if m else timedelta(hours=1))


def check(model: str, now: datetime | None = None, results: Path = ROOT / "results") -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    last = last_quota_error(model, results)
    if last is None:
        return True, f"{model}: no daily-quota error recorded"
    t = ready_at(model, *last, results=results)
    if now >= t:
        return True, f"{model}: quota should be back since {t.isoformat(timespec='minutes')}"
    return False, f"{model}: wait until {t.isoformat(timespec='minutes')} (last daily-quota stop {last[0].isoformat(timespec='minutes')})"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    ok, why = check(sys.argv[1])
    print(why)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
