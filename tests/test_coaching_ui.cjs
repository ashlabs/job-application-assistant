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
    URL: class extends URL {
      static createObjectURL() { return "blob:test"; }
      static revokeObjectURL() {}
    },
    chrome: { storage: { local: { get: async () => ({ captureToken: "token" }) } } },
    fetch: fetcher,
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
      dispatchEvent(event) { return handlers[event.type]?.(event); },
      addEventListener(name, callback) { handlers[name] = callback; }
    },
    window: { addEventListener() {} }
  };
  context.setBusy = (value) => { context.busy = value; };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "../chrome-extension/coaching-ui.js"), "utf8"),
    context
  );
  return {
    el: (name) => elements.get(`coaching-${name}`),
    open: (id) => handlers["resume-capture-opened"]({ detail: { captureUuid: id } }),
    clear: () => handlers["resume-capture-cleared"](),
    click: (name) => elements.get(`coaching-${name}`).listeners.click(),
    change: (name) => elements.get(`coaching-${name}`).listeners.change(),
    input: () => elements.get("coaching-answer").listeners.input(),
    emit: (name, detail) => handlers[name]?.({ detail }),
    setBusy: (value) => { context.busy = value; }
  };
}

function state(overrides = {}) {
  return {
    session_uuid: "session-a", capture_uuid: "job-a", guide_uuid: "guide-a",
    created_at: "2026-11-19T20:00:00+00:00", revision: "a".repeat(64),
    status: "active", phase: "main", question_number: 1,
    question: "Describe your leadership example?", followup_question: null,
    request_count: 0, latest_feedback: null, history: [], last_error: null,
    preserved_answer: "", context_outdated: false,
    ...overrides
  };
}
function feedback() {
  const value = Object.fromEntries([
    "relevance", "structure", "specificity", "ownership", "results", "clarity"
  ].map((name) => [name, { score: 3, explanation: "Give more specific detail." }]));
  return { ...value, suggestions: ["Explain your personal contribution."], follow_up: null };
}
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 409, json: async () => body });
const listing = (s) => [{ session_uuid: s.session_uuid, created_at: s.created_at }];


test("saved paused session loads without AI and enables Resume", async () => {
  const saved = state({ status: "paused" });
  const methods = [];
  const ui = harness(async (url, options) => {
    methods.push(options.method);
    return response(url.endsWith("/coaching") ? listing(saved) : saved);
  });
  await ui.open("job-a");
  assert.deepEqual(methods, ["GET", "GET"]);
  assert.equal(ui.el("resume").disabled, false);
  assert.equal(ui.el("submit").disabled, true);
  assert.match(ui.el("progress").textContent, /paused/);
});


test("new practice requires a current loaded guide", async () => {
  const ui = harness(async () => response([]));
  await ui.open("job-a");
  assert.equal(ui.el("start").disabled, true);
  ui.emit("preparation-guide-ready", { captureUuid: "job-a", guideUuid: "guide-a" });
  assert.equal(ui.el("start").disabled, false);
  ui.emit("preparation-guide-cleared", {});
  assert.equal(ui.el("start").disabled, true);
});


test("submitting renders feedback and clears the submitted answer", async () => {
  const saved = state();
  const posts = [];
  const ui = harness(async (url, options) => {
    if (options.method === "POST") {
      posts.push(JSON.parse(options.body));
      return response(state({ revision: "b".repeat(64), phase: "review", request_count: 1, latest_feedback: feedback() }));
    }
    return response(url.endsWith("/coaching") ? listing(saved) : saved);
  });
  await ui.open("job-a");
  ui.el("answer").value = "I coached engineers.";
  ui.input();
  assert.equal(ui.el("submit").disabled, false);
  await ui.click("submit");
  assert.equal(posts[0].action, "answer");
  assert.equal(posts[0].answer, "I coached engineers.");
  assert.equal(posts[0].expected_revision, saved.revision);
  assert.equal(ui.el("answer").value, "");
  assert.equal(ui.el("next").disabled, false);
  assert.equal(ui.el("submit").disabled, true);
  assert.ok(ui.el("feedback").children.some((child) => /Ownership 3\/5/.test(child.textContent)));
});


test("lost answer responses preserve text and reuse the request identity", async () => {
  const saved = state();
  const posts = [];
  const ui = harness(async (url, options) => {
    if (options.method === "POST") {
      posts.push(JSON.parse(options.body));
      if (posts.length === 1) throw new Error("Simulated lost response");
      return response(state({ revision: "b".repeat(64), phase: "review", request_count: 1 }));
    }
    return response(url.endsWith("/coaching") ? listing(saved) : saved);
  });
  await ui.open("job-a");
  ui.el("answer").value = "My practice answer.";
  ui.input();
  await ui.click("submit");
  assert.equal(ui.el("answer").value, "My practice answer.");
  assert.match(ui.el("status").textContent, /Reload session/);
  await ui.click("submit");
  assert.deepEqual(posts[0], posts[1]);
});


test("completed sessions block further answers and show completion", async () => {
  const saved = state({ status: "complete", question: null, question_number: 5 });
  const ui = harness(async (url) => response(url.endsWith("/coaching") ? listing(saved) : saved));
  await ui.open("job-a");
  assert.match(ui.el("progress").textContent, /Five-question session complete/);
  for (const name of ["submit", "next", "skip", "retry", "pause", "resume"]) {
    assert.equal(ui.el(name).disabled, true);
  }
});


test("older guide snapshots are explicit while saved practice stays usable", async () => {
  const saved = state({ context_outdated: true });
  const ui = harness(async (url) => response(url.endsWith("/coaching") ? listing(saved) : saved));
  await ui.open("job-a");
  assert.match(ui.el("context").textContent, /earlier guide snapshot/);
  assert.equal(ui.el("skip").disabled, false);
});


test("switching jobs clears old answers, history links, and session controls", async () => {
  const saved = state();
  const ui = harness(async (url) => response(url.endsWith("/coaching") ? listing(saved) : saved));
  await ui.open("job-a");
  ui.el("answer").value = "Private draft answer.";
  ui.clear();
  assert.equal(ui.el("answer").value, "");
  assert.equal(ui.el("workspace").hidden, true);
  assert.equal(ui.el("history").children.length, 0);
  assert.equal(ui.el("download").children.length, 0);
  assert.equal(ui.el("submit").disabled, true);
});


test("busy page gives a visible message instead of silently ignoring click", async () => {
  let posts = 0;
  const saved = state();
  const ui = harness(async (url, options) => {
    if (options.method === "POST") posts += 1;
    return response(url.endsWith("/coaching") ? listing(saved) : saved);
  });
  await ui.open("job-a");
  ui.el("answer").value = "My answer.";
  ui.input();
  ui.setBusy(true);
  await ui.click("submit");
  assert.match(ui.el("status").textContent, /page is busy/);
  assert.equal(posts, 0);
});


test("delayed session data from an old job cannot replace the current practice", async () => {
  let finishOldRead;
  let signalOldRead;
  const oldReadStarted = new Promise((resolve) => { signalOldRead = resolve; });
  const second = state({ capture_uuid: "job-b", session_uuid: "session-b", question: "New job question?" });
  const ui = harness(async (url) => {
    if (url.includes("job-a") && !url.endsWith("/coaching")) {
      return new Promise((resolve) => { finishOldRead = resolve; signalOldRead(); });
    }
    const saved = url.includes("job-b") ? second : state();
    return response(url.endsWith("/coaching") ? listing(saved) : saved);
  });
  const first = ui.open("job-a");
  await oldReadStarted;
  ui.clear();
  await ui.open("job-b");
  finishOldRead(response(state()));
  await first;
  assert.equal(ui.el("question").textContent, "New job question?");
});
