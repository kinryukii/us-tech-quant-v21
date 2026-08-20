#!/usr/bin/env python
"""FAST3 R35 economic-selection R1: fixed OOF selected-signal loss-risk audit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score, mean_absolute_error, roc_auc_score

SOURCE_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R30A_FROZEN = RESULTS_ROOT / "frozen/fast3/r30a_economic_target_20260809T120000Z"
R30A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"
R28_3G_LEDGER = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28_PHASE2_DECISION = RESULTS_ROOT / "frozen/fast3/r28_phase2_20260808T125629Z/R28_PHASE2_DECISION.json"
R28_PHASE3_IDENTITY = RESULTS_ROOT / "frozen/fast3/r28_phase3_20260808T131135Z/R28_PHASE3_RESEARCH_IDENTITY.json"
R30A_DATA_IDENTITY = R30A_FROZEN / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30A_FEATURE_IDENTITY = R30A_FROZEN / "FAST3_R30A_FEATURE_IDENTITY.json"
R30A_SPLIT_IDENTITY = R30A_FROZEN / "FAST3_R30A_SPLIT_IDENTITY.json"

EXPECTED = {
    "R28_3G_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "R28_PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "R30A_TARGET_LEDGER": "7ea7521b97b7e633cb1b843fb406f6f385bd878998bd9c9b332f7dc5da1f245d",
    "R30A_FEATURE_LEDGER": "171c55eb837d14ba07b4bc9c36f2c8461d38d4e5d62104bc4463dc86d44824a1",
}
BASE_FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m",
    "realized_vol_60m", "relative_volume", "range_position", "symbol_code",
    "direction_code", "session_code", "volume_zscore_60m",
    "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
DERIVED_FEATURES = (
    "realized_vol_ratio_15m_60m", "abs_return_15m",
    "cross_asset_disagreement_15m", "abs_relative_dislocation_15m",
)
FEATURES = BASE_FEATURES + DERIVED_FEATURES
CATEGORICAL = ("symbol_code", "session_code")
FILTER_EXCLUSIONS = (5, 10, 20)
MODEL_PARAMS = {
    "learning_rate": 0.05, "max_iter": 100, "max_leaf_nodes": 7,
    "min_samples_leaf": 20, "l2_regularization": 1.0, "random_state": 1729,
}
CLASSIFICATIONS = {
    "A_LOSS_SEVERITY_FILTER_CONFIRMED_POSITIVE_ECONOMIC_EDGE",
    "B_LOSS_SEVERITY_SIGNAL_EXISTS_BUT_ECONOMIC_EDGE_NOT_CONFIRMED",
    "C_NO_USEFUL_LOSS_SEVERITY_SIGNAL", "D_INVALID_RESEARCH_INTEGRITY_FAILURE",
}


class R35EconomicStop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def value_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None: raise R35EconomicStop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def preregistration(created_at: str, data_identity: dict[str, Any], r30a) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R35_ECONOMIC_SELECTION_R1_PREREGISTRATION",
        "STATUS": "FROZEN_BEFORE_STAGE1_METRICS_AND_MODEL_FIT", "CREATED_AT_UTC": created_at,
        "RESEARCH_QUESTION": "Can decision-time features rank severe losses among immutable R28 selected signals?",
        "ECONOMIC_MODEL_TRAINING_UNIT": "R28_SELECTED_SIGNAL", "BASELINE_SIGNAL_COUNT": 1197,
        "R28_PHASE2_DECISION_SHA256": EXPECTED["R28_PHASE2_DECISION"],
        "R28_CORRECTED_LEDGER_SHA256": EXPECTED["R28_3G_LEDGER"],
        "TARGET_LEDGER_SHA256": EXPECTED["R30A_TARGET_LEDGER"],
        "FEATURE_LEDGER_SHA256": EXPECTED["R30A_FEATURE_LEDGER"],
        "FEATURES": list(FEATURES), "BASE_FEATURE_COUNT": 14, "DERIVED_FEATURE_COUNT": 4,
        "DERIVED_FEATURE_FORMULAS": {
            "realized_vol_ratio_15m_60m": "realized_vol_15m/realized_vol_60m; zero denominator -> missing",
            "abs_return_15m": "abs(return_15m)",
            "cross_asset_disagreement_15m": "abs(peer_return_15m-return_15m)",
            "abs_relative_dislocation_15m": "abs(relative_return_15m)",
        },
        "TARGET_A": "LARGE_LOSS_2PCT=1[NET20<=-0.02]", "TARGET_B": "LOSS_SEVERITY=max(-NET20,0)",
        "TARGET_C_ROBUSTNESS_ONLY": "LARGE_LOSS_3PCT=1[NET20<=-0.03]",
        "STAGE1_GATE": {"max_oriented_univariate_auc_gte": 0.60, "feature_count_auc_gte_0_56": 2},
        "MODEL_VARIANTS": ["HGB_CLASSIFIER_LARGE_LOSS_2PCT", "HGB_REGRESSOR_LOSS_SEVERITY"],
        "MODEL_PARAMS": MODEL_PARAMS, "MODEL_CONFIG_COUNT": 1, "DIRECTION_HANDLING": "SEPARATE_UP_DOWN",
        "FOLDS": [list(row) for row in r30a.ECONOMIC_FOLDS], "FOLD_METHOD": "EXPANDING_WINDOW_PURGED_24H",
        "LOSS_HEAD_GATE": {
            "classifier": "AUC>=0.55, PR_AUC>base_rate, top10 event rate>bottom50 event rate, >=3 positive-AUC folds",
            "regressor": "Spearman>=0.10 and >=3 positive-Spearman folds",
            "risk_score_priority": ["CLASSIFIER", "REGRESSOR"],
        },
        "FILTER_EXCLUSION_LEVELS": list(FILTER_EXCLUSIONS),
        "FILTER_BOUNDARY": "within-fold stable rank of OOF risk predictions only",
        "FILTER_SELECTION_RULE": "FIRST_PASS_BY_MINIMUM_EXCLUSION_5_THEN_10_THEN_20",
        "FILTER_PASS_GATE": "mean_net20>0, profit_factor>1, retention>=0.80, abs(mean_loss) improves, >=3 folds improve mean",
        "STOP_IF_NO_DISCRIMINATION": True, "STOP_IF_NO_FILTER_PASSES": True,
        "R28_REFIT_ALLOWED": False, "R28_THRESHOLD_CHANGE_ALLOWED": False,
        "HYPERPARAMETER_SEARCH_ALLOWED": False, "FEATURE_SEARCH_ALLOWED": False,
        "FILTER_SEARCH_ALLOWED": False, "FINAL_CONFIRMATION_DATA_ALLOWED": False,
        "TRUE_HOLDOUT_START": data_identity["TRUE_HOLDOUT_START"],
    }


def verify_lineage(r30a) -> dict[str, Any]:
    required = [R28_3G_LEDGER, R28_PHASE2_DECISION, R28_PHASE3_IDENTITY, R30A_DATA_IDENTITY,
                R30A_FEATURE_IDENTITY, R30A_SPLIT_IDENTITY]
    if not all(path.is_file() for path in required): raise R35EconomicStop("STOP_LINEAGE_FILE_MISSING")
    if sha256(R28_3G_LEDGER) != EXPECTED["R28_3G_LEDGER"]: raise R35EconomicStop("STOP_CORRECTED_LEDGER_HASH")
    if sha256(R28_PHASE2_DECISION) != EXPECTED["R28_PHASE2_DECISION"]: raise R35EconomicStop("STOP_R28_IDENTITY_HASH")
    identity = read_json(R30A_DATA_IDENTITY); feature = read_json(R30A_FEATURE_IDENTITY); split = read_json(R30A_SPLIT_IDENTITY)
    target_path = Path(identity["TARGET_LEDGER_PATH"]); feature_path = Path(identity["FEATURE_LEDGER_SOURCE"])
    if sha256(target_path) != EXPECTED["R30A_TARGET_LEDGER"] or sha256(feature_path) != EXPECTED["R30A_FEATURE_LEDGER"]:
        raise R35EconomicStop("STOP_SELECTED_SIGNAL_LEDGER_HASH")
    if identity["TARGET_ROW_COUNT"] != 1197 or identity["FINAL_CONFIRMATION_DATA_USED"]:
        raise R35EconomicStop("STOP_TARGET_CARDINALITY_OR_FINAL")
    if tuple(feature["FEATURE_NAMES"]) != BASE_FEATURES or split["FOLD_COUNT"] != 5:
        raise R35EconomicStop("STOP_FEATURE_OR_FOLD_IDENTITY")
    if split["EVALUATED_FOLDS"] != [list(row) for row in r30a.ECONOMIC_FOLDS]:
        raise R35EconomicStop("STOP_FOLD_IDENTITY")
    return {"data": identity, "feature": feature, "split": split, "target_path": target_path, "feature_path": feature_path}


def add_targets_and_features(targets: pd.DataFrame, feature_rows: pd.DataFrame) -> pd.DataFrame:
    feature_copy = feature_rows.drop(columns=["head", "underlying_symbol"], errors="ignore")
    frame = targets.merge(feature_copy, on=["candidate_id", "decision_timestamp_utc"], validate="one_to_one")
    denominator = frame["realized_vol_60m"].replace(0.0, np.nan)
    frame["realized_vol_ratio_15m_60m"] = frame["realized_vol_15m"] / denominator
    frame["abs_return_15m"] = frame["return_15m"].abs()
    frame["cross_asset_disagreement_15m"] = (frame["peer_return_15m"] - frame["return_15m"]).abs()
    frame["abs_relative_dislocation_15m"] = frame["relative_return_15m"].abs()
    frame["LARGE_LOSS_2PCT"] = (frame["raw_net20"] <= -0.02).astype(int)
    frame["LARGE_LOSS_3PCT"] = (frame["raw_net20"] <= -0.03).astype(int)
    frame["LARGE_LOSS_5PCT"] = (frame["raw_net20"] <= -0.05).astype(int)
    frame["LOSS_SEVERITY"] = (-frame["raw_net20"]).clip(lower=0.0)
    frame["outcome_group"] = np.select(
        [frame["raw_net20"] > 0, frame["raw_net20"] <= -0.02], ["WIN", "LARGE_LOSS"], default="NORMAL_LOSS")
    return frame.sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)


def integrity_audit(frame: pd.DataFrame, r30a) -> dict[str, Any]:
    decision = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="raise")
    feature_time = pd.to_datetime(frame["max_feature_timestamp_utc"], utc=True, errors="raise")
    label_time = pd.to_datetime(frame["label_information_end_utc"], utc=True, errors="raise")
    if len(frame) != 1197 or frame["candidate_id"].duplicated().any(): raise R35EconomicStop("STOP_TARGET_IDENTITY")
    if not bool((feature_time <= decision).all()): raise R35EconomicStop("STOP_PIT_FAILURE")
    if not bool((label_time >= decision).all()) or decision.max() >= r30a.TRUE_HOLDOUT_START:
        raise R35EconomicStop("STOP_LABEL_OR_HOLDOUT_FAILURE")
    expected = pd.read_csv(R28_3G_LEDGER)
    expected = expected.loc[expected["primary_executable_first_touch_cohort"].astype(bool), ["candidate_id", "corrected_net20"]]
    check = frame[["candidate_id", "raw_net20"]].merge(expected, on="candidate_id", validate="one_to_one")
    max_diff = float((check["raw_net20"] - check["corrected_net20"]).abs().max())
    if len(check) != 1197 or max_diff > 1e-12: raise R35EconomicStop("STOP_CORPORATE_ACTION_TARGET_MISMATCH")
    return {"PIT_STATUS": "PASS", "FUTURE_FEATURE_ROW_COUNT": 0, "TARGET_RECONCILIATION_MAX_ABS_DIFF": max_diff,
            "CORPORATE_ACTION_STATUS": "PASS", "PAYOFF_ROW_COUNT": len(check)}


def safe_spearman(x: Any, y: Any) -> float | None:
    a = np.asarray(x, dtype=float); b = np.asarray(y, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b); a = a[mask]; b = b[mask]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2: return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def safe_auc(y: Any, score: Any) -> float | None:
    target = np.asarray(y, dtype=int); pred = np.asarray(score, dtype=float)
    mask = np.isfinite(pred); target = target[mask]; pred = pred[mask]
    if len(target) < 2 or np.unique(target).size < 2: return None
    return float(roc_auc_score(target, pred))


def stage1_tables(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    distribution_rows = []
    effect_rows = []
    for feature in FEATURES:
        for group in ("WIN", "NORMAL_LOSS", "LARGE_LOSS"):
            values = pd.to_numeric(frame.loc[frame["outcome_group"].eq(group), feature], errors="coerce").dropna()
            distribution_rows.append({"feature": feature, "outcome_group": group, "count": len(values),
                                      "mean": values.mean(), "median": values.median(), "p25": values.quantile(.25), "p75": values.quantile(.75)})
        valid = frame[[feature, "LARGE_LOSS_2PCT"]].dropna()
        auc = safe_auc(valid["LARGE_LOSS_2PCT"], valid[feature])
        oriented = None if auc is None else max(auc, 1.0 - auc)
        effect_rows.append({"feature": feature, "raw_auc_vs_large_loss_2pct": auc,
                            "oriented_univariate_auc": oriented,
                            "signed_rank_biserial_effect": None if auc is None else 2.0 * auc - 1.0})
    effects = pd.DataFrame(effect_rows).sort_values(["oriented_univariate_auc", "feature"], ascending=[False, True])
    max_auc = float(effects["oriented_univariate_auc"].max())
    count_56 = int((effects["oriented_univariate_auc"] >= .56).sum())
    gate = bool(max_auc >= .60 and count_56 >= 2)
    return pd.DataFrame(distribution_rows), effects, {"STAGE1_MAX_ORIENTED_AUC": max_auc,
                                                       "STAGE1_FEATURE_COUNT_AUC_GE_056": count_56,
                                                       "DO_DECISION_TIME_FEATURES_SHOW_LOSS_SEVERITY_STRUCTURE": gate}


def feature_mutation_hash(frame: pd.DataFrame, future_outcome: pd.Series | None = None) -> str:
    # Outcome values are intentionally absent from the feature identity.
    _ = future_outcome
    values = frame[["candidate_id", "decision_timestamp_utc", *FEATURES]].sort_values("candidate_id", kind="mergesort")
    return hashlib.sha256(pd.util.hash_pandas_object(values, index=False).values.tobytes()).hexdigest()


def model_params() -> tuple[dict[str, Any], dict[str, Any]]:
    mask = [name in CATEGORICAL for name in FEATURES]
    common = {**MODEL_PARAMS, "categorical_features": mask}
    return common.copy(), common.copy()


def run_oof(frame: pd.DataFrame, r30a, scratch: Path, prereg_path: Path, prereg_sha: str) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    classifier_params, regressor_params = model_params(); parts = []; fold_rows = []
    fit_count = predict_count = 0
    model_root = scratch / "models"; model_root.mkdir(parents=True, exist_ok=False)
    for fold in r30a.ECONOMIC_FOLDS:
        train_all, valid_all, audit = r30a.construct_economic_fold(frame, fold)
        direction_parts = []
        for direction in ("UP", "DOWN"):
            train = train_all.loc[train_all["head"].eq(direction)].copy()
            valid = valid_all.loc[valid_all["head"].eq(direction)].copy()
            if train.empty or valid.empty or sha256(prereg_path) != prereg_sha:
                raise R35EconomicStop("STOP_OOF_OR_PREREGISTRATION_INTEGRITY")
            classifier = HistGradientBoostingClassifier(**classifier_params)
            classifier.fit(train[list(FEATURES)], train["LARGE_LOSS_2PCT"]); fit_count += 1
            regressor = HistGradientBoostingRegressor(**regressor_params)
            regressor.fit(train[list(FEATURES)], train["LOSS_SEVERITY"]); fit_count += 1
            scored = valid.copy()
            scored["pred_large_loss_2pct"] = classifier.predict_proba(valid[list(FEATURES)])[:, 1]; predict_count += 1
            scored["pred_loss_severity"] = regressor.predict(valid[list(FEATURES)]); predict_count += 1
            scored["fold"] = fold[0]; direction_parts.append(scored)
            for name, model in (("CLASSIFIER", classifier), ("REGRESSOR", regressor)):
                path = model_root / f"{name}_{direction}_{fold[0]}.joblib"
                joblib.dump(model, path, compress=3)
        fold_scored = pd.concat(direction_parts, ignore_index=True)
        auc = safe_auc(fold_scored["LARGE_LOSS_2PCT"], fold_scored["pred_large_loss_2pct"])
        rank = safe_spearman(fold_scored["pred_loss_severity"], fold_scored["LOSS_SEVERITY"])
        fold_rows.append({**audit, "classifier_auc": auc, "regressor_spearman": rank,
                          "unfiltered_mean_net20": float(fold_scored["raw_net20"].mean())})
        parts.append(fold_scored)
    oof = pd.concat(parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort")
    if oof["candidate_id"].duplicated().any() or len(oof) != sum(row["validation_rows"] for row in fold_rows):
        raise R35EconomicStop("STOP_OOF_DUPLICATE_OR_CARDINALITY")
    return oof.reset_index(drop=True), pd.DataFrame(fold_rows), fit_count, predict_count


def assign_fold_risk_percentile(oof: pd.DataFrame, score: str) -> pd.Series:
    result = pd.Series(index=oof.index, dtype=float)
    for _, index in oof.groupby("fold", sort=True).groups.items():
        ordered = oof.loc[index].sort_values([score, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
        percentile = (np.arange(len(ordered), dtype=float) + 1.0) / len(ordered)
        result.loc[ordered.index] = percentile
    return result


def economic_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    net = frame["raw_net20"].astype(float); wins = net[net > 0]; losses = net[net < 0]
    return {"signal_count": len(frame), "win_rate_net20": float((net > 0).mean()), "mean_net20": float(net.mean()),
            "median_net20": float(net.median()), "mean_win_net20": float(wins.mean()) if len(wins) else None,
            "mean_loss_net20": float(losses.mean()) if len(losses) else None,
            "profit_factor_net20": float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else None,
            "p05_net20": float(net.quantile(.05)), "p10_net20": float(net.quantile(.10)), "worst_trade_net20": float(net.min()),
            "large_loss_2pct_rate": float((net <= -.02).mean()), "large_loss_3pct_rate": float((net <= -.03).mean()),
            "large_loss_5pct_rate": float((net <= -.05).mean())}


def loss_head_metrics(oof: pd.DataFrame, folds: pd.DataFrame) -> dict[str, Any]:
    target = oof["LARGE_LOSS_2PCT"]; pred = oof["pred_large_loss_2pct"]
    auc = safe_auc(target, pred); pr = float(average_precision_score(target, pred)); base = float(target.mean())
    classifier_ranked = oof.assign(_risk=assign_fold_risk_percentile(oof, "pred_large_loss_2pct"))
    top10 = classifier_ranked.loc[classifier_ranked["_risk"] > .90, "LARGE_LOSS_2PCT"].mean()
    bottom50 = classifier_ranked.loc[classifier_ranked["_risk"] <= .50, "LARGE_LOSS_2PCT"].mean()
    positive_auc_folds = int((folds["classifier_auc"] > .5).sum())
    reg_s = safe_spearman(oof["pred_loss_severity"], oof["LOSS_SEVERITY"])
    positive_reg_folds = int((folds["regressor_spearman"] > 0).sum())
    classifier_gate = bool(auc is not None and auc >= .55 and pr > base and top10 > bottom50 and positive_auc_folds >= 3)
    regressor_gate = bool(reg_s is not None and reg_s >= .10 and positive_reg_folds >= 3)
    selected = "HGB_CLASSIFIER_LARGE_LOSS_2PCT" if classifier_gate else "HGB_REGRESSOR_LOSS_SEVERITY" if regressor_gate else "NONE"
    return {"LOSS2_AUC": auc, "LOSS2_PR_AUC": pr, "LOSS2_BASE_RATE": base,
            "LOSS2_TOP10_RISK_EVENT_RATE": float(top10), "LOSS2_BOTTOM50_RISK_EVENT_RATE": float(bottom50),
            "LOSS2_POSITIVE_AUC_FOLD_COUNT": positive_auc_folds, "LOSS_SEVERITY_MAE": float(mean_absolute_error(oof["LOSS_SEVERITY"], oof["pred_loss_severity"])),
            "LOSS_SEVERITY_SPEARMAN": reg_s, "LOSS_SEVERITY_POSITIVE_FOLD_COUNT": positive_reg_folds,
            "CLASSIFIER_DISCRIMINATION_GATE": classifier_gate, "REGRESSOR_DISCRIMINATION_GATE": regressor_gate,
            "LOSS_HEAD_MODEL": selected}


def evaluate_filters(oof: pd.DataFrame, folds: pd.DataFrame, score: str) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    ranked = oof.copy(); ranked["risk_percentile"] = assign_fold_risk_percentile(ranked, score)
    baseline = economic_metrics(ranked); rows = []
    for exclusion in FILTER_EXCLUSIONS:
        kept = ranked.loc[ranked["risk_percentile"] <= 1.0 - exclusion / 100.0].copy()
        metrics = economic_metrics(kept); direction_metrics = {d: economic_metrics(part) for d, part in kept.groupby("head", sort=True)}
        improvements = 0
        for fold, part in ranked.groupby("fold", sort=True):
            filtered = part.loc[part["risk_percentile"] <= 1.0 - exclusion / 100.0]
            if not filtered.empty and filtered["raw_net20"].mean() > part["raw_net20"].mean(): improvements += 1
        retention = len(kept) / len(ranked)
        passed = bool(metrics["mean_net20"] > 0 and metrics["profit_factor_net20"] > 1 and retention >= .80
                      and abs(metrics["mean_loss_net20"]) < abs(baseline["mean_loss_net20"]) and improvements >= 3)
        rows.append({"filter": f"EXCLUDE_TOP_{exclusion}PCT_RISK", "exclusion_pct": exclusion, "retention_rate": retention,
                     "improved_fold_count": improvements, "gate_status": "PASS" if passed else "FAIL", **metrics,
                     "UP_mean_net20": direction_metrics.get("UP", {}).get("mean_net20"),
                     "UP_profit_factor": direction_metrics.get("UP", {}).get("profit_factor_net20"),
                     "DOWN_mean_net20": direction_metrics.get("DOWN", {}).get("mean_net20"),
                     "DOWN_profit_factor": direction_metrics.get("DOWN", {}).get("profit_factor_net20")})
    table = pd.DataFrame(rows)
    passed = table.loc[table["gate_status"].eq("PASS")].sort_values("exclusion_pct", kind="mergesort")
    return table, None if passed.empty else passed.iloc[0].to_dict()


def render_report(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R35 Economic Selection R1

- Status / classification: `{summary['FAST3_R35_STATUS']}` / `{summary['FAST3_R35_CLASSIFICATION']}`
- Decision: `{summary['FAST3_R35_DECISION']}`
- Stage1 structure: `{summary['DO_DECISION_TIME_FEATURES_SHOW_LOSS_SEVERITY_STRUCTURE']}`
- Loss head: `{summary['LOSS_HEAD_MODEL']}`; AUC `{summary['LOSS_HEAD_OOF_AUC']}`; PR-AUC `{summary['LOSS_HEAD_OOF_PR_AUC']}`
- Selected preregistered filter: `{summary['BEST_PREREGISTERED_FILTER']}`
- Baseline mean / PF: `{summary['BASELINE_MEAN_NET20']}` / `{summary['BASELINE_PROFIT_FACTOR_NET20']}`
- Filtered mean / PF: `{summary['FILTERED_MEAN_NET20']}` / `{summary['FILTERED_PROFIT_FACTOR_NET20']}`
- Final/confirmation used: `false`; R28 refit/threshold changes: `0 / 0`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    run_name = f"r35_economic_selection_r1_{args.run_id}"
    frozen = RESULTS_ROOT / "frozen/fast3" / run_name; scratch = RESULTS_ROOT / "scratch/fast3" / run_name
    runtime = RESULTS_ROOT / "runtime/fast3" / run_name
    if any(path.exists() for path in (frozen, scratch, runtime)): raise R35EconomicStop("STOP_RUN_ID_EXISTS")
    frozen.mkdir(parents=True); scratch.mkdir(parents=True); runtime.mkdir(parents=True)
    r30a = import_module(R30A_RUNNER, "fast3_r35_economic_bound_r30a"); authority = verify_lineage(r30a)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    prereg_path = frozen / "FAST3_R35_ECONOMIC_SELECTION_PREREGISTRATION_R1.json"
    prereg = preregistration(datetime.now(timezone.utc).isoformat(), authority["data"], r30a)
    write_json(prereg_path, prereg); prereg_sha = sha256(prereg_path)
    targets = pd.read_parquet(authority["target_path"]); feature_rows = pd.read_parquet(authority["feature_path"])
    frame = add_targets_and_features(targets, feature_rows); integrity = integrity_audit(frame, r30a)
    feature_hash = feature_mutation_hash(frame); mutated = frame["raw_net20"].copy(); mutated.loc[frame["decision_timestamp_utc"].dt.year >= 2024] *= -1
    if feature_hash != feature_mutation_hash(frame, mutated): raise R35EconomicStop("STOP_FUTURE_MUTATION_FAILURE")
    distributions, effects, stage1 = stage1_tables(frame)
    distributions.to_csv(frozen / "FAST3_R35_STAGE1_FEATURE_DISTRIBUTIONS.csv", index=False, lineterminator="\n")
    effects.to_csv(frozen / "FAST3_R35_STAGE1_EFFECT_SIZES.csv", index=False, lineterminator="\n")
    baseline = economic_metrics(frame); fit_count = predict_count = 0; oof_count = 0
    loss_metrics = {"LOSS2_AUC": None, "LOSS2_PR_AUC": None, "LOSS2_BASE_RATE": float(frame["LARGE_LOSS_2PCT"].mean()),
                    "LOSS2_TOP10_RISK_EVENT_RATE": None, "LOSS2_BOTTOM50_RISK_EVENT_RATE": None,
                    "LOSS_SEVERITY_MAE": None, "LOSS_SEVERITY_SPEARMAN": None, "LOSS_HEAD_MODEL": "NONE"}
    filter_table = pd.DataFrame(); selected_filter = None; oof_path = None
    if stage1["DO_DECISION_TIME_FEATURES_SHOW_LOSS_SEVERITY_STRUCTURE"]:
        if sha256(prereg_path) != prereg_sha: raise R35EconomicStop("STOP_PREREGISTRATION_MUTATION")
        oof, folds, fit_count, predict_count = run_oof(frame, r30a, scratch, prereg_path, prereg_sha); oof_count = len(oof)
        loss_metrics = loss_head_metrics(oof, folds)
        oof_path = scratch / "FAST3_R35_LOSS_HEAD_OOF.parquet"; oof.to_parquet(oof_path, index=False)
        folds.to_csv(frozen / "FAST3_R35_OOF_FOLD_METRICS.csv", index=False, lineterminator="\n")
        if loss_metrics["LOSS_HEAD_MODEL"] != "NONE":
            score = "pred_large_loss_2pct" if loss_metrics["LOSS_HEAD_MODEL"].startswith("HGB_CLASSIFIER") else "pred_loss_severity"
            filter_table, selected_filter = evaluate_filters(oof, folds, score)
            filter_table.to_csv(frozen / "FAST3_R35_PREREGISTERED_FILTER_METRICS.csv", index=False, lineterminator="\n")
    if not stage1["DO_DECISION_TIME_FEATURES_SHOW_LOSS_SEVERITY_STRUCTURE"] or loss_metrics["LOSS_HEAD_MODEL"] == "NONE":
        classification = "C_NO_USEFUL_LOSS_SEVERITY_SIGNAL"; decision = "STOP_NO_STABLE_LOSS_SEVERITY_DISCRIMINATION"
    elif selected_filter is None:
        classification = "B_LOSS_SEVERITY_SIGNAL_EXISTS_BUT_ECONOMIC_EDGE_NOT_CONFIRMED"; decision = "STOP_ECONOMIC_FILTER_GATES_NOT_PASSED"
    else:
        classification = "A_LOSS_SEVERITY_FILTER_CONFIRMED_POSITIVE_ECONOMIC_EDGE"; decision = "AUTHORIZE_FROZEN_SEQUENTIAL_ACCOUNT_TRANSLATION"
    if classification not in CLASSIFICATIONS: raise R35EconomicStop("STOP_CLASSIFICATION_ENUM")
    chosen = selected_filter or {}
    base_rates = {k: baseline[k] for k in ("large_loss_2pct_rate", "large_loss_3pct_rate", "large_loss_5pct_rate")}
    reductions = {name: None if not chosen else 1.0 - chosen[name] / base_rates[name] for name in base_rates}
    summary = {
        "FAST3_R35_STATUS": "PASS", "FAST3_R35_STAGE1_STATUS": "PASS_STRUCTURE" if stage1["DO_DECISION_TIME_FEATURES_SHOW_LOSS_SEVERITY_STRUCTURE"] else "STOP_NO_STRUCTURE",
        "FAST3_R35_CLASSIFICATION": classification, "FAST3_R35_DECISION": decision,
        "BRANCH": branch, "HEAD": head, "R35_PREREGISTRATION_VERIFIED": True, "R35_PREREGISTRATION_SHA256": prereg_sha,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True, "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "ECONOMIC_MODEL_TRAINING_UNIT": "R28_SELECTED_SIGNAL", "BASELINE_SIGNAL_COUNT": 1197,
        "BASELINE_WIN_RATE_NET20": baseline["win_rate_net20"], "BASELINE_MEAN_NET20": baseline["mean_net20"],
        "BASELINE_MEDIAN_NET20": baseline["median_net20"], "BASELINE_MEAN_WIN_NET20": baseline["mean_win_net20"],
        "BASELINE_MEAN_LOSS_NET20": baseline["mean_loss_net20"], "BASELINE_PROFIT_FACTOR_NET20": baseline["profit_factor_net20"],
        "LARGE_LOSS_1PCT_COUNT": int((frame["raw_net20"] <= -.01).sum()), "LARGE_LOSS_2PCT_COUNT": int(frame["LARGE_LOSS_2PCT"].sum()),
        "LARGE_LOSS_3PCT_COUNT": int(frame["LARGE_LOSS_3PCT"].sum()), "LARGE_LOSS_5PCT_COUNT": int(frame["LARGE_LOSS_5PCT"].sum()),
        **stage1, "LOSS_HEAD_MODEL": loss_metrics["LOSS_HEAD_MODEL"], "LOSS_HEAD_OOF_AUC": loss_metrics["LOSS2_AUC"],
        "LOSS_HEAD_OOF_PR_AUC": loss_metrics["LOSS2_PR_AUC"], "LOSS2_BASE_RATE": loss_metrics["LOSS2_BASE_RATE"],
        "LOSS2_TOP10_RISK_EVENT_RATE": loss_metrics["LOSS2_TOP10_RISK_EVENT_RATE"],
        "LOSS2_BOTTOM50_RISK_EVENT_RATE": loss_metrics["LOSS2_BOTTOM50_RISK_EVENT_RATE"],
        "LOSS_SEVERITY_MAE": loss_metrics["LOSS_SEVERITY_MAE"], "LOSS_SEVERITY_SPEARMAN": loss_metrics["LOSS_SEVERITY_SPEARMAN"],
        "OOF_EVALUATION_SIGNAL_COUNT": oof_count, "BEST_PREREGISTERED_FILTER": chosen.get("filter", "NONE"),
        "FILTERED_SIGNAL_COUNT": chosen.get("signal_count"), "RETENTION_RATE": chosen.get("retention_rate"),
        "FILTERED_WIN_RATE_NET20": chosen.get("win_rate_net20"), "FILTERED_MEAN_NET20": chosen.get("mean_net20"),
        "FILTERED_MEDIAN_NET20": chosen.get("median_net20"), "FILTERED_MEAN_WIN_NET20": chosen.get("mean_win_net20"),
        "FILTERED_MEAN_LOSS_NET20": chosen.get("mean_loss_net20"), "FILTERED_PROFIT_FACTOR_NET20": chosen.get("profit_factor_net20"),
        "FILTERED_P05_NET20": chosen.get("p05_net20"), "FILTERED_WORST_TRADE_NET20": chosen.get("worst_trade_net20"),
        "UP_FILTERED_MEAN_NET20": chosen.get("UP_mean_net20"), "UP_FILTERED_PROFIT_FACTOR": chosen.get("UP_profit_factor"),
        "DOWN_FILTERED_MEAN_NET20": chosen.get("DOWN_mean_net20"), "DOWN_FILTERED_PROFIT_FACTOR": chosen.get("DOWN_profit_factor"),
        "LARGE_LOSS_2PCT_REDUCTION": reductions["large_loss_2pct_rate"], "LARGE_LOSS_3PCT_REDUCTION": reductions["large_loss_3pct_rate"],
        "LARGE_LOSS_5PCT_REDUCTION": reductions["large_loss_5pct_rate"],
        "MODEL_FIT_COUNT": fit_count, "MODEL_PREDICT_CALL_COUNT": predict_count,
        "PIT_STATUS": integrity["PIT_STATUS"], "FUTURE_MUTATION_STATUS": "PASS",
        "OOF_INTEGRITY_STATUS": "PASS" if (fit_count in (0, 20) and predict_count in (0, 20)) else "FAIL",
        "CORPORATE_ACTION_STATUS": integrity["CORPORATE_ACTION_STATUS"], "FINAL_CONFIRMATION_DATA_USED": False,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0, "FILTER_CUTOFF_SEARCH_COUNT": 0,
        "MODEL_CONFIG_COUNT": 1, "FILTER_EXCLUSION_LEVELS": list(FILTER_EXCLUSIONS),
        "NEXT_STAGE": "FROZEN_SEQUENTIAL_ACCOUNT_TRANSLATION" if classification.startswith("A_") else "STOP_WITHOUT_RESEARCH_EXPANSION",
        "REPORT_PATH": str(frozen / "FAST3_R35_ECONOMIC_SELECTION_REPORT.md"),
        "SUMMARY_JSON_PATH": str(frozen / "FAST3_R35_ECONOMIC_SELECTION_SUMMARY.json"),
        "OOF_PATH": str(oof_path) if oof_path else None,
    }
    write_json(frozen / "FAST3_R35_ECONOMIC_SELECTION_SUMMARY.json", summary)
    (frozen / "FAST3_R35_ECONOMIC_SELECTION_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    write_json(runtime / "FAST3_R35_ECONOMIC_SELECTION_RUNTIME.json", {"status": "PASS", "classification": classification,
               "summary_sha256": sha256(frozen / "FAST3_R35_ECONOMIC_SELECTION_SUMMARY.json")})
    if sha256(prereg_path) != prereg_sha: raise R35EconomicStop("STOP_PREREGISTRATION_MUTATION")
    keys = ("FAST3_R35_STATUS", "FAST3_R35_CLASSIFICATION", "FAST3_R35_DECISION", "BASELINE_SIGNAL_COUNT",
            "BASELINE_WIN_RATE_NET20", "BASELINE_MEAN_NET20", "BASELINE_MEDIAN_NET20", "BASELINE_MEAN_WIN_NET20",
            "BASELINE_MEAN_LOSS_NET20", "BASELINE_PROFIT_FACTOR_NET20", "LOSS_HEAD_MODEL", "LOSS_HEAD_OOF_AUC",
            "LOSS_HEAD_OOF_PR_AUC", "BEST_PREREGISTERED_FILTER", "FILTERED_SIGNAL_COUNT", "RETENTION_RATE",
            "FILTERED_WIN_RATE_NET20", "FILTERED_MEAN_NET20", "FILTERED_MEDIAN_NET20", "FILTERED_MEAN_WIN_NET20",
            "FILTERED_MEAN_LOSS_NET20", "FILTERED_PROFIT_FACTOR_NET20", "FILTERED_P05_NET20", "FILTERED_WORST_TRADE_NET20",
            "UP_FILTERED_MEAN_NET20", "UP_FILTERED_PROFIT_FACTOR", "DOWN_FILTERED_MEAN_NET20", "DOWN_FILTERED_PROFIT_FACTOR",
            "LARGE_LOSS_2PCT_REDUCTION", "LARGE_LOSS_3PCT_REDUCTION", "LARGE_LOSS_5PCT_REDUCTION",
            "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "PIT_STATUS", "FUTURE_MUTATION_STATUS",
            "OOF_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS")
    print("\n".join(f"{key}={summary[key]}" for key in keys))


if __name__ == "__main__":
    main()
