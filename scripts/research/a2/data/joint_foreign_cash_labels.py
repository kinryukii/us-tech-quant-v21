"""B-only unpaid native-currency H5 target candidate; no account/PIT admission.

Explicit EUR label types extend, rather than alter, the CAD-only shared owner.
All entitlement and claim valuation arithmetic stays in that owner. Paid windows,
foreign post-verified facts and mixed native currencies remain blocked. The caller
owns complete event/source/class coverage and exact input-file qualification.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib
import html
import math
from pathlib import Path
import re
import numpy as np
import pandas as pd
from scripts.research.a2.data.joint_input_binding import cash_inclusive_shareholder_open_targets
from scripts.research.a2.data import consensus_h10_fx_sources as h10
from scripts.v22 import corporate_action_transition_r1 as owner

EUR_PER_RAW_OLD_SHARE = 'EUR_PER_RAW_OLD_SHARE'
EUR_PER_USD = 'EUR_PER_USD'
_BOUNDARY = pd.Timestamp('2026-01-01',tz='UTC')

@dataclass(frozen=True)
class SourceBackedEURCashEvent(owner.SourceBackedForeignCashEvent):
    """Explicit EUR gross ordinary entitlement, admitted only by this label wrapper."""
    def __post_init__(self):
        if (self.action_type != 'CASH_DIVIDEND' or self.currency != 'EUR'
                or self.amount_unit != EUR_PER_RAW_OLD_SHARE
                or self.quantity_coordinate != owner.RAW_OLD_SHARE_COORDINATE
                or self.source_type not in owner.AUTHORIZED_SOURCE_TYPES
                or not re.fullmatch(r'[0-9a-fA-F]{64}',str(self.source_fingerprint))
                or type(self.cash_per_old_share) not in (float,int)
                or not math.isfinite(self.cash_per_old_share) or self.cash_per_old_share < 0):
            raise ValueError('SOURCE_QUALIFIED_GROSS_EUR_COMMON_DIVIDEND_REQUIRED')
        if any(not isinstance(v,str) or not v.strip() for v in
                (self.event_id,self.old_security_id,self.ticker,self.source_reference)):
            raise ValueError('EUR_CASH_SOURCE_AND_DATED_SECURITY_REQUIRED')
        if any(v in self.old_security_id.upper() for v in
                ('FROZEN_VENDOR:','UNKNOWN','PLACEHOLDER','UNCONFIRMED')):
            raise ValueError('EUR_CASH_PLACEHOLDER_SECURITY_FORBIDDEN')
        ex,record,pay=map(owner._entitlement_day,(self.ex_date,self.record_date,self.pay_date))
        available=owner._entitlement_available(self.available_at)
        if (not pd.Timestamp('2023-01-01') <= ex < pd.Timestamp('2026-01-01')
                or record < ex or pay < ex or available >= _BOUNDARY):
            raise ValueError('EUR_CASH_PRE2026_SOURCE_EX_AND_KNOWN_SCHEDULE_REQUIRED')

@dataclass(frozen=True)
class SourceBackedEURFXMark(owner.SourceBackedFXMark):
    """EUR per USD, derived explicitly from the H10 asterisk USD-per-EUR row."""
    def __post_init__(self):
        observation=owner._entitlement_day(self.observation_date)
        available=owner._entitlement_available(self.available_at)
        local=available.tz_convert('America/New_York')
        if (self.currency != 'EUR' or self.rate_unit != EUR_PER_USD
                or not pd.Timestamp('2023-01-01') <= observation < pd.Timestamp('2026-01-01')
                or available >= _BOUNDARY or observation.date() > local.date()
                or (local.hour,local.minute,local.second,local.microsecond)!=(23,59,59,0)
                or type(self.currency_per_usd) not in (float,int)
                or not math.isfinite(self.currency_per_usd) or self.currency_per_usd <= 0
                or not isinstance(self.source_reference,str) or not self.source_reference.strip()
                or not re.fullmatch(r'[0-9a-fA-F]{64}',str(self.source_fingerprint))):
            raise ValueError('PRE2026_H10_EUR_PER_USD_PUBLICATION_BOUND_MARK_REQUIRED')

_EVENT_TYPES=(owner.SourceBackedForeignCashEvent,SourceBackedEURCashEvent)
_MARK_TYPES=(owner.SourceBackedFXMark,SourceBackedEURFXMark)

def _open(day):
    return (pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')

def _eligible_fx(marks,*,currency,as_of,cutoff):
    candidates=[]
    for mark in marks:
        if type(mark) not in _MARK_TYPES:
            raise ValueError('FOREIGN_LABEL_EXACT_CAD_OR_EUR_FX_TYPE_REQUIRED')
        if mark.currency != currency:
            continue
        # Availability precedes value validation/selection. Never inspect a late
        # mark's rate, even if that rate is corrupted/deserialized garbage.
        known=owner._entitlement_available(mark.available_at)
        if known > as_of:
            continue
        if known >= cutoff:
            raise ValueError('FOREIGN_FX_NOT_BEFORE_FOLD_CUTOFF')
        mark.__post_init__()
        candidates.append(mark)
    selected=owner.select_foreign_fx_mark(candidates,as_of=as_of)
    if selected is None:
        raise ValueError('FOREIGN_LABEL_NO_PUBLISHED_FX_AT_SESSION_OPEN')
    return selected

def foreign_cash_inclusive_shareholder_open_targets(keys,raw,calendar,event_records,
        apply_event_windows,*,cash_events=(),foreign_cash_events=(),foreign_fx_marks=(),
        cutoff,label_only_post_verified_cash=False,research_cash_authority=None,
        cash_publication_proofs=()):
    """Pure cash-inclusive descendant, limited to native claims unpaid at exit.

    Native source facts must be known by ex Open, strictly before annual fit.
    Latest published FX is selected at every held session, including exit Open.
    Entry-ex excluded / exit-ex included, and original pre-ex quantity snapshots
    feed the unchanged entitlement owner. No paid conversion/fee rule is created.
    No-foreign input returns the original USD function's exact frame.
    """
    events=tuple(foreign_cash_events);marks=tuple(foreign_fx_marks)
    usd_events=tuple(cash_events);records=tuple(event_records)
    frame=cash_inclusive_shareholder_open_targets(keys,raw,calendar,records,
        apply_event_windows,cash_events=usd_events,cutoff=cutoff,
        label_only_post_verified_cash=label_only_post_verified_cash,
        research_cash_authority=research_cash_authority,
        cash_publication_proofs=cash_publication_proofs)
    if not events:
        if marks: raise ValueError('FOREIGN_FX_WITHOUT_FOREIGN_EVENT_CATALOGUE')
        return frame
    if any(type(e) not in _EVENT_TYPES for e in events):
        raise ValueError('FOREIGN_LABEL_EXACT_CAD_OR_EXPLICIT_EUR_EVENT_TYPE_REQUIRED')
    if any(type(m) not in _MARK_TYPES for m in marks):
        raise ValueError('FOREIGN_LABEL_EXACT_CAD_OR_EUR_FX_TYPE_REQUIRED')
    if len({e.event_id for e in events}) != len(events):
        raise ValueError('FOREIGN_LABEL_DUPLICATE_EVENT_ID')
    if {e.event_id for e in events}&{e.event_id for e in usd_events}:
        raise ValueError('FOREIGN_LABEL_USD_FOREIGN_DUPLICATE_EVENT_ID')
    cut=owner._entitlement_available(cutoff)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar));positions={d:i for i,d in enumerate(dates)}
    opening=raw.set_index(['ticker',pd.to_datetime(raw.trade_date)]).open
    frame['label_foreign_cash_event_count']=0
    frame['label_foreign_currency']=''
    frame['label_foreign_receivable_usd_per_entry_share']=0.
    frame['foreign_label_reason']='NO_RELEVANT_NATIVE_EVENT'
    frame['foreign_label_fx_source_refs']=[() for _ in range(len(frame))]
    for i,row in frame.iterrows():
        if not bool(row.label_available):continue
        entry,end=pd.Timestamp(row.execution_date),pd.Timestamp(row.label_end_date)
        try:
            relevant=tuple(e for e in events if e.ticker==row.ticker
                and entry < owner._entitlement_day(e.ex_date) <= end)
            if not relevant:continue
            currencies={e.currency for e in relevant}
            if len(currencies)!=1 or not currencies.issubset({'CAD','EUR'}):
                raise ValueError('FOREIGN_LABEL_SINGLE_NATIVE_CURRENCY_PER_ROW_REQUIRED')
            currency=next(iter(currencies))
            if any(e.ticker==row.ticker and entry < owner._entitlement_day(e.ex_date) <= end for e in usd_events):
                raise ValueError('FOREIGN_LABEL_MIXED_USD_NATIVE_WINDOW_BLOCKED')
            for event in relevant:
                # Source-clock proof comes before any amount validation/value use.
                known=owner._entitlement_available(event.available_at)
                if known >= cut or known > _open(event.ex_date):
                    raise ValueError('FOREIGN_LABEL_SOURCE_UNKNOWN_OR_LATE_FOR_EX_OR_FOLD')
                if event.old_security_id != row.security_id:
                    raise ValueError('FOREIGN_LABEL_EXACT_SECURITY_ID_MISMATCH')
                event.__post_init__()
                if owner._entitlement_day(event.ex_date) not in positions:
                    raise ValueError('FOREIGN_LABEL_EX_NOT_LEGAL_SESSION')
                if owner._entitlement_day(event.pay_date) <= end:
                    raise ValueError('FOREIGN_LABEL_PAID_BY_EXIT_NOT_SUPPORTED')
            state=None;receivable=0.;used={};known_at=pd.Timestamp(row.label_available_at)
            for di in range(positions[entry]+1,positions[end]+1):
                day=dates[di];at=_open(day)
                if not any(owner._entitlement_day(e.ex_date)<=day for e in relevant):continue
                selected=_eligible_fx(marks,currency=currency,as_of=at,cutoff=cut)
                probe=pd.DataFrame({'ticker':[row.ticker],'execution_date':[entry],
                    'label_end_date':[dates[di-1]]})
                quantity,bad,_=apply_event_windows(probe,records)
                if bool(bad[0]) or not np.isfinite(quantity[0]) or quantity[0]<=0:
                    raise ValueError('FOREIGN_LABEL_PRE_EX_QUANTITY_UNQUALIFIED')
                applied=owner.apply_entitlement_lifecycle(relevant,
                    {row.security_id:float(quantity[0])},0.,execution_date=day,
                    session_open_at=at,security_tickers={row.security_id:row.ticker},
                    quantity_coordinate=owner.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,
                    foreign_fx_mark=selected,foreign_conversion_friction_bps=25.)
                if not applied.accounting_qualified:
                    raise ValueError('FOREIGN_LABEL_ENTITLEMENT_UNQUALIFIED:'+str(applied.state.blocked_events))
                if applied.cash != 0. or applied.fx_conversion_fee_usd != 0.:
                    raise ValueError('FOREIGN_LABEL_UNPAID_ONLY_CASH_OR_FEE_UNEXPECTED')
                if any(c.currency!=currency or c.old_security_id!=row.security_id
                        for c in applied.state.foreign_cash_receivables):
                    raise ValueError('FOREIGN_LABEL_CLAIM_COORDINATE_MISMATCH')
                receivable=applied.receivable_value_usd;state=applied.state
                used[(selected.source_reference,selected.source_fingerprint)]=None
                known_at=max(known_at,owner._entitlement_available(selected.available_at))
            known_at=max([known_at]+[owner._entitlement_available(e.available_at) for e in relevant])
            value=float(row.y_open5)+receivable/float(opening.loc[(row.ticker,entry)])
            if not np.isfinite(value) or known_at>=cut:
                raise ValueError('FOREIGN_LABEL_NONFINITE_VALUE_OR_LATE_KNOWLEDGE')
        except (ValueError,TypeError,KeyError) as error:
            frame.at[i,'label_available']=False;frame.at[i,'y_open5']=np.nan
            frame.at[i,'label_unsupported_common_event']=True
            frame.at[i,'foreign_label_reason']=str(error)
            continue
        frame.at[i,'y_open5']=value
        frame.at[i,'label_cash_receivable_per_entry_share']=float(row.label_cash_receivable_per_entry_share)+receivable
        frame.at[i,'label_foreign_receivable_usd_per_entry_share']=receivable
        frame.at[i,'label_foreign_currency']=currency
        frame.at[i,'label_foreign_cash_event_count']=len(relevant)
        frame.at[i,'label_cash_event_count']=int(row.label_cash_event_count)+len(relevant)
        frame.at[i,'label_common_event_count']=int(row.label_common_event_count)+len(relevant)
        frame.at[i,'label_available_at']=known_at
        frame.at[i,'foreign_label_fx_source_refs']=tuple(dict(path=p,sha256=s) for p,s in used)
        frame.at[i,'foreign_label_reason']='QUALIFIED_UNPAID_NATIVE_CLAIM_CALLER_SOURCE_COVERAGE_REQUIRED'
        frame.at[i,'label_coordinate']='CASH_INCLUSIVE_UNPAID_NATIVE_FX_SHAREHOLDER_OPEN_H5_LABEL_V1'
        frame.at[i,'target_source']='EXISTING_QUANTITY_USD_AND_FOREIGN_ENTITLEMENT_OWNER_EXPLICIT_EUR_LABEL_TYPES_V1'
    return frame

def parse_label_h10_release(path,*,expected_sha256,expected_release_date,currency,as_of):
    """Physically pinned existing edition, causal gate before parsing rate cells.

    CAD parsing delegates unchanged. EUR requires source asterisk AND exact unit
    footnote: source USD/EUR is inverted to EUR/USD; the owner then divides claim.
    No network, no price fallback, no latest/current H10 discovery.
    """
    if re.match(r'^\s*(?:[EF]:|[\\/]{2}[?.][\\/][EF]:)',str(path),re.I):
        raise ValueError('EF_PATH_FORBIDDEN_BEFORE_FILESYSTEM_IO')
    release=owner._entitlement_day(expected_release_date)
    at=owner._entitlement_available(as_of)
    if not pd.Timestamp('2023-01-01') <= release < pd.Timestamp('2026-01-01') or at>=_BOUNDARY:
        raise ValueError('FOREIGN_LABEL_PRE2026_RELEASE_AND_EXIT_CLOCK_REQUIRED')
    available=(release+pd.Timedelta(hours=23,minutes=59,seconds=59)).tz_localize('America/New_York').tz_convert('UTC')
    if available>at:
        raise ValueError('H10_EDITION_NOT_PUBLISHED_BY_LABEL_SESSION_OPEN')
    if currency not in ('CAD','EUR'):raise ValueError('FOREIGN_LABEL_H10_CAD_OR_EUR_ONLY')
    cad=h10.parse_cad_h10_release(path,expected_sha256=expected_sha256,expected_release_date=expected_release_date)
    if currency=='CAD':return cad
    raw=Path(path).read_bytes()  # owner already bounded and physically verified it
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('H10_EDITION_SOURCE_CHANGED')
    unit=re.search(rb'<div[^>]*class=[\"\']tableunit[\"\'][^>]*>(.*?)</div>',raw,re.I|re.S)
    foot=re.search(rb'<div[^>]*class=[\"\']footnotes[\"\'][^>]*>(.*?)</div>',raw,re.I|re.S)
    clean=lambda b:' '.join(html.unescape(re.sub('<[^>]*>',' ',b.decode('utf8'))).split())
    if (unit is None or 'except as noted by an asterisk' not in clean(unit.group(1))
            or foot is None or '* U.S. dollars per currency unit.' not in clean(foot.group(1))):
        raise ValueError('H10_EUR_ASTERISK_USD_PER_CURRENCY_FOOTNOTE_REQUIRED')
    rows=list(re.finditer(rb'<tr[^>]*>\s*<th[^>]*>\s*\*EMU MEMBERS\s*</th>(.*?)</tr>',raw,re.I|re.S))
    if len(rows)!=1:raise ValueError('H10_UNIQUE_ASTERISK_EMU_MEMBERS_ROW_REQUIRED')
    cells=h10._Cells();cells.feed(rows[0].group(0).decode('utf8'))
    if len(cells.cells)!=7 or cells.cells[:2]!=['*EMU MEMBERS','EURO']:
        raise ValueError('H10_EUR_EXACT_ASTERISK_EURO_COORDINATE_REQUIRED')
    head=re.search(rb'<thead[^>]*>(.*?)</thead>',raw,re.I|re.S)
    labels=h10._Cells();labels.feed(head.group(1).decode('utf8'))
    # All dates have already passed the original CAD owner's header/time guard.
    days=[m['observation_date'] for m in cad['observations']]+cad['no_data_observation_dates']
    by_monthday={pd.Timestamp(d).strftime('%m-%d'):d for d in days}
    observations=[by_monthday[datetime.strptime(v.replace('.',''),'%b %d').strftime('%m-%d')]
        for v in labels.cells[2:]]
    marks=[];missing=[]
    for day,value in zip(observations,cells.cells[2:]):
        if value=='ND':missing.append(day);continue
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value):raise ValueError('H10_EXPLICIT_EUR_RATE_REQUIRED')
        usd_per_eur=float(value)
        if not math.isfinite(usd_per_eur) or usd_per_eur<=0:raise ValueError('H10_POSITIVE_USD_PER_EUR_REQUIRED')
        mark=SourceBackedEURFXMark('EUR',EUR_PER_USD,day,str(available),1./usd_per_eur,str(path),expected_sha256)
        marks.append(asdict(mark))
    return dict(schema='B_UNPAID_LABEL_PRE2026_H10_EUR_SOURCE_FACTS_R1',
        release_date=cad['release_date'],available_at=str(available),source_ref=cad['source_ref'],
        source_quote_unit='USD_PER_EUR_ASTERISK_FOOTNOTE',quote_unit=EUR_PER_USD,
        source_to_mark_rule='1 / source USD_PER_EUR',claim_to_usd_rule='native claim / EUR_PER_USD',
        availability_clock=cad['availability_clock'],observations=marks,
        no_data_observation_dates=missing,strict_PIT_certified=False,
        historical_account_or_decision_eligibility_granted=False,paid_cases_supported=False)
