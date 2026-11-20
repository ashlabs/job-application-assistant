# User-verified live observations

These observations were reported during development using the local application
and a fictional career profile. They are not newly executed provider calls, a
complete transcript, or a quantitative model evaluation. Original run timestamps,
provider identity, and model names were not captured alongside these excerpts.
The evidence collector added in this batch can preserve current saved outputs.

| Case | Reported observation | What it supports / limitation |
| --- | --- | --- |
| Completed versus ongoing education | Bachelor's degree matched with qualification, status, and field citations. The ongoing master's did not count as an awarded degree. | Observed education handling; does not prove all degree alternatives are interpreted correctly. |
| Approved profile changes | Changing the bachelor's completion year made the prior match no longer current. | Observed profile-version invalidation. |
| Coaching | The user received six feedback dimensions and suggestions on education and team leadership answers; a follow-up was saved for the education question. | Observed live feedback and follow-up history, not an independently validated quality score. |
| Ambiguous practical conditions | Kirkland location and in-person interviews both needed clarification for a remote-only profile. | The system did not infer an onsite requirement or interview refusal solely from a location/work preference. |
| Explicit practical conflict | A fictional JD required onsite work in Kirkland five days per week with no remote option. The report showed a blocking constraint against the approved fully remote preference. | Observed constraint reasoning; excluded from qualification credit. |
| Requirements correction | The user confirmed that edited requirements persisted after explicitly saving the review. | Observed persistence, rather than unsaved editor changes. |
| Scoring transparency | The user confirmed the versioned report and credit breakdown live check. | Observed interface verification; raw totals were not pasted into the chat. |

A relevant observed limitation was ambiguous practical compatibility: a location
alone could not resolve whether a remote-only candidate could accept the role.
Another user-facing issue was that grey URL example text looked like entered data;
the interface now states that users must enter actual URLs. These are development
observations, not invented failure transcripts.

Before submission, preserve and inspect actual saved JSON for representative
fictional captures and practice sessions using `agentic_system.py evidence`.
Only describe outputs present in those bundles. Keep missing or outdated outcomes
visible instead of replacing them with sample successes. Any public evidence copy
must be checked for personal career information and credentials first.
