from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


RUN_ID = "A2_PIT_MOOMOO_CURRENT_WEEK_COMPLETION_R1"
REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
WORK = Path(r"D:\us-tech-quant-cache\a2_pit_moomoo_current_week_completion_r1")
FINAL = RESULTS / RUN_ID
HISTORY = WORK / "merged_history"
INTERVAL_DATA = WORK / "interval_data"
PIT_ROOT = RESULTS / "A2_PIT13F_MATERIALIZATION_R1"
PRIOR_ROOT = RESULTS / "A2_PIT_DATA_COVERAGE_R1"
PRIOR_MAX = RESULTS / "A2_PIT_MOOMOO_MAX_BACKFILL_R1"
PRICE_ROOT = DATA / "moomoo/source/prices_qfq"
FETCH_SOURCE = REPO / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"
A2_SOURCE = REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
COVERAGE_SOURCE = PRIOR_ROOT / "run_coverage.py"
FEATURE_CONTRACT = RESULTS / "ABCDE_A2_R1C_EXECUTION_CONTRACT_FREEZE_R1/a2_r1_feature_equation_contract.json"
INTERVALS_SOURCE = PIT_ROOT / "effective_universe_intervals.parquet"
IDENTITY_SOURCE = PIT_ROOT / "identity_coverage.csv"
PRIOR_BACKFILL = PRIOR_ROOT / "market_data_backfill_manifest.json"
PRIOR_FEATURES = PRIOR_ROOT / "pit_feature_rows.parquet"
FIXED_CUTOFF = pd.Timestamp("2026-08-18")
GLOBAL_REQUIRED_START = pd.Timestamp("2019-01-01")
APPDATA = Path(r"D:\us-tech-quant-cache\moomoo_sdk_appdata")
TERMINAL = {
    "COMPLETE_TO_FIXED_CUTOFF", "PARTIAL_MISSING_HISTORY", "EMPTY_RESPONSE_CONFIRMED",
    "UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY", "UNSUPPORTED_OTC",
    "INVALID_HISTORICAL_MAPPING", "OTHER_HARD_FAILURE",
}
FEATURES = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d",
    "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
)
QUOTA_FIELDS = [
    "quota_security_id", "moomoo_code", "provider_name", "quota_request_time",
    "ticker", "pit_security_ids", "pit_member", "mapping_status", "required_history_start",
    "fixed_backfill_cutoff_date", "membership_source", "membership_observed_utc",
]
STATUS_FIELDS = [
    "quota_security_id", "moomoo_code", "ticker", "pit_security_ids", "required_history_start",
    "fixed_backfill_cutoff_date", "status", "local_row_count_before", "final_row_count",
    "first_history_date", "last_history_date", "planned_interval_count", "attempted_interval_count",
    "successful_interval_count", "empty_interval_count", "continuity_gap_count", "request_count",
    "error_code", "error_message", "history_path", "history_sha256", "updated_utc",
]
INTERVAL_FIELDS = [
    "quota_security_id", "moomoo_code", "ticker", "interval_start", "interval_end", "status",
    "attempt_count", "request_count", "row_count", "first_date", "last_date", "data_path",
    "data_sha256", "error_code", "error_message", "updated_utc",
]

# The legacy V11 mapping treated GE's temporary 2024 ex-distribution
# when-issued symbol as the permanent security symbol.  Keep the immutable PIT
# source intact and correct the transport identity at the existing mapping
# boundary.  CUSIP 369604103 is the pre-2021 reverse-split identity and
# 369604301 is the current identity; both trade through the regular-way GE
# history rather than GE.WI.
SECURITY_IDENTITY_OVERRIDES = {
    "369604103": {"ticker": "GE", "moomoo_transport_code": "US.GE"},
    "369604301": {"ticker": "GE", "moomoo_transport_code": "US.GE"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_read(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def csv_write(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(list(rows), columns=fields).to_csv(tmp, index=False, lineterminator="\n")
    os.replace(tmp, path)


def import_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def safe_key(code: str) -> str:
    label = re.sub(r"[^A-Z0-9_-]+", "_", code.upper())[:32]
    return f"{label}_{hashlib.sha256(code.encode()).hexdigest()[:12]}"


def history_path(code: str) -> Path:
    return HISTORY / f"{safe_key(code)}.parquet"


def interval_path(code: str, start: str, end: str) -> Path:
    token = hashlib.sha256(f"{code}|{start}|{end}|QFQ".encode()).hexdigest()[:16]
    return INTERVAL_DATA / f"{safe_key(code)}_{token}.parquet"


def apply_security_identity_overrides(intervals: pd.DataFrame) -> pd.DataFrame:
    """Correct verified CUSIP identities without mutating frozen inputs."""
    out = intervals.copy()
    security_ids = out.security_id.fillna("").astype(str)
    for security_id, identity in SECURITY_IDENTITY_OVERRIDES.items():
        mask = security_ids.eq(security_id)
        out.loc[mask, "ticker"] = identity["ticker"]
        out.loc[mask, "moomoo_transport_code"] = identity["moomoo_transport_code"]
        if "mapping_status" in out:
            out.loc[mask, "mapping_status"] = "RESOLVED"
        if "mapping_source" in out:
            out.loc[mask, "mapping_source"] = "A2_CUSIP_IDENTITY_OVERRIDE_R1"
        if "mapping_confidence" in out:
            out.loc[mask, "mapping_confidence"] = "CUSIP_VERIFIED"
    return out


def normalize_frame(frame: pd.DataFrame, ticker: str, code: str, origin: str) -> pd.DataFrame:
    columns = ["ticker", "moomoo_code", "date", "open", "high", "low", "close", "volume", "turnover", "adjustment", "source", "origin"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    out = frame.copy()
    if "trade_date" in out.columns and "date" not in out.columns:
        out = out.rename(columns={"trade_date": "date"})
    if "moomoo_symbol" in out.columns and "moomoo_code" not in out.columns:
        out = out.rename(columns={"moomoo_symbol": "moomoo_code"})
    out["ticker"] = ticker
    out["moomoo_code"] = code
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for name in ("open", "high", "low", "close", "volume", "turnover"):
        if name not in out:
            out[name] = np.nan
        out[name] = pd.to_numeric(out[name], errors="coerce")
    out["adjustment"] = "qfq"
    out["source"] = "MOOMOO_OPEND"
    out["origin"] = origin
    out = out.loc[(out.date >= GLOBAL_REQUIRED_START) & (out.date <= FIXED_CUTOFF), columns]
    out = out.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    valid = out[["open", "high", "low", "close"]].notna().all(axis=1)
    valid &= (out[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid &= out.volume.notna() & (out.volume >= 0)
    require(bool(valid.all()), f"INVALID_OHLCV:{code}:{origin}")
    require(not out.date.duplicated().any(), f"DUPLICATE_DATES:{code}:{origin}")
    return out.reset_index(drop=True)


def load_mapping() -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    intervals = pd.read_parquet(INTERVALS_SOURCE)
    intervals["ticker"] = intervals.ticker.fillna("").astype(str).str.upper()
    intervals["moomoo_transport_code"] = intervals.moomoo_transport_code.fillna("").astype(str)
    intervals["security_id"] = intervals.security_id.fillna("").astype(str)
    intervals = apply_security_identity_overrides(intervals)
    mapped: dict[str, dict[str, Any]] = {}
    for code, group in intervals.loc[intervals.moomoo_transport_code.ne("")].groupby("moomoo_transport_code"):
        tickers = sorted(set(group.ticker) - {""})
        ids = sorted(set(group.security_id) - {""})
        earliest = pd.to_datetime(group.effective_start).min() - pd.Timedelta(days=220)
        mapped[str(code)] = {
            "tickers": tickers, "security_ids": ids,
            "required_start": max(GLOBAL_REQUIRED_START, earliest).normalize(),
        }
    return intervals, mapped


def quota_detail() -> tuple[int, int, list[dict[str, Any]]]:
    os.environ["APPDATA"] = str(APPDATA)
    import moomoo
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        ret, payload = context.get_history_kl_quota(get_detail=True)
    finally:
        context.close()
    require(ret == moomoo.RET_OK, f"QUOTA_DETAIL_FAILED:{payload}")
    used, remain, detail = payload
    require(isinstance(detail, list), "QUOTA_DETAIL_NOT_LIST")
    return int(used), int(remain), detail


def initialize() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)
    INTERVAL_DATA.mkdir(parents=True, exist_ok=True)
    manifest_path = WORK / "current_week_quota_set.csv"
    if manifest_path.is_file():
        frame = pd.read_csv(manifest_path, dtype=str).fillna("")
        require(len(frame) == 1000 and frame.moomoo_code.nunique() == 1000, "WORKING_QUOTA_SET_INVALID")
        require(frame.fixed_backfill_cutoff_date.eq(str(FIXED_CUTOFF.date())).all(), "FIXED_CUTOFF_CHANGED")
        return
    used, remain, detail = quota_detail()
    require(used == 1000 and remain == 0 and len(detail) == 1000, f"CURRENT_WEEK_QUOTA_COUNT_NOT_1000:{used}:{remain}:{len(detail)}")
    codes = [str(row.get("code", "")) for row in detail]
    require(all(code.startswith("US.") for code in codes), "NON_US_QUOTA_MEMBER")
    require(len(set(codes)) == 1000, "QUOTA_DETAIL_DUPLICATE_CODE")
    _, mapped = load_mapping()
    observed = utc_now()
    rows = []
    for item in sorted(detail, key=lambda x: str(x.get("code", ""))):
        code = str(item["code"])
        info = mapped.get(code)
        tickers = [] if info is None else info["tickers"]
        ticker = tickers[0] if len(tickers) == 1 else code.split(".", 1)[1]
        status = "NOT_IN_FROZEN_A2_UNIVERSE" if info is None else ("RESOLVED" if len(tickers) == 1 else "AMBIGUOUS_TICKER")
        required_start = GLOBAL_REQUIRED_START if info is None else info["required_start"]
        rows.append({
            "quota_security_id": code, "moomoo_code": code, "provider_name": str(item.get("name", "")),
            "quota_request_time": str(item.get("request_time", "")), "ticker": ticker,
            "pit_security_ids": "|".join([] if info is None else info["security_ids"]),
            "pit_member": info is not None, "mapping_status": status,
            "required_history_start": str(pd.Timestamp(required_start).date()),
            "fixed_backfill_cutoff_date": str(FIXED_CUTOFF.date()),
            "membership_source": "MOOMOO_GET_HISTORY_KL_QUOTA_DETAIL", "membership_observed_utc": observed,
        })
    csv_write(manifest_path, rows, QUOTA_FIELDS)
    json_write(WORK / "fixed_backfill_cutoff.json", {
        "run_id": RUN_ID, "fixed_backfill_cutoff_date": str(FIXED_CUTOFF.date()),
        "resolution": "Latest fully completed XNYS trading date at task initialization",
        "initialization_market_state": "2026-08-19 XNYS regular session had not closed in Asia/Tokyo at task initialization",
        "do_not_advance": True, "max_required_lookback_trading_days": 120,
        "max_required_observations": 121, "global_non_a2_history_floor": str(GLOBAL_REQUIRED_START.date()),
        "quota_used": used, "quota_remaining": remain, "quota_security_count": len(rows),
        "quota_manifest_sha256": sha256(manifest_path), "created_utc": observed,
    })
    csv_write(WORK / "working_completion_state.csv", [], STATUS_FIELDS)
    csv_write(WORK / "completed_intervals.csv", [], INTERVAL_FIELDS)
    csv_write(WORK / "remaining_intervals.csv", [], INTERVAL_FIELDS)
    json_write(WORK / "request_audit.json", {"requests": [], "new_unique_security_request_count": 0})
    print("CURRENT_WEEK_QUOTA_SECURITY_COUNT=1000", flush=True)
    print(f"FIXED_BACKFILL_CUTOFF_DATE={FIXED_CUTOFF.date()}", flush=True)


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def prior_leg_index() -> dict[str, list[dict[str, Any]]]:
    payload = json_read(PRIOR_BACKFILL)
    result: dict[str, list[dict[str, Any]]] = {}
    for leg in payload.get("legs", []):
        if leg.get("status") == "PASS" and leg.get("raw_cache_path") and leg.get("raw_cache_sha256"):
            result.setdefault(str(leg.get("moomoo_symbol", "")), []).append(leg)
    return result


def prior_otc_set() -> set[str]:
    if not (PRIOR_MAX / "hard_failure_manifest.csv").is_file():
        return set()
    frame = pd.read_csv(PRIOR_MAX / "hard_failure_manifest.csv", dtype=str).fillna("")
    return set(frame.loc[frame.request_status.eq("UNSUPPORTED_OTC"), "moomoo_code"])


def canonical_prices(wanted: set[str]) -> dict[str, pd.DataFrame]:
    pieces = []
    for year in range(2019, 2027):
        path = PRICE_ROOT / f"year={year}/prices.parquet"
        if not path.is_file():
            continue
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "high", "low", "close", "volume", "turnover"])
        part["ticker"] = part.ticker.astype(str).str.upper()
        part = part.loc[part.ticker.isin(wanted)]
        if len(part):
            pieces.append(part)
    if not pieces:
        return {}
    all_rows = pd.concat(pieces, ignore_index=True)
    return {ticker: group.copy() for ticker, group in all_rows.groupby("ticker", sort=False)}


def local_history(member: dict[str, Any], canonical: dict[str, pd.DataFrame], prior: dict[str, list[dict[str, Any]]]) -> pd.DataFrame:
    code, ticker = member["moomoo_code"], member["ticker"]
    frames: list[pd.DataFrame] = []
    if ticker in canonical:
        frames.append(normalize_frame(canonical[ticker], ticker, code, "CANONICAL_READ_ONLY"))
    for leg in prior.get(code, []):
        path = Path(leg["raw_cache_path"])
        if path.is_file() and sha256(path) == leg["raw_cache_sha256"]:
            frames.append(normalize_frame(pd.read_parquet(path), ticker, code, "A2_PIT_DATA_COVERAGE_R1_VALIDATED"))
    working = history_path(code)
    if working.is_file():
        frames.append(normalize_frame(pd.read_parquet(working), ticker, code, "CURRENT_WEEK_WORKING_CACHE"))
    # Interval files are promoted before the interval checkpoint.  Loading
    # them here makes a crash between interval success and security merge
    # resume without refetching that validated range.
    for path in sorted(INTERVAL_DATA.glob(f"{safe_key(code)}_*.parquet")):
        frames.append(normalize_frame(pd.read_parquet(path), ticker, code, "CURRENT_WEEK_INTERVAL_CACHE"))
    if not frames:
        return normalize_frame(pd.DataFrame(), ticker, code, "NONE")
    merged = pd.concat(frames, ignore_index=True)
    priority = {
        "CANONICAL_READ_ONLY": 0, "A2_PIT_DATA_COVERAGE_R1_VALIDATED": 1,
        "CURRENT_WEEK_WORKING_CACHE": 2, "CURRENT_WEEK_INTERVAL_CACHE": 3,
    }
    merged["priority"] = merged.origin.map(priority).fillna(0)
    merged = merged.sort_values(["date", "priority"], kind="mergesort").drop_duplicates("date", keep="last").drop(columns="priority")
    return normalize_frame(merged, ticker, code, "MERGED_LOCAL_VALIDATED")


def asof_history_window(
    frame: pd.DataFrame,
    as_of_date: str | pd.Timestamp | None,
    *,
    date_column: str = "date",
    current_mode: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return the only rows an historical readiness decision may observe.

    Historical callers must provide ``as_of_date``.  ``current_mode`` is an
    explicit compatibility path for operational callers that intentionally
    use all currently available rows; it is never an implicit fallback.
    """
    if date_column not in frame.columns:
        raise RuntimeError(f"ASOF_DATE_COLUMN_MISSING:{date_column}")
    if as_of_date is None and not current_mode:
        raise RuntimeError("ASOF_DATE_REQUIRED_FOR_HISTORICAL_READINESS")
    result = frame.copy()
    parsed = pd.to_datetime(result[date_column], errors="coerce").dt.normalize()
    invalid_date_count = int(parsed.isna().sum())
    result[date_column] = parsed
    local_latest = "" if parsed.dropna().empty else str(parsed.max().date())
    if current_mode:
        used = result.loc[parsed.notna()].copy()
        effective_as_of = local_latest
    else:
        target = pd.Timestamp(as_of_date).normalize()
        used = result.loc[parsed.notna() & parsed.le(target)].copy()
        effective_as_of = str(target.date())
    used = used.sort_values(date_column, kind="stable").reset_index(drop=True)
    max_used = "" if used.empty else str(used[date_column].max().date())
    return used, {
        "as_of_date": effective_as_of,
        "current_mode": bool(current_mode),
        "local_latest_date": local_latest,
        "local_data_extends_beyond_asof": bool(not current_mode and local_latest and local_latest > effective_as_of),
        "asof_rows_used_max_date": max_used,
        "invalid_date_count": invalid_date_count,
    }


def asof_feature_readiness(
    frame: pd.DataFrame,
    as_of_date: str | pd.Timestamp | None,
    *,
    required_observations: int = 121,
    date_column: str = "date",
    current_mode: bool = False,
) -> dict[str, Any]:
    """Evaluate the frozen price/volume warmup after the as-of mask."""
    used, audit = asof_history_window(
        frame, as_of_date, date_column=date_column, current_mode=current_mode,
    )
    required_fields = {"close", "volume"}
    missing = sorted(required_fields - set(used.columns))
    if missing:
        raise RuntimeError(f"FEATURE_INPUT_FIELDS_MISSING:{','.join(missing)}")
    numeric = used[["close", "volume"]].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(numeric).all(axis=1) & numeric.close.gt(0) & numeric.volume.ge(0)
    valid_dates = used.loc[valid, date_column].drop_duplicates()
    observation_count = int(valid_dates.nunique())
    audit.update({
        "required_observations": int(required_observations),
        "observation_count_asof": observation_count,
        "feature_input_max_date": "" if valid_dates.empty else str(valid_dates.max().date()),
        "model_safe": observation_count >= int(required_observations),
    })
    return audit


def authoritative_model_safe_coverage(
    raw: pd.DataFrame,
    qfq: pd.DataFrame,
    required_tickers: Iterable[str],
    as_of_date: str | pd.Timestamp | None,
    *,
    required_observations: int = 121,
) -> dict[str, Any]:
    """Compute target-date coverage without consulting post-target rows."""
    required = sorted({str(ticker).strip().upper() for ticker in required_tickers if str(ticker).strip()})
    raw_used, raw_audit = asof_history_window(raw, as_of_date)
    qfq_used, qfq_audit = asof_history_window(qfq, as_of_date)
    raw_used["_coverage_ticker"] = raw_used.ticker.astype(str).str.upper()
    qfq_used["_coverage_ticker"] = qfq_used.ticker.astype(str).str.upper()
    raw_groups = {ticker: group for ticker, group in raw_used.groupby("_coverage_ticker", sort=False)}
    qfq_groups = {ticker: group for ticker, group in qfq_used.groupby("_coverage_ticker", sort=False)}
    target = str(pd.Timestamp(as_of_date).date())
    results: list[dict[str, Any]] = []
    for ticker in required:
        r = raw_groups.get(ticker, raw_used.iloc[0:0])
        q = qfq_groups.get(ticker, qfq_used.iloc[0:0])
        r_target = r.loc[r.date.eq(pd.Timestamp(target))]
        q_target = q.loc[q.date.eq(pd.Timestamp(target))]
        feature = asof_feature_readiness(q, target, required_observations=required_observations)
        raw_target_ready = len(r_target) == 1
        qfq_target_ready = len(q_target) == 1
        model_safe = raw_target_ready and qfq_target_ready and bool(feature["model_safe"])
        results.append({
            "ticker": ticker,
            "as_of_date": target,
            "raw_target_ready": raw_target_ready,
            "qfq_target_ready": qfq_target_ready,
            "observation_count_asof": feature["observation_count_asof"],
            "max_used_date": feature["asof_rows_used_max_date"],
            "local_data_extends_beyond_asof": feature["local_data_extends_beyond_asof"],
            "model_safe": model_safe,
        })
    safe = sorted(row["ticker"] for row in results if row["model_safe"])
    max_dates = [value for value in (raw_audit["asof_rows_used_max_date"], qfq_audit["asof_rows_used_max_date"]) if value]
    return {
        "as_of_date": target,
        "required_count": len(required),
        "model_safe_count": len(safe),
        "model_safe_tickers": safe,
        "rows": results,
        "max_used_date": max(max_dates, default=""),
        "local_data_extends_beyond_asof": bool(raw_audit["local_data_extends_beyond_asof"] or qfq_audit["local_data_extends_beyond_asof"]),
        "raw_qfq_asof_guard": True,
        "feature_input_asof_guard": True,
        "observation_count_asof_guard": True,
    }


def frozen_queue_security_id_hash(rows: Iterable[dict[str, Any]]) -> str:
    identities = sorted(str(row["security_id"]).strip() for row in rows)
    return hashlib.sha256(("\n".join(identities) + "\n").encode("utf-8")).hexdigest()


def load_frozen_backfill_queue(
    queue_path: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Validate a frozen queue before a future runner constructs API work."""
    require(bool(expected_manifest_sha256), "QUEUE_MANIFEST_EXPECTED_HASH_REQUIRED")
    require(sha256(manifest_path) == expected_manifest_sha256, "QUEUE_MANIFEST_HASH_MISMATCH")
    manifest = json_read(manifest_path)
    require(sha256(queue_path) == manifest.get("queue_file_sha256"), "QUEUE_FILE_HASH_MISMATCH")
    rows = pd.read_csv(queue_path, dtype=str).fillna("").to_dict("records")
    required_fields = {"security_id", "symbol", "moomoo_code", "fetch_priority", "queue_reason"}
    require(all(required_fields <= set(row) for row in rows), "QUEUE_SCHEMA_MISMATCH")
    require(len(rows) == int(manifest.get("queue_count", -1)), "QUEUE_COUNT_MISMATCH")
    require(len({row["security_id"] for row in rows}) == len(rows), "QUEUE_SECURITY_ID_DUPLICATE")
    require(frozen_queue_security_id_hash(rows) == manifest.get("security_id_set_sha256"), "QUEUE_SECURITY_ID_SET_HASH_MISMATCH")
    priority = {"P0_MINIMAL_GAP": 0, "P1_PARTIAL_HISTORY": 1, "P2_FULL_HISTORY": 2}
    require(all(row["fetch_priority"] in priority for row in rows), "QUEUE_PRIORITY_INVALID")
    expected_order = sorted(rows, key=lambda row: (priority[row["fetch_priority"]], row["security_id"]))
    require(rows == expected_order, "QUEUE_ORDER_NOT_DETERMINISTIC")
    require(all(row["queue_reason"] == "FAIL_MOOMOO_WEEKLY_QUOTA_DEFERRED" for row in rows), "QUEUE_REASON_NOT_QUOTA_DEFERRED")
    return {
        "status": "PASS",
        "queue_count": len(rows),
        "execution_order": [row["security_id"] for row in rows],
        "moomoo_api_request_count": 0,
        "rows": rows,
    }


def planned_ranges(member: dict[str, Any], frame: pd.DataFrame) -> list[tuple[str, str]]:
    start = pd.Timestamp(member["required_history_start"])
    if frame.empty:
        return [(str(start.date()), str(FIXED_CUTOFF.date()))]
    dates = pd.to_datetime(frame.date)
    ranges: list[tuple[str, str]] = []
    if dates.min() > start:
        ranges.append((str(start.date()), str((dates.min() - pd.Timedelta(days=1)).date())))
    if dates.max() < FIXED_CUTOFF:
        ranges.append((str((dates.max() + pd.Timedelta(days=1)).date()), str(FIXED_CUTOFF.date())))
    return [(a, b) for a, b in ranges if pd.Timestamp(a) <= pd.Timestamp(b)]


def classify_error(message: str) -> str:
    text = (message or "").lower()
    if "otc" in text:
        return "UNSUPPORTED_OTC"
    if "unknown" in text or "未知股票" in text:
        return "UNKNOWN_SECURITY"
    if "unsupported" in text or "不支持" in text:
        return "UNSUPPORTED_SECURITY"
    if "1000/1000" in text or "quota" in text or "额度不足" in text:
        return "QUOTA_EXHAUSTED_FOR_MEMBER"
    return "TRANSIENT_FAILURE"


def fetch_interval(context: Any, moomoo: Any, limiter: Any, fetch_module: Any, member: dict[str, Any], start: str, end: str) -> tuple[pd.DataFrame, str, str, int, int]:
    allowed = set(pd.read_csv(WORK / "current_week_quota_set.csv", dtype=str).moomoo_code)
    code, ticker = member["moomoo_code"], member["ticker"]
    require(code in allowed, f"SECURITY_NOT_IN_CURRENT_WEEK_QUOTA_SET:{code}")
    audit = json_read(WORK / "request_audit.json", {"requests": [], "new_unique_security_request_count": 0})
    request_count = 0
    last_code = last_message = ""
    for attempt in range(3):
        page_key = None
        pages = []
        while True:
            require(code in allowed, f"PRE_REQUEST_MEMBERSHIP_GATE_FAILED:{code}")
            limiter.acquire({"ticker": ticker, "adjustment": "qfq", "frequency": "1d"})
            request_count += 1
            event = {"timestamp_utc": utc_now(), "moomoo_code": code, "ticker": ticker, "start": start, "end": end, "page": len(pages) + 1, "membership_gate": "PASS"}
            ret = context.request_history_kline(code, start=start, end=end, ktype=moomoo.KLType.K_DAY, autype=moomoo.AuType.QFQ, page_req_key=page_key)
            if not isinstance(ret, tuple) or ret[0] != moomoo.RET_OK:
                last_message = str(ret[1] if isinstance(ret, tuple) and len(ret) > 1 else ret)
                last_code = classify_error(last_message)
                event.update({"result": last_code, "error_message": last_message})
                audit["requests"].append(event)
                json_write(WORK / "request_audit.json", audit)
                break
            pages.append(ret[1])
            event.update({"result": "PASS", "rows": int(len(ret[1]))})
            audit["requests"].append(event)
            json_write(WORK / "request_audit.json", audit)
            page_key = ret[2] if len(ret) > 2 else None
            if not page_key:
                raw = pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
                frame = pd.DataFrame(fetch_module.normalize_records(raw, ticker, code, "US", "qfq", RUN_ID, utc_now()))
                return normalize_frame(frame, ticker, code, "CURRENT_WEEK_API"), "", "", attempt + 1, request_count
        if last_code in {"UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY", "UNSUPPORTED_OTC"}:
            break
        if attempt < 2:
            time.sleep(1.0 + attempt)
    return normalize_frame(pd.DataFrame(), ticker, code, "CURRENT_WEEK_API"), last_code, last_message, 3, request_count


def checkpoint(status_rows: list[dict[str, Any]], interval_rows: list[dict[str, Any]], members: list[dict[str, Any]]) -> None:
    by_code = {row["moomoo_code"]: row for row in status_rows}
    csv_write(WORK / "working_completion_state.csv", [by_code[k] for k in sorted(by_code)], STATUS_FIELDS)
    completed = [row for row in interval_rows if row["status"] != "PENDING"]
    csv_write(WORK / "completed_intervals.csv", completed, INTERVAL_FIELDS)
    pending: list[dict[str, Any]] = []
    for member in members:
        if member["moomoo_code"] in by_code:
            continue
        pending.append({
            "quota_security_id": member["quota_security_id"], "moomoo_code": member["moomoo_code"], "ticker": member["ticker"],
            "interval_start": member["required_history_start"], "interval_end": str(FIXED_CUTOFF.date()), "status": "PENDING",
            "attempt_count": 0, "request_count": 0, "row_count": 0, "first_date": "", "last_date": "", "data_path": "", "data_sha256": "",
            "error_code": "", "error_message": "", "updated_utc": utc_now(),
        })
    csv_write(WORK / "remaining_intervals.csv", pending, INTERVAL_FIELDS)
    json_write(WORK / "resume_state.json", {
        "run_id": RUN_ID, "checkpoint_utc": utc_now(), "quota_security_count": len(members),
        "terminal_security_count": len(by_code), "remaining_security_count": len(members) - len(by_code),
        "new_unique_security_request_count": int(json_read(WORK / "request_audit.json").get("new_unique_security_request_count", 0)),
        "restartable": True, "final_frozen": FINAL.is_dir(),
    })


def fetch_all() -> None:
    initialize()
    members = pd.read_csv(WORK / "current_week_quota_set.csv", dtype=str).fillna("").to_dict("records")
    require(len(members) == 1000, "CURRENT_WEEK_QUOTA_SECURITY_COUNT_NOT_1000")
    status_rows = read_rows(WORK / "working_completion_state.csv")
    interval_rows = read_rows(WORK / "completed_intervals.csv")
    # An empty requested prefix/suffix is authoritative confirmation that the
    # provider has no rows there (commonly pre-IPO, post-delisting, or a
    # holiday-only edge).  It is not missing history when valid rows exist in
    # the security's actual trading span.
    for row in status_rows:
        if row.get("status") == "PARTIAL_MISSING_HISTORY" and not row.get("error_code") and int(float(row.get("final_row_count") or 0)) > 0:
            row["status"] = "COMPLETE_TO_FIXED_CUTOFF"
    done = {row["moomoo_code"] for row in status_rows if row.get("status") in TERMINAL}
    _, mapping = load_mapping()
    ambiguous = {code for code, value in mapping.items() if len(value["tickers"]) != 1}
    prior = prior_leg_index()
    otc = prior_otc_set()
    canonical = canonical_prices({member["ticker"] for member in members})
    fetch_module = import_path("current_week_canonical_fetch", FETCH_SOURCE)
    os.environ["APPDATA"] = str(APPDATA)
    import moomoo
    limiter = fetch_module.HistoryKlineLimiter()
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        for number, member in enumerate(members, 1):
            code, ticker = member["moomoo_code"], member["ticker"]
            if code in done:
                continue
            before, _ = asof_history_window(
                local_history(member, canonical, prior),
                FIXED_CUTOFF,
            )
            initial_count = len(before)
            ranges = planned_ranges(member, before)
            new_frames: list[pd.DataFrame] = []
            security_intervals: list[dict[str, Any]] = []
            error_code = error_message = ""
            total_requests = 0
            if code in ambiguous:
                error_code = "AMBIGUOUS_FROZEN_A2_CODE_TO_TICKER"
                final_status = "INVALID_HISTORICAL_MAPPING"
            elif code in otc:
                error_code = "PRIOR_AUTHORITATIVE_UNSUPPORTED_OTC"
                final_status = "UNSUPPORTED_OTC"
            else:
                for start, end in ranges:
                    frame, code_error, message, attempts, requests = fetch_interval(context, moomoo, limiter, fetch_module, member, start, end)
                    total_requests += requests
                    path = interval_path(code, start, end)
                    if len(frame):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        frame.to_parquet(path, index=False)
                        new_frames.append(frame)
                        interval_status = "SUCCESS_VALIDATED"
                    elif code_error:
                        interval_status = code_error
                        error_code, error_message = code_error, message
                    else:
                        interval_status = "EMPTY_RESPONSE_CONFIRMED"
                    security_intervals.append({
                        "quota_security_id": code, "moomoo_code": code, "ticker": ticker, "interval_start": start, "interval_end": end,
                        "status": interval_status, "attempt_count": attempts, "request_count": requests, "row_count": len(frame),
                        "first_date": "" if frame.empty else str(frame.date.min().date()), "last_date": "" if frame.empty else str(frame.date.max().date()),
                        "data_path": str(path) if path.is_file() else "", "data_sha256": sha256(path) if path.is_file() else "",
                        "error_code": code_error, "error_message": message, "updated_utc": utc_now(),
                    })
                    interval_rows.extend(security_intervals[-1:])
                    checkpoint(status_rows, interval_rows, members)
                    if code_error in {"UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY", "UNSUPPORTED_OTC", "QUOTA_EXHAUSTED_FOR_MEMBER"}:
                        break
                combined = pd.concat([before, *new_frames], ignore_index=True) if new_frames else before
                if len(combined):
                    combined = combined.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
                    combined = normalize_frame(combined, ticker, code, "CURRENT_WEEK_MERGED")
                    path = history_path(code)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    combined.to_parquet(path, index=False)
                empty_intervals = sum(row["status"] == "EMPTY_RESPONSE_CONFIRMED" for row in security_intervals)
                hard_map = {
                    "UNKNOWN_SECURITY": "UNKNOWN_SECURITY", "UNSUPPORTED_SECURITY": "UNSUPPORTED_SECURITY",
                    "UNSUPPORTED_OTC": "UNSUPPORTED_OTC", "QUOTA_EXHAUSTED_FOR_MEMBER": "OTHER_HARD_FAILURE",
                    "TRANSIENT_FAILURE": "OTHER_HARD_FAILURE",
                }
                if error_code in hard_map:
                    final_status = "PARTIAL_MISSING_HISTORY" if len(combined) and error_code in {"QUOTA_EXHAUSTED_FOR_MEMBER", "TRANSIENT_FAILURE"} else hard_map[error_code]
                elif len(combined) == 0 and (empty_intervals or not ranges):
                    final_status = "EMPTY_RESPONSE_CONFIRMED"
                else:
                    final_status = "COMPLETE_TO_FIXED_CUTOFF"
                before = combined
            expected = pd.DatetimeIndex([])
            if len(before):
                import exchange_calendars as xcals
                cal = xcals.get_calendar("XNYS")
                expected = cal.sessions_in_range(before.date.min(), min(before.date.max(), FIXED_CUTOFF)).tz_localize(None)
            gaps = len(expected.difference(pd.DatetimeIndex(pd.to_datetime(before.date)))) if len(before) else 0
            hp = history_path(code)
            status_rows.append({
                "quota_security_id": code, "moomoo_code": code, "ticker": ticker, "pit_security_ids": member["pit_security_ids"],
                "required_history_start": member["required_history_start"], "fixed_backfill_cutoff_date": str(FIXED_CUTOFF.date()),
                "status": final_status, "local_row_count_before": initial_count, "final_row_count": len(before),
                "first_history_date": "" if before.empty else str(before.date.min().date()),
                "last_history_date": "" if before.empty else str(before.date.max().date()),
                "planned_interval_count": len(ranges), "attempted_interval_count": len(security_intervals),
                "successful_interval_count": sum(row["status"] == "SUCCESS_VALIDATED" for row in security_intervals),
                "empty_interval_count": sum(row["status"] == "EMPTY_RESPONSE_CONFIRMED" for row in security_intervals),
                "continuity_gap_count": gaps, "request_count": total_requests, "error_code": error_code,
                "error_message": error_message, "history_path": str(hp) if hp.is_file() else "",
                "history_sha256": sha256(hp) if hp.is_file() else "", "updated_utc": utc_now(),
            })
            checkpoint(status_rows, interval_rows, members)
            print(f"SECURITY_PROGRESS={len(status_rows)}/1000 code={code} status={final_status} rows={len(before)}", flush=True)
    finally:
        context.close()
    require(len(status_rows) == 1000, "SECURITY_PROCESS_COUNT_NOT_1000")
    require(set(row["status"] for row in status_rows).issubset(TERMINAL), "NONTERMINAL_STATUS_PRESENT")


def build_feature_outputs() -> dict[str, Any]:
    status = pd.read_csv(WORK / "working_completion_state.csv", dtype=str).fillna("")
    intervals = pd.read_parquet(INTERVALS_SOURCE)
    identity = pd.read_csv(IDENTITY_SOURCE)
    wanted = set(intervals.ticker.fillna("").astype(str).str.upper()) | {"QQQ"}
    pieces = []
    for year in range(2019, 2027):
        path = PRICE_ROOT / f"year={year}/prices.parquet"
        if path.is_file():
            part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "high", "low", "close", "volume", "turnover", "autype", "source"])
            part["ticker"] = part.ticker.astype(str).str.upper()
            pieces.append(part.loc[part.ticker.isin(wanted)].assign(priority=0))
    prior_overlay = Path(json_read(PRIOR_BACKFILL).get("overlay_path", ""))
    if prior_overlay.is_file():
        part = pd.read_parquet(prior_overlay).rename(columns={"date": "trade_date", "adjustment": "autype"})
        part["ticker"] = part.ticker.astype(str).str.upper()
        part["source"] = "MOOMOO_OPEND"
        pieces.append(part.loc[part.ticker.isin(wanted)].assign(priority=1))
    for row in status.itertuples(index=False):
        path = Path(row.history_path) if row.history_path else None
        if path is not None and path.is_file() and row.ticker in wanted:
            part = pd.read_parquet(path).rename(columns={"date": "trade_date", "adjustment": "autype"})
            part["source"] = "MOOMOO_OPEND"
            pieces.append(part.assign(priority=2))
    prices = pd.concat(pieces, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    prices, prices_asof_audit = asof_history_window(
        prices,
        FIXED_CUTOFF,
        date_column="trade_date",
    )
    prices = prices.sort_values(["ticker", "trade_date", "priority"], kind="mergesort").drop_duplicates(["ticker", "trade_date"], keep="last")
    prices["autype"] = "qfq"; prices["source"] = "MOOMOO_OPEND"
    require("QQQ" in set(prices.ticker), "QQQ_MISSING_FOR_CALENDAR")
    coverage = import_path("current_week_coverage_pipeline", COVERAGE_SOURCE)
    a2 = import_path("current_week_a2_feature_pipeline", A2_SOURCE)
    require(tuple(a2.FEATURE_COLUMNS) == FEATURES, "INCUMBENT_FEATURE_LIST_CHANGED")
    contract = json_read(FEATURE_CONTRACT)
    require(tuple(contract["feature_order"]) == FEATURES and contract["max_required_observations"] == 121, "FEATURE_CONTRACT_CHANGED")
    coverage.FEATURE_PATH = WORK / "all_feature_rows.parquet"
    coverage.BOUNDARY = FIXED_CUTOFF + pd.Timedelta(days=1)
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    membership = coverage.membership_rows(intervals, calendar)
    state, feature_rows = coverage.materialize_features(prices, membership, a2)
    daily, quarter, security = coverage.waterfall(state, identity)
    prior_features = pd.read_parquet(PRIOR_FEATURES, columns=["as_of_date", "security_id", "ticker"])
    old_keys = pd.MultiIndex.from_frame(prior_features[["as_of_date", "security_id", "ticker"]])
    new_keys = pd.MultiIndex.from_frame(feature_rows[["as_of_date", "security_id", "ticker"]])
    incremental = feature_rows.loc[~new_keys.isin(old_keys)].copy()
    incremental_path = WORK / "incremental_feature_rows.parquet"
    incremental.to_parquet(incremental_path, index=False)
    quarter_path = WORK / "coverage_by_quarter.csv"
    quarter.to_csv(quarter_path, index=False)
    result = {
        "state_row_count": len(state), "feature_row_count": len(feature_rows), "new_feature_row_count": len(incremental),
        "pit_market_data_coverage": float(daily.historical_market_data_available_coverage.median()),
        "pit_feature_coverage": float(daily.final_feature_vector_available_coverage.median()),
        "pit_next_open_coverage": float(daily.execution_open_available_coverage.median()),
        "pit_executable_mapping_coverage": float(daily.executable_mapping_available_coverage.median()),
        "min_quarter_feature_coverage": float(quarter.final_feature_vector_available_coverage.min()),
        "median_quarter_feature_coverage": float(quarter.final_feature_vector_available_coverage.median()),
        "incremental_feature_path": str(incremental_path), "incremental_feature_sha256": sha256(incremental_path),
        "incremental_feature_min_date": "" if incremental.empty else str(incremental.as_of_date.min().date()),
        "incremental_feature_max_date": "" if incremental.empty else str(incremental.as_of_date.max().date()),
        "feature_timestamp_violation_count": int((feature_rows.feature_max_timestamp > feature_rows.as_of_date).sum()),
        "as_of_date": str(FIXED_CUTOFF.date()),
        "max_used_date": prices_asof_audit["asof_rows_used_max_date"],
        "local_data_extends_beyond_asof": prices_asof_audit["local_data_extends_beyond_asof"],
        "2026_training_rows": 0, "2026_parameter_search_count": 0, "2026_model_selection_count": 0,
    }
    json_write(WORK / "coverage_after_completion.json", result)
    return result


def freeze() -> None:
    initialize()
    state_path = WORK / "working_completion_state.csv"
    require(state_path.is_file(), "WORKING_STATE_MISSING")
    state = pd.read_csv(state_path, dtype=str).fillna("")
    require(len(state) == 1000 and state.moomoo_code.nunique() == 1000, "SECURITY_PROCESS_COUNT_NOT_1000")
    require(state.status.isin(TERMINAL).all(), "ALL_CURRENT_WEEK_SECURITIES_TERMINAL_FALSE")
    audit = json_read(WORK / "request_audit.json")
    initial = set(pd.read_csv(WORK / "current_week_quota_set.csv", dtype=str).moomoo_code)
    requested = {str(row["moomoo_code"]) for row in audit.get("requests", [])}
    new_unique = len(requested - initial)
    require(new_unique == 0, "NEW_UNIQUE_SECURITY_REQUEST_COUNT_NONZERO")
    audit["new_unique_security_request_count"] = new_unique
    json_write(WORK / "request_audit.json", audit)
    coverage = build_feature_outputs()
    require(coverage["feature_timestamp_violation_count"] == 0, "FEATURE_TIMESTAMP_VIOLATION")
    require(not FINAL.exists(), "FINAL_RESULT_ROOT_ALREADY_EXISTS")
    FINAL.mkdir(parents=True)
    shutil.copy2(WORK / "current_week_quota_set.csv", FINAL / "current_week_quota_set.csv")
    shutil.copy2(WORK / "fixed_backfill_cutoff.json", FINAL / "fixed_backfill_cutoff.json")
    shutil.copy2(WORK / "working_completion_state.csv", FINAL / "security_completion_status.csv")
    shutil.copy2(WORK / "completed_intervals.csv", FINAL / "completed_intervals.csv")
    shutil.copy2(WORK / "remaining_intervals.csv", FINAL / "remaining_intervals.csv")
    quarter = pd.read_csv(WORK / "coverage_by_quarter.csv")
    quarter.to_csv(FINAL / "coverage_by_quarter.csv", index=False)
    failures = state.loc[~state.status.eq("COMPLETE_TO_FIXED_CUTOFF")]
    failures.to_csv(FINAL / "hard_failure_manifest.csv", index=False)
    new_rows = 0
    for row in read_rows(WORK / "completed_intervals.csv"):
        if row.get("status") == "SUCCESS_VALIDATED":
            new_rows += int(float(row.get("row_count") or 0))
    json_write(FINAL / "market_data_manifest.json", {
        "run_id": RUN_ID, "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY", "adjustment": "QFQ",
        "fixed_backfill_cutoff_date": str(FIXED_CUTOFF.date()), "quota_security_count": 1000,
        "requested_security_count": len(requested), "new_unique_security_request_count": 0,
        "new_market_data_row_count": new_rows, "canonical_data_modified": False,
        "working_history_root": str(HISTORY), "request_audit_path": str(WORK / "request_audit.json"),
        "request_audit_sha256": sha256(WORK / "request_audit.json"),
    })
    json_write(FINAL / "incremental_feature_manifest.json", {
        "run_id": RUN_ID, "incumbent_feature_count": 32, "feature_order": list(FEATURES),
        "feature_definition_changed": False, "missing_value_rules_changed": False, "target_changed": False,
        "hgb_changed": False, "universe_rules_changed": False, "new_feature_row_count": coverage["new_feature_row_count"],
        "incremental_feature_path": coverage["incremental_feature_path"],
        "incremental_feature_sha256": coverage["incremental_feature_sha256"],
        "feature_timestamp_violation_count": 0, "2026_training_rows": 0,
        "2026_parameter_search_count": 0, "2026_model_selection_count": 0,
    })
    json_write(FINAL / "coverage_after_completion.json", coverage)
    source_paths = [
        REPO / "docs/governance/ANTI_BLOAT_POLICY.md", Path(__file__), INTERVALS_SOURCE, IDENTITY_SOURCE,
        FEATURE_CONTRACT, A2_SOURCE, FETCH_SOURCE, COVERAGE_SOURCE, PRIOR_BACKFILL, PRIOR_FEATURES,
    ]
    sources = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in source_paths]
    json_write(FINAL / "source_hash_manifest.json", {"run_id": RUN_ID, "sources": sources})
    counts = state.status.value_counts().to_dict()
    summary = {
        "A2_PIT_MOOMOO_CURRENT_WEEK_COMPLETION_R1_STATUS": "PASS",
        "FIXED_BACKFILL_CUTOFF_DATE": str(FIXED_CUTOFF.date()),
        "CURRENT_WEEK_QUOTA_SECURITY_COUNT": 1000, "NEW_UNIQUE_SECURITY_REQUEST_COUNT": 0,
        "SECURITY_PROCESS_COUNT": 1000, "COMPLETE_TO_FIXED_CUTOFF_COUNT": int(counts.get("COMPLETE_TO_FIXED_CUTOFF", 0)),
        "PARTIAL_COUNT": int(counts.get("PARTIAL_MISSING_HISTORY", 0)),
        "EMPTY_RESPONSE_COUNT": int(counts.get("EMPTY_RESPONSE_CONFIRMED", 0)),
        "UNKNOWN_SECURITY_COUNT": int(counts.get("UNKNOWN_SECURITY", 0)),
        "UNSUPPORTED_SECURITY_COUNT": int(counts.get("UNSUPPORTED_SECURITY", 0)),
        "OTC_UNSUPPORTED_COUNT": int(counts.get("UNSUPPORTED_OTC", 0)),
        "OTHER_HARD_FAILURE_COUNT": int(counts.get("OTHER_HARD_FAILURE", 0) + counts.get("INVALID_HISTORICAL_MAPPING", 0)),
        "CURRENT_WEEK_COMPLETE_COUNT": int(counts.get("COMPLETE_TO_FIXED_CUTOFF", 0)),
        "CURRENT_WEEK_PARTIAL_COUNT": int(counts.get("PARTIAL_MISSING_HISTORY", 0)),
        "CURRENT_WEEK_EMPTY_COUNT": int(counts.get("EMPTY_RESPONSE_CONFIRMED", 0)),
        "CURRENT_WEEK_UNKNOWN_COUNT": int(counts.get("UNKNOWN_SECURITY", 0)),
        "CURRENT_WEEK_UNSUPPORTED_COUNT": int(counts.get("UNSUPPORTED_SECURITY", 0)),
        "CURRENT_WEEK_OTC_UNSUPPORTED_COUNT": int(counts.get("UNSUPPORTED_OTC", 0)),
        "NEW_MARKET_DATA_ROW_COUNT": new_rows, "NEW_FEATURE_ROW_COUNT": coverage["new_feature_row_count"],
        "PIT_MARKET_DATA_COVERAGE": coverage["pit_market_data_coverage"],
        "PIT_FEATURE_COVERAGE_BEFORE": 0.5850439882697948,
        "PIT_FEATURE_COVERAGE_AFTER": coverage["pit_feature_coverage"],
        "PIT_NEXT_OPEN_COVERAGE_AFTER": coverage["pit_next_open_coverage"],
        "PIT_EXECUTABLE_MAPPING_COVERAGE_AFTER": coverage["pit_executable_mapping_coverage"],
        "MIN_QUARTER_FEATURE_COVERAGE_AFTER": coverage["min_quarter_feature_coverage"],
        "MEDIAN_QUARTER_FEATURE_COVERAGE_AFTER": coverage["median_quarter_feature_coverage"],
        "ALL_CURRENT_WEEK_SECURITIES_TERMINAL": True, "FINAL_COMPLETION_ASSET_FROZEN": True,
        "2026_TRAINING_ROWS": 0, "2026_PARAMETER_SEARCH_COUNT": 0, "2026_MODEL_SELECTION_COUNT": 0,
        "NEXT_AUTHORIZED_STEP": "PRESERVE_FROZEN_COMPLETION_ASSET_AND_REVIEW_DOCUMENTED_HARD_FAILURES",
    }
    json_write(FINAL / "coverage_after_completion.json", {**coverage, **summary})
    material = [
        "current_week_quota_set.csv", "fixed_backfill_cutoff.json", "security_completion_status.csv",
        "completed_intervals.csv", "remaining_intervals.csv", "market_data_manifest.json",
        "incremental_feature_manifest.json", "coverage_after_completion.json", "coverage_by_quarter.csv",
        "hard_failure_manifest.csv", "source_hash_manifest.json",
    ]
    hashes = [{"path": str(FINAL / name), "bytes": (FINAL / name).stat().st_size, "sha256": sha256(FINAL / name)} for name in material]
    # A tree digest avoids self-reference: it hashes the stable ordered set of
    # core material outputs.  The manifest then also hashes the closeout.
    freeze_hash = hashlib.sha256("\n".join(f"{Path(row['path']).name}|{row['sha256']}" for row in hashes).encode()).hexdigest()
    summary["FINAL_FREEZE_SHA256"] = freeze_hash
    block = "\n".join(f"{key}={value}" for key, value in summary.items())
    closeout = (
        f"# {RUN_ID}\n\nAll 1,000 securities in the provider-reported current-week quota set reached a documented terminal state before this asset was frozen. "
        "Every historical request passed the frozen membership gate; no canonical data was modified and no model was trained.\n\n"
        f"```text\n{block}\n```\n"
    )
    (FINAL / "closeout.md").write_text(closeout, encoding="utf-8")
    json_write(FINAL / "freeze_manifest.json", {
        "run_id": RUN_ID, "frozen_utc": utc_now(),
        "final_freeze_sha256": freeze_hash,
        "final_freeze_sha256_definition": "SHA256 of ordered filename|sha256 lines for core material outputs; freeze_manifest is non-self-referential",
        "artifacts": hashes + [{"path": str(FINAL / "closeout.md"), "bytes": (FINAL / "closeout.md").stat().st_size, "sha256": sha256(FINAL / "closeout.md")}],
    })
    print(block, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("initialize", "fetch", "freeze", "all"), default="all")
    args = parser.parse_args()
    if args.stage in {"initialize", "all"}:
        initialize()
    if args.stage in {"fetch", "all"}:
        fetch_all()
    if args.stage in {"freeze", "all"}:
        freeze()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
