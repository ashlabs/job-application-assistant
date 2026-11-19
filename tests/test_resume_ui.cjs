/* Browser-control tests using Node's built-in test runner. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const { webcrypto } = require("node:crypto");

function harness(fetcher) {
  const elements = new Map();
  function element() {
    return {
      value: "", textContent: "", checked: false, hidden: false,
      disabled: false, children: [], style: {}, listeners: {},
      addEventListener(name, callback) { this.listeners[name] = callback; },
      replaceChildren() { this.children = []; },
      append(child) { this.children.push(child); }
    };
  }
  const handlers = {};
  const context = {
    console, Blob, Uint8Array, AbortSignal, atob,
    crypto: webcrypto, busy: false,
    URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
    chrome: { storage: { local: { get: async () => ({ captureToken: "token" }) } } },
    fetch: fetcher,
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
      addEventListener(name, callback) { handlers[name] = callback; }
    },
    window: { addEventListener() {} }
  };
  context.setBusy = (value) => { context.busy = value; };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "../chrome-extension/resume-ui.js"), "utf8"),
    context
  );
  return {
    el: (name) => elements.get(`resume-${name}`),
    open: (id) => handlers["resume-capture-opened"]({ detail: { captureUuid: id } }),
    clear: () => handlers["resume-capture-cleared"](),
    click: (name) => elements.get(`resume-${name}`).listeners.click(),
    change: () => elements.get("resume-confirm").listeners.change()
  };
}

function draft(capture = "job-a", approved = false) {
  return {
    resume_uuid: "draft-a", capture_uuid: capture,
    review_token: "a".repeat(64), approved,
    text: "Example Candidate\nEDUCATION\nCompleted\n",
    evidence: { selection: {}, approved_source_snapshot: {} }
  };
}
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 409, json: async () => body });


test("reopening loads draft without generating or approving", async () => {
  const calls = [];
  const ui = harness(async (url, options) => {
    calls.push(options.method);
    return response(draft());
  });
  await ui.open("job-a");
  assert.deepEqual(calls, ["GET"]);
  assert.equal(ui.el("text").textContent, draft().text);
  assert.equal(ui.el("approve").disabled, true);
  assert.equal(ui.el("export").disabled, true);
});


test("approval requires confirmation and export creates both links", async () => {
  const ui = harness(async (url) => {
    if (url.endsWith("/export")) return response({ files: {
      "resume.docx": "dGVzdA==", "resume.pdf": "dGVzdA=="
    } });
    return response(draft("job-a", url.endsWith("/approve")));
  });
  await ui.open("job-a");
  ui.el("confirm").checked = true;
  ui.change();
  assert.equal(ui.el("approve").disabled, false);
  await ui.click("approve");
  assert.equal(ui.el("export").disabled, false);
  await ui.click("export");
  assert.deepEqual(ui.el("downloads").children.map((link) => link.download),
    ["resume.docx", "resume.pdf"]);
  ui.clear();
  assert.equal(ui.el("downloads").children.length, 0);
  assert.equal(ui.el("review").hidden, true);
});


test("delayed result from a previous job cannot replace current draft", async () => {
  let finishFirst;
  const ui = harness(async (url) => {
    if (url.includes("job-a")) return new Promise((resolve) => { finishFirst = resolve; });
    return response(draft("job-b"));
  });
  const first = ui.open("job-a");
  await Promise.resolve();
  await Promise.resolve();
  await ui.open("job-b");
  finishFirst(response({ ...draft("job-a"), text: "Wrong old draft" }));
  await first;
  assert.equal(ui.el("text").textContent, draft("job-b").text);
});


test("generation response is not overwritten by an earlier saved-draft lookup", async () => {
  let finishLookup;
  const ui = harness(async (url, options) => {
    if (options.method === "GET") return new Promise((resolve) => { finishLookup = resolve; });
    return response({ ...draft(), text: "New generated draft" });
  });
  const lookup = ui.open("job-a");
  await Promise.resolve();
  await Promise.resolve();
  ui.el("name").value = "Example Candidate";
  await ui.click("generate");
  finishLookup(response(draft()));
  await lookup;
  assert.equal(ui.el("text").textContent, "New generated draft");
});
