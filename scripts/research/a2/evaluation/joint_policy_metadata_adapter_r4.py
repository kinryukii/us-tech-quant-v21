"""Engineering-only exact epoch carry for R4 policy metadata discovery.

No new science, estimator, account or risk refresh. The original helper builds
all first-quarter/gap/change cases. A carry is a proof over immutable metadata:
consecutive common session, same complete domain and UID, one known UID row per
asset, no past rewrite. Missing proof uses the original complete-history helper.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import pandas as pd
from scripts.research.a2.evaluation import joint_policy_execution_r4 as policy
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar,_clock
from scripts.common.storage_paths import assert_safe_output_path,resolve
old=policy.old
BINDING='POLICY_METADATA_ENGINEERING_BINDING_R1.json'
AUDIT='POLICY_METADATA_EQUIVALENCE_AUDIT_R1.json'


def identity(pool):
    return {k:pool[k] for k in ('assets','asset_uids','asset_epochs','segment_starts','blocked_assets')}


@dataclass(frozen=True)
class ImmutableHistory:
    path:str
    sha256:str
    size:int
    mtime_ns:int
    ctime_ns:int
    synthetic:bool=False
    def unchanged(self):
        if self.synthetic:return True
        current=Path(self.path).stat()
        return (current.st_size,current.st_mtime_ns,current.st_ctime_ns)==(self.size,self.mtime_ns,self.ctime_ns)


def history_witness(reader):
    if not isinstance(reader,old.ProjectedReader) or reader.phase!='support':
        raise policy.PolicyInputBlocked('EXACT_EXISTING_PROJECTED_METADATA_READER_REQUIRED')
    pin=reader.sources['prediction_features']
    if not isinstance(pin,dict) or not pin.get('physical_pre2026_guard'):
        raise policy.PolicyInputBlocked('EXACT_FROZEN_METADATA_SNAPSHOT_REQUIRED')
    path=old._safe_source(pin['path'])
    old._pin(path,pin['sha256'],'immutable_policy_feature_history')
    stat=path.stat()
    return ImmutableHistory(str(path),pin['sha256'],stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)


class EpochCarryMetadataPool(policy.DailyMetadataPool):
    def __init__(self,reader,days,*,witness=None,audit_dates=()):
        super().__init__(reader,days)
        self.witness=history_witness(reader) if witness is None else witness
        if not isinstance(self.witness,ImmutableHistory):
            raise policy.PolicyInputBlocked('TYPED_IMMUTABLE_HISTORY_WITNESS_REQUIRED')
        if self.witness.synthetic and isinstance(reader,old.ProjectedReader):
            raise policy.PolicyInputBlocked('SYNTHETIC_WITNESS_CANNOT_ACTIVATE_REAL_READER')
        self.previous_pool=None
        self.positions={d:i for i,d in enumerate(days)}
        self.quarter_starts={pd.Timestamp(s['as_of']).tz_convert('America/New_York').tz_localize(None).normalize()
            for s in policy.producer.quarterly_schedule(days)}
        self.audit_dates={pd.Timestamp(d).normalize() for d in audit_dates}
        self.audits=[];self.carry_calls=0;self.full_helper_calls=0
    def __call__(self,day):
        day=pd.Timestamp(day).normalize()
        if day not in self.positions or day>=old.BOUNDARY or (self.loaded_through is not None and day<=self.loaded_through):
            raise policy.PolicyInputBlocked('MONOTONE_LEGAL_COMMON_SESSION_REQUIRED')
        if not self.witness.unchanged():
            # Rehash the original source; a changed frozen byte identity fails
            # closed. An administrative stat-only change forces full rebuild.
            old._pin(self.witness.path,self.witness.sha256,'immutable_policy_history_changed')
            consecutive=False
        else:
            consecutive=(self.loaded_through is not None and self.previous_pool is not None
                and self.positions[day]==self.positions[self.loaded_through]+1)
        if not consecutive or day in self.quarter_starts:
            result=super().__call__(day)
            self.full_helper_calls+=1
            raw=None
        else:
            added=self.reader.read('prediction_features',old.FEATURE_META,date_field='signal_date',
                start=self.loaded_through+pd.Timedelta(days=1),
                stop=(day+pd.Timedelta(days=1) if day+pd.Timedelta(days=1)<old.BOUNDARY else None))
            added_dates=pd.to_datetime(added.signal_date)
            if (added_dates<=self.loaded_through).any() or (added_dates>day).any():
                raise policy.PolicyInputBlocked('NEW_METADATA_WINDOW_REWRITES_PAST_OR_OBSERVES_FUTURE')
            self.history=pd.concat([self.history,added],ignore_index=True)
            raw=self.reader.read('raw_open_close',('ticker','trade_date'),date_field='trade_date',day=day)
            today=added.loc[added_dates.eq(day)]
            local=old.current_pool(today,raw,self.days,_clock(day))
            clean=(not added.duplicated(['ticker','signal_date']).any()
                and not local['blocked_assets'] and not self.previous_pool['blocked_assets'])
            same=(tuple(local['assets'])==tuple(self.previous_pool['assets'])
                and local['asset_uids']==self.previous_pool['asset_uids'])
            if clean and same:
                # For every asset the original backward loop traverses this new
                # known equal-UID session then the already-proved prior suffix.
                # Therefore its first break, start and epoch hash are identical.
                result={**local,'asset_epochs':dict(self.previous_pool['asset_epochs']),
                    'segment_starts':dict(self.previous_pool['segment_starts']),
                    'history':None,'history_not_materialised':True,
                    'epoch_carry_witness':dict(previous_common_session=str(self.loaded_through.date()),
                        current_common_session=str(day.date()),previous_identity_sha256=content_hash(identity(self.previous_pool)),
                        new_metadata_keys_sha256=content_hash(added),immutable_source_sha256=self.witness.sha256,
                        complete_domain_uid_match=True,no_unknown_or_duplicate_rows=True,no_past_rewrite=True,
                        no_source_availability_authority_upgrade=True)}
                self.carry_calls+=1
            else:
                result=old.current_pool(self.history,raw,self.days,_clock(day))
                self.full_helper_calls+=1
            self.loaded_through=day
        if day in self.audit_dates:
            if raw is None:
                raw=self.reader.read('raw_open_close',('ticker','trade_date'),date_field='trade_date',day=day)
            reference=old.current_pool(self.history,raw,self.days,_clock(day))
            actual,expected=content_hash(identity(result)),content_hash(identity(reference))
            audit=dict(date=day.date().isoformat(),original_identity_sha256=expected,
                adapter_identity_sha256=actual,exact_identity_equal=actual==expected,
                numerical_quote_score_label_values_read=0,outcome_reads=0,new_fit_units=0)
            self.audits.append(audit)
            if actual!=expected:raise policy.PolicyInputBlocked('METADATA_ADAPTER_NOT_EQUIVALENT_TO_ORIGINAL_HELPER')
        self.previous_pool=result
        return result


def audit(run):
    run=Path(run);source,_,_=policy.producer._source(run)
    reader=old.ProjectedReader(source,phase='support')
    days,_=_calendar(reader.read('calendar',('trade_date',),date_field='trade_date').trade_date)
    selected=days[(days>=pd.Timestamp('2023-01-03'))&(days<=pd.Timestamp('2023-01-05'))]
    if len(selected)!=3:raise policy.PolicyInputBlocked('EXACT_THREE_EARLY_LEGAL_METADATA_AUDIT_DAYS_REQUIRED')
    pool=EpochCarryMetadataPool(reader,days,audit_dates=selected)
    for day in selected:pool(day)
    result=dict(schema='B_R4_POLICY_METADATA_ENGINEERING_EQUIVALENCE_V1',research_id=policy.ID,
        original_code_ref=policy._ref(policy.__file__),adapter_code_ref=policy._ref(__file__),
        source_authority_ref=policy._ref(run/'SOURCE_AUTHORITY.json'),samples=pool.audits,
        source_witness=pool.witness.__dict__,carry_calls=pool.carry_calls,full_helper_calls=pool.full_helper_calls,
        all_exact_equal=all(a['exact_identity_equal'] for a in pool.audits),projections=reader.audit,
        numeric_reads=0,outcome_reads=0,new_fit_units=0,account_attempts=0,test2026_rows_read=0,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    old.write(run,AUDIT,result,immutable=True)
    return dict(status='METADATA_EQUIVALENCE_PASS',audit_ref=policy._ref(run/AUDIT),samples=3,
        full_helper_calls=pool.full_helper_calls,carry_calls=pool.carry_calls)


def support(run):
    run=Path(run);spec=policy._spec(run)
    proof=old.read_json(run/AUDIT)
    if proof['all_exact_equal'] is not True or proof['adapter_code_ref']!=policy._ref(__file__):
        raise policy.PolicyInputBlocked('CURRENT_SYNTHETIC_AND_REAL_METADATA_EQUIVALENCE_REQUIRED')
    binding=dict(schema='B_R4_POLICY_METADATA_ENGINEERING_BINDING_V1',research_id=policy.ID,
        policy_spec_ref=policy._ref(run/policy.SPEC),original_wrapper_ref=policy._ref(policy.__file__),
        adapter_code_ref=policy._ref(__file__),original_helper_ref=policy._ref(old.__file__),
        equivalence_audit_ref=policy._ref(run/AUDIT),source_authority_ref=policy._ref(run/'SOURCE_AUTHORITY.json'),
        risk_support_ref=policy._ref(run/policy.producer.SUPPORT),semantic_change=False,
        full_domain_uid_epoch_cadence_unchanged=True,extra_refreshes=0,numeric_reads=0,outcome_reads=0,
        new_fit_units=0,account_attempts=0,test2026_rows_read=0,
        source_history_assumption='CURRENT_PINNED_IMMUTABLE_FROZEN_BYTES; historical publication/revision remain UNKNOWN')
    old.write(run,BINDING,binding,immutable=True)
    original=policy.DailyMetadataPool
    # Existing wrapper's public metadata-factory binding, explicitly recorded.
    # Only this process is affected; original file and numerical code stay pinned.
    policy.DailyMetadataPool=EpochCarryMetadataPool
    try:
        return {**policy.support(run), 'engineering_binding_ref':policy._ref(run/BINDING)}
    finally:
        policy.DailyMetadataPool=original


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--phase',choices=['audit','support'],required=True)
    args=parser.parse_args();run=Path(args.run)
    # Independent metadata lease: does not reserve learned units/account paths.
    lease=run/'work/leases/policy_metadata_engineering'
    assert_safe_output_path(lease,kind='backtest',paths=resolve(old.REPO))
    (lease/'work').mkdir(parents=True,exist_ok=True)
    with old.task_writer(lease):
        result=audit(run) if args.phase=='audit' else support(run)
    print(json.dumps(old._json(result),allow_nan=False),flush=True)

if __name__=='__main__':main()
