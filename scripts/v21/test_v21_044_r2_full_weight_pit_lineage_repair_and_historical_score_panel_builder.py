from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder.ps1"
OUT = ROOT / "outputs" / "v21" / "review"
DISCOVERY = OUT / "V21_044_R2_PIT_LINEAGE_ARTIFACT_DISCOVERY.csv"
REPAIR = OUT / "V21_044_R2_PIT_LINEAGE_REPAIR_AUDIT.csv"
PANEL = OUT / "V21_044_R2_FULL_WEIGHT_HISTORICAL_SCORE_PANEL.csv"
ELIGIBLE = OUT / "V21_044_R2_FULL_WEIGHT_PANEL_ELIGIBLE_ASOF_MANIFEST.csv"
COVERAGE = OUT / "V21_044_R2_FULL_WEIGHT_PANEL_COVERAGE_AUDIT.csv"
DECISION = OUT / "V21_044_R2_FULL_WEIGHT_PANEL_DECISION_SUMMARY.csv"
REPORTS = [
    ROOT / "outputs" / "v21" / "read_center" / "V21_044_R2_FULL_WEIGHT_PIT_LINEAGE_REPAIR_AND_PANEL_BUILDER_REPORT.md",
    ROOT / "outputs" / "v21" / "read_center" / "CURRENT_V21_044_R2_FULL_WEIGHT_PIT_LINEAGE_REPAIR_AND_PANEL_BUILDER_REPORT.md",
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
    guarded: dict[Path, int] = {}
    roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21",
        ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    guarded[path] = path.stat().st_mtime_ns
    for root in [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name):
                    guarded[path] = path.stat().st_mtime_ns
    return guarded


def main() -> int:
    assert_true(SCRIPT.exists(), "Production script missing")
    assert_true(WRAPPER.exists(), "PowerShell wrapper missing")
    py_compile.compile(str(SCRIPT), doraise=True)

    source = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in source.lower(), "yfinance must not be referenced")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not imported.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Network modules are forbidden")
    assert_true("st_mtime" not in source and "getmtime" not in source, "File modification time must not produce factor dates")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parser did not return PARSE_OK")

    before = guarded_snapshot()
    wrapped = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder.ps1",
    ], "Wrapper")
    assert_true("final_status=" in wrapped.stdout, "Wrapper did not print final_status")
    assert_true(before == guarded_snapshot(), "Guarded or official files changed")

    for path in [DISCOVERY, REPAIR, PANEL, ELIGIBLE, COVERAGE, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing or empty: {path}")

    discovery = rows(DISCOVERY)
    decision_rows = rows(DECISION)
    assert_true(discovery, "Artifact discovery is empty")
    assert_true(decision_rows, "Decision summary is empty")
    decision = decision_rows[0]
    assert_true(
        decision["full_weight_source_path"].replace("\\", "/").endswith(
            "outputs/v20/consolidation/V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
        ),
        "Full weight source was not resolved from V20_107",
    )

    repair = rows(REPAIR)
    unknown = [row for row in repair if row.get("factor_date_status") == "UNKNOWN"]
    assert_true(unknown, "Expected UNKNOWN factor-date diagnosis is missing")
    assert_true(
        all(int(float(row.get("point_in_time_safe_row_count") or "0")) == 0 for row in unknown),
        "UNKNOWN factor_date rows were marked PIT-safe",
    )

    panel_rows = rows(PANEL)
    panel_headers = next(csv.reader(PANEL.open("r", encoding="utf-8-sig", newline="")))
    required_panel = {
        "as_of_date", "ticker", "family", "family_weight",
        "full_weight_score", "point_in_time_safe",
    }
    assert_true(required_panel.issubset(panel_headers), "Historical panel schema is incomplete")
    for row in panel_rows:
        if row.get("complete_family_coverage_per_ticker_date") != "TRUE":
            assert_true(row.get("full_weight_score", "") == "", "Incomplete family rows have fabricated full scores")
        if row.get("factor_date_status") == "UNKNOWN":
            assert_true(row.get("point_in_time_safe") != "TRUE", "UNKNOWN panel factor date marked safe")

    assert_true(ELIGIBLE.exists(), "Eligible as-of manifest missing")
    coverage = rows(COVERAGE)
    assert_true(coverage, "Coverage audit is empty")
    assert_true(
        all(not row.get("missing_expected_families") or row.get("complete_family_coverage_asof") != "TRUE" for row in coverage),
        "Missing family scores were treated as complete",
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
    assert_true(decision.get("file_modified_time_used_for_factor_date") == "FALSE", "mtime date inference occurred")
    assert_true(decision.get("factor_dates_fabricated") == "FALSE", "Factor dates were fabricated")
    assert_true(decision.get("family_scores_fabricated") == "FALSE", "Family scores were fabricated")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21",
        ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R2*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
