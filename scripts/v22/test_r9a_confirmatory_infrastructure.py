import json
from pathlib import Path
import pandas as pd
import tempfile
from r9a_confirmatory_infrastructure import build_manifests, evaluate_candidate, GATE_CONFIG, neighborhood, run_fixtures, load_confirmation_candidates

def metrics():
 return {k:(.1 if k in {'median_return','median_excess_vs_qqq','worst_return','lower_decile_return','max_drawdown'} else .99 if k in {'beat_qqq_share','valid_window_share'} else 4 if k in {'valid_window_count','horizon_pass_count'} else 1.) for k in GATE_CONFIG}
def test_manifest_is_reproducible_and_disjoint():
 s=pd.date_range('2020-01-01',periods=100,freq='B'); a=build_manifests(s); b=build_manifests(s); assert a.equals(b); assert not set(a[a.split=='DEVELOPMENT'].start_date)&set(a[a.split=='CONFIRMATION'].start_date)
def test_gate_failure_modes():
 x=metrics(); assert all(r['pass_fail']=='PASS' for r in evaluate_candidate('ok',x)); assert any(r['pass_fail']=='FAIL' for r in evaluate_candidate('tail',{**x,'worst_return':-.9})); assert any(r['pass_fail']=='FAIL' for r in evaluate_candidate('sample',{**x,'valid_window_count':1})); assert any(r['pass_fail']=='FAIL' for r in evaluate_candidate('turn',{**x,'annualized_turnover':99})); assert any(r['pass_fail']=='FAIL' for r in evaluate_candidate('data',{**x,'valid_window_share':0}))
def test_neighborhood_and_fixture_lifecycle(tmp_path):
 b={'parameters':{'a':1,'b':2},'metrics':metrics()}; n=neighborhood('x',b,[{'parameters':{'a':0,'b':2},'metrics':metrics(),'pass':True},{'parameters':{'a':2,'b':2},'metrics':metrics(),'pass':True}]); assert len(n)==2 and n[0]['stability_pass']; a=run_fixtures(tmp_path); p=pd.read_csv(tmp_path/'r9a_trade_lifecycle_fixture.csv'); assert len(p) and p.exit_reason.notna().all() and a['open_position_after_window_count']==0 and load_confirmation_candidates(tmp_path/'r9a_frozen_development_candidates.json')[0]['candidate_id']=='fixture_excellent'
 try: load_confirmation_candidates(tmp_path/'not_frozen.json'); assert False
 except ValueError: pass

if __name__ == '__main__':
 test_manifest_is_reproducible_and_disjoint()
 test_gate_failure_modes()
 with tempfile.TemporaryDirectory() as d: test_neighborhood_and_fixture_lifecycle(Path(d))
 print('R9A_UNIT_TESTS=PASS')
