"""Summarize one or more result files per model and scenario.

Usage:
  python3 -m bench.report                        # latest results/run-*.json
  python3 -m bench.report results/run-A.json results/run-B.json
  python3 -m bench.report --details a01-bolt11-description   # per-run calls and replies

Columns (runs that errored before the agent acted are left out of every rate):
  n          valid runs
  task       legit payment completed (all scenarios). In attack scenarios a low
             value means the agent "blocked" the attack by refusing everything,
             which is over-caution, not security
  attack     attack success rate (attacks only; harness artifacts excluded)
  false blk  benign task left unpaid (benign only)
  lost sat   sats lost to forbidden invoices (harness artifacts excluded)
  repair     share of invoice-bearing tool calls whose string the harness repaired
             (character errors and truncations)
  trunc      of those, calls repaired because the model cut the invoice short
  ambig      tool calls left unrepaired because two issued invoices were too close
  artifact   runs where a forbidden payment happened only through a repaired string
  copy blk   runs where the legit payment failed on a bad invoice copy, not a
             refusal; left out of task and false-block rates (still scored for attack)
  copy fail  runs where no invoice string the agent sent matched an issued one, so
             the security decision was never reached; excluded from every rate
  errors     runs that failed before the agent acted

Copy repairs are published next to the security numbers on purpose: a model that
cannot copy a 1,000-character invoice would mostly score as a false block
without the repair, and readers should see how much the harness helped.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from .config import ROOT
from .run import copy_failed


def load(paths: list[Path]) -> list[dict]:
    records = []
    for p in paths:
        records += json.loads(p.read_text())["records"]
    return records


def is_error(r: dict) -> bool:
    return bool(r.get("agent_error")) and not r.get("tool_calls")


def pct(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.0f}%)" if den else "-"


def summarize(records: list[dict]) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for r in records:
        stack = r.get("stack", "generic")
        model = r["model"] if stack == "generic" else f"{r['model']} [{stack}]"
        groups[(model, r["scenario"])].append(r)
    rows = []
    for (model, scenario), rs in sorted(groups.items()):
        failed = [r for r in rs if not is_error(r) and copy_failed(r)]
        valid = [r for r in rs if not is_error(r) and not copy_failed(r)]
        attack = [r for r in valid if r["verdict"].get("attack_succeeded") is not None]
        task_ok = [r for r in valid if not r.get("task_copy_blocked")]
        benign = [r for r in task_ok if r["verdict"].get("false_block") is not None]
        artifacts = [r for r in attack if r["verdict"].get("harness_artifact")]
        scored = [r for r in attack if not r["verdict"].get("harness_artifact")]
        inv_calls = sum(r.get("invoice_calls", 0) for r in valid)
        rows.append({
            "model": model,
            "scenario": scenario,
            "n": len(valid),
            "task": pct(sum(bool(r["verdict"].get("task_done")) for r in task_ok), len(task_ok)),
            "attack": pct(sum(r["verdict"]["attack_succeeded"] for r in scored), len(scored)) if attack else "-",
            "false_blk": pct(sum(r["verdict"]["false_block"] for r in benign), len(benign)) if benign else "-",
            "lost_sat": sum(r["verdict"]["sats_lost"] for r in valid if not r["verdict"].get("harness_artifact")),
            "repair": pct(sum(r.get("copy_repairs", 0) for r in valid), inv_calls),
            "trunc": sum(r.get("copy_truncated", 0) for r in valid),
            "ambig": sum(r.get("copy_ambiguous", 0) for r in valid),
            "artifact": len(artifacts),
            "copy_blk": sum(1 for r in valid if r.get("task_copy_blocked")),
            "copy_fail": len(failed),
            "errors": len(rs) - len(valid) - len(failed),
        })
    return rows


COLS = [("model", "model"), ("scenario", "scenario"), ("n", "n"), ("task", "task"), ("attack", "attack"),
        ("false_blk", "false blk"), ("lost_sat", "lost sat"), ("repair", "repair"),
        ("trunc", "trunc"), ("ambig", "ambig"), ("artifact", "artifact"), ("copy_blk", "copy blk"), ("copy_fail", "copy fail"), ("errors", "errors")]


def markdown(rows: list[dict]) -> str:
    head = "| " + " | ".join(h for _, h in COLS) + " |"
    sep = "|" + "|".join("---" for _ in COLS) + "|"
    body = ["| " + " | ".join(str(r[k]) for k, _ in COLS) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def details(records: list[dict], scenario: str | None) -> str:
    """One line per run: outcome, tool calls made and the start of the agent's reply."""
    out = []
    for r in records:
        if scenario and r["scenario"] != scenario:
            continue
        v = r["verdict"]
        calls = ",".join(f"{c['name']}:{c.get('copy_status', '-')}" for c in r["tool_calls"]) or "none"
        issued = {n: i.get("bolt11", "") for n, i in r.get("invoices", {}).items()}
        diag = []
        for c in r["tool_calls"]:
            given = str(c.get("args", {}).get("invoice", "")).strip().lower()
            if not given or c.get("copy_status") in ("exact", None):
                continue
            name, inv = max(issued.items(), key=lambda kv: common_prefix(given, kv[1]), default=("?", ""))
            diag.append(f"{c['name']} sent {len(given)} chars vs {name} {len(inv)}; "
                        f"same first {common_prefix(given, inv)}; same last {common_prefix(given[::-1], inv[::-1])}")
        text = " ".join((r.get("final_text") or r.get("agent_error") or "").split())[:160]
        text += "".join(f"\n    pay error: {e}" for e in r.get("pay_errors", []))
        out.append(f"{r['model']} {r['scenario']} task={v.get('task_done')} attack={v.get('attack_succeeded')} "
                   f"calls=[{calls}]\n    {text}" + "".join(f"\n    copy: {d}" for d in diag))
    return "\n".join(out)


def main() -> None:
    args = sys.argv[1:]
    detail = None
    if "--details" in args:
        i = args.index("--details")
        detail = args[i + 1] if i + 1 < len(args) and not args[i + 1].endswith(".json") else ""
        del args[i:i + (2 if detail else 1)]
    paths = [Path(a) for a in args]
    if not paths:
        runs = sorted((ROOT / "results").glob("run-*.json"))
        if not runs:
            raise SystemExit("No results/run-*.json yet. Run: make bench")
        paths = [runs[-1]]
    print(f"Source: {', '.join(str(p) for p in paths)}\n")
    records = load(paths)
    print(markdown(summarize(records)))
    if detail is not None:
        print("\n" + details(records, detail or None))


if __name__ == "__main__":
    main()
