# Phase 0 run status

Updated 2026-11-13T23:35-03:00. Run counts only; results are published after the cutoff (2026-11-18 00:00 BRT).

Groq phase0-r1 valid runs: gpt-oss-120b 76/78, qwen3.8-27b 72/78.

| round | model | defense | valid | model error | invalid |
|---|---|---|---|---|---|
| phase0-pilot-gemini | gemini/gemini-3.6-flash | none | 6 | 0 | 3 |
| phase0-pilot-gemini | gemini/gemini-3.6-flash | prompt | 3 | 0 | 2 |
| phase0-r1 | gemini/gemma-4-31b-it | none | 39 | 0 | 0 |
| phase0-r1 | gemini/gemma-4-31b-it | prompt | 39 | 0 | 0 |
| phase0-r1 | groq/openai/gpt-oss-120b | none | 39 | 1 | 1 |
| phase0-r1 | groq/openai/gpt-oss-120b | prompt | 37 | 8 | 6 |
| phase0-r1 | groq/qwen/qwen3.8-27b | none | 39 | 1 | 0 |
| phase0-r1 | groq/qwen/qwen3.8-27b | prompt | 33 | 0 | 7 |

Repetitions closed after 3 model-error attempts (executed with model_error): gpt-oss 1, qwen 0.
