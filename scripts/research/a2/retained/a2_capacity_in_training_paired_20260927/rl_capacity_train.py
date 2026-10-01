"""Paired RL capacity-in-training arm; the original training branch is read only.

This is a deliberately small fork of qualification_holdings_v1/joint_neural_v2.py.
The treatment is the execution-day BUY limit from signal-day raw-dollar ADV.
Everything else, including the target-based risk penalty, stays matched.
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
SOURCE=ROOT.parent/'a2_latest_effective_joint_20260927'
REFERENCE=ROOT.parent/'a2_qualification_holdings_v1_20260927'
REFERENCE_ARTIFACTS=REFERENCE/'neural_artifacts'
OUT=ROOT/'rl_capacity_artifacts'
FEATURES=json.loads((SOURCE/'models/model_registry.json').read_text(encoding='utf-8'))['feature_order']
PRICE=ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
SEEDS=(20260927,20260928)
MAX_WEIGHT=.10
MAX_EXPOSURE=.95
COST=.001
RL_EPOCHS=4
CAPACITY_FRACTION=.01
INITIAL_CASH_DOLLARS=1_000_000.
torch.set_num_threads(2)

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

class JointPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.net=nn.Sequential(nn.Linear(len(FEATURES)+3,32),nn.Tanh(),nn.Linear(32,16),nn.Tanh(),nn.Linear(16,1))
        nn.init.constant_(self.net[-1].bias,-.7)
    def forward(self,x):return self.net(x).flatten()

def project(logits, training=False, upper=None, max_names=20, max_exposure=.95):
    """Only signal-known residual capacity enters policy projection."""
    if not 0 <= max_names <= 20 or not 0 <= max_exposure <= .95 + 1e-10:
        raise ValueError('INVALID_SIGNAL_CAPACITY')
    n=len(logits)
    proposal=.1*torch.sigmoid(logits)
    if upper is not None:proposal=torch.minimum(proposal,upper.to(proposal.dtype))
    keep=torch.zeros_like(proposal)
    if n and max_names:keep[torch.topk(logits,min(max_names,n)).indices]=1.
    gated=torch.where(proposal>=.02,proposal,torch.zeros_like(proposal))
    if training:gated=proposal+(gated-proposal).detach()
    w=gated*keep
    w=w*torch.clamp(torch.tensor(max_exposure,dtype=w.dtype)/w.sum().clamp_min(1e-12),max=1.)
    return w


def execute_targets(units, cash, opening, fill, global_w, locked, buy_eligible,
                    signal_adv_dollars):
    """Execute with the ledger's signal-day 1% ADV cap on each BUY order.

    ``cash`` and ``units`` are in initial-capital-normalized account units.
    ADV is in raw dollars; divide its dollar cap by the evaluator's frozen
    $1,000,000 initial capital. Sells remain unconstrained by ADV.
    """
    prevalues=units*opening
    pre_nav=cash+prevalues.sum()
    desired=global_w*pre_nav
    sells=torch.relu(prevalues-desired)*fill*(~locked)
    after_sells=units-sells/opening.clamp_min(1e-12)
    uncapped_requests=torch.relu(desired-prevalues)*fill*buy_eligible*(~locked)
    adv=signal_adv_dollars.to(dtype=uncapped_requests.dtype)
    caps=torch.where(torch.isfinite(adv)&(adv>0),
        adv.clamp_min(0.)*(CAPACITY_FRACTION/INITIAL_CASH_DOLLARS),
        torch.zeros_like(adv))
    requests=torch.minimum(uncapped_requests,caps)
    cap_limited=(uncapped_requests.detach()>requests.detach()+1e-12)
    reserved_names=after_sells.detach()>1e-12
    admission=torch.ones(len(units),dtype=torch.bool)
    blocked=0
    candidates=torch.nonzero((requests.detach()>1e-12)&~reserved_names).flatten()
    order=candidates[torch.argsort(global_w.detach()[candidates],descending=True,stable=True)]
    for idx in order.tolist():
        if int(reserved_names.sum())>=20:
            admission[idx]=False;blocked+=1
        else:reserved_names[idx]=True
    requests=requests*admission
    available=cash+sells.sum()*(1-COST)
    scale=torch.clamp(available/(requests.sum()*(1+COST)).clamp_min(1e-12),max=1.)
    buys=requests*scale
    fees=(sells.sum()+buys.sum())*COST
    new_cash=cash+sells.sum()-buys.sum()-fees
    new_units=units+(buys-sells)/opening.clamp_min(1e-12)
    new_units=torch.where((~locked)&(new_units.detach().abs()<1e-12),torch.zeros_like(new_units),new_units)
    if int((new_units.detach()>1e-12).sum())>20:raise RuntimeError('TRAIN_ACTUAL_NAMES_OVER_20')
    if not torch.equal(new_units[locked].detach(),units[locked].detach()):
        raise RuntimeError('MISSING_DECISION_UNITS_CHANGED')
    cap_info=dict(cap_limited_orders=int(cap_limited.sum()),
        requested_buy_notional=float(uncapped_requests.detach().sum()),
        allowed_buy_notional=float(requests.detach().sum()),
        filled_buy_notional=float(buys.detach().sum()))
    return new_units,new_cash,fees,pre_nav,blocked,cap_info

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
            adv=np.zeros(len(tickers),dtype=float)
            adv[ids]=g.avg_dollar_volume_20d.to_numpy(float)
            self.days.append(dict(date=str(d.date()),ids=torch.tensor(ids),x=torch.tensor(x,dtype=torch.float32),
                eligible=torch.tensor(g.new_buy_eligible.to_numpy(bool)),
                close=arr(close_marks.iloc[i].to_numpy(float)),
                signal_price_usable=torch.tensor(np.isfinite(cw.iloc[i].to_numpy(float))&(cw.iloc[i].to_numpy(float)>0)),
                opening=arr(open_marks.iloc[i+1].to_numpy(float)),
                ending=arr(open_marks.iloc[i+2].to_numpy(float)),
                fill=torch.tensor(np.isfinite(op)&(op>0)),
                signal_adv_dollars=arr(adv),
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
            input_mask=torch.zeros(len(self.tickers),dtype=torch.bool)
            input_mask[d['ids'][observable]]=True
            locked=held&(~input_mask|~d['signal_price_usable'])
            observable=observable&(~locked[d['ids']])
            ids=d['ids'][observable];n=len(ids)
            reserved_slots=int(locked.sum())
            reserved_weight=float(current[locked].sum())
            free_slots=max(0,20-reserved_slots)
            free_exposure=max(0.,MAX_EXPOSURE-reserved_weight)
            upper=torch.where(d['eligible'][observable],torch.tensor(.1),current[ids].clamp(max=.1)).float()
            global_w=torch.where(locked,current,torch.zeros_like(current))
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
                        action=project(raw,False,upper,free_slots,free_exposure)
                    else:action=project(logits+noise,True,upper,free_slots,free_exposure)
                else:action=project(logits,False,upper,free_slots,free_exposure)
                global_w=global_w.index_copy(0,ids,action.double())
            else:lp=None
            opening=d['opening']
            buy_eligible=torch.zeros(len(self.tickers),dtype=torch.bool)
            buy_eligible[d['ids']]=d['eligible']
            new_units,new_cash,fees,pre_nav,blocked_new,cap_info=execute_targets(
                units,cash,opening,d['fill'],global_w,locked,buy_eligible,d['signal_adv_dollars'])
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
                reserved_missing_or_restricted_names=reserved_slots,reserved_weight=reserved_weight,
                actual_names=int((new_units.detach()>1e-12).sum()),new_buys_blocked_actual_names=blocked_new,
                fill_missing_held=int(((units>0)&~d['fill']).sum()),**cap_info))
            rewards.append(float(reward.detach()))
            # Truncated-gradient online state; no gradient through earlier dates.
            units=new_units.detach();cash=new_cash.detach()
            if float(cash)<-1e-8 or not torch.isfinite(units).all():raise RuntimeError('TRAIN_CASH_OR_UNITS')
        if optimizer is not None and log_probs:
            self._reinforce(log_probs,pg_rewards,optimizer,model);updates+=1
        return dict(log_reward_sum=float(np.sum(rewards)),reward_nav_proxy=float(np.exp(np.sum(rewards))),
            updates=updates,days=len(records),loss_mean=float(np.mean(losses)) if losses else None,
            max_actual_names=max((r['actual_names'] for r in records),default=0),
            reserved_holding_days=sum(r['reserved_missing_or_restricted_names']>0 for r in records),
            reserved_position_days=sum(r['reserved_missing_or_restricted_names'] for r in records),
            execution_capacity_blocks=sum(r['new_buys_blocked_actual_names'] for r in records),
            adv_limited_buy_orders=sum(r['cap_limited_orders'] for r in records),
            requested_buy_notional=sum(r['requested_buy_notional'] for r in records),
            allowed_buy_notional=sum(r['allowed_buy_notional'] for r in records),
            filled_buy_notional=sum(r['filled_buy_notional'] for r in records),
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
    binding=json.loads((ROOT/'RL_PREFIT_BINDING.json').read_text(encoding='utf-8'))
    for relative,expected in binding['sha256'].items():
        path=ROOT.parent/relative
        if sha(path)!=expected:raise RuntimeError(f'READ_ONLY_SOURCE_DRIFT: {path}')
    if OUT.exists() and any(OUT.iterdir()):raise RuntimeError('CAPACITY_RL_OUTPUT_ALREADY_EXISTS')
    OUT.mkdir(exist_ok=True)
    source=SOURCE/'data/pre2026_joint_context.parquet'
    if not source.exists():source=SOURCE/'data/pre2026_joint.parquet'
    panel=pd.read_parquet(source)
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    assert panel.signal_date.max()<pd.Timestamp('2026-01-01')
    assert pd.to_datetime(panel.label_end_date.dropna()).max()<pd.Timestamp('2026-01-01')
    if (panel.avg_dollar_volume_20d.isna()|panel.avg_dollar_volume_20d.le(0)).any():
        raise RuntimeError('NONPOSITIVE_PRE2026_SIGNAL_ADV')
    original=json.loads((REFERENCE_ARTIFACTS/'PRE_FIT_CONTRACT.json').read_text(encoding='utf-8'))
    if original['source_sha256']!=sha(source) or original['price_source_sha256']!=sha(PRICE):
        raise RuntimeError('ORIGINAL_RL_INPUT_DRIFT')
    if original['seeds']!=list(SEEDS) or original['rl_epochs']!=RL_EPOCHS or original['feature_order']!=FEATURES:
        raise RuntimeError('ORIGINAL_RL_SPEC_DRIFT')
    spec=dict(source=str(source),source_sha256=sha(source),price_source_sha256=sha(PRICE),
        rl_epochs=RL_EPOCHS,seeds=SEEDS,feature_order=FEATURES,
        architecture=[len(FEATURES)+3,32,16,1],train_cost_bps_per_side=10,max_positions=20,
        max_weight=.1,max_exposure=.95,zero_threshold=.02,learning_rate=.0005,
        risk_aversion=5,rl_gamma=.97,rl_block_steps=32,
        selection='fixed epochs and seeds; validation diagnostic only; no 2026 selection',
        universe_rule=original['universe_rule'],
        policy_version='qualification_holdings_v1_rl_capacity_paired',source_code_sha256=sha(Path(__file__)),
        reference_training_code_sha256=sha(REFERENCE/'joint_neural_v2.py'),
        reference_contract_sha256=sha(REFERENCE/'VERSION_CONTRACT.md'),
        reference_pre_fit_sha256=sha(REFERENCE_ARTIFACTS/'PRE_FIT_CONTRACT.json'),
        reference_model_sha256={f'{stage}_{seed}':sha(REFERENCE_ARTIFACTS/f'{stage}_rl_{seed}.pt')
            for stage in ('validation','final') for seed in SEEDS},
        capacity_fraction=CAPACITY_FRACTION,capacity_side='BUY',
        initial_capital_dollars=INITIAL_CASH_DOLLARS,
        capacity_adv_source='unscaled signal-day avg_dollar_volume_20d in pre2026_joint_context',
        normalizers='reuse original validation/final normalization without refitting',
        changed_training_mechanism='cap each buy request before cash scaling, then feed actual units, cash and NAV reward into next state',
        unchanged_training_mechanism='same network, zero starts, exploration, optimizer, risk penalty, slots, weights, fees and reward horizon',
        limitations=['Signal-day raw-dollar ADV times 1% limits index-coordinate notional; this is the original evaluation proxy.',
        'Target-weight volatility penalty is held fixed to isolate the capacity treatment.',
        'Historical 2025 validation and 2026 diagnostics have been observed before this design; neither is fresh blind confirmation.'])
    (OUT/'PRE_FIT_CONTRACT.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    logs=[];artifacts=[]
    for stage,last in [('validation','2024-12-31'),('final','2025-12-31')]:
        normalization=REFERENCE_ARTIFACTS/f'{stage}_normalization.npz'
        original_normalization=np.load(normalization)
        mean=original_normalization['mean'];scale=original_normalization['scale']
        if not np.isfinite(mean).all() or not np.isfinite(scale).all() or (scale<=0).any():
            raise RuntimeError('INVALID_REFERENCE_NORMALIZATION')
        market=Market(panel,'2023-01-01',last,mean,scale)
        validation=Market(panel,'2025-01-01','2025-12-31',mean,scale) if stage=='validation' else None
        for method,seeds,epochs in [('rl',SEEDS,RL_EPOCHS)]:
            for seed in seeds:
                torch.manual_seed(seed);model=JointPolicy()
                zero=REFERENCE_ARTIFACTS/f'{stage}_{method}_{seed}_zero.pt'
                reference_zero=torch.load(zero,weights_only=True,map_location='cpu')
                if not all(torch.equal(v,reference_zero[k]) for k,v in model.state_dict().items()):
                    raise RuntimeError('PAIRED_INITIALIZATION_DRIFT')
                optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
                for epoch in range(epochs):
                    t=time.monotonic()
                    info,train_records=market.episode(model,optimizer,method,seed+epoch)
                    row=dict(stage=stage,method=method,seed=seed,epoch=epoch+1,seconds=time.monotonic()-t,**info)
                    logs.append(row)
                    with (OUT/'training.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
                    print(json.dumps(row),flush=True)
                pd.DataFrame(train_records).to_parquet(OUT/f'{stage}_{method}_{seed}_last_train_episode.parquet',index=False)
                file=OUT/f'{stage}_{method}_{seed}.pt';torch.save(model.state_dict(),file)
                artifacts.append(dict(stage=stage,method=method,seed=seed,path=str(file),sha256=sha(file),
                    parameters=sum(p.numel() for p in model.parameters()),reference_zero_sha256=sha(zero),
                    reference_normalization_sha256=sha(normalization)))
                if validation is not None:
                    with torch.no_grad():info,records=validation.episode(model)
                    pd.DataFrame(records).to_parquet(OUT/f'validation_{method}_{seed}_2025.parquet',index=False)
                    logs.append(dict(stage='2025_validation',method=method,seed=seed,**info))
    if any(sha(ROOT.parent/relative)!=expected for relative,expected in binding['sha256'].items()):
        raise RuntimeError('READ_ONLY_SOURCE_DRIFT_AFTER_FIT')
    receipt=dict(specification=spec,artifacts=artifacts,logs=logs,
        actual_parameter_updates=sum(v.get('updates',0) for v in logs if v.get('stage')!='2025_validation'),
        training_signal_max=str(panel.signal_date.max().date()),
        training_label_end_max=str(pd.to_datetime(panel.label_end_date.dropna()).max().date()),
        max_consumed_price_date='2025-12-31',fit_2026_rows=0,status='PAIRED_RL_CAPACITY_TRAINING_COMPLETE')
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')

class NeuralAdapter:
    def __init__(self,method='direct',zero=False,stage='final'):
        if method!='rl':raise ValueError('RL_ONLY_CAPACITY_CANDIDATE')
        a=np.load(REFERENCE_ARTIFACTS/f'{stage}_normalization.npz');self.mean=a['mean'];self.scale=a['scale']
        self.models=[]
        for seed in SEEDS:
            model=JointPolicy()
            path=(REFERENCE_ARTIFACTS if zero else OUT)/f'{stage}_{method}_{seed}{"_zero" if zero else ""}.pt'
            model.load_state_dict(torch.load(path,weights_only=True,map_location='cpu'))
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
