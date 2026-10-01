"""Finalize exact candidate input gate from the completed read-only feature run."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STAGE = HERE / "test2026_stage"
OUT = STAGE / "identity_feature_application_r1"
BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
EXECUTION = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
METHODS = ("hgb", "ridge", "elastic_net", "mlp")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    raw_ledger = OUT / "CANDIDATE_111868_IDENTITY_32_FEATURE_VERSION_LEDGER.parquet"
    feature_path = OUT / "ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet"
    candidate = pd.read_parquet(raw_ledger)
    features = pd.read_parquet(feature_path)
    events = pd.read_parquet(OUT / "CONSUMED_REHAB_EVENT_AUDIT.parquet")
    code_audit = pd.read_csv(OUT / "CODE_FEATURE_CONSUMPTION_AUDIT.csv")
    assert len(candidate) == 111868 and len(features) == 152457
    key = ["cusip", "title_of_class", "quarter", "signal_date"]
    assert not candidate.duplicated(key).any()
    assert candidate.signal_date.nunique() == 181

    applied = events.loc[events.audit_kind.eq("APPLIED_CORPORATE_ACTION")].copy()
    assert len(applied) == 9011
    initial_rows = []
    for original_code, group in applied.groupby("original_code", sort=True):
        alpha, beta = 1.0, 0.0
        pre_count = 0
        for row in group.sort_values(["event_date", "source_event_date"], kind="mergesort").itertuples():
            if row.event_date >= pd.Timestamp("2026-01-02"):
                continue
            old_alpha = alpha
            alpha = old_alpha / float(row.factor_a)
            beta -= old_alpha * float(row.factor_b) / float(row.factor_a)
            pre_count += 1
        assert np.isfinite(alpha) and alpha > 0 and np.isfinite(beta)
        initial_rows.append({"moomoo_transport_code": original_code,
                             "initial_alpha_2026_01_02": alpha, "initial_beta_2026_01_02": beta,
                             "consumed_prior_events": pre_count})
    initial = pd.DataFrame(initial_rows)
    all_codes = code_audit[["moomoo_transport_code"]].merge(initial, how="left", on="moomoo_transport_code")
    all_codes["initial_alpha_2026_01_02"] = all_codes.initial_alpha_2026_01_02.fillna(1.0)
    all_codes["initial_beta_2026_01_02"] = all_codes.initial_beta_2026_01_02.fillna(0.0)
    all_codes["consumed_prior_events"] = all_codes.consumed_prior_events.fillna(0).astype(int)
    all_codes.to_csv(OUT / "CONSUMED_2026_INITIAL_ADJUSTMENT_STATE.csv", index=False)

    first_event = (applied.loc[applied.event_date.ge("2026-01-02") & applied.event_date.le("2026-09-22")]
                   .groupby("original_code").event_date.min())
    jumps = events.loc[events.audit_kind.eq("LARGE_RAW_MOVE_NO_VENDOR_EVENT")
                       & events.event_date.ge("2026-01-02") & events.event_date.le("2026-09-22")].copy()
    first_jump = jumps.groupby("original_code").event_date.min()
    candidate["first_consumed_2026_event"] = candidate.moomoo_transport_code.map(first_event)
    candidate["first_unexplained_2026_jump"] = candidate.moomoo_transport_code.map(first_jump)
    candidate["2026_event_publication_time_unverified"] = (candidate.first_consumed_2026_event.notna()
        & candidate.signal_date.ge(candidate.first_consumed_2026_event))
    candidate["unexplained_raw_jump_dependency"] = (candidate.first_unexplained_2026_jump.notna()
        & candidate.signal_date.ge(candidate.first_unexplained_2026_jump))
    candidate["no_frozen_coordinate_overlap"] = candidate.coordinate_overlap_rows.eq(0)
    assert not ((candidate.coordinate_overlap_rows.gt(0)) & (~candidate.coordinate_match)).any()
    # One primary class per candidate day.  The independent flags above remain
    # available for multi-dependency analysis without double-counting.
    candidate["final_input_gate"] = np.select([
        candidate.proven_lifecycle_ineligible.to_numpy(dtype=bool),
        candidate.proven_121_ineligible.to_numpy(dtype=bool),
        candidate.multi_cusip_transport_interval_pending.to_numpy(dtype=bool),
        candidate.feature_error.fillna("").ne("").to_numpy(dtype=bool),
        ~candidate.lookback_121_eligible.fillna(False).to_numpy(dtype=bool),
        ~candidate.has_32_finite.to_numpy(dtype=bool),
        candidate.no_frozen_coordinate_overlap.to_numpy(dtype=bool),
        candidate.unexplained_raw_jump_dependency.to_numpy(dtype=bool),
        candidate["2026_event_publication_time_unverified"].to_numpy(dtype=bool),
    ], ["PROVEN_LIFECYCLE_INELIGIBLE", "PROVEN_ORIGINAL_121_INELIGIBLE",
        "UNKNOWN_MULTI_CUSIP_TRANSPORT_INTERVAL", "UNKNOWN_RAW_REHAB_OR_ALIAS_IDENTITY",
        "UNKNOWN_121_HISTORY", "UNKNOWN_32_FEATURE_FINITE",
        "UNKNOWN_FROZEN_COORDINATE_NO_OVERLAP", "UNKNOWN_UNEXPLAINED_RAW_JUMP",
        "UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME"], default="INPUT_VERIFIED_THIS_GATE")
    assert len(candidate) == 111868 and not candidate.final_input_gate.isna().any()
    candidate.to_parquet(OUT / "FINAL_111868_CANDIDATE_INPUT_GATE.parquet", index=False)
    unknown = candidate.loc[candidate.final_input_gate.str.startswith("UNKNOWN")]
    grouped = unknown.groupby(["quarter", "ticker", "cusip", "title_of_class",
                               "moomoo_transport_code", "final_input_gate"], as_index=False).agg(
        days=("signal_date", "size"), first_signal=("signal_date", "min"), last_signal=("signal_date", "max"))
    grouped.to_csv(OUT / "FINAL_REMAINING_CANDIDATE_GAPS.csv", index=False)
    focus = ["US.BGNE", "US.DTP", "US.LILAB", "US.LLYVB", "US.GE.WI", "US.AZNCF",
             "US.BLDE", "US.BSIG", "US.CBDY", "US.MSTLW", "US.RLYB"]
    focus_rows = candidate.loc[candidate.moomoo_transport_code.isin(focus)].groupby(
        ["moomoo_transport_code", "transport_used", "final_input_gate"], dropna=False,
        as_index=False).agg(days=("signal_date", "size"), first_signal=("signal_date", "min"),
                            last_signal=("signal_date", "max"))
    focus_rows.to_csv(OUT / "FOCUS_IDENTITY_STATUS_CHANGE.csv", index=False)

    freeze = json.loads((BASE / "pre2026_model_freeze.json").read_text(encoding="utf-8"))
    model_hashes = {}
    for method in METHODS:
        model = BASE / method / "final_full_pre2026.joblib"
        digest = sha(model)
        frozen = next(x["sha256"] for x in freeze["models"][method]["fits"] if x["stage"] == "FULL_PRE2026")
        assert digest == frozen
        model_hashes[method] = digest
    accounting_source = EXECUTION.read_text(encoding="utf-8")
    evaluate_source = (HERE / "evaluate.py").read_text(encoding="utf-8")
    assert "def reconstruct_path(" in accounting_source
    assert 'r0f.reconstruct_path(model=method' in evaluate_source
    assert 'r0f = import_file("original_r0f_for_execution", R0F)' in evaluate_source
    gate_counts = candidate.final_input_gate.value_counts().to_dict()
    report = {
        "status": "FORMAL_FOUR_MODEL_TEST_NOT_STARTED_INCOMPLETE_COMMON_INPUT",
        "test_asof_utc": "2026-09-25T18:10:21.6494935Z",
        "last_signal": "2026-09-22", "last_execution": "2026-09-23", "terminal_valuation": "2026-09-24",
        "candidate_days": len(candidate), "signal_days": candidate.signal_date.nunique(),
        "gate_counts_mutually_exclusive": gate_counts, "unknown_candidate_days": len(unknown),
        "feature_rows_generated": len(features), "feature_columns": 32,
        "frozen_coordinate_overlap_matched_codes": int(code_audit.coordinate_match.sum()),
        "frozen_coordinate_overlap_mismatch_codes": int(((code_audit.coordinate_overlap_rows > 0) & ~code_audit.coordinate_match).sum()),
        "codes_without_frozen_coordinate_overlap": int(code_audit.coordinate_overlap_rows.eq(0).sum()),
        "consumed_applied_rehab_events": len(applied),
        "consumed_2026_applied_rehab_events": int(applied.event_date.ge("2026-01-02").sum()),
        "candidate_days_dependent_on_2026_event_without_publication_timestamp": int(candidate["2026_event_publication_time_unverified"].sum()),
        "unexplained_2026_raw_jumps": jumps[["original_code", "ticker", "event_date", "raw_jump"]].to_dict("records"),
        "feature_source_sha256": json.loads((OUT / "FEATURE_CONSUMPTION_REPORT.json").read_text(encoding="utf-8"))["original_feature_source_sha256"],
        "frozen_model_hashes_verified_without_loading": model_hashes,
        "actual_accounting_source_path": str(EXECUTION), "actual_accounting_source_sha256": sha(EXECUTION),
        "formal_predictions_started": False, "formal_accounting_started": False,
        "new_model_fit_calls": 0, "new_preprocessor_fit_calls": 0,
        "fit_count_basis": "Only source builders, read-only saved Raw/rehab, and audit code executed; no estimator or scaler was loaded or called.",
        "candidate_execution_valuation_gate": "NOT_RUN_NO_FIXED_TOP20; prior possible price gaps remain separate and are not actual held-position needs",
        "input_ledger_sha256": sha(raw_ledger), "feature_checkpoint_sha256": sha(feature_path),
    }
    (OUT / "FINAL_FEATURE_GATE_REPORT.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    lines = ["# A2 test2026：原身份与 32 特征实际消费验收", "",
             "完整候选池仍有未知，因此四个冻结最终模型的正式预测、TOP20 和会计回放均未启动。",
             "保留原 TEST_ASOF、181 个信号日、09-23 执行与 09-24 终止估值边界。", "",
             f"- 原候选日：{len(candidate):,}；原函数生成特征行：{len(features):,}；特征列：32。",
             f"- 已证实原规则不合格：{gate_counts.get('PROVEN_LIFECYCLE_INELIGIBLE',0):,} 生命周期；"
             f"{gate_counts.get('PROVEN_ORIGINAL_121_INELIGIBLE',0):,} 预热。",
             f"- 未知候选日：{len(unknown):,}；互斥分类见 FINAL_FEATURE_GATE_REPORT.json。",
             f"- 旧价格坐标重叠一致代码：{report['frozen_coordinate_overlap_matched_codes']}；有重叠但不一致：0。",
             f"- 实际消费复权事件：{len(applied):,}，其中 2026 年 {report['consumed_2026_applied_rehab_events']:,}；"
             "事件历史公布时钟仍须逐事件证明。", "",
             "重点映射实际状态变更见 FOCUS_IDENTITY_STATUS_CHANGE.csv。",
             "983 条旧预热未知按原 CUSIP、股类、季度、信号日逐键对账；215 条有首次交易证据，768 条仍未知。",
             "当候选资格未全窗成立时，候选级潜在成交/估值缺价不能充当四组合的实际持仓需求；未生成策略净值。", "",
             "新增模型拟合 0；新增预处理拟合 0。模型哈希只读核对，未加载模型。", ""]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"gate_counts": gate_counts, "unknown": len(unknown),
                      "event_dependent_days": report["candidate_days_dependent_on_2026_event_without_publication_timestamp"]}))


if __name__ == "__main__":
    main()
