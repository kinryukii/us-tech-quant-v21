"""All-result descriptive comparisons; never select/refit a configuration."""
from __future__ import annotations
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
from integrity import OLD, ROOT, read, write, sha, verify_freeze

def percent(value):
    return '失败/缺失' if pd.isna(value) else f'{100*float(value):.2f}%'

def pareto_flags(frame):
    result = pd.Series(False, index=frame.index)
    for _, block in frame.groupby(['year', 'risk', 'optimizer'], sort=False):
        valid = block.dropna(subset=['indicative_return', 'indicative_max_drawdown'])
        for index, row in valid.iterrows():
            dominates = ((valid.indicative_return >= row.indicative_return) &
                         (valid.indicative_max_drawdown >= row.indicative_max_drawdown) &
                         ((valid.indicative_return > row.indicative_return) |
                          (valid.indicative_max_drawdown > row.indicative_max_drawdown)))
            result.loc[index] = not bool(dominates.any())
    return result

def prediction_differences(year):
    old = pd.read_parquet(OLD / 'predictions' / f'evaluation_{year}' / 'streams.parquet')
    new = pd.read_parquet(ROOT / 'predictions' / f'evaluation_{year}' / 'streams.parquet')
    keys = ['signal_date', 'ticker']
    if not old[keys].equals(new[keys]):
        raise RuntimeError('OLD_NEW_FULL_PREDICTION_KEY_MISMATCH')
    pool = pd.read_parquet(OLD / 'data' / ('pre_panel.parquet' if year == 2025 else 'test_panel.parquet'),
                          columns=[*keys, 'new_buy_eligible'],
                          filters=[('signal_date', '>=', pd.Timestamp(f'{year}-01-01')),
                                   ('signal_date', '<', pd.Timestamp(f'{year+1}-01-01'))])
    allowed = old[keys].merge(pool, on=keys, how='left', validate='one_to_one').new_buy_eligible
    if allowed.isna().any():
        raise RuntimeError('MISSING_BUY_ELIGIBILITY_IN_ANALYSIS')
    rows = []
    for stream in [name for name in old.columns if name not in keys]:
        a, b = old[stream].to_numpy(float), new[stream].to_numpy(float)
        if not np.array_equal(np.isfinite(a), np.isfinite(b)):
            raise RuntimeError('INTERVENTION_CHANGED_DECLARED_FAILURE_MASK:' + stream)
        if not np.isfinite(a).all():
            rows.append({'year': year, 'stream_id': stream, 'status': 'FAILED_PRESERVED'})
            continue
        delta = b - a
        statistics = []
        for date, indices in old.loc[allowed].groupby('signal_date', sort=True).groups.items():
            idx = np.asarray(indices)
            tickers = old.loc[idx, 'ticker'].to_numpy(str)
            before = np.lexsort((tickers, -a[idx]))[:20]
            after = np.lexsort((tickers, -b[idx]))[:20]
            statistics.append({'old_top20_mean': float(a[idx][before].mean()),
                               'new_top20_mean': float(b[idx][after].mean()),
                               'old_above_10bp': int((a[idx][before] > .001).sum()),
                               'new_above_10bp': int((b[idx][after] > .001).sum()),
                               'top20_overlap': len(set(tickers[before]) & set(tickers[after])) / 20})
        stat = pd.DataFrame(statistics)
        rows.append({'year': year, 'stream_id': stream, 'status': 'AVAILABLE',
                     'rows': len(a), 'mean_mu_shift_bp': float(delta.mean()*10000),
                     'min_mu_shift_bp': float(delta.min()*10000),
                     'max_mu_shift_bp': float(delta.max()*10000),
                     'mean_top20_overlap': float(stat.top20_overlap.mean()),
                     'old_top20_mean_bp': float(stat.old_top20_mean.mean()*10000),
                     'new_top20_mean_bp': float(stat.new_top20_mean.mean()*10000),
                     'old_top20_mean_above_10bp': float(stat.old_above_10bp.mean()),
                     'new_top20_mean_above_10bp': float(stat.new_above_10bp.mean())})
    return pd.DataFrame(rows)

def main():
    verify_freeze()
    output = ROOT / 'results' / 'analysis'
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / 'COMPLETE.json'
    if receipt_path.exists():
        receipt = read(receipt_path)
        for name, digest in receipt['artifacts'].items():
            if sha(output / name) != digest:
                raise RuntimeError('PRESERVE_COMPLETED_ANALYSIS')
        print(receipt['status'], flush=True)
        return receipt
    new_parts, old_parts = [], []
    for year in [2025, 2026]:
        final = ROOT / 'results' / f'evaluation_{year}'
        complete = read(final / 'COMPLETE.json')
        if complete['declared'] != 8247:
            raise RuntimeError('YEAR_ROSTER_INCOMPLETE')
        audit = read(final / 'INDEPENDENT_AUDIT_COMPLETE.json')
        if audit['status'] != 'COMPLETE':
            raise RuntimeError('INDEPENDENT_ACCOUNT_AUDIT_REQUIRED')
        new_parts.append(pd.read_csv(final / 'ALL_PATHS.csv'))
        old_parts.append(pd.read_csv(OLD / 'results' / f'evaluation_{year}' / 'ALL_PATHS.csv'))
    new = pd.concat(new_parts, ignore_index=True)
    old = pd.concat(old_parts, ignore_index=True)
    new['participation_flag'] = np.where(new.indicative_return.isna(), 'FAILED',
                              np.where(new.mean_gross_exposure.eq(0), 'ALL_CASH',
                              np.where(new.mean_gross_exposure.lt(.01), 'NEAR_CASH_UNDER_1_PERCENT', 'PARTICIPATING')))
    new['replay_complete'] = new.research_status.isin(['REPLAY_COMPLETE', 'REPLAY_COMPLETE_WITH_APPROXIMATE_SOLVES'])
    new['result_sign'] = np.select([new.indicative_return.isna(), new.indicative_return.gt(0),
                                  new.indicative_return.lt(0)], ['FAILED_OR_UNRESOLVED', 'POSITIVE', 'NEGATIVE'], default='ZERO')
    new.to_csv(output / 'ALL_COMBINATIONS.csv', index=False)
    # Reuse tested pure-frame factorial contrasts; never call the old CLI/writers.
    if str(OLD) not in sys.path:
        sys.path.insert(1, str(OLD))
    from analyze_results import factor_main_effects, build_effects
    main_effects = factor_main_effects(new)
    model_pairs, interactions = build_effects(new)
    main_effects.to_csv(output / 'FACTOR_MAIN_EFFECTS.csv', index=False)
    model_pairs.to_csv(output / 'PAIRED_EFFECTS.csv', index=False)
    interactions.to_csv(output / 'INTERACTIONS.csv', index=False)
    numeric = ['indicative_return', 'indicative_max_drawdown', 'mean_gross_exposure',
               'total_fees', 'turnover', 'optimization_iteration_limit_decisions']
    old_subset = old[['path_id', 'year', *numeric]].rename(columns={name: 'old_' + name for name in numeric})
    paired = new.merge(old_subset, on=['path_id', 'year'], how='left', validate='one_to_one')
    for name in numeric:
        paired['delta_' + name] = paired[name] - paired['old_' + name]
    paired.to_csv(output / 'BEFORE_AFTER_ALL_PATHS.csv', index=False)
    # One fixed canonical risk supplies a readable table; every other cell remains above.
    canonical = paired.loc[paired.layer.eq('pto') & paired.risk.eq('ledoit_wolf') &
                           paired.optimizer.isin(['positive_equal', 'mean_variance'])].copy()
    canonical['stream_id'] = canonical.group + '__' + canonical.fusion
    canonical['pareto_in_this_risk_optimizer_cell'] = pareto_flags(canonical)
    canonical.to_csv(output / 'CANONICAL_MODEL_COMPARISON.csv', index=False)
    a2_rows = new.loc[new.group.eq('a2_reference'), ['year', 'risk', 'optimizer', *numeric]].rename(
        columns={name: 'a2_' + name for name in numeric})
    vs = new.loc[new.layer.eq('pto')].merge(a2_rows, on=['year', 'risk', 'optimizer'],
                                           how='left', validate='many_to_one')
    for name in numeric:
        vs['difference_vs_a2_' + name] = vs[name] - vs['a2_' + name]
    vs.to_csv(output / 'ALL_SAME_CONFIGURATION_VS_A2.csv', index=False)
    differences = pd.concat([prediction_differences(year) for year in [2025, 2026]], ignore_index=True)
    differences.to_csv(output / 'PREDICTION_INPUT_SHIFT.csv', index=False)
    # Marginal summaries are descriptive averages of configurations, never strategy curves.
    factors = []
    for dimension in ['group', 'fusion', 'risk', 'optimizer']:
        part = new.loc[new.layer.eq('pto')].groupby(['year', dimension], dropna=False).agg(
            declared_paths=('path_id', 'size'), available_paths=('indicative_return', 'count'),
            descriptive_mean_return=('indicative_return', 'mean'),
            descriptive_mean_drawdown=('indicative_max_drawdown', 'mean'),
            descriptive_mean_exposure=('mean_gross_exposure', 'mean'),
            descriptive_mean_fees=('total_fees', 'mean')).reset_index().rename(columns={dimension: 'member'})
        part['dimension'] = dimension
        factors.append(part)
    pd.concat(factors, ignore_index=True).to_csv(output / 'FACTOR_DESCRIPTIVE_COMPARISON.csv', index=False)
    count_rows = []
    for year, block in new.groupby('year'):
        available = block.indicative_return.notna()
        count_rows.append({'year': int(year), 'declared': len(block), 'available': int(available.sum()),
                           'failed': int((~available).sum()),
                           'positive': int(block.indicative_return.gt(0).sum()),
                           'negative': int(block.indicative_return.lt(0).sum()),
                           'zero': int(block.indicative_return.eq(0).sum()),
                           'near_cash': int(block.mean_gross_exposure.lt(.01).sum())})
    pd.DataFrame(count_rows).to_csv(output / 'RESULT_COUNTS.csv', index=False)
    report = ['# 共同校准基线修正：已有训练成果重测', '',
              '本批只干预共同μ基线，不新训练原有基础模型、融合或风险。A2仅新增时间合法的一日收益接口适配。2026已暴露，本结果是描述性敏感性评估，不证明泛化。', '',
              '原8194路径加52条A2一日μ参照及1条原A2分数共同账户参照，每年8247条；失败完整保留。4条RL账本输入和规则不变，经哈希验证复用。完整原池仍BLOCKED_DATA，价格仍为未认证股东总收益的研究坐标。', '',
              '## 完整覆盖', '', '| 年份 | 声明 | 可用 | 失败 | 正 | 负 | 零 | 平均敞口<1% |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in count_rows:
        report.append('| ' + ' | '.join(str(row[name]) for name in [
            'year', 'declared', 'available', 'failed', 'positive', 'negative', 'zero', 'near_cash']) + ' |')
    report += ['', '## 单成员与A2：相同LW风险、分别采用两种优化', '',
               '下表不是跨风险/优化平均策略。2025与2026复用不同原有训练阶段，不能把跨年差异归因于单一学习进步。A2行是原冻结A2评分经共同一日收益适配的参照。', '',
               '| 年份 | 预测器 | 优化 | 净收益 | 最大回撤 | 平均敞口 | 相对旧结果收益变化 |',
               '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    single_groups = list(read(OLD / 'models/final/FIT_STATUS.json')['fits'])
    names = {record['name'] for record in single_groups} | {'a2_reference'}
    for row in canonical.loc[canonical.group.isin(names)].itertuples():
        report.append(f'| {row.year} | {row.group} | {row.optimizer} | {percent(row.indicative_return)} | '
                      f'{percent(row.indicative_max_drawdown)} | {percent(row.mean_gross_exposure)} | '
                      f'{percent(row.delta_indicative_return)} |')
    report += ['', '## 原A2分数共同账户参照', '',
               '沿用旧2025H2参照的排名与每票4.75%上限规则，延伸到同全年/2026可用候选及共同账户。分数不当一天μ、不设10bp分数门槛；这不是Raw A2原生账户。', '',
               '| 年份 | 净收益 | 最大回撤 | 平均敞口 |',
               '| --- | ---: | ---: | ---: |']
    for row in new.loc[new.layer.eq('a2_raw_score_reference')].itertuples():
        report.append(f'| {row.year} | {percent(row.indicative_return)} | '
                      f'{percent(row.indicative_max_drawdown)} | {percent(row.mean_gross_exposure)} |')
    report += ['', '## 解释边界与完整文件', '',
               '现金是允许的决策。近零敞口的低回撤不作为选股能力证据；robust 0.5σ与CVaR线性尾损的既定惩罚可能压倒一日μ，与MV中同一数值并非同等保守程度。本批不根据新2026结果更换惩罚参数。', '',
               '非线性融合可能因校准输入平移改变排序；这是冻结融合的输入敏感性，不能称为重新学习的改善。完整校准斜率、基础模型非嵌套抽样、历史PIT及价格认证问题并未由截距修正消除。', '',
               '- ALL_COMBINATIONS.csv：全部正负、零和失败结果。',
               '- BEFORE_AFTER_ALL_PATHS.csv：全部同路径干预前后配对。',
               '- ALL_SAME_CONFIGURATION_VS_A2.csv：相同风险和优化下对比A2。',
               '- CANONICAL_MODEL_COMPARISON.csv：所有成员与融合的可读主表。',
               '- PREDICTION_INPUT_SHIFT.csv：排序、10bp准入与预测水平变化。',
               '- PAIRED_EFFECTS.csv / INTERACTIONS.csv：固定参考下配对与四格交互；缺必要单元的比较保留不可用原因。',
               '- FACTOR_DESCRIPTIVE_COMPARISON.csv：维度描述平均，不能视为真实组合。', '',
               '后续1/3/5/7/9年历史基线窗口在独立阶段检验；本批完成后不追加任何救结果的模型或参数。']
    (output / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    receipt = {'status': 'COMPLETE_FIXED_INTERVENTION_DESCRIPTIVE_ANALYSIS',
               'rows': len(new), 'fit_calls': 0, 'all_positive_negative_failures_included': True,
               'post_test_parameter_search': False, 'blind_test': False,
               'artifacts': {path.name: sha(path) for path in output.iterdir() if path.is_file()}}
    write(receipt_path, receipt)
    verify_freeze()
    print(receipt['status'], len(new), flush=True)
    return receipt

if __name__ == '__main__':
    main()
