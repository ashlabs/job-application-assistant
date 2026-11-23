# Review and correct extracted requirements

Saved Jobs now has **Review or correct requirements** under the extracted requirements. Extraction still occurs only when requested. Opening the editor, cancelling, and saving corrections make no AI requests.

The editor supports requirement wording, qualification versus practical constraint, required/preferred/unspecified importance, exact supporting excerpts, adding and removing items, and correcting the company name or job title. It preserves IDs for remaining rows. Source excerpts must occur in the original captured JD, which is never overwritten by requirements review.

Before saving, check **I reviewed these exact requirements and supporting JD excerpts**. Changing a field resets this confirmation. Cancel discards the edits. The backend validates coverage provenance, identifiers, and size, rejects duplicate descriptions after case/whitespace normalization, and writes the previous and new snapshots to `requirement_review_history` in the same SQLite transaction as the current extraction update. This is a local correction history, not a separate career-profile approval.

Duplicate detection is deterministic and limited to equal descriptions after case, whitespace, and trailing period/semicolon normalization. It does not detect every semantic overlap. Duplicate extractions remain readable so the editor can fix them. The validator verifies source excerpts, not whether edited wording logically follows from them; the reviewer must check that relationship.

Concurrent editors use the exact requirements revision. A stale save is rejected with a request to reopen the editor. Retrying the exact saved result is harmless and does not create duplicate history records. A network error keeps the edited draft visible; reopen the job to check whether the save succeeded before changing it further.

Changed requirements invalidate dependent match reports and resume approvals and make existing interview guides outdated through their existing source hashes. The browser clears and reloads dependent views after a save. Existing practice sessions remain pinned to their old guide snapshots and display the existing outdated-context warning; a new session needs a current guide. Stored artifacts are retained rather than deleted. An unchanged save leaves their hashes intact.

## Local live check

1. Restart the API, reload the extension, close Saved Jobs, and open it again.
2. Open the fictional Software Engineer capture used for the onsite blocker check. You should already see its saved requirements and match.
3. Click **Review or correct requirements**. Change the Python qualification's importance to **preferred**, leaving its exact supporting excerpt intact.
4. Confirm the checkbox and click **Save reviewed requirements**. The updated importance should appear in the main requirement list. The former match should no longer be displayed as current. No assessment runs automatically.
5. Close/reopen this job and verify the correction persisted. Click **Assess profile match** to explicitly create a report using the corrected requirements. The onsite condition should still be a blocker for the remote-only test profile.
6. Optionally reopen the editor and put an excerpt absent from the JD into a row. Try saving: it should fail without changing the saved requirements. Cancel the invalid edit. You can also verify that Cancel discards a valid unsaved change.

For a stale-tab check, open the editor for the same job in two Saved Jobs tabs.
Save a changed importance in the first; attempt a different change from the second.
The second save should be rejected and its edits retained for review.

## Checks

```bash
python -m pytest -q
node --test tests/test_*ui.cjs
git diff --check
```

Offline tests include authenticated reads/writes, no extra model calls, unchanged original captures, history, stable IDs, source and hash tampering, duplicate repair, size limits, concurrent saves, idempotent retry, match/resume/guide invalidation, confirmation reset, cancel, failure preservation, and delayed old-tab responses.
