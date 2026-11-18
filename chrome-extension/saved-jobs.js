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
  text: document.getElementById("job-text")
};

let busy = false;

function showStatus(message, kind = "") {
  ui.status.textContent = message;
  ui.status.dataset.kind = kind;
}

function setBusy(value) {
  busy = value;
  ui.refresh.disabled = value;

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

function clearDetail() {
  ui.detail.hidden = true;
  ui.empty.hidden = false;

  for (const button of ui.list.querySelectorAll("button")) {
    button.removeAttribute("aria-current");
  }
}

async function getJson(path) {
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
      headers: { "X-Capture-Token": token },
      signal: AbortSignal.timeout(15000),
      credentials: "omit",
      redirect: "error",
      cache: "no-store"
    });
  } catch {
    throw new Error(
      "Could not reach the local API. Start the server, then try again."
    );
  }

  if (!response.ok) {
    const messages = {
      401: "The token was rejected. Update Connection settings in the extension popup.",
      404: "This capture could not be found. Refresh the list.",
      500: "Stored capture data could not be read.",
      503: "Capture storage is unavailable. Try again later."
    };

    throw new Error(
      messages[response.status]
      || `Request failed with HTTP ${response.status}.`
    );
  }

  return response.json();
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

    button.setAttribute("aria-current", "true");
    ui.empty.hidden = true;
    ui.detail.hidden = false;
    showStatus("Capture loaded.");
  } catch (error) {
    showStatus(error.message || "Could not load the capture.", "error");
  } finally {
    setBusy(false);
  }
}

async function refreshCaptures() {
  if (busy) {
    return;
  }

  setBusy(true);
  clearDetail();
  ui.list.replaceChildren();
  showStatus("Loading saved captures…");

  try {
    const captures = await getJson("/captures");

    if (!Array.isArray(captures)) {
      throw new Error("The API returned an unexpected capture list.");
    }

    for (const capture of captures) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      const title = document.createElement("span");
      const time = document.createElement("span");

      button.type = "button";
      button.disabled = true;

      title.className = "job-list-title";
      title.textContent = capture.page_title || capture.source_url;

      time.className = "job-list-time";
      time.textContent = displayTime(capture.captured_at);

      button.append(title, time);
      button.addEventListener("click", () =>
        openCapture(capture.capture_uuid, button)
      );

      item.append(button);
      ui.list.append(item);
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

ui.refresh.addEventListener("click", refreshCaptures);
refreshCaptures();