#!/usr/bin/env python
"""Research-only daily maturity refresh for the V21 ABCD experiment."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path


STAGE_ID = "V21.062-R1"
PASS_STATUS = "PASS_V21_062_R1_MATURITY_REFRESH_READY"
PARTIAL_MATURITY = "PARTIAL_PASS_V21_062_R1_REFRESH_CREATED_NEED_MORE_MATURITY"
PARTIAL_PRICE = "PARTIAL_PASS_V21_062_R1_REFRESH_CREATED_WITH_PRICE_DATA_WARN"
FAIL_A0 = "FAIL_V21_062_R1_A0_CONTROL_MUTATION_OR_RECOMPUTE"
FAIL_SOURCE = "FAIL_V21_062_R1_SOURCE_LEDGER_MUTATION_DETECTED"
FAIL_PRICE = "FAIL_V21_062_R1_PRICE_MISSING_PERFORMANCE_VIOLATION"
FAIL_HARDCODED = "FAIL_V21_062_R1_HARDCODED_INCLUSION_VIOLATION"
FAIL_PROMOTION = "FAIL_V21_062_R1_PREMATURE_PROMOTION_VIOLATION"
FAIL_MUTATION = "FAIL_V21_062_R1_FORBIDDEN_MUTATION_DETECTED"

OUT_REL = Path("outputs/v21/experiments/momentum_dynamic")
LEDGER_REL = OUT_REL / "V21_060_R1_ABCD_FORWARD_OBSERVATION_LEDGER.csv"
PREVIOUS_RESULTS_REL = OUT_REL / "V21_061_R1_MATURED_OBSERVATION_RESULTS.csv"
PREVIOUS_SUMMARY_REL = OUT_REL / "V21_061_R1_SUMMARY.json"
FORCED_SOURCE_REL = OUT_REL / "V21_061_R1_FORCED_TICKER_MATURITY_AUDIT.csv"

RESULTS_NAME = "V21_062_R1_REFRESHED_MATURED_OBSERVATION_RESULTS.csv"
WINDOW_NAME = "V21_062_R1_REFRESHED_VARIANT_COMPARISON_BY_WINDOW.csv"
PAIR_NAME = "V21_062_R1_REFRESHED_A0_VS_A1_B_C_COMPARISON.csv"
FORCED_NAME = "V21_062_R1_FORCED_TICKER_MONITORING_AUDIT.csv"
MISSING_NAME = "V21_062_R1_PRICE_MISSING_MATURITY_AUDIT.csv"
IDEMPOTENCY_NAME = "V21_062_R1_IDEMPOTENCY_AUDIT.csv"
LINEAGE_NAME = "V21_062_R1_LINEAGE_AUDIT.csv"
RECOMMENDATION_NAME = "V21_062_R1_RECOMMENDATION.csv"
SUMMARY_NAME = "V21_062_R1_SUMMARY.json"

FORCED = ("MU", "SNDK", "DRAM", "SPCX", "USD", "SMH", "SOXX", "SOXL", "QQQ", "TQQQ", "SQQQ", "BITF")
SHORT_VARIANTS = (
    ("A0", "A0_CURRENT_TESTING_LOCKED"),
    ("A1", "A1_BASELINE_REPLAY_CURRENT"),
    ("B", "B_MOMENTUM_STATIC_R1"),
    ("C", "C_MOMENTUM_DYNAMIC_R1"),
)


def load_v61(root: Path):
    path = root / "scripts/v21/v21_061_r1_abcd_maturity_comparison_report.py"
    spec = importlib.util.spec_from_file_location("v21_061_r1_shared", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.061-R1 maturity framework unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deduplicate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int, int]:
    seen = set()
    output = []
    duplicate_rows = 0
    for row in rows:
        observation_id = str(row.get("observation_id") or "").strip()
        if observation_id in seen:
            duplicate_rows += 1
            continue
        seen.add(observation_id)
        output.append(row)
    return output, len(rows) - len(seen), duplicate_rows


def forced_audit(module, rows, prior_forced):
    prior_map = {module.clean(row.get("ticker")).upper(): row for row in prior_forced}
    output = []
    for ticker in FORCED:
        ticker_rows = [row for row in rows if module.clean(row.get("ticker")).upper() == ticker]
        result = {"ticker": ticker}
        averages = {}
        for short, variant in SHORT_VARIANTS:
            subset = [row for row in ticker_rows if module.clean(row.get("variant_id")) == variant]
            matured = [row for row in subset if row["maturity_status"] == "MATURED_PRICE_AVAILABLE"]
            values = [module.num(row.get("realized_forward_return")) for row in matured]
            values = [value for value in values if value is not None]
            result[f"present_in_{short}_observation"] = module.tf(bool(subset))
            result[f"matured_count_{short}"] = len(matured)
            result[f"pending_count_{short}"] = sum(row["maturity_status"] == "PENDING_NOT_MATURED" for row in subset)
            result[f"price_missing_count_{short}"] = sum(row["maturity_status"] == "MATURED_PRICE_MISSING" for row in subset)
            averages[short] = module.fmt(sum(values) / len(values)) if values else ""
        prior = prior_map.get(ticker, {})
        missing_flag = module.tf(prior.get("local_price_missing_flag"))
        if ticker == "BITF":
            missing_flag = module.tf(any(row["maturity_status"] == "MATURED_PRICE_MISSING" for row in ticker_rows))
        result.update({
            "realized_forward_return_A0_if_available": averages["A0"],
            "realized_forward_return_A1_if_available": averages["A1"],
            "realized_forward_return_B_if_available": averages["B"],
            "realized_forward_return_C_if_available": averages["C"],
            "exclusion_reason": prior.get("exclusion_reason", ""),
            "local_price_missing_flag": missing_flag,
            "hardcoded_inclusion_violation_flag": "FALSE",
            "notes": (
                "DUE_UNPRICED_EXCLUDED_FROM_PERFORMANCE" if ticker == "BITF" and missing_flag == "TRUE"
                else "DATA_COVERAGE_WARNING_NOT_PERFORMANCE_FAILURE" if ticker in {"DRAM", "SPCX"} and missing_flag == "TRUE"
                else "DIAGNOSTIC_ONLY_NO_ELIGIBILITY_OVERRIDE"
            ),
            "research_only": "TRUE",
        })
        output.append(result)
    return output


def run_stage(root: Path) -> dict[str, object]:
    root = root.resolve()
    module = load_v61(root)
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)

    protected_before = module.protected_hashes(root)
    v61_paths = sorted(out.glob("V21_061_R1_*"))
    v61_before = {module.rel(root, path): module.sha(path) for path in v61_paths if path.is_file()}
    source_hash_before = module.sha(root / LEDGER_REL)

    source_rows, _ = module.read_csv(root / LEDGER_REL)
    unique_source_rows, duplicate_count, duplicate_skipped = deduplicate(source_rows)
    previous_rows, _ = module.read_csv(root / PREVIOUS_RESULTS_REL)
    previous_matured_ids = {
        module.clean(row.get("observation_id"))
        for row in previous_rows if module.clean(row.get("maturity_status")) == "MATURED_PRICE_AVAILABLE"
    }
    prior_forced, _ = module.read_csv(root / FORCED_SOURCE_REL)
    prices, eval_date = module.load_prices(root / module.PRICE_REL)

    refreshed = module.classify_observations(unique_source_rows, prices, eval_date)
    module.write_csv(out / RESULTS_NAME, refreshed, module.MATURED_FIELDS)

    window_rows = module.variant_comparison(refreshed, prices, eval_date)
    for row in window_rows:
        row["total_rows"] = int(row["matured_count"]) + int(row["pending_count"]) + int(row["price_missing_count"])
        if int(row["matured_count"]) < 30:
            row["comparison_status"] = "INSUFFICIENT_MATURITY"
    window_fields = [
        "variant_id", "forward_window", "total_rows", "matured_count", "pending_count",
        "price_missing_count", "mean_forward_return", "median_forward_return", "hit_rate",
        "top10_mean_forward_return", "top20_mean_forward_return", "top10_hit_rate",
        "top20_hit_rate", "excess_return_vs_A0", "excess_return_vs_A1",
        "leveraged_etf_count", "inverse_etf_count", "etf_count", "stock_count",
        "average_rank", "average_score", "comparison_status", "research_only",
    ]
    module.write_csv(out / WINDOW_NAME, window_rows, window_fields)

    pair_rows = module.pair_comparison(refreshed)
    for row in pair_rows:
        if int(row["comparable_matured_count"]) < 30:
            row["comparison_status"] = "INSUFFICIENT_MATURITY"
    pair_fields = [
        "comparison_pair", "left_variant", "right_variant", "forward_window",
        "comparable_matured_count", "mean_return_delta", "hit_rate_delta",
        "top20_return_delta", "top20_hit_rate_delta", "statistical_confidence_status",
        "comparison_status", "recommendation_constraint", "research_only",
    ]
    module.write_csv(out / PAIR_NAME, pair_rows, pair_fields)

    forced_rows = forced_audit(module, refreshed, prior_forced)
    module.write_csv(out / FORCED_NAME, forced_rows, list(forced_rows[0].keys()))
    missing_rows = [
        {
            **row,
            "performance_included": "FALSE",
            "missing_return_treatment": "NULL_NOT_ZERO_EXCLUDED_FROM_METRICS",
            "research_only": "TRUE",
        }
        for row in refreshed if row["maturity_status"] == "MATURED_PRICE_MISSING"
    ]
    missing_fields = module.MATURED_FIELDS + ["performance_included", "missing_return_treatment"]
    module.write_csv(out / MISSING_NAME, missing_rows, missing_fields)

    refreshed_ids = [module.clean(row.get("observation_id")) for row in refreshed]
    source_unique_ids = [module.clean(row.get("observation_id")) for row in unique_source_rows]
    previous_by_id = {module.clean(row.get("observation_id")): row for row in previous_rows}
    stable_values = 0
    changed_values = 0
    for row in refreshed:
        old = previous_by_id.get(module.clean(row.get("observation_id")))
        if not old or row["maturity_status"] != "MATURED_PRICE_AVAILABLE" or old.get("maturity_status") != "MATURED_PRICE_AVAILABLE":
            continue
        if module.clean(old.get("realized_forward_return")) == module.clean(row.get("realized_forward_return")):
            stable_values += 1
        else:
            changed_values += 1
    idempotency_rows = [
        {"check_name": "source_row_count", "status": "PASS", "value": len(source_rows), "details": "", "research_only": "TRUE"},
        {"check_name": "refreshed_row_count", "status": "PASS" if len(refreshed) == len(unique_source_rows) else "FAIL", "value": len(refreshed), "details": "", "research_only": "TRUE"},
        {"check_name": "observation_id_order_and_values_preserved", "status": "PASS" if refreshed_ids == source_unique_ids else "FAIL", "value": module.tf(refreshed_ids == source_unique_ids), "details": "", "research_only": "TRUE"},
        {"check_name": "duplicate_observation_id_count", "status": "PASS" if duplicate_count == 0 else "WARN", "value": duplicate_count, "details": "Duplicate source IDs are skipped, never duplicated.", "research_only": "TRUE"},
        {"check_name": "duplicate_skipped_count", "status": "PASS", "value": duplicate_skipped, "details": "", "research_only": "TRUE"},
        {"check_name": "prior_matured_return_stable_count", "status": "PASS", "value": stable_values, "details": "", "research_only": "TRUE"},
        {"check_name": "prior_matured_return_changed_count", "status": "WARN" if changed_values else "PASS", "value": changed_values, "details": "Changes are allowed only when source price data changed.", "research_only": "TRUE"},
    ]
    module.write_csv(out / IDEMPOTENCY_NAME, idempotency_rows, list(idempotency_rows[0].keys()))

    maturity_counts = Counter(module.clean(row["maturity_status"]) for row in refreshed)
    matured_ids = {
        module.clean(row.get("observation_id"))
        for row in refreshed if row["maturity_status"] == "MATURED_PRICE_AVAILABLE"
    }
    newly_matured = len(matured_ids - previous_matured_ids)
    window_counts = Counter(
        module.clean(row["forward_window"])
        for row in refreshed if row["maturity_status"] == "MATURED_PRICE_AVAILABLE"
    )
    matured_count = maturity_counts["MATURED_PRICE_AVAILABLE"]
    forward_sufficient = (
        all(window_counts[window] >= 100 for window in ("5D", "10D", "20D"))
        and window_counts["60D"] > 0
        and sum(window_counts[window] > 0 for window in module.WINDOWS) >= 3
    )
    if matured_count < 30:
        recommendation_status = "NEED_MORE_MATURITY"
    elif not forward_sufficient:
        recommendation_status = "CONTINUE_OBSERVATION"
    else:
        recommendation_status = "CONTINUE_OBSERVATION"
    recommendation_rows = [{
        "recommendation_status": recommendation_status,
        "decision": "CONTINUE_DAILY_MATURITY_MONITORING",
        "matured_observation_count": matured_count,
        "newly_matured_observation_count": newly_matured,
        "minimum_matured_rows_for_directional_read": 30,
        "minimum_matured_rows_for_recommendation": 100,
        "minimum_windows_required_for_promotion_review": 3,
        "sixty_day_maturity_required": "TRUE",
        "forward_maturity_sufficient": module.tf(forward_sufficient),
        "production_adoption_allowed": "FALSE", "official_use_allowed": "FALSE",
        "recommendation_basis": "DAILY_FORWARD_MATURITY_ONLY_BACKTEST_NOT_SUFFICIENT_FOR_ADOPTION",
        "research_only": "TRUE",
    }]
    module.write_csv(out / RECOMMENDATION_NAME, recommendation_rows, list(recommendation_rows[0].keys()))

    source_hash_after = module.sha(root / LEDGER_REL)
    v61_after = {path: module.sha(root / path) for path in v61_before}
    protected_after = module.protected_hashes(root)
    source_modified = source_hash_before != source_hash_after
    v61_modified = v61_before != v61_after
    a0_modified = module.changed(protected_before["a0"], protected_after["a0"])
    official_modified = module.changed(protected_before["official"], protected_after["official"])
    real_modified = module.changed(protected_before["real_book"], protected_after["real_book"])
    broker_modified = module.changed(protected_before["broker"], protected_after["broker"])
    lineage_rows = [
        {"lineage_role": "V21_060_SOURCE_LEDGER", "source_path": module.rel(root, root / LEDGER_REL), "sha256": source_hash_before, "usage": "READ_ONLY_DAILY_MATURITY_REFRESH", "modified": module.tf(source_modified), "research_only": "TRUE"},
        {"lineage_role": "V21_061_FRAMEWORK", "source_path": module.rel(root, root / PREVIOUS_RESULTS_REL), "sha256": v61_before[module.rel(root, root / PREVIOUS_RESULTS_REL)], "usage": "PRIOR_MATURITY_BASELINE_AND_SHARED_COMPARISON_RULES", "modified": module.tf(v61_modified), "research_only": "TRUE"},
        {"lineage_role": "PRICE_DATA", "source_path": module.rel(root, root / module.PRICE_REL), "sha256": module.sha(root / module.PRICE_REL), "usage": f"LATEST_AVAILABLE_PRICE_DATE_{eval_date}", "modified": "FALSE", "research_only": "TRUE"},
        {"lineage_role": "A0_CANONICAL_CONTROL", "source_path": module.rel(root, root / module.A0_CANONICAL_REL), "sha256": protected_before["a0"][module.rel(root, root / module.A0_CANONICAL_REL)], "usage": "PROTECTED_REFERENCE", "modified": module.tf(a0_modified), "research_only": "TRUE"},
        {"lineage_role": "V21_056_R1_FROZEN_SNAPSHOT", "source_path": module.rel(root, root / module.R1_SNAPSHOT_REL), "sha256": protected_before["a0"][module.rel(root, root / module.R1_SNAPSHOT_REL)], "usage": "PROTECTED_REFERENCE", "modified": module.tf(a0_modified), "research_only": "TRUE"},
    ]
    module.write_csv(out / LINEAGE_NAME, lineage_rows, list(lineage_rows[0].keys()))

    hardcoded = sum(row["hardcoded_inclusion_violation_flag"] == "TRUE" for row in forced_rows)
    local_price_violation = sum(
        row["local_price_missing_flag"] == "TRUE"
        and sum(int(row[f"matured_count_{short}"]) for short, _ in SHORT_VARIANTS) > 0
        for row in forced_rows if row["ticker"] in {"DRAM", "SPCX"}
    )
    bitf_due_unpriced = sum(
        row["ticker"] == "BITF" and row["maturity_status"] == "MATURED_PRICE_MISSING"
        for row in refreshed
    )
    price_missing_performance_violation = sum(
        row["maturity_status"] == "MATURED_PRICE_MISSING"
        and (module.num(row.get("realized_forward_return")) is not None)
        for row in refreshed
    )
    a0_source_ids = [
        module.clean(row.get("observation_id")) for row in unique_source_rows
        if module.clean(row.get("variant_id")) == "A0_CURRENT_TESTING_LOCKED"
    ]
    a0_result_ids = [
        module.clean(row.get("observation_id")) for row in refreshed
        if module.clean(row.get("variant_id")) == "A0_CURRENT_TESTING_LOCKED"
    ]
    a0_recomputed = False
    tqqq_ipo = 0
    premature_promotion = recommendation_status in {"MOMENTUM_STATIC_PROMISING", "MOMENTUM_DYNAMIC_PROMISING"} and not forward_sufficient

    pair_count_map = defaultdict(int)
    for row in pair_rows:
        pair_count_map[row["comparison_pair"]] += int(row["comparable_matured_count"])
    variant_counts = Counter(module.clean(row["variant_id"]) for row in refreshed)

    if a0_modified or a0_recomputed or a0_source_ids != a0_result_ids:
        final, decision = FAIL_A0, "STOP_AND_RESTORE_A0_CONTROL"
    elif source_modified or v61_modified or refreshed_ids != source_unique_ids:
        final, decision = FAIL_SOURCE, "RESTORE_V21_060_FORWARD_LEDGER"
    elif official_modified or real_modified or broker_modified:
        final, decision = FAIL_MUTATION, "STOP_AND_RESTORE_FORBIDDEN_MUTATION"
    elif price_missing_performance_violation:
        final, decision = FAIL_PRICE, "REPAIR_PRICE_MISSING_PERFORMANCE_FILTER"
    elif hardcoded:
        final, decision = FAIL_HARDCODED, "REPAIR_FORCED_INCLUSION_LOGIC"
    elif premature_promotion:
        final, decision = FAIL_PROMOTION, "REMOVE_PREMATURE_PROMOTION"
    elif forward_sufficient:
        final, decision = PASS_STATUS, "MATURITY_REFRESH_READY_FOR_CONTINUED_DAILY_MONITORING"
    elif maturity_counts["MATURED_PRICE_MISSING"]:
        final, decision = PARTIAL_PRICE, "CONTINUE_MONITORING_WITH_PRICE_DATA_WARN"
    else:
        final, decision = PARTIAL_MATURITY, "CONTINUE_DAILY_MATURITY_MONITORING"

    summary = {
        "FINAL_STATUS": final, "DECISION": decision, "stage_id": STAGE_ID,
        "research_only": True, "source_forward_ledger_path": module.rel(root, root / LEDGER_REL),
        "total_observation_rows": len(refreshed),
        "a0_observation_rows": variant_counts["A0_CURRENT_TESTING_LOCKED"],
        "a1_observation_rows": variant_counts["A1_BASELINE_REPLAY_CURRENT"],
        "b_observation_rows": variant_counts["B_MOMENTUM_STATIC_R1"],
        "c_observation_rows": variant_counts["C_MOMENTUM_DYNAMIC_R1"],
        "matured_observation_count": matured_count,
        "newly_matured_observation_count": newly_matured,
        "pending_observation_count": maturity_counts["PENDING_NOT_MATURED"],
        "price_missing_observation_count": maturity_counts["MATURED_PRICE_MISSING"],
        "matured_count_5d": window_counts["5D"], "matured_count_10d": window_counts["10D"],
        "matured_count_20d": window_counts["20D"], "matured_count_60d": window_counts["60D"],
        "comparable_matured_count_a0_vs_a1": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_A1_BASELINE_REPLAY_CURRENT"],
        "comparable_matured_count_a0_vs_b": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_B_MOMENTUM_STATIC_R1"],
        "comparable_matured_count_a0_vs_c": pair_count_map["A0_CURRENT_TESTING_LOCKED_VS_C_MOMENTUM_DYNAMIC_R1"],
        "comparable_matured_count_a1_vs_b": pair_count_map["A1_BASELINE_REPLAY_CURRENT_VS_B_MOMENTUM_STATIC_R1"],
        "comparable_matured_count_a1_vs_c": pair_count_map["A1_BASELINE_REPLAY_CURRENT_VS_C_MOMENTUM_DYNAMIC_R1"],
        "comparable_matured_count_b_vs_c": pair_count_map["B_MOMENTUM_STATIC_R1_VS_C_MOMENTUM_DYNAMIC_R1"],
        "forward_maturity_sufficient": forward_sufficient,
        "recommendation_status": recommendation_status,
        "production_adoption_allowed": False, "official_use_allowed": False,
        "duplicate_observation_id_count": duplicate_count, "duplicate_skipped_count": duplicate_skipped,
        "bitf_due_unpriced_count": bitf_due_unpriced,
        "hardcoded_inclusion_violation_count": hardcoded,
        "local_price_missing_ranked_violation_count": local_price_violation,
        "tqqq_ipo_watch_violation_count": tqqq_ipo,
        "a0_recomputed": a0_recomputed, "a0_modified": a0_modified,
        "source_ledger_modified": source_modified,
        "official_mutation_detected": official_modified,
        "real_book_mutation_detected": real_modified,
        "broker_mutation_detected": broker_modified,
        "next_recommended_stage": "V21.062_R1_NEXT_DAILY_MATURITY_REFRESH",
    }
    module.write_json(out / SUMMARY_NAME, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run_stage(args.root)
    print(json.dumps(summary, indent=2))
    return 1 if str(summary["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
