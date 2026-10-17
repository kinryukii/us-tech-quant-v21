import copy
from pathlib import Path
import pytest
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as r

def test_actual_fit_debits_are_durable_nonrefundable_and_not_retried(monkeypatch,tmp_path):
    store={}
    monkeypatch.setattr(r,'guard_numeric',lambda run,sha:Path(run))
    monkeypatch.setattr(r.parent,'write',lambda root,name,value:store.update({name:copy.deepcopy(value)}))
    x=r.R6Ledger(tmp_path,'a'*64)
    x.reserve('estimator_learned_state_fit','learner1',2,physical_kind='joint trunk and head')
    assert store['work/R6_PHYSICAL_LEDGER.json']['actual_counts']['estimator_learned_state_fit']==2
    x.fail('learner1',reason='synthetic numerical failure')
    assert x.status['actual_counts']['estimator_learned_state_fit']==2
    with pytest.raises(ValueError,match='NO_SCIENTIFIC_RETRY'):x.reserve('estimator_learned_state_fit','learner1')
    x.reserve('deterministic_optimizer_policy_solve','q1')
    x.complete('q1',backend_calls=1)
    x.deterministic('projection_iterations',100)
    assert x.status['actual_counts']['deterministic_optimizer_policy_solve']==1
    assert x.status['deterministic_counters']['projection_iterations']==100

def test_all_hard_caps_include_failure_and_zero_scientific_retry(monkeypatch,tmp_path):
    monkeypatch.setattr(r,'guard_numeric',lambda run,sha:Path(run))
    monkeypatch.setattr(r.parent,'write',lambda *args:None)
    x=r.R6Ledger(tmp_path,'a'*64)
    x.reserve('account_mechanism_paths','last',120)
    x.fail('last',reason='synthetic failure')
    with pytest.raises(ValueError,match='BUDGET_EXHAUSTED'):x.reserve('account_mechanism_paths','overflow')
    with pytest.raises(ValueError,match='BUDGET_EXHAUSTED'):x.reserve('scientific_retry','retry')
    assert x.status['actual_counts']['account_mechanism_paths']==120
