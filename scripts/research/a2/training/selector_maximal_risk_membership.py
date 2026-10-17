"""C14 conditional classical/veto composition over original membership owners.

Explicit execution only. No fit, risk estimation, new matcher, account, worker,
registry or statistical inference is implemented. Old P01 inputs are immutable
and opened only after the independent source review and full752 role gates.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import selector_maximal_breadth as owner
from scripts.research.a2.training import selector_maximal_risk_journal as transport
from scripts.research.a2.training import selector_constrained_risk as rank_owner
from scripts.research.a2.data import selector_maximal_risk_binding as binding
from scripts.research.a2.data.selector_shared_risk_consumer import decision_close
from scripts.research.a2.evaluation import selector_constrained_evidence as evidence
from scripts.research.a2.risk import event_risk_contract_r5 as event

CLASSICAL = ('C14_D01','C14_D05','C14_D06','C14_D09','C14_D10','C14_D11')
VETO = ('C14_G1','C14_G4')
ROLES = (*CLASSICAL,'C14_D02',*VETO)
CALENDAR_DATES, OUTER_DATES = 752, 502
RANK_SHA = '46b123b8b2297582a76496355fd7bb8eb9534241d490af5453166454752a3cc7'
EVIDENCE_SHA = '9bf3a1c564a352f66ff5b10e9a41152f680d154a85f00c703e5cd63c9e05265e'


def reviewed_sources(run, source_review_ref, journal):
    """No old numeric artifact is opened by this source/opaque-pin gate."""
    review = journal.read_ref(source_review_ref, Path(run))
    owner.require(review.get('status')=='PASS' and review.get('research_id')==owner.ID,
                  'INDEPENDENT_MEMBERSHIP_SOURCE_REVIEW_REQUIRED')
    pins = review.get('source_pins',{})
    modules = (Path(__file__),Path(owner.__file__),Path(transport.__file__),
               Path(binding.__file__),Path(rank_owner.__file__),Path(evidence.__file__),Path(event.__file__),
               Path(decision_close.__code__.co_filename))
    for path in modules:
        path=path.resolve()
        owner.require(str(path) in pins,'REVIEWED_MEMBERSHIP_SOURCE_CLOSURE_INCOMPLETE')
        journal.pin(path,pins[str(path)])
    owner.require(pins[str(Path(owner.__file__).resolve())]==transport.OWNER_SHA
                  and pins[str(Path(rank_owner.__file__).resolve())]==RANK_SHA
                  and pins[str(Path(evidence.__file__).resolve())]==EVIDENCE_SHA
                  and pins[str(Path(event.__file__).resolve())]==transport.EVENT_SHA
                  and pins[str(Path(decision_close.__code__.co_filename).resolve())]=='71a57696ba1596ee03c17939d561b75cfcd9870969aadc32991fc4e0dbf79fd3',
                  'ORIGINAL_MEMBERSHIP_OWNERS_CHANGED')
    for path,digest in pins.items():
        p=Path(path).resolve()
        owner.require(p.is_relative_to(owner.REPO.resolve()) and p.suffix=='.py','SOURCE_ONLY_REVIEW_PINS_REQUIRED')
        journal.pin(p,digest)
    refs=review.get('immutable_inputs',{})
    names={'ML_ASSEMBLY.json','SOLVE_LEDGER.json','C14_P01_native'}
    owner.require(names<=set(refs),'INDEPENDENT_OLD_P01_INPUT_PINS_REQUIRED')
    for name in names:
        ref=refs[name]; p=Path(ref['path']).resolve()
        expected=Path(run)/('predictions/native_pairs_C14_P01_pre2026.parquet' if name=='C14_P01_native' else name)
        owner.require(p==expected.resolve(),'EXACT_ORIGINAL_P01_INPUT_PATH_REQUIRED')
        journal.pin(p,ref['sha256'])
    owner.require(refs['SOLVE_LEDGER.json']['sha256']==transport.BASELINE_HASHES['SOLVE_LEDGER.json'],
                  'ORIGINAL_P01_LEDGER_PIN_CHANGED')
    return review


def _p01_reader(run, q, geometry, review):
    """Reuse the exact P01 proposal kernel with a stat-guarded one-load cache."""
    refs=review['immutable_inputs']
    assembly_path=Path(refs['ML_ASSEMBLY.json']['path'])
    owner.require(binding.sha(assembly_path)==refs['ML_ASSEMBLY.json']['sha256'],'ORIGINAL_P01_ASSEMBLY_PIN_CHANGED')
    assembly=json.loads(assembly_path.read_text(encoding='utf-8'))
    owner.require(binding.sha(assembly_path)==refs['ML_ASSEMBLY.json']['sha256'],'ORIGINAL_P01_ASSEMBLY_CHANGED_DURING_READ')
    owner.require(assembly.get('status')=='ML_ASSEMBLY_COMPLETE' and assembly.get('research_id')==owner.ID
                  and assembly.get('design_freeze_sha256')==binding.DESIGN_SHA
                  and assembly.get('pair_key_sha256')==q['pair_key_sha256']
                  and assembly.get('full_U_keys_sha256')==q['full_U_keys_sha256']
                  and assembly.get('all_training_terminal') is True and assembly.get('forecast2026_rows')==0
                  and 'C14_P01' in assembly.get('complete_candidates',[]),'ORIGINAL_COMPLETE_P01_ASSEMBLY_REQUIRED')
    native_ref=assembly['native_pair_predictions']['C14_P01']; expected=refs['C14_P01_native']
    owner.require(native_ref.get('path')==expected['path'] and native_ref.get('sha256')==expected['sha256']
                  and native_ref.get('kind')=='U0_POINT_GT0','REVIEWED_P01_NATIVE_INPUT_REQUIRED')
    columns=[*owner.PAIR_KEYS,'point','source_cutoff','source_capacity','source_kind','paradigm']
    native=owner.project(native_ref,columns,start='2024-01-01',stop='2026-01-01')
    future=geometry.loc[geometry.signal_date.dt.year.isin((2024,2025))].reset_index(drop=True)
    keys=list(owner.PAIR_KEYS); index=pd.MultiIndex.from_frame(native[keys]); target=pd.MultiIndex.from_frame(future[keys])
    owner.require(index.is_unique and len(index)==len(target) and len(native)==OUTER_DATES*200
                  and native.signal_date.nunique()==OUTER_DATES,'EXACT502_P01_WHOLE_NATIVE_FORECAST_REQUIRED')
    positions=index.get_indexer(target)
    owner.require((positions>=0).all() and np.isfinite(native.point.to_numpy(float)).all()
                  and native.source_kind.eq('MODEL_OOF').all() and native.paradigm.eq('RIDGE').all()
                  and native.source_capacity.isin(owner.CAPACITIES).all()
                  and native.source_cutoff.eq(native.signal_date.dt.year.astype(str)+'-01-01').all(),
                  'EXACT_FROZEN_P01_FORECAST_LINEAGE_REQUIRED')
    ordered=native.iloc[positions].reset_index(drop=True)
    values=owner.values_from_table(ordered); scores,eligible=owner.decision_values(values,'U0_POINT_GT0')
    daily={d:(future.iloc[ix],scores[ix],eligible[ix]) for d,ix in future.groupby('signal_date',sort=True).indices.items()}
    ref=refs['SOLVE_LEDGER.json']; ledger_path=Path(ref['path']).resolve(); initial=ledger_path.stat()
    owner.require(binding.sha(ledger_path)==ref['sha256'],'ORIGINAL_P01_CACHE_PHYSICAL_PIN_CHANGED')
    after_hash=ledger_path.stat()
    owner.require((initial.st_size,initial.st_mtime_ns,initial.st_ctime_ns)==(after_hash.st_size,after_hash.st_mtime_ns,after_hash.st_ctime_ns),
                  'ORIGINAL_P01_CACHE_CHANGED_DURING_HASH')
    stamp=(initial.st_size,initial.st_mtime_ns,initial.st_ctime_ns); cache={}
    def unchanged(path):
        p=Path(path).resolve(); s=p.stat()
        owner.require(p==ledger_path and (s.st_size,s.st_mtime_ns,s.st_ctime_ns)==stamp,'ORIGINAL_P01_CACHE_CHANGED_DURING_EXECUTION')
        return ref['sha256']
    def load(stream):
        unchanged(stream.name)
        if 'ledger' not in cache:
            cache['ledger']=json.load(stream); unchanged(stream.name)
        return cache['ledger']
    proposal=event.bind_pinned_kernel(binding.read_p01_proposal,physical_path=binding.__file__,
        expected_sha256=review['source_pins'][str(Path(binding.__file__).resolve())],
        dependencies=dict(sha=unchanged,json=SimpleNamespace(load=load)))
    def read(day, raw):
        g,score,ok=daily[pd.Timestamp(day)]
        # These are exactly the original checkpoint input hashes, independently
        # constructed before consulting any cached proposal identity.
        identity=dict(design_sha256=binding.DESIGN_SHA,pair_key_sha256=owner.pairs.pair_key_sha256(g),candidate_id='C14_P01',
            full_U_keys_sha256=owner.content_hash(raw[[*owner.KEYS,'raw_rank','U_t_fingerprint']].astype(str).values.tolist()),
            score_sha256=hashlib.sha256(np.asarray(score,dtype='<f8').tobytes()).hexdigest(),
            eligibility_sha256=hashlib.sha256(np.asarray(ok,bool).tobytes()).hexdigest())
        return proposal(ref,decision_asof=decision_close(day),raw_metadata=raw,expected_identity=identity)
    return read


def panel_for(raw, chosen, role):
    prepared=raw.copy(); prepared['rank']=prepared.raw_rank
    return rank_owner.membership_panel(prepared,chosen,role)


def input_identity(requirement, meta, raw, geometry, journal):
    return dict(research_id=owner.ID,design_sha256=binding.DESIGN_SHA,role=requirement['role'],
        family=meta.family,method=meta.header['method'],recipe_sha256=meta.recipe_sha256,risk_metadata_sha256=meta._seal,
        state_ref=meta.header['artifact_ref'],risk_state_id=meta.header['risk_state_id'],
        cutoff=meta.header['cutoff'],as_of=meta.header['as_of'],decision_asof=str(meta.decision_asof),
        full_U_keys_sha256=owner.content_hash(raw[[*owner.KEYS,'U_t_fingerprint','raw_rank']].astype(str).values.tolist()),
        pair_key_sha256=owner.pairs.pair_key_sha256(geometry),requirement_sha256=owner.content_hash(requirement),
        role_qualification_sha256=journal.roles[requirement['role']]['qualification_ref']['sha256'])


def predicted_risk(meta,payload,raw40,chosen):
    covariance,_=binding._numeric_input(meta,payload,raw40)
    uids=binding._consumer_uids(meta)
    before=evidence.risk_coordinates(covariance,uids,raw40[:20])
    after=evidence.risk_coordinates(covariance,uids,chosen)
    return before,after


def execute_membership(run,design,q,raw,geometry,requirements,get_risk,journal,source_review_ref,*,role_gates=None,qualification_ref=None,artifact_root=None,raw_identity_ref=None):
    """Execute the fixed six classical, Raw identity, G1/G4 roles independently."""
    run=Path(run).resolve()
    owner.require(run==journal.run and design['research_id']==q['research_id']==owner.ID,'ORIGINAL_C14_IDENTITY_REQUIRED')
    review=reviewed_sources(run,source_review_ref,journal); journal.verify()
    if qualification_ref is not None:
        owner.require(Path(qualification_ref['path']).resolve().is_relative_to(run/'risk_execution'),'RUN_OWNED_INPUT_QUALIFICATION_RECEIPT_REQUIRED')
        journal.pin(qualification_ref['path'],qualification_ref['sha256'])
    base=run/'risk_execution' if artifact_root is None else Path(artifact_root).resolve()
    owner.require(base.resolve() in {(run/'risk_execution').resolve(),
        (run/'risk_execution/source_metadata_recovery_r1').resolve(),
        (run/'risk_execution/source_guard_recovery_r1').resolve()}, 'EXACT_CONDITIONAL_ARTIFACT_ROOT_REQUIRED')
    reuse=None
    if raw_identity_ref is not None:
        owner.require(base.resolve() in {(run/'risk_execution/source_metadata_recovery_r1').resolve(),
            (run/'risk_execution/source_guard_recovery_r1').resolve()}
            and 'source_metadata_recovery_ref' in review, 'REVIEWED_RAW_IDENTITY_RECOVERY_REQUIRED')
        custody=journal.read_ref(review['source_metadata_recovery_ref'],run)
        owner.require(custody.get('prior_refs',{}).get('membership')==raw_identity_ref, 'EXACT_PRIOR_RAW_IDENTITY_ASSEMBLY_REF_REQUIRED')
        reuse=journal.read_ref(raw_identity_ref,run)
        owner.require(reuse.get('research_id')==owner.ID and reuse.get('status')=='MEMBERSHIP_ASSEMBLY_COMPLETE'
            and reuse.get('complete_candidates')==['C14_D02'] and reuse.get('native_pair_predictions')=={}
            and reuse.get('roles',{}).get('C14_D02',{}).get('status')=='MEMBERSHIP_COMPLETE', 'ONLY_ORIGINAL_RAW_IDENTITY_COMPLETE_REUSE')
        for key,field in (('panel','panels'),('predicted_risk','predicted_risk')):
            reference=reuse[field]['C14_D02']; expected={k:reference[k] for k in ('path','sha256')}
            owner.require(custody.get('d02_artifacts',{}).get(key)==expected, 'EXACT_REVIEWED_RAW_IDENTITY_ARTIFACT_REQUIRED')
            journal.pin(expected['path'],expected['sha256'])
    raw=raw.copy(); geometry=geometry.copy()
    raw['signal_date']=pd.to_datetime(raw.signal_date); geometry['signal_date']=pd.to_datetime(geometry.signal_date)
    dates=tuple(d.isoformat() for d in sorted(raw.signal_date.unique()))
    owner.require(dates==tuple(journal.dates) and len(dates)==CALENDAR_DATES and raw.signal_date.lt('2026-01-01').all()
                  and len(geometry)==CALENDAR_DATES*200 and owner.pairs.pair_key_sha256(geometry)==q['pair_key_sha256']
                  and owner.content_hash(raw[[*owner.KEYS,'U_t_fingerprint','raw_rank']].astype(str).values.tolist())==q['full_U_keys_sha256'],
                  'EXACT_ORIGINAL_FULL752_INPUT_REQUIRED')
    owner.require(requirements['research_id']==owner.ID and requirements['design_sha256']==binding.DESIGN_SHA
                  and requirements['dag_sha256']==binding.DAG_SHA,'FROZEN_REQUIREMENT_MATRIX_REQUIRED')
    matrix={r['role']:r for r in requirements['roles']}
    frozen={r['candidate_id']:r for r in design['risk']['classical_bindings']}
    result=dict(status='MEMBERSHIP_ASSEMBLY_COMPLETE',research_id=owner.ID,complete_candidates=[],failed_or_untestable={},
        panels={},native_pair_predictions={},predicted_risk={},variance_diagnostics={},roles={},input_qualification=qualification_ref,scientific_retry=0,forecast2026_rows=0,strict_PIT_promotion_eligible=False)
    proposal=None
    for role in ROLES:
        root=base/role
        if role=='C14_D02' and reuse is not None:
            owner.require(reuse['panels'][role].get('calendar_dates')==CALENDAR_DATES
                and reuse['panels'][role].get('common_rows')==len(raw)
                and reuse['predicted_risk'][role].get('rows')==CALENDAR_DATES
                and reuse['variance_diagnostics'][role]==reuse['predicted_risk'][role], 'EXACT_FULL752_RAW_IDENTITY_REUSE_REQUIRED')
            result['complete_candidates'].append(role)
            for field in ('panels','predicted_risk','variance_diagnostics','roles'):
                result[field][role]=json.loads(json.dumps(reuse[field][role]))
            continue
        assert_safe_output_path(root,kind='backtest',paths=resolve(owner.REPO))
        failure=None; panels=[]; daily=[]; receipts=[]; req=matrix.get(role)
        try:
            owner.require(req is not None and tuple(req['required_dates'])==dates,'EXACT752_ROLE_REQUIREMENT_REQUIRED')
            route=req['solver_requirement']['route']
            expected=(design['risk']['gate_families'][role.removeprefix('C14_')] if role in VETO else frozen[role]['family'])
            method=role.removeprefix('C14_') if role in VETO else frozen[role]['existing_rule']
            owner.require(req['required_family_method']==expected and req['solver_requirement']['existing_owner']==method,
                          'FROZEN_FAMILY_MEMBERSHIP_OWNER_CHANGED')
            owner.require(route==('CLASSICAL' if role in CLASSICAL else 'RAW_IDENTITY' if role=='C14_D02' else 'VETO'),
                          'EXACT_FROZEN_MEMBERSHIP_ROUTE_REQUIRED')
            if role in CLASSICAL:owner.require(role in journal.roles,'INDEPENDENT_FULL752_NUMERIC_GATE_REQUIRED')
            if role in VETO:
                inputs_owner=getattr(get_risk,'__self__',None)
                owner.require(callable(getattr(inputs_owner,'role_gate',None)),'EXISTING_RISK_INPUTS_GATE_OWNER_REQUIRED')
                gate=inputs_owner.role_gate(role)
                owner.require(gate.get('phase')=='FULL752_NUMERIC_INPUT_QUALIFIED' and gate.get('role')==role
                    and gate.get('family')==req['required_family_method'] and gate.get('full_required_dates_qualified') is True
                    and gate.get('source_review')==source_review_ref and len(gate.get('states',[]))==CALENDAR_DATES
                    and [r.get('decision_date') for r in gate['states']]==list(dates),
                    'INDEPENDENT_FULL752_VETO_INPUT_GATE_REQUIRED')
            for day,raw_day in raw.groupby('signal_date',sort=True):
                rankraw=raw_day.sort_values('raw_rank'); raw40=rankraw.security_uid.iloc[:40].tolist()
                if role=='C14_D02':
                    out=binding.classical_route(req,None,None,raw40,decision_close(day))
                    owner.require(out['chosen_uids']==raw40[:20] and out['optimizer_solve_calls']==0,'RAW_IDENTITY_ZERO_SOLVE_REQUIRED')
                if role=='C14_D02' or role in VETO and day.year==2023:
                    panel=raw_day.copy(); panel['score']=panel.raw_score; panel['rank']=panel.raw_rank;panel['candidate_id']=role
                    panels.append(panel)
                    daily.append(dict(candidate_id=role,signal_date=day,status='EXACT_RAW_IDENTITY' if role=='C14_D02' else 'EXACT_2023_RAW_FALLBACK',
                                      learned_prediction=False,optimizer_solve_calls=0))
                    continue
                meta,payload=get_risk(role,day)
                owner.require(meta.role==role and meta.family==req['required_family_method']
                    and binding.clock(meta.decision_asof)==binding.clock(decision_close(day))
                    and set(rankraw.security_uid)==set(binding._consumer_uids(meta)), 'EXACT_CURRENT_FULL_U_ROLE_INPUT_REQUIRED')
                if role in CLASSICAL:
                    g=geometry.loc[geometry.signal_date.eq(day)]
                    identity=input_identity(req,meta,raw_day,g,journal)
                    out=journal.classical_request('CLASSICAL|'+role+'|'+day.isoformat(),identity,
                        lambda:binding.classical_route(req,meta,payload,raw40,decision_close(day)))
                else:
                    if proposal is None: proposal=_p01_reader(run,q,geometry,review)
                    cached=proposal(day,raw_day)
                    out=binding.whole_set_veto(meta,payload,raw40,cached['chosen_uids'],proposal_receipt=cached)
                    owner.require(out['rematching'] is False and out['extra_solves']==0,'WHOLE_SET_VETO_NO_REMATCH_REQUIRED')
                chosen=out['chosen_uids']; before,after=predicted_risk(meta,payload,raw40,chosen)
                panels.append(panel_for(raw_day,chosen,role));receipts.append(dict(signal_date=day.isoformat(),result=out))
                daily.append(dict(candidate_id=role,signal_date=day,status='COMPLETE',learned_prediction=role in VETO,
                    predicted_variance_before=before['predicted_variance'],predicted_variance_after=after['predicted_variance'],
                    before=before,after=after,optimizer_solve_calls=1 if role in CLASSICAL else 0,
                    veto_status=out.get('status') if role in VETO else None))
            panel=pd.concat(panels,ignore_index=True)[[*owner.KEYS,'ticker','U_t_fingerprint','score','rank','candidate_id']]
            owner.require(len(panel)==len(raw) and panel.signal_date.nunique()==CALENDAR_DATES,'FULL752_NO_PARTIAL_SUCCESS_REQUIRED')
        except Exception as error:failure=f'{type(error).__name__}:{error}'
        status=dict(status='MEMBERSHIP_COMPLETE' if failure is None else 'MEMBERSHIP_FAILED',role=role,
            failure=failure,calendar_dates=CALENDAR_DATES,raw_fallback_2023_exact=role in VETO,
            year2023_counted_as_learning_success=False,source_review=source_review_ref,scientific_retry=0,forecast2026_rows=0)
        if failure is None:
            pref=owner.write_table(root/'scores_pre2026.parquet',panel);pref.update(calendar_dates=CALENDAR_DATES,common_rows=len(raw),raw_fallback_2023_exact=role in VETO)
            riskref=owner.write_table(root/'predicted_risk_pre2026.parquet',pd.DataFrame(daily))
            owner.write_json(root/'MEMBERSHIP_RECEIPTS.json',receipts)
            result['complete_candidates'].append(role);result['panels'][role]=pref;result['predicted_risk'][role]=riskref;result['variance_diagnostics'][role]=riskref
        else:result['failed_or_untestable'][role]=failure
        owner.write_json(root/'MEMBERSHIP_ASSEMBLY.json',status);result['roles'][role]=status
    owner.write_json(base/'MEMBERSHIP_ASSEMBLY.json',result)
    return result
