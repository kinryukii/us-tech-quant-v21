"""Task-only binding of existing raw-share source owners; no event reconstruction.

Metadata preflight never decodes prices or quote numeric evidence. Actual loading
requires the caller's frozen pre2026 account-read gate. A stream projection visits
only JSON keys/status values before selecting exact date/ticker evidence records.
"""
from __future__ import annotations
import ast
import copy
import inspect
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace, FunctionType
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.research.a2.data import full_selector_account_inputs as existing
from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.evaluation import consensus_shareholder_account as account
from scripts.research.a2.training import stateful_research_quote_domain as signal_quote

TASK=account.TASK
SCOPE_SCHEMA='CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1'
GATE='AUTHORIZED_PRE2026_ACCOUNT_REPLAY'
OWNER_SHA='ab9c7927d68e3484229fb29ad33438efe79958c4eeeac2dbfbec4adafa021a41'
SOURCE_ADAPTER_SHA='d45671945fdaf1adbe24944c06f4dab31e3850b3f703468c1cb203d76f7936cb'
SOURCE_DEPENDENCIES={'joint_cash_bindings':'8f57a1b233d3b4bc19421724964b9cb4902591ac580412b359fa03347d163f9e','corporate_action':'97a0ecd16297bf0ede9394e78d74e8135ad95fdbded904fbb7bc05bec33f9053'}
SIGNAL_QUOTE_OWNER_SHA='70ab76370a5ccd379b4761947a1a939117bd9872edb4f55173b1d53680d94acb'
SIGNAL_QUOTE_LOADER_AST_SHA='37b8a3cfba704a81a943781e85f7a93355a99e532e1581af397c538e623b764f'
LEGACY_SIGNAL_REPLAY_REF=dict(path='D:/us-tech-quant/scripts/research/a2/training/stateful_replay.py',sha256='65fd5dd5ce00ee52ce295636b0e0c95b0abdfc08354fce034f244fef082c9c07')
LEGACY_SOURCE_FACT_OWNER_REF=dict(path='D:/us-tech-quant/scripts/research/a2/data/reused_pair_ca_sources.py',sha256='1775b34066887c59b1da10e83121c6d860575d050edded5f59040a457684ba98')
LEGACY_JOINT_CASH_REF=dict(path='D:/us-tech-quant/scripts/research/a2/data/joint_cash_bindings.py',sha256='8a654259e21bc52769764242b2ba27ec477648180df8df57e56544d081a235e6')
CONSTRUCTION_SOURCE_REF_WHITELIST=(LEGACY_SOURCE_FACT_OWNER_REF,LEGACY_JOINT_CASH_REF)


def require(ok,code):
    if not ok:raise ValueError(code)


def file_ref(path):
    return dict(path=str(path),sha256=sha256(path))


class _JsonProjection:
    """Bounded lexical skipping; skipped numeric values are never JSON-decoded."""
    def __init__(self,handle):self.handle=handle;self.buf=b'';self.i=0;self.base=0
    def peek(self):
        if self.i==len(self.buf):
            self.base+=len(self.buf);self.buf=self.handle.read(65536);self.i=0
        return self.buf[self.i:self.i+1]
    def take(self):
        ch=self.peek();self.i+=bool(ch);return ch
    def tell(self):return self.base+self.i
    def white(self):
        while self.peek() and self.peek() in b' \t\r\n':self.take()
    def expect(self,ch):
        self.white();require(self.take()==ch,'SOURCE_JSON_STRUCTURE_CHANGED')
    def string(self,decode=False):
        self.expect(b'"');parts=[b'"'] if decode else None;escape=False
        while True:
            ch=self.take();require(bool(ch),'SOURCE_JSON_TRUNCATED_STRING')
            if decode:parts.append(ch)
            if not escape and ch==b'"':break
            if not escape and ch==b'\\':escape=True
            else:escape=False
        if decode:return json.loads(b''.join(parts))
    def skip(self):
        self.white();ch=self.peek()
        if ch==b'"':self.string();return
        if ch in (b'{',b'['):
            end=b'}' if self.take()==b'{' else b']';self.white()
            if self.peek()==end:self.take();return
            while True:
                if end==b'}':self.string();self.expect(b':')
                self.skip();self.white();sep=self.take()
                if sep==end:return
                require(sep==b',','SOURCE_JSON_STRUCTURE_CHANGED')
        else:
            count=0
            while self.peek() and self.peek() not in b',]} \t\r\n':self.take();count+=1
            require(count>0,'SOURCE_JSON_EMPTY_VALUE')
    def scalar(self,limit=16384):
        self.white();start=self.tell();self.skip();end=self.tell()
        require(end-start<=limit,'SOURCE_JSON_METADATA_VALUE_TOO_LARGE')
        here=self.handle.tell();self.handle.seek(start);raw=self.handle.read(end-start);self.handle.seek(here)
        return json.loads(raw)
    def descend(self,path):
        self.expect(b'{');self.white()
        while self.peek()!=b'}':
            key=self.string(True);self.expect(b':')
            if key==path[0]:
                if len(path)==1:return
                self.descend(path[1:]);return
            self.skip();self.white();sep=self.take()
            require(sep==b',','SOURCE_JSON_SELECTED_PATH_MISSING')
        raise ValueError('SOURCE_JSON_SELECTED_PATH_MISSING')
    def metadata_fields(self,names):
        self.expect(b'{');result={};self.white()
        while self.peek()!=b'}':
            key=self.string(True);self.expect(b':')
            if key in names:
                require(key not in result,'SOURCE_JSON_DUPLICATE_METADATA_KEY');result[key]=self.scalar(limit=65536)
            else:self.skip()
            self.white();sep=self.take()
            if sep==b'}':return result
            require(sep==b',','SOURCE_JSON_STRUCTURE_CHANGED')
        self.take();return result
    def decisions(self,allowed_keys,branch):
        self.descend(('branches','A','decisions') if branch=='A' else ('decisions',));self.expect(b'[');self.white()
        if self.peek()==b']':self.take();return
        while True:
            self.white();start=self.tell();self.expect(b'{');meta={};self.white()
            while self.peek()!=b'}':
                name=self.string(True);self.expect(b':')
                if name in ('key','classification','source_availability','qualification'):
                    require(name not in meta,'SOURCE_JSON_DUPLICATE_METADATA_KEY');meta[name]=self.scalar()
                else:self.skip()
                self.white();sep=self.take()
                if sep==b'}':break
                require(sep==b',','SOURCE_JSON_DECISION_STRUCTURE_CHANGED')
            else:self.take()
            end=self.tell();key=meta.get('key')
            require(isinstance(key,dict) and set(key)=={'date','ticker'},'SOURCE_QUOTE_EXACT_KEY_REQUIRED')
            day=pd.Timestamp(key['date'])
            require(pd.Timestamp('2023-01-01')<=day<pd.Timestamp('2026-01-01') and day==day.normalize() and day.tzinfo is None,'SOURCE_QUOTE_PRE2026_SCOPE_CHANGED')
            pair=(str(day.date()),key['ticker'])
            if pair in allowed_keys:yield start,end,meta
            self.white();sep=self.take()
            if sep==b']':return
            require(sep==b',','SOURCE_JSON_DECISION_ARRAY_CHANGED')


def project_quote_decisions(path,allowed_keys,*,decode_numeric_evidence=False,source_scope_proof):
    """Two-pass exact-key A branch projection; outcome branches are lexical skips.

    The supplied proof is part of the task's hashed source-scope metadata. The
    first pass JSON-decodes only key/classification/availability/qualification.
    Even within an allowed record, numeric evidence is decoded only at gate.
    """
    physical_ref=file_ref(path)
    branch=source_scope_proof.get('branch')
    require(branch in ('A','STATEFUL') and source_scope_proof==dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch=branch,classification_ref=physical_ref),
        'EXACT_PRE2026_CLASSIFICATION_SOURCE_SCOPE_PROOF_REQUIRED')
    allowed={(str(pd.Timestamp(d).date()),str(t)) for d,t in allowed_keys}
    require(all('2023-01-01'<=d<'2026-01-01' for d,_ in allowed),'QUOTE_PROJECTION_KEY_OUTSIDE_SCOPE')
    selected=[];seen=set();numeric_records=0
    with Path(path).open('rb') as handle:
        parser=_JsonProjection(handle)
        for start,end,metadata in parser.decisions(allowed,branch):
            pair=(metadata['key']['date'],metadata['key']['ticker'])
            require(pair not in seen,'QUOTE_PROJECTION_DUPLICATE_KEY');seen.add(pair)
            selected.append((start,end,metadata))
    if decode_numeric_evidence:
        result=[]
        with Path(path).open('rb') as handle:
            for start,end,metadata in selected:
                require(end-start<=1024*1024,'QUOTE_SELECTED_RECORD_TOO_LARGE')
                handle.seek(start);value=json.loads(handle.read(end-start));require(value['key']==metadata['key'],'QUOTE_SELECTED_KEY_CHANGED')
                result.append(value);numeric_records+=1
    else:result=[m for _,_,m in selected]
    return result,dict(schema='CONSENSUS100_EXACT_QUOTE_A_STREAM_PROJECTION_R1',branch=branch,selected_records=len(selected),
        numeric_evidence_records_decoded=numeric_records,unselected_values_json_decoded=False,outcome_branches_json_decoded=False,
        classification_ref=physical_ref,source_scope_proof=source_scope_proof)


def signal_quote_metadata_preflight(freeze_ref,*,legacy_source_transport=()):
    """Validate actual new-task source closure; never reuse old account authority.

    Preserve the old rule/source-clock checks through an exact AST projection,
    but separately audit its unexecuted historical replay pin when same bytes
    cannot be recovered. That is not validation of the old freeze. Decode only
    task-qualified exact population keys later and reproduce the pure rule.
    """
    require(sha256(signal_quote.__file__)==SIGNAL_QUOTE_OWNER_SHA,'SIGNAL_QUOTE_SOURCE_OWNER_CHANGED')
    tree=ast.parse(inspect.getsource(signal_quote.load_frozen_domain));node=tree.body[0]
    require(hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()==SIGNAL_QUOTE_LOADER_AST_SHA,'SIGNAL_QUOTE_METADATA_LOADER_AST_CHANGED')
    anchor=ast.parse("population = json.loads(_reference_path(frozen['population_ref']).read_text(encoding='utf-8'))").body[0]
    hits=[i for i,v in enumerate(node.body) if ast.dump(v,include_attributes=False)==ast.dump(anchor,include_attributes=False)]
    require(len(hits)==1,'SIGNAL_QUOTE_POPULATION_READ_ANCHOR_CHANGED')
    pin_loop=ast.parse("for path, pin in frozen.get('source_pins', {}).items():\n    _reference_path(dict(path=path, sha256=pin))").body[0]
    loops=[i for i,v in enumerate(node.body[:hits[0]]) if ast.dump(v,include_attributes=False)==ast.dump(pin_loop,include_attributes=False)]
    require(len(loops)==1,'SIGNAL_QUOTE_SOURCE_PIN_LOOP_ANCHOR_CHANGED')
    transports=list(legacy_source_transport);require(len(transports)<=1,'SIGNAL_QUOTE_EXACT_LEGACY_TRANSPORT_ONLY')
    for item in transports:
        original=item.get('original_ref',{});custody=item.get('custody_ref',{})
        require(Path(original.get('path','')).resolve()==Path(LEGACY_SIGNAL_REPLAY_REF['path']).resolve() and original.get('sha256')==LEGACY_SIGNAL_REPLAY_REF['sha256'] and custody.get('sha256')==original['sha256'] and item.get('original_bytes_unchanged') is True and TASK in Path(custody.get('path','')).parts,'SIGNAL_QUOTE_SAME_BYTE_TASK_CUSTODY_REQUIRED')
    physical={}
    def pin(ref):
        transport=next((v for v in transports if Path(v['original_ref']['path']).resolve()==Path(ref['path']).resolve() and v['original_ref']['sha256']==ref['sha256']),None)
        path=signal_quote._reference_path(transport['custody_ref'] if transport else ref)
        stat=path.stat();physical[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        return path
    unexecuted=[]
    def task_source_pin(path,expected):
        ref=dict(path=path,sha256=expected)
        is_legacy=(Path(path).resolve()==Path(LEGACY_SIGNAL_REPLAY_REF['path']).resolve() and expected==LEGACY_SIGNAL_REPLAY_REF['sha256'])
        has_transport=any(Path(v['original_ref']['path']).resolve()==Path(path).resolve() and v['original_ref']['sha256']==expected for v in transports)
        if is_legacy and not has_transport:
            unexecuted.append(dict(ref=ref,status='UNEXECUTED_OLD_SOURCE_PIN_NOT_REVALIDATED',same_byte_custody_unavailable=True))
        else:pin(ref)
    node.body=node.body[:hits[0]]+[ast.parse('return frozen').body[0]]
    node.body[loops[0]]=ast.parse("for path, pin in frozen.get('source_pins', {}).items():\n    _newtask_source_pin(path, pin)").body[0]
    node.name='_consensus_signal_quote_metadata';namespace={**signal_quote.load_frozen_domain.__globals__,'_reference_path':pin,'_newtask_source_pin':task_source_pin}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),__file__,'exec'),namespace)
    frozen=namespace[node.name](freeze_ref);population_path=pin(frozen['population_ref'])
    with population_path.open('rb') as handle:
        header=_JsonProjection(handle).metadata_fields({'schema','task_id','source_refs','masked_key_count'})
    require(header.get('schema')=='QUOTE_MASK_POPULATION_CENSUS_R1' and header.get('task_id')==signal_quote.TASK_ID and header.get('source_refs')==frozen['source_refs'] and isinstance(header.get('masked_key_count'),int) and header['masked_key_count']>0,'SIGNAL_QUOTE_POPULATION_METADATA_IDENTITY_CHANGED')
    return dict(frozen=frozen,physical_stats=physical,header=header,lineage=dict(owner_ref=file_ref(signal_quote.__file__),loader_ast_sha256=SIGNAL_QUOTE_LOADER_AST_SHA,population_read_anchor_count=1,source_pin_loop_anchor_count=1,original_source_checks_unchanged=not bool(unexecuted),source_ref_and_clock_checks_unchanged=True,
        unexecuted_old_source_pins=unexecuted,old_freeze_full_validation_passed=False,current_task_source_fact_closure_qualified=True,population_full_numeric_decode=False,legacy_execution_authority_reused=False))


def apply_signal_quote_binding(raw_market,original_market,remaining_market,shared_usable,decisions):
    """Intersect both source owners and retain independent/remaining CA masks."""
    require(sha256(signal_quote.__file__)==SIGNAL_QUOTE_OWNER_SHA,'SIGNAL_QUOTE_SOURCE_OWNER_CHANGED')
    base=raw_market.quality;inherited=original_market.quality&~base
    di={str(pd.Timestamp(d).date()):i for i,d in enumerate(raw_market.dates)};ti={t:i for i,t in enumerate(raw_market.tickers)}
    for decision in decisions:
        require(decision==signal_quote.classify_quote_key(decision['evidence']),'SIGNAL_QUOTE_DECISION_NOT_REPRODUCED')
        if decision['classification']=='A':
            i=di[decision['key']['date']];j=ti[decision['key']['ticker']];row=decision['evidence']['raw_rows'][0]
            require(float(row['open'])==raw_market.open[i,j] and float(row['close'])==raw_market.close[i,j],'SIGNAL_QUOTE_RAW_COORDINATE_MISMATCH')
    quality,audit=signal_quote.apply_quote_domain(base,inherited,raw_market.dates,raw_market.tickers,decisions)
    remaining=remaining_market.quality&~base
    quality|=inherited&~np.asarray(shared_usable,bool);quality|=remaining
    require(not np.any(base&~quality) and not np.any(remaining&~quality),'TASK_QUOTE_BLOCKER_REMOVED')
    audit=dict(audit,task_id=TASK,source_fact_task_id=signal_quote.TASK_ID,remaining_unsupported_CA_preserved=True,
        shared_quote_owner_intersection=True,actual_signal_quality_cleared_count=int((original_market.quality&~quality).sum()),
        legacy_execution_authority_reused=False,historical_quote_vintage_status='UNKNOWN',strict_PIT=False)
    return replace(raw_market,quality=quality),np.asarray(shared_usable,bool)&~quality,audit


def source_fact_custody_reader(legacy_ca_transport,construction_transport=None):
    """Translate only the two discovered, recovered historical code-byte refs.

    The existing reader still verifies CA transport and all unrelated refs.
    Historical1775/8a construction pins stay unchanged; current executable
    source facts/dependencies stay independently bound at d456/8f57/97.
    The earlier single1775 dictionary keeps its original strict semantics.
    """
    base_pin,base_read=existing.custody_reader(legacy_ca_transport)
    if construction_transport is None:return base_pin,base_read,None
    single=isinstance(construction_transport,dict)
    require(single or isinstance(construction_transport,(list,tuple)),'EXACT_SOURCE_FACT_CONSTRUCTION_TRANSPORT_REQUIRED')
    entries=[construction_transport] if single else list(construction_transport)
    required=(LEGACY_SOURCE_FACT_OWNER_REF,) if single else CONSTRUCTION_SOURCE_REF_WHITELIST
    require(len(entries)==len(required),'EXACT_DISCOVERED_CONSTRUCTION_TRANSPORT_SET_REQUIRED')
    roots=existing.resolve(existing.REPO);seen=[]
    for tx in entries:
        require(isinstance(tx,dict) and set(tx)=={'original_ref','custody_ref','original_bytes_unchanged','old_ref_not_relabelled_as_current_producer'},'EXACT_SOURCE_FACT_CONSTRUCTION_TRANSPORT_REQUIRED')
        original,custody=tx['original_ref'],tx['custody_ref']
        require(isinstance(original,dict) and set(original)=={'path','sha256'} and any(existing._same_ref(original,r) for r in required)
            and not any(existing._same_ref(original,r) for r in seen)
            and isinstance(custody,dict) and set(custody)=={'path','sha256'} and custody['sha256']==original['sha256']
            and tx['original_bytes_unchanged'] is True and tx['old_ref_not_relabelled_as_current_producer'] is True,'SAME_BYTE_1775_OR_8A_CONSTRUCTION_CUSTODY_REQUIRED')
        location=Path(custody['path']).resolve()
        require(TASK in location.parts and any(location.is_relative_to(p.resolve()) for p in (roots.backtest_root,roots.cache_root)),'CONSTRUCTION_CUSTODY_MUST_BELONG_TO_TASK')
        base_pin(custody);seen.append(original)
    def translate(ref):
        if isinstance(ref,dict) and {'path','sha256'}.issubset(ref):
            for tx in entries:
                if existing._same_ref(ref,tx['original_ref']):return tx['custody_ref']
        return ref
    def pin(ref):return base_pin(translate(ref))
    def read(ref):return base_read(translate(ref))
    proof=dict(schema='CONSENSUS100_EXACT_HISTORICAL_SOURCE_FACT_TRANSPORT_R1',task_id=TASK,
        transports=entries,original_bytes_unchanged=True,old_ref_not_relabelled_as_current_producer=True,
        old_bundle_references_unchanged=True,source_pin_check_skipped=False,legacy_execution_authority_reused=False)
    if single:proof.update(original_ref=entries[0]['original_ref'],custody_ref=entries[0]['custody_ref'])
    return pin,read,proof


def source_scope_template(*,sources,pool_ref,calendar_ref,settlement_calendar_ref,legacy_source_transport,quote_classification_scope_proof,signal_adv_source_ref,source_fact_owner_ref,source_dependency_refs,signal_quote_domain_ref=None,signal_quote_population_scope_proof=None,signal_quote_legacy_source_transport=(),source_fact_construction_transport=None):
    return dict(schema=SCOPE_SCHEMA,task_id=TASK,scope_start='2023-01-01',scope_end_exclusive='2026-01-01',
        raw_price_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',strict_PIT=False,
        sources=copy.deepcopy(sources),pool_ref=pool_ref,calendar_ref=calendar_ref,settlement_calendar_ref=settlement_calendar_ref,legacy_source_transport=legacy_source_transport,
        quote_classification_scope_proof=quote_classification_scope_proof,signal_adv_source_ref=signal_adv_source_ref,
        source_fact_owner_ref=source_fact_owner_ref,source_dependency_refs=source_dependency_refs,source_fact_construction_transport=source_fact_construction_transport,
        signal_quote_domain_ref=signal_quote_domain_ref,signal_quote_population_scope_proof=signal_quote_population_scope_proof,signal_quote_legacy_source_transport=list(signal_quote_legacy_source_transport),numeric_read_authorization='PROPOSED_NOT_AUTHORIZED')


def screen_raw_identity_keys(raw_keys):
    """Reject absent/ambiguous dated UIDs before invoking the existing owner.

    A missing SID has no UID. A same-session SID shared across tickers has no
    preferred alias. Retain both as coverage gaps and admit neither price key.
    The source owner's original CUSIP/mapping/UID checks still run unchanged.
    """
    f=raw_keys.copy();f.signal_date=pd.to_datetime(f.signal_date)
    require(not f.duplicated(['signal_date','ticker']).any(),'RAW_DATE_TICKER_METADATA_AMBIGUOUS')
    cusip=f.security_id.astype('string').str.strip().str.upper()
    missing=cusip.isna()|cusip.eq('');gaps=[]
    for row in f.loc[missing].itertuples():
        gaps.append(dict(signal_date=str(row.signal_date.date()),security_uid=None,ticker=row.ticker,reason='MISSING_DATED_SECURITY_IDENTITY'))
    f=f.loc[~missing].copy();f['cusip']=cusip.loc[~missing];f['security_uid']='CUSIP:'+f.cusip
    ambiguous=f.duplicated(['signal_date','security_uid'],keep=False)
    for row in f.loc[ambiguous].itertuples():
        gaps.append(dict(signal_date=str(row.signal_date.date()),security_uid=row.security_uid,ticker=row.ticker,reason='AMBIGUOUS_DATED_SECURITY_UID'))
    proof=dict(input_metadata_keys=len(raw_keys),missing_identity_keys=int(missing.sum()),ambiguous_identity_keys=int(ambiguous.sum()),
        ambiguous_date_uid_pairs=len(f.loc[ambiguous,['signal_date','security_uid']].drop_duplicates()),qualified_uid_candidate_keys=int((~ambiguous).sum()),
        missing_uid_not_invented=True,ambiguous_alias_not_selected=True,numeric_price_projection_before_identity_screen=False)
    return f.loc[~ambiguous].copy(),gaps,proof


def continuation_dependency_custody(scope,pin,read):
    """Preserve historical fact producers; bind current CA execution separately."""
    from scripts.research.a2.training import consensus_fusion as fusion
    transports=scope.get('continuation_source_dependency_custody')
    if transports is None:
        require(scope.get('research_id')!=fusion.CONTINUATION_RESEARCH_ID,'CONTINUATION_HISTORICAL_FACT_CUSTODY_REQUIRED')
        return pin,read,None,None
    require(scope.get('research_id')==fusion.CONTINUATION_RESEARCH_ID,'EXACT_SOURCE_COMPLETION_IDENTITY_REQUIRED')
    expected_scope=dict(path=str(fusion.CONTINUATION_RUN/'CONTINUATION_SCOPE.json'),sha256=fusion.CONTINUATION_SCOPE_SHA256)
    require(scope.get('continuation_scope_ref')==expected_scope,'SOURCE_COMPLETION_SCOPE_CHANGED');pin(expected_scope)
    convention=scope.get('account_convention_scope_ref')
    require(convention==dict(path=str(fusion.CONTINUATION_RUN/'ACCOUNT_CONVENTION_SCOPE.json'),
        sha256='71ccae1d26b09cd972747a1876f7750b940e5b133abac5010c0a7bf28045eba8'),'SOURCE_COMPLETION_ACCOUNT_CONVENTION_REQUIRED');pin(convention)
    deps=scope['source_dependency_refs'];roots=existing.resolve(existing.REPO)
    expected={'joint_cash_bindings':existing.REPO/'scripts/research/a2/data/joint_cash_bindings.py',
        'corporate_action':existing.REPO/'scripts/v22/corporate_action_transition_r1.py'}
    require(isinstance(transports,list) and len(transports)==2,'EXACT_HISTORICAL_FACT_DEPENDENCY_TRANSPORT_REQUIRED')
    seen={}
    for tx in transports:
        require(set(tx)=={'role','original_ref','custody_ref','original_bytes_unchanged','not_current_execution_source'}
            and tx['role'] in expected and tx['role'] not in seen and tx['original_bytes_unchanged'] is True
            and tx['not_current_execution_source'] is True,'EXACT_HISTORICAL_FACT_DEPENDENCY_TRANSPORT_REQUIRED')
        role=tx['role'];origin,custody=tx['original_ref'],tx['custody_ref']
        require(set(origin)==set(custody)=={'path','sha256'} and existing._same_ref(origin,deps[role])
            and Path(origin['path']).resolve()==expected[role].resolve() and origin['sha256']==custody['sha256']==SOURCE_DEPENDENCIES[role],
            'HISTORICAL_FACT_DEPENDENCY_BYTES_NOT_SAME')
        location=Path(custody['path']).resolve()
        require((TASK in location.parts or fusion.CONTINUATION_RESEARCH_ID in location.parts)
            and any(location.is_relative_to(root.resolve()) for root in (roots.results_root,roots.backtest_root)),
            'HISTORICAL_FACT_CUSTODY_TASK_ROOT_REQUIRED')
        pin(custody);seen[role]=tx
    current=scope['current_corporate_owner_ref']
    require(Path(current['path']).resolve()==Path(existing.ca.__file__).resolve()
        and current['sha256']==sha256(existing.ca.__file__),'CURRENT_CORPORATE_EXECUTION_SOURCE_CHANGED');pin(current)
    def translate(ref):
        for tx in seen.values():
            if existing._same_ref(ref,tx['original_ref']):return tx['custody_ref']
        return ref
    def historical_pin(ref):return pin(translate(ref))
    def historical_read(ref):return read(translate(ref))
    proof=dict(schema='CONSENSUS_SOURCE_COMPLETION_HISTORICAL_FACT_DEPENDENCY_CUSTODY_R1',
        research_id=fusion.CONTINUATION_RESEARCH_ID,transports=transports,current_corporate_execution_ref=current,
        historical_facts_not_relabelled_as_current=True,legacy_execution_authority_reused=False)
    return historical_pin,historical_read,seen['joint_cash_bindings']['custody_ref'],proof


def completion_metadata(scope,pin,read,calendar):
    """Exact child source manifest and quote identity keys before price decoding."""
    from scripts.research.a2.training import consensus_fusion as fusion
    ref=scope.get('source_completion_manifest_ref')
    if ref is None:return None
    require(scope.get('research_id')==fusion.CONTINUATION_RESEARCH_ID,'EXACT_SOURCE_COMPLETION_IDENTITY_REQUIRED')
    manifest=read(ref)
    require(manifest.get('schema')=='CONSENSUS_SOURCE_COMPLETION_ACCOUNT_INPUT_MANIFEST_R1'
        and manifest.get('research_id')==fusion.CONTINUATION_RESEARCH_ID and manifest.get('task_id')==TASK
        and manifest.get('status')=='QUALIFIED_SOURCE_FACTS_FOR_PRE2026_ACCOUNTING_ONLY'
        and manifest.get('scope_start')=='2023-01-01' and manifest.get('scope_end_exclusive')=='2026-01-01'
        and manifest.get('strict_PIT') is False and manifest.get('target_support_expansion') is False,
        'QUALIFIED_PRE2026_SOURCE_COMPLETION_MANIFEST_REQUIRED')
    for role in ('ordinary_bundle_ref','ordinary_owner_ref','ordinary_cash_owner_ref','special_events_ref',
            'price_links_ref','fx_source_book_ref','fx_parser_ref','fx_source_validation_ref'):
        pin(manifest[role])
    for source in manifest['source_refs']:pin(source)
    for role,relative in (('ordinary_owner_ref','scripts/research/a2/data/reused_pair_ca_sources.py'),
            ('ordinary_cash_owner_ref','scripts/research/a2/data/joint_cash_bindings.py'),
            ('fx_parser_ref','scripts/research/a2/data/consensus_h10_fx_sources.py')):
        require(Path(manifest[role]['path']).resolve()==(existing.REPO/relative).resolve(),'COMPLETION_EXACT_CURRENT_SOURCE_OWNER_PATH_REQUIRED')
    fx_proof=read(manifest['fx_source_validation_ref'])
    require(fx_proof.get('schema')=='CONSENSUS_PRE2026_H10_CAD_SOURCE_CUSTODY_AMBIGUITY_SUPPLEMENT_R2'
        and fx_proof.get('status')=='PASS_SOURCE_FACTS_ONLY_PENDING_ROOT_ACCOUNT_ADMISSION'
        and fx_proof.get('book_ref')==manifest['fx_source_book_ref']
        and fx_proof.get('current_parser_ref')==manifest['fx_parser_ref']
        and fx_proof.get('exact_observation_match') is True and fx_proof.get('duplicate_publication_observation_keys')==0
        and fx_proof.get('selected_mark_order_invariant') is True
        and fx_proof.get('current_source_guard_applied_to_actual_pre2026_CAD_only') is True
        and fx_proof.get('test_2026_payload_read') is False,'CURRENT_FX_SOURCE_AMBIGUITY_VALIDATION_REQUIRED')
    historical=fx_proof['historical_parser_custody'];pin(historical['archived_ref'])
    require(historical['original_ref']['sha256']==historical['archived_ref']['sha256'],'FX_HISTORICAL_PRODUCER_CUSTODY_NOT_SAME_BYTES')
    links=read(manifest['price_links_ref'])
    require(links.get('schema')=='CONSENSUS_QUALIFIED_ADDITIONAL_RAW_PRICE_LINKS_R1'
        and links.get('status')=='QUALIFIED_ACCOUNTING_RAW_KEYS_NO_POOL_OR_ALPHA_EXPANSION',
        'QUALIFIED_EXTRA_RAW_PRICE_IDENTITY_LINKS_REQUIRED')
    rows=[];prices=[]
    for entry in links['entries']:
        require(entry.get('role') in ('HELD_RAW_SID_CONTINUATION','STOCK_DISTRIBUTION_CHILD_RAW')
            and entry.get('new_buy_eligibility_upgrade') is False and entry.get('alpha_or_label_expansion') is False
            and entry.get('price_coordinate')=='RAW_ACTUAL_SHARE'
            and entry.get('source_identity_status')=='QUALIFIED_DATED_LEGAL_CLASS_AND_EXISTING_RAW_TRANSPORT',
            'ADDITIONAL_RAW_SOURCE_IDENTITY_AND_USE_SCOPE_REQUIRED')
        if entry['role']=='HELD_RAW_SID_CONTINUATION':
            require(entry['ticker']=='TRP' and entry.get('new_CUSIP_assignment') is False,'TRP_HELD_RAW_ONLY_REQUIRED')
        else:require(entry['ticker'] in ('VLTO','RAL','SNRE'),'EXACT_THREE_STOCK_CHILD_QUOTES_REQUIRED')
        sid=entry['raw_security_id'];require(isinstance(sid,str) and sid and not any(x in sid.upper() for x in ('UNKNOWN','PLACEHOLDER','UNCONFIRMED')),'QUALIFIED_RAW_SID_REQUIRED')
        available=pd.Timestamp(entry['identity_available_at']);require(available.tzinfo is not None and available<pd.Timestamp('2026-01-01',tz='UTC'),'ADDITIONAL_IDENTITY_PRE2026_CLOCK_REQUIRED')
        for source in entry['identity_source_refs']:pin(source)
        price_ref=entry['price_ref'];pin(price_ref);guard_parquet(price_ref['path'],price_ref['sha256'],['trade_date'])
        dates=pd.DatetimeIndex(entry['trade_dates'])
        require(not dates.empty and not dates.has_duplicates and dates.tz is None and dates.equals(dates.normalize())
            and dates.isin(calendar).all() and dates.min()>=pd.Timestamp('2023-01-01') and dates.max()<pd.Timestamp('2026-01-01'),
            'EXACT_EXTRA_RAW_PRICE_PRE2026_DATE_KEYS_REQUIRED')
        first_open=(dates.min()+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
        require(available<=first_open,'RAW_IDENTITY_UNAVAILABLE_AT_FIRST_EXTRA_QUOTE')
        keys=pd.DataFrame(dict(signal_date=dates,ticker=entry['ticker'],security_uid=sid))
        rows.append(keys);prices.append(dict(price_ref=price_ref,keys=keys,role=entry['role']))
    return dict(manifest=manifest,manifest_ref=ref,price_links=links,
        additional_raw_keys=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=['signal_date','ticker','security_uid']),
        additional_price_sources=prices)


def completion_predecessor_reader(bundle,pin,read):
    """Project only declared historical producer metadata, never its payload."""
    parents={(str(Path(tx['predecessor_source_contract_ref']['path']).resolve()),tx['predecessor_source_contract_ref']['sha256'])
        for tx in bundle.get('exact_historical_python_code_custody_transport',())}
    cache={}
    def bounded_read(ref):
        key=(str(Path(ref['path']).resolve()),ref['sha256'])
        if key not in parents:return read(ref)
        if key not in cache:
            path=pin(ref)
            with path.open('rb') as handle:
                selected=_JsonProjection(handle).metadata_fields({'schema','status'})
            with path.open('rb') as handle:
                projection=_JsonProjection(handle);projection.descend(('source_refs',))
                selected['source_refs']=projection.scalar(limit=2*1024*1024)
            cache[key]=selected
        return cache[key]
    return bounded_read


def merge_completion_descendant(combined,descendant,manifest_ref):
    """Compose already-qualified native facts; keep exact old events on corroboration."""
    result=copy.deepcopy(combined);native=descendant['events']
    retained=list(result['entitlement_events'])
    by_key={existing._cash_key(e):e for e in retained if isinstance(e,existing.ca.SourceBackedEntitlementEvent)}
    retained_fingerprints={e.event_fingerprint for e in retained}
    for event in native['entitlement_events']:
        if not isinstance(event,existing.ca.SourceBackedEntitlementEvent):
            require(event.event_fingerprint in retained_fingerprints,'COMPLETION_NONCASH_FACT_MUST_ALREADY_BE_QUALIFIED')
            continue
        key=existing._cash_key(event);prior=by_key.get(key)
        if prior is not None:require(existing._cash_terms(prior)==existing._cash_terms(event),'COMPLETION_CASH_SOURCE_CONFLICT_NO_CHOICE')
        else:retained.append(event);by_key[key]=event
    require(len({e.event_id for e in retained})==len(retained),'COMPLETION_DUPLICATE_TYPED_EVENT_ID')
    removed=native['entitlement_source_binding']['manifest']['removed_exact_original_keys']
    removed_keys={existing.source._key(e) for e in removed}
    # Removal is limited to the native owner's exact independently proved records.
    result['unsupported_events']=tuple(e for e in result.get('unsupported_events',()) if existing.source._key(e) not in removed_keys)
    admissions=[result.get('research_account_authority',{}).get('frozen_history_cash_admission'),native.get('research_account_authority',{}).get('frozen_history_cash_admission')]
    wanted={e.event_fingerprint for e in retained if isinstance(e,existing.ca.ResearchReconstructedCashEvent)}
    if wanted:
        entries={};template=None
        for admission in admissions:
            if admission is None:continue
            if template is None:template=copy.deepcopy(admission)
            for item in admission['events']:
                token=item['event_fingerprint']
                if token in entries:require(entries[token]==item,'COMPLETION_CASH_ADMISSION_CONFLICT')
                entries[token]=item
        require(wanted<=set(entries) and template is not None,'COMPLETION_EXACT_CASH_ADMISSIONS_REQUIRED')
        template.update(source_contract_ref=manifest_ref,source_binding_fingerprint=existing.digest(dict(old=admissions[0],new=admissions[1],manifest_ref=manifest_ref)),events=[entries[k] for k in sorted(wanted)])
        existing.ca._validate_frozen_history_cash_admission(tuple(retained),template)
        result['research_account_authority']['frozen_history_cash_admission']=template
    mappings=dict(result['entitlement_security_tickers'])
    for sid,ticker in native['entitlement_security_tickers'].items():
        require(sid not in mappings or mappings[sid]==ticker,'COMPLETION_RAW_SECURITY_MAPPING_CONFLICT');mappings[sid]=ticker
    result.update(entitlement_events=tuple(sorted(retained,key=lambda e:(str(existing.ca._entitlement_effective_day(e)),e.event_id))),entitlement_security_tickers=mappings)
    result['entitlement_source_binding']=dict(result['entitlement_source_binding'],source_fingerprint=existing.digest(dict(old=result['entitlement_source_binding'],new=native['entitlement_source_binding'],manifest_ref=manifest_ref)),manifest=dict(original=result['entitlement_source_binding']['manifest'],completion=native['entitlement_source_binding']['manifest']),security_tickers=mappings,event_fingerprints=[e.event_fingerprint for e in result['entitlement_events']])
    return result


def apply_special_completion(combined,catalogue,manifest_ref,*,source_pin=None,source_read=None):
    """Instantiate only qualified typed source terms; remove exact proven blockers."""
    require(catalogue.get('schema')=='CONSENSUS_QUALIFIED_SPECIAL_ACCOUNT_CATALOGUE_R1'
        and catalogue.get('status')=='QUALIFIED_SOURCE_FACTS_PRE2026_ACCOUNTING_ONLY',
        'QUALIFIED_SPECIAL_EVENT_CATALOGUE_REQUIRED')
    types={cls.__name__:cls for cls in (existing.ca.SourceBackedStockDistributionEvent,
        existing.ca.SourceBackedForeignCashEvent,existing.ca.SourceBackedEntitlementEvent)}
    result=copy.deepcopy(combined);events=list(result['entitlement_events'])
    by_key={(e.ticker,str(existing.ca._entitlement_effective_day(e).date()),e.action_type):e for e in events}
    special={};mappings=dict(result['entitlement_security_tickers'])
    for record in catalogue['events']:
        require(record.get('type') in types,'EXACT_SPECIAL_TYPED_EVENT_CLASS_REQUIRED')
        event=types[record['type']](**record['terms'])
        require(event.event_fingerprint==record['event_fingerprint']
            and pd.Timestamp('2023-01-01')<=existing.ca._entitlement_effective_day(event)<pd.Timestamp('2026-01-01'),
            'SPECIAL_TYPED_EVENT_HASH_OR_PRE2026_SCOPE_CHANGED')
        available=pd.Timestamp(event.available_at)
        require(available.tzinfo is not None and available<pd.Timestamp('2026-01-01',tz='UTC'),'SPECIAL_SOURCE_PUBLICATION_PRE2026_REQUIRED')
        key=(event.ticker,event.ex_date,event.action_type)
        if key in by_key:
            prior=by_key[key]
            if isinstance(event,existing.ca.SourceBackedStockDistributionEvent):
                require(event.event_fingerprint==prior.event_fingerprint,'SPECIAL_STOCK_SOURCE_CONFLICT')
            else:require(existing._cash_terms(event)==existing._cash_terms(prior),'SPECIAL_CASH_SOURCE_CONFLICT')
        else:events.append(event);by_key[key]=event
        special[event.event_id]=event
        for sid,ticker in ((event.old_security_id,event.ticker),*(([(event.child_security_id,event.child_ticker)]) if isinstance(event,existing.ca.SourceBackedStockDistributionEvent) else [])):
            require(sid not in mappings or mappings[sid]==ticker,'SPECIAL_RAW_SECURITY_MAPPING_CONFLICT');mappings[sid]=ticker
    require(len({e.event_id for e in events})==len(events),'SPECIAL_EVENT_ID_CONFLICT')
    for replacement in catalogue.get('corporate_action_replacements',()):
        prior=[e for e in result.get('corporate_actions',()) if e.event_fingerprint==replacement['original_event_fingerprint']]
        require(len(prior)==1,'EXACT_ORIGINAL_CORPORATE_ACTION_REPLACEMENT_REQUIRED')
        event=existing.ca.CorporateActionTransition(**replacement['terms']);old=prior[0]
        require((event.old_ticker,event.new_ticker,event.effective_date,event.action_type,event.quantity_multiplier,event.cash_component_per_old_share)==('BN','BN','2025-10-10','FORWARD_SPLIT',1.5,0.)
            and event.repair_authorized is True
            and event.source_fingerprint==replacement['source_sha256'] and replacement.get('price_ratio_inference') is False,
            'EXACT_OFFICIAL_BN_OCT10_SOURCE_SPLIT_REPLACEMENT_REQUIRED')
        same_sid=(event.old_security_id==old.old_security_id and event.new_security_id==old.new_security_id)
        if not same_sid:
            require(old.old_security_id==old.new_security_id=='FROZEN_VENDOR:BN'
                and event.old_security_id==event.new_security_id=='FROZEN_RAW_TRANSPORT_CODE:US.BN'
                and source_pin is not None and source_read is not None,'BN_PLACEHOLDER_REQUIRES_EXISTING_DATED_RAW_IDENTITY_BRIDGE')
            bridge_ref=replacement['raw_identity_bridge_ref'];source_pin(bridge_ref);bridge=source_read(bridge_ref)
            require(bridge.get('schema')=='CONSENSUS_BN_OFFICIAL_SPLIT_EXISTING_DATED_RAW_IDENTITY_BRIDGE_R1'
                and bridge.get('status')=='PASS_EXISTING_EXACT_PRIOR_AND_EX_RAW_LINK_NO_CUSIP_EXPANSION'
                and bridge.get('original_vendor_placeholder_sid')==old.old_security_id
                and bridge.get('qualified_raw_accounting_sid')==event.old_security_id
                and bridge.get('new_CUSIP_assignment') is False and bridge.get('new_identity_interval_extension') is False,
                'BN_EXACT_ORIGINAL_RAW_IDENTITY_BRIDGE_REQUIRED')
            rows=bridge['exact_key_rows']
            require(len(rows)==2 and {str(pd.Timestamp(r['signal_date']).date()) for r in rows}=={'2025-10-09','2025-10-10'}
                and all(r['ticker']=='BN' and r['accounting_sid']==event.old_security_id for r in rows),'BN_PRIOR_AND_EX_DATED_RAW_LINK_REQUIRED')
        known=pd.Timestamp(replacement['known_at']);opening=pd.Timestamp('2025-10-10T09:30:00',tz='America/New_York').tz_convert('UTC')
        require(known.tzinfo is not None and known<=opening,'BN_OFFICIAL_SPLIT_NOT_KNOWN_BEFORE_EFFECTIVE_OPEN')
        result['corporate_actions']=tuple(event if e.event_fingerprint==old.event_fingerprint else e for e in result['corporate_actions'])
        known_at=dict(result.get('corporate_action_known_at') or {});known_at.pop(old.event_fingerprint,None);known_at[event.event_fingerprint]=str(known)
        result['corporate_action_known_at']=known_at
    removed=set()
    originals={existing.source._key(e):e for e in result.get('unsupported_events',())}
    for proof in catalogue['resolved_unsupported_records']:
        event=special.get(proof['resolved_event_id']);original=proof['original_record'];key=existing.source._key(original)
        require(event is not None and key in originals and originals[key]==original
            and original['ticker']==event.ticker and pd.Timestamp(original['effective_date'])==existing.ca._entitlement_effective_day(event)
            and proof.get('vendor_price_factor_as_share_ratio') is False
            and proof.get('original_raw_price_coordinate_preserved') is True,'EXACT_SPECIAL_BLOCKER_RESOLUTION_PROOF_REQUIRED')
        removed.add(key)
    result.update(entitlement_events=tuple(events),entitlement_security_tickers=mappings,
        unsupported_events=tuple(e for e in result.get('unsupported_events',()) if existing.source._key(e) not in removed))
    manifest=dict(original=result['entitlement_source_binding']['manifest'],qualified_special_catalogue_ref=manifest_ref,
        resolved_exact_keys=sorted(removed),source_event_fingerprints=sorted(special[e].event_fingerprint for e in special))
    result['entitlement_source_binding']=dict(result['entitlement_source_binding'],manifest=manifest,source_fingerprint=existing.digest(manifest),security_tickers=mappings)
    return result


def read_additional_prices(completion,pin):
    frames=[]
    for source in completion['additional_price_sources']:
        keys=source['keys'];price_ref=source['price_ref'];schema=pq.ParquetFile(pin(price_ref)).schema_arrow.names
        columns=['ticker','trade_date','open','close']+(['price_quality_warning'] if 'price_quality_warning' in schema else [])
        frame=pq.read_table(price_ref['path'],columns=columns,filters=_price_filters(keys)).to_pandas()
        expected=set(zip(pd.to_datetime(keys.signal_date),keys.ticker));actual=set(zip(pd.to_datetime(frame.trade_date),frame.ticker))
        require(actual==expected and not frame.duplicated(['trade_date','ticker']).any(),'EXACT_EXTRA_QUOTE_SOURCE_KEY_COVERAGE_REQUIRED')
        require(np.isfinite(frame[['open','close']].to_numpy(float)).all() and frame.open.gt(0).all() and frame.close.gt(0).all(),'EXTRA_RAW_OPEN_CLOSE_POSITIVE_FINITE_REQUIRED')
        if 'price_quality_warning' not in frame:frame['price_quality_warning']=False
        frames.append(frame)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['ticker','trade_date','open','close','price_quality_warning'])


def merge_raw_price_projections(original,additional):
    if additional.empty:return original
    projections=[frame.copy() for frame in (original,additional)]
    for frame in projections:
        # Preserve the pinned market adapter's absent-column default; explicit
        # null or True warnings remain blocked by its original quality rules.
        if 'price_quality_warning' not in frame:frame['price_quality_warning']=False
    both=pd.concat(projections,ignore_index=True)
    for _,group in both.loc[both.duplicated(['trade_date','ticker'],keep=False)].groupby(['trade_date','ticker']):
        require(group.open.nunique(dropna=False)==group.close.nunique(dropna=False)==1,'ORIGINAL_AND_ADDITIONAL_RAW_QUOTE_CONFLICT')
        if 'price_quality_warning' in group:require(group.price_quality_warning.fillna(True).nunique()==1,'RAW_QUOTE_WARNING_CONFLICT')
    return both.drop_duplicates(['trade_date','ticker']).reset_index(drop=True)


def metadata_preflight(*,frozen_contract_ref,source_scope_ref):
    """Small metadata and identity/calendar columns only; never price decode."""
    require(sha256(existing.__file__)==OWNER_SHA,'ACCOUNT_SOURCE_OWNER_CHANGED')
    child=Path(frozen_contract_ref['path']).resolve().is_relative_to(account.CHILD_RUN.resolve())
    account._metadata_ref(frozen_contract_ref,child=child);account._metadata_ref(source_scope_ref,scope=True,child=child)
    scope=json.loads(Path(source_scope_ref['path']).read_text(encoding='utf-8'))
    require(scope.get('scope_start')=='2023-01-01' and scope.get('scope_end_exclusive')=='2026-01-01'
        and scope.get('raw_price_coordinate')=='RAW_ACTUAL_SHARE' and scope.get('historical_quote_vintage_status')=='UNKNOWN'
        and scope.get('strict_PIT') is False,'TASK_ACCOUNT_SOURCE_SCOPE_REQUIRED')
    sources=scope['sources'];require(set(sources)==set(existing.DEFAULT_REFS),'EXACT_ACCOUNT_SOURCE_CATALOGUE_REQUIRED')
    pin,read,construction_proof=source_fact_custody_reader(scope['legacy_source_transport'],scope.get('source_fact_construction_transport'))
    pin,read,historical_cash_ref,dependency_proof=continuation_dependency_custody(scope,pin,read)
    fact_ref=scope['source_fact_owner_ref'];require(fact_ref['sha256']==SOURCE_ADAPTER_SHA and TASK in Path(fact_ref['path']).parts,'TASK_SOURCE_FACT_OWNER_CUSTODY_REQUIRED');pin(fact_ref)
    deps=scope['source_dependency_refs'];require(set(deps)==set(SOURCE_DEPENDENCIES),'EXACT_SOURCE_FACT_DEPENDENCIES_REQUIRED')
    for key,ref in deps.items():require(ref['sha256']==SOURCE_DEPENDENCIES[key],'SOURCE_FACT_DEPENDENCY_VERSION_CHANGED');pin(ref)
    if dependency_proof is None:
        require(Path(deps['joint_cash_bindings']['path']).resolve()==Path(existing.source.cash.__file__).resolve() and Path(deps['corporate_action']['path']).resolve()==Path(existing.ca.__file__).resolve(),'SOURCE_FACT_DEPENDENCIES_MUST_MATCH_IMPORTED_OWNERS')
    for ref in sources.values():pin(ref)
    pin(scope['pool_ref']);pin(scope['calendar_ref']);pin(scope['settlement_calendar_ref'])
    pool_file,pool_proof=guard_parquet(scope['pool_ref']['path'],scope['pool_ref']['sha256'],['signal_date'])
    calendar_file,calendar_proof=guard_parquet(scope['calendar_ref']['path'],scope['calendar_ref']['sha256'],['trade_date'])
    settle_file,settle_proof=guard_parquet(scope['settlement_calendar_ref']['path'],scope['settlement_calendar_ref']['sha256'],['settlement_date'])
    pool=pq.read_table(scope['pool_ref']['path'],columns=['signal_date','cusip','ticker','security_id','identity_present'],
        filters=[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',pd.Timestamp('2026-01-01'))]).to_pandas()
    calendar=pq.read_table(scope['calendar_ref']['path'],columns=['trade_date'],
        filters=[('trade_date','>=',pd.Timestamp('2023-01-01')),('trade_date','<',pd.Timestamp('2026-01-01'))]).to_pandas()
    settle=pq.read_table(scope['settlement_calendar_ref']['path'],columns=['settlement_date'],filters=[('settlement_date','>=',pd.Timestamp('2023-01-01')),('settlement_date','<',pd.Timestamp('2026-01-01'))]).to_pandas()
    settlement_sessions=pd.DatetimeIndex(settle.settlement_date)
    require(not settlement_sessions.empty and not settlement_sessions.has_duplicates and settlement_sessions.is_monotonic_increasing,'ACCOUNT_SETTLEMENT_CALENDAR_INVALID')
    sessions=pd.DatetimeIndex(calendar.trade_date)
    require(not sessions.empty and not sessions.has_duplicates and sessions.is_monotonic_increasing,'ACCOUNT_CALENDAR_INVALID')
    pool.signal_date=pd.to_datetime(pool.signal_date);pool.cusip=pool.cusip.fillna('').astype(str).str.strip().str.upper()
    require(not pool.duplicated(['signal_date','cusip']).any() and pool.signal_date.isin(sessions).all(),'ACCOUNT_POOL_KEYS_INVALID')
    mapped=pool.loc[pool.identity_present.eq(True)&pool.ticker.notna()&pool.security_id.notna()].copy()
    mapped['security_uid']='CUSIP:'+mapped.cusip
    require(not mapped.duplicated(['signal_date','ticker']).any(),'ACCOUNT_POOL_TICKER_KEY_AMBIGUOUS')
    dated_file,dated_proof=guard_parquet(sources['dated_identity']['path'],sources['dated_identity']['sha256'],['signal_date'])
    dated=pq.read_table(sources['dated_identity']['path'],columns=['signal_date','ticker','security_id','moomoo_transport_code'],
        filters=[('signal_date','>=',pd.Timestamp('2023-01-01')),('signal_date','<',pd.Timestamp('2026-01-01'))]).to_pandas()
    mapping,identity=read(sources['a_mapping']),read(sources['a_identity'])
    links,gaps=existing.identity_links(mapped,mapping,identity,dated)
    raw_file,raw_proof=guard_parquet(sources['raw_prices']['path'],sources['raw_prices']['sha256'],['trade_date'])
    raw_keys=pq.read_table(sources['raw_prices']['path'],columns=['ticker','trade_date'],
        filters=[('trade_date','>=',sessions[0]),('trade_date','<=',sessions[-1]),('ticker','in',sorted(set(mapped.ticker)))]).to_pandas()
    raw_keys=raw_keys.rename(columns={'trade_date':'signal_date'});raw_keys.signal_date=pd.to_datetime(raw_keys.signal_date)
    first=mapped.groupby('ticker').signal_date.min();raw_keys=raw_keys.loc[raw_keys.signal_date.ge(raw_keys.ticker.map(first))&raw_keys.signal_date.isin(sessions)]
    raw_keys=raw_keys.merge(dated,on=['signal_date','ticker'],how='left',validate='one_to_one')
    raw_keys,key_gaps,key_screen=screen_raw_identity_keys(raw_keys)
    raw_links,raw_gaps=existing.identity_links(raw_keys,mapping,identity,dated)
    raw_gaps=key_gaps+raw_gaps
    proof=scope['quote_classification_scope_proof']
    require(proof==dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch='A',classification_ref=sources['quote_classification']),
        'EXACT_PRE2026_CLASSIFICATION_SOURCE_SCOPE_PROOF_REQUIRED')
    signal_metadata=None
    if scope.get('signal_quote_domain_ref') is not None:
        signal_metadata=signal_quote_metadata_preflight(scope['signal_quote_domain_ref'],legacy_source_transport=scope.get('signal_quote_legacy_source_transport',()))
        frozen=signal_metadata['frozen'];signal_proof=scope.get('signal_quote_population_scope_proof')
        require(signal_proof==dict(scope_start='2023-01-01',scope_end_exclusive='2026-01-01',branch='STATEFUL',classification_ref=frozen['population_ref']),'SIGNAL_QUOTE_EXACT_POPULATION_SCOPE_PROOF_REQUIRED')
        for role,current in [('raw_quotes','raw_prices'),('security_mapping','a_mapping')]:
            old=frozen['source_refs'][role]
            require(Path(old['path']).resolve()==Path(sources[current]['path']).resolve() and old['sha256']==sources[current]['sha256'],'SIGNAL_QUOTE_SOURCE_COORDINATE_BINDING_CHANGED')
    else:require(scope.get('signal_quote_population_scope_proof') is None and not scope.get('signal_quote_legacy_source_transport'),'SIGNAL_QUOTE_BINDING_INCOMPLETE')
    physical_stats={str(pin(ref)):dict(size=pin(ref).stat().st_size,mtime_ns=pin(ref).stat().st_mtime_ns) for ref in [*sources.values(),fact_ref,*deps.values()]}
    if construction_proof is not None:
        for transport in construction_proof['transports']:
            path=pin(transport['custody_ref']);stat=path.stat();physical_stats[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    if dependency_proof is not None:
        path=pin(dependency_proof['current_corporate_execution_ref']);stat=path.stat()
        physical_stats[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    if signal_metadata is not None:physical_stats.update(signal_metadata['physical_stats'])
    completion=completion_metadata(scope,pin,read,sessions)
    if completion is not None:
        for source in [completion['manifest_ref'],*completion['manifest']['source_refs'],*[completion['manifest'][k] for k in ('ordinary_bundle_ref','ordinary_owner_ref','ordinary_cash_owner_ref','special_events_ref','price_links_ref','fx_source_book_ref','fx_parser_ref','fx_source_validation_ref')],*[x['price_ref'] for x in completion['additional_price_sources']]]:
            path=pin(source);stat=path.stat();physical_stats[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    return dict(scope=scope,pin=pin,read=read,sources=sources,pool=pool,keys=links,raw_keys=raw_links,calendar=sessions,settlement_calendar=settlement_sessions,physical_stats=physical_stats,signal_quote_metadata=signal_metadata,
        identity_gaps=gaps,raw_identity_gaps=raw_gaps,unmapped_pool_rows=int((~pool.identity_present.eq(True)).sum()),
        frozen_contract_ref=frozen_contract_ref,source_scope_ref=source_scope_ref,
        metadata_proofs={'pool':pool_proof,'calendar':calendar_proof,'dated_identity':dated_proof,'raw_prices':raw_proof,'settlement_calendar':settle_proof,'raw_identity_key_screen':key_screen,'source_fact_construction_transport':construction_proof},
        historical_cash_ref=historical_cash_ref,source_dependency_custody_proof=dependency_proof,source_completion=completion,
        numeric_prices_read=False,quote_numeric_evidence_read=False)


def _price_filters(keys):
    """Exact post-first-entry identity keys; no interval×ticker superset."""
    filters=[]
    for ticker,group in keys.groupby('ticker',sort=True):
        dates=sorted(pd.to_datetime(group.signal_date).unique())
        if dates:filters.append([('ticker','==',ticker),('trade_date','in',dates),('trade_date','>=',pd.Timestamp('2023-01-01')),('trade_date','<',pd.Timestamp('2026-01-01'))])
    return filters


def load_account_inputs(bound,*,signal_adv_by_key):
    """Caller-authorized actual entry; all numeric inputs predicate before decode.

    signal_adv_by_key columns: signal_date,ticker,adv,available_at. Its attrs
    source_ref must match the task source-scope pin. Availability cannot exceed
    signal close. The historical vendor provenance remains UNKNOWN.
    """
    require(sha256(existing.__file__)==OWNER_SHA,'ACCOUNT_SOURCE_OWNER_CHANGED')
    child=bound['scope'].get('research_id')==account.CHILD_RESEARCH_ID
    account._metadata_ref(bound['frozen_contract_ref'],child=child);account._metadata_ref(bound['source_scope_ref'],scope=True,child=child)
    require(json.loads(Path(bound['source_scope_ref']['path']).read_text(encoding='utf-8'))==bound['scope'],'TASK_BOUND_SOURCE_SCOPE_CHANGED')
    scope=bound['scope'];require(scope.get('numeric_read_authorization')==GATE,'TASK_ACCOUNT_NUMERIC_READ_GATE_REQUIRED')
    for path,expected in bound['physical_stats'].items():
        stat=Path(path).stat();require(dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)==expected,'BOUND_PHYSICAL_SOURCE_CHANGED:'+path)
    require(signal_adv_by_key.attrs.get('source_ref')==scope['signal_adv_source_ref'],'SIGNAL_ADV_SOURCE_PIN_REQUIRED')
    adv=signal_adv_by_key[['signal_date','ticker','adv','available_at']].copy();adv.signal_date=pd.to_datetime(adv.signal_date)
    require(not adv.duplicated(['signal_date','ticker']).any() and adv.signal_date.ge('2023-01-01').all() and adv.signal_date.lt('2026-01-01').all(),'SIGNAL_ADV_SCOPE_KEY_CHANGED')
    available=pd.to_datetime(adv.available_at,utc=True);close_at=(adv.signal_date+pd.Timedelta(hours=16)).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    require(available.notna().all() and available.le(close_at).all(),'SIGNAL_ADV_NOT_SIGNAL_KNOWN')
    pin,read,sources=bound['pin'],bound['read'],bound['sources']
    original=joblib.load(pin(sources['original_cash_kwargs']))
    require(not {'market','mu','sigma','feature_cube','predictions'}&set(original),'SOURCE_KWARGS_ONLY_NO_ACCOUNT_OR_FORECAST_CACHE')
    fact_owner=existing._load_python(scope['source_fact_owner_ref'],'_consensus_pinned_ca_source_facts')
    if bound.get('historical_cash_ref') is not None:
        fact_owner.cash=existing._load_python(bound['historical_cash_ref'],'_consensus_historical_fact_cash_owner')
    if original['entitlement_events'] and type(original['entitlement_events'][0]) is not existing.ca.SourceBackedEntitlementEvent:
        import sys
        original=fact_owner.rebind_entitlement_catalogue(original,source_owner=sys.modules[type(original['entitlement_events'][0]).__module__],target_owner=existing.ca)
    original_owner=SimpleNamespace(**vars(existing.account));original_owner._frozen_ca_module=existing.ca
    factory=FunctionType(existing.private_source_adapter.__code__,{**existing.private_source_adapter.__globals__,'source':fact_owner},argdefs=existing.private_source_adapter.__defaults__)
    adapter=factory(pin,read)
    descendant=adapter.bind_source_account_descendant(original_owner,original,read(sources['ordinary_sources']),account_dates=bound['calendar'],bundle_ref=sources['ordinary_sources'])
    terminal_fact=read(sources['a_authority'])['research_account']['research_account_authority']
    combined,composition=existing.combine_cash_and_terminal(descendant,existing._typed_a(read(sources['a_catalogue'])['events']),terminal_fact,bound['frozen_contract_ref'])
    completion=bound.get('source_completion')
    if completion is not None:
        manifest=completion['manifest']
        current=existing._load_python(manifest['ordinary_owner_ref'],'_consensus_current_completion_cash_facts')
        # Historical source bootstrap can retain an old canonical cash module.
        # Bind the independently pinned current parser to this private owner.
        current.cash=existing._load_python(manifest['ordinary_cash_owner_ref'],'_consensus_current_completion_cash_owner')
        require(sha256(current.cash.__file__)==manifest['ordinary_cash_owner_ref']['sha256'],'CURRENT_COMPLETION_CASH_OWNER_CHANGED')
        current_factory=FunctionType(existing.private_source_adapter.__code__,{**existing.private_source_adapter.__globals__,'source':current},argdefs=existing.private_source_adapter.__defaults__)
        current_bundle=read(manifest['ordinary_bundle_ref'])
        current_read=completion_predecessor_reader(current_bundle,pin,read)
        native=current_factory(pin,current_read).bind_source_account_descendant(original_owner,original,current_bundle,account_dates=bound['calendar'],bundle_ref=manifest['ordinary_bundle_ref'])
        combined=merge_completion_descendant(combined,native,completion['manifest_ref'])
        combined=apply_special_completion(combined,read(manifest['special_events_ref']),manifest['special_events_ref'],source_pin=pin,source_read=read)
        book=read(manifest['fx_source_book_ref'])
        require(book.get('schema')=='CONSENSUS_PRE2026_OFFICIAL_H10_CAD_SOURCE_BOOK_R1'
            and book.get('clock_qualification_ref')==account.FX_AVAILABILITY_REF,'QUALIFIED_FROZEN_CAD_SOURCE_BOOK_REQUIRED')
        fx_proof=read(manifest['fx_source_validation_ref'])
        require(existing.digest(book['observations'])==fx_proof['observation_payload_sha256'],'FX_SOURCE_BOOK_OBSERVATION_PAYLOAD_CHANGED')
        combined['foreign_fx_marks']=tuple(existing.ca.SourceBackedFXMark(**entry) for entry in book['observations'])
        composition=dict(original=composition,source_completion_manifest_ref=completion['manifest_ref'],native_source_completion_receipt=native['receipt'])
    require(all(pd.Timestamp('2023-01-01')<=existing.ca._entitlement_effective_day(e)<pd.Timestamp('2026-01-01') for e in combined['entitlement_events']),'TYPED_ACCOUNT_FACT_SCOPE_CHANGED')
    # Retain all original catalogue facts in the composition; empty-prefix replay
    # admits only effective events at/after its first supplied account session.
    combined=copy.deepcopy(combined);active=tuple(e for e in combined['entitlement_events'] if existing.ca._entitlement_effective_day(e)>=bound['calendar'][0])
    admission=combined.get('research_account_authority',{}).get('frozen_history_cash_admission')
    if admission is not None:
        pins={e.event_fingerprint for e in active if isinstance(e,existing.ca.ResearchReconstructedCashEvent)}
        admission['events']=[e for e in admission['events'] if e['event_fingerprint'] in pins]
        if not pins:admission=None
    terminals=tuple(e for e in active if isinstance(e,existing.ca.ResearchReconstructedTerminalEvent))
    market_binding=dict(task_id=TASK,quantity_coordinate='RAW_ACTUAL_SHARE',historical_quote_vintage_status='UNKNOWN',
        source_refs=[sources['raw_prices'],sources['dated_identity'],scope['pool_ref'],scope['calendar_ref'],scope['settlement_calendar_ref'],scope['signal_adv_source_ref']],
        coverage_gaps=['Historical quote vintage UNKNOWN',*bound['identity_gaps'],*bound['raw_identity_gaps'],f"Unmapped pool members retained: {bound['unmapped_pool_rows']}"])
    completion_refs={}
    if completion is not None:
        completion_refs=dict(continuation_scope_ref=scope['continuation_scope_ref'],account_convention_scope_ref=scope['account_convention_scope_ref'],
            account_fx_convention_scope_ref=account.FX_CONVENTION_REF,fx_source_availability_qualification_ref=account.FX_AVAILABILITY_REF)
        market_binding['source_refs'] += [completion['manifest_ref'],completion['manifest']['special_events_ref'],completion['manifest']['price_links_ref'],completion['manifest']['fx_source_book_ref']]
    authority=account.make_task_authority(active,frozen_contract_ref=bound['frozen_contract_ref'],source_scope_ref=bound['source_scope_ref'],
        market_source_binding=market_binding,frozen_history_cash_admission=admission,terminal_source_authority=terminal_fact if terminals else None,**completion_refs)
    combined.update(entitlement_events=active,research_account_authority=authority)
    combined['entitlement_source_binding']['event_fingerprints']=[e.event_fingerprint for e in active]
    keys=bound['raw_keys'];require(not keys.empty,'NO_QUALIFIED_ACCOUNT_PRICE_KEYS');filters=_price_filters(keys);require(bool(filters),'NO_QUALIFIED_ACCOUNT_PRICE_KEYS')
    columns=['ticker','trade_date','open','close'];schema=pq.ParquetFile(pin(sources['raw_prices'])).schema_arrow.names
    if 'price_quality_warning' in schema:columns.append('price_quality_warning')
    prices=pq.read_table(sources['raw_prices']['path'],columns=columns,filters=filters).to_pandas()
    expected=set(zip(pd.to_datetime(keys.signal_date),keys.ticker));actual=set(zip(pd.to_datetime(prices.trade_date),prices.ticker))
    require(actual<=expected,'ACCOUNT_PRICE_PREDICATE_KEY_MISMATCH')
    if completion is not None:
        prices=merge_raw_price_projections(prices,read_additional_prices(completion,pin))
        keys=pd.concat([keys,completion['additional_raw_keys']],ignore_index=True).drop_duplicates(['signal_date','ticker'])
    market_owner=existing._load_python(sources['market_adapter'],'_consensus_existing_raw_market')
    market=market_owner.make_market(existing.account,prices,bound['keys'],bound['calendar'])
    aw=adv.pivot(index='signal_date',columns='ticker',values='adv').reindex(index=market.dates,columns=market.tickers).to_numpy(float)
    market=replace(market,adv=aw)
    composer=existing._load_python(sources['quote_composer'],'_consensus_existing_quote_composer')
    raw_market=market;market=composer.bind_original_wrapper_quality(raw_market,original)
    # Quote validation covers only source-qualified cells; missing/unentered
    # cells retain their original blocked quality bits and are never decoded.
    qualified=np.zeros(market.quality.shape,bool);di={d:i for i,d in enumerate(market.dates)};ti={t:i for i,t in enumerate(market.tickers)}
    for row in keys.itertuples():qualified[di[pd.Timestamp(row.signal_date)],ti[row.ticker]]=True
    checked_quality=market.quality&qualified
    quote_keys=[(market.dates[i],market.tickers[j]) for i,j in zip(*np.nonzero(checked_quality))]
    decisions,projection=project_quote_decisions(sources['quote_classification']['path'],quote_keys,decode_numeric_evidence=True,source_scope_proof=scope['quote_classification_scope_proof'])
    usable,coverage=existing.quote.build_usable_a_mask(market.dates,market.tickers,checked_quality,decisions,raw_open=market.open,raw_close=market.close)
    signal_binding=None
    if bound.get('signal_quote_metadata') is not None:
        selected=market.quality&~raw_market.quality&qualified
        signal_keys=[(market.dates[i],market.tickers[j]) for i,j in zip(*np.nonzero(selected))]
        signal_decisions,signal_projection=project_quote_decisions(bound['signal_quote_metadata']['frozen']['population_ref']['path'],signal_keys,
            decode_numeric_evidence=True,source_scope_proof=scope['signal_quote_population_scope_proof'])
        remaining_market=composer.bind_original_wrapper_quality(raw_market,combined)
        market,usable,signal_audit=apply_signal_quote_binding(raw_market,market,remaining_market,usable,signal_decisions)
        signal_binding=dict(schema='CONSENSUS100_SOURCE_BOUND_SIGNAL_QUOTE_R1',task_id=TASK,source_fact_freeze_ref=scope['signal_quote_domain_ref'],
            population_scope_proof=scope['signal_quote_population_scope_proof'],lineage=bound['signal_quote_metadata']['lineage'],projection=signal_projection,audit=signal_audit,
            historical_quote_vintage_status='UNKNOWN',strict_PIT=False,legacy_execution_authority_reused=False)
    return {**bound,'market':market,'events':combined,'task_authority':authority,'settlement_calendar':bound['settlement_calendar'],
        'usable_a':usable,'signal_quote_binding':signal_binding,'quote_coverage':coverage,'quote_projection':projection,'quote_checked_scope':'original masked AND source-qualified post-first-entry cells; signal upgrade only when both quote owners qualify and no remaining CA/base blocker',
        'cash_source_receipt':descendant['receipt'],'source_composition':composition,'numeric_prices_read':True,'quote_numeric_evidence_read':True,
        'quote_execution_upgrade_applied':False,'signal_quote_upgrade_applied':signal_binding is not None,'certified_NAV':False,'conditional_research_only':True}