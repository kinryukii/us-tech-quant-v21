"""Precommitted, evidence-based input quarantine; retain raw data and held units."""
from pathlib import Path
import hashlib
import json
import pandas as pd
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'a2_qualification_holdings_v1_20260927/data'
OUT=ROOT/'data'
DATE=pd.Timestamp('2026-02-26')

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def quarantine(panel,prices):
    feature_mask=panel.ticker.eq('GLW')&panel.signal_date.eq(DATE)
    price_mask=prices.ticker.eq('GLW')&prices.trade_date.eq(DATE)
    assert feature_mask.sum()==1 and price_mask.sum()==1,'Frozen conflict scope changed'
    assert not prices.loc[price_mask,'price_quality_warning'].any(),'Conflict already gated in source'
    clean_panel=panel.loc[~feature_mask].copy()
    clean_prices=prices.copy();clean_prices.loc[price_mask,'price_quality_warning']=True
    pd.testing.assert_frame_equal(clean_prices.drop(columns='price_quality_warning'),prices.drop(columns='price_quality_warning'))
    pd.testing.assert_frame_equal(clean_prices.loc[~price_mask],prices.loc[~price_mask])
    pd.testing.assert_frame_equal(clean_panel,panel.loc[~feature_mask])
    return clean_panel,clean_prices,panel.loc[feature_mask].copy(),prices.loc[price_mask].copy()

def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'ADMISSIBILITY_RECEIPT.json').exists():raise RuntimeError('Completed input quarantine is immutable')
    sources={name:SOURCE/name for name in ['test_features_context.parquet','test_prices.parquet']}
    panel=pd.read_parquet(sources['test_features_context.parquet']);prices=pd.read_parquet(sources['test_prices.parquet'])
    a,b,c,d=quarantine(panel,prices)
    for name,frame in [('test_features_context.parquet',a),('test_prices.parquet',b),
                       ('quarantined_feature_rows.parquet',c),('quarantined_price_rows.parquet',d)]:
        frame.to_parquet(OUT/name,index=False)
    receipt=dict(status='PASS',created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        pre_test_evaluation=True,training_rows_changed=0,quarantined_ticker='GLW',quarantined_date=str(DATE.date()),
        feature_rows_excluded=1,price_rows_warning_added=1,raw_feature_rows=len(panel),admitted_feature_rows=len(a),
        raw_buy_rows=int(panel.new_buy_eligible.sum()),admitted_buy_rows=int(a.new_buy_eligible.sum()),
        held_unit_semantics='Missing model input preserves held units and reserves capital/slots; no implicit exit',
        price_numeric_values_unchanged=True,window_unchanged=True,selection_using_test_returns=False,
        source_sha256={str(p):sha(p) for p in sources.values()},
        code_sha256=sha(Path(__file__)),contract_sha256=sha(ROOT/'DATA_ADMISSIBILITY_ADDENDUM.md'),
        output_sha256={p.name:sha(p) for p in OUT.glob('*.parquet')},
        full_pool_pit_certified=False)
    (OUT/'ADMISSIBILITY_RECEIPT.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
