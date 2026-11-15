const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, { hidden: false, open: false, textContent: "", href: "", src: "", showModal() { this.open = true; } });
  return elements.get(id);
};
let fetched = "";
const context = vm.createContext({
  location: { pathname: "/alumni/" },
  document: { getElementById: get, addEventListener() {} },
  fetch: async url => {
    fetched = url;
    return { ok: true, headers: { get: () => "application/pdf" }, arrayBuffer: async () => Uint8Array.from(Buffer.from("%PDF-1.4\nexample")).buffer };
  },
  TextDecoder,
  Blob,
  URL: { createObjectURL: () => "blob:preview", revokeObjectURL() {} },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8"), context);
vm.runInContext("openResume({ id: 'local_test', candidate_name: '候选人' })", context).then(() => {
  assert.equal(fetched, "/api/alumni/recommendation-resume?id=local_test&index=0");
  assert.equal(get("resumeFrame").src, "blob:preview");
  assert.equal(get("resumeFrame").hidden, false);
  assert.equal(get("resumeDownload").href, "/api/alumni/recommendation-resume?id=local_test&index=0&download=1");
  console.log("Resume opens a preview without starting a download");
}).catch(error => { console.error(error); process.exitCode = 1; });
