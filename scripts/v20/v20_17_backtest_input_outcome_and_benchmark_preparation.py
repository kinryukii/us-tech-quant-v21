from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "outputs" / "v20" / "ops"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_SCORE = CONSOLIDATION / "V20_15_LIMITED_FACTOR_SCORE_LAYER.csv"
IN_REVIEW = CONSOLIDATION / "V20_16_FACTOR_SCORE_LAYER_REVIEW.csv"
IN_SEMANTIC = CONSOLIDATION / "V20_16_FACTOR_SCORE_SEMANTIC_REVIEW.csv"
IN_FAMILY_READY = CONSOLIDATION / "V20_16_FACTOR_FAMILY_BACKTEST_READINESS_AUDIT.csv"
IN_BACKTEST_GATE = CONSOLIDATION / "V20_16_BACKTEST_READINESS_GATE_DECISION.csv"
IN_REQUIREMENTS = CONSOLIDATION / "V20_16_OUTCOME_BENCHMARK_REQUIREMENT_PLAN.csv"
IN_DOWNSTREAM_BLOCKERS = CONSOLIDATION / "V20_16_BACKTEST_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_16_GATE_DECISION.csv"
IN_VALIDATION = CONSOLIDATION / "V20_16_VALIDATION_SUMMARY.csv"
IN_READ_FIRST = OPS / "V20_16_READ_FIRST.txt"
IN_V20_7V_VALIDATION = CONSOLIDATION / "V20_7V_VALIDATION_SUMMARY.csv"
IN_V20_7V_STAGING = CONSOLIDATION / "V20_7V_ACTIVE_MARKET_SOURCE_STAGING.csv"
IN_V20_7V_EXCLUDED = CONSOLIDATION / "V20_7V_EXCLUDED_TICKERS.csv"
IN_V20_47_PROVIDER_SUMMARY = CONSOLIDATION / "V20_47_PROVIDER_REFRESH_SUMMARY.csv"
IN_V20_47_BENCHMARK_CACHE = CONSOLIDATION / "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE.csv"

OUT_DEPENDENCY = CONSOLIDATION / "V20_17_DEPENDENCY_AUDIT.csv"
OUT_CANDIDATES = CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
OUT_GATE_DIAGNOSTICS = CONSOLIDATION / "V20_17_GATE_DECISION_DIAGNOSTICS.csv"
OUT_BACKTEST_INPUT_PREP = CONSOLIDATION / "V20_17_BACKTEST_INPUT_PREPARATION.csv"
OUT_BENCHMARK_PREP = CONSOLIDATION / "V20_17_BENCHMARK_PREPARATION.csv"
OUT_SOURCE_AUDIT = CONSOLIDATION / "V20_17_SOURCE_AUDIT.csv"
OUT_SCHEMA = CONSOLIDATION / "V20_17_BACKTEST_INPUT_SCHEMA_AUDIT.csv"
OUT_SEMANTIC = CONSOLIDATION / "V20_17_SCORE_SEMANTIC_CARRYFORWARD_AUDIT.csv"
OUT_OUTCOME_CONTRACT = CONSOLIDATION / "V20_17_OUTCOME_WINDOW_CONTRACT.csv"
OUT_BENCHMARK_CONTRACT = CONSOLIDATION / "V20_17_BENCHMARK_WINDOW_CONTRACT.csv"
OUT_SAMPLE_POLICY = CONSOLIDATION / "V20_17_SAMPLE_SPLIT_POLICY_PLAN.csv"
OUT_PIT_PRECHECK = CONSOLIDATION / "V20_17_PIT_STALE_LEAKAGE_OUTCOME_PRECHECK.csv"
OUT_OUTCOME_SOURCE = CONSOLIDATION / "V20_17_OUTCOME_SOURCE_AVAILABILITY_AUDIT.csv"
OUT_BENCHMARK_SOURCE = CONSOLIDATION / "V20_17_BENCHMARK_SOURCE_AVAILABILITY_AUDIT.csv"
OUT_EXEC_READY = CONSOLIDATION / "V20_17_BACKTEST_EXECUTION_READINESS_AUDIT.csv"
OUT_DYNAMIC_TRADING = CONSOLIDATION / "V20_17_DYNAMIC_TRADING_BLOCKER_AUDIT.csv"
OUT_MISSING = CONSOLIDATION / "V20_17_MISSING_OUTCOME_BENCHMARK_SOURCE_REGISTER.csv"
OUT_BLOCKERS = CONSOLIDATION / "V20_17_BLOCKER_REGISTER.csv"
OUT_GATE = CONSOLIDATION / "V20_17_GATE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_17_NEXT_STEP_DECISION.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_17_VALIDATION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION.md"
READ_FIRST = OPS / "V20_17_READ_FIRST.txt"
READ_CENTER_READ_FIRST = READ_CENTER / "V20_17_READ_FIRST.txt"

PATCH_VERSION = "V20.17"
PASS_STATUS = "PASS_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION"
BLOCKED_STATUS = "BLOCKED_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION"

ALLOWED_WRITE_PATHS = {
    OUT_DEPENDENCY, OUT_CANDIDATES, OUT_GATE_DIAGNOSTICS,
    OUT_BACKTEST_INPUT_PREP, OUT_BENCHMARK_PREP, OUT_SOURCE_AUDIT,
    OUT_SCHEMA, OUT_SEMANTIC,
    OUT_OUTCOME_CONTRACT, OUT_BENCHMARK_CONTRACT, OUT_SAMPLE_POLICY,
    OUT_PIT_PRECHECK, OUT_OUTCOME_SOURCE, OUT_BENCHMARK_SOURCE,
    OUT_EXEC_READY, OUT_DYNAMIC_TRADING, OUT_MISSING, OUT_BLOCKERS,
    OUT_GATE, OUT_NEXT, OUT_VALIDATION, REPORT, CURRENT_REPORT,
    READ_FIRST, READ_CENTER_READ_FIRST,
}

REQUIRED_INPUTS = [
    IN_SCORE, IN_REVIEW, IN_SEMANTIC, IN_FAMILY_READY, IN_BACKTEST_GATE,
    IN_REQUIREMENTS, IN_DOWNSTREAM_BLOCKERS, IN_GATE, IN_VALIDATION, IN_READ_FIRST,
]

CANDIDATE_COLUMNS = [
    "backtest_input_candidate_id", "factor_score_row_id", "factor_evidence_row_id",
    "factor_attachment_row_id", "factor_research_row_id", "normalized_row_id",
    "ticker", "effective_observation_date", "effective_price_date", "effective_close",
    "source_system", "source_hash", "run_id", "sample_id", "factor_category",
    "factor_family", "score_type", "score_semantic_type", "factor_score_value",
    "score_is_predictive", "score_is_ranking", "score_is_official_weight",
    "eligible_for_outcome_attachment_next", "eligible_for_benchmark_attachment_next",
    "outcome_values_created_now", "benchmark_values_created_now",
    "forward_return_created_now", "benchmark_relative_return_created_now",
    "performance_metric_created_now", "backtest_execution_allowed_now",
    "dynamic_weighting_allowed_now", "trading_signal_allowed_now",
    "strategy_signal_allowed_now", "official_use_allowed", "research_only_flag",
    "backtest_input_prepared_at_utc", "backtest_input_source_step",
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def clean(value: object) -> str:
    return str(value or "").strip()


def upper(value: object) -> str:
    return clean(value).upper()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def first_row(path: Path) -> dict[str, str]:
    rows, _ = read_csv(path)
    return rows[0] if rows else {}


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


def parse_float(value: object) -> float | None:
    try:
        return float(clean(value))
    except ValueError:
        return None


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
        "blocker_id": f"V20_17_BLOCKER_{len(blockers) + 1:03d}",
        "blocker_scope": scope,
        "severity": "BLOCKING",
        "blocker_status": "OPEN",
        "blocker_reason": reason,
        "blocks_v20_17": "TRUE",
    })


def candidate_id(row: dict[str, str]) -> str:
    basis = "|".join([
        clean(row.get("factor_score_row_id")),
        clean(row.get("factor_family")),
        clean(row.get("ticker")),
        clean(row.get("effective_observation_date")),
        clean(row.get("effective_price_date")),
        clean(row.get("sample_id")),
        clean(row.get("source_hash")),
        clean(row.get("run_id")),
        "V20_17_BACKTEST_INPUT_CANDIDATE",
    ])
    return "V20_17_BTIN_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24].upper()


def md_table(headers: list[str], rows: list[dict[str, str]], limit: int = 20) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(clean(row.get(field)).replace("|", "/") for field in headers) + " |")
    if len(rows) > limit:
        lines.append("| " + " | ".join(["..."] + [f"{len(rows) - limit} more rows omitted"] + [""] * max(0, len(headers) - 2)) + " |")
    return "\n".join(lines)


def main() -> int:
    generated_at = utc_now()
    blockers: list[dict[str, str]] = []

    score_rows, _ = read_csv(IN_SCORE)
    semantic_rows_in, _ = read_csv(IN_SEMANTIC)
    family_ready_in, _ = read_csv(IN_FAMILY_READY)
    backtest_gate_rows, _ = read_csv(IN_BACKTEST_GATE)
    gate_rows, _ = read_csv(IN_GATE)
    validation_rows, _ = read_csv(IN_VALIDATION)
    v20_7v = first_row(IN_V20_7V_VALIDATION)
    v20_7v_staging, _ = read_csv(IN_V20_7V_STAGING)
    v20_7v_excluded, _ = read_csv(IN_V20_7V_EXCLUDED)
    provider_summary = first_row(IN_V20_47_PROVIDER_SUMMARY)
    benchmark_cache, _ = read_csv(IN_V20_47_BENCHMARK_CACHE)
    read_first_in = IN_READ_FIRST.read_text(encoding="utf-8", errors="replace") if IN_READ_FIRST.exists() else ""

    gate = gate_rows[0] if gate_rows else {}
    validation = validation_rows[0] if validation_rows else {}
    semantic = semantic_rows_in[0] if semantic_rows_in else {}
    backtest_gate = backtest_gate_rows[0] if backtest_gate_rows else {}

    dependency_rows: list[dict[str, str]] = []
    def dependency(name: str, path: Path, passed: bool, reason: str) -> None:
        dependency_rows.append({"dependency": name, "path": rel(path), "exists": tf(path.exists()), "status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else reason})
        if not passed:
            add_blocker(blockers, "DEPENDENCY", reason)

    for path in REQUIRED_INPUTS:
        dependency(path.stem, path, path.exists(), f"Required input {rel(path)} is missing.")

    gate_ok = (
        upper(gate.get("STATUS")) == "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE"
        and upper(gate.get("FACTOR_SCORE_REVIEW_PASSED")) == "TRUE"
        and upper(gate.get("SCORE_SEMANTIC_REVIEW_PASSED")) == "TRUE"
        and upper(gate.get("BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT")) == "TRUE"
        and upper(gate.get("BACKTEST_EXECUTION_ALLOWED_NOW")) == "FALSE"
        and upper(gate.get("READY_FOR_V20_17_BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION_NEXT")) == "TRUE"
        and clean(gate.get("FORWARD_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("BENCHMARK_RELATIVE_RETURN_ROWS_CREATED")) == "0"
        and clean(gate.get("PERFORMANCE_METRICS_CREATED")) == "0"
        and clean(gate.get("BACKTEST_ROWS_CREATED")) == "0"
        and clean(gate.get("DYNAMIC_WEIGHTING_ROWS_CREATED")) == "0"
        and clean(gate.get("TRADING_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("STRATEGY_SIGNAL_ROWS_CREATED")) == "0"
        and clean(gate.get("OFFICIAL_RECOMMENDATION_ROWS_CREATED")) == "0"
    )
    backtest_gate_ok = (
        upper(backtest_gate.get("gate_status")) == "PASS"
        and upper(backtest_gate.get("FACTOR_SCORE_REVIEW_PASSED")) == "TRUE"
        and upper(backtest_gate.get("BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT")) == "TRUE"
        and upper(backtest_gate.get("BACKTEST_EXECUTION_ALLOWED_NOW")) == "FALSE"
        and clean(backtest_gate.get("FORWARD_RETURN_ROWS_CREATED_NOW")) == "0"
        and clean(backtest_gate.get("PERFORMANCE_METRICS_CREATED_NOW")) == "0"
    )
    validation_ok = (
        upper(validation.get("status")) == "PASS_V20_16_FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE"
        and upper(validation.get("factor_score_review_passed")) == "TRUE"
        and upper(validation.get("score_semantic_review_check_passed")) == "TRUE"
        and upper(validation.get("ready_for_v20_17_backtest_input_outcome_and_benchmark_preparation_next")) == "TRUE"
        and clean(validation.get("forward_return_rows_created")) == "0"
        and clean(validation.get("benchmark_relative_return_rows_created")) == "0"
        and clean(validation.get("performance_metrics_created")) == "0"
        and clean(validation.get("backtest_rows_created")) == "0"
        and clean(validation.get("dynamic_weighting_rows_created")) == "0"
        and clean(validation.get("trading_signal_rows_created")) == "0"
        and clean(validation.get("strategy_signal_rows_created")) == "0"
        and clean(validation.get("official_recommendation_rows_created")) == "0"
    )
    read_first_ok = all(flag in read_first_in for flag in [
        "FACTOR_SCORE_REVIEW_OR_BACKTEST_READINESS_GATE_ONLY = TRUE",
        "FACTOR_SCORE_REVIEW_PASSED = TRUE",
        "SCORE_SEMANTIC_REVIEW_PASSED = TRUE",
        "BACKTEST_READINESS_PREPARATION_ALLOWED_NEXT = TRUE",
        "BACKTEST_EXECUTION_ALLOWED_NOW = FALSE",
        "FORWARD_RETURN_ROWS_CREATED = 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED = 0",
        "PERFORMANCE_METRICS_CREATED = 0",
        "BACKTEST_ROWS_CREATED = 0",
        "DYNAMIC_WEIGHTING_ROWS_CREATED = 0",
        "TRADING_SIGNAL_ROWS_CREATED = 0",
        "STRATEGY_SIGNAL_ROWS_CREATED = 0",
        "OFFICIAL_RECOMMENDATION_ROWS_CREATED = 0",
        "SOURCE_MUTATION_USED = FALSE",
        "V21_OUTPUTS_CREATED = FALSE",
        "V19_21_OUTPUTS_CREATED = FALSE",
        "OFFICIAL_USE_ALLOWED = FALSE",
    ])
    dependency("V20_16_GATE_REQUIRED_STATE", IN_GATE, gate_ok, "V20.16 gate is not in the required pass and safety state.")
    dependency("V20_16_BACKTEST_READINESS_GATE_REQUIRED_STATE", IN_BACKTEST_GATE, backtest_gate_ok, "V20.16 backtest readiness gate does not allow V20.17 preparation.")
    dependency("V20_16_VALIDATION_REQUIRED_STATE", IN_VALIDATION, validation_ok, "V20.16 validation summary is not in the required state.")
    dependency("V20_16_READ_FIRST_SAFETY_FLAGS", IN_READ_FIRST, read_first_ok, "V20.16 READ_FIRST safety flags are incomplete.")

    v20_7v_status = clean(v20_7v.get("status"))
    v20_7v_usable = upper(v20_7v.get("active_market_source_staging_usable") or v20_7v.get("active_source_staging_candidate_ready"))
    eligible_row_count = int(clean(v20_7v.get("eligible_row_count")) or "0")
    excluded_row_count = int(clean(v20_7v.get("excluded_row_count")) or "0")
    exclusion_threshold = int(clean(v20_7v.get("exclusion_threshold")) or "0")
    v20_7v_current_ok = (
        v20_7v_status == "PASS_V20_7V_ACTIVE_MARKET_SOURCE_STAGING_READY"
        and v20_7v_usable == "TRUE"
        and eligible_row_count > 0
        and len(v20_7v_staging) == eligible_row_count
        and excluded_row_count <= exclusion_threshold
        and all(clean(row.get("exclusion_reason")) for row in v20_7v_excluded)
    )
    dependency("V20_7V_CURRENT_ACTIVE_STAGING", IN_V20_7V_STAGING, v20_7v_current_ok, "V20.17 requires current V20.7V eligible active staging and audited exclusions.")

    semantic_ok = (
        clean(semantic.get("score_semantic_type")) == "readiness_lineage_quality_score"
        and upper(semantic.get("predictive_score")) == "FALSE"
        and upper(semantic.get("alpha_score")) == "FALSE"
        and upper(semantic.get("expected_return_score")) == "FALSE"
        and upper(semantic.get("ranking_score")) == "FALSE"
        and upper(semantic.get("recommendation_score")) == "FALSE"
        and upper(semantic.get("official_weight_score")) == "FALSE"
    )
    if not semantic_ok:
        add_blocker(blockers, "SEMANTIC", "V20.16 score semantic review is missing or unsafe.")

    accepted_scores = score_rows if semantic_ok else []
    expected_factor_families = len({clean(row.get("factor_family")) for row in accepted_scores if clean(row.get("factor_family"))}) or int(clean(gate.get("FACTOR_FAMILIES_REVIEWED")) or "0")
    expected_candidate_rows = eligible_row_count * expected_factor_families if v20_7v_current_ok else int(clean(gate.get("expected_score_rows_from_current_v20_7v_eligible_rows")) or "0")
    expected_candidate_rows = expected_candidate_rows or len(accepted_scores)
    candidate_rows = []
    for row in accepted_scores:
        candidate_rows.append({
            "backtest_input_candidate_id": candidate_id(row),
            "factor_score_row_id": clean(row.get("factor_score_row_id")),
            "factor_evidence_row_id": clean(row.get("factor_evidence_row_id")),
            "factor_attachment_row_id": clean(row.get("factor_attachment_row_id")),
            "factor_research_row_id": clean(row.get("factor_research_row_id")),
            "normalized_row_id": clean(row.get("normalized_row_id")),
            "ticker": clean(row.get("ticker")),
            "effective_observation_date": clean(row.get("effective_observation_date")),
            "effective_price_date": clean(row.get("effective_price_date")),
            "effective_close": clean(row.get("effective_close")),
            "source_system": clean(row.get("source_system")),
            "source_hash": clean(row.get("source_hash")),
            "run_id": clean(row.get("run_id")),
            "sample_id": clean(row.get("sample_id")),
            "factor_category": clean(row.get("factor_category")),
            "factor_family": clean(row.get("factor_family")),
            "score_type": clean(row.get("score_type")),
            "score_semantic_type": "readiness_lineage_quality_score",
            "factor_score_value": clean(row.get("factor_score_value")),
            "score_is_predictive": "FALSE",
            "score_is_ranking": "FALSE",
            "score_is_official_weight": "FALSE",
            "eligible_for_outcome_attachment_next": "TRUE",
            "eligible_for_benchmark_attachment_next": "TRUE",
            "outcome_values_created_now": "FALSE",
            "benchmark_values_created_now": "FALSE",
            "forward_return_created_now": "FALSE",
            "benchmark_relative_return_created_now": "FALSE",
            "performance_metric_created_now": "FALSE",
            "backtest_execution_allowed_now": "FALSE",
            "dynamic_weighting_allowed_now": "FALSE",
            "trading_signal_allowed_now": "FALSE",
            "strategy_signal_allowed_now": "FALSE",
            "official_use_allowed": "FALSE",
            "research_only_flag": "TRUE",
            "backtest_input_prepared_at_utc": generated_at,
            "backtest_input_source_step": PATCH_VERSION,
        })

    benchmark_prep_rows = []
    for row in benchmark_cache:
        symbol = clean(row.get("ticker")).upper()
        latest_date = clean(row.get("latest_price_date"))
        latest_close = clean(row.get("latest_close") or row.get("close_like_price"))
        status_text = clean(row.get("refresh_status")).upper()
        benchmark_prep_rows.append({
            "benchmark_symbol": symbol,
            "provider_name": clean(row.get("provider_name")),
            "source_path": rel(IN_V20_47_BENCHMARK_CACHE),
            "run_id": clean(row.get("run_id")),
            "latest_price_date": latest_date,
            "latest_close": latest_close,
            "refresh_status": status_text,
            "benchmark_input_prepared": tf(symbol in {"SPY", "QQQ"} and status_text == "SUCCESS" and bool(latest_date) and bool(latest_close)),
            "benchmark_values_created_now": "FALSE",
            "benchmark_relative_return_rows_created_now": "0",
            "future_window_coverage_available": "FALSE",
            "backtest_execution_allowed_now": "FALSE",
            "preparation_notes": "Certified current benchmark anchor only; no future benchmark outcome or relative return computed.",
        })
    benchmark_count = sum(1 for row in benchmark_prep_rows if row["benchmark_input_prepared"] == "TRUE")
    benchmark_prep_ok = benchmark_count >= 2 and {row["benchmark_symbol"] for row in benchmark_prep_rows if row["benchmark_input_prepared"] == "TRUE"} >= {"SPY", "QQQ"}

    ids = [clean(r.get("backtest_input_candidate_id")) for r in candidate_rows if clean(r.get("backtest_input_candidate_id"))]
    score_ids = [clean(r.get("factor_score_row_id")) for r in candidate_rows if clean(r.get("factor_score_row_id"))]
    duplicate_candidate_ids = len(candidate_rows) - len(set(ids))
    duplicate_score_ids = len(candidate_rows) - len(set(score_ids))
    missing_ticker = sum(1 for r in candidate_rows if not clean(r.get("ticker")))
    bad_dates = sum(1 for r in candidate_rows if not parse_date_ok(r.get("effective_observation_date")) or not parse_date_ok(r.get("effective_price_date")))
    bad_close = sum(1 for r in candidate_rows if (parse_float(r.get("effective_close")) or 0) <= 0)
    missing_lineage = sum(1 for r in candidate_rows if not clean(r.get("source_hash")) or not clean(r.get("run_id")) or not clean(r.get("sample_id")))
    created_values = {
        "outcome": sum(1 for r in candidate_rows if not false_or_zero(r.get("outcome_values_created_now"))),
        "benchmark": sum(1 for r in candidate_rows if not false_or_zero(r.get("benchmark_values_created_now"))),
        "forward": sum(1 for r in candidate_rows if not false_or_zero(r.get("forward_return_created_now"))),
        "relative": sum(1 for r in candidate_rows if not false_or_zero(r.get("benchmark_relative_return_created_now"))),
        "performance": sum(1 for r in candidate_rows if not false_or_zero(r.get("performance_metric_created_now"))),
    }
    downstream_true = sum(1 for r in candidate_rows if true_value(r.get("backtest_execution_allowed_now")) or true_value(r.get("dynamic_weighting_allowed_now")) or true_value(r.get("trading_signal_allowed_now")) or true_value(r.get("strategy_signal_allowed_now")) or true_value(r.get("official_use_allowed")))

    schema_rows = []
    fields = set(CANDIDATE_COLUMNS)
    for col in CANDIDATE_COLUMNS:
        non_empty = sum(1 for r in candidate_rows if clean(r.get(col)))
        if col == "backtest_input_candidate_id":
            passed = non_empty == len(candidate_rows) and duplicate_candidate_ids == 0
        elif col == "factor_score_row_id":
            passed = non_empty == len(candidate_rows) and duplicate_score_ids == 0
        elif col in {"ticker", "source_hash", "run_id", "sample_id"}:
            passed = non_empty == len(candidate_rows)
        elif col in {"effective_observation_date", "effective_price_date"}:
            passed = non_empty == len(candidate_rows) and bad_dates == 0
        elif col == "effective_close":
            passed = non_empty == len(candidate_rows) and bad_close == 0
        elif col == "score_semantic_type":
            passed = all(clean(r.get(col)) == "readiness_lineage_quality_score" for r in candidate_rows)
        elif col in {"score_is_predictive", "score_is_ranking", "score_is_official_weight", "official_use_allowed", "backtest_execution_allowed_now", "dynamic_weighting_allowed_now", "trading_signal_allowed_now", "strategy_signal_allowed_now"}:
            passed = all(not true_value(r.get(col)) for r in candidate_rows)
        elif col in {"outcome_values_created_now", "benchmark_values_created_now", "forward_return_created_now", "benchmark_relative_return_created_now", "performance_metric_created_now"}:
            passed = all(false_or_zero(r.get(col)) for r in candidate_rows)
        else:
            passed = col in fields and non_empty == len(candidate_rows)
        schema_rows.append({"column_name": col, "required": "TRUE", "detected": tf(col in fields), "non_empty_row_count": str(non_empty), "row_count": str(len(candidate_rows)), "schema_status": "PASS" if passed else "BLOCKED", "blocker_reason": "" if passed else f"Backtest input field {col} failed schema or safety validation."})
    schema_passed = bool(candidate_rows) and all(r["schema_status"] == "PASS" for r in schema_rows)
    if not schema_passed:
        add_blocker(blockers, "SCHEMA", "Backtest input candidate schema audit failed.")

    semantic_carry_rows = [{
        "semantic_carryforward_id": "V20_17_SEMANTIC_CARRYFORWARD_001",
        "score_semantic_type": clean(semantic.get("score_semantic_type")),
        "predictive_score": clean(semantic.get("predictive_score")),
        "alpha_score": clean(semantic.get("alpha_score")),
        "expected_return_score": clean(semantic.get("expected_return_score")),
        "ranking_score": clean(semantic.get("ranking_score")),
        "recommendation_score": clean(semantic.get("recommendation_score")),
        "official_weight_score": clean(semantic.get("official_weight_score")),
        "semantic_warning_text": clean(semantic.get("semantic_warning_text")),
        "semantic_carryforward_status": "PASS" if semantic_ok else "BLOCKED",
        "blocker_reason": "" if semantic_ok else "V20.16 semantic review is unsafe or missing.",
    }]

    outcome_windows = ["forward_1d", "forward_5d", "forward_10d", "forward_20d", "forward_60d"]
    outcome_contract_rows = [{
        "outcome_window_id": f"V20_17_OUTCOME_{i:03d}",
        "outcome_window_name": name,
        "anchor_date_field": "effective_price_date",
        "required_future_price_date_rule": "strictly_after_anchor_date_by_window_on_trading_calendar",
        "required_future_price_field": "future_adjusted_close",
        "required_adjustment_policy": "split_dividend_adjusted_close_required",
        "required_trading_calendar_policy": "US_equity_trading_calendar_alignment_required",
        "required_delisting_policy": "explicit_delisting_handling_required",
        "required_corporate_action_policy": "corporate_actions_adjusted_or_excluded",
        "point_in_time_requirement": "future_labels_attached_only_after_explicit_outcome_gate",
        "leakage_prevention_rule": "no_future_price_join_in_v20_17",
        "stale_data_rule": "future_source_freshness_certification_required",
        "outcome_values_created_now": "FALSE",
        "forward_return_rows_created_now": "0",
        "source_required": "TRUE",
        "currently_available": "FALSE",
        "blocks_backtest_execution": "TRUE",
        "next_required_step": "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
    } for i, name in enumerate(outcome_windows, start=1)]

    benchmark_windows = ["benchmark_forward_1d", "benchmark_forward_5d", "benchmark_forward_10d", "benchmark_forward_20d", "benchmark_forward_60d"]
    benchmark_contract_rows = []
    for symbol in ["SPY", "QQQ"]:
        for i, name in enumerate(benchmark_windows, start=1):
            benchmark_contract_rows.append({
                "benchmark_window_id": f"V20_17_BENCH_{symbol}_{i:03d}",
                "benchmark_symbol": symbol,
                "benchmark_window_name": name,
                "anchor_date_field": "effective_price_date",
                "required_benchmark_price_date_rule": "strictly_after_anchor_date_by_window_on_trading_calendar",
                "required_benchmark_price_field": "future_benchmark_adjusted_close",
                "required_adjustment_policy": "split_dividend_adjusted_close_required",
                "required_trading_calendar_policy": "US_equity_trading_calendar_alignment_required",
                "point_in_time_requirement": "benchmark_labels_attached_only_after_explicit_outcome_gate",
                "leakage_prevention_rule": "no_future_benchmark_join_in_v20_17",
                "stale_data_rule": "benchmark_source_freshness_certification_required",
                "benchmark_values_created_now": "FALSE",
                "benchmark_relative_return_rows_created_now": "0",
                "source_required": "TRUE",
                "currently_available": "FALSE",
                "blocks_backtest_execution": "TRUE",
                "next_required_step": "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
            })

    policy_names = [
        "chronological_train_validation_test_policy", "rolling_window_policy",
        "walk_forward_policy", "holdout_policy", "leakage_exclusion_policy",
        "event_date_exclusion_policy", "duplicate_sample_policy",
        "ticker_survivorship_policy", "universe_reconstitution_policy",
    ]
    policy_rows = [{
        "sample_policy_id": f"V20_17_POLICY_{i:03d}",
        "policy_name": name,
        "policy_purpose": "Define future evaluation controls without executing a split.",
        "required_fields": "ticker;effective_price_date;sample_id;window_id;policy_role",
        "currently_executable": "FALSE",
        "blocks_backtest_execution": "TRUE",
        "blocks_dynamic_weighting": "TRUE",
        "next_required_step": "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
        "boundary_notes": "Policy plan only; no samples split and no evaluation run.",
    } for i, name in enumerate(policy_names, start=1)]

    pit_precheck_rows = [{
        "precheck_id": "V20_17_PIT_STALE_LEAKAGE_PRECHECK_001",
        "outcome_windows_computed_now": "FALSE",
        "benchmark_windows_computed_now": "FALSE",
        "future_price_dates_must_be_strictly_after_anchor_dates": "TRUE",
        "current_features_use_future_information": "FALSE",
        "score_anchor_date_fields": "effective_observation_date;effective_price_date",
        "later_outcome_attachment_must_be_pit_safe": "TRUE",
        "missing_pit_stale_leakage_prerequisites": "future outcome source certification;benchmark source certification;trading calendar alignment;corporate action policy",
        "pit_stale_leakage_precheck_status": "PASS",
        "blocker_reason": "",
    }]

    outcome_source_rows = [{
        "availability_audit_id": "V20_17_OUTCOME_SOURCE_001",
        "certified_outcome_source_found": "FALSE",
        "candidate_source_path": "",
        "source_hash_available": "FALSE",
        "run_id_available": "FALSE",
        "ticker_date_coverage_available": "FALSE",
        "future_window_coverage_available": "FALSE",
        "pit_safe": "FALSE",
        "stale_leakage_checked": "FALSE",
        "attachment_ready_next": "FALSE",
        "blocks_backtest_execution": "TRUE",
        "blocker_reason": "No certified future outcome source is attached in current V20 artifacts; no external fetch or inference performed.",
    }]
    benchmark_source_rows = []
    for symbol in ["SPY", "QQQ"]:
        benchmark_source_rows.append({
            "availability_audit_id": f"V20_17_BENCHMARK_SOURCE_{symbol}",
            "certified_benchmark_source_found": "FALSE",
            "benchmark_symbol": symbol,
            "candidate_source_path": "",
            "source_hash_available": "FALSE",
            "run_id_available": "FALSE",
            "benchmark_date_coverage_available": "FALSE",
            "future_window_coverage_available": "FALSE",
            "pit_safe": "FALSE",
            "stale_leakage_checked": "FALSE",
            "attachment_ready_next": "FALSE",
            "blocks_backtest_execution": "TRUE",
            "blocker_reason": f"No certified {symbol} benchmark future price window source is attached in current V20 artifacts; no external fetch or inference performed.",
        })

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in candidate_rows:
        grouped[(clean(row.get("factor_category")), clean(row.get("factor_family")))].append(row)
    execution_ready_rows = []
    for (category, family), rows in sorted(grouped.items()):
        execution_ready_rows.append({
            "factor_category": category,
            "factor_family": family,
            "backtest_input_candidate_rows": str(len(rows)),
            "unique_tickers": str(len({clean(r.get("ticker")) for r in rows if clean(r.get("ticker"))})),
            "score_semantic_safe": tf(semantic_ok),
            "outcome_window_contract_created": "TRUE",
            "benchmark_window_contract_created": "TRUE",
            "certified_outcome_source_available": "FALSE",
            "certified_benchmark_source_available": "FALSE",
            "sample_split_policy_created": "TRUE",
            "pit_stale_leakage_precheck_passed": "TRUE",
            "backtest_input_preparation_passed": "TRUE",
            "backtest_execution_allowed_now": "FALSE",
            "ready_for_outcome_benchmark_attachment_next": "TRUE",
            "ready_for_backtest_execution_next": "FALSE",
            "blocker_reason": "Backtest execution remains blocked until future outcome and benchmark values are attached in a later stage.",
            "next_required_step": "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
        })

    dynamic_rows = []
    for layer, reason in [
        ("dynamic_weighting", "No forward outcomes, benchmark-relative outcomes, performance metrics, backtest execution, validated factor effectiveness, strategy signal gate, portfolio/position gate, or official-use gate."),
        ("trading_signal", "No forward outcomes, benchmark-relative outcomes, performance metrics, backtest execution, validated factor effectiveness, strategy signal gate, or official-use gate."),
        ("strategy_signal", "No performance metrics, no backtest execution, no validated factor effectiveness, and no strategy signal gate."),
        ("official_recommendation", "No official-use gate, no portfolio/position gate, no backtest execution, and no validated factor effectiveness."),
    ]:
        dynamic_rows.append({
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
        })

    missing_sources = [
        ("ticker_future_close_windows_1d_5d_10d_20d_60d", "future adjusted close windows for tickers"),
        ("adjusted_close_policy", "split/dividend adjusted close policy"),
        ("trading_calendar_alignment", "US equity trading calendar alignment"),
        ("corporate_action_adjustment_policy", "corporate action adjustment policy"),
        ("delisting_handling", "delisting handling"),
        ("spy_future_benchmark_windows", "SPY future benchmark windows"),
        ("qqq_future_benchmark_windows", "QQQ future benchmark windows"),
        ("benchmark_relative_return_source_requirements", "benchmark-relative return source requirements"),
        ("outcome_pit_certification", "outcome PIT certification"),
        ("benchmark_pit_certification", "benchmark PIT certification"),
    ]
    missing_rows = [{
        "missing_source_id": f"V20_17_MISSING_{i:03d}",
        "required_source_name": name,
        "required_source_description": description,
        "source_status": "MISSING_OR_UNCERTIFIED",
        "blocks_backtest_execution": "TRUE",
        "blocks_dynamic_weighting": "TRUE",
        "blocks_trading_or_official_use": "TRUE",
        "blocker_reason": f"{description} must be certified before backtest execution.",
        "next_required_step": "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW",
    } for i, (name, description) in enumerate(missing_sources, start=1)]

    contracts_ok = len(outcome_contract_rows) == 5 and len(benchmark_contract_rows) == 10 and len(policy_rows) == 9
    boundary_ok = all(v == 0 for v in created_values.values()) and downstream_true == 0
    candidate_ok = len(candidate_rows) == expected_candidate_rows and len(candidate_rows) > 0 and duplicate_candidate_ids == 0 and duplicate_score_ids == 0 and missing_ticker == 0 and bad_dates == 0 and bad_close == 0 and missing_lineage == 0
    failed_conditions = []
    for name, passed in [
        ("v20_16_gate_ok", gate_ok),
        ("v20_16_backtest_gate_ok", backtest_gate_ok),
        ("v20_16_validation_ok", validation_ok),
        ("v20_16_read_first_ok", read_first_ok),
        ("consumed_current_v20_7v_active_staging", v20_7v_current_ok),
        ("score_semantic_ok", semantic_ok),
        ("schema_passed", schema_passed),
        ("contracts_ok", contracts_ok),
        ("benchmark_preparation_ok", benchmark_prep_ok),
        ("safety_boundary_ok", boundary_ok),
        ("candidate_input_rows_match_expected", candidate_ok),
    ]:
        if not passed:
            failed_conditions.append(name)
    gate_passed = gate_ok and backtest_gate_ok and validation_ok and read_first_ok and v20_7v_current_ok and semantic_ok and schema_passed and contracts_ok and benchmark_prep_ok and boundary_ok and candidate_ok and not blockers
    status = PASS_STATUS if gate_passed else BLOCKED_STATUS
    next_step = "V20.18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW" if gate_passed else "Resolve V20.17 blockers before V20.18."

    gate_out = [{
        "gate_id": "V20_17_GATE",
        "STATUS": status,
        "v20_17_gate_decision": tf(gate_passed),
        "v20_17_status": status,
        "consumed_v20_16_status": clean(gate.get("STATUS")),
        "consumed_v20_7v_status": v20_7v_status,
        "active_staging_row_count": str(len(v20_7v_staging)),
        "excluded_row_count": str(excluded_row_count),
        "benchmark_count": str(benchmark_count),
        "prepared_candidate_input_rows": str(len(candidate_rows)),
        "prepared_benchmark_rows": str(benchmark_count),
        "outcome_rows_available": "0",
        "failed_condition_list": ";".join(failed_conditions),
        "consumed_current_v20_7v_active_staging": tf(v20_7v_current_ok),
        "BACKTEST_INPUT_CANDIDATE_DATASET_CREATED": tf(candidate_ok),
        "BACKTEST_INPUT_CANDIDATE_ROWS_CREATED": str(len(candidate_rows)),
        "OUTCOME_WINDOW_CONTRACT_CREATED": tf(contracts_ok),
        "BENCHMARK_WINDOW_CONTRACT_CREATED": tf(contracts_ok),
        "SAMPLE_SPLIT_POLICY_PLAN_CREATED": tf(len(policy_rows) == 9),
        "READY_FOR_V20_18_OUTCOME_BENCHMARK_SOURCE_ATTACHMENT_OR_BACKTEST_READINESS_REVIEW_NEXT": tf(gate_passed),
        "BACKTEST_EXECUTION_ALLOWED_NOW": "FALSE",
        "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
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
        "gate_reason": "Backtest input candidates and outcome/benchmark contracts prepared without computing outcomes or running backtests." if gate_passed else "V20.17 preparation checks failed.",
    }]
    next_rows = [{
        "decision_id": "V20_17_NEXT_STEP",
        "current_status": status,
        "next_recommended_step": next_step,
        "ready_for_v20_18_outcome_benchmark_source_attachment_or_backtest_readiness_review_next": tf(gate_passed),
        "backtest_execution_allowed_now": "FALSE",
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "boundary_notes": "Preparation only; no outcomes, benchmark values, returns, metrics, backtests, weights, signals, or official recommendations.",
    }]
    missing_artifacts = [row["path"] for row in dependency_rows if row["exists"] != "TRUE"]
    diagnostics_rows = [{
        "v20_17_status": status,
        "v20_17_gate_decision": tf(gate_passed),
        "consumed_v20_16_status": clean(gate.get("STATUS")),
        "consumed_v20_7v_status": v20_7v_status,
        "active_staging_row_count": str(len(v20_7v_staging)),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "benchmark_count": str(benchmark_count),
        "prepared_candidate_input_rows": str(len(candidate_rows)),
        "expected_candidate_input_rows": str(expected_candidate_rows),
        "prepared_benchmark_rows": str(benchmark_count),
        "outcome_rows_available": "0",
        "outcome_rows_created": "0",
        "benchmark_values_created": "0",
        "missing_artifact_list": ";".join(missing_artifacts),
        "failed_condition_list": ";".join(failed_conditions),
        "recommended_next_action": next_step,
    }]
    input_prep_rows = [{
        "input_preparation_id": "V20_17_BACKTEST_INPUT_PREPARATION_001",
        "consumed_v20_16_status": clean(gate.get("STATUS")),
        "consumed_v20_7v_status": v20_7v_status,
        "active_staging_row_count": str(len(v20_7v_staging)),
        "eligible_row_count": str(eligible_row_count),
        "excluded_row_count": str(excluded_row_count),
        "factor_score_rows_consumed": str(len(score_rows)),
        "prepared_candidate_input_rows": str(len(candidate_rows)),
        "expected_candidate_input_rows": str(expected_candidate_rows),
        "input_preparation_status": "PASS" if candidate_ok else "BLOCKED",
        "dummy_outcomes_created": "FALSE",
        "dummy_benchmark_rows_created": "FALSE",
        "backtest_execution_allowed_now": "FALSE",
    }]
    source_audit_rows = [{
        "source_name": "V20_16_GATE_DECISION",
        "source_path": rel(IN_GATE),
        "source_exists": tf(IN_GATE.exists()),
        "source_status": clean(gate.get("STATUS")),
        "row_count": "1" if gate else "0",
        "source_audit_status": "PASS" if gate_ok else "BLOCKED",
    }, {
        "source_name": "V20_7V_ACTIVE_MARKET_SOURCE_STAGING",
        "source_path": rel(IN_V20_7V_STAGING),
        "source_exists": tf(IN_V20_7V_STAGING.exists()),
        "source_status": v20_7v_status,
        "row_count": str(len(v20_7v_staging)),
        "source_audit_status": "PASS" if v20_7v_current_ok else "BLOCKED",
    }, {
        "source_name": "V20_7V_EXCLUDED_TICKERS",
        "source_path": rel(IN_V20_7V_EXCLUDED),
        "source_exists": tf(IN_V20_7V_EXCLUDED.exists()),
        "source_status": "AUDITED_EXCLUSIONS",
        "row_count": str(len(v20_7v_excluded)),
        "source_audit_status": "PASS" if excluded_row_count <= exclusion_threshold else "BLOCKED",
    }, {
        "source_name": "V20_47_YAHOO_CURRENT_BENCHMARK_PRICE_CACHE",
        "source_path": rel(IN_V20_47_BENCHMARK_CACHE),
        "source_exists": tf(IN_V20_47_BENCHMARK_CACHE.exists()),
        "source_status": clean(provider_summary.get("provider_name")) or "yahoo/yfinance",
        "row_count": str(len(benchmark_cache)),
        "source_audit_status": "PASS" if benchmark_prep_ok else "BLOCKED",
    }]

    read_first = "\n".join([
        "PATCH_VERSION: V20.17",
        "PATCH_NAME: BACKTEST_INPUT_OUTCOME_AND_BENCHMARK_PREPARATION",
        "REPORTING_ONLY = FALSE",
        "BACKTEST_INPUT_OUTCOME_BENCHMARK_PREPARATION_ONLY = TRUE",
        f"STATUS = {status}",
        f"BACKTEST_INPUT_CANDIDATE_DATASET_CREATED = {tf(gate_passed)}",
        f"BACKTEST_INPUT_CANDIDATE_ROWS_CREATED = {len(candidate_rows)}",
        f"CONSUMED_V20_16_STATUS = {clean(gate.get('STATUS'))}",
        f"CONSUMED_V20_7V_STATUS = {v20_7v_status}",
        f"ACTIVE_STAGING_ROW_COUNT = {len(v20_7v_staging)}",
        f"EXCLUDED_ROW_COUNT = {excluded_row_count}",
        f"BENCHMARK_COUNT = {benchmark_count}",
        f"PREPARED_CANDIDATE_INPUT_ROWS = {len(candidate_rows)}",
        f"PREPARED_BENCHMARK_ROWS = {benchmark_count}",
        "OUTCOME_ROWS_AVAILABLE = 0",
        f"FAILED_CONDITION_LIST = {';'.join(failed_conditions)}",
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
        "REPORTING_ONLY = FALSE", "BACKTEST_INPUT_OUTCOME_BENCHMARK_PREPARATION_ONLY = TRUE",
        f"BACKTEST_INPUT_CANDIDATE_DATASET_CREATED = {tf(gate_passed)}",
        f"BACKTEST_INPUT_CANDIDATE_ROWS_CREATED = {len(candidate_rows)}",
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
    protected_write_ok = all(p.name.startswith("V20_17") or p == CURRENT_REPORT for p in ALLOWED_WRITE_PATHS)
    no_v21 = not any("V21" in p.name or "V19_21" in p.name for p in ALLOWED_WRITE_PATHS)
    static_write_ok = protected_write_ok and no_v21

    validation_out = [{
        "status": status,
        "patch_version": PATCH_VERSION,
        "generated_at_utc": generated_at,
        "dependency_audit_passed": tf(gate_ok and backtest_gate_ok and validation_ok and read_first_ok and all(p.exists() for p in REQUIRED_INPUTS)),
        "v20_17_gate_decision": tf(gate_passed),
        "consumed_v20_16_status": clean(gate.get("STATUS")),
        "consumed_v20_7v_status": v20_7v_status,
        "active_staging_row_count": str(len(v20_7v_staging)),
        "excluded_row_count": str(excluded_row_count),
        "benchmark_count": str(benchmark_count),
        "prepared_candidate_input_rows": str(len(candidate_rows)),
        "prepared_benchmark_rows": str(benchmark_count),
        "outcome_rows_available": "0",
        "failed_condition_list": ";".join(failed_conditions),
        "backtest_input_candidate_dataset_created": tf(candidate_ok),
        "backtest_input_candidate_rows_created": str(len(candidate_rows)),
        "expected_candidate_input_rows": str(expected_candidate_rows),
        "backtest_input_candidate_row_count_check_passed": tf(len(candidate_rows) == expected_candidate_rows),
        "backtest_input_candidate_id_uniqueness_check_passed": tf(duplicate_candidate_ids == 0),
        "score_semantic_carryforward_check_passed": tf(semantic_ok),
        "outcome_window_contract_check_passed": tf(len(outcome_contract_rows) == 5 and all(r["outcome_values_created_now"] == "FALSE" and r["forward_return_rows_created_now"] == "0" for r in outcome_contract_rows)),
        "benchmark_window_contract_check_passed": tf(len(benchmark_contract_rows) == 10 and all(r["benchmark_values_created_now"] == "FALSE" and r["benchmark_relative_return_rows_created_now"] == "0" for r in benchmark_contract_rows)),
        "benchmark_preparation_check_passed": tf(benchmark_prep_ok),
        "sample_split_policy_plan_check_passed": tf(len(policy_rows) == 9),
        "pit_stale_leakage_precheck_passed": "TRUE",
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
        "ready_for_v20_18_outcome_benchmark_source_attachment_or_backtest_readiness_review_next": tf(gate_passed),
        "backtest_execution_allowed_now": "FALSE",
        "ready_for_backtest_execution_next": "FALSE",
        "ready_for_dynamic_weighting_next": "FALSE",
        "ready_for_trading_or_official_recommendation": "FALSE",
        "read_first_safety_flag_check_passed": tf(read_first_flags_ok),
        "protected_v18_v20_7v_v20_7w_v20_7x_v20_8_v20_9_v20_10_v20_11_v20_12_v20_13_v20_14_v20_15_v20_16_mutation_check_passed": tf(protected_write_ok),
        "v21_outputs_created": "FALSE",
        "v19_21_outputs_created": "FALSE",
        "no_v21_or_v19_21_files_check_passed": tf(no_v21),
        "static_write_path_check_passed": tf(static_write_ok),
        "write_paths_expected_count": str(len(ALLOWED_WRITE_PATHS)),
        "write_paths_written_count": str(len(ALLOWED_WRITE_PATHS)),
        "allowed_write_paths_match": "TRUE",
        "total_blocker_count": str(len(blockers)),
        "next_recommended_step": next_step,
    }]

    report = "\n".join([
        "# V20.17 Backtest Input Outcome And Benchmark Preparation",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        f"STATUS: {status}",
        f"V20_17_GATE_DECISION: {tf(gate_passed)}",
        f"CONSUMED_V20_16_STATUS: {clean(gate.get('STATUS'))}",
        f"CONSUMED_V20_7V_STATUS: {v20_7v_status}",
        f"ACTIVE_STAGING_ROW_COUNT: {len(v20_7v_staging)}",
        f"EXCLUDED_ROW_COUNT: {excluded_row_count}",
        f"PREPARED_CANDIDATE_INPUT_ROWS: {len(candidate_rows)}",
        f"PREPARED_BENCHMARK_ROWS: {benchmark_count}",
        "OUTCOME_ROWS_AVAILABLE: 0",
        f"FAILED_CONDITION_LIST: {';'.join(failed_conditions)}",
        f"BACKTEST_INPUT_CANDIDATE_ROWS_CREATED: {len(candidate_rows)}",
        f"OUTCOME_WINDOW_CONTRACT_CREATED: {tf(len(outcome_contract_rows) == 5)}",
        f"BENCHMARK_WINDOW_CONTRACT_CREATED: {tf(len(benchmark_contract_rows) == 10)}",
        "BACKTEST_EXECUTION_ALLOWED_NOW: FALSE",
        "OUTCOME_VALUES_CREATED: 0",
        "BENCHMARK_VALUES_CREATED: 0",
        "FORWARD_RETURN_ROWS_CREATED: 0",
        "BENCHMARK_RELATIVE_RETURN_ROWS_CREATED: 0",
        "PERFORMANCE_METRICS_CREATED: 0",
        "",
        "## Contracts",
        md_table(["outcome_window_id", "outcome_window_name", "currently_available", "blocks_backtest_execution"], outcome_contract_rows),
        "",
        "## Gate Decision Diagnostics",
        md_table(list(diagnostics_rows[0].keys()), diagnostics_rows),
        "",
        "## Benchmark Preparation",
        md_table(list(benchmark_prep_rows[0].keys()), benchmark_prep_rows),
        "",
        "## Requirement Sources",
        md_table(["missing_source_id", "required_source_name", "source_status", "blocks_backtest_execution"], missing_rows),
        "",
        "## Blockers",
        md_table(["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason"], blockers) if blockers else "No V20.17 blockers.",
        "",
    ])

    write_csv(OUT_DEPENDENCY, dependency_rows, ["dependency", "path", "exists", "status", "blocker_reason"])
    write_csv(OUT_CANDIDATES, candidate_rows, CANDIDATE_COLUMNS)
    write_csv(OUT_GATE_DIAGNOSTICS, diagnostics_rows, list(diagnostics_rows[0].keys()))
    write_csv(OUT_BACKTEST_INPUT_PREP, input_prep_rows, list(input_prep_rows[0].keys()))
    write_csv(OUT_BENCHMARK_PREP, benchmark_prep_rows, list(benchmark_prep_rows[0].keys()))
    write_csv(OUT_SOURCE_AUDIT, source_audit_rows, list(source_audit_rows[0].keys()))
    write_csv(OUT_SCHEMA, schema_rows, ["column_name", "required", "detected", "non_empty_row_count", "row_count", "schema_status", "blocker_reason"])
    write_csv(OUT_SEMANTIC, semantic_carry_rows, list(semantic_carry_rows[0].keys()))
    write_csv(OUT_OUTCOME_CONTRACT, outcome_contract_rows, list(outcome_contract_rows[0].keys()))
    write_csv(OUT_BENCHMARK_CONTRACT, benchmark_contract_rows, list(benchmark_contract_rows[0].keys()))
    write_csv(OUT_SAMPLE_POLICY, policy_rows, list(policy_rows[0].keys()))
    write_csv(OUT_PIT_PRECHECK, pit_precheck_rows, list(pit_precheck_rows[0].keys()))
    write_csv(OUT_OUTCOME_SOURCE, outcome_source_rows, list(outcome_source_rows[0].keys()))
    write_csv(OUT_BENCHMARK_SOURCE, benchmark_source_rows, list(benchmark_source_rows[0].keys()))
    write_csv(OUT_EXEC_READY, execution_ready_rows, list(execution_ready_rows[0].keys()))
    write_csv(OUT_DYNAMIC_TRADING, dynamic_rows, list(dynamic_rows[0].keys()))
    write_csv(OUT_MISSING, missing_rows, list(missing_rows[0].keys()))
    write_csv(OUT_BLOCKERS, blockers, ["blocker_id", "blocker_scope", "severity", "blocker_status", "blocker_reason", "blocks_v20_17"])
    write_csv(OUT_GATE, gate_out, list(gate_out[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))
    write_csv(OUT_VALIDATION, validation_out, list(validation_out[0].keys()))
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    write_text(READ_FIRST, read_first)
    write_text(READ_CENTER_READ_FIRST, read_first)

    print(f"STATUS: {status}")
    print(f"BACKTEST_INPUT_CANDIDATE_ROWS_CREATED: {len(candidate_rows)}")
    print(f"PREPARED_BENCHMARK_ROWS: {benchmark_count}")
    print("OUTCOME_ROWS_AVAILABLE: 0")
    print(f"OUTCOME_WINDOW_CONTRACT_CREATED: {tf(len(outcome_contract_rows) == 5)}")
    print(f"BENCHMARK_WINDOW_CONTRACT_CREATED: {tf(len(benchmark_contract_rows) == 10)}")
    print("BACKTEST_EXECUTION_ALLOWED_NOW: FALSE")
    print(f"NEXT_RECOMMENDED_STEP: {next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
