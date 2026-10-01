"""Independent saved-ledger arithmetic audit; no model imports, fitting or replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parent / "original_A2_scores_common_account_reference_r1/account"
POLICIES = ["base_ridge", "base_hgb", "base_mlp", "fixed_pred", "learned_fixed", "stack_ridge",
            "stack_mlp", "conditional_gate", "ridge_then_hgb", "hgb_then_ridge", "decision_blend"]
KEYS = ["daily", "trades", "positions", "target_decisions", "signal_contexts", "execution_results"]


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def close(actual, expected, tol, name):
    a, b = np.asarray(actual, float), np.asarray(expected, float)
    assert a.shape == b.shape, (name, "shape", a.shape, b.shape)
    assert np.array_equal(np.isnan(a), np.isnan(b)), (name, "missingness")
    mask = np.isfinite(a) & np.isfinite(b)
    assert np.all(mask | (np.isnan(a) & np.isnan(b))), (name, "nonfinite")
    err = float(np.max(np.abs(a[mask]-b[mask]))) if mask.any() else 0.
    assert err <= tol, (name, err, tol)
    return err


def validate(folder, forecast, calendar, expected_signals):
    receipt = read(folder / "PATH_COMPLETE.json")
    for key, digest in receipt["ledger_sha256"].items():
        assert sha(folder/f"{key}.parquet") == digest, f"LEDGER_HASH_DRIFT:{folder}:{key}"
    frames = {k: pd.read_parquet(folder/f"{k}.parquet") for k in KEYS}
    d, tr, pos, tar, ctx, exe = [frames[k] for k in KEYS]
    assert pd.DatetimeIndex(d.date).equals(calendar), (folder, "FULL_CALENDAR")
    assert not d.date.duplicated().any() and len(d) in [128, 183]
    assert pd.DatetimeIndex(ctx.signal_date).equals(expected_signals)
    assert not pos.duplicated(["date", "ticker"]).any()
    assert not tar.order_id.duplicated().any()
    assert d.cash.ge(-1e-7).all() and d.actual_name_count.le(20).all()
    assert set(tr.side).issubset({"BUY", "SELL"})
    assert tr.index_units.gt(0).all() and tr.price.gt(0).all() and tr.notional.gt(0).all()
    assert tr.execution_date.isin(calendar).all() and tr.signal_date.isin(expected_signals).all()
    next_session = dict(zip(calendar[:-1], calendar[1:]))
    assert (tr.signal_date.map(next_session) == tr.execution_date).all()
    assert (tar.signal_date.map(next_session) == tar.execution_date).all()
    assert (exe.signal_date.map(next_session) == exe.execution_date).all()
    notional_error = close(tr.index_units*tr.price, tr.notional, 1e-6, "units_times_price")
    fee_error = close(tr.transaction_cost, tr.notional*.001, 1e-7, "one_way_10bp")
    assert tr.cost_bps.eq(10).all()

    # Independently accumulate dollar cash from every trade, not daily error fields.
    cash_change = np.where(tr.side.eq("SELL"),tr.notional,-tr.notional)-tr.transaction_cost
    daily_change = pd.Series(np.asarray(cash_change,float),index=tr.execution_date).groupby(level=0).sum().reindex(calendar,fill_value=0)
    cash_error = close(d.cash, 1e6+daily_change.cumsum().to_numpy(), 1e-5, "cash_from_all_trades")
    fees=tr.groupby("execution_date").transaction_cost.sum().reindex(calendar,fill_value=0)
    close(d.transaction_cost_amount,fees.to_numpy(),1e-6,"daily_fees")
    for side,field in [("BUY","buy_notional"),("SELL","sell_notional")]:
        total=tr.loc[tr.side.eq(side)].groupby("execution_date").notional.sum().reindex(calendar,fill_value=0)
        close(d[field],total.to_numpy(),1e-6,f"daily_{side}_notional")

    # Full union of all ever traded AND actual position tickers avoids hiding an
    # unexplained holding by reindexing solely to the traded ticker columns.
    changes=tr.assign(net_units=np.where(tr.side.eq("BUY"),tr.index_units,-tr.index_units)).pivot_table(
        index="execution_date",columns="ticker",values="net_units",aggfunc="sum",fill_value=0)
    tickers=sorted(set(tr.ticker)|set(pos.ticker))
    expected=changes.reindex(index=calendar,columns=tickers,fill_value=0).fillna(0).cumsum()
    actual=pos.pivot(index="date",columns="ticker",values="index_units").reindex(index=calendar,columns=tickers).fillna(0)
    units_error=close(actual.to_numpy(),expected.to_numpy(),1e-7,"positions_from_all_net_units")
    assert actual.ge(-1e-10).all().all()
    actual_counts=pos.groupby("date").size().reindex(calendar,fill_value=0)
    close(d.actual_name_count,actual_counts.to_numpy(),0,"position_count")
    close(pos.market_value,pos.index_units*pos.mark,1e-6,"position_valuation")
    market=pos.groupby("date").market_value.sum().reindex(calendar,fill_value=0)
    known=d.nav.notna()
    nav_error=close(d.loc[known,"nav"],(d.cash+market.to_numpy()).loc[known],1e-5,"NAV_cash_plus_positions")
    stale=pos.groupby("date").stale.sum().reindex(calendar,fill_value=0)
    unknown=pos.groupby("date").unknown.sum().reindex(calendar,fill_value=0)
    close(d.stale_count,stale.to_numpy(),0,"stale_counts")
    close(d.unknown_count,unknown.to_numpy(),0,"unknown_counts")
    certified=(stale.to_numpy()==0)&(unknown.to_numpy()==0)&np.isfinite(d.nav.to_numpy())
    assert np.array_equal(d.certified_nav.notna().to_numpy(),certified)
    close(d.loc[certified,"certified_nav"],d.loc[certified,"nav"],0,"certified_NAV")
    close(d.loc[known,"cash_weight"],(d.cash/d.nav).loc[known],1e-10,"cash_weight_ratio")

    # Capacity and eligibility use frozen signal-day observations, not execution
    # dates or a recreated feature panel.
    buys=tr[tr.side.eq("BUY")].merge(tar[["order_id","signal_day_adv"]],on="order_id",validate="one_to_one")
    assert buys.signal_day_adv.gt(0).all()
    assert (buys.notional<=.01*buys.signal_day_adv+1e-6).all()
    if forecast is not None:
        observed=buys.merge(forecast[["signal_date","ticker","new_buy_eligible","avg_dollar_volume_20d"]],
                            on=["signal_date","ticker"],how="left",validate="many_to_one")
        assert observed.new_buy_eligible.fillna(False).all()
        close(observed.signal_day_adv,observed.avg_dollar_volume_20d,1e-6,"signal_ADV_source")
    assert tar.raw_model_weight.dropna().ge(0).all() and tar.raw_model_weight.dropna().le(.0475+1e-8).all()

    # Audit no-decision old holdings by quantities at signal and execution; a
    # missing model key never becomes an implicit sale or apparent cash.
    no_decision=tar[tar.decision_semantic.eq("MODEL_NO_DECISION")&tar.current_units.gt(0)].copy()
    assert no_decision.order_type.eq("HOLD_UNITS").all()
    close(no_decision.hold_units,no_decision.current_units,1e-9,"saved_hold_units")
    pos_units=pos.set_index(["date","ticker"]).index_units
    signal_index=pd.MultiIndex.from_arrays([no_decision.signal_date,no_decision.ticker])
    execution_index=pd.MultiIndex.from_arrays([no_decision.execution_date,no_decision.ticker])
    close(no_decision.current_units,pos_units.reindex(signal_index).to_numpy(),1e-7,"held_signal_units")
    hold_error=close(no_decision.current_units,pos_units.reindex(execution_index).to_numpy(),1e-7,"no_decision_units_preserved")
    assert not tr.order_id.isin(no_decision.order_id).any()
    preserve=exe[exe.order_id.isin(no_decision.order_id)]
    assert len(preserve)==len(no_decision) and preserve.status.eq("PRESERVED_UNITS").all()
    filled=exe[exe.status.eq("FILLED")]
    assert len(filled)==len(tr)
    matching=tr.merge(filled,on="order_id",suffixes=("_trade","_execution"),validate="one_to_one")
    for field in ["index_units","notional","transaction_cost"]:
        close(matching[field+"_trade"],matching[field+"_execution"],1e-7,"fill_"+field)
    assert matching.side_trade.eq(matching.side_execution).all()
    assert int(receipt["metrics"]["uncertified_days"])==int((~certified).sum())
    return {"status":"PASS","policy":folder.name,"calendar_days":len(d),"signal_days":len(ctx),
            "trades":len(tr),"buy_trades_checked":len(buys),"no_decision_held_events_checked":len(no_decision),
            "uncertified_days":int((~certified).sum()),"uncertified_dates":[str(x.date()) for x in d.loc[~certified,"date"]],
            "all_problem_dates_retained":True,"cash_error_max_usd":cash_error,"unit_price_error_max_usd":notional_error,
            "fee_error_max_usd":fee_error,"net_units_position_error_max":units_error,"NAV_error_max_usd":nav_error,
            "no_decision_preservation_error_max_units":hold_error,"fit_calls":0,"new_replays":0}


def main():
    # No polling or starting work against a partial path. Caller must wait for
    # both independent evaluations to finish before invoking this audit.
    for year in [2025,2026]:
        completion=ROOT/f"evaluation_{year}/COMPLETE.json"
        if not completion.exists():
            raise RuntimeError(f"EVALUATION_NOT_COMPLETE_NO_AUDIT_POLLING:{year}")
        receipt=read(completion)
        assert receipt["status"]=="PASS" and receipt["policies"]==11
    sources={}
    def remember(path):
        sources[str(path)]=sha(path)
    remember(Path(__file__))
    remember(REFERENCE/"PATH_COMPLETE.json")
    for key in KEYS:
        remember(REFERENCE/f"{key}.parquet")
    reference_daily=pd.read_parquet(REFERENCE/"daily.parquet")
    calendar_h2=pd.DatetimeIndex(reference_daily.date)
    reference_signals=pd.DatetimeIndex(pd.read_parquet(REFERENCE/"signal_contexts.parquet").signal_date)
    assert len(calendar_h2)==128 and str(calendar_h2[0].date())=="2025-07-01" and str(calendar_h2[-1].date())=="2025-12-31"
    reference_audit=validate(REFERENCE,None,calendar_h2,reference_signals)
    results=[]
    for year in [2025,2026]:
        evaluation=ROOT/f"evaluation_{year}"
        remember(evaluation/"COMPLETE.json");remember(evaluation/"FROZEN_BEFORE_REPLAY.json")
        frozen=read(evaluation/"FROZEN_BEFORE_REPLAY.json")
        assert frozen["policies"]==POLICIES
        remember(evaluation/"FROZEN_FORECASTS.parquet")
        forecast=pd.read_parquet(evaluation/"FROZEN_FORECASTS.parquet",columns=["signal_date","ticker","new_buy_eligible","avg_dollar_volume_20d"])
        assert not forecast.duplicated(["signal_date","ticker"]).any()
        expected_signals=pd.DatetimeIndex(sorted(forecast.signal_date.unique()))
        if year==2025:
            calendar=calendar_h2
            assert expected_signals.equals(reference_signals) and len(expected_signals)==126
        else:
            assert len(expected_signals)==181 and expected_signals[0]==pd.Timestamp("2026-01-02") and expected_signals[-1]==pd.Timestamp("2026-09-22")
            calendar=expected_signals.append(pd.DatetimeIndex(["2026-09-23","2026-09-24"]))
            assert len(calendar)==183
        for policy in POLICIES:
            folder=evaluation/policy
            remember(folder/"PATH_COMPLETE.json")
            for key in read(folder/"PATH_COMPLETE.json")["ledger_sha256"]:
                remember(folder/f"{key}.parquet")
            audit=validate(folder,forecast,calendar,expected_signals);audit["year"]=year
            results.append(audit)
            print(f"AUDIT_PASS {year}/{policy} days={audit['calendar_days']} uncertified={audit['uncertified_days']}",flush=True)
    assert len(results)==22
    assert all(sha(Path(p))==digest for p,digest in sources.items()),"AUDITED_LEDGER_OR_INPUT_CHANGED"
    report={"status":"PASS_INDEPENDENT_SAVED_LEDGER_AUDIT","new_policy_paths":22,"reference_paths_read_only":1,
            "new_policy_daily_rows":sum(r["calendar_days"] for r in results),"fit_calls":0,"model_loads":0,"new_replays":0,
            "source_files_unchanged":True,"source_sha256":sources,"reference_audit":reference_audit,"path_audits":results,
            "scope":"Independent dollar and quantity arithmetic; all 128/183 days retained; no recomputation of models or strategy paths",
            "qualification_limits":["Ledger arithmetic certification does not certify shareholder total returns or economic event mappings.",
                                    "2026 unqualified NAV days are retained and enumerated per new policy, not copied from legacy strategies.",
                                    "2025 dates checked against the saved common-account reference; 2026 dates checked against all 181 frozen signal dates plus two fixed terminal sessions."]}
    (ROOT/"INDEPENDENT_LEDGER_AUDIT.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["status","new_policy_paths","new_policy_daily_rows","source_files_unchanged"]}),flush=True)


if __name__=="__main__":
    main()
