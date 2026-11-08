# Architecture note

Ascent support assistant, Ascent AI Engineer assessment, Assignment 2. (The data pack's documents call the
platform ParcelPilot.)

## 1. The idea

The AI model picks tools and writes the reply, but code makes the decisions that matter: who can see what, every
fee, credit and deadline, which source wins, and nothing changes until a person presses Confirm. Where judgement is
needed (is this PDF a contract? is this ticket P1 or P2? did the user ask to escalate?), a smaller labelling model
answers. It must back each answer with something the code can check, and several runs must agree. If they don't, the
app takes the safe option.

## 2. Agent design

One FastAPI server runs both chats. The customer chat and the staff chat share the same agent loop and the same
tools. They differ in the system prompt and in which tools each role gets.

Here's what happens to one message:

1. **Login.** The session token is signed. The user's role and company come from the server, never from the browser
   or the model.
2. **Request check.** While the main model starts working, a small model (`gpt-oss-20b`) reads only the user's
   message and the end of the previous reply. It decides whether the user asked for an escalation, a task, or
   neither. The message is split into numbered sentences, and the model has to say which sentence asks. The code
   then takes that sentence from the message itself, so the evidence is always the user's own words. It never
   reads tool results, so text planted in a ticket can't reach it.
3. **Agent loop.** `gpt-oss-120b` writes a short plan, calls tools (up to 6 steps) and writes the answer. Each step
   streams to the screen live: the plan, each tool call and its result. An escalation or task tool is refused
   unless the request check found the user asking for it.
4. **Checks in code** before the answer is shown:
   - a citation that doesn't match a source the assistant actually opened is removed, and confidence drops;
   - a tool name written as if it were a source (`[calc_ticket_sla]`) is removed;
   - if two sources disagree and the answer only cites one, a note citing both is added;
   - if the user mentioned an outdated document, a note says it wasn't used;
   - calculator warnings ("check with the carrier first") are always shown;
   - confidence is lowered when facts are missing, access was limited, hidden instructions were found, or the
     search found words that no document contains.

Follow-ups like "escalate that one" or "what about the other order?" work because each chat keeps its last 16
messages plus the order and ticket ids already used. A chat belongs to the user who started it.

## 3. Tool design

There are 10 tools, and every call goes through one function, `tools.run`. It checks, in this order: is this role
allowed to use the tool, is the record in the user's own company (for customers), which personal fields to hide,
and whether to hide contract money terms from Support L1. Then it scans the returned text for hidden instructions
and writes the call, input, output and decision to the audit log.

| Tool | What it does |
|---|---|
| `search_documents` | Keyword search (BM25) over the documents in force, returning source ids. A contract only shows up for its own customer. It also lists words from the question that no readable document contains, so the model can see the topic isn't covered. |
| `query_records` | Orders, tickets and accounts, limited to the user's scope and masked by role. An old ticket's resolution comes with the current rules on the same topic. |
| `get_account_terms` | A customer's terms after precedence, with each conflict and the reason one source won. |
| `calc_cancellation`, `calc_pickup_credit`, `calc_ticket_sla` | Fees, credits and deadlines, worked out in code. The model never does arithmetic. |
| `sla_watchlist` (staff) | Tickets that have breached, or will within N hours. |
| `propose_escalation` (everyone, for what they can see), `propose_task` (staff) | Make a preview only. |
| `audit_lookup` (staff) | Search the audit log. |

The Confirm button sends a signed token tied to the preview, the user, the exact content and an expiry time. The
model never sees the token, so it can't confirm anything or change the action afterwards. Each action has a unique
key (one escalation per ticket, one task per alert), so a double click or two staff confirming the same thing still
creates one record.

## 4. Documents and data

- **Workbook.** Read by column name, so a new workbook with reordered columns still loads. The snapshot time in the
  README sheet is "now" for every calculation. If the data folder holds two workbooks, the app refuses to start
  rather than guess which one is current.
- **PDFs.** Split into numbered sections, with table rows kept whole. The labelling model
  (`gpt-oss-safeguard-20b`) reads each document and decides its type, whether it's in force, its version and dates,
  which customer it belongs to, and which contract sections are about money. Labels are saved per text version in
  `cache/labels.json`. The same text always gets the same label, and a changed document is labelled again.
- **Terms.** The model reads each current document once and lists its terms: fees, windows, targets, credits. A term
  is only kept if its quote appears word for word in the document and contains the value.
- **Nothing hard-coded.** No id, name, clause number or answer from the data pack is in `backend/app/`. A test checks
  this on every run. Another test renames every id and customer and moves the clock, then checks the answers follow
  the new data. The unseen-data eval does the same with the real model.

## 5. Which source wins

The brief's order is written in code (`config.SOURCE_PRECEDENCE`): the customer's contract, then the support policy,
then the cancellation and credit procedure, then the product guide, then old tickets.

- **Left out entirely:** deprecated or superseded documents, contracts outside their term, documents dated after
  "now", and anything the labelling model couldn't classify. If the user names one ("the 2025 policy"), the answer
  says it's out of date and answers from the current one.
- **Conflicts:** each term comes from the highest source, and every lower source that disagrees is listed. The answer
  has to name both, and the code adds a note if the model forgets.
- **Old tickets** are context only. A past answer always comes with the current rules on the same topic, so a wrong
  past answer gets corrected rather than repeated.
- **Saying "I don't know":** when no source supports an answer, or a fact can't be verified ("it was the carrier's
  fault"), the assistant says so and offers an escalation. The calculator never promises a credit when fault is
  unknown. When the search finds the topic in no document, the model is told and confidence is capped. Only text
  the user is allowed to read counts, so this never hints at another customer's contract.

## 6. Security

I treat everything outside the server as untrusted, including the model. Four checkpoints in code make the
decisions:

1. **Login:** a signed session, with role and company from the server.
2. **Tools:** role, company, personal-field and money-term checks on every call. Arguments from the model can only
   narrow what a user sees, never widen it.
3. **Confirmation:** a signed token, tied to the exact content, usable once.
4. **Answer checks:** citations to sources the assistant didn't open are removed.

Prompt injection is handled in three layers. Ticket and document text is marked as data in the prompt. Prompt Guard
2, a small model built for this, scans every tool result and adds a warning when it finds instructions. But the
main defence is the structure: whether an action may happen is decided from the user's own message, before any data
is read. Planted text can't unlock an action even when the scan misses it, and it does miss some. On the data pack,
blunt attacks scored 0.999 but a politely worded planted instruction scored only 0.016. That's why the scan is a
warning signal, not the lock.

147 automated tests back this up. They include forged tool arguments, one user opening another user's chat, edited
Confirm tokens, and a scripted model that has been completely tricked. None of them leak data or run an action.

## 7. Evaluation

`python -m evals.run` plays each conversation against the real app and model, as the right test user, with an empty
database. Every answer is checked for the brief's critical failures (another customer's data, an action without
Confirm, a false "done" claim, money terms shown to L1), plus each case's own checks on tools, previews, conflicts,
confidence and wording.

| Set | Passed | Critical failures |
|---|---|---|
| Main set (77 cases, the one I tuned against) | 74 (96%) | none |
| Reworded set (22 cases, run once at the end) | 21 (95%) | none |
| Unseen data: new ids, names, records and a weekday clock (22 cases, run once) | 21 (95%) | none |

Five of the 112 cases failed. Two are behaviour I chose not to patch: the model misread who was at fault once, and
it once asked before showing a preview. The other three are the phrase checks missing correct answers. The labelling
model scores 118 of 120 against hand labels, and both misses fail safe. Details and the per-group tables are in
[EVALUATION.md](EVALUATION.md).

## 8. Cost, latency and model choice

| | `gpt-oss-120b` (default) | `gpt-oss-20b` (small) |
|---|---|---|
| Main set passed | 74/77 (96%) | 65/77 (84%) |
| Median wait, one tool (target under 6 s) | 3.7 s | 3.5 s |
| Median wait, multi-step (target under 15 s) | 5.8 s | 6.2 s |
| Cost per conversation | about USD 0.0012 | about USD 0.0008 |

The small model is cheaper but slips more often on contract overrides, citations and the calculator's inputs. Safety
was the same with both, because it doesn't depend on the model. Total spend for all the submitted runs was
USD 0.21 ([SPEND.md](SPEND.md)).

The models run through OpenRouter on Groq's servers. Prompt Guard 2 is only on Groq, so it has its own key.
Switching provider or model is a change in `.env`, not in code.

## 9. Trade-offs

- **A labelling model instead of keyword rules.** Keyword rules break as soon as new documents use other words. The
  model costs extra calls and is sometimes unsure. Then the app fails safe and lists the item in `/api/health`, so
  being unsure costs usefulness, not safety.
- **Five votes per label.** Four of five must agree. It costs five times as much, but a label is made once per
  document version, not per chat.
- **The stricter reading when the brief is vague.** Fee waivers count as money terms, so L1 sees less, and unclear
  tickets are treated as more urgent. Showing L1 too much is worse than showing too little.
- **Keyword search, not embeddings.** Enough for six documents, exact on ids and numbers, no extra service.
- **No second model checking every sentence.** I built one. It removed correct facts and added 8 to 12 seconds per
  answer, so it's off and the gap is reported.

## 10. What I'd build next, in order

1. **Check the facts the user states against the tool inputs.** Once the model passed the calculator the opposite
   of what the user said about fault. The request check already reads every message, so it could list those facts
   for code to compare before any calculation runs. Wrong inputs give wrong money, even when the maths is right.
2. **A small fact-checking model on every answer.** Today a real citation can sit on a claim the source doesn't
   make. A model built for "does this text support this sentence" (MiniCheck is one) is fast enough to run on every
   answer, unlike the large-model check I tried.
3. **A credit ledger.** Monthly credit caps are reported but not enforced, because the data has no record of credits
   already given. Money is where a support mistake costs the most.
4. **Per-customer time zones and holiday calendars.** Every SLA deadline depends on one assumed calendar today
   (Monday to Friday, 09:00 to 18:00, India time). A customer in another time zone, or a public holiday, would get a
   wrong deadline.
5. **Rate limits on logins and messages.** The hosted app has one shared demo password and a paid model behind it.
   Limits stop password guessing and protect the budget.
