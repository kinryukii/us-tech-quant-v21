from __future__ import annotations

import ast
import csv
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

PASS_STATUS = "PASS_V20_55_TESTS"
STAGE = "V20.55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
EXPECTED_WRAPPER_STATUS = "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
WARN_WRAPPER_STATUS = "WARN_V20_55_RESEARCH_ONLY_READY_PROMOTION_BLOCKED"
BLOCKED_WRAPPER_STATUS = "BLOCKED_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
NEXT_STAGE = "V20.55_FORMAL_TESTS"
RUN_ID_PATTERN = re.compile(r"V20_47_\d{8}T\d{6}Z")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

PRODUCTION = SCRIPT_DIR / "v20_55_daily_one_click_research_runner.py"
WRAPPER = SCRIPT_DIR / "run_v20_55_daily_one_click_research_runner.ps1"

OUT_SUMMARY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_RUN_SUMMARY.csv"
OUT_LOG = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_STAGE_EXECUTION_LOG.csv"
OUT_ARTIFACT_CHECK = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_REQUIRED_ARTIFACT_CHECK.csv"
OUT_INVENTORY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_OUTPUT_INVENTORY.csv"
OUT_STATIC_CONTRACT = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_STATIC_CONTRACT_CHECK.csv"
OUT_POLICY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_POLICY_LANGUAGE_BOUNDARY_CHECK.csv"
OUT_SAFETY = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_SAFETY_BOUNDARY_VALIDATION.csv"
OUT_NEXT = CONSOLIDATION / "V20_55_DAILY_ONE_CLICK_NEXT_STEP_DECISION.csv"
OUT_REFRESH_DIAGNOSTICS = CONSOLIDATION / "V20_CURRENT_MARKET_REFRESH_DIAGNOSTICS.csv"
OUT_V20_16_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
OUT_V20_16_DIAGNOSTICS = CONSOLIDATION / "V20_16_GATE_DECISION_DIAGNOSTICS.csv"
OUT_V20_17_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
OUT_V20_17_DIAGNOSTICS = CONSOLIDATION / "V20_17_GATE_DECISION_DIAGNOSTICS.csv"
REPORT = READ_CENTER / "V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md"
CONCLUSION = READ_CENTER / "V20_CURRENT_DAILY_CONCLUSION.md"
READ_FIRST = OPS / "V20_55_READ_FIRST.txt"
FINAL_V20_54_REPORT = READ_CENTER / "V20_54_USER_READABLE_CURRENT_DECISION_REPORT.md"
FINAL_V20_54_CURRENT_REPORT = READ_CENTER / "V20_CURRENT_USER_READABLE_CURRENT_DECISION_REPORT.md"
V49_SUMMARY = CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv"
V49_RESEARCH_GATE = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_PROMOTION_GATE = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V49_LINEAGE = CONSOLIDATION / "V20_49_OPERATOR_LINEAGE_REVIEW_READINESS.csv"
V50_SUMMARY = CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv"
V50_LINEAGE = CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv"

IN_V47_SUMMARY = CONSOLIDATION / "V20_47_CONTROLLED_REFRESH_SUMMARY.csv"
IN_V47_CACHE_HASH_LEDGER = CONSOLIDATION / "V20_47_CACHE_HASH_LEDGER.csv"

RUN_ID_SOURCE_FILES = [
    OUT_LOG,
    CONSOLIDATION / "V20_48_REFRESHED_OPERATOR_REPORT_SUMMARY.csv",
    CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv",
    CONSOLIDATION / "V20_48_REFRESHED_BENCHMARK_CONTEXT_VIEW.csv",
    CONSOLIDATION / "V20_48_REFRESHED_LINEAGE_FRESHNESS_VIEW.csv",
    CONSOLIDATION / "V20_49_OPERATOR_REVIEW_ACCEPTANCE_SUMMARY.csv",
    CONSOLIDATION / "V20_49_OPERATOR_CANDIDATE_REVIEW_READINESS.csv",
    CONSOLIDATION / "V20_49_OPERATOR_BENCHMARK_REVIEW_READINESS.csv",
    CONSOLIDATION / "V20_49_OPERATOR_LINEAGE_REVIEW_READINESS.csv",
    CONSOLIDATION / "V20_50_RESEARCH_ONLY_DECISION_PACKET_SUMMARY.csv",
    CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv",
    CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv",
    CONSOLIDATION / "V20_50_LINEAGE_RESEARCH_CONTEXT_PACKET.csv",
    CONSOLIDATION / "V20_54_USER_READABLE_REPORT_SUMMARY.csv",
    CONSOLIDATION / "V20_54_USER_READABLE_CANDIDATE_VIEW.csv",
    CONSOLIDATION / "V20_54_LINEAGE_FRESHNESS_READABLE_VIEW.csv",
]

REQUIRED_FILES = [
    OUT_SUMMARY,
    OUT_LOG,
    OUT_ARTIFACT_CHECK,
    OUT_INVENTORY,
    OUT_STATIC_CONTRACT,
    OUT_POLICY,
    OUT_SAFETY,
    OUT_NEXT,
    OUT_REFRESH_DIAGNOSTICS,
    REPORT,
    CURRENT_REPORT,
    CONCLUSION,
    READ_FIRST,
    FINAL_V20_54_CURRENT_REPORT,
]

SUMMARY_COLUMNS = {
    "stage_id",
    "stage_name",
    "run_id",
    "run_timestamp_utc",
    "overall_status",
    "daily_sequence_started",
    "daily_sequence_completed",
    "stages_attempted",
    "stages_passed",
    "stages_warned",
    "stages_blocked",
    "stages_failed",
    "current_market_refresh_stage_used",
    "refreshed_report_stage_used",
    "operator_acceptance_stage_used",
    "decision_packet_stage_used",
    "user_readable_report_stage_used",
    "static_policy_contracts_validated",
    "final_user_readable_report_path",
    "final_current_alias_report_path",
    "no_broker_action",
    "no_order_execution",
    "no_official_recommendation",
    "no_trading_signal",
    "manual_review_required",
    "research_only_daily_conclusion_ready",
    "official_promotion_blocked",
    "next_recommended_stage",
}

EXPECTED_STAGES = {
    "V20.47_CONTROLLED_CURRENT_MARKET_REFRESH_AND_CACHE_CERTIFICATION",
    "V20_POST_REFRESH_RECOMPUTE_HANDOFF",
    "V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT",
    "V20.49_OPERATOR_REVIEW_ACCEPTANCE_GATE",
    "V20.50_RESEARCH_ONLY_DECISION_PACKET",
    "V20.54_USER_READABLE_CURRENT_DECISION_REPORT",
}

SAFETY_CHECKS = {
    "orchestrator only",
    "provider refresh only through approved V20.47 wrapper",
    "no direct yfinance import in V20.55",
    "no direct provider/network call in V20.55",
    "no broker/order execution path",
    "no official recommendation generation",
    "no buy/sell/hold instruction generation",
    "no trading signal generation",
    "no returns calculation in V20.55",
    "no score/ranking recomputation in V20.55",
    "no ranking/weight mutation",
    "no dynamic weighting mutation",
    "no real-book position mutation",
    "no outputs/v21",
    "no outputs/v19_21",
    "no outputs/v19/V19_21",
    "final output remains research-only",
    "manual review required",
}

REPORT_SECTIONS = [
    "stage status",
    "daily run sequence",
    "stage execution results",
    "current market refresh result",
    "post-refresh recompute",
    "refreshed operator report result",
    "operator review acceptance result",
    "research-only decision packet result",
    "user-readable report result",
    "static policy/schema contract validation",
    "final report location",
    "artifact inventory summary",
    "policy/language boundary",
    "safety boundary",
    "what this one-click runner is allowed to do",
    "what this one-click runner is not allowed to do",
    "recommended next gated stage",
]

RUN_ID_COLUMNS = {
    "run_id",
    "upstream_run_id",
    "v20_47_run_id",
    "current_market_refresh_run_id",
    "cache_run_id",
    "refresh_run_id",
    "source_run_id",
    "lineage_run_id",
    "upstream_v20_47_run_id",
    "v20_48_upstream_run_id",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def truthy(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "PASS", "YES", "1"}


def falsey(value: object) -> bool:
    return clean(value).upper() in {"FALSE", "NO", "0", ""}


def as_int(value: object) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return -1


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def assert_columns(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    rows, columns = read_csv(path)
    missing = sorted(required - set(columns))
    assert_true(not missing, f"{path.name} missing required columns: {missing}")
    assert_true(rows, f"{path.name} must be non-empty")
    return rows, columns


def by_key(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {clean(row.get(key)): row for row in rows}


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def resolve_artifact(value: object) -> Path:
    text = clean(value).replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        return path
    return ROOT / path


def current_overall_status() -> str:
    if not OUT_SUMMARY.exists():
        return ""
    rows, _ = read_csv(OUT_SUMMARY)
    return clean(rows[0].get("overall_status")) if rows else ""


def row_has_fail(row: dict[str, str]) -> bool:
    joined = ",".join(clean(value).upper() for value in row.values())
    return "BLOCKED" in joined or "FAIL" in joined


def run_ids_from_rows(rows: list[dict[str, str]], columns: list[str]) -> set[str]:
    ids: set[str] = set()
    lower_to_actual = {column.lower(): column for column in columns}
    for wanted in RUN_ID_COLUMNS:
        actual = lower_to_actual.get(wanted.lower())
        if actual:
            for row in rows:
                value = clean(row.get(actual))
                if value:
                    assert_true(RUN_ID_PATTERN.fullmatch(value) is not None, f"Invalid V20.47 run_id in {actual}: {value}")
                    ids.add(value)
    if ids:
        return ids
    for row in rows:
        for value in row.values():
            ids.update(RUN_ID_PATTERN.findall(clean(value)))
    return ids


def discover_active_v20_47_run_id() -> str:
    found: dict[str, set[str]] = {}
    for path in RUN_ID_SOURCE_FILES:
        if not path.exists():
            continue
        rows, columns = read_csv(path)
        ids = run_ids_from_rows(rows, columns)
        if ids:
            found[path.name] = ids
    assert_true(found, "No active V20.47 run_id discovered from V20.55/V20.48/V20.49/V20.50/V20.54 artifacts")
    all_ids = set().union(*found.values())
    assert_true(len(all_ids) == 1, f"Inconsistent active V20.47 run_ids across final artifacts: {found}")
    run_id = next(iter(all_ids))

    artifact_ids: dict[str, set[str]] = {}
    for path in [IN_V47_SUMMARY, IN_V47_CACHE_HASH_LEDGER]:
        rows, columns = assert_columns(path, {"run_id"})
        artifact_ids[path.name] = run_ids_from_rows(rows, columns)
    assert_true(any(run_id in ids for ids in artifact_ids.values()), f"Run id {run_id} not found in V20.47 summary/cache ledger: {artifact_ids}")
    return run_id


def test_required_outputs_and_production_files() -> None:
    required = list(REQUIRED_FILES) + [PRODUCTION, WRAPPER]
    required.extend([OUT_V20_16_GATE, OUT_V20_16_DIAGNOSTICS, OUT_V20_17_GATE, OUT_V20_17_DIAGNOSTICS])
    if current_overall_status() == BLOCKED_WRAPPER_STATUS:
        required = [path for path in required if path != FINAL_V20_54_CURRENT_REPORT]
    missing = [str(path) for path in required if not path.exists()]
    assert_true(not missing, f"Missing required files: {missing}")
    empty = [str(path) for path in required if path.stat().st_size <= 0]
    assert_true(not empty, f"Empty required files: {empty}")


def test_production_and_wrapper_syntax() -> None:
    compile(PRODUCTION.read_text(encoding="utf-8"), str(PRODUCTION), "exec")
    command = (
        "$parseErrors = $null; "
        "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
        f"'{WRAPPER.as_posix()}'), [ref]$parseErrors); "
        "if ($parseErrors) { $parseErrors; exit 1 }; 'PARSE_OK'"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert_true(result.returncode == 0 and "PARSE_OK" in result.stdout, f"Wrapper parse failed: {result.stdout} {result.stderr}")


def test_run_summary() -> None:
    rows, _ = assert_columns(OUT_SUMMARY, SUMMARY_COLUMNS)
    assert_true(len(rows) == 1, f"Summary expected 1 row, got {len(rows)}")
    row = rows[0]
    assert_true(clean(row.get("stage_name")) == STAGE, "Summary stage_name mismatch")
    overall = clean(row.get("overall_status"))
    assert_true(overall in {EXPECTED_WRAPPER_STATUS, WARN_WRAPPER_STATUS, BLOCKED_WRAPPER_STATUS}, f"Unexpected overall_status {overall}")
    for key in [
        "daily_sequence_started",
        "current_market_refresh_stage_used",
        "no_broker_action",
        "no_order_execution",
        "no_official_recommendation",
        "no_trading_signal",
        "manual_review_required",
    ]:
        assert_true(truthy(row.get(key)), f"Summary {key} expected TRUE-like")
    if overall in {EXPECTED_WRAPPER_STATUS, WARN_WRAPPER_STATUS}:
        expected_counts = {"stages_attempted": 6, "stages_blocked": 0, "stages_failed": 0}
        for key, expected in expected_counts.items():
            assert_true(as_int(row.get(key)) == expected, f"Summary {key} expected {expected}, got {row.get(key)}")
        assert_true(as_int(row.get("stages_passed")) + as_int(row.get("stages_warned")) == 6, "PASS/WARN summary must account for all stages")
        assert_true(truthy(row.get("daily_sequence_completed")), "Summary daily_sequence_completed expected TRUE-like")
        assert_true(truthy(row.get("refreshed_report_stage_used")), "Summary refreshed_report_stage_used expected TRUE-like")
        assert_true(truthy(row.get("operator_acceptance_stage_used")), "Summary operator_acceptance_stage_used expected TRUE-like")
        assert_true(truthy(row.get("decision_packet_stage_used")), "Summary decision_packet_stage_used expected TRUE-like")
        assert_true(truthy(row.get("user_readable_report_stage_used")), "Summary user_readable_report_stage_used expected TRUE-like")
        if overall == EXPECTED_WRAPPER_STATUS:
            assert_true(truthy(row.get("static_policy_contracts_validated")), "Summary static_policy_contracts_validated expected TRUE-like")
        else:
            assert_true(truthy(row.get("research_only_daily_conclusion_ready")), "WARN summary must mark research-only ready")
            assert_true(truthy(row.get("official_promotion_blocked")), "WARN summary must preserve promotion blocker")
        assert_true(resolve_artifact(row.get("final_user_readable_report_path")).exists(), "Final V20.54 report path missing")
        assert_true(resolve_artifact(row.get("final_current_alias_report_path")).exists(), "Final V20.54 current alias path missing")
    else:
        assert_true(as_int(row.get("stages_attempted")) >= 1, "Blocked summary must attempt at least one stage")
        assert_true(as_int(row.get("stages_blocked")) >= 1 or as_int(row.get("stages_failed")) >= 1, "Blocked summary must record a blocked/failed stage")
    assert_true(clean(row.get("next_recommended_stage")) == NEXT_STAGE, "Unexpected next recommended stage")


def test_stage_execution_log() -> None:
    rows, _ = assert_columns(OUT_LOG, {
        "execution_order",
        "upstream_stage",
        "wrapper_path",
        "started_at_utc",
        "ended_at_utc",
        "elapsed_seconds",
        "return_code",
        "detected_status",
        "status_classification",
        "required_outputs_checked",
        "required_outputs_present",
        "required_outputs_non_empty",
        "stop_after_stage",
    })
    by_stage = by_key(rows, "upstream_stage")
    missing = sorted(EXPECTED_STAGES - set(by_stage))
    assert_true(not missing, f"Stage log missing expected stages: {missing}")
    assert_true(len(rows) == 6, f"Final V20.55 stage log expected 6 rows, got {len(rows)}")
    for stage in EXPECTED_STAGES:
        row = by_stage[stage]
        assert_true(clean(row.get("status_classification")) == "PASS", f"{stage} not PASS")
        assert_true(clean(row.get("detected_status")).startswith("PASS_"), f"{stage} detected_status not PASS-like")
        assert_true(as_int(row.get("return_code")) == 0, f"{stage} return_code not zero")
        assert_true(as_int(row.get("required_outputs_checked")) == as_int(row.get("required_outputs_present")), f"{stage} required outputs not all present")
        assert_true(as_int(row.get("required_outputs_checked")) == as_int(row.get("required_outputs_non_empty")), f"{stage} required outputs not all non-empty")
        assert_true(falsey(row.get("stop_after_stage")), f"{stage} stop_after_stage expected false/empty")
        assert_true("BLOCKED" not in clean(row.get("detected_status")).upper(), f"{stage} detected BLOCKED")
        assert_true("FAIL" not in clean(row.get("detected_status")).upper(), f"{stage} detected FAIL")


def test_required_artifact_check() -> None:
    rows, _ = assert_columns(OUT_ARTIFACT_CHECK, {"artifact_stage", "artifact_path", "exists", "non_empty", "validation_status", "blocker_reason"})
    represented = {clean(row.get("artifact_stage")) for row in rows}
    for stage in EXPECTED_STAGES:
        assert_true(stage in represented, f"Artifact check missing stage {stage}")
    for row in rows:
        assert_true(truthy(row.get("exists")), f"Artifact missing: {row.get('artifact_path')}")
        assert_true(truthy(row.get("non_empty")), f"Artifact empty: {row.get('artifact_path')}")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Artifact check not PASS: {row}")
        assert_true(not clean(row.get("blocker_reason")), f"Artifact blocker present: {row}")


def test_static_contract_check() -> None:
    rows, _ = assert_columns(OUT_STATIC_CONTRACT, {"artifact_stage", "artifact_path", "exists", "non_empty", "validation_status", "blocker_reason"})
    text = "\n".join(clean(row.get("artifact_path")) for row in rows).lower()
    assert_true("v20_52" in text, "Static contract check missing V20.52 policy contract artifacts")
    assert_true("v20_53" in text, "Static contract check missing V20.53 schema dry-run artifacts")
    assert_true("v20_54" in text, "Static contract check missing V20.54 test/report contract artifacts")
    for row in rows:
        assert_true(truthy(row.get("exists")), f"Static contract missing: {row.get('artifact_path')}")
        assert_true(truthy(row.get("non_empty")), f"Static contract empty: {row.get('artifact_path')}")
        assert_true(clean(row.get("validation_status")) == "PASS", f"Static contract not PASS: {row}")
        assert_true(not clean(row.get("blocker_reason")), f"Static contract blocker present: {row}")


def test_output_inventory() -> None:
    rows, _ = assert_columns(OUT_INVENTORY, {"artifact_path", "artifact_stage", "exists", "non_empty", "size_bytes", "modified_at_utc", "sha256", "artifact_role", "notes"})
    paths = {clean(row.get("artifact_path")): row for row in rows}
    for expected in [rel(FINAL_V20_54_REPORT), rel(REPORT)]:
        assert_true(expected in paths, f"Inventory missing {expected}")
    for row in rows:
        if truthy(row.get("exists")):
            assert_true(truthy(row.get("non_empty")), f"Inventory artifact empty: {row.get('artifact_path')}")
            assert_true(as_int(row.get("size_bytes")) > 0, f"Inventory artifact has non-positive size: {row.get('artifact_path')}")
            assert_true(SHA256_PATTERN.fullmatch(clean(row.get("sha256"))) is not None, f"Invalid sha256 for {row.get('artifact_path')}")
            assert_true(resolve_artifact(row.get("artifact_path")).exists(), f"Inventory path does not exist: {row.get('artifact_path')}")


ALLOWED_FORBIDDEN_CONTEXTS = [
    re.compile(r"\bnot (?:an? )?(?:official recommendation|trading signal)\b", re.IGNORECASE),
    re.compile(r"\bno (?:official recommendation|trading signal|order execution|broker action|broker/order execution)\b", re.IGNORECASE),
    re.compile(r"\bdoes not (?:create|connect|execute|mutate|import|implement)\b", re.IGNORECASE),
    re.compile(r"\bcreated\s*=\s*false\b", re.IGNORECASE),
    re.compile(r"\ballowed\s*=\s*false\b", re.IGNORECASE),
    re.compile(r"\bexecuted\s*=\s*false\b", re.IGNORECASE),
    re.compile(r"\bnot_a_trading_signal|no_order_execution|no_broker_action\b", re.IGNORECASE),
    re.compile(r"\bno buy/sell/hold instruction", re.IGNORECASE),
    re.compile(r"\bbuy_sell_hold_instructions_created\s*,?\s*false\b", re.IGNORECASE),
    re.compile(r"\bthis_is_not_an_official_recommendation_generator\b", re.IGNORECASE),
    re.compile(r"\bthis_is_not_a_trading_signal_generator\b", re.IGNORECASE),
    re.compile(r"\breport order\b|\bordering\b", re.IGNORECASE),
]

FORBIDDEN_ACTIONABLE_PATTERNS = [
    re.compile(r"\bstrong\s+buy\b", re.IGNORECASE),
    re.compile(r"\bstrong\s+sell\b", re.IGNORECASE),
    re.compile(r"\btrading\s+signal\b", re.IGNORECASE),
    re.compile(r"\bofficial\s+recommendation\b", re.IGNORECASE),
    re.compile(r"\bauto\s+trade\b", re.IGNORECASE),
    re.compile(r"\bposition\s+instruction\b", re.IGNORECASE),
    re.compile(r"\bbuy\b|\bsell\b|\bhold\b|\border\b|\bexecute\b", re.IGNORECASE),
]


def assert_no_actionable_language(path: Path) -> None:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not any(pattern.search(line) for pattern in FORBIDDEN_ACTIONABLE_PATTERNS):
            continue
        if any(pattern.search(line) for pattern in ALLOWED_FORBIDDEN_CONTEXTS):
            continue
        raise AssertionError(f"Forbidden actionable language in {path.name}:{line_no}: {line}")


def test_policy_language_boundary() -> None:
    rows, _ = assert_columns(OUT_POLICY, {"checked_artifact", "forbidden_actionable_phrase_count", "research_only_language_confirmed", "validation_status", "blocker_reason"})
    for row in rows:
        assert_true(clean(row.get("validation_status")) == "PASS", f"Policy boundary not PASS: {row}")
        assert_true(not row_has_fail(row), f"Policy boundary contains BLOCKED/FAIL: {row}")
    for path in [REPORT, CURRENT_REPORT, READ_FIRST, OUT_SUMMARY, OUT_LOG, OUT_ARTIFACT_CHECK, OUT_INVENTORY, OUT_STATIC_CONTRACT, OUT_POLICY, OUT_SAFETY, OUT_NEXT, FINAL_V20_54_REPORT]:
        assert_no_actionable_language(path)


def test_safety_boundary() -> None:
    rows, _ = assert_columns(OUT_SAFETY, {"safety_check", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"})
    safety = by_key(rows, "safety_check")
    missing = sorted(SAFETY_CHECKS - set(safety))
    assert_true(not missing, f"Safety boundary missing rows: {missing}")
    for name in SAFETY_CHECKS:
        row = safety[name]
        assert_true(clean(row.get("validation_status")) == "PASS", f"{name} did not PASS")
        assert_true(clean(row.get("expected_value")) == clean(row.get("actual_value")), f"{name} expected/actual mismatch")
        assert_true(not clean(row.get("blocker_reason")), f"{name} has blocker reason")


def test_report_alias_and_read_first() -> None:
    primary = REPORT.read_text(encoding="utf-8")
    alias = CURRENT_REPORT.read_text(encoding="utf-8")
    lower = primary.lower()
    for section in REPORT_SECTIONS:
        assert_true(section in lower, f"Report missing section: {section}")
    assert_true(STAGE in primary and (EXPECTED_WRAPPER_STATUS in primary or WARN_WRAPPER_STATUS in primary or BLOCKED_WRAPPER_STATUS in primary), "Primary report missing stage/status")
    assert_true(alias == primary, "V20_CURRENT_DAILY_ONE_CLICK_RESEARCH_RUNNER_REPORT.md must exactly match primary V20.55 report")
    conclusion = CONCLUSION.read_text(encoding="utf-8").lower()
    for phrase in [
        "executive status",
        "data freshness / market source",
        "market refresh diagnostics",
        "current ranking",
        "technical timing / buy-zone",
        "manual additions",
        "research conclusion",
        "remaining blockers",
        "safety",
        "final_chain_status",
        "v20_55_status",
        "v20.7v status",
        "active_market_source_staging_usable:",
        "eligible_row_count:",
        "excluded_row_count:",
        "excluded ticker examples:",
        "v20_7v_used_quarantine:",
        "v20.16 gate decision",
        "v20.16 status",
        "v20.16 consumed current v20.7v outputs",
        "v20.17 gate decision",
        "v20.17 status",
        "v20.17 prepared candidate input rows",
        "v20.17 outcome rows available",
        "provider/cache refresh status:",
        "post-refresh recompute",
        "post_refresh_recompute_ran:",
        "dominant failure reason:",
        "stale-data blocker remains:",
        "research-only",
        "no broker execution",
        "no official recommendation",
        "no trade action",
        "no official ranking mutation",
        "no factor weight mutation",
    ]:
        assert_true(phrase in conclusion, f"Daily conclusion missing phrase: {phrase}")
    if "v20.7v status: pass_v20_7v_active_market_source_staging_ready" in conclusion:
        assert_true("daily_conclusion_mode: degraded_research_only_due_to_stale_market_data" not in conclusion, "Daily conclusion must not use stale-data degraded mode when V20.7V passes")
        assert_true("daily_conclusion_mode: research_only_daily_conclusion_ready_official_promotion_blocked" in conclusion, "Daily conclusion missing corrected research-only promotion-blocked mode")
    research_gate_rows, _ = assert_columns(V49_RESEARCH_GATE, {"research_only_gate_status", "active_candidate_rows_available", "factor_rows_available", "prepared_candidate_input_rows", "benchmark_rows_available"})
    promotion_gate_rows, _ = assert_columns(V49_PROMOTION_GATE, {"official_promotion_gate_status", "acceptance_status", "missing_promotion_lineage_sources", "official_recommendation_allowed", "trade_action_allowed", "weight_mutation_allowed"})
    assert_true(clean(research_gate_rows[0].get("research_only_gate_status")) == "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE", "V20.49 research-only gate must pass")
    assert_true(clean(promotion_gate_rows[0].get("official_promotion_gate_status")) == "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE", "V20.49 official promotion gate must remain blocked")
    assert_true(clean(promotion_gate_rows[0].get("acceptance_status")) == "BLOCKED_OPERATOR_REVIEW_ACCEPTANCE", "Operator acceptance must remain blocked")
    assert_true("V20.35-R2" in clean(promotion_gate_rows[0].get("missing_promotion_lineage_sources")), "Missing promotion lineage must be preserved")
    v7v_rows, _ = assert_columns(CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv", {"status", "active_source_staging_candidate_ready", "eligible_row_count", "excluded_row_count"})
    excluded_rows, _ = assert_columns(CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv", {"ticker", "exclusion_reason", "supporting_reason"})
    staging_rows, _ = assert_columns(CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv", {"ticker", "latest_price_date", "composite_candidate_score"})
    v7v = v7v_rows[0]
    staging_tickers = {clean(row.get("ticker")).upper() for row in staging_rows}
    excluded_by_ticker = {clean(row.get("ticker")).upper(): row for row in excluded_rows}
    assert_true("BITF" in excluded_by_ticker, "BITF must be in V20.7V excluded tickers while provider refresh failed")
    assert_true("TQQQ" in excluded_by_ticker, "TQQQ must be in V20.7V excluded tickers while insufficient-history scoring is unavailable")
    assert_true("BITF" not in staging_tickers and "TQQQ" not in staging_tickers, "Excluded tickers must not be present in active staging")
    assert_true(all(clean(row.get("composite_candidate_score")) for row in staging_rows), "Active staging must not contain missing composite_candidate_score")
    if clean(v7v.get("status")) == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY":
        assert_true(clean(v7v.get("active_source_staging_candidate_ready")) == "TRUE", "V20.7V PASS must use eligible rows only")
        assert_true(clean(v7v.get("v20_7v_used_quarantine")) == "TRUE", "V20.7V PASS with exclusions must report quarantine")
    v16_rows, _ = assert_columns(OUT_V20_16_GATE, {"v20_16_gate_decision", "consumed_v20_7v_status", "consumed_current_v20_7v_outputs", "excluded_rows_allowed_by_v20_16"})
    assert_true(clean(v16_rows[0].get("consumed_v20_7v_status")) == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "V20.16 must consume current V20.7V PASS status")
    assert_true(clean(v16_rows[0].get("consumed_current_v20_7v_outputs")) == "TRUE", "V20.16 must not consume stale pre-quarantine V20.7V outputs")
    assert_true(clean(v16_rows[0].get("excluded_rows_allowed_by_v20_16")) == "TRUE", "V20.16 must allow audited V20.7V exclusions within threshold")
    v17_rows, _ = assert_columns(OUT_V20_17_GATE, {"v20_17_gate_decision", "consumed_v20_16_status", "consumed_v20_7v_status", "prepared_candidate_input_rows", "prepared_benchmark_rows", "outcome_rows_available"})
    assert_true(clean(v17_rows[0].get("consumed_v20_16_status")) == "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE", "V20.17 must consume current V20.16 PASS")
    assert_true(clean(v17_rows[0].get("consumed_v20_7v_status")) == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY", "V20.17 must consume current V20.7V PASS")
    assert_true(as_int(v17_rows[0].get("prepared_candidate_input_rows")) > 0, "V20.17 must prepare candidate inputs")
    assert_true(as_int(v17_rows[0].get("prepared_benchmark_rows")) >= 2, "V20.17 must prepare benchmark anchors")
    assert_true(clean(v17_rows[0].get("outcome_rows_available")) == "0", "V20.17 must not fake outcome rows")
    refresh_rows, _ = assert_columns(OUT_REFRESH_DIAGNOSTICS, {
        "v20_47_script_exists",
        "v20_47_wrapper_exists",
        "latest_v20_47_status",
        "expected_downstream_artifact_for_v20_55",
        "expected_downstream_artifact_exists",
        "price_cache_latest_date",
        "price_cache_ticker_count",
        "stale_price_cache_ticker_count",
        "v20_46_readiness_status",
        "v20_46_candidate_ticker_count",
        "v20_47_requested_ticker_count",
        "v20_47_attempted_ticker_count",
        "v20_47_success_count",
        "v20_47_empty_dataframe_count",
        "v20_47_exception_count",
        "provider_available",
        "dominant_failure_reason",
        "provider_diagnostics_path",
        "post_refresh_recompute_status",
        "post_refresh_ran",
        "pre_refresh_cache_latest_date_distribution",
        "post_refresh_cache_latest_date_distribution",
        "post_refresh_full_ranked_latest_price_date_distribution",
        "v18_factor_pack_recomputed_after_v20_47",
        "v18_technical_timing_recomputed_after_v20_47",
        "v18_13b_rerun_after_v20_47",
        "v18_full_ranked_rebuilt_after_v20_47",
        "v20_7v_used_post_refresh_artifacts",
        "eligible_row_count",
        "excluded_row_count",
        "excluded_ticker_examples",
        "v20_7v_used_quarantine",
        "recommended_next_action",
    })
    refresh = refresh_rows[0]
    assert_true(clean(refresh.get("v20_47_script_exists")) == "TRUE", "V20.47 script should exist")
    assert_true(clean(refresh.get("v20_47_wrapper_exists")) == "TRUE", "V20.47 wrapper should exist")
    assert_true(clean(refresh.get("latest_v20_47_status")) != "", "V20.47 latest status should be diagnosed")
    assert_true(clean(refresh.get("recommended_next_action")) != "", "Refresh diagnostics must include recommended next action")
    assert_true(as_int(refresh.get("v20_47_requested_ticker_count")) > 0, "V20.47 requested ticker count must be diagnosed")
    assert_true(as_int(refresh.get("v20_47_attempted_ticker_count")) >= 0, "V20.47 attempted ticker count must be numeric")
    provider_diag_path = resolve_artifact(refresh.get("provider_diagnostics_path"))
    if clean(refresh.get("provider_diagnostics_path")):
        assert_true(provider_diag_path.exists(), "Provider diagnostics path in refresh diagnostics must exist")
    assert_true((CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_AUDIT.csv").exists(), "Post-refresh recompute audit must exist")
    assert_true((CONSOLIDATION / "V20_POST_REFRESH_RECOMPUTE_STATUS.csv").exists(), "Post-refresh recompute status must exist")
    if clean(refresh.get("latest_v20_47_status")) == "CERTIFIED_FOR_RESEARCH_REPORT_HANDOFF":
        assert_true(clean(refresh.get("post_refresh_ran")) == "TRUE", "Post-refresh recompute must run after certified V20.47")
        assert_true(clean(refresh.get("v18_factor_pack_recomputed_after_v20_47")) in {"TRUE", "FALSE"}, "Factor recompute flag must be explicit")
    alias_lower = alias.lower()
    for section in ["stage status", "daily run sequence", "stage execution results", "recommended next gated stage"]:
        assert_true(section in alias_lower, f"Alias missing core section: {section}")

    read_first = READ_FIRST.read_text(encoding="utf-8").lower()
    required = [
        "daily_one_click_research_only_runner=true",
        "orchestrates_approved_v20_stages=true",
        "market_refresh_allowed_only_through_approved_v20_47_wrapper=true",
        "v20_55_direct_yfinance_import_used=false",
        "v20_55_direct_provider_network_refresh_logic_used=false",
        "this_is_not_an_official_recommendation_generator=true",
        "this_is_not_a_trading_signal_generator=true",
        "buy_sell_hold_instructions_created=false",
        "broker_order_system_connected=false",
        "trades_executed=false",
        "rankings_scores_factor_weights_dynamic_weights_real_book_mutated=false",
        "final_report_for_manual_review_only=true",
    ]
    for phrase in required:
        assert_true(phrase in read_first, f"READ_FIRST missing statement: {phrase}")


def test_active_v20_47_run_id_dynamic_validation() -> None:
    run_id = discover_active_v20_47_run_id()
    final_text = FINAL_V20_54_CURRENT_REPORT.read_text(encoding="utf-8")
    assert_true(run_id in final_text, f"Current user-readable report does not reference active V20.47 run_id {run_id}")
    v54_rows, _ = assert_columns(CONSOLIDATION / "V20_54_USER_READABLE_REPORT_SUMMARY.csv", {"v20_47_run_id"})
    assert_true(clean(v54_rows[0].get("v20_47_run_id")) == run_id, "V20.54 summary run_id does not match active V20.47 run_id")


def test_lineage_contract_v49_v50() -> None:
    v49_rows, _ = assert_columns(V49_SUMMARY, {
        "lineage_rows_available",
        "expected_lineage_row_policy",
        "minimum_required_lineage_rows",
        "actual_lineage_rows_available",
        "lineage_row_count_validation_status",
        "duplicate_lineage_rows",
        "malformed_lineage_rows",
        "stale_lineage_rows",
        "missing_required_lineage_sources",
        "blocker_count",
    })
    v50_rows, _ = assert_columns(V50_SUMMARY, {
        "lineage_rows_included",
        "expected_lineage_row_policy",
        "minimum_required_lineage_rows",
        "actual_lineage_rows_available",
        "lineage_row_count_validation_status",
        "duplicate_lineage_rows",
        "malformed_lineage_rows",
        "stale_lineage_rows",
        "blocker_count",
    })
    for label, row, count_key in [("V20.49", v49_rows[0], "lineage_rows_available"), ("V20.50", v50_rows[0], "lineage_rows_included")]:
        minimum = as_int(row.get("minimum_required_lineage_rows"))
        actual = as_int(row.get("actual_lineage_rows_available"))
        row_count = as_int(row.get(count_key))
        assert_true(minimum >= 35, f"{label} minimum lineage row policy should be at least 35")
        assert_true(row_count >= minimum and actual >= minimum, f"{label} lineage rows below minimum")
        assert_true(clean(row.get("lineage_row_count_validation_status")) == "PASS", f"{label} lineage policy did not PASS")
        assert_true(clean(row.get("duplicate_lineage_rows")) == "0", f"{label} duplicate lineage rows not zero")
        assert_true(clean(row.get("malformed_lineage_rows")) == "0", f"{label} malformed lineage rows not zero")
        assert_true(clean(row.get("stale_lineage_rows")) == "0", f"{label} stale lineage rows not zero")
        assert_true(as_int(row.get("blocker_count")) == 0, f"{label} blocker count not zero")
        assert_true("minimum" in clean(row.get("expected_lineage_row_policy")).lower(), f"{label} lineage policy is not contract-based")
    assert_true(clean(v49_rows[0].get("missing_required_lineage_sources")) == "", "V20.49 required source coverage did not pass")

    for path in [V49_LINEAGE, V50_LINEAGE]:
        rows, _ = assert_columns(path, {"source_name_or_input_name", "source_contract_or_version", "safe_for_research_report", "safe_for_trading", "blocker_count"})
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (clean(row.get("source_name_or_input_name")), clean(row.get("source_contract_or_version")))
            assert_true(key not in seen, f"Duplicate lineage key in {path.name}: {key}")
            seen.add(key)
            assert_true(all(key), f"Malformed lineage key in {path.name}: {row}")
            assert_true(clean(row.get("safe_for_research_report")) == "TRUE", f"Lineage row not safe for research in {path.name}: {row}")
            assert_true(clean(row.get("safe_for_trading")) == "FALSE", f"Lineage row safe for trading in {path.name}: {row}")
            assert_true(as_int(row.get("blocker_count")) == 0, f"Lineage row blocker count not zero in {path.name}: {row}")


def call_names(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id.lower())
            elif isinstance(func, ast.Attribute):
                names.add(func.attr.lower())
                if isinstance(func.value, ast.Name):
                    names.add(f"{func.value.id.lower()}.{func.attr.lower()}")
    return names


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0].lower())
    return modules


def test_static_safety_scan() -> None:
    test_script = SCRIPT_DIR / "test_v20_55_daily_one_click_research_runner.py"
    forbidden_imports = {"yfinance", "requests", "urllib", "httpx"}
    forbidden_calls = {
        "submit_order",
        "place_order",
        "create_order",
        "buy_order",
        "sell_order",
        "buy",
        "sell",
        "order",
        "execute",
    }
    for path in [PRODUCTION, test_script]:
        imports = imported_modules(path)
        bad_imports = forbidden_imports & imports
        assert_true(not bad_imports, f"Forbidden imports in {path.name}: {bad_imports}")
        calls = call_names(path)
        bad_calls = forbidden_calls & calls
        assert_true(not bad_calls, f"Forbidden executable calls in {path.name}: {bad_calls}")

    wrapper_text = WRAPPER.read_text(encoding="utf-8", errors="ignore")
    forbidden_wrapper_patterns = [
        re.compile(r"^\s*(import|from)\s+yfinance\b", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\b(?:submit_order|place_order|create_order|buy_order|sell_order)\b", re.IGNORECASE),
        re.compile(r"\brequests\b|\burllib\b|\bhttpx\b", re.IGNORECASE),
    ]
    for pattern in forbidden_wrapper_patterns:
        assert_true(pattern.search(wrapper_text) is None, f"Forbidden wrapper executable/provider path: {pattern.pattern}")


def test_forbidden_output_paths() -> None:
    forbidden_paths = [ROOT / "outputs" / "v21", ROOT / "outputs" / "v19_21", ROOT / "outputs" / "v19" / "V19_21"]
    existing = [str(path) for path in forbidden_paths if path.exists()]
    assert_true(not existing, f"Forbidden output paths exist: {existing}")

    for path in [PRODUCTION, WRAPPER, SCRIPT_DIR / "test_v20_55_daily_one_click_research_runner.py"]:
        text = path.read_text(encoding="utf-8", errors="ignore").replace("\\", "/")
        for forbidden in ["outputs/v21", "outputs/v19_21", "outputs/v19/V19_21"]:
            if forbidden not in text:
                continue
            lines = [line for line in text.splitlines() if forbidden in line]
            unsafe = [line for line in lines if "forbidden" not in line.lower() and "safety" not in line.lower() and "no " not in line.lower()]
            assert_true(not unsafe, f"Forbidden output path appears as possible write target in {path.name}: {unsafe}")


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def test_pycache_hygiene() -> None:
    cleanup_pycache()
    remaining = [str(path) for path in SCRIPT_DIR.rglob("__pycache__") if path.is_dir()]
    assert_true(not remaining, f"__pycache__ remains under scripts/v20: {remaining}")


def main() -> int:
    overall = current_overall_status()
    tests = [
        test_required_outputs_and_production_files,
        test_production_and_wrapper_syntax,
        test_run_summary,
        test_safety_boundary,
        test_report_alias_and_read_first,
        test_static_safety_scan,
        test_forbidden_output_paths,
        test_pycache_hygiene,
    ]
    if overall == EXPECTED_WRAPPER_STATUS:
        tests[3:3] = [
            test_stage_execution_log,
            test_required_artifact_check,
            test_static_contract_check,
            test_output_inventory,
            test_policy_language_boundary,
            test_active_v20_47_run_id_dynamic_validation,
            test_lineage_contract_v49_v50,
        ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL_DETAIL: {failure}")
        print("FAIL_V20_55_TESTS")
        return 1
    print(PASS_STATUS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
