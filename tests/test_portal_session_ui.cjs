const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, {
    open: false,
    hidden: false,
    classList: { add() {} },
    showModal() { this.open = true; },
    close() { this.open = false; },
  });
  return elements.get(id);
};
const context = vm.createContext({
  location: { pathname: "/alumni/" },
  document: { getElementById: get, addEventListener() {} },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8"), context);

get("feedbackDialog").showModal();
vm.runInContext("showSessionExpired()", context);
assert.equal(get("feedbackDialog").open, false);
assert.equal(get("noticeDialog").open, true);

get("companyDialog").showModal();
vm.runInContext("showAuth()", context);
assert.equal(get("companyDialog").open, false);
assert.equal(get("noticeDialog").open, false);
assert.equal(get("auth").hidden, false);
assert.equal(get("dashboard").hidden, true);
