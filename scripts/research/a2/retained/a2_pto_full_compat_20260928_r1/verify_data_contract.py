"""Read-only data/time-boundary audit; never prepares test or reads PnL.

Audits only source manifests, input qualification, finite feature availability,
the physical pre-2026 files, and deterministic 13F membership/version rules.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
AUDITS = ROOT / "audits"
SOURCE_HASHES = {}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bind(path):
    path = Path(path).resolve()
    SOURCE_HASHES[str(path)] = sha(path)
    return path


def read_json(path):
    return json.loads(bind(path).read_text(encoding="utf-8-sig"))


def read_parquet(path, **kwargs):
    return pd.read_parquet(bind(path), **kwargs)


def main():
    ns = runpy.run_path(str(bind(ROOT / "prepare_data.py")))
    features = ns["FEATURES"]
    receipt = read_json(ROOT / "data/PRE_DATA_RECEIPT.json")
    checks = {}
    for name, expected in receipt["output_sha256"].items():
        assert sha(bind(ROOT / "data" / name)) == expected
    checks["pre_saved_output_hashes_match"] = True
    for path, expected in receipt["input_sha256"].items():
        assert sha(bind(path)) == expected
    checks["pre_frozen_source_hashes_unchanged"] = True
    pre = read_parquet(ROOT / "data/pre.parquet")
    px = read_parquet(ROOT / "data/pre_prices.parquet")
    calendar_pre = read_parquet(ROOT / "data/pre_calendar.parquet")
    assert len(pre) == 313668 and pre.signal_date.nunique() == 752
    assert pre.signal_date.lt("2026-01-01").all() and px.trade_date.lt("2026-01-01").all()
    assert calendar_pre.trade_date.lt("2026-01-01").all()
    assert len(features) == 32 and np.isfinite(pre[features].to_numpy(float)).all()
    checks["physical_training_inputs_contain_no_2026_rows"] = True
    checks["all_32_finite_observation_features_in_fixed_order"] = True
    mature = pre.loc[pre.label_available]
    assert len(mature) == 312707
    assert mature.execution_date.gt(mature.signal_date).all()
    assert mature.label_end_date.gt(mature.execution_date).all()
    assert mature.label_end_date.lt("2026-01-01").all()
    assert np.allclose(mature.y_next_open, mature.following_open / mature.next_open - 1, atol=1e-12, rtol=0)
    checks["one_session_next_open_to_following_open_label"] = True
    cutoff_rows = []
    for stage, cutoff in [("development", "2024-01-01"), ("validation", "2025-01-01"), ("final", "2026-01-01")]:
        fit = mature.loc[mature.signal_date.lt(cutoff) & mature.label_end_date.lt(cutoff)]
        assert fit.signal_date.lt(cutoff).all() and fit.label_end_date.lt(cutoff).all()
        cutoff_rows.append({"stage": stage, "cutoff_exclusive": cutoff, "eligible_rows": len(fit),
                            "signal_max": str(fit.signal_date.max().date()),
                            "label_end_max": str(fit.label_end_date.max().date())})
    checks["all_three_fit_stages_require_mature_pre_cutoff_labels"] = True
    timing_path = WS / "a2_latest_effective_joint_20260927/data/quarter_timing.csv"
    timing = pd.read_csv(bind(timing_path), parse_dates=["report_date", "latest_filing_date", "quarter_effective_date", "next_quarter_effective_date"])
    timing = timing.sort_values("quarter_effective_date")
    assert timing.report_date.lt(timing.latest_filing_date).all()
    assert timing.latest_filing_date.lt(timing.quarter_effective_date).all()
    def independent_active(date):
        date = pd.Timestamp(date)
        eligible = timing.loc[timing.quarter_effective_date.le(date) & timing.latest_filing_date.lt(date)]
        assert len(eligible)
        return eligible.iloc[-1].quarter
    cases = [
        ("2023-01-03", "2022Q3", "2022Q4 not public; recurse to the latest earlier public/effective quarter"),
        ("2026-01-02", "2025Q3", "2025Q4 not public; preserve previous public/effective pool"),
        ("2026-02-17", "2025Q3", "before 2025Q4 publication"),
        ("2026-02-18", "2025Q3", "publication date alone does not activate the next quarter"),
        ("2026-02-24", "2025Q3", "published but not effective; preserve preceding pool"),
        ("2026-02-25", "2025Q4", "switch exactly on effective date"),
        ("2026-04-01", "2025Q4", "natural-quarter rollover does not consume an unpublished future report"),
        ("2026-05-21", "2025Q4", "2026Q1 published but not effective"),
        ("2026-05-22", "2026Q1", "switch exactly on 2026Q1 effective date"),
        ("2026-07-01", "2026Q1", "2026Q2 unpublished; retain preceding effective quarter"),
        ("2026-08-14", "2026Q1", "2026Q2 publication still awaits the fifth session"),
        ("2026-08-20", "2026Q1", "last session before 2026Q2 effective date"),
        ("2026-08-21", "2026Q2", "activate 2026Q2 initial 24-manager version"),
    ]
    case_records = []
    for date, expected, reason in cases:
        actual = independent_active(date)
        assert actual == expected, (date, expected, actual)
        case_records.append({"signal_date": date, "expected": expected, "actual": actual, "reason": reason})
    positions = np.searchsorted(timing.quarter_effective_date.to_numpy("datetime64[ns]"), pre.signal_date.to_numpy("datetime64[ns]"), side="right") - 1
    assert (positions >= 0).all()
    assert np.array_equal(timing.iloc[positions].quarter.to_numpy(), pre.asof_quarter.to_numpy())
    checks["independent_asof_matches_all_313668_pre_rows"] = True
    checks["unpublished_quarter_recursive_carry"] = True
    checks["published_not_effective_quarter_carry"] = True
    checks["exact_effective_date_switch"] = True
    checks["natural_quarter_rollover_cannot_consume_future_quarter"] = True
    initial, restated, q2_receipt, q2_audit = ns["rebuild_restated_q2"]()
    SOURCE_HASHES.update(ns["SOURCES"])
    assert len(initial) == len(restated) == 575
    assert set(zip(initial.ticker, initial.cusip)) == set(zip(restated.ticker, restated.cusip))
    q2_version_cases = []
    for date, expected in [("2026-09-01", "INITIAL_24"), ("2026-09-02", "INITIAL_24"),
                            ("2026-09-09", "INITIAL_24"), ("2026-09-10", "CITADEL_RESTATED"),
                            ("2026-09-11", "CITADEL_RESTATED")]:
        assert independent_active(date) == "2026Q2"
        actual = "CITADEL_RESTATED" if pd.Timestamp(date) >= pd.Timestamp(q2_receipt["citadel_restatement_effective_date"]) else "INITIAL_24"
        assert actual == expected
        q2_version_cases.append({"signal_date": date, "expected": expected, "actual": actual})
    input_calendar = read_parquet(WS / "a2_latest_effective_joint_20260927/data/calendar.parquet", columns=["trade_date"])
    sessions = pd.DatetimeIndex(input_calendar.trade_date).unique().sort_values()
    for filed, effective in [("2026-08-14", "2026-08-21"), ("2026-09-02", "2026-09-10")]:
        following = sessions[sessions > pd.Timestamp(filed)]
        assert len(following) >= 5 and following[4] == pd.Timestamp(effective)
    checks["q2_initial_and_restatement_fifth_following_session"] = True
    checks["citadel_restatement_replaces_initial_only_from_20260910"] = True
    checks["original_v17b_initial_membership_independently_reproduced"] = True
    checks["restated_top100_union_same_575_ticker_cusip_keys"] = True
    full = read_parquet(WS / "a2_ensemble_attribution_20260928_r1/qualification_all_candidates.parquet")
    feature_path = WS / "a2_strict_method_retrain_20260926/test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"
    material = read_parquet(feature_path, columns=["signal_date", "ticker", *features])
    assert len(full) == 111868 and not full.duplicated(["signal_date", "ticker"]).any()
    assert not material.duplicated(["signal_date", "ticker"]).any()
    joined = full.merge(material, on=["signal_date", "ticker"], how="left", validate="one_to_one", indicator=True)
    finite = np.isfinite(joined[features].to_numpy(float)).all(axis=1)
    unknown = joined.current_frozen_status.eq("UNKNOWN")
    coverage = {
        "original_candidate_security_days": len(full), "signal_days": int(full.signal_date.nunique()),
        "qualified_security_days": int(full.current_frozen_qualified.sum()),
        "unknown_security_days": int(full.current_frozen_unknown.sum()),
        "proven_ineligible_security_days": int(full.current_frozen_proven_ineligible.sum()),
        "unknown_with_32_finite_features": int((unknown & finite).sum()),
        "unknown_with_present_but_nonfinite_features": int((unknown & ~finite & joined["_merge"].eq("both")).sum()),
        "unknown_without_materialized_feature_row": int((unknown & joined["_merge"].eq("left_only")).sum()),
        "fully_qualified_full_pool_signal_days": int(full.groupby("signal_date").current_frozen_unknown.sum().eq(0).sum()),
    }
    assert coverage["qualified_security_days"] == 62393
    assert coverage["unknown_security_days"] == 47271 and coverage["proven_ineligible_security_days"] == 2204
    assert coverage["unknown_with_32_finite_features"] == 43863
    assert coverage["unknown_with_present_but_nonfinite_features"] == 559
    assert coverage["unknown_without_materialized_feature_row"] == 2849
    assert coverage["fully_qualified_full_pool_signal_days"] == 0
    checks["all_original_full_candidate_keys_survive_left_feature_join"] = True
    checks["finite_numeric_unknown_rows_are_not_qualified_by_audit"] = True
    checks["formal_full_pool_performance_remains_blocked_data"] = True
    # Explicitly check that this audit did not construct the post-freeze stage.
    assert not (ROOT / "data/TEST_DATA_RECEIPT.json").exists()
    assert not (ROOT / "data/test.parquet").exists()
    checks["test_construction_not_run_before_full_learning_freeze"] = True
    assert all(sha(path) == expected for path, expected in SOURCE_HASHES.items())
    checks["all_audited_source_bytes_unchanged"] = True
    result = {
        "status": "PASS_INPUT_AND_TIME_CONTRACT_ONLY_FORMAL_FULL_POOL_BLOCKED_DATA",
        "created_utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "checks_passed": len(checks), "feature_order": features, "fit_stage_boundaries": cutoff_rows,
        "quarter_carry_and_switch_cases": case_records, "q2_version_cases": q2_version_cases,
        "q2_restatement_recomputed_membership": q2_audit, "full_candidate_coverage": coverage,
        "pre_source_summary": {"context_rows": len(pre), "signal_days": int(pre.signal_date.nunique()),
            "tickers": int(pre.ticker.nunique()), "first": str(pre.signal_date.min().date()), "last": str(pre.signal_date.max().date()),
            "price_rows": len(px), "price_first": str(px.trade_date.min().date()), "price_last": str(px.trade_date.max().date()),
            "mature_label_rows": len(mature)},
        "training_2026_rows_read": 0, "new_fit_calls": 0, "new_predictions": 0, "new_replays": 0,
        "test_construction_calls": 0, "portfolio_performance_files_read": 0,
        "2026_numerical_input_values_inspected_for_finite_coverage_only": True,
        "previous_2026_exposure_preserved_no_blind_test_claim": True,
        "full_pool_formal_performance_allowed": False,
        "read_only_source_sha256": SOURCE_HASHES,
        "producer_sha256": sha(Path(__file__)),
    }
    AUDITS.mkdir(exist_ok=True)
    path = AUDITS / "DATA_CONTRACT_VERIFICATION.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str, allow_nan=False) + "\n", encoding="utf-8")
    markdown = f"""# 数据、13F 时钟与执行审计

结论：pre 输入与时间合同已通过 {len(checks)} 项定向检查；新批 test 构建尚未运行。完整 2026 候选池正式绩效仍是 BLOCKED_DATA，有限数字不能替代输入资格证据。

## 已核对输入

| 输入 | 规模与范围 | 用途 |
| --- | --- | --- |
| data/pre.parquet | {len(pre):,} 行、752 个信号日、730 ticker；2023-01-03 至 2025-12-31 | 32 个共同观察特征与成熟标签；保留 961 行无标签记录 |
| data/pre_prices.parquet | {len(px):,} 行；{px.trade_date.min().date()} 至 {px.trade_date.max().date()}，所有日期严格早于 2026 | 共同账户与历史风险输入 |
| data/pre_calendar.parquet | 原 QQQ 会话日历，仅 pre-2026 | 统一下一开盘执行及 following-open 标签终点 |
| qualification_all_candidates.parquet | 111,868 个原始候选证券日、181 个信号日 | 完整候选键与原资格状态；不能缩成旧 A2 TOP20 |
| ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet | materialized 原 32 特征 | 只读有限值覆盖审计；未预测、未优化、未回放 |

标签固定为信号收盘后下一 QQQ 交易会话开盘至再下一会话开盘的一日毛价格指数收益，即 `following_open / next_open - 1`。312,707 行标签可用；训练还要按每个阶段同时检查 signal 与 label_end 严格早于阶段 cutoff。原 3/5/10/20 日超额收益 target 不能作为本次单期收益标签或观察特征。标准化、学习融合及校准须仍由各模块遵守独立 pre-2026/时间合法 OOF 合同，本审计没有替它们宣告训练完成。

## 13F 池规则与边界

固定原 authoritative_24_manager_manifest 的 24 家机构。同一季度、机构、accession 版本及 CUSIP 先聚合合格股票披露美元价值，再按价值降序、CUSIP 升序取每机构最多 TOP100。24 家取 CUSIP 并集；每机构 TOP20 是 protected_core 池成员保护标志。并集沿 protected_core、机构数、conviction_score、累计价值降序与 CUSIP 升序排序，硬上限 900，再使用既有证券身份映射与 ticker/transport 去重；并非旧 A2 TOP20。

合格类别要求 SH、put/call 空，并属于普通股、ordinary、ADR/ADS/GDR、class、REIT 等允许股权类别；排除衍生期权、非 SH、权证、单位、rights、优先股、债券/票据、可转债、ETF/ETP/ETN/fund、指数产品、商品/加密信托等，以及类别不明确的条目。原规则源码为 `D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/integrity_rebuild_v17b.py` 与 `eligibility_v17b.py`，哈希已登记。

新季度未公开时，递归沿用最近历史上已公开且生效的池；已公开但尚未生效时仍保留此前有效池。原时钟是最新实际披露日期后的第 5 个 QQQ 交易会话激活，不能用自然季度倒推未来成员。本次保存 13 个独立边界案例；313,668 个 pre 行的 asof_quarter 全部与独立 searchsorted 对齐。

2026Q2 初始 24 家 08-14 披露、08-21 激活。Citadel 13F-HR/A restatement `0001104659-26-104387` 的 accepted_at 为 09-01 22:14 UTC、filed_date 为 09-02，按既有保守 filed-date 第 5 会话规则于 09-10 替换原 Citadel 版本。原 v17b 三个纯函数从版本化源重算：初始与重报池均 575 ticker/CUSIP，集合无增删。更正版本时钟不等于按结果扩大模型或股票。Pershing 仍属于原 24 家；通过 other-manager 1 归属只取 14/15 行，不能把代理申报人另加成第 25 家。

## 完整池缺口

原 111,868 候选证券日中，62,393 行资格通过、47,271 行 UNKNOWN、2,204 行已证不适格，181 个信号日完整资格覆盖为 0。UNKNOWN 中 43,863 行已有有限 32 特征、559 行特征非有限、2,849 行无 materialized 特征行。所有原始键及原状态仍保存；数值存在没有使 UNKNOWN 升格。以后只使用合法上下文回放时，结果只能标记为子池诊断，正式完整候选池 TOP20 绩效仍受阻。

静态历史证券身份、121 会话与缺价选择、历史供应商真实到达/版本时间、GLW 事件日期冲突、EXAS 权利与现金结算等未因重训得到认证。这里价格为 affine 调整研究指数；单位不是原始实际股数，净值不是已认证股东总回报。既有 2026 暴露记录保持，不宣称新的盲测或完整 2026 全年。

## 共同执行与新批账户 API

原只读执行引擎：`a2_buy_sell_cash_multimodel_20260928/engine_v2.py`，`run_replay(prices, calendar, features, policy, ...)`，回调返回 `HoldingAwareDecision`。信号收盘定目标、下一交易会话开盘成交；缺输入或缺明确输出保留已有单位和资金/名额，明确 0 才是模型退出；缺开盘不成交；先卖后买，实际仍持有的证券继续占名额；单边费用与 ADV 1% 买入限制用信号时冻结信息；不终端清算。

新 `batch_engine.py` 在共同不可变报价上以 K×N 独立 units 与每策略 cash 数组推进。回调 `callback(day_dataframe, context)` 返回 `targets`/`decided`，每策略当前真实账户进入风险与优化；没有用静态目标权重相乘代替账户。全部明确 0 与决定覆盖 mask 保存到每日压缩矩阵，订单、成交、费用、实际持仓和净值通过 strategy_id、signal_date、execution_date、decision_id、order_id 连接。13 个目标专家贡献单独存矩阵。独立旧引擎 conformance 见 `audits/BATCH_ENGINE_CONFORMANCE.json`；本输入审计不运行生产账户。

审计收据：`audits/DATA_CONTRACT_VERIFICATION.json`，包括所有源 SHA-256、边界案例、cutoff 核对与完整缺口。所有源字节未变；新增 fit/predict/replay/test-build 调用均为 0。
"""
    (AUDITS / "data_engine_audit.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks_passed": len(checks), "full_candidate_coverage": coverage}, ensure_ascii=False))


if __name__ == "__main__":
    main()
