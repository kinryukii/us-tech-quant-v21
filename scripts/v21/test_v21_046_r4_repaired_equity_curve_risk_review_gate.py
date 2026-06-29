from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_046_r4_repaired_equity_curve_risk_review_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_046_r4_repaired_equity_curve_risk_review_gate.ps1"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
OUTPUTS = [
    REV / "V21_046_R4_UPSTREAM_REPAIR_VALIDATION_AUDIT.csv",
    REV / "V21_046_R4_HEADLINE_RISK_METRIC_AUDIT.csv",
    REV / "V21_046_R4_BEST_VARIANT_AUDIT.csv",
    REV / "V21_046_R4_BETA_ACTIVE_RISK_AUDIT.csv",
    REV / "V21_046_R4_DRAWDOWN_AUDIT.csv",
    REV / "V21_046_R4_TURNOVER_COST_AUDIT.csv",
    REV / "V21_046_R4_SUBPERIOD_STABILITY_AUDIT.csv",
    REV / "V21_046_R4_HOLDINGS_CONCENTRATION_AUDIT.csv",
    REV / "V21_046_R4_PRICE_OUTLIER_FOLLOWUP_AUDIT.csv",
    REV / "V21_046_R4_ETF_COMPARATOR_LIMITATION_AUDIT.csv",
    REV / "V21_046_R4_SCOPE_BOUNDARY_AUDIT.csv",
    REV / "V21_046_R4_DECISION_SUMMARY.csv",
]
REPORTS = [
    RC / "V21_046_R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md",
    RC / "CURRENT_V21_046_R4_REPAIRED_EQUITY_CURVE_RISK_REVIEW_GATE_REPORT.md",
]
FALSE_FIELDS = ["portfolio_variant_adoption_allowed","filter_adoption_allowed","full_weight_result_available","full_weight_rebacktest_allowed_now","official_adoption_allowed","official_weight_mutation","official_ranking_mutation","official_recommendation_allowed","real_book_action_allowed","broker_execution_allowed","trade_action_allowed","shadow_gate_allowed","shadow_adoption_allowed","buy_sell_hold_recommendation_created","online_download_attempted","yfinance_used"]


def assert_true(v: bool, msg: str) -> None:
    if not v:
        raise AssertionError(msg)


def rows(p: Path) -> list[dict[str, str]]:
    with p.open("r", encoding="utf-8-sig", newline="") as h:
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
    parsed = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_046_r4_repaired_equity_curve_risk_review_gate.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'"], "parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parse failed")
    assert_true((REV / "V21_046_R3_DECISION_SUMMARY.csv").exists(), "R3 output missing")
    before = protected_snapshot()
    wrapper = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/v21/run_v21_046_r4_repaired_equity_curve_risk_review_gate.ps1"], "wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")
    for p in OUTPUTS + REPORTS:
        assert_true(p.exists() and p.stat().st_size > 0, f"Missing output {p}")
    for p in OUTPUTS[:-1]:
        assert_true(rows(p), f"Empty audit {p}")
    summary = rows(REV / "V21_046_R4_DECISION_SUMMARY.csv")[0]
    assert_true(summary["portfolio_variant_adopted"] == "FALSE", "Portfolio adopted")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["repaired_equity_curve_risk_review_gate_only"] == "TRUE", "review gate flag must be TRUE")
    for f in FALSE_FIELDS:
        assert_true(summary[f] == "FALSE", f"{f} must be FALSE")
    for p in OUTPUTS:
        text = p.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found: {p}")
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only repaired equity curve results must not be interpreted as full-weight results" in report, "Full-weight boundary missing")
    print("PASS test_v21_046_r4_repaired_equity_curve_risk_review_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
