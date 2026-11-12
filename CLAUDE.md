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
- Rotate the local regtest RPC password (`BTC_RPC_PASS` in `.env`) and rebuild the lab (`make down && make up && make setup && make status`) only after every phase0 round has closed (after 2026-11-17). Do not rebuild the lab during a round. Low risk meanwhile: bitcoind publishes no port on the host. `.env.example` already holds a placeholder (ba2bc85).
- Phase 0 closing plan (owner decision, 2026-11-12). Session cron jobs die with the session; a new session must recreate them:
  - Daily at ~05:17 BRT through 2026-11-17 (after the free quotas reset): if alice has an active channel (`make status`; if not, stop and tell the owner, never rebuild the lab), resume the rounds that are not already running, in background:
    - `bash scripts/round.sh phase0-r1 3 groq/openai/gpt-oss-120b groq/qwen/qwen3.8-27b`
    - in parallel, `bash scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash; bash scripts/ordered-round.sh phase0-r1 gemini/gemma-4-31b-it bench/rounds/phase0-r1-gemma.order`
    - priority if quota is short: Groq to n=3, then Gemma, then the Flash pilot. Quota-cut runs stay invalid; never re-run valid runs. After each day, send the owner 3 lines (valid per model × defense, invalid/model_error, what is missing). Do not quote partial numbers anywhere before the cutoff.
  - Gemma rule: at its first HTTP 429 read the limit in `results/private/http-errors/`; if it cannot reach n=3 by 2026-11-17 23:59 BRT, move it to a pilot round (like the Flash pilot) and tell the owner the limit and the decision.
  - Cutoff 2026-11-18 00:02 BRT: delete the daily job, stop all rounds (no lab action), then `python3 -m bench.report --summary --round phase0-r1 --pilot phase0-pilot-gemini --cutoff 2026-11-18T00:00-03:00` (plus any Gemma pilot). Nothing after the cutoff enters; incomplete cells are published with their n.
  - Then: commit `results/summary.*` and the phase0-r1/pilot `results/run-*.json` (`git add -f`; never `results/private/` or `.env*`); finish `docs/notes/2026-11-phase0-results.md` from the frozen numbers (≤ ~2 pages, English, no third-party tool findings) and link it from README; `make test` green; push `phase0-first-round`; open a PR to main and do NOT merge; stop and send the owner the PR link and a final report in Portuguese.
  - Not in phase 0: stage 8 (Lightning Agent Kit), deferred to month 1 of the grant.
