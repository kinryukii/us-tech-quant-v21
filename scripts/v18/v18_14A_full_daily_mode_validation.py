from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


ROOT_DEFAULT = Path(r"D:\us-tech-quant")

OK_STATUS = "OK_V18_14A_FULL_DAILY_MODE_VALIDATION_READY"
FAIL_STATUS = "FAIL_V18_14A_FULL_DAILY_MODE_VALIDATION"

OFFICIAL_DECISION_IMPACT = "NONE"
AUTO_TRADE = "DISABLED"
AUTO_SELL = "DISABLED"
READ_ONLY = "TRUE"
FULL_DAILY_VALIDATION_ONLY = "TRUE"

DANGEROUS_TOKENS = (
    "SELL_NOW",
    "BUY_NOW_FORCE",
    "AUTO_EXECUTE",
    "LIVE_ORDER",
    "LIVE_SELL",
    "BROKER_ORDER",
)

SUMMARY_FIELDS = ("metric", "value")
AUDIT_FIELDS = (
    "component",
    "source_file",
    "exists",
    "row_count",
    "parse_status",
    "status_value",
    "note",
)


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


def rel_path(root: Path, path: Path) -> str:
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


def metric_value(path: Path, metric: str) -> str:
    rows, _, _ = read_csv(path)
    for row in rows:
        if row.get("metric") == metric:
            return row.get("value", "")
    return ""


def scan_tokens(root: Path, paths: Iterable[Path]) -> List[str]:
    hits: List[str] = []
    for path in paths:
        text = read_text(path)
        for token in DANGEROUS_TOKENS:
            if token in text:
                hits.append(f"{rel_path(root, path)}::{token}")
    return hits


def top_5_from_candidates(rows: Sequence[Dict[str, str]]) -> str:
    tickers: List[str] = []
    for row in rows:
        ticker = (row.get("ticker") or row.get("symbol") or "").strip()
        if ticker:
            tickers.append(ticker)
        if len(tickers) >= 5:
            break
    return ",".join(tickers)


def count_scored(rows: Sequence[Dict[str, str]]) -> Tuple[int, int]:
    scored = 0
    unscored = 0
    for row in rows:
        score = ""
        for key in ("composite_candidate_score", "score", "candidate_score"):
            if key in row:
                score = str(row.get(key, "")).strip()
                break
        if score:
            scored += 1
        else:
            unscored += 1
    return scored, unscored


def audit_row(component: str, path: Path, row_count: int, parse_status: str, status_value: str, note: str) -> Dict[str, str]:
    return {
        "component": component,
        "source_file": str(path),
        "exists": "YES" if path.exists() else "NO",
        "row_count": str(row_count),
        "parse_status": parse_status,
        "status_value": status_value,
        "note": note,
    }


def markdown_table(rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join(["---"] * len(fields)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(row.get(field, "")).replace("|", "/") for field in fields) + " |")
    return out


def build(root: Path) -> Tuple[Dict[str, str], int]:
    read_dir = root / "outputs/v18/read_center"
    candidates_dir = root / "outputs/v18/candidates"
    ops_dir = root / "outputs/v18/ops"

    d_read_first = read_dir / "V18_13D_READ_FIRST.txt"
    d_main = read_dir / "V18_13D_CURRENT_DAILY_COMMAND_CENTER.md"
    c_main = read_dir / "V18_13C_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES.md"
    b_csv = candidates_dir / "V18_13B_CURRENT_RANKED_CANDIDATES.csv"

    d_summary = read_dir / "V18_13D_CURRENT_DAILY_COMMAND_CENTER_SUMMARY.csv"
    c_summary = read_dir / "V18_13C_CURRENT_UNIFIED_DAILY_WITH_RANKED_CANDIDATES_SUMMARY.csv"
    b_summary = read_dir / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"

    out_read_first = ops_dir / "V18_14A_READ_FIRST.txt"
    out_report = ops_dir / "V18_14A_CURRENT_FULL_DAILY_MODE_VALIDATION_REPORT.md"
    out_summary = ops_dir / "V18_14A_CURRENT_FULL_DAILY_MODE_VALIDATION.csv"
    out_audit = ops_dir / "V18_14A_CURRENT_FULL_DAILY_MODE_VALIDATION_INPUT_AUDIT.csv"

    candidate_rows, candidate_fields, candidate_parse = read_csv(b_csv)
    scored_count, unscored_count = count_scored(candidate_rows)

    run_mode = first_value(d_read_first, "RUN_MODE") or metric_value(d_summary, "RUN_MODE") or "UNKNOWN"
    full_daily_mode_status = "FULL_DAILY_MODE_CONFIRMED" if run_mode != "READ_CENTER_REFRESH_ONLY" else "READ_CENTER_REFRESH_ONLY"
    official_status = first_value(d_read_first, "OFFICIAL_DAILY_STATUS") or metric_value(d_summary, "OFFICIAL_DAILY_STATUS") or "UNKNOWN"
    v18_13a_status = first_value(d_read_first, "V18_13A_STATUS") or metric_value(d_summary, "V18_13A_STATUS") or "UNKNOWN"
    v18_13b_status = first_value(d_read_first, "V18_13B_STATUS") or metric_value(d_summary, "V18_13B_STATUS") or metric_value(b_summary, "STATUS") or "UNKNOWN"
    v18_13c_status = first_value(d_read_first, "V18_13C_STATUS") or metric_value(d_summary, "V18_13C_STATUS") or metric_value(c_summary, "STATUS") or "UNKNOWN"
    rank_source = first_value(d_read_first, "RANK_SOURCE_STATUS") or metric_value(c_summary, "RANK_SOURCE_STATUS") or metric_value(b_summary, "RANK_SOURCE_STATUS") or "UNKNOWN"
    second_stage = first_value(d_read_first, "SECOND_STAGE_COUNT") or metric_value(c_summary, "SECOND_STAGE_COUNT") or metric_value(b_summary, "SECOND_STAGE_COUNT") or str(len(candidate_rows))
    scored = first_value(d_read_first, "SCORED_TICKER_COUNT") or metric_value(c_summary, "SCORED_TICKER_COUNT") or str(scored_count)
    unscored = first_value(d_read_first, "UNSCORED_TICKER_COUNT") or metric_value(c_summary, "UNSCORED_TICKER_COUNT") or str(unscored_count)
    top_5 = first_value(d_read_first, "TOP_5_TICKERS") or metric_value(c_summary, "TOP_5_TICKERS") or top_5_from_candidates(candidate_rows)

    token_hits = scan_tokens(root, [d_read_first, d_main, c_main, b_csv])

    fail_reasons: List[str] = []
    if not d_read_first.exists():
        fail_reasons.append("V18_13D_READ_FIRST_MISSING")
    if not d_main.exists():
        fail_reasons.append("V18_13D_MAIN_READ_MISSING")
    if run_mode == "READ_CENTER_REFRESH_ONLY":
        fail_reasons.append("READ_CENTER_REFRESH_ONLY")
    if official_status == "SKIPPED":
        fail_reasons.append("OFFICIAL_DAILY_STATUS_SKIPPED")
    if not b_csv.exists():
        fail_reasons.append("RANKED_CANDIDATES_CSV_MISSING")
    if candidate_parse != "OK" or not candidate_rows:
        fail_reasons.append("RANKED_CANDIDATES_CSV_EMPTY_OR_UNREADABLE")
    if OFFICIAL_DECISION_IMPACT != "NONE":
        fail_reasons.append("OFFICIAL_DECISION_IMPACT_NOT_NONE")
    if AUTO_TRADE != "DISABLED":
        fail_reasons.append("AUTO_TRADE_NOT_DISABLED")
    if AUTO_SELL != "DISABLED":
        fail_reasons.append("AUTO_SELL_NOT_DISABLED")
    if token_hits:
        fail_reasons.append("DANGEROUS_TOKEN_DETECTED")

    status = OK_STATUS if not fail_reasons else FAIL_STATUS
    values = {
        "STATUS": status,
        "FULL_DAILY_MODE_STATUS": full_daily_mode_status,
        "OFFICIAL_DAILY_STATUS": official_status,
        "V18_13A_STATUS": v18_13a_status,
        "V18_13B_STATUS": v18_13b_status,
        "V18_13C_STATUS": v18_13c_status,
        "RANK_SOURCE_STATUS": rank_source,
        "SECOND_STAGE_COUNT": second_stage,
        "SCORED_TICKER_COUNT": scored,
        "UNSCORED_TICKER_COUNT": unscored,
        "TOP_5_TICKERS": top_5,
        "TODAY_MAIN_READ": rel_path(root, d_main) if d_main.exists() else "MISSING",
        "TODAY_RANKED_CANDIDATES_CSV": rel_path(root, b_csv) if b_csv.exists() else "MISSING",
        "OFFICIAL_DECISION_IMPACT": OFFICIAL_DECISION_IMPACT,
        "AUTO_TRADE": AUTO_TRADE,
        "AUTO_SELL": AUTO_SELL,
        "READ_ONLY": READ_ONLY,
        "FULL_DAILY_VALIDATION_ONLY": FULL_DAILY_VALIDATION_ONLY,
        "VALIDATION_FAIL_COUNT": str(len(fail_reasons)),
        "FAIL_REASONS": ";".join(fail_reasons) if fail_reasons else "NONE",
        "DANGEROUS_TOKEN_DETECTED": "YES" if token_hits else "NO",
        "DANGEROUS_TOKEN_HITS": ";".join(token_hits) if token_hits else "NONE",
    }

    audit_rows = [
        audit_row("V18_13D_READ_FIRST", d_read_first, 0, "OK_TEXT" if d_read_first.exists() else "MISSING", run_mode, "REQUIRED"),
        audit_row("V18_13D_MAIN_READ", d_main, 0, "OK_TEXT" if d_main.exists() else "MISSING", v18_13a_status, "REQUIRED"),
        audit_row("V18_13C_MAIN_READ", c_main, 0, "OK_TEXT" if c_main.exists() else "MISSING", v18_13c_status, "RANKED_LINK"),
        audit_row("V18_13B_CANDIDATES", b_csv, len(candidate_rows), candidate_parse, rank_source, "REQUIRED"),
        audit_row("DANGEROUS_TOKEN_SCAN", ops_dir, len(token_hits), "OK" if not token_hits else "FAIL", values["DANGEROUS_TOKEN_DETECTED"], values["DANGEROUS_TOKEN_HITS"]),
    ]

    read_first_keys = (
        "STATUS",
        "FULL_DAILY_MODE_STATUS",
        "OFFICIAL_DAILY_STATUS",
        "V18_13A_STATUS",
        "V18_13B_STATUS",
        "V18_13C_STATUS",
        "RANK_SOURCE_STATUS",
        "SECOND_STAGE_COUNT",
        "SCORED_TICKER_COUNT",
        "UNSCORED_TICKER_COUNT",
        "TOP_5_TICKERS",
        "TODAY_MAIN_READ",
        "TODAY_RANKED_CANDIDATES_CSV",
        "OFFICIAL_DECISION_IMPACT",
        "AUTO_TRADE",
        "AUTO_SELL",
        "READ_ONLY",
        "FULL_DAILY_VALIDATION_ONLY",
        "VALIDATION_FAIL_COUNT",
        "FAIL_REASONS",
    )
    write_text(out_read_first, "\n".join(f"{key}: {values[key]}" for key in read_first_keys) + "\n")
    write_csv(out_summary, [{"metric": key, "value": value} for key, value in values.items()], SUMMARY_FIELDS)
    write_csv(out_audit, audit_rows, AUDIT_FIELDS)

    report = [
        "# V18.14A Full Daily Mode Validation",
        "",
        "Validation-only parser for existing V18.13D full daily outputs. V18.14A does not launch V18.13D.",
        "",
        "## Status",
        "",
    ]
    report.extend(f"- {key}: {values[key]}" for key in read_first_keys)
    report.extend(
        [
            f"- DANGEROUS_TOKEN_DETECTED: {values['DANGEROUS_TOKEN_DETECTED']}",
            f"- DANGEROUS_TOKEN_HITS: {values['DANGEROUS_TOKEN_HITS']}",
            "",
            "## Input Audit",
            "",
        ]
    )
    report.extend(markdown_table(audit_rows, AUDIT_FIELDS))
    if candidate_rows:
        fields = [field for field in ("rank", "ticker", "composite_candidate_score", "final_action", "technical_status") if field in candidate_fields]
        report.extend(["", "## Top Ranked Candidates", ""])
        report.extend(markdown_table(candidate_rows[:5], fields or candidate_fields[:5]))
    write_text(out_report, "\n".join(report) + "\n")

    for key in read_first_keys:
        print(f"{key}: {values[key]}")
    print(f"DANGEROUS_TOKEN_DETECTED: {values['DANGEROUS_TOKEN_DETECTED']}")

    return values, 0 if status == OK_STATUS else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="V18.14A validation-only parser for existing V18.13D full daily outputs.")
    parser.add_argument("--root", default=str(ROOT_DEFAULT))
    args = parser.parse_args()
    _, code = build(Path(args.root))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
