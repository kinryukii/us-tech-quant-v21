from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r1_full_weight_source_resolution_and_rebacktest.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r1_full_weight_source_resolution_and_rebacktest.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
FILES = {
    "candidates": OUT / "V21_044_R1_FULL_WEIGHT_SOURCE_CANDIDATE_AUDIT.csv",
    "selected": OUT / "V21_044_R1_SELECTED_FULL_WEIGHT_SOURCE_AUDIT.csv",
    "coverage": OUT / "V21_044_R1_FULL_WEIGHT_FAMILY_COVERAGE_AUDIT.csv",
    "panel": OUT / "V21_044_R1_FULL_WEIGHT_REBACKTEST_PANEL.csv",
    "summary": OUT / "V21_044_R1_FULL_WEIGHT_VARIANT_WINDOW_SUMMARY.csv",
    "benchmark": OUT / "V21_044_R1_FULL_WEIGHT_BENCHMARK_COMPARISON.csv",
    "leakage": OUT / "V21_044_R1_FULL_WEIGHT_LEAKAGE_AUDIT.csv",
    "decision": OUT / "V21_044_R1_FULL_WEIGHT_DECISION_SUMMARY.csv",
}
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R1_FULL_WEIGHT_SOURCE_RESOLUTION_AND_REBACKTEST_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R1_FULL_WEIGHT_SOURCE_RESOLUTION_AND_REBACKTEST_REPORT.md",
]
EXPECTED_FAMILIES = {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=240)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def guarded_snapshot() -> dict[Path, int]:
    roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    snap: dict[Path, int] = {}
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
    lowered = text.lower()
    assert_true("yfinance" not in lowered, "yfinance must not be referenced")
    tree = ast.parse(text)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not (imported & {"requests", "urllib", "httpx", "aiohttp"}), "Network/download modules are forbidden")

    parse = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r1_full_weight_source_resolution_and_rebacktest.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parse.stdout, "PowerShell parse did not return PARSE_OK")

    before = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r1_full_weight_source_resolution_and_rebacktest.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapper.stdout, "Wrapper did not print final_status")

    after = guarded_snapshot()
    assert_true(before == after, "A guarded or official file was created, removed, or modified")

    for path in [*FILES.values(), *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing or empty: {path}")

    candidate_rows = rows(FILES["candidates"])
    decision_rows = rows(FILES["decision"])
    assert_true(candidate_rows, "Source candidate audit is empty")
    assert_true(decision_rows, "Decision summary is empty")
    decision = decision_rows[0]

    selected = rows(FILES["selected"])[0]
    if selected.get("selection_status") == "SELECTED":
        assert_true(
            selected.get("selected_source_classification") != "TECHNICAL_SUBFACTOR_ONLY_SOURCE",
            "Technical subfactor source cannot be selected as full source",
        )

    coverage = rows(FILES["coverage"])
    assert_true({row["expected_family"] for row in coverage} == EXPECTED_FAMILIES, "Expected family coverage is incomplete")
    assert_true(all(row["weight_fabricated"] == "FALSE" for row in coverage), "Missing family weights were fabricated")
    for row in coverage:
        if row["family_present"] != "TRUE":
            assert_true(row["resolved_weight"] == "", "Missing family has a fabricated numeric weight")

    benchmark = rows(FILES["benchmark"])[0]
    qqq_exists = (ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv").exists()
    if qqq_exists:
        assert_true(benchmark["benchmark_symbol"] == "QQQ", "Local QQQ source was not recorded")
        assert_true(bool(benchmark["benchmark_source_path"]), "QQQ source path is missing")

    leakage = rows(FILES["leakage"])
    assert_true(leakage, "Leakage audit is empty")
    unsafe = [row for row in leakage if row["point_in_time_safe"] != "TRUE"]
    assert_true(
        all(row["included_in_performance_aggregation"] == "FALSE" for row in unsafe),
        "Unsafe rows were included in performance aggregation",
    )
    panel = rows(FILES["panel"])
    assert_true(
        not any(row["point_in_time_safe"] != "TRUE" and row.get("realized_forward_return") for row in panel),
        "Unsafe panel rows contain aggregated performance",
    )

    expected_guards = {
        "research_only": "TRUE",
        "official_adoption_allowed": "FALSE",
        "official_weight_mutation": "FALSE",
        "official_ranking_mutation": "FALSE",
        "real_book_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "shadow_gate_allowed": "FALSE",
        "shadow_adoption_allowed": "FALSE",
    }
    for key, expected in expected_guards.items():
        assert_true(decision.get(key) == expected, f"{key} must be {expected}")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R1*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r1_full_weight_source_resolution_and_rebacktest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
