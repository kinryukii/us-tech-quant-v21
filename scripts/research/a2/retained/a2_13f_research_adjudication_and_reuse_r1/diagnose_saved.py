"""Read-only diagnostics of already-saved predictions and account paths; no fit or QP."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SOURCE = Path(r"C:\Users\Lenovo\Documents\CODING开发\top20_multimethod_pre2026_test2026_r1")
OUT = Path(__file__).parent
sys.path.insert(0, str(SOURCE))
from policy_engine import selected_prediction  # noqa: E402
from fit_supervised import model_key  # noqa: E402


def prediction(fold, family):
    p = selected_prediction(fold, family).copy()
    if family == "LOGISTIC":
        selection = json.loads((SOURCE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"]
        meta = json.loads((SOURCE / "models" / f"{model_key(fold, family, selection[family])}.json").read_text(encoding="utf-8"))
        p["prediction"] = p.prediction * meta["m_positive_decimal"] + (1 - p.prediction) * meta["m_nonpositive_decimal"]
    return p


rows = []
summary = {}
panel = pd.read_parquet(SOURCE / "PRE2026_SHARED_PANEL.parquet")[
    ["signal_date", "experiment_security_key", "execution_date", "label_end_date", "gross_return_decimal"]]
assert not panel.duplicated(["signal_date", "experiment_security_key"]).any()
for fold in ("D1", "D2", "V25", "FINAL"):
    prefix = f"DEVELOPMENT_{fold}" if fold in ("D1", "D2") else "V25" if fold == "V25" else "FINAL_INSAMPLE"
    weights = pd.read_parquet(SOURCE / f"{prefix}_WEIGHTS.parquet")
    daily = pd.read_parquet(SOURCE / f"{prefix}_POLICY_DAILY.parquet")
    s = {}
    for family in ("RIDGE", "ELASTIC", "LOGISTIC", "HGB", "MLP", "HGB_NO13F", "QUANTILE"):
        p = prediction(fold, family)
        joined = p.merge(panel, on=["signal_date", "experiment_security_key"],
                         how="left", validate="one_to_one", suffixes=("", "_panel"))
        assert len(joined) == len(p) and joined.execution_date.notna().all() and joined.label_end_date.notna().all()
        assert joined.label_end_date.ge(joined.execution_date).all()
        assert np.allclose(joined.gross_return_decimal, joined.gross_return_decimal_panel, atol=0, rtol=0)
        if family == "QUANTILE":
            vals = p[["q10", "q50", "q90"]].to_numpy(float).copy()
            vals.sort(axis=1)
            y = p.gross_return_decimal.to_numpy(float)
            s[family] = {"rows": len(p), "coverage80": float(np.mean((y >= vals[:, 0]) & (y <= vals[:, 2]))),
                         "lower_tail": float(np.mean(y < vals[:, 0])), "upper_tail": float(np.mean(y > vals[:, 2]))}
            for day, block in p.groupby("signal_date", sort=True):
                x = block.q50.to_numpy(float)
                y_day = block.gross_return_decimal.to_numpy(float)
                good = np.isfinite(x) & np.isfinite(y_day)
                rho = np.nan
                if good.sum() >= 3 and np.unique(x[good]).size > 1 and np.unique(y_day[good]).size > 1:
                    rho = float(spearmanr(x[good], y_day[good]).statistic)
                rows.append({"fold": fold, "family": "QUANTILE_Q50", "signal_date": day,
                             "valid_names": int(good.sum()), "spearman": rho})
            continue
        if family == "LOGISTIC":
            raw = selected_prediction(fold, family)
            y = raw.up_label.to_numpy(float)
            pr = np.clip(raw.prediction.to_numpy(float), 1e-15, 1 - 1e-15)
            s["LOGISTIC_PROB"] = {"brier": float(np.mean((pr-y)**2)), "logloss": float(np.mean(-(y*np.log(pr)+(1-y)*np.log1p(-pr))))}
        else:
            s[family] = {"mse": float(np.mean((p.prediction-p.gross_return_decimal)**2))}
        for day, block in p.groupby("signal_date", sort=True):
            x = block.prediction.to_numpy(float)
            y = block.gross_return_decimal.to_numpy(float)
            good = np.isfinite(x) & np.isfinite(y)
            rho = np.nan
            if good.sum() >= 3 and np.unique(x[good]).size > 1 and np.unique(y[good]).size > 1:
                rho = float(spearmanr(x[good], y[good]).statistic)
            rows.append({"fold": fold, "family": family, "signal_date": day, "valid_names": int(good.sum()), "spearman": rho})
    for policy, family in (("P3", "LOGISTIC"), ("P4", "HGB"), ("P6", "HGB_NO13F")):
        w = weights.loc[weights.policy.eq(policy)].copy()
        p = prediction(fold, family)
        merged = w.merge(p, left_on=["signal_date", "security_key"], right_on=["signal_date", "experiment_security_key"], validate="one_to_one")
        active = merged.target_weight.to_numpy(float) - .05
        error = (merged.prediction - merged.gross_return_decimal).to_numpy(float)
        valid = np.isfinite(active) & np.isfinite(error)
        if valid.sum() == 0:
            corr = None
        else:
            corr = float(spearmanr(np.abs(active[valid]), np.abs(error[valid])).statistic)
        rd = daily.loc[daily.policy.eq(policy) & daily.signal_date.notna()].copy()
        s[policy] = {"weight_rows": len(w), "matched_prediction_rows": len(merged),
                     "mean_abs_active_weight": float(np.abs(active).mean()),
                     "abs_active_abs_error_spearman": corr,
                     "mean_abs_error_overweight": float(np.mean(np.abs(error[active > 0]))) if (active > 0).any() else None,
                     "mean_abs_error_underweight": float(np.mean(np.abs(error[active < 0]))) if (active < 0).any() else None,
                     "cap10_target_count": int(np.isclose(merged.target_weight, .1, atol=1e-8).sum()),
                     "mean_target_exposure": float(rd.stock_target_sum.mean()),
                     "mean_cash_target": float(merged.groupby("signal_date").cash_target.first().mean()),
                     "mean_actual_cash_at_execution": float(rd.cash_at_execution.mean()),
                     "sum_traded_notional": float(rd.traded_notional.sum()),
                     "sum_fee": float(daily.loc[daily.policy.eq(policy), "fee"].sum()),
                     "fallback_days": rd.fallback.value_counts().to_dict()}
    risk = {}
    for policy in ("P7", "P8"):
        d = daily.loc[daily.policy.eq(policy) & daily.signal_date.notna()]
        p4 = weights.loc[weights.policy.eq("P4"), ["signal_date", "security_key", "target_weight"]].rename(columns={"target_weight":"p4_weight"})
        wp = weights.loc[weights.policy.eq(policy)].merge(p4, on=["signal_date", "security_key"], validate="one_to_one")
        changed = wp.assign(changed=(wp.target_weight-wp.p4_weight).abs()>1e-10).groupby("signal_date").changed.any()
        risk[policy] = {"signal_days": len(d), "risk_to_diag_days": int(d.fallback.eq("RISK_TO_DIAG").sum()),
                        "non_diag_days": int(d.qualification.sum()-d.fallback.eq("RISK_TO_DIAG").sum()),
                        "changed_weight_days_vs_P4": int(changed.sum())}
    s["risk"] = risk
    account = {}
    for policy, d in daily.groupby("policy"):
        terminal = float(d.net_nav_at_execution.iloc[-1])
        fee = float(d.fee.sum())
        account[policy] = {"terminal_nav": terminal, "paid_fees": fee,
                           "gross_pnl_native_path": terminal-1+fee,
                           "reconcile_residual": float((terminal-1+fee)-fee-(terminal-1))}
    s["account"] = account
    summary[fold] = s

pd.DataFrame(rows).to_csv(OUT / "DAILY_RANK_DIAGNOSTIC.csv", index=False)
(OUT / "diagnostic_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
