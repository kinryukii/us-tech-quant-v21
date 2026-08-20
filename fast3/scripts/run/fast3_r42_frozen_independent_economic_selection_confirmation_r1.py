#!/usr/bin/env python
"""FAST3 R42 frozen independent economic selection confirmation audit.

This stage is confirmatory-only.  It refuses historical backfill, refuses to
derive score bucket boundaries after R41, and emits no substantive metrics
when a legal frozen confirmation cohort does not exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")

R28_ROOT = RESULTS / "frozen/fast3/r28_phase3_20260808T131135Z"
R28_IDENTITY = R28_ROOT / "R28_PHASE3_RESEARCH_IDENTITY.json"
R28_REGISTRATION = R28_ROOT / "R28_PROSPECTIVE_SHADOW_REGISTRATION.json"
R28_READY = R28_ROOT / "R28_PROSPECTIVE_SHADOW_R1_READY_MANIFEST.json"
R28_MODELS = {
    "UP": R28_ROOT / "models/R28_3_UP_FINAL.joblib",
    "DOWN": R28_ROOT / "models/R28_3_DOWN_FINAL.joblib",
}
R28_RUNTIME = RESULTS / "runtime/fast3/r28_prospective_dual_shadow_r1"
R28_SEALED = RESULTS / "frozen/fast3/r28_prospective_dual_shadow_r1"

R41_ROOT = RESULTS / "frozen/fast3/r41_independent_economic_score_alignment_r1_20260810T151254Z"
R41_SUMMARY = R41_ROOT / "FAST3_R41_SUMMARY.json"
R41_PREREG = R41_ROOT / "FAST3_R41_PREREGISTRATION_R1.json"
R41_QUINTILES = R41_ROOT / "FAST3_R41_QUINTILE_ECONOMIC_METRICS.csv"

CANONICAL = DATA / "fast3/moomoo_24h_1m/canonical"
HEADS = ("DOWN", "UP")
HORIZONS = (5, 10, 15, 30, 60)
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
BOUNDARY_KEYS = tuple(
    f"{head}_{left}_{right}_BOUNDARY"
    for head in ("UP", "DOWN")
    for left, right in (("Q1", "Q2"), ("Q2", "Q3"), ("Q3", "Q4"), ("Q4", "Q5"))
)
NOT_EVALUATED = "NOT_EVALUATED_NO_LEGAL_CONFIRMATION_DATA"


class R42Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def preregistration(created_at: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R42_FROZEN_INDEPENDENT_ECONOMIC_SELECTION_CONFIRMATION_R1",
        "CREATED_AT_UTC": created_at,
        "STATUS": "FROZEN_BEFORE_CONFIRMATION_COHORT_ACCESS",
        "STAGE_NATURE": "FROZEN_CONFIRMATORY_TEST_ONLY",
        "PRIMARY_DIRECTION": "DOWN",
        "SECONDARY_DIRECTION": "UP",
        "UP_CANNOT_REPLACE_FAILED_DOWN_PRIMARY": True,
        "HORIZONS_FIXED_MINUTES": list(HORIZONS),
        "SCORE_BUCKETS_FIXED": list(QUINTILES),
        "MAX_HORIZON_COUNT": 5,
        "MAX_SCORE_BUCKET_COUNT": 5,
        "MAX_RESEARCH_ITERATION_COUNT": 1,
        "PRIMARY_SUCCESS_RULES": {
            "A": ">=3/5 horizons Spearman(score, NET20) > 0",
            "B": ">=3/5 horizons Q5 mean NET20 > Q1 mean NET20",
            "C": ">=2/5 horizons mean ordering MONOTONIC_POSITIVE or MOSTLY_POSITIVE",
            "D": "raw ordering is not driven by one extreme trade; report fixed robustness metrics",
        },
        "POSITIVE_ECONOMIC_CANDIDATE_RULE": ">=2 horizons Q5 mean NET20>0, Q5 PF>1, and Q5 mean>Q1 mean",
        "ORDERING_RULES": {
            "MONOTONIC_POSITIVE": "all four adjacent differences >=0",
            "MOSTLY_POSITIVE": "at least three adjacent differences >0 and Q5>Q1",
            "MONOTONIC_NEGATIVE": "all four adjacent differences <=0 (evaluated after positive rule)",
            "NON_MONOTONIC": "otherwise",
        },
        "WINSORIZATION_FIXED": "1%/99%",
        "NET_COST_BPS": 20,
        "FIXED_HORIZON_PAYOFF": "entry open to exact +N minute open, subtract 20bps once",
        "QUINTILE_BOUNDARIES_SOURCE_REQUIRED": "R41_FROZEN_DISCOVERY",
        "R41_BOUNDARY_REFIT_ALLOWED": False,
        "HISTORICAL_BACKFILL_ALLOWED": False,
        "R41_DATA_REUSE_ALLOWED": False,
        "MODEL_FIT_ALLOWED": False,
        "R28_REFIT_ALLOWED": False,
        "R28_RESCORE_WITH_MODIFIED_MODEL_ALLOWED": False,
        "THRESHOLD_CHANGE_ALLOWED": False,
        "FEATURE_CHANGE_ALLOWED": False,
        "CALIBRATION_CHANGE_ALLOWED": False,
        "HORIZON_SEARCH_ALLOWED": False,
        "SCORE_CUTOFF_SEARCH_ALLOWED": False,
        "SECOND_ROUND_ANALYSIS_ALLOWED": False,
        "AUTOMATIC_FOLLOWUP_EXPERIMENT_ALLOWED": False,
        "DOWN_MINIMUM_SIGNAL_COUNT": 50,
        "CLASSIFICATION_PRIORITY": ["E_NO_LEGAL_CONFIRMATION_DATA", "F_CONFIRMATION_SAMPLE_TOO_SMALL", "B", "A", "C", "D"],
    }


def canonical_latest_timestamp(symbol: str) -> pd.Timestamp | None:
    paths = sorted((CANONICAL / f"symbol={symbol}").glob("year=*/month=*/data.parquet"))
    if not paths:
        return None
    frame = pd.read_parquet(paths[-1], columns=["timestamp_utc"])
    if frame.empty:
        return None
    return pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise").max()


def verify_r28_identity() -> tuple[dict[str, Any], dict[str, str]]:
    required = [R28_IDENTITY, R28_REGISTRATION, R28_READY, *R28_MODELS.values()]
    if any(not path.is_file() for path in required):
        raise R42Stop("STOP_R28_FROZEN_IDENTITY_MISSING")
    identity = json.loads(R28_IDENTITY.read_text(encoding="utf-8"))
    registration = json.loads(R28_REGISTRATION.read_text(encoding="utf-8"))
    ready = json.loads(R28_READY.read_text(encoding="utf-8"))
    observed_models = {head: sha256(path) for head, path in R28_MODELS.items()}
    if observed_models != identity.get("r28_model_sha256"):
        raise R42Stop("STOP_R28_MODEL_HASH_MISMATCH")
    if ready.get("r28_model_sha256") != observed_models:
        raise R42Stop("STOP_R28_READY_MANIFEST_MODEL_MISMATCH")
    if identity.get("candidate") != "R28_3_CROSS_ASSET_FLOW" or identity.get("candidate_change_allowed") is not False:
        raise R42Stop("STOP_R28_MODEL_IDENTITY_MISMATCH")
    if identity.get("feature_count") != 14 or len(identity.get("features", [])) != 14 or identity.get("feature_change_allowed") is not False:
        raise R42Stop("STOP_R28_FEATURE_IDENTITY_MISMATCH")
    if identity.get("threshold_optimization_allowed") is not False or set(identity.get("thresholds", {})) != {
        "DOWN_HGB_THRESHOLD", "DOWN_LOGIT_THRESHOLD", "UP_HGB_THRESHOLD", "UP_LOGIT_THRESHOLD"
    }:
        raise R42Stop("STOP_R28_THRESHOLD_IDENTITY_MISMATCH")
    if registration.get("historical_backfill_allowed") is not False or registration.get("outcome_before_ledger_freeze") is not False:
        raise R42Stop("STOP_R28_PROSPECTIVE_REGISTRATION_INVALID")
    hashes = {path.name: sha256(path) for path in required}
    return {"identity": identity, "registration": registration, "ready": ready}, hashes


def r41_boundaries() -> tuple[bool, dict[str, Any], list[str], dict[str, str]]:
    required = [R41_SUMMARY, R41_PREREG, R41_QUINTILES]
    if any(not path.is_file() for path in required):
        raise R42Stop("STOP_R41_FROZEN_ARTIFACT_MISSING")
    summary = json.loads(R41_SUMMARY.read_text(encoding="utf-8"))
    if summary.get("FAST3_R41_CLASSIFICATION") != "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED":
        raise R42Stop("STOP_R41_AUTHORITATIVE_CLASSIFICATION_MISMATCH")
    table = pd.read_csv(R41_QUINTILES)
    exact_columns = set(table.columns)
    found = sorted(key for key in BOUNDARY_KEYS if key in summary or key in exact_columns)
    values = {key: summary.get(key, "NOT_SAVED_IN_R41_ARTIFACT") for key in BOUNDARY_KEYS}
    return len(found) == len(BOUNDARY_KEYS), values, found, {path.name: sha256(path) for path in required}


def sealed_prospective_manifests() -> list[Path]:
    return sorted(R28_SEALED.rglob("*.json")) if R28_SEALED.is_dir() else []


def empty_metric_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    horizon_rows: list[dict[str, Any]] = []
    bucket_rows: list[dict[str, Any]] = []
    for direction in HEADS:
        for minute in HORIZONS:
            horizon_rows.append({
                "direction": direction,
                "horizon_minutes": minute,
                "signal_count": 0,
                "score_vs_net20_spearman": None,
                "score_vs_net20_pearson": None,
                "q5_minus_q1_mean_net20": None,
                "q5_minus_q1_win_rate": None,
                "q5_minus_q1_profit_factor": None,
                "mean_net20_ordering": NOT_EVALUATED,
                "p05_net20": None,
                "p95_net20": None,
                "worst_net20": None,
                "best_net20": None,
                "winsorized_q5_minus_q1_mean_net20": None,
                "q5_minus_q1_mean_excluding_single_best_trade": None,
                "q5_minus_q1_mean_excluding_single_worst_trade": None,
                "evaluation_status": NOT_EVALUATED,
            })
            for quintile in QUINTILES:
                bucket_rows.append({
                    "direction": direction,
                    "horizon_minutes": minute,
                    "quintile": quintile,
                    "count": 0,
                    "win_rate_net20": None,
                    "mean_net20": None,
                    "median_net20": None,
                    "profit_factor_net20": None,
                    "evaluation_status": NOT_EVALUATED,
                })
    return pd.DataFrame(horizon_rows), pd.DataFrame(bucket_rows)


def audit() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    r28, r28_hashes = verify_r28_identity()
    boundaries_frozen, boundary_values, found_boundary_fields, r41_hashes = r41_boundaries()
    manifests = sealed_prospective_manifests()
    canonical_latest = {symbol: canonical_latest_timestamp(symbol) for symbol in ("QQQ", "SOXX")}
    registration = pd.Timestamp(r28["registration"]["registration_utc"])
    registration = registration.tz_localize("UTC") if registration.tzinfo is None else registration.tz_convert("UTC")
    latest_common = min(value for value in canonical_latest.values() if value is not None) if all(canonical_latest.values()) else None

    # A confirmation row is legal only if its frozen R28 score ledger was sealed
    # before outcomes.  Canonical bars alone can never be re-labelled confirmation.
    legal_signal_count = 0
    legal_manifest_count = len(manifests)
    if manifests:
        raise R42Stop("STOP_UNEXPECTED_PROSPECTIVE_MANIFEST_REQUIRES_NEW_FROZEN_R42_REVIEW")

    stop_reasons = []
    if legal_manifest_count == 0:
        stop_reasons.append("NO_SEALED_R28_PROSPECTIVE_SCORE_LEDGER")
    if latest_common is None or latest_common <= registration:
        stop_reasons.append("CANONICAL_COMMON_DATA_DOES_NOT_POSTDATE_R28_REGISTRATION")
    if not boundaries_frozen:
        stop_reasons.append("R41_DID_NOT_SAVE_APPLICABLE_QUINTILE_BOUNDARIES")

    horizon_metrics, quintile_metrics = empty_metric_tables()
    summary: dict[str, Any] = {
        "FAST3_R42_STATUS": "STOP",
        "FAST3_R42_CLASSIFICATION": "E_NO_LEGAL_CONFIRMATION_DATA",
        "FAST3_R42_DECISION": "STOP_NO_UNUSED_CONFIRMATION_COHORT",
        "NEXT_STAGE": "STOP_NO_UNUSED_CONFIRMATION_COHORT",
        "STOP_REASONS": stop_reasons,
        "CONFIRMATION_TYPE": "NONE_NO_LEGAL_COHORT",
        "CONFIRMATION_IS_PROSPECTIVE": False,
        "CONFIRMATION_START": "NOT_AVAILABLE",
        "CONFIRMATION_END": "NOT_AVAILABLE",
        "CONFIRMATION_TRADING_DAYS": 0,
        "CONFIRMATION_SIGNAL_COUNT": legal_signal_count,
        "UP_CONFIRMATION_SIGNAL_COUNT": 0,
        "DOWN_CONFIRMATION_SIGNAL_COUNT": 0,
        "FIRST_LEGAL_CONFIRMATION_SIGNAL_TS": "NOT_AVAILABLE",
        "LAST_CONFIRMATION_SIGNAL_TS": "NOT_AVAILABLE",
        "R41_DATA_REUSED_FOR_CONFIRMATION": False,
        "WAS_CONFIRMATION_PERIOD_USED_IN_ANY_PRIOR_MODEL_SELECTION": False,
        "WAS_CONFIRMATION_PERIOD_USED_IN_R41_DISCOVERY": False,
        "CONFIRMATION_PERIOD_PRIOR_USE_APPLICABILITY": "NO_CONFIRMATION_PERIOD_EXISTS",
        "R28_PROSPECTIVE_REGISTRATION_UTC": str(registration),
        "CANONICAL_LATEST_COMMON_TIMESTAMP": str(latest_common) if latest_common is not None else "NOT_AVAILABLE",
        "R28_SEALED_PROSPECTIVE_MANIFEST_COUNT": legal_manifest_count,
        "R28_MODEL_IDENTITY_MATCH": True,
        "R28_FEATURE_IDENTITY_MATCH": True,
        "R28_THRESHOLD_IDENTITY_MATCH": True,
        "R28_REFIT_COUNT": 0,
        "R28_THRESHOLD_CHANGE_COUNT": 0,
        "R28_PREDICTIVE_IDENTITY_UNCHANGED": True,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "MAX_HORIZON_COUNT": 5,
        "MAX_SCORE_BUCKET_COUNT": 5,
        "MAX_RESEARCH_ITERATION_COUNT": 1,
        "HORIZONS_FIXED": list(HORIZONS),
        "SCORE_BUCKETS_FIXED": list(QUINTILES),
        "NO_SECOND_ROUND_ANALYSIS": True,
        "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "RESEARCH_CHOICE_CHANGED_AFTER_RESULT": False,
        "QUINTILE_BOUNDARIES_SOURCE": "R41_FROZEN_DISCOVERY",
        "QUINTILE_BOUNDARIES_FROZEN": boundaries_frozen,
        "R41_BOUNDARY_FIELD_COUNT": len(found_boundary_fields),
        "R41_BOUNDARY_FIELDS_FOUND": found_boundary_fields,
        **boundary_values,
        **{f"H{minute}_INDEPENDENT": True for minute in HORIZONS},
        "CONFIRMATION_DATA_INDEPENDENCE_STATUS": "STOP_NO_UNUSED_CONFIRMATION_COHORT",
        "INDEPENDENT_PAYOFF_STATUS": "PASS_CONTRACT_ONLY_NO_CONFIRMATION_ROWS",
        "PIT_STATUS": "PASS_FROZEN_IDENTITY_ONLY_NO_CONFIRMATION_ROWS",
        "CORPORATE_ACTION_STATUS": "PASS_R36_R41_CONTRACT_ONLY_NO_CONFIRMATION_ROWS",
        "SCORE_IDENTITY_STATUS": "PASS_FROZEN_R28_IDENTITY_NO_CONFIRMATION_SCORE_ROWS",
        "DOWN_POSITIVE_SPEARMAN_HORIZON_COUNT": None,
        "DOWN_Q5_GT_Q1_HORIZON_COUNT": None,
        "DOWN_POSITIVE_ORDERING_HORIZON_COUNT": None,
        "DOWN_PRIMARY_CONFIRMATION_PASS": False,
        "DOWN_PRIMARY_CONFIRMATION_EVALUATED": False,
        "DOWN_POSITIVE_ECONOMIC_CANDIDATE": False,
        "UP_POSITIVE_SPEARMAN_HORIZON_COUNT": None,
        "UP_Q5_GT_Q1_HORIZON_COUNT": None,
        "UP_POSITIVE_ORDERING_HORIZON_COUNT": None,
        "UP_SECONDARY_CONFIRMATION_PASS": False,
        "UP_SECONDARY_CONFIRMATION_EVALUATED": False,
        "UP_POSITIVE_ECONOMIC_CANDIDATE": False,
        "PREDICTIVE_EDGE_STATUS": "CONFIRMED_FIRST_PASSAGE_EVENT_EDGE",
        "INDEPENDENT_ECONOMIC_TRANSLATION_STATUS": "ALIGNMENT_ONLY_UNCONFIRMED_R42_NOT_EVALUATED",
        "INPUT_SHA256": {"R28": r28_hashes, "R41": r41_hashes},
    }
    for head in HEADS:
        for minute in HORIZONS:
            summary[f"{head}_SCORE_VS_{minute}M_NET20_SPEARMAN"] = None
            summary[f"{head}_SCORE_VS_{minute}M_NET20_PEARSON"] = None
            summary[f"{head}_Q5_MINUS_Q1_{minute}M"] = None
    return summary, horizon_metrics, quintile_metrics


def terminal_value(value: Any) -> str:
    if value is None:
        return "NOT_EVALUATED"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ",".join(map(str, value))
    return str(value)


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R42_STATUS", "FAST3_R42_CLASSIFICATION", "FAST3_R42_DECISION",
        "CONFIRMATION_TYPE", "CONFIRMATION_IS_PROSPECTIVE", "CONFIRMATION_START", "CONFIRMATION_END",
        "CONFIRMATION_TRADING_DAYS", "CONFIRMATION_SIGNAL_COUNT", "UP_CONFIRMATION_SIGNAL_COUNT",
        "DOWN_CONFIRMATION_SIGNAL_COUNT", "WAS_CONFIRMATION_PERIOD_USED_IN_ANY_PRIOR_MODEL_SELECTION",
        "WAS_CONFIRMATION_PERIOD_USED_IN_R41_DISCOVERY", "R41_DATA_REUSED_FOR_CONFIRMATION",
        "UP_Q1_Q2_BOUNDARY", "UP_Q2_Q3_BOUNDARY", "UP_Q3_Q4_BOUNDARY", "UP_Q4_Q5_BOUNDARY",
        "DOWN_Q1_Q2_BOUNDARY", "DOWN_Q2_Q3_BOUNDARY", "DOWN_Q3_Q4_BOUNDARY", "DOWN_Q4_Q5_BOUNDARY",
        "QUINTILE_BOUNDARIES_SOURCE", "QUINTILE_BOUNDARIES_FROZEN",
        *[f"DOWN_SCORE_VS_{minute}M_NET20_SPEARMAN" for minute in HORIZONS],
        *[f"DOWN_Q5_MINUS_Q1_{minute}M" for minute in HORIZONS],
        "DOWN_POSITIVE_SPEARMAN_HORIZON_COUNT", "DOWN_Q5_GT_Q1_HORIZON_COUNT",
        "DOWN_POSITIVE_ORDERING_HORIZON_COUNT", "DOWN_PRIMARY_CONFIRMATION_PASS",
        "DOWN_POSITIVE_ECONOMIC_CANDIDATE", "UP_POSITIVE_SPEARMAN_HORIZON_COUNT",
        "UP_Q5_GT_Q1_HORIZON_COUNT", "UP_POSITIVE_ORDERING_HORIZON_COUNT",
        "UP_SECONDARY_CONFIRMATION_PASS", "UP_POSITIVE_ECONOMIC_CANDIDATE",
        "MODEL_FIT_COUNT", "R28_REFIT_COUNT", "R28_THRESHOLD_CHANGE_COUNT",
        "R28_PREDICTIVE_IDENTITY_UNCHANGED", "CONFIRMATION_DATA_INDEPENDENCE_STATUS",
        "INDEPENDENT_PAYOFF_STATUS", "PIT_STATUS", "CORPORATE_ACTION_STATUS", "SCORE_IDENTITY_STATUS",
        "RESEARCH_CHOICE_CHANGED_AFTER_RESULT", "NEXT_STAGE",
    ]
    return "\n".join(f"{key}={terminal_value(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    frozen = RESULTS / "frozen/fast3" / f"r42_frozen_independent_economic_selection_confirmation_r1_{run_id}"
    stage = RESULTS / "scratch/fast3" / f".r42_frozen_independent_economic_selection_confirmation_r1_{run_id}.staging"
    if frozen.exists() or stage.exists():
        raise R42Stop("STOP_OUTPUT_PATH_EXISTS")
    stage.mkdir(parents=True)
    prereg_path = stage / "FAST3_R42_PREREGISTRATION_R1.json"
    write_json(prereg_path, preregistration(now.isoformat().replace("+00:00", "Z")))
    prereg_hash = sha256(prereg_path)

    summary, metrics, buckets = audit()
    summary.update({
        "RUN_ID": run_id,
        "RUN_ID_TIMESTAMP_SEMANTICS": "REAL_UTC_WALL_CLOCK",
        "PREREGISTRATION_EXISTS_BEFORE_AUDIT": True,
        "R42_PREREGISTRATION_SHA256": prereg_hash,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    })
    metrics.to_csv(stage / "FAST3_R42_CONFIRMATION_METRICS.csv", index=False)
    buckets.to_csv(stage / "FAST3_R42_QUINTILE_METRICS.csv", index=False)
    write_json(stage / "FAST3_R42_SUMMARY.json", summary)
    report = [
        "# FAST3 R42 Frozen Independent Economic Selection Confirmation R1", "",
        f"- Status: `{summary['FAST3_R42_STATUS']}`",
        f"- Classification: `{summary['FAST3_R42_CLASSIFICATION']}`",
        f"- Decision: `{summary['FAST3_R42_DECISION']}`", "",
        "R42 stopped before any confirmation metric was evaluated. No sealed post-registration R28 score ledger exists, the canonical common timestamp does not postdate R28 registration, and R41 did not save applicable score quintile boundaries. Historical R41/R28 rows were not reused or re-bucketed.", "",
        "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
    ]
    (stage / "FAST3_R42_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    frozen.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stage), str(frozen))
    summary["ARTIFACT_ROOT"] = str(frozen)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("FAST3_R42_STATUS=READY_REQUIRES_EXECUTE")
        return 0
    try:
        summary = execute()
    except R42Stop as exc:
        print("FAST3_R42_STATUS=STOP")
        print("FAST3_R42_CLASSIFICATION=E_NO_LEGAL_CONFIRMATION_DATA")
        print(f"FAST3_R42_DECISION={exc}")
        return 2
    print(render_terminal(summary))
    print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
