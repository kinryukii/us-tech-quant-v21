from __future__ import annotations

import ast
import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_042_r2_current_weight_random_asof_benchmark_comparator.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_042_r2_current_weight_random_asof_benchmark_comparator.ps1"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

SOURCE_AUDIT = BACKTEST / "V21_042_R2_BENCHMARK_SOURCE_AUDIT.csv"
PANEL = BACKTEST / "V21_042_R2_RANDOM_ASOF_BENCHMARK_PANEL.csv"
SUMMARY = BACKTEST / "V21_042_R2_VARIANT_WINDOW_BENCHMARK_SUMMARY.csv"
PER_DATE = BACKTEST / "V21_042_R2_PER_DATE_BENCHMARK_COMPARISON.csv"
DECISION = BACKTEST / "V21_042_R2_BENCHMARK_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V21_042_R2_CURRENT_WEIGHT_RANDOM_ASOF_BENCHMARK_COMPARATOR_REPORT.md"
CURRENT_REPORT = READ_CENTER / "CURRENT_V21_042_R2_CURRENT_WEIGHT_RANDOM_ASOF_BENCHMARK_COMPARATOR_REPORT.md"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def guarded_snapshot() -> dict[Path, int]:
    roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21",
        ROOT / "broker", ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
        ROOT / "outputs" / "v21" / "broker", ROOT / "outputs" / "v21" / "execution",
        ROOT / "outputs" / "v21" / "trade-action", ROOT / "outputs" / "v21" / "trade_action",
    ]
    result: dict[Path, int] = {}
    for root in roots:
        if root.exists():
            result.update({path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()})
    for root in [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name):
                    result[path] = path.stat().st_mtime_ns
    return result


def main() -> int:
    check(SCRIPT.exists(), "Production script missing")
    check(WRAPPER.exists(), "PowerShell wrapper missing")
    py_compile.compile(str(SCRIPT), doraise=True)

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = {
        alias.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    check("yfinance" not in imports, "yfinance import is forbidden")
    forbidden_network = {"requests", "urllib", "httpx", "aiohttp", "socket"}
    check(not imports.intersection(forbidden_network), f"Online network import found: {imports & forbidden_network}")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
        "'scripts/v21/run_v21_042_r2_current_weight_random_asof_benchmark_comparator.ps1'), "
        "[ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    check("PARSE_OK" in parsed.stdout, "Wrapper parse did not return PARSE_OK")

    before = guarded_snapshot()
    run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_042_r2_current_weight_random_asof_benchmark_comparator.ps1",
    ], "Wrapper execution")
    after = guarded_snapshot()
    check(before == after, "A guarded output, broker, execution, trade, official ranking, or recommendation path changed")

    check(SOURCE_AUDIT.exists() and SOURCE_AUDIT.stat().st_size > 0, "Benchmark source audit missing")
    check(DECISION.exists() and DECISION.stat().st_size > 0, "Decision summary missing")
    decision = rows(DECISION)[0]
    status = decision["final_status"]
    check(status in {
        "PASS_V21_042_R2_CURRENT_WEIGHT_BENCHMARK_COMPARISON_READY",
        "PARTIAL_PASS_V21_042_R2_BENCHMARK_COMPARISON_LIMITED_COVERAGE",
        "BLOCKED_V21_042_R2_BENCHMARK_SOURCE_NOT_FOUND",
        "BLOCKED_V21_042_R2_UPSTREAM_BACKTEST_NOT_READY",
    }, f"Unexpected status: {status}")

    audit = rows(SOURCE_AUDIT)
    check(audit, "Benchmark source audit is empty")
    if not status.startswith("BLOCKED_"):
        used = [row for row in audit if row.get("source_status") == "USED_LOCAL_BENCHMARK_SOURCE"]
        check(used, "Used benchmark source was not recorded")
        check(bool(used[0].get("benchmark_symbol")), "Benchmark symbol missing")
        check(bool(used[0].get("source_path")), "Benchmark source path missing")
        for required in [PANEL, SUMMARY, PER_DATE, REPORT, CURRENT_REPORT]:
            check(required.exists() and required.stat().st_size > 0, f"Required output missing or empty: {required}")
        panel = rows(PANEL)
        check(panel, "Benchmark panel is empty")
        missing = [row for row in panel if row.get("benchmark_alignment_status") != "AVAILABLE"]
        for row in missing:
            check(row.get("benchmark_forward_return", "") == "", "Missing benchmark return was filled")
        check(not any(
            row.get("benchmark_alignment_status") != "AVAILABLE"
            and row.get("benchmark_forward_return") in {"0", "0.0", "0.0000000000"}
            for row in panel
        ), "Missing benchmark return was filled with zero")

    check(decision["research_only"] == "TRUE", "research_only must be TRUE")
    for field in [
        "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
        "real_book_action_allowed", "broker_execution_allowed", "trade_action_allowed",
        "shadow_gate_allowed", "shadow_adoption_allowed",
    ]:
        check(decision[field] == "FALSE", f"{field} must remain FALSE")

    print("PASS test_v21_042_r2_current_weight_random_asof_benchmark_comparator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
