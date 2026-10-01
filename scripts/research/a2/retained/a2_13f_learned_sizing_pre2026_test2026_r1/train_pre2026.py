"""Fixed pre-2026 sizing fits; this module never opens 2026 data."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "a2_top20_13f_sizing_pilot_r1"
sys.path.insert(0, str(OLD))
from run import load_prices, get_module, R4, sha  # noqa: E402

FULL = ["r", "log_sigma20", "u", "u_squared", "v", "v_squared", "breadth", "r_times_v", "age_times_v"]
ABLATION = FULL[:2]
LAMBDAS = (0.01, 0.10)
FOLDS = [
    ("DEV_1", "2023-12-31", "2024-01-01", "2024-06-30"),
    ("DEV_2", "2024-06-30", "2024-07-01", "2024-12-31"),
]


def capped(q: np.ndarray, gross: float = 1.0) -> np.ndarray:
    if gross == 0:
        return np.zeros_like(q)
    upper = 0.10 * gross
    if np.any(q < 0) or not np.isfinite(q).all() or abs(q.sum() - gross) > 1e-10:
        raise ValueError("BAD_UNCAPPED_TARGET")
    if np.max(q) <= upper:
        return q.copy()  # exact theta=0 identity
    low, high = float(q.min() - upper), float(q.max())
    for _ in range(60):
        middle = (low + high) / 2
        if np.clip(q - middle, 0, upper).sum() > gross:
            low = middle
        else:
            high = middle
    w = np.clip(q - (low + high) / 2, 0, upper)
    # A tiny conservation adjustment at a non-bound coordinate.
    delta = gross - w.sum()
    if abs(delta) > 1e-12:
        free = np.flatnonzero((w > 1e-12) & (w < upper - 1e-12))
        if len(free):
            w[free[0]] += delta
    if abs(w.sum() - gross) > 1e-10:
        raise RuntimeError("PROJECTION_NOT_CONSERVED")
    return w


def targets(phi: np.ndarray, theta: np.ndarray, usable: np.ndarray) -> np.ndarray:
    score = np.einsum("djk,k->dj", phi, theta)
    score -= score.max(axis=1, keepdims=True)
    raw = np.exp(score)
    raw /= raw.sum(axis=1, keepdims=True)
    out = np.empty_like(raw)
    for d in range(len(raw)):
        out[d] = capped(raw[d]) if usable[d] else 0.05
    return out


def transform(raw: np.ndarray, train_days: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    subset = raw[train_days].reshape(-1, raw.shape[-1])
    if not np.isfinite(subset).all():
        raise RuntimeError("NONFINITE_TRAIN_FEATURE")
    mean = subset.mean(axis=0)
    std = subset.std(axis=0)
    constant = std < 1e-12
    safe = np.where(constant, 1.0, std)
    result = np.clip((raw - mean) / safe, -5, 5)
    result[:, :, constant] = 0.0
    return result, mean, std


def load_data():
    panel = pd.read_parquet(HERE / "PIT_PRE2026_TOP20_VH_PANEL.parquet")
    panel = panel.sort_values(["signal_date", "a2_rank"]).reset_index(drop=True)
    dates = pd.DatetimeIndex(panel.signal_date.unique())
    assert len(dates) == 750 and len(panel) == 15000
    assert panel.groupby("signal_date").size().eq(20).all()
    assert panel.groupby("signal_date").a2_rank.apply(lambda x: set(x) == set(range(1, 21))).all()
    ticker_names = sorted(panel.ticker.unique())
    prices = load_prices({"US." + x for x in ticker_names})
    prices = prices.assign(ticker=prices.ticker.str.removeprefix("US."))
    qqq = prices.loc[prices.ticker.eq("QQQ"), "trade_date"]
    calendar = pd.DatetimeIndex(sorted(qqq))
    assert dates.isin(calendar).all()
    open_wide = prices.pivot(index="trade_date", columns="ticker", values="open").reindex(index=calendar, columns=ticker_names)
    close_wide = prices.pivot(index="trade_date", columns="ticker", values="close").reindex(index=calendar, columns=ticker_names)
    # 20 completed historical close-to-close returns, including signal close.
    returns = close_wide.pct_change(fill_method=None)
    sigma = returns.rolling(20, min_periods=20).std(ddof=0)
    vol = np.array([sigma.at[r.signal_date, r.ticker] for r in panel.itertuples()], dtype=float).reshape(-1, 20)
    legal = np.isfinite(vol).all(axis=1) & (vol > 0).all(axis=1)
    usable = panel.groupby("signal_date").full_vh_usable.all().to_numpy() & legal
    vol[~np.isfinite(vol) | (vol <= 0)] = 1.0  # all affected days use B0; finite transform only
    r = (1 - 2 * (panel.a2_rank.to_numpy().reshape(-1, 20) - 1) / 19).astype(float)
    m = panel.M_full_initial_usd.to_numpy().reshape(-1, 20)
    c = panel.C_full_initial.to_numpy().reshape(-1, 20)
    breadth = panel.B_full_initial.to_numpy().reshape(-1, 20)
    age = (panel.signal_date - panel.report_date).dt.days.to_numpy().reshape(-1, 20) / 365
    assert (age >= 0).all() and np.isfinite(m).all() and np.isfinite(c).all()
    u, v = np.log1p(m / 1e6), np.log1p(1000 * c)
    raw = np.stack([r, np.log(vol), u, u*u, v, v*v, breadth, r*v, age*v], axis=2)
    # Price matrix is indexed by execution session; target signal on previous session.
    positions = calendar.get_indexer(dates)
    assert (positions >= 0).all() and (positions + 2 < len(calendar)).all()
    execution = calendar[positions + 1]
    path_end = calendar[positions + 2]
    ticker_id = {name: i for i, name in enumerate(ticker_names)}
    name_ids = np.array([ticker_id[t] for t in panel.ticker]).reshape(-1, 20)
    opens = open_wide.to_numpy(dtype=float)
    return panel, dates, execution, path_end, usable, raw, name_ids, opens, calendar, prices


def replay(day_indices: np.ndarray, weights: np.ndarray, name_ids: np.ndarray,
           opens: np.ndarray, calendar: pd.DatetimeIndex, dates: pd.DatetimeIndex,
           detailed: bool = False) -> tuple[float, list[dict]]:
    """R4/R0F no-action adapter numerical core, checked against native R4 below."""
    if len(day_indices) == 0:
        raise RuntimeError("EMPTY_PATH")
    start = int(calendar.get_loc(dates[day_indices[0]])) + 1
    stop = int(calendar.get_loc(dates[day_indices[-1]])) + 2
    if not np.array_equal(day_indices, np.arange(day_indices[0], day_indices[-1]+1)):
        raise RuntimeError("GAPPED_EXECUTION_SEGMENT")
    shares = np.zeros(opens.shape[1], dtype=float)
    cash, nav = 1.0, 1.0
    detail = []
    for k, day in enumerate(range(start, stop + 1)):
        previous_signal_idx = day_indices[0] + k if k < len(day_indices) else -1
        price = opens[day]
        held = shares > 1e-14
        if not np.isfinite(price[held]).all() or np.any(price[held] <= 0):
            raise RuntimeError("MISSING_HELD_OPEN_NEEDS_NATIVE_R4")
        value = np.where(held, shares * np.nan_to_num(price, nan=0), 0)
        pre = cash + value.sum()
        desired = np.zeros_like(value)
        if previous_signal_idx >= 0:
            ids = name_ids[previous_signal_idx]
            if not np.isfinite(price[ids]).all() or np.any(price[ids] <= 0):
                raise RuntimeError("MISSING_TARGET_OPEN_NEEDS_NATIVE_R4")
            desired[ids] = weights[previous_signal_idx] * pre
        sell = np.maximum(0, value - desired)
        sell[sell <= 1e-14] = 0
        shares -= np.divide(sell, price, out=np.zeros_like(sell), where=np.isfinite(price) & (price > 0))
        shares[shares <= 1e-14] = 0
        cash += sell.sum()
        fee = 0.0005 * sell.sum()
        remaining = value - sell
        buy = np.maximum(0, desired - remaining)
        buy[buy <= 1e-14] = 0
        buy_need = buy.sum() * 1.0005
        scale = min(1.0, max(0.0, cash - fee) / buy_need) if buy_need > 0 else 1.0
        buy *= scale
        shares += np.divide(buy, price, out=np.zeros_like(buy), where=np.isfinite(price) & (price > 0))
        cash -= buy.sum()
        fee += 0.0005 * buy.sum()
        cash -= fee
        if cash < -1e-10:
            raise RuntimeError("NEGATIVE_CASH")
        cash = max(0.0, cash)
        nav = cash + (shares * np.nan_to_num(price, nan=0)).sum()
        if abs(nav - (pre - fee)) > 1e-10:
            raise RuntimeError("ACCOUNTING_IDENTITY")
        if detailed:
            detail.append({"execution_date": str(calendar[day].date()), "net_nav": nav,
                           "transaction_cost_amount": fee, "executed_traded_notional": float(sell.sum()+buy.sum()),
                           "cash": cash, "pretrade_nav": pre})
    return float(nav), detail


def native_check(panel, dates, weights, day_indices, prices, fast_nav):
    r4 = get_module(R4)
    chosen = panel.loc[panel.signal_date.isin(dates[day_indices])].copy()
    chosen["a1_rank"] = chosen.a2_rank
    target = {d: dict(zip(part.ticker, weights[i])) for i, (d, part) in enumerate(chosen.groupby("signal_date", sort=True))}
    # Weights handed here align with selected day_indices, not absolute rows.
    original = r4.build_target_map
    try:
        r4.build_target_map = lambda *_args, **_kwargs: target
        ledger = r4.simulate_portfolio(chosen, prices.assign(ticker=lambda x: np.where(x.ticker.eq("QQQ"), "QQQ", x.ticker)),
                                       "NUMERIC_CHECK", "a2_rank", 20, 10)
    finally:
        r4.build_target_map = original
    error = abs(float(ledger.net_nav.iloc[-1]) - fast_nav)
    if error > 1e-10:
        raise RuntimeError(f"NATIVE_ACCOUNTING_DRIFT:{error}")
    return error


def fit_one(name, lam, cutoff, dates, path_end, usable, raw, name_ids, opens, calendar, counter):
    cutoff = pd.Timestamp(cutoff)
    training = np.flatnonzero(path_end <= cutoff)
    if len(training) == 0 or not np.array_equal(training, np.arange(len(training))):
        raise RuntimeError("TRAIN_PATH_CUTOFF_GAP")
    cols = FULL if name == "M_FULL" else ABLATION
    raw_spec = raw[:, :, [FULL.index(x) for x in cols]]
    phi, mean, std = transform(raw_spec, np.isin(np.arange(len(dates)), training))
    if not np.isfinite(phi).all():
        raise RuntimeError("BAD_SCALED_FEATURE")
    best = {"loss": np.inf, "theta": np.zeros(len(cols))}
    evals = 0
    def objective(theta):
        nonlocal evals
        if evals >= 1200:
            raise StopIteration("EVALUATION_BUDGET")
        evals += 1
        w = targets(phi, theta, usable)
        nav, _ = replay(training, w, name_ids, opens, calendar, dates)
        loss = -252 / (len(training)+1) * np.log(nav) + lam * np.mean(theta*theta)
        if np.isfinite(loss) and loss < best["loss"]:
            best.update(loss=float(loss), theta=theta.copy())
        return loss
    objective(np.zeros(len(cols)))
    try:
        result = minimize(objective, np.zeros(len(cols)), method="L-BFGS-B",
                          bounds=[(-2, 2)]*len(cols), options={"maxiter": 100, "maxfun": 1199,
                                                               "ftol": 1e-9, "gtol": 1e-5})
        message = str(result.message)
    except StopIteration:
        message = "OUTER_1200_EVALUATION_BUDGET"
    counter["sizing_parameter_fits"] += 1
    counter["train_objective_evaluations"] += evals
    return {"name": name, "lambda": lam, "cutoff": str(cutoff.date()), "theta": best["theta"],
            "columns": cols, "mean": mean, "std": std, "phi": phi,
            "train_days": len(training), "evaluations": evals, "objective": -best["loss"], "message": message}


def main():
    manifest_path = HERE / "RUN_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["counts"]["sizing_parameter_fits"] != 0:
        raise RuntimeError("FITS_ALREADY_STARTED; resume from saved log")
    panel, dates, execution, path_end, usable, raw, ids, opens, calendar, prices = load_data()
    assert dates.max() < pd.Timestamp("2026-01-01") and path_end.max() < pd.Timestamp("2026-01-01")
    full_weights = np.full((len(dates), 20), 0.05)
    baseline, _ = replay(np.arange(len(dates)), full_weights, ids, opens, calendar, dates)
    old_nav = float(pd.read_parquet(OLD / "B0_DAILY.parquet").net_nav.iloc[-1])
    assert abs(baseline - old_nav) < 1e-10, (baseline, old_nav)
    # Native short path with two distinct weights checks trade/cost/cash semantics.
    short = np.arange(4)
    err0 = native_check(panel, dates, full_weights[short], short, prices, replay(short, full_weights, ids, opens, calendar, dates)[0])
    trial = full_weights.copy(); trial[0] = capped(np.linspace(1, 20, 20) / 210)
    err1 = native_check(panel, dates, trial[short], short, prices, replay(short, trial, ids, opens, calendar, dates)[0])
    counter = manifest["counts"]
    records = []
    dev = {}
    for fold, cutoff, val_start, val_end in FOLDS:
        val = np.flatnonzero((execution >= pd.Timestamp(val_start)) & (path_end <= pd.Timestamp(val_end)))
        assert len(val) > 0 and np.array_equal(val, np.arange(val[0], val[-1]+1))
        b0, _ = replay(val, full_weights, ids, opens, calendar, dates)
        for name in ("M_FULL", "M_NO13F"):
            for lam in LAMBDAS:
                fit = fit_one(name, lam, cutoff, dates, path_end, usable, raw, ids, opens, calendar, counter)
                w = targets(fit["phi"], fit["theta"], usable)
                nav, _ = replay(val, w, ids, opens, calendar, dates)
                records.append({"stage": fold, "name": name, "lambda": lam, "train_days": fit["train_days"],
                                "validation_days": len(val)+1, "training_objective": fit["objective"],
                                "fit_evaluations": fit["evaluations"], "optimizer_status": fit["message"],
                                "model_nav": nav, "b0_nav": b0, "model_log_growth_per_day": np.log(nav)/(len(val)+1),
                                "b0_log_growth_per_day": np.log(b0)/(len(val)+1)})
                dev[(fold, name, lam)] = fit
                (HERE / "FIT_LOG.csv").write_text(pd.DataFrame(records).to_csv(index=False), encoding="utf-8")
                manifest["stages"]["development"] = "IN_PROGRESS"
                manifest["next_command"] = "Fit underway; inspect FIT_LOG.csv. Do not rerun train_pre2026.py while partial."
                manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    selected = {}
    for name in ("M_FULL", "M_NO13F"):
        score = {lam: sum(r["model_log_growth_per_day"]*r["validation_days"] for r in records
                          if r["name"] == name and r["lambda"] == lam) /
                     sum(r["validation_days"] for r in records if r["name"] == name and r["lambda"] == lam)
                 for lam in LAMBDAS}
        selected[name] = max(reversed(LAMBDAS), key=lambda lam: (score[lam], lam))
    manifest["selected_lambda"] = selected
    manifest["stages"]["development"] = "COMPLETE"
    # Confirmation only after development lambda selection, no reselection.
    confirm = np.flatnonzero((execution >= pd.Timestamp("2025-01-01")) &
                            (path_end <= pd.Timestamp("2025-12-31")))
    assert len(confirm) > 0 and np.array_equal(confirm, np.arange(confirm[0], confirm[-1]+1))
    cb0, _ = replay(confirm, full_weights, ids, opens, calendar, dates)
    for name in ("M_FULL", "M_NO13F"):
        fit = fit_one(name, selected[name], "2024-12-31", dates, path_end, usable, raw, ids, opens, calendar, counter)
        w = targets(fit["phi"], fit["theta"], usable)
        nav, _ = replay(confirm, w, ids, opens, calendar, dates)
        records.append({"stage": "CONFIRM_2025", "name": name, "lambda": selected[name],
                        "train_days": fit["train_days"], "validation_days": len(confirm)+1,
                        "training_objective": fit["objective"], "fit_evaluations": fit["evaluations"],
                        "optimizer_status": fit["message"], "model_nav": nav, "b0_nav": cb0,
                        "model_log_growth_per_day": np.log(nav)/(len(confirm)+1),
                        "b0_log_growth_per_day": np.log(cb0)/(len(confirm)+1)})
        (HERE / "FIT_LOG.csv").write_text(pd.DataFrame(records).to_csv(index=False), encoding="utf-8")
        manifest["stages"]["confirmation_2025"] = "IN_PROGRESS"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    manifest["stages"]["confirmation_2025"] = "COMPLETE"
    final_artifacts = {}
    for name in ("M_FULL", "M_NO13F"):
        fit = fit_one(name, selected[name], "2025-12-31", dates, path_end, usable, raw, ids, opens, calendar, counter)
        final_artifacts[name] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in fit.items() if k != "phi"}
        (HERE / "FIT_LOG.csv").write_text(pd.DataFrame(records).to_csv(index=False), encoding="utf-8")
        manifest["stages"]["final_fit"] = "IN_PROGRESS"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    model = {"spec": "A2_13F_LEARNED_SIZING_PRE2026_TEST2026_R1", "max_weight_fraction_G": 0.10,
             "sigma": "20 completed frozen index close-to-close returns, ddof=0", "qualified_pit_cap": False,
             "training_last_path_end": str(path_end.max().date()), "usable_days": int(usable.sum()),
             "fallback_days": int((~usable).sum()), "native_check_errors": [err0,err1],
             "old_b0_replay_error": baseline-old_nav, "fits": final_artifacts,
             "input_sha256": {p.name: sha(p) for p in [HERE / "PIT_PRE2026_TOP20_VH_PANEL.parquet",
                                                      HERE / "PRE2026_FULL_INITIAL_INFOTABLE.parquet"]},
             "code_sha256": sha(Path(__file__))}
    model_path = HERE / "MODEL_FROZEN.json"
    model_path.write_text(json.dumps(model, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    manifest["stages"]["final_fit"] = "COMPLETE"
    manifest["stages"]["model_freeze"] = "MODEL_FROZEN"
    manifest["model_frozen_sha256"] = sha(model_path)
    manifest["status"] = "MODEL_FROZEN"
    manifest["next_command"] = "Inspect 2026 frozen Raw A2 input and matching price-coordinate eligibility; then run one test without fit."
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"selected_lambda": selected, "counts": counter, "frozen_model_sha256": manifest["model_frozen_sha256"]}, indent=2))

if __name__ == "__main__":
    main()
