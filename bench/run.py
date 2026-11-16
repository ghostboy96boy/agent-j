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
from .agent import DEFENSES, LAK_PROFILE, STACKS, make_tool_runner, policy_sha256, run_agent
from .config import DEFAULT_MODELS, ROOT, load_env
from .llm import ChatClient, DailyQuotaError, LLMError

# Bump when a change alters what a run measures (tools the agent sees, turn limit,
# copy-repair rules, scoring). Resume and report only mix runs of the same version.
# 0.2 = commit cc15d2b: fetch tool, 20 turns, truncation repair at 75%, refunds.
HARNESS = "0.2"

SCENARIO_DIR = ROOT / "scenarios"
RESULTS_DIR = ROOT / "results"
MODEL_ERROR_DIR = RESULTS_DIR / "model_errors"
# A repetition whose model keeps emitting unparseable tool calls is tried at most this many
# times; then it counts as executed with model_error and is not tried again (owner rule,
# 2026-11-12). Quota and other invalid runs do not count toward this limit.
MAX_MODEL_ERROR_ATTEMPTS = 3


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


def defense_layer(stack: str, defense: str) -> str:
    """Defense layers a run had: the stack's, plus the prompt policy if enabled."""
    layers = [STACKS[stack][0]] if STACKS[stack][0] != "none" else []
    if defense == "prompt":
        layers.append("prompt-policy")
    return "+".join(layers) or "none"


def run_one(model: str, scenario: dict, do_refund: bool = True, stack: str = "generic",
            defense: str = "none", round_name: str | None = None) -> dict:
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
        "lnd_version": LAB["lnd_version"],
        "stack": stack,
        "defense": defense,
        "defense_layer": defense_layer(stack, defense),
        "policy_sha256": policy_sha256(defense),
        "round": round_name,
        "invoices": {name: {**issued[name], "bolt11": bolt11[name]} for name in issued},
    }
    client = None
    try:
        runner = make_tool_runner(list(bolt11.values()), documents, stack,
                                  l402=scenario.get("l402"), lnget_creds=LNGET_CREDS.get(LAK_PROFILE.get(stack, "")))
        client = ChatClient(model)
        transcript = run_agent(client, task, tool_runner=runner, defense=defense)
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
        record["model_error"] = is_model_error(record)
        if record["model_error"]:
            record["model_error_file"] = save_model_error(record, exc)
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
LAB = {"lnd_version": ""}


def other_bench_running() -> bool:
    import os
    import subprocess
    out = subprocess.run(["pgrep", "-f", "bench.run"], capture_output=True, text=True).stdout.split()
    return any(int(pid) != os.getpid() for pid in out if pid.isdigit())


def is_model_error(record: dict) -> bool:
    """The model itself produced a tool call the provider could not parse (HTTP 400 tool_use_failed).

    That is a model failure, not an outage, so it is reported apart from invalid runs. Older
    records without the flag are recognized from the stored error text.
    """
    if "model_error" in record:
        return bool(record["model_error"])
    err = str(record.get("agent_error") or "")
    return bool(record.get("aborted")) and "HTTP 400" in err and "tool_use_failed" in err


def save_model_error(record: dict, exc: Exception) -> str:
    """Keep the provider's raw response for a model error (Groq puts the model's unparseable
    output in error.failed_generation) in results/model_errors/<utc>-<run_tag>.json. Only the
    response body is stored: no request, no headers, no keys."""
    MODEL_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    raw = getattr(exc, "raw", None) or b""
    text = raw.decode(errors="replace")
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = MODEL_ERROR_DIR / f"{stamp}-{record['run_tag']}.json"
    path.write_text(json.dumps({key: record.get(key) for key in
                                ("model", "scenario", "defense", "stack", "round", "run_tag", "harness")}
                               | {"http_status": getattr(exc, "status", None), "provider_response": body},
                               indent=2, ensure_ascii=False) + "\n")
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def is_invalid(record: dict) -> bool:
    """Run that cannot be scored: the model call failed or the run was cut short."""
    return bool(record.get("aborted")) or (bool(record.get("agent_error")) and not record.get("tool_calls"))


def cell_progress(paths: list[Path], round_name: str | None = None) -> dict[tuple, dict]:
    """(model, stack, defense, scenario) -> {"valid", "exhausted", "attempts"} replayed in run order.

    Each repetition ends with a valid run, or after MAX_MODEL_ERROR_ATTEMPTS model errors
    ("executed with model_error"). Other invalid runs (quota, outages) do not count as an attempt.
    "attempts" lists the model errors of each repetition, in order. Files are read in name
    (start time) order and records in file order, which is the order the runs were made.
    """
    records = [r for p in sorted(paths, key=lambda x: x.name) for r in json.loads(p.read_text())["records"]]
    return progress_of(records, round_name)


def progress_of(records: list[dict], round_name: str | None = None) -> dict[tuple, dict]:
    """cell_progress over records already loaded, in run order."""
    cells: dict[tuple, dict] = {}
    for r in records:
        if round_name is not None and r.get("round") != round_name:
            continue
        if harness_of(r) != HARNESS:
            continue
        key = (r["model"], r.get("stack", "generic"), r.get("defense", "none"), r["scenario"])
        c = cells.setdefault(key, {"valid": 0, "exhausted": 0, "attempts": [0], "current": 0})
        if is_model_error(r):
            c["current"] += 1
            c["attempts"][-1] = c["current"]
            if c["current"] >= MAX_MODEL_ERROR_ATTEMPTS:
                c["exhausted"] += 1
                c["current"] = 0
                c["attempts"].append(0)
        elif not is_invalid(r):
            c["valid"] += 1
            c["current"] = 0
            c["attempts"].append(0)
    for c in cells.values():
        del c["current"]
        if c["attempts"][-1] == 0:
            c["attempts"].pop()
    return cells


def prior_model_errors(records: list[dict]) -> dict[int, int]:
    """id(record) -> model errors that preceded it in the same repetition, for each valid run.

    Derived from run order like progress_of, so no stored record changes. 0 means the
    repetition was valid at the first scored attempt; quota and other invalid runs in
    between are ignored.
    """
    current: dict[tuple, int] = {}
    out: dict[int, int] = {}
    for r in records:
        if harness_of(r) != HARNESS:
            continue
        key = (r.get("round"), r["model"], r.get("stack", "generic"), r.get("defense", "none"), r["scenario"])
        if is_model_error(r):
            current[key] = current.get(key, 0) + 1
            if current[key] >= MAX_MODEL_ERROR_ATTEMPTS:
                current[key] = 0
        elif not is_invalid(r):
            out[id(r)] = current.get(key, 0)
            current[key] = 0
    return out


def done_counts(paths: list[Path], round_name: str | None = None) -> dict[tuple, int]:
    """(model, stack, defense, scenario) -> repetitions already executed in these result files:
    valid runs plus repetitions closed after MAX_MODEL_ERROR_ATTEMPTS model errors.

    With round_name, only runs tagged with that round count, so a new round is not
    filled up with older runs of the same cell.
    """
    return {k: c["valid"] + c["exhausted"] for k, c in cell_progress(paths, round_name).items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent J benchmark runner (regtest only)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--scenarios", nargs="+")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--stack", default="generic", choices=sorted(STACKS),
                    help="payment stack the agent uses (see bench/README.md)")
    ap.add_argument("--defense", default="none", choices=sorted(DEFENSES),
                    help="none: base system prompt; prompt: add the spending policy in bench/policies/prompt_policy.txt")
    ap.add_argument("--round", dest="round_name", metavar="NAME",
                    help="tag every record with this round; with --resume, count only runs of this round")
    ap.add_argument("--no-refund", action="store_true", help="do not return received sats to alice after each run")
    ap.add_argument("--resume", nargs="*", metavar="RESULTS",
                    help="top up to --repeat valid runs per cell, counting current-harness runs in these files "
                         "(no files given: every results/run-*.json)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any benign task is not completed (smoke test)")
    args = ap.parse_args()

    load_env()
    scenarios = load_scenarios(args.scenarios)
    LAB["lnd_version"] = lnnodes.lnd_version()
    print(f"lab: alice lnd {LAB['lnd_version'] or 'unknown'}", flush=True)
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
        already = done_counts(paths, args.round_name)
        print(f"resume: counting valid runs in {len(paths)} file(s)", flush=True)
    print(f"defense: {args.defense} (layer {defense_layer(args.stack, args.defense)})"
          + (f", round {args.round_name}" if args.round_name else ""), flush=True)
    todo = {(m, sc["id"]): max(0, args.repeat - already.get((m, args.stack, args.defense, sc["id"]), 0))
            for m in args.models for sc in scenarios}
    total = sum(todo.values())
    print(f"{total} runs -> {out.relative_to(ROOT)} (saved after every run)", flush=True)

    def save() -> None:
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"created": stamp, "stack": args.stack, "defense": args.defense,
                                   "defense_layer": defense_layer(args.stack, args.defense), "round": args.round_name,
                                   "complete": len(records) == total, "records": records}, indent=2))
        tmp.replace(out)
    out_of_quota: list[str] = []
    for model in args.models:
        quota_hit = False
        for sc in scenarios:
            if quota_hit:
                break
            start = already.get((model, args.stack, args.defense, sc["id"]), 0)
            for i in range(start, start + todo[(model, sc["id"])]):
                rec = run_one(model, sc, do_refund=not args.no_refund, stack=args.stack,
                              defense=args.defense, round_name=args.round_name)
                records.append(rec)
                save()
                v = rec["verdict"]
                if rec.get("quota_exhausted"):
                    quota_hit = True
                    out_of_quota.append(model)
                    print(f"[{len(records)}/{total}] {model}: daily quota reached; skipping its remaining runs. "
                          f"Continue later with --resume.", flush=True)
                    break
                if is_model_error(rec):
                    outcome = "MODEL ERROR"
                elif is_invalid(rec):
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
                tag += f" /{args.defense}"
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
              f"Next day: python3 -m bench.run --resume --repeat {args.repeat} --defense {args.defense}"
              + (f" --round {args.round_name}" if args.round_name else "") + f" --models {' '.join(args.models)}")
    errors = sum(1 for r in records if is_invalid(r) and not r.get("quota_exhausted") and not is_model_error(r))
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
