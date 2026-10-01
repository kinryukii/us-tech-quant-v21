"""Evaluate frozen pre-2026 predictions with the original A2 execution engine."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from fit import OUT, SOURCE, SPECS, FEATURES, sha, write_json

REBUILD = SOURCE / "scripts/run_rebuild.py"
R0F = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
R0F1 = Path(r"D:\us-tech-quant\scripts\v22\fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py")


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prices():
    rebuild = import_file("original_rebuild", REBUILD)
    r0f1 = import_file("original_r0f1_for_prices", R0F1)
    members = pd.read_parquet(SOURCE / "universe/quarterly_universe_members.parquet", columns=["ticker", "moomoo_transport_code"]).drop_duplicates()
    codes = set(members.moomoo_transport_code)
    status = pd.read_csv(rebuild.RUN_CACHE / "rehab_status.csv", keep_default_na=False)
    rehab = pd.read_parquet(rebuild.RUN_CACHE / "rehab_factors.parquet")
    index, failures = rebuild.raw_file_index()
    assert not failures
    assert codes.intersection(index).issubset(set(status.loc[status.status.eq("PASS"), "code"])), "frozen rehab cache incomplete for priced codes"
    wolf = [x for x in r0f1.frozen_evidence_records() if x["ticker"] == "WOLF"][0]
    pieces = []
    for row in members.itertuples(index=False):
        if row.moomoo_transport_code not in index:
            continue
        raw = rebuild.load_raw_code(row.moomoo_transport_code, index[row.moomoo_transport_code])
        raw = raw.loc[raw.trade_date.lt(rebuild.END_EXCLUSIVE)]
        if raw.empty:
            continue
        frame, _ = rebuild.adjusted_price_frame(row.moomoo_transport_code, row.ticker, raw, rehab, wolf)
        pieces.append(frame[["ticker", "trade_date", "open", "close"]])
    qqq = rebuild.qqq_prices().loc[lambda x: x.trade_date.lt(rebuild.END_EXCLUSIVE), ["ticker", "trade_date", "open", "close"]]
    result = pd.concat([*pieces, qqq], ignore_index=True).sort_values(["ticker", "trade_date"], kind="mergesort")
    assert not result.duplicated(["ticker", "trade_date"]).any()
    return result


def main():
    r0f = import_file("original_r0f_for_execution", R0F)
    ref = pd.read_parquet(SOURCE / "A2/oof_predictions.parquet")
    ref_daily = pd.read_parquet(SOURCE / "A2/portfolio_daily.parquet")
    price = prices()
    price_path = OUT / "pre2026_original_price_coordinate.parquet"
    price.to_parquet(price_path, index=False)
    report = {"price_rows": len(price), "price_tickers": price.ticker.nunique(), "price_sha256": sha(price_path), "methods": {}}
    calendar = pd.DatetimeIndex(price.loc[price.ticker.eq("QQQ"), "trade_date"])
    terminal = pd.Timestamp(calendar[-3])
    for method in ("hgb", "ridge", "elastic_net", "mlp"):
        p = OUT / method / "pre2026_oof.parquet"
        assert p.exists(), method
        preds = pd.read_parquet(p)
        merged = preds.merge(ref[["signal_date", "ticker", "target", "a2_rank"]], on=["signal_date", "ticker"], validate="one_to_one")
        labeled = merged.loc[merged.target.notna()].copy()
        daily = labeled.groupby("signal_date", sort=True).apply(lambda g: pd.Series({"rank_ic": g["prediction"].rank().corr(g["target"].rank()), "top20_mean_target": g.loc[g["rank"].le(20), "target"].mean()}), include_groups=False).reset_index()
        chosen = preds.loc[preds["rank"].le(20), ["signal_date", "ticker", "rank"]].sort_values(["signal_date", "rank"])
        assert chosen.groupby("signal_date").size().eq(20).all()
        chosen.to_parquet(OUT / method / "top20_pre2026.parquet", index=False)
        signals = preds.loc[preds.signal_date.le(terminal)]
        target_map = {pd.Timestamp(d): dict.fromkeys(g.ticker, 1.0 / 20) for d, g in signals.loc[signals["rank"].le(20)].groupby("signal_date", sort=True)}
        path = r0f.reconstruct_path(model=method, target_map=target_map, qfq=price, signal_dates=signals.signal_date.unique(), cost_bps=10)
        path.daily.to_parquet(OUT / method / "portfolio_daily_pre2026.parquet", index=False)
        path.positions.to_parquet(OUT / method / "position_ledger_pre2026.parquet", index=False)
        path.trades.to_parquet(OUT / method / "trade_ledger_pre2026.parquet", index=False)
        ordered = path.daily.sort_values("execution_date")
        returns = ordered.reconstructed_daily_return.to_numpy(float)
        nav = np.r_[1.0, np.cumprod(1.0 + returns)]
        drawdown = nav / np.maximum.accumulate(nav) - 1
        report["methods"][method] = {"rank_ic_mean": float(daily.rank_ic.mean()), "top20_mean_target": float(daily.top20_mean_target.mean()),
             "cagr": float(nav[-1] ** (252 / len(returns)) - 1), "total_return": float(nav[-1] - 1),
             "max_drawdown": float(drawdown.min()), "annualized_volatility": float(np.std(returns) * np.sqrt(252)),
             "total_turnover": float(ordered.reconstructed_turnover.sum()), "execution_days": len(ordered)}
        if method == "hgb":
            check = ordered.merge(ref_daily, on="execution_date", suffixes=("_new", "_old"), validate="one_to_one")
            report["methods"][method]["old_nav_max_abs_difference"] = float((check.reconstructed_nav_new - check.reconstructed_nav_old).abs().max())
            assert report["methods"][method]["old_nav_max_abs_difference"] <= 1e-12
        daily.to_parquet(OUT / method / "daily_prediction_metrics.parquet", index=False)
        write_json(OUT / "evaluation.json", report)
        print(method, "evaluated", flush=True)
    write_json(OUT / "evaluation.json", report)


if __name__ == "__main__":
    main()
