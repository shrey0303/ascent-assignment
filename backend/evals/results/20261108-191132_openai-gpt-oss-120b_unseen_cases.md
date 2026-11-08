# Evaluation run 2026-11-08 19:11 UTC

Model `openai/gpt-oss-120b` via `https://openrouter.ai/api/v1`, classifier `openai/gpt-oss-safeguard-20b`. Labels needing review: 06_LumenWorks_Service_Agreement: effective; 06_LumenWorks_Service_Agreement: commercial: 2. Cancellation terms. **1/1 cases passed (100%).** Critical failures: none.

| Category | Cases | Passed | Pass rate |
|---|---|---|---|
| abstention | 1 | 1 | 100% |

## Latency (per chat turn)

Wall = what the user waits, including provider rate-limit waits. Model = time inside the agent's successful LLM calls (the request check and injection scans run alongside and are not added).

| Turn type | Turns | Median wall | Median model | Target |
|---|---|---|---|---|
| single_tool | 1 | 4.0 s | 3.4 s | < 6 s |

## Cost

9 LLM calls (7 of them request checks and injection scans), 4,909 input and 592 output tokens, each model at its own price: **USD 0.0008 total, USD 0.00084 per conversation** (one case = one conversation). By model: `openai/gpt-oss-20b` USD 0.0002, `openai/gpt-oss-120b` USD 0.0006, `meta-llama/llama-prompt-guard-2-86m` USD 0.0000.

Answers where an unsupported citation was removed before display: 0. Cases re-run once because the LLM was unavailable: 0.

## Failures

None.
