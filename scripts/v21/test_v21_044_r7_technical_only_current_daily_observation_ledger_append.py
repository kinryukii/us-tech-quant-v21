from __future__ import annotations

import ast
import csv
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_044_r7_technical_only_current_daily_observation_ledger_append.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_044_r7_technical_only_current_daily_observation_ledger_append.ps1"
REVIEW = ROOT / "outputs" / "v21" / "review"
LEDGER_DIR = ROOT / "outputs" / "v21" / "ledger"
READ_CENTER = ROOT / "outputs" / "v21" / "read_center"

R6 = REVIEW / "V21_044_R6_CONTINUITY_GATE_DECISION_SUMMARY.csv"
SOURCE_AUDIT = REVIEW / "V21_044_R7_CURRENT_TECHNICAL_SOURCE_AUDIT.csv"
BOUNDARY_AUDIT = REVIEW / "V21_044_R7_OBSERVATION_SCOPE_BOUNDARY_AUDIT.csv"
SUMMARY = REVIEW / "V21_044_R7_OBSERVATION_DECISION_SUMMARY.csv"
LEDGER = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER.csv"
APPEND = LEDGER_DIR / "V21_044_R7_CURRENT_TECHNICAL_ONLY_OBSERVATION_APPEND.csv"
INTEGRITY = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_LEDGER_INTEGRITY_AUDIT.csv"
MATURITY = LEDGER_DIR / "V21_044_R7_TECHNICAL_ONLY_MATURITY_SCHEDULE.csv"
REPORTS = [
    READ_CENTER / "V21_044_R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND_REPORT.md",
    READ_CENTER / "CURRENT_V21_044_R7_TECHNICAL_ONLY_CURRENT_DAILY_OBSERVATION_LEDGER_APPEND_REPORT.md",
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


def guarded_snapshot() -> dict[Path, int]:
    snap: dict[Path, int] = {}
    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    snap[path] = path.stat().st_mtime_ns
    return snap


def main() -> int:
    assert_true(SCRIPT.exists() and WRAPPER.exists(), "R7 production files missing")
    py_compile.compile(str(SCRIPT), doraise=True)
    source_text = SCRIPT.read_text(encoding="utf-8")
    assert_true("yfinance" not in source_text.lower(), "Forbidden market-data package referenced")
    tree = ast.parse(source_text)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert_true(not imports.intersection({"requests", "urllib", "httpx", "aiohttp"}), "Online-download module imported")

    parsed = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts/v21/run_v21_044_r7_technical_only_current_daily_observation_ledger_append.ps1'), [ref]$null) | Out-Null; 'PARSE_OK'",
    ], "PowerShell parse")
    assert_true("PARSE_OK" in parsed.stdout, "PowerShell wrapper parse failed")

    r6 = rows(R6)[0]
    assert_true(r6["final_status"] == "PARTIAL_PASS_V21_044_R6_TECHNICAL_ONLY_CONTINUITY_WITH_WARNINGS", "R6 status is not ready")
    assert_true(r6["decision"] == "ALLOW_TECHNICAL_ONLY_OBSERVATION_WITH_WEAK_HIT_RATE_WARNING", "R6 decision is not ready")
    assert_true(r6["technical_only_shadow_observation_continuity_allowed"] == "TRUE", "R6 continuity is not allowed")

    before_ledger = rows(LEDGER) if LEDGER.exists() else []
    before_ids = [row["observation_id"] for row in before_ledger]
    before_guarded = guarded_snapshot()
    wrapper = run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "scripts/v21/run_v21_044_r7_technical_only_current_daily_observation_ledger_append.ps1",
    ], "PowerShell wrapper")
    assert_true("wrapper_final_status=" in wrapper.stdout, "Wrapper status output missing")
    assert_true(before_guarded == guarded_snapshot(), "Forbidden output area changed")

    for path in [SOURCE_AUDIT, BOUNDARY_AUDIT, SUMMARY, LEDGER, APPEND, INTEGRITY, MATURITY, *REPORTS]:
        assert_true(path.exists() and path.stat().st_size > 0, f"Required output missing: {path}")

    summary = rows(SUMMARY)[0]
    assert_true(summary["final_status"] in {
        "PASS_V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER_APPENDED",
        "PARTIAL_PASS_V21_044_R7_TECHNICAL_ONLY_OBSERVATION_LEDGER_APPENDED_WITH_PRICE_WARNINGS",
        "PARTIAL_PASS_V21_044_R7_NO_NEW_ROWS_DUPLICATE_OBSERVATION_DATE",
    }, "Unexpected successful R7 status")
    assert_true(summary["selected_technical_source"] == "outputs/v21/review/V21_044_R4_TECHNICAL_ONLY_HISTORICAL_SCORE_PANEL.csv", "Wrong technical source selected")
    assert_true(summary["observation_as_of_date"] == "2026-06-16", "Embedded observation date not used")

    source_audit = rows(SOURCE_AUDIT)
    selected = [row for row in source_audit if row["selected"] == "TRUE"]
    assert_true(len(selected) == 1, "Source audit must select exactly one source")
    assert_true(selected[0]["has_technical_rank"] == "TRUE", "Selected source lacks explicit rank")
    assert_true(any(row["candidate_file"].endswith("V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv") and row["selected"] == "FALSE" for row in source_audit), "V21_038 rank limitation not audited")

    ledger = rows(LEDGER)
    assert_true(all(observation_id in [row["observation_id"] for row in ledger] for observation_id in before_ids), "Prior ledger rows were not preserved")
    ids = [row["observation_id"] for row in ledger]
    assert_true(len(ids) == len(set(ids)), "Duplicate observation IDs found")
    keys = [(row["observation_as_of_date"], row["ticker"], row["bucket"], row["forward_window"]) for row in ledger]
    assert_true(len(keys) == len(set(keys)), "Duplicate natural observation keys found")

    current = [row for row in ledger if row["observation_as_of_date"] == summary["observation_as_of_date"]]
    assert_true({row["bucket"] for row in current} == {"Top20", "Top50"}, "Top20/Top50 buckets missing")
    assert_true({row["forward_window"] for row in current} == {"5D", "10D", "20D", "60D"}, "Forward windows incomplete")
    assert_true(len({row["ticker"] for row in current if row["bucket"] == "Top20"}) == 20, "Top20 ticker count is not 20")
    assert_true(len({row["ticker"] for row in current if row["bucket"] == "Top50"}) == 50, "Top50 ticker count is not 50")
    assert_true(len(current) == 280, "Current observation set must contain 280 rows")
    assert_true(all(row["scheduled_maturity_date"] for row in current), "Maturity date missing")
    assert_true(all(row["maturity_status"] == "PENDING" for row in current), "Current rows are not pending")
    assert_true(all(row["realized_forward_return"] == "" and row["benchmark_forward_return"] == "" and row["excess_vs_QQQ"] == "" for row in current), "Pending returns must be blank")
    assert_true(all(row["weak_hit_rate_warning"] == "TRUE" for row in current), "Weak-hit-rate warning missing")

    maturity = rows(MATURITY)
    assert_true(len(maturity) == len(ledger), "Maturity schedule does not cover the full ledger")
    integrity = {row["audit_check"]: row["check_passed"] for row in rows(INTEGRITY)}
    assert_true(all(value == "TRUE" for value in integrity.values()), "Ledger integrity audit failed")

    for row in current:
        assert_true(row["research_only"] == "TRUE" and row["observation_only"] == "TRUE" and row["technical_only_observation"] == "TRUE", "Positive guardrail missing")
        for field in FALSE_GUARDRAILS:
            assert_true(row[field] == "FALSE", f"{field} must be FALSE")
    for field in FALSE_GUARDRAILS:
        assert_true(summary[field] == "FALSE", f"Summary {field} must be FALSE")
    assert_true(summary["full_weight_blocked"] == "TRUE", "Full-weight blocked status missing")

    for report_path in REPORTS:
        text = report_path.read_text(encoding="utf-8")
        assert_true("Technical-only observation is not full-weight evidence" in text, "Technical/full-weight boundary missing")
        assert_true(not re.search(r"\b(?:buy|sell|hold)\b", text, flags=re.IGNORECASE), "Prohibited action language found in report")

    forbidden_roots = [
        ROOT / "outputs" / "v22", ROOT / "outputs" / "v19_21", ROOT / "broker",
        ROOT / "execution", ROOT / "trade-action", ROOT / "trade_action",
    ]
    for root in forbidden_roots:
        if root.exists():
            created = [path for path in root.rglob("*V21_044_R7*") if path.is_file()]
            assert_true(not created, f"Forbidden output created: {created}")

    print("PASS test_v21_044_r7_technical_only_current_daily_observation_ledger_append")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
