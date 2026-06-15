from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


STATUS_REFRESH = "OK_V18_14B_CURRENT_DAILY_COMMAND_CENTER_REFRESH_READY"
STATUS_FULL = "OK_V18_14B_CURRENT_DAILY_COMMAND_CENTER_FULL_DAILY_READY"
STATUS_VALIDATE = "OK_V18_14B_CURRENT_DAILY_COMMAND_CENTER_VALIDATE_ONLY_READY"
STATUS_FAIL = "FAIL_V18_14B_CURRENT_DAILY_COMMAND_CENTER"

OFFICIAL_DECISION_IMPACT = "NONE"
AUTO_TRADE = "DISABLED"
AUTO_SELL = "DISABLED"
READ_ONLY = "TRUE"
CURRENT_ENTRY_ONLY = "TRUE"

DANGEROUS_TOKENS = (
    "SELL_NOW",
    "BUY_NOW_FORCE",
    "AUTO_EXECUTE",
    "LIVE_ORDER",
    "LIVE_SELL",
    "BROKER_ORDER",
)

SUMMARY_FIELDS = ("metric", "value")
AUDIT_FIELDS = ("component", "source_file", "alias_file", "exists", "copied", "row_count", "parse_status", "status_value", "note")
LEGACY_TOP20_SIDECAR = "V18_14B_LEGACY_TOP_RANKED_CANDIDATES.csv"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return ""


def read_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                return list(reader), list(reader.fieldnames or []), "OK"
        except Exception:
            continue
    return [], [], "CSV_PARSE_FAILED"


def write_csv(path: Path, rows: Sequence[Dict[str, object]], fields: Sequence[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def first_value(path: Path, key: str) -> str:
    target = f"{key}:"
    bullet_target = f"- {target}"
    lines = [line.strip() for line in read_text(path).splitlines()]
    for i, line in enumerate(lines):
        if line == target:
            for nxt in lines[i + 1 :]:
                if nxt:
                    return nxt.strip("` ")
        if line.startswith(target):
            value = line[len(target) :].strip()
            if value:
                return value.strip("` ")
        if line.startswith(bullet_target):
            value = line[len(bullet_target) :].strip()
            if value:
                return value.strip("` ")
    return ""


def metric_value(path: Path, key: str) -> str:
    rows, _, _ = read_csv(path)
    for row in rows:
        if row.get("metric") == key:
            return row.get("value", "")
    return ""


def copy_alias(src: Path, dst: Path) -> Tuple[bool, str]:
    if not src.exists() or not src.is_file():
        return False, "MISSING_SOURCE"
    try:
        ensure_dir(dst.parent)
        shutil.copy2(src, dst)
        return True, "COPIED"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def scan_tokens(root: Path, paths: Iterable[Path]) -> List[str]:
    hits: List[str] = []
    for path in paths:
        text = read_text(path)
        for token in DANGEROUS_TOKENS:
            if token in text:
                hits.append(f"{rel(root, path)}::{token}")
    return hits


def top_5_from_rows(rows: Sequence[Dict[str, str]]) -> str:
    tickers: List[str] = []
    for row in rows:
        ticker = (row.get("ticker") or row.get("symbol") or "").strip()
        if ticker:
            tickers.append(ticker)
        if len(tickers) >= 5:
            break
    return ",".join(tickers)


def markdown_table(rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(row.get(field, "")).replace("|", "/") for field in fields) + " |")
    return out


def build(root: Path, mode: str) -> Tuple[Dict[str, str], int]:
    read_dir = root / "outputs/v18/read_center"
    candidates_dir = root / "outputs/v18/candidates"
    ops_dir = root / "outputs/v18/ops"

    d_read_first = read_dir / "V18_13D_READ_FIRST.txt"
    d_main = read_dir / "V18_13D_CURRENT_DAILY_COMMAND_CENTER.md"
    c_main = read_dir / "V18_13C_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES.md"
    b_csv = candidates_dir / "V18_13B_CURRENT_RANKED_CANDIDATES.csv"
    a14_read_first = ops_dir / "V18_14A_READ_FIRST.txt"

    d_summary = read_dir / "V18_13D_CURRENT_DAILY_COMMAND_CENTER_SUMMARY.csv"
    c_summary = read_dir / "V18_13C_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES_SUMMARY.csv"
    b_summary = read_dir / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"

    aliases = [
        ("V18_CURRENT_READ_FIRST", d_read_first, read_dir / "V18_CURRENT_READ_FIRST.txt"),
        ("V18_CURRENT_DAILY_COMMAND_CENTER", d_main, read_dir / "V18_CURRENT_DAILY_COMMAND_CENTER.md"),
        ("V18_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES", c_main, read_dir / "V18_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES.md"),
        # V18.50B-R2 owns V18_CURRENT_TOP_RANKED_CANDIDATES.csv exclusively.
        # Keep this legacy V18.14B snapshot as a sidecar so standalone runs cannot contaminate current Top20.
        ("V18_14B_LEGACY_TOP_RANKED_CANDIDATES", b_csv, candidates_dir / LEGACY_TOP20_SIDECAR),
        ("V18_CURRENT_FULL_DAILY_MODE_VALIDATION_READ_FIRST", a14_read_first, ops_dir / "V18_CURRENT_FULL_DAILY_MODE_VALIDATION_READ_FIRST.txt"),
    ]

    audit_rows: List[Dict[str, str]] = []
    copy_failures: List[str] = []
    for component, src, dst in aliases:
        copied, note = copy_alias(src, dst)
        if not copied:
            copy_failures.append(component)
        row_count = 0
        parse_status = "OK_TEXT" if dst.exists() and dst.suffix.lower() != ".csv" else ""
        if dst.suffix.lower() == ".csv":
            rows, _, parse_status = read_csv(dst)
            row_count = len(rows)
        audit_rows.append({
            "component": component,
            "source_file": str(src),
            "alias_file": str(dst),
            "exists": "YES" if src.exists() else "NO",
            "copied": "YES" if copied else "NO",
            "row_count": str(row_count),
            "parse_status": parse_status or ("OK_TEXT" if dst.exists() else "MISSING"),
            "status_value": note,
            "note": "LEGACY_TOP20_SIDECAR_NOT_CURRENT_ALIAS" if component == "V18_14B_LEGACY_TOP_RANKED_CANDIDATES" else "CURRENT_ALIAS",
        })

    candidate_rows, candidate_fields, candidate_parse = read_csv(candidates_dir / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv")
    run_mode = first_value(d_read_first, "RUN_MODE") or metric_value(d_summary, "RUN_MODE") or "UNKNOWN"
    official_status = first_value(d_read_first, "OFFICIAL_DAILY_STATUS") or metric_value(d_summary, "OFFICIAL_DAILY_STATUS") or "UNKNOWN"
    v13a_status = first_value(d_read_first, "V18_13A_STATUS") or metric_value(d_summary, "V18_13A_STATUS") or "UNKNOWN"
    v13b_status = first_value(d_read_first, "V18_13B_STATUS") or metric_value(d_summary, "V18_13B_STATUS") or metric_value(b_summary, "STATUS") or "UNKNOWN"
    v13c_status = first_value(d_read_first, "V18_13C_STATUS") or metric_value(d_summary, "V18_13C_STATUS") or metric_value(c_summary, "STATUS") or "UNKNOWN"
    v14a_status = first_value(a14_read_first, "STATUS") or "UNKNOWN"
    v14a_full_status = first_value(a14_read_first, "FULL_DAILY_MODE_STATUS") or "UNKNOWN"
    rank_source = first_value(d_read_first, "RANK_SOURCE_STATUS") or metric_value(c_summary, "RANK_SOURCE_STATUS") or metric_value(b_summary, "RANK_SOURCE_STATUS") or "UNKNOWN"
    second_stage = first_value(d_read_first, "SECOND_STAGE_COUNT") or metric_value(c_summary, "SECOND_STAGE_COUNT") or metric_value(b_summary, "SECOND_STAGE_COUNT") or str(len(candidate_rows))
    scored = first_value(d_read_first, "SCORED_TICKER_COUNT") or metric_value(c_summary, "SCORED_TICKER_COUNT") or "0"
    unscored = first_value(d_read_first, "UNSCORED_TICKER_COUNT") or metric_value(c_summary, "UNSCORED_TICKER_COUNT") or "0"
    top_5 = first_value(d_read_first, "TOP_5_TICKERS") or metric_value(c_summary, "TOP_5_TICKERS") or top_5_from_rows(candidate_rows)

    if run_mode == "READ_CENTER_REFRESH_ONLY":
        full_daily_mode_status = "NOT_FULL_DAILY_REFRESH_ONLY"
    elif v14a_status == "OK_V18_14A_FULL_DAILY_MODE_VALIDATION_READY":
        full_daily_mode_status = "FULL_DAILY_MODE_CONFIRMED"
    else:
        full_daily_mode_status = v14a_full_status if v14a_full_status != "UNKNOWN" else "FULL_DAILY_NOT_VALIDATED"

    report_path = ops_dir / "V18_14B_CURRENT_DAILY_COMMAND_CENTER_REPORT.md"
    summary_path = ops_dir / "V18_14B_CURRENT_DAILY_COMMAND_CENTER_SUMMARY.csv"
    audit_path = ops_dir / "V18_14B_CURRENT_DAILY_COMMAND_CENTER_INPUT_AUDIT.csv"
    read_first_path = ops_dir / "V18_14B_READ_FIRST.txt"

    scan_paths = [
        read_dir / "V18_CURRENT_READ_FIRST.txt",
        read_dir / "V18_CURRENT_DAILY_COMMAND_CENTER.md",
        read_dir / "V18_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES.md",
        candidates_dir / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv",
        ops_dir / "V18_CURRENT_FULL_DAILY_MODE_VALIDATION_READ_FIRST.txt",
        report_path,
    ]
    pre_report_hits = scan_tokens(root, scan_paths[:-1])

    failures: List[str] = []
    for component, src, _ in aliases:
        if not src.exists():
            failures.append(f"{component}_SOURCE_MISSING")
    if copy_failures:
        failures.append("CURRENT_ALIAS_COPY_FAILED")
    if AUTO_TRADE != "DISABLED":
        failures.append("AUTO_TRADE_NOT_DISABLED")
    if AUTO_SELL != "DISABLED":
        failures.append("AUTO_SELL_NOT_DISABLED")
    if OFFICIAL_DECISION_IMPACT != "NONE":
        failures.append("OFFICIAL_DECISION_IMPACT_NOT_NONE")
    if candidate_parse != "OK" or not candidate_rows:
        failures.append("RANKED_CANDIDATES_MISSING_OR_UNREADABLE")
    if pre_report_hits:
        failures.append("DANGEROUS_TOKEN_DETECTED")

    if failures:
        status = STATUS_FAIL
    elif mode == "VALIDATE_ONLY":
        status = STATUS_VALIDATE
    elif run_mode == "READ_CENTER_REFRESH_ONLY" or mode == "READ_CENTER_REFRESH_ONLY":
        status = STATUS_REFRESH
    else:
        status = STATUS_FULL

    values = {
        "STATUS": status,
        "RUN_MODE": run_mode,
        "OFFICIAL_DAILY_STATUS": official_status,
        "V18_13A_STATUS": v13a_status,
        "V18_13B_STATUS": v13b_status,
        "V18_13C_STATUS": v13c_status,
        "V18_14A_STATUS": v14a_status,
        "FULL_DAILY_MODE_STATUS": full_daily_mode_status,
        "RANK_SOURCE_STATUS": rank_source,
        "SECOND_STAGE_COUNT": second_stage,
        "SCORED_TICKER_COUNT": scored,
        "UNSCORED_TICKER_COUNT": unscored,
        "TOP_5_TICKERS": top_5,
        "TODAY_MAIN_READ": rel(root, read_dir / "V18_CURRENT_DAILY_COMMAND_CENTER.md"),
        "TODAY_RANKED_CANDIDATES_CSV": rel(root, candidates_dir / "V18_CURRENT_TOP_RANKED_CANDIDATES.csv"),
        "V18_14B_DIRECT_CURRENT_TOP20_WRITE_DISABLED": "TRUE",
        "V18_14B_LEGACY_TOP20_SIDECAR": rel(root, candidates_dir / LEGACY_TOP20_SIDECAR),
        "OFFICIAL_DECISION_IMPACT": OFFICIAL_DECISION_IMPACT,
        "AUTO_TRADE": AUTO_TRADE,
        "AUTO_SELL": AUTO_SELL,
        "READ_ONLY": READ_ONLY,
        "CURRENT_ENTRY_ONLY": CURRENT_ENTRY_ONLY,
        "VALIDATION_FAIL_COUNT": str(len(failures)),
        "FAIL_REASONS": ";".join(failures) if failures else "NONE",
        "DANGEROUS_TOKEN_DETECTED": "YES" if pre_report_hits else "NO",
        "DANGEROUS_TOKEN_HITS": ";".join(pre_report_hits) if pre_report_hits else "NONE",
        "READ_FIRST": rel(root, read_first_path),
    }

    read_first_keys = (
        "STATUS",
        "RUN_MODE",
        "OFFICIAL_DAILY_STATUS",
        "V18_13A_STATUS",
        "V18_13B_STATUS",
        "V18_13C_STATUS",
        "V18_14A_STATUS",
        "FULL_DAILY_MODE_STATUS",
        "RANK_SOURCE_STATUS",
        "SECOND_STAGE_COUNT",
        "SCORED_TICKER_COUNT",
        "UNSCORED_TICKER_COUNT",
        "TOP_5_TICKERS",
        "TODAY_MAIN_READ",
        "TODAY_RANKED_CANDIDATES_CSV",
        "V18_14B_DIRECT_CURRENT_TOP20_WRITE_DISABLED",
        "V18_14B_LEGACY_TOP20_SIDECAR",
        "OFFICIAL_DECISION_IMPACT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "READ_ONLY",
        "CURRENT_ENTRY_ONLY",
        "VALIDATION_FAIL_COUNT",
        "FAIL_REASONS",
    )
    write_text(read_first_path, "\n".join(f"{key}: {values[key]}" for key in read_first_keys) + "\n")
    write_csv(summary_path, [{"metric": key, "value": value} for key, value in values.items()], SUMMARY_FIELDS)
    write_csv(audit_path, audit_rows, AUDIT_FIELDS)

    report = [
        "# V18.14B Current Daily Command Center",
        "",
        "Current one-command entry summary. V18.14B does not enable trading or selling.",
        "",
        "## Status",
        "",
    ]
    report.extend(f"- {key}: {values[key]}" for key in read_first_keys)
    report.extend([
        f"- DANGEROUS_TOKEN_DETECTED: {values['DANGEROUS_TOKEN_DETECTED']}",
        "",
        "## Alias Outputs",
        "",
    ])
    report.extend(markdown_table(audit_rows, AUDIT_FIELDS))
    if candidate_rows:
        fields = [field for field in ("rank", "ticker", "composite_candidate_score", "final_action", "technical_status") if field in candidate_fields]
        report.extend(["", "## Top Ranked Candidates", ""])
        report.extend(markdown_table(candidate_rows[:5], fields or candidate_fields[:5]))
    write_text(report_path, "\n".join(report) + "\n")

    post_report_hits = scan_tokens(root, scan_paths)
    if post_report_hits and not pre_report_hits:
        values["STATUS"] = STATUS_FAIL
        values["DANGEROUS_TOKEN_DETECTED"] = "YES"
        values["DANGEROUS_TOKEN_HITS"] = ";".join(post_report_hits)
        values["VALIDATION_FAIL_COUNT"] = "1"
        values["FAIL_REASONS"] = "DANGEROUS_TOKEN_DETECTED"
        write_text(read_first_path, "\n".join(f"{key}: {values[key]}" for key in read_first_keys) + "\n")
        write_csv(summary_path, [{"metric": key, "value": value} for key, value in values.items()], SUMMARY_FIELDS)

    for key in read_first_keys:
        print(f"{key}: {values[key]}")
    print(f"DANGEROUS_TOKEN_DETECTED: {values['DANGEROUS_TOKEN_DETECTED']}")
    return values, 0 if values["STATUS"] != STATUS_FAIL else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="V18.14B current daily command center alias and summary layer.")
    parser.add_argument("--root", default=r"D:\us-tech-quant")
    parser.add_argument("--mode", choices=["READ_CENTER_REFRESH_ONLY", "FULL_DAILY", "VALIDATE_ONLY"], default="READ_CENTER_REFRESH_ONLY")
    args = parser.parse_args()
    _, code = build(Path(args.root), args.mode)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
