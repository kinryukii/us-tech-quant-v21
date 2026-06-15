from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCAN_DIRS = [CONSOLIDATION, READ_CENTER, OPS]

STAGE = "V20.83_AUTHORITATIVE_OFFICIAL_CURRENT_TICKER_LEVEL_RANKING_EXPORT"
PASS_STATUS = "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT"
PRICE_GAPS_STATUS = "PASS_V20_83_AUTHORITATIVE_EXPORT_WITH_PRICE_GAPS"
NO_SOURCE_STATUS = "BLOCKED_V20_83_NO_AUTHORITATIVE_OFFICIAL_CURRENT_SOURCE"
AMBIGUOUS_STATUS = "BLOCKED_V20_83_AMBIGUOUS_CURRENT_SOURCE"
ACCEPTANCE_MISSING_STATUS = "BLOCKED_V20_83_ACCEPTANCE_PROOF_MISSING"

RANKING_FIELDS = [
    "ticker",
    "official_current_rank",
    "official_current_score",
    "score_name",
    "latest_price",
    "latest_price_date",
    "source_stage",
    "source_run_id",
    "source_file",
    "source_role",
    "ranking_timestamp_utc",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
    "certification_status",
    "certification_reason",
    "acceptance_proof_status",
    "acceptance_proof_file",
    "acceptance_proof_stage",
    "acceptance_proof_reason",
    "acceptance_summary_file",
    "acceptance_summary_status",
    "acceptance_package_manifest_file",
    "acceptance_package_manifest_status",
    "accepted_artifact_path",
    "accepted_artifact_validation_status",
    "exact_artifact_proof_status",
    "exact_artifact_proof_reason",
    "source_row_count",
    "unique_ticker_count",
    "duplicate_ticker_count",
    "deduplication_rule",
]

AUDIT_FIELDS = [
    "candidate_file",
    "candidate_role",
    "detected_stage",
    "detected_run_id",
    "has_ticker",
    "has_rank",
    "has_score",
    "has_price",
    "row_count",
    "accepted_as_official_current",
    "reject_reason",
    "unique_ticker_count",
    "duplicate_ticker_count",
    "deduplication_rule",
    "certification_reason",
]

OUTPUTS = {
    "ranking": CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    "audit": CONSOLIDATION / "V20_83_OFFICIAL_CURRENT_INPUT_BINDING_AUDIT.csv",
    "report": READ_CENTER / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_REPORT.md",
    "manifest": OPS / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json",
}

APPROVED_SOURCE_RULES = [
    (
        "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv",
        "OPERATOR_ACCEPTED_CURRENT_RESEARCH",
        "V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH",
        ["normalized_ticker", "ticker_or_candidate_id", "ticker"],
        ["report_rank", "rank", "current_rank"],
        ["source_rank_or_score", "current_score", "score"],
        ["refreshed_latest_close", "latest_price", "latest_refreshed_price"],
        ["refreshed_price_date", "latest_price_date", "price_date_or_run_id"],
    ),
    (
        "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv",
        "CURRENT_DECISION_PACKET_RESEARCH_ONLY",
        "V20.50_RESEARCH_ONLY_DECISION_PACKET",
        ["normalized_ticker", "display_name_or_ticker", "ticker"],
        ["report_rank", "rank", "current_rank"],
        ["current_score", "score", "official_current_score"],
        ["refreshed_latest_close", "latest_price"],
        ["refreshed_price_date", "latest_price_date"],
    ),
    (
        "V20_67_DAILY_OPERATION_CANDIDATE_PACKET.csv",
        "CURRENT_DAILY_RESEARCH_PACKET",
        "V20.67_DAILY_OPERATION_RESEARCH_PACKET",
        ["ticker"],
        ["official_current_rank", "current_rank", "report_rank", "rank"],
        ["official_current_score", "current_score", "score"],
        ["latest_refreshed_price", "latest_price"],
        ["latest_price_date"],
    ),
    (
        "V20_68_READABLE_PRIORITY_REVIEW_TABLE.csv",
        "CURRENT_READABLE_REPORT_LAYER",
        "V20.68_DAILY_OPERATION_READABLE_REPORT_LAYER",
        ["ticker"],
        ["official_current_rank", "current_rank", "report_rank", "rank"],
        ["official_current_score", "current_score", "score"],
        ["latest_refreshed_price", "latest_price"],
        ["latest_price_date", "price_date_or_run_id"],
    ),
    (
        "V20_68_READABLE_STANDARD_REVIEW_TABLE.csv",
        "CURRENT_READABLE_REPORT_LAYER",
        "V20.68_DAILY_OPERATION_READABLE_REPORT_LAYER",
        ["ticker"],
        ["official_current_rank", "current_rank", "report_rank", "rank"],
        ["official_current_score", "current_score", "score"],
        ["latest_refreshed_price", "latest_price"],
        ["latest_price_date", "price_date_or_run_id"],
    ),
    (
        "V20_69_EXPORT_READY_DAILY_OPERATION_BRIEF.csv",
        "CURRENT_DAILY_OPERATION_EXPORT",
        "V20.69_DAILY_OPERATION_REVIEW_ACCEPTANCE_AND_EXPORT_GATE",
        ["ticker"],
        ["official_current_rank", "current_rank", "report_rank", "rank"],
        ["official_current_score", "current_score", "score"],
        ["latest_price"],
        ["latest_price_date"],
    ),
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return "V20_83_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_83_", "V20_CURRENT_", 1))


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except (OSError, csv.Error, UnicodeDecodeError):
        return [], [], "UNUSABLE_SCHEMA"
    if not fields:
        return [], [], "UNUSABLE_SCHEMA"
    return rows, fields, "OK"


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean(row.get(field)) for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def find_column(fields: list[str], names: list[str]) -> str:
    by_lower = {field.lower(): field for field in fields}
    for name in names:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return ""


def detect_run_id(path: Path, rows: list[dict[str, str]]) -> str:
    for row in rows:
        for column in ["source_run_id", "v20_47_run_id", "run_id", "stage_run_id", "provider_refresh_run_id"]:
            value = clean(row.get(column))
            if value:
                return value
    match = re.search(r"V20_\d{2,}[A-Z]?_\d{8}T\d{6}Z", path.name)
    return match.group(0) if match else ""


def acceptance_proof_for(source_path: Path, source_run_id: str) -> dict[str, str]:
    source_artifact = rel(source_path)
    if source_path.name.upper() != "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.CSV":
        return {
            "acceptance_proof_status": "NOT_REQUIRED_FOR_SOURCE_ROLE",
            "acceptance_proof_file": "",
            "acceptance_proof_stage": "",
            "acceptance_proof_reason": "Source role does not require V20.48 downstream acceptance proof.",
            "acceptance_summary_file": "",
            "acceptance_summary_status": "NOT_REQUIRED",
            "acceptance_package_manifest_file": "",
            "acceptance_package_manifest_status": "NOT_REQUIRED",
            "accepted_artifact_path": "",
            "accepted_artifact_validation_status": "NOT_REQUIRED",
            "exact_artifact_proof_status": "NOT_REQUIRED",
            "exact_artifact_proof_reason": "Exact V20.49 package proof is not required for this source role.",
        }
    summary_path = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
    package_path = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_PACKAGE_MANIFEST.csv"
    summary_rows, _summary_fields, summary_read_status = read_csv(summary_path)
    summary_status = "MISSING_OR_UNUSABLE"
    summary_ok = False
    if summary_read_status == "OK":
        for row in summary_rows:
            accepted = clean(row.get("acceptance_status")) == "ACCEPTED_FOR_OPERATOR_REVIEW_RESEARCH_ONLY"
            run_ok = not source_run_id or clean(row.get("v20_47_run_id")) == source_run_id
            if accepted and run_ok:
                summary_ok = True
                summary_status = clean(row.get("acceptance_status"))
                break
        if not summary_ok and summary_rows:
            summary_status = clean(summary_rows[0].get("acceptance_status") or "NOT_ACCEPTED_OR_RUN_MISMATCH")

    package_rows, _package_fields, package_read_status = read_csv(package_path)
    package_status = "MISSING_OR_UNUSABLE"
    artifact_row: dict[str, str] | None = None
    if package_read_status == "OK":
        for row in package_rows:
            if clean(row.get("artifact_path")).replace("\\", "/") == source_artifact:
                artifact_row = row
                break
    if artifact_row:
        checks = {
            "exists_flag": clean(artifact_row.get("exists_flag")) == "TRUE",
            "non_empty_flag": clean(artifact_row.get("non_empty_flag")) == "TRUE",
            "research_only_flag": clean(artifact_row.get("research_only_flag")) == "TRUE",
            "official_recommendation_allowed": clean(artifact_row.get("official_recommendation_allowed")) == "FALSE",
            "trading_allowed": clean(artifact_row.get("trading_allowed")) == "FALSE",
            "validation_status": clean(artifact_row.get("validation_status")) == "PASS",
        }
        package_ok = all(checks.values())
        package_status = "PASS" if package_ok else "FAILED_REQUIRED_ARTIFACT_FLAGS"
        failed = [name for name, ok in checks.items() if not ok]
    else:
        package_ok = False
        failed = ["EXACT_ARTIFACT_ROW_MISSING"]

    if summary_ok and package_ok and artifact_row:
        return {
            "acceptance_proof_status": "FOUND",
            "acceptance_proof_file": rel(summary_path),
            "acceptance_proof_stage": "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE",
            "acceptance_proof_reason": "V20.49 acceptance summary matched source run id and exact package manifest artifact row passed.",
            "acceptance_summary_file": rel(summary_path),
            "acceptance_summary_status": summary_status,
            "acceptance_package_manifest_file": rel(package_path),
            "acceptance_package_manifest_status": package_status,
            "accepted_artifact_path": clean(artifact_row.get("artifact_path")),
            "accepted_artifact_validation_status": clean(artifact_row.get("validation_status")),
            "exact_artifact_proof_status": "FOUND",
            "exact_artifact_proof_reason": "Exact bound artifact path found in V20.49 package manifest with required research-only/non-trading flags.",
        }
    reason_parts = []
    if not summary_ok:
        reason_parts.append(f"ACCEPTANCE_SUMMARY_NOT_VALID:{summary_status}")
    if not package_ok:
        reason_parts.append("EXACT_PACKAGE_ARTIFACT_PROOF_NOT_VALID:" + ",".join(failed))
    return {
        "acceptance_proof_status": "MISSING",
        "acceptance_proof_file": "",
        "acceptance_proof_stage": "",
        "acceptance_proof_reason": ";".join(reason_parts),
        "acceptance_summary_file": rel(summary_path),
        "acceptance_summary_status": summary_status,
        "acceptance_package_manifest_file": rel(package_path),
        "acceptance_package_manifest_status": package_status,
        "accepted_artifact_path": clean(artifact_row.get("artifact_path")) if artifact_row else "",
        "accepted_artifact_validation_status": clean(artifact_row.get("validation_status")) if artifact_row else "",
        "exact_artifact_proof_status": "MISSING",
        "exact_artifact_proof_reason": ";".join(reason_parts),
    }


def stage_number(path: Path) -> int:
    match = re.search(r"V20_(\d{2})", path.name.upper())
    return int(match.group(1)) if match else -1


def source_rule(path: Path) -> tuple[str, str, str, list[str], list[str], list[str], list[str], list[str]] | None:
    for rule in APPROVED_SOURCE_RULES:
        if path.name.upper() == rule[0].upper():
            return rule
    return None


def rejected_role(path: Path) -> str:
    name = path.name.upper()
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json"}:
        return "README_OR_REPORT_ONLY"
    if "V20_76" in name or "SHADOW_OPERATIONAL" in name:
        return "SHADOW_OPERATIONAL"
    if "V20_75" in name or "RANK_CHANGE_ATTRIBUTION" in name:
        return "RANK_CHANGE_ATTRIBUTION_ONLY"
    if "V20_80_REQUIRED_OUTPUT_CHECKS" in name or "V20_81_REQUIRED_OUTPUT_CHECKS" in name or "REQUIRED_OUTPUT_CHECKS" in name or "CHECKS" in name:
        return "REQUIRED_OUTPUT_CHECKS"
    if "MANIFEST" in name:
        return "MANIFEST_ONLY"
    if "SUMMARY" in name or "DIAGNOSTIC" in name or "STATUS" in name:
        return "DIAGNOSTIC_ONLY"
    if "V20_73" in name or "V20_74" in name or "OVERLAY" in name:
        return "OVERLAY_ONLY"
    if suffix in {".md", ".txt"} or "READ_FIRST" in name or "REPORT" in name:
        return "README_OR_REPORT_ONLY"
    return "UNCLASSIFIED_REJECTED"


def scan_candidates() -> list[Path]:
    paths: list[Path] = []
    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        paths.extend(path for path in directory.iterdir() if path.is_file() and "V20_83" not in path.name.upper())
    return sorted(paths, key=lambda path: (stage_number(path), path.stat().st_mtime, path.name), reverse=True)


def row_counts(rows: list[dict[str, str]], ticker_col: str) -> tuple[int, int, str]:
    if not rows or not ticker_col:
        return 0, 0, "NA"
    unique = {clean(row.get(ticker_col)).upper() for row in rows if clean(row.get(ticker_col))}
    return len(unique), max(0, len(rows) - len(unique)), "first_ranked_row_kept"


def build_audit_row(path: Path, role: str, stage: str, run_id: str, rows: list[dict[str, str]], fields: list[str], ticker_col: str, rank_col: str, score_col: str, price_col: str, accepted: bool, reject_reason: str) -> dict[str, object]:
    unique_ticker_count, duplicate_ticker_count, deduplication_rule = row_counts(rows, ticker_col)
    certification_reason = ""
    if accepted:
        certification_reason = f"Ticker/rank/score source accepted; source rows={len(rows)}, unique tickers={unique_ticker_count}, duplicate tickers={duplicate_ticker_count}, deduplication_rule={deduplication_rule}."
    return {
        "candidate_file": rel(path),
        "candidate_role": role,
        "detected_stage": stage,
        "detected_run_id": run_id,
        "has_ticker": tf(bool(ticker_col)),
        "has_rank": tf(bool(rank_col)),
        "has_score": tf(bool(score_col)),
        "has_price": tf(bool(price_col)),
        "row_count": len(rows),
        "accepted_as_official_current": tf(accepted),
        "reject_reason": reject_reason,
        "unique_ticker_count": unique_ticker_count,
        "duplicate_ticker_count": duplicate_ticker_count,
        "deduplication_rule": deduplication_rule,
        "certification_reason": certification_reason,
    }


def discover_source() -> tuple[dict[str, object] | None, list[dict[str, object]], str]:
    audit_rows: list[dict[str, object]] = []
    accepted: list[dict[str, object]] = []
    acceptance_missing_seen = False
    for path in scan_candidates():
        rule = source_rule(path)
        if not rule:
            role = rejected_role(path)
            if role != "UNCLASSIFIED_REJECTED":
                rows, fields, _status = read_csv(path) if path.suffix.lower() == ".csv" else ([], [], "UNUSABLE_SCHEMA")
                audit_rows.append(build_audit_row(path, role, "", detect_run_id(path, rows), rows, fields, "", "", "", "", False, role))
            continue
        _, role, stage, ticker_names, rank_names, score_names, price_names, price_date_names = rule
        rows, fields, status = read_csv(path)
        ticker_col = find_column(fields, ticker_names)
        rank_col = find_column(fields, rank_names)
        score_col = find_column(fields, score_names)
        price_col = find_column(fields, price_names)
        price_date_col = find_column(fields, price_date_names)
        run_id = detect_run_id(path, rows)
        reasons: list[str] = []
        if status != "OK" or not rows:
            reasons.append(status)
        if not ticker_col:
            reasons.append("MISSING_TICKER")
        if not rank_col:
            reasons.append("MISSING_RANK")
        if not score_col:
            reasons.append("MISSING_SCORE")
        valid = status == "OK" and bool(rows) and bool(ticker_col) and bool(rank_col) and bool(score_col)
        reject_reason = "" if valid else ";".join(reasons)
        audit_rows.append(build_audit_row(path, role, stage, run_id, rows, fields, ticker_col, rank_col, score_col, price_col, valid, reject_reason))
        if valid:
            proof = acceptance_proof_for(path, run_id)
            effective_role = role
            effective_valid = True
            if path.name.upper() == "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.CSV" and proof["acceptance_proof_status"] != "FOUND":
                effective_role = "CURRENT_REFRESHED_RESEARCH_VIEW_ACCEPTANCE_PENDING"
                effective_valid = False
                acceptance_missing_seen = True
                audit_rows[-1]["candidate_role"] = effective_role
                audit_rows[-1]["accepted_as_official_current"] = "FALSE"
                audit_rows[-1]["reject_reason"] = "BLOCKED_ACCEPTANCE_PROOF_MISSING"
            if not effective_valid:
                continue
            accepted.append(
                {
                    "path": path,
                    "role": effective_role,
                    "stage": stage,
                    "run_id": run_id,
                    "rows": rows,
                    "ticker_col": ticker_col,
                    "rank_col": rank_col,
                    "score_col": score_col,
                    "score_name": score_col,
                    "price_col": price_col,
                    "price_date_col": price_date_col,
                    **proof,
                }
            )
    if len(accepted) > 1:
        top_stage = max(stage_number(item["path"]) for item in accepted)
        top = [item for item in accepted if stage_number(item["path"]) == top_stage]
        if len(top) > 1:
            return None, audit_rows, AMBIGUOUS_STATUS
        return top[0], audit_rows, PASS_STATUS
    if accepted:
        return accepted[0], audit_rows, PASS_STATUS
    if acceptance_missing_seen:
        return None, audit_rows, ACCEPTANCE_MISSING_STATUS
    return None, audit_rows, NO_SOURCE_STATUS


def source_counts(source: dict[str, object] | None) -> tuple[int, int, int, str]:
    if not source:
        return 0, 0, 0, "NA"
    rows = list(source["rows"])
    ticker_col = clean(source["ticker_col"])
    unique = {clean(row.get(ticker_col)).upper() for row in rows if clean(row.get(ticker_col))}
    duplicate_count = max(0, len(rows) - len(unique))
    return len(rows), len(unique), duplicate_count, "first_ranked_row_kept"


def build_ranking_rows(source: dict[str, object] | None, created_at: str) -> tuple[list[dict[str, object]], bool]:
    if not source:
        return [], False
    rows = list(source["rows"])
    price_col = clean(source.get("price_col"))
    price_date_col = clean(source.get("price_date_col"))
    output: list[dict[str, object]] = []
    missing_price = False
    seen: set[str] = set()
    source_row_count, unique_ticker_count, duplicate_ticker_count, deduplication_rule = source_counts(source)
    dedupe_reason = f"Source had {source_row_count} rows and {unique_ticker_count} unique tickers; duplicate tickers collapsed using {deduplication_rule}."
    for row in rows:
        ticker = clean(row.get(clean(source["ticker_col"]))).upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        price = clean(row.get(price_col)) if price_col else ""
        if not price:
            missing_price = True
        output.append(
            {
                "ticker": ticker,
                "official_current_rank": clean(row.get(clean(source["rank_col"]))),
                "official_current_score": clean(row.get(clean(source["score_col"]))),
                "score_name": clean(source["score_name"]),
                "latest_price": price if price else "NA",
                "latest_price_date": clean(row.get(price_date_col)) if price_date_col else "NA",
                "source_stage": clean(source["stage"]),
                "source_run_id": clean(source["run_id"]),
                "source_file": rel(source["path"]),
                "source_role": clean(source["role"]),
                "ranking_timestamp_utc": created_at,
                "research_only": "TRUE",
                "official_recommendation_created": "FALSE",
                "official_weight_mutated": "FALSE",
                "trade_action_created": "FALSE",
                "certification_status": "CERTIFIED_AUTHORITATIVE_OFFICIAL_CURRENT_RESEARCH_RANKING",
                "certification_reason": ("PRICE_MISSING_ALLOWED. " if not price else "TICKER_RANK_SCORE_PRESENT_RESEARCH_ONLY_NO_TRADE. ") + dedupe_reason,
                "acceptance_proof_status": clean(source.get("acceptance_proof_status")),
                "acceptance_proof_file": clean(source.get("acceptance_proof_file")),
                "acceptance_proof_stage": clean(source.get("acceptance_proof_stage")),
                "acceptance_proof_reason": clean(source.get("acceptance_proof_reason")),
                "acceptance_summary_file": clean(source.get("acceptance_summary_file")),
                "acceptance_summary_status": clean(source.get("acceptance_summary_status")),
                "acceptance_package_manifest_file": clean(source.get("acceptance_package_manifest_file")),
                "acceptance_package_manifest_status": clean(source.get("acceptance_package_manifest_status")),
                "accepted_artifact_path": clean(source.get("accepted_artifact_path")),
                "accepted_artifact_validation_status": clean(source.get("accepted_artifact_validation_status")),
                "exact_artifact_proof_status": clean(source.get("exact_artifact_proof_status")),
                "exact_artifact_proof_reason": clean(source.get("exact_artifact_proof_reason")),
                "source_row_count": source_row_count,
                "unique_ticker_count": unique_ticker_count,
                "duplicate_ticker_count": duplicate_ticker_count,
                "deduplication_rule": deduplication_rule,
            }
        )
    output.sort(key=lambda item: float(clean(item["official_current_rank"]) or 999999))
    return output, missing_price


def write_aliases() -> list[Path]:
    aliases: list[Path] = []
    for path in OUTPUTS.values():
        alias = alias_path(path)
        alias.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, alias)
        aliases.append(alias)
    return aliases


def main() -> int:
    created_at = now_utc()
    run_id = make_run_id()
    source, audit_rows, status = discover_source()
    ranking_rows, missing_price = build_ranking_rows(source, created_at)
    acceptance_proof = acceptance_proof_for(source["path"], clean(source["run_id"])) if source else {
        "acceptance_proof_status": "NA",
        "acceptance_proof_file": "",
        "acceptance_proof_stage": "",
        "acceptance_proof_reason": "No source bound.",
        "acceptance_summary_file": "",
        "acceptance_summary_status": "NA",
        "acceptance_package_manifest_file": "",
        "acceptance_package_manifest_status": "NA",
        "accepted_artifact_path": "",
        "accepted_artifact_validation_status": "NA",
        "exact_artifact_proof_status": "NA",
        "exact_artifact_proof_reason": "No source bound.",
    }
    if source:
        acceptance_proof = {
            "acceptance_proof_status": clean(source.get("acceptance_proof_status")),
            "acceptance_proof_file": clean(source.get("acceptance_proof_file")),
            "acceptance_proof_stage": clean(source.get("acceptance_proof_stage")),
            "acceptance_proof_reason": clean(source.get("acceptance_proof_reason")),
            "acceptance_summary_file": clean(source.get("acceptance_summary_file")),
            "acceptance_summary_status": clean(source.get("acceptance_summary_status")),
            "acceptance_package_manifest_file": clean(source.get("acceptance_package_manifest_file")),
            "acceptance_package_manifest_status": clean(source.get("acceptance_package_manifest_status")),
            "accepted_artifact_path": clean(source.get("accepted_artifact_path")),
            "accepted_artifact_validation_status": clean(source.get("accepted_artifact_validation_status")),
            "exact_artifact_proof_status": clean(source.get("exact_artifact_proof_status")),
            "exact_artifact_proof_reason": clean(source.get("exact_artifact_proof_reason")),
        }
    source_row_count, unique_ticker_count, duplicate_ticker_count, deduplication_rule = source_counts(source)
    if status == PASS_STATUS and missing_price:
        status = PRICE_GAPS_STATUS
    if status == PASS_STATUS and not ranking_rows:
        status = NO_SOURCE_STATUS

    if not ranking_rows:
        write_csv(OUTPUTS["ranking"], [], RANKING_FIELDS)
    else:
        write_csv(OUTPUTS["ranking"], ranking_rows, RANKING_FIELDS)
    write_csv(OUTPUTS["audit"], audit_rows, AUDIT_FIELDS)

    bound_file = rel(source["path"]) if source else ""
    bound_role = clean(source["role"]) if source else ""
    rank_column_used = clean(source.get("rank_col")) if source else ""
    score_column_used = clean(source.get("score_col")) if source else ""
    price_column_used = clean(source.get("price_col")) if source else ""
    report = f"""# V20.83 Authoritative Official-Current Ranking Export

Stage: {STAGE}
Run ID: {run_id}
Created UTC: {created_at}
Status: {status}

Research-only authoritative official-current ticker-level ranking export.
Official-current means authoritative current research ranking source.
No official recommendation.
No buy/sell recommendation.
No official weight mutation.
No trade order.
No broker action.

## Binding

- Bound source file: {bound_file if bound_file else "NA"}
- Bound source role: {bound_role if bound_role else "NA"}
- Acceptance proof status: {acceptance_proof["acceptance_proof_status"]}
- Acceptance proof file: {acceptance_proof["acceptance_proof_file"] if acceptance_proof["acceptance_proof_file"] else "NA"}
- Acceptance proof stage: {acceptance_proof["acceptance_proof_stage"] if acceptance_proof["acceptance_proof_stage"] else "NA"}
- Acceptance proof reason: {acceptance_proof["acceptance_proof_reason"]}
- Acceptance summary file: {acceptance_proof["acceptance_summary_file"] if acceptance_proof["acceptance_summary_file"] else "NA"}
- Acceptance summary status: {acceptance_proof["acceptance_summary_status"]}
- Acceptance package manifest file: {acceptance_proof["acceptance_package_manifest_file"] if acceptance_proof["acceptance_package_manifest_file"] else "NA"}
- Acceptance package manifest status: {acceptance_proof["acceptance_package_manifest_status"]}
- Accepted artifact path: {acceptance_proof["accepted_artifact_path"] if acceptance_proof["accepted_artifact_path"] else "NA"}
- Accepted artifact validation status: {acceptance_proof["accepted_artifact_validation_status"]}
- Exact artifact proof status: {acceptance_proof["exact_artifact_proof_status"]}
- Exact artifact proof reason: {acceptance_proof["exact_artifact_proof_reason"]}
- Row count: {len(ranking_rows)}
- Latest price included: {"TRUE" if ranking_rows and not missing_price else "FALSE"}
- Source row count: {source_row_count}
- Unique ticker count: {unique_ticker_count}
- Duplicate ticker count: {duplicate_ticker_count}
- Deduplication rule: {deduplication_rule}
- Rank column used: {rank_column_used if rank_column_used else "NA"}
- Score column used: {score_column_used if score_column_used else "NA"}
- Price column used: {price_column_used if price_column_used else "NA"}

## Certification

{"No authoritative official-current ticker-level source with ticker, rank, and score was discovered." if not source else "Ticker, rank, and score were recovered from an approved current research/operator source."}
Rejected shadow, overlay-only, rank-change attribution, diagnostics, manifests, checks, summaries, readme, and report-only artifacts.
"""
    write_text(OUTPUTS["report"], report)

    output_files = [rel(path) for path in OUTPUTS.values()]
    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "bound_source_file": bound_file,
        "bound_source_role": bound_role,
        "row_count": len(ranking_rows),
        "output_files": output_files,
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "trade_action_created": False,
        "acceptance_proof_status": acceptance_proof["acceptance_proof_status"],
        "acceptance_proof_file": acceptance_proof["acceptance_proof_file"],
        "acceptance_proof_stage": acceptance_proof["acceptance_proof_stage"],
        "acceptance_summary_file": acceptance_proof["acceptance_summary_file"],
        "acceptance_summary_status": acceptance_proof["acceptance_summary_status"],
        "acceptance_package_manifest_file": acceptance_proof["acceptance_package_manifest_file"],
        "acceptance_package_manifest_status": acceptance_proof["acceptance_package_manifest_status"],
        "accepted_artifact_path": acceptance_proof["accepted_artifact_path"],
        "accepted_artifact_validation_status": acceptance_proof["accepted_artifact_validation_status"],
        "exact_artifact_proof_status": acceptance_proof["exact_artifact_proof_status"],
        "exact_artifact_proof_reason": acceptance_proof["exact_artifact_proof_reason"],
        "source_row_count": source_row_count,
        "unique_ticker_count": unique_ticker_count,
        "duplicate_ticker_count": duplicate_ticker_count,
        "deduplication_rule": deduplication_rule,
        "rank_column_used": rank_column_used,
        "score_column_used": score_column_used,
        "price_column_used": price_column_used,
    }
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    aliases = write_aliases()
    manifest["output_files"].extend(rel(path) for path in aliases)
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(OUTPUTS["manifest"], alias_path(OUTPUTS["manifest"]))

    print(status)
    return 0 if status in {PASS_STATUS, PRICE_GAPS_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
