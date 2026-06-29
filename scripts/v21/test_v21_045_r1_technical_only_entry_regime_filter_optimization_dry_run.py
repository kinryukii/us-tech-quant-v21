from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_045_r1_technical_only_entry_regime_filter_optimization_dry_run.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_045_r1_technical_only_entry_regime_filter_optimization_dry_run.ps1"
OPT = ROOT / "outputs" / "v21" / "optimization"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"

R5_PANEL = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R5_SUMMARY = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
COL_AUDIT = OPT / "V21_045_R1_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
REGISTER = OPT / "V21_045_R1_FILTER_VARIANT_DEFINITION_REGISTER.csv"
FILTERED_PANEL = OPT / "V21_045_R1_FILTERED_REBACKTEST_PANEL.csv"
WINDOW_SUMMARY = OPT / "V21_045_R1_FILTER_VARIANT_WINDOW_SUMMARY.csv"
HIT_PAYOFF = OPT / "V21_045_R1_FILTER_HIT_RATE_AND_PAYOFF_AUDIT.csv"
DOWNSIDE = OPT / "V21_045_R1_FILTER_DOWNSIDE_AUDIT.csv"
ATTRITION = OPT / "V21_045_R1_FILTER_SAMPLE_ATTRITION_AUDIT.csv"
DECISION = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_045_R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN_REPORT.md",
    READ_CENTER / "CURRENT_V21_045_R1_TECHNICAL_ONLY_ENTRY_REGIME_FILTER_OPTIMIZATION_DRY_RUN_REPORT.md",
]

FALSE_GUARDRAILS = [
    "filter_adoption_allowed",
    "full_weight_result_available",
    "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed",
    "official_weight_mutation",
    "official_ranking_mutation",
    "official_recommendation_allowed",
    "real_book_action_allowed",
    "broker_execution_allowed",
    "trade_action_allowed",
    "shadow_gate_allowed",
    "shadow_adoption_allowed",
]


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=600)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def protected_snapshot() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    roots = [
        ROOT / "outputs" / "v22",
        ROOT / "outputs" / "v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "trade_action",
    ]
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snapshot[path] = path.stat().st_mtime_ns
    for root in [ROOT / "outputs" / "v21", ROOT / "outputs" / "v20"]:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snapshot[path] = path.stat().st_mtime_ns
    return snapshot


def import_roots(text: str) -> set[str]:
    tree = ast.parse(text)
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "V21.045-R1 production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    script_text = SCRIPT.read_text(encoding="utf-8")
    imports = import_roots(script_text)
    assert_true("yfinance" not in imports, "yfinance import exists")
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_045_r1_technical_only_entry_regime_filter_optimization_dry_run.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    assert_true(R5_PANEL.exists() and R5_PANEL.stat().st_size > 0, "R5 panel missing")
    assert_true(R5_SUMMARY.exists() and R5_SUMMARY.stat().st_size > 0, "R5 summary missing")
    protected_before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_045_r1_technical_only_entry_regime_filter_optimization_dry_run.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_best_filter_candidate=" in wrapper.stdout, "Wrapper best candidate missing")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    for path in [COL_AUDIT, REGISTER, FILTERED_PANEL, WINDOW_SUMMARY, HIT_PAYOFF, DOWNSIDE, ATTRITION, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    assert_true(rows(COL_AUDIT), "Filter column availability audit empty")
    register = rows(REGISTER)
    variants = {row["filter_variant"] for row in register}
    for required in [
        "BASELINE_TECHNICAL_ONLY",
        "OVERHEAT_EXCLUSION_FILTER",
        "PULLBACK_HEALTHY_TREND_FILTER",
        "QQQ_REGIME_FILTER",
        "COMBINED_CONSERVATIVE_FILTER",
    ]:
        assert_true(required in variants, f"Missing variant definition: {required}")
    assert_true(rows(WINDOW_SUMMARY), "Window summary empty")
    assert_true(rows(HIT_PAYOFF), "Hit-rate/payoff audit empty")
    assert_true(rows(DOWNSIDE), "Downside audit empty")
    assert_true(rows(ATTRITION), "Sample attrition audit empty")
    assert_true(all(row["filter_adopted"] == "FALSE" for row in register), "A filter was marked adopted")

    summary = rows(DECISION)[0]
    assert_true(summary["baseline_source"] == "V21_044_R5_CANONICAL_CONSERVATIVE", "Canonical R5 baseline not read/reconstructed")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["optimization_dry_run_only"] == "TRUE", "optimization_dry_run_only must be TRUE")
    assert_true(summary["online_download_attempted"] == "FALSE", "Online download attempted")
    assert_true(summary["yfinance_used"] == "FALSE", "yfinance used")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    for output in [COL_AUDIT, REGISTER, FILTERED_PANEL, WINDOW_SUMMARY, HIT_PAYOFF, DOWNSIDE, ATTRITION, DECISION]:
        text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
    report_text = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only filter results must not be interpreted as full-weight results" in report_text, "Full-weight boundary missing")
    assert_true("No filter was adopted" in report_text, "No-adoption statement missing")

    forbidden_roots = [
        ROOT / "outputs" / "v22",
        ROOT / "outputs" / "v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_045_R1*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_045_r1_technical_only_entry_regime_filter_optimization_dry_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
