const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: "", hidden: false, checked: false, disabled: false, textContent: "",
    classList: { toggle() {} }, replaceChildren() {},
  });
  return elements.get(id);
}
const saved = new Map();
const oldServerResponse = { base_url: "https://example.com/v1", model: "mock", models: ["mock"], has_key: true };
const context = vm.createContext({
  oldServerResponse,
  document: { getElementById: element, addEventListener() {} },
  localStorage: { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) },
  Option: class { constructor(label, value) { this.label = label; this.value = value; } },
  fetch: async () => ({ ok: true, json: async () => oldServerResponse }),
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8"), context);

async function main() {
  element("aiBaseUrl").value = oldServerResponse.base_url;
  element("aiModelSelect").value = "mock";
  element("aiManualModel").hidden = true;
  element("aiTagConcurrency").value = "10";
  assert.equal(await vm.runInContext("saveAiConfig()", context), true);
  assert.equal(saved.get("ar-tag-concurrency"), "10");
  assert.equal(Number(element("aiTagConcurrency").value), 10);
  assert.equal(vm.runInContext("state.aiConfig.max_concurrency", context), 10);
  vm.runInContext("showAiConfig(oldServerResponse)", context);
  assert.equal(Number(element("aiTagConcurrency").value), 10);
  console.log("Old-server concurrency setting passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
