#!/usr/bin/env python
"""Formal checks for V21.047-R1A overlay metric-attribution repair."""

from __future__ import annotations

import csv
import hashlib
import py_compile
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_047_r1a_overlay_metric_attribution_repair.py"
WRAPPER = ROOT / "scripts/v21/run_v21_047_r1a_overlay_metric_attribution_repair.ps1"
REV = ROOT / "outputs/v21/review"
RC = ROOT / "outputs/v21/read_center"

OUTPUTS = [
    "V21_047_R1A_UPSTREAM_ATTRIBUTION_WARNING_AUDIT.csv",
    "V21_047_R1A_OVERLAY_LEVEL_METRIC_RECONSTRUCTION.csv",
    "V21_047_R1A_SAME_OVERLAY_PRESERVATION_AUDIT.csv",
    "V21_047_R1A_NO_OP_DETECTION_AUDIT.csv",
    "V21_047_R1A_REPAIRED_BALANCED_SCORE_AUDIT.csv",
    "V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv",
    "V21_047_R1A_REVIEW_WORTHINESS_AUDIT.csv",
    "V21_047_R1A_LEAKAGE_AND_SCOPE_AUDIT.csv",
    "V21_047_R1A_DECISION_SUMMARY.csv",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"missing {path}"
    assert path.stat().st_size > 0, f"empty {path}"
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, f"no rows in {path}"
    return rows


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_true(row: dict[str, str], key: str) -> None:
    assert row.get(key, "").upper() == "TRUE", f"{key} must be TRUE"


def assert_false(row: dict[str, str], key: str) -> None:
    assert row.get(key, "").upper() == "FALSE", f"{key} must be FALSE"


def main() -> int:
    # 1. Production script compiles.
    py_compile.compile(str(SCRIPT), doraise=True)

    # 2. PowerShell wrapper parses.
    parse = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw "
            "scripts/v21/run_v21_047_r1a_overlay_metric_attribution_repair.ps1), "
            "[ref]$null) | Out-Null; 'PARSE_OK'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "PARSE_OK" in parse.stdout

    official_files = [
        REV / "V21_047_DECISION_SUMMARY.csv",
        REV / "V21_047_R1_DECISION_SUMMARY.csv",
        REV / "V21_046_R4_DECISION_SUMMARY.csv",
        ROOT / "outputs/v21/backtest/V21_047_OVERLAY_RISK_METRIC_SUMMARY.csv",
    ]
    before = {path: digest(path) for path in official_files}

    # 3. Wrapper executes. Research partial-pass and warning statuses remain exit zero.
    run = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "final_status=" in run.stdout
    assert "decision=" in run.stdout
    assert "repaired_best_balanced_overlay=" in run.stdout
    assert "TURNOVER_BUFFER_RANK_30_no_op_status=" in run.stdout
    assert "any_single_overlay_review_worthy=" in run.stdout
    assert "recommended_next_stage=" in run.stdout

    # 4. V21.047 and R1 outputs are read and explicitly recorded.
    warning = read_rows(REV / OUTPUTS[0])
    read_names = {
        row.get("input_name") for row in warning
        if row.get("audit_item") == "required_input" and row.get("read_successfully") == "TRUE"
    }
    assert "v047_decision" in read_names
    assert "r1_decision" in read_names
    assert "r1_attribution" in read_names
    assert "r1_balanced" in read_names

    # 5-10. Required audit outputs exist and are non-empty.
    rows_by_name = {name: read_rows(REV / name) for name in OUTPUTS}
    metrics = rows_by_name["V21_047_R1A_OVERLAY_LEVEL_METRIC_RECONSTRUCTION.csv"]
    preservation = rows_by_name["V21_047_R1A_SAME_OVERLAY_PRESERVATION_AUDIT.csv"]
    noop = rows_by_name["V21_047_R1A_NO_OP_DETECTION_AUDIT.csv"]
    scores = rows_by_name["V21_047_R1A_REPAIRED_BALANCED_SCORE_AUDIT.csv"]
    selection = rows_by_name["V21_047_R1A_REPAIRED_BEST_CANDIDATE_SELECTION.csv"]
    review = rows_by_name["V21_047_R1A_REVIEW_WORTHINESS_AUDIT.csv"]
    decision = rows_by_name["V21_047_R1A_DECISION_SUMMARY.csv"][0]
    assert metrics and preservation and noop and scores and selection and review

    # 11. TURNOVER_BUFFER_RANK_30 is explicitly audited.
    turn30 = [row for row in noop if row.get("overlay_id") == "TURNOVER_BUFFER_RANK_30"]
    assert len(turn30) == 1
    assert turn30[0].get("no_op_status")

    # 12-13. Candidate metrics never combine overlay IDs.
    assert all(row.get("overlay_id") for row in metrics)
    assert len({row["overlay_id"] for row in metrics}) == len(metrics)
    assert all(
        row.get("overlay_id") == row.get("metric_attribution_overlay_id")
        for row in metrics
    )
    assert all(
        row.get("overlay_id") == row.get("metric_attribution_overlay_id")
        and row.get("selected_metrics_from_one_overlay_only") == "TRUE"
        for row in selection
    )

    # 14-31. Adoption and scope guardrails.
    assert_false(decision, "overlay_adoption_allowed")
    assert_false(decision, "portfolio_variant_adoption_allowed")
    assert_false(decision, "filter_adoption_allowed")
    assert_false(decision, "full_weight_result_available")
    assert_false(decision, "full_weight_rebacktest_allowed_now")
    assert_true(decision, "research_only")
    assert_true(decision, "metric_attribution_repair_only")
    for key in [
        "official_adoption_allowed",
        "official_weight_mutation",
        "official_ranking_mutation",
        "official_recommendation_allowed",
        "real_book_action_allowed",
        "broker_execution_allowed",
        "trade_action_allowed",
        "shadow_gate_allowed",
        "shadow_adoption_allowed",
        "buy_sell_hold_recommendation_created",
    ]:
        assert_false(decision, key)
    assert_false(decision, "overlay_adopted")
    assert_false(decision, "portfolio_variant_adopted")
    assert_false(decision, "filter_adopted")
    assert_false(decision, "any_overlay_adoptable_now")
    assert all(row.get("adoptable_now") == "FALSE" for row in selection)

    # 32-34. No recommendation language, yfinance, or online access.
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+yfinance\b", source, re.I | re.M)
    assert "requests." not in source.lower()
    assert "urlopen(" not in source.lower()
    assert "download(" not in source.lower()
    for name in OUTPUTS:
        text = (REV / name).read_text(encoding="utf-8", errors="ignore")
        recommendation_phrases = re.findall(
            r"\b(?:BUY|SELL|HOLD)\s+(?:RECOMMENDATION|SIGNAL|ACTION)\b", text, re.I
        )
        assert not recommendation_phrases, f"recommendation language in {name}"

    # 35. No stage files appear in prohibited roots.
    for root in [
        ROOT / "outputs/v22",
        ROOT / "outputs/v19_21",
        ROOT / "broker",
        ROOT / "execution",
        ROOT / "trade-action",
        ROOT / "official-recommendation",
        ROOT / "official-ranking",
    ]:
        if root.exists():
            touched = [
                path for path in root.rglob("*")
                if path.is_file() and "V21_047_R1A" in path.name
            ]
            assert not touched, f"forbidden output written: {touched}"

    # 36. Existing upstream/official files are unchanged.
    after = {path: digest(path) for path in official_files}
    assert before == after, "upstream or official artifacts were modified"

    # 37. Report states the full-weight boundary.
    report = RC / "V21_047_R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR_REPORT.md"
    current = RC / "CURRENT_V21_047_R1A_OVERLAY_METRIC_ATTRIBUTION_REPAIR_REPORT.md"
    report_text = report.read_text(encoding="utf-8")
    assert current.read_text(encoding="utf-8") == report_text
    assert (
        "Technical-only overlay attribution repair results must not be interpreted "
        "as full-weight results" in report_text
    )
    assert "No overlay was adopted." in report_text
    assert "Full-weight remains blocked: TRUE" in report_text

    print("V21_047_R1A_TESTS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
