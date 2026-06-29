from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r8b_technical_only_price_cache_refresh_or_source_repair.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r8b_technical_only_price_cache_refresh_or_source_repair.ps1"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R8A_DECISION = REVIEW / "V21_044_R8A_DECISION_SUMMARY.csv"
R8A_REQUIREMENT = REVIEW / "V21_044_R8A_PRICE_COVERAGE_REQUIREMENT.csv"
R8A_READINESS = REVIEW / "V21_044_R8A_MATURITY_READINESS_BY_WINDOW.csv"
R8_REFRESHED = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_OBSERVATION_LEDGER_REFRESHED.csv"
R8_PENDING = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PENDING_ROWS.csv"
R8_PRICE_AUDIT = LEDGER_DIR / "V21_044_R8_TECHNICAL_ONLY_PRICE_BINDING_AUDIT.csv"
R7_LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
CANONICAL_TICKER = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
CANONICAL_BENCHMARK = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_BENCHMARK_OHLCV.csv"

DISCOVERY = REVIEW / "V21_044_R8B_PRICE_SOURCE_DISCOVERY.csv"
COVERAGE_AUDIT = REVIEW / "V21_044_R8B_REQUIRED_PRICE_COVERAGE_AUDIT.csv"
REPAIR_MAPPING = REVIEW / "V21_044_R8B_PRICE_SOURCE_REPAIR_MAPPING.csv"
REFRESH_CONTRACT = REVIEW / "V21_044_R8B_PRICE_REFRESH_REQUIREMENT_CONTRACT.csv"
SCOPE_AUDIT = REVIEW / "V21_044_R8B_SCOPE_BOUNDARY_AUDIT.csv"
DECISION = REVIEW / "V21_044_R8B_DECISION_SUMMARY.csv"
REPORTS = [
    READ_CENTER / "V21_044_R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R8B_TECHNICAL_ONLY_PRICE_CACHE_REFRESH_OR_SOURCE_REPAIR_REPORT.md",
]

FALSE_GUARDRAILS = [
    "maturity_refresh_only",
    "realized_return_computation_allowed",
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
    official_roots = [
        ROOT / "outputs" / "v21",
        ROOT / "outputs" / "v20",
    ]
    for root in official_roots:
        if root.exists():
            for path in root.rglob("*"):
                name = path.name.lower()
                if path.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snapshot[path] = path.stat().st_mtime_ns
    return snapshot


def parse_import_roots(text: str) -> set[str]:
    tree = ast.parse(text)
    return {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R8B production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    script_text = SCRIPT.read_text(encoding="utf-8")
    imports = parse_import_roots(script_text)
    assert_true("yfinance" not in imports, "yfinance import exists")
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r8b_technical_only_price_cache_refresh_or_source_repair.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    for path in [
        R8A_DECISION, R8A_REQUIREMENT, R8A_READINESS, R8_REFRESHED, R8_PENDING, R8_PRICE_AUDIT,
        R7_LEDGER, CANONICAL_TICKER, CANONICAL_BENCHMARK,
    ]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required input missing: {path}")

    r8a = rows(R8A_DECISION)[0]
    assert_true(r8a["decision"] == "WAIT_FOR_PRICE_CACHE_REFRESH_BEFORE_R8_RERUN", "R8A decision was not read as expected")
    refreshed_before = R8_REFRESHED.read_bytes()
    pending_before = R8_PENDING.read_bytes()
    canonical_ticker_before = CANONICAL_TICKER.stat().st_mtime_ns
    canonical_benchmark_before = CANONICAL_BENCHMARK.stat().st_mtime_ns
    protected_before = protected_snapshot()

    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r8b_technical_only_price_cache_refresh_or_source_repair.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper final status missing")
    assert_true("wrapper_decision=" in wrapper.stdout, "Wrapper decision missing")
    assert_true("wrapper_local_source_covers_2026_06_16=" in wrapper.stdout, "Wrapper local coverage result missing")
    assert_true("wrapper_r8_rerun_allowed_now=" in wrapper.stdout, "Wrapper R8 rerun field missing")

    assert_true(R8_REFRESHED.read_bytes() == refreshed_before, "R8 refreshed ledger was modified")
    assert_true(R8_PENDING.read_bytes() == pending_before, "R8 pending ledger was modified")
    assert_true(CANONICAL_TICKER.stat().st_mtime_ns == canonical_ticker_before, "Canonical ticker file was overwritten")
    assert_true(CANONICAL_BENCHMARK.stat().st_mtime_ns == canonical_benchmark_before, "Canonical benchmark file was overwritten")
    assert_true(protected_before == protected_snapshot(), "Protected or official file changed")

    for path in [DISCOVERY, COVERAGE_AUDIT, SCOPE_AUDIT, DECISION, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required R8B output missing: {path}")
    assert_true(rows(DISCOVERY), "Price source discovery output empty")
    assert_true(rows(COVERAGE_AUDIT), "Required coverage audit output empty")
    assert_true(rows(DECISION), "Decision summary empty")
    summary = rows(DECISION)[0]

    if summary["selected_repair_source"]:
        assert_true(REPAIR_MAPPING.exists() and REPAIR_MAPPING.stat().st_size > 0, "Repair mapping missing")
        assert_true(all(row["canonical_price_file_overwrite_allowed"] == "FALSE" for row in rows(REPAIR_MAPPING)), "Repair mapping allows canonical overwrite")
    else:
        assert_true(REFRESH_CONTRACT.exists() and REFRESH_CONTRACT.stat().st_size > 0, "Refresh requirement contract missing")

    assert_true(summary["no_returns_computed"] == "TRUE", "Returns computation was not disabled")
    assert_true(summary["no_prices_fabricated"] == "TRUE", "Price fabrication guardrail missing")
    assert_true(summary["online_download_attempted"] == "FALSE", "Online download attempted")
    assert_true(summary["yfinance_used"] == "FALSE", "yfinance used")
    assert_true(summary["full_weight_result_available"] == "FALSE", "full_weight_result_available must be FALSE")
    assert_true(summary["full_weight_rebacktest_allowed_now"] == "FALSE", "full_weight_rebacktest_allowed_now must be FALSE")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["price_source_repair_only"] == "TRUE", "price_source_repair_only must be TRUE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"{field} must be FALSE")

    refreshed_after = rows(R8_REFRESHED)
    assert_true(all(not row["realized_forward_return"] and not row["benchmark_forward_return"] and not row["excess_vs_QQQ"] for row in refreshed_after), "Realized returns were fabricated")

    csv_outputs = [DISCOVERY, COVERAGE_AUDIT, REPAIR_MAPPING, REFRESH_CONTRACT, SCOPE_AUDIT, DECISION]
    for output in csv_outputs:
        text = output.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action recommendation language found: {output}")
        assert_true("realized_forward_return" not in text, f"Realized-return field should not be produced: {output}")
        assert_true("benchmark_forward_return" not in text, f"Benchmark-return field should not be produced: {output}")
    for report in REPORTS:
        text = report.read_text(encoding="utf-8")
        assert_true("No buy/sell/hold recommendation was created" in text, "Required no-recommendation statement missing")
        assert_true("Technical-only observation must not be interpreted as full-weight result" in text, "Full-weight interpretation boundary missing")
        assert_true("No returns were computed" in text, "No-return-computation statement missing")

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
            created = [path for path in root.rglob("*V21_044_R8B*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r8b_technical_only_price_cache_refresh_or_source_repair")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
