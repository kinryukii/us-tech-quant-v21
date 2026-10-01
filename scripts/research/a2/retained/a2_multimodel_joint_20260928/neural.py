"""Fresh fixed-budget joint MLP and RL training with capacity-aware state.

Only the frozen pre-2026 context and original pre-2026 price file are training
inputs. Validation models never fit on 2025; final models never fit on 2026.
No old weight, normalizer, validation result, or test file is read by train().
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
OUT=ROOT/'neural_artifacts'
CONTRACT=ROOT/'EXPERIMENT_CONTRACT.md'
FEATURES=['ret_1d', 'ret_3d', 'ret_5d', 'ret_10d', 'ret_20d', 'ret_40d', 'ret_60d', 'ret_120d', 'price_vs_ma10', 'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma120', 'ma10_vs_ma20', 'ma20_vs_ma50', 'ma50_vs_ma120', 'realized_vol_5d', 'realized_vol_10d', 'realized_vol_20d', 'realized_vol_60d', 'downside_vol_20d', 'upside_vol_20d', 'distance_from_high_20d', 'distance_from_high_60d', 'distance_from_low_20d', 'distance_from_low_60d', 'max_drawdown_20d', 'max_drawdown_60d', 'avg_volume_20d', 'avg_volume_60d', 'volume_ratio_5d_20d', 'volume_ratio_20d_60d', 'avg_dollar_volume_20d']
PRICE=ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
SEEDS=(20260928,20260929)
DIRECT_EPOCHS=6
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


def stage_rows(panel,last):
    """All learned statistics and observations require mature in-stage labels."""
    last=pd.Timestamp(last)
    if last>=pd.Timestamp('2026-01-01'):raise ValueError('TRAIN_STAGE_BOUNDARY_2026')
    signal=pd.to_datetime(panel.signal_date)
    end=pd.to_datetime(panel.label_end_date)
    return panel.loc[signal.le(last)&end.notna()&end.le(last)].copy()


def fit_normalization(panel,last):
    rows=stage_rows(panel,last)
    rows=rows.loc[np.isfinite(rows[FEATURES].to_numpy(float)).all(axis=1)]
    if rows.empty:raise RuntimeError('EMPTY_STAGE_NORMALIZER')
    x=rows[FEATURES].to_numpy(float)
    mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-12]=1.
    evidence=dict(rows=len(rows),signal_max=str(pd.to_datetime(rows.signal_date).max().date()),
                  label_end_max=str(pd.to_datetime(rows.label_end_date).max().date()),
                  fitted_from_scratch=True)
    return mean,scale,evidence

class Market:
    def __init__(self,panel,first,last,mean,scale):
        boundary=pd.Timestamp(last)
        if boundary >= pd.Timestamp('2026-01-01'):raise ValueError('TRAIN_PRICE_BOUNDARY_2026')
        panel=stage_rows(panel,last)
        px=pd.read_parquet(PRICE,columns=['ticker','trade_date','open','close'],
            filters=[('trade_date','<=',boundary)])
        px['trade_date']=pd.to_datetime(px.trade_date)
        px=px[px.trade_date.le(boundary)].copy()
        if px.empty or px.trade_date.max()>boundary:raise RuntimeError('TRAIN_PRICE_BOUNDARY')
        self.price_date_max=str(px.trade_date.max().date())
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
            self.days.append(dict(date=str(d.date()),execution_date=str(calendar[i+1].date()),
                reward_end_date=str(calendar[i+2].date()),ids=torch.tensor(ids),x=torch.tensor(x,dtype=torch.float32),
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
            records.append(dict(signal_date=d['date'],execution_date=d['execution_date'],
                reward_end_date=d['reward_end_date'],next_open_nav=float(pre_nav.detach()),
                actual_cash_fraction=float((new_cash/ending_nav).detach()),
                actual_exposure=float(((new_units*d['ending']).sum()/ending_nav).detach()),
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
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError('FRESH_NEURAL_OUTPUT_ALREADY_EXISTS')
    OUT.mkdir(exist_ok=True)
    source=SOURCE/'data/pre2026_joint_context.parquet'
    inputs={'context':source,'price':PRICE,'contract':CONTRACT,'source_code':Path(__file__)}
    frozen={key:sha(path) for key,path in inputs.items()}
    panel=pd.read_parquet(source)
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    panel['label_end_date']=pd.to_datetime(panel.label_end_date)
    if panel.signal_date.max()>=pd.Timestamp('2026-01-01'):
        raise RuntimeError('TRAIN_SOURCE_CONTAINS_2026_SIGNAL')
    if panel.label_end_date.dropna().max()>=pd.Timestamp('2026-01-01'):
        raise RuntimeError('TRAIN_SOURCE_CONTAINS_2026_LABEL')
    if (panel.avg_dollar_volume_20d.isna()|panel.avg_dollar_volume_20d.le(0)).any():
        raise RuntimeError('NONPOSITIVE_PRE2026_SIGNAL_ADV')
    spec=dict(input_paths={key:str(path) for key,path in inputs.items()},input_sha256=frozen,
        source_sha256=frozen['context'],price_source_sha256=frozen['price'],
        source_code_sha256=frozen['source_code'],contract_sha256=frozen['contract'],
        direct_epochs=DIRECT_EPOCHS,rl_epochs=RL_EPOCHS,seeds=list(SEEDS),feature_order=FEATURES,
        architecture=[len(FEATURES)+3,32,16,1],train_cost_bps_per_side=10,max_positions=20,
        max_weight=.1,max_exposure=.95,zero_threshold=.02,learning_rate=.0005,
        weight_decay=.001,risk_aversion=5,rl_gamma=.97,rl_block_steps=32,
        train_first='2023-01-01',stage_last={'validation':'2024-12-31','final':'2025-12-31'},
        selection='fixed epochs and seeds; no validation/test-based training or selection',
        universe_rule='Latest public/effective 13F pool; previous effective pool carried until the next becomes effective.',
        policy_version='20260928_fresh_multimodel_capacity_joint',
        holding_semantics='Preserve unavailable holdings, reserve names/capital, feed actual filled units and cash into subsequent observations.',
        capacity_fraction=CAPACITY_FRACTION,capacity_side='BUY',initial_capital_dollars=INITIAL_CASH_DOLLARS,
        normalizers='new independent stage fits on finite features with signal and label_end <= stage cutoff',
        initialization='fresh torch initialization for each stage/method/seed; no pretrained artifact reads',
        limitations=['Direct utility gradients stop at each day; this is not backpropagation through an entire episode.',
            'Hard TOP20 is differentiated only through selected proposals; exploration noise is fixed by seed.',
            'Reward uses one-period log NAV and target-weight volatility penalty; independent ledger evaluates realized returns.',
            'Signal ADV caps index-coordinate notional; these are research price-coordinate rewards, not certified shareholder returns.',
            'Previously observed historical diagnostics are not a fresh blind holdout.'])
    (OUT/'PRE_FIT_CONTRACT.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    logs=[];artifacts=[];stages=[]
    for stage,last in spec['stage_last'].items():
        mean,scale,norm_evidence=fit_normalization(panel,last)
        normalization=OUT/f'{stage}_normalization.npz'
        np.savez(normalization,mean=mean,scale=scale)
        market=Market(panel,'2023-01-01',last,mean,scale)
        if not market.days:raise RuntimeError('EMPTY_STAGE_MARKET')
        stage_evidence=dict(stage=stage,cutoff=last,normalization=norm_evidence,
            normalization_path=str(normalization),normalization_sha256=sha(normalization),
            first_signal=market.days[0]['date'],last_signal=market.days[-1]['date'],
            last_execution_date=market.days[-1]['execution_date'],
            last_reward_end_date=market.days[-1]['reward_end_date'],
            consumed_price_max=market.price_date_max,market_days=len(market.days))
        stages.append(stage_evidence)
        for method,seeds,epochs in [('direct',[SEEDS[0]],DIRECT_EPOCHS),('rl',SEEDS,RL_EPOCHS)]:
            for seed in seeds:
                torch.manual_seed(seed)
                model=JointPolicy()
                zero=OUT/f'{stage}_{method}_{seed}_zero.pt'
                torch.save(model.state_dict(),zero)
                initial={k:v.detach().clone() for k,v in model.state_dict().items()}
                optimizer=torch.optim.Adam(model.parameters(),lr=.0005,weight_decay=.001)
                updates=0
                for epoch in range(epochs):
                    started=time.monotonic()
                    info,train_records=market.episode(model,optimizer,method,seed+epoch)
                    updates+=info['updates']
                    row=dict(stage=stage,method=method,seed=seed,epoch=epoch+1,
                             seconds=time.monotonic()-started,**info)
                    logs.append(row)
                    with (OUT/'training.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps(row)+'\n')
                    print(json.dumps(row),flush=True)
                delta=float(sum((v-initial[k]).square().sum().item() for k,v in model.state_dict().items())**.5)
                if not delta>0 or updates<=0:raise RuntimeError('NO_ACTUAL_TRAINING_UPDATE')
                records_path=OUT/f'{stage}_{method}_{seed}_last_train_episode.parquet'
                pd.DataFrame(train_records).to_parquet(records_path,index=False)
                file=OUT/f'{stage}_{method}_{seed}.pt'
                torch.save(model.state_dict(),file)
                artifacts.append(dict(stage=stage,method=method,seed=seed,path=str(file),sha256=sha(file),
                    zero_path=str(zero),zero_sha256=sha(zero),initialization='fresh',epochs=epochs,
                    parameters=sum(p.numel() for p in model.parameters()),parameter_delta_l2=delta,
                    actual_parameter_updates=updates,fit_signal_max=market.days[-1]['date'],
                    fit_label_end_max=stage_evidence['last_reward_end_date'],
                    consumed_price_max=market.price_date_max,normalization_sha256=sha(normalization),
                    last_episode_path=str(records_path),last_episode_sha256=sha(records_path)))
    if any(sha(path)!=frozen[key] for key,path in inputs.items()):
        raise RuntimeError('INPUT_CHANGED_DURING_TRAINING')
    receipt=dict(specification=spec,stages=stages,artifacts=artifacts,logs=logs,
        fit_count=len(artifacts),actual_parameter_updates=sum(v['actual_parameter_updates'] for v in artifacts),
        fit_2026_rows=0,reused_weight_files=[],reused_normalization_files=[],
        training_signal_max=max(s['last_signal'] for s in stages),
        training_label_end_max=max(s['last_reward_end_date'] for s in stages),
        max_consumed_price_date=max(s['consumed_price_max'] for s in stages),
        input_sha256_unchanged=True,status='FRESH_JOINT_NEURAL_TRAINING_COMPLETE')
    (OUT/'TRAIN_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'status':receipt['status'],'fits':len(artifacts),
                      'actual_parameter_updates':receipt['actual_parameter_updates']}),flush=True)


class NeuralAdapter:
    def __init__(self,method='direct',zero=False,stage='final'):
        if method not in ('direct','rl') or stage not in ('validation','final'):
            raise ValueError('INVALID_NEURAL_METHOD_OR_STAGE')
        self.method=method;self.zero=zero;self.stage=stage
        a=np.load(OUT/f'{stage}_normalization.npz')
        self.mean=a['mean'];self.scale=a['scale'];self.models=[]
        for seed in ([SEEDS[0]] if method=='direct' else SEEDS):
            model=JointPolicy();suffix='_zero' if zero else ''
            model.load_state_dict(torch.load(OUT/f'{stage}_{method}_{seed}{suffix}.pt',weights_only=True,map_location='cpu'))
            model.eval();self.models.append(model)

    def __call__(self,day,weights,cash):
        if day.empty:return {}
        if 'new_buy_eligible' in day:
            day=day[day.new_buy_eligible.astype(bool)|day.ticker.map(weights).fillna(0).gt(0)]
        day=day.loc[np.isfinite(day[FEATURES].to_numpy(float)).all(axis=1)].sort_values('ticker',kind='stable')
        if day.empty:return {}
        visible=set(day.ticker)
        locked={t:w for t,w in weights.items() if w>1e-12 and t not in visible}
        free_slots=max(0,20-len(locked));free_exposure=max(0.,.95-sum(locked.values()))
        x=np.clip((day[FEATURES].to_numpy(float)-self.mean)/self.scale,-8,8)
        old=np.array([weights.get(t,0) for t in day.ticker])
        obs=torch.tensor(np.column_stack([x,old,np.repeat(cash,len(day)),old>0]),dtype=torch.float32)
        eligible=day.new_buy_eligible.to_numpy(bool) if 'new_buy_eligible' in day else np.ones(len(day),bool)
        upper=torch.tensor(np.where(eligible,.1,np.minimum(old,.1)),dtype=torch.float32)
        with torch.no_grad():
            w=torch.stack([project(m(obs),upper=upper,max_names=free_slots,max_exposure=free_exposure)
                           for m in self.models]).mean(dim=0).numpy()
        keep=np.argsort(-w,kind='stable')[:free_slots];mask=np.zeros(len(w));mask[keep]=1;w*=mask
        if w.sum()>free_exposure:w*=free_exposure/w.sum()
        return {str(t):float(v) for t,v in zip(day.ticker,w) if v>1e-8}


if __name__=='__main__':train()
