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
