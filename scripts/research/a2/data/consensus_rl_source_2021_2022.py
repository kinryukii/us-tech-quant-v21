"""Private pre2023 SOURCE and canonical RL account adapters.

Exact frozen scopes reuse original transport, cash validators and account owners.
Historical vintage remains UNKNOWN; this does not certify PIT, quotes or NAV.
"""
from __future__ import annotations
import ast
from collections import Counter
from datetime import datetime
import hashlib
import inspect
import io
import json
import math
from pathlib import Path
import pyarrow as pa
import pyarrow.dataset as ds
from scripts.common.storage_paths import resolve, resolve_cache_path, assert_safe_output_path
from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
from scripts.storage import massive_dividend_sources as original
from scripts.research.a2.data import consensus_cash_source_bulk_completion as binder

TASK='CONSENSUS100_PTO_3000_20261012_R1'
SCHEMA='CONSENSUS_RL_2021_2022_CA_SOURCE_SCOPE_R1'
LOWER,UPPER='2021-01-01','2023-01-01'
TRANSPORT_SHA='22018a77eb7bb4cfd06a71bd249189869735c8e6a076f47089f246c4ea3d5cde'
DEFAULT_POOL=Path('D:/us-tech-quant-backtests')/TASK/'20261011T170254+0000_bf592a79/derived/consensus100_daily.parquet'
DEFAULT_EVENTS=Path('D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/ACCOUNT_EVENT_BINDING_R1.json')


def require(ok,reason):
    if not ok: raise ValueError(reason)


def ref(path):
    p=Path(path)
    with p.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(path=str(p),sha256=digest)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def source_root():
    return resolve_cache_path('_maintenance',TASK,'rl_source_2021_2022')


def _write(path,value):
    p=Path(path);assert_safe_output_path(p,kind='cache');p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return ref(p)


def _array_metadata(path,name,fields):
    with Path(path).open('rb') as f:
        q=_JsonProjection(f);q.descend((name,));q.expect(b'[');q.white()
        while q.peek()!=b']':
            yield q.metadata_fields(set(fields))
            q.white();sep=q.take()
            if sep==b']':return
            require(sep==b',','RL_SOURCE_METADATA_ARRAY_CHANGED');q.white()


def plan_scope(pool=DEFAULT_POOL,event_binding=DEFAULT_EVENTS):
    """Arrow predicate and lexical metadata only; no action numbers or outcomes."""
    pool,event_binding=Path(pool),Path(event_binding)
    columns=['signal_date','ticker','cusip','security_id','security_id_type',
             'identity_present','identity_source','decision_at','available_at','effective_at']
    filt=(ds.field('signal_date')>=pa.scalar(datetime(2021,1,1))) & (ds.field('signal_date')<pa.scalar(datetime(2023,1,1)))
    table=ds.dataset(pool,format='parquet').to_table(columns=columns,filter=filt)
    dated={}
    for row in table.to_pylist():
        day=str(row.pop('signal_date').date())
        if not isinstance(row.get('ticker'),str) or not row['ticker'].strip():continue
        key=(day,row['ticker'])
        require(key not in dated,'RL_SOURCE_POOL_DUPLICATE_DATED_IDENTITY')
        dated[key]=dict(signal_date=day,**row)
    events=[];supported=0
    for item in _array_metadata(event_binding,'event_records',('ticker','event_date','status','reason','source_fingerprint')):
        day=item.get('event_date','');key=(day,item.get('ticker'))
        if not (LOWER<=day<UPPER and key in dated):continue
        if item.get('status')!='UNSUPPORTED':supported+=1;continue
        original_key=dict(ticker=item['ticker'],effective_date=day,reason=item['reason'],
            source_reference=str(event_binding),source_fingerprint=item['source_fingerprint'])
        events.append(dict(event_id=_digest(original_key),original5field_key=original_key,
            pool_identity=dated[key],raw_share_identity_witness='MISSING_NOT_INFERRED_FROM_POOL',
            historical_available_at='UNKNOWN',strict_PIT=False))
    events.sort(key=lambda e:(e['original5field_key']['ticker'],e['original5field_key']['effective_date']))
    require(len({e['event_id'] for e in events})==len(events),'RL_SOURCE_DUPLICATE_EVENT_KEY')
    return dict(schema=SCHEMA,status='PROPOSED',task_id=TASK,start=LOWER,end_exclusive=UPPER,
        purpose='PAST_2021_2022_OOF_ACCOUNT_REWARD_SOURCE_ONLY_NOT_MODEL_FEATURE',
        source_policy='POST_VERIFIED_ACCOUNTING_ONLY_HISTORICAL_VINTAGE_UNKNOWN',
        strict_PIT=False,source_qualified=False,account_qualified=False,
        no_predictions_prices_accounts_or_2026_read=True,numeric_gate='EXACT_TARGET_AND_PRE2023_DECLARATION_PAY_AND_METADATA_CLOCKS_FIRST',
        source_refs=dict(pool=ref(pool),event_binding=ref(event_binding)),
        producer_ref=ref(__file__),transport_ref=ref(original.__file__),fact_binder_ref=ref(binder.__file__),
        event_count=len(events),ticker_count=len({e['original5field_key']['ticker'] for e in events}),
        pool_rows=table.num_rows,dated_ticker_identity_rows=len(dated),pool_dates=len({k[0] for k in dated}),supported_pool_events_preserved=supported,
        reason_counts=dict(Counter(e['original5field_key']['reason'] for e in events)),events=events)


def preflight(scope,*,expected_events=132):
    require(scope.get('schema')==SCHEMA and scope.get('task_id')==TASK,'RL_SOURCE_PRIVATE_SCOPE_REQUIRED')
    require(scope['start']==LOWER and scope['end_exclusive']==UPPER,'RL_SOURCE_2021_2022_ONLY')
    require(scope['event_count']==len(scope['events'])==expected_events,'RL_SOURCE_EXPECTED_EVENT_COUNT_CHANGED')
    require(scope['transport_ref']['sha256']==TRANSPORT_SHA,'RL_SOURCE_ORIGINAL_TRANSPORT_CHANGED')
    for value in [scope['producer_ref'],scope['transport_ref'],scope['fact_binder_ref'],*scope['source_refs'].values()]:
        actual=ref(value['path'])
        if value is scope['producer_ref'] and not _same_ref(actual,value):_capture_producer_pin(value)
        else:require(_same_ref(actual,value),'RL_SOURCE_FROZEN_BYTES_CHANGED')
    for event in scope['events']:
        k=event['original5field_key'];identity=event['pool_identity']
        require(LOWER<=k['effective_date']<UPPER and identity['signal_date']==k['effective_date']
                and identity['ticker']==k['ticker'] and event['event_id']==_digest(k),'RL_SOURCE_EXACT_DATED_EVENT_KEY_REQUIRED')
        require(identity['identity_present'] is True and identity['security_id_type']=='CUSIP'
                and identity['cusip']==identity['security_id'],'RL_SOURCE_POOL_IDENTITY_METADATA_REQUIRED')
    return dict(status='PASS_STATIC_EXACT_SOURCE_SCOPE',events=len(scope['events']),
                tickers=scope['ticker_count'],raw_identity_witnesses_missing=len(scope['events']))


def freeze_scope(scope,*,root=None,expected_events=132):
    preflight(scope,expected_events=expected_events);root=Path(root or source_root())
    scope=dict(scope,status='FROZEN_AUTHORIZED_2021_2022_SOURCE_CAPTURE')
    path=root/'scope.json';assert_safe_output_path(path,kind='cache')
    if path.exists():require(json.loads(path.read_text(encoding='utf-8'))==scope,'RL_SOURCE_FROZEN_SCOPE_ALREADY_EXISTS_DIFFERENT')
    else:_write(path,scope)
    return ref(path)


def _valid_day(value):
    try:return isinstance(value,str) and datetime.strptime(value,'%Y-%m-%d').strftime('%Y-%m-%d')==value
    except ValueError:return False


def project_dividends(body,*,ticker,start_date,end_date,target_dates):
    """Metadata eligibility precedes any selected monetary field decoding."""
    require(LOWER<=start_date<=end_date<UPPER,'RL_VENDOR_2021_2022_WINDOW_REQUIRED')
    wanted=frozenset(target_dates)
    require(wanted and all(start_date<=d<=end_date for d in wanted),'RL_VENDOR_EXACT_TARGETS_REQUIRED')
    rows=original._metadata_rows(body)
    require(all(m.get('ticker')==ticker and _valid_day(m.get('ex_dividend_date'))
                and start_date<=m['ex_dividend_date']<=end_date for _,_,m in rows),
            'RL_VENDOR_RESPONSE_SCOPE_CHANGED_NO_NUMERIC_DECODE')
    records=[];rejected=[]
    fields={'ticker','ex_dividend_date','declaration_date','record_date','pay_date','currency','available_at','reward_mature_at'}
    for a,z,m in rows:
        day=m['ex_dividend_date']
        if day not in wanted:continue
        raw=body[a:z]
        with io.BytesIO(raw) as f:timing=_JsonProjection(f).metadata_fields(fields)
        declared,record,pay=(timing.get(n) for n in ('declaration_date','record_date','pay_date'))
        reason=None
        if not all(_valid_day(d) for d in (declared,record,pay)):reason='MISSING_OR_INVALID_DECLARATION_RECORD_PAY_NO_CASH_DECODE'
        elif not declared<day<=record<=pay:reason='DECLARATION_EX_RECORD_PAY_ORDER_INVALID_NO_CASH_DECODE'
        elif not declared<UPPER or not pay<UPPER:reason='FUTURE_PAY_REQUIRES_PRE2023_ISSUER_DECLARED_SOURCE_NO_VENDOR_CASH_DECODE'
        elif timing.get('currency')!='USD':reason='NON_USD_RAW_SHARE_UNIT_REQUIRES_INDEPENDENT_SOURCE_NO_CASH_DECODE'
        for name in ('available_at','reward_mature_at'):
            value=timing.get(name)
            if value is not None and (not isinstance(value,str) or value[:10]>=UPPER or value[:10]>day):
                reason='FUTURE_OR_INELIGIBLE_'+name.upper()+'_NO_CASH_DECODE'
        if reason:
            rejected.append(dict(ticker=ticker,ex_dividend_date=day,reason=reason,metadata=timing));continue
        with io.BytesIO(raw) as f:records.append(_JsonProjection(f).metadata_fields(original.FIELDS))
    return dict(records=records,rejected_target_metadata=rejected,total_metadata_rows=len(rows),
        target_rows_decoded=len(records),outside_exact_target_numeric_rows_decoded=0,
        excluded_numeric_fields=list(original.EXCLUDED),historical_vintage='UNKNOWN',first_publication_at=None,
        native_qualified=False,strict_PIT=False,source_scope=SCHEMA)


def _acquirer():
    """Reuse the original exact transport; only private date constants change."""
    require(ref(original.__file__)['sha256']==TRANSPORT_SHA,'RL_ORIGINAL_CAPTURE_OWNER_PIN_REQUIRED')
    tree=ast.parse(inspect.getsource(original.acquire_window));edits=Counter()
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and node.value in (LOWER,UPPER,'2026-01-01'):
            if node.value==UPPER:node.value=LOWER;edits['lower']+=1
            elif node.value=='2026-01-01':node.value=UPPER;edits['upper']+=1
    require(edits==dict(lower=1,upper=1),'RL_PRIVATE_CAPTURE_DATE_ANCHORS_CHANGED')
    namespace={**vars(original),'__file__':__file__,'project_dividends':project_dividends}
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)
    return namespace['acquire_window']


def capture_all(scope_ref,*,root=None,key=None,request_get=None,gate=None,progress=None):
    """One process, original throttling/retries, complete per-event disposition."""
    require(ref(scope_ref['path'])==scope_ref,'RL_SOURCE_SCOPE_BYTES_CHANGED')
    scope=json.loads(Path(scope_ref['path']).read_text(encoding='utf-8'));preflight(scope)
    require(scope['status']=='FROZEN_AUTHORIZED_2021_2022_SOURCE_CAPTURE','RL_SOURCE_CAPTURE_NOT_FROZEN')
    root=Path(root or source_root());assert_safe_output_path(root/'status.json',kind='cache')
    groups={}
    rows={e['event_id']:dict(event_id=e['event_id'],original5field_key=e['original5field_key'],
        attempt_status='UNATTEMPTED',attempt_count=0,source_record_status='UNREAD',account_qualified=False,
        missing_witnesses=['EXACT_DATED_RAW_SHARE_IDENTITY','2021_2022_ACCOUNT_AND_SETTLEMENT_CALENDAR_BINDING']) for e in scope['events']}
    for event in scope['events']:groups.setdefault(event['original5field_key']['ticker'],[]).append(event)
    state=dict(schema=SCHEMA,status='CAPTURING',scope_ref=scope_ref,events=list(rows.values()),windows=[],requests_made_this_invocation=0)
    def save():
        state['status_counts']=dict(Counter(r['attempt_status'] for r in rows.values()))
        state['record_status_counts']=dict(Counter(r['source_record_status'] for r in rows.values()))
        _write(root/'status.json',state)
    save()
    if key is None:
        from scripts.storage.refresh_current_massive import load_api_key
        key=load_api_key(resolve())
    if not key:
        state['status']='UNATTEMPTED_CREDENTIAL_UNAVAILABLE';save();return state
    acquire=_acquirer()
    for ticker,events in groups.items():
        dates=sorted({e['original5field_key']['effective_date'] for e in events});kwargs={}
        if request_get is not None:kwargs['request_get']=request_get
        if gate is not None:kwargs['gate']=gate
        captured,count=acquire(ticker=ticker,start_date=dates[0],end_date=dates[-1],target_dates=dates,
            key=key,root=root,paths=resolve(),**kwargs)
        checkpoint=root/'windows'/ticker/'checkpoint.json';cpref=ref(checkpoint)
        attempts=len(captured['attempts']);state['requests_made_this_invocation']+=count
        state['windows'].append(dict(ticker=ticker,status=captured['status'],checkpoint_ref=cpref,attempt_count=attempts))
        for event in events:
            row=rows[event['event_id']];day=event['original5field_key']['effective_date']
            records=[r for r in captured.get('records',[]) if r['ex_dividend_date']==day]
            rejected=[r for r in captured.get('rejected_target_metadata',[]) if r['ex_dividend_date']==day]
            row.update(attempt_status='ATTEMPTED_'+captured['status'],attempt_count=attempts,checkpoint_ref=cpref,
                source_record_status='NO_EXACT_VENDOR_RECORD',numeric_component_count=len(records))
            if rejected:row.update(source_record_status='METADATA_REJECTED_WITHOUT_CASH_DECODE',metadata_rejections=rejected)
            elif records:
                valid=all(isinstance(r.get('cash_amount'),(int,float)) and math.isfinite(r['cash_amount']) and r['cash_amount']>0 and r.get('id') for r in records)
                row['source_record_status']='CAPTURED_ORIGINAL_COMPONENTS_IDENTITY_AND_ACCOUNT_BINDING_PENDING' if valid else 'INVALID_ORIGINAL_COMPONENT_AMOUNT_OR_ID'
                row['source_components_ref']=cpref
            elif captured['status']!='CAPTURED_EXACT_VENDOR_SOURCE_NOT_NATIVE_QUALIFIED':row['source_record_status']='TRANSPORT_NOT_CAPTURED'
        save()
        if progress:progress(dict(ticker=ticker,windows_done=len(state['windows']),windows_total=len(groups),events_done=sum(r['attempt_count']>0 for r in rows.values()),status_counts=state['status_counts']))
    state['status']='ALL_EXACT_EVENT_WINDOWS_ATTEMPTED_SOURCE_QUALIFICATION_INCOMPLETE';save()
    return state

# Exact same-byte custody of the immutable first capture producer.
CAPTURE_PRODUCER_SHA='72593ca10ce78ee3bf0baaff4ebb9d5f37ba12fb748b5668cf7b35d6ef7d1ceb'
R3_MANIFEST=Path('D:/us-tech-quant-backtests/V24/20261003T061818+0000_49b1a578/FAMILY_SOURCE_INPUTS.json')
R3_MANIFEST_SHA='04d17931c7437f9c7bc1277b33820c52ec2e527a995b0f1c587dc26f5b2c2fd8'
ACCOUNT_SCOPE_SCHEMA='CONSENSUS_RL_2021_2022_ACCOUNT_SOURCE_SCOPE_R1'
ACCOUNT_AUTHORITY_SCHEMA='CONSENSUS_RL_2021_2022_ACCOUNT_AUTHORITY_R1'
NATIVE_SCHEMA='CONSENSUS_RL_2021_2022_ORIGINAL_VENDOR_NATIVE_BUNDLE_R1'


def _same_ref(actual,expected):
    return Path(actual['path']).resolve()==Path(expected['path']).resolve() and actual['sha256']==expected['sha256']


def _capture_producer_pin(expected):
    actual=ref(expected['path'])
    if _same_ref(actual,expected):return actual
    custody=source_root()/'owner_custody/consensus_rl_capture_72593ca1.py'
    require(expected['sha256']==CAPTURE_PRODUCER_SHA and Path(expected['path']).resolve()==Path(__file__).resolve()
            and ref(custody)['sha256']==expected['sha256'],'RL_CAPTURE_PRODUCER_EXACT_CUSTODY_REQUIRED')
    return ref(custody)


def independent_identity_witness(scope):
    """Existing exact-pinned R3 source, metadata projection only; no FF48 need."""
    import pandas as pd
    from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as R
    require(ref(R3_MANIFEST)['sha256']==R3_MANIFEST_SHA,'RL_R3_MANIFEST_PIN_CHANGED')
    with R3_MANIFEST.open('rb') as f:source=_JsonProjection(f).metadata_fields({'sources'})
    reader=R.ProjectedReader(source,phase='support')
    tickers=sorted({e['original5field_key']['ticker'] for e in scope['events']})
    fields=['effective_start','effective_end','ticker','security_id','security_id_type','cusip','title_of_class','moomoo_transport_code','mapping_status','mapping_source','source_filing']
    intervals=reader.read('uid_intervals',fields,date_field='effective_start',stop=UPPER,tickers=tickers)
    raw=reader.read('raw_open_close',['ticker','trade_date','code'],date_field='trade_date',start=LOWER,stop=UPPER,tickers=tickers)
    intervals.effective_start=pd.to_datetime(intervals.effective_start);intervals.effective_end=pd.to_datetime(intervals.effective_end);raw.trade_date=pd.to_datetime(raw.trade_date)
    entries=[]
    for event in scope['events']:
        k=event['original5field_key'];day=pd.Timestamp(k['effective_date']);sid=event['pool_identity']['cusip']
        rows=intervals[(intervals.ticker==k['ticker'])&(intervals.effective_start<=day)&(intervals.effective_end>=day)&(intervals.security_id==sid)]
        classes=rows[['security_id_type','cusip','title_of_class','moomoo_transport_code','mapping_status']].drop_duplicates()
        prices=raw[(raw.ticker==k['ticker'])&(raw.trade_date==day)]
        require(len(classes)==len(prices)==1,'RL_INDEPENDENT_DATED_UID_OR_RAW_KEY_NOT_UNIQUE')
        c=classes.iloc[0];transport='US.'+k['ticker']
        require(c.security_id_type=='CUSIP' and c.cusip==sid and c.moomoo_transport_code==prices.iloc[0].code==transport
                and c.mapping_status=='RESOLVED' and isinstance(c.title_of_class,str) and c.title_of_class.strip(),
                'RL_INDEPENDENT_CLASS_RAW_COORDINATE_NOT_BOUND')
        entries.append(dict(original5field_key=k,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:'+transport,
            ticker=k['ticker'],signal_date=k['effective_date'],cusip=sid,security_uid='CUSIP:'+sid,
            moomoo_transport_code=transport,raw_coordinate='RAW_ACTUAL_SHARE',title_of_class=c.title_of_class,
            security_id_type='CUSIP',mapping_status='RESOLVED',source_filings=sorted(set(rows.source_filing.dropna())),
            source_role='EXACT_FROZEN_INTERVAL_METADATA_DECLARATION_AND_DATED_ORIGINAL_RAW_TRANSPORT',
            strict_historical_authority=False))
    return dict(schema='CONSENSUS_RL_INDEPENDENT_DATED_RAW_IDENTITY_R1',task_id=TASK,
        status='SOURCE_BOUND_FROZEN_HISTORY_MECHANISM_ONLY',manifest_ref=ref(R3_MANIFEST),
        source_refs={k:source['sources'][k] for k in ('uid_intervals','raw_open_close','calendar')},
        raw_fill_coordinate='RAW_FRACTIONAL_SECURITY_SHARES_NEXT_OPEN',historical_quote_vintage='UNKNOWN',
        strict_PIT=False,quote_qualified=False,certified_NAV=False,entries=entries,reader_audit=reader.audit)


def _date_tree(tree):
    edits=Counter()
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            if node.value=='2023-01-01':node.value=LOWER;edits['lower']+=1
            elif node.value=='2026-01-01':node.value=UPPER;edits['upper']+=1
    return edits


def _private_functions(module,*,namespace=None,names=None):
    """Private function globals/date guards only; original business AST retained."""
    import types
    tree=ast.parse(Path(module.__file__).read_text(encoding='utf-8-sig'))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and (names is None or n.name in names)]
    body=ast.Module(body=nodes,type_ignores=[]);edits=_date_tree(body)
    ns={**vars(module),**(namespace or {})}
    exec(compile(ast.fix_missing_locations(body),module.__file__,'exec'),ns)
    return types.SimpleNamespace(**ns),dict(edits)


_PRIVATE_CA=None

def private_cash_owner():
    global _PRIVATE_CA
    if _PRIVATE_CA is not None:return _PRIVATE_CA
    from scripts.v22 import corporate_action_transition_r1 as ca
    module,_=_private_functions(ca)
    # inspect returns an indented method; dedent keeps the original exact body.
    import textwrap
    tree=ast.parse(textwrap.dedent(inspect.getsource(ca.ResearchReconstructedCashEvent.__post_init__)))
    _date_tree(tree);ns=vars(module).copy();exec(compile(ast.fix_missing_locations(tree),ca.__file__,'exec'),ns)
    original_post=ns['__post_init__']
    def private_post(self,source_scope='US_2026_SOURCE_ONLY'):
        require(source_scope=='B_FROZEN_PRE2026_ACCOUNTING_ONLY','RL_PRIVATE_EXPLICIT_PRE2023_CASH_SCOPE_REQUIRED')
        original_post(self,source_scope)
    cls=type('RLResearchReconstructedCashEvent',(ca.ResearchReconstructedCashEvent,),{'__post_init__':private_post,'__module__':__name__})
    module.ResearchReconstructedCashEvent=cls
    # Functions share one private globals dictionary so validators see the type.
    for value in vars(module).values():
        if inspect.isfunction(value) and value.__module__==ca.__name__:value.__globals__['ResearchReconstructedCashEvent']=cls
    _PRIVATE_CA=module;return module


def _native_binder(identity,producer_ref=None,aliases=None,declared_validator=None):
    """Reuse the original native component/amount/group validators unchanged."""
    from types import SimpleNamespace
    bykey={_digest(e['original5field_key']):e for e in identity['entries']}
    def exact_identity(fact):
        row=bykey.get(_digest(fact['original5field_key']))
        require(row is not None and row['accounting_sid']==fact['accounting_sid'] and row['ticker']==fact['ticker']
                and row['signal_date']==fact['ex_date'],'RL_EXACT_INDEPENDENT_RAW_IDENTITY_REQUIRED')
        return row
    def provider_subject(fact):
        entry=(aliases or {}).get(_digest(fact['original5field_key']))
        if entry is None:
            require(not fact.get('provider_ticker') and not fact.get('provider_identity_alias_ref'),'RL_UNBOUND_PROVIDER_ALIAS_FORBIDDEN')
            return fact['ticker']
        require(fact.get('provider_ticker')==entry['provider_ticker'] and fact.get('provider_identity_alias_ref')==entry['witness_ref'],
            'RL_EXACT_HISTORICAL_PROVIDER_ALIAS_REQUIRED')
        require(_same_ref(ref(entry['witness_ref']['path']),entry['witness_ref']),'RL_HISTORICAL_ALIAS_WITNESS_CHANGED')
        return entry['provider_ticker']
    transport=SimpleNamespace(**vars(original));transport.project_dividends=project_dividends
    names=['_vendor_original_components','_vendor_fact_event','_bind_vendor_source_descendant']
    tree=ast.parse(Path(binder.__file__).read_text(encoding='utf-8-sig'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    body=ast.Module(body=nodes,type_ignores=[]);_date_tree(body)
    edits=Counter()
    for n in ast.walk(body):
        if isinstance(n,ast.ImportFrom) and n.module=='scripts.storage':
            n.module=None;n.names=[]
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ca' for t in n.targets) and isinstance(n.value,ast.Attribute):
            n.value=ast.Name(id='_rl_ca',ctx=ast.Load());edits['ca']+=1
    # Replace the one local transport import with the explicitly bound namespace.
    fn=next(n for n in nodes if n.name=='_vendor_original_components')
    for i,n in enumerate(fn.body):
        if isinstance(n,ast.ImportFrom) and not n.names:
            fn.body[i]=ast.Assign(targets=[ast.Name(id='M',ctx=ast.Store())],value=ast.Name(id='_rl_transport',ctx=ast.Load()));edits['transport']+=1
    class ProviderSubject(ast.NodeTransformer):
        def visit_Compare(self,node):
            self.generic_visit(node)
            if isinstance(node.left,ast.Subscript) and isinstance(node.left.value,ast.Name) and node.left.value.id in ('query','record') and isinstance(node.left.slice,ast.Constant) and node.left.slice.value=='ticker':
                require(len(node.comparators)==1 and ast.dump(node.comparators[0])==ast.dump(ast.parse("fact['ticker']",mode='eval').body),'RL_PROVIDER_COMPARISON_ANCHOR_CHANGED')
                node.comparators[0]=ast.Call(func=ast.Name(id='_provider_subject',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[]);edits['provider_compare']+=1
            return node
        def visit_Call(self,node):
            self.generic_visit(node)
            if isinstance(node.func,ast.Attribute) and node.func.attr=='project_dividends':
                item=next(k for k in node.keywords if k.arg=='ticker');require(ast.dump(item.value)==ast.dump(ast.parse("fact['ticker']",mode='eval').body),'RL_PROVIDER_PROJECTOR_ANCHOR_CHANGED')
                item.value=ast.Call(func=ast.Name(id='_provider_subject',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[]);edits['provider_projector']+=1
            return node
    body=ProviderSubject().visit(body)
    if declared_validator is not None:
        changes=Counter()
        target=next(n for n in nodes if n.name=='_bind_vendor_source_descendant')
        for n in ast.walk(target):
            if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and n.slice.value=='vendor_components':n.slice.value='issuer_components';changes['component_field']+=1
            elif isinstance(n,ast.Constant) and n.value=='PASS_SOURCE_ONLY_MASSIVE_ORIGINAL_RAW_LISTED_VENDOR_NATIVE':n.value='PASS_SOURCE_ONLY_ORIGINAL_ISSUER_DECLARED_RAW_LISTED_NATIVE';changes['status']+=1
            elif isinstance(n,ast.keyword) and n.arg=='vendor_source_profile':n.arg='declared_source_profile';changes['profile_field']+=1
        require(changes==dict(component_field=1,status=1,profile_field=2),'RL_DECLARED_ORIGINAL_NATIVE_SOURCE_ANCHORS_CHANGED')
    require(edits==dict(ca=1,transport=1,provider_compare=2,provider_projector=1),'RL_NATIVE_PRIVATE_OWNER_ANCHORS_CHANGED')
    def owner_ref(path):
        if producer_ref is not None and Path(path).resolve()==Path(__file__).resolve():
            custody=source_root()/'owner_custody'/('account_owner_'+producer_ref['sha256'][:12]+'.py')
            require(ref(custody)['sha256']==producer_ref['sha256'],'RL_ACCOUNT_OWNER_EXACT_CUSTODY_REQUIRED')
            return producer_ref
        return binder._ref(path)
    ns={**vars(binder),'__file__':__file__,'_ref':owner_ref,'VENDOR_NATIVE_SCHEMA':NATIVE_SCHEMA,
        '_vendor_identity':exact_identity,'_provider_subject':provider_subject,'_rl_transport':transport,'_rl_ca':private_cash_owner()}
    exec(compile(ast.fix_missing_locations(body),__file__,'exec'),ns)
    if declared_validator is not None:
        ns['_vendor_fact_event']=declared_validator;ns['VENDOR_NATIVE_SCHEMA']=DECLARED_SCHEMA
    return SimpleNamespace(**ns)



def _native_fact(event,components,identity_ref,identity):
    from decimal import Decimal
    first=components[0]['record'];ticker=event['original5field_key']['ticker'];day=event['original5field_key']['effective_date'];sid=next(e['accounting_sid'] for e in identity['entries'] if e['original5field_key']==event['original5field_key'])
    dates={n:first[n] for n in ('ex_dividend_date','record_date','pay_date','declaration_date','currency')}
    group=dict(original5field_key=event['original5field_key'],accounting_sid=sid,listed_unit='RAW_ACTUAL_SHARE',currency='USD',dates=dates,
        components=sorted([dict(id=c['record']['id'],type=c['record']['distribution_type'],original_amount=c['original_cash_amount_decimal'],rawSHA=c['raw_ref']['sha256']) for c in components],key=lambda x:x['id']),clock_role='POST_VERIFIED_ACCOUNTING_ONLY')
    fact=dict(schema='SOURCE131_ORIGINAL_MASSIVE_VENDOR_CASH_NATIVE_FACT_R1',source_type='TIER3_VENDOR_METADATA',available_at=None,ordinary_cash_confirmed=False,
        clock_role='POST_VERIFIED_ACCOUNTING_ONLY',original5field_key=event['original5field_key'],ticker=ticker,accounting_sid=sid,ex_date=day,
        pay_date=first['pay_date'],record_date=first['record_date'],declaration_date=first['declaration_date'],vendor_endpoint=original.ENDPOINT,
        vendor_components=components,original_raw_identity_links_ref=identity_ref,
        derived_cash_amount_decimal=str(sum((Decimal(c['original_cash_amount_decimal']) for c in components),Decimal(0))),
        source_kind='COMPOSITE_CASH' if len(components)>1 else 'VENDOR_ORIGINAL_CASH_COMPONENT',
        amount_aggregation_role='DERIVED_ORIGINAL_COMPONENT_SUM_CREDIT_ONCE' if len(components)>1 else 'SINGLE_ORIGINAL_VENDOR_COMPONENT',
        canonical_group_definition=group,group_id=_digest(group))
    return fact


def prepare_native_sources(*,frozen_contract_ref,root=None):
    """Actually bind all eligible vendor components; keep every unresolved key."""
    from decimal import Decimal
    import pandas as pd
    root=Path(root or source_root());capture_ref=ref(root/'scope.json')
    scope=json.loads((root/'scope.json').read_text(encoding='utf-8'));preflight(scope)
    identity=independent_identity_witness(scope);identity_ref=_write(root/'identity_binding.json',identity)
    native=_native_binder(identity);cash=private_cash_owner()
    status=json.loads((root/'status.json').read_text(encoding='utf-8'))
    byid={e['event_id']:e for e in status['events']};facts=[];all_source_refs=[identity_ref,capture_ref,ref(root/'owner_custody/consensus_rl_capture_72593ca1.py')]
    for event in scope['events']:
        row=byid[event['event_id']]
        if row['source_record_status']!='CAPTURED_ORIGINAL_COMPONENTS_IDENTITY_AND_ACCOUNT_BINDING_PENDING':continue
        cpref=row['checkpoint_ref'];require(_same_ref(ref(cpref['path']),cpref),'RL_CAPTURE_CHECKPOINT_CHANGED')
        cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'));day=event['original5field_key']['effective_date']
        components=[]
        for attempt in cp['attempts']:
            if attempt.get('http_status')!=200:continue
            rawref=attempt['raw_ref'];require(_same_ref(ref(rawref['path']),rawref),'RL_CAPTURE_RESPONSE_CHANGED')
            query=cp['contract']['query'];selected=project_dividends(Path(rawref['path']).read_bytes(),ticker=event['original5field_key']['ticker'],
                start_date=query['ex_dividend_date.gte'],end_date=query['ex_dividend_date.lte'],target_dates=[day])
            for record in selected['records']:
                components.append(dict(record=record,raw_ref=rawref,checkpoint_ref=cpref,pagination_complete=cp['pagination_complete'],original_cash_amount_decimal=str(Decimal(str(record['cash_amount'])))))
            all_source_refs.append(rawref)
        require(components,'RL_ELIGIBLE_CAPTURE_COMPONENTS_MISSING')
        fact=_native_fact(event,components,identity_ref,identity)
        projection_ref=_write(root/'native_facts'/(event['event_id']+'.json'),fact)
        typed=native._vendor_fact_event(cash,fact,projection_ref)
        facts.append(projection_ref);all_source_refs.append(cpref)
        row['native_fact_qualified']=True;row['native_fact_ref']=projection_ref;row['typed_event_fingerprint']=typed.event_fingerprint
        row['missing_witnesses']=[x for x in row['missing_witnesses'] if x not in ('EXACT_DATED_RAW_SHARE_IDENTITY','2021_2022_ACCOUNT_AND_SETTLEMENT_CALENDAR_BINDING')]
        row['qualification_status']='NATIVE_CASH_FACT_BOUND_PRIVATE_2021_2022_OWNER'
    # Existing market sessions plus an explicitly frozen, conservative T+2 bank
    # calendar projection. Tail sessions are metadata only; no 2023 price/reward.
    source=identity['source_refs']['calendar'];require(ref(source['path'])['sha256']==source['sha256'],'RL_CALENDAR_PIN_CHANGED')
    table=ds.dataset(source['path'],format='parquet').to_table(columns=['trade_date'],filter=(ds.field('trade_date')>=pa.scalar(datetime(2021,1,1)))&(ds.field('trade_date')<pa.scalar(datetime(2023,1,7))))
    days=pd.DatetimeIndex(table.column('trade_date').to_pandas())
    excluded=pd.DatetimeIndex(['2021-10-11','2021-11-11','2022-10-10','2022-11-11'])
    settlement=days[~days.isin(excluded)]
    settlement_ref=_write(root/'settlement_calendar.json',dict(schema='CONSENSUS_RL_PRIVATE_T2_SETTLEMENT_CALENDAR_R1',task_id=TASK,
        source_calendar_ref=source,dates=[str(d.date()) for d in settlement],excluded_open_market_bank_holidays=[str(d.date()) for d in excluded],
        rule='CANONICAL_T2_PRE_2024_05_28; RELEASE_ON_NEXT_ACCOUNT_SESSION',source_policy='FROZEN_HISTORY_MECHANISM_ONLY',
        certified_broker_calendar=False,calendar_tail_role='KNOWN_DATES_ONLY_NO_2023_QUOTES_OR_REWARDS'))
    source_refs=list({(x['path'],x['sha256']):x for x in all_source_refs}.values())
    bundle=dict(schema=NATIVE_SCHEMA,completion_binder_owner_ref=ref(__file__),event_projection_refs=facts,source_refs=source_refs)
    bundle_ref=_write(root/'native_bundle.json',bundle)
    unsupported=[e['original5field_key'] for e in scope['events']]
    mapping={e['accounting_sid']:e['ticker'] for e in identity['entries']}
    base=dict(entitlement_security_tickers=mapping,unsupported_events=unsupported)
    descendant=native._bind_vendor_source_descendant(None,base,bundle,account_dates=days[days<'2023-01-01'],bundle_ref=bundle_ref)
    binding=dict(schema=ACCOUNT_SCOPE_SCHEMA,task_id=TASK,status='FROZEN_AUTHORIZED_2021_2022_ACCOUNT_SOURCE',
        numeric_read_authorization='AUTHORIZED_RL_2021_2022_FROZEN_RAW_AND_SIGNAL_ADV',start=LOWER,end_exclusive=UPPER,
        frozen_contract_ref=frozen_contract_ref,capture_scope_ref=capture_ref,capture_owner_custody_ref=ref(root/'owner_custody/consensus_rl_capture_72593ca1.py'),
        identity_ref=identity_ref,bundle_ref=bundle_ref,settlement_calendar_ref=settlement_ref,producer_ref=ref(__file__),
        source_manifest_ref=ref(R3_MANIFEST),native_fact_count=len(facts),retained_unsupported_count=len(descendant['events']['unsupported_events']),
        ordinary_cash_classification_not_inferred=True,strict_PIT=False,quote_qualified=False,certified_NAV=False,
        signal_adv_role='EXISTING_PRE2023_SIGNAL_MATRIX_AVG_DOLLAR_VOLUME20',real_fits_started=0)
    binding_ref=_write(root/'account_scope.json',binding)
    status['raw_identity_preflight']=dict(status='RESOLVED_BY_INDEPENDENT_EXACT_PINNED_R3_METADATA',identity_ref=identity_ref,exact_links=len(identity['entries']),gaps=0)
    status['qualification_summary'].update(native_cash_facts_qualified=len(facts),independent_identity_links=len(identity['entries']),identity_gaps=0,
        missing_dated_raw_identity_events=0,private_settlement_calendar_ref=settlement_ref,account_source_binding_ref=binding_ref,
        native_binder_status=descendant['receipt']['status'],account_replay_passed=False)
    from scripts.research.a2.data import full_selector_account_inputs as legacy
    status['legacy_ref_check_correction']={name:dict(status='HASH_AND_RESOLVED_PATH_MATCH',ref=legacy.DEFAULT_REFS[name]) for name in ('a_mapping','a_identity','dated_identity')}
    status['legacy_ref_check_note']='Earlier mismatch was path separator string comparison; SHA and resolved paths match. Legacy mapping range still starts in 2023; independent R3 witness is used.'
    _write(root/'status.json',status)
    return binding_ref,descendant

_PRIVATE_SHAREHOLDER=None

def private_shareholder_owner():
    """Existing shareholder/cash lifecycle with only private date/schema routing."""
    global _PRIVATE_SHAREHOLDER
    if _PRIVATE_SHAREHOLDER is not None:return _PRIVATE_SHAREHOLDER
    import copy,types
    from scripts.research.a2.evaluation import consensus_shareholder_account as S
    from scripts.research.a2.evaluation import continuous_research_account as C
    from scripts.research.a2.evaluation import consensus_cash_account as cash
    ca=private_cash_owner()
    overlaps={k:v for k,v in vars(ca).items() if k in vars(C) and not k.startswith('__')}
    continuous,_=_private_functions(C,namespace=overlaps)
    def compile_scope(tree,*args,**kwargs):
        _date_tree(tree)
        # Keep bounded RL episodes free of accumulated presentation ledgers.
        changed=0
        for node in ast.walk(tree):
            if isinstance(node,ast.If) and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute)
                    and x.func.attr=='setdefault' and isinstance(x.func.value,ast.Name)
                    and x.func.value.id=='enriched' for statement in node.body for x in ast.walk(statement)):
                node.test=ast.Constant(value=False);changed+=1
        require(changed==1,'RL_CANONICAL_LEDGER_STORAGE_ANCHOR_CHANGED')
        return compile(ast.fix_missing_locations(tree),*args,**kwargs)
    def bounded_cash(*args,**kwargs):
        kwargs['collect_ledgers']=False
        return cash.run_cash_account(*args,**kwargs)
    tree=ast.parse(Path(S.__file__).read_text(encoding='utf-8-sig'))
    body=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[])
    _date_tree(body)
    for node in ast.walk(body):
        if isinstance(node,ast.Constant) and node.value=='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1':node.value=ACCOUNT_SCOPE_SCHEMA
    ns={**vars(S),'ca':ca,'owner':continuous,'SCHEMA':ACCOUNT_AUTHORITY_SCHEMA,
        'run_cash_account':bounded_cash,'compile':compile_scope}
    exec(compile(ast.fix_missing_locations(body),S.__file__,'exec'),ns)
    _PRIVATE_SHAREHOLDER=types.SimpleNamespace(**ns)
    return _PRIVATE_SHAREHOLDER


def _supported_share_records(path,tickers):
    """Decode old source share ratio only after exact pre2023 metadata selection."""
    selected=[]
    with Path(path).open('rb') as f:
        q=_JsonProjection(f);q.descend(('event_records',));q.expect(b'[');q.white()
        while q.peek()!=b']':
            start=q.tell();meta=q.metadata_fields({'event_date','ticker','status'});end=q.tell()
            if LOWER<=meta.get('event_date','')<UPPER and meta.get('ticker') in tickers and meta.get('status') in ('SHARE_ONLY_SUPPORTED','FROZEN_TIER1_SHARE_ONLY_SUPPORTED'):
                require(end-start<=65536,'RL_SHARE_SOURCE_RECORD_OVER_65KI')
                here=f.tell();f.seek(start);selected.append(json.loads(f.read(end-start)));f.seek(here)
            q.white();sep=q.take()
            if sep==b']':break
            require(sep==b',','RL_SHARE_SOURCE_ARRAY_CHANGED');q.white()
    return selected


def load_account_inputs(binding_ref):
    """Frozen 2021/22 source-only numeric projection; no models/results/joblib."""
    import numpy as np,pandas as pd,importlib.util
    from dataclasses import replace
    from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as R
    require(_same_ref(ref(binding_ref['path']),binding_ref),'RL_ACCOUNT_SOURCE_BINDING_CHANGED')
    binding=json.loads(Path(binding_ref['path']).read_text(encoding='utf-8'));root=Path(binding_ref['path']).parent
    require(binding['schema']==ACCOUNT_SCOPE_SCHEMA and binding['start']==LOWER and binding['end_exclusive']==UPPER
            and binding['numeric_read_authorization']=='AUTHORIZED_RL_2021_2022_FROZEN_RAW_AND_SIGNAL_ADV'
            and (_same_ref(ref(__file__),binding['producer_ref']) or ref(root/'owner_custody'/('account_owner_'+binding['producer_ref']['sha256'][:12]+'.py'))['sha256']==binding['producer_ref']['sha256']),'RL_EXPLICIT_FROZEN_ACCOUNT_SOURCE_REQUIRED')
    for name in ('capture_scope_ref','identity_ref','bundle_ref','settlement_calendar_ref','source_manifest_ref'):
        expected=binding[name]
        require(_same_ref(ref(expected['path']),expected),'RL_ACCOUNT_METADATA_REFERENCE_CHANGED:'+name)
    require(_same_ref(ref(R3_MANIFEST),binding['source_manifest_ref']),'RL_ACCOUNT_R3_MANIFEST_REFERENCE_CHANGED')
    capture=json.loads(Path(binding['capture_scope_ref']['path']).read_text(encoding='utf-8'));preflight(capture)
    identity=json.loads(Path(binding['identity_ref']['path']).read_text(encoding='utf-8'))
    bundle=json.loads(Path(binding['bundle_ref']['path']).read_text(encoding='utf-8'))
    native=_native_binder(identity,producer_ref=bundle['completion_binder_owner_ref'])
    with R3_MANIFEST.open('rb') as f:source=_JsonProjection(f).metadata_fields({'sources'})
    reader=R.ProjectedReader(source,phase='fit')
    pool=ds.dataset(capture['source_refs']['pool']['path'],format='parquet').to_table(columns=['signal_date','ticker','cusip','security_id','identity_present'],
        filter=(ds.field('signal_date')>=pa.scalar(datetime(2021,1,1)))&(ds.field('signal_date')<pa.scalar(datetime(2023,1,1)))).to_pandas()
    return_pool=pool.loc[pool.ticker.notna(),['signal_date','ticker']].copy()
    pool=pool[pool.identity_present.eq(True)&pool.ticker.notna()&pool.security_id.notna()].copy()
    require(not pool.duplicated(['signal_date','ticker']).any(),'RL_ACCOUNT_POOL_DATED_UID_AMBIGUOUS')
    tickers=sorted(set(pool.ticker))
    prices=reader.read('raw_open_close',['ticker','trade_date','open','close'],date_field='trade_date',start=LOWER,stop=UPPER,tickers=tickers)
    calendar=reader.read('calendar',['trade_date'],date_field='trade_date',start=LOWER,stop=UPPER)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.trade_date))
    # Existing original raw-market array builder is the same R1 source owner.
    market_path=Path('D:/us-tech-quant-results/TOP20_SELECTOR_CHALLENGER_PRE2026_TEST2026_R1/work/selector_replay.py')
    require(ref(market_path)['sha256']=='b344fa6f10c08249e21ef590820bab8bf1a8ed46dcfa2459312766f34d8ed4bb','RL_RAW_MARKET_OWNER_PIN_CHANGED')
    spec=importlib.util.spec_from_file_location('_consensus_rl_frozen_market_owner',market_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from scripts.research.a2.evaluation import consensus_cash_account as cash
    market=module.make_market(cash.engine,prices,pool,dates)
    adv=reader.read('prediction_features',['signal_date','ticker','avg_dollar_volume_20d'],date_field='signal_date',start=LOWER,stop=UPPER,tickers=tickers)
    require(not adv.duplicated(['signal_date','ticker']).any(),'RL_SIGNAL_ADV_DATED_KEY_AMBIGUOUS')
    values=adv.pivot(index='signal_date',columns='ticker',values='avg_dollar_volume_20d').reindex(index=dates,columns=market.tickers).to_numpy(float)
    market=replace(market,adv=values)
    returns=qualified_daily_returns(reader,return_pool)
    unsupported=[]
    for event in _array_metadata(capture['source_refs']['event_binding']['path'],'event_records',('event_date','ticker','status','reason','source_fingerprint')):
        if LOWER<=event.get('event_date','')<UPPER and event.get('ticker') in tickers and event['status']=='UNSUPPORTED':
            unsupported.append(dict(ticker=event['ticker'],effective_date=event['event_date'],reason=event['reason'],
                source_reference=capture['source_refs']['event_binding']['path'],source_fingerprint=event['source_fingerprint']))
    base=dict(entitlement_security_tickers={e['accounting_sid']:e['ticker'] for e in identity['entries']},unsupported_events=unsupported)
    settlement_payload=json.loads(Path(binding['settlement_calendar_ref']['path']).read_text(encoding='utf-8'));settlement=pd.DatetimeIndex(settlement_payload['dates'])
    descendant=native._bind_vendor_source_descendant(None,base,bundle,account_dates=dates,bundle_ref=binding['bundle_ref'])
    from types import SimpleNamespace,FunctionType
    from scripts.research.a2.data import consensus_account_inputs as I
    empty=dict(base,entitlement_events=(),research_account_authority={'frozen_history_cash_admission':None},
        entitlement_source_binding=dict(status='SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND',source_fingerprint=_digest(base),
            quantity_coordinate=private_cash_owner().RAW_OLD_SHARE_COORDINATE,manifest={'original_event_binding_ref':capture['source_refs']['event_binding']},
            security_tickers=base['entitlement_security_tickers'],event_fingerprints=[]))
    merge=FunctionType(I.merge_completion_descendant.__code__,{**I.merge_completion_descendant.__globals__,'existing':SimpleNamespace(**{**vars(I.existing),'ca':private_cash_owner()})})
    combined=merge(empty,descendant,binding['bundle_ref']);descendant['events']=combined
    completion_ref=binding.get('completion_bundle_ref')
    if completion_ref is not None:
        require(_same_ref(ref(completion_ref['path']),completion_ref),'RL_COMPLETION_BUNDLE_CHANGED')
        completion=json.loads(Path(completion_ref['path']).read_text(encoding='utf-8'))
        routes=_alias_routes(completion['source_alias_witness_ref'])
        alias_native=_native_binder(identity,producer_ref=completion['completion_binder_owner_ref'],aliases=routes)
        alias_desc=alias_native._bind_vendor_source_descendant(None,combined,completion,account_dates=dates,bundle_ref=completion_ref)
        descendant['events']=merge(combined,alias_desc,completion_ref)
    declared_ref=binding.get('declared_completion_bundle_ref')
    if declared_ref is not None:
        require(_same_ref(ref(declared_ref['path']),declared_ref),'RL_DECLARED_COMPLETION_BUNDLE_CHANGED')
        declared=json.loads(Path(declared_ref['path']).read_text(encoding='utf-8'))
        validator=_declared_fact_validator(identity,declared['declared_supports'],declared['declared_capsules'])
        declared_native=_native_binder(identity,producer_ref=declared['completion_binder_owner_ref'],declared_validator=validator)
        current=descendant['events'];declared_desc=declared_native._bind_vendor_source_descendant(None,current,declared,account_dates=dates,bundle_ref=declared_ref)
        descendant['events']=merge(current,declared_desc,declared_ref)
    shares=_supported_share_records(capture['source_refs']['event_binding']['path'],set(tickers));ca=private_cash_owner();actions=[];known={}
    for row in shares:
        day=row['event_date'];ticker=row['ticker'];sid='FROZEN_RAW_TRANSPORT_CODE:US.'+ticker
        action=ca.CorporateActionTransition(day,'OTHER_SHARE_COUNT_TRANSFORM',sid,sid,ticker,ticker,row['quantity_multiplier'],0.,
            'TIER2_LOCAL_CANONICAL',capture['source_refs']['event_binding']['path']+'#'+row['source_fingerprint'],row['source_fingerprint'])
        actions.append(action);known[action.event_fingerprint]=pd.Timestamp(row['known_at_assumption'])
    return dict(binding=binding,binding_ref=binding_ref,market=market,returns=returns,events=descendant['events'],
        settlement_calendar=settlement,corporate_actions=tuple(actions),corporate_action_known_at=known,
        source_refs=[binding['identity_ref'],binding['bundle_ref'],binding['settlement_calendar_ref'],binding['source_manifest_ref']]+([completion_ref] if completion_ref else [])+([declared_ref] if declared_ref else []),
        reader_audit=reader.audit,loader_ref=ref(__file__),source_qualified=True,unsupported_events_fail_closed=True,
        certified_NAV=False,strict_PIT=False,real_fits_started=0)


def account_episode_factory(loaded,policy_factory,*,segment_ids=('2021','2022')):
    """Caller supplies original frozen OOF PTO policy_factory(year, market)."""
    from dataclasses import replace
    import numpy as np,pandas as pd
    from scripts.research.a2.training.consensus_account_rl import AccountEpisode
    owner=private_shareholder_owner()
    def build(segment_id,seed):
        require(str(segment_id) in tuple(segment_ids),'RL_EPISODE_OUTSIDE_FROZEN_SEGMENT_IDS')
        year=int(segment_id);require(year in (2021,2022),'RL_ONLY_2021_2022_EPISODE')
        market=loaded['market'];mask=pd.DatetimeIndex(market.dates).year==year;indices=np.flatnonzero(mask)
        require(len(indices)>=2,'RL_YEAR_ACCOUNT_SESSIONS_REQUIRED')
        fields={}
        for name in ('open','close','quality','adv','input_present','new_buy_eligible','buy_restricted','sell_restricted','row_present'):
            fields[name]=getattr(market,name)[mask].copy()
        signals=np.ones(len(indices),bool);signals[-1]=False
        current=replace(market,dates=market.dates[mask],signal_mask=signals,signal_asof=[market.signal_asof[i] for i in indices],**fields)
        policy=policy_factory(year,current)
        events=tuple(e for e in loaded['events']['entitlement_events'] if pd.Timestamp(e.ex_date).year==year)
        original=loaded['events']['research_account_authority']['frozen_history_cash_admission']
        admission=dict(original,events=[r for r in original['events'] if r['event_fingerprint'] in {e.event_fingerprint for e in events}]) if events else None
        authority=owner.make_task_authority(events,frozen_contract_ref=loaded['binding']['frozen_contract_ref'],source_scope_ref=loaded['binding_ref'],
            market_source_binding=dict(task_id=TASK,quantity_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',source_refs=loaded['source_refs'],coverage_gaps=['Historical vintage UNKNOWN; unresolved corporate actions remain hard blockers']),
            frozen_history_cash_admission=admission)
        action=tuple(e for e in loaded['corporate_actions'] if pd.Timestamp(e.effective_date).year==year)
        source_binding=dict(loaded['events']['entitlement_source_binding'],event_fingerprints=[e.event_fingerprint for e in events])
        kwargs=dict(task_authority=authority,settlement_calendar=loaded['settlement_calendar'],entitlement_events=events,
            entitlement_security_tickers=loaded['events']['entitlement_security_tickers'],entitlement_source_binding=source_binding,
            corporate_actions=action,corporate_action_known_at=loaded['corporate_action_known_at'],
            unsupported_events=tuple(e for e in loaded['events']['unsupported_events'] if pd.Timestamp(e['effective_date']).year==year))
        def run(active_policy,ledger):return owner.run_shareholder_cash_account(current,['RL_'+str(year)],active_policy,ledger_callback=ledger,**kwargs)
        return AccountEpisode(current,policy,run,dict(source_qualified=True,chronological_oof_only=True,cash_shareholder_owner_bound=True,
            unsupported_events_fail_closed=True,fresh_lifecycle=True,training_inputs_ref=loaded['binding_ref'],runner_ref=ref(__file__)))
    return build



def rl_environment_contract(loaded,*,segment_ids=('2021','2022')):
    """Fixed original RL recipe, source-bound 2021/22 chronological segments."""
    import pandas as pd
    from scripts.research.a2.training import consensus_auxiliary as A
    from scripts.research.a2.training import consensus_account_rl as bridge
    segments=[]
    require(tuple(segment_ids) and set(segment_ids)<=set(('2021','2022')),'RL_EXPLICIT_LEGAL_SEGMENT_IDS_REQUIRED')
    for year in [int(x) for x in segment_ids]:
        days=pd.DatetimeIndex(loaded['market'].dates);days=days[days.year==year]
        require(len(days)>=2,'RL_FIXED_YEAR_SOURCE_SEGMENT_REQUIRED')
        segments.append(dict(segment_id=str(year),start=str(days[0].date()),end_exclusive=str(year+1)+'-01-01'))
    return dict(causal_observations=True,source_qualified=True,stateful_cash_holdings_fee_account=True,
        actual_fees_in_reward=True,episode_segments_frozen=True,training_reward_years=[int(x) for x in segment_ids],
        activity_caps=list(A.CAPS),observation_scaling=A.RECIPE['observation_scaling'],reward_definition=A.RECIPE['reward_definition'],
        dependency_paths=[str(A.TORCH_SNAPSHOT)],reset_segments=segments,chronological_oof_only=True,primary_horizon_sessions=5,
        outer_development_rewards_used=False,activity_gate_ref=ref(bridge.__file__),training_inputs_ref=loaded['binding_ref'],
        source_limitations=['FROZEN_HISTORY_MECHANISM_ONLY','UNRESOLVED_EVENTS_HARD_BLOCK_ACTUAL_REWARD','NO_2023_REWARD_OR_QUOTES'])


def causal_schedule_template_2022(source_binding_ref):
    from scripts.research.a2.training import consensus_auxiliary as A
    from scripts.research.a2.training import consensus_account_rl as B
    return dict(schema='CONSENSUS_RL_2022_CAUSAL_SCHEDULE_R1',status='PROPOSED',task_id=TASK,
        segment_ids=['2022'],training_reward_years=[2022],upstream_forecast_year=2022,
        upstream_training_max_year=2021,outer_development_rewards_used=False,
        source_binding_ref=source_binding_ref,upstream_forecast_refs=[],causal_forecast_proof_ref=None,
        auxiliary_owner_ref=ref(A.__file__),bridge_owner_ref=ref(B.__file__),adapter_ref=ref(__file__),
        epochs=12,seed=A.SEED,primary_horizon_sessions=5,algorithm_change=False,
        admission_note='Root must supply final 2022 upstream forecast refs and explicit causal proof before FROZEN_AUTHORIZED_RL_2022_ONLY')


def _schedule_2022(schedule_ref):
    require(_same_ref(ref(schedule_ref['path']),schedule_ref),'RL_2022_SCHEDULE_BYTES_CHANGED')
    schedule=json.loads(Path(schedule_ref['path']).read_text(encoding='utf-8'))
    require(schedule.get('schema')=='CONSENSUS_RL_2022_CAUSAL_SCHEDULE_R1'
        and schedule.get('status')=='FROZEN_AUTHORIZED_RL_2022_ONLY' and schedule.get('task_id')==TASK
        and schedule.get('segment_ids')==['2022'] and schedule.get('training_reward_years')==[2022]
        and schedule.get('upstream_forecast_year')==2022 and schedule.get('upstream_training_max_year')==2021
        and schedule.get('outer_development_rewards_used') is False and schedule.get('epochs')==12
        and schedule.get('algorithm_change') is False,'FROZEN_RL_2022_ONLY_CAUSAL_SCHEDULE_REQUIRED')
    from scripts.research.a2.training import consensus_auxiliary as A
    from scripts.research.a2.training import consensus_account_rl as B
    require(schedule.get('seed')==A.SEED and schedule.get('primary_horizon_sessions')==5
        and _same_ref(ref(A.__file__),schedule['auxiliary_owner_ref'])
        and _same_ref(ref(B.__file__),schedule['bridge_owner_ref'])
        and _same_ref(ref(__file__),schedule['adapter_ref']),'RL_2022_ORIGINAL_RECIPE_OR_OWNER_CHANGED')
    forecasts=schedule.get('upstream_forecast_refs');proof=schedule.get('causal_forecast_proof_ref')
    require(isinstance(forecasts,list) and forecasts and isinstance(proof,dict),'FINAL_2022_UPSTREAM_FORECAST_REFS_AND_CAUSAL_PROOF_REQUIRED')
    for r in [schedule['source_binding_ref'],proof,*forecasts]:require(_same_ref(ref(r['path']),r),'RL_2022_CAUSAL_SOURCE_PIN_CHANGED')
    with Path(proof['path']).open('rb') as f:meta=_JsonProjection(f).metadata_fields({'forecast_year','training_max_year','all_fit_and_labels_before','outer_development_rewards_used'})
    require(meta.get('forecast_year')==2022 and meta.get('training_max_year')==2021
        and meta.get('all_fit_and_labels_before')=='2022-01-01' and meta.get('outer_development_rewards_used') is False,
        'RL_2022_UPSTREAM_MUST_BE_FIT_BEFORE_2022_NO_2023_FORECAST_SUBSTITUTE')
    return schedule


_PRIVATE_AUX_2022=None

def private_auxiliary_owner_2022():
    """Only truthful contract/receipt year literals change, never gradient AST."""
    global _PRIVATE_AUX_2022
    if _PRIVATE_AUX_2022 is not None:return _PRIVATE_AUX_2022
    import copy,types
    from scripts.research.a2.training import consensus_auxiliary as A
    names=('environment_contract','fit_account_rl')
    source=ast.parse(Path(A.__file__).read_text(encoding='utf-8-sig'))
    nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
    original_nodes=copy.deepcopy(nodes);edits=Counter()
    for node in nodes:
        for item in ast.walk(node):
            if isinstance(item,ast.List) and [x.value if isinstance(x,ast.Constant) else None for x in item.elts]==[2021,2022]:
                item.elts=[ast.Constant(value=2022)];edits[node.name]+=1
    require(edits==dict(environment_contract=1,fit_account_rl=1),'RL_2022_METADATA_YEAR_ANCHORS_CHANGED')
    # Reversing the two metadata literals must reproduce the entire original AST,
    # including all PPO/REINFORCE updates, 12 epochs, optimizer, seed and rewards.
    restored=copy.deepcopy(nodes)
    for node in restored:
        for item in ast.walk(node):
            if isinstance(item,ast.List) and [x.value if isinstance(x,ast.Constant) else None for x in item.elts]==[2022]:item.elts=[ast.Constant(value=2021),ast.Constant(value=2022)]
    require(ast.dump(ast.Module(body=restored,type_ignores=[]))==ast.dump(ast.Module(body=original_nodes,type_ignores=[])),
        'RL_2022_NONMETADATA_ALGORITHM_AST_CHANGED')
    recipe=copy.deepcopy(A.RECIPE);recipe['reward_years']=[2022]
    ns={**vars(A),'RECIPE':recipe}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),A.__file__,'exec'),ns)
    ns['projection_identity']=dict(schema='RL_2022_ONLY_METADATA_YEAR_PROJECTION_R1',original_owner_ref=ref(A.__file__),
        adapter_ref=ref(__file__),metadata_literal_edits=dict(edits),gradient_ast_unchanged=True)
    _PRIVATE_AUX_2022=types.SimpleNamespace(**ns);return _PRIVATE_AUX_2022


def sourcecontract_template(loaded,schedule_ref):
    schedule=_schedule_2022(schedule_ref)
    require(loaded.get('source_qualified') is True and _same_ref(loaded['binding_ref'],schedule['source_binding_ref']),
        'RL_2022_ACTUAL_QUALIFIED_ACCOUNT_SOURCE_REQUIRED')
    contract=rl_environment_contract(loaded,segment_ids=('2022',))
    contract.update(causal_schedule_ref=schedule_ref,rl_2022_adapter_ref=ref(__file__),
        upstream_forecast_refs=schedule['upstream_forecast_refs'],causal_forecast_proof_ref=schedule['causal_forecast_proof_ref'])
    return contract


_ENVIRONMENT_2022=None

def account_environment_2022(loaded,policy_factory,schedule_ref):
    global _ENVIRONMENT_2022
    import types
    from scripts.research.a2.training import consensus_account_rl as bridge
    auxiliary=private_auxiliary_owner_2022();contract=sourcecontract_template(loaded,schedule_ref)
    if _ENVIRONMENT_2022 is None:
        init=types.FunctionType(bridge.AccountEnvironment.__init__.__code__,{**bridge.AccountEnvironment.__init__.__globals__,'auxiliary':auxiliary})
        class Environment2022(bridge.AccountEnvironment):
            def __init__(self,source_contract,episode_factory,activity_gate):init(self,source_contract,episode_factory,activity_gate)
        _ENVIRONMENT_2022=Environment2022
    factory=account_episode_factory(loaded,policy_factory,segment_ids=('2022',))
    return _ENVIRONMENT_2022(contract,factory,bridge.activity_delta_gate)


def fit_activity_policy_2022(method,environment,*,on_fit_started,schedule_ref):
    """Frozen schedule gate then the original close-in-finally fit adapter."""
    import types
    from scripts.research.a2.training import consensus_account_rl as bridge
    schedule=_schedule_2022(schedule_ref)
    require(_ENVIRONMENT_2022 is not None and isinstance(environment,_ENVIRONMENT_2022)
        and environment.source_contract.get('causal_schedule_ref')==schedule_ref
        and environment.source_contract.get('training_reward_years')==[2022]
        and [s['segment_id'] for s in environment.source_contract['reset_segments']]==['2022'],
        'SOURCE_GATED_2022_ONLY_ACCOUNT_ENVIRONMENT_REQUIRED')
    auxiliary=private_auxiliary_owner_2022()
    fit=types.FunctionType(bridge.fit_activity_policy.__code__,{**bridge.fit_activity_policy.__globals__,'auxiliary':auxiliary})
    result=fit(method,environment,on_fit_started=on_fit_started)
    if isinstance(result,auxiliary.RLFit):
        result.receipt.update(adapter_identity=auxiliary.projection_identity,causal_schedule_ref=schedule_ref,
            upstream_forecast_refs=schedule['upstream_forecast_refs'],training_reward_years=[2022])
    return result


def reference_metadata_scope():
    """Four exact historical provider identity queries; no prices/amounts."""
    state=json.loads((source_root()/'status.json').read_text(encoding='utf-8'))
    queries=[]
    for event in state['events']:
        key=event['original5field_key']
        if event['source_record_status']=='NO_EXACT_VENDOR_RECORD':
            require(key['ticker'] in ('MRSH','WTW'),'RL_REFERENCE_EXACT_KNOWN_GAPS_REQUIRED')
            queries.append(dict(event_id=event['event_id'],original5field_key=key,
                query=dict(search='Marsh' if key['ticker']=='MRSH' else 'Willis',date=key['effective_date'],market='stocks',locale='us',active='true',limit=50,sort='ticker',order='asc')))
    require(len(queries)==4,'RL_FOUR_EXACT_REFERENCE_METADATA_QUERIES_REQUIRED')
    return dict(schema='CONSENSUS_RL_FOUR_HISTORICAL_REFERENCE_METADATA_SCOPE_R1',task_id=TASK,
        status='FROZEN_AUTHORIZED_REFERENCE_METADATA_ONLY',source_binding_ref=ref(source_root()/'account_scope.json'),
        identity_witness_ref=ref(source_root()/'identity_binding.json'),endpoint='https://api.massive.com/v3/reference/tickers',
        dates_before=UPPER,queries=queries,numeric_price_or_cash_fields_forbidden=True,
        purpose='DISCOVER_HISTORICAL_TICKER_WITH_DATED_PROVIDER_UID_NO_ALIAS_GUESS',
        source_policy='FROZEN_HISTORY_MECHANISM_ONLY_UNKNOWN_VINTAGE_NOT_STRICT_PIT',producer_ref=ref(__file__))


def acquire_reference_metadata(scope_ref,*,key=None,request_get=None,gate=None):
    """Opaque custody + bounded reference identity metadata; no numeric decode."""
    require(_same_ref(ref(scope_ref['path']),scope_ref),'RL_REFERENCE_SCOPE_CHANGED')
    scope=json.loads(Path(scope_ref['path']).read_text(encoding='utf-8'))
    require(scope.get('schema')=='CONSENSUS_RL_FOUR_HISTORICAL_REFERENCE_METADATA_SCOPE_R1'
        and scope.get('status')=='FROZEN_AUTHORIZED_REFERENCE_METADATA_ONLY'
        and scope.get('numeric_price_or_cash_fields_forbidden') is True
        and scope.get('endpoint')=='https://api.massive.com/v3/reference/tickers','RL_EXACT_REFERENCE_METADATA_SCOPE_REQUIRED')
    for r in (scope['source_binding_ref'],scope['identity_witness_ref'],scope['producer_ref']):require(_same_ref(ref(r['path']),r),'RL_REFERENCE_SOURCE_PIN_CHANGED')
    if key is None:
        from scripts.storage.refresh_current_massive import load_api_key
        key=load_api_key(resolve())
    require(bool(key),'RL_REFERENCE_CREDENTIAL_UNAVAILABLE_NO_REQUEST')
    get=request_get or original.requests.get;wait=gate or original.wait_request;root=source_root()/'reference_metadata'
    allowed={'ticker','name','market','locale','type','active','primary_exchange','currency_name','cik','composite_figi','share_class_figi'}
    outcomes=[]
    for item in scope['queries']:
        q=item['query'];require(LOWER<=q['date']<UPPER and q['date']==item['original5field_key']['effective_date']
            and item['original5field_key']['ticker'] in ('MRSH','WTW') and q['search'] in ('Marsh','Willis'),'RL_REFERENCE_EXACT_DATED_KEY_REQUIRED')
        folder=root/item['event_id'];checkpoint=folder/'checkpoint.json'
        if checkpoint.exists():
            saved=json.loads(checkpoint.read_text(encoding='utf-8'));require(saved['query']==q,'RL_REFERENCE_RESUME_QUERY_CHANGED');outcomes.append(saved);continue
        wait(source_root(),minimum_interval=13)
        response=get(scope['endpoint'],params=q,headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=(15,45),allow_redirects=False)
        body=response.content;require(key.encode() not in body,'RL_REFERENCE_RESPONSE_SECRET_NOT_PERSISTED')
        raw_path=folder/('response_'+hashlib.sha256(body).hexdigest()+'.json');assert_safe_output_path(raw_path,kind='cache');raw_path.parent.mkdir(parents=True,exist_ok=True);raw_path.write_bytes(body)
        with io.BytesIO(body) as f:top=_JsonProjection(f).metadata_fields({'status','request_id','next_url'})
        rows=[]
        if response.status_code==200:
            with io.BytesIO(body) as f:
                p=_JsonProjection(f);p.descend(('results',));p.expect(b'[');p.white()
                while p.peek()!=b']':
                    rows.append(p.metadata_fields(allowed));require(len(rows)<=50,'RL_REFERENCE_MAX50_METADATA_ROWS')
                    p.white();sep=p.take()
                    if sep==b']':break
                    require(sep==b',','RL_REFERENCE_ARRAY_CHANGED');p.white()
        saved=dict(scope_ref=scope_ref,event_id=item['event_id'],original5field_key=item['original5field_key'],query=q,
            http_status=response.status_code,raw_ref=ref(raw_path),provider_status=top.get('status'),pagination_complete=not bool(top.get('next_url')),
            metadata=rows,numeric_fields_decoded=False,available_at='UNKNOWN',strict_PIT=False,alias_qualified=False)
        _write(checkpoint,saved);outcomes.append(saved)
    return outcomes


def capture_sec_identity_covers(scope_ref,*,request_get=None):
    """Only exact pre-ex SEC cover prefixes; collect named XBRL identity fields."""
    from html.parser import HTMLParser
    from scripts.storage.refresh_13f_quarter import configured_user_agent
    require(_same_ref(ref(scope_ref['path']),scope_ref),'RL_SEC_COVER_SCOPE_CHANGED')
    scope=json.loads(Path(scope_ref['path']).read_text(encoding='utf-8'))
    require(scope.get('schema')=='CONSENSUS_RL_THREE_PRE2023_SEC_IDENTITY_COVERS_R1'
        and scope.get('status')=='FROZEN_AUTHORIZED_IDENTITY_METADATA_PREFIX_ONLY'
        and scope.get('maximum_prefix_bytes') in (65536,524288),'RL_EXACT_SEC_COVER_SCOPE_REQUIRED')
    require(_same_ref(ref(scope['sec_index_ref']['path']),scope['sec_index_ref']),'RL_SEC_INDEX_PIN_CHANGED')
    class Cover(HTMLParser):
        def __init__(self):super().__init__();self.target=None;self.depth=0;self.values={}
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs);name=attrs.get('name','')
            if tag.lower()=='ix:nonnumeric' and name in ('dei:TradingSymbol','dei:EntityRegistrantName','dei:EntityCentralIndexKey','dei:Security12bTitle','dei:DocumentType'):
                self.target=name;self.depth=1;self.values.setdefault(name,[]).append('')
            elif self.target:self.depth+=1
        def handle_endtag(self,tag):
            if self.target:
                self.depth-=1
                if self.depth<=0:self.target=None
        def handle_data(self,data):
            if self.target:self.values[self.target][-1]+=data
    get=request_get or original.requests.get
    agent=configured_user_agent(resolve().repo_root/'scripts/v22/stage_sec_pit_taxonomy.py')
    limit=scope['maximum_prefix_bytes'];outcomes=[];root=source_root()/'sec_identity_covers'
    if limit!=65536:root=root/('prefix_limit_'+str(limit))
    for item in scope['documents']:
        require(item['accepted_at'][:10]<min(item['event_dates'])<UPPER and item['url'].startswith('https://www.sec.gov/Archives/edgar/data/'),
                'RL_SEC_COVER_PREEX_EXACT_SOURCE_REQUIRED')
        folder=root/item['accession'];checkpoint=folder/'checkpoint.json'
        if checkpoint.exists():outcomes.append(json.loads(checkpoint.read_text(encoding='utf-8')));continue
        original.wait_request(source_root(),minimum_interval=13)
        response=get(item['url'],headers={'User-Agent':agent,'Range':'bytes=0-'+str(limit-1)},timeout=(15,45),stream=True,allow_redirects=False)
        body=response.raw.read(limit,decode_content=True);response.close()
        prefix=folder/('prefix_'+hashlib.sha256(body).hexdigest()+'.html');assert_safe_output_path(prefix,kind='cache');prefix.parent.mkdir(parents=True,exist_ok=True);prefix.write_bytes(body)
        parser=Cover()
        if response.status_code in (200,206):parser.feed(body.decode('utf-8',errors='replace'))
        fields={k:[' '.join(x.split()) for x in v] for k,v in parser.values.items()}
        selected=item['expected_historical_ticker'] in fields.get('dei:TradingSymbol',[])
        ciks={x.lstrip('0') for x in fields.get('dei:EntityCentralIndexKey',[])}
        qualified=selected and str(item['cik']) in ciks and bool(fields.get('dei:EntityRegistrantName')) and bool(fields.get('dei:Security12bTitle'))
        saved=dict(scope_ref=scope_ref,source=item,http_status=response.status_code,original_prefix_ref=ref(prefix),prefix_bytes=len(body),
            full_original_body_claimed=False,identity_fields=fields,pre2023_historical_ticker_cover_verified=qualified,
            actual_payment_or_numeric_financial_fields_decoded=False,strict_PIT=False)
        _write(checkpoint,saved);outcomes.append(saved)
    return outcomes

def historical_alias_witness():
    """Join exact dated provider IDs to pre-ex SEC cover and raw listed CUSIP."""
    root=source_root();identity=json.loads((root/'identity_binding.json').read_text(encoding='utf-8'))
    refs=[];entries=[]
    for q in reference_metadata_scope()['queries']:
        cpref=ref(root/'reference_metadata'/q['event_id']/'checkpoint.json');cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'))
        require(cp['http_status']==200 and cp['pagination_complete'] and cp['numeric_fields_decoded'] is False,'RL_DATED_REFERENCE_METADATA_INCOMPLETE')
        key=q['original5field_key'];day=key['effective_date']
        covers=[]
        for path in (root/'sec_identity_covers'/'prefix_limit_524288').glob('*/checkpoint.json'):
            cover=json.loads(path.read_text(encoding='utf-8'));item=cover['source']
            if day not in item['event_dates']:continue
            require(cover['pre2023_historical_ticker_cover_verified'] and item['accepted_at'][:10]<day<UPPER,'RL_SEC_PREEX_TICKER_CLASS_WITNESS_REQUIRED')
            matching=[r for r in cp['metadata'] if r.get('ticker')==item['expected_historical_ticker'] and str(r.get('cik','')).lstrip('0')==str(item['cik']) and r.get('type')=='CS' and r.get('currency_name')=='usd']
            require(len(matching)==1,'RL_HISTORICAL_PROVIDER_CIK_AND_COMMON_UNIT_NOT_UNIQUE')
            row=next(x for x in identity['entries'] if x['original5field_key']==key)
            require(row['title_of_class'] in ('COM','SHS') and row['raw_coordinate']=='RAW_ACTUAL_SHARE','RL_ALIAS_LISTED_SHARE_CLASS_NOT_COMMON_OR_ORDINARY')
            coverref=ref(path);refs.extend((cpref,coverref,cover['original_prefix_ref']))
            covers.append(dict(event_id=q['event_id'],original5field_key=key,provider_ticker=matching[0]['ticker'],provider_CIK=item['cik'],
                provider_reference_metadata_ref=cpref,preex_SEC_identity_ref=coverref,preex_SEC_accepted_at=item['accepted_at'],
                exact_raw_identity_ref=ref(root/'identity_binding.json'),accounting_sid=row['accounting_sid'],cusip=row['cusip'],
                raw_listed_class=row['title_of_class'],share_unit_conversion_applied=False,strict_PIT=False))
        require(len(covers)==1,'RL_UNIQUE_PREEX_HISTORICAL_TICKER_COVER_REQUIRED');entries.extend(covers)
    require(len(entries)==4,'RL_FOUR_HISTORICAL_ALIAS_WITNESSES_REQUIRED')
    return dict(schema='CONSENSUS_RL_FOUR_EXACT_HISTORICAL_PROVIDER_TICKER_WITNESSES_R1',task_id=TASK,
        status='FROZEN_AUTHORIZED_EXACT_HISTORICAL_TICKER_SOURCE_ROUTE',entries=entries,source_refs=refs,
        historical_vintage='UNKNOWN',strict_PIT=False,share_unit_conversion_applied=False,producer_ref=ref(__file__))


def _alias_routes(witness_ref):
    require(_same_ref(ref(witness_ref['path']),witness_ref),'RL_ALIAS_WITNESS_CHANGED')
    witness=json.loads(Path(witness_ref['path']).read_text(encoding='utf-8'))
    require(witness.get('schema')=='CONSENSUS_RL_FOUR_EXACT_HISTORICAL_PROVIDER_TICKER_WITNESSES_R1'
        and witness['status']=='FROZEN_AUTHORIZED_EXACT_HISTORICAL_TICKER_SOURCE_ROUTE'
        and len(witness['entries'])==4 and witness['share_unit_conversion_applied'] is False,'RL_EXACT_FROZEN_ALIAS_SCOPE_REQUIRED')
    for r in witness['source_refs']:require(_same_ref(ref(r['path']),r),'RL_ALIAS_SOURCE_PIN_CHANGED')
    return {_digest(x['original5field_key']):dict(x,witness_ref=witness_ref) for x in witness['entries']}


def capture_historical_alias_cash(witness_ref,*,key=None,request_get=None,gate=None):
    """Four exact ex-date keys, two original-provider ticker windows."""
    routes=_alias_routes(witness_ref);root=source_root()/'historical_alias_cash';acquire=_acquirer()
    if key is None:
        from scripts.storage.refresh_current_massive import load_api_key
        key=load_api_key(resolve())
    require(bool(key),'RL_ALIAS_CREDENTIAL_UNAVAILABLE_NO_ATTEMPT')
    groups={}
    for entry in routes.values():groups.setdefault(entry['provider_ticker'],[]).append(entry)
    outcomes=[]
    for ticker,entries in groups.items():
        dates=sorted(x['original5field_key']['effective_date'] for x in entries);kwargs={}
        if request_get is not None:kwargs['request_get']=request_get
        if gate is not None:kwargs['gate']=gate
        result,count=acquire(ticker=ticker,start_date=dates[0],end_date=dates[-1],target_dates=dates,key=key,root=root,paths=resolve(),**kwargs)
        cpref=ref(root/'windows'/ticker/'checkpoint.json')
        outcomes.append(dict(provider_ticker=ticker,events=[x['event_id'] for x in entries],checkpoint_ref=cpref,
            actual_attempt_count=len(result['attempts']),requests_made_this_invocation=count,status=result['status'],
            exact_component_count=len(result.get('records',[])),metadata_rejections=result.get('rejected_target_metadata',[])))
    return outcomes


def prepare_alias_native_facts(witness_ref):
    from decimal import Decimal
    root=source_root();routes=_alias_routes(witness_ref);identity_ref=ref(root/'identity_binding.json');identity=json.loads(Path(identity_ref['path']).read_text(encoding='utf-8'))
    native=_native_binder(identity,aliases=routes);facts=[];sources=[witness_ref,identity_ref];events=[]
    for entry in routes.values():
        cpref=ref(root/'historical_alias_cash'/'windows'/entry['provider_ticker']/'checkpoint.json');cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'))
        key=entry['original5field_key'];day=key['effective_date'];components=[]
        for attempt in cp['attempts']:
            if attempt.get('http_status')!=200:continue
            rawref=attempt['raw_ref'];require(_same_ref(ref(rawref['path']),rawref),'RL_ALIAS_RAW_PIN_CHANGED')
            query=cp['contract']['query'];selected=project_dividends(Path(rawref['path']).read_bytes(),ticker=entry['provider_ticker'],
                start_date=query['ex_dividend_date.gte'],end_date=query['ex_dividend_date.lte'],target_dates=[day])
            for record in selected['records']:
                components.append(dict(record=record,raw_ref=rawref,checkpoint_ref=cpref,pagination_complete=cp['pagination_complete'],original_cash_amount_decimal=str(Decimal(str(record['cash_amount'])))))
            sources.append(rawref)
        if not components:
            events.append(dict(event_id=entry['event_id'],status='ATTEMPTED_NO_ELIGIBLE_EXACT_ORIGINAL_COMPONENT'));continue
        fact=_native_fact(dict(original5field_key=key),components,identity_ref,identity)
        fact.update(provider_ticker=entry['provider_ticker'],provider_identity_alias_ref=witness_ref)
        factref=_write(root/'historical_alias_cash'/'native_facts'/(entry['event_id']+'.json'),fact)
        typed=native._vendor_fact_event(private_cash_owner(),fact,factref)
        facts.append(factref);sources.append(cpref);events.append(dict(event_id=entry['event_id'],status='ORIGINAL_VENDOR_NATIVE_TYPED_FACT_BOUND',fact_ref=factref,event_fingerprint=typed.event_fingerprint))
    return dict(event_projection_refs=facts,source_refs=sources,source_alias_witness_ref=witness_ref,events=events)


def qualified_daily_returns(reader,pool):
    """Original daily100 eligibility, exact date/name projections before ret_1d."""
    import copy,numpy as np,pandas as pd
    from scripts.research.a2.training.stateful_inputs import ALLOWED_SOURCES
    from scripts.research.a2.training.stateful_values import digest
    pool=pool[['signal_date','ticker']].copy();pool.signal_date=pd.to_datetime(pool.signal_date)
    require(not pool.empty and pool.signal_date.ge(LOWER).all() and pool.signal_date.lt(UPPER).all()
        and not pool.duplicated(['signal_date','ticker']).any(),'RL_RETURN_EXACT_2021_2022_POOL_REQUIRED')
    flags=reader.read('prediction_features',['signal_date','ticker','feature_available','feature_source'],
        date_field='signal_date',start=LOWER,stop=UPPER,tickers=sorted(set(pool.ticker)))
    require(not flags.duplicated(['signal_date','ticker']).any(),'RL_RETURN_PREDICTION_METADATA_AMBIGUOUS')
    flags.signal_date=pd.to_datetime(flags.signal_date)
    keys=pool.merge(flags,on=['signal_date','ticker'],how='inner',validate='one_to_one')
    keys=keys.loc[keys.feature_available.eq(True)&keys.feature_source.isin(ALLOWED_SOURCES)].copy()
    require(not keys.empty,'RL_NO_CAUSAL_DAILY100_RETURN_KEYS')
    parts=[]
    for day,group in keys.groupby('signal_date',sort=True):
        # ProjectedReader binds the physical pre2026 pin, then exact day/names.
        # Metadata uniqueness above means no ineligible duplicate shares this key.
        parts.append(reader.read('prediction_features',['signal_date','ticker','ret_1d'],
            date_field='signal_date',start=LOWER,stop=UPPER,day=day,tickers=sorted(set(group.ticker))))
    vectors=pd.concat(parts,ignore_index=True);vectors.signal_date=pd.to_datetime(vectors.signal_date)
    legal=keys[['signal_date','ticker']].merge(vectors,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(len(legal)==len(keys) and np.isfinite(legal.ret_1d.to_numpy(float)).all(),'RL_NONFINITE_OR_MISSING_QUALIFIED_DAILY_RETURN')
    record=reader.sources['prediction_features'];require(isinstance(record,dict),'RL_SINGLE_RETURN_SOURCE_PIN_REQUIRED')
    source=dict(path=record['path'],sha256=record['sha256'])
    returns=legal.pivot(index='signal_date',columns='ticker',values='ret_1d').sort_index()
    returns.attrs.update(source_id=digest(source),source_ref=copy.deepcopy(source),unit='DAILY_DECIMAL_RETURN',
        eligibility='CURRENT_DAILY100_QUALIFIED_KEYS; monthly owner fits only current decision assets plus held')
    return returns


def publish_alias_completion(witness_ref):
    """New immutable extension binding; retain baseline capture/fact custody."""
    root=source_root();packet=prepare_alias_native_facts(witness_ref)
    producer=ref(__file__);custody=root/'owner_custody'/('account_owner_'+producer['sha256'][:12]+'.py')
    assert_safe_output_path(custody,kind='cache');custody.write_bytes(Path(__file__).read_bytes())
    bundle=dict(schema=NATIVE_SCHEMA,completion_binder_owner_ref=producer,event_projection_refs=packet['event_projection_refs'],
        source_refs=packet['source_refs'],source_alias_witness_ref=witness_ref)
    bundle_ref=_write(root/('completion_bundle_'+_digest(bundle)[:16]+'.json'),bundle)
    baseline_ref=ref(root/'account_scope.json');binding=json.loads(Path(baseline_ref['path']).read_text(encoding='utf-8'))
    binding.update(producer_ref=producer,baseline_account_scope_ref=baseline_ref,completion_bundle_ref=bundle_ref,
        native_fact_count=binding['native_fact_count']+len(packet['event_projection_refs']))
    binding_ref=_write(root/('account_scope_'+_digest(binding)[:16]+'.json'),binding)
    state=json.loads((root/'status.json').read_text(encoding='utf-8'));byid={e['event_id']:e for e in state['events']}
    for result in packet['events']:
        row=byid[result['event_id']];row['completion_attempted']=True;row['completion_status']=result['status']
        if result['status']=='ORIGINAL_VENDOR_NATIVE_TYPED_FACT_BOUND':
            row.update(native_fact_qualified=True,native_fact_ref=result['fact_ref'],typed_event_fingerprint=result['event_fingerprint'],
                qualification_status='HISTORICAL_PROVIDER_TICKER_NATIVE_FACT_BOUND',missing_witnesses=[])
    state['qualification_summary'].update(native_cash_facts_qualified=binding['native_fact_count'],account_source_binding_ref=binding_ref,
        unresolved_exact_pool_events=sum(not e.get('native_fact_qualified',False) for e in state['events']))
    state['historical_alias_completion']=dict(witness_ref=witness_ref,bundle_ref=bundle_ref,account_source_binding_ref=binding_ref,
        qualified_events=len(packet['event_projection_refs']),actual_loader_validated=False)
    _write(root/'status.json',state)
    return binding_ref


def capture_declared_physical_sources(scope_ref,*,request_get=None):
    """Exact pre-ex originals, bounded opaque custody; no financial scalar parse."""
    from scripts.storage.refresh_13f_quarter import configured_user_agent
    require(_same_ref(ref(scope_ref['path']),scope_ref),'RL_DECLARED_PHYSICAL_SCOPE_CHANGED')
    scope=json.loads(Path(scope_ref['path']).read_text(encoding='utf-8'))
    require(scope['schema']=='CONSENSUS_RL_THREE_EXACT_DECLARED_CASH_PHYSICAL_UNIT_SCOPE_R1'
        and scope['status']=='FROZEN_AUTHORIZED_PREEX_ORIGINAL_UNIT_AND_DECLARATION'
        and len(scope['documents'])==3,'RL_EXACT_THREE_DECLARED_PHYSICAL_SCOPE_REQUIRED')
    for r in (scope['sec_index_ref'],scope['declaration_metadata_ref']):require(_same_ref(ref(r['path']),r),'RL_DECLARED_METADATA_PIN_CHANGED')
    get=request_get or original.requests.get;agent=configured_user_agent(resolve().repo_root/'scripts/v22/stage_sec_pit_taxonomy.py')
    outcomes=[]
    for item in scope['documents']:
        require(item['accepted_at_utc'][:10]<item['original5field_key']['effective_date']<UPPER
            and item['publication_date']<item['original5field_key']['effective_date'],'RL_DECLARED_PREEX_SOURCE_REQUIRED')
        folder=source_root()/'declaration_sources'/item['original5field_key']['ticker'];checkpoint=folder/'physical_checkpoint.json'
        if checkpoint.exists():outcomes.append(json.loads(checkpoint.read_text(encoding='utf-8')));continue
        received=[]
        roles=[('SEC_HEADER',item['submission_url'],65536,item['accession']+'.txt'),
            ('SEC_UNIT_PRIMARY',item['SEC_url'],2097152,item['primary_member']),
            ('ISSUER_DECLARATION',item['issuer_declaration_url'],524288,'declaration_original_prefix.html')]
        for role,url,limit,name in roles:
            original.wait_request(source_root(),minimum_interval=13)
            response=get(url,headers={'User-Agent':agent,'Range':'bytes=0-'+str(limit-1)},timeout=(15,45),stream=True,allow_redirects=False)
            body=response.raw.read(limit,decode_content=True);response.close()
            target=folder/name;assert_safe_output_path(target,kind='cache');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            received.append(dict(role=role,url=url,http_status=response.status_code,prefix_ref=ref(target),maximum_bytes=limit,received_bytes=len(body),full_original_body_claimed=False))
        saved=dict(scope_ref=scope_ref,source=item,attempts=received,numeric_financial_scalar_decoded=False,
            actual_2023_payment_or_reward_read=False,strict_PIT=False)
        _write(checkpoint,saved);outcomes.append(saved)
    return outcomes


DECLARED_SCHEMA='CONSENSUS_RL_PRE2023_ORIGINAL_ISSUER_DECLARED_NATIVE_BUNDLE_R1'


def _declared_fact_validator(identity,supports,capsules):
    """Same original physical/unit/money validators with exact new case custody."""
    import copy,types
    from scripts.research.a2.data import consensus_declared_cash_source_completion as D
    native=_native_binder(identity)
    def submission(support):
        candidates=[x for x in supports.values() if x['issuer_CIK']==support['issuer_CIK'] and x['accession']==support['accession']]
        require(len(candidates)==1,'RL_EXACT_DATED_COMMON_UNIT_SOURCE_VERSION_REQUIRED')
        original=types.FunctionType(D._declared_unit_submission.__code__,{**D._declared_unit_submission.__globals__,'APPROVED_UNIT_SUPPORTS':{support['issuer_CIK']:candidates[0]}})
        return original(support)
    unit=types.FunctionType(D._declared_common_usd_unit.__code__,{**D._declared_common_usd_unit.__globals__,'_declared_unit_submission':submission})
    def mature_reward(fact):
        if fact.get('source_kind')!='ISSUER_PRE2023_REALIZED_FIXED_USD_RAW_LISTED_CASH':return False
        r=fact['frozen_mature_reward_scope_ref'];require(_same_ref(ref(r['path']),r),'RL_MATURE_REWARD_SCOPE_CHANGED')
        scope=json.loads(Path(r['path']).read_text(encoding='utf-8'))
        require(scope['schema']=='CONSENSUS_RL_TWO_FCX_2022_POSTVERIFIED_REWARD_CASH_SCOPE_R1'
            and scope['status']=='FROZEN_AUTHORIZED_EXACT_2022_MATURE_REWARD_SOURCE'
            and scope['training_reward_cutoff_exclusive']==UPPER and scope['ordinary_cash_classification_inferred'] is False,
            'RL_EXACT_MATURE_2022_REWARD_SCOPE_REQUIRED')
        entries=[x for x in scope['documents'] if x['original5field_key']==fact['original5field_key']]
        require(len(entries)==1 and entries[0]['SEC_url']==fact['original_issuer_source_url']
            and entries[0]['issuer_CIK']==fact['common_usd_unit_support']['issuer_CIK']==831259
            and fact['ticker']=='FCX' and '2022-01-01'<=fact['ex_date']<=fact['record_date']<=fact['pay_date']<UPPER
            and fact['pay_date']<=fact['source_SEC_accepted_at'][:10]<UPPER
            and fact['reward_mature_at']==fact['source_SEC_accepted_at'] and fact['asof_policy_input_allowed'] is False
            and fact['ordinary_cash_classification_inferred'] is False,'RL_REALIZED_CASH_AND_PUBLICATION_MUST_MATURE_BEFORE_TRAINING_CUTOFF')
        return True
    def publication_eligible(fact):return mature_reward(fact) or publication_day(fact)<fact['ex_date']
    def realization_flag(fact):return fact.get('actual_payment_status_read') is (True if mature_reward(fact) else False)
    def unit_before(fact):return (UPPER if mature_reward(fact) else fact['ex_date'])+'T00:00:00+00:00'
    def validated_numbers(fact,text,numbers):
        if not mature_reward(fact):return numbers
        from decimal import Decimal
        import re
        pattern=r'quarterly cash dividends totaling \$\s*([0-9.]+) per share \(\$\s*([0-9.]+) per share base dividend and \$\s*([0-9.]+) per share variable dividend\) on its common stock, which were paid on'
        m=re.search(pattern,text)
        require(m is not None and len(numbers)==3 and list(m.groups())==numbers,'RL_FCX_EXACT_TOTAL_BASE_VARIABLE_ORIGINAL_ROLE_REQUIRED')
        values=[Decimal(x) for x in numbers]
        require(all(x.is_finite() and x>0 for x in values) and values[0]==sum(values[1:],Decimal(0)),'RL_FCX_ORIGINAL_TOTAL_COMPONENT_SUM_MUST_AGREE')
        require([x['original_cash_amount_decimal'] for x in fact['issuer_components']]==numbers[1:]
            and len({x['record']['id'] for x in fact['issuer_components']})==2,'RL_FCX_TWO_ORIGINAL_COMPONENTS_CREDIT_TOTAL_ONCE')
        return numbers[:1]
    def exact_capsule(fact):
        capsule_ref=capsules.get(_digest(fact['original5field_key']))
        require(capsule_ref is not None and fact['approved_current_capsule_ref']==capsule_ref,'RL_EXACT_DECLARED_CAPSULE_REQUIRED')
        require(_same_ref(ref(capsule_ref['path']),capsule_ref),'RL_DECLARED_CAPSULE_CHANGED')
        capsule=json.loads(Path(capsule_ref['path']).read_text(encoding='utf-8'))
        fields=('original5field_key','original_current_source_ref','current_cash_fragment_ref','current_cash_physical_range','current_original_cash_text',
            'record_date','pay_date','common_usd_unit_support','original_issuer_source_url')
        fields=fields+(('source_SEC_accepted_at',) if fact['primary_source_provider']=='ISSUER_FILED_SEC_ORIGINAL' else ('declaration_displayed_date',))
        require(all(fact[k]==capsule[k] for k in fields),'RL_DECLARED_EXACT_PHYSICAL_SOURCE_CAPSULE_CHANGED:'+','.join(k for k in fields if fact[k]!=capsule[k]))
        require(publication_eligible(fact) and fact['ex_date']<UPPER and capsule.get('source_displayed_date_verified',capsule.get('source_SEC_acceptance_verified')) is True,'RL_DECLARED_PREEX_PUBLICATION_REQUIRED')
        return True
    def publication_day(fact):
        if fact['primary_source_provider']=='ISSUER_FILED_SEC_ORIGINAL':
            require(fact['source_SEC_accepted_at']==fact['common_usd_unit_support']['accepted_at_utc'],'RL_SEC_DECLARATION_SAME_ORIGINAL_HEADER_REQUIRED')
            return fact['source_SEC_accepted_at'][:10]
        return fact['declaration_displayed_date']
    node=copy.deepcopy(next(n for n in ast.parse(Path(D.__file__).read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='_declared_fact_event'))
    first=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='require' and "fact.get('schema')" in ast.unparse(n))
    require(first==8,'RL_DECLARED_ORIGINAL_CASE_PREFIX_ANCHOR_CHANGED')
    node.body=[node.body[0],ast.parse("require(_exact_capsule(fact),'RL_DECLARED_CAPSULE_REQUIRED')").body[0],node.body[7],*node.body[first:]]
    edits=_date_tree(node);require(edits==dict(lower=1,upper=1),'RL_DECLARED_ONLY_DATE_ANCHORS_CHANGED')
    class SECMetadataRoute(ast.NodeTransformer):
        def __init__(self):self.edits=Counter()
        def visit_Tuple(self,n):
            if [x.value if isinstance(x,ast.Constant) else None for x in n.elts]==['ISSUER_IR','ISSUER_AUTHENTICATED_WIRE']:
                n.elts.append(ast.Constant(value='ISSUER_FILED_SEC_ORIGINAL'));self.edits['provider']+=1
            return self.generic_visit(n)
        def visit_Subscript(self,n):
            if isinstance(n.value,ast.Name) and n.value.id=='fact' and isinstance(n.slice,ast.Constant) and n.slice.value=='declaration_displayed_date':
                self.edits['clock']+=1;return ast.Call(func=ast.Name(id='_publication_day',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[])
            return self.generic_visit(n)
    route=SECMetadataRoute();node=route.visit(node);require(route.edits==dict(provider=1,clock=1),'RL_DECLARED_SEC_METADATA_ONLY_ANCHORS_CHANGED')
    class MatureRewardRoute(ast.NodeTransformer):
        def __init__(self):self.edits=Counter()
        def visit_Compare(self,n):
            self.generic_visit(n)
            if isinstance(n.left,ast.Call) and isinstance(n.left.func,ast.Name) and n.left.func.id=='_publication_day':
                self.edits['clock']+=1;return ast.Call(func=ast.Name(id='_publication_eligible',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[])
            if isinstance(n.left,ast.Call) and isinstance(n.left.func,ast.Attribute) and isinstance(n.left.func.value,ast.Name) and n.left.func.value.id=='fact' and n.left.func.attr=='get' and len(n.left.args)==1 and isinstance(n.left.args[0],ast.Constant):
                field=n.left.args[0].value
                extra={'schema':'CONSENSUS_RL_2022_REALIZED_ISSUER_USD_RAW_CASH_FACT_R1','source_kind':'ISSUER_PRE2023_REALIZED_FIXED_USD_RAW_LISTED_CASH','amount_source_role':'ORIGINAL_2022_ISSUER_REPORTED_REALIZED_CASH_NOT_ASOF_INPUT'}
                if field in extra:
                    require(len(n.comparators)==1 and isinstance(n.ops[0],ast.Eq),'RL_MATURE_REWARD_SOURCE_ROLE_ANCHOR_CHANGED')
                    n.ops=[ast.In()];n.comparators=[ast.Tuple(elts=[n.comparators[0],ast.Constant(value=extra[field])],ctx=ast.Load())];self.edits[field]+=1
                elif field=='actual_payment_status_read':
                    self.edits['realization']+=1;return ast.Call(func=ast.Name(id='_realization_flag',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[])
            return n
        def visit_Call(self,n):
            self.generic_visit(n)
            if isinstance(n.func,ast.Name) and n.func.id=='_declared_common_usd_unit':
                k=next(k for k in n.keywords if k.arg=='before');k.value=ast.Call(func=ast.Name(id='_unit_before',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load())],keywords=[]);self.edits['unit_clock']+=1
            return n
        def visit_Assign(self,n):
            self.generic_visit(n)
            if len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='numbers':
                n.value=ast.Call(func=ast.Name(id='_validated_numbers',ctx=ast.Load()),args=[ast.Name(id='fact',ctx=ast.Load()),ast.Name(id='text',ctx=ast.Load()),n.value],keywords=[]);self.edits['numbers']+=1
            return n
    reward_route=MatureRewardRoute();node=reward_route.visit(node)
    require(reward_route.edits==dict(schema=1,source_kind=1,amount_source_role=1,clock=1,realization=1,unit_clock=1,numbers=1),'RL_MATURE_REWARD_METADATA_AND_COMPONENT_ANCHORS_CHANGED')
    ns={**vars(D),'_declared_identity':native._vendor_identity,'_declared_common_usd_unit':unit,'_exact_capsule':exact_capsule,'_publication_day':publication_day,
        '_publication_eligible':publication_eligible,'_realization_flag':realization_flag,'_unit_before':unit_before,'_validated_numbers':validated_numbers}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),__file__,'exec'),ns)
    return ns['_declared_fact_event']


def prepare_declared_native_facts():
    """Bind only original common-share USD unit witnesses actually present."""
    import re,pandas as pd
    from decimal import Decimal
    from scripts.storage.refresh_sec_event_originals import FilingText
    from scripts.research.a2.data import consensus_declared_cash_source_completion as D
    root=source_root();identity_ref=ref(root/'identity_binding.json');identity=json.loads(Path(identity_ref['path']).read_text(encoding='utf-8'))
    index_ref=ref(root/'declaration_sources'/'index.json');index=json.loads(Path(index_ref['path']).read_text(encoding='utf-8'))
    supports={};capsules={};facts=[];events=[];sources=[identity_ref,index_ref]
    pattern=rb'<ix:nonFraction\b[^>]*name="(us-gaap:CommonStockDividendsPerShare(?:Declared|CashPaid))"[^>]*>'
    for entry in index['entries']:
        key=entry['original5field_key'];ticker=key['ticker']
        if entry['status']!='CAPTURED_TARGET_DECLARATION_FRAGMENT':continue
        folder=root/'declaration_sources'/ticker;cpref=ref(folder/'physical_checkpoint.json');cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'))
        byrole={a['role']:a for a in cp['attempts']};physical=byrole['SEC_UNIT_PRIMARY']['prefix_ref']
        extension=folder/'unit_extent'/'checkpoint.json'
        if extension.exists():physical=json.loads(extension.read_text(encoding='utf-8'))['original_prefix_ref'];sources.append(ref(extension))
        require(all(a['http_status'] in (200,206) for a in byrole.values()),'RL_DECLARED_ORIGINAL_HTTP_NOT_AVAILABLE')
        support=_declared_unit_support(cp,physical,byrole['SEC_HEADER']['prefix_ref'],folder)
        if support is None:
            events.append(dict(event_id=entry['event_id'],status='ATTEMPTED_COMMON_USD_PER_SHARE_ORIGINAL_UNIT_WITNESS_MISSING',typed_fact_qualified=False));continue
        supports[support['issuer_CIK']]=support
        irref=byrole['ISSUER_DECLARATION']['prefix_ref'];ir=Path(irref['path']).read_bytes()
        literal={'AAPL':b'board of directors has declared a cash dividend','JPM':b'The Board of Directors of JPMorgan Chase'}
        require(ticker in literal,'RL_NEW_DECLARATION_NEEDS_EXACT_PHYSICAL_PROFILE')
        anchor=ir.find(literal[ticker]);require(anchor>=0,'RL_DECLARED_CURRENT_CASH_ANCHOR_NOT_FOUND')
        if ticker=='AAPL':a=ir.rfind(b'<div',0,anchor);z=ir.find(b'</div>',anchor)+6
        else:a=ir.rfind(b'<p',0,anchor);z=ir.find(b'</p>',anchor)+4
        require(0<=a<z<=len(ir) and z-a<=4096,'RL_DECLARED_ONE_BOUNDED_PHYSICAL_COMMON_CLAUSE')
        fragment=ir[a:z];fragment_ref=_write_binary(folder/'current_common_cash.physical',fragment)
        parser=FilingText();parser.feed(fragment.decode('utf-8'));text=' '.join(' '.join(parser.parts).split())
        pub=pd.Timestamp(entry['publication_date']);display=pub.strftime('%B ')+str(pub.day)+pub.strftime(', %Y')
        require(display.encode() in ir and entry['publication_date']<key['effective_date'],'RL_ORIGINAL_PAGE_PREEX_DISPLAY_DATE_REQUIRED')
        def date_literal(value):
            d=pd.Timestamp(value);return d.strftime('%B ')+str(d.day)+d.strftime(', %Y')
        record_literal=date_literal(entry['record_date']);pay_literal=date_literal(entry['pay_date'])
        # Currency/common-unit guards execute before selecting a money token.
        import types
        sub=types.FunctionType(D._declared_unit_submission.__code__,{**D._declared_unit_submission.__globals__,'APPROVED_UNIT_SUPPORTS':supports})
        unitcheck=types.FunctionType(D._declared_common_usd_unit.__code__,{**D._declared_common_usd_unit.__globals__,'_declared_unit_submission':sub})
        unitcheck(support,before=key['effective_date']+'T00:00:00+00:00')
        require('common stock' in text and record_literal in text and pay_literal in text and 'declared' in text,'RL_DECLARED_COMMON_SHARE_AND_DATE_LITERALS_REQUIRED')
        amounts=re.findall(r'\$\s*([0-9]*\s*\.\s*[0-9]+|[0-9]+)',text);require(len(amounts)==1,'RL_DECLARED_SINGLE_ORIGINAL_CASH_TOKEN_REQUIRED')
        amount=str(Decimal(re.sub(r'\s+','',amounts[0])))
        sid=next(e['accounting_sid'] for e in identity['entries'] if e['original5field_key']==key)
        fact=dict(schema=D.FACT_SCHEMA,source_kind='ISSUER_PRE2026_DECLARED_FIXED_USD_RAW_LISTED_CASH',primary_source_provider='ISSUER_IR',
            amount_source_role='ORIGINAL_PRE2026_ISSUER_DECLARATION_NOT_VENDOR_PAYMENT_RESULT',original5field_key=key,ticker=ticker,accounting_sid=sid,
            ex_date=key['effective_date'],record_date=entry['record_date'],pay_date=entry['pay_date'],declaration_displayed_date=entry['publication_date'],
            original_raw_identity_links_ref=identity_ref,original_current_source_ref=irref,current_cash_fragment_ref=fragment_ref,current_cash_physical_range=[a,z],
            current_original_cash_text=text,common_usd_unit_support=support,record_literal=record_literal,pay_literal=pay_literal,current_action_literal='declared',current_common_literal='common stock',
            declared_cash_amount_decimal=amount,currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',
            available_at=None,strict_PIT=False,actual_payment_status_read=False,vendor_payment_amount_read=False,original_issuer_source_url=entry['url'],
            source_displayed_date_verified=True,issuer_components=[dict(record=dict(id='ISSUER_DECLARATION:'+fragment_ref['sha256']),original_source_ref=irref)])
        capsuleref=_write(folder/'exact_declared_capsule.json',fact);capsules[_digest(key)]=capsuleref
        fact['approved_current_capsule_ref']=capsuleref;factref=_write(folder/'native_declared_fact.json',fact)
        validator=_declared_fact_validator(identity,supports,capsules);typed=validator(private_cash_owner(),fact,factref)
        facts.append(factref);sources.extend((cpref,physical,byrole['SEC_HEADER']['prefix_ref'],irref,capsuleref));events.append(dict(event_id=entry['event_id'],status='ORIGINAL_ISSUER_DECLARED_NATIVE_TYPED_FACT_BOUND',typed_fact_qualified=True,fact_ref=factref,event_fingerprint=typed.event_fingerprint))
    sec=_prepare_sec_declared_facts(identity_ref,identity)
    fcx=_prepare_fcx_realized_facts(identity_ref,identity)
    for k in ('event_projection_refs','source_refs','events'):sec[k].extend(fcx[k])
    sec['declared_supports'].update(fcx['declared_supports']);sec['declared_capsules'].update(fcx['declared_capsules'])
    facts.extend(sec['event_projection_refs']);sources.extend(sec['source_refs']);supports.update(sec['declared_supports']);capsules.update(sec['declared_capsules']);events.extend(sec['events'])
    return dict(event_projection_refs=facts,source_refs=sources,declared_supports={str(k):v for k,v in supports.items()},declared_capsules=capsules,events=events)


def _write_binary(path,body):
    assert_safe_output_path(path,kind='cache');Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_bytes(body);return ref(path)


def publish_declared_completion(previous_binding_ref):
    """Add qualified original declarations; all unresolved exact keys stay blocked."""
    require(_same_ref(ref(previous_binding_ref['path']),previous_binding_ref),'RL_PRIOR_ACCOUNT_BINDING_CHANGED')
    root=source_root();packet=prepare_declared_native_facts();producer=ref(__file__)
    _write_binary(root/'owner_custody'/('account_owner_'+producer['sha256'][:12]+'.py'),Path(__file__).read_bytes())
    bundle=dict(schema=DECLARED_SCHEMA,completion_binder_owner_ref=producer,**{k:packet[k] for k in ('event_projection_refs','source_refs','declared_supports','declared_capsules')})
    bundle_ref=_write(root/('completion_declared_bundle_'+_digest(bundle)[:16]+'.json'),bundle)
    binding=json.loads(Path(previous_binding_ref['path']).read_text(encoding='utf-8'))
    previous_declared_count=0
    if binding.get('declared_completion_bundle_ref'):
        previous_declared_count=len(json.loads(Path(binding['declared_completion_bundle_ref']['path']).read_text(encoding='utf-8'))['event_projection_refs'])
    binding.update(producer_ref=producer,prior_account_scope_ref=previous_binding_ref,declared_completion_bundle_ref=bundle_ref,
        native_fact_count=binding['native_fact_count']-previous_declared_count+len(packet['event_projection_refs']))
    binding['retained_unsupported_count']=132-binding['native_fact_count']
    binding['unsupported_count_scope']='EXACT_132_FROZEN_POOL_KEYS_NOT_ALL_PERSISTENT_HOLDINGS'
    binding_ref=_write(root/('account_scope_'+_digest(binding)[:16]+'.json'),binding)
    state=json.loads((root/'status.json').read_text(encoding='utf-8'));byid={e['event_id']:e for e in state['events']}
    index=json.loads((root/'declaration_sources'/'index.json').read_text(encoding='utf-8'))
    for entry in index['entries']:
        row=byid[entry['event_id']];row.update(completion_attempted=True,declaration_source_status=entry['status'],declaration_HTTP_status=entry['http_status'])
    for result in packet['events']:
        row=byid[result['event_id']];row['completion_status']=result['status']
        if result['typed_fact_qualified']:
            row.update(native_fact_qualified=True,native_fact_ref=result['fact_ref'],typed_event_fingerprint=result['event_fingerprint'],
                qualification_status='ORIGINAL_ISSUER_DECLARED_NATIVE_TYPED_FACT_BOUND',missing_witnesses=[])
        else:row['missing_witnesses']=['ORIGINAL_COMMON_USD_PER_SHARE_UNIT_WITNESS']
    state['qualification_summary'].update(native_cash_facts_qualified=binding['native_fact_count'],account_source_binding_ref=binding_ref,
        unresolved_exact_pool_events=sum(not e.get('native_fact_qualified',False) for e in state['events']))
    state['declared_completion']=dict(bundle_ref=bundle_ref,account_source_binding_ref=binding_ref,qualified_events=len(packet['event_projection_refs']),actual_loader_validated=False)
    _write(root/'status.json',state)
    return binding_ref


def _declared_unit_support(cp,physical,header_source,folder,*,require_preex=True):
    import re,pandas as pd
    pattern=rb'<ix:nonFraction\b[^>]*name="(us-gaap:CommonStockDividendsPerShare(?:Declared|CashPaid))"[^>]*>'
    raw=Path(physical['path']).read_bytes();tag=re.search(pattern,raw)
    if tag is None:return None
    key=cp['source']['original5field_key']
    header_raw=Path(header_source['path']).read_bytes();hz=header_raw.find(b'</SEC-HEADER>')+len(b'</SEC-HEADER>')
    require(0<hz<=8192,'RL_ORIGINAL_SEC_HEADER_BOUND_REQUIRED')
    header_ref=_write_binary(folder/'accepted_header.physical',header_raw[:hz])
    stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header_raw).group(1).decode()
    accepted=pd.to_datetime(stamp,format='%Y%m%d%H%M%S').tz_localize('America/New_York').tz_convert('UTC').isoformat()
    require(accepted[:10]<(key['effective_date'] if require_preex else UPPER),'RL_DECLARED_ACTUAL_HEADER_PREEX_OR_MATURE_REWARD_REQUIRED')
    unit_id=re.search(rb'unitRef="([^"]+)"',tag.group()).group(1)
    unit=re.search(rb'<xbrli:unit\b[^>]*id="'+re.escape(unit_id)+rb'"[^>]*>.*?</xbrli:unit>',raw,re.S)
    require(unit is not None and len(unit.group())<=4096,'RL_DECLARED_ORIGINAL_UNIT_FRAGMENT_REQUIRED')
    support=dict(issuer_CIK=cp['source']['issuer_CIK'],source_ref=physical,accepted_header_ref=header_ref,
        accepted_at_utc=accepted,accession=cp['source']['accession'],form=cp['source'].get('form','10-Q'),original_header_prefix_custody_ref=header_source,
        common_concept=tag.group(1).decode(),opening_tag_ref=_write_binary(folder/'common_dividend_opening_tag.physical',tag.group()),
        opening_tag_physical_range=list(tag.span()),original_USD_divided_shares_ref=_write_binary(folder/'USD_per_share_unit.physical',unit.group()),unit_physical_range=list(unit.span()))
    return support



def _prepare_sec_declared_facts(identity_ref,identity):
    import re,types
    from decimal import Decimal
    from scripts.storage.refresh_sec_event_originals import FilingText
    from scripts.research.a2.data import consensus_declared_cash_source_completion as D
    root=source_root();facts=[];sources=[];supports={};capsules={};events=[]
    profiles={'MU':(1293888,1295709,'2023-01-03','2023-01-19',None),
        'QSR':(2392186,2392850,'2022-12-21','2023-01-04','per common share')}
    for ticker,(a,z,record,pay,common) in profiles.items():
        folder=root/'declaration_sources'/ticker/'SEC_diagnostic';cpref=ref(folder/'checkpoint.json');cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'))
        require(cp['source']['original5field_key']['ticker']==ticker and cp['source']['accepted_at_utc'][:10]<cp['source']['original5field_key']['effective_date']<UPPER,'RL_EXACT_PREEX_SEC_DECLARED_CASE_REQUIRED')
        roles={x['role']:x for x in cp['attempts']};require(all(x['http_status'] in (200,206) for x in roles.values()),'RL_SEC_DECLARED_PRIMARY_NOT_CAPTURED')
        physical=roles['SEC_PRIMARY']['original_prefix_ref'];support=_declared_unit_support(cp,physical,roles['SEC_HEADER']['original_prefix_ref'],folder)
        require(support is not None,'RL_SEC_DECLARED_COMMON_UNIT_REQUIRED');supports[support['issuer_CIK']]=support
        sub=types.FunctionType(D._declared_unit_submission.__code__,{**D._declared_unit_submission.__globals__,'APPROVED_UNIT_SUPPORTS':supports})
        unit=types.FunctionType(D._declared_common_usd_unit.__code__,{**D._declared_common_usd_unit.__globals__,'_declared_unit_submission':sub})
        key=cp['source']['original5field_key'];unit(support,before=key['effective_date']+'T00:00:00+00:00')
        with Path(physical['path']).open('rb') as f:f.seek(a);raw=f.read(z-a)
        if ticker=='QSR':
            stop=raw.find(b'Partnership will');require(stop>0,'RL_QSR_COMMON_CLAUSE_PHYSICAL_BOUNDARY_CHANGED');z=a+stop;raw=raw[:stop]
        fragment_ref=_write_binary(folder/'exact_common_declared_cash.physical',raw)
        parser=FilingText();parser.feed(raw.decode('utf-8'));text=' '.join(' '.join(parser.parts).split())
        numbers=re.findall(r'\$\s*([0-9]*\s*\.\s*[0-9]+|[0-9]+)',text);require(len(numbers)==1 and 'declared' in text,'RL_SEC_SINGLE_COMMON_FIXED_DECLARED_AMOUNT_REQUIRED')
        def literal(day):
            import pandas as pd
            t=pd.Timestamp(day);return t.strftime('%B ')+str(t.day)+t.strftime(', %Y')
        require(literal(record) in text and literal(pay) in text,'RL_SEC_ORIGINAL_FIXED_RECORD_PAY_REQUIRED')
        amount=str(Decimal(re.sub(r'\s+','',numbers[0])));sid=next(x['accounting_sid'] for x in identity['entries'] if x['original5field_key']==key)
        fact=dict(schema=D.FACT_SCHEMA,source_kind='ISSUER_PRE2026_DECLARED_FIXED_USD_RAW_LISTED_CASH',primary_source_provider='ISSUER_FILED_SEC_ORIGINAL',
            amount_source_role='ORIGINAL_PRE2026_ISSUER_DECLARATION_NOT_VENDOR_PAYMENT_RESULT',original5field_key=key,ticker=ticker,accounting_sid=sid,
            ex_date=key['effective_date'],record_date=record,pay_date=pay,source_SEC_accepted_at=support['accepted_at_utc'],source_SEC_acceptance_verified=True,
            publication_clock_role='ORIGINAL_PREEX_SEC_ACCEPTANCE_UPPER_BOUND_NOT_FIRST_PUBLICATION',
            original_raw_identity_links_ref=identity_ref,original_current_source_ref=physical,current_cash_fragment_ref=fragment_ref,current_cash_physical_range=[a,z],
            current_original_cash_text=text,common_usd_unit_support=support,record_literal=literal(record),pay_literal=literal(pay),current_action_literal='declared',current_common_literal=common,
            declared_cash_amount_decimal=amount,currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',
            available_at=None,strict_PIT=False,actual_payment_status_read=False,vendor_payment_amount_read=False,original_issuer_source_url=cp['source']['SEC_url'],
            issuer_components=[dict(record=dict(id='ISSUER_SEC_DECLARATION:'+fragment_ref['sha256']),original_source_ref=physical)],
            non_target_listing_or_partnership_cash_included=False)
        capsuleref=_write(folder/'exact_declared_capsule.json',fact);capsules[_digest(key)]=capsuleref;fact['approved_current_capsule_ref']=capsuleref
        factref=_write(folder/'native_declared_fact.json',fact);validator=_declared_fact_validator(identity,supports,capsules);event=validator(private_cash_owner(),fact,factref)
        facts.append(factref);sources.extend((cpref,cp['scope_ref'],physical,roles['SEC_HEADER']['original_prefix_ref'],capsuleref));events.append(dict(event_id=cp['source']['event_id'],status='ORIGINAL_SEC_DECLARED_NATIVE_TYPED_FACT_BOUND',typed_fact_qualified=True,fact_ref=factref,event_fingerprint=event.event_fingerprint))
    return dict(event_projection_refs=facts,source_refs=sources,declared_supports=supports,declared_capsules=capsules,events=events)


def _prepare_fcx_realized_facts(identity_ref,identity):
    import re,types
    from scripts.storage.refresh_sec_event_originals import FilingText
    from scripts.research.a2.data import consensus_declared_cash_source_completion as D
    root=source_root();scope_ref=ref(root/'FCX_2022_postverified_exact_payment_scope.json');scope=json.loads(Path(scope_ref['path']).read_text(encoding='utf-8'))
    ranges={'2022-04-13':(919726,921691,'2022-04-14','2022-05-02'),
        '2022-07-14':(1298533,1300350,'2022-07-15','2022-08-01')}
    supports={};capsules={};facts=[];events=[];sources=[scope_ref,scope['source_index_ref']]
    for item in scope['documents']:
        key=item['original5field_key'];a,z,record,pay=ranges[key['effective_date']]
        folder=root/'declaration_sources'/'FCX_postverified'/item['accession'];cpref=ref(folder/'checkpoint.json');cp=json.loads(Path(cpref['path']).read_text(encoding='utf-8'));roles={x['role']:x for x in cp['attempts']}
        require(all(x['http_status'] in (200,206) for x in roles.values()),'RL_FCX_ORIGINAL_HTTP_CAPTURE_REQUIRED')
        require(cp['source']['accession']==item['accession'],'RL_FCX_EXACT_ORIGINAL_PRIMARY_VERSION_REQUIRED')
        physical=roles['SEC_PRIMARY']['original_prefix_ref'];support=_declared_unit_support(dict(cp,source=item),physical,roles['SEC_HEADER']['original_prefix_ref'],folder,require_preex=False)
        require(support is not None,'RL_FCX_ORIGINAL_COMMON_USD_PER_SHARE_REQUIRED');supports[support['accession']]=support
        sub=types.FunctionType(D._declared_unit_submission.__code__,{**D._declared_unit_submission.__globals__,'APPROVED_UNIT_SUPPORTS':{831259:support}})
        unit=types.FunctionType(D._declared_common_usd_unit.__code__,{**D._declared_common_usd_unit.__globals__,'_declared_unit_submission':sub});unit(support,before=UPPER+'T00:00:00+00:00')
        require(pay<=support['accepted_at_utc'][:10]<UPPER,'RL_FCX_REALIZED_CASH_AND_SOURCE_MUST_MATURE_IN_2022')
        with Path(physical['path']).open('rb') as f:f.seek(a);raw=f.read(z-a)
        fragment_ref=_write_binary(folder/'exact_2022_common_paid_cash.physical',raw);parser=FilingText();parser.feed(raw.decode('utf-8'));text=' '.join(' '.join(parser.parts).split())
        pattern=r'quarterly cash dividends totaling \$\s*([0-9.]+) per share \(\$\s*([0-9.]+) per share base dividend and \$\s*([0-9.]+) per share variable dividend\) on its common stock, which were paid on'
        match=re.search(pattern,text);require(match is not None,'RL_FCX_ORIGINAL_TOTAL_BASE_VARIABLE_CLAUSE_REQUIRED')
        def literal(day):
            import pandas as pd
            t=pd.Timestamp(day);return t.strftime('%B ')+str(t.day)+t.strftime(', %Y')
        require(literal(pay) in text and literal(record) in text,'RL_FCX_EXACT_ORIGINAL_RECORD_PAY_REQUIRED')
        components=[dict(record=dict(id='ISSUER_SEC_FCX_'+role+':'+fragment_ref['sha256']),role=role,original_cash_amount_decimal=amount,original_source_ref=physical)
            for role,amount in zip(('BASE','VARIABLE'),match.groups()[1:])]
        sid=next(x['accounting_sid'] for x in identity['entries'] if x['original5field_key']==key)
        fact=dict(schema='CONSENSUS_RL_2022_REALIZED_ISSUER_USD_RAW_CASH_FACT_R1',source_kind='ISSUER_PRE2023_REALIZED_FIXED_USD_RAW_LISTED_CASH',primary_source_provider='ISSUER_FILED_SEC_ORIGINAL',
            amount_source_role='ORIGINAL_2022_ISSUER_REPORTED_REALIZED_CASH_NOT_ASOF_INPUT',original5field_key=key,ticker='FCX',accounting_sid=sid,ex_date=key['effective_date'],record_date=record,pay_date=pay,
            source_SEC_accepted_at=support['accepted_at_utc'],source_SEC_acceptance_verified=True,reward_mature_at=support['accepted_at_utc'],frozen_mature_reward_scope_ref=scope_ref,
            asof_policy_input_allowed=False,ordinary_cash_classification_inferred=False,publication_clock_role='ACTUAL_2022_POSTPAY_SEC_PUBLICATION_REWARD_MATURITY_NOT_EX_ANTE_INFORMATION',
            original_raw_identity_links_ref=identity_ref,original_current_source_ref=physical,current_cash_fragment_ref=fragment_ref,current_cash_physical_range=[a,z],current_original_cash_text=text,
            common_usd_unit_support=support,record_literal=literal(record),pay_literal=literal(pay),current_action_literal='paid',current_common_literal='common stock',declared_cash_amount_decimal=match.group(1),
            currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',available_at=None,strict_PIT=False,actual_payment_status_read=True,vendor_payment_amount_read=False,
            original_issuer_source_url=item['SEC_url'],issuer_components=components,total_credit_once=True)
        capsuleref=_write(folder/'exact_2022_realized_capsule.json',fact);capsules[_digest(key)]=capsuleref;fact['approved_current_capsule_ref']=capsuleref
        factref=_write(folder/'native_2022_realized_fact.json',fact);validator=_declared_fact_validator(identity,supports,capsules);event=validator(private_cash_owner(),fact,factref)
        facts.append(factref);sources.extend((cpref,physical,roles['SEC_HEADER']['original_prefix_ref'],capsuleref));events.append(dict(event_id=item['event_id'],status='ORIGINAL_2022_REALIZED_NATIVE_TYPED_FACT_BOUND',typed_fact_qualified=True,fact_ref=factref,event_fingerprint=event.event_fingerprint))
    return dict(event_projection_refs=facts,source_refs=sources,declared_supports=supports,declared_capsules=capsules,events=events)
