"""Turn a new quarterly CUSIP set into an evidence-backed data intake queue.

This is a derived review queue, not a security master or strategy membership
authority. Only exact CUSIP matches from the supplied existing mapping are used.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from scripts.storage.storage_r2a import DataStore
from scripts.storage.build_data_catalog import register_file, sha256


def prepare(store, quarter_root, identity_path, historical_universe):
    quarter_root=store._check_data_path(Path(quarter_root))
    qp=quarter_root/'quarter_universe.parquet'
    quarter=pq.ParquetFile(qp).read(columns=['cusip','issuer_name','effective_date','quarter']).to_pandas()
    identity_path=store._check_data_path(Path(identity_path))
    identities=pq.ParquetFile(identity_path).read().to_pandas()
    history_path=store._check_data_path(Path(historical_universe))
    historical=set(pq.ParquetFile(history_path).read(columns=['cusip']).to_pandas().cusip.astype(str))
    mappings={str(k):v for k,v in identities.groupby('cusip')}
    prices=store._catalog_rows('prices_daily')
    availability={(r['ticker'],r['adjustment']):r['max_date'] for r in prices}
    rows=[]
    for row in quarter.to_dict('records'):
        cusip=str(row['cusip']);matches=mappings.get(cusip,pd.DataFrame())
        out={**row,'first_seen_in_history':cusip not in historical,'ticker':None,'provider_code':None,
             'mapping_source':None,'mapping_status':'NO_EXISTING_CUSIP_MAPPING','intake_status':'PENDING_IDENTITY'}
        if len(matches)==1:
            m=matches.iloc[0]
            val=lambda x:'' if pd.isna(m.get(x)) else str(m.get(x))
            ticker=val('ticker');code=val('moomoo_transport_code') or val('moomoo_candidate_code')
            status=val('mapping_status')
            out.update(ticker=ticker or None,provider_code=code or None,mapping_source=val('mapping_source'),mapping_status=status)
            rejected=any(s in (status+' '+val('transport_alias_status')+' '+val('transport_interval_status')).upper() for s in ['REJECT','INVALID','UNRESOLVED','QUARANTINE','BLOCKED'])
            if ticker and code.startswith('US.') and not rejected:
                out['intake_status']='EXISTING_MAPPING_REQUIRES_LIFECYCLE_REVIEW'
        elif len(matches)>1:out['mapping_status']='AMBIGUOUS_EXISTING_CUSIP_MAPPING'
        out['raw_latest']=availability.get((out['ticker'],'raw'))
        out['qfq_latest']=availability.get((out['ticker'],'qfq'))
        out['identity_evidence_path']=str(identity_path)
        rows.append(out)
    frame=pd.DataFrame(rows)
    # One provider code assigned to multiple simultaneous CUSIPs is not silently
    # resolved by choosing the first ticker or company name.
    ambiguous=frame.dropna(subset=['provider_code']).groupby('provider_code').cusip.nunique()
    bad=set(ambiguous[ambiguous>1].index)
    frame.loc[frame.provider_code.isin(bad),'intake_status']='PENDING_SIMULTANEOUS_IDENTITY_REVIEW'
    output=quarter_root/'security_onboarding.parquet'
    temporary=output.with_suffix('.parquet.tmp');frame.to_parquet(temporary,index=False,compression='zstd')
    # Derived queue is deterministic for the current data catalog. Prior versions
    # are preserved by content hash before a refresh.
    if output.exists() and sha256(output)!=sha256(temporary):
        backup=quarter_root/f'security_onboarding_{sha256(output)[:20]}.parquet'
        if not backup.exists():backup.write_bytes(output.read_bytes())
    temporary.replace(output)
    lineage={'role':'DERIVED_DATA_INTAKE_QUEUE_NOT_IDENTITY_AUTHORITY','inputs':[
        {'path':str(p),'sha256':sha256(p)} for p in [qp,identity_path,history_path]],
        'strategy_membership_changed':False}
    with sqlite3.connect(store.catalog_path) as conn:
        register_file(conn,'security_onboarding_external25','','',output,len(frame),
                      str(frame.effective_date.min()),str(frame.effective_date.max()),'EXISTING_CUSIP_MAPPING',lineage)
    return {'path':str(output),'securities':len(frame),'new_historical_cusips':int(frame.first_seen_in_history.sum()),
            'intake_status_counts':frame.intake_status.value_counts().to_dict(),
            'raw_available':int(frame.raw_latest.notna().sum()),'qfq_available':int(frame.qfq_latest.notna().sum())}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--quarter-root',type=Path,required=True)
    ap.add_argument('--identity-path',type=Path,required=True);ap.add_argument('--historical-universe',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(prepare(DataStore(),args.quarter_root,args.identity_path,args.historical_universe),ensure_ascii=False))


if __name__=='__main__':main()
