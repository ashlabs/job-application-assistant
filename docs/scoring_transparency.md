# Scoring transparency and rule versions

Saved Jobs shows the scoring-rule version and each qualification's contribution. For example, a required qualification with transferable experience shows:

> Scoring: weight 2 × classification credit 0.5 = 1 of 2 weighted credits.

This release labels the existing policy `documented-alignment-v1`. It does not change the formula or award additional credit.

| Item                                     | Policy                                                  |
| ---------------------------------------- | ------------------------------------------------------- |
| Required qualification weight            | 2                                                       |
| Preferred qualification weight           | 1                                                       |
| Strong match credit                      | 1                                                       |
| Transferable experience credit           | 0.5                                                     |
| Missing evidence or confirmed gap credit | 0                                                       |
| Unspecified importance                   | Excluded; review the requirement                        |
| Practical constraints                    | Excluded; assessed separately                           |
| Percentage                               | Earned weighted credit / possible weighted credit × 100 |
| Rounding                                 | Once at the end, to one decimal, using Python `round`   |
| No scoreable qualifications              | Not available, rather than 0%                           |

The AI provider supplies evidence-backed classifications, never weights, numeric credit, percentages, or rule-version labels. Python calculates all credit details from the validated classifications and requirements. Contributions follow JD order and include unspecified qualifications with an explicit exclusion reason. Practical constraints do not appear as qualification contributions.

## Versioned storage

Matches now use four cache keys: capture UUID, requirements hash, approved profile hash, and scoring-rule version. The payload must agree with the stored version. Current cached matches load without another model request. Reports from older or unversioned rules are not used for percentages or saved-job ranking.

Existing unversioned reports remain in the local database. Reading them neither migrates storage nor calls AI. When the user explicitly clicks **Assess profile match**, the first new save atomically upgrades the table's primary key, retains legacy payloads under `unversioned`, and stores the current report separately. Failures roll back the whole migration. The existing confirmation text about AI usage applies to this reassessment; it may incur a provider charge.

Because older reports did not record a policy version, they need one explicit reassessment after applying this patch. This does not modify the approved profile or job requirements. Resume approvals and interview guides depend on those sources and are not invalidated solely by the new scoring-version label.

Developers must bump `SCORING_RULES_VERSION` in `scoring_rules.py` whenever weights, classification credit, exclusions, rounding, or assessment interpretation rules change. Version labels are immutable. The UI displays API-supplied credit values; it does not compute an independent percentage.

## Local live check

1. Restart the API, reload the extension, and close/reopen Saved Jobs.
2. Open the fictional Software Engineer job used for the earlier tests. Its old report may no longer be current because it was saved without a rule version.
3. Click **Assess profile match**. Verify **Scoring rules: documented-alignment-v1** appears beneath the total.
4. Verify each scored qualification shows its weight, classification credit, and earned/possible weighted credit. The Python qualification marked preferred in the previous live check should have weight 1. Missing evidence should earn 0.
5. Check that the onsite blocker remains under **Practical compatibility**, outside the credit total. Expand **How the documented match is calculated** to see the formula and exclusions.
6. Close/reopen the job. The versioned saved report and scoring details should load without requesting another assessment.

## Automated checks

```bash
python -m pytest -q
node --test tests/test_*ui.cjs
git diff --check
```

Tests cover every classification/importance combination, reconciliation of row credits and totals, exclusions, rounding, current-cache reuse, mismatched version rejection, legacy-data retention, atomic migration rollback, concurrent saves, explicit API reassessment, saved-job summaries, and browser credit/version display.
