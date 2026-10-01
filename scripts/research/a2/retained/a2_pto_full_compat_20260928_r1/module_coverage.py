"""Export every registered module stage and preserved incompatibility reasons."""
from common import *

def main():
    out=ROOT/'analysis';out.mkdir(exist_ok=True);rows=[]
    def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
    for stage in CUTOFFS:
        for member in MEMBERS:
            r=read(f'models/base/{member}/{stage}_RECEIPT.json')
            rows.append(dict(layer='prediction',stage=stage,member=member,status=r['status'],
                rows=r['train_rows'],label_end_max=r['train_label_end_max'],cutoff=r['cutoff_exclusive'],
                actual_estimators=r['estimator_fit_count'],artifact=f'models/base/{member}/{stage}.joblib',artifact_sha256=r['artifact_sha256'],reason=''))
    for stage in ['validation','final']:
        r=read(f'models/fusion/{stage}/RECEIPT.json')
        for a in r['adapters']:
            artifact=f'models/fusion/{stage}/{a["member"]}_adapter.joblib'
            rows.append(dict(layer='return_interface_calibration',stage=stage,member=a['member'],status=a['status'],rows=a['rows'],
                label_end_max=a['label_end_max'],cutoff=a['cutoff'],artifact=artifact,artifact_sha256=sha(ROOT/artifact),reason='Time-legal OOF, nested mapping.'))
        for f in r['fusions']:
            rows.append(dict(layer='prediction_fusion',stage=stage,member=f['stream'],status=f['status'],rows=f['rows'],
                label_end_max=f['label_end_max'],cutoff=CUTOFFS[stage],artifact=f'models/fusion/{stage}/{f["stream"]}.joblib',
                artifact_sha256=f['artifact_sha256'],reason='Required members: '+ '|'.join(f['members'])))
        r=read(f'models/risk/{stage}/TRAIN_RECEIPT.json')
        for name in RISKS:
            reason=f'Shared {r["risk_return_window"]}-day frozen structures; model-specific per-ticker fallback evidence in RISK_FIT_FAILURES_AND_FALLBACKS.csv.'
            artifact=f'models/risk/{stage}/{name}.json'
            rows.append(dict(layer='risk',stage=stage,member=name,status=r['status'],rows=r['training_rows'],
                label_end_max=r['training_label_end_max'],cutoff=r['cutoff_exclusive'],artifact=artifact,artifact_sha256=sha(ROOT/artifact),reason=reason))
        r=read(f'models/rl/{stage}/TRAIN_RECEIPT.json')
        for name in ['reinforce_updated','reinforce_zero','ppo_updated','ppo_zero']:
            artifact=f'models/rl/{stage}/{name}.pt'
            rows.append(dict(layer='rl_policy',stage=stage,member=name,status=r['status'],rows=r['scaler_training_rows'],
                label_end_max=r['reward_end_last'],cutoff=r['cutoff_exclusive'],artifact=artifact,artifact_sha256=sha(ROOT/artifact),
                reason='Zero-update matched initialization.' if name.endswith('zero') else 'Fixed four updates; actual accounts, no 2026 learning.'))
    pd.DataFrame(rows).to_csv(out/'MODULE_TRAINING_COVERAGE.csv',index=False)
    old=[
        ('a2_latest_effective_joint_20260927/models','32 features; MEAN_ER_3D_5D_10D_20D','INCOMPATIBLE','Different target/horizon; one-session y_next_open required.'),
        ('a2_strict_method_retrain_20260926/results','Pre2026 staged multi-horizon excess forecasts','INCOMPATIBLE','Legal old timing does not make the new statistical target match.'),
        ('a2_collaboration_methods_20260928_r1','32 features; multi-horizon target, clip .30, 50000 rows','INCOMPATIBLE','Target, sampling and clip differ.'),
        ('a2_multimodel_joint_20260928/value_artifacts','106-dimensional state-action utility','INCOMPATIBLE','Costs/weight/risk already inside utility; not return mean, quantiles or upward event.'),
        ('a2_multimodel_joint_20260928/ensemble_artifacts','Old state-action utility OOF and meta','INCOMPATIBLE','Target and member interface differ.'),
        ('a2_cooperative_fusion_20260928_9231','Action-rank/utility cooperative fusion','INCOMPATIBLE','Not same-unit one-session return fusion.'),
        ('a2_contextual_stacking_r1_20260928','State-dependent old utility panel','INCOMPATIBLE','Target and sample-state contract differ.'),
        ('top20_multimethod_pre2026_test2026_r1/fit_ppo.py','Old fixed TOP20 PPO observation','INCOMPATIBLE','Candidate and 32-feature/state interface differ.'),
        ('a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet','Physical pre2026 32-feature context and mature y_next_open','REUSED_MATCHING_CONTRACT','Retain inherited identity/price limitations.'),
        ('a2_buy_sell_cash_multimodel_20260928/engine_v2.py','Holding-aware units/cash, next-open execution, fees and capacity','REUSED_REFERENCE_AND_RULES','Independent batch-engine conformance; scalar RL reuses this engine.'),
        ('D:/us-tech-quant-results/13f_pit_v1/scripts/v17b/integrity_rebuild_v17b.py','Original eligible rows, Top100 and capped protected union functions','REUSED_RULE_FUNCTIONS','AST loaded without mutating old batch; restated pool independently rebuilt.')]
    pd.DataFrame(old,columns=['source','old_object','reuse_status','reason']).to_csv(out/'ARTIFACT_REUSE_COMPATIBILITY.csv',index=False)
    write_json(out/'MODULE_COVERAGE_RECEIPT.json',{'rows':len(rows),'prediction_stages':93,'return_interface_stages':62,
        'fusion_stages':88,'risk_stages':24,'rl_policy_stages':8,'new_fit_calls':0,'candidate_additions':0})

if __name__=='__main__':main()
