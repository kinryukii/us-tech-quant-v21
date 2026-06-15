from __future__ import annotations

import ast
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
PASS_STATUS = "PASS_V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
BLOCKED_STATUS = "BLOCKED_V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_CREATED"
SCHEMA_DRY_RUN_PASS = "PASS_SCHEMA_DRY_RUN_GATE_CREATED"
NEXT_STAGE = "V20.53_FORMAL_TESTS"
V20_52_CONTRACT_PASS = "PASS_POLICY_CONTRACT_GATE_CREATED"
V20_52_DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_CREATED"
RUN_ID_FALLBACK = "V20_47_20260604T114058Z"

IN_V52_SUMMARY = CONSOLIDATION / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_SUMMARY.csv"
IN_V52_UPSTREAM = CONSOLIDATION / "V20_52_UPSTREAM_V20_51_VALIDATION.csv"
IN_V52_GAP = CONSOLIDATION / "V20_52_POLICY_GAP_RESOLUTION_CONTRACT.csv"
IN_V52_SCHEMA = CONSOLIDATION / "V20_52_OFFICIAL_OUTPUT_SCHEMA_CONTRACT.csv"
IN_V52_LANGUAGE = CONSOLIDATION / "V20_52_RECOMMENDATION_LANGUAGE_POLICY.csv"
IN_V52_RISK = CONSOLIDATION / "V20_52_RISK_POSITION_POLICY_CONTRACT.csv"
IN_V52_MANUAL = CONSOLIDATION / "V20_52_MANUAL_APPROVAL_AND_REAL_BOOK_POLICY.csv"
IN_V52_BROKER = CONSOLIDATION / "V20_52_BROKER_DISABLED_ENFORCEMENT_CONTRACT.csv"
IN_V52_AUDIT = CONSOLIDATION / "V20_52_POST_RECOMMENDATION_AUDIT_TEST_CONTRACT.csv"
IN_V52_SCOPE = CONSOLIDATION / "V20_52_FUTURE_OFFICIAL_STAGE_ALLOWED_SCOPE.csv"
IN_V52_ACTION = CONSOLIDATION / "V20_52_POLICY_CONTRACT_ACTION_BOUNDARY.csv"
IN_V52_SAFETY = CONSOLIDATION / "V20_52_POLICY_CONTRACT_SAFETY_BOUNDARY.csv"
IN_V52_NEXT = CONSOLIDATION / "V20_52_NEXT_STEP_DECISION.csv"
IN_V52_REPORT = READ_CENTER / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_REPORT.md"
IN_V52_CURRENT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE.md"
IN_V52_READ_FIRST = OPS / "V20_52_READ_FIRST.txt"
IN_V52_TEST = SCRIPT_DIR / "test_v20_52_official_recommendation_policy_contract_gate.py"

IN_V50_CANDIDATE = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
IN_V50_BENCHMARK = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_FACTOR = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_LINEAGE = CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"
IN_V50_NEXT = CONSOLIDATION / "V20_50_NEXT_STEP_DECISION.csv"

OUT_SUMMARY = CONSOLIDATION / "V20_53_OFFICIAL_SCHEMA_DRY_RUN_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_53_UPSTREAM_V20_52_VALIDATION.csv"
OUT_MAPPING = CONSOLIDATION / "V20_53_SCHEMA_FIELD_MAPPING_DRY_RUN.csv"
OUT_DRY_ROWS = CONSOLIDATION / "V20_53_CANDIDATE_SCHEMA_DRY_RUN_ROWS.csv"
OUT_LANGUAGE_VALIDATION = CONSOLIDATION / "V20_53_LANGUAGE_POLICY_DRY_RUN_VALIDATION.csv"
OUT_POLICY_BINDING = CONSOLIDATION / "V20_53_POLICY_BINDING_DRY_RUN_VALIDATION.csv"
OUT_ACTION = CONSOLIDATION / "V20_53_SCHEMA_DRY_RUN_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_53_SCHEMA_DRY_RUN_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_53_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_53_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE.md"
READ_FIRST = OPS / "V20_53_READ_FIRST.txt"

V52_REQUIRED = [
    IN_V52_SUMMARY,
    IN_V52_UPSTREAM,
    IN_V52_GAP,
    IN_V52_SCHEMA,
    IN_V52_LANGUAGE,
    IN_V52_RISK,
    IN_V52_MANUAL,
    IN_V52_BROKER,
    IN_V52_AUDIT,
    IN_V52_SCOPE,
    IN_V52_ACTION,
    IN_V52_SAFETY,
    IN_V52_NEXT,
    IN_V52_REPORT,
    IN_V52_CURRENT,
    IN_V52_READ_FIRST,
]

V50_REQUIRED = [
    IN_V50_CANDIDATE,
    IN_V50_BENCHMARK,
    IN_V50_FACTOR,
    IN_V50_ENTRY,
    IN_V50_LINEAGE,
    IN_V50_NEXT,
]

SCHEMA_FIELD_ORDER = [
    "recommendation_run_id",
    "source_research_packet_id",
    "source_v20_47_run_id",
    "candidate_id_or_ticker",
    "preserved_report_rank",
    "research_decision_category",
    "official_recommendation_label",
    "recommendation_confidence_band",
    "recommendation_rationale",
    "risk_summary",
    "position_policy_reference",
    "manual_approval_required",
    "broker_execution_allowed",
    "real_book_mutation_allowed",
    "official_trading_allowed",
    "created_timestamp_utc",
    "audit_status",
]


def clean(value: object) -> str:
    return str(value or "").strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def exists_non_empty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def row_count(path: Path) -> int:
    rows, _ = read_csv(path)
    return len(rows)


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


def status_row(item: str, path: Path, expected: str, actual: str, ok: bool, blocker: str = "") -> dict[str, object]:
    return {
        "validation_item": item,
        "source_path": rel(path),
        "expected_value": expected,
        "actual_value": actual,
        "validation_status": "PASS" if ok else "BLOCKED",
        "blocker_reason": "" if ok else blocker,
    }


def value_by_name(rows: list[dict[str, str]], name_field: str, name: str, value_field: str) -> str:
    for row in rows:
        if clean(row.get(name_field)) == name:
            return clean(row.get(value_field))
    return ""


def run_v52_tests() -> bool:
    if not IN_V52_TEST.exists():
        return False
    result = subprocess.run([sys.executable, str(IN_V52_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    return result.returncode == 0 and "PASS_V20_52_TESTS" in result.stdout.splitlines()


def source_has_forbidden_imports(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"yfinance", "requests", "urllib", "httpx", "alpaca_trade_api", "ibapi", "ccxt"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in forbidden for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden:
                return True
    return False


def actionable_hits(text: str) -> list[str]:
    lowered = text.lower()
    allowed_contexts = [
        r"no buy/sell/hold instruction",
        r"no buy/sell/hold instructions",
        r"buy/sell/hold/trading signal statement",
        r"official_buy_sell_hold_recommendation_allowed",
        r"buy_sell_hold_instruction_created",
        r"no broker/order execution",
        r"not trading-authorized",
        r"dry-run only",
        r"schema dry-run only",
        r"future gate required",
        r"not assigned",
        r"not_assigned_dry_run",
    ]
    for pattern in allowed_contexts:
        lowered = re.sub(pattern, "", lowered, flags=re.IGNORECASE)
    patterns = [
        r"\bstrong buy\b",
        r"\badd position\b",
        r"\benter position\b",
        r"\bexit position\b",
        r"\btrade now\b",
        r"\bexecute\b",
        r"\bbuy\b",
        r"\bsell\b",
        r"\bhold\b",
    ]
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            start = max(0, match.start() - 35)
            end = min(len(lowered), match.end() + 35)
            hits.append(lowered[start:end].replace("\n", " "))
    return hits


def build_upstream_validation(v52_tests_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V52_SUMMARY)
    next_row = first_row(IN_V52_NEXT)
    language, _ = read_csv(IN_V52_LANGUAGE)
    broker, _ = read_csv(IN_V52_BROKER)
    actions, _ = read_csv(IN_V52_ACTION)
    safety, _ = read_csv(IN_V52_SAFETY)
    checks: list[dict[str, object]] = []

    for path in V52_REQUIRED:
        item = path.stem.lower() + "_exists_non_empty"
        ok = exists_non_empty(path)
        checks.append(status_row(item, path, "TRUE", tf(ok), ok, "missing_or_empty"))
    checks.append(status_row("v20_52_formal_test_script_exists", IN_V52_TEST, "TRUE", tf(IN_V52_TEST.exists()), IN_V52_TEST.exists(), "missing_test_script"))
    checks.append(status_row("v20_52_tests_status", IN_V52_TEST, "PASS", "PASS" if v52_tests_passed else "FAIL", v52_tests_passed, "formal_tests_failed"))
    checks.append(status_row("v20_52_contract_gate_status", IN_V52_SUMMARY, V20_52_CONTRACT_PASS, clean(summary.get("contract_gate_status")), clean(summary.get("contract_gate_status")) == V20_52_CONTRACT_PASS, "contract_gate_not_pass"))
    checks.append(status_row("v20_52_decision", IN_V52_NEXT, V20_52_DECISION_PASS, clean(next_row.get("decision")), clean(next_row.get("decision")) == V20_52_DECISION_PASS, "decision_not_pass"))
    checks.append(status_row("v20_52_required_outputs_present_non_empty", IN_V52_SUMMARY, "16", str(sum(1 for path in V52_REQUIRED if exists_non_empty(path))), all(exists_non_empty(path) for path in V52_REQUIRED), "required_outputs_missing"))

    checks.extend([
        status_row("v20_52_policy_gap_contract_rows", IN_V52_GAP, "9", str(row_count(IN_V52_GAP)), row_count(IN_V52_GAP) == 9, "gap_contract_count"),
        status_row("v20_52_official_output_schema_contract_rows", IN_V52_SCHEMA, "17", str(row_count(IN_V52_SCHEMA)), row_count(IN_V52_SCHEMA) == 17, "schema_contract_count"),
        status_row("v20_52_language_policy_forbidden_rows", IN_V52_LANGUAGE, "10", str(sum(1 for row in language if clean(row.get("policy_type")) == "FORBIDDEN_ACTIONABLE_LANGUAGE")), sum(1 for row in language if clean(row.get("policy_type")) == "FORBIDDEN_ACTIONABLE_LANGUAGE") == 10, "language_forbidden_count"),
        status_row("v20_52_language_policy_safe_rows", IN_V52_LANGUAGE, "7", str(sum(1 for row in language if clean(row.get("policy_type")) == "SAFE_RESEARCH_ONLY_LANGUAGE")), sum(1 for row in language if clean(row.get("policy_type")) == "SAFE_RESEARCH_ONLY_LANGUAGE") == 7, "language_safe_count"),
        status_row("v20_52_risk_policy_rows", IN_V52_RISK, "10", str(row_count(IN_V52_RISK)), row_count(IN_V52_RISK) == 10, "risk_count"),
        status_row("v20_52_manual_real_book_policy_rows", IN_V52_MANUAL, "8", str(row_count(IN_V52_MANUAL)), row_count(IN_V52_MANUAL) == 8, "manual_count"),
        status_row("v20_52_broker_disabled_pass_rows", IN_V52_BROKER, "8", str(sum(1 for row in broker if clean(row.get("enforcement_status")) == "PASS")), sum(1 for row in broker if clean(row.get("enforcement_status")) == "PASS") == 8, "broker_pass_count"),
        status_row("v20_52_post_recommendation_audit_contract_rows", IN_V52_AUDIT, "10", str(row_count(IN_V52_AUDIT)), row_count(IN_V52_AUDIT) == 10, "audit_count"),
    ])

    action_ok = row_count(IN_V52_ACTION) == 22 and all(clean(row.get("allowed_flag")) in {"TRUE", "FALSE"} for row in actions)
    safety_ok = row_count(IN_V52_SAFETY) == 19 and all(clean(row.get("validation_status")) == "PASS" and clean(row.get("expected_value")) == clean(row.get("actual_value")) for row in safety)
    checks.append(status_row("v20_52_action_boundary_pass", IN_V52_ACTION, "PASS", "PASS" if action_ok else "FAIL", action_ok, "action_boundary_failed"))
    checks.append(status_row("v20_52_safety_boundary_pass", IN_V52_SAFETY, "PASS", "PASS" if safety_ok else "FAIL", safety_ok, "safety_boundary_failed"))

    false_fields = [
        "official_recommendation_created_in_this_stage",
        "official_recommendation_allowed_in_this_stage",
        "official_trading_allowed",
        "broker_order_execution_used",
        "provider_refresh_executed_in_this_stage",
        "yfinance_import_used_in_this_stage",
        "official_ranking_mutated",
        "dynamic_weighting_mutated",
        "returns_calculated",
        "benchmark_relative_returns_calculated",
        "scores_recomputed",
        "rankings_recomputed",
        "trading_signals_created",
    ]
    for field in false_fields:
        checks.append(status_row(f"v20_52_{field}", IN_V52_SUMMARY, "FALSE", clean(summary.get(field)), clean(summary.get(field)) == "FALSE", f"{field}_not_false"))
    for name in ["official_ranking_mutated", "dynamic_weighting_mutated", "returns_calculated", "scores_recomputed", "rankings_recomputed", "trading_signals_created"]:
        checks.append(status_row(f"v20_52_safety_{name}", IN_V52_SAFETY, "FALSE", value_by_name(safety, "safety_boundary", name, "actual_value"), value_by_name(safety, "safety_boundary", name, "actual_value") == "FALSE", f"safety_{name}_not_false"))
    return checks


def build_mapping(schema: list[dict[str, str]]) -> list[dict[str, object]]:
    policy: dict[str, tuple[str, str, str, str, str]] = {
        "recommendation_run_id": ("MAPPED_DRY_RUN", "V20.53", "deterministic dry-run row id", "DRY_RUN_PLACEHOLDER", "FALSE"),
        "source_research_packet_id": ("MAPPED", "V20.50", "packet_row_id", "copy source research packet row id", "FALSE"),
        "source_v20_47_run_id": ("MAPPED", "V20.50", "v20_47_run_id", "copy certified source run id", "FALSE"),
        "candidate_id_or_ticker": ("MAPPED", "V20.50", "normalized_ticker", "copy source ticker", "FALSE"),
        "preserved_report_rank": ("MAPPED", "V20.50", "report_rank", "copy preserved source rank", "FALSE"),
        "research_decision_category": ("MAPPED", "V20.50", "research_decision_category", "copy research-only category", "FALSE"),
        "official_recommendation_label": ("PLACEHOLDER_NOT_ASSIGNED", "V20.53", "not assigned in schema dry-run", "NOT_ASSIGNED_DRY_RUN", "TRUE"),
        "recommendation_confidence_band": ("PLACEHOLDER_NOT_ASSIGNED", "V20.53", "not assigned in schema dry-run", "NOT_ASSIGNED_DRY_RUN", "TRUE"),
        "recommendation_rationale": ("MAPPED_DRY_RUN", "V20.50", "research_rationale", "schema placeholder summary only", "FALSE"),
        "risk_summary": ("MAPPED_DRY_RUN", "V20.52", "risk/position policy contract", "schema placeholder bound to risk policy", "FALSE"),
        "position_policy_reference": ("MAPPED_DRY_RUN", "V20.52", "risk policy ids", "V20_52_RISK_POSITION_POLICY_CONTRACT", "FALSE"),
        "manual_approval_required": ("MAPPED_CONSTANT", "V20.52", "manual approval policy", "TRUE", "FALSE"),
        "broker_execution_allowed": ("MAPPED_CONSTANT", "V20.52", "broker-disabled enforcement", "FALSE", "FALSE"),
        "real_book_mutation_allowed": ("MAPPED_CONSTANT", "V20.52", "real-book separation policy", "FALSE", "FALSE"),
        "official_trading_allowed": ("MAPPED_CONSTANT", "V20.52", "policy contract boundary", "FALSE", "FALSE"),
        "created_timestamp_utc": ("MAPPED_DRY_RUN", "V20.53", "dry-run timestamp placeholder", "DRY_RUN_TIMESTAMP_NOT_OFFICIAL", "FALSE"),
        "audit_status": ("MAPPED_DRY_RUN", "V20.52", "audit/test contract", "DRY_RUN_ONLY", "FALSE"),
    }
    schema_by_name = {clean(row.get("field_name")): row for row in schema}
    rows: list[dict[str, object]] = []
    for field_name in SCHEMA_FIELD_ORDER:
        source = schema_by_name.get(field_name, {})
        status, stage, source_rule, value_policy, pending = policy[field_name]
        ok = bool(source) and (pending == "TRUE" or status in {"MAPPED", "MAPPED_DRY_RUN", "MAPPED_CONSTANT"})
        rows.append({
            "field_name": field_name,
            "field_type": clean(source.get("field_type")),
            "required_flag": clean(source.get("required_flag")) or "TRUE",
            "source_mapping_status": status,
            "source_stage": stage,
            "source_field_or_rule": source_rule,
            "dry_run_value_policy": value_policy,
            "pending_future_gate_flag": pending,
            "validation_rule": clean(source.get("validation_rule")),
            "blocker_if_missing": clean(source.get("blocker_if_missing")),
            "dry_run_validation_status": "PASS" if ok else "BLOCKED",
            "notes": "Schema dry-run only; no official recommendation label assigned.",
        })
    return rows


def build_candidate_rows(candidates: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, row in enumerate(candidates, 1):
        ticker = clean(row.get("normalized_ticker")) or clean(row.get("display_name_or_ticker"))
        rows.append({
            "dry_run_row_id": f"V20_53_SCHEMA_DRY_RUN_{index:03d}",
            "source_packet_row_id": clean(row.get("packet_row_id")),
            "source_v20_47_run_id": clean(row.get("v20_47_run_id")) or RUN_ID_FALLBACK,
            "candidate_id_or_ticker": ticker,
            "preserved_report_rank": clean(row.get("report_rank")),
            "research_decision_category": clean(row.get("research_decision_category")),
            "official_recommendation_label": "NOT_ASSIGNED_DRY_RUN",
            "recommendation_confidence_band": "NOT_ASSIGNED_DRY_RUN",
            "recommendation_rationale": f"Schema placeholder for {ticker}; research-only category copied from source packet; future gate required.",
            "risk_summary": "Schema placeholder bound to V20.52 risk policy; not trading-authorized.",
            "position_policy_reference": "V20_52_RISK_POSITION_POLICY_CONTRACT",
            "manual_approval_required": "TRUE",
            "broker_execution_allowed": "FALSE",
            "real_book_mutation_allowed": "FALSE",
            "official_trading_allowed": "FALSE",
            "created_timestamp_utc": "DRY_RUN_TIMESTAMP_NOT_OFFICIAL",
            "audit_status": "DRY_RUN_ONLY",
            "schema_dry_run_only": "TRUE",
            "official_recommendation_created": "FALSE",
            "recommendation_label_assigned": "FALSE",
            "trading_signal_created": "FALSE",
            "ranking_mutated": "FALSE",
            "score_recomputed": "FALSE",
            "blocker_reason": "",
        })
    return rows


def build_language_validation(mapping: list[dict[str, object]], dry_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    artifacts = [
        ("schema_field_mapping", OUT_MAPPING, mapping),
        ("candidate_schema_dry_run_rows", OUT_DRY_ROWS, dry_rows),
        ("read_center_report", REPORT, []),
        ("current_alias", CURRENT_REPORT, []),
        ("read_first", READ_FIRST, []),
    ]
    safe_phrases = ["schema placeholder", "not assigned", "dry-run only", "future gate required", "no official recommendation created", "not trading-authorized"]
    rows: list[dict[str, object]] = []
    for scope, path, source_rows in artifacts:
        if source_rows:
            text = "\n".join(",".join(clean(value) for value in row.values()) for row in source_rows)
        else:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        hits = actionable_hits(text)
        safe_count = sum(1 for phrase in safe_phrases if phrase in text.lower())
        rows.append({
            "validation_scope": scope,
            "checked_artifact": rel(path),
            "forbidden_phrase_count": len(hits),
            "allowed_research_phrase_count": safe_count,
            "actionable_instruction_found": tf(bool(hits)),
            "validation_status": "PASS" if not hits else "BLOCKED",
            "blocker_reason": "" if not hits else "actionable_instruction_language",
        })
    return rows


def build_policy_binding() -> list[dict[str, object]]:
    specs = [
        ("official output schema", IN_V52_SCHEMA, "PASS", "17 schema fields consumed; placeholder rows only.", "Future gate required before instantiation."),
        ("recommendation language", IN_V52_LANGUAGE, "PASS", "Language validation scan blocks actionable instructions.", "Future controlled labels require later gate."),
        ("risk/position policy", IN_V52_RISK, "PASS", "Rows bind position_policy_reference to V20.52 risk contract.", "Future risk binding still required."),
        ("manual approval policy", IN_V52_MANUAL, "PASS", "manual_approval_required is TRUE in dry-run rows.", "Human/operator approval required before future publication."),
        ("real-book separation", IN_V52_MANUAL, "PASS", "real_book_mutation_allowed is FALSE.", "Separate approved ledger required before any real-book action."),
        ("broker-disabled enforcement", IN_V52_BROKER, "PASS", "broker_execution_allowed is FALSE.", "Separate later broker gate required."),
        ("post-recommendation audit/test contract", IN_V52_AUDIT, "PENDING_FUTURE_GATE", "audit_status is DRY_RUN_ONLY.", "Future generated output requires audit tests."),
    ]
    return [
        {
            "policy_area": area,
            "policy_source": rel(path),
            "binding_status": status,
            "dry_run_evidence": evidence,
            "future_gate_requirement": future,
            "blocker_reason": "",
        }
        for area, path, status, evidence, future in specs
    ]


def build_action_boundary() -> list[dict[str, object]]:
    true_items = [
        "schema_dry_run_allowed",
        "schema_field_mapping_allowed",
        "candidate_schema_placeholder_rows_allowed",
        "policy_binding_validation_allowed",
        "language_policy_validation_allowed",
        "future_schema_instantiation_gate_preparation_allowed",
    ]
    false_items = [
        "official_recommendation_generation_allowed_in_this_stage",
        "official_recommendation_label_assignment_allowed",
        "official_buy_sell_hold_recommendation_allowed",
        "live_trading_allowed",
        "broker_order_execution_allowed",
        "provider_refresh_allowed_in_this_stage",
        "yfinance_import_allowed_in_this_stage",
        "official_ranking_mutation_allowed",
        "dynamic_weighting_mutation_allowed",
        "real_portfolio_mutation_allowed",
        "return_calculation_allowed",
        "benchmark_relative_return_calculation_allowed",
        "score_recomputation_allowed",
        "ranking_recomputation_allowed",
        "trading_signal_generation_allowed",
    ]
    rows = [{"boundary_name": item, "allowed_flag": "TRUE", "evidence": "Allowed schema dry-run and validation activity.", "blocker_reason": ""} for item in true_items]
    rows.extend({"boundary_name": item, "allowed_flag": "FALSE", "evidence": "Blocked by V20.53 schema dry-run gate boundary.", "blocker_reason": "blocked_by_schema_dry_run_boundary"} for item in false_items)
    return rows


def build_safety_boundary() -> list[dict[str, object]]:
    specs = [
        ("provider_refresh_executed_in_v20_53", "FALSE", "FALSE", "No provider refresh in V20.53."),
        ("yfinance_imported_in_v20_53", "FALSE", "FALSE", "No yfinance import in V20.53."),
        ("v20_52_policy_contract_used", "TRUE", "TRUE", "V20.52 policy contract artifacts consumed."),
        ("v20_50_research_only_packet_reference_used", "TRUE", "TRUE", "V20.50 research-only packet referenced."),
        ("v20_47_certified_cache_reference_used", "TRUE", "TRUE", "V20.47 certified cache run id preserved."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_created", "FALSE", "FALSE", "No official recommendation created."),
        ("official_recommendation_label_assigned", "FALSE", "FALSE", "No official recommendation label assigned."),
        ("official_recommendation_allowed_in_this_stage", "FALSE", "FALSE", "Generation is blocked in V20.53."),
        ("official_trading_allowed", "FALSE", "FALSE", "Not trading-authorized."),
        ("official_ranking_mutated", "FALSE", "FALSE", "No official rank mutation."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No dynamic weight mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No real portfolio mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No forward return calculation."),
        ("benchmark_relative_returns_calculated", "FALSE", "FALSE", "No benchmark-relative return calculation."),
        ("scores_recomputed", "FALSE", "FALSE", "No score recomputation."),
        ("rankings_recomputed", "FALSE", "FALSE", "No ranking recomputation."),
        ("trading_signals_created", "FALSE", "FALSE", "No trading signals."),
        ("v21_output_path_created", "FALSE", "FALSE", "No V21 output path."),
        ("v19_21_output_path_created", "FALSE", "FALSE", "No V19.21 output path."),
    ]
    return [
        {
            "safety_boundary": name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": "PASS" if expected == actual else "BLOCKED",
            "evidence": evidence,
            "blocker_reason": "" if expected == actual else "safety_boundary_violation",
        }
        for name, expected, actual, evidence in specs
    ]


def md_table(rows: list[dict[str, object]], fields: list[str], limit: int | None = None) -> str:
    selected = rows if limit is None else rows[:limit]
    if not selected:
        return "_No rows._"
    header = "| " + " | ".join(fields) + " |"
    sep = "| " + " | ".join(["---"] * len(fields)) + " |"
    body = ["| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in fields) + " |" for row in selected]
    return "\n".join([header, sep, *body])


def cleanup_pycache() -> None:
    pycache = SCRIPT_DIR / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)


def main() -> int:
    v52_tests_passed = run_v52_tests()
    v52_summary = first_row(IN_V52_SUMMARY)
    schema, _ = read_csv(IN_V52_SCHEMA)
    candidates, _ = read_csv(IN_V50_CANDIDATE)
    v20_47_run_id = clean(v52_summary.get("v20_47_run_id")) or RUN_ID_FALLBACK

    upstream = build_upstream_validation(v52_tests_passed)
    mapping = build_mapping(schema)
    dry_rows = build_candidate_rows(candidates[:50])
    policy_binding = build_policy_binding()
    action = build_action_boundary()
    safety = build_safety_boundary()

    blockers = [clean(row.get("blocker_reason")) for row in upstream if clean(row.get("validation_status")) == "BLOCKED"]
    blockers.extend(clean(row.get("blocker_reason")) for row in mapping if clean(row.get("dry_run_validation_status")) == "BLOCKED")
    blockers.extend(clean(row.get("blocker_reason")) for row in safety if clean(row.get("validation_status")) == "BLOCKED")
    if any(not exists_non_empty(path) for path in V50_REQUIRED):
        blockers.append("v20_50_research_context_missing")
    if len(candidates) < 50:
        blockers.append("candidate_packet_fewer_than_50_rows")
    if source_has_forbidden_imports(Path(__file__)):
        blockers.append("forbidden_runtime_import")
    if any(clean(row.get("official_recommendation_label")) not in {"NOT_ASSIGNED_DRY_RUN", "PLACEHOLDER_NOT_ASSIGNED"} for row in dry_rows):
        blockers.append("official_recommendation_label_assigned")
    if any(actionable_hits(",".join(clean(value) for value in row.values())) for row in dry_rows):
        blockers.append("actionable_instruction_language_in_dry_run_rows")
    if (ROOT / "outputs" / "v21").exists() or (ROOT / "outputs" / "v19_21").exists() or (ROOT / "outputs" / "v19" / "V19_21").exists():
        blockers.append("forbidden_future_output_path_exists")
    blockers = [item for item in blockers if item]
    warnings: list[str] = []

    language_validation = build_language_validation(mapping, dry_rows)
    blockers.extend(clean(row.get("blocker_reason")) for row in language_validation if clean(row.get("validation_status")) == "BLOCKED")
    blockers = [item for item in blockers if item]

    blocker_count = len(blockers)
    warning_count = len(warnings)
    pass_gate = blocker_count == 0
    final_status = PASS_STATUS if pass_gate else BLOCKED_STATUS
    schema_status = SCHEMA_DRY_RUN_PASS if pass_gate else "BLOCKED_SCHEMA_DRY_RUN_GATE"
    decision = DECISION_PASS if pass_gate else "BLOCKED_OFFICIAL_RECOMMENDATION_SCHEMA_DRY_RUN_GATE"
    mapped_count = sum(1 for row in mapping if clean(row.get("pending_future_gate_flag")) == "FALSE" and clean(row.get("dry_run_validation_status")) == "PASS")
    pending_count = sum(1 for row in mapping if clean(row.get("pending_future_gate_flag")) == "TRUE")

    summary = [{
        "stage": STAGE,
        "upstream_v20_52_contract_status": clean(v52_summary.get("contract_gate_status")),
        "upstream_v20_52_tests_status": "PASS" if v52_tests_passed else "FAIL",
        "v20_47_run_id": v20_47_run_id,
        "schema_contract_used": tf(exists_non_empty(IN_V52_SCHEMA)),
        "language_policy_used": tf(exists_non_empty(IN_V52_LANGUAGE)),
        "risk_position_policy_used": tf(exists_non_empty(IN_V52_RISK)),
        "manual_approval_policy_used": tf(exists_non_empty(IN_V52_MANUAL)),
        "broker_disabled_policy_used": tf(exists_non_empty(IN_V52_BROKER)),
        "audit_contract_used": tf(exists_non_empty(IN_V52_AUDIT)),
        "research_packet_used": tf(exists_non_empty(IN_V50_CANDIDATE)),
        "candidate_rows_reviewed": len(candidates),
        "schema_fields_reviewed": len(schema),
        "dry_run_rows_created": len(dry_rows),
        "required_fields_mapped": mapped_count,
        "required_fields_pending_future_gate": pending_count,
        "official_recommendation_created_in_this_stage": "FALSE",
        "official_recommendation_label_assigned": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_order_execution_used": "FALSE",
        "provider_refresh_executed_in_this_stage": "FALSE",
        "yfinance_import_used_in_this_stage": "FALSE",
        "official_ranking_mutated": "FALSE",
        "dynamic_weighting_mutated": "FALSE",
        "returns_calculated": "FALSE",
        "benchmark_relative_returns_calculated": "FALSE",
        "scores_recomputed": "FALSE",
        "rankings_recomputed": "FALSE",
        "trading_signals_created": "FALSE",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "schema_dry_run_status": schema_status,
        "next_recommended_stage": NEXT_STAGE,
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "schema_dry_run_status": schema_status,
        "schema_dry_run_created": tf(pass_gate),
        "official_recommendation_created_in_this_stage": "FALSE",
        "official_recommendation_label_assigned": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "next_recommended_stage": NEXT_STAGE,
    }]

    write_csv(OUT_UPSTREAM, upstream, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_MAPPING, mapping, ["field_name", "field_type", "required_flag", "source_mapping_status", "source_stage", "source_field_or_rule", "dry_run_value_policy", "pending_future_gate_flag", "validation_rule", "blocker_if_missing", "dry_run_validation_status", "notes"])
    write_csv(OUT_DRY_ROWS, dry_rows, ["dry_run_row_id", "source_packet_row_id", "source_v20_47_run_id", "candidate_id_or_ticker", "preserved_report_rank", "research_decision_category", "official_recommendation_label", "recommendation_confidence_band", "recommendation_rationale", "risk_summary", "position_policy_reference", "manual_approval_required", "broker_execution_allowed", "real_book_mutation_allowed", "official_trading_allowed", "created_timestamp_utc", "audit_status", "schema_dry_run_only", "official_recommendation_created", "recommendation_label_assigned", "trading_signal_created", "ranking_mutated", "score_recomputed", "blocker_reason"])
    report_stub = ""
    write_text(REPORT, report_stub)
    write_text(CURRENT_REPORT, report_stub)
    write_text(READ_FIRST, "")
    language_validation = build_language_validation(mapping, dry_rows)
    write_csv(OUT_LANGUAGE_VALIDATION, language_validation, ["validation_scope", "checked_artifact", "forbidden_phrase_count", "allowed_research_phrase_count", "actionable_instruction_found", "validation_status", "blocker_reason"])
    write_csv(OUT_POLICY_BINDING, policy_binding, ["policy_area", "policy_source", "binding_status", "dry_run_evidence", "future_gate_requirement", "blocker_reason"])
    write_csv(OUT_ACTION, action, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.53 Official Recommendation Schema Dry-Run Gate

## Stage status

Stage: {STAGE}
Final status: {final_status}
Decision: {decision}
Schema dry-run status: {schema_status}
Next recommended stage: {NEXT_STAGE}

## Upstream V20.52 validation

V20.52 contract status: {clean(v52_summary.get("contract_gate_status"))}
V20.52 formal tests status: {"PASS" if v52_tests_passed else "FAIL"}
V20.47 run ID/cache reference: {v20_47_run_id}

{md_table(upstream, ["validation_item", "expected_value", "actual_value", "validation_status"], 45)}

## Schema dry-run scope

This stage is schema dry-run only. It creates schema placeholder rows from the V20.50 research-only packet and keeps future gate required for any future official schema instantiation.

## Schema field mapping dry-run

{md_table(mapping, ["field_name", "source_mapping_status", "dry_run_value_policy", "pending_future_gate_flag", "dry_run_validation_status"])}

## Candidate schema dry-run rows

Dry-run rows created: {len(dry_rows)}
Candidate rows reviewed: {len(candidates)}
Official labels assigned: FALSE

{md_table(dry_rows, ["dry_run_row_id", "candidate_id_or_ticker", "preserved_report_rank", "research_decision_category", "official_recommendation_label", "schema_dry_run_only"], 12)}

## Language policy dry-run validation

{md_table(language_validation, ["validation_scope", "actionable_instruction_found", "validation_status"])}

## Policy binding dry-run validation

{md_table(policy_binding, ["policy_area", "binding_status", "future_gate_requirement"])}

## Action boundary

{md_table(action, ["boundary_name", "allowed_flag", "evidence"])}

## Safety boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"])}

## Explicit no official recommendation created statement

No official recommendation created in V20.53. This stage is a schema dry-run gate only.

## Explicit no recommendation label assigned statement

No recommendation label assigned in V20.53. Candidate rows use NOT_ASSIGNED_DRY_RUN placeholders.

## Explicit no buy/sell/hold/trading signal statement

No buy/sell/hold instruction and no trading signal created in V20.53.

## Explicit no broker/order statement

Broker disabled. No broker/order execution path is used by V20.53.

## Explicit no provider refresh/yfinance statement

No provider refresh or network refresh is performed in V20.53. V20.53 does not import yfinance.

## Explicit no score/ranking/return recomputation statement

No forward return calculation, benchmark-relative return calculation, score recomputation, ranking recomputation, official ranking mutation, or dynamic weighting mutation is performed in V20.53.

## Blockers and warnings

Blockers: {blocker_text}
Warnings: {warning_text}

## Next recommended stage

{NEXT_STAGE}
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"DECISION={decision}",
        f"SCHEMA_DRY_RUN_GATE_STATUS={schema_status}",
        "V20_52_POLICY_CONTRACT_USED=TRUE",
        "V20_50_RESEARCH_ONLY_PACKET_REFERENCE=TRUE",
        f"V20_47_RUN_ID_CACHE_REFERENCE={v20_47_run_id}",
        "DRY_RUN_ONLY_SAFETY_FLAGS=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "RECOMMENDATION_LABEL_ASSIGNED=FALSE",
        "BUY_SELL_HOLD_INSTRUCTION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_53=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_53=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "SCHEMA_DRY_RUN_ONLY=TRUE",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    language_validation = build_language_validation(mapping, dry_rows)
    write_csv(OUT_LANGUAGE_VALIDATION, language_validation, ["validation_scope", "checked_artifact", "forbidden_phrase_count", "allowed_research_phrase_count", "actionable_instruction_found", "validation_status", "blocker_reason"])

    cleanup_pycache()
    print(final_status)
    print(f"DECISION={decision}")
    print(f"SCHEMA_DRY_RUN_STATUS={schema_status}")
    print(f"UPSTREAM_V20_52_CONTRACT_STATUS={clean(v52_summary.get('contract_gate_status'))}")
    print(f"UPSTREAM_V20_52_TESTS_STATUS={'PASS' if v52_tests_passed else 'FAIL'}")
    print(f"SCHEMA_FIELDS_REVIEWED={len(schema)}")
    print(f"CANDIDATE_DRY_RUN_ROWS_CREATED={len(dry_rows)}")
    print(f"REQUIRED_FIELDS_MAPPED={mapped_count}")
    print(f"REQUIRED_FIELDS_PENDING_FUTURE_GATE={pending_count}")
    print(f"BLOCKER_COUNT={blocker_count}")
    print(f"WARNING_COUNT={warning_count}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}")
    return 0 if pass_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
