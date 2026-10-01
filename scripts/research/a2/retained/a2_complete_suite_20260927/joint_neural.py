"""Joint stock selection and continuous portfolio policy learning before 2026.

Direct differentiable one-period portfolio utility and episodic REINFORCE
share the same observable state and a share/cash next-open simulator. Hard
TOP20 is inside training. No independent return-to-weight model is fitted.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
import pandas as pd
import torch
from torch import nn

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'joint_neural_v3'
FEATURES=json.loads((ROOT/'models/model_registry.json').read_text(encoding='utf-8'))['feature_order']
PRICE=ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
SEEDS=(20260927,20260928)
MAX_WEIGHT=.10
MAX_EXPOSURE=.95
COST=.001
DIRECT_EPOCHS=6
RL_EPOCHS=4
torch.set_num_threads(2)

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

class JointPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(len(FEATURES)+3,32),nn.Tanh(),nn.Linear(32,16),nn.Tanh(),nn.Linear(16,1))
        nn.init.constant_(self.net[-1].bias,-.7)
    def forward(self,x):return self.net(x).flatten()

def project(logits, training=False, upper=None):
    n=len(logits)
    proposal=.1*torch.sigmoid(logits)
    if upper is not None:proposal=torch.minimum(proposal,upper.to(proposal.dtype))
    keep=torch.zeros_like(proposal)
    if n:keep[torch.topk(logits,min(20,n)).indices]=1.
    gated=torch.where(proposal>=.02,proposal,torch.zeros_like(proposal))
    if training:gated=proposal+(gated-proposal).detach()
    w=gated*keep
    w=w*torch.clamp(torch.tensor(.95,dtype=w.dtype)/w.sum().clamp_min(1e-12),max=1.)
    return w

class Market:
    def __init__(self,panel,first,last,mean,scale):
        px=pd.read_parquet(PRICE,columns=['ticker','trade_date','open','close'])
        px['trade_date']=pd.to_datetime(px.trade_date)
        assert px.trade_date.max()<pd.Timestamp('2026-01-01')
        calendar=pd.DatetimeIndex(sorted(px.loc[px.ticker.eq('QQQ'),'trade_date'].unique()))
        tickers=sorted(panel.ticker.astype(str).unique())
        self.tickers=tickers; self.lookup={t:i for i,t in enumerate(tickers)}
        ow=px.pivot(index='trade_date',columns='ticker',values='open').reindex(index=calendar,columns=tickers)
        cw=px.pivot(index='trade_date',columns='ticker',values='close').reindex(index=calendar,columns=tickers)
        close_marks=cw.ffill()
        open_marks=ow.where(ow.gt(0),close_marks.shift(1))
        self.days=[]
        groups={pd.Timestamp(d):g for d,g in panel.groupby('signal_date',sort=True)}
        for i,d in enumerate(calendar[:-2]):
            if d<pd.Timestamp(first) or calendar[i+2]>pd.Timestamp(last):continue
            g=groups.get(d,panel.iloc[:0])
            ids=np.asarray([self.lookup[t] for t in g.ticker],int)
            x=np.clip((g[FEATURES].to_numpy(float)-mean)/scale,-8,8)
            valid=np.isfinite(x).all(axis=1)
            ids=ids[valid];x=x[valid];g=g.iloc[np.flatnonzero(valid)]
            def arr(v):return torch.tensor(np.nan_to_num(v,nan=0.),dtype=torch.float64)
            op=ow.iloc[i+1].to_numpy(float)
            self.days.append(dict(date=str(d.date()),ids=torch.tensor(ids),x=torch.tensor(x,dtype=torch.float32),
                eligible=torch.tensor(g.new_buy_eligible.to_numpy(bool)),
                close=arr(close_marks.iloc[i].to_numpy(float)),
                opening=arr(open_marks.iloc[i+1].to_numpy(float)),
                ending=arr(open_marks.iloc[i+2].to_numpy(float)),
                fill=torch.tensor(np.isfinite(op)&(op>0)),
                vol=torch.tensor(np.maximum(g.realized_vol_20d.to_numpy(float),.01),dtype=torch.float64)))

    def episode(self,model,optimizer=None,method='direct',noise_seed=0):
        generator=torch.Generator().manual_seed(noise_seed)
        units=torch.zeros(len(self.tickers),dtype=torch.float64)
        cash=torch.tensor(1.,dtype=torch.float64)
        losses=[];rewards=[];records=[];log_probs=[];pg_rewards=[];updates=0
        for d in self.days:
            held=units>0
            if any(bool(torch.any(held&(d[k]<=0))) for k in ('close','opening','ending')):
                raise RuntimeError('UNKNOWN_HELD_TRAINING_PRICE: reject reward rather than mark at zero')
            closevalues=units*d['close'];closenav=cash+closevalues.sum()
            if not torch.isfinite(closenav) or float(closenav)<=0:raise RuntimeError('TRAIN_CLOSE_NAV_INVALID')
            current=closevalues/closenav
            observable=d['eligible']|(units[d['ids']]>0)
            ids=d['ids'][observable];n=len(ids)
            upper=torch.where(d['eligible'][observable],torch.tensor(.1),current[ids].clamp(max=.1)).float()
            global_w=torch.zeros(len(self.tickers),dtype=torch.float64)
            if n:
                obs=torch.cat([d['x'][observable],current[ids,None].float(),
                    torch.full((n,1),float(cash/closenav)),(units[ids,None]>0).float()],dim=1)
                logits=model(obs)
                lp=None
                if optimizer is not None:
                    noise=torch.randn(logits.shape,generator=generator)*(.35 if method=='rl' else .10)
                    if method=='rl':
                        dist=torch.distributions.Normal(logits,.35)
                        raw=logits.detach()+noise
                        lp=dist.log_prob(raw).mean()
                        action=project(raw,False,upper)
                    else:action=project(logits+noise,True,upper)
                else:action=project(logits,False,upper)
                global_w=global_w.index_copy(0,ids,action.double())
            else:lp=None
            opening=d['opening']
            prevalues=units*opening
            pre_nav=cash+prevalues.sum()
            desired=global_w*pre_nav
            sells=torch.relu(prevalues-desired)*d['fill']
            buy_eligible=torch.zeros(len(self.tickers),dtype=torch.bool)
            buy_eligible[d['ids']]=d['eligible']
            requests=torch.relu(desired-prevalues)*d['fill']*buy_eligible
            available=cash+sells.sum()*(1-COST)
            scale=torch.clamp(available/(requests.sum()*(1+COST)).clamp_min(1e-12),max=1.)
            buys=requests*scale
            fees=(sells.sum()+buys.sum())*COST
            new_cash=cash+sells.sum()-buys.sum()-fees
            new_units=units+(buys-sells)/opening.clamp_min(1e-12)
            if bool(torch.any((new_units>0)&(d['ending']<=0))):
                raise RuntimeError('UNKNOWN_END_TRAINING_PRICE: reject reward rather than mark at zero')
            ending_nav=new_cash+(new_units*d['ending']).sum()
            # Mature future prices appear only in reward/execution, never obs.
            reward=torch.log((ending_nav/pre_nav).clamp_min(1e-12))
            risk=(global_w[ids].square()*d['vol'][observable].square()).sum() if n else torch.tensor(0.)
            utility=reward-5*risk
            if optimizer is not None and n:
                if method=='direct':
                    loss=-100*utility
                    optimizer.zero_grad();loss.backward()
                    grad=float(torch.nn.utils.clip_grad_norm_(model.parameters(),2.))
                    optimizer.step();updates+=1;losses.append(float(loss.detach()))
                else:
                    log_probs.append(lp);pg_rewards.append(float(utility.detach()))
                    if len(log_probs)>=32:
                        self._reinforce(log_probs,pg_rewards,optimizer,model)
                        updates+=1;log_probs=[];pg_rewards=[]
            records.append(dict(signal_date=d['date'],next_open_nav=float(pre_nav.detach()),
                reward=float(reward.detach()),risk_penalty=float((5*risk).detach()),fees=float(fees.detach()),
                target_exposure=float(global_w.sum().detach()),target_names=int((global_w>0).sum()),
                fill_missing_held=int(((units>0)&~d['fill']).sum())))
            rewards.append(float(reward.detach()))
            # Truncated-gradient online state; no gradient through earlier dates.
            units=new_units.detach();cash=new_cash.detach()
            if float(cash)<-1e-8 or not torch.isfinite(units).all():raise RuntimeError('TRAIN_CASH_OR_UNITS')
        if optimizer is not None and log_probs:
            self._reinforce(log_probs,pg_rewards,optimizer,model);updates+=1
        return dict(log_reward_sum=float(np.sum(rewards)),reward_nav_proxy=float(np.exp(np.sum(rewards))),
            updates=updates,days=len(records),loss_mean=float(np.mean(losses)) if losses else None,
            max_reward_signal=records[-1]['signal_date'] if records else None),records

    @staticmethod
    def _reinforce(log_probs,rewards,optimizer,model):
        result=[];future=0.
        for r in rewards[::-1]:future=r+.97*future;result.append(future)
        advantages=torch.tensor(result[::-1],dtype=torch.float32)
        advantages=(advantages-advantages.mean())/(advantages.std(unbiased=False)+1e-6)
        loss=-(torch.stack(log_probs)*advantages).mean()
        optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),2.);optimizer.step()

def train():
    OUT.mkdir(exist_ok=True)
    if (OUT/'TRAIN_RECEIPT.json').exists():raise RuntimeError('JOINT_NEURAL_ALREADY_TRAINED')
    source=ROOT/'data/pre2026_joint_context.parquet'
    if not source.exists():source=ROOT/'data/pre2026_joint.parquet'
    panel=pd.read_parquet(source)
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    assert panel.signal_date.max()<pd.Timestamp('2026-01-01')
    assert pd.to_datetime(panel.label_end_date.dropna()).max()<pd.Timestamp('2026-01-01')
    spec=dict(source=str(source),source_sha256=sha(source),price_source_sha256=sha(PRICE),
        direct_epochs=DIRECT_EPOCHS,rl_epochs=RL_EPOCHS,seeds=SEEDS,feature_order=FEATURES,
        architecture=[len(FEATURES)+3,32,16,1],train_cost_bps_per_side=10,max_positions=20,
        max_weight=.1,max_exposure=.95,zero_threshold=.02,learning_rate=.0005,
        risk_aversion=5,rl_gamma=.97,rl_block_steps=32,
        selection='fixed epochs and seeds; validation diagnostic only; no 2026 selection',
        correction='v1 forced old-quarter positions to exit; v2 permits learned holding but only capped target weights. v3 additionally blocks actual buy orders for old-quarter holdings, because an overnight relative loss can otherwise create a mechanical top-up. All prior artifacts retained and excluded from comparison.',
        limitations=['Direct gradient is one-step utility with detached historical portfolio state.',
        'Hard TOP20 uses gradient through selected proposals; exploration noise during training.',
        'Training has no volume-capacity constraint; strict evaluator adds capacity and audits mismatches.',
        'Price-index units; missing execution price blocks fills, last known close marks valuation.',
        'Reward NAV proxy is sum of one-period log rewards; final comparison uses independent ledger.'])
    (OUT/'PRE_FIT_CONTRACT.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    logs=[];artifacts=[]
    for stage,last in [('validation','2024-12-31'),('final','2025-12-31')]:
        fitrows=panel[panel.signal_date.le(last)]
        fitrows=fitrows[np.isfinite(fitrows[FEATURES].to_numpy(float)).all(axis=1)]
        x=fitrows[FEATURES].to_numpy(float)
        mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-12]=1.
        np.savez(OUT/f'{stage}_normalization.npz',mean=mean,scale=scale)
        market=Market(panel,'2023-01-01',last,mean,scale)
        validation=Market(panel,'2025-01-01','2025-12-31',mean,scale) if stage=='validation' else None
        for method,seeds,epochs in [('direct',[SEEDS[0]],DIRECT_EPOCHS),('rl',SEEDS,RL_EPOCHS)]:
            for seed in seeds:
                torch.manual_seed(seed);model=JointPolicy()
                zero=OUT/f'{stage}_{method}_{seed}_zero.pt';torch.save(model.state_dict(),zero)
                optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
                for epoch in range(epochs):
                    t=time.monotonic()
                    info,_=market.episode(model,optimizer,method,seed+epoch)
                    row=dict(stage=stage,method=method,seed=seed,epoch=epoch+1,seconds=time.monotonic()-t,**info)
                    logs.append(row)
                    with (OUT/'training.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
                    print(json.dumps(row),flush=True)
                file=OUT/f'{stage}_{method}_{seed}.pt';torch.save(model.state_dict(),file)
                artifacts.append(dict(stage=stage,method=method,seed=seed,path=str(file),sha256=sha(file),
                    parameters=sum(p.numel() for p in model.parameters())))
                if validation is not None:
                    with torch.no_grad():info,records=validation.episode(model)
                    pd.DataFrame(records).to_parquet(OUT/f'validation_{method}_{seed}_2025.parquet',index=False)
                    logs.append(dict(stage='2025_validation',method=method,seed=seed,**info))
    receipt=dict(specification=spec,artifacts=artifacts,logs=logs,
        actual_parameter_updates=sum(v.get('updates',0) for v in logs if v.get('stage')!='2025_validation'),
        training_signal_max=str(panel.signal_date.max().date()),
        training_label_end_max=str(pd.to_datetime(panel.label_end_date.dropna()).max().date()),
        max_consumed_price_date='2025-12-31',fit_2026_rows=0,status='JOINT_TRAINING_COMPLETE')
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')

class NeuralAdapter:
    def __init__(self,method='direct',zero=False,stage='final'):
        a=np.load(OUT/f'{stage}_normalization.npz');self.mean=a['mean'];self.scale=a['scale']
        self.models=[]
        for seed in ([SEEDS[0]] if method=='direct' else SEEDS):
            model=JointPolicy();suffix='_zero' if zero else ''
            model.load_state_dict(torch.load(OUT/f'{stage}_{method}_{seed}{suffix}.pt',weights_only=True,map_location='cpu'))
            model.eval();self.models.append(model)
    def __call__(self,day,weights,cash):
        if day.empty:return {}
        if 'new_buy_eligible' in day:day=day[day.new_buy_eligible.astype(bool)|day.ticker.map(weights).fillna(0).gt(0)]
        if day.empty:return {}
        day=day.sort_values('ticker',kind='stable')
        x=np.clip((day[FEATURES].to_numpy(float)-self.mean)/self.scale,-8,8)
        old=np.array([weights.get(t,0) for t in day.ticker])
        obs=torch.tensor(np.column_stack([x,old,np.repeat(cash,len(day)),old>0]),dtype=torch.float32)
        upper=torch.tensor(np.where(day.new_buy_eligible.to_numpy(bool),.1,np.minimum(old,.1)),dtype=torch.float32)
        with torch.no_grad():w=torch.stack([project(m(obs),upper=upper) for m in self.models]).mean(dim=0).numpy()
        # Ensemble may have up to 40 names; enforce the common account constraint.
        keep=np.argsort(-w,kind='stable')[:20];mask=np.zeros(len(w));mask[keep]=1;w*=mask
        if w.sum()>.95:w*=.95/w.sum()
        return {str(t):float(v) for t,v in zip(day.ticker,w) if v>1e-8}

if __name__=='__main__':train()
