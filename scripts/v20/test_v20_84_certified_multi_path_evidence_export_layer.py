from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

STAGE_SCRIPT = SCRIPT_DIR / "v20_84_certified_multi_path_evidence_export_layer.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_84_certified_multi_path_evidence_export_layer.py"
WRAPPER = SCRIPT_DIR / "run_v20_84_certified_multi_path_evidence_export_layer.ps1"

ALLOWED_STATUSES = {
    "PASS_V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT",
    "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS",
    "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
    "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS",
    "BLOCKED_V20_84_NO_USABLE_STRUCTURED_EVIDENCE",
    "BLOCKED_V20_84_UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT_DETECTED",
}
R2_DETAIL = EVIDENCE / "V20_84_R2_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
R2_DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_REQUIRED_PATH_INTEGRATION_DETAIL.csv"
R2_REQUIRED_CATEGORIES = {
    "etf_rotation_evidence",
    "multi_window_strategy_evidence",
    "regime_conditioned_evidence",
    "downside_risk_evidence",
    "benchmark_comparison_evidence",
    "score_lineage_evidence",
    "ranking_delta_diagnostic_evidence",
    "acceptance_proof_evidence",
}
R2_DETAIL_SCHEMA = [
    "integration_category",
    "path_id",
    "required_level",
    "manifest_current_status",
    "expected_source_file",
    "expected_current_alias",
    "bound_source_file",
    "source_status",
    "v20_82_r5_validation_status",
    "attached_row_count",
    "certified_row_count",
    "partial_row_count",
    "blocked_row_count",
    "integration_status",
    "integration_blocker_reason",
    "research_only",
    "official_recommendation_created",
    "official_weight_mutated",
    "trade_action_created",
]
OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
    "audit": CONSOLIDATION / "V20_84_EVIDENCE_INPUT_BINDING_AUDIT.csv",
    "coverage": CONSOLIDATION / "V20_84_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv",
    "report": READ_CENTER / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_REPORT.md",
    "manifest": OPS / "V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json",
}
SCHEMAS = {
    "evidence": [
        "component_name",
        "component_type",
        "evidence_path",
        "source_stage",
        "source_file",
        "source_run_id",
        "metric_name",
        "metric_value",
        "metric_unit",
        "evaluation_window",
        "benchmark_name",
        "benchmark_return",
        "excess_return",
        "drawdown",
        "hit_rate",
        "coverage_status",
        "certification_status",
        "certification_reason",
        "usable_for_v20_82",
        "research_only",
        "official_recommendation_created",
        "official_weight_mutated",
        "trade_action_created",
    ],
    "audit": [
        "input_family",
        "expected_stage",
        "candidate_file",
        "detected_status",
        "row_count",
        "required_or_optional",
        "schema_valid",
        "semantic_valid",
        "usable_evidence_count",
        "binding_quality",
        "reject_reason",
    ],
    "coverage": [
        "component_name",
        "component_type",
        "historical_backtest_found",
        "random_asof_found",
        "live_observation_found",
        "regime_conditioned_found",
        "downside_risk_found",
        "portfolio_backtest_found",
        "benchmark_comparison_found",
        "etf_rotation_found",
        "usable_evidence_count",
        "required_evidence_count",
        "evidence_coverage_ratio",
        "has_any_usable_evidence",
        "v20_82_usable",
        "blocking_reason",
    ],
}
ALLOWED_COMPONENT_TYPES = {
    "FACTOR",
    "ENTRY_STRATEGY",
    "EXIT_STRATEGY",
    "POSITION_SIZING",
    "PORTFOLIO_MODEL",
    "BENCHMARK_MODEL",
    "ETF_ROTATION",
    "LIVE_OBSERVATION",
    "PROMOTION_GATE",
}
ALLOWED_EVIDENCE_PATHS = {
    "HISTORICAL_BACKTEST",
    "RANDOM_ASOF_BACKTEST",
    "LIVE_OBSERVATION",
    "REGIME_CONDITIONED",
    "DOWNSIDE_RISK",
    "PORTFOLIO_BACKTEST",
    "BENCHMARK_COMPARISON",
    "ETF_ROTATION_EVIDENCE",
    "PROMOTION_READINESS",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fields(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_84_", "V20_CURRENT_", 1))


def load_stage_module():
    spec = importlib.util.spec_from_file_location("v20_84_stage_under_test", STAGE_SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "unable to load V20.84 stage module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wrapper_final_status(stdout: str) -> str:
    tokens = re.findall(r"\b(?:PASS|PARTIAL_PASS|BLOCKED)_V20_84_[A-Z0-9_]+\b", stdout)
    return tokens[-1] if tokens else ""


def tracked_v20_47_to_83_production_files() -> list[Path]:
    result = run_command(["git", "ls-files"])
    assert_true(result.returncode == 0, f"git ls-files failed: {result.stdout}\n{result.stderr}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        text = line.strip().replace("\\", "/")
        if text.startswith("scripts/v20/") and any(f"v20_{number}" in text.lower() for number in range(47, 84)):
            paths.append(ROOT / text)
        if text.startswith(("inputs/", "outputs/")) and any(f"V20_{number}" in text.upper() for number in range(47, 84)):
            paths.append(ROOT / text)
    return sorted(paths)


def file_digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths: list[Path]) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        out[rel] = (file_digest(path), path.stat().st_size if path.exists() else -1)
    return out


def test_compile_parser_and_no_hardcoded_run_id() -> None:
    for path in [STAGE_SCRIPT, TEST_SCRIPT]:
        result = run_command([sys.executable, "-m", "py_compile", str(path)])
        assert_true(result.returncode == 0, f"py_compile failed for {path}: {result.stdout}\n{result.stderr}")
    parse = run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_84_certified_multi_path_evidence_export_layer.ps1'), [ref]$null); 'PARSE_OK'",
    ])
    assert_true(parse.returncode == 0 and "PARSE_OK" in parse.stdout, f"PowerShell parser check failed: {parse.stdout}\n{parse.stderr}")
    tree = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
    hardcoded = []
    pattern = re.compile(r"^V20_84_\d{8}T\d{6}Z$")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.match(node.value):
            hardcoded.append(node.value)
    assert_true(not hardcoded, f"hardcoded V20.84 run_id found: {hardcoded}")


def test_integration_run_and_no_old_mutation() -> None:
    tracked = tracked_v20_47_to_83_production_files()
    before = snapshot(tracked)
    result = run_command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    final_status = wrapper_final_status(result.stdout)
    assert_true(final_status in ALLOWED_STATUSES, f"unexpected wrapper status {final_status!r}: {result.stdout}\n{result.stderr}")
    after = snapshot(tracked)
    changed = [path for path, value in before.items() if after.get(path) != value]
    assert_true(not changed, "V20.84 mutated V20.47-V20.83 tracked production files: " + "; ".join(changed[:25]))


def test_outputs_aliases_and_schemas() -> None:
    for key, path in OUTPUTS.items():
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
        alias = alias_path(path)
        assert_true(alias.exists() and alias.stat().st_size > 0, f"missing or empty alias: {alias}")
        assert_true(path.read_bytes() == alias.read_bytes(), f"alias differs: {alias}")
        if path.suffix.lower() == ".csv":
            rows = read_csv(path)
            assert_true(rows, f"CSV has no rows: {path}")
            assert_true(fields(path) == SCHEMAS[key], f"schema mismatch for {path}: {fields(path)}")
    evidence = read_csv(OUTPUTS["evidence"])
    assert_true(all(row["component_type"] in ALLOWED_COMPONENT_TYPES for row in evidence), "invalid component_type emitted")
    assert_true(all(row["evidence_path"] in ALLOWED_EVIDENCE_PATHS for row in evidence), "invalid evidence_path emitted")
    assert_true(R2_DETAIL.exists() and R2_DETAIL.stat().st_size > 0, f"missing or empty R2 detail: {R2_DETAIL}")
    assert_true(R2_DETAIL_ALIAS.exists() and R2_DETAIL_ALIAS.stat().st_size > 0, f"missing or empty R2 detail alias: {R2_DETAIL_ALIAS}")
    assert_true(R2_DETAIL.read_bytes() == R2_DETAIL_ALIAS.read_bytes(), "R2 detail alias differs from versioned output")
    assert_true(fields(R2_DETAIL) == R2_DETAIL_SCHEMA, f"R2 detail schema mismatch: {fields(R2_DETAIL)}")


def test_r2_manifest_driven_integration_detail() -> None:
    detail = read_csv(R2_DETAIL)
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(detail, "R2 detail output empty")
    categories = {row["integration_category"] for row in detail}
    assert_true(R2_REQUIRED_CATEGORIES.issubset(categories), f"missing R2 categories: {sorted(R2_REQUIRED_CATEGORIES - categories)}")
    assert_true(manifest["status"] in {"PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED", "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS"}, f"unexpected R2 manifest status: {manifest['status']}")
    assert_true(manifest.get("v20_89_consumed") is True, f"V20.89 manifest not consumed: {manifest}")
    assert_true(manifest.get("v20_82_r5_consumed") is True, f"V20.82-R5 detail not consumed: {manifest}")
    assert_true(manifest.get("v20_90_consumed") is True, f"V20.90 not consumed: {manifest}")
    assert_true(manifest.get("v20_91_consumed") is True, f"V20.91 not consumed: {manifest}")
    for row in detail:
        assert_true(row["research_only"] == "TRUE", f"R2 row not research-only: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"R2 row created recommendation: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"R2 row mutated weight: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"R2 row created trade action: {row}")
        if row["required_level"] == "OPTIONAL":
            assert_true(row["integration_status"] != "BLOCKED", f"optional/WARN path blocked R2: {row}")
        if row["required_level"] != "OPTIONAL" and row["integration_status"] == "BLOCKED":
            assert_true(row["integration_category"].upper() in row["integration_blocker_reason"], f"required blocker is not category-level: {row}")
    etf = next(row for row in detail if row["integration_category"] == "etf_rotation_evidence")
    assert_true(int(etf["attached_row_count"]) > 0, f"V20.90 ETF rows not attached: {etf}")
    assert_true(int(etf["partial_row_count"]) >= 0, f"bad V20.90 partial count: {etf}")
    if int(etf["partial_row_count"]) > 0:
        assert_true(int(etf["certified_row_count"]) < int(etf["attached_row_count"]), f"V20.90 partial rows treated as fully certified: {etf}")
    multi_window = next(row for row in detail if row["integration_category"] == "multi_window_strategy_evidence")
    assert_true(int(multi_window["certified_row_count"]) > 0, f"V20.91 certified rows not counted: {multi_window}")
    blocked_required = [row for row in detail if row["required_level"] != "OPTIONAL" and row["integration_status"] == "BLOCKED"]
    if manifest["status"].startswith("PARTIAL_PASS_"):
        assert_true(blocked_required, "partial R2 status without required blocked path rows")


def test_r2_notes_only_and_synthetic_rules() -> None:
    stage_module = load_stage_module()
    notes_only = {
        "notes": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
        "certification_reason": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
    }
    assert_true(not stage_module.r2_structured_certified(notes_only), "R2 accepted notes-only certification")
    assert_true(stage_module.r2_structured_certified({"certification_status": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE"}), "R2 rejected structured certification_status")


def test_guardrails_and_certification_contracts() -> None:
    evidence = read_csv(OUTPUTS["evidence"])
    audit = read_csv(OUTPUTS["audit"])
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(manifest["research_only"] is True, "manifest research_only must be true")
    assert_true(manifest["official_recommendation_created"] is False, "official recommendation flag must be false")
    assert_true(manifest["official_weight_mutated"] is False, "official weight mutation flag must be false")
    assert_true(manifest["trade_action_created"] is False, "trade action flag must be false")
    assert_true(all(row["research_only"] == "TRUE" for row in evidence), "evidence rows must be research-only")
    for field in ["official_recommendation_created", "official_weight_mutated", "trade_action_created"]:
        assert_true(all(row[field] == "FALSE" for row in evidence), f"{field} output was not false")
    proxy_rows = [row for row in evidence if row["certification_reason"] == "PROXY_TECHNICAL_RETURN_NOT_CERTIFIED_STRATEGY_ALPHA"]
    assert_true(proxy_rows, "expected proxy technical return rows")
    assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in proxy_rows), "proxy returns must be non-usable")
    etf_not_ready = [
        row for row in evidence
        if row["component_type"] == "ETF_ROTATION" and row["certification_reason"] == "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE"
    ]
    assert_true(etf_not_ready, "expected ETF not-ready/design-only rows")
    assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in etf_not_ready), "ETF not-ready rows must be non-usable")
    generic_rejects = [
        row for row in audit
        if row["reject_reason"] != "NA" and any(token in row["reject_reason"] for token in ["MANIFEST", "CHECKS", "HASH", "REPORT", "DIAGNOSTIC"])
    ]
    assert_true(generic_rejects, "expected rejected generic manifest/check/report/hash/diagnostic inputs")
    assert_true(all(row["usable_evidence_count"] == "0" for row in generic_rejects), "generic rejected inputs counted as usable")


def test_strict_repair_contracts() -> None:
    evidence = read_csv(OUTPUTS["evidence"])
    audit = read_csv(OUTPUTS["audit"])
    coverage = read_csv(OUTPUTS["coverage"])
    v20_82_etf_rows = [
        row for row in evidence
        if row["source_file"].endswith("V20_82_ETF_ROTATION_SHADOW_SIGNAL_TABLE.csv")
    ]
    assert_true(v20_82_etf_rows, "expected V20.82 ETF rows")
    assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in v20_82_etf_rows), "V20.82 design-only ETF rows became usable")
    assert_true(all(row["certification_status"] == "NOT_USABLE" for row in v20_82_etf_rows), "V20.82 design-only ETF rows were certified")
    insufficient_etf_rows = [
        row for row in evidence
        if row["component_type"] == "ETF_ROTATION" and "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE" in row["certification_reason"]
    ]
    assert_true(insufficient_etf_rows, "expected insufficient ETF rows")
    assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in insufficient_etf_rows), "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE matched as certified")
    blocked_readiness = [
        row for row in evidence
        if row["source_file"].endswith(("V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv", "V20_65_PROPOSAL_PROMOTION_READINESS_GATE.csv"))
    ]
    readiness_sources_present = any(CONSOLIDATION.glob("V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv")) or any(CONSOLIDATION.glob("V20_65_PROPOSAL_PROMOTION_READINESS_GATE.csv"))
    if readiness_sources_present:
        assert_true(blocked_readiness, "expected V20.64/V20.65 readiness rows")
        assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in blocked_readiness), "blocked readiness rows became usable")
    count_metrics = [row for row in evidence if row["metric_name"] == "effective_source_run_count"]
    if readiness_sources_present:
        assert_true(count_metrics, "expected effective_source_run_count rows")
        assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in count_metrics), "status/count metrics became usable performance evidence")
    dry_run_zero = [
        row for row in evidence
        if row["source_file"].endswith("V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv") and row["metric_value"] == "0.000000"
    ]
    dry_run_source_present = any(CONSOLIDATION.glob("V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv"))
    if dry_run_source_present:
        assert_true(dry_run_zero, "expected V20.66 dry-run zero delta rows")
        assert_true(all(row["usable_for_v20_82"] == "FALSE" for row in dry_run_zero), "V20.66 dry-run zero deltas became usable")
    zero_ratio_usable = [
        row for row in coverage
        if row["evidence_coverage_ratio"] == "0.000000" and row["v20_82_usable"] == "TRUE"
    ]
    assert_true(not zero_ratio_usable, "coverage ratio 0 rows marked v20_82_usable")
    irrelevant_schema = [
        row for row in audit
        if row["candidate_file"].endswith(("V20_36_V20_37_EXECUTION_PLAN.csv", "V20_37_FORMULA_RECHECK.csv", "V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv"))
    ]
    irrelevant_sources_present = (
        any(CONSOLIDATION.glob("V20_36_V20_37_EXECUTION_PLAN.csv"))
        or any(CONSOLIDATION.glob("V20_37_FORMULA_RECHECK.csv"))
        or any(CONSOLIDATION.glob("V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv"))
    )
    if irrelevant_sources_present:
        assert_true(irrelevant_schema, "expected irrelevant schema audit rows")
        assert_true(all(row["schema_valid"] == "FALSE" for row in irrelevant_schema), "irrelevant CSV schemas marked valid")
        assert_true(all(row["semantic_valid"] == "FALSE" for row in irrelevant_schema), "irrelevant CSV schemas marked semantic valid")
        assert_true(
            all(row["reject_reason"] == "UNUSABLE_SCHEMA_IRRELEVANT_TO_CERTIFIED_EVIDENCE" for row in irrelevant_schema),
            "irrelevant CSV schemas missing strict reject reason",
        )
    allowed_usable_sources = {
        "outputs/v20/consolidation/V20_37_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY.csv",
        "outputs/v20/consolidation/V20_38_FACTOR_EFFECTIVENESS_METRICS.csv",
        "outputs/v20/consolidation/V20_39_R1_SHADOW_BENCHMARK_RELATIVE_SUMMARY.csv",
        "outputs/v20/consolidation/V20_39_R2_SHADOW_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY.csv",
        "outputs/v20/consolidation/V20_40_PORTFOLIO_BENCHMARK_RELATIVE_RETURNS.csv",
    }
    allowed_usable_metrics = {
        "average_ticker_return",
        "rank_corr_factor_vs_qqq_relative_return",
        "average_net_portfolio_return",
    }
    usable_rows = [row for row in evidence if row["usable_for_v20_82"] == "TRUE"]
    if not usable_rows:
        r2_detail = read_csv(R2_DETAIL)
        assert_true(any(row["integration_status"] == "INTEGRATED" for row in r2_detail), "expected legacy usable evidence or R2 integrated categories")
        return
    assert_true(all(row["source_file"] in allowed_usable_sources for row in usable_rows), "usable evidence came from a disallowed source")
    assert_true(all(row["metric_name"] in allowed_usable_metrics for row in usable_rows), "usable evidence used a disallowed metric")
    blocked_metric_tokens = [
        "row_count",
        "exists_flag",
        "non_empty_flag",
        "status",
        "effective_source_run_count",
        "candidate_weight_delta",
        "manifest_field",
        "cache_row_count",
    ]
    bad_usable_metrics = [
        row for row in usable_rows
        if row["metric_name"] in blocked_metric_tokens or any(token in row["metric_name"].lower() for token in ["cache", "manifest", "status"])
    ]
    assert_true(not bad_usable_metrics, "status/count/cache/manifest/design metric became usable")


def test_component_integration_status_contracts() -> None:
    stage_module = load_stage_module()
    coverage = read_csv(OUTPUTS["coverage"])
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    report = OUTPUTS["report"].read_text(encoding="utf-8")
    fully_covered_count = sum(row["v20_82_usable"] == "TRUE" for row in coverage)
    partial_count = sum(row["has_any_usable_evidence"] == "TRUE" and row["v20_82_usable"] != "TRUE" for row in coverage)
    assert_true(manifest["row_level_usable_evidence_count"] == manifest["usable_evidence_count"], "row-level usable count mismatch")
    assert_true(manifest["v20_82_fully_covered_component_count"] == fully_covered_count, "fully covered component count mismatch")
    assert_true(manifest["v20_82_partial_component_count"] == partial_count, "partial component count mismatch")
    if fully_covered_count == 0:
        assert_true(
            manifest["v20_82_integration_status"] == "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS",
            "manifest suggests V20.82 can clear blocker with zero fully covered components",
        )
    zero_ratio_usable = [
        row for row in coverage
        if row["evidence_coverage_ratio"] == "0.000000" and row["v20_82_usable"] == "TRUE"
    ]
    assert_true(not zero_ratio_usable, "coverage ratio 0 rows marked v20_82_usable")
    partial_rows = [row for row in coverage if row["has_any_usable_evidence"] == "TRUE" and row["evidence_coverage_ratio"] != "1.000000"]
    assert_true(all(row["v20_82_usable"] == "FALSE" for row in partial_rows), "partial evidence rows marked fully usable")
    assert_true("usable_for_v20_82: TRUE" not in report, "report uses ambiguous usable_for_v20_82 wording")
    assert_true("row_level_usable_evidence_exists:" in report, "report missing row-level usable wording")
    assert_true("fully_covered_v20_82_components_exist:" in report, "report missing full component coverage wording")
    assert_true(
        "V20.82 should remain blocked/partial when no component satisfies required multi-path coverage." in report,
        "report missing V20.82 partial-block integration warning",
    )
    synthetic_positive = {
        "notes": "CERTIFIED_ETF_ROTATION_EVIDENCE",
        "direction_type": "ACTIVE_ROTATION",
        "rotation_shadow_score": "1.0",
    }
    assert_true(not stage_module.has_exact_positive_etf_certification(synthetic_positive), "ETF certification accepted non-status column")
    synthetic_status_positive = {
        "etf_rotation_certification_status": "CERTIFIED_ETF_ROTATION_EVIDENCE",
        "direction_type": "ACTIVE_ROTATION",
        "rotation_shadow_score": "1.0",
    }
    assert_true(stage_module.has_exact_positive_etf_certification(synthetic_status_positive), "ETF certification rejected named status column")
    synthetic_blocked = {
        "etf_rotation_certification_status": "CERTIFIED_ETF_ROTATION_EVIDENCE",
        "explanation": "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE",
    }
    assert_true(not stage_module.has_exact_positive_etf_certification(synthetic_blocked), "ETF certification ignored blocking token")


def test_status_contracts() -> None:
    evidence = read_csv(OUTPUTS["evidence"])
    coverage = read_csv(OUTPUTS["coverage"])
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    usable_count = sum(row["usable_for_v20_82"] == "TRUE" for row in evidence)
    assert_true(manifest["usable_evidence_count"] == usable_count, "manifest usable_evidence_count mismatch")
    if manifest["status"] in {"PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED", "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS"}:
        return
    if usable_count == 0:
        assert_true(manifest["status"] == "BLOCKED_V20_84_NO_USABLE_STRUCTURED_EVIDENCE", "no usable evidence must block")
    if usable_count > 0 and any(row["v20_82_usable"] == "FALSE" for row in coverage):
        assert_true(manifest["status"] == "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS", "gapped usable evidence must use gap pass status")


def main() -> None:
    load_stage_module()
    test_compile_parser_and_no_hardcoded_run_id()
    test_integration_run_and_no_old_mutation()
    test_outputs_aliases_and_schemas()
    test_r2_manifest_driven_integration_detail()
    test_r2_notes_only_and_synthetic_rules()
    test_guardrails_and_certification_contracts()
    test_strict_repair_contracts()
    test_component_integration_status_contracts()
    test_status_contracts()
    print("PASS_V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_TESTS")


if __name__ == "__main__":
    main()
