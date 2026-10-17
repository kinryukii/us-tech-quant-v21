"""Generated only: variable risk charges and finite full policy dispatch."""
import json
import sqlite3
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.training import full_selector_workflow as w

class Journal:
    def __init__(self):
        self.design={"risk_inputs":{"source":"GENERATED"}}
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE nodes (node_id TEXT PRIMARY KEY,kind TEXT,status TEXT,entered INTEGER,identity TEXT,artifact TEXT,error TEXT)')
        self.db.execute('CREATE TABLE events (node_id TEXT,action TEXT,payload TEXT)')
        names=[('RISK_REFRESH|2024-01-02','RISK_REFRESH_DISPATCH')]+[('RISK_REFRESH|2024-01-02|UNIT|'+str(i).zfill(2),'RISK_LEARNED_UNIT') for i in range(71)]
        self.db.executemany("INSERT INTO nodes VALUES (?,?,'NAMED',0,NULL,NULL,NULL)",names)
        self.db.commit()
    def status(self,node):
        row=self.db.execute('SELECT status,entered,identity,artifact,error FROM nodes WHERE node_id=?',(node,)).fetchone()
        return dict(zip(('status','entered','identity','artifact','error'),row))
    def event(self,node,action,payload):self.db.execute('INSERT INTO events VALUES (?,?,?)',(node,action,json.dumps(payload)))


def context():return dict(decision_at='2024-01-02T21:00:00+00:00',ordered_assets=['A','B'],asset_uids={'A':'CUSIP:A','B':'CUSIP:B'},asset_epochs={'A':'E1','B':'E1'},cutoff='2023-12-29T21:00:00+00:00')


def test_whole_task_dag_counts_union_risk_not18_times_learned_and_future_no_slots():
    days=pd.bdate_range('2024-01-02',periods=502)
    value={'decision_to_context':[{'decision_at':str(d.date())+'T21:00:00Z'} for d in days],
        'plan':{'nodes':[dict(decision_at=str(days[0].date())+'T21:00:00Z',family=f) for f in w.c.FAMILIES]}}
    dag=w.task_dag(value)
    assert dag['risk_weighted_learned_ceiling']==71 and dag['counts']['RISK_LEARNED_UNIT']==71
    assert dag['counts']['HYBRID_ESTIMATOR']==120 and dag['counts']['HYBRID_SCALER']==24
    assert dag['counts']['MEMBER_SOLVE']==9036 and dag['counts']['CONTINUOUS_ACCOUNT']==66
    assert dag['exposure_endpoints']==321 and len({n['node_id'] for n in dag['nodes']})==len(dag['nodes'])


def test_reserve_before_decode_actual_weighted_units_separate_from18_outputs(monkeypatch,tmp_path):
    j=Journal();entered=[]
    def load(run,ctx,*,reservation_ack):
        assert reservation_ack=={'ack':True,'reserved_units':71,'reservation_id':'RISK_REFRESH|2024-01-02'}
        assert j.db.execute("SELECT count(*) FROM events WHERE action='RESERVE_WEIGHTED_UPPER_71'").fetchone()[0]==1
        entered.append('numeric')
        return dict(inputs=object(),support_metadata=object(),current_identity_proof=object())
    def estimate(inputs,**kw):
        assert kw['reserve_callback'](dict(research_id=w.ID,recipe_sha256=w.risk.content_hash(w.risk.fixed_policy_risk_specification()),as_of=context()['decision_at'],requested_families=list(w.c.FAMILIES),maximum_weighted_units=71))['ack']
        token=dict(name='two_native_parameters',kind='covariance',units=2,key='native',status='FIT_STARTED')
        assert kw['on_component_start'](token)['ack'];token['status']='SUCCEEDED'
        return dict(states={f:dict(status='ESTIMATED') for f in w.c.FAMILIES},component_starts=[token],weighted_learned_units=2)
    monkeypatch.setattr(w.risk,'estimate_fixed_policy_risk_refresh',estimate)
    value=w.risk_refresh_once(tmp_path,j,context(),load)
    assert len(value['states'])==18 and value['weighted_learned_units']==2
    assert j.db.execute('SELECT sum(entered) FROM nodes').fetchone()[0]==2
    assert j.db.execute("SELECT count(*) FROM nodes WHERE status='NOT_REQUIRED'").fetchone()[0]==69
    assert j.db.execute("SELECT count(*) FROM events WHERE action='RESERVE_WEIGHTED_UPPER_71'").fetchone()[0]==1
    again=w.risk_refresh_once(tmp_path,j,context(),lambda *a,**k:pytest.fail('COMPLETE exact reuse must not decode'))
    assert again['weighted_learned_units']==2


def test_missing_source_no_fit_cannot_be_called_success_and_no_retry(monkeypatch,tmp_path):
    j=Journal()
    def missing(*a,**k):raise ValueError('EXACT_MATURE_SOURCE_MISSING')
    monkeypatch.setattr(w.risk,'estimate_fixed_policy_risk_refresh',lambda *a,**k:pytest.fail('No producer on missing source'))
    assert w.risk_refresh_once(tmp_path,j,context(),missing) is None
    assert j.status('RISK_REFRESH|2024-01-02')['status']=='SOURCE_NOT_TESTABLE'
    assert j.db.execute('SELECT sum(entered) FROM nodes').fetchone()[0]==0
    assert w.risk_refresh_once(tmp_path,j,context(),lambda *a,**k:pytest.fail('No source retry')) is None


def test_partial_actual_risk_failure_retains_charged_and_unentered_status(monkeypatch,tmp_path):
    j=Journal()
    def estimate(*a,**k):
        k['on_component_start'](dict(name='actual',kind='covariance',units=1,key='k'))
        raise ValueError('ACTUAL_BACKEND_FAILED')
    monkeypatch.setattr(w.risk,'estimate_fixed_policy_risk_refresh',estimate)
    load=lambda *a,**k:dict(inputs=object(),support_metadata=object(),current_identity_proof=object())
    assert w.risk_refresh_once(tmp_path,j,context(),load) is None
    assert j.status('RISK_REFRESH|2024-01-02|UNIT|00')['entered']==1
    assert j.status('RISK_REFRESH|2024-01-02|UNIT|00')['status']=='FAILED'
    assert j.db.execute("SELECT count(*) FROM nodes WHERE status='NOT_REQUIRED'").fetchone()[0]==70


def test_changed_completed_risk_source_refuses_cache(monkeypatch,tmp_path):
    j=Journal();node='RISK_REFRESH|2024-01-02'
    j.db.execute("UPDATE nodes SET status='COMPLETE',identity='different' WHERE node_id=?",(node,));j.db.commit()
    with pytest.raises(ValueError,match='IDENTITY_CHANGED'):w.risk_refresh_once(tmp_path,j,context(),lambda *a,**k:None)


def test_new_member_set_retains_whole_U_and_fixed_weights():
    f=pd.DataFrame(dict(ticker=[str(i) for i in range(42)],selected=[i<20 for i in range(42)],target_weight=[.05 if i<20 else 0. for i in range(42)],score=list(range(42))))
    members=[str(i) for i in range(22,42)]
    value=w._decision_panel(f,members)
    assert len(value)==42 and value.selected.sum()==20 and value.loc[value.selected,'target_weight'].eq(.05).all()
    assert value.selected.iloc[:10].sum()==0 and value.selected.iloc[40:].all()
    with pytest.raises(ValueError):w._decision_panel(f,members[:-1])
