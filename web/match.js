/* JD-first matching workspace. The browser never receives the AI API key. */
const POSITION_TAGS = ["技术研发", "产品经理", "设计", "运营", "市场&品牌&商务", "销售", "职能（人力、财会、法务、行政）", "内容&创意", "供应链&生产"];
const POSITION_CATEGORY = { candidate: "AI 评估岗位", job: "岗位方向" };
const MATCH_DEFAULT_RULES = {
  candidate: { categories: [{ name: "专业背景", tags: ["理工", "经管", "人文社科", "其他"] }, { name: "行业与技术方向", tags: ["LLM", "Agent", "具身智能", "数据分析", "机器人", "其他"] }, { name: POSITION_CATEGORY.candidate, tags: POSITION_TAGS }], instructions: "仅依据简历和文字描述中明确的能力、项目与工作经历打标签；AI 评估岗位不得引用候选人自己填写的意向岗位；不要根据姓名、性别或照片推断。" },
  job: { categories: [{ name: "专业背景", tags: ["理工", "经管", "人文社科", "其他"] }, { name: "行业与技术方向", tags: ["LLM", "Agent", "具身智能", "数据分析", "机器人", "其他"] }, { name: POSITION_CATEGORY.job, tags: POSITION_TAGS }], instructions: "依据岗位职责、必备条件和业务方向打标签；岗位方向只能使用统一的九类岗位标签；不要把加分项当作必备条件。" }
};
const matchUI = { job: null, selected: new Set(), filters: {}, records: [], recommendations: [], confirming: new Set(), data: { candidate_tags: {}, job_tags: {}, evaluations: {} }, hardFilters: {}, hardFilterReady: false, busy: false, tagStopRequested: false, tagAbortController: null, tagAbortControllers: new Set(), tagHideTimer: null, evalStopRequested: false, evalAbortControllers: new Set(), evalHideTimer: null, messageTimer: null, previousFocus: null, errors: {} };
const LEGACY_CATEGORY_NAMES = { education: "专业背景", domain: "行业与技术方向", role: "岗位方向" };

function normalizedTagRules(rules) {
  const output = structuredClone(rules);
  for (const kind of ["candidate", "job"]) {
    const desired = POSITION_CATEGORY[kind];
    const categories = Array.isArray(output[kind]?.categories) ? output[kind].categories : [];
    const positionIndex = categories.findIndex((category) => ["岗位方向", "AI评估岗位", "AI 评估岗位"].includes(category.name));
    const fixed = { name: desired, tags: [...POSITION_TAGS] };
    if (positionIndex >= 0) categories.splice(positionIndex, 1, fixed);
    else categories.push(fixed);
    output[kind].categories = categories.filter((category, index) => !(["岗位方向", "AI评估岗位", "AI 评估岗位"].includes(category.name) && index !== categories.indexOf(fixed)));
  }
  return output;
}
function tagRules() {
  try {
    const stored = JSON.parse(localStorage.getItem("ar-tag-rules") || "null");
    if (stored?.candidate && stored?.job) {
      if (Array.isArray(stored.candidate.categories) && Array.isArray(stored.job.categories)) return normalizedTagRules(stored);
      const migrated = {};
      for (const kind of ["candidate", "job"]) migrated[kind] = { categories: Object.entries(LEGACY_CATEGORY_NAMES).map(([key, name]) => ({ name, tags: Array.isArray(stored[kind][key]) ? stored[kind][key] : [] })), instructions: stored[kind].instructions || "" };
      return normalizedTagRules(migrated);
    }
  } catch { /* Use defaults. */ }
  return normalizedTagRules(MATCH_DEFAULT_RULES);
}
function addCategoryRow(kind, name = "", tags = []) {
  const row = document.createElement("div");
  row.className = "tag-category-row";
  const fixedPositionCategory = name === POSITION_CATEGORY[kind];
  const heading = document.createElement("div");
  heading.className = "tag-category-row-head";
  const nameInput = document.createElement("input");
  nameInput.className = "ai-field tag-category-name";
  nameInput.placeholder = "分类名称，例如：语言能力";
  nameInput.maxLength = 40;
  nameInput.value = name;
  nameInput.setAttribute("aria-label", "标签分类名称");
  nameInput.readOnly = fixedPositionCategory;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "tag-category-remove";
  remove.textContent = "删除分类";
  remove.disabled = fixedPositionCategory;
  if (fixedPositionCategory) remove.title = "岗位分类需与候选人意向岗位保持统一，不能删除";
  remove.addEventListener("click", () => row.remove());
  heading.append(nameInput, remove);
  const tagsInput = document.createElement("input");
  tagsInput.className = "ai-field tag-category-tags";
  tagsInput.placeholder = "可选标签，用逗号分隔";
  tagsInput.value = tags.join("、");
  tagsInput.setAttribute("aria-label", "此分类可用标签，用逗号分隔");
  tagsInput.readOnly = fixedPositionCategory;
  row.append(heading, tagsInput);
  $(kind === "candidate" ? "candidateCategoryEditor" : "jobCategoryEditor").append(row);
  return nameInput;
}
function writeRuleInputs() {
  const rules = tagRules();
  for (const kind of ["candidate", "job"]) {
    $(kind === "candidate" ? "candidateCategoryEditor" : "jobCategoryEditor").replaceChildren();
    for (const category of rules[kind].categories) addCategoryRow(kind, category.name, category.tags);
  }
  $("candidateTagInstructions").value = rules.candidate.instructions || "";
  $("jobTagInstructions").value = rules.job.instructions || "";
}
function saveTagRules() {
  const rules = {};
  for (const kind of ["candidate", "job"]) {
    rules[kind] = { categories: [] };
    const rows = [...$(kind === "candidate" ? "candidateCategoryEditor" : "jobCategoryEditor").querySelectorAll(".tag-category-row")];
    if (rows.length > 12) { $("tagRulesStatus").textContent = "每侧最多 12 个分类。"; return; }
    for (const row of rows) {
      const name = row.querySelector(".tag-category-name").value.trim();
      const tags = row.querySelector(".tag-category-tags").value.split(/[、,，;；\n]+/).map((item) => item.trim()).filter(Boolean);
      if (!name || name.length > 40 || rules[kind].categories.some((category) => category.name === name)) { $("tagRulesStatus").textContent = "分类名称不能为空、重复或超过 40 字。"; return; }
      if (tags.length > 40 || tags.some((tag) => tag.length > 40)) { $("tagRulesStatus").textContent = "每类最多 40 个标签，每个不超过 40 字。"; return; }
      rules[kind].categories.push({ name, tags: [...new Set(tags)] });
    }
    rules[kind].instructions = $(kind === "candidate" ? "candidateTagInstructions" : "jobTagInstructions").value.trim();
  }
  const normalized = normalizedTagRules(rules);
  try { localStorage.setItem("ar-tag-rules", JSON.stringify(normalized)); $("tagRulesStatus").textContent = "标签规则已保存；岗位标签已统一为九类标准词，规则变化后会重新分析。"; writeRuleInputs(); renderFilters(); }
  catch { $("tagRulesStatus").textContent = "无法保存标签规则，请检查浏览器存储设置。"; }
}
function matchProgress(message, error = false, sticky = false) {
  const target = $("matchProgress");
  const refresh = $("matchRefreshStaleData");
  clearTimeout(matchUI.messageTimer);
  $("matchProgressText").textContent = message;
  refresh.hidden = !message.includes("JD 原文与本地快照不符");
  refresh.disabled = false;
  refresh.textContent = "刷新数据";
  target.classList.toggle("error", error);
  target.hidden = !message;
  if (message && !sticky) matchUI.messageTimer = setTimeout(() => { target.hidden = true; refresh.hidden = true; }, 5000);
}
function sameJobRecord(left, right) {
  return !!left && !!right && (left.sourceKey === right.sourceKey || left.id === right.id);
}
async function refreshStaleJobData() {
  if (!matchUI.job || matchUI.busy) return;
  const refresh = $("matchRefreshStaleData");
  const previous = matchUI.job;
  refresh.disabled = true;
  refresh.textContent = "正在刷新…";
  clearTimeout(matchUI.messageTimer);
  try {
    await loadCatalog();
    const updated = buildJdUnits().find((unit) => sameJobRecord(unit, previous));
    if (!updated) throw new Error("当前岗位已停止招聘或已被删除，请点击“更换 JD”重新选择");
    matchUI.job = updated;
    matchUI.hardFilters = {};
    matchUI.hardFilterReady = false;
    $("matchJobLabel").textContent = `${updated.company} · ${updated.title}`;
    await loadMatchState();
    matchProgress("数据已刷新，已载入 SQL 中的最新 JD。请重新点击“AI 为此 JD 打标签”。", false);
  } catch (error) {
    matchProgress(`刷新数据失败：${error.message}`, true, true);
  }
}
function beginTagProgress(label, total) {
  matchUI.tagStopRequested = false;
  clearTimeout(matchUI.tagHideTimer);
  const panel = $("matchTagProgressPanel");
  panel.hidden = false;
  panel.open = true;
  $("matchTagProgressSummary").textContent = `${label} · 进行中`;
  $("matchTagProgressBar").max = Math.max(total, 1);
  $("matchTagProgressBar").value = 0;
  $("matchTagProgressFraction").textContent = `0 / ${total}`;
  $("matchTagProgressCurrent").textContent = "正在准备…";
  $("matchTagProgressLog").replaceChildren();
  $("matchStopTagging").disabled = false;
  $("matchChangeJob").disabled = true;
}
function updateTagProgress(done, total, message) {
  $("matchTagProgressBar").value = done;
  $("matchTagProgressFraction").textContent = `${done} / ${total}`;
  $("matchTagProgressCurrent").textContent = message;
  const item = document.createElement("li");
  item.textContent = message;
  $("matchTagProgressLog").prepend(item);
}
function endTagProgress(summary, error = false) {
  $("matchTagProgressSummary").textContent = summary;
  $("matchTagProgressCurrent").textContent = summary;
  $("matchStopTagging").disabled = true;
  $("matchChangeJob").disabled = false;
  if (error) return;
  if (matchUI.tagStopRequested) $("matchTagProgressPanel").hidden = true;
  else matchUI.tagHideTimer = setTimeout(() => { $("matchTagProgressPanel").hidden = true; }, 10000);
}
function beginEvalProgress(total) {
  matchUI.evalStopRequested = false;
  clearTimeout(matchUI.evalHideTimer);
  $("matchEvalProgressPanel").hidden = false;
  $("matchEvalProgressPanel").open = true;
  $("matchEvalProgressSummary").textContent = "评估进行中";
  $("matchEvalProgressBar").max = Math.max(total, 1);
  $("matchEvalProgressBar").value = 0;
  $("matchEvalProgressFraction").textContent = `0 / ${total}`;
  $("matchEvalProgressCurrent").textContent = "正在准备…";
  $("matchEvalProgressLog").replaceChildren();
  $("matchStopEvaluation").disabled = false;
  $("matchChangeJob").disabled = true;
}
function updateEvalProgress(done, total, message) {
  $("matchEvalProgressBar").value = done;
  $("matchEvalProgressFraction").textContent = `${done} / ${total}`;
  $("matchEvalProgressCurrent").textContent = message;
  const item = document.createElement("li");
  item.textContent = message;
  $("matchEvalProgressLog").prepend(item);
}
function endEvalProgress(summary) {
  $("matchEvalProgressSummary").textContent = summary;
  $("matchEvalProgressCurrent").textContent = summary;
  $("matchStopEvaluation").disabled = true;
  $("matchChangeJob").disabled = false;
  if (matchUI.evalStopRequested) $("matchEvalProgressPanel").hidden = true;
  else matchUI.evalHideTimer = setTimeout(() => { $("matchEvalProgressPanel").hidden = true; }, 10000);
}
async function matchRequest(path, payload, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const limit = path === "/api/match-tag" || path === "/api/match-evaluate" ? 105000 : 30000;
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, limit);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  try {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-AR-Match": "1" }, body: JSON.stringify(payload), signal: controller.signal });
    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.includes("application/json")) {
      if (response.status === 403) throw new Error("AR 服务拒绝了请求，可能仍在运行旧版。请关闭旧服务窗口，再运行“打开AR网页.cmd”重启。");
      throw new Error(`AR 服务返回了非 JSON 响应（HTTP ${response.status}），请重启本地服务。`);
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  } catch (error) {
    if (timedOut) throw new Error("AI 请求等待超时，请检查 AI 管理中的 API 连接后重试");
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
async function runBoundedQueue(items, limit, shouldStop, processItem) {
  let nextIndex = 0;
  async function worker() {
    while (!shouldStop()) {
      const index = nextIndex++;
      if (index >= items.length) return;
      await processItem(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(items.length, limit) }, worker));
}
async function loadMatchState() {
  try {
    const response = await fetch("/api/match-state", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    matchUI.data = result;
    await loadRecommendations(false);
    renderMatch();
  } catch (error) { matchProgress(`读取匹配记录失败：${error.message}。请通过启动脚本打开新版网页。`, true); }
}
async function loadRecommendations(updateDataCenter = true) {
  try {
    const response = await fetch("/api/recommendations", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    matchUI.recommendations = result.items || [];
    renderMatch();
    if (updateDataCenter) renderRecommendationCenter();
  } catch (error) {
    if (updateDataCenter) $("dataRecommendationsStatus").textContent = `读取推荐状态失败：${error.message}`;
    throw error;
  }
}
function renderRecommendationCenter() {
  const host = $("dataRecommendationsList");
  if (!host) return;
  const jobs = new Map(currentJobRecords().map((record) => {
    const body = textOf(field(record, "AR_JD正文")).trim();
    const job = { id: `${record.record_id}:2:${jdHash(body)}`, title: compact(field(record, "AR_岗位名称"), 70) || "岗位", company: compact(field(record, "AR_企业名称"), 55) || "校友企业" };
    return [job.id, job];
  }));
  for (const row of matchUI.recommendations) if (!jobs.has(row.job_id)) jobs.set(row.job_id, { id: row.job_id, title: "历史岗位", company: "" });
  $("dataRecommendationsStatus").textContent = `更新于 ${new Date().toLocaleString("zh-CN")} · 共 ${matchUI.recommendations.length} 位已确认推荐`;
  host.innerHTML = [...jobs.values()].map((job) => {
    const rows = matchUI.recommendations.filter((row) => row.job_id === job.id);
    const interested = rows.filter((row) => row.interest === "感兴趣").length;
    const hired = rows.filter((row) => row.status === "录用").length;
    return `<section class="data-job-group"><div class="data-job-heading"><div><h3>${escapeHtml(job.company ? `${job.company} · ${job.title}` : job.title)}</h3><small>已推荐 ${rows.length} 人 · 感兴趣 ${interested} 人 · 已录用 ${hired} 人</small></div></div>${rows.length ? `<div class="data-job-people">${rows.map((row) => `<div class="data-job-person"><strong>${escapeHtml(row.candidate_name || row.candidate_id)}</strong><span>${escapeHtml(row.status === "待反馈" ? "待反馈" : row.status === "面试中" ? "感兴趣 · 面试中" : row.status)}</span></div>`).join("")}</div>` : `<p class="data-job-empty">尚未确认推荐候选人</p>`}</section>`;
  }).join("") || `<p class="data-job-empty">暂无 JD。请先同步校友岗位。</p>`;
}
async function confirmCandidate(candidateId) {
  if (!matchUI.job || matchUI.busy || matchUI.confirming.has(candidateId)) return;
  if (recommendationHistory(candidateId).some((row) => row.status === "不感兴趣")) { matchProgress("校友已反馈不感兴趣，不能再次推荐给此 JD。", true); return; }
  matchUI.confirming.add(candidateId);
  renderMatch();
  matchProgress("正在确认推荐，请稍候…", false, true);
  try {
    const result = await matchRequest("/api/match-confirm", { job_id: matchUI.job.id, jd_text: matchUI.job.source, candidate_id: candidateId });
    if (!result.published) throw new Error(result.reason || "推荐未成功");
    matchUI.selected.delete(candidateId);
    try {
      await loadRecommendations();
      matchProgress(result.cached ? "这位候选人此前已推荐给当前 JD。" : "已确认推荐，校友端现在可以看到这位候选人。");
    } catch { matchProgress("推荐已保存；刷新推荐状态失败，请稍后刷新页面。", true); }
  } catch (error) { matchProgress(`确认推荐失败：${error.message}`, true); }
  finally { matchUI.confirming.delete(candidateId); renderMatch(); }
}
function fillLaunchJobs() {
  state.jdUnits = buildJdUnits();
  const select = $("matchLaunchJob");
  select.replaceChildren(...(state.jdUnits.length ? state.jdUnits.map((unit) => new Option(`${unit.company} · ${unit.title}`, unit.id)) : [new Option("暂无可用 JD", "")]));
  select.disabled = !state.jdUnits.length;
  select.value = matchUI.job && state.jdUnits.some((item) => item.id === matchUI.job.id) ? matchUI.job.id : state.jdUnits[0]?.id || "";
  select.dataset.previousJob = select.value;
  $("matchLaunchStart").disabled = !state.jdUnits.length;
  updateLaunchSummary();
}
function updateLaunchSummary() {
  const unit = state.jdUnits.find((item) => item.id === $("matchLaunchJob").value);
  $("matchLaunchGlobal").value = readPrompt("ar-match-global-prompt") ?? DEFAULT_GLOBAL_PROMPT;
  $("matchLaunchSpecific").value = unit ? (readPrompt(`ar-match-job-prompt:${unit.id}`) || "") : "";
  $("matchLaunchSummary").textContent = unit ? compact(unit.source, 260) : "先同步校友 JD 表，再选择具体岗位。";
  $("matchLaunchSaveStatus").textContent = "";
}
function saveLaunchPrompts(jobId) {
  try {
    localStorage.setItem("ar-match-global-prompt", $("matchLaunchGlobal").value);
    localStorage.setItem(`ar-match-job-prompt:${jobId}`, $("matchLaunchSpecific").value);
    $("matchLaunchSaveStatus").textContent = "已保存";
    return true;
  } catch {
    $("matchLaunchSaveStatus").textContent = "保存失败，请检查浏览器存储设置";
    return false;
  }
}
function openLaunch() {
  if (matchUI.busy) { showView("match", "navMatch"); return; }
  matchUI.previousFocus = document.activeElement;
  fillLaunchJobs();
  $("matchLaunchBackdrop").hidden = false;
  $("matchLaunchModal").hidden = false;
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => $("matchLaunchBackdrop").classList.add("visible"));
  $("matchLaunchJob").focus();
}
function openWorkspace() {
  if (matchUI.job) showView("match", "navMatch");
  else { showView("match", "navMatch"); openLaunch(); }
}
function closeLaunch() {
  $("matchLaunchBackdrop").classList.remove("visible");
  $("matchLaunchBackdrop").hidden = true;
  $("matchLaunchModal").hidden = true;
  document.body.style.overflow = "";
  matchUI.previousFocus?.focus();
}
async function startMatch() {
  const job = state.jdUnits.find((item) => item.id === $("matchLaunchJob").value);
  if (!job || !saveLaunchPrompts(job.id)) return;
  matchUI.job = job;
  matchUI.hardFilters = {};
  matchUI.hardFilterReady = false;
  matchUI.selected.clear();
  for (const key of Object.keys(matchUI.filters)) matchUI.filters[key].clear();
  closeLaunch();
  showView("match", "navMatch");
  $("matchJobLabel").textContent = `${matchUI.job.company} · ${matchUI.job.title}`;
  renderFilters();
  await loadMatchState();
  if (state.aiConfig?.base_url && state.aiConfig?.model) {
    await tagJob();
    if (matchUI.data.job_tags[matchUI.job.id] && !matchUI.tagStopRequested) {
      await tagCandidates();
      if (!matchUI.tagStopRequested) {
        await refreshHardFilters();
        applyJobFilters();
      }
    }
  } else {
    await refreshHardFilters(false);
    matchProgress("硬性匹配需要统一的岗位标签；如标签尚未生成，请先在 AI 管理页配置 API 和模型。", true);
  }
}
function renderFilters() {
  const categories = tagRules().candidate.categories;
  const active = {};
  for (const category of categories) active[category.name] = matchUI.filters[category.name] || new Set();
  matchUI.filters = active;
  $("matchFilterGroups").innerHTML = categories.map(({ name, tags }) => `<fieldset class="match-filter-group"><legend>${escapeHtml(name)}</legend>${tags.map((tag) => `<label class="match-filter-chip"><input type="checkbox" data-filter-category="${escapeHtml(name)}" value="${escapeHtml(tag)}" ${matchUI.filters[name].has(tag) ? "checked" : ""}><span>${escapeHtml(tag)}</span></label>`).join("")}</fieldset>`).join("");
  renderMatch();
}
function candidateRecords() {
  return currentCandidateRecords().filter(record => textOf(field(record, "AR_推荐状态")) !== "停止");
}
async function refreshHardFilters(showMessage = true) {
  if (!matchUI.job) return;
  matchUI.hardFilterReady = false;
  renderMatch();
  try {
    const result = await matchRequest("/api/match-hard-filter", { job_id: matchUI.job.id, jd_text: matchUI.job.source, candidate_ids: candidateRecords().map((record) => record.record_id) });
    matchUI.hardFilters = result.results || {};
    matchUI.hardFilterReady = true;
    for (const id of [...matchUI.selected]) if (!matchUI.hardFilters[id]?.passed) matchUI.selected.delete(id);
    const total = candidateRecords().length;
    const passed = Object.values(matchUI.hardFilters).filter((item) => item.passed).length;
    if (showMessage) matchProgress(`硬性条件初筛完成：${passed}/${total} 人通过。未通过者不会进入 AI 深度评估。`, false, true);
  } catch (error) {
    matchUI.hardFilters = {};
    matchUI.hardFilterReady = false;
    matchProgress(`硬性条件初筛失败：${error.message}`, true, true);
  }
  renderMatch();
}
function filteredCandidates() {
  return candidateRecords().filter((record) => {
    if (!matchUI.hardFilterReady || !matchUI.hardFilters[record.record_id]?.passed) return false;
    const labels = matchUI.data.candidate_tags[record.record_id]?.tags || {};
    for (const [category, required] of Object.entries(matchUI.filters)) {
      if (required.size && !(labels[category] || []).some((tag) => required.has(tag))) return false;
    }
    return true;
  });
}
function tagPills(entry) {
  if (!entry) return `<span class="match-muted">尚未处理</span>`;
  const tags = Object.values(entry?.tags || {}).flat();
  return tags.length ? tags.slice(0, 7).map((tag) => `<span class="match-tag">${escapeHtml(tag)}</span>`).join("") : `<span class="match-muted">无明确标签</span>`;
}
function starsHtml(entry) {
  if (!entry) return `<span class="match-muted">待评估</span>`;
  return `<span class="match-stars" aria-label="${entry.stars} 星"><span>${"★".repeat(entry.stars)}</span><span class="match-stars-dim">${"★".repeat(5 - entry.stars)}</span></span><small>${escapeHtml(entry.model || "AI 评估")}</small>`;
}
function recommendationForStars(stars) {
  return stars >= 4 ? "推荐" : stars === 3 ? "谨慎推荐" : "不推荐";
}
function assessmentHtml(entry) {
  const assessment = entry?.assessment;
  if (!assessment || typeof assessment !== "object" || !assessment.schema_version) return escapeHtml(entry?.reason || "—");
  const label = recommendationForStars(Number(entry.stars));
  const legacy = Number(entry.stars) >= 3 ? assessment.advantages : assessment.risks;
  const details = Array.isArray(assessment.details) ? assessment.details : (Array.isArray(legacy) ? legacy : []);
  const title = Number(entry.stars) >= 3 ? "匹配依据" : "低分原因";
  const items = details.map((item) => `<li><b>简历事实：</b>${escapeHtml(item.resume_evidence || "")}<br><b>对应JD：</b>${escapeHtml(item.jd_requirement || "")}<br>${escapeHtml(item.analysis || "")}</li>`).join("");
  return `<div class="match-assessment-summary"><b>【${label}】</b>${escapeHtml(assessment.summary || entry.summary || "")}</div><details class="match-assessment-detail"><summary>查看${title}</summary><section><strong>${title}</strong><ul>${items}</ul></section></details>`;
}
function recommendationHistory(candidateId) {
  if (!matchUI.job) return [];
  return matchUI.recommendations.filter((row) => row.candidate_id === candidateId && (row.job_id === matchUI.job.id || row.job_id.startsWith(`${matchUI.job.sourceKey}:`)));
}
function recommendationStatus(rows) {
  if (rows.some((row) => row.status === "不感兴趣")) return "不感兴趣";
  const latest = [...rows].sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""))[0];
  return latest?.status === "待反馈" ? "尚未反馈" : latest?.status === "面试中" ? "感兴趣 · 面试中" : latest?.status || "";
}
function selectedForRecommendation() {
  if (!matchUI.job) return [];
  const jobId = matchUI.job.id;
  return [...matchUI.selected].filter((candidateId) => matchUI.data.evaluations[`${jobId}|${candidateId}`] && !recommendationHistory(candidateId).some((row) => row.status === "不感兴趣" || row.job_id === jobId));
}
function hardDateLabel(value) {
  if (value === null || value === undefined || value === "") return "不限制（跳过此项）";
  if (typeof value === "number") {
    const date = new Date(value > 10000000000 ? value : value * 1000);
    if (!Number.isNaN(date.getTime())) return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }
  return textOf(value) || "格式无效";
}
function renderHardFilterPanel() {
  const host = $("matchHardCriteria");
  if (!host || !matchUI.job) return;
  const sourceId = matchUI.job.sourceKey?.split(":")[0] || "";
  const jobRecord = currentJobRecords().find((record) => record.record_id === sourceId);
  const jobTags = matchUI.data.job_tags[matchUI.job.id]?.tags || {};
  const criteria = [
    ["工作地点", jobRecord ? textOf(field(jobRecord, "工作地点")) : ""],
    ["出勤方式", jobRecord ? textOf(field(jobRecord, "出勤方式")) : ""],
    ["岗位类别", jobRecord ? textOf(field(jobRecord, "岗位类别")) : ""],
    ["岗位方向", textOf(jobTags[POSITION_CATEGORY.job])],
    ["最晚到岗", hardDateLabel(jobRecord ? field(jobRecord, "最晚到岗日期") : "")],
    ["每周到岗", jobRecord ? textOf(field(jobRecord, "每周最少到岗天数")) : ""],
  ];
  host.innerHTML = criteria.map(([label, value]) => `<div class="match-hard-criterion"><dt>${escapeHtml(label)}</dt><dd class="${value ? "" : "is-empty"}">${escapeHtml(value || (label === "岗位方向" ? "等待 JD 标签" : "未填写"))}</dd></div>`).join("");
  const total = candidateRecords().length;
  const failures = matchUI.hardFilterReady ? candidateRecords().filter((record) => !matchUI.hardFilters[record.record_id]?.passed) : [];
  const passed = matchUI.hardFilterReady ? total - failures.length : 0;
  $("matchHardSummary").textContent = matchUI.hardFilterReady ? `${passed}/${total} 人通过` : "等待标签完成";
  const details = $("matchHardFailures");
  details.hidden = !matchUI.hardFilterReady || !failures.length;
  if (failures.length) {
    $("matchHardFailuresSummary").textContent = `未通过 ${failures.length} 人 · 查看原因`;
    $("matchHardFailureList").innerHTML = failures.map((record) => {
      const failed = matchUI.hardFilters[record.record_id]?.failed || ["尚未完成检查"];
      return `<div class="match-hard-failure"><strong>${escapeHtml(candidateView(record).title)}</strong><span>${escapeHtml(failed.join("、"))}</span></div>`;
    }).join("");
  } else $("matchHardFailureList").replaceChildren();
}
function renderMatch() {
  if (!matchUI.job) return;
  renderHardFilterPanel();
  const rows = filteredCandidates();
  const selectable = rows.filter((record) => !recommendationHistory(record.record_id).some((row) => row.status === "不感兴趣"));
  for (const id of matchUI.selected) if (recommendationHistory(id).some((row) => row.status === "不感兴趣")) matchUI.selected.delete(id);
  matchUI.records = rows;
  $("matchCount").textContent = rows.length;
  $("matchSelectedCount").textContent = matchUI.selected.size;
  const ready = selectedForRecommendation();
  $("matchConfirmCount").textContent = ready.length;
  $("matchConfirmSelected").disabled = matchUI.busy || ready.length === 0;
  $("matchSelectAll").checked = selectable.length > 0 && selectable.every((record) => matchUI.selected.has(record.record_id));
  $("matchSelectAll").disabled = matchUI.busy || selectable.length === 0;
  $("matchEvaluate").disabled = matchUI.busy || matchUI.selected.size === 0;
  const jobTag = matchUI.data.job_tags[matchUI.job.id];
  $("matchJobTagStatus").textContent = jobTag ? `JD 标签：${Object.values(jobTag.tags || {}).flat().join(" · ") || "无明确标签"}` : "JD 尚未打标签";
  $("matchRows").innerHTML = rows.length ? rows.map((record) => {
    const id = record.record_id, view = candidateView(record), tag = matchUI.data.candidate_tags[id], assessment = matchUI.data.evaluations[`${matchUI.job.id}|${id}`];
    const history = recommendationHistory(id), rejected = history.some((row) => row.status === "不感兴趣");
    const recommended = history.some((row) => row.job_id === matchUI.job.id);
    const historyLabel = history.length ? `<span class="match-recommend-history ${rejected ? "match-recommend-rejected" : ""}">已推荐给此 JD ${history.length} 次 · ${escapeHtml(recommendationStatus(history))}</span>` : "";
    const action = rejected || recommended ? "" : assessment ? `<button type="button" class="match-outline-button match-confirm-button" data-match-confirm="${escapeHtml(id)}" ${matchUI.confirming.has(id) || matchUI.busy ? "disabled" : ""}>${matchUI.confirming.has(id) ? "确认中…" : "确认推荐"}</button>` : `<span class="match-muted">待评估</span>`;
    return `<tr><td><input type="checkbox" data-match-select="${escapeHtml(id)}" aria-label="选择${escapeHtml(view.title)}" ${matchUI.selected.has(id) ? "checked" : ""} ${matchUI.busy || rejected ? "disabled" : ""}></td><td><button type="button" class="match-person" data-match-detail="${escapeHtml(id)}"><span class="match-person-avatar">${escapeHtml(view.avatar)}</span><span><strong>${escapeHtml(view.title)}</strong><small>${escapeHtml(view.subtitle)}</small></span></button></td><td><div class="match-tag-list">${tagPills(tag)}</div></td><td>${starsHtml(assessment)}</td><td class="match-reason">${matchUI.errors[id] ? escapeHtml(matchUI.errors[id]) : assessmentHtml(assessment)}</td><td><div class="match-recommend-cell">${historyLabel}${action}</div></td></tr>`;
  }).join("") : `<tr><td colspan="6" class="match-empty">${matchUI.hardFilterReady ? "当前没有同时满足六项硬性条件的候选人。" : "正在核对工作地点、出勤方式、岗位类别、岗位方向、到岗日期与每周到岗天数…"}</td></tr>`;
}
function applyJobFilters() {
  if (!matchUI.job) return;
  const tags = matchUI.data.job_tags[matchUI.job.id]?.tags;
  if (!tags) { matchProgress("请先为当前 JD 打标签。", true); return; }
  const rules = tagRules().candidate;
  for (const category of rules.categories) {
    if (category.name === POSITION_CATEGORY.candidate) {
      matchUI.filters[category.name] = new Set();
      continue;
    }
    const jobCategory = category.name === POSITION_CATEGORY.candidate ? POSITION_CATEGORY.job : category.name;
    matchUI.filters[category.name] = new Set((tags[jobCategory] || []).filter((tag) => category.tags.includes(tag)));
  }
  renderFilters();
  matchProgress("已按 JD 标签设置初筛条件；你可以继续调整。", false);
}
async function tagJob() {
  if (!matchUI.job || matchUI.busy) return;
  matchUI.busy = true;
  matchUI.tagStopRequested = false;
  $("matchTagJob").disabled = true;
  const rules = tagRules().job;
  let started = false;
  matchProgress("正在检查这条 JD 是否需要重新打标签…");
  try {
    const plan = await matchRequest("/api/match-tag-plan", { kind: "job", id: matchUI.job.id, jd_text: matchUI.job.source, rules });
    if (!plan.pending_ids.length) {
      clearTimeout(matchUI.tagHideTimer);
      $("matchTagProgressPanel").hidden = true;
      matchProgress("这条 JD 的资料和规则都未变化，已跳过打标签。", false);
      return;
    }
    beginTagProgress("JD 标签", 1);
    started = true;
    matchProgress("正在为这条 JD 打标签…");
    matchUI.tagAbortController = new AbortController();
    const result = await matchRequest("/api/match-tag", { kind: "job", id: matchUI.job.id, jd_text: matchUI.job.source, rules }, matchUI.tagAbortController.signal);
    matchUI.data.job_tags[matchUI.job.id] = result;
    renderMatch();
    updateTagProgress(1, 1, result.cached ? "JD · 复用现有标签" : "JD · 已生成新标签");
    endTagProgress(matchUI.tagStopRequested ? "已停止；本条 JD 已完成" : "JD 标签检查完成");
    matchProgress(result.cached ? "已复用这条 JD 的现有标签。" : "JD 标签已生成并保存。可点击“按 JD 标签初筛”。");
  } catch (error) {
    if (matchUI.tagStopRequested && error.name === "AbortError") { endTagProgress("已停止 · JD 请求已取消等待"); matchProgress("已停止打标签；正在处理的服务端请求可能仍会完成。", false); }
    else { if (started) { updateTagProgress(1, 1, `JD · 失败：${error.message}`); endTagProgress("JD 标签失败", true); } matchProgress(`JD 打标签失败：${error.message}`, true, true); }
  }
  finally { matchUI.tagAbortController = null; matchUI.busy = false; $("matchTagJob").disabled = false; renderMatch(); }
}
async function tagCandidates() {
  if (matchUI.busy) return;
  matchUI.busy = true;
  matchUI.tagStopRequested = false;
  $("matchTagCandidates").disabled = true;
  const records = candidateRecords();
  const rules = tagRules().candidate;
  let pending = [];
  let skipped = 0;
  try {
    matchProgress("正在比对候选人资料和标签规则…");
    const plan = await matchRequest("/api/match-tag-plan", { kind: "candidate", rules });
    skipped = plan.cached_count;
    const byId = new Map(records.map((record) => [record.record_id, record]));
    pending = plan.pending_ids.map((id) => byId.get(id)).filter(Boolean);
    if (!pending.length) {
      clearTimeout(matchUI.tagHideTimer);
      $("matchTagProgressPanel").hidden = true;
      await loadMatchState();
      if (matchUI.data.job_tags[matchUI.job?.id]) await refreshHardFilters(false);
      matchProgress(`已跳过 ${skipped} 位资料和规则均未变化的候选人，无需重新打标签。`);
      return;
    }
  } catch (error) {
    matchProgress(`检查候选人标签失败：${error.message}`, true);
    return;
  } finally {
    if (!pending.length) { matchUI.busy = false; $("matchTagCandidates").disabled = false; renderMatch(); }
  }
  beginTagProgress("候选人标签", pending.length);
  const concurrency = Math.max(1, Math.min(10, Number(state.aiConfig?.max_concurrency) || 3));
  matchProgress(`发现 ${pending.length} 位需要打标签；并发 ${Math.min(concurrency, pending.length)} 项，跳过 ${skipped} 位未变化的候选人。`);
  let changed = 0, failed = 0, done = 0, fatalError = "";
  try { await runBoundedQueue(pending, concurrency, () => matchUI.tagStopRequested, async (record) => {
    const name = candidateView(record).title;
    const controller = new AbortController();
    matchUI.tagAbortControllers.add(controller);
    $("matchTagProgressCurrent").textContent = `正在等待 AI 返回：${name} · 已完成 ${done}/${pending.length}。单条请求最长约 90 秒，连接失败后会显示原因。`;
    let message = "";
    try {
      const result = await matchRequest("/api/match-tag", { kind: "candidate", id: record.record_id, rules }, controller.signal);
      matchUI.data.candidate_tags[record.record_id] = result;
      if (!result.cached) changed++;
      message = `${name} · ${result.cached ? "复用现有标签" : "已生成新标签"}`;
    } catch (error) {
      if (!(matchUI.tagStopRequested && error.name === "AbortError")) {
        failed++;
        message = `${name} · 失败：${error.message}`;
        if (!matchUI.tagStopRequested && /AI 服务返回 HTTP (401|403|429)\b|无法连接 AI 服务|AI 请求等待超时|AI 未返回约定的 JSON 格式/.test(error.message)) {
          fatalError = error.message;
          matchUI.tagStopRequested = true;
        }
      }
    } finally {
      matchUI.tagAbortControllers.delete(controller);
      if (message) {
        done++;
        updateTagProgress(done, pending.length, message);
        renderMatch();
      }
    }
  }); } catch (error) {
    fatalError = error.message;
  } finally {
    matchUI.busy = false;
    $("matchTagCandidates").disabled = false;
    renderMatch();
  }
  const summary = fatalError ? `服务错误，已停止 · ${done}/${pending.length}` : matchUI.tagStopRequested ? `已停止 · ${done}/${pending.length}` : failed ? `部分失败 · ${done}/${pending.length}` : `已完成 · ${done}/${pending.length}`;
  endTagProgress(summary, !!fatalError || failed > 0);
  if (!matchUI.tagStopRequested && matchUI.data.job_tags[matchUI.job?.id]) await refreshHardFilters(false);
  matchProgress(fatalError ? `打标签因 ${fatalError} 而停止；其余未发送的记录可稍后重试。` : `${matchUI.tagStopRequested ? "已停止" : "标签检查完成"}：新生成 ${changed} 份，失败 ${failed} 份，跳过未变化 ${skipped} 份。`, failed > 0, failed > 0);
}
function chooseEvaluationReuse(total, evaluated) {
  const dialog = $("matchEvaluationReuseDialog");
  $("matchEvaluationReuseSummary").textContent = `所选 ${total} 人中有 ${evaluated} 人已经完成 AI 评估。`;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(["reuse", "refresh"].includes(dialog.returnValue) ? dialog.returnValue : null), { once: true });
    dialog.showModal();
  });
}
async function evaluateSelected() {
  if (matchUI.busy || !matchUI.job || !matchUI.selected.size) return;
  const blocked = [...matchUI.selected].filter((id) => !matchUI.hardFilters[id]?.passed);
  if (blocked.length) {
    for (const id of blocked) matchUI.selected.delete(id);
    renderMatch();
    matchProgress("所选候选人中有未通过硬性条件的记录，已从本次 AI 评估移除。", true);
    return;
  }
  const jobId = matchUI.job.id;
  let ids = [...matchUI.selected];
  const evaluated = ids.filter((id) => matchUI.data.evaluations[`${jobId}|${id}`]);
  let force = false, reusedExisting = 0;
  if (evaluated.length) {
    const choice = await chooseEvaluationReuse(ids.length, evaluated.length);
    if (!choice) return;
    if (choice === "reuse") {
      const evaluatedSet = new Set(evaluated);
      ids = ids.filter((id) => !evaluatedSet.has(id));
      reusedExisting = evaluated.length;
      if (!ids.length) {
        matchProgress(`已沿用 ${reusedExisting} 人的已有评估，无需重新请求 AI。`);
        return;
      }
    } else {
      force = true;
    }
  }
  matchUI.busy = true;
  renderMatch();
  beginEvalProgress(ids.length);
  const common = readPrompt("ar-match-global-prompt") ?? DEFAULT_GLOBAL_PROMPT;
  const specific = readPrompt(`ar-match-job-prompt:${matchUI.job.id}`) || "";
  const jdText = matchUI.job.source;
  const concurrency = Math.max(1, Math.min(10, Number(state.aiConfig?.max_concurrency) || 3));
  matchProgress(`正在评估 ${ids.length} 位候选人；最多并发 ${Math.min(concurrency, ids.length)} 项。`, false, true);
  let completed = 0, reused = reusedExisting, failed = 0, done = 0, interrupted = "";
  try { await runBoundedQueue(ids, concurrency, () => matchUI.evalStopRequested, async (id) => {
    const record = candidateRecords().find((item) => item.record_id === id);
    const name = record ? candidateView(record).title : id;
    const controller = new AbortController();
    matchUI.evalAbortControllers.add(controller);
    $("matchEvalProgressCurrent").textContent = `正在并发评估：${name} · 已完成 ${done}/${ids.length}`;
    let message = "";
    try {
      const result = await matchRequest("/api/match-evaluate", { job_id: jobId, jd_text: jdText, candidate_id: id, common_prompt: common, job_prompt: specific, force }, controller.signal);
      matchUI.data.evaluations[`${jobId}|${id}`] = result;
      delete matchUI.errors[id];
      result.cached ? reused++ : completed++;
      message = `${name} · ${result.cached ? "复用已有评分" : `${result.stars} 星，评估完成`} · 请确认是否推荐`;
    } catch (error) {
      if (!(matchUI.evalStopRequested && error.name === "AbortError")) {
        matchUI.errors[id] = `评估失败：${error.message}`;
        failed++;
        message = `${name} · 失败：${error.message}`;
      }
    } finally {
      matchUI.evalAbortControllers.delete(controller);
      if (message) {
        done++;
        updateEvalProgress(done, ids.length, message);
        renderMatch();
      }
    }
  }); } catch (error) {
    failed++;
    interrupted = error.message;
  } finally {
    matchUI.busy = false;
    renderMatch();
  }
  endEvalProgress(matchUI.evalStopRequested ? `已停止 · ${done}/${ids.length}` : `已完成 · ${done}/${ids.length}`);
  matchProgress(interrupted ? `评估被中断：${interrupted}。可重新选择候选人重试。` : `${matchUI.evalStopRequested ? "已停止" : "评估完成"}：新分析 ${completed} 人，复用结果 ${reused} 人，失败 ${failed} 人。勾选已保留，可直接批量确认推荐。`, failed > 0);
}
async function confirmSelected() {
  if (matchUI.busy || !matchUI.job) return;
  const ids = selectedForRecommendation();
  if (!ids.length) { matchProgress("所选候选人中没有待确认的已评估记录。", true); return; }
  const job = matchUI.job;
  matchUI.busy = true;
  $("matchChangeJob").disabled = true;
  renderMatch();
  let succeeded = 0, failed = 0;
  try { for (const [index, id] of ids.entries()) {
    matchProgress(`正在确认推荐 ${index + 1}/${ids.length} 人…`, false, true);
    try {
      const result = await matchRequest("/api/match-confirm", { job_id: job.id, jd_text: job.source, candidate_id: id });
      if (!result.published) throw new Error(result.reason || "推荐未成功");
      succeeded++;
      matchUI.selected.delete(id);
      delete matchUI.errors[id];
    } catch (error) {
      failed++;
      matchUI.errors[id] = `推荐失败：${error.message}`;
    }
  } } finally {
    matchUI.busy = false;
    $("matchChangeJob").disabled = false;
    renderMatch();
  }
  try { await loadRecommendations(); } catch { matchProgress(`已保存 ${succeeded} 人；推荐状态暂时无法刷新。`, true); renderMatch(); return; }
  renderMatch();
  matchProgress(`批量推荐完成：成功 ${succeeded} 人，失败 ${failed} 人。${failed ? "失败的人仍保持勾选，可查看对应行并重试。" : ""}`, failed > 0);
}
function onCatalogUpdated() {
  if (matchUI.job) {
    const updated = buildJdUnits().find((unit) => sameJobRecord(unit, matchUI.job));
    if (updated) matchUI.job = updated;
    renderMatch();
  }
}
window.AR_MATCH = { openLaunch, openWorkspace, onCatalogUpdated, refreshRecommendations: loadRecommendations };
document.addEventListener("DOMContentLoaded", () => {
  writeRuleInputs();
  $("tagRulesSave").addEventListener("click", saveTagRules);
  for (const kind of ["candidate", "job"]) $(kind === "candidate" ? "candidateAddCategory" : "jobAddCategory").addEventListener("click", () => {
    const editor = $(kind === "candidate" ? "candidateCategoryEditor" : "jobCategoryEditor");
    if (editor.querySelectorAll(".tag-category-row").length >= 12) { $("tagRulesStatus").textContent = "每侧最多 12 个分类。"; return; }
    addCategoryRow(kind).focus();
    $("tagRulesStatus").textContent = "新增分类后请填写名称和标签，再保存规则。";
  });
  $("matchLaunchJob").addEventListener("change", (event) => {
    const previousId = event.target.dataset.previousJob;
    if (previousId) saveLaunchPrompts(previousId);
    updateLaunchSummary();
    event.target.dataset.previousJob = event.target.value;
  });
  $("matchLaunchClose").addEventListener("click", closeLaunch);
  $("matchLaunchBackdrop").addEventListener("click", closeLaunch);
  $("matchLaunchManage").addEventListener("click", () => { const id = $("matchLaunchJob").value; if (id && !saveLaunchPrompts(id)) return; closeLaunch(); showView("ai", "navAI"); preparePrompt(); if (id) selectPromptJd(id); });
  $("matchLaunchStart").addEventListener("click", startMatch);
  $("matchChangeJob").addEventListener("click", openLaunch);
  $("matchRefreshStaleData").addEventListener("click", refreshStaleJobData);
  $("matchTagJob").addEventListener("click", tagJob);
  $("matchTagCandidates").addEventListener("click", tagCandidates);
  $("matchStopTagging").addEventListener("click", () => { matchUI.tagStopRequested = true; matchUI.tagAbortController?.abort(); for (const controller of matchUI.tagAbortControllers) controller.abort(); $("matchStopTagging").disabled = true; $("matchTagProgressPanel").hidden = true; matchProgress("已停止打标签；后续记录不会继续处理。已发出的服务端请求可能仍会完成。", false); });
  $("matchEditTagRules").addEventListener("click", () => { showView("ai", "navAI", "tagRulesCard"); $("candidateCategoryEditor").querySelector(".tag-category-name")?.focus({ preventScroll: true }); });
  $("matchApplyJobTags").addEventListener("click", async () => { await refreshHardFilters(); applyJobFilters(); });
  $("matchResetFilters").addEventListener("click", () => { for (const category of Object.keys(matchUI.filters)) matchUI.filters[category].clear(); renderFilters(); });
  $("matchFilterGroups").addEventListener("change", (event) => { const input = event.target.closest("[data-filter-category]"); if (!input) return; const set = matchUI.filters[input.dataset.filterCategory]; input.checked ? set.add(input.value) : set.delete(input.value); renderMatch(); });
  $("matchSelectAll").addEventListener("change", (event) => { for (const record of matchUI.records) if (!recommendationHistory(record.record_id).some((row) => row.status === "不感兴趣")) event.target.checked ? matchUI.selected.add(record.record_id) : matchUI.selected.delete(record.record_id); renderMatch(); });
  $("matchRows").addEventListener("change", (event) => { const input = event.target.closest("[data-match-select]"); if (!input) return; if (!recommendationHistory(input.dataset.matchSelect).some((row) => row.status === "不感兴趣")) input.checked ? matchUI.selected.add(input.dataset.matchSelect) : matchUI.selected.delete(input.dataset.matchSelect); renderMatch(); });
  $("matchRows").addEventListener("click", (event) => { const confirm = event.target.closest("[data-match-confirm]"); if (confirm) { confirmCandidate(confirm.dataset.matchConfirm); return; } const button = event.target.closest("[data-match-detail]"); if (!button) return; const record = candidateRecords().find((item) => item.record_id === button.dataset.matchDetail); if (record) showDetail(record, "candidate"); });
  $("dataRecommendationsRefresh").addEventListener("click", () => loadRecommendations().catch(() => {}));
  setInterval(() => { if (!$("dataView").hidden || !$("matchView").hidden) loadRecommendations().catch(() => {}); }, 15000);
  $("matchEvaluate").addEventListener("click", evaluateSelected);
  $("matchConfirmSelected").addEventListener("click", confirmSelected);
  $("matchStopEvaluation").addEventListener("click", () => { matchUI.evalStopRequested = true; for (const controller of matchUI.evalAbortControllers) controller.abort(); $("matchStopEvaluation").disabled = true; $("matchEvalProgressPanel").hidden = true; matchProgress("已停止 AI 评估；未完成的候选人仍保持选中。已发出的服务端请求可能仍会完成。", false); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("matchLaunchModal").hidden) closeLaunch(); });
  loadMatchState();
});
