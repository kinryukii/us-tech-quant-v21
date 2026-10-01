"""Three fixed strategies in one workbench: comparison, ranks and stock history."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from io import StringIO

import altair as alt
import pandas as pd
import streamlit as st

from apps.demo_console.adapters import selected_strategies_reader as reader
from apps.demo_console.adapters import workspace_reader
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.performance_charts import nav_comparison_chart
from apps.demo_console.components.performance_charts import STRATEGY_COLORS
from apps.demo_console.components.performance_stats import summarize_nav_window
from apps.demo_console.components.visuals import apply_style
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.components.localized_tabs import localized_tabs
from apps.demo_console.i18n import tr


_ACTION_LABELS = {"BUY": "买入 / 加仓", "SELL": "卖出 / 减仓", "HOLD": "保持"}
WORKSPACE_STRATEGIES = {"RAW_A2": "Raw A2", "HGB_DIAG_5": "HGB + diagonal risk",
                        "HGB_FACTOR_5": "HGB + factor / shrinkage risk"}


def target_csv(strategy_id, strategy):
    """Download an account-independent weight plan, including the target cash."""
    application = strategy["application"]
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=("strategy_id", "signal_date", "account_basis", "ticker",
                                               "target_weight", "weight_before", "action"))
    writer.writeheader()
    for row in application["rows"]:
        writer.writerow({"strategy_id": strategy_id, "signal_date": application["signal_date"],
                         "account_basis": application["account_basis"], **{key: row.get(key) for key in
                         ("ticker", "target_weight", "weight_before", "action")}})
    writer.writerow({"strategy_id": strategy_id, "signal_date": application["signal_date"],
        "account_basis": application["account_basis"], "ticker": "CASH",
        "target_weight": application["target_cash_weight"],
        "weight_before": application.get("cash_weight_before", 1.0), "action": "RESERVE"})
    return stream.getvalue().encode("utf-8-sig")


def _target_table(rows, *, localized=False):
    labels = tuple(map(tr, ("Ticker", "Target weight", "Previous signal weight", "Adjustment"))) if localized else (
        "证券", "目标仓位", "方案原仓位", "调整")
    actions = {"BUY": tr("Buy / increase"), "SELL": tr("Sell / reduce"), "HOLD": tr("Hold")} if localized else _ACTION_LABELS
    frame = pd.DataFrame([{labels[0]: row["ticker"], labels[1]: row["target_weight"],
        labels[2]: row["weight_before"], labels[3]: actions.get(row["action"], row["action"])}
        for row in rows], columns=labels)
    st.dataframe(frame, hide_index=True, width="stretch",
        height=min(650, 42 + 35 * len(frame)),
        column_config={labels[1]: st.column_config.NumberColumn(format="percent"),
                       labels[2]: st.column_config.NumberColumn(format="percent")})






def nav_chart(package):
    """Use explicit observed domains through Streamlit's empty-then-Arrow lifecycle."""
    rows = [{"date": point["date"], "nav": point["nav"], "strategy": package["strategies"][sid]["label"]}
            for sid in reader.STRATEGY_IDS for point in package["strategies"][sid]["daily"]]
    dates = sorted({row["date"] for row in rows})
    domain = [dates[0], dates[-1]]
    if len(dates) == 1:
        day = date.fromisoformat(dates[0])
        domain = [(day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat()]
    values = [1.0, *(row["nav"] for row in rows)]
    low, high = min(values), max(values)
    padding = (high - low) * .06 or .04
    count = min(6, len(dates))
    ticks = ([dates[round(index * (len(dates) - 1) / (count - 1))] for index in range(count)]
             if count > 1 else dates)
    return (alt.Chart(alt.Data(values=rows)).mark_line(clip=True, strokeWidth=3,
                point=alt.OverlayMarkDef(filled=True, size=65) if len(dates) == 1 else False)
            .encode(x=alt.X("date:T", title="执行日期", scale=alt.Scale(domain=domain, nice=False),
                           axis=alt.Axis(format="%Y-%m-%d", values=ticks, labelAngle=0)),
                    y=alt.Y("nav:Q", title="NAV（初始值 1）",
                            scale=alt.Scale(domain=[max(0, low - padding), high + padding],
                                            zero=False, nice=False)),
                    color=alt.Color("strategy:N", title=None,
                                    scale=alt.Scale(domain=[package["strategies"][sid]["label"]
                                                           for sid in reader.STRATEGY_IDS],
                                                    range=[STRATEGY_COLORS[sid] for sid in reader.STRATEGY_IDS]),
                                    legend=alt.Legend(orient="top")),
                    tooltip=[alt.Tooltip("date:T", title="执行日期", format="%Y-%m-%d"),
                             alt.Tooltip("strategy:N", title="策略"),
                             alt.Tooltip("nav:Q", title="NAV", format=".4f")])
            .properties(height=360, autosize=alt.AutoSizeParams(type="fit", contains="padding"))
            .configure_view(stroke=None))




def replay_basis_caption(package):
    if package["performance_period"]["price_basis"] == "PIT_FORWARD_REHAB_INDEX":
        return "独立 PIT 三策略研究回放：按前向复权价格坐标、收盘信号和下一交易日开盘执行计算；原冻结 QFQ 回放保留。曲线是描述性研究结果，不是模拟账户绩效，也不是新的独立检验。"
    return "HGB replay uses the corrected close-signal / next-session-open clock and QFQ price-coordinate proxies. These exposed 2026 outcomes are descriptive, not a new independent test."


def replay_update_caption(package):
    extension = package.get("performance_extension")
    if not extension:
        return None
    end = package["performance_period"]["end"]
    if extension["status"] == "READY":
        return "三策略图表已同步至 " + end + "。"
    return ("三策略图表已验证至 " + end + "；本次请求更新至 " + extension["requested_end_date"]
            + "，下一执行日 " + extension["blocked_next"]["execution_date"] + " 尚未通过："
            + extension["blocked_next"]["reason"])


def _source_details(package, *, presentation=False):
    if presentation:
        with st.expander(tr("Data sources")):
            st.write(tr(replay_basis_caption(package)))
            st.caption(tr("Historical return records and current target allocations have separate dates. Target weights do not represent executed trades."))
            st.caption(tr("Source integrity") + " · " + package["package_sha256"][:12])
        return
    with st.expander("来源与适用范围"):
        st.write("截图中的旧统计使用了未修正的决策时钟；本页显示修正后的收盘信号、下一交易日开盘执行回放，指标以本页数据包为准。")
        st.write(tr(replay_basis_caption(package)))
        st.caption("选择依据：USER_SELECTED_AFTER_EXPOSURE · 已暴露结果后的用户选择，不能恢复独立留出检验状态。")
        st.caption("数据包生成时间：" + package["generated_at"])
        st.caption("数据包 SHA-256：" + package["package_sha256"])
        st.dataframe(pd.DataFrame([{"来源工件": name, "SHA-256": digest}
                                  for name, digest in package["source_hashes"].items()]),
                     hide_index=True, width="stretch")


def render_selected_strategies(pages):
    """Keep old bookmarks on the same workbench and observation context."""
    if st.session_state.get("workspace_strategy") not in WORKSPACE_STRATEGIES:
        previous = st.session_state.get("selected_hgb_strategy")
        st.session_state["workspace_strategy"] = previous if previous in reader.STRATEGY_IDS else reader.STRATEGY_IDS[0]
    st.session_state.pop("selected_hgb_strategy", None)
    st.session_state.pop("selected_hgb_history_date", None)
    st.session_state["workspace"] = "Overview"
    st.session_state["_applied_workspace_context"] = {
        key: st.session_state[key] for key in ("workspace_strategy", "decision_date", "workspace_sample")
        if key in st.session_state}
    st.switch_page(pages["research"])


def _display_number(value, *, percent=False, precision=2, suffix=""):
    if value is None:
        return "—"
    return (f"{value:.{precision}%}" if percent else f"{value:.{precision}f}") + suffix


def _comparison_summaries(comparison):
    return {comparison["strategy_ids"].get(label, "RAW_A2"): window
            for label, window in comparison["windows"].items()} if comparison else {}


def render_comparison_cards(contexts, *, summaries=None, include_targets=True,
                            key="applied_summary_table"):
    """Compatibility name for the single compact, always-three-strategy table."""
    summaries = summaries if summaries is not None else {
        sid: summarize_nav_window(view["history"]["daily"], view["history"]["start"], view["history"]["end"])
        if view["history"]["daily"] else None for sid, view in contexts.items()}
    fields = (("Period return", "cumulative_return", True),
              ("Maximum window drawdown", "max_drawdown", True),
              ("Annualized volatility", "annualized_volatility", True),
              ("Annualized Sharpe", "sharpe", False),
              ("Historical average cash", "mean_cash", True))
    rows = [{tr("Strategy"): tr(label), **{tr(name): _display_number(
        (summaries.get(sid) or {}).get(field), percent=percent) for name, field, percent in fields}}
        for sid, label in WORKSPACE_STRATEGIES.items()]
    st.html('<section class="uq-strategy-scorecard" aria-label="' + text(tr("Applied strategies")) + '">'
        + ''.join('<article class="uq-strategy-score" data-strategy="' + text(sid)
            + '" style="--strategy-color:' + STRATEGY_COLORS[sid] + '">'
            + '<div class="uq-strategy-name"><span class="uq-strategy-index">' + f'{index:02}'
            + '</span><h2>' + text(row[tr("Strategy")]) + '</h2></div>'
            + '<div class="uq-strategy-return"><span>' + text(tr("Period return"))
            + '</span><strong>' + text(row[tr("Period return")]) + '</strong></div>'
            + '<dl class="uq-strategy-metrics">' + ''.join('<div><dt>' + text(tr(name))
                + '</dt><dd>' + text(row[tr(name)]) + '</dd></div>' for name, _, _ in fields[1:])
            + '</dl></article>' for index, (sid, row) in enumerate(zip(WORKSPACE_STRATEGIES, rows), 1))
        + '</section>')
    # Keep one native table as an accessible, sortable alternative to the scorecard.
    # Both surfaces use exactly the same already formatted observations.
    with st.expander(tr("Quantitative comparison"), expanded=False, key=key + "_table"):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=149, key=key,
            column_config={tr("Strategy"): st.column_config.TextColumn(width=180),
                           **{tr(name): st.column_config.TextColumn(width=110) for name, _, _ in fields}})


def render_comparison_paths(comparison, *, key_prefix="applied"):
    if not comparison:
        st.caption(tr("No comparable replay is available in this window."))
        return
    labels = {label: tr(WORKSPACE_STRATEGIES[comparison["strategy_ids"].get(label, "RAW_A2")])
              for label in comparison["windows"]}
    colors = {labels[label]: STRATEGY_COLORS[comparison["strategy_ids"].get(label, "RAW_A2")]
              for label in labels}
    series = {labels[label]: window["rows"] for label, window in comparison["windows"].items()}
    reference=comparison.get("reference")
    net_series=dict(series)
    dashed=()
    if reference:
        net_series[reference["label"]]=reference["rows"]
        colors[reference["label"]]="#7b8792"
        dashed=(reference["label"],)
    with st.container(key=key_prefix + "_portfolio_canvas"):
        st.html(section_header(tr("Portfolio growth"), tr("RETURN & RISK"),
                               f'{comparison["start"]} → {comparison["end"]}'))
        render_chart(nav_comparison_chart(net_series, title="NAV", colors=colors, dashed=dashed)
                     .properties(height=365, name=key_prefix + "_nav"), width="stretch", theme=None, key=key_prefix + "_nav")
        st.html('<div class="uq-chart-note"><span>' + text(tr("Recorded execution days"))
                + '</span><strong>' + text(comparison["days"]) + '</strong><p>'
                + text(tr("Historical return records and current target allocations have separate dates. Target weights do not represent executed trades."))
                + '</p></div>')
    with st.expander(tr("Drawdown comparison"), expanded=False, key=key_prefix + "_risk_path"):
        render_chart(nav_comparison_chart({label: [{**row, "value": row["drawdown"]} for row in points]
                     for label, points in series.items()}, baseline=0, title="Window drawdown", percent=True,
                     colors=colors).properties(height=235, name=key_prefix + "_drawdown"), width="stretch", theme=None, key=key_prefix + "_drawdown")


def render_comparison_statistics(comparison, *, key_prefix="applied"):
    if not comparison:
        return
    summaries = _comparison_summaries(comparison)
    st.subheader(tr("Quantitative comparison"))
    fields = (("Period return", "cumulative_return", "percent"), ("End NAV", "end_nav", "number"),
        ("Annualized compound return", "annualized_return", "percent"),
        ("Annualized volatility", "annualized_volatility", "percent"),
        ("Annualized Sharpe", "sharpe", "number"), ("Sortino · Target return 0", "sortino", "number"),
        ("Calmar · Selected window", "calmar", "number"),
        ("Maximum window drawdown", "max_drawdown", "percent"),
        ("Worst daily net return", "worst_return", "percent"), ("Best daily net return", "best_return", "percent"),
        ("Longest underwater period · Records", "longest_underwater_days", "integer"),
        ("Drawdown peak date", "peak_date", "date"), ("Drawdown trough date", "trough_date", "date"),
        ("Recovery date", "recovery_date", "date"), ("Peak-to-recovery · Records", "recovery_days", "integer"),
        ("Positive return days", "positive_day_fraction", "percent"),
        ("Positive return months", "positive_month_fraction", "percent"),
        ("Best recorded month", "best_month_return", "percent"), ("Worst recorded month", "worst_month_return", "percent"),
        ("Historical average cash", "mean_cash", "percent"), ("Historical average exposure", "mean_exposure", "percent"),
        ("Average recorded securities", "mean_holding_count", "number"),
        ("Cumulative turnover · Times", "turnover", "number"),
        ("Average daily turnover", "mean_turnover", "percent"),
        ("Simulated fees / Window initial NAV", "cost_fraction", "percent"),
        ("Gross period return", "gross_return", "percent"),
        ("Gross/net return difference · pp", "gross_net_difference_pp", "number"),
        ("Skipped buy observations", "skipped_buy_count", "integer"),
        ("Blocked sell observations", "blocked_sell_count", "integer"),
        ("Stale mark observations", "stale_mark_count", "integer"),
        ("Benchmark beta", "benchmark_beta", "number"),
        ("Tracking error", "tracking_error", "percent"),
        ("Information ratio", "information_ratio", "number"),
        ("Account trade win rate", "account_win_rate", "percent"),
        ("Closed trade profit/loss ratio", "closed_trade_payoff", "number"),
        ("Recorded execution days", "days", "integer"))
    labels = {"RAW_A2": tr("Raw A2"), "HGB_DIAG_5": tr("HGB · Diagonal"), "HGB_FACTOR_5": tr("HGB · Factor")}
    rows = []
    for name, field, kind in fields:
        row = {tr("Metric"): tr(name)}
        for sid, label in labels.items():
            window = summaries.get(sid)
            value = window.get(field) if window else None
            if kind == "date":
                row[label] = value or (tr("Not recovered within the window") if field == "recovery_date" and window and window["max_drawdown"] < 0 else "—")
            else:
                row[label] = _display_number(value, percent=kind == "percent", precision=0 if kind == "integer" else 2)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=700, key=key_prefix + "_statistics")
    st.caption(tr("Daily observations · 252 sessions/year · Sample standard deviation · Sharpe risk-free return 0 · Sortino target return 0. Annualized values below one year are estimates."))
    st.caption(tr("Fees and turnover use the selected daily ledger only. Missing execution fields remain unavailable; research NAV is not account P&L."))
    st.caption(tr("Gross returns compound gross daily returns on the recorded holdings path; the gross/net difference includes compounding and is not the cumulative fee amount."))
    if comparison.get("reference"):
        reference=comparison["reference"]
        st.caption(tr("{label}: {return_value} over these dates · RAW open-price reference, excluding dividends and fees. Strategy replay uses its recorded adjustment basis.",label=reference["label"],return_value=_display_number(reference["return"],percent=True)))
    st.caption(tr("Benchmark beta, tracking error and information ratio require a matching return basis. Account trade ratios require a connected account and closed trades; unavailable values remain —."))
    months = [{"period": month["period"] + ("*" if month["partial"] else ""),
               "strategy": labels[sid], "return": month["return"], "days": month["days"]}
              for sid, window in summaries.items() for month in window["months"]]
    if months:
        st.markdown("**" + tr("Monthly return comparison") + "**")
        base = alt.Chart(alt.Data(values=months)).encode(
            x=alt.X("period:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("strategy:N", title=None, sort=list(labels.values())))
        heat = base.mark_rect().encode(color=alt.Color("return:Q", title=tr("Period return"),
            scale=alt.Scale(scheme="redblue", domainMid=0), legend=alt.Legend(format=".0%")),
            tooltip=[alt.Tooltip("strategy:N", title=tr("Strategy")), alt.Tooltip("period:O", title=tr("Period")),
                     alt.Tooltip("return:Q", title=tr("Period return"), format=".2%"),
                     alt.Tooltip("days:Q", title=tr("Recorded execution days"))])
        values = base.mark_text(fontSize=14).encode(text=alt.Text("return:Q", format=".1%"),
            color=alt.condition("luminance(scale('color', datum.return)) > 0.179128784747792", alt.value("#000000"), alt.value("#ffffff")))
        render_chart((heat + values).properties(height=155).configure_view(stroke=None),
                     width="stretch", theme=None, key=key_prefix + "_monthly")
        st.caption(tr("* Archive-edge or selected-window month may be incomplete. Positive-month statistics include these partial periods."))

    paths = {labels[sid]: window["rows"] for sid, window in summaries.items()}
    colors = {labels[sid]: STRATEGY_COLORS[sid] for sid in summaries}
    cash, rolling = st.columns(2, gap="medium")
    with cash:
        st.markdown("**" + tr("Historical cash comparison") + "**")
        render_chart(nav_comparison_chart({label: [{**row,"value":row["cash_weight"]} for row in points]
            for label,points in paths.items()},baseline=0,title="Historical cash weight",percent=True,colors=colors)
            .properties(height=250),width="stretch",theme=None,key=key_prefix+"_cash")
    with rolling:
        st.markdown("**" + tr("21-record rolling net return") + "**")
        if comparison["days"] >= 21:
            rolling_paths = {label: [{"execution_date":points[i]["execution_date"],
                "value":points[i]["value"]/(points[i-21]["value"] if i>=21 else 1.)-1.}
                for i in range(20,len(points))] for label,points in paths.items()}
            render_chart(nav_comparison_chart(rolling_paths,baseline=0,title="Net return",percent=True,colors=colors)
                .properties(height=250),width="stretch",theme=None,key=key_prefix+"_rolling")
        else:
            st.caption(tr("This interval has fewer than 21 return records."))
    from math import fsum, sqrt
    correlations=[]
    for sid,left in summaries.items():
        row={tr("Strategy"):labels[sid]}
        x=[point["net_return"] for point in left["rows"]]
        mean_x=fsum(x)/len(x)
        for other,right in summaries.items():
            y=[point["net_return"] for point in right["rows"]]
            mean_y=fsum(y)/len(y)
            divisor=sqrt(fsum((v-mean_x)**2 for v in x)*fsum((v-mean_y)**2 for v in y))
            value=fsum((a-mean_x)*(b-mean_y) for a,b in zip(x,y))/divisor if divisor>0 and len(x)>1 else None
            row[labels[other]]=_display_number(value)
        correlations.append(row)
    st.markdown("**"+tr("Daily return correlation")+"**")
    st.dataframe(correlations,hide_index=True,width="stretch",height=149,key=key_prefix+"_correlations")


def _exact_signal_contexts(contexts, cutoff):
    """Compare same-date plans; an older plan never becomes today's plan."""
    result = {}
    for sid, context in contexts.items():
        target = context.get("signal_target", context["target"]) if sid == "RAW_A2" else context["target"]
        if target.get("signal_date") != cutoff or target.get("kind") == "UNAVAILABLE":
            target = {**target, "kind": "UNAVAILABLE", "status": "UNAVAILABLE", "rows": [],
                      "signal_date": None, "target_cash_weight": None}
        result[sid] = {**context, "target": target}
    return result


def _workspace_allocation_comparison(contexts, *, compact=False):
    """A side-by-side union of exact-date targets, with explicit missing plans."""
    st.markdown("#### " + tr("Allocation comparison"))
    ids = tuple(WORKSPACE_STRATEGIES)
    valid = {sid: contexts[sid]["target"]["kind"] != "UNAVAILABLE" for sid in ids}
    labels = {"RAW_A2": tr("Raw A2"), "HGB_DIAG_5": tr("HGB · Diagonal"), "HGB_FACTOR_5": tr("HGB · Factor")}
    status = []
    raw_plan=contexts["RAW_A2"]["target"]
    for sid in ids:
        target = contexts[sid]["target"]
        ranked_weights=sorted((row["target_weight"] for row in target["rows"] if row["target_weight"]>0),reverse=True)
        plan_date=(raw_plan.get("execution_date") if raw_plan.get("signal_date")==target.get("signal_date") else target.get("execution_date"))
        status.append({tr("Strategy"): tr(WORKSPACE_STRATEGIES[sid]),
            tr("Target signal date"): target.get("signal_date") or "—",
            tr("Planned execution date"): plan_date or "—",
            tr("Target securities"): sum(row["target_weight"] > 0 for row in target["rows"]) if valid[sid] else None,
            tr("Target cash allocation"): _display_number(target.get("target_cash_weight"), percent=True),
            tr("Maximum security weight"): _display_number(max(ranked_weights,default=0.) if valid[sid] else None,percent=True),
            tr("Top 5 concentration"): _display_number(sum(ranked_weights[:5]) if valid[sid] else None,percent=True),
            tr("Weight record type"): tr("Raw rule target" if sid == "RAW_A2" else
                "Empty-account target" if target.get("kind") in {"CURRENT_CASH_START_TARGET", "ARCHIVED_CASH_START_TARGET"} else "Historical signal target")
                if valid[sid] else tr("Target unavailable")})
    st.dataframe(status, hide_index=True, width="stretch", height=149, key="applied_target_status",
        column_config={tr("Strategy"):st.column_config.TextColumn(width=175),
            **{tr(name):st.column_config.TextColumn(width=105) for name in ("Target signal date","Planned execution date","Weight record type")},
            **{tr(name):st.column_config.TextColumn(width=85) for name in ("Target cash allocation","Maximum security weight","Top 5 concentration")},
            tr("Target securities"):st.column_config.NumberColumn(width=65)})
    for sid in ids:
        target = contexts[sid]["target"]
        if target.get("status") == "BLOCKED" and target.get("reason"):
            st.caption(tr(WORKSPACE_STRATEGIES[sid]) + " · " + target["reason"])
    weights = {sid: {row["ticker"]: row["target_weight"] for row in contexts[sid]["target"]["rows"]} for sid in ids}
    names = set().union(*(set(values) for values in weights.values()))
    tickers = ["CASH", *sorted(names, key=lambda ticker: (-max(values.get(ticker, 0.) for values in weights.values()), ticker))]
    rows = [{tr("Ticker"): ticker, **{labels[sid]: _display_number(
        contexts[sid]["target"]["target_cash_weight"] if ticker == "CASH" else weights[sid].get(ticker, 0.), percent=True)
        if valid[sid] else "—" for sid in ids}} for ticker in tickers]
    st.dataframe(rows, hide_index=True, width="stretch", height=285 if compact else 370,
                 key="workspace_hgb_target_comparison")
    st.caption(tr("These are same-date signal plans. Verified absent names have zero weight; a missing plan remains unavailable. Recorded Raw execution holdings are shown in details."))
    downloads = st.columns(3, gap="small")
    for column, sid in zip(downloads, ids):
        if not valid[sid]:
            continue
        target = contexts[sid]["target"]
        download_target = {**target, "cash_weight_before": (max(0., 1 - sum(row["weight_before"] for row in target["rows"]))
            if all(row.get("weight_before") is not None for row in target["rows"]) else None)}
        column.download_button(tr("Download weights") + " · " + labels[sid],
            target_csv(sid, {"application": download_target}),
            file_name=f'{sid}_{target["signal_date"]}_targets.csv', mime="text/csv",
            key="workspace_hgb_comparison_csv_" + sid)


def _workspace_target(context, *, searchable=False):
    target = context["target"]
    st.html(section_header(tr("Strategy target allocation"), tr("SIGNAL PLAN")))
    if target["kind"] == "UNAVAILABLE":
        st.warning(tr("No verified target allocation is available by the selected date."))
        if target.get("reason"):
            st.caption(target["reason"])
        return
    if target["status"] == "LATEST_AVAILABLE_SIGNAL":
        st.warning(tr("Latest available target signal: {date}", date=target["signal_date"]))
    else:
        st.caption(tr("Target signal date: {date}", date=target["signal_date"]))
    if target["kind"] in {"CURRENT_CASH_START_TARGET", "ARCHIVED_CASH_START_TARGET"}:
        st.caption(tr("Cash-start account plan · Initial cash 100% · Target weights only."))
    else:
        st.caption(tr("Recorded historical signal targets. These are not executed account holdings."))
    stock_weight = sum(row["target_weight"] for row in target["rows"])
    stocks, cash, count = st.columns(3)
    stocks.metric(tr("Target equity allocation"), f"{stock_weight:.2%}")
    cash.metric(tr("Target cash allocation"), f'{target["target_cash_weight"]:.2%}')
    count.metric(tr("Target securities"), sum(row["target_weight"] > 0 for row in target["rows"]))
    rows = target["rows"]
    if searchable:
        query = st.text_input(tr("Search ticker"), key="workspace_hgb_ticker_search").strip().upper()
        rows = [row for row in rows if query in row["ticker"]]
    if rows:
        _target_table(rows, localized=True)
    else:
        st.info(tr("No records match these filters. Clear the ticker search or choose All names."))
    download_target = {**target, "cash_weight_before": (max(0., 1 - sum(row["weight_before"] for row in target["rows"]))
            if all(row.get("weight_before") is not None for row in target["rows"]) else None)}
    st.download_button(tr("Download target weights CSV"),
        target_csv(context["strategy_id"], {"application": download_target}),
        file_name=f'{context["strategy_id"]}_{target["signal_date"]}_targets.csv', mime="text/csv",
        key="workspace_hgb_target_csv")


def _workspace_model(context, package, *, presentation):
    st.html(section_header(tr("Frozen HGB model and risk allocation"), tr("SELECTED STRATEGY")))
    identity = context["model_identity"]
    features, cutoff = st.columns(2)
    features.metric(tr("Model input features"), identity["feature_count"])
    cutoff.metric(tr("Training boundary"), "< " + identity["fit_cutoff_exclusive"])
    st.write(tr("Prediction target: next-open to five-session-later-open absolute return."))
    st.dataframe([
        {tr("Feature family"): tr("Original A2 rank and standardized score"), tr("Feature count"): 2},
        {tr("Feature family"): tr("Returns, volatility, volume and price position"), tr("Feature count"): 9},
        {tr("Feature family"): tr("Ten observed close-return lags"), tr("Feature count"): 10},
    ], hide_index=True, width="stretch")
    st.caption(tr("These policies reuse frozen HGB and downside-quantile models with their selected risk optimizer. No model is fitted in DEMO."))
    st.caption(tr("Both HGB policies share frozen Raw Top40 prediction scores. Portfolio weights are produced by their separate risk models; a model rank is not a weight rank."))
    if not presentation:
        st.json(identity)


def _verified_raw_model(model, cutoff):
    """HGB detail focus must not replace the independent full-pool Raw source."""
    if workspace_reader.is_updated(model) and not model.error:
        return model
    latest = workspace_reader.load_overview(source=workspace_reader.LATEST)
    if latest.error or cutoff == latest.decision_date:
        return latest
    available = tuple(day for day in latest.available_dates if day <= cutoff)
    if not available:
        return latest
    return workspace_reader.load_overview(available[-1], source=workspace_reader.LATEST,
                                         reference=workspace_reader.source_reference(latest))


def render_workspace(model, package, *, presentation=True, view="Overview"):
    """Extend the original workbench with three always-visible fixed strategies."""
    from apps.demo_console.pages.research import render_applied_performance, render_research
    from apps.demo_console.components.top20_table import render_applied_rankings
    from apps.demo_console.components.stock_history_search import render_applied_stock_history

    strategy_id = st.session_state["workspace_strategy"]
    cutoff = st.session_state.get("decision_date") or model.decision_date
    apply_style(presentation=presentation)
    title = {"Overview": "Applied strategies", "Portfolio": "Decisions & portfolio",
             "History": "Historical replay", "Research": "Performance & risk"}.get(view, view)
    st.html('<section class="uq-workspace-lead"><div><span class="uq-eyebrow">US TECH QUANT / 03 STRATEGIES</span>'
            + '<h1>' + text(tr(title)) + '</h1></div><div class="uq-workspace-observation"><span>'
            + text(tr("Observation date")) + '</span><strong>' + text(cutoff) + '</strong></div></section>')
    if st.session_state.get("workspace_sample") == "historical":
        st.info(tr("The selected HGB policies have no published training-period replay here. Choose the 2026 sample or Raw A2."))
        return
    raw_model = _verified_raw_model(model, cutoff)
    contexts = workspace_reader.load_applied_strategies(cutoff, package=package,
        sample=st.session_state.get("workspace_sample", "test_2026"), raw_model=raw_model)
    context = contexts[strategy_id]
    blocked = [tr(WORKSPACE_STRATEGIES[sid]) for sid, item in contexts.items() if item.get("status") == "BLOCKED"]
    if blocked:
        st.warning(tr("Unavailable strategies: {names}", names=" · ".join(blocked)))
    if view == "Research":
        render_research(raw_model, presentation=presentation, selected_package=package)
    elif view in ("Machine learning", "Evidence"):
        _workspace_model(context, package, presentation=presentation)
        if view == "Evidence":
            _source_details(package, presentation=presentation)
    else:
        comparison = render_applied_performance(contexts, package, cutoff, key_prefix="applied", statistics=False)
        with st.spinner(tr("Loading verified records…"), show_time=True):
            stock_history = workspace_reader.load_applied_stock_history(package=package, raw_model=raw_model, as_of=cutoff)
            snapshot = workspace_reader.load_applied_rankings(cutoff, package=package, raw_model=raw_model, history=stock_history)
        # Reuse the existing localized navigation and shared snapshots. Business
        # reads remain outside the display containers; changing a tab adds no source.
        decision_tab, history_tab, statistics_tab = localized_tabs(
            ("Decisions & portfolio", "Stock history across strategies", "Quantitative comparison"),
            key="applied_workspace_tools")
        with decision_tab:
            render_applied_rankings(cutoff, package, raw_model, snapshot=snapshot)
            _workspace_allocation_comparison(_exact_signal_contexts(contexts, cutoff), compact=view == "Overview")
        with history_tab:
            render_applied_stock_history(raw_model, package, cutoff, history=stock_history)
        with statistics_tab:
            render_comparison_statistics(comparison, key_prefix="applied")
        details = st.expander(tr("Selected strategy details") + " · " + tr(WORKSPACE_STRATEGIES[strategy_id]),
            expanded=False, on_change="rerun", key="applied_strategy_details")
        if details.open:
            with details:
                if strategy_id == "RAW_A2":
                    from apps.demo_console.pages.overview import render_overview
                    render_overview(raw_model, presentation=presentation, view="Portfolio" if view == "Portfolio" else "Overview")
                else:
                    _workspace_target(context)
        _source_details(package, presentation=presentation)
    st.caption(tr("Historical return records and current target allocations have separate dates. Target weights do not represent executed trades."))
