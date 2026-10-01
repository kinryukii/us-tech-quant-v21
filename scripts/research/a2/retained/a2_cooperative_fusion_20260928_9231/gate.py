"""Frozen conditional six-expert gate; train only on temporally valid old OOF.

The five gate variables exclude action, ranks, targets and future information.
One state therefore has the same six proportions for all five actions. The
positive scalar calibration has no intercept; all-zero expert scores give zero.
"""
from pathlib import Path
import hashlib
import json
import math
import time

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'gate_artifacts'
CONTRACT=ROOT/'EXPERIMENT_CONTRACT.md'
SEED=20260928
EPOCHS=12
BATCH_SIZE=4096
LEARNING_RATE=.003
WEIGHT_DECAY=.001
STAGES={'validation':'2025-01-01','final':'2026-01-01'}
RANK_COLUMNS=[f'rank_{name}' for name in ('ridge','elastic_net','logistic','hgb','q50','mlp')]
GATE_COLUMNS=['current_weight','cash_weight','age_scaled','realized_vol_20d','ret_20d']
torch.set_num_threads(2)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False,default=str),encoding='utf-8')


def array_sha(array):
    a=np.ascontiguousarray(array)
    return hashlib.sha256(str((a.shape,str(a.dtype))).encode()+a.tobytes()).hexdigest()


class ConditionalGate(nn.Module):
    def __init__(self):
        super().__init__()
        self.hidden=nn.Linear(5,8)
        self.experts=nn.Linear(8,6)
        self.raw_calibration=nn.Parameter(torch.tensor(0.,dtype=torch.float32))

    def proportions(self,features):
        return torch.softmax(self.experts(torch.tanh(self.hidden(features))),dim=1)

    def calibration(self):return F.softplus(self.raw_calibration)

    def forward(self,features,expert_ranks):
        weights=self.proportions(features)
        return self.calibration()*(weights*expert_ranks).sum(dim=1),weights


def validate_training_frame(frame,stage):
    if stage not in STAGES:raise ValueError('INVALID_GATE_STAGE')
    required=['signal_date','label_end_date','base_fit_cutoff','ticker','state_id','action',
              'target_advantage',*RANK_COLUMNS]
    if any(name not in frame for name in required):raise ValueError('MISSING_GATE_TRAINING_COLUMN')
    signal=pd.to_datetime(frame.signal_date)
    end=pd.to_datetime(frame.label_end_date)
    base=pd.to_datetime(frame.base_fit_cutoff)
    cutoff=pd.Timestamp(STAGES[stage])
    expected={2024} if stage=='validation' else {2024,2025}
    if (frame.empty or set(signal.dt.year)!=expected or signal.isna().any() or end.isna().any()
            or base.isna().any() or not signal.lt(cutoff).all() or not end.lt(cutoff).all()
            or not end.gt(signal).all() or not base.le(signal).all()):
        raise ValueError('GATE_TRAINING_TIME_LEAKAGE_OR_WRONG_YEARS')
    if not (base==pd.to_datetime(signal.dt.year.astype(str)+'-01-01')).all():
        raise ValueError('GATE_OOF_BASE_STAGE_MISMATCH')
    if not np.isfinite(frame[RANK_COLUMNS+['target_advantage']].to_numpy(float)).all():
        raise ValueError('NONFINITE_GATE_TRAINING_INPUT')
    key=['signal_date','ticker','state_id','action']
    if frame.duplicated(key).any():raise ValueError('DUPLICATE_GATE_ACTION_ROW')
    if not set(frame.action.astype(float)).issubset({0.,.025,.05,.075,.1}):
        raise ValueError('INVALID_GATE_ACTION')
    if not frame.groupby(['signal_date','ticker','state_id'],sort=False).size().eq(5).all():
        raise ValueError('INCOMPLETE_FIVE_ACTION_STATE')
    zero=frame.action.eq(0)
    if not frame.loc[zero,RANK_COLUMNS+['target_advantage']].eq(0).all().all():
        raise ValueError('NONZERO_EXIT_BASELINE')


def deterministic_order(frame):
    """Same complete-sample order in every epoch, independent of targets/ranks."""
    digests=[]
    for row in frame[['signal_date','ticker','state_id','action']].itertuples(index=False):
        key=f'{pd.Timestamp(row.signal_date).date()}|{row.ticker}|{int(row.state_id)}|{float(row.action):.3f}'
        digests.append(hashlib.sha256(key.encode()).hexdigest())
    return np.argsort(np.asarray(digests),kind='stable')


def _gate_features(frame):
    from data_context import gate_features
    x=np.asarray(gate_features(frame),dtype=np.float64)
    if x.shape!=(len(frame),5) or not np.isfinite(x).all():raise ValueError('INVALID_GATE_OBSERVABLE_STATE')
    return x


def _capture_sources(stage):
    import data_context
    supplied=data_context.training_sources(stage)
    if not isinstance(supplied,dict):raise ValueError('TRAINING_SOURCES_MUST_BE_HASH_MAPPING')
    sources={str(Path(path)):str(value) for path,value in supplied.items()}
    for path in (Path(__file__),CONTRACT,Path(data_context.__file__)):
        sources[str(path)]=sha(path)
    for path,value in sources.items():
        if sha(path)!=value:raise ValueError(f'GATE_PREFIT_INPUT_HASH_MISMATCH:{path}')
    return sources


def fit_stage(stage):
    import data_context
    if list(data_context.RANK_COLUMNS)!=RANK_COLUMNS:raise ValueError('GATE_RANK_ORDER_MISMATCH')
    if list(data_context.GATE_COLUMNS)!=GATE_COLUMNS:raise ValueError('GATE_STATE_ORDER_MISMATCH')
    OUT.mkdir(exist_ok=True)
    if any(OUT.glob(f'{stage}_*')):raise RuntimeError('EXISTING_GATE_STAGE_PRESERVED')
    sources=_capture_sources(stage)
    specification=dict(stage=stage,cutoff_exclusive=STAGES[stage],seed=SEED,epochs=EPOCHS,
        batch_size=BATCH_SIZE,learning_rate=LEARNING_RATE,weight_decay=WEIGHT_DECAY,
        optimizer='Adam',loss='MSE target_advantage / in-stage target population std, no centering',
        architecture=[5,8,6],hidden_activation='tanh',output_activation='softmax',
        calibration='softplus(raw_calibration), raw initial 0; shared positive scalar, no intercept',
        gate_columns=GATE_COLUMNS,rank_columns=RANK_COLUMNS,
        normalization='Fresh in-stage mean/population std on five observable inputs; zero scale replaced by 1',
        target_scaling='Fresh in-stage population std only; zero scale replaced by 1; inference restores original utility units',
        row_order='Ascending SHA256(date|ticker|state_id|action rounded to 3 decimals), fixed every epoch',
        action_in_gate=False,expert_scores_in_gate=False,early_stopping=False,search_trials=0,
        input_sha256=sources,created_utc=pd.Timestamp.now(tz='UTC').isoformat())
    write(OUT/f'{stage}_PRE_FIT.json',specification)
    frame=data_context.load_training(stage)
    validate_training_frame(frame,stage)
    expected_rows=90_000 if stage=='validation' else 180_000
    if len(frame)!=expected_rows:raise ValueError('GATE_OOF_SAMPLE_BUDGET_MISMATCH')
    gate_x=_gate_features(frame)
    state_keys=frame[['signal_date','ticker','state_id']].copy()
    for index,name in enumerate(GATE_COLUMNS):state_keys[name]=gate_x[:,index]
    if state_keys.groupby(['signal_date','ticker','state_id'],sort=False)[GATE_COLUMNS].nunique().to_numpy().max()!=1:
        raise ValueError('ACTION_LEAKAGE_IN_GATE_FEATURES')
    order=deterministic_order(frame)
    mean=gate_x.mean(axis=0);scale=gate_x.std(axis=0);scale[scale<1e-12]=1.
    target=frame.target_advantage.to_numpy(np.float64)
    target_scale=float(target.std())
    if target_scale<1e-12:target_scale=1.
    normalized=(gate_x-mean)/scale
    ranks=frame[RANK_COLUMNS].to_numpy(np.float64)
    normpath=OUT/f'{stage}_normalization.npz'
    np.savez(normpath,mean=mean,scale=scale,target_scale=np.array(target_scale))
    x=torch.tensor(normalized[order],dtype=torch.float32)
    r=torch.tensor(ranks[order],dtype=torch.float32)
    y=torch.tensor(target[order]/target_scale,dtype=torch.float32)
    torch.manual_seed(SEED)
    model=ConditionalGate()
    before={key:value.detach().clone() for key,value in model.state_dict().items()}
    optimizer=torch.optim.Adam(model.parameters(),lr=LEARNING_RATE,weight_decay=WEIGHT_DECAY)
    updates=0;logs=[]
    started=time.monotonic()
    for epoch in range(EPOCHS):
        loss_sum=0.;epoch_steps=0
        for offset in range(0,len(x),BATCH_SIZE):
            bx=x[offset:offset+BATCH_SIZE];br=r[offset:offset+BATCH_SIZE];by=y[offset:offset+BATCH_SIZE]
            prediction,_=model(bx,br)
            loss=F.mse_loss(prediction,by)
            if not torch.isfinite(loss):raise RuntimeError('NONFINITE_GATE_LOSS')
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
            loss_sum+=float(loss.detach())*len(bx);updates+=1;epoch_steps+=1
        row=dict(stage=stage,epoch=epoch+1,normalized_training_mse=loss_sum/len(x),
            optimizer_steps=epoch_steps,cumulative_steps=updates,
            raw_calibration=float(model.raw_calibration.detach()),positive_calibration=float(model.calibration().detach()))
        logs.append(row)
        with (OUT/f'{stage}_training.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    assert updates==EPOCHS*math.ceil(len(frame)/BATCH_SIZE)
    delta=float(sum((value-before[key]).square().sum().item() for key,value in model.state_dict().items())**.5)
    if not delta>0:raise RuntimeError('GATE_NO_PARAMETER_UPDATE')
    model.eval()
    with torch.no_grad():
        weights=model.proportions(torch.tensor(normalized,dtype=torch.float32)).double().numpy()
    positive_calibration=float(model.calibration().detach())
    output_scale=positive_calibration*target_scale
    prediction=np.sum(weights*ranks,axis=1)*output_scale
    modelpath=OUT/f'{stage}_gate.pt';torch.save(model.state_dict(),modelpath)
    # Fixed diagnostic: all original training rows, no candidate/test-based selection.
    variation=dict(weight_mean=weights.mean(axis=0).tolist(),weight_std=weights.std(axis=0).tolist(),
        weight_min=weights.min(axis=0).tolist(),weight_max=weights.max(axis=0).tolist(),
        largest_expert_range=float(np.ptp(weights,axis=0).max()),
        mean_distance_from_uniform=float(np.linalg.norm(weights-1/6,axis=1).mean()),
        max_simplex_sum_error=float(np.abs(weights.sum(axis=1)-1).max()),
        finite=bool(np.isfinite(weights).all()),strictly_positive=bool((weights>0).all()))
    same=state_keys[['signal_date','ticker','state_id']].copy()
    for index in range(6):same[f'w{index}']=weights[:,index]
    grouped=same.groupby(['signal_date','ticker','state_id'],sort=False)[[f'w{k}' for k in range(6)]]
    state_variation=grouped.max()-grouped.min()
    variation['max_within_same_state_action_difference']=float(state_variation.to_numpy().max())
    if variation['max_within_same_state_action_difference']>1e-7:raise RuntimeError('GATE_ACTION_DEPENDENT_WEIGHTS')
    if variation['max_simplex_sum_error']>2e-7:raise RuntimeError('GATE_SIMPLEX_FAILURE')
    if not np.all(prediction[frame.action.eq(0).to_numpy()]==0.):raise RuntimeError('GATE_NONZERO_EXIT_PREDICTION')
    for path,expected in sources.items():
        if sha(path)!=expected:raise RuntimeError(f'GATE_FROZEN_SOURCE_CHANGED:{path}')
    receipt=dict(status='PASS',specification=specification,stage=stage,fit_count=1,rows=len(frame),
        optimizer_steps=updates,epochs=EPOCHS,parameter_count=sum(p.numel() for p in model.parameters()),
        parameter_delta_l2=delta,loss_curve=logs,final_training_mse_original_units=float(np.mean((prediction-target)**2)),
        normalization_mean=mean.tolist(),normalization_scale=scale.tolist(),target_scale=target_scale,
        raw_calibration=float(model.raw_calibration.detach()),positive_calibration=positive_calibration,
        output_scale=output_scale,weight_diagnostics=variation,model_path=str(modelpath),model_sha256=sha(modelpath),
        normalization_path=str(normpath),normalization_sha256=sha(normpath),
        signal_first=str(pd.to_datetime(frame.signal_date).min().date()),signal_last=str(pd.to_datetime(frame.signal_date).max().date()),
        label_end_max=str(pd.to_datetime(frame.label_end_date).max().date()),
        max_base_fit_cutoff=str(pd.to_datetime(frame.base_fit_cutoff).max().date()),
        ordered_gate_matrix_sha256=array_sha(normalized[order]),ordered_rank_matrix_sha256=array_sha(ranks[order]),
        ordered_target_sha256=array_sha(target[order]),order_sha256=array_sha(order),
        fit_2026_rows=0,input_hashes_unchanged=True,seconds=time.monotonic()-started)
    write(OUT/f'{stage}_RECEIPT.json',receipt)
    return receipt


class GateModel:
    def __init__(self,stage='final',artifact_dir=None):
        if stage not in STAGES:raise ValueError('INVALID_GATE_STAGE')
        self.stage=stage;directory=Path(artifact_dir) if artifact_dir is not None else OUT
        self.receipt=json.loads((directory/f'{stage}_RECEIPT.json').read_text(encoding='utf-8'))
        path=directory/f'{stage}_gate.pt';normalization=directory/f'{stage}_normalization.npz'
        if (self.receipt['status']!='PASS' or self.receipt['stage']!=stage
            or self.receipt['label_end_max']>=STAGES[stage]
            or sha(path)!=self.receipt['model_sha256']
            or sha(normalization)!=self.receipt['normalization_sha256']):
            raise ValueError('GATE_CHECKPOINT_HASH_STAGE_OR_CLOCK_MISMATCH')
        loaded=np.load(normalization)
        self.mean=loaded['mean'];self.scale=loaded['scale'];self.target_scale=float(loaded['target_scale'])
        if self.mean.shape!=(5,) or self.scale.shape!=(5,) or not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or (self.scale<=0).any() or not self.target_scale>0:
            raise ValueError('INVALID_GATE_NORMALIZER')
        self.network=ConditionalGate()
        self.network.load_state_dict(torch.load(path,map_location='cpu',weights_only=True));self.network.eval()
        self.raw_calibration=float(self.network.raw_calibration.detach())
        self.positive_calibration=float(self.network.calibration().detach())
        self.output_scale=self.positive_calibration*self.target_scale
        if not self.output_scale>0 or not np.isfinite(self.output_scale):raise ValueError('INVALID_GATE_CALIBRATION')

    def predict(self,frame):
        if not len(frame):return np.empty(0),np.empty((0,6))
        features=_gate_features(frame)
        ranks=frame[RANK_COLUMNS].to_numpy(float)
        if ranks.shape!=(len(frame),6) or not np.isfinite(ranks).all():raise ValueError('INVALID_GATE_EXPERT_SCORES')
        x=torch.tensor((features-self.mean)/self.scale,dtype=torch.float32)
        with torch.no_grad():weights=self.network.proportions(x).double().numpy()
        score=np.sum(ranks*weights,axis=1)*self.output_scale
        return score,weights


def train():
    if (OUT/'TRAIN_RECEIPT.json').exists():raise RuntimeError('GATE_TRAINING_ALREADY_COMPLETE')
    receipts=[fit_stage(stage) for stage in STAGES]
    result=dict(status='PASS',fit_count=2,optimizer_steps=sum(r['optimizer_steps'] for r in receipts),
        parameter_count_each=103,fit_2026_rows=0,stages=receipts)
    write(OUT/'TRAIN_RECEIPT.json',result)
    print(json.dumps({'status':'PASS','fit_count':2,'optimizer_steps':result['optimizer_steps']}),flush=True)


if __name__=='__main__':train()
