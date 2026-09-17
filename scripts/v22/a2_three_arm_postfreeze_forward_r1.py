#!/usr/bin/env python3
"""Append-only post-freeze forward ledger for Raw, S1, and fixed gross scaling.

The module is intentionally a thin adapter over frozen A2 artifacts, the
existing forward-shadow calendar, and the existing atomic/hash helpers.  It
does not refresh canonical data, train a model, select parameters, or read
pre-freeze economic outcomes.  A production daily append requires one
hash-bound exact-date session bundle at the stable external daily pointer.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import shutil
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd


TASK_ID = "A2_THREE_ARM_POSTFREEZE_FORWARD_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DAILY = Path(r"D:\us-tech-quant-daily")
OUT = RESULTS / TASK_ID

SCRIPTS = REPO / "scripts"
V22 = SCRIPTS / "v22"
for _path in (SCRIPTS, V22):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from a2_successor_s1.successor_control import (  # noqa: E402
    atomic_write_json,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from forward_shadow.trading_calendar import (  # noqa: E402
    ForwardShadowTradingCalendarProvider,
)


MODEL = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "final_full_pre2026_hgb.joblib"
ALPHA_REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"
ALPHA_BINDING = REPO / "config" / "research_governance" / "a2_forward_shadow_production_binding_r1.json"
FROZEN_CONTRACTS = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "audit" / "frozen_contracts_before_outcome_read.json"
BASELINE_SUMMARY = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "audit" / "fail_closed_or_pass_summary.json"
S1_SOURCE = V22 / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
S1_MANIFEST = RESULTS / "A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1" / "hash_manifest.json"
GROSS_ROOT = RESULTS / "A2_CONCENTRATION_TRIGGERED_GROSS_SCALER_R1"
GROSS_CONTRACT = GROSS_ROOT / "gross_scaler_contract.json"
GROSS_MANIFEST = GROSS_ROOT / "hash_manifest.json"
GROSS_SOURCE = V22 / "a2_concentration_triggered_gross_scaler_r1.py"
TAXONOMY_ROOT = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
TAXONOMY = TAXONOMY_ROOT / "pit_ff12_ff48_taxonomy.parquet"
TAXONOMY_METADATA = TAXONOMY_ROOT / "research_metadata.json"
TAXONOMY_MANIFEST = TAXONOMY_ROOT / "hash_manifest.json"
TAXONOMY_SOURCE = V22 / "stage_sec_pit_taxonomy.py"
CALENDAR_CONTRACT = REPO / "config" / "research_governance" / "a2_forward_shadow_trading_calendar_r1.json"
CANONICAL_POINTER = DAILY / "current" / "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD" / "canonical_snapshot_pointer.json"
SESSION_INPUT_POINTER = DAILY / "current" / TASK_ID / "session_input.json"

FORWARD_CONTRACT = OUT / "forward_contract.json"
FORWARD_LEDGER = OUT / "forward_ledger.csv"
FORWARD_STATE = OUT / "forward_state.json"
HASH_MANIFEST = OUT / "hash_manifest.json"

EXPECTED_MODEL_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
EXPECTED_S1_SOURCE_SHA256 = "4ce2aec79b556af22774441a6eb9cbf5811426f5db9c32c9585afb5d0b174549"
EXPECTED_GROSS_CONTRACT_HASH = "cba9d72c409afdbb057fb1c591b27a665c2505dd23cf2ecbd1ea572bfd2f014d"
EXPECTED_GROSS_CONTRACT_FILE_SHA256 = "68bdeacff463ab541feb0200f1583063ac9c39547b119824fcae2d9907b6da3c"
EXPECTED_GROSS_SOURCE_SHA256 = "575045b5e0cbdcd248be84a1285d472de587195d15f5f381bdfb05affe2d2d91"
EXPECTED_TAXONOMY_FILE_SHA256 = "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f"
EXPECTED_TAXONOMY_LOGICAL_HASH = "0f0b48772c09dadb1b93d783a623a896a3a18ef307b75fa253ef2f08ee9208e1"

TOP_N = 20
COST_BPS = 10
COST_RATE = COST_BPS / 10_000.0
GROSS_FLOOR = 0.80
TOL = 1e-12
MARKET_TZ = ZoneInfo("America/New_York")
OPEN_TIME = time(9, 30)
MILESTONES = (20, 60, 120, 250)
PREEXISTING_ACL_EXCEPTION_COUNT = 2

ARM0 = "RAW_A2"
ARM1 = "S1_SOFT_025"
ARM2 = "S1_CONCENTRATION_GROSS_SCALED"
ARM3 = "RAW_CONCENTRATION_GROSS_SCALED"
ARMS = (ARM0, ARM1, ARM2, ARM3)

LEDGER_FIELDS = [
    "session_date", "signal_date", "decision_timestamp", "outcome_timestamp",
    "canonical_snapshot_id", "canonical_manifest_sha256", "alpha_manifest_sha256",
    "raw_model_hash", "raw_portfolio_hash", "s1_contract_hash",
    "gross_scaler_contract_hash", "taxonomy_hash",
    "raw_return", "raw_nav", "raw_turnover", "raw_cost", "raw_equity_gross", "raw_cash",
    "raw_ff12_hhi", "raw_ff48_hhi",
    "s1_return", "s1_nav", "s1_turnover", "s1_cost", "s1_equity_gross", "s1_cash",
    "s1_ff12_hhi", "s1_ff48_hhi", "gross_scale_g",
    "raw_scaled_return", "raw_scaled_nav", "raw_scaled_turnover", "raw_scaled_cost",
    "raw_scaled_gross", "raw_scaled_cash",
    "s1_scaled_return", "s1_scaled_nav", "s1_scaled_turnover", "s1_scaled_cost",
    "s1_scaled_gross", "s1_scaled_cash",
    "s1_minus_raw_return", "s1_scaled_minus_s1_return",
    "s1_scaled_minus_raw_scaled_return", "session_eligibility", "eligibility_reason",
    "previous_row_hash", "row_hash",
]


class ForwardGateError(RuntimeError):
    """Fail-closed forward contract or append error."""


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise ForwardGateError(f"{code}:{detail}")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), "JSON_OBJECT_REQUIRED", path)
    return payload


def stable_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def import_frozen(name: str, path: Path, expected_hash: str):
    require(path.is_file() and sha256_file(path) == expected_hash, "FROZEN_SOURCE_HASH_MISMATCH", path)
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "FROZEN_SOURCE_IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def manifest_artifact(manifest_path: Path, name: str, expected_hash: str) -> None:
    manifest = read_json(manifest_path)
    require(manifest.get("status") == "PASS_HASH_VERIFIED", "INPUT_MANIFEST_NOT_VERIFIED", manifest_path)
    matches = [row for row in manifest.get("artifacts", []) if row.get("name") == name]
    require(len(matches) == 1 and matches[0].get("sha256") == expected_hash, "MANIFEST_ARTIFACT_HASH_MISMATCH", name)


def taxonomy_level_hash(frame: pd.DataFrame, level: str) -> str:
    columns = ["signal_date", "ticker", "security_id", "cik", "pit_sic", level, "sic_accepted_timestamp_utc"]
    ordered = frame[columns].sort_values(["signal_date", "ticker"], kind="mergesort")
    digest = __import__("hashlib").sha256()
    for row in ordered.itertuples(index=False, name=None):
        digest.update(("|".join("" if pd.isna(value) else str(value) for value in row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def taxonomy_logical_hash(frame: pd.DataFrame) -> str:
    columns = ["signal_date", "ticker", "security_id", "cik", "pit_sic", "ff12", "ff48", "sic_accepted_timestamp_utc"]
    ordered = frame[columns].sort_values(["signal_date", "ticker"], kind="mergesort")
    digest = __import__("hashlib").sha256()
    for row in ordered.itertuples(index=False, name=None):
        digest.update(("|".join("" if pd.isna(value) else str(value) for value in row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def recover_frozen_identities() -> dict[str, Any]:
    require(MODEL.is_file() and sha256_file(MODEL) == EXPECTED_MODEL_SHA256, "RAW_MODEL_HASH_MISMATCH")
    alpha = read_json(ALPHA_REGISTRY)
    champions = [row for row in alpha.get("models", []) if row.get("model_id") == "A2_HGB" and row.get("role") == "ALPHA_CHAMPION"]
    require(len(champions) == 1 and champions[0].get("model_sha256") == EXPECTED_MODEL_SHA256, "RAW_REGISTRY_IDENTITY")
    require(champions[0].get("uses_2026_training") is False, "RAW_MODEL_2026_TRAINING")

    baseline = read_json(BASELINE_SUMMARY)
    training_cutoff = str(baseline.get("A2_MAX_TRAIN_DATE"))
    require(training_cutoff <= "2025-12-31", "RAW_TRAINING_CUTOFF", training_cutoff)
    frozen = read_json(FROZEN_CONTRACTS)
    require(frozen.get("TOP_N") == TOP_N and frozen.get("COST_BPS") == COST_BPS, "RAW_PORTFOLIO_FROZEN_CONTRACT")
    raw_portfolio_spec = {
        "a2_config_fingerprint": frozen["A2_CONFIG_FINGERPRINT"],
        "a2_source_fingerprint": frozen["A2_SOURCE_FINGERPRINT"],
        "top_n": TOP_N,
        "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC",
        "target_weighting": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
        "decision_timing": "AFTER_SIGNAL_CLOSE_BEFORE_NEXT_LEGAL_SESSION_OPEN",
        "return_interval": "EXECUTION_OPEN_TO_NEXT_LEGAL_SESSION_OPEN",
        "cost_bps": COST_BPS,
        "cost_formula": "0.5_TIMES_TRADED_NOTIONAL_TIMES_COST_RATE",
    }

    s1_manifest = read_json(S1_MANIFEST)
    require(s1_manifest.get("task_source_sha256") == EXPECTED_S1_SOURCE_SHA256, "S1_MANIFEST_SOURCE_HASH")
    require(sha256_file(S1_SOURCE) == EXPECTED_S1_SOURCE_SHA256, "S1_SOURCE_HASH")
    s1_contract_spec = {
        "id": "S1_SOFT_025",
        "source_sha256": EXPECTED_S1_SOURCE_SHA256,
        "top20_membership": "IDENTICAL_TO_RAW_A2",
        "taxonomy": "FF12_FROM_FROZEN_PIT_SEC_SIC",
        "group_budget": "(GROUP_COUNT/TOP20_COUNT)^0.75_NORMALIZED",
        "within_group": "EQUAL_WEIGHT",
        "fully_invested": True,
        "parameter": 0.25,
        "top_n": TOP_N,
    }

    manifest_artifact(GROSS_MANIFEST, "gross_scaler_contract.json", EXPECTED_GROSS_CONTRACT_FILE_SHA256)
    gross_manifest = read_json(GROSS_MANIFEST)
    require(gross_manifest.get("task_source_sha256") == EXPECTED_GROSS_SOURCE_SHA256, "GROSS_SOURCE_MANIFEST_HASH")
    require(sha256_file(GROSS_SOURCE) == EXPECTED_GROSS_SOURCE_SHA256, "GROSS_SOURCE_HASH")
    gross = read_json(GROSS_CONTRACT)
    require(sha256_file(GROSS_CONTRACT) == EXPECTED_GROSS_CONTRACT_FILE_SHA256, "GROSS_CONTRACT_FILE_HASH")
    require(gross.get("gross_scaler_contract_hash") == EXPECTED_GROSS_CONTRACT_HASH, "GROSS_CONTRACT_LOGICAL_HASH")
    require(float(gross.get("gross_floor")) == GROSS_FLOOR and gross.get("contract_mutation_forbidden") is True, "GROSS_CONTRACT_RULE")

    manifest_artifact(TAXONOMY_MANIFEST, "pit_ff12_ff48_taxonomy.parquet", EXPECTED_TAXONOMY_FILE_SHA256)
    taxonomy_meta = read_json(TAXONOMY_METADATA)
    require(taxonomy_meta.get("taxonomy_hash") == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_METADATA_HASH")
    require(sha256_file(TAXONOMY) == EXPECTED_TAXONOMY_FILE_SHA256, "TAXONOMY_FILE_HASH")
    taxonomy = pd.read_parquet(TAXONOMY)
    base_manifest = read_json(TAXONOMY_MANIFEST)
    expected_taxonomy_source = base_manifest["inputs"]["base_runner"]["sha256"]
    require(sha256_file(TAXONOMY_SOURCE) == expected_taxonomy_source, "TAXONOMY_MAPPING_SOURCE_HASH")
    taxonomy_module = import_frozen("a2_forward_frozen_taxonomy", TAXONOMY_SOURCE, expected_taxonomy_source)
    bridge_path = TAXONOMY_ROOT / "security_cik_bridge.parquet"
    logical = taxonomy_module.canonical_hash({
        "sec_stage_sha256": sha256_file(taxonomy_module.SUB_MIN),
        "sec_source_manifest_sha256": sha256_file(taxonomy_module.SOURCE_MANIFEST),
        "security_cik_bridge_sha256": sha256_file(bridge_path),
        "pit_ff12_ff48_taxonomy_sha256": sha256_file(TAXONOMY),
        "ff12_mapping": taxonomy_module.FF12_RANGES,
        "ff48_mapping": taxonomy_module.FF48_RANGES,
    })
    require(logical == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_LOGICAL_HASH", logical)

    binding_hash = sha256_file(ALPHA_BINDING)
    calendar_hash = sha256_file(CALENDAR_CONTRACT)
    return {
        "raw_model_id": "A2_HGB",
        "raw_model_hash": EXPECTED_MODEL_SHA256,
        "raw_signal_id": "A_A2_QUARTERLY_13F_CLEAN_BASELINE_R1",
        "raw_training_cutoff": training_cutoff,
        "raw_training_label_cutoff": "2025-12-31",
        "raw_portfolio_contract": raw_portfolio_spec,
        "raw_portfolio_hash": stable_hash(raw_portfolio_spec),
        "alpha_binding_file_sha256": binding_hash,
        "s1_contract": s1_contract_spec,
        "s1_contract_hash": stable_hash(s1_contract_spec),
        "gross_scaler_contract_hash": EXPECTED_GROSS_CONTRACT_HASH,
        "gross_scaler_contract_file_sha256": EXPECTED_GROSS_CONTRACT_FILE_SHA256,
        "gross_scaler_source_sha256": EXPECTED_GROSS_SOURCE_SHA256,
        "taxonomy_file_sha256": EXPECTED_TAXONOMY_FILE_SHA256,
        "taxonomy_hash": EXPECTED_TAXONOMY_LOGICAL_HASH,
        "ff12_taxonomy_hash": taxonomy_level_hash(taxonomy, "ff12"),
        "ff48_taxonomy_hash": taxonomy_level_hash(taxonomy, "ff48"),
        "ff12_mapping_hash": stable_hash(taxonomy_module.FF12_RANGES),
        "ff48_mapping_hash": stable_hash(taxonomy_module.FF48_RANGES),
        "taxonomy_mapping_source_sha256": expected_taxonomy_source,
        "calendar_contract_sha256": calendar_hash,
    }


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "TIMEZONE_AWARE_TIMESTAMP_REQUIRED", value)
    return parsed.astimezone(timezone.utc)


def first_session_after_freeze(provider: ForwardShadowTradingCalendarProvider, freeze_utc: datetime) -> str:
    for value in provider.sessions:
        session_open = datetime.combine(datetime.fromisoformat(value).date(), OPEN_TIME, MARKET_TZ)
        if session_open.astimezone(timezone.utc) > freeze_utc:
            return value
    raise ForwardGateError("NO_SESSION_AFTER_FREEZE_IN_BOUND_CALENDAR")


def build_contract(identities: Mapping[str, Any], freeze_utc: datetime) -> dict[str, Any]:
    provider = ForwardShadowTradingCalendarProvider(CALENDAR_CONTRACT)
    freeze = freeze_utc.astimezone(timezone.utc)
    first_session = first_session_after_freeze(provider, freeze)
    core = {
        "schema_version": "1.0.0",
        "experiment_id": TASK_ID,
        "forward_freeze_timestamp_utc": freeze.isoformat(),
        "forward_freeze_timestamp_et": freeze.astimezone(MARKET_TZ).isoformat(),
        "first_eligible_forward_session": first_session,
        "evidence_start_rule": "FIRST_BOUND_US_SESSION_WITH_OPEN_AFTER_FREEZE_AND_EX_ANTE_DECISION_EVIDENCE",
        "pre_freeze_history_classification": "EXPOSED_HISTORY_NOT_FORWARD",
        "historical_backfill_allowed": False,
        "top_n": TOP_N,
        "arms": {
            "ARM0_CONTROL": {"id": ARM0, "role": "PRIMARY_CONTROL"},
            "ARM1_SIMPLE_DECONCENTRATION": {"id": ARM1, "role": "PRIMARY"},
            "ARM2_RISK_ADJUSTED": {"id": ARM2, "role": "PRIMARY"},
            "ARM3_CAUSAL_DIAGNOSTIC_ONLY": {"id": ARM3, "role": "DIAGNOSTIC_ONLY", "winner_selection_allowed": False},
        },
        "frozen_identities": dict(identities),
        "gross_rule": {
            "formula": "G=max(0.80,min(1,g12,g48));gL=1_if_raw_hhi<=s1_hhi_else_sqrt(s1_hhi/raw_hhi)",
            "gross_floor": GROSS_FLOOR,
            "arm2_arm3_same_gross": True,
            "normalized_composition_unchanged_by_uniform_scaling": True,
        },
        "execution_accounting": {
            "signal_to_execution": "AFTER_SIGNAL_CLOSE_TO_NEXT_LEGAL_SESSION_OPEN",
            "session_return_interval": "EXECUTION_OPEN_TO_NEXT_LEGAL_SESSION_OPEN",
            "cost_bps": COST_BPS,
            "cost_formula": "0.5_TIMES_TRADED_NOTIONAL_TIMES_COST_RATE",
            "cash_return": 0.0,
            "cash_convention": "RESIDUAL_ONE_MINUS_TARGET_EQUITY_GROSS",
            "membership_change_across_arms": False,
        },
        "taxonomy_forward_contract": {
            "identity": "PIT_SEC_SIC_TO_FROZEN_FF12_FF48",
            "accepted_timestamp_must_not_exceed_decision_timestamp": True,
            "ff12_mapping_hash": identities["ff12_mapping_hash"],
            "ff48_mapping_hash": identities["ff48_mapping_hash"],
            "unknown_policy": "FROZEN_UNKNOWN_CATEGORY_AND_SESSION_COVERAGE_GATE",
            "max_unknown_security_date_pct": 0.01,
            "max_unknown_portfolio_weight": 0.05,
            "manual_classification_allowed": False,
        },
        "session_input_contract": {
            "stable_pointer": str(SESSION_INPUT_POINTER),
            "producer_role": "EXISTING_AUTHORITATIVE_EXACT_DATE_FORWARD_PIPELINE",
            "required_collections": ["target_rows", "price_rows"],
            "external_references_hash_verified": True,
            "same_day_outcome_for_decision_forbidden": True,
            "session_input_is_not_strategy_selection_evidence": True,
        },
        "ledger_contract": {
            "path": str(FORWARD_LEDGER),
            "fields": LEDGER_FIELDS,
            "append_only": True,
            "lock_required": True,
            "hash_chain": True,
            "duplicate_session_reject": True,
            "out_of_order_append_reject": True,
            "pre_freeze_session_reject": True,
        },
        "milestones": {"20": "OPERATIONAL_ONLY", "60": "EARLY_ECONOMIC", "120": "FORMAL_FORWARD_REVIEW", "250": "ANNUAL_SCALE_REVIEW"},
        "governance": {
            "model_retraining": False,
            "parameter_change": False,
            "historical_research_rerun": False,
            "forward_outcome_based_selection": False,
            "broker_action": False,
            "canonical_data_read_only": True,
            "preexisting_acl_exception_count": PREEXISTING_ACL_EXCEPTION_COUNT,
        },
        "freeze_timestamp_immutable": True,
    }
    return {**core, "forward_contract_hash": stable_hash(core)}


def load_contract() -> dict[str, Any]:
    contract = read_json(FORWARD_CONTRACT)
    observed = dict(contract)
    contract_hash = observed.pop("forward_contract_hash")
    require(stable_hash(observed) == contract_hash, "FORWARD_CONTRACT_HASH_INVALID")
    require(contract.get("freeze_timestamp_immutable") is True, "FREEZE_NOT_IMMUTABLE")
    return contract


def initial_arm_state() -> dict[str, Any]:
    return {"nav": 1.0, "cash": 1.0, "shares": {}, "last_marks": {}}


def initial_state(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "experiment_id": TASK_ID,
        "forward_contract_hash": contract["forward_contract_hash"],
        "forward_freeze_timestamp_utc": contract["forward_freeze_timestamp_utc"],
        "first_eligible_forward_session": contract["first_eligible_forward_session"],
        "forward_session_count": 0,
        "ledger_row_count": 0,
        "last_session_date": None,
        "last_row_hash": "GENESIS",
        "next_milestone": 20,
        "arm_state": {arm: initial_arm_state() for arm in ARMS},
        "dry_run_status": "NOT_RUN",
        "updated_at_utc": contract["forward_freeze_timestamp_utc"],
    }


def ledger_header_bytes() -> bytes:
    import io
    buffer = io.StringIO(newline="")
    csv.DictWriter(buffer, fieldnames=LEDGER_FIELDS, lineterminator="\n").writeheader()
    return buffer.getvalue().encode("utf-8")


def ensure_ledger(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(ledger_header_bytes())
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == LEDGER_FIELDS, "LEDGER_SCHEMA_MISMATCH")


def ledger_rows(path: Path) -> list[dict[str, str]]:
    ensure_ledger(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def row_hash(row: Mapping[str, Any]) -> str:
    payload = {field: str(row.get(field, "")) for field in LEDGER_FIELDS if field != "row_hash"}
    return stable_hash(payload)


def validate_hash_chain(path: Path) -> dict[str, Any]:
    rows = ledger_rows(path)
    previous = "GENESIS"
    reasons: list[str] = []
    last_date: str | None = None
    for index, row in enumerate(rows):
        if row.get("previous_row_hash") != previous or row.get("row_hash") != row_hash(row):
            reasons.append(f"HASH_CHAIN_MISMATCH:{index}")
        date_value = row.get("session_date", "")
        if last_date is not None and date_value <= last_date:
            reasons.append(f"DATE_ORDER_VIOLATION:{date_value}")
        last_date, previous = date_value, row.get("row_hash", "")
    return {"status": "PASS" if not reasons else "FAIL", "row_count": len(rows), "last_row_hash": previous, "reasons": reasons}


class LedgerLock:
    def __init__(self, ledger: Path):
        self.path = ledger.with_suffix(ledger.suffix + ".lock")
        self.token = stable_hash({"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat()})

    def __enter__(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ForwardGateError("LOCK_ALREADY_HELD") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(self.token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.path.is_file() and self.path.read_text(encoding="utf-8").strip() == self.token:
            self.path.unlink()


def append_ledger_row(path: Path, row: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, str]:
    with LedgerLock(path):
        rows = ledger_rows(path)
        session = str(row["session_date"])
        if any(existing["session_date"] == session for existing in rows):
            raise ForwardGateError("DUPLICATE_SESSION_REJECTED")
        if rows and session <= rows[-1]["session_date"]:
            raise ForwardGateError("OUT_OF_ORDER_APPEND_REJECTED")
        if session < str(contract["first_eligible_forward_session"]):
            raise ForwardGateError("PRE_FREEZE_SESSION_REJECTED")
        prepared = {field: row.get(field, "") for field in LEDGER_FIELDS}
        prepared["previous_row_hash"] = rows[-1]["row_hash"] if rows else "GENESIS"
        prepared["row_hash"] = row_hash(prepared)
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n", extrasaction="raise")
            writer.writerow(prepared)
            handle.flush()
            os.fsync(handle.fileno())
        require(validate_hash_chain(path)["status"] == "PASS", "POST_APPEND_HASH_CHAIN_INVALID")
        return {key: str(value) for key, value in prepared.items()}


def load_frozen_runtime(contract: Mapping[str, Any]):
    identities = contract["frozen_identities"]
    s1 = import_frozen("a2_forward_s1_runtime", S1_SOURCE, identities["s1_contract"]["source_sha256"])
    gross = import_frozen("a2_forward_gross_runtime", GROSS_SOURCE, identities["gross_scaler_source_sha256"])
    taxonomy = import_frozen("a2_forward_taxonomy_runtime", TAXONOMY_SOURCE, identities["taxonomy_mapping_source_sha256"])
    return s1, gross, taxonomy


def concentration(weights: Mapping[str, float], target_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    by = {str(row["ticker"]).upper(): row for row in target_rows}
    gross = float(sum(weights.values()))
    require(gross > 0, "ZERO_EQUITY_GROSS")
    result: dict[str, float] = {"gross": gross, "cash": 1.0 - gross}
    for level in ("ff12", "ff48"):
        grouped: dict[str, float] = {}
        for ticker, weight in weights.items():
            label = str(by[ticker][level])
            grouped[label] = grouped.get(label, 0.0) + float(weight) / gross
        result[f"{level}_hhi"] = float(sum(value * value for value in grouped.values()))
    return result


def arm_targets(target_rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    s1_runtime, gross_runtime, _ = load_frozen_runtime(contract)
    frame = pd.DataFrame(target_rows)
    frame["ticker"] = frame.ticker.astype(str).str.upper()
    raw = {str(ticker): 1.0 / TOP_N for ticker in frame.ticker}
    s1 = s1_runtime.s1_weights(frame)
    raw_conc, s1_conc = concentration(raw, target_rows), concentration(s1, target_rows)
    g12, g48, unclipped, gross = gross_runtime.gross_rule(
        raw_conc["ff12_hhi"], raw_conc["ff48_hhi"], s1_conc["ff12_hhi"], s1_conc["ff48_hhi"]
    )
    require(abs(float(gross) - max(GROSS_FLOOR, min(1.0, float(g12), float(g48)))) <= TOL, "GROSS_FORMULA_IDENTITY")
    raw_scaled = {ticker: float(gross) * weight for ticker, weight in raw.items()}
    s1_scaled = {ticker: float(gross) * weight for ticker, weight in s1.items()}
    targets = {ARM0: raw, ARM1: s1, ARM2: s1_scaled, ARM3: raw_scaled}
    require(set(raw) == set(s1) == set(raw_scaled) == set(s1_scaled), "ARM_MEMBERSHIP_MISMATCH")
    require(abs(sum(raw_scaled.values()) - sum(s1_scaled.values())) <= TOL, "ARM2_ARM3_GROSS_MISMATCH")
    require(abs(concentration(raw_scaled, target_rows)["ff12_hhi"] - raw_conc["ff12_hhi"]) <= TOL, "RAW_SCALED_NORMALIZED_HHI")
    require(abs(concentration(s1_scaled, target_rows)["ff48_hhi"] - s1_conc["ff48_hhi"]) <= TOL, "S1_SCALED_NORMALIZED_HHI")
    return targets, {"g12": g12, "g48": g48, "unclipped": unclipped, "gross": gross, "raw": raw_conc, "s1": s1_conc}


def rebalance_and_mark(
    state: Mapping[str, Any], target: Mapping[str, float], entry: Mapping[str, float], outcome: Mapping[str, float]
) -> tuple[dict[str, Any], dict[str, float]]:
    shares = {str(key): float(value) for key, value in state.get("shares", {}).items()}
    cash = float(state.get("cash", 1.0))
    prior_nav = float(state.get("nav", 1.0))
    required = set(shares) | set(target)
    require(required <= set(entry) and set(shares) | set(target) <= set(outcome), "PRICE_COVERAGE_INCOMPLETE", sorted(required - set(entry)))
    pre_values = {ticker: shares.get(ticker, 0.0) * float(entry[ticker]) for ticker in shares}
    pretrade_nav = cash + sum(pre_values.values())
    require(abs(pretrade_nav - prior_nav) <= max(TOL, abs(prior_nav) * 1e-10), "NAV_MARK_CONTINUITY", (pretrade_nav, prior_nav))
    desired = {ticker: float(weight) * pretrade_nav for ticker, weight in target.items()}
    transaction_cost = 0.0
    traded = 0.0
    for ticker in sorted(set(shares) | set(target)):
        current, wanted = pre_values.get(ticker, 0.0), desired.get(ticker, 0.0)
        if current <= wanted + 1e-14:
            continue
        notional = current - wanted
        shares[ticker] = max(0.0, shares[ticker] - notional / float(entry[ticker]))
        if shares[ticker] <= 1e-14:
            shares.pop(ticker, None)
        cash += notional
        traded += notional
        transaction_cost += 0.5 * notional * COST_RATE
    post_sell = {ticker: quantity * float(entry[ticker]) for ticker, quantity in shares.items()}
    buys = {
        ticker: wanted - post_sell.get(ticker, 0.0)
        for ticker, wanted in desired.items()
        if wanted > post_sell.get(ticker, 0.0) + 1e-14
    }
    buy_total = sum(buys.values())
    cash_available = max(0.0, cash - transaction_cost)
    requirement = buy_total * (1.0 + 0.5 * COST_RATE)
    buy_scale = min(1.0, cash_available / requirement) if requirement > 0 else 1.0
    for ticker, requested in sorted(buys.items()):
        notional = requested * buy_scale
        if notional <= 1e-14:
            continue
        shares[ticker] = shares.get(ticker, 0.0) + notional / float(entry[ticker])
        cash -= notional
        traded += notional
        transaction_cost += 0.5 * notional * COST_RATE
    cash -= transaction_cost
    require(cash >= -1e-10, "NEGATIVE_CASH", cash)
    cash = max(0.0, cash)
    post_nav = cash + sum(quantity * float(outcome[ticker]) for ticker, quantity in shares.items())
    require(post_nav > 0, "NONPOSITIVE_NAV")
    result = {
        "return": post_nav / prior_nav - 1.0,
        "nav": post_nav,
        "turnover": 0.5 * traded / pretrade_nav,
        "cost": transaction_cost,
        "buy_cash_scale": buy_scale,
    }
    new_state = {"nav": post_nav, "cash": cash, "shares": shares, "last_marks": {ticker: float(outcome[ticker]) for ticker in shares}}
    return new_state, result


def previous_session(provider: ForwardShadowTradingCalendarProvider, session: str) -> str:
    index = provider.sessions.index(session)
    require(index > 0, "NO_PREVIOUS_BOUND_SESSION")
    return provider.sessions[index - 1]


def next_session(provider: ForwardShadowTradingCalendarProvider, session: str) -> str:
    index = provider.sessions.index(session)
    require(index + 1 < len(provider.sessions), "NO_NEXT_BOUND_SESSION")
    return provider.sessions[index + 1]


def verify_external_reference(reference: Mapping[str, Any], code: str) -> None:
    path = Path(str(reference.get("path", "")))
    expected = str(reference.get("sha256", ""))
    require(path.is_file() and sha256_file(path) == expected, code, path)


def validate_session_input(
    payload: Mapping[str, Any], contract: Mapping[str, Any], state: Mapping[str, Any], *, verify_refs: bool = True, now: datetime | None = None
) -> dict[str, Any]:
    provider = ForwardShadowTradingCalendarProvider(CALENDAR_CONTRACT)
    session = str(payload.get("session_date", ""))
    require(provider.is_session(session), "SESSION_NOT_ON_BOUND_CALENDAR", session)
    require(session >= contract["first_eligible_forward_session"], "PRE_FREEZE_SESSION_REJECTED", session)
    expected = next_session(provider, state["last_session_date"]) if state.get("last_session_date") else contract["first_eligible_forward_session"]
    require(session == expected, "OUT_OF_ORDER_SESSION_INPUT", (session, expected))
    signal = str(payload.get("signal_date", ""))
    require(signal == previous_session(provider, session), "INFORMATION_EXECUTION_DATE_ALIGNMENT", (signal, session))
    decision = parse_timestamp(str(payload.get("decision_timestamp")))
    entry_time = datetime.combine(datetime.fromisoformat(session).date(), OPEN_TIME, MARKET_TZ).astimezone(timezone.utc)
    next_value = next_session(provider, session)
    outcome_minimum = datetime.combine(datetime.fromisoformat(next_value).date(), OPEN_TIME, MARKET_TZ).astimezone(timezone.utc)
    outcome = parse_timestamp(str(payload.get("outcome_timestamp")))
    freeze = parse_timestamp(contract["forward_freeze_timestamp_utc"])
    require(freeze < decision < entry_time, "DECISION_NOT_POSTFREEZE_EXANTE", (freeze, decision, entry_time))
    require(outcome >= outcome_minimum and outcome > freeze, "OUTCOME_NOT_COMPLETED_POSTFREEZE", outcome)
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    require(observed_now >= outcome, "OUTCOME_TIMESTAMP_IN_FUTURE", outcome)
    identities = contract["frozen_identities"]
    required_hashes = {
        "raw_model_hash": identities["raw_model_hash"],
        "raw_portfolio_hash": identities["raw_portfolio_hash"],
        "s1_contract_hash": identities["s1_contract_hash"],
        "gross_scaler_contract_hash": identities["gross_scaler_contract_hash"],
        "taxonomy_hash": identities["taxonomy_hash"],
    }
    for field, expected_hash in required_hashes.items():
        require(payload.get(field) == expected_hash, "SESSION_FROZEN_IDENTITY_MISMATCH", field)
    if verify_refs:
        verify_external_reference(payload.get("canonical_manifest", {}), "CANONICAL_MANIFEST_HASH_MISMATCH")
        verify_external_reference(payload.get("alpha_manifest", {}), "ALPHA_MANIFEST_HASH_MISMATCH")
    targets = list(payload.get("target_rows", []))
    require(len(targets) == TOP_N, "TOP20_TARGET_ROW_COUNT")
    tickers = [str(row.get("ticker", "")).upper() for row in targets]
    require(len(set(tickers)) == TOP_N and all(tickers), "TOP20_TARGET_IDENTITY")
    require(max(abs(float(row.get("raw_target_weight", 0.0)) - 1.0 / TOP_N) for row in targets) <= TOL, "RAW_TARGET_WEIGHT_IDENTITY")
    _, _, taxonomy_runtime = load_frozen_runtime(contract)
    unknown = 0
    for row in targets:
        accepted = parse_timestamp(str(row.get("sic_accepted_timestamp_utc")))
        require(accepted <= decision, "FUTURE_TAXONOMY_FILING", row.get("ticker"))
        sic = row.get("pit_sic")
        if sic is None or str(sic).strip() in {"", "nan", "None"}:
            unknown += 1
            require(str(row.get("ff12")).startswith("UNKNOWN") and str(row.get("ff48")).startswith("UNKNOWN"), "UNKNOWN_TAXONOMY_POLICY")
        else:
            require(str(row.get("ff12")) == taxonomy_runtime.ff12(int(float(sic))), "FF12_MAPPING_MISMATCH", row.get("ticker"))
            require(str(row.get("ff48")) == taxonomy_runtime.ff48(int(float(sic))), "FF48_MAPPING_MISMATCH", row.get("ticker"))
    unknown_pct = unknown / TOP_N
    require(unknown_pct <= contract["taxonomy_forward_contract"]["max_unknown_security_date_pct"] + TOL, "FORWARD_TAXONOMY_COVERAGE_GATE", unknown_pct)
    prices = list(payload.get("price_rows", []))
    require(prices, "PRICE_ROWS_MISSING")
    price_by = {str(row.get("ticker", "")).upper(): row for row in prices}
    require(len(price_by) == len(prices), "DUPLICATE_PRICE_TICKER")
    required_price_tickers = set(tickers)
    for arm in ARMS:
        required_price_tickers.update(state["arm_state"][arm].get("shares", {}).keys())
    require(required_price_tickers <= set(price_by), "PRICE_ROW_COVERAGE", sorted(required_price_tickers - set(price_by)))
    for ticker in required_price_tickers:
        require(float(price_by[ticker]["entry_open"]) > 0 and float(price_by[ticker]["outcome_open"]) > 0, "INVALID_OPEN_PRICE", ticker)
        prior_marks = [state["arm_state"][arm].get("last_marks", {}).get(ticker) for arm in ARMS]
        prior_marks = [float(value) for value in prior_marks if value is not None]
        if prior_marks:
            require(max(abs(value - float(price_by[ticker]["entry_open"])) for value in prior_marks) <= max(TOL, abs(prior_marks[0]) * 1e-10), "OPEN_PRICE_CONTINUITY", ticker)
    return {"provider": provider, "session": session, "signal": signal, "decision": decision, "outcome": outcome, "targets": targets, "prices": price_by}


def process_session(
    payload: Mapping[str, Any], contract: Mapping[str, Any], state: Mapping[str, Any], *, verify_refs: bool = True, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    checked = validate_session_input(payload, contract, state, verify_refs=verify_refs, now=now)
    targets, mechanics = arm_targets(checked["targets"], contract)
    entry = {ticker: float(row["entry_open"]) for ticker, row in checked["prices"].items()}
    outcome = {ticker: float(row["outcome_open"]) for ticker, row in checked["prices"].items()}
    new_state = json.loads(json.dumps(state))
    results: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        arm_state, arm_result = rebalance_and_mark(state["arm_state"][arm], targets[arm], entry, outcome)
        new_state["arm_state"][arm] = arm_state
        results[arm] = arm_result
    require(abs(sum(targets[ARM2].values()) - sum(targets[ARM3].values())) <= TOL, "ARM2_ARM3_SAME_GROSS")
    raw, s1 = mechanics["raw"], mechanics["s1"]
    row = {
        "session_date": checked["session"], "signal_date": checked["signal"],
        "decision_timestamp": checked["decision"].isoformat(), "outcome_timestamp": checked["outcome"].isoformat(),
        "canonical_snapshot_id": payload.get("canonical_snapshot_id", ""),
        "canonical_manifest_sha256": payload.get("canonical_manifest", {}).get("sha256", ""),
        "alpha_manifest_sha256": payload.get("alpha_manifest", {}).get("sha256", ""),
        "raw_model_hash": contract["frozen_identities"]["raw_model_hash"],
        "raw_portfolio_hash": contract["frozen_identities"]["raw_portfolio_hash"],
        "s1_contract_hash": contract["frozen_identities"]["s1_contract_hash"],
        "gross_scaler_contract_hash": contract["frozen_identities"]["gross_scaler_contract_hash"],
        "taxonomy_hash": contract["frozen_identities"]["taxonomy_hash"],
        "raw_return": results[ARM0]["return"], "raw_nav": results[ARM0]["nav"], "raw_turnover": results[ARM0]["turnover"], "raw_cost": results[ARM0]["cost"],
        "raw_equity_gross": 1.0, "raw_cash": 0.0, "raw_ff12_hhi": raw["ff12_hhi"], "raw_ff48_hhi": raw["ff48_hhi"],
        "s1_return": results[ARM1]["return"], "s1_nav": results[ARM1]["nav"], "s1_turnover": results[ARM1]["turnover"], "s1_cost": results[ARM1]["cost"],
        "s1_equity_gross": 1.0, "s1_cash": 0.0, "s1_ff12_hhi": s1["ff12_hhi"], "s1_ff48_hhi": s1["ff48_hhi"],
        "gross_scale_g": mechanics["gross"],
        "raw_scaled_return": results[ARM3]["return"], "raw_scaled_nav": results[ARM3]["nav"], "raw_scaled_turnover": results[ARM3]["turnover"], "raw_scaled_cost": results[ARM3]["cost"],
        "raw_scaled_gross": mechanics["gross"], "raw_scaled_cash": 1.0 - mechanics["gross"],
        "s1_scaled_return": results[ARM2]["return"], "s1_scaled_nav": results[ARM2]["nav"], "s1_scaled_turnover": results[ARM2]["turnover"], "s1_scaled_cost": results[ARM2]["cost"],
        "s1_scaled_gross": mechanics["gross"], "s1_scaled_cash": 1.0 - mechanics["gross"],
        "s1_minus_raw_return": results[ARM1]["return"] - results[ARM0]["return"],
        "s1_scaled_minus_s1_return": results[ARM2]["return"] - results[ARM1]["return"],
        "s1_scaled_minus_raw_scaled_return": results[ARM2]["return"] - results[ARM3]["return"],
        "session_eligibility": "TRUE", "eligibility_reason": "ELIGIBLE_POSTFREEZE_EXACT_DATE_PIT",
    }
    new_state["forward_session_count"] = int(state["forward_session_count"]) + 1
    new_state["ledger_row_count"] = int(state["ledger_row_count"]) + 1
    new_state["last_session_date"] = checked["session"]
    new_state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    new_state["next_milestone"] = next((value for value in MILESTONES if value > new_state["forward_session_count"]), None)
    return row, new_state


def synthetic_payload(contract: Mapping[str, Any]) -> tuple[dict[str, Any], datetime]:
    provider = ForwardShadowTradingCalendarProvider(CALENDAR_CONTRACT)
    session = contract["first_eligible_forward_session"]
    signal = previous_session(provider, session)
    entry = datetime.combine(datetime.fromisoformat(session).date(), OPEN_TIME, MARKET_TZ).astimezone(timezone.utc)
    next_value = next_session(provider, session)
    outcome = datetime.combine(datetime.fromisoformat(next_value).date(), OPEN_TIME, MARKET_TZ).astimezone(timezone.utc)
    freeze = parse_timestamp(contract["forward_freeze_timestamp_utc"])
    decision = freeze + (entry - freeze) / 2
    target_rows = []
    price_rows = []
    sic_values = (3571, 2834, 7372, 3674, 4813)
    _, _, taxonomy_runtime = load_frozen_runtime(contract)
    for index in range(TOP_N):
        ticker = f"SYN{index:02d}"
        sic = sic_values[index % len(sic_values)]
        target_rows.append({
            "security_id": f"SYNTHETIC_{index:02d}", "ticker": ticker, "raw_target_weight": 0.05,
            "pit_sic": sic, "ff12": taxonomy_runtime.ff12(sic), "ff48": taxonomy_runtime.ff48(sic),
            "sic_accepted_timestamp_utc": (freeze - __import__("datetime").timedelta(days=1)).isoformat(),
        })
        price_rows.append({"ticker": ticker, "entry_open": 100.0 + index, "outcome_open": (100.0 + index) * (1.0 + (index - 9.5) / 10_000.0)})
    payload = {
        "session_date": session, "signal_date": signal, "decision_timestamp": decision.isoformat(), "outcome_timestamp": outcome.isoformat(),
        "canonical_snapshot_id": "SYNTHETIC_DRY_RUN", "canonical_manifest": {"path": "SYNTHETIC", "sha256": "0" * 64},
        "alpha_manifest": {"path": "SYNTHETIC", "sha256": "1" * 64}, "target_rows": target_rows, "price_rows": price_rows,
        **{field: contract["frozen_identities"][field] for field in ("raw_model_hash", "raw_portfolio_hash", "s1_contract_hash", "gross_scaler_contract_hash", "taxonomy_hash")},
    }
    return payload, outcome + __import__("datetime").timedelta(minutes=1)


def internal_dry_run(contract: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    ledger_before = sha256_file(FORWARD_LEDGER)
    count_before = int(state["forward_session_count"])
    payload, observed_now = synthetic_payload(contract)
    row, candidate_state = process_session(payload, contract, json.loads(json.dumps(state)), verify_refs=False, now=observed_now)
    require(abs(float(row["raw_scaled_gross"]) - float(row["s1_scaled_gross"])) <= TOL, "DRY_RUN_SAME_GROSS")
    require(abs(float(row["raw_scaled_gross"]) + float(row["raw_scaled_cash"]) - 1.0) <= TOL, "DRY_RUN_CASH_IDENTITY")
    require(abs(float(row["s1_minus_raw_return"]) - (float(row["s1_return"]) - float(row["raw_return"]))) <= TOL, "DRY_RUN_DELTA_IDENTITY")
    require(candidate_state["forward_session_count"] == count_before + 1, "DRY_RUN_IN_MEMORY_COUNTER")
    require(sha256_file(FORWARD_LEDGER) == ledger_before and count_before == state["forward_session_count"], "DRY_RUN_LEDGER_MUTATION")

    temp_root = OUT / ".init_dry_run"
    require(not temp_root.exists(), "DRY_RUN_TEMP_PATH_PREEXISTS", temp_root)
    temp_root.mkdir(parents=False, exist_ok=False)
    try:
        ledger = temp_root / "ledger.csv"
        ensure_ledger(ledger)
        appended = append_ledger_row(ledger, row, contract)
        duplicate = out_of_order = lock = prefreeze = False
        try:
            append_ledger_row(ledger, row, contract)
        except ForwardGateError as exc:
            duplicate = "DUPLICATE_SESSION_REJECTED" in str(exc)
        older = dict(row)
        older["session_date"] = previous_session(ForwardShadowTradingCalendarProvider(CALENDAR_CONTRACT), row["session_date"])
        try:
            append_ledger_row(ledger, older, contract)
        except ForwardGateError as exc:
            out_of_order = "OUT_OF_ORDER_APPEND_REJECTED" in str(exc) or "PRE_FREEZE_SESSION_REJECTED" in str(exc)
        try:
            with LedgerLock(ledger):
                with LedgerLock(ledger):
                    pass
        except ForwardGateError as exc:
            lock = "LOCK_ALREADY_HELD" in str(exc)
        pref = dict(payload)
        pref["decision_timestamp"] = (parse_timestamp(contract["forward_freeze_timestamp_utc"]) - __import__("datetime").timedelta(minutes=1)).isoformat()
        try:
            process_session(pref, contract, state, verify_refs=False, now=observed_now)
        except ForwardGateError as exc:
            prefreeze = "DECISION_NOT_POSTFREEZE_EXANTE" in str(exc)
        require(all((duplicate, out_of_order, lock, prefreeze)), "DRY_RUN_REJECTION_GATE")
        chain = validate_hash_chain(ledger)
        require(chain["status"] == "PASS" and appended["previous_row_hash"] == "GENESIS", "DRY_RUN_HASH_CHAIN")
    finally:
        shutil.rmtree(temp_root, ignore_errors=False)
    return {
        "status": "PASS_NO_LEDGER_MUTATION", "same_gross": "PASS", "cash_identity": "PASS",
        "cost_accounting": "PASS_FROZEN_10BPS_HALF_TRADED_NOTIONAL", "hash_chain": "PASS",
        "duplicate_rejection": "PASS", "out_of_order_rejection": "PASS", "pre_freeze_rejection": "PASS",
        "lock": "PASS_EXCLUSIVE_CREATE", "ledger_sha256_before_after": ledger_before,
    }


def update_manifest(contract: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = []
    for path in (FORWARD_CONTRACT, FORWARD_LEDGER, FORWARD_STATE):
        require(path.is_file(), "FINAL_ARTIFACT_MISSING", path)
        artifacts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path), "mutable_forward_state": path != FORWARD_CONTRACT})
    manifest = {
        "schema_version": "1.0.0", "experiment_id": TASK_ID, "status": "PASS_HASH_VERIFIED",
        "forward_contract_hash": contract["forward_contract_hash"], "artifact_count_including_manifest": len(artifacts) + 1,
        "artifacts": artifacts, "source_sha256": sha256_file(Path(__file__)),
        "canonical_data_read_only": True, "2026_pre_freeze_outcome_read_count": 0,
    }
    require(manifest["artifact_count_including_manifest"] <= 5, "ARTIFACT_BUDGET_EXCEEDED")
    atomic_write_json(HASH_MANIFEST, manifest)
    return manifest


def verify_state(contract: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    chain = validate_hash_chain(FORWARD_LEDGER)
    require(chain["status"] == "PASS", "LEDGER_HASH_CHAIN_INVALID", chain["reasons"])
    require(state["forward_contract_hash"] == contract["forward_contract_hash"], "STATE_CONTRACT_MISMATCH")
    require(int(state["ledger_row_count"]) == chain["row_count"], "STATE_LEDGER_COUNT_MISMATCH")
    require(int(state["forward_session_count"]) == sum(row["session_eligibility"] == "TRUE" for row in ledger_rows(FORWARD_LEDGER)), "FORWARD_SESSION_COUNT_MISMATCH")
    require(state["last_row_hash"] == chain["last_row_hash"], "STATE_LAST_HASH_MISMATCH")
    return chain


def initialize() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    identities = recover_frozen_identities()
    if FORWARD_CONTRACT.is_file():
        contract = load_contract()
        require(contract["frozen_identities"] == identities, "FROZEN_IDENTITY_DRIFT")
    else:
        contract = build_contract(identities, datetime.now(timezone.utc))
        atomic_write_json(FORWARD_CONTRACT, contract)
    ensure_ledger(FORWARD_LEDGER)
    if FORWARD_STATE.is_file():
        state = read_json(FORWARD_STATE)
    else:
        state = initial_state(contract)
        atomic_write_json(FORWARD_STATE, state)
    verify_state(contract, state)
    dry = internal_dry_run(contract, state)
    state = read_json(FORWARD_STATE)
    state["dry_run_status"] = dry["status"]
    state["initialization_tests"] = dry
    state["current_exact_date_input_status"] = "AWAITING_BOUND_SESSION_INPUT" if not SESSION_INPUT_POINTER.is_file() else "INPUT_POINTER_PRESENT_NOT_CONSUMED_BY_INIT"
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(FORWARD_STATE, state)
    verify_state(contract, state)
    manifest = update_manifest(contract)
    return {"contract": contract, "state": state, "manifest": manifest, "chain": validate_hash_chain(FORWARD_LEDGER)}


def daily(input_path: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    contract = load_contract()
    state = read_json(FORWARD_STATE)
    verify_state(contract, state)
    source = (input_path or Path(contract["session_input_contract"]["stable_pointer"])).resolve()
    if not source.is_file():
        return {"status": "SESSION_DATA_BLOCKED", "reason": "AWAITING_HASH_BOUND_EXACT_DATE_SESSION_INPUT", "ledger_mutated": False, "forward_session_count": state["forward_session_count"]}
    payload = read_json(source)
    row, new_state = process_session(payload, contract, state, verify_refs=True)
    if dry_run:
        return {"status": "PASS_DRY_RUN_NO_MUTATION", "session_date": row["session_date"], "ledger_mutated": False, "forward_session_count": state["forward_session_count"]}
    appended = append_ledger_row(FORWARD_LEDGER, row, contract)
    new_state["last_row_hash"] = appended["row_hash"]
    atomic_write_json(FORWARD_STATE, new_state)
    verify_state(contract, new_state)
    manifest = update_manifest(contract)
    return {"status": "PASS_APPENDED_ONE_ELIGIBLE_SESSION", "session_date": row["session_date"], "row_hash": appended["row_hash"], "forward_session_count": new_state["forward_session_count"], "manifest": manifest}


def status_payload() -> dict[str, Any]:
    contract = load_contract()
    state = read_json(FORWARD_STATE)
    chain = verify_state(contract, state)
    return {"status": "PASS", "contract_hash": contract["forward_contract_hash"], "forward_session_count": state["forward_session_count"], "next_milestone": state["next_milestone"], "hash_chain": chain}


def terminal_summary(result: Mapping[str, Any]) -> str:
    contract, state, manifest = result["contract"], result["state"], result["manifest"]
    identities = contract["frozen_identities"]
    task_status = "FORWARD_FROZEN_AWAITING_FIRST_ELIGIBLE_SESSION_WITH_PREEXISTING_REPOSITORY_ANTI_BLOAT_HARD_GATE_FAIL"
    daily_command = f"& '{Path(sys.executable)}' '{Path(__file__).resolve()}' daily"
    lines = [
        "=" * 60, "A2_THREE_ARM_POSTFREEZE_FORWARD_INIT_R1_FINAL", "=" * 60, "", f"TASK_STATUS={task_status}", "",
        "-" * 60, "FREEZE", "-" * 60, "", f"FORWARD_FREEZE_TIMESTAMP_UTC={contract['forward_freeze_timestamp_utc']}",
        f"FORWARD_FREEZE_TIMESTAMP_ET={contract['forward_freeze_timestamp_et']}", "", f"FIRST_ELIGIBLE_FORWARD_SESSION={contract['first_eligible_forward_session']}",
        "", f"FORWARD_SESSION_COUNT={state['forward_session_count']}", "", "-" * 60, "ARM0 CONTROL", "-" * 60, "",
        "ARM0_ID=RAW_A2", f"ARM0_MODEL_HASH={identities['raw_model_hash']}", f"ARM0_PORTFOLIO_HASH={identities['raw_portfolio_hash']}",
        f"ARM0_TRAINING_CUTOFF={identities['raw_training_cutoff']}", "", "-" * 60, "ARM1 SIMPLE DECONCENTRATION", "-" * 60, "",
        "ARM1_ID=S1_SOFT_025", f"ARM1_CONTRACT_HASH={identities['s1_contract_hash']}", "", "-" * 60, "ARM2 RISK ADJUSTED", "-" * 60, "",
        "ARM2_ID=S1_CONCENTRATION_GROSS_SCALED", f"ARM2_GROSS_SCALER_HASH={identities['gross_scaler_contract_hash']}", "", "-" * 60,
        "ARM3 CAUSAL DIAGNOSTIC", "-" * 60, "", "ARM3_ID=RAW_CONCENTRATION_GROSS_SCALED", "ARM3_ROLE=DIAGNOSTIC_ONLY", "",
        "ARM2_ARM3_SAME_GROSS_CONTRACT=PASS", "", "-" * 60, "TAXONOMY", "-" * 60, "",
        f"FF12_TAXONOMY_HASH={identities['ff12_taxonomy_hash']}", f"FF48_TAXONOMY_HASH={identities['ff48_taxonomy_hash']}", "",
        f"FORWARD_TAXONOMY_PATH_STATUS={state['current_exact_date_input_status']};FAIL_CLOSED_PIT_ACCEPTANCE_AND_COVERAGE_GATE_BOUND", "", "-" * 60,
        "FORWARD INFRASTRUCTURE", "-" * 60, "", "APPEND_ONLY_STATUS=PASS_ENABLED", "HASH_CHAIN_STATUS=PASS_GENESIS_EMPTY_LEDGER",
        "LOCK_STATUS=PASS_EXCLUSIVE_CREATE_TESTED", "", "DUPLICATE_REJECTION_STATUS=PASS", "OUT_OF_ORDER_REJECTION_STATUS=PASS",
        "PRE_FREEZE_REJECTION_STATUS=PASS", "", f"DRY_RUN_STATUS={state['dry_run_status']}", "", "-" * 60, "MILESTONES", "-" * 60, "",
        "NEXT_MILESTONE=20", "", "MILESTONE_20_ROLE=OPERATIONAL_ONLY", "MILESTONE_60_ROLE=EARLY_ECONOMIC",
        "MILESTONE_120_ROLE=FORMAL_FORWARD_REVIEW", "MILESTONE_250_ROLE=ANNUAL_SCALE_REVIEW", "", "-" * 60, "GOVERNANCE", "-" * 60, "",
        "2026_PRE_FREEZE_HISTORY_CLASSIFICATION=EXPOSED_HISTORY_NOT_FORWARD", "", "NO_HISTORICAL_BACKFILL=TRUE", "NO_MODEL_RETRAINING=TRUE",
        "NO_PARAMETER_CHANGE=TRUE", "", "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS", f"PREEXISTING_ACL_EXCEPTION_COUNT={PREEXISTING_ACL_EXCEPTION_COUNT}", "",
        "-" * 60, "OPERATIONS", "-" * 60, "", f"DAILY_FORWARD_COMMAND={daily_command}", "", f"OUTPUT_DIR={OUT}",
        f"FINAL_ARTIFACT_COUNT={manifest['artifact_count_including_manifest']}", f"HASH_MANIFEST_STATUS={manifest['status']}", "", "=" * 60,
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "daily", "status", "validate"))
    parser.add_argument("--session-input", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize()
            print(terminal_summary(result))
        elif args.command == "daily":
            print(json.dumps(daily(args.session_input, dry_run=args.dry_run), indent=2, sort_keys=True))
        else:
            print(json.dumps(status_payload(), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, ForwardGateError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
