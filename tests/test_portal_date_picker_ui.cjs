const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8");
const context = vm.createContext({
  location: { pathname: "/candidate/" },
  document: { addEventListener() {} },
});
vm.runInContext(source, context);

assert.equal(vm.runInContext("calendarCells(2026, 10).length", context), 42);
assert.equal(vm.runInContext("dateInputValue(2026, 10, 3)", context), "2026-11-03");
assert.equal(vm.runInContext("calendarCells(2026, 10)[0].day", context), 26);
assert.equal(vm.runInContext("calendarCells(2026, 10)[0].month", context), 9);
assert.match(source, /input\.addEventListener\("click", \(\) => openTalentDatePicker/);
assert.match(source, /input\.addEventListener\("keydown"/);
assert.match(source, /function enhanceTalentDateInput/);
assert.match(source, /enhanceTalentDateInput\(\$\("jobLatestArrivalDate"\), "最晚到岗日期"\)/);
assert.match(source, /input\.type = "text"/);
assert.match(source, /input\.readOnly = true/);
