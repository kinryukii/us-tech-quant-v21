"""Extend the DEMO's bound ETF RAW references from existing Massive cache only.

No provider SDK, HTTP client, credential loader, catalog mutation, or download
fallback is used. Both ETFs must cover every new verified session before the
small reference is atomically published. The initial historical projection is
created separately and retained as immutable provenance.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

import pandas as pd

COLUMNS = ["date", "ticker", "open", "source", "adjustment"]
CUTOVER = {"date": "2024-09-13", "before": "MOOMOO_OPEND", "on_and_after": "MASSIVE_GROUPED"}
ENDPOINT = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/"


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _ref(path, expected=None):
    path = Path(path).resolve()
    value = _hash(path)
    if expected is not None and (not re.fullmatch(r"[a-f0-9]{64}", expected) or value != expected):
        raise ValueError("BENCHMARK_SOURCE_HASH_CHANGED:" + str(path))
    return {"path": str(path), "sha256": value}


def _iso(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("BENCHMARK_ISO_DATE_REQUIRED")
    return value


def _frame(frame, symbol):
    frame = frame.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
    if (frame.empty or not frame.ticker.eq(symbol).all() or not frame.adjustment.eq("raw").all()
            or frame.date.tolist() != sorted(set(frame.date))
            or not all(math.isfinite(float(x)) and float(x) > 0 for x in frame.open)):
        raise ValueError("BENCHMARK_INVALID_PRICE_PROJECTION:" + symbol)
    wanted = frame.date.map(lambda day: CUTOVER["before"] if day < CUTOVER["date"] else CUTOVER["on_and_after"])
    if not frame.source.eq(wanted).all():
        raise ValueError("BENCHMARK_FIXED_RAW_SOURCE_RULE_CHANGED")
    return frame.reset_index(drop=True)


def _checkpoint(cache_root, day):
    root = (Path(cache_root) / "daily_recommendation/massive_current/days" / day).resolve()
    checkpoint_path = root / "checkpoint.json"
    checkpoint_ref = _ref(checkpoint_path)
    saved = json.loads(checkpoint_path.read_bytes())
    expected = {"date": day, "url": ENDPOINT + day,
                "params": {"adjusted": "false", "include_otc": "false"}}
    if saved.get("status") != "SUCCESS" or saved.get("contract") != expected:
        raise ValueError("BENCHMARK_MASSIVE_DAY_NOT_VERIFIED:" + day)
    source = saved["raw"]
    raw_path = Path(source["path"]).resolve()
    if raw_path.parent != root or raw_path.suffix != ".json":
        raise ValueError("BENCHMARK_MASSIVE_RAW_OUTSIDE_CHECKPOINT")
    raw_ref = _ref(raw_path, source["sha256"])
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != source["bytes"]:
        raise ValueError("BENCHMARK_MASSIVE_RAW_SIZE_CHANGED")
    raw = json.loads(raw_bytes)
    if raw.get("status") != "OK" or not isinstance(raw.get("results"), list) or raw.get("resultsCount") != len(raw["results"]) or raw.get("next_url"):
        raise ValueError("BENCHMARK_MASSIVE_RESPONSE_NOT_COMPLETE")
    if raw.get("adjusted") is not False:
        raise ValueError("BENCHMARK_MASSIVE_RAW_BASIS_REQUIRED")
    rows = {}
    for symbol in ("QQQ", "SPY"):
        selected = [row for row in raw.get("results", []) if row.get("T") == symbol]
        if len(selected) != 1:
            raise ValueError("BENCHMARK_ETF_MISSING_OR_DUPLICATED:" + day + ":" + symbol)
        item = selected[0]
        stamp = pd.Timestamp(item["t"], unit="ms", tz="UTC").tz_convert("America/New_York")
        opening = float(item["o"])
        if stamp.strftime("%Y-%m-%d") != day or not math.isfinite(opening) or opening <= 0:
            raise ValueError("BENCHMARK_INVALID_CACHED_OPEN:" + day + ":" + symbol)
        rows[symbol] = {"date": day, "ticker": symbol, "open": opening,
                        "source": "MASSIVE_GROUPED", "adjustment": "raw"}
    # Detect source changes during extraction before publication.
    _ref(raw_path, raw_ref["sha256"])
    _ref(checkpoint_path, checkpoint_ref["sha256"])
    return rows, [raw_ref, checkpoint_ref]


def _refresh(paths, target, calendar, result):
    target = _iso(target)
    sessions = [_iso(day) for day in calendar["sessions"]]
    if sessions != sorted(set(sessions)) or target not in sessions or calendar.get("target_date") != target:
        raise ValueError("BENCHMARK_VERIFIED_TARGET_CALENDAR_REQUIRED")
    root = (Path(paths.results_root) / "demo-console/benchmarks").resolve()
    pointer = root / "updated_reference.json"
    original_pointer = pointer.read_bytes()
    reference = json.loads(original_pointer)
    manifest_path = Path(reference["path"]).resolve()
    if not manifest_path.is_relative_to(root / "updated"):
        raise ValueError("BENCHMARK_REFERENCE_OUTSIDE_DERIVED_ROOT")
    manifest_ref = _ref(manifest_path, reference["sha256"])
    base = json.loads(manifest_path.read_bytes())
    if (base.get("schema_version") != 1 or base.get("status") != "READY"
            or base.get("basis") != "OPEN_TO_OPEN_PRICE_RETURN" or base.get("adjustment") != "RAW"
            or base.get("provider") != "MOOMOO_OPEND_AND_MASSIVE" or base.get("dividends_included") is not False
            or base.get("splits_adjusted") is not False or base.get("fixed_source_cutover") != CUTOVER):
        raise ValueError("BENCHMARK_ESTABLISHED_RAW_CONTRACT_CHANGED")
    artifacts = base["artifacts"]
    if len(artifacts) != 2 or sorted(x["symbol"] for x in artifacts) != ["QQQ", "SPY"]:
        raise ValueError("BENCHMARK_BOTH_ETFS_REQUIRED")
    frames, old_dates = {}, None
    for artifact in artifacts:
        symbol, path = artifact["symbol"], Path(artifact["path"]).resolve()
        if path.parent != manifest_path.parent:
            raise ValueError("BENCHMARK_PRICE_OUTSIDE_IMMUTABLE_RUN")
        _ref(path, artifact["sha256"])
        frame = _frame(pd.read_parquet(path, columns=COLUMNS), symbol)
        if len(frame) != artifact["row_count"] or (frame.date.iloc[0], frame.date.iloc[-1]) != (artifact["start_date"], artifact["end_date"]):
            raise ValueError("BENCHMARK_PRICE_COVERAGE_METADATA_CHANGED")
        if artifact["start_date"] != base["start_date"] or artifact["end_date"] != base["end_date"]:
            raise ValueError("BENCHMARK_COMMON_WINDOW_REQUIRED")
        if old_dates is not None and frame.date.tolist() != old_dates:
            raise ValueError("BENCHMARK_ETF_DATE_SETS_DIFFER")
        old_dates = frame.date.tolist()
        if not artifact.get("source_refs"):
            raise ValueError("BENCHMARK_SOURCE_REFS_REQUIRED")
        for source in artifact["source_refs"]:
            _ref(source["path"], source["sha256"])
        frames[symbol] = frame
    previous_end = base["end_date"]
    result.update(previous_end_date=previous_end, available_end_date=previous_end)
    if target < base["start_date"]:
        raise ValueError("BENCHMARK_TARGET_BEFORE_AVAILABLE_WINDOW")
    if target <= previous_end:
        if target not in old_dates:
            raise ValueError("BENCHMARK_TARGET_MISSING_FROM_EXISTING_WINDOW")
        result.update(status="READY", reused=True, manifest=manifest_ref, reference=str(pointer),
                      start_date=base["start_date"], end_date=previous_end, appended_sessions=0)
        return result
    if previous_end not in sessions:
        raise ValueError("BENCHMARK_PREVIOUS_END_OUTSIDE_VERIFIED_CALENDAR")
    days = [day for day in sessions if previous_end < day <= target]
    additions = {symbol: [] for symbol in frames}
    refs = []
    for day in days:
        rows, inputs = _checkpoint(paths.cache_root, day)
        refs.extend(inputs)
        for symbol in frames:
            additions[symbol].append(rows[symbol])
    for symbol in frames:
        frames[symbol] = _frame(pd.concat([frames[symbol], pd.DataFrame(additions[symbol])], ignore_index=True), symbol)
        if frames[symbol].date.tolist() != old_dates + days:
            raise ValueError("BENCHMARK_NEW_SESSION_COVERAGE_MISMATCH")
    for ref in refs:
        _ref(ref["path"], ref["sha256"])
    calendar_proof = {key: calendar[key] for key in ("calendar_id", "calendar_sha256", "as_of_utc") if key in calendar}
    calendar_proof.update(target_date=target, appended_sessions=days,
                          sessions_sha256=hashlib.sha256(_bytes(sessions)).hexdigest())
    contract = {key: value for key, value in base.items() if key not in
                {"artifacts", "generated_at", "run_id", "content_fingerprint", "previous_manifest", "refresh_calendar", "end_date"}}
    contract.update(end_date=target, previous_manifest=manifest_ref, refresh_calendar=calendar_proof)
    specifications = []
    for artifact in artifacts:
        sources = {item["path"]: item for item in [*artifact["source_refs"], manifest_ref,
                   {"path": artifact["path"], "sha256": artifact["sha256"]}, *refs]}
        specifications.append({"symbol": artifact["symbol"], "start_date": base["start_date"], "end_date": target,
                               "row_count": len(frames[artifact["symbol"]]), "source_refs": [sources[k] for k in sorted(sources)]})
    identity = hashlib.sha256(_bytes({**contract, "artifacts": specifications})).hexdigest()
    run_dir = root / "updated" / identity[:24]
    run_dir.mkdir(parents=True, exist_ok=True)
    for artifact in specifications:
        path = run_dir / (artifact["symbol"] + ".parquet")
        if path.exists():
            pd.testing.assert_frame_equal(pd.read_parquet(path), frames[artifact["symbol"]])
        else:
            frames[artifact["symbol"]].to_parquet(path, index=False)
        artifact.update(_ref(path))
        pd.testing.assert_frame_equal(_frame(pd.read_parquet(path), artifact["symbol"]), frames[artifact["symbol"]])
    manifest = {**contract, "artifacts": specifications, "generated_at": datetime.now(timezone.utc).isoformat(),
                "run_id": identity[:24], "content_fingerprint": identity}
    output = run_dir / "manifest.json"
    if output.exists():
        prior = json.loads(output.read_bytes())
        if prior["content_fingerprint"] != identity or prior["artifacts"] != specifications:
            raise ValueError("BENCHMARK_IMMUTABLE_RUN_CONFLICT")
    else:
        output.write_bytes(_bytes(manifest))
    published = _ref(output)
    if pointer.read_bytes() != original_pointer:
        raise ValueError("BENCHMARK_REFERENCE_CHANGED_DURING_REFRESH")
    temporary = pointer.with_name("updated_reference." + identity[:16] + ".tmp")
    temporary.write_bytes(_bytes(published))
    os.replace(temporary, pointer)
    result.update(status="READY", reused=False, manifest=published, reference=str(pointer),
                  start_date=base["start_date"], end_date=target, available_end_date=target, appended_sessions=len(days))
    return result


def refresh_demo_benchmarks(paths, target, calendar, progress=lambda message: None):
    """Return an independent status; missing cache never changes the old pointer."""
    result = {"status": "BLOCKED", "target_date": target, "network_requests": 0, "moomoo_requests": 0,
              "basis": "OPEN_TO_OPEN_PRICE_RETURN", "dividends_included": False}
    try:
        result = _refresh(paths, target, calendar, result)
    except Exception as exc:
        result["error"] = str(exc)
        progress("QQQ / SPY 缓存尚未覆盖本次日期；保留已有基准及其实际截止日期。")
        return result
    progress("QQQ / SPY 价格基准已由本地缓存核验至 " + result["end_date"] + "（不含分红）。")
    return result
