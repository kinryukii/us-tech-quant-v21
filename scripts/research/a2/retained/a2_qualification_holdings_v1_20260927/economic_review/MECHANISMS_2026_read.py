"""Summarize saved 2026 account mechanisms; never import policies or replay.

No ticker/date exclusion, state recomputation, portfolio splice, or counterfactual.
Outputs only MECHANISMS_2026.csv and MECHANISMS_2026_NOTES.md beside this script.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'evaluation_2026/cost_10'
FILES = ['raw_model_outputs', 'target_decisions', 'signal_contexts',
         'execution_results', 'positions', 'daily', 'trades', 'operational_actions']
FOCUS = ['joint_rl_ensemble', 'joint_rl_zero_control', 'joint_mlp', 'hgb_return_baseline']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def js(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def daystr(value):
    return None if pd.isna(value) else pd.Timestamp(value).strftime('%Y-%m-%d')


def runs(daily):
    answer = []
    mask = daily.certified_nav.notna().to_numpy()
    start = None
    for i in range(len(daily) + 1):
        valid = i < len(daily) and mask[i]
        if valid and start is None:
            start = i
        elif not valid and start is not None:
            answer.append({'start': daystr(daily.iloc[start].date), 'end': daystr(daily.iloc[i - 1].date), 'sessions': i - start})
            start = None
    return answer


def summarize(folder):
    sources = {name: folder / (name + '.parquet') for name in FILES}
    original_hashes = {name: sha(path) for name, path in sources.items()}
    data = {name: pd.read_parquet(path) for name, path in sources.items()}
    raw, targets, ctx, execution, positions, daily, trades, ops = [data[name] for name in FILES]
    daily = daily.sort_values('date').reset_index(drop=True)
    ctx = ctx.sort_values('signal_date').reset_index(drop=True)
    dates = pd.DatetimeIndex(ctx.signal_date)
    last_signal, last_date = dates[-1], daily.date.iloc[-1]
    start_nav = float(daily.nav.iloc[0])
    assert len(daily) == 183 and len(ctx) == len(raw) == 181
    assert not targets.order_id.duplicated().any()
    assert not positions.duplicated(['date', 'ticker']).any()
    by_order = targets[['order_id', 'current_units', 'current_weight', 'adapted_target_weight']]
    at_close = positions[['date', 'ticker', 'index_units', 'market_value', 'weight', 'stale', 'unknown']].rename(
        columns={'date': 'execution_date', 'index_units': 'units_at_execution_close', 'weight': 'weight_at_execution_close'})
    linked = execution.merge(by_order, on='order_id', how='left', validate='many_to_one').merge(
        at_close, on=['execution_date', 'ticker'], how='left', validate='many_to_one')
    linked['held_before'] = linked.current_units.gt(0)
    linked['held_at_execution_close'] = linked.units_at_execution_close.fillna(0).gt(0)
    linked['existing_units_unchanged'] = linked.held_before & np.isclose(
        linked.units_at_execution_close.fillna(0), linked.current_units, rtol=1e-11, atol=1e-10)

    no = targets.loc[targets.decision_semantic.eq('MODEL_NO_DECISION') & targets.current_units.gt(0)]
    nodaily = no.groupby('signal_date').agg(names=('ticker', 'size'), capital_fraction=('current_weight', 'sum')).reindex(dates, fill_value=0)
    no_end_keys = no.loc[no.signal_date.eq(last_signal), ['ticker', 'current_units']]
    no_end = no_end_keys.merge(positions.loc[positions.date.eq(last_date)], on='ticker', how='left', validate='one_to_one')
    no_end_held = no_end.loc[no_end.index_units.fillna(0).gt(0)]
    preserved = linked.loc[linked.status.eq('PRESERVED_UNITS')]
    rejected = linked.loc[linked.status.eq('REJECTED')]
    opheld = ops.loc[ops.had_position]
    op_targets_held = targets.loc[targets.decision_semantic.eq('OPERATIONAL_EXIT_REQUIRED') & targets.current_units.gt(0)]
    op_daily_capital = op_targets_held.groupby('signal_date').current_weight.sum().reindex(dates, fill_value=0)
    op_end_names = set(op_targets_held.loc[op_targets_held.signal_date.eq(last_signal), 'ticker'])
    op_end = positions.loc[positions.date.eq(last_date) & positions.ticker.isin(op_end_names)]
    optrade = trades.loc[trades.decision_semantic.eq('OPERATIONAL_EXIT_REQUIRED')]
    opreject = rejected.loc[rejected.decision_semantic.eq('OPERATIONAL_EXIT_REQUIRED') & rejected.held_before]
    reasons = []
    for (status, reason, side), frame in linked.loc[linked.status.isin(['REJECTED', 'PARTIALLY_FILLED'])].groupby(['status', 'reason', 'side'], dropna=False):
        reasons.append({'status': status, 'reason': reason, 'side': side, 'orders': int(frame.order_id.nunique()),
                        'signal_days': int(frame.signal_date.nunique()), 'execution_days': int(frame.execution_date.nunique()),
                        'tickers': int(frame.ticker.nunique()), 'orders_with_existing_units': int(frame.held_before.sum()),
                        'existing_units_unchanged_at_execution_close': int(frame.existing_units_unchanged.sum()),
                        'held_at_execution_close': int(frame.held_at_execution_close.sum())})
    reserve_reasons = {}
    for value in no.signal_reservation_reasons:
        for reason in set(str(value).split('|')):
            if reason:
                reserve_reasons[reason] = reserve_reasons.get(reason, 0) + 1
    model_output_counts = [sum(float(w) > 1e-12 for w in json.loads(x).values()) for x in raw.model_decisions_json]
    model_output_exposure = [sum(float(w) for w in json.loads(x).values()) for x in raw.model_decisions_json]
    active = targets.loc[targets.decision_semantic.eq('MODEL_ACTIVE_EXIT')]
    positive = targets.loc[targets.decision_semantic.eq('MODEL_TARGET_WEIGHT')]
    buys = trades.loc[trades.side.eq('BUY')]
    sells = trades.loc[trades.side.eq('SELL')]
    capacity_boundary = buys.loc[buys.capacity_enforced & np.isclose(buys.notional, .01 * buys.capacity_adv, rtol=1e-8, atol=1e-6)]
    certified_runs = runs(daily)
    prefix = certified_runs[0] if certified_runs and certified_runs[0]['start'] == daystr(daily.date.iloc[0]) else None
    columns = {
        'policy': folder.name, 'cost_bps': 10, 'source_scope': 'SAVED_2026_VERSION_ONLY_NO_REPLAY_NO_COUNTERFACTUAL',
        'first_account_date': daystr(daily.date.iloc[0]), 'last_account_date': daystr(last_date),
        'last_signal_date': daystr(last_signal), 'account_days': len(daily), 'signal_days': len(ctx),
        'policy_called_days': int(raw.policy_called.sum()), 'raw_output_provided_days': int(raw.raw_model_outputs_provided.sum()),
        'model_positive_target_orders': len(positive), 'model_positive_target_signal_days': int(positive.signal_date.nunique()),
        'model_raw_positive_names_mean': float(np.mean(model_output_counts)),
        'model_raw_positive_target_exposure_mean': float(np.mean(model_output_exposure)),
        'model_raw_positive_target_exposure_last_signal': float(model_output_exposure[-1]),
        'model_active_exit_orders': len(active), 'model_active_exit_signal_days': int(active.signal_date.nunique()),
        'model_active_exit_actual_fill_orders': int(trades.loc[trades.decision_semantic.eq('MODEL_ACTIVE_EXIT'), 'order_id'].nunique()),
        'model_active_exit_actual_flatten_orders': int(trades.loc[trades.decision_semantic.eq('MODEL_ACTIVE_EXIT') & trades.action.eq('EXIT'), 'order_id'].nunique()),
        'actual_trade_fills': len(trades), 'actual_trade_execution_days': int(trades.execution_date.nunique()),
        'actual_initial_buy_fills': int(trades.action.eq('BUY').sum()), 'actual_increase_fills': int(trades.action.eq('INCREASE').sum()),
        'actual_reduce_fills': int(trades.action.eq('REDUCE').sum()), 'actual_exit_fills': int(trades.action.eq('EXIT').sum()),
        'actual_buy_notional': float(buys.notional.sum()), 'actual_sell_notional': float(sells.notional.sum()),
        'actual_gross_traded_notional': float(trades.notional.sum()), 'actual_fees': float(trades.transaction_cost.sum()),
        'actual_fees_fraction_initial_capital': float(trades.transaction_cost.sum() / start_nav),
        'no_decision_held_order_rows': len(no), 'no_decision_signal_days': int(no.signal_date.nunique()),
        'no_decision_fraction_of_signal_days': float(no.signal_date.nunique() / len(ctx)),
        'no_decision_names_mean_all_signal_days': float(nodaily.names.mean()),
        'no_decision_capital_fraction_mean_all_signal_days': float(nodaily.capital_fraction.mean()),
        'no_decision_names_last_signal': int(nodaily.names.iloc[-1]),
        'no_decision_capital_fraction_last_signal': float(nodaily.capital_fraction.iloc[-1]),
        'no_decision_names_held_at_account_end': len(no_end_held),
        'no_decision_indicative_value_at_account_end': float(no_end_held.market_value.sum()),
        'no_decision_capital_fraction_at_account_end': float(no_end_held.weight.sum()),
        'no_decision_end_units_unchanged_from_last_signal': bool(np.isclose(no_end_held.index_units, no_end_held.current_units, rtol=1e-11, atol=1e-10).all()),
        'no_decision_end_tickers': '|'.join(sorted(no_end_held.ticker)),
        'no_decision_signal_price_unavailable_order_rows': int(no.signal_reservation_reasons.str.contains('SIGNAL_CLOSE_UNAVAILABLE', regex=False).sum()),
        'no_decision_reason_counts_nonexclusive_json': js(reserve_reasons),
        'preserved_execution_orders': int(preserved.order_id.nunique()),
        'preserved_execution_days': int(preserved.execution_date.nunique()),
        'preserved_existing_units_unchanged_orders': int(preserved.existing_units_unchanged.sum()),
        'all_reserved_names_mean': float(ctx.final_reserved_slots.mean()), 'all_reserved_capital_fraction_mean': float(ctx.final_reserved_weight.mean()),
        'all_reserved_names_last_signal': int(ctx.final_reserved_slots.iloc[-1]), 'all_reserved_capital_fraction_last_signal': float(ctx.final_reserved_weight.iloc[-1]),
        'operational_notification_rows': len(ops), 'operational_notifications_without_position': int((~ops.had_position).sum()),
        'operational_held_order_rows': len(opheld), 'operational_held_signal_days': int(opheld.signal_date.nunique()),
        'operational_held_unique_tickers': int(opheld.ticker.nunique()),
        'operational_held_capital_fraction_mean_all_signal_days': float(op_daily_capital.mean()),
        'operational_names_held_at_account_end': len(op_end),
        'operational_indicative_value_at_account_end': float(op_end.market_value.sum()),
        'operational_capital_fraction_at_account_end': float(op_end.weight.sum()),
        'operational_end_tickers': '|'.join(sorted(op_end.ticker)),
        'operational_actual_fill_orders': int(optrade.order_id.nunique()), 'operational_actual_exit_fills': int(optrade.action.eq('EXIT').sum()),
        'operational_rejected_held_orders': int(opreject.order_id.nunique()), 'operational_rejected_units_unchanged_orders': int(opreject.existing_units_unchanged.sum()),
        'execution_rejected_orders': int(rejected.order_id.nunique()), 'execution_rejected_signal_days': int(rejected.signal_date.nunique()),
        'execution_rejected_execution_days': int(rejected.execution_date.nunique()),
        'rejected_sell_existing_position_orders': int((rejected.side.eq('SELL') & rejected.held_before).sum()),
        'rejected_sell_existing_units_unchanged_orders': int((rejected.side.eq('SELL') & rejected.existing_units_unchanged).sum()),
        'execution_limit_breakdown_json': js(reasons),
        'buy_fills_with_capacity_policy_applied': int(buys.capacity_enforced.sum()),
        'buy_fills_at_recorded_one_pct_ADV_boundary': len(capacity_boundary),
        'buy_cash_scale_less_than_one_days': int(daily.buy_cash_scale.lt(1 - 1e-9).sum()),
        'actual_names_mean_account_days': float(daily.actual_name_count.mean()), 'actual_names_end': int(daily.actual_name_count.iloc[-1]),
        'cash_weight_mean_account_days': float(daily.cash_weight.mean()), 'cash_weight_end': float(daily.cash_weight.iloc[-1]),
        'certified_close_days': int(daily.certified_nav.notna().sum()), 'stale_close_days': int(daily.valuation_status.eq('stale').sum()),
        'unknown_close_days': int(daily.valuation_status.eq('unknown').sum()),
        'stale_position_days': int(positions.stale.sum()), 'unknown_position_days': int(positions.unknown.sum()),
        'stale_positions_end': int(daily.stale_count.iloc[-1]), 'unknown_positions_end': int(daily.unknown_count.iloc[-1]),
        'full_window_certified': bool(daily.certified_nav.notna().all()),
        'certified_contiguous_windows_json': js(certified_runs),
        'initial_certified_prefix_end': prefix['end'] if prefix else None,
        'initial_certified_prefix_days': prefix['sessions'] if prefix else 0,
        'full_window_indicative_nav_return': float(daily.nav.iloc[-1] / start_nav - 1),
        'full_window_return_is_certified': bool(daily.certified_nav.notna().all()),
        'source_hashes_json': js(original_hashes),
    }
    # These are saved-row joins, not an alternative account reconstruction.
    assert len(preserved) == len(no)
    assert preserved.existing_units_unchanged.all()
    assert all(sha(path) == original_hashes[name] for name, path in sources.items())
    return columns, daily


def main():
    folders = sorted(p for p in BASE.iterdir() if p.is_dir())
    assert len(folders) == 14
    rows, days = [], {}
    for folder in folders:
        row, daily = summarize(folder)
        rows.append(row)
        days[folder.name] = daily
    result = pd.DataFrame(rows)
    result.to_csv(HERE / 'MECHANISMS_2026.csv', index=False, encoding='utf-8-sig')
    by = result.set_index('policy')
    lines = ['# 2026 已存结果：交易和保留机制', '',
        '只分析本版本 `evaluation_2026/cost_10` 的 14 个原账户，1/2—9/24 共 183 个账户日，1/2—9/22 共 181 个信号日。全部日期和后来出现的未知证券均保留。脚本只读原始记录，没有模型调用、重训、参数更改、回放、删除股票、拼接正常日或收益反事实。', '',
        '## 可以辨认的行为差异', '',
        '| 策略 | 实际新开仓／增持／减持／退出 | 主动退出目标／实际退出 | 无决策平均名额／末日名额 | 平均无决策资本占比／末日占比 | 实际费用 | 认证收盘日 |',
        '|---|---|---|---|---|---:|---:|']
    for name in FOCUS:
        r = by.loc[name]
        lines.append(f"| {name} | {r.actual_initial_buy_fills}/{r.actual_increase_fills}/{r.actual_reduce_fills}/{r.actual_exit_fills} | {r.model_active_exit_orders}/{r.model_active_exit_actual_flatten_orders} | {r.no_decision_names_mean_all_signal_days:.2f}/{r.no_decision_names_held_at_account_end} | {r.no_decision_capital_fraction_mean_all_signal_days:.2%}/{r.no_decision_capital_fraction_at_account_end:.2%} | {r.actual_fees:,.2f} | {r.certified_close_days}/183 |")
    lines += ['',
        '平均保留名额和资本比以全部 181 个信号日为分母，含零占用日；末日为 9/24 实际持仓中仍对应 9/22 无决策保留指令的仓位。资本比是账本指示性估值比例；若标记陈旧，就不是核证可变现资本。运营限制保留另计，不混入无决策表。', '',
        '训练后的 RL 更频繁地重新选择证券并退出：实际新开仓和主动退出均多于零更新对照；MLP 的主动退出很少，更多成交为旧仓增减。新开仓指该次从零仓位买入，允许同一证券退出后再次进入，不是其全期首次买入。RL 的实际费用高于 zero，且 RL 平均现金比例更高。以上是各自已经走出的账户路径，不能单凭这些差异证明学习有效、无效或给收益差额作精确因果分解。', '',
        '| 策略 | 无决策保留涉及信号日 | 平均／终点现金比 | 显式正目标平均敞口 | 实际费用／初始资金 |', '|---|---:|---|---:|---:|']
    for name in FOCUS:
        r = by.loc[name]
        lines.append(f"| {name} | {r.no_decision_signal_days}/181（{r.no_decision_fraction_of_signal_days:.2%}） | {r.cash_weight_mean_account_days:.2%}/{r.cash_weight_end:.2%} | {r.model_raw_positive_target_exposure_mean:.2%} | {r.actual_fees_fraction_initial_capital:.2%} |")
    lines += ['',
        '正目标敞口只统计显式模型输出，不包含另行预留单位。目标、成交、无决策保留分别来自原字典／目标表、trades 和 PRESERVED_UNITS 记录；不能把大量未持有证券的 MODEL_ZERO_ALLOCATION 算作卖出。所有保留记录都按 order_id 与执行收盘持仓连接，确认原有单位未变；没有把异质证券的指数单位跨股票相加。', '',
        '## 运营事件与执行限制', '',
        '每个策略都有 127 条 EXAS 全局运营通知。只有 `joint_rl_ensemble` 当时真正持有 EXAS：127 个持仓日、1 只证券，127 次已知卖出限制，单位持续保留，实际运营退出成交为 0。其余 13 策略的通知均无仓位，实际持仓运营退出次数为 0。不得将 127 条通知称作 127 次已完成退出；现金权利也未当作已到账现金。', '',
        f"RL 期末另保留 EXAS 1 个运营受限名称，陈旧账面值 {by.loc['joint_rl_ensemble', 'operational_indicative_value_at_account_end']:,.2f}，占指示性 NAV {by.loc['joint_rl_ensemble', 'operational_capital_fraction_at_account_end']:.2%}；它不包含在上表的 10 个无决策名称内。", '',
        '| 策略 | 拒绝订单 | 拒单涉及执行日 | 具体原因（订单数；执行日数；已有单位原样保留数） |', '|---|---:|---:|---|']
    for name in by.index:
        r = by.loc[name]
        breakdown = json.loads(r.execution_limit_breakdown_json)
        label = '; '.join(f"{x['reason']}:{x['side']} {x['orders']};{x['execution_days']};{x['existing_units_unchanged_at_execution_close']}" for x in breakdown) or '无已记录拒单'
        lines.append(f'| {name} | {r.execution_rejected_orders} | {r.execution_rejected_execution_days} | {label} |')
    lines += ['',
        '订单口径为唯一 order_id；同一证券跨多个日期的受限卖出会多次计数，不是多次成功交易。原因细分的涉及日可能重叠，不能相加当总日数。RL 共 146 条拒单，其中 127 条属于上述持续 EXAS 限制；其余 19 条为 15 条价格未核证、1 条缺价格行、3 条实际名额上限。zero 的 6 条、MLP 的 15 条与基准的 5 条没有 EXAS 持仓通知混入。', '',
        '容量的 `capacity_enforced=True` 只表示执行过该规则，不等于容量实际卡住。CSV 另统计成交名义额恰好达到已存信号 ADV 1% 边界的买单，此数不冒充拒单数。全部账户的已存 buy_cash_scale 均未低于 1；不能据此推断取消费用或保留仓位后仍会走同一路径。', '',
        '费用是实际双边成交名义额乘单边 10bp 的现金支出。累计成交额、次数和费用描述活动量；没有用它们直接分摊收益，也没有把费用加回后宣称获得无费用反事实收益。', '',
        '## 估值与比较资格', '',
        '| 策略 | 全窗认证／陈旧／无标记日 | 首段连续认证截至 | 全窗指示性净值变化 | 全窗可作认证比较 |', '|---|---|---|---:|---|']
    for name in by.index:
        r = by.loc[name]
        lines.append(f"| {name} | {r.certified_close_days}/{r.stale_close_days}/{r.unknown_close_days} | {r.initial_certified_prefix_end} | {r.full_window_indicative_nav_return:.2%} | {'是' if r.full_window_certified else '否'} |")
    lines += ['',
        '“无标记日为零”不等于估值完整：陈旧价格仍能产生指示性 NAV，却没有 certified NAV。HGB／两风险版本等存在无决策保留，但当日仍有可核证价格，因此保留本身不必然造成估值不完整。CSV 保留每个连续认证区间，不把后续认证片段拼为连续收益。', '',
        '这里的认证限定为该已存账本的价格指数坐标估值资格，不等于完整股票池认证、原始股数或股东总收益，也不证明模型具有预测优势。', '',
        '首段连续认证截止日期／天数只说明完整 183 日研究对象何时失去认证资格，不据此重新选共同短窗、计算短窗收益或替代原研究对象。', '',
        '完整 183 日 RL、zero、MLP 和基准的回报均只能作为指示性记录，不能据此确认全窗优劣，也不能精确把收益差额归于模型学习、保留单位、费用或限制。未运行这些因素的反事实实验。', '',
        '## 文件与口径', '',
        '`MECHANISMS_2026.csv` 每策略一行，含原模型正目标／退出、实际四类成交、名义额／费用、无决策与全保留容量、拒单分原因／天数／实际保留、运营通知与有仓位行动、认证区间，以及各原始输入 SHA256。`MECHANISMS_2026_read.py` 可仅凭同批已存文件重建摘要；源文件读前读后哈希一致。', '',
        f"摘要 CSV SHA256：`{sha(HERE / 'MECHANISMS_2026.csv')}`。", '']
    (HERE / 'MECHANISMS_2026_NOTES.md').write_text('\n'.join(lines), encoding='utf-8')
    print(result.loc[result.policy.isin(FOCUS), ['policy', 'actual_trade_fills', 'model_active_exit_orders',
          'no_decision_names_mean_all_signal_days', 'no_decision_capital_fraction_at_account_end',
          'execution_rejected_orders', 'operational_held_order_rows', 'certified_close_days']].to_string(index=False))
    print('PASS: summarized all 14 saved policies; zero fits, policy calls or replays.')


if __name__ == '__main__':
    main()
