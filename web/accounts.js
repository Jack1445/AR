(() => {
  const byId = (id) => document.getElementById(id);
  const html = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const accountState = { items: [], role: "all", query: "", loaded: false };

  function accountDate(value) {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function roleLabel(role) { return role === "candidate" ? "候选人" : "校友"; }
  function relatedLabel(item) {
    if (item.role === "candidate") return `${item.linked.recommendations} 条推荐`;
    return `${item.linked.jobs} 个 JD · ${item.linked.recommendations} 条反馈`;
  }
  function renderAccounts() {
    const query = accountState.query.toLocaleLowerCase("zh-CN");
    const items = accountState.items.filter((item) => (accountState.role === "all" || item.role === accountState.role) && (!query || [item.phone, item.name, item.detail].some((value) => String(value || "").toLocaleLowerCase("zh-CN").includes(query))));
    byId("candidateAccountCount").textContent = accountState.items.filter((item) => item.role === "candidate").length;
    byId("alumniAccountCount").textContent = accountState.items.filter((item) => item.role === "alumni").length;
    byId("accountRows").innerHTML = items.length ? items.map((item) => `<tr><td><strong>${html(item.phone)}</strong><small>${html(accountDate(item.updated_at))}</small></td><td><span class="account-role account-role-${item.role}">${roleLabel(item.role)}</span></td><td><strong>${html(item.name || "未完善")}</strong><small>${html(item.detail)}</small></td><td>${html(relatedLabel(item))}</td><td><span class="account-sync account-sync-${html(item.sync_state)}">${item.sync_state === "synced" ? "已同步" : item.sync_state === "pending" ? "待同步" : "同步异常"}</span></td><td><button type="button" class="account-delete-button" data-account-delete="${html(item.id)}" data-account-role="${item.role}">删除</button></td></tr>`).join("") : `<tr><td colspan="6"><div class="account-empty"><strong>没有匹配的账号</strong><span>调整类型或搜索条件后重试</span></div></td></tr>`;
  }
  async function loadAccounts(force = false) {
    if (accountState.loaded && !force) return renderAccounts();
    byId("accountStatus").textContent = "正在读取本地账号…";
    try {
      const response = await fetch("/api/accounts", { cache: "no-store" });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
      accountState.items = value.items || [];
      accountState.loaded = true;
      byId("accountStatus").textContent = `共 ${accountState.items.length} 个账号`;
      renderAccounts();
    } catch (error) {
      byId("accountStatus").textContent = `读取失败：${error.message}`;
      byId("accountRows").innerHTML = "";
    }
  }
  function showDataPage(name) {
    byId("dataCenterBlank").hidden = true;
    for (const page of ["Accounts", "Recommendations", "Sync", "Audit"]) byId(`data${page}Page`).hidden = page.toLocaleLowerCase() !== name;
    document.querySelectorAll("[data-data-page]").forEach((button) => button.classList.toggle("active", button.dataset.dataPage === name));
    if (name === "accounts") loadAccounts();
    if (name === "recommendations") window.AR_MATCH?.refreshRecommendations().catch(() => {});
  }
  function resetDataCenter() {
    byId("dataCenterBlank").hidden = false;
    for (const page of ["Accounts", "Recommendations", "Sync", "Audit"]) byId(`data${page}Page`).hidden = true;
    document.querySelectorAll("[data-data-page]").forEach((button) => button.classList.remove("active"));
  }
  function openCreate() {
    byId("accountCreateForm").reset();
    byId("accountCreateStatus").textContent = "";
    byId("accountCreateDialog").showModal();
    byId("accountCreatePhone").focus();
  }
  function openDelete(item) {
    byId("accountDeleteForm").reset();
    byId("accountDeleteId").value = item.id;
    byId("accountDeleteRole").value = item.role;
    byId("accountDeleteSummary").textContent = `${roleLabel(item.role)}账号 ${item.phone}`;
    byId("accountDeleteImpact").textContent = item.role === "alumni" ? `将同时删除名下 ${item.linked.jobs} 个 JD 和 ${item.linked.recommendations} 条推荐/反馈记录，并同步删除飞书对应记录。` : `将同时删除 ${item.linked.recommendations} 条推荐/反馈记录，并同步删除飞书对应记录。`;
    byId("accountDeleteStatus").textContent = "";
    byId("accountDeleteDialog").showModal();
    byId("accountDeletePhone").focus();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-data-page]").forEach((button) => button.addEventListener("click", () => showDataPage(button.dataset.dataPage)));
    byId("accountCreateOpen").addEventListener("click", openCreate);
    byId("accountRefresh").addEventListener("click", () => loadAccounts(true));
    byId("accountSearch").addEventListener("input", (event) => { accountState.query = event.target.value.trim(); renderAccounts(); });
    document.querySelectorAll("[data-account-role]").forEach((button) => {
      if (!button.closest(".account-role-filter")) return;
      button.addEventListener("click", () => { accountState.role = button.dataset.accountRole; document.querySelectorAll(".account-role-filter button").forEach((item) => item.classList.toggle("active", item === button)); renderAccounts(); });
    });
    document.querySelectorAll("[data-account-close]").forEach((button) => button.addEventListener("click", () => byId(button.dataset.accountClose).close()));
    byId("accountRows").addEventListener("click", (event) => {
      const button = event.target.closest("[data-account-delete]");
      if (!button) return;
      const item = accountState.items.find((entry) => entry.id === button.dataset.accountDelete && entry.role === button.dataset.accountRole);
      if (item) openDelete(item);
    });
    byId("accountCreateForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = event.submitter;
      if (submit) submit.disabled = true;
      byId("accountCreateStatus").textContent = "正在创建并写入飞书…";
      try {
        const response = await fetch("/api/accounts", { method: "POST", headers: { "Content-Type": "application/json", "X-AR-Accounts": "1" }, body: JSON.stringify({ role: byId("accountCreateRole").value, phone: byId("accountCreatePhone").value.trim(), password: byId("accountCreatePassword").value }) });
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
        byId("accountCreateDialog").close();
        await loadAccounts(true);
      } catch (error) { byId("accountCreateStatus").textContent = error.message; }
      finally { if (submit) submit.disabled = false; }
    });
    byId("accountDeleteForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = event.submitter;
      if (submit) submit.disabled = true;
      byId("accountDeleteStatus").textContent = "正在删除本地及飞书关联数据…";
      try {
        const role = byId("accountDeleteRole").value, id = byId("accountDeleteId").value, phone = byId("accountDeletePhone").value.trim();
        const response = await fetch(`/api/accounts/${encodeURIComponent(role)}/${encodeURIComponent(id)}?phone=${encodeURIComponent(phone)}`, { method: "DELETE", headers: { "X-AR-Accounts": "1" } });
        const value = await response.json();
        if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
        byId("accountDeleteDialog").close();
        await loadAccounts(true);
      } catch (error) { byId("accountDeleteStatus").textContent = error.message; }
      finally { if (submit) submit.disabled = false; }
    });
    resetDataCenter();
  });
  window.AR_ACCOUNTS = { resetDataCenter, load: loadAccounts };
})();
