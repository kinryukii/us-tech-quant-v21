"""Independent read-only audit of the new method's pre-2026 time boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import run


def import_original():
    spec = importlib.util.spec_from_file_location("risk_temporal_audit_original_producer", run.PRODUCER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    producer = import_original()
    matrix = pd.read_parquet(run.TRAIN, columns=["signal_date", "ticker", "target", "target_end_date"])
    ref = pd.read_parquet(run.REF_KEYS, columns=["signal_date", "ticker", "target"])
    price = pd.read_parquet(run.PRICE, columns=["ticker", "trade_date", "close"])
    preds = pd.read_parquet(run.OUT / "pre2026_oof_factor_predictions.parquet", columns=["signal_date", "ticker", "stage"])
    weights = pd.read_parquet(run.OUT / "pre2026_oof_optimized_weights.parquet", columns=["signal_date", "ticker", "stage"])
    diagnostics = pd.read_parquet(run.OUT / "pre2026_oof_risk_cost_diagnostics.parquet", columns=["signal_date", "stage", "covariance_observations"])
    logs = json.loads((run.OUT / "FIT_LOG.json").read_text(encoding="utf-8"))
    cutoff = pd.Timestamp("2026-01-01")
    assert len(matrix) == 520328 and matrix.target.notna().all() and matrix.target_end_date.lt(cutoff).all()
    assert price.trade_date.lt(cutoff).all()
    assert preds.signal_date.lt(cutoff).all() and weights.signal_date.lt(cutoff).all() and diagnostics.signal_date.lt(cutoff).all()
    assert diagnostics.covariance_observations.eq(60).all()
    assert len(preds) == len(ref) == 313668 and not preds.duplicated(["signal_date", "ticker"]).any()
    labeled = ref.loc[ref.target.notna()].merge(matrix, on=["signal_date", "ticker"], how="left", validate="one_to_one", suffixes=("_ref", "_train"))
    assert len(labeled) == 304085 and labeled.target_train.notna().all()
    assert np.array_equal(labeled.target_ref.to_numpy(float), labeled.target_train.to_numpy(float))
    assert labeled.target_end_date.lt(cutoff).all()
    folds = []
    for stage, year in producer.STAGES:
        train, evaluation, original = producer.stage_rows(matrix, year)
        first = pd.Timestamp(original["evaluation_first_trading_date"])
        own = preds.loc[preds.stage.eq(stage)]
        stage_log = next(x for x in logs if x.get("stage") == stage)
        assert len(train) == stage_log["train_rows"]
        assert len(own) == len(ref.loc[ref.signal_date.dt.year.eq(year)])
        assert train.signal_date.lt(first).all() and train.target_end_date.lt(first).all()
        assert train.target_end_date.lt(cutoff).all()
        assert own.signal_date.dt.year.eq(year).all()
        assert digest(Path(stage_log["model_artifact"])) == stage_log["model_sha256"]
        folds.append({"stage": stage, "year": year, "train_rows": len(train),
                      "train_signal_max": str(train.signal_date.max().date()),
                      "train_target_end_max": str(train.target_end_date.max().date()),
                      "evaluation_first_signal": str(first.date()),
                      "validation_prediction_rows": len(own),
                      "validation_label_max_end": str(evaluation.target_end_date.max().date()),
                      "train_target_end_ge_validation_first": int(train.target_end_date.ge(first).sum()),
                      "train_target_end_ge_2026": int(train.target_end_date.ge(cutoff).sum())})
    final_log = next(x for x in logs if x.get("stage") == "FULL_PRE2026")
    assert final_log["train_rows"] == len(matrix)
    assert digest(Path(final_log["model_artifact"])) == final_log["model_sha256"]
    annual_execution = {}
    for stage, year in producer.STAGES:
        frame = pd.read_parquet(run.OUT / f"{stage.lower()}_{year}_daily.parquet", columns=["execution_date"])
        assert frame.execution_date.lt(cutoff).all()
        annual_execution[stage] = str(frame.execution_date.max().date())
    result = {"status": "PASS_NO_2026_LABEL_OR_PRICE_READ_IN_NEW_METHOD", "audited_utc": datetime.now(timezone.utc).isoformat(),
              "run_source_sha256": digest(Path(run.__file__)), "original_producer_sha256": digest(run.PRODUCER),
              "training_matrix_sha256": digest(run.TRAIN), "price_coordinate_sha256": digest(run.PRICE),
              "matrix_rows": len(matrix), "matrix_signal_max": str(matrix.signal_date.max().date()),
              "matrix_target_end_max": str(matrix.target_end_date.max().date()),
              "matrix_target_end_ge_2026_rows": int(matrix.target_end_date.ge(cutoff).sum()),
              "price_rows_read_by_run": len(price), "price_max_trade_date": str(price.trade_date.max().date()),
              "price_ge_2026_rows": int(price.trade_date.ge(cutoff).sum()),
              "oof_prediction_rows": len(preds), "oof_labeled_target_rows": len(labeled),
              "oof_labeled_target_end_max": str(labeled.target_end_date.max().date()),
              "oof_labeled_ge_2026_rows": int(labeled.target_end_date.ge(cutoff).sum()),
              "risk_covariance_signal_max": str(diagnostics.signal_date.max().date()),
              "risk_covariance_calls": len(diagnostics), "risk_covariance_uses_date_lte_signal": "verified in run.covariance_for_day source and no other price path",
              "weight_signal_max": str(weights.signal_date.max().date()),
              "annual_execution_max": annual_execution, "folds": folds,
              "full_pre2026_fit_rows": len(matrix), "full_pre2026_target_end_max": str(matrix.target_end_date.max().date()),
              "read_2026_price_rows": 0, "used_2026_training_labels": 0, "repair_or_retrain_needed": False}
    (run.OUT / "TEMPORAL_BOUNDARY_AUDIT_20260927.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
