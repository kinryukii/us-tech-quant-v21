"""Frozen RX selection with current DEMO execution; A2 outputs stay immutable."""
from __future__ import annotations
import ast
from contextlib import contextmanager
from types import ModuleType
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import uuid
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import demo_performance as base
from scripts.research.a2.evaluation import demo_performance_prices as price_reader
from scripts.common.daily_support import save
from scripts.daily_recommendation_prices import verify, PRICE_FIELDS

R5_PATH=Path('D:/us-tech-quant-worktrees/harness-task-20260827-041928-8076/scripts/v22/a2_free_factor_discovery.py')
RX_PATH=Path('D:/us-tech-quant/_codex_transfer/rx_exact_1sigma_replay_r1_scratch/pre2026_exact_rx_replay.py')
CONTRACT_PATH=Path('D:/us-tech-quant-results/RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1/frozen_contract.json')
PINS={R5_PATH:'1cdff21546e4ad5bd7cfd732b221f784222977d476a640b3b8765c911139b880',
      RX_PATH:'049f6ce79a69717753e0544278c268fe142504ea2ea65028a0b38c534fa5b07c',
      CONTRACT_PATH:'e9735b812549bd147a4fa311027f5d5cc0cedf06bbe29352c4cd564fa449832e'}
FEATURES=('close_location_5','range_shock_5_20','volume_shock_5_20')


@contextmanager
def isolated_frozen_imports():
    """Frozen runners may prepend old worktrees; never leak import routing."""
    saved_path=list(sys.path)
    saved_modules={name:module for name,module in sys.modules.items()
                   if name=='scripts' or name.startswith('scripts.')}
    saved_attrs={name:dict(vars(module)) for name,module in saved_modules.items() if module is not None}
    try:
        yield
    finally:
        sys.path[:]=saved_path
        for name in list(sys.modules):
            if (name=='scripts' or name.startswith('scripts.')) and name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)
        for name,attrs in saved_attrs.items():
            namespace=vars(saved_modules[name])
            for key,value in list(namespace.items()):
                if isinstance(value,ModuleType) and key not in attrs:namespace.pop(key,None)
            for key,value in attrs.items():
                if isinstance(value,ModuleType) or key=='__path__':namespace[key]=value


def json_audit(value):
    """Convert audit scalars without changing selection or execution values."""
    if isinstance(value,dict):return {key:json_audit(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [json_audit(item) for item in value]
    if isinstance(value,(pd.Timestamp,datetime)):return value.isoformat()
    if isinstance(value,np.generic):return value.item()
    return value


def authority():
    for path,sha in PINS.items():verify(path,sha)
    modules=[]
    with isolated_frozen_imports():
        for path in (R5_PATH,RX_PATH):
            name='rx_demo_pinned_'+uuid.uuid4().hex
            spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
            sys.modules[name]=module;spec.loader.exec_module(module);modules.append(module)
    r5,rx=modules
    specification=next(s for s in r5.R4_CANDIDATES if s.candidate_id=='R5_RANGE_EXHAUSTION')
    contract=base.read(CONTRACT_PATH)
    if (r5.semantic_fingerprint(r5.r4_semantic_spec(specification))!=contract['source_r5_fingerprint']
            or contract['exact_replacement_rule']['threshold_sigma']!=1.0
            or contract['exact_replacement_rule']['cross_sectional_score_std']['ddof']!=0):
        raise ValueError('RX_FROZEN_AUTHORITY_MISMATCH')
    return r5,rx


def frozen_price_features(panel,prices):
    """Execute only pinned original AST assignments needed by RX, no labels."""
    tree=ast.parse(R5_PATH.read_text(encoding='utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='attach_price_path_features')
    loop=next(n for n in function.body if isinstance(n,ast.For))
    wanted={'previous_close','spread','close_location_1','range_pct_1','log_volume',
            'close_location_5','range_pct_5','range_pct_20','range_shock_5_20','volume_shock_5_20'}
    statements=[]
    for node in loop.body:
        if not isinstance(node,ast.Assign):continue
        target=node.targets[0]
        name=target.id if isinstance(target,ast.Name) else target.slice.value if isinstance(target,ast.Subscript) and isinstance(target.slice,ast.Constant) else None
        if name in wanted:statements.append(node)
    if len(statements)!=len(wanted):raise ValueError('RX_FEATURE_AST_CONTRACT_CHANGED')
    code=compile(ast.fix_missing_locations(ast.Module(body=statements,type_ignores=[])),str(R5_PATH),'exec')
    frames=[]
    for ticker,history in prices.groupby('ticker',sort=True):
        history=history.sort_values('trade_date',kind='mergesort').copy()
        scope={'history':history,'np':np};exec(code,scope)
        feature=history[['trade_date',*FEATURES]].rename(columns={'trade_date':'signal_date'})
        feature['ticker']=ticker;frames.append(feature)
    return panel.merge(pd.concat(frames,ignore_index=True),on=['signal_date','ticker'],how='left',validate='one_to_one')


def select_rx(rankings,prices,calendar,r5,rx):
    panel=rankings.rename(columns={'target_date':'signal_date','rank':'raw_rank','score':'raw_score'}).copy()
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    if 'raw_score' not in panel:raise ValueError('RX_REQUIRES_ORIGINAL_A2_SCORE_FOR_TIEBREAK_ONLY')
    if panel.groupby('signal_date').ticker.nunique().ne(40).any():raise ValueError('RX_REQUIRES_EXACT_TOP40')
    if prices.loc[prices.trade_date.lt(panel.signal_date.min()),'trade_date'].nunique()<60:
        raise ValueError('RX_REQUIRES_60_SESSION_WARMUP')
    panel['raw_score_z']=r5._safe_zscore(panel,'raw_score')
    for col in ['target','target_end_date','realized_vol_20d','ret_20d','avg_dollar_volume_20d',
                'entered_top40','tight_boundary_state','beta60_qqq','beta60_soxx','peer_count']:
        if col not in panel:panel[col]=np.nan
    panel['ff12_bucket']='UNKNOWN'
    r5.FOLD_YEARS=tuple(sorted(panel.signal_date.dt.year.unique()))
    r5.CUTOFF=panel.signal_date.max();r5.BOUNDARY_EXCLUSIVE=r5.CUTOFF+pd.Timedelta(days=1)
    panel,graph=r5.attach_residual_graph_features(panel,prices.loc[prices.trade_date<=r5.CUTOFF])
    panel=frozen_price_features(panel,prices.loc[prices.trade_date<=r5.CUTOFF])
    score=(-r5._safe_zscore(panel,'range_shock_5_20')*r5._safe_zscore(panel,'close_location_5')
           *(1+0.25*r5._safe_zscore(panel,'volume_shock_5_20'))).replace([np.inf,-np.inf],np.nan).fillna(-10.)
    panel['candidate_score']=score
    spec=next(s for s in r5.R4_CANDIDATES if s.candidate_id=='R5_RANGE_EXHAUSTION')
    proposed=r5.r4_make_selection(panel,score,spec);raw=r5.raw_selection(panel)
    selections=[];decisions=[]
    # NaT is an explicit unknown next open, never an invented calendar session.
    dates=pd.DataFrame({'ticker':'QQQ','trade_date':[*calendar,pd.NaT]})
    for day,original in raw.groupby('signal_date',sort=True):
        proposal=proposed.loc[proposed.signal_date.eq(day)]
        universe=panel.loc[panel.signal_date.eq(day)]
        if set(original.ticker)==set(proposal.ticker):
            selected=universe.loc[universe.ticker.isin(original.ticker)].sort_values(
                ['candidate_score','raw_score','ticker'],ascending=[False,False,True],kind='mergesort').copy()
            selected['candidate_rank']=np.arange(1,21);selected['candidate_id']='RX_MARGIN_R1'
            selected=selected[proposal.columns]
        else:
            selected,ledger=rx.build_exact_rx_selection(universe,original,proposal,dates)
            decisions.append(ledger)
        selections.append(selected)
    selected=pd.concat(selections,ignore_index=True)
    ledger=pd.concat(decisions,ignore_index=True) if decisions else pd.DataFrame(columns=['signal_date','execution_date','pair_index','replacement_decision'])
    signals=selected.rename(columns={'signal_date':'target_date','candidate_rank':'rank'})
    signals['target_date']=signals.target_date.dt.strftime('%Y-%m-%d')
    return signals,ledger,{'graph':graph,'predictive_model_fit_count':0,'parameter_search_count':0,
        'feature_extraction':'HASH_PINNED_ORIGINAL_AST_TRAILING_ONLY','future_label_columns_computed':False}


def qualified_feature_prices(paths,historical_path,tickers,end,current_report_path=None):
    """Rehydrate only historical feature-qualified OHLCV, never open-only supplements."""
    hist=base.read(historical_path);ref=hist['price_manifest'];inputs=base.read(base.verified(ref))
    from scripts.daily_recommendation_prices import _adapter,COVERAGE_PATH,COVERAGE_SHA
    coverage=base.read(verify(COVERAGE_PATH,COVERAGE_SHA));adapter=_adapter(end)
    wolf={'event_date':coverage['adjustment']['wolf_event_date'],'quantity_multiplier':coverage['adjustment']['wolf_new_shares_per_old_share']}
    from scripts.research.a2.inference.historical_top40_prices import _store
    store=_store(paths);cache={};refs={};frames=[];gaps=[]
    def checked(path,sha):
        path=verify(path,sha);refs[str(path)]={'path':str(path),'sha256':sha};return path
    entries=list(inputs['lineage'])
    if current_report_path is not None:
        current,_=price_reader._current_entries(current_report_path,Path(historical_path).resolve(),base.digest(historical_path),checked)
        entries.extend(current)
    by_ticker={}
    for entry in entries:
        if entry['ticker'] not in tickers:continue
        if entry.get('execution_bridge'):raise ValueError('RX_EXECUTION_ONLY_INPUT_FORBIDDEN')
        try:
            raw=price_reader._raw(entry,checked,store,cache)
            factor=entry['rehab'];factors=pd.read_parquet(checked(factor['path'],factor['sha256']))
            if 'code' not in factors or (factor.get('kind')=='CURRENT_SNAPSHOT' and not factors.code.eq(entry['code']).all()):
                raise ValueError('RX_REHAB_IDENTITY_INVALID')
            frame,_=adapter.adjusted_price_frame(entry['code'],entry['ticker'],raw,factors,wolf)
            if frame.duplicated(['ticker','trade_date']).any() or not np.isfinite(frame[PRICE_FIELDS].to_numpy(float)).all():
                raise ValueError('RX_FULL_OHLCV_INVALID')
            if (frame[['open','high','low','close']]<=0).any().any() or frame.volume.lt(0).any():raise ValueError('RX_FULL_OHLCV_INVALID')
            frame=frame[['ticker','trade_date',*PRICE_FIELDS]]
            if entry['ticker'] in by_ticker:
                frame=merge_qualified_frames(by_ticker[entry['ticker']],frame)
            by_ticker[entry['ticker']]=frame
        except (ValueError,KeyError,OSError) as exc:
            if str(exc)=='RX_CURRENT_FULL_OHLCV_OVERLAP_CHANGED':raise
            gaps.append({'ticker':entry['ticker'],'reason':str(exc)})
    frames=list(by_ticker.values())
    missing=set(tickers)-set(by_ticker)
    if missing:raise ValueError('RX_QUALIFIED_OHLCV_MISSING:'+','.join(sorted(missing)))
    return pd.concat(frames,ignore_index=True),list(refs.values()),gaps


def merge_qualified_frames(old,new):
    overlap=old.merge(new,on=['ticker','trade_date'],suffixes=('_old','_new'))
    if overlap.empty or any(not overlap[field+'_old'].eq(overlap[field+'_new']).all() for field in PRICE_FIELDS):
        raise ValueError('RX_CURRENT_FULL_OHLCV_OVERLAP_CHANGED')
    return pd.concat([old,new.loc[~new.trade_date.isin(old.trade_date)]],ignore_index=True).sort_values('trade_date')


def validate_signal_price_dates(rankings,prices,calendar):
    required={(pd.Timestamp(day),ticker) for day,ticker in rankings[['target_date','ticker']].itertuples(index=False,name=None)}
    if not {day for day,_ in required}<=set(calendar):raise ValueError('RX_SIGNAL_OUTSIDE_VERIFIED_CALENDAR')
    available=set(zip(pd.to_datetime(prices.trade_date),prices.ticker))
    if required-available:raise ValueError('RX_SIGNAL_FULL_OHLCV_DATE_MISSING')


def parent_rankings(parent):
    if parent.get('missing_signal_inference'):
        raise ValueError('RX_BLOCKED_MISSING_SIGNAL_FEATURE_LINEAGE')
    refs=[parent['outputs'][name] for name in ('rankings','coverage')]
    return *(pd.read_parquet(base.verified(ref)) for ref in refs),refs


def execution_tickers(rx_signals,a2_rankings,a2_positions):
    """Retain the A2 reviewed union, including names only in pending signals."""
    return sorted(set(rx_signals.ticker) | set(a2_positions.ticker)
                  | set(a2_rankings.loc[a2_rankings['rank'].le(20),'ticker']))


def refresh_rx_performance(paths,historical_path,current_report_path,parent_a2_manifest,output_dir):
    """Explicit independent producer; does not publish or modify A2 latest."""
    work=Path(output_dir).resolve()
    if work.parent != (paths.daily_root/'A2_updated_research_rx/runs').resolve():
        raise ValueError('RX_REQUIRES_INDEPENDENT_CANONICAL_RUN_DIRECTORY')
    work.mkdir(parents=True,exist_ok=False)
    report={'schema_version':1,'source_id':'A2_RX_UPDATED_RESEARCH','policy_id':'RX_MARGIN_R1','status':'RUNNING',
        'report_path':str(work/'manifest.json'),'run_id':work.name,'generated_at':datetime.now(timezone.utc).isoformat(),
        'contract':{'path':str(CONTRACT_PATH),'sha256':PINS[CONTRACT_PATH]},
        'limitations':['Frozen RX selection with current DEMO open-ended execution; not a reproduction of the old terminal-liquidation ledger.',
                        '2023–2025 historical training/validation and exposed 2026 test are descriptive; no untouched holdout claim.']}
    try:
        parent_path,parent_ref=base.canonical_manifest(parent_a2_manifest)
        parent=base.read(parent_path)
        if parent['status'] not in {'READY','PARTIAL'} or parent['ranking_manifest']['sha256']!=base.digest(historical_path):
            raise ValueError('RX_PARENT_A2_HISTORY_MISMATCH')
        parent_contract=base.read(base.verified(parent['evaluation_contract']))
        if parent_contract['current_report']['sha256']!=base.digest(current_report_path):
            raise ValueError('RX_PARENT_A2_CURRENT_REPORT_MISMATCH')
        report['parent_a2_manifest']=parent_ref
        from scripts.research.a2.inference.historical_top40 import load_sessions
        rankings,coverage,ranking_refs=parent_rankings(parent)
        sessions,calendar_ref=load_sessions(paths);calendar=pd.DatetimeIndex(pd.to_datetime(sessions))
        prices,feature_refs,gaps=qualified_feature_prices(paths,historical_path,set(rankings.ticker),str(rankings.target_date.max()),current_report_path)
        validate_signal_price_dates(rankings,prices,calendar)
        r5,rx=authority();signals,decisions,selection_audit=select_rx(rankings,prices,calendar,r5,rx)
        parent_positions=pd.read_parquet(base.verified(parent['outputs']['positions']))
        selected=execution_tickers(signals,rankings,parent_positions)
        execution=price_reader.load_execution_prices(paths,historical_path,current_report_path=current_report_path,tickers=selected)
        resolved,event_audit=base.reviewed_events(execution['events'],execution.get('event_review'),execution['refs'])
        cutoff,blocked=base.safe_execution_end(signals,execution['prices'],calendar,execution['events'],resolved)
        save(work/'selection_audit.json',json_audit(selection_audit))
        save(work/'selection_contract.json',{'policy_id':'RX_MARGIN_R1','authority_refs':[{'path':str(p),'sha256':s} for p,s in PINS.items()],
            'frozen_contract':{'path':str(CONTRACT_PATH),'sha256':PINS[CONTRACT_PATH]},
            'selection_audit':base.reference(work/'selection_audit.json'),'producer':base.reference(__file__),
            'warmup_sessions':60,'predictive_model_fit_count':0,'threshold_search_count':0,
            'execution_policy':'CURRENT_DEMO_NEXT_OPEN_EQUAL_WEIGHT_10BP_NO_TERMINAL_LIQUIDATION'})
        report['selection_contract']=base.reference(work/'selection_contract.json')
        save(work/'evaluation_contract.json',{'source_id':'A2_RX_UPDATED_RESEARCH',
            'evaluation':{**base.EVALUATION,'selection':'RX_MARGIN_R1'},
            'parent_a2_manifest':parent_ref,'selection_contract':report['selection_contract'],
            'historical_manifest':base.reference(historical_path),'current_report':base.reference(current_report_path),
            'price_refs':execution['refs'],'safe_execution_end_date':str(cutoff.date()),'blocking_input':blocked})
        report['evaluation_contract']=base.reference(work/'evaluation_contract.json')
        engine,engine_refs=base._authority(paths);engine.EFFECTIVE_START=pd.Timestamp(signals.target_date.min())
        targets=engine.build_target_map(signals.rename(columns={'target_date':'signal_date'}),'rank')
        ledger=engine.reconstruct_open_ended('RX_MARGIN_R1',targets,execution['prices'],calendar,cutoff)
        daily,positions,trades=base.normalize_ledger(ledger,signals,calendar)
        daily['model']='A2_RX';positions['model']='A2_RX'
        if 'model' in trades:trades['model']='A2_RX'
        decisions=decisions.rename(columns={'execution_date':'scheduled_execution_date'})
        price_paths=execution['prices'][['trade_date','ticker','open','close']].rename(columns={'trade_date':'date'}).copy()
        price_paths['adjustment']='PIT_FORWARD_REHAB_INDEX'
        price_paths['source']='VERIFIED_RAW_PLUS_PIT_REHAB'
        outputs={}
        for name,frame in {'selections':signals,'decisions':decisions,'portfolio_daily':daily,
            'positions':positions,'trades':trades,'decision_calendar':base.decision_calendar(signals,coverage,calendar,cutoff,blocked),
            'corporate_action_events':event_audit,'price_paths':price_paths}.items():
            dest=work/(name+'.parquet');frame.to_parquet(dest,index=False);outputs[name]={**base.reference(dest),'rows':len(frame)}
        report.update(status='PARTIAL' if blocked else 'READY',outputs=outputs,
            ranking_start_date=str(signals.target_date.min()),ranking_end_date=str(signals.target_date.max()),
            performance_start_date=str(signals.target_date.min()),performance_end_date=str(cutoff.date()),
            ranking_days=int(signals.target_date.nunique()),performance_points=len(daily),return_observations=max(0,len(daily)-1),
            blocking_input=blocked,feature_gaps=gaps,execution_gaps=execution['gaps'],
            evaluation={**base.EVALUATION,'selection':'RX_MARGIN_R1'},model_fit_count=0,parameter_search_count=0,
            authority_refs=[{'path':str(p),'sha256':s} for p,s in PINS.items()]+engine_refs,
            input_refs=ranking_refs+feature_refs+execution['refs']+[parent_ref,parent['outputs']['positions']],calendar_lineage=calendar_ref['lineage'])
        for ref in report['authority_refs']+report['input_refs']:base.verified(ref)
    except Exception as exc:report.update(status='BLOCKED',error=str(exc))
    save(work/'manifest.json',report)
    return report


def main():
    import argparse
    from scripts.common.storage_paths import resolve
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-manifest',required=True,type=Path)
    parser.add_argument('--current-report',required=True,type=Path)
    parser.add_argument('--parent-a2-manifest',required=True,type=Path)
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    if Path(args.run_id).name!=args.run_id or args.run_id in {'.','..'}:raise ValueError('INVALID_RUN_ID')
    paths=resolve()
    result=refresh_rx_performance(paths,args.historical_manifest,args.current_report,args.parent_a2_manifest,
        paths.daily_root/'A2_updated_research_rx/runs'/args.run_id)
    print(result['status'],result['report_path'])
    return 0 if result['status'] in {'READY','PARTIAL'} else 2


if __name__=='__main__':raise SystemExit(main())
