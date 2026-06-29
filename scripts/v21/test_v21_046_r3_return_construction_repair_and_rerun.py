from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_046_r3_return_construction_repair_and_rerun.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_046_r3_return_construction_repair_and_rerun.ps1"
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"

OUTS = [
    BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv",
    BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv",
    BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv",
    BT / "V21_046_R3_REPAIRED_BENCHMARK_EQUITY_CURVE_PANEL.csv",
    BT / "V21_046_R3_REPAIRED_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    BT / "V21_046_R3_REPAIRED_RELATIVE_METRICS_VS_QQQ.csv",
    BT / "V21_046_R3_REPAIRED_TURNOVER_AND_COST_AUDIT.csv",
    BT / "V21_046_R3_REPAIRED_DRAWDOWN_DIAGNOSTICS.csv",
    BT / "V21_046_R3_INVALID_VS_REPAIRED_CURVE_COMPARISON.csv",
    BT / "V21_046_R3_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv",
    REV / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AUDIT.csv",
    REV / "V21_046_R3_REPAIRED_EQUITY_CURVE_SANITY_AUDIT.csv",
    REV / "V21_046_R3_PRICE_OUTLIER_AUDIT.csv",
    REV / "V21_046_R3_REBALANCE_HOLDING_AUDIT.csv",
    REV / "V21_046_R3_BENCHMARK_COMPARISON_AUDIT.csv",
    REV / "V21_046_R3_SCOPE_BOUNDARY_AUDIT.csv",
    REV / "V21_046_R3_DECISION_SUMMARY.csv",
]
REPORTS = [
    RC / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN_REPORT.md",
    RC / "CURRENT_V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AND_RERUN_REPORT.md",
]
FALSE_FIELDS = ["portfolio_variant_adoption_allowed","filter_adoption_allowed","full_weight_result_available","full_weight_rebacktest_allowed_now","official_adoption_allowed","official_weight_mutation","official_ranking_mutation","official_recommendation_allowed","real_book_action_allowed","broker_execution_allowed","trade_action_allowed","shadow_gate_allowed","shadow_adoption_allowed","buy_sell_hold_recommendation_created","online_download_attempted","yfinance_used"]


def assert_true(v: bool, msg: str) -> None:
    if not v:
        raise AssertionError(msg)


def rows(p: Path) -> list[dict[str, str]]:
    with p.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=600)
    if p.returncode:
        raise AssertionError(f"{label} failed\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


def imports(text: str) -> set[str]:
    tree = ast.parse(text)
    return {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}


def protected_snapshot() -> dict[Path, int]:
    snap = {}
    for root in [ROOT/"outputs"/"v22", ROOT/"outputs"/"v19_21", ROOT/"broker", ROOT/"execution", ROOT/"trade-action", ROOT/"trade_action"]:
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    snap[p] = p.stat().st_mtime_ns
    for root in [ROOT/"outputs"/"v21", ROOT/"outputs"/"v20"]:
        if root.exists():
            for p in root.rglob("*"):
                name = p.name.lower()
                if p.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name):
                    snap[p] = p.stat().st_mtime_ns
    return snap


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "Production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imps = imports(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imps, "yfinance import exists")
    assert_true(not imps.intersection({"requests","urllib","httpx","aiohttp"}), "Online-download module imported")
    parsed = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_046_r3_return_construction_repair_and_rerun.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'"], "parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parse failed")
    assert_true((REV / "V21_046_R2_DECISION_SUMMARY.csv").exists(), "R2 decision missing")
    before = protected_snapshot()
    wrapper = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/v21/run_v21_046_r3_return_construction_repair_and_rerun.ps1"], "wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")
    for p in OUTS + REPORTS:
        assert_true(p.exists() and p.stat().st_size > 0, f"Missing output {p}")
    repaired = rows(BT / "V21_046_R3_REPAIRED_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv")
    assert_true(repaired, "Repaired daily returns empty")
    assert_true(all(r["daily_price_returns_used"] == "TRUE" for r in repaired[:100]), "Daily price returns not marked used")
    assert_true(all(r["forward_returns_used_as_daily"] == "FALSE" for r in repaired[:100]), "Forward returns reused as daily")
    audit = rows(REV / "V21_046_R3_RETURN_CONSTRUCTION_REPAIR_AUDIT.csv")[0]
    assert_true(audit["forward_returns_used_as_daily"] == "FALSE", "Audit says forward returns used as daily")
    assert_true(audit["holding_period_returns_reused_as_daily"] == "FALSE", "Holding-period returns reused")
    assert_true(audit["overlapping_portfolios_double_counted"] == "FALSE", "Overlapping portfolios double counted")
    assert_true(audit["daily_price_returns_used"] == "TRUE", "Daily price returns not used")
    assert_true(audit["weights_sum_valid"] == "TRUE", "Weights do not sum to 1")
    etf = rows(BT / "V21_046_R3_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv")[0]
    assert_true(etf["curve_fabricated"] == "FALSE", "ETF curve fabricated")
    summary = rows(REV / "V21_046_R3_DECISION_SUMMARY.csv")[0]
    assert_true(summary["portfolio_variant_adopted"] == "FALSE", "Portfolio adopted")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["return_construction_repair_only"] == "TRUE", "repair_only must be TRUE")
    assert_true(summary["repaired_equity_curve_backtest_only"] == "TRUE", "backtest_only must be TRUE")
    for f in FALSE_FIELDS:
        assert_true(summary[f] == "FALSE", f"{f} must be FALSE")
    for p in OUTS:
        text = p.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found: {p}")
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only repaired equity curve results must not be interpreted as full-weight results" in report, "Full-weight boundary missing")
    print("PASS test_v21_046_r3_return_construction_repair_and_rerun")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
