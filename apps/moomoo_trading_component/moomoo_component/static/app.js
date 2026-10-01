"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const embedded = new URLSearchParams(location.search).get("embed") === "1";
  document.body.classList.toggle("embedded", embedded);
  document.querySelectorAll("[data-environment-link], .environment-link, .brand").forEach((link) => {
    if (embedded) link.href = `${link.getAttribute("href")}?embed=1`;
  });
  const meta = {
    overview: ["交易工作台", "模拟交易工作台", "从目标持仓到订单计划，每一步都可检查。"],
    strategies: ["策略接入", "策略接口与策略库", "用标准 JSON 导入目标持仓，明确选择本轮使用的策略。"],
    connection: ["账户连接", "模拟账户连接", "从本机 OpenD 读取模拟账户，再手动选择执行环境。"],
    risk: ["风控设置", "模拟交易风控", "统一管理资金、持仓与行情时效限制，策略无法绕过。"],
  };
  const limitMeta = {
    max_order_notional: ["单笔订单金额上限", "USD", 0.01],
    max_daily_turnover: ["单日成交 / 委托金额上限", "USD", 0.01],
    max_position_notional: ["单个标的持仓上限", "USD", 0.01],
    max_total_exposure: ["总持仓风险敞口上限", "USD", 0.01],
    min_cash_reserve: ["最低现金保留", "USD", 0.01],
    max_daily_loss: ["当日首次观测后净值下降阈值", "USD", 0.01],
    max_orders_per_day: ["每日订单数量上限", "笔", 1],
    max_quote_age_seconds: ["行情最大有效期", "秒", 1],
    max_spread_bps: ["买卖价差上限", "基点", 0.01],
    max_signal_age_seconds: ["信号最大有效期", "秒", 1],
  };
  let state = null;
  let token = null;
  let busy = 0;
  let refreshing = false;
  let limitsDirty = false;
  let toastTimer;
  let currentView = "overview";
  const number = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const count = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const finite = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const money = (value) => finite(value) ? number.format(Number(value)) : "—";
  const quantity = (value) => finite(value) ? count.format(Number(value)) : "—";
  const list = (value) => Array.isArray(value) ? value : [];
  const text = (id, value) => { $(id).textContent = value == null ? "—" : String(value); };
  const modeLabel = (mode) => mode === "moomoo_simulate" ? "Moomoo 模拟" : "离线纸面";
  const dateLabel = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
  };
  const node = (tag, className, content) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = String(content);
    return element;
  };
  const objectText = (value) => typeof value === "string" ? value : JSON.stringify(value ?? "", null, 2);

  function notify(message, error = false) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").className = "toast" + (error ? " error" : "");
    $("toast").hidden = false;
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7000 : 4200);
  }

  function showError(message) {
    $("error-banner").textContent = message || "";
    $("error-banner").hidden = !message;
  }

  async function request(path, body) {
    const options = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store" };
    if (body !== undefined) {
      if (!token) {
        const result = await request("/api/token");
        token = result.token;
        if (!token) throw new Error("无法取得本机会话令牌，请刷新页面。");
      }
      options.headers = { "Content-Type": "application/json", "X-CSRF-Token": token };
      options.body = JSON.stringify(body);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    options.signal = controller.signal;
    let response;
    try { response = await fetch(path, options); }
    catch (error) {
      if (error.name === "AbortError") throw new Error("请求超时，结果可能尚未返回。请更新状态，勿重复提交订单。");
      throw new Error("本机服务连接失败。请确认组件仍在运行，然后更新状态。");
    } finally { clearTimeout(timeout); }
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error("服务返回格式异常，请查看本机服务日志。"); }
    if (!response.ok || !result.ok) throw new Error(result.error || `请求失败（${response.status}）。`);
    return result.data;
  }

  async function refresh(silent = false) {
    if (refreshing) return;
    refreshing = true;
    try {
      state = await request("/api/state");
      render();
      text("service-status", "已连接");
      text("last-update", `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
      if (!silent) notify("状态已更新");
    } catch (error) {
      text("service-status", "不可达");
      showError(error.message);
      if (!silent) notify(error.message, true);
    } finally { refreshing = false; updateButtons(); }
  }

  async function action(path, body = {}, message, after) {
    if (busy && path !== "/api/halt" && path !== "/api/stop") return;
    busy += 1;
    updateButtons();
    let failure = "";
    try {
      const result = await request(path, body);
      if (after) after(result);
      if (message) notify(message);
    } catch (error) { failure = error.message; notify(failure, true); }
    finally {
      busy = Math.max(0, busy - 1);
      await refresh(true);
      if (failure) showError(failure);
      updateButtons();
    }
  }

  function setView(view) {
    if (view === "audit") { view = "overview"; setLedger("audit"); }
    if (!meta[view]) view = "overview";
    currentView = view;
    document.querySelectorAll(".view").forEach((section) => { section.hidden = section.id !== `view-${view}`; });
    document.querySelectorAll(".nav-item").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const [name, title, description] = meta[view];
    text("page-name", name);
    text("page-title", title);
    text("page-description", description);
    if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  }

  function setLedger(tab) {
    document.querySelectorAll("[data-ledger]").forEach((button) => {
      const active = button.dataset.ledger === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-ledger-panel]").forEach((panel) => { panel.hidden = panel.dataset.ledgerPanel !== tab; });
  }

  function activeManifest() { return list(state?.strategies).find((item) => item.strategy_id === state?.active_strategy); }
  function updateButtons() {
    const offline = !state;
    const blocked = busy || offline;
    const running = Boolean(state?.running);
    const halted = Boolean(state?.halted);
    const active = Boolean(activeManifest());
    ["demo-btn", "connect-btn", "import-btn", "paper-mode-btn", "save-limits-btn", "active-strategy"].forEach((id) => { $(id).disabled = blocked || running; });
    $("preview-btn").disabled = blocked || !active;
    $("inspect-daily-btn").disabled = blocked;
    $("start-btn").disabled = blocked || running || halted || !active || !state?.preview?.allowed;
    $("step-btn").disabled = blocked || running || halted || !active || !state?.preview?.allowed;
    $("stop-btn").disabled = offline || (!running && !busy);
    $("refresh-btn").disabled = busy || refreshing;
    $("sim-mode-btn").disabled = blocked || running || !$("sim-account").value || !$("sim-confirm").checked;
    $("sim-account").disabled = blocked || running || !list(state?.connection?.accounts).length;
    $("sim-confirm").disabled = blocked || running;
    $("reset-halt-btn").disabled = blocked || running || !halted;
    $("reconcile-btn").disabled = blocked || running || state?.mode !== "moomoo_simulate";
    $("halt-btn").disabled = false;
    document.querySelectorAll("[data-switch]").forEach((button) => { button.disabled = blocked || running || button.dataset.switch === state?.active_strategy; });
    document.querySelectorAll("#limits-fields input").forEach((input) => { input.disabled = blocked || running; });
  }

  function tableEmpty(tbody, columns, message) {
    const row = node("tr");
    const cell = node("td", "table-empty", message);
    cell.colSpan = columns;
    row.append(cell);
    tbody.append(row);
  }

  function render() {
    if (!state) return;
    showError(state.last_error || "");
    const account = state.account || {};
    const positions = account.positions && typeof account.positions === "object" ? account.positions : {};
    text("equity-value", money(account.equity));
    text("cash-value", money(account.cash));
    text("positions-value", Object.keys(positions).length ? quantity(Object.values(positions).filter((item) => Number(item.qty) > 0).length) : finite(account.cash) ? "0" : "—");
    const values = Object.values(positions).map((position) => position.market_value);
    text("exposure-value", values.length && values.every(finite) ? `持仓市值 $${money(values.reduce((sum, value) => sum + Number(value), 0))}` : "按当前报价计算风险敞口");
    text("account-footnote", state.mode === "moomoo_simulate" ? `模拟账户 ${state.account_id || "—"} · 非真实资金` : finite(account.cash) ? "paper · 离线虚拟资金 / 合成行情" : "paper · 尚未载入账户快照");
    text("engine-value", state.halted ? "已停止" : state.running ? "运行中" : "待机");
    text("engine-footnote", state.halted ? "须复核原因后手动解除" : state.running ? "自动评估策略与风险" : "启动前请先预览策略");
    $("engine-dot").className = `tiny-dot${state.halted ? " halted" : state.running ? " running" : ""}`;
    text("mode-badge", modeLabel(state.mode));
    $("mode-badge").className = `badge ${state.mode === "moomoo_simulate" ? "badge-warning" : "badge-neutral"}`;
    $("halt-banner").hidden = !state.halted;
    text("halt-reason", state.halt_reason || "请核对最新审计日志和模拟订单状态。");
    renderStrategy();
    renderPreview();
    renderHoldings(positions);
    renderConnection();
    renderLimits();
    renderOrders();
    renderAudit();
    updateButtons();
  }

  function renderStrategy() {
    const strategies = list(state.strategies);
    text("strategy-count", strategies.length);
    text("library-count", `${strategies.length} 份策略`);
    const select = $("active-strategy");
    select.replaceChildren();
    const empty = node("option", "", strategies.length ? "请选择执行策略" : "先导入一份策略");
    empty.value = "";
    select.append(empty);
    strategies.forEach((strategy) => {
      const option = node("option", "", `${strategy.name} · ${strategy.strategy_id} · v${strategy.revision}`);
      option.value = strategy.strategy_id;
      select.append(option);
    });
    select.value = state.active_strategy || "";
    const manifest = activeManifest();
    const targetBody = $("targets-body");
    targetBody.replaceChildren();
    if (!manifest) tableEmpty(targetBody, 3, "选择策略后显示目标持仓");
    list(manifest?.targets).forEach((target) => {
      const holding = state.account?.positions?.[target.code];
      const current = holding ? quantity(holding.qty) : finite(state.account?.cash) ? "0" : "—";
      const row = node("tr");
      row.append(node("td", "symbol-cell", target.code), node("td", "align-right", current), node("td", "align-right target-quantity", quantity(target.target_qty)));
      targetBody.append(row);
    });
    const summary = $("strategy-summary");
    summary.replaceChildren();
    if (!manifest) {
      summary.append(node("div", "empty-icon", "⇄"), node("strong", "", "连接策略与执行"), node("p", "", "在「策略接入」导入 JSON，或载入离线演示开始体验。"));
    } else {
      const heading = node("div", "strategy-detail-head");
      heading.append(node("strong", "", manifest.name), provenanceBadge(manifest.provenance));
      summary.append(heading, node("p", "", `${manifest.source || manifest.strategy_id} · 版本 ${manifest.revision}\n有效至 ${dateLabel(manifest.expires_at)}`));
    }
    const library = $("strategy-library");
    library.replaceChildren();
    if (!strategies.length) library.append(node("p", "table-empty", "策略库还是空的。导入一份策略，或载入离线演示。"));
    strategies.forEach((strategy) => {
      const active = strategy.strategy_id === state.active_strategy;
      const card = node("article", `library-card${active ? " active" : ""}`);
      const heading = node("div", "library-card-heading");
      heading.append(node("h3", "", strategy.name), provenanceBadge(strategy.provenance));
      card.append(heading, node("p", "", `${strategy.strategy_id} · v${strategy.revision}\n${list(strategy.targets).length} 个目标标的\n有效至 ${dateLabel(strategy.expires_at)}`));
      const button = node("button", "button button-light", active ? "当前执行策略" : "选择此策略");
      button.type = "button";
      button.dataset.switch = strategy.strategy_id;
      button.addEventListener("click", () => action("/api/switch", { strategy_id: strategy.strategy_id }, "策略已切换，请重新预览", () => setView("overview")));
      const inspect = node("button", "button button-text inspect-button", "查看 JSON");
      inspect.type = "button";
      inspect.addEventListener("click", () => { $("manifest-editor").value = JSON.stringify(strategy, null, 2); text("file-label", `正在查看 ${strategy.strategy_id}`); $("manifest-editor").focus(); });
      card.append(button, inspect);
      library.append(card);
    });
  }

  function provenanceBadge(value) {
    const labels = { demo: "演示信号", live: "实时信号", historical: "历史记录" };
    return node("span", `badge ${value === "historical" ? "badge-warning" : "badge-neutral"}`, labels[value] || value || "未标注");
  }

  function renderPreview() {
    const preview = state.preview;
    $("preview-empty").hidden = Boolean(preview);
    $("preview-content").hidden = !preview;
    text("preview-badge", !preview ? "等待预览" : preview.allowed ? "检查通过" : "已阻止执行");
    $("preview-badge").className = `badge ${!preview ? "badge-neutral" : preview.allowed ? "badge-safe" : "badge-warning"}`;
    if (!preview) return;
    const checks = $("preview-checks");
    checks.replaceChildren();
    if (preview.allowed) {
      checks.append(node("div", "check-item", "策略、账户、行情与资金限制检查通过"));
      checks.append(node("div", "check-item", "提交时会重新核验，预览结果不代表成交承诺"));
    }
    list(preview.reasons).forEach((reason) => checks.append(node("div", "check-item failed", reason)));
    if (!preview.allowed && !list(preview.reasons).length) checks.append(node("div", "check-item failed", "当前预览未通过，请查看审计日志。"));
    text("preview-meta", `${dateLabel(preview.created_at)} · ${preview.quote_source === "synthetic" ? "合成演示行情" : "Moomoo 模拟行情"} · 预览不提交订单`);
    const tbody = $("preview-orders");
    tbody.replaceChildren();
    if (!list(preview.orders).length) tableEmpty(tbody, 4, preview.allowed ? "目标已满足，本轮没有待执行订单" : "当前没有可执行订单");
    list(preview.orders).forEach((order) => {
      const row = node("tr");
      const symbol = node("td", "", order.code);
      symbol.append(node("span", `cell-sub ${order.side === "BUY" ? "side-buy" : "side-sell"}`, order.side === "BUY" ? "买入" : order.side === "SELL" ? "卖出" : order.side));
      row.append(symbol, node("td", "align-right", quantity(order.qty)), node("td", "align-right", money(order.limit_price)), node("td", "align-right", money(order.notional)));
      tbody.append(row);
    });
  }

  function renderHoldings(positions) {
    const tbody = $("holdings-body");
    tbody.replaceChildren();
    const entries = Object.entries(positions).filter(([, value]) => Number(value.qty) !== 0);
    if (!entries.length) tableEmpty(tbody, 4, finite(state.account?.cash) ? "当前模拟账户没有持仓" : "载入离线演示或选择模拟账户后显示持仓");
    entries.forEach(([code, value]) => {
      const row = node("tr");
      row.append(node("td", "", code), node("td", "align-right", quantity(value.qty)), node("td", "align-right", quantity(value.sellable)), node("td", "align-right", money(value.market_value)));
      tbody.append(row);
    });
  }

  function renderConnection() {
    const connection = state.connection || {};
    text("top-connection", connection.connected ? "OpenD 已连接" : "OpenD 未连接");
    $("connection-dot").className = `status-dot${connection.connected ? " connected" : ""}`;
    text("probe-badge", connection.connected ? "检测通过" : "未连接");
    $("probe-badge").className = `badge ${connection.connected ? "badge-safe" : "badge-neutral"}`;
    const connectionMessage = connection.message || (connection.connected ? `发现 ${list(connection.accounts).length} 个符合条件的模拟账户。` : "还没有检测连接。打开并登录本机 OpenD 后再检测。");
    text("connection-message", `${connectionMessage} 当前执行账户：${state.mode === "moomoo_simulate" ? `Moomoo 模拟 ${state.account_id || "—"}` : "paper（离线虚拟资金）"}。`);
    if (connection.port && document.activeElement !== $("port")) $("port").value = connection.port;
    if (connection.security_firm && document.activeElement !== $("security-firm")) $("security-firm").value = connection.security_firm;
    const select = $("sim-account");
    const previous = select.value;
    select.replaceChildren();
    const empty = node("option", "", connection.connected ? "请明确选择一个模拟账户" : "先完成只读连接检测");
    empty.value = "";
    select.append(empty);
    list(connection.accounts).forEach((account) => {
      const option = node("option", "", `模拟账户 ${account.account_id} · ${account.market || "US"} · SIMULATE`);
      option.value = String(account.account_id);
      select.append(option);
    });
    if (list(connection.accounts).some((account) => String(account.account_id) === previous)) select.value = previous;
    else $("sim-confirm").checked = false;
  }

  function renderLimits() {
    text("risk-order-value", `$${money(state.limits?.max_order_notional)}`);
    text("risk-cash-value", `$${money(state.limits?.min_cash_reserve)}`);
    text("risk-count-value", `${quantity(state.limits?.max_orders_per_day)} 笔`);
    const fields = $("limits-fields");
    if (!fields.children.length) {
      Object.entries(limitMeta).forEach(([key, [label, unit, step]]) => {
        const group = node("div");
        const labelEl = node("label", "field-label", label);
        labelEl.htmlFor = `limit-${key}`;
        labelEl.append(node("span", "limit-unit", unit));
        const input = node("input");
        input.id = `limit-${key}`;
        input.name = key;
        input.type = "number";
        input.min = key === "min_cash_reserve" ? "0" : String(step);
        input.step = String(step);
        input.required = true;
        input.addEventListener("input", () => { limitsDirty = true; });
        group.append(labelEl, input);
        fields.append(group);
      });
    }
    if (!limitsDirty) Object.keys(limitMeta).forEach((key) => { $(`limit-${key}`).value = finite(state.limits?.[key]) ? state.limits[key] : ""; });
  }

  function renderOrders() {
    const orders = list(state.orders);
    text("order-count", `${orders.length} 笔`);
    const tbody = $("orders-body");
    tbody.replaceChildren();
    if (!orders.length) tableEmpty(tbody, 7, "尚无模拟订单记录");
    orders.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 200).forEach((order) => {
      const row = node("tr");
      const time = node("td", "", dateLabel(order.created_at));
      time.append(node("span", "cell-sub", order.strategy_id || "—"));
      const status = node("td");
      const warning = /unknown|fail|reject|error/i.test(String(order.status));
      status.append(node("span", `badge ${warning ? "badge-warning" : "badge-neutral"}`, order.status || "—"));
      if (order.order_id) status.append(node("span", "cell-sub", `#${order.order_id}`));
      row.append(time, node("td", "", order.code), node("td", order.side === "BUY" ? "side-buy" : "side-sell", order.side === "BUY" ? "买入" : order.side === "SELL" ? "卖出" : order.side), node("td", "align-right", quantity(order.qty)), node("td", "align-right", money(order.limit_price)), node("td", "", modeLabel(order.mode)), status);
      tbody.append(row);
    });
  }

  function renderAudit() {
    const container = $("audit-list");
    container.replaceChildren();
    const entries = list(state.audit);
    if (!entries.length) container.append(node("p", "table-empty", "尚无审计事件"));
    entries.slice().sort((a, b) => String(b.time || "").localeCompare(String(a.time || ""))).slice(0, 150).forEach((entry) => {
      const row = node("div", "audit-entry");
      row.append(node("span", "audit-time", dateLabel(entry.time)), node("span", "audit-event", entry.event || "事件"), node("pre", "audit-detail", objectText(entry.detail)));
      container.append(row);
    });
  }

  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  document.querySelectorAll("[data-ledger]").forEach((button) => button.addEventListener("click", () => setLedger(button.dataset.ledger)));
  document.querySelectorAll("[data-goto]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.goto)));
  window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
  $("refresh-btn").addEventListener("click", () => refresh());
  $("demo-btn").addEventListener("click", () => action("/api/demo", {}, "离线演示已载入，请预览策略", () => setView("overview")));
  $("active-strategy").addEventListener("change", () => {
    if ($("active-strategy").value) action("/api/switch", { strategy_id: $("active-strategy").value }, "策略已切换，请重新预览");
  });
  $("preview-btn").addEventListener("click", () => action("/api/preview", {}, "预览已完成，请查看检查结果"));
  $("start-btn").addEventListener("click", () => action("/api/start", {}, "模拟执行已启动"));
  $("step-btn").addEventListener("click", () => action("/api/step", {}, "执行请求已处理，请查看订单与审计"));
  $("stop-btn").addEventListener("click", () => action("/api/stop", {}, "引擎已暂停，已提交订单请另行核对"));
  $("halt-btn").addEventListener("click", () => action("/api/halt", {}, "已请求紧急停止。已提交的模拟订单仍须核对。"));
  $("reset-halt-btn").addEventListener("click", () => action("/api/reset-halt", {}, "停止锁已解除，请重新预览后再启动"));
  $("reconcile-btn").addEventListener("click", () => action("/api/reconcile", {}, "模拟订单状态已读取，请查看订单与审计"));
  $("connect-btn").addEventListener("click", () => {
    const port = Number($("port").value);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return notify("请输入 1 至 65535 之间的 API 端口。", true);
    action("/api/connect", { port, security_firm: $("security-firm").value }, "只读检测完成，请查看模拟账户列表");
  });
  $("paper-mode-btn").addEventListener("click", () => action("/api/mode", { mode: "paper" }, "已切换为离线纸面模式，请重新预览"));
  $("sim-account").addEventListener("change", () => { $("sim-confirm").checked = false; updateButtons(); });
  $("sim-confirm").addEventListener("change", updateButtons);
  $("sim-mode-btn").addEventListener("click", () => {
    if (!$("sim-confirm").checked || !$("sim-account").value) return;
    action("/api/mode", { mode: "moomoo_simulate", account_id: $("sim-account").value, confirmation: "SIMULATE" }, "已选择 Moomoo 模拟账户，请预览策略", () => { $("sim-confirm").checked = false; setView("overview"); });
  });
  $("template-btn").addEventListener("click", () => {
    const now = new Date();
    $("manifest-editor").value = JSON.stringify({ schema_version: 1, strategy_id: "my-strategy", name: "我的目标持仓策略", revision: "1", asof: now.toISOString(), expires_at: new Date(now.valueOf() + 3600000).toISOString(), provenance: "demo", targets: [{ code: "US.AAPL", target_qty: 1 }], source: "JSON 格式示例：请替换为你的策略输出" }, null, 2);
    text("file-label", "已填入演示格式模板；请检查内容后导入。");
    $("manifest-editor").focus();
  });
  $("strategy-file").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 256 * 1024) { notify("策略文件超过 256 KB，请缩小后再导入。", true); event.target.value = ""; return; }
    try {
      const content = await file.text();
      JSON.parse(content);
      $("manifest-editor").value = content;
      text("file-label", `${file.name} · 已读取，尚未导入`);
    } catch (_) { notify("文件不是有效的 JSON，请检查文件内容。", true); }
    event.target.value = "";
  });
  $("import-btn").addEventListener("click", () => {
    let manifest;
    try { manifest = JSON.parse($("manifest-editor").value); }
    catch (_) { return notify("JSON 格式有误，请检查逗号、引号与括号。", true); }
    if (!manifest || Array.isArray(manifest) || typeof manifest !== "object") return notify("策略内容必须是一个 JSON 对象。", true);
    action("/api/import", { manifest }, "策略已导入，请在策略库中选择执行策略");
  });
  $("inspect-daily-btn").addEventListener("click", () => {
    let payload;
    try { payload = JSON.parse($("manifest-editor").value); }
    catch (_) { return notify("请先粘贴有效的 A2 原始推荐 JSON。", true); }
    if (!payload || Array.isArray(payload) || typeof payload !== "object") return notify("A2 推荐内容必须是一个 JSON 对象。", true);
    action("/api/inspect-daily", { payload }, "A2 推荐检查完成，未导入或启用策略", (result) => {
      const container = $("daily-inspection");
      container.replaceChildren();
      container.hidden = false;
      container.append(node("strong", "", result?.summary || "检查完成"));
      container.append(node("p", "helper", result?.eligible_for_conversion ? "兼容性检查通过；这里只展示检查结果，尚未转换为可执行策略。" : "当前不能转换为可执行策略。"));
      const issues = node("div", "check-list inspection-checks");
      list(result?.rejection_details).forEach((item) => { issues.append(node("div", "check-item failed", `${item.code ? `${item.code}：` : ""}${item.message || "未通过检查"}`)); });
      container.append(issues);
      const details = { 来源: result?.source, 模型: result?.model_id, 运行标识: result?.run_id, 数据日期: result?.data_date, 覆盖率: result?.coverage, 原始权重目标: result?.targets };
      container.append(node("pre", "audit-detail", objectText(details)));
    });
  });
  $("limits-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const limits = {};
    for (const key of Object.keys(limitMeta)) {
      const input = $(`limit-${key}`);
      if (!input.value || !Number.isFinite(Number(input.value))) return notify("请完整填写所有风控限额。", true);
      limits[key] = Number(input.value);
    }
    action("/api/limits", limits, "风控限额已保存，请重新预览策略", () => { limitsDirty = false; });
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !busy) refresh(true); });
  setView(location.hash.slice(1));
  updateButtons();
  request("/api/token").then((result) => { token = result.token; }).catch((error) => showError(error.message));
  refresh(true);
  setInterval(() => { if (!document.hidden && !busy) refresh(true); }, 5000);
})();
