"""Interpret the completed frozen grid; never fit, select deployment, or replay."""
from __future__ import annotations
import sys, time, json
from pathlib import Path
from datetime import datetime, timezone
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from common import sha, write, clean, PROVIDERS, COALITIONS, FUSIONS, RISKS, OPTIMIZERS, forecasts, strategies
from freeze_batch import validate_global_freeze

YEARS = [2025, 2026]
METRICS = ['net_return', 'max_drawdown', 'mean_gross_exposure', 'total_fees']
SOURCE_SHA = {}


def load(relative, **kwargs):
    path = ROOT / relative
    before = sha(path)
    result = pd.read_csv(path, **kwargs)
    assert before == sha(path), 'SOURCE_CHANGED_DURING_READ:' + relative
    SOURCE_SHA[relative] = before
    return result


def signs(values):
    values = np.asarray(values, float)
    return dict(positive=int((values > 0).sum()), negative=int((values < 0).sum()),
                zero=int((values == 0).sum()), nonfinite=int((~np.isfinite(values)).sum()))


def summary(frame):
    return dict(cells=len(frame), return_signs=signs(frame.net_return), no_trade_paths=int(frame.trades.eq(0).sum()),
                **{metric: dict(mean=float(frame[metric].mean()), min=float(frame[metric].min()), max=float(frame[metric].max()))
                   for metric in METRICS})


def contrast(left, right):
    merged = left.merge(right, on=['risk', 'optimizer'], suffixes=('_left', '_right'), validate='one_to_one')
    assert len(merged) == 30
    delta = {metric: merged[metric + '_left'] - merged[metric + '_right'] for metric in METRICS}
    return dict(matched_cells=len(merged), delta_return_signs=signs(delta['net_return']),
                **{'delta_' + metric: dict(mean=float(values.mean()), min=float(values.min()), max=float(values.max()))
                   for metric, values in delta.items()},
                same_cash_path_cells=int(merged.trades_left.eq(0).mul(merged.trades_right.eq(0)).sum()))


def wait_reports():
    for _ in range(18):
        method = ROOT / 'report/ANALYSIS_METHOD.json'
        final = ROOT / 'report/ALL_PTO_RESULTS.csv'
        if method.is_file() and final.is_file():
            try:
                data = json.loads(method.read_text(encoding='utf-8'))
                if data.get('status') == 'DESCRIPTIVE_FIXED_GRID':
                    return
            except json.JSONDecodeError:
                pass
        print('Waiting <=20 seconds for final two-year statistics sentinel', flush=True)
        time.sleep(20)
    raise RuntimeError('FINAL_TWO_YEAR_ANALYSIS_NOT_READY')


def pct(value):
    return f'{100 * value:.2f}%'


def pp(value):
    return f'{100 * value:+.2f}'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def main():
    started = time.perf_counter()
    frozen = validate_global_freeze()
    SOURCE_SHA['GLOBAL_FREEZE.json'] = sha(ROOT / 'GLOBAL_FREEZE.json')
    SOURCE_SHA['comparison_analysis.py'] = sha(ROOT / 'comparison_analysis.py')
    data = {'created_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'AFFINE research accounts; provided inputs only; original complete pool formal BLOCKED; previously exposed, nonblind',
            'fit_calls': 0, 'replay_calls': 0, 'model_selection_performed': False, 'candidate_expansion': False,
            'statistical_significance_claimed': False, 'causal_effect_claimed': False,
            'shareholder_total_return_claimed': False, 'window_comparability': '2025 and partial-year 2026 have different lengths; terminal returns are not annualized',
            'sign_count_rule': 'exact sign of saved result, including exact zero; path count is not independent sample N',
            'years': {}}
    roster = pd.DataFrame(strategies())
    wanted = set(roster.strategy_id)
    primary = {}
    columns = ['strategy_id','forecast_id','coalition','fusion','risk','optimizer','route','year','status',
               'net_return','max_drawdown','mean_gross_exposure','total_fees','trades',
               'optimizer_approx_unconverged_days','target_blend_unconverged_member_days']
    for year in YEARS:
        frame = load(f'evaluation_{year}/comparison.csv', usecols=columns)
        assert len(frame) == 5053 and frame.strategy_id.is_unique and set(frame.strategy_id) == wanted
        assert frame.status.eq('REPLAY_COMPLETE').all() and np.isfinite(frame[METRICS].to_numpy()).all()
        primary[year] = frame
        base = frame.loc[frame.route.eq('prediction_fusion') & frame.optimizer.isin(OPTIMIZERS)]
        assert len(base) == 4560
        y = {'all_paths': summary(frame), 'prediction_grid': summary(base), 'singles': {}, 'fusion_within_cohort': {},
             'risk': {}, 'optimizer': {}, 'target_vs_convex': {}}
        for provider in PROVIDERS:
            rows = base.loc[base.forecast_id.eq('single__' + provider)]
            assert len(rows) == 30
            y['singles'][provider] = summary(rows)
        for group in COALITIONS:
            equal = base.loc[base.forecast_id.eq(group + '__equal')]
            y['fusion_within_cohort'][group] = {method: contrast(base.loc[base.forecast_id.eq(group + '__' + method)], equal)
                                               for method in FUSIONS if method != 'equal'}
            target = frame.loc[frame.route.eq('target_fusion') & frame.coalition.eq(group) & frame.optimizer.isin(OPTIMIZERS)]
            y['target_vs_convex'][group] = contrast(target, base.loc[base.forecast_id.eq(group + '__convex')])
        for risk in RISKS:
            y['risk'][risk] = summary(base.loc[base.risk.eq(risk)])
        for optimizer in OPTIMIZERS:
            y['optimizer'][optimizer] = summary(base.loc[base.optimizer.eq(optimizer)])
        data['years'][str(year)] = y
        print(json.dumps(dict(year=year, primary_rows=len(frame), return_signs=y['all_paths']['return_signs'],
                              no_trade_paths=y['all_paths']['no_trade_paths'])), flush=True)

    wait_reports()
    allrows = load('report/ALL_PTO_RESULTS.csv', usecols=columns)
    assert len(allrows) == 10106 and not allrows[['year','strategy_id']].duplicated().any()
    for year in YEARS:
        saved = primary[year].set_index('strategy_id').sort_index()
        reported = allrows.loc[allrows.year.eq(year)].set_index('strategy_id').sort_index()
        assert saved.index.equals(reported.index), 'FINAL_ALL_RESULTS_ID_MISMATCH'
        numeric = saved.select_dtypes(include=[np.number]).columns
        for column in numeric:
            assert np.allclose(saved[column], reported[column], rtol=2e-15, atol=1e-13), 'FINAL_ALL_RESULTS_NUMERIC_MISMATCH:' + column
        for column in saved.columns.difference(numeric):
            assert saved[column].fillna('none').astype(str).equals(reported[column].fillna('none').astype(str)), 'FINAL_ALL_RESULTS_METADATA_MISMATCH:' + column
        y = data['years'][str(year)]
        y['primary_vs_final_csv_max_errors'] = {column: float(np.abs(saved[column] - reported[column]).max()) for column in numeric}
        pairs = load(f'report/matched_dimension_comparisons_{year}.csv',
                     usecols=lambda c: c not in ['left_ids_json','right_ids_json'])
        conditional = load(f'report/fusion_risk_conditional_comparisons_{year}.csv',
                           usecols=lambda c: c not in ['left_ids_json','right_ids_json'])
        assert len(pairs) == 634 and len(conditional) == 1100
        assert pairs.complete_matched_grid.all() and conditional.complete_matched_grid.all()
        y['matched_summary'] = {kind: {'comparisons': len(part), 'mean_delta_return_signs': signs(part.delta_net_return),
            'delta_return_range': [float(part.delta_net_return.min()), float(part.delta_net_return.max())],
            'valid_return_days': sorted(part.days.unique().tolist())} for kind, part in pairs.groupby('comparison')}
        y['risk_pairs'] = pairs.loc[pairs.comparison.eq('risk')].to_dict('records')
        y['optimizer_pairs'] = pairs.loc[pairs.comparison.eq('optimizer')].to_dict('records')
        y['target_pairs'] = pairs.loc[pairs.comparison.eq('target_vs_prediction_fusion')].to_dict('records')
        y['fusion_method_across_fixed_cohorts'] = {}
        for method in [m for m in FUSIONS if m != 'equal']:
            part = pairs.loc[pairs.comparison.eq('fusion_within_fixed_members') & pairs.left.eq(method)]
            assert len(part) == 11
            y['fusion_method_across_fixed_cohorts'][method] = {'cohorts': 11, 'cohort_mean_delta_signs': signs(part.delta_net_return),
                **{key: float(part[key].mean()) for key in ['delta_net_return','delta_max_drawdown','delta_mean_gross_exposure','delta_total_fees']}}
        y['conditional_fusion_signs'] = signs(conditional.delta_net_return)
        y['fusion_risk_sign_switches'] = []
        for (group, method), part in conditional.groupby(['coalition','left']):
            if part.delta_net_return.min() < 0 < part.delta_net_return.max():
                y['fusion_risk_sign_switches'].append({'coalition': group, 'method': method,
                    'conditional_delta_return_min': float(part.delta_net_return.min()),
                    'conditional_delta_return_max': float(part.delta_net_return.max())})
        y['interaction_amplitudes'] = {}
        for metric in ['net_return','max_drawdown','mean_gross_exposure','mean_daily_log_return']:
            factors = load(f'report/factor_interactions_{year}_{metric}.csv')
            assert len(factors) == 4560 and not factors[['forecast_id','risk','optimizer']].duplicated().any()
            y['interaction_amplitudes'][metric] = {}
            for key in ['forecast_risk_interaction','forecast_optimizer_interaction','risk_optimizer_interaction','three_way_interaction']:
                vals = factors[key].to_numpy(float)
                idx = int(np.abs(vals).argmax())
                example = factors.iloc[idx]
                y['interaction_amplitudes'][metric][key] = {'mean_abs': float(np.abs(vals).mean()),
                    'rms': float(np.sqrt(np.mean(vals ** 2))), 'max_abs': float(np.abs(vals).max()),
                    'illustrative_largest_absolute_cell': {c: example[c] for c in ['forecast_id','risk','optimizer',key,'observed']}}
        adjusted = load(f'report/optimization_vs_fixed_gross_{year}.csv', usecols=lambda c: not c.startswith('ledger_sha256'))
        assert len(adjusted) == 4890 and adjusted.strategy_id.is_unique
        y['optimization_vs_budget_control'] = {route: {optimizer: {'cells': len(part), 'delta_return_signs': signs(part.delta_net_return),
            **{key: float(part[key].mean()) for key in ['delta_net_return','delta_max_drawdown','delta_mean_gross_exposure','delta_total_fees']}}
            for optimizer, part in byroute.groupby('optimizer')} for route, byroute in adjusted.groupby('route')}

        # Named contrasts were chosen for their role before looking up outcomes, not as deployment candidates.
        specs = [('predictor', 'single__hgb__lw__mv','single__ridge__lw__mv'),
                 ('within_cohort_fusion','cross_structure__convex__lw__robust','cross_structure__equal__lw__robust'),
                 ('risk','single__ridge__diag__mv','single__ridge__lw__mv'),
                 ('optimizer','single__ridge__lw__mv','single__ridge__lw__robust'),
                 ('target_fusion','quantiles__target_blend__lw__cvar','quantiles__convex__lw__cvar')]
        indexed = primary[year].set_index('strategy_id')
        y['named_controlled_examples'] = []
        for kind, left, right in specs:
            a, b = indexed.loc[left], indexed.loc[right]
            y['named_controlled_examples'].append({'dimension': kind, 'left': left, 'right': right,
                'left_metrics': {m: a[m] for m in METRICS}, 'right_metrics': {m: b[m] for m in METRICS},
                'delta_metrics': {m: float(a[m] - b[m]) for m in METRICS}})
        def effect(risk, optimizer):
            a = indexed.loc[f'cross_structure__convex__{risk}__{optimizer}']
            b = indexed.loc[f'cross_structure__equal__{risk}__{optimizer}']
            return {m: float(a[m] - b[m]) for m in METRICS}
        four = {f'{r}|{o}': effect(r, o) for r in ['diag','lw'] for o in ['mv','robust']}
        did = {o: {m: four['diag|' + o][m] - four['lw|' + o][m] for m in METRICS} for o in ['mv','robust']}
        y['named_fusion_risk_optimizer_interaction'] = {'coalition': 'cross_structure', 'fusion_contrast': 'convex minus equal',
            'risk_contrast': 'diag minus lw', 'optimizer_contrast': 'mv minus robust', 'four_conditional_deltas': four,
            'fusion_by_risk_differences_of_differences': did, 'three_factor_difference': {m: did['mv'][m] - did['robust'][m] for m in METRICS},
            'interpretation': 'Eight saved accounts, descriptive terminal-metric contrasts only; no interaction HAC, p-value, or causal claim'}

    lines = ['# 完整冻结清单的实际比较解读',
        '范围：2025 与 2026 的已完成 AFFINE 研究账户、provided 输入池诊断；原完整池 formal BLOCKED，此前曝光保留，非盲测，非认证股东 total return。两个窗口长度不同，本文不年化或把跨年收益差当作同期限比较。全部比较只解读已有结果，0fit、0replay、无部署模型选择和候选扩展。',
        '收益/回撤/gross 数值按冻结单元等权描述；单元数不是独立 N。max_drawdown 为非正数，ΔDD>0 表示回撤较浅。下列 delta 均为左减右，百分数差按百分点报告；费用按 1,000,000 初始现金的研究账户货币单位报告。HAC5 只作用于同日平均配对差，未作多重比较校正；本文“幅度较大”不表示统计显著。',
        '## 全路径与现金结果', table(['窗口','正收益','负收益','零收益','完全无交易'], [[year,
          data['years'][str(year)]['all_paths']['return_signs']['positive'],data['years'][str(year)]['all_paths']['return_signs']['negative'],
          data['years'][str(year)]['all_paths']['return_signs']['zero'],data['years'][str(year)]['all_paths']['no_trade_paths']] for year in YEARS]),
        '两个窗口零收益数都与完全无交易路径数一致。现金路径零回撤不能解释为学习能力提高；有交易路径的收益与成本同样全部保留。']
    for year in YEARS:
        y = data['years'][str(year)]
        lines += [f'## {year}：31 个单预测器', '各预测器均使用同一十风险×三优化的 30 格；表按事前成员顺序，P/N/Z 是路径收益的正/负/零计数。',
            table(['预测器','P/N/Z','收益均值','gross均值','DD均值','费用均值'],
              [[p,'/'.join(str(y['singles'][p]['return_signs'][s]) for s in ['positive','negative','zero']),
                pct(y['singles'][p]['net_return']['mean']),pct(y['singles'][p]['mean_gross_exposure']['mean']),
                pct(y['singles'][p]['max_drawdown']['mean']),f"{y['singles'][p]['total_fees']['mean']:,.0f}"] for p in PROVIDERS]),
            f"465 组单预测器配对的平均终值差符号为 {y['matched_summary']['single_predictor']['mean_delta_return_signs']}，每组固定 30 格；这些方向依照成员登记顺序而非胜者排序，不能把正组数看作一个模型胜率。",
            f'## {year}：固定联盟内部合作',
            '下表先在同一联盟固定 risk/optimizer 与 equal 配对，再按 11 个事前联盟等权汇总。P/N/Z 是联盟内 30 格平均差的符号，不是 11 个独立样本。JSON 另保留每联盟、每方法的 30 格正负零数和最小/最大差。',
            table(['方法相对equal','联盟P/N/Z','Δ收益pp','Δgross pp','ΔDD pp','Δ费用'],
              [[m,'/'.join(str(y['fusion_method_across_fixed_cohorts'][m]['cohort_mean_delta_signs'][s]) for s in ['positive','negative','zero']),
                 pp(y['fusion_method_across_fixed_cohorts'][m]['delta_net_return']),pp(y['fusion_method_across_fixed_cohorts'][m]['delta_mean_gross_exposure']),
                 pp(y['fusion_method_across_fixed_cohorts'][m]['delta_max_drawdown']),f"{y['fusion_method_across_fixed_cohorts'][m]['delta_total_fees']:+,.0f}"] for m in FUSIONS if m != 'equal']),
            f"同联盟同方法的融合平均差随 risk 改变而跨过零的组数为 {len(y['fusion_risk_sign_switches'])}/110；这体现合同内依赖搭配，不能用‘每层挑一个冠军’概括。"]
        for dimension in ['risk','optimizer']:
            order = RISKS if dimension == 'risk' else OPTIMIZERS
            lines += [f'## {year}：{dimension} 的条件表现', '仅使用 152 个预测接口×十风险×三优化的 4,560 格，目标融合与预算控制不混入这张表。',
              table([dimension,'cells','P/N/Z','收益均值','gross均值','DD均值','费用均值'],
                [[name,y[dimension][name]['cells'],'/'.join(str(y[dimension][name]['return_signs'][s]) for s in ['positive','negative','zero']),
                 pct(y[dimension][name]['net_return']['mean']),pct(y[dimension][name]['mean_gross_exposure']['mean']),
                 pct(y[dimension][name]['max_drawdown']['mean']),f"{y[dimension][name]['total_fees']['mean']:,.0f}"] for name in order])]
        lines += [f'## {year}：目标融合相对同联盟convex预测融合',
          '配对同联盟、同 OOF convex 系数、risk 和 optimizer，但各自账户状态独立推进；支持合并/截断、现金及 CVaR 原生成员与融合 Normal proxy 场景语义都可能改变结果，不能隔离纯融合顺序因果效果。',
          table(['联盟','30格Δ收益P/N/Z','Δ收益pp','Δgross pp','ΔDD pp','Δ费用'],
            [[g,'/'.join(str(y['target_vs_convex'][g]['delta_return_signs'][s]) for s in ['positive','negative','zero']),
              pp(y['target_vs_convex'][g]['delta_net_return']['mean']),pp(y['target_vs_convex'][g]['delta_mean_gross_exposure']['mean']),
              pp(y['target_vs_convex'][g]['delta_max_drawdown']['mean']),f"{y['target_vs_convex'][g]['delta_total_fees']['mean']:+,.0f}"] for g in COALITIONS]),
          f'## {year}：交互幅度与可复核例子',
          '完整 factor 表是等权描述性代数，不是独立样本 ANOVA。下表基于 net_return 的全部 4,560 格，不按收益选模型；重复的边际交互格不是额外 N。',
          table(['交互项','平均绝对幅度pp','RMS pp','最大绝对幅度pp'],
            [[k,f"{100*v['mean_abs']:.3f}",f"{100*v['rms']:.3f}",f"{100*v['max_abs']:.3f}"] for k,v in y['interaction_amplitudes']['net_return'].items()])]
        for example in y['named_controlled_examples']:
            a, b, d = example['left_metrics'], example['right_metrics'], example['delta_metrics']
            lines += [f"- {example['dimension']}：`{example['left']}` 对照 `{example['right']}`。收益 {pct(a['net_return'])} vs {pct(b['net_return'])}；gross {pct(a['mean_gross_exposure'])} vs {pct(b['mean_gross_exposure'])}；DD {pct(a['max_drawdown'])} vs {pct(b['max_drawdown'])}；费用 {a['total_fees']:,.0f} vs {b['total_fees']:,.0f}。Δ收益 {pp(d['net_return'])}pp、Δgross {pp(d['mean_gross_exposure'])}pp、ΔDD {pp(d['max_drawdown'])}pp。"]
        interaction = y['named_fusion_risk_optimizer_interaction']
        lines += [f"固定 cross_structure 的 convex−equal，在 diag−lw 下，MV 的收益差异之差为 {pp(interaction['fusion_by_risk_differences_of_differences']['mv']['net_return'])}pp，robust 下为 {pp(interaction['fusion_by_risk_differences_of_differences']['robust']['net_return'])}pp，两者差为 {pp(interaction['three_factor_difference']['net_return'])}pp；对应 gross 三阶差 {pp(interaction['three_factor_difference']['mean_gross_exposure'])}pp，DD 三阶差 {pp(interaction['three_factor_difference']['max_drawdown'])}pp。八个已有账户的完整条件差见 JSON；未计算交互显著性或因果效应。",
          'equal95 是 <=0.95 预算规则及相同资格/槽位/费用约束下的独立账户对照，不是实际 gross 恒定的反事实。优化相对预算对照的收益差仍同时含配权、支持、持仓、现金和交易费用变化。']
    lines += ['## 预测误差与证据边界', '此解读不使用 MSE 选择模型。已有 forecast TOP20 标签诊断包含 provided input 的 held-only 行，缺少逐账户新买 gate、槽位和执行成本，不等于此处账户选股表现或原完整池表现；原生输出与 Normal proxy 的语义继续沿用诊断文件。两个年份的预测诊断负结果、标签缺失以及先前曝光不能被这次完成回放抹去。']
    output_md = ROOT / 'diagnostics/COMPARISON_FINDINGS.md'
    output_json = ROOT / 'diagnostics/COMPARISON_FINDINGS.json'
    output_md.write_text('\n\n'.join(lines) + '\n', encoding='utf-8')
    data['source_sha256'] = SOURCE_SHA
    data['elapsed_seconds'] = time.perf_counter() - started
    write(output_json, data)
    for relative, value in SOURCE_SHA.items():
        assert value == sha(ROOT / relative), 'SOURCE_CHANGED_AFTER_INTERPRETATION:' + relative
    write(ROOT / 'diagnostics/COMPARISON_FINDINGS_RECEIPT.json', {'status': 'PASS_COMPLETE_TWO_YEAR_DESCRIPTIVE_INTERPRETATION',
          'created_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': SOURCE_SHA,
          'output_sha256': {str(p.relative_to(ROOT)).replace('\\','/'): sha(p) for p in [output_md,output_json]},
          'runner_sha256': sha(Path(__file__)), 'frozen_artifacts_verified': len(frozen['artifact_sha256']),
          'fit_calls': 0, 'replay_calls': 0, 'model_selection_performed': False, 'learning_artifacts_modified': False,
          'accounts_per_year': 5053, 'paired_per_year': 634, 'conditional_per_year': 1100,
          'factor_cells_per_metric_per_year': 4560, 'budget_contrasts_per_year': 4890,
          'pool_status': 'FORMAL_FULL_ORIGINAL_POOL_BLOCKED', 'causal_or_blind_or_shareholder_return_claimed': False})
    print(json.dumps({'status': 'FINDINGS_WRITTEN', 'path': str(output_md), 'years': {y: {
        'return_signs': data['years'][str(y)]['all_paths']['return_signs'],
        'fusion_risk_sign_switches': len(data['years'][str(y)]['fusion_risk_sign_switches']),
        'interaction': data['years'][str(y)]['interaction_amplitudes']['net_return'],
        'optimizer': data['years'][str(y)]['optimizer_pairs']} for y in YEARS}}, default=str), flush=True)


if __name__ == '__main__':
    main()
