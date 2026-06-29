from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r5_technical_only_rebacktest_from_materialized_panel.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r5_technical_only_rebacktest_from_materialized_panel.ps1"
OUT = ROOT / "outputs" / "v21" / "backtest"
PANEL = OUT / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
SUMMARY = OUT / "V21_044_R5_TECHNICAL_ONLY_VARIANT_WINDOW_SUMMARY.csv"
QQQ = OUT / "V21_044_R5_TECHNICAL_ONLY_QQQ_BENCHMARK_COMPARISON.csv"
REPRO = OUT / "V21_044_R5_TECHNICAL_ONLY_REPRODUCTION_COMPARISON.csv"
LEAKAGE = OUT / "V21_044_R5_TECHNICAL_ONLY_LEAKAGE_AUDIT.csv"
DECISION = OUT / "V21_044_R5_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R5_TECHNICAL_ONLY_REBACKTEST_FROM_MATERIALIZED_PANEL_REPORT.md",
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

    parse = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r5_technical_only_rebacktest_from_materialized_panel.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parse.stdout, "Wrapper parse failed")
    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r5_technical_only_rebacktest_from_materialized_panel.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [PANEL, SUMMARY, QQQ, REPRO, LEAKAGE, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")
    decision = rows(DECISION)[0]
    r4 = rows(ROOT / "outputs" / "v21" / "review" / "V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv")[0]
    panel = pd.read_csv(PANEL, low_memory=False)
    if r4["technical_only_backtest_allowed_next"] == "TRUE":
        assert_true(not panel.empty, "R5 panel missing despite ready R4 panel")
    assert_true(set(panel["family"].astype(str)) == {"TECHNICAL"}, "Non-Technical score input found")
    assert_true("full_weight_score" not in panel.columns, "full_weight_score was created")
    forbidden_score_tokens = {"fundamental", "strategy", "risk", "market_regime", "data_trust"}
    assert_true(not any(any(token in column.lower() for token in forbidden_score_tokens) for column in panel.columns), "Blocked family fields used")

    manifest = rows(ROOT / "outputs" / "v21" / "backtest" / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv")
    if manifest:
        assert_true(decision["sample_source"] == "REUSED_V21_042_R1_SAMPLE_MANIFEST", "Prior manifest was not reused")
    qqq = rows(QQQ)[0]
    assert_true(qqq["benchmark_symbol"] == "QQQ" and bool(qqq["benchmark_source_path"]), "QQQ source missing")
    available = panel["price_alignment_status"] == "AVAILABLE"
    assert_true(panel.loc[~available, "realized_forward_return"].isna().all(), "Missing ticker returns filled")
    benchmark_available = panel["benchmark_alignment_status"] == "AVAILABLE"
    assert_true(panel.loc[~benchmark_available, "benchmark_forward_return"].isna().all(), "Missing benchmark returns filled")

    leakage = pd.read_csv(LEAKAGE, low_memory=False)
    unsafe = leakage["point_in_time_safe"].astype(str).str.upper() != "TRUE"
    assert_true(
        leakage.loc[unsafe, "included_in_performance_aggregation"].astype(str).str.upper().ne("TRUE").all(),
        "Unsafe rows included in aggregation",
    )
    repro = rows(REPRO)
    assert_true({row["forward_return_window"] for row in repro} == {"5D", "10D", "20D", "60D"}, "Reproduction comparison incomplete")

    expected = {
        "full_weight_rebacktest_allowed_now": "FALSE", "research_only": "TRUE",
        "official_adoption_allowed": "FALSE", "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE", "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE", "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE", "shadow_adoption_allowed": "FALSE",
    }
    for key, value in expected.items():
        assert_true(decision.get(key) == value, f"{key} must be {value}")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R5*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")
    print("PASS test_v21_044_r5_technical_only_rebacktest_from_materialized_panel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
