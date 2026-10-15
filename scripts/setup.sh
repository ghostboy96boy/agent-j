#!/usr/bin/env bash
# Funds the nodes and opens channels: alice -> bob -> carol.
# Safe to run on a fresh lab (after `make up`). Regtest only.
source "$(dirname "$0")/lib.sh"

echo "Waiting for bitcoind..."
wait_for "bitcoind" btc getblockchaininfo

if ! btc listwallets | grep -q '"miner"'; then
  btc createwallet miner >/dev/null 2>&1 || btc loadwallet miner >/dev/null
fi
echo "Mining 101 blocks..."
mine 101

echo "Waiting for Lightning nodes..."
wait_for "alice" lnd alice getinfo
wait_for "bob"   lnd bob getinfo
wait_for "carol" cln getinfo

ALICE_ADDR=$(lnd alice newaddress p2wkh | json "['address']")
BOB_ADDR=$(lnd bob newaddress p2wkh | json "['address']")
CAROL_ADDR=$(cln newaddr | json "['bech32']")

echo "Funding nodes with 1 BTC each..."
for a in "$ALICE_ADDR" "$BOB_ADDR" "$CAROL_ADDR"; do
  btc -rpcwallet=miner sendtoaddress "$a" 1 >/dev/null
done
mine 6
sleep 5

has_funds() { [[ $(lnd "$1" walletbalance | json "['confirmed_balance']") -gt 0 ]]; }

BOB_PUB=$(lnd bob getinfo | json "['identity_pubkey']")
CAROL_PUB=$(cln getinfo | json "['id']")

echo "Connecting peers..."
lnd alice connect "${BOB_PUB}@bob:9735" >/dev/null 2>&1 || true
lnd bob connect "${CAROL_PUB}@carol:9735" >/dev/null 2>&1 || true

echo "Opening channels (alice -> bob, bob -> carol)..."
wait_for "alice funds" has_funds alice
lnd alice openchannel --node_key "$BOB_PUB" --local_amt 5000000 --push_amt 1000000 >/dev/null
wait_for "bob funds" has_funds bob
lnd bob openchannel --node_key "$CAROL_PUB" --local_amt 5000000 --push_amt 1000000 >/dev/null
mine 6
sleep 5

echo
echo "Lab ready. Run 'make status' to see balances and channels."
