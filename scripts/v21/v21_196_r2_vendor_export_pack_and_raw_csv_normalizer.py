#!/usr/bin/env python
"""V21.196 R2 vendor export pack and raw CSV normalizer."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.196_R2_VENDOR_EXPORT_PACK_AND_RAW_CSV_NORMALIZER"
OUT = ROOT / "outputs/v21/V21.196_R2_VENDOR_EXPORT_PACK_AND_RAW_CSV_NORMALIZER"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
MANUAL_DIR = ROOT / "inputs/manual_price_sources"
APPROVED_PATH = MANUAL_DIR / "approved_daily_ohlcv_20260629_20260630.csv"
APPROVE_ENV = "V21_196_R2_APPROVE_VENDOR_NORMALIZED_CSV"
TARGET_DATES = ["2026-06-29", "2026-06-30"]
MIN_COVERAGE_RATIO = 0.80
REQUIRED = ["symbol", "date", "open", "high", "low", "close", "volume"]
AUDIT_COLS = REQUIRED + ["source_provider", "source_file"]
RAW_INPUTS = [
    "raw_moomoo_ohlcv_20260629_20260630.csv",
    "raw_tradingview_ohlcv_20260629_20260630.csv",
    "raw_vendor_ohlcv_20260629_20260630.csv",
    "raw_broker_ohlcv_20260629_20260630.csv",
    "raw_moomoo_ohlcv_20260629.csv",
    "raw_moomoo_ohlcv_20260630.csv",
    "raw_tradingview_ohlcv_20260629.csv",
    "raw_tradingview_ohlcv_20260630.csv",
    "raw_vendor_ohlcv_20260629.csv",
    "raw_vendor_ohlcv_20260630.csv",
]

SYMBOL_ALIASES = {
    "symbol", "ticker", "code", "instrument", "instrument_code", "stock_code", "security_code",
    "銘柄コード", "コード", "股票代码", "代码",
}
DATE_ALIASES = {"date", "time", "datetime", "trading_date", "trade_date", "日付", "日期"}
OPEN_ALIASES = {"open", "始値", "开盘价"}
HIGH_ALIASES = {"high", "高値", "最高价"}
LOW_ALIASES = {"low", "安値", "最低价"}
CLOSE_ALIASES = {"close", "last", "last_price", "終値", "收盘价"}
VOLUME_ALIASES = {"volume", "vol", "vol.", "turnover_volume", "出来高", "成交量"}


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


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefixes = (
        "?? outputs/v21/V21.196_R2_VENDOR_EXPORT_PACK_AND_RAW_CSV_NORMALIZER/",
        "?? inputs/manual_price_sources/vendor_export_",
        " M inputs/manual_price_sources/vendor_export_",
        "?? inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
        " M inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
    )
    allowed_scripts = {
        "?? scripts/v21/v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py",
        "?? scripts/v21/run_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.ps1",
        "?? scripts/v21/test_v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized in allowed_scripts or normalized.startswith(allowed_prefixes):
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def canonical_symbols(path: Path | None = None) -> list[str]:
    path = path or CANONICAL
    df = pd.read_csv(path, usecols=["symbol"], low_memory=False)
    return sorted(df["symbol"].dropna().astype(str).str.upper().str.strip().unique())


def symbol_variants(symbol: str) -> set[str]:
    sym = str(symbol).upper().strip()
    return {sym, sym.replace(".", "-"), sym.replace("-", ".")}


def canonical_symbol_lookup(symbols: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for sym in symbols:
        for variant in symbol_variants(sym):
            lookup[variant] = sym
    return lookup


def normalize_symbol(raw: Any, lookup: dict[str, str]) -> str:
    sym = str(raw).strip().upper()
    if ":" in sym:
        sym = sym.split(":")[-1]
    if sym.startswith("US."):
        sym = sym[3:]
    if sym.endswith(".US"):
        sym = sym[:-3]
    sym = sym.strip()
    return lookup.get(sym, lookup.get(sym.replace("-", "."), lookup.get(sym.replace(".", "-"), sym)))


def normalize_col_name(col: Any) -> str:
    return str(col).strip().lower().replace(" ", "_")


def column_mapping(columns: Iterable[Any]) -> tuple[dict[Any, str], list[str]]:
    mapping: dict[Any, str] = {}
    errors: list[str] = []
    seen_targets: set[str] = set()
    alias_groups = [
        ("symbol", SYMBOL_ALIASES),
        ("date", DATE_ALIASES),
        ("open", OPEN_ALIASES),
        ("high", HIGH_ALIASES),
        ("low", LOW_ALIASES),
        ("close", CLOSE_ALIASES),
        ("volume", VOLUME_ALIASES),
    ]
    for col in columns:
        norm = normalize_col_name(col)
        for target, aliases in alias_groups:
            if norm in aliases or str(col).strip() in aliases:
                if target in seen_targets:
                    errors.append(f"DUPLICATE_ALIAS_FOR_{target.upper()}:{col}")
                else:
                    mapping[col] = target
                    seen_targets.add(target)
                break
    missing = [field for field in REQUIRED if field not in seen_targets]
    errors.extend([f"MISSING_COLUMN_{field.upper()}" for field in missing])
    return mapping, errors


def infer_provider(path: Path) -> str:
    name = path.name.lower()
    if "moomoo" in name:
        return "LOCAL_VENDOR_MOOMOO"
    if "tradingview" in name:
        return "LOCAL_VENDOR_TRADINGVIEW"
    if "broker" in name:
        return "LOCAL_VENDOR_BROKER"
    return "LOCAL_VENDOR_APPROVED"


def normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def normalize_vendor_frame(raw: pd.DataFrame, source_file: Path, lookup: dict[str, str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    mapping, schema_errors = column_mapping(raw.columns)
    provider = infer_provider(source_file)
    errors = [{"source_file": rel(source_file), "row_number": "", "symbol": "", "date": "", "error": err} for err in schema_errors]
    if schema_errors:
        return pd.DataFrame(columns=AUDIT_COLS), errors
    frame = raw.rename(columns=mapping)[REQUIRED].copy()
    frame["symbol"] = frame["symbol"].map(lambda item: normalize_symbol(item, lookup))
    frame["date"] = frame["date"].map(normalize_date)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["source_provider"] = provider
    frame["source_file"] = rel(source_file)
    return frame[AUDIT_COLS], errors


def validate_rows(frame: pd.DataFrame, canonical_set: set[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame]:
    if frame.empty:
        return frame.copy(), [], frame.copy()
    duplicate_mask = frame.duplicated(["symbol", "date"], keep=False)
    valid_mask = pd.Series(True, index=frame.index)
    errors: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        row_errors: list[str] = []
        symbol = str(row.get("symbol", ""))
        date = str(row.get("date", ""))
        if date not in TARGET_DATES:
            row_errors.append("DATE_NOT_ALLOWED")
        if symbol not in canonical_set:
            row_errors.append("SYMBOL_NOT_IN_CANONICAL_UNIVERSE")
        for col in ["open", "high", "low", "close", "volume"]:
            if pd.isna(row.get(col)):
                row_errors.append(f"{col.upper()}_NOT_NUMERIC")
        for col in ["open", "high", "low", "close"]:
            if not pd.isna(row.get(col)) and float(row[col]) <= 0:
                row_errors.append(f"{col.upper()}_NON_POSITIVE")
        if not pd.isna(row.get("volume")) and float(row["volume"]) < 0:
            row_errors.append("VOLUME_NEGATIVE")
        if not any(pd.isna(row.get(col)) for col in ["open", "high", "low", "close"]):
            if float(row["high"]) < float(row["low"]):
                row_errors.append("HIGH_BELOW_LOW")
            if float(row["high"]) < float(row["open"]) or float(row["high"]) < float(row["close"]):
                row_errors.append("HIGH_BELOW_OPEN_OR_CLOSE")
            if float(row["low"]) > float(row["open"]) or float(row["low"]) > float(row["close"]):
                row_errors.append("LOW_ABOVE_OPEN_OR_CLOSE")
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


def vendor_symbol_rows(symbols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for sym in symbols:
        needs_manual = "." in sym or "-" in sym
        rows.append({
            "canonical_symbol": sym,
            "moomoo_symbol_guess": f"US.{sym}",
            "tradingview_symbol_guess": f"NASDAQ:{sym}",
            "stooq_symbol_guess": f"{sym.lower().replace('.', '-')}.us",
            "yahoo_symbol_guess": sym.replace(".", "-"),
            "needs_manual_mapping": bool(needs_manual),
        })
    return rows


def create_export_pack(symbols: list[str]) -> tuple[Path, Path]:
    rows = vendor_symbol_rows(symbols)
    map_path = MANUAL_DIR / "vendor_export_symbol_list_canonical_universe.csv"
    txt_path = MANUAL_DIR / "vendor_export_symbol_list_canonical_universe.txt"
    template_path = MANUAL_DIR / "vendor_export_template_20260629_20260630.csv"
    write_csv(map_path, rows)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    write_csv(template_path, [
        {"symbol": symbols[0] if symbols else "AAPL", "date": "2026-06-29", "open": "", "high": "", "low": "", "close": "", "volume": ""},
        {"symbol": symbols[0] if symbols else "AAPL", "date": "2026-06-30", "open": "", "high": "", "low": "", "close": "", "volume": ""},
    ], REQUIRED)
    write_csv(OUT / "canonical_universe_vendor_symbol_map.csv", rows)
    instructions = [
        "V21.196_R2 vendor export instructions",
        "Export completed daily OHLCV bars for 2026-06-29 and 2026-06-30 only.",
        "Use the canonical universe symbol list in inputs/manual_price_sources/vendor_export_symbol_list_canonical_universe.csv.",
        "Place raw exports in inputs/manual_price_sources using one accepted raw_* filename.",
        "Do not forward-fill or infer missing symbols. Missing rows will fail coverage if below 0.80.",
        f"After candidate validation passes, set {APPROVE_ENV}=TRUE to write the approved V21.196 CSV.",
    ]
    (OUT / "vendor_export_instructions.txt").write_text("\n".join(instructions) + "\n", encoding="utf-8")
    return map_path, template_path


def raw_inventory() -> list[dict[str, Any]]:
    rows = []
    for name in RAW_INPUTS:
        path = MANUAL_DIR / name
        rows.append({
            "path": rel(path),
            "exists": path.is_file(),
            "row_count": int(len(pd.read_csv(path))) if path.is_file() else 0,
            "provider_guess": infer_provider(path),
        })
    return rows


def load_raw_vendor_files(lookup: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    raw_frames: list[pd.DataFrame] = []
    normalized_frames: list[pd.DataFrame] = []
    normalization_errors: list[dict[str, Any]] = []
    read_errors: list[dict[str, Any]] = []
    for name in RAW_INPUTS:
        path = MANUAL_DIR / name
        if not path.is_file():
            continue
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            read_errors.append({"source_file": rel(path), "row_number": "", "symbol": "", "date": "", "error": f"READ_FAILED:{exc}"})
            continue
        raw_copy = raw.copy()
        raw_copy["source_file"] = rel(path)
        raw_copy["source_provider"] = infer_provider(path)
        raw_frames.append(raw_copy)
        normalized, errors = normalize_vendor_frame(raw, path, lookup)
        normalized_frames.append(normalized)
        normalization_errors.extend(errors)
    raw_all = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
    norm_all = pd.concat(normalized_frames, ignore_index=True) if normalized_frames else pd.DataFrame(columns=AUDIT_COLS)
    return raw_all, norm_all, normalization_errors + read_errors, read_errors


def coverage_rows(frame: pd.DataFrame, canonical_count: int) -> list[dict[str, Any]]:
    rows = []
    for date in TARGET_DATES:
        count = int(frame.loc[frame["date"].eq(date), "symbol"].nunique()) if not frame.empty else 0
        ratio = count / canonical_count if canonical_count else 0.0
        rows.append({
            "date": date,
            "symbol_count": count,
            "canonical_symbol_count": canonical_count,
            "coverage_ratio": ratio,
            "broad_eligible": ratio >= MIN_COVERAGE_RATIO,
        })
    return rows


def approve_candidate(candidate_path: Path, candidate_valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPROVE_ENV, "").upper() == "TRUE"
    audit = {
        "approved_write_requested": requested,
        "approved_write_succeeded": False,
        "candidate_path": rel(candidate_path),
        "approved_path": rel(APPROVED_PATH),
        "write_note": "",
    }
    if not requested:
        audit["write_note"] = f"Dry mode. Set {APPROVE_ENV}=TRUE to approve."
        return audit
    if not candidate_valid or not candidate_path.is_file():
        audit["write_note"] = "REFUSED_INVALID_OR_MISSING_CANDIDATE"
        return audit
    APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_path, APPROVED_PATH)
    audit["approved_write_succeeded"] = APPROVED_PATH.is_file()
    audit["write_note"] = "APPROVED_VENDOR_CSV_WRITTEN" if audit["approved_write_succeeded"] else "WRITE_FAILED"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"export_pack_created={summary['export_pack_created']}",
        f"raw_vendor_files_found={summary['raw_vendor_files_found']}",
        f"candidate_valid={summary['candidate_valid']}",
        f"approved_write_requested={summary['approved_write_requested']}",
        f"approved_write_succeeded={summary['approved_write_succeeded']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.196_R2_vendor_export_pack_and_raw_csv_normalizer_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    symbols = canonical_symbols()
    lookup = canonical_symbol_lookup(symbols)
    symbol_list_path, template_path = create_export_pack(symbols)
    inventory = raw_inventory()
    write_csv(OUT / "raw_vendor_file_inventory.csv", inventory)
    files_found = int(sum(1 for row in inventory if row["exists"]))

    raw_rows, normalized, normalization_errors, _read_errors = load_raw_vendor_files(lookup)
    if files_found:
        raw_rows.to_csv(OUT / "raw_vendor_rows_loaded.csv", index=False)
        normalized.to_csv(OUT / "normalized_vendor_rows.csv", index=False)
    valid, validation_errors, rejected = validate_rows(normalized, set(symbols))
    write_csv(OUT / "vendor_normalization_errors.csv", normalization_errors, ["source_file", "row_number", "symbol", "date", "error"])
    write_csv(OUT / "vendor_validation_errors.csv", validation_errors, ["source_file", "row_number", "symbol", "date", "error"])
    valid.to_csv(OUT / "vendor_valid_rows.csv", index=False)
    rejected.to_csv(OUT / "vendor_rejected_rows.csv", index=False)
    coverage = coverage_rows(valid, len(symbols))
    write_csv(OUT / "vendor_per_date_coverage_audit.csv", coverage)

    candidate_path = OUT / "candidate_daily_ohlcv_20260629_20260630_from_vendor.csv"
    candidate_created = not valid.empty
    if candidate_created:
        valid[AUDIT_COLS].sort_values(["symbol", "date"]).to_csv(candidate_path, index=False)
    duplicate_count = int(valid.duplicated(["symbol", "date"]).sum()) if not valid.empty else 0
    by_date = {row["date"]: row for row in coverage}
    candidate_valid = (
        candidate_created
        and duplicate_count == 0
        and not validation_errors
        and by_date["2026-06-29"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
        and by_date["2026-06-30"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
    )
    approve_audit = approve_candidate(candidate_path, candidate_valid)
    write_csv(OUT / "approved_csv_write_audit.csv", [approve_audit])

    if files_found == 0:
        final_status = "PARTIAL_PASS_V21_196_R2_EXPORT_PACK_READY_WAIT_VENDOR_CSV"
        final_decision = "EXPORT_SYMBOL_LIST_AND_PLACE_VENDOR_CSV_IN_INPUTS"
    elif candidate_valid and approve_audit["approved_write_succeeded"]:
        final_status = "PASS_V21_196_R2_APPROVED_VENDOR_CSV_CREATED"
        final_decision = "APPROVED_VENDOR_CSV_READY_FOR_V21_196_IMPORT"
    elif candidate_valid:
        final_status = "PARTIAL_PASS_V21_196_R2_VENDOR_CANDIDATE_READY_NOT_APPROVED"
        final_decision = "REVIEW_VENDOR_CANDIDATE_THEN_SET_APPROVE_FLAG"
    else:
        final_status = "FAIL_V21_196_R2_VENDOR_CSV_VALIDATION_FAILED"
        final_decision = "FIX_VENDOR_CSV_OR_EXPORT_BROADER_SYMBOL_COVERAGE"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_symbol_count": len(symbols),
        "export_pack_created": symbol_list_path.is_file() and template_path.is_file(),
        "vendor_symbol_list_path": rel(symbol_list_path),
        "vendor_template_path": rel(template_path),
        "raw_vendor_files_found": files_found,
        "raw_vendor_rows_loaded": int(len(raw_rows)),
        "normalized_row_count": int(len(normalized)),
        "valid_row_count": int(len(valid)),
        "rejected_row_count": int(len(rejected)) + len(normalization_errors),
        "duplicate_symbol_date_rows": duplicate_count,
        "imported_20260629_symbol_count": int(by_date["2026-06-29"]["symbol_count"]),
        "imported_20260630_symbol_count": int(by_date["2026-06-30"]["symbol_count"]),
        "imported_20260629_coverage_ratio": float(by_date["2026-06-29"]["coverage_ratio"]),
        "imported_20260630_coverage_ratio": float(by_date["2026-06-30"]["coverage_ratio"]),
        "candidate_created": candidate_created,
        "candidate_valid": candidate_valid,
        "candidate_path": rel(candidate_path),
        "approved_write_requested": bool(approve_audit["approved_write_requested"]),
        "approved_write_succeeded": bool(approve_audit["approved_write_succeeded"]),
        "approved_path": rel(APPROVED_PATH),
        "ready_for_v21_196_import": bool(approve_audit["approved_write_succeeded"]),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(git_status(), baseline),
    }
    write_json(OUT / "v21_196_r2_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "export_pack_created", "vendor_symbol_list_path",
        "vendor_template_path", "raw_vendor_files_found", "raw_vendor_rows_loaded",
        "normalized_row_count", "valid_row_count", "rejected_row_count",
        "imported_20260629_symbol_count", "imported_20260629_coverage_ratio",
        "imported_20260630_symbol_count", "imported_20260630_coverage_ratio",
        "candidate_valid", "candidate_path", "approved_write_requested", "approved_write_succeeded",
        "approved_path", "ready_for_v21_196_import", "official_adoption_allowed",
        "broker_action_allowed", "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
