"""Readable views of main frozen paths; complete originals remain in Parquet."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'delivery_tables'


def main():
    OUT.mkdir(exist_ok=True)
    files = []
    for year in (2025, 2026):
        for method in ('M0', 'M1'):
            folder = ROOT / f'evaluation_{year}/cost_10/{method}'
            assert (folder/'DONE.json').is_file()
            for source, label in [('daily', 'daily_nav_cash'), ('daily_meta_audit', 'daily_meta_coefficients'),
                                  ('trades', 'all_trades')]:
                target = OUT / f'{year}_cost10_{method}_{label}.csv'
                pd.read_parquet(folder/(source+'.parquet')).to_csv(target, index=False)
                files.append(str(target))
            decisions = pd.read_parquet(folder/'target_decisions.parquet')
            date = decisions.signal_date.max()
            target = OUT / f'{year}_cost10_{method}_last_signal_all_decisions.csv'
            decisions.loc[decisions.signal_date.eq(date)].to_csv(target, index=False)
            files.append(str(target))
            positions = pd.read_parquet(folder/'positions.parquet')
            latest = pd.read_parquet(folder/'daily.parquet', columns=['date']).date.max()
            target = OUT / f'{year}_cost10_{method}_last_valuation_positions.csv'
            positions.loc[positions.date.eq(latest)].to_csv(target, index=False)
            files.append(str(target))
    (OUT/'README.md').write_text(
        '# 冻结主成本路径的CSV查看表\n\n'
        '这些表逐值导出2025／2026单边10bp完整Parquet工件，不新增推理或重新选模型。'
        'daily_meta_coefficients含每日有效系数的均值／范围和目标现金；原逐股票逐动作系数及贡献仍见各路径action_diagnostics.parquet。'
        'all_trades为完整年度成交；last_signal_all_decisions保留最新信号的买卖、退出及保留持仓语义，不能只按非零仓位筛掉退出动作。'
        'last_valuation_positions是最新估值日实际持仓，可能与信号目标不同。\n\n'
        '这些是历史研究回放查看表。2026股票池、价格认证和非盲测限制与主报告相同，不是当前交易建议。\n', encoding='utf-8')
    (OUT/'EXPORT_RECEIPT.json').write_text(json.dumps(dict(status='PASS',
        fit_calls=0, inference_calls=0, replay_calls=0, exports=files), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='PASS', exported_csvs=len(files)), ensure_ascii=False))


if __name__ == '__main__': main()
