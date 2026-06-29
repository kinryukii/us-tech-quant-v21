from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest.ps1"
BACKTEST = ROOT / "outputs" / "v21" / "backtest"
REVIEW = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R3B = REVIEW / "V21_045_R3B_DECISION_SUMMARY.csv"
R5 = BACKTEST / "V21_044_R5_TECHNICAL_ONLY_REBACKTEST_PANEL.csv"
R6 = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
OUTS = [
    BACKTEST / "V21_046_TECHNICAL_ONLY_EQUITY_CURVE_PANEL.csv",
    BACKTEST / "V21_046_TECHNICAL_ONLY_PORTFOLIO_HOLDINGS_BY_REBALANCE.csv",
    BACKTEST / "V21_046_TECHNICAL_ONLY_PORTFOLIO_DAILY_RETURNS.csv",
    BACKTEST / "V21_046_BENCHMARK_EQUITY_CURVE_PANEL.csv",
    BACKTEST / "V21_046_ETF_ROTATION_COMPARATOR_PANEL.csv",
    BACKTEST / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv",
    BACKTEST / "V21_046_RELATIVE_METRICS_VS_QQQ.csv",
    BACKTEST / "V21_046_TURNOVER_AND_COST_AUDIT.csv",
    BACKTEST / "V21_046_DRAWDOWN_DIAGNOSTICS.csv",
    BACKTEST / "V21_046_PRICE_COVERAGE_AUDIT.csv",
    BACKTEST / "V21_046_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv",
    REVIEW / "V21_046_EQUITY_CURVE_BACKTEST_DECISION_SUMMARY.csv",
    REVIEW / "V21_046_SCOPE_BOUNDARY_AUDIT.csv",
    REVIEW / "V21_046_READINESS_FOR_NEXT_REVIEW.csv",
]
REPORTS = [
    READ_CENTER / "V21_046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST_REPORT.md",
    READ_CENTER / "CURRENT_V21_046_TECHNICAL_ONLY_CONTINUOUS_EQUITY_CURVE_AND_RISK_METRIC_BACKTEST_REPORT.md",
]
FALSE_FIELDS = ["filter_adoption_allowed","full_weight_result_available","full_weight_rebacktest_allowed_now","official_adoption_allowed","official_weight_mutation","official_ranking_mutation","official_recommendation_allowed","real_book_action_allowed","broker_execution_allowed","trade_action_allowed","shadow_gate_allowed","shadow_adoption_allowed","buy_sell_hold_recommendation_created","online_download_attempted","yfinance_used"]


def assert_true(v: bool, msg: str) -> None:
    if not v:
        raise AssertionError(msg)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
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
    parsed = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'"], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parse failed")
    assert_true(R3B.exists() and rows(R3B)[0]["retained_stream"] == "BASELINE_TECHNICAL_ONLY", "R3B retention status not read")
    assert_true(R5.exists() and R5.stat().st_size > 0 and R6.exists() and R6.stat().st_size > 0, "R5/R6 inputs missing")
    before = protected_snapshot()
    wrapper = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/v21/run_v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest.ps1"], "Wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper output missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")
    for p in OUTS + REPORTS:
        assert_true(p.exists() and p.stat().st_size > 0, f"Missing output: {p}")
    assert_true(rows(OUTS[0]), "Equity curve panel empty")
    assert_true(rows(OUTS[2]), "Daily returns empty")
    assert_true(rows(BACKTEST / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv"), "Risk summary empty")
    assert_true(rows(BACKTEST / "V21_046_RELATIVE_METRICS_VS_QQQ.csv"), "Relative metrics empty")
    assert_true(rows(BACKTEST / "V21_046_TURNOVER_AND_COST_AUDIT.csv"), "Turnover empty")
    assert_true(rows(BACKTEST / "V21_046_DRAWDOWN_DIAGNOSTICS.csv"), "Drawdown empty")
    etf = rows(BACKTEST / "V21_046_ETF_COMPARATOR_AVAILABILITY_AUDIT.csv")[0]
    if etf["availability_status"] == "ETF_ROTATION_DATA_LIMITED":
        assert_true(rows(BACKTEST / "V21_046_ETF_ROTATION_COMPARATOR_PANEL.csv")[0]["curve_fabricated"] == "FALSE", "ETF curve fabricated")
    summary = rows(REVIEW / "V21_046_EQUITY_CURVE_BACKTEST_DECISION_SUMMARY.csv")[0]
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["equity_curve_backtest_only"] == "TRUE", "equity_curve_backtest_only must be TRUE")
    for f in FALSE_FIELDS:
        assert_true(summary[f] == "FALSE", f"{f} must be FALSE")
    for p in OUTS:
        text = p.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found: {p}")
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only equity curve results must not be interpreted as full-weight results" in report, "Full-weight boundary missing")
    print("PASS test_v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
