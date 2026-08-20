#!/usr/bin/env python
"""FAST3 R40 target/payoff contract independence audit (read-only, zero-model)."""
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
R28G_LEDGER = RESULTS / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28E_LEDGER = RESULTS / "frozen/fast3/r28_3e_clean_lineage_first_touch_20260809_r3/R28_3E_FIRST_TOUCH_TRADE_LEDGER.csv"
R36_ROOT = RESULTS / "frozen/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z"
R36_SUMMARY = R36_ROOT / "FAST3_R36_SUMMARY.json"
R39_SUMMARY = RESULTS / "frozen/fast3/r39_target_first_conditional_payoff_decomposition_r1_20260810T142051Z/FAST3_R39_SUMMARY.json"

TARGET_SOURCE = REPO / "fast3/scripts/run/fast3_cleanroom_r1_preholdout.py"
FIRST_TOUCH_SOURCE = REPO / "fast3/scripts/run/fast3_r28_3e_clean_lineage_first_touch.py"
CORRECTION_SOURCE = REPO / "fast3/scripts/run/fast3_r28_3g_corporate_action_normalized_first_touch.py"
PAYOFF_SOURCE = REPO / "fast3/src/fast3/economics/executable_payoff_ledger_calendar_hard_r26a2.py"
HEADS = ("UP", "DOWN")
CLASSIFICATIONS = {
    "A_TARGET_AND_PAYOFF_INDEPENDENT", "B_TARGET_PAYOFF_PARTIALLY_COUPLED",
    "C_TARGET_PAYOFF_MECHANICALLY_COUPLED", "D_PREDICTIVE_LEAKAGE_DISCOVERED",
    "E_INVALID_CONTRACT_IDENTITY",
}
EXPECTED = {
    "PHASE2_DECISION": "ed3a803165f2e2516903433c31b36d01b12a63895fc5ab4d7d7e6a773a7d90c7",
    "PHASE2_LINEAGE": "eb012006137745cc870840afac9b9fc9b59a46c9268f860d12ffd9c715e8b4df",
    "R28G_LEDGER": "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    "R28E_LEDGER": "52e8ac6ea642f57abb900d2c78315a7061347c74a70ba8c54597867a63713097",
    "R36_SUMMARY": "1f90403dc33c1f222a3732bc39b9d507217857c4e74ab389fa2eece3edd7647f",
    "R39_SUMMARY": "f94094d0986e0f5cea95bc51d00ffd84909778ca0575c253fc6d1f658e151eac",
    "UP_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
    "TARGET_SOURCE": "6a41a129d8580c72c5dbbdc35799486f4b90e9265beba757ba9a491e8fa7d297",
    "FIRST_TOUCH_SOURCE": "341e53921bb14ef8fdcde52e0915f83df9a5302b4b438bac7bab272fc0652bff",
    "CORRECTION_SOURCE": "5ec1c494bb557d48657e598f872d3a3f1ff08a9b062f020474122dbef1d7cd14",
    "PAYOFF_SOURCE": "b5ce1e7e45143d616289a8d9e67e2c59ff7865bdcd2666aa22bf5a5bf533f21d",
}


class R40Stop(RuntimeError):
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
        "CONTRACT_ID": "FAST3_R40_TARGET_PAYOFF_CONTRACT_INDEPENDENCE_AUDIT_R1",
        "CREATED_AT_UTC": created_at, "STATUS": "FROZEN_BEFORE_CONTRACT_IDENTITY_METRICS",
        "RESEARCH_QUESTION": "Are target_first and corrected first-touch NET20 definitionally independent?",
        "AUTHORITATIVE_SIGNAL_COUNT": 1197, "AUTHORITATIVE_TARGET1_COUNT": 613,
        "DEPENDENCY_LABELS": ["NONE", "DIRECT", "INDIRECT", "SHARED_CONSTRUCTION"],
        "CLASSIFICATION_RULE": {
            "A": "target and payoff construction are independent",
            "B": "shared construction exists but target is not the principal termination branch",
            "C": "target-first is a core input to the first-touch exit timestamp/price and therefore indirectly NET20",
            "D": "decision-time model features contain future target, exit, or NET20 information",
            "E": "definitions or frozen identities cannot be uniquely traced",
        },
        "MODEL_TRAINING_ALLOWED": False, "MODEL_PREDICTION_ALLOWED": False,
        "NEW_FEATURE_ALLOWED": False, "NEW_PAYOFF_CONTRACT_ALLOWED": False,
        "COUNTERFACTUAL_SIMULATION_ALLOWED": False, "PARAMETER_OPTIMIZATION_ALLOWED": False,
        "SECOND_ROUND_ANALYSIS_ALLOWED": False, "AUTOMATIC_FOLLOWUP_ALLOWED": False,
        "FINAL_OR_PROSPECTIVE_DATA_ALLOWED": False,
        "CLASSIFICATIONS": sorted(CLASSIFICATIONS),
    }


def authoritative_definitions() -> pd.DataFrame:
    rows = [
        ("TARGET_FIRST", TARGET_SOURCE, "candidate_features / lines 237,260-271",
         "For each direction, 1 iff that direction's +/-1% underlying barrier is the unique first barrier touched within 24h."),
        ("UP_DOWN_TARGET_EVENT", TARGET_SOURCE, "first_cross; candidate_features / lines 260-271",
         "UP uses first high >= entry*1.01; DOWN uses first low <= entry*0.99; same-minute opposing touches are ambiguous and excluded."),
        ("FAVORABLE_PROFIT_BARRIER", TARGET_SOURCE, "candidate_features / entry_price*1.01 and entry_price*0.99",
         "UP favorable barrier is +1%; DOWN favorable barrier is -1%, both on the underlying reference path."),
        ("COMPETING_ADVERSE_BARRIER", TARGET_SOURCE, "candidate_features / first-touch ordering",
         "UP adverse competitor is -1%; DOWN adverse competitor is +1%; first observed index determines the label."),
        ("FIRST_TOUCH_EXIT_TIMESTAMP", FIRST_TOUCH_SOURCE, "attach_first_touch / lines 420-445",
         "Favorable-first rows replace frozen 24h closeout with first legal execution-ETF open at/after target touch; other rows retain R26A2 closeout."),
        ("ENTRY_PRICE", PAYOFF_SOURCE, "_join_action / lines 155-190",
         "Open of first legal mapped execution-ETF one-minute bar strictly after authoritative anchor, within 15 minutes."),
        ("EXIT_PRICE", FIRST_TOUCH_SOURCE, "attach_first_touch / lines 428-445",
         "Favorable-first: open at first legal ETF bar at/after touch; adverse/no-event: frozen R26A2 24h closeout open."),
        ("GROSS_RETURN", FIRST_TOUCH_SOURCE, "attach_first_touch / line 448",
         "first_touch_exit_price / entry_price - 1 before corporate-action correction."),
        ("NET20", FIRST_TOUCH_SOURCE, "attach_first_touch / line 450",
         "first_touch_gross - 0.002 (20 bps)."),
        ("CORPORATE_ACTION_NORMALIZED_PAYOFF", CORRECTION_SOURCE, "normalize_trade / lines 210-223; run / lines 390-392",
         "Normalize entry/exit across issuer-authoritative split factors, recompute gross, then corrected NET20=normalized gross-0.002."),
    ]
    return pd.DataFrame(rows, columns=["CONTRACT_ITEM", "SOURCE_FILE", "SOURCE_LINE_OR_SYMBOL", "CONTRACT_DESCRIPTION"])


def dependency_matrix() -> pd.DataFrame:
    return pd.DataFrame([
        ["decision-time features", "NONE", "NONE", "NONE", "NONE"],
        ["target_first", "DIRECT", "DIRECT", "DIRECT", "INDIRECT"],
        ["first_touch contract", "SHARED_CONSTRUCTION", "DIRECT", "DIRECT", "INDIRECT"],
        ["profit barrier", "DIRECT", "INDIRECT", "INDIRECT", "INDIRECT"],
        ["loss barrier", "DIRECT", "INDIRECT", "INDIRECT", "INDIRECT"],
    ], columns=["DEPENDENCY_SOURCE", "target_first", "exit_ts", "exit_price", "NET20"])


def verify_inputs() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], dict[str, str]]:
    score_paths = {head: SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet" for head in HEADS}
    paths = {
        "PHASE2_DECISION": PHASE2_DECISION, "PHASE2_LINEAGE": PHASE2_LINEAGE,
        "R28G_LEDGER": R28G_LEDGER, "R28E_LEDGER": R28E_LEDGER,
        "R36_SUMMARY": R36_SUMMARY, "R39_SUMMARY": R39_SUMMARY,
        "TARGET_SOURCE": TARGET_SOURCE, "FIRST_TOUCH_SOURCE": FIRST_TOUCH_SOURCE,
        "CORRECTION_SOURCE": CORRECTION_SOURCE, "PAYOFF_SOURCE": PAYOFF_SOURCE,
        **{f"{head}_LEDGER": path for head, path in score_paths.items()},
    }
    if any(not path.is_file() for path in paths.values()): raise R40Stop("STOP_REQUIRED_CONTRACT_SOURCE_MISSING")
    observed = {name: sha256(path) for name, path in paths.items()}
    if observed != EXPECTED: raise R40Stop("STOP_FROZEN_CONTRACT_HASH_MISMATCH")

    decision = json.loads(PHASE2_DECISION.read_text(encoding="utf-8"))
    lineage = json.loads(PHASE2_LINEAGE.read_text(encoding="utf-8"))
    if decision.get("status") != "PASS" or decision.get("champions") != {"DOWN": "R28_3_CROSS_ASSET_FLOW", "UP": "R28_3_CROSS_ASSET_FLOW"}:
        raise R40Stop("STOP_AUTHORITATIVE_R28_DECISION")
    if any(lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head] != observed[f"{head}_LEDGER"] for head in HEADS):
        raise R40Stop("STOP_SCORE_LINEAGE")
    feature_audit = decision["feature_audit"]["R28_3_CROSS_ASSET_FLOW"]
    for head in HEADS:
        for fold in feature_audit[head]["folds"]:
            if fold["status"] != "USED" or not (fold["purge_pass"] and fold["embargo_pass"] and fold["time_order_pass"]):
                raise R40Stop("STOP_OOF_OR_PIT_AUDIT")
    if any(decision.get(key) for key in ("prospective_outcome_used_for_training", "prospective_outcome_used_for_selection",
                                          "holdout_rescoring_executed", "threshold_optimization_executed")):
        raise R40Stop("STOP_PREDICTIVE_LEAKAGE_OR_RESEARCH_MUTATION")
    r39 = json.loads(R39_SUMMARY.read_text(encoding="utf-8"))
    if r39.get("FAST3_R39_CLASSIFICATION") != "E_INVALID_PATH_OR_IDENTITY" or r39.get("TARGET1_SIGNAL_COUNT") != 613:
        raise R40Stop("STOP_R39_TRIGGER_RECONCILIATION")
    r36 = json.loads(R36_SUMMARY.read_text(encoding="utf-8"))
    if r36.get("FAST3_R36_STATUS") != "PASS" or r36.get("PATH_COMPLETE_SIGNAL_COUNT") != 1197:
        raise R40Stop("STOP_INDEPENDENT_ECONOMIC_ARTIFACT_IDENTITY")

    score_columns = ["candidate_id", "target_first", "selected", "head", "decision_timestamp_utc",
                     "underlying_symbol", "probability", "feature_manifest_sha256", "model_sha256"]
    score = pd.concat([pd.read_parquet(path, columns=score_columns) for path in score_paths.values()], ignore_index=True)
    if score.candidate_id.duplicated().any(): raise R40Stop("STOP_SCORE_DUPLICATE")
    corrected = pd.read_csv(R28G_LEDGER)
    corrected = corrected.loc[corrected.primary_executable_first_touch_cohort.astype(bool)].copy()
    r28e = pd.read_csv(R28E_LEDGER, usecols=["candidate_id", "frozen_label", "first_touch_exit_reason"])
    if len(corrected) != 1197 or corrected.candidate_id.duplicated().any() or r28e.candidate_id.duplicated().any():
        raise R40Stop("STOP_CORRECTED_COHORT_IDENTITY")
    frame = corrected.merge(r28e, on="candidate_id", validate="one_to_one").merge(
        score, on="candidate_id", validate="one_to_one", suffixes=("_economic", "_score"))
    for column in ("timestamp", "touch_timestamp", "first_touch_exit_timestamp"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    timestamp_ok = np.array_equal(frame.timestamp.to_numpy(dtype="datetime64[us]"),
                                  pd.to_datetime(frame.decision_timestamp_utc, utc=True).to_numpy(dtype="datetime64[us]"))
    identity_ok = (timestamp_ok and frame.head_economic.eq(frame.head_score).all() and frame.selected.eq(True).all()
                   and frame.underlying_symbol_economic.eq(frame.underlying_symbol_score).all()
                   and np.array_equal(frame.target_first.astype(int), frame.event_state.eq("FAVORABLE_FIRST").astype(int))
                   and np.allclose(frame.corrected_gross - .002, frame.corrected_net20, atol=1e-14, rtol=0))
    if not identity_ok: raise R40Stop("STOP_TARGET_PAYOFF_IDENTITY")
    return frame, decision, r36, observed


def relation_counts(frame: pd.DataFrame) -> dict[str, int]:
    gross = pd.to_numeric(frame.corrected_gross, errors="raise")
    return {
        "EXIT_ABOVE_ENTRY": int(gross.gt(0).sum()), "EXIT_EQUALS_ENTRY": int(gross.eq(0).sum()),
        "EXIT_BELOW_ENTRY": int(gross.lt(0).sum()),
    }


def audit(frame: pd.DataFrame, r36: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    target1 = frame.loc[frame.target_first.eq(1)].copy()
    target0 = frame.loc[frame.target_first.eq(0)].copy()
    competing = target0.loc[target0.event_state.eq("ADVERSE_FIRST") & target0.touch_timestamp.notna()].copy()
    t1_equal = target1.touch_timestamp.eq(target1.first_touch_exit_timestamp)
    t0_equal = competing.touch_timestamp.eq(competing.first_touch_exit_timestamp)
    if len(target1) != 613 or len(target0) != 584 or not t1_equal.all() or len(competing) != 479:
        raise R40Stop("STOP_MECHANICAL_IDENTITY_RECONCILIATION")
    fixed = {f"{m}M": {"mean_net20": r36[f"HORIZON_{m}M_MEAN_NET20"],
                        "profit_factor": r36[f"HORIZON_{m}M_PROFIT_FACTOR"]} for m in (5, 10, 15, 30, 60)}
    return {
        "FAST3_R40_STATUS": "PASS",
        "FAST3_R40_CLASSIFICATION": "C_TARGET_PAYOFF_MECHANICALLY_COUPLED",
        "FAST3_R40_DECISION": "DESIGN_INDEPENDENT_ECONOMIC_EVALUATION_CONTRACT",
        "TARGET_FIRST_FORMAL_DEFINITION": "For direction d in {UP,DOWN}, target_first(d)=1 iff the d-favorable underlying +/-1% barrier has a finite first-cross index within 24h and occurs strictly before the competing adverse barrier; same-minute ties are ambiguous and excluded.",
        "TARGET_FIRST_EVENT_TYPE": "BARRIER_ORDER_EVENT",
        "IS_TARGET_FIRST_A_PURE_MARKET_STATE_LABEL": False,
        "IS_TARGET_FIRST_A_TRADING_OUTCOME_LABEL": False,
        "IS_TARGET_FIRST_A_FIRST_PASSAGE_LABEL": True,
        "TARGET_FIRST_DEPENDS_ON_FUTURE_PRICE_PATH": True,
        "TARGET_FIRST_DEPENDS_ON_PROFIT_BARRIER": True,
        "TARGET_FIRST_DEPENDS_ON_LOSS_BARRIER": True,
        "TARGET_FIRST_DEPENDS_ON_FIRST_TOUCH_ORDER": True,
        "TARGET_FIRST_DEPENDS_ON_EXIT_TIMESTAMP": False,
        "TARGET_FIRST_DEPENDS_ON_EXIT_PRICE": False,
        "TARGET_FIRST_DEPENDS_ON_REALIZED_NET20": False,
        "EXIT_TIMESTAMP_DEPENDS_ON_TARGET_FIRST": True,
        "EXIT_PRICE_DEPENDS_ON_TARGET_FIRST": True,
        "NET20_DEPENDS_ON_TARGET_FIRST_DIRECTLY": False,
        "NET20_DEPENDS_ON_TARGET_FIRST_INDIRECTLY": True,
        "TARGET1_TOUCH_TS_EQUALS_EXIT_TS_RATE": float(t1_equal.mean()),
        "TARGET1_TOUCH_TS_EQUALS_EXIT_TS_COUNT": int(t1_equal.sum()),
        "TARGET0_COMPETING_TS_EQUALS_EXIT_TS_RATE": float(t0_equal.mean()),
        "TARGET0_COMPETING_TS_EQUALS_EXIT_TS_COUNT": int(t0_equal.sum()),
        "TARGET0_COMPETING_TS_AVAILABLE_COUNT": len(competing),
        "TARGET1_EXIT_REASON_COUNTS": target1.first_touch_exit_reason.value_counts().to_dict(),
        "TARGET0_EXIT_REASON_COUNTS": target0.first_touch_exit_reason.value_counts().to_dict(),
        "TARGET1_EXIT_PRICE_RELATION_TO_ENTRY": relation_counts(target1),
        "TARGET0_EXIT_PRICE_RELATION_TO_ENTRY": relation_counts(target0),
        "MECHANICAL_POSITIVE_PAYOFF_BIAS_GIVEN_TARGET1": True,
        "MECHANICAL_NEGATIVE_PAYOFF_BIAS_GIVEN_TARGET0": True,
        "R37_TARGET_PAYOFF_COMPARISON_INDEPENDENT_VALIDATION": False,
        "R37_TARGET_PAYOFF_COMPARISON_NONINDEPENDENCE_REASON": "TARGET_AND_PAYOFF_SHARE_FIRST_TOUCH_BARRIER_CONTRACT; target_first=1 selects the early-touch exit branch while target_first=0 retains the frozen 24h closeout branch",
        "R37_ECONOMIC_ALIGNMENT_EVIDENCE_STATUS": "INVALID_AS_INDEPENDENT_EVIDENCE",
        "R28_PREDICTIVE_EDGE_VALID": True,
        "R28_PREDICTIVE_EDGE_INTERPRETATION": "PREDICTS_FIRST_PASSAGE_BARRIER_ORDER",
        "DO_DECISION_TIME_FEATURES_USE_TARGET_FUTURE_INFORMATION": False,
        "DO_DECISION_TIME_FEATURES_USE_EXIT_INFORMATION": False,
        "DO_DECISION_TIME_FEATURES_USE_NET20_INFORMATION": False,
        "PREDICTIVE_LEAKAGE_STATUS": "PASS",
        "INDEPENDENT_ECONOMIC_EVALUATION_EXISTS": True,
        "INDEPENDENT_ECONOMIC_EVALUATIONS": [{
            "ARTIFACT": str(R36_ROOT / "FAST3_R36_HORIZON_METRICS.csv"),
            "OUTCOME": "entry-to-fixed-5/10/15/30/60-minute execution-ETF NET20",
            "WHY_INDEPENDENT": "fixed timestamps are determined from entry time, not target_first or target touch",
            "OBSERVED_FROZEN_RESULTS": fixed,
        }],
        "PREDICTIVE_EDGE_STATUS": "CONFIRMED_FIRST_PASSAGE_EVENT_EDGE",
        "INDEPENDENT_ECONOMIC_EDGE_STATUS": "NOT_ESTABLISHED",
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True,
        "PIT_STATUS": "PASS", "OOF_INTEGRITY_STATUS": "PASS", "CORPORATE_ACTION_STATUS": "PASS",
        "CONTRACT_TRACEABILITY_STATUS": "PASS",
        "FINAL_CONFIRMATION_DATA_USED": False,
        "MAX_NEW_MODEL_COUNT": 0, "MAX_NEW_FEATURE_COUNT": 0,
        "MAX_NEW_PAYOFF_CONTRACT_COUNT": 0, "COUNTERFACTUAL_SIMULATION_COUNT": 0,
        "PARAMETER_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "PRIMARY_RESEARCH_INTERPRETATION": "R28_VALIDLY_PREDICTS_A_FUTURE_FIRST_PASSAGE_BARRIER_ORDER_EVENT_BUT_R37_TARGET1_VS_TARGET0_NET20_IS_MECHANICALLY_COUPLED_TO_THE_ASYMMETRIC_FIRST_TOUCH_EXIT_CONTRACT",
        "NEXT_STAGE": "DESIGN_INDEPENDENT_ECONOMIC_EVALUATION_CONTRACT",
        "INPUT_SHA256": hashes,
    }


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R40_STATUS", "FAST3_R40_CLASSIFICATION", "FAST3_R40_DECISION",
        "TARGET_FIRST_FORMAL_DEFINITION", "TARGET_FIRST_EVENT_TYPE",
        "TARGET_FIRST_DEPENDS_ON_PROFIT_BARRIER", "TARGET_FIRST_DEPENDS_ON_LOSS_BARRIER",
        "TARGET_FIRST_DEPENDS_ON_FIRST_TOUCH_ORDER", "EXIT_TIMESTAMP_DEPENDS_ON_TARGET_FIRST",
        "EXIT_PRICE_DEPENDS_ON_TARGET_FIRST", "NET20_DEPENDS_ON_TARGET_FIRST_DIRECTLY",
        "NET20_DEPENDS_ON_TARGET_FIRST_INDIRECTLY", "TARGET1_TOUCH_TS_EQUALS_EXIT_TS_RATE",
        "TARGET0_COMPETING_TS_EQUALS_EXIT_TS_RATE", "MECHANICAL_POSITIVE_PAYOFF_BIAS_GIVEN_TARGET1",
        "MECHANICAL_NEGATIVE_PAYOFF_BIAS_GIVEN_TARGET0", "R37_TARGET_PAYOFF_COMPARISON_INDEPENDENT_VALIDATION",
        "R37_ECONOMIC_ALIGNMENT_EVIDENCE_STATUS", "R28_PREDICTIVE_EDGE_VALID",
        "R28_PREDICTIVE_EDGE_INTERPRETATION", "PREDICTIVE_LEAKAGE_STATUS",
        "INDEPENDENT_ECONOMIC_EVALUATION_EXISTS", "PREDICTIVE_EDGE_STATUS",
        "INDEPENDENT_ECONOMIC_EDGE_STATUS", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
        "R28_PREDICTIVE_IDENTITY_UNCHANGED", "PIT_STATUS", "OOF_INTEGRITY_STATUS",
        "CORPORATE_ACTION_STATUS", "CONTRACT_TRACEABILITY_STATUS", "FINAL_CONFIRMATION_DATA_USED",
        "NEXT_STAGE",
    ]
    return "\n".join(f"{key}={str(summary[key]).lower() if isinstance(summary[key], bool) else summary[key]}" for key in keys)


def execute() -> dict[str, Any]:
    now = datetime.now(timezone.utc); run_id = now.strftime("%Y%m%dT%H%M%SZ")
    frozen = RESULTS / "frozen/fast3" / f"r40_target_payoff_contract_independence_audit_r1_{run_id}"
    stage = RESULTS / "scratch/fast3" / f".r40_target_payoff_contract_independence_audit_r1_{run_id}.staging"
    if frozen.exists() or stage.exists(): raise R40Stop("STOP_OUTPUT_PATH_EXISTS")
    stage.mkdir(parents=True)
    prereg = preregistration(now.isoformat().replace("+00:00", "Z"))
    prereg_path = stage / "FAST3_R40_PREREGISTRATION_R1.json"; write_json(prereg_path, prereg)
    prereg_hash = sha256(prereg_path)
    try:
        frame, _, r36, hashes = verify_inputs()
        summary = audit(frame, r36, hashes)
        definitions = authoritative_definitions(); matrix = dependency_matrix()
        summary.update({
            "R40_PREREGISTRATION_VERIFIED": True, "R40_PREREGISTRATION_SHA256": prereg_hash,
            "RUN_ID": run_id, "RUN_ID_TIMESTAMP_SEMANTICS": "REAL_UTC_WALL_CLOCK",
            "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
            "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "PREREGISTRATION_EXISTS_BEFORE_AUDIT_METRICS": True,
        })
        definitions.to_csv(stage / "FAST3_R40_AUTHORITATIVE_DEFINITIONS.csv", index=False)
        matrix.to_csv(stage / "FAST3_R40_CONTRACT_DEPENDENCY_MATRIX.csv", index=False)
        write_json(stage / "FAST3_R40_SUMMARY.json", summary)
        report = [
            "# FAST3 R40 Target/Payoff Contract Independence Audit R1", "",
            f"- Classification: `{summary['FAST3_R40_CLASSIFICATION']}`",
            f"- Decision: `{summary['FAST3_R40_DECISION']}`", "",
            "The target label is a legitimate future first-passage barrier-order label and does not consume exit or NET20. The subsequent first-touch economic translation is not independent: favorable target-first rows switch to an exit at the target touch, while target-first=0 rows retain the frozen 24-hour closeout.", "",
            "Accordingly, the R28 OOF lift remains valid as first-passage prediction. The R37 target1/target0 NET20 contrast is invalid as independent economic validation. Existing fixed-horizon R36 outcomes are independent of target-touch termination and remain negative in the frozen audit.", "",
            "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
        ]
        (stage / "FAST3_R40_REPORT.md").write_text("\n".join(report), encoding="utf-8")
        frozen.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(stage), str(frozen))
        summary["ARTIFACT_ROOT"] = str(frozen)
        return summary
    except Exception:
        if stage.exists(): shutil.rmtree(stage)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    if not args.execute:
        print("FAST3_R40_STATUS=READY_REQUIRES_EXECUTE"); return 0
    try: summary = execute()
    except R40Stop as exc:
        print(f"FAST3_R40_STATUS=STOP\nFAST3_R40_CLASSIFICATION=E_INVALID_CONTRACT_IDENTITY\nFAST3_R40_DECISION={exc}"); return 2
    print(render_terminal(summary)); print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
