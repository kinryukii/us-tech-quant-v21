"""Read-only V24 coverage and finite-budget completion from own-run metadata.

No forecast/ledger/model binary or parquet body is opened. Audit JSON is projected
while streaming: unrequested account values and exception payloads are skipped
without decoding. This reporter neither selects a model nor unlocks the test.
"""
from __future__ import annotations
import argparse, ast, copy, hashlib, json, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from scripts.storage.storage_r2a import resolve_storage_paths, assert_write_path

YEARS=(2023,2024,2025)
BUCKET_LIMITS={'value_meta_primary':384,'value_meta_technical':384,'risk_primary':72,'conditional_final':24}
ALIASES={'M061':'M050','M083':'BASE_STATEFUL_ACTION','M104':'M103'}
OBSERVED_DATE_KEYS={'signal_date','execution_date','label_mature_date','label_end_date','fitted_dates',
 'train_label_maturity_max','calibration_label_maturity_max','train_maturity_max','cal_maturity_max',
 'min_date','max_date','date_min','date_max','max_signal_date','min_signal_date'}
ALL=object();CODE=object()
FAILURE={'type':ALL,'message':CODE}
SLOT={'model_id':ALL,'method_id':ALL,'method':ALL,'year':ALL,'status':ALL,'fit_units':ALL,'failure':FAILURE}
PROGRESS={'status':ALL,'expected_slots':ALL,'slots':[SLOT],'2026_rows_read':ALL,'test_2026_rows_read':ALL}
EVENT={k:ALL for k in ('event','model_id','year','component','fit_units','budget_bucket','role','candidate_id',
 'scientific_tuple_sha256','reuse_tuple_sha256','batch','path_units','stage','audit_path','audit_sha256',
 'risk_estimate_units','reserved_estimate_units','canonical_method','generation')};EVENT['failure']=FAILURE
RECEIPT={k:ALL for k in ('status','model_id','method_id','method','year','role','fit_units','risk_estimate_units',
 'scientific_target_qualified','scientific_feature_pit_qualified','scientific_return_proxy_qualified',
 'model_sha256','reuse_tuple_sha256','source_model_sha256','source_receipt_sha256','canonical_method',
 'source_receipt_path','receipt_path','labels_used','account_input','fusion_rule_kind','test_2026_rows_read',
 '2026_rows_read','generation','ledger_model_id','train_label_maturity_max','calibration_label_maturity_max','fitted_dates')}
RECEIPT['failure']=FAILURE
RECEIPT['source_pins']={'module_sha256':ALL,'repair_transport_sha256':ALL}
RECEIPT['old_failed_receipt']={k:ALL for k in ('receipt_path','receipt_sha256','reuse_tuple_sha256','year')}
RECEIPT['reuse_tuple_source_pins']={'module_sha256':ALL}
RECEIPT['reuse_tuple']={k:ALL for k in ('model_id','method','year','fold','role','cutoff_exclusive',
 'training_signal_and_label_maturity_exclusive','calibration_label_maturity_exclusive','train_maturity_max','cal_maturity_max','original_scientific_tuple_sha256')}
RECEIPT['reuse_tuple']['source_pins']={'module_sha256':ALL,'repair_transport_sha256':ALL}
QUAL={k:ALL for k in ('sessions','accounting_qualified_all','certified_nav_positive_and_finite_all','net_return_finite_except_initial')}
AUDIT={k:ALL for k in ('status','batch','candidate_ids','account_paths_created','attempt_units','calendar_sessions',
 'annual_reset','candidates_sha256','selection_performed','fit_units','2026_rows_read','test_2026_rows_read')}
AUDIT.update(selection_eligibility={'*':{'*':QUAL}},failure=FAILURE,
 blocked={'*':FAILURE},blocked_candidates={'*':FAILURE},source_closure={'module_sha256':ALL})
CONFIG={k:ALL for k in ('strategy_version','parent_task_id','strategy_id','run_id','results_directory',
 'phase','prior_cumulative_fit_units','prior_account_paths','training_cutoff_exclusive','evaluation_years',
 'request_path','request_sha256','test_access','2026_rows_read','fractional_primary')}
CONFIG['research_design']={'finite_execution':ALL,'evaluation':{'family_upper_bound':ALL,'hac_lag':ALL}}
for name in ('value_training','fusion_training','value_repair','risk_training','aux_training','conditional_final'):
 CONFIG[name]={k:ALL for k in ('status','budget_bucket','max_new_bucket_fit_units','max_fit_units','max_model_year_attempts','module_sha256')}
CONFIG['value_repair'].update({k:ALL for k in ('method','generation','repair_transport_sha256')})
CONFIG['stateful_replay']={k:ALL for k in ('status','candidates_path','candidates_sha256','module_sha256','max_account_paths')}
CONFIG['stateful_candidates']=ALL


class _Projection:
 """Minimal streaming JSON projection; discarded values are never decoded."""
 def __init__(self,stream):self.stream=stream;self.c=stream.read(1)
 def step(self):self.c=self.stream.read(1)
 def ws(self):
  while self.c and self.c.isspace():self.step()
 def string(self,keep=True,code=False):
  if self.c!='"':raise ValueError('METADATA_JSON_STRING_REQUIRED')
  chars=[];active=True;escaped=False;self.step()
  while self.c:
   ch=self.c;self.step()
   if not escaped and ch=='"':
    if not keep:return None
    if code:
     token=''.join(chars);return token if token and token[0].isupper() else 'UNCLASSIFIED_ERROR'
    return json.loads('"'+''.join(chars)+'"')
   if code:
    if active and (ch.isupper() or ch.isdigit() or ch=='_') and len(chars)<128:chars.append(ch)
    else:active=False
   elif keep:chars.append(ch)
   if escaped:escaped=False
   elif ch=='\\':escaped=True
  raise ValueError('INCOMPLETE_METADATA_JSON_STRING')
 def value(self,schema):
  self.ws()
  if self.c=='{':
   self.step();out={};self.ws()
   while self.c!='}':
    key=self.string();self.ws()
    if self.c!=':':raise ValueError('METADATA_JSON_COLON_REQUIRED')
    self.step();child=ALL if schema is ALL else schema.get(key,schema.get('*')) if isinstance(schema,dict) else None
    item=self.value(child)
    if child is not None:out[key]=item
    self.ws()
    if self.c==',':self.step();self.ws()
    elif self.c!='}':raise ValueError('METADATA_JSON_OBJECT_DELIMITER')
   self.step();return out if schema is not None else None
  if self.c=='[':
   self.step();out=[];self.ws();child=ALL if schema is ALL else schema[0] if isinstance(schema,list) else None
   while self.c!=']':
    item=self.value(child)
    if child is not None:out.append(item)
    self.ws()
    if self.c==',':self.step();self.ws()
    elif self.c!=']':raise ValueError('METADATA_JSON_ARRAY_DELIMITER')
   self.step();return out if schema is not None else None
  if self.c=='"':return self.string(keep=schema is not None,code=schema is CODE)
  token=[]
  while self.c and self.c not in ',}] \r\n\t':
   if schema is not None:token.append(self.c)
   self.step()
  if schema is None:return None
  if not token:raise ValueError('METADATA_JSON_VALUE_REQUIRED')
  return json.loads(''.join(token))


def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _own(run,path):
 p=Path(path);p=p if p.is_absolute() else run/p;p=p.resolve()
 if not p.is_relative_to(run) or p.suffix.lower() not in ('.json','.jsonl'):
  raise ValueError('COMPLETION_ONLY_OWN_RUN_JSON_METADATA:'+str(p))
 return p


def _boundary(item,key=''):
 if isinstance(item,dict):
  for k,v in item.items():
   if k in ('2026_rows_read','test_2026_rows_read') and v not in (0,None):raise ValueError('TEST_INFORMATION_ALREADY_READ')
   if k=='year':
    if isinstance(v,bool) or not isinstance(v,int):raise ValueError('NONINTEGER_MODEL_OR_EVENT_YEAR')
    if v>=2026:raise ValueError('POST2025_MODEL_OR_EVENT_METADATA_REFUSED')
   _boundary(v,k)
 elif isinstance(item,list):
  for v in item:_boundary(v,key)
 elif key in OBSERVED_DATE_KEYS and isinstance(item,str) and re.match(r'^\d{4}-',item) and item[:4]>='2026':
  raise ValueError('POST2025_OBSERVATION_FOOTER_METADATA_REFUSED')


def read_metadata(run,path,schema):
 p=_own(run,path)
 with p.open('r',encoding='utf-8-sig') as stream:
  parser=_Projection(stream);out=parser.value(schema);parser.ws()
  if parser.c:raise ValueError('TRAILING_METADATA_JSON')
 _boundary(out);return out


def read_events(run,name):
 p=_own(run,name)
 if not p.exists():return [],False
 events=[];incomplete=False
 with p.open('r',encoding='utf-8-sig') as stream:
  while True:
   parser=_Projection(stream);parser.ws()
   if not parser.c:break
   try:item=parser.value(EVENT)
   except ValueError:
    # Only an unfinished last append is an in-progress snapshot, never a success.
    if not parser.c:incomplete=True;break
    raise
   _boundary(item);events.append(item)
   # Parser lookahead is a newline; avoid consuming a following event's first byte.
   if parser.c and not parser.c.isspace():raise ValueError('JSONL_EVENT_DELIMITER_REQUIRED')
 return events,incomplete


def source_maps(repo):
 def constant(path,name):
  tree=ast.parse(path.read_text(encoding='utf-8'))
  for node in tree.body:
   if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):return ast.literal_eval(node.value)
  raise ValueError('RUNTIME_METADATA_CONSTANT_MISSING:'+name)
 fusion=constant(repo/'scripts/research/a2/training/stateful_fusion.py','METHODS')
 aux=repo/'scripts/research/a2/training/stateful_aux.py';methods=constant(aux,'METHODS')
 tree=ast.parse(aux.read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='IDS' for t in n.targets))
 # Consume the existing IDS=dict(zip(METHODS,range(...))) declaration, not a second row catalogue.
 call=node.value;z=call.args[0];bounds=z.args[1]
 if not (isinstance(call.func,ast.Name) and call.func.id=='dict' and isinstance(z.func,ast.Name) and z.func.id=='zip' and isinstance(z.args[0],ast.Name) and z.args[0].id=='METHODS' and isinstance(bounds.func,ast.Name) and bounds.func.id=='range'):raise ValueError('AUX_IDS_SOURCE_SCHEMA_CHANGED')
 ids=tuple(range(*(ast.literal_eval(a) for a in bounds.args)))
 if len(methods)!=len(ids):raise ValueError('AUX_IDS_SOURCE_LENGTH_CHANGED')
 from scripts.research.a2.risk.joint_risk_estimators import canonical_method
 return fusion,dict(zip(ids,methods)),canonical_method


def _integer(value,name):
 if isinstance(value,bool) or not isinstance(value,int) or value<0:raise ValueError('NONINTEGER_FINITE_BUDGET:'+name)
 return value


def budget_audit(cfg,fit_events,path_events):
 if cfg.get('prior_cumulative_fit_units')!=18 or cfg.get('prior_account_paths')!=4:raise ValueError('PRIOR_FAILED_RESEARCH_COUNTS_CHANGED')
 counts=Counter();violations=[]
 for stage in ('value_training','fusion_training','value_repair','risk_training','aux_training','conditional_final'):
  auth=cfg.get(stage,{})
  if auth.get('status')=='FROZEN':
   bucket=auth.get('budget_bucket')
   if bucket not in BUCKET_LIMITS:violations.append('UNDECLARED_AUTH_BUCKET:'+str(bucket))
   elif auth.get('max_new_bucket_fit_units')!=BUCKET_LIMITS[bucket]:violations.append('AUTH_BUCKET_LIMIT_CHANGED:'+stage)
   if auth.get('max_fit_units')!=882 or auth.get('max_model_year_attempts')!=201:violations.append('AUTH_GLOBAL_LIMIT_CHANGED:'+stage)
 for event in fit_events:
  if event.get('event')=='FIT_STARTED':counts[event.get('budget_bucket','UNDECLARED')]+=_integer(event.get('fit_units'),'fit_units')
  if event.get('event')=='RISK_METHOD_EXACT_REUSED' and event.get('fit_units')!=0:violations.append('ALIAS_HAS_NONZERO_FIT_UNITS')
 for bucket,used in counts.items():
  if bucket not in BUCKET_LIMITS:violations.append('UNDECLARED_FIT_BUCKET:'+str(bucket))
  elif used>BUCKET_LIMITS[bucket]:violations.append('FIT_BUCKET_EXCEEDED:'+bucket)
 started=[e for e in fit_events if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED']
 paths=[e for e in path_events if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
 if any(e.get('path_units')!=1 for e in paths):violations.append('NONCANONICAL_ACCOUNT_PATH_UNIT')
 new=sum(counts.values());fullpaths=4+len(paths)
 if 18+new>882:violations.append('GLOBAL_FIT_CAP_EXCEEDED')
 if len(started)>201:violations.append('MODEL_YEAR_ATTEMPT_CAP_EXCEEDED')
 if fullpaths>220:violations.append('FULL_PATH_CAP_EXCEEDED')
 reserved=sum(_integer(e.get('reserved_estimate_units',0),'reserved_estimate_units') for e in fit_events if e.get('event')=='RISK_ESTIMATE_STARTED')
 analytical=sum(_integer(e.get('risk_estimate_units',0),'risk_estimate_units') for e in fit_events if e.get('event')=='RISK_ESTIMATE')
 if max(reserved,analytical)>352000:violations.append('ANALYTICAL_RISK_CAP_EXCEEDED')
 failed={(e.get('model_id'),e.get('year')) for e in fit_events if e.get('event')=='MODEL_YEAR_FAILED'}
 failed_units=sum(e.get('fit_units',0) for e in fit_events if e.get('event')=='FIT_STARTED' and (e.get('model_id'),e.get('year')) in failed)
 return dict(status='WITHIN_FIXED_LIMITS' if not violations else 'BUDGET_AUDIT_FAILED',violations=violations,
  prior_fit_units=18,prior_account_paths=4,new_fit_units=new,cumulative_fit_units=18+new,cumulative_fit_limit=882,
  buckets={b:dict(used=counts[b],limit=limit,remaining=max(0,limit-counts[b]),authorization_state=next((a.get('status','NOT_STARTED') for a in (cfg.get(k,{}) for k in ('value_training','fusion_training','value_repair','risk_training','aux_training','conditional_final')) if a.get('budget_bucket')==b),'NOT_STARTED_AUTH_NOT_PRESENT')) for b,limit in BUCKET_LIMITS.items()},
  unknown_bucket_units={b:n for b,n in counts.items() if b not in BUCKET_LIMITS},
  model_year_attempts=len(started),model_year_attempt_limit=201,failed_model_years=len(failed),failed_fit_units_included=failed_units,
  account_path_attempts_new=len(paths),account_path_attempts_cumulative=fullpaths,account_path_limit=220,
  failed_path_attempts=sum(e.get('event')=='ACCOUNT_PATH_FAILED' for e in path_events),aliases_new_fit_units=0,
  risk_estimate_units_completed=analytical,risk_estimate_units_reserved=reserved,risk_estimate_limit=352000,
  account_candidate_day_call_upper_bound=fullpaths*800,account_candidate_day_call_limit=176000,
  risk_call_upper_bound=fullpaths*1600,risk_call_limit=352000,q_optimizer_call_limit=0,
  calls_are_conservative_upper_bounds_not_observed_counts=True,
  counting_rule='FIT_STARTED and ACCOUNT_PATH_ATTEMPT_STARTED only; failed/obsolete attempts retained; completed/failed summaries never added again')


def failure_state(record):
 code=record.get('failure',{}).get('message','')
 if 'BUDGET' in code or code.endswith(('_CAP_EXHAUSTED','_BUCKET_EXHAUSTED')):return 'BUDGET_STOP_NOT_COMPLETE'
 if code.startswith('BLOCKED_DEPENDENCY'):return 'BLOCKED_DEPENDENCY'
 if code.startswith(('BLOCKED_INPUT','BLOCKED_DATA','RISK_REQUIRES','FUSION_REQUIRES','NO_MATURED','HELDOUT','UNQUALIFIED')):return 'BLOCKED_INPUT'
 return 'FAILED'


def annual_state(run,group,model,year,progress,auth,path_override=None):
 path=_own(run,path_override) if path_override else run/'models'/group/model/str(year)/'fit_receipt.json'
 if path.exists():
  receipt=read_metadata(run,path,RECEIPT);status=receipt.get('status','UNKNOWN')
  if receipt.get('year')!=year:raise ValueError('ANNUAL_RECEIPT_YEAR_CHANGED')
  identity=receipt.get('method') if group=='aux' else receipt.get('method_id') if group=='risk' else receipt.get('model_id')
  if identity!=model:raise ValueError('MODEL_RECEIPT_SLOT_IDENTITY_CHANGED')
  state='IN_PROGRESS' if status=='RUNNING' else failure_state(receipt) if status in ('FAILED','ERROR') else status
  producer=receipt.get('source_pins',receipt.get('reuse_tuple',{}).get('source_pins',{}))
  qualified=receipt.get('scientific_feature_pit_qualified') is True and auth.get('status')=='FROZEN' and bool(auth.get('module_sha256')) and producer.get('module_sha256')==auth.get('module_sha256')
  if group in ('value','fusion'):qualified &= receipt.get('scientific_target_qualified') is True
  if group=='risk':qualified &= receipt.get('scientific_return_proxy_qualified') is True
  qualified &= isinstance(receipt.get('model_sha256',receipt.get('source_model_sha256')),str) and bool(re.fullmatch('[0-9a-f]{64}',receipt.get('model_sha256',receipt.get('source_model_sha256',''))))
  if state in ('TRAINED','FITTED','EXACT_REUSED','EXACT_METHOD_REUSED') and not qualified:state='UNQUALIFIED_RECEIPT'
  return dict(year=year,state=state,producer_status=status,metadata_qualified=qualified and state not in ('FAILED','BLOCKED_INPUT','BLOCKED_DEPENDENCY','IN_PROGRESS','UNQUALIFIED_RECEIPT'),receipt_path=str(path),receipt_sha256=sha(path),reuse_tuple_sha256=receipt.get('reuse_tuple_sha256'),fit_units=receipt.get('fit_units',0),model_sha256=receipt.get('model_sha256',receipt.get('source_model_sha256')),failure=receipt.get('failure'),qualification_authority='PRODUCER_RECEIPT_METADATA_ONLY; model binary and numerical outputs not inspected')
 matching=[s for s in progress.get('slots',[]) if s.get('year')==year and model in (s.get('model_id'),s.get('method_id'),s.get('method'))]
 if len(matching)>1:raise ValueError('DUPLICATE_PROGRESS_SLOT')
 record=matching[0] if matching else {};status=record.get('status','NOT_RUN')
 return dict(year=year,state=failure_state(record) if status in ('FAILED','ERROR','NOT_ATTEMPTED_COMMON_BLOCK') else 'MISSING_RECEIPT' if status in ('TRAINED','FITTED','EXACT_REUSED') else status,producer_status=status,metadata_qualified=False,fit_units=record.get('fit_units',0),failure=record.get('failure'))



def technical_states(run,repo,cfg,model,primary):
 auth=cfg.get('value_repair',{})
 if auth.get('method')!=model:return [],None
 source=repo/'scripts/research/a2/training/stateful_value_repair.py';tree=ast.parse(source.read_text(encoding='utf-8'))
 literals={t.id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) for t in n.targets if isinstance(t,ast.Name) and t.id in ('GENERATION','LEDGER_ID')}
 generation=literals['GENERATION'];ledger=literals['LEDGER_ID']
 if auth.get('status')!='FROZEN' or auth.get('generation')!=generation:raise ValueError('REPAIR_METADATA_AUTH_OR_GENERATION_CHANGED')
 result=[]
 for previous in primary:
  year=previous['year'];path=run/'models/value'/model/str(year)/generation/'fit_receipt.json'
  if not path.exists():result.append(dict(year=year,state='NOT_RUN',metadata_qualified=False,fit_units=0));continue
  receipt=read_metadata(run,path,RECEIPT);old=receipt.get('old_failed_receipt',{});tup=receipt.get('reuse_tuple',{})
  if receipt.get('generation')!=generation or receipt.get('ledger_model_id')!=ledger or old.get('receipt_sha256')!=previous.get('receipt_sha256') or tup.get('original_scientific_tuple_sha256')!=previous.get('reuse_tuple_sha256') or tup.get('source_pins',{}).get('repair_transport_sha256')!=auth.get('repair_transport_sha256'):
   raise ValueError('REPAIR_MUST_BIND_RETAINED_OLD_FAILURE_AND_EXACT_SCIENTIFIC_TUPLE')
  result.append(annual_state(run,'value',model,year,{},cfg.get('value_training',{}),path))
 return result,ledger


def _candidates(run,cfg):
 auth=cfg.get('stateful_replay',{})
 if 'candidates_path' in auth:
  path=_own(run,auth['candidates_path'])
  if sha(path)!=auth.get('candidates_sha256'):raise ValueError('CANDIDATE_METADATA_PIN_CHANGED')
  candidates=read_metadata(run,path,ALL)
 else:
  candidates=cfg.get('stateful_candidates',[])
  if candidates:
   digest=hashlib.sha256(json.dumps(candidates,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
   if digest!=auth.get('candidates_sha256'):raise ValueError('INLINE_CANDIDATE_METADATA_PIN_CHANGED')
 if not isinstance(candidates,list):raise ValueError('CANDIDATE_LIST_REQUIRED')
 if len({c['candidate_id'] for c in candidates})!=len(candidates):raise ValueError('DUPLICATE_CANDIDATE_ID')
 return candidates


def account_states(run,cfg,candidates,events):
 audits={};by_id={}
 for event in events:
  p=event.get('audit_path')
  if p and p not in audits:
   path=_own(run,p)
   if sha(path)!=event.get('audit_sha256'):raise ValueError('ACCOUNT_AUDIT_METADATA_PIN_CHANGED')
   audits[p]=read_metadata(run,path,AUDIT)
 for path in sorted((run/'ledgers/stateful').glob('attempt_*/audit.json')):
  if str(path) not in audits:audits[str(path)]=read_metadata(run,path,AUDIT)
 for audit in audits.values():
  eligibility=audit.get('selection_eligibility',{})
  if set(eligibility).difference({c['candidate_id'] for c in candidates}):raise ValueError('UNREGISTERED_ACCOUNT_QUALIFICATION')
  for candidate,annual in eligibility.items():
   if set(annual)!=set(map(str,YEARS)):raise ValueError('QUALIFICATION_MUST_HAVE_ALL_THREE_PRE2026_YEARS')
   good=cfg.get('phase')=='FROZEN' and cfg.get('stateful_replay',{}).get('status')=='FROZEN' and audit.get('status')=='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE' and audit.get('calendar_sessions')==752 and audit.get('annual_reset') is False
   if cfg.get('stateful_replay',{}).get('module_sha256')!=audit.get('source_closure',{}).get('module_sha256'):good=False
   if audit.get('candidates_sha256')!=cfg.get('stateful_replay',{}).get('candidates_sha256'):good=False
   good &= sum(_integer(a.get('sessions',0),'qualification.sessions') for a in annual.values())==752
   good &= all(a.get('sessions',0)>0 and all(a.get(k) is True for k in ('accounting_qualified_all','certified_nav_positive_and_finite_all','net_return_finite_except_initial')) for a in annual.values())
   by_id[candidate]=dict(state='QUALIFIED_ACCOUNT_METADATA' if good else 'NOT_TESTABLE',annual_qualification=annual,audit_status=audit['status'])
 for c in candidates:
  identity=c['candidate_id'];history=[e for e in events if e.get('candidate_id')==identity]
  if identity in by_id:continue
  failed=next((e for e in reversed(history) if e.get('event')=='ACCOUNT_PATH_FAILED'),None)
  by_id[identity]=dict(state=failure_state(failed) if failed else 'IN_PROGRESS' if history else 'NOT_RUN',failure=failed.get('failure') if failed else None)
 baseline=[c['candidate_id'] for c in candidates if c.get('action')=='raw' and c.get('gross')=='fixed' and c.get('control','none')=='none' and c.get('forecast','none')=='none']
 baseline_state='QUALIFIED_ACCOUNT_METADATA' if len(baseline)==1 and by_id[baseline[0]]['state']=='QUALIFIED_ACCOUNT_METADATA' else 'NOT_TESTABLE'
 return by_id,dict(state=baseline_state,candidate_ids=baseline,selection_testable=baseline_state=='QUALIFIED_ACCOUNT_METADATA',economic_NO_FINALIST_inferred=False)


def _write(path,payload):
 assert_write_path(path,'report');path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix(path.suffix+'.tmp')
 temp.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+'\n' if not isinstance(payload,str) else payload,encoding='utf-8');temp.replace(path)


def build_report(run):
 paths=resolve_storage_paths();run=Path(run).resolve()
 if not run.is_relative_to(paths.backtest_root.resolve()):raise ValueError('COMPLETION_RUN_OUTSIDE_BACKTEST_ROOT')
 cfg=read_metadata(run,'run_config.json',CONFIG)
 if cfg.get('strategy_version')!='V24' or cfg.get('training_cutoff_exclusive')!='2026-01-01' or cfg.get('evaluation_years')!=list(YEARS):raise ValueError('COMPLETION_V24_PRE2026_BOUNDARY')
 out=Path(cfg['results_directory']).resolve()
 if not out.is_relative_to(paths.results_root.resolve()) or out.name!='V24':raise ValueError('COMPLETION_REPORT_OUTSIDE_RESULTS_V24')
 coverage_path=run/'method_coverage.json';coverage=read_metadata(run,coverage_path,ALL)
 rows=coverage.get('methods',[]);ids=[r.get('method_id') for r in rows]
 if coverage.get('count')!=106 or ids!=[f'M{i:03d}' for i in range(1,107)] or coverage.get('request_sha256')!=cfg.get('request_sha256'):raise ValueError('ORIGINAL_106_CATALOGUE_IDENTITY_CHANGED')
 a=sum(r.get('applicability')=='A_APPLIES' for r in rows);b=sum(r.get('applicability')=='HANDOFF_B' for r in rows)
 if (a,b)!=(78,28):raise ValueError('A78_B28_SCOPE_CHANGED')
 fits,fit_tail=read_events(run,'FIT_LOG.jsonl');path_events,path_tail=read_events(run,'ACCOUNT_PATH_LOG.jsonl')
 budget=budget_audit(cfg,fits,path_events)
 if fit_tail or path_tail:budget.update(status='INCOMPLETE_APPEND_SNAPSHOT',counts_are_completed_log_prefix_only=True)
 fusion,aux,risk_name=source_maps(paths.repo_root)
 progress={g:read_metadata(run,f'logs/{g}_batch_status.json',PROGRESS) if (run/f'logs/{g}_batch_status.json').exists() else {'status':'NOT_RUN','slots':[]} for g in ('value','fusion','risk','aux')}
 candidates=_candidates(run,cfg);accounts,baseline=account_states(run,cfg,candidates,path_events)
 canonical_ids=set(ids)
 for c in candidates:
  if not isinstance(c.get('source_method_ids'),list) or not set(c['source_method_ids']).issubset(canonical_ids):raise ValueError('CANDIDATE_SOURCE_METHOD_IDS_NOT_ORIGINAL106')
 report=copy.deepcopy(coverage);report.update(original_catalogue_sha256=sha(coverage_path),catalogue_schema_preserved=True,report_type='OBSERVED_METADATA_COMPLETION_NOT_NEW_METHOD_AUTHORITY',catalogue_declared_status=coverage.get('status'),status='METADATA_REPORT_GENERATED',all_106_trained=False,all_106_assessed_by_A=False)
 for row in report['methods']:
  mid=row['method_id'];number=int(mid[1:]);binding=None;role=row['scientific_role']
  row['catalogue_declared_runtime']={k:row.get(k) for k in ('status','actual_fit_units','actual_account_paths','empirical_validation')}
  if row['applicability']=='HANDOFF_B':
   row.update(status='NOT_ASSESSED_BY_A',actual_fit_units=0,actual_account_paths=0,empirical_validation='NOT_ASSESSED_BY_A')
   row['observed_runtime']={'state':'NOT_ASSESSED_BY_A','annual_models':[],'account_representatives':[],'actual_fit_units':0};continue
  if role=='VALUE_PRIMITIVE':binding=('value',row.get('native_model_id',row.get('extension_model_id')))
  elif number in fusion:binding=('fusion',fusion[number])
  elif number in aux:binding=('aux',aux[number])
  elif role=='RISK_SIGNAL_PROXY':binding=('risk',risk_name(re.sub(r'\s*/\s*','/',row['method'])))
  annual=[annual_state(run,*binding,y,progress[binding[0]],cfg.get(binding[0]+'_training',{})) for y in YEARS] if binding and binding[1] else []
  primary=list(annual);technical,repair_id=technical_states(run,paths.repo_root,cfg,binding[1],primary) if binding and binding[0]=='value' else ([],None)
  annual=[next((r for r in technical if r['year']==a['year'] and r['state']!='NOT_RUN'),a) for a in primary]
  internal=[annual_state(run,'value',binding[1],y,progress['value'],cfg.get('value_training',{})) for y in (2021,2022)] if binding and binding[0]=='value' and binding[1] in ('ridge','hgb','lgb') else []
  reps=[c for c in candidates if mid in c['source_method_ids']]
  if mid=='M061':reps=[c for c in candidates if 'M050' in c['source_method_ids'] or mid in c['source_method_ids']]
  elif mid=='M104':reps=[c for c in candidates if 'M103' in c['source_method_ids'] or mid in c['source_method_ids']]
  elif mid=='M083':reps=[c for c in candidates if c.get('action')=='stateful']
  elif mid=='M099' and cfg.get('fractional_primary') is True:reps=list(candidates)
  model=binding[1] if binding else None;log_id=('RISK::' if binding and binding[0]=='risk' else 'AUX::' if binding and binding[0]=='aux' else '')+str(model)
  actual=[e for e in fits if e.get('event')=='FIT_STARTED' and e.get('model_id') in (log_id,repair_id)]
  states={s['state'] for s in annual};state='NOT_RUN' if not reps or all(accounts[c['candidate_id']]['state']=='NOT_RUN' for c in reps) else 'FIXED_RULE_EXECUTED_QUALIFIED_METADATA' if any(accounts[c['candidate_id']]['state']=='QUALIFIED_ACCOUNT_METADATA' for c in reps) else 'FIXED_RULE_NO_ECONOMIC_QUALIFICATION'
  if annual:
   state='MODEL_METADATA_QUALIFIED' if all(s['metadata_qualified'] for s in annual) else 'FAILED' if 'FAILED' in states else 'BUDGET_STOP_NOT_COMPLETE' if 'BUDGET_STOP_NOT_COMPLETE' in states else 'BLOCKED_DEPENDENCY' if 'BLOCKED_DEPENDENCY' in states else 'BLOCKED_INPUT' if 'BLOCKED_INPUT' in states else 'PARTIAL_OR_NOT_RUN'
  if number in aux and state=='MODEL_METADATA_QUALIFIED':state='DIAGNOSTIC_ONLY_METADATA_QUALIFIED'
  row.update(status=state,actual_fit_units=sum(e['fit_units'] for e in actual),actual_account_paths=sum(any(e.get('candidate_id')==c['candidate_id'] and e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED' for e in path_events) for c in reps),empirical_validation='DIAGNOSTIC_ONLY' if number in aux else 'NO_PORTFOLIO_OUTCOME_CLAIMED')
  row['observed_runtime']=dict(state=state,fit_log_model_ids=[i for i in (log_id,repair_id) if i and i!='None'],model_binding=dict(group=binding[0],model_id=model) if binding else None,annual_models=annual,primary_annual_models=primary,technical_repair_models=technical,internal_packet_models=internal,actual_fit_units=sum(e['fit_units'] for e in actual),fit_components=dict(Counter(e.get('component','UNKNOWN') for e in actual)),alias_of=ALIASES.get(mid),account_representatives=[dict(candidate_id=c['candidate_id'],**accounts[c['candidate_id']]) for c in reps],portfolio_outcome_claimed=False,diagnostic_only=number in aux)
 # Read the sole append journals again after model receipts. Counts include every
 # acknowledged start that produced an observed receipt, while states remain a
 # conservative live snapshot and are never a freeze or economic selection.
 fits,fit_tail=read_events(run,'FIT_LOG.jsonl');path_events,path_tail=read_events(run,'ACCOUNT_PATH_LOG.jsonl')
 budget=budget_audit(cfg,fits,path_events)
 if fit_tail or path_tail:budget.update(status='INCOMPLETE_APPEND_SNAPSHOT',counts_are_completed_log_prefix_only=True)
 for row in report['methods']:
  obs=row['observed_runtime']
  if row['applicability']=='HANDOFF_B':continue
  actual=[e for e in fits if e.get('event')=='FIT_STARTED' and e.get('model_id') in obs['fit_log_model_ids']]
  units=sum(e['fit_units'] for e in actual);obs.update(actual_fit_units=units,fit_components=dict(Counter(e.get('component','UNKNOWN') for e in actual)))
  attempted={e.get('candidate_id') for e in path_events if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'}
  row.update(actual_fit_units=units,actual_account_paths=sum(c['candidate_id'] in attempted for c in obs['account_representatives']))
 report['observed_summary']=dict(A_methods=78,B_handoff_not_assessed=28,states=dict(Counter(r['observed_runtime']['state'] for r in report['methods'])),baseline=baseline,budget_status=budget['status'],test_access='LOCKED; COMPLETION_REPORT_CANNOT_AUTHORIZE_TEST',economic_selection_performed=False)
 task=dict(task=cfg.get('strategy_id'),run_id=cfg.get('run_id'),strategy_version='V24',report_created_utc=datetime.now(timezone.utc).isoformat(),run_dir=str(run),status='NOT_TESTABLE' if not baseline['selection_testable'] else 'PENDING_ECONOMIC_SELECTION',training_progress={k:{'status':p.get('status'),'observed_slots':len(p.get('slots',[])),'expected_slots':p.get('expected_slots')} for k,p in progress.items()},A_methods=78,B_methods_not_assessed=28,all_106_trained=False,baseline=baseline,model_states=report['observed_summary']['states'],cumulative_fit_units=budget['cumulative_fit_units'],account_path_attempts_cumulative=budget['account_path_attempts_cumulative'],partial_append_snapshot=fit_tail or path_tail,snapshot_is_live_not_a_freeze=True,test_2026_rows_read=0,test_access='LOCKED_BEFORE_FINALIST_FREEZE',selection_performed=False,finalist_status='NOT_DECIDED; FAILED_OR_BLOCKED_IS_NOT_ECONOMIC_NO_FINALIST',qualification_scope='PRODUCER_METADATA_ONLY; no forecast/NAV/return/body inspected',prior_failed_and_superseded_research_retained=True,source_sha256=sha(__file__),coverage_source_sha256=sha(coverage_path))
 lines=['V24 方法覆盖元数据报告','',f'A 适用 78 项；B 分工 28 项，本报告未评价 B。当前基准资格：{baseline["state"]}。',
  '模型状态来自本 run 的 receipt；执行状态来自显式候选和账户资格布尔元数据。没有读取预测、NAV 或收益，也没有经济胜负结论。',
  'M045–049 仅表征诊断；M061= M050，M083=原 Action 不确定性逻辑，M104= M103，不增加独立 fit/账户路径。','',
  '| 方法 | 原名称 | 分工 | 年度模型状态 | 新 fit 次数 | 执行代表 |','|---|---|---|---|---:|---|']
 for row in report['methods']:
  obs=row['observed_runtime'];annual=', '.join(f'{s["year"]}:{s["state"]}' for s in obs['annual_models']) or obs['state'];reps=', '.join(f'{r["candidate_id"]}:{r["state"]}' for r in obs['account_representatives']) or '未执行'
  lines.append('| '+ ' | '.join((row['method_id'],str(row['method']).replace('|','/'),row['applicability'],annual,str(obs['actual_fit_units']),reps))+' |')
 record_md=f'V24 当前任务记录\n\n状态：{task["status"]}。累计 fit={budget["cumulative_fit_units"]}/882，累计账户尝试={budget["account_path_attempts_cumulative"]}/220；失败和旧18 fit、旧4路径均保留。\n\nA78/B28分工，不宣称106项都训练成功。缺少完整三年度账户资格意味着不可评价，不意味着经济 NO_FINALIST。2023–2025是已暴露探索窗口；2026继续锁定。\n'
 for name,payload in (('TASK_RECORD.json',task),('TASK_RECORD.md',record_md),('METHOD_COVERAGE_REPORT.json',report),('METHOD_COVERAGE_REPORT.md','\n'.join(lines)+'\n'),('FINITE_BUDGET_AUDIT.json',budget)):_write(out/name,payload)
 return dict(status=task['status'],results_directory=str(out),outputs={name:str(out/name) for name in ('TASK_RECORD.json','TASK_RECORD.md','METHOD_COVERAGE_REPORT.json','METHOD_COVERAGE_REPORT.md','FINITE_BUDGET_AUDIT.json')},test_2026_rows_read=0,economic_values_read=0)



def build_continuation_report(run):
 """Same streaming metadata reporter; no economic body is opened."""
 run=Path(run).resolve()
 mode=read_metadata(run,run/'run_config.json',{'execution_continuation':{'qualification_only':ALL,'namespace':ALL}})
 if mode.get('execution_continuation',{}).get('namespace')=='A_SOURCE_ACCOUNT_R5':return build_r5_baseline_to37_report(run)
 if mode.get('execution_continuation',{}).get('qualification_only') is True:return build_source_account_qualification_report(run)
 paths=resolve_storage_paths();run=Path(run).resolve()
 if not run.is_relative_to(paths.backtest_root.resolve()):raise ValueError('CONTINUATION_REPORT_RUN_PATH')
 cfg=read_metadata(run,'run_config.json',ALL);auth=cfg.get('execution_continuation',{})
 if cfg.get('phase')!='FROZEN' or auth.get('status')!='FROZEN' or not auth.get('reuse_only'):raise ValueError('CONTINUATION_REPORT_FREEZE_REQUIRED')
 if cfg.get('training_cutoff_exclusive')!='2026-01-01' or cfg.get('evaluation_years')!=list(YEARS):raise ValueError('CONTINUATION_REPORT_TIME_BOUNDARY')
 out=Path(cfg['outputs']['reports']).resolve()
 if not out.is_relative_to(paths.results_root.resolve()) or out.name!='V24':raise ValueError('CONTINUATION_REPORT_PATH')
 candidates=read_metadata(run,auth['candidates_path'],ALL)
 if sha(auth['candidates_path'])!=auth['candidates_sha256']:raise ValueError('CONTINUATION_REPORT_CANDIDATE_PIN')
 events,tail=read_events(run,'ACCOUNT_PATH_LOG.jsonl');fits,fit_tail=read_events(run,'FIT_LOG.jsonl')
 starts=[e for e in events if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED'];ids={e['candidate_id'] for e in starts}
 if len(ids)!=len(starts) or len({e['scientific_tuple_sha256'] for e in starts})!=len(starts):raise ValueError('CONTINUATION_REPORT_DUPLICATE_SCIENCE')
 ends={e['candidate_id']:e for e in events if e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED')}
 pending=ids-set(ends);newfits=sum(e.get('fit_units',0) for e in fits if e.get('event')=='FIT_STARTED')
 if newfits or len(starts)>auth['max_new_account_paths']:raise ValueError('CONTINUATION_REPORT_REUSE_OR_BUDGET_VIOLATION')
 accounts={};audits={}
 schema={**AUDIT,'artifacts':{'*':{k:ALL for k in ('path','sha256','rows','schema')}}}
 for c in candidates:
  cid=c['candidate_id'];e=ends.get(cid)
  if e and e.get('event')=='ACCOUNT_PATH_COMPLETE':
   ap=e['audit_path']
   if sha(ap)!=e['audit_sha256']:raise ValueError('CONTINUATION_REPORT_AUDIT_PIN')
   if ap not in audits:audits[ap]=read_metadata(run,ap,schema)
   a=audits[ap];annual=a.get('selection_eligibility',{}).get(cid,{})
   good=(set(annual)=={'2023','2024','2025'} and a.get('calendar_sessions')==752 and all(v.get('sessions',0)>0 and all(v.get(k) is True for k in ('accounting_qualified_all','certified_nav_positive_and_finite_all','net_return_finite_except_initial')) for v in annual.values()))
   accounts[cid]=dict(state='QUALIFIED_ACCOUNT_METADATA' if good else 'NOT_TESTABLE',annual=annual,audit_path=ap,audit_sha256=e['audit_sha256'],audit_status=a.get('status'))
  elif e:accounts[cid]=dict(state='FAILED_ATTEMPT_RETAINED',failure=e.get('failure'))
  elif cid in ids:accounts[cid]=dict(state='IN_PROGRESS')
  else:accounts[cid]=dict(state='NOT_EXECUTED',reason='CONDITIONAL_SCHEDULE_NOT_ACTIVATED')
 bid=auth['baseline_candidate_id'];baseline=accounts[bid];diagnostic=set(auth['diagnostic_candidate_ids'])
 required={c['candidate_id'] for c in candidates} if baseline['state']=='QUALIFIED_ACCOUNT_METADATA' else diagnostic if baseline['state'] in ('NOT_TESTABLE','FAILED_ATTEMPT_RETAINED') else {bid}
 complete=not (pending or tail or fit_tail) and required.issubset(ends)
 for cid,v in accounts.items():
  if complete and v['state']=='NOT_EXECUTED':v['reason']='NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED'
 status=('NOT_TESTABLE' if baseline['state']!='QUALIFIED_ACCOUNT_METADATA' else 'PENDING_ECONOMIC_SELECTION') if complete else 'IN_PROGRESS'
 counts=dict(Counter(v['state'] for v in accounts.values()))
 budget=dict(status='WITHIN_FIXED_LIMITS',new_fit_units=newfits,new_account_attempts=len(starts),scheduled_new_candidates=len(candidates),diagnostic_candidates=len(diagnostic),new_fit_ceiling=auth['max_new_fit_units'],new_account_ceiling=auth['max_new_account_paths'],prior_cumulative_fit_units=cfg['prior_cumulative_fit_units'],prior_account_paths=cfg['prior_account_paths'],cumulative_fit_units=cfg['prior_cumulative_fit_units']+newfits,cumulative_account_attempts=cfg['prior_account_paths']+len(starts),ceilings_are_not_spending_targets=True)
 task=dict(task=cfg['strategy_id'],run_id=cfg['run_id'],status=status,finite_execution_complete=complete,baseline_candidate_id=bid,baseline=baseline,accounts=accounts,account_state_counts=counts,budget=budget,report_created_utc=datetime.now(timezone.utc).isoformat(),source_sha256=sha(__file__),selection_performed=False,finalist_status='NOT_TESTABLE_REQUIRED_BASELINE' if status=='NOT_TESTABLE' else 'NOT_SELECTED',economic_NO_FINALIST_inferred=False,economic_values_read=0,test_2026_rows_read=0,test_access='LOCKED',read_2027=False,research_only=True,official_adoption_allowed=False,broker_action_allowed=False,artifacts_metadata={k:v.get('artifacts',{}) for k,v in audits.items()},parent_run=cfg['parent_run_dir'])
 coverage=dict(status='METADATA_COVERAGE_COMPLETE' if complete else 'IN_PROGRESS',current_target_value_models=['ridge','hgb'],new_value_fits=0,value_fit_reuse='MATCHED_PARENT_V24_TARGET_FOLD_CALIBRATION_SOURCE',risk_methods_declared=sorted({c['risk'] for c in candidates if c['risk']!='diag20_reference'}),risk_consumer_states={c['candidate_id']:accounts[c['candidate_id']]['state'] for c in candidates if c['risk']!='diag20_reference'},source_bank_ref=str(run/'contracts/RISK_BANK_REUSE_INVENTORY.json'),zero_cost_prior_reference=str(run/'contracts/ZERO_COST_PRIOR_REFERENCE_METADATA.json'),prior_failures_preserved=True,candidate_states=accounts,corporate_event_state='C_SIDE_INVENTORY_ONLY;NOT_ACTIVE_IN_A',source_sha256=sha(__file__))
 lines=['# V24 A Stateful：成本与风险续训报告','',
  '**结论：'+status+'。** '+('已完成本轮激活的有限执行范围。' if complete else '实际执行仍在进行。')+' 必需基准未合格时，不挑经济赢家、不解锁2026，也不推断经济NO_FINALIST。','',
  '## 目标、增量与实际训练','',
  'A冻结Raw A2选股，只研究各自HOLD/SELL/REPLACE、交易控制及独立Gross/Cash。当前创新是PTO基础上用户提供的非机器学习方法包，尤其风险和执行摩擦；完整相对q优化属于B，Selector属于C。','',
  'R1已完成201项年度模型尝试，累计455 FIT、74旧账户尝试，失败保留。R2新增FIT='+str(newfits)+'，复用为当前5交易日shareholder目标训练的Ridge/HGB年度预测，不把旧目标模型冒充当前目标。动作和Gross是预声明规则消费者，并未新训练直接动作头或现金头。','',
  '## 信息边界与账户','',
  '训练/开发严格早于2026-01-01；连续账户从2023-01-03到2025-12-31，共752交易日、USD3000、fractional、long-only、跨年不重置。2023–25已暴露，属于探索性开发，不能称独立留出集。每年模型、预处理、校准按原折的训练标签成熟和60交易日校准边界，禁止未来标签。2026锁定；没有读取2027。信号为纽约16:00已完成的价量及过去已拟合对象，下一真实Open只用于执行。','',
  '## 执行摩擦与成本感知','',
  '主场景单边10bps固定不利Open滑点，5/20bps敏感性，显式费用/现金利息为0。这是研究假设，不是经纪商实证报价或拟合冲击模型。买价Open*(1+s)，卖价Open*(1-s)，实际现金在执行时扣成本一次；Raw benchmark与实际成交价格/金额并列保存，禁止事后NAV再扣一遍。','',
  'blind与aware采用相同真实执行成本。aware给现持仓避免卖出成本的优势，对新进入者扣买入成本，因此REPLACE计两腿，KEEP不计增量换仓成本。它是固定一阶每单位动作效用，不能声称不等金额换仓的精确组合利润。原收益预测未改，Gross不会把避免卖出成本的优势当成机会收益。signal-time计划成本是意图估计；quoter不独立认证输入时间资格，不使用未来Open。','',
  '## 风险、控制与有限范围','',
  '12个三年成功风险银行维持原静态63过去日收益、daily covariance×5单位，仅复用；它不等价B的source-backed五日shareholder风险。失败方法保留，不自动用成功模型替换。Volatility targeting与Risk-constrained cash现公式同义，已去重。控制包括固定no-trade-band/hysteresis/partial/minimum-trade；forecast shrink和BL只是固定坐标变换。所有阈值、目标波动、种子与配置保持既定值，无收益驱动调参。','',
  '预声明51个新账户候选，零bps Raw/Ridge/HGB三条等价路径直接引用R1。先执行10bps Raw基准；合格才激活全组，不合格时只完成14条预声明诊断，剩余37条记录条件未执行。80新账户和72新FIT为上限，不是花完指标；本轮计划新FIT0。','',
  '实际新账户尝试='+str(len(starts))+'；累计FIT='+str(budget['cumulative_fit_units'])+'；累计账户尝试='+str(budget['cumulative_account_attempts'])+'。状态计数：'+json.dumps(counts,ensure_ascii=False)+'。','',
  '## 每个候选的实际状态','', '| 候选 | 单边bps | 动作成本 | 控制 / G / 风险 | 状态 |','|---|---:|---|---|---|']
 for c in candidates:lines.append('| '+c['candidate_id']+' | '+str(c['execution_friction']['one_way_bps'])+' | '+c['action_cost_mode']+' | '+c['control']+' / '+c['gross']+' / '+c['risk']+' | '+accounts[c['candidate_id']]['state']+' |')
 lines+=['','## 会计资格与影响','',
  '基准状态='+baseline['state']+'。共享引擎合成PASS不代表真实现金事件证据已绑定。已知PFE事件仍需原始股数/现金单位、历史公告可得时间及实际支付日等权威来源；不能推算cash factor、把除权日当支付日或删除股票/日期来提升资格。基准未合格就不能判定匹配成本经济增量。本报告没有读取indicative NAV、数值预测、收益或协方差来挑赢家。','',
  '## 协作与公司事件旁支','',
  'B独占共享现金权利/执行补丁，A只薄适配，C独占早年风险缺口；SA使用共享季度适用名单修复，不重建13F。Corporate Event State只由C做结构化历史事件及可得时间/修订/类型的轻量来源盘点，未激活A特征或额外账户，没有新闻NLP、LLM情绪、embedding、人工新闻规则或2026 KDK案例规则。','',
  '## 产物、复核与后续条件','',
  '本run：'+str(run),'','模型/预测/完整连续账户ledger进入backtest_root；报告进入results_root；验证临时产物进入cache_root。每次尝试有唯一科学tuple、START/COMPLETE/FAILED日志与输出hash。持仓units、age/entry、现金、fills/orders、动作、风险/G与跨年continuation已按实际产生情况保存；旧源码字节、旧冻结、失败保留。','',
  '本轮TASK_RECORD.json、FINITE_BUDGET_AUDIT.json、METHOD_COVERAGE_REPORT.json均在 '+str(out)+'。完整R1训练报告位于 D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/V24/TRAINING_ROUTE_REPORT.md。','',
  '最小解锁条件：B提供带来源指纹、原股数坐标、金额币种、历史可得时间及实际支付日的完整公司现金事件绑定，然后以新显式身份进行有限资格验证，不改旧结论。当前结果保持研究用途，不交易、不正式采用。','']
 for name,payload in [('TASK_RECORD.json',task),('FINITE_BUDGET_AUDIT.json',budget),('METHOD_COVERAGE_REPORT.json',coverage),('TRAINING_ROUTE_REPORT.md','\n'.join(lines)+'\n')]:_write(out/name,payload)
 return dict(status=status,finite_execution_complete=complete,results_directory=str(out),outputs={n:str(out/n) for n in ('TASK_RECORD.json','FINITE_BUDGET_AUDIT.json','METHOD_COVERAGE_REPORT.json','TRAINING_ROUTE_REPORT.md')},test_2026_rows_read=0,economic_values_read=0)


def build_source_account_qualification_report(run):
 from scripts.research.a2.training.stateful_execution import continuation_contract,continuation_budget,_continuation_events
 run,cfg,auth,candidates=continuation_contract(run)
 budget=continuation_budget(run,cfg,auth,candidates)
 complete=[e for e in _continuation_events(run,'ACCOUNT_PATH_LOG.jsonl') if e.get('event')=='ACCOUNT_PATH_COMPLETE']
 checks={}
 if complete:
  item=complete[0];p=_own(run,item['audit_path'])
  if sha(p)!=item['audit_sha256']:raise ValueError('SOURCE_ACCOUNT_REPORT_AUDIT_CHANGED')
  checks=read_metadata(run,p,{'qualification_checks':ALL,'source_account_binding':ALL})
 if 'source_account_binding' in checks:checks['actual_source_execution_projection']=checks.pop('source_account_binding')
 status=checks.get('qualification_checks',{}).get('status','FAILED_ACCOUNT_ATTEMPT_RETAINED')
 cfg_full=read_metadata(run,run/'run_config.json',{'outputs':{'reports':ALL}})
 out=Path(cfg_full['outputs']['reports']).resolve();assert_write_path(out/'TASK_RECORD.json','report')
 task=dict(status=status,run_dir=str(run),finite_execution_complete=budget['outstanding']==0 and budget['new_account_path_attempts']==1,
  budget=budget,**checks,selection_performed=False,candidate_37_activated=False,test_2026_rows_read=0,read_2027=False,
  role='RAW_BASELINE_SOURCE_ACCOUNT_QUALIFICATION_ONLY',source_account_binding=auth['source_account_binding'])
 _write(out/'TASK_RECORD.json',task)
 _write(out/'BASELINE_QUALIFICATION.json',task)
 q=checks.get('qualification_checks',{})
 lines=['# V24 A Raw baseline 来源和账户资格报告','',
  '只回放一个主 10bps Raw baseline。旧 R2 保留。没有新增拟合，没有启动 37 条候选。','',
  '结果：'+status+'。这不是收益比较，也不是赢家结论。','',
  '| 检查 | 结果 |','| --- | --- |']
 for key in ('accounting_qualified','quote_qualified','certified_NAV_all_window_finite','cash_identity_correct','entitlement_identity_correct','full_window_752_sessions'):
  lines.append('| '+key+' | '+str(q.get(key,'NOT_VERIFIED'))+' |')
 lines+=['','公告毛额 SOURCE_DECLARED_GROSS。vendor 数值冲突保留，实付未认证。原事件日 quote 域保持不变。',
  '原 5D target、训练行、features、cutoff 和 label maturity 保持原冻结。未补现金缺口标签，现有模型继续复用。','',
  'stale 持仓行='+str(q.get('stale_holding_rows','UNKNOWN'))+'；unknown 持仓行='+str(q.get('unknown_holding_rows','UNKNOWN'))+'；实际公司行动异常='+str(q.get('actual_CA_exception_rows','UNKNOWN'))+'。',
  '完整缺口键、source/catalogue/security/quote/execution 绑定及预算见 BASELINE_QUALIFICATION.json。','',
  'run：'+str(run),'',
  '资格未通过时，保留失败和全窗口。不得放宽 quote 域、删除股票/日期、推算 vendor cash 或启动候选。2026 仍锁定。']
 _write(out/'REPORT.md','\n'.join(lines)+'\n')
 return dict(status=status,finite_execution_complete=task['finite_execution_complete'],results_directory=str(out),report_path=str(out/'REPORT.md'),task_record_path=str(out/'TASK_RECORD.json'))


def build_r5_baseline_to37_report(run):
 from scripts.research.a2.training.stateful_execution import (
  continuation_contract,continuation_budget,_continuation_events,r5_baseline_gate,r5_source_decision)
 run,cfg,auth,candidates=continuation_contract(run);budget=continuation_budget(run,cfg,auth,candidates)
 gate=r5_baseline_gate(run,auth,auth['baseline_candidate_id'])
 events=_continuation_events(run,'ACCOUNT_PATH_LOG.jsonl')
 starts=[e for e in events if e.get('event')=='ACCOUNT_PATH_ATTEMPT_STARTED']
 ends={e['candidate_id']:e for e in events if e.get('event') in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED')}
 expected={c['candidate_id'] for c in candidates} if gate['all_passed'] else {auth['baseline_candidate_id']}
 finished=(budget['outstanding']==0 and expected.issubset(ends))
 if not gate['all_passed'] and any(e['candidate_id']!=auth['baseline_candidate_id'] for e in starts):
  raise ValueError('R5_CONDITIONAL_ACCOUNT_WITHOUT_QUALIFIED_BASELINE')
 accounts={}
 for item in candidates:
  cid=item['candidate_id'];e=ends.get(cid)
  if e:
   attempt_state='FAILED_ATTEMPT_RETAINED' if e['event']=='ACCOUNT_PATH_FAILED' else 'COMPLETE_ATTEMPT_NOT_AUTOMATIC_QUALIFICATION'
   state='NOT_TESTABLE' if cid==auth['baseline_candidate_id'] and not gate['all_passed'] else attempt_state
  else:
   attempt_state='NOT_EXECUTED'
   state='NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED' if finished else 'NOT_EXECUTED'
  accounts[cid]=dict(state=state,attempt_state=attempt_state,scientific_tuple_sha256=item['scientific_tuple_sha256'])
 status=('PENDING_PRE2026_COMPARISON' if gate['all_passed'] else 'NOT_TESTABLE') if finished else 'IN_PROGRESS'
 view=read_metadata(run,run/'run_config.json',{'outputs':{'reports':ALL},'run_id':ALL,'research_id':ALL})
 out=Path(view['outputs']['reports']).resolve();paths=resolve_storage_paths()
 if not out.is_relative_to(paths.results_root.resolve()) or out.name!='V24':raise ValueError('R5_REPORT_PATH')
 source=r5_source_decision(auth,verify_refs=False)
 task=dict(status=status,role='RAW_BASELINE_THEN_FROZEN37_SOURCE_ACCOUNT_R5',run_dir=str(run),
  run_id=view.get('run_id'),research_id=view.get('research_id'),finite_execution_complete=finished,
  source_decision=source,baseline_candidate_id=auth['baseline_candidate_id'],baseline_gate=gate,
  accounts=accounts,budget=budget,candidate_37_activated=gate['all_passed'],
  actual_conditional_attempts=sum(e['candidate_id']!=auth['baseline_candidate_id'] for e in starts),
  selection_performed=False,economic_NO_FINALIST_inferred=False,economic_values_read=0,
  test_2026_rows_read=0,read_2027=False,research_only=True,official_adoption_allowed=False,broker_action_allowed=False)
 lines=['# V24 A R5 来源与账户资格收尾','',
  '状态：'+status+'。完整R5身份和来源决策按本run冻结。这里只读取资格元数据。','',
  '基准七组全部为真才立即执行原冻结37项。任一不通过，只保留基准尝试。','',
  '来源分支：'+source['branch_id']+'；资格声明：'+source['qualification_claim']+'。','',
  '| 七组 | 结果 |','| --- | --- |']
 lines += ['| '+k+' | '+str(v)+' |' for k,v in gate['groups'].items()]
 lines += ['','累计FIT='+str(budget['cumulative_fit_units'])+'；新FIT=0；新账户尝试='+
  str(budget['new_account_path_attempts'])+'；累计账户尝试='+str(budget['account_path_attempts_cumulative'])+'。',
  'COMPLETE不是资格PASS。失败保留。NOT_TESTABLE不是经济NO_FINALIST。2026仍锁定。',
  'Branch N为明确研究来源政策，不能声称严格历史PIT。','']
 coverage=dict(candidate_states=accounts,source_decision=source,baseline_gate=gate,
  frozen37_reference=auth['frozen37_reference'],old_failures_preserved=True,source_only_report=False)
 for name,data in (('TASK_RECORD.json',task),('FINITE_BUDGET_AUDIT.json',budget),
                   ('METHOD_COVERAGE_REPORT.json',coverage),('TRAINING_ROUTE_REPORT.md','\n'.join(lines))):
  _write(out/name,data)
 return dict(status=status,finite_execution_complete=finished,results_directory=str(out),
  outputs={n:str(out/n) for n in ('TASK_RECORD.json','FINITE_BUDGET_AUDIT.json',
           'METHOD_COVERAGE_REPORT.json','TRAINING_ROUTE_REPORT.md')},economic_values_read=0,test_2026_rows_read=0)



def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args(argv)
 print(json.dumps(build_report(args.run_dir),ensure_ascii=False,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
