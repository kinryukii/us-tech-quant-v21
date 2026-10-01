"""Replay new cooperative layers through the one existing frozen account engine."""
from pathlib import Path
import argparse
import json
import sys
import time

import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
BASE_ROOT = ROOT.parent / 'a2_top20_multimodel_selection_20260928_9231'
sys.path.insert(0, str(BASE_ROOT))
import evaluate as old
from engine_v2 import run_replay
from active_13f_gate import validate_active_13f_pool
sys.path.insert(0, str(ROOT))
from policy import CooperativePolicy, NAMES


def new_artifacts():
    files = [ROOT / p for p in ['EXPERIMENT_CONTRACT.md', 'policy.py', 'replay.py',
                                'data_context.py', 'meta_models.py', 'gate.py']]
    for directory in ['meta_artifacts', 'gate_artifacts']:
        files += [p for p in (ROOT / directory).rglob('*') if p.is_file()
                  and p.suffix in ['.json', '.joblib', '.npz', '.pt']]
    return sorted(set(files))


def main(year, cost, resume=False):
    assert cost in [5, 10, 25] and (year == 2026 or cost == 10)
    out = ROOT / f'evaluation_{year}' / f'cost_{cost:g}'
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'COMPLETE.json').exists():
        raise RuntimeError('COMPLETED_REPLAY_PRESERVED')
    guard = old.forbid_fitting()
    import scipy.optimize
    def denied_nnls(*args, **kwargs):
        guard['attempts'] += 1
        raise RuntimeError('FIT_FORBIDDEN_DURING_EVALUATION')
    scipy.optimize.nnls = denied_nnls
    if year == 2026:
        sources = [old.QUALIFIED / 'test_features_context.parquet', old.QUALIFIED / 'test_prices.parquet',
                   old.DATA / 'calendar.parquet', old.QUALIFIED / 'operational_exit_evidence.csv']
        panel = pd.read_parquet(sources[0]); prices = pd.read_parquet(sources[1])
        calendar = pd.DatetimeIndex(pd.read_parquet(sources[2]).query('is_test').trade_date)
        last = '2026-09-22'; stage = 'final'
    else:
        sources = [old.DATA / 'pre2026_joint_context.parquet', old.PRICE]
        panel = pd.read_parquet(sources[0]); panel = panel.loc[panel.signal_date.ge('2025-01-01')]
        prices = pd.read_parquet(sources[1])
        calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')
                            & prices.trade_date.ge('2025-01-01'), 'trade_date'].unique()))
        last = '2025-12-29'; stage = 'validation'
    sources += [old.DATA / 'quarter_timing.csv', BASE_ROOT / 'acceptance_diagnostics/evidence/FINAL_EVIDENCE_SUMMARY.json']
    panel = panel.loc[panel.signal_date.le(last)].copy()
    qualification = validate_active_13f_pool(panel.loc[panel.new_buy_eligible],
        pd.read_csv(old.DATA / 'quarter_timing.csv'),
        quarter_column='quarter' if year == 2026 else 'active_13f_quarter')
    qualification['latest_restatement_membership_certified'] = False
    qualification['qualification_scope'] = 'QUARTER_CLOCK_ONLY_INHERITED_DATA_LIMITATIONS'
    old.write(out / 'ACTIVE_13F_AUDIT.json', qualification)
    panel = panel[['signal_date', 'ticker', 'new_buy_eligible', *old.FEATURES]].copy()
    assert panel.signal_date.dt.year.eq(year).all() and np.isfinite(panel[old.FEATURES]).all().all()
    hashes = {str(p): old.sha(p) for p in old.model_files() + new_artifacts() + sources}
    frozen = out / 'FROZEN_BEFORE_REPLAY.json'
    binding = dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(), year=year, cost_bps=cost,
        roster=NAMES, source_sha256=hashes, fit_2026_rows=0, full_pool_complete=False, blind_test=False)
    if frozen.exists():
        assert resume, 'INTERRUPTED_REPLAY_REQUIRES_EXPLICIT_RESUME'
        previous = json.loads(frozen.read_text(encoding='utf-8'))
        assert previous['source_sha256'] == hashes and previous['roster'] == NAMES
    else:
        old.write(frozen, binding)
    asofs = old.clocks(calendar); ops = old.operations(calendar, asofs) if year == 2026 else {}
    metrics = []
    for name in NAMES:
        folder = out / name
        if (folder / 'DONE.json').exists() and resume:
            metrics.append(json.loads((folder / 'DONE.json').read_text(encoding='utf-8'))); continue
        if folder.exists():
            raise RuntimeError(f'INCOMPLETE_DERIVED_OUTPUT_PRESERVED:{folder}')
        folder.mkdir(); started = time.monotonic()
        actor = CooperativePolicy(name, stage)
        with threadpool_limits(limits=2), torch.no_grad():
            result = run_replay(prices, calendar, panel, actor, candidate=name, cost_bps=cost,
                capacity_fraction=.01, signal_start=f'{year}-01-01', signal_end=last,
                signal_asof=asofs, operational_exits_by_signal=ops)
        for key in old.LEDGERS:
            getattr(result, key).to_parquet(folder / f'{key}.parquet', index=False)
        old.write(folder / 'metadata.json', result.metadata)
        row = old.summarize(result, name, year, cost)
        row['price_gate_only_return'] = row.pop('certified_retrospective_return', None)
        row.update(certified_retrospective_return=None, formal_performance=False,
                   metric_status='RESEARCH_ONLY_INHERITED_UNIVERSE_ACTION_AND_ARRIVAL_LIMITATIONS',
                   seconds=round(time.monotonic() - started, 2))
        old.write(folder / 'DONE.json', row); metrics.append(row)
        pd.DataFrame(metrics).to_csv(out / 'comparison.csv', index=False)
        print(json.dumps(old.clean(row)), flush=True)
    assert guard['attempts'] == 0
    assert all(old.sha(p) == digest for p, digest in hashes.items())
    old.write(out / 'COMPLETE.json', dict(status='PASS_FROZEN_REPLAY', year=year, cost_bps=cost,
        policies=len(NAMES), fit_attempts=guard['attempts'], sources_unchanged=True,
        full_pool_complete=False, blind_test=False, formal_data_certification=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--year', type=int, choices=[2025, 2026], required=True)
    parser.add_argument('--cost', type=float, default=10); parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(); main(args.year, args.cost, args.resume)
