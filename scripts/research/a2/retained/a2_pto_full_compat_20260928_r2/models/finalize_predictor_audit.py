"""Read-only final checks of predictor receipts; never trains or reads 2026."""
from pathlib import Path
import sys
import datetime
import json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from shared import STAGES, FEATURES, read_json, write_json, sha

EXPECTED_NAMES = ["ridge", "elastic", "huber", "ebm", "rf", "extra", "hgb", "xgb", "lgb", "cat", "mlp", "resnet", "fttransformer",
                  "logistic", "rf_class", "hgb_class", "xgb_class", "lgb_class", "cat_class", "mlp_class",
                  "linear_q", "hgb_q", "xgb_q", "lgb_q", "cat_q", "mlp_q", "ngboost", "gaussian_mlp", "cat_uncertainty", "xgb_rank", "lgb_rank"]
SOURCE_PATHS = {"pre_panel": ROOT / "data/pre_panel.parquet", "predictors": ROOT / "predictors.py",
                "trainer": ROOT / "train_predictors.py", "bootstrap": ROOT / "runtime_bootstrap.py",
                "shared": ROOT / "shared.py", "contract": ROOT / "EXPERIMENT_CONTRACT.md"}


def main():
    stage_counts, physical_records, failures, logical_rows, physical_rows = {}, [], [], [], []
    source_hashes = {key: sha(path) for key, path in SOURCE_PATHS.items()}
    for stage, cutoff in STAGES.items():
        status = read_json(ROOT / f"models/{stage}/FIT_STATUS.json")
        assert status["complete"] and len(status["fits"]) == 31, f"INCOMPLETE_STAGE:{stage}"
        assert [r["name"] for r in status["fits"]] == EXPECTED_NAMES, f"MEMBER_LIST_CHANGED:{stage}"
        assert status["source_hashes"] == source_hashes, f"SOURCE_HASH_CHANGED:{stage}"
        assert status["fit_2026_rows"] == 0 and status["test_2026_rows_read"] == 0
        keys = pd.read_parquet(status["sample_keys"])
        assert len(keys) == status["rows"] <= 40000
        assert not keys.duplicated(["signal_date", "ticker"]).any()
        assert keys.signal_date.lt(cutoff).all() and keys.label_end_date.lt(cutoff).all()
        assert sha(status["sample_keys"]) == status["sample_keys_sha256"]
        heads = []
        for record in status["fits"]:
            assert record["sample_keys_sha256"] == status["sample_keys_sha256"]
            individual = record["physical_fit_records"]
            assert len(individual) == (3 if record["name"].endswith("_q") else 1)
            if record["status"] == "TRAINED":
                assert sha(record["artifact"]) == record["artifact_sha256"]
            else:
                assert record["status"] == "FAILED" and record.get("failure")
                assert sha(record["failed_artifact"]) == record["failed_artifact_sha256"]
            logical_rows.append(dict(
                stage=stage, name=record["name"], status=record["status"], seconds=record["seconds"],
                cutoff_exclusive=cutoff, training_rows=status["rows"], physical_specs=len(individual),
                successful_heads=sum(h["status"] == "TRAINED" for h in individual),
                failed_heads=sum(h["status"] == "FAILED" for h in individual),
                artifact=record.get("artifact") or record.get("failed_artifact"),
                artifact_sha256=record.get("artifact_sha256") or record.get("failed_artifact_sha256"),
                failure=record.get("failure", {}).get("message", ""),
                failure_exception=record.get("failure", {}).get("exception", ""),
                convergence=json.dumps(record.get("convergence"), ensure_ascii=False),
                sample_keys_sha256=status["sample_keys_sha256"],
                fit_status_json=str(ROOT / f"models/{stage}/FIT_STATUS.json")))
            for head in individual:
                assert head["status"] in ("TRAINED", "FAILED")
                value = {"stage": stage, "name": record["name"], **head}
                physical_records.append(value)
                heads.append(value)
                if head["status"] == "FAILED": failures.append(value)
                physical_rows.append(dict(
                    stage=stage, name=record["name"], quantile=head["quantile"], status=head["status"],
                    seconds=head["seconds"], convergence=head["convergence"], cutoff_exclusive=cutoff,
                    training_rows=status["rows"], epochs=head.get("epochs"), updates=head.get("updates"),
                    failure=head.get("failure", {}).get("message", ""),
                    failure_exception=head.get("failure", {}).get("exception", ""),
                    warnings=json.dumps(head.get("warnings"), ensure_ascii=False),
                    warnings_capture_complete="warnings" in head,
                    numerical_extension=json.dumps(head.get("numerical_extension"), ensure_ascii=False),
                    artifact=record.get("artifact") or record.get("failed_artifact"),
                    artifact_sha256=record.get("artifact_sha256") or record.get("failed_artifact_sha256"),
                    sample_keys_sha256=status["sample_keys_sha256"],
                    fit_status_json=str(ROOT / f"models/{stage}/FIT_STATUS.json")))
            if record["name"].endswith("_q"):
                assert [head["quantile"] for head in individual] == [.1, .5, .9]
        assert len(heads) == 43 and len({(r["name"], r["quantile"]) for r in heads}) == 43
        scaler_means = {r["scaler_mean_sha256"] for r in status["fits"] if r["status"] == "TRAINED"}
        scaler_scales = {r["scaler_scale_sha256"] for r in status["fits"] if r["status"] == "TRAINED"}
        assert len(scaler_means) == len(scaler_scales) == 1, f"TRAIN_SAMPLE_NORMALIZATION_MISMATCH:{stage}"
        stage_counts[stage] = dict(cutoff_exclusive=cutoff, train_rows=len(keys), logical_attempts=31,
                                  logical_successful=sum(r["status"] == "TRAINED" for r in status["fits"]),
                                  logical_failed=sum(r["status"] == "FAILED" for r in status["fits"]),
                                  physical_attempts=43, physical_successful=sum(r["status"] == "TRAINED" for r in heads),
                                  physical_failed=sum(r["status"] == "FAILED" for r in heads),
                                  sample_keys_sha256=status["sample_keys_sha256"],
                                  signal_max=str(keys.signal_date.max()), label_end_max=str(keys.label_end_date.max()))
    assert len(physical_records) == 172
    successful = sum(r["status"] == "TRAINED" for r in physical_records)
    failed = sum(r["status"] == "FAILED" for r in physical_records)
    assert successful+failed == 172
    assert len(physical_rows) == 172 and len(logical_rows) == 124
    physical_path = ROOT / "models/PHYSICAL_FIT_COVERAGE.csv"
    logical_path = ROOT / "models/LOGICAL_FIT_COVERAGE.csv"
    pd.DataFrame(physical_rows).to_csv(physical_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(logical_rows).to_csv(logical_path, index=False, encoding="utf-8-sig")
    oof_checks = {}
    for label, stage, first, cutoff in [("2023H2", "inner", "2023-07-01", "2024-01-01"),
                                       ("2024", "early", "2024-01-01", "2025-01-01"),
                                       ("2025", "validation", "2025-01-01", "2026-01-01")]:
        path = ROOT / f"predictions/raw_oof_{label}.parquet"
        receipt = read_json(ROOT / f"predictions/raw_oof_{label}_receipt.json")
        frame = pd.read_parquet(path)
        assert sha(path) == receipt["sha256"]
        assert len(frame) == receipt["rows"] and len(frame.columns) == 51
        assert not frame.duplicated(["signal_date", "ticker"]).any()
        assert frame.signal_date.ge(first).all() and frame.signal_date.lt(cutoff).all()
        assert frame.label_end_date.lt(cutoff).all()
        missing = []
        for column in frame.columns[4:]:
            name, statistic = column.split("__", 1)
            value = frame[column].to_numpy(float)
            if name in receipt["failed_predictors"]:
                assert np.isnan(value).all()
                missing.append(column)
            else:
                assert np.isfinite(value).all(), f"NONFINITE_OOF:{label}:{column}"
                if statistic == "p": assert ((value >= 0) & (value <= 1)).all()
                if statistic == "scale": assert (value > 0).all()
        oof_checks[label] = dict(status="PASS", rows=len(frame), columns=51,
                                file_sha256=receipt["sha256"], failed_predictors=receipt["failed_predictors"],
                                failed_columns_preserved=missing, base_fit_cutoff_exclusive=STAGES[stage],
                                signal_min=str(frame.signal_date.min()), signal_max=str(frame.signal_date.max()),
                                label_end_max=str(frame.label_end_date.max()))
    result = dict(status="COMPLETE_WITH_FAILURES" if failed else "COMPLETE",
                  checked_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  physical_attempts=172, physical_successful=successful, physical_failed=failed,
                  physical_count_identity_verified=True, logical_attempts=124,
                  logical_successful=sum(r["logical_successful"] for r in stage_counts.values()),
                  logical_failed=sum(r["logical_failed"] for r in stage_counts.values()),
                  fit_2026_rows=0, read_2026_rows=0, generated_2026_predictions=False,
                  feature_count=len(FEATURES), source_hashes=source_hashes, stages=stage_counts,
                  numerical_extensions=sum(r.get("numerical_extension") is not None for r in physical_records),
                  actual_fit_calls=172+sum(r.get("numerical_extension") is not None for r in physical_records),
                  failure_records=failures, oof_checks=oof_checks,
                  physical_coverage_file=str(physical_path), physical_coverage_sha256=sha(physical_path),
                  logical_coverage_file=str(logical_path), logical_coverage_sha256=sha(logical_path),
                  interim_global_counter_note="While a quantile group was running, global completed included active heads; global success/failure only included completed logical groups. This independent final receipt counts every physical head.")
    write_json(ROOT / "models/FINAL_TRAINING_COUNTS.json", result)
    print({key: result[key] for key in ("status", "physical_attempts", "physical_successful", "physical_failed", "actual_fit_calls")}, flush=True)


if __name__ == "__main__": main()
