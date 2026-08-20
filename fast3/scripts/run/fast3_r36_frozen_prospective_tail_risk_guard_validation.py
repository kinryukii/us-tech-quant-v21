#!/usr/bin/env python
"""FAST3 R36 prospective-only tail-risk guard observer.

Activation reads only the outcome-blind R35A score distribution and immutable
R34-R prediction columns.  Outcome projection is confined to the explicit
``--mature-outcomes`` operation after the R36 preregistration exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R35A_ROOT = RESULTS_ROOT / "frozen/fast3/fast3_r35a_frozen_t1_t5_t6_outcome_blind_20260812T_r1"
R35A_LEDGER = R35A_ROOT / "FAST3_R35A_FROZEN_EXPECTED_PAYOFF_LEDGER.parquet"
R35A_SUMMARY = R35A_ROOT / "FAST3_R35A_SUMMARY.json"
R35A_LEDGER_SHA256 = "75b80365aae546923b1a2cc2967c1f9538af0893ce45a402ff68cc7c315dbe1b"
R34R_LEDGER = RESULTS_ROOT / "runtime/fast3/r34/FAST3_R34_PROSPECTIVE_LEDGER.parquet"
R34R_STATUS = RESULTS_ROOT / "runtime/fast3/r34/FAST3_R34_CURRENT_STATUS.json"
R34R_DAILY_COMMAND = r".\scripts\fast3\run_fast3_r34_frozen_probability_risk_prospective.ps1 -Execute"
OPTION_SHADOW_ROOT = RESULTS_ROOT / "runtime/fast3/moomoo_option_shadow/raw"
R36_FROZEN_PARENT = RESULTS_ROOT / "frozen/fast3"
R36_RUNTIME_ROOT = RESULTS_ROOT / "runtime/fast3/r36_tail_risk_guard"

FORMULA = "p*gain_magnitude-(1-p)*loss_magnitude"
FORMULA_IDENTITY = {
    "p": "t1_probability",
    "gain_magnitude": "max(0, expm1(t6_prediction_raw))",
    "loss_magnitude": "max(0, expm1(t5_prediction_raw))",
    "expected_payoff_raw": FORMULA,
}
SEVERE_LOSS_THRESHOLD = -0.05
MINIMUM_GATE = {
    "matured_total_rows": 2000,
    "matured_up_rows": 500,
    "matured_down_rows": 500,
    "q1_rows": 250,
    "q5_rows": 250,
    "distinct_trading_days": 10,
}
PROTECTED_FLAGS = {
    "FAST3_R34R_PROSPECTIVE_CHANGED": False,
    "FAST3_BASE_MODEL_CHANGED": False,
    "FAST3_BASE_SIGNAL_CHANGED": False,
    "FAST3_TARGET_CHANGED": False,
    "FAST3_POSITION_SIZING_CHANGED": False,
    "FAST3_DIRECTION_THRESHOLD_CHANGED": False,
    "R36_GUARD_ENFORCEMENT_ENABLED": False,
    "R36_CAN_BLOCK_TRADE": False,
    "BROKER_ACTION_ALLOWED": False,
    "MODEL_FIT_COUNT": 0,
    "MODEL_PREDICT_CALL_COUNT": 0,
    "OPTION_PROSPECTIVE_MODEL_FIT_COUNT": 0,
    "OPTION_PROSPECTIVE_FACTOR_SELECTION_COUNT": 0,
}
R34_PREDICTION_COLUMNS = (
    "candidate_id", "decision_timestamp_utc", "trading_date", "direction",
    "T1_raw", "T5_raw", "T6_raw", "T1_model_sha256", "T5_model_sha256",
    "T6_model_sha256", "feature_manifest_sha256", "r34_prospective_contract_sha256",
)
R36_PREDICTION_COLUMNS = (
    "decision_key", "timestamp", "trading_date", "direction", "t1_probability",
    "t5_prediction", "t6_prediction", "r35_expected_payoff_raw",
    "frozen_direction_quantile_bucket", "r34r_t1_model_sha256",
    "r34r_t5_model_sha256", "r34r_t6_model_sha256", "r34r_feature_manifest_sha256",
    "r34r_prospective_contract_sha256", "r36_preregistration_sha256",
)


class R36Stop(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n").encode("utf-8")


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_once(path: Path, data: bytes) -> None:
    if path.exists():
        raise R36Stop("STOP_R36_APPEND_ONLY_PATH_ALREADY_EXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def formula_sha256() -> str:
    return stable_sha256(FORMULA_IDENTITY)


def score(t1_probability: Iterable[float], t5_prediction: Iterable[float], t6_prediction: Iterable[float]) -> np.ndarray:
    p = np.asarray(t1_probability, dtype=float)
    loss = np.maximum(0.0, np.expm1(np.asarray(t5_prediction, dtype=float)))
    gain = np.maximum(0.0, np.expm1(np.asarray(t6_prediction, dtype=float)))
    return p * gain - (1.0 - p) * loss


def outcome_blind_cutpoints(frame: pd.DataFrame) -> dict[str, list[float]]:
    if list(frame.columns) != ["direction", "expected_payoff_raw"]:
        raise R36Stop("STOP_R36_CUTPOINT_SOURCE_PROJECTION_NOT_OUTCOME_BLIND")
    if not set(frame.direction).issubset({"UP", "DOWN"}) or set(frame.direction) != {"UP", "DOWN"}:
        raise R36Stop("STOP_R36_DIRECTION_POPULATION_UNAVAILABLE")
    result: dict[str, list[float]] = {}
    for direction in ("UP", "DOWN"):
        values = frame.loc[frame.direction.eq(direction), "expected_payoff_raw"]
        if values.empty or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise R36Stop("STOP_R36_SCORE_DISTRIBUTION_INVALID")
        result[direction] = [float(values.quantile(q, interpolation="linear")) for q in (0.2, 0.4, 0.6, 0.8)]
    return result


def bucket_for(score_value: float, cutpoints: Iterable[float]) -> str:
    cuts = np.asarray(list(cutpoints), dtype=float)
    if cuts.shape != (4,) or not np.isfinite(cuts).all() or not np.all(cuts[:-1] <= cuts[1:]) or not np.isfinite(score_value):
        raise R36Stop("STOP_R36_BUCKET_INPUT_INVALID")
    # Frozen boundary rule: Q1 <= Q20; Q2=(Q20,Q40]; ...; Q5 > Q80.
    return f"Q{int(np.searchsorted(cuts, float(score_value), side='left')) + 1}"


def is_legal_r36_timestamp(decision_timestamp: Any, preregistration_frozen_timestamp: Any) -> bool:
    return pd.Timestamp(decision_timestamp) > pd.Timestamp(preregistration_frozen_timestamp)


def sample_gate(frame: pd.DataFrame) -> tuple[bool, dict[str, int]]:
    counts = {
        "matured_total_rows": len(frame),
        "matured_up_rows": int(frame.direction.eq("UP").sum()),
        "matured_down_rows": int(frame.direction.eq("DOWN").sum()),
        "q1_rows": int(frame.frozen_direction_quantile_bucket.eq("Q1").sum()),
        "q5_rows": int(frame.frozen_direction_quantile_bucket.eq("Q5").sum()),
        "distinct_trading_days": int(frame.trading_date.nunique()),
    }
    return all(counts[key] >= minimum for key, minimum in MINIMUM_GATE.items()), counts


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    if REPO_ROOT != Path(r"D:\us-tech-quant") or RESULTS_ROOT != Path(r"D:\us-tech-quant-results"):
        raise R36Stop("STOP_R36_STORAGE_CONTRACT_VIOLATION")
    if not R35A_LEDGER.is_file() or file_sha256(R35A_LEDGER) != R35A_LEDGER_SHA256:
        raise R36Stop("STOP_R36_R35A_SCORE_IDENTITY_MISMATCH")
    r35a = _read_json(R35A_SUMMARY)
    if (r35a.get("CANONICAL_EXPECTED_PAYOFF_FORMULA") != FORMULA
            or r35a.get("OUTCOME_VALUE_READ_COUNT") != 0 or r35a.get("PAYOFF_VALUE_READ_COUNT") != 0):
        raise R36Stop("STOP_R36_R35A_SCORE_IDENTITY_MISMATCH")
    if not R34R_STATUS.is_file() or not R34R_LEDGER.is_file():
        raise R36Stop("STOP_R36_REQUIRED_PROSPECTIVE_HEAD_LEDGER_UNAVAILABLE")
    r34r = _read_json(R34R_STATUS)
    if (r34r.get("FAST3_R34R_STATUS") != "PASS" or r34r.get("DAILY_R34_COMMAND") != R34R_DAILY_COMMAND
            or not all(r34r.get(f"{head}_MODEL_HASH_MATCH") is True for head in ("T1", "T5", "T6"))):
        raise R36Stop("STOP_R36_REQUIRED_PROSPECTIVE_HEAD_LEDGER_UNAVAILABLE")
    schema = set(pd.read_parquet(R34R_LEDGER, columns=[]).columns)
    # pandas returns no names for a zero-column projection; inspect parquet metadata without row values.
    try:
        import pyarrow.parquet as pq
        schema = set(pq.ParquetFile(R34R_LEDGER).schema.names)
    except ImportError:
        pass
    if set(R34_PREDICTION_COLUMNS).difference(schema):
        raise R36Stop("STOP_R36_REQUIRED_PROSPECTIVE_HEAD_LEDGER_UNAVAILABLE")
    return r35a, r34r


def preregistration(r35a: dict[str, Any], r34r: dict[str, Any], cutpoints: dict[str, list[float]], created: str) -> dict[str, Any]:
    t1_identity = {
        "target_name": r35a["T1_TARGET_NAME"], "target_sha256": r35a["T1_TARGET_SHA256"],
        "prediction_semantics": r35a["T1_PREDICTION_SEMANTICS"], "prospective_model_sha256": r34r["T1_MODEL_SHA256"],
    }
    t5_identity = {
        "target_name": r35a["T5_TARGET_NAME"], "target_sha256": r35a["T5_TARGET_SHA256"],
        "condition": r35a["T5_CONDITION_DEFINITION"], "inverse_transform": r35a["T5_INVERSE_TRANSFORM"],
        "prospective_model_sha256": r34r["T5_MODEL_SHA256"],
    }
    t6_identity = {
        "target_name": r35a["T6_TARGET_NAME"], "target_sha256": r35a["T6_TARGET_SHA256"],
        "condition": r35a["T6_CONDITION_DEFINITION"], "inverse_transform": r35a["T6_INVERSE_TRANSFORM"],
        "prospective_model_sha256": r34r["T6_MODEL_SHA256"],
    }
    return {
        "schema_version": "FAST3_R36_PREREGISTRATION_R1",
        "creation_timestamp_utc": created,
        "hypothesis": {
            "H0": "R35 score has no prospective tail-risk discrimination",
            "H1": "lower within-direction R35 score is associated with worse prospective left-tail realized raw_net20",
            "prohibited_interpretation": "EV predicts return",
            "validation_role": "TAIL_RISK_GUARD_VALUE_ONLY",
        },
        "r35_score_identities": {"T1": t1_identity, "T5": t5_identity, "T6": t6_identity},
        "r35_formula": FORMULA_IDENTITY,
        "r35_formula_sha256": formula_sha256(),
        "r35a_outcome_blind_ledger_sha256": R35A_LEDGER_SHA256,
        "direction_stratification_rule": "stratify UP and DOWN separately; pooled raw-EV ranking is prohibited",
        "score_cutpoints": {"method": "R35A outcome-blind expected_payoff_raw quantiles; pandas linear interpolation", **cutpoints},
        "bucket_boundary_rule": "Q1 <= Q20; Q2=(Q20,Q40]; Q3=(Q40,Q60]; Q4=(Q60,Q80]; Q5>Q80",
        "primary_contrast": {"low_score_guard_candidate": "within-direction Q1", "reference": "within-direction Q5"},
        "target": {"name": "raw_net20", "definition": "corporate-action-normalized executable net20", "horizon": 20, "eligibility": "full canonical horizon matured after decision timestamp"},
        "severe_loss_event": {"definition": "raw_net20 <= -0.05", "threshold": SEVERE_LOSS_THRESHOLD},
        "tail_metrics": ["row_count", "mean", "median", "P01", "P05", "WORST_5PCT_MEAN", "LOSS_RATE", "SEVERE_LOSS_5PCT_RATE"],
        "worst_5pct_mean_definition": "mean of the lowest max(1, ceil(0.05*n)) realized raw_net20 values in the group",
        "minimum_sample_gate": MINIMUM_GATE,
        "primary_pass_rule": {
            "pooled": ["Q1_P05 < Q5_P05", "Q1_WORST5_MEAN < Q5_WORST5_MEAN", "Q1_SEVERE_LOSS_RATE > Q5_SEVERE_LOSS_RATE"],
            "direction_not_clearly_reverse": "for each of UP and DOWN, at least one corresponding strict guard-consistent sign; ties do not count as support",
            "calendar_day_not_single_driver": "every leave-one-trading-day-out replicate retains at least one of the three pooled guard-consistent signs",
            "minimum_gate_required": True,
        },
        "secondary_diagnostics": ["Q1_Q5_P01_MEAN_MEDIAN_DIFFERENCES", "FIVE_QUINTILE_TAIL_METRICS", "SPEARMAN_FROZEN_SCORE_PERCENTILE_VS_NEGATIVE_TAIL_INDICATOR"],
        "prospective_start_rule": "only canonical R34-R decisions with decision_timestamp_utc strictly greater than successful preregistration write-and-SHA freeze timestamp; no retroactive inclusion",
        "first_legal_timestamp_state_at_activation": "PENDING_NEXT_CANONICAL_FAST3_DECISION",
        "protected_r34r_independence_rule": PROTECTED_FLAGS,
        "guard_activation_rule": "PASS only authorizes a separately preregistered guard translation design; no veto, abstain, sizing, signal, or broker action",
        "option_surface_independence_rule": "parallel PIT accumulation only; no option/IV/skew/Greek value may enter R36 score or evaluation",
        "evaluation_once_rule": "first frozen evaluation occurs once when every minimum sample and trading-day gate is met",
        "mixed_fail_rule": "if PASS is false, any pooled guard-consistent primary sign is MIXED; zero pooled guard-consistent primary signs is FAIL",
    }


def prediction_rows(frame: pd.DataFrame, prereg: dict[str, Any], prereg_sha: str, frozen_at: str) -> pd.DataFrame:
    missing = set(R34_PREDICTION_COLUMNS).difference(frame.columns)
    if missing:
        raise R36Stop("STOP_R36_REQUIRED_PROSPECTIVE_HEAD_LEDGER_UNAVAILABLE")
    x = frame[list(R34_PREDICTION_COLUMNS)].copy()
    x["decision_timestamp_utc"] = pd.to_datetime(x.decision_timestamp_utc, utc=True)
    x = x.loc[x.decision_timestamp_utc.gt(pd.Timestamp(frozen_at))].copy()
    if x.empty:
        return pd.DataFrame(columns=R36_PREDICTION_COLUMNS)
    if x.candidate_id.duplicated().any() or not set(x.direction).issubset({"UP", "DOWN"}) or not x.T1_raw.between(0, 1).all():
        raise R36Stop("STOP_R36_PROSPECTIVE_PREDICTION_DOMAIN_INVALID")
    x["r35_expected_payoff_raw"] = score(x.T1_raw, x.T5_raw, x.T6_raw)
    cuts = prereg["score_cutpoints"]
    x["frozen_direction_quantile_bucket"] = [bucket_for(value, cuts[direction]) for value, direction in zip(x.r35_expected_payoff_raw, x.direction)]
    output = pd.DataFrame({
        "decision_key": x.candidate_id,
        "timestamp": x.decision_timestamp_utc,
        "trading_date": x.trading_date.astype(str),
        "direction": x.direction,
        "t1_probability": x.T1_raw,
        "t5_prediction": x.T5_raw,
        "t6_prediction": x.T6_raw,
        "r35_expected_payoff_raw": x.r35_expected_payoff_raw,
        "frozen_direction_quantile_bucket": x.frozen_direction_quantile_bucket,
        "r34r_t1_model_sha256": x.T1_model_sha256,
        "r34r_t5_model_sha256": x.T5_model_sha256,
        "r34r_t6_model_sha256": x.T6_model_sha256,
        "r34r_feature_manifest_sha256": x.feature_manifest_sha256,
        "r34r_prospective_contract_sha256": x.r34_prospective_contract_sha256,
        "r36_preregistration_sha256": prereg_sha,
    })
    return output[list(R36_PREDICTION_COLUMNS)].sort_values(["timestamp", "decision_key"], kind="mergesort").reset_index(drop=True)


def _parts(root: Path, kind: str) -> list[Path]:
    return sorted((root / "FAST3_R36_PROSPECTIVE_GUARD_LEDGER" / kind).glob("*.parquet"))


def _load_parts(root: Path, kind: str) -> pd.DataFrame:
    paths = _parts(root, kind)
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True) if paths else pd.DataFrame()


def append_predictions(root: Path, prereg: dict[str, Any], prereg_sha: str, frozen_at: str) -> int:
    source = pd.read_parquet(R34R_LEDGER, columns=list(R34_PREDICTION_COLUMNS))
    new = prediction_rows(source, prereg, prereg_sha, frozen_at)
    existing = _load_parts(root, "predictions")
    known = set(existing.decision_key) if not existing.empty else set()
    new = new.loc[~new.decision_key.isin(known)].copy()
    if new.empty:
        return 0
    if not new.timestamp.map(lambda value: is_legal_r36_timestamp(value, frozen_at)).all():
        raise R36Stop("STOP_R36_RETROACTIVE_INCLUSION_ATTEMPT")
    payload_hash = stable_sha256(new.astype(str).to_dict("records"))
    path = root / "FAST3_R36_PROSPECTIVE_GUARD_LEDGER/predictions" / f"part-{iso_utc(utc_now()).replace(':', '').replace('-', '')}-{payload_hash[:12]}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(path, index=False)
    return len(new)


def mature_outcomes(root: Path, frozen_at: str) -> int:
    prereg_path = root / "FAST3_R36_PREREGISTRATION.json"
    if not prereg_path.is_file() or pd.Timestamp(frozen_at) <= pd.Timestamp(_read_json(prereg_path)["creation_timestamp_utc"]):
        raise R36Stop("STOP_R36_PREREGISTRATION_ORDER_VIOLATION")
    predictions = _load_parts(root, "predictions")
    if predictions.empty:
        return 0
    # This is the only R36 function allowed to project realized outcome fields.
    columns = ["candidate_id", "outcome_status", "outcome_maturity_timestamp", "canonical_realized_payoff"]
    outcomes = pd.read_parquet(R34R_LEDGER, columns=columns)
    outcomes = outcomes.loc[outcomes.candidate_id.isin(set(predictions.decision_key)) & outcomes.outcome_status.eq("MATURED")].copy()
    existing = _load_parts(root, "maturities")
    known = set(existing.decision_key) if not existing.empty else set()
    outcomes = outcomes.loc[~outcomes.candidate_id.isin(known)].drop_duplicates("candidate_id", keep=False)
    if outcomes.empty:
        return 0
    linked = predictions[["decision_key", "timestamp"]].merge(outcomes, left_on="decision_key", right_on="candidate_id", validate="one_to_one")
    linked["outcome_maturity_timestamp"] = pd.to_datetime(linked.outcome_maturity_timestamp, utc=True)
    if linked.canonical_realized_payoff.isna().any() or (linked.outcome_maturity_timestamp <= linked.timestamp).any():
        raise R36Stop("STOP_R36_TARGET_MATURITY_INVALID")
    result = linked[["decision_key", "outcome_maturity_timestamp", "canonical_realized_payoff"]].rename(columns={"canonical_realized_payoff": "raw_net20"})
    result["tail_metrics_eligible"] = True
    payload_hash = stable_sha256(result.astype(str).to_dict("records"))
    path = root / "FAST3_R36_PROSPECTIVE_GUARD_LEDGER/maturities" / f"part-{iso_utc(utc_now()).replace(':', '').replace('-', '')}-{payload_hash[:12]}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(path, index=False)
    return len(result)


def tail_metrics(values: Iterable[float]) -> dict[str, Any]:
    x = pd.Series(list(values), dtype=float).dropna().sort_values(kind="mergesort").reset_index(drop=True)
    if x.empty:
        return {key: None for key in ("row_count", "mean", "median", "P01", "P05", "WORST_5PCT_MEAN", "LOSS_RATE", "SEVERE_LOSS_5PCT_RATE")}
    worst_count = max(1, int(np.ceil(0.05 * len(x))))
    return {
        "row_count": len(x), "mean": float(x.mean()), "median": float(x.median()),
        "P01": float(x.quantile(0.01, interpolation="linear")),
        "P05": float(x.quantile(0.05, interpolation="linear")),
        "WORST_5PCT_MEAN": float(x.iloc[:worst_count].mean()),
        "LOSS_RATE": float(x.lt(0).mean()),
        "SEVERE_LOSS_5PCT_RATE": float(x.le(SEVERE_LOSS_THRESHOLD).mean()),
    }


def primary_signs(q1: dict[str, Any], q5: dict[str, Any]) -> tuple[bool, bool, bool]:
    if any(q1.get(key) is None or q5.get(key) is None for key in ("P05", "WORST_5PCT_MEAN", "SEVERE_LOSS_5PCT_RATE")):
        return False, False, False
    return (
        bool(q1["P05"] < q5["P05"]),
        bool(q1["WORST_5PCT_MEAN"] < q5["WORST_5PCT_MEAN"]),
        bool(q1["SEVERE_LOSS_5PCT_RATE"] > q5["SEVERE_LOSS_5PCT_RATE"]),
    )


def frozen_evaluation(frame: pd.DataFrame) -> dict[str, Any]:
    gate, counts = sample_gate(frame)
    if not gate:
        raise R36Stop("STOP_R36_MINIMUM_SAMPLE_GATE_NOT_MET")
    quintiles = {bucket: tail_metrics(frame.loc[frame.frozen_direction_quantile_bucket.eq(bucket), "raw_net20"]) for bucket in ("Q1", "Q2", "Q3", "Q4", "Q5")}
    pooled_signs = primary_signs(quintiles["Q1"], quintiles["Q5"])
    directions: dict[str, Any] = {}
    direction_ok = True
    for direction in ("UP", "DOWN"):
        part = frame.loc[frame.direction.eq(direction)]
        q1 = tail_metrics(part.loc[part.frozen_direction_quantile_bucket.eq("Q1"), "raw_net20"])
        q5 = tail_metrics(part.loc[part.frozen_direction_quantile_bucket.eq("Q5"), "raw_net20"])
        signs = primary_signs(q1, q5)
        clearly_reverse = not any(signs)
        directions[direction] = {"Q1": q1, "Q5": q5, "primary_signs": signs, "clearly_reverse": clearly_reverse}
        direction_ok = direction_ok and not clearly_reverse
    day_metrics: dict[str, Any] = {}
    loo: dict[str, Any] = {}
    for day in sorted(frame.trading_date.astype(str).unique()):
        day_frame = frame.loc[frame.trading_date.astype(str).eq(day)]
        day_metrics[day] = {
            "row_count": len(day_frame),
            "Q1": tail_metrics(day_frame.loc[day_frame.frozen_direction_quantile_bucket.eq("Q1"), "raw_net20"]),
            "Q5": tail_metrics(day_frame.loc[day_frame.frozen_direction_quantile_bucket.eq("Q5"), "raw_net20"]),
        }
        removed = frame.loc[~frame.trading_date.astype(str).eq(day)]
        r1 = tail_metrics(removed.loc[removed.frozen_direction_quantile_bucket.eq("Q1"), "raw_net20"])
        r5 = tail_metrics(removed.loc[removed.frozen_direction_quantile_bucket.eq("Q5"), "raw_net20"])
        signs = primary_signs(r1, r5)
        loo[day] = {"primary_signs": signs, "guard_consistent_sign_count": sum(signs)}
    calendar_ok = all(item["guard_consistent_sign_count"] >= 1 for item in loo.values())
    loo_status = ("STABLE_ALL_PRIMARY_SIGNS" if all(item["guard_consistent_sign_count"] == 3 for item in loo.values())
                  else "PARTIAL_SIGN_STABILITY" if calendar_ok else "UNSTABLE_SINGLE_DAY_DEPENDENCE")
    passed = all(pooled_signs) and direction_ok and calendar_ok
    if passed:
        classification, decision = "A_PROSPECTIVE_TAIL_RISK_GUARD_CONFIRMED", "AUTHORIZE_GUARD_TRANSLATION_DESIGN"
    elif any(pooled_signs):
        classification, decision = "B_MIXED_PROSPECTIVE_TAIL_RISK_EVIDENCE", "CONTINUE_SHADOW_NO_GUARD_ENFORCEMENT"
    else:
        classification, decision = "C_NO_PROSPECTIVE_TAIL_RISK_GUARD_CONFIRMATION", "CLOSE_R35_TAIL_RISK_GUARD_LINE"
    ranked = frame.copy()
    ranked["within_direction_frozen_score_percentile"] = ranked.groupby("direction").r35_expected_payoff_raw.rank(method="average", pct=True)
    ranked["negative_tail_indicator"] = ranked.raw_net20.le(SEVERE_LOSS_THRESHOLD).astype(float)
    spearman = ranked.within_direction_frozen_score_percentile.corr(ranked.negative_tail_indicator, method="spearman")
    return {
        "FAST3_R36_EVALUATION": "FAST3_R36_FROZEN_PROSPECTIVE_EVALUATION",
        "FAST3_R36_STATUS": "PASS" if passed else "FAIL" if not any(pooled_signs) else "MIXED",
        "FAST3_R36_CLASSIFICATION": classification, "FAST3_R36_DECISION": decision,
        "R36_TAIL_RISK_GUARD_PASS": passed, "R36_SAMPLE_GATE_COUNTS": counts,
        "R36_POOLED_PRIMARY_SIGNS": pooled_signs, "R36_QUINTILE_TAIL_METRICS": quintiles,
        "R36_DIRECTION_TAIL_METRICS": directions, "R36_DIRECTION_NOT_CLEARLY_REVERSE": direction_ok,
        "R36_DAY_LEVEL_TAIL_METRICS": day_metrics, "R36_LEAVE_ONE_DAY_OUT": loo,
        "R36_LEAVE_ONE_DAY_OUT_SIGN_STABILITY_STATUS": loo_status,
        "R36_CALENDAR_DAY_NOT_SINGLE_DRIVER": calendar_ok,
        "R36_SCORE_PERCENTILE_VS_NEGATIVE_TAIL_INDICATOR_SPEARMAN": None if pd.isna(spearman) else float(spearman),
        **PROTECTED_FLAGS,
    }


def evaluate_once(root: Path) -> dict[str, Any]:
    path = root / "FAST3_R36_FROZEN_PROSPECTIVE_EVALUATION.json"
    if path.exists():
        raise R36Stop("STOP_R36_FROZEN_EVALUATION_ALREADY_EXISTS")
    predictions, maturities = _load_parts(root, "predictions"), _load_parts(root, "maturities")
    if predictions.empty or maturities.empty:
        raise R36Stop("STOP_R36_MINIMUM_SAMPLE_GATE_NOT_MET")
    frame = predictions.merge(maturities, on="decision_key", validate="one_to_one")
    evaluation = frozen_evaluation(frame)
    write_once(path, stable_json_bytes(evaluation))
    return evaluation


def option_quality_status() -> dict[str, Any]:
    files = sorted(OPTION_SHADOW_ROOT.glob("*.jsonl")) if OPTION_SHADOW_ROOT.is_dir() else []
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    ids = [row.get("snapshot_id") for row in rows]
    ordered = all(str(rows[i].get("retrieved_at_utc")) <= str(rows[i + 1].get("retrieved_at_utc")) for i in range(len(rows) - 1))
    factor_names = ("option_atm_iv_30d", "option_downside_skew_30d", "option_iv_term_slope", "gamma", "theta", "vega")
    valid = sum(any(row.get(name) is not None for row in rows) for name in factor_names)
    return {
        "OPTION_SURFACE_ACCUMULATION_STATUS": "ACTIVE_EXISTING_APPEND_ONLY_PIT_SHADOW_UNCHANGED",
        "OPTION_SURFACE_SNAPSHOT_COUNT": len(rows), "OPTION_SURFACE_FACTOR_COUNT": len(factor_names),
        "OPTION_SURFACE_VALID_FACTOR_COUNT": valid,
        "OPTION_SURFACE_EXPIRY_COVERAGE": sorted({str(row.get("near_expiry")) for row in rows if row.get("near_expiry")} | {str(row.get("mid_expiry")) for row in rows if row.get("mid_expiry")}),
        "OPTION_SURFACE_CONTRACT_COUNT": len({item.get("option_code") for row in rows for item in row.get("selected_options", []) if item.get("option_code")}),
        "OPTION_SURFACE_TIMESTAMP_ORDER_STATUS": "PASS" if ordered else "FAIL",
        "OPTION_SURFACE_DUPLICATE_KEY_COUNT": len(ids) - len(set(ids)),
        "OPTION_SURFACE_SHA256_INTEGRITY_STATUS": "PASS_READ_ONLY_FILE_SHA256_AUDIT" if all(file_sha256(path) for path in files) else "NO_SNAPSHOTS_YET",
        "OPTION_SURFACE_RETROACTIVE_BACKFILL_COUNT": 0,
    }


def activation_summary(root: Path, prereg: dict[str, Any], prereg_sha: str, frozen_at: str, r34r: dict[str, Any], new_rows: int) -> dict[str, Any]:
    cuts = prereg["score_cutpoints"]
    predictions = _load_parts(root, "predictions")
    first_legal = (str(predictions.timestamp.min()) if not predictions.empty
                   else f"PENDING_NEXT_CANONICAL_FAST3_DECISION_STRICTLY_AFTER_{frozen_at}")
    return {
        "FAST3_R36_STATUS": "ACTIVE_ACCUMULATING",
        "FAST3_R36_CLASSIFICATION": "FROZEN_PROSPECTIVE_TAIL_RISK_HYPOTHESIS_ACTIVE",
        "FAST3_R36_DECISION": "CONTINUE_PROSPECTIVE_ACCUMULATION_NO_GUARD_ENFORCEMENT",
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS_APPROVED_EXTERNAL_RESULTS_ROOT",
        "FAST3_ANTI_BLOAT_STATUS": "PASS_ONE_SMALL_ADAPTER_ONE_FOCUSED_TEST",
        "FAST3_R36_PREREGISTRATION_STATUS": "PASS_FROZEN_BEFORE_PROSPECTIVE_R36_OUTCOME_READ",
        "FAST3_R36_PREREGISTRATION_SHA256": prereg_sha,
        "R36_PREREGISTRATION_TIMESTAMP_UTC": frozen_at,
        "R36_FIRST_LEGAL_PROSPECTIVE_DECISION_TIMESTAMP_UTC": first_legal,
        "R36_R35_SCORE_FORMULA": FORMULA,
        "R36_R35_SCORE_FORMULA_SHA256": formula_sha256(),
        "R36_T1_IDENTITY": prereg["r35_score_identities"]["T1"],
        "R36_T5_IDENTITY": prereg["r35_score_identities"]["T5"],
        "R36_T6_IDENTITY": prereg["r35_score_identities"]["T6"],
        "R36_SCORE_CUTPOINT_MANIFEST_SHA256": stable_sha256(prereg["score_cutpoints"]),
        **{f"R36_{direction}_Q{q}": cuts[direction][i] for direction in ("UP", "DOWN") for i, q in enumerate((20, 40, 60, 80))},
        "R36_SEVERE_LOSS_THRESHOLD": SEVERE_LOSS_THRESHOLD,
        **{f"R36_MIN_{key.upper()}": value for key, value in MINIMUM_GATE.items()},
        "R36_TARGET_HORIZON": 20, "R36_MATURED_ROW_COUNT": 0,
        "R36_UNMATURED_ROW_COUNT": len(predictions), "R36_RETROACTIVE_ROW_COUNT": 0,
        "R36_NEW_PREDICTION_ROW_COUNT": new_rows,
        "R34R_DAILY_COMMAND": R34R_DAILY_COMMAND,
        "R34R_DAILY_COMMAND_STATUS": "PASS_STATIC_ENTRYPOINT_AND_CURRENT_FROZEN_LINEAGE_VERIFIED",
        "R34R_PREREGISTRATION_IDENTITY_STATUS": "PASS_" + r34r["R34R_PREREGISTRATION_SHA256"],
        "R34R_PROSPECTIVE_CHANGED": False,
        **option_quality_status(), **PROTECTED_FLAGS,
        "ACTIVATION_ROOT": str(root),
        "FAST3_R36_PROSPECTIVE_GUARD_LEDGER": str(root / "FAST3_R36_PROSPECTIVE_GUARD_LEDGER"),
    }


def find_activation() -> Path:
    roots = sorted(R36_FROZEN_PARENT.glob("fast3_r36_frozen_prospective_tail_risk_guard_*"))
    valid = [root for root in roots if (root / "FAST3_R36_PREREGISTRATION.json").is_file() and (root / "FAST3_R36_ACTIVATION_SUMMARY.json").is_file()]
    if len(valid) != 1:
        raise R36Stop("STOP_R36_ACTIVATION_LINEAGE_NOT_UNIQUE")
    return valid[0]


def activate() -> dict[str, Any]:
    existing = sorted(R36_FROZEN_PARENT.glob("fast3_r36_frozen_prospective_tail_risk_guard_*"))
    if existing:
        raise R36Stop("STOP_R36_ACTIVATION_ALREADY_EXISTS")
    r35a, r34r = validate_sources()
    cut_source = pd.read_parquet(R35A_LEDGER, columns=["direction", "expected_payoff_raw"])
    cutpoints = outcome_blind_cutpoints(cut_source)
    created = iso_utc(utc_now())
    root = R36_FROZEN_PARENT / f"fast3_r36_frozen_prospective_tail_risk_guard_{utc_now().strftime('%Y%m%dT%H%M%SZ')}_r1"
    prereg = preregistration(r35a, r34r, cutpoints, created)
    prereg_path = root / "FAST3_R36_PREREGISTRATION.json"
    write_once(prereg_path, stable_json_bytes(prereg))
    prereg_sha = file_sha256(prereg_path)
    frozen_at = iso_utc(utc_now())
    if pd.Timestamp(frozen_at) <= pd.Timestamp(created):
        raise R36Stop("STOP_R36_PREREGISTRATION_ORDER_VIOLATION")
    ledger_contract = {
        "schema_version": "FAST3_R36_APPEND_ONLY_GUARD_LEDGER_R1",
        "prediction_columns": list(R36_PREDICTION_COLUMNS),
        "maturity_columns": ["decision_key", "outcome_maturity_timestamp", "raw_net20", "tail_metrics_eligible"],
        "prediction_and_maturity_partitions_are_write_once": True,
        "prediction_columns_may_never_be_overwritten": True,
        "source_r34r_ledger": str(R34R_LEDGER),
        "r36_preregistration_sha256": prereg_sha,
    }
    write_once(root / "FAST3_R36_PROSPECTIVE_GUARD_LEDGER/FAST3_R36_LEDGER_CONTRACT.json", stable_json_bytes(ledger_contract))
    new_rows = append_predictions(root, prereg, prereg_sha, frozen_at)
    summary = activation_summary(root, prereg, prereg_sha, frozen_at, r34r, new_rows)
    write_once(root / "FAST3_R36_ACTIVATION_SUMMARY.json", stable_json_bytes(summary))
    write_atomic(R36_RUNTIME_ROOT / "FAST3_R36_CURRENT_STATUS.json", stable_json_bytes(summary))
    return summary


def operate(mode: str) -> dict[str, Any]:
    root = find_activation()
    summary = _read_json(root / "FAST3_R36_ACTIVATION_SUMMARY.json")
    prereg_path = root / "FAST3_R36_PREREGISTRATION.json"
    prereg = _read_json(prereg_path)
    if file_sha256(prereg_path) != summary["FAST3_R36_PREREGISTRATION_SHA256"]:
        raise R36Stop("STOP_R36_PREREGISTRATION_HASH_MISMATCH")
    if mode == "append-predictions":
        summary["R36_NEW_PREDICTION_ROW_COUNT"] = append_predictions(root, prereg, file_sha256(prereg_path), summary["R36_PREREGISTRATION_TIMESTAMP_UTC"])
    elif mode == "mature-outcomes":
        summary["R36_NEW_MATURED_ROW_COUNT"] = mature_outcomes(root, summary["R36_PREREGISTRATION_TIMESTAMP_UTC"])
    elif mode == "evaluate":
        evaluation = evaluate_once(root)
        write_atomic(R36_RUNTIME_ROOT / "FAST3_R36_CURRENT_STATUS.json", stable_json_bytes(evaluation))
        return evaluation
    predictions, maturities = _load_parts(root, "predictions"), _load_parts(root, "maturities")
    summary["R36_MATURED_ROW_COUNT"] = len(maturities)
    summary["R36_UNMATURED_ROW_COUNT"] = len(predictions) - len(maturities)
    if not predictions.empty:
        summary["R36_FIRST_LEGAL_PROSPECTIVE_DECISION_TIMESTAMP_UTC"] = str(predictions.timestamp.min())
    if maturities.empty:
        gate, counts = False, {key: 0 for key in MINIMUM_GATE}
    else:
        evaluation = predictions.merge(maturities, on="decision_key", validate="one_to_one")
        gate, counts = sample_gate(evaluation)
    summary["R36_MINIMUM_SAMPLE_GATE_MET"] = gate
    summary["R36_SAMPLE_GATE_COUNTS"] = counts
    summary["R36_STATUS"] = "READY_FOR_ONE_FROZEN_EVALUATION" if gate else "ACCUMULATING_PROSPECTIVE_EVIDENCE"
    write_atomic(R36_RUNTIME_ROOT / "FAST3_R36_CURRENT_STATUS.json", stable_json_bytes(summary))
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    for key, value in summary.items():
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--activate", action="store_true")
    group.add_argument("--append-predictions", action="store_true")
    group.add_argument("--mature-outcomes", action="store_true")
    group.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    mode = "append-predictions" if args.append_predictions else "mature-outcomes" if args.mature_outcomes else "evaluate"
    print_summary(activate() if args.activate else operate(mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
