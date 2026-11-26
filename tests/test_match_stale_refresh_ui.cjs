const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = {
  matchProgress: { hidden: true, classList: { toggle() {} } },
  matchProgressText: { textContent: "" },
  matchRefreshStaleData: { hidden: true, disabled: false, textContent: "刷新数据" },
};
const context = vm.createContext({
  window: {},
  document: { addEventListener() {} },
  AbortController,
  setTimeout() { return 1; },
  clearTimeout() {},
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "web", "match.js"), "utf8"), context);
context.$ = (id) => elements[id];

vm.runInContext('matchProgress("JD 打标签失败：JD 原文与本地快照不符，请刷新数据", true, true)', context);
assert.equal(elements.matchProgress.hidden, false);
assert.equal(elements.matchRefreshStaleData.hidden, false);

vm.runInContext('matchProgress("数据已刷新，已载入 SQL 中的最新 JD。", false)', context);
assert.equal(elements.matchRefreshStaleData.hidden, true);
assert.equal(elements.matchProgressText.textContent, "数据已刷新，已载入 SQL 中的最新 JD。");

assert.equal(vm.runInContext('sameJobRecord({ id: "old", sourceKey: "rec:2" }, { id: "new", sourceKey: "rec:2" })', context), true);
assert.equal(vm.runInContext('sameJobRecord({ id: "old", sourceKey: "rec:2" }, { id: "new", sourceKey: "other:2" })', context), false);
