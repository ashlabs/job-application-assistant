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
      addEventListener() {},
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
        match: { capture_uuid: "job", scoring_rules_version: "documented-alignment-v1", assessments: [{ requirement_uuid: "q", classification: "evidence_missing", explanation: "Unknown", evidence: [] }], constraints },
        score: { scoring_rules_version: "documented-alignment-v1", contributions: [{
          requirement_uuid: "q", importance: "required", classification: "evidence_missing",
          weight: 2, classification_credit: 0, earned_weighted_credit: 0,
          possible_weighted_credit: 2, exclusion_reason: null
        }], percentage: 0, earned_weighted_credit: 0, possible_weighted_credit: 2,
          scored_qualification_count: 1, unspecified_qualification_uuids: [], constraint_uuids: ["c"] }
      };
      vm.runInContext('displayMatch(report, "job")', context);
    },
    displayReport(report, requirements) {
      context.report = report;
      context.requirements = requirements;
      vm.runInContext('currentRequirements = { requirements }; displayMatch(report, "job")', context);
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

function scoringCase() {
  const requirements = [
    {requirement_uuid: "q1", description: "Architecture", kind: "qualification", importance: "required"},
    {requirement_uuid: "q2", description: "Python", kind: "qualification", importance: "preferred"},
    {requirement_uuid: "q3", description: "Communication", kind: "qualification", importance: "unspecified"}
  ];
  const classifications = ["transferable_experience", "strong_match", "strong_match"];
  const report = {
    match: {capture_uuid: "job", scoring_rules_version: "documented-alignment-v1", constraints: [],
      assessments: requirements.map((r, i) => ({requirement_uuid: r.requirement_uuid, classification: classifications[i], explanation: "Documented evidence.", evidence: []}))},
    score: {scoring_rules_version: "documented-alignment-v1", percentage: 66.7,
      earned_weighted_credit: 2, possible_weighted_credit: 3, scored_qualification_count: 2,
      unspecified_qualification_uuids: ["q3"], constraint_uuids: [],
      contributions: requirements.map((r, i) => ({requirement_uuid: r.requirement_uuid,
        importance: r.importance, classification: classifications[i],
        weight: [2, 1, null][i], classification_credit: [.5, 1, 1][i],
        earned_weighted_credit: [1, 1, 0][i], possible_weighted_credit: [2, 1, 0][i],
        exclusion_reason: i === 2 ? "unspecified_importance" : null}))}
  };
  return {report, requirements};
}

test("each qualification shows earned credit, exclusions, and the current rule version", () => {
  const ui = harness();
  const {report, requirements} = scoringCase();
  ui.displayReport(report, requirements);
  assert.match(ui.text("assessment-list"), /weight 2 × classification credit 0.5 = 1 of 2 weighted credits/);
  assert.match(ui.text("assessment-list"), /weight 1 × classification credit 1 = 1 of 1 weighted credits/);
  assert.match(ui.text("assessment-list"), /excluded — importance is unspecified/);
  assert.match(ui.text("match-rules-version"), /documented-alignment-v1/);
  assert.match(ui.text("match-calculation"), /2 of 3 weighted credits across 2 scored qualifications/);
  ui.clear();
  assert.equal(ui.text("match-rules-version"), "");
});

for (const problem of ["missing", "duplicate", "version", "classification"]) {
  test(`inconsistent scoring detail is rejected: ${problem}`, () => {
    const ui = harness();
    const {report, requirements} = scoringCase();
    if (problem === "missing") report.score.contributions.pop();
    else if (problem === "duplicate") report.score.contributions.push(report.score.contributions[0]);
    else if (problem === "version") report.match.scoring_rules_version = "outdated";
    else report.score.contributions[0].classification = "confirmed_gap";
    assert.throws(() => ui.displayReport(report, requirements), /Scoring details|scoring details|credit details|disagree/);
  });
}
