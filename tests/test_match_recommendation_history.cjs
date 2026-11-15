const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "web", "match.js"), "utf8");
const context = vm.createContext({ window: {}, document: { addEventListener() {} } });
vm.runInContext(source, context);
vm.runInContext(`
  matchUI.job = { id: "recJob:2:new", sourceKey: "recJob:2" };
  matchUI.data.evaluations["recJob:2:new|recCandidate"] = { stars: 4 };
  matchUI.selected.add("recCandidate");
  matchUI.recommendations = [{ job_id: "recJob:2:old", candidate_id: "recCandidate", status: "待反馈", updated_at: "2026-11-15" }];
`, context);
assert.equal(vm.runInContext("recommendationHistory('recCandidate').length", context), 1);
assert.equal(vm.runInContext("recommendationStatus(recommendationHistory('recCandidate'))", context), "尚未反馈");
assert.equal(vm.runInContext("selectedForRecommendation().length", context), 1);
vm.runInContext("matchUI.recommendations[0].status = '不感兴趣'", context);
assert.equal(vm.runInContext("recommendationStatus(recommendationHistory('recCandidate'))", context), "不感兴趣");
assert.equal(vm.runInContext("selectedForRecommendation().length", context), 0);
console.log("Recommendation history selection passed");
