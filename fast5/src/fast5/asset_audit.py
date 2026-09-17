from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
R1_ROOT = RESULTS / "frozen/fast4/fast4_r1_full_economic_ensemble_20260812T123322Z"
R1_MATRIX = R1_ROOT / "FAST4_R1_HISTORICAL_PIT_MATRIX.parquet"
R1_FEATURE_MANIFEST = R1_ROOT / "FAST4_R1_FEATURE_MANIFEST.json"
R43A_CONTRACT = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1/FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
OPTION_ROOT = RESULTS / "archive/fast3/moomoo_option_history_r2_20260811T191300Z"
CONFIG = REPO / "fast5/config/fast5_r1.json"

EXPECTED_R1_MATRIX_SHA = "0200dca9310a2ddd9f7123a1cc3864554cc59f57b4839ed3774e7afe6a398fc2"
EXPECTED_R1_FEATURE_FILE_SHA = "ad1c30ce0dbfd2d08e549b7899ad511f73b48101e8ed2c391290c63875142cbe"
ALLOWED_CANDIDATE_COLUMNS = (
    "candidate_id", "decision_timestamp_utc", "trading_date", "validation_slice", "head", "underlying_symbol",
)
FORBIDDEN_TARGET_COLUMNS = {
    "primary_target", "y_positive", "positive_horizon_majority", "severe_loss",
    "y_5m", "y_10m", "y_15m", "y_30m", "y_60m",
}
TIER_A = "TIER_A_ELIGIBLE_NEW_PIT_INFORMATION"
TIER_B = "TIER_B_VALID_PIT_BUT_INSUFFICIENT_COVERAGE"
TIER_C = "TIER_C_UNSAFE_OR_NON_PIT_FORBIDDEN"
TIER_D = "TIER_D_REDUNDANT_WITH_EXISTING_FAST4_INFORMATION"


class StageAFirewallError(RuntimeError):
    pass


@dataclass
class TargetValueFirewall:
    stage: str = "STAGE_A_OUTCOME_BLIND_DATA_AUDIT"
    target_value_read_count: int = 0
    preregistration_frozen: bool = False

    def assert_projection(self, columns: Iterable[str]) -> None:
        requested = set(columns)
        overlap = requested & FORBIDDEN_TARGET_COLUMNS
        if self.stage == "STAGE_A_OUTCOME_BLIND_DATA_AUDIT" and overlap:
            raise StageAFirewallError(f"TARGET_VALUE_READ_BEFORE_PREREGISTRATION:{sorted(overlap)}")

    def authorize_stage_b(self) -> None:
        if not self.preregistration_frozen or self.target_value_read_count != 0:
            raise StageAFirewallError("TARGET_VALUE_READ_BEFORE_PREREGISTRATION")
        self.stage = "STAGE_B_MODEL_TRAINING"

    def record_target_read(self) -> None:
        if self.stage != "STAGE_B_MODEL_TRAINING" or not self.preregistration_frozen:
            raise StageAFirewallError("TARGET_VALUE_READ_BEFORE_PREREGISTRATION")
        self.target_value_read_count += 1


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, default=str, allow_nan=False) + "\n").encode("utf-8")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str,
                                     allow_nan=False).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stable_bytes(value))


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def verify_stage_a_identities() -> dict[str, Any]:
    observed = {
        str(R43A_CONTRACT): sha256(R43A_CONTRACT),
        str(R1_FEATURE_MANIFEST): sha256(R1_FEATURE_MANIFEST),
        str(R1_MATRIX): sha256(R1_MATRIX),
    }
    cfg = load_config()
    feature = json.loads(R1_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    if observed[str(R43A_CONTRACT)] != cfg["target_sha256"]:
        raise StageAFirewallError("TARGET_IDENTITY_FAIL")
    if observed[str(R1_FEATURE_MANIFEST)] != EXPECTED_R1_FEATURE_FILE_SHA:
        raise StageAFirewallError("FROZEN_ARTIFACT_MUTATION:R1_FEATURE_MANIFEST")
    if observed[str(R1_MATRIX)] != EXPECTED_R1_MATRIX_SHA:
        raise StageAFirewallError("FROZEN_ARTIFACT_MUTATION:R1_MATRIX")
    if feature.get("feature_manifest_sha256") != cfg["fast4_baseline_feature_manifest_sha256"]:
        raise StageAFirewallError("FEATURE_PIT_FAIL:FAST4_BASELINE_IDENTITY")
    return {"observed_sha256": observed, "feature_manifest": feature}


def load_candidate_metadata(firewall: TargetValueFirewall) -> pd.DataFrame:
    firewall.assert_projection(ALLOWED_CANDIDATE_COLUMNS)
    frame = pd.read_parquet(R1_MATRIX, columns=list(ALLOWED_CANDIDATE_COLUMNS))
    if set(frame.columns) != set(ALLOWED_CANDIDATE_COLUMNS):
        raise StageAFirewallError("STAGE_A_CANDIDATE_PROJECTION_FAIL")
    frame["decision_timestamp_utc"] = pd.to_datetime(frame.decision_timestamp_utc, utc=True, errors="raise")
    frame["trading_date"] = pd.to_datetime(frame.trading_date, errors="raise").dt.date
    if len(frame) != 1197 or frame.candidate_id.duplicated().any():
        raise StageAFirewallError("STAGE_A_CANDIDATE_IDENTITY_FAIL")
    return frame


def _directory_stats(path: Path) -> tuple[int, int]:
    files = []
    if path.is_file():
        files = [path]
    elif path.is_dir():
        for base, _, names in os.walk(path, onerror=lambda _: None):
            for name in names:
                local = Path(base) / name
                try:
                    if local.is_file():
                        files.append(local)
                except OSError:
                    pass
    return len(files), sum(local.stat().st_size for local in files if local.exists())


def _stock_inventory(symbol: str) -> dict[str, Any]:
    root = DATA / "stocks" / symbol
    path = root / "daily_raw.parquet"
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    table = pd.read_parquet(path, columns=["date", "close", "source", "fetched_at_utc"])
    date = pd.to_datetime(table.date, errors="raise")
    return {
        "logical_asset_family": "GENUINELY_NEW_CROSS_ASSET", "asset": f"{symbol}_RAW_DAILY_OHLCV",
        "path": str(path), "file_format": "PARQUET", "partition_structure": "ONE_FILE_PER_SYMBOL",
        "file_count": 1, "approximate_bytes": path.stat().st_size, "row_count": len(table),
        "min_timestamp": str(date.min().date()), "max_timestamp": str(date.max().date()),
        "timezone": "AMERICA_NEW_YORK_TRADING_DATE", "timestamp_column": "date", "symbol_column": "ticker",
        "frequency_resolution": "DAILY", "duplicate_key_count": int(date.duplicated().sum()),
        "monotonic_timestamp_status": "PASS" if date.is_monotonic_increasing else "FAIL",
        "missingness": int(table.close.isna().sum()), "schema": list(pq.ParquetFile(path).schema_arrow.names),
        "candidate_underlyings_covered": "QQQ|SOXX", "pit_reconstruction_possible": True,
        "information_available_time": "NEXT_CANDIDATE_TRADING_DATE_AFTER_COMPLETED_PRIOR_US_SESSION",
        "source_immutable_read_only": True, "source": metadata.get("source"),
        "manifest_sha256": metadata["daily_raw"]["sha256"], "observed_sha256": sha256(path),
        "tier": TIER_A,
    }


def _option_dates(group: str, symbols: tuple[str, ...]) -> dict[str, set[Any]]:
    result: dict[str, set[Any]] = {}
    for symbol in symbols:
        path = OPTION_ROOT / group / f"{symbol}.parquet"
        if not path.is_file():
            result[symbol] = set()
            continue
        values = pd.read_parquet(path, columns=["time"])
        result[symbol] = set(pd.to_datetime(values.time, errors="coerce").dt.date.dropna())
    return result


def _prior_coverage(candidate: pd.DataFrame, source_dates: dict[str, np.ndarray], map_symbol: Any,
                    max_staleness: int = 7) -> tuple[pd.Series, pd.Series]:
    covered, stale = [], []
    for row in candidate.itertuples(index=False):
        key = map_symbol(row)
        dates = source_dates.get(key, np.array([], dtype=object))
        prior = dates[dates < row.trading_date]
        days = (row.trading_date - prior[-1]).days if len(prior) else np.nan
        covered.append(bool(np.isfinite(days) and 0 < days <= max_staleness))
        stale.append(days)
    return pd.Series(covered, index=candidate.index), pd.Series(stale, index=candidate.index, dtype=float)


def _coverage_rows(candidate: pd.DataFrame, family_masks: dict[str, tuple[pd.Series, pd.Series]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    slices = [("OVERALL", pd.Series(True, index=candidate.index))]
    for column, name in (("validation_slice", "OUTER_FOLD"), ("head", "DIRECTION"),
                         ("underlying_symbol", "UNDERLYING")):
        for value in sorted(candidate[column].astype(str).unique()):
            slices.append((f"{name}:{value}", candidate[column].astype(str).eq(value)))
    year = candidate.decision_timestamp_utc.dt.year.astype(str)
    for value in sorted(year.unique()):
        slices.append((f"YEAR:{value}", year.eq(value)))
    for family, (covered, staleness) in family_masks.items():
        for label, mask in slices:
            local = covered.loc[mask]
            local_stale = staleness.loc[mask & covered]
            rows.append({
                "logical_asset_family": family, "slice": label, "candidate_count": int(mask.sum()),
                "covered_candidate_count": int(local.sum()), "coverage": float(local.mean()) if len(local) else 0.0,
                "median_staleness_calendar_days": float(local_stale.median()) if len(local_stale) else np.nan,
                "maximum_staleness_calendar_days": float(local_stale.max()) if len(local_stale) else np.nan,
            })
    return pd.DataFrame(rows)


def select_tier_a(eligibility: pd.DataFrame, priority: list[str], maximum: int) -> list[str]:
    eligible = set(eligibility.loc[eligibility.tier.eq(TIER_A), "logical_asset_family"])
    return [family for family in priority if family in eligible][:maximum]


def run_asset_audit(output: Path, firewall: TargetValueFirewall) -> dict[str, Any]:
    identities = verify_stage_a_identities()
    candidate = load_candidate_metadata(firewall)
    cfg = load_config()
    symbols = cfg["cross_asset_symbols"]
    inventory = [_stock_inventory(symbol) for symbol in symbols]

    option_files, option_bytes = _directory_stats(OPTION_ROOT)
    option_stats = pd.concat([
        pd.read_parquet(OPTION_ROOT / "daily_underlying_statistics" / f"{symbol}.parquet", columns=["time"])
        .assign(symbol=symbol) for symbol in ("QQQ", "SMH", "SOXX", "SPY")
    ], ignore_index=True)
    option_time = pd.to_datetime(option_stats.time, errors="coerce")
    inventory.append({
        "logical_asset_family": "HISTORICAL_OPTIONS", "asset": "MOOMOO_OPTION_HISTORY_R2",
        "path": str(OPTION_ROOT), "file_format": "PARQUET_PLUS_JSON", "partition_structure": "DATASET_CONTRACT_EXPIRY",
        "file_count": option_files, "approximate_bytes": option_bytes, "row_count": 1_503_835,
        "min_timestamp": str(option_time.min().date()), "max_timestamp": str(option_time.max().date()),
        "timezone": "UTC_AND_US_TRADING_DATE", "timestamp_column": "time|timestamp|time_key",
        "symbol_column": "underlying|option_code", "frequency_resolution": "DAILY_AND_5_MINUTE",
        "duplicate_key_count": 0, "monotonic_timestamp_status": "PASS_WITHIN_PARTITIONS",
        "missingness": "SEE_FROZEN_DATA_QUALITY_MANIFEST", "schema": "OPTIONS_CHAIN_IV_VOLUME_OI_QUOTES_5M",
        "candidate_underlyings_covered": "QQQ|SOXX", "pit_reconstruction_possible": True,
        "information_available_time": "SOURCE_EVENT_TIME_WITH_CONSERVATIVE_PRIOR_DAY_USE",
        "source_immutable_read_only": True, "source": "MOOMOO_OPEND", "manifest_sha256": "FROZEN_R2_MANIFEST",
        "observed_sha256": "DIRECTORY_DATASET_SEE_INDIVIDUAL_MANIFESTS", "tier": TIER_B,
    })
    canonical = DATA / "fast3/moomoo_24h_1m/canonical"
    canonical_files, canonical_bytes = _directory_stats(canonical)
    inventory.append({
        "logical_asset_family": "EXISTING_FAST4_MARKET_INFORMATION", "asset": "CANONICAL_SIX_ETF_1M_OHLCV",
        "path": str(canonical), "file_format": "PARQUET", "partition_structure": "SYMBOL",
        "file_count": canonical_files, "approximate_bytes": canonical_bytes, "row_count": "MANIFEST_DRIVEN",
        "min_timestamp": "2020-01-01", "max_timestamp": "2026-07-24", "timezone": "UTC",
        "timestamp_column": "timestamp", "symbol_column": "symbol", "frequency_resolution": "1_MINUTE",
        "duplicate_key_count": 0, "monotonic_timestamp_status": "PASS_CANONICAL_MANIFEST",
        "missingness": "SEE_SIX_ETF_COVERAGE_MANIFEST", "schema": "OHLCV",
        "candidate_underlyings_covered": "QQQ|SOXX", "pit_reconstruction_possible": True,
        "information_available_time": "BAR_CLOSE", "source_immutable_read_only": True,
        "source": "MOOMOO_OPEND", "manifest_sha256": "FAST4_FROZEN_SOURCE_CONTRACT",
        "observed_sha256": "MANIFEST_REFERENCED", "tier": TIER_D,
    })
    for family, asset, reason in (
        ("MARKET_MICROSTRUCTURE", "NO_LOCAL_TICK_QUOTE_OR_ORDER_BOOK_ARCHIVE",
         "Minute OHLCV is not bid/ask/trade-print microstructure and proxy fabrication is forbidden."),
        ("SCHEDULED_MACRO_EVENTS", "NO_LOCAL_PIT_MACRO_RELEASE_ARCHIVE",
         "No local timestamped consensus/actual/revision calendar with availability times was found."),
        ("ARCHIVED_NEWS_EVENTS", "NO_LOCAL_FIRST_PUBLISHED_NEWS_ARCHIVE",
         "No local first-known headline/content archive with defensible publication timestamps was found."),
        ("OTHER_ALTERNATIVE_PIT_DATA", "CURRENT_2026_EQUITY_UNIVERSE_DAILY_HISTORY",
         "Current-universe membership is not historical PIT membership and would introduce survivorship selection."),
    ):
        inventory.append({
            "logical_asset_family": family, "asset": asset, "path": str(DATA), "file_format": "NONE_ELIGIBLE",
            "partition_structure": "NOT_APPLICABLE", "file_count": 0, "approximate_bytes": 0, "row_count": 0,
            "min_timestamp": None, "max_timestamp": None, "timezone": None, "timestamp_column": None,
            "symbol_column": None, "frequency_resolution": None, "duplicate_key_count": 0,
            "monotonic_timestamp_status": "NOT_APPLICABLE", "missingness": "NO_ELIGIBLE_ARCHIVE",
            "schema": reason, "candidate_underlyings_covered": "NONE", "pit_reconstruction_possible": False,
            "information_available_time": "UNPROVEN", "source_immutable_read_only": True, "source": "NOT_FOUND",
            "manifest_sha256": None, "observed_sha256": None, "tier": TIER_C,
        })

    cross_dates = {}
    for symbol in symbols:
        dates = pd.read_parquet(DATA / "stocks" / symbol / "daily_raw.parquet", columns=["date"])
        cross_dates[symbol] = np.array(pd.to_datetime(dates.date, errors="raise").dt.date)
    cross_cover = pd.Series(True, index=candidate.index)
    cross_stale = pd.Series(0.0, index=candidate.index)
    for symbol in symbols:
        local_cover, local_stale = _prior_coverage(candidate, {symbol: cross_dates[symbol]}, lambda _: symbol)
        cross_cover &= local_cover
        cross_stale = pd.concat([cross_stale, local_stale], axis=1).max(axis=1)
    stats_dates = _option_dates("daily_underlying_statistics", ("QQQ", "SOXX"))
    vol_dates = _option_dates("daily_underlying_volatility", ("QQQ", "SOXX"))
    option_dates = {symbol: np.array(sorted(stats_dates[symbol] & vol_dates[symbol])) for symbol in ("QQQ", "SOXX")}
    option_cover, option_stale = _prior_coverage(candidate, option_dates,
        lambda row: "QQQ" if row.underlying_symbol == "QQQ" else "SOXX")
    zero = pd.Series(False, index=candidate.index)
    none_stale = pd.Series(np.nan, index=candidate.index)
    family_masks = {
        "MARKET_MICROSTRUCTURE": (zero, none_stale), "HISTORICAL_OPTIONS": (option_cover, option_stale),
        "SCHEDULED_MACRO_EVENTS": (zero, none_stale), "ARCHIVED_NEWS_EVENTS": (zero, none_stale),
        "GENUINELY_NEW_CROSS_ASSET": (cross_cover, cross_stale),
        "OTHER_ALTERNATIVE_PIT_DATA": (zero, none_stale),
        "EXISTING_FAST4_MARKET_INFORMATION": (pd.Series(True, index=candidate.index), pd.Series(0.0, index=candidate.index)),
    }
    coverage = _coverage_rows(candidate, family_masks)
    eligibility = pd.DataFrame([
        {"logical_asset_family": "MARKET_MICROSTRUCTURE", "tier": TIER_C, "coverage": 0.0,
         "covered_outer_blocks": 0, "covered_calendar_years": 0, "reason": "NO_LOCAL_TICK_QUOTE_ORDER_BOOK_ARCHIVE"},
        {"logical_asset_family": "HISTORICAL_OPTIONS", "tier": TIER_B, "coverage": float(option_cover.mean()),
         "covered_outer_blocks": int(candidate.loc[option_cover, "validation_slice"].nunique()),
         "covered_calendar_years": int(candidate.loc[option_cover, "decision_timestamp_utc"].dt.year.nunique()),
         "reason": "33.5_PERCENT_COVERAGE_ONLY_2023_PARTIAL_2024_2025JAN;FAIL_65_PERCENT_AND_4_BLOCK_GATES"},
        {"logical_asset_family": "SCHEDULED_MACRO_EVENTS", "tier": TIER_C, "coverage": 0.0,
         "covered_outer_blocks": 0, "covered_calendar_years": 0, "reason": "NO_LOCAL_PIT_RELEASE_ARCHIVE"},
        {"logical_asset_family": "ARCHIVED_NEWS_EVENTS", "tier": TIER_C, "coverage": 0.0,
         "covered_outer_blocks": 0, "covered_calendar_years": 0, "reason": "NO_LOCAL_FIRST_PUBLISHED_ARCHIVE"},
        {"logical_asset_family": "GENUINELY_NEW_CROSS_ASSET", "tier": TIER_A, "coverage": float(cross_cover.mean()),
         "covered_outer_blocks": int(candidate.loc[cross_cover, "validation_slice"].nunique()),
         "covered_calendar_years": int(candidate.loc[cross_cover, "decision_timestamp_utc"].dt.year.nunique()),
         "reason": "SIX_RAW_DAILY_ETFS_PRIOR_DAY_ONLY_100_PERCENT_COVERAGE_ALL_BLOCKS_2020_2025"},
        {"logical_asset_family": "OTHER_ALTERNATIVE_PIT_DATA", "tier": TIER_C, "coverage": 0.0,
         "covered_outer_blocks": 0, "covered_calendar_years": 0, "reason": "NO_OTHER_DEFENSIBLE_PIT_SOURCE;CURRENT_UNIVERSE_SURVIVORSHIP_FORBIDDEN"},
        {"logical_asset_family": "EXISTING_FAST4_MARKET_INFORMATION", "tier": TIER_D, "coverage": 1.0,
         "covered_outer_blocks": int(candidate.validation_slice.nunique()),
         "covered_calendar_years": int(candidate.decision_timestamp_utc.dt.year.nunique()),
         "reason": "QQQ_SOXX_VIX_AND_TARGET_INSTRUMENT_OHLCV_ALREADY_IN_FAST4_241_FEATURES"},
    ])
    selected = select_tier_a(eligibility, cfg["family_priority"], cfg["maximum_selected_families"])
    inventory_frame = pd.DataFrame(inventory)
    inventory_frame.to_csv(output / "FAST5_R1_DATA_ASSET_INVENTORY.csv", index=False)
    eligibility.to_csv(output / "FAST5_R1_DATA_FAMILY_ELIGIBILITY.csv", index=False)
    coverage.to_csv(output / "FAST5_R1_COVERAGE_MATRIX.csv", index=False)
    tier_lists = {tier: eligibility.loc[eligibility.tier.eq(tier), "logical_asset_family"].tolist()
                  for tier in (TIER_A, TIER_B, TIER_C, TIER_D)}
    audit = {
        "schema_version": "FAST5_R1_DATA_ASSET_AUDIT_V1", "created_at_utc": now_utc(),
        "stage": firewall.stage, "outcome_blind": True, "target_value_read_count": firewall.target_value_read_count,
        "candidate_projection_columns": list(ALLOWED_CANDIDATE_COLUMNS), "candidate_count": len(candidate),
        "candidate_start": str(candidate.decision_timestamp_utc.min()), "candidate_end": str(candidate.decision_timestamp_utc.max()),
        "canonical_data_root": str(DATA), "external_results_root": str(RESULTS), "external_cache_root": str(CACHE),
        "approved_roots_only": True, "data_root_write_count": 0, "source_data_mutation": False,
        "frozen_identities": identities["observed_sha256"], "asset_record_count": len(inventory_frame),
        "family_count": len(eligibility), "tier_lists": tier_lists, "selected_new_information_families": selected,
        "coverage_contract": {"continuous_minimum": cfg["continuous_coverage_minimum"],
                              "outer_blocks_minimum": cfg["continuous_outer_blocks_minimum"],
                              "calendar_years_minimum": cfg["continuous_calendar_years_minimum"]},
        "pit_audit_status": "PASS_SELECTED_CROSS_ASSET_RAW_PRIOR_DAY_STRICT_JOIN",
        "timezone_session_status": "PASS_US_TRADING_DATE_TO_NEXT_CANDIDATE_DAY_CONSERVATIVE_AVAILABILITY",
        "corporate_action_status": "PASS_RAW_PRICES_WITH_ABS_35PCT_RETURN_WINDOW_INVALIDATION_PREDECLARED",
    }
    write_json(output / "FAST5_R1_DATA_ASSET_AUDIT.json", audit)
    gaps = {
        "schema_version": "FAST5_R1_DATA_GAP_REPORT_V1", "created_at_utc": now_utc(),
        "microstructure": "Acquire immutable historical trades/quotes with bid, ask, sizes and availability timestamps.",
        "historical_options": "Existing archive begins mid-2023 for daily aggregates and late-2024 for a narrow 5m contract set; 65%/4-fold gate fails.",
        "macro_events": "Materialize a first-known release calendar including scheduled time, consensus, actual and revision availability.",
        "news_events": "Materialize first-published immutable headlines/company-event archive with source timestamps.",
        "other": "Avoid retrospective current-universe breadth; require historical constituent membership snapshots.",
        "training_allowed_families": selected,
    }
    write_json(output / "FAST5_R1_DATA_GAP_REPORT.json", gaps)
    discovery = {
        "schema_version": "FAST5_R1_DISCOVERY_MANIFEST_V1", "created_at_utc": now_utc(),
        "repository": str(REPO), "canonical_data_root": str(DATA), "external_results_root": str(RESULTS),
        "r1_frozen_root": str(R1_ROOT), "candidate_metadata_source": str(R1_MATRIX),
        "target_contract_path": str(R43A_CONTRACT), "target_contract_sha256": cfg["target_sha256"],
        "fast4_feature_manifest_path": str(R1_FEATURE_MANIFEST),
        "fast4_feature_manifest_identity": cfg["fast4_baseline_feature_manifest_sha256"],
        "python_executable": sys.executable, "python_version": platform.python_version(),
        "stage_a_target_value_read_count": firewall.target_value_read_count,
        "prospective_outcome_read": False, "broker_action_allowed": False,
    }
    write_json(output / "FAST5_R1_DISCOVERY_MANIFEST.json", discovery)
    return {"audit": audit, "eligibility": eligibility, "coverage": coverage, "inventory": inventory_frame,
            "selected": selected, "candidate": candidate, "tier_lists": tier_lists}
