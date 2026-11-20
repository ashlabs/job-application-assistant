# Approved profile facts and practical compatibility

The career interview can propose preferences, standalone skills, and projects.
Each fact has a stable `fact_uuid`, a category, a name, and a statement. Facts
follow the same `/review` and `/approve UUID` process as employment and education.
Draft interview answers and coaching answers never update the approved file.

Facts are available as exact-field citations in qualification assessments and
interview guides. A preference is not evidence of competence. Skills and projects
are stored as the user described them, without invented proficiency, duration,
metrics, or outcomes. This batch does not add new resume sections: resume
selection still uses roles, stories, and education.

Practical constraints are assessed separately in the same matching request:

- **Compatible:** explicit approved evidence establishes compatibility.
- **Blocking constraint:** explicit approved evidence establishes a conflict.
- **Needs clarification:** the condition or the candidate's circumstances remain
  unclear. Missing facts never establish a blocker.

All constraints must be covered exactly once. Compatibility and blockers require
an existing profile record, an allowed field, and an exact excerpt. Validation
checks provenance and coverage; the AI provider interprets meaning. Review its
reasoning. A location alone does not establish willingness to relocate or commute.
Constraints contribute no qualification weight or credit and do not alter sorting
by documented match percentage. Saved reports are tied to profile and requirement
hashes. Reading a saved report makes no model request.

## Local live check

Use the fictional test profile, not your real career facts, for this check.
Restart the API after applying the patch and reload the extension. Close and
reopen Saved Jobs.

1. Run the existing career interview:

   ```bash
   python -m job_application_assistant.interview_cli \
     --session profile-facts-check \
     --profile-dir data/private/education-check
   ```

2. Enter: `For this fictional test profile, I only accept fully remote roles.`
   Use `/draft` to check for one `facts` entry with category `preference` and a
   statement preserving the restriction. No role or story should be created.
   Use `/review`, inspect the proposed diff, and approve its exact UUID only if
   the proposal is correct. Existing education and experience should remain.
3. In Saved Jobs, open a posting that **explicitly requires onsite work** and
   extract its requirements if needed. An office location without an onsite
   requirement is insufficient for the blocker check; use a fresh test capture
   with an explicit onsite requirement if necessary.
4. Click **Assess profile match**. In **Practical compatibility**, verify that the
   onsite requirement is blocking with the remote-only preference cited. Unknown
   conditions should say **Needs clarification**. Neither result should award
   or remove qualification credit.
5. Reopen the job. The saved report should appear without another assessment.
6. Optionally correct the fictional preference through the interview, then review
   and approve it. Reopen the job: the old report should no longer be current.
   Reassess to use the newly approved statement.

The added `facts` field changes the canonical profile representation once for
older files. Existing approved profile files remain readable and are not edited
automatically. Previously cached matches, resume approvals, and preparation
snapshots may need regeneration/review because their source hash is older.
Do not treat that refresh as a newly approved career fact.

## Automated checks

```bash
python -m pytest -q
node --test tests/test_*ui.cjs
git diff --check
```

Tests cover fact-only intake, stable identity, approval boundaries, backward
profile loading, duplicate and ambiguous updates, citation tampering, constraint
coverage, unchanged scoring, profile-change invalidation, authenticated API
persistence/reuse, and separate browser rendering.
