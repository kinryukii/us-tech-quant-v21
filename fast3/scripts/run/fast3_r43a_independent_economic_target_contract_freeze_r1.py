#!/usr/bin/env python
"""FAST3 R43A independent economic target contract freeze and sanity audit."""
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
AUTHORITATIVE_ROOT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1"
STAGING_ROOT = RESULTS / "scratch/fast3/.r43a_independent_economic_target_contract_freeze_r1.staging"

R42R_ROOT = RESULTS / "frozen/fast3/r42r_frozen_confirmation_preregistration_repair_r1"
R42R_PREREG = R42R_ROOT / "FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
R42R_SUMMARY = R42R_ROOT / "FAST3_R42R_SUMMARY.json"
R42R_EXPECTED_SHA256 = "2df064f334d6a8bc45d79d8bd4f308ee9b82a33c97129a6ae36ba6aecfc9c3e1"

R36_ROOT = RESULTS / "frozen/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z"
R36_PREREG = R36_ROOT / "FAST3_R36_PREREGISTRATION_R1.json"
R36_SUMMARY = R36_ROOT / "FAST3_R36_SUMMARY.json"
R36_SOURCE = REPO / "fast3/scripts/run/fast3_r36_payoff_path_decomposition_r1.py"
R36_LEDGER = RESULTS / "scratch/fast3/r36_payoff_path_decomposition_r1_20260810T131648Z/FAST3_R36_PATH_DIAGNOSTIC_LEDGER.parquet"

R28_3E_ROOT = RESULTS / "frozen/fast3/r28_3e_clean_lineage_first_touch_20260809_r3"
R28_3E_SUMMARY = R28_3E_ROOT / "R28_3E_SUMMARY.json"
ENTRY_SOURCE = RESULTS / "frozen/fast3/cleanroom_r2_execution_contract_completion_20260808/execution_contract_completion.json"
ACTION_LEDGER = RESULTS / "frozen/fast3/r28_3g_corporate_action_normalized_first_touch_20260809/R28_3G_CORPORATE_ACTION_LEDGER.json"

R28_ROOT = RESULTS / "frozen/fast3/r28_phase3_20260808T131135Z"
R28_IDENTITY = R28_ROOT / "R28_PHASE3_RESEARCH_IDENTITY.json"
R28_READY = R28_ROOT / "R28_PROSPECTIVE_SHADOW_R1_READY_MANIFEST.json"
R28_MODELS = {
    "UP": R28_ROOT / "models/R28_3_UP_FINAL.joblib",
    "DOWN": R28_ROOT / "models/R28_3_DOWN_FINAL.joblib",
}
R41_SCORE_ROOT = RESULTS / "scratch/fast3/r28_phase2_20260808T125629Z/ledgers"
R41_SCORE_PATHS = {
    head: R41_SCORE_ROOT / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
    for head in ("UP", "DOWN")
}

HORIZONS = (5, 10, 15, 30, 60)
RETURN_COLUMNS = tuple(f"return_{minute}m_net20" for minute in HORIZONS)
EXPECTED = {
    "R42R_SUMMARY": "aee17824ab16ac0213f8ee36712ce84c9e50f8ac852faab26aefe777e8355880",
    "R36_PREREG": "da2a4493a252618798998de458855a39c9ced09bb8952dac11f76d13d9cdbb61",
    "R36_SUMMARY": "1f90403dc33c1f222a3732bc39b9d507217857c4e74ab389fa2eece3edd7647f",
    "R36_SOURCE": "c0e6cf1270556a0c0bf53ce9a1d5fc7f342b582d33dba16cc6cd30dea5c78752",
    "R36_LEDGER": "261bc7618abdf289444a84bd7b9dc47787f1788758d5bbee38f639ca0ec63aeb",
    "R28_3E_SUMMARY": "90994e4877d97490e5a854e8e32babf785591d7044e4a4acc035f1e721be97f2",
    "ENTRY_SOURCE": "17bf95775457e76c1f0e9f6d2c7fde41c5c7e117cac3f133a6da0f2cd639b55e",
    "ACTION_LEDGER": "3a72c80d4bce04e409ed429b9434e9f936405e1ffc38ac3ee04213675781a0dd",
    "UP_SCORE_LEDGER": "6e9cae3e9226bae3acc54ac3e7f50575b5614983db35bf639b66c2b515c25b9b",
    "DOWN_SCORE_LEDGER": "bb14261a8727df883ae6c8fdd001bedc7d6e626b6437e444c507a9919e1a3ee1",
}
PRIMARY_NAME = "AVERAGE_FIXED_HORIZON_NET20"
PRIMARY_FORMULA = "Y_ECON_i=(NET20_5m_i+NET20_10m_i+NET20_15m_i+NET20_30m_i+NET20_60m_i)/5"
SECONDARY_NAME = "MULTI_HORIZON_POSITIVE_MAJORITY_K3"
SECONDARY_FORMULA = "Y_POSITIVE_MAJORITY_i=1 iff count(NET20_h_i>0 for h in [5,10,15,30,60])>=3; else 0"


class IdentityStop(RuntimeError):
    pass


class CouplingStop(RuntimeError):
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


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, Path, datetime)): return str(value)
    if pd.isna(value): return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               default=json_default, allow_nan=False) + "\n", encoding="utf-8")


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise IdentityStop(f"STOP_REQUIRED_FROZEN_ROOT_MISSING:{root}")
    return {str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def verify_line_a_isolation() -> tuple[dict[str, str], dict[str, Any]]:
    before = tree_hashes(R42R_ROOT)
    if not R42R_PREREG.is_file() or sha256(R42R_PREREG) != R42R_EXPECTED_SHA256:
        raise IdentityStop("STOP_R42R_PREREGISTRATION_SHA256_MISMATCH")
    if sha256(R42R_SUMMARY) != EXPECTED["R42R_SUMMARY"]:
        raise IdentityStop("STOP_R42R_SUMMARY_SHA256_MISMATCH")
    prereg = json.loads(R42R_PREREG.read_text(encoding="utf-8"))
    r28 = prereg.get("R28_PRODUCTION_IDENTITY", {})
    actual_models = {head: sha256(path) for head, path in R28_MODELS.items()}
    if actual_models != r28.get("MODEL_SHA256_BY_DIRECTION"):
        raise IdentityStop("STOP_R28_FROZEN_MODEL_IDENTITY_MISMATCH")
    identity = json.loads(R28_IDENTITY.read_text(encoding="utf-8"))
    ready = json.loads(R28_READY.read_text(encoding="utf-8"))
    feature_payload = {"features": identity["features"], "feature_count": identity["feature_count"],
                       "feature_manifest_sha256": ready["feature_manifest_sha256"]}
    threshold_payload = {"thresholds": identity["thresholds"]}
    if (canonical_sha256(feature_payload) != r28.get("FEATURE_IDENTITY_SHA256")
            or canonical_sha256(threshold_payload) != r28.get("THRESHOLD_IDENTITY_SHA256")):
        raise IdentityStop("STOP_R28_FEATURE_OR_THRESHOLD_IDENTITY_MISMATCH")
    return before, r28


def verify_payoff_lineage() -> dict[str, str]:
    paths = {
        "R36_PREREG": R36_PREREG, "R36_SUMMARY": R36_SUMMARY, "R36_SOURCE": R36_SOURCE,
        "R36_LEDGER": R36_LEDGER, "R28_3E_SUMMARY": R28_3E_SUMMARY,
        "ENTRY_SOURCE": ENTRY_SOURCE, "ACTION_LEDGER": ACTION_LEDGER,
        "UP_SCORE_LEDGER": R41_SCORE_PATHS["UP"], "DOWN_SCORE_LEDGER": R41_SCORE_PATHS["DOWN"],
    }
    if any(not path.is_file() for path in paths.values()):
        raise IdentityStop("STOP_INDEPENDENT_PAYOFF_LINEAGE_MISSING")
    observed = {name: sha256(path) for name, path in paths.items()}
    if observed != {name: EXPECTED[name] for name in paths}:
        raise IdentityStop("STOP_INDEPENDENT_PAYOFF_LINEAGE_HASH_MISMATCH")
    prereg = json.loads(R36_PREREG.read_text(encoding="utf-8"))
    summary = json.loads(R36_SUMMARY.read_text(encoding="utf-8"))
    action = json.loads(ACTION_LEDGER.read_text(encoding="utf-8"))
    entry = json.loads(ENTRY_SOURCE.read_text(encoding="utf-8"))
    if (prereg.get("FIXED_HORIZONS_MINUTES") != list(HORIZONS)
            or prereg.get("FIXED_HORIZON_RETURN") != "entry open to exact +N minute open, then subtract frozen 20bps once"
            or summary.get("PATH_COMPLETE_SIGNAL_COUNT") != 1197
            or summary.get("CORPORATE_ACTION_STATUS") != "PASS"
            or action.get("price_basis") != "RAW"
            or action.get("normalization_layer") != "ECONOMIC_RETURN_ONLY"
            or entry["original_economic_contract"].get("cost_total") != 0.002):
        raise IdentityStop("STOP_INDEPENDENT_PAYOFF_CONTRACT_NOT_REPRODUCIBLE")
    return observed


def frozen_subcontracts(lineage: dict[str, str]) -> dict[str, Any]:
    entry_payload = {
        "ENTRY_TIMESTAMP": "first legal execution-symbol one-minute bar strictly after frozen decision anchor within 15 minutes",
        "ENTRY_PRICE": "RAW open of that exact legal one-minute bar",
        "EXECUTION_SYMBOL": {
            "QQQ_UP": "TQQQ", "QQQ_DOWN": "SQQQ", "SOXX_UP": "SOXL", "SOXX_DOWN": "SOXS",
        },
        "SOURCE": str(ENTRY_SOURCE),
        "SOURCE_SHA256": lineage["ENTRY_SOURCE"],
        "FUTURE_TARGET_OR_PAYOFF_DEPENDENCE": False,
    }
    exit_payload = {
        f"H{minute}": (
            f"RAW open of the same execution symbol at entry_timestamp+{minute} calendar minutes; exact unique bar required; "
            "no barrier, target_first, score, or path-dependent termination"
        ) for minute in HORIZONS
    }
    cost_payload = {
        "ECONOMIC_COST_BPS": 20,
        "FORMULA": "NET20=corporate-action-corrected gross return-0.002, applied exactly once",
        "SOURCE": str(R36_PREREG),
        "SOURCE_SHA256": lineage["R36_PREREG"],
    }
    corporate_action_payload = {
        "PRICE_BASIS": "RAW",
        "NORMALIZATION_LAYER": "ECONOMIC_RETURN_ONLY",
        "FORMULA": (
            "For actions with entry_timestamp < effective_timestamp <= exit_timestamp, divide exit_open by "
            "entry_open multiplied by the product of frozen pre_to_post_price_multiplier values; factor=1 otherwise"
        ),
        "SOURCE": str(ACTION_LEDGER),
        "SOURCE_SHA256": lineage["ACTION_LEDGER"],
    }
    entry_payload["ENTRY_CONTRACT_SHA256"] = canonical_sha256(entry_payload)
    exit_payload["EXIT_CONTRACT_SHA256"] = canonical_sha256(exit_payload)
    cost_payload["COST_CONTRACT_SHA256"] = canonical_sha256(cost_payload)
    corporate_action_payload["CORPORATE_ACTION_CONTRACT_SHA256"] = canonical_sha256(corporate_action_payload)
    return {
        "ENTRY_CONTRACT": entry_payload, "EXIT_CONTRACT": exit_payload,
        "COST_CONTRACT": cost_payload, "CORPORATE_ACTION_CONTRACT": corporate_action_payload,
    }


def target_contract(created_at: str, r28_identity: dict[str, Any], lineage: dict[str, str]) -> dict[str, Any]:
    subcontracts = frozen_subcontracts(lineage)
    return {
        "CONTRACT_ID": "FAST3_R43A_INDEPENDENT_ECONOMIC_TARGET_CONTRACT_FREEZE_R1",
        "STATUS": "FROZEN_BEFORE_R43A_TARGET_DISTRIBUTION_AUDIT_AND_ALL_FUTURE_MODELING",
        "CREATED_AT_UTC": created_at,
        "RESEARCH_LINE": "LINE_B_NEW_GENERATION_INDEPENDENT_ECONOMIC_RESEARCH",
        "R28_PROSPECTIVE_LINE_ISOLATION": True,
        "LINE_A_R42R_PREREGISTRATION_SHA256": R42R_EXPECTED_SHA256,
        "LINE_A_R28_MODEL_IDENTITY_SHA256": r28_identity["MODEL_IDENTITY_SHA256"],
        "LINE_A_R28_FEATURE_IDENTITY_SHA256": r28_identity["FEATURE_IDENTITY_SHA256"],
        "LINE_A_R28_THRESHOLD_IDENTITY_SHA256": r28_identity["THRESHOLD_IDENTITY_SHA256"],
        "R28_MODEL_UNCHANGED": True,
        "R28_FEATURES_UNCHANGED": True,
        "R28_THRESHOLDS_UNCHANGED": True,
        "R28_CONFIRMATION_CONTRACT_UNCHANGED": True,
        "ALLOWED_TARGET_FAMILY_COUNT": 3,
        "TARGET_FAMILY_A": {
            "NAME": "MULTI_HORIZON_ECONOMIC_QUALITY",
            "AUDIT_DECISION": "NOT_SELECTED_NO_ADDITIONAL_NORMALIZATION_DEGREES_INTRODUCED",
            "RATIONALE": "All five components already share the same decimal NET20 unit; normalized aggregation would add an unnecessary reference-distribution choice",
        },
        "TARGET_FAMILY_B": {
            "NAME": SECONDARY_NAME, "AUDIT_DECISION": "FROZEN_SECONDARY_ONLY", "K": 3,
            "K_SEARCH_ALLOWED": False,
        },
        "TARGET_FAMILY_C": {
            "NAME": PRIMARY_NAME, "AUDIT_DECISION": "FROZEN_PRIMARY",
            "RATIONALE": "Equal inclusion of all preregistered horizons, no classification cutoff, retains economic magnitude",
        },
        "PRIMARY_TARGET_NAME": PRIMARY_NAME,
        "PRIMARY_TARGET_FORMULA": PRIMARY_FORMULA,
        "PRIMARY_TARGET_UNIT": "decimal net execution-ETF return after 20bps total cost, equally averaged across five horizons",
        "PRIMARY_TARGET_DIRECTIONAL_ORIENTATION": (
            "Actual long execution-instrument PnL orientation for both directions: UP uses TQQQ/SOXL and DOWN uses SQQQ/SOXS; "
            "positive always means economically favorable and no additional DOWN sign inversion is applied"
        ),
        "SECONDARY_TARGET_NAME": SECONDARY_NAME,
        "SECONDARY_TARGET_FORMULA": SECONDARY_FORMULA,
        "SECONDARY_CANNOT_REPLACE_FAILED_PRIMARY": True,
        "HORIZONS": list(HORIZONS),
        "HORIZON_WEIGHTS": {str(minute): 0.2 for minute in HORIZONS},
        "SINGLE_HORIZON_SELECTION_ALLOWED": False,
        **subcontracts,
        "MISSING_DATA_POLICY": (
            "Both targets require 5/5 finite, legal, path-complete, corporate-action-resolved horizon NET20 values; "
            "otherwise target validity=false with no partial average, interpolation, or forward fill"
        ),
        "UP_DOWN_ORIENTATION": "identical target mathematics; only the already-frozen execution-symbol mapping differs",
        "VALIDITY_RULES": [
            "path_complete is true", "all five NET20 values are finite", "all raw prices are positive and exact-bar legal",
            "corporate-action status is resolved PASS", "candidate identity and PIT lineage pass",
        ],
        "PRIMARY_TARGET_DEPENDS_ON_TARGET_FIRST": False,
        "PRIMARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT": False,
        "PRIMARY_TARGET_DEPENDS_ON_R28_SCORE": False,
        "PRIMARY_TARGET_DEPENDS_ON_MODEL_PREDICTION": False,
        "PRIMARY_TARGET_DEPENDS_ON_SELECTED_HORIZON": False,
        "PRIMARY_TARGET_USES_FUTURE_PRICE_PATH": True,
        "SECONDARY_TARGET_DEPENDS_ON_TARGET_FIRST": False,
        "SECONDARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT": False,
        "SECONDARY_TARGET_DEPENDS_ON_R28_SCORE": False,
        "SECONDARY_TARGET_DEPENDS_ON_MODEL_PREDICTION": False,
        "TARGET_PAYOFF_MECHANICAL_COUPLING": False,
        "CAUSAL_ORDER": "fixed exit timestamps -> realized NET20 returns -> target; target never determines exit",
        "DESCRIPTIVE_AUDIT_SEMANTICS": {
            "STD": "sample standard deviation ddof=1",
            "QUANTILES": "linear interpolation at p05,p10,p25,p75,p90,p95",
            "TAIL_CONTRIBUTION": "sum of largest K absolute primary-target values divided by total absolute primary-target sum",
            "TARGET_WINSORIZATION_ALLOWED": False,
            "DISTRIBUTION_CAN_CHANGE_TARGET_DEFINITION": False,
        },
        "NEXT_GENERATION_RESEARCH_SEQUENCE": [
            "R43B_CURRENT_14_FEATURE_BASELINE",
            "R43C_REGIME_INFORMATION_FAMILY_ONLY_IF_BASELINE_COMPLETE",
            "R43D_PATH_SHAPE_INFORMATION_FAMILY_ONLY_IF_INCREMENTAL_VALUE",
            "R43E_CROSS_ASSET_INFORMATION_FAMILY_ONLY_IF_INCREMENTAL_VALUE",
        ],
        "FAMILY_TESTING_MODE": "SEQUENTIAL_ONE_INFORMATION_FAMILY_AT_A_TIME",
        "MAX_NEW_FEATURES_PER_FAMILY": 8,
        "MAX_MODEL_FAMILY_COUNT": 1,
        "INITIAL_MODEL_CLASS": "HistGradientBoosting",
        "FUTURE_ACCEPTANCE_CRITERIA_FREEZE_STAGE": "AFTER_R43B_NOT_IN_R43A",
        "MODEL_FIT_ALLOWED": False,
        "MODEL_PREDICT_CALL_ALLOWED": False,
        "NEW_FEATURE_ALLOWED": False,
        "HORIZON_OPTIMIZATION_ALLOWED": False,
        "THRESHOLD_OPTIMIZATION_ALLOWED": False,
        "STOP_OR_TAKE_PROFIT_OPTIMIZATION_ALLOWED": False,
        "STRATEGY_SIMULATION_ALLOWED": False,
        "ACCOUNT_TRANSLATION_ALLOWED": False,
        "SEQUENTIAL_COMPOUNDING_ALLOWED": False,
        "AUTHORITATIVE_FILE_HASH_SEMANTICS": (
            "R43A_TARGET_CONTRACT_SHA256 is SHA256 of this exact UTF-8 JSON file including final newline; "
            "stored in summary and .sha256 sidecar, not self-embedded"
        ),
        "INPUT_LINEAGE_SHA256": lineage,
    }


def load_target_frame() -> tuple[pd.DataFrame, dict[str, int]]:
    columns = ["candidate_id", "decision_timestamp_utc", "entry_timestamp", "head", "underlying_symbol",
               "action_instrument", "path_complete", *RETURN_COLUMNS]
    frame = pd.read_parquet(R36_LEDGER, columns=columns)
    input_count = len(frame)
    duplicate_count = int(frame["candidate_id"].duplicated().sum())
    numeric = frame.loc[:, RETURN_COLUMNS].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    valid = frame["path_complete"].eq(True).to_numpy() & finite
    frame["primary_target_valid"] = valid
    frame["secondary_target_valid"] = valid
    frame["primary_target"] = numeric.mean(axis=1).where(valid)
    frame["secondary_target"] = numeric.gt(0).sum(axis=1).ge(3).astype("Int64").where(valid)
    frame["primary_target_positive"] = frame["primary_target"].gt(0).where(valid)
    frame["decision_timestamp_utc"] = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="raise")
    frame["entry_timestamp"] = pd.to_datetime(frame["entry_timestamp"], utc=True, errors="raise")
    if input_count != 1197 or duplicate_count:
        raise IdentityStop("STOP_R36_TARGET_COHORT_IDENTITY")
    if not (frame["entry_timestamp"] > frame["decision_timestamp_utc"]).all():
        raise IdentityStop("STOP_ENTRY_TIMESTAMP_NOT_STRICTLY_AFTER_DECISION")
    metadata = {
        "TARGET_INPUT_COUNT": input_count,
        "TARGET_DUPLICATE_COUNT": duplicate_count,
        "PRIMARY_TARGET_VALID_COUNT": int(frame["primary_target_valid"].sum()),
        "PRIMARY_TARGET_INVALID_COUNT": int((~frame["primary_target_valid"]).sum()),
        "SECONDARY_TARGET_VALID_COUNT": int(frame["secondary_target_valid"].sum()),
        "SECONDARY_TARGET_INVALID_COUNT": int((~frame["secondary_target_valid"]).sum()),
    }
    return frame, metadata


def attach_folds(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["candidate_id", "validation_slice", "selected", "head", "direction"]
    folds = pd.concat([pd.read_parquet(path, columns=columns) for path in R41_SCORE_PATHS.values()], ignore_index=True)
    joined = frame.merge(folds, on="candidate_id", how="left", validate="one_to_one",
                         suffixes=("", "_score"), indicator=True)
    if (not joined["_merge"].eq("both").all() or not joined["selected"].eq(True).all()
            or not joined["head"].eq(joined["head_score"]).all()
            or not joined["head"].eq(joined["direction"]).all()):
        raise IdentityStop("STOP_CHRONOLOGICAL_OOF_FOLD_IDENTITY")
    return joined.drop(columns=["_merge"])


def distribution_row(scope: str, direction: str, frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.loc[frame["primary_target_valid"], "primary_target"], errors="raise").astype(float)
    secondary = pd.to_numeric(frame.loc[frame["secondary_target_valid"], "secondary_target"], errors="raise").astype(float)
    return {
        "scope": scope, "direction": direction, "count": len(values),
        "mean": float(values.mean()), "median": float(values.median()), "std": float(values.std(ddof=1)),
        "p05": float(values.quantile(.05)), "p10": float(values.quantile(.10)),
        "p25": float(values.quantile(.25)), "p75": float(values.quantile(.75)),
        "p90": float(values.quantile(.90)), "p95": float(values.quantile(.95)),
        "min_target": float(values.min()), "max_target": float(values.max()),
        "primary_positive_rate": float((values > 0).mean()),
        "secondary_positive_rate": float(secondary.mean()),
        "unique_primary_target_count": int(values.nunique()),
    }


def audit_distribution(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    valid = frame.loc[frame["primary_target_valid"]].copy()
    rows = [distribution_row("ALL", "ALL", valid)]
    for head in ("UP", "DOWN"):
        rows.append(distribution_row("DIRECTION", head, valid.loc[valid["head"].eq(head)]))
    distribution = pd.DataFrame(rows)
    fold_rows = []
    for (head, fold), part in valid.groupby(["head", "validation_slice"], sort=True):
        row = distribution_row("DIRECTION_FOLD", str(head), part)
        row["validation_slice"] = str(fold)
        fold_rows.append(row)
    by_fold = pd.DataFrame(fold_rows)
    tail_rows = []
    for direction, part in [("ALL", valid), *[(head, valid.loc[valid["head"].eq(head)]) for head in ("UP", "DOWN")]]:
        absolute = part["primary_target"].abs().sort_values(ascending=False, kind="mergesort")
        denominator = float(absolute.sum())
        tail_rows.append({
            "direction": direction,
            "top1_abs_target_contribution": float(absolute.iloc[:1].sum() / denominator),
            "top5_abs_target_contribution": float(absolute.iloc[:5].sum() / denominator),
            "top10_abs_target_contribution": float(absolute.iloc[:10].sum() / denominator),
            "max_target": float(part["primary_target"].max()),
            "min_target": float(part["primary_target"].min()),
            "target_winsorized": False,
        })
    tails = pd.DataFrame(tail_rows)
    all_row = distribution.loc[distribution["direction"].eq("ALL")].iloc[0]
    all_tail = tails.loc[tails["direction"].eq("ALL")].iloc[0]
    direction_counts_ok = all(int(valid["head"].eq(head).sum()) >= 50 for head in ("UP", "DOWN"))
    fold_coverage_ok = bool((by_fold["count"] > 0).all()) and by_fold["validation_slice"].nunique() >= 2
    nonconstant = bool(all_row["std"] > 0 and all_row["unique_primary_target_count"] >= 20)
    severe_single_tail = bool(all_tail["top1_abs_target_contribution"] >= .5)
    sanity_pass = bool(len(valid) >= 100 and direction_counts_ok and fold_coverage_ok and nonconstant and not severe_single_tail)
    audit = {
        "TARGET_DISTRIBUTION_SANITY_STATUS": (
            "PASS_FINITE_NONCONSTANT_WITH_DIRECTION_AND_CHRONOLOGICAL_FOLD_COVERAGE" if sanity_pass
            else "FAIL_SEVERE_TARGET_DISTRIBUTION_INVALIDITY"
        ),
        "TARGET_DISTRIBUTION_SANITY_PASS": sanity_pass,
        "DIRECTION_MINIMUM_COUNT_PASS": direction_counts_ok,
        "CHRONOLOGICAL_FOLD_COVERAGE_PASS": fold_coverage_ok,
        "NONCONSTANT_TARGET_PASS": nonconstant,
        "SEVERE_SINGLE_TAIL_DOMINANCE": severe_single_tail,
        "TOP1_ABS_TARGET_CONTRIBUTION": float(all_tail["top1_abs_target_contribution"]),
        "TOP5_ABS_TARGET_CONTRIBUTION": float(all_tail["top5_abs_target_contribution"]),
        "TOP10_ABS_TARGET_CONTRIBUTION": float(all_tail["top10_abs_target_contribution"]),
        "MAX_TARGET": float(all_tail["max_target"]), "MIN_TARGET": float(all_tail["min_target"]),
        "TARGET_WINSORIZATION_COUNT": 0,
    }
    return distribution, by_fold, tails, audit


def summary_payload(contract: dict[str, Any], contract_hash: str, metadata: dict[str, int],
                    distribution: pd.DataFrame, audit: dict[str, Any], isolation_unchanged: bool) -> dict[str, Any]:
    lookup = distribution.set_index("direction")
    if not audit["TARGET_DISTRIBUTION_SANITY_PASS"]:
        raise IntegrityStop("STOP_SEVERE_TARGET_DISTRIBUTION_INVALIDITY")
    return {
        "FAST3_R43A_STATUS": "PASS",
        "FAST3_R43A_CLASSIFICATION": "A_INDEPENDENT_ECONOMIC_TARGET_CONTRACT_FROZEN",
        "FAST3_R43A_DECISION": "R43B_CURRENT_INFORMATION_SET_ECONOMIC_BASELINE",
        "NEXT_STAGE": "R43B_CURRENT_INFORMATION_SET_ECONOMIC_BASELINE",
        "PRIMARY_TARGET_NAME": PRIMARY_NAME, "PRIMARY_TARGET_FORMULA": PRIMARY_FORMULA,
        "PRIMARY_TARGET_UNIT": contract["PRIMARY_TARGET_UNIT"],
        "PRIMARY_TARGET_DIRECTIONAL_ORIENTATION": contract["PRIMARY_TARGET_DIRECTIONAL_ORIENTATION"],
        "SECONDARY_TARGET_NAME": SECONDARY_NAME, "SECONDARY_TARGET_FORMULA": SECONDARY_FORMULA,
        "TARGET_HORIZONS": list(HORIZONS), **metadata,
        "UP_PRIMARY_TARGET_VALID_COUNT": int(lookup.loc["UP", "count"]),
        "DOWN_PRIMARY_TARGET_VALID_COUNT": int(lookup.loc["DOWN", "count"]),
        "UP_PRIMARY_TARGET_MEAN": float(lookup.loc["UP", "mean"]),
        "UP_PRIMARY_TARGET_MEDIAN": float(lookup.loc["UP", "median"]),
        "DOWN_PRIMARY_TARGET_MEAN": float(lookup.loc["DOWN", "mean"]),
        "DOWN_PRIMARY_TARGET_MEDIAN": float(lookup.loc["DOWN", "median"]),
        "UP_SECONDARY_POSITIVE_RATE": float(lookup.loc["UP", "secondary_positive_rate"]),
        "DOWN_SECONDARY_POSITIVE_RATE": float(lookup.loc["DOWN", "secondary_positive_rate"]),
        "PRIMARY_TARGET_DEPENDS_ON_TARGET_FIRST": False,
        "PRIMARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT": False,
        "PRIMARY_TARGET_DEPENDS_ON_R28_SCORE": False,
        "PRIMARY_TARGET_DEPENDS_ON_MODEL_PREDICTION": False,
        "PRIMARY_TARGET_DEPENDS_ON_SELECTED_HORIZON": False,
        "PRIMARY_TARGET_USES_FUTURE_PRICE_PATH": True,
        "TARGET_PAYOFF_MECHANICAL_COUPLING": False,
        "ENTRY_CONTRACT_SOURCE": contract["ENTRY_CONTRACT"]["SOURCE"],
        "ENTRY_CONTRACT_SHA256": contract["ENTRY_CONTRACT"]["ENTRY_CONTRACT_SHA256"],
        "ECONOMIC_COST_BPS": 20,
        "ECONOMIC_COST_CONTRACT_SOURCE": contract["COST_CONTRACT"]["SOURCE"],
        "CORPORATE_ACTION_CONTRACT_SOURCE": contract["CORPORATE_ACTION_CONTRACT"]["SOURCE"],
        "R43A_TARGET_CONTRACT_SHA256": contract_hash,
        "TARGET_CONTRACT_EXISTS_BEFORE_DISTRIBUTION_AUDIT": True,
        "R28_PROSPECTIVE_LINE_ISOLATION": isolation_unchanged,
        "R28_MODEL_CHANGED": False, "R28_FEATURE_CHANGED": False,
        "R28_THRESHOLD_CHANGED": False, "R28_PREREGISTRATION_CHANGED": False,
        "R42R_PREREGISTRATION_SHA256_VERIFIED": True,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "MAX_NEW_FEATURE_COUNT": 0, "HORIZON_SELECTION_COUNT": 0,
        "THRESHOLD_OPTIMIZATION_COUNT": 0, "STRATEGY_SIMULATION_COUNT": 0,
        "PIT_STATUS": "PASS_DECISION_TIME_IDENTITY_AND_CHRONOLOGICAL_OOF_FOLDS",
        "PAYOFF_INDEPENDENCE_STATUS": "PASS_FIXED_ENTRY_PLUS_TIME_EXIT_NO_TARGET_FIRST_TERMINATION",
        "CORPORATE_ACTION_STATUS": "PASS_R36_FROZEN_RAW_ECONOMIC_RETURN_NORMALIZATION",
        "STORAGE_CONTRACT_STATUS": "PASS_FAST3_STORAGE_CONTRACT_R1_EXTERNAL_FROZEN_ONLY",
        "NEXT_GENERATION_RESEARCH_SEQUENCE": contract["NEXT_GENERATION_RESEARCH_SEQUENCE"],
        "MAX_NEW_FEATURES_PER_FAMILY": 8, "MAX_MODEL_FAMILY_COUNT": 1,
        "INITIAL_MODEL_CLASS": "HistGradientBoosting",
        **audit,
    }


def render_terminal(summary: dict[str, Any]) -> str:
    keys = [
        "FAST3_R43A_STATUS", "FAST3_R43A_CLASSIFICATION", "FAST3_R43A_DECISION",
        "PRIMARY_TARGET_NAME", "PRIMARY_TARGET_FORMULA", "SECONDARY_TARGET_NAME", "SECONDARY_TARGET_FORMULA",
        "TARGET_HORIZONS", "PRIMARY_TARGET_VALID_COUNT", "UP_PRIMARY_TARGET_VALID_COUNT",
        "DOWN_PRIMARY_TARGET_VALID_COUNT", "UP_PRIMARY_TARGET_MEAN", "UP_PRIMARY_TARGET_MEDIAN",
        "DOWN_PRIMARY_TARGET_MEAN", "DOWN_PRIMARY_TARGET_MEDIAN",
        "UP_SECONDARY_POSITIVE_RATE", "DOWN_SECONDARY_POSITIVE_RATE",
        "PRIMARY_TARGET_DEPENDS_ON_TARGET_FIRST", "PRIMARY_TARGET_DEPENDS_ON_FIRST_TOUCH_EXIT",
        "PRIMARY_TARGET_DEPENDS_ON_R28_SCORE", "PRIMARY_TARGET_DEPENDS_ON_MODEL_PREDICTION",
        "PRIMARY_TARGET_DEPENDS_ON_SELECTED_HORIZON", "PRIMARY_TARGET_USES_FUTURE_PRICE_PATH",
        "TARGET_PAYOFF_MECHANICAL_COUPLING", "ENTRY_CONTRACT_SOURCE", "ECONOMIC_COST_BPS",
        "CORPORATE_ACTION_CONTRACT_SOURCE", "TOP1_ABS_TARGET_CONTRIBUTION",
        "TOP5_ABS_TARGET_CONTRIBUTION", "TOP10_ABS_TARGET_CONTRIBUTION", "MAX_TARGET", "MIN_TARGET",
        "TARGET_DISTRIBUTION_SANITY_STATUS", "R43A_TARGET_CONTRACT_SHA256",
        "R28_PROSPECTIVE_LINE_ISOLATION", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
        "R42R_PREREGISTRATION_SHA256_VERIFIED", "PIT_STATUS", "PAYOFF_INDEPENDENCE_STATUS",
        "CORPORATE_ACTION_STATUS", "STORAGE_CONTRACT_STATUS", "NEXT_STAGE",
    ]
    def value(item: Any) -> str:
        if isinstance(item, bool): return str(item).lower()
        if isinstance(item, list): return "[" + ",".join(map(str, item)) + "]"
        return str(item)
    return "\n".join(f"{key}={value(summary[key])}" for key in keys)


def execute() -> dict[str, Any]:
    if AUTHORITATIVE_ROOT.exists():
        raise IntegrityStop("STOP_AUTHORITATIVE_R43A_CONTRACT_ALREADY_EXISTS_USE_VERIFY")
    if STAGING_ROOT.exists():
        raise IntegrityStop("STOP_R43A_STAGING_PATH_ALREADY_EXISTS")
    before, r28_identity = verify_line_a_isolation()
    lineage = verify_payoff_lineage()
    STAGING_ROOT.mkdir(parents=True)

    # The target definition is frozen and hashed before any descriptive target
    # value or distribution is constructed.
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    contract = target_contract(created_at, r28_identity, lineage)
    contract_path = STAGING_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
    write_json(contract_path, contract)
    contract_hash = sha256(contract_path)
    (STAGING_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json.sha256").write_text(
        contract_hash + "\n", encoding="ascii"
    )

    frame, metadata = load_target_frame()
    frame = attach_folds(frame)
    distribution, by_fold, tails, audit = audit_distribution(frame)
    after = tree_hashes(R42R_ROOT)
    isolation_unchanged = before == after and sha256(R42R_PREREG) == R42R_EXPECTED_SHA256
    if not isolation_unchanged:
        raise IntegrityStop("STOP_R28_PROSPECTIVE_LINE_ISOLATION_FAILURE")
    summary = summary_payload(contract, contract_hash, metadata, distribution, audit, isolation_unchanged)
    summary.update({
        "RUN_MODE": "CREATE_AUTHORITATIVE_ONCE",
        "CREATED_AT_UTC": created_at,
        "BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "INPUT_SHA256": lineage,
        "R42R_TREE_SHA256_BEFORE_AND_AFTER": before,
    })
    distribution.to_csv(STAGING_ROOT / "FAST3_R43A_TARGET_DISTRIBUTION.csv", index=False)
    by_fold.to_csv(STAGING_ROOT / "FAST3_R43A_TARGET_DISTRIBUTION_BY_FOLD.csv", index=False)
    tails.to_csv(STAGING_ROOT / "FAST3_R43A_TARGET_TAIL_CONCENTRATION.csv", index=False)
    write_json(STAGING_ROOT / "FAST3_R43A_SUMMARY.json", summary)
    report = [
        "# FAST3 R43A Independent Economic Target Contract Freeze R1", "",
        f"- Classification: `{summary['FAST3_R43A_CLASSIFICATION']}`",
        f"- Decision: `{summary['FAST3_R43A_DECISION']}`",
        f"- Target contract SHA256: `{contract_hash}`", "",
        "The primary label is the equal-weight mean of five pre-frozen, corporate-action-normalized NET20 horizons. The secondary label is the fixed 3-of-5 positive majority. Target definition was written and hashed before this stage constructed descriptive target values.", "",
        "No model fit, prediction, feature work, target search, horizon selection, strategy simulation, or R28 prospective mutation occurred.", "",
        "## Terminal summary", "", "```text", render_terminal(summary), "```", "",
    ]
    (STAGING_ROOT / "FAST3_R43A_CONTRACT.md").write_text("\n".join(report), encoding="utf-8")
    AUTHORITATIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(STAGING_ROOT), str(AUTHORITATIVE_ROOT))
    if sha256(AUTHORITATIVE_ROOT / contract_path.name) != contract_hash:
        raise IntegrityStop("STOP_POST_FREEZE_R43A_CONTRACT_HASH_MISMATCH")
    summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def verify() -> dict[str, Any]:
    contract_path = AUTHORITATIVE_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
    sidecar = AUTHORITATIVE_ROOT / "FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json.sha256"
    summary_path = AUTHORITATIVE_ROOT / "FAST3_R43A_SUMMARY.json"
    if any(not path.is_file() for path in (contract_path, sidecar, summary_path)):
        raise IntegrityStop("STOP_AUTHORITATIVE_R43A_ARTIFACT_MISSING")
    expected = sidecar.read_text(encoding="ascii").strip()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (sha256(contract_path) != expected or summary.get("R43A_TARGET_CONTRACT_SHA256") != expected
            or sha256(R42R_PREREG) != R42R_EXPECTED_SHA256):
        raise IntegrityStop("STOP_AUTHORITATIVE_R43A_OR_R42R_HASH_MISMATCH")
    verify_line_a_isolation()
    verify_payoff_lineage()
    summary["RUN_MODE"] = "VERIFY_ONLY_NO_WRITE"
    summary["ARTIFACT_ROOT"] = str(AUTHORITATIVE_ROOT)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        summary = execute() if args.execute else verify()
    except CouplingStop as exc:
        print("FAST3_R43A_STATUS=STOP")
        print("FAST3_R43A_CLASSIFICATION=C_TARGET_PAYOFF_MECHANICAL_COUPLING_REMAINS")
        print(f"FAST3_R43A_DECISION={exc}")
        return 2
    except IdentityStop as exc:
        print("FAST3_R43A_STATUS=STOP")
        print("FAST3_R43A_CLASSIFICATION=D_INDEPENDENT_PAYOFF_IDENTITY_NOT_REPRODUCIBLE")
        print(f"FAST3_R43A_DECISION={exc}")
        return 2
    except IntegrityStop as exc:
        print("FAST3_R43A_STATUS=STOP")
        print("FAST3_R43A_CLASSIFICATION=B_TARGET_CONTRACT_PARTIALLY_INVALID")
        print(f"FAST3_R43A_DECISION={exc}")
        return 2
    print(render_terminal(summary))
    print(f"ARTIFACT_ROOT={summary['ARTIFACT_ROOT']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
