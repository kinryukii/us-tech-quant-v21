from pathlib import Path
import hashlib,json
import pandas as pd
import numpy as np

P=Path(__file__).resolve().parent;ROOT=P.parent;WS=ROOT.parent
OLD=WS/'a2_latest_effective_joint_20260927/data'
STAGE=WS/'a2_strict_method_retrain_20260926/test2026_stage'
a=json.loads((P/'DATA_RECEIPT.json').read_text(encoding='utf8'))
old=pd.read_parquet(OLD/'test_features_context.parquet');new=pd.read_parquet(P/'test_features_context.parquet')
op=pd.read_parquet(OLD/'test_prices.parquet');np_=pd.read_parquet(P/'test_prices.parquet')
g=pd.read_parquet(STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
f=pd.read_parquet(STAGE/'identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet')
event=pd.read_parquet(ROOT/'evidence/events/security_day_qualification.parquet')
changes=pd.read_parquet(P/'candidate_qualification_changes.parquet')
pc=pd.read_parquet(P/'price_qualification_changes.parquet')
names=set(a['scope_tickers']);key=['signal_date','ticker'];features=a['feature_columns']
assert len(new)==62476 and int(new.new_buy_eligible.sum())==62393
assert len(new.loc[new.context_only_if_held])==83 and not new.loc[new.context_only_if_held,'new_buy_eligible'].any()
assert not new.duplicated(key).any()
pd.testing.assert_frame_equal(new.loc[~new.ticker.isin(names),old.columns].sort_values(key).reset_index(drop=True),old.loc[~old.ticker.isin(names)].sort_values(key).reset_index(drop=True),check_dtype=False)
for c in ['ticker','trade_date','open','close','volume','raw_open','raw_close','price_coordinate','original_transport','transport_used','extreme_adjusted_jump']:
    pd.testing.assert_series_equal(op[c],np_[c],check_dtype=False)
untouched=~(op.ticker.isin(names)&op.trade_date.ge('2026-01-01'))
pd.testing.assert_frame_equal(op.loc[untouched],np_.loc[untouched,op.columns],check_dtype=False)
restored=changes.loc[changes.qualification_change.eq('RESTORED_CURRENT_POOL')]
assert len(restored)==491 and restored.final_input_gate.eq('UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME').all()
down=changes.loc[changes.qualification_change.eq('DOWNGRADE_UNKNOWN')]
assert len(down)==61 and down.ticker.eq('APD').all()
assert new.loc[new.ticker.eq('APD')].empty
assert len(new.loc[new.ticker.eq('DTP')])==13 and new.loc[new.ticker.eq('DTP'),'transport_used'].eq('US.DTE').all()
scoped=new.loc[new.ticker.isin(names)].merge(event,left_on=key,right_on=['date','ticker'],validate='one_to_one',suffixes=('','_event'))
assert scoped[['all_consumed_events_verified','full_value_reconstruction_verified','public_clock_verified','identity_event_bridge_verified']].all().all()
scoped=scoped.merge(pc.rename(columns={'trade_date':'signal_date'})[key+['price_quality_warning','anchor_date']],on=key,validate='one_to_one',suffixes=('','_price'))
assert not scoped.price_quality_warning.any() and scoped.anchor_date_price.le(scoped.signal_date).all()
matched=new.merge(f[key+features],on=key,validate='one_to_one',suffixes=('','_source'))
assert np.array_equal(matched[features].to_numpy(float),matched[[c+'_source' for c in features]].to_numpy(float))
pool=new.loc[new.new_buy_eligible];assert pool.quarter.eq(pool.asof_quarter).all()
held=new.loc[new.context_only_if_held];assert held.quarter.ne(held.asof_quarter).all()
assert held.groupby('ticker').size().to_dict()=={'BYND':61,'SLMT':22}
# Known event boundary: next unknown cash event removes current context immediately.
for ticker,end in [('LRCX','2026-06-17'),('MKSI','2026-06-03'),('MSFT','2026-05-21'),('RTX','2026-05-22'),('UNH','2026-06-15')]:
    assert new.loc[new.ticker.eq(ticker)&new.signal_date.ge(end)].empty
ex=pd.read_csv(P/'operational_exit_evidence.csv');assert len(ex)==1 and ex.ticker.iloc[0]=='EXAS'
assert pd.Timestamp(ex.known_at.iloc[0])==pd.Timestamp('2026-03-23T13:00:16Z')
assert ex.effective_date.iloc[0]=='2026-03-23' and ':sha256:' in ex.source_id.iloc[0]
assert set(ex.columns)=={'ticker','known_at','effective_date','reason','source_id'}
assert not any('cash_amount' in c for c in ex.columns)
mapping=pd.read_parquet(P/'old54_account_qualification_mapping.parquet')
assert len(mapping)==54 and mapping.ticker.nunique()==45 and mapping.new_context_available.sum()==9
assert a['full_pool']['candidate_rows']==a['full_pool']['qualified_rows']+a['full_pool']['unknown_rows']+a['full_pool']['proven_ineligible_rows']
assert a['full_pool_complete'] is False
for path,h in a['input_sha256'].items():
    with Path(path).open('rb') as fh:assert hashlib.file_digest(fh,'sha256').hexdigest()==h,path
tests={'status':'PASS','context_rows':len(new),'new_buy_rows':len(pool),'held_only_rows':len(held),'restored_current_pool':len(restored),'downgraded_current_pool':len(down),'price_rows':len(np_),
    'checks':['all frozen inputs hash-unchanged','all original numeric prices unchanged','all 32 feature values match materialized source','non45 context and price values preserved','491 restorations from exact original event-only block','61 APD downgrades explicit','corrected DTE original13 rows preserved','event full-prefix and same-day price join pass','no future identity anchor','current pool membership unchanged','held-only83 cannot buy','next unproved event blocks immediately','EXAS source-bound operational evidence has no cash amount','old54 exact mapping']}
(P/'DATA_VALIDATION.json').write_text(json.dumps(tests,indent=2),encoding='utf8')
freeze={}
for path in sorted([ROOT/'build_qualified_data.py',*P.iterdir()]):
    if path.is_file() and path.name!='DATA_FREEZE.json':
        with path.open('rb') as fh:freeze[str(path)]=hashlib.file_digest(fh,'sha256').hexdigest()
(P/'DATA_FREEZE.json').write_text(json.dumps({'status':'FROZEN_AFTER_VALIDATION','files':freeze},indent=2),encoding='utf8')
print(json.dumps(tests,indent=2))
