"""One fixed 2023-only fresh MLP fit for genuinely temporal 2024 OOF logits."""
from pathlib import Path
import json
import time

import numpy as np
import pandas as pd
import torch

import neural

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'ensemble_artifacts'/'early_neural'
CUTOFF='2023-12-31'
SEED=20260928
EPOCHS=6


def load_early_panel(source):
    boundary=pd.Timestamp(CUTOFF)
    panel=pd.read_parquet(source,filters=[('signal_date','<=',boundary),('label_end_date','<=',boundary)])
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    panel['label_end_date']=pd.to_datetime(panel.label_end_date)
    if panel.empty or panel.signal_date.max()>boundary or panel.label_end_date.max()>boundary:
        raise RuntimeError('EARLY_DATA_OUTSIDE_2023')
    if panel.label_end_date.isna().any():raise RuntimeError('EARLY_LABEL_NOT_MATURE')
    if 'label_available' in panel and not panel.label_available.astype(bool).all():
        raise RuntimeError('EARLY_LABEL_NOT_AVAILABLE')
    return panel


def train():
    if OUT.exists() and any(OUT.iterdir()):raise RuntimeError('EARLY_NEURAL_OUTPUT_ALREADY_EXISTS')
    OUT.mkdir(parents=True,exist_ok=True)
    source=neural.SOURCE/'data/pre2026_joint_context.parquet'
    paths=dict(context=source,price=neural.PRICE,source_code=Path(__file__),
               reused_execution_source=Path(neural.__file__),base_contract=ROOT/'EXPERIMENT_CONTRACT.md',
               ensemble_contract=ROOT/'ENSEMBLE_CONTRACT.md')
    hashes={key:neural.sha(path) for key,path in paths.items()}
    panel=load_early_panel(source)
    spec=dict(input_paths={key:str(path) for key,path in paths.items()},input_sha256=hashes,
        source_code_sha256=hashes['source_code'],stage='early',method='direct',seed=SEED,epochs=EPOCHS,
        architecture=[len(neural.FEATURES)+3,32,16,1],feature_order=neural.FEATURES,
        fit_cutoff=CUTOFF,oof_prediction_year=2024,learning_rate=.0005,weight_decay=.001,
        train_cost_bps_per_side=10,max_positions=20,max_weight=.1,max_exposure=.95,
        capacity_fraction=.01,initial_capital_dollars=1_000_000.,risk_aversion=5,
        normalization='new 2023-only fit; no other-stage normalization read',
        initialization='fresh torch initialization; no existing weights read',
        selection='fixed six epochs and one seed; no OOF/test-based selection',
        observation='32 causal features plus actual filled position weight, cash weight, and holding flag',
        role='Predict 2024 OOF meta features; never updated on 2024 or later data')
    (OUT/'PRE_FIT_CONTRACT.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    mean,scale,norm=neural.fit_normalization(panel,CUTOFF)
    normalization=OUT/'early_normalization.npz'
    np.savez(normalization,mean=mean,scale=scale)
    market=neural.Market(panel,'2023-01-01',CUTOFF,mean,scale)
    if not market.days:raise RuntimeError('EMPTY_EARLY_MARKET')
    stage=dict(stage='early',cutoff=CUTOFF,normalization=norm,
        normalization_path=str(normalization),normalization_sha256=neural.sha(normalization),
        first_signal=market.days[0]['date'],last_signal=market.days[-1]['date'],
        last_execution_date=market.days[-1]['execution_date'],
        last_reward_end_date=market.days[-1]['reward_end_date'],
        consumed_price_max=market.price_date_max,market_days=len(market.days))
    torch.manual_seed(SEED);model=neural.JointPolicy()
    initial={key:value.detach().clone() for key,value in model.state_dict().items()}
    zero=OUT/'early_direct_zero.pt';torch.save(model.state_dict(),zero)
    optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
    logs=[]
    for epoch in range(EPOCHS):
        started=time.monotonic()
        info,records=market.episode(model,optimizer,'direct',SEED+epoch)
        row=dict(stage='early',method='direct',seed=SEED,epoch=epoch+1,seconds=time.monotonic()-started,**info)
        logs.append(row)
        with (OUT/'training.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    delta=float(sum((value-initial[key]).square().sum().item() for key,value in model.state_dict().items())**.5)
    updates=sum(row['updates'] for row in logs)
    if delta<=0 or updates<=0:raise RuntimeError('EARLY_NO_PARAMETER_UPDATES')
    path=OUT/'early_direct.pt';torch.save(model.state_dict(),path)
    episode=OUT/'early_direct_last_train_episode.parquet'
    pd.DataFrame(records).to_parquet(episode,index=False)
    artifact=dict(stage='early',method='direct',seed=SEED,path=str(path),sha256=neural.sha(path),
        zero_path=str(zero),zero_sha256=neural.sha(zero),initialization='fresh',epochs=EPOCHS,
        parameters=sum(p.numel() for p in model.parameters()),parameter_delta_l2=delta,
        actual_parameter_updates=updates,fit_signal_max=stage['last_signal'],
        fit_label_end_max=stage['last_reward_end_date'],consumed_price_max=market.price_date_max,
        normalization_sha256=neural.sha(normalization),last_episode_path=str(episode),last_episode_sha256=neural.sha(episode))
    if any(neural.sha(path)!=hashes[key] for key,path in paths.items()):
        raise RuntimeError('EARLY_INPUT_CHANGED_DURING_FIT')
    receipt=dict(status='FRESH_EARLY_NEURAL_TRAINING_COMPLETE',specification=spec,stages=[stage],
        artifacts=[artifact],logs=logs,fit_count=1,actual_parameter_updates=updates,
        training_signal_max=stage['last_signal'],training_label_end_max=stage['last_reward_end_date'],
        max_consumed_price_date=market.price_date_max,fit_2024_or_later_rows=0,fit_2026_rows=0,
        reused_weight_files=[],reused_normalization_files=[],input_sha256_unchanged=True)
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=receipt['status'],actual_parameter_updates=updates)),flush=True)


class EarlyNeuralAdapter(neural.NeuralAdapter):
    """The ordinary joint-policy inference API with 2023-only learned inputs."""
    def __init__(self,zero=False):
        self.method='direct';self.zero=zero;self.stage='early'
        a=np.load(OUT/'early_normalization.npz');self.mean=a['mean'];self.scale=a['scale']
        model=neural.JointPolicy()
        path=OUT/('early_direct_zero.pt' if zero else 'early_direct.pt')
        model.load_state_dict(torch.load(path,weights_only=True,map_location='cpu'))
        model.eval();self.models=[model]


if __name__=='__main__':train()
