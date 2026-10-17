"""Final action account-consumer child of the unique stateful controller.
No estimator fitting, feature reconstruction, accounting or execution algorithm.
Existing causal publications supply actions; the existing RAW policy owns q/budget.
"""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training import stateful_research_account as research
from scripts.research.a2.training.stateful_account import StatefulOverlay
from scripts.research.a2.training.stateful_decision import _valid_sid
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

TASK='V24_A_FINAL_ACTION_COVERAGE_AND_STATEFUL_DECISION_R1'
BOUNDARY=pd.Timestamp('2026-01-01')


def require(condition, code):
    if not condition: raise ValueError(code)


def read_ref(ref):
    p=Path(ref['path']).resolve()
    require(replay.sha(p)==ref['sha256'], 'FINAL_ACTION_REF_CHANGED:'+str(p))
    return json.loads(p.read_text(encoding='utf-8-sig'))


def write_report(path, payload):
    path=Path(path).resolve(); roots=resolve(replay.REPO)
    require(path.is_relative_to(roots.results_root.resolve()/ '_maintenance'/TASK), 'FINAL_REPORT_ROUTING')
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,default=str,allow_nan=False)+'\n'
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(text,encoding='utf-8');temp.replace(path)


class _MaskView:
    def __init__(self,context,mask): self.context=context;self.decision_mask=mask
    def __getattr__(self,name): return getattr(self.context,name)


class FinalActionOverlay:
    """Thin action-to-target encoding; RAW q and resource constraints are retained.
    True HOLD is exact units. SKIP leaves the slot in cash, with no re-ranking.
    Frozen publications' proxy state is never replaced with actual holding age.
    """
    def __init__(self,candidates,packets,top,qualified,vol,*,risk_provider=None,
                 action_packets=None,resource_decoder=None,sid_by_key=None,descriptive_evaluation_authority=None):
        self.candidates=candidates;self.top=top;self.qualified=qualified
        self.descriptive_evaluation_authority=descriptive_evaluation_authority
        self.raw=StatefulOverlay(candidates,packets,top,qualified,vol,risk_provider=risk_provider,descriptive_evaluation_authority=descriptive_evaluation_authority)
        self.action_packets=action_packets or {}; self.resource_decoder=resource_decoder
        self.sid_by_key=sid_by_key;self.audit=[];self.action_audit=[]

    def __call__(self,di,ctx):
        date=pd.Timestamp(ctx.signal_date)
        if self.descriptive_evaluation_authority is not None:
            from scripts.research.a2.evaluation.frozen_test_authority import require_descriptive_decision
            for candidate in self.candidates:
                require_descriptive_decision(self.descriptive_evaluation_authority,date,path_id=candidate['candidate_id'])
        elif date>=BOUNDARY:
            raise ValueError('FINAL_ACTION_2026_LOCKED')
        hold_mask=ctx.decision_mask.copy(); decisions=[]
        ti={str(t):j for j,t in enumerate(ctx.tickers)}
        for row,c in enumerate(self.candidates):
            held=set(str(ctx.tickers[j]) for j in np.flatnonzero(ctx.current_units[row]>1e-10))
            allowed=set(str(ctx.tickers[j]) for j in np.flatnonzero(self.top[di]&self.qualified[di]&ctx.buy_allowed[row]&ctx.decision_mask[row]))
            records=[] if date.year==2023 else self.action_packets.get(c['candidate_id'],{}).get(date,[])
            # Identity support is checked against the original input SID, never a
            # current ticker alias or an inferred account age.
            legal=[]
            for record in records:
                r=dict(record); ticker=str(r.get('ticker',''))
                if ticker not in ti or not ctx.decision_mask[row,ti[ticker]]:continue
                if self.sid_by_key is not None:
                    sid=self.sid_by_key.get((date,ticker))
                    if not _valid_sid(sid) or not _valid_sid(r.get('security_id')) or str(r.get('security_id'))!=str(sid):continue
                    entrant=r.get('entrant')
                    if entrant and (not _valid_sid(r.get('entrant_security_id')) or not _valid_sid(self.sid_by_key.get((date,str(entrant)))) or str(r['entrant_security_id'])!=str(self.sid_by_key[(date,str(entrant))])):continue
                legal.append(r)
            if self.resource_decoder is None:
                require(not legal,'FINAL_ACTION_RESOURCE_DECODER_REQUIRED')
                result={'accepted':[],'conflicts':[]}
            else: result=self.resource_decoder(legal,held=held,allowed=allowed)
            selected=result['accepted'];decisions.append(selected)
            for r in selected:
                if r.get('kind')=='HOLD' and str(r['ticker']) in held:
                    hold_mask[row,ti[str(r['ticker'])]]=False
            for r in result.get('conflicts',[]):
                self.action_audit.append(dict(path_id=c['candidate_id'],signal_date=date,consumer_status='RESOURCE_CONFLICT_REFERENCE',**r))
        raw=self.raw(di,_MaskView(ctx,hold_mask));w=raw.weights.copy();m=raw.explicit_mask.copy()
        for row,(c,selected) in enumerate(zip(self.candidates,decisions)):
            held=ctx.current_units[row]>1e-10
            for r in selected:
                j=ti[str(r['ticker'])];kind=r.get('kind');decision=r.get('decision',kind)
                applied=False
                if decision=='SKIP' and not held[j]:w[row,j]=0.;m[row,j]=False;applied=True
                elif kind=='HOLD' and held[j]:w[row,j]=0.;m[row,j]=False;applied=True
                elif kind=='SELL' and held[j]:w[row,j]=0.;m[row,j]=True;applied=True
                elif kind=='BUY' and not held[j] and self.top[di,j] and ctx.buy_allowed[row,j]:
                    # Preserve the exact reference target; no redistribution of skipped slots.
                    applied=True
                elif kind=='REPLACE':
                    e=ti.get(str(r.get('entrant')))
                    if e is not None and held[j] and not held[e] and self.top[di,e] and ctx.buy_allowed[row,e]:
                        w[row,j]=0.;m[row,j]=True;applied=True
                        # The entrant receives its original RAW equal-weight slot.
                        # A held non-top20 incumbent has no artificial extra budget.
                self.action_audit.append(dict(path_id=c['candidate_id'],signal_date=date,consumer_status='APPLIED' if applied else 'REFERENCE_UNAVAILABLE',**r))
        self.audit=self.raw.audit
        return TargetDecision(w,explicit_mask=m,raw_evidence_id='FROZEN_EXISTING_ACTION_PUBLICATION')


def contract(run):
    run=Path(run).resolve();assert_write_path(run,'backtest')
    cfg=json.loads((run/'run_config.json').read_text(encoding='utf-8'))
    require(cfg.get('final_action_namespace')==TASK,'FINAL_ACTION_EXACT_NAMESPACE')
    manifest=read_ref(cfg['coverage_manifest_ref'])
    require(manifest.get('status')=='FROZEN_PRE_OUTCOME' and manifest.get('phase0_frozen') is True,'FINAL_ACTION_PHASE0_REQUIRED')
    require(manifest.get('real_fit_budget')==0 and manifest.get('2026_locked') is True,'FINAL_ACTION_NO_FIT_LOCK')
    cfg.pop('_engineering_quote_domain_ref',None)  # Never accept an unverified caller override.
    cfg.pop('_engineering_session_convention_ref',None)
    from scripts.maintenance import research_registry as registry
    admission=registry.verify_a_final_action_admission(resolve(replay.REPO).results_root/'US_TECH_QUANT_RESEARCH_REGISTRY', final_action_manifest_ref=cfg['coverage_manifest_ref'])
    if admission.get('engineering_run_dir') is not None:
        require(Path(admission['engineering_run_dir']).resolve()==run,'FINAL_ACTION_ENGINEERING_EXACT_RUN')
    for ref in admission.get('effective_source_pins',manifest['source_pins']):
        require(replay.sha(ref['path'])==ref['sha256'],'FINAL_ACTION_SOURCE_CHANGED:'+ref['path'])
    if admission.get('quote_domain_ref') is not None:
        cfg['_engineering_quote_domain_ref']=admission['quote_domain_ref']
    if admission.get('session_convention_ref') is not None:
        cfg['_engineering_session_convention_ref']=admission['session_convention_ref']
    require(manifest['reference']['candidate_id']=='RAW_s10','FINAL_ACTION_RAW_REFERENCE_ONLY')
    audit=read_ref(manifest['reference']['audit_ref'])
    gate=audit['research_integrity']['RAW_s10']
    require(gate['all_passed'] is True and set(gate['groups'])==set(research.GATES) and all(v is True for v in gate['groups'].values()),'FINAL_ACTION_REFERENCE_TEN_LITERAL_TRUE')
    require(cfg['new_fit_units']==0 and cfg['scientific_retry']==0 and cfg['max_new_account_paths']==len(manifest['candidates']),'FINAL_ACTION_EXACT_BUDGET')
    parent=read_ref(manifest['reference']['config_ref'])
    require(parent['research_account']['namespace']==research.SESSION_NAMESPACE,'FINAL_ACTION_SESSION_REFERENCE')
    return run,cfg,manifest,parent


def history(run,candidates):
    events=replay._events(Path(run)/'ACCOUNT_PATH_LOG.jsonl')
    ids=[c['candidate_id'] for c in candidates]; seen=[];terminal={}
    for e in events:
        cid=e['candidate_id'];require(cid in ids,'FINAL_ACTION_UNKNOWN_ATTEMPT')
        if e['event']=='ACCOUNT_PATH_ATTEMPT_STARTED':require(cid not in seen,'FINAL_ACTION_DUPLICATE_ATTEMPT');seen.append(cid)
        elif e['event'] in ('ACCOUNT_PATH_COMPLETE','ACCOUNT_PATH_FAILED'):
            require(cid in seen and cid not in terminal,'FINAL_ACTION_DUPLICATE_TERMINAL');terminal[cid]=e
    require(seen==ids[:len(seen)],'FINAL_ACTION_EXACT_FROZEN_ORDER')
    require(len(seen)<=len(ids),'FINAL_ACTION_BUDGET_EXCEEDED')
    return dict(events=events,started=seen,terminal=terminal,outstanding=[cid for cid in seen if cid not in terminal])


def run_owned(run):
    from scripts.research.a2.training import stateful_execution as owner
    from scripts.research.a2.training import stateful_final_action_packets as packets_module
    run,cfg,manifest,parent=contract(run)
    status_path=run/'EXECUTION_STATUS.json'
    with owner.continuation_lock(run,replay.sha(Path(owner.__file__)),namespace=TASK):
        prior=history(run,manifest['candidates']);require(not prior['outstanding'],'FINAL_ACTION_OUTSTANDING_NO_SCIENTIFIC_RETRY')
        owner.configure_environment(dict(cache_directory=str(resolve(replay.REPO).cache_root/'V24')))
        write_json_atomic(status_path,dict(status='RUNNING',stage='FROZEN_PUBLICATION_CONSUMPTION',real_fit=0,new_account_paths=len(prior['started']),**{'2026_locked':True}))
        reader=replay._read_parent_inputs_readonly(Path(parent['parent_run_dir']))
        market,top,qualified,vol,stock,raw=replay.read_market(reader)
        auth=dict(parent['research_account']);old=replay._old()
        if cfg.get('_engineering_quote_domain_ref') is not None:
            auth['quote_domain_ref']=cfg['_engineering_quote_domain_ref']
        if cfg.get('_engineering_session_convention_ref') is not None:
            auth['research_ca_accounting_convention']=cfg['_engineering_session_convention_ref']
        events,known,unsupported,_=old.frozen_events(replay._json(replay.PARENT/'INPUT_BINDING_R1.json'))
        before=research._decision_digest(market,(top,qualified,vol,stock,raw))
        market,unsupported,kwargs,binding=research.bound_inputs(auth,market,events,unsupported)
        require(before==research._decision_digest(market,(top,qualified,vol,stock,raw)),'FINAL_ACTION_DECISION_MUTATION')
        raw_candidate=manifest['reference']['raw_candidate'];model=raw_candidate['value_model']
        worker_auth={**auth,**auth.get('replay_source_pins',{})};worker_auth.update({k:replay.sha(p) for k,p in replay.SOURCE_PATHS.items()})
        worker_auth['input_manifest_sha256']=replay.sha(Path(parent['parent_run_dir'])/'input_manifest.json')
        packet=replay.read_packet(auth['value_packets'][model],reader,market.dates,market.tickers,auth=worker_auth)
        packet['mu']=np.where(stock,packet['mu'],np.nan)
        bundles=packets_module.load_packets(manifest['census_ref'],market.dates,market.tickers,authorization_ref=cfg['coverage_manifest_ref'])
        sid={(pd.Timestamp(r.signal_date),str(r.ticker)):r.security_id for r in reader.pred_flags[['signal_date','ticker','security_id']].itertuples(index=False)}
        account=old.config_adapter(replay._json(replay.PARENT/'R1_ACCOUNT_CONFIG.json'))
        for index,c in enumerate(manifest['candidates']):
            if c['candidate_id'] in prior['started']:continue
            contract(run)
            cid=c['candidate_id'];folder=run/'ledgers/stateful'/('attempt_%04d'%(index+1));require(not folder.exists(),'FINAL_ACTION_OUTPUT_ALREADY_EXISTS');folder.mkdir(parents=True)
            replay._append(run/'ACCOUNT_PATH_LOG.jsonl',dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id=cid,scientific_tuple_sha256=c['scientific_tuple_sha256'],path_units=1,namespace=TASK))
            try:
                holder={}
                def factory(*args,**kw):
                    holder['overlay']=FinalActionOverlay(*args,**kw,action_packets=bundles['packets'],resource_decoder=packets_module.decode_resource_proposals,sid_by_key=sid)
                    return holder['overlay']
                result,frames=replay.execute_market(market,[c],{model:packet},top,qualified,vol,account,stock_present=stock,raw_selector_present=raw,events=events,known_at=known,unsupported=unsupported,execution_friction=c['execution_friction'],policy_factory=factory,**kwargs)
                contract(run)  # Reverify source/manifest custody after the shared engine returns.
                frames['daily']=research.add_dual_nav(result)
                frames['learned_action_decisions']=pd.DataFrame(holder['overlay'].action_audit)
                gate=research.integrity_gates(result,cid,binding,decision_unchanged=before==research._decision_digest(market,(top,qualified,vol,stock,raw)),custody_verified=True,market=market)
                records={name:research._artifact(folder,name,frame) for name,frame in frames.items()}
                audit=dict(status='COMPLETE',candidate_id=cid,scientific_tuple_sha256=c['scientific_tuple_sha256'],research_integrity=gate,artifacts=records,reference='RAW_s10',real_fit=0,test_2026_rows_read=0,production_qualified=False,strict_PIT_promotion_eligible=False,packet_diagnostics=bundles.get('diagnostics'),MKFG_settlement_assumption_added=False)
                write_json_atomic(folder/'audit.json',audit)
                replay._append(run/'ACCOUNT_PATH_LOG.jsonl',dict(event='ACCOUNT_PATH_COMPLETE',candidate_id=cid,audit_path=str(folder/'audit.json'),audit_sha256=replay.sha(folder/'audit.json'),qualified=gate['all_passed']))
            except Exception as exc:
                failure=dict(status='FAILED_ENGINEERING_OR_QUALIFICATION',candidate_id=cid,error_type=type(exc).__name__,error=str(exc),scientific_retry=0,real_fit=0)
                write_json_atomic(folder/'audit.json',failure)
                replay._append(run/'ACCOUNT_PATH_LOG.jsonl',dict(event='ACCOUNT_PATH_FAILED',candidate_id=cid,audit_path=str(folder/'audit.json'),audit_sha256=replay.sha(folder/'audit.json')))
            snapshot=history(run,manifest['candidates'])
            write_json_atomic(status_path,dict(status='RUNNING',stage='FROZEN_ACTION_ACCOUNTS',new_account_paths=len(snapshot['started']),completed=sum(v['event']=='ACCOUNT_PATH_COMPLETE' for v in snapshot['terminal'].values()),failed=sum(v['event']=='ACCOUNT_PATH_FAILED' for v in snapshot['terminal'].values()),real_fit=0,test_2026_rows_read=0,last_candidate=cid))
            print(json.dumps(dict(candidate_id=cid,status=snapshot['terminal'][cid]['event']),ensure_ascii=False),flush=True)
        report=build_report(run)
        write_json_atomic(status_path,dict(status='COMPLETED',stage='FINAL_ACTION_REPORT',report=report,real_fit=0,test_2026_rows_read=0,new_account_paths=len(manifest['candidates'])))
        return dict(status='COMPLETED',stage='FINAL_ACTION_REPORT',report=report,real_fit=0,test_2026_rows_read=0)


def build_report(run):
    # Defined below; the canonical metrics/evaluator are reused unchanged.
    return _build_report(run)


def _frames(audit,root,names=None):
    result={}
    for name,ref in audit['artifacts'].items():
        if names is not None and name not in names:continue
        path=Path(ref['path']).resolve()
        require(path.is_relative_to(root) and replay.sha(path)==ref['sha256'],'FINAL_ACTION_OUTPUT_CUSTODY')
        require(ref.get('test_2026_rows_read')==0 and all(research._clock_before_boundary(v['max']) for v in ref['clock_bounds'].values()),'FINAL_ACTION_OUTPUT_TIME_BOUNDARY')
        result[name]=pd.read_parquet(path)
    return result


def _full_metrics(c,frames):
    cid=c['candidate_id'];positions=frames['positions']
    local=dict(frames)
    # Existing evaluator expects this column even for a path with zero holdings.
    if 'holding_age' not in positions and positions.empty:
        local['positions']=positions.assign(holding_age=pd.Series(dtype=float))
    metrics=research.path_metrics(c,local)
    d=frames['daily'].loc[frames['daily'].path_id.eq(cid)].sort_values('date')
    p=positions.loc[positions.path_id.eq(cid)].copy()
    previous=3000.;annual_dd={}
    for year,g in d.groupby(d.date.dt.year,sort=True):
        nav=g.TOTAL_ECONOMIC_NAV.to_numpy(float)
        annual_dd[str(year)]=float(np.min(nav/np.maximum.accumulate(np.r_[previous,nav])[1:]-1.));previous=float(nav[-1])
    metrics['annual_MaxDD']=annual_dd
    if p.empty:
        maximum=pd.Series(0.,index=d.date);hhi=maximum.copy();counts=maximum.copy()
    else:
        nav=d.set_index('date').TOTAL_ECONOMIC_NAV
        p['realized_weight']=p.market_value/p.date.map(nav)
        maximum=p.groupby('date').realized_weight.max().reindex(d.date,fill_value=0.)
        hhi=p.assign(w2=p.realized_weight**2).groupby('date').w2.sum().reindex(d.date,fill_value=0.)
        counts=p.loc[p.index_units.gt(1e-10)].groupby('date').size().reindex(d.date,fill_value=0.)
    metrics['position_count_distribution']=research._distribution(counts)
    metrics['max_single_name_realized_weight']=float(maximum.max())
    metrics['concentration_HHI_distribution']=research._distribution(hhi)
    learned=frames.get('learned_action_decisions',pd.DataFrame())
    learned=learned.loc[learned.path_id.eq(cid)] if not learned.empty else learned
    applied=learned.loc[learned.consumer_status.eq('APPLIED')] if not learned.empty else learned
    metrics['learned_decision_counts']=dict(Counter(applied['decision'])) if not applied.empty else {}
    metrics['learned_kind_counts']=dict(Counter(applied['kind'])) if not applied.empty else {}
    metrics['learned_resource_conflicts']=int(learned.consumer_status.eq('RESOURCE_CONFLICT_REFERENCE').sum()) if not learned.empty else 0
    pairs=applied.loc[applied.kind.eq('REPLACE')] if not applied.empty else applied
    completed=0;partial=0
    for r in pairs.itertuples():
        fills=frames['fills'];f=fills.loc[fills.path_id.eq(cid)&fills.signal_date.eq(r.signal_date)]
        sell=f.loc[f.ticker.eq(r.ticker)&f.side.eq('SELL')&f.index_units_after.le(1e-10)]
        buy=f.loc[f.ticker.eq(r.entrant)&f.side.eq('BUY')&f.index_units_before.le(1e-10)]
        completed+=int(len(sell)>0 and len(buy)>0);partial+=int((len(sell)>0)!=(len(buy)>0))
    metrics['REPLACE_count']=len(pairs)
    metrics['REPLACE_identification']='EXACT_FROZEN_PAIR_ID_IN_LEARNED_DECODER;POLICY_DECISION_VS_TWO_LEG_FILL_DISTINGUISHED'
    metrics['REPLACE_executed_full_pair_count']=completed;metrics['REPLACE_one_leg_only_count']=partial
    return metrics


def _adjust_effect(effect,family):
    from scipy.stats import norm
    result=dict(effect);p=result.get('one_sided_p');z=result.get('statistic')
    critical=float(norm.ppf(1.-.05/family))
    result.update(inherited_family=220,Bonferroni_family=family,adjusted_p=min(1.,p*family) if p is not None else None,
                  one_sided_normal_critical=critical,frozen_hypothesis_pass=bool(z>critical) if z is not None else None,
                  family_interpretation='FROZEN_SELECTION_HISTORY_UPPER_BOUND_NOT_INDEPENDENT_TRIAL_COUNT')
    return result


def _build_report(run):
    run,cfg,manifest,parent=contract(run);history_state=history(run,manifest['candidates'])
    require(not history_state['outstanding'] and len(history_state['terminal'])==len(manifest['candidates']),'FINAL_ACTION_REPORT_BEFORE_TERMINAL')
    out=Path(manifest['results_directory']);rows=[];daily_by_id={};gates={}
    # Prior 57 bytes are read only after the action manifest freeze, never used for inclusion.
    prior_root=Path(manifest['reference']['run_dir']).resolve()
    prior_audits=manifest['prior_account_audit_refs']
    old_loaded={};baseline_metrics=None
    for ref in prior_audits:
        audit=read_ref(ref)
        frames=_frames(audit,prior_root,names={'daily'})
        if 'RAW_s10' in audit['candidate_ids']:
            baseline_metrics=research.path_metrics(manifest['reference']['raw_candidate'],_frames(audit,prior_root))
        for cid in audit['candidate_ids']:
            if cid=='RAW_s10' or cid in manifest['statistical_design']['rule_reference_ids']:
                require(audit['research_integrity'][cid]['all_passed'] is True,'FINAL_ACTION_PRIOR_REFERENCE_UNQUALIFIED')
                daily_by_id[cid]=frames['daily'].loc[frames['daily'].path_id.eq(cid)].copy()
    for c in manifest['candidates']:
        cid=c['candidate_id'];event=history_state['terminal'][cid];audit=read_ref(dict(path=event['audit_path'],sha256=event['audit_sha256']))
        if event['event']=='ACCOUNT_PATH_FAILED':
            rows.append(dict(candidate_id=cid,status='NOT_TESTABLE_ACCOUNT_CONSUMER',failure=audit));continue
        gate=audit['research_integrity'];gates[cid]=gate
        if not (gate['all_passed'] is True and set(gate['groups'])==set(research.GATES) and all(v is True for v in gate['groups'].values())):
            rows.append(dict(candidate_id=cid,status='NOT_TESTABLE_ACCOUNT_QUALIFICATION',integrity_gates=gate));continue
        frames=_frames(audit,run);daily_by_id[cid]=frames['daily'].loc[frames['daily'].path_id.eq(cid)].copy()
        rows.append(dict(status='ECONOMICALLY_EVALUATED',asset_status='EXISTING_FROZEN_ASSET',new_fit=0,**_full_metrics(c,frames)))
    comparisons=[];family=manifest['statistical_design']['Bonferroni_family']
    for specification in manifest['statistical_design']['contrasts']:
        cid=specification['candidate'];reference=specification['reference']
        if cid not in daily_by_id or reference not in daily_by_id:
            comparisons.append(dict(specification,status='NOT_TESTABLE_MISSING_QUALIFIED_PATH'));continue
        effect=_adjust_effect(research.paired_effect(daily_by_id[cid],daily_by_id[reference]),family)
        left=research._log_returns(daily_by_id[cid]);right=research._log_returns(daily_by_id[reference]);diff=left-right
        annual={str(y):dict(mean_daily_net_log_difference=float(diff.loc[diff.index.year==y].mean()),cumulative_net_log_difference=float(diff.loc[diff.index.year==y].sum())) for y in (2023,2024,2025)}
        directions=[int(np.sign(annual[str(y)]['cumulative_net_log_difference'])) for y in (2023,2024,2025)]
        active=[directions[1],directions[2]]
        comparisons.append(dict(specification,status='EVALUATED',effect=effect,annual=annual,cross_year_directions=directions,
            trained_years_2024_2025_direction_consistent=bool(active[0]==active[1]),sign_reversal_2024_2025=bool(active[0]*active[1]<0)))
    primary={r['candidate']:r for r in comparisons if r['reference']=='RAW_s10'}
    supported=[]
    for row in rows:
        contrast=primary.get(row['candidate_id']);row['supported_vs_RAW_s10']=bool(contrast and contrast.get('effect',{}).get('frozen_hypothesis_pass') is True)
        row['economic_disposition']='SUPPORTED_STATISTICAL_EFFECT_EXPLORATORY_ONLY' if row['supported_vs_RAW_s10'] else ('NO_SUPPORT' if row['status']=='ECONOMICALLY_EVALUATED' else 'NOT_TESTABLE')
        if row['supported_vs_RAW_s10']:supported.append(row['candidate_id'])
    qualified=[r for r in rows if r['status']=='ECONOMICALLY_EVALUATED']
    coverage=[]
    descriptions=[
        ('Value',True,True,'Existing 29 value-family training bank; prior57 consumption retained'),
        ('Fusion',True,True,'Existing 13 fusion bank; prior frozen fusion account comparisons retained'),
        ('Risk',True,True,'Existing trained risk bank and prior57 risk/Gross comparisons; blocked estimates preserved'),
        ('Rule-based Action',True,True,'All 56 original account mechanisms immutable; 52 same-cost references retained'),
        ('Learned Stateful Action',True,False,'Original R9 three-head Gross feature projection unbound; no invented schema'),
        ('Direct Action',True,any(not r['candidate_id'].startswith('R10_SEQUENCE') for r in qualified),'Existing R6/R10 frozen outputs consumed; original proxy state is not actual account state learning'),
        ('Sequence Action',True,any(r['candidate_id'].startswith('R10_SEQUENCE') for r in qualified),'Original earliest complete TCN/GRU/LSTM L5/MID three-seed assets'),
        ('Uncertainty-aware Action',True,any(r['candidate_id'].startswith('R6_DISTRIBUTION') for r in qualified),'Native tail/width action consumed; no matched point-only account contrast, independent increment not identified'),
        ('Gross/Cash',True,True,'Prior frozen Gross/Cash account policies; learned R7/R9 Gross unavailable, no new q optimizer'),
        ('Cost',True,True,'Prior5/10/20bps preserved; new action accounts10bps only'),
        ('Execution',True,True,'Same next raw Open/fractional/USD3000 continuous engine; research authority only')]
    for dimension,attempted,evaluated,gap in descriptions:
        coverage.append(dict(dimension=dimension,attempted=attempted,account_evaluated=evaluated,supported='NOT_SEPARATELY_IDENTIFIED' if dimension in ('Value','Fusion','Risk','Gross/Cash','Cost','Execution') else ('SEE_FROZEN_PAIRED_COMPARISONS' if evaluated else False),remaining_gap=gap))
    status=('ACTION_COVERAGE_COMPLETE_SUPPORTED' if supported else 'ACTION_COVERAGE_COMPLETE_NO_SUPPORTED_WINNER') if qualified else 'NOT_TESTABLE_ACCOUNT_CONSUMER_OR_QUALIFICATION'
    summary=dict(task_id=TASK,status=status,scope_status='SUFFICIENTLY_EXPLORED_FOR_CURRENT_PRE2026_SCOPE',real_fit=0,
        new_account_paths=len(rows),economically_evaluated=len(qualified),not_testable=len(rows)-len(qualified),
        original_R9='NOT_TESTABLE_CAUSAL_INPUT',R9_blocker='R9_GROSS_FEATURE_PROJECTION_UNBOUND_IN_ORIGINAL_CONTRACT',
        new_counterfactual_label_generations=0,native_uncertainty_action_covered=any(r['candidate_id'].startswith('R6_DISTRIBUTION') for r in qualified),
        native_uncertainty_independent_increment='NOT_IDENTIFIED_NO_MATCHED_POINT_ONLY_ACCOUNT;CASE_A_NO_EXTRA_PAIR',
        supported_vs_RAW_s10=supported,selection_performed=False,finalist='NOT_SELECTED_NO_NEW_SCORING_RULE',
        total_preserved_and_new_account_paths=57+len(rows),test_2026_rows_read=0,EF_access=False,provider_access=False,
        strict_PIT_promotion_eligible=False,production_qualified=False,certified_market_quote_authority=False,
        MKFG_settlement_authority='UNKNOWN',receivable_spendable=False,expansion_stopped=True,
        pre2026_exposed=True,fresh_holdout=False,effective_independent_trials='UNKNOWN',Bonferroni_family=family,
        unresolved_original_assets=[r['representative_id'] for r in read_ref(manifest['census_ref'])['representatives'] if r['classification']=='INCOMPLETE_TRAINING_IDENTITY'])
    write_report(out/'A_FINAL_ACCOUNT_PATH_RESULTS.json',dict(summary=summary,reference_RAW_s10=baseline_metrics,per_path=rows))
    write_report(out/'A_FINAL_PAIRED_COMPARISONS.json',dict(design=manifest['statistical_design'],comparisons=comparisons))
    write_report(out/'A_FINAL_SCIENTIFIC_COVERAGE_MATRIX.json',dict(summary=summary,coverage=coverage))
    write_report(out/'A_FINAL_ACTION_COMPLETION.json',summary)
    lines=['# A 最终 Stateful Action 覆盖报告','',f"状态：{summary['scope_status']}",'',
        f"本次消费 {len(rows)} 个既有动作代表，{len(qualified)} 条通过完整研究账户资格；新增拟合 0，新增反事实标签 0。旧 57 条账户全部保留，未重跑。",'',
        '原 R9 文件可恢复，但 Gross 头没有具体聚合列、算子、pool 和 weights；原三头共同选择契约无法原样执行。结论为 NOT_TESTABLE_CAUSAL_INPUT，不能解释成模型经济失败。','',
        ('原生分位数/分布动作已通过研究账户资格并完成评价。' if summary['native_uncertainty_action_covered'] else '原生分位数/分布动作已尝试消费，但没有合格账户，保留具体资格 blocker。')+'按照本次 case A 停止规则，没有额外增加 uncertainty pair；因此其独立增量没有被匹配点预测对照识别。','',
        '## 本次账户结果','', '|候选|资格|2023|2024|2025|总经济NAV|Liquid NAV|MaxDD|交易数|相对Raw统计支持|','|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    if baseline_metrics:
        r=baseline_metrics;ar=r['annual_return'];lines.append(f"|RAW_s10（既有基准）|PASS|{ar['2023']:.2%}|{ar['2024']:.2%}|{ar['2025']:.2%}|{r['terminal_TOTAL_ECONOMIC_NAV']:.2f}|{r['terminal_LIQUID_NAV']:.2f}|{r['MaxDD']:.2%}|{r['trade_count']}|REFERENCE|")
    for r in rows:
        if r['status']=='ECONOMICALLY_EVALUATED':
            ar=r['annual_return'];lines.append(f"|{r['candidate_id']}|PASS|{ar['2023']:.2%}|{ar['2024']:.2%}|{ar['2025']:.2%}|{r['terminal_TOTAL_ECONOMIC_NAV']:.2f}|{r['terminal_LIQUID_NAV']:.2f}|{r['MaxDD']:.2%}|{r['trade_count']}|{r['supported_vs_RAW_s10']}|")
        else:lines.append(f"|{r['candidate_id']}|{r['status']}|—|—|—|—|—|—|—|NOT_TESTABLE|")
    lines+=['','## 解释边界','',f'统计继承 paired daily net-log、HAC20、Bartlett 权重、one-sided normal 和 alpha .05。冻结历史上界 220 加本次全部 {len(manifest["statistical_design"]["contrasts"])} 个比较，共 {family}，不按成功子集缩减。2024/2025 单年方向和反转逐项列在比较 JSON；统计支持不自动构成 finalist。','',
        '这是已暴露 pre-2026 的冻结历史研究；strict PIT、production 和 certified quote authority 均为 false。MKFG 未知结算日保持未知，应收非可花现金。2026、E/F、网络/供应商读取均为 0。','',
        '## 覆盖矩阵','', '|维度|已尝试|账户评价|剩余边界|','|---|---|---|---|']
    lines += [f"|{r['dimension']}|{r['attempted']}|{r['account_evaluated']}|{r['remaining_gap']}|" for r in coverage]
    lines += ['','## 收口','', '当前范围不再扩模型、seed、threshold、风险或优化器。R9 的真实账户状态问题仍未被原设计合法回答；若未来重新定义 Gross schema，需要另行科学授权，不冒称本轮完成了 R9。下一步仅在单独授权后对冻结政策做 2026 评价。','',
        '详细收益、双 NAV、年度回撤、集中度、Gross/Cash、持有期、成本、动作与精确 replacement 双腿统计见 A_FINAL_ACCOUNT_PATH_RESULTS.json；失败和缺口没有删去。']
    report=out/'REPORT.md';report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return summary
