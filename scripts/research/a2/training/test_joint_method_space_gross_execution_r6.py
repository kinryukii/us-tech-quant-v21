import pandas as pd
import numpy as np
import pytest
from scripts.research.a2.training import joint_method_space_gross_execution_r6 as x

class Source:
    def __init__(self,bad_selected=False):
        self.calls=[];self.bad_selected=bad_selected
    def rows(self,**kwargs):
        assert kwargs.get('fit') is None
        return pd.DataFrame([dict(signal_date=pd.Timestamp('2022-06-01'),ticker=f'T{i:02}',security_uid=f'UID{i}',asset_epoch='epoch1',execution_date=pd.Timestamp('2022-06-02'),label_end_date=pd.Timestamp('2022-06-09'),label_mature_date=pd.Timestamp('2022-06-09'),identity_qualified=True,source_qualified=True) for i in range(21)])
    def context(self,keys,stop,columns):
        self.calls.append('features');v=keys[['signal_date','ticker']].copy()
        for c in columns:v[c]=.01 if c!='avg_dollar_volume_20d' else 1e6
        return v
    def truth(self,keys,stop):
        self.calls.append('truth')
        assert len(keys)==20 and 'T00' not in set(keys.ticker)
        if self.bad_selected:raise ValueError('SELECTED_TARGET_SOURCE_UNSUPPORTED')
        return np.full(len(keys),.01)

def packet(source,year,keys):
    v=keys.copy();v['native_equal_mu']=np.arange(len(v),dtype=float)/1000
    v['verified_source_fit_cutoff']=pd.Timestamp('2022-01-01',tz='UTC')
    v['verified_source_label_mature_max']=pd.Timestamp('2021-12-20',tz='UTC')
    v['genuine_chronological_oof']=True
    v.attrs['verified_full_five_member_genuine_clocks']=True
    return v

def test_top20_before_target_support_and_no_labeled_replacement(monkeypatch):
    monkeypatch.setattr(x.io,'r4_equal_packet',packet)
    s=Source();out=x.reference_rows(s,start='2022-01-01',stop='2023-01-01',mature=True)
    assert len(out)==20 and s.calls==['features','truth']
    with pytest.raises(ValueError,match='SELECTED_TARGET_SOURCE_UNSUPPORTED'):x.reference_rows(Source(True),start='2022-01-01',stop='2023-01-01',mature=True)

def test_clock_proof_before_context_values(monkeypatch):
    def unproved(*args):
        v=packet(*args);v.attrs['verified_full_five_member_genuine_clocks']=False;return v
    monkeypatch.setattr(x.io,'r4_equal_packet',unproved)
    s=Source()
    with pytest.raises(ValueError,match='REAL_FIVE_MEMBER'):x.reference_rows(s,start='2022-01-01',stop='2023-01-01',mature=True)
    assert s.calls==[]

def test_future_maturity_cannot_be_relabelled_by_year(monkeypatch):
    def bad_clock(*args):
        v=packet(*args);v['verified_source_label_mature_max']=pd.Timestamp('2022-01-01',tz='UTC');return v
    monkeypatch.setattr(x.io,'r4_equal_packet',bad_clock)
    s=Source()
    with pytest.raises(ValueError,match='REAL_PRODUCER_MATURITY'):x.reference_rows(s,start='2022-01-01',stop='2023-01-01',mature=True)
    assert s.calls==[]
