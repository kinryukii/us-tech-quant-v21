"""Read-only verification of the paired RL training; writes one concise receipt."""
from pathlib import Path
import hashlib
import json

import pandas as pd
import torch


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'a2_qualification_holdings_v1_20260927' / 'neural_artifacts'
OUT = ROOT / 'rl_capacity_artifacts'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run():
    binding = json.loads((ROOT / 'RL_PREFIT_BINDING.json').read_text(encoding='utf-8'))
    receipt = json.loads((OUT / 'TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    drift = [name for name, expected in binding['sha256'].items()
             if sha(ROOT.parent / name) != expected]
    if drift:
        raise RuntimeError(f'FROZEN_SOURCE_DRIFT: {drift}')
    if receipt['status'] != 'PAIRED_RL_CAPACITY_TRAINING_COMPLETE':
        raise RuntimeError('INCOMPLETE_RL_TRAINING')
    if receipt['fit_2026_rows'] != 0 or receipt['max_consumed_price_date'] != '2025-12-31':
        raise RuntimeError('RL_TRAINING_TIME_BOUNDARY')
    if receipt['actual_parameter_updates'] != 320 or len(receipt['artifacts']) != 4:
        raise RuntimeError('RL_TRAINING_BUDGET_DRIFT')
    artifacts = []
    for item in receipt['artifacts']:
        stage, seed = item['stage'], item['seed']
        if sha(item['path']) != item['sha256']:
            raise RuntimeError('CAPACITY_MODEL_HASH_DRIFT')
        candidate = torch.load(item['path'], weights_only=True, map_location='cpu')
        zero = torch.load(BASE / f'{stage}_rl_{seed}_zero.pt', weights_only=True, map_location='cpu')
        original = torch.load(BASE / f'{stage}_rl_{seed}.pt', weights_only=True, map_location='cpu')
        trained = any(not torch.equal(candidate[key], zero[key]) for key in candidate)
        treatment_differs = any(not torch.equal(candidate[key], original[key]) for key in candidate)
        if not trained or not treatment_differs or not all(torch.isfinite(t).all() for t in candidate.values()):
            raise RuntimeError('CAPACITY_MODEL_INVALID_OR_UNCHANGED')
        episodes = pd.read_parquet(OUT / f'{stage}_rl_{seed}_last_train_episode.parquet')
        expected_days = 500 if stage == 'validation' else 750
        if (len(episodes) != expected_days or episodes['cap_limited_orders'].sum() <= 0
                or not episodes['actual_names'].le(20).all()
                or episodes['filled_buy_notional'].sum() > episodes['allowed_buy_notional'].sum() + 1e-8
                or episodes['allowed_buy_notional'].sum() > episodes['requested_buy_notional'].sum() + 1e-8):
            raise RuntimeError('CAPACITY_EPISODE_INVALID')
        artifacts.append(dict(stage=stage, seed=seed, sha256=item['sha256'],
            zero_sha256=sha(BASE / f'{stage}_rl_{seed}_zero.pt'),
            original_sha256=sha(BASE / f'{stage}_rl_{seed}.pt'),
            trained_from_zero=trained, differs_from_original=treatment_differs,
            episode_days=len(episodes), cap_limited_orders=int(episodes.cap_limited_orders.sum()),
            requested_buy_notional=float(episodes.requested_buy_notional.sum()),
            allowed_buy_notional=float(episodes.allowed_buy_notional.sum()),
            filled_buy_notional=float(episodes.filled_buy_notional.sum()),
            max_actual_names=int(episodes.actual_names.max()),
            last_reward_signal=str(episodes.signal_date.iloc[-1])))
    logs = receipt['logs']
    training_logs = [row for row in logs if row['stage'] in ('validation', 'final')]
    result = dict(status='VERIFIED', bound_source_count=len(binding['sha256']),
        source_hash_drift=drift, fit_2026_rows=0,
        actual_parameter_updates=receipt['actual_parameter_updates'],
        training_epochs=len(training_logs),
        total_capacity_limited_orders=sum(row['adv_limited_buy_orders'] for row in training_logs),
        artifacts=artifacts,
        normalizer_fit_attempts=0,
        interpretation='ADV cap changes realized buys, next cash/units and NAV reward; it does not change target-based volatility penalty.')
    destination = ROOT / 'RL_TRAIN_VERIFY.json'
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'bound_source_count',
        'actual_parameter_updates', 'training_epochs', 'total_capacity_limited_orders')}, ensure_ascii=False))


if __name__ == '__main__':
    run()
