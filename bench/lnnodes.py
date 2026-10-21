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


def _exec(node: str, args: list[str], timeout: int = 90, macaroon: str | None = None) -> str:
    if node in LND_NODES:
        mac = [f"--macaroonpath={macaroon}"] if macaroon else []
        cmd = ["docker", "compose", "exec", "-T", node, "lncli", "--network=regtest", *mac, *args]
    elif node in CLN_NODES:
        cmd = ["docker", "compose", "exec", "-T", node, "lightning-cli", "--network=regtest", *args]
    else:
        raise NodeError(f"Unknown node {node}")
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise NodeError((proc.stderr or proc.stdout).strip()[:500])
    return proc.stdout


def _json(node: str, args: list[str], timeout: int = 90, macaroon: str | None = None) -> dict:
    out = _exec(node, args, timeout, macaroon)
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


# ---- harness housekeeping: keep the agent's balance constant between runs ----

def return_to_wallet(node: str, amount_sat: int) -> None:
    """Send sats a merchant/attacker node received back to alice.

    Runs after the judge has scored the run, so it never affects a verdict. It keeps
    every run starting from the same wallet balance and stops channels from draining
    over a long benchmark.
    """
    if amount_sat <= 0:
        return
    inv = _json(WALLET, ["addinvoice", "--amt", str(amount_sat), "--memo", "agent-j harness refund"])
    if node in CLN_NODES:
        _json(node, ["pay", inv["payment_request"]], timeout=120)
    elif node in LND_NODES:
        _exec(node, ["payinvoice", "--force", "--json", "--timeout", "60s", "--pay_req", inv["payment_request"]], timeout=120)
    else:
        raise NodeError(f"Unknown node {node}")


# ---- Lightning Agent Kit stack ("lak-lncli") ----
#
# Mirrors lightninglabs/lightning-agent-tools: the lnd skill pays with
# `lncli sendpayment --pay_req=<bolt11>`, and the macaroon-bakery "pay-only"
# preset grants SendPaymentSync, DecodePayReq and GetInfo. The agent's calls run
# with that scoped macaroon instead of admin (defense layer 4: scoped credentials).

MACAROON_DIR = "/root/.lnd/agentj"
LAK_PROFILES = {
    # Exact permissions of the kit's pay-only preset (docs/security.md).
    "pay-only": [
        "uri:/lnrpc.Lightning/SendPaymentSync",
        "uri:/lnrpc.Lightning/DecodePayReq",
        "uri:/lnrpc.Lightning/GetInfo",
    ],
    # Variant that also allows the router RPCs current lncli versions use for
    # sendpayment; used to tell a permission gap apart from a security block.
    # What lnget (lndclient v0.20) needs to connect and pay: version check, node info,
    # decode and the router send/track calls.
    "lnget-min": [
        "uri:/verrpc.Versioner/GetVersion",
        "uri:/lnrpc.Lightning/GetInfo",
        "uri:/lnrpc.Lightning/DecodePayReq",
        "uri:/routerrpc.Router/SendPaymentV2",
        "uri:/routerrpc.Router/TrackPaymentV2",
    ],
    "pay-only-v2": [
        "uri:/lnrpc.Lightning/SendPaymentSync",
        "uri:/routerrpc.Router/SendPaymentV2",
        "uri:/routerrpc.Router/TrackPaymentV2",
        "uri:/lnrpc.Lightning/DecodePayReq",
        "uri:/lnrpc.Lightning/GetInfo",
    ],
}


def macaroon_path(profile: str) -> str:
    return f"{MACAROON_DIR}/{profile}.macaroon"


def ensure_macaroon(profile: str) -> str:
    """Bake the profile's macaroon on alice once (with admin) and return its path."""
    path = macaroon_path(profile)
    check = subprocess.run(["docker", "compose", "exec", "-T", WALLET, "test", "-f", path],
                           cwd=ROOT, capture_output=True, text=True)
    if check.returncode != 0:
        subprocess.run(["docker", "compose", "exec", "-T", WALLET, "mkdir", "-p", MACAROON_DIR],
                       cwd=ROOT, capture_output=True, text=True, check=False)
        _exec(WALLET, ["bakemacaroon", "--save_to", path, *LAK_PROFILES[profile]])
    return path


def lak_decode_invoice(bolt11: str, profile: str) -> dict:
    d = _json(WALLET, ["decodepayreq", bolt11], macaroon=macaroon_path(profile))
    return {
        "amount_sat": int(d.get("num_satoshis", 0)),
        "description": d.get("description", ""),
        "destination": d.get("destination", ""),
        "expiry_seconds": int(d.get("expiry", 0)),
    }


def lak_sendpayment(bolt11: str, profile: str) -> dict:
    """The kit's payment command: lncli sendpayment --pay_req=<bolt11>, with the scoped macaroon."""
    out = _exec(WALLET, ["sendpayment", "--force", "--json", f"--pay_req={bolt11}"],
                timeout=120, macaroon=macaroon_path(profile))
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


def lak_wallet_balance(profile: str) -> dict:
    """ChannelBalance is not in the pay-only preset, so this is expected to be refused."""
    d = _json(WALLET, ["channelbalance"], macaroon=macaroon_path(profile))
    local = d.get("local_balance", {}).get("sat", d.get("balance", 0))
    return {"spendable_sat": int(local)}


def unissued_settled(node: str, since: int, exclude_refs: set[str]) -> dict[str, int]:
    """Settled LND invoices created on `node` at or after `since` that the scenario did not issue.

    Used for aperture, which creates its own L402 invoices on bob. Only meaningful when
    no other benchmark is creating invoices on the same node at the same time.
    """
    d = _json(node, ["listinvoices", "--max_invoices", "500"])
    found = {}
    for inv in d.get("invoices", []):
        if inv.get("state") != "SETTLED" or int(inv.get("creation_date", 0)) < since:
            continue
        if inv.get("r_hash") in exclude_refs:
            continue
        found[inv["r_hash"]] = int(inv.get("amt_paid_sat", 0))
    return found
