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
    fs.readFileSync(path.join(__dirname, "../chrome-extension/preparation-ui.js"), "utf8"),
    context
  );
  return {
    el: (name) => elements.get(`preparation-${name}`),
    open: (id) => handlers["resume-capture-opened"]({ detail: { captureUuid: id } }),
    clear: () => handlers["resume-capture-cleared"](),
    click: (name) => elements.get(`preparation-${name}`).listeners.click(),
    change: (name) => elements.get(`preparation-${name}`).listeners.change()
  };
}

function sourceReport(job = "job-a") {
  return {
    research_uuid: `research-${job}`, research_sha256: "a".repeat(64),
    bundle: {
      capture_uuid: job, submitted_urls: ["https://example.com/about"],
      sources: [{
        source_uuid: "source-a", title: `About ${job}`,
        url: "https://example.com/about", text: "We build developer tools.",
        retrieved_at: "2026-11-19T20:00:00+00:00", publication_date: null
      }]
    }
  };
}
function guideReport(job = "job-a", guidance = "") {
  return {
    capture_uuid: job, guide_uuid: "guide-a", recruiter_guidance: guidance,
    sources: sourceReport(job).bundle.sources,
    markdown: "# Draft guide\n",
    guide: {
      company_notes: [{ statement: "The company builds developer tools.", source_uuid: "source-a", excerpt: "We build developer tools." }],
      documented_hiring_information: [],
      practice_questions: Array.from({ length: 5 }, (_, i) => ({
        question: `Practice question ${i}?`, requirement_uuid: "requirement-a",
        answer_draft: null, clarification: "Describe your own contribution.", evidence: []
      }))
    }
  };
}
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 409, json: async () => body });


test("saved research and guide load without network capture or AI generation", async () => {
  const calls = [];
  const ui = harness(async (url, options) => {
    calls.push(options.method);
    return response(url.includes("/research/") ? sourceReport() : guideReport());
  });
  await ui.open("job-a");
  assert.deepEqual(calls, ["GET", "GET"]);
  assert.equal(ui.el("generate").disabled, true);
  assert.match(ui.el("guide-status").textContent, /No new AI request/);
  assert.equal(ui.el("sources").children.length, 1);
  assert.ok(ui.el("guide").children.some((node) => node.textContent === "Not established by the captured sources."));
});


test("generating requires source review and forwards recruiter guidance", async () => {
  const posts = [];
  const guidance = "The recruiter said one remote interview.";
  const ui = harness(async (url, options) => {
    if (options.method === "POST") {
      const body = JSON.parse(options.body);
      posts.push(body);
      return response(guideReport("job-a", body.recruiter_guidance));
    }
    return response(url.includes("/research/") ? sourceReport() : null);
  });
  await ui.open("job-a");
  await ui.click("generate");
  assert.equal(posts.length, 0);
  ui.el("reviewed").checked = true;
  ui.change("reviewed");
  assert.equal(ui.el("generate").disabled, false);
  ui.el("recruiter").value = guidance;
  await ui.click("generate");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].sources_reviewed, true);
  assert.equal(posts[0].recruiter_guidance, guidance);
  assert.ok(ui.el("guide").children.some((node) => node.textContent === guidance));
});


test("capturing requires explicit official-source confirmation", async () => {
  let posts = 0;
  const ui = harness(async (url, options) => {
    if (options.method === "POST") { posts += 1; return response(sourceReport()); }
    return response(null);
  });
  await ui.open("job-a");
  ui.el("urls").value = "https://example.com/about";
  await ui.click("capture");
  assert.equal(posts, 0);
  ui.el("official").checked = true;
  ui.change("official");
  await ui.click("capture");
  assert.equal(posts, 1);
  assert.equal(ui.el("reviewed").checked, false);
  assert.equal(ui.el("generate").disabled, true);
});


test("switching jobs clears source fields, recruiter notes, and guide links", async () => {
  const ui = harness(async (url) => response(url.includes("/research/") ? sourceReport() : guideReport()));
  await ui.open("job-a");
  ui.el("recruiter").value = "Private recruiter notes";
  ui.clear();
  assert.equal(ui.el("urls").value, "");
  assert.equal(ui.el("recruiter").value, "");
  assert.equal(ui.el("sources").children.length, 0);
  assert.equal(ui.el("guide").children.length, 0);
  assert.equal(ui.el("review-label").hidden, true);
});


test("a delayed old job lookup cannot display sources for the new job", async () => {
  let finishFirst;
  const ui = harness(async (url) => {
    if (url.includes("job-a/research")) return new Promise((resolve) => { finishFirst = resolve; });
    return response(url.includes("/research/") ? sourceReport("job-b") : null);
  });
  const first = ui.open("job-a");
  await Promise.resolve();
  await Promise.resolve();
  ui.clear();
  await ui.open("job-b");
  finishFirst(response(sourceReport("job-a")));
  await first;
  assert.equal(ui.el("sources").children[0].children[0].textContent, "About job-b");
});


test("an outdated guide is reported without displaying stale content", async () => {
  const ui = harness(async (url) => url.includes("/research/")
    ? response(sourceReport()) : response({ detail: "This guide needs refresh." }, false));
  await ui.open("job-a");
  assert.match(ui.el("guide-status").textContent, /needs refresh/);
  assert.equal(ui.el("guide").children.length, 0);
});


test("editing source URLs clears confirmations and blocks guide generation", async () => {
  const ui = harness(async (url) => response(url.includes("/research/") ? sourceReport() : null));
  await ui.open("job-a");
  ui.el("reviewed").checked = true;
  ui.change("reviewed");
  assert.equal(ui.el("generate").disabled, false);
  ui.el("urls").value = "https://example.com/new-page";
  ui.el("urls").listeners.input();
  assert.equal(ui.el("official").checked, false);
  assert.equal(ui.el("reviewed").checked, false);
  assert.equal(ui.el("generate").disabled, true);
});
