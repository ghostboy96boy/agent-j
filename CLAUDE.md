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
  - Hourly (owner decision, 2026-11-12; replaces the daily 05:17 job) at minute 23, until 2026-11-17 23:00 BRT: run `bash scripts/hourly-resume.sh` in background. It never touches the lab (on an inactive channel it notifies and exits 3: stop and tell the owner), starts the Groq phase0-r1 chain (`scripts/round.sh phase0-r1 3 ...`) and the Flash pilot chain (`scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash`) only if not already running and only for models whose daily quota should be back (`python3 -m bench.quota MODEL`), and each chain stops at the daily-quota message. Gemma phase0-r1 finished n=3 on 2026-11-12 (no 429 seen).
    - After every pass that recorded at least one run, the script pushes `results/STATUS.md` alone and shows a Windows notification "Groq: gpt-oss X/78, qwen Y/78 · Flash Z/26 · próxima tentativa HH:MM"; a pass that ran nothing stays silent.
    - When every Groq repetition is executed (see the model-error rule), the script commits and pushes `results/STATUS.md` alone (counts only), shows a Windows notification (`scripts/notify.sh`) and prints `GROQ COMPLETE`; then send the owner 3 lines (valid per model × defense, invalid/model_error, what the pilot still misses).
    - Model-error rule (owner, 2026-11-12): each repetition of a cell (model × scenario × defense × repeat) gets at most 3 attempts that end in model_error (`MAX_MODEL_ERROR_ATTEMPTS` in bench/run.py); after 3 it counts as executed with model_error and is not tried again. Quota-cut and other invalid runs do not count toward the 3 and are retried. Each model_error saves the provider's raw response (Groq `failed_generation`) in `results/model_errors/`, one file per run, no headers or keys; these files are evidence for the note. Groq is complete when every repetition of both models is executed (valid or closed with model_error): notification "gpt-oss X válidas + E model_error / 78".
    - Quota-cut runs stay invalid; never re-run valid runs. After each day, send the owner 3 lines (counts only). Do not quote partial numbers anywhere before the cutoff.
  - Gemma rule (resolved 2026-11-12): gemma-4-31b-it reached n=3 with no 429, so it stays in the main round phase0-r1.
  - Cutoff 2026-11-18 00:02 BRT: delete the hourly job, stop all rounds (no lab action), then `python3 -m bench.report --summary --round phase0-r1 --pilot phase0-pilot-gemini --cutoff 2026-11-18T00:00-03:00` (plus any Gemma pilot). Nothing after the cutoff enters; incomplete cells are published with their n.
  - Then: commit `results/summary.*` and the phase0-r1/pilot `results/run-*.json` (`git add -f`; never `results/private/` or `.env*`); finish `docs/notes/2026-11-phase0-results.md` from the frozen numbers (≤ ~2 pages, English, no third-party tool findings) and link it from README; `make test` green; push `phase0-first-round`; open a PR to main and do NOT merge; write and push `results/STATUS.md` (`python3 -m bench.status --write`), show the Windows notification with the Groq counts and the PR link (`scripts/notify.sh "Agent J" "..."`); stop and send the owner the PR link and a final report in Portuguese.
  - Not in phase 0: stage 8 (Lightning Agent Kit), deferred to month 1 of the grant.
