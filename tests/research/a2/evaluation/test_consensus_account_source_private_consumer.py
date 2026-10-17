"""Synthetic fixtures only: no real kwargs/quotes/FX/forecasts/account/run reads."""
import copy
from dataclasses import asdict, replace
import importlib.util
import json
import pickle
from pathlib import Path
from types import ModuleType, SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_account_source_private_consumer as shim
from scripts.research.a2.evaluation import consensus_account_source_continuation as routing
from scripts.research.a2.data import consensus_cad_source_completion as cad
from scripts.research.a2.data import consensus_account_inputs as inputs


def fixtures_module(name, path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


ROOT=Path(shim.__file__).parents[4]
cf=fixtures_module('_private_consumer_generated_CAD_fixtures',ROOT/'tests/research/a2/data/test_consensus_cad_source_completion.py')
rf=fixtures_module('_private_consumer_generated_routing_fixtures',ROOT/'tests/research/a2/evaluation/test_consensus_account_source_continuation.py')


def saved(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8');return routing.file_ref(path)


@pytest.fixture
def generated(tmp_path,monkeypatch):
    # The frozen consumer owns an isolated routing namespace. Bind the same
    # reviewed functions into a test module so monkeypatch updates its globals,
    # and construct synthetic refs from that logical frozen owner.
    if shim.routing is not routing:
        original_ns=shim.routing.template.__globals__
        private=ModuleType('_generated_private_consumer_routing')
        private.__dict__.update(original_ns)
        for name,function in tuple(private.__dict__.items()):
            if isinstance(function,shim.FunctionType) and function.__globals__ is original_ns:
                private.__dict__[name]=shim._rebind(function,private.__dict__)
        monkeypatch.setattr(shim,'routing',private)
        monkeypatch.setattr(rf,'routing',private)
        monkeypatch.setitem(globals(),'routing',private)
    sources,_,_,calendar=cf.source_fixtures(tmp_path,monkeypatch,keys=list(cad.CASES))
    fx,oldmarks,early=cf.fx_fixtures(tmp_path,monkeypatch,sources)
    fx3=cad.qualify_fx_marks(oldmarks,early,sources=sources[:3]);fx1=cad.qualify_fx_marks(oldmarks,early,sources=sources[3:])
    facts=tuple(cf.native(source,fx3 if i<3 else fx1) for i,source in enumerate(sources))
    origin=saved(tmp_path/'original_kwargs_metadata.json',dict(generated_only=True));monkeypatch.setattr(cad,'ORIGINAL_KWARGS_REF',origin)
    entries=[];descendants=[];allrecords=[];allfps=[];bundles={};usd_calls=[]
    for index in range(1,21):
        number={16:1,17:3,18:1,19:4,20:7}.get(index,3)
        foreign=facts[:3] if index==17 else facts[3:] if index==18 else None
        events=tuple(n.source.event for n in foreign) if foreign else tuple(replace(cf.old_events()[j],event_id=f'NEW_{index}_{j}',old_security_id=f'GENERATED_USD_SID_{index}_{j}',ticker=f'U{index}_{j}') for j in range(number))
        records=[dict(ticker=e.ticker,effective_date=e.ex_date,reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='generated_original_binding',source_fingerprint=cad.digest([index,j])) for j,e in enumerate(events)]
        ownerref=routing.file_ref(cad.__file__)
        if foreign:
            metarecords=[dict(key=list(n.source.key),original_record=k,original_record_key=inputs.existing.source._key(k)) for n,k in zip(foreign,records)]
            metadata=saved(tmp_path/f'cad{index}_original5.json',dict(status='PASS_EXACT_ORIGINAL7_PREDECODE_AUTHORITY_AND_THREE_FIVEFIELD_METADATA' if index==17 else 'PINNED_ORIGINAL194_FIVEFIELD_METADATA_REQUIRES_ACTUAL_SERDE_MATCH',original_kwargs_ref=origin,records=metarecords))
            monkeypatch.setattr(cad,'ORIGINAL_BLOCKERS_REF' if index==17 else 'CCJ2024_ORIGINAL_BLOCKERS_REF',metadata)
            rows=[]
            for j,n in enumerate(foreign):
                sq=saved(tmp_path/f'cad{index}_{j}_source.json',dict(event=asdict(n.source.event),receipt=n.source.receipt,receipt_sha256=n.source.receipt_sha256))
                np=saved(tmp_path/f'cad{index}_{j}_native.json',dict(proof=n.proof,proof_sha256=n.proof_sha256))
                rows.append(dict(key=list(n.source.key),source_qualification_ref=sq,native_proof_ref=np,native_proof_fingerprint=n.proof_sha256))
            bundle=dict(status='QUALIFIED_SOURCE_NATIVE_COMPONENT_ONLY_NOT_ACCOUNT',completion_binder_owner_ref=ownerref,native_proofs=rows)
        else:
            native=dict(events=dict(entitlement_events=events,entitlement_security_tickers={e.old_security_id:e.ticker for e in events},entitlement_source_binding=dict(source_fingerprint=cad.digest(index),manifest=dict(removed_exact_original_keys=records)),research_account_authority={}))
            bundle=dict(generated_USD_native=native)
        # USD fixture payload stays in memory; JSON contains metadata only.
        br=saved(tmp_path/f'bundle{index}.json',dict(generated_only=True));bundles[br['path']]=bundle
        item=dict(bundle_ref=dict(br,bytes=123),native_owner_ref=dict(ownerref,bytes=456),original_namespace=f'cad{index}' if foreign else f'USD{index}',event_keys=records,event_fingerprints=[e.event_fingerprint for e in events],historical_note='synthetic prefix preserves metadata')
        entries.append(item);allrecords.extend(records);allfps.extend(item['event_fingerprints'])
    original=dict(corporate_actions=(),corporate_action_known_at={},unsupported_events=tuple(allrecords+[dict(allrecords[0],ticker='RETAINED')]),entitlement_enabled=True,entitlement_events=cf.old_events()+(cf.trp_event(),),entitlement_security_tickers={},entitlement_source_binding=dict(manifest={},source_fingerprint='d'*64))
    for index in (17,18):
        bundle=bundles[entries[index-1]['bundle_ref']['path']];bundle['original_resolution']=cad.qualify_original_records(original,facts[:3] if index==17 else facts[3:],original_ref=origin)
    def read(ref):
        path=str(ref['path'])
        if path in bundles:return bundles[path]
        return json.loads(routing._pin(shim.canonical(ref)).read_text())
    def loader(ref,namespace):
        if namespace.startswith('cad'):return cad
        def bind(env,kwargs,bundle,*,account_dates,bundle_ref):
            assert set(kwargs)==cad.ORIGINAL7 and set(bundle_ref)=={'path','sha256'};usd_calls.append(namespace)
            return bundle['generated_USD_native']
        return SimpleNamespace(bind_source_account_descendant=bind)
    monkeypatch.setattr(inputs.existing,'_load_python',loader)
    expected=dict(base_ref=saved(tmp_path/'base105.json',dict(generated_only=True)),supplements=entries)
    ef=saved(tmp_path/'expected61.json',dict(expected_supplement_count=49,expected_source_set=expected))
    bootstrap=saved(tmp_path/'source_bootstrap.json',dict(schema='ORIGINAL_BOOTSTRAP_SOURCE_SCOPE',task_id=routing.engine.TASK))
    joint=saved(tmp_path/'joint61.json',dict(status='PASS_ORIGINAL_ACCOUNT_SOURCE_OWNER_PREFLIGHT',all_source_qualified=True,base_native_count=105,supplement_count=61,event_fingerprints=allfps,removed_exact_original_keys=allrecords,FX_mark_count=272,original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False,source_scope_ref=bootstrap))
    ef=saved(tmp_path/'expected61.json',dict(expected_supplement_count=49,expected_source_set=expected,original_actual_preflight_ref=joint))
    composition=saved(tmp_path/'composition61.json',dict(schema='CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1',status='QUALIFIED_EXACT61_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY',base_native_count=105,supplement_count=61,base_ref=expected['base_ref'],supplements=entries,original_actual_preflight_ref=joint,original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False))
    base_route,_,_=rf.route_fixture.__wrapped__(tmp_path,monkeypatch)
    scope=saved(tmp_path/'source61.json',dict(schema='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1',task_id=routing.engine.TASK,source_only_supplement_count=49,source_completion_count=61,qualified_source_expected_set_ref=ef,qualified_source_composition_ref=composition,joint_owner_source_preflight_ref=joint))
    reader=saved(tmp_path/'reader.json',shim.reader_scope_template(dict(schema='ORIGINAL_DATA_SOURCE_SCOPE',task_id=routing.engine.TASK),data_origin_ref=scope,output_run=base_route['output_run']))
    payload=saved(tmp_path/'qualified272_payload_metadata.json',dict(proof_sha256=fx.proof_sha256,actual_joint61_receipt_ref=joint,FX_mark_count=272,old_count=258,early_count=14))
    fqm=saved(tmp_path/'FX272.json',dict(schema=shim.FX_SCHEMA,task_id=routing.engine.TASK,status='QUALIFIED_KNOWN_PUBLISHED_BOOKS_ONLY',original_fx_convention_ref=inputs.account.FX_CONVENTION_REF,original_availability_ref=inputs.account.FX_AVAILABILITY_REF,old258_book_ref=cad.OLD_FX_REF,early14_book_ref=cad.EARLY_FX_REF,early14_qualification_ref=cad.EARLY_FX_QUAL_REF,old_count=258,early_count=14,combined_count=272,payload_qualification_ref=joint,merged272_payload_ref=payload,canonical_payload_proof_sha256=fx.proof_sha256,available_at_convention='END_OF_CERTIFIED_RELEASE_DATE_AMERICA_NEW_YORK_23_59_59_CONVERTED_TO_UTC',actual_timestamp_authority='UNKNOWN_RETAINED',same_release_date_market_close_mark_allowed=False,global_latest='UNKNOWN',source_only_not_account_coverage=True,revision_vintage='UNKNOWN',FX_account_coverage_qualified=False))
    route=shim.template(base_route,expected_freeze_ref=ef,source_joint_ref=joint,qualified_source_scope_ref=scope,reader_scope_ref=reader,fx_qualification_ref=fqm)
    return SimpleNamespace(route=route,expected=expected,original=original,origin=origin,calendar=calendar,read=read,fx=fx,facts=facts,usd_calls=usd_calls,tmp=tmp_path,bundles=bundles)


def bind(g):
    return shim.bind_components(g.expected,SimpleNamespace(),g.original,g.calendar,pin=lambda ref:routing._pin(shim.canonical(ref)),read=g.read,qualified_fx=g.fx,original_source_kwargs_ref=g.origin)


def test_actual_synthetic_20owner_roundtrip_18USD_twoCAD_nochoice_and272_identity(generated):
    g=generated;desc,native=bind(g);assert len(desc)==20 and len(g.usd_calls)==18 and len(native)==4
    before=[asdict(e) for e in g.original['entitlement_events']]
    combined=dict(g.original,research_account_authority={},foreign_fx_marks=tuple(g.fx.old_marks))
    result=shim.compose_components(combined,g.expected,desc,qualified_fx=g.fx)
    assert len(result['entitlement_events'])==212 and result['unsupported_events']==(g.original['unsupported_events'][-1],)
    assert [asdict(e) for e in g.original['entitlement_events']]==before and len(g.original['unsupported_events'])==62
    assert len(result['foreign_fx_marks'])==272 and all(a is b for a,b in zip(g.fx.old_marks,result['foreign_fx_marks']))
    assert {e.event_fingerprint for e in g.original['entitlement_events']}<={e.event_fingerprint for e in result['entitlement_events']}
    assert shim.validate_entries(g.expected)==dict(current_count=61,owner_count=20,USD_owner_count=18,USD_count=57,CAD_owner_count=2,CAD_count=4)


@pytest.mark.parametrize('kind',['USD_as_CAD','CAD_as_USD','missing_owner','wrong_namespace','fivefield','CAD_resolution','native_fingerprint','CAD_proof','duplicate_FX','changed_FX','conflicting_FX','unqualified_CAD'])
def test_heterogeneous_binder_and_nochoice_guards(generated,kind):
    g=generated
    if kind=='CAD_proof':
        bundle=g.bundles[g.expected['supplements'][16]['bundle_ref']['path']];row=bundle['native_proofs'][0];p=Path(row['native_proof_ref']['path']);v=json.loads(p.read_text());v['proof']['event_fingerprint']='f'*64;row['native_proof_ref']=saved(p,v)
        with pytest.raises(ValueError,match='CLOSED_ORIGINAL'):bind(g)
        return
    desc,_=bind(g);desc=copy.deepcopy(desc);combined=dict(g.original,research_account_authority={},foreign_fx_marks=tuple(g.fx.marks))
    if kind=='USD_as_CAD':desc[0]['binder_kind']='ORIGINAL_CAD_FOREIGN_NATIVE'
    elif kind=='CAD_as_USD':desc[16]['binder_kind']='ORIGINAL_USD_NATIVE_BINDER'
    elif kind=='unqualified_CAD':desc[16]['CAD_native_qualifications']=()
    elif kind=='missing_owner':desc.pop()
    elif kind=='wrong_namespace':desc[18]['original_namespace']='CHANGED'
    elif kind=='fivefield':desc[0]['native']['events']['entitlement_source_binding']['manifest']['removed_exact_original_keys'][0]['source_reference']='CHANGED'
    elif kind=='CAD_resolution':desc[16]['CAD_original_resolution']['proof']['removed_exact_original_keys']=[]
    elif kind=='native_fingerprint':desc[0]['native']['events']['entitlement_events']=()
    elif kind=='duplicate_FX':combined['foreign_fx_marks']+=tuple(g.fx.early_marks)
    elif kind=='changed_FX':combined['foreign_fx_marks']=(replace(g.fx.marks[0],currency_per_usd=1.4),)+tuple(g.fx.marks[1:])
    elif kind=='conflicting_FX':
        with pytest.raises(ValueError,match='AMBIGUOUS'):cad.merge_fx_marks(g.fx.marks,(replace(g.fx.marks[0],currency_per_usd=1.4),))
        return
    with pytest.raises(ValueError):shim.compose_components(combined,g.expected,desc,qualified_fx=g.fx)


def test_large_expected_metadata_uses_perentry_original_scalar_without_relaxing65KiB(generated):
    g=generated;value=dict(expected_source_set=copy.deepcopy(g.expected));
    for item in value['expected_source_set']['supplements']:item['historical_padding']='P'*5000
    ref=saved(g.tmp/'large_expected.json',value);assert Path(ref['path']).stat().st_size>65536
    projected=shim.expected_projection(ref);assert projected==value['expected_source_set']
    value['expected_source_set']['supplements'][0]['historical_padding']='P'*70000;ref=saved(g.tmp/'large_entry.json',value)
    with pytest.raises(ValueError):shim.expected_projection(ref)


@pytest.mark.parametrize('kind',['inherited49','missing_CAD','old_FX_qualification','wrong_272_payload','FX_286','FX_global_latest','FX_claim_account','wrong_reader','wrong_origin','budget_reset','read2026','real_account'])
def test_consumer_metadata_scope_failclosed_before_any_original_reader(generated,kind):
    g=generated;r=copy.deepcopy(g.route)
    if kind=='inherited49':r['current_source_count']=49
    elif kind=='missing_CAD':
        expected=copy.deepcopy(g.expected);expected['supplements'].pop(17);r['expected_freeze_ref']=saved(g.tmp/'missing.json',dict(expected_source_set=expected))
    elif kind in ('old_FX_qualification','wrong_272_payload','FX_286','FX_global_latest','FX_claim_account'):
        value=json.loads(Path(r['fx_qualification_ref']['path']).read_text())
        if kind=='old_FX_qualification':value['schema']='CONSENSUS_FX_RELEASE_DATE_AVAILABILITY_QUALIFICATION_R1'
        elif kind=='wrong_272_payload':value['canonical_payload_proof_sha256']='0'*64
        elif kind=='FX_286':value['combined_count']=286
        elif kind=='FX_global_latest':value['global_latest']='PROVED'
        else:value['FX_account_coverage_qualified']=True
        r['fx_qualification_ref']=saved(g.tmp/'bad_fx.json',value)
    elif kind=='wrong_reader':r['reader_owner_ref']=dict(r['reader_owner_ref'],sha256='0'*64)
    elif kind=='wrong_origin':r['qualified_source_scope_ref']=dict(r['qualified_source_scope_ref'],sha256='0'*64)
    elif kind=='budget_reset':r['original_routing_metadata']['budget']['prior_fit_units']=0
    elif kind=='read2026':r['test2026_read_authorized']=True
    elif kind=='real_account':r['real_account_execution_authorized']=True
    with pytest.raises(ValueError):shim.validate(r,execute=(kind=='real_account'))
    assert not Path(r['original_routing_metadata']['output_run']).exists()


def test_same_proxy_actual_function_globals_dual_validator_worker_and_engineering_entries(generated,monkeypatch):
    g=generated;ns=cad.private_shareholder_namespace(g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint])
    freeze=dict(path=str(Path(g.route['original_routing_metadata']['output_run'])/shim.FREEZE),sha256='a'*64)
    runner,lineage=shim.bind_runner(g.route,freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=lambda *args:(_ for _ in ()).throw(AssertionError('must not execute source payload')))
    cells=dict(zip(runner.evaluate_flow.__code__.co_freevars,(cell.cell_contents for cell in runner.evaluate_flow.__closure__)))
    core=cells['function']
    proxy=core.__globals__['shareholder'];pinputs=core.__globals__['account_inputs']
    assert proxy is pinputs.load_account_inputs.__globals__['account'] is pinputs.metadata_preflight.__globals__['account']
    assert proxy is pinputs._private_original_metadata_preflight.__globals__['account'] is pinputs._private_original_load_account_inputs.__globals__['account']
    assert proxy.validate_task_authority.__globals__['validate_task_authority'] is proxy.validate_task_authority
    assert pinputs._private_original_metadata_preflight.__code__ is inputs.metadata_preflight.__code__
    assert runner._risk_worker is routing.engine._risk_worker and runner._risk_worker.__module__==routing.engine._risk_worker.__module__
    assert pickle.loads(pickle.dumps(runner._risk_worker)) is routing.engine._risk_worker
    assert lineage['engine_routing_anchor_count']==5 and lineage['input_business_AST_restored_exact']
    for call in (lambda:runner.run_all(g.route['original_routing_metadata']['output_run']),lambda:pinputs.metadata_preflight(frozen_contract_ref=freeze,source_scope_ref=g.route['reader_scope_ref']),lambda:pinputs.load_account_inputs({},signal_adv_by_key=None)):
        with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_NOT_AUTHORIZED'):call()
    bad=dict(freeze,path=str(Path(freeze['path']).parent/'OLD_FREEZE.json'))
    with pytest.raises(ValueError,match='EXACT_NEW_FREEZE_PATH'):shim.bind_runner(g.route,bad,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=lambda *a:None)


def test_original_math_and_protected_owners_are_single_authority():
    pins=shim.protected_pins();assert pins['inputs']['sha256']==shim.PROTECTED['inputs']
    assert cad.ca.foreign_claim_value_usd is inputs.existing.ca.foreign_claim_value_usd
    assert cad._r6_fraction_check(.24,1)==.24
    with pytest.raises(ValueError):cad._r6_fraction_check(.25,1)


def test_dual_authority_calls_share_validator_and_new272_ref_without_oldref_relabel(generated,monkeypatch):
    g=generated;old_scope_calls=[]
    monkeypatch.setattr(inputs.account,'_validate_source_completion_scopes',lambda a:None)
    monkeypatch.setattr(inputs.account,'_metadata_ref',lambda ref,**kw:ref)
    def old_scope(authority):
        assert authority['fx_source_availability_qualification_ref']==inputs.account.FX_AVAILABILITY_REF;old_scope_calls.append(True)
    monkeypatch.setattr(inputs.account,'_validate_foreign_cash_scopes',old_scope)
    freeze=saved(g.tmp/'private_freeze_fixture.json',dict(schema=shim.SCHEMA,task_id=routing.engine.TASK))
    proxy=shim.private_shareholder(g.route,g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],freeze_ref=freeze)
    events=(cf.trp_event(),)+tuple(n.source.event for n in g.facts)
    authority=dict(frozen_contract_ref=freeze,source_scope_ref=g.route['reader_scope_ref'],
        account_fx_convention_scope_ref=inputs.account.FX_CONVENTION_REF,
        fx_source_availability_qualification_ref=g.route['fx_qualification_ref'])
    proxy._validate_foreign_cash_scopes(authority)
    assert len(old_scope_calls)==1
    bad=dict(authority,fx_source_availability_qualification_ref=inputs.account.FX_AVAILABILITY_REF)
    with pytest.raises(ValueError,match='EXPLICIT272_FX_REF'):proxy._validate_foreign_cash_scopes(bad)
    with pytest.raises(ValueError,match='EXACT_METADATA_REF'):proxy._metadata_ref(dict(freeze,bytes=12))
    for call in (lambda:proxy.make_task_authority(events),lambda:proxy.run_shareholder_cash_account(None,[],None)):
        with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_NOT_AUTHORIZED'):call()


def test_unknown_global_latest_is_metadata_not_an_unauthorized_research_gate(generated):
    route=copy.deepcopy(generated.route);route['real_account_execution_authorized']=True;route['source_gaps_remaining']=0
    assert route['global_latest_FX']=='UNKNOWN'
    with pytest.raises(ValueError,match='NEW_ACCOUNT_AUTHORIZATION_CONTRACT_REQUIRED'):
        shim.validate(route,execute=True)


@pytest.mark.parametrize('kind',['both_origin_refs','expected_base','composition_joint','scope_joint','scope_expected','missing_composition','bootstrap_missing'])
def test_origin_custody_is_external_pinned_chain_not_matching_self_reports(generated,kind):
    g=generated;r=copy.deepcopy(g.route)
    if kind=='both_origin_refs':
        arbitrary=dict(path=str(g.tmp/'absent_origin.json'),sha256='0'*64)
        r['qualified_source_scope_ref']=arbitrary
        reader=json.loads(Path(r['reader_scope_ref']['path']).read_text());reader['data_origin_scope_ref']=arbitrary
        r['reader_scope_ref']=saved(g.tmp/'arbitrary_reader.json',reader)
    elif kind=='expected_base':
        value=json.loads(Path(r['expected_freeze_ref']['path']).read_text());value['expected_source_set']['base_ref']=saved(g.tmp/'different_base.json',dict(generated_only=True,different=True))
        r['expected_freeze_ref']=saved(g.tmp/'wrong_expected_base.json',value)
        scope=json.loads(Path(r['qualified_source_scope_ref']['path']).read_text());scope['qualified_source_expected_set_ref']=r['expected_freeze_ref']
        r['qualified_source_scope_ref']=saved(g.tmp/'wrong_expected_scope.json',scope)
        reader=json.loads(Path(r['reader_scope_ref']['path']).read_text());reader['data_origin_scope_ref']=r['qualified_source_scope_ref']
        r['reader_scope_ref']=saved(g.tmp/'wrong_expected_reader.json',reader)
    elif kind=='bootstrap_missing':
        joint=json.loads(Path(r['source_joint_ref']['path']).read_text());joint['source_scope_ref']=dict(path=str(g.tmp/'absent_bootstrap.json'),sha256='0'*64)
        # Call the custody check directly so changing the joint digest cannot make unrelated FX refs fail first.
        with pytest.raises((ValueError,FileNotFoundError)):shim._qualified_origin(r,g.expected,joint)
        return
    else:
        scope=json.loads(Path(r['qualified_source_scope_ref']['path']).read_text())
        if kind=='composition_joint':
            value=json.loads(Path(scope['qualified_source_composition_ref']['path']).read_text());value['original_actual_preflight_ref']=r['reader_scope_ref']
            scope['qualified_source_composition_ref']=saved(g.tmp/'wrong_composition.json',value)
        elif kind=='scope_joint':scope['joint_owner_source_preflight_ref']=r['reader_scope_ref']
        elif kind=='scope_expected':scope['qualified_source_expected_set_ref']=r['reader_scope_ref']
        else:scope['qualified_source_composition_ref']=dict(path=str(g.tmp/'absent_composition.json'),sha256='0'*64)
        r['qualified_source_scope_ref']=saved(g.tmp/'bad_origin_scope.json',scope)
        reader=json.loads(Path(r['reader_scope_ref']['path']).read_text());reader['data_origin_scope_ref']=r['qualified_source_scope_ref']
        r['reader_scope_ref']=saved(g.tmp/'matching_bad_reader.json',reader)
    with pytest.raises((ValueError,FileNotFoundError)):shim.validate(r)


def test_all_exported_account_and_fit_entries_guard_before_core_calls(generated,monkeypatch):
    g=generated;calls=[]
    def must_not_run(*args,**kwargs):calls.append(True);raise AssertionError('core executed')
    guarded=shim._guarded_execution(g.route,must_not_run)
    with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_NOT_AUTHORIZED'):guarded()
    freeze=dict(path=str(Path(g.route['original_routing_metadata']['output_run'])/shim.FREEZE),sha256='a'*64)
    runner,_=shim.bind_runner(g.route,freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=must_not_run)
    for name in ('evaluate_flow','freeze_selected_risk','make_policy','run_all','main','freeze_template','published_forecasts','qualified_vectors','unavailable_publication'):
        with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_NOT_AUTHORIZED'):getattr(runner,name)()
    proxy=shim.private_shareholder(g.route,g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],freeze_ref=freeze)
    for name in ('make_task_authority','run_shareholder_cash_account'):
        with pytest.raises(ValueError,match='ACCOUNT_EXECUTION_NOT_AUTHORIZED'):getattr(proxy,name)()
    assert calls==[] and not Path(g.route['original_routing_metadata']['output_run']).exists()


@pytest.fixture
def dynamic_generated(generated,monkeypatch):
    g=generated;expected=copy.deepcopy(g.expected);original=copy.deepcopy(g.original)
    legacy_loader=inputs.existing._load_python;aliases={}
    for index,item in enumerate(expected['supplements'],1):
        alias='_consensus_dynamic_source_'+inputs.existing.digest(dict(owner=shim.canonical(item['native_owner_ref']),bundle=shim.canonical(item['bundle_ref'])))[:24]
        aliases[alias]=item['original_namespace']
    # Real first-source namespaces can be dict metadata, never Python module names.
    expected['supplements'][0]['original_namespace']=dict(schema='ORIGINAL_SOURCE_NAMESPACE',scientific_profile='GENERATED_ONLY')
    extra_records=[]
    for index in range(21,33):
        n=3 if index<=23 else 2
        events=tuple(replace(cf.old_events()[0],event_id=f'DYN_{index}_{j}',old_security_id=f'DYN_SID_{index}_{j}',ticker=f'D{index}_{j}') for j in range(n))
        records=[dict(ticker=e.ticker,effective_date=e.ex_date,reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='generated_original_binding',source_fingerprint=cad.digest([index,j])) for j,e in enumerate(events)]
        native=dict(events=dict(entitlement_events=events,entitlement_security_tickers={e.old_security_id:e.ticker for e in events},entitlement_source_binding=dict(source_fingerprint=cad.digest(index),manifest=dict(removed_exact_original_keys=records)),research_account_authority={}))
        br=saved(g.tmp/f'dynamic_bundle{index}.json',dict(generated_only=True));g.bundles[br['path']]=dict(generated_USD_native=native)
        item=dict(bundle_ref=br,native_owner_ref=routing.file_ref(cad.__file__),original_namespace=f'USD{index}',event_keys=records,event_fingerprints=[e.event_fingerprint for e in events])
        expected['supplements'].append(item);extra_records.extend(records)
        alias='_consensus_dynamic_source_'+inputs.existing.digest(dict(owner=shim.canonical(item['native_owner_ref']),bundle=shim.canonical(item['bundle_ref'])))[:24];aliases[alias]=item['original_namespace']
    def loader(ref,name):
        assert isinstance(name,str) and name in aliases
        return legacy_loader(ref,aliases[name])
    monkeypatch.setattr(inputs.existing,'_load_python',loader)
    original['unsupported_events']=tuple(list(original['unsupported_events'][:-1])+extra_records+[original['unsupported_events'][-1]])
    roles=[dict(original_namespace=copy.deepcopy(item['original_namespace']),native_owner_ref=shim.canonical(item['native_owner_ref']),bundle_ref=shim.canonical(item['bundle_ref']),binder_kind='ORIGINAL_CAD_FOREIGN_NATIVE' if i in (17,18) else 'ORIGINAL_USD_NATIVE_BINDER',event_count=len(item['event_keys'])) for i,item in enumerate(expected['supplements'],1)]
    g.dynamic_expected=expected;g.dynamic_original=original;g.dynamic_roles=roles
    return g


def save_dynamic_sources(g,expected,roles,*,authorized=False):
    source_fields=dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',raw_price_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',strict_PIT=False,sources=dict(original_cash_kwargs=g.origin))
    count=sum(len(item['event_keys']) for item in expected['supplements'])
    joint=saved(g.tmp/'dynamic_joint.json',dict(status='PASS_ORIGINAL_ACCOUNT_SOURCE_OWNER_PREFLIGHT',all_source_qualified=True,base_native_count=105,supplement_count=count,event_fingerprints=[fp for item in expected['supplements'] for fp in item['event_fingerprints']],removed_exact_original_keys=[k for item in expected['supplements'] for k in item['event_keys']],FX_mark_count=272,original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False,source_scope_ref=g.route['qualified_source_scope_ref']))
    ef=saved(g.tmp/'dynamic_expected.json',dict(expected_source_set=expected,original_actual_preflight_ref=joint))
    composition=saved(g.tmp/'dynamic_composition.json',dict(schema='CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1',status=f'QUALIFIED_EXACT{count}_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY',base_native_count=105,supplement_count=count,base_ref=expected['base_ref'],supplements=expected['supplements'],original_actual_preflight_ref=joint,original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False))
    scope=saved(g.tmp/'dynamic_scope.json',dict(schema='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1',task_id=routing.engine.TASK,source_completion_count=count,qualified_source_expected_set_ref=ef,qualified_source_composition_ref=composition,joint_owner_source_preflight_ref=joint,**source_fields))
    base_route=copy.deepcopy(g.route['original_routing_metadata'])
    reader=saved(g.tmp/'dynamic_reader.json',shim.reader_scope_template(dict(schema='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1',task_id=routing.engine.TASK,numeric_read_authorization=inputs.GATE,**source_fields),data_origin_ref=scope,output_run=base_route['output_run'],dynamic=True,execute=authorized))
    # Keep the original61 FX payload origin, even while current SOURCE count changes.
    fx=json.loads(Path(g.route['fx_qualification_ref']['path']).read_text());fx['schema']=shim.CONTINUATION_FX_SCHEMA
    fxref=saved(g.tmp/'dynamic_fx.json',fx)
    route=shim.template(base_route,expected_freeze_ref=ef,source_joint_ref=joint,qualified_source_scope_ref=scope,reader_scope_ref=reader,fx_qualification_ref=fxref,source_roles=roles)
    return route


def test_dynamic88_explicit_roles_dict_namespace_and_original272_fx_origin(dynamic_generated):
    g=dynamic_generated;route=save_dynamic_sources(g,g.dynamic_expected,g.dynamic_roles)
    run,expected=shim.validate(route);counts=shim.validate_entries(expected,source_roles=g.dynamic_roles)
    assert counts==dict(current_count=88,owner_count=32,USD_owner_count=30,USD_count=84,CAD_owner_count=2,CAD_count=4)
    assert route['source_gaps_remaining']==106 and not run.exists()
    desc,facts=shim.bind_components(expected,SimpleNamespace(),g.dynamic_original,g.calendar,pin=lambda ref:routing._pin(shim.canonical(ref)),read=g.read,qualified_fx=g.fx,original_source_kwargs_ref=g.origin,source_roles=g.dynamic_roles)
    result=shim.compose_components(dict(g.dynamic_original,research_account_authority={},foreign_fx_marks=g.fx.marks),expected,desc,qualified_fx=g.fx,source_roles=g.dynamic_roles)
    assert len(facts)==4 and result['unsupported_events']==(g.dynamic_original['unsupported_events'][-1],)
    assert desc[0]['original_namespace']==expected['supplements'][0]['original_namespace'] and isinstance(desc[0]['original_namespace'],dict)
    assert all(a is b for a,b in zip(g.fx.marks,result['foreign_fx_marks']))
    moved=expected['supplements'][::-1];roles=g.dynamic_roles[::-1]
    assert shim.validate_entries(dict(base_ref=expected['base_ref'],supplements=moved),source_roles=roles)==counts


def shared_namespace_packets(g):
    expected=copy.deepcopy(g.dynamic_expected);roles=copy.deepcopy(g.dynamic_roles)
    namespace=dict(schema='ORIGINAL_VENDOR_NAMESPACE',source_profile='SAME_OWNER_SPLIT_PACKETS')
    for item,role in zip(expected['supplements'][-2:],roles[-2:]):
        item['original_namespace']=copy.deepcopy(namespace);role['original_namespace']=copy.deepcopy(namespace)
    return expected,roles


def test_dynamic_same_owner_distinct_bundles_shared_original_namespace_roundtrip(dynamic_generated):
    g=dynamic_generated;expected,roles=shared_namespace_packets(g)
    ordered=shim._entry_roles(expected,roles[::-1])
    assert ordered==roles and shim.validate_entries(expected,source_roles=roles)['current_count']==88
    descendants,facts=shim.bind_components(expected,SimpleNamespace(),g.dynamic_original,g.calendar,pin=lambda ref:routing._pin(shim.canonical(ref)),read=g.read,qualified_fx=g.fx,original_source_kwargs_ref=g.origin,source_roles=roles[::-1])
    assert descendants[-2]['original_namespace']==descendants[-1]['original_namespace']==expected['supplements'][-1]['original_namespace']
    assert descendants[-2]['bundle_ref']!=descendants[-1]['bundle_ref']
    result=shim.compose_components(dict(g.dynamic_original,research_account_authority={},foreign_fx_marks=g.fx.marks),expected,descendants,qualified_fx=g.fx,source_roles=roles[::-1])
    assert len(facts)==4 and result['unsupported_events']==(g.dynamic_original['unsupported_events'][-1],)
    assert all(a is b for a,b in zip(g.fx.marks,result['foreign_fx_marks']))


def test_dynamic_distinct_expected_owners_shared_namespace_match_exact_roles(dynamic_generated):
    g=dynamic_generated;expected,roles=shared_namespace_packets(g)
    expected['supplements'][-1]['native_owner_ref']=saved(g.tmp/'other_original_owner.py',dict(generated_only=True))
    roles[-1]['native_owner_ref']=shim.canonical(expected['supplements'][-1]['native_owner_ref'])
    assert shim._entry_roles(expected,roles[::-1])==roles
    assert shim.validate_entries(expected,source_roles=roles)['current_count']==88


@pytest.mark.parametrize('kind,error',[('role_only_wrong_owner','DYNAMIC_SOURCE_ROLE_OWNER_OR_BUNDLE_CHANGED'),('duplicate_bundle','DYNAMIC_SOURCE_ROLE_OWNER_BUNDLE_DUPLICATE'),('duplicate_owner_bundle_other_namespace','DYNAMIC_SOURCE_ROLE_OWNER_BUNDLE_DUPLICATE'),('overlapping_key','PRIVATE61_EXACT_SOURCE_KEYS_AND_FINGERPRINTS_REQUIRED'),('overlapping_fingerprint','PRIVATE61_EXACT_SOURCE_KEYS_AND_FINGERPRINTS_REQUIRED')])
def test_dynamic_shared_namespace_packet_conflicts_reject_before_binder(dynamic_generated,monkeypatch,kind,error):
    g=dynamic_generated;expected,roles=shared_namespace_packets(g);last=expected['supplements'][-1];role=roles[-1];previous=expected['supplements'][-2]
    if kind=='role_only_wrong_owner':
        role['native_owner_ref']=saved(g.tmp/'unmatched_role_owner.py',dict(generated_only=True))
    elif kind in ('duplicate_bundle','duplicate_owner_bundle_other_namespace'):
        last['bundle_ref']=copy.deepcopy(previous['bundle_ref']);role['bundle_ref']=shim.canonical(last['bundle_ref'])
        if kind=='duplicate_owner_bundle_other_namespace':last['original_namespace']=role['original_namespace']='OTHER_NAMESPACE_SAME_PACKET'
    elif kind=='overlapping_key':last['event_keys'][0]=copy.deepcopy(previous['event_keys'][0])
    else:last['event_fingerprints'][0]=previous['event_fingerprints'][0]
    calls=[]
    def no_binder(*args,**kwargs):calls.append(True);raise AssertionError('source binder called')
    monkeypatch.setattr(inputs.existing,'_load_python',no_binder)
    with pytest.raises(ValueError,match=error):shim.bind_components(expected,SimpleNamespace(),g.dynamic_original,g.calendar,pin=lambda ref:routing._pin(shim.canonical(ref)),read=g.read,qualified_fx=g.fx,original_source_kwargs_ref=g.origin,source_roles=roles)
    assert calls==[]


@pytest.mark.parametrize('kind',['missing_role','role_bundle','role_namespace','CAD_as_USD','future_effective','fake_zero_gaps','count','unsupported_vendor_api'])
def test_dynamic_roles_counts_and_boundary_fail_before_account(dynamic_generated,kind):
    g=dynamic_generated;expected=copy.deepcopy(g.dynamic_expected);roles=copy.deepcopy(g.dynamic_roles)
    if kind=='missing_role':roles.pop()
    elif kind=='role_bundle':roles[0]['bundle_ref']['sha256']='0'*64
    elif kind=='role_namespace':roles[1]['original_namespace']=roles[0]['original_namespace']
    elif kind=='CAD_as_USD':roles[16]['binder_kind']='ORIGINAL_USD_NATIVE_BINDER'
    elif kind=='future_effective':expected['supplements'][0]['event_keys'][0]['effective_date']='2026-01-01'
    elif kind=='unsupported_vendor_api':
        item=expected['supplements'][0];roles[0]['binder_kind']='MASSIVE_VENDOR_USD_NATIVE_BINDER'
        item['key_to_component_fingerprints']=[dict(original_record=k,component_fingerprints=[fp]) for k,fp in zip(item['event_keys'],item['event_fingerprints'])]
        with pytest.raises(ValueError,match='VENDOR_ACTUAL_OWNER_API'):
            shim.bind_components(expected,SimpleNamespace(),g.dynamic_original,g.calendar,pin=lambda ref:routing._pin(shim.canonical(ref)),read=g.read,qualified_fx=g.fx,original_source_kwargs_ref=g.origin,source_roles=roles)
        return
    else:
        route=save_dynamic_sources(g,expected,roles)
        if kind=='fake_zero_gaps':route['source_gaps_remaining']=0
        else:route['current_source_count']=194
        with pytest.raises(ValueError):shim.validate(route)
        return
    with pytest.raises(ValueError):shim.validate_entries(expected,source_roles=roles)


def test_dynamic_vendor_components_preserve_each_native_fingerprint_and_original_key(dynamic_generated):
    g=dynamic_generated;expected=copy.deepcopy(g.dynamic_expected);roles=copy.deepcopy(g.dynamic_roles)
    item=expected['supplements'][0];roles[0]['binder_kind']='MASSIVE_VENDOR_USD_NATIVE_BINDER'
    second='f'*64;item['event_fingerprints'].append(second)
    item['key_to_component_fingerprints']=[dict(original_record=k,component_fingerprints=[fp]) for k,fp in zip(item['event_keys'],item['event_fingerprints'])]
    item['key_to_component_fingerprints'][0]['component_fingerprints'].append(second)
    counts=shim.validate_entries(expected,source_roles=roles)
    assert counts['current_count']==88 and sum(len(x['event_fingerprints']) for x in expected['supplements'])==89
    item['key_to_component_fingerprints'][0]['component_fingerprints'].pop()
    with pytest.raises(ValueError,match='COMPONENT_MAP_OR_FINGERPRINT'):shim.validate_entries(expected,source_roles=roles)


@pytest.fixture
def dynamic_authorized(dynamic_generated,monkeypatch):
    g=dynamic_generated;expected=copy.deepcopy(g.dynamic_expected);roles=copy.deepcopy(g.dynamic_roles)
    # A generated original API owner adds106 distinct source keys; no vendor cash is fabricated.
    index=33;events=tuple(replace(cf.old_events()[0],event_id=f'DYN_{index}_{j}',old_security_id=f'DYN_SID_{index}_{j}',ticker=f'D{index}_{j}') for j in range(106))
    records=[dict(ticker=e.ticker,effective_date=e.ex_date,reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='generated_original_binding',source_fingerprint=cad.digest([index,j])) for j,e in enumerate(events)]
    br=saved(g.tmp/'generated_owner33.json',dict(generated_only=True))
    item=dict(bundle_ref=br,native_owner_ref=routing.file_ref(cad.__file__),original_namespace='SYNTHETIC_ONLY_OWNER33',event_keys=records,event_fingerprints=[e.event_fingerprint for e in events])
    expected['supplements'].append(item);roles.append(dict(original_namespace=item['original_namespace'],native_owner_ref=shim.canonical(item['native_owner_ref']),bundle_ref=br,binder_kind='ORIGINAL_USD_NATIVE_BINDER',event_count=106))
    # The synthetic managed metadata is created only in pytest's external task cache.
    run=g.tmp/routing.engine.TASK/'SYNTHETIC_NEW_RUN';run.mkdir(parents=True)
    monkeypatch.setattr(routing,'assert_safe_output_path',lambda path,**kwargs: path if Path(path).is_relative_to(g.tmp) else (_ for _ in ()).throw(ValueError('SYNTHETIC_TEMP_ROOT_ONLY')))
    g.route['original_routing_metadata']['output_run']=str(run)
    route=save_dynamic_sources(g,expected,roles,authorized=True);route.update(status=shim.AUTHORIZED,real_account_execution_authorized=True)
    spec=saved(g.tmp/'synthetic_spec.json',dict(generated_only=True));monkeypatch.setattr(shim,'AUTHORIZED_SPEC_REF',spec)
    scope=dict(source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',history_vintage='UNKNOWN',development_end_exclusive='2026-01-01',source_gaps_must_be_qualified_before_account_execution=True,reuse_R1_features_and_R2_fusion=True,prior_fit_units=1291,max_fit_units=10000,account_initial_cash_usd=3000,account_type='CASH',fractional=True,new_managed_account_output_required=True,old_frozen_outputs_preserved=True)
    restrictions={k:False for k in ('test2026_read_authorized','FAST3_Confirmation_access','broker_action_allowed','production_promotion_allowed','provider_upgrade_or_purchase_allowed','future_adjusted_cash_or_price_as_actual_share_allowed','source_qualification_or_economic_acceptance_granted')}
    human=saved(g.tmp/'synthetic_human_authorization.json',dict(schema=shim.AUTHORIZATION_SCHEMA,task_id=routing.engine.TASK,authorization_source='DIRECT_HUMAN_MESSAGES_IN_THIS_CHAT',recorded_by='root',human_user_authorized=True,account_replay_authorized=True,pre2026_risk_fitting_authorized=True,authorized_spec_ref=spec,scope=scope,restrictions=restrictions));monkeypatch.setattr(shim,'HUMAN_AUTHORIZATION_REF',human)
    gaps=saved(g.tmp/'synthetic_original194_gaps.json',dict(gaps=[k for x in expected['supplements'] for k in x['event_keys']]));monkeypatch.setattr(shim,'ORIGINAL_GAPS_REF',gaps)
    managed=dict(strategy_id=routing.engine.TASK,run_id=run.name,research_start_date='2023-01-01',research_end_date='2025-12-31',input_data_copied=False,duplicate_market_data_count=0,broker_action_allowed=False,official_adoption_allowed=False,research_only=True,execution_assumption='RESEARCH_ONLY')
    rc=saved(run/'run_config.json',managed);im=saved(run/'input_manifest.json',managed)
    contract=shim.execution_contract_template(route,research_id='SYNTHETIC_CONTINUATION_R3',managed_run_config_ref=rc,managed_input_manifest_ref=im)
    route['execution_contract_ref']=saved(g.tmp/'dynamic_execution_contract.json',contract)
    freeze=saved(run/shim.CONTINUATION_FREEZE,route)
    return SimpleNamespace(g=g,route=route,contract=contract,run=run,freeze=freeze)


def test_dynamic_formal_execution_contract_passes_only_complete_synthetic_source_and_saved_freeze(dynamic_authorized):
    a=dynamic_authorized;assert shim.validate(a.route,execute=True)[0]==a.run
    calls=[]
    def core(run):calls.append(run);return 'SYNTHETIC_CORE_ONLY'
    wrapped=shim._guarded_execution(a.route,core)
    assert wrapped(a.run)=='SYNTHETIC_CORE_ONLY' and calls==[a.run]
    with pytest.raises(ValueError,match='WRONG_OUTPUT_RUN'):wrapped(a.run.parent/'WRONG')
    assert calls==[a.run]
    assert not (a.run/'FIT_LOG.jsonl').exists() and not (a.run/'evaluation').exists()


@pytest.mark.parametrize('kind',['no_contract','budget','future','old_state','old_cache','managed_other_run','managed_trade','human_ref','source_ref','old_fx_relabel','saved_freeze','missing_original_key'])
def test_dynamic_formal_execution_contract_rejects_boolean_bypass_and_lineage_drift(dynamic_authorized,kind):
    a=dynamic_authorized;r=copy.deepcopy(a.route);c=copy.deepcopy(a.contract)
    if kind=='no_contract':r['execution_contract_ref']=None
    elif kind=='budget':c['budget']['prior_fit_units']=0
    elif kind=='future':c['scope_end_exclusive']='2027-01-01'
    elif kind=='old_state':c['old_account_state_reused']=True
    elif kind=='old_cache':c['old_risk_cache_reused']=True
    elif kind=='managed_other_run':c['managed_run_config_ref']=c['managed_input_manifest_ref']
    elif kind=='managed_trade':
        m=json.loads(Path(c['managed_run_config_ref']['path']).read_text());m['broker_action_allowed']=True;c['managed_run_config_ref']=saved(a.run/'run_config.json',m)
    elif kind=='human_ref':c['human_authorization_ref']=c['authorized_spec_ref']
    elif kind=='source_ref':c['source_joint_ref']=c['reader_scope_ref']
    elif kind=='old_fx_relabel':
        fx=json.loads(Path(r['fx_qualification_ref']['path']).read_text());fx['payload_qualification_ref']=r['source_joint_ref'];r['fx_qualification_ref']=saved(a.g.tmp/'relabeled_fx.json',fx)
    elif kind=='saved_freeze':saved(a.run/shim.CONTINUATION_FREEZE,dict(r,global_latest_FX='FALSIFIED'))
    else:
        gaps=json.loads(Path(shim.ORIGINAL_GAPS_REF['path']).read_text());gaps['gaps'][0]['source_fingerprint']='0'*64;saved(Path(shim.ORIGINAL_GAPS_REF['path']),gaps)
    if kind not in ('no_contract','old_fx_relabel','saved_freeze','missing_original_key'):
        r['execution_contract_ref']=saved(a.g.tmp/'bad_execution_contract.json',c);saved(a.run/shim.CONTINUATION_FREEZE,r)
    with pytest.raises(ValueError):shim.validate(r,execute=True)
    assert not (a.run/'FIT_LOG.jsonl').exists() and not (a.run/'evaluation').exists()


def test_dynamic_direct_input_entries_require_new_freeze_and_reader_before_core_read(dynamic_authorized):
    a=dynamic_authorized;calls=[]
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    connector=shim.source_connector(expected,qualified_fx=a.g.fx,pin=lambda *args:None,read=lambda *args:(_ for _ in ()).throw(AssertionError('actual source read')),original_source_kwargs_ref=a.g.origin,source_roles=a.route['source_roles'])
    source_inputs=shim.private_inputs(a.route,SimpleNamespace(),connector)
    ns=source_inputs.metadata_preflight.__globals__
    ns['_private_original_metadata_preflight']=lambda **kwargs:(calls.append('metadata'),'SYNTHETIC_METADATA')[1]
    ns['_private_original_load_account_inputs']=lambda *args,**kwargs:(calls.append('numeric'),'SYNTHETIC_NUMERIC')[1]
    for ref in (a.route['original_routing_metadata']['frozen_refs']['account_freeze'],dict(a.freeze,sha256='0'*64)):
        with pytest.raises(ValueError,match='INPUT_EXACT_NEW_FREEZE_AND_READER'):
            source_inputs.metadata_preflight(frozen_contract_ref=ref,source_scope_ref=a.route['reader_scope_ref'])
    for scope in (a.route['qualified_source_scope_ref'],dict(a.route['reader_scope_ref'],sha256='0'*64)):
        with pytest.raises(ValueError,match='INPUT_EXACT_NEW_FREEZE_AND_READER'):
            source_inputs.load_account_inputs(dict(frozen_contract_ref=a.freeze,source_scope_ref=scope),signal_adv_by_key=None)
    assert calls==[]
    assert source_inputs.metadata_preflight(frozen_contract_ref=a.freeze,source_scope_ref=a.route['reader_scope_ref'])=='SYNTHETIC_METADATA'
    assert source_inputs.load_account_inputs(dict(frozen_contract_ref=a.freeze,source_scope_ref=a.route['reader_scope_ref']),signal_adv_by_key=None)=='SYNTHETIC_NUMERIC'
    assert calls==['metadata','numeric'] and not (a.run/'FIT_LOG.jsonl').exists()


def test_dynamic_runner_rejects_old_or_arbitrary_connector_before_source_read(dynamic_authorized):
    a=dynamic_authorized;g=a.g;calls=[]
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    def read(*args):calls.append(True);raise AssertionError('source read before contract')
    old=shim.source_connector(g.expected,qualified_fx=g.fx,pin=lambda *args:None,read=read,original_source_kwargs_ref=g.origin)
    correct=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=read,original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    wrong_roles=copy.deepcopy(a.route['source_roles']);wrong_roles[0]['original_namespace']=dict(changed=True)
    # Mutation of an accepted connector's closed metadata must also fail.
    mismatched=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=read,original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    cells=dict(zip(mismatched.__code__.co_freevars,(c.cell_contents for c in mismatched.__closure__)));cells['source_roles'][0]['original_namespace']=dict(changed=True)
    for connector in (old,lambda *args:None,mismatched):
        with pytest.raises(ValueError,match='SOURCE_CONNECTOR'):
            shim.bind_runner(a.route,a.freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=connector)
    runner,_=shim.bind_runner(a.route,a.freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=correct)
    assert runner._risk_worker is routing.engine._risk_worker and calls==[]


@pytest.mark.parametrize('field',['signal_quote_domain_ref','quote_classification_scope_proof','legacy_source_transport','research_id'])
def test_dynamic_reader_cannot_change_approved_input_provenance_with_matching_self_refs(dynamic_authorized,field):
    a=dynamic_authorized;r=copy.deepcopy(a.route);c=copy.deepcopy(a.contract)
    reader=json.loads(Path(r['reader_scope_ref']['path']).read_text());reader[field]={'generated_different_source':True}
    r['reader_scope_ref']=saved(a.g.tmp/f'changed_reader_{field}.json',reader)
    c['reader_scope_ref']=r['reader_scope_ref'];r['execution_contract_ref']=saved(a.g.tmp/f'changed_execution_{field}.json',c)
    saved(a.run/shim.CONTINUATION_FREEZE,r)
    with pytest.raises(ValueError,match='APPROVED_SOURCE_READER_ORIGIN_FIELDS_CHANGED'):shim.validate(r,execute=True)
    assert not (a.run/'FIT_LOG.jsonl').exists()


def test_dynamic_engine_freeze_arguments_and_selected_state_are_new_run_bound(dynamic_authorized):
    a=dynamic_authorized;calls=[]
    def core(run,freeze_ref,selected=None):calls.append(True);return 'SYNTHETIC_CORE'
    guarded=shim._guarded_execution(a.route,core)
    for ref in (a.route['original_routing_metadata']['frozen_refs']['account_freeze'],dict(a.freeze,sha256='0'*64)):
        with pytest.raises(ValueError,match='NEW_AUTHORITY_FREEZE_AND_READER'):guarded(a.run,ref)
    old=dict(receipt_path=a.route['original_routing_metadata']['frozen_refs']['account_freeze']['path'],artifacts=dict(state=a.route['reader_scope_ref']))
    with pytest.raises(ValueError,match='OLD_SELECTED_ACCOUNT_STATE'):guarded(a.run,a.freeze,old)
    assert calls==[]
    assert guarded(a.run,a.freeze)=='SYNTHETIC_CORE' and calls==[True]


def test_dynamic_direct_input_factory_and_entry_reject_unbound_or_drifted_connector(dynamic_authorized):
    a=dynamic_authorized;g=a.g;calls=[]
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    def read(*args):calls.append('read');raise AssertionError('source read')
    old=shim.source_connector(g.expected,qualified_fx=g.fx,pin=lambda *args:None,read=read,original_source_kwargs_ref=g.origin)
    for connector in (old,lambda *args:None):
        with pytest.raises(ValueError,match='SOURCE_CONNECTOR'):shim.private_inputs(a.route,SimpleNamespace(),connector)
    correct=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=read,original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    source_inputs=shim.private_inputs(a.route,SimpleNamespace(),correct)
    source_inputs.metadata_preflight.__globals__['_private_original_metadata_preflight']=lambda **kwargs:calls.append('core')
    # A metadata closure drift after factory binding still cannot reach I's core.
    cells=dict(zip(correct.__code__.co_freevars,(c.cell_contents for c in correct.__closure__)));cells['source_roles'][0]['original_namespace']=dict(changed=True)
    with pytest.raises(ValueError,match='SOURCE_CONNECTOR'):
        source_inputs.metadata_preflight(frozen_contract_ref=a.freeze,source_scope_ref=a.route['reader_scope_ref'])
    assert calls==[]


def test_dynamic_risk_cache_first_empty_then_same_instance_current_run_recovery(dynamic_authorized):
    a=dynamic_authorized;calls=[];context={}
    def core(run,cache):calls.append(cache);return 'SYNTHETIC_CORE'
    first=shim._guarded_execution(a.route,core,cache_context=context)
    second=shim._guarded_execution(a.route,core,cache_context=context)
    with pytest.raises(ValueError,match='INITIAL_OLD_RISK_CACHE'):first(a.run,dict(old_bundle=True))
    assert calls==[] and context=={}
    cache={};assert first(a.run,cache)=='SYNTHETIC_CORE'
    # Original current-run receipt recovery populates this already-owned cache.
    cache['synthetic_current_run_hashed_receipt_bundle']=True
    assert second(a.run,cache)=='SYNTHETIC_CORE'
    for replacement in ({},dict(old_bundle=True)):
        with pytest.raises(ValueError,match='SHARED_RISK_CACHE_INSTANCE'):second(a.run,replacement)
    assert len(calls)==2 and calls[0] is calls[1] is cache
    assert not (a.run/'FIT_LOG.jsonl').exists()


@pytest.fixture
def partition_authorized(dynamic_authorized,monkeypatch):
    a=dynamic_authorized;g=a.g
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles']);roles=copy.deepcopy(a.route['source_roles'])
    retained=copy.deepcopy(expected['supplements'][-1]['event_keys'][-2:])
    expected['supplements'][-1]['event_keys']=expected['supplements'][-1]['event_keys'][:-2]
    expected['supplements'][-1]['event_fingerprints']=expected['supplements'][-1]['event_fingerprints'][:-2];roles[-1]['event_count']-=2
    route=save_dynamic_sources(g,expected,roles,authorized=True);route.update(status=shim.AUTHORIZED,real_account_execution_authorized=True)
    facts={name:saved(g.tmp/f'synthetic_retained_fact_{name}.json',dict(generated_source_fact=True,native_qualified=False)) for name in ('HDB','PCG')}
    intent=dict(schema='CONSENSUS_PRE2026_RETAINED_UNSUPPORTED_ACCOUNT_SCOPE_R1',status='ROOT_EXECUTION_SCOPE_RECORDED_NOT_DATA_OR_ECONOMIC_PASS',task_id=routing.engine.TASK,research_id='SYNTHETIC_CONTINUATION_R3',output_run=str(a.run),recorded_by='root',authorization_basis='EXISTING_HUMAN_TASK_SCOPE_INTERPRETED_BY_ROOT',human_authorization_ref=shim.HUMAN_AUTHORIZATION_REF,authorized_spec_ref=shim.AUTHORIZED_SPEC_REF,no_new_explicit_item_by_item_user_approval_claimed=True,decision_disclosed_to_user_before_outcome_read=True,old_all194_native_path_preserved=True,old_freezes_unchanged=True,original_gaps_ref=shim.ORIGINAL_GAPS_REF,retained_unsupported_keys=retained,sourcefact_refs=facts,native_count_required=192,source_review_count_required=194,native_gap_count_required=2,source_review_gap_count_required=0,economic_PASS=False,scope_start='2023-01-01',scope_end_exclusive='2026-01-01',source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',history_vintage='UNKNOWN',strict_PIT_certified=False,test2026_read_authorized=False,real_trades_authorized=False,future_payment_outcomes_as_training_input=False,cash_date_or_amount_synthesis_allowed=False,retained_event_exclusion_from_pool_allowed=False,retained_events_remain_original_unsupported=True,unknown_values_are_not_zero=True,actual_affected_account_candidate_must_be_NOT_TESTABLE=True,unheld_is_not_preassumed=True,existing_account_unsupported_failclosed_unchanged=True,candidate_families_risk_cost_selection_units_unchanged=True,original_pool_and_quote_masks_unchanged=True,prior_fit_units=1291,max_fit_units=10000,protected_owner_refs=shim.protected_pins())
    intention=saved(g.tmp/'partition_intention.json',intent);monkeypatch.setattr(shim,'PARTITION_SCOPE_REF',intention)
    final=dict(intent,status=shim.PARTITION_STATUS,intention_scope_ref=intention,native_expected_ref=route['expected_freeze_ref'],source_joint_ref=route['source_joint_ref'])
    finalref=saved(g.tmp/'partition_final_scope.json',final)
    partition=dict(schema=shim.PARTITION_SCHEMA,status=shim.PARTITION_STATUS,task_id=routing.engine.TASK,research_id=final['research_id'],root_scope_ref=finalref,original_gaps_ref=shim.ORIGINAL_GAPS_REF,native_expected_ref=route['expected_freeze_ref'],source_joint_ref=route['source_joint_ref'],native_count=192,original_key_count=194,native_gap_count=2,source_review_gaps=0,retained_unsupported_keys=retained,sourcefact_refs=facts,economic_PASS=False,test2026_read_authorized=False)
    route.update(source_partition_ref=saved(g.tmp/'partition.json',partition),source_review_gaps=0)
    contract=shim.execution_contract_template(route,research_id=final['research_id'],managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    route['execution_contract_ref']=saved(g.tmp/'partition_execution.json',contract)
    freeze=saved(a.run/shim.PARTITION_FREEZE,route)
    return SimpleNamespace(a=a,route=route,partition=partition,expected=expected,retained=retained,contract=contract,freeze=freeze)


def test_partition_optional_only_actual192_reviewed194_original_strict_default(partition_authorized):
    p=partition_authorized
    assert shim.validate(p.route,execute=True)[0]==p.a.run
    assert p.route['current_source_count']==192 and p.route['source_gaps_remaining']==2 and p.route['source_review_gaps']==0
    assert Path(p.freeze['path']).name==shim.PARTITION_FREEZE and Path(p.a.freeze['path']).name==shim.CONTINUATION_FREEZE
    strict=copy.deepcopy(p.route);strict.pop('source_partition_ref');strict.pop('source_review_gaps')
    with pytest.raises(ValueError,match='SOURCE_GAPS_BLOCK_ACCOUNT'):shim.validate(strict,execute=True)
    assert not (p.a.run/'FIT_LOG.jsonl').exists()


@pytest.mark.parametrize('kind',['missing_key','overlap','foreign_key','fake_native_fp','false_review_zero','economic_pass','future_key','wrong_joint','root_self_approval'])
def test_partition_failclosed_complete_disjoint_original_keys_and_root_scope(partition_authorized,kind):
    p=partition_authorized;r=copy.deepcopy(p.route);value=copy.deepcopy(p.partition)
    if kind=='missing_key':value['retained_unsupported_keys'].pop()
    elif kind=='overlap':value['retained_unsupported_keys'][0]=p.expected['supplements'][0]['event_keys'][0]
    elif kind=='foreign_key':value['retained_unsupported_keys'][0]['source_fingerprint']='0'*64
    elif kind=='fake_native_fp':value['retained_unsupported_keys'][0]['event_fingerprint']='0'*64
    elif kind=='false_review_zero':value['source_review_gaps']=2
    elif kind=='economic_pass':value['economic_PASS']=True
    elif kind=='future_key':value['retained_unsupported_keys'][0]['effective_date']='2026-01-01'
    elif kind=='wrong_joint':value['source_joint_ref']=r['reader_scope_ref']
    else:
        scope=json.loads(Path(value['root_scope_ref']['path']).read_text());scope['no_new_explicit_item_by_item_user_approval_claimed']=False;value['root_scope_ref']=saved(p.a.g.tmp/'fake_user_approval_scope.json',scope)
    r['source_partition_ref']=saved(p.a.g.tmp/'bad_partition.json',value)
    with pytest.raises(ValueError):shim.validate(r)


def test_partition_retained_unsupported_no_deletion_no_native_and_direct_I_guard(partition_authorized):
    p=partition_authorized;before=dict(unsupported_events=copy.deepcopy(p.retained),entitlement_events=())
    after=copy.deepcopy(before);assert shim._retain_partition_unsupported(before,after,p.retained) is after
    deleted=dict(after,unsupported_events=after['unsupported_events'][:1])
    with pytest.raises(ValueError,match='UNSUPPORTED_CHANGED_OR_REMOVED'):shim._retain_partition_unsupported(before,deleted,p.retained)
    n=p.retained[0];e=replace(cf.old_events()[0],ticker=n['ticker'],ex_date=n['effective_date'])
    with pytest.raises(ValueError,match='RETAINED_UNSUPPORTED_HAS_NATIVE_EVENT'):shim._retain_partition_unsupported(before,dict(after,entitlement_events=(e,)),p.retained)
    calls=[];g=p.a.g
    connector=shim.source_connector(p.expected,qualified_fx=g.fx,pin=lambda *args:None,read=lambda *args:(_ for _ in ()).throw(AssertionError('real source read')),original_source_kwargs_ref=g.origin,source_roles=p.route['source_roles'],source_partition_ref=p.route['source_partition_ref'])
    source_inputs=shim.private_inputs(p.route,SimpleNamespace(),connector)
    ns=source_inputs.metadata_preflight.__globals__;ns['_private_original_metadata_preflight']=lambda **kw:(calls.append('metadata'),'SYNTHETIC_METADATA')[1]
    assert source_inputs.metadata_preflight(frozen_contract_ref=p.freeze,source_scope_ref=p.route['reader_scope_ref'])=='SYNTHETIC_METADATA'
    assert calls==['metadata'] and not (p.a.run/'FIT_LOG.jsonl').exists()


def test_exact_old_risk_code_source_private_factory_pin_real_samebytes_no_math_or_read_change():
    physical=shim._risk_code_transport(shim.RISK_CODE_TRANSPORT_REF);calls=[]
    def old_pin(ref):calls.append(ref);return 'ORIGINAL_OTHER_PIN'
    def old_read(ref):return 'ORIGINAL_READ'
    private_ns=dict(_pin=old_pin,_read=old_read)
    exec('def bind_source_account_descendant(ref): return _pin(ref)',private_ns)
    original=private_ns['bind_source_account_descendant'];anchors=dict(original_ast_anchors=True)
    def factory():return SimpleNamespace(**private_ns),anchors
    outer_ns=dict(_owner=factory,__file__='ORIGINAL_SOURCE_OWNER.py')
    exec('def bind_source_account_descendant(ref):\n owner, anchors = _owner()\n return owner.bind_source_account_descendant(ref)',outer_ns)
    outer=SimpleNamespace(**outer_ns);bound=shim.bind_exact_risk_code_source_owner(outer,transport_ref=shim.RISK_CODE_TRANSPORT_REF)
    assert bound.bind_source_account_descendant.__code__ is outer.bind_source_account_descendant.__code__
    inner,proof=bound.bind_source_account_descendant.__globals__['_owner']()
    assert proof is anchors and inner._read is old_read and inner.bind_source_account_descendant.__code__ is original.__code__
    assert bound.bind_source_account_descendant(shim.RISK_CODE_LOGICAL_REF)==physical and calls==[]
    other=dict(path='UNRELATED_SOURCE.py',sha256='GENERATED_ONLY')
    assert bound.bind_source_account_descendant(other)=='ORIGINAL_OTHER_PIN' and calls==[other]
    with pytest.raises(ValueError,match='OLD_RISK_CODE_SOURCE_HASH_CHANGED'):
        bound.bind_source_account_descendant(dict(shim.RISK_CODE_LOGICAL_REF,sha256='0'*64))
    assert outer.bind_source_account_descendant.__globals__['_owner'] is factory and private_ns['_pin'] is old_pin


@pytest.mark.parametrize('kind',['wrong_proof','wrong_logical','wrong_physical_hash','non_python','modified_python'])
def test_exact_old_risk_code_source_transport_rejects_other_pair_or_changed_bytes(tmp_path,monkeypatch,kind):
    if kind=='wrong_proof':
        with pytest.raises(ValueError):shim._risk_code_transport(dict(shim.RISK_CODE_TRANSPORT_REF,sha256='0'*64))
        return
    value=shim._metadata(shim.RISK_CODE_TRANSPORT_REF,('status','original_code_ref','fixed_custody_ref','old_ref_not_current_risk_execution','old_facts_reconstruction_ids_math_bytes_unchanged','old_freeze_modified','current_risk_modified'))
    if kind=='wrong_logical':value['original_code_ref']=dict(value['original_code_ref'],path=str(tmp_path/'OTHER.py'))
    elif kind=='wrong_physical_hash':value['fixed_custody_ref']=dict(value['fixed_custody_ref'],sha256='0'*64)
    else:
        path=tmp_path/('NOT_CODE.txt' if kind=='non_python' else 'SOURCE.py');path.write_text('GENERATED_SOURCE_BYTES',encoding='utf-8')
        fixed=routing.file_ref(path);monkeypatch.setattr(shim,'RISK_CODE_FIXED_REF',fixed);value['fixed_custody_ref']=fixed
        if kind=='modified_python':path.write_text('CHANGED_GENERATED_BYTES',encoding='utf-8')
    ref=saved(tmp_path/'transport.json',value);monkeypatch.setattr(shim,'RISK_CODE_TRANSPORT_REF',ref)
    with pytest.raises(ValueError):shim._risk_code_transport(ref)


@pytest.fixture
def published192_origin(tmp_path):
    base=saved(tmp_path/'generated_base.json',dict(generated_only=True))
    historical=saved(tmp_path/'generated_historical88.json',dict(generated_only=True))
    actual=saved(tmp_path/'generated_actual192.json',dict(generated_only=True))
    bootstrap=saved(tmp_path/'generated_bootstrap.json',dict(generated_only=True))
    expected=dict(base_ref=base,supplements=[dict(generated_original_owner=i) for i in range(35)])
    ef=saved(tmp_path/'generated_expected192.json',dict(original_actual_preflight_ref=actual))
    composition=dict(schema='CONSENSUS192_QUALIFIED_SOURCE_JOINT_COMPOSITION_VENDOR100',status='QUALIFIED_EXACT192_ORIGINAL35_OWNER_NO_ACCOUNT',base_native_count=105,supplement_count=192,base_ref=base,supplements=expected['supplements'],original_actual_preflight_ref=historical,actual_source_preflight_ref=actual,original_namespaces_preserved=True,source_conflicts_resolved_by_choice=False)
    cr=saved(tmp_path/'generated_composition192.json',composition)
    scope=dict(schema='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1',task_id=routing.engine.TASK,source_completion_count=192,qualified_source_expected_set_ref=ef,qualified_source_composition_ref=cr,joint_owner_source_preflight_ref=actual)
    sr=saved(tmp_path/'generated_scope192.json',scope)
    route=dict(schema=shim.CONTINUATION_SCHEMA,current_source_count=192,qualified_source_scope_ref=sr,expected_freeze_ref=ef,source_joint_ref=actual)
    return SimpleNamespace(tmp=tmp_path,expected=expected,composition=composition,scope=scope,route=route,joint=dict(source_scope_ref=bootstrap),historical=historical)


def test_published192_current_actual_ref_is_distinct_from_historical88_provenance(published192_origin):
    p=published192_origin
    assert shim._qualified_origin(p.route,p.expected,p.joint)==p.scope
    read=shim._composition_projection(p.scope['qualified_source_composition_ref'],dynamic=True)
    assert read['original_actual_preflight_ref']==p.historical
    assert read['actual_source_preflight_ref']==p.route['source_joint_ref']


@pytest.mark.parametrize('kind',['missing_current','wrong_current','only_historical_current','schema','status','count','owners','legacy_route'])
def test_published192_rejects_current_ref_fallback_or_unknown_contract(published192_origin,kind):
    p=published192_origin;r=copy.deepcopy(p.route);c=copy.deepcopy(p.composition)
    if kind=='missing_current':c.pop('actual_source_preflight_ref')
    elif kind=='wrong_current':c['actual_source_preflight_ref']=p.historical
    elif kind=='only_historical_current':c.pop('actual_source_preflight_ref');c['original_actual_preflight_ref']=r['source_joint_ref']
    elif kind=='schema':c['schema']='UNKNOWN_COMPOSITION_SCHEMA'
    elif kind=='status':c['status']='QUALIFIED_EXACT192_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY'
    elif kind=='count':c['supplement_count']=191
    elif kind=='owners':c['supplements']=c['supplements'][:-1]
    else:r['schema']=shim.SCHEMA
    scope=dict(p.scope,qualified_source_composition_ref=saved(p.tmp/'bad_composition.json',c))
    r['qualified_source_scope_ref']=saved(p.tmp/'bad_scope.json',scope)
    with pytest.raises(ValueError):shim._qualified_origin(r,p.expected,p.joint)


def test_legacy61_composition_uses_original_current_reference_unchanged(published192_origin):
    p=published192_origin;r=dict(p.route,schema=shim.SCHEMA,current_source_count=61)
    c=dict(p.composition,schema='CONSENSUS_ACCOUNT_SOURCE_COMPOSITION_ROUTING_R1',status='QUALIFIED_EXACT61_BY_ORIGINAL_OWNER_NO_ACCOUNT_REPLAY',supplement_count=61,original_actual_preflight_ref=r['source_joint_ref'],actual_source_preflight_ref=p.historical)
    scope=dict(p.scope,source_completion_count=61,qualified_source_composition_ref=saved(p.tmp/'legacy61_composition.json',c))
    r['qualified_source_scope_ref']=saved(p.tmp/'legacy61_scope.json',scope)
    assert shim._qualified_origin(r,p.expected,p.joint)==scope


@pytest.mark.parametrize('kind',['exact','wrong_sha','wrong_path'])
def test_private_inputs_original_baseline105_current_factory_exact_source_pin(generated,kind):
    # Run the original I loader to its actual current_factory(pin,current_read)
    # call. Only generated source facts are supplied; stop at the SOURCE pin.
    g=generated;route=dict(g.route,source_code_transport_ref=shim.RISK_CODE_TRANSPORT_REF)
    proxy=SimpleNamespace(CHILD_RESEARCH_ID='UNRELATED_CHILD',_metadata_ref=lambda *a,**kw:None)
    clone=shim.private_inputs(route,proxy,lambda *a:None);ns=clone.load_account_inputs.__globals__
    ns['_consumer_input_entry_guard']=lambda *a:None  # separately covered guards
    events=(cf.old_events()[0],)*105
    original=dict(entitlement_events=events,entitlement_security_tickers={},unsupported_events=(),corporate_actions=(),corporate_action_known_at={})
    risk=copy.deepcopy(shim.RISK_CODE_LOGICAL_REF)
    if kind=='wrong_sha':risk['sha256']='0'*64
    elif kind=='wrong_path':risk['path']=str(g.tmp/'UNRELATED_RISK_CODE.py')
    calls=[];reads=[]
    def original_pin(ref):
        calls.append(ref)
        if ref==risk:raise ValueError('ORIGINAL_SOURCE_PIN_REJECTED_CHANGED_RISK')
        return Path(ref['path'])
    payloads={}
    def save_source(name,value):
        ref=saved(g.tmp/name,value);payloads[ref['path']]=value;return ref
    sources=dict(original_cash_kwargs=save_source('baseline_original.json',{}),ordinary_sources=save_source('baseline_initial.json',{}),a_authority=save_source('baseline_authority.json',dict(research_account=dict(research_account_authority=None))),a_catalogue=save_source('baseline_catalogue.json',dict(events=[])))
    current_ref=save_source('baseline_completion_owner.json',{})
    bundle_ref=save_source('baseline_completion_bundle.json',dict(original_bundle_marker=True))
    manifest=dict(ordinary_owner_ref=current_ref,ordinary_cash_owner_ref=routing.file_ref(inputs.existing.source.cash.__file__),ordinary_bundle_ref=bundle_ref)
    def read(ref):reads.append(ref);return payloads[ref['path']]
    class SourcePinProbe(Exception):pass
    initial=SimpleNamespace(__name__='_generated_baseline_initial',bind_source_account_descendant=lambda *a,**kw:dict(events={}))
    scope=dict(research_id='GENERATED_ONLY',numeric_read_authorization=inputs.GATE,signal_adv_source_ref=dict(path='generated_adv',sha256='b'*64),source_fact_owner_ref=save_source('baseline_initial_owner.json',{}))
    scope_ref=save_source('baseline_scope.json',scope);freeze_ref=save_source('baseline_freeze.json',{})
    current_ns=dict(__name__='_generated_baseline_current',RISK_REF=risk,SourcePinProbe=SourcePinProbe)
    exec("def bind_source_account_descendant(env,kwargs,bundle,*,account_dates,bundle_ref):\n path=_pin(RISK_REF)\n raise SourcePinProbe(path,len(kwargs['entitlement_events']))",current_ns)
    current=SimpleNamespace(**current_ns)
    def loader(ref,name):
        if ref==scope['source_fact_owner_ref']:return initial
        if ref==current_ref:return current
        if ref==manifest['ordinary_cash_owner_ref']:return inputs.existing.source.cash
        raise AssertionError('Unexpected SOURCE owner load')
    existing=SimpleNamespace(__file__=inputs.existing.__file__,ca=inputs.existing.ca,account=SimpleNamespace(),private_source_adapter=inputs.existing.private_source_adapter,_load_python=loader,combine_cash_and_terminal=lambda *a:({},{}),_typed_a=lambda *a:())
    ns['existing']=existing;ns['joblib']=SimpleNamespace(load=lambda path:original)
    bound=dict(scope=scope,source_scope_ref=scope_ref,frozen_contract_ref=freeze_ref,physical_stats={},pin=original_pin,read=read,sources=sources,calendar=pd.DatetimeIndex(['2025-06-02']),source_completion=dict(manifest=manifest))
    adv=pd.DataFrame(dict(signal_date=pd.to_datetime(['2025-06-02']),ticker=['SYNTHETIC'],adv=[1000.],available_at=['2025-06-02T19:59:00Z']));adv.attrs['source_ref']=scope['signal_adv_source_ref']
    if kind=='exact':
        with pytest.raises(SourcePinProbe) as reached:clone.load_account_inputs(bound,signal_adv_by_key=adv)
        assert reached.value.args==(shim._risk_code_transport(shim.RISK_CODE_TRANSPORT_REF),105)
        assert risk not in calls
    else:
        error='OLD_RISK_CODE_SOURCE_HASH_CHANGED' if kind=='wrong_sha' else 'ORIGINAL_SOURCE_PIN_REJECTED_CHANGED_RISK'
        with pytest.raises(ValueError,match=error):clone.load_account_inputs(bound,signal_adv_by_key=adv)
        assert (risk in calls)==(kind=='wrong_path')
    assert bound['pin'] is original_pin and bound['read'] is read and bound['sources'] is sources
    assert inputs.load_account_inputs.__globals__['existing'] is not existing
    assert bundle_ref in reads and not (g.tmp/'FIT_LOG.jsonl').exists()


def test_exact_source_bound_shallow_copy_keeps_other_fields_and_original_pin():
    calls=[]
    def old_pin(ref):calls.append(ref);return 'ORIGINAL_OTHER_PIN'
    read=object();facts=object();bound=dict(pin=old_pin,read=read,source_facts=facts)
    assert shim.exact_risk_code_source_bound(bound,transport_ref=None) is bound
    clone=shim.exact_risk_code_source_bound(bound,transport_ref=shim.RISK_CODE_TRANSPORT_REF)
    assert clone is not bound and set(clone)==set(bound) and clone['read'] is read and clone['source_facts'] is facts and bound['pin'] is old_pin
    other=dict(path='GENERATED_UNRELATED_SOURCE',sha256='GENERATED_ONLY')
    assert clone['pin'](other)=='ORIGINAL_OTHER_PIN' and calls==[other]


@pytest.fixture
def cvx_identity_fixture(tmp_path,monkeypatch):
    sid='SOURCE_ISSUER_COMMON_CLASS:0d7bd0e3ba929e637481cef5f8a1a6f00ebf17fd51be8570396f236913fed7ec';raw='FROZEN_RAW_TRANSPORT_CODE:US.CVX';ca=inputs.existing.ca
    metadata=saved(tmp_path/'synthetic_cvx_metadata.json',dict(generated_only=True))
    events=[];records=[];links=[]
    for index,(prior,ex,available) in enumerate([('2023-02-14','2023-02-15','2023-01-27 00:00:00+00:00'),('2023-05-17','2023-05-18','2023-04-30 00:00:00+00:00'),('2023-11-15','2023-11-16','2023-10-29 00:00:00+00:00')]):
        fact=saved(tmp_path/f'synthetic_cvx_fact{index}.json',dict(generated_only=True,index=index))
        event=ca.SourceBackedEntitlementEvent(f'GENERATED_CVX_{index}','CASH_DIVIDEND',sid,'CVX',ex,ex,str(pd.Timestamp(ex)+pd.Timedelta(days=20))[:10],available,1.25,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,'TIER1_ISSUER_REGULATOR_EXCHANGE',f'https://example.test/source{index}',fact['sha256']);events.append(event)
        converted=replace(event,old_security_id=raw);non_sid={k:v for k,v in asdict(event).items() if k!='old_security_id'}
        dated=[dict(signal_date=d,ticker='CVX',security_id='166764100',moomoo_transport_code='US.CVX') for d in (prior,ex)]
        links.extend(dict(signal_date=d,security_uid='CUSIP:166764100',ticker='CVX',accounting_sid=raw) for d in (prior,ex))
        records.append(dict(event_type='SourceBackedEntitlementEvent',original_event_fingerprint=event.event_fingerprint,derived_event_fingerprint=converted.event_fingerprint,
            non_sid_fields_sha256=inputs.existing.digest(dict(event_type=type(event).__name__,fields=non_sid)),source_fingerprint=event.source_fingerprint,
            source_reference=event.source_reference,original_source_fact_ref=fact,original_identity_binding=dict(security_id=sid,issuer='Chevron Corporation',listing_identity='NYSE:CVX',security_type='COMMON_STOCK',identity_payload_sha256='63f07fafd2470b7ea88add9acdb7277a7177305976a77e2307ab9768fdfc8417'),
            original_source_available_at=available,identity_available_at='2023-01-31T18:58:04Z',effective_identity_available_at=max(pd.Timestamp(available),pd.Timestamp('2023-01-31T18:58:04Z')).isoformat(),ex_date=ex,prior_date=prior,cusip='166764100',security_uid='CUSIP:166764100',accounting_sid=raw,source_coordinate='RAW_ACTUAL_SHARE',dated_identity_rows=dated))
    proof=dict(schema='CONSENSUS_CVX_ORIGINAL_CLASS_DATED_RAW_IDENTITY_PROJECTION_R1',status='FROZEN_EXACT_THREE_ORIGINAL_CVX_IDENTITY_REPRESENTATIONS',task_id=routing.engine.TASK,ticker='CVX',source_sid=sid,accounting_sid=raw,cusip='166764100',security_uid='CUSIP:166764100',source_coordinate='RAW_ACTUAL_SHARE',identity_available_at='2023-01-31T18:58:04Z',same_common_share_class=True,original_source192_qualification_precedes_projection=True,historical_archive_vintage='UNKNOWN',only_authorized_original_event_count=3,new_fits=0,
        derived_fingerprint_rule='SHA256_CANONICAL_DATACLASS_ASDICT_WITH_ONLY_OLD_SECURITY_ID_REPLACED',non_sid_digest_rule='SHA256_CANONICAL_EVENT_TYPE_AND_ASDICT_EXCLUDING_OLD_SECURITY_ID',
        official_subject_common_security=dict(subject_company_cik=93410,subject_company_name='CHEVRON CORP',issuer_literal='CHEVRON CORPORATION',title_of_class='Common Stock',cusip='166764100',acceptance_datetime_local='20230131135804',acceptance_timezone='America/New_York',available_at_utc='2023-01-31T18:58:04Z'),event_projections=records,evidence_refs=dict(generated_metadata_ref=metadata),dated_identity_links=links,
        **{k:False for k in ('share_quantity_effect','source_cash_terms_changed','original_source_available_at_changed','original_source_fingerprints_changed','original_mapping_rewritten','strict_PIT','new_legal_CUSIP_created','actual2026_values_read','market_forecast_or_account_read')})
    projection=saved(tmp_path/'synthetic_cvx_projection.json',proof);monkeypatch.setattr(shim,'CVX_IDENTITY_PROJECTION_REF',projection)
    mapping={sid:'CVX',raw:'CVX','GENERATED_OTHER_SID':'OTHER'}
    binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,source_fingerprint='a'*64,event_fingerprints=[e.event_fingerprint for e in events],security_tickers=mapping,manifest=dict(generated_original_source=True))
    combined=dict(entitlement_events=tuple(events),entitlement_security_tickers=mapping,entitlement_source_binding=binding,corporate_actions=(),unsupported_events=(dict(generated_retained=True),),research_account_authority=dict(generated_original=True),foreign_fx_marks=())
    return SimpleNamespace(proof=proof,ref=projection,events=tuple(events),combined=combined,raw=raw,sid=sid,tmp=tmp_path)


def test_cvx_source_identity_only_sid_binding_lineage_and_original_objects_unchanged(cvx_identity_fixture):
    g=cvx_identity_fixture;before=copy.deepcopy(g.combined)
    with pytest.raises(ValueError,match='ENTITLEMENT_SECURITY_TICKER_BINDING_AMBIGUOUS'):inputs.existing.account._entitlement_binding(g.events,g.combined['entitlement_security_tickers'],g.combined['entitlement_source_binding'])
    result=shim.project_source_identity(g.combined,projection_ref=g.ref)
    assert g.combined==before and result is not g.combined and result['unsupported_events'] is g.combined['unsupported_events']
    assert result['foreign_fx_marks'] is g.combined['foreign_fx_marks'] and result['research_account_authority'] is g.combined['research_account_authority']
    for old,new,row in zip(g.events,result['entitlement_events'],g.proof['event_projections']):
        assert type(old) is type(new) and new.old_security_id==g.raw and new.event_fingerprint==row['derived_event_fingerprint']
        assert {k:v for k,v in asdict(old).items() if k!='old_security_id'}=={k:v for k,v in asdict(new).items() if k!='old_security_id'}
    assert inputs.existing.account._entitlement_identity_chains(result['entitlement_events'],result['entitlement_security_tickers'])=={}
    assert inputs.existing.account._entitlement_binding(result['entitlement_events'],result['entitlement_security_tickers'],result['entitlement_source_binding'])==result['entitlement_source_binding']
    lineage=result['entitlement_source_binding']['manifest']['source_identity_projection']['event_lineage'];assert len(lineage)==3
    assert lineage[0]['original_source_available_at']=='2023-01-27 00:00:00+00:00' and lineage[0]['effective_identity_available_at']=='2023-01-31T18:58:04+00:00'
    assert result['entitlement_security_tickers']=={g.raw:'CVX','GENERATED_OTHER_SID':'OTHER'}


@pytest.mark.parametrize('kind',['UID','sourceFP','proofclock','eventtype','cash','unit','originalavailable','effectiveclock','derivedFP','futureproof','sharetransition','unproved_source_event'])
def test_cvx_identity_projection_rejects_unproved_changes(cvx_identity_fixture,monkeypatch,kind):
    g=cvx_identity_fixture;proof=copy.deepcopy(g.proof);combined=dict(g.combined)
    if kind=='UID':proof['event_projections'][0]['dated_identity_rows'][0]['security_id']='BAD_CUSIP'
    elif kind=='sourceFP':proof['event_projections'][0]['source_fingerprint']='e'*64
    elif kind=='proofclock':proof['event_projections'][0]['identity_available_at']='2023-02-16T00:00:00Z'
    elif kind=='effectiveclock':proof['event_projections'][0]['effective_identity_available_at']='2023-01-27T00:00:00Z'
    elif kind=='derivedFP':proof['event_projections'][0]['derived_event_fingerprint']='e'*64
    elif kind=='futureproof':proof['event_projections'].append(dict(proof['event_projections'][0],ex_date='2025-12-01'))
    elif kind=='sharetransition':combined['corporate_actions']=(SimpleNamespace(old_security_id=g.sid,new_security_id=g.raw),)
    else:
        events=list(g.events)
        if kind=='unit':
            with pytest.raises(ValueError):replace(events[0],amount_unit='UNCONFIRMED')
            return
        if kind=='eventtype':
            class GeneratedChangedType(inputs.existing.ca.SourceBackedEntitlementEvent):pass
            events[0]=GeneratedChangedType(**asdict(events[0]))
        elif kind=='unproved_source_event':events.append(replace(events[0],event_id='UNPROVED_EXTRA'))
        else:events[0]=replace(events[0],**{'cash':{'cash_per_old_share':2.},'unit':{'amount_unit':'UNCONFIRMED'},'originalavailable':{'available_at':'2023-01-28 00:00:00+00:00'}}[kind])
        combined['entitlement_events']=tuple(events)
    if proof!=g.proof:
        changed=saved(g.tmp/'generated_changed_proof.json',proof);monkeypatch.setattr(shim,'CVX_IDENTITY_PROJECTION_REF',changed);g.ref=changed
    with pytest.raises(ValueError):shim.project_source_identity(combined,projection_ref=g.ref)


def test_cvx_future_append_preserves_prior_typed_events_and_lineage(cvx_identity_fixture):
    g=cvx_identity_fixture;first=shim.project_source_identity(g.combined,projection_ref=g.ref)
    future=replace(g.events[2],event_id='GENERATED_FUTURE_RAW',old_security_id=g.raw,ex_date='2025-11-17',record_date='2025-11-17',pay_date='2025-12-01',available_at='2025-10-31 00:00:00+00:00')
    appended=dict(g.combined,entitlement_events=g.events+(future,))
    second=shim.project_source_identity(appended,projection_ref=g.ref)
    assert [asdict(e) for e in first['entitlement_events']]==[asdict(e) for e in second['entitlement_events'][:3]]
    assert first['entitlement_source_binding']['manifest']['source_identity_projection']['event_lineage']==second['entitlement_source_binding']['manifest']['source_identity_projection']['event_lineage']
    assert second['entitlement_events'][-1] is future


def test_cvx_connector_projects_after_native_source_validation(cvx_identity_fixture,monkeypatch):
    g=cvx_identity_fixture;order=[]
    monkeypatch.setattr(shim,'validate_entries',lambda *a,**k:dict(current_count=192))
    def bind(*a,**k):order.append('native');return [],()
    def compose(*a,**k):order.append('compose');return g.combined
    original=shim.project_source_identity
    def project(value,**kw):assert value is g.combined;order.append('identity');return original(value,**kw)
    monkeypatch.setattr(shim,'bind_components',bind);monkeypatch.setattr(shim,'compose_components',compose);monkeypatch.setattr(shim,'project_source_identity',project)
    hook=shim.source_connector({},qualified_fx=None,pin=None,read=None,original_source_kwargs_ref=None,source_identity_projection_ref=g.ref)
    result,_=hook({},None,dict(calendar=()),None,{})
    assert order==['native','compose','identity'] and all(e.old_security_id==g.raw for e in result['entitlement_events'])
    order.clear()
    def bad_compose(*a,**k):order.append('compose');raise ValueError('ORIGINAL_SOURCE_FINGERPRINT_GATE')
    monkeypatch.setattr(shim,'compose_components',bad_compose)
    with pytest.raises(ValueError,match='ORIGINAL_SOURCE_FINGERPRINT_GATE'):hook({},None,dict(calendar=()),None,{})
    assert order==['native','compose']


@pytest.fixture
def named_cvx_dd_identity_fixture(cvx_identity_fixture,monkeypatch):
    cvx=cvx_identity_fixture;ca=inputs.existing.ca;sid='SOURCE_ISSUER_COMMON_CLASS:e2ed4b7d2c8319ffe0205f635a4dca9430d063db41cd5ed3183b0be34d21dde5';raw='FROZEN_RAW_TRANSPORT_CODE:US.DD';events=[];records=[];links=[]
    dates=['2023-02-27','2023-05-30','2023-07-28','2023-11-29','2024-02-28','2024-05-31','2024-08-30','2024-11-29','2025-03-03','2025-05-30','2025-08-29']
    for index,ex in enumerate(dates):
        prior=str((pd.Timestamp(ex)-pd.Timedelta(days=1)).date());available='2023-02-09 00:00:00+00:00';fact=saved(cvx.tmp/f'generated_dd_fact_{index}.json',dict(generated_only=True,index=index))
        e=ca.SourceBackedEntitlementEvent(f'GENERATED_DD_{index}','CASH_DIVIDEND',sid,'DD',ex,ex,str((pd.Timestamp(ex)+pd.Timedelta(days=20)).date()),available,0.75,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,'TIER1_ISSUER_REGULATOR_EXCHANGE',f'https://example.test/dd/{index}',fact['sha256']);events.append(e);converted=replace(e,old_security_id=raw);non_sid={k:v for k,v in asdict(e).items() if k!='old_security_id'}
        dated=[dict(signal_date=d,ticker='DD',security_id='26614N102',moomoo_transport_code='US.DD') for d in (prior,ex)];links.extend(dict(signal_date=d,security_uid='CUSIP:26614N102',ticker='DD',accounting_sid=raw) for d in (prior,ex))
        records.append(dict(event_type='SourceBackedEntitlementEvent',original_event_fingerprint=e.event_fingerprint,derived_event_fingerprint=converted.event_fingerprint,non_sid_fields_sha256=inputs.existing.digest(dict(event_type=type(e).__name__,fields=non_sid)),source_fingerprint=e.source_fingerprint,source_reference=e.source_reference,original_source_fact_ref=fact,original_identity_binding=dict(security_id=sid,issuer='DuPont de Nemours, Inc.',listing_identity='NYSE:DD',security_type='COMMON_STOCK',identity_payload_sha256='5b9b16995ae1aa7a0c8d373cf768cbcddeea1dab2ac576d81561a84bb12c429c'),original_source_available_at=available,identity_available_at='2023-02-03T16:43:53Z',effective_identity_available_at=pd.Timestamp(available).isoformat(),ex_date=ex,prior_date=prior,cusip='26614N102',security_uid='CUSIP:26614N102',accounting_sid=raw,source_coordinate='RAW_ACTUAL_SHARE',dated_identity_rows=dated))
    retained=dict(ticker='DD',effective_date='2025-11-03',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference=r'D:\us-tech-quant-results\A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1\ACCOUNT_EVENT_BINDING_R1.json',source_fingerprint='153701085c92c6508d55782fedb41f86458a0c67e888a3e5300fbc6ae136bb9d')
    dd=dict(cvx.proof,schema='CONSENSUS_DD_ORIGINAL_CLASS_DATED_RAW_IDENTITY_PROJECTION_R1',status='FROZEN_EXACT_ELEVEN_ORIGINAL_DD_IDENTITY_REPRESENTATIONS',ticker='DD',source_sid=sid,accounting_sid=raw,cusip='26614N102',security_uid='CUSIP:26614N102',identity_available_at='2023-02-03T16:43:53Z',only_authorized_original_event_count=11,event_projections=records,dated_identity_links=links,official_subject_common_security=dict(subject_company_cik=1666700,subject_company_name='DuPont de Nemours, Inc.',issuer_literal='DUPONT DE NEMOURS INC',title_of_class='COMMON STOCK',cusip='26614N102',acceptance_datetime_local='20230203114353',acceptance_timezone='America/New_York',available_at_utc='2023-02-03T16:43:53Z'),share_quantity_effect_scope='THIS_IDENTITY_REPRESENTATION_PROJECTION_ONLY',retained_unsupported_event=retained,
        retained_unsupported_instructions={k:True for k in ('all_original_Nov03_fields_must_remain_unchanged','all6500_remaining_unsupported_preserved','owner26_removes_only_DD_2025_11_28_cash_key','preexisting_held_Nov03_permanently_invalid_NAV','actual_holdings_not_assumed','namespace_projection_does_not_qualify_distribution')},parent_quantity_evidence=dict(document_date='2025-10-15',absolute_publication_available_at='UNKNOWN_IN_THIS_BODY_CUSTODY',historical_availability='UNKNOWN',only_Qnity_distribution_no_parent_surrender_exchange_and_parent_outstanding_rights_unchanged=True,other_corporate_actions_exhaustively_checked=False,unproved_other_actions='UNKNOWN',child_asset_or_cash_in_lieu_valuation_qualified=False,fragments=[dict(role=role,fragment_ref=saved(cvx.tmp/f'generated_parent_{i}.json',dict(generated_only=True))) for i,role in enumerate(['DOCUMENT_DATE','LEGAL_ISSUERS_AND_DISTRIBUTED_COMMON_CLASS','OLD_DD_NO_SURRENDER_OR_EXCHANGE','OLD_DD_OUTSTANDING_SHARES_AND_RIGHTS_UNCHANGED'])]))
    ddref=saved(cvx.tmp/'generated_dd_projection.json',dd);monkeypatch.setattr(shim,'DD_IDENTITY_PROJECTION_REF',ddref)
    manifest=dict(schema='CONSENSUS_CVX_DD_EXACT_IDENTITY_PROJECTION_MANIFEST_R1',status='FROZEN_TWO_NAMED_SOURCE_IDENTITY_REPRESENTATIONS',task_id=routing.engine.TASK,projections=[dict(ticker='CVX',projection_ref=cvx.ref,original_event_count=3),dict(ticker='DD',projection_ref=ddref,original_event_count=11)],authorized_original_event_count=14,historical_archive_vintage='UNKNOWN',unproved_other_actions='UNKNOWN',new_fits=0,retained_DD_Nov03_unsupported_event=retained,
        **{k:True for k in ('original_source192_qualification_precedes_projection','original_source_payload_unchanged','original_Source_available_at_unchanged','original_Source_fingerprints_unchanged','all_non_SID_economic_fields_unchanged','unsupported_events_all_original_fields_unchanged','retained_DD_held_permanent_NAV_invalid')},**{k:False for k in ('share_quantity_effect','other_ticker_alias_authorized','child_asset_or_cash_in_lieu_qualification','strict_PIT','actual2026_values_read','market_forecast_or_account_read')})
    manifest_ref=saved(cvx.tmp/'generated_named_manifest.json',manifest);monkeypatch.setattr(shim,'IDENTITY_PROJECTION_MANIFEST_REF',manifest_ref)
    mapping=dict(cvx.combined['entitlement_security_tickers'],**{sid:'DD',raw:'DD'});all_events=cvx.events+tuple(events);binding=dict(cvx.combined['entitlement_source_binding'],event_fingerprints=[e.event_fingerprint for e in all_events],security_tickers=mapping)
    combined=dict(cvx.combined,entitlement_events=all_events,entitlement_security_tickers=mapping,entitlement_source_binding=binding,unsupported_events=(dict(retained,generated_extra_field='MUST_REMAIN'),))
    return SimpleNamespace(cvx=cvx,dd=dd,ddref=ddref,manifest=manifest,ref=manifest_ref,combined=combined,sid=sid,raw=raw,retained=retained)


def test_named_cvx_dd_identity_projection_keeps_all_economics_and_full_unsupported(named_cvx_dd_identity_fixture):
    g=named_cvx_dd_identity_fixture;before=copy.deepcopy(g.combined);result=shim.project_source_identity(g.combined,projection_ref=g.ref)
    assert g.combined==before and result['unsupported_events'] is g.combined['unsupported_events']
    assert result['unsupported_events'][0]['generated_extra_field']=='MUST_REMAIN'
    for old,new in zip(g.combined['entitlement_events'],result['entitlement_events']):
        assert type(new) is type(old) and {k:v for k,v in asdict(old).items() if k!='old_security_id'}=={k:v for k,v in asdict(new).items() if k!='old_security_id'}
    assert set(e.old_security_id for e in result['entitlement_events'])=={g.raw,g.cvx.raw}
    assert len(result['entitlement_source_binding']['manifest']['source_identity_projection']['event_lineage'])==14
    assert inputs.existing.account._entitlement_identity_chains(result['entitlement_events'],result['entitlement_security_tickers'])=={}
    inputs.existing.account._entitlement_binding(result['entitlement_events'],result['entitlement_security_tickers'],result['entitlement_source_binding'])


@pytest.mark.parametrize('kind',['wrong_UID','source_FP','late_clock','type','cash','missing_Nov03','changed_Nov03','changed_parent_quantity','new_issuer','wrong_manifest'])
def test_named_dd_identity_projection_fails_closed(named_cvx_dd_identity_fixture,monkeypatch,kind):
    g=named_cvx_dd_identity_fixture;dd=copy.deepcopy(g.dd);combined=dict(g.combined);manifest=copy.deepcopy(g.manifest)
    if kind=='wrong_UID':dd['event_projections'][0]['dated_identity_rows'][0]['security_id']='BAD'
    elif kind=='source_FP':dd['event_projections'][0]['source_fingerprint']='e'*64
    elif kind=='late_clock':dd['event_projections'][0]['effective_identity_available_at']='2023-02-28T00:00:00Z'
    elif kind=='changed_parent_quantity':dd['parent_quantity_evidence']['only_Qnity_distribution_no_parent_surrender_exchange_and_parent_outstanding_rights_unchanged']=False
    elif kind=='missing_Nov03':combined['unsupported_events']=()
    elif kind=='changed_Nov03':combined['unsupported_events']=(dict(g.retained,source_fingerprint='b'*64),)
    elif kind=='new_issuer':manifest['projections'].append(dict(ticker='UNPROVED',projection_ref=g.ddref,original_event_count=1))
    elif kind=='wrong_manifest':manifest['authorized_original_event_count']=13
    else:
        events=list(combined['entitlement_events']);e=events[3]
        if kind=='cash':events[3]=replace(e,cash_per_old_share=0.8)
        elif kind=='type':
            class ChangedType(inputs.existing.ca.SourceBackedEntitlementEvent):pass
            events[3]=ChangedType(**asdict(e))
        combined['entitlement_events']=tuple(events)
    if dd!=g.dd:
        changed=saved(g.cvx.tmp/'generated_bad_dd.json',dd);monkeypatch.setattr(shim,'DD_IDENTITY_PROJECTION_REF',changed);manifest['projections'][1]['projection_ref']=changed
    if manifest!=g.manifest:
        changed=saved(g.cvx.tmp/'generated_bad_manifest.json',manifest);monkeypatch.setattr(shim,'IDENTITY_PROJECTION_MANIFEST_REF',changed);g.ref=changed
    with pytest.raises(ValueError):shim.project_source_identity(combined,projection_ref=g.ref)


@pytest.fixture
def interrupted_risk(dynamic_authorized):
    a=dynamic_authorized;engine=routing.engine;joint=engine.joint
    dates=pd.bdate_range('2022-09-01',periods=100)
    returns=pd.DataFrame({'A':[.001*((i%7)-3) for i in range(100)],
                          'B':[.002*((i%11)-5) for i in range(100)]},index=dates)
    returns.attrs['source_id']='SYNTHETIC_CAUSAL_PRE2026_RETURNS'
    forecasts=pd.DataFrame(columns=['signal_date','ticker','mu','sigma','p_up','q10','q50','q90'])
    forecasts.attrs['unit']=joint.UNIT
    events=[];policy=joint.ConsensusJointPolicy(forecasts,returns,on_risk_fit_started=events.append)
    policy._risk(pd.Timestamp('2023-02-01'),('A','B'))
    token=engine.values.digest(dict(source_pins=engine.source_pins(),event=events[0]))
    original=a.run.parent/'SYNTHETIC_INTERRUPTED_RUN'
    assert original.resolve().is_relative_to(a.g.tmp.resolve())
    original.mkdir()
    old_route=copy.deepcopy(a.route);old_route['original_routing_metadata']['output_run']=str(original)
    old_contract=copy.deepcopy(a.contract);old_contract['output_run']=str(original)
    old_route['execution_contract_ref']=saved(original/'old_execution_contract.json',old_contract)
    old_freeze=saved(original/shim.CONTINUATION_FREEZE,old_route)
    root=original/'evaluation/consensus_account'/'synthetic_LW';root.mkdir(parents=True)
    # This intentionally mixed state proves that only its risk_cache is injected.
    state_path=root/'state.joblib'
    assert state_path.resolve().is_relative_to(a.g.tmp.resolve())
    engine.joblib.dump(dict(risk_cache=policy.risk_cache,
        final_state=dict(SYNTHETIC_OLD_ACCOUNT_MUST_NOT_BE_REUSED=True)),state_path)
    state=routing.file_ref(state_path)
    receipt=saved(root/'receipt.json',dict(status='COMPLETE',task_id=engine.TASK,
        freeze_ref=old_freeze,artifacts=dict(state=state)))
    rows=[dict(event='FIT_STARTED',fit_units=1,model_id='LW',year=2023,
        component=component,budget_bucket='consensus_account_primary_risk',reuse_tuple_sha256=token)
        for component in ('RISK_INPUT_PREPROCESSING_ATTEMPT','RISK_ESTIMATOR_STATE_ATTEMPT')]
    def log(path,rows):
        assert path.resolve().is_relative_to(a.g.tmp.resolve())
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
        return routing.file_ref(path)
    original_log=log(original/'FIT_LOG.jsonl',rows)
    prefix=log(a.g.tmp/'stopped_raw_prefix.jsonl',rows)
    native=[]
    for parent,count in ((routing.FEATURE_ORIGIN,700),(routing.FROZEN_ORIGIN,591)):
        path=parent/'FIT_LOG.jsonl';ref=log(path,[dict(event='FIT_STARTED',fit_units=1) for _ in range(count)])
        native.append(dict(ref,bytes=path.stat().st_size,fit_started_count=count,fit_units=count))
    proof=dict(schema='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R1',status='PINNED_CHECKPOINT_CARRYOVER',
        task_id=engine.TASK,output_run=str(a.run),original_run=str(original),original_freeze_ref=old_freeze,
        risk_state_receipt_ref=receipt,risk_state_ref=state,risk_fit_log_ref=prefix,original_fit_log_ref=original_log,
        baseline_fit_log_proofs=native,prior_fit_units=1291,carried_fit_units=2,effective_prior_fit_units=1293,
        max_fit_units=10000,risk_cache_entry_count=1,log_started_tuple_count=1,risk_state_source_modules=[])
    a.route.update(risk_fit_carryover_ref=saved(a.g.tmp/'carryover.json',proof),effective_prior_fit_units=1293)
    a.contract=shim.execution_contract_template(a.route,research_id='SYNTHETIC_RECOVERY',
        managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    a.route['execution_contract_ref']=saved(a.g.tmp/'recovery_execution_contract.json',a.contract)
    a.freeze=saved(a.run/shim.CONTINUATION_FREEZE,a.route)
    return SimpleNamespace(a=a,proof=proof,returns=returns,forecasts=forecasts,token=token,events=events)


def test_carryover_reuses_actual_toy_risk_bundle_without_fitting_or_old_account(interrupted_risk,monkeypatch):
    r=interrupted_risk;a=r.a;joint=routing.engine.joint;context={};seen=[]
    def core(run,cache):seen.append(cache);return cache
    guarded=shim._guarded_execution(a.route,core,cache_context=context)
    cache={};assert guarded(a.run,cache) is cache
    assert len(cache)==1 and 'final_state' not in cache
    def forbidden(*args,**kwargs):raise AssertionError('checkpointed risk must not be fitted again')
    monkeypatch.setattr(joint.risk,'fit_risk_estimator',forbidden)
    policy=joint.ConsensusJointPolicy(r.forecasts,r.returns,shared_risk_cache=cache,on_risk_fit_started=forbidden)
    covariance,metadata=policy._risk(pd.Timestamp('2023-02-01'),('A','B'))
    assert covariance.shape==(2,2) and metadata['fit_cutoff']=='2023-02-01 00:00:00'
    assert guarded(a.run,cache) is cache and seen==[cache,cache]
    assert a.contract['budget']==dict(prior_fit_units=1291,max_fit_units=10000)
    assert a.contract['effective_prior_fit_units']==1293 and a.contract['old_risk_cache_reused'] is True
    assert a.contract['old_account_state_reused'] is False and not (a.run/'FIT_LOG.jsonl').exists()


@pytest.mark.parametrize('kind',['budget','native_prefix','risk_prefix','state_hash','source_recipe','cache_tuple','future_cutoff'])
def test_carryover_rejects_unproven_budget_identity_and_state_before_fit(interrupted_risk,monkeypatch,kind):
    r=interrupted_risk;a=r.a;proof=copy.deepcopy(r.proof)
    if kind=='budget':proof['effective_prior_fit_units']=1291
    elif kind=='native_prefix':proof['baseline_fit_log_proofs'][0]['sha256']='0'*64
    elif kind=='risk_prefix':proof['risk_fit_log_ref']['sha256']='0'*64
    elif kind=='state_hash':proof['risk_state_ref']['sha256']='0'*64
    elif kind=='source_recipe':
        old=json.loads(Path(proof['original_freeze_ref']['path']).read_text());old['original_routing_metadata']['recipe']['lookback_sessions']=60
        proof['original_freeze_ref']=saved(Path(proof['original_freeze_ref']['path']),old)
    else:
        assert Path(proof['risk_state_ref']['path']).resolve().is_relative_to(a.g.tmp.resolve())
        assert Path(proof['risk_state_receipt_ref']['path']).resolve().is_relative_to(a.g.tmp.resolve())
        state=routing.engine.joblib.load(proof['risk_state_ref']['path']);key,bundle=next(iter(state['risk_cache'].items()))
        if kind=='cache_tuple':state['risk_cache']={(*key[:3],'0'*64):bundle}
        else:bundle.specification['fit_cutoff']=pd.Timestamp('2026-02-01')
        routing.engine.joblib.dump(state,proof['risk_state_ref']['path']);proof['risk_state_ref']=routing.file_ref(proof['risk_state_ref']['path'])
        receipt=json.loads(Path(proof['risk_state_receipt_ref']['path']).read_text());receipt['artifacts']['state']=proof['risk_state_ref']
        proof['risk_state_receipt_ref']=saved(Path(proof['risk_state_receipt_ref']['path']),receipt)
    a.route['risk_fit_carryover_ref']=saved(a.g.tmp/'changed_carryover.json',proof)
    calls=[]
    monkeypatch.setattr(routing.engine.joint.risk,'fit_risk_estimator',lambda *args,**kwargs:calls.append(True))
    with pytest.raises(ValueError):
        value=shim._risk_fit_carryover(a.route,a.run)
        shim._carryover_risk_cache(value)
    assert calls==[]


def test_carryover_private_policy_bans_old_started_tuple_and_uses_total_prior(interrupted_risk,monkeypatch):
    r=interrupted_risk;a=r.a;g=a.g
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    connector=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=g.read,
        original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    runner,lineage=shim.bind_runner(a.route,a.freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=connector)
    assert lineage['engine_routing_anchor_count']==6 and runner._routing_prior(a.run)==1293
    cache={};policy=runner.make_policy(r.forecasts,r.returns,routing.engine.joint.PolicyConfig(),
        routing.engine.cash.FeeConfig(),a.run,dict(fit_units=0),cache,'synthetic_identity')
    assert len(cache)==1
    # If a started tuple has no usable checkpoint it remains a no-retry failure.
    policy.risk_cache.clear()
    with pytest.raises(ValueError,match='RISK_FAILED_OR_UNCHECKPOINTED_ATTEMPT_NO_RETRY'):
        policy._risk(pd.Timestamp('2023-02-01'),('A','B'))
    physical=[]
    def stop_before_fit(*args,**kwargs):
        physical.append(kwargs);raise RuntimeError('SYNTHETIC_STOP_BEFORE_PHYSICAL_FIT')
    monkeypatch.setattr(routing.engine.values,'_fit_job',stop_before_fit)
    with pytest.raises(RuntimeError,match='SYNTHETIC_STOP_BEFORE_PHYSICAL_FIT'):
        policy._risk(pd.Timestamp('2023-03-01'),('A','B'))
    assert len(physical)==1 and physical[0]['prior']==1293 and physical[0]['auth']['max_fit_units']==10000
    assert not (a.run/'FIT_LOG.jsonl').exists()


def test_carryover_source_module_must_be_exact_registered_member_before_joblib(interrupted_risk,monkeypatch):
    r=interrupted_risk;a=r.a;proof=copy.deepcopy(r.proof);role=a.route['source_roles'][0]
    owner=shim.canonical(role['native_owner_ref']);bundle=shim.canonical(role['bundle_ref'])
    name='_consensus_dynamic_source_'+inputs.existing.digest(dict(owner=owner,bundle=bundle))[:24]
    proof['risk_state_source_modules']=[dict(name=name,owner_ref=owner,bundle_ref=bundle)]
    a.route['risk_fit_carryover_ref']=saved(a.g.tmp/'module_guard_carryover.json',proof)
    value=shim._risk_fit_carryover(a.route,a.run)
    monkeypatch.delitem(__import__('sys').modules,name,raising=False)
    calls=[]
    monkeypatch.setattr(routing.engine.joblib,'load',lambda *args,**kwargs:calls.append(True))
    with pytest.raises(ValueError,match='CARRYOVER_EXACT_REGISTERED_SOURCE_MODULE_REQUIRED'):
        shim._carryover_risk_cache(value)
    assert calls==[]


@pytest.fixture
def two_prefix_equal_repair(interrupted_risk,monkeypatch):
    r=interrupted_risk;a=r.a;old_run=a.run;old_route=copy.deepcopy(a.route);old_freeze=a.freeze
    engine=routing.engine;events=[]
    original_flow_id=engine.flow_id
    def generated_flow_id(method,risk_method='LW',allocation_method='cost_aware',tag=None,*,run=None):
        # Temp synthetic origins do not alter the maintained owner's frozen run.
        assert run is None or Path(run).resolve() in (routing.FROZEN_ORIGIN.resolve(),engine.fusion.CONTINUATION_RUN.resolve())
        return original_flow_id(method,risk_method,allocation_method,tag,run=engine.fusion.CONTINUATION_RUN)
    monkeypatch.setattr(engine,'flow_id',generated_flow_id)
    policy=engine.joint.ConsensusJointPolicy(r.forecasts,r.returns,shared_risk_cache=dict(
        shim._carryover_risk_cache(shim._risk_fit_carryover(old_route,old_run))),on_risk_fit_started=events.append)
    policy._risk(pd.Timestamp('2023-03-01'),('A','B'))
    token=engine.values.digest(dict(source_pins=engine.source_pins(),event=events[0]))
    def log(path,token):
        rows=[dict(event='FIT_STARTED',fit_units=1,model_id='LW',year=2023,component=component,
            budget_bucket='consensus_account_primary_risk',reuse_tuple_sha256=token)
            for component in ('RISK_INPUT_PREPROCESSING_ATTEMPT','RISK_ESTIMATOR_STATE_ATTEMPT')]
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf8');return routing.file_ref(path)
    original_log=log(old_run/'FIT_LOG.jsonl',token);prefix=log(a.g.tmp/'second_raw_prefix.jsonl',token)
    root=old_run/'evaluation/consensus_account'/'synthetic_r9_cache';root.mkdir(parents=True)
    state=root/'state.joblib';engine.joblib.dump(dict(risk_cache=policy.risk_cache,
        final_state=dict(SYNTHETIC_OLD_ACCOUNT_MUST_NOT_BE_REUSED=True)),state)
    receipt=saved(root/'receipt.json',dict(status='NOT_TESTABLE',task_id=engine.TASK,
        freeze_ref=old_freeze,artifacts=dict(state=routing.file_ref(state))))
    new=old_run.parent/'SYNTHETIC_EQUAL_REPAIR_RUN';new.mkdir()
    proof=dict(schema='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R2',status='PINNED_CHECKPOINT_CARRYOVER',
        task_id=engine.TASK,output_run=str(new),original_run=str(old_run),original_freeze_ref=old_freeze,
        risk_state_receipt_ref=receipt,risk_state_ref=routing.file_ref(state),risk_fit_log_ref=prefix,
        original_fit_log_ref=original_log,baseline_fit_log_proofs=r.proof['baseline_fit_log_proofs'],
        prior_fit_units=1291,carried_fit_units=4,current_run_fit_units=2,effective_prior_fit_units=1295,
        max_fit_units=10000,risk_cache_entry_count=2,log_started_tuple_count=2,risk_state_source_modules=[],
        predecessor_carryover_ref=old_route['risk_fit_carryover_ref'])
    refs=[]
    for path in old_route['original_routing_metadata']['recipe']['stage2']:
        fid=engine.flow_id('nnls_zero_abstain',path['risk_method'],path['allocation_method'],run=engine.fusion.CONTINUATION_RUN)
        status='NOT_TESTABLE';failure={};statistics={}
        if path['risk_method']=='OAS':status='COMPLETE';statistics=dict(mean_annual_cost_net_sharpe=1.,total_turnover=2.)
        if path['allocation_method']=='equal_weight':status='FAILED_NO_RETRY';failure=dict(type='ZeroDivisionError',reason='float division by zero')
        value=dict(status=status,task_id=engine.TASK,flow_id=fid,fusion_method='nnls_zero_abstain',**path,
            diagnostic_only=False,freeze_ref=old_freeze,fee_config=old_route['original_routing_metadata']['recipe']['fee_config'],
            lookback_sessions=120,statistics=statistics,failure=failure,fit_units=0)
        refs.append(saved(old_run/'evaluation/consensus_account'/fid/'receipt.json',value))
    failed=next(ref for ref in refs if 'equal_weight' in ref['path'])
    scope=dict(schema='CONSENSUS_EQUAL_EMPTY_SUPPORT_NO_NEW_FIT_REPAIR_R1',status='FROZEN_NO_NEW_FIT_EQUAL_REPAIR',
        task_id=engine.TASK,output_run=str(new),original_run=str(old_run),original_freeze_ref=old_freeze,
        original_failed_receipt_ref=failed,stage2_receipt_refs=refs,fusion_method='nnls_zero_abstain',risk_method='LW',
        allocation_method='equal_weight',diagnostic=None,initial_cash_usd=3000,initial_holdings=[],no_new_risk_fit=True,
        test2026_read_authorized=False,real_trades_authorized=False,old_account_state_reused=False,prior_fit_units=1291,
        effective_prior_fit_units=1295,max_fit_units=10000,scope_start='2023-01-01',scope_end_exclusive='2026-01-01',
        protected_owner_refs=shim.protected_pins(),actual_compiler_ref=shim.JOINT_EXECUTION_BINDING['actual_allocator_compiler_ref'],
        old_failed_fit_tuples_no_retry=True,old_receipts_preserved=True)
    final_root=old_run/'models/consensus_final_policy'/engine.flow_id('nnls_zero_abstain','OAS','cost_aware',run=engine.fusion.CONTINUATION_RUN)
    final_root.mkdir(parents=True);final_state=final_root/'state.joblib';final_state.write_bytes(b'SYNTHETIC_PIN_ONLY_NEVER_DECODED')
    final_ref=saved(final_root/'receipt.json',dict(status='COMPLETE',task_id=engine.TASK,
        selected_flow=final_root.name,freeze_ref=old_freeze,final_risk_fit_cutoff='2026-01-01 exclusive',test_rows_read=0,
        artifacts=dict(state=routing.file_ref(final_state)),actual_final_risk_budget=dict(total_state_estimations=2)))
    a.route=copy.deepcopy(old_route);a.run=new;a.route['original_routing_metadata']['output_run']=str(new)
    reader=json.loads(Path(a.route['reader_scope_ref']['path']).read_text(encoding='utf8'));reader['consumer_output_run']=str(new)
    a.route['reader_scope_ref']=saved(new/'synthetic_reader_scope.json',reader)
    a.route.update(risk_fit_carryover_ref=saved(a.g.tmp/'two_prefix_carryover.json',proof),effective_prior_fit_units=1295,
        no_new_risk_fit=True,account_repair_ref=saved(a.g.tmp/'equal_repair_scope.json',scope),original_final_risk_receipt_ref=final_ref)
    managed=json.loads(Path(a.contract['managed_run_config_ref']['path']).read_text(encoding='utf8'));managed['run_id']=new.name
    rc=saved(new/'run_config.json',managed);im=saved(new/'input_manifest.json',managed)
    a.contract=shim.execution_contract_template(a.route,research_id='SYNTHETIC_NO_FIT_EQUAL_REPAIR',
        managed_run_config_ref=rc,managed_input_manifest_ref=im)
    a.route['execution_contract_ref']=saved(new/'synthetic_execution_contract.json',a.contract)
    a.freeze=saved(new/shim.CONTINUATION_FREEZE,a.route)
    return SimpleNamespace(a=a,r=r,proof=proof,scope=scope,old_run=old_run,second_token=token,old_failed=failed)


def test_two_prefix_budget_and_full_risk_cache_union_no_old_account(two_prefix_equal_repair):
    r=two_prefix_equal_repair;a=r.a;assert shim.validate(a.route,execute=True)[0]==a.run
    value=shim._risk_fit_carryover(a.route,a.run);cache=shim._carryover_risk_cache(value)
    assert value['effective_prior_fit_units']==1295 and len(value['started'])==4
    assert value['started_tokens']=={r.r.token,r.second_token} and len(cache)==2
    assert a.contract['no_new_risk_fit'] is True and a.contract['account_repair_ref']==a.route['account_repair_ref']
    assert a.contract['budget']==dict(prior_fit_units=1291,max_fit_units=10000)
    assert 'final_state' not in cache and not (a.run/'FIT_LOG.jsonl').exists()


@pytest.mark.parametrize('kind',['total','current_count','predecessor','duplicate_token','third_prefix','scope_cash','scope_future','slot_order','failed_reason','contract_no_fit'])
def test_two_prefix_and_equal_scope_fail_closed(two_prefix_equal_repair,kind):
    r=two_prefix_equal_repair;a=r.a;proof=copy.deepcopy(r.proof);scope=copy.deepcopy(r.scope)
    if kind=='total':proof['carried_fit_units']=2
    elif kind=='current_count':proof['current_run_fit_units']=4
    elif kind=='predecessor':proof['predecessor_carryover_ref']['sha256']='0'*64
    elif kind=='duplicate_token':
        for name in ('original_fit_log_ref','risk_fit_log_ref'):
            path=Path(proof[name]['path']);body=path.read_text(encoding='utf8').replace(r.second_token,r.r.token)
            path.write_text(body,encoding='utf8');proof[name]=routing.file_ref(path)
    elif kind=='third_prefix':
        predecessor=json.loads(Path(proof['predecessor_carryover_ref']['path']).read_text(encoding='utf8'))
        predecessor['schema']='CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R2';predecessor['predecessor_carryover_ref']=proof['predecessor_carryover_ref']
        proof['predecessor_carryover_ref']=saved(a.g.tmp/'third_prefix.json',predecessor)
        old=json.loads(Path(proof['original_freeze_ref']['path']).read_text(encoding='utf8'));old['risk_fit_carryover_ref']=proof['predecessor_carryover_ref']
        proof['original_freeze_ref']=saved(Path(proof['original_freeze_ref']['path']),old)
    elif kind=='scope_cash':scope['initial_cash_usd']=2000
    elif kind=='scope_future':scope['test2026_read_authorized']=True
    elif kind=='slot_order':scope['stage2_receipt_refs'][0],scope['stage2_receipt_refs'][1]=scope['stage2_receipt_refs'][1],scope['stage2_receipt_refs'][0]
    elif kind=='failed_reason':
        ref=scope['original_failed_receipt_ref'];value=json.loads(Path(ref['path']).read_text(encoding='utf8'))
        value['failure']['type']='OTHER_FAILURE';changed=saved(Path(ref['path']),value)
        scope['original_failed_receipt_ref']=changed;scope['stage2_receipt_refs'][7]=changed
    else:
        contract=copy.deepcopy(a.contract);contract['no_new_risk_fit']=False
        a.route['execution_contract_ref']=saved(a.run/'changed_contract.json',contract)
        with pytest.raises(ValueError,match='CARRYOVER_EXECUTION_PROOF_CHANGED'):shim.validate(a.route,execute=True)
        return
    a.route['risk_fit_carryover_ref']=saved(a.g.tmp/'changed_two_prefix.json',proof)
    a.route['account_repair_ref']=saved(a.g.tmp/'changed_equal_scope.json',scope)
    with pytest.raises(ValueError):
        value=shim._risk_fit_carryover(a.route,a.run);shim._equal_repair_metadata(a.route,a.run,value)


def test_no_fit_private_policy_cache_hit_and_old_or_new_miss_before_worker(two_prefix_equal_repair,monkeypatch):
    r=two_prefix_equal_repair;a=r.a;g=a.g
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    connector=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=g.read,
        original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    runner,_=shim.bind_runner(a.route,a.freeze,native=g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=connector)
    calls=[]
    def forbidden(*args,**kwargs):calls.append(True);raise AssertionError('new physical fit forbidden')
    monkeypatch.setattr(routing.engine.values,'_fit_job',forbidden)
    policy=runner.make_policy(r.r.forecasts,r.r.returns,runner.joint.PolicyConfig('LW','equal_weight'),
        runner.cash.FeeConfig(),a.run,dict(fit_units=0),{},'SYNTHETIC_REPAIR')
    for date in ('2023-02-01','2023-03-01'):
        covariance,meta=policy._risk(pd.Timestamp(date),('A','B'));assert covariance.shape==(2,2)
    policy.risk_cache.clear();policy.monthly_state_keys.clear()
    for date in ('2023-02-01','2023-03-01','2023-04-01'):
        with pytest.raises(runner.NotTestable,match='NO_NEW_RISK_FIT_CACHE_MISS'):policy._risk(pd.Timestamp(date),('A','B'))
    with pytest.raises(ValueError,match='CANNOT_RUN_FULL_RECIPE'):runner.run_all(a.run)
    with pytest.raises(ValueError,match='ONLY_ORIGINAL_EQUAL_SLOT'):
        runner.evaluate_flow(a.run,'nnls_zero_abstain','LW','gmv',None,None,None,a.freeze,[],{})
    assert calls==[] and runner._routing_prior(a.run)==1295 and not (a.run/'FIT_LOG.jsonl').exists()


@pytest.mark.parametrize('result_status,score',[('COMPLETE',0.),('COMPLETE',2.),('NOT_TESTABLE',0.)])
def test_equal_repair_entry_reuses_selector_and_zero_fit_final_boundary(two_prefix_equal_repair,monkeypatch,result_status,score):
    # No market/model source is read: a finite generated one-date container and spies
    # exercise the exact C orchestration; real risk/cache/guard is covered above.
    r=two_prefix_equal_repair;a=r.a;calls=[];engine=routing.engine
    class Lock:
        def __enter__(self):return None
        def __exit__(self,*args):return False
    predictors=SimpleNamespace(fit_lock=lambda run:Lock(),contract=lambda *args:(None,{},None),
        reader_integrity=lambda *args:None)
    account_inputs=SimpleNamespace(metadata_preflight=lambda **kw:{'scope':{},'SOURCE_ONLY_TOY':True},
        load_account_inputs=lambda *args,**kw:{'market':SimpleNamespace(dates=pd.DatetimeIndex(['2023-02-01']))})
    def evaluate(*args,**kwargs):
        calls.append(('evaluate',args[1:4]));return dict(status=result_status,task_id=engine.TASK,
            flow_id=engine.flow_id('nnls_zero_abstain','LW','equal_weight',run=engine.fusion.CONTINUATION_RUN),risk_method='LW',allocation_method='equal_weight',
            fit_units=0,statistics=dict(mean_annual_cost_net_sharpe=score,total_turnover=1.),artifacts={})
    def freeze(*args):calls.append(('final',));return dict(status='COMPLETE',fit_units=0)
    runner=SimpleNamespace(contract=lambda run:(run,dict(account_source_scope_ref=a.route['reader_scope_ref'],recipe=a.route['original_routing_metadata']['recipe']),a.freeze),
        predictors=predictors,account_inputs=account_inputs,_routing_feature_origin=lambda run:Path('SYNTHETIC_ONLY'),
        ConsensusInputs=lambda *args:None,qualified_vectors=lambda *args:({},r.r.returns,None),
        pd=pd,BOUNDARY=engine.BOUNDARY,published_forecasts=lambda *args:(r.r.forecasts,[]),evaluate_flow=evaluate,
        select_best=engine.select_best,freeze_selected_risk=freeze,TASK=engine.TASK,write_json_atomic=lambda path,value:calls.append(('write',value)))
    monkeypatch.setattr(engine.joblib,'load',lambda *args:(_ for _ in ()).throw(AssertionError('old account must never load')))
    summary=shim.run_equal_weight_repair(runner,a.route,a.run)
    assert calls[0]==('evaluate',('nnls_zero_abstain','LW','equal_weight')) and len(summary['stage2'])==17
    assert summary['new_fit_units']==0 and summary['effective_prior_fit_units']==1295
    assert summary['old_account_state_reused'] is False and not (a.run/'FIT_LOG.jsonl').exists()
    if result_status=='NOT_TESTABLE':assert summary['status']=='REPAIR_NOT_COMPLETE_NO_TEST_USE' and summary['final_risk_receipt'] is None
    else:
        if score>1.:
            assert summary['status']=='CANDIDATE_UNTIL_REQUIRED_DIAGNOSTICS_NO_TEST_USE'
            assert summary['new_winner_requires_original_four_diagnostic_sensitivities'] is True
            assert len(summary['required_diagnostic_recipe'])==4 and ('final',) in calls and summary['selected_flow'].endswith('equal_weight')
        else:
            assert summary['status']=='COMPLETE' and ('final',) not in calls and summary['selected_flow'].endswith('OAS__cost_aware')
    assert routing.file_ref(r.old_failed['path'])==r.old_failed


@pytest.mark.parametrize('usable',[False,True])
def test_scalar_cash_projection_preserves_twenty_targets_and_entire_account(usable):
    import numpy as np
    cash=routing.engine.cash;engine=cash.engine;n=20;dates=pd.bdate_range('2024-02-01',periods=4)
    market=engine.MarketArrays(dates,[f'G{i:02}' for i in range(n)],np.full((4,n),10.),np.full((4,n),10.),adv=np.full((4,n),1e9))
    def policy(j,ctx):return engine.TargetDecision(np.full((1,n),.95/n),np.ones((1,n),bool),'SYNTHETIC_TWENTY_TARGETS')
    kwargs=dict(settlement_calendar=pd.bdate_range('2024-02-01',periods=12),usable_a=np.ones((4,n),bool) if usable else None)
    old=cash.run_cash_account(market,['generated'],policy,**kwargs)
    entry=shim._cash_invariant_diagnostic_entry(cash.run_cash_account);new=entry(market,['generated'],policy,**kwargs)
    assert entry.__code__ is cash.run_cash_account.__code__ and entry is not cash.run_cash_account
    for name in ('daily','fills','positions','orders','execution_results','settlement_ledger'):
        pd.testing.assert_frame_equal(getattr(new,name),getattr(old,name))
    assert new.audit==old.audit and new.daily.actual_name_count.max()==20 and new.daily.cash.min()>0
    lineage=new.metadata['source_lineage']['account_invariant_diagnostic']
    assert lineage['reverse_restoration_exact'] and lineage['original_predicate_unchanged']
    assert lineage['raise_replacement_count']==1 and lineage['allowed_scalar_fields']==list(shim.INVARIANT_SCALAR_FIELDS)


@pytest.mark.parametrize('kind',['cash','name'])
def test_scalar_cash_projection_original_rejected_account_stops_and_only_six_scalars(kind):
    import numpy as np
    cash=routing.engine.cash;engine=cash.engine;n=21;dates=pd.bdate_range('2024-02-01',periods=3)
    market=engine.MarketArrays(dates,[f'G{i:02}' for i in range(n)],np.full((3,n),10.),np.full((3,n),10.),adv=np.full((3,n),1e9))
    units=np.r_[np.ones(20),0.];seen=[]
    def hook(di,date,units,amount):
        units=units.copy();amount=amount.copy()
        if di==1:
            if kind=='cash':amount[:]=-1.
            else:units[:,-1]=1.
        return units,amount,np.zeros(1)
    def policy(j,ctx):seen.append(j);return engine.TargetDecision(np.zeros((1,n)),np.zeros((1,n),bool),'SYNTHETIC_KEEP')
    kwargs=dict(initial_units=units,settlement_calendar=pd.bdate_range('2024-02-01',periods=12),corporate_action_hook=hook)
    with pytest.raises(AssertionError,match='common cash/actual name invariant'):cash.run_cash_account(market,['generated'],policy,**kwargs)
    seen.clear();entry=shim._cash_invariant_diagnostic_entry(cash.run_cash_account)
    with pytest.raises(routing.engine.NotTestable) as caught:entry(market,['generated'],policy,**kwargs)
    reason=str(caught.value);assert reason.startswith(shim.INVARIANT_SCALAR_PREFIX)
    data=json.loads(reason[len(shim.INVARIANT_SCALAR_PREFIX):]);assert set(data)==set(shim.INVARIANT_SCALAR_FIELDS)
    assert data['cash_failure']==(kind=='cash') and data['name_failure']==(kind=='name')
    assert data['actual_name_max']==(20 if kind=='cash' else 21) and data['max_positions']==20
    assert data['pre2026_execution_date']=='2024-02-02' and seen==[0]
    assert all(not isinstance(value,(dict,list,tuple)) for value in data.values())


def test_scalar_cash_projection_future_date_refuses_metadata_before_scalar_read():
    class Unreadable:
        def __array__(self,*args):raise AssertionError('future arrays must not be read')
    with pytest.raises(ValueError,match='PRE2026_ONLY'):
        shim._account_invariant_scalar_exception(Unreadable(),Unreadable(),20,'2026-01-01',True,False)


def test_scalar_diagnostic_route_scope_and_private_cash_are_bound(two_prefix_equal_repair):
    r=two_prefix_equal_repair;a=r.a;scope=copy.deepcopy(r.scope)
    scope.update(original_execution_invariant_diagnostic_only=True,execution_invariant_original_error='common cash/actual name invariant',
        allowed_failure_scalar_fields=list(shim.INVARIANT_SCALAR_FIELDS),invariant_diagnostic_replay_only_semantics_unchanged=True,
        original_retained_assertion_predicate_unchanged=True,source_backed_stock_delivery_and_mechanical_exit_timing_unchanged=True)
    a.route.update(execution_invariant_scalar_diagnostic_authorized=True,account_repair_ref=saved(a.g.tmp/'scalar_scope.json',scope))
    a.contract=shim.execution_contract_template(a.route,research_id='SYNTHETIC_SCALAR_ONLY',
        managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    assert a.contract['execution_invariant_scalar_diagnostic_authorized'] is True
    a.route['execution_contract_ref']=saved(a.run/'scalar_contract.json',a.contract);a.freeze=saved(a.run/shim.CONTINUATION_FREEZE,a.route)
    assert shim.validate(a.route,execute=True)[0]==a.run
    proxy=shim.private_shareholder(a.route,a.g.facts,old_trp_fingerprints=[cf.trp_event().event_fingerprint],freeze_ref=a.freeze)
    guard=proxy.make_task_authority
    original=dict(zip(guard.__code__.co_freevars,(c.cell_contents for c in guard.__closure__)))['function']
    entry=original.__globals__['run_cash_account']
    assert entry is not routing.engine.cash.run_cash_account and entry.__code__ is routing.engine.cash.run_cash_account.__code__
    assert routing.engine.source_pins()['joint_policy']['sha256']==shim.JOINT_57_SHA
    scope['original_retained_assertion_predicate_unchanged']=False
    a.route['account_repair_ref']=saved(a.g.tmp/'bad_scalar_scope.json',scope)
    with pytest.raises(ValueError,match='ORIGINAL_GATE_DIAGNOSTIC_ONLY'):
        shim._equal_repair_metadata(a.route,a.run,shim._risk_fit_carryover(a.route,a.run))


def test_fresh_holder_consumer_namespace_and_r11_callback_injection_preserve_old_module():
    paths=shim.routing.resolve(shim.routing.engine.predictors.REPO)
    cache=paths.cache_root/'_maintenance'/shim.routing.engine.TASK/'source_repair/vendor_api_gap_completion'
    oldref=routing.file_ref(cache/'source_custody/consensus_account_source_private_consumer_c1c311795ff4687a93f69abccd3636f8b062135cfcc5f034202a063e68cf4f94.py')
    old=inputs.existing._load_python(oldref,'_synthetic_retained_C1_namespace')
    currentref=routing.file_ref(shim.__file__)
    current=inputs.existing._load_python(currentref,'_source192_root_reviewed_consumer_'+currentref['sha256'])
    callback=fixtures_module('_synthetic_fresh_r11_callback',cache/'assemble_private_account_callback_equal_invariant_scalar_no_new_fit_r11.py')
    callback.C=current
    assert current is not old and hasattr(current,'_cash_invariant_diagnostic_entry') and not hasattr(old,'_cash_invariant_diagnostic_entry')
    assert callback.CONSUMER_SHA==currentref['sha256'] and current.__file__==str(Path(shim.__file__))
    assert current.CANONICAL_ENGINE is old.CANONICAL_ENGINE and current.routing.engine._risk_worker is current.CANONICAL_ENGINE._risk_worker
    payload=dict(canonical_CA=current.inputs.existing.ca,removed_exact_original_keys=[])
    assert callback.assemble(payload,{},execute=False)['actual_account_run'] is False
    assert not hasattr(old,'_cash_invariant_diagnostic_entry')


@pytest.fixture
def method_matrix_carryover(two_prefix_equal_repair):
    """Two real synthetic risk bundles, with failed raw attempts spent to2063."""
    r=two_prefix_equal_repair;a=r.a;proof=copy.deepcopy(r.proof)
    coordinates=saved(a.g.tmp/'synthetic_matrix_coordinates.json',dict(coordinates=[
        dict(forecast_pack="core5__equal",risk_combination="LW",decision_method="cost_aware")]))
    scope=dict(schema="CONSENSUS_METHOD_MATRIX_EXTENSION_R1",status="AUTHORIZED_PRE2026_COMPARISON",
        task_id=routing.engine.TASK,research_id="CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12",
        output_run=str(a.run),selection_boundary_exclusive="2026-01-01",initial_cash=3000,
        prior_fit_units=2063,max_fit_units=10000,test2026_read_authorized=False,real_trades_authorized=False,
        old_account_state_reused=False,source_policy="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        matrix_coordinates_ref=coordinates,
        extension_source_ref=routing.file_ref(ROOT/'scripts/research/a2/evaluation/consensus_method_extension.py'))
    scope_ref=saved(a.g.tmp/'synthetic_matrix_scope.json',scope)
    review=dict(status="PASS_METADATA_CODE_ONLY",scope_ref=scope_ref,
        consumer_ref=a.route['consumer_owner_ref'],metadata_code_only=True,economic_PASS=False)
    rows=[json.loads(line) for line in Path(proof['risk_fit_log_ref']['path']).read_text(encoding='utf8').splitlines()]
    for i in range(384):
        token=routing.engine.values.digest(dict(synthetic_failed_attempt=i))
        rows.extend(dict(rows[j],reuse_tuple_sha256=token) for j in (0,1))
    for key in ('risk_fit_log_ref','original_fit_log_ref'):
        path=Path(proof[key]['path']);assert path.resolve().is_relative_to(a.g.tmp.resolve())
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf8')
        proof[key]=routing.file_ref(path)
    proof.update(schema="CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3",carried_fit_units=772,
        current_run_fit_units=770,effective_prior_fit_units=2063,log_started_tuple_count=386,
        method_matrix_scope_ref=scope_ref)
    a.route.update(method_matrix_scope_ref=scope_ref,
        method_matrix_admission_ref=saved(a.g.tmp/'synthetic_matrix_admission.json',review),
        risk_fit_carryover_ref=saved(a.g.tmp/'synthetic_matrix_carryover.json',proof),effective_prior_fit_units=2063,
        no_new_risk_fit=False,account_repair_ref=None,original_final_risk_receipt_ref=None)
    return SimpleNamespace(a=a,proof=proof,scope=scope,review=review,legacy=r,rows=rows)


def test_method_matrix_exact_scope_review_and_r3_budget_risk_only_cache(method_matrix_carryover,monkeypatch):
    r=method_matrix_carryover;a=r.a
    scope=shim._method_matrix_metadata(a.route,a.run,require_review=True)
    assert scope['research_id']=="CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12"
    assert (scope['prior_fit_units'],scope['max_fit_units'],scope['initial_cash'])==(2063,10000,3000)
    monkeypatch.setattr(routing.engine.joint.risk,'fit_risk_estimator',lambda *args,**kwargs:pytest.fail('carried state must not refit'))
    value=shim._risk_fit_carryover(a.route,a.run);cache=shim._carryover_risk_cache(value)
    assert value['schema']=="CONSENSUS_PRE2026_RISK_FIT_CARRYOVER_R3"
    assert value['effective_prior_fit_units']==2063 and len(value['started'])==772
    assert len(value['started_tokens'])==386 and len(cache)==2 and 'final_state' not in cache
    assert value['predecessor_carryover_ref']==r.legacy.proof['predecessor_carryover_ref']
    assert not (a.run/'FIT_LOG.jsonl').exists() and a.route['no_new_risk_fit'] is False


@pytest.mark.parametrize('field,value',[
    ('research_id','OLD_FIXED_WINNER_REPAIR'),('output_run','SYNTHETIC_WRONG_RUN'),
    ('selection_boundary_exclusive','2027-01-01'),('test2026_read_authorized',True),
    ('initial_cash',10000),('prior_fit_units',1295),('max_fit_units',12000),
    ('real_trades_authorized',True),('old_account_state_reused',True)])
def test_method_matrix_scope_rejects_identity_clock_cash_and_budget_drift(method_matrix_carryover,field,value,monkeypatch):
    r=method_matrix_carryover;a=r.a;scope=copy.deepcopy(r.scope);scope[field]=value
    a.route['method_matrix_scope_ref']=saved(a.g.tmp/'changed_matrix_scope.json',scope)
    monkeypatch.setattr(routing.engine.joblib,'load',lambda *a,**kw:pytest.fail('metadata rejection must precede numeric state decode'))
    with pytest.raises(ValueError):shim._method_matrix_metadata(a.route,a.run)


@pytest.mark.parametrize('kind',['missing','scope','consumer','metadata_only','economic','status','scope_hash'])
def test_method_matrix_independent_review_requires_exact_current_scope_and_consumer(method_matrix_carryover,kind):
    r=method_matrix_carryover;a=r.a;review=copy.deepcopy(r.review)
    if kind=='missing':a.route['method_matrix_admission_ref']=None
    elif kind=='scope_hash':
        a.route['method_matrix_scope_ref']=dict(a.route['method_matrix_scope_ref'],sha256='0'*64)
    else:
        if kind=='scope':review['scope_ref']=saved(a.g.tmp/'same_scope_other_path.json',r.scope)
        elif kind=='consumer':review['consumer_ref']=routing.file_ref(routing.__file__)
        elif kind=='metadata_only':review['metadata_code_only']=False
        elif kind=='economic':review['economic_PASS']=True
        else:review['status']='PLANNED'
        a.route['method_matrix_admission_ref']=saved(a.g.tmp/'changed_matrix_review.json',review)
    with pytest.raises(ValueError):shim._method_matrix_metadata(a.route,a.run,require_review=True)


def test_method_matrix_review_cannot_exist_without_named_scope(method_matrix_carryover):
    r=method_matrix_carryover;r.a.route['method_matrix_scope_ref']=None
    with pytest.raises(ValueError,match='MATRIX_REVIEW_WITHOUT_SCOPE'):
        shim._method_matrix_metadata(r.a.route,r.a.run)


def test_method_matrix_r3_formal_contract_is_new_fit_scope_not_equal_repair(method_matrix_carryover):
    r=method_matrix_carryover;a=r.a
    a.contract=shim.execution_contract_template(a.route,research_id=r.scope['research_id'],
        managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    assert a.contract['method_matrix_scope_ref']==a.route['method_matrix_scope_ref']
    assert a.contract['method_matrix_admission_ref']==a.route['method_matrix_admission_ref']
    assert a.contract['no_new_risk_fit'] is False and a.contract['account_repair_ref'] is None
    assert a.contract['effective_prior_fit_units']==2063 and a.contract['old_account_state_reused'] is False
    a.route['execution_contract_ref']=saved(a.run/'matrix_execution_contract.json',a.contract)
    a.freeze=saved(a.run/shim.CONTINUATION_FREEZE,a.route)
    assert shim.validate(a.route,execute=True)[0]==a.run


@pytest.mark.parametrize('kind',['matrix_missing','matrix_ref','fake_old_no_fit','old_repair','total','current_count','tuple_count'])
def test_method_matrix_r3_carryover_rejects_unbound_scope_old_no_fit_and_wrong_counts(method_matrix_carryover,kind):
    r=method_matrix_carryover;a=r.a;proof=copy.deepcopy(r.proof)
    if kind=='matrix_missing':a.route['method_matrix_scope_ref']=None;a.route['method_matrix_admission_ref']=None
    elif kind=='matrix_ref':proof['method_matrix_scope_ref']=r.legacy.a.route['reader_scope_ref']
    elif kind=='fake_old_no_fit':a.route['no_new_risk_fit']=True
    elif kind=='old_repair':a.route['account_repair_ref']=saved(a.g.tmp/'pretended_old_repair.json',r.legacy.scope)
    elif kind=='total':proof['carried_fit_units']=770
    elif kind=='current_count':proof['current_run_fit_units']=772
    else:proof['log_started_tuple_count']=385
    a.route['risk_fit_carryover_ref']=saved(a.g.tmp/'bad_matrix_carryover.json',proof)
    with pytest.raises(ValueError):shim._risk_fit_carryover(a.route,a.run)


def test_method_matrix_scope_prior_must_equal_independently_proven_prefix_total(method_matrix_carryover):
    r=method_matrix_carryover;a=r.a;proof=copy.deepcopy(r.proof)
    # Both pinned raw prefixes and their totals are internally correct at1295;
    # only the independently frozen matrix requires2063. Neither authority may
    # silently overrule the other or discard the intervening spent attempts.
    for key in ('risk_fit_log_ref','original_fit_log_ref'):
        path=Path(proof[key]['path']);path.write_text(''.join(json.dumps(row)+'\n' for row in r.rows[:2]),encoding='utf8')
        proof[key]=routing.file_ref(path)
    proof.update(carried_fit_units=4,current_run_fit_units=2,effective_prior_fit_units=1295,log_started_tuple_count=2)
    a.route.update(effective_prior_fit_units=1295,
        risk_fit_carryover_ref=saved(a.g.tmp/'truncated_matrix_prior.json',proof))
    with pytest.raises(ValueError):shim._risk_fit_carryover(a.route,a.run)


def synthetic_matrix_guarded_evaluation(run,method,risk_method,allocation_method,cache,freeze_ref,*,diagnostic=None):
    if allocation_method in SCENARIO_METHODS:
        return {"status":"blanket NOT_TESTABLE must be replaced before account qualification"}
    receipt=dict(status="IN_PROGRESS")
    policy=make_policy()
    if any(d.get("status")=="NOT_TESTABLE_RISK_PRESERVE_UNITS" for d in policy.diagnostics):
        return dict(receipt,status="NOT_TESTABLE")
    return dict(receipt,status="SYNTHETIC_COMPLETE",risk_cache_entries=len(cache),
        flow_id=flow_id(method,risk_method,allocation_method,run=run))


def test_method_matrix_reprojection_reapplies_actual_C_route_reader_and_cache_guard(method_matrix_carryover):
    from scripts.research.a2.evaluation import consensus_method_extension as extension
    r=method_matrix_carryover;a=r.a
    a.contract=shim.execution_contract_template(a.route,research_id=r.scope['research_id'],
        managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    a.route['execution_contract_ref']=saved(a.run/'matrix_guard_execution_contract.json',a.contract)
    freeze=saved(a.run/shim.CONTINUATION_FREEZE,a.route)
    coordinate=extension.Coordinate("core5__equal","LW","cost_aware")
    binding=SimpleNamespace(matrix_coordinate=asdict(coordinate),matrix_scope=r.scope)
    cache_context={};calls=[];guards=[]
    def protect(function):
        guards.append(function)
        return shim._guarded_execution(a.route,function,cache_context=cache_context)
    runner=SimpleNamespace(evaluate_flow=shim._guarded_execution(a.route,synthetic_matrix_guarded_evaluation),
        _matrix_evaluation_source=synthetic_matrix_guarded_evaluation,_matrix_execution_guard=protect)
    def factory():calls.append("policy");return SimpleNamespace(diagnostics=[])
    def evaluate(run,cache,freeze_ref=freeze):
        return extension.evaluate_flow(runner,coordinate,run,"core5__equal","LW","cost_aware",cache,freeze_ref,
            binding=binding,make_policy=factory)
    cache={}
    with pytest.raises(ValueError,match="WRONG_OUTPUT_RUN"):
        evaluate(a.run.parent/'SYNTHETIC_WRONG_RUN',cache)
    assert calls==[] and cache=={}
    result=evaluate(a.run,cache)
    assert result['status']=="SYNTHETIC_COMPLETE" and result['matrix_coordinate']==asdict(coordinate)
    assert result['risk_cache_entries']==len(cache)==2 and 'final_state' not in cache
    assert result['flow_id']=="matrix__"+coordinate.identity and calls==["policy"]
    with pytest.raises(ValueError,match="SHARED_RISK_CACHE_INSTANCE_CHANGED"):evaluate(a.run,{})
    with pytest.raises(ValueError,match="NEW_AUTHORITY_FREEZE_AND_READER"):
        evaluate(a.run,cache,{'path':'synthetic://wrong-freeze','sha256':'0'*64})
    assert calls==["policy"] and len(guards)==4
    assert not (a.run/'FIT_LOG.jsonl').exists()


def test_method_matrix_actual_bind_runner_exposes_original_E_and_rejects_before_raw_account(method_matrix_carryover):
    from scripts.research.a2.evaluation import consensus_method_extension as extension
    r=method_matrix_carryover;a=r.a;g=a.g
    a.contract=shim.execution_contract_template(a.route,research_id=r.scope['research_id'],
        managed_run_config_ref=a.contract['managed_run_config_ref'],managed_input_manifest_ref=a.contract['managed_input_manifest_ref'])
    a.route['execution_contract_ref']=saved(a.run/'matrix_bound_execution_contract.json',a.contract)
    freeze=saved(a.run/shim.CONTINUATION_FREEZE,a.route)
    expected=shim.expected_projection(a.route['expected_freeze_ref'],source_roles=a.route['source_roles'])
    connector=shim.source_connector(expected,qualified_fx=g.fx,pin=lambda *args:None,read=g.read,
        original_source_kwargs_ref=g.origin,source_roles=a.route['source_roles'])
    runner,_=shim.bind_runner(a.route,freeze,native=g.facts,
        old_trp_fingerprints=[cf.trp_event().event_fingerprint],connector=connector)
    assert callable(runner._matrix_evaluation_source) and callable(runner._matrix_execution_guard)
    assert runner._matrix_evaluation_source is not runner.evaluate_flow
    assert runner._matrix_evaluation_source.__globals__['shareholder'] is runner.shareholder
    coordinate=extension.Coordinate("core5__equal","LW","cost_aware")
    binding=SimpleNamespace(matrix_coordinate=asdict(coordinate),matrix_scope=r.scope)
    with pytest.raises(ValueError,match="PRIVATE_CONSUMER_WRONG_OUTPUT_RUN"):
        extension.evaluate_flow(runner,coordinate,a.run.parent/'SYNTHETIC_WRONG_RUN',"core5__equal","LW","cost_aware",
            None,None,None,freeze,[],{},binding=binding,
            make_policy=lambda *a:pytest.fail("original E account must not be reached after C rejection"))
    assert not (a.run/'FIT_LOG.jsonl').exists()
