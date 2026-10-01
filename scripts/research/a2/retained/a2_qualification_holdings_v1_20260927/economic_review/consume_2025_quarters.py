"""Read the same complete 2025 accounts and partition by fixed calendar quarter."""
from pathlib import Path
import json
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    folder = ROOT / "evaluation_2025/cost_10"
    records = []
    for policy in pd.read_csv(folder / "comparison.csv").policy:
        d = pd.read_parquet(folder / policy / "daily.parquet").sort_values("date")
        assert len(d) == 250 and d.valuation_status.eq("certified").all()
        assert d.certified_nav.notna().all()
        initial = json.loads((folder / policy / "metadata.json").read_text(encoding="utf-8"))["initial_cash"]
        start_value = float(initial)
        for quarter, group in d.groupby(d.date.dt.to_period("Q"), sort=True):
            end_value = float(group.certified_nav.iloc[-1])
            records.append(dict(policy=policy, quarter=str(quarter), sessions=len(group),
                first_date=str(group.date.iloc[0].date()), last_date=str(group.date.iloc[-1].date()),
                beginning_value_previous_close_or_initial=start_value, ending_value=end_value,
                net_index_return=end_value / start_value - 1))
            start_value = end_value
    result = pd.DataFrame(records)
    for control, label in [("joint_rl_zero_control", "minus_rl_zero_pp"),
                           ("hgb_return_baseline", "minus_return_baseline_pp")]:
        reference = result.loc[result.policy.eq(control)].set_index("quarter").net_index_return
        result[label] = (result.net_index_return - result.quarter.map(reference)) * 100
    result.to_csv(HERE / "FULL_2025_QUARTERS.csv", index=False, encoding="utf-8-sig")
    print(result.loc[result.policy.isin(["joint_rl_ensemble", "joint_rl_zero_control", "joint_mlp", "hgb_return_baseline"]),
        ["policy", "quarter", "sessions", "net_index_return", "minus_rl_zero_pp"]].to_string(index=False))


if __name__ == "__main__":
    main()
