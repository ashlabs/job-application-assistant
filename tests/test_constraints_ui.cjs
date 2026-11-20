/* Practical compatibility is visible separately from qualification credit. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

function harness() {
  const elements = new Map();
  const element = () => ({
    textContent: "", children: [], style: {},
    addEventListener() {},
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); }
  });
  const context = vm.createContext({
    console,
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
      createDocumentFragment: element
    }
  });
  const source = fs.readFileSync(path.join(__dirname, "../chrome-extension/saved-jobs.js"), "utf8");
  vm.runInContext(source.replace(/refreshCaptures\(\);\s*$/, ""), context);
  vm.runInContext(`currentRequirements = { requirements: [
    {requirement_uuid: "q", description: "Python experience", kind: "qualification", importance: "required"},
    {requirement_uuid: "c", description: "Required onsite", kind: "constraint", importance: "required"}
  ]};`, context);
  const text = node => node.textContent + node.children.map(text).join(" ");
  return {
    display(constraints) {
      context.report = {
        match: { capture_uuid: "job", assessments: [{ requirement_uuid: "q", classification: "evidence_missing", explanation: "Unknown", evidence: [] }], constraints },
        score: { percentage: 0, earned_weighted_credit: 0, possible_weighted_credit: 2,
          scored_qualification_count: 1, unspecified_qualification_uuids: [], constraint_uuids: ["c"] }
      };
      vm.runInContext('displayMatch(report, "job")', context);
    },
    text: id => text(elements.get(id)),
    clear: () => vm.runInContext("clearMatch()", context)
  };
}
const evidence = [{ record_type: "fact", record_uuid: "fact-1", field_name: "statement", excerpt: "Remote only" }];

test("blocking preference and evidence appear outside qualification score", () => {
  const ui = harness();
  ui.display([{ requirement_uuid: "c", classification: "blocking", explanation: "Onsite conflicts with remote only.", evidence }]);
  assert.match(ui.text("constraint-assessment-list"), /Blocking constraint/);
  assert.match(ui.text("constraint-assessment-list"), /Remote only/);
  assert.equal(ui.text("match-percentage"), "Documented match: 0.0%");
  assert.doesNotMatch(ui.text("assessment-list"), /Blocking constraint/);
  ui.clear();
  assert.equal(ui.text("constraint-assessment-list"), "");
});

test("unknown and legacy assessments never imply compatibility", () => {
  const ui = harness();
  ui.display([{ requirement_uuid: "c", classification: "needs_clarification", explanation: "Willingness is unknown.", evidence: [] }]);
  assert.match(ui.text("constraint-assessment-list"), /Needs clarification/);
  ui.display(null);
  assert.match(ui.text("constraint-assessment-list"), /have not been assessed/);
});

test("missing coverage and unsupported blocker are rejected", () => {
  const ui = harness();
  assert.throws(() => ui.display([]), /cover every/);
  assert.throws(() => ui.display([{requirement_uuid: "c", classification: "blocking", explanation: "Unsupported", evidence: []}]), /invalid practical constraint/);
});
