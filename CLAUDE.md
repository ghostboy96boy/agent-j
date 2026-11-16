# Agent J: context for Claude Code

Open-source benchmark and guardrail library for AI agents that hold Lightning wallets. Target: OpenSats general grant (submission by end of November 2026).

Rules for work in this repo:
- Regtest only. Never add mainnet configuration, real keys or real funds.
- Never commit `.env` or credentials.
- The judge must score from settled payments on the network, never from the agent's own report.
- Findings in third-party tools follow SECURITY.md (private disclosure first).
- Keep docs in English; a Portuguese guide comes in phase 2.
- Phase 0 models are free tiers only, pinned in bench/config.py: groq/openai/gpt-oss-120b, groq/qwen/qwen3.8-27b, gemini/gemini-3.6-flash. gemini/gemini-2.5-flash returned HTTP 404 on 2026-11-12 and was replaced by gemini-3.6-flash. Never swap a model without the owner's ok.

Next task (phase 0): reference agent that pays regtest invoices through one stack, then the first 10 scenarios and the judge. See docs/ROADMAP.md.

Pending:
- Phase 0 is closed. The owner moved the cutoff forward to 2026-11-16 19:18 BRT (zero cost; the Gemini Flash pilot stays at 18/26 runs, n=1). The hourly resume and the scheduled cutoff were cancelled; no round runs anymore. Data, `results/summary.*` and `docs/notes/2026-11-phase0-results.md` were merged to main in PR #1 (ed332f0).
- Done 2026-11-16: after the phase 0 PR merge (ed332f0), `BTC_RPC_PASS` in `.env` was rotated and the lab rebuilt from empty volumes (bitcoind, alice, bob, carol); `make status` showed alice → bob and bob → carol active. The `lak` profile containers (aperture, weatherln) were removed with it and not restarted; `make up-lak` brings them back.
- Do not add runs to rounds phase0-r1 or phase0-pilot-gemini; their data is frozen.
- Not in phase 0: stage 8 (Lightning Agent Kit), deferred to month 1 of the grant.
