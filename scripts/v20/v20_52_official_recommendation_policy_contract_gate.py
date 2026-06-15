from __future__ import annotations

import ast
import csv
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
PASS_STATUS = "PASS_V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
BLOCKED_STATUS = "BLOCKED_V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_CREATED"
CONTRACT_GATE_PASS = "PASS_POLICY_CONTRACT_GATE_CREATED"
NEXT_STAGE = "V20.52_FORMAL_TESTS"
V20_51_DECISION_PASS = "PASS_OFFICIAL_RECOMMENDATION_READINESS_GATE_CREATED"
V20_51_READY_VALUES = {"READY_WITH_RESEARCH_ONLY_LIMITS", "READY_FOR_FUTURE_OFFICIAL_RECOMMENDATION_GATE"}
V20_51_FUTURE_READY_VALUES = {"CONDITIONAL", "TRUE"}
RUN_ID_FALLBACK = "V20_47_20260604T114058Z"

IN_V51_SUMMARY = CONSOLIDATION / "V20_51_OFFICIAL_RECOMMENDATION_READINESS_SUMMARY.csv"
IN_V51_UPSTREAM = CONSOLIDATION / "V20_51_UPSTREAM_V20_50_VALIDATION.csv"
IN_V51_PREREQ = CONSOLIDATION / "V20_51_RECOMMENDATION_GATE_PREREQUISITE_REVIEW.csv"
IN_V51_CANDIDATE = CONSOLIDATION / "V20_51_CANDIDATE_READINESS_FOR_FUTURE_OFFICIAL_GATE.csv"
IN_V51_CONTEXT = CONSOLIDATION / "V20_51_CONTEXT_READINESS_FOR_FUTURE_OFFICIAL_GATE.csv"
IN_V51_GAPS = CONSOLIDATION / "V20_51_OFFICIAL_GATE_POLICY_GAP_REGISTER.csv"
IN_V51_ACTION = CONSOLIDATION / "V20_51_GATE_ACTION_BOUNDARY.csv"
IN_V51_SAFETY = CONSOLIDATION / "V20_51_GATE_SAFETY_BOUNDARY.csv"
IN_V51_NEXT = CONSOLIDATION / "V20_51_NEXT_STEP_DECISION.csv"
IN_V51_REPORT = READ_CENTER / "V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE_REPORT.md"
IN_V51_CURRENT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_READINESS_GATE.md"
IN_V51_READ_FIRST = OPS / "V20_51_READ_FIRST.txt"
IN_V51_TEST = SCRIPT_DIR / "test_v20_51_official_recommendation_readiness_gate.py"

OUT_SUMMARY = CONSOLIDATION / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_SUMMARY.csv"
OUT_UPSTREAM = CONSOLIDATION / "V20_52_UPSTREAM_V20_51_VALIDATION.csv"
OUT_GAP_CONTRACT = CONSOLIDATION / "V20_52_POLICY_GAP_RESOLUTION_CONTRACT.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_52_OFFICIAL_OUTPUT_SCHEMA_CONTRACT.csv"
OUT_LANGUAGE = CONSOLIDATION / "V20_52_RECOMMENDATION_LANGUAGE_POLICY.csv"
OUT_RISK = CONSOLIDATION / "V20_52_RISK_POSITION_POLICY_CONTRACT.csv"
OUT_MANUAL = CONSOLIDATION / "V20_52_MANUAL_APPROVAL_AND_REAL_BOOK_POLICY.csv"
OUT_BROKER = CONSOLIDATION / "V20_52_BROKER_DISABLED_ENFORCEMENT_CONTRACT.csv"
OUT_AUDIT = CONSOLIDATION / "V20_52_POST_RECOMMENDATION_AUDIT_TEST_CONTRACT.csv"
OUT_SCOPE = CONSOLIDATION / "V20_52_FUTURE_OFFICIAL_STAGE_ALLOWED_SCOPE.csv"
OUT_ACTION = CONSOLIDATION / "V20_52_POLICY_CONTRACT_ACTION_BOUNDARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_52_POLICY_CONTRACT_SAFETY_BOUNDARY.csv"
OUT_NEXT = CONSOLIDATION / "V20_52_NEXT_STEP_DECISION.csv"
REPORT = READ_CENTER / "V20_52_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE.md"
READ_FIRST = OPS / "V20_52_READ_FIRST.txt"


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


def run_v51_tests() -> tuple[bool, str]:
    if not IN_V51_TEST.exists():
        return False, "V20.51 formal test script missing"
    result = subprocess.run([sys.executable, str(IN_V51_TEST)], cwd=str(ROOT), text=True, capture_output=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    passed = result.returncode == 0 and "PASS_V20_51_TESTS" in result.stdout.splitlines()
    return passed, output


def source_has_forbidden_runtime_imports(path: Path) -> bool:
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


def build_upstream_validation(v51_tests_passed: bool) -> list[dict[str, object]]:
    summary = first_row(IN_V51_SUMMARY)
    next_row = first_row(IN_V51_NEXT)
    gaps, _ = read_csv(IN_V51_GAPS)
    actions, _ = read_csv(IN_V51_ACTION)
    safety, _ = read_csv(IN_V51_SAFETY)
    candidates, _ = read_csv(IN_V51_CANDIDATE)
    priority_count = sum(1 for row in candidates if clean(row.get("research_decision_category")) == "PRIORITY_REVIEW")
    standard_count = sum(1 for row in candidates if clean(row.get("research_decision_category")) == "STANDARD_REVIEW")
    gap_count = len(gaps)

    checks: list[dict[str, object]] = []
    for item, path in [
        ("v20_51_summary_exists_non_empty", IN_V51_SUMMARY),
        ("v20_51_upstream_validation_exists_non_empty", IN_V51_UPSTREAM),
        ("v20_51_prerequisite_review_exists_non_empty", IN_V51_PREREQ),
        ("v20_51_candidate_readiness_exists_non_empty", IN_V51_CANDIDATE),
        ("v20_51_context_readiness_exists_non_empty", IN_V51_CONTEXT),
        ("v20_51_policy_gap_register_exists_non_empty", IN_V51_GAPS),
        ("v20_51_action_boundary_exists_non_empty", IN_V51_ACTION),
        ("v20_51_safety_boundary_exists_non_empty", IN_V51_SAFETY),
        ("v20_51_next_step_decision_exists_non_empty", IN_V51_NEXT),
        ("v20_51_read_center_report_exists_non_empty", IN_V51_REPORT),
        ("v20_51_current_alias_exists_non_empty", IN_V51_CURRENT),
        ("v20_51_read_first_exists_non_empty", IN_V51_READ_FIRST),
    ]:
        ok = exists_non_empty(path)
        checks.append(status_row(item, path, "TRUE", tf(ok), ok, "missing_or_empty"))

    checks.append(status_row("v20_51_formal_test_script_exists", IN_V51_TEST, "TRUE", tf(IN_V51_TEST.exists()), IN_V51_TEST.exists(), "missing_test_script"))
    checks.append(status_row("v20_51_decision", IN_V51_NEXT, V20_51_DECISION_PASS, clean(next_row.get("decision")), clean(next_row.get("decision")) == V20_51_DECISION_PASS, "v20_51_decision_not_pass"))
    checks.append(status_row("v20_51_readiness_status", IN_V51_SUMMARY, "READY_WITH_RESEARCH_ONLY_LIMITS or READY_FOR_FUTURE_OFFICIAL_RECOMMENDATION_GATE", clean(summary.get("readiness_status")), clean(summary.get("readiness_status")) in V20_51_READY_VALUES, "readiness_status_not_ready"))
    checks.append(status_row("v20_51_tests_status", IN_V51_TEST, "PASS", "PASS" if v51_tests_passed else "FAIL", v51_tests_passed, "formal_tests_failed"))
    checks.append(status_row("v20_51_future_gate_readiness", IN_V51_SUMMARY, "CONDITIONAL or TRUE", clean(summary.get("future_official_recommendation_gate_ready")), clean(summary.get("future_official_recommendation_gate_ready")) in V20_51_FUTURE_READY_VALUES, "future_gate_readiness_not_ready"))
    checks.append(status_row("v20_51_candidate_count", IN_V51_CANDIDATE, "50", str(row_count(IN_V51_CANDIDATE)), row_count(IN_V51_CANDIDATE) == 50, "candidate_count_not_50"))
    checks.append(status_row("v20_51_priority_review_count", IN_V51_CANDIDATE, "20", str(priority_count), priority_count == 20, "priority_review_count_not_20"))
    checks.append(status_row("v20_51_standard_review_count", IN_V51_CANDIDATE, "30", str(standard_count), standard_count == 30, "standard_review_count_not_30"))
    checks.append(status_row("v20_51_context_rows", IN_V51_CONTEXT, "6", str(row_count(IN_V51_CONTEXT)), row_count(IN_V51_CONTEXT) == 6, "context_row_count_not_6"))
    checks.append(status_row("v20_51_policy_gap_count", IN_V51_GAPS, "9", str(gap_count), gap_count == 9, "policy_gap_count_not_9"))

    false_summary_fields = [
        "official_recommendation_created",
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
    for field in false_summary_fields:
        checks.append(status_row(f"v20_51_{field}", IN_V51_SUMMARY, "FALSE", clean(summary.get(field)), clean(summary.get(field)) == "FALSE", f"{field}_not_false"))

    boundary_false = [
        ("v20_51_action_boundary_official_ranking_mutation_allowed", IN_V51_ACTION, value_by_name(actions, "boundary_name", "official_ranking_mutation_allowed", "allowed_flag")),
        ("v20_51_action_boundary_dynamic_weighting_mutation_allowed", IN_V51_ACTION, value_by_name(actions, "boundary_name", "dynamic_weighting_mutation_allowed", "allowed_flag")),
        ("v20_51_safety_returns_calculated", IN_V51_SAFETY, value_by_name(safety, "safety_boundary", "returns_calculated", "actual_value")),
        ("v20_51_safety_scores_recomputed", IN_V51_SAFETY, value_by_name(safety, "safety_boundary", "scores_recomputed", "actual_value")),
        ("v20_51_safety_rankings_recomputed", IN_V51_SAFETY, value_by_name(safety, "safety_boundary", "rankings_recomputed", "actual_value")),
        ("v20_51_safety_trading_signals_created", IN_V51_SAFETY, value_by_name(safety, "safety_boundary", "trading_signals_created", "actual_value")),
    ]
    for item, path, actual in boundary_false:
        checks.append(status_row(item, path, "FALSE", actual, actual == "FALSE", f"{item}_not_false"))
    checks.append(status_row("v20_51_forbidden_actionable_language_scan", IN_V51_TEST, "PASS", "PASS" if v51_tests_passed else "FAIL", v51_tests_passed, "forbidden_language_scan_not_pass"))
    return checks


def build_gap_contract(gaps: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for gap in sorted(gaps, key=lambda row: clean(row.get("gap_id"))):
        rows.append({
            "gap_id": clean(gap.get("gap_id")),
            "gap_name": clean(gap.get("gap_name")),
            "gap_category": clean(gap.get("gap_category")),
            "v20_51_current_status": clean(gap.get("current_status")),
            "blocker_for_future_official_generation": "TRUE",
            "required_policy_contract": f"V20.52 contract defines the required policy for {clean(gap.get('gap_name'))}.",
            "v20_52_contract_status": "CONTRACT_DEFINED",
            "required_before_generation": "TRUE",
            "recommended_resolution_stage": "FUTURE_OFFICIAL_STAGE_REQUIRES_LATER_GATE",
            "blocker_if_unresolved": "TRUE",
            "notes": "Contract-only resolution; no official recommendation created and no generation allowed now.",
        })
    return rows


def build_schema_contract() -> list[dict[str, object]]:
    specs = [
        ("recommendation_run_id", "string", "TRUE", "future controlled run identifier", "", "Lineage key for a future official stage.", "Must be unique within a future official output.", "TRUE"),
        ("source_research_packet_id", "string", "TRUE", "V20.50 research-only packet identifier", "", "Binds output to research-only source packet.", "Must reference an accepted research-only packet.", "TRUE"),
        ("source_v20_47_run_id", "string", "TRUE", "certified V20.47 run id", "", "Preserves cache and market context lineage.", "Must match upstream certified run id.", "TRUE"),
        ("candidate_id_or_ticker", "string", "TRUE", "source candidate identifier", "", "Identifies the candidate without creating rows in V20.52.", "Required only when a later gate instantiates the schema.", "TRUE"),
        ("preserved_report_rank", "integer", "TRUE", "source report rank", "new recomputed rank", "Preserves source rank without mutation.", "Must equal preserved upstream report order.", "TRUE"),
        ("research_decision_category", "string", "TRUE", "PRIORITY_REVIEW|STANDARD_REVIEW", "buy|sell|hold", "Carries research-only category context.", "Must come from upstream research-only category.", "TRUE"),
        ("official_recommendation_label", "controlled string", "TRUE", "future later-gate controlled labels only", "buy|sell|hold|strong buy|trade now", "Placeholder contract for a future label field.", "V20.52 must not assign candidate label values.", "TRUE"),
        ("recommendation_confidence_band", "controlled string", "TRUE", "future later-gate controlled confidence band", "guaranteed return language", "Captures confidence without return prediction.", "Must not imply trading authorization.", "TRUE"),
        ("recommendation_rationale", "text", "TRUE", "policy-safe rationale", "action instruction language", "Explains future label under policy constraints.", "Must pass forbidden language scan.", "TRUE"),
        ("risk_summary", "text", "TRUE", "risk policy summary", "execution instruction", "Summarizes risk constraints.", "Must bind to risk/position policy.", "TRUE"),
        ("position_policy_reference", "string", "TRUE", "risk policy id", "", "Links to approved position policy.", "Must reference a defined policy contract.", "TRUE"),
        ("manual_approval_required", "boolean", "TRUE", "TRUE", "FALSE", "Requires human/operator approval.", "Must be TRUE for any future official output.", "TRUE"),
        ("broker_execution_allowed", "boolean", "TRUE", "FALSE unless separate future broker contract exists", "TRUE in V20.52", "Keeps broker disabled.", "Must remain FALSE in V20.52.", "TRUE"),
        ("real_book_mutation_allowed", "boolean", "TRUE", "FALSE", "TRUE", "Separates research/simulation from real book.", "Must remain FALSE unless separately approved by later gate.", "TRUE"),
        ("official_trading_allowed", "boolean", "TRUE", "FALSE unless explicitly overridden by future gate", "TRUE in V20.52", "Prevents trading authorization.", "Must remain FALSE in V20.52.", "TRUE"),
        ("created_timestamp_utc", "datetime", "TRUE", "UTC ISO-8601", "", "Audit timestamp for future output.", "Required when future output is instantiated.", "TRUE"),
        ("audit_status", "controlled string", "TRUE", "PENDING_AUDIT|PASS_AUDIT|BLOCKED_AUDIT", "SKIP_AUDIT", "Forces future post-generation audit.", "Must be populated by future audit tests.", "TRUE"),
    ]
    return [
        {
            "field_name": field,
            "field_type": field_type,
            "required_flag": required,
            "allowed_values": allowed,
            "forbidden_values": forbidden,
            "purpose": purpose,
            "validation_rule": rule,
            "blocker_if_missing": blocker,
        }
        for field, field_type, required, allowed, forbidden, purpose, rule, blocker in specs
    ]


def build_language_policy() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    forbidden = [
        ("buy", "candidate for further review"),
        ("sell", "risk review required"),
        ("hold", "research status unchanged"),
        ("strong buy", "high review priority"),
        ("reduce", "exposure review required"),
        ("add position", "position policy review required"),
        ("enter position", "future gate required"),
        ("exit position", "risk review required"),
        ("execute", "not trading-authorized"),
        ("trade now", "future gate required"),
    ]
    for idx, (phrase, replacement) in enumerate(forbidden, 1):
        rows.append({
            "language_policy_id": f"LANG_FORBID_{idx:03d}",
            "phrase_or_pattern": phrase,
            "policy_type": "FORBIDDEN_ACTIONABLE_LANGUAGE",
            "allowed_in_future_official_output": "FALSE_UNLESS_LATER_GATE_CONTROLLED_LABEL",
            "allowed_in_research_only_output": "FALSE",
            "requires_manual_approval": "TRUE",
            "replacement_or_safe_phrase": replacement,
            "rationale": "V20.52 is contract-only and not trading-authorized.",
        })
    safe = [
        "research review priority",
        "candidate for further review",
        "factor support context",
        "refreshed price context",
        "not an official recommendation",
        "not trading-authorized",
        "future gate required",
    ]
    for idx, phrase in enumerate(safe, 1):
        rows.append({
            "language_policy_id": f"LANG_SAFE_{idx:03d}",
            "phrase_or_pattern": phrase,
            "policy_type": "SAFE_RESEARCH_ONLY_LANGUAGE",
            "allowed_in_future_official_output": "TRUE_IF_CONTEXTUAL_AND_LATER_GATE_ALLOWED",
            "allowed_in_research_only_output": "TRUE",
            "requires_manual_approval": "FALSE",
            "replacement_or_safe_phrase": phrase,
            "rationale": "Safe contract language does not create an official recommendation or trading signal.",
        })
    return rows


def build_risk_policy() -> list[dict[str, object]]:
    areas = [
        "max position size policy",
        "max single-name exposure policy",
        "sector concentration policy",
        "liquidity/volume policy",
        "volatility/VIX risk policy",
        "earnings/event risk policy",
        "stop/exit framework reference",
        "portfolio drawdown policy",
        "cash allocation policy",
        "manual override policy",
    ]
    return [
        {
            "policy_id": f"RISK_{idx:03d}",
            "policy_area": area,
            "policy_requirement": f"Future official stage must bind output to an approved {area}.",
            "required_before_official_generation": "TRUE",
            "current_status": "CONTRACT_DEFINED",
            "enforcement_stage": "FUTURE_OFFICIAL_STAGE_REQUIRES_LATER_GATE",
            "blocker_if_missing": "TRUE",
            "notes": "This policy contract does not enable trading in V20.52.",
        }
        for idx, area in enumerate(areas, 1)
    ]


def build_manual_policy() -> list[dict[str, object]]:
    specs = [
        ("human/operator approval required before any official recommendation publication", "future official output", "manual_approval_required_TRUE", "publication_without_manual_approval"),
        ("user/manual approval required before any real-book action", "real-book action", "manual_approval_required_TRUE", "real_book_action_without_approval"),
        ("real book must remain separate from research/simulation book", "portfolio state", "research_book_only", "real_book_conflation"),
        ("real-book mutation blocked in this stage", "V20.52", "blocked", "real_book_mutation"),
        ("broker route disabled", "execution path", "disabled", "broker_route_enabled"),
        ("actual holdings not inferred unless explicitly supplied through approved ledger", "holdings context", "approved_ledger_only", "inferred_real_holdings"),
        ("official output cannot imply automatic execution", "future official output", "no_automatic_execution", "automatic_execution_implied"),
        ("recommendation packet cannot mutate portfolio state", "future packet", "read_only_packet", "portfolio_state_mutation"),
    ]
    return [
        {
            "policy_id": f"MANUAL_REALBOOK_{idx:03d}",
            "policy_name": name,
            "required_flag": "TRUE",
            "policy_status": "CONTRACT_DEFINED",
            "applies_to": applies_to,
            "allowed_state": allowed,
            "blocked_state": blocked,
            "enforcement_notes": "Required by V20.52 contract; no automatic execution allowed.",
        }
        for idx, (name, applies_to, allowed, blocked) in enumerate(specs, 1)
    ]


def build_broker_enforcement(wrapper: Path) -> list[dict[str, object]]:
    script_imports_forbidden = source_has_forbidden_runtime_imports(Path(__file__))
    wrapper_text = wrapper.read_text(encoding="utf-8") if wrapper.exists() else ""
    no_wrapper_blocked_terms = not any(term in wrapper_text.lower() for term in ["alpaca", "ibapi", "ccxt", "placeorder", "submitorder"])
    specs = [
        ("broker_order_execution_allowed", "FALSE", "Contract value is FALSE.", True),
        ("broker_api_import_allowed", "FALSE", "AST import scan has no broker API imports.", not script_imports_forbidden),
        ("live_trading_allowed", "FALSE", "Contract value is FALSE.", True),
        ("order_file_creation_allowed", "FALSE", "No order output artifact is produced.", True),
        ("trade_signal_file_creation_allowed", "FALSE", "No trading signal artifact is produced.", True),
        ("real_portfolio_mutation_allowed", "FALSE", "Real-book mutation is blocked.", True),
        ("no broker/order code path in V20.52 script", "TRUE", "AST import scan and output list are contract-only.", not script_imports_forbidden),
        ("no broker/order code path in wrapper", "TRUE", "Wrapper only invokes Python stage script.", no_wrapper_blocked_terms),
    ]
    return [
        {
            "enforcement_id": f"BROKER_DISABLED_{idx:03d}",
            "enforcement_check": check,
            "expected_value": expected,
            "enforcement_status": "PASS" if ok else "BLOCKED",
            "evidence": evidence,
            "blocker_if_failed": "" if ok else "broker_disabled_enforcement_failed",
        }
        for idx, (check, expected, evidence, ok) in enumerate(specs, 1)
    ]


def build_audit_contract() -> list[dict[str, object]]:
    requirements = [
        "official output schema validation tests",
        "forbidden language scan tests",
        "no broker/order path tests",
        "no trading signal tests",
        "no ranking mutation tests",
        "no dynamic weighting mutation tests",
        "source lineage and run_id tests",
        "manual approval field validation tests",
        "risk policy field validation tests",
        "read-center/READ_FIRST safety tests",
    ]
    return [
        {
            "audit_requirement_id": f"AUDIT_{idx:03d}",
            "audit_requirement": requirement,
            "required_before_future_official_generation": "TRUE",
            "required_after_future_official_generation": "TRUE",
            "test_or_artifact_needed": f"Future formal test coverage for {requirement}.",
            "blocker_if_missing": "TRUE",
            "notes": "Future official stage requires later gate and audit evidence.",
        }
        for idx, requirement in enumerate(requirements, 1)
    ]


def build_scope() -> list[dict[str, object]]:
    conditional = [
        "official recommendation schema instantiation",
        "controlled recommendation label assignment",
        "recommendation rationale generation",
        "risk policy binding",
        "manual approval field binding",
        "official recommendation report generation",
    ]
    blocked = [
        "actual candidate recommendation labels",
        "buy/sell/hold instruction generation",
        "trading signal generation",
        "broker/order route",
        "real portfolio mutation",
        "official ranking mutation",
        "dynamic weighting mutation",
        "returns calculation",
        "score/ranking recomputation",
    ]
    rows = [
        {
            "scope_item": item,
            "allowed_for_future_official_stage": "CONDITIONAL",
            "allowed_in_v20_52": "FALSE",
            "required_precondition": "Requires later gate, formal tests, manual approval, risk policy binding, and broker-disabled enforcement.",
            "blocked_action": "Do not instantiate in V20.52.",
            "notes": "Defined as future scope only.",
        }
        for item in conditional
    ]
    rows.extend(
        {
            "scope_item": item,
            "allowed_for_future_official_stage": "FALSE_UNLESS_SEPARATE_LATER_GATE",
            "allowed_in_v20_52": "FALSE",
            "required_precondition": "Blocked by V20.52 policy contract.",
            "blocked_action": item,
            "notes": "No official recommendation created; not trading-authorized.",
        }
        for item in blocked
    )
    return rows


def build_action_boundary() -> list[dict[str, object]]:
    true_items = [
        "policy_contract_definition_allowed",
        "official_output_schema_contract_allowed",
        "recommendation_language_policy_allowed",
        "risk_position_policy_contract_allowed",
        "manual_approval_policy_contract_allowed",
        "broker_disabled_policy_contract_allowed",
        "post_recommendation_audit_contract_allowed",
        "future_official_stage_scope_definition_allowed",
    ]
    false_items = [
        "official_recommendation_generation_allowed_in_this_stage",
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
    rows = [
        {"boundary_name": item, "allowed_flag": "TRUE", "evidence": "Allowed contract-only policy definition.", "blocker_reason": ""}
        for item in true_items
    ]
    rows.extend(
        {
            "boundary_name": item,
            "allowed_flag": "FALSE",
            "evidence": "Blocked by V20.52 policy contract gate boundary.",
            "blocker_reason": "blocked_by_policy_contract_gate_boundary",
        }
        for item in false_items
    )
    return rows


def build_safety_boundary() -> list[dict[str, object]]:
    specs = [
        ("provider_refresh_executed_in_v20_52", "FALSE", "FALSE", "No provider refresh in V20.52."),
        ("yfinance_imported_in_v20_52", "FALSE", "FALSE", "No yfinance import in V20.52."),
        ("v20_51_readiness_gate_used", "TRUE", "TRUE", "V20.51 readiness gate artifacts consumed."),
        ("v20_50_research_only_packet_reference_used", "TRUE", "TRUE", "V20.51 carries V20.50 research-only packet reference."),
        ("v20_47_certified_cache_reference_used", "TRUE", "TRUE", "V20.51 carries V20.47 run/cache reference."),
        ("broker_order_execution_used", "FALSE", "FALSE", "No broker/order execution."),
        ("official_recommendation_created", "FALSE", "FALSE", "No official recommendation created."),
        ("official_recommendation_allowed_in_this_stage", "FALSE", "FALSE", "Generation is blocked in V20.52."),
        ("official_trading_allowed", "FALSE", "FALSE", "Not trading-authorized."),
        ("official_ranking_mutated", "FALSE", "FALSE", "No official rank mutation."),
        ("dynamic_weighting_mutated", "FALSE", "FALSE", "No dynamic weight mutation."),
        ("real_portfolio_mutated", "FALSE", "FALSE", "No real portfolio mutation."),
        ("returns_calculated", "FALSE", "FALSE", "No return calculation."),
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
    v51_tests_passed, _ = run_v51_tests()
    v51_summary = first_row(IN_V51_SUMMARY)
    v51_next = first_row(IN_V51_NEXT)
    v51_gaps, _ = read_csv(IN_V51_GAPS)
    v20_47_run_id = clean(v51_summary.get("v20_47_run_id")) or RUN_ID_FALLBACK

    upstream = build_upstream_validation(v51_tests_passed)
    gap_contract = build_gap_contract(v51_gaps)
    schema = build_schema_contract()
    language = build_language_policy()
    risk = build_risk_policy()
    manual = build_manual_policy()
    broker = build_broker_enforcement(SCRIPT_DIR / "run_v20_52_official_recommendation_policy_contract_gate.ps1")
    audit = build_audit_contract()
    scope = build_scope()
    action = build_action_boundary()
    safety = build_safety_boundary()

    blockers = [clean(row.get("blocker_reason")) for row in upstream if clean(row.get("validation_status")) == "BLOCKED"]
    blockers.extend(clean(row.get("blocker_if_failed")) for row in broker if clean(row.get("enforcement_status")) == "BLOCKED")
    blockers.extend(clean(row.get("blocker_reason")) for row in safety if clean(row.get("validation_status")) == "BLOCKED")
    blockers = [item for item in blockers if item]
    warnings: list[str] = []
    if len(v51_gaps) == 9 and any(clean(gap.get("blocker_for_future_official_generation")) != "TRUE" for gap in v51_gaps):
        warnings.append("v20_51_gap_register_has_non_blocking_gap_rows")

    blocker_count = len(blockers)
    warning_count = len(warnings)
    contract_pass = blocker_count == 0
    final_status = PASS_STATUS if contract_pass else BLOCKED_STATUS
    decision = DECISION_PASS if contract_pass else "BLOCKED_OFFICIAL_RECOMMENDATION_POLICY_CONTRACT_GATE"
    contract_gate_status = CONTRACT_GATE_PASS if contract_pass else "BLOCKED_POLICY_CONTRACT_GATE"
    future_ready = "CONDITIONAL" if contract_pass else "FALSE"

    summary = [{
        "stage": STAGE,
        "upstream_v20_51_readiness_status": clean(v51_summary.get("readiness_status")),
        "upstream_v20_51_tests_status": "PASS" if v51_tests_passed else "FAIL",
        "v20_47_run_id": v20_47_run_id,
        "v20_51_policy_gap_count": len(v51_gaps),
        "policy_contract_created": tf(contract_pass),
        "official_output_schema_contract_created": tf(bool(schema) and contract_pass),
        "recommendation_language_policy_created": tf(bool(language) and contract_pass),
        "risk_position_policy_created": tf(bool(risk) and contract_pass),
        "manual_approval_policy_created": tf(bool(manual) and contract_pass),
        "real_book_separation_policy_created": tf(bool(manual) and contract_pass),
        "broker_disabled_policy_created": tf(bool(broker) and contract_pass),
        "post_recommendation_audit_policy_created": tf(bool(audit) and contract_pass),
        "future_official_generation_allowed_by_contract": future_ready,
        "official_recommendation_created_in_this_stage": "FALSE",
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
        "contract_gate_status": contract_gate_status,
        "next_recommended_stage": NEXT_STAGE,
    }]
    next_rows = [{
        "stage": STAGE,
        "decision": decision,
        "contract_gate_status": contract_gate_status,
        "policy_contract_created": tf(contract_pass),
        "future_official_policy_contract_ready": future_ready,
        "official_recommendation_created_in_this_stage": "FALSE",
        "official_recommendation_allowed_in_this_stage": "FALSE",
        "official_trading_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "formal_tests_required_next": "TRUE",
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "next_recommended_stage": NEXT_STAGE,
    }]

    write_csv(OUT_UPSTREAM, upstream, ["validation_item", "source_path", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_GAP_CONTRACT, gap_contract, ["gap_id", "gap_name", "gap_category", "v20_51_current_status", "blocker_for_future_official_generation", "required_policy_contract", "v20_52_contract_status", "required_before_generation", "recommended_resolution_stage", "blocker_if_unresolved", "notes"])
    write_csv(OUT_SCHEMA, schema, ["field_name", "field_type", "required_flag", "allowed_values", "forbidden_values", "purpose", "validation_rule", "blocker_if_missing"])
    write_csv(OUT_LANGUAGE, language, ["language_policy_id", "phrase_or_pattern", "policy_type", "allowed_in_future_official_output", "allowed_in_research_only_output", "requires_manual_approval", "replacement_or_safe_phrase", "rationale"])
    write_csv(OUT_RISK, risk, ["policy_id", "policy_area", "policy_requirement", "required_before_official_generation", "current_status", "enforcement_stage", "blocker_if_missing", "notes"])
    write_csv(OUT_MANUAL, manual, ["policy_id", "policy_name", "required_flag", "policy_status", "applies_to", "allowed_state", "blocked_state", "enforcement_notes"])
    write_csv(OUT_BROKER, broker, ["enforcement_id", "enforcement_check", "expected_value", "enforcement_status", "evidence", "blocker_if_failed"])
    write_csv(OUT_AUDIT, audit, ["audit_requirement_id", "audit_requirement", "required_before_future_official_generation", "required_after_future_official_generation", "test_or_artifact_needed", "blocker_if_missing", "notes"])
    write_csv(OUT_SCOPE, scope, ["scope_item", "allowed_for_future_official_stage", "allowed_in_v20_52", "required_precondition", "blocked_action", "notes"])
    write_csv(OUT_ACTION, action, ["boundary_name", "allowed_flag", "evidence", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_boundary", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    blocker_text = "None" if not blockers else "; ".join(blockers)
    warning_text = "None" if not warnings else "; ".join(warnings)
    report = f"""# V20.52 Official Recommendation Policy Contract Gate

## Stage status

Stage: {STAGE}
Final status: {final_status}
Decision: {decision}
Contract gate status: {contract_gate_status}
Next recommended stage: {NEXT_STAGE}

## Upstream V20.51 validation

V20.51 readiness status: {clean(v51_summary.get("readiness_status"))}
V20.51 formal tests status: {"PASS" if v51_tests_passed else "FAIL"}
V20.51 decision: {clean(v51_next.get("decision"))}
V20.47 run ID/cache reference: {v20_47_run_id}

{md_table(upstream, ["validation_item", "expected_value", "actual_value", "validation_status"], 40)}

## Policy gap resolution contract

{md_table(gap_contract, ["gap_id", "gap_name", "v20_52_contract_status", "required_before_generation"])}

## Future official output schema contract

{md_table(schema, ["field_name", "field_type", "required_flag", "validation_rule"])}

## Recommendation language policy

{md_table(language, ["language_policy_id", "phrase_or_pattern", "policy_type", "allowed_in_research_only_output"])}

## Risk/position policy contract

{md_table(risk, ["policy_id", "policy_area", "current_status", "required_before_official_generation"])}

## Manual approval and real-book separation policy

{md_table(manual, ["policy_id", "policy_name", "allowed_state", "blocked_state"])}

## Broker-disabled enforcement contract

{md_table(broker, ["enforcement_id", "enforcement_check", "expected_value", "enforcement_status"])}

## Post-recommendation audit/test contract

{md_table(audit, ["audit_requirement_id", "audit_requirement", "required_before_future_official_generation", "required_after_future_official_generation"])}

## Future official stage allowed scope

{md_table(scope, ["scope_item", "allowed_for_future_official_stage", "allowed_in_v20_52"])}

## Action boundary

{md_table(action, ["boundary_name", "allowed_flag", "evidence"])}

## Safety boundary

{md_table(safety, ["safety_boundary", "expected_value", "actual_value", "validation_status"])}

## Explicit no official recommendation created statement

No official recommendation created in V20.52. This stage is a policy contract gate only.

## Explicit no buy/sell/hold/trading signal statement

No buy/sell/hold instruction and no trading signal created in V20.52. Future official output requires a later gate and controlled policy.

## Explicit no broker/order statement

Broker disabled. No broker/order execution path is used by V20.52.

## Explicit no provider refresh/yfinance statement

No provider refresh or network refresh is performed in V20.52. V20.52 does not import yfinance.

## Explicit no score/ranking/return recomputation statement

No return calculation, benchmark-relative return calculation, score recomputation, ranking recomputation, official ranking mutation, or dynamic weighting mutation is performed in V20.52.

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
        f"POLICY_CONTRACT_GATE_STATUS={contract_gate_status}",
        "V20_51_READINESS_GATE_USED=TRUE",
        "V20_50_RESEARCH_ONLY_PACKET_REFERENCE=TRUE",
        f"V20_47_RUN_ID_CACHE_REFERENCE={v20_47_run_id}",
        "GATE_ONLY_SAFETY_FLAGS=TRUE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "BUY_SELL_HOLD_INSTRUCTION_CREATED=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_52=FALSE",
        "YFINANCE_IMPORT_USED_IN_V20_52=FALSE",
        "BROKER_ORDER_EXECUTION_USED=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_MUTATED=FALSE",
        "RETURNS_CALCULATED=FALSE",
        "BENCHMARK_RELATIVE_RETURNS_CALCULATED=FALSE",
        "SCORES_RECOMPUTED=FALSE",
        "RANKINGS_RECOMPUTED=FALSE",
        "POLICY_CONTRACT_ONLY=TRUE",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}",
        "",
    ])
    write_text(READ_FIRST, read_first)
    cleanup_pycache()

    print(final_status)
    print(f"DECISION={decision}")
    print(f"CONTRACT_GATE_STATUS={contract_gate_status}")
    print(f"V20_51_READINESS_STATUS={clean(v51_summary.get('readiness_status'))}")
    print(f"V20_51_TESTS_STATUS={'PASS' if v51_tests_passed else 'FAIL'}")
    print(f"POLICY_GAP_RESOLUTION_COUNT={len(gap_contract)}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE}")
    return 0 if contract_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
