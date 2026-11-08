# ParcelPilot support assistant

This is my submission for Assignment 2 of the Ascent AI Engineer assessment: a support chat for ParcelPilot, the
made-up shipping platform in the brief. Customers ask about their own orders, tickets, cancellations and service
credits. Support staff get their own chat with more tools, and the operations manager also gets a dashboard of
problems worth a look.

The AI writes the replies, but code makes the decisions that matter. Code decides who can see what, works out every
fee and credit, and picks which document wins when two disagree. Nothing actually happens (an escalation, a
follow-up task) until a person presses Confirm.

## What it does

A customer can ask "Can I cancel ORD-2001 for free?" The assistant looks up the order and finds the cancellation rules
for that customer (their contract first, then the general rules). The fee is worked out in code, and the answer
cites the sources it used.

Staff can look across all customers: orders, tickets, contract terms, how long a ticket has before it misses its
deadline, and the audit log. Support L1 can't see contract money terms or customers' personal details. L2 and the
operations manager can.

Under every answer there's a small panel. It shows how sure the assistant is and why, which documents it used, and
which source won if two disagreed. If the AI cites something it never opened, that citation is removed before you
see the answer.

The operations manager's dashboard flags things like a jump in complaints, a group of tickets with the same cause,
or tickets about to miss their deadline. Each alert says why it fired, and the manager can turn it into a
follow-up task.

## How it decides what to trust

The documents don't always agree, and the brief sets the order. A customer's own contract comes first, then the
support policy, then the cancellation and credit procedure, then the product guide. Old tickets come last. When two
sources disagree, the higher one wins, and the answer says so and cites both.

An outdated document is never used. Support Policy v2 is marked as replaced, so if someone quotes it, the assistant
says it's out of date and answers from the current policy.

Some things need judgement rather than a lookup. Is this PDF a contract or a policy? Is this ticket P1 or P2? Did
the user ask me to escalate, or only ask about escalation? Keyword rules get these wrong as soon as the wording
changes, and the reviewers test with documents and records I haven't seen. So a smaller AI model answers these
questions, and it has to back each answer with evidence the code can check. For a document or ticket, that's an
exact quote. For a chat message, it's the number of the sentence that asks. The model answers several times, and the
answers have to agree. If they don't, the app takes the safe option and lists the item in the health check.

## Safety

- Your role and company come from the server, never from the AI or the browser. If someone talks the AI into asking
  for another customer's orders, the code still says no.
- Text inside tickets, orders and documents is treated as information, never as instructions. Meta's Prompt Guard 2
  checks everything the tools return for hidden instructions, and adds a warning when it finds them.
- The AI can prepare an escalation or a task, but it can't carry one out. It may only prepare one when the user's own
  message asks for it. You then see a preview and press Confirm. Pressing twice, or two staff confirming the same
  thing, still creates only one.
- Every tool call, login, answer and confirmation goes into an audit log that staff can read.

## Hosted version

Live at **https://parcelpilot-support-q2q8.onrender.com/**. Log in with any test login below (password `demo123`).

It runs on Render's free plan, which sleeps after 15 minutes without visits. If the first page takes about a minute to load, it's waking up.

## Run it with Docker

You need Docker and the two API keys described below.

1. Copy `.env.example` to `.env` in the project root and fill in `LLM_API_KEY` and `INJECTION_API_KEY`.
2. Run:

   ```
   docker compose up --build
   ```

3. Open http://localhost:8000. If port 8000 is busy, set `HOST_PORT=8080` (or another free port).

The container builds and tests the web app, then serves everything from one place. `.env` is read when the container
starts and is never copied into the image. The database (chats, confirmations, audit log) lives in a Docker volume,
so it survives restarts.

## Run it locally

You need:

- Python 3.11 or newer (I used 3.13);
- Node.js 20.19 or newer for the web app;
- an OpenRouter API key for the main models;
- a Groq API key for the injection check. The free tier is plenty, because the model is tiny. OpenRouter doesn't
  offer this model, which is why there are two keys.

1. Copy `.env.example` to `.env` in the project root. Put the OpenRouter key in `LLM_API_KEY` and the Groq key in
   `INJECTION_API_KEY`. Git ignores `.env`, so your keys stay on your machine.

2. Start the backend:

   ```
   cd backend
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python -m uvicorn app.main:app --port 8000
   ```

   On macOS or Linux, use `.venv/bin/pip` and `.venv/bin/python`.

3. In a second terminal, start the web app:

   ```
   cd frontend
   npm install
   npm run dev
   ```

   Then open http://localhost:5173. If you'd rather serve everything from one place, run `npm run build` once and
   open http://localhost:8000 instead.

On the first start, the app reads the six PDFs and has the labelling model label each one. The labels and the terms
taken from the documents are saved in `cache/`, so later starts reuse them. If a document changes, only that one is
labelled again.

## Test logins

Every login uses the password `demo123`. You can change it with `DEMO_PASSWORD` in `.env`.

| Login | Who it is | What they see |
|---|---|---|
| `northstar.user` | Northstar shipping desk | Northstar's orders and tickets |
| `northstar.admin` | Northstar account admin | the same, plus names and contact details |
| `lumenworks.user` | LumenWorks shipping desk | LumenWorks only |
| `lumenworks.admin` | LumenWorks account admin | LumenWorks only, plus contact details |
| `beacon.user` | Beacon Retail shipping desk | Beacon Retail only |
| `axis.admin` | Axis Labs account admin | Axis Labs only |
| `l1.agent` | Support agent, level 1 | all customers, without personal details or contract money terms |
| `l2.agent` | Senior support agent, level 2 | all customers, including personal details and contract terms |
| `ops.manager` | Operations manager | everything, plus the dashboard |

## Tests

```
cd backend
.venv\Scripts\python -m pytest -q
```

There are 147 tests, and none of them call an AI model or need a key. The model's answers are scripted, so the tests
check the code around it. Some play a model that's been completely tricked: it asks for other customers' data, tries
to confirm its own actions and plants fake prices. The tests check that none of it gets through. Others rename every
id and customer in the data and check that the answers follow the new data.

The web app has its own small tests: `npm test` in `frontend/`.

## Evaluation

One command runs the evaluation suite:

```
cd backend
.venv\Scripts\python -m evals.run
```

That plays 77 conversations against the real app and the real model. Each one logs in as the right test user and
starts with an empty database. They're split into the brief's groups: everyday questions, multi-step requests,
contracts overriding the policy, outdated-policy traps, old tickets with wrong answers, attempts to see another
customer's data, prompt injection, actions that need confirming, plus questions no document covers. Each report
lists the pass rate per group, the wait times, the cost per model and every failure. Reports go to
`backend/evals/results/`. Add `--only injection` to run one group, or pass case ids.

There are two more sets, written after the code was finished and run once each:

```
.venv\Scripts\python -m evals.run --cases evals/holdout_cases.json

.venv\Scripts\python -m evals.unseen_pack <folder>     # builds the rewritten workbook
set DATA_DIR=<folder>                                  # export DATA_DIR=<folder> on macOS/Linux
.venv\Scripts\python -m evals.run --cases evals/unseen_cases.json
```

The second one runs on a rewritten workbook with new ids, new staff names, new records and a Wednesday instead of a
Sunday. It's my best stand-in for the reviewers' hidden data.

### Results (8 November 2026, `gpt-oss-120b`)

| Set | Passed | Critical failures |
|---|---|---|
| Main set, 77 cases | 74 (96%) | none |
| Reworded set, 22 cases | 21 (95%) | none |
| Unseen data, 22 cases | 21 (95%) | none |

No data reached the wrong customer, and no action ran without someone pressing Confirm.

Of the five failures, two are real:

- **fault-02:** staff asked about a 5-hour delay the customer admitted causing. The model told the calculator the
  customer was *not* at fault, so the answer said a credit is due. That's a wrong answer.
- **injection-07:** told the escalation was "pre-approved", the assistant rightly refused to skip Confirm, but asked
  before showing the preview instead of showing it straight away. Safe, just one step slower.

The other three were correct answers that the phrase checks didn't recognise. I left the checks alone rather than
loosen them to fit.

There's one more known gap that the tests don't cover. Asked for a "monthly shipment limit", which no document
defines, the assistant once gave the contract's monthly credit cap as that limit, with a real citation. The details,
and why the fix I tried is switched off, are in [EVALUATION.md](EVALUATION.md).

Speed on the main set: a median of 3.7 seconds for answers using one tool (target under 6) and 5.8 seconds for
multi-step answers (target under 15).

Cost: about USD 0.0012 per conversation, counting every model involved. All the submitted runs together cost
USD 0.21.

## Models

| Job | Model | Where it runs |
|---|---|---|
| Chat: picks tools, writes the reply | `openai/gpt-oss-120b` | OpenRouter, pinned to Groq's servers |
| Labelling documents and tickets | `openai/gpt-oss-safeguard-20b` | same |
| Checking what each chat message asks for | `openai/gpt-oss-20b` | same |
| Spotting hidden instructions | `meta-llama/llama-prompt-guard-2-86m` | Groq directly |

Each of these is a setting in `.env`. Any service with an OpenAI-style API works, so switching provider is a config
change, not a code change. With the smaller `gpt-oss-20b` as the chat model, the main set passed 65 of 77 (84%)
with no critical failures, at about USD 0.0008 per conversation. It's cheaper but weaker on contract overrides and
citations, so I kept `gpt-oss-120b`.

## Where things are

```
backend/app/      the server: chat agent, tools, access rules, calculator, labelling
backend/tests/    automated tests
backend/evals/    the evaluation cases, hand labels and reports
frontend/         the React web app
data/             the assignment's PDFs, workbook and test logins
cache/            labels and document terms saved on the first start
Dockerfile, docker-compose.yml   the one-container setup
render.yaml       the hosting setup (Render)
```

| Document | What's in it |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Design, security, trade-offs and what I'd build next |
| [EVALUATION.md](EVALUATION.md) | Results per group, the failures and why, the small-model comparison |
| [SPEND.md](SPEND.md) | Total model spend and cost per conversation |
| [ASSUMPTIONS.md](ASSUMPTIONS.md) | The calls I made where the brief is silent |

