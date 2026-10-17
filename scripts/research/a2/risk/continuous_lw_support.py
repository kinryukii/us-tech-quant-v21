"""Continuous whole-LW support using the existing R5 estimator and ledger owners.

The account worker alone calls this backend. Source qualification precedes every
reservation; actual failed operations remain charged in the original ledger.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
from scripts.research.a2.risk.shared_risk_budget_r2 import _normalized
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.evaluation import joint_event_risk_execution_r5 as event_owner
from scripts.research.a2.evaluation import joint_short_risk_execution_r4 as prior
from scripts.research.a2.risk import joint_event_risk_estimators_r5 as owner
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, KINDS, content_hash
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance

RECIPE = '513bd58da78a2183731927c72d74023d345b2adf0a968d719f922d0a60a83eb7'
TASK = 'V24_B_FAST_TRACK_PAIR_COMPLETION_R1'
KIND_LIMITS = {k: 0 for k in KINDS}
KIND_LIMITS.update(scaler=2, covariance=7, deterministic_transform=5)
CONTINUOUS_LW_RULE = dict(schema='B_CONTINUOUS_CAUSAL_WHOLE_LW_RESEARCH_RULE_V1',
    estimation_domain='FULL_ORIGINAL_P_UNION_OWN_ACTUAL_H',required_domain='E_UNION_OWN_ACTUAL_H',
    trigger='ONLY_WHEN_NO_CURRENT_VALID_WHOLE_STATE_COVERS_D',primary_priority=True,
    qualified_generated_state_reuse=True,max_new_outputs_per_decision_date=1,
    max_learned_units_per_output=9,max_physical_operations_per_output=14,
    window_learned_cap=6768,window_physical_cap=10528,caps_are_not_targets=True,
    expiry='FIRST_NEXT_ORIGINAL_PRIMARY_EVENT_OR_SOURCE_IDENTITY_INVALIDATION',
    future_state_allowed=False,matrix_mixing=False,unchanged_failed_estimate_retry_allowed=False,
    past_mature_samples_only=True,risk_horizon='ORIGINAL_H5',recipe_sha256=RECIPE)

SOURCE_FAMILY_REF = dict(path='D:/us-tech-quant-backtests/V24/20261003T061818+0000_49b1a578/FAMILY_DESIGN_FREEZE.json',
    sha256='c64e600628f90f75dfe0950fca64718babfc3dcf7fb6b14e4700850afcc1344c')
SOURCE_SNAPSHOT = '2026-10-03T07:00:00.758297+00:00'
FLAGS = dict(strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)
IDENTITY_COLUMNS = ('ticker','effective_start','effective_end','security_id','security_id_type',
    'cusip','issuer_name','title_of_class','moomoo_transport_code','mapping_status',
    'mapping_source','source_filing','report_quarter')


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def reference(path):
    path=Path(path)
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(path),sha256=digest)


GLOBAL_DAY = "GLOBAL_DAY"
ACCOUNT_ID_DAY = "ACCOUNT_ID_DAY"


def continuous_lw_resource_config(value=None):
    """An omitted resource field preserves the historical global daily cap."""
    if value is None:
        return dict(schema="B_CONTINUOUS_LW_DAILY_RESOURCE_CONFIG_V1",daily_output_scope=GLOBAL_DAY)
    need(isinstance(value,dict) and set(value)=={"schema","daily_output_scope"}
        and value["schema"]=="B_CONTINUOUS_LW_DAILY_RESOURCE_CONFIG_V1"
        and value["daily_output_scope"] in (GLOBAL_DAY,ACCOUNT_ID_DAY),
        "EXPLICIT_CONTINUOUS_LW_DAILY_RESOURCE_CONFIG_REQUIRED")
    return deepcopy(value)


def logical_joint_account_id(request):
    """Reuse the existing task::policy_account_label, never an attempt namespace."""
    value=request.get("account_id")
    # Original 10bps Joint books plus the existing 5/20bps base-Joint profiles.
    label=r"::(?:JOINT_REUSE_S(?:5|10|20)|JOINT_REUSE_(?:NO_ALPHA|G1|A2|G1_A2)_S10|PTO_REUSE_ROBUST_COST_S10)"
    need(isinstance(value,str) and re.fullmatch(re.escape(TASK)+label,value) is not None,
        "EXISTING_LOGICAL_JOINT_POLICY_ACCOUNT_ID_REQUIRED")
    return value


class ContinuousLWLedger(old.DurableFitLedger):
    """Scope initialization and bounds only; reserve/sync/checkpoint retain owner."""
    def __init__(self, run, *, inherited_ref, resource_config=None, legacy_owner_binding_ref=None):
        self.resource_config=continuous_lw_resource_config(resource_config)
        self.run,self.stage=Path(run),'risk'
        assert_safe_output_path(self.run,kind='backtest',paths=resolve(old.REPO))
        self.inherited=0
        self.new_cap=self.stage_cap=CONTINUOUS_LW_RULE['window_learned_cap']
        self.active_rr_correction=self.active_complete_group=None
        path=self.run/'work/FIT_STATUS.json'
        self.status=old.read_json(path) if path.exists() else dict(
            schema='B_CONTINUOUS_LW_DURABLE_SCOPE_V1',task_id=TASK,status='READY',
            fit_attempts=0,inherited_fit_units=0,new_fit_units=0,risk_fit_units=0,
            records=[],failures=[],physical_events=[],requests=[],account_paths=2,
            test2026_rows_read=0,inherited_state_history=dict(publication_ref=inherited_ref,
                learned_units=9,physical_operations=14,charged_to_this_scope=False))
        need(self.status.get('schema')=='B_CONTINUOUS_LW_DURABLE_SCOPE_V1'
            and self.status.get('task_id')==TASK and self.status.get('inherited_fit_units')==0
            and self.status.get('fit_attempts')==self.status.get('new_fit_units')
            and self.status.get('inherited_state_history')==dict(publication_ref=inherited_ref,
                learned_units=9,physical_operations=14,charged_to_this_scope=False),
            'EXACT_CONTINUOUS_SCOPE_AND_INHERITED_HISTORY_REQUIRED')
        need(sum(r['learned_states'] for r in self.status['physical_events'])==self.status['new_fit_units']
            and len({r['key'] for r in self.status['physical_events']})==len(self.status['physical_events'])
            and self.status['new_fit_units']<=self.new_cap
            and len(self.status['physical_events'])<=CONTINUOUS_LW_RULE['window_physical_cap'],
            'DURABLE_CONTINUOUS_COUNTERS_OR_CAP_CHANGED')
        self.active_request=None
        self.legacy_owner_bindings={}
        if self.resource_config['daily_output_scope']==ACCOUNT_ID_DAY:
            need(isinstance(legacy_owner_binding_ref,dict) and set(legacy_owner_binding_ref)=={'path','sha256'},
                 'EXACT_LEGACY_RESOURCE_OWNER_BINDING_REQUIRED')
            expected=self.run/'work/CONTINUOUS_LW_LEGACY_OWNER_BINDING_ACCOUNT_DAY_R1.json'
            need(Path(legacy_owner_binding_ref['path'])==expected,'EXACT_LEGACY_RESOURCE_OWNER_BINDING_PATH_REQUIRED')
            need(reference(expected)==legacy_owner_binding_ref,'LEGACY_RESOURCE_OWNER_BINDING_PHYSICAL_SHA_MISMATCH')
            binding=old.read_json(expected)
            need(binding.get('schema')=='B_CONTINUOUS_LW_LEGACY_RESOURCE_OWNER_BINDING_V1'
                 and binding.get('task_id')==TASK and binding.get('old_requests_and_records_not_rewritten') is True,
                 'EXACT_LEGACY_RESOURCE_OWNER_BINDING_SCHEMA_REQUIRED')
            rows=binding.get('bindings',[])
            need(len({r['request_sha256'] for r in rows})==len(rows),'UNIQUE_LEGACY_RESOURCE_OWNER_BINDINGS_REQUIRED')
            self.legacy_owner_bindings={r['request_sha256']:r for r in rows}

    def record_account_id(self, record):
        """Resolve legacy ownership through its actual request; never backfill rows."""
        matches=[r for r in self.status['requests'] if r.get('request_sha256')==record.get('request_sha256')]
        need(len(matches)==1,'UNIQUE_HISTORICAL_LW_REQUEST_OWNER_REQUIRED')
        stored=matches[0];request=stored.get('request',{})
        normalized=stored.get('request_content_normalized')
        if normalized is not None:
            need(content_hash(normalized)==stored.get('request_sha256')
                 and normalized.get('account_id')==request.get('account_id')
                 and normalized.get('decision_session')==request.get('decision_session'),
                 'HISTORICAL_LW_REQUEST_HASH_CONFLICT')
        elif content_hash(request)!=stored.get('request_sha256'):
            # Old _json erased Timestamp/numpy type tags used by content_hash.
            # Match the pre-existing physical commitment; do not guess types.
            binding=getattr(self,'legacy_owner_bindings',{}).get(stored.get('request_sha256'))
            need(isinstance(binding,dict)
                 and binding.get('persisted_request_row_content_sha256')==content_hash(stored)
                 and binding.get('persisted_record_content_sha256')==content_hash(record)
                 and binding.get('account_id')==request.get('account_id')
                 and binding.get('decision_session')==request.get('decision_session'),
                 'HISTORICAL_LW_REQUEST_HASH_CONFLICT')
        need(stored.get('decision_session')==record.get('decision_session')==request.get('decision_session'),
             'HISTORICAL_LW_ACCOUNT_DAY_PROVENANCE_CONFLICT')
        account_id=logical_joint_account_id(request)
        need(record.get('account_id',account_id)==account_id,'HISTORICAL_LW_ACCOUNT_OWNER_CONFLICT')
        return account_id

    def begin(self, request):
        key=content_hash(request)
        need(not any(r['request_sha256']==key for r in self.status['requests']),
             'UNCHANGED_REQUEST_ALREADY_ATTEMPTED_NO_AUTOMATIC_RETRY')
        day=request['decision_session']
        complete=[r for r in self.status['records'] if r.get('decision_session')==day and r.get('status')=='COMPLETE_WHOLE_LW_OUTPUT']
        if self.resource_config['daily_output_scope']==GLOBAL_DAY:
            need(not complete,'ONE_WHOLE_LW_OUTPUT_PER_SESSION')
        else:
            account_id=logical_joint_account_id(request)
            need(not any(self.record_account_id(r)==account_id for r in complete),
                 'ONE_WHOLE_LW_OUTPUT_PER_ACCOUNT_SESSION')
        row=dict(request_sha256=key,decision_session=day,request=old._json(request),
                 status='SOURCE_QUALIFICATION_RUNNING',started_utc=datetime.now(timezone.utc).isoformat())
        if self.resource_config['daily_output_scope']==ACCOUNT_ID_DAY:
            row['request_content_normalized']=_normalized(request)
        self.status['requests'].append(row)
        self.active_request=row
        self._start_new=self.status['new_fit_units']
        self._start_physical=len(self.status['physical_events'])
        self.checkpoint()
        return key

    def reserve(self,event):
        need(self.active_request is not None and self.active_request['status']=='SOURCE_QUALIFIED_BEFORE_RESERVATION','ACTIVE_QUALIFIED_CONTINUOUS_REQUEST_REQUIRED')
        need(len(self.status['physical_events'])<CONTINUOUS_LW_RULE['window_physical_cap'],
             'CONTINUOUS_PHYSICAL_WINDOW_CAP')
        recent=self.status['physical_events'][self._start_physical:]
        need(len(recent)<14 and sum(r['kind']==event['kind'] for r in recent)<KIND_LIMITS[event['kind']],
             'CONTINUOUS_SINGLE_INVOCATION_PHYSICAL_OR_KIND_CAP')
        need(self.status['new_fit_units']-self._start_new+int(event['kind'] in old.LEARNED_KINDS)<=9,
             'CONTINUOUS_SINGLE_INVOCATION_LEARNED_CAP')
        return super().reserve(event)

    def finish(self, record):
        need(self.active_request is not None,'ACTIVE_REQUEST_REQUIRED')
        record=old._json(record)
        self.active_request.update(status=record['status'],finished_utc=datetime.now(timezone.utc).isoformat())
        record.update(request_sha256=self.active_request['request_sha256'],
                      decision_session=self.active_request['decision_session'])
        if self.resource_config['daily_output_scope']==ACCOUNT_ID_DAY:
            record.update(account_id=logical_joint_account_id(self.active_request['request']),
                          daily_output_scope=ACCOUNT_ID_DAY)
        self.status['records'].append(record)
        self.status['status']=record['status']
        self.checkpoint()
        self.active_request=None


def _current_identity(intervals, raw, asset, uid, day):
    rows=intervals.loc[intervals.ticker.eq(asset)
        &pd.to_datetime(intervals.effective_start).le(day)&pd.to_datetime(intervals.effective_end).ge(day)]
    keys=raw.loc[raw.ticker.eq(asset)]
    need(len(rows)==1 and len(keys)==1,'UNIQUE_CURRENT_UID_AND_RAW_KEY_REQUIRED:'+asset)
    row=rows.iloc[0]
    need(row.security_id==uid and row.mapping_status=='RESOLVED'
        and row.moomoo_transport_code==keys.iloc[0].code,'CURRENT_UID_RAW_COORDINATE_CONFLICT:'+asset)
    for field in ('security_id_type','cusip','title_of_class','moomoo_transport_code','mapping_source','source_filing'):
        need(isinstance(row[field],str) and row[field].strip()
            and not row[field].strip().upper().startswith(('UNKNOWN','NONE','NAN')),
            'KNOWN_CURRENT_IDENTITY_SOURCE_REQUIRED:'+asset+':'+field)
    return dict(security_id=row.security_id,security_id_type=row.security_id_type,cusip=row.cusip,
        share_class=row.title_of_class,raw_code=row.moomoo_transport_code,
        raw_actual_share_coordinate='RAW_ACTUAL_SHARE')


def _held_current_identity(request,raw,asset,account_id,raw_source_ref):
    """Accepted own-held continuity, not an extension of 13F membership."""
    from scripts.research.a2.inference.reused_r5_risk_inputs import _held_identity,_held_ref,_held_raw_key_row_identity,_held_metadata_proof_matches_current
    proof=request['held_lineage_proofs'].get(asset)
    identity=request['current_identities'].get(asset)
    need(proof is not None and identity is not None,'ACTUAL_HELD_SOURCE_PROOF_REQUIRED:'+asset)
    identity=_held_identity(identity)
    quantity=proof.get('actual_quantity_binding',{})
    rows=raw.loc[raw.ticker.eq(asset)&pd.to_datetime(raw.trade_date).eq(pd.Timestamp(request['decision_session']))]
    need(len(rows)==1 and rows.iloc[0].code==identity['raw_code'],
         'EXACT_HELD_CURRENT_RAW_SECURITY_KEY_REQUIRED:'+asset)
    q=quantity.get('raw_quantity')
    need(proof.get('lineage_status')=='QUALIFIED_RESEARCH_HELD_LINEAGE'
        and proof.get('decision_session')==request['decision_session']
        and quantity.get('account_id')==account_id and quantity.get('session')==request['decision_session']
        and quantity.get('stage')=='DECISION_CLOSE_RAW_ACTUAL_SHARE'
        and isinstance(q,(float,int,np.floating)) and np.isfinite(q) and q>0,
        'QUALIFIED_OWN_CURRENT_ACTUAL_HELD_QUANTITY_REQUIRED:'+asset)
    exact=proof.get('raw_exact_key_ref',{})
    need(_held_ref(exact.get('source_ref'))==_held_ref(raw_source_ref)
        and exact.get('row_identity')==_held_raw_key_row_identity(rows)
        and ((proof.get('seed_security_id')==identity['security_id']
              and proof.get('seed_security_id_type')==identity['security_id_type'])
            or _held_metadata_proof_matches_current(proof,identity,
                request.get('held_source_receipt',{}).get('quantity_guard_proofs',{}).get(asset,{})))
        and proof.get('raw_actual_share_coordinate')=='RAW_ACTUAL_SHARE',
        'ACCEPTED_HELD_RAW_AND_SEED_IDENTITY_BINDING_REQUIRED:'+asset)
    return identity


class ContinuousLWEstimator:
    """Callable original-owner backend; constructing it performs no fit or load."""
    def __init__(self, freeze, *, base_shared, account_id):
        need(freeze.get('task_id')==TASK,'AUTHORIZED_FAST_TRACK_TASK_REQUIRED')
        need(freeze.get('continuous_lw_rule')==CONTINUOUS_LW_RULE,'EXACT_CONTINUOUS_LW_RULE_REQUIRED')
        science=deepcopy(freeze['continuous_lw_source_science'])
        need(set(science)=={'scientific_contract_identity','scientific_contract_sha256','actual_snapshot_timestamp'}
            and isinstance(science['scientific_contract_identity'],str) and science['scientific_contract_identity'].startswith(TASK)
            and len(science['scientific_contract_sha256'])==64
            and science['actual_snapshot_timestamp']==SOURCE_SNAPSHOT,'EXACT_NEW_SCIENCE_AND_ORIGINAL_SOURCE_SNAPSHOT_REQUIRED')
        self.freeze,self.base,self.account_id,self.science=freeze,base_shared,account_id,science
        self.resource_config=continuous_lw_resource_config(freeze.get('continuous_lw_resource_config'))
        if self.resource_config['daily_output_scope']==ACCOUNT_ID_DAY:
            logical_joint_account_id(dict(account_id=account_id))
        self.legacy_owner_binding_ref=freeze.get('legacy_lw_owner_binding_ref')
        config_ref=freeze['research_config_ref']
        from scripts.research.a2.inference.reused_r5_risk_inputs import _causal_pin
        config=base_shared.interface.read(_causal_pin(base_shared.interface,config_ref))
        need(config.get('continuous_lw_rule')==CONTINUOUS_LW_RULE
            and config.get('task_id')==TASK and config_ref['sha256']==science['scientific_contract_sha256'],
            'EXACT_PINNED_CONTINUOUS_SCIENTIFIC_CONFIG_REQUIRED')
        need(continuous_lw_resource_config(config.get('continuous_lw_resource_config'))==self.resource_config,
             'EXACT_PINNED_CONTINUOUS_DAILY_RESOURCE_CONFIG_REQUIRED')
        need(config.get('legacy_lw_owner_binding_ref')==self.legacy_owner_binding_ref,
             'EXACT_PINNED_LEGACY_RESOURCE_OWNER_BINDING_REQUIRED')
        if self.resource_config['daily_output_scope']==ACCOUNT_ID_DAY:
            need(isinstance(self.legacy_owner_binding_ref,dict),
                 'EXACT_LEGACY_RESOURCE_OWNER_BINDING_REQUIRED')
        from scripts.research.a2.inference.reused_r5_risk_inputs import _normalize_additional_descriptor_bridge_refs
        need(freeze.get('additional_share_class_descriptor_bridge_refs')==config.get('additional_share_class_descriptor_bridge_refs'),
            'EXACT_FROZEN_ADDITIONAL_DESCRIPTOR_SOURCE_REFS_REQUIRED')
        self.additional_descriptor_bridge_refs=_normalize_additional_descriptor_bridge_refs(
            freeze.get('additional_share_class_descriptor_bridge_refs'))
        self.run=Path(freeze['run'])
        assert_safe_output_path(self.run,kind='backtest',paths=resolve(old.REPO))
        self.ledger=None
        self.last_request=None
        self.estimator=None
        self._source=None
        self._producer_ref=None
        self.descriptor_bridges=None

    def available_state_records(self,as_of,primary_epoch,*,known_state_refs=()):
        """Past generated metadata only; numeric artifacts stay lazy."""
        path=self.run/'work/FIT_STATUS.json'
        if self.ledger is None and path.exists():
            self.ledger=ContinuousLWLedger(self.run,inherited_ref=self.freeze['supplemental_lw_state_ref'],resource_config=self.resource_config,legacy_owner_binding_ref=self.legacy_owner_binding_ref)
        if self.ledger is None:return []
        current=pd.Timestamp(as_of)
        return [deepcopy(r) for r in self.ledger.status['records']
            if r['status']=='COMPLETE_WHOLE_LW_OUTPUT'
            and r['original_primary_dependency_epoch']==primary_epoch
            and pd.Timestamp(r['as_of'])<=current and pd.Timestamp(r['state_available_at'])<=current
            and (not known_state_refs or r['state_ref'] not in known_state_refs)]

    def _producer_custody(self):
        if self._producer_ref is None:
            data=Path(__file__).read_bytes();digest=hashlib.sha256(data).hexdigest()
            target=resolve(old.REPO).cache_root/'V24'/TASK/'source_audit'/'executed_lw_backend'/('backend_'+digest+'.py')
            assert_safe_output_path(target,kind='cache',paths=resolve(old.REPO))
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():need(target.read_bytes()==data,'IMMUTABLE_EXECUTED_BACKEND_CUSTODY_CHANGED')
            else:
                with target.open('xb') as stream:stream.write(data)
            self._producer_ref=dict(path=str(target),sha256=digest)
        return self._producer_ref

    def budget_summary(self):
        path=self.run/'work/FIT_STATUS.json'
        status=self.ledger.status if self.ledger is not None else (old.read_json(path) if path.exists() else None)
        if status is None:
            return dict(new_complete_outputs=0,charged_new_learned_units=0,charged_new_physical_operations=0,
                physical_failed=0,physical_started=0,ledger_ref=None,
                inherited_paid_history=dict(learned_units=9,physical_operations=14),authoritative_ledger_available=True)
        return dict(new_complete_outputs=sum(r['status']=='COMPLETE_WHOLE_LW_OUTPUT' for r in status['records']),
            charged_new_learned_units=status['new_fit_units'],charged_new_physical_operations=len(status['physical_events']),
            physical_failed=sum(r['status']=='FIT_FAILURE' for r in status['physical_events']),
            physical_started=sum(r['status']=='STARTED' for r in status['physical_events']),
            ledger_ref=reference(path),inherited_paid_history=status['inherited_state_history'],
            authoritative_ledger_available=True)

    def _prepare(self, request):
        """Original assembler and source support, with distinct current held roles."""
        self.base._initialize();c=self.base._components
        reader=c['reader']
        if self._source is None:
            self._source=self.base.interface.read(self.base.interface.pin(c['refs']['source']))
        source=self._source
        day=pd.Timestamp(request['decision_session']);asof=pd.Timestamp(request['as_of'])
        days=c['calendar'];j=days.get_loc(day)
        need(j>0 and day<pd.Timestamp('2026-01-01') and asof==event_owner._clock(day),
             'PRE2026_EXACT_SIGNAL_CLOSE_REQUIRED')
        previous=days[j-1];cutoff=event_owner._clock(previous)
        need(cutoff.isoformat()==request['cutoff'],'EXCLUSIVE_PRIOR_CLOSE_REQUIRED')
        start=days[max(0,j-1-306)];assets=tuple(request['U'])
        original=self.base._domain(day,asof);event=original['event'];record=original['record']
        need(request['P']==list(record['assets']) and set(assets)==set(request['P'])|set(request['H'])
            and len(assets)==len(set(assets)) and set(request['D']).issubset(assets),
            'FULL_ORIGINAL_POOL_UNION_ACTUAL_HELD_ESTIMATION_AXIS_REQUIRED')
        primary=dict(event_id=event['dependency_local_event_ids']['PRIMARY'],
            signature_sha256=event['dependency_local_signature_sha256']['PRIMARY'])
        need(request['original_primary_dependency_epoch']==primary,'EXACT_CURRENT_PRIMARY_DEPENDENCY_REQUIRED')
        features=reader.read('prediction_features',old.FEATURE_META,date_field='signal_date',start=start,
            stop=day+pd.Timedelta(days=1),tickers=assets)
        raw=reader.read('raw_open_close',('ticker','trade_date','code'),date_field='trade_date',day=day,tickers=assets)
        intervals=reader.read('uid_intervals',IDENTITY_COLUMNS,date_field='effective_start',
            stop=day+pd.Timedelta(days=1),tickers=assets)
        need(not raw.duplicated(['ticker','trade_date']).any() and len(raw)==len(assets),
             'EXACT_FULL_U_CURRENT_RAW_KEYS_REQUIRED')
        uids={a:record['asset_uids'][a] for a in request['P']}
        epochs={a:record['asset_epochs'][a] for a in request['P']}
        starts={a:event['segment_starts'][a] for a in request['P']}
        current_epochs=dict(epochs);identities={};held={}
        from scripts.research.a2.inference.reused_r5_risk_inputs import (
            _held_security_identity_equal, _load_share_class_descriptor_bridge, _extend_share_class_descriptor_bridge,
            _normalize_additional_descriptor_bridge_refs, _load_additional_share_class_descriptor_bridges)
        if self.descriptor_bridges is None:
            self.descriptor_bridges=(_load_share_class_descriptor_bridge(self.base.interface,
                self.freeze['share_class_descriptor_bridge_ref'],reader.sources['uid_intervals'])
                if self.freeze.get('share_class_descriptor_bridge_ref') is not None else ())
            if self.freeze.get('share_class_descriptor_bridge_extension_ref') is not None:
                self.descriptor_bridges=_extend_share_class_descriptor_bridge(self.base.interface,self.descriptor_bridges,
                    self.freeze['share_class_descriptor_bridge_extension_ref'],reader.sources['uid_intervals'])
            additional=_normalize_additional_descriptor_bridge_refs(
                self.freeze.get('additional_share_class_descriptor_bridge_refs'))
            need(additional==getattr(self,'additional_descriptor_bridge_refs',additional),
                'FROZEN_ADDITIONAL_DESCRIPTOR_SOURCE_REFS_CHANGED')
            if additional:
                self.descriptor_bridges=_load_additional_share_class_descriptor_bridges(self.base.interface,
                    additional,reader.sources['uid_intervals'],self.descriptor_bridges)
        for asset in assets:
            if asset not in uids:
                proof=request['held_lineage_proofs'].get(asset)
                identity=request['current_identities'].get(asset)
                need(proof is not None and identity is not None,'ACTUAL_HELD_SOURCE_PROOF_REQUIRED:'+asset)
                uids[asset]=identity['security_id']
                epochs[asset]=request['historical_source_epochs'][asset]
                past=[e for e in c['support']['events'] if pd.Timestamp(e['decision_asof'])<=cutoff
                    and e['asset_uids'].get(asset)==uids[asset] and e['asset_epochs'].get(asset)==epochs[asset]]
                need(past,'EXACT_ORIGINAL_HELD_HISTORICAL_EPOCH_WITNESS_REQUIRED:'+asset)
                witness=max(past,key=lambda e:pd.Timestamp(e['decision_asof']))
                starts[asset]=witness['segment_starts'][asset]
                held[asset]=dict(identity=deepcopy(identity),historical_source_epoch=epochs[asset],
                    historical_epoch_event_id=witness['event_id'],actual_held_proof_sha256=content_hash(proof),
                    fit_asof_actual_position_id=proof['position_id'])
                current_epochs[asset]='HELD_POSITION_LINEAGE:'+content_hash(held[asset])
            if asset in request['P']:
                identities[asset]=_current_identity(intervals,raw,asset,uids[asset],day)
            else:
                identities[asset]=_held_current_identity(request,raw,asset,self.account_id,reader.sources['raw_open_close'])
            if asset in request['current_identities']:
                need(_held_security_identity_equal(identities[asset],request['current_identities'][asset],self.descriptor_bridges),
                     'CURRENT_ACTUAL_HELD_IDENTITY_CONFLICT:'+asset)
        history=features.loc[pd.to_datetime(features.signal_date).le(previous),
            ['ticker','signal_date','security_id']].copy()
        need(not history.duplicated(['ticker','signal_date']).any(),'UNIQUE_HISTORICAL_UID_ROWS_REQUIRED')
        history['signal_date']=pd.to_datetime(history.signal_date)
        history['available_at']=history.signal_date.map(old._clock)
        history['identity_epoch']=[epochs[a] if t>=pd.Timestamp(starts[a]) and uid==uids[a]
            else 'PRIOR_OBSERVED_UID_EPOCH' for a,t,uid in history[['ticker','signal_date','security_id']].itertuples(index=False,name=None)]
        pool=dict(assets=assets,asset_uids=uids,asset_epochs=epochs,segment_starts=starts,history=history)
        labels=reader.read('extended_shareholder_y5',old.LABEL_META,date_field='signal_date',start=start,
            stop=previous,tickers=assets,mature_before=previous)
        base=reader.read('shareholder_y5',('ticker','signal_date','security_id'),date_field='signal_date',
            start=start,stop=previous,tickers=assets)
        qqq=reader.read('qqq_qfq_years',('ticker','trade_date'),date_field='trade_date',
            start=days[max(0,j-1-360)],stop=previous,tickers=('QQQ',))
        source_identity=dict(dependency='PRIMARY',original_primary_dependency_epoch=primary,
            source_manifest_ref=c['refs']['source'],historical_observation_filter_epochs=epochs,
            current_authority_epochs=current_epochs,held_lineage_authorities=held,
            share_class_descriptor_bridge_refs=[r for b in self.descriptor_bridges
                for r in ([b['source_ref']]+([b['extension_ref']] if 'extension_ref' in b else []))],
            source_pins={k:reader.sources[k]['sha256'] for k in
                ('extended_shareholder_y5','prediction_features','uid_intervals')},
            preparation_producer_ref=self._producer_custody(),
            historical_invalid_rows_reclassified=False,new_descendant_not_original_pool_equivalence=True)
        epoch='CONTINUOUS_LW_CURRENT_AND_HISTORICAL_ROLES:'+content_hash(source_identity)
        primary_receipt=old._receipt(source,self.science,cutoff,epoch)
        benchmark=old._receipt(source,self.science,cutoff,'EXISTING_QQQ_QFQ_OPEN_PROXY',benchmark=True)
        proof=dict(assets=list(assets),asset_uids=uids,asset_epochs=current_epochs,
            security_coordinate=primary_receipt.return_coordinate,source_support_identity=source_identity,
            source_qualified=True,maturity_qualified=True,current_identity_asof=asof.isoformat(),
            history_cutoff=cutoff.isoformat(),historical_source_epochs=epochs,**FLAGS)
        def assemble(values,qqq_values,numeric):
            bound=values.merge(base,on=['ticker','signal_date'],how='left',validate='one_to_one').merge(
                history[['ticker','signal_date','identity_epoch']],on=['ticker','signal_date'],how='left',validate='many_to_one')
            if not numeric:
                bound['y_open5']=np.nan;bound=event_owner._MetadataFrame(bound)
            assembly=event_owner.assemble_risk_inputs(bound,days,assets=assets,asset_uids=uids,
                asset_epochs=epochs,identity_epoch=epoch,source_receipt=primary_receipt,cutoff=cutoff,
                identity_history=history,qqq_opens=qqq_values if numeric else None,
                qqq_receipt=benchmark if numeric else None)
            inputs=assembly.risk_input
            if not numeric:inputs=prior.qqq_metadata_only(inputs,qqq_values,source,self.science,days,cutoff)
            keys=prior.source_support_keys(inputs,values.loc[:,list(old.LABEL_META)],base,pool)
            q=self.estimator.qualify(inputs,as_of=asof,support_metadata=keys,current_identity_proof=proof)
            return inputs,keys,q
        _,_,metadata_q=assemble(labels,qqq,False)
        phase=reader.phase
        try:
            reader.phase='fit'
            values=reader.read('extended_shareholder_y5',(*old.LABEL_META,'y_open5'),date_field='signal_date',
                start=start,stop=previous,tickers=assets,mature_before=previous)
            qqq_values=reader.read('qqq_qfq_years',('ticker','trade_date','open'),date_field='trade_date',
                start=days[max(0,j-1-360)],stop=previous,tickers=('QQQ',))
        finally:reader.phase=phase
        inputs,keys,q=assemble(values,qqq_values,True)
        need(q==metadata_q,'SOURCE_METADATA_AND_NUMERIC_QUALIFICATION_CHANGED')
        joint=inputs.observations.merge(keys,on=['asset','origin_at'],how='left',validate='one_to_one')
        need(np.isfinite(joint.loc[joint.qualified.fillna(False),'return_value'].to_numpy(float)).all(),
             'QUALIFIED_ORIGINAL_H5_NUMERIC_UNAVAILABLE')
        legal=inputs.qqq_observations
        legal=legal.loc[legal.horizon.eq(5)&legal.origin_at.map(lambda t:t.isoformat()).isin(q['origins'])]
        need(len(legal)==252 and np.isfinite(legal.return_value.to_numpy(float)).all(),
             'QUALIFIED_ORIGINAL_QQQ_252_H5_UNAVAILABLE')
        return dict(inputs=inputs,keys=keys,qualification=q,proof=proof,identities=identities,
            historical_source_epochs=epochs,current_authority_epochs=current_epochs,held_lineages=held,
            original_primary_dependency_epoch=primary)

    def __call__(self,request):
        request=deepcopy(request)
        request['estimation_producer_source_pins']=deepcopy(self.freeze['source_pins'])
        request['scientific_contract_sha256']=self.science['scientific_contract_sha256']
        self.last_request=request
        if self.ledger is None:
            self.ledger=ContinuousLWLedger(self.run,inherited_ref=self.freeze['supplemental_lw_state_ref'],resource_config=self.resource_config,legacy_owner_binding_ref=self.legacy_owner_binding_ref)
        key=self.ledger.begin(request)
        print(json.dumps(dict(stage='LW_SOURCE_QUALIFICATION_START',date=request['decision_session'],P=len(request['P']),H=len(request['H']),U=len(request['U']))),flush=True)
        budget=None;cache=None;prepared=None;state=None;metadata=None;error=None;artifact=None;cache_ref=None
        try:
            from scripts.research.a2.inference.reused_r5_risk_inputs import _causal_pin
            for pin in self.freeze['source_pins']:_causal_pin(self.base.interface,pin)
            _causal_pin(self.base.interface,SOURCE_FAMILY_REF)
            self.estimator=owner.EventRiskEstimator(owner.specification(industry_mode='MARKET_ONLY'))
            need(self.estimator.recipe_sha256==RECIPE,'ORIGINAL_LW_RECIPE_CHANGED')
            prepared=self._prepare(request)
            print(json.dumps(dict(stage='LW_SOURCE_QUALIFICATION_COMPLETE',date=request['decision_session'],U=len(request['U']),qualification_sha256=prepared['qualification']['metadata_proof_sha256'])),flush=True)
            self.ledger.active_request['status']='SOURCE_QUALIFIED_BEFORE_RESERVATION'
            self.ledger.active_request['qualification_sha256']=prepared['qualification']['metadata_proof_sha256']
            self.ledger.checkpoint()
            budget=StateBudget(limit=9,limits=KIND_LIMITS,reserve_callback=self.ledger.reserve)
            cache=self.estimator.make_cache(prepared['inputs'],as_of=request['as_of'],budget=budget)
            print(json.dumps(dict(stage='LW_ORIGINAL_OWNER_FIT_START',date=request['decision_session'])),flush=True)
            with threadpool_limits(limits=2):
                state=self.estimator.fit_family('LW',prepared['inputs'],as_of=request['as_of'],
                    support_metadata=prepared['keys'],current_identity_proof=prepared['proof'],cache=cache,
                    expected_qualification=prepared['qualification'],expected_recipe_sha256=RECIPE)
            # Persist typed terminal states too: a blocked result is part of history.
            artifact=prior._persist_state(self.run,state)
            need(state.status=='PASS_FROZEN_HISTORY_MECHANISM' and state.covariance is not None,
                 'ORIGINAL_LW_OWNER_RETURNED_BLOCKED_STATE:'+str(state.notes.get('block_reason')))
            full=np.asarray(state.covariance,dtype=float)
            need(full.shape==(len(request['U']),len(request['U'])),'WHOLE_U_CROSS_COVARIANCE_REQUIRED')
            _,psd=validate_covariance(full,regularize=False)
            metadata=dict(schema='B_CONTINUOUS_ORIGINAL_OWNER_LW_STATE_V1',status='COMPLETE_WHOLE_LW_OUTPUT',
                assets=list(state.assets),asset_uids=dict(prepared['inputs'].asset_uids),
                historical_source_epochs=prepared['historical_source_epochs'],
                asset_epochs=prepared['current_authority_epochs'],current_identities=prepared['identities'],
                held_lineages=prepared['held_lineages'],original_primary_dependency_epoch=prepared['original_primary_dependency_epoch'],
                as_of=pd.Timestamp(state.as_of).isoformat(),cutoff=pd.Timestamp(state.cutoff).isoformat(),
                state_available_at=request['as_of'],availability_role='MECHANISM_ASSUMPTION_NOT_HISTORICAL_PUBLICATION',
                historical_availability_authority='UNKNOWN',risk_state_id=state.risk_state_id,method=state.method,
                recipe_sha256=RECIPE,typed_state_content_sha256=content_hash(state),state_ref=artifact,
                covariance_sha256=content_hash(full),full_covariance_validation=psd,
                qualification_sha256=prepared['qualification']['metadata_proof_sha256'],
                current_identity_proof_sha256=content_hash(prepared['proof']),
                learned_units=budget.learned_total,physical_operations=len(budget.events),kind_counts=budget.counts,
                producer_ref=self._producer_custody(),scientific_contract_ref=self.freeze['research_config_ref'],
                fit_dependency_ids=list(state.fit_dependency_ids),request_sha256=key,**FLAGS)
        except BaseException as exc:
            error=exc
        finally:
            # Checkpoint failure and charges exactly once, even if persistence fails.
            if budget is not None:
                try:self.ledger.sync(budget.events)
                except BaseException as exc:
                    if error is None:error=exc
            if cache is not None:
                try:cache_ref=event_owner._save_cache(self.run,cache,'CONTINUOUS_'+key)
                except BaseException as exc:
                    if error is None:error=exc
            if error is None:
                metadata['cache_ref']=cache_ref
                record=metadata
            else:
                record=dict(status='TERMINAL_FAILED_CONTINUOUS_LW_REQUEST',reason=str(error),error_type=type(error).__name__,
                    learned_units=0 if budget is None else budget.learned_total,
                    physical_operations=0 if budget is None else len(budget.events),
                    source_qualification_completed=prepared is not None,state_ref=artifact,cache_ref=cache_ref,
                    typed_state_content_sha256=None if state is None else content_hash(state),
                    failed_units_refunded=False,**FLAGS)
            self.ledger.finish(record)
        if error is not None:raise error
        print(json.dumps(dict(stage='LW_COMPLETE_WHOLE_STATE',date=request['decision_session'],state_id=state.risk_state_id,learned_units=budget.learned_total,physical_operations=len(budget.events))),flush=True)
        return dict(state=state,metadata=metadata)


def make_continuous_lw_estimator(freeze, *, base_shared, account_id):
    return ContinuousLWEstimator(freeze,base_shared=base_shared,account_id=account_id)
