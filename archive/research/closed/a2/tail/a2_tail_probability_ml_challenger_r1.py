from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Managed Windows workspaces can forbid the anonymous pipe used by joblib's
# physical-core probe. This is a runtime resource bound, not a model parameter.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from a2_raw_score_oos_tail_prediction_r1 import safe_binary_metrics
from a2_right_tail_event_antecedent_diagnostic_r1 import (
    atomic_csv,
    atomic_parquet,
    atomic_text,
    sha256_file,
)
from fast3.src.fast3.event_factor_law_discovery import make_model


TASK_NAME = "A2_TAIL_PROBABILITY_ML_CHALLENGER_R1"
ROOT = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_NAME
BASELINE_ROOT = RESULTS / "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1"
ANTECEDENT_ROOT = RESULTS / "A2_RIGHT_TAIL_EVENT_ANTECEDENT_DIAGNOSTIC_R1"
BRIDGE_ROOT = RESULTS / "A2_RAW_SCORE_OOS_PROBABILITY_TO_ECONOMICS_BRIDGE_R1"
A2_DAILY = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
MAX_OUTCOME_DATE = pd.Timestamp("2025-12-31")
PRE2025_END = pd.Timestamp("2024-12-31")
RANDOM_STATE = 314159
TOL = 1e-12

FEATURES = {
    "F1": ("raw_score", "raw_score_available_timestamp"),
    "F2": ("top10_score_gap", "top10_score_gap_available_timestamp"),
    "F3": ("rank_jump", "rank_jump_available_timestamp"),
    "F4": ("prior_top10_share", "prior_top10_share_available_timestamp"),
    "F5": ("holder_count", "holder_count_available_timestamp"),
    "F6": ("holder_count_change", "holder_count_change_available_timestamp"),
    "F7": ("momentum_20d", "momentum_20d_available_timestamp"),
    "F8": ("momentum_60d", "momentum_60d_available_timestamp"),
    "F10": ("risk_score", "risk_score_available_timestamp"),
}


class ChallengerFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise ChallengerFailure(f"{code}{suffix}")


def prior_value(frame: pd.DataFrame, section: str, metric: str, scope: str | None = None) -> str:
    rows = frame.loc[frame.section.eq(section) & frame.metric.eq(metric)]
    if scope is not None:
        rows = rows.loc[rows.scope.eq(scope)]
    require(len(rows) == 1, "PRIOR_SUMMARY_METRIC_IDENTITY", f"{section}:{metric}:{scope}:{len(rows)}")
    return str(rows.iloc[0].value)


def summary_row(section: str, metric: str, scope: str, value: Any, notes: str = "") -> dict[str, Any]:
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        value = "NA"
    return {"section": section, "metric": metric, "scope": scope, "value": value, "notes": notes}


def same_float(left: float, right: float, tolerance: float = TOL) -> bool:
    return bool(np.isclose(float(left), float(right), rtol=0.0, atol=tolerance, equal_nan=True))


def probability_metrics(frame: pd.DataFrame, probability_column: str) -> dict[str, float]:
    return safe_binary_metrics(frame.right_tail.to_numpy(int), frame[probability_column].to_numpy(float))


def group_metrics(frame: pd.DataFrame, flag_column: str) -> dict[str, float]:
    high = frame.loc[frame[flag_column].astype(bool)]
    low = frame.loc[~frame[flag_column].astype(bool)]
    base = float(frame.right_tail.mean()) if len(frame) else float("nan")
    high_rate = float(high.right_tail.mean()) if len(high) else float("nan")
    low_rate = float(low.right_tail.mean()) if len(low) else float("nan")

    def conditional(group: pd.DataFrame, tail: int) -> float:
        values = group.loc[group.right_tail.eq(tail), "event_active_return"]
        return float(values.mean()) if len(values) else float("nan")

    return {
        "high_count": int(len(high)),
        "low_count": int(len(low)),
        "base_rate": base,
        "high_rate": high_rate,
        "low_rate": low_rate,
        "lift": high_rate / base if base > 0 and np.isfinite(high_rate) else float("nan"),
        "high_mean": float(high.event_active_return.mean()) if len(high) else float("nan"),
        "low_mean": float(low.event_active_return.mean()) if len(low) else float("nan"),
        "mean_spread": float(high.event_active_return.mean() - low.event_active_return.mean()) if len(high) and len(low) else float("nan"),
        "high_tail_mean": conditional(high, 1),
        "low_tail_mean": conditional(low, 1),
        "high_nontail_mean": conditional(high, 0),
        "low_nontail_mean": conditional(low, 0),
    }


def fit_linear(train: pd.DataFrame, test: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray, float, dict[str, int]]:
    model = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=RANDOM_STATE)),
    ])
    model.fit(train[columns], train.right_tail)
    train_probability = model.predict_proba(train[columns])[:, 1]
    test_probability = model.predict_proba(test[columns])[:, 1]
    q80 = float(np.quantile(train_probability, .80, method="linear"))
    coefficients = model.named_steps["model"].coef_[0]
    signs = {column: int(np.sign(value)) for column, value in zip(columns, coefficients, strict=True)}
    return train_probability, test_probability, q80, signs


def fit_hgb(train: pd.DataFrame, test: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray, float]:
    # Direct reuse of the project's fixed hgb_leaf7 factory: 100 trees,
    # learning_rate=.08, max_leaf_nodes=7, L2=1, median imputation.
    model = make_model("hgb_leaf7", RANDOM_STATE)
    model.fit(train[columns], train.right_tail)
    train_probability = model.predict_proba(train[columns])[:, 1]
    test_probability = model.predict_proba(test[columns])[:, 1]
    q80 = float(np.quantile(train_probability, .80, method="linear"))
    return train_probability, test_probability, q80


def classify_challenger(metrics: dict[str, Any]) -> str:
    supported = (
        metrics["delta_auroc"] >= .015
        and metrics["delta_ap_over_base"] >= .10
        and metrics["delta_brier"] <= 0
        and metrics["auroc_fold_wins"] >= 3
        and metrics["pre2025_delta_auroc"] >= 0
        and metrics["group"]["lift"] > 1.0
        and metrics["group"]["mean_spread"] > 0
    )
    if supported:
        return "SUPPORTED"
    predictive_direction = metrics["delta_auroc"] > 0 or metrics["delta_ap_over_base"] > 0 or metrics["delta_brier"] < 0
    corroboration = metrics["auroc_fold_wins"] >= 3 or metrics["pre2025_delta_auroc"] >= 0 or metrics["group"]["lift"] > 1.0 or metrics["group"]["mean_spread"] > 0
    return "MIXED" if predictive_direction and corroboration else "NOT_SUPPORTED"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = {
        "baseline_predictions": BASELINE_ROOT / "oos_predictions.parquet",
        "baseline_summary": BASELINE_ROOT / "oos_summary.csv",
        "antecedent_features": ANTECEDENT_ROOT / "event_feature_detail.parquet",
        "bridge_summary": BRIDGE_ROOT / "economics_bridge.csv",
        "a2_daily": A2_DAILY,
    }
    for name, path in paths.items():
        require(path.is_file(), "REQUIRED_INPUT_MISSING", f"{name}:{path}")

    baseline = pd.read_parquet(paths["baseline_predictions"])
    baseline_summary = pd.read_csv(paths["baseline_summary"], dtype=str, keep_default_na=False)
    antecedent = pd.read_parquet(paths["antecedent_features"])
    daily = pd.read_parquet(paths["a2_daily"], columns=["execution_date", "pretrade_nav"])

    for frame in (baseline, antecedent):
        for column in ("decision_date", "holding_start", "holding_end"):
            frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    daily["execution_date"] = pd.to_datetime(daily.execution_date, errors="raise").dt.normalize()

    require(len(baseline) == 625, "BASELINE_OOS_ROW_COUNT_MISMATCH", len(baseline))
    require(baseline.decision_date.is_unique, "BASELINE_EVENT_DUPLICATE")
    require(antecedent.decision_date.is_unique, "ANTECEDENT_EVENT_DUPLICATE")
    require(set(baseline.outer_fold.unique()) == {f"OUTER_{index}" for index in range(1, 6)}, "BASELINE_FOLD_IDENTITY_MISMATCH")
    require(int(baseline.right_tail.sum()) == 67, "BASELINE_LABEL_COUNT_MISMATCH", int(baseline.right_tail.sum()))
    require(baseline.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_USED", baseline.holding_end.max())

    computed = probability_metrics(baseline, "predicted_right_tail_probability")
    expected = {
        "n": float(prior_value(baseline_summary, "POOLED_PROBABILITY", "N", "OUTER_TEST_ONLY")),
        "positive_count": float(prior_value(baseline_summary, "POOLED_PROBABILITY", "POSITIVE_COUNT", "OUTER_TEST_ONLY")),
        "auroc": float(prior_value(baseline_summary, "POOLED_PROBABILITY", "AUROC", "OUTER_TEST_ONLY")),
        "ap_over_base": float(prior_value(baseline_summary, "POOLED_PROBABILITY", "AP_OVER_BASE", "OUTER_TEST_ONLY")),
        "brier": float(prior_value(baseline_summary, "POOLED_PROBABILITY", "BRIER", "OUTER_TEST_ONLY")),
    }
    for metric, expected_value in expected.items():
        require(same_float(computed[metric], expected_value), "BASELINE_IDENTITY_MISMATCH", f"{metric}:{computed[metric]}:{expected_value}")
    prior_pre = float(prior_value(baseline_summary, "PRE2025_PROBABILITY", "AUROC", "OUTER_TEST_ONLY_PRE2025"))
    current_pre = probability_metrics(baseline.loc[baseline.holding_end <= PRE2025_END], "predicted_right_tail_probability")["auroc"]
    require(same_float(prior_pre, current_pre), "BASELINE_PRE2025_IDENTITY_MISMATCH")

    required_features = [item[0] for item in FEATURES.values()]
    required_timestamps = [item[1] for item in FEATURES.values()]
    require(set(required_features + required_timestamps).issubset(antecedent.columns), "ANTECEDENT_FEATURE_SCHEMA_MISMATCH")
    require("fundamental_change" not in required_features, "F9_FUNDAMENTAL_FIELD_FORBIDDEN")
    for feature, timestamp in FEATURES.values():
        valid = antecedent[feature].notna()
        require(antecedent.loc[valid, timestamp].notna().all(), "FEATURE_TIMESTAMP_MISSING", feature)
        feature_time = pd.to_datetime(antecedent.loc[valid, timestamp], errors="raise").dt.normalize()
        require((feature_time <= antecedent.loc[valid, "decision_date"]).all(), "FEATURE_TEMPORAL_LEAKAGE", feature)

    nav = daily.rename(columns={"execution_date": "holding_start"})
    antecedent = antecedent.merge(nav, on="holding_start", how="left", validate="many_to_one")
    require(antecedent.pretrade_nav.notna().all() and (antecedent.pretrade_nav > 0).all(), "PRE_EVENT_NAV_IDENTITY_FAILURE")
    antecedent["event_active_return"] = antecedent.event_incremental_wealth.astype(float) / antecedent.pretrade_nav.astype(float)

    joined_test = baseline[["decision_date", "event_active_return"]].merge(
        antecedent[["decision_date", "event_active_return"]], on="decision_date", suffixes=("_prior", "_rebuilt"), validate="one_to_one"
    )
    require(len(joined_test) == len(baseline), "BASELINE_ANTECEDENT_EVENT_IDENTITY_MISMATCH")
    require(np.allclose(joined_test.event_active_return_prior, joined_test.event_active_return_rebuilt, rtol=0, atol=TOL), "EVENT_ACTIVE_RETURN_IDENTITY_MISMATCH")
    return baseline.sort_values("decision_date").reset_index(drop=True), baseline_summary, antecedent.sort_values("decision_date").reset_index(drop=True), daily


def run() -> dict[str, Any]:
    baseline, baseline_summary, antecedent, _ = load_inputs()
    feature_columns = [item[0] for item in FEATURES.values()]
    output_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []

    for fold, test_prior in baseline.groupby("outer_fold", sort=True):
        test_prior = test_prior.sort_values("decision_date").reset_index(drop=True)
        metadata = test_prior.iloc[0]
        constant_metadata = [
            "train_count_after_purge", "train_max_decision_date", "train_max_holding_end",
            "test_min_decision_date", "test_min_holding_start", "train_q90",
        ]
        require(all(test_prior[column].nunique(dropna=False) == 1 for column in constant_metadata), "FOLD_METADATA_NOT_CONSTANT", fold)

        train = antecedent.loc[antecedent.decision_date <= pd.Timestamp(metadata.train_max_decision_date)].copy()
        require(len(train) == int(metadata.train_count_after_purge), "PURGED_TRAIN_COUNT_MISMATCH", fold)
        require(train.holding_end.max() == pd.Timestamp(metadata.train_max_holding_end), "PURGED_TRAIN_END_MISMATCH", fold)
        require(train.holding_end.max() < pd.Timestamp(metadata.test_min_holding_start), "OUTCOME_OVERLAP_PURGE_FAILURE", fold)
        train["right_tail"] = train.event_active_return > float(metadata.train_q90)

        test = test_prior.merge(
            antecedent[["decision_date", *feature_columns]], on="decision_date", how="left",
            validate="one_to_one", suffixes=("_baseline", "_antecedent"),
        )
        require(len(test) == len(test_prior), "TEST_EVENT_JOIN_MISMATCH", fold)
        require(np.array_equal(test.right_tail.to_numpy(int), test_prior.right_tail.to_numpy(int)), "FOLD_TARGET_LABEL_MISMATCH", fold)
        require(
            np.allclose(test.raw_score_baseline, test.raw_score_antecedent, rtol=0, atol=TOL),
            "RAW_SCORE_PROVENANCE_MISMATCH", fold,
        )
        test["raw_score"] = test.raw_score_baseline
        active_columns = [column for column in feature_columns if train[column].notna().any()]
        dropped_columns = sorted(set(feature_columns).difference(active_columns))

        _, c1_test_probability, c1_q80, coefficient_signs = fit_linear(train, test, active_columns)
        _, c2_test_probability, c2_q80 = fit_hgb(train, test, active_columns)
        test["b0_probability"] = test.predicted_right_tail_probability.astype(float)
        test["c1_probability"] = c1_test_probability
        test["c2_probability"] = c2_test_probability
        test["b0_high_probability"] = test.high_score.astype(bool)
        test["c1_high_probability"] = test.c1_probability > c1_q80
        test["c2_high_probability"] = test.c2_probability > c2_q80

        for feature, sign in coefficient_signs.items():
            coefficient_rows.append({"outer_fold": fold, "feature": feature, "standardized_coefficient_sign": sign})

        fold_record: dict[str, Any] = {
            "outer_fold": fold,
            "test_count": len(test),
            "right_tail_count": int(test.right_tail.sum()),
            "active_features": ";".join(active_columns),
            "dropped_completely_missing_features": ";".join(dropped_columns),
            "c1_train_probability_q80": c1_q80,
            "c2_train_probability_q80": c2_q80,
        }
        for model in ("b0", "c1", "c2"):
            metrics = probability_metrics(test, f"{model}_probability")
            groups = group_metrics(test, f"{model}_high_probability")
            fold_record.update({f"{model}_{key}": value for key, value in metrics.items()})
            fold_record.update({f"{model}_group_{key}": value for key, value in groups.items()})
        for model in ("c1", "c2"):
            fold_record[f"{model}_delta_auroc"] = fold_record[f"{model}_auroc"] - fold_record["b0_auroc"]
            fold_record[f"{model}_delta_ap_over_base"] = fold_record[f"{model}_ap_over_base"] - fold_record["b0_ap_over_base"]
            fold_record[f"{model}_delta_brier"] = fold_record[f"{model}_brier"] - fold_record["b0_brier"]
        fold_rows.append(fold_record)
        output_parts.append(test)

    predictions = pd.concat(output_parts, ignore_index=True).sort_values(["outer_fold", "decision_date"], kind="mergesort").reset_index(drop=True)
    require(len(predictions) == len(baseline), "POOLED_TEST_ROW_COUNT_MISMATCH")
    require(predictions.decision_date.is_unique, "POOLED_TEST_EVENT_DUPLICATE")
    require(np.array_equal(predictions.right_tail.to_numpy(int), baseline.sort_values(["outer_fold", "decision_date"]).right_tail.to_numpy(int)), "POOLED_LABEL_IDENTITY_MISMATCH")
    folds = pd.DataFrame(fold_rows).sort_values("outer_fold").reset_index(drop=True)

    model_results: dict[str, dict[str, Any]] = {}
    pre2025 = predictions.loc[predictions.holding_end <= PRE2025_END].copy()
    for model in ("b0", "c1", "c2"):
        pooled_metrics = probability_metrics(predictions, f"{model}_probability")
        pooled_group = group_metrics(predictions, f"{model}_high_probability")
        pre_metrics = probability_metrics(pre2025, f"{model}_probability")
        pre_group = group_metrics(pre2025, f"{model}_high_probability")
        result: dict[str, Any] = {
            "status": "AUTHORITATIVE_REUSED" if model == "b0" else "EXECUTED_FIXED_SPEC",
            "metrics": pooled_metrics,
            "group": pooled_group,
            "pre2025_metrics": pre_metrics,
            "pre2025_group": pre_group,
        }
        if model != "b0":
            result.update({
                "delta_auroc": pooled_metrics["auroc"] - model_results["b0"]["metrics"]["auroc"],
                "delta_ap_over_base": pooled_metrics["ap_over_base"] - model_results["b0"]["metrics"]["ap_over_base"],
                "delta_brier": pooled_metrics["brier"] - model_results["b0"]["metrics"]["brier"],
                "pre2025_delta_auroc": pre_metrics["auroc"] - model_results["b0"]["pre2025_metrics"]["auroc"],
                "pre2025_delta_ap_over_base": pre_metrics["ap_over_base"] - model_results["b0"]["pre2025_metrics"]["ap_over_base"],
                "pre2025_delta_brier": pre_metrics["brier"] - model_results["b0"]["pre2025_metrics"]["brier"],
                "auroc_fold_wins": int((folds[f"{model}_auroc"] > folds.b0_auroc).sum()),
                "ap_fold_wins": int((folds[f"{model}_ap"] > folds.b0_ap).sum()),
                "brier_fold_wins": int((folds[f"{model}_brier"] < folds.b0_brier).sum()),
            })
            result["classification"] = classify_challenger(result)
        model_results[model] = result

    c1_class = model_results["c1"]["classification"]
    c2_class = model_results["c2"]["classification"]
    if c2_class == "SUPPORTED" and (
        model_results["c2"]["metrics"]["auroc"] - model_results["c1"]["metrics"]["auroc"] >= .015
        and model_results["c2"]["metrics"]["ap_over_base"] - model_results["c1"]["metrics"]["ap_over_base"] >= .10
    ):
        decision = "PROMISING_NONLINEAR_CHALLENGER"
        signal_candidate = "NONLINEAR_CHALLENGER_RESEARCH_ONLY"
    elif c1_class == "SUPPORTED" or c2_class == "SUPPORTED":
        decision = "PROMISING_LINEAR_CHALLENGER" if c1_class == "SUPPORTED" else "PROMISING_NONLINEAR_CHALLENGER"
        signal_candidate = "LINEAR_CHALLENGER_RESEARCH_ONLY" if c1_class == "SUPPORTED" else "NONLINEAR_CHALLENGER_RESEARCH_ONLY"
    elif "MIXED" in (c1_class, c2_class):
        decision = "MULTIVARIATE_INCREMENT_MIXED"
        signal_candidate = "UNRESOLVED"
    else:
        decision = "KEEP_RAW_SCORE_BASELINE"
        signal_candidate = "RAW_SCORE_ONLY"

    baseline_prior_auroc = float(prior_value(baseline_summary, "POOLED_PROBABILITY", "AUROC", "OUTER_TEST_ONLY"))
    require(same_float(model_results["b0"]["metrics"]["auroc"], baseline_prior_auroc), "BASELINE_FINAL_IDENTITY_FAILURE")

    summary: list[dict[str, Any]] = []
    source_paths = [
        BASELINE_ROOT / "oos_predictions.parquet", BASELINE_ROOT / "oos_summary.csv",
        ANTECEDENT_ROOT / "event_feature_detail.parquet", BRIDGE_ROOT / "economics_bridge.csv", A2_DAILY,
    ]
    for path in source_paths:
        summary.append(summary_row("INPUT_IDENTITY", "SHA256", str(path), sha256_file(path)))
    summary.extend([
        summary_row("VALIDATION", "BASELINE_IDENTITY_STATUS", "ALL", "PASS"),
        summary_row("VALIDATION", "POST_2025_OUTCOME_USED", "ALL", False),
        summary_row("VALIDATION", "NETWORK_USED", "ALL", False),
        summary_row("VALIDATION", "OUTER_TEST_ROWS_ONLY", "ALL", True),
        summary_row("VALIDATION", "FOLD_LABELS_REUSED", "ALL", True),
        summary_row("VALIDATION", "PURGE_BOUNDARIES_REUSED", "ALL", True),
        summary_row("VALIDATION", "TRAIN_ONLY_PREPROCESSING", "ALL", True),
        summary_row("VALIDATION", "F9_PRESENT", "ALL", False),
        summary_row("VALIDATION", "PREDICTOR_COUNT", "ALL", len(FEATURES)),
        summary_row("POOLED", "EVENT_COUNT", "OUTER_TEST_ONLY", len(predictions)),
        summary_row("POOLED", "RIGHT_TAIL_COUNT", "OUTER_TEST_ONLY", int(predictions.right_tail.sum())),
    ])
    for _, row in folds.iterrows():
        fold = row.outer_fold
        for metric, value in row.items():
            if metric != "outer_fold":
                summary.append(summary_row("OUTER_FOLD", str(metric).upper(), fold, value))
    for model, result in model_results.items():
        scope = model.upper()
        summary.append(summary_row("MODEL", "STATUS", scope, result["status"]))
        for metric, value in result["metrics"].items():
            summary.append(summary_row("POOLED_METRIC", metric.upper(), scope, value))
        for metric, value in result["group"].items():
            summary.append(summary_row("POOLED_HIGH_PROB", metric.upper(), scope, value))
        for metric, value in result["pre2025_metrics"].items():
            summary.append(summary_row("PRE2025_METRIC", metric.upper(), scope, value))
        for metric, value in result["pre2025_group"].items():
            summary.append(summary_row("PRE2025_HIGH_PROB", metric.upper(), scope, value))
        if model != "b0":
            for metric in (
                "delta_auroc", "delta_ap_over_base", "delta_brier", "pre2025_delta_auroc",
                "pre2025_delta_ap_over_base", "pre2025_delta_brier", "auroc_fold_wins", "ap_fold_wins", "brier_fold_wins",
            ):
                summary.append(summary_row("INCREMENTAL", metric.upper(), scope, result[metric]))
            summary.append(summary_row("CLASSIFICATION", "INCREMENTAL_PREDICTIVE_VALUE", scope, result["classification"]))
    for record in coefficient_rows:
        summary.append(summary_row("C1_COEFFICIENT_SIGN", record["feature"].upper(), record["outer_fold"], record["standardized_coefficient_sign"]))
    summary.extend([
        summary_row("CLASSIFICATION", "TAIL_PROBABILITY_MODEL_DECISION", "ALL", decision),
        summary_row("CLASSIFICATION", "POSITION_SIZING_SIGNAL_CANDIDATE", "ALL", signal_candidate),
    ])

    output_columns = [
        "decision_date", "outer_fold", "right_tail", "event_active_return",
        "b0_probability", "c1_probability", "c2_probability",
        "b0_high_probability", "c1_high_probability", "c2_high_probability",
    ]
    output = predictions[output_columns].copy()
    output.insert(0, "event_id", output.decision_date.dt.strftime("%Y-%m-%d"))
    require(output.event_id.is_unique, "OUTPUT_EVENT_ID_DUPLICATE")

    m = model_results
    report = f"""# A2 Tail Probability ML Challenger R1

## Result

The authoritative Raw-score-only baseline was reproduced exactly on the frozen 625 strict chronological OOS events. The challengers reused the same five outer-test folds, persisted purge boundaries, and fold-local right-tail labels. No baseline refit, fold reconstruction, label reconstruction, strategy replay, position sizing, network access, or post-2025 outcome access occurred.

The fixed linear challenger is **{c1_class}** and the fixed HGB challenger is **{c2_class}**. The resulting model decision is **{decision}**; the position-sizing signal candidate is **{signal_candidate}** (research designation only, not authorization to size positions).

## Pooled strict-OOS comparison

| Model | AUROC | AP/base | Brier | Delta AUROC | Delta AP/base | Delta Brier | AUROC fold wins | High-prob lift | High-minus-lower active return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 Raw score | {m['b0']['metrics']['auroc']:.6f} | {m['b0']['metrics']['ap_over_base']:.6f} | {m['b0']['metrics']['brier']:.6f} | 0 | 0 | 0 | — | {m['b0']['group']['lift']:.6f} | {m['b0']['group']['mean_spread']:.8f} |
| C1 fixed L2 Logistic | {m['c1']['metrics']['auroc']:.6f} | {m['c1']['metrics']['ap_over_base']:.6f} | {m['c1']['metrics']['brier']:.6f} | {m['c1']['delta_auroc']:+.6f} | {m['c1']['delta_ap_over_base']:+.6f} | {m['c1']['delta_brier']:+.6f} | {m['c1']['auroc_fold_wins']}/5 | {m['c1']['group']['lift']:.6f} | {m['c1']['group']['mean_spread']:.8f} |
| C2 fixed HGB leaf7 | {m['c2']['metrics']['auroc']:.6f} | {m['c2']['metrics']['ap_over_base']:.6f} | {m['c2']['metrics']['brier']:.6f} | {m['c2']['delta_auroc']:+.6f} | {m['c2']['delta_ap_over_base']:+.6f} | {m['c2']['delta_brier']:+.6f} | {m['c2']['auroc_fold_wins']}/5 | {m['c2']['group']['lift']:.6f} | {m['c2']['group']['mean_spread']:.8f} |

## Interpretation

- C1 materially beats Raw-score-only only if all seven frozen gates pass; its result is `{c1_class}`.
- C2 uses the repository's existing fixed `hgb_leaf7` factory without tuning; its result is `{c2_class}`.
- Chronological breadth is shown by AUROC fold wins and the full per-fold ledger in `ml_challenger_summary.csv`.
- Pre-2025 AUROC deltas are C1 {m['c1']['pre2025_delta_auroc']:+.6f} and C2 {m['c2']['pre2025_delta_auroc']:+.6f}; no special pre-2025 refit was performed.
- Positive event economics are required but do not constitute a portfolio backtest. Pooled high-minus-lower active-return spreads are C1 {m['c1']['group']['mean_spread']:+.8f} and C2 {m['c2']['group']['mean_spread']:+.8f}.
- Complexity is justified only by a fully supported challenger. The frozen decision is `{decision}`.

## Research boundaries and provenance

- Outcome maximum: 2025-12-31; post-2025 outcome used: false.
- Predictors: exactly F1–F8 and F10 from the antecedent artifact; F9 is absent.
- All nonmissing feature timestamps were revalidated as no later than decision timestamps.
- C1 imputation/scaling and both models' Q80 thresholds were fit on training rows only.
- F10 was completely missing in OUTER_1 training and was dropped only for that fold, exactly as specified.
- C2 configuration source: existing `fast3.src.fast3.event_factor_law_discovery.make_model('hgb_leaf7', 314159)`.
- These are descriptive strict-OOS event predictions, not a strategy, promotion, or position-sizing result.
"""

    OUT.mkdir(parents=True, exist_ok=True)
    atomic_csv(OUT / "ml_challenger_summary.csv", pd.DataFrame(summary))
    atomic_parquet(OUT / "oos_challenger_predictions.parquet", output)
    atomic_text(OUT / "final_report.md", report)
    require(len([path for path in OUT.iterdir() if path.is_file()]) == 3, "RESULT_ARTIFACT_COUNT_MISMATCH")
    require(not list(OUT.glob(".*.tmp")) and not list(OUT.glob(".*.parquet")), "TEMP_FILE_REMAINS")

    final = {
        "RESEARCH_RESULT_STATUS": "COMPLETED_VALID_RESEARCH",
        "EXECUTION_STATUS": "PASS",
        "REPOSITORY_POLICY_STATUS": "PASS_WITH_SCOPED_HARD_BLOCKERS_NOT_APPLICABLE",
        "DATE_MAX_OUTCOME_USED": "2025-12-31",
        "POST_2025_OUTCOME_USED": "false",
        "NETWORK_USED": "false",
        "BASELINE_IDENTITY_STATUS": "PASS",
        "POOLED_OOS_EVENT_COUNT": len(predictions),
        "POOLED_OOS_RIGHT_TAIL_COUNT": int(predictions.right_tail.sum()),
        "B0_AUROC": m["b0"]["metrics"]["auroc"],
        "B0_AP_OVER_BASE": m["b0"]["metrics"]["ap_over_base"],
        "B0_BRIER": m["b0"]["metrics"]["brier"],
        "C1_STATUS": m["c1"]["status"],
        "C1_AUROC": m["c1"]["metrics"]["auroc"],
        "C1_AP_OVER_BASE": m["c1"]["metrics"]["ap_over_base"],
        "C1_BRIER": m["c1"]["metrics"]["brier"],
        "C1_DELTA_AUROC": m["c1"]["delta_auroc"],
        "C1_DELTA_AP_OVER_BASE": m["c1"]["delta_ap_over_base"],
        "C1_DELTA_BRIER": m["c1"]["delta_brier"],
        "C1_AUROC_FOLD_WIN_COUNT": m["c1"]["auroc_fold_wins"],
        "C1_HIGH_PROB_WINNER_LIFT": m["c1"]["group"]["lift"],
        "C1_HIGH_MINUS_LOWER_MEAN_EVENT_ACTIVE_RETURN": m["c1"]["group"]["mean_spread"],
        "C1_PRE2025_DELTA_AUROC": m["c1"]["pre2025_delta_auroc"],
        "C1_INCREMENTAL_PREDICTIVE_VALUE": c1_class,
        "C2_STATUS": m["c2"]["status"],
        "C2_AUROC": m["c2"]["metrics"]["auroc"],
        "C2_AP_OVER_BASE": m["c2"]["metrics"]["ap_over_base"],
        "C2_BRIER": m["c2"]["metrics"]["brier"],
        "C2_DELTA_AUROC": m["c2"]["delta_auroc"],
        "C2_DELTA_AP_OVER_BASE": m["c2"]["delta_ap_over_base"],
        "C2_DELTA_BRIER": m["c2"]["delta_brier"],
        "C2_AUROC_FOLD_WIN_COUNT": m["c2"]["auroc_fold_wins"],
        "C2_HIGH_PROB_WINNER_LIFT": m["c2"]["group"]["lift"],
        "C2_HIGH_MINUS_LOWER_MEAN_EVENT_ACTIVE_RETURN": m["c2"]["group"]["mean_spread"],
        "C2_PRE2025_DELTA_AUROC": m["c2"]["pre2025_delta_auroc"],
        "C2_INCREMENTAL_PREDICTIVE_VALUE": c2_class,
        "TAIL_PROBABILITY_MODEL_DECISION": decision,
        "POSITION_SIZING_SIGNAL_CANDIDATE": signal_candidate,
        "SOURCE_MODIFICATION_COUNT": 1,
        "RESULT_ARTIFACT_COUNT": 3,
        "TEMP_FILE_REMAINS": 0,
        "NEXT_RESEARCH_QUESTION": "STOP_NO_AUTOMATIC_FOLLOW_UP",
    }
    return final


def print_final(final: dict[str, Any]) -> None:
    print("=" * 60)
    print("A2_TAIL_PROBABILITY_ML_CHALLENGER_R1_FINAL")
    print("=" * 60)
    for key, value in final.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    print_final(run())
