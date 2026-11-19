# Browser resume workflow

Select a captured job in Saved Jobs. Extract its requirements if necessary.
Enter the candidate name under Resume preparation, then explicitly generate a
draft. Generation sends approved profile evidence and saved requirements to the
configured model. Review the displayed resume and supporting profile records,
confirm review with the checkbox, and approve the exact draft. Prepare DOCX and
PDF, then use the two download links and inspect their layouts.

Reopening the job loads the most recent browser-generated draft without a model
call. CLI-generated drafts remain in their existing directories; this view does
not migrate or overwrite them. A changed approved profile or changed requirements
blocks approval and export of outdated drafts. Generate a new draft after updating
career facts through the career-profile approval flow.

## Design

- All routes reuse the capture API token. File paths stay server-controlled.
- Each job owns its browser-generated draft directories.
- A client request UUID prevents a successful generation from running again when
  its response is retried. Concurrent or incomplete requests do not trigger an
  automatic second model call. After an incomplete request, check the server and
  reload the job before explicitly generating a new request.
- Review and approval use the existing content hashes and evidence validation.
- Export rechecks current sources and approval, renders both formats in memory,
  and verifies their extracted text and reading order before returning downloads.
- Changing jobs discards old download links. Delayed lookups cannot display a
  previous job's draft or overwrite a newer generation result.
- Export prepares documents only; no application is submitted.

## Verification

Run `python -m pytest -q`, `node --test tests/test_resume_ui.cjs`, and
`git diff --check`. The Node tests use built-in modules and require no npm setup.
Then verify generation, evidence review, approval, DOCX/PDF download, and reopening
from the loaded Chrome extension with the local API running.
