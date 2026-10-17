"""Synthetic SOURCE-only bounds; no credentials, network, quotes or outcomes."""
from datetime import datetime
import json
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.data import consensus_rl_source_2021_2022 as source
from scripts.storage import massive_dividend_sources as original


def row(day='2021-06-01',**changes):
    value=dict(ticker='A',ex_dividend_date=day,declaration_date='2021-05-01',
        record_date=day,pay_date='2021-06-15',currency='USD',cash_amount=.25,id='one',
        distribution_type='recurring',split_adjusted_cash_amount=999,historical_adjustment_factor=999)
    value.update(changes);return value


def body(rows):return json.dumps(dict(status='OK',results=rows)).encode()


def project(rows,targets=None):
    return source.project_dividends(body(rows),ticker='A',start_date='2021-01-01',
        end_date='2022-12-31',target_dates=targets or ['2021-06-01'])


def test_private_scope_retains_original_capture_and_exact_components():
    a=row();b=row(id='two',cash_amount=.50,distribution_type='special')
    result=project([row('2021-03-01',id='ignored'),a,b])
    assert [r['id'] for r in result['records']]==['one','two']
    assert result['outside_exact_target_numeric_rows_decoded']==0
    assert not result['native_qualified'] and not result['strict_PIT']
    assert not any(k in result['records'][0] for k in original.EXCLUDED)
    with pytest.raises(ValueError,match='VENDOR_PRE2026_WINDOW'):
        original.project_dividends(body([a]),ticker='A',start_date='2021-01-01',end_date='2022-12-31',target_dates=['2021-06-01'])


@pytest.mark.parametrize('changes,reason',[
    ({'declaration_date':None},'MISSING_OR_INVALID'),
    ({'declaration_date':'2021-06-02'},'ORDER_INVALID'),
    ({'pay_date':'2023-01-15'},'FUTURE_PAY'),
    ({'currency':'CAD'},'NON_USD'),
    ({'available_at':'2023-01-01T00:00:00Z'},'INELIGIBLE_AVAILABLE'),
    ({'reward_mature_at':'2023-01-01'},'INELIGIBLE_REWARD'),
])
def test_ineligible_metadata_rejects_before_monetary_fields(monkeypatch,changes,reason):
    old=source._JsonProjection.metadata_fields
    def checked(self,names):
        assert set(names)!=original.FIELDS, 'numeric decoder entered before eligibility'
        return old(self,names)
    monkeypatch.setattr(source._JsonProjection,'metadata_fields',checked)
    result=project([row(**changes)])
    assert result['records']==[] and reason in result['rejected_target_metadata'][0]['reason']


def test_unexpected_ticker_or_future_ex_rejects_before_any_cash_decode():
    for wrong in (row(ticker='B'),row('2026-06-01')):
        with pytest.raises(ValueError,match='NO_NUMERIC_DECODE'):
            project([row(),wrong])


def synthetic_scope(tmp_path):
    pool=tmp_path/'pool.parquet';binding=tmp_path/'events.json'
    rows=[]
    for year in (2021,2022,2026):
        day=f'{year}-06-01'
        rows.append(dict(signal_date=datetime(year,6,1),ticker='A',cusip='000000001',security_id='000000001',
            security_id_type='CUSIP',identity_present=True,identity_source='SYNTHETIC_ONLY',
            decision_at=day,available_at=day,effective_at=day))
    rows.extend([dict(rows[0],ticker=None,security_id=None,identity_present=False)]*2)
    pq.write_table(pa.Table.from_pylist(rows),pool)
    binding.write_text(json.dumps(dict(event_records=[dict(ticker='A',event_date=f'{y}-06-01',
        status='UNSUPPORTED',reason='SYNTHETIC_UNSUPPORTED',source_fingerprint=str(y),
        forbidden_numeric_payload={'cash_amount':'MUST_NOT_BE_DECODED'}) for y in (2021,2022,2026)])),encoding='utf-8')
    return source.plan_scope(pool,binding)


def test_pool_predicate_and_event_lexical_scope_never_admit_future(tmp_path):
    scope=synthetic_scope(tmp_path)
    assert scope['event_count']==scope['dated_ticker_identity_rows']==2
    assert scope['pool_rows']==4
    assert all(e['original5field_key']['effective_date']<'2023-01-01' for e in scope['events'])
    assert not scope['source_qualified']
    assert source.preflight(scope,expected_events=2)['raw_identity_witnesses_missing']==2
    with pytest.raises(ValueError,match='COUNT_CHANGED'):source.preflight(scope)


def test_actual_original_transport_reuse_persists_each_attempt_and_resumes(tmp_path,monkeypatch):
    scope=synthetic_scope(tmp_path);root=tmp_path/'capture'
    sr=source.freeze_scope(scope,root=root,expected_events=2)
    check=source.preflight
    monkeypatch.setattr(source,'preflight',lambda scope:check(scope,expected_events=2))
    calls=[]
    def get(url,**kwargs):
        calls.append(kwargs['params'])
        assert kwargs['params']['ex_dividend_date.gte']=='2021-06-01'
        return SimpleNamespace(content=body([row(),row('2022-06-01',declaration_date='2022-05-01',pay_date='2022-06-15',id='two')]),status_code=200,headers={})
    first=source.capture_all(sr,root=root,key='SYNTHETIC_TEST_KEY',request_get=get,gate=lambda *a,**k:None)
    assert len(calls)==1 and first['requests_made_this_invocation']==1
    assert len(first['events'])==2 and all(e['attempt_count']==1 for e in first['events'])
    assert all(e['source_record_status']=='CAPTURED_ORIGINAL_COMPONENTS_IDENTITY_AND_ACCOUNT_BINDING_PENDING' for e in first['events'])
    assert all(not e['account_qualified'] for e in first['events'])
    second=source.capture_all(sr,root=root,key='SYNTHETIC_TEST_KEY',request_get=get,gate=lambda *a,**k:None)
    assert len(calls)==1 and second['requests_made_this_invocation']==0


def test_private_cash_type_accepts_only_new_scope_without_changing_old_owner(tmp_path):
    from scripts.v22 import corporate_action_transition_r1 as old
    ca=source.private_cash_owner()
    terms=dict(event_id='SYNTHETIC',action_type='CASH_DIVIDEND',old_security_id='SYNTHETIC:A',ticker='A',
        ex_date='2021-01-06',record_date='2021-01-07',pay_date='2021-01-08',available_at=None,
        cash_per_old_share=.25,currency='USD',amount_unit=old.USD_PER_RAW_OLD_SHARE,quantity_coordinate=old.RAW_OLD_SHARE_COORDINATE,
        source_type='TIER3_VENDOR_METADATA',source_reference='SYNTHETIC_ONLY',source_fingerprint='a'*64,
        reconstruction_ref=str(tmp_path/'synthetic_projection.json'),reconstruction_sha256='a'*64,
        source_scope='B_FROZEN_PRE2026_ACCOUNTING_ONLY')
    event=ca.ResearchReconstructedCashEvent(**terms)
    assert isinstance(event,old.ResearchReconstructedCashEvent)
    with pytest.raises(ValueError,match='SOURCE_TERMS'):old.ResearchReconstructedCashEvent(**terms)
    assert old.ResearchReconstructedCashEvent is not ca.ResearchReconstructedCashEvent
    with pytest.raises(ValueError,match='EXPLICIT_PRE2023'):ca.ResearchReconstructedCashEvent(**dict(terms,source_scope='US_2026_SOURCE_ONLY'))
    with pytest.raises(ValueError,match='SOURCE_TERMS'):ca.ResearchReconstructedCashEvent(**dict(terms,ex_date='2023-01-06',record_date='2023-01-07',pay_date='2023-01-08'))


def test_private_original_shareholder_cash_runner_is_bounded_and_preserves_unsupported(tmp_path):
    import numpy as np,pandas as pd
    from scripts.research.a2.evaluation import consensus_cash_account as cash
    owner=source.private_shareholder_owner()
    frozen=tmp_path/'frozen.json';scope=tmp_path/'account_scope.json'
    frozen.write_text(json.dumps(dict(task_id=source.TASK)),encoding='utf-8')
    scope.write_text(json.dumps(dict(task_id=source.TASK,schema=source.ACCOUNT_SCOPE_SCHEMA)),encoding='utf-8')
    authority=owner.make_task_authority((),frozen_contract_ref=source.ref(frozen),source_scope_ref=source.ref(scope),
        market_source_binding=dict(task_id=source.TASK,quantity_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',source_refs=[source.ref(scope)],coverage_gaps=[]))
    dates=pd.bdate_range('2021-01-04',periods=5);shape=(5,1)
    market=cash.engine.MarketArrays(dates,['A'],np.full(shape,100.),np.full(shape,100.),adv=np.full(shape,1e8),signal_mask=[True,True,True,True,False])
    seen=[]
    def policy(di,ctx):return cash.engine.TargetDecision(np.array([[.08]]),ctx.decision_mask.copy())
    result=owner.run_shareholder_cash_account(market,['SYNTHETIC'],policy,task_authority=authority,
        settlement_calendar=dates,ledger_callback=lambda name,frame:seen.append((name,frame.copy())),
        entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='a'*64,quantity_coordinate='RAW_OLD_SECURITY_SHARES',event_fingerprints=[],security_tickers={}),
        unsupported_events=[dict(ticker='A',effective_date='2021-01-07',reason='SYNTHETIC_UNSUPPORTED',source_reference='SYNTHETIC_ONLY',source_fingerprint='a'*64)])
    assert result.daily.empty and result.fills.empty
    daily=pd.concat([f for n,f in seen if n=='daily'])
    assert daily.loc[daily.date.lt(pd.Timestamp('2021-01-07')),'accounting_qualified'].all()
    assert not daily.loc[daily.date.ge(pd.Timestamp('2021-01-07')),'accounting_qualified'].all()
    assert daily.loc[daily.date.ge(pd.Timestamp('2021-01-07')),'certified_nav'].isna().all()



def _synthetic_2022_admission(tmp_path):
    import numpy as np,pandas as pd
    from scripts.research.a2.evaluation import consensus_cash_account as cash
    frozen=tmp_path/'synthetic_frozen.json';binding=tmp_path/'synthetic_account_scope.json'
    frozen.write_text(json.dumps(dict(task_id=source.TASK,synthetic_only=True)),encoding='utf-8')
    binding.write_text(json.dumps(dict(task_id=source.TASK,schema=source.ACCOUNT_SCOPE_SCHEMA,synthetic_only=True)),encoding='utf-8')
    dates=pd.bdate_range('2022-01-03',periods=4);shape=(4,1)
    market=cash.engine.MarketArrays(dates,['A'],np.full(shape,100.),np.full(shape,100.),adv=np.full(shape,1e8))
    loaded=dict(source_qualified=True,binding_ref=source.ref(binding),binding={'frozen_contract_ref':source.ref(frozen)},
        market=market,events=dict(entitlement_events=(),research_account_authority={'frozen_history_cash_admission':None},
            entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint='a'*64,
                quantity_coordinate='RAW_OLD_SECURITY_SHARES',event_fingerprints=[],security_tickers={}),
            entitlement_security_tickers={},unsupported_events=()),settlement_calendar=dates,
        corporate_actions=(),corporate_action_known_at={},source_refs=[source.ref(binding)])
    proof=tmp_path/'synthetic_2022_forecast_proof.json'
    proof.write_text(json.dumps(dict(synthetic_only=True,forecast_year=2022,training_max_year=2021,
        all_fit_and_labels_before='2022-01-01',outer_development_rewards_used=False)),encoding='utf-8')
    schedule=source.causal_schedule_template_2022(loaded['binding_ref'])
    schedule.update(status='FROZEN_AUTHORIZED_RL_2022_ONLY',upstream_forecast_refs=[source.ref(proof)],causal_forecast_proof_ref=source.ref(proof))
    path=tmp_path/'synthetic_schedule.json';path.write_text(json.dumps(schedule),encoding='utf-8')
    policy=lambda year,market:lambda di,ctx:cash.engine.TargetDecision(np.full_like(ctx.current_weights,.08),ctx.decision_mask.copy())
    return loaded,policy,source.ref(path)


@pytest.mark.parametrize('method',['ppo','reinforce'])
def test_private_2022_owner_uses_original_gradients_and_truthful_receipt_years(tmp_path,method):
    from scripts.research.a2.training import consensus_auxiliary as old
    loaded,policy,schedule=_synthetic_2022_admission(tmp_path)
    owner=source.private_auxiliary_owner_2022()
    assert owner.network is old.network and owner.gae is old.gae and owner.discounted is old.discounted
    assert old.RECIPE['reward_years']==[2021,2022] and owner.RECIPE['reward_years']==[2022]
    env=source.account_environment_2022(loaded,policy,schedule)
    assert env.source_contract['training_reward_years']==[2022]
    assert [s['segment_id'] for s in env.source_contract['reset_segments']]==['2022']
    with pytest.raises(ValueError,match='REGISTERED_FROZEN'):env.reset('2021',0)
    seen=[];factory=env._factory
    def observed(segment,seed):seen.append(segment);return factory(segment,seed)
    env._factory=observed;units=[]
    fit=source.fit_activity_policy_2022(method,env,on_fit_started=units.append,schedule_ref=schedule)
    assert isinstance(fit,old.RLFit),fit
    assert fit.receipt['training_reward_years']==fit.receipt['recipe']['reward_years']==[2022]
    assert fit.receipt['training_steps']==36 and set(seen)=={'2022'} and len(seen)==12
    assert len(units)==fit.receipt['fit_units']==(1 if method=='ppo' else 13)
    assert fit.receipt['adapter_identity']['gradient_ast_unchanged'] is True
    assert env._thread is None


def test_proposed_2022_schedule_and_later_upstream_are_rejected_before_fit(tmp_path):
    loaded,policy,schedule=_synthetic_2022_admission(tmp_path)
    path=__import__('pathlib').Path(schedule['path']);body=json.loads(path.read_text())
    body['status']='PROPOSED';path.write_text(json.dumps(body))
    with pytest.raises(ValueError,match='FROZEN_RL_2022_ONLY'):source.account_environment_2022(loaded,policy,source.ref(path))
    body['status']='FROZEN_AUTHORIZED_RL_2022_ONLY';body['upstream_training_max_year']=2022;path.write_text(json.dumps(body))
    with pytest.raises(ValueError,match='FROZEN_RL_2022_ONLY'):source.account_environment_2022(loaded,policy,source.ref(path))

def test_historical_provider_alias_preserves_original_record_and_requires_exact_witness(tmp_path):
    import copy
    key=dict(ticker='NEW',effective_date='2021-06-01',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='a'*64)
    identity=dict(entries=[dict(original5field_key=key,accounting_sid='SYNTHETIC:NEW',ticker='NEW',signal_date='2021-06-01')])
    witness=tmp_path/'witness.json';witness.write_text('{"synthetic_only":true}')
    raw=tmp_path/'raw.json';raw.write_bytes(body([row(ticker='OLD')]))
    rawref=source.ref(raw);checkpoint=tmp_path/'checkpoint.json'
    checkpoint.write_text(json.dumps(dict(contract=dict(endpoint=original.ENDPOINT,query=dict(ticker='OLD',**{'ex_dividend_date.gte':'2021-06-01','ex_dividend_date.lte':'2021-06-01'})),
        attempts=[dict(http_status=200,raw_ref=rawref,next_url_present=False)],pagination_complete=True)))
    selected=source.project_dividends(raw.read_bytes(),ticker='OLD',start_date='2021-06-01',end_date='2021-06-01',target_dates=['2021-06-01'])
    components=[dict(record=selected['records'][0],raw_ref=rawref,checkpoint_ref=source.ref(checkpoint),pagination_complete=True,original_cash_amount_decimal='0.25')]
    fact=source._native_fact(dict(original5field_key=key),components,source.ref(witness),identity)
    fact.update(provider_ticker='OLD',provider_identity_alias_ref=source.ref(witness))
    routes={source._digest(key):dict(provider_ticker='OLD',witness_ref=source.ref(witness))}
    native=source._native_binder(identity,aliases=routes)
    projection=tmp_path/'fact.json';projection.write_text(json.dumps(fact))
    event=native._vendor_fact_event(source.private_cash_owner(),fact,source.ref(projection))
    assert event.ticker=='NEW' and event.cash_per_old_share==.25
    assert fact['vendor_components'][0]['record']['ticker']=='OLD'
    bad=copy.deepcopy(fact);bad['provider_ticker']='GUESSED'
    with pytest.raises(ValueError,match='EXACT_HISTORICAL_PROVIDER_ALIAS'):native._vendor_fact_event(source.private_cash_owner(),bad,source.ref(projection))
    with pytest.raises(ValueError,match='UNBOUND_PROVIDER_ALIAS'):source._native_binder(identity)._vendor_original_components(fact)


def _synthetic_return_reader():
    import pandas as pd
    from scripts.research.a2.training.stateful_inputs import ALLOWED_SOURCES
    allowed=sorted(ALLOWED_SOURCES)[0]
    rows=pd.DataFrame([dict(signal_date=pd.Timestamp(day),ticker=t,feature_available=ok,feature_source=src,ret_1d=value)
        for day,t,ok,src,value in [('2021-06-01','A',True,allowed,.01),('2021-06-01','B',False,allowed,999.),
        ('2022-06-01','A',True,allowed,-.02),('2022-06-01','B',True,'FORBIDDEN_SOURCE',999.),('2026-06-01','A',True,allowed,999.)]])
    class Reader:
        def __init__(self):self.calls=[];self.sources={'prediction_features':dict(path='SYNTHETIC',sha256='a'*64)}
        def read(self,name,columns,**kw):
            assert name=='prediction_features' and kw['start']=='2021-01-01' and kw['stop']=='2023-01-01'
            self.calls.append((list(columns),kw));selected=rows.loc[rows.signal_date.ge(kw['start'])&rows.signal_date.lt(kw['stop'])&rows.ticker.isin(kw['tickers'])]
            if 'day' in kw:selected=selected.loc[selected.signal_date.eq(kw['day'])]
            if 'ret_1d' in columns:
                assert self.calls[0][0]==['signal_date','ticker','feature_available','feature_source']
                assert selected.feature_available.all() and selected.feature_source.isin(ALLOWED_SOURCES).all()
            return selected[list(columns)].copy()
    return Reader(),rows


def test_daily_returns_project_only_eligible_exact_pool_keys_and_keep_original_attrs():
    reader,rows=_synthetic_return_reader()
    pool=rows.loc[rows.signal_date.lt('2023-01-01'),['signal_date','ticker']]
    out=source.qualified_daily_returns(reader,pool)
    assert list(out.columns)==['A'] and out.shape==(2,1) and out.iloc[:,0].tolist()==[.01,-.02]
    assert out.attrs['source_ref']==reader.sources['prediction_features'] and out.attrs['unit']=='DAILY_DECIMAL_RETURN'
    assert out.attrs['eligibility']=='CURRENT_DAILY100_QUALIFIED_KEYS; monthly owner fits only current decision assets plus held'
    assert len(reader.calls)==3


def test_daily_returns_reject_out_of_scope_pool_before_any_source_read():
    reader,rows=_synthetic_return_reader()
    with pytest.raises(ValueError,match='EXACT_2021_2022_POOL'):source.qualified_daily_returns(reader,rows[['signal_date','ticker']])
    assert not reader.calls


def _synthetic_declared_case(tmp_path,currency='USD',provider='ISSUER_IR'):
    from scripts.research.a2.data import consensus_declared_cash_source_completion as D
    key=dict(ticker='A',effective_date='2021-06-01',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='a'*64)
    identity=dict(entries=[dict(original5field_key=key,accounting_sid='SYNTHETIC:A',ticker='A',signal_date='2021-06-01')])
    unit=b'<xbrli:unit id="u"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:'+currency.encode()+b'</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    tag=b'<ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="u" contextRef="c">'
    context=b'<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="SYNTHETIC">123</xbrli:identifier></xbrli:entity></xbrli:context>'
    primary=b'<html>'+context+unit+tag+b'UNREAD_FINANCIAL_SCALAR</ix:nonFraction></html>'
    primary_path=tmp_path/'synthetic.htm';primary_path.write_bytes(primary)
    header=b'<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20210501120000\nACCESSION NUMBER: 0000000123-21-000001\nCONFORMED SUBMISSION TYPE: 10-Q\nCENTRAL INDEX KEY: 123\n</SEC-HEADER>'
    header_path=tmp_path/'header.physical';header_path.write_bytes(header)
    submission=tmp_path/'submission.physical';submission.write_bytes(header+b'\n<DOCUMENT>\n<TYPE>10-Q\n<SEQUENCE>1\n<FILENAME>synthetic.htm\n<TEXT>\n<XBRL>\n'+primary)
    tagpath=tmp_path/'tag.physical';tagpath.write_bytes(tag);unitpath=tmp_path/'unit.physical';unitpath.write_bytes(unit)
    support=dict(issuer_CIK=123,source_ref=source.ref(primary_path),accepted_header_ref=source.ref(header_path),
        accepted_at_utc='2021-05-01T16:00:00+00:00',accession='0000000123-21-000001',form='10-Q',original_header_prefix_custody_ref=source.ref(submission),
        common_concept='us-gaap:CommonStockDividendsPerShareDeclared',opening_tag_ref=source.ref(tagpath),opening_tag_physical_range=[primary.index(tag),primary.index(tag)+len(tag)],
        original_USD_divided_shares_ref=source.ref(unitpath),unit_physical_range=[primary.index(unit),primary.index(unit)+len(unit)])
    text='Synthetic Inc. declared a quarterly dividend of $0.25 per share of common stock, payable on June 15, 2021 to holders of record on June 1, 2021.'
    raw=('<p>'+text+'</p>').encode();ir=tmp_path/'ir.html';ir.write_bytes(raw);fragment=tmp_path/'cash.physical';fragment.write_bytes(raw)
    fact=dict(schema=D.FACT_SCHEMA,source_kind='ISSUER_PRE2026_DECLARED_FIXED_USD_RAW_LISTED_CASH',primary_source_provider='ISSUER_IR',
        amount_source_role='ORIGINAL_PRE2026_ISSUER_DECLARATION_NOT_VENDOR_PAYMENT_RESULT',original5field_key=key,ticker='A',accounting_sid='SYNTHETIC:A',ex_date='2021-06-01',
        record_date='2021-06-01',pay_date='2021-06-15',declaration_displayed_date='2021-05-01',original_current_source_ref=source.ref(ir),current_cash_fragment_ref=source.ref(fragment),
        current_cash_physical_range=[0,len(raw)],current_original_cash_text=text,common_usd_unit_support=support,original_issuer_source_url='SYNTHETIC_ONLY',source_displayed_date_verified=True,
        available_at=None,strict_PIT=False,actual_payment_status_read=False,vendor_payment_amount_read=False,declared_cash_amount_decimal='.25',
        current_action_literal='declared',record_literal='June 1, 2021',pay_literal='June 15, 2021',current_common_literal='common stock',
        currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES')
    if provider=='ISSUER_FILED_SEC_ORIGINAL':
        fact['primary_source_provider']=provider;fact.pop('declaration_displayed_date');fact.pop('source_displayed_date_verified')
        fact.update(source_SEC_accepted_at=support['accepted_at_utc'],source_SEC_acceptance_verified=True)
    capsule=tmp_path/'capsule.json';capsule.write_text(json.dumps(fact),encoding='utf-8');fact['approved_current_capsule_ref']=source.ref(capsule)
    factpath=tmp_path/'fact.json';factpath.write_text(json.dumps(fact),encoding='utf-8')
    validator=source._declared_fact_validator(identity,{123:support},{source._digest(key):source.ref(capsule)})
    return validator,fact,source.ref(factpath)


def test_declared_private_route_keeps_original_physical_unit_and_money_checks(tmp_path):
    validator,fact,projection=_synthetic_declared_case(tmp_path)
    event=validator(source.private_cash_owner(),fact,projection)
    assert event.ticker=='A' and event.cash_per_old_share==.25 and event.available_at is None
    with pytest.raises(ValueError,match='DIRECT_MONEY_AND_DATES'):validator(source.private_cash_owner(),dict(fact,declared_cash_amount_decimal='.26'),projection)


def test_declared_dollar_sign_does_not_override_non_usd_original_unit(tmp_path):
    validator,fact,projection=_synthetic_declared_case(tmp_path,'EUR')
    fact['declared_cash_amount_decimal']='DO_NOT_PARSE_BEFORE_UNIT'
    with pytest.raises(ValueError,match='USD_PER_LISTED_SHARE_UNIT'):validator(source.private_cash_owner(),fact,projection)


def test_original_sec_declaration_uses_actual_header_clock_without_invented_ir_date(tmp_path):
    validator,fact,projection=_synthetic_declared_case(tmp_path,provider='ISSUER_FILED_SEC_ORIGINAL')
    assert 'declaration_displayed_date' not in fact
    event=validator(source.private_cash_owner(),fact,projection)
    assert event.available_at is None and event.cash_per_old_share==.25
    with pytest.raises(ValueError,match='EXACT_PHYSICAL_SOURCE_CAPSULE'):validator(source.private_cash_owner(),dict(fact,source_SEC_accepted_at='2021-06-02T00:00:00Z'),projection)


def _synthetic_realized_fcx_case(tmp_path,total='0.15'):
    from pathlib import Path
    _,fact,_=_synthetic_declared_case(tmp_path,provider='ISSUER_FILED_SEC_ORIGINAL')
    old=fact['common_usd_unit_support'];primary=Path(old['source_ref']['path']);body=primary.read_bytes().replace(b'>123<',b'>831259<');primary.write_bytes(body)
    header=Path(old['accepted_header_ref']['path']);h=header.read_bytes().replace(b'20210501120000',b'20220505120000').replace(b'0000000123-21-000001',b'0000831259-22-000001').replace(b'CENTRAL INDEX KEY: 123',b'CENTRAL INDEX KEY: 831259');header.write_bytes(h)
    submission=Path(old['original_header_prefix_custody_ref']['path']);submission.write_bytes(h+b'\n<DOCUMENT>\n<TYPE>10-Q\n<SEQUENCE>1\n<FILENAME>synthetic.htm\n<TEXT>\n<XBRL>\n'+body)
    tag=Path(old['opening_tag_ref']['path']).read_bytes();unit=Path(old['original_USD_divided_shares_ref']['path']).read_bytes()
    support=dict(old,issuer_CIK=831259,source_ref=source.ref(primary),accepted_header_ref=source.ref(header),original_header_prefix_custody_ref=source.ref(submission),
        accepted_at_utc='2022-05-05T16:00:00+00:00',accession='0000831259-22-000001',opening_tag_physical_range=[body.index(tag),body.index(tag)+len(tag)],unit_physical_range=[body.index(unit),body.index(unit)+len(unit)])
    key=dict(fact['original5field_key'],ticker='FCX',effective_date='2022-04-13')
    text='FCX declared quarterly cash dividends totaling $'+total+' per share ($0.075 per share base dividend and $0.075 per share variable dividend) on its common stock, which were paid on May 2, 2022, to common stockholders of record as of April 14, 2022.'
    raw=('<p>'+text+'</p>').encode();ir=Path(fact['original_current_source_ref']['path']);ir.write_bytes(raw);fragment=Path(fact['current_cash_fragment_ref']['path']);fragment.write_bytes(raw)
    scope=dict(schema='CONSENSUS_RL_TWO_FCX_2022_POSTVERIFIED_REWARD_CASH_SCOPE_R1',status='FROZEN_AUTHORIZED_EXACT_2022_MATURE_REWARD_SOURCE',
        training_reward_cutoff_exclusive='2023-01-01',ordinary_cash_classification_inferred=False,
        documents=[dict(original5field_key=key,issuer_CIK=831259,SEC_url='SYNTHETIC_ONLY')])
    scopepath=tmp_path/'mature_reward_scope.json';scopepath.write_text(json.dumps(scope),encoding='utf-8')
    fact.update(schema='CONSENSUS_RL_2022_REALIZED_ISSUER_USD_RAW_CASH_FACT_R1',source_kind='ISSUER_PRE2023_REALIZED_FIXED_USD_RAW_LISTED_CASH',
        amount_source_role='ORIGINAL_2022_ISSUER_REPORTED_REALIZED_CASH_NOT_ASOF_INPUT',original5field_key=key,ticker='FCX',accounting_sid='SYNTHETIC:FCX',ex_date='2022-04-13',record_date='2022-04-14',pay_date='2022-05-02',
        common_usd_unit_support=support,source_SEC_accepted_at=support['accepted_at_utc'],reward_mature_at=support['accepted_at_utc'],frozen_mature_reward_scope_ref=source.ref(scopepath),
        asof_policy_input_allowed=False,ordinary_cash_classification_inferred=False,current_original_cash_text=text,declared_cash_amount_decimal=total,current_action_literal='paid',
        current_cash_physical_range=[0,len(raw)],record_literal='April 14, 2022',pay_literal='May 2, 2022',original_current_source_ref=source.ref(ir),current_cash_fragment_ref=source.ref(fragment),
        actual_payment_status_read=True,total_credit_once=True,issuer_components=[dict(record=dict(id='SYNTHETIC_BASE'),original_cash_amount_decimal='0.075'),dict(record=dict(id='SYNTHETIC_VARIABLE'),original_cash_amount_decimal='0.075')])
    fact.pop('approved_current_capsule_ref');capsule=tmp_path/'realized_capsule.json';capsule.write_text(json.dumps(fact),encoding='utf-8');fact['approved_current_capsule_ref']=source.ref(capsule)
    projection=tmp_path/'realized_fact.json';projection.write_text(json.dumps(fact),encoding='utf-8')
    identity=dict(entries=[dict(original5field_key=key,accounting_sid='SYNTHETIC:FCX',ticker='FCX',signal_date='2022-04-13')])
    validator=source._declared_fact_validator(identity,{support['accession']:support},{source._digest(key):source.ref(capsule)})
    return validator,fact,source.ref(projection)


def test_2022_realized_cash_keeps_actual_later_source_clock_and_credits_total_once(tmp_path):
    validator,fact,projection=_synthetic_realized_fcx_case(tmp_path)
    event=validator(source.private_cash_owner(),fact,projection)
    assert fact['source_SEC_accepted_at'][:10]>fact['pay_date']>fact['ex_date']
    assert event.cash_per_old_share==.15 and len(fact['issuer_components'])==2 and event.available_at is None
    assert fact['asof_policy_input_allowed'] is False and fact['ordinary_cash_classification_inferred'] is False
    with pytest.raises(ValueError,match='MATURE_BEFORE_TRAINING_CUTOFF'):validator(source.private_cash_owner(),dict(fact,reward_mature_at='2023-01-01T00:00:00Z'),projection)


def test_realized_fcx_explicit_total_must_equal_both_original_components(tmp_path):
    validator,fact,projection=_synthetic_realized_fcx_case(tmp_path,total='0.16')
    with pytest.raises(ValueError,match='TOTAL_COMPONENT_SUM'):validator(source.private_cash_owner(),fact,projection)


@pytest.mark.parametrize('drift',[ 'capture_scope_ref','identity_ref','bundle_ref','settlement_calendar_ref','source_manifest_ref','manifest_same_bytes_different_path'])
def test_loader_metadata_drift_rejects_before_metadata_body_or_first_numeric_reader(tmp_path,monkeypatch,drift):
    from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as risk
    paths={};binding=dict(schema=source.ACCOUNT_SCOPE_SCHEMA,start=source.LOWER,end_exclusive=source.UPPER,
        numeric_read_authorization='AUTHORIZED_RL_2021_2022_FROZEN_RAW_AND_SIGNAL_ADV',producer_ref=source.ref(source.__file__))
    for name in ('capture_scope_ref','identity_ref','bundle_ref','settlement_calendar_ref','source_manifest_ref'):
        p=tmp_path/(name+'.json');p.write_text('{"synthetic_metadata_only":true}',encoding='utf-8');paths[name]=p;binding[name]=source.ref(p)
    manifest=paths['source_manifest_ref']
    if drift=='manifest_same_bytes_different_path':
        other=tmp_path/'alternate_manifest.json';other.write_bytes(manifest.read_bytes());monkeypatch.setattr(source,'R3_MANIFEST',other)
    else:
        monkeypatch.setattr(source,'R3_MANIFEST',manifest);paths[drift].write_text('{"synthetic_metadata_only":"DRIFTED"}',encoding='utf-8')
    p=tmp_path/'synthetic_binding.json';p.write_text(json.dumps(binding),encoding='utf-8')
    calls=[]
    def forbidden(*args,**kwargs):calls.append('BODY_OR_NUMERIC_READER');pytest.fail('source body/numeric reader reached before metadata pins')
    monkeypatch.setattr(source,'preflight',forbidden);monkeypatch.setattr(risk,'ProjectedReader',forbidden);monkeypatch.setattr(source.ds,'dataset',forbidden)
    reason='R3_MANIFEST_REFERENCE_CHANGED' if drift=='manifest_same_bytes_different_path' else 'METADATA_REFERENCE_CHANGED:'+drift
    with pytest.raises(ValueError,match=reason):source.load_account_inputs(source.ref(p))
    assert calls==[]
