#!/usr/bin/env python
"""V21.196 manual-approved broad daily OHLCV import for 2026-06-29/30."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from v21_194_broad_date_gate_utils import BroadDateGateError, load_latest_broad_date_gate


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.196_MANUAL_APPROVED_BROAD_DAILY_BAR_IMPORT_20260629_20260630"
OUT = ROOT / "outputs/v21/V21.196_MANUAL_APPROVED_BROAD_DAILY_BAR_IMPORT_20260629_20260630"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
MANUAL_DIR = ROOT / "inputs/manual_price_sources"
COMBINED_INPUT = MANUAL_DIR / "approved_daily_ohlcv_20260629_20260630.csv"
INPUT_20260629 = MANUAL_DIR / "approved_daily_ohlcv_20260629.csv"
INPUT_20260630 = MANUAL_DIR / "approved_daily_ohlcv_20260630.csv"
APPLY_ENV = "V21_196_APPLY_MANUAL_BROAD_BARS"
TARGET_DATES = ["2026-06-29", "2026-06-30"]
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
REQUIRED_INPUT = ["symbol", "date", "open", "high", "low", "close", "volume"]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
MIN_BROAD_SYMBOLS = 300
MIN_COVERAGE_RATIO = 0.80


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str], apply_requested: bool) -> bool:
    if apply_requested:
        return True
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.196_MANUAL_APPROVED_BROAD_DAILY_BAR_IMPORT_20260629_20260630/"
    allowed_scripts = {
        "?? scripts/v21/v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.py",
        "?? scripts/v21/run_v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.ps1",
        "?? scripts/v21/test_v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def normalize_price_panel(frame: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in frame.columns:
        low = str(col).strip().lower().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjusted_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    frame = frame.rename(columns=rename).copy()
    if "symbol" not in frame and "ticker" in frame:
        frame["symbol"] = frame["ticker"]
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col not in frame:
            frame[col] = pd.NA
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["adjusted_close"] = frame["adjusted_close"].fillna(frame["close"])
    for col in CANONICAL_FIELDS:
        if col not in frame:
            frame[col] = ""
    return frame[CANONICAL_FIELDS].dropna(subset=["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def load_canonical(path: Path | None = None) -> pd.DataFrame:
    return normalize_price_panel(pd.read_csv(path or CANONICAL, low_memory=False))


def audit_panel(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    dupes = int(frame.duplicated(["symbol", "date"]).sum()) if len(frame) else 0
    return {
        "path": rel(path),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["symbol"].nunique()) if len(frame) else 0,
        "min_date": str(frame["date"].min()) if len(frame) else "",
        "max_date": str(frame["date"].max()) if len(frame) else "",
        "duplicate_symbol_date_rows": dupes,
        "non_null_ohlcv_count": int(frame[OHLCV].notna().sum().sum()) if len(frame) else 0,
        "sha256": sha256(path),
    }


def date_coverage(frame: pd.DataFrame) -> list[dict[str, Any]]:
    universe_count = int(frame["symbol"].nunique())
    previous_broad_symbols: set[str] = set()
    rows: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        distinct = int(group["symbol"].nunique())
        duplicate_count = int(group.duplicated(["symbol", "date"]).sum())
        zero_close = int((pd.to_numeric(group["close"], errors="coerce") <= 0).sum())
        all_null_ohlcv = int(group[OHLCV].isna().all(axis=1).sum())
        coverage = distinct / universe_count if universe_count else 0.0
        coverage_prev = distinct / len(previous_broad_symbols) if previous_broad_symbols else coverage
        broad = (
            distinct >= MIN_BROAD_SYMBOLS
            and coverage >= MIN_COVERAGE_RATIO
            and duplicate_count == 0
            and zero_close == 0
            and all_null_ohlcv == 0
        )
        rows.append({
            "date": str(date),
            "price_row_count": int(len(group)),
            "distinct_symbol_count": distinct,
            "coverage_ratio_vs_canonical_universe": coverage,
            "coverage_ratio_vs_previous_broad_date_universe": coverage_prev,
            "has_duplicate_symbol_date": duplicate_count > 0,
            "duplicate_symbol_date_count": duplicate_count,
            "zero_or_negative_close_count": zero_close,
            "null_ohlcv_count": int(group[OHLCV].isna().any(axis=1).sum()),
            "all_null_ohlcv_count": all_null_ohlcv,
            "broad_price_date_eligible": broad,
        })
        if broad:
            previous_broad_symbols = set(group["symbol"].astype(str))
    return rows


def broad_gate_for_panel(frame: pd.DataFrame, stage: str = STAGE) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    coverage = date_coverage(frame)
    coverage_df = pd.DataFrame(coverage)
    raw_max = str(frame["date"].max()) if len(frame) else ""
    raw_row = coverage_df[coverage_df["date"].eq(raw_max)].iloc[0].to_dict() if raw_max and not coverage_df.empty else {}
    broad_dates = coverage_df.loc[coverage_df["broad_price_date_eligible"].astype(bool), "date"].astype(str).tolist() if not coverage_df.empty else []
    broad_latest = max(broad_dates) if broad_dates else ""
    narrow_tail = sorted(set(frame.loc[frame["date"].astype(str) > broad_latest, "date"].astype(str))) if broad_latest else []
    gate = {
        "stage": stage,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(raw_row.get("distinct_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": bool(raw_row.get("broad_price_date_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical": broad_latest,
        "feature_latest_date_momentum": broad_latest,
        "abcd_honest_latest_date": broad_latest,
        "narrow_tail_dates_must_not_be_used_for_abcde": narrow_tail,
        "blocked_newer_dates": narrow_tail,
        "integration_note": "Candidate gate generated from manually approved completed daily bars.",
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    return gate, coverage


def write_template(path: Path) -> None:
    rows = [
        {"symbol": "AAPL", "date": "2026-06-29", "open": "", "high": "", "low": "", "close": "", "volume": ""},
        {"symbol": "AAPL", "date": "2026-06-30", "open": "", "high": "", "low": "", "close": "", "volume": ""},
    ]
    write_csv(path, rows, REQUIRED_INPUT)


def input_inventory() -> list[dict[str, Any]]:
    files = [COMBINED_INPUT, INPUT_20260629, INPUT_20260630]
    return [{
        "input_path": rel(path),
        "exists": path.is_file(),
        "row_count": int(len(pd.read_csv(path))) if path.is_file() else 0,
        "sha256": sha256(path),
    } for path in files]


def load_manual_inputs() -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    files = [path for path in [COMBINED_INPUT, INPUT_20260629, INPUT_20260630] if path.is_file()]
    rows: list[pd.DataFrame] = []
    errors: list[dict[str, Any]] = []
    for path in files:
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            errors.append({"input_path": rel(path), "row_number": "", "symbol": "", "date": "", "error": f"READ_FAILED:{exc}"})
            continue
        frame["source_file"] = rel(path)
        rows.append(frame)
    if not rows:
        return pd.DataFrame(), errors, []
    raw = pd.concat(rows, ignore_index=True)
    normalized = normalize_manual_rows(raw)
    return normalized, errors, normalized.to_dict("records")


def normalize_manual_rows(raw: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in raw.columns:
        low = str(col).strip().lower().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjusted_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    frame = raw.rename(columns=rename).copy()
    if "symbol" not in frame:
        frame["symbol"] = ""
    if "date" not in frame:
        frame["date"] = ""
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in frame:
            frame[col] = pd.NA
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if "adjusted_close" not in frame:
        frame["adjusted_close"] = frame["close"]
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce").fillna(frame["close"])
    if "source_file" not in frame:
        frame["source_file"] = ""
    return frame[["source_file", "symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"]].reset_index(drop=True)


def validate_manual_rows(frame: pd.DataFrame, canonical_symbols: set[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame]:
    errors: list[dict[str, Any]] = []
    if frame.empty:
        return frame.copy(), errors, frame.copy()
    duplicate_mask = frame.duplicated(["symbol", "date"], keep=False)
    valid_mask = pd.Series(True, index=frame.index)
    for idx, row in frame.iterrows():
        row_errors: list[str] = []
        symbol = str(row.get("symbol", ""))
        date = str(row.get("date", ""))
        if date not in TARGET_DATES:
            row_errors.append("DATE_NOT_ALLOWED")
        if symbol not in canonical_symbols:
            row_errors.append("SYMBOL_NOT_IN_CANONICAL_UNIVERSE")
        for col in ["open", "high", "low", "close", "volume"]:
            if pd.isna(row.get(col)):
                row_errors.append(f"{col.upper()}_NOT_NUMERIC")
        if not pd.isna(row.get("close")) and float(row["close"]) <= 0:
            row_errors.append("CLOSE_NON_POSITIVE")
        for col in ["open", "high", "low"]:
            if not pd.isna(row.get(col)) and float(row[col]) <= 0:
                row_errors.append(f"{col.upper()}_NON_POSITIVE")
        if not any(pd.isna(row.get(col)) for col in ["open", "high", "low", "close"]):
            if float(row["high"]) < float(row["low"]):
                row_errors.append("HIGH_BELOW_LOW")
            if float(row["high"]) < float(row["open"]) or float(row["high"]) < float(row["close"]):
                row_errors.append("HIGH_BELOW_OPEN_OR_CLOSE")
            if float(row["low"]) > float(row["open"]) or float(row["low"]) > float(row["close"]):
                row_errors.append("LOW_ABOVE_OPEN_OR_CLOSE")
        if not pd.isna(row.get("volume")) and float(row["volume"]) < 0:
            row_errors.append("VOLUME_NEGATIVE")
        if bool(duplicate_mask.loc[idx]):
            row_errors.append("DUPLICATE_SYMBOL_DATE")
        if row_errors:
            valid_mask.loc[idx] = False
            errors.append({
                "source_file": row.get("source_file", ""),
                "row_number": int(idx) + 2,
                "symbol": symbol,
                "date": date,
                "error": "|".join(row_errors),
            })
    return frame.loc[valid_mask].copy(), errors, frame.loc[~valid_mask].copy()


def make_append_rows(valid_rows: pd.DataFrame) -> pd.DataFrame:
    if valid_rows.empty:
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    frame = valid_rows.copy()
    frame["source_provider"] = "MANUAL_APPROVED_DAILY_OHLCV"
    frame["source_artifact"] = frame["source_file"]
    frame["refresh_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frame["price_row_status"] = "MANUAL_APPROVED_COMPLETED_DAILY_BAR"
    frame["row_hash"] = [
        hashlib.sha256(f"{r.symbol}|{r.date}|{r.open}|{r.high}|{r.low}|{r.close}|{r.volume}".encode("utf-8")).hexdigest()
        for r in frame.itertuples(index=False)
    ]
    return frame[CANONICAL_FIELDS].sort_values(["symbol", "date"]).reset_index(drop=True)


def make_candidate(base: pd.DataFrame, append_rows: pd.DataFrame) -> pd.DataFrame:
    if append_rows.empty:
        return base.iloc[0:0].copy()
    keys = set(zip(append_rows["symbol"].astype(str), append_rows["date"].astype(str)))
    existing_same_key = base.apply(lambda row: (str(row["symbol"]), str(row["date"])) in keys, axis=1)
    retained = base.loc[~existing_same_key].copy()
    candidate = pd.concat([retained, append_rows], ignore_index=True)
    return normalize_price_panel(candidate).sort_values(["symbol", "date"]).reset_index(drop=True)


def coverage_for_import(append_rows: pd.DataFrame, universe_count: int) -> list[dict[str, Any]]:
    rows = []
    for date in TARGET_DATES:
        group = append_rows[append_rows["date"].astype(str).eq(date)] if not append_rows.empty else append_rows
        symbols = int(group["symbol"].nunique()) if len(group) else 0
        ratio = symbols / universe_count if universe_count else 0.0
        rows.append({
            "date": date,
            "imported_symbol_count": symbols,
            "canonical_universe_count": universe_count,
            "coverage_ratio": ratio,
            "broad_eligible": symbols >= MIN_BROAD_SYMBOLS and ratio >= MIN_COVERAGE_RATIO,
        })
    return rows


def apply_candidate(candidate_path: Path, candidate: pd.DataFrame, candidate_valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPLY_ENV, "").upper() == "TRUE"
    audit = {
        "apply_requested": requested,
        "apply_succeeded": False,
        "backup_created": False,
        "restored_after_failed_apply": False,
        "backup_path": "",
        "apply_note": "",
    }
    if not requested:
        audit["apply_note"] = f"Dry mode. Set {APPLY_ENV}=TRUE to apply."
        return audit
    if not candidate_valid or not candidate_path.is_file() or candidate.empty:
        audit["apply_note"] = "REFUSED_INVALID_OR_EMPTY_CANDIDATE"
        return audit
    backup = OUT / "canonical_backup_before_v21_196_manual_broad_bar_apply.csv"
    shutil.copy2(CANONICAL, backup)
    audit["backup_created"] = True
    audit["backup_path"] = rel(backup)
    shutil.copy2(candidate_path, CANONICAL)
    after = load_canonical()
    after_gate, _coverage = broad_gate_for_panel(after, f"{STAGE}_APPLIED_VERIFY")
    ok = (
        len(after) == len(candidate)
        and int(after.duplicated(["symbol", "date"]).sum()) == 0
        and after_gate["broad_price_latest_date"] >= "2026-06-29"
        and str(after["date"].max()) >= str(candidate["date"].max())
    )
    if ok:
        audit["apply_succeeded"] = True
        audit["apply_note"] = "APPLIED_AND_VERIFIED"
    else:
        shutil.copy2(backup, CANONICAL)
        audit["restored_after_failed_apply"] = True
        audit["apply_note"] = "VERIFY_FAILED_RESTORED_BACKUP"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"canonical_broad_latest_date_before={summary['canonical_broad_latest_date_before']}",
        f"candidate_broad_price_latest_date={summary['candidate_broad_price_latest_date']}",
        f"candidate_valid={summary['candidate_valid']}",
        f"apply_requested={summary['apply_requested']}",
        f"apply_succeeded={summary['apply_succeeded']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.196_manual_approved_broad_daily_bar_import_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    before = load_canonical()
    before_audit = audit_panel(before, CANONICAL)
    write_csv(OUT / "canonical_before_v21_196_audit.csv", [before_audit])
    try:
        gate_before = load_latest_broad_date_gate()
    except BroadDateGateError:
        gate_before, _ = broad_gate_for_panel(before, f"{STAGE}_BEFORE_FALLBACK")
    write_csv(OUT / "manual_input_file_inventory.csv", input_inventory())
    write_template(OUT / "manual_import_schema_template_20260629_20260630.csv")

    files_exist = COMBINED_INPUT.is_file() or INPUT_20260629.is_file() or INPUT_20260630.is_file()
    normalized = pd.DataFrame()
    read_errors: list[dict[str, Any]] = []
    valid_rows = pd.DataFrame()
    rejected = pd.DataFrame()
    validation_errors: list[dict[str, Any]] = []
    append_rows = pd.DataFrame(columns=CANONICAL_FIELDS)
    candidate = pd.DataFrame(columns=CANONICAL_FIELDS)
    candidate_gate = {
        "raw_canonical_max_date": "",
        "broad_price_latest_date": "",
        "abcd_honest_latest_date": "",
    }
    candidate_coverage: list[dict[str, Any]] = []
    candidate_valid = False
    candidate_created = False

    if files_exist:
        normalized, read_errors, _records = load_manual_inputs()
        normalized.to_csv(OUT / "manual_import_normalized_rows.csv", index=False)
        valid_rows, validation_errors, rejected = validate_manual_rows(normalized, set(before["symbol"].astype(str)))
        validation_errors = read_errors + validation_errors
        valid_rows.to_csv(OUT / "manual_import_valid_rows.csv", index=False)
        rejected.to_csv(OUT / "manual_import_rejected_rows.csv", index=False)
        append_rows = make_append_rows(valid_rows)
        if len(append_rows):
            append_rows.to_csv(OUT / "candidate_append_rows_20260629_20260630.csv", index=False)
            candidate = make_candidate(before, append_rows)
            candidate_path = OUT / "candidate_canonical_with_manual_bars.csv"
            candidate.to_csv(candidate_path, index=False)
            candidate_created = True
            candidate_audit = audit_panel(candidate, candidate_path)
            write_csv(OUT / "candidate_canonical_audit.csv", [candidate_audit])
            candidate_gate, candidate_coverage = broad_gate_for_panel(candidate, f"{STAGE}_CANDIDATE")
            write_csv(OUT / "candidate_broad_date_coverage_audit.csv", candidate_coverage)
            write_json(OUT / "candidate_latest_broad_date_gate.json", candidate_gate)
            candidate_valid = (
                int(candidate_audit["duplicate_symbol_date_rows"]) == 0
                and int(candidate_audit["row_count"]) >= int(before_audit["row_count"])
                and str(candidate_gate["broad_price_latest_date"]) >= "2026-06-29"
            )
        else:
            write_csv(OUT / "candidate_canonical_audit.csv", [])
            write_csv(OUT / "candidate_broad_date_coverage_audit.csv", [])
            write_json(OUT / "candidate_latest_broad_date_gate.json", candidate_gate)
    else:
        write_csv(OUT / "manual_import_valid_rows.csv", [])
        write_csv(OUT / "manual_import_rejected_rows.csv", [])
        write_csv(OUT / "candidate_canonical_audit.csv", [])
        write_csv(OUT / "candidate_broad_date_coverage_audit.csv", [])
        write_json(OUT / "candidate_latest_broad_date_gate.json", candidate_gate)

    write_csv(OUT / "manual_import_validation_errors.csv", validation_errors, ["source_file", "row_number", "symbol", "date", "error", "input_path"])
    coverage_rows = coverage_for_import(append_rows, int(before["symbol"].nunique()))
    write_csv(OUT / "manual_import_per_date_coverage_audit.csv", coverage_rows)

    candidate_path = OUT / "candidate_canonical_with_manual_bars.csv"
    apply_audit = apply_candidate(candidate_path, candidate, candidate_valid)
    write_csv(OUT / "manual_broad_bars_apply_audit.csv", [apply_audit])
    after = load_canonical()
    after_latest = str(after["date"].max()) if len(after) else ""
    latest_gate_created = (OUT / "candidate_latest_broad_date_gate.json").is_file()

    if not files_exist:
        final_status = "PARTIAL_PASS_V21_196_WAIT_MANUAL_APPROVED_PRICE_SOURCE"
        final_decision = "MANUAL_PRICE_TEMPLATE_READY_IMPORT_NOT_ATTEMPTED"
    elif apply_audit["apply_requested"] and apply_audit["restored_after_failed_apply"]:
        final_status = "FAIL_V21_196_APPLY_VERIFICATION_FAILED_RESTORED_BACKUP"
        final_decision = "CANONICAL_RESTORED_DO_NOT_USE_MANUAL_IMPORT"
    elif apply_audit["apply_succeeded"] and candidate_gate.get("broad_price_latest_date", "") >= "2026-06-29":
        final_status = "PASS_V21_196_MANUAL_BROAD_BARS_APPLIED"
        final_decision = "CANONICAL_BROAD_DATE_ADVANCED_READY_FOR_ABCDE_RERUN_RESEARCH_ONLY"
    elif candidate_valid:
        final_status = "PARTIAL_PASS_V21_196_MANUAL_BROAD_BAR_CANDIDATE_READY_NOT_APPLIED"
        final_decision = "MANUAL_BROAD_BAR_CANDIDATE_READY_FOR_GUARDED_APPLY"
    else:
        final_status = "FAIL_V21_196_MANUAL_BROAD_BAR_VALIDATION_FAILED"
        final_decision = "DO_NOT_APPLY_INVALID_MANUAL_PRICE_SOURCE"

    by_date = {row["date"]: row for row in coverage_rows}
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date_before": before_audit["max_date"],
        "canonical_broad_latest_date_before": gate_before.get("broad_price_latest_date", ""),
        "abcd_honest_latest_date_before": gate_before.get("abcd_honest_latest_date", ""),
        "manual_input_combined_file_exists": COMBINED_INPUT.is_file(),
        "manual_input_20260629_file_exists": INPUT_20260629.is_file(),
        "manual_input_20260630_file_exists": INPUT_20260630.is_file(),
        "manual_import_attempted": files_exist,
        "manual_import_valid_row_count": int(len(valid_rows)),
        "manual_import_rejected_row_count": int(len(rejected)) + len(read_errors),
        "imported_date_count": int(append_rows["date"].nunique()) if len(append_rows) else 0,
        "imported_20260629_symbol_count": int(by_date["2026-06-29"]["imported_symbol_count"]),
        "imported_20260630_symbol_count": int(by_date["2026-06-30"]["imported_symbol_count"]),
        "imported_20260629_coverage_ratio": float(by_date["2026-06-29"]["coverage_ratio"]),
        "imported_20260630_coverage_ratio": float(by_date["2026-06-30"]["coverage_ratio"]),
        "candidate_created": candidate_created,
        "candidate_valid": bool(candidate_valid),
        "candidate_raw_max_date": candidate_gate.get("raw_canonical_max_date", ""),
        "candidate_broad_price_latest_date": candidate_gate.get("broad_price_latest_date", ""),
        "candidate_abcd_honest_latest_date": candidate_gate.get("abcd_honest_latest_date", ""),
        "candidate_duplicate_symbol_date_rows": int(candidate.duplicated(["symbol", "date"]).sum()) if len(candidate) else 0,
        "apply_requested": bool(apply_audit["apply_requested"]),
        "apply_succeeded": bool(apply_audit["apply_succeeded"]),
        "backup_created": bool(apply_audit["backup_created"]),
        "restored_after_failed_apply": bool(apply_audit["restored_after_failed_apply"]),
        "canonical_latest_date_after": after_latest,
        "latest_broad_date_gate_created": latest_gate_created,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(git_status(), baseline, bool(apply_audit["apply_requested"])),
    }
    write_json(OUT / "v21_196_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "canonical_broad_latest_date_before",
        "abcd_honest_latest_date_before", "manual_input_combined_file_exists",
        "manual_input_20260629_file_exists", "manual_input_20260630_file_exists",
        "manual_import_attempted", "manual_import_valid_row_count", "manual_import_rejected_row_count",
        "imported_20260629_symbol_count", "imported_20260629_coverage_ratio",
        "imported_20260630_symbol_count", "imported_20260630_coverage_ratio",
        "candidate_created", "candidate_valid", "candidate_broad_price_latest_date",
        "candidate_abcd_honest_latest_date", "apply_requested", "apply_succeeded",
        "canonical_latest_date_after", "official_adoption_allowed", "broker_action_allowed",
        "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
