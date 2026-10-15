#!/usr/bin/env bash
# Prints block height, on-chain balances and channels for each node.
source "$(dirname "$0")/lib.sh"

lnd_channels() {
  python3 -c '
import sys, json
for c in json.load(sys.stdin)["channels"]:
    print("  channel {}: local {} / remote {} active={}".format(
        c["chan_id"], c["local_balance"], c["remote_balance"], c["active"]))
'
}

cln_funds() {
  python3 -c '
import sys, json
d = json.load(sys.stdin)
print("on-chain sats:", sum(o["amount_msat"] // 1000 for o in d["outputs"]))
for c in d["channels"]:
    print("  channel with {}...: {} sats ours, state {}".format(
        c["peer_id"][:12], c["our_amount_msat"] // 1000, c["state"]))
'
}

echo "Block height: $(btc getblockcount)"
for n in alice bob; do
  echo
  echo "== $n (LND)"
  echo "on-chain sats: $(lnd "$n" walletbalance | json "['confirmed_balance']")"
  lnd "$n" listchannels | lnd_channels
done
echo
echo "== carol (Core Lightning)"
cln listfunds | cln_funds
