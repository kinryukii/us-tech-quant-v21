"""One verified zero-update ensemble control and frozen ensemble projection audit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import batch2026 as batch  # noqa: E402
import optimize_route as opt  # noqa: E402
import rl_policy as rl  # noqa: E402
from rl_reconstruct import make_initial  # noqa: E402


def combined(models, day, shares, pre_values, nav):
    separate = [rl.policy_target(m, day, shares, pre_values, nav, False) for m in models]
    names = set().union(*(set(x) for x in separate))
    averaged = {t: sum(x.get(t, 0.) for x in separate) / len(separate) for t in names}
    sorted_names = sorted(averaged, key=lambda t: (-averaged[t], t))
    retained = set(sorted_names[:rl.MAX_NAMES])
    projected = {t: averaged[t] for t in sorted_names if t in retained}
    return separate, averaged, projected


def main():
    torch.set_num_threads(1)
    panel = pd.read_parquet(batch.OUT / "predictions.parquet")
    norm = np.load(rl.OUT / "normalization.npz")
    days = rl.build_days(panel, norm["mean"], norm["scale"])
    e5 = rl.load_module("audit_rl_e5_2026", rl.E5)
    _, prices, _ = e5.load_2026_prices(set(panel.ticker.astype(str)))
    prices = prices.loc[prices.trade_date.le(batch.ASOF_DAY)].copy()
    replay = rl.dynamic_e5_replay(e5)
    _, executions, by_execution = opt.dates_for(prices, panel, "2026-01-01", "2026-09-25")
    selected = [rl.load_frozen(s)[0] for s in rl.SEEDS]
    originals = pd.read_parquet(batch.OUT / "rl_ensemble_targets.parquet")
    decomposition = []
    maximum_target_error = 0.
    for signal, g in originals.groupby("signal_date", sort=True):
        shares = {str(r.ticker): float(r.pretrade_shares) for r in g.itertuples() if r.held_before}
        pre_values = {str(r.ticker): float(r.pretrade_weight) for r in g.itertuples() if r.held_before}
        separate, averaged, projected = combined(selected, days[pd.Timestamp(signal)], shares, pre_values, 1.)
        recorded = dict(zip(g.ticker.astype(str), g.target_weight.astype(float)))
        maximum_target_error = max(maximum_target_error,
                                   max((abs(projected.get(t, 0.) - recorded.get(t, 0.))
                                        for t in set(projected) | set(recorded)), default=0.))
        decomposition.append({"signal_date": signal,
                              "seed_a_names": len(separate[0]), "seed_b_names": len(separate[1]),
                              "seed_a_exposure": sum(separate[0].values()),
                              "seed_b_exposure": sum(separate[1].values()),
                              "averaged_names_before_projection": len(averaged),
                              "names_after_projection": len(projected),
                              "averaged_exposure_before_projection": sum(averaged.values()),
                              "exposure_after_projection": sum(projected.values()),
                              "weight_removed_by_projection": sum(averaged.values()) - sum(projected.values())})
    decomposed = pd.DataFrame(decomposition)
    decomposed.to_csv(OUT / "rl_ensemble_projection.csv", index=False)

    initial = [make_initial(s).eval() for s in rl.SEEDS]
    target_count = 0

    def callback(signal, shares, pre_values, nav):
        nonlocal target_count
        with torch.no_grad():
            _, _, projected = combined(initial, days[pd.Timestamp(signal)], shares, pre_values, nav)
        target_count += 1
        return projected

    with torch.no_grad():
        init = replay("AUDIT_RL_ZERO_UPDATE_ENSEMBLE", callback, prices, executions, by_execution)
    frozen = pd.read_parquet(batch.OUT / "rl_ensemble_daily.parquet")
    assert len(init.daily) == len(frozen)
    assert init.daily.execution_date.equals(frozen.execution_date)
    init.daily.to_parquet(OUT / "rl_zero_update_ensemble_daily.parquet", index=False)
    metrics = {"zero_update_final_nav": float(init.daily.nav.iloc[-1]),
               "frozen_final_nav": float(frozen.nav.iloc[-1]),
               "zero_update_vs_frozen_log_nav": float(np.log(init.daily.nav.iloc[-1] / frozen.nav.iloc[-1])),
               "zero_update_mean_cash": float(init.daily.cash_weight.mean()),
               "frozen_mean_cash": float(frozen.cash_weight.mean()),
               "zero_update_turnover": float(init.daily.turnover.sum()),
               "frozen_turnover": float(frozen.turnover.sum()),
               "zero_update_fee_sum": float(init.daily.transaction_cost_amount.sum()),
               "frozen_fee_sum": float(frozen.transaction_cost_amount.sum()),
               "execution_dates": len(init.daily), "target_calls": target_count,
               "projection_dates": int(decomposed.averaged_names_before_projection.gt(rl.MAX_NAMES).sum()),
               "projection_total_target_weight_removed": float(decomposed.weight_removed_by_projection.sum()),
               "max_target_reconstruction_error": maximum_target_error}
    (OUT / "rl_initial_test_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
