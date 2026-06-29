from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r3_full_family_historical_score_materialization_plan_and_contract.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r3_full_family_historical_score_materialization_plan_and_contract.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
DISCOVERY = OUT / "V21_044_R3_FULL_FAMILY_SOURCE_DISCOVERY.csv"
CONTRACT = OUT / "V21_044_R3_FAMILY_MATERIALIZATION_CONTRACT.csv"
MISSING = OUT / "V21_044_R3_MISSING_INPUT_REQUIREMENTS.csv"
RISKS = OUT / "V21_044_R3_LINEAGE_RISK_REGISTER.csv"
PLAN = OUT / "V21_044_R3_NEXT_STAGE_IMPLEMENTATION_PLAN.csv"
DECISION = OUT / "V21_044_R3_MATERIALIZATION_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R3_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION_PLAN_AND_CONTRACT_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R3_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZATION_PLAN_AND_CONTRACT_REPORT.md",
]
FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}


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
    assert_true(SCRIPT.exists(), "Production script missing")
    assert_true(WRAPPER.exists(), "Wrapper missing")
    py_compile.compile(str(SCRIPT), doraise=True)

    source = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in source.lower(), "Forbidden market-data package referenced")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Network modules imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r3_full_family_historical_score_materialization_plan_and_contract.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "Wrapper did not parse")

    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r3_full_family_historical_score_materialization_plan_and_contract.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper did not print summary")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [DISCOVERY, CONTRACT, MISSING, RISKS, PLAN, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")

    discovery = rows(DISCOVERY)
    contracts = rows(CONTRACT)
    decision = rows(DECISION)[0]
    assert_true(discovery, "Source discovery is empty")
    assert_true({row["family_name"] for row in contracts} == FAMILIES, "Contract does not contain all six families")

    by_family = {row["family_name"]: row for row in contracts}
    technical_evidence = ROOT / "outputs" / "v21" / "review" / "V21_044_R2_PIT_LINEAGE_REPAIR_AUDIT.csv"
    if technical_evidence.exists():
        assert_true(by_family["TECHNICAL"]["family_score_materialization_allowed"] == "TRUE", "Technical not recognized as materializable")
    for family in FAMILIES - {"TECHNICAL"}:
        assert_true(by_family[family]["family_score_materialization_allowed"] == "FALSE", f"{family} silently marked materializable")

    assert_true(by_family["DATA_TRUST"]["data_trust_alpha_allowed"] == "FALSE", "Data Trust alpha classification missing")
    assert_true(by_family["DATA_TRUST"]["data_trust_gate_only_allowed"] == "TRUE", "Data Trust gate classification missing")
    assert_true(by_family["RISK"]["risk_score_alpha_allowed"] == "FALSE", "Risk alpha classification missing")
    assert_true(by_family["RISK"]["risk_gate_only_allowed"] == "TRUE", "Risk gate classification missing")
    assert_true("MARKET" in by_family["MARKET_REGIME"]["market_regime_scope_classification"], "Market Regime scope classification missing")

    assert_true(decision["scores_materialized_now"] == "FALSE", "Scores were materialized")
    assert_true(decision["dates_fabricated"] == "FALSE", "Dates were fabricated")
    assert_true(decision["family_labels_fabricated"] == "FALSE", "Family labels were fabricated")
    assert_true(decision["full_weight_backtest_run"] == "FALSE", "Backtest was run")

    expected = {
        "full_weight_rebacktest_allowed_now": "FALSE", "research_only": "TRUE",
        "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE", "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "shadow_adoption_allowed": "FALSE",
    }
    for key, value in expected.items():
        assert_true(decision.get(key) == value, f"{key} must be {value}")

    forbidden = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R3*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r3_full_family_historical_score_materialization_plan_and_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
