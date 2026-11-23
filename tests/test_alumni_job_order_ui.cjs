const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8");
const saved = new Map();
const context = vm.createContext({
  location: { pathname: "/alumni/" },
  document: { addEventListener() {} },
  localStorage: {
    getItem(key) { return saved.has(key) ? saved.get(key) : null; },
    setItem(key, value) { saved.set(key, String(value)); },
  },
});
vm.runInContext(source, context);
vm.runInContext('data.me = { id: "alumni-1", phone: "13800138000" };', context);
const ordered = JSON.parse(vm.runInContext('JSON.stringify(sortJobsByOrder([{id:"job-a"},{id:"job-new"},{id:"job-b"}], ["job-b", "job-a"]).map(job => job.id))', context));
assert.deepEqual(ordered, ["job-b", "job-a", "job-new"]);
assert.equal(vm.runInContext('jobOrderStorageKey()', context), "talent.pipeline.jobs.alumni-1.v1");
assert.match(source, /request\("job-order", \{ job_ids: ids \}\)/);
assert.doesNotMatch(source, /localStorage\.setItem\(jobOrderStorageKey\(\)/);

