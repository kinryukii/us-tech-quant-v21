from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
PANEL = OUT / "V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv"
BLOCKS = OUT / "V21_044_R4_EXPLICIT_FAMILY_SOURCE_BLOCK_REGISTER.csv"
ELIGIBLE = OUT / "V21_044_R4_TECHNICAL_ONLY_ELIGIBLE_ASOF_MANIFEST.csv"
COVERAGE = OUT / "V21_044_R4_MATERIALIZATION_COVERAGE_AUDIT.csv"
BLOCK_AUDIT = OUT / "V21_044_R4_FULL_WEIGHT_REBACKTEST_BLOCK_AUDIT.csv"
DECISION = OUT / "V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R4_FULL_FAMILY_HISTORICAL_SCORE_MATERIALIZER_WITH_EXPLICIT_SOURCE_BLOCKS_REPORT.md",
]
BLOCKED = {"FUNDAMENTAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}


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

    text = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in text.lower(), "Forbidden market-data package referenced")
    tree = ast.parse(text)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Network modules imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "Wrapper parse failed")

    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper did not print final status")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [PANEL, BLOCKS, ELIGIBLE, COVERAGE, BLOCK_AUDIT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")

    decision = rows(DECISION)[0]
    blocks = rows(BLOCKS)
    assert_true({row["family_name"] for row in blocks} == BLOCKED, "Block register does not contain all five families")
    assert_true(all(row["family_score_materialization_allowed"] == "FALSE" for row in blocks), "Blocked family marked materializable")
    assert_true(all(row["neutral_fill_allowed"] == "FALSE" for row in blocks), "Neutral fill was allowed")
    assert_true(all((row.get("materialized_row_count") or "0") == "0" for row in blocks), "Blocked family rows were materialized")

    contract = pd.read_csv(OUT / "V21_044_R3_FAMILY_MATERIALIZATION_CONTRACT.csv")
    technical_ready = (
        (contract["family_name"] == "TECHNICAL")
        & (contract["family_score_materialization_allowed"].astype(str).str.upper() == "TRUE")
    ).any()
    panel = pd.read_csv(PANEL, low_memory=False)
    if technical_ready:
        assert_true(not panel.empty, "Technical panel was not materialized")
    if not panel.empty:
        assert_true(set(panel["family"].astype(str)) == {"TECHNICAL"}, "Non-Technical rows found in panel")
        assert_true((panel["factor_date_status"] != "UNKNOWN").all(), "UNKNOWN factor dates included")
        assert_true(panel["point_in_time_safe"].astype(str).str.upper().eq("TRUE").all(), "Unsafe rows included")
        assert_true(panel["leakage_violation_reason"].fillna("").eq("").all(), "Leakage violations included")
        factor_dates = pd.to_datetime(panel["factor_date"], errors="coerce")
        asof_dates = pd.to_datetime(panel["as_of_date"], errors="coerce")
        assert_true(factor_dates.notna().all() and (factor_dates <= asof_dates).all(), "Invalid factor-date ordering")
        assert_true("full_weight_score" not in panel.columns, "full_weight_score must not be created")
        assert_true(panel["full_weight_score_allowed"].astype(str).str.upper().eq("FALSE").all(), "Full-weight score allowed")

    expected_technical_allowed = "TRUE" if not panel.empty else "FALSE"
    assert_true(decision["technical_only_backtest_allowed_next"] == expected_technical_allowed, "Technical backtest guard is inconsistent")
    expected = {
        "full_weight_rebacktest_allowed_now": "FALSE", "research_only": "TRUE",
        "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE", "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "shadow_adoption_allowed": "FALSE",
        "full_weight_score_created": "FALSE", "neutral_fill_used": "FALSE",
    }
    for key, value in expected.items():
        assert_true(decision.get(key) == value, f"{key} must be {value}")

    forbidden = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R4*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
