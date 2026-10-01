"""Read-only trace of saved held positions lacking latest-target metadata.

Reads saved inputs and replay artifacts only. No fit, prediction, replay, price
replacement, imputed identity, original-file edits, or external data requests.
Writes this directory's audit tables, short report, and receipt.
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SIGNAL = pd.Timestamp("2026-09-22")
EXECUTION = pd.Timestamp("2026-09-23")
TERMINAL = pd.Timestamp("2026-09-24")
DATES = (SIGNAL, EXECUTION, TERMINAL)
SOURCES = {}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def track(path):
    path = Path(path).resolve()
    SOURCES[str(path)] = sha(path)
    return path


def parquet(path):
    return pd.read_parquet(track(path))


def read_json(path):
    return json.loads(track(path).read_text(encoding="utf-8"))


def positive(value):
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) > 0)


def scalar(frame, message):
    assert len(frame) == 1, f"{message}: expected exactly one row, got {len(frame)}"
    return frame.iloc[0]


def same(a, b):
    return bool(np.isclose(float(a), float(b), rtol=1e-10, atol=1e-10, equal_nan=True))


def dated(value):
    return "" if pd.isna(value) else str(pd.Timestamp(value).date())


def price_evidence(prices, ticker, date):
    rows = prices.loc[(prices.ticker == ticker) & (prices.trade_date == date)]
    assert len(rows) <= 1
    result = {"price_row_present": bool(len(rows)), "stored_open": np.nan, "stored_close": np.nan,
              "stored_raw_open": np.nan, "stored_raw_close": np.nan, "stored_open_positive": False,
              "price_quality_warning": False, "unresolved_event_on_or_before": False,
              "lifecycle_ended": False, "extreme_adjusted_jump": False,
              "execution_price_evidence": "NO_SAVED_PRICE_ROW"}
    if len(rows):
        row = rows.iloc[0]
        result.update(stored_open=row.open, stored_close=row.close,
                      stored_raw_open=row.raw_open, stored_raw_close=row.raw_close,
                      stored_open_positive=positive(row.open))
        for flag in ["price_quality_warning", "unresolved_event_on_or_before", "lifecycle_ended", "extreme_adjusted_jump"]:
            result[flag] = bool(row[flag])
        if not result["stored_open_positive"]:
            result["execution_price_evidence"] = "SAVED_OPEN_MISSING_OR_NONPOSITIVE"
        elif result["price_quality_warning"]:
            result["execution_price_evidence"] = "POSITIVE_SAVED_OPEN_BUT_QUALITY_UNCERTIFIED"
        else:
            result["execution_price_evidence"] = "POSITIVE_SAVED_OPEN_NOT_FLAGGED"
    return result


def main():
    target_path = ROOT / "LAST_TEST_DATE_TARGETS.csv"
    target = pd.read_csv(track(target_path), dtype={"ticker": str, "quarter": str, "cusip": str})
    for field in ["signal_date", "execution_date"]:
        target[field] = pd.to_datetime(target[field])
    missing = target[["quarter", "cusip", "new_buy_eligible"]].isna().any(axis=1)
    cases = target.loc[missing].copy().sort_values(["policy", "ticker"]).reset_index(drop=True)
    assert len(target) == 302 and len(cases) == 54
    assert not cases.duplicated(["policy", "ticker"]).any()
    assert cases.signal_date.eq(SIGNAL).all() and cases.execution_date.eq(EXECUTION).all()
    assert cases.target_weight.eq(0).all() and cases.current_weight.gt(0).all()
    features = parquet(ROOT / "data/test_features_context.parquet")
    prices = parquet(ROOT / "data/test_prices.parquet")
    current_inputs = features.loc[features.signal_date == SIGNAL]
    assert not current_inputs.ticker.duplicated().any()
    comparison = pd.read_csv(track(ROOT / "evaluation_2026/cost_10/comparison.csv"))
    assert comparison.cost_bps_per_side.eq(10).all() and not comparison.policy.duplicated().any()
    roster = sorted(comparison.policy.unique())
    assert set(target.policy).issubset(roster)
    ledgers = {}
    for policy in roster:
        directory = ROOT / "evaluation_2026/cost_10" / f"{policy}_10bps"
        ledgers[policy] = {name: parquet(directory / f"{name}.parquet")
                           for name in ["target_decisions", "positions", "trades", "diagnostics", "daily"]}
        ledgers[policy]["metadata"] = read_json(directory / "metadata.json")
    rows = []
    occupancy = []
    for case in cases.itertuples(index=False):
        ledger = ledgers[case.policy]
        q, p, t, diag, daily = [ledger[n] for n in ["target_decisions", "positions", "trades", "diagnostics", "daily"]]
        decision = scalar(q.loc[(q.signal_date == SIGNAL) & (q.ticker == case.ticker)], f"decision {case.policy}/{case.ticker}")
        assert same(decision.target_weight, case.target_weight) and same(decision.current_weight, case.current_weight)
        assert decision.execution_date == EXECUTION and decision.status == "submitted"
        model_input = current_inputs.loc[current_inputs.ticker == case.ticker]
        historical = features.loc[(features.ticker == case.ticker) & (features.signal_date < SIGNAL)].sort_values("signal_date")
        past = historical.iloc[-1] if len(historical) else None
        fills = t.loc[(t.execution_date == EXECUTION) & (t.ticker == case.ticker)]
        refusal = diag.loc[(diag.date == EXECUTION) & (diag.ticker == case.ticker)]
        history_refusal = diag.loc[(diag.ticker == case.ticker) & diag.date.le(EXECUTION) & diag.code.eq("missing_open_sell")]
        price_history = prices.loc[(prices.ticker == case.ticker) & prices.trade_date.le(TERMINAL)]
        evidence = price_evidence(prices, case.ticker, EXECUTION)
        row = {
            "policy": case.policy, "ticker": case.ticker,
            "signal_date": dated(SIGNAL), "execution_date": dated(EXECUTION),
            "missing_metadata_fields": "|".join(c for c in ["quarter", "cusip", "new_buy_eligible"] if pd.isna(getattr(case, c))),
            "model_input_row_present": bool(len(model_input)), "model_input_row_count": len(model_input),
            "target_weight_recorded": float(decision.target_weight), "current_weight_recorded": float(decision.current_weight),
            "target_status": decision.status, "whole_signal_day_missing_cash_fallback": bool(decision.missing_signal_cash),
            "target_origin_evidence": "CURRENT_INPUT_ROW_ABSENT_ZERO_TARGET_RECORD" if model_input.empty else "CURRENT_INPUT_ROW_PRESENT",
            "raw_policy_dictionary_persisted_in_these_sources": False,
            "model_active_exit_proven": False,
            "input_absence_is_not_proof_numeric_features_missing": True,
            "original_export_intended_action": case.intended_action,
            "last_prior_input_date": "" if past is None else dated(past.signal_date),
            "last_prior_input_quarter_historical_only": "" if past is None else str(past.quarter),
            "last_prior_input_cusip_historical_only": "" if past is None else str(past.cusip),
            "last_saved_price_date": "" if price_history.empty else dated(price_history.trade_date.max()),
            "execution_diagnostic_codes": "|".join(sorted(refusal.code.unique())),
            "missing_open_sell_recorded": bool(refusal.code.eq("missing_open_sell").any()),
            "execution_fill_count": len(fills), "execution_sell_notional": float(fills.loc[fills.side == "SELL", "notional"].sum()),
            "execution_buy_notional": float(fills.loc[fills.side == "BUY", "notional"].sum()),
            "first_saved_missing_open_sell_date": "" if history_refusal.empty else dated(history_refusal.date.min()),
            "saved_missing_open_sell_attempts_through_execution": len(history_refusal),
            **evidence,
        }
        units = []
        for date in DATES:
            suffix = date.strftime("%Y%m%d")
            position = scalar(p.loc[(p.date == date) & (p.ticker == case.ticker)], f"position {case.policy}/{case.ticker}/{date}")
            account = scalar(daily.loc[daily.date == date], f"daily {case.policy}/{date}")
            assert positive(position.index_units)
            assert same(position.weight, position.market_value / account.nav)
            if date == SIGNAL:
                assert same(position.weight, decision.current_weight)
            units.append(float(position.index_units))
            values = {"index_units": float(position.index_units), "indicative_market_value": float(position.market_value),
                      "indicative_nav_weight": float(position.weight), "mark": float(position.mark),
                      "mark_date": dated(position.mark_date), "mark_source": position.mark_source,
                      "stale": bool(position.stale), "unknown": bool(position.unknown),
                      "account_cash": float(account.cash), "account_indicative_nav": float(account.nav),
                      "account_certified_nav": float(account.certified_nav) if pd.notna(account.certified_nav) else np.nan,
                      "account_actual_names": int(account.actual_name_count), "held_slot_count": 1}
            row.update({f"{key}_{suffix}": value for key, value in values.items()})
            occupancy.append({"policy": case.policy, "ticker": case.ticker, "date": dated(date), **values})
        row["units_unchanged_0922_0923_0924"] = all(same(units[0], value) for value in units[1:])
        rows.append(row)
    detail = pd.DataFrame(rows)
    assert (~detail.model_input_row_present).all()
    assert detail.missing_open_sell_recorded.all()
    assert detail.execution_fill_count.eq(0).all()
    assert detail.units_unchanged_0922_0923_0924.all()
    assert not detail.whole_signal_day_missing_cash_fallback.any()
    assert detail.execution_price_evidence.isin(["POSITIVE_SAVED_OPEN_BUT_QUALITY_UNCERTIFIED", "NO_SAVED_PRICE_ROW"]).all()
    present_unverified = detail.loc[detail.execution_price_evidence.eq("POSITIVE_SAVED_OPEN_BUT_QUALITY_UNCERTIFIED")]
    assert present_unverified.price_quality_warning.all() and present_unverified.unresolved_event_on_or_before.all()

    blocked_rows = []
    all_policy_rows = []
    for policy in roster:
        ledger = ledgers[policy]
        q, p, t, diag, daily = [ledger[n] for n in ["target_decisions", "positions", "trades", "diagnostics", "daily"]]
        blocks = diag.loc[(diag.date == EXECUTION) & diag.code.isin(["live_position_limit", "live_position_cap"])]
        assert not blocks.duplicated(["date", "ticker"]).any()
        account = scalar(daily.loc[daily.date == EXECUTION], f"blocked daily {policy}")
        prior_names = set(p.loc[p.date == SIGNAL, "ticker"])
        end_names = set(p.loc[p.date == EXECUTION, "ticker"])
        for event in blocks.itertuples(index=False):
            decision = scalar(q.loc[(q.signal_date == SIGNAL) & (q.ticker == event.ticker)], f"cap target {policy}/{event.ticker}")
            input_row = scalar(current_inputs.loc[current_inputs.ticker == event.ticker], f"cap input {policy}/{event.ticker}")
            fills = t.loc[(t.execution_date == EXECUTION) & (t.ticker == event.ticker)]
            was_new = event.ticker not in prior_names and same(decision.current_weight, 0)
            record = {"policy": policy, "ticker": event.ticker, "signal_date": dated(SIGNAL), "execution_date": dated(EXECUTION),
                      "diagnostic_code": event.code, "target_weight": float(decision.target_weight),
                      "current_weight_at_signal": float(decision.current_weight), "model_input_row_present": True,
                      "new_buy_eligible": bool(input_row.new_buy_eligible), "new_position_attempt": was_new,
                      "execution_fill_count": len(fills), "held_at_execution_close": event.ticker in end_names,
                      "end_of_execution_day_actual_names": int(account.actual_name_count),
                      "max_positions": int(ledger["metadata"]["max_positions"]),
                      "account_cash_end_execution_day": float(account.cash),
                      "affected_missing_metadata_old_slots": int(cases.policy.eq(policy).sum()),
                      "counterfactual_fill_if_old_positions_sold_not_evaluated": True}
            assert was_new and record["new_buy_eligible"] and decision.target_weight > 0
            assert len(fills) == 0 and not record["held_at_execution_close"]
            assert record["end_of_execution_day_actual_names"] == record["max_positions"]
            blocked_rows.append(record)
        all_policy_rows.append({"policy": policy, "missing_metadata_old_holdings": int(cases.policy.eq(policy).sum()),
                                "new_position_orders_blocked_by_live_position_limit": len(blocks),
                                "actual_names_20260923": int(account.actual_name_count),
                                "cash_20260923": float(account.cash),
                                "all_execution_diagnostics_20260923": json.dumps(diag.loc[diag.date == EXECUTION, "code"].value_counts().to_dict(), sort_keys=True)})
    blocked = pd.DataFrame(blocked_rows)
    all_policies = pd.DataFrame(all_policy_rows)
    summaries = []
    for policy, group in detail.groupby("policy", sort=True):
        allrow = scalar(all_policies.loc[all_policies.policy == policy], f"policy summary {policy}")
        result = {"policy": policy, "affected_old_holdings": len(group), "model_input_rows_absent": int((~group.model_input_row_present).sum()),
                  "zero_target_records": int(group.target_weight_recorded.eq(0).sum()),
                  "active_model_exit_proven": int(group.model_active_exit_proven.sum()),
                  "positive_saved_open_but_quality_uncertified": int(group.execution_price_evidence.eq("POSITIVE_SAVED_OPEN_BUT_QUALITY_UNCERTIFIED").sum()),
                  "no_saved_execution_price_row": int(group.execution_price_evidence.eq("NO_SAVED_PRICE_ROW").sum()),
                  "execution_missing_open_sell_refusals": int(group.missing_open_sell_recorded.sum()),
                  "actual_execution_fills_on_affected_holdings": int(group.execution_fill_count.sum()),
                  "new_position_orders_blocked_by_live_position_limit": int(allrow.new_position_orders_blocked_by_live_position_limit)}
        for date in DATES:
            suffix = date.strftime("%Y%m%d")
            nav = float(group[f"account_indicative_nav_{suffix}"].iloc[0])
            total = float(group[f"indicative_market_value_{suffix}"].sum())
            names = int(group[f"account_actual_names_{suffix}"].iloc[0])
            slots = int(group[f"held_slot_count_{suffix}"].sum())
            result.update({f"old_indicative_value_{suffix}": total, f"old_fraction_of_indicative_nav_{suffix}": total / nav,
                           f"old_occupied_slots_{suffix}": slots, f"account_actual_names_{suffix}": names,
                           f"old_fraction_of_20_slot_limit_{suffix}": slots / 20,
                           f"account_cash_{suffix}": float(group[f"account_cash_{suffix}"].iloc[0]),
                           f"account_indicative_nav_{suffix}": nav,
                           f"old_stale_positions_{suffix}": int(group[f"stale_{suffix}"].sum())})
        summaries.append(result)
    summary = pd.DataFrame(summaries)
    outputs = {
        "MISSING_METADATA_HOLDINGS_DETAIL.csv": detail,
        "MISSING_METADATA_HOLDINGS_DAILY_OCCUPANCY.csv": pd.DataFrame(occupancy),
        "MISSING_METADATA_HOLDINGS_BY_POLICY.csv": summary,
        "LIVE_POSITION_LIMIT_BLOCKED_NEW_BUYS_20260923.csv": blocked,
        "ALL_POLICIES_EXECUTION_20260923.csv": all_policies,
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    no_row = detail.loc[detail.execution_price_evidence.eq("NO_SAVED_PRICE_ROW")]
    source_unchanged = all(sha(path) == expected for path, expected in SOURCES.items())
    assert source_unchanged, "source file changed during this read-only audit"
    receipt = {
        "status": "PASS", "scope": "saved cost-10-bps artifacts only; no model fit, inference or replay",
        "target_export_rows": len(target), "affected_policy_ticker_rows": len(detail), "affected_policies": len(summary),
        "all_cost10_policies_checked": len(roster),
        "unique_affected_tickers": detail.ticker.nunique(), "model_input_row_absent_count": int((~detail.model_input_row_present).sum()),
        "model_active_exit_proven_count": 0, "missing_open_sell_refusals": int(detail.missing_open_sell_recorded.sum()),
        "actual_execution_fills_on_affected_rows": int(detail.execution_fill_count.sum()),
        "unchanged_units_across_three_closes": int(detail.units_unchanged_0922_0923_0924.sum()),
        "positive_saved_open_but_quality_uncertified_rows": int(detail.execution_price_evidence.eq("POSITIVE_SAVED_OPEN_BUT_QUALITY_UNCERTIFIED").sum()),
        "no_saved_execution_price_rows": len(no_row), "no_saved_execution_price_tickers": sorted(no_row.ticker.unique()),
        "blocked_new_position_orders_20260923": len(blocked), "blocked_new_position_policies": blocked.policy.nunique(),
        "blocked_new_position_unique_tickers": blocked.ticker.nunique(),
        "sources_unchanged_before_after": source_unchanged, "source_files_hashed": len(SOURCES),
        "fit_calls": 0, "model_inference_calls": 0, "ledger_replays": 0, "external_requests": 0,
        "source_sha256": SOURCES,
        "evidence_limits": [
            "Current model input row absent does not imply numeric raw features do not exist.",
            "Raw policy target dictionaries, logits and last_actions were not persisted in these sources; a zero target is not proof of active model exit.",
            "Price row absent means absent from this saved dataset; it does not prove no market quote existed.",
            "Positive prices with a quality-warning flag are uncertified observations, not missing quoted values.",
            "Old-position values use stored stale price-index marks; they are neither certified liquidation proceeds nor raw shareholder-share valuations.",
            "Policies are separate nominal accounts. Cross-policy sums are audit counts, not a combined investable portfolio.",
            "Live-position-cap diagnostic orders are observed refusals. Counterfactual fills after hypothetical old-stock liquidation were not simulated.",
        ],
    }
    lines = [
        "# 54 条缺字段旧仓的成交、拒单和占用核对", "",
        "只读取已存 10 bps 场景账本、目标表、输入表与价格表；没有训练、推理、重放或修改原文件。", "",
        f"原目标表 {len(target)} 行中，{len(detail)} 行属于 {len(summary)} 个策略、{detail.ticker.nunique()} 个股票代码。全部在 2026-09-22 已持有、目标权重为 0，且当日模型输入表没有该股票行。这里的缺输入行不等于数值特征不存在。", "",
        "这些是缺当前输入行后出现的零目标记录，不能把导出表的“退出”标签当作模型主动判断。本次证据中没有持久化原始策略字典、logits 或动作评分；模型主动退出的可证明数量为 0。默认零值的源码链条由主审报告解释。", "",
        f"09-23 的 {len(detail)} 条旧仓都记录 missing_open_sell，均没有成交，09-22、09-23、09-24 收盘持仓单位保持不变。", "",
        f"其中 {receipt['positive_saved_open_but_quality_uncertified_rows']} 条策略持仓行的存档 open 为正，但 price_quality_warning=True、unresolved_event_on_or_before=True：有价格数值但未核证。另 {len(no_row)} 条（{', '.join(sorted(no_row.ticker.unique()))}）在存档价格表中没有 09-23 行；不能将这两类原因混写成行情全部缺失。", "",
        f"09-23 共 {len(blocked)} 个新仓目标被 live_position_limit 拒绝，分布在 {blocked.policy.nunique()} 个策略；全部当日输入存在、允许新增、原持仓为零、目标权重大于零，且没有成交。该数量按“策略×股票”的订单计，不是股票去重数。是否在假设旧仓售出后一定成交，本次没有做反事实重放。", "",
        "| 策略 | 旧仓条数/占用名额 | 09-23 旧仓陈旧估值 | 占当日指示性 NAV | 09-23 账户现金 | 被名额上限拒绝的新仓 |", 
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.itertuples(index=False):
        lines.append(f"| {row.policy} | {row.affected_old_holdings} / 20 | {row.old_indicative_value_20260923:,.2f} | {row.old_fraction_of_indicative_nav_20260923:.2%} | {row.account_cash_20260923:,.2f} | {row.new_position_orders_blocked_by_live_position_limit} |")
    lines += ["", "表中的旧仓金额是账本使用陈旧价格得到的指数坐标估值，用来描述已占用的账面敞口；不是核证净值、可保证收回的现金或原始股票股数。各策略为独立名义账户。逐行文件记录了三个日期的持仓单位、价格标记来源/日期、金额、账户现金和名额。", "",
              f"验证通过：{len(detail)} 条目标与原始 target_decisions 一致、缺输入核对、拒单/零成交核对、三个收盘单位连续性、资金占用与 NAV 权重一致，以及 {len(SOURCES)} 个源文件读前读后 SHA-256 未变。", "",
              "数据文件：MISSING_METADATA_HOLDINGS_DETAIL.csv；MISSING_METADATA_HOLDINGS_DAILY_OCCUPANCY.csv；MISSING_METADATA_HOLDINGS_BY_POLICY.csv；LIVE_POSITION_LIMIT_BLOCKED_NEW_BUYS_20260923.csv；ALL_POLICIES_EXECUTION_20260923.csv。"]
    (OUT / "HOLDINGS_TRACE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    receipt["output_sha256"] = {name: sha(OUT / name) for name in [*outputs, "HOLDINGS_TRACE_REPORT.md", Path(__file__).name]}
    (OUT / "HOLDINGS_TRACE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in receipt.items() if key not in ["source_sha256", "output_sha256", "evidence_limits"]}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
