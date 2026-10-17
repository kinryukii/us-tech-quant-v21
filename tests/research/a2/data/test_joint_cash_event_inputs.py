"""Synthetic Arrow-before-pandas exact-key and clock guards."""
import hashlib
import pandas as pd
import pytest
from scripts.research.a2.data.joint_cash_event_inputs import read_exact_vendor_actions,ACTION_COLUMNS

def source(tmp_path):
    f=pd.DataFrame({c:[0.,0.,0.] for c in ACTION_COLUMNS if c not in ("code","ex_div_date")})
    f["code"]=["US.AAA","US.AAA","US.BBB"]
    f["ex_div_date"]=["2023-01-26","2026-01-26","2023-01-26"]
    f["per_cash_div"]=[.1,123.,.2]
    p=tmp_path/"actions.parquet";f[ACTION_COLUMNS].to_parquet(p,index=False)
    return p,hashlib.file_digest(p.open("rb"),"sha256").hexdigest()

def test_mixed_source_future_and_unrequested_names_never_enter_result(tmp_path):
    p,s=source(tmp_path)
    f=read_exact_vendor_actions(p,s,[("US.AAA","2023-01-26")])
    assert f.code.tolist()==["US.AAA"] and f.per_cash_div.tolist()==[.1]
    assert set(f)==set(ACTION_COLUMNS)
    assert not any(c.startswith(("forward","backward")) for c in f)

@pytest.mark.parametrize("day",["2026-01-01",None,"2023-01-26T12:00:00","2023-01-26T00:00:00Z"])
def test_invalid_or_future_request_rejected_before_materialization(tmp_path,day):
    p,s=source(tmp_path)
    with pytest.raises(ValueError):read_exact_vendor_actions(p,s,[("US.AAA",day)])

def test_source_hash_and_request_identity_guard(tmp_path):
    p,s=source(tmp_path)
    with pytest.raises(ValueError,match="HASH_CHANGED"):read_exact_vendor_actions(p,"0"*64,[("US.AAA","2023-01-26")])
    with pytest.raises(ValueError,match="DUPLICATE"):read_exact_vendor_actions(p,s,[("US.AAA","2023-01-26")]*2)
