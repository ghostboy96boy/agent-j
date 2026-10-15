#!/usr/bin/env bash
# Shared helpers for the Agent J regtest lab.
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "Missing .env. Run: cp .env.example .env" >&2
  exit 1
fi
# shellcheck disable=SC1091
source .env

DC="docker compose"

btc() {
  $DC exec -T bitcoind bitcoin-cli -regtest -datadir=/data \
    -rpcuser="$BTC_RPC_USER" -rpcpassword="$BTC_RPC_PASS" "$@"
}
lnd() {
  local node="$1"; shift
  $DC exec -T "$node" lncli --network=regtest "$@"
}
cln() {
  $DC exec -T carol lightning-cli --network=regtest "$@"
}

mine() {
  local n="${1:-1}"
  local addr
  addr=$(btc -rpcwallet=miner getnewaddress)
  btc generatetoaddress "$n" "$addr" >/dev/null
}

wait_for() {
  local what="$1"; shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "Timed out waiting for $what" >&2
  exit 1
}

json() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }
