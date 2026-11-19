"use strict";

const API_BASE = "http://127.0.0.1:8000";

const ui = {
  refresh: document.getElementById("refresh-jobs"),
  status: document.getElementById("status"),
  list: document.getElementById("job-list"),
  empty: document.getElementById("empty-detail"),
  detail: document.getElementById("job-detail"),
  title: document.getElementById("job-title"),
  source: document.getElementById("job-source"),
  time: document.getElementById("job-time"),
  method: document.getElementById("job-method"),
  uuid: document.getElementById("job-uuid"),
  text: document.getElementById("job-text"),
  extract: document.getElementById("extract-requirements"),
  extractionStatus: document.getElementById("extraction-status"),
  requirements: document.getElementById("requirements-result"),
  qualifications: document.getElementById("qualification-list"),
  constraints: document.getElementById("constraint-list"),
  assess: document.getElementById("assess-profile-match"),
  matchStatus: document.getElementById("match-status"),
  matchResult: document.getElementById("match-result"),
  percentage: document.getElementById("match-percentage"),
  calculation: document.getElementById("match-calculation"),
  exclusions: document.getElementById("match-exclusions"),
  assessments: document.getElementById("assessment-list"),
  sort: document.getElementById("job-sort")
};

const CLASSIFICATION_LABELS = {
  strong_match: "Strong match",
  transferable_experience: "Transferable experience",
  evidence_missing: "Evidence missing",
  confirmed_gap: "Confirmed gap"
};

let busy = false;
let selectedCaptureUuid = null;
let currentRequirements = null;
let listMatchSummaries = new Map();

function sortJobList() {
  const items = Array.from(ui.list.children);

  function percentage(item) {
    const summary = listMatchSummaries.get(item.dataset.captureUuid);
    return (
      summary?.status === "assessed"
      && typeof summary.percentage === "number"
      && Number.isFinite(summary.percentage)
    ) ? summary.percentage : null;
  }

  items.sort((a, b) => {
    if (ui.sort.value === "match") {
      const aScore = percentage(a);
      const bScore = percentage(b);

      if (aScore === null && bScore !== null) return 1;
      if (aScore !== null && bScore === null) return -1;
      if (aScore !== null && bScore !== null && aScore !== bScore) {
        return bScore - aScore;
      }
    }

    return (
      Number(b.dataset.capturedAt) - Number(a.dataset.capturedAt)
      || a.dataset.captureUuid.localeCompare(b.dataset.captureUuid)
    );
  });

  for (const item of items) {
    ui.list.append(item);
  }
}

function showStatus(message, kind = "") {
  ui.status.textContent = message;
  ui.status.dataset.kind = kind;
}

function setBusy(value) {
  busy = value;
  ui.refresh.disabled = value;
  ui.extract.disabled = (
    value || selectedCaptureUuid === null || currentRequirements !== null
  );
  ui.assess.disabled = (
    value || selectedCaptureUuid === null || currentRequirements === null
  );

  for (const button of ui.list.querySelectorAll("button")) {
    button.disabled = value;
  }
}

function displayTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString();
}

function clearMatch() {
  ui.matchStatus.textContent = "";
  ui.matchResult.hidden = true;
  ui.percentage.textContent = "";
  ui.calculation.textContent = "";
  ui.exclusions.textContent = "";
  ui.assessments.replaceChildren();
}

function clearDetail() {
  selectedCaptureUuid = null;
  currentRequirements = null;

  ui.extract.disabled = true;
  ui.extract.textContent = "Extract requirements";
  ui.assess.disabled = true;

  ui.requirements.hidden = true;
  ui.qualifications.replaceChildren();
  ui.constraints.replaceChildren();
  ui.extractionStatus.textContent = "";

  clearMatch();
  ui.detail.hidden = true;
  ui.empty.hidden = false;

  for (const button of ui.list.querySelectorAll("button")) {
    button.removeAttribute("aria-current");
  }
}

async function getJson(
  path,
  { method = "GET", timeoutMs = 15000 } = {}
) {
  const settings = await chrome.storage.local.get("captureToken");
  const token = (settings.captureToken || "").trim();

  if (!token) {
    throw new Error(
      "Set your local capture token in the extension popup's Connection settings."
    );
  }

  let response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "X-Capture-Token": token },
      signal: AbortSignal.timeout(timeoutMs),
      credentials: "omit",
      redirect: "error",
      cache: "no-store"
    });
  } catch {
    throw new Error(
      method === "POST"
        ? "No response was received. The model request may have run. "
          + "Check the server before starting another request."
        : "Could not reach the local API. Start the server, then try again."
    );
  }

  if (!response.ok) {
    let detail = null;

    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Fall back to the HTTP status when no readable detail exists.
    }

    if (response.status === 401) {
      throw new Error(
        "The token was rejected. Update Connection settings in the extension popup."
      );
    }

    throw new Error(
      detail || `Request failed with HTTP ${response.status}.`
    );
  }

  return response.json();
}

function renderRequirementList(container, requirements) {
  container.replaceChildren();

  if (requirements.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = "None extracted.";
    container.append(empty);
    return;
  }

  for (const requirement of requirements) {
    const item = document.createElement("li");
    const description = document.createElement("p");
    const importance = document.createElement("p");
    const evidence = document.createElement("details");
    const summary = document.createElement("summary");
    const excerpt = document.createElement("blockquote");

    description.textContent = requirement.description;
    importance.textContent = (
      requirement.importance === "unspecified"
        ? "Importance: unspecified — needs review"
        : `Importance: ${requirement.importance}`
    );

    summary.textContent = "Supporting JD excerpt";
    excerpt.textContent = requirement.source_excerpt;
    excerpt.style.whiteSpace = "pre-wrap";
    excerpt.style.overflowWrap = "anywhere";

    evidence.append(summary, excerpt);
    item.append(description, importance, evidence);
    container.append(item);
  }
}

function displayRequirements(result, captureUuid) {
  if (
    result.capture_uuid !== captureUuid
    || !Array.isArray(result.requirements)
  ) {
    throw new Error("The API returned an unexpected extraction result.");
  }

  renderRequirementList(
    ui.qualifications,
    result.requirements.filter(
      (requirement) => requirement.kind === "qualification"
    )
  );
  renderRequirementList(
    ui.constraints,
    result.requirements.filter(
      (requirement) => requirement.kind === "constraint"
    )
  );

  currentRequirements = result;
  ui.extract.textContent = "Requirements saved";
  ui.requirements.hidden = false;
  ui.extractionStatus.textContent = (
    `${result.requirements.length} saved AI-extracted requirements. `
    + "Review the classifications and supporting excerpts. "
    + "Saved does not mean user-approved."
  );
}

async function loadSavedMatch(captureUuid) {
  clearMatch();
  ui.matchStatus.textContent = "Checking for a saved match report…";

  try {
    const report = await getJson(
      `/captures/${encodeURIComponent(captureUuid)}/profile-match`
    );

    if (report === null) {
      ui.matchStatus.textContent = (
        "No saved match for the current profile and requirements. "
        + "Click Assess profile match to create one."
      );
      return;
    }

    displayMatch(report, captureUuid);
    ui.matchStatus.textContent = (
      "Saved match report loaded. "
      + "Review the explanations and profile evidence. "
      + "Saved does not mean user-approved."
    );
  } catch (error) {
    ui.matchResult.hidden = true;
    ui.matchStatus.textContent = (
      error.message || "Could not load the saved match report."
    );
  }
}

async function openCapture(captureUuid, button) {
  if (busy) {
    return;
  }

  setBusy(true);
  clearDetail();
  showStatus("Loading capture…");

  try {
    const capture = await getJson(
      `/captures/${encodeURIComponent(captureUuid)}`
    );

    const source = new URL(capture.source_url);
    if (!["http:", "https:"].includes(source.protocol)) {
      throw new Error("The capture has an unsupported source URL.");
    }

    ui.title.textContent = capture.page_title || "Untitled capture";
    ui.source.textContent = capture.source_url;
    ui.source.href = source.href;
    ui.time.textContent = (
      `${displayTime(capture.captured_at)} (${capture.captured_at})`
    );
    ui.method.textContent = capture.capture_method;
    ui.uuid.textContent = capture.capture_uuid;
    ui.text.textContent = capture.jd_text;

    selectedCaptureUuid = capture.capture_uuid;
    button.setAttribute("aria-current", "true");
    ui.empty.hidden = true;
    ui.detail.hidden = false;
    showStatus("Capture loaded.");

    ui.extractionStatus.textContent = "Checking for saved requirements…";

    try {
      const saved = await getJson(
        `/captures/${encodeURIComponent(captureUuid)}/requirements`
      );

      if (saved === null) {
        ui.extractionStatus.textContent = (
          "No saved extraction. Click Extract requirements to create one."
        );
      } else {
        displayRequirements(saved, captureUuid);
        await loadSavedMatch(captureUuid)
      }
    } catch (error) {
      ui.extractionStatus.textContent = (
        error.message || "Could not check saved requirements."
      );
    }
  } catch (error) {
    clearDetail();
    showStatus(error.message || "Could not load the capture.", "error");
  } finally {
    setBusy(false);
  }
}

async function loadListMatchSummaries() {
  const labels = ui.list.querySelectorAll("[data-match-capture]");

  try {
    const summaries = await getJson("/capture-match-summaries");

    if (!Array.isArray(summaries)) {
      throw new Error("Unexpected match summary response.");
    }

    const byId = new Map();

    for (const summary of summaries) {
      if (
        !summary
        || typeof summary.capture_uuid !== "string"
        || byId.has(summary.capture_uuid)
        || !["assessed", "not_assessed", "profile_unavailable"].includes(
          summary.status
        )
        || (
          summary.percentage !== null
          && (
            typeof summary.percentage !== "number"
            || !Number.isFinite(summary.percentage)
            || summary.percentage < 0
            || summary.percentage > 100
          )
        )
        || (
          summary.status !== "assessed"
          && summary.percentage !== null
        )
      ) {
        throw new Error("Invalid match summary response.");
      }

      byId.set(summary.capture_uuid, summary);
    }

    listMatchSummaries = byId;
    sortJobList();
    for (const label of labels) {
      const summary = byId.get(label.dataset.matchCapture);

      if (!summary) {
        label.textContent = "Match unavailable — refresh the list.";
      } else if (summary.status === "profile_unavailable") {
        label.textContent = "Profile unavailable";
      } else if (summary.status === "not_assessed") {
        label.textContent = "Not assessed";
      } else {
        label.textContent = (
          summary.percentage === null
            ? "Match: Not available"
            : `Documented match: ${summary.percentage.toFixed(1)}%`
        );
        const missingCount = summary.missing_evidence_count;
        if (Number.isInteger(missingCount) && missingCount >= 0) {
          label.textContent += (
            ` · ${missingCount} qualification`
            + `${missingCount === 1 ? "" : "s"} need`
            + `${missingCount === 1 ? "s" : ""} clarification`
          );
        }
        const requiredGapCount = summary.required_gap_count;
        if (
          Number.isInteger(requiredGapCount)
          && requiredGapCount >= 0
        ) {
          label.textContent += (
            ` · ${requiredGapCount} confirmed required gap`
            + `${requiredGapCount === 1 ? "" : "s"}`
          );
        }
      }
    }
  } catch {
    listMatchSummaries = new Map();
    sortJobList();
    for (const label of labels) {
      label.textContent = "Match unavailable — refresh to retry.";
    }
  }
}

async function refreshCaptures() {
  if (busy) {
    return;
  }

  setBusy(true);
  clearDetail();
  ui.list.replaceChildren();
  listMatchSummaries = new Map();
  showStatus("Loading saved captures…");

  try {
    const captures = await getJson("/captures");

    if (!Array.isArray(captures)) {
      throw new Error("The API returned an unexpected capture list.");
    }

    for (const capture of captures) {
      const item = document.createElement("li");
      item.dataset.captureUuid = capture.capture_uuid;
      item.dataset.capturedAt = String(
        Date.parse(capture.captured_at) || 0
      );
      const button = document.createElement("button");
      const title = document.createElement("span");
      const time = document.createElement("span");

      button.type = "button";
      button.disabled = true;
      title.className = "job-list-title";
      title.textContent = capture.page_title || capture.source_url;
      time.className = "job-list-time";
      time.textContent = displayTime(capture.captured_at);

      const matchLabel = document.createElement("span");
      matchLabel.dataset.matchCapture = capture.capture_uuid;
      matchLabel.style.display = "block";
      matchLabel.textContent = "Checking saved match…";

      button.append(title, time, matchLabel);
      button.addEventListener("click", () =>
        openCapture(capture.capture_uuid, button)
      );

      item.append(button);
      ui.list.append(item);
    }

    if (captures.length > 0) {
      await loadListMatchSummaries();
    }

    showStatus(
      captures.length === 0
        ? "No saved captures yet. Save a JD using the extension popup."
        : `${captures.length} saved capture${captures.length === 1 ? "" : "s"}.`
    );
  } catch (error) {
    ui.list.replaceChildren();
    showStatus(error.message || "Could not load saved captures.", "error");
  } finally {
    setBusy(false);
  }
}

async function extractSelectedRequirements() {
  if (busy || selectedCaptureUuid === null || currentRequirements !== null) {
    return;
  }

  const captureUuid = selectedCaptureUuid;
  setBusy(true);
  clearMatch();
  ui.requirements.hidden = true;
  ui.qualifications.replaceChildren();
  ui.constraints.replaceChildren();
  ui.extractionStatus.textContent = "Extracting and saving requirements…";

  try {
    const result = await getJson(
      `/captures/${encodeURIComponent(captureUuid)}/requirements`,
      { method: "POST", timeoutMs: 75000 }
    );
    displayRequirements(result, captureUuid);
  } catch (error) {
    ui.extractionStatus.textContent = (
      error.message || "Extraction failed."
    );
  } finally {
    setBusy(false);
  }
}

function renderAssessment(assessment, requirement) {
  const item = document.createElement("li");
  const heading = document.createElement("p");
  const classification = document.createElement("p");
  const explanation = document.createElement("p");

  heading.textContent = requirement.description;
  classification.textContent = (
    `${CLASSIFICATION_LABELS[assessment.classification]} `
    + `— ${requirement.importance}`
  );
  explanation.textContent = assessment.explanation;

  item.append(heading, classification, explanation);

  if (assessment.evidence.length === 0) {
    const missing = document.createElement("p");
    missing.textContent = "No supporting profile excerpt cited.";
    item.append(missing);
  } else {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Supporting profile evidence";
    details.append(summary);

    for (const evidence of assessment.evidence) {
      const reference = document.createElement("p");
      const excerpt = document.createElement("blockquote");

      reference.textContent = (
        `${evidence.record_type}: ${evidence.record_uuid} `
        + `— field: ${evidence.field_name}`
      );
      reference.style.overflowWrap = "anywhere";
      excerpt.textContent = evidence.excerpt;
      excerpt.style.whiteSpace = "pre-wrap";
      excerpt.style.overflowWrap = "anywhere";

      details.append(reference, excerpt);
    }

    item.append(details);
  }

  return item;
}

function displayMatch(report, captureUuid) {
  const match = report.match;
  const score = report.score;

  if (
    !match
    || !score
    || match.capture_uuid !== captureUuid
    || !Array.isArray(match.assessments)
    || !Array.isArray(score.unspecified_qualification_uuids)
    || !Array.isArray(score.constraint_uuids)
  ) {
    throw new Error("The API returned an unexpected match report.");
  }

  const percentage = score.percentage;
  if (
    percentage !== null
    && (
      typeof percentage !== "number"
      || !Number.isFinite(percentage)
      || percentage < 0
      || percentage > 100
    )
  ) {
    throw new Error("The API returned an invalid percentage.");
  }

  const requirementsById = new Map(
    currentRequirements.requirements.map(
      (requirement) => [requirement.requirement_uuid, requirement]
    )
  );
  const fragment = document.createDocumentFragment();

  for (const assessment of match.assessments) {
    const requirement = requirementsById.get(assessment.requirement_uuid);

    if (
      !requirement
      || requirement.kind !== "qualification"
      || !Object.hasOwn(
        CLASSIFICATION_LABELS,
        assessment.classification
      )
      || !Array.isArray(assessment.evidence)
    ) {
      throw new Error("The report contains an unexpected assessment.");
    }

    fragment.append(renderAssessment(assessment, requirement));
  }

  if (match.assessments.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = "No qualifications to assess.";
    fragment.append(empty);
  }

  ui.assessments.replaceChildren(fragment);
  ui.percentage.textContent = (
    percentage === null
      ? "Documented match: Not available"
      : `Documented match: ${percentage.toFixed(1)}%`
  );
  ui.calculation.textContent = (
    `${score.earned_weighted_credit} of `
    + `${score.possible_weighted_credit} weighted credits across `
    + `${score.scored_qualification_count} scored qualifications.`
  );
  ui.exclusions.textContent = (
    `Excluded from the percentage: `
    + `${score.unspecified_qualification_uuids.length} qualifications `
    + `with unspecified importance and `
    + `${score.constraint_uuids.length} practical constraints.`
  );

  ui.matchResult.hidden = false;
}

async function assessSelectedProfile() {
  if (busy || selectedCaptureUuid === null || currentRequirements === null) {
    return;
  }

  const captureUuid = selectedCaptureUuid;
  setBusy(true);
  clearMatch();
  ui.matchStatus.textContent = "Assessing the saved career profile…";

  try {
    const report = await getJson(
      `/captures/${encodeURIComponent(captureUuid)}/profile-match`,
      { method: "POST", timeoutMs: 75000 }
    );

    displayMatch(report, captureUuid);
    ui.matchStatus.textContent = (
      "Match report saved or reused for the current profile and requirements. "
      + "Review the explanations and profile evidence. "
      + "Saved does not mean user-approved."
    );
    await loadListMatchSummaries();
  } catch (error) {
    ui.matchResult.hidden = true;
    ui.matchStatus.textContent = (
      error.message || "Profile assessment failed."
    );
  } finally {
    setBusy(false);
  }
}

ui.refresh.addEventListener("click", refreshCaptures);
ui.extract.addEventListener("click", extractSelectedRequirements);
ui.assess.addEventListener("click", assessSelectedProfile);

ui.sort.addEventListener("change", sortJobList);
refreshCaptures();