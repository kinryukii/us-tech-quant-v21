"""Descriptive fixed-policy comparison; never selects a configuration."""
from __future__ import annotations

import numpy as np
import pandas as pd

from policy_engine import HERE


def frame_for(fold: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    prefix = f"DEVELOPMENT_{fold}" if fold in ("D1", "D2") else "V25" if fold == "V25" else "FINAL_INSAMPLE"
    daily = [pd.read_parquet(HERE / f"{prefix}_POLICY_DAILY.parquet")]
    weights = [pd.read_parquet(HERE / f"{prefix}_WEIGHTS.parquet")]
    for suffix in ("P10_DAILY", "P10_WEIGHTS"):
        path = HERE / f"{prefix}_{suffix}.parquet"
        if path.exists():
            if suffix.endswith("DAILY"):
                daily.append(pd.read_parquet(path))
            else:
                weights.append(pd.read_parquet(path))
    return pd.concat(daily, ignore_index=True), pd.concat(weights, ignore_index=True)


def summarize(fold: str) -> list[dict]:
    daily, weights = frame_for(fold)
    baseline = daily.loc[daily.policy.eq("B0")].sort_values("execution_date").net_nav_at_execution.to_numpy(float)
    rows = []
    for policy, path in daily.groupby("policy"):
        path = path.sort_values("execution_date")
        nav = path.net_nav_at_execution.to_numpy(float)
        assert len(nav) == len(baseline) and (nav > 0).all()
        ret = np.diff(np.log(np.r_[1., nav]))
        vol = float(ret.std(ddof=0) * np.sqrt(252))
        peak = np.maximum.accumulate(np.r_[1., nav])
        drawdown = float(np.min(np.r_[1., nav] / peak - 1))
        target = weights.loc[weights.policy.eq(policy)]
        w = target.target_weight.to_numpy(float)
        rows.append({"fold": fold, "policy": policy, "execution_steps": len(path),
                     "terminal_nav": float(nav[-1]),
                     "terminal_ratio_to_b0": float(nav[-1] / baseline[-1]),
                     "annualized_log_volatility": vol,
                     "annualized_log_sharpe_zero_cash_rate": float(ret.mean() * 252 / vol) if vol > 0 else np.nan,
                     "max_drawdown": drawdown,
                     "fees_amount": float(path.fee.sum()),
                     "half_turnover_sum": float((.5 * path.traded_notional /
                                                 (path.net_nav_at_execution + path.fee)).sum()),
                     "mean_stock_target_exposure": float(path.loc[path.fallback.ne("TERMINAL_LIQUIDATION"), "stock_target_sum"].mean()),
                     "mean_cash_target": float(target.cash_target.mean()),
                     "cap_hit_count": int(np.count_nonzero(np.isclose(w, .10, atol=1e-7))),
                     "target_rows": len(w),
                     "base_input_fallback_days": int(path.fallback.eq("BASE_INPUT_FALLBACK").sum()),
                     "risk_fallback_days": int(path.fallback.eq("RISK_TO_DIAG").sum())})
    return rows


if __name__ == "__main__":
    # Choose only path files that actually exist; no hidden evaluation is triggered.
    folds = [f for f in ("D1", "D2", "V25", "FINAL") if
             (HERE / f"{'DEVELOPMENT_' + f if f in ('D1','D2') else 'V25' if f == 'V25' else 'FINAL_INSAMPLE'}_POLICY_DAILY.parquet").exists()]
    table = pd.DataFrame([row for fold in folds for row in summarize(fold)])
    table.to_csv(HERE / "POLICY_COMPARISON.csv", index=False)
    print(table[["fold", "policy", "terminal_nav", "terminal_ratio_to_b0"]].to_string(index=False))
