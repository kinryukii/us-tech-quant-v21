"""V24 stage adapters; pure estimators and immutable replay own the mechanics."""
from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
import hashlib
import inspect
from pathlib import Path
import numpy as np
import pandas as pd

from scripts.research.a2.data.joint_input_binding import load_training_inputs, load_held_features, guard_parquet, FEATURES
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
from scripts.v22.corporate_action_transition_r1 import CorporateActionTransition
from scripts.research.a2.evaluation.joint_method_coverage import (
    JointMethodCoverage, mature_training_mask,
)
from scripts.research.a2.evaluation.joint_execution_resume import digest
from scripts.research.a2.risk import joint_risk_estimators as risk

RISK_ROWS = [
    (50, "DIAG"), (51, "SCOV"), (52, "LW"), (53, "OAS"),
    (54, "CONSTANT_CORR"), (55, "PCA"), (56, "FA"), (57, "SINGLE_INDEX"),
    (58, "INDUSTRY"), (59, "FUNDAMENTAL"), (60, "EWMA"), (61, "HISTVOL"),
    (62, "GARCH"), (63, "GJR_GARCH"), (64, "GRAPHICAL_LASSO"),
    (65, "ROBUST_COV"), (66, "NONLINEAR_SHRINKAGE"), (67, "COV_ENSEMBLE"),
]


EXPOSURE_SOURCES = {
    "INDUSTRY": {
        "path": "D:/us-tech-quant-results/A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1/pit_sec_sic_ff12_ff48_eligible_surface.parquet",
        "sha256": "591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646",
        "date_fields": ["decision_date", "sic_available_at"],
        "columns": ["decision_date", "ticker_at_date", "identity_status", "sic_available_at",
                    "sic_source_sha256", "ff48_code", "taxonomy_status"],
        "loading": "last earlier qualified source decision row; FF48 one-hot as-of annual fit cutoff",
    },
    "FUNDAMENTAL": {
        "path": "D:/us-tech-quant-results/A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1/fundamental_feature_ledger.parquet",
        "sha256": "2789c80596e9758c7a984529f034a389594aa6aa7cbf9d88bc99c8cd9c933aef",
        "date_fields": ["accepted_datetime", "feature_effective_date", "mapping_effective_date"],
        "columns": ["ticker", "accepted_datetime", "feature_effective_date", "mapping_effective_date",
                    "mapping_source", "mapping_confidence", "coverage_status",
                    "corporate_action_scale_consistent", "accepted_source_sha256",
                    "revenue_yoy", "operating_margin", "asset_growth_yoy", "accrual_quality"],
        "loading": "latest earlier accepted/effective/mapping-qualified filing; four fixed finite fundamental loadings",
    },
}


def load_exposure_sources():
    result = {}
    for kind, source in EXPOSURE_SOURCES.items():
        file, _ = guard_parquet(source["path"], source["sha256"], source["date_fields"])
        result[kind] = file.read(columns=source["columns"]).to_pandas()
    return result


def asof_exposures(kind, frame, cutoff):
    """Current fit-cutoff loadings, not a reconstructed historical classification."""
    cutoff = pd.Timestamp(cutoff)
    if kind == "INDUSTRY":
        f = frame.copy()
        f["decision_date"] = pd.to_datetime(f.decision_date)
        available = pd.to_datetime(f.sic_available_at, utc=True, errors="coerce")
        signal = (f.decision_date + pd.Timedelta(hours=16)).dt.tz_localize(
            "America/New_York").dt.tz_convert("UTC")
        ok = (f.decision_date.lt(cutoff) & available.lt(cutoff.tz_localize("UTC"))
              & available.le(signal) & f.identity_status.eq("AUTHORITATIVE")
              & f.taxonomy_status.eq("STRICT_PIT_SIC_FF12_FF48_MAPPED")
              & f.sic_source_sha256.notna() & f.ff48_code.notna())
        f = f.loc[ok].sort_values(["decision_date", "ticker_at_date"], kind="stable")
        f = f.drop_duplicates("ticker_at_date", keep="last")
        if f.empty:
            return None
        exposures = pd.get_dummies(f.set_index("ticker_at_date").ff48_code.astype(str),
                                   prefix="FF48", dtype=float)
        latest = pd.to_datetime(f.sic_available_at, utc=True).max().tz_localize(None)
    else:
        f = frame.copy()
        available = pd.to_datetime(f.accepted_datetime, utc=True, errors="coerce")
        feature_date = pd.to_datetime(f.feature_effective_date)
        mapping_date = pd.to_datetime(f.mapping_effective_date)
        columns = ["revenue_yoy", "operating_margin", "asset_growth_yoy", "accrual_quality"]
        ok = (available.lt(cutoff.tz_localize("UTC")) & feature_date.lt(cutoff)
              & mapping_date.lt(cutoff) & f.coverage_status.eq(True)
              & f.corporate_action_scale_consistent.eq(True)
              & f.mapping_confidence.isin(["A_EXISTING_AUDITED", "B_HISTORICAL_EXACT_NAME"])
              & f.mapping_source.notna() & f.accepted_source_sha256.notna()
              & np.isfinite(f[columns].to_numpy(float)).all(axis=1))
        f["available_for_sort"] = available
        f = f.loc[ok].sort_values(["available_for_sort", "ticker"], kind="stable").drop_duplicates("ticker", keep="last")
        if f.empty:
            return None
        exposures = f.set_index("ticker")[columns].astype(float)
        latest = max(f.available_for_sort.max().tz_localize(None),
                     pd.to_datetime(f.feature_effective_date).max(),
                     pd.to_datetime(f.mapping_effective_date).max())
    exposures.attrs.update(pit_qualified=True, source_id=EXPOSURE_SOURCES[kind]["sha256"],
                           available_at=str(latest),
                           definition="static current-asof fit-cutoff loadings; not historical feature backfill")
    return exposures


def run_risk(root):
    task = JointMethodCoverage(root)
    binding = task.read("INPUT_BINDING.json")
    if not binding.get("full848_label_extension"):
        raise RuntimeError("Full848 label input is not bound")
    frame = load_training_inputs(binding)
    specs = risk.specs()
    exposure_sources = load_exposure_sources()
    freeze = {"status": "FIXED_BEFORE_RISK_FITS", "risk_specifications": specs,
              "risk_source_sha256": digest(risk.__file__),
              "caller_functions_sha256": hashlib.sha256("".join(inspect.getsource(f) for f in [run_risk, load_exposure_sources, asof_exposures]).encode()).hexdigest(),
              "input_binding_sha256": task.input_sha,
              "years": [2021, 2022, 2023, 2024, 2025],
              "return_unit": "FIVE_SESSION_SOURCE_BACKED_SHAREHOLDER_VALUE",
              "market_factor": "contemporaneous date-equal legal PIT cross-section mean of matured five-session returns",
              "industry_fundamental": EXPOSURE_SOURCES,
              "exposure_semantics": "static current-asof cutoff loadings for prior-return covariance estimation, never historical feature or universe backfill",
              "unknown_asset_rule": "prior median variance independent correlation; no eligibility upgrade",
              "test2026_reads": 0}
    dest = "receipts/RISK_FIT_FREEZE.json"
    if task.out(dest).exists() and task.read(dest) != freeze:
        raise RuntimeError("Risk freeze changed after fit")
    if not task.out(dest).exists():
        task.write(dest, freeze)
    records = []
    for year in [2021, 2022, 2023, 2024, 2025]:
        train = frame.loc[mature_training_mask(frame, f"{year}-01-01")].copy()
        table = train.pivot(index="signal_date", columns="ticker", values="y_open5").sort_index()
        market = table.mean(axis=1)
        annual = {}
        for row, kind in RISK_ROWS:
            if kind == "HISTVOL":
                annual[kind] = annual["DIAG"]
                records.append({"method_id": f"M{row:03d}", "year": year,
                                "status": "DIRECT_REUSE_MATHEMATICALLY_EQUIVALENT",
                                "equivalent_method": "DIAG", "reason": "same input/window/ddof1 diagonal variance",
                                "artifact": str(task.out(f"models/risk_DIAG_{year}.joblib"))})
                continue
            params = {"fit_cutoff": f"{year}-01-01",
                      "return_unit": "FIVE_SESSION_SOURCE_BACKED_SHAREHOLDER_VALUE",
                      "return_horizon_sessions": 5, "source_id": task.input_sha}
            exposure = asof_exposures(kind, exposure_sources[kind], f"{year}-01-01") if kind in exposure_sources else None
            exposure_key = None if exposure is None else {"source": exposure.attrs, "assets": exposure.index.tolist(), "factors": exposure.columns.tolist()}
            count = {"PCA": 4, "FA": 4, "SINGLE_INDEX": 4,
                     "INDUSTRY": 4, "FUNDAMENTAL": 4, "GARCH": 4,
                     "GJR_GARCH": 4, "COV_ENSEMBLE": 3}.get(kind, 2)
            bundle = task.fit_state("risk_"+kind, year, {"specification": specs[kind], "params": params, "exposure": exposure_key},
                                    train[["signal_date", "ticker", "label_end_date",
                                           "label_mature_date", "y_open5"]],
                                    lambda kind=kind: risk.fit_risk_estimator(
                                        kind, table, market_returns=market, exposure_frame=exposure, params=params),
                                    state_count=count)
            annual[kind] = bundle
            rec = {"method_id": f"M{row:03d}", "kind": kind, "year": year,
                   "status": bundle.status, "reason": bundle.failure_reason,
                   "estimated_assets": len(bundle.estimated_assets),
                   "training_rows": len(train), "return_dates": len(table),
                   "last_mature_label": str(train.label_mature_date.max()),
                   "actual_estimated_state_counts": bundle.budget,
                   "counted_fit_attempt_upper_bound": count,
                   "artifact": str(task.out(f"models/risk_{kind}_{year}.joblib")),
                   "sha256": digest(task.out(f"models/risk_{kind}_{year}.joblib"))}
            records.append(rec)
            task.write("receipts/RISK_FIT_PROGRESS.json", {"records": records, "test2026_reads": 0})
    task.write("receipts/REAL_RISK_FITS.json", {"status": "ALL18_RISK_ROLES_ATTEMPTED",
                                             "records": records, "test2026_reads": 0})
    coverage = pd.read_csv(task.out("METHOD_COVERAGE.csv"))
    for row, kind in RISK_ROWS:
        states = {r["status"] for r in records if r["method_id"] == f"M{row:03d}"}
        status = ("REAL_ANNUAL_RISK_FIT_COMPLETE" if states == {"FITTED"} else
                  "DIRECT_REUSE_MATHEMATICALLY_EQUIVALENT" if row == 61 else
                  "ATTEMPTED_"+"_".join(sorted(states)))
        mask = coverage.method_id.eq(f"M{row:03d}")
        coverage.loc[mask, "status"] = status
        coverage.loc[mask, "evidence"] = "receipts/REAL_RISK_FITS.json"
    coverage.to_csv(task.out("METHOD_COVERAGE.csv"), index=False)
    task.status["status"] = "ALL_RISK_METHOD_ATTEMPTS_COMPLETE"
    task.checkpoint()




@contextmanager
def task_writer(root):
    """A task-owned command lease; all FIT_STATUS writers execute sequentially."""
    lock_path = Path(root).resolve() / "work/WRITER_LOCK"
    with lock_path.open("a+b") as lease:
        lease.seek(0)
        if lease.read(1) == b"":
            lease.write(b"1")
            lease.flush()
        lease.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("V24 writer already active; do not start a concurrent status writer") from exc
            try:
                yield
            finally:
                lease.seek(0)
                msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lease, fcntl.LOCK_UN)


def market_dependencies(task):
    result = {"run_config": digest(task.out("RUN_CONFIG.json")),
              "input_binding": task.input_sha,
              "market_constructor": hashlib.sha256(inspect.getsource(prepare_market).encode()).hexdigest(),
              "input_adapter": digest(__import__(
                  "scripts.research.a2.data.joint_input_binding", fromlist=["__file__"]).__file__),
              "initial_fit_source": digest(__import__(
                  "scripts.research.a2.evaluation.joint_method_coverage", fromlist=["__file__"]).__file__),
              "raw_control": digest("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet"),
              "oof": {}}
    for year in [2021, 2022, 2023, 2024, 2025]:
        receipt = task.read(f"receipts/INITIAL_{year}.json")
        path = task.out(f"OOF/INITIAL_{year}.parquet")
        actual = digest(path)
        if actual != receipt["sha256"]:
            raise RuntimeError("Initial OOF artifact changed")
        result["oof"][str(year)] = actual
    for rec in task.status["records"]:
        if rec["status"] == "FIT_COMPLETE" and rec["identity"]["kind"].startswith("five_day"):
            if digest(rec["artifact"]) != rec["sha256"]:
                raise RuntimeError("Initial fitted artifact changed")
    return result


def prepare_market(root):
    """One guarded pre-2026 market projection, shared by real account/RL stages."""
    task = JointMethodCoverage(root)
    binding = task.read("INPUT_BINDING.json")
    path = task.out("cache/market_and_inputs.joblib")
    receipt = "receipts/MARKET_INPUTS.json"
    if path.exists():
        import joblib
        old = task.read(receipt)
        if (old["input_binding_sha256"] != task.input_sha or old["sha256"] != digest(path)
                or old.get("build_dependencies") != market_dependencies(task)):
            raise RuntimeError("Bound market cache identity changed")
        return joblib.load(path)
    source = binding["sources"]["calendar"]
    file, _ = guard_parquet(source["path"], source["sha256"], ["trade_date"])
    dates = pd.DatetimeIndex(file.read(columns=["trade_date"]).to_pandas().trade_date)
    dates = dates[(dates >= pd.Timestamp("2021-01-01")) & (dates < pd.Timestamp("2026-01-01"))]
    raw = binding["sources"]["raw_prices"]
    file, _ = guard_parquet(raw["path"], raw["sha256"], ["trade_date"])
    prices = file.read(columns=["trade_date", "ticker", "open", "close"]).to_pandas()
    prices.trade_date = pd.to_datetime(prices.trade_date)
    tickers = np.asarray(sorted(prices.ticker.unique()), dtype=str)
    ti = pd.Index(tickers)
    di = pd.Index(dates)
    shape = (len(dates), len(tickers))
    def indices(frame, date="signal_date"):
        return di.get_indexer(frame[date]), ti.get_indexer(frame.ticker)
    def numeric_cube(frame, column, date="signal_date", default=np.nan):
        a = np.full(shape, default, dtype=float)
        ri, ci = indices(frame, date)
        valid = (ri >= 0) & (ci >= 0)
        a[ri[valid], ci[valid]] = frame[column].to_numpy(float)[valid]
        return a
    volumes = []
    for part in binding["sources"]["forward_rehab_surface"]["partitions"]:
        file, _ = guard_parquet(part["path"], part["sha256"], ["trade_date"])
        volumes.append(file.read(columns=["trade_date", "ticker", "volume"]).to_pandas())
    volume = pd.concat(volumes, ignore_index=True)
    volume.trade_date = pd.to_datetime(volume.trade_date)
    prices = prices.merge(volume, on=["trade_date", "ticker"], validate="one_to_one")
    prices = prices.sort_values(["ticker", "trade_date"], kind="stable")
    prices["dollar_volume"] = prices.close * prices.volume
    prices["adv"] = prices.groupby("ticker", sort=False).dollar_volume.transform(
        lambda x: x.rolling(20, min_periods=20).mean())
    frame = load_training_inputs(binding)
    held = load_held_features(binding)
    held.signal_date = pd.to_datetime(held.signal_date)
    present = numeric_cube(held.assign(flag=1), "flag", default=0).astype(bool)
    pool = numeric_cube(frame.assign(flag=frame.trade_eligible.astype(int)), "flag", default=0).astype(bool)
    op = numeric_cube(prices, "open", date="trade_date")
    close = numeric_cube(prices, "close", date="trade_date")
    row_present = numeric_cube(prices.assign(flag=1), "flag", date="trade_date", default=0).astype(bool)
    adv = numeric_cube(prices, "adv", date="trade_date")
    features = np.stack([numeric_cube(held, name) for name in FEATURES], axis=2)
    market = MarketArrays(dates, tickers, op, close, row_present=row_present, adv=adv,
                          input_present=present, new_buy_eligible=pool,
                          signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize("America/New_York")
                                       for d in dates])
    initial = pd.concat([pd.read_parquet(task.out(f"OOF/INITIAL_{y}.parquet"))
                         for y in [2021, 2022, 2023, 2024, 2025]], ignore_index=True)
    initial.signal_date = pd.to_datetime(initial.signal_date)
    mu = {name: numeric_cube(initial, name+"_mu") for name in ["Ridge", "HGB"]}
    sigma = {name: numeric_cube(initial, name+"_uncertainty") for name in ["Ridge", "HGB"]}
    mu["EQUAL"] = (mu["Ridge"]+mu["HGB"])/2
    sigma["EQUAL"] = np.sqrt((sigma["Ridge"]**2+sigma["HGB"]**2)/4
                            +(mu["Ridge"]-mu["HGB"])**2/4)
    raw_path = "D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet"
    raw_sha = "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468"
    file, _ = guard_parquet(raw_path, raw_sha, ["signal_date"])
    raw_scores = file.read(columns=["signal_date", "ticker", "a2_prediction"]).to_pandas()
    raw_scores.signal_date = pd.to_datetime(raw_scores.signal_date)
    mu["RAW_CONTROL"] = numeric_cube(raw_scores, "a2_prediction")
    sigma["RAW_CONTROL"] = np.where(np.isfinite(mu["RAW_CONTROL"]), 0., np.nan)
    event_source = binding["sources"]["event_binding"]
    if digest(event_source["path"]) != event_source["sha256"]:
        raise RuntimeError("Corporate action binding changed")
    import json
    event_binding = json.loads(Path(event_source["path"]).read_text(encoding="utf-8-sig"))
    actions, known_at, unsupported = [], {}, []
    for event in event_binding["event_records"]:
        day = pd.Timestamp(event["event_date"])
        if day >= pd.Timestamp("2026-01-01"):
            raise ValueError("Corporate action crosses training boundary")
        if event["status"] in {"SHARE_ONLY_SUPPORTED", "FROZEN_TIER1_SHARE_ONLY_SUPPORTED"}:
            action = CorporateActionTransition(
                str(day.date()), "OTHER_SHARE_COUNT_TRANSFORM",
                "FROZEN_VENDOR:"+event["ticker"], "FROZEN_VENDOR:"+event["ticker"],
                event["ticker"], event["ticker"], event["quantity_multiplier"], 0,
                "TIER2_LOCAL_CANONICAL", event_source["path"]+"#"+event["source_fingerprint"],
                event["source_fingerprint"])
            actions.append(action)
            known_at[action.event_fingerprint] = pd.Timestamp(event["known_at_assumption"])
        else:
            unsupported.append({"ticker": event["ticker"], "effective_date": str(day.date()),
                                "reason": event["reason"], "source_reference": event_source["path"],
                                "source_fingerprint": event["source_fingerprint"]})
    # Producer's event uniqueness is preserved by source key; no economic heuristics.
    actions = list({(a.effective_date, a.old_ticker): a for a in actions}.values())
    unsupported = list({(e["ticker"], e["effective_date"], e["reason"]): e for e in unsupported}.values())
    account = dict(base_currency="USD", initial_nav=3000, initial_cash=3000, initial_holdings=[],
                   fractional_shares=True, integer_share_rounding=False, cash_interest=0,
                   transaction_cost_bps=0, financing=False, borrowed_cash=False, long_only=True,
                   max_positions=20, max_weight=.1, max_invested=1, capacity_fraction=.01)
    result = {"market": market, "feature_cube": features, "mu": mu, "sigma": sigma,
              "account": account, "replay_kwargs": {"corporate_actions": actions,
                  "corporate_action_known_at": known_at, "unsupported_events": unsupported}}
    import joblib
    joblib.dump(result, path, compress=3)
    task.write(receipt, {"status": "COMMON_MARKET_READY", "input_binding_sha256": task.input_sha,
                         "path": str(path), "sha256": digest(path), "days": len(dates),
                         "build_dependencies": market_dependencies(task),
                         "tickers": len(tickers), "feature_rows": int(present.sum()),
                         "new_buy_rows": int(pool.sum()), "account": account,
                         "event_supported": len(actions), "event_unsupported": len(unsupported),
                         "adv": "signal-known rolling20 raw close*existing source volume; no endpoint screen",
                         "raw_control_columns": ["signal_date", "ticker", "a2_prediction"],
                         "test2026_reads": 0})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task-root", required=True)
    p.add_argument("command", choices=["fit-risk", "prepare-market"])
    args = p.parse_args()
    if args.command == 'fit-risk':
        with task_writer(args.task_root):
            run_risk(args.task_root)
    else:
        prepare_market(args.task_root)


if __name__ == "__main__":
    main()
