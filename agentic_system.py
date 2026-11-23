"""# Job Application and Interview Assistant

## Task and architecture
A single local backend hosts focused semi-autonomous workflows. The user enters
career statements through the interview CLI and invokes job operations through
Chrome. Career intake routes validate_draft -> interview only while collecting;
coaching executes bounded feedback turns. Both use LangGraph SQLite checkpoints.
Python services perform JD extraction, evidence matching, record selection,
selected-page retrieval, guide generation, validation, scoring, and document
rendering. There is no supervisor or autonomous multi-agent delegation.

## Persona and authority
The intake model is a factual career interviewer; the coaching model provides
supportive practice feedback. Models return typed proposals and interpretations.
Only explicit user approval saves profile proposals or authorizes resume exports.
Approved Markdown facts remain separate from session memory and practice claims.

## Configuration and invocation
Install the pinned requirements and the package as described in README.md.
Set the local configuration in .env, then run `python agentic_system.py serve`.
Use `python -m job_application_assistant.interview_cli --help` for career intake.
Use `python agentic_system.py evidence --capture-uuid UUID` to record saved outputs.
The configured AI API and selected public HTTPS pages are external capabilities;
reading saved evidence makes no AI request. Actual implementation is delegated to
the modules under src/job_application_assistant, not reimplemented in this launcher.

## Observed runs and limitations
The reviewed examples are in docs/evidence/reviewed_live_cases.json. Snapshot A
retains outdated resume/research/guide conflicts; snapshot B shows partial refresh;
snapshot C records eight successful reads, 4/17 credits (23.5%), an approved resume,
a five-question guide, and practice tied to the current guide. These are selected
and redacted actual saved outputs, not newly generated model traces. Figure 1 and
the full design explanation are in docs/Agentic_AI_System_Design_Report.pdf.

## Summary
This project prepares job applications and interviews through a local application
with checkpointed career-intake and coaching workflows. Structured model responses
support interpretation while Python validates records, versions inputs, calculates
credit, and renders approved facts. Reviewed executions showed both stale-output
rejection and a refreshed match, resume, guide, and coaching session. An incomplete
guide request required explicit recovery, demonstrating a usability limitation.
Exact citations and human approval support control, but they do not establish
semantic correctness, fairness, or hiring effectiveness.
"""

from job_application_assistant.system_cli import main


if __name__ == "__main__":
    main()
