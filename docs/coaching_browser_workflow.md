# Interview coaching in Saved Jobs

## Live walkthrough

1. Open the Google test job in Saved Jobs. Let its saved interview guide load.
2. Scroll below Company research and interview guide to **Interview practice**.
3. Click **Start new practice session**. This saves the five guide questions and
   their approved-profile snapshot without making an AI request.
4. Type a fictional test answer into **Your practice answer** and click **Submit
   answer for feedback**. Read all six dimensions and the suggestions.
5. If a follow-up appears, answer it using the same input. The workflow permits
   at most one follow-up per main question, including after a retry.
6. After feedback, use **Retry main question** or **Next question**. Use **Skip
   question** when appropriate.
7. Click **Pause**, close Saved Jobs, and reopen the same job. Its saved session
   should load paused, at the same question, with its answers and feedback intact.
   Click **Resume** to continue.
8. Skip through the remaining questions. Confirm **Five-question session
   complete**, expand saved history, and optionally download that history.

New sessions preserve old sessions. Use **Saved practice sessions** to reopen an
earlier one. Reload session, pause/resume, and other session controls do not call
the model. A submitted answer sends the question, answer, and the guide's approved
profile snapshot to the configured provider; usage charges may apply. Practice
claims never update the approved career profile.

## Reliability and source versions

- All routes reuse the capture token and typed job/session UUIDs. Paths are kept
  server-side. Each session has its own SQLite checkpoints and immutable creation
  metadata, separate from career-profile data.
- New sessions require the currently saved guide and current preparation inputs.
  Current-guide validation is shared with the preparation API.
- An existing session remains pinned to its original guide and profile snapshot.
  If preparation changes, the interface labels it as an earlier snapshot. Its
  progress remains available; start a new session to use updated inputs.
- Revision checks reject stale-tab mutations. File locks serialize cooperating
  server threads/processes for a session.
- Request IDs and operation receipts prevent a completed answer or command from
  being repeated when a response is retried. A repeated completed request returns
  the current session without another model call.
- An evaluation budget slot is checkpointed before evaluation. Failed or
  interrupted attempts consume a slot; there are at most four per main question.
  An interrupted request ID is not automatically replayed. Reload saved progress
  before explicitly choosing a new attempt.
- This cannot establish what an external provider did during a lost connection.
  It preserves local request identity and budget rather than silently retrying.
- Ratings are practice feedback, not hiring predictions. Human review is still
  needed to assess feedback quality and identify unsupported statements.

## Automated checks

```bash
python -m pytest -q
node --test tests/test_resume_ui.cjs tests/test_preparation_ui.cjs tests/test_coaching_ui.cjs
git diff --check
```

The Node tests use built-in modules; no npm installation is required. Tests cover
checkpoint restoration, one-follow-up and request limits, explicit start,
authentication, concurrent operations, stale tabs, interrupted evaluations,
request reuse, old guide snapshots, and browser control states. The live extension
walkthrough completes verification with the configured provider.
