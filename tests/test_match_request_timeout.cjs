const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

let requestedTimeout;
const context = vm.createContext({
  window: {},
  document: { addEventListener() {} },
  AbortController,
  setTimeout(callback, delay) {
    requestedTimeout = delay;
    queueMicrotask(callback);
    return 1;
  },
  clearTimeout() {},
  fetch(_url, { signal }) {
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    });
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "web", "match.js"), "utf8"), context);
vm.runInContext("matchRequest('/api/match-tag', { kind: 'candidate' })", context).then(
  () => { throw new Error("Expected request timeout"); },
  error => {
    assert.equal(requestedTimeout, 105000);
    assert.match(error.message, /等待超时/);
  },
).catch(error => { console.error(error); process.exitCode = 1; });
