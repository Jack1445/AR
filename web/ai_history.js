/* Local AI request history. All prompt and response text is inserted as text. */
const aiHistory = { items: [], selected: null, hasMore: false, loading: false, version: 0 };
const historyKinds = { candidate_tag: "候选人打标签", job_tag: "JD 打标签", evaluation: "深度评估" };
const historyStatuses = { running: "进行中", success: "已回复", failed: "失败" };

function historyTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function historyText(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function renderHistoryList() {
  const list = document.getElementById("aiHistoryList");
  list.replaceChildren();
  if (!aiHistory.items.length) list.append(historyText("p", "ai-history-empty", "暂无分析记录。发起打标签或深度评估后会显示在这里。"));
  for (const item of aiHistory.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ai-history-item";
    button.classList.toggle("active", item.id === aiHistory.selected);
    button.setAttribute("aria-pressed", String(item.id === aiHistory.selected));
    button.append(
      historyText("span", "ai-history-kind", historyKinds[item.kind] || item.kind),
      historyText("strong", "ai-history-target", item.target_label || item.target_id),
      historyText("span", "ai-history-meta", `${historyTime(item.started_at)} · ${historyStatuses[item.status] || item.status}`),
    );
    button.addEventListener("click", () => showHistoryDetail(item.id));
    list.append(button);
  }
  document.getElementById("aiHistoryMore").hidden = !aiHistory.hasMore;
}

function historySection(title, value) {
  const section = document.createElement("section");
  section.className = "ai-history-section";
  const heading = document.createElement("div");
  heading.className = "ai-history-section-head";
  heading.append(historyText("h4", "", title));
  const copy = historyText("button", "match-outline-button", "复制");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(value); copy.textContent = "已复制"; }
    catch { copy.textContent = "复制失败"; }
  });
  heading.append(copy);
  section.append(heading, historyText("pre", "ai-history-pre", value || "（空）"));
  return section;
}

async function showHistoryDetail(id) {
  aiHistory.selected = id;
  renderHistoryList();
  const detail = document.getElementById("aiHistoryDetail");
  detail.replaceChildren(historyText("p", "ai-history-empty", "正在读取记录…"));
  try {
    const response = await fetch(`/api/ai-history/${id}`, { cache: "no-store" });
    const item = await response.json();
    if (!response.ok) throw new Error(item.error || `HTTP ${response.status}`);
    if (aiHistory.selected !== id) return;
    const heading = document.createElement("div");
    heading.className = "ai-history-detail-head";
    heading.append(historyText("span", "ai-history-kind", historyKinds[item.kind] || item.kind), historyText("h3", "", item.target_label || item.target_id));
    const meta = historyText("p", "ai-history-detail-meta", `发起：${historyTime(item.started_at)} · 完成：${historyTime(item.finished_at)} · ${item.model} · ${historyStatuses[item.status] || item.status}${item.elapsed_seconds == null ? "" : ` · ${item.elapsed_seconds} 秒`}`);
    detail.replaceChildren(heading, meta);
    if (item.error) detail.append(historyText("p", "ai-history-error", item.error));
    detail.append(historySection("系统提示词（实际发送）", item.system_prompt), historySection("用户提示词与资料（实际发送）", item.user_prompt), historySection("模型原始回复", item.raw_response));
  } catch (error) {
    if (aiHistory.selected === id) detail.replaceChildren(historyText("p", "ai-history-error", `读取失败：${error.message}`));
  }
}

async function loadAiHistory(reset = false) {
  if (aiHistory.loading) return;
  aiHistory.loading = true;
  const version = ++aiHistory.version;
  const status = document.getElementById("aiHistoryStatus");
  status.textContent = "正在读取本地分析记录…";
  try {
    const params = new URLSearchParams();
    const kind = document.getElementById("aiHistoryKind").value;
    if (kind) params.set("kind", kind);
    if (!reset && aiHistory.items.length) params.set("before", String(aiHistory.items.at(-1).id));
    const response = await fetch(`/api/ai-history?${params}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    if (version !== aiHistory.version) return;
    aiHistory.items = reset ? data.items : [...aiHistory.items, ...data.items];
    aiHistory.hasMore = data.has_more;
    if (reset) aiHistory.selected = null;
    renderHistoryList();
    status.textContent = aiHistory.items.length ? `已显示 ${aiHistory.items.length} 条记录` : "暂无记录";
    if (reset && aiHistory.items.length) showHistoryDetail(aiHistory.items[0].id);
    else if (reset) document.getElementById("aiHistoryDetail").replaceChildren(historyText("p", "ai-history-empty", "发起打标签或深度评估后，记录会显示在这里。"));
  } catch (error) { status.textContent = `读取失败：${error.message}`; }
  finally { aiHistory.loading = false; }
}

window.AR_AI_HISTORY = { load: loadAiHistory };
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("aiHistoryRefresh").addEventListener("click", () => loadAiHistory(true));
  document.getElementById("aiHistoryKind").addEventListener("change", () => loadAiHistory(true));
  document.getElementById("aiHistoryMore").addEventListener("click", () => loadAiHistory(false));
});
