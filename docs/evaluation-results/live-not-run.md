# Live repair evaluation

Status: NOT_RUN
Model: gpt-4.1-mini
Reason: OPENAI_API_KEY unavailable; no inference or Docker evaluation performed.

| Fixture | Outcome | Generated | Validated | Approved | Docker tested | Repair |
| --- | --- | --- | --- | --- | --- | --- |
| arithmetic | NOT_RUN | False | False | False | False | False |
| off_by_one | NOT_RUN | False | False | False | False | False |
| boolean | NOT_RUN | False | False | False | False | False |
| dictionary | NOT_RUN | False | False | False | False | False |
| conversion | NOT_RUN | False | False | False | False | False |

A successful repair means the fixed fixture tests passed in Docker; it is not
a general correctness proof. No source is executed on the host.
