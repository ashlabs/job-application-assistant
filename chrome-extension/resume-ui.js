"use strict";

(() => {
  const el = (id) => document.getElementById(id);
  const elements = {
    name: el("resume-name"), generate: el("resume-generate"),
    status: el("resume-status"), review: el("resume-review"),
    text: el("resume-text"), evidence: el("resume-evidence"),
    confirm: el("resume-confirm"), approve: el("resume-approve"),
    export: el("resume-export"), downloads: el("resume-downloads")
  };
  let captureUuid = null;
  let draft = null;
  let working = false;
  let requestUuid = null;
  let requestName = null;
  let urls = [];
  let viewVersion = 0;

  function clearDownloads() {
    urls.forEach((url) => URL.revokeObjectURL(url));
    urls = [];
    elements.downloads.replaceChildren();
  }

  function controls() {
    elements.name.disabled = working;
    elements.generate.disabled = working || !captureUuid;
    elements.confirm.disabled = working || !draft || draft.approved;
    elements.approve.disabled = (
      working || !draft || draft.approved || !elements.confirm.checked
    );
    elements.export.disabled = working || !draft?.approved;
  }

  function clearDraft() {
    draft = null;
    elements.review.hidden = true;
    elements.text.textContent = "";
    elements.evidence.textContent = "";
    elements.confirm.checked = false;
    clearDownloads();
    controls();
  }

  function showDraft(value) {
    if (
      !value || value.capture_uuid !== captureUuid
      || typeof value.resume_uuid !== "string"
      || typeof value.text !== "string"
      || !/^[a-f0-9]{64}$/.test(value.review_token)
      || typeof value.approved !== "boolean"
    ) throw new Error("Unexpected resume response.");
    clearDownloads();
    draft = value;
    elements.text.textContent = value.text;
    elements.evidence.textContent = JSON.stringify(value.evidence, null, 2);
    elements.confirm.checked = value.approved;
    elements.review.hidden = false;
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
        headers: {
          "X-Capture-Token": token,
          ...(body ? { "Content-Type": "application/json" } : {})
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(body ? 75000 : 15000),
        credentials: "omit", redirect: "error", cache: "no-store"
      });
    } catch {
      throw new Error(
        body ? "No response. The operation may have completed. Reload the job "
          + "to check its saved draft; retry generation with the same name "
          + "before starting a different request."
          : "Could not reach the local API."
      );
    }
    const result = await response.json();
    if (!response.ok) throw new Error(
      typeof result.detail === "string" ? result.detail
        : `Resume request failed: HTTP ${response.status}.`
    );
    return result;
  }

  async function action(operation) {
    if (working || !captureUuid || busy) return;
    viewVersion += 1;
    working = true;
    setBusy(true);
    controls();
    try {
      await operation();
    } catch (error) {
      elements.status.textContent = error.message;
    } finally {
      working = false;
      setBusy(false);
      controls();
    }
  }

  elements.generate.addEventListener("click", () => action(async () => {
    const name = elements.name.value.trim();
    if (!name) throw new Error("Enter the candidate name first.");
    // Preserve the request identity if a response was lost.
    if (!requestUuid || requestName !== name) {
      requestUuid = crypto.randomUUID();
      requestName = name;
    }
    elements.status.textContent = "Generating resume draft…";
    const result = await request(`/captures/${captureUuid}/resumes`, {
      request_uuid: requestUuid, name
    });
    showDraft(result);
    requestUuid = null;
    requestName = null;
    elements.status.textContent = "Draft saved. Review its text and evidence.";
  }));

  elements.confirm.addEventListener("change", controls);
  elements.approve.addEventListener("click", () => action(async () => {
    if (!draft || !elements.confirm.checked) return;
    elements.status.textContent = "Checking and approving this exact draft…";
    showDraft(await request(
      `/captures/${captureUuid}/resumes/${draft.resume_uuid}/approve`,
      { confirmed: true, review_token: draft.review_token }
    ));
    elements.status.textContent = "Exact draft approved. Exports are available.";
  }));

  elements.export.addEventListener("click", () => action(async () => {
    if (!draft?.approved) return;
    clearDownloads();
    elements.status.textContent = "Checking approval and rendering documents…";
    const result = await request(
      `/captures/${captureUuid}/resumes/${draft.resume_uuid}/export`,
      { confirmed: true, review_token: draft.review_token }
    );
    const types = {
      "resume.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "resume.pdf": "application/pdf"
    };
    for (const [name, type] of Object.entries(types)) {
      const binary = atob(result.files[name]);
      const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type }));
      urls.push(url);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.textContent = `Download ${name}`;
      link.style.display = "block";
      elements.downloads.append(link);
    }
    elements.status.textContent = "Text and reading order verified. Review both layouts.";
  }));

  document.addEventListener("resume-capture-cleared", () => {
    viewVersion += 1;
    captureUuid = null;
    requestUuid = null;
    requestName = null;
    elements.status.textContent = "";
    clearDraft();
  });

  document.addEventListener("resume-capture-opened", async (event) => {
    captureUuid = event.detail.captureUuid;
    const opened = captureUuid;
    const version = ++viewVersion;
    clearDraft();
    elements.status.textContent = "Checking for a saved resume draft…";
    try {
      const result = await request(`/captures/${opened}/resumes/latest`);
      if (captureUuid !== opened || version !== viewVersion) return;
      if (result) {
        showDraft(result);
        elements.status.textContent = result.approved
          ? "Saved approved draft loaded." : "Saved draft loaded for review.";
      } else {
        elements.status.textContent = "No saved browser-generated draft for this job.";
      }
    } catch (error) {
      if (captureUuid === opened && version === viewVersion) {
        elements.status.textContent = error.message;
      }
    }
  });

  window.addEventListener("pagehide", clearDownloads);
  controls();
})();
