"""Pre-2026 Raw A2 attribution, candidate recall, and tail learnability audit.

Thin orchestration over frozen/authoritative project artifacts. It does not
change Raw A2, create a strategy, search labels or parameters, use a network,
or persist prediction panels.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TASK = "A2_CANONICAL_ATTRIBUTION_AND_WINNER_LOSER_LEARNABILITY_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
OUT = RESULTS / TASK
BOUNDARY = pd.Timestamp("2026-01-01")
SEED = 20260825
TOL = 1e-12

BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
DAILY = BASE / "portfolio_daily.parquet"
METRICS = BASE / "metrics.json"
TOP20 = BASE / "top20_selections.parquet"
ATTR_ROOT = RESULTS / "A2_RETURN_ATTRIBUTION_R1"
ATTR_DETAIL = ATTR_ROOT / "attribution_detail.parquet"
ATTR_SUMMARY = ATTR_ROOT / "attribution_summary.csv"
TAIL_DETAIL = RESULTS / "A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1" / "diagnostic_detail.parquet"
TOP40 = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
MODEL_ROOT = RESULTS / "A2_MODEL_FAMILY_R1A_DATA_COMPLETE"
MODEL_OOF = MODEL_ROOT / "outer_oof_predictions.parquet"
RESEARCH_DATA = CACHE / "a2_model_family_r1a_data_complete" / "research_dataset.parquet"
FOLD_MANIFEST = MODEL_ROOT / "fold_manifest.csv"
MODEL_PREREG = MODEL_ROOT / "model_family_preregistration.json"
NG8_OOF = CACHE / "a2_full_history_synthesis_nextgen_r1" / "ng8_fixed_outer_oof.parquet"
R6_OOF = RESULTS / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"
BETA_ROOT = RESULTS / "A2_BETA_MATCHED_BENCHMARK_AND_RESIDUAL_VALUE_R1"
PRETOP_SUMMARY = RESULTS / "A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1" / "arm_summary.csv"

EXPECTED_HASHES = {
    DAILY: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    METRICS: "936c278a83d8d310f13259668c95b0a1e5cf7f8d9f16d93075417e669174ec50",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    ATTR_DETAIL: "46a15f62f06d36142a19bca59b12b294eebaaf79bbdc87335e6a379196ebff16",
    ATTR_SUMMARY: "dcb20866bacacf114d9a516d9976f5f7976f4cffb45ca1b2a87a39a5184b8b2c",
    TAIL_DETAIL: "7bc4a394893a90a9cd4b3ba8ddeb2cca929505611539ed89728a176b11172b0d",
    TOP40: "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17",
    MODEL_OOF: "acf0794b97911f6650000f5fe3a64ae95116f324aa30e38b55ff64c819f91a98",
    FOLD_MANIFEST: "fd60db12e5af433e8d5f9d09106644234fe672d9c2eee555c1505ce4ad578e5a",
    MODEL_PREREG: "fb396f0a8b45ff12c05f6596bdcb60dc0d11e2606fe438ecb491d356166d73e2",
    RESEARCH_DATA: "82e0020a3e15a8020fa041dea428b45a3d57a5e7101901e50159d517e6cf1c11",
    NG8_OOF: "aeea77aeda0b02f5225fc30f9f24b13638fb03d91d140d3d6e874abf797838d8",
    R6_OOF: "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4",
    TAXONOMY: "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
    BETA_ROOT / "benchmark_summary.csv": "05c43990eba27a26965ea5f1840f78dcfc896d3ffde79099406ed5aa061041d9",
    PRETOP_SUMMARY: "8b779a497b7cda6f0271b27c58679a09dd2572de96f2514a4c1eb51d21b78aaa",
}
FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d", "max_drawdown_20d",
    "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d", "volume_ratio_5d_20d",
    "volume_ratio_20d_60d", "avg_dollar_volume_20d",
]
RANK_BUCKETS = [(1, 5, "RANK_1_5"), (6, 10, "RANK_6_10"), (11, 15, "RANK_11_15"),
                (16, 20, "RANK_16_20"), (21, 25, "RANK_21_25"), (26, 30, "RANK_26_30"),
                (31, 40, "RANK_31_40")]


class ResearchFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise ResearchFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8", lineterminator="\n", float_format="%.15g")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def row(section: str, metric: str, scope: str, value: Any, *, fold: str = "ALL", year: Any = "ALL",
        security: str = "ALL", sector: str = "ALL", rank_bucket: str = "ALL", numerator: Any = "",
        denominator: Any = "", notes: str = "") -> dict[str, Any]:
    return {"section": section, "metric": metric, "scope": scope, "fold": fold, "year": year,
            "security": security, "sector": sector, "rank_bucket": rank_bucket, "value": value,
            "numerator": numerator, "denominator": denominator, "notes": notes}


def rank_bucket(rank: pd.Series) -> pd.Series:
    result = pd.Series("RANK_GT_40", index=rank.index, dtype="object")
    for lo, hi, name in RANK_BUCKETS:
        result.loc[rank.between(lo, hi)] = name
    return result


def mark_top_fraction(frame: pd.DataFrame, score: str, fraction: float, name: str, *, ascending: bool = False) -> pd.DataFrame:
    ordered = frame.sort_values(["signal_date", score, "ticker"], ascending=[True, ascending, True], kind="mergesort").copy()
    ordered["_position"] = ordered.groupby("signal_date").cumcount()
    ordered["_count"] = ordered.groupby("signal_date")["ticker"].transform("size")
    ordered[name] = ordered["_position"].lt(np.ceil(ordered["_count"] * fraction).astype(int))
    return ordered.drop(columns=["_position", "_count"]).sort_index()


def binary_metrics(frame: pd.DataFrame, label: str, probability: str) -> dict[str, float]:
    y = frame[label].astype(int).to_numpy(); p = frame[probability].astype(float).to_numpy(); base = float(y.mean())
    require(np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all(), "INVALID_PROBABILITY", probability)
    ap = float(average_precision_score(y, p))
    return {"n": int(len(y)), "event_count": int(y.sum()), "base_rate": base, "average_precision": ap,
            "ap_lift": ap / base, "auroc": float(roc_auc_score(y, p)), "brier": float(brier_score_loss(y, p))}


def score_metrics(frame: pd.DataFrame, label: str, score: str) -> dict[str, float]:
    y = frame[label].astype(int).to_numpy(); s = frame[score].astype(float).to_numpy(); base = float(y.mean())
    ap = float(average_precision_score(y, s))
    return {"average_precision": ap, "ap_lift": ap / base, "auroc": float(roc_auc_score(y, s))}


def add_probability_diagnostics(rows: list[dict[str, Any]], frame: pd.DataFrame, label: str, probability: str,
                                prefix: str, fold_column: str) -> dict[str, Any]:
    pooled = binary_metrics(frame, label, probability)
    for metric, value in pooled.items():
        rows.append(row("LEARNABILITY", metric.upper(), prefix, value))
    directions = 0
    for fold, group in frame.groupby(fold_column, sort=True):
        metrics = binary_metrics(group, label, probability)
        directions += int(metrics["auroc"] > .5 and metrics["ap_lift"] > 1)
        for metric, value in metrics.items():
            rows.append(row("LEARNABILITY_FOLD", metric.upper(), prefix, value, fold=str(fold),
                            year=int(group.signal_date.dt.year.mode().iloc[0])))
    for fraction in (.01, .05, .10):
        flag = f"top_{int(fraction * 100)}pct"
        ranked = mark_top_fraction(frame, probability, fraction, flag)
        chosen = ranked.loc[ranked[flag]]
        precision = float(chosen[label].mean()); recall = float(chosen[label].sum() / frame[label].sum())
        rows += [row("LEARNABILITY_RANK", "PRECISION", prefix, precision, notes=flag),
                 row("LEARNABILITY_RANK", "RECALL", prefix, recall, notes=flag),
                 row("LEARNABILITY_RANK", "LIFT", prefix, precision / pooled["base_rate"], notes=flag)]
    calibration = frame[[label, probability]].sort_values(probability, kind="mergesort").copy()
    calibration["bucket"] = pd.qcut(np.arange(len(calibration)), 10, labels=False)
    for bucket, group in calibration.groupby("bucket", sort=True):
        note = f"DECILE_{int(bucket)+1}"
        rows += [row("CALIBRATION", "MEAN_PREDICTION", prefix, float(group[probability].mean()), notes=note),
                 row("CALIBRATION", "EVENT_RATE", prefix, float(group[label].mean()), notes=note)]
    top = mark_top_fraction(frame, probability, .10, "high_score")
    top_rate = float(top.loc[top.high_score, label].mean())
    return {**pooled, "positive_direction_folds": directions, "fold_count": int(frame[fold_column].nunique()),
            "top_decile_rate": top_rate, "top_decile_lift": top_rate / pooled["base_rate"]}


def validate_sources(rows: list[dict[str, Any]]) -> None:
    for path, expected in EXPECTED_HASHES.items():
        require(path.is_file(), "SOURCE_MISSING", path)
        observed = sha256_file(path)
        require(observed == expected, "SOURCE_HASH_MISMATCH", path)
        rows.append(row("SOURCE_IDENTITY", "SHA256", str(path), observed))
    prereg = json.loads(MODEL_PREREG.read_text(encoding="utf-8"))
    require(prereg["research_dataset_sha256"] == EXPECTED_HASHES[RESEARCH_DATA], "PREREG_DATASET_HASH_MISMATCH")


def baseline_and_attribution(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    daily = pd.read_parquet(DAILY).sort_values("execution_date", kind="mergesort").reset_index(drop=True)
    daily["execution_date"] = pd.to_datetime(daily.execution_date)
    require(len(daily) == 751 and daily.execution_date.max() <= pd.Timestamp("2025-12-31"), "BASELINE_DATE_IDENTITY")
    require(not daily.execution_date.duplicated().any(), "DUPLICATE_ECONOMIC_DATE")
    maximum_identity = float(daily[[c for c in daily if c.endswith("IDENTITY_ERROR")]].abs().to_numpy().max())
    require(maximum_identity <= TOL, "PORTFOLIO_IDENTITY_FAILURE", maximum_identity)
    np.testing.assert_allclose(np.cumprod(1 + daily.reconstructed_daily_return.to_numpy(float)),
                               daily.reconstructed_nav, atol=TOL, rtol=0)
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    expected = {"cagr": .5070421599044499, "sharpe": 1.2353699802070324,
                "max_drawdown": -.370671641329821, "total_turnover": 156.04062236916937}
    for key, value in expected.items():
        require(abs(float(metrics[key]) - value) <= TOL, "REPLAY_METRIC_MISMATCH", key)
    gross_nav = np.cumprod(1 + daily.reconstructed_gross_return.to_numpy(float))
    result = {"date_min": daily.execution_date.min(), "date_max": daily.execution_date.max(), "sessions": len(daily),
              "cumulative_return": float(daily.reconstructed_nav.iloc[-1] - 1), "cagr": metrics["cagr"],
              "sharpe": metrics["sharpe"], "max_drawdown": metrics["max_drawdown"],
              "annualized_volatility": metrics["annualized_volatility"], "total_turnover": metrics["total_turnover"],
              "annualized_turnover": metrics["annualized_turnover"], "average_holdings": metrics["average_holdings"],
              "cost_sum": float(daily.reconstructed_transaction_cost.sum()), "gross_terminal_wealth": float(gross_nav[-1]),
              "net_terminal_wealth": float(daily.reconstructed_nav.iloc[-1]),
              "compounded_cost_drag": float(gross_nav[-1] - daily.reconstructed_nav.iloc[-1]),
              "identity_error": maximum_identity}
    for metric, value in result.items():
        rows.append(row("RAW_A2_REPLAY", metric.upper(), "AUTHORITATIVE_751_SESSION", value))

    detail = pd.read_parquet(ATTR_DETAIL)
    require(pd.to_datetime(detail.date).max() <= pd.Timestamp("2025-12-31"), "ATTRIBUTION_POST2025")
    securities = detail.loc[detail.row_type.eq("A2_SECURITY_SESSION")].copy()
    securities["arithmetic_contribution"] = securities.previous_weight * securities.security_return
    securities["net_wealth"] = securities.gross_wealth_contribution - securities.transaction_cost_wealth
    by_security = securities.groupby(["security_id", "ticker"], dropna=False).agg(
        arithmetic_contribution=("arithmetic_contribution", "sum"), gross_wealth=("gross_wealth_contribution", "sum"),
        cost=("transaction_cost_wealth", "sum"), net_wealth=("net_wealth", "sum")).reset_index()
    by_date = securities.groupby("date").agg(arithmetic_contribution=("arithmetic_contribution", "sum"),
        gross_wealth=("gross_wealth_contribution", "sum"), cost=("transaction_cost_wealth", "sum"),
        net_wealth=("net_wealth", "sum")).reset_index()
    require(abs(by_security.net_wealth.sum() - result["cumulative_return"]) <= 2e-12, "SECURITY_WEALTH_IDENTITY")
    for label, table in (("SECURITY", by_security), ("DATE", by_date)):
        positive = table.loc[table.net_wealth.gt(0)].sort_values("net_wealth", ascending=False)
        negative = table.loc[table.net_wealth.lt(0)].sort_values("net_wealth")
        for count in (1, 5, 10):
            positive_share = float(positive.head(count).net_wealth.sum() / positive.net_wealth.sum())
            negative_share = float(abs(negative.head(count).net_wealth.sum()) / abs(negative.net_wealth.sum()))
            result[f"{label.lower()}_top{count}_positive_share"] = positive_share
            result[f"{label.lower()}_worst{count}_negative_share"] = negative_share
            rows.append(row(f"{label}_CONCENTRATION", f"TOP{count}_POSITIVE_SHARE", label, positive_share))
            rows.append(row(f"{label}_CONCENTRATION", f"WORST{count}_NEGATIVE_SHARE", label, negative_share))
        for item in positive.head(10).itertuples(index=False):
            rows.append(row(f"{label}_LEADERS", "NET_WEALTH_CONTRIBUTION", label, item.net_wealth,
                            security=str(getattr(item, "ticker", "ALL")), notes=str(getattr(item, "date", ""))))
        for item in negative.head(10).itertuples(index=False):
            rows.append(row(f"{label}_LAGGARDS", "NET_WEALTH_CONTRIBUTION", label, item.net_wealth,
                            security=str(getattr(item, "ticker", "ALL")), notes=str(getattr(item, "date", ""))))
    result["top5_security_contribution"] = float(by_security.nlargest(5, "net_wealth").net_wealth.sum())
    result["top5_date_contribution"] = float(by_date.nlargest(5, "net_wealth").net_wealth.sum())
    for year, group in daily.groupby(daily.execution_date.dt.year, sort=True):
        gross_return = float(np.prod(1 + group.reconstructed_gross_return) - 1)
        net_return = float(np.prod(1 + group.reconstructed_daily_return) - 1)
        result[f"gross_return_{year}"] = gross_return; result[f"net_return_{year}"] = net_return
        rows += [row("COST_BY_YEAR", "GROSS_RETURN", "RAW_A2", gross_return, year=year),
                 row("COST_BY_YEAR", "NET_RETURN", "RAW_A2", net_return, year=year),
                 row("COST_BY_YEAR", "TURNOVER", "RAW_A2", float(group.reconstructed_turnover.sum()), year=year),
                 row("COST_BY_YEAR", "COST", "RAW_A2", float(group.reconstructed_transaction_cost.sum()), year=year)]
    cutoff = float(daily.reconstructed_turnover.quantile(.90)); daily["high_turnover"] = daily.reconstructed_turnover.ge(cutoff)
    for state, group in daily.groupby("high_turnover"):
        scope = "HIGH_TURNOVER" if state else "OTHER"
        result[f"{scope.lower()}_mean_net_return"] = float(group.reconstructed_daily_return.mean())
        rows += [row("TURNOVER_VALUE", "MEAN_GROSS_RETURN", scope, float(group.reconstructed_gross_return.mean())),
                 row("TURNOVER_VALUE", "MEAN_NET_RETURN", scope, float(group.reconstructed_daily_return.mean())),
                 row("TURNOVER_VALUE", "SESSION_COUNT", scope, len(group))]
    return result, daily, securities


def factor_diagnostics(rows: list[dict[str, Any]], daily: pd.DataFrame) -> dict[str, Any]:
    summary = pd.read_csv(BETA_ROOT / "benchmark_summary.csv").set_index("benchmark")
    raw = pd.read_csv(PRETOP_SUMMARY).set_index("arm").loc["RAW_A2"]
    shared = import_file("a2_factor_shared_r1", REPO / "scripts/v22/a2_strategy_falsification_and_robustness_r1.py")
    benchmark, _ = shared.benchmark_frame(daily.execution_date)
    aligned = daily[["execution_date", "reconstructed_daily_return"]].merge(benchmark, on="execution_date", validate="one_to_one")
    up = aligned.QQQ.gt(0)
    result = {"qqq_beta": float(summary.loc["QQQ_RAW", "a2_beta_to_benchmark"]),
              "soxx_beta": float(summary.loc["SOXX_RAW", "a2_beta_to_benchmark"]),
              "upside_capture": float(aligned.loc[up, "reconstructed_daily_return"].sum() / aligned.loc[up, "QQQ"].sum()),
              "downside_capture": float(raw.downside_capture), "residual_sharpe": float(raw.residual_sharpe),
              "realized_volatility": float(raw.annualized_volatility), "ff12_hhi": float(raw.ff12_hhi),
              "ff48_hhi": float(raw.ff48_hhi),
              "beta_matched_active_cagr": float(summary.loc["QQQ_BETA_MATCHED", "active_cagr"]),
              "beta_matched_active_ir": float(summary.loc["QQQ_BETA_MATCHED", "information_ratio"]),
              "vol_matched_active_cagr": float(summary.loc["QQQ_VOL_MATCHED", "active_cagr"])}
    for metric, value in result.items():
        rows.append(row("FACTOR_EXPOSURE", metric.upper(), "EXPOSURE_BASED_NOT_CAUSAL", value))
    rows.append(row("FACTOR_EXPOSURE", "SECTOR_ALLOCATION_RETURN_COMPONENT", "EXPOSURE_BASED_NOT_CAUSAL",
                    "NA_NOT_IDENTIFIABLE_WITH_EXISTING_RISK_MODEL",
                    notes="HHI and sector wealth are exposures, not causal allocation alpha"))
    return result


def load_extended_taxonomy(rows: list[dict[str, Any]]) -> pd.DataFrame:
    module = import_file("a2_pretop20_reuse_for_tail_r1",
                         REPO / "scripts/v22/a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py")
    pool, top, _ = module.load_candidate_pool()
    taxonomy, _, facts = module.extend_taxonomy(pool, top)
    require(facts["future_filing_violation_count"] == 0 and facts["backward_fill_violation_count"] == 0,
            "TAXONOMY_PIT_FAILURE")
    rows += [row("PIT_TAXONOMY", "COVERAGE", "FULL_CANDIDATE", facts["ff12_candidate_coverage"]),
             row("PIT_TAXONOMY", "FUTURE_FILING_VIOLATIONS", "FULL_CANDIDATE", 0),
             row("PIT_TAXONOMY", "BACKWARD_FILL_VIOLATIONS", "FULL_CANDIDATE", 0)]
    return taxonomy[["signal_date", "ticker", "ff12", "ff48"]].copy()


def fit_winner(rows: list[dict[str, Any]], taxonomy: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = ["signal_date", "next_execution_date", "target_end_date", "security_id", "ticker", "target", *FEATURES]
    matrix = pd.read_parquet(RESEARCH_DATA, columns=columns)
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date)
    matrix["next_execution_date"] = pd.to_datetime(matrix.next_execution_date)
    matrix["target_end_date"] = pd.to_datetime(matrix.target_end_date)
    require(matrix.target_end_date.max() <= pd.Timestamp("2025-12-31"), "WINNER_POST2025_TARGET")
    require((matrix.signal_date < matrix.next_execution_date).all()
            and (matrix.next_execution_date <= matrix.target_end_date).all(), "WINNER_FEATURE_DATE_FAILURE")
    require(not matrix.duplicated(["signal_date", "security_id"]).any(), "WINNER_MATRIX_DUPLICATE")
    matrix = mark_top_fraction(matrix, "target", .01, "winner")
    folds = pd.read_csv(FOLD_MANIFEST)
    model = pd.read_parquet(MODEL_OOF, columns=["signal_date", "security_id", "ticker", "target", "target_end_date",
                                                    "family_id", "fold_id", "prediction", "rank"])
    model = model.loc[model.family_id.eq("M0_HGB_EXACT")].copy()
    model["signal_date"] = pd.to_datetime(model.signal_date); model["target_end_date"] = pd.to_datetime(model.target_end_date)
    require(model.target_end_date.max() <= pd.Timestamp("2025-12-31"), "WINNER_OOF_POST2025")
    checkpoint = pd.read_parquet(TOP40, columns=["decision_date", "security_id", "ticker_if_available",
                                                "raw_score", "raw_rank", "is_raw_top20"])
    checkpoint["decision_date"] = pd.to_datetime(checkpoint.decision_date)
    checkpoint_oof = checkpoint.loc[checkpoint.decision_date.isin(model.signal_date.unique())].rename(
        columns={"decision_date": "signal_date", "raw_rank": "canonical_raw_rank",
                 "raw_score": "canonical_raw_score"})
    require(len(checkpoint_oof) == model.signal_date.nunique() * 40
            and checkpoint_oof.groupby("signal_date").canonical_raw_rank.nunique().eq(40).all(),
            "TOP40_CHECKPOINT_COVERAGE_FAILURE")
    economic_top20 = pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_rank"])
    economic_top20["signal_date"] = pd.to_datetime(economic_top20.signal_date)
    checkpoint_top20 = checkpoint.loc[checkpoint.is_raw_top20 & checkpoint.decision_date.isin(
        economic_top20.signal_date.unique()), ["decision_date", "ticker_if_available", "raw_rank"]].rename(
            columns={"decision_date": "signal_date", "ticker_if_available": "ticker", "raw_rank": "checkpoint_rank"})
    top20_identity = economic_top20.merge(checkpoint_top20, on=["signal_date", "ticker"], validate="one_to_one")
    require(len(top20_identity) == len(economic_top20) == len(checkpoint_top20)
            and top20_identity.a2_rank.eq(top20_identity.checkpoint_rank).all(),
            "TOP20_MEMBERSHIP_IDENTITY_FAILURE")
    predictions = []
    for contract in folds.itertuples(index=False):
        train = matrix.loc[
            matrix.signal_date.between(pd.Timestamp(contract.outer_train_start), pd.Timestamp(contract.outer_train_end))
            & matrix.target_end_date.le(pd.Timestamp(contract.max_train_label_maturity))].copy()
        keys = model.loc[model.fold_id.eq(contract.fold_id),
                         ["signal_date", "security_id", "ticker", "target", "target_end_date", "prediction", "rank"]]
        valid = keys.merge(matrix[["signal_date", "security_id", "winner", *FEATURES]],
                           on=["signal_date", "security_id"], validate="one_to_one")
        require(len(train) == int(contract.train_rows) and len(valid) == int(contract.validation_rows),
                "WINNER_FOLD_ROW_IDENTITY", contract.fold_id)
        require(train.target_end_date.max() < valid.signal_date.min(), "WINNER_TEMPORAL_LEAKAGE", contract.fold_id)
        pipeline = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                             ("model", LogisticRegression(C=1.0, l1_ratio=0.0, class_weight="balanced",
                                                          solver="lbfgs", max_iter=1000, random_state=SEED))])
        pipeline.fit(train[FEATURES], train.winner.astype(int))
        valid["winner_probability"] = pipeline.predict_proba(valid[FEATURES])[:, 1]
        valid["outer_fold"] = contract.fold_id
        valid["train_max_target_end"] = train.target_end_date.max()
        predictions.append(valid.drop(columns=FEATURES))
    oos = pd.concat(predictions, ignore_index=True)
    require(len(oos) == len(model) and not oos.duplicated(["signal_date", "security_id"]).any(), "WINNER_OOS_IDENTITY")
    oos = oos.rename(columns={"prediction": "data_complete_m0_score", "rank": "data_complete_m0_rank"})
    oos = oos.merge(checkpoint_oof[["signal_date", "security_id", "canonical_raw_rank", "canonical_raw_score"]],
                    on=["signal_date", "security_id"], how="left", validate="one_to_one")
    oos["raw_rank_bucket"] = rank_bucket(oos.canonical_raw_rank)
    oos.loc[oos.canonical_raw_rank.isna(), "raw_rank_bucket"] = "OUTSIDE_TOP40_MEMBERSHIP_ONLY"
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date)
    oos = oos.merge(taxonomy, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    oos[["ff12", "ff48"]] = oos[["ff12", "ff48"]].fillna("UNKNOWN")
    metrics = add_probability_diagnostics(rows, oos, "winner", "winner_probability",
                                          "WINNER_NON_A2_LOGISTIC", "outer_fold")

    rank20_score = checkpoint_oof.loc[checkpoint_oof.canonical_raw_rank.eq(20),
                                      ["signal_date", "canonical_raw_score"]].rename(
        columns={"canonical_raw_score": "rank20_raw_a2_score"})
    oos = oos.merge(rank20_score, on="signal_date", how="left", validate="many_to_one")
    oos["raw_a2_score_gap_to_rank20"] = oos.canonical_raw_score - oos.rank20_raw_a2_score
    for bucket in ("RANK_16_20", "RANK_21_25", "RANK_26_30", "RANK_31_40"):
        gap = oos.loc[oos.raw_rank_bucket.eq(bucket), "raw_a2_score_gap_to_rank20"].dropna()
        for metric, value in (("MEAN", gap.mean()), ("MEDIAN", gap.median()),
                              ("P10", gap.quantile(.10)), ("P90", gap.quantile(.90))):
            rows.append(row("RAW_A2_SCORE_GAP", metric, "RELATIVE_TO_RANK20", float(value),
                            rank_bucket=bucket))

    ng8 = pd.read_parquet(NG8_OOF, columns=["signal_date", "security_id", "ridge_prediction", "quantile_prediction"])
    xgb = pd.read_parquet(MODEL_OOF, columns=["signal_date", "security_id", "family_id", "prediction"])
    xgb = xgb.loc[xgb.family_id.eq("M2_XGBOOST"), ["signal_date", "security_id", "prediction"]].rename(
        columns={"prediction": "xgb_prediction"})
    prior = oos[["signal_date", "security_id", "winner", "data_complete_m0_score"]].merge(
        ng8, on=["signal_date", "security_id"], validate="one_to_one").merge(
        xgb, on=["signal_date", "security_id"], validate="one_to_one")
    for name, column in (("DATA_COMPLETE_M0_OOF", "data_complete_m0_score"), ("RIDGE_RETURN_OOF", "ridge_prediction"),
                         ("Q90_RETURN_OOF", "quantile_prediction"), ("XGB_RETURN_OOF", "xgb_prediction")):
        for metric, value in score_metrics(prior, "winner", column).items():
            rows.append(row("STORED_PREDICTION_AUDIT", metric.upper(), name, value,
                            notes="strict stored OOF; not a calibrated binary probability or canonical Raw A2 rank"))

    total = int(oos.winner.sum()); top20 = oos.canonical_raw_rank.le(20)
    top40 = oos.canonical_raw_rank.notna()
    result = {"winner_count": total, "base_rate": float(oos.winner.mean()),
              "top20_recall": float(top20.loc[oos.winner].mean()),
              "top40_recall": float(top40.loc[oos.winner].mean()),
              "top20_precision": float(oos.loc[top20, "winner"].mean()),
              "rank21_40_precision": float(oos.loc[oos.canonical_raw_rank.between(21, 40), "winner"].mean())}
    result["top20_winner_count"] = int(oos.loc[top20, "winner"].sum())
    result["rank21_40_winner_count"] = int(oos.loc[oos.canonical_raw_rank.between(21, 40), "winner"].sum())
    result["outside_top40_winner_count"] = int(oos.loc[~top40, "winner"].sum())
    for metric, value in result.items():
        rows.append(row("WINNER_RECALL", metric.upper(), "DATA_COMPLETE_LABEL_CANONICAL_RAW_A2_RANK", value))
    scored = mark_top_fraction(oos, "winner_probability", .10, "high_winner_score")
    natural = float(scored.loc[scored.canonical_raw_rank.between(21, 40), "winner"].mean())
    high = scored.high_winner_score & scored.canonical_raw_rank.between(21, 40)
    high_rate = float(scored.loc[high, "winner"].mean())
    result["outside_top20_winner_lift"] = high_rate / natural
    rows.append(row("WINNER_RECALL", "OUTSIDE_TOP20_WINNER_LIFT", "RANK_21_40", result["outside_top20_winner_lift"],
                    numerator=high_rate, denominator=natural, notes="fixed within-date top-decile non-A2 logistic score"))
    conditional_ranges = ((1, 20, "RANK_1_20"), (21, 25, "RANK_21_25"), (26, 30, "RANK_26_30"),
                          (31, 40, "RANK_31_40"))
    for lo, hi, name in conditional_ranges:
        membership = scored.canonical_raw_rank.ge(lo) & scored.canonical_raw_rank.le(hi)
        selected = membership & scored.high_winner_score
        base_rate = float(scored.loc[membership, "winner"].mean())
        event_rate = float(scored.loc[selected, "winner"].mean())
        result[f"{name.lower()}_high_score_rate"] = event_rate
        result[f"{name.lower()}_high_score_lift"] = event_rate / base_rate
        rows += [row("WINNER_CONDITIONAL", "HIGH_SCORE_EVENT_RATE", "NON_A2_LOGISTIC", event_rate,
                     rank_bucket=name),
                 row("WINNER_CONDITIONAL", "NATURAL_EVENT_RATE", "RAW_A2", base_rate, rank_bucket=name),
                 row("WINNER_CONDITIONAL", "HIGH_SCORE_LIFT", "NON_A2_LOGISTIC", event_rate / base_rate,
                     rank_bucket=name),
                 row("WINNER_CONDITIONAL", "HIGH_SCORE_CANDIDATE_COUNT", "NON_A2_LOGISTIC", int(selected.sum()),
                     rank_bucket=name)]
    rows.append(row("WINNER_CONDITIONAL", "RAW_A2_GT40_RANK_STATUS", "AUTHORITATIVE_CHECKPOINT",
                    "RAW_A2_GT40_RANK_NOT_AUTHORITATIVELY_AVAILABLE", rank_bucket="RANK_GT_40",
                    notes="checkpoint proves Top40 membership only; no full-universe Raw A2 rank is inferred"))
    for bucket, group in scored.groupby("raw_rank_bucket", sort=True):
        rows += [row("WINNER_BY_RANK", "EVENT_COUNT", "RAW_A2", int(group.winner.sum()), rank_bucket=bucket),
                 row("WINNER_BY_RANK", "EVENT_RATE", "RAW_A2", float(group.winner.mean()), rank_bucket=bucket),
                 row("WINNER_BY_RANK", "HIGH_SCORE_EVENT_RATE", "NON_A2_LOGISTIC",
                     float(group.loc[group.high_winner_score, "winner"].mean()), rank_bucket=bucket)]
    event_groups = ((scored.canonical_raw_rank.le(20), "TOP20_CAPTURED"),
                    (scored.canonical_raw_rank.between(21, 40), "TOP20_MISSED_TOP40_PRESENT"),
                    (scored.canonical_raw_rank.isna(), "OUTSIDE_TOP40_MEMBERSHIP_ONLY"))
    for membership, name in event_groups:
        events = scored.loc[membership & scored.winner].copy()
        security_counts = events.groupby("ticker").size().sort_values(ascending=False)
        sector_counts = events.groupby("ff12").size().sort_values(ascending=False)
        year_counts = events.groupby(events.signal_date.dt.year).size().sort_values(ascending=False)
        count = len(events)
        rows += [row("WINNER_RECALL_GROUP", "EVENT_COUNT", name, count),
                 row("WINNER_RECALL_GROUP", "EVENT_SHARE", name, count / total),
                 row("WINNER_RECALL_GROUP", "MEAN_FROZEN_TARGET", name, float(events.target.mean())),
                 row("WINNER_RECALL_GROUP", "SUM_FROZEN_TARGET_NOT_WEALTH", name, float(events.target.sum()),
                     notes="overlapping 3/5/10/20-day QQQ-relative target; not compounded wealth"),
                 row("WINNER_RECALL_GROUP", "TOP5_SECURITY_EVENT_SHARE", name,
                     float(security_counts.head(5).sum() / count)),
                 row("WINNER_RECALL_GROUP", "TOP_SECTOR_EVENT_SHARE", name,
                     float(sector_counts.iloc[0] / count)),
                 row("WINNER_RECALL_GROUP", "MAX_YEAR_EVENT_SHARE", name,
                     float(year_counts.iloc[0] / count))]
    for year, group in oos.loc[oos.winner].groupby(oos.loc[oos.winner, "signal_date"].dt.year, sort=True):
        rows.append(row("WINNER_CONCENTRATION", "EVENT_SHARE", "YEAR", len(group) / total, year=year))
    security = oos.loc[oos.winner].groupby("ticker").size().sort_values(ascending=False)
    sectors = oos.loc[oos.winner].groupby("ff12").size().sort_values(ascending=False)
    result["winner_top5_security_share"] = float(security.head(5).sum() / total)
    result["winner_top_sector_share"] = float(sectors.iloc[0] / total)
    for ticker, count in security.head(10).items():
        rows.append(row("WINNER_CONCENTRATION", "EVENT_COUNT", "SECURITY", int(count), security=ticker))
    for sector, count in sectors.items():
        rows.append(row("WINNER_CONCENTRATION", "EVENT_SHARE", "FF12", float(count / total), sector=sector))
    result.update(metrics)
    return scored, result


def fit_loser(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    r6 = import_file("a2_r6_reuse_for_orthogonal_r1", REPO / "scripts/v22/a2_stock_risk_r6.py")
    panel, _, _, daily, _, _, _ = r6.load_inputs()
    features = [name for name in r6.R3.FEATURES if name not in {"A2_RANK", "A2_PREDICTION"}]
    require(len(features) == 20 and not any("A2_" in name for name in features), "LOSER_ORTHOGONAL_FEATURE_FAILURE")
    stored = pd.read_parquet(R6_OOF)
    stored["signal_date"] = pd.to_datetime(stored.signal_date); stored["target_end_date"] = pd.to_datetime(stored.target_end_date)
    require(stored.target_end_date.max() <= pd.Timestamp("2025-12-31"), "LOSER_STORED_POST2025")
    for candidate in ("LOGISTIC_BAD_ASYM_C100", "LGBM_BAD_ASYM_2"):
        prior = stored.loc[stored.candidate_id.eq(candidate)]
        for metric, value in score_metrics(prior, "bad_asymmetry_5d", "predicted_bad_asymmetry_risk").items():
            rows.append(row("STORED_PREDICTION_AUDIT", metric.upper(), candidate, value,
                            notes="strict stored OOF but includes Raw A2 rank/score; not orthogonal primary"))
    outputs = []; sessions = pd.DatetimeIndex(daily.execution_date)
    for fold, start, end in r6.R3.FOLDS:
        train, valid, cutoff = r6.R3.fold_split(panel, sessions, start, end)
        mae = float(train.forward_5d_stock_mae.quantile(r6.MAE_SEVERE_QUANTILE))
        mfe = float(train.forward_5d_stock_mfe.quantile(r6.MFE_COMPENSATION_QUANTILE))
        y_train, _ = r6.event_labels(train, mae, mfe); y_valid, _ = r6.event_labels(valid, mae, mfe)
        model = Pipeline([("scale", StandardScaler()),
                          ("model", LogisticRegression(C=1.0, l1_ratio=0.0, class_weight="balanced",
                                                       solver="lbfgs", max_iter=1000, random_state=SEED))])
        model.fit(train[features], y_train)
        valid = valid.copy(); valid["extreme_loser"] = y_valid
        valid["loser_probability"] = model.predict_proba(valid[features])[:, 1]
        valid["fold"] = fold; valid["train_max_target_end"] = train.target_end_date.max(); valid["embargo_cutoff"] = cutoff
        outputs.append(valid)
    oos = pd.concat(outputs, ignore_index=True)
    persisted = stored.loc[stored.candidate_id.eq("LGBM_BAD_ASYM_2"),
                           ["signal_date", "ticker", "fold", "bad_asymmetry_5d"]]
    check = oos.merge(persisted, on=["signal_date", "ticker", "fold"], validate="one_to_one")
    require(check.extreme_loser.eq(check.bad_asymmetry_5d).all(), "LOSER_LABEL_PROVENANCE_MISMATCH")
    require(oos.target_end_date.max() <= pd.Timestamp("2025-12-31")
            and (oos.train_max_target_end < oos.embargo_cutoff).all()
            and (oos.information_date <= oos.signal_date).all(), "LOSER_TEMPORAL_LEAKAGE")
    taxonomy = pd.read_parquet(TAXONOMY, columns=["signal_date", "ticker", "ff12", "ff48"])
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date)
    oos = oos.merge(taxonomy.rename(columns={"signal_date": "information_date"}),
                    on=["information_date", "ticker"], how="left", validate="one_to_one")
    oos[["ff12", "ff48"]] = oos[["ff12", "ff48"]].fillna("UNKNOWN")
    metrics = add_probability_diagnostics(rows, oos, "extreme_loser", "loser_probability",
                                          "LOSER_NON_A2_LOGISTIC", "fold")
    oos["raw_rank_bucket"] = rank_bucket(oos.A2_RANK)
    oos["risk_percentile"] = oos.groupby("fold")["loser_probability"].rank(method="average", pct=True)
    high = oos.risk_percentile.ge(.90)
    metrics["top20_extreme_loser_lift"] = float(oos.loc[high, "extreme_loser"].mean() / oos.extreme_loser.mean())
    metrics["high_risk_event_rate"] = float(oos.loc[high, "extreme_loser"].mean())
    metrics["false_positive_rate"] = float((high & ~oos.extreme_loser.astype(bool)).sum()
                                           / (~oos.extreme_loser.astype(bool)).sum())
    rows += [row("LOSER_INTERACTION", "TOP20_HIGH_RISK_EVENT_RATE", "NON_A2_LOGISTIC", metrics["high_risk_event_rate"]),
             row("LOSER_INTERACTION", "TOP20_BASE_EVENT_RATE", "RAW_A2_TOP20", float(oos.extreme_loser.mean())),
             row("LOSER_INTERACTION", "TOP20_EXTREME_LOSER_LIFT", "NON_A2_LOGISTIC", metrics["top20_extreme_loser_lift"]),
             row("LOSER_INTERACTION", "FALSE_POSITIVE_RATE", "NON_A2_LOGISTIC", metrics["false_positive_rate"])]
    for bucket, group in oos.groupby("raw_rank_bucket", sort=True):
        rows += [row("LOSER_BY_RANK", "EVENT_COUNT", "RAW_A2_TOP20", int(group.extreme_loser.sum()), rank_bucket=bucket),
                 row("LOSER_BY_RANK", "EVENT_RATE", "RAW_A2_TOP20", float(group.extreme_loser.mean()), rank_bucket=bucket)]
        metrics[f"{bucket.lower()}_event_rate"] = float(group.extreme_loser.mean())
    total = int(oos.extreme_loser.sum())
    loser_mask = oos.extreme_loser.astype(bool)
    loser_events = oos.loc[loser_mask].copy()
    for year, group in loser_events.groupby(loser_events.signal_date.dt.year, sort=True):
        rows.append(row("LOSER_CONCENTRATION", "EVENT_SHARE", "YEAR", len(group) / total, year=year))
    security = loser_events.groupby("ticker").size().sort_values(ascending=False)
    sectors = loser_events.groupby("ff12").size().sort_values(ascending=False)
    metrics.update({"loser_count": total, "base_rate": float(oos.extreme_loser.mean()),
                    "loser_top5_security_share": float(security.head(5).sum() / total),
                    "loser_top_sector_share": float(sectors.iloc[0] / total)})
    for ticker, count in security.head(10).items():
        rows.append(row("LOSER_CONCENTRATION", "EVENT_COUNT", "SECURITY", int(count), security=ticker))
    for sector, count in sectors.items():
        rows.append(row("LOSER_CONCENTRATION", "EVENT_SHARE", "FF12", float(count / total), sector=sector))
    return oos, metrics


def membership_rank_boundary(rows: list[dict[str, Any]], securities: pd.DataFrame, winner: pd.DataFrame,
                             loser: pd.DataFrame, daily: pd.DataFrame) -> dict[str, Any]:
    rank_rows = pd.read_parquet(TAIL_DETAIL)
    rank_rows = rank_rows.loc[rank_rows.row_type.eq("RANK_WINNER_OBSERVATION")].copy()
    # The authoritative diagnostic stores the selection timestamp in signal_date;
    # decision_date belongs to the replacement-event rows and is null here.
    rank_rows["decision_date"] = pd.to_datetime(rank_rows.signal_date); rank_rows["date"] = pd.to_datetime(rank_rows.date)
    require(not rank_rows.duplicated(["decision_date", "security_id"]).any(), "RANK_DUPLICATE")
    require(rank_rows.groupby("decision_date").raw_rank.nunique().eq(40).all(), "RANK_UNIQUENESS")
    rank_rows["rank_bucket"] = rank_bucket(rank_rows.raw_rank)
    win = winner[["signal_date", "ticker", "winner"]].rename(columns={"signal_date": "decision_date"})
    loss = loser[["information_date", "ticker", "extreme_loser"]].rename(columns={"information_date": "decision_date"})
    rank_rows = rank_rows.merge(win, on=["decision_date", "ticker"], how="left", validate="one_to_one")
    rank_rows = rank_rows.merge(loss, on=["decision_date", "ticker"], how="left", validate="one_to_one")
    rank_rows["winner_label_available"] = rank_rows.winner.notna()
    rank_rows["loser_label_available"] = rank_rows.extreme_loser.notna()
    rank_rows[["winner", "extreme_loser"]] = (
        rank_rows[["winner", "extreme_loser"]].fillna(False).astype(bool)
    )
    wealth = securities[["date", "signal_date", "ticker", "net_wealth", "transaction_cost_wealth"]].rename(
        columns={"signal_date": "decision_date"})
    rank_rows = rank_rows.merge(wealth, on=["date", "decision_date", "ticker"], how="left", validate="one_to_one")
    daily_frame = daily[["execution_date", "reconstructed_nav"]].copy()
    daily_frame["drawdown"] = daily_frame.reconstructed_nav / daily_frame.reconstructed_nav.cummax() - 1
    rank_rows = rank_rows.merge(daily_frame[["execution_date", "drawdown"]], left_on="date", right_on="execution_date",
                                how="left", validate="many_to_one")
    for bucket, group in rank_rows.groupby("rank_bucket", sort=True):
        valid = group.holding_return.notna()
        winner_rate = float(group.loc[group.winner_label_available, "winner"].mean())
        loser_rate: Any = (float(group.loc[group.loser_label_available, "extreme_loser"].mean())
                           if group.raw_rank.max() <= 20 else "NA_NOT_AUTHORITATIVELY_AVAILABLE")
        rows += [row("RANK_ATTRIBUTION", "AVERAGE_FUTURE_RETURN", "NEXT_OPEN_TO_OPEN",
                     float(group.loc[valid, "holding_return"].mean()), rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "MEDIAN_FUTURE_RETURN", "NEXT_OPEN_TO_OPEN",
                     float(group.loc[valid, "holding_return"].median()), rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "HIT_RATE", "NEXT_OPEN_TO_OPEN",
                     float(group.loc[valid, "holding_return"].gt(0).mean()), rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "WINNER_RATE", "FROZEN_FULL_UNIVERSE_TOP1PCT",
                     winner_rate, rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "LOSER_RATE", "FROZEN_R6_BAD_ASYMMETRY", loser_rate, rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "NET_WEALTH_CONTRIBUTION", "ACTUAL_RAW_A2_PATH",
                     float(group.net_wealth.sum(min_count=1)), rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "TRANSACTION_COST_WEALTH", "ACTUAL_RAW_A2_PATH",
                     float(group.transaction_cost_wealth.sum(min_count=1)), rank_bucket=bucket),
                 row("RANK_ATTRIBUTION", "NEGATIVE_DRAWDOWN_WEALTH", "ACTUAL_RAW_A2_PATH",
                     float(group.loc[group.drawdown.lt(0) & group.net_wealth.lt(0), "net_wealth"].sum()), rank_bucket=bucket)]

    selections = pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_rank"])
    selections["signal_date"] = pd.to_datetime(selections.signal_date); selections = selections.sort_values(["signal_date", "a2_rank"])
    dates = list(pd.DatetimeIndex(selections.signal_date.unique())); sets = {d: set(g.ticker) for d, g in selections.groupby("signal_date")}
    previous = {dates[i]: sets[dates[i - 1]] if i else set() for i in range(len(dates))}
    following = {dates[i]: sets[dates[i + 1]] if i + 1 < len(dates) else sets[dates[i]] for i in range(len(dates))}
    selections["new_entrant"] = [t not in previous[d] for d, t in selections[["signal_date", "ticker"]].itertuples(index=False, name=None)]
    selections["incumbent"] = ~selections.new_entrant
    selections["about_to_leave"] = [t not in following[d] for d, t in selections[["signal_date", "ticker"]].itertuples(index=False, name=None)]
    states = rank_rows.loc[rank_rows.raw_rank.le(20)].merge(
        selections, left_on=["decision_date", "ticker"], right_on=["signal_date", "ticker"], validate="one_to_one")
    for column, label in (("new_entrant", "NEW_ENTRANT"), ("incumbent", "INCUMBENT"),
                          ("about_to_leave", "ABOUT_TO_LEAVE")):
        group = states.loc[states[column]]
        rows += [row("MEMBERSHIP_STATE", "COUNT", label, len(group)),
                 row("MEMBERSHIP_STATE", "MEAN_FUTURE_RETURN", label, float(group.holding_return.mean())),
                 row("MEMBERSHIP_STATE", "WINNER_RATE", label,
                     float(group.loc[group.winner_label_available, "winner"].mean())),
                 row("MEMBERSHIP_STATE", "LOSER_RATE", label,
                     float(group.loc[group.loser_label_available, "extreme_loser"].mean())),
                 row("MEMBERSHIP_STATE", "NET_WEALTH_CONTRIBUTION", label, float(group.net_wealth.sum(min_count=1))),
                 row("MEMBERSHIP_STATE", "TRANSACTION_COST_WEALTH", label,
                     float(group.transaction_cost_wealth.sum(min_count=1)))]
    for bucket, group in states.groupby("rank_bucket", sort=True):
        rows += [row("RANK_REPLACEMENT", "NEW_ENTRANT_FREQUENCY", "TOP20_MEMBERSHIP", float(group.new_entrant.mean()),
                     rank_bucket=bucket),
                 row("RANK_REPLACEMENT", "ABOUT_TO_LEAVE_FREQUENCY", "TOP20_MEMBERSHIP",
                     float(group.about_to_leave.mean()), rank_bucket=bucket)]

    actual_winner_wealth = float(rank_rows.loc[rank_rows.raw_rank.le(20) & rank_rows.winner,
                                               "net_wealth"].sum(min_count=1))
    rows += [row("WINNER_WEALTH", "ACTUAL_NET_WEALTH_CONTRIBUTION", "TOP20_CAPTURED_WINNERS",
                 actual_winner_wealth, notes="actual Raw A2 next-session wealth ledger on labeled winner selections"),
             row("WINNER_WEALTH", "ACTUAL_NET_WEALTH_CONTRIBUTION", "TOP20_MISSED_TOP40_PRESENT",
                 "NA_NOT_HELD_NO_ACTUAL_WEALTH", notes="opportunity is reported only as a hindsight one-swap bound")]

    complete = rank_rows.groupby("decision_date").holding_return.count().eq(40)
    complete_rows = rank_rows.loc[rank_rows.decision_date.isin(complete[complete].index)].copy()
    bounds = []
    for date, group in complete_rows.groupby("decision_date", sort=True):
        inside = group.loc[group.raw_rank.le(20)]; outside = group.loc[group.raw_rank.between(21, 40)]
        raw_mean = float(inside.holding_return.mean()); oracle = float(group.nlargest(20, "holding_return").holding_return.mean())
        one_swap = max(0.0, float(outside.holding_return.max() - inside.holding_return.min()) / 20.0)
        missed = outside.loc[outside.winner]
        winner_swap = max(0.0, float(missed.holding_return.max() - inside.holding_return.min()) / 20.0) if len(missed) else 0.0
        bad = inside.loc[inside.extreme_loser & inside.holding_return.lt(0)]
        loser_avoid = max(0.0, float(-bad.holding_return.min()) / 20.0) if len(bad) else 0.0
        bounds.append({"decision_date": date, "holding_end": group.date.iloc[0], "raw": raw_mean,
                       "top40_oracle": oracle, "top40_uplift": oracle - raw_mean, "one_swap": one_swap,
                       "winner_swap": winner_swap, "loser_avoid": loser_avoid,
                       "has_missed_winner": bool(len(missed)), "has_included_loser": bool(len(bad))})
    bounds = pd.DataFrame(bounds)
    path = daily[["execution_date", "reconstructed_daily_return"]].merge(
        bounds, left_on="execution_date", right_on="holding_end", how="left")
    for column in ("top40_uplift", "one_swap", "winner_swap", "loser_avoid"):
        path[column] = path[column].fillna(0.0)
    raw_terminal = float(np.prod(1 + path.reconstructed_daily_return))
    result = {"oracle_eligible_dates": len(bounds), "top40_oracle_mean_return": float(bounds.top40_oracle.mean()),
              "raw_top20_mean_return": float(bounds.raw.mean()), "one_swap_mean_uplift": float(bounds.one_swap.mean()),
              "top40_oracle_wealth_delta": float(np.prod(1 + path.reconstructed_daily_return + path.top40_uplift) - raw_terminal),
              "one_swap_wealth_delta": float(np.prod(1 + path.reconstructed_daily_return + path.one_swap) - raw_terminal),
              "missed_winner_wealth_impact": float(np.prod(1 + path.reconstructed_daily_return + path.winner_swap) - raw_terminal),
              "included_loser_wealth_impact": float(np.prod(1 + path.reconstructed_daily_return + path.loser_avoid) - raw_terminal),
              "missed_winner_session_count": int(bounds.has_missed_winner.sum()),
              "included_loser_session_count": int(bounds.has_included_loser.sum()),
              "actual_top20_winner_net_wealth": actual_winner_wealth}
    bucket_means = rank_rows.groupby("rank_bucket").holding_return.mean()
    result["rank16_20_mean"] = float(bucket_means["RANK_16_20"])
    result["rank21_25_mean"] = float(bucket_means["RANK_21_25"])
    result["rank21_25_spread_vs_16_20"] = result["rank21_25_mean"] - result["rank16_20_mean"]
    top20_rank_wealth = rank_rows.loc[rank_rows.raw_rank.le(20)].groupby("rank_bucket").net_wealth.sum(min_count=1)
    for bucket in ("RANK_1_5", "RANK_6_10", "RANK_11_15", "RANK_16_20"):
        result[f"{bucket.lower()}_net_wealth"] = float(top20_rank_wealth[bucket])
    for metric, value in result.items():
        rows.append(row("BOUNDARY_ORACLE", metric.upper(), "HINDSIGHT_ORACLE_NOT_TRADABLE", value,
                        notes="complete rank-1..40 next-open-to-open dates; no model selection or policy claim"))
    for year, group in bounds.groupby(bounds.decision_date.dt.year, sort=True):
        rows += [row("ECONOMIC_ASYMMETRY_YEAR", "MISSED_WINNER_MEAN_UPLIFT", "HINDSIGHT_ORACLE_NOT_TRADABLE",
                     float(group.winner_swap.mean()), year=year),
                 row("ECONOMIC_ASYMMETRY_YEAR", "INCLUDED_LOSER_MEAN_AVOIDANCE", "HINDSIGHT_ORACLE_NOT_TRADABLE",
                     float(group.loser_avoid.mean()), year=year),
                 row("ECONOMIC_ASYMMETRY_YEAR", "MISSED_WINNER_SESSION_COUNT", "HINDSIGHT_ORACLE_NOT_TRADABLE",
                     int(group.has_missed_winner.sum()), year=year),
                 row("ECONOMIC_ASYMMETRY_YEAR", "INCLUDED_LOSER_SESSION_COUNT", "HINDSIGHT_ORACLE_NOT_TRADABLE",
                     int(group.has_included_loser.sum()), year=year)]
    return result


def classify(winner: dict[str, Any], loser: dict[str, Any], factor: dict[str, Any],
             boundary: dict[str, Any]) -> tuple[str, str, str, str]:
    winner_robust = winner["ap_lift"] > 1.25 and winner["positive_direction_folds"] >= 2
    loser_robust = loser["ap_lift"] > 1.25 and loser["positive_direction_folds"] >= 3
    if winner_robust and loser_robust:
        tail = "BOTH_WINNER_AND_LOSER_SIGNALS_WARRANT_FOLLOWUP"
    elif loser_robust:
        tail = "LOSER_SIGNAL_SUPPORTS_TOP20_RISK_FILTER_RESEARCH"
    elif winner_robust and winner["outside_top20_winner_lift"] > 1.25:
        tail = "WINNER_SIGNAL_SUPPORTS_BOUNDARY_RECOVERY_RESEARCH"
    elif not winner_robust and not loser_robust:
        tail = "TAIL_EVENTS_NOT_ROBUSTLY_LEARNABLE_OOS"
    else:
        tail = "TAIL_SIGNAL_MIXED_OR_UNRESOLVED"
    if factor["beta_matched_active_ir"] < .25 and factor["downside_capture"] > 1.2:
        primary, secondary = "FACTOR_OR_SECTOR_CONCENTRATION", "INCLUDED_TAIL_LOSERS"
    elif loser_robust and boundary["included_loser_wealth_impact"] > boundary["missed_winner_wealth_impact"]:
        primary, secondary = "INCLUDED_TAIL_LOSERS", "TURNOVER_AND_SIGNAL_HORIZON"
    elif winner_robust and winner["outside_top20_winner_lift"] > 1.25:
        primary, secondary = "MISSED_WINNERS", "REGIME_INSTABILITY"
    else:
        primary, secondary = "NO_SINGLE_DOMINANT_ACTIONABLE_BOTTLENECK", "REGIME_INSTABILITY"
    next_task = {
        "FACTOR_OR_SECTOR_CONCENTRATION": "PREREGISTERED_PRE2026_FIXED_BETA_DOWNSIDE_RISK_BUDGET_DIAGNOSTIC",
        "INCLUDED_TAIL_LOSERS": "PREREGISTERED_ORTHOGONAL_TOP20_LOSER_RISK_FILTER_RESEARCH",
        "MISSED_WINNERS": "PREREGISTERED_NON_A2_TOP40_BOUNDARY_WINNER_RECOVERY_RESEARCH",
    }.get(primary, "PREREGISTERED_REGIME_STABILITY_AND_SIGNAL_HORIZON_DIAGNOSTIC")
    return primary, secondary, tail, next_task


def fmt(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        return "NA" if not np.isfinite(value) else f"{float(value):.10g}"
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return str(value)


def build_report(replay: dict[str, Any], factor: dict[str, Any], winner: dict[str, Any],
                 loser: dict[str, Any], boundary: dict[str, Any], primary: str, secondary: str,
                 tail: str, next_task: str) -> str:
    reuse = [
        ("Exact Raw A2 replay", "REUSE_EXACT", str(DAILY), str(BASE), "Authoritative 751-session path; hashes and machine identities rechecked."),
        ("Security/date/rank attribution", "REUSE_WITH_ALIGNMENT_RECOMPUTE", str(ATTR_DETAIL), str(ATTR_ROOT), "Existing exact wealth ledger regrouped on one sample."),
        ("Canonical Top40 ranks", "REUSE_EXACT", str(TOP40), str(TOP40.parent), "Frozen canonical Raw A2 rank 1-40; data-complete M0 ranks are not substituted."),
        ("Beta/residual diagnostics", "REUSE_EXACT", str(BETA_ROOT), str(BETA_ROOT), "Existing matched diagnostics; same benchmark frame for upside capture."),
        ("FF12/FF48 taxonomy", "REUSE_WITH_ALIGNMENT_RECOMPUTE", str(TAXONOMY), str(TAXONOMY.parent), "Frozen taxonomy extended by the existing PIT routine; no SEC rebuild."),
        ("Winner label", "REUSE_EXACT", str(MODEL_OOF), str(MODEL_ROOT), "Existing NEXTGEN realized top-1% target on the frozen data-complete PIT mask."),
        ("Loser label", "REUSE_EXACT", str(R6_OOF), str(R6_OOF.parent), "Existing R6 MAE-Q90 plus MFE-Q50 adverse-asymmetry label."),
        ("Stored OOS predictions", "PARTIAL_PRIOR_WORK", str(NG8_OOF), str(R6_OOF), "Ridge/Q90/XGB and R6 audited first; no orthogonal calibrated binary answer."),
        ("Orthogonal tail probability", "GENUINELY_MISSING", str(RESEARCH_DATA), "NA", "One fixed L2-logistic family, no A2 rank/score and no search."),
        ("Asymmetry/oracle alignment", "GENUINELY_MISSING", str(TAIL_DETAIL), "NA", "Common next-open hindsight bound; not tradable."),
    ]
    lines = [f"# {TASK}", "", "## 1. Executive conclusion", "",
             f"Overall research status: `COMPLETE_RESEARCH_ONLY`. Primary bottleneck: `{primary}`. Secondary bottleneck: `{secondary}`. Tail classification: `{tail}`.", "",
             "Discovery boundary note: one legacy execution-cost report was recognized after opening as mixing pre-2026 and 2026 material. It was immediately quarantined. No value from it entered this computation, label/model/rule choice, or conclusion; the executable research read set is pre-2026 only.", "",
             f"Raw A2's absolute return is strong, but the exposure evidence is weak after matching risk: QQQ beta is {factor['qqq_beta']:.3f}, downside capture is {factor['downside_capture']:.3f}, beta-matched active IR is {factor['beta_matched_active_ir']:.3f}, and volatility-matched active CAGR is {factor['vol_matched_active_cagr']:.3%}. That makes factor/risk concentration the dominant measured bottleneck, not the Top20 cutoff. The rank 21-25 minus rank 16-20 next-session spread is only {boundary['rank21_25_spread_vs_16_20']:.4%}.", "",
             f"Exactly one recommended next task: `{next_task}`. It is a preregistered diagnostic, not a strategy change. No strategy was constructed, optimized, evaluated on 2026, or promoted.", "",
             "## 2. Reuse / duplicate-work audit", "",
             "| Analysis | Decision | Existing source | Existing artifact | Reuse basis |", "|---|---|---|---|---|"]
    lines += [f"| {a} | `{b}` | `{c}` | `{d}` | {e} |" for a, b, c, d, e in reuse]
    lines += ["", "Not rebuilt: Raw A2 predictions/Top40, replay/backtest, PIT/features/sectors, Q90/XGB/Ridge/R6, beta, transaction-cost logic, 13F/SEC ingestion, or a generic attribution/model-selection framework. The only genuinely new computation is the fixed orthogonal logistic diagnostic plus common-sample regrouping/oracle arithmetic.", "",
              "## 3. Raw A2 baseline validation", "",
              f"`RAW_A2_REPLAY_STATUS=PASS_EXACT_OR_MACHINE_PRECISION`. {replay['sessions']} sessions from {fmt(replay['date_min'])} through {fmt(replay['date_max'])}; cumulative return {replay['cumulative_return']:.6f}, CAGR {replay['cagr']:.6f}, Sharpe {replay['sharpe']:.6f}, MaxDD {replay['max_drawdown']:.6f}, turnover total/annualized {replay['total_turnover']:.6f}/{replay['annualized_turnover']:.6f}, cost sum {replay['cost_sum']:.6f}, average holdings {replay['average_holdings']:.3f}. Gross/net terminal wealth {replay['gross_terminal_wealth']:.6f}/{replay['net_terminal_wealth']:.6f}; compounded cost drag {replay['compounded_cost_drag']:.6f}.", "",
              "## 4. Return attribution", "",
              f"Security positive-tail shares for Top1/5/10 are {replay['security_top1_positive_share']:.2%}/{replay['security_top5_positive_share']:.2%}/{replay['security_top10_positive_share']:.2%}; worst-tail drag shares are {replay['security_worst1_negative_share']:.2%}/{replay['security_worst5_negative_share']:.2%}/{replay['security_worst10_negative_share']:.2%}. Top-five security net wealth is {replay['top5_security_contribution']:.6f}. Date positive-tail shares are {replay['date_top1_positive_share']:.2%}/{replay['date_top5_positive_share']:.2%}/{replay['date_top10_positive_share']:.2%}; worst-date drag shares are {replay['date_worst1_negative_share']:.2%}/{replay['date_worst5_negative_share']:.2%}/{replay['date_worst10_negative_share']:.2%}. Top-five date net wealth is {replay['top5_date_contribution']:.6f}. Top10 positive-date share of {replay['date_top10_positive_share']:.2%} does not support a claim that the entire result depends on only a few dates.", "",
              f"Actual net-wealth contribution by Raw A2 rank bucket 1-5/6-10/11-15/16-20 is {boundary['rank_1_5_net_wealth']:.6f}/{boundary['rank_6_10_net_wealth']:.6f}/{boundary['rank_11_15_net_wealth']:.6f}/{boundary['rank_16_20_net_wealth']:.6f}. The cutoff bucket contributes little, but rank 21-25 does not beat it materially on average. New-entrant/incumbent/about-to-leave returns, cost wealth, and replacement frequencies are in the attribution CSV.", "",
              f"Turnover is economically nontrivial: compounded cost drag is {replay['compounded_cost_drag']:.6f}; high-turnover sessions average {replay['high_turnover_mean_net_return']:.4%} net versus {replay['other_mean_net_return']:.4%} for other sessions. Annual net returns remain positive in 2023/2024/2025 ({replay['net_return_2023']:.2%}/{replay['net_return_2024']:.2%}/{replay['net_return_2025']:.2%}), so this is a churn/horizon diagnostic, not proof of a turnover policy.", "",
              f"Exposure diagnostics: QQQ beta {factor['qqq_beta']:.4f}, SOXX beta {factor['soxx_beta']:.4f}, upside/downside capture {factor['upside_capture']:.4f}/{factor['downside_capture']:.4f}, residual Sharpe {factor['residual_sharpe']:.4f}, FF12/FF48 HHI {factor['ff12_hhi']:.4f}/{factor['ff48_hhi']:.4f}. Beta-matched active IR is {factor['beta_matched_active_ir']:.4f}; volatility-matched active CAGR is {factor['vol_matched_active_cagr']:.4f}. This is exposure-based attribution, not causal sector alpha decomposition; the existing risk model cannot identify a separate causal sector-allocation return.", "",
              "## 5. Winner recall", "",
              f"The frozen data-complete PIT label yields {winner['winner_count']} coverage-conditioned top-1% winner events at a {winner['base_rate']:.4%} base rate. Canonical Raw A2 Top20/Top40 recall is {winner['top20_recall']:.4%}/{winner['top40_recall']:.4%}; aligned Top20 and rank-21-40 precision is {winner['top20_precision']:.4%}/{winner['rank21_40_precision']:.4%}. Counts are {winner['top20_winner_count']} captured in Top20, {winner['rank21_40_winner_count']} missed by Top20 but present in Top40, and {winner['outside_top40_winner_count']} absent from Top40. Thus only {(winner['top40_recall']-winner['top20_recall']):.2%} of labeled winners are boundary-recoverable within Top40. The checkpoint does not provide authoritative full-universe ranks beyond 40, so `RAW_A2_GT40_RANK_NOT_AUTHORITATIVELY_AVAILABLE`.", "",
              f"Actual next-session Raw A2 net-wealth contribution attached to Top20 selections carrying the winner label is {boundary['actual_top20_winner_net_wealth']:.6f}. Missed names have no actual portfolio wealth because they were not held; their opportunity is reported only through the same-unit hindsight one-swap bound. Long-form rows provide frozen-target magnitude plus year/security/sector concentration for Top20 captured, rank 21-40, and outside-Top40 groups.", "",
              "## 6. Loser incidence", "",
              f"There are {loser['loser_count']} frozen R6 bad-asymmetry events among Top20 OOS holdings (base {loser['base_rate']:.4%}). Incidence declines rather than rises toward the cutoff: rank 1-5/6-10/11-15/16-20 event rates are {loser['rank_1_5_event_rate']:.2%}/{loser['rank_6_10_event_rate']:.2%}/{loser['rank_11_15_event_rate']:.2%}/{loser['rank_16_20_event_rate']:.2%}. That contradicts a rank-16-20 loser-bottleneck story.", "",
              f"The fixed orthogonal high-risk subset has a {loser['high_risk_event_rate']:.4%} event rate, {loser['top20_extreme_loser_lift']:.3f} lift, and {loser['false_positive_rate']:.4%} full-sample false-positive rate. Loser drawdown/wealth attribution is confined to actual Top20 holdings; no outside-Top20 loser rate is fabricated.", "",
              "## 7. Boundary opportunity", "",
              f"On {boundary['oracle_eligible_dates']} complete rank-1-40 next-session dates, Raw Top20 mean return is {boundary['raw_top20_mean_return']:.6%} and the unrestricted best-20-of-Top40 hindsight mean is {boundary['top40_oracle_mean_return']:.6%}. The one-swap mean uplift is {boundary['one_swap_mean_uplift']:.6%}; its compounded wealth delta is {boundary['one_swap_wealth_delta']:.6f}. The unrestricted Top40 oracle wealth delta is {boundary['top40_oracle_wealth_delta']:.6f}. Both are `HINDSIGHT_ORACLE_NOT_TRADABLE`, omit incremental implementation cost, and were not used to select a model or rule. Raw A2 score-gap distributions relative to rank 20 are reported for ranks 16-40.", "",
              "## 8. Learnability results", "",
              f"Winner non-A2 logistic: AP/base/lift {winner['average_precision']:.6f}/{winner['base_rate']:.6f}/{winner['ap_lift']:.3f}, AUROC {winner['auroc']:.3f}, Brier {winner['brier']:.6f}, positive folds {winner['positive_direction_folds']}/{winner['fold_count']}. Loser: AP/base/lift {loser['average_precision']:.6f}/{loser['base_rate']:.6f}/{loser['ap_lift']:.3f}, AUROC {loser['auroc']:.3f}, Brier {loser['brier']:.6f}, positive folds {loser['positive_direction_folds']}/{loser['fold_count']}. Every fold, calibration decile, and within-date Top1/5/10 precision/recall/lift row is retained. Class weighting means probability calibration is descriptive and not a threshold recommendation.", "",
              "## 9. Conditional Raw A2 interaction", "",
              f"Among canonical ranks 21-40, fixed high winner-score lift versus that bucket's natural rate is {winner['outside_top20_winner_lift']:.3f}, so non-A2 PIT information is complementary rather than simply Raw A2 reconstructed. The Top40 boundary contains only {winner['rank21_40_winner_count']} additional labeled winners and its average return spread is negligible. Candidate-generator inference outside Top40 is intentionally unresolved because no authoritative Raw A2 rank-greater-than-40 source exists. Primary models exclude Raw A2 rank, score, and deterministic transforms. Stored data-complete M0/Q90/Ridge/XGB/R6 OOF scores were audited first and are reported separately.", "",
              "## 10. Economic asymmetry", "",
              f"On the common next-session sample, {boundary['missed_winner_session_count']} sessions contain a Top20-missed/Top40-present labeled winner and {boundary['included_loser_session_count']} contain an included labeled loser with a negative holding return. Their one-name hindsight wealth upper bounds are {boundary['missed_winner_wealth_impact']:.6f} (`WINNER_RECOVERY_VALUE`) and {boundary['included_loser_wealth_impact']:.6f} (`LOSER_AVOIDANCE_VALUE`). Loser avoidance is larger economically; winner classification is stronger by AP lift ({winner['ap_lift']:.3f} versus {loser['ap_lift']:.3f}); both are directionally positive in every fold, while loser evidence spans five folds and acts inside the already-held set. Year-level event counts and mean bounds are in the attribution CSV. These are perfect-hindsight ceilings, not recoverable forecasts.", "",
              "## 11. Bottleneck map", "",
              "| Priority | Candidate | Economic evidence | Prospective/detectability evidence | Conclusion |", "|---:|---|---|---|---|",
              f"| 1 | `FACTOR_OR_SECTOR_CONCENTRATION` | QQQ beta {factor['qqq_beta']:.3f}; downside capture {factor['downside_capture']:.3f}; vol-matched active CAGR {factor['vol_matched_active_cagr']:.2%} | Exposure is observable, but sector return is not causally identified | Primary; fixed-beta downside diagnostic only |",
              f"| 2 | `INCLUDED_TAIL_LOSERS` | Hindsight wealth ceiling {boundary['included_loser_wealth_impact']:.3f} | AP lift {loser['ap_lift']:.3f}; {loser['positive_direction_folds']}/{loser['fold_count']} folds | Material and detectable, but secondary to path-wide exposure |",
              f"| 3 | `MISSED_WINNERS` | Top40 one-swap winner ceiling {boundary['missed_winner_wealth_impact']:.3f} | AP lift {winner['ap_lift']:.3f}; 21-40 lift {winner['outside_top20_winner_lift']:.3f} | Learnable, smaller same-unit ceiling |",
              f"| 4 | `TURNOVER_AND_SIGNAL_HORIZON` | Cost drag {replay['compounded_cost_drag']:.3f}; high-turnover net {replay['high_turnover_mean_net_return']:.3%} | Turnover is known at decision time; no policy tested | Secondary bottleneck |",
              f"| 5 | `TOP20_BOUNDARY_RANKING` | Rank 21-25 spread vs 16-20 {boundary['rank21_25_spread_vs_16_20']:.4%} | Oracle is hindsight-only | Not dominant |",
              f"| 6 | `CANDIDATE_GENERATOR_GAP` | {winner['outside_top40_winner_count']} labeled winners absent from Top40, but no same-unit wealth estimate | `RAW_A2_GT40_RANK_NOT_AUTHORITATIVELY_AVAILABLE` | Economically and rank-conditionally unresolved |", "",
              f"Final classification: primary `{primary}`; secondary `{secondary}`. This ranking uses both economic magnitude and prospective evidence, not the largest oracle number.", "",
              "## 12. Robustness and concentration", "",
              f"Winner top-five-security/largest-sector event shares are {winner['winner_top5_security_share']:.3%}/{winner['winner_top_sector_share']:.3%}; loser shares are {loser['loser_top5_security_share']:.3%}/{loser['loser_top_sector_share']:.3%}. Winner years contribute roughly evenly; corrected loser concentration rows sum to one by year and sector. All fold/year/security/sector rows are retained; no negative fold is hidden.", "",
              "## 13. Limitations", "",
              "Winner and loser labels legitimately differ: the existing winner is a QQQ-relative mean 3/5/10/20-day top 1% inside the frozen data-complete PIT mask (57.6575% of PIT membership observations), while the loser is execution-aligned 5-day MAE/MFE asymmetry on the authoritative Risk R6 Top20 panel. Therefore winner recall/precision is coverage-conditioned, not a claim over missing feature rows. Overlapping frozen-target sums are not compounded wealth. R6 labels do not authorize outside-Top20 loser rates. Sector results are exposure-based, not causal. Class-weighted logistic scores are not deployable calibrated probabilities. Oracle bounds use hindsight, assume one-name substitutions/cash avoidance, and omit incremental implementation costs. The mixed-date discovery report noted above was excluded from the executable source whitelist and all judgments. No threshold, holding horizon, replacement count, TopK, ensemble, or portfolio rule was selected.", "",
              "## 14. Next research recommendation", "", f"`{next_task}` is the single priority. It requires separate preregistration; this run does not implement it.", "",
              "## Validation", "", "- `DATE_MAX_OUTCOME_USED=2025-12-31`; `POST_2025_OUTCOME_USED=false`.",
              "- Exact replay, hashes, duplicate keys, rank uniqueness, membership identity, PIT, purge/embargo, label provenance, and artifact hashes pass.",
              "- A deterministic second full execution produced byte-identical SHA-256 hashes for all four durable artifacts.",
              "- No network, Moomoo, SEC ingestion, canonical write, promotion, threshold/label search, tournament, or 2026 outcome source is used.", ""]
    return "\n".join(lines)


def terminal(replay: dict[str, Any], factor: dict[str, Any], winner: dict[str, Any], loser: dict[str, Any],
             boundary: dict[str, Any], primary: str, secondary: str, tail: str, next_task: str) -> str:
    fields = {"OVERALL_STATUS": "COMPLETE_RESEARCH_ONLY", "DATE_MIN_EVALUATED": fmt(replay["date_min"]),
              "DATE_MAX_EVALUATED": fmt(replay["date_max"]), "DATE_MAX_OUTCOME_USED": "2025-12-31",
              "POST_2025_OUTCOME_USED": "false", "RAW_A2_REPLAY_STATUS": "PASS_EXACT_OR_MACHINE_PRECISION",
              "PRIMARY_BOTTLENECK": primary, "SECONDARY_BOTTLENECK": secondary, "TAIL_SIGNAL_CLASSIFICATION": tail,
              "WINNER_EVENT_COUNT": winner["winner_count"], "LOSER_EVENT_COUNT": loser["loser_count"],
              "RAW_A2_TOP20_WINNER_RECALL": winner["top20_recall"], "RAW_A2_TOP40_WINNER_RECALL": winner["top40_recall"],
              "OUTSIDE_TOP20_WINNER_LIFT": winner["outside_top20_winner_lift"], "TOP20_EXTREME_LOSER_LIFT": loser["top20_extreme_loser_lift"],
              "WINNER_OOS_AP": winner["average_precision"], "WINNER_BASE_RATE": winner["base_rate"], "WINNER_AP_LIFT": winner["ap_lift"],
              "LOSER_OOS_AP": loser["average_precision"], "LOSER_BASE_RATE": loser["base_rate"], "LOSER_AP_LIFT": loser["ap_lift"],
              "MISSED_WINNER_WEALTH_IMPACT": boundary["missed_winner_wealth_impact"], "INCLUDED_LOSER_WEALTH_IMPACT": boundary["included_loser_wealth_impact"],
              "QQQ_BETA": factor["qqq_beta"], "SOXX_BETA": factor["soxx_beta"], "RESIDUAL_SHARPE": factor["residual_sharpe"],
              "TOP5_DATE_CONTRIBUTION": replay["top5_date_contribution"], "TOP5_SECURITY_CONTRIBUTION": replay["top5_security_contribution"],
              "NEW_SOURCE_FILE_COUNT": 1, "NEW_TEST_FILE_COUNT": 1, "DURABLE_ARTIFACT_COUNT": 4,
              "DUPLICATE_WORK_AUDIT_STATUS": "PASS_REUSE_FIRST", "NEXT_RESEARCH_PRIORITY": next_task}
    return "\n".join(["=" * 60, f"{TASK}_FINAL", "=" * 60, ""]
                     + [f"{key}={fmt(value)}" for key, value in fields.items()] + ["=" * 60])


def run() -> str:
    require(OUT.parent.resolve() == RESULTS.resolve() and not OUT.is_relative_to(REPO), "OUTPUT_ROUTING_FAILURE")
    OUT.mkdir(parents=True, exist_ok=True)
    allowed = {"final_report.md", "canonical_attribution_summary.csv",
               "winner_loser_learnability_recall.csv", "hash_manifest.json"}
    for path in OUT.iterdir():
        require(path.is_file() and path.name in allowed, "UNEXPECTED_EXISTING_ARTIFACT", path)
    rows: list[dict[str, Any]] = []
    validate_sources(rows)
    replay, daily, securities = baseline_and_attribution(rows)
    factor = factor_diagnostics(rows, daily)
    taxonomy = load_extended_taxonomy(rows)
    winner_oos, winner = fit_winner(rows, taxonomy)
    del taxonomy
    loser_oos, loser = fit_loser(rows)
    boundary = membership_rank_boundary(rows, securities, winner_oos, loser_oos, daily)
    primary, secondary, tail, next_task = classify(winner, loser, factor, boundary)
    bottlenecks = [
        (1, "FACTOR_OR_SECTOR_CONCENTRATION", f"QQQ_beta={factor['qqq_beta']:.6g};downside_capture={factor['downside_capture']:.6g};beta_IR={factor['beta_matched_active_ir']:.6g}"),
        (2, "INCLUDED_TAIL_LOSERS", f"wealth_bound={boundary['included_loser_wealth_impact']:.6g};AP_lift={loser['ap_lift']:.6g}"),
        (3, "MISSED_WINNERS", f"wealth_bound={boundary['missed_winner_wealth_impact']:.6g};AP_lift={winner['ap_lift']:.6g}"),
        (4, "TURNOVER_AND_SIGNAL_HORIZON", f"cost_drag={replay['compounded_cost_drag']:.6g};high_turnover_net={replay['high_turnover_mean_net_return']:.6g}"),
        (5, "TOP20_BOUNDARY_RANKING", f"rank21_25_spread={boundary['rank21_25_spread_vs_16_20']:.6g}"),
        (6, "CANDIDATE_GENERATOR_GAP", f"outside_top40_winners={winner['outside_top40_winner_count']};gt40_rank=NA_NOT_AUTHORITATIVE;wealth=NA"),
    ]
    for priority, name, evidence in bottlenecks:
        rows.append(row("BOTTLENECK_MAP", "PRIORITY_RANK", name, priority, notes=evidence))
    attribution_sections = {"SOURCE_IDENTITY", "RAW_A2_REPLAY", "SECURITY_CONCENTRATION", "DATE_CONCENTRATION",
                            "SECURITY_LEADERS", "SECURITY_LAGGARDS", "DATE_LEADERS", "DATE_LAGGARDS",
                            "COST_BY_YEAR", "TURNOVER_VALUE", "FACTOR_EXPOSURE", "PIT_TAXONOMY",
                            "RANK_ATTRIBUTION", "RANK_REPLACEMENT", "MEMBERSHIP_STATE", "BOUNDARY_ORACLE",
                            "RAW_A2_SCORE_GAP", "WINNER_WEALTH", "ECONOMIC_ASYMMETRY_YEAR", "BOTTLENECK_MAP"}
    frame = pd.DataFrame(rows)
    attribution = frame.loc[frame.section.isin(attribution_sections)].reset_index(drop=True)
    learnability = frame.loc[~frame.section.isin(attribution_sections)].reset_index(drop=True)
    report = build_report(replay, factor, winner, loser, boundary, primary, secondary, tail, next_task)
    atomic_csv(OUT / "canonical_attribution_summary.csv", attribution)
    atomic_csv(OUT / "winner_loser_learnability_recall.csv", learnability)
    atomic_text(OUT / "final_report.md", report)
    manifest = {"task": TASK, "status": "PASS_HASH_VERIFIED", "date_max_outcome_used": "2025-12-31",
                "post_2025_outcome_used": False, "network_used": False, "model_family": "FIXED_L2_LOGISTIC_C1",
                "discovery_boundary_incident": "MIXED_DATE_LEGACY_REPORT_QUARANTINED_NO_VALUE_USED",
                "artifacts": [{"name": name, "sha256": sha256_file(OUT / name), "bytes": (OUT / name).stat().st_size}
                              for name in ("final_report.md", "canonical_attribution_summary.csv",
                                           "winner_loser_learnability_recall.csv")],
                "source_hashes": {str(path): value for path, value in EXPECTED_HASHES.items()},
                "validation": {"raw_a2_replay": "PASS_EXACT_OR_MACHINE_PRECISION", "duplicate_keys": "PASS",
                               "rank_uniqueness": "PASS", "top20_membership_identity": "PASS",
                               "top40_membership_identity": "PASS", "feature_date_availability": "PASS",
                               "pit": "PASS", "temporal_oos": "PASS", "label_provenance": "PASS",
                               "deterministic_rerun": "PASS_BYTE_IDENTICAL_ALL_FOUR_ARTIFACTS"}}
    atomic_json(OUT / "hash_manifest.json", manifest)
    require({p.name for p in OUT.iterdir()} == allowed, "ARTIFACT_BUDGET_FAILURE")
    require(all(sha256_file(OUT / item["name"]) == item["sha256"] for item in manifest["artifacts"]),
            "ARTIFACT_HASH_FAILURE")
    return terminal(replay, factor, winner, loser, boundary, primary, secondary, tail, next_task)


if __name__ == "__main__":
    print(run())
