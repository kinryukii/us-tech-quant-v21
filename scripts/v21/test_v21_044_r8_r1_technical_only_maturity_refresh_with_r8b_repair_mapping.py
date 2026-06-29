from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r8_r1_technical_only_maturity_refresh_with_r8b_repair_mapping.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r8_r1_technical_only_maturity_refresh_with_r8b_repair_mapping.ps1"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R8_REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
R8_PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
R8B_MAPPING = REVIEW / "V21_044_R8B_PRICE_SOURCE_REPAIR_MAPPING.csv"
R8B_DECISION = REVIEW / "V21_044_R8B_DECISION_SUMMARY.csv"
R8B_COVERAGE = REVIEW / "V21_044_R8B_REQUIRED_PRICE_COVERAGE_AUDIT.csv"
REPAIR_SOURCE = ROOT / "outputs" / "v20" / "consolidation" / "V20_47_CURRENT_CANDIDATE_PRICE_CERTIFICATION.csv"
CANONICAL_TICKER = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
CANONICAL_BENCHMARK = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

OUT_REFRESHED = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED_WITH_REPAIR.csv"
OUT_PENDING = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_PENDING_ROWS.csv"
OUT_PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
OUT_MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
REPAIR_SUMMARY = REVIEW / "V21_044_R8_R1_PRICE_REPAIR_APPLICATION_SUMMARY.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8_R1_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R8_R1_TECHNICAL_ONLY_MATURITY_REFRESH_WITH_R8B_REPAIR_MAPPING_REPORT.md",
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
    "online_download_attempted",
    "yfinance_used",
]


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=600)
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
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R8-R1 production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    script_text = SCRIPT.read_text(encoding="utf-8")
    imports = import_roots(script_text)
    assert_true("yfinance" not in imports, "yfinance import exists")
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r8_r1_technical_only_maturity_refresh_with_r8b_repair_mapping.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    for path in [R8_REFRESHED, R8_PENDING, R8B_MAPPING, R8B_DECISION, R8B_COVERAGE, REPAIR_SOURCE, CANONICAL_TICKER, CANONICAL_BENCHMARK]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required input missing: {path}")
    r8b = rows(R8B_DECISION)[0]
    assert_true(r8b["final_status"] == "PASS_V21_044_R8B_LOCAL_PRICE_SOURCE_REPAIR_READY", "R8B pass status not read")
    assert_true(r8b["decision"] == "R8_RERUN_ALLOWED_WITH_LOCAL_PRICE_SOURCE_REPAIR", "R8B rerun decision not read")
    assert_true(rows(R8B_MAPPING), "R8B repair mapping empty")

    input_rows = rows(R8_REFRESHED)
    input_ids = [row["observation_id"] for row in input_rows]
    canonical_ticker_before = CANONICAL_TICKER.stat().st_mtime_ns
    canonical_benchmark_before = CANONICAL_BENCHMARK.stat().st_mtime_ns
    protected_before = protected_snapshot()

    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r8_r1_technical_only_maturity_refresh_with_r8b_repair_mapping.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_entry_price_repaired_row_count=" in wrapper.stdout, "Wrapper repair count missing")

    assert_true(CANONICAL_TICKER.stat().st_mtime_ns == canonical_ticker_before, "Canonical ticker file was overwritten")
    assert_true(CANONICAL_BENCHMARK.stat().st_mtime_ns == canonical_benchmark_before, "Canonical benchmark file was overwritten")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    for path in [OUT_REFRESHED, OUT_PENDING, OUT_PRICE_AUDIT, OUT_MATURITY_AUDIT, REPAIR_SUMMARY, SCOPE_AUDIT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")

    output_rows = rows(OUT_REFRESHED)
    pending_rows = rows(OUT_PENDING)
    summary = rows(DECISION)[0]
    assert_true(len(output_rows) == len(input_rows), "Refreshed output does not preserve input row count")
    assert_true([row["observation_id"] for row in output_rows] == input_ids, "New observation rows were appended or reordered")
    assert_true(int(summary["input_ledger_rows"]) == len(input_rows), "Input row metric mismatch")
    assert_true(int(summary["refreshed_ledger_rows"]) == len(input_rows), "Refreshed row metric mismatch")
    assert_true(int(summary["entry_price_repaired_row_count"]) > 0, "Entry price repair was not attempted/applied")
    assert_true(int(summary["benchmark_entry_price_repaired_row_count"]) > 0, "Benchmark entry repair was not attempted/applied")
    assert_true(all(row["entry_price"] and float(row["entry_price"]) > 0 for row in output_rows), "Missing or zero-filled ticker entry price found")
    assert_true(all(row["benchmark_entry_price"] and float(row["benchmark_entry_price"]) > 0 for row in output_rows), "Missing or zero-filled benchmark entry price found")
    assert_true(all(row["maturity_status"] == "PENDING_NOT_MATURED" for row in output_rows), "Rows matured despite uncovered maturity dates")
    assert_true(len(pending_rows) == len(output_rows), "Pending rows do not match refreshed output")
    assert_true(all(not row["realized_forward_return"] and not row["benchmark_forward_return"] and not row["excess_vs_QQQ"] for row in output_rows), "Realized returns were fabricated")
    assert_true(summary["rows_with_fabricated_returns"] == "0", "Fabricated return metric must be zero")
    assert_true(summary["full_weight_result_available"] == "FALSE", "full_weight_result_available must be FALSE")
    assert_true(summary["full_weight_rebacktest_allowed_now"] == "FALSE", "full_weight_rebacktest_allowed_now must be FALSE")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["maturity_refresh_only"] == "TRUE", "maturity_refresh_only must be TRUE")
    assert_true(summary["price_source_repair_mapping_used"] == "TRUE", "Repair mapping guardrail must be TRUE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    csv_outputs = [OUT_REFRESHED, OUT_PENDING, OUT_PRICE_AUDIT, OUT_MATURITY_AUDIT, REPAIR_SUMMARY, SCOPE_AUDIT, DECISION]
    for output in csv_outputs:
        text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
    for report in REPORTS:
        text = report.read_text(encoding="utf-8")
        assert_true("No buy/sell/hold recommendation was created" in text, "Required no-recommendation statement missing")
        assert_true("Technical-only observation must not be interpreted as full-weight result" in text, "Full-weight interpretation boundary missing")

    forbidden_roots = [
        ROOT / "outputs" / "v22",
        ROOT / "outputs" / "v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R8_R1*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r8_r1_technical_only_maturity_refresh_with_r8b_repair_mapping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
