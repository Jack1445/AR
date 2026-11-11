const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "web", "match.js"), "utf8");
const context = vm.createContext({ window: {}, document: { addEventListener() {} } });
vm.runInContext(source, context);
const runBoundedQueue = vm.runInContext("runBoundedQueue", context);

async function main() {
  let active = 0, peak = 0;
  const completed = [];
  await runBoundedQueue([0, 1, 2, 3, 4, 5], 3, () => false, async (item) => {
    active++;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, item === 0 ? 15 : 2));
    completed.push(item);
    active--;
  });
  assert.equal(peak, 3);
  assert.deepEqual(completed.sort((a, b) => a - b), [0, 1, 2, 3, 4, 5]);

  let stopped = false;
  const started = [];
  await runBoundedQueue([0, 1, 2, 3], 2, () => stopped, async (item) => {
    started.push(item);
    if (item === 1) stopped = true;
    await Promise.resolve();
  });
  assert.deepEqual(started, [0, 1]);
  console.log("Bounded tagging queue passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
