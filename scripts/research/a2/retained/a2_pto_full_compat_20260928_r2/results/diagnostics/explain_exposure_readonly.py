"""Post-hoc description of existing forecasts; no fit, solve or replay."""
from pathlib import Path
import csv
import gc
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STREAMS = [
    "ridge__identity", "elastic__identity", "huber__identity",
    "hgb__identity", "lgb__identity", "mlp__identity",
    "all_points__equal", "all_points__hgb_then_ridge",
    "neural__ridge_then_hgb",
]
records = []
for year in (2025, 2026):
    folder = ROOT / "predictions" / f"evaluation_{year}"
    forecasts = pd.read_parquet(folder / "streams.parquet", columns=["signal_date", "ticker", *STREAMS])
    panel = pd.read_parquet(ROOT / "data" / ("pre_panel.parquet" if year == 2025 else "test_panel.parquet"),
                            columns=["signal_date", "ticker", "new_buy_eligible"],
                            filters=[("signal_date", ">=", pd.Timestamp(f"{year}-01-01")),
                                     ("signal_date", "<", pd.Timestamp(f"{year+1}-01-01"))])
    forecasts = forecasts.merge(panel, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    assert forecasts.new_buy_eligible.notna().all()
    forecasts = forecasts.loc[forecasts.new_buy_eligible].copy()
    cache = np.load(folder / "risk_cache.npz", allow_pickle=False)
    scales = cache["scales"][:, 0, :]
    date_index = {pd.Timestamp(x): i for i, x in enumerate(cache["dates"])}
    ticker_index = {str(x): i for i, x in enumerate(cache["tickers"])}
    for stream in STREAMS:
        daily = []
        for date, group in forecasts.groupby("signal_date", sort=True):
            valid = group.loc[np.isfinite(group[stream])].sort_values([stream, "ticker"], ascending=[False, True], kind="stable")
            if not len(valid):
                continue
            top = valid.head(20)
            mu = top[stream].to_numpy(float)
            sig = scales[date_index[pd.Timestamp(date)], [ticker_index[str(t)] for t in top.ticker]]
            daily.append({
                "candidates": len(valid), "all_mu_mean_bp": valid[stream].mean() * 10000,
                "top20_mu_mean_bp": mu.mean() * 10000,
                "top20_above_10bp": int((mu > .001).sum()),
                "top20_positive": int((mu > 0).sum()),
                "top20_robust_effective_above_10bp": int((mu - .5 * sig > .001).sum()),
                "top20_diagonal_scale_mean_bp": sig.mean() * 10000,
            })
        d = pd.DataFrame(daily)
        rec = {"year": year, "stream": stream, "days": len(d), "candidate_rows": len(forecasts),
               **{key + "_daily_mean": float(d[key].mean()) for key in d.columns},
               "days_no_top20_above_10bp": int(d.top20_above_10bp.eq(0).sum()),
               "days_at_least_10_above_10bp": int(d.top20_above_10bp.ge(10).sum())}
        records.append(rec)
    cache.close()
    del forecasts, panel, scales, cache
    gc.collect()

selected = []
with (ROOT / "results" / "analysis" / "ALL_COMBINATIONS.csv").open(encoding="utf-8-sig", newline="") as handle:
    for r in csv.DictReader(handle):
        group = r.get("group", "")
        fusion = r.get("fusion", "")
        stream = f"{group}__{fusion}"
        if stream in STREAMS and r.get("layer") == "pto" and r.get("indicative_return", ""):
            selected.append(r)

per_optimizer = []
for year in (2025, 2026):
    for stream in STREAMS:
        for opt in ("positive_equal", "mean_variance", "robust_mv", "cvar"):
            rr = [r for r in selected if int(r["year"]) == year and f'{r["group"]}__{r["fusion"]}' == stream and r["optimizer"] == opt]
            if rr:
                per_optimizer.append({"year": year, "stream": stream, "optimizer": opt, "accounts": len(rr),
                    **{k: float(np.mean([float(r[k]) for r in rr])) for k in
                       ("indicative_return", "mean_gross_exposure", "indicative_max_drawdown", "total_fees")}})

out = {"status": "READ_ONLY_POSTHOC_DESCRIPTION", "fit_calls": 0, "optimization_calls": 0,
       "account_replays": 0, "candidate_or_model_changes": 0,
       "scope": "Existing finite forecasts on input-qualified new-buy candidates, excluding held-only. Top20 is forecast-only; actual account selection also depends on price decision masks and existing holdings. Not a replay or causal decomposition.",
       "sign_rule": "positive_equal uses mu > .001; robust uses mu - .5*diagonal_scale in this diagnostic",
       "forecast_daily_statistics": records, "existing_account_optimizer_means": per_optimizer}
target = ROOT / "results" / "diagnostics" / "EXPOSURE_MECHANISM_READONLY_20260929.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
