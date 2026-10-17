"""Synthetic R4 policy metadata/dispatch tests; no real source or outcomes."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import copy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_policy_execution_r4 as module
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash


def group_fixture(asof="2023-01-03T21:00:00+00:00",cutoff="2022-12-30T21:00:00+00:00"):
    return dict(as_of=asof,cutoff=cutoff,prior_date=pd.Timestamp(cutoff).date().isoformat(),
        block_reason=None,requested_assets=["A","B"],asset_uids={"A":"UA","B":"UB"},
        asset_epochs={"A":"EA","B":"EB"},segment_starts={"A":"2020-01-01","B":"2020-01-01"})


def pool_fixture():
    return dict(assets=("A","B"),asset_uids={"A":"UA","B":"UB"},
        asset_epochs={"A":"EA","B":"EB"},segment_starts={"A":"2020-01-01","B":"2020-01-01"},blocked_assets={})


@pytest.mark.parametrize("defect,reason",[("asset","DAILY_FULL_REQUESTED_POOL_CHANGED"),("uid","DAILY_SECURITY_UID_CHANGED"),
    ("epoch","DAILY_CONTIGUOUS_SECURITY_EPOCH_CHANGED"),("unknown","DAILY_CURRENT_UID_UNBOUND")])
def test_no_covariance_domain_expansion_or_silent_identity_transport(defect,reason):
    group,pool=group_fixture(),pool_fixture()
    before=copy.deepcopy(group)
    if defect=="asset":pool["assets"]+=("NEW",);pool["asset_uids"]["NEW"]="UN";pool["asset_epochs"]["NEW"]="EN"
    elif defect=="uid":pool["asset_uids"]["A"]="SWAP"
    elif defect=="epoch":pool["asset_epochs"]["A"]="NEW_EPOCH"
    else:pool["blocked_assets"]={"A":"UID_UNKNOWN"}
    result=module.compare_pool(group,pool,pd.Timestamp("2023-01-04T21:00:00+00:00"))
    assert result["block_reason"]==reason and result["status"]=="BLOCKED"
    assert result["extra_risk_refreshes"]==0 and result["covariance_modified"] is False
    assert group==before


def test_exact_pool_match_does_not_read_numeric_or_promote_source():
    class Poison:
        def __array__(self,*args):raise AssertionError("numeric accessed")
    pool=pool_fixture();pool["NAV"]=Poison();pool["returns"]=Poison();pool["covariance"]=Poison()
    result=module.compare_pool(group_fixture(),pool,"2023-01-03T21:00:00+00:00")
    assert result["status"]=="EXACT_DOMAIN_METADATA_MATCH" and result["numeric_reads"]==result["outcome_reads"]==0


@pytest.mark.parametrize("timestamp",["2023-01-02T21:00:00+00:00","2026-01-02T21:00:00+00:00","2023-01-03"])
def test_before_fit_future_or_unknown_clock_is_blocked(timestamp):
    with pytest.raises(module.PolicyInputBlocked):module.compare_pool(group_fixture(),pool_fixture(),timestamp)


def test_daily_reader_only_legal_metadata_incremental_before_body(monkeypatch):
    days,_=_calendar(pd.bdate_range("2022-12-29","2023-01-10"))
    calls=[]
    class Reader:
        def read(self,name,columns,**kwargs):
            assert not set(columns)&module.old.FORBIDDEN
            calls.append((name,columns,kwargs))
            if name=="raw_open_close":return pd.DataFrame(dict(ticker=["A","B"],trade_date=kwargs["day"]))
            return pd.DataFrame(dict(ticker=["A","B"],signal_date=pd.Timestamp(kwargs["stop"])-pd.Timedelta(days=1),
                security_id=["UA","UB"],feature_available=True,all_features_finite=True,feature_source="SOURCE"))
    seen=[]
    def current(features,raw,calendar,cutoff):
        seen.append((features.copy(),cutoff))
        assert pd.to_datetime(features.signal_date).max()==pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
        return pool_fixture()
    monkeypatch.setattr(module.old,"current_pool",current)
    provider=module.DailyMetadataPool(Reader(),days)
    provider("2023-01-03");provider("2023-01-05")
    assert calls[0][2]["start"] is None
    assert calls[2][2]["start"]==pd.Timestamp("2023-01-04")
    assert len(seen[-1][0])==4
    with pytest.raises(module.PolicyInputBlocked):provider("2023-01-04")
    with pytest.raises(module.PolicyInputBlocked):provider("2026-01-01")


def support_fixture():
    days,_=_calendar(pd.bdate_range("2022-01-01","2025-12-31"))
    groups=[group_fixture(s["as_of"],s["cutoff"]) for s in module.producer.quarterly_schedule(days)]
    nodes=[dict(method=m,as_of=g["as_of"],metadata_block_reason=None,numeric_check_eligible=True)
        for g in groups for m in module.producer.risk.METHODS]
    return days,groups,nodes


def test_first_input_failure_stops_quarter_preserves_all_quarters_methods():
    days,groups,nodes=support_fixture()
    calls=[]
    def pool(day):
        calls.append(day);result=pool_fixture();result["assets"]+=("NEW",);return result
    result=module.discover_carry(groups,nodes,days,pool)
    assert len(calls)==12 and len(result["quarters"])==12
    assert len(result["new_shr_paths"])==4
    assert all(q["checked_decision_days"]==1 and q["remaining_days_not_read_after_input_block"]>0 for q in result["quarters"])
    assert all(not p["full_carry_metadata_eligible"] and not p["economic_replay_eligible"] for p in result["new_shr_paths"])
    assert result["outcome_reads"]==result["numeric_reads"]==result["new_fit_units"]==result["account_attempts"]==0


def test_carry_metadata_match_still_cannot_activate_account():
    days,groups,nodes=support_fixture()
    result=module.discover_carry(groups,nodes,days,lambda day:pool_fixture())
    assert all(p["full_carry_metadata_eligible"] and not p["economic_replay_eligible"] for p in result["new_shr_paths"])
    assert all(q["methods"]["SHR_HP"]["forecast_execution_event_support"].startswith("PENDING") for q in result["quarters"])


def test_missing_duplicated_or_changed_risk_schedule_does_not_create_refresh():
    days,groups,nodes=support_fixture()
    nodes[-1]=nodes[0]
    with pytest.raises(module.PolicyInputBlocked,match="DUPLICATE"):module.discover_carry(groups,nodes,days,lambda d:pool_fixture())
    nodes[-1]=dict(method="SHR_ROBUST",as_of=groups[-1]["as_of"],metadata_block_reason=None)
    groups[-1]["as_of"]="2025-10-02T20:00:00+00:00"
    with pytest.raises(module.PolicyInputBlocked,match="SCHEDULE"):module.discover_carry(groups,nodes,days,lambda d:pool_fixture())


def test_unknown_group_uid_blocks_instead_of_deleting_asset():
    group=group_fixture();group["asset_uids"]["A"]=None
    with pytest.raises(module.PolicyInputBlocked,match="UNKNOWN_UID"):module.compare_pool(group,pool_fixture(),group["as_of"])


def test_anchor_account_freeze_transports_only_four_named_path_ids():
    kwargs=dict(research_id=module.ID,parent_research_id="R3",run_id="SYNTHETIC",registration_receipt_sha256="a"*64,
        input_sha256={},source_sha256={},identity_assumption="synthetic",anchor_path_id="R4_SHR_ANCHOR_SHR_HP")
    freeze=module.AnchorAccountFreeze(**kwargs)
    assert freeze.path_ids==("R4_SHR_ANCHOR_SHR_HP",) and freeze.one_way_friction_bps==10 and freeze.initial_cash_usd==3000
    kwargs["anchor_path_id"]="R0"
    with pytest.raises(module.PolicyInputBlocked):module.AnchorAccountFreeze(**kwargs).path_ids


def test_account_dispatch_never_enters_on_partial_or_forged_support(monkeypatch):
    called=[]
    monkeypatch.setattr(module.account.common,"run_continuous_account",lambda *a,**k:called.append(True))
    kwargs=dict(research_id=module.ID,parent_research_id="R3",run_id="SYNTHETIC",registration_receipt_sha256="a"*64,
        input_sha256={},source_sha256={},identity_assumption="synthetic",anchor_path_id="R4_SHR_ANCHOR_SHR_HP")
    freeze=module.AnchorAccountFreeze(**kwargs)
    support=dict(research_id=module.ID,path_id=freeze.path_ids[0],full_carry_metadata_eligible=True)
    contract=SimpleNamespace(source_authority_sha256="b"*64,matrix_sha256="c"*64)
    with pytest.raises(module.PolicyInputBlocked,match="ALL_ANCHOR"):
        module.run_anchor_account(None,None,None,event_inputs={},uncertified_quality_only=None,freeze=freeze,
            expected_freeze_sha256=freeze.digest(),contract=contract,input_provider=lambda *a:None,
            complete_support=support,expected_support_sha256=content_hash(support))
    assert called==[]



def test_pre2026_last_session_uses_intrinsic_bound_without_2026_stop(monkeypatch):
    days,_=_calendar(pd.bdate_range('2025-12-20','2025-12-31'))
    seen=[]
    class Reader:
        def read(self,name,columns,**kwargs):
            seen.append((name,columns,kwargs))
            if name=='raw_open_close':return pd.DataFrame({'ticker':['A'],'trade_date':[pd.Timestamp('2025-12-31')]})
            return pd.DataFrame({'ticker':['A'],'signal_date':[pd.Timestamp('2025-12-31')],
                'security_id':['UA'],'feature_available':[True],'all_features_finite':[True],'feature_source':['SOURCE']})
    monkeypatch.setattr(module.old,'current_pool',lambda *args:pool_fixture())
    module.DailyMetadataPool(Reader(),days)('2025-12-31')
    assert seen[0][2]['stop'] is None
    assert seen[1][2]['day']==pd.Timestamp('2025-12-31')


def test_existing_P0_binding_preserves_exclusive_and_matured_clocks_without_fit(monkeypatch):
    p0=dict(input_binding={'path':{'root':'B','relative':'INPUT.json'},'sha256':'a'*64},
        initial_freeze={'path':{'root':'B','relative':'FREEZE.json'},'sha256':'b'*64},artifact_records=[],initial_OOF=[])
    for year,matured in [(2023,'2022-12-30'),(2024,'2023-12-29'),(2025,'2024-12-31')]:
        for kind in ['five_day_HGB','five_day_calibration_HGB']:
            p0['artifact_records'].append(dict(kind=kind,cutoff=f'{year}-01-01',match=True,maturity_max=matured,
                path={'root':'B','relative':f'{kind}_{year}.joblib'},actual_sha256='c'*64))
        p0['initial_OOF'].append(dict(year=year,matches_receipt=True,signal_max=f'{year}-12-29',
            path={'root':'B','relative':f'OOF_{year}.parquet'},actual_sha256='d'*64,
            receipt_path={'root':'B','relative':f'OOF_{year}.json'},receipt_sha256='e'*64))
    monkeypatch.setattr(module.old,'read_json',lambda path:{'P0':p0,'roots':{'B':'D:/synthetic/B'}})
    monkeypatch.setattr(module.old,'_safe_source',lambda path:Path(path))
    pins=[]
    monkeypatch.setattr(module.old,'_pin',lambda path,digest,label:pins.append((str(path),digest)))
    monkeypatch.setattr(module,'_ref',lambda path:{'path':str(path),'sha256':'f'*64})
    binding=module.p0_binding_metadata(None,{'old_tuple_reference':{'path':'D:/synthetic/PARENT/FAMILY.json'}})
    assert len(pins)==14 and binding['model_deserializations']==binding['OOF_values_read']==binding['new_fit_units']==0
    first=binding['annual_clock_bindings']['2023']
    assert pd.Timestamp(first['exclusive_fit_cutoff'])==pd.Timestamp('2023-01-01T05:00:00+00:00')
    assert pd.Timestamp(first['latest_matured_observation'])==pd.Timestamp('2022-12-30T21:00:00+00:00')
    assert first['exclusive_fit_cutoff']!=first['latest_matured_observation']
