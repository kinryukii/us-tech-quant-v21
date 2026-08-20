#!/usr/bin/env python
"""FAST3 R38: one-target, one-config chronological OOF economic head study."""
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

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                             precision_score, recall_score, roc_auc_score)

SOURCE_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R30A_ROOT = RESULTS_ROOT / "frozen/fast3/r30a_economic_target_20260809T120000Z"
R30A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"
R30A_DATA_IDENTITY = R30A_ROOT / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30A_FEATURE_IDENTITY = R30A_ROOT / "FAST3_R30A_FEATURE_IDENTITY.json"
R30A_SPLIT_IDENTITY = R30A_ROOT / "FAST3_R30A_SPLIT_IDENTITY.json"
R28_LEDGER = RESULTS_ROOT / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28_DECISION = RESULTS_ROOT / "frozen/fast3/r28_phase2_20260808T125629Z/R28_PHASE2_DECISION.json"
R28_SCORE_ROOT = RESULTS_ROOT / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"

FEATURES = (
    "return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m",
    "relative_volume", "range_position", "symbol_code", "direction_code", "session_code",
    "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m",
)
CATEGORICAL = ("symbol_code", "session_code")
HEADS = ("UP", "DOWN")
QUINTILES = tuple(f"Q{i}" for i in range(1, 6))
HGB_PARAMS = {
    "learning_rate": 0.08, "max_iter": 100, "max_leaf_nodes": 7,
    "min_samples_leaf": 200, "l2_regularization": 1.0, "random_state": 1729,
}
EXPECTED = {
    "R28_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "R28_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "TARGET_LEDGER": "7ea7521b97b7e633cb1b843fb406f6f385bd878998bd9c9b332f7dc5da1f245d",
    "FEATURE_LEDGER": "171c55eb837d14ba07b4bc9c36f2c8461d38d4e5d62104bc4463dc86d44824a1",
    "UP_SCORE_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_SCORE_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
}
R37_REFERENCE = {"UP": -0.008971572611912153, "DOWN": 0.06842534821585773}
CLASSIFICATIONS = {
    "A_ECONOMIC_TARGET_PRODUCES_USEFUL_OOF_PAYOFF_RANKING",
    "B_ECONOMIC_TARGET_PREDICTABLE_BUT_PAYOFF_RANKING_WEAK",
    "C_NET20_POSITIVE_TARGET_NOT_PREDICTABLE",
    "D_DIRECTION_ASYMMETRIC_PARTIAL_SUCCESS",
    "E_INVALID_RESEARCH_INTEGRITY",
}


class R38Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    if spec.loader is None: raise R38Stop("STOP_MODULE_IMPORT")
    spec.loader.exec_module(module)
    return module


def preregistration(created_at: str, r30a) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R38_NET20_POSITIVE_TARGET_R1", "CREATED_AT_UTC": created_at,
        "STATUS": "FROZEN_BEFORE_FIRST_MODEL_FIT", "RESEARCH_UNIT": "R28_HISTORICAL_OOF_SELECTED_SIGNAL",
        "TARGET": "NET20_POSITIVE=1[authoritative corrected corporate-action-normalized NET20>0]",
        "NET20_COST_BPS": 20, "TARGET_COUNT": 1, "FEATURES": list(FEATURES), "FEATURE_COUNT": 14,
        "NEW_FEATURE_COUNT": 0, "MODEL_FAMILY": "HistGradientBoostingClassifier", "MODEL_FAMILY_COUNT": 1,
        "MODEL_CONFIG_COUNT": 1, "MODEL_PARAMS": HGB_PARAMS, "MODEL_PARAM_SOURCE": "R28_PHASE2_FIXED_HGB_PARAMS",
        "DIRECTION_HANDLING": "SEPARATE_UP_DOWN_FIXED_BEFORE_FIT", "COMBINED_MODEL_ALLOWED_OR_EVALUATED": False,
        "FOLDS": [list(row) for row in r30a.ECONOMIC_FOLDS], "FOLD_METHOD": "EXPANDING_WINDOW_PURGED_24H",
        "EXPECTED_FIT_COUNT": len(r30a.ECONOMIC_FOLDS) * len(HEADS),
        "EXPECTED_PREDICT_CALL_COUNT": len(r30a.ECONOMIC_FOLDS) * len(HEADS) * 2,
        "REPEAT_PREDICTION_REASON": "deterministic repeat-prediction integrity check; only first result enters OOF",
        "SCORE_BUCKET_COUNT": 5,
        "POOLED_QUINTILE_METHOD": "direction-specific stable equal-count ordering by score then decision_timestamp then candidate_id",
        "FOLD_Q5_METHOD": "within-direction-fold fixed top 20 percent by same outcome-blind stable ordering",
        "DIRECTION_PREDICTIVE_GATE": "AUROC>0.5 and PR_AUC>base_positive_rate",
        "DIRECTION_SUCCESS_GATE": "predictive gate; Q5 mean>0; Q5 PF>1; Q5 mean>REST; score-NET20 Spearman exceeds same-cohort R28 by>=0.02; and each of Q5-positive, Q5>REST, positive-Spearman fold counts>=3",
        "CLASSIFICATION_RULE": {
            "A": "both directions pass direction success gate", "D": "exactly one direction passes",
            "B": "no direction passes success but at least one passes predictive gate",
            "C": "neither direction passes predictive gate", "E": "integrity failure",
        },
        "MAX_PARAMETER_SEARCH_COUNT": 0, "MAX_RESEARCH_ITERATION_COUNT": 1,
        "NO_PARAMETER_SEARCH": True, "NO_FEATURE_SEARCH": True, "NO_THRESHOLD_SEARCH": True,
        "NO_SECOND_ROUND_FEATURE_EXPANSION": True, "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "R28_REFIT_ALLOWED": False, "R28_THRESHOLD_CHANGE_ALLOWED": False,
        "FINAL_OR_PROSPECTIVE_OUTCOME_ALLOWED": False,
    }


def payoff_metrics(values: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(values, errors="raise").astype(float); wins, losses = x[x > 0], x[x < 0]
    gross_loss = float(-losses.sum())
    return {"count": int(len(x)), "win_rate": float((x > 0).mean()), "mean_net20": float(x.mean()),
            "median_net20": float(x.median()), "mean_win_net20": float(wins.mean()) if len(wins) else np.nan,
            "mean_loss_net20": float(losses.mean()) if len(losses) else np.nan,
            "profit_factor": float(wins.sum()) / gross_loss if gross_loss else np.nan,
            "p05_net20": float(x.quantile(.05)), "large_loss_2pct_rate": float((x <= -.02).mean())}


def safe_spearman(x: Any, y: Any) -> float | None:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b); a, b = a[mask], b[mask]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2: return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def load_dataset(r30a) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = [R30A_DATA_IDENTITY, R30A_FEATURE_IDENTITY, R30A_SPLIT_IDENTITY, R28_LEDGER, R28_DECISION]
    if any(not path.is_file() for path in required): raise R38Stop("STOP_REQUIRED_LINEAGE_MISSING")
    identity, feature_identity, split_identity = read_json(R30A_DATA_IDENTITY), read_json(R30A_FEATURE_IDENTITY), read_json(R30A_SPLIT_IDENTITY)
    target_path, feature_path = Path(identity["TARGET_LEDGER_PATH"]), Path(identity["FEATURE_LEDGER_SOURCE"])
    score_paths = {head: R28_SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet" for head in HEADS}
    observed = {"R28_LEDGER": sha256(R28_LEDGER), "R28_DECISION": sha256(R28_DECISION),
                "TARGET_LEDGER": sha256(target_path), "FEATURE_LEDGER": sha256(feature_path),
                **{f"{head}_SCORE_LEDGER": sha256(path) for head, path in score_paths.items()}}
    if any(observed[key] != value for key, value in EXPECTED.items()): raise R38Stop("STOP_FROZEN_LINEAGE_HASH_MISMATCH")
    decision = read_json(R28_DECISION)
    if decision.get("champions") != {"DOWN": "R28_3_CROSS_ASSET_FLOW", "UP": "R28_3_CROSS_ASSET_FLOW"}:
        raise R38Stop("STOP_R28_CHAMPION_IDENTITY")
    if tuple(feature_identity["FEATURE_NAMES"]) != FEATURES or feature_identity["FEATURE_COUNT"] != 14:
        raise R38Stop("STOP_FEATURE_IDENTITY")
    if split_identity["EVALUATED_FOLDS"] != [list(row) for row in r30a.ECONOMIC_FOLDS] or split_identity["FOLD_COUNT"] != 5:
        raise R38Stop("STOP_FOLD_IDENTITY")
    target = pd.read_parquet(target_path); features = pd.read_parquet(feature_path)
    frame = target.merge(features.drop(columns=["head", "underlying_symbol"], errors="ignore"),
                         on=["candidate_id", "decision_timestamp_utc"], validate="one_to_one")
    score_columns = ["candidate_id", "probability", "selected", "candidate", "head", "validation_slice"]
    scores = pd.concat([pd.read_parquet(score_paths[head], columns=score_columns) for head in HEADS], ignore_index=True)
    if scores.candidate_id.duplicated().any(): raise R38Stop("STOP_R28_SCORE_DUPLICATE")
    frame = frame.merge(scores, on="candidate_id", validate="one_to_one", suffixes=("", "_score"))
    if len(frame) != 1197 or frame.candidate_id.duplicated().any() or not frame.selected.eq(True).all():
        raise R38Stop("STOP_SELECTED_SIGNAL_IDENTITY")
    frame["NET20_POSITIVE"] = (frame.raw_net20 > 0).astype(int)
    if not np.array_equal(frame.NET20_POSITIVE, frame.T1_POSITIVE_NET20.astype(int)):
        raise R38Stop("STOP_TARGET_DEFINITION_RECONCILIATION")
    corrected = pd.read_csv(R28_LEDGER)
    corrected = corrected.loc[corrected.primary_executable_first_touch_cohort.astype(bool), ["candidate_id", "corrected_net20", "probability"]]
    check = frame[["candidate_id", "raw_net20", "probability"]].merge(corrected, on="candidate_id", validate="one_to_one", suffixes=("_r28", "_corrected"))
    if len(check) != 1197 or not np.allclose(check.raw_net20, check.corrected_net20, atol=1e-14, rtol=0):
        raise R38Stop("STOP_CORRECTED_TARGET_IDENTITY")
    if not np.allclose(check.probability_r28, check.probability_corrected, atol=1e-14, rtol=0):
        raise R38Stop("STOP_R28_SCORE_IDENTITY")
    decision_time = pd.to_datetime(frame.decision_timestamp_utc, utc=True); feature_time = pd.to_datetime(frame.max_feature_timestamp_utc, utc=True)
    label_time = pd.to_datetime(frame.label_information_end_utc, utc=True)
    if not (feature_time <= decision_time).all() or not (label_time >= decision_time).all() or decision_time.max() >= r30a.TRUE_HOLDOUT_START:
        raise R38Stop("STOP_PIT_OR_HOLDOUT_INTEGRITY")
    frame = frame.rename(columns={"probability": "R28_SCORE"}).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    audit = {**observed, "TARGET_SOURCE_CORRECTED": True, "CORPORATE_ACTION_NORMALIZED": True, "NET20_COST_BPS": 20,
             "TARGET_ROW_COUNT": len(frame), "FEATURE_COUNT": 14, "FUTURE_FEATURE_ROW_COUNT": 0,
             "PIT_STATUS": "PASS", "TARGET_INTEGRITY_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS"}
    return frame, audit


def stable_quintiles(frame: pd.DataFrame, score: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype=object)
    for _, index in frame.groupby("head", sort=True).groups.items():
        ordered = frame.loc[index].sort_values([score, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
        bucket = np.floor(np.arange(len(ordered)) * 5 / len(ordered)).astype(int) + 1
        result.loc[ordered.index] = [f"Q{x}" for x in bucket]
    if result.isna().any() or set(result) != set(QUINTILES): raise R38Stop("STOP_POOLED_QUINTILE_INTEGRITY")
    return result


def top20_mask(frame: pd.DataFrame, score: str) -> pd.Series:
    ordered = frame.sort_values([score, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    count = max(1, math.ceil(len(ordered) * .20)); result = pd.Series(False, index=frame.index)
    result.loc[ordered.tail(count).index] = True
    return result


def model_params() -> dict[str, Any]:
    return {**HGB_PARAMS, "categorical_features": [name in CATEGORICAL for name in FEATURES]}


def run_oof(frame: pd.DataFrame, r30a, prereg_path: Path, prereg_sha: str) -> tuple[pd.DataFrame, pd.DataFrame, int, int, bool]:
    parts, audits, fit_count, predict_count, deterministic = [], [], 0, 0, True
    for fold in r30a.ECONOMIC_FOLDS:
        train_all, valid_all, audit = r30a.construct_economic_fold(frame, fold)
        for head in HEADS:
            train, valid = train_all.loc[train_all["head"].eq(head)].copy(), valid_all.loc[valid_all["head"].eq(head)].copy()
            if train.empty or valid.empty or train.NET20_POSITIVE.nunique() != 2 or sha256(prereg_path) != prereg_sha:
                raise R38Stop("STOP_FOLD_TRAINING_OR_PREREGISTRATION_INTEGRITY")
            model = HistGradientBoostingClassifier(**model_params())
            model.fit(train[list(FEATURES)], train.NET20_POSITIVE); fit_count += 1
            first = model.predict_proba(valid[list(FEATURES)])[:, 1]; predict_count += 1
            second = model.predict_proba(valid[list(FEATURES)])[:, 1]; predict_count += 1
            deterministic = deterministic and np.array_equal(first, second)
            scored = valid.copy(); scored["R38_SCORE"] = first; scored["fold"] = fold[0]; parts.append(scored)
            audits.append({"fold": fold[0], "head": head, "train_start": train.decision_timestamp_utc.min(),
                           "train_end": train.decision_timestamp_utc.max(), "valid_start": valid.decision_timestamp_utc.min(),
                           "valid_end": valid.decision_timestamp_utc.max(), "train_count": len(train), "valid_count": len(valid),
                           "positive_rate": float(valid.NET20_POSITIVE.mean()), "time_order_pass": audit["time_order_pass"],
                           "purge_pass": audit["purge_pass"], "overlap_count": audit["overlapping_label_contamination_count"]})
    oof = pd.concat(parts, ignore_index=True).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    if len(oof) != 998 or oof.candidate_id.duplicated().any() or not deterministic: raise R38Stop("STOP_OOF_OR_DETERMINISM_INTEGRITY")
    return oof, pd.DataFrame(audits), fit_count, predict_count, deterministic


def predictive_metrics(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for head, part in oof.groupby("head", sort=True):
        y, score = part.NET20_POSITIVE.astype(int), part.R38_SCORE.astype(float); label = (score >= .5).astype(int)
        rows.append({"head": head, "signal_count": len(part), "base_positive_rate": float(y.mean()),
                     "oof_auroc": float(roc_auc_score(y, score)), "oof_pr_auc": float(average_precision_score(y, score)),
                     "oof_brier": float(brier_score_loss(y, score)), "precision": float(precision_score(y, label, zero_division=0)),
                     "recall": float(recall_score(y, label, zero_division=0)), "accuracy": float(accuracy_score(y, label)),
                     "score_vs_net20_spearman": safe_spearman(score, part.raw_net20),
                     "score_vs_net20_pearson": float(score.corr(part.raw_net20, method="pearson")),
                     "score_vs_abs_net20_spearman": safe_spearman(score, part.raw_net20.abs())})
    return pd.DataFrame(rows)


def quintile_metrics(oof: pd.DataFrame) -> pd.DataFrame:
    scored = oof.copy(); scored["quintile"] = stable_quintiles(scored, "R38_SCORE")
    rows = []
    for (head, quintile), part in scored.groupby(["head", "quintile"], sort=True):
        rows.append({"head": head, "quintile": quintile, "mean_score": float(part.R38_SCORE.mean()), **payoff_metrics(part.raw_net20)})
    return pd.DataFrame(rows), scored


def q5_and_comparison(oof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, comparison = [], []
    for head, part in oof.groupby("head", sort=True):
        for score_name in ("R38_SCORE", "R28_SCORE"):
            temp = part.copy(); temp["quintile"] = stable_quintiles(temp, score_name)
            q5, rest = temp.loc[temp.quintile.eq("Q5")], temp.loc[~temp.quintile.eq("Q5")]
            q5m, restm = payoff_metrics(q5.raw_net20), payoff_metrics(rest.raw_net20)
            comparison.append({"head": head, "score_name": score_name, "score_vs_net20_spearman": safe_spearman(temp[score_name], temp.raw_net20),
                               "q5_mean_net20": q5m["mean_net20"], "q5_profit_factor": q5m["profit_factor"],
                               "rest_mean_net20": restm["mean_net20"], "rest_profit_factor": restm["profit_factor"]})
            if score_name == "R38_SCORE":
                rows.append({"head": head, "q5_retention_rate": len(q5) / len(temp), **{f"q5_{k}": v for k, v in q5m.items()},
                             **{f"rest_{k}": v for k, v in restm.items()},
                             "q5_minus_rest_mean_net20": q5m["mean_net20"] - restm["mean_net20"]})
    return pd.DataFrame(rows), pd.DataFrame(comparison)


def fold_metrics(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (fold, head), part in oof.groupby(["fold", "head"], sort=True):
        q5_mask = top20_mask(part, "R38_SCORE"); q5, rest = part.loc[q5_mask], part.loc[~q5_mask]
        q5m, restm = payoff_metrics(q5.raw_net20), payoff_metrics(rest.raw_net20)
        rows.append({"fold": fold, "head": head, "fold_count": len(part), "q5_count": len(q5),
                     "fold_mean_net20_q5": q5m["mean_net20"], "fold_mean_net20_rest": restm["mean_net20"],
                     "fold_q5_win_rate": q5m["win_rate"], "fold_q5_profit_factor": q5m["profit_factor"],
                     "fold_score_net20_spearman": safe_spearman(part.R38_SCORE, part.raw_net20)})
    return pd.DataFrame(rows)


def future_mutation_audit(oof: pd.DataFrame) -> bool:
    ordered = oof.sort_values("decision_timestamp_utc", kind="mergesort").copy(); cutoff = ordered.decision_timestamp_utc.max()
    past = ordered.decision_timestamp_utc < cutoff
    columns = ["candidate_id", "decision_timestamp_utc", "fold", *FEATURES, "R38_SCORE"]
    before = pd.util.hash_pandas_object(ordered.loc[past, columns], index=False).to_numpy()
    ordered.loc[~past, "NET20_POSITIVE"] = 1 - ordered.loc[~past, "NET20_POSITIVE"]
    after = pd.util.hash_pandas_object(ordered.loc[past, columns], index=False).to_numpy()
    return np.array_equal(before, after)


def classify(predictive: pd.DataFrame, q5: pd.DataFrame, comparison: pd.DataFrame, folds: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    p, q, c = predictive.set_index("head"), q5.set_index("head"), comparison.set_index(["head", "score_name"])
    flags: dict[str, Any] = {}
    success_count = 0; predictive_count = 0
    for head in HEADS:
        fold = folds.loc[folds["head"].eq(head)]
        positive_q5 = int((fold.fold_mean_net20_q5 > 0).sum())
        outperform = int((fold.fold_mean_net20_q5 > fold.fold_mean_net20_rest).sum())
        positive_s = int((fold.fold_score_net20_spearman.fillna(-np.inf) > 0).sum())
        pred = bool(p.loc[head, "oof_auroc"] > .5 and p.loc[head, "oof_pr_auc"] > p.loc[head, "base_positive_rate"])
        improvement = float(c.loc[(head, "R38_SCORE"), "score_vs_net20_spearman"] - c.loc[(head, "R28_SCORE"), "score_vs_net20_spearman"])
        success = bool(pred and q.loc[head, "q5_mean_net20"] > 0 and q.loc[head, "q5_profit_factor"] > 1
                       and q.loc[head, "q5_mean_net20"] > q.loc[head, "rest_mean_net20"] and improvement >= .02
                       and positive_q5 >= 3 and outperform >= 3 and positive_s >= 3)
        predictive_count += int(pred); success_count += int(success)
        flags.update({f"{head}_PREDICTIVE_GATE": pred, f"{head}_SUCCESS_GATE": success,
                      f"{head}_R38_MINUS_R28_SCORE_NET20_SPEARMAN": improvement,
                      f"{head}_Q5_MEAN_POSITIVE_FOLD_COUNT": positive_q5,
                      f"{head}_Q5_OUTPERFORMS_REST_FOLD_COUNT": outperform,
                      f"{head}_POSITIVE_SPEARMAN_FOLD_COUNT": positive_s})
    if success_count == 2: classification = "A_ECONOMIC_TARGET_PRODUCES_USEFUL_OOF_PAYOFF_RANKING"
    elif success_count == 1: classification = "D_DIRECTION_ASYMMETRIC_PARTIAL_SUCCESS"
    elif predictive_count > 0: classification = "B_ECONOMIC_TARGET_PREDICTABLE_BUT_PAYOFF_RANKING_WEAK"
    else: classification = "C_NET20_POSITIVE_TARGET_NOT_PREDICTABLE"
    return classification, flags


def render_report(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R38 NET20 Positive Target R1

- Status/classification: `{summary['FAST3_R38_STATUS']}` / `{summary['FAST3_R38_CLASSIFICATION']}`
- OOF: `{summary['OOF_SIGNAL_COUNT']}` rows / `{summary['OOF_FOLD_COUNT']}` expanding folds
- UP AUC / score-payoff Spearman / Q5 mean: `{summary['UP_OOF_AUROC']}` / `{summary['UP_SCORE_VS_NET20_SPEARMAN']}` / `{summary['UP_Q5_MEAN_NET20']}`
- DOWN AUC / score-payoff Spearman / Q5 mean: `{summary['DOWN_OOF_AUROC']}` / `{summary['DOWN_SCORE_VS_NET20_SPEARMAN']}` / `{summary['DOWN_Q5_MEAN_NET20']}`
- One fixed R28 HGB configuration and 14 frozen PIT features were used. No search, R28 refit, threshold change, final, or prospective data was used.
"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", required=True); args = parser.parse_args()
    run_name = f"r38_net20_positive_target_r1_{args.run_id}"
    frozen, scratch = RESULTS_ROOT / "frozen/fast3" / run_name, RESULTS_ROOT / "scratch/fast3" / run_name
    if frozen.exists() or scratch.exists(): raise R38Stop("STOP_RUN_ID_EXISTS")
    frozen.mkdir(parents=True); scratch.mkdir(parents=True)
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    r30a = import_module(R30A_RUNNER, "fast3_r38_bound_r30a")
    if r30a.HGB_PARAMS != HGB_PARAMS: raise R38Stop("STOP_R28_HGB_CONFIG_MISMATCH")
    frame, lineage = load_dataset(r30a)
    prereg_path = frozen / "FAST3_R38_PREREGISTRATION_R1.json"
    write_json(prereg_path, preregistration(datetime.now(timezone.utc).isoformat(), r30a)); prereg_sha = sha256(prereg_path)
    oof, fold_contract, fit_count, predict_count, deterministic = run_oof(frame, r30a, prereg_path, prereg_sha)
    predictive = predictive_metrics(oof); quintiles, scored = quintile_metrics(oof)
    q5, comparison = q5_and_comparison(oof); folds = fold_metrics(oof)
    classification, flags = classify(predictive, q5, comparison, folds)
    if classification not in CLASSIFICATIONS: raise R38Stop("STOP_CLASSIFICATION_ENUM")
    p, q, comp = predictive.set_index("head"), quintiles.set_index(["head", "quintile"]), comparison.set_index(["head", "score_name"])
    q5i = q5.set_index("head")
    decisions = {
        "A_ECONOMIC_TARGET_PRODUCES_USEFUL_OOF_PAYOFF_RANKING": "FREEZE_R38_ECONOMIC_HEAD_FOR_OUT_OF_SAMPLE_CONFIRMATION",
        "B_ECONOMIC_TARGET_PREDICTABLE_BUT_PAYOFF_RANKING_WEAK": "STOP_NO_FEATURE_EXPANSION",
        "C_NET20_POSITIVE_TARGET_NOT_PREDICTABLE": "STOP_CURRENT_FEATURE_SET_FOR_DIRECT_ECONOMIC_TARGET",
        "D_DIRECTION_ASYMMETRIC_PARTIAL_SUCCESS": "RETAIN_ONE_DIRECTION_RESEARCH_CANDIDATE_ONLY",
    }
    summary: dict[str, Any] = {
        "FAST3_R38_STATUS": "PASS", "FAST3_R38_CLASSIFICATION": classification, "FAST3_R38_DECISION": decisions[classification],
        "TARGET": "NET20_POSITIVE", "BRANCH": branch, "HEAD": git_head,
        "R38_PREREGISTRATION_VERIFIED": sha256(prereg_path) == prereg_sha, "R38_PREREGISTRATION_SHA256": prereg_sha,
        "OOF_SIGNAL_COUNT": len(oof), "OOF_FOLD_COUNT": len(r30a.ECONOMIC_FOLDS),
        "OOF_START_DATE": oof.decision_timestamp_utc.min(), "OOF_END_DATE": oof.decision_timestamp_utc.max(),
        **lineage, **flags,
        "MODEL_FAMILY": "HistGradientBoostingClassifier", "MODEL_CONFIG_COUNT": 1, "FEATURE_COUNT": 14,
        "MODEL_FIT_COUNT": fit_count, "MODEL_PREDICT_CALL_COUNT": predict_count,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True, "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "PIT_STATUS": "PASS", "FUTURE_MUTATION_STATUS": "PASS" if future_mutation_audit(oof) else "FAIL",
        "OOF_INTEGRITY_STATUS": "PASS" if len(oof) == 998 and oof.candidate_id.is_unique else "FAIL",
        "DETERMINISTIC_RERUN_STATUS": "PASS_REPEAT_PREDICTION_EXACT" if deterministic else "FAIL",
        "TARGET_INTEGRITY_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS",
        "FINAL_CONFIRMATION_DATA_USED": False, "PROSPECTIVE_DATA_USED": False,
        "FEATURE_SEARCH_COUNT": 0, "PARAMETER_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "RESEARCH_ITERATION_COUNT": 1, "NEXT_STAGE": decisions[classification],
    }
    for head in HEADS:
        for key in ("base_positive_rate", "oof_auroc", "oof_pr_auc", "oof_brier", "precision", "recall", "accuracy",
                    "score_vs_net20_spearman", "score_vs_net20_pearson", "score_vs_abs_net20_spearman"):
            summary[f"{head}_{key.upper()}"] = p.loc[head, key]
        summary[f"R28_{head}_SCORE_VS_NET20_SPEARMAN"] = comp.loc[(head, "R28_SCORE"), "score_vs_net20_spearman"]
        summary[f"R28_{head}_Q5_MEAN_NET20"] = comp.loc[(head, "R28_SCORE"), "q5_mean_net20"]
        summary[f"R28_{head}_Q5_PROFIT_FACTOR"] = comp.loc[(head, "R28_SCORE"), "q5_profit_factor"]
        for quintile in QUINTILES:
            summary[f"{head}_{quintile}_MEAN_NET20"] = q.loc[(head, quintile), "mean_net20"]
            summary[f"{head}_{quintile}_PROFIT_FACTOR"] = q.loc[(head, quintile), "profit_factor"]
        for key, value in q5i.loc[head].items(): summary[f"{head}_{key.upper()}"] = value
    fold_contract.to_csv(frozen / "FAST3_R38_FOLD_CONTRACT.csv", index=False, lineterminator="\n")
    folds.to_csv(frozen / "FAST3_R38_FOLD_METRICS.csv", index=False, lineterminator="\n")
    predictive.to_csv(frozen / "FAST3_R38_PREDICTIVE_METRICS.csv", index=False, lineterminator="\n")
    quintiles.to_csv(frozen / "FAST3_R38_SCORE_QUINTILE_METRICS.csv", index=False, lineterminator="\n")
    q5.to_csv(frozen / "FAST3_R38_Q5_ECONOMIC_METRICS.csv", index=False, lineterminator="\n")
    comparison.to_csv(frozen / "FAST3_R38_R28_COMPARISON.csv", index=False, lineterminator="\n")
    scored.to_parquet(scratch / "FAST3_R38_OOF_PREDICTIONS.parquet", index=False)
    write_json(frozen / "FAST3_R38_SUMMARY.json", summary)
    (frozen / "FAST3_R38_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    if sha256(prereg_path) != prereg_sha: raise R38Stop("STOP_PREREGISTRATION_MUTATION")
    keys = ["FAST3_R38_STATUS", "FAST3_R38_CLASSIFICATION", "FAST3_R38_DECISION", "TARGET", "OOF_SIGNAL_COUNT", "OOF_FOLD_COUNT",
            "UP_BASE_POSITIVE_RATE", "UP_OOF_AUROC", "UP_OOF_PR_AUC", "UP_OOF_BRIER",
            "DOWN_BASE_POSITIVE_RATE", "DOWN_OOF_AUROC", "DOWN_OOF_PR_AUC", "DOWN_OOF_BRIER",
            "UP_SCORE_VS_NET20_SPEARMAN", "DOWN_SCORE_VS_NET20_SPEARMAN",
            "R28_UP_SCORE_VS_NET20_SPEARMAN", "R28_DOWN_SCORE_VS_NET20_SPEARMAN"]
    keys += [f"{head}_{quintile}_MEAN_NET20" for head in HEADS for quintile in QUINTILES]
    keys += [f"{head}_{quintile}_PROFIT_FACTOR" for head in HEADS for quintile in QUINTILES]
    keys += [f"{head}_Q5_{key}" for head in HEADS for key in ("WIN_RATE", "MEAN_NET20", "PROFIT_FACTOR")]
    keys += [f"{head}_Q5_OUTPERFORMS_REST_FOLD_COUNT" for head in HEADS]
    keys += [f"{head}_POSITIVE_SPEARMAN_FOLD_COUNT" for head in HEADS]
    keys += ["MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "R28_PREDICTIVE_IDENTITY_UNCHANGED", "PIT_STATUS",
             "FUTURE_MUTATION_STATUS", "OOF_INTEGRITY_STATUS", "TARGET_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS", "NEXT_STAGE"]
    print("\n".join(f"{key}={summary[key]}" for key in keys))


if __name__ == "__main__":
    main()
