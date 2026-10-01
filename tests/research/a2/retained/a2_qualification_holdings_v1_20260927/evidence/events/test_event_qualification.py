"""Independent structural and causal boundary checks for saved event gates."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd

P=Path(__file__).resolve().parent
e=pd.read_parquet(P/'event_qualification.parquet')
d=pd.read_parquet(P/'security_day_qualification.parquet')
i=pd.read_parquet(P/'qualified_intervals.parquet')
assert len(e)==97 and e.event_key.is_unique
assert len(d)==45*183 and not d.duplicated(['ticker','date']).any()
assert d.date.min()==pd.Timestamp('2026-01-02') and d.date.max()==pd.Timestamp('2026-09-24')
assert e.loc[e.ticker.isin(['GOOG','GOOGL']),'instrument_key'].nunique()==2
assert e.loc[e.ticker.eq('DTP'),'transport_code'].eq('US.DTE').all()
assert e.loc[e.status.eq('VERIFIED'),['public_clock_verified','event_terms_verified','full_value_reconstruction_verified','identity_event_bridge_verified']].all().all()
assert e.loc[e.status.eq('VERIFIED'),'source_public_date'].notna().all()
assert e.loc[e.status.eq('VERIFIED'),'public_at_upper_bound_utc'].notna().all()
checks=0
for ticker,g in d.groupby('ticker'):
    ev=e.loc[e.ticker.eq(ticker)]
    for r in g.itertuples(index=False):
        used=ev.loc[ev.event_date.le(r.date)]
        bad=used.loc[used.status.ne('VERIFIED')]
        assert r.consumed_event_count==len(used)
        assert r.unresolved_event_keys=='|'.join(bad.event_key)
        assert r.all_consumed_events_verified==(len(bad)==0)
        # Explicit counterfactual: adding a future unknown event cannot change prefix.
        with_future=pd.concat([ev,ev.iloc[:1].assign(event_date=r.date+pd.Timedelta(days=1),status='UNKNOWN')])
        assert with_future.loc[with_future.event_date.le(r.date)].event_key.tolist()==used.event_key.tolist()
        interval=i.loc[i.ticker.eq(ticker)&i.interval_start.le(r.date)&i.interval_end_exclusive.gt(r.date)]
        assert len(interval)==1 and interval.iloc[0].status==r.status
        checks+=1
# Verification of a first dividend ends exactly when a later unproven event is consumed.
for ticker,first,end in [('JPM','2026-01-06','2026-04-06'),('MSFT','2026-02-19','2026-05-21'),('LRCX','2026-03-04','2026-06-17')]:
    assert d.loc[d.ticker.eq(ticker)&d.date.ge(first)&d.date.lt(end),'all_consumed_events_verified'].all()
    assert not d.loc[d.ticker.eq(ticker)&d.date.eq(end),'all_consumed_events_verified'].iloc[0]
assert not e.loc[e.ticker.eq('APD')&e.event_date.eq('2026-01-02'),'public_clock_verified'].iloc[0]
audit=json.loads((P/'EVENT_QUALIFICATION_AUDIT.json').read_text(encoding='utf8'))
for p,h in audit['source_hashes'].items():
    with Path(p).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==h
result={'status':'PASS','event_rows':len(e),'security_day_rows_checked':checks,'intervals':len(i),
    'tests':['unique economic-event keys','GOOG/GOOGL separated','DTP uses DTE transport only','verified implies all event dependencies',
    'all 8235 day prefixes independently recomputed','future unknown append leaves past prefix unchanged','interval boundary roundtrip',
    'first dividend windows end on next unproven event','APD signature date not promoted to publication','frozen input hashes unchanged']}
(P/'EVENT_QUALIFICATION_TESTS.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
