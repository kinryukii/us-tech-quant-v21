"""Read-only continuation for frozen A2 models on locally available 2026 inputs.

This entry point never fits an estimator, writes only its own staging directory,
and intentionally withholds strategy results when the expected pool is unresolved.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

BASE = Path(r"D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results")
SOURCE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
REBUILD = SOURCE / "scripts/run_rebuild.py"
R1 = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
R0F1 = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")
OUT = Path(__file__).resolve().parent / "test2026_stage"
METHODS = ("hgb", "ridge", "elastic_net", "mlp")
EXPECTED = {"common_frozen.json": "ac5c4e82791bda9670c3f81660f2cdf7ae3cd191f7b333f894452eabaadb4f8e",
    "hgb": "cc94b3cada81fdb9ca24416085d36b40036ebeaf17222548e4adbed57abecac8",
    "ridge": "5074c004a0a845f4850273789d4261dfa3d2af497df9038f41c96033bef26ba9",
    "elastic_net": "61b5139bcab676c0fa985824c06b9253e3dd958617f425f2d0b86cfc5b96a9d0",
    "mlp": "886c9f9b4195d9a91130b54e9432435cfbe614bb79d710b1dcced7a717039f38"}


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def forbid(*args, **kwargs):
    raise RuntimeError("FIT_CALL_FORBIDDEN_DURING_2026_INFERENCE")


def main():
    OUT.mkdir(exist_ok=True)
    contract = json.loads((BASE / "test2026/test2026_contract.json").read_text(encoding="utf-8"))
    assert contract["test_asof_utc"] == "2026-09-25T18:10:21.6494935Z"
    freeze = json.loads((BASE / "pre2026_model_freeze.json").read_text(encoding="utf-8"))
    common = BASE / "common_frozen.json"
    protected = [common, BASE / "pre2026_model_freeze.json", BASE / "REPORT.md", SOURCE / "A2/training_matrix.parquet", REBUILD, R1, R0F1]
    artifacts = {m: BASE / m / "final_full_pre2026.joblib" for m in METHODS}
    protected += list(artifacts.values())
    before = {str(p): sha(p) for p in protected}
    assert before[str(common)] == EXPECTED["common_frozen.json"]
    for m, p in artifacts.items():
        assert before[str(p)] == EXPECTED[m]
        assert next(x for x in freeze["models"][m]["fits"] if x["stage"] == "FULL_PRE2026")["sha256"] == EXPECTED[m]
    r1 = load("a2_r1_readonly", R1)
    r0f1 = load("a2_r0f1_readonly", R0F1)
    rebuild = load("a2_rebuild_readonly", REBUILD)
    # Original builders are invoked directly; no original main() or output writer is called.
    qqq = rebuild.qqq_prices()
    available = pd.Timestamp(qqq.trade_date.max())
    rebuild.END_EXCLUSIVE = available + pd.Timedelta(days=1)
    calendar = pd.DatetimeIndex(qqq.trade_date)
    qmanifest = pd.read_parquet(SOURCE / "universe/quarterly_universe_manifest.parquet")
    members = pd.read_parquet(SOURCE / "universe/quarterly_universe_members.parquet")
    active = rebuild.build_active_ledger(qmanifest, calendar)
    rehab_path = rebuild.RUN_CACHE / "rehab_factors.parquet"
    rehab_status_path = rebuild.RUN_CACHE / "rehab_status.csv"
    rehab = pd.read_parquet(rehab_path)
    rehab_status = pd.read_csv(rehab_status_path, keep_default_na=False)
    index, failures = rebuild.raw_file_index()
    assert not failures
    priced_codes = set(members.moomoo_transport_code).intersection(index)
    assert priced_codes.issubset(set(rehab_status.loc[rehab_status.status.eq("PASS"), "code"])), "Existing rehab cache incomplete; no read-only fallback"
    def frozen_rehab(codes):
        assert set(codes).issubset(set(rehab_status.loc[rehab_status.status.eq("PASS"), "code"]))
        return rehab, rehab_status, 0
    rebuild.load_rehab = frozen_rehab
    prices, features, eligible, daily, price_audit = rebuild.build_prices_and_u_t(r1, r0f1, members, active, qqq)
    test_dates = calendar[(calendar.year == 2026) & (calendar <= available)]
    features = features.loc[features.signal_date.isin(test_dates)].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    eligible = eligible.loc[eligible.signal_date.isin(test_dates)].copy()
    assert len(features) == len(eligible)
    assert features.loc[:, r1.FEATURE_COLUMNS].notna().all().all()
    expected = active.loc[active.signal_date.isin(test_dates), ["signal_date", "active_13f_quarter"]].merge(
        members[["quarter", "ticker", "moomoo_transport_code", "cusip"]], left_on="active_13f_quarter", right_on="quarter", validate="many_to_many")
    assert not expected.duplicated(["signal_date", "ticker"]).any()
    present = prices.loc[prices.trade_date.isin(test_dates), ["ticker", "trade_date"]].rename(columns={"trade_date": "signal_date"}).drop_duplicates()
    expected["raw_file_available"] = expected.moomoo_transport_code.isin(index)
    expected = expected.merge(present.assign(price_on_signal_date=True), on=["signal_date", "ticker"], how="left", validate="one_to_one")
    expected = expected.merge(eligible[["signal_date", "ticker", "required_observations"]].assign(original_eligible=True),
                              on=["signal_date", "ticker"], how="left", validate="one_to_one")
    expected["qualification_status"] = np.select(
        [expected.original_eligible.fillna(False).astype(bool).to_numpy(),
         (~expected.raw_file_available).astype(bool).to_numpy(),
         expected.price_on_signal_date.isna().to_numpy()],
        ["ORIGINAL_RULE_ELIGIBLE", "UNKNOWN_NO_RAW_FILE", "UNKNOWN_NO_DAILY_PRICE_OR_LIFECYCLE"],
        default="ORIGINAL_RULE_INELIGIBLE_LOOKBACK_OR_FEATURE")
    expected[["signal_date", "active_13f_quarter", "ticker", "moomoo_transport_code", "cusip", "qualification_status"]].to_parquet(
        OUT / "candidate_qualification_known_window.parquet", index=False)
    cov = expected.groupby(["signal_date", "qualification_status"], observed=True).size().unstack(fill_value=0).reset_index()
    cov["expected_members"] = expected.groupby("signal_date").size().to_numpy()
    cov.to_csv(OUT / "daily_coverage_known_window.csv", index=False)
    # Save opportunity grid and its identity before any model prediction or label read.
    grid = features[["signal_date", "ticker", *r1.FEATURE_COLUMNS]].copy()
    grid.to_parquet(OUT / "common_feature_grid_known_window.parquet", index=False)
    grid_sha = sha(OUT / "common_feature_grid_known_window.parquet")
    models = {m: joblib.load(p) for m, p in artifacts.items()}
    predictions = []
    from contextlib import ExitStack
    with ExitStack() as stack:
        for cls in (HistGradientBoostingRegressor, Ridge, ElasticNet, MLPRegressor, StandardScaler):
            stack.enter_context(patch.object(cls, "fit", forbid))
            if hasattr(cls, "partial_fit"):
                stack.enter_context(patch.object(cls, "partial_fit", forbid))
            if hasattr(cls, "fit_transform"):
                stack.enter_context(patch.object(cls, "fit_transform", forbid))
        X = grid.loc[:, r1.FEATURE_COLUMNS].to_numpy(float)
        assert np.isfinite(X).all()
        for method in METHODS:
            result = grid[["signal_date", "ticker"]].copy()
            result["method"] = method
            result["prediction"] = models[method].predict(X)
            assert np.isfinite(result.prediction).all()
            result["rank"] = r1._prediction_rank(result, "prediction")
            result["model_sha256"] = EXPECTED[method]
            result["feature_grid_sha256"] = grid_sha
            predictions.append(result)
    predictions = pd.concat(predictions, ignore_index=True)
    predictions.to_parquet(OUT / "predictions_known_window.parquet", index=False)
    predictions.loc[predictions["rank"].le(20)].to_parquet(OUT / "top20_known_window.parquet", index=False)
    after = {str(p): sha(p) for p in protected}
    assert before == after
    record = {"scope": "KNOWN_INPUT_WINDOW_DIAGNOSTIC_ONLY", "first_signal_date": str(test_dates.min().date()),
        "last_signal_date": str(test_dates.max().date()), "formal_test_asof_utc": contract["test_asof_utc"],
        "formal_window_complete": False, "2026_price_and_qqq_calendar_through": str(available.date()),
        "quarter_manifest_last": str(qmanifest.quarter.iloc[-1]), "expected_candidate_rows": len(expected),
        "eligible_prediction_rows_per_method": len(grid), "candidate_status_counts": expected.qualification_status.value_counts().to_dict(),
        "model_fit_calls_observed": 0, "preprocessor_fit_calls_observed": 0,
        "fit_call_protection": "patched sklearn estimator/scaler fit, partial_fit, fit_transform to raise during predict",
        "protected_sha256_before": before, "protected_sha256_after": after,
        "prediction_sha256": sha(OUT / "predictions_known_window.parquet"),
        "top20_sha256": sha(OUT / "top20_known_window.parquet"),
        "feature_grid_sha256": grid_sha, "no_strategy_evaluation": "Unknown pool and missing price/calendar after available snapshot; partial ranks are not formal full-pool ranks",
        "source_price_audit": {k:v for k,v in price_audit.items() if k != "event_audit"}}
    (OUT / "inference_audit.json").write_text(json.dumps(record, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(json.dumps({k:record[k] for k in ("first_signal_date","last_signal_date","expected_candidate_rows","eligible_prediction_rows_per_method","candidate_status_counts")}, default=str), flush=True)


if __name__ == "__main__":
    main()
