"""Assemble sealed evidence; this script never fits, predicts, or replays."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'a2_top20_multimodel_selection_20260928_9231'
SCENARIOS = [(2025, 10), (2026, 5), (2026, 10), (2026, 25)]
LABELS = {
    'fusion_fixed_non_equal': '固定非等权',
    'fusion_learned_weights': 'OOF学习固定权重',
    'fusion_nonlinear_stacking': '非线性Stacking',
    'fusion_conditional_gate': '条件门控',
    'fusion_hgb_then_linear': 'HGB→线性修正',
    'fusion_linear_then_hgb': '线性→HGB修正',
    'fusion_target_decisions': '目标仓位融合',
    'joint_hgb': '原HGB对照',
    'ensemble_equal': '原等权对照',
    'ensemble_stacking': '原线性Stacking对照',
}
NAMES = list(LABELS)[:7]
CONTROLS = list(LABELS)[7:]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, (np.floating, float)): return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, (pd.Timestamp, Path)): return str(value)
    return value


def write(path, value):
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def pct(value):
    return f'{float(value)*100:.2f}%'


def bp(value):
    return 'NA' if pd.isna(value) else f'{float(value)*10000:.2f}'


def coverage():
    rows = [
        ('Ridge / Elastic Net / Logistic', '冻结基础专家', '三者参与七种协同；仍可原政策独立推理', 'values.py'),
        ('HGB / GBDT', '冻结核心专家', '参与七种协同；小HGB也作为固定元模型和残差层', 'values.py'),
        ('小型 MLP', '冻结神经专家', '参与七种协同；不增加基础神经网络训练', 'neural.py'),
        ('Q10 / Q50 / Q90', '冻结分位数政策', 'Q50参与六臂，Q10提供元层风险输入，Q90仍可原政策调用', 'values.py'),
        ('PCA / 因子 / Ledoit-Wolf', '冻结风险政策', '保留原风险层；本次不新增风险惩罚搜索', 'risk_aux.py'),
        ('成本和约束优化', '唯一账户决策引擎', '原离散联合分配和持仓保留规则；成本5/10/25bp固定场景', 'engine_v2.py'),
        ('聚类 / 异常检测', '冻结辅助诊断', '原frozen_auxiliary工件可用；不额外转成买卖信号', 'risk_aux.py'),
        ('强化学习', '冻结辅助政策', '原RL独立政策可用；本次不新增种子，也不作为六臂融合专家', 'neural.py'),
    ]
    return pd.DataFrame([dict(family=a, current_role=b, this_batch=c, reused_source=str(BASE/d))
                         for a,b,c,d in rows])


def main():
    if (ROOT / 'COMPLETE_MANIFEST.json').exists():
        raise RuntimeError('COMPLETED_BATCH_PRESERVED')
    meta = read(ROOT/'meta_artifacts/TRAIN_RECEIPT.json')
    gate = read(ROOT/'gate_artifacts/TRAIN_RECEIPT.json')
    assert meta['status'] == gate['status'] == 'PASS'
    assert meta['main_fit_calls'] == 8 and meta['closed_form_anchor_estimates'] == 2
    assert meta['test2026_rows_read'] == meta['old_model_fit_calls'] == meta['hyperparameter_search_trials'] == 0
    assert gate['fit_count'] == 2 and gate['optimizer_steps'] == 792 and gate['fit_2026_rows'] == 0
    assert all(f['label_end_max'] < f['cutoff_exclusive'] for f in meta['fits'])
    assert all(f['label_end_max'] < f['specification']['cutoff_exclusive'] for f in gate['stages'])
    old_hashes = read(ROOT/'OLD_SOURCE_SNAPSHOT.json')['hashes']
    assert all(sha(path) == expected for path, expected in old_hashes.items())
    write(ROOT/'ORIGINAL_INTEGRITY_VERIFICATION.json', dict(status='PASS', files=len(old_hashes), unchanged=True))
    rows = []; frozen_sets = []; replay_paths = []
    for year, cost in SCENARIOS:
        folder = ROOT/f'evaluation_{year}/cost_{cost}'
        complete = read(folder/'COMPLETE.json'); frozen = read(folder/'FROZEN_BEFORE_REPLAY.json')
        assert complete['policies'] == 7 and complete['fit_attempts'] == 0
        assert complete['sources_unchanged'] and frozen['roster'] == NAMES
        hashes = frozen['source_sha256']
        assert all(sha(path) == expected for path, expected in hashes.items())
        frozen_sets.append(hashes)
        for name in NAMES:
            done = read(folder/name/'DONE.json')
            assert done['certified_retrospective_return'] is None and not done['formal_performance']
            rows.append(dict(done, batch='new_cooperation', source_done=str(folder/name/'DONE.json'),
                             source_done_sha256=sha(folder/name/'DONE.json')))
            replay_paths.append(str(folder/name))
        for name in CONTROLS:
            path = BASE/f'evaluation_{year}/cost_{cost}'/name/'DONE.json'
            done = read(path)
            # Preserve original records and explicitly narrow their use here.
            done.update(price_gate_only_return=done.get('certified_retrospective_return'),
                        certified_retrospective_return=None, formal_performance=False,
                        metric_status='RESEARCH_ONLY_INHERITED_UNIVERSE_ACTION_AND_ARRIVAL_LIMITATIONS')
            rows.append(dict(done, batch='reused_frozen_control', source_done=str(path), source_done_sha256=sha(path)))
    common = set.intersection(*(set(d) for d in frozen_sets))
    assert all(len({d[path] for d in frozen_sets}) == 1 for path in common)
    comparison = pd.DataFrame(rows)
    assert len(comparison) == 40 and not comparison.duplicated(['year','cost_bps','policy']).any()
    comparison['method'] = comparison.policy.map(LABELS)
    comparison.to_csv(ROOT/'MODEL_COMPARISON.csv', index=False, encoding='utf-8-sig')
    coverage().to_csv(ROOT/'METHOD_COVERAGE.csv', index=False, encoding='utf-8-sig')
    ledger = read(ROOT/'INDEPENDENT_LEDGER_VERIFICATION.json')
    assert ledger['status'].startswith('PASS') and ledger['path_count'] == 28
    reconstruction_errors = {key:max(float(path['checks'].get(key,0.)) for path in ledger['paths'])
        for key in ['cash_rebuilt_from_trades_error','nav_rebuilt_from_positions_error','units_rebuilt_from_trades_error']}
    bridge = read(ROOT/'bridge/COMPLETE.json')
    assert bridge['status'].startswith('PASS') and bridge['paths'] == 14
    joined = read(ROOT/'bridge/LAST_SIGNAL_THREE_LAYER_COMPLETE.json')
    assert joined['status'] == 'PASS' and joined['paths'] == 14
    assert read(ROOT/'bridge/FINAL_REVIEW.json')['status'].startswith('PASS')
    assert read(ROOT/'selection/VERIFICATION.json')['status'].startswith('PASS')
    selections = [read(ROOT/f'selection/COMPLETE_{year}.json') for year in (2025,2026)]
    assert all(s['status'].startswith('PASS') and s['fit_attempts'] == 0 for s in selections)
    diagnostic = pd.read_csv(ROOT/'selection/aggregate.csv')
    assert len(diagnostic) == 40 and set(diagnostic.policy) == set(LABELS)
    assert not diagnostic.duplicated(['year','policy','subset']).any()
    assert set(diagnostic.subset) == {'complete_common_pool','incomplete_observable_only'}
    ic_days = {}
    for year in (2025,2026):
        daily = pd.concat([pd.read_parquet(ROOT/f'selection/daily_{year}.parquet'),
                           pd.read_parquet(ROOT/f'selection/controls_daily_{year}.parquet')])
        assert not daily.duplicated(['signal_date','policy']).any()
        for name, group in daily.groupby('policy'):
            complete = group.loc[group.complete_common_pool]
            ic_days[(year,name)] = int(np.isfinite(complete.observed_ic.to_numpy(float)).sum())
    pd.DataFrame([dict(year=y,policy=n,ic_available_days=count) for (y,n),count in ic_days.items()]).to_csv(
        ROOT/'IC_AVAILABILITY.csv', index=False, encoding='utf-8-sig')
    overlaps = []; overlap_sources = {}
    for year in (2025,2026):
        a_path = ROOT/f'selection/scores_{year}.parquet'
        b_path = BASE/f'acceptance_diagnostics/selection/scores_{year}.parquet'
        overlap_sources.update({str(p):sha(p) for p in (a_path,b_path)})
        columns = ['signal_date','ticker','reference_top20']
        a = pd.read_parquet(a_path, filters=[('policy','=','fusion_learned_weights')], columns=columns)
        b = pd.read_parquet(b_path, filters=[('policy','=','ensemble_stacking')], columns=columns)
        matched = a.merge(b, on=['signal_date','ticker'], validate='one_to_one', suffixes=('_new','_old'))
        assert len(matched) == len(a) == len(b)
        new_top = matched.reference_top20_new
        old_top = matched.reference_top20_old
        overlaps.append(dict(year=year,signal_days=matched.signal_date.nunique(),candidate_rows=len(matched),
            selected_rows=int(new_top.sum()),overlap_selected_rows=int((new_top&old_top).sum()),
            membership_disagreements=int((new_top!=old_top).sum()),
            overlap_fraction=float((new_top&old_top).sum()/new_top.sum()),
            state='current0_cash0.95_age0',scope='TOP20 membership only, all original available signal days'))
    write(ROOT/'NNLS_OLD_STACKING_OVERLAP.json', dict(status='PASS_READ_ONLY_FROZEN_COMPARISON',
        years=overlaps,input_sha256=overlap_sources,fit_calls=0,predict_calls=0,replay_calls=0))
    training_rows = []
    for fit in meta['fits']:
        training_rows.append({k: fit.get(k) for k in ['name','stage','rows','signal_first','signal_last','label_end_max','cutoff_exclusive','main_fit_calls','fit_seconds','artifact_sha256']})
    for fit in gate['stages']:
        training_rows.append(dict(name='fusion_conditional_gate',stage=fit['stage'],rows=fit['rows'],
            signal_first=fit['signal_first'],signal_last=fit['signal_last'],label_end_max=fit['label_end_max'],
            cutoff_exclusive=fit['specification']['cutoff_exclusive'],main_fit_calls=1,
            optimizer_steps=fit['optimizer_steps'],epochs=fit['epochs'],artifact_sha256=fit['model_sha256']))
    pd.DataFrame(training_rows).to_csv(ROOT/'TRAINING_SUMMARY.csv', index=False, encoding='utf-8-sig')
    weights = read(ROOT/'meta_artifacts/final_learned_weights_TRAIN_RECEIPT.json')['numerical_evidence']['normalized_weights']
    lines = ['# TOP20多模型协同实验结果', '',
        '七种固定设计已完成真实协同层训练、28条冻结账户回放、同期限固定状态排序诊断及14条主成本账户三层桥。基础模型没有重训，旧批次没有改写。本批次属于已观察历史研究，2026结果不构成新盲测或正式认证业绩。', '',
        '六类协同均已实际运行：固定非等权、OOF学习固定比例、非线性Stacking、条件门控、分层修正的两个方向、目标仓位融合。只有学习型协同层新增拟合：8次元层主拟合、2次门控训练、2次闭式锚系数估计；门控共792次更新。单一事前规格和种子，搜索次数0，2026拟合/标准化/早停/选模读取0。', '',
        'validation用2024 OOF 90,000行、成熟标签截至2024-12-31；final用2024+2025 OOF 180,000行、成熟标签截至2025-12-31。每年实际为6,000证券日，按3个参考状态和5个动作展开为90,000行；样本单位与数量分开记录。基础预测对应训练更早的年度工件。最终NNLS归一化比例按Ridge / EN / Logistic / HGB / Q50 / MLP依次为 '+', '.join(pct(w) for w in weights)+'。实际推理使用原系数；比例仅作贡献报告。零比例如实保留，没有强迫多样性或事后换权重。', '',
        '2025信号窗口01-02..12-29；2026信号01-02..09-22、终估09-24。共用原账户：100万美元初值、最多20只、主动单票目标不超过10%、总预算95%、下一开盘交易、ADV1%买入容量、缺输入持仓保留单位、期末不强制清仓。目标仓位融合先让六专家在同一真实账户状态给出目标，再由同一账户分配器执行。', '',
        '## 主成本账户回放', '',
        '下表为单边10bp后的指示性价格指数收益和最大回撤；新策略与原冻结对照的候选输入、执行窗口和账户规则相同。实际仓位会因各策略的连续决策而不同。2025同样未获得完整数据认证。估值门控缺失日仅计原账本certified_nav缺失，不证明其余日获得公司行动、供应商到达或全宇宙认证。', '',
        '| 方法 | 2025收益 | 2025最大回撤 | 2026收益 | 2026最大回撤 | 2026平均现金 | 2026交易费用USD | 2026估值门控缺失日 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name in LABELS:
        a = comparison.query('year==2025 and cost_bps==10 and policy==@name').iloc[0]
        b = comparison.query('year==2026 and cost_bps==10 and policy==@name').iloc[0]
        lines.append(f'| {LABELS[name]} | {pct(a.indicative_return)} | {pct(a.indicative_max_drawdown)} | {pct(b.indicative_return)} | {pct(b.indicative_max_drawdown)} | {pct(b.mean_cash_weight)} | {b.total_cost_dollars:,.2f} | {int(b.uncertified_valuation_days)} |')
    lines += ['',
        '固定非等权在2026回放较强，但2025收益低于原HGB；两种分层修正在2025获得较高账户收益，2026优势却明显减弱，不能把验证年高收益称为稳定提升。门控在2026的账户收益低于HGB，同时回撤和交易费用更低，说明取舍并不限于收益排序。上述是记录中的表现差异，未将现金或费用单独加回进行虚构反事实归因。']
    lines += ['', '## 固定参考状态选股检验', '',
        '统一空仓状态(单票0、现金95%、年龄0)，分数为5%动作相对0动作的条件偏好。所有方法面对同日同候选集合，先排序再标明未来标签缺失；不扫描持有期限。这些分数不是原生独立收益预测，也不是实际账户当日决策。TOP20简单检验为每票4.75%，下一开盘到再下一开盘，按投入金额扣往返20bp，各期独立无复利。', '',
        '主比较只使用原价格门控下完整共同集合：2025为245/248信号日，2026为88/181信号日。该“完整”仍只是已有特征子池内可计算，不能等同全13F宇宙认证。不完整或冲突日保留原排名，单列诊断。', '',
        'IC只对各方法分数与标签均可定义的日子求均值；常数分数导致的未定义IC不补零。括号内给出实际IC日数。本批所有方法的有效IC日均与共同完整日一致：2025为245日、2026为88日；TOP20-rest及简单净贡献也以这些共同日期计算。', '',
        '| 方法 | 2025 IC(日数) | 2025 TOP20-rest bp | 2025单期净bp | 2026 IC(日数) | 2026 TOP20-rest bp | 2026单期净bp |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name in LABELS:
        pairs = []
        for year in (2025,2026):
            part=diagnostic.loc[diagnostic.year.eq(year)&diagnostic.policy.eq(name)&diagnostic.subset.eq('complete_common_pool')]
            assert len(part)==1
            r=part.iloc[0]
            assert int(r.signal_days)==(245 if year==2025 else 88)
            ic = 'NA' if pd.isna(r.mean_ic) else f'{r.mean_ic:.4f}'
            pairs += [f'{ic}({ic_days[(year,name)]})', bp(r.mean_top20_minus_rest), bp(r.mean_period_simple_net)]
        lines.append('| '+LABELS[name]+' | '+' | '.join(pairs)+' |')
    lines += ['',
        f"NNLS与旧线性Stacking在固定参考状态的TOP20成员重合率：2025为{pct(overlaps[0]['overlap_fraction'])}（{overlaps[0]['overlap_selected_rows']}/{overlaps[0]['selected_rows']}入选证券日），2026为{pct(overlaps[1]['overlap_fraction'])}（{overlaps[1]['overlap_selected_rows']}/{overlaps[1]['selected_rows']}），2026全部181信号日成员一致。此项只比较TOP20成员，不声称全排序、五动作分数或真实账户政策完全相同；新增求解器名称不等于新增选股多样性。"]
    lines += ['', '非线性Stacking与目标仓位融合存在大量并列；并列按事前固定ticker升序决胜，精确TOP20序号不等于模型能够区分这些股票。下表给出评分的实际分辨率，完整统计在aggregate.csv。', '',
        '| 年份 | 方法 | 平均有并列证券占比 | 平均不同分数数 | 平均第20位同分人数 |',
        '| --- | --- | ---: | ---: | ---: |']
    for year in (2025,2026):
        for name in ('fusion_nonlinear_stacking','fusion_target_decisions'):
            r = diagnostic.loc[diagnostic.year.eq(year)&diagnostic.policy.eq(name)&diagnostic.subset.eq('complete_common_pool')].iloc[0]
            lines.append(f'| {year} | {LABELS[name]} | {pct(r.mean_tied_security_fraction)} | {r.mean_score_unique_count:.2f} | {r.mean_boundary_tie_count:.2f} |')
    lines += ['', '账户累计收益与单期排序净贡献不能互换：前者包含连续持仓、卖出、现金、容量、资格及费用；后者只检查固定状态排序，而且只在共同完整日作主比较。结果没有触发新模型、种子、比例或惩罚搜索，也没有据2026选冠军。', '',
        '## 固定成本压力', '',
        '三个成本场景分别完整重放同一冻结政策；成本改变净值与后续持仓状态，因此不能简单把累计费用加回去冒充无成本反事实。', '',
        '| 新协同方法 | 2026单边5bp收益 | 10bp收益 | 25bp收益 |',
        '| --- | ---: | ---: | ---: |']
    for name in NAMES:
        values = [pct(comparison.loc[comparison.year.eq(2026)&comparison.cost_bps.eq(cost)&comparison.policy.eq(name),'indicative_return'].iloc[0]) for cost in (5,10,25)]
        lines.append('| '+LABELS[name]+' | '+' | '.join(values)+' |')
    lines += ['', '## 三层输出与可解释范围', '',
        'selection/保存固定参考榜单、数值分数、六输入rank与分歧、贡献/修正和标签状态；evaluation_*/cost_*/保存实际账户的目标、现金、保留预算、交易和价格标记；bridge/将真实账户分数、目标、成交及持仓按同一证券和信号连接。bridge/LAST_SIGNAL_THREE_LAYER.csv为两年七种策略的紧凑末信号表，ALL版本保存未筛选全榜；完整历史保留在Parquet。', '',
        '末信号的下一开盘成交后状态是2025-12-30 / 2026-09-23；终估为2025-12-31 / 2026-09-24，另外保存在TERMINAL_ACCOUNT.csv与TERMINAL_POSITIONS.parquet，二者不混用。', '',
        '固定、NNLS与门控保存可相加贡献；两层设计保存锚点与残差。HGB→线性的六基臂列只覆盖六rank项与锚，完整分数还需其余五个下行/状态/动作输入的残差项，逐行用全11项核验。非线性单臂置零敏感性不相加、也不是因果归因。目标融合保存六专家目标及混合贡献。零仓位若没有记录具体绑定约束，仍标UNKNOWN_OPTIMIZER_ACTION_COMPETITION_OR_RISK_BINDING；不会把未下单说成成交拒绝。', '',
        '线性→HGB的旧线性锚在同一meta OOF样本上学得，残差层没有额外做嵌套折外；因此不宣称其提供新的独立训练证据。门控权重变化已超过数值误差，但这只证明规则确实随已知状态变化，不能直接证明经济优势。', '',
        '## 数据认证和验收边界', '',
        '最近13F的季度生效时钟核对通过，Q2重报2026-09-10生效后9个信号日仍沿用初始成员版本，这一合规缺口继承为UNKNOWN。2026原全池111,868候选证券日中，只有62,393行在原可买特征子池，47,271行资格未知、2,204行已证不合格；没有一个原全池完整日。', '',
        '原pre2026成熟标签312,707行可从同一价格文件精确重建，不能据此证明公司行动、历史供应商到达时钟或股东回报正确。已知原价格警告/未解释大跳窗口已与实际监督样本和OOF特征窗口重叠，但这不等于数值错误或所有特征改变。本次未静默修输入或重训基础模型。GLW2026-02-26/27输入和标签冲突仍标注。旧final风险窗口直接消费WOLF2025事件，validation窗口不消费该事件；WOLF不在本次复用的六臂监督特征/标签中，历史修订到达时间仍UNKNOWN。', '',
        '已完成代码/阶段/成熟标签/源哈希检查、推理fit=0、28条独立现金/持仓/费用/NAV重建及主成本桥接对账。独立重建最大绝对误差为：现金 '+f"{reconstruction_errors['cash_rebuilt_from_trades_error']:.3g} USD，NAV {reconstruction_errors['nav_rebuilt_from_positions_error']:.3g} USD，单位 {reconstruction_errors['units_rebuilt_from_trades_error']:.3g}"+'。完整历史到达时间、全池身份和公司行动认证仍未完成，所以formal_performance=false、certified_retrospective_return=null。', '',
        '## 交付入口', '',
        '- MODEL_COMPARISON.csv：28条新回放与12条原对照引用，含原DONE路径及SHA256。',
        '- TRAINING_SUMMARY.csv / METHOD_COVERAGE.csv：训练边界、拟合预算与原方法保留定位。',
        '- selection/aggregate.csv、scores_*.parquet、daily_*.csv：选股诊断及完整/不完整分列。',
        '- bridge/：实际账户三层输出、零目标/未成交原因及价格状态。',
        '- INDEPENDENT_LEDGER_VERIFICATION.json：28条独立账本检查；COMPLETE_MANIFEST.json：最终封口。', '']
    (ROOT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    readme = ['# 阅读顺序', '', '先看 REPORT.md 的主成本和同日排序表，再用 MODEL_COMPARISON.csv 核对成本场景。', '',
              '榜单的固定参考状态与账户真实状态分开保存。要追某股票为何未买、为何成交或为何仍持有，查看 bridge/ 最后信号CSV或对应完整历史Parquet，再按信号日期回查 evaluation 的十种原始账本。', '',
              '原模型族都继续可用，METHOD_COVERAGE.csv 给出定位。此次只新增协同层和薄推理适配；基础训练系统、OOF、账户引擎直接复用。', '',
              '模型已训练、回放与内部对账已完成。完整数据认证尚未完成，所有业绩为继承限制下的研究诊断。', '']
    (ROOT/'READING_GUIDE.md').write_text('\n'.join(readme),encoding='utf-8')
    trace_files = [path for path in ROOT.rglob('*') if path.is_file()
                   and ('_interrupted' in path.parts or '.partial.' in path.name)]
    outputs = {str(path.relative_to(ROOT)):sha(path) for path in ROOT.rglob('*') if path.is_file()
               and '__pycache__' not in path.parts and '.pytest_cache' not in path.parts
               and '_interrupted' not in path.parts and '_assembly' not in path.parts
               and '.partial.' not in path.name
               and path.suffix not in ['.log','.pyc'] and path.name != 'COMPLETE_MANIFEST.json'}
    manifest = dict(status='PASS_COMPLETE_RESEARCH_BATCH', created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        designs=7, families=6, scenarios=4, replay_paths=28, reused_control_rows=12,
        new_meta_main_fit_calls=8, gate_trainings=2, gate_optimizer_steps=792, closed_form_anchor_estimates=2,
        old_base_refits=0, training_2026_rows=0, hyperparameter_search_trials=0,
        evaluation_fit_attempts=0, original_snapshot_files=len(old_hashes), original_snapshot_unchanged=True,
        independent_ledger_paths=28, bridge_paths=14, selection_years=[2025,2026],
        formal_performance=False, new_blind_test=False, full_13f_universe_certified=False,
        completed_work='All predeclared fits, frozen replays, fixed-state ranking diagnostics, account bridges, and internal checks.',
        outstanding_data_certification='Inherited identity, universe/amendment version, corporate action and historical vendor arrival evidence gaps.',
        output_sha256=outputs,
        preserved_intermediate_trace_sha256={str(path.relative_to(ROOT)):sha(path) for path in trace_files},
        intermediate_trace_is_not_accepted_result=True)
    write(ROOT/'COMPLETE_MANIFEST.json', manifest)
    print(json.dumps(dict(status=manifest['status'],outputs=len(outputs),replay_paths=28),ensure_ascii=False))


if __name__ == '__main__':
    main()
