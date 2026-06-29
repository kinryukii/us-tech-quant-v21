from __future__ import annotations

import csv
import py_compile
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_043_r1_current_weight_random_backtest_review_gate.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_043_r1_current_weight_random_backtest_review_gate.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "review"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"
UPSTREAM_LEAKAGE = ROOT / "outputs" / "v21" / "backtest" / "V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_043_R1_UPSTREAM_STATUS_AUDIT.csv",
    OUT_DIR / "V21_043_R1_WEIGHT_SOURCE_SEMANTIC_AUDIT.csv",
    OUT_DIR / "V21_043_R1_WINDOW_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_043_R1_PER_DATE_STABILITY_AUDIT.csv",
    OUT_DIR / "V21_043_R1_TICKER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_043_R1_RSI_CANDIDATE_REVIEW.csv",
    OUT_DIR / "V21_043_R1_SAFETY_GUARDRAIL_AUDIT.csv",
    OUT_DIR / "V21_043_R1_REVIEW_DECISION_SUMMARY.csv",
    READ_CENTER / "V21_043_R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE_REPORT.md",
    READ_CENTER / "CURRENT_V21_043_R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_cmd(args: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=180)
    if result.returncode != 0:
        raise AssertionError(f"{label} failed with {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
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
        ROOT / "outputs" / "v21" / "shadow_ranking",
        ROOT / "outputs" / "v21" / "shadow-ranking",
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
        for path in root.rglob("*"):
            name = path.name.lower()
            if path.is_file() and ("official" in name or "ranking" in name or "recommendation" in name):
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
        ROOT / "outputs" / "v21" / "shadow_ranking",
        ROOT / "outputs" / "v21" / "shadow-ranking",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [p for p in root.rglob("*V21_043_R1*") if p.is_file()]
            assert_true(not created, f"Unexpected V21_043_R1 files in guarded root: {created}")


def main() -> int:
    assert_true(SCRIPT.exists(), "Production script missing")
    assert_true(WRAPPER.exists(), "PowerShell wrapper missing")
    py_compile.compile(str(SCRIPT), doraise=True)

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert_true("yfinance" not in script_text, "No yfinance import/reference is allowed")

    parse = run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_043_r1_current_weight_random_backtest_review_gate.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        "PowerShell parse",
    )
    assert_true("PARSE_OK" in parse.stdout, "PowerShell wrapper did not parse")

    before = snapshot_guarded_files()
    run = run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/v21/run_v21_043_r1_current_weight_random_backtest_review_gate.ps1",
        ],
        "PowerShell wrapper execution",
    )
    assert_true("final_status=" in run.stdout, "Wrapper must print final_status")
    assert_true("decision=" in run.stdout, "Wrapper must print decision")
    assert_guarded_unchanged(before)

    for path in REQUIRED_OUTPUTS:
        assert_true(path.exists(), f"Required output missing: {path}")
        assert_true(path.stat().st_size > 0, f"Required output empty: {path}")

    summary = read_csv(OUT_DIR / "V21_043_R1_REVIEW_DECISION_SUMMARY.csv")[0]
    assert_true(summary["research_only"] == "TRUE", "research_only must be TRUE")
    assert_true(summary["official_adoption_allowed"] == "FALSE", "official_adoption_allowed must be FALSE")
    assert_true(summary["official_weight_mutation"] == "FALSE", "official_weight_mutation must be FALSE")
    assert_true(summary["official_ranking_mutation"] == "FALSE", "official_ranking_mutation must be FALSE")
    assert_true(summary["real_book_action_allowed"] == "FALSE", "real_book_action_allowed must be FALSE")
    assert_true(summary["broker_execution_allowed"] == "FALSE", "broker_execution_allowed must be FALSE")
    assert_true(summary["trade_action_allowed"] == "FALSE", "trade_action_allowed must be FALSE")
    assert_true(summary["shadow_gate_allowed"] == "FALSE", "shadow_gate_allowed must be FALSE")
    assert_true(summary["shadow_adoption_allowed"] == "FALSE", "shadow_adoption_allowed must be FALSE")

    source = read_csv(OUT_DIR / "V21_043_R1_WEIGHT_SOURCE_SEMANTIC_AUDIT.csv")[0]
    assert_true(source["source_classification"], "Weight source must be classified")
    assert_true(
        source["source_classification"] != "FULL_CURRENT_WEIGHT_SOURCE" or source["full_current_weight_source_evidence"] == "TRUE",
        "Full current-weight coverage must not be silently assumed",
    )

    windows = read_csv(OUT_DIR / "V21_043_R1_WINDOW_CONCENTRATION_AUDIT.csv")
    scopes = {row["metric_scope"] for row in windows}
    assert_true("window_balanced_mean_excess" in scopes, "Window audit must include window-balanced metric")
    assert_true("no_60d_mean_excess" in scopes, "Window audit must include no-60D metric when windows are available")

    rsi = read_csv(OUT_DIR / "V21_043_R1_RSI_CANDIDATE_REVIEW.csv")
    global_rsi = [row for row in rsi if row["candidate_name"] == "GLOBAL_RSI_CANDIDATE"]
    assert_true(global_rsi, "GLOBAL_RSI_CANDIDATE review missing")
    assert_true(global_rsi[0]["standalone_adoption_allowed"] == "FALSE", "Standalone RSI adoption must be blocked")

    upstream = read_csv(UPSTREAM_LEAKAGE)[0]
    assert_true(
        summary["leakage_violation_count"] == upstream["leakage_violation_count"],
        "Leakage violation count must be propagated from V21.042-R1",
    )

    report = (READ_CENTER / "V21_043_R1_CURRENT_WEIGHT_RANDOM_BACKTEST_REVIEW_GATE_REPORT.md").read_text(encoding="utf-8")
    assert_true("research_only = TRUE" in report, "Report must include research_only guardrail")
    assert_true("shadow_adoption_allowed = FALSE" in report, "Report must include shadow adoption guardrail")

    print("PASS test_v21_043_r1_current_weight_random_backtest_review_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
