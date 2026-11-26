const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "web", "match.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "web", "theme.css"), "utf8");
assert.match(source, /assessment\.details/);
assert.match(source, /"匹配依据" : "低分原因"/);
assert.doesNotMatch(source, /assessmentList\("面试建议"/);
assert.doesNotMatch(source, /window\.confirm/);
assert.match(source, /chooseEvaluationReuse/);
assert.match(html, /id="matchEvaluationReuseDialog"/);
assert.match(html, /value="reuse"[^>]*class="match-reuse-primary"[^>]*>.*沿用已有结果/);
assert.match(html, /value="refresh"[^>]*class="match-reuse-secondary"[^>]*>.*重新评估全部/);
assert.match(css, /\.match-reuse-dialog\{inset:0/);
const context = vm.createContext({ window: {}, document: { addEventListener() {} }, AbortController, state: { aiConfig: { max_concurrency: 3 } } });
vm.runInContext(source, context);
const progress = { value: 0 };
context.$ = (id) => id === "matchEvalProgressBar" ? progress : { textContent: "" };
vm.runInContext(`
  renderMatch = () => {};
  beginEvalProgress = () => { matchUI.evalStopRequested = false; };
  updateEvalProgress = (done) => { $("matchEvalProgressBar").value = done; };
  endEvalProgress = () => {};
  matchProgress = () => {};
  readPrompt = () => "prompt";
  candidateRecords = () => [];
`, context);

async function main() {
  vm.runInContext('matchUI.job = { id: "jd", source: "JD" }; matchUI.selected = new Set(["a", "b", "c", "d", "e"]); matchUI.hardFilters = Object.fromEntries(["a", "b", "c", "d", "e"].map((id) => [id, { passed: true }]));', context);
  let active = 0, peak = 0;
  const started = [];
  context.matchRequest = async (_path, payload) => {
    started.push(payload.candidate_id);
    active++;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active--;
    return { stars: 4, cached: false };
  };
  await vm.runInContext("evaluateSelected()", context);
  assert.equal(peak, 3);
  assert.deepEqual(started.sort(), ["a", "b", "c", "d", "e"]);
  assert.equal(progress.value, 5);
  assert.equal(vm.runInContext("matchUI.selected.size", context), 5);

  vm.runInContext('matchUI.selected = new Set(["a", "b", "c", "d", "e"]); matchUI.data.evaluations = {};', context);
  started.length = 0;
  context.matchRequest = (_path, payload, signal) => new Promise((_resolve, reject) => {
    started.push(payload.candidate_id);
    signal.addEventListener("abort", () => reject(Object.assign(new Error("stopped"), { name: "AbortError" })), { once: true });
  });
  const evaluating = vm.runInContext("evaluateSelected()", context);
  vm.runInContext("matchUI.evalStopRequested = true; for (const controller of matchUI.evalAbortControllers) controller.abort();", context);
  await evaluating;
  assert.equal(started.length, 3);
  assert.equal(vm.runInContext("matchUI.selected.size", context), 5);
  assert.equal(vm.runInContext("matchUI.evalAbortControllers.size", context), 0);

  const requests = [];
  context.matchRequest = async (_path, payload) => {
    requests.push(payload);
    return { stars: 4, cached: false };
  };
  vm.runInContext('chooseEvaluationReuse = async () => "reuse";', context);
  vm.runInContext('matchUI.selected = new Set(["a", "b"]); matchUI.data.evaluations = { "jd|a": { stars: 3 } }; matchUI.hardFilters = { a: { passed: true }, b: { passed: true } };', context);
  await vm.runInContext("evaluateSelected()", context);
  assert.deepEqual(requests.map((item) => item.candidate_id), ["b"]);
  assert.equal(requests[0].force, false);

  requests.length = 0;
  vm.runInContext('chooseEvaluationReuse = async () => "refresh";', context);
  vm.runInContext('matchUI.selected = new Set(["a", "b"]); matchUI.data.evaluations = { "jd|a": { stars: 3 } };', context);
  await vm.runInContext("evaluateSelected()", context);
  assert.deepEqual(requests.map((item) => item.candidate_id).sort(), ["a", "b"]);
  assert.equal(requests.every((item) => item.force === true), true);
  console.log("Concurrent evaluation and stop passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
