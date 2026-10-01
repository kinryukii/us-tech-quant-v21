"""Frozen 75-stream inference plus full candidate-key qualification evidence."""
from common import *
from freeze_all import verify_freeze
from replay_all import forbid_learning
from fusion import predict_stage,SmallNet
import time

def main():
    started=time.time();verify_freeze()
    for member in MEMBERS:
        if not (ROOT/f'predictions/base/final/{member}.parquet').exists():raise RuntimeError('BASE_INFERENCE_INCOMPLETE:'+member)
    forbid_learning();predict_stage('final')
    full=pd.read_parquet(ROOT/'data/test_full_candidates.parquet',columns=['signal_date','ticker','asof_quarter','pool_version_state',
        'qualification_status','new_buy_eligible','membership_active','numeric_32_finite'])
    records=[]
    for s in registry()[0]:
        name=s['stream'];path=ROOT/f'predictions/streams/final/{name}.parquet'
        frame=pd.read_parquet(path)
        if frame.duplicated(['signal_date','ticker']).any() or not np.isfinite(frame[['mu','sigma']].to_numpy(float)).all():raise RuntimeError('INVALID_FROZEN_STREAM:'+name)
        if not (frame.sigma>0).all():raise RuntimeError('INVALID_FROZEN_SCALE:'+name)
        joined=full.merge(frame[['signal_date','ticker','mu','sigma']],on=['signal_date','ticker'],how='left',validate='one_to_one')
        legal=joined.new_buy_eligible&joined.membership_active&joined.numeric_32_finite
        joined.loc[~legal,['mu','sigma']]=np.nan
        joined['stream_prediction_status']=np.where(legal&joined.mu.notna(),'PREDICTED_QUALIFIED_CANDIDATE',
            np.where(legal,'FAILED_REQUIRED_INPUT_OR_PREDICTION','BLOCKED_INPUT_QUALIFICATION'))
        joined['formal_full_pool_selection_allowed']=False
        destination=ROOT/f'predictions/streams/final/fullkeys/{name}.parquet';destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            if not pd.read_parquet(destination).equals(joined):raise RuntimeError('FULLKEY_STREAM_ALREADY_DIFFERS:'+name)
        else:joined.to_parquet(destination,index=False)
        records.append({'stream':name,'context_rows':len(frame),'full_candidate_keys':len(joined),'qualified_candidate_predictions':int(joined.stream_prediction_status.eq('PREDICTED_QUALIFIED_CANDIDATE').sum()),
            'blocked_candidate_keys':int((~legal).sum()),'context_sha256':sha(path),'fullkey_sha256':sha(destination)})
        print('FROZEN_STREAM',name,'context',len(frame),'full_keys',len(joined),flush=True)
    verify_freeze()
    write_json(ROOT/'predictions/streams/final/FROZEN_FULLKEY_RECEIPT.json',{'status':'PASS_ALL75_FROZEN_STREAMS',
        'streams':records,'fit_calls':0,'parameter_updates':0,'freeze_hashes_match_before_after':True,'seconds':time.time()-started,
        'formal_full_pool':False,'formal_status':'BLOCKED_DATA','scope':'QUALIFIED_SUBPOOL_DIAGNOSTIC'})

if __name__=='__main__':main()
