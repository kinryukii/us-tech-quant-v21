from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_RANKED = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES.csv"
RANKED_ALIAS_STATUS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_RANKED_CANDIDATES_ALIAS_STATUS.csv"
V18_13B_SUMMARY = ROOT / "outputs" / "v18" / "read_center" / "V18_13B_CURRENT_RANKED_CANDIDATE_SUMMARY.csv"
CURRENT_FACTOR = ROOT / "outputs" / "v18" / "factor_pack" / "V18_CURRENT_RAW105_FACTOR_PACK_RANKING.csv"
CURRENT_TECH = ROOT / "outputs" / "v18" / "technical_timing" / "V18_6A_CURRENT_TECHNICAL_TIMING.csv"
OUT_FULL = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES.csv"
OUT_AUDIT = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_SOURCE_AUDIT.csv"
OUT_STATUS = ROOT / "outputs" / "v18" / "candidates" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_STATUS.csv"
OUT_READ_FIRST = ROOT / "outputs" / "v18" / "read_center" / "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR_READ_FIRST.txt"

PASS_STATUS = "PASS_V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR"
WARN_STATUS = "WARN_V18_CURRENT_FULL_RANKED_CANDIDATES_FROM_PARTIAL_CURRENT_RANKING"
BLOCKED_STATUS = "BLOCKED_V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")

OUT_FIELDS = [
    "rank",
    "ticker",
    "composite_candidate_score",
    "factor_score",
    "technical_score",
    "ranking_source_policy",
    "primary_score_source_files",
    "audit_only_source_files",
    "score_source_status",
    "score_source_files",
    "score_source_columns",
    "latest_price_date",
    "latest_close",
    "technical_status",
    "event_risk_status",
    "overheat_status",
    "pullback_status",
    "execution_status",
    "final_action",
    "reason",
    "source_stage",
    "source_file",
    "source_v18_13b_status",
    "source_alias_status",
    "research_only",
    "official_decision_impact",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def valid_ticker(value: object) -> bool:
    ticker = clean(value).upper()
    return bool(ticker) and len(ticker) <= 12 and bool(TICKER_RE.fullmatch(ticker))


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


def first_row_map(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def key_value_summary(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return {clean(row.get("metric")): clean(row.get("value")) for row in rows if clean(row.get("metric"))}


def index_by_ticker(path: Path) -> dict[str, dict[str, str]]:
    rows, _ = read_csv(path)
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = clean(row.get("ticker") or row.get("yf_ticker")).upper()
        if ticker and ticker not in out:
            out[ticker] = row
    return out


def to_float(value: object) -> float | None:
    try:
        text = clean(value).replace(",", "")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def normalize_rows(
    ranked_rows: list[dict[str, str]],
    factor_idx: dict[str, dict[str, str]],
    tech_idx: dict[str, dict[str, str]],
    source_v18_13b_status: str,
    source_alias_status: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in ranked_rows:
        ticker = clean(source.get("ticker")).upper()
        if not valid_ticker(ticker):
            continue
        factor = factor_idx.get(ticker, {})
        tech = tech_idx.get(ticker, {})
        latest_price_date = clean(source.get("latest_price_date") or factor.get("latest_price_date") or tech.get("latest_price_date") or tech.get("price_date"))
        latest_close = clean(source.get("latest_close") or factor.get("latest_close") or tech.get("latest_price") or tech.get("close"))
        factor_score = clean(source.get("factor_score") or factor.get("factor_pack_score"))
        technical_score = clean(source.get("technical_score") or tech.get("technical_timing_score"))
        rows.append({
            "rank": clean(source.get("rank")),
            "ticker": ticker,
            "composite_candidate_score": clean(source.get("composite_candidate_score")),
            "factor_score": factor_score,
            "technical_score": technical_score,
            "ranking_source_policy": "V18_35D_CURRENT_FULL_HANDOFF_REPAIR_FROM_CURRENT_RANKING",
            "primary_score_source_files": clean(source.get("primary_score_source_files") or f"{rel(CURRENT_FACTOR)};{rel(CURRENT_TECH)}"),
            "audit_only_source_files": clean(source.get("audit_only_source_files") or "NONE"),
            "score_source_status": clean(source.get("score_source_status")),
            "score_source_files": clean(source.get("score_source_files") or f"{rel(CURRENT_FACTOR)};{rel(CURRENT_TECH)}"),
            "score_source_columns": clean(source.get("score_source_columns") or "factor_pack_score;technical_timing_score"),
            "latest_price_date": latest_price_date,
            "latest_close": latest_close,
            "technical_status": clean(source.get("technical_status") or tech.get("technical_status") or tech.get("technical_signal")),
            "event_risk_status": clean(source.get("event_risk_status")),
            "overheat_status": clean(source.get("overheat_status") or tech.get("overheat_status")),
            "pullback_status": clean(source.get("pullback_status") or tech.get("pullback_status")),
            "execution_status": clean(source.get("execution_status") or "REVIEW_ONLY"),
            "final_action": clean(source.get("final_action") or "REVIEW_ONLY"),
            "reason": "Research-only full-ranked handoff repaired from current V18 ranked candidates; no ticker rows fabricated.",
            "source_stage": "V18_CURRENT_FULL_RANKED_CANDIDATES_REPAIR",
            "source_file": rel(SOURCE_RANKED),
            "source_v18_13b_status": source_v18_13b_status,
            "source_alias_status": source_alias_status,
            "research_only": "TRUE",
            "official_decision_impact": "NONE",
        })
    if any(not clean(row.get("rank")) for row in rows):
        rows.sort(
            key=lambda row: (
                to_float(row.get("composite_candidate_score")) is None,
                -(to_float(row.get("composite_candidate_score")) or -10**9),
                clean(row.get("ticker")),
            )
        )
        for i, row in enumerate(rows, 1):
            row["rank"] = str(i)
    else:
        rows.sort(key=lambda row: (to_float(row.get("rank")) or 10**9, clean(row.get("ticker"))))
    return rows


def validate_source(rows: list[dict[str, str]], fields: list[str]) -> list[str]:
    blockers: list[str] = []
    field_set = {field.lower() for field in fields}
    if not SOURCE_RANKED.exists() or SOURCE_RANKED.stat().st_size <= 0:
        blockers.append("current_ranked_source_missing_or_empty")
    if not rows:
        blockers.append("current_ranked_row_count_zero")
    if "ticker" not in field_set:
        blockers.append("ticker_column_missing")
    if "rank" not in field_set and "composite_candidate_score" not in field_set:
        blockers.append("rank_or_score_column_missing")
    tickers = [clean(row.get("ticker")).upper() for row in rows]
    if any(not valid_ticker(ticker) for ticker in tickers):
        blockers.append("invalid_or_blank_ticker")
    if len(tickers) != len(set(tickers)):
        blockers.append("duplicate_ticker")
    return blockers


def main() -> int:
    generated_at = now_utc()
    ranked_rows, ranked_fields = read_csv(SOURCE_RANKED)
    source_status = key_value_summary(V18_13B_SUMMARY).get("STATUS", "")
    alias_row = first_row_map(RANKED_ALIAS_STATUS)
    alias_status = clean(alias_row.get("alias_status"))
    blockers = validate_source(ranked_rows, ranked_fields)

    repair_status = BLOCKED_STATUS
    if not blockers:
        repair_status = WARN_STATUS if "WARN" in f"{source_status} {alias_status}" else PASS_STATUS

    factor_idx = index_by_ticker(CURRENT_FACTOR)
    tech_idx = index_by_ticker(CURRENT_TECH)
    out_rows = normalize_rows(ranked_rows, factor_idx, tech_idx, source_status, alias_status) if repair_status != BLOCKED_STATUS else []
    if repair_status != BLOCKED_STATUS and not out_rows:
        blockers.append("normalized_output_row_count_zero")
        repair_status = BLOCKED_STATUS

    if repair_status != BLOCKED_STATUS:
        write_csv(OUT_FULL, out_rows, OUT_FIELDS)

    audit = [{
        "repair_status": repair_status,
        "generated_at_utc": generated_at,
        "source_file": rel(SOURCE_RANKED),
        "output_file": rel(OUT_FULL),
        "source_exists": "TRUE" if SOURCE_RANKED.exists() else "FALSE",
        "source_row_count": len(ranked_rows),
        "output_row_count": len(out_rows),
        "source_v18_13b_status": source_status,
        "source_alias_status": alias_status,
        "factor_source_file": rel(CURRENT_FACTOR),
        "technical_source_file": rel(CURRENT_TECH),
        "factor_row_count": len(factor_idx),
        "technical_row_count": len(tech_idx),
        "duplicate_ticker_policy": "BLOCK_REPAIR_ON_DUPLICATE_TICKER",
        "blocker_reason": ";".join(blockers),
        "research_only": "TRUE",
        "official_decision_impact": "NONE",
        "fabricated_ticker_rows": "FALSE",
    }]
    write_csv(OUT_AUDIT, audit, list(audit[0].keys()))
    write_csv(OUT_STATUS, audit, list(audit[0].keys()))
    write_text(
        OUT_READ_FIRST,
        "\n".join([
            "V18 CURRENT FULL RANKED CANDIDATES REPAIR READ FIRST",
            f"REPAIR_STATUS: {repair_status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"SOURCE_FILE: {rel(SOURCE_RANKED)}",
            f"OUTPUT_FILE: {rel(OUT_FULL)}",
            f"SOURCE_ROW_COUNT: {len(ranked_rows)}",
            f"OUTPUT_ROW_COUNT: {len(out_rows)}",
            f"V18_13B_STATUS: {source_status}",
            f"CURRENT_RANKED_ALIAS_STATUS: {alias_status}",
            f"BLOCKER_REASON: {';'.join(blockers)}",
            "RESEARCH_ONLY: TRUE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "FABRICATED_TICKER_ROWS: FALSE",
            "",
        ]),
    )
    print(repair_status)
    print(f"ROW_COUNT={len(out_rows)}")
    print(f"SOURCE_FILE={rel(SOURCE_RANKED)}")
    print(f"OUTPUT_FILE={rel(OUT_FULL)}")
    if blockers:
        print(f"BLOCKER_REASON={';'.join(blockers)}")
    return 0 if repair_status != BLOCKED_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
