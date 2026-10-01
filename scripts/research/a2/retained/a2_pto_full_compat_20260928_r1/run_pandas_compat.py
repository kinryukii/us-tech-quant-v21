"""Restore pandas' integer GroupBy row axis for four statistics-only scripts.

The compatibility attribute exists only in this process and is restored in a
finally block. No original source, frozen artifact, prediction cache, grouping
key, metric, candidate, training budget, or account implementation is changed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import statistics
import sys
import traceback

sys.dont_write_bytecode = True
import pandas as pd
from pandas.core.groupby.groupby import GroupBy

ROOT = Path(__file__).resolve().parent
ALLOWED = {"analyze.py", "dimension_reports.py", "figures.py", "build_report.py"}
AGGREGATIONS = ["count", "mean", "median", "min", "max"]
FIRST_FAILURE = "audits/PRODUCTION_HANDOFF_ANALYZE_FAILURE_20260928T2130"
CACHE_RECEIPT = "analysis/STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def row_axis_compat():
    had_attribute = "axis" in GroupBy.__dict__
    previous = GroupBy.__dict__.get("axis")
    setattr(GroupBy, "axis", 0)
    require(GroupBy.__dict__["axis"] == 0, "GROUPBY_ROW_AXIS_NOT_INTEGER_ZERO")
    try:
        yield {"old_attribute_present": had_attribute, "installed_axis": 0}
    finally:
        if had_attribute:
            setattr(GroupBy, "axis", previous)
        else:
            delattr(GroupBy, "axis")
        require(("axis" in GroupBy.__dict__) == had_attribute, "GROUPBY_ORIGINAL_ATTRIBUTE_NOT_RESTORED")
        if had_attribute:
            require(GroupBy.__dict__["axis"] is previous, "GROUPBY_ORIGINAL_ATTRIBUTE_IDENTITY_NOT_RESTORED")


@contextmanager
def no_learning_or_accounts():
    counts = {"fit_calls": 0, "learning_update_calls": 0, "optimization_calls": 0,
              "replay_dispatches": 0, "selection_or_tuning_calls": 0}
    previous = sys.getprofile()
    def guard(frame, event, arg):
        if event == "call":
            name = frame.f_code.co_name
            module = frame.f_globals.get("__name__", "")
            category = None
            if name in {"fit", "fit_transform", "partial_fit", "train_member", "train_models", "train_payload"}:
                category = "fit_calls"
            elif name in {"backward", "_engine_run_backward"} or (module.startswith("torch.optim") and name == "step"):
                category = "learning_update_calls"
            elif module.split(".")[0] in {"policy", "optimizers", "optimization", "portfolio_optimization"} and name in {"_solve", "solve", "optimize", "minimize"}:
                category = "optimization_calls"
            elif module.split(".")[0] in {"engine", "account_engine", "batch_engine", "run_registered", "run_grid", "rl_eval"} and name in {"run", "main", "replay", "replay_many", "run_batch", "evaluate_policy"}:
                category = "replay_dispatches"
            elif name in {"select_model", "select_candidates", "search_weights", "grid_search", "random_search", "hyperparameter_search"}:
                category = "selection_or_tuning_calls"
            if category:
                counts[category] += 1
                raise RuntimeError("FORBIDDEN_STATISTICAL_ENTRY_CALL:" + category + ":" + module + "." + name)
        if previous:
            previous(frame, event, arg)
    sys.setprofile(guard)
    try:
        yield counts
    finally:
        sys.setprofile(previous)


def verify_frozen_and_cache():
    freeze_path = ROOT / "FREEZE.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    require(freeze["status"] == "FROZEN_ALL_LEARNING_PRE2026" and len(freeze["artifact_sha256"]) == 663, "FROZEN_MANIFEST_NOT_EXPECTED663")
    for relative, digest in freeze["artifact_sha256"].items():
        require(sha(ROOT / relative) == digest, "FROZEN_BYTES_CHANGED:" + relative)
    cache_path = ROOT / CACHE_RECEIPT
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    require(cache["status"] == "PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS" and cache["analysis_rows"] == 150, "FULL_STREAM_DIAGNOSTIC_CACHE_NOT_PASS")
    require(cache["source_sha256"]["analyze.py"] == sha(ROOT / "analyze.py"), "CACHE_ANALYZE_SOURCE_BINDING_CHANGED")
    for relative, digest in cache["source_sha256"].items():
        require(sha(ROOT / relative) == digest, "STREAM_CACHE_SOURCE_CHANGED:" + relative)
    for basename, digest in cache["output_sha256"].items():
        require(sha(ROOT / "analysis" / basename) == digest, "STREAM_CACHE_OUTPUT_CHANGED:" + basename)
    return {"freeze_sha256": sha(freeze_path), "frozen_artifacts_verified": 663,
            "stream_cache_receipt_sha256": sha(cache_path), "stream_cache_sources_verified": len(cache["source_sha256"]),
            "stream_cache_output_sha256": cache["output_sha256"]}


def independent_sample_summary(records, group_columns, metrics):
    groups = {}
    for record in records:
        key = tuple(record[column] for column in group_columns)
        groups.setdefault(key, []).append(record)
    expected = {}
    for key, group in groups.items():
        for metric in metrics:
            values = [row[metric] for row in group if row[metric] is not None and not math.isnan(row[metric])]
            for aggregation in AGGREGATIONS:
                if aggregation == "count": value = len(values)
                elif not values: value = math.nan
                elif aggregation == "mean": value = statistics.mean(values)
                elif aggregation == "median": value = statistics.median(values)
                elif aggregation == "min": value = min(values)
                else: value = max(values)
                expected[(key, metric, aggregation)] = value
    return expected


def self_test():
    records = [
        {"year": 2025, "stream": "A", "axis": "joint", "indicative_return": .1, "fees": 1., "mean_cash": .2},
        {"year": 2025, "stream": "A", "axis": "buy", "indicative_return": .2, "fees": 3., "mean_cash": .4},
        {"year": 2025, "stream": "B", "axis": "cash", "indicative_return": -.2, "fees": 5., "mean_cash": .6},
        {"year": 2026, "stream": "A", "axis": "sell", "indicative_return": -.1, "fees": 0., "mean_cash": .1},
        {"year": 2026, "stream": "A", "axis": "joint", "indicative_return": 0., "fees": 2., "mean_cash": math.nan},
        {"year": 2026, "stream": "B", "axis": "cash", "indicative_return": .3, "fees": 4., "mean_cash": .9},
    ]
    frame = pd.DataFrame(records)
    group_columns = ["year", "stream"]
    metrics = ["indicative_return", "fees", "mean_cash"]
    baseline_error = None
    try:
        frame.groupby(group_columns)[metrics].agg(AGGREGATIONS)
    except IndexError as error:
        baseline_error = type(error).__name__ + ":" + str(error)
    require(baseline_error and "already selected" in baseline_error, "ORIGINAL_GROUPBY_AXIS_FAILURE_NOT_REPRODUCED")
    frame_before = frame.copy(deep=True)
    with no_learning_or_accounts() as calls:
        with row_axis_compat() as installation:
            actual = frame.groupby(group_columns)[metrics].agg(AGGREGATIONS)
            keys = tuple(actual.index.tolist())
            singleton = frame.groupby(group_columns)["fees"].median()
    pd.testing.assert_frame_equal(frame, frame_before)
    expected = independent_sample_summary(records, group_columns, metrics)
    require(set(keys) == {key for key, _, _ in expected}, "COMPAT_GROUP_KEYS_CHANGED")
    require(list(actual.columns) == [(metric, aggregation) for metric in metrics for aggregation in AGGREGATIONS], "COMPAT_METRIC_OR_AGGREGATION_ORDER_CHANGED")
    for (key, metric, aggregation), value in expected.items():
        got = actual.loc[key, (metric, aggregation)]
        require((math.isnan(got) and math.isnan(value)) or math.isclose(got, value, rel_tol=1e-12, abs_tol=1e-12), "COMPAT_AGGREGATION_DIFFERS_FROM_INDEPENDENT_STDLIB")
    for key in singleton.index:
        require(singleton.loc[key] == expected[(key, "fees", "median")], "SINGLE_METRIC_GROUP_MEDIAN_CHANGED")
    try:
        with row_axis_compat():
            raise RuntimeError("INTENTIONAL_RESTORATION_TEST")
    except RuntimeError as error:
        require(str(error) == "INTENTIONAL_RESTORATION_TEST", "RESTORATION_EXCEPTION_CHANGED")
    for bad in ["predictions_train.py", "policy.py", "../analyze.py"]:
        try: resolve_script(bad)
        except RuntimeError: pass
        else: raise RuntimeError("UNAUTHORIZED_SCRIPT_ALLOWED")
    result = {"status": "PASS_REPRODUCED_ORIGINAL_AXIS_FAILURE_AND_INDEPENDENT_AGGREGATIONS", "created_utc": datetime.now(timezone.utc).isoformat(),
              "producer_sha256": sha(Path(__file__)), "pandas_version": pd.__version__, "baseline_error": baseline_error,
              "sample_rows": 6, "group_count": len(keys), "metrics": metrics, "aggregations": AGGREGATIONS,
              "independent_checked_group_metric_aggregates": len(expected), "source_frame_and_group_keys_unchanged": True,
              "original_axis_attribute_restored_on_success_and_exception": True, "installation": installation,
              "single_metric_median_unchanged": True, "unauthorized_script_guard_verified": True,
              "sample_is_synthetic_qa_only_not_production_results": True, **calls,
              "first_failure_preservation_path": FIRST_FAILURE,
              "script_review": {"analyze.py": "Affected selected multi-metric list-aggregation at line174",
                                "dimension_reports.py": "Uses group iteration and scalar summaries; no selected list-aggregation",
                                "figures.py": "Uses group iteration and scalar median; same row-axis compatibility is harmless",
                                "build_report.py": "Uses group iteration/scalar sum; no selected list-aggregation"}}
    atomic_json(ROOT / "analysis/PANDAS_COMPAT_QA.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def resolve_script(name):
    require(name in ALLOWED, "ONLY_EXPLICIT_STATISTICS_DELIVERY_SCRIPTS_ALLOWED")
    path = ROOT / name
    require(path.resolve() == path and path.is_file(), "SCRIPT_MISSING_OR_PATH_ESCAPE")
    return path


def run_script(name):
    path = resolve_script(name)
    qa = json.loads((ROOT / "analysis/PANDAS_COMPAT_QA.json").read_text(encoding="utf-8"))
    producer = sha(Path(__file__))
    require(qa["producer_sha256"] == producer and qa["status"].startswith("PASS_REPRODUCED"), "CURRENT_COMPAT_IMPLEMENTATION_QA_REQUIRED")
    source_before = sha(path)
    provenance_before = verify_frozen_and_cache()
    axis_present_before = "axis" in GroupBy.__dict__
    axis_value_before = GroupBy.__dict__.get("axis")
    previous_argv = sys.argv
    record = {"status": "FAILED_PANDAS_STATISTICAL_COMPAT_RUN", "script": name,
              "created_utc": datetime.now(timezone.utc).isoformat(), "pandas_version": pd.__version__,
              "python_version": sys.version, "producer_sha256": producer, "script_sha256": source_before,
              "qa_sha256": sha(ROOT / "analysis/PANDAS_COMPAT_QA.json"), "compatibility": "process-local GroupBy.axis integer row axis=0",
              "first_failure_preservation_path": FIRST_FAILURE, "before": provenance_before,
              "fit_calls": 0, "learning_update_calls": 0, "optimization_calls": 0, "replay_dispatches": 0, "selection_or_tuning_calls": 0}
    record["source_sha256"] = {relative: sha(ROOT / relative) for relative in [
        Path(__file__).name, name, "analysis/PANDAS_COMPAT_QA.json", "FREEZE.json", CACHE_RECEIPT,
        FIRST_FAILURE + "/PRESERVATION_RECEIPT.json", FIRST_FAILURE + "/analyze.py",
        FIRST_FAILURE + "/FINALIZATION_STATE.json", FIRST_FAILURE + "/finalization.log"]}
    exit_code = 0
    try:
        sys.argv = [str(path)]
        with no_learning_or_accounts() as calls:
            with row_axis_compat() as installation:
                try:
                    runpy.run_path(str(path), run_name="__main__")
                except SystemExit as error:
                    require(error.code in (None, 0), "ORIGINAL_STATISTICAL_SCRIPT_EXITED_NONZERO:" + str(error.code))
        record.update(calls)
        record["installation"] = installation
        require(sha(path) == source_before and sha(Path(__file__)) == producer, "STATISTICAL_OR_COMPAT_SOURCE_BYTES_CHANGED")
        provenance_after = verify_frozen_and_cache()
        require(provenance_after == provenance_before, "FROZEN_OR_CACHE_PROVENANCE_CHANGED_DURING_STATISTICAL_RUN")
        record.update(status="PASS_PANDAS_ROW_AXIS_COMPAT_STATISTICAL_DELIVERY", after=provenance_after,
                      original_axis_attribute_restored=True, original_script_bytes_unchanged=True)
    except BaseException as error:
        exit_code = 1
        record.update(error=type(error).__name__ + ":" + str(error), traceback=traceback.format_exc())
        if "calls" in locals(): record.update(calls)
    finally:
        sys.argv = previous_argv
        record["original_axis_attribute_restored"] = (("axis" in GroupBy.__dict__) == axis_present_before
            and (not axis_present_before or GroupBy.__dict__["axis"] is axis_value_before))
        if not record["original_axis_attribute_restored"]:
            exit_code = 1
            record["status"] = "FAILED_PANDAS_ORIGINAL_AXIS_ATTRIBUTE_RESTORATION"
        if exit_code == 0:
            primary = {"analyze.py": ["analysis/ANALYSIS_RECEIPT.json"],
                       "dimension_reports.py": [f"analysis/COMPARISON_{axis.upper()}.md" for axis in ["joint", "buy", "sell", "cash"]],
                       "figures.py": ["analysis/EFFECTS_SUMMARY.json"],
                       "build_report.py": ["REPORT.md", "DELIVERY_RECEIPT.json", "analysis/ALL_STRATEGY_RESULTS.csv", "analysis/LAYER_EFFECT_RANGES.csv", "analysis/SOLVER_QUALITY_SUMMARY.csv"]}[name]
            record["output_sha256"] = {relative: sha(ROOT / relative) for relative in primary}
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = ROOT / f"audits/PANDAS_COMPAT_RUNS/{stamp}_{path.stem}.json"
        atomic_json(archive, record)
        atomic_json(ROOT / f"analysis/PANDAS_COMPAT_{path.stem}_RECEIPT.json", record)
    print(json.dumps({"status": record["status"], "script": name, "exit_code": exit_code, "receipt_archive": archive.relative_to(ROOT).as_posix()}, ensure_ascii=False), flush=True)
    return exit_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        require(args.script is None, "SELF_TEST_DOES_NOT_EXECUTE_A_PRODUCTION_SCRIPT")
        self_test()
        return 0
    require(args.script is not None, "STATISTICAL_SCRIPT_NAME_REQUIRED")
    return run_script(args.script)


if __name__ == "__main__":
    raise SystemExit(main())
