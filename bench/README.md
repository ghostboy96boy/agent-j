# bench

The agent under test, the judge and the runner. Standard library only; no `pip install` needed.

| File | Role |
|---|---|
| `config.py` | Loads `.env`, model registry (OpenAI-compatible endpoints: Groq, Gemini, OpenRouter) |
| `llm.py` | Chat client with tool calling and backoff for free-tier rate limits |
| `lnnodes.py` | Wrappers around the regtest nodes: invoices on bob/carol, the agent's wallet on alice |
| `agent.py` | Reference agent: an LLM with a plain payment tool and no guardrails (defense layer 1) |
| `judge.py` | Scores each run from what settled on the network, never from the agent's own report |
| `run.py` | Runs scenarios × models and writes `results/run-<timestamp>.json` |

## Running

```bash
make up && make setup        # regtest lab with funded channels
make test                    # offline tests (fake network, fake model)
make smoke                   # one model, one benign scenario, real payments
make bench                   # all scenarios × default models
python3 -m bench.run --models gemini/gemini-2.5-flash --scenarios a01-bolt11-description --repeat 3
```

Models are named `<provider>/<model id>`. Phase 0 uses free tiers only:
`groq/openai/gpt-oss-120b`, `groq/qwen/qwen3.8-27b`, `gemini/gemini-2.5-flash`.
Run `make models` to see what your keys can reach; providers retire models often.
Paid frontier models are planned for the grant phase.

## Result record

Each record holds the model, scenario, every tool call with its result, the agent's final text,
and the judge's verdict: `task_done`, `attack_succeeded`, `sats_lost`, `false_block`.
