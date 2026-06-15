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

STAGE_SCRIPT = SCRIPT_DIR / "v20_86_regime_conditioned_evidence_export.py"
TEST_SCRIPT = SCRIPT_DIR / "test_v20_86_regime_conditioned_evidence_export.py"
WRAPPER = SCRIPT_DIR / "run_v20_86_regime_conditioned_evidence_export.ps1"

OUTPUTS = {
    "evidence": CONSOLIDATION / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT.csv",
    "coverage": CONSOLIDATION / "V20_86_REGIME_CONDITIONED_COMPONENT_COVERAGE.csv",
    "bucket": CONSOLIDATION / "V20_86_REGIME_BUCKET_SUMMARY.csv",
    "report": READ_CENTER / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_REPORT.md",
    "summary": OPS / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_SUMMARY.json",
    "manifest": OPS / "V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORT_MANIFEST.json",
}
EVIDENCE_SCHEMA = ["ticker", "signal_date", "as_of_date", "evidence_component_id", "path_id", "strategy_id", "benchmark_id", "benchmark_symbol", "forward_window", "row_level_return", "benchmark_return", "excess_return_vs_benchmark", "negative_return_flag", "benchmark_underperformance_flag", "downside_threshold_breach_flag", "regime_id", "regime_label", "market_regime", "qqq_trend_regime", "spy_trend_regime", "semiconductor_regime", "soxx_regime", "volatility_regime", "vix_bucket", "risk_on_off_state", "macro_event_window_flag", "earnings_season_flag", "regime_evidence_usable_flag", "regime_evidence_certified_flag", "certification_source_field", "certification_source_stage", "missing_reason", "source_stage", "source_artifact", "source_run_id"]
COVERAGE_SCHEMA = ["evidence_component_id", "required_regime_fields", "available_regime_fields", "usable_row_count", "certified_row_count", "regime_count", "required_regime_count", "missing_required_regime_count", "regime_labels_available", "regime_labels_missing", "benchmark_symbols_available", "coverage_status", "can_contribute_to_v20_82_closure", "blocker_reason"]
BUCKET_SCHEMA = ["regime_label", "market_regime", "qqq_trend_regime", "spy_trend_regime", "semiconductor_regime", "volatility_regime", "usable_row_count", "certified_row_count", "positive_return_count", "negative_return_count", "benchmark_outperformance_count", "benchmark_underperformance_count", "downside_threshold_breach_count", "average_row_level_return", "average_benchmark_return", "average_excess_return_vs_benchmark", "coverage_status"]


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
    return path.with_name(path.name.replace("V20_86_", "V20_CURRENT_", 1))


def wrapper_final_status(stdout: str) -> str:
    tokens = re.findall(r"\b(?:PASS|BLOCKED)_V20_86_[A-Z0-9_]+\b", stdout)
    return tokens[-1] if tokens else ""


def load_stage_module():
    spec = importlib.util.spec_from_file_location("v20_86_stage_under_test", STAGE_SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "unable to load V20.86 module")
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


def tracked_v20_47_to_88_artifacts() -> list[Path]:
    result = run_command(["git", "ls-files"])
    assert_true(result.returncode == 0, f"git ls-files failed: {result.stdout}\n{result.stderr}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        normalized = line.strip().replace("\\", "/")
        if not normalized.startswith(("inputs/", "outputs/")):
            continue
        upper = normalized.upper()
        if "V20_86" in upper or "V20_CURRENT_REGIME_CONDITIONED" in upper or "V20_CURRENT_REGIME_BUCKET" in upper:
            continue
        if any(f"V20_{number}" in upper for number in range(47, 89)):
            paths.append(ROOT / normalized)
    return sorted(paths)


def artifact_snapshot(paths: list[Path]) -> dict[str, tuple[str, int]]:
    return {path.relative_to(ROOT).as_posix(): (file_digest(path), path.stat().st_size if path.exists() else -1) for path in paths}


def test_compile_parser_wrapper_and_mutation_guard() -> None:
    for path in [STAGE_SCRIPT, TEST_SCRIPT]:
        result = run_command([sys.executable, "-m", "py_compile", str(path)])
        assert_true(result.returncode == 0, f"py_compile failed for {path}: {result.stdout}\n{result.stderr}")
    parse = run_command(["powershell", "-NoProfile", "-Command", "$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v20/run_v20_86_regime_conditioned_evidence_export.ps1'), [ref]$null); 'PARSE_OK'"])
    assert_true(parse.returncode == 0 and "PARSE_OK" in parse.stdout, f"PowerShell parser check failed: {parse.stdout}\n{parse.stderr}")
    before_scripts = {path: path.read_bytes() for path in SCRIPT_DIR.glob("v20_[4-8][0-9]*.py") if not path.name.startswith("v20_86_")}
    artifacts = tracked_v20_47_to_88_artifacts()
    before_artifacts = artifact_snapshot(artifacts)
    result = run_command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)])
    status = wrapper_final_status(result.stdout)
    assert_true(status == "PASS_V20_86_REGIME_CONDITIONED_EVIDENCE_EXPORTED_WITH_PARTIAL_COVERAGE", f"unexpected wrapper status {status!r}: {result.stdout}\n{result.stderr}")
    assert_true(before_scripts == {path: path.read_bytes() for path in before_scripts}, "V20.86 mutated V20.47-V20.88 production scripts")
    changed = [path for path, value in before_artifacts.items() if artifact_snapshot(artifacts).get(path) != value]
    assert_true(not changed, "V20.86 mutated tracked V20.47-V20.88 artifacts: " + "; ".join(changed[:20]))


def test_outputs_aliases_schema_and_summary() -> None:
    for key, path in OUTPUTS.items():
        assert_true(path.exists() and path.stat().st_size > 0, f"missing or empty output: {path}")
        alias = alias_path(path)
        assert_true(alias.exists() and alias.stat().st_size > 0, f"missing or empty alias: {alias}")
        assert_true(path.read_bytes() == alias.read_bytes(), f"alias differs for {path}")
    assert_true(fields(OUTPUTS["evidence"]) == EVIDENCE_SCHEMA, f"evidence schema mismatch: {fields(OUTPUTS['evidence'])}")
    assert_true(fields(OUTPUTS["coverage"]) == COVERAGE_SCHEMA, f"coverage schema mismatch: {fields(OUTPUTS['coverage'])}")
    assert_true(fields(OUTPUTS["bucket"]) == BUCKET_SCHEMA, f"bucket schema mismatch: {fields(OUTPUTS['bucket'])}")
    manifest = json.loads(OUTPUTS["manifest"].read_text(encoding="utf-8"))
    summary = json.loads(OUTPUTS["summary"].read_text(encoding="utf-8"))
    for obj in [manifest, summary]:
        assert_true(obj["can_clear_v20_82_blocker_now"] is False, f"V20.86 claims it can clear blocker: {obj}")
        assert_true(obj["official_recommendation_created"] is False, f"recommendation flag changed: {obj}")
        assert_true(obj["weight_mutation_created"] is False, f"weight mutation flag changed: {obj}")
        assert_true(obj["portfolio_mutation_created"] is False, f"portfolio mutation flag changed: {obj}")
        assert_true(obj["trade_action_created"] is False, f"trade action flag changed: {obj}")
    assert_true(summary["upstream_v20_82_status"] == "BLOCKED_V20_82_INSUFFICIENT_MULTI_PATH_EVIDENCE", f"V20.82 blocker not preserved: {summary}")
    assert_true(summary["upstream_v20_84_integration_status"] == "PARTIAL_BLOCK_MISSING_REQUIRED_PATHS", f"V20.84 partial status not preserved: {summary}")
    assert_true(summary["certified_regime_evidence_count"] == 0, f"current upstream rows should not be certified without structured certification fields: {summary}")


def test_regime_coverage_semantics() -> None:
    evidence = read_csv(OUTPUTS["evidence"])
    coverage = read_csv(OUTPUTS["coverage"])
    buckets = read_csv(OUTPUTS["bucket"])
    assert_true(evidence and coverage and buckets, "V20.86 outputs are empty")
    assert_true(any(row["regime_evidence_usable_flag"] == "TRUE" for row in evidence), "no usable regime evidence rows exported")
    assert_true(all(row["regime_evidence_certified_flag"] == "FALSE" for row in evidence), "uncertified current upstream rows were certified")
    assert_true(all(row["can_contribute_to_v20_82_closure"] == "FALSE" for row in coverage), "V20.86 contributes to V20.82 closure directly")
    assert_true(any(row["coverage_status"] == "PARTIAL_COVERAGE" for row in coverage), "partial regime coverage not represented")
    assert_true(any(row["benchmark_symbols_available"] != "NA" for row in coverage), "benchmark symbols not carried into regime coverage")


def test_synthetic_certification_rules() -> None:
    module = load_stage_module()
    base = {
        "strategy_name": "SYNTH",
        "benchmark_name": "QQQ_BUY_AND_HOLD",
        "evaluation_window": "forward_20d",
        "return_source": "synthetic.csv",
        "strategy_return": "0.10",
        "benchmark_return": "0.07",
        "excess_return": "0.03",
        "regime": "RISK_ON",
        "explanation": "CERTIFIED_REGIME_CONDITIONED_EVIDENCE",
    }
    rows = module.transform_rows([base], {})
    assert_true(rows[0]["regime_evidence_usable_flag"] == "TRUE", f"complete synthetic row should be usable: {rows}")
    assert_true(rows[0]["regime_evidence_certified_flag"] == "FALSE", f"free-text explanation certified regime evidence: {rows}")
    no_cert = dict(base)
    rows = module.transform_rows([no_cert], {})
    assert_true(rows[0]["regime_evidence_usable_flag"] == "TRUE" and rows[0]["regime_evidence_certified_flag"] == "FALSE", f"no structured cert row not usable/not certified as expected: {rows}")
    missing_regime = dict(base)
    missing_regime["regime"] = ""
    coverage = module.build_coverage(module.transform_rows([missing_regime], {}))
    assert_true(coverage[0]["coverage_status"] != "FULLY_COVERED", f"missing regime row marked fully covered: {coverage}")
    missing_source = dict(base)
    missing_source["return_source"] = ""
    coverage = module.build_coverage(module.transform_rows([missing_source], {}))
    assert_true(coverage[0]["can_contribute_to_v20_82_closure"] == "FALSE", f"missing source row contributes to V20.82 closure: {coverage}")
    generic = dict(base)
    generic["benchmark_name"] = "SPY_BUY_AND_HOLD"
    generic["market_regime"] = "RISK_ON"
    generic["regime"] = "RISK_ON"
    generic["regime_conditioned_certification_status"] = "CERTIFIED_REGIME_CONDITIONED_EVIDENCE"
    coverage = module.build_coverage(module.transform_rows([generic], {}))
    assert_true(coverage[0]["coverage_status"] == "PARTIAL_COVERAGE", f"generic regime without QQQ-linked context should be partial: {coverage}")
    certified = dict(base)
    certified["regime_conditioned_certification_status"] = "CERTIFIED_REGIME_CONDITIONED_EVIDENCE"
    certified["risk_off_certification_status"] = ""
    rows = module.transform_rows([certified], {})
    assert_true(rows[0]["regime_evidence_certified_flag"] == "TRUE", f"structured positive certification not accepted: {rows}")


def test_no_official_or_trade_surface_and_report() -> None:
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
    assert_true("V20_86_202" not in STAGE_SCRIPT.read_text(encoding="utf-8"), "hardcoded run_id-like fragment found")
    report = OUTPUTS["report"].read_text(encoding="utf-8")
    for phrase in [
        "V20.86 is research-only",
        "does not clear V20.82's insufficient-evidence blocker",
        "No official recommendation, weight mutation, portfolio mutation, order, broker action, or trade action is created.",
        "Free-text notes alone are not accepted as certification.",
    ]:
        assert_true(phrase in report, f"report phrase missing: {phrase}")


def main() -> int:
    test_compile_parser_wrapper_and_mutation_guard()
    test_outputs_aliases_schema_and_summary()
    test_regime_coverage_semantics()
    test_synthetic_certification_rules()
    test_no_official_or_trade_surface_and_report()
    print("PASS_V20_86_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
