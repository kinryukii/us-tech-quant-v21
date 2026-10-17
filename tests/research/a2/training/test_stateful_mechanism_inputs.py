"""R10 input adapter tests: in-memory synthetic frames and temp fixtures only.
No real market/feature/label reads, native learner fits, provider or account.
"""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_mechanism_inputs as m


def calendar():
    return pd.bdate_range("2024-01-02", periods=45)


def prediction(names=("A", "B"), days=15):
    rows = []
    for j, d in enumerate(calendar()[:days]):
        for k, t in enumerate(names):
            rows.append({"signal_date": d, "ticker": t, "security_id": "SID_"+t,
                         "feature_available": True, "is_raw_top20": True,
                         "raw_top20_set_complete": len(names)==20,
                         "new_buy_eligible": (j==0 or (j==2 and t=="B")),
                         "raw_a2_rank": k+1, "raw_a2_prediction": .1-j*.001,
                         **{c: .01 for c in m.FEATURES}})
    return pd.DataFrame(rows)


def labels(pred):
    f=pred[["signal_date", "ticker", "security_id"]].copy()
    f["label_qualified"]=True; f["label_value"]=.05
    f["label_mature_date"]=f.signal_date+pd.Timedelta(days=6)
    f["source_label_identity"]="SYNTHETIC_H5"
    return f


def pair_frame():
    d=calendar()[2]
    return pd.DataFrame([{"signal_date":d,"entrant":"B","entrant_sid":"SID_B",
                          "incumbent":i,"incumbent_sid":"SID_"+i,"pair_id":"PAIR_"+i,
                          "pair_count_before_labels":2,"pre_label_group_weight":.5}
                         for i in ("A","C")])


def window(plan, records):
    quantity=np.ones(len(plan)); unsupported=np.zeros(len(plan),bool); count=np.zeros(len(plan),int)
    for event in records:
        mask=plan.ticker.eq(event["ticker"]) & plan.execution_date.lt(event["date"]) & plan.label_end_date.ge(event["date"])
        count[mask]+=1
        if event["supported"]:quantity[mask]*=event["quantity"]
        else:unsupported[mask]=True
    return quantity,unsupported,count


def plan(h=5, events=(), projection=None):
    p=prediction(days=35)
    q=p[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"})
    key=p.loc[p.signal_date.eq(calendar()[0]),["signal_date","ticker","security_id"]]
    return m.native_endpoint_plan(key,calendar(),h,p if projection is None else projection,q,events,window,"SYNTHETIC_NATIVE_H"+str(h))


@pytest.mark.parametrize("h",[3,5,10,20])
def test_native_horizon_endpoint_no_scaling(h):
    f=plan(h)
    assert f.execution_date.eq(calendar()[1]).all()
    assert f.label_end_date.eq(calendar()[h+1]).all()
    assert f.label_mature_date.eq(calendar()[h+1]).all()
    assert f.mechanism_observation_available_at.eq(calendar()[h+1]+pd.Timedelta(hours=16)).all()
    assert f.mechanism_coordinate_supported.all()
    assert not f.strict_endpoint_source_qualified.any()
    assert not f.historical_available_at_bound.any()


def test_sid_changed_then_back_is_blocked():
    p=prediction(days=35)
    p.loc[(p.ticker=="A") & p.signal_date.eq(calendar()[3]),"security_id"]="OTHER"
    f=plan(projection=p)
    assert not f.loc[f.ticker=="A","mechanism_coordinate_supported"].item()
    assert f.loc[f.ticker=="B","mechanism_coordinate_supported"].item()


def test_unknown_endpoint_sid_is_blocked():
    p=prediction(days=35)
    p.loc[(p.ticker=="A") & p.signal_date.eq(calendar()[1]),"security_id"]=None
    assert not plan(projection=p).loc[lambda f:f.ticker=="A","mechanism_coordinate_supported"].item()


def test_event_quantity_once_and_unsupported_fail_closed():
    events=[{"ticker":"A","date":calendar()[3],"supported":True,"quantity":2},
            {"ticker":"B","date":calendar()[3],"supported":False,"quantity":1}]
    f=plan(events=events)
    q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    q.loc[q.trade_date.eq(calendar()[6]),"open"]=6.
    y=m.native_labels(f,q)
    assert y.loc[y.ticker=="A","label_value"].item()==pytest.approx(.2)
    assert not y.loc[y.ticker=="B","label_qualified"].item()
    assert np.isnan(y.loc[y.ticker=="B","label_value"].item())


@pytest.mark.parametrize("bad",[0.,-1.,np.nan,np.inf])
def test_nonfinite_or_nonpositive_raw_open(bad):
    f=plan()
    q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    q.loc[(q.trade_date==calendar()[1]) & (q.ticker=="A"),"open"]=bad
    assert not m.native_labels(f,q).loc[lambda z:z.ticker=="A","label_qualified"].item()


def test_parent5_exact_y_maturity_sid_retained():
    f=plan();q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    parent=f[["signal_date","ticker","security_id"]].copy()
    parent["label_available"]=True;parent["y_open5"]=[.123,.456];parent["label_mature_date"]=calendar()[7]
    y=m.native_labels(f,q,parent5=parent)
    np.testing.assert_array_equal(y.label_value,parent.y_open5)
    assert y.label_mature_date.eq(calendar()[7]).all()
    assert y.parent_valid5d_exact_reuse.all()
    assert not y.strict_endpoint_source_qualified.any()
    parent.loc[0,"security_id"]="OTHER"
    with pytest.raises(ValueError,match="SID_CHANGED"):m.native_labels(f,q,parent5=parent)


def test_mean_all_horizon_identity_and_max_maturity():
    packets={h:labels(prediction(days=1)) for h in m.HORIZONS}
    for h,f in packets.items():f.label_value=h/100;f.label_mature_date=calendar()[h+1]
    y=m.mean_labels(packets)
    assert y.label_value.eq(.095).all()
    assert y.label_mature_date.eq(calendar()[21]).all()
    packets[3].loc[0,"label_qualified"]=False
    assert not m.mean_labels(packets).loc[0,"label_qualified"]
    with pytest.raises(ValueError):m.mean_labels({5:packets[5]})


def test_proxy_state_label_free_sid_cut_and_no_pair_mining(monkeypatch):
    from scripts.research.a2.training import stateful_decision
    monkeypatch.setattr(stateful_decision,"build_samples",lambda *a,**k:pytest.fail("pair mining forbidden"))
    p=prediction();p.loc[(p.ticker=="A") & p.signal_date.ge(calendar()[5]),"security_id"]="NEW_A"
    state=m.proxy_state(p,calendar())
    a=state.loc[state.ticker=="A"]
    assert a.loc[a.signal_date==calendar()[1],"cohort_age_sessions"].item()==0
    assert not a.signal_date.ge(calendar()[5]).any()
    assert state.state_role.eq("EXOGENOUS_COHORT_NOT_ACCOUNT").all()


def test_fixed_pair_order_no_missing_partner_replacement():
    p=prediction(names=("A","B","C"));p.loc[p.ticker=="B","new_buy_eligible"]=p.signal_date.eq(calendar()[2])
    state=m.proxy_state(p,calendar())
    lab=labels(p);lab.loc[(lab.ticker=="C") & lab.signal_date.eq(calendar()[2]),"label_qualified"]=False
    fixed=m.frozen_pairs(pair_frame())
    out=m.attach_pair_labels(fixed,state,lab)
    assert out.pair_id.tolist()==["PAIR_A","PAIR_C"]
    assert out.pre_label_group_weight.tolist()==[.5,.5]
    assert out.supported_training_group_weight.tolist()==[1.,0.]
    assert len(out)==2


@pytest.mark.parametrize("mutation",["count","weight","duplicate","hash"])
def test_frozen_pair_contract_failures(mutation):
    f=pair_frame();sha=m.PAIR_SHA
    if mutation=="count":f.loc[0,"pair_count_before_labels"]=1
    if mutation=="weight":f.loc[0,"pre_label_group_weight"]=1
    if mutation=="duplicate":f.loc[1,"pair_id"]=f.loc[0,"pair_id"]
    if mutation=="hash":sha="0"*64
    with pytest.raises(ValueError):m.frozen_pairs(f,actual_sha256=sha)


def test_complete20_only_gross_no_partial_mean():
    p=prediction(names=tuple(str(j) for j in range(20)),days=1);lab=labels(p)
    good=m.full20_baskets(p,lab)
    assert good.label_qualified.item();assert good.basket_y.item()==pytest.approx(.05)
    lab.loc[0,"label_qualified"]=False
    bad=m.full20_baskets(p,lab)
    assert not bad.label_qualified.item();assert np.isnan(bad.basket_y.item())
    assert m.full20_baskets(p.iloc[:-1],lab).empty


def test_full_legal_rows_no12000cap_signal_and_maturity_strict():
    n=13001
    f=pd.DataFrame({"signal_date":[pd.Timestamp("2023-03-01")]*n,
                    "label_mature_date":[pd.Timestamp("2023-03-08")]*n,"label_qualified":True,"target":.01})
    assert len(m.legal_rows(f,"2024-01-01"))==n
    f.loc[0,"label_mature_date"]=pd.Timestamp("2024-01-01")
    f.loc[1,"signal_date"]=pd.Timestamp("2024-01-01")
    f.loc[2,"label_mature_date"]=pd.NaT
    f.loc[3,"label_qualified"]=False
    assert len(m.legal_rows(f,"2024-01-01"))==n-4
    f.loc[4,"label_mature_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="2026_LOCKED"):m.legal_rows(f,"2024-01-01")


def test_date_equal_weights_do_not_depend_on_target():
    f=pd.DataFrame({"signal_date":[calendar()[0],calendar()[0],calendar()[1]],"target":[-100,.01,7.]})
    assert m.date_equal_weights(f).tolist()==[.5,.5,1.]
    f.target=-f.target
    assert m.date_equal_weights(f).tolist()==[.5,.5,1.]


def test_hazard_unknown_and_unmatured_prior_censor():
    f=pd.DataFrame([{"signal_date":calendar()[a+1],"ticker":"A","cohort_id":"COHORT",
                     "cohort_age_sessions":a,"label_value":.1,"label_qualified":True,
                     "label_mature_date":calendar()[a+6]} for a in (0,7,14)])
    assert len(m.hazard_probes(f,calendar(),ages=(0,7,14),stride=7))==3
    f.loc[0,"label_qualified"]=False
    h=m.hazard_probes(f,calendar(),ages=(0,7,14),stride=7)
    assert len(h)==1 and h.right_censored_unknown.item()
    f.loc[0,"label_qualified"]=True;f.loc[0,"label_mature_date"]=calendar()[8]
    assert len(m.hazard_probes(f,calendar(),ages=(0,7,14),stride=7))==1


@pytest.mark.parametrize("length",[5,10,20])
def test_same_sid_past_sequence_no_future(length):
    p=prediction(days=35);key=p.loc[(p.signal_date==calendar()[22]) & (p.ticker=="A")]
    out=m.sequence_blocks(p,key,calendar(),length,["ret_1d","raw_a2_rank"])
    assert out.window_complete.item()
    assert pd.Timestamp(out.dates[0,-1])==calendar()[22]
    assert pd.Timestamp(out.dates[0,0])==calendar()[23-length]
    p.loc[(p.ticker=="A") & (p.signal_date==calendar()[21]),"security_id"]="OTHER"
    out=m.sequence_blocks(p,key,calendar(),length,["ret_1d"])
    assert not out.window_complete.item()
    assert np.isnan(out.values[0,-2]).all()


def test_sequence_left_padding_and_2026_reject():
    p=prediction(days=3);out=m.sequence_blocks(p,p.iloc[:1],calendar(),5,["ret_1d"])
    assert np.isnat(out.dates[0,:4]).all() and not out.window_complete.item()
    p.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):m.sequence_blocks(p,p.iloc[:1],calendar(),5,["ret_1d"])


def test_guard_footer_precedes_any_body_read(tmp_path,monkeypatch):
    f=tmp_path/"source.parquet";pd.DataFrame({"signal_date":[pd.Timestamp("2026-01-01")],"secret_y":[123.]}).to_parquet(f)
    monkeypatch.setattr(pd,"read_parquet",lambda *a,**k:pytest.fail("body read"))
    with pytest.raises(ValueError,match="SOURCE_NOT_PHYSICALLY_PRE2026"):
        m.guard_sources({"fixture":{"path":str(f),"sha256":m.digest_file(f),"date":"signal_date"}})


def test_reader_never_constructed_without_permit():
    with pytest.raises(ValueError,match="READ_PERMIT_REQUIRED"):
        m.MechanismReader(None,{},calendar(),prediction(),prediction())


def permit_files(tmp_path, **changes):
    d=tmp_path/"design.json";a=tmp_path/"auth.json"
    d.write_text(json.dumps({"scientific_identity":m.IDENTITY}),encoding="utf-8")
    record={"scientific_identity":m.IDENTITY,"frozen_design_sha256":m.digest_file(d),
            "real_numeric_read_authorized":True,"2026_locked":True,"cutoff_exclusive":"2026-01-01",
            "source_hashes":{"synthetic":"a"*64},**{k:False for k in m.FALSE_AUTHORITY}}
    record.update(changes);a.write_text(json.dumps(record),encoding="utf-8")
    return d,a


@pytest.mark.parametrize("flag",m.FALSE_AUTHORITY)
@pytest.mark.parametrize("bad",[True,None])
def test_no_source_promotion_from_permit(tmp_path,flag,bad):
    d,a=permit_files(tmp_path,**{flag:bad})
    with pytest.raises(ValueError,match="PROMOTION_FORBIDDEN"):
        m.ReadPermit.from_files(d,m.digest_file(d),a,m.digest_file(a))


@pytest.mark.parametrize("bad",[False,None])
def test_numeric_read_authorization_literal_true(tmp_path,bad):
    d,a=permit_files(tmp_path,real_numeric_read_authorized=bad)
    with pytest.raises(ValueError,match="NOT_AUTHORIZED"):
        m.ReadPermit.from_files(d,m.digest_file(d),a,m.digest_file(a))


def test_readonly_existing_vector_binding_uses_temp_fixture_only(tmp_path,monkeypatch):
    source=tmp_path/"synthetic_vectors.parquet"
    frame=pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02"),pd.Timestamp("2024-01-03")],
                        "ticker":["FIXTURE","FIXTURE"],"fixture_number":[1.,2.]})
    frame.to_parquet(source)
    sources={"synthetic":{"path":str(source),"sha256":m.digest_file(source),"date":"signal_date"}}
    d,a=permit_files(tmp_path,source_hashes={"synthetic":sources["synthetic"]["sha256"]})
    permit=m.ReadPermit.from_files(d,m.digest_file(d),a,m.digest_file(a))
    monkeypatch.setattr(m.owner,"prepare_inputs",lambda *a,**k:pytest.fail("old run mutation"))
    reader=m.MechanismReader(permit,sources,calendar(),prediction(),prediction())
    got=reader.read("synthetic",["signal_date","ticker","fixture_number"],[("signal_date","<",pd.Timestamp("2024-01-03"))])
    assert got.fixture_number.tolist()==[1.]
    assert m.digest_file(source)==sources["synthetic"]["sha256"]
    a.write_text(a.read_text()+" ",encoding="utf-8")
    with pytest.raises(ValueError,match="AUTH_CHANGED"):
        reader.read("synthetic",["signal_date"],[("signal_date","<",pd.Timestamp("2024-01-03"))])


def test_endpoint_plan_late_window_nat_never_future_read():
    p=prediction(days=35);q=p[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"})
    key=p.loc[p.signal_date.eq(calendar()[34]),["signal_date","ticker","security_id"]]
    f=m.native_endpoint_plan(key,calendar(),20,p,q,[],window,"SYNTHETIC_LATE")
    assert f.label_end_date.isna().all()
    assert not f.mechanism_coordinate_supported.any()
    q["open"]=10.;out=m.native_labels(f,q)
    assert not out.label_qualified.any()
    assert m.legal_rows(out,"2026-01-01",target="label_value").empty


def test_gross_nonfinite_feature_blocks_whole_basket():
    p=prediction(names=tuple(str(j) for j in range(20)),days=1);lab=labels(p)
    p.loc[0,"ret_1d"]=np.nan
    assert m.full20_baskets(p,lab).empty


def test_native_shared_risk_mapping_has_local_coordinate_not_strict_authority():
    f=plan(3);q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    out=m.native_risk_observations(m.native_labels(f,q))
    assert out.horizon.eq(3).all() and out.return_value.eq(0).all()
    assert out.mechanism_coordinate_supported.all()
    assert not out.strict_endpoint_source_qualified.any()
    assert not out.historical_available_at_bound.any()
    assert (out.available_at>out.endpoint_at).all()
    assert out.identity_epoch.str.contains("FROZEN_SEGMENT").all()


def test_build_real_helper_entirely_synthetic_fixture_no_run_write(tmp_path,monkeypatch):
    names=tuple(chr(65+j) for j in range(20));pred=prediction(names=names,days=35)
    pred["is_max_group"]=pred.new_buy_eligible
    for c in ("input_present","stock_forecast_input_present","raw_selector_input_present","decision_information_present_union"):
        pred[c]=True
    pred["raw_top20_set_count"]=20;pred["active_13f_quarter"]="SYNTHETIC"
    pred["feature_source"]=m.owner.ALLOWED_SOURCES[0]
    train=pred.copy();train["label_available"]=True;train["account_event_unhandled"]=False
    train["label_mature_date"]=train.signal_date+pd.Timedelta(days=8);train["label_coordinate"]=m.owner.LABEL;train["y_open5"]=0.
    raw=pred[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});raw["open"]=10.
    extension=train[["signal_date","ticker","label_mature_date","label_available","y_open5"]].copy()
    extension["execution_date"]=extension.signal_date+pd.Timedelta(days=1)
    extension["label_end_date"]=extension.label_mature_date
    extension["label_unsupported_common_event"]=False;extension["label_quantity_multiplier"]=1.
    fixed=pair_frame();fixed["cohort_age_sessions"]=1;fixed["raw_rank"]=2
    specs={}
    frames={"prediction_feature_panel":pred,"value_training_panel":train,"raw_market_prices":raw,
            "calendar":pd.DataFrame({"trade_date":calendar()}),"five_day_extension":extension,"r8_pair_keys":fixed}
    for name,f in frames.items():
        path=tmp_path/(name+".parquet");f.to_parquet(path,index=False)
        specs[name]={"path":str(path),"sha256":m.digest_file(path),"rows":len(f),"date":"trade_date" if name in ("calendar","raw_market_prices") else "signal_date"}
    monkeypatch.setattr(m,"PAIR_SHA",specs["r8_pair_keys"]["sha256"])
    # The frozen_pairs default records its original identity; use the explicit
    # helper's checked source hash and a synthetic wrapper for this fixture.
    real_frozen=m.frozen_pairs
    monkeypatch.setattr(m,"frozen_pairs",lambda f,**kw:real_frozen(f,actual_sha256=m.PAIR_SHA))
    event=tmp_path/"events.json";event.write_text(json.dumps({"event_records":[]}),encoding="utf-8")
    code=tmp_path/"event_owner.py";code.write_text("import numpy as np\ndef apply_event_windows(frame, events):\n return np.ones(len(frame)),np.zeros(len(frame),bool),np.zeros(len(frame),int)\ndef run():\n raise RuntimeError('OLD_WRITER_FORBIDDEN')\n",encoding="utf-8")
    binding=tmp_path/"binding.json";binding.write_text("{}",encoding="utf-8")
    meta={k:{"path":str(path),"sha256":m.digest_file(path)} for k,path in (("event_binding",event),("event_window_owner",code),("parent_label_binding",binding))}
    manifest={"parquet_sources":specs,"metadata_pins":meta,"source_hashes":{k:v["sha256"] for k,v in {**specs,**meta}.items()}}
    monkeypatch.setattr(m,"r10_source_manifest",lambda:manifest)
    d,a=permit_files(tmp_path,source_hashes=manifest["source_hashes"])
    permit=m.ReadPermit.from_files(d,m.digest_file(d),a,m.digest_file(a))
    bundle=m.build_real_frames(permit,{"scientific_identity":m.IDENTITY})
    assert set(bundle.frames.labels)=={3,5,10,20,"MEAN"}
    assert bundle.metadata_coverage["pair_rows"]==2
    assert bundle.frames.heads[5]["REPLACE"].pair_id.tolist()==["PAIR_A","PAIR_C"]
    assert bundle.real_fit==bundle.real_account==0
    assert bundle.metadata_coverage["no_new_scientific_run_created"]


def test_shared_native_clocks_explicit_ny_and_parent_maturity_latest():
    f=plan(5);q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    packet=m.native_labels(f,q);packet.loc[0,"label_mature_date"]=calendar()[8]
    out=m.native_risk_observations(packet)
    assert str(out.origin_at.dt.tz)=="UTC"
    assert out.origin_at.dt.tz_convert("America/New_York").dt.hour.eq(16).all()
    local=out.entry_at.dt.tz_convert("America/New_York")
    assert local.dt.hour.eq(9).all() and local.dt.minute.eq(30).all()
    assert out.loc[0,"available_at"]==out.loc[0,"matured_at"]
    assert not out.aggregate_domain_bound.any()


def test_shared_native_domain_binding_preserves_provenance_and_unknown_epoch_fails():
    f=plan(3);q=prediction(days=35)[["signal_date","ticker"]].rename(columns={"signal_date":"trade_date"});q["open"]=10.
    packet=m.native_labels(f,q)
    epoch=dict(zip(packet.ticker,packet.identity_epoch));epoch["B"]="UNKNOWN_SEGMENT"
    out=m.native_risk_observations(packet,domain_epoch="DOMAIN_FIXED",composite_source_identity="SOURCE_COMPOSITE",asset_epochs=epoch)
    assert out.asset.tolist()==["A"]
    assert out.identity_epoch.eq("DOMAIN_FIXED").all()
    assert out.source_identity.eq("SOURCE_COMPOSITE").all()
    assert out.security_segment_epoch.str.contains("FROZEN_SEGMENT").all()
    assert out.original_label_identity.eq("SYNTHETIC_NATIVE_H3").all()
    with pytest.raises(ValueError,match="COMPLETE_NATIVE_RISK_DOMAIN"):
        m.native_risk_observations(packet,domain_epoch="DOMAIN_FIXED")


def gross_fixture():
    names=tuple(str(j) for j in range(20));sids=tuple("SID_"+t for t in names);d=calendar()[0]
    gross={h:pd.DataFrame([{"signal_date":d,"basket_members":names,"basket_sids":sids,"raw20_count":20,
                           "label_qualified":True,"basket_y":value,"label_mature_date":calendar()[h+1],
                           **{"mean_"+c:.01 for c in m.FEATURES}}]) for h,value in zip(m.HORIZONS,[-.1,.1,-.1,.1])}
    forecast=pd.DataFrame({"signal_date":[d]*20,"ticker":names,"security_id":sids,
                           "pointAdvantage":[-.1,.1]*10,"nativeSigma":.2})
    context=pd.DataFrame({"signal_date":[d],"risk_context_qualified":[True],"replacement_proxy":[.03],
                          "risk_vol":[.2],"risk_downside":[.1],"covariance_disagreement":[.02],"turnover_pressure":[.01]})
    return gross,forecast,context


def gross_build(gross,forecast,context,**kw):
    return m.gross_decision_frame(gross,forecast,context,risk_columns=("risk_vol","risk_downside","covariance_disagreement","turnover_pressure"),**kw)


def test_gross_25_fixed_grid_utility_mean_of_each_native_horizon_not_mean_y():
    g,f,c=gross_fixture();out=gross_build(g,f,c)
    assert len(out)==25 and out.sample_id.nunique()==25
    assert out.label_qualified.all() and out.information_supported.all()
    assert out.gross_previous_proxy.unique().tolist()==list(m.GROSS_GRID)
    assert out.gross_candidate.unique().tolist()==list(m.GROSS_GRID)
    chosen=out.loc[out.gross_previous_proxy.eq(.5)&out.gross_candidate.eq(.5)].iloc[0]
    assert chosen.target==pytest.approx(-.013)
    mean_y_utility=-.001*.5
    assert chosen.target!=pytest.approx(mean_y_utility)
    assert chosen.opportunity_breadth==.5
    assert chosen.average_positive_advantage==pytest.approx(.05)
    assert chosen.native_uncertainty_mean==pytest.approx(.2)
    assert chosen.label_mature_date==calendar()[21]
    assert out.attrs["all20_required"] and out.attrs["2026_locked"]
    assert "target" not in out.attrs["feature_columns"]


@pytest.mark.parametrize("missing",["horizon","label","maturity","partial_members","sid_difference"])
def test_gross_all4_all20_label_failure_no_surviving_basket(missing):
    g,f,c=gross_fixture()
    if missing=="horizon":g[10]=g[10].iloc[:0]
    elif missing=="label":g[10].loc[0,"label_qualified"]=False
    elif missing=="maturity":g[10].loc[0,"label_mature_date"]=pd.NaT
    elif missing=="partial_members":g[10].at[0,"basket_members"]=g[10].at[0,"basket_members"][:-1];g[10].loc[0,"raw20_count"]=19
    else:g[10].at[0,"basket_sids"]=("OTHER",)+g[10].at[0,"basket_sids"][1:]
    out=gross_build(g,f,c)
    assert len(out)==25 and not out.label_qualified.any()
    assert out.target.isna().all() and out.label_blocked_reason.notna().all()


@pytest.mark.parametrize("bad",["missing_stock","unknown_sid","sigma_nan","negative_sigma","missing_sigma_column","missing_context","context_unqualified","replacement_unknown"])
def test_gross_unknown_required_prediction_or_risk_context_date_blocked_not_drop(bad):
    g,f,c=gross_fixture()
    if bad=="missing_stock":f=f.iloc[:-1]
    elif bad=="unknown_sid":f.loc[0,"security_id"]="UNKNOWN"
    elif bad=="sigma_nan":f.loc[0,"nativeSigma"]=np.nan
    elif bad=="negative_sigma":f.loc[0,"nativeSigma"]=-1
    elif bad=="missing_sigma_column":f=f.drop(columns="nativeSigma")
    elif bad=="missing_context":c=c.iloc[:0]
    elif bad=="context_unqualified":c.loc[0,"risk_context_qualified"]=False
    else:c.loc[0,"replacement_proxy"]=np.nan
    out=gross_build(g,f,c)
    assert len(out)==25 and out.label_qualified.all()
    assert not out.information_supported.any()
    assert out.target.isna().all() and out.information_blocked_reason.notna().all()


def test_gross_all_horizon_rows_absent_preserves_explicit_scheduled_dates():
    g,f,c=gross_fixture();g={h:rows.iloc[:0] for h,rows in g.items()}
    out=gross_build(g,f,c,decision_dates=calendar()[:2])
    assert len(out)==50 and out.signal_date.nunique()==2
    assert not out.label_qualified.any() and out.target.isna().all()


def test_gross_source_or_future_schema_never_promotes():
    g,f,c=gross_fixture();out=gross_build(g,f,c)
    assert not out.account_state_qualified.any() and not out.source_account_authority_upgraded.any()
    f.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):gross_build(g,f,c)
