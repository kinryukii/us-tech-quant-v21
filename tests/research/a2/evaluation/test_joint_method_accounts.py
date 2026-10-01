"""Synthetic execution and information-boundary checks for V24 orchestration."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import joint_method_accounts as driver
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays,TargetDecision

AUDIT=dict(cash_identity_error_max=0,cost_identity_error_max=0,self_finance_error_max=0,
           nav_identity_error_max=0,capacity_violations=0,next_open_violations=0,max_actual_names=1,minimum_cash=0)

def test_catalogue_all106_responsible_roles_and_aliases():
    roles=driver.catalogue()
    assert len(roles)<160
    assert all(driver.resolve_alias(r) in roles for r in range(1,107) if r!=98)
    assert driver.resolve_alias(78)==driver.resolve_alias(77)
    assert driver.resolve_alias(80)==driver.resolve_alias(81)
    assert driver.resolve_alias(104)==driver.resolve_alias(103)
    assert driver.resolve_alias(76)==driver.ANCHOR
    assert driver.resolve_alias(86)==driver.resolve_alias(75)

def test_market_projection_is_pre26_and_slices_every_signal_field():
    dates=pd.date_range("2022-12-29",periods=6)
    arrays=np.ones((6,1))
    market=MarketArrays(dates,["X"],arrays,arrays,signal_asof=dates)
    result,start=driver.evaluation_market(market)
    assert start==3 and result.dates[0]==pd.Timestamp("2023-01-01")
    assert len(result.signal_asof)==len(result.dates)==3
    assert np.array_equal(result.open,market.open[start:])
    assert np.array_equal(result.input_present,market.input_present[start:])

def test_continuous_year_boundary_retains_exact_raw_units_and_entry():
    dates=pd.to_datetime(["2023-12-28","2023-12-29","2024-01-02","2024-01-03"])
    prices=np.array([[10],[11],[12],[13]],float)
    market=MarketArrays(dates,["X"],prices,prices,adv=np.full((4,1),1e9))
    observed=[]
    def policy(day,ctx):
        observed.append((str(ctx.signal_date.date()),ctx.current_units.copy(),ctx.holding_age.copy(),ctx.entry_price.copy()))
        if day==0:return TargetDecision(np.array([[.1]]),np.array([[True]]))
        return TargetDecision(np.array([[0.]]),np.array([[False]]))
    account=dict(base_currency="USD",initial_nav=3000,initial_cash=3000,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
        financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=.1,max_invested=1,
        capacity_fraction=.01)
    replay=run_continuous_account(market,["P"],policy,account)
    assert len(replay.fills)==1 and replay.fills.iloc[0].execution_date==dates[1]
    assert observed[2][1][0,0]==observed[1][1][0,0]>0
    assert observed[2][2][0,0]>observed[1][2][0,0]
    assert observed[2][3][0,0]==11
    assert replay.final_state["entry_date"][0,0]==dates[1].to_datetime64()
    assert driver.account_audits_passed(replay.audit)

def test_scenarios_future_labels_and_maturity_do_not_enter_prior_year():
    rows=[]
    for day in pd.date_range("2022-01-01",periods=35):
        for ticker in ["X","Y"]:
            rows.append(dict(signal_date=day,ticker=ticker,execution_date=day+pd.Timedelta(days=1),
                label_end_date=day+pd.Timedelta(days=6),label_mature_date=day+pd.Timedelta(days=6),
                fit_eligible=True,y_open5=.01 if ticker=="X" else .02))
    rows.append(dict(signal_date=pd.Timestamp("2022-12-29"),ticker="Z",
        execution_date=pd.Timestamp("2022-12-30"),label_end_date=pd.Timestamp("2023-01-10"),
        label_mature_date=pd.Timestamp("2023-01-10"),fit_eligible=True,y_open5=999))
    tables,known,receipts=driver.scenario_inputs(pd.DataFrame(rows),np.array(["X","Y","Z"]))
    assert tables[2023].shape==(35,3)
    assert np.array_equal(known[2023],[True,True,False])
    assert np.all(tables[2023][:,2]==0)
    assert receipts["2023"]["known_assets"]==2
    assert "2022" in receipts["2023"]["label_max"]

def test_padded_unknown_scenario_cannot_be_traded():
    import pytest
    fake=SimpleNamespace(signal_date=pd.Timestamp("2023-01-02"),current_units=np.zeros((1,2)))
    gate=driver.ScenarioCoverageGate(lambda day,ctx:TargetDecision(np.array([[.0,.1]])),{2023:np.array([True,False])})
    with pytest.raises(AssertionError,match="zero empirical"):
        gate(0,fake)

def test_raw_reference_uses_signal_legal_pool_not_top20_prior_filter():
    market=SimpleNamespace(dates=pd.date_range("2023-01-01",periods=1),
       tickers=np.array(["A","B","C"]),new_buy_eligible=np.array([[True,False,True]]),
       input_present=np.ones((1,3),bool),row_present=np.ones((1,3),bool),quality=np.zeros((1,3),bool),
       buy_restricted=np.zeros((1,3),bool),close=np.ones((1,3)),operational_exits={},signal_asof=[pd.Timestamp("2023-01-01")])
    reference=driver.reference_portfolios(market,np.array([[1.,100.,2.]]))[0]
    assert np.array_equal(reference,[.5,0,.5])

def test_missing_native_oof_is_unavailable_not_invented(tmp_path):
    class FakeTask:
        def out(self,relative):return tmp_path/relative
    market=SimpleNamespace(dates=pd.date_range("2023-01-02",periods=2),tickers=np.array(["X"]))
    mu,sigma,complete,deps=driver.forecast_inputs(FakeTask(),market,{"mu":{},"sigma":{}},0,"xgb")
    assert not complete and np.isnan(mu).all() and np.isnan(sigma).all()
    assert len(deps)==3

def test_certified_finalist_strictly_beats_both_controls_tie_id_fixed():
    metrics=[dict(path_id=p,eligible_for_selection=True,final_certified_nav=3500+i)
             for i,p in enumerate(driver.CONTROLS)]
    metrics.extend([dict(path_id="M002",eligible_for_selection=True,final_certified_nav=3600),
                    dict(path_id="M001",eligible_for_selection=True,final_certified_nav=3600),
                    dict(path_id="M030_ZERO",eligible_for_selection=True,final_certified_nav=9000)])
    assert driver.select_finalist(metrics)==("M001",True)

def test_uncertified_control_or_candidate_cannot_select_even_with_higher_engine_nav():
    metrics=[dict(path_id=driver.CONTROLS[0],eligible_for_selection=True,final_certified_nav=3500),
             dict(path_id=driver.CONTROLS[1],eligible_for_selection=False,final_certified_nav=None),
             dict(path_id="M001",eligible_for_selection=True,final_certified_nav=9000)]
    assert driver.select_finalist(metrics)==(None,False)
    metrics[1].update(eligible_for_selection=True,final_certified_nav=3500)
    metrics[2].update(eligible_for_selection=False,final_certified_nav=None)
    assert driver.select_finalist(metrics)==(None,True)

def test_required_audit_failure_cannot_be_ranked():
    assert driver.account_audits_passed(AUDIT)
    assert not driver.account_audits_passed({**AUDIT,"next_open_violations":1})
    assert not driver.account_audits_passed({**AUDIT,"cash_identity_error_max":.01})
    assert not driver.account_audits_passed({**AUDIT,"minimum_cash":-1})

def test_coverage_requires_eligible_new_and_held_but_ignores_unheld_out_of_pool():
    ctx=SimpleNamespace(signal_date=pd.Timestamp("2023-01-02"),current_units=np.array([[0.,0.,2.]]),
        decision_mask=np.ones((1,3),bool),operational_mask=np.zeros((1,3),bool),
        buy_allowed=np.array([[True,False,False]]))
    base=lambda day,ctx:TargetDecision(np.zeros((1,3)),np.zeros((1,3),bool))
    gate=driver.ScientificCoveragePolicy(base,np.array([[1.,np.nan,np.nan]]),np.array([[1.,np.nan,np.nan]]))
    decision=gate(0,ctx)
    assert gate.missing_rows==gate.missing_held_rows==1
    assert gate.records[0]["required_rows"]==2
    assert not decision.explicit_mask.any()

def test_reference_excludes_quote_quality_and_known_buy_restrictions():
    prices=np.ones((1,3))
    market=MarketArrays(pd.to_datetime(["2023-01-02"]),["A","B","C"],prices,prices)
    market.quality[0,1]=True
    market.buy_restricted[0,2]=True
    assert np.array_equal(driver.reference_portfolios(market,np.array([[1.,999.,998.]]))[0],[1.,0.,0.])

def test_effective_event_quality_matches_only_event_session_and_preserves_source_market():
    prices=np.ones((2,1))
    market=MarketArrays(pd.to_datetime(["2023-01-02","2023-01-03"]),["A"],prices,prices)
    projected=driver.with_effective_event_quality(market,{"unsupported_events":[dict(ticker="A",effective_date="2023-01-03")]})
    assert not market.quality.any()
    assert np.array_equal(projected.quality,[[False],[True]])

def test_failure_json_safely_retains_unknown_diagnostics():
    import json
    value=driver.json_safe({"diagnostics":[{"gross_target":np.nan,"status":"FALLBACK"}]})
    assert json.loads(json.dumps(value,allow_nan=False))["diagnostics"][0]["gross_target"] is None

def test_final_record_verification_rejects_mutated_ledger(tmp_path):
    import json,hashlib,pytest
    ledger=tmp_path/"daily.parquet";ledger.write_bytes(b"ledger-before")
    identity={"path_id":"P"};metrics={"path_id":"P","eligible_for_selection":False}
    receipt={"identity":identity,"metrics":metrics,"artifacts":{"daily":{"path":str(ledger),"sha256":driver.digest(ledger)}}}
    file=tmp_path/"receipt.json";file.write_text(json.dumps(receipt),encoding="utf-8")
    class FakeTask:
        root=tmp_path
        def out(self,relative):return tmp_path/relative
        def read(self,relative):return json.loads(self.out(relative).read_text())
    record={"identity":identity,"metrics":metrics,"receipt":"receipt.json","receipt_sha256":driver.digest(file)}
    driver.verify_account_record(FakeTask(),record)
    ledger.write_bytes(b"ledger-after")
    with pytest.raises(ValueError,match="artifact changed"):driver.verify_account_record(FakeTask(),record)

def test_scenarios_reuse_already_estimated_mean_and_reject_other_dates():
    import pytest
    rows=[dict(signal_date=d,ticker="X",execution_date=d+pd.Timedelta(days=1),
         label_end_date=d+pd.Timedelta(days=6),label_mature_date=d+pd.Timedelta(days=6),
         fit_eligible=True,y_open5=.01) for d in pd.date_range("2022-01-01",periods=35)]
    frame=pd.DataFrame(rows);dates=frame.signal_date.sort_values()
    state=SimpleNamespace(status="FITTED",fitted_dates=tuple(d.isoformat() for d in dates),
                          estimated_assets=("X",),fitted_state={"mean":np.array([.01])})
    states={year:(state,{"sha256":"proven_state"}) for year in driver.YEARS}
    _,_,receipts=driver.scenario_inputs(frame,np.array(["X"]),states)
    assert receipts["2023"]["mean_preprocessor"]["new_fit_states"]==0
    state.fitted_dates=state.fitted_dates[:-1]
    with pytest.raises(ValueError,match="dates"):driver.scenario_inputs(frame,np.array(["X"]),states)

