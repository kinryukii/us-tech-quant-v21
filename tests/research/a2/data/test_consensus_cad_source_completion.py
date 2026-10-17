"""Generated CAD source/FX/quote fixtures only; no actual financial data reads."""
import copy
from dataclasses import asdict, replace
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.data import consensus_cad_source_completion as c
from scripts.research.a2.data import consensus_account_inputs as inputs
from scripts.research.a2.evaluation import consensus_shareholder_account as shareholder


def write(path, value):
    path.write_bytes(value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False)+'\n').encode())
    return c.file_ref(path)


def source_fixtures(tmp_path, monkeypatch, keys=None):
    old={};sources=[];packets=[];calendar=pd.bdate_range('2023-01-01','2025-12-31')
    for i,key in enumerate(c.ORIGINAL_THREE_KEYS if keys is None else keys):
        case=c.CASES[key]
        folder=tmp_path/str(i);folder.mkdir()
        literal=('Dividend: Our board of directors declared a 2023 annual dividend of $0.12 per common share, payable on December 15, 2023, to shareholders of record on November 30, 2023. In 2022, the board increased the dividend by 50%.' if key[0]=='CCJ' else 'The Board of Directors has approved a quarterly dividend of $0.545 per share on its common shares, payable to shareholders of record.')
        if key==('CCJ','2024-11-27'):literal='Our board of directors declared a 2024 annual dividend of $0.16 per common share, payable on December 13, 2024, to shareholders of record on November 27, 2024. Prior 2023 annual dividend was $0.12; future policy reference $0.24 is not this payment.'
        cash=('<p>'+literal+'</p>').encode();currency=('<p>'+case['currency_literal']+'</p>').encode();primary=currency+cash
        local=pd.Timestamp(case['accepted']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+case['accession']+'\nCENTRAL INDEX KEY: '+str(case['cik'])+'\n<DOCUMENT>').encode();header+=b' '*(65536-len(header))
        hr=write(folder/'header.bin',header);pr=write(folder/'primary.htm',primary);full=write(folder/'full.txt',header+primary);cr=write(folder/'cash.html',cash);ur=write(folder/'currency.html',currency)
        identity=dict(raw_security_id=case['sid'],original_source_row=dict(ticker=key[0],cusip=case['cusip'],security_id=case['cusip'],security_id_type='CUSIP',title_of_class=case['title']),identity_links=[dict(signal_date=d,security_uid='CUSIP:'+case['cusip'],accounting_sid=case['sid'],ticker=key[0]) for d in (case['prior'],key[1])])
        event=dict(original_primary_ref=pr,actual_HEADER_ref=hr,original_current_fragment=dict(ref=cr,original_byte_range=[len(currency),len(primary)],original_complete_native_spacejoin_literal=literal),original_announcement_currency_definition=dict(ref=ur,original_byte_range=[0,len(currency)],document_level_before_current=True,financial_table_or_caption=False,USD_or_other_currency_override_inside_current=False,original_announcement_masthead_layout_proof=dict(cash_paragraph_outside_after_header_table=True)),original_frozen_identity_metadata=identity)
        old[key]=event
        cap=write(folder/'capture.json',dict(response_status=200,actual_HTTP_status_observed=True,response_url=f"https://www.sec.gov/Archives/edgar/data/{case['cik']}/{case['accession']}.txt",original_HTTP_ref=full,old_HTTP_status_remains_UNKNOWN=True))
        packet=dict(ticker=key[0],ex_date=key[1],declared_currency='CAD',amount_unit=c.ca.CAD_PER_RAW_OLD_SHARE,quantity_coordinate=c.ca.RAW_OLD_SHARE_COORDINATE,old_primary_ref=pr,old_HEADER_ref=hr,new_full_ref=full,old_full_ref=full,capture_ref=cap,record_date=case['record'],pay_date=case['pay'],identity=copy.deepcopy(identity),packet_ref=write(folder/'source_only_packet.json',dict(schema='SYNTHETIC_ONLY')),physical_bindings=[dict(role=role,old_fragment_ref=r,old_primary_byte_range=span,new_full_submission_byte_range=[65536+span[0],65536+span[1]]) for role,r,span in [('currency',ur,[0,len(currency)]),('cash',cr,[len(currency),len(primary)])]])
        packets.append(packet)
    monkeypatch.setattr(c,'_material_event',lambda key:old[key])
    sources=[c.qualify_source(p,calendar=calendar) for p in packets]
    return sources,packets,old,calendar


def mark(day,available,ref,value=1.2):
    return c.ca.SourceBackedFXMark('CAD',c.ca.CAD_PER_USD,day,available,value,ref['path'],ref['sha256'])


def fx_fixtures(tmp_path,monkeypatch,sources):
    edition=write(tmp_path/'generated_official_edition.html',b'Generated CAD row; no actual rates')
    old=[mark(str(d.date()),str((d+pd.Timedelta(days=7,hours=23,minutes=59,seconds=59)).tz_localize('America/New_York').tz_convert('UTC')),edition) for d in pd.bdate_range('2024-12-16',periods=258)]
    early=[mark(d,'2023-11-28T04:59:59+00:00',edition) for d in ('2023-11-20','2023-11-21','2023-11-22','2023-11-24')]+[mark(d,'2024-05-29T03:59:59+00:00',edition) for d in ('2024-05-20','2024-05-21','2024-05-22','2024-05-23','2024-05-24')]+[mark(d,'2024-08-27T03:59:59+00:00',edition) for d in ('2024-08-19','2024-08-20','2024-08-21','2024-08-22','2024-08-23')]
    oldref=write(tmp_path/'old258.json',dict(observations=[asdict(m) for m in old],unselected_financial_field='MUST_NOT_BE_DECODED'));earlyref=write(tmp_path/'early14.json',dict(observations=[asdict(m) for m in early]));qualref=write(tmp_path/'qualification.json',dict(status='SYNTHETIC_ORIGINAL_PARSER_QUALIFIED_14'))
    monkeypatch.setattr(c,'OLD_FX_REF',oldref);monkeypatch.setattr(c,'EARLY_FX_REF',earlyref);monkeypatch.setattr(c,'EARLY_FX_QUAL_REF',qualref)
    fx=c.qualify_fx_marks(old,early,sources=sources)
    return fx,old,early


def prior(source):
    case=c.CASES[source.key]
    return dict(ticker=source.key[0],trade_date=case['prior'],security_uid='CUSIP:'+case['cusip'],security_id=case['sid'],price_currency='USD',price_coordinate='RAW_CLOSE',quantity_coordinate=c.ca.RAW_OLD_SHARE_COORDINATE,source_coordinate='RAW_ACTUAL_SHARE',same_prior_ex_UID_and_SID=True,share_quantity_effect=False,raw_close=50.,source_fingerprint='a'*64)


def native(source,fx,p=None):
    return c.qualify_native(source,prior(source) if p is None else p,fx,fx_book_refs={'old':c.OLD_FX_REF,'early':c.EARLY_FX_REF,'early_qualification':c.EARLY_FX_QUAL_REF})


def old_events():
    events=[]
    for i,d in enumerate(pd.bdate_range('2023-01-02',periods=150)):
        events.append(c.ca.SourceBackedEntitlementEvent(event_id='SYNTHETIC_105_PLUS45_'+str(i),action_type='CASH_DIVIDEND',old_security_id='SYNTHETIC_DATED_COMMON_'+str(i),ticker='SYN'+str(i),ex_date=str(d.date()),record_date=str(d.date()),pay_date=str((d+pd.Timedelta(days=3)).date()),available_at='2022-12-31T00:00:00Z',cash_per_old_share=.3,currency='USD',amount_unit=c.ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=c.ca.RAW_OLD_SHARE_COORDINATE,source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',source_reference='generated source',source_fingerprint='b'*64))
    return tuple(events)


def trp_event():
    return c.ca.SourceBackedForeignCashEvent(event_id='GENERATED_OLD_TRP',action_type='CASH_DIVIDEND',old_security_id='FROZEN_RAW_TRANSPORT_CODE:US.TRP',ticker='TRP',ex_date='2025-03-31',record_date='2025-03-31',pay_date='2025-04-30',available_at='2025-02-14T11:42:10Z',cash_per_old_share=.85,currency='CAD',amount_unit=c.ca.CAD_PER_RAW_OLD_SHARE,quantity_coordinate=c.ca.RAW_OLD_SHARE_COORDINATE,source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',source_reference='generated old TRP source',source_fingerprint='c'*64)


def test_roundtrip_three_source_types_native_original_math_and_old258_plus14(tmp_path,monkeypatch):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);facts=[native(s,fx) for s in sources]
    assert len(facts)==3 and fx.proof['old_count']==258 and fx.proof['early_count']==14 and len(fx.marks)==272
    assert all(a is b for a,b in zip(oldmarks,fx.marks)) and all(n.source.event.currency=='CAD' and n.proof['declared_CAD_amount_was_not_relabelled_USD'] for n in facts)
    assert facts[0].source.receipt['frequency_original']=='annual' and all(n.proof['cash_fraction_in_USD']<.25 for n in facts)
    assert all(c.ca.SourceBackedForeignCashEvent(**asdict(n.source.event)).event_fingerprint==n.source.event.event_fingerprint for n in facts)
    assert c.cash.SPEC['small_cash_fraction_strict_upper_bound']==.25 and c._r6_fraction_check(.24,1)==.24
    assert c.ca.foreign_claim_value_usd is inputs.existing.ca.foreign_claim_value_usd


@pytest.mark.parametrize('kind',['currency','unit','coordinate','UID','SID','class','record','pay','HTTP','header','current_fragment','currency_fragment','whole_version','unknown_key'])
def test_source_gate_rejects_wrong_currency_identity_transport_words(tmp_path,monkeypatch,kind):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);p=copy.deepcopy(packets[0])
    if kind in ('currency','unit','coordinate','record','pay'):p[{'currency':'declared_currency','unit':'amount_unit','coordinate':'quantity_coordinate','record':'record_date','pay':'pay_date'}[kind]]='WRONG'
    elif kind in ('UID','SID','class'):p['identity']['identity_links'][0]['security_uid']='CUSIP:WRONG' if kind=='UID' else p['identity']['identity_links'][0]['security_uid'];p['identity']['raw_security_id']='US.CCJ' if kind=='SID' else p['identity']['raw_security_id'];p['identity']['original_source_row']['title_of_class']='COM' if kind=='class' else p['identity']['original_source_row']['title_of_class']
    elif kind=='HTTP':p['capture_ref']=write(tmp_path/'wrong_capture.json',dict(response_status=None,actual_HTTP_status_observed=False,response_url='wrong',original_HTTP_ref=p['new_full_ref'],old_HTTP_status_remains_UNKNOWN=True))
    elif kind=='header':p['old_HEADER_ref']=write(tmp_path/'wrong_header.txt',b'changed')
    elif kind=='whole_version':p['old_full_ref']=write(tmp_path/'changed_full.txt',b'changed')
    elif kind=='unknown_key':p['ex_date']='2024-11-27'
    else:p['physical_bindings'][0 if kind=='currency_fragment' else 1]['old_fragment_ref']=write(tmp_path/'wrong_fragment.html',b'changed')
    with pytest.raises(ValueError):c.qualify_source(p,calendar=cal)


@pytest.mark.parametrize('kind',['late_only','empty','wrong_mark_payload','conflicting_version','wrong_book_ref','wrong_UID','wrong_currency','wrong_unit','strict25','source_receipt_changed'])
def test_source_FX_native_no_choice_and_strict_boundary(tmp_path,monkeypatch,kind):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);s=sources[0];p=prior(s)
    if kind=='wrong_mark_payload':
        changed=list(early);changed[0]=replace(changed[0],currency_per_usd=1.4)
        with pytest.raises(ValueError,match='EACH_PINNED_BOOK'):c.qualify_fx_marks(oldmarks,changed,sources=sources)
        return
    if kind=='conflicting_version':
        with pytest.raises(ValueError,match='AMBIGUOUS'):c.merge_fx_marks(oldmarks,(replace(oldmarks[0],currency_per_usd=1.4),))
        return
    if kind in ('late_only','empty'):
        records=[] if kind=='empty' else [asdict(oldmarks[0])];r=write(tmp_path/'unavailable_early.json',dict(observations=records));monkeypatch.setattr(c,'EARLY_FX_REF',r);fx=c.qualify_fx_marks(oldmarks,() if kind=='empty' else (oldmarks[0],),sources=sources)
    elif kind=='wrong_book_ref':fx=replace(fx,proof=dict(fx.proof,early_book_ref=c.OLD_FX_REF))
    elif kind=='wrong_UID':p['security_uid']='CUSIP:OTHER'
    elif kind=='wrong_currency':p['price_currency']='CAD'
    elif kind=='wrong_unit':p['quantity_coordinate']='ADJUSTED_SHARE'
    elif kind=='strict25':p['raw_close']=.4
    elif kind=='source_receipt_changed':s=replace(s,receipt=dict(s.receipt,source_available_at='WRONG'))
    with pytest.raises(ValueError):native(s,fx,p)


def test_original_no_choice_merger_keeps_105_plus45_TRP_and_explicitFX(tmp_path,monkeypatch):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);facts=[native(s,fx) for s in sources];events=old_events()+(trp_event(),);before=[asdict(e) for e in events]
    combined=dict(entitlement_events=events,entitlement_security_tickers={e.old_security_id:e.ticker for e in events},unsupported_events=(),entitlement_source_binding=dict(manifest={},source_fingerprint='d'*64),research_account_authority={},foreign_fx_marks=tuple(oldmarks))
    result=c.merge_cad_completion(combined,facts,manifest_ref=write(tmp_path/'manifest.json',dict(schema='SYNTHETIC')),qualified_fx=fx)
    assert len(result['entitlement_events'])==154 and [asdict(e) for e in combined['entitlement_events']]==before
    assert {e.event_fingerprint for e in events}<={e.event_fingerprint for e in result['entitlement_events']} and all(a is b for a,b in zip(oldmarks,result['foreign_fx_marks'])) and len(result['foreign_fx_marks'])==272
    conflicting=dict(combined,entitlement_events=events+(replace(facts[0].source.event,cash_per_old_share=.13),))
    with pytest.raises(ValueError,match='CONFLICT_NO_CHOICE'):c.merge_cad_completion(conflicting,facts,manifest_ref=c.MATERIAL_REF,qualified_fx=fx)


def stub_authority_sources(monkeypatch):
    monkeypatch.setattr(shareholder,'_validate_source_completion_scopes',lambda a:None);monkeypatch.setattr(shareholder,'_validate_foreign_cash_scopes',lambda a:None);monkeypatch.setattr(shareholder,'_metadata_ref',lambda *a,**kw:None)


def authority(ns,events):
    r=dict(path='D:/synthetic/source.json',sha256='e'*64)
    return ns.make_task_authority(events,frozen_contract_ref=r,source_scope_ref=r,market_source_binding=dict(task_id=c.TASK,quantity_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',source_refs=[r],coverage_gaps=[]),continuation_scope_ref=r,account_convention_scope_ref=r,account_fx_convention_scope_ref=r,fx_source_availability_qualification_ref=r)


def test_private_exact_scope_two_entries_and_input_hook_business_identity(tmp_path,monkeypatch):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);facts=[native(s,fx) for s in sources];trp=trp_event();stub_authority_sources(monkeypatch);ns=c.private_shareholder_namespace(facts,old_trp_fingerprints=[trp.event_fingerprint]);events=(trp,)+tuple(n.source.event for n in facts);a=authority(ns,events)
    assert ns.validate_task_authority(events,a)['event_fingerprints']==sorted(e.event_fingerprint for e in events)
    assert ns.make_task_authority.__globals__['validate_task_authority'] is ns.validate_task_authority and ns.run_shareholder_cash_account.__globals__['validate_task_authority'] is ns.validate_task_authority
    assert ns.make_task_authority.__code__ is shareholder.make_task_authority.__code__ and ns.run_shareholder_cash_account.__code__ is shareholder.run_shareholder_cash_account.__code__ and ns.cad_projection_lineage['other_authority_business_AST_unchanged'] is True
    with pytest.raises(ValueError,match='TRP_COMMON_SCOPE'):authority(ns,(replace(facts[0].source.event,cash_per_old_share=.13),))
    with pytest.raises(ValueError,match='TRP_COMMON_SCOPE'):authority(ns,(replace(trp,cash_per_old_share=.9),))
    calls=[]
    def original_load():return account, _routing_connect_supplements('generated')
    def original_hook(*args):calls.append(args);return {'old':105+45}, {'source':'old'}
    original_load=type(original_load)(original_load.__code__,{'account':shareholder,'_routing_connect_supplements':original_hook})
    base=SimpleNamespace(load_account_inputs=original_load,_routing_connect_supplements=original_hook,account=shareholder)
    projected=c.private_input_namespace(base,ns,lambda value:dict(value,CAD=3));account_ns,(result,composition)=projected.load_account_inputs()
    assert account_ns is ns and projected.load_account_inputs.__code__ is base.load_account_inputs.__code__ and result==dict(old=150,CAD=3) and calls and base.account is shareholder


def test_windows_spawn_rebuilds_same_code_and_existing_CAD_class(tmp_path):
    event=trp_event();ctx=mp.get_context('spawn');queue=ctx.Queue();source=c.file_ref(c.__file__);process=ctx.Process(target=c.spawn_engineering_identity,args=(queue,source,[asdict(event)]));process.start()
    try:
        result=queue.get(timeout=45);process.join(timeout=10);assert process.exitcode==0 and result['source_ref']==source and result['typed_fingerprints']==[event.event_fingerprint] and result['event_terms']==[asdict(event)] and result['numeric_data_read'] is False and result['account_or_fit_run'] is False
    finally:
        if process.is_alive():process.terminate();process.join(timeout=10)
        queue.close()


def test_engineering_capsule_and_protected_code_pins_no_execution():
    p=c.engineering_capsule(source_owner_ref=c.file_ref(c.__file__),test_ref=c.file_ref(__file__))
    assert p['status']==c.ENGINEERING and p['required_actual_SOURCE_HTTP200_count']==4 and p['actual_SOURCE_native_RAW_FX_numeric_account_or_2026_authorized'] is False and p['prior_fit_units']==1291 and len(p['exact_keys'])==4

@pytest.mark.parametrize('mutation',[None,'reason','source_reference','source_fingerprint','date','extra_field','missing_field','native_proof','duplicate','wrong_original_ref'])
def test_exact_original_fivefield_resolution_and_original_no_choice_merge(tmp_path,monkeypatch,mutation):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch);fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);facts=[native(s,fx) for s in sources]
    records=[dict(ticker=s.key[0],effective_date=s.key[1],reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='synthetic-original-binding',source_fingerprint=('a','b','c')[i]*64) for i,s in enumerate(sources)]
    origin=write(tmp_path/'original.json',{'synthetic':True});monkeypatch.setattr(c,'ORIGINAL_KWARGS_REF',origin)
    metadata=write(tmp_path/'original_records.json',dict(status='PASS_EXACT_ORIGINAL7_PREDECODE_AUTHORITY_AND_THREE_FIVEFIELD_METADATA',original_kwargs_ref=origin,records=[dict(key=list(s.key),original_record=r,original_record_key=inputs.existing.source._key(r)) for s,r in zip(sources,records)]));monkeypatch.setattr(c,'ORIGINAL_BLOCKERS_REF',metadata)
    retained=dict(records[0],ticker='OTHER');original=dict(corporate_actions=(),corporate_action_known_at={},unsupported_events=tuple(records+[retained]),entitlement_enabled=True,entitlement_events=old_events()+(trp_event(),),entitlement_security_tickers={},entitlement_source_binding=dict(manifest={},source_fingerprint='d'*64))
    original_ref=origin
    if mutation in ('reason','source_reference','source_fingerprint'):original['unsupported_events'][0][mutation]='CHANGED'
    elif mutation=='date':original['unsupported_events'][0]['effective_date']='2023-11-28'
    elif mutation=='extra_field':original['unsupported_events'][0]['extra']='CHANGED'
    elif mutation=='missing_field':original['unsupported_events'][0].pop('reason')
    elif mutation=='native_proof':facts[0].proof['event_fingerprint']='0'*64
    elif mutation=='duplicate':original['unsupported_events']+= (dict(records[0]),)
    elif mutation=='wrong_original_ref':original_ref=dict(origin,sha256='0'*64)
    if mutation is not None:
        with pytest.raises(ValueError,match='CAD_'):c.qualify_original_records(original,facts,original_ref=original_ref)
        return
    resolution=c.qualify_original_records(original,facts,original_ref=original_ref)
    combined=dict(original,research_account_authority={},foreign_fx_marks=tuple(oldmarks));before=[asdict(e) for e in combined['entitlement_events']]
    result=c.merge_cad_completion(combined,facts,manifest_ref=metadata,qualified_fx=fx,original_resolution=resolution)
    assert result['unsupported_events']==(retained,) and len(result['entitlement_events'])==154
    assert [asdict(e) for e in combined['entitlement_events']]==before and len(combined['unsupported_events'])==4
    assert all(a is b for a,b in zip(oldmarks,result['foreign_fx_marks'])) and len(result['foreign_fx_marks'])==272
    resolution['proof']['removed_exact_original_keys'][0]['reason']='CHANGED';resolution['proof_sha256']=c.digest(resolution['proof'])
    with pytest.raises(ValueError,match='CAD_EXACT_NATIVE_ORIGINAL_RESOLUTION_CHANGED'):c.merge_cad_completion(combined,facts,manifest_ref=metadata,qualified_fx=fx,original_resolution=resolution)


@pytest.mark.parametrize('mutation',[None,'year','current_amount','record','pay','SID','USD','cash_byte_tamper'])
def test_fourth_CCJ_annual_current_exact_scope_no_old_amount_or_quarter_inference(tmp_path,monkeypatch,mutation):
    sources,packets,old,cal=source_fixtures(tmp_path,monkeypatch,keys=[('CCJ','2024-11-27')]);s=sources[0];p=packets[0];case=c.CASES[s.key]
    assert s.event.currency=='CAD' and s.receipt['frequency_original']=='annual' and s.event.cash_per_old_share==.16
    if mutation is None:
        fx,oldmarks,early=fx_fixtures(tmp_path,monkeypatch,sources);n=native(s,fx);assert n.proof['strict_upper_bound']==.25 and n.source.event.currency=='CAD'
        ns=c.private_shareholder_namespace([n],old_trp_fingerprints={trp_event().event_fingerprint});assert ns.cad_projection_lineage['other_authority_business_AST_unchanged'] and ns.make_task_authority.__code__ is shareholder.make_task_authority.__code__
        return
    if mutation in ('year','current_amount'):
        modified=dict(case);modified['amount']='0.24' if mutation=='current_amount' else case['amount'];monkeypatch.setitem(c.CASES,s.key,modified)
        if mutation=='year':
            monkeypatch.setitem(c.CASES,('CCJ','2024-11-27'),dict(modified,record='2023-11-30'))
    elif mutation in ('record','pay'):p[mutation+'_date']='2024-12-12'
    elif mutation=='SID':p['identity']['raw_security_id']='US.CCJ'
    elif mutation=='USD':p['declared_currency']='USD'
    elif mutation=='cash_byte_tamper':Path(old[s.key]['original_current_fragment']['ref']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='CAD_'):c.qualify_source(p,calendar=cal)
