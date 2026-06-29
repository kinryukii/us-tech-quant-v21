from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_045_r3_soft_combined_filter_threshold_relaxation_dry_run.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_045_r3_soft_combined_filter_threshold_relaxation_dry_run.ps1"
OPT = ROOT / "outputs" / "v21" / "optimization"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R1_DECISION = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R2_DECISION = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
REGISTER = OPT / "V21_045_R3_SOFT_FILTER_VARIANT_REGISTER.csv"
COLS = OPT / "V21_045_R3_SOFT_FILTER_COLUMN_AVAILABILITY_AUDIT.csv"
PANEL = OPT / "V21_045_R3_SOFT_FILTER_REBACKTEST_PANEL.csv"
SUMMARY = OPT / "V21_045_R3_SOFT_FILTER_VARIANT_WINDOW_SUMMARY.csv"
HIT_EXCESS = OPT / "V21_045_R3_SOFT_FILTER_HIT_RATE_EXCESS_COMPARISON.csv"
ATTRITION = OPT / "V21_045_R3_SOFT_FILTER_ATTRITION_USABILITY_AUDIT.csv"
CONC = OPT / "V21_045_R3_SOFT_FILTER_CONCENTRATION_AUDIT.csv"
PAYOFF = OPT / "V21_045_R3_SOFT_FILTER_PAYOFF_DOWNSIDE_AUDIT.csv"
DECISION = OPT / "V21_045_R3_SOFT_FILTER_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_045_R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN_REPORT.md",
    READ_CENTER / "CURRENT_V21_045_R3_SOFT_COMBINED_FILTER_THRESHOLD_RELAXATION_DRY_RUN_REPORT.md",
]
FALSE_GUARDRAILS = [
    "filter_adoption_allowed", "full_weight_result_available", "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
    "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
    "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
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


def imports(text: str) -> set[str]:
    tree = ast.parse(text)
    return {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}


def protected_snapshot() -> dict[Path, int]:
    snap: dict[Path, int] = {}
    for root in [ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action"]:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snap[path] = path.stat().st_mtime_ns
    for root in [ROOT / "outputs" / "v21", ROOT / "outputs" / "v20"]:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snap[path] = path.stat().st_mtime_ns
    return snap


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R3 production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imps = imports(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imps, "yfinance import exists")
    assert_true(not imps.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_045_r3_soft_combined_filter_threshold_relaxation_dry_run.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    assert_true(R1_DECISION.exists() and R1_DECISION.stat().st_size > 0, "R1 decision missing")
    assert_true(R2_DECISION.exists() and R2_DECISION.stat().st_size > 0, "R2 decision missing")
    before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_045_r3_soft_combined_filter_threshold_relaxation_dry_run.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_best_soft_filter_candidate=" in wrapper.stdout, "Wrapper best candidate missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")

    for path in [REGISTER, COLS, PANEL, SUMMARY, HIT_EXCESS, ATTRITION, CONC, PAYOFF, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    register = rows(REGISTER)
    variants = {r["filter_variant"] for r in register}
    assert_true("BASELINE_TECHNICAL_ONLY" in variants, "Baseline missing")
    assert_true("COMBINED_CONSERVATIVE_ORIGINAL" in variants, "Original combined missing")
    soft = [v for v in variants if v.startswith("SOFT_COMBINED_")]
    assert_true(len(soft) >= 5, "Fewer than five soft variants registered")
    assert_true(rows(SUMMARY), "Summary output empty")
    assert_true(rows(HIT_EXCESS), "Hit-rate/excess comparison empty")
    assert_true(rows(ATTRITION), "Attrition audit empty")
    assert_true(rows(CONC), "Concentration audit empty")
    assert_true(rows(PAYOFF), "Payoff/downside audit empty")

    summary = rows(DECISION)[0]
    assert_true(summary["filter_adopted"] == "FALSE", "Filter was adopted")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["soft_filter_relaxation_dry_run_only"] == "TRUE", "soft_filter_relaxation_dry_run_only must be TRUE")
    assert_true(summary["online_download_attempted"] == "FALSE", "Online download attempted")
    assert_true(summary["yfinance_used"] == "FALSE", "yfinance used")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    for output in [REGISTER, COLS, PANEL, SUMMARY, HIT_EXCESS, ATTRITION, CONC, PAYOFF, DECISION]:
        text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found: {output}")
    report_text = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only soft filter results must not be interpreted as full-weight results" in report_text, "Full-weight boundary missing")
    assert_true("No filter was adopted" in report_text, "No-adoption statement missing")

    for root in [ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action"]:
        if root.exists():
            created = [p for p in root.rglob("*V21_045_R3*") if p.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_045_r3_soft_combined_filter_threshold_relaxation_dry_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
