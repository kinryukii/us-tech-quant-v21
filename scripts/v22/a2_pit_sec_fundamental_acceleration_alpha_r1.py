from __future__ import annotations

"""Strict-PIT SEC financial-statement acceleration research for Raw A2.

The only portfolio treatment in this runner is equal-weight Top20 membership.
SEC facts are keyed to their accession and become usable on the first NYSE
session strictly after the EDGAR acceptance timestamp.  Economic labels and
portfolio replay are delegated to the clean A2 R2 and authoritative replay
implementations rather than reimplemented here.
"""

import hashlib
import importlib.util
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("A2_AUTONOMOUS_POLICY_MODE", "R2")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import joblib
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


TASK = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache\sec_fundamental_pit_r1")
OUT = RESULTS / TASK
R2_SOURCE = REPO / "scripts" / "v22" / "a2_autonomous_buy_sell_and_sizing_policy_r1.py"
SEC_STAGE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
ACTION_SOURCE = REPO / "scripts" / "v22" / "a2_global_ff12_hold_replace_r1.py"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
E5_SOURCE = RESULTS / "A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS" / "run_a2_execution_efficiency_r2.py"
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
MATRIX = A2_ROOT / "training_matrix.parquet"
OOF = A2_ROOT / "oof_predictions.parquet"
RESEARCH_DATASET = Path(r"D:\us-tech-quant-cache\a2_model_family_r1a_data_complete\research_dataset.parquet")
UNIVERSE_INTERVALS = RESULTS / "A2_PIT13F_MATERIALIZATION_R1" / "effective_universe_intervals.parquet"
PRIOR_CIK_BRIDGE = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "security_cik_bridge.parquet"
PRIOR_SEC_SUB = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_fsds_sub_min.parquet")
PRIOR_SEC_MANIFEST = Path(r"D:\us-tech-quant-cache\sec_pit_taxonomy\sec_source_manifest.json")
RESUME_PROVENANCE = Path(
    r"D:\us-tech-quant-backtests\A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1"
    r"\DATA_COVERAGE_INSUFFICIENT_PROVENANCE_20260824T043714JST"
)
BULK_ROOT = CACHE_ROOT / "bulk"
COMPANYFACTS_BULK = BULK_ROOT / "companyfacts.zip"
SUBMISSIONS_BULK = BULK_ROOT / "submissions.zip"
BULK_SNAPSHOT_MANIFEST = CACHE_ROOT / "sec_bulk_snapshot_manifest.json"
BULK_DERIVED_ROOT = CACHE_ROOT / "derived_bulk_resume"
FEATURE_STATE_CACHE_VERSION = "ACCESSION_PIT_STATES_V1_BASE_FORM_AMENDMENT_ALIAS"

BULK_CONTRACT: dict[str, dict[str, Any]] = {
    "companyfacts": {
        "path": str(COMPANYFACTS_BULK), "bytes": 1_407_131_132, "entries": 20_266,
        "sha256": "d7b4b3c5f2fe014a203bdaef2197d2cba5683f434e965fc9bced1023a43c82ca",
    },
    "submissions": {
        "path": str(SUBMISSIONS_BULK), "bytes": 1_559_612_838, "entries": 987_520,
        "sha256": "928d67221c6e6183bc343e7234c1391448c15cd1dd644d36b425db2f99ba4350",
    },
}
FROZEN_PREREG_SHA256 = "001ce13b44adaa1c8ccb0bd8340a3ed383c2c481e8d75c4fd77e2ccacad4d900"
FROZEN_CONCEPT_SHA256 = "3840fd339105f90a804af00ee637be2ce88e7af1f637911a54bd902c23dee19a"
FROZEN_MAPPING_LEDGER_SHA256 = "31678c81d744c1014b06e5521257ace8c1a3998f289dc52041818434d38b8bb1"

SEC_QUARTER_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_START = pd.Timestamp("2018-01-01")
SEC_CUTOFF_UTC = pd.Timestamp("2026-01-01", tz="America/New_York").tz_convert("UTC")
LABEL_CUTOFF = pd.Timestamp("2025-12-31")
TOL = 1e-12
MAX_REQUEST_RATE = 5.0
REQUEST_INTERVAL = 1.0 / MAX_REQUEST_RATE
MAX_UNIQUE_MODEL_SPECS = 36
MAX_TOTAL_MODEL_FITS = 200
MAX_POLICY_SPECS = 24
MAX_OUTER_FINALISTS = 6
MAX_ENSEMBLES = 1
RANDOM_SEEDS = (20260824, 20260825, 20260826)
FORBIDDEN_LABEL_SOURCE = "FROZEN_POSITION_LEDGER_EXACT_MARK"

REVENUE_PRIORITY = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
CONCEPT_PRIORITY: dict[str, tuple[str, ...]] = {
    "revenue": REVENUE_PRIORITY,
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "research_and_development": ("ResearchAndDevelopmentExpense",),
    "share_based_compensation": ("ShareBasedCompensation",),
}
INSTANT_CATEGORIES = {"assets", "equity"}
FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

FEATURE_FAMILIES: dict[str, list[str]] = {
    "F0_GROWTH_ACCELERATION": [
        "revenue_yoy", "revenue_yoy_change_vs_prior_filing", "revenue_growth_acceleration",
    ],
    "F1_PROFITABILITY": [
        "gross_margin", "gross_margin_yoy_change", "operating_margin",
        "operating_margin_yoy_change", "net_margin", "net_margin_yoy_change",
    ],
    "F2_CASH_FLOW_QUALITY": [
        "operating_cash_flow_margin", "operating_cash_flow_margin_change",
        "free_cash_flow_margin", "free_cash_flow_margin_change", "cfo_to_net_income",
        "accrual_quality",
    ],
    "F3_INVESTMENT_INNOVATION": [
        "asset_growth_yoy", "rd_to_revenue", "rd_intensity_change",
        "sbc_to_revenue", "sbc_intensity_change",
    ],
    "F4_FILING_QUALITY": [
        "filing_lag_days", "amendment_indicator", "concept_switch_indicator",
        "fact_coverage_ratio",
    ],
}
FEATURE_FAMILIES["F5_FULL_BOUNDED"] = list(
    dict.fromkeys(sum(FEATURE_FAMILIES.values(), []))
)
CORE_COVERAGE_FAMILIES = tuple(FEATURE_FAMILIES[name] for name in (
    "F0_GROWTH_ACCELERATION", "F1_PROFITABILITY", "F2_CASH_FLOW_QUALITY",
    "F3_INVESTMENT_INNOVATION",
))
SIMPLE_SIGNS: dict[str, float] = {
    "revenue_growth_acceleration": 1.0,
    "revenue_yoy": 1.0,
    "gross_margin_yoy_change": 1.0,
    "operating_margin_yoy_change": 1.0,
    "net_margin_yoy_change": 1.0,
    "operating_cash_flow_margin_change": 1.0,
    "free_cash_flow_margin_change": 1.0,
    "accrual_quality": -1.0,
    "asset_growth_yoy": -1.0,
    "sbc_to_revenue": -1.0,
    "sbc_intensity_change": -1.0,
}
CONTROL_FEATURES = [
    "raw_score_z", "ret_20d", "ret_60d", "realized_vol_20d",
    "avg_dollar_volume_20d",
]


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def zip_contract_metadata(path: Path) -> dict[str, Any]:
    require(path.is_file(), "SEC_BULK_PAYLOAD_MISSING", path)
    with zipfile.ZipFile(path) as archive:
        count = len(archive.filelist)
    return {"path": str(path), "bytes": path.stat().st_size, "entries": count, "sha256": sha256_file(path)}


def freeze_bulk_snapshot() -> dict[str, Any]:
    observed = {
        name: zip_contract_metadata(Path(contract["path"]))
        for name, contract in BULK_CONTRACT.items()
    }
    for name, contract in BULK_CONTRACT.items():
        actual = observed[name]
        require(actual["bytes"] == contract["bytes"], "SEC_BULK_BYTE_LENGTH_MISMATCH", name)
        require(actual["entries"] == contract["entries"], "SEC_BULK_ENTRY_COUNT_MISMATCH", name)
        require(actual["sha256"] == contract["sha256"], "SEC_BULK_SHA256_MISMATCH", name)
    payload = {
        "research_id": TASK,
        "status": "FROZEN_AUTHORITATIVE_OFFICIAL_SEC_BULK_SNAPSHOT",
        "network_requests_permitted": False,
        "full_extraction_permitted": False,
        "payloads": observed,
        "snapshot_contract_hash": stable_hash(observed),
    }
    if BULK_SNAPSHOT_MANIFEST.is_file():
        prior = json.loads(BULK_SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
        require(prior == payload, "SEC_BULK_SNAPSHOT_MUTATION")
    else:
        atomic_json(BULK_SNAPSHOT_MANIFEST, payload)
    payload["manifest_sha256"] = sha256_file(BULK_SNAPSHOT_MANIFEST)
    return payload


def restore_frozen_research_contract() -> tuple[dict[str, Any], dict[str, Any], str, str]:
    pairs = (
        ("sec_concept_contract.json", FROZEN_CONCEPT_SHA256),
        ("preregistration.json", FROZEN_PREREG_SHA256),
    )
    restored: dict[str, dict[str, Any]] = {}
    for name, expected in pairs:
        source = RESUME_PROVENANCE / name
        require(source.is_file(), "FROZEN_PROVENANCE_MISSING", source)
        require(sha256_file(source) == expected, "FROZEN_PROVENANCE_HASH_MISMATCH", name)
        destination = OUT / name
        if destination.is_file():
            require(sha256_file(destination) == expected, "FROZEN_CONTRACT_MISMATCH", destination)
        else:
            atomic_bytes(destination, source.read_bytes())
        restored[name] = json.loads(destination.read_text(encoding="utf-8"))
    return (
        restored["sec_concept_contract.json"], restored["preregistration.json"],
        FROZEN_CONCEPT_SHA256, FROZEN_PREREG_SHA256,
    )


def load_frozen_cik_mapping() -> tuple[pd.DataFrame, str]:
    ledger_path = RESUME_PROVENANCE / "trial_ledger.parquet"
    require(ledger_path.is_file(), "FROZEN_MAPPING_LEDGER_MISSING", ledger_path)
    require(sha256_file(ledger_path) == FROZEN_MAPPING_LEDGER_SHA256, "FROZEN_MAPPING_LEDGER_HASH_MISMATCH")
    ledger = pd.read_parquet(ledger_path)
    mapping = ledger.loc[ledger.record_type.eq("CIK_MAPPING")].copy()
    required = {
        "security_id", "cusip", "ticker", "issuer_name", "cik", "mapping_source",
        "mapping_confidence", "mapping_effective_date", "identity_effective_start",
        "identity_effective_end", "mapping_evidence",
    }
    require(required.issubset(mapping.columns), "FROZEN_MAPPING_SCHEMA", sorted(required - set(mapping.columns)))
    mapping = mapping[list(sorted(required))].copy()
    for column in ("mapping_effective_date", "identity_effective_start", "identity_effective_end"):
        mapping[column] = pd.to_datetime(mapping[column], errors="coerce").dt.normalize()
    mapping["ticker"] = mapping.ticker.astype(str).str.upper().str.strip()
    mapping["cik"] = pd.to_numeric(mapping.cik, errors="coerce").astype("Int64")
    require(mapping.cik.dropna().nunique() == 1219, "FROZEN_RESOLVED_CIK_SET_MISMATCH")
    return mapping.reset_index(drop=True), FROZEN_MAPPING_LEDGER_SHA256


def normalize_name(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]", " ", str(value).upper())
    text = re.sub(
        r"\b(THE|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|PLC|LP|LLC|HOLDINGS?|GROUP)\b",
        " ", text,
    )
    return re.sub(r"\s+", "", text).strip()


def rank_z(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    observed = numeric.notna()
    result = pd.Series(0.0, index=series.index, dtype=float)
    if observed.any():
        percentile = numeric.loc[observed].rank(method="average", pct=True)
        clipped = percentile.clip(1e-3, 1 - 1e-3)
        values = pd.Series(norm.ppf(clipped), index=percentile.index).clip(-3.0, 3.0)
        result.loc[observed] = values
    return result


def safe_div(numerator: Any, denominator: Any) -> float:
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError):
        return math.nan
    if not np.isfinite(num) or not np.isfinite(den):
        return math.nan
    guard = max(1.0, abs(num) * 1e-6)
    if abs(den) < guard:
        return math.nan
    return num / den


def next_full_nyse_session(accepted: pd.Timestamp, sessions: Sequence[pd.Timestamp]) -> pd.Timestamp | pd.NaT:
    timestamp = pd.Timestamp(accepted)
    require(timestamp.tzinfo is not None, "ACCEPTED_DATETIME_TIMEZONE_MISSING", accepted)
    local_date = timestamp.tz_convert("America/New_York").tz_localize(None).normalize()
    ordered = pd.DatetimeIndex(pd.to_datetime(list(sessions))).tz_localize(None).normalize().unique().sort_values()
    position = ordered.searchsorted(local_date, side="right")
    return pd.NaT if position >= len(ordered) else pd.Timestamp(ordered[position])


def parse_accepted(series: pd.Series) -> pd.Series:
    raw = series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    compact = raw.str.replace(r"\D", "", regex=True)
    parsed = pd.to_datetime(compact.where(compact.str.len().ge(8)), format="%Y%m%d%H%M%S", errors="coerce")
    missing = parsed.isna()
    parsed.loc[missing] = pd.to_datetime(raw.loc[missing], errors="coerce")
    return parsed.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def normalize_accession(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value))
    if len(digits) != 18:
        return str(value).strip()
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def quarter_ids() -> list[str]:
    return [f"{period.year}q{period.quarter}" for period in pd.period_range("2018Q1", "2025Q4", freq="Q")]


def novelty_audit() -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = [
        REPO / "scripts" / "v21" / "v21_086_r1_fundamental_pit_and_quality_repair.py",
        SEC_STAGE_SOURCE,
        REPO / "scripts" / "v22" / "a2_sec_cik_identity_gap_close_and_deconcentration_autorun_r1.py",
        RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "final_report.md",
        REPO / "scripts" / "v22" / "a2_earnings_fundamental_change_alpha_r1.py",
    ]
    rows: list[dict[str, Any]] = []
    exact_requirements = (
        "companyfacts", "accepted", "raw_counterfactual", "2023", "2024", "top20", "accession",
    )
    exact_count = 0
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
        low = text.lower()
        # Textual overlap is not an economic duplicate.  A duplicate must also
        # contain completed numeric-fact economics, rather than an explicit
        # zero-coverage/NOT_RUN receipt such as the earlier earnings task.
        incomplete_tokens = (
            "not_run_zero_numeric_pit_fact_coverage", "data_coverage_limited",
            "materialized_numeric_information\": false", "numeric fact coverage is 0",
        )
        exact = all(token in low for token in exact_requirements) and not any(
            token in low for token in incomplete_tokens
        )
        exact_count += int(exact)
        if exact:
            classification = "EXACT_DUPLICATE"
        elif "fundamental" in low or "sec" in low:
            classification = "PARTIAL_OVERLAP"
        else:
            classification = "GENERIC_NAME_ONLY"
        if path.name.startswith("v21_086"):
            detail = "Provider cache; filing/report-date fallback; no accession/actual acceptance-time historical lineage."
        elif path.name == "stage_sec_pit_taxonomy.py":
            detail = "Official SEC accepted-time accession staging, but only CIK/SIC/FF12/FF48 taxonomy; no financial-change features."
        elif "cik_identity" in path.name:
            detail = "Deterministic CIK identity and taxonomy economics only; no companyfacts financial features."
        elif path.name == "a2_earnings_fundamental_change_alpha_r1.py":
            detail = (
                "Accepted-time/as-of/quarterization prototype; official numeric SEC fact coverage was zero, "
                "all fundamental portfolios were NOT_RUN, and no ML/outer/Primary economic result exists."
            )
        else:
            detail = "Taxonomy/deconcentration result; no SEC financial-statement feature model."
        rows.append({
            "research_surface": path.stem, "artifact_path": str(path),
            "source_sha256": sha256_file(path) if path.is_file() else "MISSING",
            "classification": classification, "sec_accession_aware": "accession" in low,
            "accepted_time_effective": "accepted" in low and "strictly after" in low,
            "historical_pit": "pit" in low, "clean_raw_counterfactual_labels": "raw_counterfactual" in low,
            "historical_oos_2023_2024": "2023" in low and "2024" in low,
            "top20_membership_economic_test": "top20" in low and ("sharpe" in low or "economic" in low),
            "notes": detail,
        })
    for family in FEATURE_FAMILIES:
        if family == "F5_FULL_BOUNDED":
            continue
        rows.append({
            "research_surface": family, "artifact_path": "NEW_CONTRACT",
            "source_sha256": "PENDING_CURRENT_SOURCE_HASH", "classification": "NOVEL_PIT_FEATURE",
            "sec_accession_aware": True, "accepted_time_effective": True, "historical_pit": True,
            "clean_raw_counterfactual_labels": True, "historical_oos_2023_2024": True,
            "top20_membership_economic_test": True,
            "notes": "New official-SEC accession/acceptance-time feature family under the fixed R1 contract.",
        })
    frame = pd.DataFrame(rows)
    facts = {
        "novelty_audit_status": "PASS_NOVEL" if exact_count == 0 else "STOP_EXACT_DUPLICATE",
        "exact_duplicate_count": exact_count,
        "partial_overlap_count": int(frame.classification.eq("PARTIAL_OVERLAP").sum()),
        "novel_core_feature_family_count": int(frame.classification.eq("NOVEL_PIT_FEATURE").sum()),
        "existing_a2_fundamental_lineage_status": (
            "PARTIAL_OVERLAP_PROVIDER_DIAGNOSTIC_AND_ZERO_NUMERIC_FACT_SEC_PROTOTYPE_NOT_RAW_A2_INPUT"
        ),
    }
    return frame, facts


def concept_contract() -> dict[str, Any]:
    payload = {
        "research_id": TASK,
        "status": "FROZEN_BEFORE_SEC_FACT_BUILD_AND_MODEL_FIT",
        "authoritative_source": "Official SEC companyfacts plus official SEC FSDS accession acceptance metadata",
        "accepted_datetime_rule": "first NYSE trading session strictly after EDGAR accepted datetime; never same-day",
        "forms": sorted(FORMS), "accepted_cutoff_et": "2025-12-31T23:59:59 America/New_York",
        "concept_priority": {key: list(value) for key, value in CONCEPT_PRIORITY.items()},
        "taxonomy": "us-gaap", "monetary_unit": "USD",
        "amendment_policy": "amendment facts effective only after amendment accession acceptance",
        "restatement_policy": "decision-date latest already-accepted accession; no backward fill",
        "period_policy": "current filing duration matched to same accession prior-year same fiscal-period duration; tolerance 10 days",
        "standalone_quarter_role": "DIAGNOSTIC_ONLY_NOT_PRIMARY",
        "denominator_guard": "abs(denominator)>=max(1 USD,1e-6*abs(numerator))",
        "dilution_feature_status": "DISABLED_SCALE_UNSAFE",
    }
    payload["contract_hash"] = stable_hash(payload)
    return payload


def preregistration(concept_hash: str, catboost_available: bool) -> dict[str, Any]:
    model_specs = [asdict(spec) for spec in candidate_model_specs(catboost_available=catboost_available)]
    payload: dict[str, Any] = {
        "research_id": TASK, "created_before_outer_read": True,
        "only_information_axis": "SEC_PIT_FINANCIAL_STATEMENT_CHANGE",
        "duplicate_stop_rule": "exact duplicate requires accession+accepted-time+historical PIT+clean labels+2023/2024+Top20 membership economics",
        "sec_data": {
            "source": "official SEC only", "cache": str(CACHE_ROOT), "cache_first": True,
            "max_requests_per_second": MAX_REQUEST_RATE, "retry_with_backoff": True,
            "feature_effective_rule": "first NYSE session strictly after accepted datetime",
            "start": "2018-01-01", "accepted_cutoff": "2025-12-31T23:59:59 ET",
        },
        "concept_contract_hash": concept_hash,
        "coverage_gate": {
            "covered_security_definition": "at least one usable derived feature in at least 3 of F0-F3",
            "raw_top40_median_min": 0.60, "decision_date_fraction_with_coverage_at_least_0_50_min": 0.75,
            "missing_policy": "keep eligible; per-date rank normalization; missing normalized values zero; missing indicators",
        },
        "labels": {
            "primary": "FF12 residual 20-session return", "diagnostics": ["ABS20", "WINNER60", "DOWNSIDE20"],
            "price_lineage": "continuous_raw_counterfactual", "max_label_end_date": "2025-12-31",
            "winner60": "same-date Raw Top40 candidate-set clean 60-session return Top10%",
        },
        "sample_weight": "inverse frequency within security_id+accession; normalized to mean one",
        "feature_families": FEATURE_FAMILIES,
        "structures": ["M0_FUNDAMENTAL_ONLY", "M1_RAW_PLUS_FUNDAMENTAL", "M2_RAW_PLUS_FUNDAMENTAL_RESIDUALIZED", "M3_RAW_PLUS_FUNDAMENTAL_WITH_FF12_FEATURE"],
        "m2_residualization": "three-fold decision-date cross-fit multivariate Ridge on Raw score, bounded price/volume controls, and FF12; final residualizer fit on training only",
        "models": model_specs,
        "candidate_buffer": "CURRENT_HOLDINGS_UNION_RAW_A2_TOP40",
        "raw_prior": "RawScoreZ + eta*FundamentalSignalZ", "eta": [0.10, 0.25, 0.50],
        "entry_protection": ["EP0_NO_HARD_PROTECTION", "EP1_RAW_TOP10_PROTECTED"],
        "portfolio": "Top20 equal 5%; gross 1; long-only; no cash/leverage/sizing/optimizer/hold-replace",
        "simple_baselines": {
            "C0": "AUTHORITATIVE_RAW_A2_TOP20_EQUAL", "C1": "SIMPLE_FUNDAMENTAL_COMPOSITE_ONLY_DIAGNOSTIC",
            "C2": "RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT_ETA_0.25", "C3": "RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT_ETA_0.25",
        },
        "temporal_firewall": {
            "feature_history": "2018-2019", "discovery_inner": "2020-2022 (A2 OOF usable 2021-2022)",
            "outer_1": 2023, "outer_2": 2024, "primary_freeze_before_2025": True,
            "2025": "exposed read-once diagnostic", "2026_plus": "prohibited",
            "purge": "label_end_date < validation_first_decision_date",
        },
        "inner_gates": {
            "incremental_ic_positive": True, "net_sharpe_delta_vs_raw_positive": True,
            "delta_vs_best_simple_min": -0.02, "coverage_pass": True,
            "no_catastrophic_fold": True, "cost_included": True, "raw_prior_preserved": True,
            "seed_stability": True,
        },
        "outer_gates": {
            "delta_sharpe_raw_each_fold_gt": 0.0, "delta_sharpe_best_simple_each_fold_min": 0.0,
            "pooled_delta_sharpe_raw_min": 0.05, "maxdd_worsening_pp_each_fold_max": 2.0,
            "net_cagr_delta_each_fold_min": -0.03, "winner_capture_delta_min": 0.0,
            "qqq_beta_material_increase_max": 0.10, "hhi_material_worsening_max": 0.02,
        },
        "search_budgets": {
            "max_unique_model_specs": MAX_UNIQUE_MODEL_SPECS, "max_total_model_fits": MAX_TOTAL_MODEL_FITS,
            "max_policy_specs": MAX_POLICY_SPECS, "max_outer_finalists": MAX_OUTER_FINALISTS,
            "max_ensembles": MAX_ENSEMBLES,
        },
        "vintage_concentration_gate": "Top3 filing vintages >50% of positive contribution => VINTAGE_CONCENTRATED_NO_PROMOTION",
        "automatic_promotion": False, "moomoo_api_allowed": False,
    }
    payload["contract_hash"] = stable_hash(payload)
    return payload


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    family: str
    structure: str
    feature_family: str
    params: dict[str, Any]


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    model_id: str
    eta: float
    entry_protection: str


@dataclass
class FittedModel:
    spec: ModelSpec
    estimator: Any
    numeric_features: list[str]
    categorical_features: list[str]
    residualizer: Any | None
    residual_control_columns: list[str]
    residual_feature_columns: list[str]
    max_feature_date: pd.Timestamp
    max_label_end_date: pd.Timestamp


class FitCounter:
    def __init__(self, initial: int = 0) -> None:
        self.total = initial

    def add(self, value: int = 1) -> None:
        self.total += value
        require(self.total <= MAX_TOTAL_MODEL_FITS, "MODEL_FIT_BUDGET", self.total)


def candidate_model_specs(catboost_available: bool) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    for feature_family in FEATURE_FAMILIES:
        specs.append(ModelSpec(f"RIDGE_M1_{feature_family}_A1", "RIDGE", "M1_RAW_PLUS_FUNDAMENTAL", feature_family, {"alpha": 1.0}))
        specs.append(ModelSpec(f"EN_M1_{feature_family}", "ELASTIC_NET", "M1_RAW_PLUS_FUNDAMENTAL", feature_family, {"alpha": 0.001, "l1_ratio": 0.2}))
    for structure in (
        "M0_FUNDAMENTAL_ONLY", "M1_RAW_PLUS_FUNDAMENTAL",
        "M2_RAW_PLUS_FUNDAMENTAL_RESIDUALIZED", "M3_RAW_PLUS_FUNDAMENTAL_WITH_FF12_FEATURE",
    ):
        for alpha in (0.1, 10.0):
            token = str(alpha).replace(".", "P")
            specs.append(ModelSpec(f"RIDGE_{structure}_F5_A{token}", "RIDGE", structure, "F5_FULL_BOUNDED", {"alpha": alpha}))
        for depth in (2, 3):
            specs.append(ModelSpec(f"HGB_{structure}_F5_D{depth}", "HGB", structure, "F5_FULL_BOUNDED", {"max_depth": depth, "max_iter": 150}))
        if catboost_available:
            specs.append(ModelSpec(f"CAT_{structure}_F5", "CATBOOST", structure, "F5_FULL_BOUNDED", {"depth": 4, "iterations": 200, "learning_rate": 0.03}))
    require(len(specs) <= MAX_UNIQUE_MODEL_SPECS, "MODEL_SPEC_BUDGET", len(specs))
    return specs


class SecCache:
    def __init__(self, root: Path, user_agent: str) -> None:
        self.root = root
        self.quarters = root / "quarters"
        self.database = root / "sec_raw_cache.sqlite"
        self.manifest_path = root / "cache_manifest.json"
        self.user_agent = user_agent
        self.request_count = 0
        self.cache_hit_count = 0
        self.last_request = 0.0
        self.root.mkdir(parents=True, exist_ok=True)
        self.quarters.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS responses (url TEXT PRIMARY KEY, status INTEGER NOT NULL, sha256 TEXT, fetched_utc TEXT, byte_size INTEGER, body_zlib BLOB, error TEXT)"
            )

    def _wait(self) -> None:
        delay = REQUEST_INTERVAL - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)

    def request(self, url: str, timeout: int = 180) -> bytes:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute("SELECT status, body_zlib, error FROM responses WHERE url=?", (url,)).fetchone()
        if row and int(row[0]) == 200 and row[1] is not None:
            self.cache_hit_count += 1
            return zlib.decompress(row[1])
        last_error = ""
        for attempt in (1, 2):
            try:
                self._wait()
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"})
                self.request_count += 1
                self.last_request = time.monotonic()
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    require(int(response.status) == 200, "SEC_HTTP_STATUS", (url, response.status))
                    payload = response.read()
                digest = hashlib.sha256(payload).hexdigest()
                with sqlite3.connect(self.database) as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?,?)",
                        (url, 200, digest, datetime.now(timezone.utc).isoformat(), len(payload), sqlite3.Binary(zlib.compress(payload, 6)), ""),
                    )
                return payload
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                if attempt == 1:
                    time.sleep(1.0)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?,?)",
                (url, 0, "", datetime.now(timezone.utc).isoformat(), 0, None, last_error),
            )
        raise GateFailure(f"SEC_REQUEST_FAILED:{url}:{last_error}")

    def quarter_payload(self, quarter: str) -> bytes:
        path = self.quarters / f"{quarter}.zip"
        if path.is_file():
            payload = path.read_bytes()
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    require(archive.testzip() is None, "SEC_ZIP_INTEGRITY", quarter)
                self.cache_hit_count += 1
                return payload
            except Exception:
                raise GateFailure(f"SEC_CACHE_CORRUPTION:{path}")
        payload = self.request(SEC_QUARTER_URL.format(quarter=quarter), timeout=240)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            require(archive.testzip() is None, "SEC_ZIP_INTEGRITY", quarter)
        temporary = path.with_suffix(".zip.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        return payload

    def write_manifest(self, extra: Mapping[str, Any]) -> dict[str, Any]:
        quarter_rows = []
        for path in sorted(self.quarters.glob("*.zip")):
            quarter_rows.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        with sqlite3.connect(self.database) as connection:
            row_count = int(connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0])
        payload = {
            "status": "PASS_CACHE_FIRST_DEDUPLICATED", "cache_path": str(self.root),
            "request_count_current_run": self.request_count, "cache_hit_count_current_run": self.cache_hit_count,
            "sqlite_response_count": row_count, "sqlite_sha256": sha256_file(self.database),
            "quarter_files": quarter_rows, "max_request_rate": MAX_REQUEST_RATE,
            "user_agent_source": str(SEC_STAGE_SOURCE), **dict(extra),
        }
        atomic_json(self.manifest_path, payload)
        return payload


def parse_sub_zip(payload: bytes, quarter: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = {name.lower(): name for name in archive.namelist()}
        key = next((name for name in names if name.endswith("sub.txt")), None)
        require(key is not None, "SEC_SUB_MISSING", quarter)
        with archive.open(names[key]) as stream:
            frame = pd.read_csv(stream, sep="\t", dtype="string", keep_default_na=False, low_memory=False)
    frame.columns = [str(column).lower().strip() for column in frame.columns]
    needed = ["adsh", "cik", "name", "sic", "form", "period", "fy", "fp", "filed", "accepted", "instance"]
    for column in needed:
        if column not in frame:
            frame[column] = pd.NA
    frame = frame[needed].copy()
    frame["adsh"] = frame.adsh.map(normalize_accession)
    frame["cik"] = pd.to_numeric(frame.cik, errors="coerce").astype("Int64")
    frame["filed_date"] = pd.to_datetime(frame.filed, format="%Y%m%d", errors="coerce")
    frame["period_date"] = pd.to_datetime(frame.period, format="%Y%m%d", errors="coerce")
    frame["accepted_datetime"] = parse_accepted(frame.accepted)
    frame["quarter"] = quarter.upper()
    return frame.drop(columns=["filed", "period", "accepted"]).drop_duplicates("adsh", keep="last")


def load_sec_submissions(cache: SecCache) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    covered: set[str] = set()
    missing_quarters: list[str] = []
    network_failures: list[dict[str, str]] = []
    if PRIOR_SEC_SUB.is_file() and PRIOR_SEC_MANIFEST.is_file():
        prior_manifest = json.loads(PRIOR_SEC_MANIFEST.read_text(encoding="utf-8"))
        require(prior_manifest.get("status") == "PASS_COMPLETE", "PRIOR_SEC_STAGE_STATUS")
        require(sha256_file(PRIOR_SEC_SUB) == prior_manifest.get("sec_fsds_sub_min_sha256"), "PRIOR_SEC_STAGE_HASH")
        prior = pd.read_parquet(PRIOR_SEC_SUB)
        prior = prior.rename(columns={"accepted_timestamp_utc": "accepted_datetime", "filed": "filed_date"})
        prior["period_date"] = pd.to_datetime(prior.period.astype("string"), format="%Y%m%d", errors="coerce")
        prior = prior.drop(columns=["period"], errors="ignore")
        pieces.append(prior)
        covered = set(prior.quarter.astype(str).str.lower().unique())
        cache.cache_hit_count += len(covered)
    uncovered = [quarter for quarter in quarter_ids() if quarter.lower() not in covered]
    consecutive_network_failures = 0
    for position, quarter in enumerate(uncovered):
        try:
            payload = cache.quarter_payload(quarter)
        except GateFailure as exc:
            if "SEC_REQUEST_FAILED" not in str(exc):
                raise
            missing_quarters.append(quarter)
            network_failures.append({"quarter": quarter, "failure": str(exc)})
            consecutive_network_failures += 1
            if consecutive_network_failures >= 3:
                missing_quarters.extend(uncovered[position + 1:])
                break
            continue
        pieces.append(parse_sub_zip(payload, quarter))
        consecutive_network_failures = 0
    frame = pd.concat(pieces, ignore_index=True)
    frame = frame.loc[frame.form.astype(str).isin(FORMS)].copy()
    frame = frame.loc[frame.accepted_datetime.notna() & frame.accepted_datetime.ge(SEC_START.tz_localize("America/New_York").tz_convert("UTC")) & frame.accepted_datetime.lt(SEC_CUTOFF_UTC)]
    frame = frame.sort_values(["accepted_datetime", "cik", "adsh"], kind="mergesort").drop_duplicates("adsh", keep="last")
    require(not frame.empty, "SEC_SUBMISSIONS_EMPTY")
    frame = frame.reset_index(drop=True)
    frame.attrs["missing_quarters"] = missing_quarters
    frame.attrs["network_failures"] = network_failures
    return frame


def company_tickers(cache: SecCache) -> pd.DataFrame:
    payload = cache.request(SEC_COMPANY_TICKERS_URL, timeout=90)
    data = json.loads(payload.decode("utf-8"))
    rows = list(data.values()) if isinstance(data, dict) else list(data)
    frame = pd.DataFrame(rows).rename(columns={"cik_str": "cik", "title": "sec_title"})
    require({"cik", "ticker", "sec_title"}.issubset(frame.columns), "SEC_COMPANY_TICKERS_SCHEMA")
    frame = frame[["cik", "ticker", "sec_title"]].copy()
    frame["cik"] = pd.to_numeric(frame.cik, errors="coerce").astype("Int64")
    frame["ticker"] = frame.ticker.astype(str).str.upper().str.strip()
    frame["normalized_name"] = frame.sec_title.map(normalize_name)
    return frame


def build_cik_mapping(universe: pd.DataFrame, submissions: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    identities = universe[["security_id", "cusip", "ticker", "issuer_name", "effective_start", "effective_end", "mapping_source", "mapping_confidence"]].drop_duplicates().copy()
    identities["ticker"] = identities.ticker.astype(str).str.upper().str.strip()
    identities["normalized_name"] = identities.issuer_name.map(normalize_name)
    name_rows = submissions[["cik", "name", "accepted_datetime"]].dropna(subset=["cik", "name"]).copy()
    name_rows["normalized_name"] = name_rows.name.map(normalize_name)
    name_counts = name_rows.groupby("normalized_name").cik.nunique()
    unique_names = set(name_counts.index[name_counts.eq(1)])
    name_map = name_rows.loc[name_rows.normalized_name.isin(unique_names)].sort_values("accepted_datetime").drop_duplicates("normalized_name").set_index("normalized_name")
    ticker_name = tickers.groupby("ticker", as_index=False).filter(lambda x: x.cik.nunique() == 1).set_index("ticker")
    prior = pd.read_parquet(PRIOR_CIK_BRIDGE) if PRIOR_CIK_BRIDGE.is_file() else pd.DataFrame()
    if not prior.empty:
        prior["ticker"] = prior.ticker.astype(str).str.upper()
        prior = prior.loc[prior.full_required_date_coverage.astype(bool)].drop_duplicates("ticker").set_index("ticker")
    rows = []
    for row in identities.itertuples(index=False):
        cik: int | None = None
        source = "UNRESOLVED"
        confidence = "UNRESOLVED"
        evidence = ""
        effective = pd.NaT
        ticker = str(row.ticker)
        normalized = str(row.normalized_name)
        if not prior.empty and ticker in prior.index:
            item = prior.loc[ticker]
            if isinstance(item, pd.DataFrame):
                item = item.iloc[0]
            cik = int(item.cik)
            source = "EXISTING_A2_SEC_CIK_BRIDGE"
            confidence = "A_EXISTING_AUDITED"
            effective = pd.Timestamp(item.cik_effective_start)
            evidence = str(item.mapping_evidence)
        elif normalized in name_map.index:
            item = name_map.loc[normalized]
            cik = int(item.cik)
            source = "SEC_SUBMISSION_LEGAL_NAME_EXACT_UNIQUE"
            confidence = "B_HISTORICAL_EXACT_NAME"
            effective = pd.Timestamp(item.accepted_datetime).tz_convert("America/New_York").tz_localize(None).normalize()
            evidence = str(item["name"])
        elif ticker in ticker_name.index:
            item = ticker_name.loc[ticker]
            if isinstance(item, pd.DataFrame):
                item = item.iloc[0]
            if normalize_name(row.issuer_name) == str(item.normalized_name):
                cik = int(item.cik)
                source = "SEC_COMPANY_TICKER_AND_NAME_EXACT"
                confidence = "C_CURRENT_TICKER_NAME_EXACT"
                accepted = submissions.loc[submissions.cik.eq(cik), "accepted_datetime"]
                effective = accepted.min().tz_convert("America/New_York").tz_localize(None).normalize() if len(accepted) else pd.NaT
                evidence = str(item.sec_title)
        rows.append({
            "security_id": str(row.security_id), "cusip": str(row.cusip), "ticker": ticker,
            "issuer_name": str(row.issuer_name), "cik": cik, "mapping_source": source,
            "mapping_confidence": confidence, "mapping_effective_date": effective,
            "identity_effective_start": pd.Timestamp(row.effective_start),
            "identity_effective_end": pd.Timestamp(row.effective_end), "mapping_evidence": evidence,
        })
    result = pd.DataFrame(rows)
    result["cik"] = pd.to_numeric(result.cik, errors="coerce").astype("Int64")
    return result


def companyfacts_records(payload: bytes, cik: int, source_sha: str) -> pd.DataFrame:
    data = json.loads(payload.decode("utf-8"))
    records: list[dict[str, Any]] = []
    allowed = {concept for values in CONCEPT_PRIORITY.values() for concept in values}
    for taxonomy, concepts in data.get("facts", {}).items():
        if taxonomy != "us-gaap":
            continue
        for concept, block in concepts.items():
            if concept not in allowed:
                continue
            for unit, observations in block.get("units", {}).items():
                if unit != "USD":
                    continue
                for item in observations:
                    form = str(item.get("form", ""))
                    if form not in FORMS:
                        continue
                    filed = str(item.get("filed") or "")
                    if filed and (filed < "2018-01-01" or filed > "2025-12-31"):
                        continue
                    records.append({
                        "cik": cik, "concept": concept, "taxonomy": taxonomy, "unit": unit,
                        "start_date": item.get("start"), "end_date": item.get("end"),
                        "raw_value": item.get("val"),
                        "accession": normalize_accession(item.get("accn", "")),
                        "fiscal_year": item.get("fy"), "fiscal_period": item.get("fp"),
                        "form": form, "filed_date_fact": filed,
                        "frame": item.get("frame", ""), "source_sha256": source_sha,
                        "source_url_id": f"companyfacts/CIK{cik:010d}",
                    })
    frame = pd.DataFrame(records)
    if not frame.empty:
        for column in ("start_date", "end_date", "filed_date_fact"):
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
        frame["raw_value"] = pd.to_numeric(frame.raw_value, errors="coerce")
    return frame


def _array_value(values: Any, position: int) -> Any:
    return values[position] if isinstance(values, list) and position < len(values) else None


def submission_document_rows(
    document: Mapping[str, Any], cik: int, issuer_name: str, sic: Any,
    source_entry: str, source_sha256: str,
) -> pd.DataFrame:
    filing = document.get("filings", {}).get("recent", {}) if "filings" in document else document
    accessions = filing.get("accessionNumber", [])
    rows: list[dict[str, Any]] = []
    for position, accession in enumerate(accessions if isinstance(accessions, list) else []):
        form = str(_array_value(filing.get("form"), position) or "")
        if form not in FORMS:
            continue
        accepted = pd.to_datetime(_array_value(filing.get("acceptanceDateTime"), position), utc=True, errors="coerce")
        if pd.isna(accepted) or accepted < SEC_START.tz_localize("America/New_York").tz_convert("UTC") or accepted >= SEC_CUTOFF_UTC:
            continue
        rows.append({
            "adsh": normalize_accession(accession), "cik": int(cik), "name": issuer_name,
            "sic": sic, "form": form,
            "period_date": pd.to_datetime(_array_value(filing.get("reportDate"), position), errors="coerce"),
            "fy": pd.NA, "fp": pd.NA,
            "filed_date": pd.to_datetime(_array_value(filing.get("filingDate"), position), errors="coerce"),
            "accepted_datetime": accepted, "instance": str(_array_value(filing.get("primaryDocument"), position) or ""),
            "quarter": "SUBMISSIONS_BULK", "accepted_source_entry": source_entry,
            "accepted_source_sha256": source_sha256,
        })
    return pd.DataFrame(rows)


def _zip_index_row(archive_name: str, info: zipfile.ZipInfo, cik: int, role: str) -> dict[str, Any]:
    return {
        "archive": archive_name, "entry": info.filename, "cik": int(cik), "role": role,
        "compressed_bytes": int(info.compress_size), "uncompressed_bytes": int(info.file_size),
        "crc32": f"{int(info.CRC):08x}",
    }


def read_relevant_bulk_submissions(
    path: Path, resolved_ciks: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pieces: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.NameToInfo
        for number, cik in enumerate(sorted(set(int(value) for value in resolved_ciks)), 1):
            primary = f"CIK{cik:010d}.json"
            info = names.get(primary)
            if info is None:
                audit.append({"record_type": "SUBMISSIONS_BULK_CIK", "cik": cik, "status": "MISSING_PRIMARY_ENTRY", "filing_rows": 0})
                continue
            payload = archive.read(info)
            digest = hashlib.sha256(payload).hexdigest()
            document = json.loads(payload)
            issuer_name = str(document.get("name", ""))
            sic = document.get("sic")
            frame = submission_document_rows(document, cik, issuer_name, sic, primary, digest)
            if not frame.empty:
                pieces.append(frame)
            index_rows.append(_zip_index_row(path.name, info, cik, "PRIMARY_SUBMISSION"))
            old_loaded = 0
            for descriptor in document.get("filings", {}).get("files", []):
                filing_to = pd.to_datetime(descriptor.get("filingTo"), errors="coerce")
                filing_from = pd.to_datetime(descriptor.get("filingFrom"), errors="coerce")
                if pd.isna(filing_to) or filing_to < SEC_START or (pd.notna(filing_from) and filing_from > LABEL_CUTOFF):
                    continue
                entry = str(descriptor.get("name", ""))
                old_info = names.get(entry)
                if old_info is None:
                    audit.append({"record_type": "SUBMISSIONS_BULK_HISTORY", "cik": cik, "status": "MISSING_REFERENCED_ENTRY", "entry": entry})
                    continue
                old_payload = archive.read(old_info)
                old_digest = hashlib.sha256(old_payload).hexdigest()
                old_frame = submission_document_rows(json.loads(old_payload), cik, issuer_name, sic, entry, old_digest)
                if not old_frame.empty:
                    pieces.append(old_frame)
                index_rows.append(_zip_index_row(path.name, old_info, cik, "HISTORICAL_SUBMISSION"))
                old_loaded += 1
            audit.append({
                "record_type": "SUBMISSIONS_BULK_CIK", "cik": cik, "status": "PASS_SELECTIVE_READ",
                "filing_rows": int(len(frame)), "historical_entries_loaded": old_loaded,
                "source_sha256": digest,
            })
            if number % 250 == 0:
                print(f"SEC_BULK_SUBMISSIONS_PROGRESS={number}/{len(resolved_ciks)}", flush=True)
    submissions = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=[
        "adsh", "cik", "name", "sic", "form", "period_date", "fy", "fp", "filed_date",
        "accepted_datetime", "instance", "quarter", "accepted_source_entry", "accepted_source_sha256",
    ])
    if not submissions.empty:
        submissions["accepted_datetime"] = pd.to_datetime(submissions.accepted_datetime, utc=True)
        conflicts = submissions.groupby("adsh").accepted_datetime.nunique().gt(1)
        require(not conflicts.any(), "ACCEPTED_DATETIME_PIT_FAILURE", "ACCESSION_ACCEPTANCE_CONFLICT")
        submissions = submissions.sort_values(["accepted_datetime", "adsh"], kind="mergesort").drop_duplicates("adsh", keep="last")
    return submissions.reset_index(drop=True), pd.DataFrame(audit), pd.DataFrame(index_rows)


def read_relevant_bulk_companyfacts(
    path: Path, resolved_ciks: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pieces: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.NameToInfo
        for number, cik in enumerate(sorted(set(int(value) for value in resolved_ciks)), 1):
            entry = f"CIK{cik:010d}.json"
            info = names.get(entry)
            if info is None:
                audit.append({"record_type": "CIK_FETCH", "cik": cik, "status": "MISSING_COMPANYFACTS_ENTRY", "fact_rows": 0})
                continue
            payload = archive.read(info)
            digest = hashlib.sha256(payload).hexdigest()
            frame = companyfacts_records(payload, cik, digest)
            if not frame.empty:
                frame["source_url_id"] = f"companyfacts.zip!{entry}"
                pieces.append(frame)
            audit.append({
                "record_type": "CIK_FETCH", "cik": cik, "status": "PASS_BULK_SELECTIVE_READ",
                "fact_rows": int(len(frame)), "source_sha256": digest,
            })
            index_rows.append(_zip_index_row(path.name, info, cik, "COMPANYFACTS"))
            if number % 250 == 0:
                print(f"SEC_BULK_COMPANYFACTS_PROGRESS={number}/{len(resolved_ciks)}", flush=True)
    facts = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=[
        "cik", "concept", "taxonomy", "unit", "start_date", "end_date", "raw_value", "accession",
        "fiscal_year", "fiscal_period", "form", "filed_date_fact", "frame", "source_sha256", "source_url_id",
    ])
    return facts, pd.DataFrame(audit), pd.DataFrame(index_rows)


def load_bulk_sec_data(
    snapshot: Mapping[str, Any], mapping_sha256: str, resolved_ciks: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    BULK_DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    paths = {
        "submissions": BULK_DERIVED_ROOT / "relevant_submissions.parquet",
        "facts": BULK_DERIVED_ROOT / "relevant_companyfacts.parquet",
        "audit": BULK_DERIVED_ROOT / "bulk_read_audit.parquet",
        "index": BULK_DERIVED_ROOT / "relevant_zip_index.parquet",
    }
    manifest_path = BULK_DERIVED_ROOT / "bulk_parse_manifest.json"
    cache_key = stable_hash({
        "snapshot_contract_hash": snapshot["snapshot_contract_hash"],
        "mapping_sha256": mapping_sha256, "resolved_ciks": list(sorted(set(resolved_ciks))),
        "concept_priority": CONCEPT_PRIORITY, "forms": sorted(FORMS), "cutoff": str(SEC_CUTOFF_UTC),
    })
    if manifest_path.is_file() and all(path.is_file() for path in paths.values()):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("cache_key") == cache_key and all(
            sha256_file(paths[name]) == manifest.get("files", {}).get(name, {}).get("sha256") for name in paths
        ):
            return (
                pd.read_parquet(paths["facts"]), pd.read_parquet(paths["submissions"]),
                pd.read_parquet(paths["audit"]), pd.read_parquet(paths["index"]),
                {"status": "PASS_HASHED_DERIVED_CACHE_HIT", "cache_hit_count": 4, "manifest_path": manifest_path},
            )
    submissions, submission_audit, submission_index = read_relevant_bulk_submissions(SUBMISSIONS_BULK, resolved_ciks)
    facts, fact_audit, fact_index = read_relevant_bulk_companyfacts(COMPANYFACTS_BULK, resolved_ciks)
    audit = pd.concat([submission_audit, fact_audit], ignore_index=True, sort=False)
    index = pd.concat([submission_index, fact_index], ignore_index=True, sort=False)
    atomic_parquet(paths["submissions"], submissions)
    atomic_parquet(paths["facts"], facts)
    atomic_parquet(paths["audit"], audit)
    atomic_parquet(paths["index"], index)
    manifest = {
        "status": "PASS_SELECTIVE_ZIP_READ_NO_FULL_EXTRACTION", "cache_key": cache_key,
        "resolved_cik_count": len(set(resolved_ciks)),
        "files": {name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for name, path in paths.items()},
    }
    atomic_json(manifest_path, manifest)
    return facts, submissions, audit, index, {"status": manifest["status"], "cache_hit_count": 0, "manifest_path": manifest_path}


def fetch_companyfacts(cache: SecCache, ciks: Iterable[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    pieces: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    cik_list = sorted(set(int(value) for value in ciks))
    consecutive_network_failures = 0
    for number, cik in enumerate(cik_list, 1):
        url = SEC_COMPANYFACTS_URL.format(cik=cik)
        try:
            payload = cache.request(url, timeout=120)
            digest = hashlib.sha256(payload).hexdigest()
            frame = companyfacts_records(payload, cik, digest)
            if not frame.empty:
                pieces.append(frame)
            audit.append({"record_type": "CIK_FETCH", "cik": cik, "status": "PASS", "fact_rows": len(frame), "source_sha256": digest})
            consecutive_network_failures = 0
        except Exception as exc:
            audit.append({"record_type": "CIK_FETCH", "cik": cik, "status": "FAILED_CONTINUE", "fact_rows": 0, "failure_reason": f"{type(exc).__name__}:{exc}"})
            consecutive_network_failures += 1
            if consecutive_network_failures >= 3:
                for remaining in cik_list[number:]:
                    audit.append({"record_type": "CIK_FETCH", "cik": remaining, "status": "SKIPPED_SYSTEMIC_SEC_NETWORK_GATE", "fact_rows": 0, "failure_reason": "three consecutive official SEC request failures"})
                break
        if number % 100 == 0:
            print(f"SEC_COMPANYFACTS_PROGRESS={number}/{len(cik_list)}", flush=True)
    facts = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=[
        "cik", "concept", "taxonomy", "unit", "start_date", "end_date", "raw_value", "accession",
        "fiscal_year", "fiscal_period", "form", "filed_date_fact", "frame", "source_sha256", "source_url_id",
    ])
    return facts, pd.DataFrame(audit)


def _duration_target(fp: str) -> int:
    return {"Q1": 91, "Q2": 182, "Q3": 273, "FY": 365}.get(str(fp).upper(), 365)


def select_duration_pair(records: pd.DataFrame, concepts: Sequence[str], period: pd.Timestamp, fp: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for concept in concepts:
        candidates = records.loc[
            records.concept.eq(concept) & records.start_date.notna() & records.end_date.eq(period)
        ].copy()
        if candidates.empty:
            continue
        candidates["duration_days"] = (candidates.end_date - candidates.start_date).dt.days
        candidates["duration_distance"] = (candidates.duration_days - _duration_target(fp)).abs()
        current = candidates.sort_values(["duration_distance", "start_date"], kind="mergesort").iloc[0]
        same_current = candidates.loc[
            candidates.start_date.eq(current.start_date) & candidates.end_date.eq(current.end_date)
        ]
        if same_current.raw_value.dropna().nunique() > 1:
            continue
        current = same_current.sort_values(["filed_date_fact", "frame"], kind="mergesort").iloc[-1]
        prior_candidates = records.loc[
            records.concept.eq(concept) & records.start_date.notna() &
            records.end_date.between(period - pd.Timedelta(days=380), period - pd.Timedelta(days=350))
        ].copy()
        if prior_candidates.empty:
            return current.to_dict(), None
        prior_candidates["duration_days"] = (prior_candidates.end_date - prior_candidates.start_date).dt.days
        prior_candidates = prior_candidates.loc[(prior_candidates.duration_days - current.duration_days).abs().le(10)]
        if prior_candidates.empty:
            return current.to_dict(), None
        prior_candidates["end_distance"] = (prior_candidates.end_date - (period - pd.DateOffset(years=1))).abs().dt.days
        prior = prior_candidates.sort_values(["end_distance", "start_date"], kind="mergesort").iloc[0]
        same_prior = prior_candidates.loc[
            prior_candidates.start_date.eq(prior.start_date) & prior_candidates.end_date.eq(prior.end_date)
        ]
        if same_prior.raw_value.dropna().nunique() > 1:
            return current.to_dict(), None
        prior = same_prior.sort_values(["filed_date_fact", "frame"], kind="mergesort").iloc[-1]
        return current.to_dict(), prior.to_dict()
    return None, None


def select_instant_pair(records: pd.DataFrame, concepts: Sequence[str], period: pd.Timestamp) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for concept in concepts:
        current_rows = records.loc[records.concept.eq(concept) & records.start_date.isna() & records.end_date.eq(period)]
        if current_rows.empty:
            continue
        if current_rows.raw_value.dropna().nunique() > 1:
            continue
        current = current_rows.sort_values("filed_date_fact", kind="mergesort").iloc[-1]
        prior_rows = records.loc[
            records.concept.eq(concept) & records.start_date.isna() &
            records.end_date.between(period - pd.Timedelta(days=380), period - pd.Timedelta(days=350))
        ].copy()
        if prior_rows.empty:
            return current.to_dict(), None
        prior_rows["end_distance"] = (prior_rows.end_date - (period - pd.DateOffset(years=1))).abs().dt.days
        prior = prior_rows.sort_values("end_distance", kind="mergesort").iloc[0]
        same_prior = prior_rows.loc[prior_rows.end_date.eq(prior.end_date)]
        if same_prior.raw_value.dropna().nunique() > 1:
            return current.to_dict(), None
        prior = same_prior.sort_values(["filed_date_fact", "frame"], kind="mergesort").iloc[-1]
        return current.to_dict(), prior.to_dict()
    return None, None


def fact_value(fact: dict[str, Any] | None) -> float:
    return math.nan if fact is None else float(fact.get("raw_value", math.nan))


def fact_lineage(fact: dict[str, Any] | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {
        key: fact.get(key) for key in (
            "concept", "taxonomy", "unit", "start_date", "end_date", "fiscal_year",
            "fiscal_period", "form", "accession", "filed_date_fact", "raw_value",
            "source_url_id", "source_sha256",
        )
    }


def build_feature_states(facts: pd.DataFrame, submissions: pd.DataFrame, sessions: Sequence[pd.Timestamp]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if facts.empty:
        return pd.DataFrame(), {"restatement_guard_status": "PASS_NO_FACTS", "unit_scale_status": "PASS_NO_FACTS"}
    sub_columns = [
        "adsh", "cik", "name", "form", "period_date", "fy", "fp", "filed_date", "accepted_datetime",
        "accepted_source_entry", "accepted_source_sha256",
    ]
    sub = submissions[[column for column in sub_columns if column in submissions]].copy()
    for column in sub_columns:
        if column not in sub:
            sub[column] = pd.NA
    sub = sub.rename(columns={"form": "filing_form"})
    merged = facts.merge(sub, left_on=["accession", "cik"], right_on=["adsh", "cik"], how="inner", validate="many_to_one")
    merged = merged.loc[merged.accepted_datetime.lt(SEC_CUTOFF_UTC) & merged.unit.eq("USD")].copy()
    fact_base_form = merged.form.astype(str).str.replace("/A", "", regex=False)
    filing_base_form = merged.filing_form.astype(str).str.replace("/A", "", regex=False)
    require(fact_base_form.eq(filing_base_form).all(), "SEC_FACT_LINEAGE_FAILURE", "FACT_BASE_FORM_ACCESSION_MISMATCH")
    amendment_form_alias_count = int(merged.form.ne(merged.filing_form).sum())
    merged["fp"] = merged.fp.where(merged.fp.notna(), merged.fiscal_period)
    merged["fy"] = merged.fy.where(merged.fy.notna(), merged.fiscal_year)
    rows: list[dict[str, Any]] = []
    for (cik, accession), group in merged.groupby(["cik", "accession"], sort=False):
        header = group.iloc[0]
        period = pd.Timestamp(header.period_date)
        if pd.isna(period):
            continue
        selected: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
        for category, concepts in CONCEPT_PRIORITY.items():
            if category in INSTANT_CATEGORIES:
                selected[category] = select_instant_pair(group, concepts, period)
            else:
                selected[category] = select_duration_pair(group, concepts, period, str(header.fp))
        current = {key: fact_value(pair[0]) for key, pair in selected.items()}
        prior = {key: fact_value(pair[1]) for key, pair in selected.items()}
        rev_yoy = safe_div(current["revenue"], prior["revenue"])
        rev_yoy = rev_yoy - 1.0 if np.isfinite(rev_yoy) else math.nan
        gross_margin = safe_div(current["gross_profit"], current["revenue"])
        gross_margin_prior = safe_div(prior["gross_profit"], prior["revenue"])
        op_margin = safe_div(current["operating_income"], current["revenue"])
        op_margin_prior = safe_div(prior["operating_income"], prior["revenue"])
        net_margin = safe_div(current["net_income"], current["revenue"])
        net_margin_prior = safe_div(prior["net_income"], prior["revenue"])
        cfo_margin = safe_div(current["operating_cash_flow"], current["revenue"])
        cfo_margin_prior = safe_div(prior["operating_cash_flow"], prior["revenue"])
        fcf = current["operating_cash_flow"] - current["capital_expenditure"] if np.isfinite(current["operating_cash_flow"]) and np.isfinite(current["capital_expenditure"]) else math.nan
        fcf_prior = prior["operating_cash_flow"] - prior["capital_expenditure"] if np.isfinite(prior["operating_cash_flow"]) and np.isfinite(prior["capital_expenditure"]) else math.nan
        fcf_margin = safe_div(fcf, current["revenue"])
        fcf_margin_prior = safe_div(fcf_prior, prior["revenue"])
        asset_growth = safe_div(current["assets"], prior["assets"])
        asset_growth = asset_growth - 1.0 if np.isfinite(asset_growth) else math.nan
        rd = safe_div(current["research_and_development"], current["revenue"])
        rd_prior = safe_div(prior["research_and_development"], prior["revenue"])
        sbc = safe_div(current["share_based_compensation"], current["revenue"])
        sbc_prior = safe_div(prior["share_based_compensation"], prior["revenue"])
        effective = next_full_nyse_session(pd.Timestamp(header.accepted_datetime), sessions)
        if pd.isna(effective):
            continue
        lineage = {category: {"current": fact_lineage(pair[0]), "prior": fact_lineage(pair[1])} for category, pair in selected.items()}
        numeric = {
            "revenue_yoy": rev_yoy,
            "gross_margin": gross_margin,
            "gross_margin_yoy_change": gross_margin - gross_margin_prior if np.isfinite(gross_margin) and np.isfinite(gross_margin_prior) else math.nan,
            "operating_margin": op_margin,
            "operating_margin_yoy_change": op_margin - op_margin_prior if np.isfinite(op_margin) and np.isfinite(op_margin_prior) else math.nan,
            "net_margin": net_margin,
            "net_margin_yoy_change": net_margin - net_margin_prior if np.isfinite(net_margin) and np.isfinite(net_margin_prior) else math.nan,
            "operating_cash_flow_margin": cfo_margin,
            "operating_cash_flow_margin_change": cfo_margin - cfo_margin_prior if np.isfinite(cfo_margin) and np.isfinite(cfo_margin_prior) else math.nan,
            "free_cash_flow_margin": fcf_margin,
            "free_cash_flow_margin_change": fcf_margin - fcf_margin_prior if np.isfinite(fcf_margin) and np.isfinite(fcf_margin_prior) else math.nan,
            "cfo_to_net_income": safe_div(current["operating_cash_flow"], current["net_income"]),
            "accrual_quality": safe_div(current["net_income"] - current["operating_cash_flow"] if np.isfinite(current["net_income"]) and np.isfinite(current["operating_cash_flow"]) else math.nan, abs(current["assets"])),
            "asset_growth_yoy": asset_growth,
            "rd_to_revenue": rd,
            "rd_intensity_change": rd - rd_prior if np.isfinite(rd) and np.isfinite(rd_prior) else math.nan,
            "sbc_to_revenue": sbc,
            "sbc_intensity_change": sbc - sbc_prior if np.isfinite(sbc) and np.isfinite(sbc_prior) else math.nan,
            "filing_lag_days": float((pd.Timestamp(header.accepted_datetime).tz_convert("America/New_York").tz_localize(None).normalize() - period).days),
            "amendment_indicator": float(str(header.filing_form).endswith("/A")),
        }
        numeric_count = sum(np.isfinite(value) for value in numeric.values())
        row = {
            "cik": int(cik), "accession": accession, "issuer_name": str(header["name"]),
            "form": str(header.filing_form), "filed_date": pd.Timestamp(header.filed_date),
            "accepted_datetime": pd.Timestamp(header.accepted_datetime), "feature_effective_date": effective,
            "fiscal_year": str(header.fy), "fiscal_period": str(header.fp), "period_end_date": period,
            **numeric, "concept_switch_indicator": 0.0,
            "fact_coverage_ratio": numeric_count / max(1, len(numeric)),
            "lineage_hash": stable_hash(lineage), "fact_lineage_json": json.dumps(lineage, sort_keys=True, default=str),
            "source_url_id": next((str(value) for value in group.source_url_id.dropna().unique()), f"companyfacts/CIK{int(cik):010d}"),
            "source_sha256": next((str(value) for value in group.source_sha256.dropna().unique()), ""),
            "accepted_source_entry": str(header.accepted_source_entry),
            "accepted_source_sha256": str(header.accepted_source_sha256),
            "corporate_action_scale_consistent": True,
        }
        row["revenue_concept"] = selected["revenue"][0].get("concept") if selected["revenue"][0] else ""
        rows.append(row)
    states = pd.DataFrame(rows)
    if states.empty:
        return states, {"restatement_guard_status": "PASS_NO_USABLE_STATES", "unit_scale_status": "PASS_USD_ONLY"}
    states = states.sort_values(["cik", "accepted_datetime", "accession"], kind="mergesort")
    states["previous_revenue_yoy"] = states.groupby("cik").revenue_yoy.shift(1)
    states["revenue_yoy_change_vs_prior_filing"] = states.revenue_yoy - states.previous_revenue_yoy
    states["revenue_growth_acceleration"] = states.revenue_yoy_change_vs_prior_filing
    previous_concept = states.groupby("cik").revenue_concept.shift(1)
    states["concept_switch_indicator"] = (previous_concept.notna() & states.revenue_concept.ne(previous_concept)).astype(float)
    states["fact_coverage_ratio"] = states[FEATURE_FAMILIES["F5_FULL_BOUNDED"]].notna().mean(axis=1)
    require(states.accepted_datetime.lt(SEC_CUTOFF_UTC).all(), "2026_FILING_EXCLUSION")
    require((states.feature_effective_date > states.accepted_datetime.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()).all(), "ACCEPTED_DATETIME_PIT_FAILURE")
    return states.reset_index(drop=True), {
        "restatement_guard_status": "PASS_ACCESSION_ASOF_NO_BACKFILL",
        "unit_scale_status": "PASS_USD_ONLY",
        "pit_effective_date_status": "PASS_STRICT_NEXT_NYSE_SESSION",
        "companyfacts_amendment_form_alias_count": amendment_form_alias_count,
        "companyfacts_base_form_mismatch_count": 0,
    }


def load_or_build_feature_states(
    facts: pd.DataFrame,
    submissions: pd.DataFrame,
    sessions: Sequence[pd.Timestamp],
    cache_key: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resume the expensive accession-level PIT reduction from a hash-valid cache."""
    state_path = BULK_DERIVED_ROOT / "fundamental_feature_states.parquet"
    manifest_path = BULK_DERIVED_ROOT / "fundamental_feature_states_manifest.json"
    if manifest_path.exists() and state_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("cache_version") == FEATURE_STATE_CACHE_VERSION
            and manifest.get("cache_key") == cache_key
            and manifest.get("state_sha256") == sha256_file(state_path)
        ):
            states = pd.read_parquet(state_path)
            require(len(states) == int(manifest["state_rows"]), "SEC_FACT_LINEAGE_FAILURE", "STATE_CACHE_ROW_COUNT")
            return states, dict(manifest["lineage_facts"])
    states, lineage_facts = build_feature_states(facts, submissions, sessions)
    atomic_parquet(state_path, states)
    atomic_json(manifest_path, {
        "research_id": TASK,
        "cache_version": FEATURE_STATE_CACHE_VERSION,
        "cache_key": cache_key,
        "state_path": str(state_path),
        "state_rows": len(states),
        "state_sha256": sha256_file(state_path),
        "lineage_facts": lineage_facts,
        "status": "PASS_HASH_VALID_DURABLE_PREFIT_CHECKPOINT",
    })
    return states, lineage_facts


def build_feature_ledger(states: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "security_id", "ticker", "cusip", "cik", "mapping_source", "mapping_confidence",
        "mapping_effective_date", "accession", "issuer_name", "form", "filed_date",
        "accepted_datetime", "feature_effective_date", "fiscal_year", "fiscal_period",
        "period_end_date", *FEATURE_FAMILIES["F5_FULL_BOUNDED"], "revenue_concept",
        "lineage_hash", "fact_lineage_json", "source_url_id", "source_sha256",
        "accepted_source_entry", "accepted_source_sha256",
        "corporate_action_scale_consistent", "coverage_status", "amendment_status",
        "concept_switch_status",
    ]
    if states.empty:
        return pd.DataFrame(columns=columns)
    identities = mapping.loc[mapping.cik.notna(), [
        "security_id", "ticker", "cusip", "cik", "mapping_source", "mapping_confidence",
        "mapping_effective_date",
    ]].drop_duplicates(["security_id", "cik"])
    ledger = identities.merge(states, on="cik", how="inner", validate="many_to_many")
    family_counts = []
    for features in CORE_COVERAGE_FAMILIES:
        family_counts.append(ledger[features].notna().any(axis=1).astype(int))
    ledger["coverage_status"] = np.sum(family_counts, axis=0) >= 3
    ledger["amendment_status"] = np.where(ledger.amendment_indicator.eq(1.0), "AMENDMENT_EFFECTIVE_FROM_OWN_ACCEPTANCE", "ORIGINAL_FILING")
    ledger["concept_switch_status"] = np.where(ledger.concept_switch_indicator.eq(1.0), "CONCEPT_SWITCH_RECORDED", "NO_CONCEPT_SWITCH")
    ledger = ledger.sort_values(["security_id", "feature_effective_date", "accepted_datetime", "accession"], kind="mergesort")
    ledger = ledger.drop_duplicates(["security_id", "feature_effective_date", "accession"], keep="last")
    for column in columns:
        if column not in ledger:
            ledger[column] = pd.NA
    return ledger[columns].reset_index(drop=True)


def prepare_a2_inputs() -> dict[str, Any]:
    policy = import_file("a2_sec_fundamental_clean_policy", R2_SOURCE)
    base = import_file("a2_sec_fundamental_base", SEC_STAGE_SOURCE)
    action = import_file("a2_sec_fundamental_action", ACTION_SOURCE)
    pretop = import_file("a2_sec_fundamental_pretop", PRETOP_SOURCE)
    e5 = import_file("a2_sec_fundamental_e5", E5_SOURCE)
    top_authoritative, portfolio, raw = base.verify_inputs()
    require(len(portfolio) == 751, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", len(portfolio))
    require(abs(float(raw["cagr"]) - 0.5070421599044499) <= TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "CAGR")
    require(abs(float(raw["sharpe"]) - 1.2353699802070324) <= TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "SHARPE")
    require(abs(float(raw["max_drawdown"]) + 0.370671641329821) <= TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "MAXDD")

    matrix = pd.read_parquet(MATRIX)
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date).dt.normalize()
    matrix["target_end_date"] = pd.to_datetime(matrix.target_end_date).dt.normalize()
    authoritative = pd.read_parquet(OOF, columns=[
        "signal_date", "ticker", "universe_size", "split", "a2_model_name", "a2_prediction", "a2_rank",
    ])
    authoritative["signal_date"] = pd.to_datetime(authoritative.signal_date).dt.normalize()
    authoritative["ticker"] = authoritative.ticker.astype(str).str.upper()
    raw_fit_counter = policy.FitCounter()
    early, a2_identity = policy.reconstruct_a2_oof(matrix, authoritative, raw_fit_counter)
    authoritative_dates = set(pd.to_datetime(top_authoritative.signal_date).dt.normalize())
    support = authoritative.loc[authoritative.signal_date.isin(authoritative_dates)].copy()
    pool = pd.concat([early, support], ignore_index=True).sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort")
    top = pd.concat([
        early.loc[early.a2_rank.le(20), ["signal_date", "ticker", "a2_prediction", "a2_rank"]],
        top_authoritative[["signal_date", "ticker", "a2_prediction", "a2_rank"]],
    ], ignore_index=True)
    research_dates = pd.read_parquet(RESEARCH_DATASET, columns=["signal_date", "next_execution_date"])
    research_dates["signal_date"] = pd.to_datetime(research_dates.signal_date).dt.normalize()
    research_dates["next_execution_date"] = pd.to_datetime(research_dates.next_execution_date).dt.normalize()
    execution = pd.concat([
        pd.DataFrame({"execution_date": research_dates.loc[research_dates.signal_date.isin(early.signal_date), "next_execution_date"].dropna().unique()}),
        portfolio[["execution_date"]],
    ], ignore_index=True).drop_duplicates()
    taxonomy, _, taxonomy_facts = policy.extend_taxonomy(pretop, base, pool, top, execution)
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    matrix_features = matrix[["signal_date", "ticker", *[name for name in policy.A2_FEATURES if name in matrix.columns]]].drop_duplicates(["signal_date", "ticker"])
    return {
        "policy": policy, "base": base, "action": action, "pretop": pretop, "e5": e5,
        "top_authoritative": top_authoritative, "portfolio": portfolio, "raw": raw,
        "matrix": matrix, "matrix_features": matrix_features, "pool": pool, "top": top,
        "taxonomy": taxonomy, "taxonomy_facts": taxonomy_facts, "a2_identity": a2_identity,
        "raw_extension_fit_count": int(raw_fit_counter.count),
    }


def trading_sessions(action: Any) -> pd.DatetimeIndex:
    prices = action.load_prices({"QQQ"}, list(range(2018, 2026)))
    raw = prices.attrs.get("raw_counterfactual")
    require(isinstance(raw, pd.DataFrame), "LABEL_LINEAGE_FAILURE", "QQQ_RAW_COUNTERFACTUAL_MISSING")
    sessions = pd.DatetimeIndex(pd.to_datetime(raw.loc[raw.ticker.eq("QQQ"), "trade_date"]).dt.normalize().unique()).sort_values()
    require(len(sessions) > 1500 and sessions.max() <= LABEL_CUTOFF, "NYSE_SESSION_CALENDAR_FAILURE", (len(sessions), sessions.max()))
    return sessions


def load_universe() -> pd.DataFrame:
    universe = pd.read_parquet(UNIVERSE_INTERVALS)
    universe["effective_start"] = pd.to_datetime(universe.effective_start).dt.normalize()
    universe["effective_end"] = pd.to_datetime(universe.effective_end).dt.normalize()
    universe["ticker"] = universe.ticker.astype(str).str.upper().str.strip()
    universe = universe.loc[
        universe.effective_start.le(LABEL_CUTOFF) & universe.effective_end.ge(pd.Timestamp("2020-01-01"))
    ].copy()
    require(not universe.empty, "PIT_13F_UNIVERSE_EMPTY")
    return universe


def attach_mapping_to_pool(pool: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    right = mapping.sort_values(["ticker", "identity_effective_start"], kind="mergesort")
    for ticker, left_group in pool.groupby("ticker", sort=False):
        left = left_group.sort_values("signal_date").copy()
        candidates = right.loc[right.ticker.eq(str(ticker))].copy()
        if candidates.empty:
            left["security_id"] = "A2_TICKER_" + str(ticker)
            left["cik"] = pd.NA
            left["identity_effective_end"] = pd.NaT
            left["cik_mapping_source"] = "UNRESOLVED"
            pieces.append(left)
            continue
        candidates = candidates.sort_values("identity_effective_start").drop_duplicates("identity_effective_start", keep="last")
        merged = pd.merge_asof(
            left.sort_values("signal_date"),
            candidates[["identity_effective_start", "identity_effective_end", "mapping_effective_date", "security_id", "cik", "mapping_source"]].sort_values("identity_effective_start"),
            left_on="signal_date", right_on="identity_effective_start", direction="backward", allow_exact_matches=True,
        )
        valid = merged.signal_date.le(merged.identity_effective_end) & (
            merged.mapping_effective_date.isna() |
            merged.signal_date.ge(pd.to_datetime(merged.mapping_effective_date))
        )
        merged.loc[~valid, "security_id"] = "A2_TICKER_" + str(ticker)
        merged.loc[~valid, "cik"] = pd.NA
        merged["cik_mapping_source"] = merged.mapping_source.fillna("UNRESOLVED")
        pieces.append(merged.drop(columns=["mapping_source"], errors="ignore"))
    frame = pd.concat(pieces, ignore_index=True)
    frame["cik"] = pd.to_numeric(frame.cik, errors="coerce").astype("Int64")
    return frame.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def attach_features_asof(pool: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "accession", "accepted_datetime", "feature_effective_date", "fiscal_year", "fiscal_period",
        "period_end_date", *FEATURE_FAMILIES["F5_FULL_BOUNDED"], "lineage_hash",
    ]
    pieces: list[pd.DataFrame] = []
    for cik_key, left_group in pool.groupby(pool.cik.astype("string"), dropna=False, sort=False):
        left = left_group.sort_values("signal_date").copy()
        # ``groupby(..., dropna=False)`` can return the scalar ``pd.NA`` for
        # the frozen missing-neutral population.  It must remain eligible
        # with missing fundamental features, never be coerced to an integer.
        if pd.isna(cik_key) or str(cik_key) in {"<NA>", "nan", "None"} or states.empty:
            for column in columns:
                left[column] = pd.NA
            pieces.append(left)
            continue
        cik = int(cik_key)
        right_columns = list(dict.fromkeys(["feature_effective_date", *columns]))
        right = states.loc[states.cik.eq(cik), right_columns].copy()
        right = right.sort_values(["feature_effective_date", "accepted_datetime", "accession"], kind="mergesort").drop_duplicates("feature_effective_date", keep="last")
        if right.empty:
            for column in columns:
                left[column] = pd.NA
            pieces.append(left)
            continue
        merged = pd.merge_asof(
            left.sort_values("signal_date"), right.sort_values("feature_effective_date"),
            left_on="signal_date", right_on="feature_effective_date", direction="backward", allow_exact_matches=True,
        )
        pieces.append(merged)
    frame = pd.concat(pieces, ignore_index=True)
    known = frame.accepted_datetime.notna()
    if known.any():
        cutoff = pd.to_datetime(frame.loc[known, "signal_date"]).dt.normalize()
        accepted_local = pd.to_datetime(frame.loc[known, "accepted_datetime"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        require((accepted_local < cutoff).all(), "ACCEPTED_DATETIME_PIT_FAILURE", int((accepted_local >= cutoff).sum()))
        require((pd.to_datetime(frame.loc[known, "feature_effective_date"]) <= cutoff).all(), "FEATURE_EFFECTIVE_DATE_FAILURE")
    return frame.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def normalize_feature_panel(frame: pd.DataFrame) -> pd.DataFrame:
    panel = frame.copy()
    panel["raw_score_z"] = panel.groupby("signal_date", group_keys=False).a2_prediction.apply(rank_z)
    for feature in FEATURE_FAMILIES["F5_FULL_BOUNDED"]:
        panel[f"missing_{feature}"] = panel[feature].isna().astype(float)
        panel[f"z_{feature}"] = panel.groupby("signal_date", group_keys=False)[feature].apply(rank_z)
    family_available = []
    for index, features in enumerate(CORE_COVERAGE_FAMILIES):
        column = f"coverage_family_{index}"
        panel[column] = panel[features].notna().any(axis=1).astype(int)
        family_available.append(column)
    panel["feature_covered"] = panel[family_available].sum(axis=1).ge(3)
    composite_parts = []
    for feature, sign in SIMPLE_SIGNS.items():
        composite_parts.append(sign * panel[f"z_{feature}"])
    panel["fundamental_composite"] = pd.concat(composite_parts, axis=1).mean(axis=1)
    panel["sector_relative_composite"] = panel.fundamental_composite - panel.groupby(["signal_date", "ff12"]).fundamental_composite.transform("mean")
    panel["sector_relative_composite"] = panel.groupby(["signal_date", "ff12"], group_keys=False).sector_relative_composite.apply(rank_z)
    return panel


def make_clean_labels(policy: Any, action: Any, tickers: set[str], years: list[int], stage: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    prices, labels, gate, audit = policy.label_lineage_hard_gate(action, tickers, years, stage)
    require(gate["label_lineage_hard_gate"] == "PASS", "LABEL_LINEAGE_FAILURE", gate)
    raw = prices.attrs.get("raw_counterfactual")
    qfq = raw.loc[~raw.source.astype(str).eq(FORBIDDEN_LABEL_SOURCE)].sort_values(["ticker", "trade_date"], kind="mergesort").drop_duplicates(["ticker", "trade_date"]).copy()
    pieces = []
    for _, group in qfq.groupby("ticker", sort=False):
        group = group.sort_values("trade_date").copy()
        group["y_abs60"] = group.close.shift(-60) / group.close - 1.0
        group["label_end_date_60"] = group.trade_date.shift(-60)
        group["end_price_60"] = group.close.shift(-60)
        pieces.append(group[["trade_date", "ticker", "y_abs60", "label_end_date_60", "end_price_60"]])
    sixty = pd.concat(pieces, ignore_index=True).rename(columns={"trade_date": "signal_date"})
    labels = labels.merge(sixty, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    mature = labels.label_end_date_60.notna() & labels.label_end_date_60.le(LABEL_CUTOFF)
    direct = labels.loc[mature, "end_price_60"] / labels.loc[mature, "start_price"] - 1.0
    mismatch60 = int(((direct - labels.loc[mature, "y_abs60"]).abs() > TOL).sum())
    gate["abs60_arithmetic_mismatch_count"] = mismatch60
    gate["2026_winner60_label_count"] = int(labels.label_end_date_60.ge(pd.Timestamp("2026-01-01")).sum())
    require(mismatch60 == 0, "LABEL_LINEAGE_FAILURE", "ABS60_ARITHMETIC")
    return prices, labels, gate, audit


def build_research_panel(
    mapped_pool: pd.DataFrame,
    states: pd.DataFrame,
    taxonomy: pd.DataFrame,
    matrix_features: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    panel = attach_features_asof(mapped_pool, states)
    panel = panel.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel["ff12"] = panel.ff12.fillna("UNKNOWN").astype(str)
    panel["ff48"] = panel.ff48.fillna("UNKNOWN").astype(str)
    panel = panel.merge(matrix_features, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel = panel.merge(labels[[
        "signal_date", "ticker", "y_abs20", "y_downside20", "label_end_date",
        "y_abs60", "label_end_date_60", "start_price", "end_price_20",
        "label_price_lineage",
    ]], on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel = normalize_feature_panel(panel)
    candidate = panel.a2_rank.le(40)
    panel["y_ff12res20"] = np.nan
    panel.loc[candidate, "y_ff12res20"] = panel.loc[candidate, "y_abs20"] - panel.loc[candidate].groupby(["signal_date", "ff12"]).y_abs20.transform("mean")
    quantile = panel.loc[candidate].groupby("signal_date").y_abs60.transform(lambda values: values.quantile(0.90))
    panel["winner60"] = np.nan
    panel.loc[candidate, "winner60"] = (panel.loc[candidate, "y_abs60"] >= quantile).astype(float)
    panel.loc[panel.label_end_date_60.gt(LABEL_CUTOFF), "winner60"] = np.nan
    panel["sample_weight"] = 1.0
    counts = panel.loc[candidate & panel.accession.notna()].groupby(["security_id", "accession"]).size()
    keys = list(zip(panel.security_id.astype(str), panel.accession.astype(str)))
    panel["sample_weight"] = [1.0 / float(counts.get(key, 1)) for key in keys]
    if panel.sample_weight.mean() > 0:
        panel["sample_weight"] /= panel.sample_weight.mean()
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    panel["label_end_date_60"] = pd.to_datetime(panel.label_end_date_60)
    require(not panel.label_price_lineage.dropna().ne("continuous_raw_counterfactual").any(), "LABEL_LINEAGE_FAILURE")
    return panel.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def coverage_metrics(panel: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    raw40 = panel.loc[panel.a2_rank.le(40)].copy()
    daily = raw40.groupby("signal_date").feature_covered.mean()
    median = float(daily.median()) if len(daily) else 0.0
    passing_fraction = float(daily.ge(0.50).mean()) if len(daily) else 0.0
    passed = median >= 0.60 and passing_fraction >= 0.75
    facts = {
        "feature_coverage_median": float(panel.feature_covered.mean()) if len(panel) else 0.0,
        "raw_top40_coverage_median": median,
        "decision_dates_passing_coverage_gate": passing_fraction,
        "coverage_gate": "PASS" if passed else "FAIL",
    }
    rows: list[dict[str, Any]] = []
    for year, group in raw40.groupby(raw40.signal_date.dt.year):
        rows.append({"record_type": "COVERAGE_YEAR", "group": str(year), "coverage": float(group.feature_covered.mean()), "rows": len(group)})
    for sector, group in raw40.groupby("ff12"):
        rows.append({"record_type": "COVERAGE_FF12", "group": str(sector), "coverage": float(group.feature_covered.mean()), "rows": len(group)})
    liquidity = pd.qcut(raw40.avg_dollar_volume_20d.rank(method="first"), 4, labels=["Q1_LOW", "Q2", "Q3", "Q4_HIGH"]) if raw40.avg_dollar_volume_20d.notna().any() else pd.Series("UNKNOWN", index=raw40.index)
    for bucket, group in raw40.assign(liquidity_bucket=liquidity).groupby("liquidity_bucket", observed=False):
        rows.append({"record_type": "COVERAGE_LIQUIDITY", "group": str(bucket), "coverage": float(group.feature_covered.mean()), "rows": len(group)})
    return facts, pd.DataFrame(rows)


def targeted_unresolved_impact(
    coverage_panel: pd.DataFrame, mapping: pd.DataFrame, facts: pd.DataFrame,
    submissions: pd.DataFrame, states: pd.DataFrame,
) -> pd.DataFrame:
    raw40 = coverage_panel.loc[coverage_panel.a2_rank.le(40)].copy()
    missing = raw40.loc[~raw40.feature_covered.astype(bool)].copy()
    if missing.empty:
        return pd.DataFrame(columns=[
            "security_id", "ticker", "issuer_name", "raw_top40_occurrence_count",
            "affected_decision_date_count", "cik_status", "likely_mapping_filer_issue",
            "estimated_coverage_recovery_if_fixed",
        ])
    identity = mapping.sort_values("mapping_confidence", kind="mergesort").drop_duplicates("security_id", keep="first")
    identity = identity[["security_id", "ticker", "issuer_name", "cik", "mapping_source"]]
    grouped = missing.groupby(["security_id", "ticker"], dropna=False).agg(
        raw_top40_occurrence_count=("signal_date", "size"),
        affected_decision_date_count=("signal_date", "nunique"),
    ).reset_index()
    grouped = grouped.merge(identity, on=["security_id", "ticker"], how="left", validate="many_to_one")
    facts_ciks = set(pd.to_numeric(facts.cik, errors="coerce").dropna().astype(int))
    accepted_ciks = set(pd.to_numeric(submissions.cik, errors="coerce").dropna().astype(int))
    state_ciks = set(pd.to_numeric(states.cik, errors="coerce").dropna().astype(int)) if not states.empty else set()
    issues: list[str] = []
    statuses: list[str] = []
    for row in grouped.itertuples(index=False):
        if pd.isna(row.cik):
            statuses.append("UNRESOLVED")
            issues.append("UNRESOLVED_CIK_REUSED_AS_UNRESOLVED_NO_BROAD_REMAP")
            continue
        cik = int(row.cik)
        statuses.append(f"RESOLVED:{cik}")
        if cik not in facts_ciks:
            issues.append("RESOLVED_CIK_NO_COMPANYFACTS_ENTRY_OR_ALLOWED_CONCEPT_FACT")
        elif cik not in accepted_ciks:
            issues.append("RESOLVED_CIK_NO_PRE2026_ACCEPTED_SUBMISSION_LINKAGE")
        elif cik not in state_ciks:
            issues.append("FACTS_PRESENT_NO_USABLE_ACCESSION_PERIOD_STATE")
        else:
            issues.append("STATE_PRESENT_BELOW_THREE_CORE_FAMILY_COVERAGE")
    grouped["cik_status"] = statuses
    grouped["likely_mapping_filer_issue"] = issues
    grouped["estimated_coverage_recovery_if_fixed"] = grouped.raw_top40_occurrence_count / max(1, len(raw40))
    return grouped[[
        "security_id", "ticker", "issuer_name", "raw_top40_occurrence_count",
        "affected_decision_date_count", "cik_status", "likely_mapping_filer_issue",
        "estimated_coverage_recovery_if_fixed",
    ]].sort_values(
        ["raw_top40_occurrence_count", "affected_decision_date_count", "ticker"],
        ascending=[False, False, True], kind="mergesort",
    ).reset_index(drop=True)


def write_bulk_cache_manifest(
    snapshot: Mapping[str, Any], derived: Mapping[str, Any], resolved_cik_count: int,
    facts: pd.DataFrame, submissions: pd.DataFrame, states: pd.DataFrame, zip_index: pd.DataFrame,
) -> Path:
    derived_manifest = Path(derived["manifest_path"])
    payload = {
        "status": "PASS_OFFLINE_HASH_FROZEN_BULK_RESUME",
        "research_id": TASK, "network_request_count": 0, "moomoo_request_count": 0,
        "cache_path": str(CACHE_ROOT), "snapshot_manifest": str(BULK_SNAPSHOT_MANIFEST),
        "snapshot_manifest_sha256": sha256_file(BULK_SNAPSHOT_MANIFEST),
        "snapshot_contract_hash": snapshot["snapshot_contract_hash"],
        "companyfacts_sha256": snapshot["payloads"]["companyfacts"]["sha256"],
        "submissions_sha256": snapshot["payloads"]["submissions"]["sha256"],
        "resolved_cik_count": resolved_cik_count, "numeric_fact_rows": len(facts),
        "accepted_submission_rows": len(submissions), "feature_state_rows": len(states),
        "selectively_indexed_entry_count": len(zip_index),
        "derived_cache_status": derived["status"], "derived_manifest": str(derived_manifest),
        "derived_manifest_sha256": sha256_file(derived_manifest),
        "full_zip_extraction": False,
    }
    atomic_json(CACHE_ROOT / "cache_manifest.json", payload)
    return CACHE_ROOT / "cache_manifest.json"


def sec_bulk_prefit_block(gate: Mapping[str, Any]) -> str:
    keys = [
        "COMPANYFACTS_PATH", "COMPANYFACTS_SHA256", "COMPANYFACTS_ENTRY_COUNT", "COMPANYFACTS_HASH_MATCH", "",
        "SUBMISSIONS_PATH", "SUBMISSIONS_SHA256", "SUBMISSIONS_ENTRY_COUNT", "SUBMISSIONS_HASH_MATCH", "",
        "SEC_NUMERIC_FACT_COUNT", "RELEVANT_RESOLVED_CIK_COUNT", "RELEVANT_CIK_WITH_FACTS_COUNT",
        "ACCESSION_LINKAGE_COUNT", "ACCEPTED_DATETIME_LINKAGE_COUNT", "",
        "PIT_EFFECTIVE_DATE_STATUS", "RESTATEMENT_GUARD_STATUS", "UNIT_SCALE_STATUS", "CONCEPT_CONTRACT_STATUS", "",
        "RAW_TOP40_COVERAGE_MEDIAN", "DECISION_DATES_PASSING_COVERAGE_GATE", "FEATURE_COVERAGE_MEDIAN", "",
        "LABEL_PRICE_LINEAGE", "LABEL_ARITHMETIC_MISMATCH_COUNT", "2026_OUTCOME_USED", "2026_LEAKAGE_COUNT", "",
        "MODEL_FIT_ALLOWED",
    ]
    lines = ["=" * 60, "SEC_BULK_RESUME_PREFIT_GATE", "=" * 60, ""]
    for key in keys:
        lines.append("") if not key else lines.append(f"{key}={gate.get(key, 'NOT_APPLICABLE')}")
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def model_columns(spec: ModelSpec) -> tuple[list[str], list[str], list[str]]:
    raw_features = FEATURE_FAMILIES[spec.feature_family]
    fundamental = [f"z_{name}" for name in raw_features]
    missing = [f"missing_{name}" for name in raw_features]
    numeric = [*fundamental, *missing]
    if spec.structure != "M0_FUNDAMENTAL_ONLY":
        numeric.append("raw_score_z")
    categorical = ["ff12"] if spec.structure == "M3_RAW_PLUS_FUNDAMENTAL_WITH_FF12_FEATURE" else []
    return list(dict.fromkeys(numeric)), categorical, fundamental


def _control_matrix(frame: pd.DataFrame, medians: Mapping[str, float] | None = None, columns: Sequence[str] | None = None) -> tuple[pd.DataFrame, dict[str, float], list[str]]:
    values = frame[CONTROL_FEATURES].apply(pd.to_numeric, errors="coerce").copy()
    learned = dict(medians or {})
    for column in CONTROL_FEATURES:
        if column not in learned:
            median = values[column].median()
            learned[column] = float(median) if np.isfinite(median) else 0.0
        values[column] = values[column].fillna(learned[column])
    dummies = pd.get_dummies(frame.ff12.fillna("UNKNOWN").astype(str), prefix="ff12", dtype=float)
    matrix = pd.concat([values.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
    if columns is None:
        output_columns = list(matrix.columns)
    else:
        output_columns = list(columns)
        matrix = matrix.reindex(columns=output_columns, fill_value=0.0)
    return matrix, learned, output_columns


def crossfit_residualize(
    train: pd.DataFrame,
    feature_columns: list[str],
    counter: FitCounter,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = train.copy()
    y = result[feature_columns].fillna(0.0).to_numpy(float)
    dates = np.array(sorted(pd.to_datetime(result.signal_date).unique()))
    blocks = [block for block in np.array_split(dates, 3) if len(block)]
    oof = np.zeros_like(y)
    for block in blocks:
        validation_mask = result.signal_date.isin(block).to_numpy()
        training_mask = ~validation_mask
        require(training_mask.sum() > len(feature_columns), "RESIDUAL_CROSSFIT_SUPPORT")
        controls_train, medians, columns = _control_matrix(result.loc[training_mask])
        controls_validation, _, _ = _control_matrix(result.loc[validation_mask], medians, columns)
        model = Ridge(alpha=10.0)
        model.fit(controls_train.to_numpy(float), y[training_mask], sample_weight=result.loc[training_mask, "sample_weight"].to_numpy(float))
        counter.add()
        oof[validation_mask] = y[validation_mask] - model.predict(controls_validation.to_numpy(float))
    for index, column in enumerate(feature_columns):
        result[column] = oof[:, index]
    controls, medians, columns = _control_matrix(train)
    final_model = Ridge(alpha=10.0)
    final_model.fit(controls.to_numpy(float), y, sample_weight=train.sample_weight.to_numpy(float))
    counter.add()
    return result, {"model": final_model, "medians": medians, "columns": columns}


def apply_residualizer(frame: pd.DataFrame, feature_columns: list[str], residualizer: Mapping[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    controls, _, _ = _control_matrix(result, residualizer["medians"], residualizer["columns"])
    observed = result[feature_columns].fillna(0.0).to_numpy(float)
    prediction = residualizer["model"].predict(controls.to_numpy(float))
    for index, column in enumerate(feature_columns):
        result[column] = observed[:, index] - prediction[:, index]
    return result


def make_estimator(spec: ModelSpec, numeric: list[str], categorical: list[str], seed: int) -> Pipeline:
    transformers: list[tuple[str, Any, list[str]]] = [
        ("numeric", Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
            ("scaler", StandardScaler()),
        ]), numeric),
    ]
    if categorical:
        transformers.append(("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical))
    preprocess = ColumnTransformer(transformers, remainder="drop", sparse_threshold=0.0)
    if spec.family == "RIDGE":
        model: Any = Ridge(alpha=float(spec.params["alpha"]))
    elif spec.family == "ELASTIC_NET":
        model = ElasticNet(
            alpha=float(spec.params["alpha"]), l1_ratio=float(spec.params["l1_ratio"]),
            max_iter=5000, random_state=seed,
        )
    elif spec.family == "HGB":
        model = HistGradientBoostingRegressor(
            learning_rate=0.05, max_iter=int(spec.params["max_iter"]),
            max_depth=int(spec.params["max_depth"]), min_samples_leaf=40,
            l2_regularization=1.0, early_stopping=False, random_state=seed,
        )
    elif spec.family == "CATBOOST":
        from catboost import CatBoostRegressor
        model = CatBoostRegressor(
            depth=int(spec.params["depth"]), iterations=int(spec.params["iterations"]),
            learning_rate=float(spec.params["learning_rate"]), loss_function="RMSE",
            l2_leaf_reg=3.0, random_seed=seed, verbose=False, allow_writing_files=False,
            thread_count=max(1, min(8, os.cpu_count() or 1)),
        )
    else:
        raise GateFailure(f"MODEL_FAMILY_UNSUPPORTED:{spec.family}")
    return Pipeline([("preprocess", preprocess), ("model", model)])


def fit_model(spec: ModelSpec, train: pd.DataFrame, seed: int, counter: FitCounter) -> FittedModel:
    usable = train.loc[
        train.a2_rank.le(40) & train.y_ff12res20.notna() & train.label_end_date.notna()
    ].copy()
    require(not usable.empty, "MODEL_TRAIN_EMPTY", spec.model_id)
    require(usable.label_end_date.max() <= LABEL_CUTOFF, "LABEL_END_DATE_GUARD", usable.label_end_date.max())
    numeric, categorical, fundamental = model_columns(spec)
    residualizer = None
    if spec.structure == "M2_RAW_PLUS_FUNDAMENTAL_RESIDUALIZED":
        usable, residualizer = crossfit_residualize(usable, fundamental, counter)
    estimator = make_estimator(spec, numeric, categorical, seed)
    fit_kwargs = {"model__sample_weight": usable.sample_weight.to_numpy(float)}
    estimator.fit(usable[numeric + categorical], usable.y_ff12res20.to_numpy(float), **fit_kwargs)
    counter.add()
    return FittedModel(
        spec=spec, estimator=estimator, numeric_features=numeric,
        categorical_features=categorical, residualizer=residualizer,
        residual_control_columns=list(residualizer["columns"]) if residualizer else [],
        residual_feature_columns=fundamental if residualizer else [],
        max_feature_date=pd.Timestamp(usable.signal_date.max()),
        max_label_end_date=pd.Timestamp(usable.label_end_date.max()),
    )


def predict_model(bundle: FittedModel, frame: pd.DataFrame) -> np.ndarray:
    work = frame.copy()
    if bundle.residualizer is not None:
        work = apply_residualizer(work, bundle.residual_feature_columns, bundle.residualizer)
    return bundle.estimator.predict(work[bundle.numeric_features + bundle.categorical_features])


def daily_rank_ic(frame: pd.DataFrame, prediction: Sequence[float], target: str = "y_ff12res20") -> float:
    work = frame[["signal_date", target]].copy()
    work["prediction"] = np.asarray(prediction, dtype=float)
    values = []
    for _, group in work.dropna(subset=[target, "prediction"]).groupby("signal_date"):
        if group[target].nunique() > 1 and group.prediction.nunique() > 1:
            values.append(group.prediction.corr(group[target], method="spearman"))
    return float(np.nanmean(values)) if values else math.nan


def predictive_metrics(frame: pd.DataFrame, prediction: Sequence[float]) -> dict[str, float]:
    ic = daily_rank_ic(frame, prediction)
    raw_ic = daily_rank_ic(frame, frame.raw_score_z.to_numpy(float))
    work = frame[["signal_date", "y_ff12res20"]].copy()
    work["prediction"] = np.asarray(prediction, dtype=float)
    work["quartile"] = work.groupby("signal_date").prediction.transform(
        lambda values: pd.qcut(values.rank(method="first"), 4, labels=False, duplicates="drop")
    )
    top = work.loc[work.quartile.eq(3), "y_ff12res20"].mean()
    bottom = work.loc[work.quartile.eq(0), "y_ff12res20"].mean()
    return {
        "rank_ic": ic, "raw_rank_ic": raw_ic,
        "incremental_rank_ic": ic - raw_ic if np.isfinite(ic) and np.isfinite(raw_ic) else math.nan,
        "top_bottom_residual_spread": float(top - bottom),
    }


def raw_targets(frame: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in frame.groupby("signal_date", sort=True):
        selected = group.sort_values(["a2_rank", "ticker"], kind="mergesort").head(20)
        require(len(selected) == 20, "RAW_TOP20_IDENTITY", date)
        targets[pd.Timestamp(date)] = {str(ticker): 0.05 for ticker in selected.ticker}
    return targets


def membership_targets(
    frame: pd.DataFrame,
    signal_column: str,
    eta: float,
    entry_protection: str,
    *,
    preserve_raw_prior: bool = True,
) -> dict[pd.Timestamp, dict[str, float]]:
    require(eta in {0.10, 0.25, 0.50} or not preserve_raw_prior, "RAW_PRIOR_ETA", eta)
    require(entry_protection in {"EP0_NO_HARD_PROTECTION", "EP1_RAW_TOP10_PROTECTED"}, "ENTRY_PROTECTION", entry_protection)
    previous: set[str] = set()
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group0 in frame.groupby("signal_date", sort=True):
        group = group0.loc[group0.a2_rank.le(40) | group0.ticker.isin(previous)].copy()
        require(group.ticker.nunique() >= 20, "RAW_TOP40_CANDIDATE_IDENTITY", date)
        group["fundamental_signal_z"] = rank_z(group[signal_column])
        group["combined_score"] = group.raw_score_z + eta * group.fundamental_signal_z if preserve_raw_prior else group.fundamental_signal_z
        protected = set(group.loc[group.a2_rank.le(10), "ticker"]) if entry_protection == "EP1_RAW_TOP10_PROTECTED" else set()
        remaining = group.loc[~group.ticker.isin(protected)].sort_values(["combined_score", "a2_rank", "ticker"], ascending=[False, True, True], kind="mergesort")
        selected = list(sorted(protected)) + remaining.ticker.head(20 - len(protected)).astype(str).tolist()
        selected = list(dict.fromkeys(selected))
        require(len(selected) == 20, "PORTFOLIO_CONSTRAINT_FAILURE", (date, len(selected)))
        weights = {ticker: 0.05 for ticker in selected}
        require(abs(sum(weights.values()) - 1.0) <= TOL and len(weights) == 20, "PORTFOLIO_CONSTRAINT_FAILURE", date)
        targets[pd.Timestamp(date)] = weights
        previous = set(selected)
    return targets


def simple_target_maps(frame: pd.DataFrame) -> dict[str, dict[pd.Timestamp, dict[str, float]]]:
    return {
        "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL": raw_targets(frame),
        "C1_SIMPLE_FUNDAMENTAL_COMPOSITE_ONLY": membership_targets(frame, "fundamental_composite", 1.0, "EP0_NO_HARD_PROTECTION", preserve_raw_prior=False),
        "C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT": membership_targets(frame, "fundamental_composite", 0.25, "EP0_NO_HARD_PROTECTION"),
        "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT": membership_targets(frame, "sector_relative_composite", 0.25, "EP0_NO_HARD_PROTECTION"),
    }


def replay_arm(
    policy_module: Any,
    e5: Any,
    action: Any,
    name: str,
    targets: dict[pd.Timestamp, dict[str, float]],
    prices: pd.DataFrame,
    raw_control: dict[pd.Timestamp, dict[str, float]],
    taxonomy: pd.DataFrame,
) -> tuple[Any, dict[str, Any]]:
    replay, metrics = policy_module.replay_metrics(e5, action, name, targets, prices, raw_control, taxonomy)
    require(metrics["position_count_min"] == 20, "PORTFOLIO_CONSTRAINT_FAILURE", name)
    require(metrics["gross_error_max"] <= TOL, "PORTFOLIO_CONSTRAINT_FAILURE", name)
    require(max(metrics["nav_identity_error_max"], metrics["cost_identity_error_max"], metrics["turnover_identity_error_max"]) <= 1e-10, "NAV/COST/RETURN_RECONCILIATION_FAILURE", name)
    return replay, metrics


def winner_capture(panel: pd.DataFrame, targets: Mapping[pd.Timestamp, Mapping[str, float]]) -> float:
    work = panel.loc[panel.a2_rank.le(40) & panel.winner60.eq(1.0), ["signal_date", "ticker"]]
    if work.empty:
        return math.nan
    captured = [str(row.ticker) in targets.get(pd.Timestamp(row.signal_date), {}) for row in work.itertuples(index=False)]
    return float(np.mean(captured))


def orthogonality_metrics(panel: pd.DataFrame) -> dict[str, Any]:
    work = panel.loc[panel.a2_rank.le(40) & panel.y_ff12res20.notna()].copy()
    correlations = []
    fundamental_ic = []
    for _, group in work.groupby("signal_date"):
        if group.fundamental_composite.nunique() > 1 and group.raw_score_z.nunique() > 1:
            correlations.append(group.fundamental_composite.corr(group.raw_score_z, method="spearman"))
        if group.fundamental_composite.nunique() > 1 and group.y_ff12res20.nunique() > 1:
            fundamental_ic.append(group.fundamental_composite.corr(group.y_ff12res20, method="spearman"))
    controls, _, _ = _control_matrix(work)
    fund = work.fundamental_composite.to_numpy(float)
    target = work.y_ff12res20.to_numpy(float)
    fund_model = Ridge(alpha=10.0).fit(controls.to_numpy(float), fund, sample_weight=work.sample_weight.to_numpy(float))
    target_controls = np.column_stack([controls.to_numpy(float), work.raw_score_z.to_numpy(float)])
    target_model = Ridge(alpha=10.0).fit(target_controls, target, sample_weight=work.sample_weight.to_numpy(float))
    fund_residual = fund - fund_model.predict(controls.to_numpy(float))
    target_residual = target - target_model.predict(target_controls)
    partial = pd.Series(fund_residual).corr(pd.Series(target_residual), method="spearman")
    return {
        "raw_score_correlation": float(np.nanmean(correlations)) if correlations else math.nan,
        "incremental_rank_ic": float(np.nanmean(fundamental_ic)) if fundamental_ic else math.nan,
        "partial_rank_ic": float(partial),
        "orthogonality_status": "PASS_SOURCE_ORTHOGONAL_STATISTICALLY_INCREMENTAL" if np.isfinite(partial) and partial > 0 else "SOURCE_ORTHOGONAL_NO_POSITIVE_PARTIAL_IC",
    }


def return_metrics(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"cagr": math.nan, "sharpe": math.nan, "max_drawdown": math.nan}
    nav = (1.0 + values).cumprod()
    years = len(values) / 252.0
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and nav.iloc[-1] > 0 else math.nan
    std = float(values.std(ddof=1))
    sharpe = float(values.mean() / std * math.sqrt(252)) if std > 0 else math.nan
    maxdd = float((nav / nav.cummax() - 1.0).min())
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": maxdd}


def run_inner_search(
    policy_module: Any,
    e5: Any,
    action: Any,
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    taxonomy: pd.DataFrame,
    specs: list[ModelSpec],
    counter: FitCounter,
) -> tuple[pd.DataFrame, list[PolicySpec], list[str], dict[tuple[str, int, int], FittedModel]]:
    folds = [
        (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-06-30")),
        (pd.Timestamp("2022-07-01"), pd.Timestamp("2022-12-30")),
    ]
    cache: dict[tuple[str, int, int], FittedModel] = {}
    model_rows: list[dict[str, Any]] = []
    first_start, first_end = folds[0]
    train = panel.loc[panel.label_end_date.lt(first_start)]
    valid_all = panel.loc[panel.signal_date.between(first_start, first_end)]
    valid = valid_all.loc[valid_all.a2_rank.le(40) & valid_all.y_ff12res20.notna()]
    require(not train.empty and not valid.empty, "INNER_FOLD_SUPPORT")
    for spec in specs:
        phase = "A_BROAD_LINEAR" if spec.family in {"RIDGE", "ELASTIC_NET"} else "B_LIMITED_NONLINEAR"
        try:
            bundle = fit_model(spec, train, RANDOM_SEEDS[0], counter)
            prediction = predict_model(bundle, valid)
            metrics = predictive_metrics(valid, prediction)
            cache[(spec.model_id, 0, 0)] = bundle
            model_rows.append({
                "record_type": "MODEL_TRIAL", "phase": phase, "model_id": spec.model_id,
                "family": spec.family, "structure": spec.structure, "feature_family": spec.feature_family,
                "fold": 0, "seed": RANDOM_SEEDS[0], "status": "SUCCESS", **metrics,
            })
        except Exception as exc:
            model_rows.append({
                "record_type": "MODEL_TRIAL", "phase": phase, "model_id": spec.model_id,
                "family": spec.family, "structure": spec.structure, "feature_family": spec.feature_family,
                "fold": 0, "seed": RANDOM_SEEDS[0], "status": "FAILED_CONTINUE",
                "failure_reason": f"{type(exc).__name__}:{exc}",
            })
    screen = pd.DataFrame(model_rows)
    successful = screen.loc[screen.status.eq("SUCCESS")].copy()
    require(not successful.empty, "NO_MODEL_SCREEN_SUCCESS")
    successful["screen_score"] = successful.incremental_rank_ic + successful.top_bottom_residual_spread
    survivor_ids: list[str] = []
    for family in ("RIDGE", "ELASTIC_NET", "HGB", "CATBOOST"):
        candidates = successful.loc[successful.family.eq(family)].nlargest(2, "screen_score")
        survivor_ids.extend(candidates.model_id.astype(str).tolist())
    for model_id in successful.nlargest(10, "screen_score").model_id.astype(str):
        if model_id not in survivor_ids:
            survivor_ids.append(model_id)
        if len(survivor_ids) >= 10:
            break
    survivor_ids = survivor_ids[:10]
    spec_by_id = {spec.model_id: spec for spec in specs}
    phase_c_rows: list[dict[str, Any]] = []
    stability: dict[str, float] = {}
    for model_id in survivor_ids:
        spec = spec_by_id[model_id]
        all_scores: list[float] = []
        for fold_index, (start, end) in enumerate(folds):
            train = panel.loc[panel.label_end_date.lt(start)]
            valid = panel.loc[panel.signal_date.between(start, end) & panel.a2_rank.le(40) & panel.y_ff12res20.notna()]
            seeds = RANDOM_SEEDS if spec.family in {"HGB", "CATBOOST"} else RANDOM_SEEDS[:1]
            fold_scores: list[dict[str, float]] = []
            for seed_index, seed in enumerate(seeds):
                try:
                    bundle = cache.get((model_id, fold_index, seed_index))
                    if bundle is None:
                        bundle = fit_model(spec, train, seed, counter)
                        cache[(model_id, fold_index, seed_index)] = bundle
                    metrics = predictive_metrics(valid, predict_model(bundle, valid))
                    fold_scores.append(metrics)
                    all_scores.append(metrics["incremental_rank_ic"])
                except Exception as exc:
                    phase_c_rows.append({
                        "record_type": "MODEL_TRIAL", "phase": "C_LOCAL_REFINEMENT",
                        "model_id": model_id, "family": spec.family, "structure": spec.structure,
                        "feature_family": spec.feature_family, "fold": fold_index, "seed": seed,
                        "status": "FAILED_CONTINUE", "failure_reason": f"{type(exc).__name__}:{exc}",
                    })
            if fold_scores:
                phase_c_rows.append({
                    "record_type": "MODEL_TRIAL", "phase": "C_LOCAL_REFINEMENT",
                    "model_id": model_id, "family": spec.family, "structure": spec.structure,
                    "feature_family": spec.feature_family, "fold": fold_index, "seed": "MEDIAN",
                    "status": "SUCCESS", "rank_ic": float(np.median([row["rank_ic"] for row in fold_scores])),
                    "raw_rank_ic": float(np.median([row["raw_rank_ic"] for row in fold_scores])),
                    "incremental_rank_ic": float(np.median([row["incremental_rank_ic"] for row in fold_scores])),
                    "top_bottom_residual_spread": float(np.median([row["top_bottom_residual_spread"] for row in fold_scores])),
                    "seed_dispersion": float(np.std([row["incremental_rank_ic"] for row in fold_scores])),
                })
        stability[model_id] = float(np.std(all_scores)) if all_scores else math.inf
    model_ledger = pd.concat([screen, pd.DataFrame(phase_c_rows)], ignore_index=True, sort=False)
    summary = model_ledger.loc[
        model_ledger.phase.eq("C_LOCAL_REFINEMENT") & model_ledger.status.eq("SUCCESS")
    ].groupby("model_id").agg(
        folds=("fold", "nunique"), min_incremental_ic=("incremental_rank_ic", "min"),
        mean_incremental_ic=("incremental_rank_ic", "mean"),
        min_spread=("top_bottom_residual_spread", "min"),
    ).reset_index()
    summary["seed_dispersion"] = summary.model_id.map(stability)
    policy_model_ids = summary.loc[
        summary.folds.eq(2) & summary.min_incremental_ic.gt(0) & summary.seed_dispersion.le(0.10)
    ].sort_values(["min_incremental_ic", "mean_incremental_ic"], ascending=False).head(4).model_id.astype(str).tolist()
    if not policy_model_ids:
        return model_ledger, [], [], cache

    policy_specs = [
        PolicySpec(
            policy_id=f"P_{model_id}_ETA{str(eta).replace('.', 'P')}_{protection}",
            model_id=model_id, eta=eta, entry_protection=protection,
        )
        for model_id in policy_model_ids
        for eta in (0.10, 0.25, 0.50)
        for protection in ("EP0_NO_HARD_PROTECTION", "EP1_RAW_TOP10_PROTECTED")
    ]
    require(len(policy_specs) <= MAX_POLICY_SPECS, "POLICY_SPEC_BUDGET", len(policy_specs))
    policy_rows: list[dict[str, Any]] = []
    for fold_index, (start, end) in enumerate(folds):
        fold_panel = panel.loc[panel.signal_date.between(start, end)].copy()
        simple = simple_target_maps(fold_panel)
        simple_metrics: dict[str, dict[str, Any]] = {}
        for name, targets in simple.items():
            _, metrics = replay_arm(policy_module, e5, action, name, targets, prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
            simple_metrics[name] = metrics
            policy_rows.append({"record_type": "POLICY_TRIAL", "phase": "INNER_SIMPLE", "policy_id": name, "fold": fold_index, "status": "SUCCESS", **metrics})
        best_simple = max(("C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT", "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT"), key=lambda name: simple_metrics[name]["sharpe"])
        for policy_spec in policy_specs:
            try:
                bundle = cache[(policy_spec.model_id, fold_index, 0)]
                predicted = fold_panel.copy()
                predicted["model_signal"] = predict_model(bundle, predicted)
                targets = membership_targets(predicted, "model_signal", policy_spec.eta, policy_spec.entry_protection)
                _, metrics = replay_arm(policy_module, e5, action, policy_spec.policy_id, targets, prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
                predictive = predictive_metrics(
                    predicted.loc[predicted.a2_rank.le(40) & predicted.y_ff12res20.notna()],
                    predicted.loc[predicted.a2_rank.le(40) & predicted.y_ff12res20.notna(), "model_signal"],
                )
                policy_rows.append({
                    "record_type": "POLICY_TRIAL", "phase": "INNER_POLICY", "policy_id": policy_spec.policy_id,
                    "model_id": policy_spec.model_id, "eta": policy_spec.eta,
                    "entry_protection": policy_spec.entry_protection, "fold": fold_index, "status": "SUCCESS",
                    "best_simple": best_simple,
                    "delta_sharpe_raw": metrics["sharpe"] - simple_metrics["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"]["sharpe"],
                    "delta_sharpe_best_simple": metrics["sharpe"] - simple_metrics[best_simple]["sharpe"],
                    **predictive, **metrics,
                })
            except Exception as exc:
                policy_rows.append({
                    "record_type": "POLICY_TRIAL", "phase": "INNER_POLICY", "policy_id": policy_spec.policy_id,
                    "model_id": policy_spec.model_id, "eta": policy_spec.eta,
                    "entry_protection": policy_spec.entry_protection, "fold": fold_index,
                    "status": "FAILED_CONTINUE", "failure_reason": f"{type(exc).__name__}:{exc}",
                })
    policy_ledger = pd.DataFrame(policy_rows)
    candidates = policy_ledger.loc[policy_ledger.phase.eq("INNER_POLICY") & policy_ledger.status.eq("SUCCESS")]
    gate = candidates.groupby("policy_id").agg(
        folds=("fold", "nunique"), min_ic=("incremental_rank_ic", "min"),
        min_raw=("delta_sharpe_raw", "min"), min_simple=("delta_sharpe_best_simple", "min"),
        mean_simple=("delta_sharpe_best_simple", "mean"), max_nav=("nav_identity_error_max", "max"),
        min_positions=("position_count_min", "min"), max_gross=("gross_error_max", "max"),
    ).reset_index()
    gate["seed_stability"] = [stability.get(next(spec.model_id for spec in policy_specs if spec.policy_id == policy_id), math.inf) for policy_id in gate.policy_id]
    gate["inner_gate_pass"] = (
        gate.folds.eq(2) & gate.min_ic.gt(0) & gate.min_raw.gt(0) & gate.min_simple.ge(-0.02) &
        gate.max_nav.le(1e-10) & gate.min_positions.eq(20) & gate.max_gross.le(TOL) & gate.seed_stability.le(0.10)
    )
    finalists = gate.loc[gate.inner_gate_pass].sort_values(["min_simple", "mean_simple"], ascending=False).head(MAX_OUTER_FINALISTS).policy_id.astype(str).tolist()
    combined = pd.concat([model_ledger, policy_ledger], ignore_index=True, sort=False)
    return combined, policy_specs, finalists, cache


def run_outer(
    policy_module: Any,
    e5: Any,
    action: Any,
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    taxonomy: pd.DataFrame,
    specs: list[ModelSpec],
    policy_specs: list[PolicySpec],
    finalists: list[str],
    counter: FitCounter,
) -> tuple[pd.DataFrame, str | None, str, dict[tuple[int, str], Any], dict[tuple[int, str], dict[pd.Timestamp, dict[str, float]]], pd.DataFrame]:
    spec_by_id = {spec.model_id: spec for spec in specs}
    policy_by_id = {spec.policy_id: spec for spec in policy_specs}
    rows: list[dict[str, Any]] = []
    paths: dict[tuple[int, str], Any] = {}
    targets_by: dict[tuple[int, str], dict[pd.Timestamp, dict[str, float]]] = {}
    prediction_rows: list[pd.DataFrame] = []
    for year in (2023, 2024):
        validation = panel.loc[panel.signal_date.dt.year.eq(year)].copy()
        train = panel.loc[panel.label_end_date.lt(pd.Timestamp(f"{year}-01-01"))].copy()
        simple = simple_target_maps(validation)
        for name, targets in simple.items():
            replay, metrics = replay_arm(policy_module, e5, action, name, targets, prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
            capture = winner_capture(validation, targets)
            rows.append({"year": year, "kind": "SIMPLE", "policy_id": name, "status": "SUCCESS", "winner_capture": capture, **metrics})
            paths[(year, name)] = replay
            targets_by[(year, name)] = targets
        bundles: dict[str, FittedModel] = {}
        for policy_id in finalists:
            policy_spec = policy_by_id[policy_id]
            try:
                if policy_spec.model_id not in bundles:
                    bundles[policy_spec.model_id] = fit_model(spec_by_id[policy_spec.model_id], train, RANDOM_SEEDS[0], counter)
                predicted = validation.copy()
                predicted["model_signal"] = predict_model(bundles[policy_spec.model_id], predicted)
                targets = membership_targets(predicted, "model_signal", policy_spec.eta, policy_spec.entry_protection)
                replay, metrics = replay_arm(policy_module, e5, action, policy_id, targets, prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
                capture = winner_capture(validation, targets)
                rows.append({
                    "year": year, "kind": "ML", "policy_id": policy_id, "model_id": policy_spec.model_id,
                    "eta": policy_spec.eta, "entry_protection": policy_spec.entry_protection,
                    "status": "SUCCESS", "winner_capture": capture, **metrics,
                })
                paths[(year, policy_id)] = replay
                targets_by[(year, policy_id)] = targets
                prediction_rows.append(predicted[["signal_date", "ticker", "a2_rank", "ff12", "accession", "feature_effective_date", "model_signal", "winner60", "y_ff12res20"]].assign(year=year, policy_id=policy_id))
            except Exception as exc:
                rows.append({"year": year, "kind": "ML", "policy_id": policy_id, "model_id": policy_spec.model_id, "status": "FAILED_CONTINUE", "failure_reason": f"{type(exc).__name__}:{exc}"})
    outer = pd.DataFrame(rows)
    successful = outer.loc[outer.status.eq("SUCCESS")].copy()
    delta_rows: list[dict[str, Any]] = []
    for row in successful.loc[successful.kind.eq("ML")].itertuples(index=False):
        year_simple = successful.loc[successful.year.eq(row.year) & successful.kind.eq("SIMPLE")]
        best_simple = year_simple.loc[year_simple.policy_id.isin(["C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT", "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT"])].sort_values("sharpe", ascending=False).iloc[0]
        raw = year_simple.loc[year_simple.policy_id.eq("C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].iloc[0]
        delta_rows.append({
            "policy_id": row.policy_id, "year": row.year, "best_simple_name": best_simple.policy_id,
            "delta_sharpe_raw": row.sharpe - raw.sharpe,
            "delta_sharpe_best_simple": row.sharpe - best_simple.sharpe,
            "delta_cagr_raw": row.cagr - raw.cagr,
            "maxdd_worsening_pp": max(0.0, (abs(row.max_drawdown) - abs(raw.max_drawdown)) * 100),
            "winner_capture_delta": row.winner_capture - raw.winner_capture,
            "qqq_beta_delta": row.qqq_beta - raw.qqq_beta,
            "ff12_hhi_delta": row.ff12_hhi - raw.ff12_hhi,
            "ff48_hhi_delta": row.ff48_hhi - raw.ff48_hhi,
        })
    if delta_rows:
        outer = outer.merge(pd.DataFrame(delta_rows), on=["policy_id", "year"], how="left")

    candidate_gate_rows: list[dict[str, Any]] = []
    for policy_id in finalists:
        folds = outer.loc[outer.policy_id.eq(policy_id) & outer.status.eq("SUCCESS")]
        deltas = outer.loc[outer.policy_id.eq(policy_id) & outer.delta_sharpe_raw.notna()]
        if len(folds) != 2 or len(deltas) != 2:
            continue
        primary_returns = pd.concat([paths[(year, policy_id)].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
        raw_returns = pd.concat([paths[(year, "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
        pooled_delta = return_metrics(primary_returns)["sharpe"] - return_metrics(raw_returns)["sharpe"]
        passed = (
            deltas.delta_sharpe_raw.gt(0).all() & deltas.delta_sharpe_best_simple.ge(0).all() &
            (pooled_delta >= 0.05) & deltas.maxdd_worsening_pp.le(2.0).all() &
            deltas.delta_cagr_raw.ge(-0.03).all() & deltas.winner_capture_delta.ge(0).all() &
            deltas.qqq_beta_delta.le(0.10).all() & deltas.ff12_hhi_delta.le(0.02).all() &
            deltas.ff48_hhi_delta.le(0.02).all()
        )
        candidate_gate_rows.append({
            "policy_id": policy_id, "robust_delta_best_simple": float(deltas.delta_sharpe_best_simple.min()),
            "pooled_delta_sharpe_raw": pooled_delta, "positive_folds": int(deltas.delta_sharpe_raw.gt(0).sum()),
            "outer_gate_pass": bool(passed),
        })

    eligible = pd.DataFrame(candidate_gate_rows)
    primary_id: str | None = None
    classification = "NO_ROBUST_INCREMENTAL_ALPHA"
    if not eligible.empty and eligible.outer_gate_pass.any():
        chosen = eligible.loc[eligible.outer_gate_pass].sort_values(["robust_delta_best_simple", "pooled_delta_sharpe_raw"], ascending=False).iloc[0]
        primary_id = str(chosen.policy_id)
        classification = "PIT_FUNDAMENTAL_INCREMENTAL_ALPHA_SUPPORTED"
    else:
        # A simple tilt may be the economically sufficient treatment even when
        # no complex model clears its incremental gate.
        simple_candidates = []
        for name in ("C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT", "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT"):
            fold_rows = successful.loc[successful.policy_id.eq(name)]
            raw_rows = successful.loc[successful.policy_id.eq("C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].set_index("year")
            if len(fold_rows) != 2:
                continue
            deltas = [float(row.sharpe - raw_rows.loc[row.year, "sharpe"]) for row in fold_rows.itertuples(index=False)]
            primary_returns = pd.concat([paths[(year, name)].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
            raw_returns = pd.concat([paths[(year, "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
            pooled_delta = return_metrics(primary_returns)["sharpe"] - return_metrics(raw_returns)["sharpe"]
            winner_delta = min(float(fold_rows.loc[fold_rows.year.eq(year), "winner_capture"].iloc[0] - raw_rows.loc[year, "winner_capture"]) for year in (2023, 2024))
            if min(deltas) > 0 and pooled_delta >= 0.05 and winner_delta >= 0:
                simple_candidates.append((min(deltas), pooled_delta, name))
        if simple_candidates:
            primary_id = max(simple_candidates)[2]
            classification = "SIMPLE_FUNDAMENTAL_TILT_SUFFICIENT"
    prediction_frame = pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame()
    if candidate_gate_rows:
        gate_frame = pd.DataFrame(candidate_gate_rows)
        for row in gate_frame.itertuples(index=False):
            outer = pd.concat([outer, pd.DataFrame([{"year": "POOLED_2023_2024", "kind": "OUTER_GATE", **row._asdict()}])], ignore_index=True, sort=False)
    return outer, primary_id, classification, paths, targets_by, prediction_frame


def contribution_and_robustness(
    primary_id: str | None,
    paths: Mapping[tuple[int, str], Any],
    panel: pd.DataFrame,
    outer_finalists: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    empty_facts = {
        "top3_vintage_positive_contribution_share": math.nan,
        "ex_best1_vintage": math.nan, "ex_best3_vintages": math.nan,
        "ex_best5_vintages": math.nan, "ex_best1_security": math.nan,
        "ex_best3_securities": math.nan, "ex_best_ff12": math.nan,
        "multiple_testing_status": "NOT_APPLICABLE_NO_PRIMARY",
        "effective_trial_count": 0.0, "deflated_sharpe_status": "NOT_APPLICABLE_NO_PRIMARY",
        "quarter_cluster_bootstrap_status": "NOT_APPLICABLE_NO_PRIMARY",
        "rebalance_cluster_bootstrap_status": "NOT_APPLICABLE_NO_PRIMARY",
        "vintage_concentrated": False,
    }
    if primary_id is None:
        return pd.DataFrame(columns=["attribution_type", "group", "year", "delta_contribution"]), pd.DataFrame([{"record_type": "MULTIPLE_TESTING", **empty_facts}]), empty_facts
    contribution_parts: list[pd.DataFrame] = []
    delta_daily_parts: list[pd.Series] = []
    candidate_returns: list[pd.Series] = []
    for year in (2023, 2024):
        primary = paths[(year, primary_id)]
        raw = paths[(year, "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")]
        p = primary.contributions.groupby(["execution_date", "signal_date", "ticker"], as_index=False).net_contribution.sum()
        r = raw.contributions.groupby(["execution_date", "signal_date", "ticker"], as_index=False).net_contribution.sum()
        merged = p.merge(r, on=["execution_date", "signal_date", "ticker"], how="outer", suffixes=("_primary", "_raw")).fillna({"net_contribution_primary": 0.0, "net_contribution_raw": 0.0})
        merged["delta_contribution"] = merged.net_contribution_primary - merged.net_contribution_raw
        merged["year"] = year
        contribution_parts.append(merged)
        daily = pd.concat([
            primary.daily.set_index("execution_date").net_return.rename("primary"),
            raw.daily.set_index("execution_date").net_return.rename("raw"),
        ], axis=1, join="inner").dropna()
        delta_daily_parts.append((daily.primary - daily.raw).rename(str(year)))
        for candidate in outer_finalists:
            if (year, candidate) in paths:
                candidate_returns.append(paths[(year, candidate)].daily.set_index("execution_date").net_return.rename(f"{year}:{candidate}"))
    contributions = pd.concat(contribution_parts, ignore_index=True)
    lookup = panel[["signal_date", "ticker", "feature_effective_date", "accession", "ff12"]].drop_duplicates(["signal_date", "ticker"])
    contributions = contributions.merge(lookup, on=["signal_date", "ticker"], how="left")
    contributions["filing_vintage"] = pd.to_datetime(contributions.feature_effective_date).dt.to_period("Q").astype("string").fillna("MISSING")
    total = float(contributions.delta_contribution.sum())
    positive_by_vintage = contributions.groupby("filing_vintage").delta_contribution.sum().clip(lower=0.0).sort_values(ascending=False)
    positive_total = float(positive_by_vintage.sum())
    top3_share = float(positive_by_vintage.head(3).sum() / positive_total) if positive_total > 0 else math.nan

    attribution_rows: list[dict[str, Any]] = []
    for year in (2023, 2024):
        subset = contributions.loc[contributions.year.eq(year)]
        for attribution_type, column in (("FILING_VINTAGE", "filing_vintage"), ("REBALANCE", "signal_date"), ("SECURITY", "ticker"), ("FF12", "ff12")):
            for group, value in subset.groupby(column, dropna=False).delta_contribution.sum().items():
                attribution_rows.append({"attribution_type": attribution_type, "group": str(group), "year": year, "delta_contribution": float(value)})

    def ex_best(column: str, count: int) -> float:
        values = contributions.groupby(column, dropna=False).delta_contribution.sum().sort_values(ascending=False)
        return float(total - values.head(count).sum())

    rng = np.random.default_rng(20260824)
    def cluster_bootstrap(column: str) -> tuple[float, float]:
        clusters = contributions.groupby(column, dropna=False).delta_contribution.sum().to_numpy(float)
        if len(clusters) < 4:
            return math.nan, math.nan
        draws = [float(rng.choice(clusters, size=len(clusters), replace=True).sum()) for _ in range(2000)]
        low, high = np.quantile(draws, [0.025, 0.975])
        return float(low), float(high)

    quarter_low, quarter_high = cluster_bootstrap("filing_vintage")
    rebalance_low, rebalance_high = cluster_bootstrap("signal_date")
    delta_daily = pd.concat(delta_daily_parts).sort_index()
    observed = return_metrics(delta_daily)["sharpe"]
    if candidate_returns:
        wide = pd.concat(candidate_returns, axis=1).fillna(0.0)
        matrix = wide.corr()
        offdiag = matrix.where(~np.eye(len(matrix), dtype=bool)).stack()
        mean_correlation = float(offdiag.mean()) if len(offdiag) else 1.0
    else:
        mean_correlation = 1.0
    trial_count = max(1, len(set(outer_finalists)))
    effective_trials = float(max(1.0, 1.0 + (trial_count - 1.0) * (1.0 - max(0.0, min(1.0, mean_correlation)))))
    standard_error = math.sqrt(max(1e-12, (1.0 + 0.5 * observed * observed) / max(2, len(delta_daily) - 1))) if np.isfinite(observed) else math.inf
    expected_max = norm.ppf(max(0.50, 1.0 - 1.0 / max(2.0, effective_trials))) * standard_error
    deflated_probability = float(norm.cdf((observed - expected_max) / standard_error)) if np.isfinite(observed) and np.isfinite(standard_error) else 0.0
    deflated_status = "PASS" if deflated_probability >= 0.95 else "FAIL"
    quarter_status = "PASS" if np.isfinite(quarter_low) and quarter_low > 0 else "FAIL"
    rebalance_status = "PASS" if np.isfinite(rebalance_low) and rebalance_low > 0 else "FAIL"
    multiple_status = "PASS" if deflated_status == quarter_status == rebalance_status == "PASS" else "FAIL"
    facts = {
        "top3_vintage_positive_contribution_share": top3_share,
        "ex_best1_vintage": ex_best("filing_vintage", 1),
        "ex_best3_vintages": ex_best("filing_vintage", 3),
        "ex_best5_vintages": ex_best("filing_vintage", 5),
        "ex_best1_security": ex_best("ticker", 1),
        "ex_best3_securities": ex_best("ticker", 3),
        "ex_best_ff12": ex_best("ff12", 1),
        "multiple_testing_status": multiple_status,
        "effective_trial_count": effective_trials,
        "deflated_sharpe_status": deflated_status,
        "deflated_sharpe_probability": deflated_probability,
        "quarter_cluster_bootstrap_status": quarter_status,
        "quarter_cluster_ci_low": quarter_low, "quarter_cluster_ci_high": quarter_high,
        "rebalance_cluster_bootstrap_status": rebalance_status,
        "rebalance_cluster_ci_low": rebalance_low, "rebalance_cluster_ci_high": rebalance_high,
        "vintage_concentrated": bool(np.isfinite(top3_share) and top3_share > 0.50),
    }
    robust = pd.DataFrame([
        {"record_type": "MULTIPLE_TESTING", **facts},
        {"record_type": "CONTRIBUTION_BREADTH", **facts},
    ])
    return pd.DataFrame(attribution_rows), robust, facts


def evaluate_2025(
    primary_id: str | None,
    policy_module: Any,
    e5: Any,
    action: Any,
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    taxonomy: pd.DataFrame,
    model_specs: list[ModelSpec],
    policy_specs: list[PolicySpec],
    best_simple_name: str,
    counter: FitCounter,
) -> tuple[pd.DataFrame, str, bool, FittedModel | None, dict[pd.Timestamp, dict[str, float]] | None]:
    validation = panel.loc[panel.signal_date.dt.year.eq(2025)].copy()
    simple = simple_target_maps(validation)
    rows: list[dict[str, Any]] = []
    paths: dict[str, Any] = {}
    for name in ("C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL", best_simple_name):
        replay, metrics = replay_arm(policy_module, e5, action, name, simple[name], prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
        rows.append({"year": 2025, "kind": "SIMPLE", "policy_id": name, "status": "SUCCESS", "winner_capture": winner_capture(validation, simple[name]), **metrics})
        paths[name] = replay
    if primary_id is None:
        return pd.DataFrame(rows), "NOT_APPLICABLE:NO_PRIMARY", False, None, None
    bundle: FittedModel | None = None
    if primary_id in simple:
        targets = simple[primary_id]
        kind = "SIMPLE_PRIMARY"
    else:
        policy_by_id = {spec.policy_id: spec for spec in policy_specs}
        model_by_id = {spec.model_id: spec for spec in model_specs}
        policy_spec = policy_by_id[primary_id]
        train = panel.loc[panel.label_end_date.lt(pd.Timestamp("2025-01-01"))]
        bundle = fit_model(model_by_id[policy_spec.model_id], train, RANDOM_SEEDS[0], counter)
        predicted = validation.copy()
        predicted["model_signal"] = predict_model(bundle, predicted)
        targets = membership_targets(predicted, "model_signal", policy_spec.eta, policy_spec.entry_protection)
        kind = "ML_PRIMARY"
    replay, metrics = replay_arm(policy_module, e5, action, primary_id, targets, prices, simple["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"], taxonomy)
    capture = winner_capture(validation, targets)
    rows.append({"year": 2025, "kind": kind, "policy_id": primary_id, "status": "SUCCESS", "winner_capture": capture, **metrics})
    raw = next(row for row in rows if row["policy_id"] == "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")
    catastrophic = (metrics["sharpe"] - raw["sharpe"] < -0.15) or ((abs(metrics["max_drawdown"]) - abs(raw["max_drawdown"])) * 100 > 5.0)
    diagnostic = f"Sharpe={metrics['sharpe']:.6f};DeltaRaw={metrics['sharpe']-raw['sharpe']:.6f};MaxDD={metrics['max_drawdown']:.6f}"
    return pd.DataFrame(rows), diagnostic, catastrophic, bundle, targets


def value(summary: Mapping[str, Any], key: str, default: Any = "NOT_APPLICABLE") -> Any:
    item = summary.get(key, default)
    if item is None:
        return default
    return item


def final_block(summary: Mapping[str, Any]) -> str:
    keys = [
        "RESEARCH_STATUS", "ENVIRONMENT_STATUS", "ECONOMIC_VERDICT", "",
        "NOVELTY_AUDIT_STATUS", "EXACT_DUPLICATE_COUNT", "PARTIAL_OVERLAP_COUNT",
        "NOVEL_CORE_FEATURE_FAMILY_COUNT", "EXISTING_A2_FUNDAMENTAL_LINEAGE_STATUS", "",
        "SEC_DATA_SOURCE", "SEC_CACHE_PATH", "SEC_REQUEST_COUNT", "SEC_CACHE_HIT_COUNT", "",
        "TOTAL_SECURITIES", "CIK_RESOLVED_COUNT", "CIK_UNRESOLVED_COUNT", "DOMESTIC_FILER_COUNT", "FOREIGN_FILER_COUNT", "",
        "TOTAL_FILINGS", "TOTAL_10Q", "TOTAL_10K", "TOTAL_AMENDMENTS", "MAX_ACCEPTED_DATETIME_USED", "",
        "PIT_EFFECTIVE_DATE_STATUS", "RESTATEMENT_GUARD_STATUS", "UNIT_SCALE_STATUS", "CONCEPT_CONTRACT_STATUS", "",
        "FEATURE_COVERAGE_MEDIAN", "RAW_TOP40_COVERAGE_MEDIAN", "DECISION_DATES_PASSING_COVERAGE_GATE", "DILUTION_FEATURE_STATUS", "",
        "LABEL_PRICE_LINEAGE", "LABEL_ARITHMETIC_MISMATCH_COUNT", "2026_OUTCOME_USED", "2026_LEAKAGE_COUNT", "FINAL_TRAIN_MAX_LABEL_END_DATE", "",
        "AUTHORITATIVE_RAW_REPLAY_STATUS", "AUTHORITATIVE_RAW_SESSIONS", "AUTHORITATIVE_RAW_CAGR", "AUTHORITATIVE_RAW_SHARPE", "AUTHORITATIVE_RAW_MAXDD", "",
        "UNIQUE_MODEL_SPECS", "TOTAL_MODEL_FITS", "TOTAL_POLICY_SPECS", "OUTER_FINALIST_COUNT", "",
        "PRIMARY_MODEL", "PRIMARY_FEATURE_SET", "PRIMARY_POLICY", "PRIMARY_RAW_PRIOR_ETA", "PRIMARY_ENTRY_PROTECTION", "PRIMARY_FIXED_BEFORE_2025_READ", "",
        "RAW_SHARPE", "BEST_SIMPLE_NAME", "BEST_SIMPLE_SHARPE", "PRIMARY_SHARPE", "",
        "2023_DELTA_SHARPE_VS_RAW", "2023_DELTA_SHARPE_VS_BEST_SIMPLE", "2024_DELTA_SHARPE_VS_RAW", "2024_DELTA_SHARPE_VS_BEST_SIMPLE",
        "POOLED_DELTA_SHARPE_VS_RAW", "POSITIVE_HISTORICAL_OOS_FOLDS", "",
        "PRIMARY_DELTA_CAGR_VS_RAW", "PRIMARY_DELTA_MAXDD_VS_RAW", "PRIMARY_DELTA_TURNOVER", "PRIMARY_DELTA_COST", "PRIMARY_WINNER_CAPTURE_DELTA", "",
        "RAW_SCORE_CORRELATION", "INCREMENTAL_RANK_IC", "PARTIAL_RANK_IC", "ORTHOGONALITY_STATUS", "",
        "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "EX_BEST1_VINTAGE", "EX_BEST3_VINTAGES", "EX_BEST5_VINTAGES",
        "EX_BEST1_SECURITY", "EX_BEST3_SECURITIES", "EX_BEST_FF12", "",
        "MULTIPLE_TESTING_STATUS", "EFFECTIVE_TRIAL_COUNT", "DEFLATED_SHARPE_STATUS", "QUARTER_CLUSTER_BOOTSTRAP_STATUS", "",
        "EVIDENCE_CLASS", "", "2025_STATUS", "PRIMARY_2025_DIAGNOSTIC", "PRIMARY_CHANGED_AFTER_2025_READ", "",
        "FORWARD_ELIGIBLE", "FORWARD_ROLE", "FINAL_FORWARD_MODEL_ID", "FINAL_FORWARD_MODEL_HASH", "",
        "PRIMARY_CLASSIFICATION", "", "MAIN_NOVELTY_LESSON", "MAIN_FUNDAMENTAL_LESSON", "MAIN_ORTHOGONALITY_LESSON",
        "MAIN_WINNER_CAPTURE_LESSON", "MAIN_VINTAGE_RISK", "STRONGEST_SUPPORTING_EVIDENCE", "MOST_DAMAGING_EVIDENCE", "",
        "TASK_LOCAL_ANTI_BLOAT_STATUS", "PREEXISTING_ACL_EXCEPTION_COUNT", "FINAL_ARTIFACT_COUNT", "HASH_MANIFEST_STATUS",
    ]
    lines = ["=" * 60, "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_FINAL", "=" * 60, ""]
    for key in keys:
        lines.append("") if not key else lines.append(f"{key}={value(summary, key)}")
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def render_report(summary: Mapping[str, Any]) -> str:
    return f"""# A2 PIT SEC Fundamental Acceleration Alpha R1

## Verdict

`{value(summary, 'ECONOMIC_VERDICT')}` / `{value(summary, 'PRIMARY_CLASSIFICATION')}`.

The task tests only equal-weight Top20 membership. It does not change position
sizes, gross exposure, cash, Hold/Replace rules, 13F-change signals, or broker
state. Evidence from 2023/2024 is classified as fixed historical OOS, not a
pristine or prospective holdout.

## Novelty and overlap

- Novelty audit: `{value(summary, 'NOVELTY_AUDIT_STATUS')}`; exact duplicates:
  {value(summary, 'EXACT_DUPLICATE_COUNT')}; partial overlaps:
  {value(summary, 'PARTIAL_OVERLAP_COUNT')}.
- Existing V21.086 fundamentals are provider-cache diagnostics with filing/report
  date fallback, not accession/actual-acceptance-time lineage. Existing SEC A2
  work supplies CIK/SIC/FF12/FF48 identity and taxonomy, not financial-change
  economic research.
- Novel strict-PIT core families: {value(summary, 'NOVEL_CORE_FEATURE_FAMILY_COUNT')}.

## SEC lineage and PIT controls

- Source: `{value(summary, 'SEC_DATA_SOURCE')}`; request/cache hits:
  {value(summary, 'SEC_REQUEST_COUNT')} / {value(summary, 'SEC_CACHE_HIT_COUNT')}.
- CIK resolution: {value(summary, 'CIK_RESOLVED_COUNT')} resolved and
  {value(summary, 'CIK_UNRESOLVED_COUNT')} unresolved out of
  {value(summary, 'TOTAL_SECURITIES')} securities.
- Filings: {value(summary, 'TOTAL_FILINGS')}; latest accepted timestamp used:
  `{value(summary, 'MAX_ACCEPTED_DATETIME_USED')}`.
- Effective-date / restatement / unit controls:
  `{value(summary, 'PIT_EFFECTIVE_DATE_STATUS')}` /
  `{value(summary, 'RESTATEMENT_GUARD_STATUS')}` /
  `{value(summary, 'UNIT_SCALE_STATUS')}`.
- Amendments become visible only from their own acceptance timestamp. Every
  state points to accession-specific facts and a lineage hash; later facts are
  never backfilled.

## Coverage and labels

- Raw Top40 median coverage: {value(summary, 'RAW_TOP40_COVERAGE_MEDIAN')};
  decision-date gate fraction: {value(summary, 'DECISION_DATES_PASSING_COVERAGE_GATE')}.
- Missing fundamentals never remove a security. Missing observations remain
  eligible and are neutral after cross-sectional rank normalization, with
  explicit missing indicators.
- Economic labels use `{value(summary, 'LABEL_PRICE_LINEAGE')}`. Arithmetic
  mismatches: {value(summary, 'LABEL_ARITHMETIC_MISMATCH_COUNT')}; 2026 leakage:
  {value(summary, '2026_LEAKAGE_COUNT')}.
- Share dilution is `{value(summary, 'DILUTION_FEATURE_STATUS')}` because no
  separately proven same-share-scale lineage was introduced.

## Historical economic evidence

- Raw authoritative replay: {value(summary, 'AUTHORITATIVE_RAW_SESSIONS')}
  sessions, CAGR {value(summary, 'AUTHORITATIVE_RAW_CAGR')}, Sharpe
  {value(summary, 'AUTHORITATIVE_RAW_SHARPE')}, MaxDD
  {value(summary, 'AUTHORITATIVE_RAW_MAXDD')}.
- Best simple fundamental arm: `{value(summary, 'BEST_SIMPLE_NAME')}`, pooled
  Sharpe {value(summary, 'BEST_SIMPLE_SHARPE')}.
- Frozen Primary: `{value(summary, 'PRIMARY_POLICY')}`, pooled Sharpe
  {value(summary, 'PRIMARY_SHARPE')}; 2023/2024 Sharpe deltas versus Raw are
  {value(summary, '2023_DELTA_SHARPE_VS_RAW')} and
  {value(summary, '2024_DELTA_SHARPE_VS_RAW')}.
- Winner capture delta: {value(summary, 'PRIMARY_WINNER_CAPTURE_DELTA')}.

## Orthogonality, robustness, and vintage risk

- Fundamental/Raw score rank correlation: {value(summary, 'RAW_SCORE_CORRELATION')}.
- Incremental and partial rank IC: {value(summary, 'INCREMENTAL_RANK_IC')} /
  {value(summary, 'PARTIAL_RANK_IC')} (`{value(summary, 'ORTHOGONALITY_STATUS')}`).
- Top-three filing-vintage positive-contribution share:
  {value(summary, 'TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE')}.
- Multiple testing / Deflated Sharpe / quarter bootstrap:
  `{value(summary, 'MULTIPLE_TESTING_STATUS')}` /
  `{value(summary, 'DEFLATED_SHARPE_STATUS')}` /
  `{value(summary, 'QUARTER_CLUSTER_BOOTSTRAP_STATUS')}`.

## 2025 and forward decision

The Primary specification was durable before any corrected 2025 policy
diagnostic. 2025 status: `{value(summary, '2025_STATUS')}`; diagnostic:
`{value(summary, 'PRIMARY_2025_DIAGNOSTIC')}`. The Primary was not changed after
that read. Forward eligibility is `{value(summary, 'FORWARD_ELIGIBLE')}` with
role `{value(summary, 'FORWARD_ROLE')}`. Even an eligible result is only a new
frozen prospective challenger and never a canonical promotion.

## Required interpretation

- Novelty: {value(summary, 'MAIN_NOVELTY_LESSON')}.
- Fundamental evidence: {value(summary, 'MAIN_FUNDAMENTAL_LESSON')}.
- Orthogonality: {value(summary, 'MAIN_ORTHOGONALITY_LESSON')}.
- Winner capture: {value(summary, 'MAIN_WINNER_CAPTURE_LESSON')}.
- Vintage risk: {value(summary, 'MAIN_VINTAGE_RISK')}.
- Strongest evidence: {value(summary, 'STRONGEST_SUPPORTING_EVIDENCE')}.
- Most damaging evidence: {value(summary, 'MOST_DAMAGING_EVIDENCE')}.

## Governance

No Moomoo API, new dependency, repository-local environment, dynamic sizing,
portfolio optimizer, 13F-change reopening, broker binding, or production
promotion was used. Task-local Anti-Bloat status is
`{value(summary, 'TASK_LOCAL_ANTI_BLOAT_STATUS')}`; the two pre-existing managed
ACL objects remain a separate environment exception.

```text
{final_block(summary)}
```
"""


def write_final_artifacts(
    summary: dict[str, Any],
    feature_ledger: pd.DataFrame,
    trial_ledger: pd.DataFrame,
    outer_metrics: pd.DataFrame,
    vintage: pd.DataFrame,
    robustness: pd.DataFrame,
    freeze: dict[str, Any],
    cache_manifest_path: Path | None,
    unresolved_impact: pd.DataFrame | None = None,
) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_parquet(OUT / "fundamental_feature_ledger.parquet", feature_ledger)
    for column in trial_ledger.select_dtypes(include=["object"]).columns:
        trial_ledger[column] = trial_ledger[column].map(
            lambda item: json.dumps(item, sort_keys=True, default=str) if isinstance(item, (dict, list, tuple, set)) else item
        )
    atomic_parquet(OUT / "trial_ledger.parquet", trial_ledger)
    outer_metrics.to_csv(OUT / "outer_metrics.csv", index=False, lineterminator="\n")
    vintage.to_csv(OUT / "vintage_attribution.csv", index=False, lineterminator="\n")
    robustness.to_csv(OUT / "robustness_metrics.csv", index=False, lineterminator="\n")
    if unresolved_impact is not None and not unresolved_impact.empty:
        unresolved_impact.to_csv(OUT / "targeted_unresolved_impact.csv", index=False, lineterminator="\n")
    atomic_json(OUT / "finalist_freeze.json", freeze)
    nonmanifest_names = {path.name for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json"}
    nonmanifest_names.add("final_report.md")
    summary["FINAL_ARTIFACT_COUNT"] = len(nonmanifest_names) + 1
    summary["HASH_MANIFEST_STATUS"] = "PASS_HASH_VERIFIED"
    (OUT / "final_report.md").write_text(render_report(summary), encoding="utf-8")
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest = {
        "research_id": TASK, "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files],
        "source_sha256": sha256_file(Path(__file__)),
        "authoritative_inputs": {
            "a2_matrix": sha256_file(MATRIX), "a2_oof": sha256_file(OOF),
            "universe_intervals": sha256_file(UNIVERSE_INTERVALS),
            "prior_sec_sub": sha256_file(PRIOR_SEC_SUB) if PRIOR_SEC_SUB.is_file() else "MISSING",
            "sec_cache_manifest": sha256_file(cache_manifest_path) if cache_manifest_path and cache_manifest_path.is_file() else "NOT_AVAILABLE",
            "sec_bulk_snapshot_manifest": sha256_file(BULK_SNAPSHOT_MANIFEST) if BULK_SNAPSHOT_MANIFEST.is_file() else "NOT_AVAILABLE",
            "companyfacts_bulk_sha256": BULK_CONTRACT["companyfacts"]["sha256"],
            "submissions_bulk_sha256": BULK_CONTRACT["submissions"]["sha256"],
            "frozen_prior_coverage_preregistration": FROZEN_PREREG_SHA256,
        },
        "2026_outcome_used": False, "2026_leakage_count": 0,
        "automatic_promotion": False, "task_local_anti_bloat_status": summary["TASK_LOCAL_ANTI_BLOAT_STATUS"],
    }
    atomic_json(OUT / "hash_manifest.json", manifest)
    require(len(list(OUT.glob("*"))) <= 12, "ARTIFACT_BUDGET", len(list(OUT.glob("*"))))
    for item in manifest["artifacts"]:
        require(sha256_file(OUT / item["name"]) == item["sha256"], "ARTIFACT_HASH_FAILURE", item["name"])
    return manifest


def freeze_json(path: Path, payload: dict[str, Any], hash_key: str = "contract_hash") -> str:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        require(existing.get(hash_key) == payload.get(hash_key), "FROZEN_CONTRACT_MISMATCH", path)
    else:
        atomic_json(path, payload)
    return sha256_file(path)


def feature_only_panel(mapped_pool: pd.DataFrame, states: pd.DataFrame, taxonomy: pd.DataFrame, matrix_features: pd.DataFrame) -> pd.DataFrame:
    panel = attach_features_asof(mapped_pool, states)
    panel = panel.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], how="left", validate="one_to_one")
    panel["ff12"] = panel.ff12.fillna("UNKNOWN").astype(str)
    panel["ff48"] = panel.ff48.fillna("UNKNOWN").astype(str)
    panel = panel.merge(matrix_features, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    return normalize_feature_panel(panel)


def _empty_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    feature = pd.DataFrame(columns=["security_id", "feature_effective_date", "accession"])
    trial = pd.DataFrame([{"record_type": "NO_TRIALS", "status": "NOT_RUN"}])
    outer = pd.DataFrame(columns=["year", "kind", "policy_id", "status", "sharpe"])
    vintage = pd.DataFrame(columns=["attribution_type", "group", "year", "delta_contribution"])
    return feature, trial, outer, vintage


def main() -> int:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    novelty, novelty_facts = novelty_audit()
    current_source_hash = sha256_file(Path(__file__))
    novelty.loc[novelty.classification.eq("NOVEL_PIT_FEATURE"), "source_sha256"] = current_source_hash
    novelty.to_csv(OUT / "feature_novelty_audit.csv", index=False, lineterminator="\n")

    summary: dict[str, Any] = {
        "RESEARCH_STATUS": "IN_PROGRESS", "ENVIRONMENT_STATUS": "PREEXISTING_EXCEPTION_MANAGED_ACL_OBJECTS_2",
        "ECONOMIC_VERDICT": "NO_VERDICT", "NOVELTY_AUDIT_STATUS": novelty_facts["novelty_audit_status"],
        "EXACT_DUPLICATE_COUNT": novelty_facts["exact_duplicate_count"],
        "PARTIAL_OVERLAP_COUNT": novelty_facts["partial_overlap_count"],
        "NOVEL_CORE_FEATURE_FAMILY_COUNT": novelty_facts["novel_core_feature_family_count"],
        "EXISTING_A2_FUNDAMENTAL_LINEAGE_STATUS": novelty_facts["existing_a2_fundamental_lineage_status"],
        "SEC_DATA_SOURCE": "OFFICIAL_SEC_HASH_FROZEN_COMPANYFACTS_AND_SUBMISSIONS_BULK_OFFLINE",
        "SEC_CACHE_PATH": str(CACHE_ROOT), "SEC_REQUEST_COUNT": 0, "SEC_CACHE_HIT_COUNT": 0,
        "TOTAL_SECURITIES": 0, "CIK_RESOLVED_COUNT": 0, "CIK_UNRESOLVED_COUNT": 0,
        "DOMESTIC_FILER_COUNT": 0, "FOREIGN_FILER_COUNT": 0,
        "TOTAL_FILINGS": 0, "TOTAL_10Q": 0, "TOTAL_10K": 0, "TOTAL_AMENDMENTS": 0,
        "MAX_ACCEPTED_DATETIME_USED": "NOT_APPLICABLE", "PIT_EFFECTIVE_DATE_STATUS": "NOT_RUN",
        "RESTATEMENT_GUARD_STATUS": "NOT_RUN", "UNIT_SCALE_STATUS": "NOT_RUN",
        "CONCEPT_CONTRACT_STATUS": "NOT_FROZEN", "FEATURE_COVERAGE_MEDIAN": 0.0,
        "RAW_TOP40_COVERAGE_MEDIAN": 0.0, "DECISION_DATES_PASSING_COVERAGE_GATE": 0.0,
        "DILUTION_FEATURE_STATUS": "DISABLED_SCALE_UNSAFE", "LABEL_PRICE_LINEAGE": "continuous_raw_counterfactual",
        "LABEL_ARITHMETIC_MISMATCH_COUNT": 0, "2026_OUTCOME_USED": "FALSE", "2026_LEAKAGE_COUNT": 0,
        "FINAL_TRAIN_MAX_LABEL_END_DATE": "NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY",
        "AUTHORITATIVE_RAW_REPLAY_STATUS": "NOT_RUN", "AUTHORITATIVE_RAW_SESSIONS": 0,
        "AUTHORITATIVE_RAW_CAGR": math.nan, "AUTHORITATIVE_RAW_SHARPE": math.nan, "AUTHORITATIVE_RAW_MAXDD": math.nan,
        "UNIQUE_MODEL_SPECS": 0, "TOTAL_MODEL_FITS": 0, "TOTAL_POLICY_SPECS": 0, "OUTER_FINALIST_COUNT": 0,
        "PRIMARY_MODEL": "NONE", "PRIMARY_FEATURE_SET": "NONE", "PRIMARY_POLICY": "NONE",
        "PRIMARY_RAW_PRIOR_ETA": "NONE", "PRIMARY_ENTRY_PROTECTION": "NONE",
        "PRIMARY_FIXED_BEFORE_2025_READ": "FALSE", "RAW_SHARPE": math.nan,
        "BEST_SIMPLE_NAME": "NONE", "BEST_SIMPLE_SHARPE": math.nan, "PRIMARY_SHARPE": math.nan,
        "2023_DELTA_SHARPE_VS_RAW": math.nan, "2023_DELTA_SHARPE_VS_BEST_SIMPLE": math.nan,
        "2024_DELTA_SHARPE_VS_RAW": math.nan, "2024_DELTA_SHARPE_VS_BEST_SIMPLE": math.nan,
        "POOLED_DELTA_SHARPE_VS_RAW": math.nan, "POSITIVE_HISTORICAL_OOS_FOLDS": 0,
        "PRIMARY_DELTA_CAGR_VS_RAW": math.nan, "PRIMARY_DELTA_MAXDD_VS_RAW": math.nan,
        "PRIMARY_DELTA_TURNOVER": math.nan, "PRIMARY_DELTA_COST": math.nan,
        "PRIMARY_WINNER_CAPTURE_DELTA": math.nan, "RAW_SCORE_CORRELATION": math.nan,
        "INCREMENTAL_RANK_IC": math.nan, "PARTIAL_RANK_IC": math.nan,
        "ORTHOGONALITY_STATUS": "NOT_RUN", "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE": math.nan,
        "EX_BEST1_VINTAGE": math.nan, "EX_BEST3_VINTAGES": math.nan, "EX_BEST5_VINTAGES": math.nan,
        "EX_BEST1_SECURITY": math.nan, "EX_BEST3_SECURITIES": math.nan, "EX_BEST_FF12": math.nan,
        "MULTIPLE_TESTING_STATUS": "NOT_APPLICABLE", "EFFECTIVE_TRIAL_COUNT": 0.0,
        "DEFLATED_SHARPE_STATUS": "NOT_APPLICABLE", "QUARTER_CLUSTER_BOOTSTRAP_STATUS": "NOT_APPLICABLE",
        "EVIDENCE_CLASS": "FIXED_HISTORICAL_OOS_NOT_PROSPECTIVE", "2025_STATUS": "NOT_READ",
        "PRIMARY_2025_DIAGNOSTIC": "NOT_APPLICABLE", "PRIMARY_CHANGED_AFTER_2025_READ": "FALSE",
        "FORWARD_ELIGIBLE": "FALSE", "FORWARD_ROLE": "NONE", "FINAL_FORWARD_MODEL_ID": "NONE",
        "FINAL_FORWARD_MODEL_HASH": "NONE", "PRIMARY_CLASSIFICATION": "NO_VERDICT_SEC_LINEAGE_FAILURE",
        "MAIN_NOVELTY_LESSON": (
            "The earlier earnings/fundamental task is a partial PIT prototype with zero numeric-fact coverage "
            "and no economic run; no completed accepted-time clean-label Top20 membership duplicate exists."
        ),
        "MAIN_FUNDAMENTAL_LESSON": "NOT_EVALUATED", "MAIN_ORTHOGONALITY_LESSON": "NOT_EVALUATED",
        "MAIN_WINNER_CAPTURE_LESSON": "NOT_EVALUATED", "MAIN_VINTAGE_RISK": "NOT_EVALUATED",
        "STRONGEST_SUPPORTING_EVIDENCE": "NOT_APPLICABLE", "MOST_DAMAGING_EVIDENCE": "NOT_APPLICABLE",
        "TASK_LOCAL_ANTI_BLOAT_STATUS": "PASS", "PREEXISTING_ACL_EXCEPTION_COUNT": 2,
        "FINAL_ARTIFACT_COUNT": 0, "HASH_MANIFEST_STATUS": "PENDING",
    }

    feature_ledger, trial_ledger, outer_metrics, vintage = _empty_frames()
    robustness = pd.DataFrame([{"record_type": "NOT_RUN", "status": "NOT_APPLICABLE"}])
    freeze: dict[str, Any] = {
        "research_id": TASK, "outer_finalists_frozen": False, "outer_outcome_read_count_at_freeze": 0,
        "primary_fixed_before_2025_read": False, "primary_id": None,
    }
    cache_manifest_path: Path | None = None

    if novelty_facts["exact_duplicate_count"] > 0:
        summary.update({
            "RESEARCH_STATUS": "STOP_DUPLICATE_RESEARCH", "ECONOMIC_VERDICT": "DUPLICATE_RESEARCH_STOP",
            "PRIMARY_CLASSIFICATION": "DUPLICATE_RESEARCH_STOP",
            "MOST_DAMAGING_EVIDENCE": "An exact accession/accepted-time clean-label Top20 membership research duplicate was found.",
        })
        # The stop artifact itself is frozen before any data fetch or fit.
        duplicate_contract = concept_contract()
        freeze_json(OUT / "sec_concept_contract.json", duplicate_contract)
        freeze_json(OUT / "preregistration.json", preregistration(duplicate_contract["contract_hash"], False))
        write_final_artifacts(summary, feature_ledger, trial_ledger, outer_metrics, vintage, robustness, freeze, None)
        print(final_block(summary), flush=True)
        return 0

    try:
        snapshot = freeze_bulk_snapshot()
        inputs = prepare_a2_inputs()
        raw = inputs["raw"]
        summary.update({
            "AUTHORITATIVE_RAW_REPLAY_STATUS": "PASS_EXACT_AUTHORITATIVE_TOLERANCE",
            "AUTHORITATIVE_RAW_SESSIONS": len(inputs["portfolio"]),
            "AUTHORITATIVE_RAW_CAGR": raw["cagr"], "AUTHORITATIVE_RAW_SHARPE": raw["sharpe"],
            "AUTHORITATIVE_RAW_MAXDD": raw["max_drawdown"], "RAW_SHARPE": raw["sharpe"],
        })
        catboost_available = importlib.util.find_spec("catboost") is not None
        concept, prereg, concept_sha, prereg_sha = restore_frozen_research_contract()
        require(concept == concept_contract(), "FROZEN_CONTRACT_MISMATCH", "CONCEPT_CONTRACT_REGENERATED_DIFFERENTLY")
        generated_prereg = preregistration(concept["contract_hash"], catboost_available)
        require(prereg == generated_prereg, "PREREG_SEARCH_SPACE_EXPANSION", "CURRENT_CODE_DIFFERS_FROM_FROZEN_PREREG")
        summary["CONCEPT_CONTRACT_STATUS"] = f"PASS_FROZEN:{concept_sha}"
        specs = candidate_model_specs(catboost_available)
        require([asdict(spec) for spec in specs] == prereg["models"], "PREREG_SEARCH_SPACE_EXPANSION", "MODEL_SPECS")
        summary["UNIQUE_MODEL_SPECS"] = len(specs)

        sessions = trading_sessions(inputs["action"])
        universe = load_universe()
        summary["TOTAL_SECURITIES"] = int(universe.security_id.nunique())
        mapping, mapping_sha256 = load_frozen_cik_mapping()
        security_mapping = mapping.sort_values("mapping_confidence").drop_duplicates("security_id", keep="first")
        summary["CIK_RESOLVED_COUNT"] = int(security_mapping.cik.notna().sum())
        summary["CIK_UNRESOLVED_COUNT"] = int(security_mapping.cik.isna().sum())
        resolved_ciks = sorted(mapping.cik.dropna().astype(int).unique())
        facts_all, submissions, bulk_audit, zip_index, derived = load_bulk_sec_data(
            snapshot, mapping_sha256, resolved_ciks,
        )
        domestic_ciks = set(submissions.cik.dropna().astype(int).unique())
        summary["DOMESTIC_FILER_COUNT"] = int(sum(cik in domestic_ciks for cik in resolved_ciks))
        summary["FOREIGN_FILER_COUNT"] = int(sum(cik not in domestic_ciks for cik in resolved_ciks))
        accepted_accessions = set(submissions.adsh.astype(str))
        facts = facts_all.loc[facts_all.accession.astype(str).isin(accepted_accessions)].copy()
        accession_linkage_count = int(facts.accession.nunique())
        accepted_datetime_linkage_count = int(
            submissions.loc[submissions.adsh.astype(str).isin(set(facts.accession.astype(str))) & submissions.accepted_datetime.notna(), "adsh"].nunique()
        )
        state_cache_key = stable_hash({
            "snapshot_contract_hash": snapshot["snapshot_contract_hash"],
            "mapping_sha256": mapping_sha256,
            "concept_contract_sha256": concept_sha,
            "bulk_parse_manifest_sha256": sha256_file(Path(derived["manifest_path"])),
            "numeric_fact_rows": len(facts),
            "submission_rows": len(submissions),
            "session_count": len(sessions),
            "session_min": min(sessions) if len(sessions) else None,
            "session_max": max(sessions) if len(sessions) else None,
            "cache_version": FEATURE_STATE_CACHE_VERSION,
        })
        states, lineage_facts = load_or_build_feature_states(
            facts, submissions, sessions, state_cache_key,
        )
        feature_ledger = build_feature_ledger(states, mapping)
        summary.update({
            "PIT_EFFECTIVE_DATE_STATUS": lineage_facts.get("pit_effective_date_status", "PASS_NO_USABLE_STATES"),
            "RESTATEMENT_GUARD_STATUS": lineage_facts.get("restatement_guard_status", "PASS_NO_USABLE_STATES"),
            "UNIT_SCALE_STATUS": lineage_facts.get("unit_scale_status", "PASS_NO_USABLE_STATES"),
            "TOTAL_FILINGS": int(len(submissions)),
            "TOTAL_10Q": int(submissions.form.astype(str).str.startswith("10-Q").sum()) if not submissions.empty else 0,
            "TOTAL_10K": int(submissions.form.astype(str).str.startswith("10-K").sum()) if not submissions.empty else 0,
            "TOTAL_AMENDMENTS": int(submissions.form.astype(str).str.endswith("/A").sum()) if not submissions.empty else 0,
            "MAX_ACCEPTED_DATETIME_USED": states.accepted_datetime.max().isoformat() if not states.empty else "NOT_APPLICABLE",
        })
        cache_manifest_path = write_bulk_cache_manifest(
            snapshot, derived, len(resolved_ciks), facts, submissions, states, zip_index,
        )
        summary["SEC_REQUEST_COUNT"] = 0
        summary["SEC_CACHE_HIT_COUNT"] = int(len(zip_index) + int(derived["cache_hit_count"]))

        mapped_pool = attach_mapping_to_pool(inputs["pool"], mapping)
        coverage_panel = feature_only_panel(mapped_pool, states, inputs["taxonomy"], inputs["matrix_features"])
        coverage_facts, coverage_rows = coverage_metrics(coverage_panel)
        summary.update({
            "FEATURE_COVERAGE_MEDIAN": coverage_facts["feature_coverage_median"],
            "RAW_TOP40_COVERAGE_MEDIAN": coverage_facts["raw_top40_coverage_median"],
            "DECISION_DATES_PASSING_COVERAGE_GATE": coverage_facts["decision_dates_passing_coverage_gate"],
        })
        mapping_records = mapping.copy()
        mapping_records["record_type"] = "CIK_MAPPING"
        mapping_records["status"] = np.where(mapping_records.cik.notna(), "RESOLVED", "UNRESOLVED_KEEP_ELIGIBLE")
        gate_records = pd.DataFrame([
            {"record_type": "SEC_LINEAGE_GATE", "gate": key, "value": json.dumps(item, default=str)}
            for key, item in {**lineage_facts, **coverage_facts, "dilution_feature_status": "DISABLED_SCALE_UNSAFE"}.items()
        ])
        zip_records = zip_index.copy(); zip_records["record_type"] = "RELEVANT_ZIP_INDEX"
        trial_parts: list[pd.DataFrame] = [mapping_records, bulk_audit, zip_records, coverage_rows, gate_records]

        tickers = set(mapped_pool.ticker.astype(str)) | {"QQQ", "MSFT", "NVDA", "AVGO", "AMC", "AEVA", "SSG", "DBVT", "WOLF"}
        # Sealed arithmetic/lineage QA for every period that can enter the
        # fixed historical OOS. These labels are not passed to inner selection.
        _, qa_labels, qa_gate, qa_audit = make_clean_labels(
            inputs["policy"], inputs["action"], tickers, list(range(2018, 2025)),
            "PREFIT_SEALED_LABEL_QA_2018_2024",
        )
        arithmetic_mismatches = int(qa_gate["label_arithmetic_mismatch_count"] + qa_gate["abs60_arithmetic_mismatch_count"])
        summary["LABEL_ARITHMETIC_MISMATCH_COUNT"] = arithmetic_mismatches
        require(arithmetic_mismatches == 0, "LABEL_LINEAGE_FAILURE", qa_gate)
        trial_parts.append(qa_audit.assign(record_type="LABEL_QA"))
        trial_parts.append(pd.DataFrame([{"record_type": "LABEL_GATE", **qa_gate}]))
        del qa_labels

        relevant_cik_with_facts = int(facts.cik.nunique()) if not facts.empty else 0
        prefit_gate = {
            "COMPANYFACTS_PATH": str(COMPANYFACTS_BULK),
            "COMPANYFACTS_SHA256": snapshot["payloads"]["companyfacts"]["sha256"],
            "COMPANYFACTS_ENTRY_COUNT": snapshot["payloads"]["companyfacts"]["entries"],
            "COMPANYFACTS_HASH_MATCH": "TRUE",
            "SUBMISSIONS_PATH": str(SUBMISSIONS_BULK),
            "SUBMISSIONS_SHA256": snapshot["payloads"]["submissions"]["sha256"],
            "SUBMISSIONS_ENTRY_COUNT": snapshot["payloads"]["submissions"]["entries"],
            "SUBMISSIONS_HASH_MATCH": "TRUE",
            "SEC_NUMERIC_FACT_COUNT": int(len(facts)),
            "RELEVANT_RESOLVED_CIK_COUNT": int(len(resolved_ciks)),
            "RELEVANT_CIK_WITH_FACTS_COUNT": relevant_cik_with_facts,
            "ACCESSION_LINKAGE_COUNT": accession_linkage_count,
            "ACCEPTED_DATETIME_LINKAGE_COUNT": accepted_datetime_linkage_count,
            "PIT_EFFECTIVE_DATE_STATUS": summary["PIT_EFFECTIVE_DATE_STATUS"],
            "RESTATEMENT_GUARD_STATUS": summary["RESTATEMENT_GUARD_STATUS"],
            "UNIT_SCALE_STATUS": summary["UNIT_SCALE_STATUS"],
            "CONCEPT_CONTRACT_STATUS": summary["CONCEPT_CONTRACT_STATUS"],
            "RAW_TOP40_COVERAGE_MEDIAN": summary["RAW_TOP40_COVERAGE_MEDIAN"],
            "DECISION_DATES_PASSING_COVERAGE_GATE": summary["DECISION_DATES_PASSING_COVERAGE_GATE"],
            "FEATURE_COVERAGE_MEDIAN": summary["FEATURE_COVERAGE_MEDIAN"],
            "LABEL_PRICE_LINEAGE": summary["LABEL_PRICE_LINEAGE"],
            "LABEL_ARITHMETIC_MISMATCH_COUNT": summary["LABEL_ARITHMETIC_MISMATCH_COUNT"],
            "2026_OUTCOME_USED": summary["2026_OUTCOME_USED"],
            "2026_LEAKAGE_COUNT": summary["2026_LEAKAGE_COUNT"],
        }
        model_fit_allowed = bool(
            coverage_facts["coverage_gate"] == "PASS" and arithmetic_mismatches == 0 and
            str(summary["PIT_EFFECTIVE_DATE_STATUS"]).startswith("PASS") and
            str(summary["RESTATEMENT_GUARD_STATUS"]).startswith("PASS") and
            str(summary["UNIT_SCALE_STATUS"]).startswith("PASS")
        )
        prefit_gate["MODEL_FIT_ALLOWED"] = str(model_fit_allowed).upper()
        trial_parts.append(pd.DataFrame([{"record_type": "SEC_BULK_RESUME_PREFIT_GATE", **prefit_gate}]))
        print(sec_bulk_prefit_block(prefit_gate), flush=True)

        if not model_fit_allowed:
            summary.update({
                "RESEARCH_STATUS": "PASS_DATA_BUILD_COMPLETE_COVERAGE_INSUFFICIENT",
                "ECONOMIC_VERDICT": "DATA_COVERAGE_INSUFFICIENT",
                "PRIMARY_CLASSIFICATION": "DATA_COVERAGE_INSUFFICIENT",
                "PRIMARY_FIXED_BEFORE_2025_READ": "TRUE", "2025_STATUS": "NOT_READ_COVERAGE_GATE_FAIL",
                "MAIN_FUNDAMENTAL_LESSON": "Strict-PIT SEC coverage did not clear the frozen Raw Top40 gate; complex training was not forced.",
                "MAIN_ORTHOGONALITY_LESSON": "Source orthogonality exists by construction, but economic orthogonality was not testable at required coverage.",
                "MAIN_WINNER_CAPTURE_LESSON": "NOT_EVALUATED_COVERAGE_GATE_FAIL",
                "MAIN_VINTAGE_RISK": "NOT_EVALUATED_COVERAGE_GATE_FAIL",
                "MOST_DAMAGING_EVIDENCE": f"Raw Top40 median coverage={coverage_facts['raw_top40_coverage_median']:.6f}; date-pass fraction={coverage_facts['decision_dates_passing_coverage_gate']:.6f}.",
                "STRONGEST_SUPPORTING_EVIDENCE": "Raw identity and clean-label gates passed before any fundamental candidate model fit.",
            })
            freeze.update({
                "outer_finalists_frozen": True, "outer_finalist_ids": [], "outer_finalist_count": 0,
                "primary_fixed_before_2025_read": True, "primary_id": None,
                "preregistration_sha256": prereg_sha, "concept_contract_sha256": concept_sha,
            })
            freeze["outer_freeze_hash"] = stable_hash(freeze)
            trial_ledger = pd.concat(trial_parts, ignore_index=True, sort=False)
            summary["TOTAL_MODEL_FITS"] = inputs["raw_extension_fit_count"]
            unresolved_impact = targeted_unresolved_impact(coverage_panel, mapping, facts, submissions, states)
            write_final_artifacts(
                summary, feature_ledger, trial_ledger, outer_metrics, vintage, robustness,
                freeze, cache_manifest_path, unresolved_impact,
            )
            print(final_block(summary), flush=True)
            return 0

        # Physical discovery firewall: only pre-2023 economic labels enter the
        # adaptive search below.
        prices_inner, labels_inner, inner_gate, inner_audit = make_clean_labels(
            inputs["policy"], inputs["action"], tickers, list(range(2018, 2023)),
            "DISCOVERY_LABELS_2018_2022",
        )
        discovery_pool = mapped_pool.loc[mapped_pool.signal_date.lt(pd.Timestamp("2023-01-01"))]
        discovery_panel = build_research_panel(discovery_pool, states, inputs["taxonomy"], inputs["matrix_features"], labels_inner)
        discovery_panel = discovery_panel.loc[
            discovery_panel.signal_date.ge(pd.Timestamp("2021-01-01")) & discovery_panel.label_end_date.le(pd.Timestamp("2022-12-31"))
        ].copy()
        require(not discovery_panel.empty, "DISCOVERY_PANEL_EMPTY")
        recomputed = discovery_panel.loc[discovery_panel.a2_rank.le(40), "y_abs20"] - discovery_panel.loc[discovery_panel.a2_rank.le(40)].groupby(["signal_date", "ff12"]).y_abs20.transform("mean")
        t1_mismatch = int(((recomputed - discovery_panel.loc[discovery_panel.a2_rank.le(40), "y_ff12res20"]).abs() > TOL).sum())
        require(t1_mismatch == 0, "LABEL_LINEAGE_FAILURE", "T1_RECONCILIATION")
        trial_parts.extend([inner_audit.assign(record_type="LABEL_QA"), pd.DataFrame([{"record_type": "LABEL_GATE", **inner_gate, "t1_mismatch_count": t1_mismatch}])])
        orthogonality = orthogonality_metrics(discovery_panel)
        summary.update({
            "RAW_SCORE_CORRELATION": orthogonality["raw_score_correlation"],
            "INCREMENTAL_RANK_IC": orthogonality["incremental_rank_ic"],
            "PARTIAL_RANK_IC": orthogonality["partial_rank_ic"],
            "ORTHOGONALITY_STATUS": orthogonality["orthogonality_status"],
        })
        counter = FitCounter(initial=inputs["raw_extension_fit_count"])
        inner_ledger, policy_specs, finalists, _ = run_inner_search(
            inputs["policy"], inputs["e5"], inputs["action"], discovery_panel,
            prices_inner, inputs["taxonomy"], specs, counter,
        )
        summary["TOTAL_POLICY_SPECS"] = len(policy_specs)
        summary["OUTER_FINALIST_COUNT"] = len(finalists)
        trial_parts.append(inner_ledger)
        policy_by_id = {spec.policy_id: spec for spec in policy_specs}
        spec_by_id = {spec.model_id: spec for spec in specs}
        freeze.update({
            "outer_finalists_frozen": True, "outer_outcome_read_count_at_freeze": 0,
            "outer_finalist_ids": finalists, "outer_finalist_count": len(finalists),
            "preregistration_sha256": prereg_sha, "concept_contract_sha256": concept_sha,
            "specs": [
                {"policy": asdict(policy_by_id[policy_id]), "model": asdict(spec_by_id[policy_by_id[policy_id].model_id])}
                for policy_id in finalists
            ],
        })
        freeze["outer_freeze_hash"] = stable_hash({key: item for key, item in freeze.items() if key != "outer_freeze_hash"})
        freeze_json(OUT / "finalist_freeze.json", freeze, "outer_freeze_hash")

        prices_outer, labels_outer, outer_label_gate, outer_label_audit = make_clean_labels(
            inputs["policy"], inputs["action"], tickers, list(range(2018, 2025)),
            "FROZEN_HISTORICAL_OOS_LABELS_2018_2024",
        )
        outer_pool = mapped_pool.loc[mapped_pool.signal_date.lt(pd.Timestamp("2025-01-01"))]
        outer_panel = build_research_panel(outer_pool, states, inputs["taxonomy"], inputs["matrix_features"], labels_outer)
        outer_panel = outer_panel.loc[outer_panel.signal_date.ge(pd.Timestamp("2021-01-01"))].copy()
        outer_metrics, primary_id, classification, outer_paths, outer_targets, prediction_frame = run_outer(
            inputs["policy"], inputs["e5"], inputs["action"], outer_panel, prices_outer,
            inputs["taxonomy"], specs, policy_specs, finalists, counter,
        )
        if classification == "NO_ROBUST_INCREMENTAL_ALPHA" and np.isfinite(orthogonality["partial_rank_ic"]) and orthogonality["partial_rank_ic"] > 0:
            classification = "FUNDAMENTAL_SIGNAL_PRESENT_NOT_ECONOMIC"
        freeze["primary_id"] = primary_id
        freeze["primary_fixed_before_2025_read"] = True
        freeze["primary_2025_outcome_read_count_at_freeze"] = 0
        freeze["primary_freeze_hash"] = stable_hash({
            "outer_freeze_hash": freeze["outer_freeze_hash"], "primary_id": primary_id,
            "outer_evidence_hash": stable_hash(outer_metrics.to_dict("records")),
        })
        atomic_json(OUT / "finalist_freeze.json", freeze)
        frozen_bytes = (OUT / "finalist_freeze.json").read_bytes()
        summary["PRIMARY_FIXED_BEFORE_2025_READ"] = "TRUE"

        # Pooled baseline and Primary accounting.
        pooled_paths: dict[str, dict[str, float]] = {}
        simple_names = ["C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT", "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT"]
        for name in ["C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL", *simple_names, *([primary_id] if primary_id and primary_id not in simple_names else [])]:
            returns = pd.concat([outer_paths[(year, name)].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
            pooled_paths[name] = return_metrics(returns)
        best_simple_name = max(simple_names, key=lambda name: pooled_paths[name]["sharpe"])
        best_simple_sharpe = pooled_paths[best_simple_name]["sharpe"]
        summary["BEST_SIMPLE_NAME"] = best_simple_name
        summary["BEST_SIMPLE_SHARPE"] = best_simple_sharpe
        summary["TOTAL_MODEL_FITS"] = counter.total
        summary["PRIMARY_CLASSIFICATION"] = classification
        summary["ECONOMIC_VERDICT"] = classification

        robust_vintage, robust_metrics, robust_facts = contribution_and_robustness(primary_id, outer_paths, outer_panel, finalists)
        vintage = robust_vintage
        robustness = robust_metrics
        summary.update({
            "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE": robust_facts["top3_vintage_positive_contribution_share"],
            "EX_BEST1_VINTAGE": robust_facts["ex_best1_vintage"], "EX_BEST3_VINTAGES": robust_facts["ex_best3_vintages"],
            "EX_BEST5_VINTAGES": robust_facts["ex_best5_vintages"], "EX_BEST1_SECURITY": robust_facts["ex_best1_security"],
            "EX_BEST3_SECURITIES": robust_facts["ex_best3_securities"], "EX_BEST_FF12": robust_facts["ex_best_ff12"],
            "MULTIPLE_TESTING_STATUS": robust_facts["multiple_testing_status"],
            "EFFECTIVE_TRIAL_COUNT": robust_facts["effective_trial_count"],
            "DEFLATED_SHARPE_STATUS": robust_facts["deflated_sharpe_status"],
            "QUARTER_CLUSTER_BOOTSTRAP_STATUS": robust_facts["quarter_cluster_bootstrap_status"],
        })
        if primary_id:
            primary_policy = policy_by_id.get(primary_id)
            primary_model = spec_by_id.get(primary_policy.model_id) if primary_policy else None
            summary.update({
                "PRIMARY_MODEL": primary_model.family if primary_model else "SIMPLE_FIXED_SIGNS",
                "PRIMARY_FEATURE_SET": primary_model.feature_family if primary_model else "SIMPLE_FIXED_F0_TO_F3",
                "PRIMARY_POLICY": primary_id,
                "PRIMARY_RAW_PRIOR_ETA": primary_policy.eta if primary_policy else 0.25,
                "PRIMARY_ENTRY_PROTECTION": primary_policy.entry_protection if primary_policy else "EP0_NO_HARD_PROTECTION",
            })
            primary_returns = pd.concat([outer_paths[(year, primary_id)].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
            raw_returns = pd.concat([outer_paths[(year, "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
            primary_pooled = return_metrics(primary_returns)
            raw_pooled = return_metrics(raw_returns)
            summary.update({
                "PRIMARY_SHARPE": primary_pooled["sharpe"],
                "POOLED_DELTA_SHARPE_VS_RAW": primary_pooled["sharpe"] - raw_pooled["sharpe"],
                "PRIMARY_DELTA_CAGR_VS_RAW": primary_pooled["cagr"] - raw_pooled["cagr"],
                "PRIMARY_DELTA_MAXDD_VS_RAW": primary_pooled["max_drawdown"] - raw_pooled["max_drawdown"],
            })
            deltas_raw, deltas_simple, turnover_delta, cost_delta, winner_delta = [], [], [], [], []
            for year in (2023, 2024):
                primary_row = outer_metrics.loc[outer_metrics.year.eq(year) & outer_metrics.policy_id.eq(primary_id)].iloc[0]
                raw_row = outer_metrics.loc[outer_metrics.year.eq(year) & outer_metrics.policy_id.eq("C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")].iloc[0]
                fold_best = outer_metrics.loc[outer_metrics.year.eq(year) & outer_metrics.policy_id.isin(simple_names)].sort_values("sharpe", ascending=False).iloc[0]
                delta_raw = float(primary_row.sharpe - raw_row.sharpe)
                delta_simple = float(primary_row.sharpe - fold_best.sharpe)
                summary[f"{year}_DELTA_SHARPE_VS_RAW"] = delta_raw
                summary[f"{year}_DELTA_SHARPE_VS_BEST_SIMPLE"] = delta_simple
                deltas_raw.append(delta_raw); deltas_simple.append(delta_simple)
                turnover_delta.append(float(primary_row.turnover - raw_row.turnover))
                cost_delta.append(float(primary_row.cost - raw_row.cost))
                winner_delta.append(float(primary_row.winner_capture - raw_row.winner_capture))
            summary["POSITIVE_HISTORICAL_OOS_FOLDS"] = int(sum(item > 0 for item in deltas_raw))
            summary["PRIMARY_DELTA_TURNOVER"] = float(sum(turnover_delta))
            summary["PRIMARY_DELTA_COST"] = float(sum(cost_delta))
            summary["PRIMARY_WINNER_CAPTURE_DELTA"] = float(np.mean(winner_delta))

        trial_parts.extend([outer_label_audit.assign(record_type="LABEL_QA"), pd.DataFrame([{"record_type": "LABEL_GATE", **outer_label_gate}])])
        if not prediction_frame.empty:
            prediction_frame["record_type"] = "OUTER_PREDICTION_DIAGNOSTIC"
            trial_parts.append(prediction_frame)

        # Read 2025 exactly once after the durable Primary freeze.
        prices_2025, labels_2025, gate_2025, audit_2025 = make_clean_labels(
            inputs["policy"], inputs["action"], tickers, list(range(2018, 2026)),
            "POST_PRIMARY_READ_ONCE_2025",
        )
        panel_2025 = build_research_panel(mapped_pool, states, inputs["taxonomy"], inputs["matrix_features"], labels_2025)
        panel_2025 = panel_2025.loc[panel_2025.signal_date.ge(pd.Timestamp("2021-01-01"))].copy()
        diagnostics_2025, diagnostic_text, catastrophic, _, _ = evaluate_2025(
            primary_id, inputs["policy"], inputs["e5"], inputs["action"], panel_2025,
            prices_2025, inputs["taxonomy"], specs, policy_specs, best_simple_name, counter,
        )
        require((OUT / "finalist_freeze.json").read_bytes() == frozen_bytes, "PRIMARY_CHANGED_AFTER_2025_READ")
        summary["2025_STATUS"] = "EXPOSED_READ_ONCE_DIAGNOSTIC"
        summary["PRIMARY_2025_DIAGNOSTIC"] = diagnostic_text
        summary["PRIMARY_CHANGED_AFTER_2025_READ"] = "FALSE"
        trial_parts.extend([audit_2025.assign(record_type="LABEL_QA"), pd.DataFrame([{"record_type": "LABEL_GATE", **gate_2025}])])
        outer_metrics = pd.concat([outer_metrics, diagnostics_2025], ignore_index=True, sort=False)

        forward_eligible = bool(primary_id) and classification in {
            "PIT_FUNDAMENTAL_INCREMENTAL_ALPHA_SUPPORTED", "SIMPLE_FUNDAMENTAL_TILT_SUFFICIENT",
        } and robust_facts["multiple_testing_status"] == "PASS" and not robust_facts["vintage_concentrated"] and not catastrophic
        if primary_id and robust_facts["vintage_concentrated"]:
            classification = "VINTAGE_CONCENTRATED_NO_PROMOTION"
            forward_eligible = False
        elif primary_id and classification == "PIT_FUNDAMENTAL_INCREMENTAL_ALPHA_SUPPORTED" and robust_facts["multiple_testing_status"] != "PASS":
            classification = "OVERFIT_RISK_TOO_HIGH"
            forward_eligible = False
        elif primary_id and catastrophic:
            classification = "PROMISING_BUT_HISTORICAL_OOS_MIXED"
            forward_eligible = False
        summary["PRIMARY_CLASSIFICATION"] = classification
        summary["ECONOMIC_VERDICT"] = classification
        final_model_id = final_model_hash = "NONE"
        if forward_eligible and primary_id:
            bundle_path = OUT / "forward_model_bundle.joblib"
            if primary_id in policy_by_id:
                policy_spec = policy_by_id[primary_id]
                model_spec = spec_by_id[policy_spec.model_id]
                legal = panel_2025.loc[panel_2025.label_end_date.le(LABEL_CUTOFF)]
                final_bundle = fit_model(model_spec, legal, RANDOM_SEEDS[0], counter)
                joblib.dump({
                    "research_id": TASK, "model": final_bundle, "policy": policy_spec,
                    "concept_contract_hash": concept["contract_hash"], "preregistration_hash": prereg["contract_hash"],
                    "automatic_promotion": False, "forward_role": "NEW_PROSPECTIVE_CHALLENGER_ONLY",
                }, bundle_path, compress=3)
                summary["FINAL_TRAIN_MAX_LABEL_END_DATE"] = str(final_bundle.max_label_end_date.date())
            else:
                joblib.dump({
                    "research_id": TASK, "simple_policy": primary_id, "eta": 0.25,
                    "automatic_promotion": False, "forward_role": "NEW_PROSPECTIVE_CHALLENGER_ONLY",
                }, bundle_path, compress=3)
                legal_dates = panel_2025.loc[panel_2025.label_end_date.le(LABEL_CUTOFF), "label_end_date"]
                summary["FINAL_TRAIN_MAX_LABEL_END_DATE"] = str(legal_dates.max().date())
            final_model_id = f"SEC_FUNDAMENTAL_{stable_hash({'primary': primary_id, 'prereg': prereg['contract_hash']})[:16]}"
            final_model_hash = sha256_file(bundle_path)
        summary.update({
            "FORWARD_ELIGIBLE": str(forward_eligible).upper(),
            "FORWARD_ROLE": "NEW_PROSPECTIVE_CHALLENGER_ONLY" if forward_eligible else "NONE",
            "FINAL_FORWARD_MODEL_ID": final_model_id, "FINAL_FORWARD_MODEL_HASH": final_model_hash,
            "TOTAL_MODEL_FITS": counter.total,
            "RESEARCH_STATUS": "PASS_RESEARCH_COMPLETE" if primary_id else "PASS_RESEARCH_COMPLETE_NEGATIVE_RESULT",
            "MAIN_FUNDAMENTAL_LESSON": (
                "Strict-PIT fundamentals cleared all economic gates." if forward_eligible else
                "No frozen fundamental membership policy cleared every historical OOS, robustness, vintage and 2025 gate."
            ),
            "MAIN_ORTHOGONALITY_LESSON": f"Raw correlation={orthogonality['raw_score_correlation']:.6f}; partial IC={orthogonality['partial_rank_ic']:.6f}.",
            "MAIN_WINNER_CAPTURE_LESSON": f"Primary winner-capture delta={summary['PRIMARY_WINNER_CAPTURE_DELTA']}.",
            "MAIN_VINTAGE_RISK": f"Top3 positive contribution share={robust_facts['top3_vintage_positive_contribution_share']}.",
            "STRONGEST_SUPPORTING_EVIDENCE": f"Partial rank IC={orthogonality['partial_rank_ic']:.6f}; {len(finalists)} frozen finalists.",
            "MOST_DAMAGING_EVIDENCE": (
                f"2023/2024 deltas vs Raw={summary['2023_DELTA_SHARPE_VS_RAW']}/{summary['2024_DELTA_SHARPE_VS_RAW']}; multiple testing={robust_facts['multiple_testing_status']}."
            ),
        })
        trial_ledger = pd.concat(trial_parts, ignore_index=True, sort=False)
        write_final_artifacts(summary, feature_ledger, trial_ledger, outer_metrics, vintage, robustness, freeze, cache_manifest_path)
    except GateFailure as exc:
        message = str(exc)
        hard_tokens = (
            "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "SEC_FACT_LINEAGE_FAILURE", "ACCEPTED_DATETIME_PIT_FAILURE",
            "RESTATEMENT_BACKFILL", "UNIT_SCALE_MIX", "LABEL_LINEAGE_FAILURE", "2026_OUTCOME_ACCESS",
            "OUTER_DRIVEN_REDESIGN", "NAV/COST/RETURN_RECONCILIATION_FAILURE", "ARTIFACT_HASH_FAILURE",
            "PREREG_SEARCH_SPACE_EXPANSION", "FROZEN_CONTRACT_MISMATCH", "FROZEN_PROVENANCE",
            "SEC_BULK_BYTE_LENGTH_MISMATCH", "SEC_BULK_ENTRY_COUNT_MISMATCH", "SEC_BULK_SHA256_MISMATCH",
            "SEC_BULK_SNAPSHOT_MUTATION",
        )
        hard = any(token in message for token in hard_tokens)
        summary.update({
            "RESEARCH_STATUS": "FAIL_CLOSED_SEC_LINEAGE_OR_RESEARCH_GATE" if hard else "PASS_DATA_BUILD_INCOMPLETE_COVERAGE_INSUFFICIENT",
            "ECONOMIC_VERDICT": "NO_VERDICT_SEC_LINEAGE_FAILURE" if hard else "DATA_COVERAGE_INSUFFICIENT",
            "PRIMARY_CLASSIFICATION": "NO_VERDICT_SEC_LINEAGE_FAILURE" if hard else "DATA_COVERAGE_INSUFFICIENT",
            "MOST_DAMAGING_EVIDENCE": message,
            "MAIN_FUNDAMENTAL_LESSON": "No economic model verdict was produced after the prefit data/PIT gate stopped progression.",
            "PRIMARY_FIXED_BEFORE_2025_READ": "TRUE", "2025_STATUS": "NOT_READ_PREFIT_GATE",
        })
        if "cache" in locals():
            summary["SEC_REQUEST_COUNT"] = cache.request_count
            summary["SEC_CACHE_HIT_COUNT"] = cache.cache_hit_count
            try:
                cache.write_manifest({"terminal_failure": message})
                cache_manifest_path = cache.manifest_path
            except Exception:
                pass
        if "mapping" in locals():
            mapping_failure = mapping.copy(); mapping_failure["record_type"] = "CIK_MAPPING"
            trial_ledger = pd.concat([trial_ledger, mapping_failure], ignore_index=True, sort=False)
        if "feature_ledger" not in locals() or not isinstance(feature_ledger, pd.DataFrame):
            feature_ledger = _empty_frames()[0]
        freeze.update({"outer_finalists_frozen": True, "outer_finalist_ids": [], "outer_finalist_count": 0, "primary_fixed_before_2025_read": True, "primary_id": None, "failure": message})
        freeze["outer_freeze_hash"] = stable_hash(freeze)
        # Ensure the two frozen design artifacts exist even when official SEC
        # connectivity/data fails after Raw identity.
        if not (OUT / "sec_concept_contract.json").is_file():
            contract = concept_contract(); freeze_json(OUT / "sec_concept_contract.json", contract)
            freeze_json(OUT / "preregistration.json", preregistration(contract["contract_hash"], False))
        write_final_artifacts(summary, feature_ledger, trial_ledger, outer_metrics, vintage, robustness, freeze, cache_manifest_path)

    summary["ELAPSED_SECONDS"] = time.time() - started
    print(final_block(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
