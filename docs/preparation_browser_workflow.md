# Company research and interview preparation in Saved Jobs

## Live walkthrough

1. Open a saved job and extract its requirements if necessary.
2. Scroll to **Company research and interview guide**, after Resume preparation and before the original Job description.
3. Enter one to five official HTTPS URLs, one per line. For the Google test job, use `https://about.google/`.
4. Confirm that these are official company sources, then click **1. Capture sources**. This makes bounded web requests without an AI call.
5. Expand the source title. Review its captured text, URL, retrieval time, and publication date, if available. Check **I reviewed the captured sources**.
6. Optionally enter actual recruiter guidance. Keep it separate from candidate experience; it takes precedence over general company hiring information.
7. Click **2. Generate interview guide**. This sends the saved qualifications, approved profile, captured sources, and recruiter guidance to the configured provider. Review the resulting draft and its supporting evidence.
8. Download the Markdown guide if useful. Close and reopen the job: saved sources and the current guide load without another source fetch or model call.

With only Google's company homepage captured, hiring stages should remain **Not established by the captured sources**. Practice questions are generated, not company-published questions or predictions. Missing candidate evidence should produce a clarification prompt rather than an invented answer.

## Design and limits

- All preparation routes reuse the capture API token and typed job/request UUIDs. Filesystem paths stay server-controlled, with preparation stored per job.
- User confirmation identifies official sources; the application does not independently establish company ownership or search for sources autonomously.
- URLs must use HTTPS. The default fetcher rejects private and loopback DNS destinations before retrieval and does not follow redirects. If a page redirects, review and supply its final official HTTPS URL.
- Capture is limited to five pages, 2 MB per page, a 20-second timeout per page, and 80,000 extracted characters per collection. Static HTML can omit dynamic content. No truncation is silently presented as a complete source.
- Source review is tied to the exact saved collection hash. A newer collection, changed source file, approved profile change, or JD change flags the old guide for refresh. Generate again using reviewed current inputs.
- Successful request retries reuse stored results. Incomplete requests do not automatically repeat web or model calls. Check the local server and reopen the job before explicitly starting a new request after an interrupted operation.
- Company notes, recruiter guidance, and candidate evidence remain separate. Recruiter guidance is labeled user-supplied. It does not update the profile.
- Source and candidate citations are validated against exact excerpts. Semantic support and usefulness still require human review.
- Existing CLI research/guide files are preserved; browser preparation has its own per-job directories and does not migrate those earlier outputs.

## Checks

```bash
python -m pytest -q
node --test tests/test_resume_ui.cjs tests/test_preparation_ui.cjs
git diff --check
```

The browser-control tests use Node's built-in runner; no npm install is needed. They exercise control gating, saved-result loading, recruiter guidance, stale results, source URL edits, and delayed results when switching jobs. Perform the live extension walkthrough as the final check.
