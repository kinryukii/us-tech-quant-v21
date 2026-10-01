"""One frozen development MLP fit through 2023 for causal 2024 stacking OOF.

This wrapper leaves the main neural implementation and contract immutable.
It uses the same architecture/environment and fixed training budget, while
fitting a separate 2023-only normalizer and freshly initialized model.
"""
from pathlib import Path
import json
import time
import numpy as np
import pandas as pd
import torch

from neural import JointPolicy, Market, fit_normalization, sha, FEATURES, SOURCE, PRICE

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'development_neural_artifacts'
SEED=20260928
LAST='2023-12-31'
EPOCHS=6


def train():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError('DEVELOPMENT_NEURAL_OUTPUT_ALREADY_EXISTS')
    OUT.mkdir(exist_ok=True)
    source=SOURCE/'data/pre2026_joint_context.parquet'
    inputs={'context':source,'price':PRICE,'main_code':ROOT/'neural.py',
        'wrapper':Path(__file__),'main_contract':ROOT/'EXPERIMENT_CONTRACT.md'}
    frozen={key:sha(path) for key,path in inputs.items()}
    spec=dict(purpose='Development fit through 2023 for genuine 2024 out-of-fold ensemble features',
        method='direct',seed=SEED,epochs=EPOCHS,cutoff=LAST,architecture=[35,32,16,1],
        feature_order=FEATURES,learning_rate=.0005,weight_decay=.001,cost_bps=10,
        buy_capacity_fraction=.01,initial_capital_dollars=1_000_000,max_positions=20,
        input_paths={k:str(p) for k,p in inputs.items()},input_sha256=frozen,
        label_rule='signal_date and label_end_date <= 2023-12-31; next-open reward must mature by cutoff',
        training_budget='Single seed, six epochs, no search, no 2024/2025/2026 score-based adjustments',
        role='OOF feature generator only; not a candidate selected using test data')
    (OUT/'PRE_FIT_CONTRACT.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    panel=pd.read_parquet(source)
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    panel['label_end_date']=pd.to_datetime(panel.label_end_date)
    if panel.signal_date.max()>=pd.Timestamp('2026-01-01') or panel.label_end_date.max()>=pd.Timestamp('2026-01-01'):
        raise RuntimeError('DEVELOPMENT_SOURCE_CONTAINS_2026')
    mean,scale,evidence=fit_normalization(panel,LAST)
    normpath=OUT/'development_normalization.npz'
    np.savez(normpath,mean=mean,scale=scale)
    market=Market(panel,'2023-01-01',LAST,mean,scale)
    if not market.days:raise RuntimeError('EMPTY_DEVELOPMENT_MARKET')
    torch.manual_seed(SEED)
    model=JointPolicy()
    initial={k:v.detach().clone() for k,v in model.state_dict().items()}
    zero=OUT/f'development_direct_{SEED}_zero.pt'
    torch.save(model.state_dict(),zero)
    optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
    logs=[]
    for epoch in range(EPOCHS):
        started=time.monotonic()
        info,records=market.episode(model,optimizer,'direct',SEED+epoch)
        row=dict(stage='development',method='direct',seed=SEED,epoch=epoch+1,
            seconds=time.monotonic()-started,**info)
        logs.append(row)
        with (OUT/'training.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    path=OUT/f'development_direct_{SEED}.pt'
    torch.save(model.state_dict(),path)
    records_path=OUT/f'development_direct_{SEED}_last_train_episode.parquet'
    pd.DataFrame(records).to_parquet(records_path,index=False)
    delta=float(sum((v-initial[k]).square().sum().item() for k,v in model.state_dict().items())**.5)
    updates=sum(row['updates'] for row in logs)
    if not delta>0 or updates<=0:raise RuntimeError('NO_DEVELOPMENT_UPDATES')
    if any(sha(path)!=frozen[key] for key,path in inputs.items()):
        raise RuntimeError('DEVELOPMENT_INPUT_CHANGED')
    receipt=dict(specification=spec,status='DEVELOPMENT_MLP_TRAINING_COMPLETE',logs=logs,
        normalization=evidence,normalization_path=str(normpath),normalization_sha256=sha(normpath),
        path=str(path),sha256=sha(path),zero_path=str(zero),zero_sha256=sha(zero),
        last_episode_path=str(records_path),last_episode_sha256=sha(records_path),
        parameters=sum(p.numel() for p in model.parameters()),parameter_delta_l2=delta,
        actual_parameter_updates=updates,fit_count=1,fit_2024_rows=0,fit_2025_rows=0,fit_2026_rows=0,
        first_signal=market.days[0]['date'],training_signal_max=market.days[-1]['date'],
        training_label_end_max=market.days[-1]['reward_end_date'],max_consumed_price_date=market.price_date_max,
        input_sha256_unchanged=True)
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'actual_parameter_updates':updates}),flush=True)


class DevelopmentNeuralAdapter:
    def __init__(self):
        normalization=np.load(OUT/'development_normalization.npz')
        self.mean=normalization['mean'];self.scale=normalization['scale']
        model=JointPolicy()
        model.load_state_dict(torch.load(OUT/f'development_direct_{SEED}.pt',weights_only=True,map_location='cpu'))
        model.eval();self.models=[model]


if __name__=='__main__':train()
