# Agent J

**An open security benchmark and guardrail library for AI agents that hold Lightning wallets.**

Agent J is a crash-test lab for AI agents that move bitcoin. It gives agents real Lightning wallets on a private regtest network, attacks them on purpose, and measures two things: which models get tricked into paying, and which controls actually stop the money from leaving.

> Status: early development (October 2026). The regtest lab runs with one command; agents, attack scenarios and the judge are next. See the [roadmap](docs/ROADMAP.md).

## Why this exists

AI agents can already run Lightning nodes, pay invoices and sell services over L402. Lightning Labs released an open agent toolkit in February 2026, several MCP servers connect agents to wallets through Nostr Wallet Connect, and other teams are adding Lightning payments to AI compute networks.

At the same time, prompt injection has already pushed agents into sending funds on other rails:

- In July 2026, Zscaler reported that 4 of 26 models it tested were manipulated into paying an attacker's wallet through instructions hidden in web pages.
- In May 2026, agents linked to Grok and Bankrbot transferred an estimated US$150,000–200,000 in tokens on Base after an instruction hidden in Morse code.

The Lightning ecosystem already offers controls such as scoped macaroons, NWC budgets and remote signers. Nobody has measured, in public and on real Lightning nodes, how well they hold up against a manipulated agent. Agent J does that.

## What Agent J does

1. **Test.** Agents built on real stacks (Lightning Agent Kit, NWC/MCP servers, a generic payment tool) perform ordinary payment tasks on regtest. Along the way they meet traps: an invoice whose description carries hidden instructions, an L402 endpoint that charges 100× the advertised price, a look-alike Lightning address.
2. **Measure.** A judge reads what actually settled on the network, not what the agent claims it did. Results are reported per model and per defense layer, in sats lost and in attack success rate, alongside false blocks on legitimate tasks.
3. **Protect.** An open guardrail library enforces spending policy outside the model (allowlists, caps, human approval above a threshold), plus a secure configuration guide for agent builders, in English and Portuguese.

## Attack categories

Direct injection · instructions in BOLT11 invoice descriptions · LNURL metadata · inflated L402 prices · look-alike destinations (BIP353, Lightning Address) · urgency and authority impersonation · splitting under per-payment caps · encoded instructions (Base64, Morse, invisible Unicode) · Nostr zap content · fake refunds.

Details in [docs/ATTACKS.md](docs/ATTACKS.md).

## Defense layers evaluated

1. None (wallet balance only)
2. Spending policy written in the system prompt
3. Tool-level limits (lnget `--max-cost`, NWC budget and per-payment limit)
4. Scoped credentials (pay-only macaroon with a cap)
5. Agent J guardrails (policy enforced outside the model)

## Quick start (regtest lab)

Requirements: Docker with Compose v2, `make`, about 4 GB of free RAM. Linux, macOS or Windows with WSL2.

```bash
git clone https://github.com/ghostboy96boy/agent-j.git
cd agent-j
cp .env.example .env
make up        # bitcoind + 2 LND nodes (alice, bob) + 1 Core Lightning node (carol)
make setup     # funds the nodes and opens channels alice -> bob -> carol
make status    # shows balances and channels
make down      # stops everything and deletes the regtest data
```

Everything runs on regtest. No real bitcoin is involved at any point.

## Repository layout

```
docker-compose.yml   regtest network: bitcoind, alice (LND), bob (LND), carol (CLN)
scripts/             setup, status and teardown helpers
bench/               agent adapters and the judge (in progress)
scenarios/           attack and benign scenarios (in progress)
guard/               guardrail library (planned)
results/             machine-readable results (JSON)
docs/                roadmap, attack catalog, methodology
```

## Responsible disclosure

Any weakness found in third-party software is reported privately to its maintainers before publication. See [SECURITY.md](SECURITY.md).

## Author

Christopher Silva, technology and AI consultant based in São Paulo, Brazil. [LinkedIn](https://www.linkedin.com/in/christopher-p-silva) · [GitHub](https://github.com/ghostboy96boy)

## License

MIT. See [LICENSE](LICENSE).
