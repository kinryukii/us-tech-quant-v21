"""Incremental, read-only strategy/expert solver-quality evidence.

Only COMPLETE batches are scanned. No account, policy, optimizer, predictive,
learning, or performance-ranking implementation is imported or executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "analysis"
CACHE = OUT / "solver_quality_cache"
VERSION = "ALL_SOURCE_STATES_STRATEGY_EXPERT_RESIDUAL_V1"
YEARS = [2025, 2026]
SIGNAL_ENDS = {2025: "2025-12-29", 2026: "2026-09-22"}
CERTIFIED = {"SOLVED_CASH_CERTIFICATE", "SOLVED_TOLERANCE"}
NUMERICAL = CERTIFIED | {"APPROXIMATE_BUDGET"}
COORDINATOR = "TARGET_EXPERT_FUSION"
MISSING_STATUS = "__DIAGNOSTIC_MISSING_SOURCE_STATUS__"
OUTPUTS = ["SOLVER_QUALITY_BY_STRATEGY.csv", "SOLVER_QUALITY_BY_TARGET_EXPERT.csv", "SOLVER_QUALITY_STATUS_SUPPORT.csv"]
RECEIPT = OUT / "SOLVER_QUALITY_RECEIPT.json"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def numeric_empty():
    return {"records": 0, "finite_records": 0, "missing_records": 0, "nonfinite_records": 0, "nonnumeric_records": 0,
            "sum": 0., "min": None, "max": None}


def numeric_add(state, value):
    state["records"] += 1
    if value is None:
        state["missing_records"] += 1
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        state["nonnumeric_records"] += 1
        return
    number = float(value)
    if not math.isfinite(number):
        state["nonfinite_records"] += 1
        return
    state["finite_records"] += 1
    state["sum"] += number
    state["min"] = number if state["min"] is None else min(state["min"], number)
    state["max"] = number if state["max"] is None else max(state["max"], number)


def numeric_summary(state):
    return {key: state[key] for key in ["records", "finite_records", "missing_records", "nonfinite_records", "nonnumeric_records", "min", "max"]} | {
        "mean": state["sum"]/state["finite_records"] if state["finite_records"] else None}


def empty_accumulator():
    return {"records": 0, "source_status_counts": {}, "missing_source_status_records": 0, "status_stats": {},
            "logged_residual": numeric_empty(), "logged_objective": numeric_empty(), "numerical_residual": numeric_empty(),
            "numerical_objective": numeric_empty(), "approximate_residual": numeric_empty(), "certificate_residual_violations": 0,
            "negative_numerical_residual_records": 0}


def observe(state, status, residual, objective=None, expert=False):
    state["records"] += 1
    source_valid = isinstance(status, str) and bool(status)
    status_key = status if source_valid else MISSING_STATUS
    if source_valid:
        state["source_status_counts"][status] = state["source_status_counts"].get(status, 0)+1
    else:
        state["missing_source_status_records"] += 1
    group = state["status_stats"].setdefault(status_key, {"records": 0, "residual": numeric_empty(), "objective": numeric_empty()})
    group["records"] += 1
    numeric_add(group["residual"], residual)
    numeric_add(state["logged_residual"], residual)
    if not expert:
        numeric_add(group["objective"], objective)
        numeric_add(state["logged_objective"], objective)
    if status_key in NUMERICAL:
        numeric_add(state["numerical_residual"], residual)
        if not expert:
            numeric_add(state["numerical_objective"], objective)
        valid_number = isinstance(residual, (int, float)) and not isinstance(residual, bool) and math.isfinite(float(residual))
        if valid_number and residual < -1e-12:
            state["negative_numerical_residual_records"] += 1
        if status_key in CERTIFIED and (not valid_number or residual < -1e-12 or residual > 1e-5+1e-10):
            state["certificate_residual_violations"] += 1
    if status_key == "APPROXIMATE_BUDGET":
        numeric_add(state["approximate_residual"], residual)


def fraction(numerator, denominator):
    return numerator/denominator if denominator else None


def add_numeric_columns(row, prefix, state):
    for key, value in numeric_summary(state).items():
        row[prefix + "_" + key] = value


def accumulator_columns(state, prefix, expert=False):
    statuses = state["source_status_counts"]
    total = state["records"]
    coordination = statuses.get(COORDINATOR, 0)
    denominator = total if expert else total-coordination
    certified = sum(statuses.get(status, 0) for status in CERTIFIED)
    row = {
        prefix+"_observed_records": total, prefix+"_source_status_counts": json.dumps(statuses, sort_keys=True),
        prefix+"_missing_source_status_records": state["missing_source_status_records"],
        prefix+"_coordination_records": coordination, prefix+"_certificate_denominator_records": denominator,
        prefix+"_certificate_denominator_definition": "All expected expert slots on observed target-account decisions, including missing status" if expert else "All observed outer decision records except TARGET_EXPERT_FUSION coordination; failures/missing statuses remain included",
        prefix+"_solved_cash_certificate_records": statuses.get("SOLVED_CASH_CERTIFICATE", 0),
        prefix+"_solved_tolerance_records": statuses.get("SOLVED_TOLERANCE", 0), prefix+"_certified_status_records": certified,
        prefix+"_certified_fraction": fraction(certified, denominator),
        prefix+"_cash_certificate_fraction": fraction(statuses.get("SOLVED_CASH_CERTIFICATE", 0), denominator),
        prefix+"_solved_tolerance_fraction": fraction(statuses.get("SOLVED_TOLERANCE", 0), denominator),
        prefix+"_approximate_budget_records": statuses.get("APPROXIMATE_BUDGET", 0),
        prefix+"_approximate_budget_fraction": fraction(statuses.get("APPROXIMATE_BUDGET", 0), denominator),
        prefix+"_source_status_counts_sum": sum(statuses.values()),
        prefix+"_certificate_residual_violations": state["certificate_residual_violations"],
        prefix+"_negative_numerical_residual_records": state["negative_numerical_residual_records"],
    }
    for kind in ["logged_residual", "numerical_residual", "approximate_residual"]:
        add_numeric_columns(row, prefix+"_"+kind, state[kind])
    if not expert:
        for kind in ["logged_objective", "numerical_objective"]:
            add_numeric_columns(row, prefix+"_"+kind, state[kind])
    summaries = {}
    for status, stats in state["status_stats"].items():
        summaries[status] = {"records": stats["records"], "logged_residual": numeric_summary(stats["residual"]),
            "residual_is_numerical_optimality_measure": status in NUMERICAL,
            "coordination_residual_is_placeholder": status == COORDINATOR}
        if not expert:
            summaries[status]["logged_objective"] = numeric_summary(stats["objective"])
    row[prefix+"_all_status_support_json"] = json.dumps(summaries, sort_keys=True, allow_nan=False)
    return row


def load_registration():
    registry = json.loads((ROOT/"REGISTRY.json").read_text(encoding="utf-8"))
    paths = registry["strategies"]
    require(len(paths) == 11088 and len({path["strategy"] for path in paths}) == 11088, "REGISTERED_STRATEGY_LIST_CHANGED")
    targets = [path for path in paths if path["target_fusion"] != "none"]
    require(len(targets) == 288 and all(len(path["members"]) == 13 for path in targets), "REGISTERED_TARGET_EXPERT_GRID_CHANGED")
    require(all(path["members"] == targets[0]["members"] for path in targets), "TARGET_EXPERT_MEMBERS_CHANGED")
    dates = {}
    for year, prefix in [(2025, "pre"), (2026, "test")]:
        calendar = pq.read_table(ROOT/f"data/{prefix}_calendar.parquet", columns=["trade_date"]).to_pandas()
        index = pd.DatetimeIndex(pd.to_datetime(calendar.trade_date))
        dates[year] = [str(day.date()) for day in index[(index.year == year)&(index <= pd.Timestamp(SIGNAL_ENDS[year]))]]
        require(len(dates[year]) == (248 if year == 2025 else 181), "REGISTERED_SIGNAL_DATE_SUPPORT_CHANGED")
    return paths, {path["strategy"]: path for path in paths}, targets[0]["members"], dates


def batch_sources(batch):
    parts = sorted((batch/"raw_model_outputs").glob("part_*.parquet"))
    require(parts, "COMPLETE_BATCH_HAS_NO_RAW_OUTPUT_PARTS:"+str(batch))
    files = [batch/"COMPLETE.json", batch/"metadata.json", batch/"POLICY_RECEIPT.json"]+parts
    return parts, {path.relative_to(ROOT).as_posix(): sha(path) for path in files}


def process_batch(year, batch, registration, members, dates, code_hash):
    started = time.perf_counter()
    parts, sources = batch_sources(batch)
    complete = json.loads((batch/"COMPLETE.json").read_text(encoding="utf-8"))
    metadata = json.loads((batch/"metadata.json").read_text(encoding="utf-8"))
    policy = json.loads((batch/"POLICY_RECEIPT.json").read_text(encoding="utf-8"))
    ids = complete["strategies"]
    require(int(complete["year"]) == year and len(ids) == len(set(ids)) and set(ids).issubset(registration), "COMPLETE_BATCH_REGISTRATION_MISMATCH")
    require(set(metadata["strategy_ids"]) == set(ids), "METADATA_STRATEGY_KEYS_CHANGED")
    require(complete["metadata_sha256"] == sources[(batch/"metadata.json").relative_to(ROOT).as_posix()], "SEALED_METADATA_HASH_MISMATCH")
    require(metadata["signal_end"] == SIGNAL_ENDS[year] and metadata["signal_start"] == dates[year][0], "RAW_SOLVER_SIGNAL_PERIOD_CHANGED")
    require(complete["new_fit_calls"] == policy["fit_calls"] == 0, "SOURCE_BATCH_HAS_LEARNING_CALLS")
    outer = {strategy: empty_accumulator() for strategy in ids}
    expert = {strategy: {member: empty_accumulator() for member in members} for strategy in ids if registration[strategy]["target_fusion"] != "none"}
    expert_pooled = {strategy: empty_accumulator() for strategy in expert}
    masks = {strategy: 0 for strategy in ids}
    date_index = {day: i for i, day in enumerate(dates[year])}
    outer_counts, expert_counts = Counter(), Counter()
    row_count = 0
    missing_payloads = 0
    for part in parts:
        file = pq.ParquetFile(part)
        for chunk in file.iter_batches(batch_size=8192, columns=["strategy_id", "signal_date", "raw_model_outputs_json"]):
            data = chunk.to_pydict()
            for strategy, signal, text in zip(data["strategy_id"], data["signal_date"], data["raw_model_outputs_json"]):
                require(strategy in outer, "UNREGISTERED_RAW_SOLVER_STRATEGY")
                day = str(signal.date())
                require(day in date_index, "RAW_SOLVER_DATE_OUTSIDE_REGISTERED_PERIOD")
                bit = 1 << date_index[day]
                require(not masks[strategy]&bit, "DUPLICATED_STRATEGY_SIGNAL_SOLVER_RECORD")
                masks[strategy] |= bit
                payload = json.loads(text) if text is not None else None
                if not isinstance(payload, dict):
                    payload = {}
                    missing_payloads += 1
                status, residual, objective = payload.get("solver_status"), payload.get("solver_residual"), payload.get("objective")
                observe(outer[strategy], status, residual, objective)
                if isinstance(status, str) and status:
                    outer_counts[status] += 1
                if strategy in expert:
                    statuses, residuals = payload.get("expert_solver_statuses", {}), payload.get("expert_solver_residuals", {})
                    require(isinstance(statuses, dict) and isinstance(residuals, dict), "MALFORMED_TARGET_EXPERT_DICTIONARY")
                    require(set(statuses).issubset(members) and set(residuals).issubset(members), "UNREGISTERED_TARGET_EXPERT_MEMBER")
                    for member in members:
                        expert_status, expert_residual = statuses.get(member), residuals.get(member)
                        observe(expert[strategy][member], expert_status, expert_residual, expert=True)
                        observe(expert_pooled[strategy], expert_status, expert_residual, expert=True)
                        if isinstance(expert_status, str) and expert_status:
                            expert_counts[expert_status] += 1
                row_count += 1
    expected_mask = (1 << len(dates[year]))-1
    require(all(mask == expected_mask for mask in masks.values()), "COMPLETE_BATCH_STRATEGY_SIGNAL_KEYS_INCOMPLETE")
    require(row_count == len(ids)*len(dates[year]), "RAW_SOLVER_RECORD_COUNT_CHANGED")
    require(len(parts) == metadata["table_parts"]["raw_model_outputs"] and row_count == metadata["table_rows"]["raw_model_outputs"], "RAW_SOLVER_TABLE_METADATA_MISMATCH")
    require(dict(outer_counts) == policy["solver_counts"], "POLICY_COUNTS_DO_NOT_CLOSE_WITH_RAW_STRATEGIES")
    require({path: sha(ROOT/path) for path in sources} == sources, "SEALED_RAW_SOLVER_SOURCE_CHANGED_DURING_READ")
    record = {"cache_version": VERSION, "producer_sha256": code_hash, "year": year, "batch": batch.name,
        "status": "PASS_COMPLETE_RAW_KEYS_AND_POLICY_COUNTS", "strategies": ids, "signal_days": len(dates[year]),
        "source_sha256": sources, "raw_records": row_count, "missing_raw_payload_records": missing_payloads,
        "outer_source_status_counts": dict(outer_counts), "expert_source_status_counts": dict(expert_counts),
        "outer": outer, "expert": expert, "expert_pooled": expert_pooled, "seconds": round(time.perf_counter()-started, 6)}
    cache_path = CACHE/f"{year}_{batch.name}.json"
    atomic_json(cache_path, record)
    print(json.dumps({"batch": batch.name, "year": year, "quality_records": row_count, "strategy_keys": len(ids), "seconds": record["seconds"]}), flush=True)
    return record


def independent_closure(record):
    path = ROOT/f"audits/verification_cache/{record['year']}_{record['batch']}.json"
    if not path.exists():
        return {"status": "PENDING_INDEPENDENT_BATCH_VERIFICATION"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "PENDING_INDEPENDENT_BATCH_VERIFICATION_WRITE"}
    require(value.get("status") == "PASS", "INDEPENDENT_BATCH_CACHE_NOT_PASS")
    require(value["verifier_code_sha256"] == sha(ROOT/"independent_verify.py"), "INDEPENDENT_VERIFIER_CODE_HASH_CHANGED")
    base = f"results/{record['year']}/{record['batch']}/"
    require(all(value["ledger_sha256"].get(relative.removeprefix(base)) == digest for relative, digest in record["source_sha256"].items()), "INDEPENDENT_RAW_SOLVER_SOURCE_BINDING_MISMATCH")
    result = value["result"]
    require(result["solver_status_counts"] == record["outer_source_status_counts"], "INDEPENDENT_OUTER_SOLVER_COUNTS_MISMATCH")
    require(result["target_expert_solver_status_counts"] == record["expert_source_status_counts"], "INDEPENDENT_EXPERT_SOLVER_COUNTS_MISMATCH")
    return {"status": "PASS_SAME_SOURCE_OUTER_AND_EXPERT_COUNTS", "path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)}


def long_status_rows(year, strategy, layer, accumulator, member=None):
    rows = []
    for status, values in accumulator["status_stats"].items():
        row = {"year": year, "strategy": strategy, "layer": layer, "expert_member": member, "source_status": status,
               "observed_status_records": values["records"], "coordination_placeholder": status == COORDINATOR,
               "numerical_solver_status": status in NUMERICAL}
        add_numeric_columns(row, "logged_residual", values["residual"])
        if layer == "outer":
            add_numeric_columns(row, "logged_objective", values["objective"])
        rows.append(row)
    return rows


def snapshot(paths, members, dates, batches, code_hash, force_sha=False):
    expected = {(year, path["strategy"]) for year in YEARS for path in paths}
    expected_experts = {(year, path["strategy"], member) for year in YEARS for path in paths if path["target_fusion"] != "none" for member in members}
    require(len(expected) == 22176 and len(expected_experts) == 7488, "EXPECTED_QUALITY_GRID_CHANGED")
    observed = {}
    sources = {relative: sha(ROOT/relative) for relative in [Path(__file__).name, "REGISTRY.json", "independent_verify.py", "FREEZE.json", "data/pre_calendar.parquet", "data/test_calendar.parquet"]}
    require(sources[Path(__file__).name] == code_hash, "SOLVER_ANALYSIS_CODE_CHANGED_WHILE_WATCHING")
    closures = []
    for record in batches.values():
        if force_sha:
            batch = ROOT/f"results/{record['year']}/{record['batch']}"
            _, current_sources = batch_sources(batch)
            require(current_sources == record["source_sha256"], "SEALED_SOLVER_SOURCE_CHANGED")
        sources.update(record["source_sha256"])
        closure = independent_closure(record)
        closures.append({"year": record["year"], "batch": record["batch"], **closure})
        if closure.get("path"):
            sources[closure["path"]] = closure["sha256"]
        for strategy in record["strategies"]:
            key = (record["year"], strategy)
            require(key not in observed, "STRATEGY_PRESENT_IN_MULTIPLE_COMPLETE_BATCHES")
            observed[key] = (record, closure)
    rows, expert_rows, status_rows = [], [], []
    all_missing_status, certificate_bad, negative_residual = 0, 0, 0
    for year in YEARS:
        for path in paths:
            strategy = path["strategy"]
            found = observed.get((year, strategy))
            record, closure = found if found else (None, {"status": "PENDING_UNOBSERVED_BATCH"})
            accumulator = record["outer"][strategy] if record else empty_accumulator()
            row = {"year": year, **{key: value for key, value in path.items() if key != "members"},
                   "observation_status": "OBSERVED_COMPLETE_BATCH" if record else "PENDING_NO_COMPLETE_RAW_BATCH_OBSERVATION",
                   "source_batch": record["batch"] if record else None, "counts_are_observed": record is not None,
                   "expected_signal_records": len(dates[year]), "unobserved_expected_signal_records": len(dates[year])-accumulator["records"],
                   "independent_counts_closure": closure["status"],
                   "residual_unit": "FW_SUPPORT_GAP" if path["optimizer"] == "cvar" else "PROXIMAL_FIXED_POINT_RESIDUAL",
                   "outer_coordination_zero_is_not_optimality_residual": path["target_fusion"] != "none",
                   "component_reference_solver_quality_is_logged": False}
            row.update(accumulator_columns(accumulator, "outer"))
            if record:
                status_rows.extend(long_status_rows(year, strategy, "outer", accumulator))
            all_missing_status += accumulator["missing_source_status_records"]
            certificate_bad += accumulator["certificate_residual_violations"]
            negative_residual += accumulator["negative_numerical_residual_records"]
            if path["target_fusion"] != "none":
                pooled = record["expert_pooled"][strategy] if record else empty_accumulator()
                row["expected_expert_members"] = len(members)
                row["expected_expert_slots_from_observed_target_decisions"] = accumulator["records"]*len(members)
                row.update(accumulator_columns(pooled, "expert_aggregate", expert=True))
                for member in members:
                    state = record["expert"][strategy][member] if record else empty_accumulator()
                    detail = {"year": year, "target_strategy": strategy, "expert_member": member, "risk": path["risk"],
                              "optimizer": path["optimizer"], "axis": path["axis"], "target_fusion": path["target_fusion"],
                              "observation_status": row["observation_status"], "counts_are_observed": record is not None,
                              "source_batch": row["source_batch"], "expected_signal_records": len(dates[year]),
                              "unobserved_expected_signal_records": len(dates[year])-state["records"],
                              "independent_counts_closure": closure["status"], "expert_objective_not_logged": True,
                              "residual_unit": row["residual_unit"]}
                    detail.update(accumulator_columns(state, "expert", expert=True))
                    expert_rows.append(detail)
                    if record:
                        status_rows.extend(long_status_rows(year, strategy, "target_expert", state, member))
                    all_missing_status += state["missing_source_status_records"]
                    certificate_bad += state["certificate_residual_violations"]
                    negative_residual += state["negative_numerical_residual_records"]
            rows.append(row)
    strategy_frame, expert_frame = pd.DataFrame(rows), pd.DataFrame(expert_rows)
    require(set(zip(strategy_frame.year, strategy_frame.strategy)) == expected and not strategy_frame.duplicated(["year", "strategy"]).any(), "QUALITY_STRATEGY_EXACT_KEYS_FAILED")
    require(set(zip(expert_frame.year, expert_frame.target_strategy, expert_frame.expert_member)) == expected_experts and not expert_frame.duplicated(["year", "target_strategy", "expert_member"]).any(), "QUALITY_EXPERT_EXACT_KEYS_FAILED")
    observed_expert_rows = int(expert_frame.counts_are_observed.sum())
    coverage_complete = len(observed) == len(expected) and observed_expert_rows == len(expected_experts)
    closure_complete = bool(closures) and all(value["status"] == "PASS_SAME_SOURCE_OUTER_AND_EXPERT_COUNTS" for value in closures)
    quality_good = all_missing_status == certificate_bad == negative_residual == 0
    complete = coverage_complete and closure_complete and quality_good
    frames = [strategy_frame, expert_frame, pd.DataFrame(status_rows)]
    OUT.mkdir(exist_ok=True)
    for filename, frame in zip(OUTPUTS, frames):
        temp = OUT/(filename+".tmp")
        frame.to_csv(temp, index=False, encoding="utf-8-sig")
        os.replace(temp, OUT/filename)
    result = {
        "status": "PASS_ALL22176_STRATEGIES_7488_EXPERTS" if complete else "PARTIAL_WITH_EXPLICIT_PENDING_QUALITY_EVIDENCE",
        "created_utc": datetime.now(timezone.utc).isoformat(), "cache_version": VERSION, "producer_sha256": code_hash,
        "complete": complete, "registered_strategy_rows": len(strategy_frame), "expected_strategy_rows": 22176,
        "observed_strategy_rows": len(observed), "pending_strategy_rows": len(expected)-len(observed),
        "registered_target_expert_rows": len(expert_frame), "expected_target_expert_rows": 7488,
        "observed_target_expert_rows": observed_expert_rows, "pending_target_expert_rows": len(expected_experts)-observed_expert_rows,
        "sealed_batches_scanned": len(batches), "strategy_exact_keys_verified": True, "target_expert_exact_keys_verified": True,
        "missing_source_status_records": all_missing_status, "certificate_residual_violations": certificate_bad,
        "negative_numerical_residual_records": negative_residual,
        "all_scanned_batch_policy_counts_close": True, "all_independent_batch_counts_close": closure_complete,
        "independent_batch_closures": closures, "source_sha256": sources,
        "output_sha256": {name: sha(OUT/name) for name in OUTPUTS},
        "fit_calls": 0, "learning_update_calls": 0, "tuning_calls": 0, "optimization_calls": 0, "selection_calls": 0,
        "performance_ranking_files_read": 0, "source_policy_or_engine_imported": False,
        "denominators": {"outer": "All logged outer records except TARGET_EXPERT_FUSION coordination, including failures and missing source status; None when no numerical outer layer exists",
                         "expert": "All 13 expected expert slots per observed target decision, including missing statuses",
                         "finite_residual_mean": "Mean of finite logged values only; missing/nonfinite/nonnumeric supports reported, never treated as zero",
                         "pending": "Expected registration rows with no scanned COMPLETE raw batch; zero observed support and blank ratios, never observed zero-quality claims"},
        "interpretation": {"all_states": "All source states retained in counts and per-state support, including failures, preservation, no-valid-input and coordinator markers",
                           "coordinator": "TARGET_EXPERT_FUSION logged objective/residual zeros are placeholders, not an optimizer convergence or optimality certificate",
                           "residual_units": "QP proximal fixed-point residual and CVaR FW support gap have different meanings; do not compare their magnitude as one universal precision scale",
                           "final_targets": "Logged residuals describe original optimizer calls before component replacement and common projection, not optimality of final projected/fused targets",
                           "reference_calls": "Source JSON does not retain the common reference solver metadata; this report cannot certify those unlogged calls and does not rerun them",
                           "experts": "Experts optimize inside the same actual fusion-account state; they are separate from independent point-model account paths",
                           "source_status": "Certified fractions count the original source labels, with residual violations separately checked; no optimizer is rerun"}}
    atomic_json(RECEIPT, result)
    print(json.dumps({key: result[key] for key in ["status", "observed_strategy_rows", "pending_strategy_rows", "observed_target_expert_rows", "pending_target_expert_rows", "sealed_batches_scanned", "all_independent_batch_counts_close"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--max-new-batches", type=int)
    args = parser.parse_args()
    require(args.interval >= 10, "WATCH_INTERVAL_TOO_SHORT")
    require(not (args.watch and args.require_complete), "REQUIRE_COMPLETE_IS_A_FINAL_ONE_SHOT_CHECK")
    paths, registration, members, dates = load_registration()
    code_hash = sha(Path(__file__))
    CACHE.mkdir(parents=True, exist_ok=True)
    batches, stamps = {}, {}
    last_signature = None
    result = None
    watch_path = OUT/"SOLVER_QUALITY_WATCH_STATUS.json"
    try:
        while True:
            require(sha(Path(__file__)) == code_hash, "SOLVER_ANALYSIS_CHANGED_WHILE_RUNNING")
            newly_processed = 0
            for year in YEARS:
                for marker in sorted((ROOT/f"results/{year}").glob("batch_*/COMPLETE.json")):
                    batch = marker.parent
                    cache_key = (year, batch.name)
                    if cache_key in batches:
                        current_files = [batch/"COMPLETE.json", batch/"metadata.json", batch/"POLICY_RECEIPT.json"]+sorted((batch/"raw_model_outputs").glob("part_*.parquet"))
                        require({path.relative_to(ROOT).as_posix() for path in current_files} == set(stamps[cache_key]), "SEALED_RAW_PART_NAMESPACE_CHANGED")
                        for relative, (size, modified) in stamps[cache_key].items():
                            info = (ROOT/relative).stat()
                            require(info.st_size == size and info.st_mtime_ns == modified, "SEALED_SOURCE_FINGERPRINT_CHANGED")
                        continue
                    cache_path = CACHE/f"{year}_{batch.name}.json"
                    if cache_path.exists():
                        record = json.loads(cache_path.read_text(encoding="utf-8"))
                        require(record["cache_version"] == VERSION and record["producer_sha256"] == code_hash, "QUALITY_CACHE_CODE_VERSION_CHANGED")
                        _, current_sources = batch_sources(batch)
                        require(current_sources == record["source_sha256"], "QUALITY_CACHE_RAW_SOURCE_SHA_CHANGED")
                    else:
                        if args.max_new_batches is not None and newly_processed >= args.max_new_batches:
                            continue
                        record = process_batch(year, batch, registration, members, dates, code_hash)
                        newly_processed += 1
                    batches[cache_key] = record
                    stamps[cache_key] = {relative: ((ROOT/relative).stat().st_size, (ROOT/relative).stat().st_mtime_ns) for relative in record["source_sha256"]}
            closure_stamps = []
            for year, batch_name in sorted(batches):
                reference = ROOT/f"audits/verification_cache/{year}_{batch_name}.json"
                stat = reference.stat() if reference.exists() else None
                closure_stamps.append((year, batch_name, stat.st_size if stat else None, stat.st_mtime_ns if stat else None))
            signature = (tuple(sorted(batches)), tuple(closure_stamps))
            if args.watch and result is not None and signature == last_signature:
                if (CACHE/"STOP.json").exists():
                    atomic_json(watch_path, {"status": "STOPPED_BY_EXPLICIT_STOP_FILE", "pid": os.getpid(), "updated_utc": datetime.now(timezone.utc).isoformat()})
                    return 0
                # Unchanged sealed evidence does not rewrite the large tables.
                time.sleep(args.interval)
                continue
            result = snapshot(paths, members, dates, batches, code_hash, force_sha=args.require_complete)
            last_signature = signature
            atomic_json(watch_path, {"status": "COMPLETE" if result["complete"] else "ACTIVE" if args.watch else "ONE_SHOT_PARTIAL",
                "pid": os.getpid(), "updated_utc": datetime.now(timezone.utc).isoformat(), "producer_sha256": code_hash,
                "observed_strategy_rows": result["observed_strategy_rows"], "pending_strategy_rows": result["pending_strategy_rows"],
                "stop_file": str(CACHE/"STOP.json"), "final_command": "python -B solver_quality_analysis.py --require-complete"})
            if result["complete"]:
                if args.watch:
                    # Final auto-stop is also a full content-hash audit, not stat-only.
                    snapshot(paths, members, dates, batches, code_hash, force_sha=True)
                return 0
            if not args.watch:
                if args.require_complete:
                    print("REQUIRE_COMPLETE_FAILED: explicit pending or incomplete independent solver evidence", flush=True)
                    return 2
                return 0
            if (CACHE/"STOP.json").exists():
                atomic_json(watch_path, {"status": "STOPPED_BY_EXPLICIT_STOP_FILE", "pid": os.getpid(), "updated_utc": datetime.now(timezone.utc).isoformat()})
                return 0
            time.sleep(args.interval)
    except Exception as error:
        atomic_json(watch_path, {"status": "FAILED_CLOSED", "pid": os.getpid(), "updated_utc": datetime.now(timezone.utc).isoformat(), "reason": str(error),
                                 "fit_calls": 0, "optimization_calls": 0})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
