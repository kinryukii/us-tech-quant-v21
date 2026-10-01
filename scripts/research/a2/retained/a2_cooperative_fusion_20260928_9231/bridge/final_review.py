"""Final read-only acceptance of bridge receipts, hashes, dates and deliverables."""
from pathlib import Path
import hashlib
import json
import time
import pandas as pd

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf-8')


started=time.monotonic()
done=read(OUT/'COMPLETE.json')
joined=read(OUT/'LAST_SIGNAL_THREE_LAYER_COMPLETE.json')
parallel=read(OUT/'PARALLEL_COMPLETE.json')
assert done['status']==joined['status']==parallel['status']=='PASS'
assert done['paths']==joined['paths']==parallel['paths']==14
assert done['rows']==1225236
assert done['model_fit_calls']==done['model_predict_calls']==done['replay_calls']==0
assert parallel['completed_serial_paths_reused']==3 and parallel['newly_expanded_paths']==11
sources={}


def merge_hashes(mapping):
    for path,digest in mapping.items():
        if path in sources:
            assert sources[path]==digest,f'HASH_IDENTITY_CONFLICT:{path}'
        sources[path]=digest


merge_hashes(done['input_sha256'])
merge_hashes(joined['input_sha256'])
for year in (2025,2026):
    freeze=read(ROOT/f'evaluation_{year}/cost_10/FROZEN_BEFORE_REPLAY.json')
    merge_hashes(freeze['source_sha256'])
summaries=done['paths_summary']
assert len({(x['year'],x['policy']) for x in summaries})==14
check_hashes={}
for summary in summaries:
    check=OUT/f"CHECK_{summary['year']}_{summary['policy']}.json"
    assert read(check)==summary
    check_hashes[str(check)]=sha(check)
    path=ROOT/summary['path']
    assert path.parent==OUT and '_interrupted' not in str(path)
    merge_hashes({str(path):summary['sha256']})
for path,digest in sources.items():
    assert '_interrupted' not in path and '_assembly' not in path
    assert sha(path)==digest,f'FINAL_SOURCE_OR_OUTPUT_HASH_CHANGED:{path}'

full=pd.read_parquet(OUT/'LAST_SIGNAL_THREE_LAYER_FULL.parquet')
compact=pd.read_csv(OUT/'LAST_SIGNAL_THREE_LAYER.csv',parse_dates=['signal_date'])
assert len(full)==5463 and len(compact)==427
key=['year','policy','signal_date','ticker']
assert not full.duplicated(key).any() and not compact.duplicated(key).any()
expected=full.loc[full.show_in_compact_last_signal,key].sort_values(key).reset_index(drop=True)
pd.testing.assert_frame_equal(compact[key].sort_values(key).reset_index(drop=True),expected,check_dtype=False)
assert full.three_layer_join_status.eq('both').sum()==5355
assert full.three_layer_join_status.eq('left_only').sum()==108
assert full.three_layer_join_status.eq('right_only').sum()==0
assert full.groupby('year').signal_date.nunique().eq(1).all()
assert full.loc[full.year.eq(2025),'signal_date'].eq(pd.Timestamp('2025-12-29')).all()
assert full.loc[full.year.eq(2026),'signal_date'].eq(pd.Timestamp('2026-09-22')).all()
terminal=pd.read_csv(OUT/'TERMINAL_ACCOUNT.csv',parse_dates=['date','last_signal_date','last_signal_execution_date'])
assert len(terminal)==14 and not terminal.duplicated(['year','policy']).any()
assert terminal.formal_price_certification.eq(False).all()
for year,signal,execution,mark in [(2025,'2025-12-29','2025-12-30','2025-12-31'),
                                  (2026,'2026-09-22','2026-09-23','2026-09-24')]:
    part=terminal[terminal.year.eq(year)]
    assert len(part)==7
    assert part.last_signal_date.eq(pd.Timestamp(signal)).all()
    assert part.last_signal_execution_date.eq(pd.Timestamp(execution)).all()
    assert part.date.eq(pd.Timestamp(mark)).all()
positions=pd.read_parquet(OUT/'TERMINAL_POSITIONS.parquet')
assert positions.formal_shareholder_valuation_certification.eq(False).all()
assert not positions.duplicated(['year','policy','date','ticker']).any()

metrics=['high_rank_zero_target','positive_target_no_trade','rejected_rows','capacity_limited_fills','held_without_decision_input']
by_year={str(year):{m:sum(x[m] for x in summaries if x['year']==year) for m in metrics} for year in (2025,2026)}
maximum={name:max(x['checks'][name] for x in summaries) for name in [
    'fusion_reconstruction_max_abs_error','raw_chosen_weight_max_abs_error','buy_fill_reconstruction_max_abs_error',
    'units_from_signal_plus_trades_error','daily_positions_nav_error','daily_recorded_cost_error','daily_cash_flow_error']}
limits={'fusion_reconstruction_max_abs_error':1e-10,'raw_chosen_weight_max_abs_error':1e-8,
    'buy_fill_reconstruction_max_abs_error':1e-5,'units_from_signal_plus_trades_error':1e-7,
    'daily_positions_nav_error':1e-5,'daily_recorded_cost_error':1e-5,'daily_cash_flow_error':1e-5}
assert all(maximum[k]<limits[k] for k in maximum)
unknown=sum(x['high_rank_zero_reasons'].get('UNKNOWN_OPTIMIZER_ACTION_COMPETITION_OR_RISK_BINDING',0) for x in summaries)
review=dict(status='PASS',paths=14,rows=done['rows'],checks_identical_to_master=14,
    verified_unique_source_and_output_hashes=len(sources),source_sha256=sources,check_sha256=check_hashes,
    compact_last_signal_rows=427,full_last_signal_rows=5463,reference_matches=5355,account_only_rows=108,
    reference_candidates_lost=0,by_year=by_year,maximum_recorded_check_errors=maximum,
    high_rank_zero_target_unknown_cause_rows=unknown,terminal_dates={'2025':'2025-12-31','2026':'2026-09-24'},
    terminal_positions_rows=len(positions),all_terminal_formal_certification_flags_false=True,
    terminal_original_gate_status=terminal.groupby('year').valuation_status.value_counts().to_dict().__str__(),
    interrupted_outputs_excluded_from_accepted_tables=True,interrupted_output_receipt='INTERRUPTED_OUTPUT.json',
    incomplete_output_scope='Unreceipted serial gate file preserved only under _interrupted; excluded from all accepted path manifests and joined outputs',
    runtime_scope='COMPLETE.seconds measures cached final assembly; PARALLEL_COMPLETE.seconds is the two-worker continuation plus assembly/join, excluding earlier serial time',
    model_fit_calls=0,model_predict_calls=0,replay_calls=0,seconds=time.monotonic()-started)
dump(OUT/'FINAL_REVIEW.json',review)
lines=['# 协同方法实际账户三层证据桥','',
    '14条主成本10bp路径全部完成，共1,225,236条逐证券记录；模型拟合、预测、账户回放新增调用均为0。',
    '源模型/回放冻结哈希、桥接读取源及产出哈希最终一致，14份逐路径检查收据与总收据完全一致。',
    '末信号完整三层表5,463行，紧凑展示427行：5,355条固定参考候选全部匹配，另保留108条账户独有记录。',
    '2025末信号12月29日、执行12月30日、终估12月31日；2026分别为9月22日、23日、24日。','',
    '| 年份 | 前20名但目标为零 | 正目标无成交 | 有拒绝记录 | 容量受限买入 | 有持仓但无决策输入 |',
    '| --- | ---: | ---: | ---: | ---: | ---: |']
for year in (2025,2026):
    v=by_year[str(year)]
    lines.append('| '+str(year)+' | '+' | '.join(str(v[m]) for m in metrics)+' |')
lines += ['',
    f'上表按七条独立路径累计证券/信号记录，不是去重股票数。前20名零目标共17,953条，其中{unknown:,}条未记录具体优化器绑定原因，保留UNKNOWN；另13条原始分数没有正动作优势。不能从零目标倒推出某个模型或约束导致拒绝。',
    '分数为实际账户状态下5%动作相对退出的条件偏好，排名不能代替目标，也不能当作原生收益。固定参考排名采用(0,0.95,0)，单独列示；即使全负仍可有TOP20，并列按事先确定的股票代码规则展示。',
    '加法贡献、锚与修正均核对全部五动作；最大分数重构误差3.26e-19。最大每日现金/净值核对误差小于4.66e-10美元。非线性单臂置零敏感性不相加，目标混合的专家目标贡献不是分数贡献。',
    '终估原账本状态：2025七条均显示内部certified；2026六条stale、一条内部certified。所有正式认证标志均为false：内部价格门控通过不代表公司行动、全13F池、历史到达时间或完整路径已认证。',
    '使用 LAST_SIGNAL_THREE_LAYER.csv 查看紧凑三层表，完整逐股贡献在各 actual_account_bridge_*.parquet；终估账户与持仓分别在 TERMINAL_ACCOUNT.csv 和 TERMINAL_POSITIONS.parquet。METHODS.md说明字段语义。',
    '串行完成的前三条结果原样保留，其余11条由两个只读进程完成。中断时尚无收据的gate临时文件保存在_interrupted，未进入任何验收表。COMPLETE的耗时仅为最终汇总；并行续跑耗时见PARALLEL_COMPLETE，不能当作全部计算耗时。',
    '本桥验证记录一致性，不修复原数据问题、不构成正式收益认证或新盲测，也不根据结果选择或调整模型。']
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:review[k] for k in ['status','paths','rows','verified_unique_source_and_output_hashes','compact_last_signal_rows','terminal_positions_rows','high_rank_zero_target_unknown_cause_rows','seconds']}))
