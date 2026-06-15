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

STAGE_SCRIPT = SCRIPT_DIR / "v20_87_downside_risk_evidence_export.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_87_downside_risk_evidence_export.py"
WRAPPER = SCRIPT_DIR / "run_v20_87_downside_risk_evidence_export.ps1"

OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT.csv",
    "coverage": CONSOLIDATION / "V20_87_DOWNSIDE_RISK_COMPONENT_COVERAGE.csv",
    "report": READ_CENTER / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_REPORT.md",
    "summary": OPS / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_SUMMARY.json",
    "manifest": OPS / "V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORT_MANIFEST.json",
}
EVIDENCE_SCHEMA = ["ticker", "signal_date", "as_of_date", "evidence_component_id", "path_id", "strategy_id", "benchmark_id", "forward_window", "row_level_return", "benchmark_return", "excess_return_vs_benchmark", "negative_return_flag", "benchmark_underperformance_flag", "downside_threshold_breach_flag", "drawdown_proxy", "downside_proxy", "downside_evidence_usable_flag", "downside_evidence_certified_flag", "missing_reason", "source_stage", "source_artifact", "source_run_id"]
COVERAGE_SCHEMA = ["evidence_component_id", "required_downside_fields", "available_downside_fields", "usable_row_count", "certified_row_count", "missing_required_field_count", "coverage_status", "can_contribute_to_v20_82_closure", "blocker_reason"]
ALLOWED_STATUSES = {
    "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE",
    "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_FULL_COVERAGE",
    "BLOCKED_V20_87_MISSING_REQUIRED_UPSTREAM_EVIDENCE",
    "BLOCKED_V20_87_UNSAFE_UPSTREAM_GUARDRAIL",
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
    return path.with_name(path.name.replace("V20_87_", "V20_CURRENT_", 1))


def wrapper_final_status(stdout: str) -> str:
    tokens = re.findall(r"\b(?:PASS|BLOCKED)_V20_87_[A-Z0-9_]+\b", stdout)
    return tokens[-1] if tokens else ""


def load_stage_module():
    spec = importlib.util.spec_from_file_location("v20_87_stage_under_test", STAGE_SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "unable to load V20.87 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tracked_v20_47_to_86_artifacts() -> list[Path]:
    result = run_command(["git", "ls-files"])
    assert_true(result.returncode == 0, f"git ls-files failed: {result.stdout}\n{result.stderr}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        normalized = line.strip().replace("\\", "/")
        if not normalized.startswith(("inputs/", "outputs/")):
            continue
        upper = normalized.upper()
        if "V20_87" in upper or "V20_CURRENT_DOWNSIDE_RISK" in upper:
            continue
        if any(f"V20_{number}" in upper for number in range(47, 87)):
            paths.append(ROOT / normalized)
    return sorted(paths)


def artifact_snapshot(paths: list[Path]) -> dict[str, tuple[str, int]]:
    snapshot: dict[str, tuple[str, int]] = {}
    for path in paths:
        snapshot[path.relative_to(ROOT).as_posix()] = (file_digest(path), path.stat().st_size if path.exists() else -1)
    return snapshot


def test_compile_parser_wrapper_and_mutation_guard() -> None:
    for path in [STAGE_SCRIPT, TEST_SCRIPT]:
        result = run_command([sys.executable, "-m", "py_compile", str(path)])
        assert_true(result.returncode == 0, f"py_compile failed for {path}: {result.stdout}\n{result.stderr}")
    parse = run_command([
        "powershell",
        "-NoProfile",
        "-Command",
        "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_87_downside_risk_evidence_export.ps1'), [ref]$null); 'PARSE_OK'",
    ])
    assert_true(parse.returncode == 0 and "PARSE_OK" in parse.stdout, f"PowerShell parser check failed: {parse.stdout}\n{parse.stderr}")
    before_scripts = {path: path.read_bytes() for path in SCRIPT_DIR.glob("v20_[4-8][0-9]*.py") if not path.name.startswith("v20_87_")}
    tracked_artifacts = tracked_v20_47_to_86_artifacts()
    before_artifacts = artifact_snapshot(tracked_artifacts)
    result = run_command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    status = wrapper_final_status(result.stdout)
    assert_true(status == "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", f"unexpected wrapper status {status!r}: {result.stdout}\n{result.stderr}")
    after_scripts = {path: path.read_bytes() for path in before_scripts}
    assert_true(before_scripts == after_scripts, "V20.87 mutated V20.47-V20.86 production scripts")
    after_artifacts = artifact_snapshot(tracked_artifacts)
    changed = [path for path, value in before_artifacts.items() if after_artifacts.get(path) != value]
    assert_true(not changed, "V20.87 mutated tracked V20.47-V20.86 artifacts: " + "; ".join(changed[:20]))


def test_outputs_aliases_schema_and_summary() -> None:
    for key, path in OUTPUTS.items():
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
        alias = alias_path(path)
        assert_true(alias.exists() and alias.stat().st_size > 0, f"missing or empty alias: {alias}")
        assert_true(path.read_bytes() == alias.read_bytes(), f"alias differs for {path}")
    assert_true(fields(OUTPUTS["evidence"]) == EVIDENCE_SCHEMA, f"evidence schema mismatch: {fields(OUTPUTS['evidence'])}")
    assert_true(fields(OUTPUTS["coverage"]) == COVERAGE_SCHEMA, f"coverage schema mismatch: {fields(OUTPUTS['coverage'])}")
    evidence = read_csv(OUTPUTS["evidence"])
    coverage = read_csv(OUTPUTS["coverage"])
    assert_true(evidence, "evidence output has no rows")
    assert_true(coverage, "coverage output has no rows")
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    summary = json.loads(OUTPUTS["summary"].read_text(encoding="utf-8"))
    for obj in [manifest, summary]:
        assert_true(obj["can_clear_v20_82_blocker_now"] is False, f"V20.87 claims it can clear blocker: {obj}")
        assert_true(obj["official_recommendation_created"] is False, f"recommendation flag changed: {obj}")
        assert_true(obj["weight_mutation_created"] is False, f"weight mutation flag changed: {obj}")
        assert_true(obj["trade_action_created"] is False, f"trade action flag changed: {obj}")
    assert_true(manifest["status"] == "PASS_V20_87_DOWNSIDE_RISK_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", f"unexpected manifest status: {manifest}")
    assert_true(summary["upstream_v20_82_status"] == "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE", f"V20.82 blocker not preserved: {summary}")
    assert_true(summary["upstream_v20_84_integration_status"] == "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS", f"V20.84 partial status not preserved: {summary}")


def test_downside_coverage_semantics() -> None:
    evidence = read_csv(OUTPUTS["evidence"])
    coverage = read_csv(OUTPUTS["coverage"])
    assert_true(any(row["downside_evidence_usable_flag"] == "TRUE" for row in evidence), "no usable downside evidence rows exported")
    assert_true(all(row["can_contribute_to_v20_82_closure"] == "FALSE" for row in coverage), "V20.87 coverage contributes to V20.82 closure directly")
    assert_true(any(row["coverage_status"] == "PARTIAL_COVERAGE" for row in coverage), "partial coverage not represented")
    assert_true(not any(row["coverage_status"] == "FULLY_COVERED" and row["missing_required_field_count"] != "0" for row in coverage), "full coverage row has missing required fields")
    assert_true(any("DRAWDOWN_OR_DOWNSIDE_PROXY" in row["missing_reason"] for row in evidence), "missing drawdown/downside proxy not surfaced")


def test_structured_certification_not_free_text_notes() -> None:
    module = load_stage_module()
    free_text_row = {
        "component_name": "SYNTH",
        "evidence_path": "HISTORICAL_BACKTEST",
        "metric_name": "average_return",
        "metric_value": "-0.100000",
        "metric_unit": "RETURN_DECIMAL",
        "evaluation_window": "forward_20d",
        "benchmark_name": "QQQ",
        "benchmark_return": "-0.050000",
        "excess_return": "-0.050000",
        "drawdown": "-0.120000",
        "certification_status": "",
        "certification_reason": "notes=CERTIFIED_DOWNSIDE_RISK_EVIDENCE",
        "usable_for_v20_82": "TRUE",
        "research_only": "TRUE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "source_stage": "SYNTH",
        "source_file": "synthetic.csv",
        "source_run_id": "SYNTH_RUN",
    }
    rows = module.transform_evidence_rows([free_text_row])
    assert_true(rows[0]["downside_evidence_usable_flag"] == "TRUE", f"synthetic row should be usable: {rows}")
    assert_true(rows[0]["downside_evidence_certified_flag"] == "FALSE", f"free-text note certified downside evidence: {rows}")
    partial_row = dict(free_text_row)
    partial_row["certification_status"] = "CERTIFIED_DOWNSIDE_RISK_EVIDENCE"
    partial_row["benchmark_return"] = "NA"
    partial_row["drawdown"] = "NA"
    partial = module.transform_evidence_rows([partial_row])
    coverage = module.build_component_coverage(partial)
    assert_true(coverage[0]["coverage_status"] == "PARTIAL_COVERAGE", f"partial synthetic row marked fully covered: {coverage}")
    assert_true(coverage[0]["can_contribute_to_v20_82_closure"] == "FALSE", f"partial synthetic row contributes to V20.82 closure: {coverage}")


def test_no_official_or_trade_surface() -> None:
    tree = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
    forbidden_imports = {"requests", "urllib", "httpx", "yfinance", "alpaca_trade_api", "ibapi", "ccxt"}
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0].lower() for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0].lower())
    assert_true(not (set(imports) & forbidden_imports), "network/broker import introduced")
    names = [path.name.upper() for path in OUTPUTS.values()] + [alias_path(path).name.upper() for path in OUTPUTS.values()]
    forbidden = ["OFFICIAL_RECOMMENDATION", "OFFICIAL_WEIGHT", "TRADE_ORDER", "BROKER", "BUY_ORDER", "SELL_ORDER"]
    assert_true(not any(token in name for token in forbidden for name in names), "official/trade output name created")
    text = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert_true("V20_87_202" not in text, "hardcoded run_id-like fragment found")
    report = OUTPUTS["report"].read_text(encoding="utf-8")
    for phrase in [
        "V20.87 is research-only",
        "does not clear V20.82's insufficient-evidence blocker",
        "No official recommendation, weight mutation, portfolio mutation, order, broker action, or trade action is created.",
        "Free-text notes alone are not accepted as certification.",
    ]:
        assert_true(phrase in report, f"report phrase missing: {phrase}")


def main() -> int:
    test_compile_parser_wrapper_and_mutation_guard()
    test_outputs_aliases_schema_and_summary()
    test_downside_coverage_semantics()
    test_structured_certification_not_free_text_notes()
    test_no_official_or_trade_surface()
    print("PASS_V20_87_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
