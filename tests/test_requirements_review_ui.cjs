const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

function harness(fetcher) {
  const elements = new Map();
  function element(tag = "div") {
    return {
      tag, value: "", textContent: "", checked: false, hidden: false, disabled: false,
      children: [], style: {}, listeners: {},
      addEventListener(name, fn) { this.listeners[name] = fn; },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      querySelectorAll() { return this.children.flatMap(child => [child, ...child.querySelectorAll()]); }
    };
  }
  const handlers = {};
  const events = [];
  const context = {
    console, structuredClone, AbortSignal, crypto: webcrypto, busy: false,
    chrome: { storage: { local: { get: async () => ({ captureToken: "token" }) } } },
    fetch: fetcher,
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
    document: {
      getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
      createElement: element,
      addEventListener(name, fn) { handlers[name] = fn; },
      dispatchEvent(event) { events.push(event); handlers[event.type]?.(event); }
    }
  };
  context.setBusy = value => { context.busy = value; };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../chrome-extension/requirements-review-ui.js"), "utf8"), context);
  const el = name => elements.get(`requirements-${name}`);
  return {
    el, events,
    open: id => handlers["requirements-loaded"]({ detail: { captureUuid: id } }),
    clear: () => handlers["resume-capture-cleared"]({}),
    click: name => el(name).listeners.click(),
    confirm() { el("confirm").checked = true; el("confirm").listeners.change(); },
    fields: () => el("rows").children[0].children.filter(child => child.tag === "label").map(label => label.children[1]),
  };
}
const snapshot = () => ({
  revision: "a".repeat(64), duplicate_groups: [],
  requirements: { capture_uuid: "job-a", jd_text_sha256: "b".repeat(64), company_name: "Example", job_title: "Engineer",
    requirements: [{ requirement_uuid: "r1", description: "Python", kind: "qualification", importance: "required", source_excerpt: "Python required." }] }
});
const response = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });

test("opening the editor only reads; exact confirmed edits are sent on save", async () => {
  const calls = [];
  const ui = harness(async (url, options) => {
    calls.push({ url, ...options });
    return response(options.method === "GET" ? snapshot() : { ...snapshot(), requirements: JSON.parse(options.body).requirements });
  });
  ui.open("job-a");
  await ui.click("edit");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "GET");
  assert.equal(ui.el("save").disabled, true);
  ui.fields()[2].value = "preferred";
  ui.confirm();
  await ui.click("save");
  const sent = JSON.parse(calls[1].body);
  assert.equal(calls[1].method, "PUT");
  assert.equal(sent.expected_revision, "a".repeat(64));
  assert.equal(sent.requirements.requirements[0].importance, "preferred");
  assert.equal(sent.requirements.requirements[0].requirement_uuid, "r1");
  assert.equal(ui.events[0].type, "requirements-review-saved");
  assert.equal(ui.el("editor").hidden, true);
});

test("editing resets confirmation; cancelling never sends a write", async () => {
  const calls = [];
  const ui = harness(async (_, options) => { calls.push(options.method); return response(snapshot()); });
  ui.open("job-a");
  await ui.click("edit");
  ui.confirm();
  ui.el("rows").listeners.input();
  assert.equal(ui.el("save").disabled, true);
  await ui.click("save");
  ui.click("cancel");
  assert.deepEqual(calls, ["GET"]);
  assert.match(ui.el("review-status").textContent, /unchanged/);
});

test("added items get stable IDs and need a supporting excerpt", async () => {
  const calls = [];
  const ui = harness(async (_, options) => { calls.push(options.method); return response(snapshot()); });
  ui.open("job-a");
  await ui.click("edit");
  ui.click("add");
  assert.equal(ui.el("rows").children.length, 2);
  ui.confirm();
  await ui.click("save");
  assert.deepEqual(calls, ["GET"]);
  assert.match(ui.el("review-status").textContent, /exact supporting JD excerpt/);
  const row = ui.el("rows").children[1];
  row.children.at(-1).listeners.click();
  assert.equal(ui.el("rows").children.length, 1);
  assert.equal(ui.el("confirm").checked, false);
});

for (const failure of ["conflict", "lost response"]) {
  test(`${failure} preserves the edited draft`, async () => {
    const ui = harness(async (_, options) => {
      if (options.method === "GET") return response(snapshot());
      if (failure === "lost response") throw new Error("network");
      return response({ detail: "Requirements changed in another tab." }, false, 409);
    });
    ui.open("job-a");
    await ui.click("edit");
    ui.fields()[2].value = "preferred";
    ui.confirm();
    await ui.click("save");
    assert.equal(ui.el("editor").hidden, false);
    assert.equal(ui.fields()[2].value, "preferred");
    assert.equal(ui.events.length, 0);
    assert.match(ui.el("review-status").textContent, failure === "conflict" ? /another tab/ : /may have completed/);
  });
}

test("a delayed read from another job cannot reopen the old editor", async () => {
  let release;
  const ui = harness(() => new Promise(resolve => { release = resolve; }));
  ui.open("job-a");
  const pending = ui.click("edit");
  await new Promise(resolve => setImmediate(resolve));
  ui.clear();
  ui.open("job-b");
  release(response(snapshot()));
  await pending;
  assert.equal(ui.el("editor").hidden, true);
  assert.equal(ui.el("rows").children.length, 0);
});
