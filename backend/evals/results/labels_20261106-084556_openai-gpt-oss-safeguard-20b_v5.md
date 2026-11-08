# Classifier check: labels `openai/gpt-oss-safeguard-20b`, request check `openai/gpt-oss-20b`

5 runs per document/ticket label (agreement needed: more than 75%), 3 per request check, temperature 1.0, reasoning effort medium. 128 calls, USD 0.0188, 79 s.

**118/120 correct (98%).**

| Task | Items | Correct | Undecided (handled fail-closed) |
|---|---|---|---|
| document type | 6 | 6 | 0 |
| in force | 6 | 6 | 0 |
| metadata | 30 | 29 | 0 |
| commercial section | 9 | 8 | 1 |
| ticket severity | 7 | 7 | 0 |
| reworded ticket severity | 20 | 20 | 0 |
| request check: actions | 21 | 21 | 0 |
| request check: outdated document | 21 | 21 | 0 |

## Not correct

- metadata: `05_Northstar_Logistics_Enterprise_Agreement / effective` expected 'not stated', got '2026-01-01'
- commercial section: `06_LumenWorks_Service_Agreement / 2. Cancellation terms` expected True, got None
