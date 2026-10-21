"""Run Lightning Labs' lnget (from lightning-agent-tools) against the lab's aperture proxy.

lnget pays L402 challenges automatically through alice, up to --max-cost sats per
request (defense layer 3: spending cap). Build it with `make lnget`; start the
proxy with `make up-lak`. Regtest only.

Each call gets a fresh HOME, so no L402 token is cached between runs.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from . import lnnodes
from .config import ROOT

BIN = ROOT / "tools" / "bin" / "lnget"
CRED_DIR = ROOT / "tools" / "lnget"
APERTURE = os.environ.get("AGENTJ_APERTURE_URL", "http://127.0.0.1:8085")
MAX_COST_SAT = int(os.environ.get("AGENTJ_LNGET_MAX_COST", "100"))


class LngetError(RuntimeError):
    pass


def prepare(profile: str) -> dict:
    """Copy alice's TLS cert and the profile's scoped macaroon out of the container."""
    if not BIN.exists():
        raise LngetError(f"{BIN} not found. Run: make lnget")
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    mac = lnnodes.ensure_macaroon(profile)
    for src, dst in ((f"{lnnodes.WALLET}:/root/.lnd/tls.cert", CRED_DIR / "tls.cert"),
                     (f"{lnnodes.WALLET}:{mac}", CRED_DIR / f"{profile}.macaroon")):
        proc = subprocess.run(["docker", "compose", "cp", src, str(dst)], cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise LngetError(f"docker compose cp {src} failed: {proc.stderr.strip()[:200]}")
    return {"tls_cert": str(CRED_DIR / "tls.cert"), "macaroon": str(CRED_DIR / f"{profile}.macaroon")}


def _config(creds: dict, max_cost: int) -> str:
    # Both key spellings: the kit's docs note `lnget config init` may write
    # tlscertpath/macaroonpath instead of tls_cert/macaroon.
    return f"""ln:
  mode: lnd
  lnd:
    host: localhost:10009
    network: regtest
    tls_cert: {creds['tls_cert']}
    tlscertpath: {creds['tls_cert']}
    macaroon: {creds['macaroon']}
    macaroonpath: {creds['macaroon']}
l402:
  auto_pay: true
  max_cost_sats: {max_cost}
  max_fee_sats: 10
  payment_timeout: 60s
"""


def fetch(path: str, creds: dict, max_cost: int = MAX_COST_SAT, timeout: int = 120) -> dict:
    """GET APERTURE+path with lnget. Returns what an agent using lnget would see."""
    with tempfile.TemporaryDirectory(prefix="agentj-lnget-") as home:
        (Path(home) / ".lnget").mkdir()
        (Path(home) / ".lnget" / "config.yaml").write_text(_config(creds, max_cost))
        env = {**os.environ, "HOME": home,
               "LNGET_LN_MODE": "lnd", "LNGET_LN_LND_HOST": "localhost:10009", "LNGET_LN_LND_NETWORK": "regtest",
               "LNGET_LN_LND_TLS_CERT": creds["tls_cert"], "LNGET_LN_LND_MACAROON": creds["macaroon"],
               "LNGET_L402_MAX_COST_SATS": str(max_cost)}
        cmd = [str(BIN), "--max-cost", str(max_cost), APERTURE + path]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "error": f"lnget timed out after {timeout}s"}
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    # On errors lnget prints its whole --help before the JSON error; keep only the JSON
    # lines so the agent sees what a script parsing lnget's output would see.
    # Keep "Warning:" lines too: they carry the real reason when the LN backend
    # cannot connect (lnget then falls back to a no-op backend).
    json_err = [ln for ln in err.splitlines() if ln.lstrip().startswith(("{", "Warning:"))]
    if json_err:
        err = "\n".join(json_err)
    meaning = {0: "ok", 1: "general error", 2: "payment exceeds max cost", 3: "payment failed",
               4: "network/connection error"}.get(proc.returncode, "unknown")
    return {"exit_code": proc.returncode, "meaning": meaning, "output": out[-2000:], "stderr": err[-1000:]}
