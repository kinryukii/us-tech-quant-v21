"""Fixed, read-only decision-clock interventions on frozen 2026 states."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import optimize_route  # noqa: E402
import risk_aux  # noqa: E402
import rl_policy  # noqa: E402

OUT = Path(__file__).resolve().parent
TEST = ROOT / "test2026"
PANEL = pd.read_parquet(TEST / "predictions.parquet")
HGB = pd.read_parquet(TEST / "hgb_diag_5_decisions.parquet")
HGB_DAILY = pd.read_parquet(TEST / "hgb_diag_5_daily.parquet")
RL = pd.read_parquet(TEST / "rl_ensemble_targets.parquet")
RL_DAILY = pd.read_parquet(TEST / "rl_ensemble_daily.parquet")


def choose_dates():
    available = sorted(set(HGB.signal_date))
    fixed = [pd.Timestamp(x) for x in ("2026-01-05", "2026-03-16", "2026-06-15", "2026-08-10")]
    fixed = [max(x for x in available if x <= d) for d in fixed]
    missed = HGB_DAILY.loc[HGB_DAILY.skipped_buy_count.gt(0), "signal_date"]
    if not missed.empty:
        fixed.append(pd.Timestamp(missed.iloc[0]))
    day_sets = PANEL.loc[PANEL.signal_date.isin(available) & PANEL.raw_rank.le(20)].groupby("signal_date").ticker.apply(frozenset)
    changes = day_sets.ne(day_sets.shift())
    identity = next(pd.Timestamp(x) for x in day_sets.index[changes.fillna(False)][1:]
                    if pd.Timestamp(x) not in fixed)
    fixed.append(pd.Timestamp(identity))
    return list(dict.fromkeys(fixed)), pd.Timestamp(missed.iloc[0]) if not missed.empty else None, pd.Timestamp(identity)


def weights(frame, col):
    return dict(zip(frame.ticker.astype(str), frame[col].astype(float)))


def difference(a, b):
    return max((abs(a.get(t, 0.) - b.get(t, 0.)) for t in set(a) | set(b)), default=0.)


def state(decisions, daily, date):
    rows = decisions.loc[decisions.signal_date.eq(date)]
    nav = float(daily.loc[daily.signal_date.eq(date), "pretrade_nav"].iloc[0])
    shares = {str(t): float(q) for t, q in zip(rows.ticker, rows.shares_before) if q > 0}
    pre = {str(t): float(w) * nav for t, w in zip(rows.ticker, rows.weight_before) if t in shares}
    return rows, shares, pre, nav


def main():
    dates, missed, identity = choose_dates()
    risk = risk_aux.load_bundle(ROOT / "risk_artifacts" / "final_pre2026.joblib")
    norm = np.load(ROOT / "rl_artifacts" / "normalization.npz")
    days = rl_policy.build_days(PANEL, norm["mean"], norm["scale"])
    rl_callback = rl_policy.frozen_callback(days)
    output = []
    for date in dates:
        day = PANEL.loc[PANEL.signal_date.eq(date)].copy()
        for policy in ("HGB_DIAG_5", "RL_ENSEMBLE", "RAW"):
            if policy == "HGB_DIAG_5":
                saved, shares, pre, nav = state(HGB, HGB_DAILY, date)
                observed = weights(saved, "feasible_target_weight")
                fn = lambda x, v: optimize_route.solve(day, shares, x, v, risk, optimize_route.SPECS["HGB_DIAG_5"], date)[0]
            elif policy == "RL_ENSEMBLE":
                saved, shares, pre, nav = state(RL.rename(columns={"pretrade_shares": "shares_before", "pretrade_weight": "weight_before"}), RL_DAILY, date)
                observed = weights(saved, "target_weight")
                fn = lambda x, v: rl_callback(date, shares, x, v)
            else:
                saved, shares, pre, nav = state(HGB, HGB_DAILY, date)
                observed = {str(t): .05 for t in day.loc[day.raw_rank.le(20), "ticker"]}
                fn = lambda x, v: {str(t): .05 for t in day.loc[day.raw_rank.le(20), "ticker"]}
            baseline = fn(pre, nav)
            target = max(pre, key=pre.get) if pre else None
            future = dict(pre)
            if target is not None:
                future[target] *= 1.20
            future_nav = nav + (future.get(target, 0.) - pre.get(target, 0.) if target else 0.)
            altered = fn(future, future_nav)
            shuffled = day.sample(frac=1, random_state=20260926)
            label_masked = day.copy()
            label_masked["y5"] = -999.0
            label_masked["label_end_date_5"] = pd.NaT
            if policy == "HGB_DIAG_5":
                order = optimize_route.solve(shuffled, shares, pre, nav, risk, optimize_route.SPECS["HGB_DIAG_5"], date)[0]
                masked = optimize_route.solve(label_masked, shares, pre, nav, risk, optimize_route.SPECS["HGB_DIAG_5"], date)[0]
            elif policy == "RL_ENSEMBLE":
                order_days = rl_policy.build_days(shuffled, norm["mean"], norm["scale"])
                order = rl_policy.frozen_callback(order_days)(date, shares, pre, nav)
                mask_days = rl_policy.build_days(label_masked, norm["mean"], norm["scale"])
                masked = rl_policy.frozen_callback(mask_days)(date, shares, pre, nav)
            else:
                order = baseline
                masked = baseline
            output.append({"signal_date": date.date().isoformat(), "policy": policy,
                           "future_open_intervention": "largest_held_price_plus_20pct",
                           "perturbed_ticker": target, "shares_before": shares.get(target, 0.),
                           "original_implied_open": pre.get(target, 0.) / shares[target] if target else np.nan,
                           "altered_implied_open": future.get(target, 0.) / shares[target] if target else np.nan,
                           "saved_recompute_max_target_absdiff": difference(observed, baseline),
                           "future_open_max_target_absdiff": difference(baseline, altered),
                           "future_open_sum_target_diff": sum(altered.values()) - sum(baseline.values()),
                           "future_open_changed_names": len({t for t in set(baseline) | set(altered)
                                                             if abs(baseline.get(t, 0.) - altered.get(t, 0.)) > 1e-8}),
                           "shuffled_rows_max_target_absdiff": difference(baseline, order),
                           "masked_label_max_target_absdiff": difference(baseline, masked),
                           "missing_buy_date": bool(date == missed), "identity_change_date": bool(date == identity)})
    frame = pd.DataFrame(output)
    frame.to_csv(OUT / "time_prefix_results.csv", index=False)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
