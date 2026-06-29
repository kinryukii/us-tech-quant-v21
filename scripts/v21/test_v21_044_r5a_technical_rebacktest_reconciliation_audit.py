from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r5a_technical_rebacktest_reconciliation_audit.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r5a_technical_rebacktest_reconciliation_audit.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
FILES = [
    OUT / "V21_044_R5A_SAMPLE_DATE_RECONCILIATION.csv",
    OUT / "V21_044_R5A_ROW_COVERAGE_RECONCILIATION.csv",
    OUT / "V21_044_R5A_TOP20_COMPOSITION_RECONCILIATION.csv",
    OUT / "V21_044_R5A_SCORE_RANK_RECONCILIATION.csv",
    OUT / "V21_044_R5A_FORWARD_RETURN_ALIGNMENT_RECONCILIATION.csv",
    OUT / "V21_044_R5A_QQQ_BENCHMARK_ALIGNMENT_RECONCILIATION.csv",
    OUT / "V21_044_R5A_DEVIATION_CONTRIBUTION_DECOMPOSITION.csv",
    OUT / "V21_044_R5A_PRIOR_60D_CONCENTRATION_CHECK.csv",
]
DECISION = OUT / "V21_044_R5A_RECONCILIATION_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R5A_TECHNICAL_REBACKTEST_RECONCILIATION_AUDIT_REPORT.md",
]


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=360)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def guarded_snapshot() -> dict[Path, int]:
    snap: dict[Path, int] = {}
    roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snap[path] = path.stat().st_mtime_ns
    for root in [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name):
                    snap[path] = path.stat().st_mtime_ns
    return snap


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "Production files missing")
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
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Network module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r5a_technical_rebacktest_reconciliation_audit.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "Wrapper parse failed")
    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r5a_technical_rebacktest_reconciliation_audit.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper output missing")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [*FILES, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    decision_rows = rows(DECISION)
    assert_true(decision_rows, "Decision summary empty")
    decision = decision_rows[0]
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("materially" in report.lower() or "deviation" in report.lower(), "R5 material deviation not acknowledged")
    assert_true("positive versus QQQ" in report or "positive vs QQQ" in report, "Positive QQQ edge not acknowledged")
    assert_true("not promoted" in report, "Positive edge promotion boundary missing")

    expected = {
        "full_weight_rebacktest_allowed_now": "FALSE", "reconciliation_only": "TRUE",
        "research_only": "TRUE", "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE", "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE", "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE", "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }
    for key, value in expected.items():
        assert_true(decision.get(key) == value, f"{key} must be {value}")

    forbidden = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R5A*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")
    print("PASS test_v21_044_r5a_technical_rebacktest_reconciliation_audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
