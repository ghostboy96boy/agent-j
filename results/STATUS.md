# Phase 0 run status

Updated 2026-11-16T19:20-03:00. Data frozen at the cutoff, 2026-11-16 19:18 BRT. Results: [summary.md](summary.md) and [the phase 0 note](../docs/notes/2026-11-phase0-results.md). PR: https://github.com/ghostboy96boy/agent-j/pull/1

Groq phase0-r1 valid runs: gpt-oss-120b 77/78, qwen3.8-27b 78/78.

| round | model | defense | valid | model error | invalid |
|---|---|---|---|---|---|
| phase0-pilot-gemini | gemini/gemini-3.6-flash | none | 9 | 0 | 6 |
| phase0-pilot-gemini | gemini/gemini-3.6-flash | prompt | 9 | 0 | 2 |
| phase0-r1 | gemini/gemma-4-31b-it | none | 39 | 0 | 0 |
| phase0-r1 | gemini/gemma-4-31b-it | prompt | 39 | 0 | 0 |
| phase0-r1 | groq/openai/gpt-oss-120b | none | 39 | 1 | 1 |
| phase0-r1 | groq/openai/gpt-oss-120b | prompt | 38 | 8 | 6 |
| phase0-r1 | groq/qwen/qwen3.8-27b | none | 39 | 1 | 0 |
| phase0-r1 | groq/qwen/qwen3.8-27b | prompt | 39 | 0 | 9 |

Repetitions closed after 3 model-error attempts (executed with model_error): gpt-oss 1, qwen 0.
