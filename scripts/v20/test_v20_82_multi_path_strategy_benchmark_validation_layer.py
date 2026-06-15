from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts" / "v20"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

STAGE_SCRIPT = SCRIPT_DIR / "v20_82_multi_path_strategy_benchmark_validation_layer.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_82_multi_path_strategy_benchmark_validation_layer.py"
WRAPPER = SCRIPT_DIR / "run_v20_82_multi_path_strategy_benchmark_validation_layer.ps1"

ALLOWED_STATUSES = {
    "PASS_V20_82_MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER",
    "PASS_V20_82_MULTI_PATH_VALIDATION_WITH_ETF_ROTATION_BLOCKED",
    "PASS_V20_82_MULTI_PATH_VALIDATION_WITH_OPTIONAL_INPUT_GAPS",
    "PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED",
    "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS",
    "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT",
    "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE",
    "BLOCKED_V20_82_WRAPPER_FAILURE",
}

R5_DETAIL = EVIDENCE / "V20_82_R5_MULTI_PATH_VALIDATION_DETAIL.csv"
R5_DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_MULTI_PATH_VALIDATION_DETAIL.csv"
R5_REQUIRED_CATEGORIES = {
    "etf_rotation_evidence",
    "multi_window_strategy_evidence",
    "regime_conditioned_evidence",
    "downside_risk_evidence",
    "benchmark_comparison_evidence",
    "score_lineage_evidence",
    "ranking_delta_diagnostic_evidence",
    "acceptance_proof_evidence",
}
R5_DETAIL_SCHEMA = [
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

V20_84_INPUTS = {
    "evidence_table": CONSOLIDATION / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
    "coverage_table": CONSOLIDATION / "V20_CURRENT_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv",
    "input_audit": CONSOLIDATION / "V20_CURRENT_EVIDENCE_INPUT_BINDING_AUDIT.csv",
    "manifest": OPS / "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json",
}

SCHEMAS = {
    "input_audit": ["input_name", "required_flag", "binding_status", "source_path", "row_count", "required_fields_recovered", "optional_fields_recovered", "run_id", "explanation"],
    "factor": ["factor_name", "factor_type", "source_path", "coverage_ratio", "score", "evidence_count", "binding_status", "explanation"],
    "strategy": ["strategy_name", "strategy_type", "evaluation_window", "constituent_count", "return_source", "return_evidence_status", "model_return", "benchmark_return", "excess_return", "evidence_coverage_ratio", "allowed_shadow_delta", "validation_status", "v20_84_evidence_bound", "v20_84_integration_status", "v20_84_evidence_effect_on_v20_82_status", "explanation"],
    "etf": ["etf_symbol", "paired_symbol", "pair_group", "direction_type", "leverage_type", "current_regime", "relative_strength_score", "downside_behavior_score", "volatility_risk_score", "liquidity_confidence_score", "rotation_shadow_score", "entry_permission", "position_permission", "benchmark_role", "promotion_status", "explanation"],
    "benchmark": ["strategy_name", "strategy_type", "benchmark_name", "benchmark_type", "evaluation_window", "return_source", "return_evidence_status", "strategy_return", "benchmark_return", "excess_return", "strategy_volatility", "benchmark_volatility", "strategy_max_drawdown", "benchmark_max_drawdown", "downside_capture", "upside_capture", "hit_rate_vs_benchmark", "risk_adjusted_alpha", "turnover_penalty", "regime", "strategy_effectiveness_grade", "v20_84_evidence_bound", "v20_84_integration_status", "v20_84_evidence_effect_on_v20_82_status", "explanation"],
    "nasdaq": ["model_name", "evaluation_window", "return_source", "return_evidence_status", "qqq_return", "model_return", "excess_return_vs_qqq", "drawdown_vs_qqq", "downside_capture_vs_qqq", "upside_capture_vs_qqq", "hit_rate_vs_qqq", "passed_nasdaq_hurdle", "v20_84_evidence_bound", "v20_84_integration_status", "v20_84_evidence_effect_on_v20_82_status", "blocking_reason"],
    "model_compare": ["ticker", "current_rank", "current_score", "current_score_scale", "shadow_adjusted_score", "shadow_score_scale", "score_comparison_valid", "shadow_adjusted_rank", "rank_delta", "main_positive_driver", "main_penalty_driver", "regime_effect", "benchmark_effect", "entry_permission", "position_permission", "v20_84_evidence_bound", "v20_84_integration_status", "v20_84_evidence_effect_on_v20_82_status", "explanation"],
    "promotion": ["component_name", "component_type", "shadow_score", "evidence_count", "required_evidence_count", "multi_path_coverage", "nasdaq_hurdle_passed", "etf_rotation_benchmark_passed", "promotion_allowed", "v20_84_evidence_bound", "v20_84_row_level_usable_evidence_count", "v20_84_fully_covered_component_count", "v20_84_partial_component_count", "v20_84_integration_status", "v20_84_evidence_effect_on_v20_82_status", "blocking_reason"],
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


def load_stage_module():
    spec = importlib.util.spec_from_file_location("v20_82_stage_under_test", STAGE_SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "unable to load V20.82 stage module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alias_path(path: Path) -> Path:
    return path.with_name(path.name.replace("V20_82_", "V20_CURRENT_", 1))


def tracked_v20_47_to_84_artifacts() -> list[Path]:
    result = run_command(["git", "ls-files"])
    assert_true(result.returncode == 0, f"git ls-files failed: {result.stdout}\n{result.stderr}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        normalized = text.replace("\\", "/")
        if not normalized.startswith(("inputs/", "outputs/")):
            continue
        upper = normalized.upper()
        if "V20_82" in upper or "V20_CURRENT_MULTI_PATH" in upper:
            continue
        if any(f"V20_{number}" in upper for number in range(47, 85)):
            paths.append(ROOT / normalized)
    return sorted(paths)


def file_digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def v20_84_inputs_available() -> bool:
    return all(path.exists() for path in V20_84_INPUTS.values())


def artifact_snapshot(paths: list[Path]) -> dict[str, tuple[str, int, int]]:
    snapshot: dict[str, tuple[str, int, int]] = {}
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if path.exists():
            stat = path.stat()
            snapshot[rel] = (file_digest(path), stat.st_size, stat.st_mtime_ns)
        else:
            snapshot[rel] = ("MISSING", -1, -1)
    return snapshot


def wrapper_final_status(stdout: str) -> str:
    tokens = re.findall(r"\b(?:PASS|PARTIAL_PASS|BLOCKED)_V20_82_[A-Z0-9_]+\b", stdout)
    return tokens[-1] if tokens else ""


def dirty_v20_47_to_84_artifacts() -> tuple[list[str], list[str]]:
    tracked_result = run_command(["git", "ls-files"])
    assert_true(tracked_result.returncode == 0, f"git ls-files failed: {tracked_result.stdout}\n{tracked_result.stderr}")
    tracked_paths = {line.strip().replace("\\", "/") for line in tracked_result.stdout.splitlines() if line.strip()}
    result = run_command(["git", "status", "--short"])
    assert_true(result.returncode == 0, f"git status failed: {result.stdout}\n{result.stderr}")
    tracked_dirty: list[str] = []
    untracked: list[str] = []
    for line in result.stdout.splitlines():
        path_text = line[3:].strip()
        normalized = path_text.replace("\\", "/")
        upper = normalized.upper()
        if normalized.startswith(("inputs/", "outputs/")) and "V20_82" not in upper and "V20_CURRENT_MULTI_PATH" not in upper and any(f"V20_{number}" in upper for number in range(47, 85)):
            if normalized in tracked_paths:
                tracked_dirty.append(line)
            elif line.startswith("??"):
                untracked.append(line)
    return tracked_dirty, untracked


def test_compile_and_parser() -> None:
    for path in [STAGE_SCRIPT, TEST_SCRIPT]:
        result = run_command([sys.executable, "-m", "py_compile", str(path)])
        assert_true(result.returncode == 0, f"py_compile failed for {path}: {result.stdout}\n{result.stderr}")
    parse = run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_82_multi_path_strategy_benchmark_validation_layer.ps1'), [ref]$null); 'PARSE_OK'",
    ])
    assert_true(parse.returncode == 0 and "PARSE_OK" in parse.stdout, f"PowerShell parser check failed: {parse.stdout}\n{parse.stderr}")


def test_integration_run() -> None:
    before = {path: path.read_bytes() for path in (SCRIPT_DIR.glob("v20_[4-8][0-9]*.py")) if not path.name.startswith("v20_82_")}
    tracked_artifacts = tracked_v20_47_to_84_artifacts()
    artifact_before = artifact_snapshot(tracked_artifacts)
    pre_existing_tracked_dirty, pre_existing_untracked = dirty_v20_47_to_84_artifacts()
    print(f"PRE_EXISTING_DIRTY_TRACKED_V20_47_TO_84_COUNT={len(pre_existing_tracked_dirty)}")
    for item in pre_existing_tracked_dirty[:50]:
        print(f"PRE_EXISTING_DIRTY_TRACKED_V20_47_TO_84={item}")
    if len(pre_existing_tracked_dirty) > 50:
        print(f"PRE_EXISTING_DIRTY_TRACKED_V20_47_TO_84_TRUNCATED={len(pre_existing_tracked_dirty) - 50}")
    print(f"PRE_EXISTING_UNTRACKED_V20_47_TO_84_COUNT={len(pre_existing_untracked)}")
    for item in pre_existing_untracked[:50]:
        print(f"PRE_EXISTING_UNTRACKED_V20_47_TO_84={item}")
    if len(pre_existing_untracked) > 50:
        print(f"PRE_EXISTING_UNTRACKED_V20_47_TO_84_TRUNCATED={len(pre_existing_untracked) - 50}")
    result = run_command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    final_status = wrapper_final_status(result.stdout)
    assert_true(final_status in ALLOWED_STATUSES, f"unexpected wrapper final status {final_status!r}: {result.stdout}")
    assert_true(final_status != "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT", f"V20.82 did not bind V20.83 authoritative current input: {result.stdout}")
    after = {path: path.read_bytes() for path in before}
    assert_true(before == after, "old production V20.47-V20.84 script files changed")
    artifact_after = artifact_snapshot(tracked_artifacts)
    changed = [path for path, value in artifact_before.items() if artifact_after.get(path) != value]
    assert_true(not changed, "V20.82 execution mutated tracked V20.47-V20.84 artifacts: " + "; ".join(changed[:20]))


def test_outputs_exist_aliases_and_schemas() -> None:
    for key, path in OUTPUTS.items():
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
        alias = alias_path(path)
        assert_true(alias.exists() and alias.stat().st_size > 0, f"missing or empty current alias: {alias}")
        if path.suffix.lower() == ".csv":
            assert_true(read_csv(path), f"CSV has no rows: {path}")
            assert_true(fields(path) == SCHEMAS[key], f"schema mismatch for {path}: {fields(path)}")
            assert_true(path.read_bytes() == alias.read_bytes(), f"alias differs for {path}")
    assert_true(R5_DETAIL.exists() and R5_DETAIL.stat().st_size > 0, f"missing or empty R5 detail output: {R5_DETAIL}")
    assert_true(R5_DETAIL_ALIAS.exists() and R5_DETAIL_ALIAS.stat().st_size > 0, f"missing or empty R5 current alias: {R5_DETAIL_ALIAS}")
    assert_true(R5_DETAIL.read_bytes() == R5_DETAIL_ALIAS.read_bytes(), "R5 detail alias differs from versioned output")
    assert_true(fields(R5_DETAIL) == R5_DETAIL_SCHEMA, f"R5 detail schema mismatch: {fields(R5_DETAIL)}")


def test_r5_detail_category_validation() -> None:
    rows = read_csv(R5_DETAIL)
    assert_true(rows, "R5 detail output empty")
    categories = {row["validation_category"] for row in rows}
    assert_true(R5_REQUIRED_CATEGORIES.issubset(categories), f"missing R5 validation categories: {sorted(R5_REQUIRED_CATEGORIES - categories)}")
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(manifest["status"] in {"PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED", "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS"}, f"unexpected R5 manifest status: {manifest['status']}")
    assert_true(manifest.get("v20_90_consumed") is True, f"V20.90 not marked consumed: {manifest}")
    assert_true(manifest.get("v20_91_consumed") is True, f"V20.91 not marked consumed: {manifest}")
    for row in rows:
        assert_true(row["research_only"] == "TRUE", f"R5 row not research-only: {row}")
        assert_true(row["official_recommendation_created"] == "FALSE", f"R5 row created official recommendation: {row}")
        assert_true(row["official_weight_mutated"] == "FALSE", f"R5 row mutated official weight: {row}")
        assert_true(row["trade_action_created"] == "FALSE", f"R5 row created trade action: {row}")
        if row["required_level"] == "REQUIRED" and row["validation_status"] == "BLOCKED":
            assert_true(row["category_blocker_reason"] != "INSUFFICIENT_MULTI_PATH_EVIDENCE", f"generic blocker used in R5 detail: {row}")
            assert_true(row["validation_category"].upper() in row["category_blocker_reason"], f"category-level blocker missing category name: {row}")
    multi_window = next(row for row in rows if row["validation_category"] == "multi_window_strategy_evidence")
    assert_true(int(multi_window["certified_row_count"]) > 0, f"V20.91 certified rows not counted: {multi_window}")
    etf = next(row for row in rows if row["validation_category"] == "etf_rotation_evidence")
    assert_true(int(etf["attached_row_count"]) > 0, f"V20.90 rows not attached: {etf}")
    if int(etf["partial_row_count"]) > 0:
        assert_true(int(etf["certified_row_count"]) < int(etf["attached_row_count"]), f"V20.90 partial rows treated as fully certified: {etf}")
    blocked_required = [row for row in rows if row["required_level"] == "REQUIRED" and row["validation_status"] == "BLOCKED"]
    if manifest["status"].startswith("PARTIAL_PASS_"):
        assert_true(blocked_required, f"partial R5 status without blocked category rows: {rows}")


def test_r5_notes_only_certification_rejected() -> None:
    module = load_stage_module()
    notes_only = {
        "ticker": "AAA",
        "notes": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
        "certification_reason": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE",
    }
    assert_true(not module.r5_structured_certified(notes_only), "R5 accepted notes-only certification")
    structured = {"certification_status": "CERTIFIED_MULTI_WINDOW_STRATEGY_EVIDENCE", "notes": "irrelevant"}
    assert_true(module.r5_structured_certified(structured), "R5 rejected structured certification_status")


def test_qqq_and_etf_contracts() -> None:
    nasdaq = read_csv(OUTPUTS["nasdaq"])
    expected_models = {
        "CURRENT_OFFICIAL_RANKING_TOP10",
        "CURRENT_OFFICIAL_RANKING_TOP20",
        "SHADOW_MULTI_PATH_ADJUSTED_TOP10",
        "SHADOW_MULTI_PATH_ADJUSTED_TOP20",
        "ETF_ROTATION_SHADOW",
    }
    assert_true(expected_models.issubset({row["model_name"] for row in nasdaq}), "mandatory Nasdaq gate model rows missing")
    assert_true(all(row["qqq_return"] not in {"", "NA"} for row in nasdaq), "QQQ gate is not populated")
    for row in nasdaq:
        if row["model_return"] not in {"", "NA"}:
            assert_true(row["return_source"] not in {"", "NA"}, f"numeric strategy return missing return_source: {row}")
            assert_true(row["return_evidence_status"] not in {"", "NA"}, f"numeric strategy return missing return_evidence_status: {row}")
        if row["drawdown_vs_qqq"] == "NA":
            assert_true("INSUFFICIENT_DRAWDOWN_EVIDENCE" in row["blocking_reason"], f"silent drawdown placeholder: {row}")
    benchmark = read_csv(OUTPUTS["benchmark"])
    assert_true("QQQ_BUY_AND_HOLD" in {row["benchmark_name"] for row in benchmark}, "QQQ benchmark comparison missing")
    assert_true("ETF_ROTATION_BASELINE" in {row["benchmark_name"] for row in benchmark}, "ETF rotation benchmark missing")
    etf = read_csv(OUTPUTS["etf"])
    roles = {row["benchmark_role"] for row in etf}
    assert_true(roles <= {"CANDIDATE_ONLY", "BENCHMARK_ONLY", "CANDIDATE_AND_BENCHMARK"}, f"invalid ETF benchmark_role: {roles}")
    assert_true(any(row["benchmark_role"] in {"BENCHMARK_ONLY", "CANDIDATE_AND_BENCHMARK"} for row in etf), "ETF benchmark role not present")


def test_etf_status_and_return_semantics() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    v20_84_evidence = read_csv(V20_84_INPUTS["evidence_table"]) if V20_84_INPUTS["evidence_table"].exists() else []
    v20_84_etf_usable_count = sum(1 for row in v20_84_evidence if row.get("component_type") == "ETF_ROTATION" and row.get("usable_for_v20_82") == "TRUE")
    etf = read_csv(OUTPUTS["etf"])
    nasdaq = read_csv(OUTPUTS["nasdaq"])
    etf_gate = next(row for row in nasdaq if row["model_name"] == "ETF_ROTATION_SHADOW")
    usable_rows = [row for row in etf if row["benchmark_role"] in {"BENCHMARK_ONLY", "CANDIDATE_AND_BENCHMARK"}]
    assert_true(usable_rows, "ETF benchmark rows missing")
    uncertified = any("DESIGN_ONLY" in row["direction_type"] or "NOT_READY" in row["explanation"] or "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE" in row["explanation"] for row in etf)
    if uncertified:
        assert_true(etf_gate["model_return"] == "NA", f"uncertified ETF design produced numeric return: {etf_gate}")
        assert_true("INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE" in etf_gate["blocking_reason"], "ETF insufficiency reason missing")
        assert_true(manifest["status"] != "PASS_V20_82_MULTI_PATH_VALIDATION_WITH_ETF_ROTATION_BLOCKED", "ETF blocked status used for normal shadow/no-trade or uncertified design state")
    if v20_84_etf_usable_count == 0:
        assert_true(etf_gate["model_return"] == "NA", f"ETF benchmark return became numeric with zero V20.84 ETF usable evidence: {etf_gate}")
        benchmark = read_csv(OUTPUTS["benchmark"])
        etf_bench_rows = [row for row in benchmark if row["benchmark_name"] == "ETF_ROTATION_BASELINE"]
        assert_true(etf_bench_rows, "ETF benchmark comparison rows missing")
        assert_true(all(row["benchmark_return"] == "NA" for row in etf_bench_rows), f"ETF benchmark return numeric with zero certified ETF evidence: {etf_bench_rows[:3]}")


def test_etf_certification_gate_rejects_substring_and_design_rows() -> None:
    module = load_stage_module()
    text = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert_true('"CERTIFIED" in clean(row.get("rotation_readiness_status")).upper()' not in text, "ETF substring certification logic remains")
    benchmark_index = {
        "TQQQ": {"ticker": "TQQQ", "return_20d_pct": "10.0"},
        "SOXL": {"ticker": "SOXL", "return_20d_pct": "8.0"},
        "TECL": {"ticker": "TECL", "return_20d_pct": "7.0"},
        "SPXL": {"ticker": "SPXL", "return_20d_pct": "6.0"},
    }
    fieldnames = [
        "bull_etf",
        "bear_etf",
        "etf_group",
        "design_confidence_score",
        "market_regime",
        "rotation_readiness_status",
        "design_only_directional_bias",
        "notes",
        "certification_status",
    ]
    cases = [
        {
            "name": "insufficient_substring",
            "row": {
                "bull_etf": "TQQQ",
                "bear_etf": "SQQQ",
                "etf_group": "NASDAQ",
                "design_confidence_score": "0.9",
                "market_regime": "BULL",
                "rotation_readiness_status": "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE",
                "design_only_directional_bias": "BULL",
                "notes": "",
                "certification_status": "",
            },
        },
        {
            "name": "design_only_wait",
            "row": {
                "bull_etf": "SOXL",
                "bear_etf": "SOXS",
                "etf_group": "SEMIS",
                "design_confidence_score": "0.8",
                "market_regime": "BULL",
                "rotation_readiness_status": "CERTIFIED_ETF_ROTATION_EVIDENCE",
                "design_only_directional_bias": "DESIGN_ONLY_CASH_OR_WAIT",
                "notes": "",
                "certification_status": "",
            },
        },
        {
            "name": "non_certification_field",
            "row": {
                "bull_etf": "TECL",
                "bear_etf": "TECS",
                "etf_group": "TECH",
                "design_confidence_score": "0.7",
                "market_regime": "BULL",
                "rotation_readiness_status": "READY",
                "design_only_directional_bias": "BULL",
                "notes": "CERTIFIED_ETF_ROTATION_EVIDENCE",
                "certification_status": "",
            },
        },
        {
            "name": "v20_84_zero_blocks_named_positive",
            "row": {
                "bull_etf": "SPXL",
                "bear_etf": "SPXS",
                "etf_group": "SP500",
                "design_confidence_score": "0.6",
                "market_regime": "BULL",
                "rotation_readiness_status": "READY",
                "design_only_directional_bias": "BULL",
                "notes": "",
                "certification_status": "CERTIFIED_ETF_ROTATION_EVIDENCE",
            },
        },
    ]
    with tempfile.TemporaryDirectory() as tmp:
        original_consolidation = module.CONSOLIDATION
        try:
            module.CONSOLIDATION = Path(tmp)
            for case in cases:
                path = module.CONSOLIDATION / "V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow(case["row"])
                rows, etf_return, blocked, reason = module.build_etf_rotation(benchmark_index, True, 0)
                assert_true(rows, f"ETF rows missing for synthetic case {case['name']}")
                assert_true(etf_return is None, f"synthetic ETF case certified without V20.84 ETF evidence: {case['name']}")
                assert_true(reason == "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE", f"wrong ETF rejection reason for {case['name']}: {reason}")
                assert_true(blocked is False, f"ETF design table should be present but uncertified for {case['name']}")
            path = module.CONSOLIDATION / "V20_79A_ETF_SIGNAL_DESIGN_TABLE.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({
                    "bull_etf": "TQQQ",
                    "bear_etf": "SQQQ",
                    "etf_group": "NASDAQ",
                    "design_confidence_score": "0.9",
                    "market_regime": "BULL",
                    "rotation_readiness_status": "READY",
                    "design_only_directional_bias": "BULL",
                    "notes": "",
                    "certification_status": "CERTIFIED_ETF_ROTATION_EVIDENCE",
                })
            _rows, etf_return, _blocked, reason = module.build_etf_rotation(benchmark_index, False, 0)
            assert_true(etf_return == 10.0 and reason == "", "named positive fallback certification rejected unexpectedly")
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({
                    "bull_etf": "TECL",
                    "bear_etf": "TECS",
                    "etf_group": "TECH",
                    "design_confidence_score": "0.7",
                    "market_regime": "BULL",
                    "rotation_readiness_status": "READY",
                    "design_only_directional_bias": "BULL",
                    "notes": "CERTIFIED_ETF_ROTATION_EVIDENCE",
                    "certification_status": "",
                })
            _rows, etf_return, _blocked, reason = module.build_etf_rotation(benchmark_index, True, 1)
            assert_true(etf_return is None, "non-certification field certified ETF return despite positive V20.84 ETF usable count")
            assert_true(reason == "INSUFFICIENT_CERTIFIED_ETF_ROTATION_EVIDENCE", f"wrong non-certification field rejection reason: {reason}")
        finally:
            module.CONSOLIDATION = original_consolidation


def test_research_only_and_manifest_invariants() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(manifest["status"] in ALLOWED_STATUSES, f"unexpected manifest status: {manifest['status']}")
    assert_true(manifest["status"] != "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT", f"V20.83 authoritative current input was not bound: {manifest['status']}")
    assert_true(manifest["research_only"] is True, "research_only flag changed")
    assert_true(manifest["shadow_only"] is True, "shadow_only flag changed")
    assert_true(manifest["official_recommendation_created"] is False, "official recommendation flag changed")
    assert_true(manifest["official_weight_mutated"] is False, "official weight flag changed")
    assert_true(manifest["trade_action_created"] is False, "trade action flag changed")
    input_files = set(manifest.get("input_files", []))
    assert_true(
        "outputs/v20/consolidation/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv" in input_files
        or "outputs/v20/consolidation/V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv" in input_files,
        f"V20.83 authoritative table missing from V20.82 manifest input_files: {input_files}",
    )
    assert_true(
        "outputs/v20/ops/V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json" in input_files,
        f"V20.83 manifest missing from V20.82 manifest input_files: {input_files}",
    )
    if v20_84_inputs_available():
        for path in V20_84_INPUTS.values():
            assert_true(path.relative_to(ROOT).as_posix() in input_files, f"V20.84 input missing from V20.82 manifest input_files: {path}")
        assert_true(manifest["v20_84_evidence_bound"] is True, f"V20.84 evidence not bound: {manifest}")
        if manifest["v20_84_integration_status"] == "FULL_COMPONENT_COVERAGE_AVAILABLE":
            assert_true(manifest["v20_84_fully_covered_component_count"] > 0, f"full V20.84 integration without covered components: {manifest}")
            assert_true(manifest["v20_84_evidence_effect_on_v20_82_status"] == "FULL_COMPONENT_COVERAGE_BOUND", f"unexpected V20.84 full effect: {manifest}")
        else:
            assert_true(manifest["v20_84_fully_covered_component_count"] == 0, f"V20.84 fully covered count should remain zero for partial evidence: {manifest}")
            assert_true(manifest["v20_84_integration_status"] == "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS", f"unexpected V20.84 integration status: {manifest}")
            assert_true(
                manifest["v20_84_evidence_effect_on_v20_82_status"] == "PARTIAL_EVIDENCE_BOUND_BUT_REQUIRED_PATHS_INCOMPLETE",
                f"unexpected V20.84 effect: {manifest}",
            )
    else:
        assert_true(manifest["v20_84_evidence_bound"] is False, f"absent V20.84 evidence unexpectedly bound: {manifest}")
    assert_true(
        manifest["status"] in {"PASS_V20_82_R5_MULTI_PATH_EVIDENCE_VALIDATED", "PARTIAL_PASS_V20_82_R5_MULTI_PATH_EVIDENCE_ATTACHED_WITH_CATEGORY_BLOCKERS"},
        f"R5 category-level validation status missing: {manifest}",
    )
    report = OUTPUTS["report"].read_text(encoding="utf-8")
    required_phrases = [
        "Research-only and shadow-only.",
        "No official recommendation.",
        "No official weight mutation.",
        "No trade order.",
        "QQQ and ETF rotation are benchmarks for strategy effectiveness.",
        "ETF rotation is not activated for trading.",
        "V20.84 row-level usable evidence count:",
        "Row-level usable evidence does not clear the V20.82 insufficient-evidence blocker",
        "V20.82-R5 consumes V20.89 required evidence paths, V20.90 ETF rotation evidence, and V20.91 multi-window strategy evidence.",
    ]
    if v20_84_inputs_available():
        required_phrases.append("V20.84 evidence bound: TRUE")
    else:
        required_phrases.append("V20.84 evidence bound: FALSE")
    for phrase in required_phrases:
        assert_true(phrase in report, f"required report phrase missing: {phrase}")
    assert_true("usable_for_v20_82: TRUE" not in report, "report reintroduced ambiguous usable_for_v20_82 summary")


def test_input_binding_and_usable_evidence_semantics() -> None:
    audit = read_csv(OUTPUTS["input_audit"])
    current = next(row for row in audit if row["input_name"] == "CURRENT_CANDIDATE_RANKING")
    assert_true("V20_76_SHADOW_OPERATIONAL_RANK_TABLE" not in current["source_path"], f"shadow table bound as official current ranking: {current}")
    assert_true("V20_75_DAILY_RANK_CHANGE_ATTRIBUTION_TABLE" not in current["source_path"], f"V20.75 attribution table bound as official current ranking: {current}")
    assert_true(current["binding_status"] == "FOUND", f"V20.83 authoritative current input not found: {current}")
    assert_true(current["source_path"].endswith("V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv") or current["source_path"].endswith("V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"), f"V20.83 current ranking not bound: {current}")
    assert_true(current["row_count"] == "40", f"unexpected V20.83 current input row count: {current}")
    assert_true("source_role=OPERATOR_ACCEPTED_CURRENT_RESEARCH" in current["explanation"], f"V20.83 source role not validated: {current}")
    assert_true("binding_quality=AUTHORITATIVE_V20_83_OFFICIAL_CURRENT" in current["explanation"], f"V20.83 binding quality missing: {current}")
    assert_true("detected_file=V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv" in current["explanation"] or "detected_file=V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv" in current["explanation"], f"V20.83 detected_file missing: {current}")
    evidence = next(row for row in audit if row["input_name"] == "CERTIFIED_MULTI_PATH_EVIDENCE")
    if v20_84_inputs_available():
        assert_true(evidence["binding_status"] == "FOUND", f"V20.84 certified evidence not found: {evidence}")
        assert_true(evidence["source_path"].endswith("V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv"), f"V20.84 evidence table not bound: {evidence}")
        assert_true(evidence["required_fields_recovered"] == "TRUE", f"V20.84 evidence schema not recovered: {evidence}")
        assert_true("binding_quality=V20_84_PARTIAL_CERTIFIED_EVIDENCE_BOUND" in evidence["explanation"], f"V20.84 binding quality missing: {evidence}")
        assert_true("fully_covered_component_count=0" in evidence["explanation"], f"V20.84 full coverage count missing: {evidence}")
        assert_true("effect=PARTIAL_EVIDENCE_BOUND_BUT_REQUIRED_PATHS_INCOMPLETE" in evidence["explanation"], f"V20.84 partial effect missing: {evidence}")
    else:
        assert_true(evidence["binding_status"] == "MISSING_REQUIRED", f"absent V20.84 evidence did not remain missing-required: {evidence}")
    for row in audit:
        if row["required_flag"] == "FALSE" and (row["source_path"].endswith(".md") or row["source_path"].endswith(".txt") or "REPORT" in row["source_path"].upper() or "READ_FIRST" in row["source_path"].upper()):
            assert_true(row["binding_status"] == "UNUSABLE_SCHEMA", f"unstructured report/readme counted as usable evidence: {row}")
    promotion = read_csv(OUTPUTS["promotion"])
    main = next(row for row in promotion if row["component_name"] == "MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER")
    unusable_count = sum(1 for row in audit if row["required_flag"] == "FALSE" and row["binding_status"] == "UNUSABLE_SCHEMA")
    if unusable_count:
        assert_true(float(main["multi_path_coverage"]) < 1.0, f"multi_path_coverage=1.0 despite unusable evidence: {main}")
    for row in audit:
        lowered = row["source_path"].lower()
        if any(token in lowered for token in ["required_output_checks", "manifest", "hash_ledger", "summary", "status", "next_step_decision"]):
            assert_true(row["binding_status"] == "UNUSABLE_SCHEMA", f"schema-irrelevant artifact counted as usable evidence: {row}")


def test_no_official_or_trade_paths_and_promotion_block() -> None:
    promotion = read_csv(OUTPUTS["promotion"])
    assert_true(promotion and all(row["promotion_allowed"] == "FALSE" for row in promotion), "promotion_allowed must default false")
    for row in promotion:
        if v20_84_inputs_available():
            assert_true(row["v20_84_evidence_bound"] == "TRUE", f"V20.84 evidence should be bound in promotion row: {row}")
            assert_true(row["v20_84_integration_status"] == "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS", f"unexpected V20.84 promotion integration status: {row}")
            assert_true(row["v20_84_evidence_effect_on_v20_82_status"] == "PARTIAL_EVIDENCE_BOUND_BUT_REQUIRED_PATHS_INCOMPLETE", f"unexpected V20.84 promotion effect: {row}")
        else:
            assert_true(row["v20_84_evidence_bound"] == "FALSE", f"absent V20.84 evidence unexpectedly bound in promotion row: {row}")
        coverage = row["multi_path_coverage"]
        try:
            value = float(coverage)
        except ValueError:
            value = 0.0
        if value < 0.5:
            assert_true("INSUFFICIENT" in row["blocking_reason"] or row["promotion_allowed"] == "FALSE", "insufficient evidence did not block promotion")
    created_names = [path.name.upper() for path in OUTPUTS.values()] + [alias_path(path).name.upper() for path in OUTPUTS.values()]
    forbidden = ["OFFICIAL_RECOMMENDATION", "OFFICIAL_WEIGHT", "TRADE_ORDER", "BROKER"]
    assert_true(not any(token in name for token in forbidden for name in created_names), "official/trade output name created")
    tree = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
    forbidden_imports = {"requests", "urllib", "httpx", "yfinance", "alpaca_trade_api", "ibapi", "ccxt"}
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0].lower() for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0].lower())
    assert_true(not (set(imports) & forbidden_imports), "network/broker import introduced")
    diff = run_command(["git", "diff", "--", "inputs/v20/current_market/yahoo_cache/v20_47/V20_47_YAHOO_CURRENT_CACHE_HASH_LEDGER.csv"])
    assert_true(diff.stdout.strip() == "", "V20.47 ledger modified by V20.82 changes")


def test_promotion_nasdaq_hurdle_uses_certified_strategy_evidence_only() -> None:
    nasdaq = read_csv(OUTPUTS["nasdaq"])
    promotion = read_csv(OUTPUTS["promotion"])
    main = next(row for row in promotion if row["component_name"] == "MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER")
    proxy_passes = [row for row in nasdaq if row["return_evidence_status"] == "PROXY_TECHNICAL_RETURN_NOT_CERTIFIED_STRATEGY_ALPHA" and row["passed_nasdaq_hurdle"] == "TRUE"]
    assert_true(not proxy_passes, f"proxy return rows passed Nasdaq hurdle: {proxy_passes}")
    if not any(row["passed_nasdaq_hurdle"] == "TRUE" and row["return_evidence_status"].startswith("CERTIFIED_STRATEGY_") for row in nasdaq):
        assert_true(main["nasdaq_hurdle_passed"] == "FALSE", f"promotion Nasdaq hurdle passed without certified strategy evidence: {main}")
        assert_true("INSUFFICIENT_CERTIFIED_STRATEGY_EVIDENCE" in main["blocking_reason"], f"certified strategy evidence block missing: {main}")
    assert_true(main["promotion_allowed"] == "FALSE", f"promotion unexpectedly allowed: {main}")


def test_insufficient_evidence_status_blocks_promotion_nasdaq_hurdle() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    nasdaq = read_csv(OUTPUTS["nasdaq"])
    promotion = read_csv(OUTPUTS["promotion"])
    if manifest.get("status") == "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE":
        assert_true(all(row["passed_nasdaq_hurdle"] == "FALSE" for row in nasdaq), f"Nasdaq hurdle passed during insufficient evidence block: {nasdaq}")
        for row in promotion:
            assert_true(row["nasdaq_hurdle_passed"] == "FALSE", f"promotion Nasdaq hurdle passed during insufficient evidence block: {row}")
            assert_true(row["promotion_allowed"] == "FALSE", f"promotion allowed during insufficient evidence block: {row}")
        main = next(row for row in promotion if row["component_name"] == "MULTI_PATH_STRATEGY_BENCHMARK_VALIDATION_LAYER")
        assert_true(main["v20_84_row_level_usable_evidence_count"] == str(manifest["v20_84_row_level_usable_evidence_count"]), f"V20.84 row-level count mismatch: {main}")
        assert_true(main["v20_84_fully_covered_component_count"] == "0", f"V20.84 fully covered count should be zero: {main}")
        assert_true("V20_84_PARTIAL_BLOCK_MISSING_REQUIRED_PATHS" in main["blocking_reason"], f"V20.84 partial blocker missing: {main}")
        assert_true(
            "INSUFFICIENT_CERTIFIED_STRATEGY_EVIDENCE" in main["blocking_reason"]
            or "INSUFFICIENT_MULTI_PATH_EVIDENCE" in main["blocking_reason"],
            f"insufficient-evidence promotion reason missing: {main}",
        )


def test_v20_83_manifest_binding_requirements() -> None:
    manifest_path = OPS / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert_true(manifest["status"] == "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT", "V20.83 manifest is not PASS")
    assert_true(manifest["research_only"] is True, "V20.83 research_only invariant failed")
    assert_true(manifest["official_recommendation_created"] is False, "V20.83 recommendation invariant failed")
    assert_true(manifest["official_weight_mutated"] is False, "V20.83 weight invariant failed")
    assert_true(manifest["trade_action_created"] is False, "V20.83 trade invariant failed")
    assert_true(manifest["bound_source_role"] == "OPERATOR_ACCEPTED_CURRENT_RESEARCH", "V20.83 source role is not accepted")
    assert_true(manifest["exact_artifact_proof_status"] == "FOUND", "V20.83 exact artifact proof missing")
    assert_true(manifest["acceptance_package_manifest_status"] == "PASS", "V20.83 package manifest proof missing")
    script_text = STAGE_SCRIPT.read_text(encoding="utf-8")
    for required in [
        "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv",
        "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT_MANIFEST.json",
        "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT",
        "official_recommendation_created",
        "official_weight_mutated",
        "trade_action_created",
        "exact_artifact_proof_status",
        "acceptance_package_manifest_status",
    ]:
        assert_true(required in script_text, f"V20.82 does not enforce V20.83 binding requirement: {required}")


def test_v20_83_manifest_validator_rejects_invalid_manifests() -> None:
    module = load_stage_module()
    valid = {
        "status": "PASS_V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_EXPORT",
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "trade_action_created": False,
        "bound_source_role": "OPERATOR_ACCEPTED_CURRENT_RESEARCH",
        "exact_artifact_proof_status": "FOUND",
        "acceptance_package_manifest_status": "PASS",
    }
    cases = [
        {"status": "BLOCKED_V20_83_TEST"},
        {"official_recommendation_created": True},
        {"official_weight_mutated": True},
        {"trade_action_created": True},
        {"exact_artifact_proof_status": "MISSING"},
        {"exact_artifact_proof_status": ""},
        {"acceptance_package_manifest_status": "BLOCKED"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        original_path = module.V20_83_MANIFEST
        try:
            module.V20_83_MANIFEST = manifest_path
            for override in cases:
                payload = dict(valid)
                payload.update(override)
                manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                ok, reason, _manifest = module.v20_83_manifest_valid()
                assert_true(not ok and reason == "V20_83_MANIFEST_INVARIANT_FAILURE", f"invalid V20.83 manifest accepted: {override}")
            payload = dict(valid)
            payload.pop("exact_artifact_proof_status")
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            ok, reason, _manifest = module.v20_83_manifest_valid()
            assert_true(not ok and reason == "V20_83_MANIFEST_INVARIANT_FAILURE", "missing exact_artifact_proof_status accepted")
        finally:
            module.V20_83_MANIFEST = original_path


def test_v20_84_manifest_binding_requirements() -> None:
    if not v20_84_inputs_available():
        return
    manifest = json.loads(V20_84_INPUTS["manifest"].read_text(encoding="utf-8"))
    assert_true(
        manifest["status"] in {
            "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS",
            "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
            "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS",
        },
        f"V20.84 manifest is not an accepted current status: {manifest['status']}",
    )
    assert_true(manifest["research_only"] is True, "V20.84 research_only invariant failed")
    assert_true(manifest["official_recommendation_created"] is False, "V20.84 recommendation invariant failed")
    assert_true(manifest["official_weight_mutated"] is False, "V20.84 weight invariant failed")
    assert_true(manifest["trade_action_created"] is False, "V20.84 trade invariant failed")
    for field in [
        "row_level_usable_evidence_count",
        "v20_82_fully_covered_component_count",
        "v20_82_partial_component_count",
        "v20_82_integration_status",
    ]:
        assert_true(field in manifest, f"V20.84 required integration field missing: {field}")
    assert_true(manifest["row_level_usable_evidence_count"] >= 0, f"V20.84 row-level evidence count invalid: {manifest}")
    assert_true(manifest["v20_82_fully_covered_component_count"] >= 0, f"current V20.84 covered component count invalid: {manifest}")
    assert_true(
        manifest["v20_82_integration_status"] in {"PARTIAL_BLOCK_MISSING_REQUIRED_PATHS", "FULL_COMPONENT_COVERAGE_AVAILABLE"},
        f"unexpected V20.84 integration status: {manifest}",
    )
    script_text = STAGE_SCRIPT.read_text(encoding="utf-8")
    for required in [
        "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_TABLE.csv",
        "V20_CURRENT_COMPONENT_EVIDENCE_COVERAGE_TABLE.csv",
        "V20_CURRENT_EVIDENCE_INPUT_BINDING_AUDIT.csv",
        "V20_CURRENT_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_MANIFEST.json",
        "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS",
        "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
        "row_level_usable_evidence_count",
        "v20_82_fully_covered_component_count",
        "v20_82_partial_component_count",
        "v20_82_integration_status",
        "PARTIAL_EVIDENCE_BOUND_BUT_REQUIRED_PATHS_INCOMPLETE",
    ]:
        assert_true(required in script_text, f"V20.82 does not enforce V20.84 binding requirement: {required}")


def test_v20_84_manifest_validator_rejects_invalid_manifests() -> None:
    if not v20_84_inputs_available():
        return
    module = load_stage_module()
    valid = {
        "status": "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
        "research_only": True,
        "official_recommendation_created": False,
        "official_weight_mutated": False,
        "trade_action_created": False,
        "row_level_usable_evidence_count": 5535,
        "v20_82_fully_covered_component_count": 0,
        "v20_82_partial_component_count": 275,
        "v20_82_integration_status": "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS",
    }
    cases = [
        {"status": "BLOCKED_V20_84_NO_USABLE_STRUCTURED_EVIDENCE"},
        {"research_only": False},
        {"official_recommendation_created": True},
        {"official_weight_mutated": True},
        {"trade_action_created": True},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        original_path = module.V20_84_MANIFEST
        try:
            module.V20_84_MANIFEST = manifest_path
            for override in cases:
                payload = dict(valid)
                payload.update(override)
                manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                ok, reason, _manifest = module.v20_84_manifest_valid()
                assert_true(not ok and reason == "V20_84_MANIFEST_INVARIANT_FAILURE", f"invalid V20.84 manifest accepted: {override}")
            for missing_field in [
                "row_level_usable_evidence_count",
                "v20_82_fully_covered_component_count",
                "v20_82_partial_component_count",
                "v20_82_integration_status",
            ]:
                payload = dict(valid)
                payload.pop(missing_field)
                manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                ok, reason, _manifest = module.v20_84_manifest_valid()
                assert_true(not ok and reason == "V20_84_MANIFEST_INVARIANT_FAILURE", f"missing V20.84 field accepted: {missing_field}")
            manifest_path.write_text(json.dumps(valid), encoding="utf-8")
            ok, reason, _manifest = module.v20_84_manifest_valid()
            assert_true(ok and reason == "V20_84_MANIFEST_VALID", f"valid V20.84 manifest rejected: {reason}")
        finally:
            module.V20_84_MANIFEST = original_path


def test_current_vs_shadow_scale_semantics() -> None:
    rows = read_csv(OUTPUTS["model_compare"])
    assert_true(rows, "model comparison empty")
    v20_83_rows = read_csv(CONSOLIDATION / "V20_CURRENT_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv")
    rank_like_tickers = {row["ticker"] for row in v20_83_rows if row.get("score_name") == "source_rank_or_score"}
    for row in rows:
        if row["current_score"] not in {"", "NA"} and row["shadow_adjusted_score"] not in {"", "NA"}:
            assert_true(row["score_comparison_valid"] in {"TRUE", "FALSE"}, f"score comparison validity missing: {row}")
            assert_true(row["shadow_score_scale"] in {"0_100", "0_100_NORMALIZED_FROM_0_1"}, f"shadow score scale not repaired: {row}")
        if row["ticker"] in rank_like_tickers and row["current_score"] not in {"", "NA"}:
            assert_true(row["current_score_scale"] == "RANK_ORDER_SCORE", f"rank-like current score labeled as normalized score: {row}")
            assert_true(row["score_comparison_valid"] == "FALSE", f"rank-like current score compared against normalized shadow score: {row}")
            if row["shadow_adjusted_score"] not in {"", "NA"}:
                assert_true("INVALID_SCORE_SCALE_CURRENT_RANK_ORDER_VS_SHADOW_NORMALIZED" in row["explanation"], f"invalid score-scale reason missing: {row}")
        if row["shadow_adjusted_rank"] == "NA":
            assert_true(row["rank_delta"] == "NA" or "INSUFFICIENT_COMPARABLE_SHADOW_SCORE" in row["explanation"], f"missing shadow rank implied meaningful delta: {row}")


def test_shadow_and_drawdown_integrity() -> None:
    strategy = read_csv(OUTPUTS["strategy"])
    shadow_rows = [row for row in strategy if row["strategy_name"].startswith("SHADOW_MULTI_PATH_ADJUSTED")]
    assert_true(shadow_rows, "shadow strategy rows missing")
    for row in shadow_rows:
        if row["model_return"] != "NA":
            assert_true("V20_76_SHADOW_OPERATIONAL_RANK_TABLE" in row["return_source"], f"shadow basket not sourced from explicit shadow table: {row}")
        else:
            assert_true(row["return_evidence_status"] in {"INSUFFICIENT_COMPARABLE_SHADOW_RANKING_EVIDENCE", "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT"}, f"shadow insufficiency reason missing: {row}")
    text = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert_true('drawdown_from_20d_high_pct") or row.get("distance_to_ma_20_pct' not in text, "drawdown uses distance_to_ma_20 fallback")


def test_hard_block_suppresses_shadow_alpha_outputs() -> None:
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    if manifest.get("status") != "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT":
        return
    nasdaq = read_csv(OUTPUTS["nasdaq"])
    for row in nasdaq:
        assert_true(row["passed_nasdaq_hurdle"] == "FALSE", f"Nasdaq hurdle passed during hard current-input block: {row}")
        if row["model_name"].startswith("SHADOW_MULTI_PATH_ADJUSTED"):
            assert_true(row["model_return"] == "NA", f"shadow model_return numeric during hard block: {row}")
            assert_true(row["excess_return_vs_qqq"] == "NA", f"shadow excess numeric during hard block: {row}")
            assert_true(row["return_evidence_status"] == "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT", f"shadow hard-block evidence status missing: {row}")
    benchmark = read_csv(OUTPUTS["benchmark"])
    for row in benchmark:
        if row["strategy_name"].startswith("SHADOW_MULTI_PATH_ADJUSTED"):
            assert_true(row["strategy_return"] == "NA", f"shadow strategy_return numeric during hard block: {row}")
            assert_true(row["excess_return"] == "NA", f"shadow benchmark excess numeric during hard block: {row}")
            assert_true(row["risk_adjusted_alpha"] == "NA", f"shadow risk_adjusted_alpha numeric during hard block: {row}")
            assert_true(row["return_evidence_status"] == "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT", f"shadow benchmark hard-block status missing: {row}")
            assert_true("Official current ranking is missing; strategy effectiveness comparison is blocked." in row["explanation"], f"blocked explanation missing: {row}")
    promotion = read_csv(OUTPUTS["promotion"])
    assert_true(all(row["nasdaq_hurdle_passed"] == "FALSE" for row in promotion), f"promotion Nasdaq hurdle passed during hard block: {promotion}")


def test_wrapper_does_not_hide_non_input_failures() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    catch_block = text.split("catch", 1)[1]
    assert_true("BLOCKED_V20_82_WRAPPER_FAILURE" in catch_block, "wrapper lacks generic failure status")
    assert_true('Write-Host "BLOCKED_V20_82_MISSING_REQUIRED_CURRENT_INPUT"' not in catch_block, "wrapper remaps catch failures to missing current input")


def test_no_hardcoded_stale_run_id() -> None:
    text = STAGE_SCRIPT.read_text(encoding="utf-8")
    forbidden_fragments = ["V20_37_202", "V20_38_202", "V20_39_202", "V20_40_202", "V20_57_202", "V20_64_202", "V20_65_202", "V20_66_202", "V20_79A_202", "V20_80_202", "V20_81_202"]
    assert_true(not any(fragment in text for fragment in forbidden_fragments), "hardcoded stale run_id-like fragment found")


def main() -> int:
    test_compile_and_parser()
    test_integration_run()
    test_outputs_exist_aliases_and_schemas()
    test_r5_detail_category_validation()
    test_r5_notes_only_certification_rejected()
    test_qqq_and_etf_contracts()
    test_etf_status_and_return_semantics()
    test_etf_certification_gate_rejects_substring_and_design_rows()
    test_research_only_and_manifest_invariants()
    test_input_binding_and_usable_evidence_semantics()
    test_no_official_or_trade_paths_and_promotion_block()
    test_promotion_nasdaq_hurdle_uses_certified_strategy_evidence_only()
    test_insufficient_evidence_status_blocks_promotion_nasdaq_hurdle()
    test_v20_83_manifest_binding_requirements()
    test_v20_83_manifest_validator_rejects_invalid_manifests()
    test_v20_84_manifest_binding_requirements()
    test_v20_84_manifest_validator_rejects_invalid_manifests()
    test_current_vs_shadow_scale_semantics()
    test_shadow_and_drawdown_integrity()
    test_hard_block_suppresses_shadow_alpha_outputs()
    test_wrapper_does_not_hide_non_input_failures()
    test_no_hardcoded_stale_run_id()
    print("PASS_V20_82_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
