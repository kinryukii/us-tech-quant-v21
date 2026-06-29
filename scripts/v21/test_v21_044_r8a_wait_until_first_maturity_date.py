from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r8a_wait_until_first_maturity_date.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r8a_wait_until_first_maturity_date.ps1"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R8_R1_DECISION = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
R8_R1_LEDGER = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv"
R8_R1_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"

WAIT_SUMMARY = REVIEW / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_SUMMARY.csv"
GATE_STATUS = REVIEW / "V21_044_R8A_MATURITY_GATE_STATUS.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8A_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R8A_WAIT_UNTIL_FIRST_MATURITY_DATE_REPORT.md",
]

FALSE_GUARDRAILS = [
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
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "Wait-gate production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imports = import_roots(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imports, "yfinance import exists")
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r8a_wait_until_first_maturity_date.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "Wrapper parse did not return PARSE_OK")

    for path in [R8_R1_DECISION, R8_R1_LEDGER, R8_R1_AUDIT]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required input missing: {path}")
    r8_r1 = rows(R8_R1_DECISION)[0]
    assert_true(r8_r1["final_status"] == "PASS_V21_044_R8_R1_ENTRY_PRICE_BINDING_REPAIRED_PENDING_MATURITY", "R8-R1 status not ready")
    assert_true(r8_r1["decision"] == "ENTRY_PRICE_REPAIRED_WAIT_FOR_MATURITY_DATES", "R8-R1 decision not ready")
    ledger_before = R8_R1_LEDGER.read_bytes()
    protected_before = protected_snapshot()

    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r8a_wait_until_first_maturity_date.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_first_maturity_date=2026-06-24" in wrapper.stdout, "Wrapper first maturity date missing")

    assert_true(R8_R1_LEDGER.read_bytes() == ledger_before, "Repaired ledger was modified")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")
    for path in [WAIT_SUMMARY, GATE_STATUS, SCOPE_AUDIT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")

    summary = rows(DECISION)[0]
    assert_true(summary["final_status"] == "PARTIAL_PASS_V21_044_R8A_WAITING_FOR_FIRST_MATURITY_DATE", "Unexpected final status")
    assert_true(summary["decision"] == "WAIT_UNTIL_2026_06_24_BEFORE_R8_RERUN_OR_R9", "Unexpected decision")
    assert_true(summary["first_maturity_date"] == "2026-06-24", "First maturity date mismatch")
    assert_true(summary["matured_rows"] == "0", "Matured rows must be zero")
    assert_true(summary["pending_rows"] == "280", "Pending rows must be 280")
    assert_true(summary["r9_allowed_now"] == "FALSE", "R9 must be disabled")
    assert_true(summary["r8_rerun_allowed_now"] == "FALSE", "R8 rerun must wait for cache coverage")
    assert_true(summary["returns_computed"] == "FALSE", "Returns must not be computed")
    assert_true(summary["observations_appended"] == "FALSE", "Observations must not be appended")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["wait_gate_only"] == "TRUE", "wait_gate_only must be TRUE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    ledger = rows(R8_R1_LEDGER)
    assert_true(all(row["maturity_status"] == "PENDING_NOT_MATURED" for row in ledger), "All rows must remain pending")
    assert_true(all(not row["realized_forward_return"] and not row["benchmark_forward_return"] for row in ledger), "Returns were fabricated")
    report_text = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only observation must not be interpreted as full-weight result" in report_text, "Full-weight boundary missing")
    assert_true("No returns were computed" in report_text, "No-return statement missing")

    print("PASS test_v21_044_r8a_wait_until_first_maturity_date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
