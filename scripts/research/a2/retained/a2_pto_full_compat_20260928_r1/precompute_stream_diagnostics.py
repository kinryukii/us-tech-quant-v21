"""Cache every frozen prediction-stream diagnostic without account-result I/O."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
from common import ROOT, registry, sha, write_json, pd, np
from freeze_all import verify_freeze
from analyze import prediction_diagnostics

OUT = ROOT / "analysis"
KEY = ["signal_date", "ticker"]
STREAMS = [row["stream"] for row in registry()[0]]
STAGES = [(2025, "validation", "pre"), (2026, "final", "test")]
DATA_PATHS = [f"data/{prefix}{suffix}.parquet" for prefix in ["pre", "test"] for suffix in ["", "_prices", "_calendar"]]
PREDICTION_PATHS = [f"predictions/streams/{stage}/{stream}.parquet" for _, stage, _ in STAGES for stream in STREAMS]
RAW_DIAGNOSTIC = "analysis/RAW_PREDICTION_DIAGNOSTICS_INCLUSIVE_EXTREME_HINTS.csv"
RAW_LEGACY_DIAGNOSTIC = "analysis/RAW_PREDICTION_DIAGNOSTICS.csv"
OUTPUT_NAMES = ["PREDICTION_DIAGNOSTICS.csv", "PREDICTION_DAILY_IC.csv"]
RECEIPT_PATH = OUT / "STREAM_PREDICTION_DIAGNOSTICS_RECEIPT.json"
LEARNING_CALLS = {"fit", "partial_fit", "fit_transform", "fit_predict", "fit_payload", "train_member", "training_sample", "backward", "optimizer_step"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def no_learning_profile(frame, event, arg):
    if event == "call" and frame.f_code.co_name in LEARNING_CALLS:
        raise RuntimeError("FORBIDDEN_LEARNING_IN_STREAM_DIAGNOSTICS:"+frame.f_code.co_name)


def bind_sources():
    paths = DATA_PATHS+PREDICTION_PATHS+["analyze.py", "raw_prediction_diagnostics.py", "raw_prediction_diagnostics_inclusive.py", Path(__file__).name, RAW_DIAGNOSTIC, RAW_LEGACY_DIAGNOSTIC]
    require(len(STREAMS) == len(set(STREAMS)) == 75 and len(PREDICTION_PATHS) == 150, "REGISTERED_STREAM_LIST_CHANGED")
    for path in paths:
        require((ROOT/path).is_file(), "STREAM_DIAGNOSTIC_SOURCE_MISSING:"+path)
    return {path: sha(ROOT/path) for path in paths}


def check_input_outputs():
    key_frames = {}
    for year, stage, prefix in STAGES:
        context = pd.read_parquet(ROOT/f"data/{prefix}.parquet")
        context = context.loc[pd.to_datetime(context.signal_date).dt.year.eq(year)].reset_index(drop=True)
        expected = context[KEY]
        require(not expected.duplicated(KEY).any(), "DUPLICATED_CONTEXT_KEYS")
        key_frames[year] = expected
        expected_keys = expected.sort_values(KEY).reset_index(drop=True)
        for stream in STREAMS:
            values = pd.read_parquet(ROOT/f"predictions/streams/{stage}/{stream}.parquet", columns=KEY+["mu", "sigma"])
            # Fusion output may use its MultiIndex order rather than source order.
            actual_keys = values[KEY].sort_values(KEY).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual_keys, expected_keys, check_dtype=False)
            require(not values.duplicated(KEY).any(), "DUPLICATED_STREAM_KEYS:"+stream)
            require(np.isfinite(values[["mu", "sigma"]].to_numpy(float)).all() and values.sigma.gt(0.).all(), "INVALID_CALIBRATED_STREAM_INTERFACE:"+stream)
        print(json.dumps({"stage": stage, "complete_stream_inputs": len(STREAMS), "context_keys_per_stream": len(expected)}), flush=True)
    return key_frames


def validate_diagnostics(table, daily, raw, legacy_raw, key_frames):
    expected_keys = {(year, stream) for year, _, _ in STAGES for stream in STREAMS}
    require(len(table) == 150 and not table.duplicated(["year", "stream"]).any(), "STREAM_DIAGNOSTIC_ROWS_INCOMPLETE")
    require(set(zip(table.year, table.stream)) == expected_keys, "STREAM_DIAGNOSTIC_REGISTERED_KEYS_CHANGED")
    require(table.status.eq("DIAGNOSTIC").all() and table.not_a_selection_criterion.eq(True).all(), "STREAM_DIAGNOSTIC_STATUS_CHANGED")
    require(not daily.duplicated(["year", "stream", "date"]).any(), "DUPLICATED_DAILY_IC_KEY")
    require(set(zip(daily.year, daily.stream)) == expected_keys, "DAILY_IC_STREAM_YEAR_COVERAGE_INCOMPLETE")
    require(daily.n.gt(0).all(), "EMPTY_DAILY_IC_SAMPLE")
    finite_ic = daily.rank_ic[np.isfinite(daily.rank_ic)]
    require(finite_ic.between(-1., 1.).all(), "DAILY_IC_OUTSIDE_VALID_RANGE")
    required_support = {2025: (111399, 110438, 961, 249), 2026: (62475, 62014, 461, 162)}
    support = []
    for year, _, _ in STAGES:
        rows = table.loc[table.year.eq(year)]
        raw_rows = raw.loc[raw.year.eq(year)]
        legacy_rows = legacy_raw.loc[legacy_raw.year.eq(year)]
        require(len(raw_rows) == 31 and raw_rows.member.nunique() == 31, "RAW_DIAGNOSTIC_REFERENCE_INCOMPLETE")
        require(len(legacy_rows) == 31 and legacy_rows.member.nunique() == 31, "LEGACY_RAW_DIAGNOSTIC_REFERENCE_INCOMPLETE")
        predicted, evaluated, excluded, extreme = required_support[year]
        require(len(key_frames[year]) == predicted, "CONTEXT_SUPPORT_CHANGED")
        for frame, column, value in [(rows, "prediction_rows", predicted), (rows, "rows", evaluated), (rows, "mature_label_rows", evaluated),
                (rows, "finite_label_rows", evaluated), (rows, "excluded_label_or_prediction_rows", excluded), (rows, "extreme_label_rows", extreme),
                (raw_rows, "prediction_rows", predicted), (raw_rows, "evaluated_rows", evaluated), (raw_rows, "finite_legal_label_rows", evaluated),
                (raw_rows, "excluded_label_rows", excluded), (raw_rows, "extreme_raw_label_rows", extreme)]:
            require(frame[column].eq(value).all(), "RAW_STREAM_SUPPORT_MISMATCH:"+str(year)+":"+column)
        status_reference = [json.loads(text) for text in raw_rows.label_status_counts]
        require(all(value == status_reference[0] for value in status_reference), "RAW_LABEL_STATUS_COUNTS_INCONSISTENT")
        require(all(json.loads(text) == status_reference[0] for text in rows.label_status_counts), "RAW_STREAM_LABEL_STATUS_COUNTS_MISMATCH")
        legacy_support = 110435 if year == 2025 else 62014
        require(legacy_rows.evaluated_rows.eq(legacy_support).all(), "ORIGINAL_CONSERVATIVE_RAW_SUPPORT_CHANGED")
        require(raw_rows.source_extreme_hint_rows_excluded.eq(0).all() and rows.source_extreme_warning_rows_excluded.eq(0).all(), "SOURCE_EXTREME_HINT_SILENTLY_EXCLUDED")
        require(raw_rows.source_extreme_hint_is_proven_bad_price.eq(False).all(), "SOURCE_EXTREME_HINT_MISLABELED_BAD_PRICE")
        daily_rows = daily.loc[daily.year.eq(year)]
        counts = daily_rows.groupby("stream").n.sum()
        require(counts.reindex(STREAMS).eq(evaluated).all(), "DAILY_IC_LABEL_SUPPORT_MISMATCH")
        date_counts = daily_rows.groupby("stream").date.nunique()
        require(date_counts.nunique() == 1, "DAILY_IC_DATES_INCONSISTENT_ACROSS_STREAMS")
        numerical = rows[["rmse_unclipped", "rmse_clipped_target", "prediction_mean", "prediction_std", "calibrated_scale_mean", "normal_proxy_nll"]].to_numpy(float)
        require(np.isfinite(numerical).all() and rows.calibrated_scale_mean.gt(0.).all(), "NONFINITE_STREAM_SCORE")
        support.append({"year": year, "streams": len(rows), "prediction_keys_per_stream": predicted, "legal_label_rows_per_stream": evaluated,
                        "excluded_rows_per_stream": excluded, "extreme_raw_label_rows_per_stream": extreme,
                        "daily_ic_signal_days_per_stream": int(date_counts.iloc[0]), "label_status_counts": status_reference[0],
                        "raw_typed_inclusive_diagnostic_support_exactly_matches": True,
                        "legacy_conservative_raw_legal_label_rows_per_member": legacy_support,
                        "legal_label_rows_added_by_retaining_source_extreme_hints": evaluated-legacy_support,
                        "source_extreme_hints_are_proven_bad_prices": False})
    return support


def main():
    started = time.perf_counter()
    freeze = verify_freeze()
    freeze_hash = sha(ROOT/"FREEZE.json")
    require(not RECEIPT_PATH.exists() and not any((OUT/name).exists() for name in OUTPUT_NAMES), "REFUSE_OVERWRITE_STREAM_DIAGNOSTIC_CACHE")
    sources = bind_sources()
    allowed_paths = {str((ROOT/path).resolve()) for path in DATA_PATHS+PREDICTION_PATHS+[RAW_DIAGNOSTIC, RAW_LEGACY_DIAGNOSTIC]}
    originals = {"read_parquet": pd.read_parquet, "read_csv": pd.read_csv}
    read_paths = []

    def guarded_reader(name):
        def read(path, *args, **kwargs):
            resolved = str(Path(path).resolve())
            require(resolved in allowed_paths, "UNAUTHORIZED_ACCOUNT_OR_OTHER_DATA_READ:"+resolved)
            read_paths.append(str(Path(resolved).relative_to(ROOT)))
            return originals[name](path, *args, **kwargs)
        return read

    pd.read_parquet, pd.read_csv = guarded_reader("read_parquet"), guarded_reader("read_csv")
    try:
        key_frames = check_input_outputs()
        raw = pd.read_csv(ROOT/RAW_DIAGNOSTIC)
        legacy_raw = pd.read_csv(ROOT/RAW_LEGACY_DIAGNOSTIC)
        tables, days = [], []
        for year, stage, _ in STAGES:
            stage_started = time.perf_counter()
            sys.setprofile(no_learning_profile)
            try:
                result, daily = prediction_diagnostics(stage)
            finally:
                sys.setprofile(None)
            tables.append(result)
            days.append(daily)
            print(json.dumps({"stage": stage, "diagnostic_rows": len(result), "daily_ic_rows": len(daily), "runtime_seconds": round(time.perf_counter()-stage_started, 6)}), flush=True)
        table, daily = pd.concat(tables, ignore_index=True), pd.concat(days, ignore_index=True)
        support = validate_diagnostics(table, daily, raw, legacy_raw, key_frames)
    finally:
        pd.read_parquet, pd.read_csv = originals["read_parquet"], originals["read_csv"]
        sys.setprofile(None)
    after = verify_freeze()
    require(after == freeze and sha(ROOT/"FREEZE.json") == freeze_hash, "FREEZE_CHANGED_DURING_STREAM_DIAGNOSTICS")
    require({path: sha(ROOT/path) for path in sources} == sources, "STREAM_DIAGNOSTIC_SOURCE_CHANGED_DURING_EXECUTION")
    OUT.mkdir(exist_ok=True)
    for name, values in zip(OUTPUT_NAMES, [table, daily]):
        values.to_csv(OUT/name, index=False, encoding="utf-8-sig")
    reloaded, daily_reloaded = pd.read_csv(OUT/OUTPUT_NAMES[0]), pd.read_csv(OUT/OUTPUT_NAMES[1])
    validate_diagnostics(reloaded, daily_reloaded, raw, legacy_raw, key_frames)
    record = {
        "status": "PASS_ALL150_FROZEN_STREAM_DIAGNOSTICS", "created_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_rows": len(table), "expected_analysis_rows": 150, "daily_ic_rows": len(daily),
        "registered_year_stream_keys": [{"year": year, "stream": stream} for year, _, _ in STAGES for stream in STREAMS],
        "fit_calls": 0, "learning_update_calls": 0, "selection_or_tuning_calls": 0, "account_result_files_read": 0,
        "source_sha256": sources, "output_sha256": {name: sha(OUT/name) for name in OUTPUT_NAMES},
        "data_parquet_hash_count": len(DATA_PATHS), "prediction_stream_parquet_hash_count": len(PREDICTION_PATHS),
        "freeze_receipt_sha256": freeze_hash, "freeze_hashes_verified_before": len(freeze["artifact_sha256"]), "freeze_hashes_verified_after": len(after["artifact_sha256"]),
        "legal_label_support": support, "only_allowed_data_paths_read": True, "unique_input_files_read": sorted(set(read_paths)),
        "source_extreme_warning_scope": "Source abs-return hints are retained in all 150 stream scores. The preserved 31-member exclusion diagnostic is a separate sensitivity view, not proof of bad prices.",
        "runtime_seconds": round(time.perf_counter()-started, 6), "formal_2026_full_pool_status": "BLOCKED_DATA",
        "2026_scope": "Previously observed qualified-context diagnostic; not a blind or formal full-pool test.",
        "cache_contract": "Exact source/output hashes and all 150 registered keys must match before reuse. No metric-based selection or new calibration.",
        "daily_ic_scope": "Spearman IC of calibrated stream mu on legal mature labels; no IID significance test; raw rank scores are separate in RAW_RANK_DAILY_IC.csv.",
    }
    write_json(RECEIPT_PATH, record)
    print(json.dumps({key: record[key] for key in ["status", "analysis_rows", "daily_ic_rows", "fit_calls", "learning_update_calls", "account_result_files_read", "freeze_hashes_verified_after", "runtime_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
