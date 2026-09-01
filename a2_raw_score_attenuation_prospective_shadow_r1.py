#!/usr/bin/env python3
"""One-arm no-backfill extension of the frozen A2 four-arm forward runner.

This module deliberately does not implement another forward framework. It
reuses the existing four-arm runner's calendar, accounting, atomic JSON,
exclusive lock, append-only CSV, and row-hash-chain implementations. The
frozen four-arm contract and its four existing artifacts are read-only here.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pandas as pd


REPO = Path(r"D:\us-tech-quant")
V22 = REPO / "scripts" / "v22"
if str(V22) not in sys.path:
    sys.path.insert(0, str(V22))

import a2_three_arm_postfreeze_forward_r1 as forward  # noqa: E402


TASK_ID = "A2_RAW_SCORE_ATTENUATION_PROSPECTIVE_SHADOW_R1"
ARM_ID = "RAW_SCORE_ATTENUATED_A2_SHADOW_R1"
SHADOW_STATUS = "RESEARCH_ONLY_PROSPECTIVE_SHADOW"

EXTENSION_ROOT = forward.RESULTS / TASK_ID
SHADOW_STATE = EXTENSION_ROOT / "shadow_registration_state.json"
SHADOW_LEDGER = EXTENSION_ROOT / "shadow_ledger.csv"
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")

ATTENUATION_ROOT = forward.RESULTS / "A2_RAW_SCORE_ACTIVE_DEVIATION_ATTENUATION_R1"
PROBABILITY_ROOT = forward.RESULTS / "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1"
ATTENUATION_REPORT = ATTENUATION_ROOT / "final_report.md"
ATTENUATION_SUMMARY = ATTENUATION_ROOT / "attenuation_summary.csv"
PROBABILITY_REPORT = PROBABILITY_ROOT / "final_report.md"
PROBABILITY_SUMMARY = PROBABILITY_ROOT / "oos_summary.csv"
OOS_PREDICTIONS = PROBABILITY_ROOT / "oos_predictions.parquet"

FIXED_SOURCE_FOLD = "OUTER_5"
TOL = 1e-12

SHADOW_LEDGER_FIELDS = [
    "session_date", "signal_date", "decision_timestamp", "economic_active_timestamp",
    "outcome_timestamp", "session_input_sha256", "base_forward_contract_hash",
    "base_forward_row_hash", "probability_spec_hash", "raw_a2_score",
    "predicted_right_tail_probability", "reference_base_rate", "lambda",
    "a_target_weights", "a2_target_weights", "shadow_target_weights",
    "prior_shadow_weights", "trade_weights", "shadow_return", "shadow_nav",
    "shadow_turnover", "shadow_cost", "a_return", "a_nav", "a_turnover", "a_cost",
    "a2_return", "a2_nav", "a2_turnover", "a2_cost", "shadow_minus_a2_return",
    "shadow_minus_a_active_return", "turnover_difference_vs_a2", "cost_difference_vs_a2",
    "nav_difference_vs_a2", "right_tail_label", "a2_active_contribution",
    "shadow_active_contribution", "attenuation_effect", "previous_row_hash", "row_hash",
]


def canonical_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def predicted_probability(raw_score: float, specification: Mapping[str, Any]) -> float:
    logit = float(specification["raw_logit_intercept"]) + float(specification["raw_logit_slope"]) * float(raw_score)
    if logit >= 0:
        result = 1.0 / (1.0 + math.exp(-logit))
    else:
        exp_value = math.exp(logit)
        result = exp_value / (1.0 + exp_value)
    forward.require(0.0 <= result <= 1.0, "PROBABILITY_RANGE")
    return result


def lambda_value(probability: float, reference_base_rate: float) -> float:
    forward.require(reference_base_rate > 0.0, "REFERENCE_BASE_RATE_NONPOSITIVE")
    result = min(1.0, max(0.0, float(probability) / float(reference_base_rate)))
    forward.require(0.0 <= result <= 1.0, "LAMBDA_RANGE")
    return result


def blended_target(
    a_weights: Mapping[str, float], a2_weights: Mapping[str, float], attenuation: float
) -> dict[str, float]:
    forward.require(0.0 <= attenuation <= 1.0, "LAMBDA_RANGE")
    tickers = sorted(set(a_weights) | set(a2_weights))
    result = {
        ticker: float(a_weights.get(ticker, 0.0))
        + attenuation * (float(a2_weights.get(ticker, 0.0)) - float(a_weights.get(ticker, 0.0)))
        for ticker in tickers
    }
    result = {ticker: value for ticker, value in result.items() if abs(value) > 1e-15}
    forward.require(all(value >= -TOL for value in result.values()), "SHADOW_SHORT_FORBIDDEN")
    forward.require(
        sum(result.values()) <= max(sum(a_weights.values()), sum(a2_weights.values())) + TOL,
        "SHADOW_LEVERAGE_INCREASE",
    )
    for ticker in tickers:
        original = float(a2_weights.get(ticker, 0.0)) - float(a_weights.get(ticker, 0.0))
        shadow = float(result.get(ticker, 0.0)) - float(a_weights.get(ticker, 0.0))
        forward.require(abs(shadow) <= abs(original) + TOL, "ACTIVE_EXPOSURE_AMPLIFICATION", ticker)
    return result


def summary_value(path: Path, section: str, metric: str, scope: str) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        matches = [
            row["value"]
            for row in csv.DictReader(handle)
            if row.get("section") == section and row.get("metric") == metric and row.get("scope") == scope
        ]
    forward.require(len(matches) == 1, "SUMMARY_VALUE_IDENTITY", (path, section, metric, scope))
    return str(matches[0])


def recover_fixed_probability_specification() -> dict[str, Any]:
    required = (ATTENUATION_REPORT, ATTENUATION_SUMMARY, PROBABILITY_REPORT, PROBABILITY_SUMMARY, OOS_PREDICTIONS)
    forward.require(all(path.is_file() for path in required), "AUTHORITATIVE_PROBABILITY_INPUT_MISSING")
    attenuation_text = ATTENUATION_REPORT.read_text(encoding="utf-8")
    forward.require(
        "ATTENUATION_MECHANISM_CLASSIFICATION=SUPPORTED_REDUCES_NONTAIL_DRAG_WITH_TAIL_PRESERVATION" in attenuation_text,
        "ATTENUATION_CLASSIFICATION_IDENTITY",
    )
    predictions = pd.read_parquet(OOS_PREDICTIONS)
    fold = predictions.loc[
        predictions.outer_fold.eq(FIXED_SOURCE_FOLD),
        ["raw_score", "predicted_right_tail_probability"],
    ].copy()
    forward.require(len(predictions) == 625 and len(fold) == 125, "OOS_PREDICTION_IDENTITY")
    fold = fold.sort_values("raw_score", kind="mergesort").reset_index(drop=True)
    forward.require(fold.raw_score.nunique() > 1, "RAW_SCORE_DEGENERATE")
    low, high = fold.iloc[0], fold.iloc[-1]
    low_p, high_p = float(low.predicted_right_tail_probability), float(high.predicted_right_tail_probability)
    forward.require(0.0 < low_p < 1.0 and 0.0 < high_p < 1.0, "PERSISTED_PROBABILITY_OPEN_INTERVAL")
    low_logit = math.log(low_p / (1.0 - low_p))
    high_logit = math.log(high_p / (1.0 - high_p))
    raw_slope = (high_logit - low_logit) / (float(high.raw_score) - float(low.raw_score))
    raw_intercept = low_logit - raw_slope * float(low.raw_score)
    local_spec = {"raw_logit_intercept": raw_intercept, "raw_logit_slope": raw_slope}
    reconstructed = fold.raw_score.map(lambda value: predicted_probability(float(value), local_spec))
    max_error = float((reconstructed - fold.predicted_right_tail_probability.astype(float)).abs().max())
    forward.require(max_error <= 5e-15, "PERSISTED_MODEL_PARAMETER_RECOVERY_ERROR", max_error)
    reference_base_rate = float(summary_value(
        ATTENUATION_SUMMARY, "TRAIN_ONLY_BASE_RATE", "TRAIN_BASE_RATE", FIXED_SOURCE_FOLD
    ))
    standardized_coefficient = float(summary_value(
        PROBABILITY_SUMMARY, "OUTER_FOLD", "LOGISTIC_COEFFICIENT", FIXED_SOURCE_FOLD
    ))
    forward.require(reference_base_rate == 63.0 / 624.0, "REFERENCE_BASE_RATE_IDENTITY")
    forward.require(raw_slope > 0.0 and standardized_coefficient > 0.0, "PROBABILITY_DIRECTION_IDENTITY")
    core = {
        "specification_id": "RAW_SCORE_RIGHT_TAIL_LOGISTIC_OUTER_5_FROZEN_R1",
        "source_role": "LATEST_EXISTING_STRICT_CHRONOLOGICAL_OOS_FITTED_SPECIFICATION_NO_REFIT",
        "source_outer_fold": FIXED_SOURCE_FOLD,
        "probability_formula": "sigmoid(RAW_LOGIT_INTERCEPT + RAW_LOGIT_SLOPE * RAW_A2_SCORE)",
        "raw_logit_intercept": raw_intercept,
        "raw_logit_slope": raw_slope,
        "standardized_logistic_coefficient": standardized_coefficient,
        "parameter_recovery_method": "EXACT_ALGEBRA_FROM_PERSISTED_OUTER_5_PROBABILITIES_NO_FIT",
        "parameter_recovery_max_probability_error": max_error,
        "reference_base_rate": reference_base_rate,
        "reference_base_rate_identity": "OUTER_5_EXACT_PURGED_TRAIN_LABEL_RATE_63_OF_624",
        "lambda_formula": "clip(P_HAT / REFERENCE_BASE_RATE, 0, 1)",
        "outcome_feedback_allowed": False,
        "refit_allowed": False,
        "recalibration_allowed": False,
        "authoritative_artifacts": {
            str(ATTENUATION_REPORT): forward.sha256_file(ATTENUATION_REPORT),
            str(ATTENUATION_SUMMARY): forward.sha256_file(ATTENUATION_SUMMARY),
            str(PROBABILITY_REPORT): forward.sha256_file(PROBABILITY_REPORT),
            str(PROBABILITY_SUMMARY): forward.sha256_file(PROBABILITY_SUMMARY),
            str(OOS_PREDICTIONS): forward.sha256_file(OOS_PREDICTIONS),
        },
    }
    return {**core, "probability_spec_hash": forward.stable_hash(core)}


@contextmanager
def shadow_ledger_schema() -> Iterator[None]:
    """Bind the existing ledger helpers to the extension schema for one call."""
    original = forward.LEDGER_FIELDS
    forward.LEDGER_FIELDS = SHADOW_LEDGER_FIELDS
    try:
        yield
    finally:
        forward.LEDGER_FIELDS = original


def shadow_rows(path: Path = SHADOW_LEDGER) -> list[dict[str, str]]:
    with shadow_ledger_schema():
        return forward.ledger_rows(path)


def shadow_chain(path: Path = SHADOW_LEDGER) -> dict[str, Any]:
    with shadow_ledger_schema():
        return forward.validate_hash_chain(path)


def append_shadow_row(path: Path, row: Mapping[str, Any], first_session: str) -> tuple[str, dict[str, str]]:
    session = str(row["session_date"])
    identity_fields = ("session_input_sha256", "base_forward_row_hash", "probability_spec_hash")
    existing = [item for item in shadow_rows(path) if item["session_date"] == session]
    if existing:
        forward.require(len(existing) == 1, "DUPLICATE_SESSION_CORRUPTION", session)
        forward.require(
            all(existing[0].get(field) == str(row.get(field, "")) for field in identity_fields),
            "CONFLICT_EXISTING_SHADOW_SESSION",
            session,
        )
        return "ALREADY_APPENDED_IDENTICAL", existing[0]
    try:
        with shadow_ledger_schema():
            appended = forward.append_ledger_row(path, row, {"first_eligible_forward_session": first_session})
    except forward.ForwardGateError as exc:
        if "DUPLICATE_SESSION_REJECTED" not in str(exc):
            raise
        return append_shadow_row(path, row, first_session)
    return "APPENDED", appended


def base_artifact_hashes() -> dict[str, str]:
    paths = (forward.FORWARD_CONTRACT, forward.FORWARD_LEDGER, forward.FORWARD_STATE, forward.HASH_MANIFEST)
    forward.require(all(path.is_file() for path in paths), "BASE_FORWARD_ARTIFACT_MISSING")
    return {path.name: forward.sha256_file(path) for path in paths}


def first_session_after_registration(registration_utc: datetime) -> str:
    provider = forward.ForwardShadowTradingCalendarProvider(forward.CALENDAR_CONTRACT)
    return forward.first_session_after_freeze(provider, registration_utc)


def build_registration_state(registration_utc: datetime) -> dict[str, Any]:
    contract = forward.load_contract()
    main_state = forward.read_json(forward.FORWARD_STATE)
    chain = forward.verify_state(contract, main_state)
    specification = recover_fixed_probability_specification()
    ledger_bytes = forward.FORWARD_LEDGER.read_bytes()
    registration = {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "arm_id": ARM_ID,
        "display_purpose": "Raw-score right-tail probability based attenuation of A2-minus-A active deviation",
        "status": SHADOW_STATUS,
        "registration_timestamp_utc": registration_utc.isoformat(),
        "registration_timestamp_et": registration_utc.astimezone(forward.MARKET_TZ).isoformat(),
        "first_eligible_shadow_session": first_session_after_registration(registration_utc),
        "evidence_start_rule": "FIRST_BOUND_US_SESSION_WITH_OPEN_STRICTLY_AFTER_SHADOW_REGISTRATION",
        "no_backfill": True,
        "post_registration_only": True,
        "not_canonical": True,
        "not_production": True,
        "broker_order_allowed": False,
        "base_forward": {
            "experiment_id": forward.TASK_ID,
            "root": str(forward.OUT),
            "contract_file_sha256": forward.sha256_file(forward.FORWARD_CONTRACT),
            "contract_hash": contract["forward_contract_hash"],
            "contract_modified": False,
            "arm_ids": list(forward.ARMS),
            "ledger_prefix_bytes": len(ledger_bytes),
            "ledger_prefix_sha256": forward.sha256_bytes(ledger_bytes),
            "ledger_row_count_at_registration": chain["row_count"],
            "artifact_hashes_at_registration": base_artifact_hashes(),
        },
        "infrastructure_reuse": {
            "calendar": "forward_shadow.trading_calendar.ForwardShadowTradingCalendarProvider",
            "accounting": "a2_three_arm_postfreeze_forward_r1.rebalance_and_mark",
            "atomic_state": "a2_successor_s1.successor_control.atomic_write_json",
            "locking": "a2_three_arm_postfreeze_forward_r1.LedgerLock",
            "ledger_append": "a2_three_arm_postfreeze_forward_r1.append_ledger_row",
            "hash_chain": "a2_three_arm_postfreeze_forward_r1.validate_hash_chain",
        },
        "probability_specification": specification,
        "mapping": {
            "lambda": "clip(P_HAT / REFERENCE_BASE_RATE, 0, 1)",
            "target": "W_A + LAMBDA * (W_A2 - W_A)",
            "lambda_min": 0.0,
            "lambda_max": 1.0,
            "parameter_update_path": False,
        },
        "comparators": {
            "A": {
                "mode": "SAME_AUTHORITATIVE_SESSION_BUNDLE_TARGET_REFERENCE_WITH_REUSED_ACCOUNTING",
                "separate_forward_arm_created": False,
            },
            "A2": {
                "mode": "LINK_EXISTING_BASE_FORWARD_LEDGER_ARM0_RAW_A2_ROW",
                "arm_id": forward.ARM0,
                "separate_forward_arm_created": False,
            },
        },
        "session_input_extension": {
            "base_pointer": str(forward.SESSION_INPUT_POINTER),
            "additional_required_fields": [
                "raw_a2_score", "raw_a2_score_available_timestamp",
                "raw_a2_score_model_hash", "a_target_rows",
            ],
            "historical_oos_probability_accepted": False,
            "predicted_probability_input_accepted": False,
            "same_base_session_must_already_be_committed": True,
        },
        "source_sha256": forward.sha256_file(Path(__file__)),
    }
    return {
        "registration": registration,
        "registration_hash": forward.stable_hash(registration),
        "runtime": {
            "forward_session_count": 0,
            "ledger_row_count": 0,
            "last_session_date": None,
            "last_row_hash": "GENESIS",
            "shadow_arm_state": forward.initial_arm_state(),
            "a_comparator_state": forward.initial_arm_state(),
            "a2_comparator_nav": 1.0,
            "prospective_tail_contribution": 0.0,
            "prospective_nontail_contribution": 0.0,
            "prospective_a2_tail_contribution": 0.0,
            "prospective_a2_nontail_contribution": 0.0,
        },
        "validation": {},
    }


def load_shadow_state() -> dict[str, Any]:
    state = forward.read_json(SHADOW_STATE)
    registration = state.get("registration", {})
    forward.require(
        forward.stable_hash(registration) == state.get("registration_hash"),
        "SHADOW_REGISTRATION_HASH_INVALID",
    )
    forward.require(registration.get("arm_id") == ARM_ID, "SHADOW_ARM_IDENTITY")
    forward.require(registration.get("no_backfill") is True, "SHADOW_BACKFILL_GATE")
    forward.require(
        registration.get("source_sha256") == forward.sha256_file(Path(__file__)),
        "SHADOW_SOURCE_IDENTITY_DRIFT",
    )
    return state


def verify_base_immutability(registration: Mapping[str, Any]) -> None:
    base_info = registration["base_forward"]
    forward.require(
        forward.sha256_file(forward.FORWARD_CONTRACT) == base_info["contract_file_sha256"],
        "BASE_FROZEN_CONTRACT_MODIFIED",
    )
    current = forward.FORWARD_LEDGER.read_bytes()
    prefix_length = int(base_info["ledger_prefix_bytes"])
    forward.require(len(current) >= prefix_length, "BASE_LEDGER_TRUNCATED")
    forward.require(
        forward.sha256_bytes(current[:prefix_length]) == base_info["ledger_prefix_sha256"],
        "BASE_ARM0_ARM3_HISTORY_MODIFIED",
    )


def verify_shadow_state(state: Mapping[str, Any]) -> dict[str, Any]:
    registration = state["registration"]
    verify_base_immutability(registration)
    chain = shadow_chain()
    runtime = state["runtime"]
    forward.require(chain["status"] == "PASS", "SHADOW_HASH_CHAIN_INVALID", chain["reasons"])
    forward.require(int(runtime["ledger_row_count"]) == chain["row_count"], "SHADOW_STATE_LEDGER_COUNT")
    forward.require(int(runtime["forward_session_count"]) == chain["row_count"], "SHADOW_SESSION_COUNT")
    forward.require(runtime["last_row_hash"] == chain["last_row_hash"], "SHADOW_LAST_ROW_HASH")
    forward.require(
        recover_fixed_probability_specification() == registration["probability_specification"],
        "PROBABILITY_SPECIFICATION_DRIFT",
    )
    return chain


def self_validate(first_session: str, specification: Mapping[str, Any]) -> dict[str, Any]:
    a = {"AAA": 0.6, "BBB": 0.4}
    a2 = {"BBB": 0.25, "CCC": 0.75}
    forward.require(blended_target(a, a2, 0.0) == a, "LAMBDA_ZERO_A_IDENTITY")
    forward.require(blended_target(a, a2, 1.0) == a2, "LAMBDA_ONE_A2_IDENTITY")
    forward.require(
        lambda_value(0.0, 0.1) == 0.0 and lambda_value(0.2, 0.1) == 1.0,
        "LAMBDA_CLIP_IDENTITY",
    )
    forward.require(specification["refit_allowed"] is False, "REFIT_FIREWALL")
    temp_root = EXTENSION_ROOT / ".self_test"
    forward.require(not temp_root.exists(), "SELF_TEST_TEMP_PATH_PREEXISTS")
    temp_root.mkdir(parents=False, exist_ok=False)
    try:
        ledger = temp_root / "shadow.csv"
        with shadow_ledger_schema():
            forward.ensure_ledger(ledger)
        provider = forward.ForwardShadowTradingCalendarProvider(forward.CALENDAR_CONTRACT)
        first_index = provider.sessions.index(first_session)
        forward.require(first_index > 0, "SELF_TEST_FIRST_SESSION_BOUNDARY")
        prior_session = provider.sessions[first_index - 1]
        rejected = False
        try:
            append_shadow_row(ledger, {
                "session_date": prior_session,
                "session_input_sha256": "pre",
                "base_forward_row_hash": "pre",
                "probability_spec_hash": specification["probability_spec_hash"],
            }, first_session)
        except forward.ForwardGateError as exc:
            rejected = "PRE_FREEZE_SESSION_REJECTED" in str(exc)
        forward.require(rejected, "SELF_TEST_NO_BACKFILL_REJECTION")
        row = {
            "session_date": first_session,
            "session_input_sha256": "input",
            "base_forward_row_hash": "base",
            "probability_spec_hash": specification["probability_spec_hash"],
        }
        first_status, _ = append_shadow_row(ledger, row, first_session)
        second_status, _ = append_shadow_row(ledger, row, first_session)
        forward.require(
            first_status == "APPENDED" and second_status == "ALREADY_APPENDED_IDENTICAL",
            "SELF_TEST_IDEMPOTENCY",
        )
        chain = shadow_chain(ledger)
        forward.require(chain["status"] == "PASS" and chain["row_count"] == 1, "SELF_TEST_HASH_CHAIN")
    finally:
        shutil.rmtree(temp_root, ignore_errors=False)
    return {
        "status": "PASS",
        "no_backfill_rejection": "PASS",
        "idempotent_daily_append": "PASS",
        "hash_chain": "PASS_REUSED",
        "file_lock": "PASS_REUSED",
        "lambda_range": "PASS",
        "lambda_zero_reproduces_a": "PASS",
        "lambda_one_reproduces_a2": "PASS",
        "temporary_files_cleaned": True,
    }


def initialize() -> tuple[dict[str, Any], bool]:
    before = base_artifact_hashes()
    if SHADOW_STATE.exists() or SHADOW_LEDGER.exists():
        forward.require(
            SHADOW_STATE.is_file() and SHADOW_LEDGER.is_file(),
            "PARTIAL_SHADOW_INITIALIZATION",
        )
        state = load_shadow_state()
        verify_shadow_state(state)
        forward.require(
            base_artifact_hashes() == before,
            "BASE_FORWARD_ARTIFACT_MUTATION_ON_IDEMPOTENT_INIT",
        )
        return state, False
    EXTENSION_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        with shadow_ledger_schema():
            forward.ensure_ledger(SHADOW_LEDGER)
        state = build_registration_state(utc_now())
        state["validation"] = self_validate(
            state["registration"]["first_eligible_shadow_session"],
            state["registration"]["probability_specification"],
        )
        forward.atomic_write_json(SHADOW_STATE, state)
        verify_shadow_state(state)
        forward.require(base_artifact_hashes() == before, "BASE_FORWARD_ARTIFACT_MUTATION_ON_INIT")
        return state, True
    except Exception:
        if EXTENSION_ROOT.is_dir() and not SHADOW_STATE.exists():
            shutil.rmtree(EXTENSION_ROOT, ignore_errors=False)
        raise


def weights_from_rows(
    rows: Sequence[Mapping[str, Any]], weight_field: str, code: str
) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        weight = float(row.get(weight_field, math.nan))
        forward.require(
            ticker and ticker not in result and math.isfinite(weight) and weight >= 0.0,
            code,
            ticker,
        )
        if weight > 1e-15:
            result[ticker] = weight
    forward.require(abs(sum(result.values()) - 1.0) <= TOL, code, sum(result.values()))
    return result


def prior_weights(arm_state: Mapping[str, Any], entry: Mapping[str, float]) -> dict[str, float]:
    shares = {str(key): float(value) for key, value in arm_state.get("shares", {}).items()}
    nav = float(arm_state.get("cash", 1.0)) + sum(
        quantity * float(entry[ticker]) for ticker, quantity in shares.items()
    )
    forward.require(nav > 0.0, "PRIOR_NAV_NONPOSITIVE")
    return {ticker: quantity * float(entry[ticker]) / nav for ticker, quantity in shares.items()}


def committed_main_row(session: str) -> tuple[dict[str, str], float]:
    rows = forward.ledger_rows(forward.FORWARD_LEDGER)
    matches = [row for row in rows if row["session_date"] == session]
    forward.require(len(matches) == 1, "BASE_ARM0_SESSION_NOT_COMMITTED", session)
    index = rows.index(matches[0])
    prior_nav = 1.0 if index == 0 else float(rows[index - 1]["raw_nav"])
    return matches[0], prior_nav


def validate_daily_input(
    payload: Mapping[str, Any], state: Mapping[str, Any], source: Path
) -> dict[str, Any]:
    registration = state["registration"]
    runtime = state["runtime"]
    provider = forward.ForwardShadowTradingCalendarProvider(forward.CALENDAR_CONTRACT)
    session = str(payload.get("session_date", ""))
    forward.require(provider.is_session(session), "SESSION_NOT_ON_BOUND_CALENDAR", session)
    forward.require(
        session >= registration["first_eligible_shadow_session"],
        "PRE_REGISTRATION_SESSION_REJECTED",
        session,
    )
    expected = (
        forward.next_session(provider, runtime["last_session_date"])
        if runtime.get("last_session_date")
        else registration["first_eligible_shadow_session"]
    )
    forward.require(session == expected, "OUT_OF_ORDER_SHADOW_SESSION", (session, expected))
    signal = str(payload.get("signal_date", ""))
    forward.require(
        signal == forward.previous_session(provider, session),
        "SHADOW_SIGNAL_SESSION_ALIGNMENT",
    )
    decision = forward.parse_timestamp(str(payload.get("decision_timestamp", "")))
    registration_time = forward.parse_timestamp(registration["registration_timestamp_utc"])
    entry_time = datetime.combine(
        datetime.fromisoformat(session).date(), forward.OPEN_TIME, forward.MARKET_TZ
    ).astimezone(timezone.utc)
    outcome = forward.parse_timestamp(str(payload.get("outcome_timestamp", "")))
    outcome_floor = datetime.combine(
        datetime.fromisoformat(forward.next_session(provider, session)).date(),
        forward.OPEN_TIME,
        forward.MARKET_TZ,
    ).astimezone(timezone.utc)
    forward.require(
        registration_time < decision < entry_time,
        "DECISION_NOT_POST_REGISTRATION_EXANTE",
    )
    forward.require(outcome >= outcome_floor and utc_now() >= outcome, "SHADOW_OUTCOME_NOT_MATURE")
    score_time = forward.parse_timestamp(str(payload.get("raw_a2_score_available_timestamp", "")))
    forward.require(
        registration_time < score_time <= decision,
        "RAW_SCORE_NOT_POST_REGISTRATION_PIT",
    )
    contract = forward.load_contract()
    forward.require(
        payload.get("raw_a2_score_model_hash") == contract["frozen_identities"]["raw_model_hash"],
        "RAW_SCORE_MODEL_IDENTITY",
    )
    forward.require(
        "predicted_right_tail_probability" not in payload,
        "HISTORICAL_OR_EXTERNAL_PROBABILITY_INPUT_FORBIDDEN",
    )
    base_row, base_prior_nav = committed_main_row(session)
    forward.require(
        base_row["decision_timestamp"] == decision.isoformat(),
        "BASE_SHADOW_DECISION_TIMESTAMP_MISMATCH",
    )
    forward.require(
        base_row["outcome_timestamp"] == outcome.isoformat(),
        "BASE_SHADOW_OUTCOME_TIMESTAMP_MISMATCH",
    )
    a2 = weights_from_rows(
        list(payload.get("target_rows", [])), "raw_target_weight", "A2_TARGET_IDENTITY"
    )
    a = weights_from_rows(
        list(payload.get("a_target_rows", [])), "target_weight", "A_TARGET_IDENTITY"
    )
    prices = {
        str(row.get("ticker", "")).upper(): row for row in payload.get("price_rows", [])
    }
    required = (
        set(a)
        | set(a2)
        | set(runtime["shadow_arm_state"].get("shares", {}))
        | set(runtime["a_comparator_state"].get("shares", {}))
    )
    forward.require(required <= set(prices), "SHADOW_PRICE_COVERAGE", sorted(required - set(prices)))
    for ticker in required:
        forward.require(
            float(prices[ticker]["entry_open"]) > 0
            and float(prices[ticker]["outcome_open"]) > 0,
            "SHADOW_INVALID_PRICE",
            ticker,
        )
    return {
        "session": session,
        "signal": signal,
        "decision": decision,
        "entry_time": entry_time,
        "outcome": outcome,
        "a": a,
        "a2": a2,
        "prices": prices,
        "base_row": base_row,
        "base_prior_nav": base_prior_nav,
        "input_sha256": forward.sha256_file(source),
    }


def daily(input_path: Path | None = None) -> dict[str, Any]:
    state = load_shadow_state()
    verify_shadow_state(state)
    source = (input_path or forward.SESSION_INPUT_POINTER).resolve()
    if not source.is_file():
        return {
            "status": "AWAITING_HASH_BOUND_POST_REGISTRATION_SESSION_INPUT",
            "forward_session_count": state["runtime"]["forward_session_count"],
            "ledger_mutated": False,
        }
    payload = forward.read_json(source)
    session = str(payload.get("session_date", ""))
    duplicates = [row for row in shadow_rows() if row["session_date"] == session]
    if duplicates:
        input_hash = forward.sha256_file(source)
        forward.require(
            len(duplicates) == 1 and duplicates[0]["session_input_sha256"] == input_hash,
            "CONFLICT_EXISTING_SHADOW_SESSION",
        )
        return {
            "status": "ALREADY_APPENDED_IDENTICAL",
            "session_date": session,
            "forward_session_count": state["runtime"]["forward_session_count"],
            "ledger_mutated": False,
        }
    checked = validate_daily_input(payload, state, source)
    specification = state["registration"]["probability_specification"]
    raw_score = float(payload["raw_a2_score"])
    forward.require(math.isfinite(raw_score), "RAW_SCORE_NONFINITE")
    p_hat = predicted_probability(raw_score, specification)
    attenuation = lambda_value(p_hat, float(specification["reference_base_rate"]))
    shadow_target = blended_target(checked["a"], checked["a2"], attenuation)
    entry = {ticker: float(row["entry_open"]) for ticker, row in checked["prices"].items()}
    outcome = {
        ticker: float(row["outcome_open"]) for ticker, row in checked["prices"].items()
    }
    runtime = json.loads(json.dumps(state["runtime"]))
    prior_shadow = prior_weights(runtime["shadow_arm_state"], entry)
    trade_weights = {
        ticker: float(shadow_target.get(ticker, 0.0)) - float(prior_shadow.get(ticker, 0.0))
        for ticker in sorted(set(shadow_target) | set(prior_shadow))
    }
    shadow_state, shadow_result = forward.rebalance_and_mark(
        runtime["shadow_arm_state"], shadow_target, entry, outcome
    )
    a_state, a_result = forward.rebalance_and_mark(
        runtime["a_comparator_state"], checked["a"], entry, outcome
    )
    base_row = checked["base_row"]
    a2_return = float(base_row["raw_return"])
    a2_nav = float(runtime["a2_comparator_nav"]) * (1.0 + a2_return)
    a2_cost_rate = float(base_row["raw_cost"]) / float(checked["base_prior_nav"])
    shadow_cost_rate = float(shadow_result["cost"]) / float(runtime["shadow_arm_state"]["nav"])
    right_tail: str = ""
    a2_active: float | str = ""
    shadow_active: float | str = ""
    attenuation_effect: float | str = ""
    maturation = payload.get("right_tail_maturation")
    if maturation is not None:
        label = int(maturation.get("label"))
        forward.require(label in (0, 1), "RIGHT_TAIL_LABEL")
        forward.verify_external_reference(
            maturation.get("source", {}), "RIGHT_TAIL_MATURATION_SOURCE_HASH"
        )
        matured_at = forward.parse_timestamp(str(maturation.get("matured_at_utc", "")))
        forward.require(matured_at <= utc_now(), "RIGHT_TAIL_LABEL_NOT_MATURE")
        right_tail = str(label)
        a2_active = a2_return - float(a_result["return"])
        shadow_active = float(shadow_result["return"]) - float(a_result["return"])
        attenuation_effect = shadow_active - a2_active
    row = {
        "session_date": checked["session"],
        "signal_date": checked["signal"],
        "decision_timestamp": checked["decision"].isoformat(),
        "economic_active_timestamp": checked["entry_time"].isoformat(),
        "outcome_timestamp": checked["outcome"].isoformat(),
        "session_input_sha256": checked["input_sha256"],
        "base_forward_contract_hash": state["registration"]["base_forward"]["contract_hash"],
        "base_forward_row_hash": base_row["row_hash"],
        "probability_spec_hash": specification["probability_spec_hash"],
        "raw_a2_score": raw_score,
        "predicted_right_tail_probability": p_hat,
        "reference_base_rate": specification["reference_base_rate"],
        "lambda": attenuation,
        "a_target_weights": canonical_text(checked["a"]),
        "a2_target_weights": canonical_text(checked["a2"]),
        "shadow_target_weights": canonical_text(shadow_target),
        "prior_shadow_weights": canonical_text(prior_shadow),
        "trade_weights": canonical_text(trade_weights),
        "shadow_return": shadow_result["return"],
        "shadow_nav": shadow_result["nav"],
        "shadow_turnover": shadow_result["turnover"],
        "shadow_cost": shadow_cost_rate,
        "a_return": a_result["return"],
        "a_nav": a_result["nav"],
        "a_turnover": a_result["turnover"],
        "a_cost": float(a_result["cost"]) / float(runtime["a_comparator_state"]["nav"]),
        "a2_return": a2_return,
        "a2_nav": a2_nav,
        "a2_turnover": base_row["raw_turnover"],
        "a2_cost": a2_cost_rate,
        "shadow_minus_a2_return": float(shadow_result["return"]) - a2_return,
        "shadow_minus_a_active_return": float(shadow_result["return"]) - float(a_result["return"]),
        "turnover_difference_vs_a2": float(shadow_result["turnover"]) - float(base_row["raw_turnover"]),
        "cost_difference_vs_a2": shadow_cost_rate - a2_cost_rate,
        "nav_difference_vs_a2": float(shadow_result["nav"]) - a2_nav,
        "right_tail_label": right_tail,
        "a2_active_contribution": a2_active,
        "shadow_active_contribution": shadow_active,
        "attenuation_effect": attenuation_effect,
    }
    append_status, appended = append_shadow_row(
        SHADOW_LEDGER, row, state["registration"]["first_eligible_shadow_session"]
    )
    if append_status == "ALREADY_APPENDED_IDENTICAL":
        return {
            "status": append_status,
            "session_date": checked["session"],
            "forward_session_count": runtime["forward_session_count"],
            "ledger_mutated": False,
        }
    runtime["forward_session_count"] = int(runtime["forward_session_count"]) + 1
    runtime["ledger_row_count"] = int(runtime["ledger_row_count"]) + 1
    runtime["last_session_date"] = checked["session"]
    runtime["last_row_hash"] = appended["row_hash"]
    runtime["shadow_arm_state"] = shadow_state
    runtime["a_comparator_state"] = a_state
    runtime["a2_comparator_nav"] = a2_nav
    if right_tail != "":
        side = "tail" if right_tail == "1" else "nontail"
        runtime[f"prospective_a2_{side}_contribution"] += float(a2_active)
        runtime[f"prospective_{side}_contribution"] += float(shadow_active)
    state["runtime"] = runtime
    forward.atomic_write_json(SHADOW_STATE, state)
    verify_shadow_state(state)
    return {
        "status": "PASS_APPENDED_ONE_POST_REGISTRATION_SESSION",
        "session_date": checked["session"],
        "forward_session_count": runtime["forward_session_count"],
        "ledger_mutated": True,
    }


def status_payload() -> dict[str, Any]:
    state = load_shadow_state()
    chain = verify_shadow_state(state)
    return {
        "status": "PASS",
        "arm_id": ARM_ID,
        "registration_timestamp_utc": state["registration"]["registration_timestamp_utc"],
        "first_eligible_shadow_session": state["registration"]["first_eligible_shadow_session"],
        "forward_session_count": state["runtime"]["forward_session_count"],
        "hash_chain": chain,
    }


def temporary_remain_count() -> int:
    count = int((EXTENSION_ROOT / ".self_test").exists())
    try:
        count += sum(1 for path in CACHE_ROOT.glob("a2_attenuation_shadow_*") if path.exists())
    except OSError:
        count += 1
    return count


def terminal_summary(state: Mapping[str, Any]) -> str:
    registration = state["registration"]
    runtime = state["runtime"]
    next_action = (
        "AWAIT_FIRST_ELIGIBLE_PROSPECTIVE_SESSION"
        if int(runtime["forward_session_count"]) == 0
        else "CONTINUE_APPEND_ONLY_EVIDENCE_ACCUMULATION"
    )
    temp_remains = temporary_remain_count()
    anti_bloat = (
        "PASS_MINIMAL_EXTERNAL_ARM_EXTENSION"
        if temp_remains == 0
        else "PASS_WITH_UNWRITABLE_EXTERNAL_TEMP_CLEANUP_WARNING"
    )
    return "\n".join([
        "=" * 60,
        "A2_RAW_SCORE_ATTENUATION_PROSPECTIVE_SHADOW_R1_FINAL",
        "=" * 60,
        "",
        "RESEARCH_STATUS=INITIALIZED_RESEARCH_ONLY_NO_BACKFILL_PROSPECTIVE_SHADOW",
        "EXECUTION_STATUS=PASS",
        f"ANTI_BLOAT_STATUS={anti_bloat}",
        "",
        "EXISTING_FORWARD_INFRASTRUCTURE_REUSED=true",
        "NEW_FORWARD_FRAMEWORK_CREATED=false",
        "EXISTING_FROZEN_CONTRACT_MODIFIED=false",
        "EXISTING_ARM0_ARM3_HISTORY_MODIFIED=false",
        "",
        f"SHADOW_ARM_ID={ARM_ID}",
        f"SHADOW_STATUS={SHADOW_STATUS}",
        "",
        f"SHADOW_REGISTRATION_TIMESTAMP={registration['registration_timestamp_utc']}",
        f"FIRST_ELIGIBLE_SHADOW_SESSION={registration['first_eligible_shadow_session']}",
        f"FORWARD_SESSION_COUNT={runtime['forward_session_count']}",
        "",
        "NO_BACKFILL=true",
        "HISTORICAL_SESSION_APPENDED=false",
        "POST_REGISTRATION_ONLY=true",
        "",
        "PROBABILITY_SPEC_FIXED=true",
        "LAMBDA_DEFINITION=clip(P_HAT/REFERENCE_BASE_RATE,0,1)",
        "LAMBDA_RANGE_ENFORCED=true",
        "",
        "A_COMPARATOR_REUSED=true",
        "A2_COMPARATOR_REUSED=true",
        "",
        "BROKER_ORDER_ALLOWED=false",
        "CANONICAL_PROMOTION=false",
        "",
        "SOURCE_MODIFICATION_COUNT=1",
        "NEW_RESULT_STATE_ARTIFACT_COUNT=2",
        f"TEMP_FILE_REMAINS={temp_remains}",
        "",
        "DUPLICATE_FORWARD_INFRASTRUCTURE_REQUIRED=false",
        "",
        f"NEXT_ACTION={next_action}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    daily_parser = subparsers.add_parser("daily")
    daily_parser.add_argument("--input", type=Path)
    subparsers.add_parser("status")
    args = parser.parse_args()
    if args.command == "initialize":
        state, _ = initialize()
        print(terminal_summary(state))
    elif args.command == "daily":
        print(canonical_text(daily(args.input)))
    else:
        print(canonical_text(status_payload()))


if __name__ == "__main__":
    main()
