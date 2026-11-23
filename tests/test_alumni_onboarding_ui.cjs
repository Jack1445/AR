const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = vm.createContext({
  location: { pathname: "/alumni/" },
  document: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8"), context);

assert.equal(vm.runInContext('alumniOnboardingStep({company:"", contact_name:"", contact_role:""}, [])', context), "company");
assert.equal(vm.runInContext('alumniOnboardingStep({company:"ACME", contact_name:"张三", contact_role:"HR"}, [])', context), "job");
assert.equal(vm.runInContext('alumniOnboardingStep({company:"ACME", contact_name:"张三", contact_role:"HR"}, [{id:"jd"}])', context), "");

const source = fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8");
assert.match(source, /openCompanyEditor\(true\)/);
assert.match(source, /openJobEditor\(\)/);
assert.match(source, /contact_name:\s*contactName/);
assert.match(source, /contact_role:\s*contactRole/);
