#!/usr/bin/env python
"""FAST3 R42R deterministic preregistration/freeze repair only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
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
AUTHORITATIVE_ROOT = RESULTS / "frozen/fast3/r42r_frozen_confirmation_preregistration_repair_r1"
STAGING_ROOT = RESULTS / "scratch/fast3/.r42r_frozen_confirmation_preregistration_repair_r1.staging"

R41_SOURCE = REPO / "fast3/scripts/run/fast3_r41_independent_economic_score_alignment_r1.py"
R41_ROOT = RESULTS / "frozen/fast3/r41_independent_economic_score_alignment_r1_20260810T151254Z"
R41_SUMMARY = R41_ROOT / "FAST3_R41_SUMMARY.json"
R41_PREREG = R41_ROOT / "FAST3_R41_PREREGISTRATION_R1.json"
R41_QUINTILE_METRICS = R41_ROOT / "FAST3_R41_QUINTILE_ECONOMIC_METRICS.csv"
R41_SCORE_ROOT = RESULTS / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R41_SCORE_PATHS = {
    head: R41_SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
    for head in ("UP", "DOWN")
}
R36_ROOT = RESULTS / "frozen/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z"
R36_PREREG = R36_ROOT / "FAST3_R36_PREREGISTRATION_R1.json"
R36_SUMMARY = R36_ROOT / "FAST3_R36_SUMMARY.json"
R36_SOURCE = REPO / "fast3/scripts/run/fast3_r36_payoff_path_decomposition_r1.py"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"
ACTION_LEDGER = RESULTS / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORPORATE_ACTION_LEDGER.json"

R28_ROOT = RESULTS / "frozen/fast3/r28_phase3_20260808T131135Z"
R28_IDENTITY = R28_ROOT / "R28_PHASE3_RESEARCH_IDENTITY.json"
R28_READY = R28_ROOT / "R28_PROSPECTIVE_SHADOW_R1_READY_MANIFEST.json"
R28_REGISTRATION = R28_ROOT / "R28_PROSPECTIVE_SHADOW_REGISTRATION.json"
R28_SCORER = REPO / "fast3/scripts/run/fast3_r28_prospective_shadow_launcher.py"
R28_MODELS = {
    "UP": R28_ROOT / "models/R28_3_UP_FINAL.joblib",
    "DOWN": R28_ROOT / "models/R28_3_DOWN_FINAL.joblib",
}

HORIZONS = (5, 10, 15, 30, 60)
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
BOUNDARY_PAIRS = (("Q1", "Q2"), ("Q2", "Q3"), ("Q3", "Q4"), ("Q4", "Q5"))
LEDGER_SCHEMA = (
    "candidate_id", "decision_ts", "direction", "execution_symbol", "r28_score", "frozen_quintile",
    "return_5m_net20", "return_10m_net20", "return_15m_net20", "return_30m_net20", "return_60m_net20",
    "path_complete_5m", "path_complete_10m", "path_complete_15m", "path_complete_30m", "path_complete_60m",
    "corporate_action_status", "model_identity_sha256", "feature_identity_sha256",
    "threshold_identity_sha256", "eligibility_status",
)
EXPECTED = {
    "R41_SOURCE": "b6332b375fdee1c42b173c24ddb569ba39e7b9c2dda1ac372ed417c86bf2ff4e",
    "R41_SUMMARY": "747f27210e63bfbf6eb5f5032905929f14296e1e9442d3021caf86a379898bd5",
    "R41_PREREG": "06471c07370e2b689e42404e8d0502a3344f1cec1a8b1afdfe845b65e30bd2de",
    "UP_SCORE_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_SCORE_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
    "R36_PREREG": "da2a4493a252618798998de458855a39c9ced09bb8952dac11f76d13d9cdbb61",
    "R36_SUMMARY": "1f90403dc33c1f222a3732bc39b9d507217857c4e74ab389fa2eece3edd7647f",
    "R36_SOURCE": "c0e6cf1270556a0c0bf53ce9a1d5fc7f342b582d33dba16cc6cd30dea5c78752",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "ACTION_LEDGER": "3a72c80d4bce04e409ed429b9434e9f936405e1ffc38ac3ee04213675781a0dd",
}
BOUNDARY_INCLUSIVITY_RULE = (
    "Q1: score <= b1; Q2: b1 < score <= b2; Q3: b2 < score <= b3; "
    "Q4: b3 < score <= b4; Q5: score > b4"
)
TIE_HANDLING_RULE = (
    "R41 discovery identity uses stable mergesort ascending by "
    "(score, decision_timestamp_utc, candidate_id), then floor(position*5/n); "
    "all eight reconstructed cutpoints have strict lower_max < upper_min, so no tie crosses a boundary; "
    "for future rows score exactly equal to a frozen boundary is assigned to the lower quintile"
)
QUINTILE_SEMANTICS = (
    "Within each direction, stable equal-count positional rank after ascending mergesort on "
    "(score, decision_timestamp_utc, candidate_id); bucket_index=min(floor(position*5/n),4)"
)


class IdentityStop(RuntimeError):
    pass


class BoundaryStop(RuntimeError):
    pass


class IntegrityStop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def verify_frozen_hashes() -> dict[str, str]:
    paths = {
        "R41_SOURCE": R41_SOURCE, "R41_SUMMARY": R41_SUMMARY, "R41_PREREG": R41_PREREG,
        "UP_SCORE_LEDGER": R41_SCORE_PATHS["UP"], "DOWN_SCORE_LEDGER": R41_SCORE_PATHS["DOWN"],
        "R36_PREREG": R36_PREREG, "R36_SUMMARY": R36_SUMMARY, "R36_SOURCE": R36_SOURCE,
        "R36_LEDGER": R36_LEDGER, "ACTION_LEDGER": ACTION_LEDGER,
    }
    if any(not path.is_file() for path in paths.values()):
        raise IdentityStop("STOP_REQUIRED_FROZEN_LINEAGE_MISSING")
    observed = {name: sha256(path) for name, path in paths.items()}
    if observed != EXPECTED:
        raise IdentityStop("STOP_FROZEN_LINEAGE_HASH_MISMATCH")
    summary = json.loads(R41_SUMMARY.read_text(encoding="utf-8"))
    if (summary.get("FAST3_R41_CLASSIFICATION") != "A_INDEPENDENT_ECONOMIC_SCORE_ALIGNMENT_CONFIRMED"
            or summary.get("ALIGNMENT_INPUT_COUNT") != 1197
            or summary.get("ALIGNMENT_MATCHED_COUNT") != 1197
            or summary.get("ALIGNMENT_DUPLICATE_COUNT") != 0
            or summary.get("ALIGNMENT_UNMATCHED_COUNT") != 0):
        raise IdentityStop("STOP_R41_AUTHORITATIVE_IDENTITY_MISMATCH")
    prereg = json.loads(R41_PREREG.read_text(encoding="utf-8"))
    if prereg.get("QUINTILE_METHOD") != (
        "Within each direction, stable equal-count rank after sort(score, decision_timestamp, candidate_id); "
        "outcome-blind and shared across OOF folds"
    ):
        raise IdentityStop("STOP_R41_QUINTILE_SEMANTICS_MISMATCH")
    return observed


def load_r41_source():
    spec = importlib.util.spec_from_file_location("r41_frozen_for_r42r", R41_SOURCE)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise IdentityStop("STOP_R41_SOURCE_LOAD_FAILURE")
    spec.loader.exec_module(module)
    return module


def identity_csv_bytes(frame: pd.DataFrame) -> bytes:
    columns = ["candidate_id", "decision_ts", "direction", "frozen_r28_score", "r41_quintile"]
    buffer = io.StringIO(newline="")
    frame.loc[:, columns].to_csv(buffer, index=False, lineterminator="\n", float_format="%.17g")
    return buffer.getvalue().encode("utf-8")


def load_discovery_scores() -> tuple[pd.DataFrame, dict[str, Any]]:
    # Only identity columns are read.  No fixed-horizon or other economic return
    # column is accessed by this repair.
    cohort = pd.read_parquet(R36_LEDGER, columns=["candidate_id", "decision_timestamp_utc", "head"])
    input_count = len(cohort)
    duplicate_count = int(cohort["candidate_id"].duplicated().sum())
    score_columns = [
        "candidate_id", "decision_timestamp_utc", "direction", "probability", "selected", "head",
        "validation_slice", "model_sha256", "feature_manifest_sha256", "frozen_threshold",
    ]
    score = pd.concat(
        [pd.read_parquet(R41_SCORE_PATHS[head], columns=score_columns) for head in ("UP", "DOWN")],
        ignore_index=True,
    )
    joined = cohort.merge(score, on="candidate_id", how="left", validate="one_to_one",
                          suffixes=("_cohort", "_score"), indicator=True)
    matched = int(joined["_merge"].eq("both").sum())
    missing = input_count - matched
    if input_count != 1197 or duplicate_count or missing:
        raise IdentityStop("STOP_R41_DISCOVERY_JOIN_IDENTITY")
    left_ts = pd.to_datetime(joined["decision_timestamp_utc_cohort"], utc=True, errors="raise")
    right_ts = pd.to_datetime(joined["decision_timestamp_utc_score"], utc=True, errors="raise")
    if (not np.array_equal(left_ts.to_numpy(dtype="datetime64[us]"), right_ts.to_numpy(dtype="datetime64[us]"))
            or not joined["head_cohort"].eq(joined["head_score"]).all()
            or not joined["head_cohort"].eq(joined["direction"]).all()
            or not joined["selected"].eq(True).all()):
        raise IdentityStop("STOP_R41_DISCOVERY_SCORE_ROW_IDENTITY")
    frame = pd.DataFrame({
        "candidate_id": joined["candidate_id"].astype(str),
        "decision_timestamp_utc": left_ts,
        "direction": joined["direction"].astype(str),
        "score": pd.to_numeric(joined["probability"], errors="raise").astype(float),
        "validation_slice": joined["validation_slice"].astype(str),
        "model_sha256": joined["model_sha256"].astype(str),
        "feature_manifest_sha256": joined["feature_manifest_sha256"].astype(str),
        "frozen_threshold": pd.to_numeric(joined["frozen_threshold"], errors="raise").astype(float),
    })
    if frame[["candidate_id", "decision_timestamp_utc", "direction", "score"]].isna().any().any():
        raise IdentityStop("STOP_R41_DISCOVERY_SCORE_MISSING")
    metadata = {
        "R41_DISCOVERY_INPUT_COUNT": input_count,
        "R41_DISCOVERY_MATCHED_SCORE_COUNT": matched,
        "R41_DISCOVERY_DUPLICATE_COUNT": duplicate_count,
        "R41_DISCOVERY_MISSING_SCORE_COUNT": missing,
        "DIRECTION_COUNTS": {head: int(frame["direction"].eq(head).sum()) for head in ("UP", "DOWN")},
        "OOF_MODEL_SHA256_BY_DIRECTION": {
            head: sorted(frame.loc[frame["direction"].eq(head), "model_sha256"].unique().tolist())
            for head in ("UP", "DOWN")
        },
        "OOF_FEATURE_MANIFEST_SHA256_BY_DIRECTION": {
            head: sorted(frame.loc[frame["direction"].eq(head), "feature_manifest_sha256"].unique().tolist())
            for head in ("UP", "DOWN")
        },
        "OOF_FROZEN_THRESHOLDS_BY_DIRECTION": {
            head: sorted(float(x) for x in frame.loc[frame["direction"].eq(head), "frozen_threshold"].unique())
            for head in ("UP", "DOWN")
        },
    }
    return frame, metadata


def assign_by_boundaries(scores: pd.Series, boundaries: list[float]) -> pd.Series:
    values = pd.to_numeric(scores, errors="raise").to_numpy(dtype=float)
    index = np.searchsorted(np.asarray(boundaries, dtype=float), values, side="left")
    return pd.Series([QUINTILES[int(value)] for value in index], index=scores.index, dtype="object")


def reconstruct_boundaries(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    r41 = load_r41_source()
    original = r41.stable_quintiles(frame[["candidate_id", "decision_timestamp_utc", "direction", "score"]].copy())
    work = frame.copy()
    work["r41_quintile"] = original
    boundary_payload: dict[str, Any] = {
        "R41_QUINTILE_IMPLEMENTATION_SOURCE_FILE": str(R41_SOURCE),
        "R41_QUINTILE_IMPLEMENTATION_SOURCE_SHA256": EXPECTED["R41_SOURCE"],
        "R41_QUINTILE_IMPLEMENTATION_SYMBOL": "stable_quintiles",
        "R41_QUINTILE_SEMANTICS": QUINTILE_SEMANTICS,
        "BOUNDARY_INCLUSIVITY_RULE": BOUNDARY_INCLUSIVITY_RULE,
        "TIE_HANDLING_RULE": TIE_HANDLING_RULE,
        "DIRECTIONS": {},
    }
    for head in ("UP", "DOWN"):
        part = work.loc[work["direction"].eq(head)].copy()
        boundaries: list[float] = []
        anchors: list[dict[str, Any]] = []
        for lower, upper in BOUNDARY_PAIRS:
            lower_max = float(part.loc[part["r41_quintile"].eq(lower), "score"].max())
            upper_min = float(part.loc[part["r41_quintile"].eq(upper), "score"].min())
            if not lower_max < upper_min:
                raise BoundaryStop(f"STOP_CROSS_BUCKET_SCORE_TIE:{head}:{lower}:{upper}")
            boundaries.append(lower_max)
            anchors.append({"lower_bucket": lower, "upper_bucket": upper,
                            "lower_bucket_max_score": lower_max, "upper_bucket_min_score": upper_min,
                            "strict_gap": True})
        reconstructed = assign_by_boundaries(part["score"], boundaries)
        reconstructed.index = part.index
        matches = int(reconstructed.eq(part["r41_quintile"]).sum())
        total = len(part)
        rate = matches / total if total else 0.0
        if rate != 1.0:
            raise BoundaryStop(f"STOP_QUINTILE_ASSIGNMENT_REPRODUCTION:{head}:{rate}")
        boundary_payload["DIRECTIONS"][head] = {
            "BOUNDARIES": {f"{lower}_{upper}": value for (lower, upper), value in zip(BOUNDARY_PAIRS, boundaries)},
            "BOUNDARY_ANCHORS": anchors,
            "QUINTILE_COUNTS": {quintile: int(part["r41_quintile"].eq(quintile).sum()) for quintile in QUINTILES},
            "QUINTILE_ASSIGNMENT_MATCH_COUNT": matches,
            "QUINTILE_ASSIGNMENT_TOTAL_COUNT": total,
            "QUINTILE_ASSIGNMENT_MATCH_RATE": rate,
            "CROSS_BOUNDARY_TIE_COUNT": 0,
        }
    identity = work[["candidate_id", "decision_timestamp_utc", "direction", "score", "r41_quintile"]].copy()
    identity = identity.sort_values(["direction", "score", "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    identity = identity.rename(columns={"decision_timestamp_utc": "decision_ts", "score": "frozen_r28_score"})
    identity["decision_ts"] = pd.to_datetime(identity["decision_ts"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    identity = identity.reset_index(drop=True)
    return identity, boundary_payload


def verify_r28_production_identity() -> dict[str, Any]:
    required = [R28_IDENTITY, R28_READY, R28_REGISTRATION, R28_SCORER, *R28_MODELS.values()]
    if any(not path.is_file() for path in required):
        raise IntegrityStop("STOP_R28_PRODUCTION_IDENTITY_MISSING")
    identity = json.loads(R28_IDENTITY.read_text(encoding="utf-8"))
    ready = json.loads(R28_READY.read_text(encoding="utf-8"))
    registration = json.loads(R28_REGISTRATION.read_text(encoding="utf-8"))
    model_hashes = {head: sha256(path) for head, path in R28_MODELS.items()}
    if model_hashes != identity.get("r28_model_sha256") or model_hashes != ready.get("r28_model_sha256"):
        raise IntegrityStop("STOP_R28_PRODUCTION_MODEL_HASH_MISMATCH")
    if (identity.get("candidate") != "R28_3_CROSS_ASSET_FLOW"
            or identity.get("feature_change_allowed") is not False
            or identity.get("threshold_optimization_allowed") is not False
            or registration.get("historical_backfill_allowed") is not False):
        raise IntegrityStop("STOP_R28_PRODUCTION_CONTRACT_MISMATCH")
    feature_payload = {"features": identity["features"], "feature_count": identity["feature_count"],
                       "feature_manifest_sha256": ready["feature_manifest_sha256"]}
    threshold_payload = {"thresholds": identity["thresholds"]}
    model_payload = {"candidate": identity["candidate"], "model_sha256": model_hashes}
    return {
        "CANDIDATE": identity["candidate"],
        "MODEL_SHA256_BY_DIRECTION": model_hashes,
        "MODEL_IDENTITY_SHA256": canonical_sha256(model_payload),
        "FEATURES": identity["features"],
        "FEATURE_COUNT": identity["feature_count"],
        "FEATURE_MANIFEST_SHA256": ready["feature_manifest_sha256"],
        "FEATURE_IDENTITY_SHA256": canonical_sha256(feature_payload),
        "THRESHOLDS": identity["thresholds"],
        "THRESHOLD_IDENTITY_SHA256": canonical_sha256(threshold_payload),
        "PROSPECTIVE_SCORER_SOURCE_FILE": str(R28_SCORER),
        "PROSPECTIVE_SCORER_SOURCE_SHA256": sha256(R28_SCORER),
        "ORIGINAL_R28_PROSPECTIVE_REGISTRATION_UTC": registration["registration_utc"],
    }


def payoff_contract() -> dict[str, Any]:
    prereg = json.loads(R36_PREREG.read_text(encoding="utf-8"))
    action = json.loads(ACTION_LEDGER.read_text(encoding="utf-8"))
    if (prereg.get("FIXED_HORIZONS_MINUTES") != list(HORIZONS)
            or prereg.get("FIXED_HORIZON_RETURN") != "entry open to exact +N minute open, then subtract frozen 20bps once"
            or action.get("price_basis") != "RAW"
            or action.get("normalization_layer") != "ECONOMIC_RETURN_ONLY"
            or action.get("record_count") != 9):
        raise IntegrityStop("STOP_R36_R41_PAYOFF_CONTRACT_MISMATCH")
    entry = (
        "Exact one-minute RAW open of execution_symbol at frozen entry_timestamp; "
        "the bar must exist uniquely and match the frozen raw entry price"
    )
    exit_contract = lambda minute: (
        f"Exact one-minute RAW open of execution_symbol at entry_timestamp+{minute} calendar minutes; "
        "no fallback bar and no target/barrier/score/path-dependent termination; "
        "NET20=exit_open/(entry_open*corporate_action_factor)-1-0.002"
    )
    return {
        "AUTHORITATIVE_SOURCE": "FAST3_R36_PAYOFF_PATH_DECOMPOSITION_R1 as consumed by FAST3_R41",
        "R36_PREREGISTRATION_SHA256": EXPECTED["R36_PREREG"],
        "R36_SOURCE_SHA256": EXPECTED["R36_SOURCE"],
        "CORPORATE_ACTION_LEDGER_SHA256": EXPECTED["ACTION_LEDGER"],
        "ENTRY_PRICE_CONTRACT": entry,
        **{f"H{minute}_EXIT_PRICE_CONTRACT": exit_contract(minute) for minute in HORIZONS},
        "CORPORATE_ACTION_NORMALIZATION_CONTRACT": (
            "RAW price basis with ECONOMIC_RETURN_ONLY normalization; for actions satisfying "
            "entry_timestamp < effective_timestamp <= exit_timestamp, corporate_action_factor is the product "
            "of frozen pre_to_post_price_multiplier values; otherwise factor=1.0"
        ),
        "NET20_CONTRACT": "corrected_gross_return - 0.002 (20bps exactly once)",
        "PATH_COMPLETENESS_CONTRACT": "exact entry and every required exact horizon exit bar must exist uniquely",
        "EXIT_DEPENDS_ON_TARGET_FIRST": False,
        "EXIT_DEPENDS_ON_BARRIER_TOUCH": False,
        "EXIT_DEPENDS_ON_R28_SCORE": False,
        "EXIT_IS_PATH_DEPENDENT": False,
    }


def reconstruction() -> tuple[pd.DataFrame, dict[str, Any]]:
    hashes = verify_frozen_hashes()
    scores, score_metadata = load_discovery_scores()
    identity, boundaries = reconstruct_boundaries(scores)
    identity_bytes = identity_csv_bytes(identity)
    payload = {
        **score_metadata,
        "R41_DISCOVERY_SCORE_LEDGER_SHA256": hashlib.sha256(identity_bytes).hexdigest(),
        "R41_FROZEN_LINEAGE_SHA256": hashes,
        "BOUNDARY_CONTRACT": boundaries,
    }
    payload["RECONSTRUCTION_IDENTITY_SHA256"] = canonical_sha256(payload)
    return identity, payload


def preregistration(created_at: str, reconstruction_payload: dict[str, Any],
                    production_identity: dict[str, Any], payoff: dict[str, Any]) -> dict[str, Any]:
    eligibility = (
        "Eligible iff: (1) signal was frozen by the authoritative R28 production/prospective scorer; "
        "(2) direction-specific model artifact hash exactly matches the frozen R28 identity; "
        "(3) feature identity hash exactly matches; (4) threshold identity hash exactly matches; "
        "(5) decision_ts is strictly greater than CONFIRMATION_ACTIVATION_TS; "
        "(6) score/decision was append-only frozen before any subsequent economic outcome was observed; "
        "(7) all exact fixed-horizon price bars required for the row are legal and complete; "
        "(8) frozen corporate-action normalization passes; (9) candidate_id is globally unique"
    )
    return {
        "CONTRACT_ID": "FAST3_R42R_FROZEN_CONFIRMATION_PREREGISTRATION_REPAIR_R1",
        "STATUS": "AUTHORITATIVE_FROZEN_BEFORE_ANY_ELIGIBLE_CONFIRMATION_OUTCOME",
        "R42R_PREREGISTRATION_CREATED_AT_UTC": created_at,
        "CONFIRMATION_ACTIVATION_TS": created_at,
        "ACTIVATION_INCLUSIVITY_RULE": "decision_ts must be strictly greater than CONFIRMATION_ACTIVATION_TS",
        "RESEARCH_NATURE": "PREREGISTRATION_FREEZE_REPAIR_ONLY",
        "PRIMARY_DIRECTION": "DOWN",
        "SECONDARY_DIRECTION": "UP",
        "PRIMARY_DIRECTION_SOURCE": "R41 preregistered discovery conclusion; not reselected in R42R",
        "PRIMARY_HYPOTHESIS": (
            "DOWN frozen R28 score preserves positive economic ordering for independent fixed-horizon NET20 "
            "in the future eligible confirmation cohort"
        ),
        "UP_CANNOT_REPLACE_FAILED_DOWN_PRIMARY": True,
        "FROZEN_HORIZONS_MINUTES": list(HORIZONS),
        "ALL_HORIZONS_RETAINED_EQUALLY": True,
        "FROZEN_SCORE_BUCKETS": list(QUINTILES),
        "R41_DISCOVERY_SCORE_IDENTITY": reconstruction_payload,
        "R28_PRODUCTION_IDENTITY": production_identity,
        "INDEPENDENT_PAYOFF_CONTRACT": payoff,
        "CONFIRMATION_ELIGIBILITY_RULE": eligibility,
        "APPEND_ONLY_CONFIRMATION_LEDGER": True,
        "CONFIRMATION_LEDGER_SCHEMA": list(LEDGER_SCHEMA),
        "HISTORICAL_ROW_MUTATION_ALLOWED": False,
        "EXTRA_RESEARCH_LEDGER_FIELDS_ALLOWED": False,
        "SAMPLE_SIZE_GATES": {
            "DOWN_FIRST_CONFIRMATION_GATE": 50,
            "DOWN_SECOND_MILESTONE": 100,
            "DOWN_COUNT_LT_50_ACTION": "NO_SUBSTANTIVE_CONFIRMATION_TEST_WAIT_FOR_MORE_DATA",
            "DOWN_COUNT_GTE_100_ROLE": "STRONGER_EVIDENCE_MILESTONE_ONLY_NOT_A_NEW_HYPOTHESIS_TEST",
            "UP_IS_SECONDARY_ONLY": True,
        },
        "ECONOMIC_RESULT_BLINDED_UNTIL_GATE": True,
        "PRE_GATE_ALLOWED_OUTPUTS": ["signal_count", "path_completion_status"],
        "PRE_GATE_FORMAL_OUTPUTS_FORBIDDEN": [
            "Spearman", "Q5_minus_Q1_mean", "Profit_Factor", "best_horizon", "economic_candidate",
        ],
        "PRIMARY_DOWN_PASS_RULE": {
            "A": ">=3 of 5 horizons have Spearman(score, NET20)>0",
            "B": ">=3 of 5 horizons have Q5 mean NET20>Q1 mean NET20",
            "C": ">=2 of 5 horizons have MONOTONIC_POSITIVE or MOSTLY_POSITIVE mean NET20 ordering",
            "D": (
                ">=3 horizons retain Q5 mean NET20>Q1 mean NET20 both after excluding exactly one best "
                "and after excluding exactly one worst direction-horizon trade; equal extremes remove the "
                "lexicographically first candidate_id"
            ),
            "PASS": "A and B and C and D must all pass",
        },
        "ORDERING_RULES": {
            "MONOTONIC_POSITIVE": "all four adjacent differences >=0",
            "MOSTLY_POSITIVE": "at least three adjacent differences >0 and Q5>Q1",
            "MONOTONIC_NEGATIVE": "all four adjacent differences <=0, evaluated after positive rule",
            "NON_MONOTONIC": "otherwise",
        },
        "TAIL_ROBUSTNESS": {
            "WINSORIZATION": "fixed 1%/99%, robustness only and never replaces raw metrics",
            "SINGLE_EXTREME_EXCLUSION": "exactly one best and one worst trade evaluated separately",
        },
        "DOWN_POSITIVE_ECONOMIC_CANDIDATE_RULE": (
            ">=2 independent horizons simultaneously have Q5_MEAN_NET20>0, Q5_PROFIT_FACTOR>1, "
            "and Q5_MEAN_NET20>Q1_MEAN_NET20"
        ),
        "MAX_RESEARCH_ITERATION_COUNT": 1,
        "MAX_NEW_FEATURE_COUNT": 0,
        "MAX_NEW_MODEL_COUNT": 0,
        "MAX_NEW_TARGET_COUNT": 0,
        "HORIZON_COUNT": 5,
        "SCORE_BUCKET_COUNT": 5,
        "MODEL_FIT_ALLOWED": False,
        "MODEL_PREDICT_CALL_ALLOWED": False,
        "R28_REFIT_ALLOWED": False,
        "R28_RESCORE_ALLOWED": False,
        "R28_THRESHOLD_CHANGE_ALLOWED": False,
        "NO_SECOND_ROUND_ANALYSIS": True,
        "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "NO_RESEARCH_CHOICE_CHANGE": True,
        "NO_CONFIRMATION_OUTCOME_READ": True,
        "AUTHORITATIVE_FILE_HASH_SEMANTICS": (
            "R42R_PREREGISTRATION_SHA256 is the SHA256 of this exact UTF-8 JSON file including its final newline; "
            "the digest is stored in FAST3_R42R_SUMMARY.json and the .sha256 sidecar, not self-embedded"
        ),
    }


def flatten_summary(contract: dict[str, Any], prereg_hash: str, identity_csv_hash: str,
                    deterministic_status: str) -> dict[str, Any]:
    reconstruction_payload = contract["R41_DISCOVERY_SCORE_IDENTITY"]
    boundary = reconstruction_payload["BOUNDARY_CONTRACT"]
    production = contract["R28_PRODUCTION_IDENTITY"]
    summary: dict[str, Any] = {
        "FAST3_R42R_STATUS": "PASS",
        "FAST3_R42R_CLASSIFICATION": "A_FROZEN_CONFIRMATION_PREREGISTRATION_REPAIRED",
        "FAST3_R42R_DECISION": "BEGIN_PROSPECTIVE_CONFIRMATION_ACCUMULATION",
        "NEXT_STAGE": "BEGIN_PROSPECTIVE_CONFIRMATION_ACCUMULATION",
        "R41_DISCOVERY_INPUT_COUNT": reconstruction_payload["R41_DISCOVERY_INPUT_COUNT"],
        "R41_DISCOVERY_MATCHED_SCORE_COUNT": reconstruction_payload["R41_DISCOVERY_MATCHED_SCORE_COUNT"],
        "R41_DISCOVERY_DUPLICATE_COUNT": reconstruction_payload["R41_DISCOVERY_DUPLICATE_COUNT"],
        "R41_DISCOVERY_MISSING_SCORE_COUNT": reconstruction_payload["R41_DISCOVERY_MISSING_SCORE_COUNT"],
        "R41_DISCOVERY_SCORE_LEDGER_SHA256": identity_csv_hash,
        "R41_QUINTILE_IMPLEMENTATION_SOURCE_FILE": boundary["R41_QUINTILE_IMPLEMENTATION_SOURCE_FILE"],
        "R41_QUINTILE_IMPLEMENTATION_SYMBOL": boundary["R41_QUINTILE_IMPLEMENTATION_SYMBOL"],
        "R41_QUINTILE_SEMANTICS": boundary["R41_QUINTILE_SEMANTICS"],
        "BOUNDARY_INCLUSIVITY_RULE": boundary["BOUNDARY_INCLUSIVITY_RULE"],
        "TIE_HANDLING_RULE": boundary["TIE_HANDLING_RULE"],
        "PRIMARY_DIRECTION": "DOWN", "SECONDARY_DIRECTION": "UP",
        "FROZEN_HORIZONS_MINUTES": list(HORIZONS),
        "CONFIRMATION_ACTIVATION_TS": contract["CONFIRMATION_ACTIVATION_TS"],
        "R42R_PREREGISTRATION_CREATED_AT_UTC": contract["R42R_PREREGISTRATION_CREATED_AT_UTC"],
        "CONFIRMATION_ELIGIBILITY_RULE": contract["CONFIRMATION_ELIGIBILITY_RULE"],
        "DOWN_FIRST_CONFIRMATION_GATE": 50, "DOWN_SECOND_MILESTONE": 100,
        "ECONOMIC_RESULT_BLINDED_UNTIL_GATE": True,
        "R28_MODEL_IDENTITY_FROZEN": True, "R28_FEATURE_IDENTITY_FROZEN": True,
        "R28_THRESHOLD_IDENTITY_FROZEN": True,
        "R28_MODEL_IDENTITY_SHA256": production["MODEL_IDENTITY_SHA256"],
        "R28_FEATURE_IDENTITY_SHA256": production["FEATURE_IDENTITY_SHA256"],
        "R28_THRESHOLD_IDENTITY_SHA256": production["THRESHOLD_IDENTITY_SHA256"],
        "APPEND_ONLY_CONFIRMATION_LEDGER": True,
        "R42R_PREREGISTRATION_SHA256": prereg_hash,
        "DETERMINISTIC_BOUNDARY_RECONSTRUCTION_STATUS": deterministic_status,
        "PREREGISTRATION_IMMUTABILITY_STATUS": "PASS_AUTHORITATIVE_CREATED_ONCE_VERIFY_ONLY",
        "MAX_RESEARCH_ITERATION_COUNT": 1, "MAX_NEW_FEATURE_COUNT": 0, "MAX_NEW_MODEL_COUNT": 0,
        "MAX_NEW_TARGET_COUNT": 0, "HORIZON_COUNT": 5, "SCORE_BUCKET_COUNT": 5,
        "NO_SECOND_ROUND_ANALYSIS": True, "NO_AUTOMATIC_FOLLOWUP_EXPERIMENT": True,
        "NO_RESEARCH_CHOICE_CHANGE": True, "NO_CONFIRMATION_OUTCOME_READ": True,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "R28_REFIT_COUNT": 0, "R28_THRESHOLD_CHANGE_COUNT": 0,
        "PIT_STATUS": "PASS_R41_OOF_PIT_LINEAGE_REPRODUCED",
        "OOF_INTEGRITY_STATUS": "PASS_R41_SCORE_IDENTITY_EXACT",
        "CORPORATE_ACTION_STATUS": "PASS_R36_R41_FROZEN_CONTRACT_REFERENCED",
        "STORAGE_CONTRACT_STATUS": "PASS_FAST3_STORAGE_CONTRACT_R1_EXTERNAL_FROZEN_ONLY",
        "DATA_ROOT_WRITE_COUNT": 0, "REPO_RESULT_FILE_COUNT": 0,
    }
    for head in ("UP", "DOWN"):
        direction = boundary["DIRECTIONS"][head]
        for pair, value in direction["BOUNDARIES"].items():
            summary[f"{head}_{pair}_BOUNDARY"] = value
        summary[f"{head}_QUINTILE_ASSIGNMENT_MATCH_COUNT"] = direction["QUINTILE_ASSIGNMENT_MATCH_COUNT"]
        summary[f"{head}_QUINTILE_ASSIGNMENT_TOTAL_COUNT"] = direction["QUINTILE_ASSIGNMENT_TOTAL_COUNT"]
        summary[f"{head}_QUINTILE_ASSIGNMENT_MATCH_RATE"] = direction["QUINTILE_ASSIGNMENT_MATCH_RATE"]
    return summary


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R42R_STATUS", "FAST3_R42R_CLASSIFICATION", "FAST3_R42R_DECISION",
        "R41_DISCOVERY_INPUT_COUNT", "R41_DISCOVERY_MATCHED_SCORE_COUNT",
        "R41_DISCOVERY_DUPLICATE_COUNT", "R41_DISCOVERY_MISSING_SCORE_COUNT",
        "R41_DISCOVERY_SCORE_LEDGER_SHA256",
        "UP_Q1_Q2_BOUNDARY", "UP_Q2_Q3_BOUNDARY", "UP_Q3_Q4_BOUNDARY", "UP_Q4_Q5_BOUNDARY",
        "DOWN_Q1_Q2_BOUNDARY", "DOWN_Q2_Q3_BOUNDARY", "DOWN_Q3_Q4_BOUNDARY", "DOWN_Q4_Q5_BOUNDARY",
        "BOUNDARY_INCLUSIVITY_RULE", "TIE_HANDLING_RULE",
        "UP_QUINTILE_ASSIGNMENT_MATCH_RATE", "DOWN_QUINTILE_ASSIGNMENT_MATCH_RATE",
        "PRIMARY_DIRECTION", "SECONDARY_DIRECTION", "FROZEN_HORIZONS_MINUTES",
        "CONFIRMATION_ACTIVATION_TS", "DOWN_FIRST_CONFIRMATION_GATE", "DOWN_SECOND_MILESTONE",
        "ECONOMIC_RESULT_BLINDED_UNTIL_GATE", "R28_MODEL_IDENTITY_FROZEN",
        "R28_FEATURE_IDENTITY_FROZEN", "R28_THRESHOLD_IDENTITY_FROZEN",
        "APPEND_ONLY_CONFIRMATION_LEDGER", "R42R_PREREGISTRATION_SHA256",
        "DETERMINISTIC_BOUNDARY_RECONSTRUCTION_STATUS", "PREREGISTRATION_IMMUTABILITY_STATUS",
        "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "R28_REFIT_COUNT", "R28_THRESHOLD_CHANGE_COUNT",
        "PIT_STATUS", "OOF_INTEGRITY_STATUS", "CORPORATE_ACTION_STATUS", "STORAGE_CONTRACT_STATUS", "NEXT_STAGE",
    ]
    def value(item: Any) -> str:
        if isinstance(item, bool): return str(item).lower()
        if isinstance(item, list): return "[" + ",".join(map(str, item)) + "]"
        return str(item)
    return "\n".join(f"{key}={value(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    if AUTHORITATIVE_ROOT.exists():
        raise IntegrityStop("STOP_AUTHORITATIVE_PREREGISTRATION_ALREADY_EXISTS_USE_VERIFY")
    if STAGING_ROOT.exists():
        raise IntegrityStop("STOP_STAGING_PATH_ALREADY_EXISTS")
    STAGING_ROOT.mkdir(parents=True)
    identity, first = reconstruction()
    # Independent pure replay of boundary construction before activation freeze.
    scores, _ = load_discovery_scores()
    replay_identity, replay_boundaries = reconstruct_boundaries(scores)
    if (hashlib.sha256(identity_csv_bytes(identity)).hexdigest()
            != hashlib.sha256(identity_csv_bytes(replay_identity)).hexdigest()
            or canonical_sha256(first["BOUNDARY_CONTRACT"]) != canonical_sha256(replay_boundaries)):
        raise BoundaryStop("STOP_NONDETERMINISTIC_BOUNDARY_RECONSTRUCTION")
    deterministic = "PASS_RECONSTRUCTED_TWICE_IDENTICAL"
    production = verify_r28_production_identity()
    payoff = payoff_contract()
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    contract = preregistration(created_at, first, production, payoff)
    prereg_path = STAGING_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
    write_json(prereg_path, contract)
    prereg_hash = sha256(prereg_path)
    (STAGING_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json.sha256").write_text(
        prereg_hash + "\n", encoding="ascii"
    )
    identity_path = STAGING_ROOT / "FAST3_R42R_DISCOVERY_SCORE_IDENTITY.csv"
    identity_path.write_bytes(identity_csv_bytes(identity))
    identity_hash = sha256(identity_path)
    if identity_hash != first["R41_DISCOVERY_SCORE_LEDGER_SHA256"]:
        raise IntegrityStop("STOP_DISCOVERY_IDENTITY_FILE_HASH_MISMATCH")
    write_json(STAGING_ROOT / "FAST3_R42R_QUINTILE_BOUNDARIES.json", first["BOUNDARY_CONTRACT"])
    summary = flatten_summary(contract, prereg_hash, identity_hash, deterministic)
    summary.update({
        "RUN_MODE": "CREATE_AUTHORITATIVE_ONCE",
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    })
    write_json(STAGING_ROOT / "FAST3_R42R_SUMMARY.json", summary)
    report = [
        "# FAST3 R42R Frozen Confirmation Preregistration Repair R1", "",
        "This artifact repairs only the missing R41 score-bucket freeze. It performs no model fit, prediction, rescore, economic analysis, or confirmation outcome read.", "",
        f"- Classification: `{summary['FAST3_R42R_CLASSIFICATION']}`",
        f"- Decision: `{summary['FAST3_R42R_DECISION']}`",
        f"- Activation: `{summary['CONFIRMATION_ACTIVATION_TS']}`",
        f"- Preregistration SHA256: `{prereg_hash}`", "",
        "Future confirmation must verify the exact preregistration file hash before accepting any row. Only decision timestamps strictly later than activation are eligible.", "",
        "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
    ]
    (STAGING_ROOT / "FAST3_R42R_CONTRACT.md").write_text("\n".join(report), encoding="utf-8")
    AUTHORITATIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGING_ROOT), str(AUTHORITATIVE_ROOT))
    if sha256(AUTHORITATIVE_ROOT / prereg_path.name) != prereg_hash:
        raise IntegrityStop("STOP_POST_FREEZE_PREREGISTRATION_HASH_MISMATCH")
    summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def verify() -> dict[str, Any]:
    prereg_path = AUTHORITATIVE_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
    summary_path = AUTHORITATIVE_ROOT / "FAST3_R42R_SUMMARY.json"
    sidecar_path = AUTHORITATIVE_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json.sha256"
    if any(not path.is_file() for path in (prereg_path, summary_path, sidecar_path)):
        raise IntegrityStop("STOP_AUTHORITATIVE_PREREGISTRATION_MISSING")
    stored = json.loads(summary_path.read_text(encoding="utf-8"))
    contract = json.loads(prereg_path.read_text(encoding="utf-8"))
    expected_hash = sidecar_path.read_text(encoding="ascii").strip()
    if sha256(prereg_path) != expected_hash or stored.get("R42R_PREREGISTRATION_SHA256") != expected_hash:
        raise IntegrityStop("STOP_AUTHORITATIVE_PREREGISTRATION_HASH_MISMATCH")
    identity, current = reconstruction()
    if current["RECONSTRUCTION_IDENTITY_SHA256"] != contract["R41_DISCOVERY_SCORE_IDENTITY"]["RECONSTRUCTION_IDENTITY_SHA256"]:
        raise IdentityStop("STOP_AUTHORITATIVE_RECONSTRUCTION_IDENTITY_MISMATCH")
    identity_path = AUTHORITATIVE_ROOT / "FAST3_R42R_DISCOVERY_SCORE_IDENTITY.csv"
    if not identity_path.is_file() or sha256(identity_path) != hashlib.sha256(identity_csv_bytes(identity)).hexdigest():
        raise IdentityStop("STOP_AUTHORITATIVE_DISCOVERY_SCORE_FILE_MISMATCH")
    stored["RUN_MODE"] = "VERIFY_ONLY_NO_WRITE"
    stored["DETERMINISTIC_BOUNDARY_RECONSTRUCTION_STATUS"] = "PASS_SECOND_PROCESS_VERIFY_IDENTICAL"
    stored["PREREGISTRATION_IMMUTABILITY_STATUS"] = "PASS_HASH_VERIFIED_NO_NEW_ACTIVATION_NO_WRITE"
    stored["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return stored


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        summary = execute() if args.execute else verify()
    except BoundaryStop as exc:
        print("FAST3_R42R_STATUS=STOP")
        print("FAST3_R42R_CLASSIFICATION=B_R41_BOUNDARIES_NOT_REPRODUCIBLE")
        print(f"FAST3_R42R_DECISION=STOP_NO_VALID_CONFIRMATION_BUCKET_FREEZE:{exc}")
        return 2
    except IdentityStop as exc:
        print("FAST3_R42R_STATUS=STOP")
        print("FAST3_R42R_CLASSIFICATION=C_R41_IDENTITY_NOT_REPRODUCIBLE")
        print(f"FAST3_R42R_DECISION=STOP_DISCOVERY_IDENTITY_FAILURE:{exc}")
        return 2
    except IntegrityStop as exc:
        print("FAST3_R42R_STATUS=STOP")
        print("FAST3_R42R_CLASSIFICATION=D_PREREGISTRATION_INTEGRITY_FAILURE")
        print(f"FAST3_R42R_DECISION={exc}")
        return 2
    print(render_terminal(summary))
    print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
