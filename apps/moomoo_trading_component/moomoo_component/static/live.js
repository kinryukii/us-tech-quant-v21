"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const embedded = new URLSearchParams(location.search).get("embed") === "1";
  document.body.classList.toggle("embedded", embedded);
  const getRoutes = new Set(["/api/live/state", "/api/live/token"]);
  const postRoutes = new Set(["/api/live/connect", "/api/live/select", "/api/live/refresh"]);
  const list = (value) => Array.isArray(value) ? value : [];
  const finite = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const moneyFormat = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const qtyFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 });
  const money = (value) => finite(value) ? moneyFormat.format(Number(value)) : "—";
  const qty = (value) => finite(value) ? qtyFormat.format(Number(value)) : "—";
  const text = (id, value) => { $(id).textContent = value == null ? "—" : String(value); };
  const node = (tag, cls, content) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (content !== undefined) el.textContent = String(content);
    return el;
  };
  const dateLabel = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
  };
  let state = null;
  let token = null;
  let busy = false;
  let refreshing = false;
  let stateFresh = false;
  let toastTimer;
  let accountSignature = "";

  function notify(message, error = false) {
    clearTimeout(toastTimer);
    text("toast", message);
    $("toast").className = `toast${error ? " error" : ""}`;
    $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7000 : 4500);
  }
  function showError(message) {
    text("error-banner", message || "");
    $("error-banner").hidden = !message;
  }
  async function request(path, body) {
    const isPost = body !== undefined;
    if (!(isPost ? postRoutes : getRoutes).has(path)) throw new Error("实盘页面只允许明确列出的只读账户接口。");
    const options = { method: isPost ? "POST" : "GET", credentials: "same-origin", cache: "no-store" };
    if (isPost) {
      if (!token) token = (await request("/api/live/token")).token;
      if (!token) throw new Error("无法获取实盘只读会话令牌，请刷新页面。");
      options.headers = { "Content-Type": "application/json", "X-CSRF-Token": token };
      options.body = JSON.stringify(body);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    options.signal = controller.signal;
    let response;
    try { response = await fetch(path, options); }
    catch (error) {
      throw new Error(error.name === "AbortError" ? "只读查询超时。请更新连接状态后重试。" : "本机组件服务不可达，请确认服务正在运行。");
    } finally { clearTimeout(timeout); }
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error("本机服务返回格式异常。"); }
    if (!response.ok || !result.ok) throw new Error(result.error || `只读请求失败（${response.status}）。`);
    return result.data;
  }
  function updateButtons() {
    const blocked = busy || !stateFresh;
    $("live-connect-btn").disabled = busy;
    $("live-port").disabled = busy;
    $("live-security-firm").disabled = busy;
    $("live-account").disabled = blocked || !state?.connected || !list(state?.accounts).length;
    const chosen = $("live-account").value;
    $("live-select-btn").disabled = blocked || !state?.connected || !chosen || chosen === String(state?.account_id || "");
    $("live-refresh-btn").disabled = blocked || !state?.connected || !state?.account_id || chosen !== String(state.account_id);
    $("state-refresh-btn").disabled = busy || refreshing;
    $("live-order-disabled").disabled = true;
  }
  async function refresh(silent = false) {
    if (refreshing) return;
    refreshing = true;
    updateButtons();
    try {
      const next = await request("/api/live/state");
      if (next.environment !== "REAL" || next.execution_enabled !== false || next.permission !== "LOCKED") throw new Error("实盘只读边界校验失败，页面已停止显示账户数据。");
      state = next;
      stateFresh = true;
      render();
      text("service-status", "已连接");
      text("last-update", `状态更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
      if (!silent) notify("连接状态已更新；账户快照须手动读取");
    } catch (error) {
      stateFresh = false;
      state = null;
      render();
      showError(error.message);
      text("service-status", "不可达");
      text("last-update", "连接状态不可用");
      if (!silent) notify(error.message, true);
    } finally { refreshing = false; updateButtons(); }
  }
  async function action(path, body, message) {
    if (busy) return;
    busy = true;
    updateButtons();
    let failure = "";
    try { await request(path, body); notify(message); }
    catch (error) { failure = error.message; notify(failure, true); }
    finally {
      await refresh(true);
      if (failure) showError(failure);
      busy = false;
      updateButtons();
    }
  }
  function empty(tbody, columns, message) {
    const row = node("tr");
    const cell = node("td", "table-empty", message);
    cell.colSpan = columns;
    row.append(cell);
    tbody.append(row);
  }
  function render() {
    const account = state?.account || null;
    showError(state?.last_error || "");
    text("equity-value", money(account?.equity));
    text("cash-value", money(account?.cash));
    text("equity-currency", account?.currency || "USD");
    text("cash-footnote", account?.cash_label || "美元现金（非可下单额度）");
    text("positions-value", account ? qty(list(account.positions).length) : "—");
    text("account-footnote", state?.account_id ? `真实账户 ${state.account_id}${account ? " · 只读快照" : " · 尚未读取"}` : "尚未选择真实账户");
    text("top-connection", state?.connected ? "OpenD 只读已连接" : "OpenD 未连接");
    $("connection-dot").className = `status-dot${state?.connected ? " connected" : ""}`;
    text("probe-badge", state?.connected ? "REAL · 只读" : "未连接");
    text("connection-message", !state?.connected ? "尚未连接；没有读取账户资金数据。" : state.account_id ? `已选择真实账户 ${state.account_id}。${account ? "账户快照已读取；再次读取可更新数据。" : "点击「读取账户快照」查询资金与持仓。"}` : `发现 ${list(state.accounts).length} 个真实账户，请明确选择。`);
    if (state?.port && document.activeElement !== $("live-port")) $("live-port").value = state.port;
    if (state?.security_firm && document.activeElement !== $("live-security-firm")) $("live-security-firm").value = state.security_firm;
    const signature = JSON.stringify([state?.connected, state?.account_id, list(state?.accounts)]);
    if (signature !== accountSignature) {
      accountSignature = signature;
      const select = $("live-account");
      const previous = select.value;
      select.replaceChildren();
      const placeholder = node("option", "", state?.connected ? "请明确选择一个真实账户" : "先检测 OpenD 连接");
      placeholder.value = "";
      select.append(placeholder);
      list(state?.accounts).filter((item) => item.environment === "REAL").forEach((item) => {
        const option = node("option", "", `真实账户 ${item.account_id} · ${item.market || "US"} · REAL`);
        option.value = String(item.account_id);
        select.append(option);
      });
      if (state?.account_id) select.value = String(state.account_id);
      else if (list(state?.accounts).some((item) => String(item.account_id) === previous)) select.value = previous;
    }
    const warnings = $("account-warnings");
    warnings.replaceChildren();
    warnings.hidden = !list(account?.warnings).length;
    list(account?.warnings).forEach((warning) => warnings.append(node("p", "", warning)));
    text("snapshot-time", `快照时间：${account ? dateLabel(account.asof) : "未读取"}`);
    const holdings = $("live-holdings-body");
    holdings.replaceChildren();
    if (!account) empty(holdings, 5, "选择真实账户并读取快照后显示持仓");
    else if (!list(account.positions).length) empty(holdings, 5, "此次真实账户快照没有持仓");
    list(account?.positions).forEach((position) => {
      const row = node("tr");
      const symbol = node("td", "symbol-cell", position.code || "—");
      if (position.name) symbol.append(node("span", "cell-sub", position.name));
      row.append(symbol, node("td", "align-right", qty(position.qty)), node("td", "align-right", qty(position.sellable)), node("td", "align-right", money(position.market_value)), node("td", "", position.currency || "—"));
      holdings.append(row);
    });
    const orders = $("live-orders-body");
    orders.replaceChildren();
    text("order-count", account ? `${list(account.orders).length} 笔` : "—");
    if (!account) empty(orders, 7, "尚未读取真实订单");
    else if (!list(account.orders).length) empty(orders, 7, "此次只读查询没有返回券商订单");
    list(account?.orders).forEach((order) => {
      const row = node("tr");
      const id = node("td", "", order.order_id ? `#${order.order_id}` : "—");
      id.append(node("span", "cell-sub", dateLabel(order.created_at)));
      const amount = node("td", "align-right", qty(order.qty));
      amount.append(node("span", "cell-sub", `已成 ${qty(order.filled_qty)}`));
      const side = order.side === "BUY" ? "买入" : order.side === "SELL" ? "卖出" : order.side || "—";
      row.append(id, node("td", "symbol-cell", order.code || "—"), node("td", order.side === "BUY" ? "side-buy" : "side-sell", side), amount, node("td", "align-right", money(order.limit_price)), node("td", "", order.currency || "—"), node("td", "", order.status || "—"));
      orders.append(row);
    });
  }
  document.querySelectorAll("[data-ledger]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("[data-ledger]").forEach((other) => {
      const active = other === button;
      other.classList.toggle("active", active);
      other.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-ledger-panel]").forEach((panel) => { panel.hidden = panel.dataset.ledgerPanel !== button.dataset.ledger; });
  }));
  $("live-account").addEventListener("change", updateButtons);
  $("live-connect-btn").addEventListener("click", () => {
    const port = Number($("live-port").value);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return notify("请输入 1 至 65535 之间的 OpenD API 端口。", true);
    action("/api/live/connect", { port, security_firm: $("live-security-firm").value }, "只读连接检测完成，请选择真实账户");
  });
  $("live-select-btn").addEventListener("click", () => {
    const accountId = $("live-account").value;
    if (accountId) action("/api/live/select", { account_id: accountId }, "已选择真实账户，点击读取账户快照查询数据");
  });
  $("live-refresh-btn").addEventListener("click", () => action("/api/live/refresh", {}, "真实账户只读快照已更新"));
  $("state-refresh-btn").addEventListener("click", () => refresh());
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !busy) refresh(true); });
  updateButtons();
  refresh(true);
  setInterval(() => { if (!document.hidden && !busy) refresh(true); }, 10000);
})();
