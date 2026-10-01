"""Read-only, fixed-scope audit of frozen forecasts and paired NAV paths."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import risk_aux  # noqa: E402

PRED = ("pred_ridge", "pred_elastic", "pred_hgb", "pred_mlp_mean")
QUANTILES = {"pred_q10": .1, "pred_q50": .5, "pred_q90": .9}


def scores(y: np.ndarray, p: np.ndarray, task: str, q: float = 0) -> dict:
    good = np.isfinite(y) & np.isfinite(p)
    y, p = y[good], p[good]
    if task == "mean":
        return {"mae": np.mean(abs(y-p)), "mse": np.mean((y-p)**2)}
    if task == "prob":
        e = (y > .001).astype(float)
        p = np.clip(p, 1e-12, 1-1e-12)
        return {"logloss": log_loss(e, p), "brier": np.mean((e-p)**2),
                "event_rate": e.mean(), "predicted_rate": p.mean()}
    d = y-p
    return {"pinball": np.mean(np.maximum(q*d, (q-1)*d)),
            "coverage": np.mean(y <= p)}


def train_constants(panel: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    t = panel.loc[panel.signal_date.lt(cutoff) &
                  panel.label_end_date_5.lt(cutoff) & panel.y5.notna(), "y5"].to_numpy(float)
    assert len(t) and np.isfinite(t).all()
    return {"mean": float(t.mean()), "median": float(np.median(t)),
            "event_rate": float(np.mean(t > .001)),
            "q10": float(np.quantile(t, .1)), "q50": float(np.quantile(t, .5)),
            "q90": float(np.quantile(t, .9)), "n": len(t)}


def labels_2026() -> pd.DataFrame:
    pred = pd.read_parquet(ROOT / "test2026/predictions.parquet")
    e5path = Path(r"D:\us-tech-quant-results\A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS\run_a2_execution_efficiency_r2.py")
    spec = importlib.util.spec_from_file_location("a2_e5_prediction_audit", e5path)
    e5 = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = e5
    spec.loader.exec_module(e5)
    _, prices, _ = e5.load_2026_prices(set(pred.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le("2026-09-24")]
    cal = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    dates = pd.DataFrame({"signal_date": cal, "entry_date": pd.Series(cal).shift(-1),
                          "label_end_date_5": pd.Series(cal).shift(-6)})
    x = pred.merge(dates, on="signal_date", how="left", validate="many_to_one")
    opens = prices[["trade_date", "ticker", "open"]]
    for dt, nm in (("entry_date", "entry_open"), ("label_end_date_5", "end_open")):
        x = x.merge(opens.rename(columns={"trade_date": dt, "open": nm}),
                    on=[dt, "ticker"], how="left", validate="many_to_one")
    x["y5"] = x.end_open / x.entry_open - 1
    x.loc[~np.isfinite(x.y5), "y5"] = np.nan
    assert x.y5.notna().sum() == 6001
    return x


def audit_predictions() -> None:
    panel = pd.read_parquet(ROOT / "pre2026_panel.parquet")
    oof = pd.read_parquet(ROOT / "pre2026_oof.parquet")
    test = labels_2026()
    cuts = {"2024": "2024-01-01", "2025": "2025-01-01", "2026": "2026-01-01"}
    rows, cal_rows = [], []
    for year, cut in cuts.items():
        const = train_constants(panel, pd.Timestamp(cut))
        frame = test if year == "2026" else oof.loc[oof.fold.eq(year)]
        frame = frame.loc[frame.y5.notna()]
        for universe, sub in (("Top40", frame), ("Raw Top20", frame.loc[frame.raw_rank.le(20)])):
            y = sub.y5.to_numpy(float)
            for model in PRED:
                for name, arr in ((model, sub[model].to_numpy(float)),
                                  ("train_mean", np.full(len(sub), const["mean"])),
                                  ("train_median", np.full(len(sub), const["median"]))):
                    rows.append({"fold": year, "universe": universe, "task": "mean", "model": name,
                                 "comparison_for": model, "rows": len(sub), "train_rows": const["n"],
                                 **scores(y, arr, "mean")})
            for name, arr in (("pred_logistic", sub.pred_logistic.to_numpy(float)),
                              ("train_event_rate", np.full(len(sub), const["event_rate"]))):
                rows.append({"fold": year, "universe": universe, "task": "prob", "model": name,
                             "comparison_for": "pred_logistic", "rows": len(sub), "train_rows": const["n"],
                             **scores(y, arr, "prob")})
            for model, q in QUANTILES.items():
                base = f"q{int(q*100)}"
                for name, arr in ((model, sub[model].to_numpy(float)),
                                  ("train_"+base, np.full(len(sub), const[base]))):
                    rows.append({"fold": year, "universe": universe, "task": "quantile", "quantile": q,
                                 "model": name, "comparison_for": model, "rows": len(sub),
                                 "train_rows": const["n"], **scores(y, arr, "quantile", q)})
            bins = pd.cut(sub.pred_logistic, np.linspace(0,1,11), include_lowest=True)
            for b, part in sub.groupby(bins, observed=True):
                cal_rows.append({"fold": year, "universe": universe, "bin": str(b), "rows": len(part),
                                 "mean_probability": part.pred_logistic.mean(),
                                 "event_rate": part.y5.gt(.001).mean()})
    pd.DataFrame(rows).to_csv(OUT / "prediction_baselines.csv", index=False)
    pd.DataFrame(cal_rows).to_csv(OUT / "probability_calibration.csv", index=False)


def audit_risk() -> None:
    spec = importlib.util.spec_from_file_location("safe_inputs_audit", ROOT.parent / "a2_top20_action_nn_20260925/safe_inputs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _, prices, _, _ = mod.load_inputs()
    close = prices.loc[prices.ticker.ne("QQQ")].pivot(index="trade_date", columns="ticker", values="close").sort_index()
    ret = close.shift(-1).div(close).sub(1)
    panel = pd.read_parquet(ROOT / "pre2026_panel.parquet")
    rows = []
    for year in (2024, 2025):
        bundle = joblib.load(ROOT / f"risk_artifacts/fold_{year}.joblib")
        assert pd.Timestamp(bundle["cutoff"]) < pd.Timestamp(f"{year}-01-02")
        assert len(bundle["tickers"]) == bundle["covariance"].shape[0]
        subset = panel.loc[panel.signal_date.dt.year.eq(year) & panel.raw_rank.le(20)]
        for date, day in subset.groupby("signal_date", sort=True):
            names = day.sort_values("raw_rank").ticker.astype(str).tolist()
            if len(names) != 20 or date not in ret.index:
                continue
            actual = ret.loc[date].reindex(names).to_numpy(float)
            if not np.isfinite(actual).all():
                continue
            cov = risk_aux.covariance_for(bundle, date, names)
            assert np.allclose(cov, cov.T, atol=1e-12) and np.linalg.eigvalsh(cov)[0] > -1e-12
            reverse = risk_aux.covariance_for(bundle, date, list(reversed(names)))
            assert np.allclose(cov, reverse[::-1, ::-1], atol=1e-12)
            w = np.full(20, .05)
            rows.append({"fold": year, "date": date, "realized": w@actual,
                         "factor_var": w@cov@w,
                         "diag_var": w@np.diag(np.diag(cov))@w,
                         "min_eigenvalue": np.linalg.eigvalsh(cov)[0],
                         "unknown_tickers": sum(t not in set(bundle["tickers"]) for t in names)})
    day = pd.DataFrame(rows)
    day.to_csv(OUT / "risk_daily.csv", index=False)
    out = []
    for year, d in day.groupby("fold"):
        obs = np.mean(d.realized**2)
        for mode in ("factor", "diag"):
            v = d[f"{mode}_var"]
            out.append({"fold": year, "estimator": mode, "days": len(d),
                        "realized_rms": np.sqrt(obs), "predicted_rms": np.sqrt(np.mean(v)),
                        "realized_over_predicted_rms": np.sqrt(obs/np.mean(v)),
                        "variance_mse": np.mean((d.realized**2-v)**2),
                        "unknown_ticker_days": int((d.unknown_tickers>0).sum()),
                        "min_eigenvalue": d.min_eigenvalue.min()})
    pd.DataFrame(out).to_csv(OUT / "risk_comparison.csv", index=False)


def audit_statistics() -> None:
    base = ROOT / "test2026"
    raw = pd.read_parquet(base / "raw_daily.parquet").sort_values("execution_date")
    original = pd.read_csv(base / "paired_block_uncertainty.csv")
    rows, periods, extremes = [], [], []
    candidates = ("hgb_diag_5", "hgb_factor_5", "rl_seed_20260925", "rl_seed_20260926", "rl_ensemble")
    for candidate in candidates:
        x = pd.read_parquet(base / f"{candidate}_daily.parquet").sort_values("execution_date")
        assert np.array_equal(x.execution_date.to_numpy(), raw.execution_date.to_numpy())
        diff = np.log1p(x.net_return.to_numpy(float))-np.log1p(raw.net_return.to_numpy(float))
        assert np.isfinite(diff).all() and len(diff)==156
        # The original implementation uses one RNG stream shared across candidates.
        for block in (10,20,40):
            if block == 20:
                continue
            rng = np.random.default_rng(20260926)
            n=len(diff)
            sims=[]
            for _ in range(500):
                starts=rng.integers(0,n,size=int(np.ceil(n/block)))
                idx=np.concatenate([(s+np.arange(block))%n for s in starts])[:n]
                sims.append(float(np.exp(diff[idx].sum())-1))
            rows.append({"candidate": candidate.upper(), "block": block,
                         "relative_nav": np.exp(diff.sum())-1,
                         "low_2p5": np.quantile(sims,.025), "high_97p5": np.quantile(sims,.975),
                         "replicates": 500, "seed": 20260926})
        for freq in ("M","Q"):
            frame=pd.DataFrame({"date":pd.to_datetime(x.execution_date),"diff":diff})
            group=frame.groupby(frame.date.dt.to_period(freq))["diff"].sum()
            periods.extend({"candidate":candidate.upper(),"period_type":freq,"period":str(k),
                            "log_return_diff":v} for k,v in group.items())
        order=np.argsort(diff)
        for label, idx in (("most_negative",order[:5]),("most_positive",order[-5:][::-1])):
            extremes.extend({"candidate":candidate.upper(),"group":label,
                             "date":str(x.execution_date.iloc[i].date()),"log_return_diff":diff[i]}
                            for i in idx)
    pd.DataFrame(rows).to_csv(OUT / "block_sensitivity.csv",index=False)
    pd.DataFrame(periods).to_csv(OUT / "calendar_contributions.csv",index=False)
    pd.DataFrame(extremes).to_csv(OUT / "daily_concentration.csv",index=False)
    # Independently regenerate the original 20-session intervals with its shared RNG.
    rng=np.random.default_rng(20260925)
    checks=[]
    for candidate in candidates:
        x=pd.read_parquet(base/f"{candidate}_daily.parquet").sort_values("execution_date")
        d=np.log1p(x.net_return.to_numpy(float))-np.log1p(raw.net_return.to_numpy(float))
        n=len(d); sims=[]; block=20
        for _ in range(500):
            starts=rng.integers(0,n,size=int(np.ceil(n/block)))
            idx=np.concatenate([(s+np.arange(block))%n for s in starts])[:n]
            sims.append(np.exp(d[idx].sum())-1)
        prior=original.loc[original.candidate.eq(candidate.upper())].iloc[0]
        checks.append({"candidate":candidate.upper(),"point_delta":np.exp(d.sum())-1-prior.relative_nav,
                       "lower_delta":np.quantile(sims,.025)-prior.date_block_bootstrap_lower_2p5,
                       "upper_delta":np.quantile(sims,.975)-prior.date_block_bootstrap_upper_97p5})
    pd.DataFrame(checks).to_csv(OUT/"original_20d_reproduction.csv",index=False)


if __name__ == "__main__":
    audit_predictions()
    audit_risk()
    audit_statistics()
    print("Prediction/risk/stat read-only audit complete")
