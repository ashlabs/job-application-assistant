# Job Application and Interview Assistant

## Purpose

Help a user assess job opportunities, prepare truthful and relevant
application materials, and practice for interviews.

## Submission Scope

The application will run locally for one user, preserve progress between
sessions, and use OpenAI with a configurable model.

### 1. Job Description Capture

A Chrome extension captures job description text, source URL, page title, and 
datetime. The user reviews and corrects the capture before saving it to the Job Inbox.

Automatic extraction is best effort. Selected text and manual paste
provide fallbacks. Failed saves preserve the draft for retry. Repeated captures are flagged for review.

### 2. Career Experience Capture

An adaptive, text-based interview gathers career preferences, employment history,
educational qualifications, skills, projects, and accomplishments.

Accomplishments and interview stories use STAR plus Reflection: (S)ituation, (T)ask, (A)ction, (R)esult, and (R)eflection.

The agent asks follow-up questions, identifies contradictions, and supports skipping, pausing, and resuming.

Only user-approved facts enter `career_profile.md`. Drafts and unresolved questions remain separate. Records have stable identifiers and approved changes are versioned.

### 3. Job Matching

The assistant compares each qualification in the JD against the user's
approved career profile.

#### Requirement Importance

Each qualification is identified as:
- Required: explicitly stated as required or a minimum qualification.
- Preferred: explicitly stated as preferred or desirable.

If its importance is unclear, flag it for review before scoring. Repeated qualifications are counted once.

#### Evidence Assessment

Each qualification receives one classification:

| Classification | Meaning | Credit |
| --- | --- | --- |
| Strong match | Approved career evidence directly demonstrates the qualification. | 1.0 |
| Transferable experience | Approved evidence demonstrates related experience, but not a direct match. | 0.5 |
| Evidence missing | The profile contains insufficient information to assess the qualification. | 0.0 |
| Confirmed gap | The user has confirmed that they do not meet the qualification. | 0.0 |

For strong matches and transferable experience, show the supporting career-profile record identifiers and explain the connection.

For missing evidence, identify what information is needed and ask the user to clarify. Do not treat missing evidence as a confirmed gap.

#### Documented Match Percentage

The agent classifies the evidence. Python calculates the percentage using fixed rules:

- Required qualification: 2 available points.
- Preferred qualification: 1 available point.
- Points earned = available points multiplied by classification credit.
- Documented Match % = 100 multiplied by total earned points divided
  by total available points.

Example:

| Qualification | Importance | Assessment | Earned / available points |
| --- | --- | --- | --- |
| Product management experience | Required | Strong match | 2 / 2 |
| Cloud infrastructure experience | Required | Transferable experience | 1 / 2 |
| SQL proficiency | Required | Evidence missing | 0 / 2 |
| Startup experience | Preferred | Strong match | 1 / 1 |
| Total | | | 4 / 7 |

Documented Match = 100 * 4 / 7 = 57%, rounded to the nearest whole number.

Display this as: `57% documented match · 1 qualification needs clarification`

If the user later provides approved evidence demonstrating SQL proficiency, the score becomes 100 * 6 / 7 = 86%.

If no qualifications can be scored, display "Not available".

#### Job Inbox and Detailed View

Allow users to sort saved jobs by Documented Match percentage.

Alongside the percentage, show:
- The number of qualifications with missing evidence.
- Confirmed gaps in required qualifications.
- Blocking constraints, such as a required location the user has ruled out.

Opening a job shows every qualification, its classification, supporting evidence, and contribution to the percentage.

A blocking constraint remains visible regardless of the percentage. An unresolved constraint is shown as requiring clarification.

#### Interpretation and Updates

The percentage measures alignment documented in the approved profile. Missing evidence lowers it, even when the user may have the experience.

It is not a hiring probability, an employer's ATS score, or a guarantee of suitability.

The weights and credits are initial application rules. Their usefulness for ranking jobs will be evaluated before finalizing the implementation.

Record the JD, career-profile, and scoring-rule versions used. After relevant approved changes, flag the assessment for refresh and recalculate it using the updated inputs.

### 4. Resume Preparation

Generate a JD-specific resume using approved career evidence. Use one simple, single-column template with DOCX and text-based PDF exports.

Provide reviewable changes and evidence references. Check factual consistency, extracted text, and reading order. Follow explicit employer file-format instructions.

### 5. Company Research and Interview Guide

Research accessible official company sources. Record source URLs, titles, retrieval times, and publication dates when available.

Distinguish documented interview stages from inferred preparation topics. User-provided recruiter guidance takes precedence over general guidance.

Prepare role-specific questions and evidence-backed answer drafts. Distinguish company-published questions from generated practice questions. Request clarification when the profile lacks supporting experience.

### 6. Interview Coaching

Conduct text-based practice with adaptive follow-ups and explicit feedback. Assess relevance, structure, specificity, ownership, results, and clarity.

Support retry, skip, pause, and resume. The initial session design uses five main questions and up to one follow-up per question.

New career claims require approval before updating the profile.

## Application Areas

- Career Profile
- Job Inbox
- Job Workspace
- Interview Practice

## Architecture Direction

One backend hosts focused LangGraph workflows for experience capture, matching and resume preparation, research and interview preparation, and coaching.

Code handles calculations, persistence, validation, and document rendering. Agents handle interpretation, evidence selection, clarification, research decisions, and adaptive conversation.

Detailed interfaces and model selection remain subject to feasibility tests.

## Data and Reliability Rules

- Preserve original source captures.
- Keep approved facts separate from drafts.
- Record input versions used by derived outputs.
- Flag affected outputs for refresh after input changes.
- Treat external content as untrusted data.
- Bound retries, research, and revision loops.
- Keep credentials and personal records out of Git.
- Use fictional samples for shareable evaluation.

## Outside Submission Scope

- Automatic job discovery
- Automatic application submission
- Voice interviews
- Multiple users or cloud deployment
- Chrome Web Store publication
- Multiple resume templates
- Guaranteed extraction from every website
- Guaranteed ATS acceptance or interview outcomes
