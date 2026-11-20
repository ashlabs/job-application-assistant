# Recording representative workflow evidence

Use fictional career facts for shareable examples. The evidence command reads only
the selected saved job and its related outputs from the local API. It makes no
provider calls and does not turn old outputs into a new live run.

## Record an existing workflow

1. Start the API with `python agentic_system.py serve`.
2. Open a test job in Saved Jobs and copy its displayed capture UUID.
3. Run:

   ```bash
   python agentic_system.py evidence --capture-uuid YOUR_CAPTURE_UUID
   ```

4. The printed directory contains a JSON bundle and a short status table. Review
   every recorded response: null means no saved output; HTTP 409 can mean an
   outdated artifact or unmet prerequisite. Those are observed results, not a
   collector-generated assessment.
5. If the job has several practice sessions, select one explicitly:

   ```bash
   python agentic_system.py evidence \
     --capture-uuid YOUR_CAPTURE_UUID \
     --session-uuid YOUR_SESSION_UUID
   ```

The default output directory is private and ignored by git. `--output-dir` can
choose a new directory. Existing directories are not overwritten. The recorder
uses only `CAPTURE_API_TOKEN` and never serializes request headers or `.env`.
Selected job/profile/practice content can still contain personal data, so inspect
it before copying a sanitized bundle into submission evidence.

## Representative cases for the final report

| Case | Inputs / actions | Evidence to inspect |
| --- | --- | --- |
| Documented match | Approved fictional profile; reviewed JD requirements; explicit assessment | Exact qualification/profile excerpts, current score version, row-credit totals |
| Missing information | A requirement whose dates or experience are not documented | Missing-evidence explanation, rather than invented years or an unsupported gap |
| Practical ambiguity and conflict | Location-only JD versus explicitly onsite JD; remote-only preference | Clarification for ambiguity; cited blocker for explicit conflict; no percentage penalty |
| User correction | Correct one requirement's importance, save, and reassess | Corrected requirements and the current report's changed denominator if applicable |
| Resume | Generate, review, approve exact text, export | Approved draft state and evidence; inspect exported DOCX/PDF layouts separately |
| Guide and coaching | Review official sources, generate guide, answer and pause practice | Source citations, five questions, six feedback dimensions, optional follow-up, persisted history |
| Outdated artifact | Correct approved facts or requirements after preparing an output | Actual 409/outdated response and the pinned practice-context warning if present |

The JSON includes saved outputs and content hashes. It is not a cryptographically
signed audit log and does not capture the original provider request time, full
model trace, or DOCX/PDF bytes. Do not infer provider/model provenance when absent.
The course report should pair inspected outputs with a description of actual user
actions, observed decisions, and at least one limitation. Do not present injected
unit-test feedback as live model feedback.

## Fresh-environment verification on macOS

Keep the working environment available while checking the pinned snapshot:

```bash
python3 -m venv /tmp/job-assistant-repro-check
/tmp/job-assistant-repro-check/bin/python -m pip install -r requirements.txt
/tmp/job-assistant-repro-check/bin/python -m pip install -e . --no-deps
/tmp/job-assistant-repro-check/bin/python -m pip check
/tmp/job-assistant-repro-check/bin/python -m pytest -q
/tmp/job-assistant-repro-check/bin/python agentic_system.py --help
node --test tests/test_*ui.cjs
```

Choose another unused path if that environment already exists. The committed
Linux verification record does not replace this macOS/Python-version check.
