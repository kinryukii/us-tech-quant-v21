from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r8a_technical_only_ledger_maturity_wait_status.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r8a_technical_only_ledger_maturity_wait_status.ps1"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
R8_DECISION = REVIEW / "V21_044_R8_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
WAIT_SUMMARY = REVIEW / "V21_044_R8A_WAIT_STATUS_SUMMARY.csv"
PRICE_REQUIREMENT = REVIEW / "V21_044_R8A_PRICE_COVERAGE_REQUIREMENT.csv"
READINESS = REVIEW / "V21_044_R8A_MATURITY_READINESS_BY_WINDOW.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8A_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_044_R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R8A_TECHNICAL_ONLY_LEDGER_MATURITY_WAIT_STATUS_REPORT.md",
]

FALSE_GUARDRAILS = [
    "full_weight_result_available", "full_weight_rebacktest_allowed_now",
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


def protected_snapshot() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snapshot[path] = path.stat().st_mtime_ns
    official_roots = [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]
    for root in official_roots:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snapshot[path] = path.stat().st_mtime_ns
    return snapshot


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R8A production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    text = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in text.lower(), "Forbidden market-data package referenced")
    tree = ast.parse(text)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r8a_technical_only_ledger_maturity_wait_status.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    for path in [REFRESHED, PENDING, PRICE_AUDIT, MATURITY_AUDIT, R8_DECISION]:
        assert_true(path.exists() and path.stat().st_size > 0, f"R8 input missing: {path}")
    refreshed_before = REFRESHED.read_bytes()
    refreshed_rows_before = rows(REFRESHED)
    protected_before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r8a_technical_only_ledger_maturity_wait_status.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(REFRESHED.read_bytes() == refreshed_before, "R8 refreshed ledger was modified")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    for path in [WAIT_SUMMARY, PRICE_REQUIREMENT, READINESS, SCOPE_AUDIT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required R8A output missing: {path}")
    summary = rows(DECISION)[0]
    wait_summary = rows(WAIT_SUMMARY)
    assert_true(wait_summary, "Wait-status summary empty")
    assert_true(rows(PRICE_REQUIREMENT), "Price coverage requirement empty")
    assert_true(rows(READINESS), "Maturity readiness by window empty")

    assert_true(rows(R8_DECISION)[0]["final_status"] == "PARTIAL_PASS_V21_044_R8_NO_MATURED_ROWS_YET", "R8 no-maturity status not read")
    assert_true(summary["matured_rows"] == "0", "Expected zero matured rows")
    assert_true(summary["r9_result_evaluator_allowed_now"] == "FALSE", "R9 must be disallowed with zero matured rows")
    assert_true(summary["full_weight_result_available"] == "FALSE", "full_weight_result_available must be FALSE")
    assert_true(summary["full_weight_rebacktest_allowed_now"] == "FALSE", "full_weight_rebacktest_allowed_now must be FALSE")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["wait_status_only"] == "TRUE", "wait_status_only must be TRUE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    refreshed_rows_after = rows(REFRESHED)
    assert_true(len(refreshed_rows_after) == len(refreshed_rows_before), "New observation ledger rows appended")
    assert_true([row["observation_id"] for row in refreshed_rows_after] == [row["observation_id"] for row in refreshed_rows_before], "Observation IDs changed")
    assert_true(all(not row["realized_forward_return"] and not row["benchmark_forward_return"] and not row["excess_vs_QQQ"] for row in refreshed_rows_after), "Realized returns were fabricated")

    output_files = [WAIT_SUMMARY, PRICE_REQUIREMENT, READINESS, SCOPE_AUDIT, DECISION]
    for output in output_files:
        output_text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", output_text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
    for report in REPORTS:
        report_text = report.read_text(encoding="utf-8")
        assert_true("No buy/sell/hold recommendation was created" in report_text, "Required no-recommendation statement missing")
        assert_true("Technical-only observation must not be interpreted as full-weight result" in report_text, "Full-weight interpretation boundary missing")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R8A*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r8a_technical_only_ledger_maturity_wait_status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
