"""Complete current input-blocker inventory without qualifying new securities."""
from common import *

def main():
    full=pd.read_parquet(ROOT/'data/test_full_candidates.parquet')
    blocked=full[~full.new_buy_eligible].copy()
    reason=blocked.current_reason.fillna('MISSING_RECORDED_QUALIFICATION_REASON').astype(str)
    glw=blocked.qualification_status.eq('UNKNOWN_GLW_EVENT_DATE_CONFLICT')
    reason.loc[glw]='GLW issuer and saved vendor ex-dividend dates differ by one session; historical correction/arrival unproven.'
    blocked['effective_block_reason']=reason
    cols=['signal_date','ticker','asof_quarter','active_pool_cusip','pool_version_state','qualification_status','effective_block_reason',
        'numeric_feature_row_present','numeric_32_finite','membership_active','new_buy_eligible','context_only_if_held']
    out=ROOT/'analysis';out.mkdir(exist_ok=True)
    blocked[cols].to_csv(out/'ALL_INPUT_BLOCKED_CANDIDATE_KEYS.csv',index=False)
    grouped=blocked.groupby(['qualification_status','effective_block_reason'],dropna=False).agg(
        candidate_security_days=('ticker','size'),tickers=('ticker','nunique'),first_signal=('signal_date','min'),last_signal=('signal_date','max'),
        finite_feature_keys=('numeric_32_finite','sum')).reset_index()
    grouped.to_csv(out/'INPUT_BLOCKERS_BY_REASON.csv',index=False)
    blocked.groupby(['ticker','qualification_status','effective_block_reason'],dropna=False).agg(
        candidate_security_days=('signal_date','size'),first_signal=('signal_date','min'),last_signal=('signal_date','max')).reset_index().to_csv(out/'INPUT_BLOCKERS_BY_TICKER.csv',index=False)
    counts=full.qualification_status.value_counts().to_dict()
    if len(full)!=111868 or len(blocked)!=49476:raise RuntimeError('BLOCKER_KEY_COVERAGE_CHANGED')
    write_json(out/'INPUT_BLOCKERS_RECEIPT.json',{'status':'COMPLETE_BLOCKED_KEY_INVENTORY','full_candidate_keys':len(full),
        'currently_not_buy_eligible_keys':len(blocked),'qualification_status_counts':{str(k):int(v) for k,v in counts.items()},
        'numeric_features_do_not_promote_qualification':True,'new_qualified_rows':0,'new_fit_calls':0,'formal_status':'BLOCKED_DATA'})
    print('INPUT_BLOCKERS',len(blocked),'of',len(full),flush=True)

if __name__=='__main__':main()
