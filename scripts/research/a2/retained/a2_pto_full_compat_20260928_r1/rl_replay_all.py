"""Evaluate four frozen RL actors as separate actual accounts; never learn.

Uses replay_all.inputs for the same pool/source/time/cost contract and the
immutable scalar holding-aware engine that trained the RL environments. RL is
joint-only and is not crossed with the PTO prediction/risk/optimizer grid.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import traceback
from types import SimpleNamespace

import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits

from common import ROOT, FEATURES, sha, write_json
from replay_all import inputs, metrics
from rl_policy import RLPolicy, POLICIES, GRID, engine, ENGINE_SOURCE

TABLES = ('daily','trades','positions','target_decisions','diagnostics','raw_model_outputs',
          'signal_contexts','operational_actions','execution_results','valuation_intervals')


def check_freeze():
    path=ROOT/'FREEZE.json'
    freeze=json.loads(path.read_text(encoding='utf-8'))
    if freeze.get('status') != 'FROZEN_ALL_LEARNING_PRE2026' or not freeze.get('all_learning_completed'):
        raise RuntimeError('FULL_BATCH_FREEZE_REQUIRED')
    for relative,expected in freeze['artifact_sha256'].items():
        if sha(ROOT/relative) != expected:
            raise RuntimeError('FROZEN_ARTIFACT_CHANGED:'+relative)
    return {'freeze_sha256':sha(path),'frozen_artifacts_checked':len(freeze['artifact_sha256']),
            'freeze_created_utc':freeze['created_utc'],'all_artifact_hashes_match':True}


def forbid_learning():
    def deny(*args,**kwargs):
        raise RuntimeError('LEARNING_FORBIDDEN_IN_FROZEN_RL_EVALUATION')
    from sklearn.preprocessing import StandardScaler
    for method in ['fit','partial_fit','fit_transform']:
        setattr(StandardScaler,method,deny)
    torch.Tensor.backward=deny
    torch.optim.Adam.step=deny
    torch.optim.AdamW.step=deny


def save_predictions(policy, panel, directory, strategy):
    rows=[]
    for record in policy.records:
        for i,ticker in enumerate(record['tickers']):
            row={'strategy_id':strategy,'signal_date':record['signal_date'],'decision_id':record['decision_id'],
                 'ticker':ticker,'action_index':int(record['actions'][i]),
                 'raw_target_weight':float(GRID[record['actions'][i]]),'policy':policy.name,'stage':policy.stage}
            row.update({f'observation_{j}':float(v) for j,v in enumerate(record['observations'][i])})
            rows.append(row)
    prediction=pd.DataFrame(rows)
    if len(prediction):
        prediction=prediction.merge(panel[['signal_date','ticker']+FEATURES],on=['signal_date','ticker'],how='left',validate='many_to_one')
        if not np.isfinite(prediction[FEATURES].to_numpy(float)).all():
            raise RuntimeError('RL_PREDICTION_WITHOUT_LEGAL_SOURCE_INPUT')
    prediction.to_parquet(directory/'policy_predictions_and_observations.parquet',index=False)
    return len(prediction)


def verify_scalar_account(result,prices,calendar,panel):
    """Independent scalar fill/mark proof, without calling any engine helper."""
    cash=1e6;units={};marks={};max_errors={};failures=[]
    quote={d:g.set_index('ticker') for d,g in prices.groupby('trade_date',sort=False)}
    trades={d:g for d,g in result.trades.groupby('execution_date',sort=False)} if len(result.trades) else {}
    positions={d:g for d,g in result.positions.groupby('date',sort=False)} if len(result.positions) else {}
    feature=panel.set_index(['signal_date','ticker'])
    targets=result.target_decisions.set_index('order_id') if len(result.target_decisions) else pd.DataFrame()
    daily=result.daily.set_index('date')
    def equal(name,a,b,day,atol=3e-6):
        error=abs(float(a)-float(b)) if np.isfinite(a) and np.isfinite(b) else np.nan
        if np.isfinite(error):max_errors[name]=max(max_errors.get(name,0.),error)
        if not np.isclose(a,b,atol=atol,rtol=2e-11,equal_nan=True):
            failures.append({'check':name,'date':str(day.date()),'actual':float(a),'expected':float(b)})
    for day in calendar:
        px=quote.get(day,pd.DataFrame())
        def price(ticker,column):
            if ticker not in px.index:return np.nan
            row=px.loc[ticker]
            if bool(row.get('price_quality_warning',False)):return np.nan
            value=float(row[column])
            return value if np.isfinite(value) and value>0 else np.nan
        for ticker in units:
            p=price(ticker,'open')
            if np.isfinite(p):marks[ticker]=p
        opening=marks.copy()
        pre=cash+sum(q*opening.get(t,np.nan) for t,q in units.items())
        equal('open_pretrade_nav',daily.loc[day,'open_pretrade_nav'],pre,day)
        fees=buys=sells=0.
        td=trades.get(day,pd.DataFrame())
        for row in td.itertuples():
            p=price(row.ticker,'open')
            equal('trade_source_open',row.price,p,day,1e-10)
            equal('trade_notional',row.notional,row.index_units*row.price,day)
            equal('trade_fee_10bps',row.transaction_cost,row.notional*.001,day,1e-9)
            equal('units_before',row.index_units_before,units.get(row.ticker,0.),day,3e-10)
            if pd.Timestamp(row.signal_date)>=pd.Timestamp(row.execution_date):
                failures.append({'check':'signal_before_execution','date':str(day.date()),'ticker':row.ticker})
            if row.order_id not in targets.index:
                failures.append({'check':'fill_order_link','date':str(day.date()),'ticker':row.ticker})
            if row.side=='BUY':
                source=feature.loc[(pd.Timestamp(row.signal_date),row.ticker)]
                if not bool(source.new_buy_eligible) or row.notional>.01*source.avg_dollar_volume_20d+3e-6:
                    failures.append({'check':'signal_eligibility_or_ADV','date':str(day.date()),'ticker':row.ticker})
                units[row.ticker]=units.get(row.ticker,0.)+row.index_units
                marks[row.ticker]=p
                opening[row.ticker]=p
                cash-=row.notional+row.transaction_cost;buys+=row.notional
            elif row.side=='SELL':
                units[row.ticker]-=row.index_units
                cash+=row.notional-row.transaction_cost;sells+=row.notional
            else:
                failures.append({'check':'unknown_side','date':str(day.date())})
            if units[row.ticker]<=1e-10:del units[row.ticker]
            equal('units_after',row.index_units_after,units.get(row.ticker,0.),day,3e-10)
            if len(units)>20 or cash < -3e-6:
                failures.append({'check':'live_count_or_cash','date':str(day.date())})
            fees+=row.transaction_cost
        cash=max(cash,0.)
        equal('open_posttrade_nav',daily.loc[day,'open_posttrade_nav'],cash+sum(q*opening.get(t,price(t,'open')) for t,q in units.items()),day)
        for ticker in units:
            p=price(ticker,'close')
            if np.isfinite(p):marks[ticker]=p
        nav=cash+sum(q*marks.get(t,np.nan) for t,q in units.items())
        equal('cash',daily.loc[day,'cash'],cash,day)
        equal('close_nav',daily.loc[day,'nav'],nav,day)
        equal('daily_fees',daily.loc[day,'transaction_cost_amount'],fees,day)
        equal('buy_notional',daily.loc[day,'buy_notional'],buys,day)
        equal('sell_notional',daily.loc[day,'sell_notional'],sells,day)
        equal('actual_names',daily.loc[day,'actual_name_count'],len(units),day,0.)
        pos=positions.get(day,pd.DataFrame())
        if len(pos):
            if set(pos.ticker)!=set(units):failures.append({'check':'position_key_coverage','date':str(day.date())})
            for row in pos.itertuples():
                equal('position_units',row.index_units,units.get(row.ticker,0.),day,3e-10)
                equal('position_mark',row.mark,marks.get(row.ticker,np.nan),day,1e-10)
        elif units:failures.append({'check':'missing_positions','date':str(day.date())})
    return {'status':'PASS' if not failures else 'FAIL','failures':failures,'max_absolute_errors':max_errors,
            'independent_source_price_cash_units_proof':True,'source_engine_helpers_used':False,
            'account_days':len(calendar),'trades':len(result.trades)}


def run_year(year, recover_saved=False):
    freeze_evidence=check_freeze()
    stage='validation' if year==2025 else 'final'
    for name in POLICIES:
        receipt=json.loads((ROOT/f'models/rl/{stage}/TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        expected=receipt['source_sha256'][str(ENGINE_SOURCE)]
        if sha(ENGINE_SOURCE)!=expected:raise RuntimeError('RL_OLD_ENGINE_CHANGED')
    print('FROZEN_INPUTS',year,flush=True)
    panel,prices,calendar,end,asofs,ops=inputs(year)
    # The unchanged scalar and batched engines load the same evidence dataclass
    # under different module identities. Convert its fields, never its rules.
    ops={day:{ticker:engine.OperationalExit(action.reason,action.known_at,action.source_id)
              for ticker,action in actions.items()} for day,actions in ops.items()}
    prices['trade_date']=pd.to_datetime(prices.trade_date)
    feature_path=ROOT/f'data/{"pre" if year==2025 else "test"}.parquet'
    price_path=ROOT/f'data/{"pre" if year==2025 else "test"}_prices.parquet'
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [feature_path,price_path]}
    records=[]
    for name in POLICIES:
        strategy=f'rl_{name}__joint'
        directory=ROOT/f'results/{year}/{strategy}'
        if (directory/'COMPLETE.json').exists():
            records.append(json.loads((directory/'COMPLETE.json').read_text(encoding='utf-8')));continue
        resume=directory.exists() and (directory/'FAILED.json').exists() and recover_saved
        if directory.exists() and any(directory.iterdir()) and not resume:
            raise RuntimeError('RL_PARTIAL_REPLAY_PRESERVED:'+str(directory))
        directory.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        print('RL_REPLAY',year,name,flush=True)
        policy=RLPolicy(name,stage);policy.capture=True
        weights_before={k:v.detach().clone() for k,v in policy.model.state_dict().items()}
        forbid_learning()
        try:
            if resume:
                saved_hashes={p.name:sha(p) for p in directory.glob('*.parquet')}
                result=SimpleNamespace(**{table:pd.read_parquet(directory/f'{table}.parquet') for table in TABLES},
                    metadata=json.loads((directory/'metadata.json').read_text(encoding='utf-8')))
                prediction=pd.read_parquet(directory/'policy_predictions_and_observations.parquet')
                observation=prediction[[f'observation_{j}' for j in range(35)]].to_numpy(np.float32,copy=True)
                with torch.inference_mode():
                    logits,_=policy.model(torch.from_numpy(observation))
                if not np.array_equal(logits.argmax(1).numpy(),prediction.action_index.to_numpy(int)):
                    raise RuntimeError('RL_SAVED_PREDICTIONS_DIFFER_FROM_FROZEN_POLICY')
                prediction_rows=len(prediction)
            else:
                with threadpool_limits(limits=1),torch.inference_mode():
                    result=engine.run_replay(prices,calendar,panel,policy,candidate=strategy,
                        initial_cash=1_000_000.,cost_bps=10.,capacity_fraction=.01,
                        max_positions=20,max_weight=.1,max_invested=.95,
                        signal_start=panel.signal_date.min(),signal_end=end,
                        signal_asof=asofs,operational_exits_by_signal=ops)
            if any(not torch.equal(weights_before[k],v) for k,v in policy.model.state_dict().items()):
                raise RuntimeError('RL_PARAMETERS_CHANGED_DURING_EVALUATION')
            if not resume:
                for table in TABLES:
                    frame=getattr(result,table).copy()
                    frame['strategy_id']=strategy
                    frame.to_parquet(directory/f'{table}.parquet',index=False,compression='zstd')
                prediction_rows=save_predictions(policy,panel,directory,strategy)
            daily=result.daily.copy();daily['strategy_id']=strategy
            pd.DataFrame(metrics(daily)).to_csv(directory/'SUMMARY.csv',index=False)
            verification=verify_scalar_account(result,prices,calendar,panel)
            verification_name='INDEPENDENT_ACCOUNT_REVERIFICATION.json' if resume else 'INDEPENDENT_ACCOUNT_VERIFICATION.json'
            write_json(directory/verification_name,verification)
            if not resume:write_json(directory/'metadata.json',result.metadata)
            if verification['status']!='PASS':raise RuntimeError('RL_INDEPENDENT_ACCOUNT_VERIFICATION_FAILED')
            if resume:
                if any(sha(directory/name)!=value for name,value in saved_hashes.items()):
                    raise RuntimeError('RL_SAVED_LEDGER_CHANGED_DURING_REVERIFICATION')
                write_json(directory/'RESUME_AUDIT.json',{'reason':'Verifier initially used a prior exited ticker mark on re-entry; all existing account parquet files retained bitwise.',
                    'new_account_replays':0,'new_fit_calls':0,'saved_policy_action_argmax_matches_frozen_weights':True,
                    'preserved_initial_failure':'FAILED.json','preserved_initial_verification':'INDEPENDENT_ACCOUNT_VERIFICATION.json',
                    'saved_parquet_sha256':saved_hashes})
            record={'status':'REPLAYED','year':year,'strategy':strategy,'policy':name,'stage':stage,'axis':'joint',
                'initial_cash':1_000_000.,'new_fit_calls':0,'optimizer_steps':0,'parameter_updates':0,
                'parameters_bitwise_unchanged':True,'prediction_rows':prediction_rows,'days':len(calendar),
                'scope':'AVAILABLE_PRE2026_RESEARCH_CONTEXT' if year==2025 else 'QUALIFIED_SUBPOOL_DIAGNOSTIC',
                'formal_full_pool':False,'quantity_coordinate':'affine price-index units; shareholder total return unverified',
                'freeze_verification':freeze_evidence,'source_hashes':source_hashes,
                'model_sha256':sha(ROOT/f'models/rl/{stage}/{name}.pt'),
                'scaler_sha256':sha(ROOT/f'models/rl/{stage}/scaler.joblib'),
                'rl_policy_sha256':sha(ROOT/'rl_policy.py'),'driver_sha256':sha(Path(__file__)),
                'engine_sha256':sha(ENGINE_SOURCE),'metadata_sha256':sha(directory/'metadata.json'),
                'artifacts_sha256':{p.name:sha(p) for p in directory.iterdir() if p.is_file()},
                'independent_account_verification':verification['status'],'seconds':time.monotonic()-started}
            record['verification_file']=verification_name
            record['recovered_existing_ledger']=resume
            write_json(directory/'COMPLETE.json',record)
            records.append(record)
            print('RL_COMPLETE',year,name,round(record['seconds'],2),flush=True)
        except Exception as exc:
            failure={'status':'FAILED','year':year,'strategy':strategy,'reason':str(exc),'traceback':traceback.format_exc()}
            write_json(directory/'FAILED.json',failure)
            records.append(failure)
            raise
    write_json(ROOT/f'results/{year}/RL_ALL_POLICIES.json',{'registered_policies':4,'records':records,
        'risk_optimizer_cross':False,'new_fit_calls':0,'parameters_updated':0,'freeze_verification':freeze_evidence})
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year',type=int,choices=[2025,2026],required=True)
    parser.add_argument('--recover-saved',action='store_true',help='Reverify already saved failed-verifier ledgers; preserve original failure, never replay them')
    args=parser.parse_args()
    run_year(args.year,args.recover_saved)
