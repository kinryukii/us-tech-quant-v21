"""Trace only the 54 missing-field last-date rows using existing saved receipts.

No prediction, replay, fitting, price fetching, gate repair, or source mutation.
"""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
STRICT=ROOT.parent/'a2_strict_method_retrain_20260926'
OLD=ROOT.parent/'a2_complete_suite_20260927'
OTHER=ROOT.parent/'a2_13f_learned_sizing_pre2026_test2026_r1/continuation_2026_r1'
DATE=pd.Timestamp('2026-09-22')

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def safe(v):
    if isinstance(v,(pd.Timestamp,np.datetime64)):return None if pd.isna(v) else str(pd.Timestamp(v).date())
    if isinstance(v,np.generic):return v.item()
    return v
def write(p,obj):Path(p).write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=safe,allow_nan=False),encoding='utf-8')
def date(v):return '' if pd.isna(v) else str(pd.Timestamp(v).date())

def main():
    paths={'last_targets':ROOT/'LAST_TEST_DATE_TARGETS.csv','current_context':ROOT/'data/test_features_context.parquet',
        'r6':STRICT/'test2026_stage/r6_contract_correction/R6_FULL_CANDIDATE_INPUT_GATE.parquet',
        'materialized_features':STRICT/'test2026_stage/identity_feature_application_r1/ORIGINAL_32_FEATURES_2026_CANDIDATE_INPUT_ONLY.parquet',
        'consumed_events':STRICT/'test2026_stage/identity_feature_application_r1/CONSUMED_REHAB_EVENT_AUDIT.parquet',
        'identity_resolution':OTHER/'REMAINING75_RESOLUTION.csv'}
    initial_hash={str(p):sha(p) for p in paths.values()}
    t=pd.read_csv(paths['last_targets'],encoding='utf-8-sig',dtype={'cusip':str})
    missing=t[['quarter','cusip','new_buy_eligible']].isna().any(axis=1)
    selected=t.loc[missing].copy();names=sorted(selected.ticker.unique())
    assert len(selected)==54 and len(names)==45 and pd.to_datetime(selected.signal_date).eq(DATE).all()
    assert selected.target_weight.eq(0).all() and selected.current_weight.gt(0).all()
    context=pd.read_parquet(paths['current_context']);g=pd.read_parquet(paths['r6']);f=pd.read_parquet(paths['materialized_features'])
    events=pd.read_parquet(paths['consumed_events'])
    resolution=pd.read_csv(paths['identity_resolution'],dtype={'original_cusip':str})
    current=g.loc[g.signal_date.eq(DATE)]
    assert not context.loc[context.signal_date.eq(DATE)&context.ticker.isin(names)].shape[0]
    featurecols=read(ROOT/'data/JOINT_DATA_AUDIT.json')['features']
    rows=[]
    for ticker in names:
        history=g.loc[g.ticker.eq(ticker)].sort_values('signal_date')
        cur=current.loc[current.ticker.eq(ticker)]
        fh=f.loc[f.ticker.eq(ticker)].sort_values('signal_date');fc=fh.loc[fh.signal_date.eq(DATE)]
        ch=context.loc[context.ticker.eq(ticker)].sort_values('signal_date')
        last=history.iloc[-1]
        current_identity_matches=current.loc[current.cusip.isin(history.cusip.unique())]
        if len(cur):
            assert len(cur)==1 and cur.iloc[0].final_input_gate=='UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME'
            r=cur.iloc[0]
            assert bool(r.has_32_finite) and bool(r.lookback_121_eligible) and bool(r.version_checked)
            reason='CURRENT_CANDIDATE_EVENT_PUBLICATION_EVIDENCE_UNVERIFIED'
            explanation='当前2026Q2候选账有此身份，32特征有限、121会话历史及版本检查通过；因已消费复权事件的历史发布时间证据未核证，R6未准入预测context。'
        else:
            assert len(current_identity_matches)==0
            r=last
            reason='ABSENT_FROM_CURRENT_SAVED_CANDIDATE_SNAPSHOT'
            explanation='当前已保存候选快照无该ticker，也无其历史CUSIP匹配；此事实说明未进入本批当前候选输入，不证明实体不存在、证券不可交易或所有13F中均未披露。'
        res=resolution.loc[resolution.original_ticker.eq(ticker)]
        rr=res.iloc[0] if len(res)==1 else None
        lifecycle=date(pd.to_datetime(last.lifecycle_end_exclusive,errors='coerce'))
        ev=events.loc[events.ticker.eq(ticker)&events.event_date.between('2026-01-01',DATE)&events.audit_kind.eq('APPLIED_CORPORATE_ACTION')].sort_values('event_date')
        row={'ticker':ticker,'affected_strategy_rows':int(selected.ticker.eq(ticker).sum()),'policies':'|'.join(sorted(selected.loc[selected.ticker.eq(ticker),'policy'])),
            'input_absence_reason':reason,'reason_zh':explanation,'in_signal_context':False,'in_current_saved_candidate_snapshot':bool(len(cur)),
            'current_saved_quarter':str(cur.iloc[0].quarter) if len(cur) else '',
            'current_saved_cusip':str(cur.iloc[0].cusip) if len(cur) else '',
            'current_gate':str(cur.iloc[0].final_input_gate) if len(cur) else '',
            'current_raw_signal_row_present':bool(cur.iloc[0].raw_on_signal) if len(cur) else None,
            'current_gate_32_finite':bool(cur.iloc[0].has_32_finite) if len(cur) else None,
            'current_gate_121_eligible':bool(cur.iloc[0].lookback_121_eligible) if len(cur) else None,
            'current_gate_version_checked':bool(cur.iloc[0].version_checked) if len(cur) else None,
            'current_materialized_feature_row':bool(len(fc)),
            'current_materialized_32_finite':bool(np.isfinite(fc[featurecols].to_numpy(float)).all()) if len(fc) else None,
            'last_materialized_feature_date':date(fh.signal_date.max()),'last_context_date':date(ch.signal_date.max()),
            'last_saved_candidate_date':date(last.signal_date),'last_saved_candidate_quarter':str(last.quarter),
            'historical_cusips':'|'.join(sorted(history.cusip.unique())),'historical_cusip_matches_current_snapshot':int(len(current_identity_matches)),
            'last_saved_gate':str(last.final_input_gate),'last_saved_transport_used':str(last.transport_used),
            'first_consumed_2026_event_field':date(r.first_consumed_2026_event),
            'consumed_2026_events_through_signal':len(ev),'has_share_event_through_signal':bool(ev.share_event.fillna(False).any()) if len(ev) else False,
            'saved_lifecycle_end_exclusive':lifecycle,'saved_resolution_status':str(rr.resolution_status) if rr is not None else '',
            'saved_identity_evidence_refs':str(rr.evidence_refs) if rr is not None else '',
            'saved_identity_evidence_hash_status':str(rr.evidence_sha256s) if rr is not None else '',
            'cannot_infer':'CSV空值不等于new_buy_eligible=False；UNKNOWN不等于当时未公开/价格错误；零目标不证明模型明确选择退出。'}
        if ticker=='EXAS':row['reason_zh']+='另有既存生命周期收据记录2026-03-23起PROVEN_LIFECYCLE_INELIGIBLE；物化特征止于3月20日。本次未重新验证其外部来源。'
        if ticker=='DTP':row['reason_zh']+='既有身份收据将历史CUSIP 233331107普通股的传输映射为US.DTE；DTP是此批保存的ticker标签。'
        rows.append(row)
    lineage=pd.DataFrame(rows).sort_values('ticker')
    lineage.to_csv(OUT/'TICKER_INPUT_LINEAGE.csv',index=False,encoding='utf-8-sig')
    enriched=selected.merge(lineage,on='ticker',validate='many_to_one')
    enriched.to_csv(OUT/'MISSING54_INPUT_LINEAGE.csv',index=False,encoding='utf-8-sig')
    gh=g.loc[g.ticker.isin(names),['signal_date','ticker','quarter','cusip','title_of_class','final_input_gate','has_32_finite','lookback_121_eligible','version_checked','lifecycle_end_exclusive','first_consumed_2026_event','transport_used']]
    gh.groupby(['ticker','quarter','cusip','final_input_gate'],dropna=False).agg(first_signal=('signal_date','min'),last_signal=('signal_date','max'),candidate_days=('ticker','size')).reset_index().to_csv(OUT/'SAVED_GATE_HISTORY_INTERVALS.csv',index=False,encoding='utf-8-sig')
    current.loc[current.ticker.isin(names)].to_parquet(OUT/'R6_CURRENT_CANDIDATE_EVIDENCE.parquet',index=False)
    events.loc[events.ticker.isin(names)&events.event_date.between('2026-01-01',DATE)].to_csv(OUT/'CONSUMED_EVENT_EVIDENCE_THROUGH_SIGNAL.csv',index=False,encoding='utf-8-sig')
    inventories=[]
    for policy in sorted(selected.policy.unique()):
        folder=ROOT/'evaluation_2026/cost_10'/f'{policy}_10bps'
        files=[]
        for p in sorted(folder.iterdir()):
            if not p.is_file():continue
            entry={'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)}
            if p.suffix=='.parquet':entry['columns']=pq.read_schema(p).names
            files.append(entry)
        forbidden=[item['name'] for item in files if any(word in item['name'].lower() for word in ['raw_target','adapted_target','raw_logits','action_value'])]
        assert not forbidden
        inventories.append({'policy':policy,'folder':str(folder),'files':files,'raw_target_dictionary_saved':False,'adapted_target_dictionary_saved':False,
            'saved_decision_receipt':'target_decisions.parquet stores validated target_weight with missing keys defaulted to zero; it is not raw model output',
            'saved_execution_receipts':['trades.parquet: actual fills only','diagnostics.parquet: blocked/exception event rows','positions.parquet: carried index-unit holdings','daily.parquet: account totals'],
            'standalone_order_object_snapshot_saved':False})
    write(OUT/'ARTIFACT_TRACE_INVENTORY.json',inventories)
    evidence=[]
    anchors=[(ROOT/'finalize_suite.py',"latest=pd.concat(latest,ignore_index=True).merge"),
        (ROOT/'engine.py','targets = _validate_targets('),(ROOT/'engine.py','for ticker in sorted(set(targets) | set(holdings))'),
        (ROOT/'engine.py','"target_weight": targets.get(ticker, 0.0)'),(ROOT/'engine.py','pending = {"signal_date": date'),
        (ROOT/'run_suite.py',"for key in ['daily','trades','positions','target_decisions'"),
        (ROOT/'joint_linear_tree.py','self.last_actions = day'),(ROOT/'joint_linear_tree.py','return targets'),
        (ROOT/'joint_neural.py','return {str(t):float(v) for t,v in zip(day.ticker,w)'),
        (OLD/'data/build_inputs.py',"verified=g.final_input_gate.str.startswith('INPUT_VERIFIED')"),
        (ROOT/'data/build_latest_effective_inputs.py',"src=OLD/'test_features_context.parquet'")]
    for path,needle in anchors:
        lines=path.read_text(encoding='utf-8').splitlines();matches=[i for i,line in enumerate(lines,1) if needle in line]
        assert matches,(path,needle)
        for number in matches:evidence.append({'path':str(path),'line':number,'text':lines[number-1].strip(),'sha256':sha(path)})
    write(OUT/'CODE_EVIDENCE.json',evidence)
    counts=lineage.groupby('input_absence_reason').agg(tickers=('ticker','size'),strategy_rows=('affected_strategy_rows','sum')).reset_index().to_dict('records')
    summary={'status':'EXISTING_INPUT_LINEAGE_REVIEW_COMPLETE','scope':'Only the 54 missing-identity fields in the saved 2026-09-22 last-date target table; no universe-rule reopening.',
        'signal_date':'2026-09-22','strategy_rows':54,'unique_tickers':45,'classifications':counts,
        'current_context_rows_for_affected_tickers':0,'all_rows_positive_current_weight_zero_target':True,
        'current_materialized_feature_tickers':int(lineage.current_materialized_feature_row.sum()),'materialized_feature_absent_tickers':lineage.loc[~lineage.current_materialized_feature_row,'ticker'].tolist(),
        'raw_target_dictionary_saved':False,'adapted_target_dictionary_saved':False,'standalone_order_object_saved':False,
        'zero_target_evidence':'Observed saved target_decisions weights are zero. Source joins holdings with validated targets and uses targets.get(ticker,0). Each affected ticker is absent from day features; saved policy implementations return day-ticker keys only. This supports a default-zero path, not a directly observed learned exit recommendation.',
        'missing_identity_evidence':'LAST_TEST_DATE_TARGETS left-joins quarter/cusip/new_buy_eligible from same-day context, so an old holding absent from that context keeps all three fields empty.',
        'cannot_infer':['UNKNOWN event publication gate does not prove the event was unpublished at the signal, a wrong quote, or economic ineligibility.',
            'No ticker/historical CUSIP in current saved candidate snapshot does not prove corporate nonexistence, untradability or disappearance from all 13F filings.',
            'Explicit model exit preference cannot be reconstructed from missing/defaulted zero targets without saved raw outputs.',
            'First consumed event field is a gate lineage field, not necessarily a fully verified timestamp of publication.',
            'No future execution-price observations were used to infer historical model input membership.'],
        'model_calls':0,'fit_calls':0,'replay_calls':0,'network_requests':0,'source_files_modified':0,
        'source_sha256':initial_hash}
    for p,h in initial_hash.items():assert sha(p)==h
    write(OUT/'INPUT_LINEAGE_SUMMARY.json',summary)
    report=['# 54条旧仓缺字段：已存输入溯源','',
        '54条记录对应45个ticker，均为2026-09-22已持有、目标权重记为0的行；这些ticker在当日已存预测context中均无行。报告没有重新运行模型或回放。','',
        '| 当前可观察分类 | ticker数 | 策略行数 |','|---|---:|---:|']
    for c in counts:report.append(f"| {c['input_absence_reason']} | {c['tickers']} | {c['strategy_rows']} |")
    report += ['',
        '37个ticker仍在当日2026Q2原候选账中，均有可计算的32特征、121会话历史及通过的版本检查。其R6状态统一为UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME，因此未进入仅接收INPUT_VERIFIED行的context。此状态说明证据未完成核证，不说明事件当时未公开，也不说明价格本身错误。','',
        '其余8个ticker为DOV、DTP、EXAS、GFS、HCA、HON、PFE、SLMT。当前候选快照既无这些ticker，也无其历史CUSIP匹配；这是快照事实，不升级为法律实体或普遍可交易资格判断。7个仍有9月22日物化特征，EXAS物化记录止于3月20日，且既存收据记录3月23日起生命周期不合格。EXAS外部来源在旧收据中为WEB_OFFICIAL_NO_LOCAL_HASH，本次未重新验证。DTP的既存普通股身份传输为US.DTE，应保留此别名说明。','',
        '缺字段的直接来源是finalize_suite.py把目标/旧持仓行，左连接到当日context的quarter、cusip和new_buy_eligible；找不到行就留下空值。不能把空值直接填成False。','',
        '未发现已持久化raw_target字典、adapted_target字典或独立订单对象快照。target_decisions保存的是经过目标校验后、对targets与holdings并集逐项记录的target_weight；不存在的目标键用targets.get(ticker,0)补0。模型适配器按当日day.ticker返回键，这45个ticker无当日特征行，因此源码支持缺省归零路径；原始模型输出没有逐项收据，不能将这54个零权重描述为模型明确学得的退出建议。线性/树策略的last_actions仅存内存，run_suite没有导出。','',
        '已有trades、diagnostics、positions、daily保存实际成交、异常/受阻、持仓和账户结果，可用于单独追踪退出是否实际发生；它们不能补回原始模型偏好。逐文件清单和列名见ARTIFACT_TRACE_INVENTORY.json，源码位置见CODE_EVIDENCE.json。','',
        'TICKER_INPUT_LINEAGE.csv列出45个ticker的当前/历史身份、门槛、物化特征、最后context日期及不可推断事项；MISSING54_INPUT_LINEAGE.csv保留原54行空字段，并追加溯源列，没有改写原报告。','']
    (OUT/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps({'status':summary['status'],'classifications':counts,'current_materialized_feature_tickers':44,'missing_feature_tickers':['EXAS'],'sources_unchanged':True},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
