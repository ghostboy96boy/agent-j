"""Run counts for the phase 0 rounds, without results:  python3 -m bench.status [--write]

Prints valid / model_error / invalid runs per round x model x defense. With --write it also writes
results/STATUS.md (date, time and the same counts; no rates, no sats), which may be pushed while
the rounds are still running.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import ROOT
from .run import HARNESS, harness_of, is_model_error

ROUNDS = ("phase0-r1", "phase0-pilot-gemini")
GROQ = ("groq/openai/gpt-oss-120b", "groq/qwen/qwen3.8-27b")
TARGET = 13 * 2 * 3  # 13 scenarios x 2 defenses x 3 repeats


def counts(results: Path = ROOT / "results") -> Counter:
    c: Counter = Counter()
    for path in sorted(results.glob("run-*.json")):
        for r in json.loads(path.read_text()).get("records", []):
            if r.get("round") not in ROUNDS or harness_of(r) != HARNESS:
                continue
            kind = "model_error" if is_model_error(r) else ("invalid" if r.get("agent_error") else "valid")
            c[(r["round"], r["model"], r.get("defense", "none"), kind)] += 1
    return c


def valid_total(c: Counter, model: str, round_name: str = "phase0-r1") -> int:
    return sum(v for (rn, m, _, kind), v in c.items() if rn == round_name and m == model and kind == "valid")


def groq_done(c: Counter) -> bool:
    return all(valid_total(c, m) >= TARGET for m in GROQ)


def table(c: Counter) -> str:
    rows = sorted({(rn, m, d) for rn, m, d, _ in c})
    lines = ["| round | model | defense | valid | model error | invalid |", "|---|---|---|---|---|---|"]
    for rn, m, d in rows:
        lines.append(f"| {rn} | {m} | {d} | {c[(rn, m, d, 'valid')]} | {c[(rn, m, d, 'model_error')]} "
                     f"| {c[(rn, m, d, 'invalid')]} |")
    return "\n".join(lines)


def status_markdown(c: Counter, now: datetime) -> str:
    groq = ", ".join(f"{m.split('/')[-1]} {valid_total(c, m)}/{TARGET}" for m in GROQ)
    return (f"# Phase 0 run status\n\nUpdated {now.isoformat(timespec='minutes')}. Run counts only; results "
            f"are published after the cutoff (2026-11-18 00:00 BRT).\n\nGroq phase0-r1 valid runs: {groq}.\n\n"
            + table(c) + "\n")


def main() -> None:
    c = counts()
    print(table(c))
    if "--write" in sys.argv[1:]:
        (ROOT / "results" / "STATUS.md").write_text(status_markdown(c, datetime.now().astimezone()))
        print("\nWrote results/STATUS.md")
    if "--groq-done" in sys.argv[1:]:
        sys.exit(0 if groq_done(c) else 1)


if __name__ == "__main__":
    main()
