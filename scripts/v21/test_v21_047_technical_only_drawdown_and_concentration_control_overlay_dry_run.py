from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run.ps1"
BT = ROOT / "outputs" / "v21" / "backtest"
REV = ROOT / "outputs" / "v21" / "review"
RC = ROOT / "outputs" / "v21" / "read_center"
OUTS = [
    BT/"V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv", BT/"V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv",
    BT/"V21_047_OVERLAY_HOLDINGS_BY_REBALANCE.csv", BT/"V21_047_OVERLAY_TURNOVER_COST_PANEL.csv",
    BT/"V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv", BT/"V21_047_OVERLAY_RELATIVE_METRICS_VS_QQQ.csv",
    BT/"V21_047_OVERLAY_DRAWDOWN_DIAGNOSTICS.csv", BT/"V21_047_OVERLAY_SUBPERIOD_STABILITY_PANEL.csv",
    REV/"V21_047_UPSTREAM_READINESS_AUDIT.csv", REV/"V21_047_OVERLAY_DEFINITION_REGISTER.csv",
    REV/"V21_047_TURNOVER_REDUCTION_AUDIT.csv", REV/"V21_047_DRAWDOWN_IMPROVEMENT_AUDIT.csv",
    REV/"V21_047_ALPHA_PRESERVATION_AUDIT.csv", REV/"V21_047_CONCENTRATION_HOLDINGS_AUDIT.csv",
    REV/"V21_047_SCOPE_BOUNDARY_AUDIT.csv", REV/"V21_047_DECISION_SUMMARY.csv",
]
REPORTS = [RC/"V21_047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN_REPORT.md", RC/"CURRENT_V21_047_TECHNICAL_ONLY_DRAWDOWN_AND_CONCENTRATION_CONTROL_OVERLAY_DRY_RUN_REPORT.md"]
FALSE_FIELDS = ["overlay_adoption_allowed","portfolio_variant_adoption_allowed","filter_adoption_allowed","full_weight_result_available","full_weight_rebacktest_allowed_now","official_adoption_allowed","official_weight_mutation","official_ranking_mutation","official_recommendation_allowed","real_book_action_allowed","broker_execution_allowed","trade_action_allowed","shadow_gate_allowed","shadow_adoption_allowed","buy_sell_hold_recommendation_created","online_download_attempted","yfinance_used"]


def assert_true(v: bool, msg: str) -> None:
    if not v: raise AssertionError(msg)
def rows(p: Path) -> list[dict[str, str]]:
    with p.open("r", encoding="utf-8-sig", newline="") as h: return list(csv.DictReader(h))
def run(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=300)
    if p.returncode: raise AssertionError(f"{label} failed\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p
def imports(text: str) -> set[str]:
    tree = ast.parse(text)
    return {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
def protected_snapshot() -> dict[Path, int]:
    snap = {}
    for root in [ROOT/"outputs"/"v22", ROOT/"outputs"/"v19_21", ROOT/"broker", ROOT/"execution", ROOT/"trade-action", ROOT/"trade_action"]:
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file(): snap[p] = p.stat().st_mtime_ns
    for root in [ROOT/"outputs"/"v21", ROOT/"outputs"/"v20"]:
        if root.exists():
            for p in root.rglob("*"):
                name = p.name.lower()
                if p.is_file() and "official" in name and ("ranking" in name or "recommendation" in name or "weight" in name): snap[p] = p.stat().st_mtime_ns
    return snap


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "Production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    imps = imports(SCRIPT.read_text(encoding="utf-8"))
    assert_true("yfinance" not in imps, "yfinance import exists")
    assert_true(not imps.intersection({"requests","urllib","httpx","aiohttp"}), "Online-download module imported")
    parsed = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command","[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'"], "parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell parse failed")
    assert_true((REV/"V21_046_R4_DECISION_SUMMARY.csv").exists(), "R4 input missing")
    before = protected_snapshot()
    wrapper = run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/v21/run_v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run.ps1"], "wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper summary missing")
    assert_true(before == protected_snapshot(), "Protected or official file changed")
    for p in OUTS + REPORTS: assert_true(p.exists() and p.stat().st_size > 0, f"Missing output {p}")
    assert_true(rows(REV/"V21_047_OVERLAY_DEFINITION_REGISTER.csv"), "Register empty")
    assert_true(rows(BT/"V21_047_OVERLAY_EQUITY_CURVE_PANEL.csv"), "Equity panel empty")
    assert_true(rows(BT/"V21_047_OVERLAY_DAILY_RETURNS_PANEL.csv"), "Returns panel empty")
    assert_true(rows(BT/"V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv"), "Risk summary empty")
    summary = rows(REV/"V21_047_DECISION_SUMMARY.csv")[0]
    assert_true(summary["overlay_adopted"] == "FALSE", "Overlay adopted")
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["overlay_dry_run_only"] == "TRUE", "overlay_dry_run_only must be TRUE")
    for f in FALSE_FIELDS: assert_true(summary[f] == "FALSE", f"{f} must be FALSE")
    for p in OUTS:
        text = p.read_text(encoding="utf-8-sig")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), f"Action language found {p}")
    report = REPORTS[0].read_text(encoding="utf-8")
    assert_true("Technical-only overlay results must not be interpreted as full-weight results" in report, "Full-weight boundary missing")
    print("PASS test_v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
