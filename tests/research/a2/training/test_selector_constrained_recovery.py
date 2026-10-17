import copy
import pytest
from scripts.research.a2.training import selector_constrained_recovery as r


def fixture():
    nodes=[{'id':'C13_R06_D02@'+str(i),'candidate_id':'C13_R06_D02','artifact':{'sha256':'a'*64}} for i in range(115)]
    events=[dict(key=n['id'],status='SUCCEEDED',backend_entered=True,inputs_sha256='a'*64,result_sha256='b'*64) for n in nodes]
    return events,{'nodes':nodes}


def test_only_terminal_success_prefix():
    e,d=fixture();out=r.successful_prefix(e,d)
    assert len(out)==115 and out==e and out is not e


@pytest.mark.parametrize('change',['failed','reserved','missing','extra','no_hash','bad_input','not_entered','wrong_role'])
def test_reconstruction_cannot_retry_failed_or_change_input(change):
    e,d=fixture()
    if change=='failed':e[0]['status']='FAILED'
    elif change=='reserved':e[0]['status']='RESERVED'
    elif change=='missing':e.pop()
    elif change=='extra':e.append(dict(e[0],key='extra'))
    elif change=='no_hash':e[0].pop('result_sha256')
    elif change=='bad_input':e[0]['inputs_sha256']='c'*64
    elif change=='not_entered':e[0]['backend_entered']=False
    else:d['nodes'][0]['candidate_id']='C13_R08_D02'
    with pytest.raises(ValueError):r.successful_prefix(e,d)


def test_hash_identity_and_mismatch_aborts_outside_scientific_catch():
    value={'chosen_uids':['S1'],'score':1.25};event={'key':'synthetic','result_sha256':r.content_hash(value)}
    assert r.identical_output(value,event)==event['result_sha256']
    with pytest.raises(r.ReconstructionMismatch):r.identical_output({'chosen_uids':['S2'],'score':1.25},event)
    assert not issubclass(r.ReconstructionMismatch,Exception)


def test_latest_success_is_original_status_not_reset():
    e,d=fixture();prefix=[dict(v,status='RESERVED') for v in e]+e
    assert r.successful_prefix(prefix,d)==e

@pytest.mark.parametrize('actual',[115,2000,3708])
def test_actual_calls_are_distinct_from_charged_ceiling(actual):
    ledger={'events':[{}]*3708,'actual_solver_calls':actual}
    snap={'events':[{'status':'SUCCEEDED','backend_entered':True}]*115}
    out=r.physical_accounting(ledger,snap,115)
    assert out['total_physical_solver_calls']==actual+115
    assert out['total_physical_charged_reservations']==3823
    assert out['physical_solver_ceiling']==3823


@pytest.mark.parametrize('change',['slots','extra','not_entered','failed','unverified','overcap'])
def test_physical_accounting_cannot_hide_missing_or_extra_reconstruction(change):
    ledger={'events':[{}]*3708,'actual_solver_calls':3708}
    snap={'events':[{'status':'SUCCEEDED','backend_entered':True} for _ in range(115)]}
    verified=115
    if change=='slots':ledger['events'].pop()
    elif change=='extra':snap['events'].pop()
    elif change=='not_entered':snap['events'][0]['backend_entered']=False
    elif change=='failed':snap['events'][0]['status']='FAILED'
    elif change=='unverified':verified=114
    else:ledger['actual_solver_calls']=3709
    with pytest.raises(ValueError):r.physical_accounting(ledger,snap,verified)
