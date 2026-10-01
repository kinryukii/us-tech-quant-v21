"""Deduplicate and qualify the 45 requested securities' existing consumed events.

No price fetch, source mutation, model fitting, or universe change.  An event
qualification is only one dependency of a usable security-day; base-coordinate,
identity, lifecycle, raw-price and feature gates remain mandatory downstream.
"""
from pathlib import Path
import hashlib,json,math
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
WS=OUT.parents[2]
LATEST=WS/'a2_latest_effective_joint_20260927'
STAGE=WS/'a2_strict_method_retrain_20260926/test2026_stage'
OTHER=WS/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'
LINEAGE=LATEST/'followup_review/input_lineage'
INPUT_HASHES={}

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def bind(p):
    p=Path(p);INPUT_HASHES[str(p)]=sha(p);return p
def csv(p):return pd.read_csv(bind(p),dtype={'cusip':str,'historical_cusips':str,'current_saved_cusip':str})
def pq(p):return pd.read_parquet(bind(p))
def js(p):return json.loads(bind(p).read_text(encoding='utf-8-sig'))
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def ds(v):return str(pd.Timestamp(v).date())
def write_df(d,name):
    d.to_parquet(OUT/(name+'.parquet'),index=False)
    d.to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig')
def normalized_class(ticker,classes):
    # Multiple 13F labels for exactly the same CUSIP; retain all originals below.
    if ticker=='CRWD':return 'CL A'
    if ticker=='SLMT':return 'CL B'
    return '|'.join(sorted({' '.join(str(x).upper().split()) for x in classes}))

def main():
    names=csv(LINEAGE/'TICKER_INPUT_LINEAGE.csv')
    consumed=csv(LINEAGE/'CONSUMED_EVENT_EVIDENCE_THROUGH_SIGNAL.csv')
    full=pq(STAGE/'identity_feature_application_r1/CONSUMED_REHAB_EVENT_AUDIT.parquet')
    full['event_date']=pd.to_datetime(full.event_date)
    late=full.loc[full.ticker.isin(names.ticker)&full.event_date.gt('2026-09-22')&full.event_date.le('2026-09-24')]
    assert late.empty,'New terminal-day events must be reviewed before extending day table'
    gate=pq(STAGE/'r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet')
    priority=csv(STAGE/'r4_event_pit/ALL_1094_EVENT_PRIORITY.csv')
    reviewed=js(OUT/'reviewed_sources.json')
    reviews={(x['ticker'],x['event_date']):x for x in reviewed['events']}
    for rel in ['r4_event_pit/TEN_CASH_EVENTS_ORIGINAL_CONTRACT_VERDICTS.csv','r7_cash_first_event_proposal/R7_TWELVE_CASH_EVENT_VERDICTS.csv','r7_cash_first_event_proposal/EVENT_SOURCES.json','finra_rule_11140_2026_snapshot.html']:
        bind(STAGE/rel)
    for r in reviews.values():
        if r.get('local_path'):
            assert sha(bind(STAGE/r['local_path']))==r['sha256']
        for item in r.get('identity_bridge_sources',[]):
            assert sha(bind(OUT.parent/'identity/official_sources'/item['name']))==item['sha256']
    rehab_paths=[Path(r'D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet')]
    rehab_paths += [OTHER/x/'rehab_factors.parquet' for x in ['REHAB_NEW_OCCUPIED_ONLY','REHAB_SUBSCRIPTION_ONLY','REHAB_AUTHORITY_ALIASES_ONLY','REHAB_OFFICIAL_COMMON_ALIASES_ONLY']]
    rehab=[]
    for p in rehab_paths:
        d=pq(p);d['rehab_source_path']=str(p);d['rehab_source_sha256']=sha(p);rehab.append(d)
    rehab=pd.concat(rehab,ignore_index=True)
    rehab['event_date']=pd.to_datetime(rehab.ex_div_date).dt.strftime('%Y-%m-%d')
    raw_dte=None
    rows=[]
    for e in consumed.to_dict('records'):
        ticker=e['ticker'];date=e['event_date'];gh=gate.loc[gate.ticker.eq(ticker)]
        cusips=sorted(gh.cusip.unique());assert len(cusips)==1,(ticker,cusips)
        cusip=cusips[0];classes=sorted(gh.title_of_class.unique());cls=normalized_class(ticker,classes)
        code=str(gh.transport_used.iloc[-1]);rr=rehab.loc[rehab.code.eq(code)&rehab.event_date.eq(date)]
        # Original snapshots can overlap; conflicting economically material rows never auto-pass.
        rr=rr.loc[np.isclose(rr.forward_adj_factorA.astype(float),e['factor_a'],rtol=0,atol=1e-10)&np.isclose(rr.forward_adj_factorB.astype(float),e['factor_b'],rtol=0,atol=1e-10)]
        assert len(rr),(ticker,date,code)
        termcols=[c for c in rr.columns if c not in ['code','ex_div_date','event_date','rehab_source_path','rehab_source_sha256','backward_adj_factorA','backward_adj_factorB']]
        variants=[]
        for r in rr.to_dict('records'):
            v={c:float(r[c]) for c in termcols if pd.notna(r[c])}
            if canon(v) not in [canon(x) for x in variants]:variants.append(v)
        vendor_conflict=len(variants)>1
        terms=variants[0]
        cash=sum(terms.get(c,0) for c in ['per_cash_div','special_dividend']) if not e['share_event'] else None
        typ='COMPOSITE_SPINOFF_REVERSE_SPLIT' if ticker=='HON' and e['share_event'] else ('SHARE_SPLIT_OR_REVERSE_SPLIT' if e['share_event'] else 'CASH_DIVIDEND')
        instrument=cusip+'|'+cls
        stable=hashlib.sha256(canon({'instrument_key':instrument,'event_date':date,'event_type':typ,'terms':terms}).encode()).hexdigest()
        pri=priority.loc[priority.ticker.eq(ticker)&priority.event_date.eq(date)]
        prior=float(pri.prior_raw_close.iloc[0]) if len(pri) and pd.notna(pri.prior_raw_close.iloc[0]) else np.nan
        if ticker=='DTP' and not np.isfinite(prior):
            if raw_dte is None:raw_dte=pq(OTHER/'SUBSCRIPTION_US_DTE_RAW_DAY_K_INPUT_ONLY.parquet')
            before=raw_dte.loc[pd.to_datetime(raw_dte.trade_date).lt(date)].sort_values('trade_date')
            prior=float(before.iloc[-1].close)
        calc=math.floor((1-cash/prior)*1e5+1e-9)/1e5 if cash is not None and np.isfinite(prior) else np.nan
        cash_match=bool(np.isfinite(calc) and abs(calc-e['factor_a'])<1e-10 and e['factor_b']==0)
        r=reviews.get((ticker,date),{})
        status=r.get('status','UNKNOWN');why=r.get('reason','NO_DATED_PRIMARY_PUBLICATION_AND_EXACT_TERMS_EVIDENCE_IN_REVIEWED_RECEIPTS')
        publicdate=r.get('source_public_date');bound=(pd.Timestamp(publicdate,tz='UTC')+pd.Timedelta(days=2)) if publicdate else pd.NaT
        announcement_verified=bool(publicdate)
        term_verified=bool(r)
        value_verified=False
        if r and not e['share_event']:
            term_verified=abs(cash-r['cash_usd'])<1e-9 and r['record_date']==date
            value_verified=bool(term_verified and cash_match and cash/prior<.25 and pd.Timestamp(date).weekday()<5)
        elif r and r.get('new_shares_per_old') and ticker!='HON':
            value_verified=bool(abs((1/r['new_shares_per_old'])-e['factor_a'])<1e-9 and e['factor_b']==0)
        if vendor_conflict:
            status='CONFLICT';why='CONFLICTING_ECONOMIC_TERMS_IN_SAVED_VENDOR_SNAPSHOTS'
        elif status=='VERIFIED':
            assert announcement_verified and term_verified and value_verified
            assert bound<pd.Timestamp(date,tz='UTC')+pd.Timedelta(hours=13,minutes=30)
            why='DATED_PRIMARY_ANNOUNCEMENT_AND_EXACT_CAUSAL_FACTOR_RECONSTRUCTION'
        bridge_verified=(ticker not in ['BYND','SLMT','HON'] or not e['share_event'] or bool(r.get('identity_bridge_sources')))
        row={'event_key':'ev_'+stable,'instrument_key':instrument,'cusip':cusip,'normalized_class':cls,
            'original_class_labels':'|'.join(classes),'ticker':ticker,'transport_code':code,'event_date':pd.Timestamp(date),
            'source_event_date':pd.Timestamp(e['source_event_date']),'event_type':typ,'terms_json':canon(terms),
            'vendor_cash_usd':cash,'issuer_cash_usd':r.get('cash_usd'),'new_shares_per_old':r.get('new_shares_per_old'),
            'new_cusip':r.get('new_cusip'),'factor_a':e['factor_a'],'factor_b':e['factor_b'],
            'prior_raw_close':prior,'reconstructed_cash_factor_a':calc,'vendor_cash_factor_arithmetic_matches':cash_match,
            'source_public_date':publicdate,'public_at_upper_bound_utc':bound,'public_clock_verified':announcement_verified,
            'publication_basis':r.get('publication_basis','NONE'),'event_terms_verified':term_verified,
            'full_value_reconstruction_verified':value_verified,'identity_event_bridge_verified':bridge_verified,
            'status':status,'reason':why,'source_url':r.get('url',''),'source_fact':r.get('fact',''),
            'source_original_path':str(STAGE/r['local_path']) if r.get('local_path') else '',
            'source_original_sha256':r.get('sha256',''),'source_original_http_body_saved':r.get('original_http_body_saved',False),
            'review_receipt_path':str(OUT/'reviewed_sources.json'),'review_receipt_sha256':sha(OUT/'reviewed_sources.json'),
            'identity_bridge_sources_json':canon(r.get('identity_bridge_sources',[])),
            'rehab_paths_json':canon(sorted(rr.rehab_source_path.unique().tolist())),
            'rehab_hashes_json':canon(sorted(rr.rehab_source_sha256.unique().tolist())),
            'historical_vendor_actual_receipt_observed':False,
            'scope':'RECONSTRUCTED_FORWARD_PRICE_INDEX_EVENT_NOT_SHAREHOLDER_RETURN',
            'dedup_source_rows':len(rr),'vendor_terms_conflict':vendor_conflict}
        rows.append(row)
    events=pd.DataFrame(rows).drop_duplicates('event_key').sort_values(['ticker','event_date']).reset_index(drop=True)
    assert len(events)==97 and events.event_key.is_unique and set(events.status)<= {'VERIFIED','UNKNOWN','CONFLICT'}
    write_df(events,'event_qualification')
    dates=pq(LATEST/'data/calendar.parquet');dates=dates.loc[dates.is_test,'trade_date'].sort_values()
    assert pd.Timestamp(dates.max())==pd.Timestamp('2026-09-24')
    dr=[]
    for n in names.to_dict('records'):
        ticker=n['ticker'];gh=gate.loc[gate.ticker.eq(ticker)];cusip=gh.cusip.iloc[0]
        instrument=cusip+'|'+normalized_class(ticker,gh.title_of_class.unique())
        ev=events.loc[events.ticker.eq(ticker)]
        for d in dates:
            d=pd.Timestamp(d);used=ev.loc[ev.event_date.le(d)]
            # Clock uses before day open, stricter than a close signal. No later event is read.
            cutoff=d.tz_localize('America/New_York')+pd.Timedelta(hours=9,minutes=30)
            bad=used.loc[used.status.ne('VERIFIED')|used.public_at_upper_bound_utc.gt(cutoff.tz_convert('UTC'))]
            clock=bool(used.public_clock_verified.all() and (used.public_at_upper_bound_utc.le(cutoff.tz_convert('UTC'))).all())
            value=bool(used.full_value_reconstruction_verified.all())
            bridge=bool(used.identity_event_bridge_verified.all())
            dr.append({'ticker':ticker,'instrument_key':instrument,'cusip':cusip,'date':d,
                'all_consumed_events_verified':len(bad)==0,'full_value_reconstruction_verified':value,
                'public_clock_verified':clock,'identity_event_bridge_verified':bridge,'consumed_event_count':len(used),
                'unresolved_event_count':len(bad),'unresolved_event_keys':'|'.join(bad.event_key),
                'status':'VERIFIED' if not len(bad) else ('CONFLICT' if bad.status.eq('CONFLICT').any() else 'UNKNOWN'),
                'no_consumed_2026_events':used.empty,'scope':'CONSUMED_2026_EVENT_PREFIX_ONLY_REQUIRES_EXTERNAL_BASE_IDENTITY_LIFECYCLE_AND_RAW_GATES'})
    daily=pd.DataFrame(dr);write_df(daily,'security_day_qualification')
    intervals=[]
    for ticker,g in daily.groupby('ticker',sort=True):
        g=g.sort_values('date').copy()
        groupcols=['status','all_consumed_events_verified','full_value_reconstruction_verified','public_clock_verified','identity_event_bridge_verified','unresolved_event_keys','consumed_event_count']
        g['_g']=g[groupcols].ne(g[groupcols].shift()).any(axis=1).cumsum()
        for _,b in g.groupby('_g'):
            row=b.iloc[0].drop(['date','_g']).to_dict();row['interval_start']=b.date.min()
            after=dates.loc[dates>b.date.max()]
            row['interval_end_exclusive']=pd.Timestamp(after.iloc[0]) if len(after) else pd.Timestamp('2026-09-25')
            row['trading_days']=len(b);intervals.append(row)
    write_df(pd.DataFrame(intervals),'qualified_intervals')
    last=csv(LATEST/'LAST_TEST_DATE_TARGETS.csv')
    last=last.loc[last[['quarter','cusip','new_buy_eligible']].isna().any(axis=1)]
    mapped=last[['candidate','policy','signal_date','ticker']].merge(events[['ticker','event_key','event_date','status','reason']],on='ticker',how='left')
    write_df(mapped,'account_event_mapping')
    unresolved=events.loc[events.status.ne('VERIFIED')];write_df(unresolved,'unresolved_events')
    assert all(sha(p)==h for p,h in INPUT_HASHES.items()),'Frozen input mutated'
    summ={'scope':'45 follow-up tickers only; not whole universe','tickers':len(names),'event_tickers':events.ticker.nunique(),
        'event_count':len(events),'status_counts':events.status.value_counts().to_dict(),'daily_rows':len(daily),
        'daily_status_counts':daily.status.value_counts().to_dict(),'start':ds(dates.min()),'end':ds(dates.max()),
        'last_day_status_counts':daily.loc[daily.date.eq(dates.max()),'status'].value_counts().to_dict(),
        'verified_event_tickers':events.loc[events.status.eq('VERIFIED'),'ticker'].tolist(),
        'source_hashes':INPUT_HASHES,'frozen_inputs_unchanged':True,'tests':{'97_unique_event_keys':True,'distinct_GOOG_GOOGL_instruments':events.loc[events.ticker.isin(['GOOG','GOOGL']),'instrument_key'].nunique()==2,
        'terminal_dates_checked_in_full_consumed_audit':True,'status_verified_requires_clock_terms_factor':True,
        'past_prefix_unchanged_by_later_events':True},
        'limitations':['Historical actual vendor receipt is not established. VERIFIED means economic event announcement and causal forward-coordinate reconstruction under the recorded source tier.',
        'A dated historical press release/SEC or exchange notice supports its stated announcement date; current retrieval timestamp alone never sets historical public_at.',
        'For a date-only announcement, public_at upper bound is the second following UTC midnight, conservatively later than end of the stated date in any civil timezone.',
        'EXAS has zero 2026 consumed events; this cannot clear its lifecycle or price gate.',
        'Each daily result is an event-only gate. External identity intervals, original base-coordinate checks, raw price availability and lifecycle checks must all pass.',
        'Cash reconstruction uses floor5(1-cash/prior raw close), zero affine b; these are price-index coordinates, not total shareholder returns.']}
    (OUT/'EVENT_QUALIFICATION_AUDIT.json').write_text(json.dumps(summ,indent=2,ensure_ascii=False,default=str),encoding='utf8')
    print(json.dumps({k:v for k,v in summ.items() if k not in ['source_hashes','limitations']},indent=2,ensure_ascii=False,default=str))

if __name__=='__main__':main()
