"""Run scenarios against models and write results/<run id>.json.

Usage:
  python3 -m bench.run                         # all scenarios x default models
  python3 -m bench.run --models groq/openai/gpt-oss-120b --scenarios b01-coffee
  python3 -m bench.run --repeat 3
"""
from __future__ import annotations

import argparse
import base64
import json
import string
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import judge, lnnodes
from .agent import LAK_PROFILE, STACKS, make_tool_runner, run_agent
from .config import DEFAULT_MODELS, ROOT, load_env
from .llm import ChatClient, DailyQuotaError, LLMError

# Bump when a change alters what a run measures (tools the agent sees, turn limit,
# copy-repair rules, scoring). Resume and report only mix runs of the same version.
# 0.2 = commit cc15d2b: fetch tool, 20 turns, truncation repair at 75%, refunds.
HARNESS = "0.2"

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


class _Renderer(string.Formatter):
    """str.format with scenario fragments and a base64 conversion: {name!b}.

    Fragments are rendered lazily, so a fragment may itself embed invoices
    issued earlier in the scenario.
    """

    def __init__(self, values: dict, fragments: dict):
        self.values, self.fragments = values, fragments

    def get_value(self, key, args, kwargs):
        if key in self.values:
            return self.values[key]
        if key in self.fragments:
            return self.format(self.fragments[key])
        raise KeyError(f"unknown template field '{key}'")

    def convert_field(self, value, conversion):
        if conversion == "b":
            return base64.b64encode(str(value).encode()).decode()
        return super().convert_field(value, conversion)


def render(template: str, bolt11: dict, scenario: dict) -> str:
    return _Renderer(bolt11, scenario.get("fragments", {})).format(template)


def issue_invoices(scenario: dict, run_tag: str) -> tuple[dict, dict]:
    """Create the scenario's invoices in order; later descriptions may embed earlier invoices."""
    issued, bolt11 = {}, {}
    for inv in scenario["invoices"]:
        desc = render(inv["description"], bolt11, scenario)
        label = f"{scenario['id']}-{inv['name']}-{run_tag}"
        made = lnnodes.create_invoice(inv["node"], inv["amount_sat"], desc, label)
        issued[inv["name"]] = {"node": inv["node"], "ref": made["ref"], "amount_sat": inv["amount_sat"]}
        bolt11[inv["name"]] = made["bolt11"]
    return issued, bolt11


def copy_failed(record: dict) -> bool:
    """True when the agent tried to use invoices but never got a usable string through.

    Such a run never reached the security decision (the model could not even decode
    the invoice), so it is excluded from task, attack and false-block rates.
    """
    calls = [c for c in record.get("tool_calls", []) if c.get("copy_status")]
    return bool(calls) and not any(c["copy_status"] in ("exact", "repaired", "truncated_repaired") for c in calls)


def pay_paths(tool_calls: list[dict], bolt11: dict[str, str]) -> dict[str, set]:
    """For each issued invoice, the copy statuses of the pay calls that targeted it."""
    by_string = {v: k for k, v in bolt11.items()}
    paths: dict[str, set] = {}
    for c in tool_calls:
        name = by_string.get(c.get("invoice_used") or "")
        if c.get("name") == "pay_invoice" and name:
            paths.setdefault(name, set()).add(c["copy_status"])
    return paths


def task_copy_blocked(record: dict, scenario: dict) -> bool:
    """The legit payment failed because a pay call carried an unusable invoice string."""
    if not scenario.get("must_pay") or record["verdict"]["task_done"]:
        return False
    return any(c.get("name") == "pay_invoice" and c.get("copy_status") in ("no_match", "ambiguous")
               for c in record.get("tool_calls", []))


def refund(issued: dict, paid: dict) -> list[str]:
    """Return everything the receiving nodes got back to the agent's wallet (after judging)."""
    problems = []
    for name, sat in paid.items():
        if sat > 0:
            try:
                lnnodes.return_to_wallet(issued[name]["node"], sat)
            except lnnodes.NodeError as exc:
                problems.append(f"{name}: {str(exc)[:120]}")
    return problems


def run_one(model: str, scenario: dict, do_refund: bool = True, stack: str = "generic") -> dict:
    run_tag = uuid.uuid4().hex[:8]
    issued, bolt11 = issue_invoices(scenario, run_tag)
    task = render(scenario["task"], bolt11, scenario)
    documents = {url: render(body, bolt11, scenario) for url, body in scenario.get("documents", {}).items()}
    started = time.time()
    since = int(started) - 1
    record = {
        "model": model,
        "scenario": scenario["id"],
        "category": scenario["category"],
        "run_tag": run_tag,
        "harness": HARNESS,
        "stack": stack,
        "defense_layer": STACKS[stack][0],
        "invoices": {name: {**issued[name], "bolt11": bolt11[name]} for name in issued},
    }
    client = None
    try:
        runner = make_tool_runner(list(bolt11.values()), documents, stack,
                                  l402=scenario.get("l402"), lnget_creds=LNGET_CREDS.get(LAK_PROFILE.get(stack, "")))
        client = ChatClient(model)
        transcript = run_agent(client, task, tool_runner=runner)
        record.update(
            tool_calls=transcript.tool_calls,
            final_text=transcript.final_text,
            agent_error=transcript.error,
        )
    except LLMError as exc:
        # The model call failed. The run is invalid even if the agent already acted
        # (it never got to finish), so it is marked aborted and left out of every rate.
        partial = getattr(exc, "transcript", None)
        record.update(tool_calls=partial.tool_calls if partial else [], final_text="",
                      agent_error=str(exc), aborted=True, quota_exhausted=isinstance(exc, DailyQuotaError))
    record["tokens"] = getattr(client, "tokens", 0)
    time.sleep(2)  # let the last HTLCs settle before reading the network
    service = {}
    if stack == "lak-lnget":
        refs = {inv["ref"] for inv in issued.values() if inv["node"] == "bob"}
        service = lnnodes.unissued_settled("bob", since, refs)
    record["service_payments"] = service
    record["verdict"] = judge.score(scenario, issued, lnnodes.invoice_paid_sat, pay_paths(record["tool_calls"], bolt11),
                                    service_paid_sat=sum(service.values()))
    calls = [c for c in record["tool_calls"] if c.get("copy_status")]
    record["invoice_calls"] = len(calls)
    record["copy_repairs"] = sum(1 for c in calls if c.get("copy_repaired"))
    record["copy_ambiguous"] = sum(1 for c in calls if c.get("copy_ambiguous"))
    record["copy_truncated"] = sum(1 for c in calls if c.get("copy_truncated"))
    record["copy_failed"] = copy_failed(record)
    record["task_copy_blocked"] = task_copy_blocked(record, scenario)
    # Payment tool errors (bad flag, missing macaroon permission, routing) would otherwise
    # look like a refusal; keep them visible.
    record["pay_errors"] = sorted({str(c["result"].get("error"))[:200] for c in record["tool_calls"]
                                   if c.get("name") == "pay_invoice" and isinstance(c.get("result"), dict)
                                   and c["result"].get("error")})
    record["refund_problems"] = refund(issued, record["verdict"]["paid_sat"]) if do_refund else []
    if do_refund and service:
        try:
            lnnodes.return_to_wallet("bob", sum(service.values()))
        except lnnodes.NodeError as exc:
            record["refund_problems"].append(f"service: {str(exc)[:120]}")
    record["seconds"] = round(time.time() - started, 1)
    return record


def harness_of(record: dict) -> str:
    """Harness version of a record; 0.2 records from before the stamp are recognized by their refund field."""
    return record.get("harness") or ("0.2" if "refund_problems" in record else "legacy")


LNGET_CREDS: dict[str, dict] = {}


def other_bench_running() -> bool:
    import os
    import subprocess
    out = subprocess.run(["pgrep", "-f", "bench.run"], capture_output=True, text=True).stdout.split()
    return any(int(pid) != os.getpid() for pid in out if pid.isdigit())


def is_invalid(record: dict) -> bool:
    """Run that cannot be scored: the model call failed or the run was cut short."""
    return bool(record.get("aborted")) or (bool(record.get("agent_error")) and not record.get("tool_calls"))


def done_counts(paths: list[Path]) -> dict[tuple, int]:
    """(model, stack, scenario) -> number of valid runs already in these result files."""
    counts: dict[tuple, int] = {}
    for p in paths:
        for r in json.loads(p.read_text())["records"]:
            if not is_invalid(r) and harness_of(r) == HARNESS:
                key = (r["model"], r.get("stack", "generic"), r["scenario"])
                counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent J benchmark runner (regtest only)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--scenarios", nargs="+")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--stack", default="generic", choices=sorted(STACKS),
                    help="payment stack the agent uses (see bench/README.md)")
    ap.add_argument("--no-refund", action="store_true", help="do not return received sats to alice after each run")
    ap.add_argument("--resume", nargs="*", metavar="RESULTS",
                    help="top up to --repeat valid runs per cell, counting current-harness runs in these files "
                         "(no files given: every results/run-*.json)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any benign task is not completed (smoke test)")
    args = ap.parse_args()

    load_env()
    scenarios = load_scenarios(args.scenarios)
    if args.stack in LAK_PROFILE:
        print(f"stack {args.stack}: macaroon {lnnodes.ensure_macaroon(LAK_PROFILE[args.stack])}")
    if args.stack == "lak-lnget":
        if other_bench_running():
            raise SystemExit("lak-lnget attributes bob's L402 invoices by time window; stop other benches first")
        from . import lnget
        LNGET_CREDS[LAK_PROFILE[args.stack]] = lnget.prepare(LAK_PROFILE[args.stack])
        print(f"lnget: {lnget.BIN}, max-cost {lnget.MAX_COST_SAT} sat, proxy {lnget.APERTURE}", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records = []
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"run-{stamp}.json"
    already: dict[tuple, int] = {}
    if args.resume is not None:
        paths = [Path(x) for x in args.resume] or sorted(RESULTS_DIR.glob("run-*.json"))
        already = done_counts(paths)
        print(f"resume: counting valid runs in {len(paths)} file(s)", flush=True)
    todo = {(m, sc["id"]): max(0, args.repeat - already.get((m, args.stack, sc["id"]), 0))
            for m in args.models for sc in scenarios}
    total = sum(todo.values())
    print(f"{total} runs -> {out.relative_to(ROOT)} (saved after every run)", flush=True)

    def save() -> None:
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"created": stamp, "stack": args.stack, "defense_layer": STACKS[args.stack][0],
                                   "complete": len(records) == total, "records": records}, indent=2))
        tmp.replace(out)
    out_of_quota: list[str] = []
    for model in args.models:
        quota_hit = False
        for sc in scenarios:
            if quota_hit:
                break
            start = already.get((model, args.stack, sc["id"]), 0)
            for i in range(start, start + todo[(model, sc["id"])]):
                rec = run_one(model, sc, do_refund=not args.no_refund, stack=args.stack)
                records.append(rec)
                save()
                v = rec["verdict"]
                if rec.get("quota_exhausted"):
                    quota_hit = True
                    out_of_quota.append(model)
                    print(f"[{len(records)}/{total}] {model}: daily quota reached; skipping its remaining runs. "
                          f"Continue later with --resume.", flush=True)
                    break
                if is_invalid(rec):
                    outcome = "ERROR"
                elif rec["copy_failed"]:
                    outcome = "COPY FAILED"
                elif v["attack_succeeded"] is not None:
                    outcome = "ATTACK SUCCEEDED" if v["attack_succeeded"] else "attack blocked"
                    if v.get("harness_artifact"):
                        outcome = "HARNESS ARTIFACT"
                else:
                    outcome = "task done" if v["task_done"] else "FALSE BLOCK"
                fix = f"  ({rec['copy_repairs']}/{rec['invoice_calls']} copy repair)" if rec["copy_repairs"] else ""
                if rec["copy_ambiguous"]:
                    fix += f"  ({rec['copy_ambiguous']} ambiguous copy)"
                tag = model if args.stack == "generic" else f"{model} [{args.stack}]"
                print(f"[{len(records)}/{total}] {tag:34s} {sc['id']:24s} #{i + 1}  {outcome:16s} "
                      f"lost={v['sats_lost']} sat  {rec['seconds']}s  {rec['tokens']} tok{fix}", flush=True)
                if rec["agent_error"]:
                    print(f"    error: {rec['agent_error'][:400]}", flush=True)
                if rec["task_copy_blocked"]:
                    print("    note: legit payment failed on a bad invoice copy (not a refusal)", flush=True)
                for err in rec["pay_errors"]:
                    print(f"    pay error: {err}", flush=True)
                for prob in rec["refund_problems"]:
                    print(f"    refund warning: {prob}", flush=True)

    print(f"\nSaved {out.relative_to(ROOT)}  (summary: python3 -m bench.report {out.relative_to(ROOT)})")
    toks = [r["tokens"] for r in records if not is_invalid(r) and r.get("tokens")]
    if toks:
        print(f"tokens per valid run: mean {sum(toks) // len(toks)}, max {max(toks)}")
    if out_of_quota:
        print(f"daily quota reached for: {', '.join(out_of_quota)}. "
              f"Next day: python3 -m bench.run --resume --repeat {args.repeat} --models {' '.join(args.models)}")
    errors = sum(1 for r in records if is_invalid(r) and not r.get("quota_exhausted"))
    if errors:
        print(f"{errors} run(s) failed before the agent acted; see errors above.")
        sys.exit(1)
    if args.strict:
        missed = [r for r in records if r["category"] == "benign" and not r["verdict"]["task_done"]]
        if missed:
            print(f"{len(missed)} benign task(s) not completed.")
            sys.exit(1)


if __name__ == "__main__":
    main()
