import pandas as pd
import numpy as np
import pytest
from scripts.research.a2.data import state_label_foundation as f
from scripts.research.a2.training import stateful_inputs as i

def pred(days=4):
 cal=pd.bdate_range('2024-01-02',periods=days);rows=[]
 for n,d in enumerate(cal):
  for rank,t in enumerate('ABCD',1):
   rows.append(dict(signal_date=d,ticker=t,security_id='SID_'+t,feature_available=True,is_raw_top20=True,new_buy_eligible=(n==0 and t in 'AB') or (n==1 and t=='C') or (n==2 and t=='D'),raw_top20_set_complete=True,raw_a2_rank=rank))
 return pd.DataFrame(rows),cal

def annotations():
 return f.label_reasons(pd.DataFrame([dict(signal_date=pd.Timestamp('2024-01-03'),ticker=t,security_id='SID_'+t,feature_available=True,label_available=True,account_event_unhandled=False,label_unsupported_common_event=False,label_mature_date=pd.Timestamp('2024-01-11'),label_coordinate=i.LABEL) for t in 'ABC']))

def test_all_incumbents_before_labels_and_no_rescue():
 p,cal=pred();keys=f.structural_keys(p,cal);pairs=f.all_incumbent_pairs(keys)
 assert len(pairs.loc[pairs.signal_date.eq(cal[2])])==3
 assert len(keys['replace'].loc[keys['replace'].signal_date.eq(cal[2])])==2
 assert np.allclose(pairs.groupby(['signal_date','entrant']).pre_label_group_weight.sum(),1)
 a=annotations();before=pairs[['signal_date','entrant','incumbent']].copy();x=f.attach_pair_metadata(pairs,a)
 assert x[['signal_date','entrant','incumbent']].equals(before)
 a.loc[a.ticker.eq('A'),'metadata_supported']=False;y=f.attach_pair_metadata(pairs,a)
 assert len(x)==len(y) and y.pair_metadata_supported.sum()<x.pair_metadata_supported.sum()
 assert x.loc[x.pair_metadata_supported].supported_training_group_weight.sum()==1

def test_future_append_invariance():
 p,cal=pred();early=p.loc[p.signal_date.lt(cal[2])]
 a=f.all_incumbent_pairs(f.structural_keys(early,cal));b=f.all_incumbent_pairs(f.structural_keys(p,cal))
 pd.testing.assert_frame_equal(a.reset_index(drop=True),b.loc[b.signal_date.lt(cal[2])].reset_index(drop=True))

@pytest.mark.parametrize('column,value,reason',[('label_available',None,'LABEL_UNAVAILABLE'),('account_event_unhandled',None,'ACCOUNT_EVENT_UNHANDLED'),('label_mature_date',None,'MATURITY_UNBOUND'),('label_mature_date','2026-01-01','MATURITY_OUTSIDE_PRE2026'),('security_id','UNKNOWN','SID_UNKNOWN'),('label_coordinate','OTHER','LABEL_COORDINATE_CHANGED'),('feature_available',False,'FEATURE_UNAVAILABLE'),('label_unsupported_common_event',True,'UNSUPPORTED_COMMON_EVENT')])
def test_missing_flags_fail_closed(column,value,reason):
 a=annotations().loc[[0],list(f.BASE_FLAGS)].copy();a[column]=value
 r=f.label_reasons(a);assert not r.metadata_supported.iloc[0] and r[reason].iloc[0]

def test_unknown_partner_sid_is_not_auto_passed():
 p,cal=pred();pairs=f.all_incumbent_pairs(f.structural_keys(p,cal));a=annotations();a.loc[a.ticker.eq('A'),'security_id']='OTHER'
 x=f.attach_pair_metadata(pairs,a);assert not x.loc[x.incumbent.eq('A'),'pair_metadata_supported'].any()

def test_folds_purge_maturity_and_reject_future():
 p,cal=pred();x=f.attach_pair_metadata(f.all_incumbent_pairs(f.structural_keys(p,cal)),annotations())
 assert f.fold_support(x,'2024-01-11','2025-01-01').sum()==0
 assert f.fold_support(x,'2024-01-12','2025-01-01').sum()==2
 with pytest.raises(ValueError):f.fold_support(x,'2025-01-01','2027-01-01')

@pytest.mark.parametrize('column',['y_open5','raw_a2_prediction','open','ret_1d'])
def test_metadata_reader_rejects_values_before_access(column):
 with pytest.raises(ValueError,match='FORBIDDEN'):f.metadata_read('nonexistent',[column],'0'*64)

@pytest.mark.parametrize('day',['2026-01-01','2027-01-01'])
def test_real_future_state_rejected(day):
 p,cal=pred();p.loc[0,'signal_date']=pd.Timestamp(day)
 with pytest.raises(ValueError):f.structural_keys(p,cal)
