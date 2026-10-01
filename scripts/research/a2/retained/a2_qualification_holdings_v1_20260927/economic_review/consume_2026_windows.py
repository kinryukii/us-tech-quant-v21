"""Describe saved full windows only; never run a model or splice valid dates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    rows = []
    reference_dates = None
    for cost in [5, 10, 25]:
        folder = ROOT / f"evaluation_2026/cost_{cost}"
        complete = json.loads((folder / "COMPLETE.json").read_text(encoding="utf-8"))
        assert complete["policies"] == 14 and complete["fit_attempts"] == 0
        comparison = pd.read_csv(folder / "comparison.csv")
        for saved in comparison.itertuples(index=False):
            path = folder / saved.policy
            daily = pd.read_parquet(path / "daily.parquet").sort_values("date")
            metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
            dates = daily.date.reset_index(drop=True)
            if reference_dates is None:
                reference_dates = dates
            else:
                pd.testing.assert_series_equal(dates, reference_dates)
            assert len(daily) == 183 and not dates.duplicated().any()
            initial = float(metadata["initial_cash"])
            certified = daily.valuation_status.eq("certified") & daily.certified_nav.notna()
            full = bool(certified.all())
            bad = daily.loc[~certified, "date"]
            indicative = float(daily.nav.iloc[-1] / initial - 1)
            assert np.isclose(indicative, saved.indicative_return, rtol=0, atol=1e-12)
            # Incomplete paths are retained as rows. No return, volatility or
            # drawdown is calculated from a subset of their certified dates.
            endpoint_return = mdd = volatility = float("nan")
            if full:
                nav = np.r_[initial, daily.certified_nav.to_numpy(float)]
                endpoint_return = float(nav[-1] / initial - 1)
                mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1))
                returns = daily.certified_nav.pct_change(fill_method=None).iloc[1:]
                assert returns.notna().all()
                volatility = float(returns.std(ddof=1) * np.sqrt(252))
            rows.append(dict(
                policy=saved.policy, cost_bps=cost, start=str(dates.iloc[0].date()),
                end=str(dates.iloc[-1].date()), sessions=len(daily),
                full_window_index_nav_certified=full, shareholder_return_certified=False,
                uncertified_sessions=int((~certified).sum()),
                first_uncertified_date=None if bad.empty else str(bad.iloc[0].date()),
                complete_window_net_index_return=endpoint_return,
                complete_window_max_drawdown=mdd,
                complete_window_annualized_volatility_252=volatility,
                original_indicative_endpoint_return_not_a_certified_comparison=indicative,
                average_book_gross_exposure=float(daily.gross_exposure.mean()),
                average_book_cash_weight=float(daily.cash_weight.mean()),
                book_exposure_uses_uncertified_marks=not full,
                average_actual_names=float(daily.actual_name_count.mean()),
                transaction_cost_amount=float(daily.transaction_cost_amount.sum()),
                transaction_cost_fraction_initial=float(daily.transaction_cost_amount.sum() / initial),
                buy_plus_sell_notional=float(daily.traded_notional.sum()),
                saved_one_way_turnover_sum=float(daily.turnover.sum()),
                actual_trades=int(saved.trades), execution_rejections=int(saved.execution_rejections),
                relative_to_same_cost_joint_hgb_return_pp=float("nan"),
            ))
    result = pd.DataFrame(rows)
    assert len(result) == 42
    for cost in [5, 10, 25]:
        ref = result.loc[result.cost_bps.eq(cost) & result.policy.eq("joint_hgb")].iloc[0]
        assert ref.full_window_index_nav_certified
        valid = result.cost_bps.eq(cost) & result.full_window_index_nav_certified
        result.loc[valid, "relative_to_same_cost_joint_hgb_return_pp"] = (
            result.loc[valid, "complete_window_net_index_return"] - ref.complete_window_net_index_return
        ) * 100
    result.to_csv(HERE / "OBSERVED_2026_WINDOWS.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({"saved_windows":len(result),"full_window_certified":int(result.full_window_index_nav_certified.sum()),
        "uncertified_windows":int((~result.full_window_index_nav_certified).sum()),
        "new_fit_or_replay_calls":0,"date_or_stock_exclusions":0}))


if __name__ == "__main__":
    main()
