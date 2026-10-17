"""R11A1 metadata prebinding only; the original numeric consumer stays pinned.

This extends its publication boundary, not RiskState/source authority. No bank
reader, estimator, registry, run creation or numeric execution entrypoint.
"""
from pathlib import Path
import copy
import json
from dataclasses import dataclass
from scripts.research.a2.training import stateful_risk_consumer as c

RUN = Path('D:/us-tech-quant-backtests/V24/20261004T044305+0000_d21499cc')
PLAN_SHA = '97dd4d91560bc80885eea511adb89a7bced2b52882bed26ddfefb0694aca54f0'
CONSUMER_SHA = '982411a8cca345b96b3b6b7e7bb5fc395d187a838c021366d8960180b01715c0'
PUBLICATIONS = {
    'global': ('work/SHARED_R5_ALL_STATE_HANDOFF_MANIFEST_R1.json', 'B_R5_SHARED_ALL_STATE_PUBLICATION_MANIFEST_V1'),
    'projection': ('work/R11A1_B_R5_CONSUMER_PROJECTION_R1.json', 'B_R5_R11A1_PREFROZEN_FAMILY_PROJECTION_V1'),
    'alias': ('work/R5_SECURITY_ID_SOURCE_COLUMN_ALIAS_PROVENANCE_R1.json', 'B_R5_SECURITY_ID_SOURCE_COLUMN_ALIAS_PROVENANCE_V1')}
STATUSES = ('ELIGIBLE', 'BLOCKED_SOURCE', 'BLOCKED_IDENTITY', 'BLOCKED_TIME',
    'BLOCKED_STATE', 'BLOCKED_PSD', 'BLOCKED_COVERAGE', 'BLOCKED_LEDGER',
    'BLOCKED_RECIPE', 'BLOCKED_ENGINEERING_PIN')
FINGERPRINT_KEYS = ('research_id','family','method','source_path','source_sha256',
    'source_version','bank_schema','state_schema','schema_version','source_identity',
    'cutoff','state_available_at','as_of','ordered_U','security_ids','uids','epochs',
    'security_coordinate','horizon','coordinate','parameters','history_recipe',
    'state_sha256','recipe_sha256','producer_sha256','ledger_ref','ledger_sha256',
    'fit_dependency_ids')


def metadata_plan():
    """Read only the original sealed descriptors; NOT numeric pin acceptance."""
    base=c.resolve(c.owner.REPO).results_root/'_maintenance'/c.FREEZE_TASK
    paths=(base/'R11A1_PREREGISTERED_DESIGN.json',base/'R11A1_PHYSICAL_DAG.json')
    c._need([c.owner.sha(p) for p in paths]==[c.DESIGN_SHA,c.DAG_SHA], 'FROZEN_A1_BYTES_CHANGED')
    plan=c.FrozenPlan(*(json.loads(p.read_text(encoding='utf-8-sig')) for p in paths))
    plan.verify()
    return plan


def expected_attempts():
    path=RUN/'R5_FINITE_EVENT_RISK_PLAN.json'
    c._need(c.owner.sha(path)==PLAN_SHA,'EXACT_ORIGINAL_R5_PLAN_REQUIRED')
    plan=json.loads(path.read_text(encoding='utf-8-sig'))
    keys=[(n['event_id'],f) for n in plan['nodes'] for f in n['families']]
    c._need(len(keys)==len(set(keys))==403,'ORIGINAL_403_ROSTER_REQUIRED')
    return tuple(keys)


def scope_requirements(plan):
    plan.verify(); rows=[]
    for scope in plan.dag['scopes']:
        family,head,year=scope.split('|'); spec=plan.family(family)
        nodes=plan.scope_nodes(scope)
        rows.append(dict(scope=scope,family=family,head=head,year=int(year),
            node_ids=[n['node_id'] for n in nodes],node_spec_sha256=[n['node_spec_SHA'] for n in nodes],
            learners=[dict(learner=n['learner'],arm=n['arm'],parameters=n['parameters'],seed=n['seed'],
                capacity=n['capacity'],cutoff=n['cutoff']) for n in nodes if n['kind']=='estimator'],
            risk_fields=list(c.ENTRY_COLUMNS+(c.PAIR_COLUMNS if head=='UNIFIED_INCUMBENT' else ())),
            method=spec['method'],recipe_sha256=spec['recipe_SHA'],producer_sha256=spec['producer_SHA'],
            horizon=5,coordinate=spec['coordinate'],security_coordinate=c.COORDINATE,
            train_cutoff=f'{year}-01-01T00:00:00+00:00',
            evaluation_window=[f'{year}-01-01T00:00:00+00:00',f'{int(year)+1}-01-01T00:00:00+00:00'],
            clocks='cutoff < as_of <= independent state_available_at <= decision_information_time; train all < own fold cutoff',
            raw20={'exact_unique_members':20,'weight_per_member':'1/20','identity':['SID','UID','epoch'],
                   'missing_member':'BLOCKED_COVERAGE','renormalization':False},
            actor='exact own row SID/UID/epoch at decision date',
            incumbent='exact own incumbent identity; no cohort/membership expiry extension' if head=='UNIFIED_INCUMBENT' else None,
            entrant='exact own entrant identity for REPLACE; absent only for original SELL structural zero' if head=='UNIFIED_INCUMBENT' else 'actor is entrant',
            ordered_U='original producer order; exact source-backed asset-to-SID map; never ticker fallback',
            required_state_metadata=list(c.handoff_schema()['properties']['states']['items']['required']),
            psd='literal true owner qualification; original numeric invariant remains future consumer gate',
            coverage='A Raw20 + actor/pair identities; global publication PASS insufficient',
            ledger='terminal original ledger ref/SHA + paid fit dependency IDs',
            matched_semantics='own family/head/year mask; identical BASE/PLUS rows,y,weights,dates,R8 keys; 10bps P0',
            current_status='BLOCKED_SOURCE',formal_state_bindings=None,
            structural_time_block='current publisher explicitly aliases state_available_at to as_of',
            engineering_pin='registry semantic-compatible descendant; original numeric pin still rejects it'))
    c._need(len(rows)==28,'ORIGINAL_28_SCOPES_REQUIRED')
    return rows


def _ref(value):
    return (type(value) is dict and c._text(value.get('path')) and
            Path(value['path']).is_absolute() and c._sha(value.get('sha256')))


def publication_view(plan, global_manifest, wrapper, alias, *, alias_ref):
    """Validate the complete global denominator; unwrap only the A consumer view."""
    plan.verify(); families=plan.design['families_order']
    for obj,name in ((global_manifest,'global'),(wrapper,'projection'),(alias,'alias')):
        c._need(type(obj) is dict and obj.get('schema')==PUBLICATIONS[name][1] and obj.get('research_id')==c.B_RESEARCH_ID,'EXACT_R5_PUBLICATION_SCHEMA')
    c._need(_ref(alias_ref) and global_manifest.get('SID_alias_provenance')==alias_ref and wrapper.get('SID_alias_provenance')==alias_ref,'EXACT_ALIAS_PUBLICATION_PIN')
    c._need(global_manifest.get('all_original_attempts_preserved') is True and global_manifest.get('A_and_C_must_independently_qualify') is True,'GLOBAL_DENOMINATOR_AND_OWN_GATES_REQUIRED')
    c._need(wrapper.get('A_consumer_qualification_granted') is False and wrapper.get('wholewindow_all_family_qualification_granted') is False and wrapper.get('requested_families')==families,'NO_PUBLICATION_AS_CONSUMER_PASS')
    c._need(wrapper.get('consumer_schema_sha256')==c.content_hash(c.handoff_schema()) and _ref(wrapper.get('consumer_schema_producer_ref')) and wrapper['consumer_schema_producer_ref']['sha256']==CONSUMER_SHA,'EXACT_EXISTING_CONSUMER_SCHEMA_PIN')
    attempts=global_manifest['states_and_retained_attempts']; expected=set(expected_attempts())
    keys=[(r['event_id'],r['family']) for r in attempts]
    c._need(len(keys)==len(set(keys)) and set(keys)==expected,'FULL_ORIGINAL_403_ATTEMPTS_REQUIRED')
    c._need(all(r['publication_status'] in ('VERIFIED_MECHANISM_STATE','BLOCKED_PUBLICATION_VERIFICATION','RETAINED_BLOCKED_OR_FAILED') for r in attempts),'KNOWN_PUBLICATION_ATTEMPT_STATUS')
    requested={k for k in expected if k[1] in families}
    c._need(wrapper['requested_state_count']==len(requested),'ORIGINAL_REQUESTED_FAMILY_DENOMINATOR')
    by_key=dict(zip(keys,attempts)); handoff=wrapper.get('handoff')
    states=[] if handoff is None else handoff['states']
    if handoff is not None:
        c._need(handoff['schema']=='R11A1_B_R5_HANDOFF_MANIFEST_R1' and handoff['research_id']==c.B_RESEARCH_ID and type(handoff['version']) is int and handoff['version']==1,'EXACT_FROZEN_INNER_HANDOFF')
        for slot in c.SOURCE_SLOTS:
            ref=handoff[slot]
            c._need(_ref(ref) and c._text(ref.get('schema')) and ref.get('qualified') is True and {k:ref[k] for k in ('path','sha256')}==global_manifest['publication_refs'][slot],'EXACT_FOUR_PUBLICATION_BINDINGS')
    projected=[]
    for m in states:
        c._need(type(m) is dict and set(m)==set(c.handoff_schema()['properties']['states']['items']['required']),'EXACT_FROZEN_STATE_METADATA_FIELDS')
        c._need(type(m['event_ids']) is list and len(m['event_ids'])==1,'ONE_EXACT_STATE_EVENT_REQUIRED')
        key=(m['event_ids'][0],m['family']); row=by_key.get(key)
        c._need(key in requested and row is not None and row['publication_status']=='VERIFIED_MECHANISM_STATE' and row['state_metadata']==m,'A_VIEW_EXACT_GLOBAL_STATE_REQUIRED')
        c._need(m['state_id']==row['risk_state_id'] and m['method']==row['method'] and m['as_of']==row['as_of'] and m['cutoff']==row['cutoff'] and m['ordered_U']==row['assets'] and m['uids']==row['asset_uids'] and m['epochs']==row['asset_epochs'] and m['fit_dependency_ids']==row['fit_dependency_ids'],'EXACT_ORIGINAL_STATE_ROW_CUSTODY')
        c._need(row['typed_state_content_sha256']==m['state_sha256'] and _ref(row.get('artifact_ref')) and row.get('physical_artifact_pin_verified') is True,'SEPARATE_TYPED_AND_PHYSICAL_CUSTODY')
        projected.append(key)
    blocks=[(r['event_id'],r['family']) for r in wrapper['typed_blocks']]
    c._need(len(projected)==len(set(projected)) and len(blocks)==len(set(blocks)) and not set(projected)&set(blocks) and set(projected)|set(blocks)==requested,'A_PROJECTION_CANNOT_DELETE_FAILURES')
    counts={s:sum(r['publication_status']==s for r in attempts) for s in ('VERIFIED_MECHANISM_STATE','BLOCKED_PUBLICATION_VERIFICATION','RETAINED_BLOCKED_OR_FAILED')}
    return dict(global_attempt_count=len(keys),global_status_counts=counts,A_requested_count=len(requested),
        A_projected_count=len(states),A_blocked_count=len(blocks),states=copy.deepcopy(states),
        global_rows={m['state_id']:copy.deepcopy(by_key[(m['event_ids'][0],m['family'])]) for m in states},
        alias=copy.deepcopy(alias),view_identity=c.owner.digest(dict(global_manifest=global_manifest,wrapper=wrapper,alias=alias)))


def fingerprint_input(metadata):
    c._need(type(metadata) is dict and all(k in metadata and metadata[k] is not None for k in FINGERPRINT_KEYS),'FINGERPRINT_UNBOUND')
    c.source_fingerprint(metadata)  # Reuse the exact existing owner validation.
    return {k:copy.deepcopy(metadata[k]) for k in FINGERPRINT_KEYS}


def binding_fingerprint(metadata):
    """Canonical metadata only; does NOT certify/activate a source."""
    return c.owner.digest(fingerprint_input(metadata))


def qualify_metadata(plan,meta,global_row,request,*,family,head,year,mode,
                     availability_witness=None,identity_witness=None,engineering_compatible=False,snapshot=None):
    """Prenumeric row assessment only. No typed-state deserialization or fit."""
    plan.verify()
    failures=[]
    if not isinstance(global_row,dict) or not isinstance(request,dict):
        return dict(status='BLOCKED_STATE',failures=[dict(status='BLOCKED_STATE',reason='EXPLICIT_ROW_REQUEST_METADATA')],fingerprint=None)
    def check(condition,status,reason):
        if not condition: failures.append(dict(status=status,reason=reason))
    spec=plan.family(family)
    c._need(head in ('ENTRY','UNIFIED_INCUMBENT') and type(year) is int and year in (2024,2025) and mode in ('train','eval'),'FROZEN_SCOPE_ROLE')
    if not isinstance(meta,dict): return dict(status='BLOCKED_SOURCE',failures=[dict(status='BLOCKED_SOURCE',reason='STATE_UNBOUND')],fingerprint=None)
    required=c.handoff_schema()['properties']['states']['items']['required']
    check(all(k in meta and meta[k] is not None for k in required),'BLOCKED_STATE','EXPLICIT_NON_NULL_STATE_METADATA')
    snapshot_ok=_snapshot_valid(snapshot)
    check(snapshot_ok and snapshot.data['view']['global_rows'].get(meta.get('state_id'))==global_row and meta in snapshot.data['view']['states'],'BLOCKED_SOURCE','PHYSICALLY_BOUND_SEALED_PUBLICATION_REQUIRED')
    check(snapshot_ok and snapshot.data.get('engineering_compatible') is True and engineering_compatible is True,'BLOCKED_ENGINEERING_PIN','EXACT_CURRENT_ENGINEERING_LINEAGE')
    check(meta.get('bank_schema')=='B_R5_EVENT_RISK_BANK_V1' and meta.get('state_schema')=='SHARED_RISK_STATE_R2' and type(meta.get('schema_version')) is int and meta.get('schema_version')==1 and c._text(meta.get('source_version')) and isinstance(meta.get('parameters'),dict) and bool(meta.get('parameters')) and isinstance(meta.get('history_recipe'),dict) and bool(meta.get('history_recipe')),'BLOCKED_STATE','EXACT_SCHEMA_VERSION_PARAMETERS_HISTORY')
    check(meta.get('family')==family and meta.get('method')==spec['method'] and meta.get('recipe_sha256')==spec['recipe_SHA'] and meta.get('producer_sha256')==spec['producer_SHA'],'BLOCKED_RECIPE','EXACT_FAMILY_METHOD_RECIPE_PRODUCER')
    check(meta.get('research_id')==c.B_RESEARCH_ID and meta.get('qualification_status')=='QUALIFIED' and meta.get('source_still_valid') is True and meta.get('maturity_still_valid') is True and c._sha(meta.get('source_sha256')) and c._text(meta.get('source_path')) and Path(meta.get('source_path','')).is_absolute(),'BLOCKED_SOURCE','EXACT_SOURCE_QUALIFICATION')
    receipt=global_row.get('source_receipt',{})
    check(isinstance(receipt,dict) and all(receipt.get(k)==meta.get(k) for k in ('source_sha256','source_identity','source_version')),'BLOCKED_SOURCE','EXACT_INDEPENDENT_SOURCE_RECEIPT_CUSTODY')
    check(meta.get('psd_qualified') is True and global_row.get('psd_qualified') is True,'BLOCKED_PSD','LITERAL_OWNER_PSD_QUALIFICATION')
    check(meta.get('coverage_qualified') is True and global_row.get('coverage_qualified') is True,'BLOCKED_COVERAGE','LITERAL_OWNER_COVERAGE')
    check(c._text(meta.get('ledger_ref')) and Path(meta.get('ledger_ref','')).is_absolute() and c._sha(meta.get('ledger_sha256')) and isinstance(meta.get('fit_dependency_ids'),list) and bool(meta.get('fit_dependency_ids')) and all(c._text(v) for v in meta.get('fit_dependency_ids',[])),'BLOCKED_LEDGER','TERMINAL_LEDGER_AND_DEPENDENCIES')
    check(meta.get('horizon')==5 and type(meta.get('horizon')) is int and meta.get('coordinate')==spec['coordinate'] and meta.get('security_coordinate')==c.COORDINATE and global_row.get('typed_state_content_sha256')==meta.get('state_sha256') and c._sha(meta.get('state_sha256')) and _ref(global_row.get('artifact_ref')) and global_row.get('physical_artifact_pin_verified') is True,'BLOCKED_STATE','SEPARATE_TYPED_PHYSICAL_SOURCE_COORDINATES')
    # An equal timestamp is legal only with independent explicit state authority.
    witness=availability_witness if isinstance(availability_witness,dict) else {}
    check(global_row.get('state_availability_authority')==witness and global_row.get('available_clock_role')=='INDEPENDENT_STATE_AVAILABILITY' and witness.get('authority_kind')=='INDEPENDENT_STATE_AVAILABILITY' and witness.get('state_id')==meta.get('state_id') and witness.get('state_available_at')==meta.get('state_available_at') and _ref(witness.get('authority_ref')) and witness.get('authority_verified') is True and snapshot_ok and _snapshot_ref_verified(snapshot,witness.get('authority_ref')),'BLOCKED_TIME','AS_OF_IS_NOT_INDEPENDENT_STATE_AVAILABILITY')
    try:
        available,asof,cutoff,decision=map(c._clock,(meta['state_available_at'],meta['as_of'],meta['cutoff'],request['decision_information_time']))
        fold=c._clock(f'{year}-01-01T00:00:00+00:00')
        check(cutoff<asof<=available<=decision<c.BOUNDARY,'BLOCKED_TIME','EXACT_NONFUTURE_STATE_CLOCK')
        check((decision<fold and available<fold and asof<fold and cutoff<fold) if mode=='train' else fold<=decision<c._clock(f'{year+1}-01-01T00:00:00+00:00'),'BLOCKED_TIME','OWN_FOLD_CLOCK')
        check(request['decision_date']==decision.date().isoformat(),'BLOCKED_TIME','OWN_DECISION_DATE')
    except (KeyError,ValueError,TypeError): check(False,'BLOCKED_TIME','MISSING_OR_INVALID_CLOCK')
    identity=identity_witness if isinstance(identity_witness,dict) else {}
    check(identity.get('decision_date')==request.get('decision_date') and identity.get('state_id')==meta.get('state_id') and identity.get('authority_verified') is True and _ref(identity.get('authority_ref')) and snapshot_ok and identity==snapshot.data.get('own_identity_witnesses',{}).get(request.get('request_id')) and _snapshot_ref_verified(snapshot,identity.get('authority_ref')),'BLOCKED_IDENTITY','OWN_DATE_IDENTITY_WITNESS_REQUIRED')
    try:
        assets=meta['ordered_U']; sids=meta['security_ids']; uids=meta['uids']; epochs=meta['epochs']
        c._need(type(assets) is list and len(assets)==len(set(assets)) and all(c._text(a) for a in assets),'ORDERED_U')
        c._need(all(type(x) is dict and set(x)==set(assets) and all(c._text(v) for v in x.values()) for x in (sids,uids,epochs)) and len(set(sids.values()))==len(assets),'EXACT_SOURCE_IDENTITY_MAPS')
        exact={sid:(sid,uids[a],epochs[a]) for a,sid in sids.items()}
        raw=request['raw20']; ids=[c._identity(r) for r in raw]
        check(len(ids)==20 and len({x[0] for x in ids})==20 and len({x[1] for x in ids})==20,'BLOCKED_COVERAGE','RAW20_EXACT20_NO_RENORMALIZATION')
        check(all(x[0] in exact for x in ids),'BLOCKED_COVERAGE','RAW20_MEMBER_MISSING_IN_STATE')
        check(all(exact.get(x[0])==x for x in ids),'BLOCKED_IDENTITY','RAW20_EXACT_SID_UID_EPOCH')
        check(exact.get(request['actor']['sid'])==c._identity(request['actor']),'BLOCKED_IDENTITY','ACTOR_EXACT_IDENTITY')
        if head=='UNIFIED_INCUMBENT' and request.get('action_type')==1:
            check(exact.get(request['entrant']['sid'])==c._identity(request['entrant']) and request['entrant']['sid']!=request['actor']['sid'],'BLOCKED_IDENTITY','ENTRANT_EXACT_IDENTITY')
        check(identity.get('raw20')==raw and identity.get('actor')==request['actor'] and identity.get('entrant')==request.get('entrant'),'BLOCKED_IDENTITY','EXACT_A_REQUEST_SOURCE_WITNESS')
        alias=request.get('alias_evidence')
        if alias is not None:
            check(_alias_date_valid(alias,request),'BLOCKED_IDENTITY','EXPLICIT_ALIAS_DATE_SCOPE_AND_AVAILABILITY')
            check(isinstance(alias,dict) and snapshot_ok and alias in snapshot.data.get('own_alias_witnesses',[]) and _snapshot_ref_verified(snapshot,alias.get('authority_ref')) and alias.get('state_id')==meta['state_id'] and alias.get('event_ids')==meta['event_ids'] and alias.get('decision_date')==request['decision_date'] and alias.get('qualified_for_exact_date') is True,'BLOCKED_IDENTITY','ALIAS_NEVER_EXTENDS_MEMBERSHIP_OR_EPOCH')
    except (KeyError,ValueError,TypeError,AttributeError,IndexError): check(False,'BLOCKED_IDENTITY','MISSING_OR_INVALID_OWN_IDENTITIES')
    if not failures:
        check(_snapshot_valid(snapshot),'BLOCKED_SOURCE','SEALED_PUBLICATION_CHANGED')
    return dict(status=failures[0]['status'] if failures else 'ELIGIBLE',failures=failures,
        fingerprint=None if failures else qualification_fingerprint(meta,snapshot,witness,identity,request.get('alias_evidence')),
        evidence_level='PRENUMERIC_METADATA_ONLY',numeric_execution_authorized=False)


PUBLISHER_PATH = Path('D:/us-tech-quant-cache/V24/V24_B_R5_R6_PUBLICATION_AND_POLICY_CLOSURE_R1/source_audit/prepare_r5_shared_handoff_partial_candidate.py')
PUBLISHER_SHA = 'f9c7c0c2488e0fe1bec232d6d5d432461ff7d675f7b173996049c546dccea85a'


def _physical_pin(ref, *, expected_path=None):
    """Hash exact D references only, not deserialize typed risk artifacts."""
    import stat
    c._need(_ref(ref),'EXPLICIT_PHYSICAL_REFERENCE_REQUIRED')
    path=Path(ref['path'])
    c._need(path.drive.upper()=='D:', 'NO_E_F_OR_PROVIDER_REFERENCE')
    if expected_path is not None:
        c._need(path==Path(expected_path),'EXACT_R5_PUBLICATION_FILENAME_REQUIRED')
    for component in reversed((path,*path.parents)):
        info=component.stat(follow_symlinks=False)
        c._need(not getattr(info,'st_file_attributes',0)&0x400 and not stat.S_ISLNK(info.st_mode),'NO_REPARSE_SOURCE_REFERENCE')
    c._need(path.is_file() and c.owner.sha(path)==ref['sha256'],'PHYSICAL_SOURCE_PIN_MISMATCH')
    return path


def bind_formal_publications(refs, *, publisher_ref=None):
    """Consume only exact source-only producer outputs; no live bank/ledger parse.

    Before content access the audited publisher and unchanged consumer must match.
    The three formal JSON files have a reviewed metadata-only construction. The
    four underlying objects are hash-verified, never deserialized here. No writer,
    registry activation, numeric row read, reservation or fit is reachable.
    """
    c._need(type(refs) is dict and set(refs)==set(PUBLICATIONS),'EXACT_THREE_PUBLICATION_REFERENCES_REQUIRED')
    publisher=_publication_producer_provenance(publisher_ref)
    consumer_provenance=_consumer_source_provenance()
    paths={name:_physical_pin(refs[name],expected_path=RUN/relative) for name,(relative,_) in PUBLICATIONS.items()}
    # These exact outputs are source-only by the pinned reviewed producer contract,
    # not a mixed bank/result file filtered after reading.
    bodies={name:json.loads(path.read_text(encoding='utf-8-sig')) for name,path in paths.items()}
    for name,path in paths.items(): c._need(c.owner.sha(path)==refs[name]['sha256'],'PUBLICATION_CHANGED_DURING_READ')
    view=publication_view(metadata_plan(),bodies['global'],bodies['projection'],bodies['alias'],alias_ref=refs['alias'])
    producer_refs=bodies['global']['publication_refs']
    c._need(producer_refs.get('publication_producer')==publisher and producer_refs.get('A_consumer')=={'path':str(Path(c.__file__)),'sha256':CONSUMER_SHA},'EXACT_REVIEWED_PUBLICATION_OWNER_CHAIN')
    _physical_pin(producer_refs['publication_producer'],expected_path=Path(publisher['path']))
    # Published old ref remains unchanged; archived exact bytes prove its historical custody.
    c._need(producer_refs['A_consumer']['sha256']==CONSUMER_SHA,'ORIGINAL_PUBLISHED_CONSUMER_REQUIRED')
    _consumer_source_provenance()
    handoff=bodies['projection'].get('handoff')
    bound={}
    if handoff is not None:
        expected={'bank':RUN/'models/risk/EVENT_RISK_BANK_R5.json','freeze':RUN/'R5_SCIENCE_AND_EXECUTION_FREEZE.json','ledger':RUN/'work/FIT_STATUS.json'}
        # Qualification path is the recovery receipt explicitly bound by the freeze;
        # do not invent the original qualification filename or scan directories.
        freeze_path=_physical_pin(handoff['freeze'],expected_path=expected['freeze'])
        freeze=json.loads(freeze_path.read_text(encoding='utf-8-sig'))
        qref=freeze['qualification_ref']
        c._need({k:handoff['qualification'][k] for k in ('path','sha256')}==qref,'EXACT_FREEZE_QUALIFICATION_REFERENCE')
        expected['qualification']=Path(qref['path'])
        for slot in c.SOURCE_SLOTS:
            _physical_pin(handoff[slot],expected_path=expected[slot]); bound[slot]=copy.deepcopy(handoff[slot])
    engineering=_engineering_prebind_status()
    data=dict(view=view,consumer_provenance=consumer_provenance,publication_producer=publisher,formal_refs=copy.deepcopy(refs),publication_bindings=bound,verified_refs=[*refs.values(),*bound.values()],
        own_identity_witnesses={},own_alias_witnesses=[],engineering_compatible=engineering['semantic_compatible'],engineering_status=engineering,
        bound_identity=c.owner.digest(dict(formal_refs=refs,publication_bindings=bound,view_identity=view['view_identity'])),
        source_activated=False,registry_activated=False,numeric_execution_authorized=False)

    # No caller true flags are admitted. Missing independent authority stays absent.
    return _snapshot(data)


_SNAPSHOT_TOKEN = object()

@dataclass(frozen=True)
class MetadataSnapshot:
    data: dict
    seal: str
    provenance: object


def _snapshot(data):
    """Private binder/test-fixture constructor; never a source authority."""
    data=copy.deepcopy(data)
    return MetadataSnapshot(data,c.owner.digest(data),_SNAPSHOT_TOKEN)


def _snapshot_valid(snapshot):
    return (type(snapshot) is MetadataSnapshot and snapshot.provenance is _SNAPSHOT_TOKEN
            and c.owner.digest(snapshot.data)==snapshot.seal)


def _snapshot_ref_verified(snapshot,ref):
    return _snapshot_valid(snapshot) and _ref(ref) and ref in snapshot.data.get('verified_refs',[])


REGISTRY_PATH = Path('D:/us-tech-quant/scripts/maintenance/research_registry.py')
OLD_REGISTRY_SHA = 'b25bb0c99254b6405b78a6d3aee3c36b2cbb3764ed2517d38173430a694de8af'
CURRENT_REGISTRY_SHA = '4f283ae0dd814bf18ea0c1ce93ea271e403848be2d9c1bdd782dd66004120c80'
B_CLOSURE = Path('D:/us-tech-quant-results/_maintenance/V24_B_R5_R6_PUBLICATION_AND_POLICY_CLOSURE_R1')
B_AUDIT = Path('D:/us-tech-quant-cache/V24/V24_B_R5_R6_PUBLICATION_AND_POLICY_CLOSURE_R1/source_audit')
REGISTRY_LINEAGE = {
    'old_source':(B_AUDIT/'research_registry_before_publication_closure.py',OLD_REGISTRY_SHA),
    'intermediate_source':(B_AUDIT/'research_registry_query_r5_dce17f4a_snapshot.py','dce17f4a61aa4dd9db06dfe57dc165e886af8993014407b8256bce0c9580daa2'),
    'current_source':(REGISTRY_PATH,CURRENT_REGISTRY_SHA),
    'independent_review':(B_CLOSURE/'R5_REGISTRY_CODE_INDEPENDENT_REVIEW_R1.json','755fff97bc32153e90c461ad0d3e6724db5cf84bea2a9d5d433c37c84003fa2c'),
    'query_proof':(B_CLOSURE/'R5_EXACT_QUERY_SOURCE_ALIAS_ENGINEERING_PROOF_R1.json','c98ba3e068d00118268282e1696d1669e4512cb2da014acab4836cba17c86866'),
    'query_application':(B_CLOSURE/'R5_QUERY_SOURCE_ALIAS_APPLICATION_RECEIPT_R1.json','a131946239c790282dd7a378918f05e47b2299d1a972a4c6a143f8754661f90d')}


def registry_descendant_compatibility():
    """Exact reviewed engineering lineage, never adoption of the old numeric pin."""
    checked={}
    for key,(path,digest) in REGISTRY_LINEAGE.items():
        c._need(c.owner.sha(path)==digest,'ENGINEERING_LINEAGE_PIN_MISMATCH:'+key)
        checked[key]={'path':str(path),'sha256':digest}
    review=json.loads(REGISTRY_LINEAGE['independent_review'][0].read_text(encoding='utf-8-sig'))
    application=json.loads(REGISTRY_LINEAGE['query_application'][0].read_text(encoding='utf-8-sig'))
    c._need(review['status']=='PASS' and application['status']=='PASS_ACTUAL_ORIGINAL_RUNTIME_GATE_ZERO_FIT' and application['applied_registry_code_sha256']==CURRENT_REGISTRY_SHA and application['stored_registry_rows_or_hashes_changed'] is False,'ACCEPTED_ENGINEERING_DESCENDANT_REQUIRED')
    adopted=c.owner.sha(Path(c.__file__))==ADOPTED_CONSUMER_SHA and c.owner.sha(CONSUMER_CUSTODY_PATH)==CONSUMER_SHA
    return dict(semantic_compatible=True,refs=checked,current_sha256=CURRENT_REGISTRY_SHA,
                frozen_pin_sha256=OLD_REGISTRY_SHA,numeric_pin_accepted=adopted,
                old_FrozenPlan_load_will_reject=not adopted,old_execute_node_will_reject=not adopted)


def qualify_scopes(plan,snapshot,requests_by_scope):
    """Independent metadata scopes; no reservation, fit, labels or BASE/PLUS change."""
    requirements=scope_requirements(plan); result=[]
    for required in requirements:
        scope=required['scope']; rows=[]
        requests=requests_by_scope.get(scope,[])
        states=[] if not _snapshot_valid(snapshot) else snapshot.data['view']['states']
        if not states:
            result.append(dict(scope=scope,status='BLOCKED_SOURCE',rows=[],reason='FORMAL_STATE_METADATA_UNBOUND',numeric_execution_authorized=False));continue
        if not requests:
            result.append(dict(scope=scope,status='BLOCKED_IDENTITY',rows=[],reason='OWN_RAW20_ACTOR_DATE_METADATA_UNBOUND',numeric_execution_authorized=False));continue
        for request in requests:
            try:
                # Exact requested state only. No nearest-date/UID carry search.
                matches=[m for m in states if m['state_id']==request['state_id'] and m['family']==required['family']]
                c._need(len(matches)==1,'EXACT_REQUESTED_STATE_REQUIRED')
                meta=matches[0];global_row=snapshot.data['view']['global_rows'][meta['state_id']]
                witness=global_row.get('state_availability_authority')
                identity=snapshot.data.get('own_identity_witnesses',{}).get(request.get('request_id'))
                rows.append(qualify_metadata(plan,meta,global_row,request,family=required['family'],head=required['head'],year=required['year'],mode=request['mode'],availability_witness=witness,identity_witness=identity,engineering_compatible=snapshot.data['engineering_compatible'],snapshot=snapshot))
            except (c.ConsumerBlocked,KeyError,TypeError,ValueError) as e:
                rows.append(dict(status='BLOCKED_STATE',failures=[dict(status='BLOCKED_STATE',reason=str(e))],fingerprint=None,numeric_execution_authorized=False))
        eligible=sum(r['status']=='ELIGIBLE' for r in rows)
        result.append(dict(scope=scope,status='ELIGIBLE' if eligible else rows[0]['status'],rows=rows,
            eligible_metadata_rows=eligible,blocked_metadata_rows=len(rows)-eligible,
            own_mask_only=True,matched_numeric_package_still_unbound=True,numeric_execution_authorized=False))
    return result



def qualification_fingerprint(metadata,snapshot,availability,identity,alias=None):
    """Hash physical publications AND own authority dates; still no activation."""
    c._need(_snapshot_valid(snapshot),'SEALED_PUBLICATION_REQUIRED')
    return c.owner.digest(dict(state_metadata=fingerprint_input(metadata),
        formal_refs=snapshot.data.get('formal_refs'),publication_bindings=snapshot.data.get('publication_bindings'),
        availability_authority=availability,own_identity_authority=identity,own_alias_authority=alias))



def _alias_date_valid(alias,request):
    """An explicit exact date or half-open source interval; no inferred carry."""
    if not isinstance(alias,dict): return False
    try:
        decision=c._clock(request['decision_information_time'])
        if c._clock(alias['available_at'])>decision: return False
        from datetime import date
        day=request['decision_date'];current=date.fromisoformat(day)
        if current.isoformat()!=day: return False
        if 'valid_from' in alias or 'valid_until_exclusive' in alias:
            start=date.fromisoformat(alias['valid_from']);end=date.fromisoformat(alias['valid_until_exclusive'])
            return start.isoformat()==alias['valid_from'] and end.isoformat()==alias['valid_until_exclusive'] and start<=current<end
        exact=date.fromisoformat(alias['valid_date'])
        return exact.isoformat()==alias['valid_date']==day
    except (KeyError,ValueError,TypeError): return False



def _engineering_prebind_status():
    """A pin failure blocks its scopes, not independent publication preparation."""
    try: return registry_descendant_compatibility()
    except (c.ConsumerBlocked,OSError,ValueError,TypeError,KeyError) as error:
        return dict(semantic_compatible=False,status='BLOCKED_ENGINEERING_PIN',
                    reason=str(error),numeric_pin_accepted=False)


ADOPTED_CONSUMER_SHA = '44c3acc29493ff310a0d4566ff950091e0bf891e1c8c65950cb6952a36995e0a'
CONSUMER_CUSTODY_PATH = Path('D:/us-tech-quant-results/_maintenance/V24_A_R11A1_R5_REAL_SOURCE_BINDING_AND_SCOPE_GATE_R1/source_custody/stateful_risk_consumer_before_registry_descendant.py')
PUBLISHER_R2_PATH = B_AUDIT/'prepare_r5_shared_handoff_partial_candidate_r2.py'
PUBLISHER_R2_SHA = 'fcf2319ae4b79df55bfafaf12f8e15cca59087651dc2e65c6473bf7d303f653a'
PUBLISHER_R2_REVIEW = B_CLOSURE/'R5_SHARED_HANDOFF_PUBLICATION_TYPED_CHAIN_BLOCK_REVIEW_R2.json'
PUBLISHER_R2_REVIEW_SHA = 'e0c2c407e1ca2c7bec8d9f8da5af0a5aa9921452c3194dd07b05bbd61f7e5c64'
PUBLISHER_R2_RECEIPT = B_CLOSURE/'R5_SHARED_HANDOFF_PUBLICATION_ACTUAL_RECEIPT_R2.json'
PUBLISHER_R2_RECEIPT_SHA = 'c4fe165d7add63ad476dd45924a8121ff9b152ca9fd33ace00106af9e50e0416'


def _consumer_source_provenance():
    """Original publication source and exact adopted runtime are distinct pins."""
    current={'path':str(Path(c.__file__)),'sha256':c.owner.sha(Path(c.__file__))}
    if current['sha256']==CONSUMER_SHA:
        return dict(published=current,runtime=current,engineering_descendant=False)
    c._need(current['sha256']==ADOPTED_CONSUMER_SHA,'UNREVIEWED_CONSUMER_SOURCE_CHANGE')
    original={'path':str(CONSUMER_CUSTODY_PATH),'sha256':CONSUMER_SHA}
    _physical_pin(original,expected_path=CONSUMER_CUSTODY_PATH)
    return dict(published={'path':str(Path(c.__file__)),'sha256':CONSUMER_SHA},
        published_source_custody=original,runtime=current,engineering_descendant=True,
        frozen_source_ref_rewritten=False)


def _publication_producer_provenance(reference=None):
    """Only the two exact reviewed publishers, never an arbitrary caller pin."""
    legacy={'path':str(PUBLISHER_PATH),'sha256':PUBLISHER_SHA}
    revised={'path':str(PUBLISHER_R2_PATH),'sha256':PUBLISHER_R2_SHA}
    reference=legacy if reference is None else reference
    c._need(reference in (legacy,revised),'UNREVIEWED_PUBLICATION_PRODUCER')
    _physical_pin(reference,expected_path=Path(reference['path']))
    if reference==revised:
        _physical_pin({'path':str(PUBLISHER_R2_REVIEW),'sha256':PUBLISHER_R2_REVIEW_SHA},expected_path=PUBLISHER_R2_REVIEW)
        _physical_pin({'path':str(PUBLISHER_R2_RECEIPT),'sha256':PUBLISHER_R2_RECEIPT_SHA},expected_path=PUBLISHER_R2_RECEIPT)
        review=json.loads(PUBLISHER_R2_REVIEW.read_text(encoding='utf-8-sig'))
        c._need(review['revision']['sha256']==PUBLISHER_R2_SHA and review['independent_source_review']['status']=='PASS' and review['guards_preserved']['source_chain_qualification_granted'] is False,'EXACT_REVIEWED_TYPED_BLOCK_DESCENDANT')
    return copy.deepcopy(reference)
