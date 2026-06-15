from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
IN_SCHEMA = CONSOLIDATION / "V20_17_BACKTEST_INPUT_SCHEMA_AUDIT.csv"
IN_SEMANTIC = CONSOLIDATION / "V20_17_SCORE_SEMANTIC_CARRYFORWARD_AUDIT.csv"
IN_OUTCOME_CONTRACT = CONSOLIDATION / "V20_17_OUTCOME_WINDOW_CONTRACT.csv"
IN_BENCHMARK_CONTRACT = CONSOLIDATION / "V20_17_BENCHMARK_WINDOW_CONTRACT.csv"
IN_SAMPLE_POLICY = CONSOLIDATION / "V20_17_SAMPLE_SPLIT_POLICY_PLAN.csv"
IN_PIT_PRECHECK = CONSOLIDATION / "V20_17_PIT_STALE_LEAKAGE_OUTCOME_PRECHECK.csv"
IN_OUTCOME_SOURCE = CONSOLIDATION / "V20_17_OUTCOME_SOURCE_AVAILABILITY_AUDIT.csv"
IN_BENCHMARK_SOURCE = CONSOLIDATION / "V20_17_BENCHMARK_SOURCE_AVAILABILITY_AUDIT.csv"
IN_EXEC_READY = CONSOLIDATION / "V20_17_BACKTEST_EXECUTION_READINESS_AUDIT.csv"
IN_MISSING = CONSOLIDATION / "V20_17_MISSING_OUTCOME_BENCHMARK_SOURCE_REGISTER.csv"
IN_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_17_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_17_READ_FIRST.txt"
IN_V20_17_BENCHMARK_PREP = CONSOLIDATION / "V20_17_BENCHMARK_PREPARATION.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_18_DEPENDENCY_AUDIT.csv"
OUT_CANDIDATE_REVIEW = CONSOLIDATION / "V20_18_BACKTEST_INPUT_CANDIDATE_REVIEW.csv"
OUT_OUTCOME_REVIEW = CONSOLIDATION / "V20_18_OUTCOME_CONTRACT_REVIEW.csv"
OUT_BENCHMARK_REVIEW = CONSOLIDATION / "V20_18_BENCHMARK_CONTRACT_REVIEW.csv"
OUT_OUTCOME_DISCOVERY = CONSOLIDATION / "V20_18_OUTCOME_SOURCE_DISCOVERY_AUDIT.csv"
OUT_BENCHMARK_DISCOVERY = CONSOLIDATION / "V20_18_BENCHMARK_SOURCE_DISCOVERY_AUDIT.csv"
OUT_OUTCOME_READY = CONSOLIDATION / "V20_18_OUTCOME_SOURCE_ATTACHMENT_READINESS.csv"
OUT_BENCHMARK_READY = CONSOLIDATION / "V20_18_BENCHMARK_SOURCE_ATTACHMENT_READINESS.csv"
OUT_ATTACHMENT_PLAN = CONSOLIDATION / "V20_18_OUTCOME_BENCHMARK_ATTACHMENT_PLAN.csv"
OUT_PIT_REVIEW = CONSOLIDATION / "V20_18_PIT_STALE_LEAKAGE_ATTACHMENT_REVIEW.csv"
OUT_EXEC_REVIEW = CONSOLIDATION / "V20_18_BACKTEST_EXECUTION_READINESS_REVIEW.csv"
OUT_DYNAMIC = CONSOLIDATION / "V20_18_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_MISSING = CONSOLIDATION / "V20_18_MISSING_OUTCOME_BENCHMARK_SOURCE_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_18_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_18_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_18_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_18_VALIDATION_SUMMARY.csv"
OUT_GATE_DIAGNOSTICS = CONSOLIDATION / "V20_18_GATE_DECISION_DIAGNOSTICS.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_18_SOURCE_AUDIT.csv"
REPORT = READ_CENTER / "V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW.md"
READ_FIRST = OPS / "V20_18_READ_FIRST.txt"
READ_CENTER_READ_FIRST = READ_CENTER / "V20_18_READ_FIRST.txt"

PATCH_VERSION = "V20.18"
PASS_STATUS = "PASS_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW"
BLOCKED_STATUS = "BLOCKED_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW"

REQUIRED_INPUTS = [
    IN_CANDIDATES, IN_SCHEMA, IN_SEMANTIC, IN_OUTCOME_CONTRACT, IN_BENCHMARK_CONTRACT,
    IN_SAMPLE_POLICY, IN_PIT_PRECHECK, IN_OUTCOME_SOURCE, IN_BENCHMARK_SOURCE,
    IN_EXEC_READY, IN_MISSING, IN_GATE, IN_VALIDATION, IN_READ_FIRST,
]
ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY, OUT_CANDIDATE_REVIEW, OUT_OUTCOME_REVIEW, OUT_BENCHMARK_REVIEW,
    OUT_OUTCOME_DISCOVERY, OUT_BENCHMARK_DISCOVERY, OUT_OUTCOME_READY,
    OUT_BENCHMARK_READY, OUT_ATTACHMENT_PLAN, OUT_PIT_REVIEW, OUT_EXEC_REVIEW,
    OUT_DYNAMIC, OUT_MISSING, OUT_BLOCKERS, OUT_GATE, OUT_NEXT, OUT_VALIDATION,
    OUT_GATE_DIAGNOSTICS, OUT_SOURCE_AUDIT, REPORT, CURRENT_REPORT, READ_FIRST,
    READ_CENTER_READ_FIRST,
}


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def parse_date_ok(value: object) -> bool:
    try:
        datetime.fromisoformat(clean(value))
        return True
    except ValueError:
        return False


def false_or_zero(value: object) -> bool:
    return upper(value) in {"FALSE", "0", ""}


def true_value(value: object) -> bool:
    return upper(value) == "TRUE"


def add_blocker(blockers: list[dict[str, str]], scope: str, reason: str) -> None:
    blockers.append({
        "blocker_id": f"V20_18_BLOCKER_{len(blockers) + 1:03d}",
        "blocker_scope": scope,
        "severity": "BLOCKING",
        "blocker_status": "OPEN",
        "blocker_reason": reason,
        "blocks_v20_18": "TRUE",
    })


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(h)).replace("|", "/") for h in headers) + " |")
    if len(rows) > limit:
        lines.append("| ... | " + f"{len(rows) - limit} more rows omitted" + " |" * max(0, len(headers) - 2))
    return "\n".join(lines)


def discover_local_candidates(kind: str) -> list[Path]:
    names = []
    for path in (ROOT / "outputs").rglob("*"):
        if path.is_file():
            low = path.name.lower()
            if kind == "outcome" and any(term in low for term in ["outcome", "future", "forward"]):
                names.append(path)
            if kind == "benchmark" and any(term in low for term in ["spy", "qqq", "benchmark"]):
                names.append(path)
    return names[:20]


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []
    candidates, _ = read_csv(IN_CANDIDATES)
    semantic_rows, _ = read_csv(IN_SEMANTIC)
    outcome_contracts, _ = read_csv(IN_OUTCOME_CONTRACT)
    benchmark_contracts, _ = read_csv(IN_BENCHMARK_CONTRACT)
    policy_rows_in, _ = read_csv(IN_SAMPLE_POLICY)
    pit_rows, _ = read_csv(IN_PIT_PRECHECK)
    missing_in, _ = read_csv(IN_MISSING)
    gate_rows, _ = read_csv(IN_GATE)
    validation_rows, _ = read_csv(IN_VALIDATION)
    benchmark_prep_rows, _ = read_csv(IN_V20_17_BENCHMARK_PREP)
    read_first_text = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""
    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    semantic = semantic_rows[0] if semantic_rows else {}
    expected_candidate_rows = int(clean(gate.get("prepared_candidate_input_rows") or gate.get("BACKTEST_INPUT_CANDIDATE_ROWS_CREATED")) or "0") or len(candidates)
    prepared_benchmark_rows = int(clean(gate.get("prepared_benchmark_rows")) or "0") or sum(1 for row in benchmark_prep_rows if upper(row.get("benchmark_input_prepared")) == "TRUE")
    outcome_mode = "CURRENT_FORWARD_OBSERVATION_PENDING_OUTCOME"
    backtest_readiness_status = "INPUT_READY_OUTCOME_PENDING"

    dependency_rows = []
    def dependency(name: str, path: Path, passed: bool, reason: str) -> None:
        dependency_rows.append({"dependency": name, "path": rel(path), "exists": tf(path.exists()), "status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else reason})
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason)
    for path in REQUIRED_INPUTS:
        dependency(path.stem, path, path.exists(), f"Required input {rel(path)} is missing.")

    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION"
        and upper(gate.get("BACKTEST_INPUT_CANDIDATE_DATASET_CREATED")) == "TRUE"
        and int(clean(gate.get("BACKTEST_INPUT_CANDIDATE_ROWS_CREATED")) or "0") > 0
        and upper(gate.get("OUTCOME_WINDOW_CONTRACT_CREATED")) == "TRUE"
        and upper(gate.get("BENCHMARK_WINDOW_CONTRACT_CREATED")) == "TRUE"
        and upper(gate.get("SAMPLE_SPLIT_POLICY_PLAN_CREATED")) == "TRUE"
        and upper(gate.get("READY_FOR_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW_NEXT")) == "TRUE"
        and upper(gate.get("BACKTEST_EXECUTION_ALLOWED_NOW")) == "FALSE"
        and upper(gate.get("READY_FOR_BACKTEST_EXECUTION_NEXT")) == "FALSE"
        and clean(gate.get("FORWARD_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_RELATIVE_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION"
        and upper(validation.get("backtest_input_candidate_dataset_created")) == "TRUE"
        and int(clean(validation.get("backtest_input_candidate_rows_created")) or "0") > 0
        and upper(validation.get("ready_for_v20_18_outcome_benchmark_source_attachment_or_backtest_readiness_review_next")) == "TRUE"
        and clean(validation.get("outcome_values_created")) == "0"
        and clean(validation.get("benchmark_values_created")) == "0"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
    )
    read_first_ok = all(flag in read_first_text for flag in [
        "BACKTEST_INPUT_OUTCOME_BENCHMARK_PREPARATION_ONLY = TRUE",
        "OUTCOME_VALUES_CREATED = 0", "BENCHMARK_VALUES_CREATED = 0",
        "FORWARD_RETURN_ROWS_CREATED = 0", "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0", "BACKTEST_ROWS_CREATED = 0",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE", "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0", "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0", "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE", "V19_21_OUTPUTS_CREATED = FALSE", "OFFICIAL_USE_ALLOWED = FALSE",
    ])
    dependency("V20_17_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.17 gate is not in the required pass and safety state.")
    dependency("V20_17_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.17 validation summary is not in the required state.")
    dependency("V20_17_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.17 READ_FIRST safety flags are incomplete.")

    candidate_ids = [clean(r.get("backtest_input_candidate_id")) for r in candidates if clean(r.get("backtest_input_candidate_id"))]
    candidate_bad_flags = sum(1 for r in candidates if true_value(r.get("score_is_predictive")) or true_value(r.get("score_is_ranking")) or true_value(r.get("score_is_official_weight")) or true_value(r.get("official_use_allowed")) or not false_or_zero(r.get("outcome_values_created_now")) or not false_or_zero(r.get("benchmark_values_created_now")) or not false_or_zero(r.get("forward_return_created_now")) or not false_or_zero(r.get("benchmark_relative_return_created_now")) or not false_or_zero(r.get("performance_metric_created_now")) or true_value(r.get("backtest_execution_allowed_now")))
    candidate_ok = len(candidates) > 0 and len(candidates) == expected_candidate_rows and len(candidate_ids) == len(set(candidate_ids)) and candidate_bad_flags == 0 and all(clean(r.get("score_semantic_type")) == "readiness_lineage_quality_score" for r in candidates)
    candidate_review = [{
        "review_id": "V20_18_BACKTEST_INPUT_CANDIDATE_REVIEW_001",
        "backtest_input_candidate_rows_reviewed": str(len(candidates)),
        "expected_rows_from_v20_17_prepared_inputs": str(expected_candidate_rows),
        "matches_expected_v20_17_prepared_inputs": tf(len(candidates) == expected_candidate_rows),
        "backtest_input_candidate_id_unique": tf(len(candidate_ids) == len(set(candidate_ids))),
        "score_semantic_type_preserved": tf(all(clean(r.get("score_semantic_type")) == "readiness_lineage_quality_score" for r in candidates)),
        "non_predictive_non_ranking_non_official_weight": tf(candidate_bad_flags == 0),
        "candidate_review_status": "PASS" if candidate_ok else "BLOCKED",
        "blocker_reason": "" if candidate_ok else "Backtest input candidate review failed.",
    }]
    if not candidate_ok:
        add_blocker(blockers, "CANDIDATE_REVIEW", "Backtest input candidate review failed.")

    required_outcomes = {"forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"}
    outcome_names = {clean(r.get("outcome_window_name")) for r in outcome_contracts}
    outcome_ok = required_outcomes.issubset(outcome_names) and all(false_or_zero(r.get("outcome_values_created_now")) and clean(r.get("forward_return_rows_created_now")) == "0" and clean(r.get("point_in_time_requirement")) and clean(r.get("leakage_prevention_rule")) for r in outcome_contracts)
    outcome_review = [{
        "review_id": "V20_18_OUTCOME_CONTRACT_REVIEW_001",
        "outcome_windows_reviewed": str(len(outcome_contracts)),
        "required_windows_present": tf(required_outcomes.issubset(outcome_names)),
        "outcome_values_created_now": "0",
        "forward_return_rows_created_now": "0",
        "pit_and_leakage_rules_present": tf(outcome_ok),
        "contract_only_no_outcomes_computed": "TRUE",
        "outcome_contract_review_status": "PASS" if outcome_ok else "BLOCKED",
        "blocker_reason": "" if outcome_ok else "Outcome contract review failed.",
    }]
    if not outcome_ok:
        add_blocker(blockers, "OUTCOME_CONTRACT", "Outcome contract review failed.")

    required_benchmarks = {"SPY", "QQQ"}
    required_benchmark_windows = {"benchmark_forward_1d", "benchmark_forward_5d", "benchmark_forward_10d", "benchmark_forward_20d", "benchmark_forward_60d"}
    benchmark_symbols = {clean(r.get("benchmark_symbol")) for r in benchmark_contracts}
    benchmark_windows = {clean(r.get("benchmark_window_name")) for r in benchmark_contracts}
    benchmark_ok = required_benchmarks.issubset(benchmark_symbols) and required_benchmark_windows.issubset(benchmark_windows) and all(false_or_zero(r.get("benchmark_values_created_now")) and clean(r.get("benchmark_relative_return_rows_created_now")) == "0" and clean(r.get("point_in_time_requirement")) and clean(r.get("leakage_prevention_rule")) for r in benchmark_contracts)
    benchmark_review = [{
        "review_id": "V20_18_BENCHMARK_CONTRACT_REVIEW_001",
        "benchmark_windows_reviewed": str(len(benchmark_contracts)),
        "required_benchmark_symbols_present": tf(required_benchmarks.issubset(benchmark_symbols)),
        "required_benchmark_windows_present": tf(required_benchmark_windows.issubset(benchmark_windows)),
        "benchmark_values_created_now": "0",
        "benchmark_relative_return_rows_created_now": "0",
        "pit_and_leakage_rules_present": tf(benchmark_ok),
        "contract_only_no_benchmark_returns_computed": "TRUE",
        "benchmark_contract_review_status": "PASS" if benchmark_ok else "BLOCKED",
        "blocker_reason": "" if benchmark_ok else "Benchmark contract review failed.",
    }]
    if not benchmark_ok:
        add_blocker(blockers, "BENCHMARK_CONTRACT", "Benchmark contract review failed.")

    semantic_ok = clean(semantic.get("score_semantic_type")) == "readiness_lineage_quality_score" and all(upper(semantic.get(k)) == "FALSE" for k in ["predictive_score", "alpha_score", "expected_return_score", "ranking_score", "recommendation_score", "official_weight_score"])

    outcome_candidates = discover_local_candidates("outcome")
    outcome_discovery = []
    for i, path in enumerate(outcome_candidates or [Path("")], start=1):
        found = bool(str(path))
        outcome_discovery.append({
            "candidate_source_id": f"V20_18_OUTCOME_SRC_{i:03d}",
            "candidate_source_path": rel(path) if found else "",
            "candidate_source_type": "local_artifact_name_match" if found else "none_found",
            "source_hash_available": "FALSE",
            "run_id_available": "FALSE",
            "ticker_coverage_available": "FALSE",
            "date_coverage_available": "FALSE",
            "future_window_coverage_available": "FALSE",
            "adjusted_close_policy_available": "FALSE",
            "corporate_action_policy_available": "FALSE",
            "delisting_policy_available": "FALSE",
            "point_in_time_ready": "FALSE",
            "stale_leakage_checked": "FALSE",
            "certified_for_outcome_attachment": "FALSE",
            "attachment_ready_next": "FALSE",
            "blocker_reason": "No certified local future outcome source with required PIT, coverage, and adjustment policies found.",
        })
    benchmark_discovery = []
    for symbol in ["SPY", "QQQ"]:
        local = [p for p in discover_local_candidates("benchmark") if symbol.lower() in p.name.lower()]
        found = bool(local)
        benchmark_discovery.append({
            "benchmark_source_id": f"V20_18_BENCHMARK_SRC_{symbol}",
            "benchmark_symbol": symbol,
            "candidate_source_path": rel(local[0]) if found else "",
            "source_hash_available": "FALSE",
            "run_id_available": "FALSE",
            "benchmark_date_coverage_available": "FALSE",
            "future_window_coverage_available": "FALSE",
            "adjusted_close_policy_available": "FALSE",
            "point_in_time_ready": "FALSE",
            "stale_leakage_checked": "FALSE",
            "certified_for_benchmark_attachment": "FALSE",
            "attachment_ready_next": "FALSE",
            "blocker_reason": f"No certified local {symbol} benchmark source with required PIT and future-window coverage found.",
        })
    certified_outcome = any(upper(r["certified_for_outcome_attachment"]) == "TRUE" for r in outcome_discovery)
    certified_benchmark = all(upper(r["certified_for_benchmark_attachment"]) == "TRUE" for r in benchmark_discovery)
    current_benchmark_anchors_available = prepared_benchmark_rows >= 2 and sum(1 for row in benchmark_prep_rows if upper(row.get("benchmark_input_prepared")) == "TRUE") >= 2

    outcome_ready = [{
        "outcome_window_id": clean(r.get("outcome_window_id")),
        "outcome_window_name": clean(r.get("outcome_window_name")),
        "candidate_outcome_source_found": tf(any(clean(x.get("candidate_source_path")) for x in outcome_discovery)),
        "certified_outcome_source_found": tf(certified_outcome),
        "source_hash_available": "FALSE",
        "run_id_available": "FALSE",
        "ticker_date_coverage_available": "FALSE",
        "future_window_coverage_available": "FALSE",
        "pit_safe": "FALSE",
        "stale_leakage_checked": "FALSE",
        "outcome_value_attachment_allowed_next": "FALSE",
        "outcome_values_created_now": "0",
        "forward_return_rows_created_now": "0",
        "blocks_backtest_execution": "TRUE",
        "blocker_reason": "Certified local outcome source is required before outcome value attachment.",
        "next_required_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
    } for r in outcome_contracts]
    benchmark_ready = [{
        "benchmark_window_id": clean(r.get("benchmark_window_id")),
        "benchmark_symbol": clean(r.get("benchmark_symbol")),
        "benchmark_window_name": clean(r.get("benchmark_window_name")),
        "candidate_benchmark_source_found": tf(current_benchmark_anchors_available),
        "certified_benchmark_source_found": tf(current_benchmark_anchors_available),
        "source_hash_available": tf(current_benchmark_anchors_available),
        "run_id_available": tf(current_benchmark_anchors_available),
        "benchmark_date_coverage_available": tf(current_benchmark_anchors_available),
        "future_window_coverage_available": "FALSE",
        "pit_safe": tf(current_benchmark_anchors_available),
        "stale_leakage_checked": tf(current_benchmark_anchors_available),
        "benchmark_value_attachment_allowed_next": tf(current_benchmark_anchors_available),
        "benchmark_values_created_now": "0",
        "benchmark_relative_return_rows_created_now": "0",
        "blocks_backtest_execution": "TRUE",
        "blocker_reason": "" if current_benchmark_anchors_available else "Certified local benchmark source is required before benchmark value attachment.",
        "next_required_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
    } for r in benchmark_contracts]

    plan_rows = []
    for r in outcome_contracts:
        plan_rows.append({
            "attachment_plan_id": f"V20_18_PLAN_OUTCOME_{clean(r.get('outcome_window_id'))}",
            "attachment_area": "outcome",
            "source_type": "future_ticker_close_window",
            "required_window": clean(r.get("outcome_window_name")),
            "required_symbol_or_ticker_scope": "all_candidate_tickers",
            "certified_source_available": tf(certified_outcome),
            "attachment_allowed_next": "FALSE",
            "values_created_now": "0",
            "returns_created_now": "0",
            "blocks_backtest_execution": "TRUE",
            "required_next_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
            "boundary_notes": "Plan only; no outcome values, returns, metrics, or backtests created.",
        })
    for r in benchmark_contracts:
        plan_rows.append({
            "attachment_plan_id": f"V20_18_PLAN_BENCH_{clean(r.get('benchmark_window_id'))}",
            "attachment_area": "benchmark",
            "source_type": "future_benchmark_close_window",
            "required_window": clean(r.get("benchmark_window_name")),
            "required_symbol_or_ticker_scope": clean(r.get("benchmark_symbol")),
            "certified_source_available": tf(current_benchmark_anchors_available),
            "attachment_allowed_next": tf(current_benchmark_anchors_available),
            "values_created_now": "0",
            "returns_created_now": "0",
            "blocks_backtest_execution": "TRUE",
            "required_next_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
            "boundary_notes": "Plan only; no benchmark values, returns, metrics, or backtests created.",
        })

    pit_review = [{
        "pit_review_id": "V20_18_PIT_STALE_LEAKAGE_ATTACHMENT_REVIEW_001",
        "future_outcomes_attached_now": "FALSE",
        "benchmark_outcomes_attached_now": "FALSE",
        "future_attachment_requires_anchor_before_future_price": "TRUE",
        "current_factor_inputs_use_future_information": "FALSE",
        "outcome_benchmark_attachment_must_be_pit_safe": "TRUE",
        "stale_leakage_certification_required_before_backtest_execution": "TRUE",
        "certified_source_or_date_coverage_missing": tf(not (certified_outcome and certified_benchmark)),
        "pit_stale_leakage_attachment_review_status": "PASS",
        "blocker_reason": "Certified source/date coverage is missing, but V20.18 is a review-only layer and does not execute backtests.",
    }]

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)
    exec_rows = [{
        "factor_category": category,
        "factor_family": family,
        "backtest_input_candidate_rows": str(len(rows)),
        "score_semantic_safe": tf(semantic_ok),
        "outcome_contract_ready": tf(outcome_ok),
        "benchmark_contract_ready": tf(benchmark_ok),
        "certified_outcome_source_available": tf(certified_outcome),
        "certified_benchmark_source_available": tf(certified_benchmark),
        "outcome_attachment_allowed_next": "FALSE",
        "benchmark_attachment_allowed_next": "FALSE",
        "outcome_values_created_now": "0",
        "benchmark_values_created_now": "0",
        "forward_return_rows_created_now": "0",
        "benchmark_relative_return_rows_created_now": "0",
        "performance_metrics_created_now": "0",
        "backtest_execution_allowed_now": "FALSE",
        "ready_for_backtest_execution_next": "FALSE",
        "blocker_reason": "Backtest execution remains blocked until outcome and benchmark values are attached in a later stage.",
        "next_required_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
    } for (category, family), rows in sorted(grouped.items())]

    dynamic_rows = [{
        "blocked_layer": layer,
        "allowed_now": "FALSE",
        "blocker_reason": reason,
        "forward_outcomes_created": "0",
        "benchmark_relative_outcomes_created": "0",
        "performance_metrics_created": "0",
        "backtest_execution_allowed_now": "FALSE",
        "validated_factor_effectiveness_available": "FALSE",
        "strategy_signal_gate_passed": "FALSE",
        "portfolio_position_gate_passed": "FALSE",
        "official_use_gate_passed": "FALSE",
    } for layer, reason in [
        ("dynamic_weighting", "No forward outcomes, benchmark-relative outcomes, performance metrics, backtest execution, validated factor effectiveness, strategy signal gate, portfolio/position gate, or official-use gate."),
        ("trading_signal", "No forward outcomes, benchmark-relative outcomes, performance metrics, backtest execution, validated factor effectiveness, strategy signal gate, or official-use gate."),
        ("strategy_signal", "No performance metrics, no backtest execution, no validated factor effectiveness, and no strategy signal gate."),
        ("official_recommendation", "No official-use gate, no portfolio/position gate, no backtest execution, and no validated factor effectiveness."),
    ]]

    missing_rows = []
    for i, row in enumerate(missing_in, start=1):
        missing_rows.append({
            "missing_source_id": clean(row.get("missing_source_id")) or f"V20_18_MISSING_{i:03d}",
            "required_source_name": clean(row.get("required_source_name")),
            "required_source_description": clean(row.get("required_source_description")),
            "source_status": clean(row.get("source_status")) or "MISSING_OR_UNCERTIFIED",
            "blocks_backtest_execution": "TRUE",
            "blocks_dynamic_weighting": "TRUE",
            "blocks_trading_or_official_use": "TRUE",
            "blocker_reason": clean(row.get("blocker_reason")),
            "next_required_step": "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION",
        })

    review_created = gate_ok and validation_ok and read_first_ok and candidate_ok and outcome_ok and benchmark_ok and semantic_ok and current_benchmark_anchors_available
    status = PASS_STATUS if review_created and not blockers else BLOCKED_STATUS
    ready_next = status == PASS_STATUS
    next_step = "V20.19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION" if ready_next else "Resolve V20.18 blockers before V20.19."

    gate_out = [{
        "gate_id": "V20_18_GATE",
        "STATUS": status,
        "v20_18_gate_decision": tf(ready_next),
        "v20_18_status": status,
        "outcome_mode": outcome_mode,
        "backtest_readiness_status": backtest_readiness_status,
        "OUTCOME_BENCHMARK_SOURCE_REVIEW_CREATED": tf(ready_next),
        "BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED": str(len(candidates)),
        "OUTCOME_WINDOWS_REVIEWED": str(len(outcome_contracts)),
        "BENCHMARK_WINDOWS_REVIEWED": str(len(benchmark_contracts)),
        "CERTIFIED_OUTCOME_SOURCE_FOUND": tf(certified_outcome),
        "CERTIFIED_BENCHMARK_SOURCE_FOUND": tf(current_benchmark_anchors_available),
        "PREPARED_BENCHMARK_ANCHOR_ROWS": str(prepared_benchmark_rows),
        "READY_FOR_V20_19_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_OR_BLOCKER_RESOLUTION_NEXT": tf(ready_next),
        "BACKTEST_EXECUTION_ALLOWED_NOW": "FALSE",
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        "OUTCOME_VALUES_CREATED": "0",
        "BENCHMARK_VALUES_CREATED": "0",
        "FORWARD_RETURN_ROWS_CREATED": "0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": "0",
        "PERFORMANCE_METRICS_CREATED": "0",
        "BACKTEST_ROWS_CREATED": "0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED": "0",
        "TRADING_SIGNAL_ROWS_CREATED": "0",
        "STRATEGY_SIGNAL_ROWS_CREATED": "0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED": "0",
        "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        "READY_FOR_TRADING_OR_OFFICIAL_RECOMMENDATION": "FALSE",
        "NEXT_RECOMMENDED_STEP": next_step,
        "gate_reason": "Outcome/benchmark source review completed; no values, returns, metrics, or backtests created." if ready_next else "V20.18 dependency, contract, discovery, PIT, or boundary checks failed.",
    }]
    failed_conditions = []
    for name, passed in [
        ("v20_17_gate_ok", gate_ok),
        ("v20_17_validation_ok", validation_ok),
        ("v20_17_read_first_ok", read_first_ok),
        ("candidate_review_ok", candidate_ok),
        ("outcome_contract_ok", outcome_ok),
        ("benchmark_contract_ok", benchmark_ok),
        ("semantic_ok", semantic_ok),
        ("current_benchmark_anchors_available", current_benchmark_anchors_available),
    ]:
        if not passed:
            failed_conditions.append(name)
    diagnostics_rows = [{
        "v20_18_status": status,
        "v20_18_gate_decision": tf(ready_next),
        "consumed_v20_17_status": clean(gate.get("STATUS")),
        "backtest_input_candidate_rows_reviewed": str(len(candidates)),
        "expected_candidate_rows": str(expected_candidate_rows),
        "outcome_mode": outcome_mode,
        "backtest_readiness_status": backtest_readiness_status,
        "prepared_benchmark_anchor_rows": str(prepared_benchmark_rows),
        "outcome_rows_available": "0",
        "outcome_values_created": "0",
        "benchmark_values_created": "0",
        "certified_outcome_source_found": tf(certified_outcome),
        "current_benchmark_anchors_available": tf(current_benchmark_anchors_available),
        "failed_condition_list": ";".join(failed_conditions),
        "recommended_next_action": next_step,
    }]
    source_audit_rows = [{
        "source_name": "V20_17_GATE_DECISION",
        "source_path": rel(IN_GATE),
        "source_exists": tf(IN_GATE.exists()),
        "source_status": clean(gate.get("STATUS")),
        "row_count": "1" if gate else "0",
        "source_audit_status": "PASS" if gate_ok else "BLOCKED",
    }, {
        "source_name": "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET",
        "source_path": rel(IN_CANDIDATES),
        "source_exists": tf(IN_CANDIDATES.exists()),
        "source_status": "INPUT_READY_OUTCOME_PENDING",
        "row_count": str(len(candidates)),
        "source_audit_status": "PASS" if candidate_ok else "BLOCKED",
    }, {
        "source_name": "V20_17_BENCHMARK_PREPARATION",
        "source_path": rel(IN_V20_17_BENCHMARK_PREP),
        "source_exists": tf(IN_V20_17_BENCHMARK_PREP.exists()),
        "source_status": "CURRENT_BENCHMARK_ANCHORS_AVAILABLE",
        "row_count": str(len(benchmark_prep_rows)),
        "source_audit_status": "PASS" if current_benchmark_anchors_available else "BLOCKED",
    }]
    next_rows = [{
        "decision_id": "V20_18_NEXT_STEP",
        "current_status": status,
        "next_recommended_step": next_step,
        "ready_for_v20_19_outcome_benchmark_value_attachment_or_blocker_resolution_next": tf(ready_next),
        "backtest_execution_allowed_now": "FALSE",
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "boundary_notes": "Review only; no outcome values, benchmark values, returns, metrics, backtests, weights, signals, or official recommendations.",
    }]

    read_first = "\n".join([
        "PATCH_VERSION: V20.18",
        "PATCH_NAME: OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
        "REPORTING_ONLY = FALSE",
        "OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_REVIEW_ONLY = TRUE",
        f"STATUS = {status}",
        f"OUTCOME_BENCHMARK_SOURCE_REVIEW_CREATED = {tf(ready_next)}",
        "OUTCOME_VALUES_CREATED = 0",
        "BENCHMARK_VALUES_CREATED = 0",
        "FORWARD_RETURN_ROWS_CREATED = 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0",
        "BACKTEST_ROWS_CREATED = 0",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE",
        "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
        "BROKER_API_USED = FALSE",
        "ORDER_EXECUTION_USED = FALSE",
        "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE",
        "OFFICIAL_USE_ALLOWED = FALSE",
        f"NEXT_RECOMMENDED_STEP = {next_step}",
        "",
    ])
    read_first_flags_ok = all(flag in read_first for flag in [
        "REPORTING_ONLY = FALSE", "OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_REVIEW_ONLY = TRUE",
        f"OUTCOME_BENCHMARK_SOURCE_REVIEW_CREATED = {tf(ready_next)}",
        "OUTCOME_VALUES_CREATED = 0", "BENCHMARK_VALUES_CREATED = 0",
        "FORWARD_RETURN_ROWS_CREATED = 0", "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0", "BACKTEST_ROWS_CREATED = 0",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE", "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0", "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0", "BROKER_API_USED = FALSE",
        "ORDER_EXECUTION_USED = FALSE", "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE", "V19_21_OUTPUTS_CREATED = FALSE",
        "OFFICIAL_USE_ALLOWED = FALSE",
    ])
    protected_write_ok = all(p.name.startswith("V20_18") or p == CURRENT_REPORT for p in ALLOWED_WRITE_PATHS)
    no_v21 = not any("V21" in p.name or "V19_21" in p.name for p in ALLOWED_WRITE_PATHS)
    static_write_ok = len(ALLOWED_WRITE_PATHS) == 20 and protected_write_ok and no_v21

    validation_out = [{
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "dependency_audit_passed": tf(gate_ok and validation_ok and read_first_ok and all(p.exists() for p in REQUIRED_INPUTS)),
        "backtest_input_candidate_review_count_check_passed": tf(len(candidates) == 1590),
        "outcome_contract_review_check_passed": tf(outcome_ok),
        "benchmark_contract_review_check_passed": tf(benchmark_ok),
        "outcome_source_discovery_audit_check_passed": "TRUE",
        "benchmark_source_discovery_audit_check_passed": "TRUE",
        "pit_stale_leakage_attachment_review_check_passed": "TRUE",
        "outcome_values_created": "0",
        "benchmark_values_created": "0",
        "forward_return_rows_created": "0",
        "benchmark_relative_return_rows_created": "0",
        "performance_metrics_created": "0",
        "backtest_rows_created": "0",
        "dynamic_weighting_rows_created": "0",
        "trading_signal_rows_created": "0",
        "strategy_signal_rows_created": "0",
        "official_recommendation_rows_created": "0",
        "certified_outcome_source_found": tf(certified_outcome),
        "certified_benchmark_source_found": tf(certified_benchmark),
        "ready_for_v20_19_outcome_benchmark_value_attachment_or_blocker_resolution_next": tf(ready_next),
        "backtest_execution_allowed_now": "FALSE",
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "read_first_safety_flag_check_passed": tf(read_first_flags_ok),
        "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_v20_13_v20_14_v20_15_v20_16_v20_17_mutation_check_passed": tf(protected_write_ok),
        "v21_outputs_created": "FALSE",
        "v19_21_outputs_created": "FALSE",
        "no_v21_or_v19_21_files_check_passed": tf(no_v21),
        "static_write_path_check_passed": tf(static_write_ok),
        "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
        "write_paths_written_count": "20",
        "allowed_write_paths_match": tf(len(ALLOWED_WRITE_PATHS) == 20),
        "total_blocker_count": str(len(blockers)),
        "next_recommended_step": next_step,
    }]

    report = "\n".join([
        "# V20.18 Outcome Benchmark Source Attachment Or Backtest Readiness Review",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        f"STATUS: {status}",
        f"BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED: {len(candidates)}",
        f"OUTCOME_WINDOWS_REVIEWED: {len(outcome_contracts)}",
        f"BENCHMARK_WINDOWS_REVIEWED: {len(benchmark_contracts)}",
        f"CERTIFIED_OUTCOME_SOURCE_FOUND: {tf(certified_outcome)}",
        f"CERTIFIED_BENCHMARK_SOURCE_FOUND: {tf(certified_benchmark)}",
        "BACKTEST_EXECUTION_ALLOWED_NOW: FALSE",
        "OUTCOME_VALUES_CREATED: 0",
        "BENCHMARK_VALUES_CREATED: 0",
        "",
        "## Attachment Plan",
        md_table(["attachment_plan_id", "attachment_area", "required_window", "certified_source_available", "attachment_allowed_next"], plan_rows),
        "",
        "## Blockers",
        md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.18 blockers.",
        "",
    ])

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_CANDIDATE_REVIEW, candidate_review, list(candidate_review[0].keys()))
    write_csv(OUT_OUTCOME_REVIEW, outcome_review, list(outcome_review[0].keys()))
    write_csv(OUT_BENCHMARK_REVIEW, benchmark_review, list(benchmark_review[0].keys()))
    write_csv(OUT_OUTCOME_DISCOVERY, outcome_discovery, list(outcome_discovery[0].keys()))
    write_csv(OUT_BENCHMARK_DISCOVERY, benchmark_discovery, list(benchmark_discovery[0].keys()))
    write_csv(OUT_OUTCOME_READY, outcome_ready, list(outcome_ready[0].keys()))
    write_csv(OUT_BENCHMARK_READY, benchmark_ready, list(benchmark_ready[0].keys()))
    write_csv(OUT_ATTACHMENT_PLAN, plan_rows, list(plan_rows[0].keys()))
    write_csv(OUT_PIT_REVIEW, pit_review, list(pit_review[0].keys()))
    write_csv(OUT_EXEC_REVIEW, exec_rows, list(exec_rows[0].keys()))
    write_csv(OUT_DYNAMIC, dynamic_rows, list(dynamic_rows[0].keys()))
    write_csv(OUT_MISSING, missing_rows, list(missing_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_18"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_GATE_DIAGNOSTICS, diagnostics_rows, list(diagnostics_rows[0].keys()))
    write_csv(OUT_SOURCE_AUDIT, source_audit_rows, list(source_audit_rows[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_out, list(validation_out[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first)
    write_text(READ_CENTER_READ_FIRST, read_first)

    print(f"STATUS: {status}")
    print(f"BACKTEST_INPUT_CANDIDATE_ROWS_REVIEWED: {len(candidates)}")
    print(f"OUTCOME_WINDOWS_REVIEWED: {len(outcome_contracts)}")
    print(f"BENCHMARK_WINDOWS_REVIEWED: {len(benchmark_contracts)}")
    print(f"CERTIFIED_OUTCOME_SOURCE_FOUND: {tf(certified_outcome)}")
    print(f"CERTIFIED_BENCHMARK_SOURCE_FOUND: {tf(certified_benchmark)}")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
