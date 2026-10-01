"""Local KKT and symmetric pre-2026-scale prediction perturbation checks."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
sys.path.insert(0, str(ROOT))
import optimize_route
import risk_aux

DATES = ["2026-01-05", "2026-01-06", "2026-02-25", "2026-03-16", "2026-06-15", "2026-08-10"]


def main():
    if (AUDIT / "optimizer_math.csv").exists():
        raise RuntimeError("ALREADY_RUN")
    pred = pd.read_parquet(ROOT / "test2026" / "predictions.parquet")
    saved = pd.read_parquet(AUDIT / "hgb_diag_5_targets.parquet")
    bundle = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    trials = pd.read_csv(ROOT / "supervised_trials.csv")
    pre_mae = float(trials.loc[trials.fold.eq("2025") & trials.model.eq("HGB"), "mae"].iloc[0])
    epsilon = .05 * pre_mae  # Fixed scale from pre-2026 prediction error, not 2026 wealth.
    rows = []
    for date_string in DATES:
        date = pd.Timestamp(date_string)
        day = pred.loc[pred.signal_date.eq(date)].copy()
        state = saved.loc[saved.signal_date.eq(date)]
        if day.empty or state.empty:
            raise RuntimeError(f"FIXED_DATE_MISSING:{date_string}")
        shares = {r.ticker: float(r.signal_close_shares) for r in state.itertuples()
                  if r.signal_close_shares > 0}
        prior = {r.ticker: float(r.signal_close_weight) for r in state.itertuples()
                 if r.signal_close_weight > 0}
        spec = optimize_route.SPECS["HGB_DIAG_5"]
        original, diag = optimize_route.solve(day, shares, prior, 1., bundle, spec, date)
        saved_target = state.set_index("ticker").target_weight.to_dict()
        baseline_max = max(abs(original.get(t, 0.) - saved_target.get(t, 0.))
                           for t in set(original) | set(saved_target))
        if baseline_max > 1e-5:
            raise RuntimeError(f"BASELINE_TARGET_REBUILD:{date}:{baseline_max}")
        top = day.loc[day.raw_rank.le(20)].sort_values("raw_rank")
        names = top.ticker.astype(str).tolist() + sorted(set(shares) - set(top.ticker.astype(str)))
        raw = {r.ticker: float(r.raw_target_weight) for r in state.itertuples()}
        w = np.array([raw.get(t, 0.) for t in names])
        old = np.array([prior.get(t, 0.) for t in names])
        mu = day.set_index("ticker").pred_hgb.reindex(names).fillna(0).to_numpy(float)
        variance = np.diag(risk_aux.covariance_for(bundle, date, names))
        lam = spec[2]
        active = (w > .005) & (w < .095) & (np.abs(w-old) > .002)
        first_order = mu - 10 * lam * variance * w - optimize_route.COST_ONE_WAY * np.sign(w-old)
        # If gross cap binds, its KKT shadow price is common to all interior
        # active names; if slack, shadow price is zero.
        nu = float(np.median(first_order[active])) if w.sum() >= .999 and active.any() else 0.
        residual = abs(first_order[active] - nu) if active.any() else np.array([])
        row = {"signal_date": date, "pre2026_mae": pre_mae, "epsilon": epsilon,
               "baseline_target_max_error": baseline_max,
               "gross_raw": float(w.sum()), "max_stock": float(w.max()),
               "active_interior_count": int(active.sum()), "kkt_shadow_nu": nu,
               "kkt_median_abs_residual": float(np.median(residual)) if len(residual) else np.nan,
               "kkt_max_abs_residual": float(np.max(residual)) if len(residual) else np.nan}
        for direction, label in ((-1, "minus"), (1, "plus")):
            moved = day.copy()
            moved["pred_hgb"] = moved.pred_hgb + direction * epsilon * np.where(
                moved.raw_rank.astype(int) % 2 == 0, 1., -1.)
            target, _ = optimize_route.solve(moved, shares, prior, 1., bundle, spec, date)
            keys = set(target) | set(original)
            delta = np.array([target.get(t, 0.) - original.get(t, 0.) for t in keys])
            row[f"{label}_target_l1"] = float(np.abs(delta).sum())
            row[f"{label}_target_max_abs"] = float(np.abs(delta).max())
            row[f"{label}_zero_or_cap_flips"] = int(sum(
                (original.get(t, 0.) <= 1e-10) != (target.get(t, 0.) <= 1e-10) or
                (original.get(t, 0.) >= .099999) != (target.get(t, 0.) >= .099999)
                for t in keys))
            row[f"{label}_expected_fee_delta"] = float(optimize_route.COST_ONE_WAY * (
                sum(abs(target.get(t, 0.) - prior.get(t, 0.)) for t in keys) -
                sum(abs(original.get(t, 0.) - prior.get(t, 0.)) for t in keys)))
        rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(AUDIT / "optimizer_math.csv", index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
