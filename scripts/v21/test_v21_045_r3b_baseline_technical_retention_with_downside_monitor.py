from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_045_r3b_baseline_technical_retention_with_downside_monitor.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_045_r3b_baseline_technical_retention_with_downside_monitor.ps1"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
OPT = ROOT / "outputs" / "v21" / "optimization"

R1 = OPT / "V21_045_R1_FILTER_OPTIMIZATION_DECISION_SUMMARY.csv"
R2 = REVIEW / "V21_045_R2_FILTER_REVIEW_DECISION_SUMMARY.csv"
R3 = OPT / "V21_045_R3_SOFT_FILTER_DECISION_SUMMARY.csv"
UPSTREAM = REVIEW / "V21_045_R3B_UPSTREAM_CHAIN_AUDIT.csv"
REJECTION = REVIEW / "V21_045_R3B_FILTER_REJECTION_AUDIT.csv"
RETENTION = REVIEW / "V21_045_R3B_BASELINE_RETENTION_AUDIT.csv"
CONTRACT = REVIEW / "V21_045_R3B_DOWNSIDE_MONITOR_CONTRACT.csv"
ROUTING = REVIEW / "V21_045_R3B_FUTURE_DECISION_ROUTING.csv"
SCOPE = REVIEW / "V21_045_R3B_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_045_R3B_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_045_R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR_REPORT.md",
    READ_CENTER / "CURRENT_V21_045_R3B_BASELINE_TECHNICAL_RETENTION_WITH_DOWNSIDE_MONITOR_REPORT.md",
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
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=300)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def import_roots(text: str) -> set[str]:
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
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R3B production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imps = import_roots(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imps, "yfinance import exists")
    assert_true(not imps.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")
    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_045_r3b_baseline_technical_retention_with_downside_monitor.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parse failed")

    for path in [R1, R2, R3]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required upstream missing: {path}")
    before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_045_r3b_baseline_technical_retention_with_downside_monitor.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper status missing")
    assert_true("wrapper_retained_stream=BASELINE_TECHNICAL_ONLY" in wrapper.stdout, "Wrapper retained stream missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")

    for path in [UPSTREAM, REJECTION, RETENTION, CONTRACT, ROUTING, SCOPE, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    assert_true(rows(REJECTION), "Filter rejection audit empty")
    assert_true(rows(RETENTION), "Baseline retention audit empty")
    assert_true(rows(CONTRACT), "Downside monitor contract empty")
    assert_true(rows(ROUTING), "Future decision routing empty")

    summary = rows(DECISION)[0]
    assert_true(summary["retained_stream"] == "BASELINE_TECHNICAL_ONLY", "retained_stream mismatch")
    assert_true(summary["filter_adoption_allowed"] == "FALSE", "Filter adoption allowed")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["retention_monitor_only"] == "TRUE", "retention_monitor_only must be TRUE")
    assert_true(summary["online_download_attempted"] == "FALSE", "Online download attempted")
    assert_true(summary["yfinance_used"] == "FALSE", "yfinance used")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")
    assert_true(all(row["adoption_allowed"] == "FALSE" for row in rows(REJECTION)), "A filter adoption row was allowed")

    for output in [UPSTREAM, REJECTION, RETENTION, CONTRACT, ROUTING, SCOPE, DECISION]:
        text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
    report_text = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only retention is not full-weight evidence" in report_text, "Full-weight boundary missing")
    assert_true("No filter was adopted" in report_text, "No-adoption statement missing")

    for root in [ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action"]:
        if root.exists():
            created = [p for p in root.rglob("*V21_045_R3B*") if p.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")
    print("PASS test_v21_045_r3b_baseline_technical_retention_with_downside_monitor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
