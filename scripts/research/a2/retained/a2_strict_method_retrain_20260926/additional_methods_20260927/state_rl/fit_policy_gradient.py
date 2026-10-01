"""Causal sequential policy-gradient ranking on the original A2 dynamic pool.

The only reward/transition evaluator is the original reconstruct_path. This is
an independent additional method; no existing A2 model or 2026 result is read.
"""
from __future__ import annotations

import hashlib, importlib.util, json, math, platform, sys, time
from pathlib import Path
import joblib, numpy as np, pandas as pd, sklearn, torch
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent
POOL=Path(r'D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A\score_rank_ledger.parquet')
PRICE=Path(r'D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\pre2026_original_price_coordinate.parquet')
ENGINE=Path(r'D:\us-tech-quant\scripts\v22\fast_a2_r0f_corporate_action_and_nav_forensic_audit.py')
FEATURES=(
    'ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
    'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120','ma10_vs_ma20','ma20_vs_ma50','ma50_vs_ma120',
    'realized_vol_5d','realized_vol_10d','realized_vol_20d','realized_vol_60d','downside_vol_20d','upside_vol_20d',
    'distance_from_high_20d','distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
    'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d','volume_ratio_5d_20d','volume_ratio_20d_60d','avg_dollar_volume_20d')
TOP_N=20; COST_BPS=10; SEED=20260927; GAMMA=.97; EPOCHS=8; LR=.003

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

spec=importlib.util.spec_from_file_location('a2_original_accounting_readonly_rl',ENGINE)
engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
torch.set_num_threads(1)
torch.manual_seed(SEED);np.random.seed(SEED)

# No target or score columns are loaded. The policy sees only original 32
# observation-time features and previous chosen names (a causal action memory).
pool=pd.read_parquet(POOL,columns=['signal_date','ticker',*FEATURES])
pool=pool.sort_values(['signal_date','ticker'],kind='mergesort').reset_index(drop=True)
assert not pool.duplicated(['signal_date','ticker']).any()
assert np.isfinite(pool.loc[:,FEATURES].to_numpy(dtype=np.float32)).all()
prices=pd.read_parquet(PRICE,columns=['ticker','trade_date','open','close'])
assert prices.ticker.eq('QQQ').any()
cal=pd.DatetimeIndex(prices.loc[prices.ticker.eq('QQQ'),'trade_date'].sort_values().unique())

def eligible_days(start_year,end_year):
    dates=pd.DatetimeIndex(pool.loc[pool.signal_date.dt.year.between(start_year,end_year),'signal_date'].unique()).sort_values()
    # The last signal must have execution and terminal mark within the specified
    # history years. Never fetch 2026 returns for pre2026 fitting.
    last_usable=cal[cal.year==end_year][-3]
    dates=dates[dates<=last_usable]
    assert len(dates)>0 and dates.isin(cal).all()
    return dates

preflight=json.loads((HERE/'RL_TIME_LEAKAGE_PREFLIGHT.json').read_text(encoding='utf-8'))
assert preflight['status']=='PASS_PRETRAIN_TIMING_BOUND'
train_dates=eligible_days(2023,2023)
validation_dates=eligible_days(2024,2024)
final_dates=eligible_days(2025,2025)
full_dates=train_dates.append(validation_dates).append(final_dates)

class LinearRankPolicy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight=torch.nn.Parameter(torch.zeros(len(FEATURES)+1,dtype=torch.float64))
    def forward(self,x):
        return x@self.weight

def make_days(dates,scaler):
    frame=pool.loc[pool.signal_date.isin(dates)].copy()
    values=np.clip(scaler.transform(frame.loc[:,FEATURES].to_numpy(dtype=np.float64)),-10,10)
    result=[]
    for date,ids in frame.groupby('signal_date',sort=True).indices.items():
        idx=np.asarray(ids,dtype=np.int64)
        tickers=frame.iloc[idx].ticker.astype(str).tolist()
        result.append((pd.Timestamp(date),tickers,torch.from_numpy(values[idx])))
    assert len(result)==len(dates)
    return result

def choose(days,policy,stochastic):
    target={};logps=[];prior=set()
    for date,tickers,x in days:
        held=torch.tensor([1.0 if t in prior else 0.0 for t in tickers],dtype=torch.float64).reshape(-1,1)
        score=policy(torch.cat((x,held),dim=1))
        if stochastic:
            # Ordered sampling without replacement gives a Plackett-Luce
            # top-20 action with an exact score-function log probability.
            available=torch.ones(len(tickers),dtype=torch.bool)
            picks=[];terms=[]
            for _ in range(TOP_N):
                masked=score.masked_fill(~available,-1e30)
                draw=int(torch.multinomial(torch.softmax(masked.detach(),dim=0),1).item())
                terms.append(score[draw]-torch.logsumexp(masked,dim=0))
                picks.append(draw);available[draw]=False
            logps.append(torch.stack(terms).sum())
        else:
            picks=torch.topk(score.detach(),TOP_N).indices.tolist()
        chosen=[tickers[i] for i in picks]
        target[date]={t:1.0/TOP_N for t in chosen}
        prior=set(chosen)
    return target,logps

def account(target,dates,label):
    # The original accounting engine has the full dynamic price coordinate;
    # candidate actions are never screened using future execution/mark prices.
    dates=pd.DatetimeIndex(dates)
    last_pos=int(cal.get_loc(dates.max()))
    terminal=cal[last_pos+2]
    assert dates.min().year==dates.max().year==terminal.year and terminal<pd.Timestamp('2026-01-01')
    names={name for weights in target.values() for name in weights}|{'QQQ'}
    qfq=prices.loc[prices.trade_date.between(dates.min(),terminal)&prices.ticker.isin(names)]
    path=engine.reconstruct_path(model=label,target_map=target,qfq=qfq,signal_dates=dates,cost_bps=COST_BPS)
    daily=path.daily.sort_values('execution_date',kind='mergesort').reset_index(drop=True)
    assert len(daily)==len(dates)+1
    assert not daily.skipped_buy_count.any() and not daily.blocked_sell_or_rebalance_count.any(),label
    assert daily[['NAV_ACCOUNTING_IDENTITY_ERROR','CASH_IDENTITY_ERROR','POSITION_VALUE_IDENTITY_ERROR','TURNOVER_IDENTITY_ERROR','TRANSACTION_COST_IDENTITY_ERROR']].abs().to_numpy(float).max()<1e-8
    return path,engine.portfolio_metrics(daily)

def train(episodes,epochs,select_on_validation):
    policy=LinearRankPolicy();optim=torch.optim.Adam(policy.parameters(),lr=LR)
    logs=[];best_state=None;best_validation=-math.inf
    for epoch in range(epochs):
        for episode in episodes:
            start=time.monotonic()
            year=int(episode[0][0].year)
            target,logps=choose(episode,policy,True)
            path,metrics=account(target,[x[0] for x in episode],f'RL_TRAIN_{year}_{epoch}')
            # Action at signal t pays cost at the following open and earns
            # subsequent open-to-open P/L. No return-to-go crosses a year.
            rewards=np.log1p(path.daily.reconstructed_daily_return.to_numpy(float))
            returns=np.zeros(len(logps),dtype=np.float64)
            acc=float(rewards[-1])
            for i in range(len(logps)-1,-1,-1):
                acc=float(rewards[i])+GAMMA*acc
                returns[i]=acc
            advantage=(returns-returns.mean())/(returns.std()+1e-8)
            loss=-torch.stack([lp*float(a) for lp,a in zip(logps,advantage)]).mean()
            optim.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(policy.parameters(),1.0);optim.step()
            item={'epoch':epoch+1,'episode_year':year,'train_cumulative_net_return':metrics['cumulative_return'],'train_total_turnover':metrics['total_turnover'],
                  'train_total_cost':metrics['transaction_cost_total'],'policy_gradient_loss':float(loss.detach()),'fit_seconds':time.monotonic()-start,
                  'last_signal':str(episode[-1][0].date()),'terminal_price_date':str(cal[int(cal.get_loc(episode[-1][0]))+2].date())}
            logs.append(item)
        if select_on_validation:
            with torch.no_grad():valid_target,_=choose(validation_days,policy,False)
            _,valid_metrics=account(valid_target,validation_dates,f'RL_VALID_{epoch}')
            item['validation_cumulative_net_return']=valid_metrics['cumulative_return']
            if valid_metrics['cumulative_return']>best_validation:
                best_validation=valid_metrics['cumulative_return']
                best_state=policy.weight.detach().clone()
        print('epoch',epoch+1,'train net',round(metrics['cumulative_return'],4),'validation net',round(item.get('validation_cumulative_net_return',float('nan')),4),flush=True)
    if select_on_validation:
        policy.weight.data.copy_(best_state)
    return policy,logs

# Strict temporal split: 2023 optimization; 2024 validation selects one
# checkpoint; 2025 is untouched final evaluation. Earlier prices have a
# terminal-liquidation counterexample under original accounting, preserved
# in RL_ABORTED_2020_22_PILOT.json.
scaler=StandardScaler().fit(pool.loc[pool.signal_date.isin(train_dates),FEATURES].to_numpy(dtype=np.float64))
train_days=make_days(train_dates,scaler)
validation_days=make_days(validation_dates,scaler)
policy,fit_log=train([train_days],EPOCHS,True)
joblib.dump(scaler,HERE/'policy_train_scaler.joblib',compress=3)
torch.save({'weight':policy.weight.detach().cpu(),'feature_order':FEATURES,'held_target_flag':True},HERE/'policy_validated.pt')
evaluations=[]
for stage,days,dates in [('VALIDATION_2024',validation_days,validation_dates),('FINAL_2025',make_days(final_dates,scaler),final_dates)]:
    with torch.no_grad():target,_=choose(days,policy,False)
    path,metrics=account(target,dates,'RL_'+stage)
    path.daily.to_parquet(HERE/f'{stage.lower()}_daily_ledger.parquet',index=False)
    evaluations.append({'stage':stage,'signals':len(days),'first_signal':str(dates.min().date()),'last_signal':str(dates.max().date()),**metrics})

# Deployment refit has a preset epoch count and no 2026 feedback. Its
# normalization is learned only on observations dated <=2025-12-29.
full_scaler=StandardScaler().fit(pool.loc[pool.signal_date.isin(full_dates),FEATURES].to_numpy(dtype=np.float64))
full_episodes=[make_days(d,full_scaler) for d in [train_dates,validation_dates,final_dates]]
full_policy,full_fit_log=train(full_episodes,EPOCHS,False)
joblib.dump(full_scaler,HERE/'policy_full_pre2026_scaler.joblib',compress=3)
torch.save({'weight':full_policy.weight.detach().cpu(),'feature_order':FEATURES,'held_target_flag':True},HERE/'policy_full_pre2026.pt')

report={'method':'sequential stochastic Plackett-Luce top-20 policy gradient with previous-target membership state',
        'environment':'Original A2 eligible dynamic pool and 32 close-known features; original reconstruct_path with QFQ open next-day execution, subsequent-open valuation, 10 bps cost, actual cash/holdings/turnover',
        'pool_sha256':sha(POOL),'original_price_coordinate_sha256':sha(PRICE),'accounting_source_sha256':sha(ENGINE),
        'train_signal_first':str(train_dates.min().date()),'train_signal_last':str(train_dates.max().date()),'train_signal_days':len(train_days),
        'train_years':[2023],'validation_year':2024,'untouched_evaluation_years':[2025],
        'gamma':GAMMA,'epochs':EPOCHS,'learning_rate':LR,'top_n':TOP_N,'cost_bps':COST_BPS,'seed':SEED,
        'trained_checkpoint_selection':'Best 2024 validation cumulative net return only; 2025 was read after checkpoint selection.',
        'validation_and_evaluation':evaluations,'train_log':fit_log,'full_pre2026_train_log':full_fit_log,
        'artifacts':{p.name:sha(p) for p in [HERE/'policy_train_scaler.joblib',HERE/'policy_validated.pt',HERE/'policy_full_pre2026_scaler.joblib',HERE/'policy_full_pre2026.pt']},
        'policy_optimizer_steps_in_successful_run':4*EPOCHS,'preprocessor_fit_calls_in_successful_run':2,
        'aborted_pilot_optimizer_steps':1,'aborted_pilot_preprocessor_fit_calls':1,
        'total_policy_optimizer_steps_including_aborted_pilot':4*EPOCHS+1,'total_preprocessor_fit_calls_including_aborted_pilot':3,
        'timing_preflight_path':str(HERE/'RL_TIME_LEAKAGE_PREFLIGHT.json'),
        '2026_input_used_for_fit_selection_or_reward':False,
        'coordinate_limit':'Original QFQ adjusted price identity, not realized shareholder total return.',
        'training_interpretation':'True sequential policy optimization from original portfolio net rewards. No claim of positive skill is made from fitting alone.'}
(HERE/'POLICY_GRADIENT_REPORT.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'evaluations':evaluations,'total_policy_optimizer_steps_including_aborted_pilot':4*EPOCHS+1,'total_preprocessor_fit_calls_including_aborted_pilot':3},indent=2))
