from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs" / "v18" / "candidates" / "V18_13B_CURRENT_RANKED_CANDIDATES.csv"
SUMMARY = ROOT / "outputs" / "v18" / "read_center" / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"
ALIAS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv"
AUDIT = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_AUDIT.csv"
STATUS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv"
READ_FIRST = ROOT / "outputs" / "v18" / "read_center" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_READ_FIRST.txt"

PASS_ALIAS = "PASS_ALIAS_CREATED_FROM_FULL_V18_13B"
WARN_ALIAS = "WARN_ALIAS_CREATED_FROM_PARTIAL_V18_13B"
BLOCKED_ALIAS = "BLOCKED_V18_CURRENT_RANKED_CANDIDATES_ALIAS_REPAIR"
ALLOWED_SOURCE_STATUSES = {
    "OK_V18_13B_RANKED_CANDIDATE_READ_CENTER_READY",
    "WARN_V18_13B_PARTIAL_RANK_READY",
}


def clean(value: object) -> str:
    return str(value or "").strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
                reader = csv.DictReader(handle)
                return [dict(row) for row in reader], list(reader.fieldnames or [])
        except Exception:
            continue
    return [], []


def summary_map() -> dict[str, str]:
    rows, _ = read_csv(SUMMARY)
    return {clean(row.get("metric")): clean(row.get("value")) for row in rows}


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_source(rows: list[dict[str, str]], fields: list[str], source_status: str) -> list[str]:
    blockers: list[str] = []
    if not SOURCE.exists() or SOURCE.stat().st_size <= 0:
        blockers.append("source_missing_or_empty")
    if not rows:
        blockers.append("row_count_zero")
    field_set = {field.lower(): field for field in fields}
    ticker_col = field_set.get("ticker") or field_set.get("symbol")
    if not ticker_col:
        blockers.append("ticker_column_missing")
    has_rank_or_score = any(name in field_set for name in ("rank", "composite_candidate_score", "factor_pack_score", "technical_timing_score"))
    if not has_rank_or_score:
        blockers.append("rank_or_score_column_missing")
    if source_status not in ALLOWED_SOURCE_STATUSES:
        blockers.append(f"source_status_not_aliasable:{source_status or 'UNKNOWN'}")
    if ticker_col:
        tickers = [clean(row.get(ticker_col)).upper() for row in rows]
        if any(not ticker for ticker in tickers):
            blockers.append("blank_ticker")
        if len(tickers) != len(set(tickers)):
            blockers.append("duplicate_ticker")
    return blockers


def main() -> int:
    generated_at = now_utc()
    rows, fields = read_csv(SOURCE)
    summary = summary_map()
    source_status = summary.get("STATUS", "")
    rank_source_status = summary.get("RANK_SOURCE_STATUS", "")
    blockers = validate_source(rows, fields, source_status)
    if blockers:
        alias_status = BLOCKED_ALIAS
    elif source_status == "WARN_V18_13B_PARTIAL_RANK_READY":
        alias_status = WARN_ALIAS
    else:
        alias_status = PASS_ALIAS

    if alias_status != BLOCKED_ALIAS:
        ALIAS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE, ALIAS)

    row_count = len(rows)
    scored_count = summary.get("SCORED_TICKER_COUNT", "")
    unscored_count = summary.get("UNSCORED_TICKER_COUNT", "")
    top5 = summary.get("TOP_5_TICKERS", "")
    audit_rows = [{
        "alias_status": alias_status,
        "source_file": rel(SOURCE),
        "alias_file": rel(ALIAS),
        "source_exists": "TRUE" if SOURCE.exists() else "FALSE",
        "alias_exists": "TRUE" if ALIAS.exists() else "FALSE",
        "row_count": row_count,
        "source_v18_13b_status": source_status,
        "rank_source_status": rank_source_status,
        "scored_ticker_count": scored_count,
        "unscored_ticker_count": unscored_count,
        "top_5_tickers": top5,
        "duplicate_ticker_policy": "BLOCK_ALIAS_ON_DUPLICATE_TICKER",
        "blocker_reason": ";".join(blockers),
        "research_only": "TRUE",
        "official_decision_impact": "NONE",
    }]
    write_csv(AUDIT, audit_rows, list(audit_rows[0].keys()))
    write_csv(STATUS, audit_rows, list(audit_rows[0].keys()))
    write_text(
        READ_FIRST,
        "\n".join([
            "V18 CURRENT RANKED CANDIDATES ALIAS READ FIRST",
            f"ALIAS_STATUS: {alias_status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"SOURCE_FILE: {rel(SOURCE)}",
            f"ALIAS_FILE: {rel(ALIAS)}",
            f"ROW_COUNT: {row_count}",
            f"V18_13B_STATUS: {source_status}",
            f"RANK_SOURCE_STATUS: {rank_source_status}",
            f"SCORED_TICKER_COUNT: {scored_count}",
            f"UNSCORED_TICKER_COUNT: {unscored_count}",
            f"TOP_5_TICKERS: {top5}",
            f"BLOCKER_REASON: {';'.join(blockers)}",
            "RESEARCH_ONLY: TRUE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "",
        ]),
    )
    print(alias_status)
    print(f"ROW_COUNT={row_count}")
    print(f"SOURCE_FILE={rel(SOURCE)}")
    print(f"ALIAS_FILE={rel(ALIAS)}")
    if blockers:
        print(f"BLOCKER_REASON={';'.join(blockers)}")
    return 0 if alias_status != BLOCKED_ALIAS else 1


if __name__ == "__main__":
    raise SystemExit(main())
