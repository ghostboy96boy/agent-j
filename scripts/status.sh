#!/usr/bin/env bash
# Prints block height, on-chain balances and channels for each node.
source "$(dirname "$0")/lib.sh"

echo "Block height: $(btc getblockcount)"
for n in alice bob; do
  echo
  echo "== $n (LND)"
  echo "on-chain sats: $(lnd "$n" walletbalance | json "['confirmed_balance']")"
  lnd "$n" listchannels | python3 -c '
import sys, json
for c in json.load(sys.stdin)["channels"]:
    print(f"  channel {c[\"chan_id\"]}: local {c[\"local_balance\"]} / remote {c[\"remote_balance\"]} active={c[\"active\"]}")'
done
echo
echo "== carol (Core Lightning)"
cln listfunds | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("  on-chain sats:", sum(o["amount_msat"] // 1000 for o in d["outputs"]))
for c in d["channels"]:
    print(f"  channel with {c[\"peer_id\"][:12]}...: {c[\"our_amount_msat\"] // 1000} sats ours, state {c[\"state\"]}")'
