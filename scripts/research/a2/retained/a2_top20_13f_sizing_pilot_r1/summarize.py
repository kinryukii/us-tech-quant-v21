import json
from pathlib import Path

import pandas as pd

p = Path(__file__).resolve().parent
m = json.loads((p / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
x = pd.read_csv(p / "POLICY_METRICS.csv")
print(x[["policy", "year", "observation_count", "cumulative_return", "gross_cumulative_return", "cagr", "annualized_volatility", "sharpe_rf0", "max_drawdown", "total_turnover", "total_transaction_cost"]].to_string(index=False))
a = x.loc[(x.policy == "B0_RAW") & (x.year == "ALL")].iloc[0]
b = x.loc[(x.policy == "B2_OBSERVED_TOP100") & (x.year == "ALL")].iloc[0]
print("nav_ratio", (1 + b.cumulative_return) / (1 + a.cumulative_return))
w = pd.read_csv(p / "WEIGHTS.csv")
g = w.groupby("signal_date")
print("coverage", len(w), g.ngroups, w.report_quarter.nunique(), w.input_status.value_counts().to_dict())
print("positive_count", g.B2_OBSERVED_TOP100.apply(lambda s: (s > 0).sum()).describe().to_dict())
print("max_weight", g.B2_OBSERVED_TOP100.max().describe().to_dict())
print("effective_n", g.B2_OBSERVED_TOP100.apply(lambda s: 1 / s.pow(2).sum()).describe().to_dict())
print("half_l1", g.apply(lambda z: abs(z.B2_OBSERVED_TOP100 - z.B0_RAW).sum() / 2).describe().to_dict())
print("top_contrib", pd.read_csv(p / "B2_MINUS_B0_SECURITY_CONTRIBUTION.csv").head(8).to_dict("records"))
print("bottom_contrib", pd.read_csv(p / "B2_MINUS_B0_SECURITY_CONTRIBUTION.csv").tail(5).to_dict("records"))
print("top_dates", pd.read_csv(p / "B2_MINUS_B0_DATE_SECURITY_CONTRIBUTION.csv").head(5).to_dict("records"))
print("ledger_counts", m["native_ledger_counts"])
