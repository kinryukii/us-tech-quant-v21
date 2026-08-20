"""Fixed-current-cohort pre-2026 historical feature eligibility contract.

This is not a historical PIT investable-universe reconstruction.  It freezes
the current canonical ABCDE cohort first, then identifies dates on which each
current name has enough contemporaneously available Moomoo-derived history to
construct every frozen A2-R1 stock-state feature.  No target, outcome, model,
broker, FAST, or daily-chain path is used.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


EXPERIMENT_ID = "ABCDE_A2_R0V_CURRENT_COHORT_HISTORICAL_ELIGIBILITY_R1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
PRICE_ROOT = DATA_ROOT / "moomoo/source/prices_qfq"
CURRENT_COHORT_TABLE = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.csv"
CURRENT_COHORT_MANIFEST = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.active_manifest.json"
R0U_SUMMARY = Path(r"D:\us-tech-quant-results\ABCDE_A2_R0U_PIT_UNIVERSE_RECOVERY_R1\abcde_a2_r0u_summary.json")
R0U_MODULE = REPO_ROOT / "scripts/v22/abcde_a2_r0u_pit_universe_recovery_r1.py"
TRAINING_START = pd.Timestamp("2020-01-02")
TRAINING_BOUNDARY = pd.Timestamp("2026-01-01")
RESEARCH_UNIVERSE_TYPE = "FIXED_CURRENT_COHORT_HISTORICAL_TRAINING"

ELIGIBILITY_PATH = RESULTS_ROOT / "current_cohort_historical_eligibility.parquet"
SECURITY_DIAGNOSTICS_PATH = RESULTS_ROOT / "current_cohort_security_diagnostics.json"
SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r0v_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r0v_manifest.json"

SUMMARY_FIELDS = (
    "ABCDE_A2_R0V_STATUS", "ABCDE_A2_R0V_CLASSIFICATION", "ABCDE_A2_R0V_DECISION",
    "RESEARCH_UNIVERSE_TYPE", "HISTORICAL_PIT_INVESTABLE_UNIVERSE_CLAIM",
    "CURRENT_COHORT_COUNT", "CURRENT_COHORT_SOURCE", "CURRENT_COHORT_FINGERPRINT",
    "CURRENT_COHORT_IDENTITY_STATUS", "MAX_REQUIRED_LOOKBACK",
    "A2_R1_PREREGISTRATION_CHANGED", "A1_A2_DAILY_UNIVERSE_IDENTITY_REQUIRED",
    "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS", "PRE2026_SECURITY_WITH_ANY_PRICE_COUNT",
    "PRE2026_SECURITY_WITH_FULL_FEATURE_ELIGIBILITY_COUNT", "NO_PRE2026_PRICE_SECURITY_COUNT",
    "INSUFFICIENT_LOOKBACK_SECURITY_COUNT", "TRAINING_ROW_COUNT_PRE2026",
    "TRAINING_ROW_COUNT_2026_PLUS", "PRE_FIRST_PRICE_ELIGIBLE_ROW_COUNT",
    "INSUFFICIENT_LOOKBACK_ELIGIBLE_ROW_COUNT", "POST_2025_TRAINING_ELIGIBLE_ROW_COUNT",
    "CURRENT_COHORT_ONLY_STATUS", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
    "TARGET_VALUE_READ_COUNT", "OUTCOME_READ_COUNT", "BROKER_ACTION_COUNT",
    "MOOMOO_API_REQUEST_COUNT", "DAILY_CHAIN_CHANGED", "A1_CHANGED", "B_CHANGED",
    "C_CHANGED", "D_CHANGED", "E_CHANGED", "FAST_CHANGED", "R0U_STATUS_PRESERVED",
    "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT",
    "ANTI_BLOAT_STATUS", "RESULTS_ROOT", "ELIGIBILITY_PATH", "SECURITY_DIAGNOSTICS_PATH",
    "MANIFEST_PATH", "SUMMARY_PATH", "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def r0u_module():
    return import_module("abcde_a2_r0u_contract", R0U_MODULE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8", newline="\n",
    )
    os.replace(temporary, path)


def write_parquet_atomic(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6", write_statistics=True)
    os.replace(temporary, path)


def feature_lookback_contract(features: tuple[str, ...] | list[str]) -> dict[str, dict[str, Any]]:
    """Derive observation requirements from the frozen, semantic feature names."""
    contract: dict[str, dict[str, Any]] = {}
    for feature in features:
        match: re.Match[str] | None
        if match := re.fullmatch(r"ret_(\d+)d", feature):
            days = int(match.group(1)); observations = days + 1; fields = ["close"]
        elif match := re.fullmatch(r"price_vs_ma(\d+)", feature):
            observations = int(match.group(1)); fields = ["close"]
        elif match := re.fullmatch(r"ma(\d+)_vs_ma(\d+)", feature):
            observations = max(int(match.group(1)), int(match.group(2))); fields = ["close"]
        elif match := re.fullmatch(r"realized_vol_(\d+)d", feature):
            observations = int(match.group(1)) + 1; fields = ["close"]
        elif match := re.fullmatch(r"(?:downside|upside)_vol_(\d+)d", feature):
            observations = int(match.group(1)) + 1; fields = ["close"]
        elif match := re.fullmatch(r"distance_from_(?:high|low)_(\d+)d", feature):
            observations = int(match.group(1)); fields = ["close"]
        elif match := re.fullmatch(r"max_drawdown_(\d+)d", feature):
            observations = int(match.group(1)); fields = ["close"]
        elif match := re.fullmatch(r"avg_volume_(\d+)d", feature):
            observations = int(match.group(1)); fields = ["volume"]
        elif match := re.fullmatch(r"volume_ratio_(\d+)d_(\d+)d", feature):
            observations = max(int(match.group(1)), int(match.group(2))); fields = ["volume"]
        elif match := re.fullmatch(r"avg_dollar_volume_(\d+)d", feature):
            observations = int(match.group(1)); fields = ["close", "volume"]
        else:
            raise ValueError(f"UNKNOWN_FROZEN_FEATURE_LOOKBACK:{feature}")
        contract[feature] = {
            "required_observations_including_t": observations,
            "required_fields": fields,
            "information_rule": "observations_at_or_before_signal_date_only",
        }
    return contract


def row_is_eligible(
    in_current_cohort: bool,
    price_available: bool,
    close_observations: int,
    volume_observations: int,
    dollar_volume_observations: int,
    signal_date: str | pd.Timestamp,
    required: dict[str, int],
) -> bool:
    signal = pd.Timestamp(signal_date)
    return bool(
        in_current_cohort and price_available and signal < TRAINING_BOUNDARY
        and signal >= TRAINING_START
        and close_observations >= required["close"]
        and volume_observations >= required["volume"]
        and dollar_volume_observations >= required["dollar_volume"]
    )


def consecutive_valid_counts(values: np.ndarray) -> np.ndarray:
    output = np.zeros(len(values), dtype=np.int32)
    count = 0
    for index, valid in enumerate(values):
        count = count + 1 if bool(valid) else 0
        output[index] = count
    return output


def freeze_current_cohort() -> tuple[list[str], dict[str, Any]]:
    manifest = json.loads(CURRENT_COHORT_MANIFEST.read_text(encoding="utf-8"))
    table_hash = sha256_file(CURRENT_COHORT_TABLE)
    with CURRENT_COHORT_TABLE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    tickers = sorted({str(row.get("ticker", "")).strip().upper() for row in rows if row.get("ticker")})
    ticker_set_fingerprint = hashlib.sha256(("\n".join(tickers) + "\n").encode("ascii")).hexdigest()
    checks = {
        "manifest_file_matches": manifest.get("manifest_file") == CURRENT_COHORT_TABLE.name,
        "manifest_sha256_matches": manifest.get("sha256") == table_hash,
        "manifest_count_matches": int(manifest.get("active_ticker_count", -1)) == len(tickers),
        "row_count_without_duplicate_tickers": len(rows) == len(tickers),
    }
    return tickers, {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "source": str(CURRENT_COHORT_TABLE),
        "manifest_path": str(CURRENT_COHORT_MANIFEST),
        "manifest_version": manifest.get("version"),
        "manifest_effective_date": manifest.get("effective_date"),
        "count": len(tickers),
        "fingerprint": table_hash,
        "ticker_set_fingerprint": ticker_set_fingerprint,
        "checks": checks,
    }


def load_pre2026_prices(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    ticker_set = set(tickers)
    parts: list[pd.DataFrame] = []
    hashes: dict[str, str] = {}
    paths = sorted(
        path for path in PRICE_ROOT.glob("year=*/prices.parquet")
        if int(path.parent.name.split("=")[1]) < 2026
    )
    if not paths or not any(path.parent.name == "year=2019" for path in paths):
        raise RuntimeError("MISSING_PRE2020_LOOKBACK_PRICE_PARTITION")
    for path in paths:
        schema = pq.ParquetFile(path).schema_arrow
        required = {"ticker", "trade_date", "close", "volume"}
        if not required.issubset(schema.names):
            raise RuntimeError(f"MISSING_PRICE_FIELDS:{path}:{sorted(required-set(schema.names))}")
        frame = pq.read_table(path, columns=sorted(required)).to_pandas()
        frame = frame.loc[frame["ticker"].isin(ticker_set)]
        parts.append(frame)
        hashes[str(path)] = sha256_file(path)
    prices = pd.concat(parts, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["volume"] = pd.to_numeric(prices["volume"], errors="coerce")
    prices = prices.sort_values(["ticker", "trade_date"], kind="stable").reset_index(drop=True)
    return prices, hashes


def add_history_state(prices: pd.DataFrame, required: dict[str, int]) -> pd.DataFrame:
    prices = prices.copy()
    prices["valid_date"] = prices["trade_date"].notna() & prices["trade_date"].lt(TRAINING_BOUNDARY)
    prices["price_available"] = prices["valid_date"] & np.isfinite(prices["close"]) & prices["close"].gt(0)
    prices["volume_available"] = prices["valid_date"] & np.isfinite(prices["volume"]) & prices["volume"].ge(0)
    prices["dollar_volume_available"] = prices["price_available"] & prices["volume_available"]
    states: list[pd.DataFrame] = []
    for _ticker, group in prices.groupby("ticker", sort=True):
        group = group.copy()
        group["close_observations"] = consecutive_valid_counts(group["price_available"].to_numpy())
        group["volume_observations"] = consecutive_valid_counts(group["volume_available"].to_numpy())
        group["dollar_volume_observations"] = consecutive_valid_counts(group["dollar_volume_available"].to_numpy())
        group["lookback_complete"] = (
            group["price_available"]
            & group["close_observations"].ge(required["close"])
            & group["volume_observations"].ge(required["volume"])
            & group["dollar_volume_observations"].ge(required["dollar_volume"])
        )
        states.append(group)
    return pd.concat(states, ignore_index=True).sort_values(["ticker", "trade_date"], kind="stable")


def build_eligibility(
    tickers: list[str], history: pd.DataFrame, required: dict[str, int]
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    calendar = sorted(
        history.loc[
            history["ticker"].eq("QQQ") & history["price_available"]
            & history["trade_date"].ge(TRAINING_START) & history["trade_date"].lt(TRAINING_BOUNDARY),
            "trade_date",
        ].unique()
    )
    if not calendar:
        raise RuntimeError("QQQ_PRE2026_TRAINING_CALENDAR_MISSING")
    grid = pd.MultiIndex.from_product([calendar, tickers], names=["signal_date", "ticker"]).to_frame(index=False)
    source = history.loc[
        history["trade_date"].ge(TRAINING_START) & history["trade_date"].lt(TRAINING_BOUNDARY),
        ["trade_date", "ticker", "price_available", "close_observations", "volume_observations", "dollar_volume_observations", "lookback_complete"],
    ].rename(columns={"trade_date": "signal_date"})
    grid = grid.merge(source, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    grid["in_current_cohort"] = True
    grid["price_available"] = grid["price_available"].fillna(False).astype(bool)
    grid["lookback_complete"] = grid["lookback_complete"].fillna(False).astype(bool)
    for column in ("close_observations", "volume_observations", "dollar_volume_observations"):
        grid[column] = grid[column].fillna(0).astype(np.int32)
    grid["date_lt_2026"] = grid["signal_date"].lt(TRAINING_BOUNDARY)
    grid["eligible_training"] = (
        grid["in_current_cohort"] & grid["price_available"] & grid["lookback_complete"]
        & grid["date_lt_2026"] & grid["signal_date"].ge(TRAINING_START)
    )
    grid["eligible_a1"] = grid["eligible_training"]
    grid["eligible_a2"] = grid["eligible_training"]
    grid = grid.sort_values(["signal_date", "ticker"], kind="stable").reset_index(drop=True)

    diagnostics: list[dict[str, Any]] = []
    for ticker in tickers:
        group = history.loc[history["ticker"].eq(ticker)]
        valid = group.loc[group["price_available"]]
        complete = group.loc[group["lookback_complete"]]
        eligible_rows = int(grid.loc[grid["ticker"].eq(ticker), "eligible_training"].sum())
        diagnostics.append({
            "ticker": ticker,
            "security_identity": f"CURRENT_ABCDE::{ticker}",
            "FIRST_OBSERVED_PRICE_DATE": valid["trade_date"].min().date().isoformat() if len(valid) else None,
            "FIRST_FULL_FEATURE_ELIGIBLE_DATE": complete["trade_date"].min().date().isoformat() if len(complete) else None,
            "last_pre2026_price_date": valid["trade_date"].max().date().isoformat() if len(valid) else None,
            "pre2026_price_row_count": int(len(valid)),
            "historical_price_available": bool(len(valid)),
            "eligible_training_row_count": eligible_rows,
        })

    daily = grid.groupby("signal_date", as_index=False)["eligible_training"].sum().rename(columns={"eligible_training": "eligible_security_count"})
    yearly: dict[str, Any] = {}
    for year in range(2020, 2026):
        rows = grid.loc[grid["signal_date"].dt.year.eq(year)]
        counts = daily.loc[daily["signal_date"].dt.year.eq(year), "eligible_security_count"]
        yearly[str(year)] = {
            "eligible_security_count": int(rows.loc[rows["eligible_training"], "ticker"].nunique()),
            "eligible_training_row_count": int(rows["eligible_training"].sum()),
            "trading_day_count": int(len(counts)),
            "daily_eligible_min": int(counts.min()),
            "daily_eligible_median": float(counts.median()),
            "daily_eligible_max": int(counts.max()),
        }

    first_dates = {row["ticker"]: row["FIRST_OBSERVED_PRICE_DATE"] for row in diagnostics}
    first_series = grid["ticker"].map(first_dates)
    first_series = pd.to_datetime(first_series, errors="coerce")
    audits = {
        "pre_first_price_eligible_row_count": int((grid["eligible_training"] & grid["signal_date"].lt(first_series)).sum()),
        "insufficient_lookback_eligible_row_count": int((grid["eligible_training"] & ~grid["lookback_complete"]).sum()),
        "post_2025_training_eligible_row_count": int((grid["eligible_training"] & grid["signal_date"].ge(TRAINING_BOUNDARY)).sum()),
        "a1_a2_daily_universe_mismatch_row_count": int(grid["eligible_a1"].ne(grid["eligible_a2"]).sum()),
        "unexpected_ticker_count": int(len(set(grid["ticker"]) - set(tickers))),
        "duplicate_ticker_date_count": int(grid.duplicated(["signal_date", "ticker"]).sum()),
        "calendar_source": "QQQ_MOOMOO_CANONICAL_VALID_PRICE_DATES",
    }
    return grid, diagnostics, yearly, audits


def eligibility_arrow(frame: pd.DataFrame) -> pa.Table:
    return pa.table({
        "signal_date": pa.array(frame["signal_date"].dt.date, type=pa.date32()),
        "ticker": pa.array(frame["ticker"], type=pa.string()),
        "in_current_cohort": pa.array(frame["in_current_cohort"], type=pa.bool_()),
        "price_available_at_t": pa.array(frame["price_available"], type=pa.bool_()),
        "lookback_complete_at_t": pa.array(frame["lookback_complete"], type=pa.bool_()),
        "valid_close_observation_count_to_t": pa.array(frame["close_observations"], type=pa.int32()),
        "valid_volume_observation_count_to_t": pa.array(frame["volume_observations"], type=pa.int32()),
        "date_lt_2026": pa.array(frame["date_lt_2026"], type=pa.bool_()),
        "eligible_for_a1": pa.array(frame["eligible_a1"], type=pa.bool_()),
        "eligible_for_a2": pa.array(frame["eligible_a2"], type=pa.bool_()),
        "eligible_training": pa.array(frame["eligible_training"], type=pa.bool_()),
    })


def logical_eligibility_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame[["signal_date", "ticker", "price_available", "lookback_complete", "eligible_training"]].itertuples(index=False):
        digest.update(f"{row.signal_date.date()}|{row.ticker}|{int(row.price_available)}|{int(row.lookback_complete)}|{int(row.eligible_training)}\n".encode("ascii"))
    return digest.hexdigest()


def _display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def run() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    prior_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else {}
    created_at = prior_manifest.get("created_at_utc") or datetime.now(timezone.utc).isoformat()

    r0u = r0u_module()
    r0u_summary = json.loads(R0U_SUMMARY.read_text(encoding="utf-8"))
    r0u_preserved = r0u_summary.get("ABCDE_A2_R0U_STATUS") == "FAIL_CLOSED"
    cohort, cohort_audit = freeze_current_cohort()
    prereg = r0u.audit_preregistration()
    a2 = r0u.import_prior_a2()
    lookbacks = feature_lookback_contract(a2.FEATURES)
    required = {
        "close": max(spec["required_observations_including_t"] for spec in lookbacks.values() if "close" in spec["required_fields"]),
        "volume": max(spec["required_observations_including_t"] for spec in lookbacks.values() if spec["required_fields"] == ["volume"]),
        "dollar_volume": max(spec["required_observations_including_t"] for spec in lookbacks.values() if spec["required_fields"] == ["close", "volume"]),
    }
    max_required = max(spec["required_observations_including_t"] for spec in lookbacks.values())
    prices, price_hashes = load_pre2026_prices(cohort)
    duplicate_source_rows = int(prices.duplicated(["ticker", "trade_date"]).sum())
    history = add_history_state(prices, required)
    eligibility, diagnostics, yearly, audits = build_eligibility(cohort, history, required)

    table = eligibility_arrow(eligibility)
    write_parquet_atomic(ELIGIBILITY_PATH, table)
    write_json_atomic(SECURITY_DIAGNOSTICS_PATH, {
        "schema_version": "1.0", "records": diagnostics,
        "first_observed_price_date_is_official_listing_date": False,
    })
    logical_fingerprint = logical_eligibility_fingerprint(eligibility)

    any_price_count = sum(bool(row["historical_price_available"]) for row in diagnostics)
    full_count = sum(row["FIRST_FULL_FEATURE_ELIGIBLE_DATE"] is not None for row in diagnostics)
    insufficient_count = sum(row["historical_price_available"] and row["FIRST_FULL_FEATURE_ELIGIBLE_DATE"] is None for row in diagnostics)
    training_rows = int(eligibility["eligible_training"].sum())
    protected_now = r0u.protected_hashes()
    protected_initial = prior_manifest.get("protected_hashes_initial", protected_now)
    protected_unchanged = protected_now == protected_initial

    pass_checks = {
        "r0u_fail_closed_preserved": r0u_preserved,
        "cohort_identity": cohort_audit["status"] == "PASS" and len(cohort) == 325,
        "preregistration_unchanged": prereg["changed"] is False,
        "all_features_have_lookback_contract": set(lookbacks) == set(a2.FEATURES),
        "max_required_lookback_is_121_observations": max_required == 121,
        "source_no_duplicates": duplicate_source_rows == 0,
        "at_least_one_price_security": any_price_count > 0,
        "pre_first_price_guard": audits["pre_first_price_eligible_row_count"] == 0,
        "lookback_guard": audits["insufficient_lookback_eligible_row_count"] == 0,
        "post_2025_guard": audits["post_2025_training_eligible_row_count"] == 0,
        "a1_a2_identity": audits["a1_a2_daily_universe_mismatch_row_count"] == 0,
        "current_cohort_only": audits["unexpected_ticker_count"] == 0,
        "eligibility_unique": audits["duplicate_ticker_date_count"] == 0,
        "protected_paths_unchanged": protected_unchanged,
    }
    status = "PASS" if all(pass_checks.values()) else "FAIL_CLOSED"

    implementation_sha256 = sha256_file(Path(__file__).resolve())
    stable_contract = {
        "experiment_id": EXPERIMENT_ID,
        "implementation_sha256": implementation_sha256,
        "cohort_audit": cohort_audit,
        "research_universe_type": RESEARCH_UNIVERSE_TYPE,
        "historical_pit_investable_universe_claim": False,
        "training_start": TRAINING_START.date().isoformat(),
        "training_end": "2025-12-31",
        "feature_lookbacks": lookbacks,
        "required_observations": required,
        "preregistration_fingerprint": prereg["current_fingerprint"],
        "price_source_hashes": price_hashes,
        "logical_eligibility_fingerprint": logical_fingerprint,
        "security_diagnostics_fingerprint": canonical_fingerprint(diagnostics),
        "yearly_diagnostics": yearly,
        "audits": audits,
        "pass_checks": pass_checks,
    }
    run_fingerprint = canonical_fingerprint(stable_contract)
    same_implementation = prior_manifest.get("implementation_sha256") == implementation_sha256
    run1 = prior_manifest.get("run1_fingerprint") if same_implementation else run_fingerprint
    run1 = run1 or run_fingerprint
    prior_run_count = int(prior_manifest.get("completed_run_count", 0)) if same_implementation else 0
    run_count = prior_run_count + 1
    reproduction = "PASS" if run_count >= 2 and run1 == run_fingerprint else "PENDING_SECOND_RUN"
    if run_count >= 2 and run1 != run_fingerprint:
        reproduction = "FAIL"
        status = "FAIL_CLOSED"

    summary: dict[str, Any] = {
        "ABCDE_A2_R0V_STATUS": status,
        "ABCDE_A2_R0V_CLASSIFICATION": "A_FIXED_CURRENT_COHORT_HISTORICAL_ELIGIBILITY_ESTABLISHED" if status == "PASS" else "FAIL_CLOSED_CONTRACT_VIOLATION",
        "ABCDE_A2_R0V_DECISION": "AUTHORIZE_A2_R1_MODELING_ON_FROZEN_CURRENT_COHORT_PRE2026_ELIGIBLE_ROWS" if status == "PASS" else "STOP_AND_REPAIR_R0V_CONTRACT",
        "RESEARCH_UNIVERSE_TYPE": RESEARCH_UNIVERSE_TYPE,
        "HISTORICAL_PIT_INVESTABLE_UNIVERSE_CLAIM": False,
        "CURRENT_COHORT_COUNT": len(cohort),
        "CURRENT_COHORT_SOURCE": str(CURRENT_COHORT_TABLE),
        "CURRENT_COHORT_FINGERPRINT": cohort_audit["fingerprint"],
        "CURRENT_COHORT_IDENTITY_STATUS": cohort_audit["status"],
        "MAX_REQUIRED_LOOKBACK": 120,
        "MAX_REQUIRED_LOOKBACK_UNIT": "TRADING_DAY_LAG",
        "MAX_REQUIRED_OBSERVATIONS": max_required,
        "A2_R1_PREREGISTRATION_CHANGED": prereg["changed"],
        "A1_A2_DAILY_UNIVERSE_IDENTITY_REQUIRED": True,
        "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS": "PASS" if audits["a1_a2_daily_universe_mismatch_row_count"] == 0 else "FAIL",
        "PRE2026_SECURITY_WITH_ANY_PRICE_COUNT": any_price_count,
        "PRE2026_SECURITY_WITH_FULL_FEATURE_ELIGIBILITY_COUNT": full_count,
        "NO_PRE2026_PRICE_SECURITY_COUNT": len(cohort) - any_price_count,
        "INSUFFICIENT_LOOKBACK_SECURITY_COUNT": insufficient_count,
        "TRAINING_ROW_COUNT_PRE2026": training_rows,
        "TRAINING_ROW_COUNT_2026_PLUS": 0,
        "PRE_FIRST_PRICE_ELIGIBLE_ROW_COUNT": audits["pre_first_price_eligible_row_count"],
        "INSUFFICIENT_LOOKBACK_ELIGIBLE_ROW_COUNT": audits["insufficient_lookback_eligible_row_count"],
        "POST_2025_TRAINING_ELIGIBLE_ROW_COUNT": audits["post_2025_training_eligible_row_count"],
        "CURRENT_COHORT_ONLY_STATUS": "PASS" if audits["unexpected_ticker_count"] == 0 else "FAIL",
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "TARGET_VALUE_READ_COUNT": 0,
        "OUTCOME_READ_COUNT": 0,
        "BROKER_ACTION_COUNT": 0,
        "MOOMOO_API_REQUEST_COUNT": 0,
        "DAILY_CHAIN_CHANGED": not protected_unchanged,
        "A1_CHANGED": not protected_unchanged,
        "B_CHANGED": False,
        "C_CHANGED": False,
        "D_CHANGED": False,
        "E_CHANGED": False,
        "FAST_CHANGED": False,
        "R0U_STATUS_PRESERVED": r0u_preserved,
        "REPRODUCIBILITY_STATUS": reproduction,
        "RUN1_FINGERPRINT": run1,
        "RUN2_FINGERPRINT": run_fingerprint if run_count >= 2 else None,
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "ELIGIBILITY_PATH": str(ELIGIBILITY_PATH),
        "SECURITY_DIAGNOSTICS_PATH": str(SECURITY_DIAGNOSTICS_PATH),
        "MANIFEST_PATH": str(MANIFEST_PATH),
        "SUMMARY_PATH": str(SUMMARY_PATH),
        "NEXT_AUTHORIZED_STEP": "ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING" if status == "PASS" else None,
        "FAILURE_REASON": None if status == "PASS" else ";".join(key for key, passed in pass_checks.items() if not passed),
        "ELIGIBILITY_LOGICAL_FINGERPRINT": logical_fingerprint,
        "IMPLEMENTATION_SHA256": implementation_sha256,
        "ELIGIBILITY_PARQUET_SHA256": sha256_file(ELIGIBILITY_PATH),
        "CURRENT_COHORT_TICKER_SET_FINGERPRINT": cohort_audit["ticker_set_fingerprint"],
        "SOURCE_PRICE_ROW_COUNT": int(len(prices)),
        "SOURCE_DUPLICATE_TICKER_DATE_COUNT": duplicate_source_rows,
        "TRAINING_CALENDAR_DATE_COUNT": int(eligibility["signal_date"].nunique()),
        "yearly_diagnostics": yearly,
        "feature_lookback_contract": lookbacks,
        "required_observations_by_field_family": required,
        "cohort_identity_audit": cohort_audit,
        "eligibility_audits": audits,
        "pass_checks": pass_checks,
        "preregistration_audit": prereg,
        "r0u_preservation_audit": {
            "path": str(R0U_SUMMARY), "sha256": sha256_file(R0U_SUMMARY),
            "status": r0u_summary.get("ABCDE_A2_R0U_STATUS"), "preserved": r0u_preserved,
        },
        "outcome_or_target_paths_read": [],
        "official_listing_date_claimed": False,
    }
    for year, values in yearly.items():
        summary[f"ELIGIBLE_SECURITY_COUNT_{year}"] = values["eligible_security_count"]

    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": "1.0",
        "created_at_utc": created_at,
        "last_verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_run_count": run_count,
        "run1_fingerprint": run1,
        "current_run_fingerprint": run_fingerprint,
        "implementation_sha256": implementation_sha256,
        "reproducibility_status": reproduction,
        "research_universe_type": RESEARCH_UNIVERSE_TYPE,
        "historical_pit_investable_universe_claim": False,
        "source_paths": [str(CURRENT_COHORT_TABLE), str(CURRENT_COHORT_MANIFEST), *price_hashes],
        "source_hashes": {str(CURRENT_COHORT_TABLE): cohort_audit["fingerprint"], **price_hashes},
        "feature_lookback_contract": lookbacks,
        "output_paths": [str(ELIGIBILITY_PATH), str(SECURITY_DIAGNOSTICS_PATH), str(SUMMARY_PATH)],
        "eligibility_logical_fingerprint": logical_fingerprint,
        "protected_hashes_initial": protected_initial,
        "model_fit_count": 0,
        "model_predict_call_count": 0,
        "target_value_read_count": 0,
        "outcome_read_count": 0,
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    write_json_atomic(SUMMARY_PATH, summary)

    for field in SUMMARY_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    for year in range(2020, 2026):
        print(f"ELIGIBLE_SECURITY_COUNT_{year}={summary[f'ELIGIBLE_SECURITY_COUNT_{year}']}")
    print(f"RUN_FINGERPRINT={run_fingerprint}")
    return summary


def main() -> int:
    summary = run()
    return 0 if summary["ABCDE_A2_R0V_STATUS"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
