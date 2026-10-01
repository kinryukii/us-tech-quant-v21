"""Read recorded cooperative outputs; reuse the frozen account bridge verbatim.

No estimator/model imports, fitting, prediction, or account replay. All new writes
are below bridge/. Accounting and explanations come from the original bridge.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import sys
import time

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
OUT = ROOT / 'bridge'
OLD = WS / 'a2_top20_multimodel_selection_20260928_9231/acceptance_diagnostics/bridge/build_bridge.py'
BASES = ('ridge', 'elastic_net', 'logistic', 'hgb', 'q50', 'mlp')
RANKS = tuple('rank_' + b for b in BASES)
META = (*RANKS, 'q10_downside_rank', 'current_weight', 'cash_weight', 'age_scaled', 'action')
ACTIONS = np.array([0., .025, .05, .075, .1])
FIXED = np.array([.05, .15, .10, .35, .20, .15])
NAMES = ('fusion_fixed_non_equal', 'fusion_learned_weights', 'fusion_nonlinear_stacking',
         'fusion_conditional_gate', 'fusion_hgb_then_linear', 'fusion_linear_then_hgb',
         'fusion_target_decisions')
KEY = ['signal_date', 'ticker']
spec = importlib.util.spec_from_file_location('frozen_account_bridge', OLD)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
bridge.ROOT, bridge.OUT, bridge.WS = ROOT, OUT, WS
bridge.INPUTS = {}


def array(item, name, shape):
    value = np.asarray(item[name], float)
    if value.shape != shape or not np.isfinite(value).all():
        raise AssertionError(f'INVALID_RECORDED_DIAGNOSTIC:{name}:{value.shape}')
    return value


def vector(item, name):
    return array(item, name, (5,))


def compact(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def expand_diagnostic(item, policy):
    """Return 5%-vs-exit explanation fields and all-action reconstruction errors."""
    if item['cooperation_design'] != policy:
        raise AssertionError('RECORDED_METHOD_MISMATCH')
    values = vector(item, 'fused_action_values')
    if abs(values[0]) > 1e-12:
        raise AssertionError('RECORDED_ZERO_ACTION_NOT_CENTERED')
    ranks = np.column_stack([array(item['base_rank_advantages'], b, (5,)) for b in BASES])
    downside = vector(item, 'q10_downside_rank')
    fields = dict(score_provenance='RECORDED_ACTUAL_STATE_COOPERATIVE_ACTION_ADVANTAGE',
        score_scale='CONDITIONAL_ACTION_PREFERENCE_NOT_NATIVE_RETURN',
        fused_action_values_json=compact(values.tolist()),
        base_rank_mean_5pct=float(ranks[2].mean()), base_rank_std_5pct=float(ranks[2].std()),
        q10_downside_rank_5pct=float(downside[2]),
        raw_projected_weight=float(item['mlp_projected_weight']),
        anchor_prediction_5pct=np.nan, residual_prediction_5pct=np.nan,
        mixed_target=np.nan, gate_output_scale=np.nan, anchor_hgb_coefficient=np.nan,
        nonlinear_sensitivities_are_additive=False)
    for j, b in enumerate(BASES):
        raw = array(item['base_action_values'], b, (5,))
        fields.update({f'base_{b}_raw_advantage_5pct': float(raw[2] - raw[0]),
                       f'base_{b}_rank_5pct': float(ranks[2, j]),
                       f'base_{b}_contribution_5pct': np.nan,
                       f'base_{b}_weight_5pct': np.nan,
                       f'base_{b}_normalized_weight_5pct': np.nan,
                       f'base_{b}_anchor_contribution_5pct': np.nan,
                       f'base_{b}_nonadditive_zero_sensitivity_5pct': np.nan,
                       f'base_{b}_expert_target_weight': np.nan,
                       f'base_{b}_target_contribution': np.nan})
    errors = {}
    if policy in ('fusion_fixed_non_equal', 'fusion_conditional_gate'):
        weights = array(item, 'weights', (5, 6))
        contributions = array(item, 'contributions', (5, 6))
        scale = float(item.get('gate_output_scale', 1.))
        if not np.isfinite(scale) or scale <= 0:
            raise AssertionError('INVALID_RECORDED_GATE_SCALE')
        if np.max(np.abs(weights - weights[:1])) > 1e-7 or np.max(np.abs(weights.sum(1) - 1)) > 1e-6:
            raise AssertionError('RECORDED_GATE_WEIGHTS_NOT_SHARED_OR_NORMALIZED')
        if (weights < 0).any():
            raise AssertionError('NEGATIVE_MIXTURE_WEIGHT')
        if policy == 'fusion_fixed_non_equal':
            errors['fixed_weights'] = float(np.max(np.abs(weights - FIXED)))
        expected_terms = ranks * weights * scale
        expected_terms -= expected_terms[:1]
        errors['recorded_terms'] = float(np.max(np.abs(expected_terms - contributions)))
        reconstructed = contributions.sum(1)
        fields['contribution_semantics'] = 'ADDITIVE_CENTERED_SCORE_CONTRIBUTIONS'
        fields['gate_output_scale'] = scale
        for j, b in enumerate(BASES):
            fields[f'base_{b}_weight_5pct'] = float(weights[2, j])
            fields[f'base_{b}_contribution_5pct'] = float(contributions[2, j])
    elif policy == 'fusion_target_decisions':
        targets = array(item, 'expert_target_weights', (6,))
        terms = array(item, 'target_contributions', (6,))
        mixed = float(item['mixed_target'])
        errors['target_terms'] = float(np.max(np.abs(targets * FIXED - terms)))
        errors['mixed_target'] = float(abs(terms.sum() - mixed))
        reconstructed = -((ACTIONS - mixed) / .1) ** 2
        reconstructed -= reconstructed[0]
        fields.update(contribution_semantics='TARGET_WEIGHT_CONTRIBUTIONS_NOT_SCORE_ATTRIBUTIONS', mixed_target=mixed)
        for j, b in enumerate(BASES):
            fields[f'base_{b}_weight_5pct'] = float(FIXED[j])
            fields[f'base_{b}_expert_target_weight'] = float(targets[j])
            fields[f'base_{b}_target_contribution'] = float(terms[j])
    else:
        anchor = vector(item, 'anchor_prediction')
        residual = vector(item, 'residual_prediction')
        reconstructed = anchor + residual
        fields.update(anchor_prediction_5pct=float(anchor[2]), residual_prediction_5pct=float(residual[2]))
        if policy == 'fusion_learned_weights':
            terms = np.column_stack([vector(item, 'contribution_' + c) for c in RANKS])
            errors['learned_terms'] = float(np.max(np.abs(terms.sum(1) - anchor)))
            errors['learned_zero_residual'] = float(np.max(np.abs(residual)))
            fields['contribution_semantics'] = 'ADDITIVE_RAW_NNLS_COEFFICIENT_SCORE_CONTRIBUTIONS'
            for j, b in enumerate(BASES):
                fields[f'base_{b}_contribution_5pct'] = float(terms[2, j])
                fields[f'base_{b}_normalized_weight_5pct'] = float(vector(item, 'normalized_weight_rank_' + b)[2])
        elif policy == 'fusion_hgb_then_linear':
            coefficient = vector(item, 'anchor_hgb_coefficient')
            anchor_expected = ranks[:, 3] * coefficient
            anchor_expected -= anchor_expected[0]
            errors['hgb_anchor'] = float(np.max(np.abs(anchor_expected - anchor)))
            terms = np.column_stack([vector(item, 'linear_residual_contribution_' + c) for c in META])
            errors['linear_residual_terms'] = float(np.max(np.abs(terms.sum(1) - residual)))
            fields['contribution_semantics'] = 'ADDITIVE_HGB_ANCHOR_PLUS_ELEVEN_LINEAR_RESIDUAL_TERMS'
            fields['anchor_hgb_coefficient'] = float(coefficient[2])
            fields['base_hgb_anchor_contribution_5pct'] = float(anchor[2])
            for j, c in enumerate(META):
                fields['linear_residual_contribution_' + c + '_5pct'] = float(terms[2, j])
            for j, b in enumerate(BASES):
                fields[f'base_{b}_contribution_5pct'] = float(terms[2, j] + (anchor[2] if b == 'hgb' else 0.))
        else:
            fields['contribution_semantics'] = ('LINEAR_ANCHOR_ADDITIVE_NONLINEAR_RESIDUAL_NONADDITIVE'
                if policy == 'fusion_linear_then_hgb' else 'NONLINEAR_NONADDITIVE_NO_UNIQUE_EXPERT_CONTRIBUTIONS')
            if policy == 'fusion_linear_then_hgb':
                terms = np.column_stack([vector(item, 'anchor_contribution_' + c) for c in RANKS])
                errors['linear_anchor_terms'] = float(np.max(np.abs(terms.sum(1) - anchor)))
                for j, b in enumerate(BASES):
                    fields[f'base_{b}_anchor_contribution_5pct'] = float(terms[2, j])
            else:
                errors['nonlinear_zero_anchor'] = float(np.max(np.abs(anchor)))
            for b in BASES:
                fields[f'base_{b}_nonadditive_zero_sensitivity_5pct'] = float(vector(item, 'nonadditive_zero_rank_' + b + '_sensitivity')[2])
            for c in META:
                fields['input_' + c + '_5pct'] = float(vector(item, 'input_' + c)[2])
    errors['fused_score'] = float(np.max(np.abs(reconstructed - values)))
    if max(errors.values(), default=0.) >= 1e-10:
        raise AssertionError(f'RECORDED_FUSION_RECONSTRUCTION_FAILED:{policy}:{errors}')
    fields.update(score_action0=float(values[0]), score_action5pct=float(values[2]),
        actual_score_5pct_vs_exit=float(values[2] - values[0]),
        max_action_advantage=float((values - values[0]).max()),
        unconstrained_best_action=float(ACTIONS[np.argmax(values)]))
    return fields, errors


def expand_raw(raw, contexts, targets, operations, policy, year, coefficients):
    if coefficients or policy not in NAMES:
        raise AssertionError('NO_OLD_EQUAL_OR_STACK_COEFFICIENT_SUBSTITUTION')
    bridge.unique(raw, ['signal_date'], 'RAW')
    bridge.unique(contexts, ['signal_date'], 'CONTEXT')
    assert set(raw.signal_date) == set(contexts.signal_date)
    context = {r.signal_date: r for r in contexts.itertuples()}
    extras = {date: set(g.ticker) for date, g in targets.groupby('signal_date', sort=False)}
    for date, g in operations.groupby('signal_date', sort=False):
        extras.setdefault(date, set()).update(g.ticker)
    rows, checks = [], {}
    decision_error = 0.
    for r in raw.itertuples():
        c = context[r.signal_date]
        original = set(json.loads(r.original_input_tickers_json))
        decision = set(json.loads(r.decision_input_tickers_json))
        weights = json.loads(r.model_decisions_json)
        outputs = json.loads(r.raw_model_outputs_json or '{}') or {}
        units = json.loads(c.current_units_json)
        current = json.loads(c.current_weights_json or '{}')
        reserved = set(json.loads(c.final_reserved_tickers_json))
        universe = sorted(original | decision | set(weights) | set(outputs) | set(units) | extras.get(r.signal_date, set()))
        glw_day = year == 2026 and r.signal_date == pd.Timestamp('2026-02-26')
        for ticker in universe:
            item = outputs.get(ticker, {})
            row = dict(year=year, policy=policy, signal_date=r.signal_date, ticker=ticker,
                state_basis='ACTUAL_ACCOUNT_AT_ORIGINAL_SIGNAL', original_input_present=ticker in original,
                decision_input_present=ticker in decision, raw_model_score_present=bool(item),
                raw_decision_present=ticker in weights, raw_chosen_weight=weights.get(ticker, np.nan),
                signal_current_units=units.get(ticker, 0.), signal_current_weight=current.get(ticker, 0.),
                signal_cash=c.cash, signal_nav=c.nav, signal_cash_weight=c.cash_weight,
                signal_reserved=ticker in reserved, reserved_slots=c.final_reserved_slots,
                reserved_weight=c.final_reserved_weight, available_slots=c.final_available_slots,
                available_weight=c.final_available_weight, account_active_target_count=c.active_target_count,
                account_active_target_weight=c.active_target_weight,
                signal_implied_cash_weight=1-c.final_reserved_weight-c.active_target_weight,
                known_glw_input_conflict=glw_day and ticker == 'GLW' and ticker in decision,
                same_day_glw_in_decision_input=glw_day and 'GLW' in decision,
                same_day_glw_score_present=glw_day and bool(outputs.get('GLW', {})),
                actual_score_5pct_vs_exit=np.nan, score_provenance='NO_RECORDED_SCORE',
                score_action0=np.nan, score_action5pct=np.nan, max_action_advantage=np.nan,
                unconstrained_best_action=np.nan, raw_projected_weight=np.nan,
                base_rank_mean_5pct=np.nan, base_rank_std_5pct=np.nan, q10_downside_rank_5pct=np.nan,
                disagreement_penalty_5pct=0., downside_penalty_5pct=0.)
            if item:
                fields, errors = expand_diagnostic(item, policy)
                row.update(fields)
                for key, error in errors.items():
                    checks[key] = max(checks.get(key, 0.), error)
                if ticker in weights:
                    decision_error = max(decision_error, abs(float(item['chosen_weight']) - weights[ticker]))
            rows.append(row)
    frame = pd.DataFrame(rows)
    bridge.unique(frame, KEY, 'EXPANDED_RAW')
    assert decision_error < 1e-8
    ranked = frame.loc[frame.actual_score_5pct_vs_exit.notna()].sort_values(
        ['signal_date', 'actual_score_5pct_vs_exit', 'ticker'], ascending=[True, False, True], kind='stable').copy()
    ranked['actual_state_rank'] = ranked.groupby('signal_date', sort=False).cumcount()+1
    frame = bridge.checked_merge(frame, ranked[KEY+['actual_state_rank']], KEY)
    frame['actual_state_top20'] = frame.actual_state_rank.le(20)
    frame['actual_score_positive'] = frame.actual_score_5pct_vs_exit.gt(0)
    counts = ranked.groupby(['signal_date', 'actual_score_5pct_vs_exit']).size().rename('exact_score_tie_count')
    frame = frame.merge(counts, on=['signal_date', 'actual_score_5pct_vs_exit'], how='left', validate='many_to_one')
    return frame, dict(fusion_reconstruction_max_abs_error=max(checks.values(), default=0.),
        method_reconstruction_errors=checks, raw_chosen_weight_max_abs_error=decision_error,
        raw_universe_rows=len(frame))


bridge.expand_raw = expand_raw


def self_test():
    """Synthetic recorded payloads exercise semantics without a model or replay."""
    ranks = np.outer(ACTIONS, np.array([-2., 3., 4., 1., -.5, 2.]))
    base = dict(base_rank_advantages={b: ranks[:, j].tolist() for j, b in enumerate(BASES)},
        base_action_values={b: (ranks[:, j] + .03).tolist() for j, b in enumerate(BASES)},
        q10_downside_rank=[0.]*5, mlp_projected_weight=.05)
    payloads = []
    for name in NAMES:
        item = {**base, 'cooperation_design': name}
        if name in ('fusion_fixed_non_equal', 'fusion_conditional_gate'):
            scale = .002 if name.endswith('gate') else 1.
            item.update(weights=np.tile(FIXED, (5, 1)).tolist(), contributions=(ranks*FIXED*scale).tolist(),
                        gate_output_scale=scale, fused_action_values=(ranks@FIXED*scale).tolist())
        elif name == 'fusion_target_decisions':
            targets = np.array([0., .025, .05, .075, .1, .05]); terms = targets*FIXED; mixed = terms.sum()
            values = -((ACTIONS-mixed)/.1)**2; values -= values[0]
            item.update(expert_target_weights=targets.tolist(), target_contributions=terms.tolist(), mixed_target=mixed,
                        fused_action_values=values.tolist())
        else:
            anchor = ranks@FIXED*.001; residual = ACTIONS*.0001
            if name == 'fusion_learned_weights':
                residual[:] = 0.
                for j, b in enumerate(BASES):
                    item['contribution_rank_'+b] = (ranks[:, j]*FIXED[j]*.001).tolist()
                    item['normalized_weight_rank_'+b] = [float(FIXED[j])]*5
            elif name == 'fusion_hgb_then_linear':
                anchor = ranks[:, 3]*.001
                item['anchor_hgb_coefficient'] = [.001]*5
                for col in META:
                    item['linear_residual_contribution_'+col] = (residual if col == 'action' else np.zeros(5)).tolist()
            else:
                if name == 'fusion_nonlinear_stacking':
                    anchor = np.zeros(5)
                else:
                    for j, b in enumerate(BASES):
                        item['anchor_contribution_rank_'+b] = (ranks[:, j]*FIXED[j]*.001).tolist()
                for b in BASES:
                    item['nonadditive_zero_rank_'+b+'_sensitivity'] = [0., .1, .2, .3, .4]
                for col in META:
                    item['input_'+col] = [0.]*5
            item.update(anchor_prediction=anchor.tolist(), residual_prediction=residual.tolist(), fused_action_values=(anchor+residual).tolist())
        fields, errors = expand_diagnostic(item, name)
        assert abs(fields['actual_score_5pct_vs_exit']-item['fused_action_values'][2]) < 1e-12
        if name in ('fusion_nonlinear_stacking', 'fusion_linear_then_hgb', 'fusion_target_decisions'):
            assert np.isnan(fields['base_hgb_contribution_5pct'])
        payloads.append(item)
    corrupted = dict(payloads[0]); corrupted['fused_action_values'] = [0., 1., 2., 3., 4.]
    try:
        expand_diagnostic(corrupted, NAMES[0])
    except AssertionError:
        pass
    else:
        raise AssertionError('CORRUPTED_RECORDED_FUSION_NOT_REJECTED')
    result = dict(status='PASS',methods_tested=list(NAMES),corrupted_fusion_rejected=True,
                  model_fit_calls=0,model_predict_calls=0,replay_calls=0)
    OUT.mkdir(exist_ok=True)
    bridge.dump(OUT/'SELF_TEST.json', result)
    print(json.dumps(result), flush=True)


def build():
    started = time.monotonic()
    OUT.mkdir(exist_ok=True)
    if (OUT/'COMPLETE.json').exists():
        raise RuntimeError('BRIDGE_ALREADY_COMPLETE')
    if list(OUT.glob('actual_account_bridge_*.parquet')):
        raise RuntimeError('PRESERVE_PARTIAL_BRIDGE_OUTPUTS')
    for year in (2025, 2026):
        if not (ROOT/f'evaluation_{year}/cost_10/COMPLETE.json').exists():
            raise RuntimeError(f'WAIT_FOR_MAIN_REPLAY_COMPLETE:{year}')
    for path in [Path(__file__), OLD, ROOT/'EXPERIMENT_CONTRACT.md', ROOT/'policy.py']:
        bridge.record(path)
    summaries, lasts, examples, terminal_accounts, terminal_positions = [], [], [], [], []
    for year in (2025, 2026):
        frozen = bridge.read_json(ROOT/f'evaluation_{year}/cost_10/FROZEN_BEFORE_REPLAY.json')
        complete = bridge.read_json(ROOT/f'evaluation_{year}/cost_10/COMPLETE.json')
        assert complete['policies'] == len(frozen['roster']) == 7
        assert set(frozen['roster']) == set(NAMES)
        assert complete['fit_attempts'] == 0 and complete['sources_unchanged']
        features, prices = bridge.source_tables(year)
        for policy in frozen['roster']:
            print(json.dumps(dict(starting_bridge=policy, year=year)), flush=True)
            summary, last, example = bridge.build_path(year, policy, features, prices)
            summaries.append(summary); lasts.append(last); examples.append(example)
            # The last signal executes before the terminal mark; retain both dates.
            directory = ROOT/f'evaluation_{year}/cost_10/{policy}'
            daily = bridge.read_frame(directory/'daily.parquet')
            terminal = daily.sort_values('date', kind='stable').tail(1).copy()
            terminal['year'] = year; terminal['policy'] = policy
            terminal['last_signal_date'] = last.signal_date.max()
            terminal['last_signal_execution_date'] = last.execution_date.max()
            terminal['formal_price_certification'] = False
            terminal_accounts.append(terminal)
            marks = bridge.read_frame(directory/'positions.parquet', filters=[('date', '==', terminal.date.iloc[0])])
            marks['year'] = year; marks['policy'] = policy
            marks['formal_shareholder_valuation_certification'] = False
            marks['known_glw_event_mark_conflict'] = marks.ticker.eq('GLW') & marks.mark_date.isin(
                [pd.Timestamp('2026-02-26'),pd.Timestamp('2026-02-27')])
            terminal_positions.append(marks)
            print(json.dumps({k: summary[k] for k in ['year', 'policy', 'rows', 'high_rank_zero_target', 'positive_target_no_trade', 'capacity_limited_fills', 'recorded_cost_dollars']}), flush=True)
    final = pd.concat(lasts, ignore_index=True)
    final.to_parquet(OUT/'LAST_SIGNAL_ACTUAL_ACCOUNT_FULL.parquet', index=False, compression='zstd')
    easy = ['year','policy','signal_date','ticker','actual_state_rank','actual_score_5pct_vs_exit','exact_score_tie_count',
        'contribution_semantics','anchor_prediction_5pct','residual_prediction_5pct','mixed_target','raw_chosen_weight',
        'target_weight','target_order_type','target_semantic','signal_current_weight','signal_cash_weight',
        'new_buy_eligible','zero_target_explanation','execution_explanation','execution_reasons',
        'buy_notional','sell_notional','recorded_cost','post_weight','post_price_status',
        'execution_cash','execution_nav','execution_account_valuation_status']
    final[easy].to_csv(OUT/'LAST_SIGNAL_READABLE.csv', index=False, encoding='utf-8-sig')
    pd.concat(examples, ignore_index=True).to_parquet(OUT/'EXPLANATION_EXAMPLES.parquet', index=False, compression='zstd')
    pd.concat(terminal_accounts, ignore_index=True).to_csv(OUT/'TERMINAL_ACCOUNT.csv', index=False, encoding='utf-8-sig')
    pd.concat(terminal_positions, ignore_index=True).to_parquet(OUT/'TERMINAL_POSITIONS.parquet', index=False, compression='zstd')
    pd.DataFrame([{k:v for k,v in row.items() if not isinstance(v,dict)} for row in summaries]).to_csv(OUT/'POLICY_SUMMARY.csv', index=False, encoding='utf-8-sig')
    for path, expected in bridge.INPUTS.items():
        assert bridge.sha(path) == expected, f'ORIGINAL_CHANGED:{path}'
    receipt = dict(status='PASS', paths=len(summaries), rows=sum(s['rows'] for s in summaries),
        model_fit_calls=0,model_predict_calls=0,replay_calls=0,original_inputs_unchanged=True,
        input_sha256=bridge.INPUTS,paths_summary=summaries,seconds=time.monotonic()-started,
        scope='Recorded actual-account 2025/2026 cost10 ledgers; independent fixed-reference ranking is separate',
        score_rule='Recorded centered .05 action value; conditional preference, not native expected return',
        ranking_rule='Scored actual-state securities descending score then ticker; every tie and unscored input retained',
        additive_scope='Fixed/gate/NNLS exact six terms; HGB-then-linear anchor plus 11 residual terms; linear-then-HGB exact anchor terms plus nonadditive residual',
        sensitivity_scope='Recorded single-rank-zero sensitivities, action0 corrected; not additive or causal attributions; never recomputed',
        target_scope='Six expert targets on same account, fixed-weight target contributions, distance preference; not six NAV averages',
        price_scope='Original gate and mark status only; 2025 missing warning defaults are not certification; known GLW conflicts marked',
        optimizer_limit='Unrecorded causes remain UNKNOWN; high rank is not an instruction to buy',
        inherited_limitations='Universe/event/arrival limitations unchanged; not blind test or formal performance')
    bridge.dump(OUT/'COMPLETE.json', receipt)
    (OUT/'METHODS.md').write_text('''# 新协同批次：实际账户证据桥

本桥只读取既有原始输出、目标、成交、持仓及现金账本；复用旧 build_path、交易聚合、分类及会计核对。没有重新预测、拟合或回放。

实际排名使用该账户当日状态下已记录的 5% 动作相对退出的条件偏好。不同方法的分数尺度不能直接比较；全部负分也仍有相对排名。按分数降序、ticker 升序确定展示顺序，exact_score_tie_count 揭示并列。固定参考状态榜单另表连接，不能当作真实下单依据。

固定比例与门控保存六个加法分数贡献；门控贡献包含已记录的正输出尺度。NNLS 使用原始系数贡献，归一化权重只描述比例。HGB→线性保存 HGB 锚及 11 项线性残差贡献。线性→HGB 保存六项线性锚贡献与 HGB 残差；非线性模型保存原始单臂置零敏感性，它们不相加、不声称唯一贡献或因果解释。所有方法都核对五个动作。

目标混合保存同一个真实账户状态下六个专家目标及比例加权贡献。其分数由 -((action-mixed_target)/0.1)^2 对零动作作差复核；目标贡献不是分数贡献，也不是多个账户净值平均。

目标、买卖额、手续费、成交后单位、现金及净值均与源账本核对。没有目标记录不等于拒单。高分零目标但未记录具体绑定约束时保持 UNKNOWN，不由结果推断原因。

LAST_SIGNAL 表中的现金及估值属于末信号下一开盘成交日。TERMINAL_ACCOUNT 和 TERMINAL_POSITIONS 另保留源账本最终估值日，不能把这两个日期混称为同一时点。

价格状态仅是原价格门控及账本估值状态：2025 缺 warning 列默认值不构成独立认证；GLW 2026-02-26/27 已知冲突显式标注。股票池、公司行动、历史到达时间和非盲测等原有限制继承，不能称为正式收益或已修复数据。
''', encoding='utf-8')
    print(json.dumps(dict(status='PASS', paths=len(summaries), rows=receipt['rows'], seconds=receipt['seconds'])), flush=True)


def join_reference():
    """Join last-signal recorded account evidence to separate fixed-state ranks."""
    if (OUT/'LAST_SIGNAL_THREE_LAYER_COMPLETE.json').exists():
        raise RuntimeError('PRESERVE_COMPLETED_REFERENCE_JOIN')
    receipt = bridge.read_json(OUT/'COMPLETE.json')
    assert receipt['status'] == 'PASS' and receipt['paths'] == 14
    pieces = []
    for year in (2025, 2026):
        selection = ROOT/'selection'
        selected_receipt = bridge.read_json(selection/f'COMPLETE_{year}.json')
        assert selected_receipt['fit_attempts'] == 0 and selected_receipt['source_sha256_unchanged']
        score_path = selection/f'scores_{year}.parquet'
        assert bridge.sha(score_path) == selected_receipt['output_sha256'][str(score_path)]
        reference = bridge.read_frame(score_path)
        last_date = reference.signal_date.max()
        reference = reference.loc[reference.signal_date.eq(last_date)].copy()
        reference['year'] = year
        join_keys = ['year','policy','signal_date','ticker']
        # Every fixed-state attribute remains visibly separate from account state.
        reference.rename(columns={c: ('fixed_'+c if c.startswith('reference_') else 'fixed_reference_'+c)
                                  for c in reference if c not in join_keys}, inplace=True)
        bridge.unique(reference, join_keys, 'REFERENCE_LAST_SIGNAL')
        actual = []
        for summary in receipt['paths_summary']:
            if summary['year'] != year:
                continue
            path = ROOT/summary['path']
            assert bridge.sha(path) == summary['sha256']
            part = bridge.read_frame(path, filters=[('signal_date', '==', last_date)])
            if part.empty:
                raise AssertionError('LAST_SIGNAL_DIFFERENT_BETWEEN_ACCOUNT_AND_REFERENCE')
            actual.append(part)
        account = pd.concat(actual, ignore_index=True)
        bridge.unique(account, join_keys, 'ACTUAL_LAST_SIGNAL')
        joined = account.merge(reference, on=join_keys, how='outer', validate='one_to_one', indicator='three_layer_join_status')
        if not joined.three_layer_join_status.eq('both').sum() == len(reference):
            raise AssertionError('REFERENCE_CANDIDATE_MISSING_FROM_ACCOUNT_ORIGINAL_INPUT')
        joined['fixed_reference_state_basis'] = 'CURRENT0_CASH0.95_AGE0_NOT_THE_ACCOUNT_STATE'
        joined['show_in_compact_last_signal'] = (joined.actual_state_top20.fillna(False).astype(bool)
            | joined.fixed_reference_top20.fillna(False).astype(bool) | joined.target_weight.gt(0)
            | joined.post_units.gt(0) | joined.has_recorded_rejection.fillna(False).astype(bool))
        pieces.append(joined)
    result = pd.concat(pieces, ignore_index=True)
    result = result.sort_values(['year','policy','actual_state_rank','ticker'], kind='stable').reset_index(drop=True)
    result.to_parquet(OUT/'LAST_SIGNAL_THREE_LAYER_FULL.parquet', index=False, compression='zstd')
    columns = ['year','policy','signal_date','ticker','three_layer_join_status',
        'fixed_reference_rank','fixed_reference_score','fixed_reference_top20','fixed_reference_label_status',
        'actual_state_rank','actual_score_5pct_vs_exit','exact_score_tie_count','actual_state_top20',
        'signal_current_weight','signal_cash_weight','raw_chosen_weight','target_weight','target_order_type',
        'zero_target_explanation','execution_explanation','execution_reasons','buy_notional','sell_notional',
        'recorded_cost','post_units','post_weight','post_price_status','execution_cash','execution_nav',
        'execution_account_valuation_status','contribution_semantics','show_in_compact_last_signal']
    result[columns].to_csv(OUT/'LAST_SIGNAL_THREE_LAYER_ALL.csv', index=False, encoding='utf-8-sig')
    compact_table = result.loc[result.show_in_compact_last_signal, columns]
    compact_table.to_csv(OUT/'LAST_SIGNAL_THREE_LAYER.csv', index=False, encoding='utf-8-sig')
    for path, expected in bridge.INPUTS.items():
        assert bridge.sha(path) == expected, f'INPUT_CHANGED_DURING_REFERENCE_JOIN:{path}'
    done = dict(status='PASS',rows=len(result),compact_rows=len(compact_table),paths=14,
        signal_dates={str(y):str(p.signal_date.iloc[0].date()) for y,p in result.groupby('year')},
        join_status=result.three_layer_join_status.value_counts().to_dict(),
        sources_unchanged=True,input_sha256=bridge.INPUTS,model_fit_calls=0,model_predict_calls=0,replay_calls=0,
        semantics='Reference .05-vs-0 rank at (0,.95,0); actual-state .05-vs-0 rank; actual target and recorded execution are separate columns',
        not_a_trading_instruction=True,unrecorded_zero_target_causes_remain_unknown=True,
        output_sha256={str(p):bridge.sha(p) for p in OUT.glob('LAST_SIGNAL_THREE_LAYER*') if p.suffix in ('.csv','.parquet')})
    bridge.dump(OUT/'LAST_SIGNAL_THREE_LAYER_COMPLETE.json', done)
    print(json.dumps({k:done[k] for k in ['status','rows','compact_rows','join_status']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--join-reference', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.join_reference:
        join_reference()
    else:
        build()
