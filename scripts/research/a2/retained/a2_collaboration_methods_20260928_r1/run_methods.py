"""Fixed collaboration evaluation: 11 policies, 2 windows, no fitting allowed."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import sys
import time
sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
from portfolio_policy import ENGINE, BASES, COMBINATIONS, POLICIES, CollaborationPolicy
from engine_v2 import run_replay, OperationalExit
from context_features import attach_context, CONTEXTS

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
LEDGERS = ["daily", "trades", "positions", "target_decisions", "diagnostics", "valuation_intervals",
           "raw_model_outputs", "signal_contexts", "operational_actions", "execution_results"]


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def write(path, value):
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def no_fit():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import Pipeline
    counter = {"attempts": 0}
    def denied(*args, **kwargs):
        counter["attempts"] += 1
        raise RuntimeError("FITTING_FORBIDDEN_DURING_FIXED_EVALUATION")
    for cls in [Ridge, StandardScaler, HistGradientBoostingRegressor, MLPRegressor, Pipeline]:
        for name in ["fit", "partial_fit", "fit_transform"]:
            if hasattr(cls, name):
                setattr(cls, name, denied)
    return counter


def load_inputs(year):
    if year == 2025:
        feature_path = WORK / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
        price_path = WORK / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
        calendar_path = None
        panel = pd.read_parquet(feature_path)
        panel = panel.loc[panel.signal_date.between("2025-07-01", "2025-12-29")].copy()
        prices = pd.read_parquet(price_path)
        calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ") & prices.trade_date.between("2025-07-01", "2025-12-31"), "trade_date"].unique()))
        first, last = "2025-07-01", "2025-12-29"
        paths = [feature_path, price_path]
    else:
        feature_path = WORK / "a2_qualification_holdings_v1_20260927/data/test_features_context.parquet"
        price_path = WORK / "a2_qualification_holdings_v1_20260927/data/test_prices.parquet"
        calendar_path = WORK / "a2_latest_effective_joint_20260927/data/calendar.parquet"
        panel = pd.read_parquet(feature_path)
        panel = panel.loc[panel.signal_date.between("2026-01-02", "2026-09-22")].copy()
        prices = pd.read_parquet(price_path)
        calendar = pd.DatetimeIndex(pd.read_parquet(calendar_path).query("is_test").trade_date)
        first, last = "2026-01-02", "2026-09-22"
        paths = [feature_path, price_path, calendar_path]
    early = {"2025-07-03", "2025-11-28", "2025-12-24"}
    asofs = {day: (day + pd.Timedelta(hours=13 if str(day.date()) in early else 16)).tz_localize("America/New_York").tz_convert("UTC") for day in calendar}
    ops = {}
    if year == 2026:
        evidence = WORK / "a2_qualification_holdings_v1_20260927/data/operational_exit_evidence.csv"
        paths.append(evidence)
        events = pd.read_csv(evidence)
        events["known_at"] = pd.to_datetime(events.known_at, utc=True)
        events["effective_date"] = pd.to_datetime(events.effective_date)
        for day in calendar:
            known = events.loc[(events.known_at <= asofs[day]) & (events.effective_date <= day)]
            if len(known):
                ops[day] = {str(r.ticker): OperationalExit(str(r.reason), r.known_at, str(r.source_id)) for r in known.itertuples()}
    return panel, prices, calendar, first, last, asofs, ops, paths


def forecasts(year, panel, stage):
    from base_train import load_base_models, FEATURES
    from meta_train import FrozenMeta
    if stage != ("validation" if year == 2025 else "final"):
        raise ValueError("EVALUATION_YEAR_STAGE_MISMATCH")
    vintage = "oof_2025" if year == 2025 else "final"
    models = load_base_models(vintage)
    values = panel[FEATURES].to_numpy(float)
    assert np.isfinite(values).all()
    out = panel[["signal_date", "ticker", "new_buy_eligible", "avg_dollar_volume_20d",
                 "ret_20d", "realized_vol_20d", "price_vs_ma20"]].copy()
    for base in BASES:
        out["p_" + base] = models[base].predict(values)
    out = attach_context(out)
    meta = FrozenMeta(stage)
    predictions = out[["p_" + b for b in BASES]].to_numpy(float)
    contexts = out[CONTEXTS].to_numpy(float)
    for name in COMBINATIONS:
        if name != "decision_blend":
            out["f_" + name] = meta.predict(name, predictions, contexts)
    gate = meta.gate_weights(contexts)
    assert np.allclose(gate.sum(axis=1), 1) and (gate >= .05 - 1e-9).all()
    for i, base in enumerate(BASES):
        out["gate_" + base] = gate[:, i]
    assert np.isfinite(out.select_dtypes(include=["number"]).to_numpy(float)).all()
    return out, np.asarray(meta.coefficients, float)


def audit(result, panel, calendar):
    daily, trades, positions, targets = result.daily, result.trades, result.positions, result.target_decisions
    assert pd.DatetimeIndex(daily.date).equals(calendar)
    assert daily.cash.ge(-1e-7).all() and daily.actual_name_count.le(20).all()
    change = trades.assign(cash_flow=np.where(trades.side.eq("SELL"), trades.notional, -trades.notional) - trades.transaction_cost)
    expected_cash = 1e6 + change.groupby("execution_date").cash_flow.sum().reindex(calendar, fill_value=0).cumsum()
    cash_error = float(np.max(np.abs(expected_cash.to_numpy() - daily.cash.to_numpy())))
    assert cash_error < 1e-5
    assert np.allclose(trades.transaction_cost, trades.notional * .001, rtol=0, atol=1e-7)
    assert np.allclose(trades.index_units * trades.price, trades.notional, rtol=0, atol=1e-6)
    next_session = dict(zip(calendar[:-1], calendar[1:]))
    assert (trades.signal_date.map(next_session) == trades.execution_date).all()
    buys = trades.loc[trades.side.eq("BUY")].merge(targets[["order_id", "signal_day_adv"]], on="order_id", validate="one_to_one")
    buys = buys.merge(panel[["signal_date", "ticker", "new_buy_eligible"]], on=["signal_date", "ticker"], how="left", validate="many_to_one")
    assert buys.new_buy_eligible.fillna(False).all()
    assert (buys.notional <= .01 * buys.signal_day_adv + 1e-6).all()
    market = positions.groupby("date").market_value.sum().reindex(calendar, fill_value=0)
    good = daily.nav.notna()
    assert np.allclose(daily.loc[good, "nav"], daily.loc[good, "cash"] + market.to_numpy()[good], rtol=0, atol=1e-5)
    assert targets.raw_model_weight.dropna().le(.0475 + 1e-8).all()
    return {"status": "PASS", "cash_error_max_usd": cash_error, "days": len(daily),
            "uncertified_days": int(daily.certified_nav.isna().sum()), "max_actual_names": int(daily.actual_name_count.max()),
            "price_index_only": True}


def metrics(result, name, year):
    daily = result.daily
    nav = np.r_[1e6, daily.nav.to_numpy(float)]
    finite = np.isfinite(nav).all()
    return {"policy": name, "year": year, "days": len(daily),
            "indicative_net_return": float(nav[-1] / 1e6 - 1) if np.isfinite(nav[-1]) else None,
            "indicative_max_drawdown": float((nav / np.maximum.accumulate(nav) - 1).min()) if finite else None,
            "mean_actual_cash": float(daily.cash_weight.mean()), "fees_usd": float(daily.transaction_cost_amount.sum()),
            "half_turnover": float(daily.turnover.sum()), "trades": len(result.trades),
            "uncertified_days": int(daily.certified_nav.isna().sum()),
            "actual_names_max": int(daily.actual_name_count.max()),
            "active_exit_decisions": int(result.target_decisions.decision_semantic.eq("MODEL_ACTIVE_EXIT").sum()),
            "no_decision_held_events": int((result.target_decisions.decision_semantic.eq("MODEL_NO_DECISION") & result.target_decisions.current_units.gt(0)).sum()),
            "rejected_orders": int(result.execution_results.status.eq("REJECTED").sum()),
            "blind_test": False, "shareholder_total_return_certified": False, "source": "new_fixed_collaboration_batch"}


def main(year):
    out = ROOT / f"evaluation_{year}"
    if (out / "COMPLETE.json").exists():
        raise RuntimeError("COMPLETED_EVALUATION_PRESERVED")
    stage = "validation" if year == 2025 else "final"
    assert read(ROOT / "DESIGN_LOCK.json")["status"] == "LOCKED_BEFORE_NEW_FITS"
    assert read(ROOT / "base_artifacts/TRAIN_RECEIPT.json")["status"] == "PASS_FIXED_NINE_BASE_FITS"
    assert read(ROOT / "meta_artifacts/TRAIN_RECEIPT.json")["status"] == "PASS"
    guard = no_fit()
    panel, prices, calendar, first, last, asofs, ops, input_paths = load_inputs(year)
    out.mkdir(exist_ok=True)
    sources = input_paths + [ROOT / n for n in ["portfolio_policy.py", "run_methods.py", "context_features.py", "DESIGN_CONTRACT.md", "DESIGN_LOCK.json", "base_train.py", "meta_train.py", "NEW_DATA_ADMISSION.json"]]
    sources += [ENGINE / "engine_v2.py"]
    for folder in ["base_artifacts", "meta_artifacts"]:
        sources += [p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in [".joblib", ".npz", ".json"]]
    binding = {str(p): sha(p) for p in sources}
    if (out / "FROZEN_BEFORE_REPLAY.json").exists():
        assert read(out / "FROZEN_BEFORE_REPLAY.json")["source_sha256"] == binding
    else:
        write(out / "FROZEN_BEFORE_REPLAY.json", {"source_sha256": binding, "stage": stage, "year": year, "policies": POLICIES,
            "cost_bps_one_way": 10, "same_full_window": True, "parameter_searches": 0})
    frame, coefficients = forecasts(year, panel, stage)
    frame.to_parquet(out / "FROZEN_FORECASTS.parquet", index=False)
    pd.DataFrame(frame.groupby("signal_date", sort=True)[["gate_" + b for b in BASES]].first()).to_csv(out / "DAILY_GATE_WEIGHTS.csv")
    rows = []
    for name in POLICIES:
        folder = out / name
        if (folder / "PATH_COMPLETE.json").exists():
            prior = read(folder / "PATH_COMPLETE.json")
            assert all(sha(folder / f"{key}.parquet") == digest for key, digest in prior["ledger_sha256"].items())
            rows.append(prior["metrics"])
            continue
        if folder.exists():
            raise RuntimeError(f"PARTIAL_PATH_MUST_BE_INSPECTED:{folder}")
        folder.mkdir()
        started = time.monotonic()
        actor = CollaborationPolicy(name, coefficients)
        result = run_replay(prices, calendar, frame, actor, candidate=name, initial_cash=1e6, initial_positions={}, cost_bps=10,
            capacity_fraction=.01, max_weight=.10, max_invested=.95, max_positions=20, signal_start=first, signal_end=last,
            signal_asof=asofs, operational_exits_by_signal=ops, capacity_on_sells=False)
        for key in LEDGERS:
            getattr(result, key).to_parquet(folder / f"{key}.parquet", index=False)
        write(folder / "metadata.json", result.metadata)
        checked = audit(result, frame, calendar)
        if year == 2025:
            assert checked["days"] == 128 and checked["uncertified_days"] == 0
        else:
            assert checked["days"] == 183
        row = metrics(result, name, year)
        row["seconds"] = time.monotonic() - started
        write(folder / "PATH_COMPLETE.json", {"audit": checked, "metrics": row,
             "ledger_sha256": {key: sha(folder / f"{key}.parquet") for key in LEDGERS}})
        rows.append(row)
        pd.DataFrame(rows).to_csv(out / "COMPARISON.csv", index=False)
        print(json.dumps(clean(row), ensure_ascii=False), flush=True)
    assert guard["attempts"] == 0
    assert all(sha(path) == digest for path, digest in binding.items())
    write(out / "COMPLETE.json", {"status": "PASS", "policies": len(rows), "year": year, "stage": stage,
         "evaluation_fit_attempts": 0, "source_unchanged": True, "blind_test": False,
         "shareholder_total_return_certified": False, "all_dates_preserved": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=[2025, 2026], required=True)
    args = parser.parse_args()
    main(args.year)
