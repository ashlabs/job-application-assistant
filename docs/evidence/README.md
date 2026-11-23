# Reviewed execution evidence

`reviewed_live_cases.json` contains selected, redacted fields derived from three
user-uploaded saved API snapshots. These are previously executed outputs, not new
model runs. Collection times are UTC and are not inferred provider execution times.

| Case | Observed saved behavior |
| --- | --- |
| A | Changed profile/company context invalidated resume, research, and guide; the old practice session was marked outdated. |
| B | Resume and research were refreshed, while the guide still required refresh. |
| C | Eight reads succeeded; the approved resume, current guide, and practice session were consistent with current sources. |

The current match has 4 of 17 weighted credits (23.5%), two strong qualifications,
nine with missing evidence, and two practical constraints excluded from scoring.
The completed bachelor's degree and leadership story support the strong matches.
The in-progress master's does not count as an awarded degree.

The public file retains the fictional approved profile, requirements, match,
resume, guide citations, and numeric practice feedback. It omits personal practice
answers, their feedback explanations, the resume review token, and full JD/page
text. Raw uploads remain private and are not required to run the application.
The original bundle hashes support later comparison if the owner retains those
files; they do not authenticate the execution or prove the model's reasoning.

Independent review checked all 24 response-body hashes, exact JD excerpts, match
validation and score recomputation, guide citations, resume rendering, and the
current practice-to-guide identity. A valid excerpt proves provenance, not that
an interpretation is correct. Subjective practice ratings are not a calibrated
assessment of candidate ability.

`offline_verification.json` records historical fresh-install command outputs and source hashes from the reproducibility batch. Documentation changes after that batch do not imply a new fresh install.
Its regression checks use injected provider responses; no live provider requests
were made for report preparation. Earlier user observations are summarized below.
The interrupted guide request and explicit recovery are discussed in the report;
its original failure cause was not established.

See `docs/evidence_workflow.md` to collect a new private snapshot without making
new AI requests. Review any resulting file before sharing it.

## Earlier user-reported observations

These observations were reported during development using the local application
and a fictional career profile. They are not newly executed provider calls, a
complete transcript, or a quantitative model evaluation. Original run timestamps,
provider identity, and model names were not captured alongside these excerpts.
The evidence collector can preserve current saved outputs.

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
