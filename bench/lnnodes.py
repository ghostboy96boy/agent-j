"""Thin wrappers around the regtest Lightning nodes (via docker compose exec).

alice (LND) is the agent's wallet. bob (LND) and carol (Core Lightning) issue
invoices for merchants and attackers. Regtest only.
"""
from __future__ import annotations

import json
import subprocess

from .config import ROOT

LND_NODES = {"alice", "bob"}
CLN_NODES = {"carol"}


class NodeError(RuntimeError):
    pass


def _exec(node: str, args: list[str], timeout: int = 90) -> str:
    if node in LND_NODES:
        cmd = ["docker", "compose", "exec", "-T", node, "lncli", "--network=regtest", *args]
    elif node in CLN_NODES:
        cmd = ["docker", "compose", "exec", "-T", node, "lightning-cli", "--network=regtest", *args]
    else:
        raise NodeError(f"Unknown node {node}")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise NodeError((proc.stderr or proc.stdout).strip()[:500])
    return proc.stdout


def _json(node: str, args: list[str], timeout: int = 90) -> dict:
    out = _exec(node, args, timeout)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise NodeError(f"Non-JSON output from {node}: {out[:300]}") from exc


# ---- invoices (issued by merchants / attackers) ----

def create_invoice(node: str, amount_sat: int, description: str, label: str) -> dict:
    """Create an invoice on bob or carol. Returns {bolt11, ref} where ref locates it later."""
    if node in CLN_NODES:
        d = _json(node, ["invoice", str(amount_sat * 1000), label, description])
        return {"bolt11": d["bolt11"], "ref": label}
    if node in LND_NODES:
        d = _json(node, ["addinvoice", "--amt", str(amount_sat), "--memo", description])
        return {"bolt11": d["payment_request"], "ref": d["r_hash"]}
    raise NodeError(f"Unknown node {node}")


def invoice_paid_sat(node: str, ref: str) -> int:
    """Sats actually received for an invoice, read from the receiving node."""
    if node in CLN_NODES:
        d = _json(node, ["listinvoices", ref])
        inv = (d.get("invoices") or [{}])[0]
        if inv.get("status") != "paid":
            return 0
        msat = inv.get("amount_received_msat", 0)
        if isinstance(msat, str):  # older CLN encodes as "1000msat"
            msat = int(msat.rstrip("msat"))
        return int(msat) // 1000
    if node in LND_NODES:
        d = _json(node, ["lookupinvoice", ref])
        return int(d.get("amt_paid_sat", 0)) if d.get("state") == "SETTLED" else 0
    raise NodeError(f"Unknown node {node}")


# ---- the agent's wallet (alice) ----

WALLET = "alice"


def decode_invoice(bolt11: str) -> dict:
    d = _json(WALLET, ["decodepayreq", bolt11])
    return {
        "amount_sat": int(d.get("num_satoshis", 0)),
        "description": d.get("description", ""),
        "destination": d.get("destination", ""),
        "expiry_seconds": int(d.get("expiry", 0)),
    }


def pay_invoice(bolt11: str) -> dict:
    out = _exec(WALLET, ["payinvoice", "--force", "--json", "--timeout", "60s", "--pay_req", bolt11], timeout=120)
    # --json prints one JSON object per payment update; the last one is final.
    last = None
    for chunk in out.replace("}\n{", "}\x00{").split("\x00"):
        try:
            last = json.loads(chunk)
        except json.JSONDecodeError:
            continue
    if not last:
        return {"status": "UNKNOWN", "raw": out[-300:]}
    return {
        "status": last.get("status", "UNKNOWN"),
        "amount_sat": int(last.get("value_sat", 0) or 0),
        "fee_sat": int(last.get("fee_sat", 0) or 0),
        "failure_reason": last.get("failure_reason", ""),
    }


def wallet_balance() -> dict:
    d = _json(WALLET, ["channelbalance"])
    local = d.get("local_balance", {}).get("sat", d.get("balance", 0))
    return {"spendable_sat": int(local)}
