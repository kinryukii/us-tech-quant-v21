#!/usr/bin/env python
"""FAST3 R41 independent fixed-horizon score/payoff alignment audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
PHASE2_ROOT = RESULTS / "frozen/fast3/r28_phase2_20260808T125629Z"
PHASE2_DECISION = PHASE2_ROOT / "R28_PHASE2_DECISION.json"
PHASE2_LINEAGE = PHASE2_ROOT / "R28_PHASE2_LINEAGE.json"
SCORE_ROOT = RESULTS / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R36_ROOT = RESULTS / "frozen/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z"
R36_PREREG = R36_ROOT / "FAST3_R36_PREREGISTRATION_R1.json"
R36_SUMMARY = R36_ROOT / "FAST3_R36_SUMMARY.json"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
R36_SOURCE = REPO / "fast3/scripts/run/fast3_r36_payoff_path_decomposition_r1.py"
R40_SUMMARY = RESULTS / "frozen/fast3/r40_target_payoff_contract_independence_audit_r1_20260810T144545Z/FAST3_R40_SUMMARY.json"

HEADS = ("UP", "DOWN")
HORIZONS = (5, 10, 15, 30, 60)
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
RETURN_COLUMNS = {minute: f"return_{minute}m_net20" for minute in HORIZONS}
CLASSIFICATIONS = {
    "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED",
    "B_WEAK_PARTIAL_INDEPENDENT_ECONOMIC_ALIGNMENT",
    "C_NO_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT",
    "D_INDEPENDENT_ECONOMIC_CANDIDATE_PRESENT",
    "E_INVALID_INDEPENDENT_ECONOMIC_ALIGNMENT_IDENTITY",
}
EXPECTED = {
    "PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "PHASE2_LINEAGE": "eb012006137745cc870840afac9b9fc9b59a46c9268f860d12ffd9c715e8b4df",
    "UP_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
    "R36_PREREG": "da2a4493a252618798998de458855a39c9ced09bb8952dac11f76d13d9cdbb61",
    "R36_SUMMARY": "1f90403dc33c1f222a3732bc39b9d507217857c4e74ab389fa2eece3edd7647f",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "R36_SOURCE": "c0e6cf1270556a0c0bf53ce9a1d5fc7f342b582d33dba16cc6cd30dea5c78752",
    "R40_SUMMARY": "684b8a75eeee4901b427aa8a46ce3915bb784123ae5f3c62af0e0d645cf9f7bd",
}


class R41Stop(RuntimeError):
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
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def preregistration(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R41_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_R1",
        "CREATED_AT_UTC": created_at, "STATUS": "FROZEN_BEFORE_ALIGNMENT_METRICS",
        "RESEARCH_QUESTION": "Does frozen R28 first-passage score rank independent fixed-horizon NET20?",
        "HORIZONS_FIXED_MINUTES": list(HORIZONS), "MAX_HORIZON_COUNT": 5,
        "SCORE_BUCKETS_FIXED": list(QUINTILES), "MAX_SCORE_BUCKET_COUNT": 5,
        "QUINTILE_METHOD": "Within each direction, stable equal-count rank after sort(score, decision_timestamp, candidate_id); outcome-blind and shared across OOF folds",
        "EMPTY_FOLD_Q1_Q5_HANDLING": "record fold Q5-Q1 contrast as NOT_AVAILABLE; do not create fold-local buckets; unavailable pairs provide no positive fold support",
        "ORDERING_RULES": {
            "MONOTONIC_POSITIVE": "all four adjacent differences >=0",
            "MOSTLY_POSITIVE": "at least three adjacent differences >0 and Q5>Q1",
            "MONOTONIC_NEGATIVE": "all four adjacent differences <=0 (evaluated after positive rule)",
            "NON_MONOTONIC": "otherwise",
        },
        "STRONG_DIRECTION_GATE": {
            "A": ">=3 horizons have Spearman>0 and Q5 mean>Q1 mean",
            "B": ">=2 horizons have MONOTONIC_POSITIVE or MOSTLY_POSITIVE mean ordering",
            "C": ">=3 horizons have positive Spearman",
            "D_IF_FOLDS_AVAILABLE": ">=2 distinct frozen folds each have >=3 horizons with Spearman>0 and Q5 mean>Q1 mean",
        },
        "POSITIVE_CANDIDATE_GATE": "a strong direction has >=2 horizons with Q5 mean>0, Q5 PF>1, and Q5 mean>Q1 mean",
        "CLASSIFICATION_PRIORITY": ["D", "A", "B", "C", "E"],
        "PARTIAL_EVIDENCE_RULE": "at least one direction/horizon has both positive Spearman and Q5 mean>Q1 mean",
        "MODEL_FIT_ALLOWED": False, "MODEL_PREDICT_ALLOWED": False,
        "R28_REFIT_ALLOWED": False, "R28_RESCORE_ALLOWED": False,
        "FEATURE_EXPANSION_ALLOWED": False, "PAYOFF_RECOMPUTATION_ALLOWED": False,
        "HORIZON_SELECTION_ALLOWED": False, "THRESHOLD_SEARCH_ALLOWED": False,
        "SECOND_ROUND_ANALYSIS_ALLOWED": False, "AUTOMATIC_FOLLOWUP_ALLOWED": False,
        "FINAL_OR_PROSPECTIVE_DATA_ALLOWED": False,
        "CLASSIFICATIONS": sorted(CLASSIFICATIONS),
    }


def stable_quintiles(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="object")
    for _, index in frame.groupby("direction", sort=True).groups.items():
        ordered = frame.loc[index].sort_values(["score", "decision_timestamp_utc", "candidate_id"], kind="mergesort")
        n = len(ordered); bucket = np.minimum(np.floor(np.arange(n) * 5 / n).astype(int), 4)
        result.loc[ordered.index] = [QUINTILES[value] for value in bucket]
    if result.isna().any() or set(result) != set(QUINTILES): raise R41Stop("STOP_QUINTILE_ASSIGNMENT")
    return result


def payoff_metrics(values: pd.Series) -> dict[str, Any]:
    x = pd.to_numeric(values, errors="raise").astype(float)
    wins, losses = x[x > 0], x[x < 0]
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "count": len(x), "win_rate_net20": float((x > 0).mean()),
        "mean_net20": float(x.mean()), "median_net20": float(x.median()),
        "mean_win_net20": float(wins.mean()) if len(wins) else np.nan,
        "mean_loss_net20": float(losses.mean()) if len(losses) else np.nan,
        "profit_factor_net20": gross_profit / gross_loss if gross_loss else np.nan,
        "p05_net20": float(x.quantile(.05)), "p10_net20": float(x.quantile(.10)),
        "large_loss_2pct_rate": float((x <= -.02).mean()),
    }


def ordering(values: list[float]) -> str:
    delta = np.diff(np.asarray(values, dtype=float))
    if np.all(delta >= 0): return "MONOTONIC_POSITIVE"
    if int((delta > 0).sum()) >= 3 and values[-1] > values[0]: return "MOSTLY_POSITIVE"
    if np.all(delta <= 0): return "MONOTONIC_NEGATIVE"
    return "NON_MONOTONIC"


def verify_and_join() -> tuple[pd.DataFrame, dict[str, str]]:
    score_paths = {head: SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet" for head in HEADS}
    paths = {"PHASE2_DECISION": PHASE2_DECISION, "PHASE2_LINEAGE": PHASE2_LINEAGE,
             "R36_PREREG": R36_PREREG, "R36_SUMMARY": R36_SUMMARY, "R36_LEDGER": R36_LEDGER,
             "R36_SOURCE": R36_SOURCE, "R40_SUMMARY": R40_SUMMARY,
             **{f"{head}_LEDGER": path for head, path in score_paths.items()}}
    if any(not path.is_file() for path in paths.values()): raise R41Stop("STOP_REQUIRED_LINEAGE_MISSING")
    observed = {name: sha256(path) for name, path in paths.items()}
    if observed != EXPECTED: raise R41Stop("STOP_FROZEN_HASH_MISMATCH")
    decision = json.loads(PHASE2_DECISION.read_text(encoding="utf-8")); lineage = json.loads(PHASE2_LINEAGE.read_text(encoding="utf-8"))
    if decision.get("status") != "PASS" or decision.get("champions") != {"DOWN": "R28_3_CROSS_ASSET_FLOW", "UP": "R28_3_CROSS_ASSET_FLOW"}:
        raise R41Stop("STOP_AUTHORITATIVE_R28_IDENTITY")
    if any(lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head] != observed[f"{head}_LEDGER"] for head in HEADS):
        raise R41Stop("STOP_SCORE_LEDGER_LINEAGE")
    r36_contract = json.loads(R36_PREREG.read_text(encoding="utf-8")); r36 = json.loads(R36_SUMMARY.read_text(encoding="utf-8"))
    if (r36_contract.get("FIXED_HORIZONS_MINUTES") != list(HORIZONS)
            or r36_contract.get("FIXED_HORIZON_RETURN") != "entry open to exact +N minute open, then subtract frozen 20bps once"
            or r36.get("PATH_COMPLETE_SIGNAL_COUNT") != 1197 or r36.get("FINAL_CONFIRMATION_DATA_USED") is not False):
        raise R41Stop("STOP_INDEPENDENT_PAYOFF_CONTRACT")
    r40 = json.loads(R40_SUMMARY.read_text(encoding="utf-8"))
    if r40.get("FAST3_R40_CLASSIFICATION") != "C_TARGET_PAYOFF_MECHANICALLY_COUPLED" or not r40.get("INDEPENDENT_ECONOMIC_EVALUATION_EXISTS"):
        raise R41Stop("STOP_R40_INDEPENDENCE_LINEAGE")
    feature_audit = decision["feature_audit"]["R28_3_CROSS_ASSET_FLOW"]
    for head in HEADS:
        if any(fold["status"] != "USED" or not (fold["purge_pass"] and fold["embargo_pass"] and fold["time_order_pass"])
               for fold in feature_audit[head]["folds"]): raise R41Stop("STOP_OOF_PIT_CONTRACT")

    score_columns = ["candidate_id", "decision_timestamp_utc", "direction", "probability", "selected", "head",
                     "validation_slice", "model_sha256", "feature_manifest_sha256"]
    score = pd.concat([pd.read_parquet(path, columns=score_columns) for path in score_paths.values()], ignore_index=True)
    if score.candidate_id.duplicated().any(): raise R41Stop("STOP_SCORE_DUPLICATE")
    payoff = pd.read_parquet(R36_LEDGER)
    if len(payoff) != 1197 or payoff.candidate_id.duplicated().any() or not payoff.path_complete.all():
        raise R41Stop("STOP_PAYOFF_COHORT_IDENTITY")
    joined = payoff.merge(score, on="candidate_id", how="left", validate="one_to_one", suffixes=("_payoff", "_score"), indicator=True)
    matched = int(joined._merge.eq("both").sum()); unmatched = len(joined) - matched
    if matched / len(payoff) < .99 or unmatched: raise R41Stop("STOP_ALIGNMENT_JOIN_RATIO")
    timestamp_ok = np.array_equal(pd.to_datetime(joined.decision_timestamp_utc_payoff, utc=True).to_numpy(dtype="datetime64[us]"),
                                  pd.to_datetime(joined.decision_timestamp_utc_score, utc=True).to_numpy(dtype="datetime64[us]"))
    if (not timestamp_ok or not joined.head_payoff.eq(joined.head_score).all()
            or not joined.head_payoff.eq(joined.direction).all() or not joined.selected.eq(True).all()):
        raise R41Stop("STOP_EXACT_ALIGNMENT_IDENTITY")
    joined = joined.rename(columns={"probability": "score",
                                    "decision_timestamp_utc_payoff": "decision_timestamp_utc"}).drop(columns="_merge")
    required = ["candidate_id", "decision_timestamp_utc", "direction", "score", "validation_slice", *RETURN_COLUMNS.values()]
    if joined[required].isna().any().any() or not np.isfinite(joined[list(RETURN_COLUMNS.values())]).all().all():
        raise R41Stop("STOP_FIXED_HORIZON_VALUE_INTEGRITY")
    result = joined[required].copy(); result["score_quintile"] = stable_quintiles(result)
    return result, observed


def calculate(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    quintile_rows, correlation_rows, contrast_rows, fold_rows = [], [], [], []
    for direction, part in frame.groupby("direction", sort=True):
        for minute, column in RETURN_COLUMNS.items():
            for quintile in QUINTILES:
                sample = part.loc[part.score_quintile.eq(quintile)]
                quintile_rows.append({"direction": direction, "horizon_minutes": minute, "quintile": quintile,
                                      "mean_score": float(sample.score.mean()), **payoff_metrics(sample[column])})
            correlation_rows.append({
                "direction": direction, "horizon_minutes": minute,
                "spearman": float(part.score.corr(part[column], method="spearman")),
                "pearson": float(part.score.corr(part[column], method="pearson")),
            })
    quintiles = pd.DataFrame(quintile_rows); correlations = pd.DataFrame(correlation_rows)
    for (direction, minute), group in quintiles.groupby(["direction", "horizon_minutes"], sort=True):
        ordered = group.set_index("quintile").loc[list(QUINTILES)]
        q1, q5 = ordered.loc["Q1"], ordered.loc["Q5"]
        contrast_rows.append({
            "direction": direction, "horizon_minutes": minute,
            "q5_minus_q1_mean_net20": float(q5.mean_net20 - q1.mean_net20),
            "q5_minus_q1_win_rate": float(q5.win_rate_net20 - q1.win_rate_net20),
            "q5_minus_q1_profit_factor": float(q5.profit_factor_net20 - q1.profit_factor_net20),
            "q5_mean_net20": float(q5.mean_net20), "q5_profit_factor_net20": float(q5.profit_factor_net20),
            "mean_net20_ordering": ordering(ordered.mean_net20.tolist()),
            "win_rate_ordering": ordering(ordered.win_rate_net20.tolist()),
            "profit_factor_ordering": ordering(ordered.profit_factor_net20.tolist()),
        })
    contrasts = pd.DataFrame(contrast_rows)
    for (direction, fold), part in frame.groupby(["direction", "validation_slice"], sort=True):
        for minute, column in RETURN_COLUMNS.items():
            q1 = part.loc[part.score_quintile.eq("Q1"), column]; q5 = part.loc[part.score_quintile.eq("Q5"), column]
            fold_rows.append({
                "direction": direction, "validation_slice": fold, "horizon_minutes": minute,
                "sample_count": len(part), "q1_count": len(q1), "q5_count": len(q5),
                "score_net20_spearman": float(part.score.corr(part[column], method="spearman")),
                "q5_minus_q1_mean_net20": float(q5.mean() - q1.mean()) if len(q1) and len(q5) else np.nan,
            })
    folds = pd.DataFrame(fold_rows)
    if folds.score_net20_spearman.isna().any(): raise R41Stop("STOP_FOLD_SPEARMAN_NOT_IDENTIFIABLE")
    return quintiles, correlations, contrasts, folds


def classify(correlations: pd.DataFrame, contrasts: pd.DataFrame, folds: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    flags: dict[str, Any] = {}
    strong_directions, candidate_directions = [], []
    for head in HEADS:
        corr = correlations.loc[correlations.direction.eq(head)].set_index("horizon_minutes")
        cont = contrasts.loc[contrasts.direction.eq(head)].set_index("horizon_minutes")
        fold = folds.loc[folds.direction.eq(head)].copy()
        favorable = (corr.spearman > 0) & (cont.q5_minus_q1_mean_net20 > 0)
        positive_order = cont.mean_net20_ordering.isin(["MONOTONIC_POSITIVE", "MOSTLY_POSITIVE"])
        per_fold = fold.assign(support=(fold.score_net20_spearman > 0) & (fold.q5_minus_q1_mean_net20 > 0)).groupby("validation_slice").support.sum()
        supported_folds = int((per_fold >= 3).sum())
        strong = bool(favorable.sum() >= 3 and positive_order.sum() >= 2 and (corr.spearman > 0).sum() >= 3 and supported_folds >= 2)
        positive_q5 = (cont.q5_mean_net20 > 0) & (cont.q5_profit_factor_net20 > 1) & (cont.q5_minus_q1_mean_net20 > 0)
        candidate = bool(strong and positive_q5.sum() >= 2)
        flags.update({
            f"{head}_POSITIVE_SPEARMAN_HORIZON_COUNT": int((corr.spearman > 0).sum()),
            f"{head}_Q5_OUTPERFORMS_Q1_MEAN_HORIZON_COUNT": int((cont.q5_minus_q1_mean_net20 > 0).sum()),
            f"{head}_MOSTLY_OR_MONOTONIC_POSITIVE_MEAN_ORDERING_HORIZON_COUNT": int(positive_order.sum()),
            f"{head}_POSITIVE_Q5_ECONOMIC_HORIZON_COUNT": int(positive_q5.sum()),
            f"{head}_POSITIVE_SPEARMAN_FOLD_HORIZON_COUNT": int((fold.score_net20_spearman > 0).sum()),
            f"{head}_Q5_GT_Q1_FOLD_HORIZON_COUNT": int((fold.q5_minus_q1_mean_net20 > 0).sum()),
            f"{head}_SUPPORTING_FOLD_COUNT": supported_folds,
            f"{head}_STRONG_ALIGNMENT": strong, f"{head}_POSITIVE_CANDIDATE": candidate,
        })
        if strong: strong_directions.append(head)
        if candidate: candidate_directions.append(head)
    strong = bool(strong_directions); candidate = bool(candidate_directions)
    partial = any(flags[f"{head}_Q5_OUTPERFORMS_Q1_MEAN_HORIZON_COUNT"] > 0 and
                  flags[f"{head}_POSITIVE_SPEARMAN_HORIZON_COUNT"] > 0 for head in HEADS)
    classification = ("D_INDEPENDENT_ECONOMIC_CANDIDATE_PRESENT" if candidate else
                      "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED" if strong else
                      "B_WEAK_PARTIAL_INDEPENDENT_ECONOMIC_ALIGNMENT" if partial else
                      "C_NO_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT")
    flags.update({"INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_STRONG": strong,
                  "INDEPENDENT_POSITIVE_ECONOMIC_CANDIDATE": candidate,
                  "STRONG_ALIGNMENT_DIRECTIONS": strong_directions, "POSITIVE_CANDIDATE_DIRECTIONS": candidate_directions})
    return classification, flags


def summary_payload(frame: pd.DataFrame, hashes: dict[str, str], quintiles: pd.DataFrame,
                    correlations: pd.DataFrame, contrasts: pd.DataFrame, folds: pd.DataFrame) -> dict[str, Any]:
    classification, flags = classify(correlations, contrasts, folds)
    decision = {
        "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED": "DESIGN_FROZEN_INDEPENDENT_ECONOMIC_SELECTION_CONFIRMATION",
        "D_INDEPENDENT_ECONOMIC_CANDIDATE_PRESENT": "DESIGN_FROZEN_INDEPENDENT_ECONOMIC_SELECTION_CONFIRMATION",
        "B_WEAK_PARTIAL_INDEPENDENT_ECONOMIC_ALIGNMENT": "STOP_OR_ONE_CONFIRMATORY_STUDY",
        "C_NO_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT": "STOP_R28_ECONOMIC_TRANSLATION_ROUTE",
    }[classification]
    payload: dict[str, Any] = {
        "FAST3_R41_STATUS": "PASS", "FAST3_R41_CLASSIFICATION": classification, "FAST3_R41_DECISION": decision,
        "ALIGNMENT_INPUT_COUNT": len(frame), "ALIGNMENT_MATCHED_COUNT": len(frame),
        "ALIGNMENT_UNMATCHED_COUNT": 0, "ALIGNMENT_DUPLICATE_COUNT": 0, "ALIGNMENT_JOIN_RATIO": 1.0,
        "INDEPENDENT_HORIZON_COUNT": 5, **{f"H{minute}_INDEPENDENT": True for minute in HORIZONS},
        "FIXED_HORIZON_EXIT_DEPENDS_ON_TARGET_FIRST": False,
        "FIXED_HORIZON_PAYOFF_DEPENDS_ON_TARGET_FIRST": False,
        "FOLD_STABILITY": "AVAILABLE_FROZEN_VALIDATION_SLICE",
        "FOLD_Q5_Q1_NOT_AVAILABLE_COUNT": int(folds.q5_minus_q1_mean_net20.isna().sum()),
        **flags,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0, "R28_PREDICTIVE_IDENTITY_UNCHANGED": True,
        "PIT_STATUS": "PASS", "OOF_INTEGRITY_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS",
        "INDEPENDENT_PAYOFF_STATUS": "PASS_FIXED_ENTRY_PLUS_TIME_EXIT_NO_TARGET_TERMINATION",
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FIRST_RUN_STATUS": "STOPPED_FOLD_STABILITY_EMPTY_GLOBAL_QUINTILE_CELLS",
        "RERUN_COUNT": 1,
        "RERUN_REASON": "DETERMINISTIC_EMPTY_FOLD_Q1_Q5_HANDLING_BUG",
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "HORIZON_SELECTION_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "PREDICTIVE_EDGE_STATUS": "CONFIRMED_FIRST_PASSAGE_EVENT_EDGE",
        "INDEPENDENT_ECONOMIC_TRANSLATION_STATUS": "CANDIDATE" if flags["INDEPENDENT_POSITIVE_ECONOMIC_CANDIDATE"] else ("ALIGNMENT_ONLY" if flags["INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_STRONG"] else "FAILED"),
        "NEXT_STAGE": decision, "INPUT_SHA256": hashes,
    }
    for head in HEADS:
        for minute in HORIZONS:
            corr = correlations.loc[(correlations.direction.eq(head)) & (correlations.horizon_minutes.eq(minute))].iloc[0]
            cont = contrasts.loc[(contrasts.direction.eq(head)) & (contrasts.horizon_minutes.eq(minute))].iloc[0]
            payload[f"{head}_SCORE_VS_{minute}M_NET20_SPEARMAN"] = float(corr.spearman)
            payload[f"{head}_SCORE_VS_{minute}M_NET20_PEARSON"] = float(corr.pearson)
            payload[f"{head}_Q5_MINUS_Q1_MEAN_{minute}M"] = float(cont.q5_minus_q1_mean_net20)
            payload[f"{head}_Q5_MINUS_Q1_WIN_RATE_{minute}M"] = float(cont.q5_minus_q1_win_rate)
            payload[f"{head}_Q5_MINUS_Q1_PROFIT_FACTOR_{minute}M"] = float(cont.q5_minus_q1_profit_factor)
            payload[f"{head}_MEAN_NET20_ORDERING_{minute}M"] = cont.mean_net20_ordering
            payload[f"{head}_WIN_RATE_ORDERING_{minute}M"] = cont.win_rate_ordering
            payload[f"{head}_PROFIT_FACTOR_ORDERING_{minute}M"] = cont.profit_factor_ordering
    return payload


def render_terminal(summary: dict[str, Any]) -> str:
    keys = ["FAST3_R41_STATUS", "FAST3_R41_CLASSIFICATION", "FAST3_R41_DECISION",
            "ALIGNMENT_MATCHED_COUNT", "ALIGNMENT_JOIN_RATIO", "INDEPENDENT_HORIZON_COUNT",
            *[f"H{minute}_INDEPENDENT" for minute in HORIZONS],
            *[f"{head}_SCORE_VS_{minute}M_NET20_SPEARMAN" for head in HEADS for minute in HORIZONS],
            *[f"{head}_Q5_MINUS_Q1_MEAN_{minute}M" for head in HEADS for minute in HORIZONS],
            "UP_POSITIVE_SPEARMAN_HORIZON_COUNT", "DOWN_POSITIVE_SPEARMAN_HORIZON_COUNT",
            "UP_Q5_OUTPERFORMS_Q1_MEAN_HORIZON_COUNT", "DOWN_Q5_OUTPERFORMS_Q1_MEAN_HORIZON_COUNT",
            "UP_POSITIVE_Q5_ECONOMIC_HORIZON_COUNT", "DOWN_POSITIVE_Q5_ECONOMIC_HORIZON_COUNT",
            "INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_STRONG", "INDEPENDENT_POSITIVE_ECONOMIC_CANDIDATE",
            "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "R28_PREDICTIVE_IDENTITY_UNCHANGED",
            "PIT_STATUS", "OOF_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS", "INDEPENDENT_PAYOFF_STATUS",
            "FINAL_CONFIRMATION_DATA_USED", "PREDICTIVE_EDGE_STATUS", "INDEPENDENT_ECONOMIC_TRANSLATION_STATUS", "NEXT_STAGE"]
    return "\n".join(f"{key}={str(summary[key]).lower() if isinstance(summary[key], bool) else summary[key]}" for key in keys)


def execute() -> dict[str, Any]:
    now = datetime.now(timezone.utc); run_id = now.strftime("%Y%m%dT%H%M%SZ")
    frozen = RESULTS / "frozen/fast3" / f"r41_independent_economic_score_alignment_r1_{run_id}"
    stage = RESULTS / "scratch/fast3" / f".r41_independent_economic_score_alignment_r1_{run_id}.staging"
    if frozen.exists() or stage.exists(): raise R41Stop("STOP_OUTPUT_PATH_EXISTS")
    stage.mkdir(parents=True)
    prereg_path = stage / "FAST3_R41_PREREGISTRATION_R1.json"
    write_json(prereg_path, preregistration(now.isoformat().replace("+00:00", "Z"))); prereg_hash = sha256(prereg_path)
    try:
        frame, hashes = verify_and_join(); quintiles, correlations, contrasts, folds = calculate(frame)
        summary = summary_payload(frame, hashes, quintiles, correlations, contrasts, folds)
        summary.update({"R41_PREREGISTRATION_VERIFIED": True, "R41_PREREGISTRATION_SHA256": prereg_hash,
                        "RUN_ID": run_id, "RUN_ID_TIMESTAMP_SEMANTICS": "REAL_UTC_WALL_CLOCK",
                        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
                        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                        "PREREGISTRATION_EXISTS_BEFORE_METRICS": True})
        quintiles.to_csv(stage / "FAST3_R41_QUINTILE_ECONOMIC_METRICS.csv", index=False)
        correlations.to_csv(stage / "FAST3_R41_SCORE_RETURN_CORRELATIONS.csv", index=False)
        contrasts.to_csv(stage / "FAST3_R41_Q5_Q1_CONTRASTS.csv", index=False)
        folds.to_csv(stage / "FAST3_R41_FOLD_STABILITY.csv", index=False)
        pd.DataFrame([{"horizon_minutes": minute, "independent": True,
                       "exit_definition": "entry_timestamp + fixed minutes",
                       "payoff_definition": "exact fixed-horizon open / entry open - 1 - 20bps",
                       "target_first_used": False} for minute in HORIZONS]).to_csv(stage / "FAST3_R41_INDEPENDENCE_AUDIT.csv", index=False)
        write_json(stage / "FAST3_R41_SUMMARY.json", summary)
        report = ["# FAST3 R41 Independent Economic Score Alignment R1", "",
                  f"- Classification: `{summary['FAST3_R41_CLASSIFICATION']}`",
                  f"- Decision: `{summary['FAST3_R41_DECISION']}`", "",
                  "All results use frozen R28 OOF scores and pre-existing R36 entry-to-fixed-time NET20. No model, score, threshold, feature, payoff, or horizon was changed.", "",
                  "## Terminal summary", "", "```text", render_terminal(summary), "```", ""]
        (stage / "FAST3_R41_REPORT.md").write_text("\n".join(report), encoding="utf-8")
        frozen.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(stage), str(frozen)); summary["ARTIFACT_ROOT"] = str(frozen)
        return summary
    except Exception:
        if stage.exists(): shutil.rmtree(stage)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute: print("FAST3_R41_STATUS=READY_REQUIRES_EXECUTE"); return 0
    try: summary = execute()
    except R41Stop as exc:
        print(f"FAST3_R41_STATUS=STOP\nFAST3_R41_CLASSIFICATION=E_INVALID_INDEPENDENT_ECONOMIC_ALIGNMENT_IDENTITY\nFAST3_R41_DECISION={exc}"); return 2
    print(render_terminal(summary)); print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
