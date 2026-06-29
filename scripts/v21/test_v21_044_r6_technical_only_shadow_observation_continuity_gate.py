from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r6_technical_only_shadow_observation_continuity_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r6_technical_only_shadow_observation_continuity_gate.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
UPSTREAM = OUT / "V21_044_R6_UPSTREAM_READINESS_AUDIT.csv"
CANONICAL = OUT / "V21_044_R6_CANONICAL_TECHNICAL_RESULT_AUDIT.csv"
RECON = OUT / "V21_044_R6_RECONCILIATION_ACCEPTANCE_AUDIT.csv"
ELIGIBILITY = OUT / "V21_044_R6_TECHNICAL_ONLY_OBSERVATION_ELIGIBILITY_AUDIT.csv"
BOUNDARY = OUT / "V21_044_R6_SCOPE_BOUNDARY_AUDIT.csv"
CONTRACT = OUT / "V21_044_R6_NEXT_OBSERVATION_CONTRACT.csv"
DECISION = OUT / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R6_TECHNICAL_ONLY_SHADOW_OBSERVATION_CONTINUITY_GATE_REPORT.md",
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
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r6_technical_only_shadow_observation_continuity_gate.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "Wrapper parse failed")
    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r6_technical_only_shadow_observation_continuity_gate.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [UPSTREAM, CANONICAL, RECON, ELIGIBILITY, BOUNDARY, CONTRACT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    decision = rows(DECISION)[0]
    upstream = rows(UPSTREAM)
    assert_true(any(row["audit_check"] == "r5_completed_status" and row["check_passed"] == "TRUE" for row in upstream), "R5 readiness not confirmed")
    assert_true(any(row["audit_check"] == "r5a_ready" and row["check_passed"] == "TRUE" for row in upstream), "R5A readiness not confirmed")
    canonical = rows(CANONICAL)
    windows = {row["metric_scope"] for row in canonical}
    assert_true({"5D", "10D", "20D", "60D"}.issubset(windows), "Canonical windows incomplete")
    assert_true(rows(RECON), "Reconciliation acceptance missing")
    boundary = {row["scope_boundary"]: row["allowed_value"] for row in rows(BOUNDARY)}
    assert_true(boundary.get("full_weight_result_available") == "FALSE", "Full-weight result incorrectly available")
    assert_true(boundary.get("full_weight_rebacktest_allowed_now") == "FALSE", "Full-weight backtest incorrectly allowed")

    eligibility = rows(ELIGIBILITY)
    eligibility_passes = bool(eligibility) and all(row["check_passed"] == "TRUE" for row in eligibility)
    if decision["technical_only_shadow_observation_continuity_allowed"] == "TRUE":
        assert_true(eligibility_passes, "Continuity allowed without passing eligibility")
        assert_true(decision["technical_only_result_canonical"] == "TRUE", "Accepted result not canonical")

    expected = {
        "full_weight_rebacktest_allowed_now": "FALSE", "full_weight_result_available": "FALSE",
        "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE", "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "shadow_adoption_allowed": "FALSE",
    }
    for key, value in expected.items():
        assert_true(decision.get(key) == value, f"{key} must be {value}")

    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("must not be interpreted as a full-weight result" in report, "Technical/full-weight boundary missing")
    assert_true("old V21.042-R2 20D and 60D magnitude is superseded" in report, "Superseded prior magnitude missing")

    forbidden = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R6*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")
    print("PASS test_v21_044_r6_technical_only_shadow_observation_continuity_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
