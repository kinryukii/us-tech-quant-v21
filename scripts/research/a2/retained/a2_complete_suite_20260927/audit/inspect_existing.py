"""Read-only audit of prior fit and test artifacts; writes only this audit folder."""
from pathlib import Path
import json, hashlib
import pandas as pd
import numpy as np

BASE = Path(r'C:\Users\Lenovo\Documents\CODING开发\a2_strict_method_retrain_20260926')
OUT = Path(__file__).resolve().parent
SOURCE = Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1')

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def main():
    mpath = SOURCE / 'A2/training_matrix.parquet'
    m = pd.read_parquet(mpath)
    report = {'source_matrix': {'path':str(mpath), 'sha256':sha(mpath), 'rows':len(m),
        'signal_min':str(m.signal_date.min()), 'signal_max':str(m.signal_date.max()),
        'target_end_max':str(m.target_end_date.max()),
        'non_pre2026_signals':int(m.signal_date.ge('2026-01-01').sum()),
        'non_pre2026_target_end':int(m.target_end_date.ge('2026-01-01').sum()),
        'duplicate_keys':int(m.duplicated(['signal_date','ticker']).sum()),
        'null_targets':int(m.target.isna().sum())}}
    methods = {}
    for method in ('hgb','ridge','elastic_net','mlp','quantile_50_diagnostic'):
        folder = BASE/'results'/method
        logs=json.loads((folder/'fit_log.json').read_text())
        models=[]
        for log in logs:
            p=folder/Path(log['model_path']).name
            models.append({'stage':log['stage'],'exists':p.exists(),'sha256_matches_log':sha(p)==log['model_sha256']})
        methods[method]={'recorded_fits':len(logs),'models':models}
    report['original_methods']=methods
    gatepath=BASE/'test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet'
    g=pd.read_parquet(gatepath)
    fpath=BASE/'test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet'
    f=pd.read_parquet(fpath)
    report['test_gate']={'path':str(gatepath),'sha256':sha(gatepath),'rows':len(g),'dates':g.signal_date.nunique(),
        'signal_min':str(g.signal_date.min()),'signal_max':str(g.signal_date.max()),
        'status_counts':g.final_input_gate.value_counts().to_dict(),
        'duplicate_date_ticker':int(g.duplicated(['signal_date','ticker']).sum()),
        'columns':list(g.columns)}
    fields=['lookback_121_eligible','has_32_finite','version_checked']
    report['test_gate']['gate_boolean_counts']={c:g[c].fillna(False).value_counts().to_dict() for c in fields if c in g}
    perday=g.groupby('signal_date').final_input_gate.apply(lambda x:int(x.str.startswith('UNKNOWN').sum()))
    report['test_gate']['days_with_zero_unknown']=int(perday.eq(0).sum())
    report['test_gate']['unknowns_per_day_min']=int(perday.min())
    report['test_gate']['unknowns_per_day_max']=int(perday.max())
    report['test_features']={'path':str(fpath),'sha256':sha(fpath),'rows':len(f),'dates':f.signal_date.nunique(),
        'tickers':f.ticker.nunique(),'columns':list(f.columns),'duplicate_date_ticker':int(f.duplicated(['signal_date','ticker']).sum())}
    c=f[['signal_date','ticker','all_features_available']]
    joined=g[['signal_date','ticker','final_input_gate']].merge(c,on=['signal_date','ticker'],how='left',validate='one_to_one')
    report['test_features']['candidate_rows_feature_available']=int(joined.all_features_available.fillna(False).sum())
    report['test_features']['candidate_rows_no_matching_feature_row']=int(joined.all_features_available.isna().sum())
    (OUT/'EXISTING_ARTIFACT_AUDIT.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k in ['source_matrix','original_methods']},default=str))
    print(json.dumps({k:v for k,v in report['test_gate'].items() if k!='columns'},default=str))
    print(json.dumps({k:v for k,v in report['test_features'].items() if k!='columns'},default=str))

if __name__=='__main__': main()
