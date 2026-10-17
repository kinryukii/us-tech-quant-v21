"""Synthetic-only full RiskState/endpoint/PIT integration; never real readers."""
from dataclasses import replace
import copy
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.risk.shared_risk_engine_r2 import (
    SourceReceipt, EndpointPair, RiskInput, SharedRiskEngine, observations_from_endpoints,
    risk_state_contract, METHODS, COORDINATE, BENCHMARK_PROXY_COORDINATE,
)
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget


def synthetic_input(assets=6, *, horizons=(3, 5, 10, 20)):
    sessions = pd.bdate_range("2021-01-01", "2025-03-31", tz="UTC") + pd.Timedelta(hours=21)
    as_of = pd.Timestamp("2025-01-01T21:00:00Z")
    names = tuple("A"+str(i) for i in range(assets))
    receipt = SourceReceipt("SYNTHETIC_STOCK", "SYNTHETIC_V1", "a"*64,
                            pd.Timestamp("2020-01-01", tz="UTC"))
    qreceipt = replace(receipt, source_identity="SYNTHETIC_QQQ", source_sha256="b"*64)
    ireceipt = replace(receipt, source_identity="SYNTHETIC_FF48", source_sha256="c"*64)
    rng = np.random.default_rng(20260928)
    daily = rng.normal(.0002, .007, len(sessions))
    market = 100*np.exp(np.cumsum(daily))
    prices = np.column_stack([50*np.exp(np.cumsum(.5*daily+rng.normal(0,.009,len(sessions))))
                              for _ in names])
    last = sessions.get_indexer([pd.Timestamp("2024-11-29T21:00:00Z")])[0]
    origins = range(last-449, last+1)

    def records(symbols, data, hs, source):
        out = []
        for i in origins:
            for h in hs:
                for a, name in enumerate(symbols):
                    e = sessions[i+1].normalize()+pd.Timedelta(hours=14,minutes=30)
                    x = sessions[i+h+1].normalize()+pd.Timedelta(hours=14,minutes=30)
                    out.append(dict(asset=name,origin_at=sessions[i],entry_at=e,endpoint_at=x,
                                    matured_at=x+pd.Timedelta(minutes=1),
                                    available_at=x+pd.Timedelta(minutes=2),horizon=h,
                                    uid=name,identity_epoch="SYNTHETIC_EPOCH",
                                    source_identity=source.source_identity,
                                    return_value=float(data[i+h+1,a]/data[i+1,a]-1)))
        return pd.DataFrame(out)
    frame = records(names, prices, horizons, receipt)
    qframe = records(("QQQ",), market[:,None], (1,5), qreceipt)
    industry = pd.DataFrame(dict(asset=names,group=[1+i%2 for i in range(assets)],
                                 available_at=pd.Timestamp("2024-01-01",tz="UTC"),
                                 effective_at=pd.Timestamp("2023-01-01",tz="UTC"),
                                 identity_epoch="SYNTHETIC_EPOCH",
                                 source_identity="SYNTHETIC_FF48"))
    return RiskInput(names, sessions, frame, receipt, {a:a for a in names},
                     qqq_observations=qframe,qqq_receipt=qreceipt,
                     industry_mapping=industry,industry_receipt=ireceipt), as_of


@pytest.fixture(scope="module")
def synthetic():
    return synthetic_input()


@pytest.mark.parametrize("method", METHODS)
def test_all_directions_have_qualified_synthetic_contract_and_psd(synthetic, method):
    inputs, as_of = synthetic
    engine = SharedRiskEngine()
    state = engine.fit(method, inputs, as_of=as_of)
    assert state.status == "PASS_SYNTHETIC", state.notes
    assert state.assets == inputs.assets and state.horizon == 5
    assert state.cutoff < state.as_of < pd.Timestamp("2026-01-01",tz="UTC")
    assert state.source_identity == inputs.source_receipt.source_identity
    assert not state.source_receipt["quote_qualified"]
    assert not state.covariance.flags.writeable
    assert np.linalg.eigvalsh(state.covariance).min() >= -1e-10
    assert state.fit_dependency_ids
    assert engine.budget.snapshot()["authority"]=="SYNTHETIC_LOCAL_ACCOUNTING_ONLY"


@pytest.mark.parametrize("method", ["RD", "RM", "RU", "RE"])
def test_future_append_invariance_and_exact_reuse(synthetic, method):
    inputs, as_of = synthetic
    engine = SharedRiskEngine()
    first = engine.fit(method, inputs, as_of=as_of)
    prior = engine.budget.snapshot()["learned_total"]
    future = inputs.observations.iloc[:1].copy()
    for field in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):
        future[field] = future[field]+pd.Timedelta(days=2000)
    future["return_value"] = 1e100
    appended = replace(inputs,observations=pd.concat([inputs.observations,future],ignore_index=True))
    second = engine.fit(method, appended, as_of=as_of)
    assert first.status==second.status=="PASS_SYNTHETIC",second.notes
    assert first.risk_state_id == second.risk_state_id
    np.testing.assert_array_equal(first.covariance,second.covariance)
    assert engine.budget.snapshot()["learned_total"]==prior


@pytest.mark.parametrize("clock",["available_at","matured_at","endpoint_at"])
def test_same_day_future_not_fit_and_metadata_endpoint_guard(synthetic,clock):
    inputs,as_of=synthetic
    frame=inputs.observations.copy()
    frame.loc[frame.horizon.eq(5),clock]=as_of
    result=SharedRiskEngine().fit("RD",replace(inputs,observations=frame),as_of=as_of)
    assert result.status=="BLOCKED"


def test_no_2026_asof_or_real_fit(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    real=replace(inputs,source_receipt=replace(inputs.source_receipt,synthetic=False,
                                             quote_qualified=True,historical_authority_status="QUALIFIED"))
    assert engine.fit("RD",real,as_of=as_of).status=="BLOCKED"
    assert engine.fit("RD",inputs,as_of=pd.Timestamp("2026-01-01",tz="UTC")).status=="BLOCKED"
    assert engine.budget.learned_total==0


@pytest.mark.parametrize("kind",["empty","short","asset_short"])
def test_history_missing_blocks_no_subset_fallback(synthetic,kind):
    inputs,as_of=synthetic
    frame=inputs.observations
    if kind=="empty":frame=frame.iloc[:0]
    elif kind=="short":frame=frame[frame.origin_at.isin(sorted(frame.origin_at.unique())[-29:])]
    else:frame=frame[(frame.asset!="A0")|(frame.origin_at.isin(sorted(frame.origin_at.unique())[-29:]))]
    engine=SharedRiskEngine()
    state=engine.fit("RD",replace(inputs,observations=frame),as_of=as_of)
    assert state.status=="BLOCKED"
    assert "A0" in state.blocked_assets
    assert engine.budget.learned_total==0


@pytest.mark.parametrize("field,value",[("uid","SWAPPED"),("identity_epoch","OTHER_EPOCH"),("source_identity","OTHER_SOURCE")])
def test_source_and_security_swaps_block(synthetic,field,value):
    inputs,as_of=synthetic
    frame=inputs.observations.copy()
    frame.loc[frame.horizon.eq(5),field]=value
    engine=SharedRiskEngine()
    assert engine.fit("RD",replace(inputs,observations=frame),as_of=as_of).status=="BLOCKED"
    assert engine.budget.learned_total==0


def test_source_version_change_cannot_exact_reuse(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    a=engine.fit("RD",inputs,as_of=as_of)
    before=engine.budget.learned_total
    changed=replace(inputs,source_receipt=replace(inputs.source_receipt,source_version="SYNTHETIC_V2",source_sha256="d"*64))
    b=engine.fit("RD",changed,as_of=as_of)
    assert a.status==b.status=="PASS_SYNTHETIC"
    assert a.risk_state_id!=b.risk_state_id
    assert engine.budget.learned_total>before


def test_duplicates_block_before_fit(synthetic):
    inputs,as_of=synthetic
    frame=pd.concat([inputs.observations,inputs.observations[inputs.observations.horizon.eq(5)].iloc[:1]],ignore_index=True)
    engine=SharedRiskEngine()
    state=engine.fit("RD",replace(inputs,observations=frame),as_of=as_of)
    assert state.status=="BLOCKED"
    assert engine.budget.learned_total==0


def test_offschedule_is_blocked_and_cutoff_is_prior_session(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    assert engine.fit("RD",inputs,as_of=as_of+pd.Timedelta(days=1)).status=="BLOCKED"
    state=engine.fit("RD",inputs,as_of=as_of)
    i=inputs.sessions.get_indexer([as_of])[0]
    assert state.cutoff==inputs.sessions[i-1]


def test_rm_true_horizons_and_common_support(synthetic):
    inputs,as_of=synthetic
    state=SharedRiskEngine().fit("RM",inputs,as_of=as_of)
    assert state.status=="PASS_SYNTHETIC"
    assert tuple(state.notes["horizon_state"]["horizons"])==(3,5,10,20)
    engine=SharedRiskEngine()
    frame=inputs.observations[inputs.observations.horizon.ne(20)]
    assert engine.fit("RM",replace(inputs,observations=frame),as_of=as_of).status=="BLOCKED"
    wrong=inputs.observations.copy()
    wrong.loc[wrong.horizon.eq(3),"horizon"]=20
    assert engine.fit("RM",replace(inputs,observations=wrong),as_of=as_of).status=="BLOCKED"


@pytest.mark.parametrize("method",["RB","RH","RR","RE"])
def test_qqq_missing_blocks_no_cross_section_substitute(synthetic,method):
    inputs,as_of=synthetic
    assert SharedRiskEngine().fit(method,replace(inputs,qqq_receipt=None),as_of=as_of).status=="BLOCKED"


def test_industry_unavailable_or_future_mapping_blocks(synthetic):
    inputs,as_of=synthetic
    assert SharedRiskEngine().fit("RH",replace(inputs,industry_receipt=None),as_of=as_of).status=="BLOCKED"
    frame=inputs.industry_mapping.copy()
    frame.loc[0,"effective_at"]=as_of+pd.Timedelta(days=1)
    assert SharedRiskEngine().fit("RH",replace(inputs,industry_mapping=frame),as_of=as_of).status=="BLOCKED"


def test_ru_four_physical_subfits_counted_no_retry(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    state=engine.fit("RU",inputs,as_of=as_of)
    assert state.status=="PASS_SYNTHETIC"
    snap=engine.budget.snapshot()
    assert snap["counts"]["jackknife_subfit"]==4
    assert snap["counts"]["scaler"]==5
    assert state.estimation_uncertainty["sigma_jackknife"].shape==(4,len(inputs.assets))
    before=snap["learned_total"]
    assert engine.fit("RU",inputs,as_of=as_of).risk_state_id==state.risk_state_id
    assert engine.budget.learned_total==before


def test_jackknife_failure_no_refund_no_retry(synthetic,monkeypatch):
    inputs,as_of=synthetic
    import scripts.research.a2.risk.shared_risk_engine_r2 as module
    original=module._estimate
    calls=[]
    def fail(method,prepared,index,*args):
        calls.append(len(index))
        if len(index)<252:raise ValueError("SYNTHETIC_JACKKNIFE_FAILURE")
        return original(method,prepared,index,*args)
    monkeypatch.setattr(module,"_estimate",fail)
    engine=SharedRiskEngine()
    state=engine.fit("RU",inputs,as_of=as_of)
    assert state.status=="BLOCKED"
    count=engine.budget.learned_total
    assert engine.budget.snapshot()["counts"]["jackknife_subfit"]==1
    engine.fit("RU",inputs,as_of=as_of)
    assert engine.budget.learned_total==count
    assert calls==[252,189]


def test_re_missing_member_never_three_member_renormalization(synthetic,monkeypatch):
    inputs,as_of=synthetic
    original=SharedRiskEngine._primitive
    def missing(cache,method,frame,**kwargs):
        if method=="OAS":raise ValueError("OAS_REQUIRED_MEMBER_MISSING")
        return original(cache,method,frame,**kwargs)
    monkeypatch.setattr(SharedRiskEngine,"_primitive",staticmethod(missing))
    state=SharedRiskEngine().fit("RE",inputs,as_of=as_of)
    assert state.status=="BLOCKED"
    assert state.model_disagreement is None


def test_true_endpoint_builder_maturity_and_no_rename(synthetic):
    inputs,as_of=synthetic
    frame=inputs.observations
    rows=[]
    for h in (3,5,10,20):
        r=frame[frame.horizon.eq(h)].iloc[-1]
        rows.append(EndpointPair(r.asset,r.origin_at,r.entry_at,r.endpoint_at,100,
                                 100*(1+r.return_value),r.matured_at,r.available_at,h,
                                 r.uid,r.identity_epoch,r.source_identity,True,"SYNTHETIC_CA_RECEIPT"))
    out=observations_from_endpoints(rows,inputs.sessions)
    assert tuple(out.horizon)==(3,5,10,20)
    assert len(set(out.return_value))==4
    with pytest.raises(ValueError,match="HORIZON"):
        observations_from_endpoints([replace(rows[0],horizon=20)],inputs.sessions)
    with pytest.raises(ValueError,match="AUTHORITY"):
        observations_from_endpoints([replace(rows[0],shareholder_coordinate_qualified=False)],inputs.sessions)
    with pytest.raises(ValueError,match="PRE2026"):
        observations_from_endpoints([replace(rows[0],available_at=pd.Timestamp("2026-01-01",tz="UTC"))],inputs.sessions)


def test_ill_conditioning_and_determinism(synthetic):
    inputs,as_of=synthetic
    a=SharedRiskEngine().fit("RD",inputs,as_of=as_of)
    b=SharedRiskEngine().fit("RD",inputs,as_of=as_of)
    assert a.risk_state_id==b.risk_state_id
    np.testing.assert_array_equal(a.covariance,b.covariance)
    raw=inputs.observations.copy()
    raw["return_value"]=0.
    result=SharedRiskEngine().fit("RD",replace(inputs,observations=raw),as_of=as_of)
    assert result.status=="BLOCKED"
    assert "ILL_CONDITIONED" in result.notes["block_reason"]


def test_contract_no_ninth_direction():
    contract=risk_state_contract()
    assert len(contract["incremental_directions"])==8
    assert len(contract["fields"])>=22
    assert "risk time-scale approximation" not in contract["RM"] or "approximation" in contract["RM"]


def test_exact_fitclosure_does_not_mix_other_direction(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    unrelated=engine.fit("RH",inputs,as_of=as_of)
    rd=engine.fit("RD",inputs,as_of=as_of)
    event={e["key"]:e for e in engine.budget.events}
    assert unrelated.status==rd.status=="PASS_SYNTHETIC"
    assert not any("qqq" in event[k]["name"] or "ff48" in event[k]["name"] for k in rd.fit_dependency_ids)
    assert len(rd.fit_dependency_ids)<len(engine.budget.events)
    assert engine.fit("RD",inputs,as_of=as_of).risk_state_id==rd.risk_state_id


def test_qqq_vintage_mutation_is_fullstate_identity_change(synthetic):
    inputs,as_of=synthetic
    engine=SharedRiskEngine()
    first=engine.fit("RE",inputs,as_of=as_of)
    before=engine.budget.learned_total
    changed=replace(inputs,qqq_receipt=replace(inputs.qqq_receipt,source_version="SYNTHETIC_QQQ_V2",source_sha256="e"*64))
    second=engine.fit("RE",changed,as_of=as_of)
    assert first.status==second.status=="PASS_SYNTHETIC"
    np.testing.assert_allclose(first.covariance,second.covariance)
    assert first.risk_state_id!=second.risk_state_id
    assert engine.budget.learned_total>before


def test_standard_jackknife_se_and_separate_re_disagreement(synthetic):
    inputs,as_of=synthetic
    ru=SharedRiskEngine().fit("RU",inputs,as_of=as_of)
    sj=ru.estimation_uncertainty["sigma_jackknife"]
    expected=np.sqrt(3/4*((sj-sj.mean(axis=0))**2).sum(axis=0))
    np.testing.assert_allclose(ru.estimation_uncertainty["marginal_sigma_uncertainty"],expected)
    re=SharedRiskEngine().fit("RE",inputs,as_of=as_of)
    assert re.status=="PASS_SYNTHETIC"
    assert len(re.model_disagreement["members"])==4
    assert re.notes["no_unknown_asset_fallback"]


def test_duplicate_legal_session_date_is_blocked(synthetic):
    inputs,as_of=synthetic
    extra=inputs.sessions[50]-pd.Timedelta(hours=1)
    sessions=inputs.sessions.insert(50,extra)
    engine=SharedRiskEngine()
    assert engine.fit("RD",replace(inputs,sessions=sessions),as_of=as_of).status=="BLOCKED"
    assert engine.budget.learned_total==0


@pytest.mark.parametrize("field", ["identity_epoch", "available_at"])
def test_qqq_epoch_or_availability_invalidates_learned_factor_reuse(synthetic, field):
    inputs, as_of = synthetic
    engine = SharedRiskEngine()
    first = engine.fit("RB", inputs, as_of=as_of)
    before = engine.budget.learned_total
    observations = inputs.qqq_observations.copy()
    if field == "identity_epoch":
        receipt = replace(inputs.qqq_receipt, identity_epoch="SYNTHETIC_QQQ_EPOCH_V2")
        observations["identity_epoch"] = receipt.identity_epoch
    else:
        receipt = replace(inputs.qqq_receipt, available_at=pd.Timestamp("2020-02-01", tz="UTC"))
    changed = replace(inputs, qqq_receipt=receipt, qqq_observations=observations)
    second = engine.fit("RB", changed, as_of=as_of)
    assert first.status == second.status == "PASS_SYNTHETIC"
    assert first.risk_state_id != second.risk_state_id
    assert engine.budget.learned_total > before
    np.testing.assert_allclose(first.covariance, second.covariance)
    stock_means = [e for e in engine.budget.events if e["name"] == "stock_observed_mean"]
    assert len(stock_means) == 1  # Stock-only preparation still reuses exactly.


def mechanism_input(synthetic):
    """Exercise real-mode envelopes with generated numbers, never a real source reader."""
    inputs, as_of = synthetic
    fields = dict(synthetic=False, mechanism=True,
                  status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
                  scientific_contract_identity="SYNTHETIC_MECHANISM_CONTRACT",
                  scientific_contract_sha256="d"*64,
                  actual_snapshot_timestamp=pd.Timestamp("2026-10-03T06:00:00Z"),
                  observation_time_assumed=True,
                  strict_PIT_promotion_eligible=False, quote_qualified=False,
                  historical_authority_status="UNKNOWN")
    primary = replace(inputs.source_receipt, **fields)
    benchmark = replace(inputs.qqq_receipt, **fields,
                        return_coordinate=BENCHMARK_PROXY_COORDINATE,
                        benchmark_proxy_allowed=True)
    industry = replace(inputs.industry_receipt, **fields)
    return replace(inputs, source_receipt=primary, qqq_receipt=benchmark,
                   industry_receipt=industry), as_of


def test_mechanism_source_keeps_snapshot_separate_from_assumed_observation(synthetic):
    inputs, as_of = mechanism_input(synthetic)
    receipt = inputs.source_receipt
    receipt.validate(as_of)
    assert receipt.actual_snapshot_timestamp >= pd.Timestamp("2026-01-01", tz="UTC")
    assert receipt.available_at < as_of
    assert receipt.cache_identity()["execution_semantics"]["actual_snapshot_timestamp"].startswith("2026-")
    assert receipt.observation_time_assumed and not receipt.quote_qualified
    assert receipt.historical_authority_status == "UNKNOWN"
    assert not receipt.strict_PIT_promotion_eligible


@pytest.mark.parametrize("field,value,reason", [
    ("synthetic", True, "EXECUTION_MODE"),
    ("mechanism", False, "EXECUTION_MODE"),
    ("status", "QUALIFIED_REAL", "SOURCE_BINDING"),
    ("quote_qualified", True, "HISTORICAL_AUTHORITY"),
    ("historical_authority_status", "QUALIFIED", "HISTORICAL_AUTHORITY"),
    ("strict_PIT_promotion_eligible", True, "HISTORICAL_AUTHORITY"),
    ("scientific_contract_identity", "", "SCIENTIFIC_CONTRACT"),
    ("scientific_contract_sha256", "BAD", "SCIENTIFIC_CONTRACT"),
    ("observation_time_assumed", False, "ASSUMED_OBSERVATION"),
    ("actual_snapshot_timestamp", None, "SNAPSHOT_TIMESTAMP"),
    ("actual_snapshot_timestamp", pd.Timestamp("2026-10-03"), "TIMEZONE"),
    ("available_at", pd.Timestamp("2026-10-03T06:00:00Z"), "AVAILABILITY"),
    ("return_coordinate", BENCHMARK_PROXY_COORDINATE, "COORDINATE"),
])
def test_mechanism_unbound_or_promoted_receipt_blocks_before_fit(synthetic, field, value, reason):
    inputs, as_of = mechanism_input(synthetic)
    inputs = replace(inputs, source_receipt=replace(inputs.source_receipt, **{field: value}))
    reserved = []
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=reserved.append))
    result = engine.fit("RD", inputs, as_of=as_of)
    assert result.status == "BLOCKED"
    assert reason in result.notes["block_reason"]
    assert engine.budget.learned_total == 0 and not reserved


def test_mechanism_requires_lifecycle_callback_and_records_true_mode(synthetic):
    inputs, as_of = mechanism_input(synthetic)
    blocked_engine = SharedRiskEngine()
    assert blocked_engine.fit("RD", inputs, as_of=as_of).status == "BLOCKED"
    assert blocked_engine.budget.learned_total == 0
    reserved = []
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=reserved.append))
    result = engine.fit("RD", inputs, as_of=as_of)
    assert result.status == "PASS_FROZEN_HISTORY_MECHANISM", result.notes
    assert reserved and all(e["mechanism"] and not e["synthetic"] for e in reserved)
    assert result.return_coordinate == COORDINATE
    assert result.source_receipt["actual_snapshot_timestamp"] == inputs.source_receipt.actual_snapshot_timestamp
    assert result.notes["real_fit"] == result.notes["mechanism_fit"] == 1
    assert result.notes["synthetic_fit"] == 0
    assert not result.notes["strict_PIT_promotion_eligible"]
    assert engine.budget.snapshot()["authority"] == "EXISTING_LIFECYCLE_MECHANISM_RESERVATIONS"
    before = engine.budget.learned_total
    repeated = engine.fit("RD", inputs, as_of=as_of)
    assert repeated.risk_state_id == result.risk_state_id
    assert engine.budget.learned_total == before


def test_mechanism_open_proxy_benchmark_requires_same_frozen_contract(synthetic):
    inputs, as_of = mechanism_input(synthetic)
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=lambda event: None))
    result = engine.fit("RB", inputs, as_of=as_of)
    assert result.status == "PASS_FROZEN_HISTORY_MECHANISM", result.notes
    assert result.notes["dependent_source_receipts"]["QQQ"]["return_coordinate"] == BENCHMARK_PROXY_COORDINATE
    assert result.return_coordinate == COORDINATE
    assert "next-session Open" in result.notes["benchmark_clock"]


@pytest.mark.parametrize("change,reason", [
    ({"return_coordinate": "frozen_qfq_close_return_proxy"}, "COORDINATE"),
    ({"benchmark_proxy_allowed": False}, "COORDINATE"),
    ({"scientific_contract_sha256": "e"*64}, "CONTRACT_MISMATCH"),
    ({"scientific_contract_identity": "OTHER_CONTRACT"}, "CONTRACT_MISMATCH"),
    ({"synthetic": True, "mechanism": False, "status": "QUALIFIED_SYNTHETIC",
      "return_coordinate": COORDINATE}, "EXECUTION_MODE_MISMATCH"),
])
def test_mechanism_benchmark_cannot_substitute_clock_or_contract(synthetic, change, reason):
    inputs, as_of = mechanism_input(synthetic)
    changed = replace(inputs, qqq_receipt=replace(inputs.qqq_receipt, **change))
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=lambda event: None))
    result = engine.fit("RB", changed, as_of=as_of)
    assert result.status == "BLOCKED" and reason in result.notes["block_reason"]
    assert engine.budget.learned_total == 0


def test_mechanism_proxy_still_requires_next_open_horizon_metadata(synthetic):
    inputs, as_of = mechanism_input(synthetic)
    frame = inputs.qqq_observations.copy()
    frame["entry_at"] = frame["origin_at"]
    changed = replace(inputs, qqq_observations=frame)
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=lambda event: None))
    assert engine.fit("RB", changed, as_of=as_of).status == "BLOCKED"
    assert engine.budget.learned_total == 0


def test_mechanism_contract_name_is_audit_identity_not_numeric_refit(synthetic):
    inputs, as_of = mechanism_input(synthetic)
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=lambda event: None))
    first = engine.fit("RD", inputs, as_of=as_of)
    count = engine.budget.learned_total
    renamed = replace(inputs, source_receipt=replace(inputs.source_receipt,
                      scientific_contract_identity="SAME_SEMANTICS_OTHER_AUDIT_NAME"))
    second = engine.fit("RD", renamed, as_of=as_of)
    assert first.status == second.status == "PASS_FROZEN_HISTORY_MECHANISM"
    assert first.risk_state_id != second.risk_state_id
    assert first.fit_dependency_ids == second.fit_dependency_ids
    assert engine.budget.learned_total == count


@pytest.mark.parametrize("field,value", [
    ("scientific_contract_sha256", "e"*64),
    ("actual_snapshot_timestamp", pd.Timestamp("2026-10-03T07:00:00Z")),
])
def test_mechanism_semantics_or_snapshot_change_invalidates_physical_reuse(synthetic, field, value):
    inputs, as_of = mechanism_input(synthetic)
    engine = SharedRiskEngine(budget=StateBudget(reserve_callback=lambda event: None))
    first = engine.fit("RD", inputs, as_of=as_of)
    count = engine.budget.learned_total
    changed = replace(inputs, source_receipt=replace(inputs.source_receipt, **{field: value}))
    second = engine.fit("RD", changed, as_of=as_of)
    assert first.status == second.status == "PASS_FROZEN_HISTORY_MECHANISM"
    assert first.risk_state_id != second.risk_state_id
    assert engine.budget.learned_total > count
