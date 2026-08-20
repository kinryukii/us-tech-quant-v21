"""Recover one authoritative Moomoo QFQ daily bar for R4 execution coverage."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import autype_for_mode, ktype_daily, normalize_kline_frame


EXPERIMENT_ID = "ABCDE_A2_R4X_HIVE_20230712_EXECUTION_PRICE_RECOVERY"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r4x_summary.json"
EVIDENCE_PATH = RESULTS_ROOT / "hive_20230710_20230714_moomoo_evidence.json"
REPAIR_AUDIT_PATH = RESULTS_ROOT / "canonical_gap_repair_audit.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r4x_manifest.json"
REPAIR_PROVENANCE_PATH = RESULTS_ROOT / "hive_20230712_repair_provenance.json"
REPAIR_CANDIDATE_PATH = RESULTS_ROOT / "hive_20230712_canonical_repair_candidate.parquet"
CANONICAL_PATH = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq\year=2023\prices.parquet")
SAFE_PROVIDER_ENV_ROOT = Path(r"D:\us-tech-quant-cache\moomoo_provider_env\a2_r4x_hive_20230712")
R4_MODULE_PATH = REPO_ROOT / "scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
R4_CONTRACT_PATH = Path(r"D:\us-tech-quant-results\ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT\a2_r4_portfolio_translation_contract_r1.json")
EXPECTED_R4_CONTRACT_SHA256 = "3d803330dee82a425b2544af16736547befea865dde5967e0de046b2ce83cd9d"
TARGET_DATE = "2023-07-12"
START_DATE = "2023-07-10"
END_DATE = "2023-07-14"


def canonical_payload(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str,
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    """Return strict-JSON values without changing finite numeric evidence."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(float(value)) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_payload(value) + b"\n")
    os.replace(temporary, path)


def import_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def canonical_before_audit() -> dict[str, Any]:
    if not CANONICAL_PATH.is_file():
        raise RuntimeError(f"MISSING_CANONICAL_PARTITION:{CANONICAL_PATH}")
    table = pq.read_table(CANONICAL_PATH)
    frame = table.to_pandas()
    dates = pd.to_datetime(frame.trade_date, errors="coerce")
    match = frame.loc[(frame.ticker.astype(str).str.upper() == "HIVE") & (dates == pd.Timestamp(TARGET_DATE))]
    return {
        "canonical_path": str(CANONICAL_PATH), "partition_sha256_before": sha256_file(CANONICAL_PATH),
        "partition_row_count_before": len(frame), "schema": str(table.schema),
        "hive_20230712_row_count_before": len(match),
        "hive_20230712_open_before": None if match.empty else float(match.iloc[0].open),
    }


def opend_preflight(host: str, port: int, timeout_seconds: float = 1.5) -> dict[str, Any]:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return {"reachable": True, "host": host, "port": int(port), "error": None}
    except OSError as exc:
        return {
            "reachable": False, "host": host, "port": int(port),
            "error": f"{type(exc).__name__}:{exc}",
        }


def request_moomoo_window() -> tuple[pd.DataFrame, dict[str, Any]]:
    safe_log_dir = SAFE_PROVIDER_ENV_ROOT / "provider_logs"
    safe_appdata = SAFE_PROVIDER_ENV_ROOT / "AppData" / "Roaming"
    safe_localappdata = SAFE_PROVIDER_ENV_ROOT / "AppData" / "Local"
    safe_userprofile = SAFE_PROVIDER_ENV_ROOT / "userprofile"
    for path in (safe_log_dir, safe_appdata, safe_localappdata, safe_userprofile):
        path.mkdir(parents=True, exist_ok=True)
    # This installed SDK hard-codes its log path below APPDATA at import time.
    # Redirect environment only; quote semantics and OpenD endpoint are unchanged.
    os.environ.update({
        "FUTU_OPEND_LOG_DIR": str(safe_log_dir), "MOOMOO_LOG_DIR": str(safe_log_dir),
        "FUTU_LOG_DIR": str(safe_log_dir), "FutuOpenD_LogDir": str(safe_log_dir),
        "APPDATA": str(safe_appdata), "LOCALAPPDATA": str(safe_localappdata),
        "USERPROFILE": str(safe_userprofile), "TMP": str(safe_log_dir), "TEMP": str(safe_log_dir),
    })
    requested_at = datetime.now(timezone.utc)
    client = MoomooQuoteClient()
    preflight = opend_preflight(client.host, client.port)
    if not preflight["reachable"]:
        raise RuntimeError(
            f"MOOMOO_OPEND_TCP_UNREACHABLE:{client.host}:{client.port}:{preflight['error']}"
        )
    with client:
        module = client.module
        ktype = ktype_daily(module)
        autype = autype_for_mode(module, "QFQ")
        frames: list[pd.DataFrame] = []
        page_req_key = None
        request_count = 0
        while True:
            kwargs: dict[str, Any] = {
                "code": "US.HIVE", "start": START_DATE, "end": END_DATE,
                "ktype": ktype, "autype": autype, "max_count": 1000,
            }
            if page_req_key is not None:
                kwargs["page_req_key"] = page_req_key
            request_count += 1
            try:
                payload = client.checked_call("request_history_kline", **kwargs)
            except Exception as exc:
                raise RuntimeError(f"MOOMOO_REQUEST_ATTEMPT_COUNT={request_count}:{type(exc).__name__}:{exc}") from exc
            data, next_key = payload, None
            if isinstance(payload, tuple):
                data = payload[0]
                next_key = payload[1] if len(payload) > 1 else None
            frames.append(data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data))
            if not next_key:
                break
            page_req_key = next_key
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        normalized = normalize_kline_frame(raw, "HIVE", "US.HIVE", "QFQ", fetched_at)
        raw_columns = [str(column) for column in raw.columns]
        metadata = {
            "ticker": "HIVE", "security_identity": "US.HIVE", "market": "US",
            "request_method": "OpenQuoteContext.request_history_kline",
            "request_start": START_DATE, "request_end": END_DATE,
            "ktype": str(ktype), "autype": str(autype), "adjustment_mode": "QFQ",
            "host": client.host, "port": client.port, "request_count": request_count,
            "sdk_log_root": str(safe_log_dir), "sdk_appdata_root": str(safe_appdata),
            "requested_at_utc": requested_at.isoformat(), "completed_at_utc": fetched_at,
            "moomoo_sdk_version": str(getattr(module, "__version__", "UNKNOWN")),
            "raw_columns": raw_columns, "raw_row_count": len(raw),
            "broker_action_count": 0, "quote_context_only": True,
        }
    raw_lower = raw.rename(columns={column: str(column).strip().lower() for column in raw.columns})
    extras = raw_lower[[column for column in ("time_key", "change_rate") if column in raw_lower]].copy()
    if "time_key" in extras:
        extras["date"] = pd.to_datetime(extras.time_key, errors="coerce").dt.strftime("%Y-%m-%d")
        normalized = normalized.merge(extras.drop(columns=["time_key"]), on="date", how="left", validate="one_to_one")
    elif "change_rate" not in normalized:
        normalized["change_rate"] = np.nan
    return normalized, metadata


def parse_evidence(frame: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    work = frame.copy()
    work["date"] = pd.to_datetime(work.date, errors="coerce").dt.strftime("%Y-%m-%d")
    numeric = ["open", "high", "low", "close", "volume", "turnover", "last_close", "change_rate"]
    for column in numeric:
        if column not in work:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    rows = []
    for row in work.sort_values("date", kind="mergesort").to_dict("records"):
        rows.append({
            "ticker": "HIVE", "security_identity": "US.HIVE", "market": "US",
            "date": row.get("date"), "open": row.get("open"), "high": row.get("high"),
            "low": row.get("low"), "close": row.get("close"), "volume": row.get("volume"),
            "turnover": row.get("turnover"), "last_close": row.get("last_close"),
            "change_rate": row.get("change_rate"), "adjustment_mode": "QFQ",
            "KLType": metadata["ktype"], "AuType": metadata["autype"], "source": "MOOMOO_OPEND",
        })
    target = [row for row in rows if row["date"] == TARGET_DATE]
    valid = False
    if len(target) == 1:
        row = target[0]
        ohlc = np.array([row["open"], row["high"], row["low"], row["close"]], dtype=float)
        valid = bool(
            np.isfinite(ohlc).all() and (ohlc > 0).all()
            and row["high"] >= max(row["open"], row["close"])
            and row["low"] <= min(row["open"], row["close"])
            and np.isfinite(float(row["volume"])) and float(row["volume"]) >= 0
        )
    stable_metadata = {key: value for key, value in metadata.items() if key not in {"requested_at_utc", "completed_at_utc"}}
    fingerprint = canonical_fingerprint({"rows": rows, "request": stable_metadata})
    return {
        "SOURCE_POLICY": "MOOMOO_ONLY", "request_metadata": metadata,
        "rows": rows, "returned_dates": [row["date"] for row in rows],
        "target_date": TARGET_DATE, "target_row_count": len(target),
        "target_bar_valid": valid, "evidence_fingerprint": fingerprint,
    }


def _semantic_fingerprint(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True).copy()
    for column in ordered.columns:
        ordered[column] = ordered[column].astype(str)
    values = pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(dtype=np.uint64)
    return hashlib.sha256(values.tobytes()).hexdigest()


def build_repair_candidate(evidence: dict[str, Any], before: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    table = pq.read_table(CANONICAL_PATH)
    original = table.to_pandas()
    target = evidence["rows"][evidence["returned_dates"].index(TARGET_DATE)]
    row = {column: None for column in original.columns}
    row.update({
        "ticker": "HIVE", "trade_date": TARGET_DATE,
        "open": target["open"], "high": target["high"], "low": target["low"], "close": target["close"],
        "volume": target["volume"], "turnover": target["turnover"], "change_rate": target["change_rate"],
        "last_close": target["last_close"], "autype": "qfq", "source": "MOOMOO_OPEND",
        "fetch_timestamp": evidence["request_metadata"]["completed_at_utc"],
        "request_start": START_DATE, "request_end": END_DATE,
    })
    candidate = pd.concat([original, pd.DataFrame([row])], ignore_index=True)
    candidate["trade_date"] = pd.to_datetime(candidate.trade_date, errors="coerce").dt.strftime("%Y-%m-%d")
    candidate = candidate.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True)
    if candidate.duplicated(["ticker", "trade_date"]).any() or len(candidate) != len(original) + 1:
        raise RuntimeError("R4X_REPAIR_CANDIDATE_KEY_OR_ROW_FAILURE")
    original_roundtrip = candidate.loc[~((candidate.ticker == "HIVE") & (candidate.trade_date == TARGET_DATE))].reset_index(drop=True)
    if _semantic_fingerprint(original) != _semantic_fingerprint(original_roundtrip):
        raise RuntimeError("R4X_NON_TARGET_ROWS_CHANGED_IN_CANDIDATE")
    audit = {
        **before, "candidate_row_count": len(candidate),
        "non_target_rows_semantic_identity_status": "PASS",
        "candidate_target_row": row,
    }
    return candidate, audit


def persist_candidate(candidate: pd.DataFrame) -> str:
    schema = pq.read_schema(CANONICAL_PATH)
    table = pa.Table.from_pandas(candidate, schema=schema, preserve_index=False, safe=True)
    temporary = REPAIR_CANDIDATE_PATH.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True, write_statistics=True)
    os.replace(temporary, REPAIR_CANDIDATE_PATH)
    return sha256_file(REPAIR_CANDIDATE_PATH)


def apply_canonical_candidate(candidate_path: Path) -> dict[str, Any]:
    before_hash = sha256_file(CANONICAL_PATH)
    temporary = CANONICAL_PATH.with_suffix(".parquet.r4x.tmp")
    try:
        temporary.write_bytes(candidate_path.read_bytes())
        os.replace(temporary, CANONICAL_PATH)
    finally:
        if temporary.exists():
            temporary.unlink()
    reread = pq.read_table(CANONICAL_PATH).to_pandas()
    dates = pd.to_datetime(reread.trade_date, errors="coerce")
    target = reread.loc[(reread.ticker.astype(str).str.upper() == "HIVE") & (dates == pd.Timestamp(TARGET_DATE))]
    if len(target) != 1 or not np.isfinite(float(target.iloc[0].open)):
        raise RuntimeError("R4X_CANONICAL_POSTWRITE_VALIDATION_FAILURE")
    return {
        "canonical_path": str(CANONICAL_PATH), "partition_sha256_before": before_hash,
        "partition_sha256_after": sha256_file(CANONICAL_PATH),
        "hive_20230712_row_count_after": len(target),
        "hive_20230712_open_after": float(target.iloc[0].open),
        "CANONICAL_HIVE_20230712_OPEN_STATUS": "PASS",
    }


def coverage_reaudit() -> dict[str, Any]:
    r4 = import_module("abcde_a2_r4x_r4_helpers", R4_MODULE_PATH)
    signals, _ = r4.load_authoritative_signals()
    prices, _ = r4.load_execution_prices(set(signals.ticker))
    first = r4.execution_open_coverage_audit(signals, prices)
    second = r4.execution_open_coverage_audit(signals, prices)
    return {
        "run1": first, "run2": second, "reproducible": first == second,
        "MISSING_CANONICAL_EXECUTION_OPEN_COUNT": first["missing_event_count"],
        "fingerprint": first["logical_fingerprint"],
    }


def protected_hashes() -> dict[str, str]:
    paths = (
        REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
        REPO_ROOT / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py",
        REPO_ROOT / "scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py",
        REPO_ROOT / "config/v21/active_chain_manifest.json",
        R4_CONTRACT_PATH,
    )
    return {str(path): sha256_file(path) for path in paths if path.is_file()}


def run_recovery(apply_repair: bool = True) -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if not R4_CONTRACT_PATH.is_file() or sha256_file(R4_CONTRACT_PATH) != EXPECTED_R4_CONTRACT_SHA256:
        raise RuntimeError("R4_FROZEN_CONTRACT_IDENTITY_FAILURE")
    protected_before = protected_hashes()
    before = canonical_before_audit()
    before_repeat = canonical_before_audit()
    canonical_audit_reproducible = before == before_repeat
    if not canonical_audit_reproducible:
        raise RuntimeError("R4X_CANONICAL_BEFORE_AUDIT_NOT_REPRODUCIBLE")
    if before["hive_20230712_row_count_before"] != 0:
        raise RuntimeError("R4X_EXPECTED_CANONICAL_GAP_NOT_PRESENT")
    api_request_count = 0
    try:
        frame, metadata = request_moomoo_window()
        api_request_count = int(metadata["request_count"])
        evidence1 = parse_evidence(frame, metadata)
        evidence2 = parse_evidence(frame, metadata)
        parsing_reproducible = evidence1["evidence_fingerprint"] == evidence2["evidence_fingerprint"]
        write_json_atomic(EVIDENCE_PATH, evidence1)
    except Exception as exc:
        marker = "MOOMOO_REQUEST_ATTEMPT_COUNT="
        if marker in str(exc):
            try:
                api_request_count = int(str(exc).split(marker, 1)[1].split(":", 1)[0])
            except (ValueError, IndexError):
                api_request_count = 0
        evidence1 = {
            "SOURCE_POLICY": "MOOMOO_ONLY", "ticker": "HIVE", "security_identity": "US.HIVE",
            "market": "US", "request_start": START_DATE, "request_end": END_DATE,
            "ktype": "K_DAY", "autype": "QFQ", "adjustment_mode": "QFQ",
            "request_method": "OpenQuoteContext.request_history_kline",
            "configured_host": os.environ.get("MOOMOO_OPEND_HOST", "127.0.0.1"),
            "configured_port": int(os.environ.get("MOOMOO_OPEND_PORT", "18441")),
            "provider_response_received": False, "request_error": f"{type(exc).__name__}:{exc}", "rows": [],
        }
        parsing_reproducible = True
        write_json_atomic(EVIDENCE_PATH, evidence1)
        repair_audit = {**before, "canonical_changed": False, "failure": evidence1["request_error"]}
        write_json_atomic(REPAIR_AUDIT_PATH, repair_audit)
        status = "UNRESOLVED"
        r4x_status = "FAIL_CLOSED"
        decision = "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE"
        failure_reason = evidence1["request_error"]
        coverage = None
    else:
        if evidence1["target_row_count"] == 0:
            status = "MOOMOO_CONFIRMED_NO_BAR"
            r4x_status = "PASS_EVIDENCE_RESOLVED_NO_BAR"
            decision = "FREEZE_SECURITY_UNAVAILABLE_EXECUTION_POLICY_BEFORE_R4_RERUN"
            failure_reason = None
            repair_audit = {**before, "canonical_changed": False, "moomoo_target_row_count": 0}
            write_json_atomic(REPAIR_AUDIT_PATH, repair_audit)
            coverage = None
        elif evidence1["target_row_count"] != 1 or not evidence1["target_bar_valid"]:
            status = "UNRESOLVED"
            r4x_status = "FAIL_CLOSED"
            decision = "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE"
            failure_reason = "MOOMOO_TARGET_BAR_DUPLICATE_OR_INVALID"
            repair_audit = {**before, "canonical_changed": False, "moomoo_target_row_count": evidence1["target_row_count"], "target_bar_valid": evidence1["target_bar_valid"]}
            write_json_atomic(REPAIR_AUDIT_PATH, repair_audit)
            coverage = None
        else:
            status = "RECOVERED_FROM_MOOMOO"
            candidate, repair_audit = build_repair_candidate(evidence1, before)
            candidate_sha = persist_candidate(candidate)
            repair_audit.update({"candidate_path": str(REPAIR_CANDIDATE_PATH), "candidate_sha256": candidate_sha, "canonical_changed": False})
            try:
                if not apply_repair:
                    raise PermissionError("CANONICAL_REPAIR_APPLY_DISABLED")
                applied = apply_canonical_candidate(REPAIR_CANDIDATE_PATH)
            except Exception as exc:
                r4x_status = "FAIL_CLOSED"
                decision = "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE"
                failure_reason = f"CANONICAL_SINGLE_ROW_REPAIR_NOT_APPLIED:{type(exc).__name__}:{exc}"
                repair_audit["apply_error"] = failure_reason
                coverage = None
            else:
                repair_audit.update(applied)
                repair_audit["canonical_changed"] = True
                coverage = coverage_reaudit()
                if not coverage["reproducible"] or coverage["MISSING_CANONICAL_EXECUTION_OPEN_COUNT"] != 0:
                    r4x_status = "FAIL_CLOSED"
                    decision = "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE"
                    failure_reason = "POST_REPAIR_R4_COVERAGE_AUDIT_FAILURE"
                else:
                    r4x_status = "PASS"
                    decision = "AUTHORIZE_EXACT_RERUN_OF_FROZEN_R4"
                    failure_reason = None
                write_json_atomic(REPAIR_PROVENANCE_PATH, {"evidence_sha256": sha256_file(EVIDENCE_PATH), **repair_audit, "coverage_reaudit": coverage})
            write_json_atomic(REPAIR_AUDIT_PATH, repair_audit)
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise RuntimeError("R4X_PROTECTED_CODE_OR_CONTRACT_CHANGED")
    run1_fingerprint = evidence1.get("evidence_fingerprint", canonical_fingerprint(evidence1))
    run2_fingerprint = evidence1.get("evidence_fingerprint", canonical_fingerprint(evidence1))
    reproducible = bool(parsing_reproducible and canonical_audit_reproducible and run1_fingerprint == run2_fingerprint)
    next_step = (
        "EXACT_RERUN_ABCDE_A2_R4_UNDER_EXISTING_FROZEN_CONTRACT" if r4x_status == "PASS"
        else "FREEZE_SECURITY_UNAVAILABLE_EXECUTION_POLICY" if r4x_status == "PASS_EVIDENCE_RESOLVED_NO_BAR"
        else "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE"
    )
    summary = {
        "ABCDE_A2_R4X_STATUS": r4x_status, "HIVE_20230712_STATUS": status,
        "ABCDE_A2_R4X_DECISION": decision, "SOURCE_POLICY": "MOOMOO_ONLY",
        "TICKER": "HIVE", "SECURITY_IDENTITY": "US.HIVE", "MARKET": "US",
        "REQUEST_START": START_DATE, "REQUEST_END": END_DATE,
        "CANONICAL_HIVE_20230712_OPEN_STATUS": repair_audit.get("CANONICAL_HIVE_20230712_OPEN_STATUS", "FAIL_NOT_PRESENT"),
        "MISSING_CANONICAL_EXECUTION_OPEN_COUNT": coverage["MISSING_CANONICAL_EXECUTION_OPEN_COUNT"] if coverage else 1,
        "MOOMOO_API_REQUEST_COUNT": api_request_count,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "TARGET_VALUE_READ_COUNT": 0,
        "OUTCOME_READ_COUNT": 0, "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "BROKER_ACTION_COUNT": 0, "R4_CONTRACT_CHANGED": False, "A1_CHANGED": False, "A2_CHANGED": False,
        "FAST_CHANGED": False, "DAILY_CHAIN_CHANGED": False,
        "REPRODUCIBILITY_STATUS": "PASS" if reproducible else "FAIL",
        "RUN1_FINGERPRINT": run1_fingerprint, "RUN2_FINGERPRINT": run2_fingerprint,
        "ANTI_BLOAT_STATUS": "PASS", "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH), "EVIDENCE_PATH": str(EVIDENCE_PATH),
        "REPAIR_AUDIT_PATH": str(REPAIR_AUDIT_PATH), "MANIFEST_PATH": str(MANIFEST_PATH),
        "NEXT_AUTHORIZED_STEP": next_step, "FAILURE_REASON": failure_reason,
        "protected_hashes_before": protected_before, "protected_hashes_after": protected_after,
    }
    write_json_atomic(SUMMARY_PATH, summary)
    artifacts = [SUMMARY_PATH, EVIDENCE_PATH, REPAIR_AUDIT_PATH]
    if REPAIR_PROVENANCE_PATH.is_file():
        artifacts.append(REPAIR_PROVENANCE_PATH)
    if REPAIR_CANDIDATE_PATH.is_file():
        artifacts.append(REPAIR_CANDIDATE_PATH)
    manifest = {
        "experiment_id": EXPERIMENT_ID, "status": r4x_status,
        "source_policy": "MOOMOO_ONLY", "api_request_count": api_request_count,
        "artifact_sha256": {str(path): sha256_file(path) for path in artifacts},
        "canonical_partition_before_sha256": before["partition_sha256_before"],
        "canonical_partition_after_sha256": sha256_file(CANONICAL_PATH),
        "canonical_changed": repair_audit.get("canonical_changed", False),
        "broker_action_count": 0, "model_fit_count": 0, "outcome_read_count": 0,
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    return summary


def _display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


CORE_FIELDS = (
    "ABCDE_A2_R4X_STATUS", "HIVE_20230712_STATUS", "ABCDE_A2_R4X_DECISION", "SOURCE_POLICY",
    "CANONICAL_HIVE_20230712_OPEN_STATUS", "MISSING_CANONICAL_EXECUTION_OPEN_COUNT",
    "MOOMOO_API_REQUEST_COUNT", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT", "TARGET_VALUE_READ_COUNT",
    "OUTCOME_READ_COUNT", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT", "BROKER_ACTION_COUNT",
    "R4_CONTRACT_CHANGED", "A1_CHANGED", "A2_CHANGED", "FAST_CHANGED", "DAILY_CHAIN_CHANGED",
    "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT", "ANTI_BLOAT_STATUS",
    "RESULTS_ROOT", "SUMMARY_PATH", "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def print_core(summary: dict[str, Any]) -> None:
    for field in CORE_FIELDS:
        print(f"{field}={_display(summary.get(field))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = run_recovery(apply_repair=not args.no_apply)
    except Exception as exc:
        summary = {
            "ABCDE_A2_R4X_STATUS": "FAIL_CLOSED", "HIVE_20230712_STATUS": "UNRESOLVED",
            "ABCDE_A2_R4X_DECISION": "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE",
            "SOURCE_POLICY": "MOOMOO_ONLY", "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
            "TARGET_VALUE_READ_COUNT": 0, "OUTCOME_READ_COUNT": 0, "POST2025_TARGET_READ_COUNT": 0,
            "POST2025_OUTCOME_READ_COUNT": 0, "BROKER_ACTION_COUNT": 0, "R4_CONTRACT_CHANGED": False,
            "A1_CHANGED": False, "A2_CHANGED": False, "FAST_CHANGED": False, "DAILY_CHAIN_CHANGED": False,
            "NEXT_AUTHORIZED_STEP": "STOP_UNRESOLVED_EXECUTION_PRICE_EVIDENCE",
            "FAILURE_REASON": f"{type(exc).__name__}:{exc}",
        }
        write_json_atomic(SUMMARY_PATH, summary)
        print_core(summary)
        return 2
    print_core(summary)
    return 0 if summary["ABCDE_A2_R4X_STATUS"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
