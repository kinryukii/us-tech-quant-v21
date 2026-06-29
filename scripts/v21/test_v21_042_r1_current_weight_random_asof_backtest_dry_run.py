from __future__ import annotations

import csv
import os
import py_compile
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_042_r1_current_weight_random_asof_backtest_dry_run.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_042_r1_current_weight_random_asof_backtest_dry_run.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "backtest"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

SUMMARY = OUT_DIR / "V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv"
MANIFEST = OUT_DIR / "V21_042_R1_RANDOM_ASOF_SAMPLE_MANIFEST.csv"
SOURCE_AUDIT = OUT_DIR / "V21_042_R1_CURRENT_WEIGHT_SOURCE_AUDIT.csv"
PANEL = OUT_DIR / "V21_042_R1_RANDOM_ASOF_BACKTEST_PANEL.csv"
PER_DATE = OUT_DIR / "V21_042_R1_RANDOM_ASOF_PER_DATE_METRICS.csv"
WINDOW_SUMMARY = OUT_DIR / "V21_042_R1_RANDOM_ASOF_VARIANT_WINDOW_SUMMARY.csv"
LEAKAGE = OUT_DIR / "V21_042_R1_RANDOM_ASOF_LEAKAGE_AUDIT.csv"
REPORT = READ_CENTER / "V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_042_R1_CURRENT_WEIGHT_RANDOM_ASOF_BACKTEST_REPORT.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_cmd(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{label} failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def snapshot_guarded_files() -> dict[Path, float]:
    guarded_roots = [
        ROOT / "outputs" / "v22",
        ROOT / "outputs" / "v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "trade_action",
        ROOT / "outputs" / "v21" / "broker",
        ROOT / "outputs" / "v21" / "execution",
        ROOT / "outputs" / "v21" / "trade-action",
        ROOT / "outputs" / "v21" / "trade_action",
    ]
    guarded_files: dict[Path, float] = {}
    for root in guarded_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                guarded_files[path] = path.stat().st_mtime
    for root in [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]:
        if not root.exists():
            continue
        for path in root.rglob("*official*"):
            if path.is_file() and ("ranking" in path.name.lower() or "recommendation" in path.name.lower()):
                guarded_files[path] = path.stat().st_mtime
    return guarded_files


def assert_guarded_unchanged(before: dict[Path, float]) -> None:
    for path, mtime in before.items():
        assert_true(path.exists(), f"Guarded file was removed: {path}")
        assert_true(path.stat().st_mtime == mtime, f"Guarded file was modified: {path}")
    forbidden_roots = [
        ROOT / "outputs" / "v22",
        ROOT / "outputs" / "v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if not root.exists():
            continue
        created = [p for p in root.rglob("*V21_042_R1*") if p.is_file()]
        assert_true(not created, f"Unexpected V21_042_R1 files in guarded root: {created}")


def main() -> int:
    assert_true(SCRIPT.exists(), "Production script missing")
    assert_true(WRAPPER.exists(), "PowerShell wrapper missing")
    py_compile.compile(str(SCRIPT), doraise=True)

    script_text = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in script_text.lower(), "Production script must not import or reference yfinance")

    parse = run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_042_r1_current_weight_random_asof_backtest_dry_run.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        "PowerShell parse",
    )
    assert_true("PARSE_OK" in parse.stdout, "PowerShell parser did not return PARSE_OK")

    before = snapshot_guarded_files()
    run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/v21/run_v21_042_r1_current_weight_random_asof_backtest_dry_run.ps1",
        ],
        "PowerShell wrapper execution",
    )
    assert_guarded_unchanged(before)

    for required in [
        SUMMARY,
        MANIFEST,
        SOURCE_AUDIT,
        PANEL,
        PER_DATE,
        WINDOW_SUMMARY,
        LEAKAGE,
        REPORT,
        CURRENT_REPORT,
    ]:
        assert_true(required.exists(), f"Required output missing: {required}")
        assert_true(required.stat().st_size > 0, f"Required output empty: {required}")

    summary_rows = read_csv(SUMMARY)
    assert_true(summary_rows, "Decision summary is empty")
    summary = summary_rows[0]
    assert_true(
        summary["final_status"].startswith(
            (
                "PASS_V21_042_R1",
                "PARTIAL_PASS_V21_042_R1",
                "BLOCKED_V21_042_R1",
            )
        ),
        f"Unexpected final_status: {summary['final_status']}",
    )
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["official_adoption_allowed"] == "FALSE", "official_adoption_allowed must be FALSE")
    assert_true(summary["official_weight_mutation"] == "FALSE", "official_weight_mutation must be FALSE")
    assert_true(summary["official_ranking_mutation"] == "FALSE", "official_ranking_mutation must be FALSE")
    assert_true(summary["real_book_action_allowed"] == "FALSE", "real_book_action_allowed must be FALSE")
    assert_true(summary["broker_execution_allowed"] == "FALSE", "broker_execution_allowed must be FALSE")
    assert_true(summary["data_trust_alpha_weight_allowed"] == "FALSE", "data_trust_alpha_weight_allowed must be FALSE")

    source_rows = read_csv(SOURCE_AUDIT)
    assert_true(source_rows, "Weight source audit is empty")
    source_statuses = {row.get("source_status", "") for row in source_rows}
    if summary["final_status"] == "BLOCKED_V21_042_R1_CURRENT_WEIGHT_SOURCE_NOT_FOUND":
        assert_true("BLOCKED_CURRENT_WEIGHT_SOURCE_NOT_FOUND" in source_statuses, "Blocked status missing from source audit")
    else:
        usable = [row for row in source_rows if row.get("source_status") == "USED_CURRENT_WEIGHT_SOURCE"]
        assert_true(usable, "Weight source audit must identify a used source path")
        assert_true(bool(usable[0].get("source_file_path")), "Used source path must be recorded")

    manifest_once = MANIFEST.read_text(encoding="utf-8")
    run_cmd([sys.executable, str(SCRIPT)], "Direct production rerun")
    manifest_twice = MANIFEST.read_text(encoding="utf-8")
    assert_true(manifest_once == manifest_twice, "Sample manifest is not reproducible with fixed seed")
    assert_guarded_unchanged(before)

    leakage_rows = read_csv(LEAKAGE)
    required_leakage_cols = {
        "as_of_date",
        "feature_max_date",
        "price_entry_date",
        "forward_return_window",
        "forward_price_date",
        "point_in_time_safe",
        "leakage_violation_reason",
    }
    assert_true(leakage_rows, "Leakage audit is empty")
    assert_true(required_leakage_cols.issubset(leakage_rows[0].keys()), "Leakage audit missing point-in-time columns")

    unsafe_rows = [row for row in leakage_rows if row.get("point_in_time_safe") != "TRUE"]
    if unsafe_rows:
        summary_rows_by_variant = read_csv(WINDOW_SUMMARY)
        for row in summary_rows_by_variant:
            assert_true(
                int(float(row.get("leakage_violation_count", "0") or "0")) >= 0,
                "Window summary leakage count must be numeric",
            )

    report_text = REPORT.read_text(encoding="utf-8")
    assert_true(summary["decision"] in report_text, "Markdown report must contain decision string")
    assert_true("official_adoption_allowed = FALSE" in report_text, "Report must document official mutation block")

    print("PASS test_v21_042_r1_current_weight_random_asof_backtest_dry_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

