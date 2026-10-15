# Roadmap

## Phase 0: foundation (October–November 2026)

- [x] Project plan and attack catalog draft
- [x] Regtest lab: bitcoind, two LND nodes, one Core Lightning node
- [ ] Reference agent paying real regtest invoices through one stack (NWC or Lightning Agent Kit)
- [ ] First 10 attack scenarios and 3 benign controls
- [ ] Judge that scores runs from settled payments on the network
- [ ] First run with 3 models and a short technical note

## Phase 1: benchmark (months 1–3)

- Full catalog of 60+ scenarios across 10 categories
- Adapters for Lightning Agent Kit, NWC/MCP servers and a generic payment tool
- Evaluation of 8–10 open and closed models with no defense and with prompt-only policy
- Evaluation of native controls: tool limits, NWC budgets, scoped macaroons
- Interim report and private disclosure to affected maintainers

## Phase 2: guardrails (months 4–6)

- Guardrail library v0.1: out-of-model spending policy, destination allowlists, caps, human approval
- Re-evaluation with guardrails enabled
- Secure configuration guide (English and Portuguese)
- Final report and v1.0 release
