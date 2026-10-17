"""C14 terminal ML delivery, adapting existing readers/statistical authority.

Labels/oracles are opened only after all currently-admissible frozen ML slots and
capacity/meta choices terminate. Missing B numeric states remain typed waiting;
there is no covariance producer, account runner, tuning or model retry here.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import assert_safe_output_path,resolve
from scripts.research.a2.training import selector_maximal_breadth as ctl
from scripts.research.a2.evaluation import selector_maximal_breadth_evidence as ev
from scripts.research.a2.evaluation import selector_boundary_delivery as old_delivery
from scripts.research.a2.evaluation.selector_account_compare import pre2026
from scripts.research.a2.data import selector_maximal_risk_consumer as risk
from scripts.research.a2.training.selector_challenge import sha


def _json(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def put(path,obj,kind='backtest'):
    assert_safe_output_path(path,kind=kind,paths=resolve(ctl.REPO));p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        ctl.require(_json(p)==obj,'PRESERVE_DIFFERENT_DELIVERY_OUTPUT:'+str(p));return
    p.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str,allow_nan=False)+'\n',encoding='utf-8')

def ref(path):return {'path':str(path),'sha256':sha(path)}

def table(path,frame):
    p=Path(path)
    if p.exists():
        assert_safe_output_path(p,kind='backtest');ctl.require(pq.read_table(p).to_pandas().equals(frame),'PRESERVE_DIFFERENT_TABLE:'+str(p));return ref(p)
    return ctl.write_table(p,frame)


def finish(run):
    run=Path(run);cfg,d,q=ctl.checked(run);ev.validate_design(d)
    results=Path(cfg['results_directory']);assert_safe_output_path(results,kind='results')
    if (run/'DELIVERY_COMPLETE.json').exists():
        done=_json(run/'DELIVERY_COMPLETE.json')
        for item in done['outputs'].values():ctl.pin(item)
        return done
    a=_json(run/'ML_ASSEMBLY.json');ledger=_json(run/'FIT_LEDGER.json')
    ctl.require(a['all_training_terminal'] and a['capacity_selection_complete'] and a['design_freeze_sha256']==sha(run/'DESIGN_FREEZE.json') and a['fit_ledger_sha256']==sha(run/'FIT_LEDGER.json'),'TERMINAL_ML_HASH_BINDING_REQUIRED')
    ctl.require(all(s['status'] not in ('RESERVED','STARTED') for s in ledger['slots'].values()),'NO_UNRESOLVED_ADMISSIBLE_FITS')
    branch=_json(run/'SCORE_ASSEMBLY.json')['branch_status'] if (run/'SCORE_ASSEMBLY.json').exists() else risk.readiness()
    # A newly published bank is reviewed by the frozen risk consumer, never
    # silently injected into already frozen ML pipelines or this ML delivery.
    statuses={r:('COMPLETE' if r in a['complete_candidates'] else a['failed_or_untestable'].get(r,d['blocked_roles'].get(r,'BLOCKED_DEPENDENCY_B_R5_NUMERIC_BANK'))) for r in d['roles']}
    failures={r:statuses[r] for r in d['roles'] if statuses[r]!='COMPLETE'}
    assembly={**a,'status':'SCORE_ASSEMBLY_COMPLETE','failed_or_untestable':failures,'branch_status':branch,'conditional_risk_queue':'WAITING_PUBLISHED_QUALIFIED_BANK','all_currently_admissible_training_terminal':True}
    put(run/'SCORE_ASSEMBLY.json',assembly)
    gate=dict(status='FINAL_PIPELINES_FROZEN',research_id=ctl.ID,design_sha256=sha(run/'DESIGN_FREEZE.json'),all_training_terminal=True,capacity_selection_complete=True,roles=d['roles'],role_statuses=statuses,score_assembly_sha256=sha(run/'SCORE_ASSEMBLY.json'),fit_ledger_sha256=sha(run/'FIT_LEDGER.json'),pair_key_sha256=q['pair_key_sha256'],forecast2026_rows=0,outer_labels_read=0,scope='terminal currently-admissible ML + typed blocked conditional risk queue')
    put(run/'FINAL_PIPELINES_FREEZE.json',gate)
    ev.validate_final_pipeline_gate(d,gate,assembly,gate['design_sha256'])
    # Reuse the existing pre2026/raw label reader only after the final gate.
    reference=old_delivery.reference_labels(d)
    clock=pre2026(ctl.pin(d['evaluation']['legacy']['clock']),['signal_date','included'],'signal_date');clock.signal_date=pd.to_datetime(clock.signal_date)
    old=pre2026(ctl.pin(d['evaluation']['legacy']['edge']),['signal_date',*d['evaluation']['legacy']['numeric_ids']],'signal_date');old.signal_date=pd.to_datetime(old.signal_date);old=old.set_index('signal_date')
    wanted=old.index[old.index.year>=2024]
    evidence_dir=run/'diagnostics/selector_evidence';evidence_dir.mkdir(parents=True,exist_ok=True)
    members=[];new={};panels={}
    for cid in a['complete_candidates']:
        p=pre2026(ctl.pin(a['panels'][cid]),['signal_date','security_uid','ticker','U_t_fingerprint','rank','score','candidate_id'],'signal_date');p.signal_date=pd.to_datetime(p.signal_date)
        ctl.require(p.candidate_id.eq(cid).all(),'EXACT_SCORE_ROLE_REQUIRED')
        daily=ev.membership_diagnostics(cid,reference,p,clock,final_gate=gate,expected_design_sha256=gate['design_sha256']);members.append(daily);panels[cid]=p
        s=daily.set_index('signal_date').replacement_edge.reindex(wanted)
        ctl.require(s.notna().all(),'FULL482_NO_PADDING_OR_DATE_DROP');new[cid]=s
    for c in d['contrasts']:
        if c['left'] in new and c['right'] in new:new[c['candidate_id']]=new[c['left']]-new[c['right']];failures.pop(c['candidate_id'],None)
    # Fixed shared oracle, charged once per mature outer date, never used in fit.
    g,y,tasks,ends,label_receipt=ctl.label_pairs(run,d,q,'2026-01-01',start='2024-01-01')
    raw=pq.read_table(ctl.pin(q['artifacts']['raw_current'])).to_pandas();raw.signal_date=pd.to_datetime(raw.signal_date)
    oracle_path=evidence_dir/'SHARED_ORACLE.parquet';oracle_receipt=run/'ORACLE_RECEIPT.json'
    if oracle_receipt.exists():
        o=_json(oracle_receipt);ctl.require(o['design_sha256']==gate['design_sha256'] and o['pair_key_sha256']==ctl.pairs.pair_key_sha256(g),'EXACT_ORACLE_REUSE_REQUIRED')
        oracle=pq.read_table(ctl.pin(o['artifact'])).to_pandas().set_index('signal_date').oracle_utility
        ctl.require(oracle.index.equals(wanted),'EXACT_SHARED_ORACLE_SUPPORT')
    else:
        journal=run/'ORACLE_EVENTS.jsonl';cached={}
        if journal.exists():
            for line in journal.read_text(encoding='utf-8').splitlines():
                row=json.loads(line);ctl.require(row['design_sha256']==gate['design_sha256'],'ORACLE_JOURNAL_PROVENANCE');cached[row['day']]=row
        charged=set()
        if (run/'SOLVE_EVENTS.jsonl').exists():charged={json.loads(line)['token'] for line in (run/'SOLVE_EVENTS.jsonl').read_text(encoding='utf-8').splitlines()}
        for day,ix in g.groupby('signal_date',sort=True).indices.items():
            daykey=day.isoformat();token='ORACLE|'+daykey
            if daykey in cached:continue
            if token in charged:row={'day':daykey,'oracle_utility':None,'status':'BLOCKED_UNCOMMITTED_ENGINEERING_SOLVE_NO_RETRY','design_sha256':gate['design_sha256']}
            else:
                _,chosen=ctl.decode(raw.loc[raw.signal_date.eq(day)],g.iloc[ix],y[ix],'ORACLE',y[ix]>0,on_solve=lambda:ctl.solve_callback(run,token))
                truth=g.iloc[ix].assign(edge=y[ix]);value=float(chosen.merge(truth,on=list(ctl.PAIR_KEYS),validate='one_to_one').edge.sum()/20)
                row={'day':daykey,'oracle_utility':value,'status':'COMPLETE','design_sha256':gate['design_sha256']}
            with journal.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,separators=(',',':'))+'\n');stream.flush()
            cached[daykey]=row
        oracle=pd.Series([cached[t.isoformat()]['oracle_utility'] for t in wanted],index=wanted,dtype=float,name='oracle_utility')
        ctl.flush_solve_ledger(run)
        artifact=table(oracle_path,oracle.reset_index());put(oracle_receipt,{'design_sha256':gate['design_sha256'],'pair_key_sha256':ctl.pairs.pair_key_sha256(g),'artifact':artifact,'charged_solve_calls':len(wanted),'failed_uncommitted_oracles':int(oracle.isna().sum()),'source_cutoff':'2026-01-01'})
    pairrows=[];bins=[];ranks=[]
    bindings={r['candidate_id']:r for r in d['role_bindings']}
    for cid in a['complete_candidates']:
        item=a['native_pair_predictions'][cid];f=pq.read_table(ctl.pin(item)).to_pandas();f.signal_date=pd.to_datetime(f.signal_date)
        f=f.loc[f.signal_date.isin(wanted)].reset_index(drop=True)
        ctl.require(f[list(ctl.PAIR_KEYS)].equals(g[list(ctl.PAIR_KEYS)]),'NATIVE_GATED_DIAGNOSTIC_KEY_ORDER')
        matches=old_delivery.matched_reader({'path':item['matching_path'],'sha256':item['matching_sha256']});matches=matches.loc[pd.to_datetime(matches.signal_date).isin(wanted)]
        rule=bindings.get(cid,{}).get('output_rule','U0_POINT_GT0');kind='edge';decision='U0'
        if rule=='U1_PROB_GT_0_5':values=f.prob.to_numpy();kind='probability';decision='U1'
        elif rule=='U2_Q10_GT0_MATCH_Q50':values=f[['q10','q50','q90']].to_numpy();kind='quantile';decision='U2'
        elif rule=='U3_MU_MINUS_SIGMA_GT0_MATCH_MU':values=f[['mu','sigma']].to_numpy();kind='gaussian';decision='U3'
        else:values=f.point.to_numpy()
        pdaily,pbins,pranks=ev.pair_diagnostics(cid,g,values,y,matches,oracle,kind=kind,decision=decision,final_gate=gate,expected_design_sha256=gate['design_sha256'],native_probability=f.prob.to_numpy() if kind=='gaussian' else None);pairrows.append(pdaily);bins.append(pbins);ranks.append(pranks)
    ctl.flush_solve_ledger(run)
    sums,boot,maxima=ev.statistics(old,new,clock,d['evaluation']['bootstrap'],d['evaluation']['legacy']['numeric_ids'],d['evaluation']['new_specs'],failures,design=d,gate=gate,assembly=assembly,expected_design_sha256=gate['design_sha256'],risk_inputs={})
    daily=pd.concat(members,ignore_index=True) if members else pd.DataFrame();pdiag=pd.concat(pairrows,ignore_index=True) if pairrows else pd.DataFrame()
    diagnostics={}
    for n,v in [('DAILY_POLICY_DIAGNOSTICS',daily),('PAIR_DIAGNOSTICS',pdiag),('PAIR_CALIBRATION',pd.concat(bins,ignore_index=True) if bins else pd.DataFrame()),('REPLACEMENT_RANK_DISTRIBUTION',pd.concat(ranks,ignore_index=True) if ranks else pd.DataFrame()),('PRIMARY_DAILY_EDGE',pd.DataFrame(new,index=wanted).reset_index()),('BOOTSTRAP_MAXT',pd.DataFrame({'max_t':maxima})),('SHARED_ORACLE',oracle.rename('oracle_utility').reset_index())]:diagnostics[n]=table(evidence_dir/(n+'.parquet'),v)
    slots=list(ledger['slots'].values());counts=dict(reservations=len(slots),entered=sum(s['entered'] for s in slots),complete=sum(s['status']=='COMPLETE' for s in slots),failed=sum(s['status']=='FAILED' for s in slots),blocked=sum(s['status'].startswith('BLOCKED') for s in slots),solver_requests=len(_json(run/'SOLVE_LEDGER.json')['requests']),scientific_retry=0,hard_fit_cap=1800,hard_solve_cap=30000,shared_risk_new_estimation_by_C=0)
    ctl.require(counts['entered']<=1800 and counts['solver_requests']<=30000,'ACTUAL_BUDGET_BREACH')
    composite=[s for s in slots if s.get('event',{}).get('operation')=='retained_Gate_composite_state_reservation' and s['entered']]
    counts.update(entered_reservation_ceiling=counts['entered'],conservative_composite_state_entries=len(composite),confirmed_external_backend_invocations=sum(bool(s['entered']) and s.get('event',{}).get('operation')!='retained_Gate_composite_state_reservation' for s in slots),composite_state_actual_internal_calls='not independently instrumented; reservation ceiling disclosed')
    covslots=[{**s,'backend_entered':bool(s['entered'])} for s in slots]
    coverage=ev.training_coverage_audit(d['coverage_plan'],covslots,statuses)
    support=[r['candidate_id'] for r in sums if r.get('supported') and r['candidate_id'] in a['complete_candidates']]
    outcome='C14_PROGRESSIVE_ML_SUPPORTED' if support else 'C14_MAXIMAL_BREADTH_COMPLETE_NO_SUPPORT'
    state='C14_WAITING_B_R5_NUMERIC_BANK' if branch['status']=='WAITING_B_R5_NUMERIC_BANK' else 'C14_PARTIAL_INPUT_BLOCKED'
    errors=[{'node_id':s['node_id'],'entered':s['entered'],'error':s.get('error',s.get('reason'))} for s in slots if s['status']=='FAILED']
    preservation=ctl.checked_sources(run,d)
    diag_summary=daily.groupby(['candidate_id','year'])[['replacement_edge','raw_overlap','replacement_count','membership_turnover']].mean().reset_index().to_dict('records') if len(daily) else []
    evidence={'research_id':ctl.ID,'status':state,'ml_outcome':outcome,'supported_progressive_roles':support,'strict_PIT_promotion_eligible':False,'independent_holdout':False,'2026_locked':True,'new2026_reads':0,'tests':sums,'bootstrap':boot,'fit_counts':counts,'failed_fits':errors,'role_statuses':statuses,'diagnostics':diagnostics,'training_coverage_audit':coverage,'risk_branch':branch,'design':ref(run/'DESIGN_FREEZE.json'),'final_pipeline':ref(run/'FINAL_PIPELINES_FREEZE.json'),'outer_label_receipt':label_receipt,'no_account_net_profit_claim':True}
    if (run/'SOURCE_CORRECTION.json').exists():evidence['source_correction']=ref(run/'SOURCE_CORRECTION.json')
    put(evidence_dir/'SELECTION_EVIDENCE.json',evidence);put(results/'SELECTION_EVIDENCE.json',evidence,kind='results')
    payload={'status':state+' / '+outcome,'tests':sums,'bootstrap':boot,'risk_tests':boot.get('risk_tests',[]),'training_coverage_audit':coverage,'budget':counts,'diagnostic_summary':diag_summary,'faults':errors,'remaining':[d['blocked_roles'],branch,'No real risk/classical/hybrid/gate inference until exact qualified B bank; conditional DAG remains frozen'],'storage':{'run':str(run),'results':str(results),'cache':cfg['cache_directory']},'preservation':preservation}
    report=results/'FINAL_REPORT.md';assert_safe_output_path(report,kind='results');report_bytes=(ev.render_report(payload)+'\n').encode('utf-8')
    if report.exists():ctl.require(report.read_bytes()==report_bytes,'PRESERVE_DIFFERENT_FROZEN_REPORT')
    else:report.write_bytes(report_bytes)
    put(results/'MODEL_UPDATE_GATE.json',{'status':'NO_STRICT_PIT_PROMOTION','mechanism_supported_roles':support,'strict_PIT_promotion_eligible':False,'2026_locked':True,'no_account_profit_assertion':True},kind='results')
    done={'status':state,'ml_outcome':outcome,'research_id':ctl.ID,'outputs':{'report':ref(report),'evidence':ref(results/'SELECTION_EVIDENCE.json'),'model_update_gate':ref(results/'MODEL_UPDATE_GATE.json')},'fit_counts':counts,'design_sha256':gate['design_sha256'],'fit_ledger_sha256':sha(run/'FIT_LEDGER.json'),'score_assembly_sha256':sha(run/'SCORE_ASSEMBLY.json'),'final_pipeline_sha256':sha(run/'FINAL_PIPELINES_FREEZE.json'),'risk_queue_completed':False,'strict_PIT_promotion_eligible':False,'current_time':ctl.now()}
    if (run/'SOURCE_CORRECTION.json').exists():done['source_correction']=ref(run/'SOURCE_CORRECTION.json')
    put(run/'DELIVERY_COMPLETE.json',done)
    return done


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=Path);args=p.parse_args()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        if not (args.run/'ML_DELIVERY_COMPLETE.json').exists():ctl.run(args.run)
        result=finish(args.run)
    print(json.dumps({'status':result['status'],'ML_delivery':True,'report':result['outputs']['report']['path']}),flush=True)

if __name__=='__main__':main()