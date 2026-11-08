# Assumptions log

These are the calls I made where the brief and the data pack don't say. The ids are referenced from code comments,
which is why they aren't in order.

"Now" is the snapshot time in the workbook's README sheet: Sunday 16 August 2026, 11:00, Asia/Kolkata.

## Time and deadlines

| Id | Assumption | Why |
|---|---|---|
| A-01 | Business hours are Monday to Friday, 09:00 to 18:00, with no public holidays. | The brief asks for business hours, but no document defines them. LumenWorks' contract does say there's no weekend cover. The exact hours are my guess. |
| A-02 | All times are Asia/Kolkata, the README's time zone. A date like 05/08/2026 is read day first. | The workbook gives one time zone, and the order and ticket times have none of their own. |
| A-03 | A target without the word "business" (for example "2 hours") runs around the clock. | The documents say "business" wherever they mean business hours. |
| A-04 | One business day is 9 business hours. | Nothing defines a business day, and one unit lets "8 business hours" and "1 business day" be compared. |
| A-13 | A late pickup is measured on the normal clock from the end of the pickup window. | The procedure and the LumenWorks contract give the delay in plain hours (see A-03). |
| A-29 | If a new workbook gives no time zone or currency, the app uses Asia/Kolkata and INR. | So a swapped workbook still loads. |

## Tickets

| Id | Assumption | Why |
|---|---|---|
| A-06 | A ticket's severity is judged by the labelling model against the policy's own P1, P2 and P3 definitions. If it's unsure, the stricter level is used. | The tickets sheet has no severity column, and the policy defines the levels in words, not keywords. |
| A-21 | "High severity" means P1 and P2. | The policy calls P1 "Critical" and P2 "High". |
| A-07 | The first-response clock starts when the ticket is created, and a ticket with no recorded reply counts as unanswered. | The workbook has no column for an agent's reply, and the customer's last message isn't one. |
| A-27 | "closed", "resolved" and "solved" all mean closed. | Words a swapped workbook might use. |
| A-22 | The dashboard warns about tickets due to breach within 4 hours. | It matches the brief's example question. |

## Cancellations and credits

| Id | Assumption | Why |
|---|---|---|
| A-08 | An order status the procedure doesn't cover gets "check first", never a fee. | The procedure covers only four statuses. |
| A-11 | A cancellation is judged at the time it was requested, or at "now" if no time is recorded. | The fee depends on time since booking, and the request time is sometimes blank. |
| A-12 | Cancelling a BOOKED order after its pickup window has started comes with a warning to check with the carrier. | Known issue KI-211: a parcel can be collected while it still shows BOOKED. |
| A-14 | Facts the user states ("it was the carrier's fault") aren't verified, so the answer is "eligible if confirmed", never a promise. | The procedure says not to promise a credit when fault is unknown. |
| A-09 | Northstar's monthly credit cap is reported but not enforced. | The workbook doesn't record credits already given. |
| A-34 | When a contract sets its own credit amount, it replaces the whole default amount rule. | LumenWorks' contract says its clause "replaces the default" amount. |

## Documents and sources

| Id | Assumption | Why |
|---|---|---|
| A-28 | A document is used only if it isn't deprecated or superseded, is in force at "now", is the newest version, and could be classified. | The brief excludes deprecated documents and warns that new versions will arrive. |
| A-32 | A contract is linked to a customer by the account id written inside it. | File names can change. The contract text is what matters. |
| A-33 | A customer's plan comes from the accounts sheet, and per-plan targets apply only to that plan. | The policy lists targets per plan. |
| A-26 | A resolved known issue is never used to explain a group of tickets. | The product guide says not to, unless the evidence clearly matches. |
| A-18 | If the data folder has more than one workbook, the app won't start. | Quietly picking one could mean answering from old data. |
| A-39 | If a searched word (4 or more letters, singular and plural counted as one) appears in no current document the user may read, the sources don't cover that topic. Company names don't count. Confidence is then capped at medium. | The brief asks the assistant to say when the sources don't support an answer, but not how to tell. Whether a word appears is something code can check. Common words like "time" are sometimes missing too, so this only informs the model and caps confidence. It never blocks an answer. |

## Access and actions

| Id | Assumption | Why |
|---|---|---|
| A-10 | The "commercial terms" hidden from L1 are contract sections about money: prices, fees, fee waivers, discounts, credits and caps. If unsure, the section is hidden. | The brief doesn't define the term, and hiding too much is safer than showing too much. |
| A-15 | Customer users don't see staff names or personal data, and customer admins do. L1 sees staff names but not personal data. L2 and the operations manager see everything. | The brief names the roles but not every permission. |
| A-31 | Customers can escalate their own tickets and orders. Follow-up tasks are for staff only. | The brief wants the agent to offer escalation, including to customers. |
| A-35 | An action is only prepared when the user's own message asks for it, or says yes to the assistant's offer. | Ticket and document text must be treated as data, never as a request. |
| A-16 | "The same escalation" means the same ticket, or failing that the same order, or failing that the same customer and reason. | The brief forbids duplicates but doesn't define "same". |
| A-30 | Previews expire after 15 minutes and logins after 12 hours. A chat keeps 16 messages, and a message gets at most 6 tool steps. | Not specified. These limit stale confirmations, cost and waiting. |
| A-17 | All test logins share one public password, `demo123`. | Reviewers need a login for every role. |
| A-40 | Ids match whatever dash they're written with (`TKT-1`, or `TKT‑1` with a non-breaking hyphen), and case is ignored. | Models often write unusual hyphens, while the records use plain ones. |
| A-41 | A bracket that names a tool or a field of a tool result (`[calc_ticket_sla]`) isn't a citation, so it's removed without lowering confidence. | It points to no source. Leaving it in would look like an invented citation, which the brief treats as a critical failure. |

## Detection and labelling

| Id | Assumption | Why |
|---|---|---|
| A-23 | A complaint spike is at least 2 tickets in 24 hours that would be unlikely given the last 30 days (Poisson test, p < 0.01). | The brief asks for a real method but gives no window or threshold. |
| A-19 | A customer with no ticket history is assumed to get one ticket every 10 days. | The spike test needs some baseline. |
| A-24 | Tickets with wording similarity of 0.2 or more share a root cause. | There's too little data to tune this. |
| A-25 | A BOOKED order still not picked up 60 minutes after its window ends counts as a missed pickup. | Pickup confirmations can arrive up to 20 minutes late. |
| A-36 | A label counts only if 4 of 5 runs agree (2 of 3 for each chat message), each backed by evidence from the text. Otherwise the safe option applies. | The brief sets no confidence level, and a close split shouldn't be decided by chance. |
| A-37 | A Prompt Guard 2 score of 0.5 or more counts as hidden instructions. It adds a warning and never grants access. | The brief sets no threshold, so I used the midpoint. |
| A-38 | The sentence-by-sentence answer check is switched off. | When I tested it, it removed correct facts and made answers too slow for the latency target. A wrong fact with a real citation is a known gap instead (see EVALUATION.md). |

A-01, A-19, A-23, A-24 and A-37 are guesses I'd revisit with real data. Each one is a setting in `config.py` or
`detect.py`.
