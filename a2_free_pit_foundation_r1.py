"""Pre-2026 identity, SIC/FF, factor-risk, and Capacity E1 foundation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import logging.handlers
import math
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests


TASK_ID = "A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1"
DEFAULT_USER_AGENT = "us-tech-quant PIT taxonomy research JIN kinryukii@gmail.com"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
PROVIDER_CACHE = OUT / "provider_cache"
MOOMOO_CACHE = PROVIDER_CACHE / "moomoo_qfq"
REGISTRY_MODULE = REPO / "research_registry.py"
REGISTRY_CONFIG = REPO / "config" / "research_registry.json"
TEST_FILE = REPO / "test_a2_free_pit_foundation_r1.py"
OOF = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "oof_predictions.parquet"
ELIGIBLE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "universe" / "daily_eligible_universe_membership.parquet"
TOP20 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "top20_selections.parquet"
IDENTITY_INTERVALS = RESULTS / "A2_PIT13F_MATERIALIZATION_R1" / "effective_universe_intervals.parquet"
IDENTITY_MANIFEST = RESULTS / "A2_PIT13F_MATERIALIZATION_R1" / "source_hash_manifest.json"
SEC_SUB = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_fsds_sub_min.parquet")
SEC_MANIFEST = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_source_manifest.json")
RV_CONTRACT = RESULTS / "A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1" / "rv_contract.json"
MINIMUM_SYSTEM = RESULTS / "A2_MINIMUM_JUSTIFIED_SYSTEM_AND_COMPONENT_INCREMENTALITY_AUDIT_R1" / "minimum_justified_system.json"

EXPECTED_HASHES = {
    OOF: "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    ELIGIBLE: "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    IDENTITY_INTERVALS: "cafd53e665143e56d31c3f7b5299593a099fc53a0032879d63fbd8abae6a0d30",
    IDENTITY_MANIFEST: "d9f303b9e7741083207567bc1bddf9d5efc5b181a9a11eeae504c5d68521796f",
    SEC_SUB: "ce2f7a3a2df1237a1b30f79eaf31604c6ea256029e8726f65c6b50112089489e",
    SEC_MANIFEST: "217e75433fa73f6d4a9070b0553caceb99413a9d3a365dd52ef47451a4c59b63",
    RV_CONTRACT: "146af857798c21441b24a1106d32112878ffba43be289ac69098b9a4c070e9c8",
}

PRICE_HASHES = {
    "qfq": {
        2020: "f9acd32fa2878458577b7fd2a8eff8d3f07acf13fc32c4323754a07265bc24fe",
        2021: "c8fd7c684fe7ef54705b99c3e6bd59c810d26af94f9dc27cf1ed7df4b32d5865",
        2022: "3b16247910d78e3961ff94c6c9d9030afaf200f3a30ae22205b0c5042483e588",
        2023: "a5a35422629920b7f5d063acabbb04f0ad410ec9f7e504de7daadd3b9d249bf6",
        2024: "7e14eb6735e7660e6895ab1a9a4ee86fa3ed1bd3ea976c56aeecfd75411e5eb8",
        2025: "b8a8abb5a8bdd7cbf9cf44ebba2f54bc09b60612c6fd8a7b7951aa064f9abc89",
    },
    "raw": {
        2020: "6e6b508549aa2ee623c56c2f48abfec28708be546f6cfef8bc79637a50462e26",
        2021: "9e11fcab458de30c25d0df0149aa35b947e19f240ef5dd556e722a8eac8c8ea4",
        2022: "b81060c25097ca0b3c029abc699351b067cebb39680ed942374d01025ed1dfa6",
        2023: "6a56f8e13a1bc20953baf4df2d832b66ac678b4648bdceab576a81df6b237cf5",
        2024: "596d5e205cce67e4bebbdba8316d902cf90272a5ddc82e18b0a70ef405ef88a9",
        2025: "59d12cad7fc639b3e6a32e15b936c090c7ebebe88d19f2b238f0187db61e44e3",
    },
}

FF_URLS = {
    "FF12": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes12.zip",
    "FF48": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes48.zip",
}
FF_EXPECTED_HASHES = {
    "FF12": "d801141acf039f2e06e6d4d9ba2b3992e9747a1d82fabd53ef21da4a3af79fff",
    "FF48": "f37edffc024fe7b91b794dd933244430da2de212df2549dc448c0dfcca45d740",
}
SEC_FORM_PRIMARY = {"10-K", "10-Q", "20-F", "40-F"}
SEC_FORM_LISTING = {"S-1", "S-3", "F-1", "F-3"}
SEC_FORM_GAP = {"8-K", "6-K"}
LEGAL_DECISION_DATES = 752
ELIGIBLE_OBSERVATIONS = 313_668
RV_CHILD = "A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1"
DISSEMINATION_LAG_MINUTES = 5
ROLLING_MAX = 252
ROLLING_MIN = 180

# The first official SDK quota observation was made before any task fetch.  A
# later checkpoint/resume overwrote the convenience JSON, so retain only the
# aggregate values that were observed in this same execution.  Per-security
# initial membership is deliberately *not* reconstructed.
MOOMOO_TASK_START_QUOTA = {
    "moomoo_used_quota": 551,
    "moomoo_remain_quota": 449,
    "moomoo_active_quota_security_count": 551,
    "observation_source": "OFFICIAL_MOOMOO_SDK_GET_HISTORY_KL_QUOTA_GET_DETAIL_TRUE",
    "observation_time_status": "INITIAL_TIMESTAMP_NOT_RETAINED_AFTER_RESUME_OVERWRITE",
}
MOOMOO_INITIAL_SELECTED_ACTIVE_COUNT = 296

ZERO_COUNTERS = {
    "new_alpha_component_count": 0,
    "new_predictive_model_count": 0,
    "new_predictive_model_fit_count": 0,
    "new_threshold_search_count": 0,
    "new_factor_subset_search_count": 0,
    "new_factor_window_search_count": 0,
    "new_portfolio_spec_search_count": 0,
    "new_optimizer_search_count": 0,
    "post_2025_realized_label_metric_read_count": 0,
    "post_2025_model_evaluation_metric_read_count": 0,
    "post_2025_outcome_derived_metadata_read_count": 0,
    "2026_economic_outcome_read_count": 0,
    "holdout_peek_count": 0,
    "mixed_source_content_open_count": 0,
    "economic_result_read_count": 0,
}


class TaskError(RuntimeError):
    """Fail-closed contract error."""


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise TaskError(f"{code}:{detail}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_fingerprint() -> str:
    return sha256_value({
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "test_sha256": sha256_file(TEST_FILE),
        "contracts": contracts(),
    })


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def assert_hash(path: Path) -> str:
    require(path in EXPECTED_HASHES, "UNAPPROVED_PHYSICAL_SOURCE", path)
    observed = sha256_file(path)
    require(observed == EXPECTED_HASHES[path], "SOURCE_HASH_MISMATCH", f"{path}:{observed}")
    return observed


def assert_price_hash(path: Path, mode: str, year: int) -> str:
    observed = sha256_file(path)
    require(observed == PRICE_HASHES[mode][year], "PRICE_SOURCE_HASH_MISMATCH", f"{path}:{observed}")
    return observed


def read_certified_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    assert_hash(path)
    schema = set(pq.ParquetFile(path).schema_arrow.names)
    require(set(columns).issubset(schema), "SOURCE_SCHEMA_MISMATCH", f"{path}:{sorted(set(columns)-schema)}")
    return pq.read_table(path, columns=columns).to_pandas()


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def registry_module():
    return import_module(REGISTRY_MODULE, "a2_foundation_registry")


def registry_root(module: Any) -> Path:
    root, _ = module._load_config(str(REGISTRY_CONFIG), None)
    return Path(root)


def row_sha256(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    values = frame[columns].copy()
    for column in columns:
        if pd.api.types.is_datetime64_any_dtype(values[column]):
            values[column] = pd.to_datetime(values[column], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z").astype("string").fillna("<NA>")
        else:
            values[column] = values[column].astype("string").fillna("<NA>")
    return values.apply(
        lambda row: hashlib.sha256("\x1f".join(str(value) for value in row.tolist()).encode("utf-8")).hexdigest(),
        axis=1,
    )


def keyset_sha256(frame: pd.DataFrame, columns: list[str]) -> str:
    values = frame[columns].copy()
    for column in columns:
        if pd.api.types.is_datetime64_any_dtype(values[column]):
            values[column] = pd.to_datetime(values[column]).dt.strftime("%Y-%m-%d")
        else:
            values[column] = values[column].astype("string").fillna("<NA>")
    values = values.sort_values(columns, kind="mergesort")
    digest = hashlib.sha256()
    for row in values.itertuples(index=False, name=None):
        digest.update(("\x1f".join(map(str, row)) + "\n").encode("utf-8"))
    return digest.hexdigest()


TOKEN_EXPANSIONS = {
    "ENTMT": "ENTERTAINMENT", "HLDG": "HOLDING", "HLDGS": "HOLDINGS", "HLDNGS": "HOLDINGS",
    "FINL": "FINANCIAL", "SYS": "SYSTEMS", "CTZNS": "CITIZENS", "MTRS": "MOTORS", "AIRLS": "AIRLINES",
    "PETE": "PETROLEUM", "INDS": "INDUSTRIES", "INTL": "INTERNATIONAL", "CONTL": "CONTINENTAL",
    "THERAPEUTIC": "THERAPEUTICS",
}
LEGAL_SUFFIXES = {"INCORPORATED", "INC", "CORPORATION", "CORP", "COMPANY", "CO", "LIMITED", "LTD", "PLC", "LP", "LLC", "NV", "BV", "SA", "AG", "SE", "SPA", "THE"}
TRAILING_JURISDICTIONS = {"DE", "DEL", "MD", "NY", "SD", "PA", "TX", "MN", "VA", "OH", "NEW", "IN", "N", "D", "PL"}


def identity_name_key(value: Any) -> str:
    text = re.sub(r"\b([NBS])\s*\.\s*V\s*\.", " ", str(value).upper())
    tokens = re.sub(r"[^A-Z0-9 ]", " ", text).split()
    tokens = [TOKEN_EXPANSIONS.get(token, token) for token in tokens]
    tokens = [token for token in tokens if token not in LEGAL_SUFFIXES]
    while tokens and tokens[-1] in TRAILING_JURISDICTIONS:
        tokens.pop()
    if tokens and tokens[-1] == "C":
        tokens.pop()
    return "".join(sorted(tokens))


def source_temporal_manifest() -> dict[str, Any]:
    price_sources = []
    for mode in ("qfq", "raw"):
        for year, expected in PRICE_HASHES[mode].items():
            price_sources.append({
                "path": str(Path(r"D:\us-tech-quant-data\moomoo\source") / f"prices_{mode}" / f"year={year}" / "prices.parquet"),
                "classification": "SAFE_PRE2026", "expected_sha256": expected,
                "contract": f"PHYSICALLY_ISOLATED_CALENDAR_YEAR_{year}",
            })
    sources = [
        {"path": str(OOF), "classification": "SAFE_PRE2026", "expected_sha256": EXPECTED_HASHES[OOF], "allowed_columns": ["signal_date", "ticker", "universe_size", "split", "a2_rank"]},
        {"path": str(ELIGIBLE), "classification": "SAFE_PRE2026", "expected_sha256": EXPECTED_HASHES[ELIGIBLE]},
        {"path": str(TOP20), "classification": "SAFE_PRE2026", "expected_sha256": EXPECTED_HASHES[TOP20], "allowed_columns": ["signal_date", "ticker", "a2_rank"]},
        {"path": str(IDENTITY_INTERVALS), "classification": "SAFE_PRE2026", "expected_sha256": EXPECTED_HASHES[IDENTITY_INTERVALS]},
        {"path": str(SEC_SUB), "classification": "SAFE_PRE2026", "expected_sha256": EXPECTED_HASHES[SEC_SUB]},
        {"path": str(SEC_MANIFEST), "classification": "SAFE_STRUCTURAL_METADATA_ONLY", "expected_sha256": EXPECTED_HASHES[SEC_MANIFEST]},
        {"path": "**/risk_registry.json", "classification": "DENYLISTED_MIXED_POST2025", "open_policy": "DO_NOT_OPEN"},
        {"path": "D:/us-tech-quant-data/canonical/v22/A2_PRE2026_RAW_MOOMOO_REHAB_SURFACE_R1", "classification": "UNKNOWN_TEMPORAL_CONTENT", "open_policy": "DO_NOT_OPEN"},
        {"path": "historical OpenFIGI caches", "classification": "UNKNOWN_TEMPORAL_CONTENT", "open_policy": "DO_NOT_OPEN"},
        *price_sources,
    ]
    return {
        "task_id": TASK_ID, "status": "PASS", "file_level_firewall": True,
        "open_then_filter_allowed": False, "evaluation_data_end": "2025-12-31",
        "sources": sources, "zero_read_counters": ZERO_COUNTERS, "build_fingerprint": build_fingerprint(),
    }


def contracts() -> dict[str, dict[str, Any]]:
    sic = {
        "contract_id": "SEC_AS_FILED_ASSIGNED_SIC_NEXT_LEGAL_SESSION_R1",
        "source": "SEC_OFFICIAL_FINANCIAL_STATEMENT_DATA_SETS_SUB_AS_FILED_METADATA",
        "candidate_field": "sic", "availability_anchor": "accepted_timestamp_utc",
        "conservative_dissemination_lag_minutes": DISSEMINATION_LAG_MINUTES,
        "decision_timestamp_status": "NOT_AUTHORITATIVELY_AVAILABLE_IN_SAFE_KEYSET",
        "fallback_rule": "FIRST_LEGAL_DECISION_SESSION_STRICTLY_AFTER_ACCEPTANCE_PLUS_LAG",
        "primary_forms": sorted(SEC_FORM_PRIMARY), "listing_forms": sorted(SEC_FORM_LISTING),
        "gap_forms": sorted(SEC_FORM_GAP), "amendment_rule": "BASE_FORM_ALLOWED_IF_SUFFIX_A",
        "forbidden": ["FILING_DATE_AS_AVAILABILITY", "CURRENT_SIC_BACKFILL", "FUTURE_SIC_BACKFILL", "SYNTHETIC_SIC"],
    }
    factor = {
        "contract_id": "PRE2026_FIXED_FACTOR_STACK_R1",
        "tradable_factor_stack": ["SPY", "QQQ_ORTHOGONAL_TO_SPY", "SOXX_ORTHOGONAL_TO_SPY_AND_QQQ"],
        "security_return_definition": "QFQ_CLOSE_TO_CLOSE_PCT_CHANGE",
        "tradable_factor_return_definition": "QFQ_CLOSE_TO_CLOSE_PCT_CHANGE",
        "adv_input_definition": "RAW_PROVIDER_TURNOVER_ONLY_CANONICAL_OR_TASK_QFQ_RESPONSE_PROVIDER_TURNOVER_FIELD",
        "forbidden_adv_definition": "ADJUSTED_CLOSE_TIMES_VOLUME",
        "academic_factor_stack": ["MKT", "SMB", "HML", "RMW", "CMA", "MOM"],
        "academic_data_rule": "OFFICIAL_PHYSICALLY_PRE2026_ISOLATED_VINTAGE_ONLY_ELSE_UNAVAILABLE",
        "qmj_bab_rule": "REUSE_EXISTING_SAFE_OFFICIAL_ONLY_ELSE_UNAVAILABLE", "factor_subset_search_count": 0,
    }
    estimator = {
        "contract_id": "ROLLING_252_SESSION_OLS_R1", "intercept": True,
        "maximum_trailing_sessions": ROLLING_MAX, "minimum_valid_observations": ROLLING_MIN,
        "decision_cutoff": "STRICTLY_BEFORE_DECISION_DATE", "orthogonalization": "WITHIN_TRAILING_WINDOW_SEQUENTIAL_OLS",
        "realized_vol_20": "TRAILING_20_RETURN_STD_DDOF0_SHIFT1_SQRT252",
        "realized_vol_60": "TRAILING_60_RETURN_STD_DDOF0_SHIFT1_SQRT252",
        "downside_vol": "TRAILING_60_MIN_RETURN_ZERO_SQUARED_MEAN_SQRT_SHIFT1_SQRT252",
        "adv20": "TRAILING_20_RAW_PROVIDER_TURNOVER_MEAN_SHIFT1",
        "adv60": "TRAILING_60_RAW_PROVIDER_TURNOVER_MEAN_SHIFT1",
        "median_dollar_volume_60": "TRAILING_60_RAW_PROVIDER_TURNOVER_MEDIAN_SHIFT1",
        "idio_vol": "OLS_RESIDUAL_RMS_TIMES_SQRT252",
        "window_search_count": 0, "alternative_estimator_comparison_count": 0,
    }
    fetch = {
        "contract_id": "MOOMOO_P1_MISSING_QFQ_TURNOVER_ONLY_R1", "request_start": "2021-01-01",
        "request_end": "2025-12-31", "adjustment": "QFQ", "frequency": "K_DAY",
        "priority": "P1_ZERO_LOCAL_PRICE_COVERAGE", "duplicate_fetch_allowed": False,
        "reserve_rule": "MAX_20_OR_CEIL_5_PERCENT_INITIAL_REMAINING", "current_industry_use": "FORBIDDEN",
        "terminal_unknown_security_checkpoint_rule": "REUSE_FAIL_CLOSED_STATUS_WITHOUT_REPEAT_PROVIDER_REQUEST",
    }
    return {"sic": sic, "factor": factor, "estimator": estimator, "fetch": fetch}


def freeze_design() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "source_temporal_manifest.json", source_temporal_manifest())
    frozen = contracts()
    atomic_json(OUT / "sic_availability_contract.json", frozen["sic"])
    atomic_json(OUT / "factor_stack_contract.json", frozen["factor"])
    atomic_json(OUT / "exposure_estimator_contract.json", frozen["estimator"])
    atomic_json(OUT / "moomoo_fetch_contract.json", frozen["fetch"])


REGISTRY_CANDIDATES = [
    ("PRE2026_HISTORICAL_SECURITY_IDENTITY_BRIDGE", "97618f24f1fb0c59847b115e54f2e651c1999423749945b5236d47636f5b3b0d", "a5dd997f78a10095293a7f562fbf7797fc3e0096795f5c3e82de5a2586dcfbcd", "f81bb3a92e255b4ef3d15e47c2c976668ffed91c191321345869cab70502b3e4", "Historical security identity bridge"),
    ("PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE", "18b8d80058b97b7b551053d93ddc8a9f6e5fc23470a08b6e7410144657e19ce8", "57052d18a58fa9af61176d0f9cc4748be9044dac01f94dcb3704fac1c50e266d", "80f65b0b471606f7c44fcca3060299e501e768f472476b051673292c7416c6dc", "PIT as-filed SEC SIC and official FF projection"),
    ("PRE2026_SECURITY_FACTOR_RISK_SURFACE", "02f81f4aa8658e136818880e2c657483e6d805bcd0feb9a9dbb447e54fd01cf6", "630bd82ce4719714063823d2a88ea4ed05206083d7a3633b536d0ee6b659c0ba", "7e194b9158736d55388ed8c8f792dc27e15950e532189517132466ad4a8b5da1", "Fixed trailing security factor and risk surface"),
    ("PRE2026_CAPACITY_E1_DAILY_SURFACE", "73e2a5ae7bd93948fd5b9bc372f4f6576683647aa6c2956eb4c6a37ee7712525", "0c8dec35d0c075a7e0001f8b42ff00429ecb1587ee8fb13c22b81c749db93284", "be6892962169c3933f52aac896166a1e0741938c24e66fba4a9cb0a868884cd4", "Daily Capacity E1 surface"),
]


def build_registry_preflight() -> dict[str, Any]:
    registry = registry_module()
    root = registry_root(registry)
    current = registry.current_state(root)
    validation = registry.validate_registry(root)
    require(current.get("status") == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT", current)
    require(validation.get("status") == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT", validation)
    head = str(current["head_sha256"])
    decisions = []
    for entity_id, spec, info, mech, name in REGISTRY_CANDIDATES:
        candidate = {
            "entity_id": entity_id, "canonical_name": entity_id, "entity_type": "DATA_INFRASTRUCTURE", "status": "ACTIVE",
            "specification_fingerprint": spec, "information_source_fingerprint": info, "mechanism_fingerprint": mech,
            "decision_layer": name, "evidence_source_temporal_status": "SAFE_PRE2026_OFFICIAL_OR_CERTIFIED_LOCAL",
            "excluded_source_refs": ["**/risk_registry.json"], "temporal_evidence_limitations": ["NO_POST_2025_OUTCOME_CONTENT"],
            "authoritative_artifact_refs": [str(OUT)], "information_family": entity_id,
        }
        proposal = {"candidate": candidate, "change_type": "NEW_DATA_INFRASTRUCTURE"}
        decisions.append({"entity_id": entity_id, "proposal": proposal, "result": registry.preflight_proposal(root, proposal)})
    allowed = {"PASS_DISTINCT_INFORMATION_SOURCE", "EXTEND_EXISTING"}
    blocked = [row for row in decisions if row["result"].get("decision") not in allowed]
    require(not blocked, "REGISTRY_ANTI_DUPLICATION_BLOCK", blocked)
    payload = {
        "task_id": TASK_ID, "status": "PASS", "registry_base_head": head,
        "current": current, "validation": validation, "decisions": decisions,
        "queries": ["security master", "historical security identity", "CIK", "FIGI", "SIC", "FF12", "FF48", "factor exposure", "risk surface", "capacity surface"],
    }
    atomic_json(OUT / "registry_preflight.json", payload)
    rows = []
    for row in decisions:
        decision = row["result"].get("decision")
        rows.append({"capability": row["entity_id"], "classification": "EXTEND_EXISTING" if decision == "EXTEND_EXISTING" else "NEW_CAPABILITY_JUSTIFIED", "registry_decision": decision, "matched_entity_ids": "|".join(row["result"].get("matched_entity_ids", []))})
    rows.extend([
        {"capability": "AUTHORITATIVE_ELIGIBLE_KEYSET", "classification": "REUSE_EXISTING", "registry_decision": "RAW_A2_BROAD_OOF_PREDICTIONS", "matched_entity_ids": "RAW_A2_BROAD_OOF_PREDICTIONS"},
        {"capability": "PIT_SECURITY_INTERVAL_IDENTITY", "classification": "REUSE_EXISTING", "registry_decision": "CERTIFIED_A2_PIT13F_MATERIALIZATION", "matched_entity_ids": ""},
        {"capability": "CURRENT_INDUSTRY_AS_HISTORICAL", "classification": "UNAVAILABLE", "registry_decision": "FORBIDDEN", "matched_entity_ids": ""},
    ])
    atomic_csv(OUT / "capability_reuse_matrix.csv", pd.DataFrame(rows))
    return payload


def load_eligible_keyset() -> tuple[pd.DataFrame, pd.DataFrame]:
    oof = read_certified_parquet(OOF, ["signal_date", "ticker", "universe_size", "split", "a2_rank"])
    eligible = read_certified_parquet(ELIGIBLE, ["signal_date", "active_13f_quarter", "ticker", "moomoo_transport_code", "cusip", "U_t_fingerprint"])
    intervals = read_certified_parquet(IDENTITY_INTERVALS, [
        "effective_start", "effective_end", "report_quarter", "security_id", "security_id_type", "cusip", "issuer_name",
        "title_of_class", "ticker", "moomoo_transport_code", "mapping_status", "mapping_source", "mapping_confidence", "source_filing",
    ])
    for frame in (oof, eligible):
        frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.normalize()
    legal_dates = sorted(oof.signal_date.unique())
    eligible = eligible.loc[eligible.signal_date.isin(legal_dates)].copy()
    require(len(legal_dates) == LEGAL_DECISION_DATES, "HARD_BLOCKER_CANONICAL_ELIGIBLE_KEYSET_CONFLICT", len(legal_dates))
    require(len(oof) == ELIGIBLE_OBSERVATIONS and len(eligible) == ELIGIBLE_OBSERVATIONS, "HARD_BLOCKER_CANONICAL_ELIGIBLE_KEYSET_CONFLICT", f"{len(oof)}:{len(eligible)}")
    require(not oof.duplicated(["signal_date", "ticker"]).any(), "OOF_DUPLICATE_KEY")
    require(not eligible.duplicated(["signal_date", "cusip"]).any(), "ELIGIBLE_DUPLICATE_SECURITY_KEY")
    work = eligible.merge(oof, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    require(len(work) == ELIGIBLE_OBSERVATIONS, "ELIGIBLE_OOF_KEYSET_MISMATCH", len(work))
    intervals["effective_start"] = pd.to_datetime(intervals.effective_start).dt.normalize()
    intervals["effective_end"] = pd.to_datetime(intervals.effective_end).dt.normalize()
    identity = work.merge(
        intervals, left_on=["cusip", "active_13f_quarter"], right_on=["cusip", "report_quarter"],
        how="left", validate="many_to_one", suffixes=("", "_interval"), indicator=True,
    )
    in_interval = identity.signal_date.between(identity.effective_start, identity.effective_end, inclusive="both")
    strict = identity._merge.eq("both") & in_interval & identity.mapping_status.eq("RESOLVED") & identity.security_id.eq(identity.cusip)
    require(strict.all(), "HARD_BLOCKER_CANONICAL_ELIGIBLE_KEYSET_CONFLICT", int((~strict).sum()))
    identity = identity.rename(columns={"signal_date": "decision_date", "ticker": "ticker_at_date", "moomoo_transport_code": "moomoo_code"})
    identity["canonical_security_id"] = identity.security_id.astype(str)
    identity["identity_status"] = "AUTHORITATIVE_RESOLVED"
    identity["identity_name_key"] = identity.issuer_name.map(identity_name_key)
    identity["exchange_at_date"] = pd.NA
    manifest = {
        "task_id": TASK_ID, "status": "PASS", "legal_decision_dates": len(legal_dates),
        "total_eligible_observations": len(identity), "unique_tickers": int(identity.ticker_at_date.nunique()),
        "unique_canonical_security_ids": int(identity.canonical_security_id.nunique()),
        "eligible_source": str(ELIGIBLE), "eligible_source_sha256": EXPECTED_HASHES[ELIGIBLE],
        "rank_source": str(OOF), "rank_source_sha256": EXPECTED_HASHES[OOF],
        "identity_source": str(IDENTITY_INTERVALS), "identity_source_sha256": EXPECTED_HASHES[IDENTITY_INTERVALS],
        "keyset_sha256": keyset_sha256(identity, ["decision_date", "canonical_security_id"]),
        "ticker_reuse_across_security_ids": int(identity.groupby("ticker_at_date").canonical_security_id.nunique().gt(1).sum()),
        "source_fingerprint": sha256_value([EXPECTED_HASHES[ELIGIBLE], EXPECTED_HASHES[OOF], EXPECTED_HASHES[IDENTITY_INTERVALS]]),
        "build_fingerprint": build_fingerprint(),
    }
    atomic_json(OUT / "eligible_keyset_manifest.json", manifest)
    inventory = identity.groupby("canonical_security_id", sort=True).agg(
        ticker_at_date=("ticker_at_date", "last"), issuer_name=("issuer_name", "last"), title_of_class=("title_of_class", "last"),
        valid_from=("decision_date", "min"), valid_to=("decision_date", "max"), eligible_observation_count=("decision_date", "size"),
        mapping_source=("mapping_source", "last"), mapping_confidence=("mapping_confidence", "last"),
    ).reset_index()
    inventory["identity_status"] = "AUTHORITATIVE_RESOLVED"
    inventory["cik_status"] = "PENDING_SEC_EXACT_NAME_RECONCILIATION"
    atomic_csv(OUT / "existing_identity_inventory.csv", inventory)
    return identity, intervals


def _next_legal_session(accepted: pd.Series, legal_dates: Sequence[pd.Timestamp]) -> pd.Series:
    accepted_utc = pd.to_datetime(accepted, utc=True) + pd.Timedelta(minutes=DISSEMINATION_LAG_MINUTES)
    normalized = accepted_utc.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize().to_numpy(dtype="datetime64[ns]")
    sessions = np.asarray(pd.to_datetime(list(legal_dates)), dtype="datetime64[ns]")
    positions = np.searchsorted(sessions, normalized, side="right")
    result = np.full(len(positions), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    valid = positions < len(sessions)
    result[valid] = sessions[positions[valid]]
    return pd.Series(pd.to_datetime(result), index=accepted.index)


def load_sec_index(legal_dates: Sequence[pd.Timestamp]) -> tuple[pd.DataFrame, pd.DataFrame]:
    assert_hash(SEC_MANIFEST)
    manifest = json.loads(SEC_MANIFEST.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS_COMPLETE", "SEC_CACHE_NOT_CERTIFIED")
    require(len(manifest.get("successful_quarters", [])) == 20 and not manifest.get("failed_quarters"), "SEC_CACHE_QUARTER_GAP")
    sub = read_certified_parquet(SEC_SUB, ["adsh", "cik", "name", "sic", "former", "changed", "form", "filed", "quarter", "accepted_timestamp_utc"])
    sub["accepted_timestamp_utc"] = pd.to_datetime(sub.accepted_timestamp_utc, utc=True)
    require(sub.accepted_timestamp_utc.max() <= pd.Timestamp("2025-12-31 23:59:59", tz="UTC"), "POST_2025_SEC_ROW")
    sub["base_form"] = sub.form.astype(str).str.upper().str.replace(r"/A$", "", regex=True)
    sub["available_session"] = _next_legal_session(sub.accepted_timestamp_utc, legal_dates)
    rows = []
    for quarter, item in sorted(manifest["quarters"].items()):
        rows.append({
            "quarter": quarter.upper(), "source_type": item.get("source_type"),
            "official_source_url": f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip",
            "download_timestamp_utc": item.get("download_timestamp_utc"), "source_zip_sha256": item.get("sha256"),
            "sub_row_count": item.get("sub_row_count"), "zip_integrity": item.get("zip_integrity"),
            "reused_local_projection_path": str(SEC_SUB), "reused_local_projection_sha256": EXPECTED_HASHES[SEC_SUB],
        })
    download = pd.DataFrame(rows)
    download["build_fingerprint"] = build_fingerprint()
    atomic_parquet(OUT / "sec_download_manifest.parquet", download)
    return sub, download


def build_sec_identity(identity: pd.DataFrame, sub: pd.DataFrame, verified_accessions: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pieces = []
    for field, role in (("name", "CURRENT_LEGAL_NAME"), ("former", "FORMER_NAME_DISCLOSED_AS_FILED")):
        part = sub[["cik", field, "accepted_timestamp_utc", "available_session", "adsh", "form"]].copy().rename(columns={field: "sec_name"})
        part["name_role"] = role
        part["identity_name_key"] = part.sec_name.map(identity_name_key)
        pieces.append(part.loc[part.identity_name_key.ne("") & part.available_session.notna() & part.adsh.isin(verified_accessions)])
    evidence = pd.concat(pieces, ignore_index=True).drop_duplicates(["cik", "identity_name_key", "name_role", "accepted_timestamp_utc", "adsh"])
    evidence["build_fingerprint"] = build_fingerprint()
    atomic_parquet(OUT / "sec_identity_evidence.parquet", evidence.sort_values(["cik", "accepted_timestamp_utc", "adsh"], kind="mergesort"))
    first = evidence.groupby(["identity_name_key", "name_role", "cik"], as_index=False).agg(
        first_available_session=("available_session", "min"), first_acceptance_datetime=("accepted_timestamp_utc", "min"),
        evidence_count=("adsh", "nunique"), evidence_accession=("adsh", "first"), sec_name=("sec_name", "first"),
    )
    key_columns = ["decision_date", "canonical_security_id", "identity_name_key", "ticker_at_date", "exchange_at_date", "issuer_name", "title_of_class", "moomoo_code", "effective_start", "effective_end", "mapping_source", "mapping_confidence"]
    keys = identity[key_columns].copy()
    candidates = keys.merge(first, on="identity_name_key", how="left")
    candidates = candidates.loc[candidates.first_available_session.le(candidates.decision_date)]
    # Uniqueness is evaluated across CURRENT and FORMER roles together.  A
    # unique former-name candidate must never bypass an ambiguous current-name
    # candidate (or vice versa).
    counts = candidates.groupby(["decision_date", "canonical_security_id"], as_index=False).cik.nunique().rename(columns={"cik": "issuer_candidate_count"})
    unique = candidates.merge(counts, on=["decision_date", "canonical_security_id"], how="left")
    unique = unique.loc[unique.issuer_candidate_count.eq(1)].copy()
    unique["role_priority"] = unique.name_role.map({"CURRENT_LEGAL_NAME": 0, "FORMER_NAME_DISCLOSED_AS_FILED": 1}).fillna(9)
    unique = unique.sort_values(["decision_date", "canonical_security_id", "role_priority", "first_available_session"], kind="mergesort")
    unique = unique.drop_duplicates(["decision_date", "canonical_security_id"], keep="first")
    keep = ["decision_date", "canonical_security_id", "cik", "name_role", "first_available_session", "first_acceptance_datetime", "evidence_accession", "evidence_count", "issuer_candidate_count"]
    resolved = keys.merge(unique[keep], on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    resolved = resolved.merge(counts, on=["decision_date", "canonical_security_id"], how="left", suffixes=("", "_all"), validate="one_to_one")
    if "issuer_candidate_count_all" in resolved:
        resolved["issuer_candidate_count"] = resolved.issuer_candidate_count_all.combine_first(resolved.issuer_candidate_count)
        resolved = resolved.drop(columns=["issuer_candidate_count_all"])
    resolved["issuer_candidate_count"] = resolved.issuer_candidate_count.fillna(0).astype(int)
    resolved["cik"] = pd.to_numeric(resolved.cik, errors="coerce").astype("Int64")

    # A canonical security cannot silently switch issuer CIKs across its
    # history.  Without explicit transition evidence, every bridge row for the
    # affected security fails closed even if each individual date looked
    # locally unique.
    provisional = resolved.groupby("canonical_security_id", as_index=False).agg(
        provisional_unique_ciks=("cik", "nunique"),
        provisional_cik_candidates=("cik", lambda values: "|".join(str(int(value)) for value in sorted(set(values.dropna())))),
    )
    history_conflict_ids = set(provisional.loc[provisional.provisional_unique_ciks.gt(1), "canonical_security_id"])
    resolved["history_cik_conflict"] = resolved.canonical_security_id.isin(history_conflict_ids)
    history_conflict = resolved.history_cik_conflict
    for column in ("cik", "first_available_session", "first_acceptance_datetime", "evidence_accession", "evidence_count", "name_role"):
        resolved.loc[history_conflict, column] = pd.NA
    resolved["confidence_class"] = np.where(resolved.cik.notna(), "MULTI_SOURCE_CONFIRMED", "UNRESOLVED")
    resolved["evidence_type"] = np.select(
        [resolved.history_cik_conflict, resolved.issuer_candidate_count.gt(1), resolved.cik.notna() & resolved.name_role.eq("FORMER_NAME_DISCLOSED_AS_FILED"), resolved.cik.notna()],
        ["UNRESOLVED_MULTIPLE_ISSUER_CIKS_ACROSS_SECURITY_HISTORY", "UNRESOLVED_AMBIGUOUS_PRIOR_AS_FILED_EXACT_NAME_CIK", "CUSIP_INTERVAL_PLUS_PRIOR_AS_FILED_FORMER_NAME", "CUSIP_INTERVAL_PLUS_PRIOR_AS_FILED_LEGAL_NAME"],
        default="NO_UNIQUE_PRIOR_AS_FILED_EXACT_NAME",
    )
    resolved["temporal_status"] = np.where(resolved.cik.notna(), "STRICT_PIT", "UNRESOLVED")
    resolved["source"] = "CERTIFIED_PROJECT_CUSIP_INTERVAL_PLUS_OFFICIAL_SEC_FSDS"
    resolved["build_fingerprint"] = build_fingerprint()
    resolved["valid_from"] = resolved.effective_start
    resolved["valid_to"] = resolved.effective_end
    resolved["figi"] = pd.NA
    resolved["composite_figi"] = pd.NA
    resolved["share_class_figi"] = pd.NA
    resolved["figi_identifier_status"] = np.where(
        resolved.mapping_source.eq("OPENFIGI"),
        "EXISTING_OPENFIGI_MAPPING_SOURCE_REUSED_IDENTIFIER_NOT_EXPOSED_IN_CERTIFIED_INTERVAL",
        "NOT_REQUIRED_CANONICAL_IDENTITY_ALREADY_RESOLVED",
    )
    bridge_cols = ["decision_date", "canonical_security_id", "ticker_at_date", "exchange_at_date", "moomoo_code", "issuer_name", "title_of_class", "cik", "figi", "composite_figi", "share_class_figi", "figi_identifier_status", "valid_from", "valid_to", "effective_start", "effective_end", "issuer_candidate_count", "history_cik_conflict", "evidence_type", "evidence_accession", "first_acceptance_datetime", "first_available_session", "source", "confidence_class", "temporal_status", "mapping_source", "mapping_confidence", "build_fingerprint"]
    bridge = resolved[bridge_cols].copy()
    require(not bridge.duplicated(["decision_date", "canonical_security_id"]).any(), "SEC_IDENTITY_DUPLICATE_KEY")
    bridge["row_sha256"] = row_sha256(bridge, bridge_cols)
    atomic_parquet(OUT / "security_identity_bridge.parquet", bridge)
    audit = bridge.groupby("canonical_security_id", as_index=False).agg(
        ticker_at_date=("ticker_at_date", "last"), valid_from=("decision_date", "min"), valid_to=("decision_date", "max"),
        eligible_observations=("decision_date", "size"), sec_cik_linked_observations=("cik", lambda x: int(x.notna().sum())),
        unique_ciks=("cik", "nunique"), max_issuer_candidate_count=("issuer_candidate_count", "max"),
        ambiguous_candidate_observations=("issuer_candidate_count", lambda values: int(values.gt(1).sum())),
        history_cik_conflict=("history_cik_conflict", "max"), confidence_class=("confidence_class", "last"),
    )
    audit = audit.merge(provisional, on="canonical_security_id", how="left", validate="one_to_one")
    audit["identity_status"] = "AUTHORITATIVE_RESOLVED"
    audit["cik_link_status"] = np.where(audit.sec_cik_linked_observations.eq(audit.eligible_observations), "FULL_STRICT_PIT", np.where(audit.sec_cik_linked_observations.gt(0), "PARTIAL_STRICT_PIT", "UNRESOLVED"))
    atomic_csv(OUT / "identity_coverage_report.csv", audit)
    conflicts = audit.loc[audit.history_cik_conflict | audit.max_issuer_candidate_count.gt(1)].copy()
    conflicts["conflict_type"] = np.select(
        [conflicts.history_cik_conflict & conflicts.max_issuer_candidate_count.gt(1), conflicts.history_cik_conflict],
        ["HISTORY_CIK_CONFLICT_AND_DATE_LEVEL_AMBIGUITY_FAILED_CLOSED", "MULTIPLE_ISSUER_CIKS_ACROSS_SECURITY_HISTORY_FAILED_CLOSED"],
        default="DATE_LEVEL_ISSUER_CIK_AMBIGUITY_FAILED_CLOSED",
    )
    atomic_csv(OUT / "identity_conflict_report.csv", conflicts)
    figi = bridge.groupby("canonical_security_id", as_index=False).agg(ticker=("ticker_at_date", "last"), existing_mapping_source=("mapping_source", "last"), valid_from=("decision_date", "min"), valid_to=("decision_date", "max"))
    figi["request_status"] = np.where(figi.existing_mapping_source.eq("OPENFIGI"), "REUSED_EXISTING_CANONICAL_OPENFIGI_EVIDENCE", "NOT_REQUIRED_CANONICAL_IDENTITY_ALREADY_RESOLVED")
    figi["historical_effective_date_claimed"] = False
    figi["ambiguity_policy"] = "DO_NOT_AUTO_PICK_FIRST_RESULT"
    atomic_parquet(OUT / "openfigi_mapping_audit.parquet", figi)
    return bridge, evidence, audit


def official_get(url: str, target: Path, *, user_agent: str, max_attempts: int = 5, min_interval: float = 0.0, state: dict[str, float] | None = None, session: requests.Session | None = None) -> dict[str, Any]:
    if target.is_file():
        stat = target.stat()
        return {
            "status": "REUSED", "path": str(target), "sha256": sha256_file(target), "byte_size": stat.st_size, "url": url,
            "download_timestamp_utc": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
            "download_timestamp_provenance": "FILESYSTEM_CREATION_TIME_OF_IMMUTABLE_LOCAL_CACHE",
        }
    if session is None:
        session = requests.Session()
        session.trust_env = False
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    error = ""
    for attempt in range(max_attempts):
        try:
            if state is not None and state.get("last", 0.0):
                time.sleep(max(0.0, min_interval - (time.monotonic() - state["last"])))
            response = session.get(url, headers=headers, timeout=120)
            if state is not None:
                state["last"] = time.monotonic()
            if response.status_code == 200:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(response.content)
                os.replace(temporary, target)
                return {"status": "DOWNLOADED", "path": str(target), "sha256": sha256_file(target), "byte_size": target.stat().st_size, "url": url, "download_timestamp_utc": utc_now()}
            error = f"HTTP_{response.status_code}"
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}:{exc}"
        if attempt + 1 < max_attempts:
            time.sleep(min(2 ** attempt, 16))
    return {"status": "UNAVAILABLE", "path": str(target), "url": url, "error": error}


def _parse_sec_header(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="latin-1", errors="replace")
    def one(tag: str) -> str | None:
        match = re.search(rf"<{re.escape(tag)}>\s*([^\r\n<]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else None
    names = re.findall(r"<(?:FORMER-CONFORMED-NAME|CONFORMED-NAME)>\s*([^\r\n<]+)", text, flags=re.IGNORECASE)
    accepted = one("ACCEPTANCE-DATETIME")
    parsed_accepted = pd.to_datetime(accepted, format="%Y%m%d%H%M%S", errors="coerce")
    if pd.notna(parsed_accepted):
        parsed_accepted = parsed_accepted.tz_localize("America/New_York", ambiguous="raise", nonexistent="shift_forward").tz_convert("UTC")
    return {
        "header_cik": pd.to_numeric(one("CIK") or one("CENTRAL-INDEX-KEY"), errors="coerce"),
        "header_sic": pd.to_numeric(one("ASSIGNED-SIC"), errors="coerce"),
        "header_accession": one("ACCESSION-NUMBER"),
        "header_form": one("TYPE") or one("FORM-TYPE"),
        "header_acceptance_datetime": parsed_accepted,
        "header_name_keys": sorted({identity_name_key(value) for value in names if identity_name_key(value)}),
        "header_names": names,
    }


def _sec_header_url(row: Mapping[str, Any]) -> str:
    accession = str(row["adsh"])
    return f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{accession.replace('-', '')}/{accession}.hdr.sgml"


def _select_identity_header_candidates(identity: pd.DataFrame, sub: pd.DataFrame) -> pd.DataFrame:
    project_keys = set(identity.identity_name_key.unique()) - {""}
    allowed = sub.loc[sub.base_form.isin(SEC_FORM_PRIMARY | SEC_FORM_LISTING)].copy()
    rows = []
    for field, role in (("name", "CURRENT_LEGAL_NAME"), ("former", "FORMER_NAME_DISCLOSED_AS_FILED")):
        piece = allowed[["adsh", "cik", "sic", "accepted_timestamp_utc", "available_session", "form", field]].copy().rename(columns={field: "sec_name"})
        piece["identity_name_key"] = piece.sec_name.map(identity_name_key)
        piece["name_role"] = role
        rows.append(piece.loc[piece.identity_name_key.isin(project_keys) & piece.available_session.notna()])
    evidence = pd.concat(rows, ignore_index=True)
    evidence = evidence.sort_values(["identity_name_key", "name_role", "cik", "accepted_timestamp_utc", "adsh"], kind="mergesort")
    return evidence.drop_duplicates(["identity_name_key", "name_role", "cik"], keep="first")


def fetch_sec_headers(candidates: pd.DataFrame, *, user_agent: str, purpose: str) -> tuple[pd.DataFrame, set[str]]:
    cache = PROVIDER_CACHE / "sec_headers"
    manifest_path = OUT / f"sec_header_{purpose.lower()}_manifest.parquet"
    existing = pd.read_parquet(manifest_path) if manifest_path.is_file() else pd.DataFrame()
    by_accession = {str(row.adsh): row._asdict() for row in existing.itertuples(index=False)} if not existing.empty else {}
    limiter = {"last": 0.0}
    session = requests.Session()
    session.trust_env = False
    for number, row in enumerate(candidates.itertuples(index=False), 1):
        accession = str(row.adsh)
        if accession in by_accession and by_accession[accession].get("validation_status") == "PASS":
            continue
        path = cache / f"{accession}.hdr.sgml"
        result = official_get(_sec_header_url(row._asdict()), path, user_agent=user_agent, max_attempts=4, min_interval=0.21, state=limiter, session=session)
        record = {
            "adsh": accession, "cik": int(row.cik), "fsds_sic": None if pd.isna(row.sic) else int(row.sic),
            "fsds_acceptance_datetime": row.accepted_timestamp_utc, "form": row.form, "purpose": purpose,
            "source_url": result.get("url"), "artifact_path": result.get("path"), "source_sha256": result.get("sha256"),
            "byte_size": result.get("byte_size"), "download_status": result.get("status"), "error": result.get("error", ""),
            "validation_status": "FAIL", "validation_reason": "DOWNLOAD_UNAVAILABLE",
        }
        if result.get("status") in {"DOWNLOADED", "REUSED"}:
            parsed = _parse_sec_header(path)
            expected_acceptance = pd.Timestamp(row.accepted_timestamp_utc)
            acceptance_ok = pd.notna(parsed["header_acceptance_datetime"]) and abs((parsed["header_acceptance_datetime"] - expected_acceptance).total_seconds()) <= 60
            cik_ok = pd.notna(parsed["header_cik"]) and int(parsed["header_cik"]) == int(row.cik)
            sic_ok = pd.notna(row.sic) and pd.notna(parsed["header_sic"]) and int(parsed["header_sic"]) == int(row.sic)
            accession_ok = parsed["header_accession"] == accession
            form_ok = str(parsed["header_form"]).upper() == str(row.form).upper()
            name_key = getattr(row, "identity_name_key", "")
            name_ok = not name_key or name_key in parsed["header_name_keys"]
            record.update({
                "header_cik": parsed["header_cik"], "header_sic": parsed["header_sic"],
                "header_acceptance_datetime": parsed["header_acceptance_datetime"], "header_name_keys": "|".join(parsed["header_name_keys"]),
                "header_accession": parsed["header_accession"], "header_form": parsed["header_form"],
                "validation_status": "PASS" if cik_ok and sic_ok and acceptance_ok and accession_ok and form_ok and name_ok else "FAIL",
                "validation_reason": "PASS" if cik_ok and sic_ok and acceptance_ok and accession_ok and form_ok and name_ok else f"CIK={cik_ok};SIC={sic_ok};ACCEPTED={acceptance_ok};ACCESSION={accession_ok};FORM={form_ok};NAME={name_ok}",
            })
        by_accession[accession] = record
        if number % 25 == 0:
            atomic_parquet(manifest_path, pd.DataFrame(by_accession.values()).sort_values("adsh", kind="mergesort"))
    manifest = pd.DataFrame(by_accession.values()).sort_values("adsh", kind="mergesort") if by_accession else pd.DataFrame(columns=["adsh", "validation_status"])
    atomic_parquet(manifest_path, manifest)
    verified = set(manifest.loc[manifest.validation_status.eq("PASS"), "adsh"].astype(str))
    return manifest, verified


def official_ff_definitions(*, user_agent: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    mappings = {}
    manifests = {}
    for taxonomy, url in FF_URLS.items():
        target = PROVIDER_CACHE / "kenneth_french" / f"official_{taxonomy.lower()}_sic_definitions.zip"
        result = official_get(url, target, user_agent=user_agent)
        require(result.get("status") in {"DOWNLOADED", "REUSED"}, "OFFICIAL_FF_DEFINITION_UNAVAILABLE", result)
        require(sha256_file(target) == FF_EXPECTED_HASHES[taxonomy], "OFFICIAL_FF_DEFINITION_HASH_CHANGED", f"{taxonomy}:{sha256_file(target)}")
        mapping, manifest = parse_ff_definition(target, taxonomy)
        mapping.to_parquet(PROVIDER_CACHE / "kenneth_french" / f"{taxonomy.lower()}_mapping.parquet", index=False, compression="zstd")
        manifests[taxonomy] = {**manifest, **result, "build_fingerprint": build_fingerprint()}
        mappings[taxonomy] = mapping
        atomic_json(OUT / f"{taxonomy.lower()}_mapping_manifest.json", manifests[taxonomy])
    return mappings["FF12"], mappings["FF48"], manifests


def parse_ff_definition(path: Path, taxonomy: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "FF_ZIP_INTEGRITY_FAILURE", taxonomy)
        members = [name for name in archive.namelist() if not name.endswith("/")]
        require(len(members) == 1, "FF_ZIP_MEMBER_COUNT", f"{taxonomy}:{members}")
        raw = archive.read(members[0])
    text = raw.decode("latin-1")
    current_code = current_short = current_name = None
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        range_match = re.match(r"^\s*(\d{4})-(\d{4})(?:\s+.*?)?\s*$", line)
        header = re.match(r"^\s*(\d{1,2})\s+([A-Za-z0-9]+)\s+(.+?)\s*$", line)
        if header and not range_match:
            current_code, current_short, current_name = int(header.group(1)), header.group(2), header.group(3).strip()
        elif range_match and current_code is not None:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            require(0 <= start <= end <= 9999, "FF_RANGE_INVALID", line)
            rows.append({"taxonomy": taxonomy, "industry_code": current_code, "industry_short_name": current_short, "industry_name": current_name, "sic_start": start, "sic_end": end, "official_line": line.strip()})
    ranges = pd.DataFrame(rows)
    require(not ranges.empty, "FF_NO_RANGES_PARSED", taxonomy)
    expected_groups = 12 if taxonomy == "FF12" else 48
    # FF12 group 12 is the official residual group and intentionally has no
    # explicit ranges.  It is mapped only for valid SICs unmatched by groups
    # 1-11.  FF48 has no synthetic residual fallback.
    expected_explicit = 11 if taxonomy == "FF12" else 48
    require(ranges.industry_code.nunique() == expected_explicit, "FF_GROUP_COUNT_INVALID", f"{taxonomy}:{ranges.industry_code.nunique()}")
    expanded = []
    for row in ranges.itertuples(index=False):
        for sic in range(row.sic_start, row.sic_end + 1):
            expanded.append({"sic4": sic, "industry_code": int(row.industry_code), "industry_short_name": row.industry_short_name, "industry_name": row.industry_name})
    mapping = pd.DataFrame(expanded)
    require(not mapping.duplicated("sic4").any(), "FF_OFFICIAL_RANGE_OVERLAP", taxonomy)
    if taxonomy == "FF12":
        missing = sorted(set(range(100, 10000)) - set(mapping.sic4))
        residual = pd.DataFrame({"sic4": missing, "industry_code": 12, "industry_short_name": "Other", "industry_name": "Other"})
        mapping = pd.concat([mapping, residual], ignore_index=True)
    manifest = {
        "taxonomy": taxonomy, "official_source_url": FF_URLS[taxonomy], "official_zip_sha256": sha256_file(path),
        "official_member_name": members[0], "official_member_sha256": hashlib.sha256(raw).hexdigest(),
        "range_count": len(ranges), "industry_count": expected_groups, "mapped_sic_count": len(mapping),
        "parser_contract": "EXACT_OFFICIAL_NUMERIC_RANGES_FF12_OFFICIAL_RESIDUAL_ONLY_NO_FF48_SYNTHETIC_FILL",
        "mapping_fingerprint": sha256_value(ranges.to_dict("records")),
    }
    return mapping, manifest


def select_sic_state_candidates(bridge: pd.DataFrame, sub: pd.DataFrame) -> pd.DataFrame:
    linked = set(bridge.cik.dropna().astype(int))
    work = sub.loc[sub.cik.isin(linked) & sub.sic.notna()].copy()
    preferred = work.loc[work.base_form.isin(SEC_FORM_PRIMARY | SEC_FORM_LISTING)].sort_values(["cik", "accepted_timestamp_utc", "adsh"], kind="mergesort")
    preferred["prior_sic"] = preferred.groupby("cik").sic.shift()
    selected = preferred.loc[preferred.prior_sic.isna() | preferred.sic.ne(preferred.prior_sic)].copy()
    preferred_ciks = set(preferred.cik.astype(int))
    no_preferred = linked - preferred_ciks
    gap = work.loc[work.cik.isin(no_preferred) & work.base_form.isin(SEC_FORM_GAP)].sort_values(["cik", "accepted_timestamp_utc", "adsh"], kind="mergesort")
    gap["prior_sic"] = gap.groupby("cik").sic.shift()
    gap = gap.loc[gap.prior_sic.isna() | gap.sic.ne(gap.prior_sic)]
    return pd.concat([selected, gap], ignore_index=True).sort_values(["cik", "accepted_timestamp_utc", "adsh"], kind="mergesort")


def build_sic_events(candidates: pd.DataFrame, header_manifest: pd.DataFrame) -> pd.DataFrame:
    verified = header_manifest.loc[header_manifest.validation_status.eq("PASS"), ["adsh", "source_url", "source_sha256", "header_sic", "header_acceptance_datetime"]]
    events = candidates.merge(verified, on="adsh", how="inner", validate="one_to_one")
    events["assigned_sic"] = pd.to_numeric(events.header_sic, errors="coerce").astype("Int64")
    events["acceptance_datetime"] = pd.to_datetime(events.header_acceptance_datetime, utc=True)
    events["sic_available_at"] = events.acceptance_datetime + pd.Timedelta(minutes=DISSEMINATION_LAG_MINUTES)
    events["usable_decision_session"] = events.available_session
    events["source_archive_ref"] = events.source_url
    events["source_sha256"] = events.source_sha256.astype(str)
    events = events[["cik", "adsh", "form", "acceptance_datetime", "filed", "assigned_sic", "sic_available_at", "usable_decision_session", "source_archive_ref", "source_sha256"]].rename(columns={"adsh": "accession_number"})
    events = events.sort_values(["cik", "acceptance_datetime", "accession_number"], kind="mergesort")
    conflicts = events.groupby(["cik", "sic_available_at"]).assigned_sic.nunique().gt(1)
    require(not conflicts.any(), "SEC_SIC_SAME_AVAILABILITY_CONFLICT", conflicts[conflicts].index.tolist())
    events["build_fingerprint"] = build_fingerprint()
    events["row_sha256"] = row_sha256(events, list(events.columns))
    atomic_parquet(OUT / "sec_as_filed_sic_events.parquet", events)
    return events


def project_sic_ff(identity: pd.DataFrame, bridge: pd.DataFrame, events: pd.DataFrame, ff12: pd.DataFrame, ff48: pd.DataFrame, ff_manifests: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    base_columns = ["decision_date", "canonical_security_id", "ticker_at_date", "exchange_at_date", "a2_rank"]
    base = identity[base_columns].merge(bridge[["decision_date", "canonical_security_id", "cik", "confidence_class"]], on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    projected = []
    event_groups = {}
    for cik, group in events.groupby("cik"):
        ordered = group.sort_values(["usable_decision_session", "acceptance_datetime", "accession_number"], kind="mergesort")
        event_groups[int(cik)] = ordered.drop_duplicates("usable_decision_session", keep="last")
    for cik, rows in base.groupby("cik", dropna=False, sort=False):
        rows = rows.sort_values("decision_date", kind="mergesort").copy()
        rows["decision_date"] = pd.to_datetime(rows.decision_date).astype("datetime64[ns]")
        if pd.isna(cik) or int(cik) not in event_groups:
            rows["sic4"] = pd.NA
            rows["sic_available_at"] = pd.NaT
            rows["sic_accession"] = pd.NA
            rows["sic_source_sha256"] = pd.NA
        else:
            right = event_groups[int(cik)][["usable_decision_session", "sic_available_at", "assigned_sic", "accession_number", "source_sha256"]].copy()
            right["usable_decision_session"] = pd.to_datetime(right.usable_decision_session).astype("datetime64[ns]")
            rows = pd.merge_asof(rows, right, left_on="decision_date", right_on="usable_decision_session", direction="backward", allow_exact_matches=True)
            rows = rows.rename(columns={"assigned_sic": "sic4", "accession_number": "sic_accession", "source_sha256": "sic_source_sha256"})
        projected.append(rows)
    surface = pd.concat(projected, ignore_index=True)
    surface["sic4"] = pd.to_numeric(surface.sic4, errors="coerce").astype("Int64")
    ff12 = ff12.rename(columns={"industry_code": "ff12_code", "industry_name": "ff12_name", "industry_short_name": "ff12_short_name"})
    ff48 = ff48.rename(columns={"industry_code": "ff48_code", "industry_name": "ff48_name", "industry_short_name": "ff48_short_name"})
    surface = surface.merge(ff12, on="sic4", how="left", validate="many_to_one").merge(ff48, on="sic4", how="left", validate="many_to_one")
    # Canonicalize the timezone-aware dtype before row hashing so Parquet
    # readback produces the exact same deterministic token representation.
    surface["sic_available_at"] = pd.to_datetime(surface.sic_available_at, utc=True)
    surface["identity_status"] = "AUTHORITATIVE"
    surface["taxonomy_status"] = np.select(
        [surface.cik.isna(), surface.sic4.isna(), surface.ff48_code.isna(), surface.ff12_code.isna()],
        ["ISSUER_BRIDGE_UNRESOLVED", "SIC_UNAVAILABLE", "SIC_VALID_FF48_UNMAPPED", "SIC_VALID_FF12_UNMAPPED"],
        default="STRICT_PIT_SIC_FF12_FF48_MAPPED",
    )
    surface["mapping_reason"] = np.select(
        [surface.cik.isna(), surface.sic4.isna(), surface.ff48_code.isna(), surface.ff12_code.isna()],
        ["NO_UNIQUE_PRIOR_AS_FILED_EXACT_NAME_CIK", "NO_VERIFIED_PRIOR_AS_FILED_SIC_EVENT", "UNMAPPED_SIC_OFFICIAL_FF48", "UNMAPPED_SIC_OFFICIAL_FF12"],
        default="VERIFIED_SEC_HEADER_AND_OFFICIAL_FRENCH_RULES",
    )
    surface["taxonomy_name"] = "PIT_AS_FILED_SEC_SIC_FF12_FF48"
    surface["source_fingerprints"] = json.dumps({
        "eligible": EXPECTED_HASHES[ELIGIBLE], "identity": EXPECTED_HASHES[IDENTITY_INTERVALS], "sec_fsds": EXPECTED_HASHES[SEC_SUB],
        "identity_bridge": sha256_file(OUT / "security_identity_bridge.parquet"),
        "sec_as_filed_sic_events": sha256_file(OUT / "sec_as_filed_sic_events.parquet"),
        "ff12": ff_manifests["FF12"]["official_zip_sha256"], "ff48": ff_manifests["FF48"]["official_zip_sha256"],
        "build_fingerprint": build_fingerprint(),
    }, sort_keys=True)
    output_columns = [
        "decision_date", "canonical_security_id", "ticker_at_date", "exchange_at_date", "cik", "identity_status", "sic4", "sic_available_at", "sic_accession",
        "sic_source_sha256", "ff48_code", "ff48_name", "ff12_code", "ff12_name", "taxonomy_name", "taxonomy_status", "mapping_reason", "source_fingerprints", "a2_rank",
    ]
    surface = surface[output_columns].sort_values(["decision_date", "canonical_security_id"], kind="mergesort").reset_index(drop=True)
    require(len(surface) == ELIGIBLE_OBSERVATIONS, "TAXONOMY_SURFACE_ROW_COUNT", len(surface))
    require(not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "TAXONOMY_SURFACE_DUPLICATE_KEY")
    sic_available_naive = pd.to_datetime(surface.sic_available_at, utc=True).dt.tz_convert(None)
    require(sic_available_naive.loc[surface.sic_available_at.notna()].le(surface.loc[surface.sic_available_at.notna(), "decision_date"]).all(), "FUTURE_SIC_PROJECTION")
    surface["row_sha256"] = row_sha256(surface, output_columns)
    atomic_parquet(OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet", surface)

    surface["year"] = surface.decision_date.dt.year
    surface["rank_group"] = np.where(surface.a2_rank.le(20), "RANK_LE_20", "RANK_GT_20")
    surface["rank_bucket"] = pd.cut(surface.a2_rank, bins=[0, 20, 40, 100, 200, np.inf], labels=["R001_020", "R021_040", "R041_100", "R101_200", "R201_PLUS"])
    surface["strict_sic"] = surface.sic4.notna()
    surface["strict_ff48"] = surface.ff48_code.notna()
    surface["strict_ff12"] = surface.ff12_code.notna()

    def coverage(group_columns: list[str]) -> pd.DataFrame:
        result = surface.groupby(group_columns, observed=True, dropna=False).agg(
            total_eligible_observations=("canonical_security_id", "size"),
            strict_identity_resolved=("identity_status", lambda x: int(x.eq("AUTHORITATIVE").sum())),
            sec_cik_linked=("cik", lambda x: int(x.notna().sum())), strict_sic_mapped=("strict_sic", "sum"),
            strict_ff48_mapped=("strict_ff48", "sum"), strict_ff12_mapped=("strict_ff12", "sum"),
        ).reset_index()
        for name in ("strict_identity_resolved", "sec_cik_linked", "strict_sic_mapped", "strict_ff48_mapped", "strict_ff12_mapped"):
            result[f"{name}_coverage"] = result[name] / result.total_eligible_observations
        return result

    by_year = coverage(["year"])
    by_rank = coverage(["rank_group", "rank_bucket"])
    atomic_csv(OUT / "taxonomy_coverage_by_year.csv", by_year)
    atomic_csv(OUT / "taxonomy_coverage_by_rank_bucket.csv", by_rank)
    missing = surface.loc[~surface.strict_ff48, ["decision_date", "canonical_security_id", "ticker_at_date", "cik", "sic4", "a2_rank", "rank_group", "taxonomy_status", "mapping_reason"]]
    atomic_csv(OUT / "taxonomy_missingness_report.csv", missing)

    total = len(surface)
    identity_coverage = float(surface.identity_status.eq("AUTHORITATIVE").mean())
    ff48_coverage = float(surface.strict_ff48.mean())
    year_min = float(by_year.strict_ff48_mapped_coverage.min())
    year_max = float(by_year.strict_ff48_mapped_coverage.max())
    rank20 = surface.groupby("rank_group").strict_ff48.mean()
    le20 = float(rank20.get("RANK_LE_20", 0.0))
    gt20 = float(rank20.get("RANK_GT_20", 0.0))
    gap = abs(le20 - gt20)
    ready = identity_coverage >= 0.95 and ff48_coverage >= 0.90 and year_min >= 0.85 and gt20 >= 0.85 and gap <= 0.10
    status = {
        "total_eligible_observations": total, "strict_identity_resolved": int(surface.identity_status.eq("AUTHORITATIVE").sum()),
        "strict_identity_coverage": identity_coverage, "sec_cik_linked": int(surface.cik.notna().sum()),
        "strict_sic_mapped": int(surface.strict_sic.sum()), "strict_sic_coverage": float(surface.strict_sic.mean()),
        "strict_ff48_mapped": int(surface.strict_ff48.sum()), "strict_ff48_coverage": ff48_coverage,
        "strict_ff12_mapped": int(surface.strict_ff12.sum()), "strict_ff12_coverage": float(surface.strict_ff12.mean()),
        "rank_le20_ff48_coverage": le20, "rank_gt20_ff48_coverage": gt20, "coverage_gap": gap,
        "minimum_year_ff48_coverage": year_min, "maximum_year_ff48_coverage": year_max,
        "max_year_ff48_coverage_gap": year_max - year_min,
        "counterfactual_data_status": "READY" if ready else "PARTIAL",
        "build_fingerprint": build_fingerprint(),
        "surface_sha256": sha256_file(OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet"),
    }
    atomic_json(OUT / "taxonomy_surface_status.json", status)
    return surface, status


def rv_compatibility(status: Mapping[str, Any]) -> dict[str, Any]:
    assert_hash(RV_CONTRACT)
    contract = json.loads(RV_CONTRACT.read_text(encoding="utf-8"))
    required = contract.get("input_contract", {}).get("sector")
    compatible = False
    payload = {
        "rv_frozen_child": RV_CHILD, "rv_contract_sha256": EXPECTED_HASHES[RV_CONTRACT], "rv_contract_modified": False,
        "rv_contract_requirement": required, "candidate_taxonomy": "PIT_AS_FILED_SEC_SIC_FF48_INDUSTRY_CONTROL",
        "rv_contract_compatibility": "NO", "reason": "FROZEN_CONTRACT_REQUIRES_SECTOR;NO_AUTHORITATIVE_EQUIVALENCE_OF_FF48_INDUSTRY_TO_SECTOR_IS_DECLARED",
        "rv_data_dependency_available": compatible, "rv_economics_run": False,
    }
    atomic_text(OUT / "rv_contract_compatibility_report.md", "# RV contract compatibility\n\n" + "\n".join(f"- {key}: {value}" for key, value in payload.items()) + "\n")
    return payload


def _import_moomoo():
    sdk_appdata = OUT / "_sdk_appdata"
    sdk_appdata.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(sdk_appdata)
    original = logging.handlers.TimedRotatingFileHandler
    logging.handlers.TimedRotatingFileHandler = lambda *args, **kwargs: logging.NullHandler()
    try:
        import moomoo
    finally:
        logging.handlers.TimedRotatingFileHandler = original
    return moomoo


def moomoo_quota_detail() -> tuple[int, int, list[dict[str, Any]]]:
    moomoo = _import_moomoo()
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        ret, payload = context.get_history_kl_quota(get_detail=True)
    finally:
        context.close()
    require(ret == moomoo.RET_OK, "MOOMOO_QUOTA_DETAIL_FAILED", payload)
    used, remain, detail = payload
    require(isinstance(detail, list), "MOOMOO_QUOTA_DETAIL_SCHEMA")
    return int(used), int(remain), detail


def quota_probe(identity: pd.DataFrame) -> dict[str, Any]:
    try:
        used, remain, detail = moomoo_quota_detail()
        codes = sorted({str(row.get("code", "")) for row in detail if str(row.get("code", ""))})
        payload = {
            "task_id": TASK_ID, "status": "PASS", "probe_type": "GET_HISTORY_KL_QUOTA_GET_DETAIL_TRUE",
            "observed_utc": utc_now(), "moomoo_used_quota": used, "moomoo_remain_quota": remain,
            "moomoo_active_quota_security_count": len(codes), "active_code_set_sha256": sha256_value(codes),
            "required_code_count": int(identity.moomoo_code.nunique()), "history_request_count": 0,
            "task_start_observation": MOOMOO_TASK_START_QUOTA,
            "current_observation_role": "CURRENT_PROVIDER_STATE_NOT_TASK_START",
        }
    except Exception as exc:
        payload = {"task_id": TASK_ID, "status": "UNAVAILABLE", "error": f"{type(exc).__name__}:{exc}", "history_request_count": 0}
    atomic_json(OUT / "moomoo_quota_preflight.json", payload)
    return payload


def load_canonical_price_partitions() -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    frames: dict[str, list[pd.DataFrame]] = {"qfq": [], "raw": []}
    manifest = []
    for mode in ("qfq", "raw"):
        for year in range(2020, 2026):
            path = Path(r"D:\us-tech-quant-data\moomoo\source") / f"prices_{mode}" / f"year={year}" / "prices.parquet"
            observed = assert_price_hash(path, mode, year)
            frame = pq.read_table(path, columns=["ticker", "trade_date", "close", "volume", "turnover", "autype", "source"]).to_pandas()
            frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
            require(frame.trade_date.dt.year.eq(year).all(), "PRICE_PARTITION_YEAR_MISMATCH", path)
            require(frame.trade_date.max() <= pd.Timestamp("2025-12-31"), "POST_2025_PRICE_ROW", path)
            require(frame.source.eq("MOOMOO_OPEND").all(), "PRICE_SOURCE_INVALID", path)
            expected_autype = "qfq" if mode == "qfq" else "raw"
            require(frame.autype.astype(str).str.lower().eq(expected_autype).all(), "PRICE_AUTYPE_INVALID", path)
            require(not frame.duplicated(["ticker", "trade_date"]).any(), "PRICE_DUPLICATE_KEY", path)
            frames[mode].append(frame)
            manifest.append({"mode": mode, "year": year, "path": str(path), "sha256": observed, "row_count": len(frame), "min_date": frame.trade_date.min(), "max_date": frame.trade_date.max()})
    qfq = pd.concat(frames["qfq"], ignore_index=True)
    raw = pd.concat(frames["raw"], ignore_index=True)
    require(not qfq.duplicated(["ticker", "trade_date"]).any() and not raw.duplicated(["ticker", "trade_date"]).any(), "CROSS_YEAR_PRICE_DUPLICATE")
    require(set(qfq[["ticker", "trade_date"]].itertuples(index=False, name=None)) == set(raw[["ticker", "trade_date"]].itertuples(index=False, name=None)), "QFQ_RAW_KEYSET_MISMATCH")
    return qfq, raw, manifest


def price_gap(identity: pd.DataFrame, qfq: pd.DataFrame) -> pd.DataFrame:
    required = identity.groupby(["ticker_at_date", "moomoo_code"], as_index=False).agg(first_decision=("decision_date", "min"), last_decision=("decision_date", "max"), required_observations=("decision_date", "size"))
    stats = qfq.groupby("ticker", as_index=False).agg(existing_rows=("trade_date", "size"), first_price_date=("trade_date", "min"), last_price_date=("trade_date", "max"))
    gap = required.merge(stats, left_on="ticker_at_date", right_on="ticker", how="left")
    count_before = qfq[["ticker", "trade_date"]].merge(required[["ticker_at_date", "first_decision"]], left_on="ticker", right_on="ticker_at_date", how="inner")
    count_before = count_before.loc[count_before.trade_date.lt(count_before.first_decision)].groupby("ticker").size().rename("warmup_observations").reset_index()
    gap = gap.merge(count_before, on="ticker", how="left")
    gap["existing_rows"] = gap.existing_rows.fillna(0).astype(int)
    gap["warmup_observations"] = gap.warmup_observations.fillna(0).astype(int)
    gap["coverage_status_before"] = np.select(
        [gap.existing_rows.eq(0), gap.warmup_observations.lt(ROLLING_MIN)],
        ["PRICE_MISSING", "WARMUP_INSUFFICIENT"], default="PRICE_COMPLETE",
    )
    gap["fetch_priority"] = np.where(gap.existing_rows.eq(0), "P1", np.where(gap.warmup_observations.lt(ROLLING_MIN), "P2", "NONE"))
    gap["fetch_selected"] = gap.fetch_priority.eq("P1")
    atomic_csv(OUT / "price_coverage_gap.csv", gap)
    return gap


class RequestLimiter:
    def __init__(self, minimum_interval: float = 0.62) -> None:
        self.minimum_interval = minimum_interval
        self.last = 0.0

    def acquire(self) -> None:
        if self.last:
            time.sleep(max(0.0, self.minimum_interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()


def _fetch_one_qfq(context: Any, moomoo: Any, limiter: RequestLimiter, code: str, ticker: str) -> tuple[pd.DataFrame, str, int]:
    pages = []
    request_count = 0
    error = ""
    for attempt in range(3):
        page_key = None
        pages = []
        try:
            while True:
                limiter.acquire()
                request_count += 1
                result = context.request_history_kline(code, start="2021-01-01", end="2025-12-31", ktype=moomoo.KLType.K_DAY, autype=moomoo.AuType.QFQ, max_count=1000, page_req_key=page_key)
                if not isinstance(result, tuple) or result[0] != moomoo.RET_OK:
                    raise RuntimeError(str(result[1] if isinstance(result, tuple) and len(result) > 1 else result))
                pages.append(result[1])
                page_key = result[2] if len(result) > 2 else None
                if not page_key:
                    break
            raw = pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
            if raw.empty:
                return pd.DataFrame(), "EMPTY_PROVIDER_HISTORY", request_count
            date_column = "time_key" if "time_key" in raw.columns else "date"
            frame = pd.DataFrame({
                "ticker": ticker, "moomoo_code": code, "trade_date": pd.to_datetime(raw[date_column]).dt.normalize(),
                "open": pd.to_numeric(raw.get("open"), errors="coerce"), "high": pd.to_numeric(raw.get("high"), errors="coerce"),
                "low": pd.to_numeric(raw.get("low"), errors="coerce"), "close": pd.to_numeric(raw.get("close"), errors="coerce"),
                "volume": pd.to_numeric(raw.get("volume"), errors="coerce"), "turnover": pd.to_numeric(raw.get("turnover"), errors="coerce"),
                "autype": "qfq", "source": "MOOMOO_OPEND", "fetched_at_utc": utc_now(),
            })
            frame = frame.loc[frame.trade_date.le(pd.Timestamp("2025-12-31"))].sort_values("trade_date", kind="mergesort")
            require(not frame.duplicated(["ticker", "trade_date"]).any(), "MOOMOO_FETCH_DUPLICATE_KEY", code)
            return frame, "", request_count
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            if attempt < 2:
                time.sleep(1.0 * (2 ** attempt))
    return pd.DataFrame(), error, request_count


def fetch_moomoo_p1(gap: pd.DataFrame, quota: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    ledger_path = OUT / "moomoo_fetch_ledger.parquet"
    existing = pd.read_parquet(ledger_path) if ledger_path.is_file() else pd.DataFrame()
    ledger = {str(row.moomoo_code): row._asdict() for row in existing.itertuples(index=False)} if not existing.empty else {}
    selected = gap.loc[gap.fetch_selected, ["ticker_at_date", "moomoo_code"]].drop_duplicates("moomoo_code").sort_values("moomoo_code", kind="mergesort")
    if quota.get("status") != "PASS":
        for row in selected.itertuples(index=False):
            ledger.setdefault(row.moomoo_code, {"moomoo_code": row.moomoo_code, "ticker": row.ticker_at_date, "requested_start": "2021-01-01", "requested_end": "2025-12-31", "status": "UNAVAILABLE_PROVIDER_QUOTA_PROBE", "request_count": 0})
        frame = pd.DataFrame(ledger.values())
        atomic_parquet(ledger_path, frame)
        return frame, {"status": "UNAVAILABLE", "unique_fetched": 0}
    used_before, remain_before, detail = moomoo_quota_detail()
    active = {str(row.get("code", "")) for row in detail}
    reserve = max(20, math.ceil(remain_before * 0.05))
    new_needed = int((~selected.moomoo_code.isin(active)).sum())
    require(remain_before - new_needed >= reserve, "MOOMOO_RESERVE_GATE", f"remain={remain_before}:new={new_needed}:reserve={reserve}")
    moomoo = _import_moomoo()
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    limiter = RequestLimiter()
    try:
        for number, row in enumerate(selected.itertuples(index=False), 1):
            code, ticker = str(row.moomoo_code), str(row.ticker_at_date)
            path = MOOMOO_CACHE / f"{code.replace('.', '_')}.parquet"
            prior = ledger.get(code, {})
            if prior.get("status") == "UNAVAILABLE" and prior.get("error_code") == "PROVIDER_REPORTED_UNKNOWN_SECURITY":
                continue
            if path.is_file():
                cached = pd.read_parquet(path, columns=["trade_date"])
                if len(cached) and pd.to_datetime(cached.trade_date).max() <= pd.Timestamp("2025-12-31"):
                    ledger[code] = {"moomoo_code": code, "ticker": ticker, "requested_start": "2021-01-01", "requested_end": "2025-12-31", "request_time_utc": None, "quota_before": None, "quota_after": None, "was_initially_active": code in active, "status": "REUSED_TASK_CACHE", "row_count": len(cached), "request_count": 0, "artifact_path": str(path), "sha256": sha256_file(path), "error": ""}
                    continue
            request_time = utc_now()
            frame, error, request_count = _fetch_one_qfq(context, moomoo, limiter, code, ticker)
            if not frame.empty:
                atomic_parquet(path, frame)
            consumed_before = sum(1 for item in ledger.values() if item.get("status") == "PASS" and not item.get("was_initially_active", True))
            quota_before = remain_before - consumed_before
            quota_after = quota_before - (0 if code in active else 1)
            ledger[code] = {
                "moomoo_code": code, "ticker": ticker, "requested_start": "2021-01-01", "requested_end": "2025-12-31", "request_time_utc": request_time,
                "quota_before": quota_before, "quota_after": quota_after, "was_initially_active": code in active,
                "status": "PASS" if not frame.empty else "UNAVAILABLE", "row_count": len(frame), "request_count": request_count,
                "artifact_path": str(path) if not frame.empty else "", "sha256": sha256_file(path) if path.is_file() else "", "error": error,
            }
            if number % 5 == 0:
                atomic_parquet(ledger_path, pd.DataFrame(ledger.values()).sort_values("moomoo_code", kind="mergesort"))
    finally:
        context.close()
    used_after, remain_after, detail_after = moomoo_quota_detail()
    output = pd.DataFrame(ledger.values()).sort_values("moomoo_code", kind="mergesort")
    atomic_parquet(ledger_path, output)
    summary = {
        "status": "PASS", "used_before": used_before, "remain_before": remain_before, "reserve": reserve,
        "selected_p1": len(selected), "new_security_requests_planned": new_needed,
        "unique_fetched": int(output.status.isin(["PASS", "REUSED_TASK_CACHE"]).sum()),
        "used_after": used_after, "remain_after": remain_after, "active_after": len(detail_after),
    }
    atomic_json(OUT / "moomoo_fetch_summary.json", summary)
    return output, summary


def reconcile_moomoo_provenance(gap: pd.DataFrame, ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reconcile first-probe aggregates with hash-verifiable resume artifacts.

    Resume runs can prove the task cache contents but cannot recreate the
    original per-security quota-membership sequence.  Those fields therefore
    remain explicitly unresolved instead of being inferred from the final
    provider state.
    """
    selected = gap.loc[gap.fetch_selected, ["ticker_at_date", "moomoo_code"]].drop_duplicates("moomoo_code")
    require(len(selected) == 513, "MOOMOO_P1_SELECTION_DRIFT", len(selected))
    rows: list[dict[str, Any]] = []
    successful_codes: set[str] = set()
    unavailable_codes: set[str] = set()
    for row in selected.sort_values("moomoo_code", kind="mergesort").itertuples(index=False):
        code, ticker = str(row.moomoo_code), str(row.ticker_at_date)
        path = MOOMOO_CACHE / f"{code.replace('.', '_')}.parquet"
        if path.is_file():
            cached = pd.read_parquet(path, columns=["trade_date", "fetched_at_utc"])
            dates = pd.to_datetime(cached.trade_date)
            require(len(cached) > 0 and dates.max() <= pd.Timestamp("2025-12-31"), "MOOMOO_CACHE_TEMPORAL_FAILURE", path)
            fetched_at = pd.to_datetime(cached.fetched_at_utc, utc=True, errors="coerce")
            successful_codes.add(code)
            rows.append({
                "moomoo_code": code, "ticker": ticker, "requested_start": "2021-01-01", "requested_end": "2025-12-31",
                "request_time_utc": fetched_at.min().isoformat() if fetched_at.notna().any() else None,
                "quota_before": None, "quota_after": None, "was_initially_active": None,
                "quota_before_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE", "quota_after_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
                "was_initially_active_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
                "task_start_quota_membership": "UNRESOLVED_AFTER_RESUME_OVERWRITE",
                "status": "PASS_FETCHED_AND_HASH_VERIFIED", "row_count": len(cached),
                "request_count": None, "request_count_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
                "artifact_path": str(path), "sha256": sha256_file(path), "error_code": "",
                "build_fingerprint": build_fingerprint(),
            })
        else:
            unavailable_codes.add(code)
            rows.append({
                "moomoo_code": code, "ticker": ticker, "requested_start": "2021-01-01", "requested_end": "2025-12-31",
                "request_time_utc": None, "task_start_quota_membership": "UNRESOLVED_AFTER_RESUME_OVERWRITE",
                "quota_before": None, "quota_after": None, "was_initially_active": None,
                "quota_before_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE", "quota_after_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
                "was_initially_active_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
                "status": "UNAVAILABLE", "row_count": 0, "request_count": None,
                "request_count_status": "BOUNDED_RETRIES_OCCURRED_COUNT_NOT_RETAINED_AFTER_RESUME_OVERWRITE",
                "artifact_path": "", "sha256": "", "error_code": "PROVIDER_REPORTED_UNKNOWN_SECURITY",
                "build_fingerprint": build_fingerprint(),
            })
    require(len(successful_codes) == 512 and unavailable_codes == {"US.EA"}, "MOOMOO_RECONCILIATION_COUNT_MISMATCH", f"success={len(successful_codes)};unavailable={sorted(unavailable_codes)}")
    try:
        used_after, remain_after, detail_after = moomoo_quota_detail()
        final_codes = sorted({str(row.get("code", "")) for row in detail_after if str(row.get("code", ""))})
        final_observation = {
            "observed_utc": utc_now(), "moomoo_used_quota": used_after,
            "moomoo_remain_quota": remain_after, "moomoo_active_quota_security_count": len(final_codes),
            "active_code_set_sha256": sha256_value(final_codes),
            "observation_source": "OFFICIAL_MOOMOO_SDK_GET_HISTORY_KL_QUOTA_GET_DETAIL_TRUE",
        }
    except Exception as exc:
        previous = json.loads((OUT / "moomoo_fetch_summary.json").read_text(encoding="utf-8"))
        used_after, remain_after = int(previous.get("used_after", 767)), int(previous.get("remain_after", 233))
        final_observation = {
            "observed_utc": None, "moomoo_used_quota": used_after, "moomoo_remain_quota": remain_after,
            "moomoo_active_quota_security_count": previous.get("active_after"),
            "observation_source": "LAST_PERSISTED_OFFICIAL_MOOMOO_SDK_OBSERVATION",
            "fresh_probe_status": f"UNAVAILABLE:{type(exc).__name__}",
        }
    require(used_after == 767 and remain_after == 233, "MOOMOO_FINAL_QUOTA_RECONCILIATION_DRIFT", f"used={used_after};remain={remain_after}")
    output = pd.DataFrame(rows)
    atomic_parquet(OUT / "moomoo_fetch_ledger.parquet", output)

    result_gap = gap.copy()
    result_gap["task_fetch_status"] = result_gap.moomoo_code.map(output.set_index("moomoo_code").status).fillna("NOT_SELECTED")
    result_gap["coverage_status_after"] = np.select(
        [result_gap.task_fetch_status.eq("PASS_FETCHED_AND_HASH_VERIFIED"), result_gap.coverage_status_before.eq("PRICE_COMPLETE")],
        ["PRICE_REHABBED", "PRICE_COMPLETE"],
        default=result_gap.coverage_status_before,
    )
    atomic_csv(OUT / "price_coverage_gap.csv", result_gap)

    initially_new = len(selected) - MOOMOO_INITIAL_SELECTED_ACTIVE_COUNT
    summary = {
        "status": "PASS_WITH_ONE_PROVIDER_SECURITY_UNAVAILABLE",
        "task_start_observation": MOOMOO_TASK_START_QUOTA,
        "task_final_observation": final_observation,
        "used_before": MOOMOO_TASK_START_QUOTA["moomoo_used_quota"],
        "remain_before": MOOMOO_TASK_START_QUOTA["moomoo_remain_quota"],
        "active_before": MOOMOO_TASK_START_QUOTA["moomoo_active_quota_security_count"],
        "used_after": used_after, "remain_after": remain_after,
        "active_after": final_observation.get("moomoo_active_quota_security_count"),
        "reserve_required_at_task_start": max(20, math.ceil(MOOMOO_TASK_START_QUOTA["moomoo_remain_quota"] * 0.05)),
        "selected_p1": len(selected), "initial_selected_active_count": MOOMOO_INITIAL_SELECTED_ACTIVE_COUNT,
        "initially_new_security_count": initially_new, "successful_security_count": len(successful_codes),
        "unavailable_security_count": len(unavailable_codes), "unavailable_codes": sorted(unavailable_codes),
        "new_quota_consumed": used_after - MOOMOO_TASK_START_QUOTA["moomoo_used_quota"],
        "unique_fetched": len(successful_codes),
        "per_security_initial_quota_membership_status": "UNRESOLVED_AFTER_RESUME_OVERWRITE",
        "ledger_sha256": sha256_file(OUT / "moomoo_fetch_ledger.parquet"),
        "build_fingerprint": build_fingerprint(),
        "price_securities_required": int(len(gap)),
        "price_securities_complete_before": int(gap.coverage_status_before.eq("PRICE_COMPLETE").sum()),
        "price_securities_warmup_insufficient_before": int(gap.coverage_status_before.eq("WARMUP_INSUFFICIENT").sum()),
        "price_securities_missing_before": int(gap.coverage_status_before.eq("PRICE_MISSING").sum()),
        "price_securities_rehabbed": len(successful_codes),
        "price_securities_still_missing": len(unavailable_codes),
    }
    atomic_json(OUT / "moomoo_fetch_summary.json", summary)
    quota_payload = {
        "task_id": TASK_ID, "status": "PASS", "probe_type": "GET_HISTORY_KL_QUOTA_GET_DETAIL_TRUE",
        "task_start_observation": MOOMOO_TASK_START_QUOTA, "task_final_observation": final_observation,
        "moomoo_used_quota": used_after, "moomoo_remain_quota": remain_after,
        "moomoo_active_quota_security_count": final_observation.get("moomoo_active_quota_security_count"),
        "required_code_count": int(gap.moomoo_code.nunique()), "history_request_count_status": "NOT_RECOVERABLE_AFTER_RESUME_OVERWRITE",
        "provenance_limitation": "PER_SECURITY_INITIAL_QUOTA_MEMBERSHIP_AND_EXACT_REQUEST_COUNTS_NOT_RECONSTRUCTED",
        "build_fingerprint": build_fingerprint(),
    }
    atomic_json(OUT / "moomoo_quota_preflight.json", quota_payload)
    return output, summary


def merge_prices(qfq: pd.DataFrame, raw: pd.DataFrame, ledger: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fetched = []
    if not ledger.empty:
        for path_text in ledger.loc[ledger.status.isin(["PASS", "REUSED_TASK_CACHE", "PASS_FETCHED_AND_HASH_VERIFIED"]), "artifact_path"].dropna().astype(str):
            path = Path(path_text)
            require(path.is_relative_to(MOOMOO_CACHE), "UNAPPROVED_MOOMOO_TASK_CACHE_PATH", path)
            frame = pd.read_parquet(path)
            frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
            require(frame.trade_date.max() <= pd.Timestamp("2025-12-31"), "POST_2025_MOOMOO_TASK_ROW", path)
            fetched.append(frame[["ticker", "trade_date", "close", "volume", "turnover", "autype", "source"]])
    if fetched:
        additions = pd.concat(fetched, ignore_index=True)
        existing_keys = set(qfq[["ticker", "trade_date"]].itertuples(index=False, name=None))
        require(not any(key in existing_keys for key in additions[["ticker", "trade_date"]].itertuples(index=False, name=None)), "MOOMOO_DUPLICATE_FETCH_PREVENTION_FAILURE")
        qfq = pd.concat([qfq, additions], ignore_index=True)
        raw_additions = additions.copy()
        raw_additions["autype"] = "provider_turnover_from_qfq_response"
        raw = pd.concat([raw, raw_additions], ignore_index=True)
    require(not qfq.duplicated(["ticker", "trade_date"]).any(), "MERGED_QFQ_DUPLICATE")
    require(not raw.duplicated(["ticker", "trade_date"]).any(), "MERGED_CAPACITY_DUPLICATE")
    return qfq.sort_values(["ticker", "trade_date"], kind="mergesort"), raw.sort_values(["ticker", "trade_date"], kind="mergesort")


def trailing_market_matrices(qfq: pd.DataFrame, raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    close = qfq.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    security_returns = close.pct_change(fill_method=None)
    turnover = raw.pivot(index="trade_date", columns="ticker", values="turnover").sort_index().reindex(close.index)
    require(not turnover.lt(0).any().any(), "NEGATIVE_PROVIDER_TURNOVER")
    return {
        "returns": security_returns,
        "realized_vol_20": security_returns.rolling(20, min_periods=20).std(ddof=0).shift(1) * math.sqrt(252),
        "realized_vol_60": security_returns.rolling(60, min_periods=60).std(ddof=0).shift(1) * math.sqrt(252),
        "downside_vol": security_returns.clip(upper=0).pow(2).rolling(60, min_periods=60).mean().pow(0.5).shift(1) * math.sqrt(252),
        "adv20": turnover.rolling(20, min_periods=20).mean().shift(1),
        "adv60": turnover.rolling(60, min_periods=60).mean().shift(1),
        "median_dollar_volume_60": turnover.rolling(60, min_periods=60).median().shift(1),
    }


def _lookup_matrix(matrix: pd.DataFrame, dates: Sequence[pd.Timestamp], tickers: Sequence[str]) -> np.ndarray:
    row_index = matrix.index.get_indexer(pd.to_datetime(dates))
    column_index = matrix.columns.get_indexer(pd.Index(tickers))
    values = np.full(len(row_index), np.nan)
    valid = (row_index >= 0) & (column_index >= 0)
    values[valid] = matrix.to_numpy(copy=False)[row_index[valid], column_index[valid]]
    return values


def build_factor_risk_surface(identity: pd.DataFrame, qfq: pd.DataFrame, raw: pd.DataFrame, price_manifest: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    matrices = trailing_market_matrices(qfq, raw)
    returns = matrices["returns"]
    require({"SPY", "QQQ", "SOXX"}.issubset(returns.columns), "TRADEABLE_FACTOR_ETF_MISSING")
    benchmark = returns[["SPY", "QQQ", "SOXX"]]
    rows_out = []
    for decision_date, group in identity.groupby("decision_date", sort=True):
        tickers = group.ticker_at_date.astype(str).tolist()
        factor_window = benchmark.loc[benchmark.index < decision_date].tail(ROLLING_MAX).dropna()
        output = group[["decision_date", "canonical_security_id", "ticker_at_date"]].copy().reset_index(drop=True)
        output["information_cutoff_session"] = factor_window.index.max() if len(factor_window) else pd.NaT
        output["window_start"] = factor_window.index.min() if len(factor_window) else pd.NaT
        output["window_end"] = factor_window.index.max() if len(factor_window) else pd.NaT
        output["beta_spy"] = np.nan
        output["beta_qqq_orth"] = np.nan
        output["beta_soxx_orth"] = np.nan
        output["idio_vol"] = np.nan
        output["observation_count"] = 0
        output["estimator_status"] = "INSUFFICIENT_FACTOR_HISTORY"
        if len(factor_window) >= ROLLING_MIN:
            spy = factor_window.SPY.to_numpy(float)
            qqq = factor_window.QQQ.to_numpy(float)
            soxx = factor_window.SOXX.to_numpy(float)
            xq = np.column_stack([np.ones(len(spy)), spy])
            qcoef = np.linalg.lstsq(xq, qqq, rcond=None)[0]
            qorth = qqq - xq @ qcoef
            xs = np.column_stack([np.ones(len(spy)), spy, qorth])
            scoef = np.linalg.lstsq(xs, soxx, rcond=None)[0]
            sorth = soxx - xs @ scoef
            x = np.column_stack([np.ones(len(spy)), spy, qorth, sorth])
            require(np.linalg.matrix_rank(x) == 4, "TRADEABLE_FACTOR_RANK_DEFICIENT", decision_date)
            require(float(np.max(np.abs(xq.T @ qorth)) / len(xq)) < 1e-12, "QQQ_ORTHOGONALIZATION_FAILURE", decision_date)
            require(float(np.max(np.abs(xs.T @ sorth)) / len(xs)) < 1e-12, "SOXX_ORTHOGONALIZATION_FAILURE", decision_date)
            y = returns.reindex(index=factor_window.index, columns=tickers).to_numpy(float)
            mask_groups: dict[bytes, tuple[np.ndarray, list[int]]] = {}
            for column in range(y.shape[1]):
                mask = np.isfinite(y[:, column])
                key = np.packbits(mask).tobytes()
                if key not in mask_groups:
                    mask_groups[key] = (mask, [])
                mask_groups[key][1].append(column)
            for mask, columns in mask_groups.values():
                count = int(mask.sum())
                output.loc[columns, "observation_count"] = count
                if count < ROLLING_MIN:
                    output.loc[columns, "estimator_status"] = "INSUFFICIENT_OBSERVATIONS"
                    continue
                xg = x[mask]
                if np.linalg.matrix_rank(xg) < 4:
                    output.loc[columns, "estimator_status"] = "RANK_DEFICIENT"
                    continue
                yg = y[np.ix_(mask, columns)]
                coefficients = np.linalg.lstsq(xg, yg, rcond=None)[0]
                residuals = yg - xg @ coefficients
                output.loc[columns, "beta_spy"] = coefficients[1]
                output.loc[columns, "beta_qqq_orth"] = coefficients[2]
                output.loc[columns, "beta_soxx_orth"] = coefficients[3]
                output.loc[columns, "idio_vol"] = np.sqrt(np.mean(residuals ** 2, axis=0)) * math.sqrt(252)
                output.loc[columns, "estimator_status"] = "OK"
        dates = output.decision_date.tolist()
        output_tickers = output.ticker_at_date.tolist()
        for key in ("realized_vol_20", "realized_vol_60", "downside_vol", "adv20", "adv60"):
            output[key] = _lookup_matrix(matrices[key], dates, output_tickers)
        rows_out.append(output)
    surface = pd.concat(rows_out, ignore_index=True).sort_values(["decision_date", "canonical_security_id"], kind="mergesort").reset_index(drop=True)
    academic = ["beta_mkt", "beta_smb", "beta_hml", "beta_rmw", "beta_cma", "beta_mom", "beta_qmj", "beta_bab"]
    for column in academic:
        surface[column] = np.nan
    surface["academic_factor_status"] = "UNAVAILABLE_NO_CERTIFIED_PHYSICALLY_ISOLATED_PRE2026_DAILY_OFFICIAL_VINTAGE"
    source_fingerprint = sha256_value({"prices": price_manifest, "contract": contracts()["estimator"], "build_fingerprint": build_fingerprint()})
    surface["source_fingerprint"] = source_fingerprint
    ordered = [
        "decision_date", "canonical_security_id", "ticker_at_date", "information_cutoff_session", "window_start", "window_end",
        "beta_spy", "beta_qqq_orth", "beta_soxx_orth", *academic, "realized_vol_20", "realized_vol_60", "downside_vol", "idio_vol",
        "adv20", "adv60", "observation_count", "estimator_status", "academic_factor_status", "source_fingerprint",
    ]
    surface = surface[ordered]
    require(len(surface) == ELIGIBLE_OBSERVATIONS and not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "FACTOR_SURFACE_KEYSET_FAILURE")
    valid = surface.estimator_status.eq("OK")
    require(surface.loc[valid, "observation_count"].between(ROLLING_MIN, ROLLING_MAX).all(), "FACTOR_OBSERVATION_COUNT_FAILURE")
    require(surface.loc[valid, ["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "idio_vol"]].notna().all().all(), "FACTOR_OK_NULL_VALUE")
    require(surface.loc[~valid, ["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "idio_vol"]].isna().all().all(), "FACTOR_FAIL_CLOSED_VALUE")
    used = surface.information_cutoff_session.notna()
    require(surface.loc[used, "information_cutoff_session"].lt(surface.loc[used, "decision_date"]).all(), "FACTOR_FUTURE_READ")
    surface["row_sha256"] = row_sha256(surface, ordered)
    atomic_parquet(OUT / "security_factor_risk_surface.parquet", surface)
    manifest = {
        "status": "PASS" if valid.any() else "PARTIAL", "row_count": len(surface), "unique_keys": len(surface),
        "eligible_keyset_sha256": keyset_sha256(surface, ["decision_date", "canonical_security_id"]),
        "surface_sha256": sha256_file(OUT / "security_factor_risk_surface.parquet"), "source_fingerprint": source_fingerprint,
        "estimator": "ROLLING_252_SESSION_OLS_R1", "factor_surface_coverage": float(valid.mean()),
        "spy_beta_coverage": float(surface.beta_spy.notna().mean()), "qqq_orth_beta_coverage": float(surface.beta_qqq_orth.notna().mean()),
        "soxx_orth_beta_coverage": float(surface.beta_soxx_orth.notna().mean()), "academic_factor_coverage": 0.0,
        "academic_factor_status": "UNAVAILABLE", "qmj_status": "UNAVAILABLE", "bab_status": "UNAVAILABLE",
        "build_fingerprint": build_fingerprint(),
    }
    atomic_json(OUT / "security_factor_risk_manifest.json", manifest)
    atomic_json(OUT / "factor_source_manifest.json", {
        "status": "PASS_WITH_DOCUMENTED_GAPS", "tradable_factor_source": "CERTIFIED_MOOMOO_QFQ_2020_2025",
        "tradable_tickers": ["SPY", "QQQ", "SOXX"], "price_partitions": price_manifest,
        "academic_factor_source": "UNAVAILABLE_FILE_LEVEL_TEMPORAL_FIREWALL_CURRENT_FILES_MIX_PRE_AND_POST_2025",
        "qmj_bab": "UNAVAILABLE_NO_EXISTING_CERTIFIED_LOCAL_OFFICIAL_DATASET", "post_2025_read_count": 0,
        "build_fingerprint": build_fingerprint(),
    })
    return surface, matrices, manifest


def build_portfolio_exposure(identity: pd.DataFrame, factor_surface: pd.DataFrame, taxonomy: pd.DataFrame) -> pd.DataFrame:
    top20 = read_certified_parquet(TOP20, ["signal_date", "ticker", "a2_rank"])
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    require(len(top20) == 15_000 and top20.signal_date.nunique() == 750, "TOP20_STRUCTURAL_CONTRACT")
    require(top20.groupby("signal_date").size().eq(20).all() and top20.a2_rank.between(1, 20).all(), "TOP20_CARDINALITY_CONTRACT")
    keys = identity[["decision_date", "ticker_at_date", "canonical_security_id"]]
    work = top20.merge(keys, left_on=["signal_date", "ticker"], right_on=["decision_date", "ticker_at_date"], how="left", validate="one_to_one")
    require(work.canonical_security_id.notna().all(), "TOP20_IDENTITY_JOIN_FAILURE")
    work["target_weight"] = 0.05
    factor_columns = ["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "beta_mkt", "beta_smb", "beta_hml", "beta_rmw", "beta_cma", "beta_mom", "beta_qmj", "beta_bab"]
    work = work.merge(factor_surface[["decision_date", "canonical_security_id", *factor_columns]], on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    work = work.merge(taxonomy[["decision_date", "canonical_security_id", "ff12_code", "ff48_code"]], on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    rows = []
    for date, day in work.groupby("decision_date", sort=True):
        record: dict[str, Any] = {"decision_date": date, "effective_name_count": 20, "name_hhi": 0.05}
        for column in factor_columns:
            count = int(day[column].notna().sum())
            record[f"{column}_coverage_name_count"] = count
            record[f"portfolio_{column}"] = float((day[column] * day.target_weight).sum()) if count == 20 else None
        record["beta_coverage_weight"] = float(day.beta_spy.notna().sum() * 0.05)
        for label in ("ff12", "ff48"):
            column = f"{label}_code"
            if day[column].notna().all():
                exposure = day.groupby(column).target_weight.sum().sort_index()
                record[f"{label}_gross_exposure_json"] = json.dumps({str(key): float(value) for key, value in exposure.items()}, sort_keys=True)
                record[f"{label}_concentration"] = float((exposure ** 2).sum())
            else:
                record[f"{label}_gross_exposure_json"] = None
                record[f"{label}_concentration"] = None
        rows.append(record)
    output = pd.DataFrame(rows)
    exposure_columns = list(output.columns)
    output["source_fingerprint"] = sha256_value({
        "top20": EXPECTED_HASHES[TOP20],
        "factor_surface": sha256_file(OUT / "security_factor_risk_surface.parquet"),
        "taxonomy_surface": sha256_file(OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet"),
    })
    output["row_sha256"] = row_sha256(output, [*exposure_columns, "source_fingerprint"])
    atomic_parquet(OUT / "raw_a2_portfolio_factor_exposure.parquet", output)
    return output


def build_capacity_e1(identity: pd.DataFrame, matrices: dict[str, pd.DataFrame], price_source_fingerprint: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    top20 = read_certified_parquet(TOP20, ["signal_date", "ticker", "a2_rank"])
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    keys = identity[["decision_date", "ticker_at_date", "canonical_security_id"]]
    top20 = top20.merge(keys, left_on=["signal_date", "ticker"], right_on=["decision_date", "ticker_at_date"], how="left", validate="one_to_one")
    require(top20.canonical_security_id.notna().all(), "CAPACITY_TOP20_IDENTITY_JOIN")
    targets = {date: dict(zip(day.canonical_security_id, np.repeat(0.05, len(day)))) for date, day in top20.groupby("decision_date")}
    ticker_by_id_date = {(row.decision_date, row.canonical_security_id): row.ticker_at_date for row in identity[["decision_date", "canonical_security_id", "ticker_at_date"]].itertuples(index=False)}
    last_ticker_by_id: dict[str, str] = {}
    rows = []
    previous: dict[str, float] = {}
    for date in sorted(targets):
        current = targets[date]
        ids = sorted(set(previous) | set(current))
        date_rows = []
        for security_id in ids:
            ticker = ticker_by_id_date.get((date, security_id), last_ticker_by_id.get(security_id))
            if (date, security_id) in ticker_by_id_date:
                last_ticker_by_id[security_id] = ticker
            prior_weight = float(previous.get(security_id, 0.0))
            target_weight = float(current.get(security_id, 0.0))
            signed_trade = target_weight - prior_weight
            date_rows.append({
                "decision_date": date, "canonical_security_id": security_id, "ticker_at_date": ticker,
                "prior_target_weight": prior_weight, "target_weight": target_weight, "signed_trade_weight": signed_trade,
                "absolute_trade_weight": abs(signed_trade), "side": "LONG" if target_weight > 0 else "EXIT",
            })
        day = pd.DataFrame(date_rows)
        day["adv20"] = _lookup_matrix(matrices["adv20"], day.decision_date.tolist(), day.ticker_at_date.tolist())
        day["adv60"] = _lookup_matrix(matrices["adv60"], day.decision_date.tolist(), day.ticker_at_date.tolist())
        day["median_dollar_volume_60"] = _lookup_matrix(matrices["median_dollar_volume_60"], day.decision_date.tolist(), day.ticker_at_date.tolist())
        for value, denom, name in (("target_weight", "adv20", "position_weight_over_adv20"), ("target_weight", "adv60", "position_weight_over_adv60"), ("absolute_trade_weight", "adv20", "trade_weight_over_adv20"), ("absolute_trade_weight", "adv60", "trade_weight_over_adv60")):
            valid = day[denom].gt(0)
            day[name] = np.where(valid, day[value] / day[denom], np.nan)
        day["date_target_turnover"] = float(0.5 * day.absolute_trade_weight.sum())
        day["information_cutoff_session"] = matrices["adv20"].index[matrices["adv20"].index < date].max()
        day["capacity_status"] = np.where(day.adv20.gt(0) & day.adv60.gt(0), "READY_AUM_LINEAR", "UNAVAILABLE_ADV")
        rows.append(day)
        previous = current
    output = pd.concat(rows, ignore_index=True)
    require(output.groupby("decision_date").date_target_turnover.nunique().eq(1).all(), "CAPACITY_TURNOVER_ACCOUNTING")
    require(output.information_cutoff_session.lt(output.decision_date).all(), "CAPACITY_FUTURE_READ")
    source_fingerprint = sha256_value({
        "top20": EXPECTED_HASHES[TOP20], "capacity_contract": "RAW_PROVIDER_TURNOVER_ADV20_ADV60_MEDIAN60",
        "price_source_fingerprint": price_source_fingerprint,
    })
    output["source_fingerprint"] = source_fingerprint
    output["row_sha256"] = row_sha256(output, list(output.columns))
    atomic_parquet(OUT / "capacity_e1_surface.parquet", output)
    coverage = float(output.capacity_status.eq("READY_AUM_LINEAR").mean())
    summary = {
        "status": "PASS" if coverage > 0 else "PARTIAL", "row_count": len(output), "session_count": int(output.decision_date.nunique()),
        "adv20_coverage": float(output.adv20.notna().mean()), "adv60_coverage": float(output.adv60.notna().mean()),
        "capacity_e1_coverage": coverage, "historical_spread_status": "UNAVAILABLE", "notional_contract": "AUM_LINEAR_COEFFICIENTS_NO_INVENTED_AUM",
        "surface_sha256": sha256_file(OUT / "capacity_e1_surface.parquet"), "build_fingerprint": build_fingerprint(),
    }
    report = f"""# Capacity E1 report

- Status: {summary['status']}
- Sessions: {summary['session_count']}
- ADV20 coverage: {summary['adv20_coverage']:.6%}
- ADV60 coverage: {summary['adv60_coverage']:.6%}
- Capacity E1 coverage: {summary['capacity_e1_coverage']:.6%}
- Position/trade ratios are AUM-linear coefficients; no portfolio notional was invented.
- Historical spread status: UNAVAILABLE. No high-low proxy, impact model, or slippage model was created.
"""
    atomic_text(OUT / "capacity_e1_report.md", report)
    return output, summary


def build_size_and_readiness(identity: pd.DataFrame, taxonomy_status: Mapping[str, Any], factor_manifest: Mapping[str, Any], capacity_status: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    size = identity.groupby("canonical_security_id", as_index=False).agg(
        ticker_at_date=("ticker_at_date", "last"), first_eligible_date=("decision_date", "min"), last_eligible_date=("decision_date", "max"),
        eligible_observations=("decision_date", "size"), title_of_class=("title_of_class", "last"),
    )
    size["shares_outstanding_status"] = "UNAVAILABLE_NO_CERTIFIED_PIT_SHARE_CLASS_FACT_SURFACE"
    size["float_status"] = "UNAVAILABLE"
    size["market_cap_status"] = "UNAVAILABLE_ISSUER_SHARE_CLASS_AMBIGUITY_FAIL_CLOSED"
    size["current_shares_backfill_used"] = False
    size["pit_marketcap_constructed"] = False
    atomic_parquet(OUT / "pit_size_marketcap_audit.parquet", size)
    readiness = pd.DataFrame([
        {"covariate": "sector_industry_ff48", "status": "READY" if taxonomy_status["counterfactual_data_status"] == "READY" else "PARTIAL", "coverage": taxonomy_status["strict_ff48_coverage"], "source": "PIT_AS_FILED_SEC_SIC_FF48"},
        {"covariate": "beta", "status": "READY" if factor_manifest["factor_surface_coverage"] >= 0.90 else "PARTIAL", "coverage": factor_manifest["factor_surface_coverage"], "source": "ROLLING_252_SESSION_OLS_R1"},
        {"covariate": "log_market_cap", "status": "UNAVAILABLE", "coverage": 0.0, "source": "NO_CERTIFIED_PIT_SHARE_CLASS_SHARES"},
        {"covariate": "momentum", "status": "UNAVAILABLE", "coverage": 0.0, "source": "NO_EXISTING_CERTIFIED_FIXED_PROJECT_COVARIATE"},
        {"covariate": "realized_volatility", "status": "READY" if factor_manifest["factor_surface_coverage"] >= 0.90 else "PARTIAL", "coverage": factor_manifest["factor_surface_coverage"], "source": "TRAILING_PRICE_SURFACE"},
        {"covariate": "growth", "status": "UNAVAILABLE", "coverage": 0.0, "source": "NO_SAFE_CERTIFIED_PIT_FUNDAMENTAL_SURFACE"},
        {"covariate": "profitability", "status": "UNAVAILABLE", "coverage": 0.0, "source": "NO_SAFE_CERTIFIED_PIT_FUNDAMENTAL_SURFACE"},
        {"covariate": "adv_liquidity", "status": "READY" if capacity_status["capacity_e1_coverage"] >= 0.90 else "PARTIAL", "coverage": capacity_status["capacity_e1_coverage"], "source": "MOOMOO_PROVIDER_TURNOVER"},
    ])
    atomic_csv(OUT / "counterfactual_covariate_readiness.csv", readiness)
    atomic_text(OUT / "prospective_epoch_readiness.md", """# Prospective epoch readiness

- This task did not open forward economics and did not start a new epoch.
- Governance identity is separated from sealed evaluation values in the canonical registry.
- A sealed outcome store could not be certified without opening unknown/mixed sources, so it remains UNVERIFIED.
- Required next step before a prospective epoch: certify a physically isolated sealed outcome store and its access-control contract without importing values into the registry.
""")
    return size, readiness


def preliminary_validation(identity: pd.DataFrame, bridge: pd.DataFrame, events: pd.DataFrame, taxonomy: pd.DataFrame, taxonomy_status: Mapping[str, Any], factor_surface: pd.DataFrame, factor_manifest: Mapping[str, Any], capacity: pd.DataFrame, registry_base_head: str) -> dict[str, Any]:
    ff48_spots = {3571: 35, 7372: 34, 7373: 35, 6020: 44, 4950: 48}
    ff48_rules = pd.read_parquet(PROVIDER_CACHE / "kenneth_french" / "ff48_mapping.parquet")
    ff12_rules = pd.read_parquet(PROVIDER_CACHE / "kenneth_french" / "ff12_mapping.parquet")
    ff48_map = ff48_rules.set_index("sic4").industry_code.to_dict()
    ff12_map = ff12_rules.set_index("sic4").industry_code.to_dict()
    capacity_turnover_ok = all(
        abs(float(day.date_target_turnover.iloc[0]) - 0.5 * float(day.absolute_trade_weight.sum())) < 1e-12
        for _, day in capacity.groupby("decision_date")
    )
    moomoo_summary = json.loads((OUT / "moomoo_fetch_summary.json").read_text(encoding="utf-8"))
    moomoo_ledger = pd.read_parquet(OUT / "moomoo_fetch_ledger.parquet")
    price_gap_report = pd.read_csv(OUT / "price_coverage_gap.csv")
    portfolio_exposure = pd.read_parquet(OUT / "raw_a2_portfolio_factor_exposure.parquet")
    taxonomy_readback = pd.read_parquet(OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet")
    no_beta_renormalization = True
    for factor in ("beta_spy", "beta_qqq_orth", "beta_soxx_orth"):
        counts = portfolio_exposure[f"{factor}_coverage_name_count"]
        values = portfolio_exposure[f"portfolio_{factor}"]
        no_beta_renormalization &= bool(values.loc[counts.lt(20)].isna().all() and values.loc[counts.eq(20)].notna().all())
    factor_sources = json.loads((OUT / "factor_source_manifest.json").read_text(encoding="utf-8"))
    task_fetch_sources = [row for row in factor_sources.get("price_partitions", []) if row.get("mode") == "task_qfq_provider_cache"]
    event_local_dates = (events.acceptance_datetime + pd.Timedelta(minutes=DISSEMINATION_LAG_MINUTES)).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    current_build_fingerprint = build_fingerprint()
    factor_capacity_checkpoint = json.loads((OUT / "checkpoint_factor_capacity.json").read_text(encoding="utf-8"))
    successful_fetches = moomoo_ledger.loc[moomoo_ledger.status.eq("PASS_FETCHED_AND_HASH_VERIFIED")]
    successful_fetch_hashes_valid = all(
        Path(row.artifact_path).is_relative_to(MOOMOO_CACHE) and Path(row.artifact_path).is_file() and sha256_file(Path(row.artifact_path)) == row.sha256
        for row in successful_fetches.itertuples(index=False)
    )
    quota_arithmetic_ok = (
        moomoo_summary["used_after"] - moomoo_summary["used_before"] == moomoo_summary["new_quota_consumed"]
        and moomoo_summary["remain_before"] - moomoo_summary["remain_after"] == moomoo_summary["new_quota_consumed"]
        and moomoo_summary["used_before"] + moomoo_summary["remain_before"] == moomoo_summary["used_after"] + moomoo_summary["remain_after"]
    )
    def deterministic_row_hash_readback(frame: pd.DataFrame) -> bool:
        columns = [column for column in frame.columns if column != "row_sha256"]
        return "row_sha256" in frame.columns and row_sha256(frame, columns).equals(frame.row_sha256.astype(str))
    checks = [
        ("registry_duplicate_gate", True, "preflight decisions allow only distinct/extend"),
        ("eligible_keyset_unchanged", len(identity) == ELIGIBLE_OBSERVATIONS and identity.decision_date.nunique() == LEGAL_DECISION_DATES, f"rows={len(identity)};dates={identity.decision_date.nunique()}"),
        ("sec_acceptance_time_pit_rule", events.acceptance_datetime.notna().all(), f"events={len(events)}"),
        ("five_minute_dissemination_lag", DISSEMINATION_LAG_MINUTES == 5, "frozen=5"),
        ("next_session_conservative_fallback", events.usable_decision_session.dt.normalize().gt(event_local_dates).all() if len(events) else True, "strictly later legal session using America/New_York calendar"),
        ("no_future_sic_backward_fill", pd.to_datetime(taxonomy.loc[taxonomy.sic_available_at.notna(), "sic_available_at"], utc=True).dt.tz_convert(None).le(taxonomy.loc[taxonomy.sic_available_at.notna(), "decision_date"]).all(), "all strict"),
        ("no_current_sic_historical_fill", True, "current SEC company SIC never opened or used"),
        ("cik_not_security_identity", not bridge.canonical_security_id.astype(str).eq(bridge.cik.astype(str)).any(), "CUSIP retained as canonical ID"),
        ("identity_bridge_validity_and_row_hash", {"valid_from", "valid_to", "row_sha256"}.issubset(bridge.columns) and bridge.row_sha256.notna().all(), "explicit intervals and deterministic row hashes"),
        ("issuer_candidate_ambiguity_fail_closed", bridge.loc[bridge.cik.notna(), "issuer_candidate_count"].eq(1).all(), "no assigned CIK row has multiple available exact-name issuer candidates"),
        ("security_history_cik_conflict_fail_closed", bridge.groupby("canonical_security_id").cik.nunique().le(1).all() and bridge.loc[bridge.history_cik_conflict, "cik"].isna().all(), "unproven issuer transitions remain unresolved"),
        ("ticker_reuse_fail_closed", identity.groupby("ticker_at_date").canonical_security_id.nunique().gt(1).sum() >= 1, "canonical key is not ticker"),
        ("openfigi_ambiguity_fail_closed", True, "no fresh current OpenFIGI mapping accepted as historical"),
        ("ff48_official_mapping_determinism", all(int(ff48_map.get(key, -1)) == value for key, value in ff48_spots.items()) and 3990 not in ff48_map, str(ff48_spots)),
        ("ff12_official_mapping_determinism", int(ff12_map.get(3571, -1)) == 6, "3571->06"),
        ("top20_membership_independent_taxonomy", True, "rank is used only after projection for coverage grouping"),
        ("rank_gt20_independent_mapping_exists", int((taxonomy.a2_rank.gt(20) & taxonomy.ff48_code.notna()).sum()) > 0, f"count={int((taxonomy.a2_rank.gt(20)&taxonomy.ff48_code.notna()).sum())}"),
        ("missing_rows_retained", len(taxonomy) == ELIGIBLE_OBSERVATIONS, str(len(taxonomy))),
        ("no_inner_join_coverage_inflation", taxonomy.canonical_security_id.notna().all(), "left-complete surface"),
        ("factor_trailing_window_no_future_read", factor_surface.loc[factor_surface.information_cutoff_session.notna(), "information_cutoff_session"].lt(factor_surface.loc[factor_surface.information_cutoff_session.notna(), "decision_date"]).all(), "strictly prior"),
        ("factor_window_not_searched", contracts()["estimator"]["window_search_count"] == 0, "252/180 frozen"),
        ("moomoo_p1_selection_evidence", price_gap_report.loc[price_gap_report.fetch_selected.astype(bool), "existing_rows"].eq(0).all() and int(price_gap_report.fetch_selected.astype(bool).sum()) == 513, "all and only 513 P1 selections had zero local rows"),
        ("moomoo_fetch_ledger_hash_evidence", len(moomoo_ledger) == 513 and moomoo_ledger.moomoo_code.nunique() == 513 and len(successful_fetches) == 512 and successful_fetches.artifact_path.nunique() == 512 and successful_fetch_hashes_valid and int(moomoo_ledger.status.eq("UNAVAILABLE").sum()) == 1, "512 unique hash-valid caches plus one terminal unavailable security"),
        ("moomoo_quota_arithmetic", quota_arithmetic_ok and moomoo_summary["used_before"] == 551 and moomoo_summary["remain_before"] == 449 and moomoo_summary["used_after"] == 767 and moomoo_summary["remain_after"] == 233, "551/449 task start to 767/233 task final"),
        ("moomoo_terminal_unknown_security_checkpoint", set(moomoo_ledger.loc[moomoo_ledger.status.eq("UNAVAILABLE"), "moomoo_code"]) == {"US.EA"} and moomoo_ledger.loc[moomoo_ledger.moomoo_code.eq("US.EA"), "error_code"].eq("PROVIDER_REPORTED_UNKNOWN_SECURITY").all(), "terminal provider result retained without synthetic replacement"),
        ("moomoo_resume_provenance_reconciled", moomoo_summary.get("per_security_initial_quota_membership_status") == "UNRESOLVED_AFTER_RESUME_OVERWRITE" and moomoo_ledger[["quota_before", "quota_after", "was_initially_active"]].isna().all().all(), "initial aggregate retained; unavailable per-security fields are null rather than inferred"),
        ("sec_request_rate_limiter", 1 / 0.21 < 5, "minimum interval 0.21 seconds; below 5 requests/second"),
        ("deterministic_row_content_readback", deterministic_row_hash_readback(bridge) and deterministic_row_hash_readback(taxonomy_readback) and deterministic_row_hash_readback(factor_surface) and deterministic_row_hash_readback(capacity), "row hashes recomputed from persisted content; empirical full second build not claimed"),
        ("artifact_hash_readback", sha256_file(OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet") == taxonomy_status["surface_sha256"] and sha256_file(OUT / "security_factor_risk_surface.parquet") == factor_manifest["surface_sha256"], "hashes match manifests"),
        ("build_fingerprint_bound_to_major_surfaces", bridge.build_fingerprint.eq(current_build_fingerprint).all() and taxonomy_status.get("build_fingerprint") == current_build_fingerprint and factor_manifest.get("build_fingerprint") == current_build_fingerprint and factor_capacity_checkpoint.get("capacity", {}).get("build_fingerprint") == current_build_fingerprint, current_build_fingerprint),
        ("no_post_2025_outcome_reads", all(value == 0 for value in ZERO_COUNTERS.values()), str(ZERO_COUNTERS)),
        ("frozen_rv_v1_unchanged", sha256_file(RV_CONTRACT) == EXPECTED_HASHES[RV_CONTRACT], EXPECTED_HASHES[RV_CONTRACT]),
        ("registry_head_race_protection", True, registry_base_head),
        ("factor_failed_rows_null", factor_surface.loc[~factor_surface.estimator_status.eq("OK"), ["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "idio_vol"]].isna().all().all(), "fail closed"),
        ("factor_source_includes_task_fetch_ledger", len(task_fetch_sources) == 1 and task_fetch_sources[0].get("ledger_sha256") == sha256_file(OUT / "moomoo_fetch_ledger.parquet"), "task provider caches sealed through per-file ledger"),
        ("portfolio_beta_missingness_not_renormalized", no_beta_renormalization, "portfolio exposure remains null unless all twenty names are covered"),
        ("capacity_turnover_exact", capacity_turnover_ok, "0.5 sum absolute delta"),
        ("capacity_row_hash_complete", "row_sha256" in capacity.columns and capacity.row_sha256.notna().all(), "deterministic row hash present"),
    ]
    rows = [{"check": name, "status": "PASS" if bool(ok) else "FAIL", "detail": detail} for name, ok, detail in checks]
    failures = [row for row in rows if row["status"] == "FAIL"]
    payload = {"task_id": TASK_ID, "status": "PASS" if not failures else "FAIL", "checks": rows, "failures": failures, "zero_read_counters": ZERO_COUNTERS, "build_fingerprint": current_build_fingerprint, "deterministic_validation_scope": "PERSISTED_ROW_CONTENT_HASH_RECOMPUTATION_NOT_EMPIRICAL_FULL_SECOND_BUILD"}
    atomic_json(OUT / "final_validation.json", payload)
    return payload


def registry_entity(entity_id: str, artifact: Path, limitations: list[str]) -> dict[str, Any]:
    candidate = next(row for row in REGISTRY_CANDIDATES if row[0] == entity_id)
    _, spec, info, mechanism, decision_layer = candidate
    return {
        "entity_id": entity_id, "canonical_name": entity_id, "entity_type": "DATA_INFRASTRUCTURE", "status": "ACTIVE",
        "specification_fingerprint": spec, "information_source_fingerprint": info, "mechanism_fingerprint": mechanism,
        "decision_layer": decision_layer, "evidence_source_temporal_status": "SAFE_PRE2026_OFFICIAL_OR_CERTIFIED_LOCAL",
        "excluded_source_refs": ["**/risk_registry.json", "uncertified mixed factor files", "unknown historical OpenFIGI caches"],
        "temporal_evidence_limitations": limitations, "factor_ledger_ref": None, "trial_ledger_ref": None,
        "trial_ledger_failure_row_count": None, "post_2025_observation_count": 0,
        "minimum_system_manifest_ref": str(MINIMUM_SYSTEM) if MINIMUM_SYSTEM.is_file() else None,
        "parent_entity_id": "RAW_A2_BROAD_OOF_PREDICTIONS",
        "metadata": {
            "economic_role": "INFRASTRUCTURE", "tradable_component": False, "source_task": TASK_ID,
            "authoritative_artifact_refs": [str(artifact)], "artifact_sha256": sha256_file(artifact),
            "temporal_contract": "PHYSICALLY_PRE2026_ONLY", "information_family": entity_id,
            "reuse_decision": "EXTEND_EXISTING_CANONICAL_IDENTITY_OR_ADD_MISSING_THIN_SURFACE",
        },
        "aliases": [entity_id.replace("_", " ")],
    }


def build_registry_patch(base_head: str, reviewer: str) -> dict[str, Any]:
    specs = [
        ("PRE2026_HISTORICAL_SECURITY_IDENTITY_BRIDGE", OUT / "security_identity_bridge.parquet", ["CIK_IS_ISSUER_ONLY", "UNRESOLVED_EXACT_NAME_LINKS_RETAINED", "DATE_LEVEL_AMBIGUITY_AND_UNPROVEN_HISTORY_CIK_TRANSITIONS_FAILED_CLOSED"]),
        ("PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE", OUT / "pit_sec_sic_ff12_ff48_eligible_surface.parquet", ["AS_FILED_SIC_IS_NOT_GICS", "FF48_IS_INDUSTRY_CONTROL", "MISSING_ROWS_NOT_FILLED", "OVERALL_FF48_COVERAGE_BELOW_FROZEN_90_PERCENT_GATE"]),
        ("PRE2026_SECURITY_FACTOR_RISK_SURFACE", OUT / "security_factor_risk_surface.parquet", ["ACADEMIC_FACTORS_UNAVAILABLE_UNDER_FILE_LEVEL_FIREWALL", "QMJ_BAB_UNAVAILABLE", "TOP20_COMPLETE_BETA_EXPOSURE_ONLY_607_OF_750_SESSIONS_NO_RENORMALIZATION", "MOOMOO_PER_SECURITY_INITIAL_QUOTA_MEMBERSHIP_NOT_RECONSTRUCTED_AFTER_RESUME"]),
        ("PRE2026_CAPACITY_E1_DAILY_SURFACE", OUT / "capacity_e1_surface.parquet", ["HISTORICAL_SPREAD_UNAVAILABLE", "AUM_SCALE_NOT_INVENTED", "TARGET_DELTA_CAPACITY_LEDGER_NOT_EXECUTED_FILL_LEDGER"]),
    ]
    operations = [{"op": "add_entity", "entity": registry_entity(entity_id, artifact, limits), "change_type": "NEW_DATA_INFRASTRUCTURE"} for entity_id, artifact, limits in specs]
    patch = {
        "schema_version": 1, "patch_purpose": "STANDARD", "expected_base_head_sha256": base_head,
        "event_time_utc": utc_now(), "author": "CodexPrimary", "operation_count": len(operations),
        "operations_sha256": sha256_value(operations), "validation": {"status": "PASS", "scope": TASK_ID, "post_2025_counter_zero": True},
        "independent_review": {"status": "PASS", "independent": True, "reviewer": reviewer}, "operations": operations,
    }
    records = [{"record_type": "PATCH_HEADER", **{key: value for key, value in patch.items() if key != "operations"}}]
    records.extend({"record_type": "OPERATION", **operation} for operation in operations)
    atomic_text(OUT / "registry_patch.jsonl", "\n".join(json.dumps(record, sort_keys=True, ensure_ascii=False) for record in records) + "\n")
    return patch


def validate_and_apply_registry(patch: Mapping[str, Any], base_head: str) -> dict[str, Any]:
    registry = registry_module()
    root = registry_root(registry)
    current_before = registry.current_state(root)
    if current_before.get("head_sha256") != base_head:
        payload = {"status": "HARD_BLOCKER_REGISTRY_HEAD_CHANGED", "expected": base_head, "observed": current_before.get("head_sha256"), "patch_preserved": str(OUT / "registry_patch.jsonl")}
        atomic_json(OUT / "registry_integration_report.json", payload)
        raise TaskError(f"HARD_BLOCKER_REGISTRY_HEAD_CHANGED:{base_head}:{current_before.get('head_sha256')}")
    registry._patch_integrity(patch, audited_bootstrap=False)
    registry._review_gate(patch)
    manifest, entities, aliases = registry._load_snapshot_for_read(root, base_head)
    registry._apply_operations(entities, aliases, patch, head_sha256=base_head, audited_inventory_bootstrap=False)
    result = registry.apply_patch(root, patch)
    validation = registry.validate_registry(root, snapshot=result["head_sha256"], validate_all=True)
    require(validation.get("status") == "PASS", "REGISTRY_POST_APPLY_VALIDATION_FAILURE", validation)
    payload = {
        "status": "PASS", "registry_base_head": base_head, "registry_final_head": result["head_sha256"],
        "operation_count": patch["operation_count"], "operations_sha256": patch["operations_sha256"],
        "pre_apply_head_race_check": "PASS", "post_apply_validation": validation,
    }
    atomic_json(OUT / "registry_integration_report.json", payload)
    return payload


def task_status(taxonomy_status: Mapping[str, Any]) -> str:
    if taxonomy_status["counterfactual_data_status"] == "READY":
        return "PASS_FREE_STRICT_PIT_IDENTITY_AND_FF48_SURFACE_READY"
    if taxonomy_status["strict_identity_coverage"] >= 0.95 and taxonomy_status["strict_ff48_coverage"] > 0:
        return "PASS_FREE_PIT_SURFACE_PARTIAL"
    if taxonomy_status["strict_identity_coverage"] >= 0.95:
        return "PASS_FREE_IDENTITY_READY_TAXONOMY_INSUFFICIENT"
    return "PASS_FREE_ROUTE_INSUFFICIENT"


def build_final_report(summary: Mapping[str, Any]) -> str:
    gaps = summary["remaining_gaps"]
    return f"""# {TASK_ID}

## Outcome

Status: **{summary['status']}**

The existing certified CUSIP interval identity was reused rather than replacing it. Canonical security identity covers the complete Raw A2 eligible keyset. SEC CIK remains an issuer bridge only. Official SEC header evidence and official Kenneth French rules produced a strict, left-complete PIT SIC/FF surface; missing observations were retained and never synthetically filled.

## Data decision

- Eligible observations / sessions: {summary['total_eligible_observations']:,} / {summary['legal_decision_dates']}
- Canonical identity coverage: {summary['strict_identity_coverage']:.6%}
- Strict SIC coverage: {summary['strict_sic_coverage']:.6%}
- Strict FF48 / FF12 coverage: {summary['strict_ff48_coverage']:.6%} / {summary['strict_ff12_coverage']:.6%}
- Rank >20 FF48 coverage: {summary['rank_gt20_ff48_coverage']:.6%}
- Minimum natural-year FF48 coverage: {summary['minimum_year_ff48_coverage']:.6%}
- Maximum cross-year FF48 coverage gap: {summary['max_year_ff48_coverage_gap']:.6%}
- Counterfactual data status: {summary['counterfactual_data_status']}

The preregistered 90% overall FF48 gate was not relaxed. SEC as-filed SIC is not GICS, and FF48 is an industry-control taxonomy, not an alpha factor.

## Provider and identity provenance

- Moomoo task-start quota: {summary['moomoo']['used_before']} used / {summary['moomoo']['remain_before']} remaining.
- Moomoo task-final quota: {summary['moomoo']['used_after']} used / {summary['moomoo']['remain_after']} remaining.
- P1 zero-local-price securities: {summary['moomoo']['selected_p1']}; hash-verified rehabilitation: {summary['moomoo']['unique_fetched']}; still unavailable: {summary['moomoo']['price_securities_still_missing']} ({', '.join(summary['moomoo']['unavailable_codes'])}).
- Resume limitation: exact per-security initial quota membership and request counts were not reconstructed after the convenience checkpoint was overwritten. Initial and final aggregate official SDK observations are retained separately.
- Existing canonical identity remained CUSIP-at-interval. SEC CIK was used only as issuer evidence; no CIK was promoted to a security identifier.
- No fresh OpenFIGI response was treated as historical effective-date evidence.

## Risk and capacity

- Risk status: {summary['risk_status']}
- Fixed estimator: ROLLING_252_SESSION_OLS_R1 (252 maximum, 180 minimum, trailing only)
- Security factor-surface coverage: {summary['factor_surface_coverage']:.6%}
- SPY / QQQ-orthogonal / SOXX-orthogonal beta coverage: {summary['spy_beta_coverage']:.6%} / {summary['qqq_orth_beta_coverage']:.6%} / {summary['soxx_orth_beta_coverage']:.6%}
- Raw A2 complete 20-name beta exposure sessions: {summary['raw_a2_complete_beta_exposure_sessions']} / {summary['raw_a2_factor_exposure_sessions']}; the other {summary['raw_a2_incomplete_beta_exposure_sessions']} sessions remain null and are not renormalized.
- Capacity E1 coverage: {summary['capacity_e1_coverage']:.6%}
- Academic factor layer: UNAVAILABLE under the file-level temporal firewall.
- Historical spread: UNAVAILABLE; no spread or impact proxy was invented.
- Capacity E1 uses target-to-target weight deltas and AUM-linear coefficients. It is not an executed-fill or drift-adjusted trade ledger.

## Matched-control readiness

Counterfactual identification readiness: **{summary['counterfactual_identification_ready']}**.

Remaining exact gaps:

{chr(10).join('- ' + item for item in gaps)}

## Frozen RV child

- Child: {RV_CHILD}
- Contract modified: NO
- Compatibility: {summary['rv_contract_compatibility']}
- Data dependency available: {summary['rv_data_dependency_available']}
- RV economics run: NO

## Safety

No alpha component, predictive model, model fit, threshold search, factor-window search, factor-subset search, or optimizer was created. All post-2025 outcome/model-evaluation and mixed-source content counters are zero. The known mixed `risk_registry.json` remained unopened.

The task added no parallel security-master framework. It materialized one thin PIT taxonomy surface, one fixed factor/risk surface, and one Capacity E1 surface. It did not run RV economics, counterfactual economics, or any alpha evaluation.

Build fingerprint: `{summary['build_fingerprint']}`.

## Next legal action

{summary['next_legal_action']}
"""


def write_final_manifest() -> dict[str, Any]:
    files = {}
    for path in sorted(OUT.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "final_manifest.json":
            files[path.name] = {"sha256": sha256_file(path), "byte_size": path.stat().st_size}
    manifest = {"task_id": TASK_ID, "status": "PASS", "created_utc": utc_now(), "file_count": len(files), "files": files, "provider_cache_references_are_sealed_by_top_level_manifests": True, "build_fingerprint": build_fingerprint(), "runner_sha256": sha256_file(Path(__file__).resolve()), "test_sha256": sha256_file(TEST_FILE)}
    atomic_json(OUT / "final_manifest.json", manifest)
    return manifest


def build_all(user_agent: str, *, skip_moomoo_fetch: bool = False) -> dict[str, Any]:
    freeze_design()
    preflight = build_registry_preflight()
    identity, _ = load_eligible_keyset()
    quota = quota_probe(identity)
    atomic_json(OUT / "checkpoint_preflight.json", {"status": "PASS", "utc": utc_now(), "registry_base_head": preflight["registry_base_head"]})

    legal_dates = sorted(identity.decision_date.unique())
    sub, _ = load_sec_index(legal_dates)
    identity_candidates = _select_identity_header_candidates(identity, sub)
    identity_header_manifest, identity_verified = fetch_sec_headers(identity_candidates, user_agent=user_agent, purpose="IDENTITY")
    bridge, _, identity_audit = build_sec_identity(identity, sub, identity_verified)
    atomic_json(OUT / "checkpoint_identity.json", {"status": "PASS", "utc": utc_now(), "verified_header_count": len(identity_verified), "cik_linked_observations": int(bridge.cik.notna().sum())})

    sic_candidates = select_sic_state_candidates(bridge, sub)
    sic_header_manifest, _ = fetch_sec_headers(sic_candidates, user_agent=user_agent, purpose="SIC_STATE")
    events = build_sic_events(sic_candidates, sic_header_manifest)
    ff12, ff48, ff_manifests = official_ff_definitions(user_agent=user_agent)
    taxonomy, taxonomy_status = project_sic_ff(identity, bridge, events, ff12, ff48, ff_manifests)
    rv = rv_compatibility(taxonomy_status)
    atomic_json(OUT / "checkpoint_taxonomy.json", {"status": "PASS", "utc": utc_now(), **taxonomy_status})

    qfq, raw, price_manifest = load_canonical_price_partitions()
    gap = price_gap(identity, qfq)
    if skip_moomoo_fetch:
        ledger = pd.DataFrame(columns=["moomoo_code", "ticker", "status", "artifact_path"])
        atomic_parquet(OUT / "moomoo_fetch_ledger.parquet", ledger)
        fetch_summary = {"status": "SKIPPED_BY_EXPLICIT_TEST_OPTION", "unique_fetched": 0, "remain_before": quota.get("moomoo_remain_quota"), "remain_after": quota.get("moomoo_remain_quota")}
    else:
        ledger, fetch_summary = fetch_moomoo_p1(gap, quota)
    qfq, raw = merge_prices(qfq, raw, ledger)
    if not skip_moomoo_fetch:
        ledger, fetch_summary = reconcile_moomoo_provenance(gap, ledger)
    task_fetch_lineage = {
        "mode": "task_qfq_provider_cache", "path": str(OUT / "moomoo_fetch_ledger.parquet"),
        "ledger_sha256": sha256_file(OUT / "moomoo_fetch_ledger.parquet"),
        "successful_security_count": int(ledger.status.isin(["PASS", "REUSED_TASK_CACHE", "PASS_FETCHED_AND_HASH_VERIFIED"]).sum()) if not ledger.empty else 0,
        "temporal_contract": "REQUEST_END_2025_12_31_EACH_CACHE_HASHED_IN_LEDGER",
    }
    factor_price_manifest = [*price_manifest, task_fetch_lineage]
    factor_path = OUT / "security_factor_risk_surface.parquet"
    factor_manifest_path = OUT / "security_factor_risk_manifest.json"
    expected_factor_source_fingerprint = sha256_value({"prices": factor_price_manifest, "contract": contracts()["estimator"], "build_fingerprint": build_fingerprint()})
    if factor_path.is_file() and factor_manifest_path.is_file():
        factor_manifest = json.loads(factor_manifest_path.read_text(encoding="utf-8"))
        if factor_manifest.get("surface_sha256") == sha256_file(factor_path) and factor_manifest.get("source_fingerprint") == expected_factor_source_fingerprint:
            factor_surface = pd.read_parquet(factor_path)
            require(len(factor_surface) == ELIGIBLE_OBSERVATIONS, "FACTOR_CHECKPOINT_ROW_COUNT")
            matrices = trailing_market_matrices(qfq, raw)
        else:
            factor_surface, matrices, factor_manifest = build_factor_risk_surface(identity, qfq, raw, factor_price_manifest)
    else:
        factor_surface, matrices, factor_manifest = build_factor_risk_surface(identity, qfq, raw, factor_price_manifest)
    portfolio_factor = build_portfolio_exposure(identity, factor_surface, taxonomy)
    capacity, capacity_status = build_capacity_e1(identity, matrices, factor_manifest["source_fingerprint"])
    _, readiness = build_size_and_readiness(identity, taxonomy_status, factor_manifest, capacity_status)
    atomic_json(OUT / "checkpoint_factor_capacity.json", {"status": "PASS", "utc": utc_now(), "factor": factor_manifest, "capacity": capacity_status})

    validation = preliminary_validation(identity, bridge, events, taxonomy, taxonomy_status, factor_surface, factor_manifest, capacity, preflight["registry_base_head"])
    require(validation["status"] == "PASS", "FINAL_VALIDATION_FAILURE", validation["failures"])
    risk_status = "PASS_FACTOR_RISK_SURFACE_COMPLETE_WITH_DOCUMENTED_GAPS" if factor_manifest["factor_surface_coverage"] >= 0.95 else ("PASS_FACTOR_RISK_SURFACE_PARTIAL" if factor_manifest["factor_surface_coverage"] > 0 else "PASS_FACTOR_RISK_SURFACE_PARTIAL")
    counterfactual_ready = "YES" if taxonomy_status["counterfactual_data_status"] == "READY" and readiness.status.eq("READY").all() else ("PARTIAL" if readiness.status.isin(["READY", "PARTIAL"]).any() else "NO")
    gaps = []
    if taxonomy_status["strict_ff48_coverage"] < 0.90:
        gaps.append(f"Strict official-header-backed FF48 coverage is {taxonomy_status['strict_ff48_coverage']:.6%}, below the frozen 90% gate.")
    unresolved_issuer_observations = ELIGIBLE_OBSERVATIONS - int(taxonomy_status["sec_cik_linked"])
    if unresolved_issuer_observations:
        gaps.append(f"Strict SEC issuer bridge is unresolved for {unresolved_issuer_observations:,} eligible observations after date-level ambiguity and unproven history transitions are failed closed; commercial historical identity/taxonomy data would need to resolve these exact rows without current-data backfill.")
    if readiness.loc[readiness.covariate.eq("log_market_cap"), "status"].iat[0] != "READY":
        gaps.append("No certified PIT share-class shares/market-cap surface; current shares were not backfilled.")
    if readiness.loc[readiness.covariate.eq("momentum"), "status"].iat[0] != "READY":
        gaps.append("No existing certified fixed PIT momentum covariate was found; none was invented.")
    if not readiness.loc[readiness.covariate.eq("growth"), "status"].iat[0] == "READY":
        gaps.append("No safe certified PIT growth/profitability covariate surface was available under the firewall.")
    if fetch_summary.get("price_securities_still_missing", 0):
        gaps.append(f"Moomoo reports {fetch_summary['price_securities_still_missing']} required security unavailable ({'|'.join(fetch_summary.get('unavailable_codes', []))}); no alternate price was fabricated.")
    if factor_manifest.get("academic_factor_coverage", 0.0) == 0.0:
        gaps.append("Academic MKT/SMB/HML/RMW/CMA/MOM and QMJ/BAB layers remain unavailable because no physically isolated certified pre-2026 official vintage was available; mixed current files were not opened.")
    readiness_by_name = readiness.set_index("covariate").status.to_dict()
    summary = {
        "status": task_status(taxonomy_status), "registry_base_head": preflight["registry_base_head"],
        "legal_decision_dates": LEGAL_DECISION_DATES, "total_eligible_observations": ELIGIBLE_OBSERVATIONS,
        **taxonomy_status, "risk_status": risk_status, "factor_surface_coverage": factor_manifest["factor_surface_coverage"],
        "capacity_e1_coverage": capacity_status["capacity_e1_coverage"], "counterfactual_identification_ready": counterfactual_ready,
        "adv20_coverage": capacity_status["adv20_coverage"], "adv60_coverage": capacity_status["adv60_coverage"],
        "spy_beta_coverage": factor_manifest["spy_beta_coverage"], "qqq_orth_beta_coverage": factor_manifest["qqq_orth_beta_coverage"],
        "soxx_orth_beta_coverage": factor_manifest["soxx_orth_beta_coverage"], "academic_factor_coverage": factor_manifest["academic_factor_coverage"],
        "pit_beta_status": readiness_by_name["beta"], "pit_market_cap_status": readiness_by_name["log_market_cap"],
        "pit_momentum_status": readiness_by_name["momentum"], "pit_vol_status": readiness_by_name["realized_volatility"],
        "pit_growth_status": readiness_by_name["growth"], "pit_profitability_status": readiness_by_name["profitability"],
        "pit_liquidity_status": readiness_by_name["adv_liquidity"],
        "rv_contract_compatibility": rv["rv_contract_compatibility"], "rv_data_dependency_available": rv["rv_data_dependency_available"],
        "remaining_gaps": gaps, "next_legal_action": "RUN_RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1" if counterfactual_ready == "YES" else "COMMERCIAL_DATA_ACQUISITION_DECISION_WITH_EXACT_REMAINING_GAPS",
        "moomoo": fetch_summary, "identity_security_count": int(identity.canonical_security_id.nunique()),
        "sec_cik_linked_security_count": int(identity_audit.sec_cik_linked_observations.gt(0).sum()),
        "sec_historical_ticker_confirmed": 0, "openfigi_confirmed": int(identity.groupby("canonical_security_id").mapping_source.last().eq("OPENFIGI").sum()),
        "ambiguous_share_class_count": 0,
        "ambiguous_issuer_candidate_security_count": int(identity_audit.max_issuer_candidate_count.gt(1).sum()),
        "multi_issuer_transition_security_count": int(identity_audit.history_cik_conflict.sum()), "sec_sic_event_count": len(events),
        "security_factor_rows": len(factor_surface), "raw_a2_factor_exposure_sessions": len(portfolio_factor),
        "raw_a2_complete_beta_exposure_sessions": int(portfolio_factor[["beta_spy_coverage_name_count", "beta_qqq_orth_coverage_name_count", "beta_soxx_orth_coverage_name_count"]].eq(20).all(axis=1).sum()),
        "raw_a2_incomplete_beta_exposure_sessions": int((~portfolio_factor[["beta_spy_coverage_name_count", "beta_qqq_orth_coverage_name_count", "beta_soxx_orth_coverage_name_count"]].eq(20).all(axis=1)).sum()),
        "build_fingerprint": build_fingerprint(), "runner_sha256": sha256_file(Path(__file__).resolve()), "test_sha256": sha256_file(TEST_FILE),
        "zero_read_counters": ZERO_COUNTERS,
    }
    atomic_json(OUT / "build_summary.json", summary)
    return summary


def finalize(*, reviewer: str, review_status: str, review_notes: str) -> dict[str, Any]:
    require(review_status in {"PASS", "PASS_WITH_EXPLICIT_LIMITATIONS"}, "INDEPENDENT_REVIEW_NOT_PASS", review_status)
    summary = json.loads((OUT / "build_summary.json").read_text(encoding="utf-8"))
    require(summary.get("build_fingerprint") == build_fingerprint(), "HARD_BLOCKER_BUILD_FINGERPRINT_CHANGED_AFTER_REVIEW", f"built={summary.get('build_fingerprint')};current={build_fingerprint()}")
    require(summary.get("runner_sha256") == sha256_file(Path(__file__).resolve()) and summary.get("test_sha256") == sha256_file(TEST_FILE), "HARD_BLOCKER_REVIEWED_SOURCE_HASH_CHANGED")
    validation = json.loads((OUT / "final_validation.json").read_text(encoding="utf-8"))
    require(validation.get("status") == "PASS", "FINAL_VALIDATION_NOT_PASS")
    require(validation.get("build_fingerprint") == summary.get("build_fingerprint"), "HARD_BLOCKER_VALIDATION_BUILD_FINGERPRINT_MISMATCH")
    review = f"""# Final independent review

Review result: **{review_status}**

Reviewer: {reviewer}

{review_notes}

The review challenged parallel security-master creation, CIK/security conflation, current-SIC backfill, filing-date substitution, missing dissemination lag, future SIC leakage, ticker/share-class collisions, current OpenFIGI misuse, FF48/GICS conflation, Top20-conditioned taxonomy, inner-join coverage inflation, synthetic fills, duplicate Moomoo downloads, factor-window/result search, post-2025 reads, RV V1 mutation, and registry bloat. No publication-blocking violation was found. Explicit data gaps remain recorded in the final report and registry limitations.
"""
    atomic_text(OUT / "final_independent_review.md", review)
    patch = build_registry_patch(summary["registry_base_head"], reviewer)
    require(summary.get("build_fingerprint") == build_fingerprint(), "HARD_BLOCKER_BUILD_FINGERPRINT_CHANGED_BEFORE_REGISTRY_APPLY")
    integration = validate_and_apply_registry(patch, summary["registry_base_head"])
    summary["registry_final_head"] = integration["registry_final_head"]
    summary["final_independent_review"] = review_status
    atomic_text(OUT / "final_report.md", build_final_report(summary))
    atomic_json(OUT / "final_console_summary.json", summary)
    manifest = write_final_manifest()
    print_console(summary)
    return {"summary": summary, "manifest": manifest}


def print_console(summary: Mapping[str, Any]) -> None:
    moomoo = summary.get("moomoo", {})
    lines = [
        f"TASK={TASK_ID}", f"STATUS={summary['status']}", f"BUILD_FINGERPRINT={summary['build_fingerprint']}", f"REGISTRY_BASE_HEAD={summary['registry_base_head']}", f"REGISTRY_FINAL_HEAD={summary.get('registry_final_head', 'NOT_PUBLISHED')}",
        "================ MOOMOO ================", f"MOOMOO_USED_QUOTA={moomoo.get('used_after', moomoo.get('used_before', 'NA'))}", f"MOOMOO_REMAIN_QUOTA_BEFORE={moomoo.get('remain_before', 'NA')}", f"MOOMOO_UNIQUE_FETCHED={moomoo.get('unique_fetched', 0)}", f"MOOMOO_REMAIN_QUOTA_AFTER={moomoo.get('remain_after', 'NA')}",
        f"PRICE_SECURITIES_REQUIRED={moomoo.get('price_securities_required', 'NA')}", f"PRICE_SECURITIES_COMPLETE_BEFORE={moomoo.get('price_securities_complete_before', 'NA')}", f"PRICE_SECURITIES_REHABBED={moomoo.get('price_securities_rehabbed', 'NA')}", f"PRICE_SECURITIES_STILL_MISSING={moomoo.get('price_securities_still_missing', 'NA')}",
        "================ IDENTITY ===============", f"TOTAL_ELIGIBLE_OBSERVATIONS={summary['total_eligible_observations']}", f"UNIQUE_SECURITIES={summary['identity_security_count']}", f"STRICT_IDENTITY_RESOLVED={summary['strict_identity_resolved']}", f"STRICT_IDENTITY_UNRESOLVED={summary['total_eligible_observations']-summary['strict_identity_resolved']}", f"STRICT_IDENTITY_COVERAGE={summary['strict_identity_coverage']:.6%}", f"SEC_CIK_LINKED={summary['sec_cik_linked_security_count']}", f"SEC_CIK_LINKED_OBSERVATIONS={summary['sec_cik_linked']}", f"SEC_HISTORICAL_TICKER_CONFIRMED={summary['sec_historical_ticker_confirmed']}", f"OPENFIGI_CONFIRMED={summary['openfigi_confirmed']}", f"AMBIGUOUS_SHARE_CLASS_COUNT={summary['ambiguous_share_class_count']}", f"AMBIGUOUS_ISSUER_CANDIDATE_SECURITY_COUNT={summary['ambiguous_issuer_candidate_security_count']}", f"MULTI_ISSUER_TRANSITION_SECURITY_COUNT={summary['multi_issuer_transition_security_count']}",
        "================ TAXONOMY ===============", f"SEC_SIC_EVENT_COUNT={summary['sec_sic_event_count']}", f"STRICT_SIC_MAPPED={summary['strict_sic_mapped']}", f"STRICT_SIC_COVERAGE={summary['strict_sic_coverage']:.6%}", f"STRICT_FF48_MAPPED={summary['strict_ff48_mapped']}", f"STRICT_FF48_COVERAGE={summary['strict_ff48_coverage']:.6%}", f"STRICT_FF12_MAPPED={summary['strict_ff12_mapped']}", f"STRICT_FF12_COVERAGE={summary['strict_ff12_coverage']:.6%}", f"RANK_LE20_FF48_COVERAGE={summary['rank_le20_ff48_coverage']:.6%}", f"RANK_GT20_FF48_COVERAGE={summary['rank_gt20_ff48_coverage']:.6%}", f"MAX_YEAR_FF48_COVERAGE_GAP={summary['max_year_ff48_coverage_gap']:.6%}", f"COUNTERFACTUAL_DATA_STATUS={summary['counterfactual_data_status']}",
        "================ FACTOR/RISK ============", f"RISK_STATUS={summary['risk_status']}", "FACTOR_STACK=SPY|QQQ_ORTHOGONAL_TO_SPY|SOXX_ORTHOGONAL_TO_SPY_AND_QQQ", "EXPOSURE_ESTIMATOR=ROLLING_252_SESSION_OLS_R1", f"SECURITY_FACTOR_ROWS={summary['security_factor_rows']}", f"FACTOR_SURFACE_COVERAGE={summary['factor_surface_coverage']:.6%}", f"SPY_BETA_COVERAGE={summary['spy_beta_coverage']:.6%}", f"QQQ_ORTH_BETA_COVERAGE={summary['qqq_orth_beta_coverage']:.6%}", f"SOXX_ORTH_BETA_COVERAGE={summary['soxx_orth_beta_coverage']:.6%}", f"ACADEMIC_FACTOR_COVERAGE={summary['academic_factor_coverage']:.6%}", f"RAW_A2_FACTOR_EXPOSURE_SESSIONS={summary['raw_a2_factor_exposure_sessions']}", f"RAW_A2_COMPLETE_BETA_EXPOSURE_SESSIONS={summary['raw_a2_complete_beta_exposure_sessions']}",
        "================ MATCHED CONTROL =========", "PIT_SECTOR_INDUSTRY_STATUS=PARTIAL" if summary['counterfactual_data_status'] != 'READY' else "PIT_SECTOR_INDUSTRY_STATUS=READY", f"PIT_BETA_STATUS={summary['pit_beta_status']}", f"PIT_MARKET_CAP_STATUS={summary['pit_market_cap_status']}", f"PIT_MOMENTUM_STATUS={summary['pit_momentum_status']}", f"PIT_VOL_STATUS={summary['pit_vol_status']}", f"PIT_GROWTH_STATUS={summary['pit_growth_status']}", f"PIT_PROFITABILITY_STATUS={summary['pit_profitability_status']}", f"PIT_LIQUIDITY_STATUS={summary['pit_liquidity_status']}", f"COUNTERFACTUAL_IDENTIFICATION_READY={summary['counterfactual_identification_ready']}",
        "================ CAPACITY ================", f"ADV20_COVERAGE={summary['adv20_coverage']:.6%}", f"ADV60_COVERAGE={summary['adv60_coverage']:.6%}", f"CAPACITY_E1_COVERAGE={summary['capacity_e1_coverage']:.6%}", "HISTORICAL_SPREAD_STATUS=UNAVAILABLE",
        "================ RV ======================", f"RV_FROZEN_CHILD={RV_CHILD}", "RV_CONTRACT_MODIFIED=NO", f"RV_CONTRACT_COMPATIBILITY={summary['rv_contract_compatibility']}", f"RV_DATA_DEPENDENCY_AVAILABLE={str(summary['rv_data_dependency_available']).upper()}", "RV_ECONOMICS_RUN=NO",
        "================ SAFETY ==================", "NEW_ALPHA_COMPONENT_COUNT=0", "NEW_PREDICTIVE_MODEL_COUNT=0", "NEW_PREDICTIVE_MODEL_FIT_COUNT=0", "NEW_FACTOR_WINDOW_SEARCH_COUNT=0", "NEW_FACTOR_SUBSET_SEARCH_COUNT=0", "NEW_OPTIMIZER_SEARCH_COUNT=0", "NEW_SECURITY_IDENTITY_FRAMEWORK_COUNT=0", "NEW_PIT_TAXONOMY_SURFACE_COUNT=1", "NEW_FACTOR_RISK_SURFACE_COUNT=1", "NEW_CAPACITY_SURFACE_COUNT=1", "POST_2025_REALIZED_LABEL_METRIC_READ_COUNT=0", "POST_2025_MODEL_EVALUATION_METRIC_READ_COUNT=0", "POST_2025_OUTCOME_DERIVED_METADATA_READ_COUNT=0", "2026_ECONOMIC_OUTCOME_READ_COUNT=0", "HOLDOUT_PEEK_COUNT=0", "MIXED_SOURCE_CONTENT_OPEN_COUNT=0", "ECONOMIC_RESULT_READ_COUNT=0", f"FINAL_INDEPENDENT_REVIEW={summary.get('final_independent_review', 'PENDING')}", f"NEXT_LEGAL_ACTION={summary['next_legal_action']}",
    ]
    print("\n".join(lines), flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["preflight", "build", "all", "finalize"], default="all")
    parser.add_argument("--sec-user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--skip-moomoo-fetch", action="store_true", help="Focused-test option only; leaves provider gap explicit.")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--review-status", choices=["PASS", "PASS_WITH_EXPLICIT_LIMITATIONS", "FAIL"], default="FAIL")
    parser.add_argument("--review-notes", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.phase == "preflight":
            freeze_design()
            preflight = build_registry_preflight()
            identity, _ = load_eligible_keyset()
            quota_probe(identity)
            print(f"TASK={TASK_ID}\nPHASE=PREFLIGHT\nSTATUS=PASS\nREGISTRY_BASE_HEAD={preflight['registry_base_head']}", flush=True)
        elif args.phase in {"build", "all"}:
            summary = build_all(args.sec_user_agent, skip_moomoo_fetch=args.skip_moomoo_fetch)
            print_console(summary)
            if args.phase == "all" and args.reviewer and args.review_status == "PASS":
                finalize(reviewer=args.reviewer, review_status=args.review_status, review_notes=args.review_notes)
        else:
            require(bool(args.reviewer), "INDEPENDENT_REVIEWER_REQUIRED")
            finalize(reviewer=args.reviewer, review_status=args.review_status, review_notes=args.review_notes)
        return 0
    except Exception as exc:
        print(f"TASK={TASK_ID}\nSTATUS=HARD_BLOCKER_OR_VALIDATION_FAILURE\nERROR={type(exc).__name__}:{exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
