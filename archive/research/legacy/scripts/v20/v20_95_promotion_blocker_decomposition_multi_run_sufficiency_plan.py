#!/usr/bin/env python
"""V20.95 promotion blocker decomposition and multi-run sufficiency plan.

Research-only decomposition layer. It converts the V20.94 preflight blockers
into measurable next-action requirements without enabling promotion,
recommendations, weight mutation, or trade actions.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

PASS_STATUS = "PASS_V20_95_PROMOTION_BLOCKERS_DECOMPOSED_RESEARCH_ONLY"
WARN_STATUS = "WARN_V20_95_PROMOTION_BLOCKERS_DECOMPOSED_WITH_MISSING_OPTIONAL_INPUTS"
BLOCKED_STATUS = "BLOCKED_V20_95_EVIDENCE_CHAIN_NOT_CLOSED"

V20_94_DETAIL = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_DETAIL.csv"
V20_94_SUMMARY = EVIDENCE / "V20_CURRENT_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_SUMMARY.md"

DETAIL = EVIDENCE / "V20_95_PROMOTION_BLOCKER_DECOMPOSITION_DETAIL.csv"
SUMMARY = EVIDENCE / "V20_95_PROMOTION_BLOCKER_DECOMPOSITION_SUMMARY.md"
DETAIL_ALIAS = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_DETAIL.csv"
SUMMARY_ALIAS = EVIDENCE / "V20_CURRENT_PROMOTION_BLOCKER_DECOMPOSITION_SUMMARY.md"

REQUIRED_RUN_COUNT = 5
REQUIRED_OBSERVATION_ROWS = 50
REQUIRED_ROLLING_LEDGER_ROWS = 20

INPUT_CANDIDATES = {
    "multi_run_history_sufficiency": [
        CONSOLIDATION / "V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv",
        EVIDENCE / "V20_CURRENT_MULTI_RUN_EVIDENCE_ACCUMULATION_SUMMARY.csv",
        CONSOLIDATION / "V20_58_STABILITY_MULTI_RUN_GATE.csv",
        EVIDENCE / "V20_CURRENT_STABILITY_MULTI_RUN_GATE.csv",
    ],
    "rolling_evidence_ledger_sufficiency": [
        CONSOLIDATION / "V20_64_ROLLING_EVIDENCE_LEDGER.csv",
        CONSOLIDATION / "V20_58_ROLLING_EVIDENCE_LEDGER.csv",
        EVIDENCE / "V20_CURRENT_ROLLING_EVIDENCE_LEDGER.csv",
    ],
    "shadow_feedback_stability": [
        CONSOLIDATION / "V20_63_OBSERVATION_INTEGRATION_TABLE.csv",
        CONSOLIDATION / "V20_64_SHADOW_FEEDBACK_STABILITY_TABLE.csv",
        EVIDENCE / "V20_CURRENT_SHADOW_FEEDBACK_STABILITY_TABLE.csv",
    ],
    "candidate_dynamic_weight_promotion_readiness": [
        CONSOLIDATION / "V20_66_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv",
        EVIDENCE / "V20_CURRENT_CANDIDATE_WEIGHT_UPDATE_DRY_RUN.csv",
    ],
    "official_recommendation_readiness": [
        CONSOLIDATION / "V20_51_OFFICIAL_RECOMMENDATION_READINESS.csv",
        EVIDENCE / "V20_CURRENT_OFFICIAL_RECOMMENDATION_READINESS.csv",
    ],
    "promotion_readiness": [
        CONSOLIDATION / "V20_65_PROPOSAL_PROMOTION_READINESS_GATE.csv",
        EVIDENCE / "V20_CURRENT_PROPOSAL_PROMOTION_READINESS_GATE.csv",
    ],
    "daily_runner_health": [
        READ_CENTER / "V20_55_DAILY_ONE_CLICK_RUNNER_REPORT.md",
        CONSOLIDATION / "V20_63_DAILY_RUNNER_HEALTH_TABLE.csv",
        EVIDENCE / "V20_CURRENT_DAILY_RUNNER_HEALTH_TABLE.csv",
    ],
}

BLOCKER_CATEGORIES = [
    "research_only_guard",
    "multi_run_history_sufficiency",
    "rolling_evidence_ledger_sufficiency",
    "shadow_feedback_stability",
    "candidate_dynamic_weight_promotion_readiness",
    "official_recommendation_readiness",
    "nasdaq_benchmark_hurdle",
    "operator_acceptance_requirement",
    "safety_state",
]

DETAIL_FIELDS = [
    "blocker_category",
    "blocker_status",
    "current_state",
    "required_state",
    "evidence_source_file",
    "evidence_source_status",
    "missing_requirement",
    "recommended_next_stage",
    "promotion_blocking",
    "discovered_run_count",
    "required_run_count",
    "remaining_run_count",
    "observation_rows_available",
    "observation_rows_required",
    "rolling_ledger_rows_available",
    "rolling_ledger_rows_required",
    "sufficiency_met",
    "candidate_dynamic_weight_rows",
    "promoted_dynamic_weight_rows",
    "blocked_dynamic_weight_rows",
    "dynamic_weight_promotion_ready",
    "official_recommendation_ready",
    "official_recommendation_created",
    "readiness_blockers",
    "official_recommendation_gate_attemptable",
    "nasdaq_hurdle_passed",
    "research_only",
    "promotion_allowed",
    "official_weight_mutated",
    "trade_action_created",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "MISSING_FILE"
    if path.stat().st_size == 0:
        return [], [], "EMPTY_FILE"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    except csv.Error:
        return [], [], "MALFORMED_CSV"
    return rows, fields, "OK" if fields else "MALFORMED_CSV"


def first_csv(paths: list[Path]) -> tuple[Path | None, list[dict[str, str]], list[str], str]:
    for path in paths:
        rows, fields, status = read_csv(path)
        if status == "OK":
            return path, rows, fields, status
    return None, [], [], "MISSING_OPTIONAL_INPUT"


def int_value(value: object) -> int:
    try:
        return int(float(clean(value) or "0"))
    except ValueError:
        return 0


def boolish(value: object) -> bool:
    return clean(value).upper() in {"TRUE", "YES", "Y", "1", "PASS", "PASSED", "READY"}


def safety_base() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "nasdaq_hurdle_passed": "FALSE",
    }


def empty_metrics() -> dict[str, str]:
    return {
        "discovered_run_count": "0",
        "required_run_count": str(REQUIRED_RUN_COUNT),
        "remaining_run_count": str(REQUIRED_RUN_COUNT),
        "observation_rows_available": "0",
        "observation_rows_required": str(REQUIRED_OBSERVATION_ROWS),
        "rolling_ledger_rows_available": "0",
        "rolling_ledger_rows_required": str(REQUIRED_ROLLING_LEDGER_ROWS),
        "sufficiency_met": "FALSE",
        "candidate_dynamic_weight_rows": "0",
        "promoted_dynamic_weight_rows": "0",
        "blocked_dynamic_weight_rows": "0",
        "dynamic_weight_promotion_ready": "FALSE",
        "official_recommendation_ready": "FALSE",
        "readiness_blockers": "NA",
        "official_recommendation_gate_attemptable": "FALSE",
    }


def row(blocker_category: str, status: str, current_state: str, required_state: str, source: str, source_status: str, missing: str, next_stage: str, promotion_blocking: bool, metrics: dict[str, str] | None = None) -> dict[str, str]:
    out = {
        "blocker_category": blocker_category,
        "blocker_status": status,
        "current_state": current_state,
        "required_state": required_state,
        "evidence_source_file": source,
        "evidence_source_status": source_status,
        "missing_requirement": missing,
        "recommended_next_stage": next_stage,
        "promotion_blocking": tf(promotion_blocking),
    }
    out.update(empty_metrics())
    if metrics:
        out.update({key: clean(value) for key, value in metrics.items()})
    out.update(safety_base())
    return out


def v20_94_state(detail_path: Path = V20_94_DETAIL, summary_path: Path = V20_94_SUMMARY) -> tuple[bool, bool, dict[str, str], str]:
    rows, _, status = read_csv(detail_path)
    summary_ok = summary_path.exists() and summary_path.stat().st_size > 0
    if status != "OK" or not rows or not summary_ok:
        return False, False, {}, status if status != "OK" else "MISSING_SUMMARY"
    first = rows[0]
    closed = clean(first.get("evidence_chain_closure_status")) == "PASS_EVIDENCE_CHAIN_CLOSED_WITH_OPTIONAL_WARN"
    blocked = clean(first.get("promotion_preflight_status")) == "PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED"
    safe = all(clean(first.get(field)) == "FALSE" for field in ["promotion_allowed", "official_recommendation_created", "official_weight_mutated", "trade_action_created"])
    return closed and safe, blocked and safe, first, "OK"


def multi_run_metrics() -> tuple[dict[str, str], str, str]:
    source, rows, _fields, status = first_csv(INPUT_CANDIDATES["multi_run_history_sufficiency"])
    ledger_source, ledger_rows, _ledger_fields, ledger_status = first_csv(INPUT_CANDIDATES["rolling_evidence_ledger_sufficiency"])
    obs_source, obs_rows, _obs_fields, obs_status = first_csv(INPUT_CANDIDATES["shadow_feedback_stability"])
    discovered = 0
    if rows:
        discovered = max([int_value(row.get("effective_source_run_count") or row.get("run_count") or row.get("source_run_count")) for row in rows] + [len(rows)])
    observation_rows = len(obs_rows) if obs_status == "OK" else 0
    ledger_count = len(ledger_rows) if ledger_status == "OK" else 0
    remaining = max(0, REQUIRED_RUN_COUNT - discovered)
    sufficiency = discovered >= REQUIRED_RUN_COUNT and observation_rows >= REQUIRED_OBSERVATION_ROWS and ledger_count >= REQUIRED_ROLLING_LEDGER_ROWS
    metrics = {
        "discovered_run_count": str(discovered),
        "required_run_count": str(REQUIRED_RUN_COUNT),
        "remaining_run_count": str(remaining),
        "observation_rows_available": str(observation_rows),
        "observation_rows_required": str(REQUIRED_OBSERVATION_ROWS),
        "rolling_ledger_rows_available": str(ledger_count),
        "rolling_ledger_rows_required": str(REQUIRED_ROLLING_LEDGER_ROWS),
        "sufficiency_met": tf(sufficiency),
    }
    source_name = rel(source) if source else "NA"
    combined_status = "OK" if status == "OK" else "MISSING_OPTIONAL_INPUT"
    if ledger_status != "OK" or obs_status != "OK":
        combined_status = "MISSING_OPTIONAL_INPUT"
    return metrics, source_name, combined_status


def dynamic_weight_metrics() -> tuple[dict[str, str], str, str]:
    source, rows, _fields, status = first_csv(INPUT_CANDIDATES["candidate_dynamic_weight_promotion_readiness"])
    promoted = 0
    blocked = 0
    for item in rows:
        tokens = {clean(value).upper() for value in item.values() if clean(value)}
        text = " ".join(tokens)
        positive = tokens & {"PROMOTED", "READY", "PROMOTION_READY", "DYNAMIC_WEIGHT_PROMOTED"}
        negative = (
            tokens & {"BLOCKED", "NOT_READY", "DRY_RUN", "NOT_PROMOTED", "PROMOTION_BLOCKED"}
            or any(token.startswith("BLOCKED_") for token in tokens)
        )
        if positive and not negative:
            promoted += 1
        if negative or "BLOCK" in text:
            blocked += 1
    ready = bool(rows) and promoted > 0 and blocked == 0
    metrics = {
        "candidate_dynamic_weight_rows": str(len(rows)),
        "promoted_dynamic_weight_rows": str(promoted),
        "blocked_dynamic_weight_rows": str(blocked if rows else 0),
        "dynamic_weight_promotion_ready": tf(ready),
    }
    return metrics, rel(source) if source else "NA", status


def official_recommendation_metrics() -> tuple[dict[str, str], str, str]:
    source, rows, _fields, status = first_csv(INPUT_CANDIDATES["official_recommendation_readiness"])
    ready = any(boolish(row.get("official_recommendation_ready") or row.get("ready") or row.get("readiness_status")) for row in rows)
    created = any(boolish(row.get("official_recommendation_created")) for row in rows)
    blockers = []
    for item in rows:
        for key in ["readiness_blockers", "blocking_reason", "blocker_reason"]:
            if clean(item.get(key)):
                blockers.append(clean(item.get(key)))
    if not rows:
        blockers.append("V20_51_OFFICIAL_RECOMMENDATION_READINESS_MISSING")
    if created:
        blockers.append("UNEXPECTED_OFFICIAL_RECOMMENDATION_CREATED")
    metrics = {
        "official_recommendation_ready": tf(ready),
        "official_recommendation_created": "FALSE",
        "readiness_blockers": "|".join(dict.fromkeys(blockers)) if blockers else "NA",
        "official_recommendation_gate_attemptable": tf(ready and not created),
    }
    return metrics, rel(source) if source else "NA", status


def nasdaq_hurdle_from_v20_94(first: dict[str, str]) -> bool:
    return clean(first.get("nasdaq_hurdle_passed")).upper() == "TRUE"


def build_rows(detail_path: Path = V20_94_DETAIL, summary_path: Path = V20_94_SUMMARY) -> tuple[list[dict[str, str]], str]:
    chain_closed, promotion_blocked, v20_94, v20_94_status = v20_94_state(detail_path, summary_path)
    if not chain_closed:
        rows = [
            row(
                "research_only_guard",
                "BLOCK",
                f"V20_94_STATUS={v20_94_status}",
                "V20_94_EVIDENCE_CHAIN_CLOSED",
                rel(detail_path),
                v20_94_status,
                "V20_94_EVIDENCE_CHAIN_NOT_CLOSED",
                "RERUN_V20_93_V20_82_R5_V20_84_R2_AND_V20_94",
                True,
            )
        ]
        return rows, BLOCKED_STATUS

    rows: list[dict[str, str]] = []
    rows.append(row("research_only_guard", "BLOCK", "RESEARCH_ONLY", "PROMOTION_GATE_APPROVED_SEPARATELY", rel(detail_path), "OK", "RESEARCH_ONLY_GUARD_REMAINS_ACTIVE", "V20_96_OPERATOR_REVIEW_PACKET", True))

    multi_metrics, multi_source, multi_status = multi_run_metrics()
    multi_missing = "NA" if multi_metrics["sufficiency_met"] == "TRUE" else "INSUFFICIENT_MULTI_RUN_HISTORY_OR_OBSERVATION_LEDGER"
    rows.append(row("multi_run_history_sufficiency", "PASS" if multi_metrics["sufficiency_met"] == "TRUE" else ("WARN" if multi_status == "MISSING_OPTIONAL_INPUT" else "BLOCK"), f"runs={multi_metrics['discovered_run_count']};observations={multi_metrics['observation_rows_available']};ledger={multi_metrics['rolling_ledger_rows_available']}", f"runs>={REQUIRED_RUN_COUNT};observations>={REQUIRED_OBSERVATION_ROWS};ledger>={REQUIRED_ROLLING_LEDGER_ROWS}", multi_source, multi_status, multi_missing, "V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION", True, multi_metrics))

    ledger_ready = int_value(multi_metrics["rolling_ledger_rows_available"]) >= int_value(multi_metrics["rolling_ledger_rows_required"])
    rows.append(row("rolling_evidence_ledger_sufficiency", "PASS" if ledger_ready else "WARN", f"ledger_rows={multi_metrics['rolling_ledger_rows_available']}", f"ledger_rows>={REQUIRED_ROLLING_LEDGER_ROWS}", multi_source, multi_status, "NA" if ledger_ready else "ROLLING_EVIDENCE_LEDGER_INSUFFICIENT", "V20_64_ROLLING_LEDGER_ACCUMULATION", True, multi_metrics))

    rows.append(row("shadow_feedback_stability", "PASS" if int_value(multi_metrics["observation_rows_available"]) >= REQUIRED_OBSERVATION_ROWS else "WARN", f"observation_rows={multi_metrics['observation_rows_available']}", f"observation_rows>={REQUIRED_OBSERVATION_ROWS}", multi_source, multi_status, "SHADOW_FEEDBACK_STABILITY_NOT_PROVEN" if int_value(multi_metrics["observation_rows_available"]) < REQUIRED_OBSERVATION_ROWS else "NA", "V20_63_OBSERVATION_INTEGRATION", True, multi_metrics))

    dyn_metrics, dyn_source, dyn_status = dynamic_weight_metrics()
    rows.append(row("candidate_dynamic_weight_promotion_readiness", "PASS" if dyn_metrics["dynamic_weight_promotion_ready"] == "TRUE" else ("WARN" if dyn_status == "MISSING_OPTIONAL_INPUT" else "BLOCK"), f"promoted={dyn_metrics['promoted_dynamic_weight_rows']};blocked={dyn_metrics['blocked_dynamic_weight_rows']}", "promoted_dynamic_weight_rows>0;blocked_dynamic_weight_rows=0", dyn_source, dyn_status, "DYNAMIC_WEIGHT_NOT_PROMOTED" if dyn_metrics["dynamic_weight_promotion_ready"] != "TRUE" else "NA", "V20_66_CANDIDATE_DYNAMIC_WEIGHT_PROMOTION_GATE", True, dyn_metrics))

    rec_metrics, rec_source, rec_status = official_recommendation_metrics()
    rows.append(row("official_recommendation_readiness", "PASS" if rec_metrics["official_recommendation_gate_attemptable"] == "TRUE" else ("WARN" if rec_status == "MISSING_OPTIONAL_INPUT" else "BLOCK"), f"ready={rec_metrics['official_recommendation_ready']};created=FALSE", "official_recommendation_ready=TRUE;official_recommendation_created=FALSE", rec_source, rec_status, rec_metrics["readiness_blockers"], "V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE", True, rec_metrics))

    nasdaq_passed = nasdaq_hurdle_from_v20_94(v20_94)
    nasdaq_metrics = {"nasdaq_hurdle_passed": tf(nasdaq_passed)}
    rows.append(row("nasdaq_benchmark_hurdle", "PASS" if nasdaq_passed else "BLOCK", f"nasdaq_hurdle_passed={tf(nasdaq_passed)}", "nasdaq_hurdle_passed=TRUE_FROM_VALID_UPSTREAM", rel(detail_path), "OK", "NASDAQ_BENCHMARK_HURDLE_FALSE" if not nasdaq_passed else "NA", "FUTURE_CERTIFIED_BENCHMARK_HURDLE_GATE", True, nasdaq_metrics))

    rows.append(row("operator_acceptance_requirement", "BLOCK", "PENDING_OPERATOR_ACCEPTANCE", "EXPLICIT_OPERATOR_ACCEPTANCE_FOR_PROMOTION", rel(summary_path), "OK", "OPERATOR_ACCEPTANCE_REQUIRED", "V20_96_OPERATOR_REVIEW_PACKET", True))
    rows.append(row("safety_state", "PASS", "NO_OFFICIAL_OR_TRADE_MUTATION", "ALL_SAFETY_FLAGS_FALSE", rel(detail_path), "OK", "NA", "CONTINUE_RESEARCH_ONLY", False))

    final_status = WARN_STATUS if any(item["evidence_source_status"] == "MISSING_OPTIONAL_INPUT" for item in rows) else PASS_STATUS
    if not promotion_blocked:
        final_status = BLOCKED_STATUS
    return rows, final_status


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, str]], status: str) -> None:
    counts = {state: sum(row["blocker_status"] == state for row in rows) for state in ["PASS", "WARN", "BLOCK"]}
    multi = next((row for row in rows if row["blocker_category"] == "multi_run_history_sufficiency"), {})
    dyn = next((row for row in rows if row["blocker_category"] == "candidate_dynamic_weight_promotion_readiness"), {})
    rec = next((row for row in rows if row["blocker_category"] == "official_recommendation_readiness"), {})
    nasdaq = next((row for row in rows if row["blocker_category"] == "nasdaq_benchmark_hurdle"), {})
    lines = [
        "# V20.95 Promotion Blocker Decomposition and Multi-Run Sufficiency Plan",
        "",
        "## V20.94 Inherited Status",
        f"- final_status: {status}",
        "- evidence_chain_closure_status: PASS_EVIDENCE_CHAIN_CLOSED_WITH_OPTIONAL_WARN",
        "- promotion_preflight_status: PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED",
        "",
        "## Blocker Decomposition Table",
        "| blocker_category | blocker_status | missing_requirement | recommended_next_stage |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(f"| {row['blocker_category']} | {row['blocker_status']} | {row['missing_requirement']} | {row['recommended_next_stage']} |" for row in rows)
    lines.extend(
        [
            "",
            "## Multi-Run Sufficiency Gap",
            f"- discovered_run_count: {multi.get('discovered_run_count', '0')}",
            f"- required_run_count: {multi.get('required_run_count', str(REQUIRED_RUN_COUNT))}",
            f"- remaining_run_count: {multi.get('remaining_run_count', str(REQUIRED_RUN_COUNT))}",
            f"- observation_rows_available: {multi.get('observation_rows_available', '0')}",
            f"- rolling_ledger_rows_available: {multi.get('rolling_ledger_rows_available', '0')}",
            f"- sufficiency_met: {multi.get('sufficiency_met', 'FALSE')}",
            "",
            "## Dynamic Weight Readiness Gap",
            f"- candidate_dynamic_weight_rows: {dyn.get('candidate_dynamic_weight_rows', '0')}",
            f"- promoted_dynamic_weight_rows: {dyn.get('promoted_dynamic_weight_rows', '0')}",
            f"- blocked_dynamic_weight_rows: {dyn.get('blocked_dynamic_weight_rows', '0')}",
            f"- dynamic_weight_promotion_ready: {dyn.get('dynamic_weight_promotion_ready', 'FALSE')}",
            "",
            "## Official Recommendation Readiness Gap",
            f"- official_recommendation_ready: {rec.get('official_recommendation_ready', 'FALSE')}",
            f"- official_recommendation_created: FALSE",
            f"- readiness_blockers: {rec.get('readiness_blockers', 'NA')}",
            f"- official_recommendation_gate_attemptable: {rec.get('official_recommendation_gate_attemptable', 'FALSE')}",
            "",
            "## Benchmark Hurdle State",
            f"- nasdaq_hurdle_passed: {nasdaq.get('nasdaq_hurdle_passed', 'FALSE')}",
            "",
            "## Operator Acceptance Requirement",
            "- explicit_operator_acceptance_required: TRUE",
            "",
            "## Safety Confirmation",
            "- research_only: TRUE",
            "- promotion_allowed: FALSE",
            "- official_recommendation_created: FALSE",
            "- official_weight_mutated: FALSE",
            "- trade_action_created: FALSE",
            "",
            "## Recommended Next Stages",
            "- V20_64_MULTI_RUN_EVIDENCE_ACCUMULATION",
            "- V20_66_CANDIDATE_DYNAMIC_WEIGHT_PROMOTION_GATE",
            "- V20_51_OFFICIAL_RECOMMENDATION_READINESS_GATE",
            "- FUTURE_CERTIFIED_BENCHMARK_HURDLE_GATE",
            "- V20_96_OPERATOR_REVIEW_PACKET",
            "",
            "## Blocker Counts",
            f"- pass_count: {counts['PASS']}",
            f"- warn_count: {counts['WARN']}",
            f"- block_count: {counts['BLOCK']}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows, status = build_rows()
    write_csv(DETAIL, rows)
    write_summary(SUMMARY, rows, status)
    shutil.copyfile(DETAIL, DETAIL_ALIAS)
    shutil.copyfile(SUMMARY, SUMMARY_ALIAS)
    counts = {state: sum(row["blocker_status"] == state for row in rows) for state in ["PASS", "WARN", "BLOCK"]}
    multi = next((row for row in rows if row["blocker_category"] == "multi_run_history_sufficiency"), {})
    dyn = next((row for row in rows if row["blocker_category"] == "candidate_dynamic_weight_promotion_readiness"), {})
    rec = next((row for row in rows if row["blocker_category"] == "official_recommendation_readiness"), {})
    print(status)
    print(f"PASS_COUNT={counts['PASS']}")
    print(f"WARN_COUNT={counts['WARN']}")
    print(f"BLOCK_COUNT={counts['BLOCK']}")
    print(f"DISCOVERED_RUN_COUNT={multi.get('discovered_run_count', '0')}")
    print(f"REQUIRED_RUN_COUNT={multi.get('required_run_count', str(REQUIRED_RUN_COUNT))}")
    print(f"REMAINING_RUN_COUNT={multi.get('remaining_run_count', str(REQUIRED_RUN_COUNT))}")
    print(f"PROMOTED_DYNAMIC_WEIGHT_ROWS={dyn.get('promoted_dynamic_weight_rows', '0')}")
    print(f"OFFICIAL_RECOMMENDATION_READY={rec.get('official_recommendation_ready', 'FALSE')}")
    print("RESEARCH_ONLY=TRUE")
    print("PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    return 1 if status == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
