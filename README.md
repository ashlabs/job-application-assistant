# Job Application and Interview Assistant

This semi-autonomous assistant helps a candidate capture job descriptions, document career evidence, compare qualifications, prepare a resume, and practice interviews. Career intake and interview coaching use checkpointed LangGraph workflows. Other stages combine structured AI responses with deterministic validation, scoring, storage, and document generation. The user reviews career facts and resume drafts before approval, and practice answers never update the approved profile. The system runs locally with a Chrome extension and makes provider requests only for explicitly requested AI operations.

## Requirements

- macOS or Linux; Python 3.11 or newer. File locking uses `fcntl`; native Windows is not supported.
- Chrome for the extension.
- Node.js 22 or newer for the browser-control tests; these use the built-in test runner and need no npm packages.
- An OpenAI API key and model supporting strict structured output for live AI features.

The pinned snapshot in `requirements.txt` was generated from the working Python
3.12 Linux environment. Fresh-install results are recorded in
[offline verification](docs/evidence/offline_verification.json). The developer's
macOS/Python 3.14 environment also needs the local verification steps when applying
this release; do not infer cross-platform validation from the Linux record.

## Install

From the submitted branch or commit:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m pip check
python agentic_system.py --help
```

`requirements.txt` pins the tested runtime and test dependencies. `pyproject.toml`
declares the application dependencies, including document export. For development
without the pinned snapshot, `python -m pip install -e '.[dev]'` resolves compatible
packages, but that does not reproduce the exact tested environment.

For a fresh clone, copy `.env.example` to `.env` and set `OPENAI_API_KEY`,
`OPENAI_MODEL`, and a locally generated `CAPTURE_API_TOKEN`. Set
`CAREER_PROFILE_PATH` to the profile you approve. These credentials and private
outputs are ignored by git. Tests do not need credentials.

## Run the workflow

1. Capture career facts using the CLI:

   ```bash
   python -m job_application_assistant.interview_cli \
     --session career-intake \
     --profile-dir data/private/profile
   ```

   Supply employment, education, preferences, skills, projects, and personal
   contributions. Use `/draft`, `/review`, and `/approve UUID` to save an exact
   proposal. `/pause`, `/resume`, and `/quit` preserve session progress. Use
   `/new` for a new story; the CLI shows its supported commands. There is no
   `/status` command.
2. Start the local API:

   ```bash
   python agentic_system.py serve
   ```

   The installed `agentic-job-assistant serve` command is equivalent. The server
   binds to `127.0.0.1:8000`; it is not a public web service.
3. In Chrome's extension manager, enable Developer mode and load
   `chrome-extension/` as an unpacked extension. Set the matching capture token
   in the extension's Connection settings.
4. Capture a job description using the popup. Review/edit the captured text before
   saving, then open Saved Jobs. Extract requirements, inspect their exact JD
   excerpts, and use **Review or correct requirements** to fix extraction errors.
5. Click **Assess profile match**. Inspect every explanation, profile citation,
   per-qualification credit calculation, and the separate practical constraints.
   Sort Saved Jobs by documented match if helpful. The percentage measures
   documented alignment, not hiring probability or an employer's ATS score.
6. Generate a resume draft, inspect its text and evidence, confirm the exact draft,
   approve, and export DOCX/PDF. Exports are single-column; inspect their layouts.
7. Supply official company source URLs, confirm/review captured sources, and
   generate an interview guide. Add recruiter guidance when available.
8. Start practice from a current guide. Answer five questions with feedback,
   optional follow-ups, and retry/skip/pause/resume controls. The system permits
   at most one follow-up and four evaluation requests per question, including
   failures. Saved practice claims remain separate from approved career facts.

Detailed walkthroughs:
[resume](docs/resume_browser_workflow.md),
[company research and guide](docs/preparation_browser_workflow.md),
[coaching](docs/coaching_browser_workflow.md),
[profile facts and constraints](docs/profile_facts_and_constraints.md),
[requirements review](docs/requirements_review_workflow.md), and
[scoring](docs/scoring_transparency.md).

## Verify and record evidence

```bash
python -m pytest -q
node --test tests/test_*ui.cjs
git diff --check
```

These are offline tests with injected provider responses. They exercise the actual
application logic but do not establish live model quality. The saved Linux
verification record contains the actual command outputs and dependency versions.

After completing a workflow on a fictional test capture, with the API running:

```bash
python agentic_system.py evidence --capture-uuid YOUR_CAPTURE_UUID
```

This makes authenticated GET requests to the fixed local API and saves selected
outputs under `data/private/evidence/`. It records missing outputs and outdated
responses honestly; it does not assess, generate, approve, export, or submit
anything. An optional `--session-uuid` selects a particular practice session;
otherwise it records the latest listed session if present. Review the bundle
before sharing it. See [evidence walkthrough](docs/evidence_workflow.md).

To refresh the lock after an intentional dependency change, run the tests in the
project environment, then:

```bash
python scripts/freeze_environment.py
```

The script checks dependencies and writes exact pins without an editable project
path. Re-test the resulting lock in a fresh environment before committing it.

## Implementation map

| Component | Source |
| --- | --- |
| Capstone entry point / local server launcher | `agentic_system.py`, `system_cli.py`, `capture_api.py` |
| Career intake, state, conditional routing | `interview_agent.py`, `interview_state.py`, `interview_graph.py` |
| Exact proposal approval and history | `profile_review.py`, `profile_storage.py` |
| JD extraction and user corrections | `job_requirements_agent.py`, `requirements_review.py` |
| Evidence validation, credit policy, versioned cache | `profile_match_validation.py`, `profile_match_scoring.py`, `profile_match_storage.py` |
| Resume selection, approval, export | `resume_draft.py`, `resume_review.py`, `resume_export.py` |
| Captured company sources and guide | `company_research.py`, `interview_guide.py`, `preparation_api.py` |
| Bounded coaching and persistence | `interview_coaching.py`, `coaching_api.py` |
| Browser workflow | `chrome-extension/` |

Package modules are under `src/job_application_assistant/`. The entry point launches
this implementation; it does not add another planner, supervisor, or agent layer.

## Limits and submission status

Source validation checks record identity and exact excerpts, not whether an AI
explanation logically follows. The user must review the reasoning. Company
research uses user-selected URLs, not autonomous web discovery. Resume selection
currently uses employment, stories, and education; standalone skill/project facts
are available for matching and guides but do not add new resume sections. This
prototype does not discover jobs or submit applications automatically, and it
uses one local user's files rather than a hosted account system.

The implementation and offline checks are available. Sanitized raw live evidence,
the final design-report PDF, and the final rubric/submission audit remain to be
completed. See [scope](docs/project_scope.md) and
[evidence record](docs/evidence/live_observations.md). Test counts are not a rubric
score or a claim of submission readiness.
