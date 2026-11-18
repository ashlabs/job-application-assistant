"use strict";

const API_URL = "http://127.0.0.1:8000/captures";
const DRAFT_KEY = "captureDraft";
const TOKEN_KEY = "captureToken";

const ui = {
  token: document.getElementById("api-token"),
  settings: document.getElementById("settings"),
  saveSettings: document.getElementById("save-settings"),
  page: document.getElementById("capture-page"),
  selection: document.getElementById("capture-selection"),
  paste: document.getElementById("start-paste"),
  form: document.getElementById("capture-form"),
  url: document.getElementById("source-url"),
  title: document.getElementById("page-title"),
  time: document.getElementById("captured-at"),
  method: document.getElementById("capture-method"),
  text: document.getElementById("jd-text"),
  confirmed: document.getElementById("confirmed"),
  save: document.getElementById("save-capture"),
  discard: document.getElementById("discard-capture"),
  status: document.getElementById("status")
};

let draft = null;
let busy = true;
let storageQueue = Promise.resolve();

function showStatus(message, kind = "") {
  ui.status.textContent = message;
  ui.status.dataset.kind = kind;
}

function persistDraft() {
  // Snapshot now and serialize writes so older edits cannot replace newer ones.
  const snapshot = draft === null ? null : structuredClone(draft);
  const operation = storageQueue.then(() =>
    chrome.storage.local.set({ [DRAFT_KEY]: snapshot })
  );
  storageQueue = operation.catch(() => {});
  return operation;
}

function updateControls() {
  const locked = busy || draft === null || draft.attempted;

  for (const field of [ui.url, ui.title, ui.text]) {
    field.disabled = locked;
  }

  ui.confirmed.disabled = busy || draft === null || draft.attempted;
  ui.save.disabled = (
    busy ||
    draft === null ||
    !ui.token.value.trim() ||
    (!draft.attempted && !ui.confirmed.checked)
  );
  ui.save.textContent = draft?.attempted
    ? "Retry same capture"
    : "Save job description";

  ui.page.disabled = busy;
  ui.selection.disabled = busy;
  ui.paste.disabled = busy;
  ui.discard.disabled = busy || draft === null;
  ui.saveSettings.disabled = busy;
  ui.token.disabled = busy;
}

function renderDraft() {
  ui.url.value = draft?.capture.source_url ?? "";
  ui.title.value = draft?.capture.page_title ?? "";
  ui.text.value = draft?.capture.jd_text ?? "";
  ui.time.textContent = draft?.capture.captured_at ?? "Not captured yet";
  ui.method.textContent = draft?.capture.capture_method ?? "Not selected";

  // Reopening an editable draft requires confirmation again.
  ui.confirmed.checked = Boolean(draft?.attempted);
  updateControls();
}

function mayReplaceDraft() {
  if (draft === null) {
    return true;
  }

  const message = draft.attempted
    ? "The previous save may already have reached the server. "
      + "Discard this local draft and start another capture?"
    : "Discard the current unsaved draft and start another capture?";

  return window.confirm(message);
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true
  });

  if (!tab || typeof tab.id !== "number") {
    throw new Error("No active tab is available.");
  }

  return tab;
}

async function beginCapture(method) {
  if (!mayReplaceDraft()) {
    return;
  }

  busy = true;
  updateControls();

  try {
    let sourceUrl = "";
    let pageTitle = null;
    let text = "";

    if (method === "paste") {
      // Manual entry remains available if tab metadata is inaccessible.
      try {
        const tab = await activeTab();
        sourceUrl = /^https?:\/\//i.test(tab.url ?? "") ? tab.url : "";
        pageTitle = tab.title?.trim() || null;
      } catch {
        // The user can enter the source URL manually.
      }
    } else {
      const tab = await activeTab();
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (captureMethod) => {
          const selected = window.getSelection()?.toString() ?? "";
          const container = (
            document.querySelector("main")
            || document.querySelector('[role="main"]')
            || document.querySelector("article")
            || document.body
          );

          return {
            url: window.location.href,
            title: document.title,
            text: captureMethod === "selection"
              ? selected
              : (container?.innerText ?? "")
          };
        },
        args: [method]
      });

      const result = results[0]?.result;
      if (!result || !/^https?:\/\//i.test(result.url)) {
        throw new Error(
          "This page cannot be captured. Use Paste instead and enter its source URL."
        );
      }

      sourceUrl = result.url;
      pageTitle = result.title?.trim() || null;
      text = result.text.trim();

      if (!text) {
        throw new Error(
          method === "selection"
            ? "No selected text was found. Select the JD first, or use Paste instead."
            : "No readable text was found. Use selected text or Paste instead."
        );
      }
    }

    draft = {
      attempted: false,
      capture: {
        capture_uuid: crypto.randomUUID(),
        source_url: sourceUrl,
        page_title: pageTitle,
        captured_at: new Date().toISOString(),
        capture_method: method,
        jd_text: text
      }
    };

    await persistDraft();
    renderDraft();
    showStatus(
      method === "paste"
        ? "Paste the job description, check the source URL, and review before saving."
        : "Review the captured text and remove anything unrelated."
    );
  } catch (error) {
    showStatus(error.message || "Capture failed.", "error");
  } finally {
    busy = false;
    updateControls();
  }
}

function recordEdits() {
  if (draft === null || draft.attempted || busy) {
    return;
  }

  draft.capture.source_url = ui.url.value;
  draft.capture.page_title = ui.title.value.trim() || null;
  draft.capture.jd_text = ui.text.value;
  ui.confirmed.checked = false;
  updateControls();

  persistDraft().catch(() => {
    showStatus(
      "Could not preserve the latest edits. Keep this popup open and try again.",
      "error"
    );
  });
}

async function saveCapture(event) {
  event.preventDefault();

  if (busy || draft === null) {
    return;
  }

  if (!draft.attempted) {
    if (!ui.form.reportValidity() || !ui.confirmed.checked) {
      return;
    }

    if (!ui.text.value.trim()) {
      showStatus("The job description cannot be blank.", "error");
      return;
    }

    draft.capture.source_url = ui.url.value.trim();
    draft.capture.page_title = ui.title.value.trim() || null;
    draft.capture.jd_text = ui.text.value.trim();

    // Validate the URL scheme before freezing the retry payload.
    try {
      const url = new URL(draft.capture.source_url);
      if (!["http:", "https:"].includes(url.protocol)) {
        throw new Error("Unsupported URL scheme.");
      }
    } catch {
      showStatus("Enter a valid HTTP or HTTPS source URL.", "error");
      return;
    }
  }

  const token = ui.token.value.trim();
  if (!token) {
    ui.settings.open = true;
    showStatus("Enter your local capture token first.", "error");
    return;
  }

  busy = true;
  updateControls();

  try {
    // Persist the exact retry payload before sending the request.
    draft.attempted = true;
    await persistDraft();
    updateControls();

    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Capture-Token": token
      },
      body: JSON.stringify({
        confirmed: true,
        capture: draft.capture
      }),
      signal: AbortSignal.timeout(15000),
      credentials: "omit",
      redirect: "error"
    });

    if (response.status !== 200 && response.status !== 201) {
      const messages = {
        401: "The capture token was rejected. Check Connection settings and retry.",
        409: "This UUID already has different saved content. Discard this draft to start a new capture.",
        422: "The API rejected this capture. Check the API response in the popup's developer tools.",
        503: "Storage is unavailable. Retry this same capture later."
      };
      throw new Error(
        messages[response.status]
        || `Save failed with HTTP ${response.status}. Retry later.`
      );
    }

    const receipt = await response.json();
    if (
      receipt.capture_uuid !== draft.capture.capture_uuid
      || !["created", "already_saved"].includes(receipt.status)
    ) {
      throw new Error("Unexpected save receipt. Retry this same capture.");
    }

    // Clear storage first; if interrupted, reopening can safely retry.
    await chrome.storage.local.set({ [DRAFT_KEY]: null });
    draft = null;
    renderDraft();
    showStatus(
      receipt.status === "created"
        ? "Job description saved."
        : "This capture was already saved. No duplicate was created.",
      "success"
    );
  } catch (error) {
    showStatus(
      error.message
        ? `${error.message} Your draft is retained.`
        : "Could not reach the API. Your draft is retained.",
      "error"
    );
  } finally {
    busy = false;
    updateControls();
  }
}

async function discardCapture() {
  if (busy || draft === null) {
    return;
  }

  const message = draft.attempted
    ? "Discard this local draft? A previous save may already exist on the server."
    : "Discard this unsaved draft?";

  if (!window.confirm(message)) {
    return;
  }

  busy = true;
  updateControls();

  try {
    await storageQueue;
    await chrome.storage.local.set({ [DRAFT_KEY]: null });
    draft = null;
    renderDraft();
    showStatus("Local draft discarded.");
  } catch {
    showStatus("Could not discard the draft. Try again.", "error");
  } finally {
    busy = false;
    updateControls();
  }
}

async function initialize() {
  updateControls();

  try {
    // Keep local settings and drafts unavailable to content scripts.
    await chrome.storage.local.setAccessLevel({
      accessLevel: "TRUSTED_CONTEXTS"
    });

    const stored = await chrome.storage.local.get([DRAFT_KEY, TOKEN_KEY]);
    draft = stored[DRAFT_KEY] ?? null;
    ui.token.value = stored[TOKEN_KEY] ?? "";

    renderDraft();

    if (draft?.attempted) {
      showStatus(
        "An earlier save has no confirmed receipt here. Retry the same capture."
      );
    } else if (draft !== null) {
      showStatus("Draft restored. Review and confirm it before saving.");
    }

    ui.page.addEventListener("click", () => beginCapture("page"));
    ui.selection.addEventListener("click", () => beginCapture("selection"));
    ui.paste.addEventListener("click", () => beginCapture("paste"));
    ui.discard.addEventListener("click", discardCapture);
    ui.form.addEventListener("submit", saveCapture);

    for (const field of [ui.url, ui.title, ui.text]) {
      field.addEventListener("input", recordEdits);
    }

    ui.confirmed.addEventListener("change", updateControls);
    ui.token.addEventListener("input", updateControls);

    ui.saveSettings.addEventListener("click", async () => {
      busy = true;
      updateControls();
      try {
        await chrome.storage.local.set({
          [TOKEN_KEY]: ui.token.value.trim()
        });
        showStatus("Connection settings saved.", "success");
      } catch {
        showStatus("Could not save connection settings.", "error");
      } finally {
        busy = false;
        updateControls();
      }
    });

    busy = false;
    updateControls();
  } catch {
    showStatus(
      "Could not initialize local storage. Close and reopen the extension.",
      "error"
    );
  }
}

initialize();