from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_045_r2_technical_only_filter_review_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_045_r2_technical_only_filter_review_gate.ps1"
OPT = ROOT / "outputs" / "v21" / "optimization"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R1_DECISION = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R1_PANEL = OPT / "V21_045_R1_FILTERED_REBACKTEST_PANEL.csv"
UPSTREAM = REVIEW / "V21_045_R2_UPSTREAM_READINESS_AUDIT.csv"
CANDIDATE = REVIEW / "V21_045_R2_CANDIDATE_FILTER_AUDIT.csv"
HIT = REVIEW / "V21_045_R2_HIT_RATE_IMPROVEMENT_AUDIT.csv"
EXCESS = REVIEW / "V21_045_R2_EXCESS_PRESERVATION_AUDIT.csv"
ATTRITION = REVIEW / "V21_045_R2_SAMPLE_ATTRITION_USABILITY_AUDIT.csv"
CONCENTRATION = REVIEW / "V21_045_R2_CONCENTRATION_AUDIT.csv"
PAYOFF = REVIEW / "V21_045_R2_PAYOFF_DOWNSIDE_AUDIT.csv"
SCOPE = REVIEW / "V21_045_R2_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_045_R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE_REPORT.md",
    READ_CENTER / "CURRENT_V21_045_R2_TECHNICAL_ONLY_FILTER_REVIEW_GATE_REPORT.md",
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
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=300)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def import_roots(text: str) -> set[str]:
    tree = ast.parse(text)
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }


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


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R2 production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imports = import_roots(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imports, "yfinance import exists")
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_045_r2_technical_only_filter_review_gate.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    assert_true(R1_DECISION.exists() and R1_DECISION.stat().st_size > 0, "R1 decision missing")
    assert_true(R1_PANEL.exists() and R1_PANEL.stat().st_size > 0, "R1 panel missing")
    protected_before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_045_r2_technical_only_filter_review_gate.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_sample_attrition_warning=" in wrapper.stdout, "Wrapper attrition warning missing")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    for path in [UPSTREAM, CANDIDATE, HIT, EXCESS, ATTRITION, CONCENTRATION, PAYOFF, SCOPE, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    assert_true(rows(CANDIDATE), "Candidate filter audit empty")
    assert_true(rows(HIT), "Hit-rate improvement audit empty")
    assert_true(rows(EXCESS), "Excess preservation audit empty")
    attr_rows = rows(ATTRITION)
    assert_true(attr_rows, "Sample attrition audit empty")
    assert_true(rows(PAYOFF), "Payoff/downside audit empty")
    summary = rows(DECISION)[0]

    assert_true(summary["best_candidate_filter"] == "COMBINED_CONSERVATIVE_FILTER", "Best candidate filter mismatch")
    assert_true(summary["sample_attrition_warning"] in {"SEVERE_ATTRITION_WARNING", "EXTREME_ATTRITION_WARNING"}, "Severe/extreme attrition warning missing")
    assert_true(any(row["usability_status"] in {"SEVERE_ATTRITION_WARNING", "EXTREME_ATTRITION_WARNING"} for row in attr_rows), "Attrition audit missing severe/extreme warning")
    assert_true(summary["filter_adopted"] == "FALSE", "Filter was marked adopted")
    assert_true(summary["filter_adoptable_now"] == "FALSE", "Filter marked adoptable")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["review_gate_only"] == "TRUE", "review_gate_only must be TRUE")
    assert_true(summary["online_download_attempted"] == "FALSE", "Online download attempted")
    assert_true(summary["yfinance_used"] == "FALSE", "yfinance used")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    for output in [UPSTREAM, CANDIDATE, HIT, EXCESS, ATTRITION, CONCENTRATION, PAYOFF, SCOPE, DECISION]:
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
            created = [path for path in root.rglob("*V21_045_R2*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_045_r2_technical_only_filter_review_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
