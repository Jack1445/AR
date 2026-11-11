/* JD-first matching workspace. The browser never receives the AI API key. */
const MATCH_DEFAULT_RULES = {
  candidate: { categories: [{ name: "专业背景", tags: ["理工", "经管", "人文社科", "其他"] }, { name: "行业与技术方向", tags: ["LLM", "Agent", "具身智能", "数据分析", "机器人", "其他"] }, { name: "岗位方向", tags: ["技术", "产品", "运营", "销售", "HR", "其他"] }], instructions: "仅依据简历和文字描述中明确的专业、项目与工作经历打标签；不要根据姓名、性别或照片推断。" },
  job: { categories: [{ name: "专业背景", tags: ["理工", "经管", "人文社科", "其他"] }, { name: "行业与技术方向", tags: ["LLM", "Agent", "具身智能", "数据分析", "机器人", "其他"] }, { name: "岗位方向", tags: ["技术", "产品", "运营", "销售", "HR", "其他"] }], instructions: "依据岗位职责、必备条件和业务方向打标签；不要把加分项当作必备条件。" }
};
const matchUI = { job: null, selected: new Set(), filters: {}, records: [], data: { candidate_tags: {}, job_tags: {}, evaluations: {} }, busy: false, tagStopRequested: false, tagAbortController: null, tagAbortControllers: new Set(), tagHideTimer: null, evalStopRequested: false, evalAbortControllers: new Set(), evalHideTimer: null, messageTimer: null, previousFocus: null, errors: {} };
const LEGACY_CATEGORY_NAMES = { education: "专业背景", domain: "行业与技术方向", role: "岗位方向" };

function tagRules() {
  try {
    const stored = JSON.parse(localStorage.getItem("ar-tag-rules") || "null");
    if (stored?.candidate && stored?.job) {
      if (Array.isArray(stored.candidate.categories) && Array.isArray(stored.job.categories)) return stored;
      const migrated = {};
      for (const kind of ["candidate", "job"]) migrated[kind] = { categories: Object.entries(LEGACY_CATEGORY_NAMES).map(([key, name]) => ({ name, tags: Array.isArray(stored[kind][key]) ? stored[kind][key] : [] })), instructions: stored[kind].instructions || "" };
      return migrated;
    }
  } catch { /* Use defaults. */ }
  return MATCH_DEFAULT_RULES;
}
function addCategoryRow(kind, name = "", tags = []) {
  const row = document.createElement("div");
  row.className = "tag-category-row";
  const heading = document.createElement("div");
  heading.className = "tag-category-row-head";
  const nameInput = document.createElement("input");
  nameInput.className = "ai-field tag-category-name";
  nameInput.placeholder = "分类名称，例如：语言能力";
  nameInput.maxLength = 40;
  nameInput.value = name;
  nameInput.setAttribute("aria-label", "标签分类名称");
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "tag-category-remove";
  remove.textContent = "删除分类";
  remove.addEventListener("click", () => row.remove());
  heading.append(nameInput, remove);
  const tagsInput = document.createElement("input");
  tagsInput.className = "ai-field tag-category-tags";
  tagsInput.placeholder = "可选标签，用逗号分隔";
  tagsInput.value = tags.join("、");
  tagsInput.setAttribute("aria-label", "此分类可用标签，用逗号分隔");
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
  try { localStorage.setItem("ar-tag-rules", JSON.stringify(rules)); $("tagRulesStatus").textContent = "标签规则已保存；规则变化后，下次打标签会重新分析。"; renderFilters(); }
  catch { $("tagRulesStatus").textContent = "无法保存标签规则，请检查浏览器存储设置。"; }
}
function matchProgress(message, error = false) {
  const target = $("matchProgress");
  clearTimeout(matchUI.messageTimer);
  target.textContent = message;
  target.classList.toggle("error", error);
  target.hidden = !message;
  if (message) matchUI.messageTimer = setTimeout(() => { target.hidden = true; }, 5000);
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
function endTagProgress(summary) {
  $("matchTagProgressSummary").textContent = summary;
  $("matchTagProgressCurrent").textContent = summary;
  $("matchStopTagging").disabled = true;
  $("matchChangeJob").disabled = false;
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
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-AR-Match": "1" }, body: JSON.stringify(payload), signal });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
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
    renderMatch();
  } catch (error) { matchProgress(`读取匹配记录失败：${error.message}。请通过启动脚本打开新版网页。`, true); }
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
  matchUI.selected.clear();
  for (const key of Object.keys(matchUI.filters)) matchUI.filters[key].clear();
  $("matchKeyword").value = "";
  closeLaunch();
  showView("match", "navMatch");
  $("matchJobLabel").textContent = `${matchUI.job.company} · ${matchUI.job.title}`;
  renderFilters();
  await loadMatchState();
  if (state.aiConfig?.base_url && state.aiConfig?.model) {
    await tagJob();
    if (matchUI.data.job_tags[matchUI.job.id] && !matchUI.tagStopRequested) {
      await tagCandidates();
      if (!matchUI.tagStopRequested) applyJobFilters();
    }
  } else matchProgress("可手动设置初筛条件；如需 AI 打标签，请先在 AI 管理页配置 API 和模型。", true);
}
function renderFilters() {
  const categories = tagRules().candidate.categories;
  const active = {};
  for (const category of categories) active[category.name] = matchUI.filters[category.name] || new Set();
  matchUI.filters = active;
  $("matchFilterGroups").innerHTML = categories.map(({ name, tags }) => `<fieldset class="match-filter-group"><legend>${escapeHtml(name)}</legend>${tags.map((tag) => `<label class="match-filter-chip"><input type="checkbox" data-filter-category="${escapeHtml(name)}" value="${escapeHtml(tag)}" ${matchUI.filters[name].has(tag) ? "checked" : ""}><span>${escapeHtml(tag)}</span></label>`).join("")}</fieldset>`).join("");
  renderMatch();
}
function candidateRecords() { return table("candidate", false)?.records || []; }
function filteredCandidates() {
  const query = $("matchKeyword").value.trim().toLocaleLowerCase("zh-CN");
  return candidateRecords().filter((record) => {
    const labels = matchUI.data.candidate_tags[record.record_id]?.tags || {};
    for (const [category, required] of Object.entries(matchUI.filters)) {
      if (required.size && !(labels[category] || []).some((tag) => required.has(tag))) return false;
    }
    if (!query) return true;
    const visible = [candidateView(record).title, ...Object.values(record.fields || {}).map(textOf), ...Object.values(labels).flat()].join(" ").toLocaleLowerCase("zh-CN");
    return visible.includes(query);
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
function renderMatch() {
  if (!matchUI.job) return;
  const rows = filteredCandidates();
  matchUI.records = rows;
  $("matchCount").textContent = rows.length;
  $("matchSelectedCount").textContent = matchUI.selected.size;
  $("matchSelectAll").checked = rows.length > 0 && rows.every((record) => matchUI.selected.has(record.record_id));
  $("matchSelectAll").disabled = matchUI.busy;
  $("matchEvaluate").disabled = matchUI.busy || matchUI.selected.size === 0;
  const jobTag = matchUI.data.job_tags[matchUI.job.id];
  $("matchJobTagStatus").textContent = jobTag ? `JD 标签：${Object.values(jobTag.tags || {}).flat().join(" · ") || "无明确标签"}` : "JD 尚未打标签";
  $("matchRows").innerHTML = rows.length ? rows.map((record) => {
    const id = record.record_id, view = candidateView(record), tag = matchUI.data.candidate_tags[id], assessment = matchUI.data.evaluations[`${matchUI.job.id}|${id}`];
    return `<tr><td><input type="checkbox" data-match-select="${escapeHtml(id)}" aria-label="选择${escapeHtml(view.title)}" ${matchUI.selected.has(id) ? "checked" : ""} ${matchUI.busy ? "disabled" : ""}></td><td><button type="button" class="match-person" data-match-detail="${escapeHtml(id)}"><span class="match-person-avatar">${escapeHtml(view.avatar)}</span><span><strong>${escapeHtml(view.title)}</strong><small>${escapeHtml(view.subtitle)}</small></span></button></td><td><div class="match-tag-list">${tagPills(tag)}</div></td><td>${starsHtml(assessment)}</td><td class="match-reason">${escapeHtml(matchUI.errors[id] || assessment?.reason || "—")}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="match-empty">当前条件下没有候选人。可调整标签条件，或先补齐候选人标签。</td></tr>`;
}
function applyJobFilters() {
  if (!matchUI.job) return;
  const tags = matchUI.data.job_tags[matchUI.job.id]?.tags;
  if (!tags) { matchProgress("请先为当前 JD 打标签。", true); return; }
  const rules = tagRules().candidate;
  for (const category of rules.categories) matchUI.filters[category.name] = new Set((tags[category.name] || []).filter((tag) => category.tags.includes(tag)));
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
    else { if (started) { updateTagProgress(1, 1, `JD · 失败：${error.message}`); endTagProgress("JD 标签失败"); } matchProgress(`JD 打标签失败：${error.message}`, true); }
  }
  finally { matchUI.tagAbortController = null; matchUI.busy = false; $("matchTagJob").disabled = false; }
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
      matchProgress(`已跳过 ${skipped} 位资料和规则均未变化的候选人，无需重新打标签。`);
      return;
    }
  } catch (error) {
    matchProgress(`检查候选人标签失败：${error.message}`, true);
    return;
  } finally {
    if (!pending.length) { matchUI.busy = false; $("matchTagCandidates").disabled = false; }
  }
  beginTagProgress("候选人标签", pending.length);
  const concurrency = Math.max(1, Math.min(10, Number(state.aiConfig?.max_concurrency) || 3));
  matchProgress(`发现 ${pending.length} 位需要打标签；并发 ${Math.min(concurrency, pending.length)} 项，跳过 ${skipped} 位未变化的候选人。`);
  let changed = 0, failed = 0, done = 0, fatalError = "";
  await runBoundedQueue(pending, concurrency, () => matchUI.tagStopRequested, async (record) => {
    const name = candidateView(record).title;
    const controller = new AbortController();
    matchUI.tagAbortControllers.add(controller);
    $("matchTagProgressCurrent").textContent = `正在并发处理：${name} · 已完成 ${done}/${pending.length}`;
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
        if (!matchUI.tagStopRequested && /AI 服务返回 HTTP (401|403|429)\b|无法连接 AI 服务|AI 未返回约定的 JSON 格式/.test(error.message)) {
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
  });
  matchUI.busy = false;
  $("matchTagCandidates").disabled = false;
  const summary = fatalError ? `服务错误，已停止 · ${done}/${pending.length}` : matchUI.tagStopRequested ? `已停止 · ${done}/${pending.length}` : `已完成 · ${done}/${pending.length}`;
  endTagProgress(summary);
  matchProgress(fatalError ? `打标签因 ${fatalError} 而停止；其余未发送的记录可稍后重试。` : `${matchUI.tagStopRequested ? "已停止" : "标签检查完成"}：新生成 ${changed} 份，失败 ${failed} 份，跳过未变化 ${skipped} 份。`, failed > 0);
}
async function evaluateSelected() {
  if (matchUI.busy || !matchUI.job || !matchUI.selected.size) return;
  matchUI.busy = true;
  renderMatch();
  const ids = [...matchUI.selected];
  beginEvalProgress(ids.length);
  const common = readPrompt("ar-match-global-prompt") ?? DEFAULT_GLOBAL_PROMPT;
  const specific = readPrompt(`ar-match-job-prompt:${matchUI.job.id}`) || "";
  const jobId = matchUI.job.id;
  const jdText = matchUI.job.source;
  const concurrency = Math.max(1, Math.min(10, Number(state.aiConfig?.max_concurrency) || 3));
  matchProgress(`正在评估 ${ids.length} 位候选人；最多并发 ${Math.min(concurrency, ids.length)} 项。`);
  let completed = 0, reused = 0, failed = 0, done = 0;
  await runBoundedQueue(ids, concurrency, () => matchUI.evalStopRequested, async (id) => {
    const record = candidateRecords().find((item) => item.record_id === id);
    const name = record ? candidateView(record).title : id;
    const controller = new AbortController();
    matchUI.evalAbortControllers.add(controller);
    $("matchEvalProgressCurrent").textContent = `正在并发评估：${name} · 已完成 ${done}/${ids.length}`;
    let message = "";
    try {
      const result = await matchRequest("/api/match-evaluate", { job_id: jobId, jd_text: jdText, candidate_id: id, common_prompt: common, job_prompt: specific }, controller.signal);
      matchUI.data.evaluations[`${jobId}|${id}`] = result;
      delete matchUI.errors[id];
      result.cached ? reused++ : completed++;
      matchUI.selected.delete(id);
      message = `${name} · ${result.cached ? "复用已有评分" : `${result.stars} 星，评估完成`}`;
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
  });
  matchUI.busy = false;
  renderMatch();
  endEvalProgress(matchUI.evalStopRequested ? `已停止 · ${done}/${ids.length}` : `已完成 · ${done}/${ids.length}`);
  matchProgress(`${matchUI.evalStopRequested ? "已停止" : "评估完成"}：新分析 ${completed} 人，复用结果 ${reused} 人，失败 ${failed} 人。${matchUI.selected.size ? `仍有 ${matchUI.selected.size} 人可继续评估。` : ""}`, failed > 0);
}
function onCatalogUpdated() {
  if (matchUI.job) {
    const updated = buildJdUnits().find((unit) => unit.id === matchUI.job.id);
    if (updated) matchUI.job = updated;
    renderMatch();
  }
}
window.AR_MATCH = { openLaunch, openWorkspace, onCatalogUpdated };
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
  $("matchTagJob").addEventListener("click", tagJob);
  $("matchTagCandidates").addEventListener("click", tagCandidates);
  $("matchStopTagging").addEventListener("click", () => { matchUI.tagStopRequested = true; matchUI.tagAbortController?.abort(); for (const controller of matchUI.tagAbortControllers) controller.abort(); $("matchStopTagging").disabled = true; $("matchTagProgressPanel").hidden = true; matchProgress("已停止打标签；后续记录不会继续处理。已发出的服务端请求可能仍会完成。", false); });
  $("matchEditTagRules").addEventListener("click", () => { showView("ai", "navAI", "tagRulesCard"); $("candidateCategoryEditor").querySelector(".tag-category-name")?.focus({ preventScroll: true }); });
  $("matchApplyJobTags").addEventListener("click", applyJobFilters);
  $("matchKeyword").addEventListener("input", renderMatch);
  $("matchResetFilters").addEventListener("click", () => { for (const category of Object.keys(matchUI.filters)) matchUI.filters[category].clear(); $("matchKeyword").value = ""; renderFilters(); });
  $("matchFilterGroups").addEventListener("change", (event) => { const input = event.target.closest("[data-filter-category]"); if (!input) return; const set = matchUI.filters[input.dataset.filterCategory]; input.checked ? set.add(input.value) : set.delete(input.value); renderMatch(); });
  $("matchSelectAll").addEventListener("change", (event) => { for (const record of matchUI.records) event.target.checked ? matchUI.selected.add(record.record_id) : matchUI.selected.delete(record.record_id); renderMatch(); });
  $("matchRows").addEventListener("change", (event) => { const input = event.target.closest("[data-match-select]"); if (!input) return; input.checked ? matchUI.selected.add(input.dataset.matchSelect) : matchUI.selected.delete(input.dataset.matchSelect); renderMatch(); });
  $("matchRows").addEventListener("click", (event) => { const button = event.target.closest("[data-match-detail]"); if (!button) return; const record = candidateRecords().find((item) => item.record_id === button.dataset.matchDetail); if (record) showDetail(record, "candidate"); });
  $("matchEvaluate").addEventListener("click", evaluateSelected);
  $("matchStopEvaluation").addEventListener("click", () => { matchUI.evalStopRequested = true; for (const controller of matchUI.evalAbortControllers) controller.abort(); $("matchStopEvaluation").disabled = true; $("matchEvalProgressPanel").hidden = true; matchProgress("已停止 AI 评估；未完成的候选人仍保持选中。已发出的服务端请求可能仍会完成。", false); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("matchLaunchModal").hidden) closeLaunch(); });
  loadMatchState();
});
