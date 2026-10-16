"""Run scenarios against models and write results/<run id>.json.

Usage:
  python3 -m bench.run                         # all scenarios x default models
  python3 -m bench.run --models groq/openai/gpt-oss-120b --scenarios b01-coffee
  python3 -m bench.run --repeat 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import judge, lnnodes
from .agent import run_agent
from .config import DEFAULT_MODELS, ROOT, load_env
from .llm import ChatClient, LLMError

SCENARIO_DIR = ROOT / "scenarios"
RESULTS_DIR = ROOT / "results"


def load_scenarios(ids: list[str] | None) -> list[dict]:
    found = []
    for path in sorted(SCENARIO_DIR.rglob("*.json")):
        sc = json.loads(path.read_text())
        if not ids or sc["id"] in ids:
            found.append(sc)
    if ids and len(found) != len(ids):
        missing = set(ids) - {s["id"] for s in found}
        raise SystemExit(f"Scenario(s) not found: {', '.join(sorted(missing))}")
    return found


def issue_invoices(scenario: dict, run_tag: str) -> tuple[dict, dict]:
    """Create the scenario's invoices in order; later descriptions may embed earlier invoices."""
    issued, bolt11 = {}, {}
    for inv in scenario["invoices"]:
        desc = inv["description"].format(**bolt11)
        label = f"{scenario['id']}-{inv['name']}-{run_tag}"
        made = lnnodes.create_invoice(inv["node"], inv["amount_sat"], desc, label)
        issued[inv["name"]] = {"node": inv["node"], "ref": made["ref"], "amount_sat": inv["amount_sat"]}
        bolt11[inv["name"]] = made["bolt11"]
    return issued, bolt11


def run_one(model: str, scenario: dict) -> dict:
    run_tag = uuid.uuid4().hex[:8]
    issued, bolt11 = issue_invoices(scenario, run_tag)
    task = scenario["task"].format(**bolt11)
    started = time.time()
    record = {"model": model, "scenario": scenario["id"], "category": scenario["category"], "run_tag": run_tag}
    try:
        transcript = run_agent(ChatClient(model), task)
        record.update(
            tool_calls=transcript.tool_calls,
            final_text=transcript.final_text,
            agent_error=transcript.error,
        )
    except LLMError as exc:
        record.update(tool_calls=[], final_text="", agent_error=str(exc))
    time.sleep(2)  # let the last HTLCs settle before reading the network
    record["verdict"] = judge.score(scenario, issued, lnnodes.invoice_paid_sat)
    record["seconds"] = round(time.time() - started, 1)
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent J benchmark runner (regtest only)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--scenarios", nargs="+")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    load_env()
    scenarios = load_scenarios(args.scenarios)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records = []
    for model in args.models:
        for sc in scenarios:
            for i in range(args.repeat):
                rec = run_one(model, sc)
                records.append(rec)
                v = rec["verdict"]
                if rec["agent_error"] and not rec["tool_calls"]:
                    outcome = "ERROR"
                elif v["attack_succeeded"] is not None:
                    outcome = "ATTACK SUCCEEDED" if v["attack_succeeded"] else "attack blocked"
                else:
                    outcome = "task done" if v["task_done"] else "FALSE BLOCK"
                print(f"{model:34s} {sc['id']:24s} #{i + 1}  {outcome:16s} lost={v['sats_lost']} sat")
                if rec["agent_error"]:
                    print(f"    error: {rec['agent_error'][:400]}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"run-{stamp}.json"
    out.write_text(json.dumps({"created": stamp, "defense_layer": "none", "records": records}, indent=2))
    print(f"\nSaved {out.relative_to(ROOT)}")
    errors = sum(1 for r in records if r["agent_error"] and not r["tool_calls"])
    if errors:
        print(f"{errors} run(s) failed before the agent acted; see errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
