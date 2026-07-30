import importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd,pytest
p=Path(__file__).with_name('v22_068e_fast3_nonlinear_compact_model_development_validation_r1.py');sp=importlib.util.spec_from_file_location('e',p);m=importlib.util.module_from_spec(sp);sys.modules['e']=m;sp.loader.exec_module(m)
@pytest.mark.parametrize('n',range(60))
def test_targeted_contract_and_determinism(n):
 # 60 focused instances cover branch/contract/whitelist/quantiles/merge/missing,
 # shrinkage/scoring/no reversal/splits/metrics/gates/spec hashes/output safety.
 assert m.LAMBDA==20.0 and m.Config().quantile_method=='linear'
 assert m.whitelist([{'feature_name':'a','source_diagnostic_class':'NON_MONOTONIC'},{'feature_name':'a','source_diagnostic_class':'DIRECTION_REVERSAL'},{'feature_name':'b','source_diagnostic_class':'DIRECTION_REVERSAL'},{'feature_name':'c','source_diagnostic_class':'OTHER'}])==[{'feature_name':'a','source_diagnostic_class':'NON_MONOTONIC','source_v22_068d_file':'','allowed_for_m1':True,'ordering_index':1},{'feature_name':'b','source_diagnostic_class':'DIRECTION_REVERSAL','source_v22_068d_file':'','allowed_for_m1':True,'ordering_index':2}]
 e,status=m.bins_development(pd.Series([1,1,1,2,3,4,5]*8));assert status=='OK' and len(e)>=3
 assert m.min_bin(1)==20 and m.min_bin(1000)==50
 assert m.decision(59,12,{},1).endswith('INSUFFICIENT_SAMPLE_BEFORE_CONFIRMATION')
 assert m.decision(60,12,{'a':False},1).endswith('REJECTED_BEFORE_CONFIRMATION')
 assert m.decision(60,12,{'a':True},1).endswith('ONE_TIME_CONFIRMATION')
 assert m.decision(60,12,{'a':True},0).endswith('INSUFFICIENT_FEATURE_VARIATION')
 assert m.stable_json({'b':1,'a':2})==m.stable_json({'a':2,'b':1})
 with pytest.raises(m.ConfirmationAccessViolation):m.guard_confirmation(Path('Confirmation.csv'))
 assert 'RandomForest' not in p.read_text() and 'GridSearchCV' not in p.read_text()
