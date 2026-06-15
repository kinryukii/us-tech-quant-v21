from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
SCRIPT_DIR = ROOT / "scripts" / "v20"

STAGE = "V20.44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN"
UPSTREAM_STAGE = "V20.43_DAILY_OPERATOR_REPORT_DRY_RUN"
PASS_STATUS = "PASS_V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN"
BLOCKED_STATUS = "BLOCKED_V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN"
ACCEPTED_STATUS = "ACCEPTED_WITH_RESEARCH_ONLY_LIMITS"
BLOCKED_ACCEPTANCE_STATUS = "BLOCKED"
NEXT_STAGE = "V20.45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"

V20_43_PRODUCTION = SCRIPT_DIR / "v20_43_daily_operator_report_dry_run.py"
V20_43_WRAPPER = SCRIPT_DIR / "run_v20_43_daily_operator_report_dry_run.ps1"
V20_43_TEST = SCRIPT_DIR / "test_v20_43_daily_operator_report_dry_run.py"

OUT_SUMMARY = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_SUMMARY.csv"
OUT_ARTIFACTS = CONSOLIDATION / "V20_44_UPSTREAM_ARTIFACT_VALIDATION.csv"
OUT_COUNTS = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_COUNT_RECHECK.csv"
OUT_SAFETY = CONSOLIDATION / "V20_44_DAILY_OPERATOR_REPORT_SAFETY_RECHECK.csv"
OUT_DECISION = CONSOLIDATION / "V20_44_CURRENT_RUN_READINESS_DECISION.csv"
REPORT = READ_CENTER / "V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE.md"
READ_FIRST = OPS / "V20_44_READ_FIRST.txt"

REQUIRED_ARTIFACTS = [
    ("v20_43_production_script", V20_43_PRODUCTION, "python_script", True),
    ("v20_43_wrapper", V20_43_WRAPPER, "powershell_wrapper", True),
    ("v20_43_formal_test", V20_43_TEST, "python_test", True),
    ("v20_43_manifest", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv", "csv", True),
    ("v20_43_source_status", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SOURCE_STATUS.csv", "csv", True),
    ("v20_43_section_status", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv", "csv", True),
    ("v20_43_candidate_research", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv", "csv", True),
    ("v20_43_factor_support", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv", "csv", True),
    ("v20_43_entry_strategy", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv", "csv", True),
    ("v20_43_lineage_freshness", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv", "csv", True),
    ("v20_43_next_step", CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv", "csv", True),
    ("v20_43_report", READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md", "markdown", True),
    ("v20_43_current_alias", READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md", "markdown", True),
    ("v20_43_read_first", OPS / "V20_43_READ_FIRST.txt", "text", True),
]

COUNT_CHECKS = [
    ("section_status_rows", 15, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_SECTION_STATUS.csv", "rows"),
    ("candidate_research_rows", 50, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_CANDIDATE_RESEARCH_TABLE.csv", "rows"),
    ("factor_support_rows", 21, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_FACTOR_SUPPORT_SUMMARY.csv", "rows"),
    ("entry_strategy_rows", 5, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_ENTRY_STRATEGY_SUMMARY.csv", "rows"),
    ("lineage_freshness_rows", 27, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_LINEAGE_FRESHNESS_SUMMARY.csv", "rows"),
    ("missing_required_sources", 0, CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv", "manifest_field"),
]

FALSE_FLAGS = {
    "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION",
    "OFFICIAL_RECOMMENDATION_CREATED",
    "BUY_SELL_TRIM_RECOMMENDATION_CREATED",
    "TRADING_SIGNAL_CREATED",
    "BROKER_ORDER_PATH_CREATED",
    "OFFICIAL_RANKING_MUTATED",
    "OFFICIAL_FACTOR_WEIGHTS_MUTATED",
    "DYNAMIC_WEIGHTING_EXECUTED",
    "PORTFOLIO_BACKTEST_RERUN",
    "NEW_RETURN_COMPUTATION_CREATED",
    "PROVIDER_REFRESH_EXECUTED",
    "V21_OUTPUTS_CREATED",
    "V19_21_OUTPUTS_CREATED",
}


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def read_flags(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    flags: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        flags[key.strip()] = value.strip()
    return flags


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def csv_row_count(path: Path) -> int:
    rows, _ = read_csv(path)
    return len(rows)


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


def validation_status(ok: bool) -> str:
    return "PASS" if ok else "BLOCKED"


def artifact_rows() -> list[dict[str, object]]:
    rows = []
    for name, path, artifact_type, required in REQUIRED_ARTIFACTS:
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ok = exists and non_empty
        rows.append({
            "artifact_name": name,
            "artifact_path": rel(path),
            "artifact_type": artifact_type,
            "required_flag": tf(required),
            "exists_flag": tf(exists),
            "non_empty_flag": tf(non_empty),
            "validation_status": validation_status(ok),
            "blocker_reason": "" if ok else "missing_or_empty_required_artifact",
        })
    return rows


def run_v20_43_formal_test() -> tuple[bool, str]:
    if not V20_43_TEST.exists():
        return False, "V20.43 formal test script is missing"
    result = subprocess.run(
        [sys.executable, str(V20_43_TEST)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    passed = result.returncode == 0 and "PASS_V20_43_TESTS" in result.stdout.splitlines()
    return passed, output


def count_rows() -> list[dict[str, object]]:
    rows = []
    for metric_name, expected, path, method in COUNT_CHECKS:
        if method == "rows":
            actual = csv_row_count(path)
        else:
            actual = int(clean(first_row(path).get("MISSING_REQUIRED_SOURCE_COUNT")) or "0") if path.exists() else -1
        ok = actual == expected
        rows.append({
            "metric_name": metric_name,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": validation_status(ok),
            "blocker_reason": "" if ok else f"expected_{expected}_got_{actual}",
        })
    return rows


def all_false(mapping: dict[str, str], keys: set[str]) -> bool:
    return all(mapping.get(key) == "FALSE" for key in keys if key in mapping)


def static_safety_scan() -> tuple[bool, str]:
    scan_paths = [
        V20_43_PRODUCTION,
        V20_43_WRAPPER,
        V20_43_TEST,
        SCRIPT_DIR / "v20_44_daily_operator_report_acceptance_gate_or_current_run.py",
        SCRIPT_DIR / "run_v20_44_daily_operator_report_acceptance_gate_or_current_run.ps1",
    ]
    forbidden_write_paths = [
        re.compile(r"outputs[\\/](?:v21|v19_21|v19[\\/]V19_21)", re.IGNORECASE),
        re.compile(r"outputs\s*/\s*(?:v21|v19_21)", re.IGNORECASE),
    ]
    executable_patterns = [
        re.compile(r"\bsubmit_order\s*\(|\bplace_order\s*\(|\bbroker\.(?:buy|sell|order|submit)\s*\(", re.IGNORECASE),
        re.compile(r"\blive_trading\s*=\s*TRUE\b|\bLIVE_TRADING\s*=\s*TRUE\b", re.IGNORECASE),
        re.compile(r"\breal_portfolio_mutat(?:e|ion)\b.*\bTRUE\b", re.IGNORECASE),
        re.compile(r"\brequests\.(?:get|post|put|delete)\s*\(|\bhttpx\.(?:get|post|put|delete)\s*\(", re.IGNORECASE),
        re.compile(r"\byfinance\.download\s*\(|\byf\.download\s*\(", re.IGNORECASE),
    ]
    failures = []
    for path in scan_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_write_paths:
            if pattern.search(text):
                failures.append(f"{rel(path)} matched forbidden path pattern {pattern.pattern}")
        for pattern in executable_patterns:
            if pattern.search(text):
                failures.append(f"{rel(path)} matched executable pattern {pattern.pattern}")
    return not failures, "; ".join(failures)


def safety_rows() -> list[dict[str, object]]:
    manifest = first_row(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_MANIFEST.csv")
    next_step = first_row(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv")
    read_first = read_flags(OPS / "V20_43_READ_FIRST.txt")
    report_text = (READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md").read_text(encoding="utf-8", errors="ignore") if (READ_CENTER / "V20_43_DAILY_OPERATOR_REPORT_DRY_RUN_REPORT.md").exists() else ""
    alias_text = (READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md").read_text(encoding="utf-8", errors="ignore") if (READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md").exists() else ""
    static_ok, static_detail = static_safety_scan()

    checks = [
        (
            "reporting_or_gate_only",
            "TRUE",
            tf(manifest.get("DRY_RUN_ONLY") == "TRUE" and next_step.get("DRY_RUN_ONLY") == "TRUE" and "dry run" in report_text.lower()),
            "V20.43 manifest, next-step decision, and report dry-run language",
        ),
        (
            "official_trading_allowed",
            "FALSE",
            next_step.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION", ""),
            "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION from V20.43 next-step decision",
        ),
        (
            "official_recommendation_mutated",
            "FALSE",
            manifest.get("OFFICIAL_RECOMMENDATION_CREATED", ""),
            "OFFICIAL_RECOMMENDATION_CREATED from V20.43 manifest",
        ),
        (
            "official_ranking_mutated",
            "FALSE",
            manifest.get("OFFICIAL_RANKING_MUTATED", ""),
            "OFFICIAL_RANKING_MUTATED from V20.43 manifest",
        ),
        (
            "broker_order_execution_path",
            "FALSE",
            manifest.get("BROKER_ORDER_PATH_CREATED", ""),
            "BROKER_ORDER_PATH_CREATED from V20.43 manifest plus static scan",
        ),
        (
            "provider_network_refresh",
            "FALSE",
            "FALSE" if manifest.get("PROVIDER_REFRESH_EXECUTED") == "FALSE" and read_first.get("NETWORK_REFRESH_EXECUTED") == "FALSE" else "TRUE",
            "PROVIDER_REFRESH_EXECUTED and NETWORK_REFRESH_EXECUTED safety flags",
        ),
        (
            "dynamic_weighting_mutated",
            "FALSE",
            manifest.get("DYNAMIC_WEIGHTING_EXECUTED", ""),
            "DYNAMIC_WEIGHTING_EXECUTED from V20.43 manifest",
        ),
        (
            "real_portfolio_mutated",
            "FALSE",
            "FALSE" if manifest.get("PORTFOLIO_BACKTEST_RERUN") == "FALSE" and read_first.get("PRIOR_ACCEPTED_OUTPUTS_MUTATED") == "FALSE" else "TRUE",
            "Portfolio/backtest and prior-output mutation flags",
        ),
        (
            "v21_output_path_created",
            "FALSE",
            manifest.get("V21_OUTPUTS_CREATED", ""),
            "V20.43 manifest and static scan",
        ),
        (
            "v19_21_output_path_created",
            "FALSE",
            manifest.get("V19_21_OUTPUTS_CREATED", ""),
            "V20.43 manifest and static scan",
        ),
        (
            "static_execution_safety_scan",
            "TRUE",
            tf(static_ok),
            static_detail or "No forbidden path writes or executable broker/order/provider logic found",
        ),
        (
            "current_alias_dry_run_safety",
            "TRUE",
            tf("dry run" in alias_text.lower() and "not official" in alias_text.lower()),
            "Current alias dry-run/not-official language",
        ),
        (
            "v20_43_safety_flags_false",
            "TRUE",
            tf(all_false(manifest, FALSE_FLAGS) and all_false(next_step, FALSE_FLAGS)),
            "False safety flags in V20.43 manifest and next-step decision",
        ),
    ]

    rows = []
    for check, expected, actual, evidence in checks:
        ok = actual == expected
        rows.append({
            "safety_check": check,
            "expected_value": expected,
            "actual_value": actual,
            "validation_status": validation_status(ok),
            "evidence": evidence,
            "blocker_reason": "" if ok else f"expected_{expected}_got_{actual}",
        })
    return rows


def current_alias_valid() -> bool:
    path = READ_CENTER / "V20_CURRENT_DAILY_OPERATOR_REPORT_DRY_RUN.md"
    if not path.exists() or path.stat().st_size == 0:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return UPSTREAM_STAGE in text and ("dry run" in text.lower() or "dry-run" in text.lower()) and "not official" in text.lower()


def read_first_valid() -> bool:
    flags = read_flags(OPS / "V20_43_READ_FIRST.txt")
    return (
        flags.get("STAGE_NAME") == UPSTREAM_STAGE
        and flags.get("DRY_RUN_ONLY") == "TRUE"
        and flags.get("NETWORK_REFRESH_EXECUTED") == "FALSE"
        and flags.get("BROKER_ORDER_PATH_CREATED") == "FALSE"
        and flags.get("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION") == "FALSE"
    )


def cleanup_pycache() -> None:
    for path in SCRIPT_DIR.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    artifacts = artifact_rows()
    test_passed, test_output = run_v20_43_formal_test()
    counts = count_rows()
    safety = safety_rows()
    cleanup_pycache()

    upstream_next = first_row(CONSOLIDATION / "V20_43_DAILY_OPERATOR_REPORT_NEXT_STEP_DECISION.csv")
    upstream_production_passed = clean(upstream_next.get("STATUS")) == "PASS_V20_43_DAILY_OPERATOR_REPORT_DRY_RUN"
    required_outputs_present = all(row["exists_flag"] == "TRUE" for row in artifacts)
    required_outputs_non_empty = all(row["non_empty_flag"] == "TRUE" for row in artifacts)
    expected_counts_validated = all(row["validation_status"] == "PASS" for row in counts)
    safety_boundaries_validated = all(row["validation_status"] == "PASS" for row in safety)
    alias_ok = current_alias_valid()
    read_first_ok = read_first_valid()

    blocker_reasons = []
    if not upstream_production_passed:
        blocker_reasons.append("upstream_production_not_passed")
    if not test_passed:
        blocker_reasons.append("upstream_formal_tests_not_passed")
    for row in artifacts + counts + safety:
        if row["validation_status"] != "PASS":
            blocker_reasons.append(clean(row.get("blocker_reason")) or clean(row.get("artifact_name")) or clean(row.get("metric_name")) or clean(row.get("safety_check")))
    if not alias_ok:
        blocker_reasons.append("current_alias_not_valid")
    if not read_first_ok:
        blocker_reasons.append("read_first_not_valid")

    blocker_count = len([reason for reason in blocker_reasons if reason])
    accepted = blocker_count == 0
    acceptance_status = ACCEPTED_STATUS if accepted else BLOCKED_ACCEPTANCE_STATUS
    final_status = PASS_STATUS if accepted else BLOCKED_STATUS

    summary = [{
        "stage": STAGE,
        "upstream_stage": UPSTREAM_STAGE,
        "upstream_production_passed": tf(upstream_production_passed),
        "upstream_formal_tests_passed": tf(test_passed),
        "required_outputs_present": tf(required_outputs_present),
        "required_outputs_non_empty": tf(required_outputs_non_empty),
        "expected_counts_validated": tf(expected_counts_validated),
        "safety_boundaries_validated": tf(safety_boundaries_validated),
        "current_alias_validated": tf(alias_ok),
        "read_first_validated": tf(read_first_ok),
        "blocker_count": blocker_count,
        "acceptance_status": acceptance_status,
        "ready_for_current_run_report": tf(accepted),
        "ready_for_official_trading": "FALSE",
        "ready_for_official_recommendation": "FALSE",
        "ready_for_dynamic_weighting_mutation": "FALSE",
        "next_recommended_stage": NEXT_STAGE if accepted else "REPAIR_V20_43_DRY_RUN_OR_FORMAL_TESTS",
    }]

    decision = [{
        "stage": STAGE,
        "current_run_report_ready": tf(accepted),
        "current_run_report_scope": "research_only_current_operator_report",
        "allowed_actions": "render_current_operator_research_report_from_approved_inputs",
        "blocked_actions": "official_trading;official_recommendations;broker_orders;official_ranking_mutation;dynamic_weighting_mutation;real_portfolio_mutation",
        "required_next_inputs": "current market snapshot and PIT-safe approved V20 research inputs",
        "current_market_refresh_required_next": "CONDITIONAL",
        "provider_refresh_allowed_in_this_stage": "FALSE",
        "official_recommendation_allowed": "FALSE",
        "official_trading_allowed": "FALSE",
        "blocker_count": blocker_count,
        "next_recommended_stage": NEXT_STAGE if accepted else "REPAIR_V20_43_DRY_RUN_OR_FORMAL_TESTS",
    }]

    write_csv(OUT_ARTIFACTS, artifacts, [
        "artifact_name", "artifact_path", "artifact_type", "required_flag", "exists_flag",
        "non_empty_flag", "validation_status", "blocker_reason",
    ])
    write_csv(OUT_COUNTS, counts, ["metric_name", "expected_value", "actual_value", "validation_status", "blocker_reason"])
    write_csv(OUT_SAFETY, safety, ["safety_check", "expected_value", "actual_value", "validation_status", "evidence", "blocker_reason"])
    write_csv(OUT_SUMMARY, summary, list(summary[0].keys()))
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))

    count_lines = "\n".join(
        f"- {row['metric_name']}: expected {row['expected_value']}, actual {row['actual_value']} ({row['validation_status']})"
        for row in counts
    )
    safety_lines = "\n".join(
        f"- {row['safety_check']}: expected {row['expected_value']}, actual {row['actual_value']} ({row['validation_status']})"
        for row in safety
    )
    blocker_text = "None" if accepted else "; ".join(blocker_reasons)
    report = f"""# V20.44 Daily Operator Report Acceptance Gate

Stage: {STAGE}
Upstream stage: {UPSTREAM_STAGE}
Final status: {final_status}
Acceptance status: {acceptance_status}

## Gate Result

V20.43 production dry-run accepted: {tf(upstream_production_passed)}
V20.43 formal tests passed: {tf(test_passed)}
Required artifacts present and non-empty: {tf(required_outputs_present and required_outputs_non_empty)}
Core counts validated: {tf(expected_counts_validated)}
Safety boundaries validated: {tf(safety_boundaries_validated)}
Current alias validated: {tf(alias_ok)}
READ_FIRST validated: {tf(read_first_ok)}

## Count Recheck

{count_lines}

## Safety Recheck

{safety_lines}

## Reporting-Only Boundary

V20.44 is a gate/reporting-only stage. It performs no trading, no official recommendations, no official ranking mutation, no broker/order execution, no provider/network refresh, no dynamic weighting mutation, and no real portfolio mutation.

## Current-Run Readiness Decision

Current-run report ready: {tf(accepted)}
Current-run report scope: research_only_current_operator_report
Provider refresh allowed in this stage: FALSE
Official recommendation allowed: FALSE
Official trading allowed: FALSE

## Next Recommended Stage

{NEXT_STAGE if accepted else "REPAIR_V20_43_DRY_RUN_OR_FORMAL_TESTS"}

## Blockers

{blocker_text}

## V20.43 Formal Test Output

```text
{test_output}
```
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)

    read_first = "\n".join([
        f"STAGE_NAME={STAGE}",
        f"STATUS={final_status}",
        f"ACCEPTANCE_STATUS={acceptance_status}",
        f"UPSTREAM_STAGE={UPSTREAM_STAGE}",
        f"UPSTREAM_ACCEPTED={tf(upstream_production_passed and test_passed)}",
        f"CURRENT_RUN_REPORT_READY={tf(accepted)}",
        "REPORTING_OR_GATE_ONLY=TRUE",
        "DRY_RUN_ONLY=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE",
        "OFFICIAL_TRADING_ALLOWED=FALSE",
        "READY_FOR_OFFICIAL_TRADING=FALSE",
        "READY_FOR_OFFICIAL_RECOMMENDATION=FALSE",
        "TRADING_SIGNAL_CREATED=FALSE",
        "BROKER_ORDER_PATH_CREATED=FALSE",
        "BROKER_ORDER_EXECUTION_PATH=FALSE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE",
        "DYNAMIC_WEIGHTING_EXECUTED=FALSE",
        "REAL_PORTFOLIO_MUTATED=FALSE",
        "PROVIDER_REFRESH_EXECUTED=FALSE",
        "NETWORK_REFRESH_EXECUTED=FALSE",
        "V21_OUTPUTS_CREATED=FALSE",
        "V19_21_OUTPUTS_CREATED=FALSE",
        f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if accepted else 'REPAIR_V20_43_DRY_RUN_OR_FORMAL_TESTS'}",
        "",
    ])
    write_text(READ_FIRST, read_first)

    print(final_status)
    print(f"ACCEPTANCE_STATUS={acceptance_status}")
    print(f"CURRENT_RUN_REPORT_READY={tf(accepted)}")
    print(f"NEXT_RECOMMENDED_STAGE={NEXT_STAGE if accepted else 'REPAIR_V20_43_DRY_RUN_OR_FORMAL_TESTS'}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
