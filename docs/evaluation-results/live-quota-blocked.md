# Live evaluation: provider quota blocked

Recorded at: 2026-11-19T00:52:50.690878+00:00. Model: `gpt-6-luna`; real Responses API.

The key was loaded from the ignored root `.env` without interpolation or logging.
Docker and the pinned image were available. OpenAI returned `insufficient_quota`
for four HTTP attempts; the fifth fixture was blocked before dispatch by the $1 guard.
No successful model response, patch, or live Docker comparison was produced.

| Fixture | Result | End-to-end seconds | HTTP attempts | Reported input/output tokens | Cost upper bound USD |
| --- | --- | ---: | ---: | --- | ---: |
| arithmetic | provider_quota | 1.713 | 1 | 0/0 (usage unavailable) | 0.23265 |
| off_by_one | provider_quota | 0.923 | 1 | 0/0 (usage unavailable) | 0.23265 |
| boolean | provider_quota | 0.922 | 1 | 0/0 (usage unavailable) | 0.23265 |
| dictionary | provider_quota | 0.623 | 1 | 0/0 (usage unavailable) | 0.23265 |
| conversion | evaluation_cost_budget | 0.028 | 0 | 0/0 (usage unavailable) | 0.00000 |

**Investigation success, evidence accuracy, patch validity, baseline/patched test results,**
**and repair success rate: N/A for every fixture.** This is an infrastructure-blocked run,
not a measured 0/5 repair score. Zero reported tokens do not establish zero billing.

Reported-usage cost: **$0.00**. Invoice-confirmed expenditure: **unknown**.
Conservative cumulative cost upper bound: **$0.93060**, within the authorized **$1.00**.
Four unresolved reservations remain in the ledger. No further live requests were made.

The raw JSON is preserved unchanged. Its `COMPLETED` status meant the fixture loop
finished, not that inference succeeded. The harness now stops the whole suite after
the first quota/authentication failure and marks it `BLOCKED`, leaving subsequent
fixtures `NOT_RUN`. This correction was validated offline, without another paid attempt.

Artifacts: [raw results](live-quota-blocked.json), [cost ledger](live-quota-cost-ledger.jsonl).
The local SQLite trace is intentionally not committed. Fixtures and test expectations
were not changed. Confirm billing/quota and obtain renewed authorization before a
new run; do not reset this ledger to bypass its outstanding reservations.
