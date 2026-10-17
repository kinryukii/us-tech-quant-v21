"""R2 metadata-only engineering guard over the exact R1 epoch carry owner.

Retain old source/audit. Reject unknown new UID rows for cached carry and derive
missing administrative MAIN scope from the immutable main-list membership.
No tuple, covariance, forecast, account, cadence or numerical pin changes.
"""
import copy
from pathlib import Path
import pandas as pd
from scripts.research.a2.evaluation import joint_policy_metadata_adapter_r4 as base
policy=base.policy
AUDIT='POLICY_METADATA_EQUIVALENCE_AUDIT_R2.json'
BINDING='POLICY_METADATA_ENGINEERING_BINDING_R2.json'
R1Pool=base.EpochCarryMetadataPool


class EpochCarryMetadataPoolR2(R1Pool):
    def __call__(self,day):
        day=pd.Timestamp(day).normalize()
        if self.loaded_through is not None and day>self.loaded_through and day<base.old.BOUNDARY:
            added=self.reader.read('prediction_features',base.old.FEATURE_META,date_field='signal_date',
                start=self.loaded_through+pd.Timedelta(days=1),
                stop=(day+pd.Timedelta(days=1) if day+pd.Timedelta(days=1)<base.old.BOUNDARY else None))
            dates=pd.to_datetime(added.signal_date)
            if (dates<=self.loaded_through).any() or (dates>day).any():
                raise policy.PolicyInputBlocked('NEW_METADATA_WINDOW_REWRITES_PAST_OR_OBSERVES_FUTURE')
            known=added.security_id.map(lambda uid:isinstance(uid,str) and bool(uid)).all()
            if not known or added.duplicated(['ticker','signal_date']).any():
                self.previous_pool=None  # Original full-history helper, no carry.
        return super().__call__(day)


def canonical_inherited(original,run,spec):
    projected=copy.deepcopy(spec)
    for row in projected['original_main']:
        if 'scope' in row and row['scope']!='MAIN':
            raise policy.PolicyInputBlocked('IMMUTABLE_MAIN_LIST_SCOPE_CONTRADICTION')
        row['scope']='MAIN'
    return original(run,projected)


def invoke(run,phase):
    run=Path(run)
    original_inherited=policy.inherited_metadata
    original_pool,original_audit,original_binding=base.EpochCarryMetadataPool,base.AUDIT,base.BINDING
    base.EpochCarryMetadataPool,base.AUDIT,base.BINDING=EpochCarryMetadataPoolR2,AUDIT,BINDING
    policy.inherited_metadata=lambda root,spec:canonical_inherited(original_inherited,root,spec)
    try:
        if phase=='support':
            proof=base.old.read_json(run/AUDIT)
            if proof.get('all_exact_equal') is not True:
                raise policy.PolicyInputBlocked('R2_REAL_METADATA_EQUIVALENCE_REQUIRED')
            extension=dict(schema='B_R4_POLICY_METADATA_R2_EXTENSION_BINDING_V1',research_id=policy.ID,
                R2_extension_code_ref=policy._ref(__file__),R1_adapter_code_ref=policy._ref(base.__file__),
                original_wrapper_ref=policy._ref(policy.__file__),policy_spec_ref=policy._ref(run/policy.SPEC),
                audit_ref=policy._ref(run/AUDIT),scope_projection='ONLY_MISSING_SCOPE_ON_ORIGINAL_MAIN_LIST_DERIVES_MAIN',
                unknown_or_duplicate_new_rows='ORIGINAL_FULL_HISTORY_HELPER_NO_CARRY',semantic_change=False,
                full_domain_UID_epoch_cadence_unchanged=True,new_fit_units=0,numeric_reads=0,outcome_reads=0,
                account_attempts=0,test2026_rows_read=0)
            base.old.write(run,'POLICY_METADATA_R2_EXTENSION_BINDING.json',extension,immutable=True)
        return base.audit(run) if phase=='audit' else base.support(run)
    finally:
        base.EpochCarryMetadataPool,base.AUDIT,base.BINDING=original_pool,original_audit,original_binding
        policy.inherited_metadata=original_inherited


def main():
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True);parser.add_argument('--phase',choices=['audit','support'],required=True)
    args=parser.parse_args();run=Path(args.run)
    lease=run/'work/leases/policy_metadata_engineering'
    base.assert_safe_output_path(lease,kind='backtest',paths=base.resolve(base.old.REPO))
    (lease/'work').mkdir(parents=True,exist_ok=True)
    with base.old.task_writer(lease):result=invoke(run,args.phase)
    print(json.dumps(base.old._json(result),allow_nan=False),flush=True)

if __name__=='__main__':main()
