"""All eight frozen RL results and their preregistered matched controls."""
from common import *
from analyze import METRICS

def main():
    registered=json.loads((ROOT/'RL_REGISTRY.json').read_text(encoding='utf-8'))['policies'];rows=[]
    for year in [2025,2026]:
        for item in registered:
            folder=ROOT/f'results/{year}/{item["strategy"]}'
            r=json.loads((folder/'COMPLETE.json').read_text(encoding='utf-8'))
            if r['status']!='REPLAYED' or r['new_fit_calls'] or r['parameter_updates']:raise RuntimeError('INVALID_FROZEN_RL_EVALUATION')
            for file,h in r['artifacts_sha256'].items():
                if sha(folder/file)!=h:raise RuntimeError('RL_LEDGER_CHANGED:'+str(folder/file))
            d=pd.read_csv(folder/'SUMMARY.csv')
            if len(d)!=1 or d.strategy.iloc[0]!=item['strategy']:raise RuntimeError('RL_SUMMARY_COVERAGE')
            row={**d.iloc[0].to_dict(),**item,'year':year,'status':'REPLAYED_DIAGNOSTIC','formal_full_pool':False,
                'scope':r['scope'],'certified_shareholder_total_return':False,'selected_for_deployment':False,'fit_calls_during_evaluation':0}
            row['algorithm']='ppo' if item['policy'].startswith('ppo') else 'reinforce';rows.append(row)
    frame=pd.DataFrame(rows);out=ROOT/'analysis';out.mkdir(exist_ok=True);frame.to_csv(out/'RL_RESULTS.csv',index=False)
    base=frame[~frame.updated][['year','algorithm']+METRICS].rename(columns={m:'zero_'+m for m in METRICS})
    paired=frame[frame.updated].merge(base,on=['year','algorithm'],validate='one_to_one')
    for metric in METRICS:paired['delta_'+metric]=paired[metric]-paired['zero_'+metric]
    paired.to_csv(out/'RL_UPDATED_VS_ZERO.csv',index=False)
    write_json(out/'RL_ANALYSIS_RECEIPT.json',{'status':'COMPLETE_ALL8','accounts':8,'matched_updated_zero_pairs':4,
        'fit_calls':0,'parameter_updates':0,'new_seeds_or_epochs':0,'formal_full_pool_status':'BLOCKED_DATA'})

if __name__=='__main__':main()
