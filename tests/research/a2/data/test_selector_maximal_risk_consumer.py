"""Synthetic-only C14 metadata contract tests; never touch B bank/data."""
import pytest
from scripts.research.a2.data import selector_maximal_risk_consumer as c
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity

def fixture():
    u={'assets':['A','B'],'asset_uids':{'A':'CUSIP:111111111','B':'CUSIP:222222222'},'asset_epochs':{'A':'e1','B':'e2'},'security_coordinate':'shareholder_H5','source_support_identity':{'source':'synthetic','sha':'a'*64}}
    sig=structural_identity(assets=tuple(u['assets']),uids=u['asset_uids'],epochs=u['asset_epochs'],security_coordinate=u['security_coordinate'],source_support_identity=u['source_support_identity'])
    r={**u,'status':'PASS_FROZEN_HISTORY_MECHANISM','strict_PIT_promotion_eligible':False,'family':'LW','recipe_sha256':'b'*64,'horizon_sessions':5,'as_of':'2025-01-03T21:00:00+00:00','cutoff':'2025-01-02T21:00:00+00:00','structural_identity':sig,'source_still_valid':True,'maturity_still_valid':True,'artifact_ref':{'path':'D:/us-tech-quant-backtests/synthetic/not_read.joblib','sha256':'c'*64}}
    return u,r

def test_header_only_no_artifact_read():
    u,r=fixture();assert c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)['numeric_read_authority'] is False

def test_uid_swap_blocks_full_domain():
    u,r=fixture();r['asset_uids']={'A':u['asset_uids']['B'],'B':u['asset_uids']['A']}
    with pytest.raises(ValueError,match='UID_EPOCH'):c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)

def test_future_append_isolated():
    u,r=fixture()
    a=c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)
    r['irrelevant_future_metadata']={'2026-01-01':'not_read'}
    assert a==c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)
    with pytest.raises(ValueError,match='PRE2026'):c.qualify_header(r,u,'2026-01-01T21:00:00+00:00','b'*64)

def test_stale_epoch_and_cutoff_block():
    u,r=fixture();r['structural_identity']='d'*64
    with pytest.raises(ValueError,match='STRUCTURAL'):c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)
    u,r=fixture();r['cutoff']=r['as_of']
    with pytest.raises(ValueError,match='CUTOFF'):c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)

def test_no_native_no_padding_and_no_state_fit():
    s=c.specification();assert len(s['families'])==16 and s['new_risk_estimation_by_C']==0
    assert s['bootstrap_stability']['draws']==500
    u,r=fixture();r['family']='DIAG'
    with pytest.raises(ValueError,match='UNSUPPORTED'):c.qualify_header(r,u,'2025-01-06T21:00:00+00:00','b'*64)