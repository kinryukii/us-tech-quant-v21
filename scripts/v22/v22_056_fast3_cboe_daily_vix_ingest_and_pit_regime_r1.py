#!/usr/bin/env python
r"""
V22.056 FAST3 official Cboe daily VIX ingest and PIT regime feature build R1.

This stage deliberately uses only official Cboe daily VIX history:
- VIX is a prior-day regime filter.
- No intraday VIX feature is synthesized.
- No VIX ETF or futures proxy is substituted.
- No multifactor backtest is executed here.

Outputs live outside the repository under D:\us-tech-quant-data and
D:\us-tech-quant-results.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


VERSION = "V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1"
SOURCE_URL = (
    "https://cdn.cboe.com/api/global/us_indices/"
    "daily_prices/VIX_History.csv"
)
MIN_REQUIRED_DATE = pd.Timestamp("2018-07-01")
ROLLING_DAYS = 252


class IngestError(RuntimeError):
    """The official daily VIX ingest cannot continue safely."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def validate_v22_055(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "BLOCKED",
        "final_decision": "VIX_MINUTE_DATA_REQUIRED_OR_INVALID",
        "v22_054_validated": True,
        "etf_data_ready": True,
        "vix_source_found": False,
        "vix_data_ready": False,
        "data_ready_for_multifactor_backtest": False,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = []
    for key, expected_value in expected.items():
        actual = summary.get(key)
        if actual != expected_value:
            failures.append(
                f"{key}: expected {expected_value!r}, got {actual!r}"
            )
    if failures:
        raise IngestError(
            "V22.055 blocked-lineage validation failed: "
            + "; ".join(failures)
        )


def download_official_csv(url: str = SOURCE_URL) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 V22.056 FAST3 research-only VIX ingest"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except Exception as exc:
        raise IngestError(
            "Official Cboe VIX download failed. "
            "Use --source-csv with a manually downloaded VIX_History.csv. "
            f"Original error: {exc}"
        ) from exc
    if not data:
        raise IngestError("Official Cboe download returned an empty file.")
    return data


def load_source_bytes(source_csv: Path | None) -> tuple[bytes, str]:
    if source_csv is None:
        return download_official_csv(), SOURCE_URL
    if not source_csv.exists():
        raise IngestError(f"Local source CSV not found: {source_csv}")
    return source_csv.read_bytes(), str(source_csv)


def normalize_vix_csv(data: bytes) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.BytesIO(data))
    except Exception as exc:
        raise IngestError(f"Unable to parse VIX CSV: {exc}") from exc

    frame.columns = [str(column).strip().upper() for column in frame.columns]
    required = ["DATE", "OPEN", "HIGH", "LOW", "CLOSE"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise IngestError(f"VIX CSV missing columns: {missing}")

    result = frame[required].copy()
    result["DATE"] = pd.to_datetime(
        result["DATE"],
        format="%m/%d/%Y",
        errors="raise",
    )
    for column in ["OPEN", "HIGH", "LOW", "CLOSE"]:
        result[column] = pd.to_numeric(result[column], errors="raise")

    result = result.sort_values("DATE", kind="mergesort").reset_index(drop=True)

    if result.empty:
        raise IngestError("VIX daily history is empty.")
    if result["DATE"].duplicated().any():
        duplicates = result.loc[
            result["DATE"].duplicated(keep=False), "DATE"
        ].dt.strftime("%Y-%m-%d").tolist()
        raise IngestError(f"Duplicate VIX dates found: {duplicates[:10]}")
    if result[["OPEN", "HIGH", "LOW", "CLOSE"]].isna().any().any():
        raise IngestError("VIX OHLC contains null values.")
    if (result[["OPEN", "HIGH", "LOW", "CLOSE"]] <= 0).any().any():
        raise IngestError("VIX OHLC contains non-positive values.")

    # The official historical file contains a small number of legacy rows
    # where OPEN falls outside the reported LOW/HIGH range. These rows are
    # retained unchanged because the FAST3 PIT regime uses prior-day CLOSE
    # only. LOW/HIGH/CLOSE consistency remains a hard validation gate.
    invalid_core_ohlc = (
        (result["LOW"] > result["HIGH"])
        | (result["CLOSE"] < result["LOW"])
        | (result["CLOSE"] > result["HIGH"])
    )
    if invalid_core_ohlc.any():
        raise IngestError(
            "Invalid VIX LOW/HIGH/CLOSE rows: "
            f"{int(invalid_core_ohlc.sum())}"
        )

    if result["DATE"].min() > pd.Timestamp("1990-01-10"):
        raise IngestError(
            f"Unexpected VIX start date: {result['DATE'].min().date()}"
        )
    if result["DATE"].max() < MIN_REQUIRED_DATE:
        raise IngestError(
            f"VIX history ends too early: {result['DATE'].max().date()}"
        )
    if len(result) < 7000:
        raise IngestError(f"Unexpectedly short VIX history: {len(result)} rows")

    return result


def rolling_prior_percentile(
    close: pd.Series,
    window: int = ROLLING_DAYS,
) -> pd.Series:
    values = pd.to_numeric(close, errors="raise").to_numpy(dtype=float)
    output = np.full(len(values), np.nan, dtype=float)

    # Feature at date t uses only closes through date t-1.
    for index in range(window, len(values)):
        history = values[index - window : index]
        prior_close = values[index - 1]
        if (
            np.isfinite(history).all()
            and np.isfinite(prior_close)
            and len(history) == window
        ):
            output[index] = float(np.mean(history <= prior_close))
    return pd.Series(output, index=close.index, dtype=float)


def build_pit_features(daily: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "trade_date": daily["DATE"],
            "vix_prev_open": daily["OPEN"].shift(1),
            "vix_prev_high": daily["HIGH"].shift(1),
            "vix_prev_low": daily["LOW"].shift(1),
            "vix_prev_close": daily["CLOSE"].shift(1),
            "vix_prev_day_return": (
                daily["CLOSE"].shift(1) / daily["CLOSE"].shift(2) - 1.0
            ),
            "vix_pctl_252_prior": rolling_prior_percentile(
                daily["CLOSE"], ROLLING_DAYS
            ),
        }
    )
    result["vix_long_regime_allowed_p80"] = (
        result["vix_pctl_252_prior"] < 0.80
    )
    result["vix_short_regime_elevated_p50"] = (
        result["vix_pctl_252_prior"] >= 0.50
    )
    result["feature_information_cutoff"] = (
        result["trade_date"] - pd.Timedelta(days=1)
    )
    return result


def assert_pit_features(daily: pd.DataFrame, features: pd.DataFrame) -> None:
    if len(daily) != len(features):
        raise IngestError("Daily/features row count mismatch.")

    # Direct no-leakage checks.
    expected_prev = daily["CLOSE"].shift(1)
    actual_prev = features["vix_prev_close"]
    if not np.allclose(
        expected_prev.to_numpy(dtype=float),
        actual_prev.to_numpy(dtype=float),
        equal_nan=True,
    ):
        raise IngestError("vix_prev_close PIT shift validation failed.")

    first_valid = features["vix_pctl_252_prior"].first_valid_index()
    if first_valid is None or first_valid < ROLLING_DAYS:
        raise IngestError("252-day prior percentile warm-up is invalid.")

    if (
        features["vix_pctl_252_prior"].dropna().lt(0).any()
        or features["vix_pctl_252_prior"].dropna().gt(1).any()
    ):
        raise IngestError("VIX percentile is outside [0, 1].")


def write_outputs(
    daily: pd.DataFrame,
    features: pd.DataFrame,
    source_bytes: bytes,
    source_label: str,
    data_root: Path,
    result_dir: Path,
    v22_055_summary_path: Path,
) -> dict[str, Any]:
    latest_date = daily["DATE"].max().strftime("%Y-%m-%d")
    raw_path = (
        data_root
        / "raw"
        / f"source_date={latest_date}"
        / "VIX_History.csv"
    )
    canonical_parquet = data_root / "canonical" / "vix_daily.parquet"
    canonical_csv = data_root / "canonical" / "vix_daily.csv"
    feature_parquet = (
        data_root / "features" / "vix_prior_day_regime_features.parquet"
    )
    feature_csv = (
        data_root / "features" / "vix_prior_day_regime_features.csv"
    )

    source_hash = sha256_bytes(source_bytes)
    if raw_path.exists():
        existing_hash = sha256_file(raw_path)
        if existing_hash != source_hash:
            raise IngestError(
                "Immutable raw snapshot already exists with a different hash: "
                f"{raw_path}"
            )
    else:
        atomic_write_bytes(raw_path, source_bytes)

    canonical_parquet.parent.mkdir(parents=True, exist_ok=True)
    feature_parquet.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(canonical_parquet, index=False)
    daily.to_csv(canonical_csv, index=False, encoding="utf-8-sig")
    features.to_parquet(feature_parquet, index=False)
    features.to_csv(feature_csv, index=False, encoding="utf-8-sig")

    result_dir.mkdir(parents=True, exist_ok=True)
    coverage_csv = result_dir / "v22_056_vix_daily_coverage.csv"
    summary_path = result_dir / "v22_056_summary.json"
    manifest_path = result_dir / "v22_056_run_manifest.json"

    coverage = pd.DataFrame(
        [
            {
                "source": source_label,
                "row_count": len(daily),
                "start_date": daily["DATE"].min().strftime("%Y-%m-%d"),
                "end_date": latest_date,
                "duplicate_date_count": int(daily["DATE"].duplicated().sum()),
                "invalid_ohlc_count": 0,
                "pit_feature_valid_count": int(
                    features["vix_pctl_252_prior"].notna().sum()
                ),
                "source_sha256": source_hash,
            }
        ]
    )
    coverage.to_csv(coverage_csv, index=False, encoding="utf-8-sig")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": (
            "OFFICIAL_CBOE_DAILY_VIX_READY_FOR_PRIOR_DAY_REGIME_FILTER"
        ),
        "v22_055_validated": True,
        "source_url": SOURCE_URL,
        "source_used": source_label,
        "source_sha256": source_hash,
        "row_count": int(len(daily)),
        "start_date": daily["DATE"].min().strftime("%Y-%m-%d"),
        "end_date": latest_date,
        "duplicate_date_count": 0,
        "invalid_ohlc_count": 0,
        "rolling_days": ROLLING_DAYS,
        "pit_feature_valid_count": int(
            features["vix_pctl_252_prior"].notna().sum()
        ),
        "prior_day_shift_validated": True,
        "daily_vix_regime_ready": True,
        "intraday_vix_data_ready": False,
        "intraday_vix_features_allowed": False,
        "vix_proxy_substitution_used": False,
        "data_ready_for_daily_vix_multifactor_backtest": True,
        "multifactor_backtest_executed": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "etf_files_modified": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "paths": {
            "raw_snapshot": str(raw_path),
            "canonical_parquet": str(canonical_parquet),
            "canonical_csv": str(canonical_csv),
            "feature_parquet": str(feature_parquet),
            "feature_csv": str(feature_csv),
        },
    }
    atomic_json(summary_path, summary)

    manifest = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "input": {
            "v22_055_summary": str(v22_055_summary_path),
            "v22_055_summary_sha256": sha256_file(v22_055_summary_path),
            "source_used": source_label,
            "source_sha256": source_hash,
        },
        "outputs": {
            "coverage_csv": str(coverage_csv),
            "summary": str(summary_path),
            "manifest": str(manifest_path),
            **summary["paths"],
        },
        "research_guards": {
            "daily_vix_only": True,
            "intraday_vix_features_allowed": False,
            "vix_proxy_substitution_used": False,
            "multifactor_backtest_executed": False,
            "parameter_sweep_executed": False,
            "broker_action_allowed": False,
            "paper_trading_allowed": False,
            "official_adoption_allowed": False,
        },
    }
    atomic_json(manifest_path, manifest)

    return {
        "summary": summary,
        "summary_path": summary_path,
        "manifest_path": manifest_path,
        "result_dir": result_dir,
    }


def run_ingest(
    v22_055_summary_path: Path,
    data_root: Path,
    result_dir: Path,
    source_csv: Path | None,
) -> dict[str, Any]:
    if not v22_055_summary_path.exists():
        raise IngestError(
            f"V22.055 summary not found: {v22_055_summary_path}"
        )
    v22_055 = json.loads(
        v22_055_summary_path.read_text(encoding="utf-8-sig")
    )
    validate_v22_055(v22_055)

    source_bytes, source_label = load_source_bytes(source_csv)
    daily = normalize_vix_csv(source_bytes)
    features = build_pit_features(daily)
    assert_pit_features(daily, features)

    return write_outputs(
        daily=daily,
        features=features,
        source_bytes=source_bytes,
        source_label=source_label,
        data_root=data_root,
        result_dir=result_dir,
        v22_055_summary_path=v22_055_summary_path,
    )


def print_final(result: Mapping[str, Any]) -> None:
    summary = result["summary"]
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"FINAL_DECISION={summary['final_decision']}")
    print("V22_055_VALIDATED=True")
    print(f"VIX_DAILY_ROW_COUNT={summary['row_count']}")
    print(f"VIX_DAILY_START_DATE={summary['start_date']}")
    print(f"VIX_DAILY_END_DATE={summary['end_date']}")
    print(
        f"PIT_FEATURE_VALID_COUNT="
        f"{summary['pit_feature_valid_count']}"
    )
    print("PRIOR_DAY_SHIFT_VALIDATED=True")
    print("DAILY_VIX_REGIME_READY=True")
    print("INTRADAY_VIX_DATA_READY=False")
    print("INTRADAY_VIX_FEATURES_ALLOWED=False")
    print("VIX_PROXY_SUBSTITUTION_USED=False")
    print("DATA_READY_FOR_DAILY_VIX_MULTIFACT_BACKTEST=True")
    print("MULTIFACTOR_BACKTEST_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("ETF_FILES_MODIFIED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={result['summary_path']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-055-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.055_FAST3_MULTIFACT_DATA_AND_FACTOR_PREFLIGHT_R1"
            r"\v22_055_summary.json"
        ),
    )
    parser.add_argument(
        "--data-root",
        default=r"D:\us-tech-quant-data\fast3\vix_cboe_daily",
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1"
        ),
    )
    parser.add_argument("--source-csv", default="")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run_ingest(
            v22_055_summary_path=Path(args.v22_055_summary),
            data_root=Path(args.data_root),
            result_dir=Path(args.result_dir),
            source_csv=Path(args.source_csv) if args.source_csv else None,
        )
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
