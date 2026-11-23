"use strict";

(() => {
  const el = (id) => document.getElementById(`preparation-${id}`);
  const ui = {
    urls: el("urls"), official: el("official"), capture: el("capture"),
    sourceStatus: el("source-status"), sources: el("sources"),
    reviewed: el("reviewed"), reviewLabel: el("review-label"),
    recruiter: el("recruiter"), generate: el("generate"),
    guideStatus: el("guide-status"), guide: el("guide")
  };
  let captureUuid = null;
  let research = null;
  let working = false;
  let version = 0;
  let captureRequest = null;
  let guideRequest = null;
  let downloadUrl = null;

  function sourceUrlsMatch() {
    if (!research) return false;
    const urls = [...new Set(ui.urls.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
    return JSON.stringify(urls) === JSON.stringify(research.bundle.submitted_urls);
  }

  function controls() {
    ui.urls.disabled = working;
    ui.official.disabled = working;
    ui.recruiter.disabled = working;
    ui.reviewed.disabled = working || !research;
    ui.capture.disabled = working || !captureUuid || !ui.official.checked;
    ui.generate.disabled = working || !research || !ui.reviewed.checked || !sourceUrlsMatch();
  }

  function clearGuide() {
    document.dispatchEvent(new CustomEvent("preparation-guide-cleared"));
    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = null;
    ui.guide.replaceChildren();
  }

  function add(parent, tag, text) {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.append(node);
    return node;
  }

  function sourceLink(parent, source) {
    const url = new URL(source.url);
    if (url.protocol !== "https:") throw new Error("Unexpected source URL.");
    const link = add(parent, "a", source.title || source.url);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    add(parent, "p", `Retrieved: ${source.retrieved_at}`);
    add(parent, "p", `Publication date: ${source.publication_date || "Not available"}`);
  }

  function showSources(value) {
    if (!value || !/^[a-f0-9]{64}$/.test(value.research_sha256)
      || typeof value.research_uuid !== "string"
      || value.bundle?.capture_uuid !== captureUuid
      || !Array.isArray(value.bundle.sources)) {
      throw new Error("Unexpected source capture response.");
    }
    research = value;
    ui.sources.replaceChildren();
    for (const source of value.bundle.sources) {
      const details = document.createElement("details");
      add(details, "summary", source.title || source.url);
      sourceLink(details, source);
      const text = add(details, "pre", source.text);
      text.style.whiteSpace = "pre-wrap";
      text.style.overflowWrap = "anywhere";
      ui.sources.append(details);
    }
    ui.reviewLabel.hidden = false;
    ui.reviewed.checked = false;
    if (!ui.urls.value.trim()) ui.urls.value = value.bundle.submitted_urls.join("\n");
    controls();
  }

  function showGuide(value) {
    if (value?.capture_uuid !== captureUuid
      || !Array.isArray(value.guide?.practice_questions)
      || !Array.isArray(value.sources)
      || typeof value.markdown !== "string") {
      throw new Error("Unexpected interview guide response.");
    }
    clearGuide();
    add(ui.guide, "p", "Draft requiring review. Practice questions are generated, not company-published questions or predictions.");
    if (value.recruiter_guidance) {
      add(ui.guide, "h5", "Recruiter guidance — user supplied");
      add(ui.guide, "p", "Takes precedence over general company hiring information.");
      add(ui.guide, "p", value.recruiter_guidance);
      if (!ui.recruiter.value.trim()) ui.recruiter.value = value.recruiter_guidance;
    }
    const sources = new Map(value.sources.map((source) => [source.source_uuid, source]));
    for (const [heading, notes] of [
      ["Company context — sourced", value.guide.company_notes],
      ["Documented hiring information — sourced", value.guide.documented_hiring_information]
    ]) {
      add(ui.guide, "h5", heading);
      if (!notes.length) add(ui.guide, "p", "Not established by the captured sources.");
      for (const note of notes) {
        add(ui.guide, "p", note.statement);
        const details = document.createElement("details");
        add(details, "summary", "Supporting source");
        const source = sources.get(note.source_uuid);
        if (!source) throw new Error("Guide has an unknown source reference.");
        sourceLink(details, source);
        add(details, "blockquote", note.excerpt);
        ui.guide.append(details);
      }
    }
    add(ui.guide, "h5", "Generated practice questions");
    const list = document.createElement("ol");
    for (const question of value.guide.practice_questions) {
      const item = document.createElement("li");
      add(item, "p", question.question);
      if (question.answer_draft !== null) {
        add(item, "strong", "Answer draft — review against evidence");
        add(item, "p", question.answer_draft);
      }
      if (question.clarification) {
        add(item, "strong", "Clarification needed");
        add(item, "p", question.clarification);
      }
      const details = document.createElement("details");
      add(details, "summary", "Qualification and approved profile evidence");
      add(details, "p", `Qualification ID: ${question.requirement_uuid}`);
      for (const evidence of question.evidence) {
        add(details, "p", `${evidence.record_type}: ${evidence.record_uuid} — ${evidence.field_name}`);
        add(details, "blockquote", evidence.excerpt);
      }
      if (!question.evidence.length) add(details, "p", "No approved profile evidence cited.");
      item.append(details);
      list.append(item);
    }
    ui.guide.append(list);
    downloadUrl = URL.createObjectURL(new Blob([value.markdown], { type: "text/markdown;charset=utf-8" }));
    const link = add(ui.guide, "a", "Download interview guide");
    link.href = downloadUrl;
    link.download = "interview-guide.md";
    document.dispatchEvent(new CustomEvent("preparation-guide-ready", {
      detail: { captureUuid, guideUuid: value.guide_uuid }
    }));
  }

  async function request(path, body, timeoutMs = 75000) {
    const settings = await chrome.storage.local.get("captureToken");
    const token = (settings.captureToken || "").trim();
    if (!token) throw new Error("Set your capture token in Connection settings.");
    let response;
    try {
      response = await fetch(`http://127.0.0.1:8000${path}`, {
        method: body ? "POST" : "GET",
        headers: {
          "X-Capture-Token": token,
          ...(body ? { "Content-Type": "application/json" } : {})
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(body ? timeoutMs : 15000),
        credentials: "omit", redirect: "error", cache: "no-store"
      });
    } catch {
      throw new Error(body
        ? "No response. The operation may have completed. Reopen this job to check saved results before starting a new request."
        : "Could not reach the local API.");
    }
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === "string"
      ? value.detail : `Preparation request failed: HTTP ${response.status}.`);
    return value;
  }

  async function action(status, operation) {
    if (working || !captureUuid || busy) return;
    version += 1;
    working = true;
    setBusy(true);
    controls();
    try { await operation(); }
    catch (error) { status.textContent = error.message; }
    finally {
      working = false;
      setBusy(false);
      controls();
    }
  }

  ui.urls.addEventListener("input", () => {
    ui.official.checked = false;
    ui.reviewed.checked = false;
    controls();
  });
  ui.official.addEventListener("change", controls);
  ui.reviewed.addEventListener("change", controls);
  ui.capture.addEventListener("click", () => action(ui.sourceStatus, async () => {
    if (!ui.official.checked) throw new Error("Confirm the official source URLs first.");
    const urls = [...new Set(ui.urls.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
    if (!urls.length || urls.length > 5) throw new Error("Enter one to five official HTTPS URLs, one per line.");
    for (const url of urls) {
      if (new URL(url).protocol !== "https:") throw new Error("Use HTTPS source URLs.");
    }
    const key = JSON.stringify(urls);
    if (!captureRequest || captureRequest.key !== key) captureRequest = { key, id: crypto.randomUUID() };
    ui.sourceStatus.textContent = "Capturing official pages. This may take up to two minutes…";
    clearGuide();
    ui.guideStatus.textContent = "";
    showSources(await request(`/captures/${captureUuid}/research`, {
      request_uuid: captureRequest.id, official_sources_confirmed: true, urls
    }, 130000));
    captureRequest = null;
    guideRequest = null;
    ui.sourceStatus.textContent = "Sources saved. Expand and review each page, then check the source-review box.";
  }));

  ui.generate.addEventListener("click", () => action(ui.guideStatus, async () => {
    if (!research || !ui.reviewed.checked || !sourceUrlsMatch()) throw new Error("Capture and review the current source URLs first.");
    const guidance = ui.recruiter.value.trim();
    const key = JSON.stringify([research.research_uuid, research.research_sha256, guidance]);
    if (!guideRequest || guideRequest.key !== key) guideRequest = { key, id: crypto.randomUUID() };
    ui.guideStatus.textContent = "Generating and validating the interview guide…";
    clearGuide();
    const value = await request(`/captures/${captureUuid}/interview-guides`, {
      request_uuid: guideRequest.id,
      research_uuid: research.research_uuid,
      research_sha256: research.research_sha256,
      sources_reviewed: true, recruiter_guidance: guidance
    });
    showGuide(value);
    guideRequest = null;
    ui.guideStatus.textContent = "Guide saved. Review sourced notes, generated questions, and candidate evidence.";
  }));

  document.addEventListener("resume-capture-cleared", () => {
    version += 1;
    captureUuid = null;
    research = null;
    captureRequest = null;
    guideRequest = null;
    ui.urls.value = "";
    ui.recruiter.value = "";
    ui.official.checked = false;
    ui.reviewed.checked = false;
    ui.reviewLabel.hidden = true;
    ui.sources.replaceChildren();
    ui.sourceStatus.textContent = "";
    ui.guideStatus.textContent = "";
    clearGuide();
    controls();
  });

  document.addEventListener("resume-capture-opened", async (event) => {
    captureUuid = event.detail.captureUuid;
    const opened = captureUuid;
    const lookup = ++version;
    ui.sourceStatus.textContent = "Checking saved research…";
    try {
      const saved = await request(`/captures/${opened}/research/latest`);
      if (captureUuid !== opened || lookup !== version) return;
      if (saved) {
        showSources(saved);
        ui.sourceStatus.textContent = "Saved sources loaded. Review them before generating a new guide.";
      } else ui.sourceStatus.textContent = "No saved research. Enter official source URLs above.";
    } catch (error) {
      if (captureUuid === opened && lookup === version) ui.sourceStatus.textContent = error.message;
    }
    if (captureUuid !== opened || lookup !== version) return;
    ui.guideStatus.textContent = "Checking for a saved interview guide…";
    try {
      const saved = await request(`/captures/${opened}/interview-guides/latest`);
      if (captureUuid !== opened || lookup !== version) return;
      if (saved) {
        showGuide(saved);
        ui.guideStatus.textContent = "Saved interview guide loaded. No new AI request was made.";
      } else ui.guideStatus.textContent = "No saved guide. Capture and review sources first.";
    } catch (error) {
      if (captureUuid === opened && lookup === version) ui.guideStatus.textContent = error.message;
    }
    controls();
  });
  window.addEventListener("pagehide", () => { if (downloadUrl) URL.revokeObjectURL(downloadUrl); });
  controls();
})();
