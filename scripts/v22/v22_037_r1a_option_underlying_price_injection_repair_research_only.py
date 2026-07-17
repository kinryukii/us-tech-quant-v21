#!/usr/bin/env python
"""V22.037 R1A underlying price injection repair research-only."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


MODULE_NAME = "OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY"
STAGE = "V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE
DEFAULT_INPUT_REL = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY" / "v22_option_quote_enrichment_clean.csv"

PASS_STATUS = "PASS_V22_037_R1A_UNDERLYING_PRICE_INJECTED_READY_FOR_IV_RERUN"
WARN_STATUS = "WARN_V22_037_R1A_UNDERLYING_PRICE_PARTIAL_INJECTION"
FAIL_NO_SOURCE = "FAIL_V22_037_R1A_NO_UNDERLYING_PRICE_SOURCE_FOUND"
FAIL_INPUT = "FAIL_V22_037_R1A_INPUT_NOT_FOUND"
PASS_DECISION = "UNDERLYING_PRICE_INJECTED_RERUN_SYNTHETIC_IV_RESEARCH_ONLY"
WARN_DECISION = "UNDERLYING_PRICE_PARTIAL_REPAIR_REVIEW_RESEARCH_ONLY"
NO_SOURCE_DECISION = "NO_UNDERLYING_PRICE_SOURCE_RESEARCH_ONLY"
INPUT_DECISION = "INPUT_NOT_FOUND_RESEARCH_ONLY"

PRICE_ALIASES = ["underlying_price", "underlying_spot", "underlying_last", "underlying_quote", "spot", "spot_price", "last_price_underlying", "underlying_mid", "stock_price", "etf_price", "price_underlying", "selected_underlying_spot", "selected_refreshed_underlying_spot"]
UNDERLYING_ALIASES = ["underlying", "underlying_symbol", "root_symbol", "ticker", "symbol", "underlying_ticker", "requested_underlying_symbol", "normalized_underlying_symbol"]
SNAPSHOT_PRICE_ALIASES = ["price", "last", "last_price", "spot", "spot_price", "underlying_price", "close", "cur_price", "selected_underlying_spot", "selected_refreshed_underlying_spot", "refreshed_last_price"]
TIME_ALIASES = ["quote_datetime", "timestamp", "quote_time", "market_datetime", "enrichment_time_utc", "data_time", "datetime", "quote_timestamp", "refreshed_quote_timestamp", "refresh_timestamp_local"]
OPTION_ROW_MARKERS = {"option_code", "contract_code", "strike", "strike_price", "expiry", "expiration", "expiry_date", "option_type", "call_put", "cp", "right"}
OUTPUT_EXTRA = ["underlying_price", "underlying_price_before", "underlying_price_after", "underlying_price_source", "underlying_price_status", "underlying_price_injected", "underlying_snapshot_path", "underlying_snapshot_age_minutes", "underlying_snapshot_stale_flag", "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed"]
AUDIT_FIELDS = ["underlying", "underlying_price_source", "row_count", "before_valid_count", "after_valid_count", "injected_count", "missing_after_count", "unique_underlying_price_after_count", "min_underlying_price", "median_underlying_price", "max_underlying_price"]


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def norm_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    return text[3:] if text.startswith("US.") else text


def first_present(row: dict[str, str], aliases: list[str]) -> tuple[str, str]:
    lower = {str(k).lower(): k for k in row}
    for alias in aliases:
        key = lower.get(alias.lower())
        if key is not None:
            return str(key), row.get(key, "")
    return "", ""


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def discover_input(repo_root: Path) -> Path | None:
    default = repo_root / DEFAULT_INPUT_REL
    if default.exists():
        return default
    root = repo_root / "outputs" / "v22"
    candidates = [p for p in root.rglob("*.csv") if "v22.032" in p.parent.name.lower() and "quote" in p.name.lower() and "clean" in p.name.lower()] if root.exists() else []
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def discover_snapshots(repo_root: Path) -> list[Path]:
    root = repo_root / "outputs" / "v22"
    if not root.exists():
        return []
    patterns = ["v22.036_r3", "v22.036", "v22.032_r1", "quote", "snapshot", "underlying"]
    files = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".csv", ".json"}:
            continue
        if STAGE.lower() in str(path).lower():
            continue
        text = f"{path.parent.name.lower()} {path.name.lower()}"
        if any(p in text for p in patterns) and any(k in text for k in ["snapshot", "quote", "underlying", "spot"]):
            files.append(path)
    def score(path: Path) -> tuple[int, float]:
        text = f"{path.parent.name.lower()} {path.name.lower()}"
        value = 0
        if "underlying_quote_snapshot_clean" in text:
            value += 1000
        if "underlying" in text and "snapshot" in text:
            value += 500
        if "v22.036_r3" in text or "v22.036_r3a" in text:
            value += 250
        if "option_" in path.name.lower() and "underlying" not in path.name.lower():
            value -= 250
        return value, path.stat().st_mtime
    return sorted(files, key=score, reverse=True)


def load_snapshot_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return read_csv_rows(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [payload]
    return []


def snapshot_mapping(paths: list[Path]) -> tuple[dict[str, dict[str, Any]], str, int]:
    mapping: dict[str, dict[str, Any]] = {}
    selected = ""
    scanned = 0
    for path in paths:
        rows = load_snapshot_rows(path)
        if not rows:
            continue
        scanned += 1
        local: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_text = {str(k): str(v) for k, v in row.items()}
            lower_keys = {k.lower() for k in row_text}
            option_like = bool(lower_keys & OPTION_ROW_MARKERS)
            price_aliases = PRICE_ALIASES if option_like else SNAPSHOT_PRICE_ALIASES + PRICE_ALIASES
            _, sym_raw = first_present(row_text, UNDERLYING_ALIASES)
            price_col, price_raw = first_present(row_text, price_aliases)
            time_col, time_raw = first_present(row_text, TIME_ALIASES)
            sym = norm_symbol(sym_raw)
            price = numeric(price_raw)
            if sym and price is not None:
                local[sym] = {"price": price, "path": str(path), "price_column": price_col, "timestamp": time_raw, "timestamp_column": time_col}
        if local and not mapping:
            mapping = local
            selected = str(path)
    return mapping, selected, scanned


def age_minutes(option_time: str, snapshot_time: str) -> tuple[float | str, bool | str]:
    a = parse_time(option_time)
    b = parse_time(snapshot_time)
    if a is None or b is None:
        return "", ""
    if a.tzinfo is not None and b.tzinfo is None:
        b = b.replace(tzinfo=a.tzinfo)
    elif a.tzinfo is None and b.tzinfo is not None:
        a = a.replace(tzinfo=b.tzinfo)
    minutes = abs((a - b).total_seconds()) / 60
    return round(minutes, 4), minutes > 30


def repair_rows(rows: list[dict[str, str]], snapshot_map: dict[str, dict[str, Any]], selected_snapshot: str) -> list[dict[str, Any]]:
    underlyings = {norm_symbol(first_present(row, UNDERLYING_ALIASES)[1]) for row in rows}
    underlyings.discard("")
    valid_snapshot_prices = {sym: data for sym, data in snapshot_map.items() if numeric(data.get("price")) is not None}
    single_broadcast = None
    if len(underlyings) == 1 and len(valid_snapshot_prices) == 1:
        single_broadcast = next(iter(valid_snapshot_prices.values()))
    out = []
    for row in rows:
        original = dict(row)
        underlying = norm_symbol(first_present(row, UNDERLYING_ALIASES)[1])
        before_col, before_raw = first_present(row, ["underlying_price"])
        before = numeric(before_raw)
        source = ""
        status = "MISSING_OR_AMBIGUOUS"
        injected = False
        after = before
        snap = None
        if before is not None:
            source = f"OPTION_ROW_COLUMN:{before_col}"
            status = "PRESERVED_EXISTING"
        else:
            for col in PRICE_ALIASES:
                if col == "underlying_price":
                    continue
                actual_col, raw = first_present(row, [col])
                val = numeric(raw)
                if val is not None:
                    after = val
                    source = f"OPTION_ROW_COLUMN:{actual_col}"
                    status = "INJECTED"
                    injected = True
                    break
            if after is None:
                snap = valid_snapshot_prices.get(underlying)
                if snap is not None:
                    after = snap["price"]
                    source = f"SNAPSHOT_JOIN:{snap['price_column']}"
                    status = "INJECTED"
                    injected = True
                elif single_broadcast is not None:
                    after = single_broadcast["price"]
                    source = "SINGLE_UNDERLYING_BROADCAST_FROM_SNAPSHOT"
                    status = "INJECTED"
                    injected = True
                    snap = single_broadcast
        snap = snap or valid_snapshot_prices.get(underlying) or single_broadcast
        opt_time = first_present(row, TIME_ALIASES)[1]
        age, stale = age_minutes(opt_time, str((snap or {}).get("timestamp", "")))
        original.update({"underlying_price": "" if after is None else after, "underlying_price_before": "" if before is None else before, "underlying_price_after": "" if after is None else after, "underlying_price_source": source or "UNAVAILABLE", "underlying_price_status": status, "underlying_price_injected": injected, "underlying_snapshot_path": (snap or {}).get("path", selected_snapshot if injected else ""), "underlying_snapshot_age_minutes": age, "underlying_snapshot_stale_flag": stale, "candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False})
        out.append(original)
    return out


def audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        sym = norm_symbol(first_present({k: str(v) for k, v in row.items()}, UNDERLYING_ALIASES)[1])
        groups.setdefault((sym, str(row.get("underlying_price_source", ""))), []).append(row)
    out = []
    for (sym, source), vals in sorted(groups.items()):
        prices = [numeric(v.get("underlying_price_after")) for v in vals if numeric(v.get("underlying_price_after")) is not None]
        out.append({"underlying": sym, "underlying_price_source": source, "row_count": len(vals), "before_valid_count": sum(1 for v in vals if numeric(v.get("underlying_price_before")) is not None), "after_valid_count": len(prices), "injected_count": sum(1 for v in vals if v.get("underlying_price_injected") is True), "missing_after_count": sum(1 for v in vals if numeric(v.get("underlying_price_after")) is None), "unique_underlying_price_after_count": len(set(prices)), "min_underlying_price": "" if not prices else min(prices), "median_underlying_price": "" if not prices else median(prices), "max_underlying_price": "" if not prices else max(prices)})
    return out


def build_summary(input_path: Path | None, output_dir: Path, rows: list[dict[str, Any]], snapshot_count: int, selected_snapshot: str, input_found: bool) -> dict[str, Any]:
    if not input_found:
        status, decision = FAIL_INPUT, INPUT_DECISION
    else:
        before = sum(1 for r in rows if numeric(r.get("underlying_price_before")) is not None)
        after = sum(1 for r in rows if numeric(r.get("underlying_price_after")) is not None)
        injected = sum(1 for r in rows if r.get("underlying_price_injected") is True)
        missing = len(rows) - after
        if injected > 0 and missing == 0:
            status, decision = PASS_STATUS, PASS_DECISION
        elif injected > 0:
            status, decision = WARN_STATUS, WARN_DECISION
        else:
            status, decision = FAIL_NO_SOURCE, NO_SOURCE_DECISION
    before = sum(1 for r in rows if numeric(r.get("underlying_price_before")) is not None)
    after = sum(1 for r in rows if numeric(r.get("underlying_price_after")) is not None)
    injected = sum(1 for r in rows if r.get("underlying_price_injected") is True)
    missing = len(rows) - after
    underlyings = {norm_symbol(first_present({k: str(v) for k, v in r.items()}, UNDERLYING_ALIASES)[1]) for r in rows}
    underlyings.discard("")
    return {"module_name": MODULE_NAME, "final_status": status, "final_decision": decision, "input_path": "" if input_path is None else str(input_path), "output_dir": str(output_dir), "input_row_count": len(rows), "underlying_symbol_count": len(underlyings), "underlying_price_before_valid_count": before, "underlying_price_after_valid_count": after, "injected_underlying_price_count": injected, "missing_underlying_price_after_count": missing, "discovered_snapshot_file_count": snapshot_count, "selected_snapshot_path": selected_snapshot, "candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "ready_for_v22_037_r1_rerun": after > before and after > 0}


def report_text(summary: dict[str, Any]) -> str:
    cmd = f".\\scripts\\v22\\run_v22_037_r1_option_synthetic_iv_solver_research_only.ps1 -Execute -InputPath {Path(summary['output_dir']) / 'option_quote_enrichment_clean_with_underlying_price.csv'}"
    lines = ["V22.037_R1A Underlying Price Injection Repair Research Only"]
    for key in ["final_status", "final_decision", "input_path", "selected_snapshot_path", "underlying_price_before_valid_count", "underlying_price_after_valid_count", "injected_underlying_price_count", "missing_underlying_price_after_count"]:
        lines.append(f"{key}={summary.get(key)}")
    lines.append(f"next_recommended_command={cmd}")
    lines.append("broker_action_allowed=False")
    lines.append("official_adoption_allowed=False")
    return "\n".join(lines) + "\n"


def run(repo_root: Path, input_path: Path | None = None, underlying_snapshot_path: Path | None = None, output_root: Path | None = None, execute: bool = True) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = (output_root or (repo_root / OUT_REL)).resolve()
    input_path = input_path or discover_input(repo_root)
    if not execute:
        return build_summary(input_path, output_dir, [], 0, "", input_path is not None and input_path.exists())
    if input_path is None or not input_path.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = build_summary(input_path, output_dir, [], 0, "", False)
        write_csv(output_dir / "option_quote_enrichment_clean_with_underlying_price.csv", OUTPUT_EXTRA, [])
        write_csv(output_dir / "underlying_price_injection_audit.csv", AUDIT_FIELDS, [])
        write_json(output_dir / "v22_037_r1a_summary.json", summary)
        (output_dir / "V22.037_R1A_underlying_price_injection_repair_report.txt").write_text(report_text(summary), encoding="utf-8")
        return summary
    rows = read_csv_rows(input_path)
    snapshot_paths = [underlying_snapshot_path] if underlying_snapshot_path else discover_snapshots(repo_root)
    snapshot_paths = [p for p in snapshot_paths if p and p.exists()]
    snap_map, selected, scanned = snapshot_mapping(snapshot_paths)
    repaired = repair_rows(rows, snap_map, selected)
    fields = list(dict.fromkeys([*(rows[0].keys() if rows else []), *OUTPUT_EXTRA]))
    audit = audit_rows(repaired)
    summary = build_summary(input_path, output_dir, repaired, scanned, selected, True)
    write_csv(output_dir / "option_quote_enrichment_clean_with_underlying_price.csv", fields, repaired)
    write_csv(output_dir / "underlying_price_injection_audit.csv", AUDIT_FIELDS, audit)
    write_json(output_dir / "v22_037_r1a_summary.json", summary)
    (output_dir / "V22.037_R1A_underlying_price_injection_repair_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--input-path", type=Path, default=None)
    parser.add_argument("--underlying-snapshot-path", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.input_path, args.underlying_snapshot_path, args.output_root, args.execute)
    for key in ["final_status", "final_decision", "underlying_price_before_valid_count", "underlying_price_after_valid_count", "injected_underlying_price_count", "missing_underlying_price_after_count", "selected_snapshot_path", "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed"]:
        print(f"{key}={summary.get(key)}")
    print(f"output_dir={summary.get('output_dir')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
