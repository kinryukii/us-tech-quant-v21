"""No additional model fit or policy solve; reconstruct executed shares."""
from pathlib import Path
import sys
import pandas as pd

from trade_detail import detail

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "a2_top20_action_nn_20260925"))
import safe_inputs


def main():
    _, prices, _, _ = safe_inputs.load_inputs()
    out = ROOT / "opt_artifacts"
    metrics = pd.read_csv(out / "pre2026_summary.csv")
    rows = []
    for item in metrics.itertuples():
        prefix = out / f"{item.year}_{item.candidate.lower()}"
        daily = pd.read_parquet(str(prefix) + "_daily.parquet")
        trades = pd.read_parquet(str(prefix) + "_trades.parquet")
        decisions = pd.read_parquet(str(prefix) + "_decisions.parquet")
        action = detail(trades, daily, prices, decisions)
        action.to_parquet(str(prefix) + "_executed.parquet", index=False)
        rows.append({"year": item.year, "candidate": item.candidate,
                     "executed_trades": len(action),
                     "actual_partial_sells": int((action.side.eq("SELL") &
                         action.sold_shares_over_prior_shares.between(.000001, .999999)).sum()),
                     "actual_full_exits": int((action.side.eq("SELL") &
                         action.sold_shares_over_prior_shares.ge(.999999)).sum()),
                     "actual_adds": int((action.side.eq("BUY") & action.shares_before.gt(0)).sum()),
                     "max_buy_over_nav": float(action.buy_notional_over_pretrade_nav.max()),
                     "max_sell_fraction": float(action.sold_shares_over_prior_shares.max())})
    pd.DataFrame(rows).to_csv(out / "executed_action_summary.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
