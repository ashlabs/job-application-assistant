"use strict";

(() => {
  const el = name => document.getElementById(`requirements-${name}`);
  const ui = Object.fromEntries([
    "edit", "review-status", "editor", "company", "title", "rows", "add",
    "duplicates", "confirm", "save", "cancel"
  ].map(name => [name, el(name)]));
  let captureUuid = null;
  let snapshot = null;
  let draft = null;
  let rows = [];
  let working = false;
  let version = 0;

  function controls() {
    ui.edit.disabled = working || !captureUuid;
    ui.save.disabled = working || !draft || !ui.confirm.checked;
    ui.cancel.disabled = working;
    ui.add.disabled = working || !draft || rows.length >= 200;
    for (const input of ui.editor.querySelectorAll("input, textarea, select, button")) {
      if (![ui.save, ui.cancel, ui.add].includes(input)) input.disabled = working;
    }
  }
  function close() {
    snapshot = null;
    draft = null;
    rows = [];
    ui.rows.replaceChildren();
    ui.confirm.checked = false;
    ui.editor.hidden = true;
    controls();
  }
  function changed() {
    ui.confirm.checked = false;
    controls();
  }
  async function request(body) {
    const requestedCapture = captureUuid;
    const { captureToken } = await chrome.storage.local.get("captureToken");
    if (!captureToken?.trim()) throw new Error("Set the capture token in Connection settings.");
    let response;
    try {
      response = await fetch(`http://127.0.0.1:8000/captures/${encodeURIComponent(requestedCapture)}/requirements/review`, {
        method: body ? "PUT" : "GET",
        headers: { "X-Capture-Token": captureToken.trim(), ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
        credentials: "omit", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(15000)
      });
    } catch {
      throw new Error(body
        ? "No response. Your save may have completed; retry the same edits or reopen the job to check."
        : "Could not reach the local API.");
    }
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `Review failed: HTTP ${response.status}.`);
    return value;
  }
  function field(parent, label, value, options) {
    const wrapper = document.createElement("label");
    wrapper.style.display = "block";
    const heading = document.createElement("span");
    heading.textContent = label;
    const input = document.createElement(options ? "select" : "textarea");
    if (options) for (const value of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      input.append(option);
    }
    input.value = value;
    wrapper.append(heading, input);
    parent.append(wrapper);
    return input;
  }
  function collect() {
    draft.company_name = ui.company.value.trim() || null;
    draft.job_title = ui.title.value.trim() || null;
    draft.requirements = rows.map(row => ({
      requirement_uuid: row.uuid,
      description: row.description.value.trim(), kind: row.kind.value,
      importance: row.importance.value, source_excerpt: row.excerpt.value.trim()
    }));
  }
  function render() {
    rows = [];
    ui.rows.replaceChildren();
    for (const item of draft.requirements) {
      const box = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = `Requirement ${rows.length + 1}`;
      box.append(legend);
      const row = {
        uuid: item.requirement_uuid,
        description: field(box, "Requirement wording", item.description),
        kind: field(box, "Type", item.kind, ["qualification", "constraint"]),
        importance: field(box, "Importance", item.importance, ["required", "preferred", "unspecified"]),
        excerpt: field(box, "Exact supporting JD excerpt", item.source_excerpt)
      };
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove this requirement";
      remove.addEventListener("click", () => {
        if (working) return;
        collect();
        draft.requirements = draft.requirements.filter(item => item.requirement_uuid !== row.uuid);
        changed();
        render();
      });
      box.append(remove);
      rows.push(row);
      ui.rows.append(box);
    }
    controls();
  }

  ui.edit.addEventListener("click", async () => {
    if (working || busy || !captureUuid) return;
    const opened = captureUuid;
    const lookup = ++version;
    working = true;
    setBusy(true);
    controls();
    ui["review-status"].textContent = "Loading requirements for review…";
    try {
      const value = await request();
      if (captureUuid !== opened || version !== lookup) return;
      snapshot = value;
      draft = structuredClone(value.requirements);
      ui.company.value = draft.company_name || "";
      ui.title.value = draft.job_title || "";
      ui.confirm.checked = false;
      ui.duplicates.textContent = value.duplicate_groups.length
        ? `${value.duplicate_groups.length} duplicate description group(s) found. Remove duplicates before saving.`
        : "No exact duplicate descriptions found. Review for overlapping meaning as well.";
      ui.editor.hidden = false;
      render();
      ui["review-status"].textContent = "Review the editable fields below. Saving requires explicit confirmation.";
    } catch (error) {
      if (captureUuid === opened && version === lookup) ui["review-status"].textContent = error.message;
    } finally {
      working = false;
      setBusy(false);
      controls();
    }
  });
  ui.add.addEventListener("click", () => {
    if (working || !draft || rows.length >= 200) return;
    collect();
    draft.requirements.push({ requirement_uuid: crypto.randomUUID(), description: "", kind: "qualification", importance: "unspecified", source_excerpt: "" });
    changed();
    render();
  });
  ui.save.addEventListener("click", async () => {
    if (working || busy || !draft || !ui.confirm.checked) return;
    collect();
    if (draft.requirements.some(item => !item.description || !item.source_excerpt)) {
      ui["review-status"].textContent = "Every requirement needs wording and an exact supporting JD excerpt.";
      return;
    }
    const opened = captureUuid;
    const lookup = ++version;
    const body = { expected_revision: snapshot.revision, requirements: structuredClone(draft), confirmed: true };
    working = true;
    setBusy(true);
    controls();
    ui["review-status"].textContent = "Saving reviewed requirements…";
    try {
      const saved = await request(body);
      if (captureUuid !== opened || version !== lookup) return;
      close();
      document.dispatchEvent(new CustomEvent("requirements-review-saved", {
        detail: { captureUuid: opened, requirements: saved.requirements }
      }));
      ui["review-status"].textContent = "Reviewed requirements saved. Reassess the match and regenerate dependent drafts or guides as needed.";
    } catch (error) {
      if (captureUuid === opened && version === lookup) ui["review-status"].textContent = error.message;
    } finally {
      working = false;
      setBusy(false);
      controls();
    }
  });
  ui.cancel.addEventListener("click", () => {
    if (working) return;
    close();
    ui["review-status"].textContent = "Edits cancelled. Saved requirements are unchanged.";
  });
  for (const input of [ui.rows, ui.company, ui.title]) {
    input.addEventListener("input", changed);
    input.addEventListener("change", changed);
  }
  ui.confirm.addEventListener("change", controls);
  document.addEventListener("requirements-loaded", event => {
    version += 1;
    captureUuid = event.detail.captureUuid;
    close();
    ui["review-status"].textContent = "";
  });
  document.addEventListener("resume-capture-cleared", event => {
    if (event.detail?.preserveRequirementsReview) return;
    version += 1;
    captureUuid = null;
    close();
    ui["review-status"].textContent = "";
  });
  controls();
})();
