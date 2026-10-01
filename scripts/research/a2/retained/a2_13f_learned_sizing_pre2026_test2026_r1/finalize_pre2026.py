"""Post-freeze descriptive pre-2026 replay; never evaluates 2026."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from train_pre2026 import (HERE, OLD, R4, FULL, capped, get_module, load_data,
                           replay, sha, targets)


def model_weights(model, name, raw, usable):
    fit = model["fits"][name]
    if fit["columns"] != (FULL if name == "M_FULL" else FULL[:2]):
        raise RuntimeError("MODEL_COLUMN_IDENTITY_CHANGED")
    raw_spec = raw[:, :, [FULL.index(c) for c in fit["columns"]]]
    mean, std = np.array(fit["mean"]), np.array(fit["std"])
    constant = std < 1e-12
    phi = np.clip((raw_spec-mean) / np.where(constant,1.0,std),-5,5)
    phi[:,:,constant] = 0
    return targets(phi,np.array(fit["theta"]),usable)


def main():
    manifest_path = HERE / "RUN_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] in {"MODEL_FROZEN", "MODEL_FROZEN_TEST2026_DATA_GAP"}
    model_path = HERE / "MODEL_FROZEN.json"
    assert sha(model_path) == manifest["model_frozen_sha256"]
    model = json.loads(model_path.read_text(encoding="utf-8"))
    panel, dates, execution, path_end, usable, raw, ids, opens, calendar, prices = load_data()
    assert dates.max() < pd.Timestamp("2026-01-01")
    assert sha(HERE/"PIT_PRE2026_TOP20_VH_PANEL.parquet") == model["input_sha256"]["PIT_PRE2026_TOP20_VH_PANEL.parquet"]
    weights = {"B0_RAW":np.full((len(dates),20),0.05),
               "M_FULL":model_weights(model,"M_FULL",raw,usable),
               "M_NO13F":model_weights(model,"M_NO13F",raw,usable)}
    m = panel.M_full_initial_usd.to_numpy().reshape(-1,20)
    mechanical = np.full_like(m,0.05)
    zero_amount_days = 0
    for day in range(len(m)):
        if usable[day] and m[day].sum()>0:
            mechanical[day] = capped(m[day]/m[day].sum())
        elif usable[day]:
            zero_amount_days += 1
    weights["B2_FULL_CAPPED"] = mechanical
    rows = []
    for policy,values in weights.items():
        for j,(rec, w) in enumerate(zip(panel.itertuples(index=False),values.reshape(-1))):
            day=j//20
            reason=("UNKNOWN_AMENDMENT_VERSION" if not rec.full_vh_usable else
                    "INVALID_OR_INSUFFICIENT_SIGMA20" if not usable[day] else "")
            rows.append({"signal_date":rec.signal_date,"ticker":rec.ticker,"a2_rank":rec.a2_rank,
                         "report_quarter":rec.report_quarter,"cusip":rec.cusip,
                         "policy":policy,"target_weight":w,"weight_over_b0":w/0.05,
                         "fallback":bool(not usable[day]) if policy!="B0_RAW" else False,
                         "fallback_reason":reason if policy!="B0_RAW" else "",
                         "input_status":rec.input_status})
    pd.DataFrame(rows).to_parquet(HERE/"PRE2026_FINAL_FIT_INSAMPLE_WEIGHTS.parquet",index=False,compression="zstd")
    r4 = get_module(R4)
    r0f_script = Path("D:/us-tech-quant/scripts/v22/fast_a2_r0f_corporate_action_and_nav_forensic_audit.py")
    r0f = get_module(r0f_script)
    signals = panel.drop_duplicates(["signal_date","ticker"]).copy()
    signals["a1_rank"] = signals.a2_rank
    original = r4.build_target_map
    metrics = []
    position_ledgers = {}
    for policy,values in weights.items():
        target = {date: dict(zip(panel.loc[panel.signal_date.eq(date)].ticker,values[d]))
                  for d,date in enumerate(dates)}
        try:
            r4.build_target_map = lambda *_args, **_kwargs: target
            r4_daily = r4.simulate_portfolio(signals, prices, policy, "a2_rank", 20, 10)
        finally:
            r4.build_target_map = original
        fast_nav,_ = replay(np.arange(len(dates)),values,ids,opens,calendar,dates)
        assert abs(fast_nav-float(r4_daily.net_nav.iloc[-1])) <= 1e-10
        native = r0f.reconstruct_path(model=policy,target_map=target,qfq=prices,
                                      signal_dates=dates,cost_bps=10)
        assert np.max(np.abs(native.daily.reconstructed_daily_return.to_numpy()-r4_daily.net_return.to_numpy())) <= 1e-12
        for field in ("NAV_ACCOUNTING_IDENTITY_ERROR","CASH_IDENTITY_ERROR",
                      "POSITION_VALUE_IDENTITY_ERROR","TURNOVER_IDENTITY_ERROR",
                      "TRANSACTION_COST_IDENTITY_ERROR"):
            assert native.daily[field].abs().max() <= 1e-10
        r4_daily.to_parquet(HERE/f"PRE2026_INSAMPLE_{policy}_R4_DAILY.parquet",index=False)
        native.daily.to_parquet(HERE/f"PRE2026_INSAMPLE_{policy}_CASH_DAILY.parquet",index=False)
        native.positions.to_parquet(HERE/f"PRE2026_INSAMPLE_{policy}_POSITIONS.parquet",index=False)
        native.trades.to_parquet(HERE/f"PRE2026_INSAMPLE_{policy}_TRADES.parquet",index=False)
        position_ledgers[policy]=native.positions
        metrics.append({"stage":"FINAL_FIT_INSAMPLE_NOT_OOF", "policy":policy,
                        "execution_days":len(r4_daily),"terminal_nav":float(r4_daily.net_nav.iloc[-1]),
                        "cumulative_return":float(r4_daily.net_nav.iloc[-1]-1),
                        "total_cost_amount":float(r4_daily.transaction_cost_amount.sum()),
                        "total_executed_turnover":float(r4_daily.executed_turnover.sum()),
                        "fallback_signal_days":int((~usable).sum()) if policy != "B0_RAW" else 0,
                        "cap_hit_target_rows":int((values>=0.1-1e-10).sum()),
                        "mean_target_effective_n":float(np.mean(1/np.sum(values*values,axis=1))),
                        "r4_r0f_max_abs_daily_return_error":float(np.max(np.abs(native.daily.reconstructed_daily_return.to_numpy()-r4_daily.net_return.to_numpy()))),
                        **r4.portfolio_metrics(r4_daily)})
    pd.DataFrame(metrics).to_csv(HERE/"PRE2026_FINAL_FIT_INSAMPLE_POLICY_METRICS.csv",index=False)
    baseline_contrib=position_ledgers["B0_RAW"].groupby("ticker").net_pnl_contribution.sum()
    for policy in ("B2_FULL_CAPPED","M_NO13F","M_FULL"):
        contribution=position_ledgers[policy].groupby("ticker").net_pnl_contribution.sum()
        contribution.sub(baseline_contrib,fill_value=0).sort_values().rename("delta_terminal_nav_vs_b0").to_csv(
            HERE/f"PRE2026_INSAMPLE_{policy}_SECURITY_CONTRIBUTION_VS_B0.csv")
    # Each development fold and confirmation remains a separate, fresh-capital interval.
    stage_windows = [("DEV_1","2024-01-01","2024-06-30"),("DEV_2","2024-07-01","2024-12-31"),
                     ("CONFIRM_2025","2025-01-01","2025-12-31")]
    comparisons=[]
    fit_log=pd.read_csv(HERE/"FIT_LOG.csv")
    for stage,start,end in stage_windows:
        selected_indices=np.flatnonzero((execution>=pd.Timestamp(start)) & (path_end<=pd.Timestamp(end)))
        b2_nav,_=replay(selected_indices,mechanical,ids,opens,calendar,dates)
        for _,row in fit_log.loc[fit_log.stage.eq(stage)].iterrows():
            if stage.startswith("DEV") and manifest["selected_lambda"][row["name"]] != row["lambda"]:
                continue
            comparisons.append({"stage":stage,"model":row["name"],"selected_lambda":row["lambda"],
                                "execution_days":len(selected_indices)+1,"model_nav":row.model_nav,
                                "b0_nav":row.b0_nav,"b2_full_capped_nav":b2_nav,
                                "model_minus_b0_nav":row.model_nav-row.b0_nav,
                                "model_minus_b2_nav":row.model_nav-b2_nav,
                                "fallback_signal_days":int((~usable[selected_indices]).sum())})
    pd.DataFrame(comparisons).to_csv(HERE/"FOLD_COMPARISONS.csv",index=False)
    manifest["stages"]["report"]="PRE2026_LEDGER_AND_FOLD_COMPARISONS_COMPLETE"
    manifest["pre2026_final_insample_metrics"]={r["policy"]:r["terminal_nav"] for r in metrics}
    manifest["pre2026_zero_amount_days"] = zero_amount_days
    manifest["r0f_source_sha256"] = sha(r0f_script)
    manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"policy_metrics":metrics,"fold_comparisons":comparisons},indent=2,default=str))

if __name__=="__main__":
    main()
