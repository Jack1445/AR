const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
const script = fs.readFileSync(path.join(__dirname, "..", "web", "accounts.js"), "utf8");
const server = fs.readFileSync(path.join(__dirname, "..", "web_server.py"), "utf8");

assert.match(html, /id="dataCenterBlank"/);
assert.match(html, /data-data-page="accounts"/);
assert.match(html, /data-data-page="recommendations"/);
assert.match(html, /id="accountCreateDialog"/);
assert.match(html, /id="accountDeleteDialog"/);
assert.match(html, /输入完整手机号确认/);
assert.match(script, /X-AR-Accounts/);
assert.match(script, /method: "DELETE"/);
assert.doesNotMatch(script, /AR_密码摘要/);
assert.match(server, /path == "\/api\/accounts"/);
assert.match(server, /def do_DELETE/);
