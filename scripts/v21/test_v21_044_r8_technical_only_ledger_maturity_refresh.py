from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r8_technical_only_ledger_maturity_refresh.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r8_technical_only_ledger_maturity_refresh.ps1"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R7_LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
MATURED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURED_RESULTS.csv"
PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
MATURITY_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_MATURITY_REFRESH_AUDIT.csv"
BUCKET_SUMMARY = REVIEW / "V21_044_R8_TECHNICAL_ONLY_MATURITY_SUMMARY_BY_BUCKET_WINDOW.csv"
REPAIR_SUMMARY = REVIEW / "V21_044_R8_TECHNICAL_ONLY_PRICE_WARNING_REPAIR_SUMMARY.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8_TECHNICAL_ONLY_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_044_R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R8_TECHNICAL_ONLY_LEDGER_MATURITY_REFRESH_REPORT.md",
]

FALSE_GUARDRAILS = [
    "full_weight_result_available", "full_weight_rebacktest_allowed_now",
    "official_adoption_allowed", "official_weight_mutation", "official_ranking_mutation",
    "official_recommendation_allowed", "real_book_action_allowed", "broker_execution_allowed",
    "trade_action_allowed", "shadow_gate_allowed", "shadow_adoption_allowed",
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


def protected_snapshot() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snapshot[path] = path.stat().st_mtime_ns
    official_roots = [ROOT / "outputs" / "v21" / "factors", ROOT / "outputs" / "v21" / "consolidation"]
    for root in official_roots:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snapshot[path] = path.stat().st_mtime_ns
    return snapshot


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R8 production files missing")
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
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r8_technical_only_ledger_maturity_refresh.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    input_before = rows(R7_LEDGER)
    input_bytes = R7_LEDGER.read_bytes()
    input_ids = [row["observation_id"] for row in input_before]
    protected_before = protected_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r8_technical_only_ledger_maturity_refresh.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(R7_LEDGER.read_bytes() == input_bytes, "R7 source ledger was modified")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    required = [
        REFRESHED, MATURED, PENDING, PRICE_AUDIT, MATURITY_AUDIT, BUCKET_SUMMARY,
        REPAIR_SUMMARY, SCOPE_AUDIT, DECISION, *REPORTS,
    ]
    for path in required:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required R8 output missing: {path}")

    refreshed = rows(REFRESHED)
    assert_true(len(refreshed) == len(input_before), "Refreshed ledger did not preserve input row count")
    assert_true([row["observation_id"] for row in refreshed] == input_ids, "Observation order or IDs changed")
    input_keys = [(row["observation_as_of_date"], row["ticker"], row["bucket"], row["forward_window"]) for row in input_before]
    refreshed_keys = [(row["observation_as_of_date"], row["ticker"], row["bucket"], row["forward_window"]) for row in refreshed]
    assert_true(refreshed_keys == input_keys, "New or changed observation rows detected")
    assert_true(len(refreshed_keys) == len(set(refreshed_keys)), "Duplicate observations found")
    assert_true(len(rows(MATURITY_AUDIT)) == len(refreshed), "Maturity audit does not cover every row")
    assert_true(len(rows(PRICE_AUDIT)) == len(refreshed), "Price-binding audit does not cover every row")

    pending = [row for row in refreshed if row["maturity_status"] != "MATURED"]
    matured = [row for row in refreshed if row["maturity_status"] == "MATURED"]
    assert_true(all(row["realized_forward_return"] == "" and row["benchmark_forward_return"] == "" and row["excess_vs_QQQ"] == "" for row in pending), "Pending/price-missing row has fabricated return")
    price_fields = ["entry_price", "benchmark_entry_price", "ticker_forward_price", "benchmark_forward_price"]
    assert_true(all(row[field] != "0" and row[field] != "0.0" and row[field] != "0.0000000000" for row in refreshed for field in price_fields), "Missing price filled with zero")
    assert_true(all(row["realized_forward_return"] and row["benchmark_forward_return"] and row["excess_vs_QQQ"] for row in matured), "Matured row lacks returns")

    scope = rows(SCOPE_AUDIT)
    assert_true(scope and all(row["check_passed"] == "TRUE" for row in scope), "Scope boundary failed")
    summary = rows(DECISION)[0]
    assert_true(int(summary["input_ledger_row_count"]) == len(input_before), "Decision input count mismatch")
    assert_true(int(summary["refreshed_ledger_row_count"]) == len(refreshed), "Decision refreshed count mismatch")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["maturity_refresh_only"] == "TRUE", "maturity_refresh_only must be TRUE")
    assert_true(summary["observation_only"] == "TRUE", "observation_only must be TRUE")
    assert_true(summary["technical_only_observation"] == "TRUE", "technical_only_observation must be TRUE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")
    for row in refreshed:
        assert_true(row["research_only"] == "TRUE" and row["maturity_refresh_only"] == "TRUE" and row["observation_only"] == "TRUE", "Positive row guardrail missing")
        for field in FALSE_GUARDRAILS:
            assert_true(row[field] == "FALSE", f"Row {field} must be FALSE")

    for output in [REFRESHED, MATURED, PENDING, PRICE_AUDIT, MATURITY_AUDIT, BUCKET_SUMMARY, REPAIR_SUMMARY, SCOPE_AUDIT, DECISION]:
        output_text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", output_text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
    for report in REPORTS:
        report_text = report.read_text(encoding="utf-8")
        assert_true("No buy/sell/hold recommendation was created" in report_text, "Required no-recommendation statement missing")
        assert_true("Technical-only observation must not be interpreted as full-weight result" in report_text, "Full-weight interpretation boundary missing")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R8*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r8_technical_only_ledger_maturity_refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
