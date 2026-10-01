"""Independent date/key/input and fitted risk/auxiliary artifact verification."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
ROOT = RUN.parent


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    old = ROOT / "a2_latest_effective_joint_20260927/data"
    qual = ROOT / "a2_qualification_holdings_v1_20260927/data"
    columns = json.loads((old / "JOINT_DATA_AUDIT.json").read_text(encoding="utf-8"))["features"]
    pre = pd.read_parquet(old / "pre2026_joint_context.parquet", columns=[
        "signal_date", "ticker", "active_13f_quarter", "new_buy_eligible", "execution_date",
        "label_end_date", "label_available", "latest_filing_date", "quarter_effective_date", *columns])
    test = pd.read_parquet(qual / "test_features_context.parquet", columns=[
        "signal_date", "ticker", "quarter", "new_buy_eligible", "context_only_if_held",
        "latest_filing_date", "quarter_effective_date", *columns])
    timing = pd.read_csv(old / "quarter_timing.csv", parse_dates=["quarter_effective_date"])
    timing = timing.sort_values("quarter_effective_date")
    frames = {}
    for name, frame, quarter in [("pre2026", pre, "active_13f_quarter"), ("test_features_only", test, "quarter")]:
        assert not frame.duplicated(["signal_date", "ticker"]).any()
        assert np.isfinite(frame[columns].to_numpy(float)).all()
        assert frame.signal_date.gt(frame.latest_filing_date).all()
        assert frame.signal_date.ge(frame.quarter_effective_date).all()
        positions = np.searchsorted(timing.quarter_effective_date.to_numpy(), frame.signal_date.to_numpy(), side="right") - 1
        assert (positions >= 0).all()
        buy = frame.new_buy_eligible.to_numpy(bool)
        assert (frame.loc[buy, quarter].to_numpy() == timing.quarter.to_numpy()[positions[buy]]).all()
        frames[name] = {"rows": len(frame), "days": int(frame.signal_date.nunique()),
                        "first_signal": str(frame.signal_date.min().date()),
                        "last_signal": str(frame.signal_date.max().date()),
                        "latest_effective_quarter_mismatches": 0, "feature_nonfinite_cells": 0}
    assert pre.signal_date.lt("2026-01-01").all()
    assert pre.loc[pre.label_available, "label_end_date"].lt("2026-01-01").all()
    assert not (test.context_only_if_held & test.new_buy_eligible).any()
    stages = {}
    for stage, cutoff in [("validation", "2025-01-01"), ("final", "2026-01-01")]:
        dest = RUN / "risk_artifacts" / stage
        receipt = json.loads((dest / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
        assert receipt["cutoff_exclusive"] == cutoff
        assert receipt["producer_sha256"] == sha(RUN / "risk_aux.py")
        assert receipt["risk"]["return_last"] < cutoff
        assert receipt["diagnostics"]["sample_last"] < cutoff
        assert receipt["risk"]["return_rows"] == 252
        for path, expected in receipt["source_sha256"].items():
            assert sha(path) == expected
        for name, expected in receipt["artifacts_sha256"].items():
            assert sha(dest / name) == expected
        keys = pd.read_csv(dest / "diagnostic_sample_keys.csv", parse_dates=["signal_date"])
        assert len(keys) == 20000 and keys.signal_date.lt(cutoff).all()
        selected = keys.merge(pre, on=["signal_date", "ticker"], validate="one_to_one")
        assert len(selected) == len(keys)
        aux = joblib.load(dest / "diagnostics.joblib")
        assert aux["stage"] == stage and aux["cutoff_exclusive"] == cutoff
        assert int(aux["scaler"].n_samples_seen_) == len(keys)
        np.testing.assert_allclose(aux["scaler"].mean_, selected[columns].to_numpy(float).mean(axis=0))
        assert aux["cluster"].n_clusters == 5 and len(aux["anomaly"].estimators_) == 100
        assert aux["anomaly"].contamination == .02
        with np.load(dest / "frozen_covariance.npz", allow_pickle=False) as data, threadpool_limits(limits=2):
            covariance = data["covariance"]
            factor = data["factor_covariance"]
            np.linalg.cholesky(covariance)
            np.linalg.cholesky(factor)
            assert data["factor_loadings"].shape == (len(data["tickers"]), 5)
            np.testing.assert_allclose(np.diag(covariance), np.diag(factor), atol=1e-10)
        mature = pre.signal_date.lt(cutoff) & pre.label_available & pre.label_end_date.lt(cutoff)
        assert pre.loc[mature, "execution_date"].gt(pre.loc[mature, "signal_date"]).all()
        assert pre.loc[mature, "label_end_date"].gt(pre.loc[mature, "execution_date"]).all()
        stages[stage] = {"risk_first": receipt["risk"]["return_first"], "risk_last": receipt["risk"]["return_last"],
                         "risk_securities": receipt["risk"]["securities"], "risk_returns": 252,
                         "mature_supervised_rows": int(mature.sum()),
                         "mature_label_end_max": str(pre.loc[mature, "label_end_date"].max().date()),
                         "diagnostic_sample_rows": len(keys), "source_and_artifact_hashes": "PASS",
                         "scaler_matches_exact_stage_sample": True, "covariance_positive_definite": True,
                         "receipt_sha256": sha(dest / "TRAIN_RECEIPT.json")}
    cov = pd.read_csv(qual / "coverage.csv")
    result = {"status": "PASS_WITH_EXPLICIT_DATA_LIMITATIONS", "created_utc": datetime.now(timezone.utc).isoformat(),
              "read_2026_numeric_prices": False, "read_model_outcome_results": False,
              "source_modified": False, "input_frames": frames, "stages": stages,
              "test_unknown_candidate_rows": int(cov.unknown_candidates.sum()),
              "test_complete_pool_days": int(cov.unknown_candidates.eq(0).sum()),
              "limitations": ["2026 is a retrospectively qualified subset, previously observed, not an untouched blind/full-pool test.",
                              "Latest publicly filed quarter activates on inherited fifth subsequent session, not immediate filing arrival.",
                              "GLW 2026-02-26 event-date/adjusted-feature conflict remains unresolved; diagnostic-only result boundary.",
                              "Risk returns use affine adjusted research coordinate, not certified shareholder total return.",
                              "Historical vendor actual arrival and original-universe survivorship are not proved."]}
    (HERE / "INDEPENDENT_RISK_INPUT_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
