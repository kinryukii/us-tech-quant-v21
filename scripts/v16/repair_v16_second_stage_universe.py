from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_YAML = ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
OUT_SCREENED_YAML = ROOT / "configs" / "v16" / "universe" / "us_full_screened_generated.yaml"
OUT_STATUS = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"
OUT_AUDIT = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_SOURCE_AUDIT.csv"
OUT_TOP = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_TOP_CANDIDATES.csv"
OUT_READ_FIRST = ROOT / "outputs" / "v16" / "read_center" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_READ_FIRST.txt"

PASS_STATUS = "PASS_V16_SECOND_STAGE_UNIVERSE_REPAIR"
BLOCKED_STATUS = "BLOCKED_V16_SECOND_STAGE_UNIVERSE_REPAIR"

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")
HEADER_TOKENS = {"TICKER", "TICKERS", "SYMBOL", "SYMBOLS"}
CONTROL_TOKENS = {"TRUE", "FALSE", "NONE", "NULL", "NAN"}

SOURCE_CANDIDATES = [
    ("V18_RAW105_UNIVERSE_FOR_FACTOR_LAB", ROOT / "state" / "v18" / "raw105_universe_for_factor_lab.csv", "structured_csv"),
    ("V17_6E_SCREENED_UNIVERSE_TICKERS", ROOT / "outputs" / "v17" / "price" / "v17_6E_screened_universe_tickers.csv", "structured_csv"),
    ("V17_8A_RAW105_FULL_DECISION_DAILY", ROOT / "outputs" / "v17" / "raw105_decision" / "v17_8A_raw105_full_decision_daily.csv", "structured_csv"),
    ("V18_UNIVERSE_ROLLING_STATE", ROOT / "state" / "v18" / "universe" / "V18_UNIVERSE_ROLLING_STATE.csv", "structured_csv"),
    ("V18_PRICE_CACHE_FILENAMES", ROOT / "state" / "v18" / "price_cache", "price_cache_directory"),
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


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def valid_ticker(token: str) -> bool:
    token = clean(token).upper()
    if not token or token in HEADER_TOKENS or token in CONTROL_TOKENS:
        return False
    if token.isdigit() or len(token) > 12:
        return False
    if any(ch in token for ch in ("\\", "/", ";", ":", "|", "\t", "\n", "\r", " ")):
        return False
    if token.startswith((".", "-")) or token.endswith((".", "-")):
        return False
    return bool(TICKER_RE.fullmatch(token))


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
                reader = csv.DictReader(handle)
                return [dict(row) for row in reader], list(reader.fieldnames or [])
        except Exception:
            continue
    return [], []


def csv_tickers(path: Path) -> list[str]:
    rows, fields = read_csv_rows(path)
    lower = {field.lower(): field for field in fields}
    ticker_col = lower.get("ticker") or lower.get("symbol") or lower.get("yf_ticker")
    if not ticker_col:
        return []
    tickers: list[str] = []
    for row in rows:
        token = clean(row.get(ticker_col)).upper()
        if valid_ticker(token):
            tickers.append(token)
    return tickers


def price_cache_tickers(path: Path) -> list[str]:
    if not path.exists() or not path.is_dir():
        return []
    tickers: list[str] = []
    for item in path.glob("*.csv"):
        token = item.stem.upper()
        if valid_ticker(token) and item.stat().st_size > 0:
            tickers.append(token)
    return tickers


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_yaml(path: Path, tickers: list[str]) -> None:
    ensure_parent(path)
    lines = ["tickers:", *[f"  - {ticker}" for ticker in tickers], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def choose_source() -> tuple[str, Path, list[str], list[dict[str, object]]]:
    audit: list[dict[str, object]] = []
    for source_name, source_path, source_type in SOURCE_CANDIDATES:
        exists = source_path.exists()
        if source_type == "price_cache_directory":
            raw = price_cache_tickers(source_path)
        elif exists and source_path.is_file():
            raw = csv_tickers(source_path)
        else:
            raw = []
        accepted = sorted(dict.fromkeys(token for token in raw if valid_ticker(token)))
        duplicate_count = max(0, len([token for token in raw if valid_ticker(token)]) - len(accepted))
        audit.append({
            "source_name": source_name,
            "source_path": rel(source_path),
            "source_type": source_type,
            "exists": "TRUE" if exists else "FALSE",
            "raw_ticker_count": len(raw),
            "accepted_ticker_count": len(accepted),
            "duplicate_count": duplicate_count,
            "selected": "FALSE",
        })
        if len(accepted) >= 20:
            audit[-1]["selected"] = "TRUE"
            return source_name, source_path, accepted, audit
    return "", Path(), [], audit


def main() -> int:
    generated_at = now_utc()
    source_name, source_path, tickers, audit = choose_source()
    status = PASS_STATUS if tickers else BLOCKED_STATUS
    blocker = "" if tickers else "no_canonical_universe_source_with_ticker_rows"
    selected_audit = next((row for row in audit if row.get("selected") == "TRUE"), {})
    duplicate_count = int(selected_audit.get("duplicate_count") or 0)

    if tickers:
        write_yaml(OUT_YAML, tickers)
        write_yaml(OUT_SCREENED_YAML, tickers)
        top_rows = [
            {
                "rank": idx,
                "ticker": ticker,
                "symbol": ticker,
                "source": source_name,
                "source_file": rel(source_path),
                "restriction": "RESEARCH_ONLY_NO_TRADE",
            }
            for idx, ticker in enumerate(tickers, start=1)
        ]
        write_csv(OUT_TOP, top_rows, ["rank", "ticker", "symbol", "source", "source_file", "restriction"])

    write_csv(OUT_AUDIT, audit, ["source_name", "source_path", "source_type", "exists", "raw_ticker_count", "accepted_ticker_count", "duplicate_count", "selected"])
    status_rows = [{
        "STATUS": status,
        "generated_at_utc": generated_at,
        "selected_source_name": source_name,
        "selected_source_path": rel(source_path) if source_path else "",
        "ticker_count": len(tickers),
        "duplicate_count": duplicate_count,
        "yaml_path": rel(OUT_YAML),
        "screened_yaml_path": rel(OUT_SCREENED_YAML),
        "blocker_reason": blocker,
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "broker_order_execution_connected": "FALSE",
        "trade_action_created": "FALSE",
        "portfolio_weight_mutated": "FALSE",
        "provenance_note": "Generated from selected existing upstream universe source; no ticker rows fabricated.",
    }]
    write_csv(OUT_STATUS, status_rows, list(status_rows[0].keys()))
    write_text(
        OUT_READ_FIRST,
        "\n".join([
            "V16 SECOND-STAGE UNIVERSE REPAIR READ FIRST",
            f"STATUS: {status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"SELECTED_SOURCE_NAME: {source_name}",
            f"SELECTED_SOURCE_PATH: {rel(source_path) if source_path else ''}",
            f"TICKER_COUNT: {len(tickers)}",
            f"DUPLICATE_COUNT: {duplicate_count}",
            f"YAML_PATH: {rel(OUT_YAML)}",
            f"BLOCKER_REASON: {blocker}",
            "RESEARCH_ONLY: TRUE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "",
        ]),
    )

    print(status)
    print(f"SELECTED_SOURCE_NAME={source_name}")
    print(f"SELECTED_SOURCE_PATH={rel(source_path) if source_path else ''}")
    print(f"TICKER_COUNT={len(tickers)}")
    print(f"DUPLICATE_COUNT={duplicate_count}")
    print(f"YAML_PATH={rel(OUT_YAML)}")
    print(f"VALIDATION_STATUS={'PASS' if status == PASS_STATUS else 'BLOCKED'}")
    if blocker:
        print(f"BLOCKER_REASON={blocker}")
    return 0 if status == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
