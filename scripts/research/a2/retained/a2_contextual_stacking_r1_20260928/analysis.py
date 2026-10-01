"""Descriptive paired analysis of the frozen M0/M1 replay paths.

No fit, parameter selection, winner reselection or alternative strategy replay
is present in this module. Same-account comparisons are explicitly diagnostic.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "a2_multimodel_joint_20260928"
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from replay import write, sha

OUT = ROOT / "paired_analysis"


def stock_cashflow_attribution(folder):
    """Full-path identity; no assumption that trade cash flows equal gains."""
    trades = pd.read_parquet(folder / "trades.parquet")
    daily = pd.read_parquet(folder / "daily.parquet")
    positions = pd.read_parquet(folder / "positions.parquet")
    last = daily.date.max()
    terminal = positions.loc[positions.date.eq(last)].groupby("ticker").market_value.sum()
    if trades.empty:
        return pd.DataFrame(columns=["ticker", "buy_notional", "sell_notional", "fees",
                                     "traded_notional", "trades", "end_market_value", "gross_price_pnl", "net_pnl"])
    buy = trades.loc[trades.side.eq("BUY")].groupby("ticker").notional.sum()
    sell = trades.loc[trades.side.eq("SELL")].groupby("ticker").notional.sum()
    totals = trades.groupby("ticker").agg(fees=("transaction_cost", "sum"),
        traded_notional=("notional", "sum"), trades=("notional", "size"))
    output = pd.concat([buy.rename("buy_notional"), sell.rename("sell_notional"),
                        terminal.rename("end_market_value"), totals], axis=1).fillna(0)
    output["gross_price_pnl"] = output.end_market_value+output.sell_notional-output.buy_notional
    output["net_pnl"] = output.gross_price_pnl-output.fees
    actual = float(daily.nav.iloc[-1]-1e6)
    error = float(output.net_pnl.sum()-actual)
    assert abs(error) < 1e-6, (folder, error)
    return output.reset_index()


def relative_daily(M0, M1):
    joined = M0.merge(M1, on="date", suffixes=("_M0", "_M1"), validate="one_to_one")
    result = pd.DataFrame({"date": joined.date})
    for name in ["nav", "cash_weight", "gross_exposure", "transaction_cost_amount", "turnover", "traded_notional"]:
        result[f"{name}_M0"] = joined[f"{name}_M0"]
        result[f"{name}_M1"] = joined[f"{name}_M1"]
        result[f"{name}_delta"] = joined[f"{name}_M1"]-joined[f"{name}_M0"]
    for method in ["M0", "M1"]:
        previous = result[f"nav_{method}"].shift(1).fillna(1e6)
        result[f"net_pnl_day_{method}"] = result[f"nav_{method}"]-previous
        result[f"gross_price_pnl_day_{method}"] = result[f"net_pnl_day_{method}"]+result[f"transaction_cost_amount_{method}"]
    for name in ["net_pnl_day", "gross_price_pnl_day"]:
        result[f"{name}_delta"] = result[f"{name}_M1"]-result[f"{name}_M0"]
    return result


def stock_daily_cashflow(folder):
    daily = pd.read_parquet(folder/"daily.parquet")
    positions = pd.read_parquet(folder/"positions.parquet")
    trades = pd.read_parquet(folder/"trades.parquet")
    tickers = sorted(set(positions.ticker) | set(trades.ticker))
    keys = pd.MultiIndex.from_product([pd.DatetimeIndex(daily.date), tickers], names=["date", "ticker"])
    result = pd.DataFrame(index=keys)
    result["market_value"] = positions.set_index(["date", "ticker"]).market_value.reindex(keys).fillna(0)
    result["previous_market_value"] = result.groupby(level="ticker").market_value.shift(1).fillna(0)
    for side, name in [("BUY", "buy_notional"), ("SELL", "sell_notional")]:
        amounts = trades.loc[trades.side.eq(side)].groupby(["execution_date", "ticker"]).notional.sum()
        amounts.index = amounts.index.set_names(["date", "ticker"])
        result[name] = amounts.reindex(keys).fillna(0)
    fees = trades.groupby(["execution_date", "ticker"]).transaction_cost.sum()
    fees.index = fees.index.set_names(["date", "ticker"])
    result["fees"] = fees.reindex(keys).fillna(0)
    result["gross_price_pnl"] = result.market_value-result.previous_market_value+result.sell_notional-result.buy_notional
    result["net_pnl"] = result.gross_price_pnl-result.fees
    actual = daily.set_index("date").nav.diff().fillna(daily.nav.iloc[0]-1e6)
    assert np.allclose(result.groupby(level="date").net_pnl.sum().reindex(actual.index, fill_value=0), actual, atol=1e-6, rtol=0)
    return result.reset_index()


def same_account_diagnostic(folder):
    pair = pd.read_parquet(folder / "same_account_pair.parquet")
    tol = 1e-8
    pair["target_difference"] = pair.M1_target-pair.M0_target
    pair["different_action"] = pair.target_difference.abs().gt(tol)
    pair["M0_direction"] = np.sign(np.where((pair.M0_target-pair.current_weight).abs() <= tol, 0,
                                             pair.M0_target-pair.current_weight))
    pair["M1_direction"] = np.sign(np.where((pair.M1_target-pair.current_weight).abs() <= tol, 0,
                                             pair.M1_target-pair.current_weight))
    pair["opposite_trade_direction"] = pair.M0_direction*pair.M1_direction < 0
    pair["M0_target_turnover"] = (pair.M0_target-pair.current_weight).abs()
    pair["M1_target_turnover"] = (pair.M1_target-pair.current_weight).abs()
    rows = []
    for date, frame in pair.groupby("signal_date", sort=True):
        set0 = set(frame.loc[frame.M0_target.gt(tol), "ticker"])
        set1 = set(frame.loc[frame.M1_target.gt(tol), "ticker"])
        utility_delta = frame[[f"M1_utility_a{j}" for j in range(5)]].to_numpy()-frame[[f"M0_utility_a{j}" for j in range(5)]].to_numpy()
        gain_delta = utility_delta-utility_delta[:, :1]
        rows.append(dict(signal_date=date, candidates=len(frame),
            different_actions=int(frame.different_action.sum()),
            opposite_directions=int(frame.opposite_trade_direction.sum()),
            M0_names=len(set0), M1_names=len(set1), selected_intersection=len(set0 & set1),
            selected_union=len(set0 | set1),
            selected_jaccard=len(set0 & set1)/len(set0 | set1) if set0 | set1 else 1.,
            M0_target_cash=1-float(frame.reserved_weight.iloc[0])-float(frame.M0_target.sum()),
            M1_target_cash=1-float(frame.reserved_weight.iloc[0])-float(frame.M1_target.sum()),
            target_l1=float(frame.target_difference.abs().sum()),
            M0_target_turnover=float(frame.M0_target_turnover.sum()),
            M1_target_turnover=float(frame.M1_target_turnover.sum()),
            action_value_abs_difference=float(np.mean(np.abs(utility_delta))),
            action_gain_abs_difference=float(np.mean(np.abs(gain_delta)))))
    daily = pd.DataFrame(rows)
    daily.to_csv(OUT / "same_account_daily_2025.csv", index=False)
    status = "POST_HOC_SAME_ACCOUNT_TARGET_DIAGNOSTIC_NOT_A_PORTFOLIO_REPLAY"
    summary = dict(status=status, account_source="M0_2025_cost10_actual_path", signals=len(daily),
        stockdays=len(pair), different_actions=int(pair.different_action.sum()),
        different_action_fraction=float(pair.different_action.mean()),
        opposite_directions=int(pair.opposite_trade_direction.sum()),
        date_equal_mean_jaccard=float(daily.selected_jaccard.mean()),
        date_equal_mean_target_l1=float(daily.target_l1.mean()),
        date_equal_M0_target_cash=float(daily.M0_target_cash.mean()),
        date_equal_M1_target_cash=float(daily.M1_target_cash.mean()),
        cumulative_M0_target_turnover=float(daily.M0_target_turnover.sum()),
        cumulative_M1_target_turnover=float(daily.M1_target_turnover.sum()),
        action_value_abs_difference=float(daily.action_value_abs_difference.mean()),
        action_gain_abs_difference=float(daily.action_gain_abs_difference.mean()),
        hypothetical_targets_executed=False, used_for_selection=False)
    return summary


def diagnostics_summary(folder):
    """Stream selected contribution and coverage without loading all columns."""
    source = pq.ParquetFile(folder / "action_diagnostics.parquet")
    names = source.schema_arrow.names
    columns = [x for x in names if x in ["signal_date", "ticker", "action_weight", "chosen_action", "chosen_weight", "current_weight", "cash_weight"]
               or x.startswith("contribution_") or "out_of_range" in x
               or x.startswith("expert_original_")]
    parts, active_parts = [], []
    for batch in source.iter_batches(columns=columns, batch_size=100000):
        frame = batch.to_pandas()
        # Keep every candidate's chosen action (including the explicit exit).
        frame = frame.loc[frame.chosen_action.astype(bool)].copy()
        if frame.empty:
            continue
        active = frame.loc[frame.chosen_weight.gt(0)].copy()
        if len(active):
            keep = [x for x in active if x in ["signal_date", "ticker", "chosen_weight", "current_weight", "cash_weight"]
                    or "out_of_range" in x or x.startswith("expert_original_")]
            active_parts.append(active[keep])
        contribution = [x for x in frame if x.startswith("contribution_")]
        if "contribution_base_ridge" in frame and "contribution_base_elastic_net" in frame:
            frame["contribution_ridge_elastic_combined"] = frame.contribution_base_ridge+frame.contribution_base_elastic_net
            contribution.append("contribution_ridge_elastic_combined")
        numeric = [x for x in frame if (x in contribution or "out_of_range" in x or x.startswith("expert_original_"))
                   and (pd.api.types.is_numeric_dtype(frame[x]) or pd.api.types.is_bool_dtype(frame[x]))]
        aggregated = frame.groupby("signal_date")[numeric].sum()
        aggregated["stockdays"] = frame.groupby("signal_date").size()
        parts.append(aggregated)
    full = pd.concat(parts).groupby(level=0).sum()
    mean = full.drop(columns="stockdays").div(full.stockdays, axis=0)
    mean.reset_index().to_csv(folder / "selected_meta_diagnostic_daily.csv", index=False)
    result = {name: float(value) for name, value in mean.mean().items()}
    active = pd.concat(active_parts, ignore_index=True) if active_parts else pd.DataFrame()
    active.to_csv(folder / "active_target_state_support.csv", index=False)
    result["active_target_stockdays"] = len(active)
    result["active_target_signal_dates"] = int(active.signal_date.nunique()) if len(active) else 0
    for name in mean:
        if "out_of_range" in name or name.startswith("expert_original_"):
            result[f"active_target_{name}"] = float(active[name].astype(float).mean()) if len(active) else None
    return result


def read_references():
    names = ["ensemble_equal_weight", "ensemble_stacked", "joint_hgb", "joint_mlp"]
    records = []
    for year, costs in [(2025, [10]), (2026, [5, 10, 25])]:
        for cost in costs:
            for name in names:
                path = OLD / f"evaluation_{year}" / f"cost_{cost}" / name / "DONE.json"
                if path.exists():
                    row = json.loads(path.read_text(encoding="utf-8"))
                    row.update(source_path=str(path), source_sha256=sha(path),
                               reference_status="FROZEN_PRIOR_BATCH_REFERENCE_NOT_RERUN_NOT_PRIMARY_NESTED_COMPARISON")
                    records.append(row)
    return records


def concentration_and_warning_diagnostic():
    """Post-hoc description of gains and inherited label-warning events."""
    base = ROOT / "evaluation_2025/cost_10"
    frames = {method: stock_daily_cashflow(base/method).set_index(["date", "ticker"])
              for method in ["M0", "M1"]}
    joined = frames["M0"].add_suffix("_M0").join(frames["M1"].add_suffix("_M1"), how="outer").fillna(0)
    for name in ["net_pnl", "gross_price_pnl", "fees", "market_value", "buy_notional", "sell_notional"]:
        joined[f"{name}_delta"] = joined[f"{name}_M1"]-joined[f"{name}_M0"]
    joined.reset_index().to_parquet(OUT / "paired_stock_daily_2025_cost10.parquet", index=False)
    stock = joined.groupby(level="ticker").net_pnl_delta.sum().sort_values(ascending=False)
    date = joined.groupby(level="date").net_pnl_delta.sum().sort_values(ascending=False)
    stock.rename("net_pnl_delta").reset_index().to_csv(OUT/"2025_stock_delta_concentration.csv", index=False)
    date.rename("net_pnl_delta").reset_index().to_csv(OUT/"2025_date_delta_concentration.csv", index=False)
    warning_path = ROOT/"panel_artifacts/label_warning_source_keys.parquet"
    warnings = pd.read_parquet(warning_path)
    warnings = warnings.loc[pd.to_datetime(warnings.signal_date).dt.year.eq(2025)].copy()
    observations = []
    union = set()
    for event in warnings.to_dict("records"):
        ticker = str(event["ticker"])
        lo, hi = pd.Timestamp(event["signal_date"]), pd.Timestamp(event["label_end_date"])
        dates = joined.index.get_level_values("date")
        mask = ((joined.index.get_level_values("ticker") == ticker) & (dates > lo) & (dates <= hi))
        part = joined.loc[mask]
        union.update(part.index.tolist())
        row = {**event, "diagnostic_status":"POST_HOC_INHERITED_SOURCE_LABEL_WARNING_DIAGNOSTIC",
            "actual_pnl_window":"signal_date < execution/valuation date <= label_end_date",
            "stocks_days_matched":len(part),
            "net_pnl_delta_in_window":float(part.net_pnl_delta.sum()),
            "gross_price_pnl_delta_in_window":float(part.gross_price_pnl_delta.sum()),
            "fee_delta_in_window":float(part.fees_delta.sum())}
        for method in ["M0", "M1"]:
            row[f"net_pnl_in_window_{method}"] = float(part[f"net_pnl_{method}"].sum())
            row[f"market_value_max_in_window_{method}"] = float(part[f"market_value_{method}"].max()) if len(part) else 0.
            row[f"buy_notional_in_window_{method}"] = float(part[f"buy_notional_{method}"].sum())
            row[f"sell_notional_in_window_{method}"] = float(part[f"sell_notional_{method}"].sum())
            row[f"net_pnl_full_year_{method}"] = float(joined.xs(ticker, level="ticker")[f"net_pnl_{method}"].sum()) if ticker in joined.index.get_level_values("ticker") else 0.
        observations.append(row)
    pd.DataFrame(observations).to_csv(OUT/"2025_inherited_label_warning_account_intersections.csv", index=False)
    window_total = joined.loc[list(union), "net_pnl_delta"].sum() if union else 0.
    positive_stock = stock[stock > 0]
    positive_day = date[date > 0]
    result = dict(status="POST_HOC_CONCENTRATION_AND_INHERITED_PRICE_LABEL_DIAGNOSTIC",
        year=2025, cost_bps=10, fitting_or_strategy_changes=False,
        net_pnl_delta_total=float(stock.sum()),
        positive_stock_contributions=float(positive_stock.sum()), negative_stock_contributions=float(stock[stock < 0].sum()),
        top5_positive_stock_delta=float(positive_stock.head(5).sum()),
        top5_share_of_positive_stock_delta=float(positive_stock.head(5).sum()/positive_stock.sum()) if len(positive_stock) else None,
        top5_positive_stock_names=positive_stock.head(5).index.tolist(),
        positive_daily_contributions=float(positive_day.sum()),
        top5_positive_day_delta=float(positive_day.head(5).sum()),
        top5_share_of_positive_daily_delta=float(positive_day.head(5).sum()/positive_day.sum()) if len(positive_day) else None,
        top5_positive_days=[str(d.date()) for d in positive_day.head(5).index],
        inherited_source_label_warning_events=len(warnings),
        inherited_warning_event_stockday_net_delta=float(window_total),
        inherited_warning_whole_stock_year_net_delta=float(stock.reindex(warnings.ticker.unique()).fillna(0).sum()),
        price_values_filtered_or_repaired=False,
        warning_reason_semantics="source boolean only; no cause or historical knowledge time fabricated",
        source_warning_file_sha256=sha(warning_path))
    write(OUT/"2025_CONCENTRATION_AND_LABEL_WARNING.json", result)
    return result


def make_plot(metrics):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for col, year in enumerate([2025, 2026]):
        for method, color in [("M0", "#3966a6"), ("M1", "#cc6a2f")]:
            d = pd.read_parquet(ROOT / f"evaluation_{year}" / "cost_10" / method / "daily.parquet")
            axes[0, col].plot(d.date, d.nav/1e6, label=method, color=color)
            axes[1, col].plot(d.date, d.cash_weight*100, label=method, color=color, linewidth=1)
        axes[0, col].set_title(f"{year}: fixed 10 bp replay" + (" (indicative only)" if year == 2026 else ""))
        axes[0, col].set_ylabel("NAV / initial NAV")
        axes[1, col].set_ylabel("Cash (%)")
        for row in range(2):
            axes[row, col].legend()
            axes[row, col].grid(alpha=.2)
            axes[row, col].tick_params(axis="x", rotation=25)
    fig.savefig(OUT / "paired_paths.png", dpi=160)
    plt.close(fig)


def write_analysis_note(metrics, differences, proof, same, concentration):
    stock_share = (f"{concentration['top5_share_of_positive_stock_delta']:.2%}"
                   if concentration['top5_share_of_positive_stock_delta'] is not None else "无正增量")
    day_share = (f"{concentration['top5_share_of_positive_daily_delta']:.2%}"
                 if concentration['top5_share_of_positive_daily_delta'] is not None else "无正增量")
    lines = ["# 固定规格 M0 与 M1 的配对经济分解", "",
             "本目录只对冻结推理账本做描述性分析。M0/M1共享专家、分配器、风险效用定义与成交规则；各自的完整账户路径不同。2025、2026均已被项目观察过，本研究不称为盲测。", "",
             "2025使用validation专家与2024元面板拟合工件；2026使用final专家与2024+2025元面板最终工件，2026只推理。主成本为单边10bp，5/25bp为固定敏感性，元模型不随成本场景重新拟合。", "",
             "| 年份 | 成本bp | 方法 | 净值变化 | 最大回撤 | 平均现金 | 费用美元 | 换手 | 未认证估值日 |",
             "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in metrics.sort_values(["year", "cost_bps", "policy"]).itertuples():
        lines.append(f"| {r.year} | {r.cost_bps:g} | {r.policy} | {r.indicative_return:.2%} | {r.indicative_max_drawdown:.2%} | {r.mean_cash_weight:.2%} | {r.total_cost_dollars:,.2f} | {r.turnover:.3f} | {r.uncertified_valuation_days} |")
    lines += ["", "2025指标为回溯价格指数路径，2026受限股票池、原价格认证缺口与原GLW隔离继续保留，仅作诊断性净值。指数单位不等于可认证原始股数，二者都不是认证的股东总回报。", "",
              "现金流逐股身份为：价格损益＝期末持仓市值＋卖出额−买入额；净损益＝价格损益−实际费用。逐股净损益合计与期末NAV−初始100万美元相等。这里的价格损益来自已经执行的账户路径，不代表另外运行零成本策略的收益。", "",
              "| 年份 | 成本bp | M1−M0净损益美元 | 价格损益差美元 | 费用差美元 | 净值变化差 | 平均现金差 | 回撤差 | 波动差 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    facts = pd.DataFrame(proof)
    for r in pd.DataFrame(differences).sort_values(["year", "cost_bps"]).itertuples():
        a = facts.loc[(facts.year == r.year) & (facts.cost_bps == r.cost_bps) & (facts.method == "M0")].iloc[0]
        b = facts.loc[(facts.year == r.year) & (facts.cost_bps == r.cost_bps) & (facts.method == "M1")].iloc[0]
        lines.append(f"| {r.year} | {r.cost_bps:g} | {b.net_stock_pnl-a.net_stock_pnl:,.2f} | {b.gross_price_pnl-a.gross_price_pnl:,.2f} | {b.fees-a.fees:,.2f} | {r.return_delta:.2%} | {r.mean_cash_delta:.2%} | {r.max_drawdown_delta:.2%} | {r.volatility_delta:.2%} |")
    lines += ["", "上表差值均为M1−M0；回撤差为负表示回撤更深。费用差为正表示M1费用更多。原始收益差须结合敞口、回撤、波动和费用判断，不能只凭收益排序声称发现了稳定互补。", "",
              "2025主成本的同账户比较只在M0实际信号账户上给两个冻结元模型相同p/z/basis及同一完整可决策候选集合，随后调用同一原分配器。M1的这些目标没有进入执行账本。该比较明确标为事后诊断，不能把其目标或单步效用当作完整策略收益。", "",
              f"同账户股票日动作不同占比 {same['different_action_fraction']:.2%}，日期等权TOP20集合Jaccard {same['date_equal_mean_jaccard']:.4f}，日均目标L1差 {same['date_equal_mean_target_l1']:.4f}；平均目标现金 M0 {same['date_equal_M0_target_cash']:.2%}、M1 {same['date_equal_M1_target_cash']:.2%}。", "",
              f"2025主口径的正股票增量中，前5股票占 {stock_share}；正日增量中，前5日期占 {day_share}。集中性是事后描述，不用于重选或拟合。", "",
              f"继承原source label_price_warning的2025事件共 {concentration['inherited_source_label_warning_events']} 个；对应事件窗口股票的M1−M0净损益合计 {concentration['inherited_warning_event_stockday_net_delta']:,.2f} 美元，相关股票全年净损益差合计 {concentration['inherited_warning_whole_stock_year_net_delta']:,.2f} 美元。该警告只有原始bool，不能当作已确认错价；原PRICE无对应price_quality_warning过滤，故本实验保留原口径并揭示交叉影响，未删除或修复价格。", "",
              "逐日有效系数用于动作效用刻度转换，不是资金分配比例或模型正确概率。冻结监督value专家（Ridge、Elastic Net、Logistic、HGB、分位数）的三网格精确点/现金仓位共线关系，与其逐维数值包络分别记录；这些grid字段不概括direct MLP的训练状态支持。新元层四状态训练范围外同样逐股票动作记录。落在数值包络内不证明监督value专家已经在这些账户组合上训练过，也不证明元层有充分联合状态密度。", "",
              "文件索引：ALL_RESULTS.csv为12条完整路径；M1_MINUS_M0.csv为固定配对差；paired_stock_delta_*为各股票价格损益/费用差；same_account_daily_2025.csv为事后同账户目标分歧；STATE_AND_CONTRIBUTION_SUMMARY.csv为按日期聚合的状态覆盖与选定动作贡献；PRIOR_FROZEN_REFERENCES.csv只复用旧DONE工件，不重跑、不作为严格嵌套主对照。", ""]
    (OUT / "ECONOMIC_ANALYSIS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    rows, differences, proof, coverage = [], [], [], []
    for year in [2025, 2026]:
        for cost in [10, 5, 25]:
            base = ROOT / f"evaluation_{year}" / f"cost_{cost}"
            complete = json.loads((base / "COMPLETE.json").read_text(encoding="utf-8"))
            assert complete["status"] == "FROZEN_PAIRED_REPLAY_COMPLETE"
            stocks, ds, records = {}, {}, {}
            for method in ["M0", "M1"]:
                folder = base / method
                row = json.loads((folder / "DONE.json").read_text(encoding="utf-8"))
                rows.append(row)
                records[method] = row
                stocks[method] = stock_cashflow_attribution(folder)
                stocks[method].to_csv(OUT / f"stock_attribution_{year}_cost{cost}_{method}.csv", index=False)
                ds[method] = pd.read_parquet(folder / "daily.parquet")
                summary = diagnostics_summary(folder)
                coverage.append(dict(year=year, cost_bps=cost, method=method, **summary))
                proof.append(dict(year=year, cost_bps=cost, method=method,
                    net_stock_pnl=float(stocks[method].net_pnl.sum()),
                    gross_price_pnl=float(stocks[method].gross_price_pnl.sum()),
                    fees=float(stocks[method].fees.sum()),
                    terminal_nav_minus_initial=float(ds[method].nav.iloc[-1]-1e6),
                    runtime_receipt_sha256=sha(folder / "RUNTIME_LOAD_RECEIPT.json"),
                    ledger_acceptance=json.loads((folder / "LEDGER_ACCEPTANCE.json").read_text(encoding="utf-8"))["status"]))
            daily = relative_daily(ds["M0"], ds["M1"])
            daily.to_parquet(OUT / f"paired_daily_{year}_cost{cost}.parquet", index=False)
            combined = stocks["M0"].set_index("ticker").add_suffix("_M0").join(
                       stocks["M1"].set_index("ticker").add_suffix("_M1"), how="outer").fillna(0)
            for name in ["gross_price_pnl", "net_pnl", "fees", "traded_notional", "end_market_value"]:
                combined[f"{name}_delta"] = combined[f"{name}_M1"]-combined[f"{name}_M0"]
            combined.reset_index().sort_values("net_pnl_delta", ascending=False).to_csv(
                OUT / f"paired_stock_delta_{year}_cost{cost}.csv", index=False)
            a, b = records["M0"], records["M1"]
            differences.append(dict(year=year, cost_bps=cost,
                return_delta=b["indicative_return"]-a["indicative_return"],
                max_drawdown_delta=b["indicative_max_drawdown"]-a["indicative_max_drawdown"],
                volatility_delta=b["indicative_annualized_volatility"]-a["indicative_annualized_volatility"],
                mean_cash_delta=b["mean_cash_weight"]-a["mean_cash_weight"],
                mean_exposure_delta=b["mean_gross_exposure"]-a["mean_gross_exposure"],
                fee_delta=b["total_cost_dollars"]-a["total_cost_dollars"],
                turnover_delta=b["turnover"]-a["turnover"],
                max_names_M0=a["max_actual_names"], max_names_M1=b["max_actual_names"],
                uncertified_days_M0=a["uncertified_valuation_days"], uncertified_days_M1=b["uncertified_valuation_days"],
                selection_status="FIXED_SPECIFICATION_COMPARISON_NO_2026_SELECTION"))
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / "ALL_RESULTS.csv", index=False)
    pd.DataFrame(differences).to_csv(OUT / "M1_MINUS_M0.csv", index=False)
    pd.DataFrame(coverage).to_csv(OUT / "STATE_AND_CONTRIBUTION_SUMMARY.csv", index=False)
    write(OUT / "LEDGER_CASHFLOW_PROOF.json", dict(status="PASS", paths=proof, fit_calls=0))
    pd.DataFrame(read_references()).to_csv(OUT / "PRIOR_FROZEN_REFERENCES.csv", index=False)
    same = same_account_diagnostic(ROOT / "evaluation_2025/cost_10/M0")
    write(OUT / "SAME_ACCOUNT_DIAGNOSTIC.json", same)
    concentration = concentration_and_warning_diagnostic()
    make_plot(metrics)
    write_analysis_note(metrics, differences, proof, same, concentration)
    write(OUT / "ANALYSIS_RECEIPT.json", dict(status="FROZEN_PAIRED_ANALYSIS_COMPLETE",
        paths=12, diagnostic_status=same["status"], fit_calls=0, selection_using_2026=False,
        source_hashes={str(ROOT / f"evaluation_{year}" / f"cost_{cost}" / method / "DONE.json"):
            sha(ROOT / f"evaluation_{year}" / f"cost_{cost}" / method / "DONE.json")
            for year in [2025, 2026] for cost in [5, 10, 25] for method in ["M0", "M1"]}))
    print(metrics[["policy", "year", "cost_bps", "indicative_return", "indicative_max_drawdown",
                   "mean_cash_weight", "total_cost_dollars", "turnover", "uncertified_valuation_days"]].to_string(index=False))
    print(json.dumps(same, ensure_ascii=False, indent=2))
    print(json.dumps(concentration, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
