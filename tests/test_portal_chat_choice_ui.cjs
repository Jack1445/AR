const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = vm.createContext({
  location: { pathname: "/candidate/" },
  document: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "portal", "portal.js"), "utf8"), context);

const fields = [
  { name: "姓名", type: 1, required: true },
  { name: "简历", type: 17, required: true },
  { name: "意向出勤方式", type: 3, options: ["线上", "线下"], required: true },
  { name: "意向base地（eg.北京,上海）", type: 1, required: true },
];
context.testProfile = { schema: fields, values: { 姓名: "测试用户", "意向base地（eg.北京,上海）": "北京" } };
vm.runInContext("data.me = testProfile", context);
assert.equal(vm.runInContext("initialChatMessages({ schema: testProfile.schema, values: {} }).length", context), 1);
assert.match(vm.runInContext("initialChatMessages({ schema: testProfile.schema, values: {} })[0]", context), /怎么称呼/);
assert.equal(vm.runInContext("initialChatMessages(testProfile).length", context), 1);
assert.match(vm.runInContext("initialChatMessages(testProfile)[0]", context), /逐题点选/);
assert.equal(vm.runInContext("nextChatChoiceField()?.name", context), "意向出勤方式");
vm.runInContext("data.me.values['意向出勤方式'] = '线上'", context);
assert.equal(vm.runInContext("nextChatChoiceField()", context), null);
assert.match(vm.runInContext("textFollowupMessages(testProfile).join(' ')", context), /上传简历/);
vm.runInContext("data.me.values['简历'] = [{ name: 'resume.pdf' }]", context);
assert.equal(vm.runInContext("initialChatMessages(testProfile).length", context), 2);
assert.equal(vm.runInContext("textFollowupMessages(testProfile).length", context), 2);
assert.match(vm.runInContext("initialChatMessages(testProfile)[1]", context), /自荐信.*最心仪的校友企业.*具体岗位或方向/);
vm.runInContext("delete data.me.values['简历']", context);

vm.runInContext("delete data.me.values['意向出勤方式']; request = async (_path, body) => ({ ...data.me, values: { ...data.me.values, ...body.fields } }); renderChat = () => {}; chatStatus = () => {}", context);
vm.runInContext("saveChatChoice(data.me.schema.find(field => field.name === '意向出勤方式'), '线上', { disabled: false })", context).then(() => {
  assert.match(vm.runInContext("data.chatMessages.filter(item => item.role === 'assistant').map(item => item.content).join(' ')", context), /上传简历/);
}).catch(error => { console.error(error); process.exitCode = 1; });
