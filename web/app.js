const state = { tables: [], candidateTab: "current", visibleCandidates: [], visibleJobs: [], previousFocus: null, promptInitialized: false, jdUnits: [], activeJdId: null, aiConfig: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

function table(kind, archived = false) {
  return state.tables.find((item) => item.kind === kind && item.archived === archived);
}

function fieldsOf(record) { return record?.fields || {}; }
function field(record, ...names) {
  const data = fieldsOf(record);
  for (const name of names) if (data[name] !== undefined && data[name] !== null && data[name] !== "") return data[name];
  return "";
}
function textOf(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(textOf).filter(Boolean).join("、");
  if (typeof value === "object") {
    if (value.file_token) return value.name || "附件";
    if (value.text) return textOf(value.text);
    if (value.name) return textOf(value.name);
    if (value.value) return textOf(value.value);
    if (value.link) return textOf(value.link);
    return Object.values(value).map(textOf).filter(Boolean).join("、");
  }
  return "";
}
function compact(value, max = 130) {
  const clean = textOf(value).replace(/\s+/g, " ").trim();
  return clean.length > max ? clean.slice(0, max).trimEnd() + "…" : clean;
}
function dateOf(record) {
  const raw = field(record, "填写时间", "提交时间");
  const timestamp = typeof raw === "number" ? raw : Number(raw);
  if (!timestamp || !Number.isFinite(timestamp)) return "";
  const date = new Date(timestamp < 1e11 ? timestamp * 1000 : timestamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}
function recordTimestamp(record) {
  const raw = field(record, "填写时间", "提交时间");
  return Number(raw) || Number(record.created_time) || 0;
}
function attachmentItems(record) {
  return Object.values(fieldsOf(record)).flatMap((value) => Array.isArray(value) ? value.filter((part) => part && typeof part === "object" && part.file_token) : []);
}
function candidateView(record) {
  const name = compact(field(record, "姓名 2", "姓名", "名字"), 45) || "未命名候选人";
  const school = compact(field(record, "学校、专业、入学时间-毕业时间"), 80);
  const role = compact(field(record, "意向投递的目标公司或岗位", "意向投递公司/岗位（选填）", "请对你想在被投企业中做的具体岗位/方向，做个简易描述"), 145);
  const location = compact(field(record, "意向base地（可多选）", "意向base地（多选）"), 40);
  const summary = compact(field(record, "请对你想在被投企业中做的具体岗位/方向，做个简易描述", "是什么原因让你决定申请被投企业联合招聘项目？", "学校、专业、入学时间-毕业时间"), 135);
  const tags = [location, compact(field(record, "你更想以什么角色加入奇绩的被投企业（多选） 2", "期望参与的工作类型"), 48)].filter(Boolean);
  return { title: name, subtitle: school || role || "候选人档案", summary, tags, date: dateOf(record), attachments: attachmentItems(record).length, avatar: name.slice(0, 1) };
}
function jobView(record) {
  const company = compact(field(record, "公司名称（对外展示的名称）", "公司名称", "企业名称"), 55) || "未命名企业";
  const position = compact(field(record, "开放岗位", "岗位名称", "招聘岗位"), 100);
  const intro = compact(field(record, "公司介绍", "为什么候选人应该加入你们？（选填）", "开放岗位2（若有更多的岗位也可一并汇总写在这一栏）"), 145);
  const tags = [position, compact(field(record, "开放岗位2（若有更多的岗位也可一并汇总写在这一栏）"), 45)].filter(Boolean);
  return { title: company, subtitle: position || "校友企业招聘需求", summary: intro, tags, date: dateOf(record), attachments: attachmentItems(record).length, avatar: company.slice(0, 1) };
}
function searchRecord(record, query) {
  return !query || Object.values(fieldsOf(record)).some((value) => textOf(value).toLocaleLowerCase("zh-CN").includes(query));
}
function cardHtml(record, index, kind) {
  const view = kind === "candidate" ? candidateView(record) : jobView(record);
  const tags = view.tags.slice(0, 2).map((tag) => `<span class="card-tag">${escapeHtml(tag)}</span>`).join("");
  const attachment = view.attachments ? `<span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 12.5 5.5-5.5a3 3 0 0 1 4.2 4.2l-7.5 7.5a5 5 0 0 1-7.1-7.1L11 3.7"/></svg>${view.attachments} 个附件</span>` : "<span>暂无附件</span>";
  return `<button type="button" class="record-card" data-index="${index}" aria-label="查看${kind === "candidate" ? "候选人" : "校友 JD"} ${escapeHtml(view.title)} 的详情"><div class="card-top"><div class="card-heading"><span class="avatar ${kind === "job" ? "job-avatar" : ""}">${escapeHtml(view.avatar)}</span><span class="card-title-wrap"><span class="card-title">${escapeHtml(view.title)}</span><span class="card-subtitle">${escapeHtml(view.subtitle)}</span></span></div><span class="card-arrow" aria-hidden="true">↗</span></div><div class="card-summary">${escapeHtml(view.summary || "点击查看完整资料与字段信息")}</div>${tags ? `<div class="card-tags">${tags}</div>` : ""}<div class="card-bottom">${attachment}<span>${escapeHtml(view.date || "已收录")}</span></div></button>`;
}
function emptyHtml(title, detail) { return `<div class="empty-state"><div class="empty-icon" aria-hidden="true">⌕</div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div>`; }

function renderList(kind) {
  const archived = kind === "candidate" && state.candidateTab === "archive";
  const source = table(kind, archived);
  const input = $(kind === "candidate" ? "candidateSearch" : "jobSearch");
  const query = input.value.trim().toLocaleLowerCase("zh-CN");
  const records = [...(source?.records || [])].sort((a, b) => recordTimestamp(b) - recordTimestamp(a));
  const visible = records.filter((record) => searchRecord(record, query));
  if (kind === "candidate") state.visibleCandidates = visible;
  else state.visibleJobs = visible;
  const target = $(kind === "candidate" ? "candidateList" : "jobList");
  const label = $(kind === "candidate" ? "candidateResultLabel" : "jobResultLabel");
  label.textContent = query ? `${visible.length} / ${records.length} 条结果` : `共 ${records.length} 条记录`;
  target.innerHTML = visible.length ? visible.map((record, index) => cardHtml(record, index, kind)).join("") : emptyHtml(source?.available ? "没有找到匹配的记录" : "尚未同步这张表", source?.available ? "换一个关键词试试" : "在终端运行 python ar.py pull --all-tables 后刷新页面");
}

function formatFieldValue(value, fieldType) {
  if ((fieldType === 5 || fieldType === 1001) && typeof value === "number") {
    const date = new Date(value < 1e11 ? value * 1000 : value);
    if (!Number.isNaN(date.getTime())) return date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
  }
  return textOf(value);
}
function attachmentHtml(item, source) {
  const entry = source.attachments.find((part) => part.file_token === item.file_token);
  const available = Boolean(entry);
  const name = item.name || "未命名附件";
  const size = item.size ? `${(item.size / 1024 / 1024).toFixed(2)} MB` : "本地附件";
  if (!available) return `<div class="attachment-row"><span class="attachment-left"><span class="attachment-icon">↳</span><span><span class="attachment-name">${escapeHtml(name)}</span><span class="attachment-size">尚未下载到本地</span></span></span></div>`;
  const url = `../downloads/${encodeURIComponent(source.id)}/${entry.file.split(/[\\/]/).map(encodeURIComponent).join("/")}`;
  return `<a class="attachment-row" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"><span class="attachment-left"><span class="attachment-icon">↳</span><span><span class="attachment-name">${escapeHtml(name)}</span><span class="attachment-size">${escapeHtml(size)}</span></span></span><span class="attachment-open" aria-hidden="true">↗</span></a>`;
}
function showDetail(record, kind) {
  const source = table(kind, kind === "candidate" && state.candidateTab === "archive");
  const view = kind === "candidate" ? candidateView(record) : jobView(record);
  const fieldTypes = new Map((source.fields || []).map((item) => [item.field_name, item.type]));
  let fields = "", attachments = "";
  for (const [name, value] of Object.entries(fieldsOf(record))) {
    if (value === "" || value === null || value === undefined || (Array.isArray(value) && !value.length)) continue;
    const files = Array.isArray(value) ? value.filter((part) => part && typeof part === "object" && part.file_token) : [];
    if (files.length) { attachments += files.map((item) => attachmentHtml(item, source)).join(""); continue; }
    const formatted = formatFieldValue(value, fieldTypes.get(name));
    if (formatted) fields += `<div class="drawer-field"><div class="drawer-field-label">${escapeHtml(name)}</div><div class="drawer-field-value ${formatted.length > 140 ? "long" : ""}">${escapeHtml(formatted)}</div></div>`;
  }
  $("drawerOverline").textContent = kind === "candidate" ? (state.candidateTab === "archive" ? "ARCHIVED TALENT" : "CANDIDATE PROFILE") : "ALUMNI OPPORTUNITY";
  $("drawerContent").innerHTML = `<div class="drawer-hero"><span class="avatar drawer-avatar ${kind === "job" ? "job-avatar" : ""}">${escapeHtml(view.avatar)}</span><div><div class="drawer-kind">${kind === "candidate" ? "候选人档案" : "校友企业 · 招聘需求"}</div><h2 class="drawer-title">${escapeHtml(view.title)}</h2><p class="drawer-subtitle">${escapeHtml(view.subtitle)}</p></div></div>${attachments ? `<div class="drawer-section-title">相关附件</div>${attachments}` : ""}<div class="drawer-section-title">完整信息</div>${fields || '<p class="drawer-field-value">暂无其他信息</p>'}<div class="drawer-meta">记录 ID：${escapeHtml(record.record_id || "—")} · 来源：${escapeHtml(source.name)}</div>`;
  state.previousFocus = document.activeElement;
  $("drawerBackdrop").hidden = false;
  $("detailDrawer").classList.add("open");
  $("detailDrawer").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => $("drawerBackdrop").classList.add("visible"));
  $("drawerClose").focus();
}
function closeDetail() {
  $("drawerBackdrop").classList.remove("visible");
  $("detailDrawer").classList.remove("open");
  $("detailDrawer").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  setTimeout(() => { if (!$("detailDrawer").classList.contains("open")) $("drawerBackdrop").hidden = true; }, 300);
  state.previousFocus?.focus();
}
function updateSummary() {
  const current = table("candidate", false), archive = table("candidate", true), jobs = table("job", false);
  const count = (item) => item?.records.length || 0;
  $("metricCandidates").textContent = count(current);
  $("metricArchive").textContent = count(archive);
  $("metricJobs").textContent = count(jobs);
  $("candidateHeadingCount").textContent = state.candidateTab === "archive" ? count(archive) : count(current);
  $("jobHeadingCount").textContent = count(jobs);
  const available = state.tables.filter((item) => item.available);
  $("syncState").textContent = available.length === state.tables.length ? "已同步" : `已同步 ${available.length}/3`;
  const newest = Math.max(...available.map((item) => new Date(item.synced_at).getTime()), 0);
  $("syncTime").textContent = newest ? `最近读取 ${new Date(newest).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : "尚无本地数据";
  const missing = state.tables.filter((item) => !item.available).map((item) => item.name);
  $("missingNotice").hidden = !missing.length;
  if (missing.length) $("missingNotice").textContent = `以下数据表还没有本地快照：${missing.join("、")}。请在终端运行 python ar.py pull --all-tables，然后重新打开网页。`;
  renderFlow();
}
function renderFlow() {
  const candidates = table("candidate", false)?.records || [];
  const jobs = table("job", false)?.records || [];
  $("flowCandidateTotal").textContent = `${candidates.length} 位候选人`;
  $("flowJobTotal").textContent = `${jobs.length} 条招聘需求`;
  const node = (record, kind, index) => {
    const view = kind === "candidate" ? candidateView(record) : jobView(record);
    const subtitle = kind === "candidate" ? "候选人" : "校友企业";
    return `<button type="button" class="flow-node ${kind === "job" ? "flow-node-job" : ""}" data-flow-kind="${kind}" style="--node-order:${index}" aria-label="查看${escapeHtml(view.title)}所在的${subtitle}列表"><span class="flow-node-avatar">${escapeHtml(view.avatar)}</span><span class="flow-node-text"><strong>${escapeHtml(view.title)}</strong><small>${escapeHtml(compact(view.subtitle, 26) || subtitle)}</small></span><span class="flow-node-arrow" aria-hidden="true">↗</span></button>`;
  };
  const placeholders = (kind) => `<div class="flow-node flow-node-placeholder"><span class="flow-node-avatar">·</span><span class="flow-node-text"><strong>暂无${kind === "candidate" ? "候选人" : "校友企业"}数据</strong><small>同步后在这里展示</small></span></div>`;
  $("flowCandidateNodes").innerHTML = candidates.length ? candidates.slice(0, 6).map((record, index) => node(record, "candidate", index)).join("") : placeholders("candidate");
  $("flowJobNodes").innerHTML = jobs.length ? jobs.slice(0, 6).map((record, index) => node(record, "job", index)).join("") : placeholders("job");
}
async function loadCatalog() {
  const button = $("refreshButton");
  button.disabled = true;
  try {
    if (state.tables.length) {
      await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = `data.js?t=${Date.now()}`;
        script.onload = resolve;
        script.onerror = () => reject(new Error("无法重新读取 data.js"));
        document.head.appendChild(script);
      });
    }
    if (!window.AR_DATA) throw new Error("网页数据尚未生成，请运行 python build_web.py");
    const payload = window.AR_DATA;
    state.tables = payload.tables || [];
    updateSummary();
    renderList("candidate");
    renderList("job");
    if (state.promptInitialized) { savePrompt(false); state.promptInitialized = false; preparePrompt(); }
    window.AR_MATCH?.onCatalogUpdated();
  } catch (error) {
    $("syncState").textContent = "读取失败";
    $("missingNotice").hidden = false;
    $("missingNotice").textContent = `读取本地数据失败：${error.message}。请运行 python build_web.py 后重新打开网页。`;
  } finally { button.disabled = false; }
}
function showSyncFeedback(message, error = false) {
  const notice = $("syncFeedback");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = false;
}
async function syncFromFeishu() {
  if (location.protocol === "file:") {
    showSyncFeedback("当前是旧版本地文件页面。请关闭网页，重新双击“打开AR网页.cmd”后再检查飞书更新。", true);
    return;
  }
  const button = $("refreshButton");
  const label = button.querySelector(".refresh-label");
  button.disabled = true;
  label.textContent = "正在检查…";
  $("syncFeedback").hidden = true;
  try {
    const response = await fetch("/api/sync", { method: "POST", headers: { "X-AR-Sync": "1" }, cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    if (result.changed) {
      await loadCatalog();
      const changedTables = result.tables.filter((item) => item.changed);
      const detail = changedTables.map((item) => `${item.name}：新增 ${item.added}、修改 ${item.edited}、移除 ${item.removed}`).join("；");
      showSyncFeedback(`已更新本地数据。${detail}${result.downloaded ? `；新附件 ${result.downloaded} 个` : ""}`);
    } else {
      showSyncFeedback("已检查飞书：三张表均无变化，本地文件未改动。");
    }
  } catch (error) {
    showSyncFeedback(`检查失败：${error.message}`, true);
  } finally {
    label.textContent = "检查飞书更新";
    button.disabled = false;
  }
}
function setupNavigation() {
  for (const [buttonId, view] of [["navOverview", "overview"], ["navDirectory", "directory"], ["navAI", "ai"], ["navData", "data"]]) {
    $(buttonId).addEventListener("click", () => showView(view, buttonId));
  }
  $("navMatch").addEventListener("click", () => window.AR_MATCH.openWorkspace());
}
function showView(view, navId, target) {
  if (state.promptInitialized && view !== "ai") savePrompt(false);
  for (const name of ["overview", "directory", "ai", "match", "data"]) $(`${name}View`).hidden = view !== name;
  if (view === "ai" && !state.promptInitialized) preparePrompt();
  document.querySelectorAll(".nav-item").forEach((item) => { item.classList.remove("active"); item.removeAttribute("aria-current"); });
  $(navId).classList.add("active");
  $(navId).setAttribute("aria-current", "page");
  document.querySelector(".breadcrumb strong").textContent = ({ overview: "总览", directory: "人才与岗位一览", ai: "AI 管理", match: "岗位匹配", data: "数据中心" })[view];
  requestAnimationFrame(() => (target ? $(target) : $("mainContent")).scrollIntoView({ behavior: "smooth", block: "start" }));
}
const DEFAULT_GLOBAL_PROMPT = `你是一位审慎的招聘匹配顾问。请根据候选人的真实资料与岗位 JD，评估是否值得推荐。\n\n评估维度：\n1. 必备技能、相关经历和岗位职责的吻合度。\n2. 地点、工作方式、入职时间等明确条件。\n3. 候选人的职业意向与企业提供的机会。\n\n输出每位候选人的匹配理由、待核实点和推荐优先级。只能引用资料中存在的事实；信息缺失时明确写“待核实”，不要推测或编造。`;
const JOB_FIELDS = ["开放岗位", "开放岗位2（若有更多的岗位也可一并汇总写在这一栏）"];
function readPrompt(key) { try { return localStorage.getItem(key); } catch { return null; } }
function jdHash(text) {
  let hash = 2166136261;
  for (const char of text.slice(0, 160)) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return (hash >>> 0).toString(36);
}
function splitJdText(raw, sourceKey = "") {
  const text = textOf(raw).trim();
  if (!text) return [];
  const boundaries = [];
  const numbered = /^\s*(?:岗位|职位)\s*[2-9二三四五六七八九]\s*[:：]?\s*$/gm;
  for (const match of text.matchAll(numbered)) boundaries.push(match.index);
  const titles = [...text.matchAll(/^\s*(?:岗位名称|职位名称)\s*[:：]/gm)];
  if (titles.length > 1) for (const match of titles.slice(1)) boundaries.push(match.index);
  if (sourceKey) {
    try {
      const markers = JSON.parse(readPrompt(`ar-jd-cuts:${sourceKey}`) || "[]");
      for (const marker of markers) {
        if (typeof marker !== "string" || !marker) continue;
        const index = text.indexOf(marker);
        if (index > 0 && index === text.lastIndexOf(marker)) boundaries.push(index);
      }
    } catch { /* Ignore malformed local split settings. */ }
  }
  const cuts = [0, ...new Set(boundaries.filter((index) => index > 0))].sort((a, b) => a - b);
  return cuts.map((start, index) => ({ body: text.slice(start, cuts[index + 1]).trim(), start })).filter((part) => part.body);
}
function jdTitle(text, fieldIndex, segmentIndex) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const title = lines.find((line) => !/^(?:岗位|职位)\s*[1-9一二三四五六七八九]\s*[:：]?$/.test(line)) || "";
  return compact(title.replace(/^(?:岗位名称|职位名称)\s*[:：]\s*/, "").replace(/^【([^】]+)】$/, "$1"), 36) || `岗位 ${fieldIndex + 1}.${segmentIndex + 1}`;
}
function buildJdUnits() {
  const jobs = table("job", false)?.records || [];
  return jobs.flatMap((record) => {
    const company = jobView(record).title;
    return JOB_FIELDS.flatMap((fieldName, fieldIndex) => {
      const sourceKey = `${record.record_id}:${fieldIndex}`;
      return splitJdText(field(record, fieldName), sourceKey).map(({ body, start }, segmentIndex) => {
      const title = jdTitle(body, fieldIndex, segmentIndex);
      return { id: `${sourceKey}:${jdHash(body)}`, company, title, source: body, body, start, sourceKey };
      });
    });
  });
}
function activeJd() { return state.jdUnits.find((unit) => unit.id === state.activeJdId); }
function updatePromptPreview() {
  const global = $("promptGlobalText").value.trim();
  const job = $("promptJobText").value.trim();
  const source = activeJd()?.source || "尚无可用 JD。请先同步校友 JD 表。";
  $("promptCombined").textContent = [`【公共提示词】\n${global}`, `【JD 专属提示词】\n${job || "（未设置）"}`, `【飞书 JD 原文】\n${source}`].join("\n\n");
}
function selectPromptJd(id) {
  state.activeJdId = id;
  $("promptJobSelect").value = id || "";
  $("promptJobText").disabled = !id;
  $("promptJobText").value = id ? (readPrompt(`ar-match-job-prompt:${id}`) || "") : "";
  $("promptJdSource").textContent = activeJd()?.source || "尚无可用 JD。请先同步校友 JD 表。";
  $("promptSplitPanel").hidden = true;
  $("promptSplitMarker").value = "";
  $("promptSplitStatus").textContent = "";
  updatePromptPreview();
}
function populateJdSelector() {
  const selector = $("promptJobSelect");
  selector.replaceChildren(...(state.jdUnits.length ? state.jdUnits.map((unit) => new Option(`${unit.company} · ${unit.title}`, unit.id)) : [new Option("暂无可用 JD", "")]));
  selector.disabled = !state.jdUnits.length;
}
function preparePrompt() {
  const legacy = readPrompt("ar-match-prompt");
  $("promptGlobalText").value = readPrompt("ar-match-global-prompt") ?? (legacy ? legacy.replace(/\n岗位需求：\{\{岗位需求\}\}\s*$/, "") : DEFAULT_GLOBAL_PROMPT);
  state.jdUnits = buildJdUnits();
  populateJdSelector();
  selectPromptJd(state.jdUnits.some((unit) => unit.id === state.activeJdId) ? state.activeJdId : state.jdUnits[0]?.id || null);
  $("promptSaveStatus").textContent = "修改仅保存在本机浏览器";
  state.promptInitialized = true;
}
function openPrompt() {
  showView("ai", "navAI", "promptDialog");
  $("promptJobSelect").focus({ preventScroll: true });
}
function savePrompt() {
  try {
    localStorage.setItem("ar-match-global-prompt", $("promptGlobalText").value);
    if (state.activeJdId) localStorage.setItem(`ar-match-job-prompt:${state.activeJdId}`, $("promptJobText").value);
    $("promptSaveStatus").textContent = "已保存在此浏览器";
  } catch { $("promptSaveStatus").textContent = "保存失败，请检查浏览器存储设置"; }
}
function splitCurrentJd() {
  const unit = activeJd();
  const marker = $("promptSplitMarker").value.trim();
  const status = $("promptSplitStatus");
  if (!unit || !marker) { status.textContent = "请先选择 JD 并填写下一条岗位的开头文字。"; return; }
  const localIndex = unit.body.indexOf(marker);
  if (localIndex <= 0 || localIndex !== unit.body.lastIndexOf(marker)) { status.textContent = "这段文字需要在当前 JD 中只出现一次，并且不能是开头。"; return; }
  const raw = textOf(field((table("job", false)?.records || []).find((record) => unit.sourceKey.startsWith(`${record.record_id}:`)), JOB_FIELDS[Number(unit.sourceKey.split(":").at(-1))])).trim();
  if (raw.indexOf(marker) !== raw.lastIndexOf(marker)) { status.textContent = "这段文字在原字段中出现多次，请换一段更独特的文字。"; return; }
  savePrompt(false);
  const key = `ar-jd-cuts:${unit.sourceKey}`;
  try {
    const markers = JSON.parse(readPrompt(key) || "[]");
    localStorage.setItem(key, JSON.stringify([...new Set([...markers, marker])]));
    state.jdUnits = buildJdUnits();
    populateJdSelector();
    const next = state.jdUnits.find((item) => item.sourceKey === unit.sourceKey && item.body.startsWith(marker));
    selectPromptJd(next?.id || unit.id);
    $("promptSplitPanel").hidden = false;
    status.textContent = "已拆分成独立 JD；原文未修改。";
  } catch { status.textContent = "拆分设置未能保存到浏览器。"; }
}
function aiStatus(message, error = false) {
  $("aiConfigStatus").textContent = message;
  $("aiConfigStatus").classList.toggle("error", error);
}
function fillModelSelect(config) {
  const select = $("aiModelSelect");
  const models = [...new Set([...(config.models || []), config.model].filter(Boolean))];
  select.replaceChildren(new Option("请选择模型", ""), ...models.map((id) => new Option(id, id)));
  select.value = config.model || "";
}
const TAG_CONCURRENCY_KEY = "ar-tag-concurrency";
function effectiveTagConcurrency(config) {
  try {
    const saved = Number(localStorage.getItem(TAG_CONCURRENCY_KEY));
    if (Number.isInteger(saved) && saved >= 1 && saved <= 10) return saved;
  } catch { /* Use the server setting. */ }
  const serverValue = config.max_concurrency;
  return Number.isInteger(serverValue) && serverValue >= 1 && serverValue <= 10 ? serverValue : 3;
}
function showAiConfig(config) {
  state.aiConfig = { ...config, max_concurrency: effectiveTagConcurrency(config) };
  $("aiBaseUrl").value = config.base_url || "";
  $("aiTagConcurrency").value = state.aiConfig.max_concurrency;
  $("aiApiKey").value = "";
  $("aiClearKey").checked = false;
  $("aiKeyState").textContent = config.has_key ? "已保存在本机" : "未配置";
  $("aiKeyState").classList.toggle("saved", Boolean(config.has_key));
  fillModelSelect(config);
  $("aiManualModel").hidden = true;
  $("aiManualModelToggle").textContent = "手动填写模型 ID";
}
async function loadAiConfig() {
  try {
    const response = await fetch("/api/ai-config", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    showAiConfig(result);
    aiStatus("连接设置仅保存在这台电脑上。");
  } catch (error) {
    aiStatus(`读取设置失败：${error.message}。请重新双击“打开AR网页.cmd”启动新版服务。`, true);
  }
}
async function saveAiConfig() {
  const button = $("aiConfigSave");
  const model = $("aiManualModel").hidden ? $("aiModelSelect").value : $("aiManualModel").value.trim();
  const maxConcurrency = Number($("aiTagConcurrency").value);
  if (!Number.isInteger(maxConcurrency) || maxConcurrency < 1 || maxConcurrency > 10) { aiStatus("AI 并发数请填写 1 到 10 的整数。", true); return false; }
  const data = { base_url: $("aiBaseUrl").value.trim(), model, api_key: $("aiApiKey").value, clear_key: $("aiClearKey").checked, max_concurrency: maxConcurrency };
  button.disabled = true;
  aiStatus("正在保存连接设置…");
  try {
    const response = await fetch("/api/ai-config", { method: "POST", headers: { "Content-Type": "application/json", "X-AR-Config": "1" }, body: JSON.stringify(data) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    let savedLocally = true;
    try { localStorage.setItem(TAG_CONCURRENCY_KEY, String(maxConcurrency)); }
    catch { savedLocally = false; }
    showAiConfig(result);
    if (result.max_concurrency == null) aiStatus(savedLocally ? "并发数已保存在当前浏览器；本地服务仍是旧版本，请重启服务以应用全部更新。" : "本地服务仍是旧版本，且浏览器未能保存并发数；请重启本地服务。", true);
    else aiStatus(savedLocally ? "连接设置已保存；尚未发起 AI 分析。" : "连接设置已保存；浏览器无法保存并发数，请检查浏览器存储设置。", !savedLocally);
    return true;
  } catch (error) {
    aiStatus(`保存失败：${error.message}`, true);
    return false;
  } finally { button.disabled = false; }
}
async function fetchAiModels() {
  if (!await saveAiConfig()) return;
  const button = $("aiFetchModels");
  button.disabled = true;
  aiStatus("正在读取模型目录…");
  try {
    const response = await fetch("/api/ai-models", { method: "POST", headers: { "X-AR-Config": "1" } });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    state.aiConfig.models = result.models;
    fillModelSelect(state.aiConfig);
    aiStatus(`已读取 ${result.models.length} 个模型。选择后请保存连接设置。`);
  } catch (error) { aiStatus(`获取模型列表失败：${error.message}。你也可以手动填写模型 ID。`, true); }
  finally { button.disabled = false; }
}
document.addEventListener("DOMContentLoaded", () => {
  $("todayLabel").textContent = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
  $("refreshButton").addEventListener("click", syncFromFeishu);
  $("candidateSearch").addEventListener("input", () => renderList("candidate"));
  $("jobSearch").addEventListener("input", () => renderList("job"));
  document.querySelectorAll("[data-candidate-tab]").forEach((button) => button.addEventListener("click", () => {
    state.candidateTab = button.dataset.candidateTab;
    document.querySelectorAll("[data-candidate-tab]").forEach((part) => { const active = part === button; part.classList.toggle("active", active); part.setAttribute("aria-pressed", String(active)); });
    $("candidateSearch").value = "";
    updateSummary();
    renderList("candidate");
  }));
  $("candidateList").addEventListener("click", (event) => { const card = event.target.closest(".record-card"); if (card) showDetail(state.visibleCandidates[Number(card.dataset.index)], "candidate"); });
  $("jobList").addEventListener("click", (event) => { const card = event.target.closest(".record-card"); if (card) showDetail(state.visibleJobs[Number(card.dataset.index)], "job"); });
  $("drawerClose").addEventListener("click", closeDetail);
  $("drawerBackdrop").addEventListener("click", closeDetail);
  $("flowCandidateNodes").addEventListener("click", (event) => { if (event.target.closest("[data-flow-kind]")) showView("directory", "navDirectory", "candidatesPanel"); });
  $("flowJobNodes").addEventListener("click", (event) => { if (event.target.closest("[data-flow-kind]")) showView("directory", "navDirectory", "jobsPanel"); });
  $("openPrompt").addEventListener("click", () => window.AR_MATCH.openLaunch());
  $("promptSave").addEventListener("click", savePrompt);
  $("promptJobSelect").addEventListener("change", (event) => { savePrompt(false); selectPromptJd(event.target.value); $("promptSaveStatus").textContent = "已切换岗位，专属提示词独立保存"; });
  $("promptGlobalText").addEventListener("input", () => { updatePromptPreview(); $("promptSaveStatus").textContent = "有未保存的修改"; });
  $("promptJobText").addEventListener("input", () => { updatePromptPreview(); $("promptSaveStatus").textContent = "有未保存的修改"; });
  $("promptSplitToggle").addEventListener("click", () => { $("promptSplitPanel").hidden = !$("promptSplitPanel").hidden; });
  $("promptSplitApply").addEventListener("click", splitCurrentJd);
  $("aiConfigForm").addEventListener("submit", (event) => { event.preventDefault(); saveAiConfig(); });
  $("aiFetchModels").addEventListener("click", fetchAiModels);
  $("aiManualModelToggle").addEventListener("click", () => {
    const input = $("aiManualModel");
    input.hidden = !input.hidden;
    if (!input.hidden) { input.value = $("aiModelSelect").value; input.focus(); }
    $("aiManualModelToggle").textContent = input.hidden ? "手动填写模型 ID" : "返回模型列表选择";
  });
  $("aiKeyToggle").addEventListener("click", () => { const input = $("aiApiKey"); input.type = input.type === "password" ? "text" : "password"; $("aiKeyToggle").textContent = input.type === "password" ? "显示" : "隐藏"; });
  $("aiClearKey").addEventListener("change", () => { if ($("aiClearKey").checked) $("aiApiKey").value = ""; });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("detailDrawer").classList.contains("open")) closeDetail(); });
  setupNavigation();
  loadCatalog();
  loadAiConfig();
});
