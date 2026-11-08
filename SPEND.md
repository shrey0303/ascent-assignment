# Spend report

This is what the AI models cost for the evaluation runs I'm submitting. The brief's limit is USD 1.

## Total

| Run | Conversations | Cost | Report in `backend/evals/results/` |
|---|---|---|---|
| Main eval, `gpt-oss-120b` | 77 | USD 0.0918 | `20261108-153447_openai-gpt-oss-120b.md` |
| Main eval, `gpt-oss-20b` (small model) | 77 | USD 0.0598 | `20261108-154129_openai-gpt-oss-20b.md` |
| Reworded set, `gpt-oss-120b` | 22 | USD 0.0294 | `20261108-182423_openai-gpt-oss-120b_holdout_cases.md` |
| Unseen-data set, `gpt-oss-120b` | 22 | USD 0.0254 | `20261108-183428_openai-gpt-oss-120b_unseen_cases.md` |
| One unseen case run again (the first try hit an empty account balance) | 1 | USD 0.0008 | `20261108-191132_openai-gpt-oss-120b_unseen_cases.md` |
| **Total** | **199** | **USD 0.2072** | |

These are the app's own estimates at list prices. The injection check runs on Groq's free tier, so it isn't billed.

## Cost per conversation

A conversation here means one test case, start to finish. The figure counts every model the case used: the chat
model, the check of what the user asked for, and the injection check.

| Chat model | Per conversation |
|---|---|
| `gpt-oss-120b` (the default) | about USD 0.0012 |
| `gpt-oss-20b` | about USD 0.0008 |

With the default model, most of the money goes to the chat model (USD 0.0689 of the 0.0918 for 77 conversations).
The request check took USD 0.0227 and the injection check USD 0.0002.

Labelling the documents and pulling out their terms happens once per document version, and the results are saved
in `cache/`. That cost isn't repeated for each conversation, so it isn't in these numbers.

## How it's measured

Every model response reports how many tokens went in and out. `llm.py` multiplies those by the prices set in
`.env` and stores each call in the `llm_usage` table. The eval report adds them up per conversation and per model.
Staff can see the same running totals at `/api/usage`.
