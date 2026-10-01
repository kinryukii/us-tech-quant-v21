"""Read saved ledgers only; no model imports, fitting, prediction or replay."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'evaluation_2025' / 'cost_10'
OUT = Path(__file__).resolve().parent
POLICIES = ['joint_ridge', 'joint_elastic_net', 'joint_logistic', 'joint_hgb',
            'joint_q10', 'joint_q50', 'joint_q90', 'joint_quantile_risk',
            'joint_mlp', 'joint_rl_ensemble', 'joint_rl_zero_control', 'hgb_return_baseline']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

rows = []
dates = None
for policy in POLICIES:
    p = BASE / policy
    d = pd.read_parquet(p / 'daily.parquet').sort_values('date')
    t = pd.read_parquet(p / 'trades.parquet')
    h = pd.read_parquet(p / 'positions.parquet')
    meta = json.loads((p / 'metadata.json').read_text(encoding='utf-8'))
    idx = pd.DatetimeIndex(d['date'])
    assert len(idx) == 250 and idx.is_unique
    assert idx.min() == pd.Timestamp('2025-01-02') and idx.max() == pd.Timestamp('2025-12-31')
    if dates is None:
        dates = idx
    assert idx.equals(dates), policy
    assert d.valuation_status.eq('certified').all(), policy
    assert d[['open_stale_count','open_unknown_count','stale_count','unknown_count']].eq(0).all().all()
    assert np.isfinite(d[['nav','certified_nav','cash']].to_numpy()).all()
    assert np.allclose(d.nav, d.certified_nav, rtol=0, atol=1e-8)
    assert meta['cost_bps_one_way'] == 10 and meta['initial_cash'] == 1_000_000
    assert meta['initial_positions'] == {} and not meta['terminal_liquidation']
    assert not meta['shareholder_total_return_certified']
    if len(h):
        assert not h[['stale','unknown']].any().any()
        assert pd.DatetimeIndex(h.date.unique()).isin(dates).all()
        held_weight = h.groupby('date').weight.sum().reindex(dates, fill_value=0)
    else:
        held_weight = pd.Series(0., index=dates)
    assert np.allclose(held_weight, d.gross_exposure, rtol=0, atol=1e-10)
    nav = d.nav.to_numpy(float)
    daily_ret = nav[1:] / nav[:-1] - 1
    assert len(daily_ret) == 249 and np.isfinite(daily_ret).all()
    assert np.allclose(daily_ret, d.net_return.iloc[1:], rtol=0, atol=1e-12)
    fee = float(t.transaction_cost.sum()) if len(t) else 0.
    assert np.isclose(fee, d.transaction_cost_amount.sum(), rtol=0, atol=1e-6)
    traded = float(t.notional.sum()) if len(t) else 0.
    assert np.isclose(traded, d.traded_notional.sum(), rtol=0, atol=1e-5)
    dd = nav / np.maximum.accumulate(nav) - 1
    rows.append(dict(
        policy=policy, window_start=str(dates[0].date()), window_end=str(dates[-1].date()),
        nav_dates=250, return_observations=249, certified_days=250,
        open_stale_or_unknown_days=0, close_stale_or_unknown_days=0,
        initial_cash=meta['initial_cash'], end_nav=nav[-1],
        net_book_return_pct=100 * (nav[-1] / nav[0] - 1),
        max_drawdown_pct=100 * dd.min(),
        daily_return_std_pct=100 * daily_ret.std(ddof=1),
        annualized_vol_pct=100 * daily_ret.std(ddof=1) * np.sqrt(252),
        annualization_days=252, std_ddof=1,
        avg_cash_weight_pct=100 * (d.cash / d.nav).mean(),
        avg_stock_weight_pct=100 * held_weight.mean(),
        avg_position_count=d.actual_name_count.mean(),
        transaction_cost_amount=fee, transaction_cost_pct_initial=100 * fee / meta['initial_cash'],
        buy_notional=d.buy_notional.sum(), sell_notional=d.sell_notional.sum(),
        traded_notional=traded, total_oneway_turnover=d.turnover.sum(),
        avg_daily_oneway_turnover=d.turnover.mean(), trade_count=len(t),
        blocked_order_count=int(d.blocked_order_count.sum()),
        shareholder_total_return_certified=False,
        daily_sha256=sha(p/'daily.parquet'), trades_sha256=sha(p/'trades.parquet'),
        positions_sha256=sha(p/'positions.parquet'), metadata_sha256=sha(p/'metadata.json')))

metrics = pd.DataFrame(rows).set_index('policy')
for base, label in [('hgb_return_baseline','hgb'), ('joint_rl_zero_control','rl_zero')]:
    for col, short in [('net_book_return_pct','return'), ('max_drawdown_pct','mdd'),
                       ('annualized_vol_pct','annvol'), ('avg_cash_weight_pct','cash')]:
        metrics[f'delta_{short}_vs_{label}_pp'] = metrics[col] - metrics.loc[base,col]
    metrics[f'delta_fees_vs_{label}_amount'] = metrics.transaction_cost_amount - metrics.loc[base,'transaction_cost_amount']
    metrics[f'delta_turnover_vs_{label}'] = metrics.total_oneway_turnover - metrics.loc[base,'total_oneway_turnover']
metrics.reset_index().to_csv(OUT/'VALIDATION_2025_METRICS.csv', index=False, encoding='utf-8-sig', float_format='%.12g')

rl = metrics.loc['joint_rl_ensemble']; z = metrics.loc['joint_rl_zero_control']
mlp = metrics.loc['joint_mlp']; hgb = metrics.loc['hgb_return_baseline']
complete = json.loads((BASE/'COMPLETE.json').read_text(encoding='utf-8'))
table = ['| 策略 | 净账面回报 % | 最大回撤 % | 日波动 % | 年化波动 % | 平均现金 % | 费用/初始资金 % | 单边换手倍数 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|']
for name, r in metrics.iterrows():
    table.append(f'| {name} | {r.net_book_return_pct:.4f} | {r.max_drawdown_pct:.4f} | {r.daily_return_std_pct:.4f} | {r.annualized_vol_pct:.4f} | {r.avg_cash_weight_pct:.4f} | {r.transaction_cost_pct_initial:.4f} | {r.total_oneway_turnover:.4f} |')

notes = f'''# 2025 年共同完整窗口经济比较（保存账本只读）

本次仅汇总本版本已保存的 12 个策略账本，未加载模型、执行预测、拟合或账户回放，未更改参数、种子、股票集合或估值日期。指标源是 `evaluation_2025/cost_10/<policy>/daily.parquet`、`trades.parquet`、`positions.parquet`、`metadata.json`。每份输入的 SHA-256 已写入指标 CSV。

## 窗口和经济口径

- 12 策略日期序列逐项完全相同：2025-01-02 至 2025-12-31，共 250 个收盘 NAV；保留首日初始现金，形成 249 个相邻收盘收益观测。没有删日、跨缺口拼接或只取 certified 子段。
- 全部 3,000 个策略日的 `valuation_status=certified`、`nav=certified_nav`，开盘与收盘 stale/unknown 计数均为零；保存的持仓记录也无 stale/unknown。这里是保存账本的资格核对，不是重新抓取或审计历史行情。
- **certified 是价格指数坐标下的 NAV 估值资格，不是股东总收益认证**。全部 metadata 明确 `unit=price-index units; shares alias is not raw shares`、`shareholder_total_return_certified=false`。费用和现金也是本账本金额，不代表已核证的现实可兑现股息、拆并股股份或清算现金。
- 共同初始现金 1,000,000，无初始持仓。净账面回报为末 NAV / 首 NAV − 1，已经扣除保存的交易费用，未再扣一次；不将此期间回报外推成年复合回报。
- 最大回撤为每个收盘 NAV / 截至当日最高收盘 NAV − 1 的最小值，含首日初值；表中为非正数，越接近零越浅。仅测收盘回撤，不代表盘中最大损失。
- 日波动是全部 249 个日简单收益的样本标准差（ddof=1）。年化波动 = 日标准差 × √252，只是统一换算，不意味着独立同分布或一年外推可靠性。
- 平均现金比例为 250 日 `cash/nav` 的算术均值，平均股票权重由保存的每日持仓权重求和，再按同一 250 日平均（首日空仓为零），与 `gross_exposure` 一致。平均持仓数亦包含首日。
- 单边交易成本为 10 bps；累计费用是已成交 `transaction_cost` 总和，与 daily 费用核对一致。`费用/初始资金` 是费用金额除以初始 1,000,000，不能直接等同于另一个零费用策略的回报差。
- 单边换手 = 每日 0.5 ×（买入名义额 + 卖出名义额）/ 当日开盘交易前 NAV，再对 250 日求和。CSV 同时给每日均值及原始名义额；累计换手单位是倍数。交易与 daily 名义额一致。没有重建零费用反事实，也没有期末强制平仓费用。
- metadata 的仓位约束为最多 20 名、单名目标最多 10%、总目标最多 95%；买入容量上限为 ADV 的 1%，卖出未使用同一容量约束。此处仅沿用既有规则；不是对实际容量或流动性的证明。

## 结果

{chr(10).join(table)}

HGB 收益基线在这一个完整年份的回报为 **{hgb.net_book_return_pct:.4f}%**，最大回撤 **{hgb.max_drawdown_pct:.4f}%**，年化波动 **{hgb.annualized_vol_pct:.4f}%**，平均现金 **{hgb.avg_cash_weight_pct:.4f}%**。它是比较基准，不是与所有联合训练策略匹配的训练消融。

RL 训练后组合为 **{rl.net_book_return_pct:.4f}%**，配对零更新对照为 **{z.net_book_return_pct:.4f}%**，差 **{rl.delta_return_vs_rl_zero_pp:+.4f} 个百分点**；最大回撤差 **{rl.delta_mdd_vs_rl_zero_pp:+.4f} 个百分点**（正表示回撤较浅），年化波动差 **{rl.delta_annvol_vs_rl_zero_pp:+.4f} 个百分点**，平均现金差 **{rl.delta_cash_vs_rl_zero_pp:+.4f} 个百分点**。RL 费用 **{rl.transaction_cost_amount:.2f}**、零更新 **{z.transaction_cost_amount:.2f}**，费用差 **{rl.delta_fees_vs_rl_zero_amount:+.2f}** 账本金额；单边换手分别 **{rl.total_oneway_turnover:.4f}** 与 **{z.total_oneway_turnover:.4f}** 倍。RL 相对 HGB 的回报差为 **{rl.delta_return_vs_hgb_pp:+.4f} 个百分点**，最大回撤差 **{rl.delta_mdd_vs_hgb_pp:+.4f} 个百分点**，年化波动差 **{rl.delta_annvol_vs_hgb_pp:+.4f} 个百分点**。

直接效用 MLP 的回报为 **{mlp.net_book_return_pct:.4f}%**，最大回撤 **{mlp.max_drawdown_pct:.4f}%**，年化波动 **{mlp.annualized_vol_pct:.4f}%**，平均现金 **{mlp.avg_cash_weight_pct:.4f}%**。RL 与它的回报差为 **{rl.net_book_return_pct-mlp.net_book_return_pct:+.4f} 个百分点**；这是不同训练方案的经济比较，不能称为仅改变 RL 更新的严格消融。

`joint_q10` 保存的 250 日全为现金，零笔交易、零费用、零回报、零波动。零风险来自没有风险敞口，不能解读为具备收益预测能力。其他模型与两个基准的回报、回撤、波动、现金、费用及换手差均在 CSV 中逐策略列出。

## RL 配对对照与证据边界

- `joint_neural_v2.py:236-247`：validation 阶段历史上采用 2023-2024 训练窗口；每个模型初始化后立即保存 `_zero.pt`，再进行参数更新。`joint_neural_v2.py:271-278` 与 `adapters_v2.py:20-22` 显示 RL 训练组和零更新组使用同样两种子、归一化、架构和适配路径，差别是读取更新后的权重还是保存的初始权重。两组均在本次同一 2025 账本规则和日期下比较，账户状态随各自动作分化属于策略效果。
- 保存的 `TRAIN_RECEIPT.json` 固定种子为 20260927 和 20260928，RL 四轮；直接效用 MLP 使用一个种子、六轮，目标和更新方法不同。因此零更新对照是 RL 的配对控制，不是 MLP 的配对控制；HGB、线性、分位数等比较也不是单变量因果消融。
- 这两个固定种子在 RL 策略内形成一个集成账户，并非两个独立验证样本。本结果没有估计显著性、置信区间、种子稳健性或未来获利概率。平均现金和风险敞口不同，回报差不能直接解释成相同风险下的超额收益。
- 本窗口是 2025 验证窗口，并非本次新增的盲测；同时比较 12 种方法有多重比较和事后选择限制。本次未据结果挑选新参数、重训或改策略。不能由这一个年份证明哪类模型普遍最好。
- 保存 `COMPLETE.json` 状态为 `{complete['status']}`，`fit_attempts={complete['fit_attempts']}`、`sources_unchanged={str(complete['sources_unchanged']).lower()}`、`full_pool_complete={str(complete['full_pool_complete']).lower()}`。这是当前版本和数据资格边界下的诊断经济比较，不是完整 13F 股票池覆盖声明，也不是股东总收益认证。

## 可追溯输入

- `evaluation_2025/cost_10/COMPLETE.json` SHA-256: `{sha(BASE/'COMPLETE.json')}`
- `evaluation_2025/cost_10/FROZEN_BEFORE_REPLAY.json` SHA-256: `{sha(BASE/'FROZEN_BEFORE_REPLAY.json')}`
- `neural_artifacts/TRAIN_RECEIPT.json` SHA-256: `{sha(ROOT/'neural_artifacts'/'TRAIN_RECEIPT.json')}`
- `joint_neural_v2.py` SHA-256: `{sha(ROOT/'joint_neural_v2.py')}`
- `adapters_v2.py` SHA-256: `{sha(ROOT/'adapters_v2.py')}`
- `engine_v2.py` SHA-256: `{sha(ROOT/'engine_v2.py')}`
- 各策略账本、交易、持仓、metadata 的逐文件哈希见 `VALIDATION_2025_METRICS.csv`。本脚本只读取上述保存数据并汇总，不重新运行技术验证或抽样流程。
'''
(OUT/'VALIDATION_2025_NOTES.md').write_text(notes, encoding='utf-8')
print(metrics[['net_book_return_pct','max_drawdown_pct','annualized_vol_pct','avg_cash_weight_pct','transaction_cost_amount','total_oneway_turnover']].to_string())
print('COMMON_250_DAY_VALUATION_CHECK_PASS; 12 saved ledgers; no models executed.')
