"""Independently reconstruct completed ledgers, clocks, fees and model hashes."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from evaluate import ROOT, DATA, QUALIFIED, TEST_DATA, PRICE, NAMES, sha, write
from values import FEATURES

def check_run(folder,panel,prices,calendar,cost):
    d=pd.read_parquet(folder/'daily.parquet').sort_values('date')
    t=pd.read_parquet(folder/'trades.parquet')
    pos=pd.read_parquet(folder/'positions.parquet')
    target=pd.read_parquet(folder/'target_decisions.parquet')
    ctx=pd.read_parquet(folder/'signal_contexts.parquet')
    assert d.cash.ge(-1e-7).all() and d.actual_name_count.le(20).all()
    errors={}
    for col in ['nav_identity_error','cash_flow_identity_error','cost_identity_error','open_self_finance_error']:
        maxerr=float(d[col].abs().max()) if d[col].notna().any() else 0.
        assert maxerr<1e-7,(folder,col,maxerr)
        errors[col]=maxerr
    if len(ctx):
        assert (ctx.active_target_count<=ctx.final_available_slots).all()
        assert (ctx.active_target_weight<=ctx.final_available_weight+1e-8).all()
    active=target.loc[target.order_type.eq('TARGET_WEIGHT')]
    assert active.target_weight.between(0,.1+1e-8).all()
    if len(t):
        assert not t.order_id.duplicated().any()
        nxt=dict(zip(calendar[:-1],calendar[1:]))
        assert t.signal_date.map(nxt).eq(t.execution_date).all()
        assert (t.signal_date<t.execution_date).all()
        assert np.allclose(t.notional,t.price*t.index_units,rtol=1e-12,atol=1e-7)
        assert np.allclose(t.transaction_cost,t.notional*(cost/10000),rtol=1e-12,atol=1e-7)
        buy=t.loc[t.side.eq('BUY')]
        legal=buy.merge(panel[['signal_date','ticker','new_buy_eligible','avg_dollar_volume_20d']],on=['signal_date','ticker'],how='left',validate='many_to_one')
        assert legal.new_buy_eligible.fillna(False).all()
        assert (legal.notional<=.01*legal.avg_dollar_volume_20d+1e-7).all()
        matched=t.merge(prices[['ticker','trade_date','open','price_quality_warning']],left_on=['ticker','execution_date'],right_on=['ticker','trade_date'],how='left',validate='many_to_one')
        assert ~matched.price_quality_warning.fillna(True).any()
        assert np.allclose(matched.price,matched.open,rtol=1e-12,atol=1e-9)
    cash=1e6;holdings={};cash_error=0.;quantity_error=0.
    trades_by_date={x:y for x,y in t.groupby('execution_date',sort=False)} if len(t) else {}
    positions_by_date={x:y for x,y in pos.groupby('date',sort=False)} if len(pos) else {}
    for row in d.itertuples():
        for order in trades_by_date.get(row.date,t.iloc[:0]).itertuples():
            sign=1 if order.side=='BUY' else -1
            holdings[order.ticker]=holdings.get(order.ticker,0.)+sign*order.index_units
            cash-=sign*order.notional+order.transaction_cost
        cash_error=max(cash_error,abs(cash-row.cash))
        p=positions_by_date.get(row.date,pos.iloc[:0])
        actual=dict(zip(p.ticker,p.index_units))
        for ticker in holdings.keys()|actual.keys():
            quantity_error=max(quantity_error,abs(holdings.get(ticker,0.)-actual.get(ticker,0.)))
        assert len([x for x in actual.values() if x>1e-10])<=20
    assert cash_error<1e-6,(folder,'independent cash',cash_error)
    assert quantity_error<1e-7,(folder,'independent quantities',quantity_error)
    # No-decision holdings must keep their units across the order execution.
    no=target.loc[target.order_type.eq('HOLD_UNITS')&target.execution_date.notna()]
    if len(no):
        consumed=no.merge(pos[['date','ticker','index_units']],left_on=['execution_date','ticker'],right_on=['date','ticker'],how='left',validate='many_to_one')
        assert np.allclose(consumed.hold_units,consumed.index_units.fillna(0),atol=1e-7,rtol=1e-10)
    return dict(status='PASS',days=len(d),trades=len(t),hold_unit_orders=len(no),
        independent_cash_error=cash_error,independent_quantity_error=quantity_error,**errors)

def main():
    rows=[];pre=pd.read_parquet(DATA/'pre2026_joint_context.parquet')
    assert pre.signal_date.lt('2026-01-01').all()
    assert pre.loc[pre.label_available,'label_end_date'].lt('2026-01-01').all()
    v=json.loads((ROOT/'value_artifacts/FIT_RECEIPT.json').read_text(encoding='utf-8'))
    n=json.loads((ROOT/'neural_artifacts/TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    assert len(v['fits'])==14 and len(n['artifacts'])==6
    assert v.get('fit_2026_rows',v.get('test2026_rows_read',-1))==0
    assert n['fit_2026_rows']==0
    artifact_checks=0
    for r in v['fits']:
        assert sha(r['artifact'])==r['artifact_sha256'];artifact_checks+=1
        cutoff='2025-01-01' if r['stage']=='validation' else '2026-01-01'
        assert r['converged'] and r['fit_2026_rows']==0
        assert pd.Timestamp(r['train_signal_max'])<pd.Timestamp(cutoff)
        assert pd.Timestamp(r['train_label_end_max'])<pd.Timestamp(cutoff)
        keys=ROOT/'value_artifacts'/f"sample_keys_{r['stage']}.parquet"
        assert sha(keys)==r['sampling']['sample_keys_sha256']
        sampled=pd.read_parquet(keys)
        assert sampled.signal_date.lt(cutoff).all() and sampled.label_end_date.lt(cutoff).all()
    for r in n['artifacts']:
        assert sha(r['path'])==r['sha256'];artifact_checks+=1
        assert sha(r['zero_path'])==r['zero_sha256']
        assert sha(r['last_episode_path'])==r['last_episode_sha256']
        cutoff='2025-01-01' if r['stage']=='validation' else '2026-01-01'
        for col in ['fit_signal_max','fit_label_end_max','consumed_price_max']:
            assert pd.Timestamp(r[col])<pd.Timestamp(cutoff)
        assert r['actual_parameter_updates']>0 and r['parameter_delta_l2']>0
    for s in n['stages']:
        cutoff='2025-01-01' if s['stage']=='validation' else '2026-01-01'
        assert sha(s['normalization_path'])==s['normalization_sha256']
        assert s['normalization']['fitted_from_scratch']
        for col in ['signal_max','label_end_max']:
            assert pd.Timestamp(s['normalization'][col])<pd.Timestamp(cutoff)
    for stage,cutoff in [('validation','2025-01-01'),('final','2026-01-01')]:
        for kind,artifact in [('risk_artifacts','frozen_covariance.npz'),('aux_artifacts','auxiliary.joblib')]:
            folder=ROOT/kind/stage
            receipt=json.loads((folder/'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
            assert receipt['fit_2026_rows']==0 and not receipt['fit_reused']
            assert receipt['stage']==stage and receipt['cutoff_exclusive']==cutoff
            assert pd.Timestamp(receipt['train_last'])<pd.Timestamp(cutoff)
            assert sha(folder/artifact)==receipt['artifact_sha256'];artifact_checks+=1
            assert sha(receipt['source'])==receipt['source_sha256']
            assert sha(ROOT/'EXPERIMENT_CONTRACT.md')==receipt['experiment_contract_sha256']
            assert sha(ROOT/'risk_aux.py')==receipt['implementation_sha256']
            if kind=='aux_artifacts':
                assert sha(folder/'sample_keys.parquet')==receipt['sample_keys_sha256']
                assert receipt['feature_order']==FEATURES and receipt['seed']==20260928
                assert receipt['cluster_parameters']['n_clusters']==5
                assert receipt['anomaly_parameters']['n_estimators']==100
    from ensemble import verify_ensemble_artifacts
    ensemble_audit=verify_ensemble_artifacts()
    gate=json.loads((TEST_DATA/'ADMISSIBILITY_RECEIPT.json').read_text(encoding='utf-8'))
    assert gate['feature_rows_excluded']==gate['price_rows_warning_added']==1
    assert sha(ROOT/'data_gate.py')==gate['code_sha256']
    assert sha(ROOT/'DATA_ADMISSIBILITY_ADDENDUM.md')==gate['contract_sha256']
    for p,h in gate['source_sha256'].items():assert sha(p)==h
    for p,h in gate['output_sha256'].items():assert sha(TEST_DATA/p)==h
    evidence=json.loads((TEST_DATA/'GLW_EVIDENCE_BINDING.json').read_text(encoding='utf-8-sig'))
    for item in evidence['bindings']:assert sha(item['path'])==item['sha256']
    for year in [2025,2026]:
        if year==2025:
            panel=pre.loc[pre.signal_date.dt.year.eq(2025)];prices=pd.read_parquet(PRICE)
            calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
        else:
            panel=pd.read_parquet(TEST_DATA/'test_features_context.parquet');prices=pd.read_parquet(TEST_DATA/'test_prices.parquet')
            calendar=pd.DatetimeIndex(pd.read_parquet(DATA/'calendar.parquet').query('is_test').trade_date)
        if 'price_quality_warning' not in prices:prices['price_quality_warning']=False
        for cost in ([10] if year==2025 else [10,5,25]):
            out=ROOT/f'evaluation_{year}'/f'cost_{cost}'
            complete=json.loads((out/'COMPLETE.json').read_text(encoding='utf-8'))
            assert complete['fit_attempts']==0 and complete['policies']==len(NAMES)
            bound=json.loads((out/'FROZEN_BEFORE_REPLAY.json').read_text(encoding='utf-8'))
            for p,h in bound['source_sha256'].items():assert sha(p)==h,('source changed',p)
            for name in NAMES:
                audit=check_run(out/name,panel,prices,calendar,cost)
                rows.append(dict(year=year,cost_bps=cost,policy=name,**audit))
    write(ROOT/'VERIFICATION.json',dict(status='PASS',new_supervised_artifacts=14,new_neural_artifacts=6,
        artifact_hashes_checked=artifact_checks,test_fit_attempts=0,ledger_runs_checked=len(rows),runs=rows,
        ensemble_audit=ensemble_audit,
        proof_scope='Code/date/hash/accounting checks; historical source completeness and GLW conflict are not certified',
        full_pool_pit_certified=False,blind_test=False))
    print(json.dumps({'status':'PASS','ledger_runs_checked':len(rows),'model_hashes_checked':artifact_checks}),flush=True)

if __name__=='__main__':main()
