const role = location.pathname.startsWith("/alumni/") ? "alumni" : "candidate";
const api = `/api/${role}`;
const $ = id => document.getElementById(id);
const data = { me: null, jobs: [], recommendations: [], registering: false, manualMode: false, chatMessages: [], chatFields: {}, chatBusy: false, chatThinking: false, chatScrollTarget: null, completionAnnounced: false, sessionExpired: false, portalVersionChecked: false, companyPrompted: false, resumeObjectUrl: null, resumeRequestId: 0 };
const baseFieldName = "意向base地（可多选）";
const baseOtherFieldName = "意向base地（可多选）-其他-补充内容";

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
  $("authSubmit").textContent = registering ? "注册并进入" : "登录";
  $("password").autocomplete = registering ? "new-password" : "current-password";
  message("", false, true);
}
function showAuth() {
  closeDashboardDialogs();
  if ($("noticeDialog").open) $("noticeDialog").close();
  data.me = null;
  data.companyPrompted = false;
  data.manualMode = false;
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
      input.type = "date";
      input.value = displayDate(current);
      input.readOnly = field.readonly;
      input.disabled = field.readonly;
      wrapper.append(input);
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
async function showDashboard(me) {
  data.me = me;
  $("auth").hidden = true;
  $("dashboard").hidden = false;
  $("logout").hidden = false;
  $("accountPhone").textContent = me.phone;
  const useChat = role === "candidate" && !me.submitted && !data.manualMode;
  $("candidateChat").hidden = !useChat;
  $("candidateDashboard").hidden = role !== "candidate" || useChat;
  $("alumniDashboard").hidden = role !== "alumni";
  if (role === "candidate") {
    if (useChat) {
      if (!data.chatMessages.length) {
        data.chatMessages = initialChatMessages(me).map(content => ({ role: "assistant", content }));
        data.completionAnnounced = requiredProfileComplete(me);
        data.chatScrollTarget = 0;
      }
      renderChat();
    }
    $("submittedBanner").hidden = !me.submitted;
    $("backToChat").hidden = me.submitted;
    renderCandidateForm(me);
    $("candidateDescription").value = me.description || "";
    $("candidateStatus").textContent = me.enabled ? "推荐已开启" : "推荐已停止";
    $("candidateStatus").classList.toggle("off", !me.enabled);
    $("toggleCandidate").textContent = me.enabled ? "停止推荐" : "重新开启";
  } else {
    $("companyName").value = me.company || "";
    $("companyContactTitle").value = me.contact_title || "";
    $("companyIntroduction").value = me.introduction || "";
    $("alumniCompanyTitle").textContent = me.company || "尚未设置企业";
    $("openJobDialog").disabled = !me.company || !me.contact_title || !me.introduction;
    await refreshAlumni();
    if (data.portalVersionChecked && !data.companyPrompted && (!me.company || !me.contact_title || !me.introduction)) {
      data.companyPrompted = true;
      if (!$("companyDialog").open) $("companyDialog").showModal();
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
    if (!healthResponse.ok || !health.local_recommendations || health.alumni_company_fields !== 1 || health.portal_revision !== 10) {
      saveNotice("校友端仍在运行旧版服务。请关闭旧服务窗口，再运行“打开校友端.cmd”，然后刷新页面。", false);
    } else data.portalVersionChecked = true;
  }
  const [jobs, recommendations] = await Promise.all([request("jobs"), request("recommendations")]);
  data.jobs = jobs.items;
  data.recommendations = recommendations.items;
  $("jobsCount").textContent = `${data.jobs.length} 个岗位`;
  $("recommendationsCount").textContent = `${data.recommendations.filter(rec => rec.status !== "不感兴趣").length} 条推荐`;
  $("alumniOverview").textContent = `${data.jobs.filter(job => job.enabled).length} 个岗位招聘中 · ${data.recommendations.filter(rec => rec.status !== "不感兴趣").length} 条候选人推荐`;
  renderJobs();
  renderRecommendations();
}
function renderJobs() {
  const list = $("jobsList");
  list.replaceChildren();
  if (!data.jobs.length) list.append(node("p", "empty", "还没有 JD。"));
  for (const job of data.jobs) {
    const card = node("article", "item-card");
    const head = node("div", "item-top");
    head.append(node("h3", "", job.title), node("span", `recruiting-pill ${job.enabled ? "active" : "paused"}`, job.enabled ? "● 招聘中" : "已停止"));
    const detail = node("details", "job-detail");
    detail.append(node("summary", "", "查看岗位要求"), node("pre", "", job.body));
    const actions = node("div", "item-actions");
    const edit = node("button", "", "编辑 JD");
    edit.type = "button";
    edit.addEventListener("click", () => {
      $("jobId").value = job.id;
      $("jobTitle").value = job.title;
      $("jobBody").value = job.body;
      $("jobEnabled").checked = job.enabled;
      $("jobSubmit").textContent = "保存修改";
      $("cancelJobEdit").hidden = false;
      $("jobDialogTitle").textContent = "编辑 JD";
      $("jobDialog").showModal();
      $("jobTitle").focus();
    });
    const toggle = node("button", "", job.enabled ? "停止招聘" : "重新开启");
    toggle.type = "button";
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try { await request("job", { id: job.id, title: job.title, body: job.body, enabled: !job.enabled }); await refreshAlumni(); message("岗位状态已更新", true); }
      catch (error) { message(error.message); toggle.disabled = false; }
    });
    actions.append(edit, toggle);
    card.append(head, detail, actions);
    list.append(card);
  }
}
const nextActions = { "待反馈": ["感兴趣", "不感兴趣"], "面试中": ["录用", "未录用"] };
function statusClass(status) {
  return ({ "待反馈": "pending", "面试中": "interview", "录用": "hired", "不感兴趣": "declined", "未录用": "declined" })[status] || "pending";
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
  const declined = data.recommendations.filter(rec => rec.status === "不感兴趣");
  const trash = $("recommendationTrash");
  trash.hidden = !declined.length;
  $("trashCount").textContent = `回收站 · ${declined.length}`;
  const trashList = $("trashList");
  trashList.replaceChildren();
  for (const rec of declined) {
    const item = node("div", "trash-item");
    const label = node("span", "", `${rec.candidate_name || "候选人"} · ${rec.job_title || "岗位"}`);
    const status = node("button", "feedback-pill declined feedback-tag", "不感兴趣 · 修改");
    status.type = "button";
    status.addEventListener("click", () => openFeedbackDialog(rec));
    const restore = node("button", "outline", "恢复显示");
    restore.type = "button";
    restore.addEventListener("click", () => saveFeedback(rec, "待反馈", restore));
    item.append(label, status, restore);
    trashList.append(item);
  }
  for (const rec of data.recommendations) {
    if (rec.status === "不感兴趣") continue;
    if (!groups.has(rec.job_id)) groups.set(rec.job_id, { title: rec.job_title || "历史岗位", enabled: false, items: [] });
    groups.get(rec.job_id).items.push(rec);
  }
  if (!data.recommendations.some(rec => rec.status !== "不感兴趣")) list.append(node("p", "empty", "当前没有待查看的候选人推荐。"));
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
      const status = node("button", `feedback-pill ${statusClass(rec.status)} feedback-tag`, "面试中 · 修改");
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
async function saveFeedback(rec, action, button) {
  button.disabled = true;
  try {
    await request("feedback", { id: rec.id, status: action });
    if ($("feedbackDialog").open) $("feedbackDialog").close();
    await refreshAlumni();
    message(action === "待反馈" ? "已恢复到推荐列表" : "反馈已保存", true);
  } catch (error) { message(error.message); button.disabled = false; }
}
function openFeedbackDialog(rec) {
  $("feedbackDialogTitle").textContent = `修改 ${rec.candidate_name || "候选人"} 的反馈`;
  $("feedbackDialogHint").textContent = rec.job_title || "";
  const choices = $("feedbackChoices");
  choices.replaceChildren();
  const available = rec.status === "不感兴趣" ? [["待反馈", "恢复显示"], ["感兴趣", "改为感兴趣"]] : [["待反馈", "改为待反馈"], ["不感兴趣", "改为不感兴趣"]];
  for (const [status, label] of available) {
    const button = node("button", status === "感兴趣" ? "primary" : "outline", label);
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
}

document.addEventListener("DOMContentLoaded", async () => {
  document.body.classList.add(role === "alumni" ? "alumni-mode" : "candidate-mode");
  document.title = role === "candidate" ? "AR · 候选人" : "AR · 校友企业";
  $("roleBadge").textContent = role === "candidate" ? "候选人端" : "校友端";
  $("authTitle").textContent = role === "candidate" ? "让合适的机会，找到你。" : "让合适的人才，走向你。";
  $("authSubtitle").textContent = role === "candidate" ? "管理你的简历与推荐状态。" : "管理岗位，查看匹配的候选人。";
  $("dashboardEyebrow").textContent = role === "candidate" ? "CANDIDATE SPACE" : "ALUMNI SPACE";
  $("dashboardTitle").textContent = role === "candidate" ? "我的求职空间" : "企业招聘空间";
  $("dashboardSubtitle").textContent = role === "candidate" ? "简历与推荐，由你掌控。" : "岗位与候选人，都在这里。";
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
          throw new Error(`请填写${field.name}`);
        }
      }
      for (const input of uploads) {
        const file = input.files[0];
        if (file.size > 8 * 1024 * 1024) throw new Error(`${input.dataset.field}不能超过 8 MB`);
        const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
        await request("resume", { field: input.dataset.field, name: file.name, data: encoded });
      }
      const me = await request("profile", { fields, description: $("candidateDescription").value });
      await showDashboard(me); message("资料已保存", true); saveNotice("资料已更新至飞书表格。", true);
    } catch (error) { message(error.message); saveNotice(error.message, false); }
    finally { if (button) button.disabled = false; }
  });
  $("toggleCandidate").addEventListener("click", async () => { try { const me = await request("profile", { enabled: !data.me.enabled }); await showDashboard(me); message("推荐状态已更新", true); } catch (error) { message(error.message); } });
  $("openCompanyDialog").addEventListener("click", () => { $("companyName").value = data.me?.company || ""; $("companyContactTitle").value = data.me?.contact_title || ""; $("companyIntroduction").value = data.me?.introduction || ""; $("companySaveStatus").textContent = ""; $("companyDialog").showModal(); $("companyName").focus(); });
  $("openJobDialog").addEventListener("click", () => { clearJobForm(); $("jobDialog").showModal(); $("jobTitle").focus(); });
  for (const button of document.querySelectorAll("[data-close-dialog]")) button.addEventListener("click", () => $(button.dataset.closeDialog).close());
  $("closeResumeDialog").addEventListener("click", () => $("resumeDialog").close());
  $("resumeDialog").addEventListener("close", () => { data.resumeRequestId++; $("resumeFrame").src = "about:blank"; $("resumeFrame").hidden = true; $("resumeDownload").removeAttribute("href"); if (data.resumeObjectUrl) URL.revokeObjectURL(data.resumeObjectUrl); data.resumeObjectUrl = null; });
  $("companyForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = event.submitter;
    const status = $("companySaveStatus");
    const company = $("companyName").value.trim(), contactTitle = $("companyContactTitle").value.trim(), introduction = $("companyIntroduction").value.trim();
    if (button) button.disabled = true;
    status.textContent = "正在保存…";
    try {
      if (!data.portalVersionChecked) throw new Error("当前仍是旧版校友端服务。请关闭旧服务窗口，重新打开校友端并刷新页面。 ");
      const me = await request("company", { company, contact_title: contactTitle, introduction });
      if (me.company !== company || me.contact_title !== contactTitle || me.introduction !== introduction) throw new Error("服务未返回新保存的企业资料。请重启校友端服务后重试。");
      $("companyDialog").close();
      await showDashboard(me);
      message("企业信息已保存", true);
    } catch (error) { status.textContent = error.message; message(error.message); }
    finally { if (button) button.disabled = false; }
  });
  $("jobForm").addEventListener("submit", async event => { event.preventDefault(); const button = $("jobSubmit"); button.disabled = true; try { await request("job", { id: $("jobId").value, title: $("jobTitle").value, body: $("jobBody").value, enabled: $("jobEnabled").checked }); $("jobDialog").close(); clearJobForm(); await refreshAlumni(); message("JD 已保存", true); } catch (error) { message(error.message); } finally { button.disabled = false; } });
  $("cancelJobEdit").addEventListener("click", () => { $("jobDialog").close(); clearJobForm(); });
  try { await showDashboard(await request("me")); } catch { showAuth(); }
});
