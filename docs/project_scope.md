# Job Application and Interview Assistant

## Purpose

The application helps a user assess job opportunities, prepare application materials from approved career evidence, and practice interviews. It runs locally for one user and uses OpenAI with a configurable model. Saved profiles, job records, derived outputs, and checkpointed sessions preserve progress between interactions.

## Implemented workflows

### 1. Job description capture and requirements review

A Chrome extension captures job description text, source URL, page title, and capture time. Selected text and manual paste provide alternatives when automatic extraction is incomplete. The user reviews the captured text before saving it. Failed saves preserve the draft, and request identifiers allow safe retries.

Structured model calls extract qualifications and practical constraints with exact supporting excerpts. Qualifications have required, preferred, or unspecified importance. The user can correct wording, importance, excerpts, and classification through the requirements editor. Saving checks the source excerpts and current revision, preserves correction history, and makes dependent outputs outdated.

Duplicate requirement detection checks equal descriptions after case, whitespace, and trailing period/semicolon normalization. It does not detect every semantic overlap. Separate captures of the same job are not automatically identified as duplicates.

### 2. Career experience capture

An adaptive text interview gathers preferences, employment history, education, skills, projects, and accomplishments. Accomplishment stories use Situation, Task, Action, Result, and Reflection. The interviewer asks follow-up questions, distinguishes personal contributions from team outcomes, and proposes structured updates.

Only explicitly approved proposals update `career_profile.md`. Draft facts, unresolved questions, and practice answers remain separate from the approved profile. Records retain stable identifiers, and approved changes retain version history. Checkpointed sessions support pausing and resuming. Persistent skipping of individual intake topics remains a product limitation.

### 3. Documented qualification matching and practical compatibility

The model assesses each qualification against the approved profile. Python validates record references and exact excerpts, then calculates the documented match percentage.

| Classification | Meaning | Credit |
| --- | --- | --- |
| Strong match | Approved evidence directly demonstrates the qualification. | 1.0 |
| Transferable experience | Approved evidence demonstrates related experience. | 0.5 |
| Evidence missing | The profile contains insufficient evidence to assess the qualification. | 0.0 |
| Confirmed gap | Approved evidence establishes that the qualification is not met. | 0.0 |

Required qualifications have weight 2; preferred qualifications have weight 1. Earned credit is the weight multiplied by the classification credit. The percentage is total earned credit divided by total available credit, multiplied by 100 and rounded once to one decimal using Python `round`. Unspecified importance and practical constraints are excluded. With no scoreable qualifications, the result is unavailable rather than zero.

For example, earning 4 of 7 weighted credits produces a documented match of 57.1%. The percentage measures documented alignment, not hiring probability, an employer's ATS score, or candidate ability. The weights and classification credits have not been validated for ranking effectiveness.

Saved Jobs supports sorting by documented match. The detailed view shows qualification explanations, supporting evidence, individual credit contributions, and the scoring-rule version. Practical compatibility appears separately as compatible, needing clarification, or blocking, with supporting profile evidence where required. An ambiguous location does not by itself establish willingness to commute or relocate.

Saved assessments are tied to the approved profile, requirements, and scoring-rule versions. Changes make earlier assessments outdated. Reassessment is explicitly requested by the user.

### 4. Resume preparation

The model selects and orders existing employment, accomplishment stories, and education for the target job. Python renders the selected facts without model-written embellishment. Standalone skill and project facts support matching and interview guides but do not currently appear as separate resume sections.

The user reviews the exact draft and evidence before approval. Export requires approval that remains valid for the draft and its source versions. The application produces single-column DOCX and text-based PDF files and checks extracted content against the approved text. It prepares documents without submitting an application. Employer-specific format guidance and comparisons with previous resumes remain future improvements.

### 5. Company research and interview-guide generation

The user supplies and confirms official company HTTPS URLs. The application captures bounded page text and source metadata; it does not autonomously discover sources. Source URLs, titles, retrieval times, and publication dates are retained when available.

The model combines reviewed sources, job requirements, approved career evidence, and optional recruiter guidance into a role-specific guide. Recruiter guidance takes precedence over general hiring information. Source citations distinguish documented company information from generated practice questions. Missing career evidence produces clarification requests rather than invented answer claims. Python validates source and profile references.

### 6. Interview coaching

Practice uses five main questions from a saved guide, with at most one follow-up per question. Feedback covers relevance, structure, specificity, ownership, results, and clarity. Python limits each question to four evaluation requests, including retries and failures.

Sessions support retry, skip, pause, and resume. Checkpoints preserve answers, feedback, question progress, and the guide/profile snapshot. Practice answers cannot update the approved career profile.

## Architecture

One local Python FastAPI backend serves the Chrome extension. Career intake uses a CLI, while Saved Jobs provides the main job-preparation and practice controls.

Career intake and interview coaching use LangGraph state graphs with SQLite checkpoints. Requirements extraction, matching, resume preparation, and company research and guide generation use Python services with structured model calls. There is no coordinating supervisor or autonomous multi-agent delegation.

Models interpret statements, classify evidence, select records, generate preparation material, and provide adaptive feedback. Python validates outputs, controls transitions and request budgets, calculates scores, checks input versions, stores approved artifacts, and renders documents. Users authorize profile changes and exact resume approval.

## Data and reliability controls

- Original job-description captures remain preserved.
- Approved facts remain separate from drafts and practice claims.
- Derived outputs retain their source versions; changes invalidate current status or approval.
- External content is treated as untrusted input.
- Request identities and bounded operations limit accidental repeated work.
- Credentials and private records are excluded from Git.
- Shared examples use fictional profiles and redacted outputs.

Exact excerpts establish traceability; they do not prove that an interpretation logically follows from the source. Human review remains necessary. Interrupted guide requests can require explicit recovery, and ranking usefulness has not been evaluated across varied profiles.

## Outside the current scope

- Automatic job discovery or application submission
- Voice interviews
- Multiple users or cloud deployment
- Chrome Web Store publication
- Multiple resume templates
- Guaranteed extraction from every website
- Guaranteed ATS acceptance or interview outcomes
