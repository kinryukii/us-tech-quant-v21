from __future__ import annotations

import csv
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
SCAN_DIRS = [CONSOLIDATION, READ_CENTER, OPS]

STAGE = "V20.82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER"
PASS_STATUS = "PASS_V20_82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER"
OPTIONAL_GAPS_STATUS = "PASS_V20_82_MULTI_PATH_VALIDATION_WITH_OPTIONAL_INPUT_GAPS"
ETF_BLOCKED_STATUS = "PASS_V20_82_MULTI_PATH_VALIDATION_WITH_ETF_ROTATION_BLOCKED"
MISSING_REQUIRED_STATUS = "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT"
INSUFFICIENT_EVIDENCE_STATUS = "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE"
R5_PASS_STATUS = "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED"
R5_PARTIAL_STATUS = "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS"
PROXY_RETURN_STATUS = "PROXY_TECHNICAL_RETURN_NOT_CERTIFIED_STRATEGY_ALPHA"
INVALID_SCORE_SCALE_REASON = "INVALID_SCORE_SCALE_CURRENT_RANK_ORDER_VS_SHADOW_NORMALIZED"

INPUT_AUDIT_FIELDS = [
    "input_name",
    "required_flag",
    "binding_status",
    "source_path",
    "row_count",
    "required_fields_recovered",
    "optional_fields_recovered",
    "run_id",
    "explanation",
]
FACTOR_FIELDS = [
    "factor_name",
    "factor_type",
    "source_path",
    "coverage_ratio",
    "score",
    "evidence_count",
    "binding_status",
    "explanation",
]
STRATEGY_FIELDS = [
    "strategy_name",
    "strategy_type",
    "evaluation_window",
    "constituent_count",
    "return_source",
    "return_evidence_status",
    "model_return",
    "benchmark_return",
    "excess_return",
    "evidence_coverage_ratio",
    "allowed_shadow_delta",
    "validation_status",
    "v20_84_evidence_bound",
    "v20_84_integration_status",
    "v20_84_evidence_effect_on_v20_82_status",
    "explanation",
]
ETF_FIELDS = [
    "etf_symbol",
    "paired_symbol",
    "pair_group",
    "direction_type",
    "leverage_type",
    "current_regime",
    "relative_strength_score",
    "downside_behavior_score",
    "volatility_risk_score",
    "liquidity_confidence_score",
    "rotation_shadow_score",
    "entry_permission",
    "position_permission",
    "benchmark_role",
    "promotion_status",
    "explanation",
]
BENCHMARK_FIELDS = [
    "strategy_name",
    "strategy_type",
    "benchmark_name",
    "benchmark_type",
    "evaluation_window",
    "return_source",
    "return_evidence_status",
    "strategy_return",
    "benchmark_return",
    "excess_return",
    "strategy_volatility",
    "benchmark_volatility",
    "strategy_max_drawdown",
    "benchmark_max_drawdown",
    "downside_capture",
    "upside_capture",
    "hit_rate_vs_benchmark",
    "risk_adjusted_alpha",
    "turnover_penalty",
    "regime",
    "strategy_effectiveness_grade",
    "v20_84_evidence_bound",
    "v20_84_integration_status",
    "v20_84_evidence_effect_on_v20_82_status",
    "explanation",
]
NASDAQ_FIELDS = [
    "model_name",
    "evaluation_window",
    "return_source",
    "return_evidence_status",
    "qqq_return",
    "model_return",
    "excess_return_vs_qqq",
    "drawdown_vs_qqq",
    "downside_capture_vs_qqq",
    "upside_capture_vs_qqq",
    "hit_rate_vs_qqq",
    "passed_nasdaq_hurdle",
    "v20_84_evidence_bound",
    "v20_84_integration_status",
    "v20_84_evidence_effect_on_v20_82_status",
    "blocking_reason",
]
MODEL_COMPARE_FIELDS = [
    "ticker",
    "current_rank",
    "current_score",
    "current_score_scale",
    "shadow_adjusted_score",
    "shadow_score_scale",
    "score_comparison_valid",
    "shadow_adjusted_rank",
    "rank_delta",
    "main_positive_driver",
    "main_penalty_driver",
    "regime_effect",
    "benchmark_effect",
    "entry_permission",
    "position_permission",
    "v20_84_evidence_bound",
    "v20_84_integration_status",
    "v20_84_evidence_effect_on_v20_82_status",
    "explanation",
]
PROMOTION_FIELDS = [
    "component_name",
    "component_type",
    "shadow_score",
    "evidence_count",
    "required_evidence_count",
    "multi_path_coverage",
    "nasdaq_hurdle_passed",
    "etf_rotation_benchmark_passed",
    "promotion_allowed",
    "v20_84_evidence_bound",
    "v20_84_row_level_usable_evidence_count",
    "v20_84_fully_covered_component_count",
    "v20_84_partial_component_count",
    "v20_84_integration_status",
    "v20_84_evidence_effect_on_v20_82_status",
    "blocking_reason",
]
R5_DETAIL_FIELDS = [
    "validation_category",
    "required_level",
    "expected_path_id",
    "source_file",
    "source_status",
    "attached_row_count",
    "certified_row_count",
    "partial_row_count",
    "blocked_row_count",
    "validation_status",
    "category_blocker_reason",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]

OUTPUTS = {
    "input_audit": CONSOLIDATION / "V20_82_MULTI_PATH_INPUT_BINDING_AUDIT.csv",
    "factor": CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    "strategy": CONSOLIDATION / "V20_82_STRATEGY_MULTI_PATH_VALIDATION_TABLE.csv",
    "etf": CONSOLIDATION / "V20_82_ETF_ROTATION_SHADOW_SIGNAL_TABLE.csv",
    "benchmark": CONSOLIDATION / "V20_82_BENCHMARK_STRATEGY_COMPARISON.csv",
    "nasdaq": CONSOLIDATION / "V20_82_NASDAQ_EFFECTIVENESS_GATE.csv",
    "model_compare": CONSOLIDATION / "V20_82_CURRENT_VS_SHADOW_MODEL_COMPARISON.csv",
    "promotion": CONSOLIDATION / "V20_82_PROMOTION_GATE.csv",
    "report": READ_CENTER / "V20_82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_REPORT.md",
    "manifest": OPS / "V20_82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_MANIFEST.json",
}

R5_DETAIL = EVIDENCE / "V20_82_R5_MULTI_PATH_VALIDATION_DETAIL.csv"
R5_DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
V20_89_REQUIRED_EVIDENCE_MANIFEST = EVIDENCE / "V20_CURRENT_REQUIRED_EVIDENCE_PATH_MANIFEST.csv"
V20_90_ETF_ROTATION_EVIDENCE = EVIDENCE / "V20_CURRENT_ETF_ROTATION_EVIDENCE_TABLE.csv"
V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE = EVIDENCE / "V20_CURRENT_MULTI_WINDOW_STRATEGY_EVIDENCE_MATRIX.csv"
V20_86_REGIME_EVIDENCE = CONSOLIDATION / "V20_CURRENT_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv"
V20_87_DOWNSIDE_EVIDENCE = CONSOLIDATION / "V20_CURRENT_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv"
V20_88_BENCHMARK_EVIDENCE = CONSOLIDATION / "V20_CURRENT_CERTIFIED_BENCHMARK_COMPARISON_EVIDENCE_EXPORT.csv"
V20_93_ACCEPTANCE_PROOF_REPAIR = EVIDENCE / "V20_CURRENT_ACCEPTANCE_PROOF_EVIDENCE_REPAIR.csv"
V20_93_RANKING_DELTA_REPAIR = EVIDENCE / "V20_CURRENT_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_REPAIR.csv"

OPTIONAL_STAGE_TOKENS = ["V20_37", "V20_38", "V20_39", "V20_40", "V20_57", "V20_64", "V20_65", "V20_66", "V20_79A", "V20_80", "V20_81"]
CURRENT_RANK_CANDIDATES = [
    CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv",
    CONSOLIDATION / "V20_67_DAILY_OPERATION_CANDIDATE_PACKET.csv",
    CONSOLIDATION / "V20_68_READABLE_PRIORITY_REVIEW_TABLE.csv",
    CONSOLIDATION / "V20_68_READABLE_STANDARD_REVIEW_TABLE.csv",
]
V20_83_MANIFEST = OPS / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json"
V20_84_EVIDENCE_TABLE = CONSOLIDATION / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv"
V20_84_COVERAGE_TABLE = CONSOLIDATION / "V20_CURRENT_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv"
V20_84_INPUT_AUDIT = CONSOLIDATION / "V20_CURRENT_EVIDENCE_INPUT_BINDING_AUDIT.csv"
V20_84_MANIFEST = OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json"
TECHNICAL_CANDIDATES = [
    CONSOLIDATION / "V20_78_PRICE_SENSITIVE_TECHNICAL_FACTOR_TABLE.csv",
    CONSOLIDATION / "V20_79_BENCHMARK_TECHNICAL_TABLE.csv",
]
SHADOW_RANK_SOURCE = CONSOLIDATION / "V20_76_SHADOW_OPERATIONAL_RANK_TABLE.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return "V20_82_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_float(value: object) -> float | None:
    text = clean(value).replace(",", "")
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "TRUE", "FALSE"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value:.6f}"


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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
    except csv.Error:
        return [], [], "MALFORMED_CSV"
    if not fields:
        return [], [], "MALFORMED_CSV"
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


def source_run_id(rows: list[dict[str, str]]) -> str:
    for row in rows:
        for column in ["run_id", "stage_run_id", "source_run_id"]:
            value = clean(row.get(column))
            if value:
                return value
    return ""


def find_column(fields: list[str], names: list[str]) -> str:
    lower = {field.lower(): field for field in fields}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return ""


def ticker_value(row: dict[str, str]) -> str:
    return clean(row.get("ticker") or row.get("symbol") or row.get("normalized_ticker") or row.get("display_name_or_ticker")).upper()


def read_json(path: Path) -> tuple[dict[str, object], str]:
    if not path.exists() or path.stat().st_size == 0:
        return {}, "MISSING_FILE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, "UNUSABLE_SCHEMA"
    return (payload, "OK") if isinstance(payload, dict) else ({}, "UNUSABLE_SCHEMA")


def v20_83_manifest_valid() -> tuple[bool, str, dict[str, object]]:
    manifest, status = read_json(V20_83_MANIFEST)
    if status != "OK":
        return False, f"V20_83_MANIFEST_{status}", manifest
    checks = [
        manifest.get("status") == "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT",
        manifest.get("research_only") is True,
        manifest.get("official_recommendation_created") is False,
        manifest.get("official_weight_mutated") is False,
        manifest.get("trade_action_created") is False,
        manifest.get("bound_source_role") == "OPERATOR_ACCEPTED_CURRENT_RESEARCH",
    ]
    if manifest.get("exact_artifact_proof_status") != "FOUND":
        checks.append(False)
    if manifest.get("acceptance_package_manifest_status") != "PASS":
        checks.append(False)
    if not all(checks):
        return False, "V20_83_MANIFEST_INVARIANT_FAILURE", manifest
    return True, "V20_83_MANIFEST_VALID", manifest


def v20_84_manifest_valid() -> tuple[bool, str, dict[str, object]]:
    manifest, status = read_json(V20_84_MANIFEST)
    if status != "OK":
        return False, f"V20_84_MANIFEST_{status}", manifest
    required_fields = [
        "row_level_usable_evidence_count",
        "v20_82_fully_covered_component_count",
        "v20_82_partial_component_count",
        "v20_82_integration_status",
    ]
    checks = [
        manifest.get("status") in {
            "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS",
            "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
            "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS",
        },
        manifest.get("research_only") is True,
        manifest.get("official_recommendation_created") is False,
        manifest.get("official_weight_mutated") is False,
        manifest.get("trade_action_created") is False,
        all(field in manifest for field in required_fields),
    ]
    if not all(checks):
        return False, "V20_84_MANIFEST_INVARIANT_FAILURE", manifest
    return True, "V20_84_MANIFEST_VALID", manifest


def discover_v20_84_evidence() -> dict[str, object]:
    manifest_ok, manifest_reason, manifest = v20_84_manifest_valid()
    evidence_rows, evidence_fields, evidence_status = read_csv(V20_84_EVIDENCE_TABLE)
    coverage_rows, coverage_fields, coverage_status = read_csv(V20_84_COVERAGE_TABLE)
    audit_rows, audit_fields, audit_status = read_csv(V20_84_INPUT_AUDIT)
    required_evidence_fields = {"component_name", "component_type", "evidence_path", "source_file", "metric_name", "metric_value", "certification_status", "usable_for_v20_82"}
    required_coverage_fields = {"component_name", "component_type", "has_any_usable_evidence", "v20_82_usable", "evidence_coverage_ratio"}
    required_audit_fields = {"input_family", "candidate_file", "binding_quality", "usable_evidence_count"}
    files_ok = (
        evidence_status == "OK"
        and coverage_status == "OK"
        and audit_status == "OK"
        and required_evidence_fields.issubset(set(evidence_fields))
        and required_coverage_fields.issubset(set(coverage_fields))
        and required_audit_fields.issubset(set(audit_fields))
    )
    row_level = int(manifest.get("row_level_usable_evidence_count") or 0) if manifest_ok else 0
    fully_covered = int(manifest.get("v20_82_fully_covered_component_count") or 0) if manifest_ok else 0
    partial = int(manifest.get("v20_82_partial_component_count") or 0) if manifest_ok else 0
    integration_status = clean(manifest.get("v20_82_integration_status")) if manifest_ok else "UNBOUND"
    bound = manifest_ok and files_ok
    if not bound:
        reason = manifest_reason if not manifest_ok else "V20_84_EVIDENCE_FILES_UNUSABLE"
        quality = "V20_84_CERTIFIED_EVIDENCE_UNUSABLE"
    elif fully_covered == 0:
        reason = "PARTIAL_EVIDENCE_BOUND_BUT_REQUIRED_PATHS_INCOMPLETE"
        quality = "V20_84_PARTIAL_CERTIFIED_EVIDENCE_BOUND"
    else:
        reason = "FULL_COMPONENT_COVERAGE_BOUND"
        quality = "V20_84_FULL_CERTIFIED_EVIDENCE_BOUND"
    etf_usable_count = sum(1 for row in evidence_rows if row.get("component_type") == "ETF_ROTATION" and row.get("usable_for_v20_82") == "TRUE")
    return {
        "bound": bound,
        "manifest_ok": manifest_ok,
        "manifest_reason": manifest_reason,
        "files_ok": files_ok,
        "binding_status": "FOUND" if bound else "MISSING_REQUIRED",
        "binding_quality": quality,
        "effect": reason,
        "manifest": manifest,
        "evidence_rows": evidence_rows,
        "coverage_rows": coverage_rows,
        "audit_rows": audit_rows,
        "row_level_usable_evidence_count": row_level,
        "fully_covered_component_count": fully_covered,
        "partial_component_count": partial,
        "integration_status": integration_status,
        "etf_usable_count": etf_usable_count,
        "input_files": [rel(path) for path in [V20_84_EVIDENCE_TABLE, V20_84_COVERAGE_TABLE, V20_84_INPUT_AUDIT, V20_84_MANIFEST]],
    }


def normalize_v20_83_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append(
            {
                "ticker": clean(row.get("ticker")).upper(),
                "current_rank": clean(row.get("official_current_rank")),
                "current_score": clean(row.get("official_current_score")),
                "latest_price": clean(row.get("latest_price")),
                "score_name": clean(row.get("score_name")),
                "source_run_id": clean(row.get("source_run_id")),
                "source_stage": clean(row.get("source_stage")),
                "source_role": clean(row.get("source_role")),
            }
        )
    return normalized


def discover_current_rank() -> dict[str, object]:
    for path in CURRENT_RANK_CANDIDATES:
        rows, fields, status = read_csv(path)
        if status != "OK" or not rows:
            continue
        if path.name.upper() in {"V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.CSV", "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.CSV"}:
            manifest_ok, manifest_reason, manifest = v20_83_manifest_valid()
            required = {"ticker", "official_current_rank", "official_current_score"}
            row_role = clean(rows[0].get("source_role"))
            if not manifest_ok or not required.issubset(set(fields)) or row_role != "OPERATOR_ACCEPTED_CURRENT_RESEARCH":
                return {"path": None, "rows": [], "fields": [], "ticker_col": "", "rank_col": "", "score_col": "", "price_col": "", "status": "MISSING_REQUIRED", "source_role": "UNUSABLE", "explanation": manifest_reason}
            normalized_rows = normalize_v20_83_rows(rows)
            return {
                "path": path,
                "rows": normalized_rows,
                "fields": ["ticker", "current_rank", "current_score", "latest_price", "score_name", "source_run_id", "source_stage", "source_role"],
                "ticker_col": "ticker",
                "rank_col": "current_rank",
                "score_col": "current_score",
                "price_col": "latest_price",
                "source_role": "OPERATOR_ACCEPTED_CURRENT_RESEARCH",
                "status": "FOUND",
                "explanation": f"CURRENT_CANDIDATE_RANKING=FOUND; detected_file={path.name}; binding_quality=AUTHORITATIVE_V20_83_OFFICIAL_CURRENT; manifest_status={manifest.get('status')}; source_role=OPERATOR_ACCEPTED_CURRENT_RESEARCH.",
            }
        ticker_col = find_column(fields, ["ticker", "symbol", "normalized_ticker", "display_name_or_ticker"])
        rank_col = find_column(fields, ["current_rank", "current_primary_rank", "primary_rank", "report_rank", "rank"])
        score_col = find_column(fields, ["current_score", "current_primary_score", "primary_score", "final_score", "official_current_score"])
        price_col = find_column(fields, ["latest_price", "latest_refreshed_price", "latest_close"])
        if ticker_col and rank_col and score_col:
            role = source_role(path)
            if role not in {"OFFICIAL_CURRENT_CANDIDATE", "CURRENT_REPORT"}:
                continue
            return {"path": path, "rows": rows, "fields": fields, "ticker_col": ticker_col, "rank_col": rank_col, "score_col": score_col, "price_col": price_col, "source_role": role, "status": "FOUND"}
    return {"path": None, "rows": [], "fields": [], "ticker_col": "", "rank_col": "", "score_col": "", "price_col": "", "status": "MISSING_REQUIRED"}


def source_role(path: Path) -> str:
    name = path.name.upper()
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json"}:
        return "UNUSABLE"
    if "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE" in name or "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE" in name:
        return "OPERATOR_ACCEPTED_CURRENT_RESEARCH"
    if "V20_76_SHADOW" in name or "SHADOW_OPERATIONAL" in name:
        return "SHADOW_OPERATIONAL"
    if "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET" in name or "V20_67_DAILY_OPERATION_CANDIDATE_PACKET" in name:
        return "OFFICIAL_CURRENT_CANDIDATE"
    if "READABLE" in name or "REPORT_SUMMARY" in name:
        return "CURRENT_REPORT"
    if "V20_73" in name or "V20_74" in name or "OVERLAY" in name:
        return "OVERLAY_RESEARCH"
    return "OPTIONAL_EVIDENCE"


def current_score_is_rank_order(row: dict[str, str], rank_col: str, score_col: str) -> bool:
    score_name = clean(row.get("score_name")).lower()
    if score_name in {"source_rank_or_score", "rank", "rank_order", "ordinal_rank", "source_rank"}:
        return True
    rank = parse_float(row.get(rank_col))
    score = parse_float(row.get(score_col))
    if rank is not None and score is not None and abs(rank - score) < 0.000001:
        return True
    return bool(score is not None and score > 0 and score <= 100 and float(score).is_integer() and score_col.lower().endswith("rank"))


def certified_strategy_nasdaq_pass(row: dict[str, object], final_status: str, coverage_ratio: float, v20_84_full_count: int) -> bool:
    if final_status == INSUFFICIENT_EVIDENCE_STATUS or coverage_ratio < 0.5 or v20_84_full_count <= 0:
        return False
    if row.get("passed_nasdaq_hurdle") != "TRUE":
        return False
    status = clean(row.get("return_evidence_status"))
    if status in {
        PROXY_RETURN_STATUS,
        MISSING_REQUIRED_STATUS,
        INSUFFICIENT_EVIDENCE_STATUS,
        "INSUFFICIENT_COMPARABLE_SHADOW_RANKING_EVIDENCE",
        "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE",
    }:
        return False
    return status.startswith("CERTIFIED_STRATEGY_")


def index_by_ticker(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        ticker = ticker_value(row)
        if ticker and ticker not in indexed:
            indexed[ticker] = row
    return indexed


def discover_optional_inputs() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for token in OPTIONAL_STAGE_TOKENS:
        matches: list[Path] = []
        for directory in SCAN_DIRS:
            if directory.exists():
                matches.extend(path for path in directory.glob(f"{token}*") if path.is_file())
        latest = max(matches, key=lambda item: item.stat().st_mtime) if matches else None
        rows: list[dict[str, str]] = []
        fields: list[str] = []
        status = "MISSING_OPTIONAL"
        role = source_role(latest) if latest else "UNUSABLE"
        if latest and latest.suffix.lower() == ".csv":
            rows, fields, csv_status = read_csv(latest)
            status = "FOUND" if csv_status == "OK" and rows and fields and optional_schema_usable(latest, fields) else "UNUSABLE_SCHEMA"
        elif latest and latest.suffix.lower() == ".json":
            try:
                payload = json.loads(latest.read_text(encoding="utf-8"))
                status = "FOUND" if isinstance(payload, dict) and json_optional_usable(latest, payload) else "UNUSABLE_SCHEMA"
            except (OSError, json.JSONDecodeError):
                status = "UNUSABLE_SCHEMA"
        elif latest:
            status = "UNUSABLE_SCHEMA"
        result.append({"input_name": token, "path": latest, "rows": rows, "fields": fields, "source_role": role, "status": status})
    return result


def optional_schema_usable(path: Path, fields: list[str]) -> bool:
    name = path.name.lower()
    blocked_name_tokens = ["required_output_checks", "manifest", "hash_ledger", "summary", "status", "read_first", "next_step_decision", "gate_decision"]
    if any(token in name for token in blocked_name_tokens):
        return False
    lowered = {field.lower() for field in fields}
    evidence_tokens = [
        "strategy_return",
        "model_return",
        "benchmark_return",
        "excess_return",
        "hit_rate",
        "backtest",
        "alpha",
        "factor_effect",
        "observation",
        "evidence_count",
        "rolling_window",
    ]
    return any(any(token in field for token in evidence_tokens) for field in lowered)


def json_optional_usable(path: Path, payload: dict[str, object]) -> bool:
    name = path.name.lower()
    if "manifest" in name or "required_output_checks" in name or "summary" in name:
        return False
    text = json.dumps(payload, sort_keys=True).lower()
    return any(token in text for token in ["strategy_return", "model_return", "benchmark_return", "alpha", "backtest", "observation"])


def return_column(fields: list[str]) -> str:
    return find_column(fields, ["return_20d_pct", "return_10d_pct", "return_5d_pct", "return_1d_pct"])


def load_return_maps() -> tuple[dict[str, float], dict[str, dict[str, str]], str]:
    returns: dict[str, float] = {}
    technical_rows: dict[str, dict[str, str]] = {}
    evidence_path = ""
    for path in TECHNICAL_CANDIDATES:
        rows, fields, status = read_csv(path)
        if status != "OK":
            continue
        col = return_column(fields)
        if not col:
            continue
        if not evidence_path:
            evidence_path = rel(path)
        for row in rows:
            ticker = ticker_value(row)
            value = parse_float(row.get(col))
            if ticker and value is not None:
                returns[ticker] = value
                technical_rows[ticker] = row
    return returns, technical_rows, evidence_path


def benchmark_rows() -> dict[str, dict[str, str]]:
    path = CONSOLIDATION / "V20_79_BENCHMARK_TECHNICAL_TABLE.csv"
    rows, _, status = read_csv(path)
    if status != "OK":
        v20_91_rows, _, v20_91_status = read_csv(V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE)
        if v20_91_status != "OK":
            return {}
        fallback: dict[str, dict[str, str]] = {}
        for row in v20_91_rows:
            if clean(row.get("holding_window")) != "forward_20d":
                continue
            if not r5_structured_certified(row):
                continue
            ticker = clean(row.get("ticker")).upper()
            benchmark = clean(row.get("benchmark_ticker")).upper()
            if ticker and clean(row.get("forward_return")) not in {"", "NA"}:
                fallback[ticker] = {
                    "ticker": ticker,
                    "return_20d_pct": clean(row.get("forward_return")),
                    "volatility_20d_pct": clean(row.get("volatility")),
                    "drawdown_from_20d_high_pct": clean(row.get("max_drawdown")),
                }
            if benchmark and clean(row.get("benchmark_forward_return")) not in {"", "NA"} and benchmark not in fallback:
                fallback[benchmark] = {
                    "ticker": benchmark,
                    "return_20d_pct": clean(row.get("benchmark_forward_return")),
                    "volatility_20d_pct": "NA",
                    "drawdown_from_20d_high_pct": "NA",
                }
        return fallback
    return index_by_ticker(rows)


def benchmark_return(symbol: str, indexed: dict[str, dict[str, str]]) -> float | None:
    row = indexed.get(symbol)
    if not row:
        return None
    for column in ["return_20d_pct", "return_10d_pct", "return_5d_pct", "return_1d_pct"]:
        value = parse_float(row.get(column))
        if value is not None:
            return value
    return None


def volatility(symbol: str, indexed: dict[str, dict[str, str]]) -> float | None:
    row = indexed.get(symbol)
    if not row:
        return None
    return parse_float(row.get("volatility_20d_pct") or row.get("volatility_10d_pct"))


def drawdown(symbol: str, indexed: dict[str, dict[str, str]]) -> float | None:
    row = indexed.get(symbol)
    if not row:
        return None
    return parse_float(row.get("drawdown_from_20d_high_pct"))


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def top_model(rows: list[dict[str, str]], rank_col: str, score_col: str, returns: dict[str, float], top_n: int, shadow: bool = False) -> tuple[list[dict[str, str]], float | None, float]:
    usable = [row for row in rows if ticker_value(row)]
    if shadow:
        usable = sorted(usable, key=lambda row: (-(parse_float(row.get("blended_shadow_score")) or parse_float(row.get(score_col)) or 0), parse_float(row.get(rank_col)) or 999999))
    else:
        usable = sorted(usable, key=lambda row: parse_float(row.get(rank_col)) or 999999)
    selected = usable[:top_n]
    found = [returns[ticker_value(row)] for row in selected if ticker_value(row) in returns]
    coverage = len(found) / max(len(selected), 1)
    return selected, average(found), coverage


def discover_shadow_rank() -> dict[str, object]:
    rows, fields, status = read_csv(SHADOW_RANK_SOURCE)
    required = {"ticker", "shadow_operational_rank", "blended_shadow_score"}
    if status == "OK" and rows and required.issubset(set(fields)):
        return {"path": SHADOW_RANK_SOURCE, "rows": rows, "fields": fields, "rank_col": "shadow_operational_rank", "score_col": "blended_shadow_score", "status": "FOUND"}
    return {"path": SHADOW_RANK_SOURCE, "rows": [], "fields": fields, "rank_col": "", "score_col": "", "status": "UNUSABLE_SCHEMA"}


def top_shadow_model(shadow: dict[str, object], returns: dict[str, float], top_n: int) -> tuple[list[dict[str, str]], float | None, float, str, str]:
    if shadow.get("status") != "FOUND":
        return [], None, 0.0, "NA", "INSUFFICIENT_COMPARABLE_SHADOW_RANKING_EVIDENCE"
    rows = list(shadow.get("rows") or [])
    rank_col = clean(shadow.get("rank_col"))
    selected = sorted([row for row in rows if ticker_value(row)], key=lambda row: parse_float(row.get(rank_col)) or 999999)[:top_n]
    found = [returns[ticker_value(row)] for row in selected if ticker_value(row) in returns]
    coverage = len(found) / max(len(selected), 1)
    return selected, average(found), coverage, rel(shadow["path"]), PROXY_RETURN_STATUS


def grade(excess: float | None, coverage: float) -> str:
    if coverage < 0.5:
        return "INSUFFICIENT_EVIDENCE"
    if excess is None:
        return "NA"
    if excess > 2:
        return "A"
    if excess > 0:
        return "B"
    if excess > -2:
        return "C"
    return "D"


ETF_CERTIFICATION_FIELDS = {
    "certification_status",
    "rotation_backtest_certification_status",
    "etf_rotation_certification_status",
    "etf_rotation_backtest_certification_status",
}
ETF_POSITIVE_CERTIFICATIONS = {
    "CERTIFIED_ETF_ROTATION_EVIDENCE",
    "CERTIFIED_ROTATION_BACKTEST",
}
ETF_REJECT_TOKENS = {
    "INSUFFICIENT",
    "DESIGN_ONLY",
    "NOT_READY",
    "RESEARCH_ONLY_GUARDRAIL",
    "MISSING",
    "BLOCKED",
}


def etf_row_has_reject_status(row: dict[str, str]) -> bool:
    return any(token in clean(value).upper() for value in row.values() for token in ETF_REJECT_TOKENS)


def etf_row_has_named_positive_certification(row: dict[str, str]) -> bool:
    if etf_row_has_reject_status(row):
        return False
    return any(clean(row.get(field)).upper() in ETF_POSITIVE_CERTIFICATIONS for field in ETF_CERTIFICATION_FIELDS)


def build_etf_rotation(benchmark_index: dict[str, dict[str, str]], v20_84_bound: bool = False, v20_84_etf_usable_count: int = 0) -> tuple[list[dict[str, object]], float | None, bool, str]:
    rows, _, status = read_csv(CONSOLIDATION / "V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv")
    output: list[dict[str, object]] = []
    returns: list[float] = []
    if status == "OK" and rows:
        certified_values: list[float] = []
        for row in rows:
            bull = clean(row.get("bull_etf")).upper()
            bear = clean(row.get("bear_etf")).upper()
            score = parse_float(row.get("design_confidence_score"))
            regime = clean(row.get("market_regime") or row.get("broad_market_regime"))
            blocked = etf_row_has_reject_status(row)
            symbol_return = benchmark_return(bull, benchmark_index)
            if symbol_return is not None:
                returns.append(symbol_return)
            row_certified = False
            if v20_84_bound:
                row_certified = v20_84_etf_usable_count > 0 and etf_row_has_named_positive_certification(row)
            else:
                row_certified = etf_row_has_named_positive_certification(row)
            if not blocked and symbol_return is not None and row_certified:
                certified_values.append(symbol_return)
            role = "CANDIDATE_AND_BENCHMARK" if bull in {"TQQQ", "SOXL", "TECL", "SPXL"} else "BENCHMARK_ONLY"
            output.append(
                {
                    "etf_symbol": bull,
                    "paired_symbol": bear,
                    "pair_group": clean(row.get("etf_group")),
                    "direction_type": clean(row.get("design_only_directional_bias") or "SHADOW_ONLY"),
                    "leverage_type": "LEVERAGED" if any(token in bull for token in ["T", "SOXL", "SPXL"]) else "UNLEVERAGED",
                    "current_regime": regime,
                    "relative_strength_score": fmt(score),
                    "downside_behavior_score": "NA",
                    "volatility_risk_score": "NA",
                    "liquidity_confidence_score": "NA",
                    "rotation_shadow_score": fmt(score),
                    "entry_permission": "FALSE",
                    "position_permission": "FALSE",
                    "benchmark_role": role,
                    "promotion_status": "RESEARCH_ONLY_GUARDRAIL",
                    "explanation": "ETF rotation is shadow-only and benchmark-only; no trading activation. " + ("INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE" if blocked else "CERTIFIED_ROTATION_EVIDENCE_REQUIRED"),
                }
            )
        if certified_values:
            return output, average(certified_values), False, ""
        return output, None, False, "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE"
    output.append(
        {
            "etf_symbol": "ETF_ROTATION_SHADOW",
            "paired_symbol": "NA",
            "pair_group": "MISSING_OPTIONAL",
            "direction_type": "SHADOW_ONLY",
            "leverage_type": "NA",
            "current_regime": "NA",
            "relative_strength_score": "NA",
            "downside_behavior_score": "NA",
            "volatility_risk_score": "NA",
            "liquidity_confidence_score": "NA",
            "rotation_shadow_score": "NA",
            "entry_permission": "FALSE",
            "position_permission": "FALSE",
            "benchmark_role": "BENCHMARK_ONLY",
            "promotion_status": "BLOCKED_MISSING_OPTIONAL_INPUT",
            "explanation": "Optional ETF rotation source missing; benchmark row retained as unavailable shadow benchmark.",
        }
    )
    return output, None, True, "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE"


R5_CATEGORIES = [
    {
        "validation_category": "etf_rotation_evidence",
        "path_id": "certified_etf_rotation_evidence",
        "required_level": "REQUIRED",
        "source": V20_90_ETF_ROTATION_EVIDENCE,
    },
    {
        "validation_category": "multi_window_strategy_evidence",
        "path_id": "multi_window_strategy_evidence",
        "required_level": "REQUIRED",
        "source": V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE,
    },
    {
        "validation_category": "regime_conditioned_evidence",
        "path_id": "regime_conditioned_evidence",
        "required_level": "REQUIRED",
        "source": V20_86_REGIME_EVIDENCE,
    },
    {
        "validation_category": "downside_risk_evidence",
        "path_id": "downside_risk_evidence",
        "required_level": "REQUIRED",
        "source": V20_87_DOWNSIDE_EVIDENCE,
    },
    {
        "validation_category": "benchmark_comparison_evidence",
        "path_id": "benchmark_comparison_evidence",
        "required_level": "REQUIRED",
        "source": V20_88_BENCHMARK_EVIDENCE,
    },
    {
        "validation_category": "score_lineage_evidence",
        "path_id": "score_lineage_evidence",
        "required_level": "REQUIRED",
        "source": CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
    },
    {
        "validation_category": "ranking_delta_diagnostic_evidence",
        "path_id": "ranking_delta_diagnostic_evidence",
        "required_level": "OPTIONAL",
        "source": V20_93_RANKING_DELTA_REPAIR,
    },
    {
        "validation_category": "acceptance_proof_evidence",
        "path_id": "acceptance_proof_evidence",
        "required_level": "REQUIRED",
        "source": V20_93_ACCEPTANCE_PROOF_REPAIR,
    },
]

R5_CERTIFICATION_FIELDS = {
    "certification_status",
    "benchmark_comparison_certification_status",
    "downside_risk_certification_status",
    "regime_conditioned_certification_status",
    "etf_rotation_certification_status",
    "multi_window_strategy_certification_status",
}
R5_REJECT_TOKENS = {
    "BLOCKED",
    "DESIGN_ONLY",
    "INSUFFICIENT",
    "MISSING",
    "NOT_CERTIFIED",
    "NOT_READY",
    "PARTIAL",
    "RESEARCH_ONLY_GUARDRAIL",
    "UNCERTIFIED",
}


def manifest_by_path_id() -> dict[str, dict[str, str]]:
    rows, _, status = read_csv(V20_89_REQUIRED_EVIDENCE_MANIFEST)
    if status != "OK":
        return {}
    return {clean(row.get("path_id")): row for row in rows if clean(row.get("path_id"))}


def r5_structured_certified(row: dict[str, str]) -> bool:
    for field, value in row.items():
        lower = field.lower()
        text = clean(value).upper()
        if lower not in R5_CERTIFICATION_FIELDS and not lower.endswith("_certification_status"):
            continue
        if "reason" in lower or "note" in lower:
            continue
        if not text or any(token in text for token in R5_REJECT_TOKENS):
            continue
        if text == "CERTIFIED" or text.startswith("CERTIFIED_") or text == "TRUE":
            return True
    return False


def r5_partial(row: dict[str, str]) -> bool:
    return any(clean(value).upper() == "PARTIAL_COVERAGE" or "PARTIAL" in clean(value).upper() for key, value in row.items() if "status" in key.lower())


def r5_blocked(row: dict[str, str]) -> bool:
    return any("BLOCKED" in clean(value).upper() for key, value in row.items() if "status" in key.lower() or "reason" in key.lower())


def build_r5_detail_rows() -> tuple[list[dict[str, object]], str]:
    manifest_index = manifest_by_path_id()
    detail_rows: list[dict[str, object]] = []
    for category in R5_CATEGORIES:
        category_name = clean(category["validation_category"])
        path_id = clean(category["path_id"])
        required_level = clean(category["required_level"])
        source = category["source"]
        manifest_row = manifest_index.get(path_id, {})
        rows, fields, source_status = read_csv(source)
        attached = len(rows) if source_status == "OK" else 0
        certified = sum(1 for row in rows if r5_structured_certified(row)) if source_status == "OK" else 0
        partial = sum(1 for row in rows if r5_partial(row) and not r5_structured_certified(row)) if source_status == "OK" else 0
        blocked = sum(1 for row in rows if r5_blocked(row)) if source_status == "OK" else 0
        validation_status = "PASSED"
        blocker = "NA"
        if source_status != "OK":
            validation_status = "BLOCKED" if required_level == "REQUIRED" else "WARN"
            blocker = f"{category_name.upper()}_MISSING_REQUIRED_PATH:{source_status}"
        elif attached == 0:
            validation_status = "BLOCKED" if required_level == "REQUIRED" else "WARN"
            blocker = f"{category_name.upper()}_NO_ATTACHED_ROWS"
        elif certified > 0:
            validation_status = "PASSED"
        elif partial > 0:
            validation_status = "BLOCKED" if required_level == "REQUIRED" else "WARN"
            blocker = f"{category_name.upper()}_PARTIAL_ATTACHED_NOT_CERTIFIED"
        else:
            validation_status = "BLOCKED" if required_level == "REQUIRED" else "WARN"
            blocker = f"{category_name.upper()}_STRUCTURED_CERTIFICATION_MISSING"
        if clean(manifest_row.get("current_status")) == "BLOCKED" and required_level == "REQUIRED" and certified == 0:
            validation_status = "BLOCKED"
            reason = clean(manifest_row.get("missing_reason")) or "MANIFEST_BLOCKED_REQUIRED_PATH"
            blocker = f"{category_name.upper()}_{reason}"
        if clean(manifest_row.get("current_status")) == "WARN" and validation_status != "PASSED":
            validation_status = "WARN"
            reason = clean(manifest_row.get("missing_reason")) or blocker
            blocker = f"{category_name.upper()}_{reason}"
        detail_rows.append(
            {
                "validation_category": category_name,
                "required_level": required_level,
                "expected_path_id": path_id,
                "source_file": rel(source),
                "source_status": source_status,
                "attached_row_count": attached,
                "certified_row_count": certified,
                "partial_row_count": partial,
                "blocked_row_count": blocked,
                "validation_status": validation_status,
                "category_blocker_reason": blocker,
                "research_only": "TRUE",
                "official_recommendation_created": "FALSE",
                "official_weight_mutated": "FALSE",
                "trade_action_created": "FALSE",
            }
        )
    has_required_blocker = any(row["required_level"] == "REQUIRED" and row["validation_status"] == "BLOCKED" for row in detail_rows)
    return detail_rows, R5_PARTIAL_STATUS if has_required_blocker else R5_PASS_STATUS


def r5_count(detail_rows: list[dict[str, object]], category: str, field: str = "certified_row_count") -> int:
    for row in detail_rows:
        if row.get("validation_category") == category:
            try:
                return int(row.get(field) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def comparison_row(strategy: str, strategy_type: str, benchmark: str, benchmark_type: str, strategy_return: float | None, bench_return: float | None, strategy_vol: float | None, bench_vol: float | None, regime: str, coverage: float, return_source: str, return_evidence_status: str, v20_84_bound: bool, v20_84_status: str, v20_84_effect: str) -> dict[str, object]:
    excess = None if strategy_return is None or bench_return is None else strategy_return - bench_return
    downside = None if strategy_return is None or bench_return in (None, 0) else min(strategy_return, 0) / min(bench_return, -0.000001)
    upside = None if strategy_return is None or bench_return in (None, 0) else max(strategy_return, 0) / max(bench_return, 0.000001)
    hit = None if excess is None else (1.0 if excess > 0 else 0.0)
    risk_alpha = None if excess is None or strategy_vol in (None, 0) else excess / max(strategy_vol, 0.000001)
    explanation = "Research-only benchmark comparison; no official recommendation, weight mutation, or trade action."
    if return_evidence_status == MISSING_REQUIRED_STATUS:
        explanation = "Official current ranking is missing; strategy effectiveness comparison is blocked. " + explanation
    return {
        "strategy_name": strategy,
        "strategy_type": strategy_type,
        "benchmark_name": benchmark,
        "benchmark_type": benchmark_type,
        "evaluation_window": "LATEST_AVAILABLE_RETURN_WINDOW",
        "return_source": return_source,
        "return_evidence_status": return_evidence_status,
        "strategy_return": fmt(strategy_return),
        "benchmark_return": fmt(bench_return),
        "excess_return": fmt(excess),
        "strategy_volatility": fmt(strategy_vol),
        "benchmark_volatility": fmt(bench_vol),
        "strategy_max_drawdown": "NA",
        "benchmark_max_drawdown": "NA",
        "downside_capture": fmt(downside),
        "upside_capture": fmt(upside),
        "hit_rate_vs_benchmark": fmt(hit),
        "risk_adjusted_alpha": fmt(risk_alpha),
        "turnover_penalty": "0.000000",
        "regime": regime or "NA",
        "strategy_effectiveness_grade": grade(excess, coverage),
        "v20_84_evidence_bound": tf(v20_84_bound),
        "v20_84_integration_status": v20_84_status,
        "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
        "explanation": explanation,
    }


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_82_", "V20_CURRENT_", 1))


def write_aliases() -> list[Path]:
    aliases: list[Path] = []
    for path in OUTPUTS.values():
        alias = alias_path(path)
        alias.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, alias)
        aliases.append(alias)
    return aliases


def main() -> int:
    run_id = make_run_id()
    created_at = now_utc()
    current = discover_current_rank()
    shadow = discover_shadow_rank()
    optional_inputs = discover_optional_inputs()
    v20_84 = discover_v20_84_evidence()
    v20_84_bound = bool(v20_84["bound"])
    v20_84_row_level = int(v20_84["row_level_usable_evidence_count"])
    v20_84_full_count = int(v20_84["fully_covered_component_count"])
    v20_84_partial_count = int(v20_84["partial_component_count"])
    v20_84_status = clean(v20_84["integration_status"])
    v20_84_effect = clean(v20_84["effect"])
    r5_detail_rows, r5_status = build_r5_detail_rows()
    r5_category_blockers = [
        clean(row["category_blocker_reason"])
        for row in r5_detail_rows
        if row["validation_status"] == "BLOCKED" and clean(row["category_blocker_reason"]) != "NA"
    ]
    r5_warn_reasons = [
        clean(row["category_blocker_reason"])
        for row in r5_detail_rows
        if row["validation_status"] == "WARN" and clean(row["category_blocker_reason"]) != "NA"
    ]
    readable_regime_evidence_count = r5_count(r5_detail_rows, "regime_conditioned_evidence")
    readable_downside_risk_evidence_count = r5_count(r5_detail_rows, "downside_risk_evidence")
    readable_benchmark_comparison_evidence_count = r5_count(r5_detail_rows, "benchmark_comparison_evidence")
    readable_acceptance_proof_evidence_count = r5_count(r5_detail_rows, "acceptance_proof_evidence")
    readable_ranking_delta_diagnostic_evidence_count = r5_count(r5_detail_rows, "ranking_delta_diagnostic_evidence", "attached_row_count")
    missing_required_evidence_categories = [
        clean(row["validation_category"])
        for row in r5_detail_rows
        if row["required_level"] == "REQUIRED" and row["validation_status"] == "BLOCKED"
    ]
    input_files: list[str] = []
    current_found = current["status"] == "FOUND"
    current_path = current["path"] if current_found else None
    current_rows = list(current["rows"])
    rank_col = clean(current["rank_col"])
    score_col = clean(current["score_col"])
    if current_path:
        input_files.append(rel(current_path))
        if source_role(current_path) == "OPERATOR_ACCEPTED_CURRENT_RESEARCH":
            input_files.append(rel(V20_83_MANIFEST))
    if shadow.get("status") == "FOUND":
        input_files.append(rel(shadow["path"]))
    input_files.extend(list(v20_84["input_files"]))
    input_files.extend(
        [
            rel(V20_89_REQUIRED_EVIDENCE_MANIFEST),
            rel(V20_90_ETF_ROTATION_EVIDENCE),
            rel(V20_91_MULTI_WINDOW_STRATEGY_EVIDENCE),
        ]
    )
    for row in r5_detail_rows:
        source_file = clean(row.get("source_file"))
        if source_file and source_file != "NA":
            input_files.append(source_file)

    returns, technical_rows, technical_source = load_return_maps()
    if technical_source:
        input_files.append(technical_source)
    bench_index = benchmark_rows()
    qqq_ret = benchmark_return("QQQ", bench_index)
    if not current_found:
        status = MISSING_REQUIRED_STATUS
    elif qqq_ret is None:
        status = MISSING_REQUIRED_STATUS
    else:
        status = PASS_STATUS

    etf_rows, etf_return, etf_attachment_blocked, etf_reason = build_etf_rotation(bench_index, v20_84_bound, int(v20_84["etf_usable_count"]))
    if etf_rows:
        input_files.append(rel(CONSOLIDATION / "V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv"))

    optional_gap = any(item["status"] in {"MISSING_OPTIONAL", "UNUSABLE_SCHEMA", "STALE"} for item in optional_inputs) or etf_return is None
    if status == PASS_STATUS and etf_attachment_blocked:
        status = ETF_BLOCKED_STATUS
    if status == PASS_STATUS and optional_gap:
        status = OPTIONAL_GAPS_STATUS
    if v20_84_bound and v20_84_full_count == 0 and status not in {MISSING_REQUIRED_STATUS}:
        status = INSUFFICIENT_EVIDENCE_STATUS
    if not v20_84_bound and status not in {MISSING_REQUIRED_STATUS}:
        status = INSUFFICIENT_EVIDENCE_STATUS
    status = r5_status

    audit_rows = [
        {
            "input_name": "CURRENT_CANDIDATE_RANKING",
            "required_flag": "TRUE",
            "binding_status": "FOUND" if current_found else "MISSING_REQUIRED",
            "source_path": rel(current_path) if current_path else "",
            "row_count": len(current_rows),
            "required_fields_recovered": tf(current_found),
            "optional_fields_recovered": tf(bool(current.get("price_col"))),
            "run_id": source_run_id(current_rows),
            "explanation": clean(current.get("explanation")) if current_found and current.get("explanation") else (f"Bound source_role={current.get('source_role')}; ticker={current['ticker_col']}, rank={rank_col}, score={score_col}." if current_found else clean(current.get("explanation")) or "No approved official-current ticker-level ranking/candidate source with ticker, rank, and score was discovered."),
        },
        {
            "input_name": "SHADOW_MULTI_PATH_RANKING",
            "required_flag": "FALSE",
            "binding_status": clean(shadow.get("status")),
            "source_path": rel(shadow["path"]),
            "row_count": len(shadow.get("rows") or []),
            "required_fields_recovered": tf(shadow.get("status") == "FOUND"),
            "optional_fields_recovered": tf(shadow.get("status") == "FOUND"),
            "run_id": source_run_id(list(shadow.get("rows") or [])),
            "explanation": "Explicit shadow operational ranking source; never used as official current ranking.",
        },
        {
            "input_name": "QQQ_NASDAQ_BENCHMARK",
            "required_flag": "TRUE",
            "binding_status": "FOUND" if qqq_ret is not None else "MISSING_REQUIRED",
            "source_path": rel(CONSOLIDATION / "V20_79_BENCHMARK_TECHNICAL_TABLE.csv"),
            "row_count": len(bench_index),
            "required_fields_recovered": tf(qqq_ret is not None),
            "optional_fields_recovered": "TRUE",
            "run_id": source_run_id(list(bench_index.values())),
            "explanation": "QQQ is mandatory benchmark.",
        },
        {
            "input_name": "CERTIFIED_MULTI_PATH_EVIDENCE",
            "required_flag": "TRUE",
            "binding_status": clean(v20_84["binding_status"]),
            "source_path": rel(V20_84_EVIDENCE_TABLE),
            "row_count": len(v20_84["evidence_rows"]),
            "required_fields_recovered": tf(v20_84_bound),
            "optional_fields_recovered": tf(v20_84_bound),
            "run_id": clean(v20_84["manifest"].get("run_id")) if isinstance(v20_84["manifest"], dict) else "",
            "explanation": f"binding_quality={v20_84['binding_quality']}; row_level_usable_evidence_count={v20_84_row_level}; fully_covered_component_count={v20_84_full_count}; partial_component_count={v20_84_partial_count}; integration_status={v20_84_status}; effect={v20_84_effect}.",
        },
    ]
    for item in optional_inputs:
        audit_rows.append(
            {
                "input_name": item["input_name"],
                "required_flag": "FALSE",
                "binding_status": item["status"],
                "source_path": rel(item["path"]) if item["path"] else "",
                "row_count": len(item["rows"]),
                "required_fields_recovered": "NA",
                "optional_fields_recovered": tf(item["status"] == "FOUND"),
                "run_id": source_run_id(item["rows"]),
                "explanation": "Optional multi-path input; missing optional inputs do not block.",
            }
        )
        if item["path"]:
            input_files.append(rel(item["path"]))

    factor_rows: list[dict[str, object]] = []
    evidence_sources = [item for item in optional_inputs if item["status"] == "FOUND"]
    coverage_ratio = len(evidence_sources) / len(optional_inputs)
    for name, score, factor_type in [
        ("current_official_rank_signal", 100.0 if current_found else None, "CURRENT_MODEL"),
        ("shadow_multi_path_signal", 100.0 * coverage_ratio if evidence_sources else None, "SHADOW_MODEL"),
        ("qqq_nasdaq_benchmark_signal", 100.0 if qqq_ret is not None else None, "MANDATORY_BENCHMARK"),
        ("etf_rotation_shadow_signal", None if etf_return is None else 100.0, "SHADOW_BENCHMARK"),
    ]:
        factor_rows.append(
            {
                "factor_name": name,
                "factor_type": factor_type,
                "source_path": rel(current_path) if "current" in name and current_path else "",
                "coverage_ratio": fmt(coverage_ratio if "shadow" in name else 1.0),
                "score": fmt(score),
                "evidence_count": len(evidence_sources) if "shadow" in name else (1 if score is not None else 0),
                "binding_status": "FOUND" if score is not None else "MISSING_OPTIONAL",
                "explanation": "0-100 research score when evidence exists; NA when evidence is missing.",
            }
        )

    models: list[tuple[str, list[dict[str, str]], float | None, float, str, str]] = []
    for model_name, top_n in [
        ("CURRENT_OFFICIAL_RANKING_TOP10", 10),
        ("CURRENT_OFFICIAL_RANKING_TOP20", 20),
    ]:
        if current_found:
            selected, model_ret, cov = top_model(current_rows, rank_col, score_col, returns, top_n, shadow=False)
            models.append((model_name, selected, model_ret, cov, technical_source or "NA", PROXY_RETURN_STATUS))
        else:
            models.append((model_name, [], None, 0.0, "NA", "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT"))
    for model_name, top_n in [
        ("SHADOW_MULTI_PATH_ADJUSTED_TOP10", 10),
        ("SHADOW_MULTI_PATH_ADJUSTED_TOP20", 20),
    ]:
        selected, model_ret, cov, return_source, evidence_status = top_shadow_model(shadow, returns, top_n)
        models.append((model_name, selected, model_ret, cov, return_source, evidence_status))
    models.append(("ETF_ROTATION_SHADOW", [], etf_return, 1.0 if etf_return is not None else 0.0, "NA", "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE" if etf_return is None else "CERTIFIED_ETF_ROTATION_EVIDENCE"))

    strategy_rows: list[dict[str, object]] = []
    nasdaq_rows: list[dict[str, object]] = []
    benchmark_compare: list[dict[str, object]] = []
    benchmarks = [
        ("QQQ_BUY_AND_HOLD", "MANDATORY_NASDAQ", qqq_ret, volatility("QQQ", bench_index), drawdown("QQQ", bench_index)),
        ("SPY_BUY_AND_HOLD", "OPTIONAL_MARKET", benchmark_return("SPY", bench_index), volatility("SPY", bench_index), drawdown("SPY", bench_index)),
        ("SOXX_BUY_AND_HOLD", "OPTIONAL_SEMICONDUCTOR", benchmark_return("SOXX", bench_index), volatility("SOXX", bench_index), drawdown("SOXX", bench_index)),
        ("ETF_ROTATION_BASELINE", "SHADOW_BENCHMARK", etf_return, None, None),
        ("CASH_PROXY", "OPTIONAL_CASH", 0.0, 0.0, 0.0),
    ]
    regime = clean((bench_index.get("QQQ") or {}).get("benchmark_trend_status"))
    hard_current_block = status == MISSING_REQUIRED_STATUS
    for model_name, selected, model_ret, cov, return_source, return_evidence_status in models:
        effective_model_ret = None if hard_current_block and model_name.startswith(("CURRENT_OFFICIAL_RANKING", "SHADOW_MULTI_PATH_ADJUSTED")) else model_ret
        effective_cov = 0.0 if hard_current_block and model_name.startswith(("CURRENT_OFFICIAL_RANKING", "SHADOW_MULTI_PATH_ADJUSTED")) else cov
        effective_return_status = MISSING_REQUIRED_STATUS if hard_current_block and model_name.startswith(("CURRENT_OFFICIAL_RANKING", "SHADOW_MULTI_PATH_ADJUSTED")) else return_evidence_status
        effective_return_source = "NA" if hard_current_block and model_name.startswith("CURRENT_OFFICIAL_RANKING") else return_source
        excess = None if effective_model_ret is None or qqq_ret is None else effective_model_ret - qqq_ret
        blocked = effective_cov < 0.5
        strategy_rows.append(
            {
                "strategy_name": model_name,
                "strategy_type": "SHADOW_BENCHMARK" if model_name == "ETF_ROTATION_SHADOW" else "RANKING_MODEL",
                "evaluation_window": "LATEST_AVAILABLE_RETURN_WINDOW",
                "constituent_count": len(etf_rows) if model_name == "ETF_ROTATION_SHADOW" else len(selected),
                "return_source": effective_return_source,
                "return_evidence_status": effective_return_status,
                "model_return": fmt(effective_model_ret),
                "benchmark_return": fmt(qqq_ret),
                "excess_return": fmt(excess),
                "evidence_coverage_ratio": fmt(effective_cov),
                "allowed_shadow_delta": "0.000000" if blocked else fmt(excess),
                "validation_status": "BLOCKED_INSUFFICIENT_EVIDENCE" if blocked else "VALIDATED_SHADOW_ONLY",
                "v20_84_evidence_bound": tf(v20_84_bound),
                "v20_84_integration_status": v20_84_status,
                "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
                "explanation": ("Official current ranking is missing; strategy effectiveness comparison is blocked. " if effective_return_status == MISSING_REQUIRED_STATUS else "") + ("INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE. " if model_name == "ETF_ROTATION_SHADOW" and effective_model_ret is None else "") + ("INSUFFICIENT_COMPARABLE_SHADOW_RANKING_EVIDENCE. " if "SHADOW_MULTI_PATH" in model_name and effective_model_ret is None and effective_return_status != MISSING_REQUIRED_STATUS else "") + "No official mutation; proxy returns are not certified strategy alpha unless explicitly marked otherwise.",
            }
        )
        model_dd_values = [] if hard_current_block and model_name.startswith(("CURRENT_OFFICIAL_RANKING", "SHADOW_MULTI_PATH_ADJUSTED")) else [parse_float(technical_rows.get(ticker_value(row), {}).get("drawdown_from_20d_high_pct")) for row in selected]
        model_dd = average([value for value in model_dd_values if value is not None])
        qqq_dd = drawdown("QQQ", bench_index)
        dd_vs_qqq = None if model_dd is None or qqq_dd is None else model_dd - qqq_dd
        base_reason = []
        if not (excess is not None and excess > 0 and effective_cov >= 0.5):
            base_reason.append("NASDAQ_HURDLE_NOT_PASSED_OR_INSUFFICIENT_EVIDENCE")
        if effective_return_status in {"BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT", "INSUFFICIENT_COMPARABLE_SHADOW_RANKING_EVIDENCE"}:
            base_reason.append(effective_return_status)
        if effective_return_status == PROXY_RETURN_STATUS:
            base_reason.append(PROXY_RETURN_STATUS)
        if dd_vs_qqq is None:
            base_reason.append("INSUFFICIENT_DRAWDOWN_EVIDENCE")
        if model_name == "ETF_ROTATION_SHADOW" and model_ret is None:
            base_reason.append(etf_reason or "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE")
        if v20_84_bound and v20_84_full_count == 0:
            base_reason.append("V20_84_PARTIAL_BLOCK_MISSING_REQUIRED_PATHS")
        nasdaq_rows.append(
            {
                "model_name": model_name,
                "evaluation_window": "LATEST_AVAILABLE_RETURN_WINDOW",
                "return_source": effective_return_source,
                "return_evidence_status": effective_return_status,
                "qqq_return": fmt(qqq_ret),
                "model_return": fmt(effective_model_ret),
                "excess_return_vs_qqq": fmt(excess),
                "drawdown_vs_qqq": fmt(dd_vs_qqq),
                "downside_capture_vs_qqq": fmt(None if effective_model_ret is None or qqq_ret in (None, 0) else min(effective_model_ret, 0) / min(qqq_ret, -0.000001)),
                "upside_capture_vs_qqq": fmt(None if effective_model_ret is None or qqq_ret in (None, 0) else max(effective_model_ret, 0) / max(qqq_ret, 0.000001)),
                "hit_rate_vs_qqq": fmt(None if excess is None else (1.0 if excess > 0 else 0.0)),
                "passed_nasdaq_hurdle": tf(bool(excess is not None and excess > 0 and effective_cov >= 0.5 and not hard_current_block and effective_return_status != PROXY_RETURN_STATUS and v20_84_full_count > 0)),
                "v20_84_evidence_bound": tf(v20_84_bound),
                "v20_84_integration_status": v20_84_status,
                "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
                "blocking_reason": ";".join(base_reason),
            }
        )
        model_vols = [] if hard_current_block and model_name.startswith(("CURRENT_OFFICIAL_RANKING", "SHADOW_MULTI_PATH_ADJUSTED")) else [parse_float(technical_rows.get(ticker_value(row), {}).get("volatility_20d_pct")) for row in selected]
        model_vol = average([value for value in model_vols if value is not None])
        for benchmark_name, benchmark_type, bench_ret, bench_vol, _bench_dd in benchmarks:
            benchmark_compare.append(comparison_row(model_name, "RANKING_MODEL_OR_SHADOW", benchmark_name, benchmark_type, effective_model_ret, bench_ret, model_vol, bench_vol, regime, effective_cov, effective_return_source, effective_return_status, v20_84_bound, v20_84_status, v20_84_effect))

    current_index = index_by_ticker(current_rows)
    shadow_rows, _, shadow_status = read_csv(CONSOLIDATION / "V20_76_SHADOW_OPERATIONAL_RANK_TABLE.csv")
    shadow_index = index_by_ticker(shadow_rows) if shadow_status == "OK" else {}
    compare_rows: list[dict[str, object]] = []
    comparison_tickers = sorted(set(current_index) | set(shadow_index))
    for ticker in comparison_tickers:
        row = current_index.get(ticker, {})
        shadow = shadow_index.get(ticker, {})
        current_rank = parse_float(row.get(rank_col))
        current_score = parse_float(row.get(score_col))
        raw_shadow_score = parse_float(shadow.get("blended_shadow_score"))
        raw_shadow_rank = parse_float(shadow.get("shadow_operational_rank"))
        rank_order_current_score = current_found and current_score_is_rank_order(row, rank_col, score_col)
        current_scale = "RANK_ORDER_SCORE" if rank_order_current_score else ("0_100" if current_score is not None and current_found else "NA")
        shadow_scale = "0_1" if raw_shadow_score is not None and raw_shadow_score <= 1 else ("0_100" if raw_shadow_score is not None else "NA")
        shadow_score = raw_shadow_score * 100 if raw_shadow_score is not None and raw_shadow_score <= 1 else raw_shadow_score
        score_valid = current_score is not None and shadow_score is not None and current_scale == "0_100"
        shadow_rank = raw_shadow_rank
        rank_delta = None if current_rank is None or shadow_rank is None else current_rank - shadow_rank
        insufficient = not score_valid or shadow_rank is None or not current_found
        compare_rows.append(
            {
                "ticker": ticker,
                "current_rank": fmt(current_rank),
                "current_score": fmt(current_score),
                "current_score_scale": current_scale,
                "shadow_adjusted_score": fmt(shadow_score),
                "shadow_score_scale": "0_100_NORMALIZED_FROM_0_1" if raw_shadow_score is not None and raw_shadow_score <= 1 else shadow_scale,
                "score_comparison_valid": tf(score_valid),
                "shadow_adjusted_rank": fmt(shadow_rank),
                "rank_delta": fmt(rank_delta),
                "main_positive_driver": clean(shadow.get("displacement_reason") or ("CURRENT_RANK_SIGNAL" if current_found else "NA")),
                "main_penalty_driver": "BENCHMARK_HURDLE_UNPROVEN",
                "regime_effect": regime or "NA",
                "benchmark_effect": "QQQ_MANDATORY_HURDLE",
                "entry_permission": "FALSE",
                "position_permission": "FALSE",
                "v20_84_evidence_bound": tf(v20_84_bound),
                "v20_84_integration_status": v20_84_status,
                "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
                "explanation": ("BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT. " if not current_found else "") + (f"{INVALID_SCORE_SCALE_REASON}. " if rank_order_current_score and shadow_score is not None else "") + ("INSUFFICIENT_COMPARABLE_SHADOW_SCORE. " if insufficient and not (rank_order_current_score and shadow_score is not None) else "") + "Shadow rank comparison remains separate from invalid score-scale comparison; no official recommendation or weight mutation.",
            }
        )
    compare_rows.sort(key=lambda item: parse_float(item["shadow_adjusted_rank"]) or 999999)

    if coverage_ratio < 0.5 and status not in {MISSING_REQUIRED_STATUS}:
        status = INSUFFICIENT_EVIDENCE_STATUS
    if v20_84_bound and v20_84_full_count == 0 and status not in {MISSING_REQUIRED_STATUS}:
        status = INSUFFICIENT_EVIDENCE_STATUS
    status = r5_status
    nasdaq_pass = any(certified_strategy_nasdaq_pass(row, status, coverage_ratio, v20_84_full_count) for row in nasdaq_rows)
    etf_benchmark_pass = etf_return is not None and not etf_attachment_blocked
    required_evidence = max(1, len(optional_inputs))
    promotion_block_reasons = ["DEFAULT_RESEARCH_ONLY_PROMOTION_BLOCK"]
    if coverage_ratio < 0.5:
        promotion_block_reasons.extend(r5_category_blockers or ["CATEGORY_LEVEL_MULTI_PATH_EVIDENCE_BLOCKERS"])
    promotion_block_reasons.extend(r5_category_blockers)
    promotion_block_reasons.extend(r5_warn_reasons)
    if v20_84_bound and v20_84_full_count == 0:
        promotion_block_reasons.append("V20_84_PARTIAL_BLOCK_MISSING_REQUIRED_PATHS")
    if not v20_84_bound:
        promotion_block_reasons.append("V20_84_CERTIFIED_EVIDENCE_NOT_BOUND")
    if not nasdaq_pass:
        promotion_block_reasons.append("INSUFFICIENT_CERTIFIED_STRATEGY_EVIDENCE")
    if coverage_ratio >= 0.5 and status != INSUFFICIENT_EVIDENCE_STATUS:
        promotion_block_reasons.append("NO_OFFICIAL_MUTATION_ALLOWED")
    promotion_rows = [
        {
            "component_name": "MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER",
            "component_type": "RESEARCH_LAYER",
            "shadow_score": fmt(100.0 * coverage_ratio if evidence_sources else None),
            "evidence_count": len(evidence_sources),
            "required_evidence_count": required_evidence,
            "multi_path_coverage": fmt(coverage_ratio),
            "nasdaq_hurdle_passed": tf(nasdaq_pass),
            "etf_rotation_benchmark_passed": tf(etf_benchmark_pass),
            "promotion_allowed": "FALSE",
            "v20_84_evidence_bound": tf(v20_84_bound),
            "v20_84_row_level_usable_evidence_count": v20_84_row_level,
            "v20_84_fully_covered_component_count": v20_84_full_count,
            "v20_84_partial_component_count": v20_84_partial_count,
            "v20_84_integration_status": v20_84_status,
            "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
            "blocking_reason": "; ".join(promotion_block_reasons),
        },
        {
            "component_name": "ETF_ROTATION_SHADOW",
            "component_type": "SHADOW_BENCHMARK",
            "shadow_score": fmt(etf_return),
            "evidence_count": 1 if etf_return is not None else 0,
            "required_evidence_count": 1,
            "multi_path_coverage": fmt(1.0 if etf_return is not None else 0.0),
            "nasdaq_hurdle_passed": "FALSE",
            "etf_rotation_benchmark_passed": tf(etf_benchmark_pass),
            "promotion_allowed": "FALSE",
            "v20_84_evidence_bound": tf(v20_84_bound),
            "v20_84_row_level_usable_evidence_count": v20_84_row_level,
            "v20_84_fully_covered_component_count": v20_84_full_count,
            "v20_84_partial_component_count": v20_84_partial_count,
            "v20_84_integration_status": v20_84_status,
            "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
            "blocking_reason": "ETF_ROTATION_IS_SHADOW_ONLY_NOT_ACTIVATED_FOR_TRADING",
        },
    ]
    write_csv(OUTPUTS["input_audit"], audit_rows, INPUT_AUDIT_FIELDS)
    write_csv(OUTPUTS["factor"], factor_rows, FACTOR_FIELDS)
    write_csv(OUTPUTS["strategy"], strategy_rows, STRATEGY_FIELDS)
    write_csv(OUTPUTS["etf"], etf_rows, ETF_FIELDS)
    write_csv(OUTPUTS["benchmark"], benchmark_compare, BENCHMARK_FIELDS)
    write_csv(OUTPUTS["nasdaq"], nasdaq_rows, NASDAQ_FIELDS)
    write_csv(OUTPUTS["model_compare"], compare_rows, MODEL_COMPARE_FIELDS)
    write_csv(OUTPUTS["promotion"], promotion_rows, PROMOTION_FIELDS)
    write_csv(R5_DETAIL, r5_detail_rows, R5_DETAIL_FIELDS)
    R5_DETAIL_ALIAS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R5_DETAIL, R5_DETAIL_ALIAS)

    report = f"""# V20.82 Multi-Path Strategy Benchmark Validation Report

Stage: {STAGE}
Run ID: {run_id}
Created UTC: {created_at}
Status: {status}

Research-only and shadow-only.
No official recommendation.
No official weight mutation.
No trade order.
QQQ and ETF rotation are benchmarks for strategy effectiveness.
ETF rotation is not activated for trading.

## Binding Summary

- Current ranking source: {rel(current_path) if current_path else "NA - BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT"}
- Ranking fields: ticker={current["ticker_col"]}, rank={rank_col}, score={score_col}
- QQQ benchmark return: {fmt(qqq_ret)}
- Optional multi-path coverage: {fmt(coverage_ratio)}
- ETF rotation benchmark return: {fmt(etf_return)}
- V20.84 evidence bound: {tf(v20_84_bound)}
- V20.84 row-level usable evidence count: {v20_84_row_level}
- V20.84 fully covered component count: {v20_84_full_count}
- V20.84 partial component count: {v20_84_partial_count}
- V20.84 integration status: {v20_84_status}
- V20.84 effect on V20.82 status: {v20_84_effect}
- R5 validation status: {r5_status}
- R5 validation category blockers: {len(r5_category_blockers)}
- Readable regime evidence count: {readable_regime_evidence_count}
- Readable downside risk evidence count: {readable_downside_risk_evidence_count}
- Readable benchmark comparison evidence count: {readable_benchmark_comparison_evidence_count}
- Readable acceptance proof evidence count: {readable_acceptance_proof_evidence_count}
- Readable ranking delta diagnostic evidence count: {readable_ranking_delta_diagnostic_evidence_count}
- Missing required evidence categories: {"|".join(missing_required_evidence_categories) if missing_required_evidence_categories else "NONE"}
- promotion_allowed: FALSE
- nasdaq_hurdle_passed: {tf(nasdaq_pass)}
- official_recommendation_created: FALSE
- official_weight_mutated: FALSE
- trade_action_created: FALSE

## Validation Summary

This layer compares current official ranking top baskets, shadow multi-path adjusted top baskets, QQQ/Nasdaq, ETF rotation, and optional SPY/SOXX/CASH proxy benchmarks where local evidence exists. All outputs are research-only artifacts and do not create recommendations, mutate official weights, or initiate any trade/broker path.

V20.84 certified multi-path evidence is bound for row-level visibility only. Row-level usable evidence does not clear the V20.82 insufficient-evidence blocker unless V20.84 reports at least one fully covered V20.82 component. If the fully covered component count is zero, V20.82 remains blocked/partial with required paths incomplete.
V20.82-R5 consumes V20.89 required evidence paths, V20.90 ETF rotation evidence, and V20.91 multi-window strategy evidence. Category-level blockers replace generic insufficient multi-path evidence reasons.
"""
    write_text(OUTPUTS["report"], report)

    row_counts = {
        "input_audit": len(audit_rows),
        "factor": len(factor_rows),
        "strategy": len(strategy_rows),
        "etf": len(etf_rows),
        "benchmark": len(benchmark_compare),
        "nasdaq": len(nasdaq_rows),
        "model_compare": len(compare_rows),
        "promotion": len(promotion_rows),
        "r5_detail": len(r5_detail_rows),
        "report": 1,
        "manifest": 1,
    }
    manifest = {
        "stage": STAGE,
        "run_id": run_id,
        "created_at_utc": created_at,
        "status": status,
        "input_files": sorted(set(input_files)),
        "output_files": [rel(path) for path in OUTPUTS.values()] + [rel(R5_DETAIL)],
        "row_counts": row_counts,
        "r5_final_status": r5_status,
        "r5_validation_category_count": len(r5_detail_rows),
        "r5_passed_category_count": sum(1 for row in r5_detail_rows if row["validation_status"] == "PASSED"),
        "r5_blocked_category_count": sum(1 for row in r5_detail_rows if row["validation_status"] == "BLOCKED"),
        "r5_warned_category_count": sum(1 for row in r5_detail_rows if row["validation_status"] == "WARN"),
        "readable_regime_evidence_count": readable_regime_evidence_count,
        "readable_downside_risk_evidence_count": readable_downside_risk_evidence_count,
        "readable_benchmark_comparison_evidence_count": readable_benchmark_comparison_evidence_count,
        "readable_acceptance_proof_evidence_count": readable_acceptance_proof_evidence_count,
        "readable_ranking_delta_diagnostic_evidence_count": readable_ranking_delta_diagnostic_evidence_count,
        "missing_required_evidence_categories": missing_required_evidence_categories,
        "promotion_allowed": False,
        "nasdaq_hurdle_passed": nasdaq_pass,
        "v20_90_consumed": any(row["validation_category"] == "etf_rotation_evidence" and int(row["attached_row_count"]) > 0 for row in r5_detail_rows),
        "v20_91_consumed": any(row["validation_category"] == "multi_window_strategy_evidence" and int(row["attached_row_count"]) > 0 for row in r5_detail_rows),
        "v20_84_evidence_bound": v20_84_bound,
        "v20_84_row_level_usable_evidence_count": v20_84_row_level,
        "v20_84_fully_covered_component_count": v20_84_full_count,
        "v20_84_partial_component_count": v20_84_partial_count,
        "v20_84_integration_status": v20_84_status,
        "v20_84_evidence_effect_on_v20_82_status": v20_84_effect,
        "research_only": True,
        "shadow_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "trade_action_created": False,
    }
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    alias_files = write_aliases()
    manifest["output_files"].extend(rel(path) for path in alias_files)
    manifest["output_files"].append(rel(R5_DETAIL_ALIAS))
    write_text(OUTPUTS["manifest"], json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(OUTPUTS["manifest"], alias_path(OUTPUTS["manifest"]))

    print(status)
    print(f"READABLE_REGIME_EVIDENCE_COUNT={readable_regime_evidence_count}")
    print(f"READABLE_DOWNSIDE_RISK_EVIDENCE_COUNT={readable_downside_risk_evidence_count}")
    print(f"READABLE_BENCHMARK_COMPARISON_EVIDENCE_COUNT={readable_benchmark_comparison_evidence_count}")
    print(f"READABLE_ACCEPTANCE_PROOF_EVIDENCE_COUNT={readable_acceptance_proof_evidence_count}")
    print(f"READABLE_RANKING_DELTA_DIAGNOSTIC_EVIDENCE_COUNT={readable_ranking_delta_diagnostic_evidence_count}")
    print(f"MISSING_REQUIRED_EVIDENCE_CATEGORIES={'|'.join(missing_required_evidence_categories) if missing_required_evidence_categories else 'NONE'}")
    print("PROMOTION_ALLOWED=FALSE")
    print(f"NASDAQ_HURDLE_PASSED={tf(nasdaq_pass)}")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 0 if status in {PASS_STATUS, OPTIONAL_GAPS_STATUS, ETF_BLOCKED_STATUS, R5_PASS_STATUS, R5_PARTIAL_STATUS} else 1


if __name__ == "__main__":
    raise SystemExit(main())
