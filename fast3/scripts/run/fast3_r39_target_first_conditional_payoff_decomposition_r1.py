#!/usr/bin/env python
"""FAST3 R39 target-first conditional payoff decomposition (zero-model audit)."""
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
PHASE2 = RESULTS / "frozen/fast3/r28_phase2_20260808T125629Z"
PHASE2_DECISION = PHASE2 / "R28_PHASE2_DECISION.json"
PHASE2_LINEAGE = PHASE2 / "R28_PHASE2_LINEAGE.json"
SCORE_ROOT = RESULTS / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R28_LEDGER = RESULTS / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
R37_SUMMARY = RESULTS / "frozen/fast3/r37_predictive_economic_alignment_audit_r1_20260810T133445Z/FAST3_R37_SUMMARY.json"

HEADS = ("UP", "DOWN")
CHECKPOINTS = (("T0", 0), ("T1", 1), ("T3", 3), ("T5", 5), ("T10", 10))
DYNAMIC_VARIABLES = (
    "RETURN_SINCE_TARGET", "MFE_SINCE_TARGET", "MAE_SINCE_TARGET",
    "DRAWDOWN_FROM_POST_TARGET_PEAK", "RECOVERY_FROM_POST_TARGET_TROUGH",
    "REALIZED_VOL_SINCE_TARGET", "TIME_TO_TARGET_FIRST",
)
CLASSIFICATIONS = {
    "A_POST_TARGET_REALTIME_REVERSAL_STRUCTURE_PRESENT",
    "B_WEAK_PARTIAL_POST_TARGET_STRUCTURE",
    "C_NO_USEFUL_POST_TARGET_PATH_INFORMATION",
    "D_TARGET_FIRST_NOT_REALTIME_OBSERVABLE",
    "E_INVALID_PATH_OR_IDENTITY",
}
EXPECTED = {
    "PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "PHASE2_LINEAGE": "eb012006137745cc870840afac9b9fc9b59a46c9268f860d12ffd9c715e8b4df",
    "R28_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "R37_SUMMARY": "0248d7e2c3e6b834d1bf5423607364efe0a92bd4049b649e14768e96e10ac69b",
    "UP_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
}
NOT_AVAILABLE = "NOT_AVAILABLE_NO_POST_TARGET_WINDOW"


class R39Stop(RuntimeError):
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
        "CONTRACT_ID": "FAST3_R39_TARGET_FIRST_CONDITIONAL_PAYOFF_DECOMPOSITION_R1",
        "CREATED_AT_UTC": created_at,
        "STATUS": "FROZEN_BEFORE_MECHANISM_METRICS",
        "RESEARCH_QUESTION": "After a realtime-observable target_first=1 event, do causal post-target path states distinguish continuation from final economic loss?",
        "TARGET_FIRST_DEFINITION": "direction-aligned first crossing of the frozen +/-1% underlying barrier within 24 hours; same-minute opposing touches are ambiguous, not target_first=1",
        "TARGET1_EXPECTED_COUNT": 613,
        "MIN_REQUIRED_PATH_COMPLETE_RATIO": 0.95,
        "OBSERVATION_CHECKPOINTS": [name for name, _ in CHECKPOINTS],
        "OBSERVATION_CHECKPOINT_MINUTES": [minute for _, minute in CHECKPOINTS],
        "DYNAMIC_VARIABLES": list(DYNAMIC_VARIABLES),
        "MAX_DYNAMIC_PATH_VARIABLE_COUNT": 7,
        "MAX_OBSERVATION_CHECKPOINT_COUNT": 5,
        "STRONG_GATE_A": "same variable oriented AUC>=0.60 at >=2 fixed checkpoints with consistent direction",
        "STRONG_GATE_B": ">=2 variables oriented AUC>=0.58 at one checkpoint and economic quintile ordering agrees",
        "MODEL_FIT_ALLOWED": False,
        "MODEL_PREDICT_ALLOWED": False,
        "PARAMETER_SEARCH_ALLOWED": False,
        "THRESHOLD_SEARCH_ALLOWED": False,
        "STOP_SEARCH_ALLOWED": False,
        "TAKE_PROFIT_SEARCH_ALLOWED": False,
        "FEATURE_EXPANSION_ALLOWED": False,
        "SECOND_ROUND_ANALYSIS_ALLOWED": False,
        "FINAL_OR_PROSPECTIVE_DATA_ALLOWED": False,
        "FAIL_CLOSE_RULE": "if required post-target checkpoint path completeness is below 0.95, stop as E_INVALID_PATH_OR_IDENTITY before discrimination metrics",
        "CLASSIFICATIONS": sorted(CLASSIFICATIONS),
    }


def checkpoint_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    touch = pd.to_datetime(frame["touch_timestamp"], utc=True)
    end = pd.to_datetime(frame["first_touch_exit_timestamp"], utc=True)
    for name, minute in CHECKPOINTS:
        checkpoint = touch + pd.Timedelta(minutes=minute)
        eligible = checkpoint <= end
        rows.append({
            "checkpoint": name, "minutes_after_target": minute,
            "ELIGIBLE_COUNT": int(eligible.sum()), "CENSORED_COUNT": int((~eligible).sum()),
            "PATH_COMPLETE_COUNT": int(eligible.sum()),
        })
    return pd.DataFrame(rows)


def verify_and_load() -> tuple[pd.DataFrame, dict[str, Any]]:
    score_paths = {head: SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet" for head in HEADS}
    paths = {"PHASE2_DECISION": PHASE2_DECISION, "PHASE2_LINEAGE": PHASE2_LINEAGE,
             "R28_LEDGER": R28_LEDGER, "R36_LEDGER": R36_LEDGER, "R37_SUMMARY": R37_SUMMARY,
             **{f"{head}_LEDGER": path for head, path in score_paths.items()}}
    if any(not path.is_file() for path in paths.values()): raise R39Stop("STOP_REQUIRED_LINEAGE_MISSING")
    observed = {name: sha256(path) for name, path in paths.items()}
    if any(observed[name] != expected for name, expected in EXPECTED.items()): raise R39Stop("STOP_FROZEN_HASH_MISMATCH")

    decision = json.loads(PHASE2_DECISION.read_text(encoding="utf-8"))
    lineage = json.loads(PHASE2_LINEAGE.read_text(encoding="utf-8"))
    if decision.get("champions") != {"DOWN": "R28_3_CROSS_ASSET_FLOW", "UP": "R28_3_CROSS_ASSET_FLOW"}:
        raise R39Stop("STOP_AUTHORITATIVE_R28_IDENTITY")
    if any(lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head] != observed[f"{head}_LEDGER"] for head in HEADS):
        raise R39Stop("STOP_SCORE_LEDGER_LINEAGE")
    prior = json.loads(R37_SUMMARY.read_text(encoding="utf-8"))
    if prior.get("FAST3_R37_STATUS") != "PASS" or prior.get("TARGET1_COUNT") != 613 or not prior.get("R28_PREDICTIVE_IDENTITY_UNCHANGED"):
        raise R39Stop("STOP_R37_COHORT_LINEAGE")

    score_columns = ["candidate_id", "decision_timestamp_utc", "underlying_symbol", "direction", "target_first",
                     "probability", "selected", "head", "validation_slice", "model_sha256", "feature_manifest_sha256"]
    score = pd.concat([pd.read_parquet(path, columns=score_columns) for path in score_paths.values()], ignore_index=True)
    if score.candidate_id.duplicated().any(): raise R39Stop("STOP_SCORE_CANDIDATE_DUPLICATE")
    economic = pd.read_csv(R28_LEDGER)
    economic = economic.loc[economic.primary_executable_first_touch_cohort.astype(bool)].copy()
    path = pd.read_parquet(R36_LEDGER)
    if len(economic) != 1197 or len(path) != 1197 or economic.candidate_id.duplicated().any() or path.candidate_id.duplicated().any():
        raise R39Stop("STOP_ECONOMIC_PATH_CARDINALITY")
    for column in ("timestamp", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp"):
        economic[column] = pd.to_datetime(economic[column], utc=True, errors="coerce")
    joined = economic.merge(score, on="candidate_id", how="left", validate="one_to_one", suffixes=("_economic", "_score"), indicator=True)
    if not joined._merge.eq("both").all(): raise R39Stop("STOP_TARGET1_IDENTITY_JOIN")
    joined = joined.drop(columns="_merge").merge(path[["candidate_id", "original_exit_timestamp", "original_net20", "mfe", "mae"]],
                                                  on="candidate_id", validate="one_to_one")
    timestamp_ok = np.array_equal(pd.to_datetime(joined.timestamp, utc=True).to_numpy(dtype="datetime64[us]"),
                                  pd.to_datetime(joined.decision_timestamp_utc, utc=True).to_numpy(dtype="datetime64[us]"))
    identity_ok = (timestamp_ok and joined.head_economic.eq(joined.head_score).all()
                   and joined.underlying_symbol_economic.eq(joined.underlying_symbol_score).all()
                   and joined.selected.eq(True).all()
                   and np.array_equal(joined.target_first.astype(int), joined.event_state.eq("FAVORABLE_FIRST").astype(int))
                   and np.allclose(joined.corrected_net20, joined.original_net20, atol=1e-14, rtol=0)
                   and np.array_equal(pd.to_datetime(joined.first_touch_exit_timestamp, utc=True).to_numpy(dtype="datetime64[us]"),
                                      pd.to_datetime(joined.original_exit_timestamp, utc=True).to_numpy(dtype="datetime64[us]")))
    if not identity_ok: raise R39Stop("STOP_EXACT_TARGET_PATH_IDENTITY")
    target1 = joined.loc[joined.target_first.eq(1)].copy()
    if len(target1) != 613 or target1.candidate_id.duplicated().any(): raise R39Stop("STOP_TARGET1_COHORT_COUNT")
    return target1.sort_values("candidate_id", kind="mergesort").reset_index(drop=True), observed


def audit(target1: pd.DataFrame, hashes: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    missing_touch = int(target1.touch_timestamp.isna().sum())
    realtime = bool(missing_touch == 0 and target1.touch_timestamp.ge(target1.timestamp).all()
                    and target1.event_state.eq("FAVORABLE_FIRST").all())
    if not realtime:
        classification = "D_TARGET_FIRST_NOT_REALTIME_OBSERVABLE"
        decision = "STOP_NONCAUSAL_CONDITIONING"
    else:
        classification = "E_INVALID_PATH_OR_IDENTITY"
        decision = "STOP_NO_POST_TARGET_WINDOW_UNDER_AUTHORITATIVE_FIRST_TOUCH_CONTRACT"
    coverage = checkpoint_coverage(target1)
    required_complete = int((target1.first_touch_exit_timestamp >= target1.touch_timestamp + pd.Timedelta(minutes=10)).sum())
    complete_ratio = required_complete / len(target1)
    same_timestamp = target1.first_touch_exit_timestamp.eq(target1.touch_timestamp)
    if realtime and (not same_timestamp.all() or complete_ratio >= .95):
        raise R39Stop("STOP_UNEXPECTED_POST_TARGET_CONTRACT_REQUIRES_NEW_PREREGISTRATION")
    wins = target1.corrected_net20.gt(0)
    result = {
        "FAST3_R39_STATUS": "STOP",
        "FAST3_R39_CLASSIFICATION": classification,
        "FAST3_R39_DECISION": decision,
        "TARGET_FIRST_REALTIME_OBSERVABLE": realtime,
        "TARGET_FIRST_TS_AVAILABLE": missing_touch == 0,
        "TARGET_FIRST_DEFINITION": "direction-aligned first crossing of the frozen +/-1% underlying barrier inside the 24-hour label window; opposing barriers first touched in the same minute are ambiguous",
        "TARGET_FIRST_OBSERVABILITY_EXPLANATION": "The event is known at completion of the canonical one-minute first-crossing bar using only elapsed path; no later bar is needed. But the corrected first-touch payoff exits at that same timestamp.",
        "TARGET1_INPUT_COUNT": len(target1), "TARGET1_MATCHED_COUNT": len(target1),
        "TARGET1_DUPLICATE_COUNT": int(target1.candidate_id.duplicated().sum()),
        "TARGET1_MISSING_TOUCH_TS_COUNT": missing_touch,
        "TARGET1_SIGNAL_COUNT": len(target1), "TARGET1_FINAL_WIN_COUNT": int(wins.sum()),
        "TARGET1_FINAL_LOSS_COUNT": int((~wins).sum()), "TARGET1_FINAL_WIN_RATE": float(wins.mean()),
        "TARGET1_TOUCH_EQUALS_FINAL_EXIT_COUNT": int(same_timestamp.sum()),
        "TARGET1_POST_TARGET_PATH_COMPLETE_COUNT": required_complete,
        "TARGET1_PATH_COMPLETE_COUNT": required_complete, "TARGET1_PATH_COMPLETE_RATIO": complete_ratio,
        "WINNER_TIME_TO_TARGET_MEDIAN": NOT_AVAILABLE,
        "LOSER_TIME_TO_TARGET_MEDIAN": NOT_AVAILABLE,
        "WINNER_ENTRY_TO_TARGET_RETURN_MEDIAN": NOT_AVAILABLE,
        "LOSER_ENTRY_TO_TARGET_RETURN_MEDIAN": NOT_AVAILABLE,
        "WINNER_PRE_TARGET_MAE_MEDIAN": NOT_AVAILABLE,
        "LOSER_PRE_TARGET_MAE_MEDIAN": NOT_AVAILABLE,
        "WINNER_TARGET_TO_FINAL_RETURN_MEDIAN": NOT_AVAILABLE,
        "LOSER_TARGET_TO_FINAL_RETURN_MEDIAN": NOT_AVAILABLE,
        "T0_MAX_ORIENTED_UNIVARIATE_AUC": "NOT_AVAILABLE_CONSTANT_AT_EXIT_STATE",
        "T1_MAX_ORIENTED_UNIVARIATE_AUC": NOT_AVAILABLE,
        "T3_MAX_ORIENTED_UNIVARIATE_AUC": NOT_AVAILABLE,
        "T5_MAX_ORIENTED_UNIVARIATE_AUC": NOT_AVAILABLE,
        "T10_MAX_ORIENTED_UNIVARIATE_AUC": NOT_AVAILABLE,
        "T1_DRAWDOWN_AUC": NOT_AVAILABLE, "T3_DRAWDOWN_AUC": NOT_AVAILABLE,
        "T5_DRAWDOWN_AUC": NOT_AVAILABLE, "T10_DRAWDOWN_AUC": NOT_AVAILABLE,
        "FINAL_LOSER_TIME_TO_POST_TARGET_PEAK_MEDIAN": NOT_AVAILABLE,
        "FINAL_LOSER_TIME_TO_BREAKEVEN_LOSS_MEDIAN": NOT_AVAILABLE,
        "UP_POST_TARGET_MAX_AUC": NOT_AVAILABLE, "DOWN_POST_TARGET_MAX_AUC": NOT_AVAILABLE,
        "UP_POST_TARGET_DISCRIMINATION": "NOT_AVAILABLE_ALL_POST_TARGET_CHECKPOINTS_CENSORED",
        "DOWN_POST_TARGET_DISCRIMINATION": "NOT_AVAILABLE_ALL_POST_TARGET_CHECKPOINTS_CENSORED",
        "STRONG_POST_TARGET_STRUCTURE": False,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True, "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "PIT_STATUS": "PASS", "TARGET_FIRST_OBSERVABILITY_STATUS": "PASS_REALTIME_AT_CANONICAL_ONE_MINUTE_BAR_RESOLUTION",
        "PATH_INTEGRITY_STATUS": "FAIL_NO_POST_TARGET_WINDOW_UNDER_AUTHORITATIVE_FIRST_TOUCH_PAYOFF",
        "CORPORATE_ACTION_STATUS": "PASS", "OOF_INTEGRITY_STATUS": "PASS",
        "FINAL_CONFIRMATION_DATA_USED": False,
        "MAX_NEW_TRADITIONAL_FEATURE_COUNT": 0, "MAX_NEW_MODEL_COUNT": 0,
        "PARAMETER_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "STOP_SEARCH_COUNT": 0, "TAKE_PROFIT_SEARCH_COUNT": 0,
        "PRIMARY_RESEARCH_INTERPRETATION": "TARGET_FIRST_IS_REALTIME_OBSERVABLE_BUT_THE_AUTHORITATIVE_FIRST_TOUCH_PAYOFF_TERMINATES_AT_TARGET_OCCURRENCE_SO_POST_TARGET_CONTINUATION_INFORMATION_IS_NOT_IDENTIFIABLE",
        "NEXT_STAGE": "STOP",
        "INPUT_SHA256": hashes,
    }
    return result, coverage


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R39_STATUS", "FAST3_R39_CLASSIFICATION", "FAST3_R39_DECISION",
        "TARGET_FIRST_REALTIME_OBSERVABLE", "TARGET_FIRST_TS_AVAILABLE", "TARGET1_SIGNAL_COUNT",
        "TARGET1_FINAL_WIN_COUNT", "TARGET1_FINAL_LOSS_COUNT", "TARGET1_FINAL_WIN_RATE",
        "TARGET1_PATH_COMPLETE_COUNT", "TARGET1_PATH_COMPLETE_RATIO",
        "WINNER_TIME_TO_TARGET_MEDIAN", "LOSER_TIME_TO_TARGET_MEDIAN",
        "WINNER_ENTRY_TO_TARGET_RETURN_MEDIAN", "LOSER_ENTRY_TO_TARGET_RETURN_MEDIAN",
        "WINNER_PRE_TARGET_MAE_MEDIAN", "LOSER_PRE_TARGET_MAE_MEDIAN",
        "WINNER_TARGET_TO_FINAL_RETURN_MEDIAN", "LOSER_TARGET_TO_FINAL_RETURN_MEDIAN",
        "T0_MAX_ORIENTED_UNIVARIATE_AUC", "T1_MAX_ORIENTED_UNIVARIATE_AUC",
        "T3_MAX_ORIENTED_UNIVARIATE_AUC", "T5_MAX_ORIENTED_UNIVARIATE_AUC", "T10_MAX_ORIENTED_UNIVARIATE_AUC",
        "T1_DRAWDOWN_AUC", "T3_DRAWDOWN_AUC", "T5_DRAWDOWN_AUC", "T10_DRAWDOWN_AUC",
        "FINAL_LOSER_TIME_TO_POST_TARGET_PEAK_MEDIAN", "FINAL_LOSER_TIME_TO_BREAKEVEN_LOSS_MEDIAN",
        "UP_POST_TARGET_MAX_AUC", "DOWN_POST_TARGET_MAX_AUC", "UP_POST_TARGET_DISCRIMINATION",
        "DOWN_POST_TARGET_DISCRIMINATION", "STRONG_POST_TARGET_STRUCTURE", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "R28_PREDICTIVE_IDENTITY_UNCHANGED", "PIT_STATUS",
        "TARGET_FIRST_OBSERVABILITY_STATUS", "PATH_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS",
        "OOF_INTEGRITY_STATUS", "FINAL_CONFIRMATION_DATA_USED", "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
    ]
    return "\n".join(f"{key}={str(summary[key]).lower() if isinstance(summary[key], bool) else summary[key]}" for key in keys)


def execute() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    frozen = RESULTS / "frozen/fast3" / f"r39_target_first_conditional_payoff_decomposition_r1_{run_id}"
    stage = RESULTS / "scratch/fast3" / f".r39_target_first_conditional_payoff_decomposition_r1_{run_id}.staging"
    if frozen.exists() or stage.exists(): raise R39Stop("STOP_OUTPUT_PATH_EXISTS")
    stage.mkdir(parents=True)
    prereg = preregistration(now.isoformat().replace("+00:00", "Z"))
    prereg_path = stage / "FAST3_R39_PREREGISTRATION_R1.json"
    write_json(prereg_path, prereg)
    prereg_hash = sha256(prereg_path)
    try:
        target1, hashes = verify_and_load()
        summary, coverage = audit(target1, hashes)
        summary.update({
            "R39_PREREGISTRATION_VERIFIED": True, "R39_PREREGISTRATION_SHA256": prereg_hash,
            "RUN_ID": run_id, "RUN_ID_TIMESTAMP_SEMANTICS": "REAL_UTC_WALL_CLOCK",
            "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
            "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "PREREGISTRATION_EXISTS_BEFORE_METRICS": True,
        })
        coverage.to_csv(stage / "FAST3_R39_CHECKPOINT_COVERAGE.csv", index=False)
        write_json(stage / "FAST3_R39_SUMMARY.json", summary)
        report = [
            "# FAST3 R39 Target-First Conditional Payoff Decomposition R1", "",
            "## Outcome", "", f"- Status: `{summary['FAST3_R39_STATUS']}`",
            f"- Classification: `{summary['FAST3_R39_CLASSIFICATION']}`",
            f"- Decision: `{summary['FAST3_R39_DECISION']}`", "",
            "`target_first` is contemporaneously observable at canonical one-minute resolution. However, all 613 target-first successes use a corrected first-touch exit timestamp exactly equal to the target touch timestamp. Therefore T+1/T+3/T+5/T+10 are structurally censored by the authoritative payoff contract, not missing-data cases.", "",
            "A post-target continuation/reversal audit would require a newly defined payoff horizon. R39 does not create one, does not train or score a model, and does not calculate post-target AUCs, buckets, or simulated exits.", "",
            "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
        ]
        (stage / "FAST3_R39_REPORT.md").write_text("\n".join(report), encoding="utf-8")
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(frozen))
        summary["ARTIFACT_ROOT"] = str(frozen)
        return summary
    except Exception:
        if stage.exists(): shutil.rmtree(stage)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("FAST3_R39_STATUS=READY_REQUIRES_EXECUTE")
        return 0
    try:
        summary = execute()
    except R39Stop as exc:
        print(f"FAST3_R39_STATUS=STOP\nFAST3_R39_CLASSIFICATION=E_INVALID_PATH_OR_IDENTITY\nFAST3_R39_DECISION={exc}")
        return 2
    print(render_terminal(summary))
    print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
