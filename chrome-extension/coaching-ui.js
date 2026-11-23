"use strict";

(() => {
  const el = (name) => document.getElementById(`coaching-${name}`);
  const ui = Object.fromEntries([
    "start", "sessions", "reload", "status", "workspace", "context",
    "progress", "question", "followup", "budget", "error", "answer",
    "submit", "retry", "next", "skip", "pause", "resume", "feedback",
    "history", "download"
  ].map((name) => [name, el(name)]));
  const dimensions = ["relevance", "structure", "specificity", "ownership", "results", "clarity"];
  let captureUuid = null;
  let guideUuid = null;
  let session = null;
  let working = false;
  let lookupVersion = 0;
  let pendingStart = null;
  let pendingAction = null;
  let historyUrl = null;

  function add(parent, tag, text) {
    const child = document.createElement(tag);
    child.textContent = text;
    parent.append(child);
    return child;
  }

  function controls() {
    const active = session?.status === "active";
    const reviewing = session?.phase === "review";
    const canAnswer = active && !reviewing && session.request_count < 4;
    ui.start.disabled = working || !captureUuid || !guideUuid;
    ui.sessions.disabled = working || ui.sessions.children.length === 0;
    ui.reload.disabled = working || !captureUuid;
    ui.answer.disabled = working || !canAnswer;
    ui.submit.disabled = working || !canAnswer || !ui.answer.value.trim();
    ui.retry.disabled = working || !active || !reviewing || session.request_count >= 4;
    ui.next.disabled = working || !active || !reviewing;
    ui.skip.disabled = working || !active;
    ui.pause.disabled = working || !active;
    ui.resume.disabled = working || session?.status !== "paused";
  }

  function revokeHistory() {
    if (historyUrl) URL.revokeObjectURL(historyUrl);
    historyUrl = null;
    ui.download.replaceChildren();
  }

  function renderFeedback(parent, feedback) {
    parent.replaceChildren();
    if (!feedback) return;
    add(parent, "h5", "Practice feedback");
    for (const dimension of dimensions) {
      const item = feedback[dimension];
      add(parent, "p", `${dimension[0].toUpperCase() + dimension.slice(1)} ${item.score}/5: ${item.explanation}`);
    }
    add(parent, "strong", "Suggestions");
    const suggestions = document.createElement("ul");
    for (const suggestion of feedback.suggestions) add(suggestions, "li", suggestion);
    parent.append(suggestions);
  }

  function showSession(value) {
    if (value?.capture_uuid !== captureUuid || typeof value.session_uuid !== "string"
      || !/^[a-f0-9]{64}$/.test(value.revision)
      || !["active", "paused", "complete"].includes(value.status)
      || !Array.isArray(value.history)) throw new Error("Unexpected coaching session response.");
    const changed = !session || value.session_uuid !== session.session_uuid || value.revision !== session.revision;
    if (changed) {
      ui.answer.value = value.preserved_answer || "";
      pendingAction = null;
    }
    session = value;
    ui.sessions.value = value.session_uuid;
    ui.workspace.hidden = false;
    ui.context.textContent = value.context_outdated
      ? "This session uses an earlier guide snapshot. Its history is preserved. Generate a current guide and start a new session to use updated inputs."
      : "This session uses the guide and approved-profile snapshot saved when it started.";
    ui.progress.textContent = value.status === "complete"
      ? "Five-question session complete. Review or download your saved history."
      : `Question ${value.question_number} of 5 · ${value.status}`;
    ui.question.textContent = value.question || "";
    ui.followup.textContent = value.followup_question ? `Follow-up: ${value.followup_question}` : "";
    ui.budget.textContent = value.status === "complete" ? "" : `Evaluation requests for this question: ${value.request_count}/4`;
    ui.error.textContent = value.last_error || "";
    renderFeedback(ui.feedback, value.latest_feedback);
    ui.history.replaceChildren();
    for (const event of value.history) {
      const details = document.createElement("details");
      add(details, "summary", `Question ${event.question_number} — ${event.event}${event.phase ? ` (${event.phase})` : ""}`);
      if (event.answer) add(details, "p", event.answer);
      if (event.followup_question) add(details, "p", `Follow-up: ${event.followup_question}`);
      if (event.feedback) {
        const feedback = document.createElement("div");
        renderFeedback(feedback, event.feedback);
        details.append(feedback);
      }
      ui.history.append(details);
    }
    revokeHistory();
    historyUrl = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const link = add(ui.download, "a", "Download practice history");
    link.href = historyUrl;
    link.download = "interview-practice-history.json";
    controls();
  }

  async function request(path, body) {
    const settings = await chrome.storage.local.get("captureToken");
    const token = (settings.captureToken || "").trim();
    if (!token) throw new Error("Set the capture token in Connection settings.");
    let response;
    try {
      response = await fetch(`http://127.0.0.1:8000${path}`, {
        method: body ? "POST" : "GET",
        headers: { "X-Capture-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(body ? 75000 : 15000),
        credentials: "omit", redirect: "error", cache: "no-store"
      });
    } catch {
      throw new Error(body
        ? "No response. The operation may have completed. Use Reload session to check history before submitting again."
        : "Could not reach the local API. Start the server, then reload the session.");
    }
    let result;
    try { result = await response.json(); }
    catch {
      throw new Error("The server returned an unreadable response. Reload session to check saved progress.");
    }
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `Coaching request failed: HTTP ${response.status}.`);
    return result;
  }

  async function loadSessions(selected = null) {
    const opened = captureUuid;
    const version = ++lookupVersion;
    ui.status.textContent = "Checking saved practice sessions…";
    const sessions = await request(`/captures/${opened}/coaching`);
    if (captureUuid !== opened || version !== lookupVersion) return;
    if (!Array.isArray(sessions)) throw new Error("Unexpected session list.");
    ui.sessions.replaceChildren();
    for (const item of sessions) {
      const option = add(ui.sessions, "option", `${new Date(item.created_at).toLocaleString()} · ${item.session_uuid.slice(0, 8)}`);
      option.value = item.session_uuid;
    }
    const target = selected || sessions[0]?.session_uuid;
    if (!target) {
      session = null;
      ui.workspace.hidden = true;
      ui.status.textContent = "No saved practice session. Load a current guide, then start a new session.";
      controls();
      return;
    }
    const value = await request(`/captures/${opened}/coaching/${target}`);
    if (captureUuid !== opened || version !== lookupVersion) return;
    showSession(value);
    ui.status.textContent = "Saved practice session loaded. No AI request was made.";
    controls();
  }

  async function action(operation) {
    if (working) { ui.status.textContent = "A coaching operation is already running."; return; }
    if (!captureUuid) { ui.status.textContent = "Select a saved job first."; return; }
    if (busy) { ui.status.textContent = "The job page is busy. Wait for it to finish, then try again."; return; }
    lookupVersion += 1;
    working = true;
    setBusy(true);
    controls();
    try { await operation(); }
    catch (error) { ui.status.textContent = error.message; }
    finally { working = false; setBusy(false); controls(); }
  }

  ui.start.addEventListener("click", () => action(async () => {
    if (!guideUuid) throw new Error("Generate and review a current interview guide first.");
    if (!pendingStart || pendingStart.guide !== guideUuid) pendingStart = { id: crypto.randomUUID(), guide: guideUuid };
    ui.status.textContent = "Starting a practice session without calling AI…";
    const value = await request(`/captures/${captureUuid}/coaching`, {
      request_uuid: pendingStart.id, guide_uuid: guideUuid, confirmed: true
    });
    pendingStart = null;
    showSession(value);
    await loadSessions(value.session_uuid);
    ui.status.textContent = "Practice started. Type your answer, then submit it for feedback.";
  }));

  async function sendAction(kind) {
    if (!session) throw new Error("Load a practice session first.");
    const answer = kind === "answer" ? ui.answer.value.trim() : "";
    if (kind === "answer" && !answer) throw new Error("Type your practice answer first.");
    const key = JSON.stringify([session.session_uuid, session.revision, kind, answer]);
    if (!pendingAction || pendingAction.key !== key) pendingAction = { key, body: {
      request_uuid: crypto.randomUUID(), expected_revision: session.revision,
      action: kind, answer
    } };
    ui.status.textContent = kind === "answer" ? "Evaluating your practice answer…" : "Saving session progress…";
    const value = await request(`/captures/${captureUuid}/coaching/${session.session_uuid}/actions`, pendingAction.body);
    showSession(value);
    pendingAction = null;
    ui.status.textContent = value.last_error ? "Evaluation did not complete. Read the message above before retrying." : "Progress saved.";
  }

  ui.submit.addEventListener("click", () => action(() => sendAction("answer")));
  for (const kind of ["retry", "next", "skip", "pause", "resume"]) {
    ui[kind].addEventListener("click", () => action(() => sendAction(kind)));
  }
  ui.answer.addEventListener("input", controls);
  ui.sessions.addEventListener("change", () => action(() => loadSessions(ui.sessions.value)));
  ui.reload.addEventListener("click", () => action(() => loadSessions(session?.session_uuid)));

  document.addEventListener("preparation-guide-ready", (event) => {
    if (event.detail.captureUuid === captureUuid) guideUuid = event.detail.guideUuid;
    controls();
  });
  document.addEventListener("preparation-guide-cleared", () => { guideUuid = null; controls(); });
  document.addEventListener("resume-capture-cleared", () => {
    lookupVersion += 1;
    captureUuid = null; guideUuid = null; session = null;
    pendingStart = null; pendingAction = null;
    ui.sessions.replaceChildren(); ui.workspace.hidden = true;
    ui.answer.value = ""; ui.status.textContent = "";
    ui.feedback.replaceChildren(); ui.history.replaceChildren();
    revokeHistory(); controls();
  });
  document.addEventListener("resume-capture-opened", async (event) => {
    captureUuid = event.detail.captureUuid;
    const opened = captureUuid;
    try { await loadSessions(); }
    catch (error) { if (captureUuid === opened) ui.status.textContent = error.message; }
  });
  window.addEventListener("pagehide", revokeHistory);
  controls();
})();
