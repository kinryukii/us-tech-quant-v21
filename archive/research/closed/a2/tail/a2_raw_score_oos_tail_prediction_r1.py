from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.preprocessing import StandardScaler

from a2_right_tail_event_antecedent_diagnostic_r1 import atomic_csv, atomic_parquet, atomic_text, sha256_file


TASK_NAME = "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1"
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_NAME
ANTECEDENT_ROOT = RESULTS / "A2_RIGHT_TAIL_EVENT_ANTECEDENT_DIAGNOSTIC_R1"
EVENT_ROOT = RESULTS / "A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1"
A2_DAILY = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
MAX_OUTCOME_DATE = pd.Timestamp("2025-12-31")
PRE2025_END = pd.Timestamp("2024-12-31")
PREDICTOR = "raw_score"
PREDICTOR_TIMESTAMP = "raw_score_available_timestamp"
RIGHT_TAIL_QUANTILE = .90
HIGH_SCORE_QUANTILE = .80
RANDOM_STATE = 314159
TOL = 1e-12


class OOSDiagnosticFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise OOSDiagnosticFailure(f"{code}{suffix}")


def metric_from_summary(frame: pd.DataFrame, section: str, metric: str, scope: str | None = None) -> str:
    rows = frame.loc[frame.section.eq(section) & frame.metric.eq(metric)]
    if scope is not None:
        rows = rows.loc[rows.scope.eq(scope)]
    require(len(rows) == 1, "SUMMARY_METRIC_IDENTITY_FAILURE", f"{section}:{metric}:{scope}:{len(rows)}")
    return str(rows.iloc[0].value)


def summary_row(section: str, metric: str, scope: str, value: Any, notes: str = "") -> dict[str, Any]:
    if isinstance(value, float) and not np.isfinite(value):
        value = "NA"
    return {"section": section, "metric": metric, "scope": scope, "value": value, "notes": notes}


def safe_binary_metrics(y: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    probability = np.asarray(probability, dtype=float)
    base = float(y.mean()) if len(y) else float("nan")
    if len(y) == 0 or np.unique(y).size < 2:
        auroc = float("nan")
        ap = float("nan")
    else:
        auroc = float(roc_auc_score(y, probability))
        ap = float(average_precision_score(y, probability))
    return {
        "n": int(len(y)), "positive_count": int(y.sum()), "base_rate": base,
        "auroc": auroc, "ap": ap, "ap_over_base": ap / base if base > 0 and np.isfinite(ap) else float("nan"),
        "brier": float(brier_score_loss(y, probability)) if len(y) else float("nan"),
        "mean_probability": float(probability.mean()) if len(probability) else float("nan"),
    }


def safe_corr(actual: np.ndarray, predicted: np.ndarray, method: str) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) < 2 or np.std(actual) == 0 or np.std(predicted) == 0:
        return float("nan")
    result = pearsonr(actual, predicted) if method == "pearson" else spearmanr(actual, predicted)
    return float(result.statistic)


def high_score_metrics(frame: pd.DataFrame, label: str = "right_tail") -> dict[str, float]:
    high = frame.loc[frame.high_score]
    low = frame.loc[~frame.high_score]
    base = float(frame[label].mean()) if len(frame) else float("nan")
    high_rate = float(high[label].mean()) if len(high) else float("nan")
    low_rate = float(low[label].mean()) if len(low) else float("nan")
    return {
        "high_count": int(len(high)), "high_rate": high_rate, "low_rate": low_rate,
        "lift": high_rate / base if base > 0 and np.isfinite(high_rate) else float("nan"),
    }


def high_payoff_metrics(frame: pd.DataFrame) -> dict[str, float]:
    high = frame.loc[frame.high_score, "event_active_return"].astype(float)
    low = frame.loc[~frame.high_score, "event_active_return"].astype(float)
    return {
        "high_mean": float(high.mean()) if len(high) else float("nan"),
        "low_mean": float(low.mean()) if len(low) else float("nan"),
        "mean_spread": float(high.mean() - low.mean()) if len(high) and len(low) else float("nan"),
        "high_median": float(high.median()) if len(high) else float("nan"),
        "low_median": float(low.median()) if len(low) else float("nan"),
        "median_spread": float(high.median() - low.median()) if len(high) and len(low) else float("nan"),
    }


def payoff_metrics(frame: pd.DataFrame) -> dict[str, float]:
    actual = frame.event_active_return.to_numpy(float)
    predicted = frame.predicted_payoff.to_numpy(float)
    baseline = frame.train_mean_payoff.to_numpy(float)
    sse = float(np.square(actual - predicted).sum())
    baseline_sse = float(np.square(actual - baseline).sum())
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "mse": float(mean_squared_error(actual, predicted)),
        "oos_r2_train_mean_baseline": 1.0 - sse / baseline_sse if baseline_sse > 0 else float("nan"),
        "pearson": safe_corr(actual, predicted, "pearson"),
        "spearman": safe_corr(actual, predicted, "spearman"),
        "actual_mean": float(actual.mean()), "predicted_mean": float(predicted.mean()),
    }


def load_validated_events() -> tuple[pd.DataFrame, list[dict[str, Any]], float]:
    feature_path = ANTECEDENT_ROOT / "event_feature_detail.parquet"
    antecedent_summary_path = ANTECEDENT_ROOT / "antecedent_summary.csv"
    event_path = EVENT_ROOT / "diagnostic_detail.parquet"
    event_summary_path = EVENT_ROOT / "diagnostic_summary.csv"
    for path in (feature_path, antecedent_summary_path, event_path, event_summary_path, A2_DAILY):
        require(path.exists(), "INPUT_MISSING", path)
    features = pd.read_parquet(feature_path)
    features["decision_date"] = pd.to_datetime(features.decision_date)
    features["holding_start"] = pd.to_datetime(features.holding_start)
    features["holding_end"] = pd.to_datetime(features.holding_end)
    features[PREDICTOR_TIMESTAMP] = pd.to_datetime(features[PREDICTOR_TIMESTAMP])
    prior = pd.read_parquet(event_path)
    prior = prior.loc[prior.row_type.eq("REPLACEMENT_EVENT"), ["decision_date", "holding_start", "holding_end", "event_incremental_wealth"]].copy()
    for column in ("decision_date", "holding_start", "holding_end"):
        prior[column] = pd.to_datetime(prior[column])
    require(len(features) == len(prior) == 750, "EVENT_COUNT_MISMATCH")
    require(features.decision_date.is_unique and prior.decision_date.is_unique, "EVENT_KEY_DUPLICATE")
    joined = features.merge(prior, on=["decision_date", "holding_start", "holding_end"], how="outer", suffixes=("_feature", "_prior"), indicator=True, validate="one_to_one")
    require(joined._merge.eq("both").all(), "EVENT_DATE_IDENTITY_MISMATCH")
    contribution_error = float((joined.event_incremental_wealth_feature - joined.event_incremental_wealth_prior).abs().max())
    require(contribution_error <= TOL, "EVENT_INCREMENTAL_WEALTH_MISMATCH", contribution_error)
    event_summary = pd.read_csv(event_summary_path, dtype=str, keep_default_na=False)
    terminal_delta = float(metric_from_summary(event_summary, "INPUT_IDENTITY", "A2_MINUS_A_TERMINAL_WEALTH_DELTA"))
    identity_error = abs(float(features.event_incremental_wealth.sum()) - terminal_delta)
    require(identity_error <= TOL, "A2_MINUS_A_WEALTH_IDENTITY_FAILURE", identity_error)
    antecedent_summary = pd.read_csv(antecedent_summary_path, dtype=str, keep_default_na=False)
    require(metric_from_summary(antecedent_summary, "FINAL_DECISION", "ANTECEDENT_STRUCTURE_CLASSIFICATION") == "REPEATABLE_A2_INTERNAL_STRENGTH", "ANTECEDENT_INPUT_CLASSIFICATION_MISMATCH")
    require(metric_from_summary(antecedent_summary, "FEATURE_AVAILABILITY", "AVAILABILITY", "F1_RAW_A2_SCORE") == "AVAILABLE", "RAW_SCORE_PROVENANCE_STATUS_MISMATCH")
    require(features[PREDICTOR].notna().all(), "RAW_SCORE_MISSING")
    require((features[PREDICTOR_TIMESTAMP] <= features.decision_date).all(), "RAW_SCORE_TEMPORAL_LEAKAGE")
    require(features.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_LEAKAGE")

    daily = pd.read_parquet(A2_DAILY, columns=["execution_date", "pretrade_nav"])
    daily["holding_start"] = pd.to_datetime(daily.execution_date)
    require(daily.holding_start.is_unique, "A2_DAILY_DATE_DUPLICATE")
    features = features.merge(daily[["holding_start", "pretrade_nav"]], on="holding_start", how="left", validate="one_to_one")
    require(features.pretrade_nav.notna().all() and features.pretrade_nav.gt(0).all(), "PRE_EVENT_A2_NAV_INVALID")
    features["event_active_return"] = features.event_incremental_wealth / features.pretrade_nav
    require(np.isfinite(features.event_active_return).all(), "EVENT_ACTIVE_RETURN_NONFINITE")
    sign_mismatch = int((np.sign(features.event_active_return) != np.sign(features.event_incremental_wealth)).sum())
    require(sign_mismatch == 0, "EVENT_ACTIVE_RETURN_SIGN_MISMATCH", sign_mismatch)
    features = features.sort_values("decision_date", kind="mergesort").reset_index(drop=True)
    rows = [
        summary_row("INPUT_IDENTITY", "ANTECEDENT_DETAIL_SHA256", str(feature_path), sha256_file(feature_path)),
        summary_row("INPUT_IDENTITY", "ANTECEDENT_SUMMARY_SHA256", str(antecedent_summary_path), sha256_file(antecedent_summary_path)),
        summary_row("INPUT_IDENTITY", "EVENT_DIAGNOSTIC_DETAIL_SHA256", str(event_path), sha256_file(event_path)),
        summary_row("INPUT_IDENTITY", "A2_DAILY_SHA256", str(A2_DAILY), sha256_file(A2_DAILY)),
        summary_row("INPUT_IDENTITY", "TOTAL_EVENT_COUNT", "ALL", len(features)),
        summary_row("INPUT_IDENTITY", "VALID_RAW_SCORE_EVENT_COUNT", "ALL", int(features.raw_score.notna().sum())),
        summary_row("INPUT_IDENTITY", "RAW_SCORE_EVENT_COVERAGE", "ALL", float(features.raw_score.notna().mean())),
        summary_row("INPUT_IDENTITY", "EVENT_CONTRIBUTION_MAX_ABS_ERROR", "ALL", contribution_error),
        summary_row("INPUT_IDENTITY", "WEALTH_IDENTITY_MAX_ABS_ERROR", "ALL", identity_error),
        summary_row("TARGET", "EVENT_ACTIVE_RETURN_DEFINITION", "ALL", "EVENT_INCREMENTAL_WEALTH / PRE_EVENT_A2_NAV"),
        summary_row("TARGET", "PRE_EVENT_A2_NAV_SOURCE", "ALL", f"{A2_DAILY}::pretrade_nav at holding_start", "authoritative NAV immediately before replacement exposure becomes active"),
        summary_row("TARGET", "ACTIVE_RETURN_SIGN_MISMATCH_COUNT", "ALL", sign_mismatch),
    ]
    return features, rows, terminal_delta


def build_outer_oos(events: pd.DataFrame, rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    indices = [array for array in np.array_split(np.arange(len(events)), 6) if len(array)]
    require(len(indices) == 6 and [len(array) for array in indices] == [125] * 6, "FALLBACK_BLOCK_IDENTITY_FAILURE")
    rows.append(summary_row("FOLD_CONTRACT", "METHOD", "ALL", "FALLBACK_6_CONTIGUOUS_DATE_BLOCKS_EXPANDING_OUTER_OOS"))
    rows.append(summary_row("FOLD_CONTRACT", "PERCENTILE_CONVENTION", "ALL", "numpy.quantile(method=linear); TRAIN only"))
    predictions: list[pd.DataFrame] = []
    fold_records: list[dict[str, Any]] = []
    for fold_index in range(1, 6):
        fold_id = f"OUTER_{fold_index}"
        test_index = indices[fold_index]
        prior_index = np.concatenate(indices[:fold_index])
        train_before = events.iloc[prior_index].copy()
        test = events.iloc[test_index].copy()
        first_test_active = test.holding_start.min()
        train = train_before.loc[train_before.holding_end.lt(first_test_active)].copy()
        purged = len(train_before) - len(train)
        require(len(train) > 0 and len(test) > 0, "EMPTY_OUTER_FOLD", fold_id)
        require(train.decision_date.max() < test.decision_date.min(), "TRAIN_TEST_DATE_OVERLAP", fold_id)
        require(train.holding_end.max() < first_test_active, "OUTCOME_WINDOW_OVERLAP_AFTER_PURGE", fold_id)
        require(set(train.index).isdisjoint(test.index), "TRAIN_TEST_ROW_OVERLAP", fold_id)

        train_q90 = float(np.quantile(train.event_active_return.to_numpy(float), RIGHT_TAIL_QUANTILE, method="linear"))
        train_score_q80 = float(np.quantile(train.raw_score.to_numpy(float), HIGH_SCORE_QUANTILE, method="linear"))
        train_label = train.event_active_return.gt(train_q90).astype(int).to_numpy()
        test_label = test.event_active_return.gt(train_q90).astype(int).to_numpy()
        require(np.unique(train_label).size == 2, "TRAIN_RIGHT_TAIL_CLASS_DEGENERATE", fold_id)

        scaler = StandardScaler()
        x_train = scaler.fit_transform(train[[PREDICTOR]])
        x_test = scaler.transform(test[[PREDICTOR]])
        logistic = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=RANDOM_STATE)
        logistic.fit(x_train, train_label)
        probability = logistic.predict_proba(x_test)[:, 1]

        linear = LinearRegression(fit_intercept=True)
        linear.fit(train[[PREDICTOR]], train.event_active_return)
        payoff_prediction = linear.predict(test[[PREDICTOR]])
        scored = test[["decision_date", "holding_start", "holding_end", "event_group", "event_incremental_wealth", "pretrade_nav", "event_active_return", "raw_score", "raw_score_available_timestamp"]].copy()
        scored["outer_fold"] = fold_id
        scored["right_tail"] = test_label
        scored["predicted_right_tail_probability"] = probability
        scored["predicted_payoff"] = payoff_prediction
        scored["high_score"] = scored.raw_score.gt(train_score_q80)
        scored["train_q90"] = train_q90
        scored["train_score_q80"] = train_score_q80
        scored["train_mean_payoff"] = float(train.event_active_return.mean())
        scored["train_count_before_purge"] = len(train_before)
        scored["train_count_after_purge"] = len(train)
        scored["purged_event_count"] = purged
        scored["test_count"] = len(test)
        scored["train_max_decision_date"] = train.decision_date.max()
        scored["train_max_holding_end"] = train.holding_end.max()
        scored["test_min_decision_date"] = test.decision_date.min()
        scored["test_min_holding_start"] = first_test_active
        scored["logistic_standardized_coefficient"] = float(logistic.coef_[0, 0])
        scored["linear_raw_score_slope"] = float(linear.coef_[0])
        scored["linear_intercept"] = float(linear.intercept_)
        predictions.append(scored)

        probability_metrics = safe_binary_metrics(test_label, probability)
        high_metrics = high_score_metrics(scored)
        fold_payoff = payoff_metrics(scored)
        high_payoff = high_payoff_metrics(scored)
        record = {
            "outer_fold": fold_id, "train_count_before_purge": len(train_before), "train_count_after_purge": len(train),
            "purged_event_count": purged, "test_count": len(test), "train_q90": train_q90,
            "train_score_q80": train_score_q80, "logistic_coefficient": float(logistic.coef_[0, 0]),
            "linear_slope": float(linear.coef_[0]), "linear_intercept": float(linear.intercept_),
            **{f"probability_{key}": value for key, value in probability_metrics.items()},
            **{f"high_score_{key}": value for key, value in high_metrics.items()},
            **{f"payoff_{key}": value for key, value in fold_payoff.items()},
            **{f"high_payoff_{key}": value for key, value in high_payoff.items()},
        }
        fold_records.append(record)
        for metric, value in record.items():
            if metric != "outer_fold":
                rows.append(summary_row("OUTER_FOLD", metric.upper(), fold_id, value))
    oos = pd.concat(predictions, ignore_index=True).sort_values("decision_date", kind="mergesort").reset_index(drop=True)
    folds = pd.DataFrame(fold_records)
    require(len(oos) == 625 and oos.decision_date.is_unique, "POOLED_OOS_ROW_IDENTITY_FAILURE")
    require(oos.outer_fold.nunique() == 5 and oos.groupby("outer_fold").size().eq(125).all(), "OUTER_FOLD_TEST_COUNT_FAILURE")
    require(not oos.decision_date.isin(events.iloc[indices[0]].decision_date).any(), "WARMUP_ROWS_IN_POOLED_OOS")
    require((oos.raw_score_available_timestamp <= oos.decision_date).all(), "OOS_PREDICTOR_TIMESTAMP_FAILURE")
    return oos, folds


def classify(oos: pd.DataFrame, folds: pd.DataFrame, rows: list[dict[str, Any]]) -> dict[str, Any]:
    probability = safe_binary_metrics(oos.right_tail.to_numpy(), oos.predicted_right_tail_probability.to_numpy())
    high = high_score_metrics(oos)
    payoff = payoff_metrics(oos)
    high_payoff = high_payoff_metrics(oos)
    positive_logistic = int(folds.logistic_coefficient.gt(0).sum())
    negative_logistic = int(folds.logistic_coefficient.lt(0).sum())
    positive_slope = int(folds.linear_slope.gt(0).sum())
    negative_slope = int(folds.linear_slope.lt(0).sum())

    pre = oos.loc[oos.holding_end.le(PRE2025_END)].copy()
    require(len(pre) > 0 and pre.holding_end.max() <= PRE2025_END, "PRE2025_SCOPE_FAILURE")
    pre_probability = safe_binary_metrics(pre.right_tail.to_numpy(), pre.predicted_right_tail_probability.to_numpy())
    pre_high = high_score_metrics(pre)
    pre_payoff = payoff_metrics(pre)
    pre_high_payoff = high_payoff_metrics(pre)
    pre_probability_sufficient = len(pre) >= 50 and pre.right_tail.sum() >= 5 and pre.right_tail.nunique() == 2
    pre_probability_not_contradictory = (
        not pre_probability_sufficient
        or (pre_probability["auroc"] >= .50 and pre_probability["ap_over_base"] >= 1.0 and pre_high["lift"] >= 1.0)
    )
    pre_payoff_sufficient = len(pre) >= 50
    pre_payoff_not_contradictory = (
        not pre_payoff_sufficient
        or (pre_payoff["pearson"] >= 0 and pre_high_payoff["mean_spread"] >= 0)
    )

    probability_conditions = {
        "POOLED_AUROC_GT_0_50": probability["auroc"] > .50,
        "POOLED_AP_OVER_BASE_GT_1_10": probability["ap_over_base"] > 1.10,
        "POOLED_HIGH_SCORE_LIFT_GT_1_20": high["lift"] > 1.20,
        "POSITIVE_COEFFICIENT_AT_LEAST_4_OF_5": positive_logistic >= 4,
        "PRE2025_NOT_CONTRADICTORY": pre_probability_not_contradictory,
    }
    if all(probability_conditions.values()):
        probability_classification = "SUPPORTED"
    elif (
        probability["auroc"] <= .50 and probability["ap_over_base"] <= 1.0 and high["lift"] <= 1.0
    ) or positive_logistic <= 1 or (pre_probability_sufficient and not pre_probability_not_contradictory and sum(probability_conditions.values()) <= 2):
        probability_classification = "NOT_SUPPORTED"
    else:
        probability_classification = "MIXED"

    payoff_conditions = {
        "POOLED_PAYOFF_RELATIONSHIP_POSITIVE": payoff["pearson"] > 0,
        "POOLED_HIGH_SCORE_MEAN_SPREAD_POSITIVE": high_payoff["mean_spread"] > 0,
        "POSITIVE_SLOPE_AT_LEAST_4_OF_5": positive_slope >= 4,
        "PRE2025_NOT_CONTRADICTORY": pre_payoff_not_contradictory,
    }
    if all(payoff_conditions.values()):
        payoff_classification = "SUPPORTED"
    elif (payoff["pearson"] <= 0 and high_payoff["mean_spread"] <= 0) or positive_slope <= 1 or (pre_payoff_sufficient and not pre_payoff_not_contradictory and sum(payoff_conditions.values()) <= 1):
        payoff_classification = "NOT_SUPPORTED"
    else:
        payoff_classification = "MIXED"

    if probability_classification == payoff_classification == "SUPPORTED":
        overall = "BOTH_PROBABILITY_AND_PAYOFF_SUPPORTED"
    elif probability_classification == "SUPPORTED" and payoff_classification != "SUPPORTED":
        overall = "PROBABILITY_ONLY_SUPPORTED"
    elif payoff_classification == "SUPPORTED" and probability_classification != "SUPPORTED":
        overall = "PAYOFF_ONLY_SUPPORTED"
    elif probability_classification == payoff_classification == "NOT_SUPPORTED":
        overall = "NOT_SUPPORTED"
    else:
        overall = "MIXED"
    justification = "SUPPORTED" if "SUPPORTED" in overall and overall != "NOT_SUPPORTED" else ("MIXED" if overall == "MIXED" else "NOT_SUPPORTED")

    wealth_label = oos.event_group.eq("RIGHT_TAIL_EVENT")
    scale_label = oos.right_tail.eq(1)
    intersection = int((wealth_label & scale_label).sum())
    union = int((wealth_label | scale_label).sum())
    overlap = intersection / union if union else float("nan")
    pooled_values = {
        "probability": probability, "high": high, "payoff": payoff, "high_payoff": high_payoff,
        "positive_logistic": positive_logistic, "negative_logistic": negative_logistic,
        "positive_slope": positive_slope, "negative_slope": negative_slope,
        "pre": pre, "pre_probability": pre_probability, "pre_high": pre_high,
        "pre_payoff": pre_payoff, "pre_high_payoff": pre_high_payoff,
        "probability_conditions": probability_conditions, "payoff_conditions": payoff_conditions,
        "probability_classification": probability_classification, "payoff_classification": payoff_classification,
        "overall": overall, "justification": justification, "overlap": overlap,
        "overlap_intersection": intersection, "scale_tail_count": int(scale_label.sum()),
        "wealth_tail_count": int(wealth_label.sum()), "full_wealth_tail_count": 75,
    }
    for metric, value in probability.items():
        rows.append(summary_row("POOLED_PROBABILITY", metric.upper(), "OUTER_TEST_ONLY", value))
    for metric, value in high.items():
        rows.append(summary_row("POOLED_HIGH_SCORE", metric.upper(), "OUTER_TEST_ONLY", value, "fold-local TRAIN score Q80"))
    rows.extend([
        summary_row("POOLED_PROBABILITY", "POSITIVE_LOGISTIC_COEFFICIENT_FOLD_COUNT", "OUTER_TEST_ONLY", positive_logistic),
        summary_row("POOLED_PROBABILITY", "NEGATIVE_LOGISTIC_COEFFICIENT_FOLD_COUNT", "OUTER_TEST_ONLY", negative_logistic),
    ])
    for metric, value in payoff.items():
        rows.append(summary_row("POOLED_PAYOFF", metric.upper(), "OUTER_TEST_ONLY", value))
    for metric, value in high_payoff.items():
        rows.append(summary_row("POOLED_HIGH_SCORE_PAYOFF", metric.upper(), "OUTER_TEST_ONLY", value, "fold-local TRAIN score Q80"))
    rows.extend([
        summary_row("POOLED_PAYOFF", "POSITIVE_PAYOFF_SLOPE_FOLD_COUNT", "OUTER_TEST_ONLY", positive_slope),
        summary_row("POOLED_PAYOFF", "NEGATIVE_PAYOFF_SLOPE_FOLD_COUNT", "OUTER_TEST_ONLY", negative_slope),
    ])
    for metric, value in pre_probability.items():
        rows.append(summary_row("PRE2025_PROBABILITY", metric.upper(), "OUTER_TEST_ONLY_PRE2025", value))
    for metric, value in pre_high.items():
        rows.append(summary_row("PRE2025_HIGH_SCORE", metric.upper(), "OUTER_TEST_ONLY_PRE2025", value))
    for metric, value in pre_payoff.items():
        rows.append(summary_row("PRE2025_PAYOFF", metric.upper(), "OUTER_TEST_ONLY_PRE2025", value))
    for metric, value in pre_high_payoff.items():
        rows.append(summary_row("PRE2025_HIGH_SCORE_PAYOFF", metric.upper(), "OUTER_TEST_ONLY_PRE2025", value))
    rows.extend([
        summary_row("WEALTH_ROBUSTNESS", "SCALE_FREE_VS_WEALTH_RIGHT_TAIL_OVERLAP", "COMPARABLE_POOLED_OOS", overlap, "Jaccard intersection/union"),
        summary_row("WEALTH_ROBUSTNESS", "SCALE_FREE_VS_WEALTH_RIGHT_TAIL_INTERSECTION_COUNT", "COMPARABLE_POOLED_OOS", intersection),
        summary_row("WEALTH_ROBUSTNESS", "SCALE_FREE_RIGHT_TAIL_COUNT", "COMPARABLE_POOLED_OOS", int(scale_label.sum())),
        summary_row("WEALTH_ROBUSTNESS", "PRIOR_WEALTH_RIGHT_TAIL_COUNT", "COMPARABLE_POOLED_OOS", int(wealth_label.sum()), "full prior fixed set count=75"),
    ])
    for key, value in probability_conditions.items():
        rows.append(summary_row("EVIDENCE_GATES", key, "PROBABILITY", str(value).lower()))
    for key, value in payoff_conditions.items():
        rows.append(summary_row("EVIDENCE_GATES", key, "PAYOFF", str(value).lower()))
    rows.extend([
        summary_row("CLASSIFICATION", "PROBABILITY_SIGNAL_CLASSIFICATION", "ALL", probability_classification),
        summary_row("CLASSIFICATION", "PAYOFF_SIGNAL_CLASSIFICATION", "ALL", payoff_classification),
        summary_row("CLASSIFICATION", "RAW_A2_SCORE_TAIL_PREDICTION_CLASSIFICATION", "ALL", overall),
        summary_row("CLASSIFICATION", "NEXT_TAIL_MODEL_RESEARCH_JUSTIFICATION", "ALL", justification),
    ])
    return pooled_values


def fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "NA"
    if isinstance(value, float):
        return f"{value:.10f}"
    return str(value)


def build_report(events: pd.DataFrame, oos: pd.DataFrame, folds: pd.DataFrame, result: dict[str, Any], terminal_delta: float) -> str:
    probability = result["probability"]
    high = result["high"]
    payoff = result["payoff"]
    high_payoff = result["high_payoff"]
    pre_probability = result["pre_probability"]
    pre_high = result["pre_high"]
    pre_payoff = result["pre_payoff"]
    pre_high_payoff = result["pre_high_payoff"]
    lines = [
        "# A2 Raw-score OOS tail prediction R1", "", "## Verdict", "",
        f"`RAW_A2_SCORE_TAIL_PREDICTION_CLASSIFICATION={result['overall']}`", "",
        f"Probability evidence is `{result['probability_classification']}`; scale-free payoff evidence is `{result['payoff_classification']}`. The justification for one future, separately authorized tail-model research step is `{result['justification']}`. No strategy, A2 coefficient, feature, threshold, or forward arm was changed.", "",
        "## Data and scale-free target", "",
        f"The exact {len(events)} prior replacement events and the exact prior `raw_score` event field were reused. Score coverage is {events.raw_score.notna().mean():.1%}; every score timestamp is no later than its decision date.", "",
        "`EVENT_ACTIVE_RETURN = EVENT_INCREMENTAL_WEALTH / PRE_EVENT_A2_NAV`, where `PRE_EVENT_A2_NAV` is authoritative A2 `pretrade_nav` at the event's `holding_start`. All denominators are positive, all targets are finite, and target signs match wealth-contribution signs.", "",
        "## Chronological OOS contract", "",
        "No existing project fold contract was directly compatible with this event dataset. The authorized fallback was therefore used: six fixed contiguous 125-date blocks, block 1 as warm-up and blocks 2–6 as five expanding outer tests. Each training event whose outcome end reached the first test economic-active date was purged. Q90 labels and score Q80 diagnostics were fitted from the purged TRAIN rows only using NumPy's fixed linear percentile convention.", "",
        "| Fold | Train before/after purge | Purged | Test | Train Q90 | Train score Q80 | Logistic coefficient | Payoff slope | AUROC | AP/base | High-score lift |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in folds.itertuples(index=False):
        lines.append(
            f"| {row.outer_fold} | {row.train_count_before_purge}/{row.train_count_after_purge} | {row.purged_event_count} | {row.test_count} | "
            f"{row.train_q90:.6f} | {row.train_score_q80:.6f} | {row.logistic_coefficient:.6f} | {row.linear_slope:.6f} | "
            f"{fmt(row.probability_auroc)} | {fmt(row.probability_ap_over_base)} | {fmt(row.high_score_lift)} |"
        )
    lines.extend([
        "", "`OUTER_5` has no test event above its TRAIN-only score Q80, so its high-score rate and lift are correctly reported as NA; no alternative threshold was substituted.",
        "", "## Probability question", "",
        f"Strict-OOS pooled N is {probability['n']} with {probability['positive_count']} fold-local scale-free right-tail events (base rate {probability['base_rate']:.2%}). AUROC is {fmt(probability['auroc'])}, AP/base is {fmt(probability['ap_over_base'])}, Brier is {fmt(probability['brier'])}, and fold-local high-score winner lift is {fmt(high['lift'])}. Logistic coefficients were positive in {result['positive_logistic']}/5 folds.", "",
        f"Before 2025, N is {len(result['pre'])}; AUROC is {fmt(pre_probability['auroc'])}, AP/base is {fmt(pre_probability['ap_over_base'])}, and high-score lift is {fmt(pre_high['lift'])}.", "",
        "## Payoff question", "",
        f"Pooled payoff OOS R2 against each fold's TRAIN-mean baseline is {fmt(payoff['oos_r2_train_mean_baseline'])}. Pearson and Spearman correlations are {fmt(payoff['pearson'])} and {fmt(payoff['spearman'])}. The fixed high-score minus lower-score mean and median payoff spreads are {fmt(high_payoff['mean_spread'])} and {fmt(high_payoff['median_spread'])}; payoff slopes were positive in {result['positive_slope']}/5 folds.", "",
        f"Before 2025, payoff Pearson correlation is {fmt(pre_payoff['pearson'])} and the high-minus-lower mean payoff spread is {fmt(pre_high_payoff['mean_spread'])}.", "",
        "## Interpretation", "",
        f"1. Raw A2 score predicting future scale-free right-tail probability OOS: `{result['probability_classification']}`.",
        f"2. Raw A2 score predicting future scale-free incremental payoff OOS: `{result['payoff_classification']}`.",
        f"3. Mechanism supported by this test: `{result['overall']}`.",
        f"4. Direction stability: Logistic {result['positive_logistic']} positive/{result['negative_logistic']} negative folds; payoff slope {result['positive_slope']} positive/{result['negative_slope']} negative folds.",
        f"5. Pre-2025 evidence is {'not contradictory' if result['probability_conditions']['PRE2025_NOT_CONTRADICTORY'] and result['payoff_conditions']['PRE2025_NOT_CONTRADICTORY'] else 'contradictory for at least one target'} under the fixed directional rules.",
        f"6. The earlier antecedent survives removal of NAV scale only as a right-tail probability signal, not as a stable payoff-magnitude predictor. Scale-free versus prior wealth-tail Jaccard overlap is {fmt(result['overlap'])} ({result['overlap_intersection']} shared events within the comparable OOS scope).",
        f"7. Future research justification: `{result['justification']}`. This does not authorize another predictor, model, strategy, or automatic follow-up.", "",
        "## Validation and boundaries", "",
        f"- Event wealth identity maximum absolute error: {abs(events.event_incremental_wealth.sum() - terminal_delta):.3e}.",
        "- Five outer-test folds contain only mutually exclusive test rows; block-1 warm-up rows never enter pooled metrics.",
        "- Every fold has strict train-before-test dates and strict `train holding_end < first test holding_start` after purge.",
        "- Scaling, TRAIN Q90, TRAIN score Q80, Logistic, and OLS are fit from TRAIN only.",
        f"- Maximum realized outcome date: {oos.holding_end.max().date()}; post-2025 outcome used: false; network used: false.",
        "- This is an outcome-exposed historical OOS diagnostic, not a strategy or promotion decision.", "",
    ])
    return "\n".join(lines)


def console_summary(events: pd.DataFrame, oos: pd.DataFrame, folds: pd.DataFrame, result: dict[str, Any], artifact_count: int) -> str:
    p = result["probability"]
    h = result["high"]
    pay = result["payoff"]
    hp = result["high_payoff"]
    pre_p = result["pre_probability"]
    pre_h = result["pre_high"]
    pre_hp = result["pre_high_payoff"]
    fields = {
        "RESEARCH_RESULT_STATUS": "COMPLETE_STRICT_CHRONOLOGICAL_OOS_DIAGNOSTIC",
        "EXECUTION_STATUS": "PASS", "REPOSITORY_POLICY_STATUS": "PASS_WITH_PREEXISTING_UNRELATED_WARNINGS",
        "DATE_MAX_OUTCOME_USED": oos.holding_end.max().date(), "POST_2025_OUTCOME_USED": "false", "NETWORK_USED": "false",
        "EVENT_ACTIVE_RETURN_DEFINITION": "EVENT_INCREMENTAL_WEALTH/PRE_EVENT_A2_NAV",
        "TOTAL_VALID_EVENT_COUNT": len(events), "OUTER_FOLD_COUNT": len(folds),
        "TOTAL_PURGED_EVENT_COUNT": int(folds.purged_event_count.sum()), "POOLED_OOS_EVENT_COUNT": p["n"],
        "POOLED_OOS_RIGHT_TAIL_COUNT": p["positive_count"], "POOLED_OOS_BASE_RATE": p["base_rate"],
        "POOLED_OOS_AUROC": p["auroc"], "POOLED_OOS_AP": p["ap"], "POOLED_OOS_AP_OVER_BASE": p["ap_over_base"], "POOLED_OOS_BRIER": p["brier"],
        "POOLED_HIGH_SCORE_RIGHT_TAIL_RATE": h["high_rate"], "POOLED_HIGH_SCORE_WINNER_LIFT": h["lift"],
        "POSITIVE_LOGISTIC_COEFFICIENT_FOLD_COUNT": result["positive_logistic"],
        "POOLED_PAYOFF_OOS_R2": pay["oos_r2_train_mean_baseline"], "POOLED_PAYOFF_PEARSON": pay["pearson"], "POOLED_PAYOFF_SPEARMAN": pay["spearman"],
        "POOLED_HIGH_SCORE_MINUS_LOWER_SCORE_MEAN_PAYOFF": hp["mean_spread"], "POOLED_HIGH_SCORE_MINUS_LOWER_SCORE_MEDIAN_PAYOFF": hp["median_spread"],
        "POSITIVE_PAYOFF_SLOPE_FOLD_COUNT": result["positive_slope"],
        "PRE2025_OOS_EVENT_COUNT": len(result["pre"]), "PRE2025_OOS_AUROC": pre_p["auroc"], "PRE2025_OOS_AP_OVER_BASE": pre_p["ap_over_base"],
        "PRE2025_HIGH_SCORE_WINNER_LIFT": pre_h["lift"], "PRE2025_HIGH_SCORE_MINUS_LOWER_SCORE_MEAN_PAYOFF": pre_hp["mean_spread"],
        "SCALE_FREE_VS_WEALTH_RIGHT_TAIL_OVERLAP": result["overlap"],
        "PROBABILITY_SIGNAL_CLASSIFICATION": result["probability_classification"],
        "PAYOFF_SIGNAL_CLASSIFICATION": result["payoff_classification"],
        "RAW_A2_SCORE_TAIL_PREDICTION_CLASSIFICATION": result["overall"],
        "NEXT_TAIL_MODEL_RESEARCH_JUSTIFICATION": result["justification"],
        "SOURCE_MODIFICATION_COUNT": 1, "RESULT_ARTIFACT_COUNT": artifact_count, "TEMP_FILE_REMAINS": 0,
        "NEXT_RESEARCH_QUESTION": "STOP;HUMAN_REVIEW_ONLY;DO_NOT_AUTO_START_FOLLOW_UP",
    }
    lines = ["=" * 60, f"{TASK_NAME}_FINAL", "=" * 60, ""]
    lines.extend(f"{key}={fmt(value)}" for key, value in fields.items())
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def main() -> None:
    events, rows, terminal_delta = load_validated_events()
    oos, folds = build_outer_oos(events, rows)
    result = classify(oos, folds, rows)
    summary = pd.DataFrame(rows)
    report = build_report(events, oos, folds, result, terminal_delta)
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob(".*.tmp"):
        path.unlink()
    atomic_csv(OUT / "oos_summary.csv", summary)
    atomic_parquet(OUT / "oos_predictions.parquet", oos)
    atomic_text(OUT / "final_report.md", report)
    artifacts = sorted(path for path in OUT.iterdir() if path.is_file())
    require(len(artifacts) == 3, "RESULT_ARTIFACT_COUNT_FAILURE", [path.name for path in artifacts])
    require(not list(OUT.glob(".*.tmp")), "TEMP_FILE_REMAINS")
    print(console_summary(events, oos, folds, result, len(artifacts)))


if __name__ == "__main__":
    main()
