from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "state" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS.csv"
OUT_STATUS = ROOT / "outputs" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_STATUS.csv"
OUT_AUDIT = ROOT / "outputs" / "v18" / "universe" / "V18_MANUAL_UNIVERSE_ADDITIONS_SOURCE_AUDIT.csv"
OUT_READ_FIRST = ROOT / "outputs" / "v18" / "read_center" / "V18_MANUAL_UNIVERSE_ADDITIONS_REPAIR_READ_FIRST.txt"

WARN_EMPTY_STATUS = "WARN_NO_MANUAL_UNIVERSE_ADDITIONS_EMPTY_FILE_CREATED"
PASS_EXISTING_STATUS = "PASS_MANUAL_UNIVERSE_ADDITIONS_FILE_PRESENT"
BLOCKED_STATUS = "BLOCKED_MANUAL_UNIVERSE_ADDITIONS_REPAIR"

FIELDS = [
    "ticker",
    "initial_tier",
    "source_tag",
    "company_name",
    "sector",
    "industry",
    "note",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value: object) -> str:
    return str(value or "").strip()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING"
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
                reader = csv.DictReader(handle)
                return [dict(row) for row in reader], list(reader.fieldnames or []), "OK"
        except Exception:
            continue
    return [], [], "CSV_PARSE_FAILED"


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


def main() -> int:
    generated_at = now_utc()
    existed_before = TARGET.exists()
    rows, fields, parse_status = read_csv(TARGET)

    blocker = ""
    created_empty = False
    if not existed_before:
        write_csv(TARGET, [], FIELDS)
        rows, fields, parse_status = read_csv(TARGET)
        created_empty = True

    missing_required = [field for field in FIELDS if field not in fields]
    if missing_required:
        status = BLOCKED_STATUS
        blocker = "missing_required_columns:" + ",".join(missing_required)
    elif parse_status != "OK":
        status = BLOCKED_STATUS
        blocker = parse_status
    elif rows:
        status = PASS_EXISTING_STATUS
    else:
        status = WARN_EMPTY_STATUS

    status_rows = [{
        "STATUS": status,
        "generated_at_utc": generated_at,
        "target_path": rel(TARGET),
        "file_existed_before_repair": "TRUE" if existed_before else "FALSE",
        "empty_file_created": "TRUE" if created_empty else "FALSE",
        "manual_addition_row_count": len(rows),
        "schema_columns": ";".join(fields),
        "blocker_reason": blocker,
        "research_only": "TRUE",
        "fabricated_ticker_rows": "FALSE",
        "official_recommendation_created": "FALSE",
        "broker_order_execution_connected": "FALSE",
    }]
    audit_rows = [{
        "source_name": "NO_EXTERNAL_MANUAL_ADDITION_SOURCE_USED",
        "source_path": rel(TARGET),
        "source_exists": "TRUE" if TARGET.exists() else "FALSE",
        "row_count": len(rows),
        "schema_valid": "TRUE" if not missing_required and parse_status == "OK" else "FALSE",
        "created_empty_schema_file": "TRUE" if created_empty else "FALSE",
        "decision": "EMPTY_SCHEMA_VALID_FILE_ACCEPTED_AS_ZERO_MANUAL_ADDITIONS" if status == WARN_EMPTY_STATUS else status,
        "blocker_reason": blocker,
    }]

    write_csv(OUT_STATUS, status_rows, list(status_rows[0].keys()))
    write_csv(OUT_AUDIT, audit_rows, list(audit_rows[0].keys()))
    write_text(
        OUT_READ_FIRST,
        "\n".join([
            "V18 MANUAL UNIVERSE ADDITIONS REPAIR READ FIRST",
            f"STATUS: {status}",
            f"GENERATED_AT_UTC: {generated_at}",
            f"TARGET_PATH: {rel(TARGET)}",
            f"FILE_EXISTED_BEFORE_REPAIR: {'TRUE' if existed_before else 'FALSE'}",
            f"EMPTY_FILE_CREATED: {'TRUE' if created_empty else 'FALSE'}",
            f"MANUAL_ADDITION_ROW_COUNT: {len(rows)}",
            f"SCHEMA_COLUMNS: {';'.join(fields)}",
            f"BLOCKER_REASON: {blocker}",
            "RESEARCH_ONLY: TRUE",
            "FABRICATED_TICKER_ROWS: FALSE",
            "OFFICIAL_RECOMMENDATION_CREATED: FALSE",
            "BROKER_ORDER_EXECUTION_CONNECTED: FALSE",
            "",
        ]),
    )

    print(status)
    print(f"MANUAL_ADDITION_ROW_COUNT={len(rows)}")
    print(f"TARGET_PATH={rel(TARGET)}")
    if blocker:
        print(f"BLOCKER_REASON={blocker}")
    return 0 if status != BLOCKED_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
