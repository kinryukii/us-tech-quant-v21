"""Render descriptive figures from reconciled 2025 records only."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
data = json.loads((OUT / 'cash_attribution/CHECKS.json').read_text(encoding='utf-8'))
stages = data['mean_cash_stages']
plt.rcParams.update({'font.family': 'Microsoft YaHei', 'axes.unicode_minus': False,
                     'font.size': 10, 'figure.facecolor': '#f7f9fc', 'axes.facecolor': '#f7f9fc'})
fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={'width_ratios': [1.06, 1]})
fig.suptitle('2025 等权融合：现金与损益的原账本分解', fontsize=19, weight='bold', x=.07, ha='left')
ax = axes[0]
values = [stages['average_target_cash_weight'] * 100,
          stages['post_top20_cash_weight'] * 100,
          stages['actual_open_cash_weight_post_fee_nav'] * 100,
          stages['actual_close_cash_weight'] * 100]
ax.bar(range(4), values, width=.60, color=['#8ba2bf', '#dc8d40', '#44799d', '#224b6c'])
for i, v in enumerate(values):
    ax.text(i, v + .8, f'{v:.2f}%', ha='center', weight='bold', fontsize=12)
ax.set_xticks(range(4), ['成员平均目标\n含保留仓位', 'TOP20 后目标', '实际开盘\n执行后', '实际收盘'])
ax.set_ylim(0, 49)
ax.set_ylabel('现金占账户净值（%）')
ax.set_title('现金：TOP20 截断增加 19.32 个百分点', loc='left', pad=18, weight='bold')
ax.text(.01, -.23, '同一账户的 248 组信号→执行配对。容量限制再增约 1.13 个百分点。\n算术平均本身不额外增现金；250 日全样本平均现金为 40.28%。',
        transform=ax.transAxes, fontsize=9, color='#43566b', va='top')

ax = axes[1]
steps = [data['overnight_pnl'] / 1000, data['intraday_pnl'] / 1000, -data['fees'] / 1000]
base = 0.
for i, step in enumerate(steps):
    endpoint = base + step
    ax.bar(i, abs(step), bottom=min(base, endpoint), width=.60, color='#35857d' if step > 0 else '#bf5962')
    ax.text(i, max(base, endpoint) + 4, f'{step:+.2f}', ha='center', weight='bold', fontsize=12)
    ax.plot([i + .3, i + .7], [endpoint, endpoint], color='#acb8c6', lw=1, linestyle='--')
    base = endpoint
ax.bar(3, abs(base), bottom=min(0., base), width=.60, color='#224b6c')
ax.text(3, base - 5, f'{base:+.2f}', ha='center', va='top', weight='bold', fontsize=12)
ax.axhline(0, lw=.9, color='#65798d')
ax.set_xticks(range(4), ['隔夜价格损益', '盘中价格损益', '交易费用', '全年净损益'])
ax.set_ylim(-42, 202)
ax.set_ylabel('千美元（初始资金 100 万美元）')
ax.set_title('损益：价格盈利 4.77 万，费用 6.70 万', loc='left', pad=18, weight='bold')
ax.text(.01, -.23, '原回放 250 日，净收益 −1.93%。费用使原路径净损益转负。\n这是账本恒等分解，不是免手续费重跑或交易动作的因果收益。',
        transform=ax.transAxes, fontsize=9, color='#43566b', va='top')
for ax in axes:
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#a7b4c3')
    ax.spines['bottom'].set_color('#a7b4c3')
    ax.grid(axis='y', alpha=.12)
    ax.set_axisbelow(True)
fig.subplots_adjust(left=.065, right=.985, top=.78, bottom=.28, wspace=.24)
fig.savefig(OUT / 'cash_and_pnl.png', dpi=160, facecolor=fig.get_facecolor())
fig.savefig(OUT / 'cash_and_pnl.svg', facecolor=fig.get_facecolor())
plt.close(fig)
print('Rendered cash_and_pnl.png and .svg from CHECKS.json')
