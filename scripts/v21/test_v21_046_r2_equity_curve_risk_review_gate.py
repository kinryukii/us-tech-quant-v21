from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_046_r2_equity_curve_risk_review_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_046_r2_equity_curve_risk_review_gate.ps1"
REVIEW = ROOT / "outputs" / "v21" / "review"
BT = ROOT / "outputs" / "v21" / "backtest"
RC = ROOT / "outputs" / "v21" / "read_center"

OUTPUTS = [
    REVIEW / "V21_046_R2_UPSTREAM_READINESS_AUDIT.csv",
    REVIEW / "V21_046_R2_EXTREME_PERFORMANCE_SANITY_AUDIT.csv",
    REVIEW / "V21_046_R2_RETURN_CONSTRUCTION_AUDIT.csv",
    REVIEW / "V21_046_R2_REBALANCE_HOLDING_AUDIT.csv",
    REVIEW / "V21_046_R2_PRICE_OUTLIER_AUDIT.csv",
    REVIEW / "V21_046_R2_CONCENTRATION_AUDIT.csv",
    REVIEW / "V21_046_R2_BENCHMARK_COMPARISON_AUDIT.csv",
    REVIEW / "V21_046_R2_ETF_COMPARATOR_LIMITATION_AUDIT.csv",
    REVIEW / "V21_046_R2_SCOPE_BOUNDARY_AUDIT.csv",
    REVIEW / "V21_046_R2_DECISION_SUMMARY.csv",
]
REPORTS = [
    RC / "V21_046_R2_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md",
    RC / "CURRENT_V21_046_R2_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md",
]
FALSE_FIELDS = ["portfolio_variant_adoption_allowed","filter_adoption_allowed","full_weight_result_available","full_weight_rebacktest_allowed_now","official_adoption_allowed","official_weight_mutation","official_ranking_mutation","official_recommendation_allowed","real_book_action_allowed","broker_execution_allowed","trade_action_allowed","shadow_gate_allowed","shadow_adoption_allowed","buy_sell_hold_recommendation_created","online_download_attempted","yfinance_used"]


def assert_true(v: bool, msg: str) -> None:
    if not v:
        raise AssertionError(msg)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=300)
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
    parsed = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_046_r2_equity_curve_risk_review_gate.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'"], "parse")
    assert_true("PARSE_OK" in parsed.stdout, "parse failed")
    assert_true((BT / "V21_046_EQUITY_CURVE_RISK_METRIC_SUMMARY.csv").exists(), "V21.046 outputs missing")
    before = protected_snapshot()
    wrapper = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/v21/run_v21_046_r2_equity_curve_risk_review_gate.ps1"], "wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "wrapper missing summary")
    assert_true(before == protected_snapshot(), "Protected or official file changed")
    for p in OUTPUTS + REPORTS:
        assert_true(p.exists() and p.stat().st_size > 0, f"Missing output {p}")
    extreme = rows(REVIEW / "V21_046_R2_EXTREME_PERFORMANCE_SANITY_AUDIT.csv")
    target = [r for r in extreme if r["curve_name"] == "TECH_TOP50_EQUAL_WEIGHT_60D"][0]
    assert_true(float(target["total_return"]) > 10, "Target total return not extreme")
    assert_true("TOTAL_RETURN_EXTREME_WARNING" in target["extreme_performance_warning"], "Extreme return not flagged")
    summary = rows(REVIEW / "V21_046_R2_DECISION_SUMMARY.csv")[0]
    assert_true(summary["portfolio_variant_adopted"] == "FALSE", "Portfolio adopted")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["equity_curve_review_gate_only"] == "TRUE", "review_gate must be TRUE")
    for f in FALSE_FIELDS:
        assert_true(summary[f] == "FALSE", f"{f} must be FALSE")
    for p in OUTPUTS:
        text = p.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found {p}")
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only equity curve results must not be interpreted as full-weight results" in report, "Full-weight boundary missing")
    print("PASS test_v21_046_r2_equity_curve_risk_review_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
