const role = location.pathname.startsWith("/alumni/") ? "alumni" : "candidate";
const api = `/api/${role}`;
const $ = id => document.getElementById(id);
const data = { me: null, jobs: [], recommendations: [], registering: false, manualMode: false, analysisResult: null, chatMessages: [], chatFields: {}, chatBusy: false, chatThinking: false, chatScrollTarget: null, completionAnnounced: false, sessionExpired: false, portalVersionChecked: false, companyPrompted: false, jobPrompted: false, companyOnboarding: false, resumeObjectUrl: null, resumeRequestId: 0 };
const baseFieldName = "意向base地（eg.北京,上海）";
const baseOtherFieldName = "意向base地（可多选）-其他-补充内容";
const requiredPortalRevision = 35;

function node(tag, className = "", value = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  return element;
}
function message(value, ok = false, auth = false) {
  const target = $(auth ? "authMessage" : "dashboardMessage");
  target.textContent = value;
  target.classList.toggle("ok", ok);
}
function saveNotice(value, ok, successTitle = "保存成功") {
  if (data.sessionExpired) return;
  $("noticeTitle").textContent = ok ? successTitle : "保存失败";
  $("noticeText").textContent = value;
  $("noticeText").hidden = !value;
  $("noticeIcon").textContent = ok ? "✓" : "!";
  $("noticeDialog").classList.toggle("error", !ok);
  if (!$("noticeDialog").open) $("noticeDialog").showModal();
}
function closeDashboardDialogs() {
  for (const id of ["feedbackDialog", "companyDialog", "jobDialog", "resumeDialog"]) {
    const dialog = $(id);
    if (dialog?.open) dialog.close();
  }
}
function showSessionExpired() {
  if (data.sessionExpired) return;
  data.sessionExpired = true;
  closeDashboardDialogs();
  $("noticeTitle").textContent = "登录已过期";
  $("noticeText").textContent = "请重新登录后继续操作。";
  $("noticeText").hidden = false;
  $("noticeIcon").textContent = "!";
  $("noticeDialog").classList.add("error");
  if (!$("noticeDialog").open) $("noticeDialog").showModal();
}
async function request(path, body = null) {
  const options = body === null ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json", "X-AR-Portal": "1" }, body: JSON.stringify(body) };
  const response = await fetch(`${api}/${path}`, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && data.me && path !== "logout") showSessionExpired();
    throw new Error(result.error || `HTTP ${response.status}`);
  }
  return result;
}
function setAuthMode(registering) {
  data.registering = registering;
  $("loginTab").classList.toggle("active", !registering);
  $("registerTab").classList.toggle("active", registering);
  $("formTitle").textContent = registering ? "创建账户" : "欢迎回来";
  $("authSubmit").querySelector("span").textContent = registering ? "注册并进入" : "登录";
  $("password").autocomplete = registering ? "new-password" : "current-password";
  message("", false, true);
}
function showAuth() {
  closeDashboardDialogs();
  if ($("noticeDialog").open) $("noticeDialog").close();
  data.me = null;
  data.companyPrompted = false;
  data.jobPrompted = false;
  data.companyOnboarding = false;
  data.manualMode = false;
  data.analysisResult = null;
  data.chatMessages = [];
  data.chatFields = {};
  data.completionAnnounced = false;
  data.chatThinking = false;
  data.chatScrollTarget = null;
  $("auth").hidden = false;
  $("dashboard").hidden = true;
  $("logout").hidden = true;
}
function displayDate(value) {
  if (!value) return "";
  const date = new Date(Number(value));
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}
const talentCalendar = { dialog: null, input: null, view: null, title: null, grid: null };
function calendarCells(year, month) {
  const first = new Date(year, month, 1, 12);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - mondayOffset, 12);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return { year: date.getFullYear(), month: date.getMonth(), day: date.getDate(), current: date.getMonth() === month };
  });
}
function dateInputValue(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}
function parseDateInput(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12) : null;
}
function commitCalendarDate(year, month, day) {
  const input = talentCalendar.input;
  if (!input) return;
  input.value = dateInputValue(year, month, day);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  updateCandidateRequiredStates();
  talentCalendar.dialog.close();
  input.focus();
}
function renderTalentCalendar() {
  const view = talentCalendar.view;
  const selected = parseDateInput(talentCalendar.input?.value);
  const today = new Date();
  talentCalendar.title.textContent = `${view.getFullYear()}年 ${view.getMonth() + 1}月`;
  talentCalendar.grid.replaceChildren();
  for (const item of calendarCells(view.getFullYear(), view.getMonth())) {
    const button = node("button", `calendar-day${item.current ? "" : " outside"}`, String(item.day));
    button.type = "button";
    button.setAttribute("aria-label", `${item.year}年${item.month + 1}月${item.day}日`);
    if (today.getFullYear() === item.year && today.getMonth() === item.month && today.getDate() === item.day) button.classList.add("today");
    if (selected && selected.getFullYear() === item.year && selected.getMonth() === item.month && selected.getDate() === item.day) button.classList.add("selected");
    button.addEventListener("click", () => commitCalendarDate(item.year, item.month, item.day));
    talentCalendar.grid.append(button);
  }
}
function ensureTalentCalendar() {
  if (talentCalendar.dialog) return;
  const dialog = node("dialog", "talent-calendar-dialog");
  const card = node("div", "talent-calendar-card");
  const heading = node("div", "talent-calendar-heading");
  const headingCopy = node("div");
  headingCopy.append(node("span", "talent-calendar-kicker", "SELECT DATE"), node("strong", "talent-calendar-label", "选择日期"));
  const close = node("button", "talent-calendar-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭日期选择器");
  close.addEventListener("click", () => dialog.close());
  heading.append(headingCopy, close);
  const nav = node("div", "talent-calendar-nav");
  const previous = node("button", "calendar-nav-button", "←");
  const title = node("strong", "calendar-month-title");
  const next = node("button", "calendar-nav-button", "→");
  for (const button of [previous, next]) button.type = "button";
  previous.setAttribute("aria-label", "上个月");
  next.setAttribute("aria-label", "下个月");
  previous.addEventListener("click", () => { talentCalendar.view.setMonth(talentCalendar.view.getMonth() - 1); renderTalentCalendar(); });
  next.addEventListener("click", () => { talentCalendar.view.setMonth(talentCalendar.view.getMonth() + 1); renderTalentCalendar(); });
  nav.append(previous, title, next);
  const weekdays = node("div", "calendar-weekdays");
  for (const day of ["一", "二", "三", "四", "五", "六", "日"]) weekdays.append(node("span", "", day));
  const grid = node("div", "calendar-grid");
  const actions = node("div", "talent-calendar-actions");
  const clear = node("button", "calendar-text-button", "清除");
  const today = node("button", "calendar-today-button", "选择今天");
  clear.type = today.type = "button";
  clear.addEventListener("click", () => {
    talentCalendar.input.value = "";
    talentCalendar.input.dispatchEvent(new Event("input", { bubbles: true }));
    updateCandidateRequiredStates();
    dialog.close();
    talentCalendar.input.focus();
  });
  today.addEventListener("click", () => { const now = new Date(); commitCalendarDate(now.getFullYear(), now.getMonth(), now.getDate()); });
  actions.append(clear, today);
  card.append(heading, nav, weekdays, grid, actions);
  dialog.append(card);
  dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
  document.body.append(dialog);
  Object.assign(talentCalendar, { dialog, title, grid });
}
function openTalentDatePicker(input, fieldName) {
  if (input.disabled) return;
  ensureTalentCalendar();
  talentCalendar.input = input;
  const selected = parseDateInput(input.value) || new Date();
  talentCalendar.view = new Date(selected.getFullYear(), selected.getMonth(), 1, 12);
  talentCalendar.dialog.querySelector(".talent-calendar-label").textContent = fieldName || "选择日期";
  renderTalentCalendar();
  if (!talentCalendar.dialog.open) talentCalendar.dialog.showModal();
}
function enhanceTalentDateInput(input, fieldName) {
  if (!input || input.dataset.talentDateBound === "true") return;
  input.dataset.talentDateBound = "true";
  input.type = "text";
  input.readOnly = true;
  input.placeholder = "选择日期";
  input.classList.add("talent-date-input");
  input.setAttribute("aria-haspopup", "dialog");
  const shell = node("div", "talent-date-shell");
  const icon = node("span", "talent-date-icon", "");
  icon.setAttribute("aria-hidden", "true");
  input.parentNode.insertBefore(shell, input);
  shell.append(input, icon);
  input.addEventListener("click", () => openTalentDatePicker(input, fieldName));
  input.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openTalentDatePicker(input, fieldName);
    }
  });
}
function fieldQuestion(field) {
  if (field.type === 17) return field.name === "简历" ? "方便把简历上传一下吗？点击右侧的「上传简历」就可以。" : `方便上传${field.name}吗？`;
  if ((field.type === 3 || field.type === 4) && field.options?.length) {
    const intro = { [baseFieldName]: "你希望在哪里工作？", "意向出勤方式": "你希望怎么出勤？", "当前求职类别（多选）": "你现在主要考虑哪类机会？", "意向岗位": "你更想做哪类岗位？", "每周到岗天数": "你每周可以到岗几天？", "是否同意奇绩被投企业与你直接取得联系？": "你是否同意被投企业直接联系你？" }[field.name] || `关于${field.name}，你倾向于哪种选择？`;
    return `${intro}可以${field.type === 4 ? "选多个" : "选择"}：${field.options.map(option => `「${option}」`).join("、")}。`;
  }
  if (field.type === 5) return field.name === "最早到岗时间" ? "你最早什么时候可以到岗？告诉我具体日期就行，例如 2026-11-24。" : `${field.name}是哪一天？例如 2026-11-24。`;
  return { "姓名": "我该怎么称呼你？", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名": "你是从哪里看到这条招聘信息的？如果是朋友推荐，也可以告诉我推荐人姓名。" }[field.name] || `关于${field.name}，方便告诉我具体内容吗？`;
}
function groupedQuestions(fields) {
  const parts = [];
  let current = [];
  for (const [index, field] of fields.entries()) {
    const question = `${index + 1}. ${fieldQuestion(field)}`;
    if (current.length && (current.length === 2 || current.join("\n").length + question.length > 260)) {
      parts.push(current.join("\n"));
      current = [];
    }
    current.push(question);
  }
  if (current.length) parts.push(current.join("\n"));
  return parts;
}
function missingOpenFields(me) {
  const filled = value => Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
  const order = ["简历", "最早到岗时间", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名"];
  return (me.schema || []).filter(field => field.required && (!(field.type === 3 || field.type === 4) || !field.options?.length) && !filled(me.values?.[field.name]))
    .sort((a, b) => (order.indexOf(a.name) < 0 ? order.length : order.indexOf(a.name)) - (order.indexOf(b.name) < 0 ? order.length : order.indexOf(b.name)));
}
const optionalProfileSuggestion = "也推荐补充自荐信、最心仪的校友企业，以及你希望在被投企业从事的具体岗位或方向，让校友更了解你。";
function requiredProfileComplete(me) {
  const filled = value => Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
  return (me.schema || []).every(field => !field.required || filled(me.values?.[field.name]));
}
function completionMessages(initial = false) {
  return [initial ? "你好！资料已经填好了，请在右侧核对，确认无误后提交。" : "资料已收集齐了，请在右侧核对，确认无误后提交。", optionalProfileSuggestion];
}
function announceCompletion() {
  if (data.completionAnnounced || !requiredProfileComplete(data.me)) return;
  data.chatScrollTarget = data.chatMessages.length;
  data.chatMessages.push(...completionMessages().map(content => ({ role: "assistant", content })));
  data.completionAnnounced = true;
}
function textFollowupMessages(me, intro = "选择题完成啦！接下来这些信息可以一起告诉我。") {
  const fields = missingOpenFields(me);
  return fields.length ? [intro, ...groupedQuestions(fields)] : completionMessages();
}
function initialChatMessages(me) {
  const filled = value => Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
  const missing = (me.schema || []).filter(field => field.required && !filled(me.values?.[field.name]));
  if (missing.some(field => field.name === "姓名")) return ["你好！欢迎来到 AR。先认识一下，我该怎么称呼你？"];
  if (!missing.length) return completionMessages(true);
  const order = ["简历", baseFieldName, "意向出勤方式", "当前求职类别（多选）", "意向岗位", "最早到岗时间", "每周到岗天数", "是否同意奇绩被投企业与你直接取得联系？", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名"];
  missing.sort((a, b) => (order.indexOf(a.name) < 0 ? order.length : order.indexOf(a.name)) - (order.indexOf(b.name) < 0 ? order.length : order.indexOf(b.name)));
  if (missing.some(field => (field.type === 3 || field.type === 4) && field.options?.length)) return ["你好！我们先做几道选择题，请在下方逐题点选。"];
  return textFollowupMessages(me, "你好！我们接着完善资料。下面这些信息可以一起告诉我。");
}
function renderCandidateForm(me) {
  const target = $("candidateFields");
  target.replaceChildren();
  const topFields = ["姓名", "手机号/微信号", "简历", "自荐信"];
  const order = [baseFieldName, "意向出勤方式", "当前求职类别（多选）", "意向岗位", "最早到岗时间", "每周到岗天数", "是否同意奇绩被投企业与你直接取得联系？", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名"];
  const rank = name => { const index = order.indexOf(name); return index < 0 ? order.length : index; };
  const group = field => topFields.includes(field.name) ? 0 : field.required ? 1 : 2;
  const schema = [...(me.schema || [])].sort((a, b) => group(a) - group(b) || (group(a) === 0 ? topFields.indexOf(a.name) - topFields.indexOf(b.name) : group(a) === 1 ? rank(a.name) - rank(b.name) : 0));
  let currentGroup = null;
  for (const field of schema) {
    if (currentGroup !== group(field)) {
      currentGroup = group(field);
      target.append(node("h3", "candidate-form-divider", ["基本资料", "其他必填资料", "补充资料 · 选填"][currentGroup]));
    }
    const current = me.values?.[field.name];
    const wrapper = node("div", "candidate-field");
    wrapper.dataset.required = field.required ? "true" : "false";
    if (currentGroup !== 0) wrapper.classList.add("candidate-field-wide");
    wrapper.dataset.field = field.name;
    const label = node("label", "field-title", field.name);
    if (field.required) {
      const mark = node("span", "required-mark", "*");
      mark.title = "必填";
      mark.setAttribute("aria-label", "必填");
      label.append(mark);
    }
    wrapper.append(label);
    if (field.name === "自荐信") wrapper.append(node("p", "field-note", "鼓励撰写，会让更多校友看到你！"));
    if (field.type === 17) {
      const row = node("div", "file-row");
      const input = node("input");
      input.type = "file";
      input.accept = ".pdf,.docx,.txt,.png,.jpg,.jpeg";
      input.dataset.field = field.name;
      input.id = `file-${(me.schema || []).indexOf(field)}`;
      input.hidden = true;
      const picker = node("label", "file-picker", `上传${field.name}`);
      picker.htmlFor = input.id;
      const selected = node("span", "file-hint", "PDF、DOCX、TXT、图片 · 最大 8 MB");
      input.addEventListener("change", () => { selected.textContent = input.files[0]?.name || "PDF、DOCX、TXT、图片 · 最大 8 MB"; });
      row.append(picker, input, selected);
      const links = node("div", "resume-links");
      const renderLinks = files => {
        links.replaceChildren();
        (Array.isArray(files) ? files : []).forEach((file, index) => {
          const item = node("div", "uploaded-file");
          const link = node("a", "", `查看 ${file.name || field.name} ↗`);
          link.href = `${api}/resume?field=${encodeURIComponent(field.name)}&index=${index}`;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          const remove = node("button", "remove-file", "×");
          remove.type = "button";
          remove.title = `删除 ${file.name || field.name}`;
          remove.setAttribute("aria-label", remove.title);
          remove.addEventListener("click", async () => {
            remove.disabled = true;
            try {
              const updated = await request("remove-attachment", { field: field.name, index });
              data.me = updated;
              renderLinks(updated.values?.[field.name]);
              message("附件已删除", true);
            } catch (error) { saveNotice(error.message, false); remove.disabled = false; }
          });
          item.append(link, remove);
          links.append(item);
        });
      };
      renderLinks(current);
      wrapper.append(row, links);
    } else if (field.type === 4) {
      const options = node("div", "choice-grid");
      const selected = Array.isArray(current) ? current : [];
      for (const option of field.options || []) {
        const choice = node("label", "choice");
        const input = node("input");
        input.type = "checkbox";
        input.value = option;
        input.checked = selected.includes(option);
        choice.append(input, node("span", "", option.trim()));
        if (field.name === baseFieldName) input.addEventListener("change", updateBaseOtherVisibility);
        options.append(choice);
      }
      wrapper.append(options);
    } else if (field.type === 3) {
      const select = node("select");
      select.append(new Option("请选择", ""));
      for (const option of field.options || []) select.append(new Option(option.trim(), option));
      select.value = typeof current === "string" ? current : "";
      wrapper.append(select);
    } else if (field.type === 5) {
      const input = node("input");
      input.type = "text";
      input.value = displayDate(current);
      input.placeholder = "选择日期";
      input.readOnly = true;
      input.disabled = field.readonly;
      input.className = "talent-date-input";
      input.setAttribute("aria-haspopup", "dialog");
      input.addEventListener("click", () => openTalentDatePicker(input, field.name));
      input.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openTalentDatePicker(input, field.name); }
      });
      const shell = node("div", "talent-date-shell");
      const icon = node("span", "talent-date-icon", "");
      icon.setAttribute("aria-hidden", "true");
      shell.append(input, icon);
      wrapper.append(shell);
    } else {
      const text = typeof current === "string" ? current : "";
      const input = text.length > 180 || /原因|描述|介绍/.test(field.name) ? node("textarea") : node("input");
      if (input.tagName === "TEXTAREA") input.rows = 2;
      else input.type = "text";
      input.maxLength = field.name === "姓名" ? 80 : 12000;
      input.value = field.name === "手机号/微信号" ? me.phone : text;
      input.readOnly = field.readonly;
      if (field.readonly) input.classList.add("readonly-field");
      wrapper.append(input);
    }
    target.append(wrapper);
  }
  updateBaseOtherVisibility();
  updateCandidateRequiredStates();
}
function updateBaseOtherVisibility() {
  const entries = [...$("candidateFields").querySelectorAll(".candidate-field")];
  const base = entries.find(item => item.dataset.field === baseFieldName);
  const other = entries.find(item => item.dataset.field === baseOtherFieldName);
  if (!base || !other) return;
  const selected = [...base.querySelectorAll("input:checked")].some(input => input.value.trim() === "其他");
  other.hidden = !selected;
  if (!selected) other.querySelector("input,textarea").value = "";
}
function collectCandidateFields() {
  const fields = {};
  const wrappers = new Map([...$("candidateFields").querySelectorAll(".candidate-field")].map(item => [item.dataset.field, item]));
  for (const field of data.me.schema || []) {
    if (field.readonly || field.type === 17) continue;
    const wrapper = wrappers.get(field.name);
    if (field.type === 4) fields[field.name] = [...wrapper.querySelectorAll("input:checked")].map(input => input.value);
    else if (field.type === 5) {
      const value = wrapper.querySelector("input").value;
      fields[field.name] = value ? new Date(`${value}T00:00:00+08:00`).getTime() : null;
    } else fields[field.name] = wrapper.querySelector("input,textarea,select").value;
  }
  return fields;
}
function candidateFieldHasValue(field, wrapper) {
  if (field.type === 17) return (Array.isArray(data.me?.values?.[field.name]) && data.me.values[field.name].length > 0) || Boolean(wrapper?.querySelector('input[type="file"]')?.files?.length);
  if (!wrapper || wrapper.hidden) return field.name === baseOtherFieldName;
  if (field.type === 4) return wrapper.querySelectorAll("input:checked").length > 0;
  const control = wrapper.querySelector("input,textarea,select");
  return Boolean(control?.value?.trim());
}
function updateCandidateRequiredStates() {
  const target = $("candidateFields");
  if (!target || !data.me?.schema) return;
  let missing = 0;
  for (const field of data.me.schema) {
    const wrapper = [...target.querySelectorAll(".candidate-field")].find(item => item.dataset.field === field.name);
    if (!wrapper || !field.required || field.readonly) continue;
    const empty = !candidateFieldHasValue(field, wrapper);
    wrapper.classList.toggle("required-missing", empty);
    wrapper.setAttribute("aria-invalid", empty ? "true" : "false");
    if (empty) missing++;
  }
  const hint = $("requiredHint");
  if (hint) {
    hint.textContent = missing ? `还有 ${missing} 项必填信息需要补充` : "必填信息已完整，可以保存";
    hint.classList.toggle("complete", missing === 0);
  }
}
function focusCandidateField(name) {
  const wrapper = [...$("candidateFields").querySelectorAll(".candidate-field")].find(item => item.dataset.field === name);
  if (!wrapper) return;
  wrapper.scrollIntoView({ behavior: "smooth", block: "center" });
  wrapper.animate([{ transform: "translateX(0)" }, { transform: "translateX(-5px)" }, { transform: "translateX(5px)" }, { transform: "translateX(0)" }], { duration: 320 });
  wrapper.querySelector("input,textarea,select,label")?.focus();
}
function alumniOnboardingStep(me, jobs) {
  if (!me?.company || !me?.contact_name || !me?.contact_role) return "company";
  return Array.isArray(jobs) && jobs.length ? "" : "job";
}
function openCompanyEditor(onboarding = false) {
  data.companyOnboarding = onboarding;
  $("companyName").value = data.me?.company || "";
  $("companyContactName").value = data.me?.contact_name || "";
  $("companyContactRole").value = data.me?.contact_role || "";
  $("companySaveStatus").textContent = "";
  $("companyDialogClose").hidden = onboarding;
  $("companyDialogCancel").hidden = onboarding;
  $("companyDialogTitle").textContent = onboarding ? "先完善企业信息" : "企业信息";
  if (!$("companyDialog").open) $("companyDialog").showModal();
  $("companyName").focus();
}
function openJobEditor() {
  clearJobForm();
  if (!$("jobDialog").open) $("jobDialog").showModal();
  updateJobRequiredStates();
  $("jobTitle").focus();
}
async function showDashboard(me) {
  data.me = me;
  $("auth").hidden = true;
  $("dashboard").hidden = false;
  $("logout").hidden = false;
  $("accountPhone").textContent = me.phone;
  $("accountPhone").hidden = role === "alumni";
  const useUpload = role === "candidate" && !me.submitted && !data.manualMode;
  $("candidateUpload").hidden = !useUpload;
  $("candidateChat").hidden = true;
  $("candidateDashboard").hidden = role !== "candidate" || useUpload;
  $("alumniDashboard").hidden = role !== "alumni";
  $("dashboard").classList.toggle("candidate-upload-view", useUpload);
  $("dashboard").classList.toggle("candidate-editor-view", role === "candidate" && !useUpload);
  document.body.classList.toggle("candidate-upload-active", useUpload);
  $("dashboard").querySelector(".page-heading").hidden = role === "candidate";
  if (me.sync?.status === "failed") {
    message("资料已保存在本地；飞书同步暂时失败，系统会自动重试。");
  }
  if (role === "candidate") {
    $("submittedBanner").hidden = !me.submitted;
    $("backToChat").hidden = true;
    renderCandidateForm(me);
    $("candidateDescription").value = me.description || "";
    $("candidateStatus").textContent = me.enabled ? "推荐已开启" : "推荐已停止";
    $("candidateStatus").classList.toggle("off", !me.enabled);
    $("toggleCandidate").classList.toggle("active", me.enabled);
    $("toggleCandidate").setAttribute("aria-checked", me.enabled ? "true" : "false");
    $("toggleCandidate").title = me.enabled ? "点击停止推荐" : "点击开启推荐";
    const analysis = data.analysisResult;
    $("analysisBanner").hidden = !analysis || me.submitted;
    if (analysis && !me.submitted) {
      $("analysisBanner").classList.toggle("warning", Boolean(analysis.error));
      $("analysisSummary").textContent = analysis.error || (analysis.count ? `已自动填写 ${analysis.count} 项信息，请检查结果并补齐橘红色必填项。` : "简历已上传，请补齐橘红色标记的必填内容。");
    }
  } else {
    $("dashboard").querySelector(".page-heading").hidden = false;
    $("companyName").value = me.company || "";
    $("companyContactName").value = me.contact_name || "";
    $("companyContactRole").value = me.contact_role || "";
    $("openJobDialog").disabled = alumniOnboardingStep(me, [{}]) === "company";
    await refreshAlumni();
    const onboarding = alumniOnboardingStep(me, data.jobs);
    if (data.portalVersionChecked && onboarding === "company" && !data.companyPrompted) {
      data.companyPrompted = true;
      openCompanyEditor(true);
    } else if (data.portalVersionChecked && onboarding === "job" && !data.jobPrompted) {
      data.jobPrompted = true;
      openJobEditor();
    }
  }
}
function renderChat() {
  const list = $("chatMessages");
  list.replaceChildren();
  for (const item of data.chatMessages) {
    const bubble = node("div", `chat-bubble ${item.role}`, item.content);
    list.append(bubble);
  }
  if (data.chatThinking) {
    const thinking = node("div", "chat-bubble assistant thinking-bubble");
    thinking.setAttribute("role", "status");
    thinking.setAttribute("aria-label", "AI 正在思考");
    thinking.append(node("span", "", "正在思考"));
    const dots = node("span", "thinking-dots");
    for (let index = 0; index < 3; index++) dots.append(node("i"));
    thinking.append(dots);
    list.append(thinking);
  }
  const choiceField = !data.chatBusy && !data.chatThinking && nextChatChoiceField();
  if (choiceField) list.append(chatChoicePrompt(choiceField));
  if (Number.isInteger(data.chatScrollTarget)) {
    const first = list.children[0];
    const target = list.children[data.chatScrollTarget];
    list.scrollTop = target && first ? Math.max(0, target.offsetTop - first.offsetTop) : 0;
    data.chatScrollTarget = null;
  } else list.scrollTop = list.scrollHeight;
  const collected = $("chatCollected");
  collected.replaceChildren();
  let missing = 0;
  for (const field of data.me?.schema || []) {
    if (field.readonly) continue;
    let value = field.type === 17 ? data.me.values?.[field.name] : data.chatFields[field.name] ?? data.me.values?.[field.name];
    const filled = Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
    if (!filled && field.required) missing++;
    if (field.name === baseOtherFieldName) {
      const bases = data.chatFields[baseFieldName] ?? data.me.values?.[baseFieldName];
      if (!Array.isArray(bases) || !bases.includes("其他")) continue;
    }
    const item = node("div", "chat-field-item");
    const row = node(field.type === 17 ? "div" : "button", `chat-field ${filled ? "filled" : "missing"}`);
    row.append(node("span", "", field.name), node("strong", "", filled ? field.type === 17 ? "已上传" : field.type === 5 ? typeof value === "number" ? displayDate(value) : value : Array.isArray(value) ? value.join("、") : String(value) : "待填写"));
    if (field.type !== 17) {
      row.type = "button";
      row.title = `点击编辑${field.name}`;
      row.setAttribute("aria-label", `编辑${field.name}`);
      row.addEventListener("click", () => openChatEditor(item, field, value));
    }
    item.append(row);
    collected.append(item);
  }
  $("chatConfirm").disabled = missing > 0 || data.chatBusy;
  $("chatResumeName").textContent = data.me?.files?.map(item => item.name).join("、") || "PDF、DOCX、TXT、图片 · 最大 8 MB";
}
function nextChatChoiceFieldFor(me) {
  if (!me?.values?.["姓名"]) return null;
  const order = [baseFieldName, "意向出勤方式", "当前求职类别（多选）", "意向岗位", "每周到岗天数", "是否同意奇绩被投企业与你直接取得联系？"];
  const fields = (me.schema || []).filter(field => field.required && (field.type === 3 || field.type === 4) && field.options?.length);
  fields.sort((a, b) => (order.indexOf(a.name) < 0 ? order.length : order.indexOf(a.name)) - (order.indexOf(b.name) < 0 ? order.length : order.indexOf(b.name)));
  return fields.find(field => {
    const value = data.chatFields[field.name] ?? me.values?.[field.name];
    return Array.isArray(value) ? !value.length : value === null || value === undefined || value === "";
  }) || null;
}
function nextChatChoiceField() { return nextChatChoiceFieldFor(data.me); }
function announceTextQuestions() {
  data.chatScrollTarget = data.chatMessages.length;
  data.chatMessages.push(...textFollowupMessages(data.me).map(content => ({ role: "assistant", content })));
  if (requiredProfileComplete(data.me)) data.completionAnnounced = true;
}
function chatChoicePrompt(field) {
  const card = node("div", "chat-choice-prompt");
  const title = fieldQuestion(field).replace(/可以(?:选多个|选择)：.*$/, "");
  card.append(node("strong", "chat-choice-title", title), node("span", "chat-choice-hint", field.type === 4 ? "可多选" : "选一项即可"));
  const options = node("div", "chat-choice-options");
  for (const option of field.options) {
    if (field.type === 3) {
      const button = node("button", "chat-choice-option", option.trim());
      button.type = "button";
      button.addEventListener("click", () => saveChatChoice(field, option, button));
      options.append(button);
    } else {
      const label = node("label", "chat-choice-option", option.trim());
      const input = node("input");
      input.type = "checkbox";
      input.value = option;
      label.prepend(input);
      options.append(label);
    }
  }
  card.append(options);
  if (field.type === 4) {
    const confirm = node("button", "chat-choice-confirm", "确认选择");
    confirm.type = "button";
    confirm.addEventListener("click", () => {
      const selected = [...options.querySelectorAll("input:checked")].map(input => input.value);
      if (!selected.length) { chatStatus("请至少选择一项", true); return; }
      saveChatChoice(field, selected, confirm);
    });
    card.append(confirm);
  }
  return card;
}
async function saveChatChoice(field, value, button) {
  if (data.chatBusy) return;
  data.chatBusy = true;
  button.disabled = true;
  chatStatus("正在保存选择…");
  try {
    data.me = await request("draft", { fields: { [field.name]: value } });
    data.chatMessages.push({ role: "user", content: Array.isArray(value) ? value.map(item => item.trim()).join("、") : value.trim() });
    if (nextChatChoiceField()) data.chatScrollTarget = data.chatMessages.length - 1;
    else announceTextQuestions();
    chatStatus("已保存");
  } catch (error) { chatStatus(error.message, true); button.disabled = false; }
  finally { data.chatBusy = false; renderChat(); }
}
function openChatEditor(item, field, current) {
  if (item.querySelector(".chat-field-editor")) return;
  const editor = node("div", "chat-field-editor");
  let control;
  if (field.type === 4) {
    control = node("div", "chat-choice-grid");
    for (const option of field.options || []) {
      const label = node("label", "", option);
      const input = node("input"); input.type = "checkbox"; input.value = option;
      input.checked = Array.isArray(current) && current.includes(option);
      label.prepend(input); control.append(label);
    }
  } else if (field.type === 3) {
    control = node("select"); control.append(new Option("请选择", ""));
    for (const option of field.options || []) control.append(new Option(option, option));
    control.value = typeof current === "string" ? current : "";
  } else if (field.type === 5) {
    control = node("input"); control.type = "date";
    control.value = typeof current === "number" ? displayDate(current) : typeof current === "string" ? current : "";
  } else {
    control = node("textarea"); control.rows = 3; control.value = typeof current === "string" ? current : "";
  }
  const actions = node("div", "chat-edit-actions");
  const cancel = node("button", "", "取消"); cancel.type = "button";
  cancel.addEventListener("click", () => editor.remove());
  const save = node("button", "", "保存"); save.type = "button";
  save.addEventListener("click", async () => {
    let value = field.type === 4 ? [...control.querySelectorAll("input:checked")].map(input => input.value) : control.value;
    if (field.type === 5) value = value ? new Date(`${value}T00:00:00+08:00`).getTime() : null;
    save.disabled = true;
    try {
      const wasPendingChoice = (field.type === 3 || field.type === 4) && !!nextChatChoiceField();
      data.me = await request("draft", { fields: { [field.name]: value } });
      delete data.chatFields[field.name];
      if (wasPendingChoice && !nextChatChoiceField()) announceTextQuestions();
      else announceCompletion();
      chatStatus("已保存到飞书"); renderChat();
    } catch (error) { chatStatus(error.message, true); save.disabled = false; }
  });
  actions.append(cancel, save); editor.append(control, actions); item.append(editor);
}
function chatStatus(value, error = false) {
  $("chatStatus").textContent = value;
  $("chatStatus").classList.toggle("ok", !error);
}
function chatFieldsForSubmit() {
  const fields = {};
  for (const field of data.me.schema || []) {
    if (field.readonly || field.type === 17 || !Object.hasOwn(data.chatFields, field.name)) continue;
    let value = data.chatFields[field.name];
    if (field.type === 5 && typeof value === "string" && value) value = new Date(`${value}T00:00:00+08:00`).getTime();
    if (value !== undefined) fields[field.name] = value;
  }
  const bases = fields[baseFieldName] ?? data.me.values?.[baseFieldName];
  if (!Array.isArray(bases) || !bases.some(item => String(item).trim() === "其他")) delete fields[baseOtherFieldName];
  return fields;
}
async function refreshAlumni() {
  if (!data.portalVersionChecked) {
    const healthResponse = await fetch("/health", { cache: "no-store" });
    const health = await healthResponse.json();
    if (!healthResponse.ok || !health.local_recommendations || health.alumni_company_fields !== 2 || health.portal_revision !== requiredPortalRevision || !health.local_primary) {
      saveNotice("校友端仍在运行旧版服务。请关闭旧服务窗口，再运行“打开校友端.cmd”，然后刷新页面。", false);
    } else data.portalVersionChecked = true;
  }
  const [jobs, recommendations] = await Promise.all([request("jobs"), request("recommendations")]);
  data.jobs = await migrateLegacyJobOrder(jobs.items);
  data.recommendations = recommendations.items;
  const visibleRecommendations = data.recommendations.filter(rec => !isBlockedStatus(rec.status));
  const activeJobs = data.jobs.filter(job => job.enabled);
  const activeJobIds = new Set(activeJobs.map(job => job.id));
  const activeRecommendations = visibleRecommendations.filter(rec => activeJobIds.has(rec.job_id));
  if (role === "alumni" && data.me) {
    $("dashboardEyebrow").textContent = `${data.me.company || "企业招聘"} · ${data.me.contact_role || "校友伙伴"}`;
    $("dashboardTitle").textContent = `${data.me.display_name || data.me.contact_name || "你好"}，来一起看看人才`;
    $("dashboardSubtitle").textContent = `${data.jobs.filter(job => job.enabled).length} 个岗位正在招聘，${visibleRecommendations.length} 位候选人等待你查看。`;
  }
  renderAlumniWorkspace();
}
const nextActions = { "待反馈": ["感兴趣", "不感兴趣"], "面试中": ["录用", "未录用"] };
function statusClass(status) {
  return ({ "待反馈": "pending", "面试中": "interview", "录用": "hired", "不感兴趣": "declined", "未录用": "declined" })[status] || "pending";
}
function isBlockedStatus(status) {
  return status === "不感兴趣" || status === "未录用";
}
function resumeUrl(rec, download = false) {
  return `${api}/recommendation-resume?id=${encodeURIComponent(rec.id)}&index=0${download ? "&download=1" : ""}`;
}
async function openResume(rec) {
  const requestId = ++data.resumeRequestId;
  $("resumeDialogTitle").textContent = `${rec.candidate_name || "候选人"}的简历`;
  $("resumeDownload").href = resumeUrl(rec, true);
  $("resumeStatus").textContent = "正在加载简历…";
  $("resumeStatus").hidden = false;
  $("resumeFrame").hidden = true;
  $("resumeDialog").showModal();
  try {
    const response = await fetch(resumeUrl(rec), { cache: "no-store" });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try { detail = (await response.json()).error || detail; } catch {}
      if (response.status === 401) showSessionExpired();
      throw new Error(detail);
    }
    const bytes = await response.arrayBuffer();
    if (!$("resumeDialog").open || requestId !== data.resumeRequestId) return;
    const contentType = response.headers.get("Content-Type") || "";
    const isPdf = new TextDecoder("ascii").decode(bytes.slice(0, 1024)).includes("%PDF-");
    if (contentType.includes("application/pdf") && !isPdf) throw new Error("这份附件不是有效的 PDF，无法在线预览。可点击右上角下载原文件。");
    if (!/^(application\/pdf|image\/(png|jpeg)|text\/plain)/i.test(contentType)) throw new Error("当前文件格式无法在线预览。可点击右上角下载原文件。");
    if (data.resumeObjectUrl) URL.revokeObjectURL(data.resumeObjectUrl);
    data.resumeObjectUrl = URL.createObjectURL(new Blob([bytes], { type: contentType }));
    $("resumeFrame").src = data.resumeObjectUrl;
    $("resumeFrame").hidden = false;
    $("resumeStatus").hidden = true;
  } catch (error) {
    if ($("resumeDialog").open && requestId === data.resumeRequestId) $("resumeStatus").textContent = error.message;
  }
}
function renderRecommendations() {
  const list = $("recommendationsList");
  list.replaceChildren();
  if (!data.recommendations.length) {
    $("recommendationTrash").hidden = true;
    list.append(node("p", "empty", "暂无候选人推荐。"));
    return;
  }
  const groups = new Map(data.jobs.map(job => [job.id, { title: job.title, enabled: job.enabled, items: [] }]));
  const declined = data.recommendations.filter(rec => isBlockedStatus(rec.status));
  const trash = $("recommendationTrash");
  trash.hidden = !declined.length;
  $("trashCount").textContent = `回收站 · ${declined.length}`;
  const trashList = $("trashList");
  trashList.replaceChildren();
  for (const rec of declined) {
    const item = node("div", "trash-item");
    const label = node("span", "", `${rec.candidate_name || "候选人"} · ${rec.job_title || "岗位"}`);
    const status = node("button", "feedback-pill declined feedback-tag", `${rec.status} · 修改`);
    status.type = "button";
    status.addEventListener("click", () => openFeedbackDialog(rec));
    const restore = node("button", "outline", "恢复显示");
    restore.type = "button";
    restore.addEventListener("click", () => saveFeedback(rec, "待反馈", restore));
    item.append(label, status, restore);
    trashList.append(item);
  }
  for (const rec of data.recommendations) {
    if (isBlockedStatus(rec.status)) continue;
    if (!groups.has(rec.job_id)) groups.set(rec.job_id, { title: rec.job_title || "历史岗位", enabled: false, items: [] });
    groups.get(rec.job_id).items.push(rec);
  }
  if (!data.recommendations.some(rec => !isBlockedStatus(rec.status))) list.append(node("p", "empty", "当前没有待查看的候选人推荐。"));
  for (const [jobId, group] of groups) {
    if (!group.items.length) continue;
    const section = node("section", "recommendation-group");
    const groupHead = node("div", "recommendation-group-heading");
    const groupTitle = node("div");
    groupTitle.append(node("h3", "", group.title), node("span", "group-count", `${group.items.length} 位候选人`));
    groupHead.append(groupTitle, node("span", `recruiting-pill ${group.enabled ? "active" : "paused"}`, group.enabled ? "● 招聘中" : "已停止"));
    const cards = node("div", "recommendation-cards");
    for (const rec of group.items) {
    const card = node("article", "item-card");
    const head = node("div", "item-top");
    head.append(node("h3", "", rec.candidate_name || "候选人"), node("span", "stars", "★".repeat(Number(rec.stars) || 0)));
    const meta = node("div", "item-meta");
    if (rec.status === "面试中") {
      const status = node("button", `feedback-pill ${statusClass(rec.status)} feedback-tag`, "面试中");
      status.type = "button";
      status.addEventListener("click", () => openFeedbackDialog(rec));
      meta.append(status);
    } else meta.append(node("span", `feedback-pill ${statusClass(rec.status)}`, rec.status));
    const disclosure = node("details", "candidate-detail");
    disclosure.append(node("summary", "", "查看候选人资料"), node("pre", "", rec.candidate_profile || "暂无资料"));
    const reason = node("details", "candidate-detail reason-detail");
    reason.append(node("summary", "", "查看评估依据"), node("pre", "", rec.reason || "暂无评估依据"));
    const actions = node("div", "item-actions");
    if (rec.resume_count > 0) {
      const view = node("button", "resume-view-button", "查看简历");
      view.type = "button";
      view.addEventListener("click", () => openResume(rec));
      actions.append(view);
    }
    for (const action of nextActions[rec.status] || []) {
      const button = node("button", `feedback-action ${action === "感兴趣" || action === "录用" ? "positive" : "negative"}`, action);
      button.type = "button";
      button.addEventListener("click", () => saveFeedback(rec, action, button));
      actions.append(button);
    }
    card.append(head, meta, reason, disclosure, actions);
    cards.append(card);
    }
    section.append(groupHead, cards);
    list.append(section);
  }
}
function editJob(job) {
  $("jobId").value = job.id;
  $("jobTitle").value = job.title;
  $("jobBody").value = job.body;
  $("jobWorkLocation").value = job.work_location || "";
  $("jobAttendanceMode").value = job.attendance_mode || "";
  $("jobMinDays").value = job.min_days_per_week || "";
  $("jobLatestArrivalDate").value = job.latest_arrival_date || "";
  const categories = new Set(job.job_categories || []);
  for (const input of document.querySelectorAll('input[name="jobCategory"]')) input.checked = categories.has(input.value);
  $("jobEnabled").checked = job.enabled;
  $("jobSubmit").textContent = "保存修改";
  $("cancelJobEdit").hidden = false;
  $("jobDialogTitle").textContent = "编辑 JD";
  $("jobDialog").showModal();
  updateJobRequiredStates();
  $("jobTitle").focus();
}
const alumniCandidateProfileFields = [
  { label: "当前求职类别", aliases: ["当前求职类别（多选）", "当前求职类别"] },
  { label: "意向base地", aliases: ["意向base地（eg.北京,上海）", "意向base地（可多选）", "意向base地"] },
  { label: "意向出勤方式", aliases: ["意向出勤方式"] },
  { label: "意向岗位", aliases: ["意向岗位"] },
  { label: "最早到岗时间", aliases: ["最早到岗时间"], date: true },
  { label: "每周到岗天数", aliases: ["每周到岗天数"] },
  { label: "来源", aliases: ["来源", "你是通过什么渠道了解到的招聘信息？若是经人推荐，可填写推荐人姓名"] },
];
function formatCandidateProfileDate(value) {
  const text = String(value || "").trim();
  if (!text) return "未填写";
  const direct = /^(\d{4})\D+(\d{1,2})\D+(\d{1,2})/.exec(text);
  if (direct) return `${direct[1]}-${direct[2].padStart(2, "0")}-${direct[3].padStart(2, "0")}`;
  let date;
  if (/^\d{10,13}$/.test(text)) {
    const timestamp = Number(text) * (text.length === 10 ? 1000 : 1);
    date = new Date(timestamp);
  } else date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(date)
      .filter(part => part.type !== "literal")
      .map(part => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function selectedCandidateProfile(profile) {
  const lines = String(profile || "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  return alumniCandidateProfileFields.map(field => {
    let value = "";
    for (const alias of field.aliases) {
      const prefix = lines.find(line => line.startsWith(`${alias}：`) || line.startsWith(`${alias}:`));
      if (prefix) {
        value = prefix.slice(alias.length + 1).trim();
        break;
      }
    }
    return { label: field.label, value: field.date ? formatCandidateProfileDate(value) : value || "未填写" };
  });
}
function appendAssessmentContent(host, rec) {
  const assessment = rec.assessment;
  if (!assessment || typeof assessment !== "object" || !assessment.schema_version) {
    host.append(node("p", "", rec.reason || "暂无评估依据"));
    return;
  }
  const summary = node("div", "candidate-assessment-summary");
  const recommendation = Number(rec.stars) >= 4 ? "推荐" : Number(rec.stars) === 3 ? "谨慎推荐" : "不推荐";
  summary.append(node("strong", "", `【${recommendation}】`), node("span", "", assessment.summary || ""));
  host.append(summary);
  const legacy = Number(rec.stars) >= 3 ? assessment.advantages : assessment.risks;
  const items = Array.isArray(assessment.details) ? assessment.details : (Array.isArray(legacy) ? legacy : []);
  if (!items.length) return;
  const section = node("div", "candidate-assessment-block");
  section.append(node("strong", "", Number(rec.stars) >= 3 ? "匹配依据" : "低分原因"));
  const list = node("ul", "");
  for (const item of items) list.append(node("li", "", `简历事实：${item.resume_evidence || ""}\n对应JD：${item.jd_requirement || ""}\n${item.analysis || ""}`));
  section.append(list);
  host.append(section);
}
function pipelineCandidateRow(rec) {
  const row = node("article", "pipeline-candidate-row");
  row.classList.add(`pipeline-row-${statusClass(rec.status)}`);
  const identity = node("div", "pipeline-candidate-identity");
  identity.append(node("strong", "", rec.candidate_name || "候选人"), node("small", "", rec.resume_count > 0 ? "简历已就绪" : "候选人资料"));
  const stars = Math.max(0, Math.min(5, Number(rec.stars) || 0));
  const match = node("div", "pipeline-match");
  match.append(node("span", "pipeline-stars-filled", "★".repeat(stars)), node("span", "pipeline-stars-empty", "★".repeat(5 - stars)));
  match.setAttribute("aria-label", `${stars} 星匹配`);
  match.title = `${stars} 星匹配`;
  const stage = node("div", "pipeline-stage");
  if (["面试中", "录用", "未录用"].includes(rec.status)) {
    const status = node("button", `feedback-pill ${statusClass(rec.status)} feedback-tag`, rec.status);
    status.type = "button";
    status.addEventListener("click", () => openFeedbackDialog(rec));
    stage.append(status);
  } else stage.append(node("span", `feedback-pill ${statusClass(rec.status)}`, rec.status));
  const actions = node("div", "pipeline-row-actions");
  if (rec.resume_count > 0) {
    const view = node("button", "outline", "查看简历");
    view.type = "button";
    view.addEventListener("click", () => openResume(rec));
    actions.append(view);
  }
  for (const action of nextActions[rec.status] || []) {
    const button = node("button", action === "感兴趣" || action === "录用" ? "primary" : "outline", action);
    button.type = "button";
    button.addEventListener("click", () => saveFeedback(rec, action, button));
    actions.append(button);
  }
  const detailToggle = node("button", "pipeline-detail-toggle", "查看详情");
  detailToggle.type = "button";
  detailToggle.setAttribute("aria-expanded", "false");
  const detailGrid = node("div", "pipeline-detail-grid pipeline-detail-panel");
  detailGrid.hidden = true;
  const reason = node("section", "candidate-ai-section");
  reason.append(node("small", "", "AI 评估依据"));
  appendAssessmentContent(reason, rec);
  const profile = node("section", "candidate-profile-section");
  profile.append(node("small", "", "候选人资料"));
  const profileGrid = node("div", "candidate-profile-grid");
  for (const item of selectedCandidateProfile(rec.candidate_profile)) {
    const field = node("div", "candidate-profile-item");
    field.append(node("span", "candidate-profile-label", item.label), node("strong", "candidate-profile-value", item.value));
    profileGrid.append(field);
  }
  profile.append(profileGrid);
  detailGrid.append(profile, reason);
  detailToggle.addEventListener("click", () => {
    const expanded = detailToggle.getAttribute("aria-expanded") === "true";
    detailToggle.setAttribute("aria-expanded", String(!expanded));
    detailToggle.textContent = expanded ? "查看详情" : "收起详情";
    detailGrid.hidden = expanded;
  });
  row.append(detailToggle, identity, match, stage, actions, detailGrid);
  return row;
}
async function setJobEnabled(job, enabled, button) {
  button.disabled = true;
  try {
    await request("job-status", { id: job.id, enabled });
    await refreshAlumni();
    message("");
  } catch (error) {
    message(error.message);
    button.disabled = false;
  }
}
const pipelineColumnDefaults = [15, 39.168573828455195, 14.362990690986752, 9.085019987043971, 22.383415493514082];
const pipelineColumnMinimums = [95, 100, 80, 80, 90];
const pipelineColumnStorageKey = "talent.pipeline.columns.v5";
function validPipelineColumnRatios(value) {
  return Array.isArray(value) && value.length === 5 && value.every(item => Number.isFinite(Number(item)) && Number(item) > 0);
}
function loadPipelineColumnRatios() {
  try {
    const saved = JSON.parse(localStorage.getItem(pipelineColumnStorageKey));
    if (validPipelineColumnRatios(saved)) return saved.map(Number);
  } catch {}
  return [...pipelineColumnDefaults];
}
function applyPipelineColumnRatios(ratios, persist = false) {
  const list = $("recommendationsList");
  if (!list || !validPipelineColumnRatios(ratios)) return;
  ratios.forEach((ratio, index) => list.style.setProperty(`--pipeline-column-${index + 1}`, `${Number(ratio).toFixed(4)}fr`));
  if (persist) {
    try { localStorage.setItem(pipelineColumnStorageKey, JSON.stringify(ratios.map(Number))); } catch {}
  }
}
function pipelineColumnWidths(labels) {
  const template = getComputedStyle(labels).gridTemplateColumns;
  const widths = template.match(/[\d.]+px/g)?.map(value => Number.parseFloat(value)) || [];
  return widths.length === 5 && widths.every(Number.isFinite) ? widths : [];
}
function resizedPipelineColumnRatios(widths, boundary, delta) {
  if (widths.length !== 5 || boundary < 0 || boundary > widths.length - 2) return null;
  const pairWidth = widths[boundary] + widths[boundary + 1];
  const leftWidth = Math.max(
    pipelineColumnMinimums[boundary],
    Math.min(pairWidth - pipelineColumnMinimums[boundary + 1], widths[boundary] + delta),
  );
  const next = [...widths];
  next[boundary] = leftWidth;
  next[boundary + 1] = pairWidth - leftWidth;
  const total = next.reduce((sum, width) => sum + width, 0);
  return next.map(width => width / total * 100);
}
function bindPipelineColumnResizer(handle, labels, boundary) {
  handle.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const initialWidths = pipelineColumnWidths(labels);
    if (!initialWidths.length) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("active");
    document.body.classList.add("pipeline-resizing");
    const startX = event.clientX;
    let latest = null;
    const move = moveEvent => {
      latest = resizedPipelineColumnRatios(initialWidths, boundary, moveEvent.clientX - startX);
      if (latest) applyPipelineColumnRatios(latest);
    };
    const finish = () => {
      handle.classList.remove("active");
      document.body.classList.remove("pipeline-resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      if (latest) applyPipelineColumnRatios(latest, true);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });
  handle.addEventListener("keydown", event => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const ratios = resizedPipelineColumnRatios(pipelineColumnWidths(labels), boundary, event.key === "ArrowLeft" ? -12 : 12);
    if (ratios) applyPipelineColumnRatios(ratios, true);
  });
  handle.addEventListener("dblclick", () => applyPipelineColumnRatios(pipelineColumnDefaults, true));
}
function jobOrderStorageKey() {
  return `talent.pipeline.jobs.${data.me?.id || data.me?.phone || "anonymous"}.v1`;
}
function loadLegacyJobOrder() {
  try {
    const value = JSON.parse(localStorage.getItem(jobOrderStorageKey()));
    return Array.isArray(value) ? value.filter(item => typeof item === "string") : [];
  } catch { return []; }
}
function sortJobsByOrder(jobs, order) {
  const positions = new Map(order.map((id, index) => [id, index]));
  return jobs.map((job, index) => ({ job, index })).sort((left, right) => {
    const leftPosition = positions.has(left.job.id) ? positions.get(left.job.id) : Number.MAX_SAFE_INTEGER;
    const rightPosition = positions.has(right.job.id) ? positions.get(right.job.id) : Number.MAX_SAFE_INTEGER;
    return leftPosition - rightPosition || left.index - right.index;
  }).map(item => item.job);
}
async function migrateLegacyJobOrder(jobs) {
  const legacyOrder = loadLegacyJobOrder();
  if (!legacyOrder.length) return jobs;
  const ordered = sortJobsByOrder(jobs, legacyOrder);
  try {
    await request("job-order", { job_ids: ordered.filter(job => job.enabled).map(job => job.id) });
    localStorage.removeItem(jobOrderStorageKey());
    return ordered;
  } catch { return jobs; }
}
async function saveRenderedJobOrder(list) {
  const ids = [...list.querySelectorAll(":scope > .pipeline-job")].map(section => section.dataset.jobId).filter(Boolean);
  try { await request("job-order", { job_ids: ids }); }
  catch (error) { saveNotice(`岗位顺序保存失败：${error.message}`, false); }
}
function bindJobOrderHandle(handle, section, list) {
  handle.draggable = true;
  handle.addEventListener("dragstart", event => {
    section.classList.add("job-order-dragging");
    list.classList.add("sorting-jobs");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", section.dataset.jobId);
  });
  handle.addEventListener("dragend", () => {
    section.classList.remove("job-order-dragging");
    list.classList.remove("sorting-jobs");
    void saveRenderedJobOrder(list);
  });
  handle.addEventListener("keydown", event => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const sibling = event.key === "ArrowUp" ? section.previousElementSibling : section.nextElementSibling;
    if (!sibling?.classList.contains("pipeline-job")) return;
    if (event.key === "ArrowUp") list.insertBefore(section, sibling);
    else list.insertBefore(sibling, section);
    void saveRenderedJobOrder(list);
    handle.focus();
  });
}
function bindJobOrderDropZone(list) {
  list.ondragover = event => {
    const dragged = list.querySelector(".pipeline-job.job-order-dragging");
    if (!dragged) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const target = event.target.closest(".pipeline-job");
    if (!target || target === dragged) return;
    const before = event.clientY < target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2;
    list.insertBefore(dragged, before ? target : target.nextElementSibling);
  };
  list.ondrop = event => {
    if (!list.querySelector(".pipeline-job.job-order-dragging")) return;
    event.preventDefault();
  };
}
function renderAlumniWorkspace() {
  const list = $("recommendationsList");
  list.replaceChildren();
  applyPipelineColumnRatios(loadPipelineColumnRatios());
  bindJobOrderDropZone(list);
  const activeJobs = data.jobs.filter(job => job.enabled);
  const stoppedJobs = data.jobs.filter(job => !job.enabled);
  const stoppedPanel = $("stoppedJobs");
  const stoppedList = $("stoppedJobsList");
  stoppedPanel.hidden = !stoppedJobs.length;
  $("stoppedJobsCount").textContent = `停止招聘 · ${stoppedJobs.length}`;
  stoppedList.replaceChildren();
  for (const job of stoppedJobs) {
    const item = node("div", "trash-item stopped-job-item");
    const candidateCount = data.recommendations.filter(rec => rec.job_id === job.id && !isBlockedStatus(rec.status)).length;
    const label = node("div", "stopped-job-label");
    label.append(node("strong", "", job.title), node("small", "", `${candidateCount} 位候选人`));
    const actions = node("div", "stopped-job-actions");
    const edit = node("button", "outline", "编辑岗位");
    edit.type = "button";
    edit.addEventListener("click", () => editJob(job));
    const reopen = node("button", "outline", "重新开启");
    reopen.type = "button";
    reopen.addEventListener("click", () => setJobEnabled(job, true, reopen));
    actions.append(edit, reopen);
    item.append(label, actions);
    stoppedList.append(item);
  }
  const declined = data.recommendations.filter(rec => isBlockedStatus(rec.status));
  $("recommendationTrash").hidden = !declined.length;
  $("trashCount").textContent = `已屏蔽 · ${declined.length}`;
  const trashList = $("trashList");
  trashList.replaceChildren();
  for (const rec of declined) {
    const item = node("div", "trash-item");
    const label = node("span", "", `${rec.candidate_name || "候选人"} · ${rec.job_title || "岗位"}`);
    const restore = node("button", "outline", "恢复到岗位");
    restore.type = "button";
    restore.addEventListener("click", () => saveFeedback(rec, "待反馈", restore));
    item.append(label, restore);
    trashList.append(item);
  }
  if (!activeJobs.length) {
    const empty = node("div", "pipeline-empty");
    empty.append(
      node("strong", "", data.jobs.length ? "当前没有正在招聘的岗位" : "从第一个岗位开始"),
      node("p", "", data.jobs.length ? "可以重新开启已停止的岗位，或创建一个新岗位。" : "创建 JD 后，匹配的候选人会直接出现在岗位下方。"),
    );
    const create = node("button", "primary", "新增岗位");
    create.type = "button";
    create.addEventListener("click", openJobEditor);
    empty.append(create);
    list.append(empty);
    return;
  }
  for (const job of activeJobs) {
    const candidates = data.recommendations
      .filter(rec => rec.job_id === job.id && !isBlockedStatus(rec.status))
      .sort((left, right) => Number(left.status === "录用") - Number(right.status === "录用"));
    const section = node("section", "pipeline-job");
    section.dataset.jobId = job.id;
    const heading = node("header", "pipeline-job-heading");
    const title = node("div", "pipeline-job-title");
    const orderHandle = node("button", "job-order-handle", "");
    orderHandle.type = "button";
    orderHandle.title = "拖动调整岗位顺序；也可用上下方向键移动";
    orderHandle.setAttribute("aria-label", `调整${job.title}的展示顺序`);
    bindJobOrderHandle(orderHandle, section, list);
    title.append(orderHandle, node("span", `recruiting-pill ${job.enabled ? "active" : "paused"}`, job.enabled ? "招聘中" : "已停止"), node("h3", "", job.title), node("span", "pipeline-candidate-count", `${candidates.length} 位候选人`));
    const jobActions = node("div", "pipeline-job-actions");
    const edit = node("button", "outline", "编辑岗位");
    edit.type = "button";
    edit.addEventListener("click", () => editJob(job));
    const toggle = node("button", "outline", "停止招聘");
    toggle.type = "button";
    toggle.addEventListener("click", () => setJobEnabled(job, false, toggle));
    jobActions.append(edit, toggle);
    heading.append(title, jobActions);
    const brief = node("details", "pipeline-job-brief");
    brief.append(node("summary", "", "查看岗位说明"), node("p", "", job.body));
    const table = node("div", "pipeline-table");
    if (candidates.length) {
      const labels = node("div", "pipeline-table-labels");
      ["匹配详情", "候选人", "匹配度", "当前阶段"].forEach((label, boundary) => {
        const cell = node("span", "pipeline-column-label", label);
        if (boundary < 3) {
          const handle = node("button", "pipeline-column-resizer");
          handle.type = "button";
          handle.title = "拖动调整列宽；双击恢复默认宽度";
          handle.setAttribute("aria-label", `调整${label}列宽`);
          bindPipelineColumnResizer(handle, labels, boundary);
          cell.append(handle);
        }
        labels.append(cell);
      });
      table.append(labels);
      for (const rec of candidates) table.append(pipelineCandidateRow(rec));
    } else {
      const empty = node("div", "pipeline-job-empty");
      empty.append(node("strong", "", "等待合适的人才"), node("span", "", "有新的推荐后，会直接显示在这里。"));
      table.append(empty);
    }
    section.append(heading, brief, table);
    list.append(section);
  }
}
async function saveFeedback(rec, action, button) {
  button.disabled = true;
  try {
    await request("feedback", { id: rec.id, status: action });
    if ($("feedbackDialog").open) $("feedbackDialog").close();
    await refreshAlumni();
    message("");
  } catch (error) { message(error.message); button.disabled = false; }
}
function openFeedbackDialog(rec) {
  $("feedbackDialogTitle").textContent = `修改 ${rec.candidate_name || "候选人"} 的反馈`;
  $("feedbackDialogHint").textContent = rec.job_title || "";
  const choices = $("feedbackChoices");
  choices.replaceChildren();
  const choicesByStatus = {
    "不感兴趣": [["待反馈", "恢复到待反馈"], ["感兴趣", "改为面试中"]],
    "未录用": [["待反馈", "恢复到待反馈"], ["面试中", "改为面试中"], ["录用", "改为录用"]],
    "录用": [["面试中", "改为面试中"], ["未录用", "改为未录用"], ["待反馈", "改为待反馈"]],
    "面试中": [["待反馈", "改为待反馈"], ["录用", "改为录用"], ["未录用", "改为未录用"], ["不感兴趣", "改为不感兴趣"]],
  };
  const available = choicesByStatus[rec.status] || [["待反馈", "改为待反馈"], ["不感兴趣", "改为不感兴趣"]];
  for (const [status, label] of available) {
    const button = node("button", status === "录用" ? "feedback-choice-hired" : status === "感兴趣" ? "primary" : "outline", label);
    button.type = "button";
    button.addEventListener("click", () => saveFeedback(rec, status, button));
    choices.append(button);
  }
  $("feedbackDialog").showModal();
}
function clearJobForm() {
  $("jobForm").reset();
  $("jobId").value = "";
  $("jobSubmit").textContent = "保存 JD";
  $("jobDialogTitle").textContent = "新增 JD";
  updateJobRequiredStates();
}
function selectedJobCategories() {
  return [...document.querySelectorAll('input[name="jobCategory"]:checked')].map(input => input.value);
}
function jobFieldHasValue(card) {
  const categoryInputs = [...card.querySelectorAll('input[name="jobCategory"]')];
  if (categoryInputs.length) return categoryInputs.some(input => input.checked);
  const control = card.querySelector("input,textarea,select");
  return Boolean(control?.value?.trim());
}
function updateJobRequiredStates() {
  const missing = [];
  for (const card of document.querySelectorAll("#jobForm [data-job-required]")) {
    const empty = !jobFieldHasValue(card);
    card.classList.toggle("required-missing", empty);
    card.setAttribute("aria-invalid", empty ? "true" : "false");
    if (empty) missing.push(card);
  }
  return missing;
}

document.addEventListener("DOMContentLoaded", async () => {
  document.body.classList.add(role === "alumni" ? "alumni-mode" : "candidate-mode");
  document.title = role === "candidate" ? "TALENT · 候选人" : "TALENT · 校友企业";
  $("roleBadge").textContent = role === "candidate" ? "候选人端" : "校友端";
  $("authTitle").textContent = role === "candidate" ? "让合适的机会，找到你。" : "让合适的人才，走向你。";
  $("authSubtitle").textContent = role === "candidate" ? "管理你的简历与推荐状态。" : "管理岗位，查看匹配的候选人。";
  $("dashboardEyebrow").textContent = role === "candidate" ? "CANDIDATE SPACE" : "ALUMNI SPACE";
  $("dashboardTitle").textContent = role === "candidate" ? "我的求职空间" : "企业招聘空间";
  $("dashboardSubtitle").textContent = role === "candidate" ? "简历与推荐，由你掌控。" : "岗位与候选人，都在这里。";
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if ((await response.json()).mp_oauth) {
      $("localLogin").hidden = true;
      $("oauthLogin").hidden = false;
      $("oauthLink").href = `/${role}/oauth/start`;
      const authError = new URLSearchParams(location.search).get("auth_error");
      const authMessages = {
        founder_company_hr_required: "此奇绩账号未关联 founder_company_hr 角色，无法登录校友端。请联系奇绩管理员确认账号角色。",
        invalid_phone: "奇绩账号未返回有效的中国大陆手机号。请在奇绩账号中绑定并验证手机号后重试。",
        phone_mismatch: "奇绩账号手机号与已绑定的候选人账户不一致，请联系管理员核实绑定。",
        phone_in_use: "该手机号已关联其他候选人账户。请联系管理员核实身份并将该账户绑定到你的奇绩账号。",
        service_error: "登录服务暂时无法读取或创建账户，请稍后重试；若持续失败，请联系管理员并告知发生时间。",
        auth_error: "OAuth 登录失败，请重新发起登录。",
      };
      if (authError) $("oauthMessage").textContent = authMessages[authError] || authMessages.auth_error;
    }
  } catch {}
  $("loginTab").addEventListener("click", () => setAuthMode(false));
  $("registerTab").addEventListener("click", () => setAuthMode(true));
  $("authForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("authSubmit"); button.disabled = true;
    try { const me = await request(data.registering ? "register" : "login", { phone: $("phone").value, password: $("password").value }); await showDashboard(me); $("password").value = ""; }
    catch (error) { message(error.message, false, true); }
    finally { button.disabled = false; }
  });
  $("logout").addEventListener("click", async () => { try { await request("logout", {}); } finally { showAuth(); } });
  $("candidateResume").addEventListener("change", async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const status = $("candidateUploadStatus");
    if (file.size > 8 * 1024 * 1024) { status.textContent = "文件不能超过 8 MB"; return; }
    $("candidateResumeButton").classList.add("busy");
    $("candidateUploadProgress").hidden = false;
    status.textContent = "";
    const phaseTimer = setTimeout(() => {
      $("candidateUploadProgressTitle").textContent = "AI 正在解析简历";
      $("candidateUploadProgressText").textContent = "正在识别经历、能力与求职意向…";
    }, 900);
    try {
      const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
      const me = await request("resume", { field: "简历", name: file.name, data: encoded, analyze: true });
      data.analysisResult = { error: me.analysis_error || "", count: Array.isArray(me.analysis_fields) ? me.analysis_fields.length : 0 };
      data.manualMode = true;
      await showDashboard(me);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      status.textContent = error.message;
      status.classList.remove("ok");
    } finally {
      clearTimeout(phaseTimer);
      $("candidateResumeButton").classList.remove("busy");
      $("candidateUploadProgress").hidden = true;
      $("candidateUploadProgressTitle").textContent = "正在读取你的简历";
      $("candidateUploadProgressText").textContent = "AI 正在整理经历与求职信息…";
      event.target.value = "";
    }
  });
  const uploadCard = $("candidateUpload").querySelector(".candidate-upload-card");
  uploadCard.addEventListener("pointermove", event => {
    const rect = uploadCard.getBoundingClientRect();
    uploadCard.style.setProperty("--pointer-x", `${event.clientX - rect.left}px`);
    uploadCard.style.setProperty("--pointer-y", `${event.clientY - rect.top}px`);
  });
  for (const eventName of ["dragenter", "dragover"]) uploadCard.addEventListener(eventName, event => { event.preventDefault(); uploadCard.classList.add("dragging"); });
  for (const eventName of ["dragleave", "drop"]) uploadCard.addEventListener(eventName, event => { event.preventDefault(); uploadCard.classList.remove("dragging"); });
  uploadCard.addEventListener("drop", event => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    $("candidateResume").files = transfer.files;
    $("candidateResume").dispatchEvent(new Event("change", { bubbles: true }));
  });
  $("candidateFields").addEventListener("input", updateCandidateRequiredStates);
  $("candidateFields").addEventListener("change", () => { updateBaseOtherVisibility(); updateCandidateRequiredStates(); });
  $("noticeOk").addEventListener("click", () => {
    $("noticeDialog").close();
    if (data.sessionExpired) { data.sessionExpired = false; showAuth(); setAuthMode(false); }
  });
  $("noticeDialog").addEventListener("cancel", event => { if (data.sessionExpired) event.preventDefault(); });
  $("manualFill").addEventListener("click", () => { data.manualMode = true; showDashboard(data.me); });
  $("backToChat").addEventListener("click", () => { data.manualMode = false; showDashboard(data.me); });
  $("chatInput").addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (event.altKey) {
      const input = event.currentTarget;
      input.setRangeText("\n", input.selectionStart, input.selectionEnd, "end");
    } else if (!event.ctrlKey && !event.metaKey && !data.chatBusy) {
      $("chatForm").requestSubmit();
    }
  });
  $("chatForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (data.chatBusy) return;
    const content = $("chatInput").value.trim();
    if (!content) return;
    data.chatBusy = true;
    data.chatThinking = true;
    $("chatSend").disabled = true;
    $("chatInput").value = "";
    data.chatMessages.push({ role: "user", content });
    renderChat();
    chatStatus("正在整理资料…");
    try {
      const result = await request("chat", { messages: data.chatMessages.slice(-24), draft: data.chatFields });
      Object.assign(data.chatFields, result.fields || {});
      if (result.profile) {
        data.me = result.profile;
        for (const name of Object.keys(result.fields || {})) delete data.chatFields[name];
      }
      const replies = Array.isArray(result.reply_parts) && result.reply_parts.length ? result.reply_parts.filter(part => typeof part === "string" && part.trim()) : [result.reply];
      data.chatScrollTarget = data.chatMessages.length;
      data.chatMessages.push(...replies.map(content => ({ role: "assistant", content })));
      if (!result.missing_required?.length && result.profile && requiredProfileComplete(result.profile)) data.completionAnnounced = true;
      chatStatus("");
    } catch (error) {
      chatStatus(error.message, true);
      data.chatMessages.push({ role: "assistant", content: "对话暂时不可用，请重试，或点击“手动填写”。" });
    } finally {
      data.chatBusy = false;
      data.chatThinking = false;
      $("chatSend").disabled = false;
      renderChat();
    }
  });
  $("chatResume").addEventListener("change", async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { chatStatus("文件不能超过 8 MB", true); return; }
    data.chatBusy = true; renderChat(); chatStatus("正在上传简历…");
    try {
      const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
      data.me = await request("resume", { field: "简历", name: file.name, data: encoded });
      announceCompletion();
      chatStatus("简历已上传");
    } catch (error) { chatStatus(error.message, true); saveNotice(error.message, false); }
    finally { data.chatBusy = false; event.target.value = ""; renderChat(); }
  });
  $("chatConfirm").addEventListener("click", async () => {
    if (data.chatBusy) return;
    data.chatBusy = true; renderChat(); chatStatus("正在保存资料…");
    try {
      const me = await request("profile", { fields: chatFieldsForSubmit() });
      data.manualMode = true;
      await showDashboard(me);
      saveNotice("你的资料已提交。", true, "提交成功");
    } catch (error) { chatStatus(error.message, true); saveNotice(error.message, false); }
    finally { data.chatBusy = false; renderChat(); }
  });
  $("profileForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter; if (button) button.disabled = true;
    try {
      const fields = collectCandidateFields();
      const uploads = [...$("candidateFields").querySelectorAll('input[type="file"]')].filter(input => input.files.length);
      for (const field of data.me.schema || []) {
        if (!field.required || field.readonly) continue;
        const value = fields[field.name];
        if (field.type === 17) {
          if (field.name === "简历" && !data.me.files?.length && !uploads.some(input => input.dataset.field === "简历")) throw new Error("请上传简历");
        } else if (value === null || value === "" || Array.isArray(value) && !value.length || typeof value === "string" && !value.trim()) {
          updateCandidateRequiredStates(); focusCandidateField(field.name); throw new Error(`请填写${field.name}`);
        }
      }
      for (const input of uploads) {
        const file = input.files[0];
        if (file.size > 8 * 1024 * 1024) throw new Error(`${input.dataset.field}不能超过 8 MB`);
        const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
        await request("resume", { field: input.dataset.field, name: file.name, data: encoded });
      }
      const me = await request("profile", { fields, description: $("candidateDescription").value });
      data.analysisResult = null;
      await showDashboard(me); message("资料已保存到本地，正在后台同步飞书", true); saveNotice("", true);
    } catch (error) { message(error.message); saveNotice(error.message, false); }
    finally { if (button) button.disabled = false; }
  });
  $("toggleCandidate").addEventListener("click", async () => {
    const button = $("toggleCandidate");
    if (button.disabled) return;
    button.disabled = true; button.setAttribute("aria-busy", "true");
    try { const me = await request("profile", { enabled: !data.me.enabled }); await showDashboard(me); message("推荐状态已更新，正在后台同步飞书", true); }
    catch (error) { message(error.message); }
    finally { button.disabled = false; button.removeAttribute("aria-busy"); }
  });
  $("openCompanyDialog").addEventListener("click", () => openCompanyEditor(false));
  $("openJobDialog").addEventListener("click", openJobEditor);
  for (const button of document.querySelectorAll("[data-close-dialog]")) button.addEventListener("click", () => $(button.dataset.closeDialog).close());
  $("companyDialog").addEventListener("cancel", event => { if (data.companyOnboarding) event.preventDefault(); });
  $("companyDialog").addEventListener("close", () => {
    data.companyOnboarding = false;
    $("companyDialogClose").hidden = false;
    $("companyDialogCancel").hidden = false;
  });
  $("closeResumeDialog").addEventListener("click", () => $("resumeDialog").close());
  $("resumeDialog").addEventListener("close", () => { data.resumeRequestId++; $("resumeFrame").src = "about:blank"; $("resumeFrame").hidden = true; $("resumeDownload").removeAttribute("href"); if (data.resumeObjectUrl) URL.revokeObjectURL(data.resumeObjectUrl); data.resumeObjectUrl = null; });
  $("companyForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter;
    const status = $("companySaveStatus");
    const company = $("companyName").value.trim(), contactName = $("companyContactName").value.trim(), contactRole = $("companyContactRole").value.trim();
    if (button) button.disabled = true;
    status.textContent = "正在保存…";
    try {
      if (!data.portalVersionChecked) throw new Error("当前仍是旧版校友端服务。请关闭旧服务窗口，重新打开校友端并刷新页面。 ");
      const me = await request("company", { company, contact_name: contactName, contact_role: contactRole });
      if (me.company !== company || me.contact_name !== contactName || me.contact_role !== contactRole) throw new Error("服务未返回新保存的企业资料。请重启校友端服务后重试。");
      data.companyOnboarding = false;
      $("companyDialog").close();
      await showDashboard(me);
      message("企业信息已保存到本地，正在后台同步飞书", true);
    } catch (error) { status.textContent = error.message; message(error.message); }
    finally { if (button) button.disabled = false; }
  });
  $("jobForm").addEventListener("input", updateJobRequiredStates);
  $("jobForm").addEventListener("change", updateJobRequiredStates);
  enhanceTalentDateInput($("jobLatestArrivalDate"), "最晚到岗日期");
  $("jobForm").addEventListener("submit", async event => {
    event.preventDefault();
    const missing = updateJobRequiredStates();
    if (missing.length) {
      missing[0].querySelector("input,textarea,select")?.focus();
      message("");
      saveNotice("请补齐新增 JD 中标红的必填信息。", false);
      return;
    }
    const button = $("jobSubmit");
    button.disabled = true;
    try {
      await request("job", {
        id: $("jobId").value,
        title: $("jobTitle").value,
        body: $("jobBody").value,
        work_location: $("jobWorkLocation").value,
        attendance_mode: $("jobAttendanceMode").value,
        job_categories: selectedJobCategories(),
        min_days_per_week: $("jobMinDays").value,
        latest_arrival_date: $("jobLatestArrivalDate").value,
        enabled: $("jobEnabled").checked,
      });
      $("jobDialog").close();
      clearJobForm();
      await refreshAlumni();
      message("JD 已保存到本地，正在后台同步飞书", true);
    } catch (error) { message(""); saveNotice(error.message, false); }
    finally { button.disabled = false; }
  });
  $("cancelJobEdit").addEventListener("click", () => { $("jobDialog").close(); clearJobForm(); });
  try { await showDashboard(await request("me")); } catch { showAuth(); }
});
