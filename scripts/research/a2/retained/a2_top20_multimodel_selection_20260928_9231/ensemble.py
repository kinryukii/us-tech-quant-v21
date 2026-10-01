"""Heterogeneous six-model fusion and genuinely out-of-time nonnegative stacking."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import values as vm
from neural import NeuralAdapter, project
from engine_v2 import HoldingAwareDecision, OperationalExit

OUT = ROOT / 'ensemble_artifacts'
CONTRACT = ROOT / 'ENSEMBLE_CONTRACT.md'
BASE_NAMES = ('ridge', 'elastic_net', 'logistic', 'hgb', 'q50', 'mlp')
RANK_COLUMNS = [f'rank_{name}' for name in BASE_NAMES]
OOF_STAGES = {2024: ('development', '2024-01-01'), 2025: ('validation', '2025-01-01')}
META_PARAMS = dict(alpha=100., positive=True, fit_intercept=False,
                   solver='lbfgs', max_iter=2000, tol=1e-8)
MAX_BASE_ROWS = 6000


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                    default=str, allow_nan=False), encoding='utf-8')


def signed_rank(gain):
    """Cross-sectional relative preference; preserve true sign and exact zeros."""
    gain = np.asarray(gain, dtype=float)
    if gain.ndim != 2 or not np.isfinite(gain).all():
        raise ValueError('Expected finite security/action matrix')
    if not len(gain):
        return gain.copy()
    return np.sign(gain) * rankdata(np.abs(gain), axis=0, method='average') / (len(gain) + 1)


def fuse(rank_inputs, downside, name, meta=None):
    rank_inputs = np.asarray(rank_inputs, dtype=float)
    if rank_inputs.ndim != 3 or rank_inputs.shape[-1] != len(BASE_NAMES):
        raise ValueError('Expected security/action/six-model inputs')
    if name == 'ensemble_equal':
        result = rank_inputs.mean(axis=-1)
    elif name == 'ensemble_disagreement':
        result = rank_inputs.mean(axis=-1) - .25 * rank_inputs.std(axis=-1) - .25 * downside
    elif name == 'ensemble_stacking':
        if meta is None:
            raise ValueError('Stacking requires frozen OOF-trained meta model')
        result = meta.predict(rank_inputs.reshape(-1, len(BASE_NAMES))).reshape(rank_inputs.shape[:2])
    else:
        raise ValueError(f'Unknown ensemble: {name}')
    if not np.isfinite(result).all():
        raise ValueError('Nonfinite ensemble score')
    # Every input action-zero advantage is identically zero and intercept is off.
    result[:, 0] = 0.
    return result


def stage_artifacts(stage):
    if stage == 'development':
        directories = [ROOT / 'development_value_artifacts', ROOT / 'development_neural_artifacts']
        files = [p for d in directories for p in d.iterdir()
                 if p.suffix in ('.joblib', '.pt', '.npz')]
    else:
        files = list((ROOT / 'value_artifacts').glob(f'{stage}_*.joblib'))
        files += [ROOT / 'neural_artifacts' / f'{stage}_normalization.npz',
                  ROOT / 'neural_artifacts' / f'{stage}_direct_20260928.pt']
    if not files or any(not path.exists() for path in files):
        raise ValueError(f'Missing base artifacts: {stage}')
    return {str(path): sha(path) for path in sorted(set(files))}


class BasePredictions:
    def __init__(self, stage):
        if stage == 'development':
            from development_values import load_policy
            from development_neural import DevelopmentNeuralAdapter
            self.neural = DevelopmentNeuralAdapter()
        elif stage in ('validation', 'final'):
            load_policy = vm.load_policy
            self.neural = NeuralAdapter('direct', stage=stage)
        else:
            raise ValueError('Invalid base stage')
        self.models = {name: load_policy(name, stage=stage).models[name]
                       for name in (*BASE_NAMES[:-1], 'q10')}
        self.stage = stage
        self.artifact_hashes = stage_artifacts(stage)

    def predict(self, day, current, cash, age, *, max_names=20, max_exposure=.95,
                restricted=()):
        """Only current signal features/account state are accepted here."""
        n = len(day)
        x = day[vm.FEATURES].to_numpy(float)
        current = np.broadcast_to(np.asarray(current, float), (n,)).copy()
        age = np.broadcast_to(np.asarray(age, float), (n,))
        mapped = vm.mapped_features(np.repeat(x, 5, axis=0), np.repeat(current, 5),
            np.full(n * 5, cash), np.repeat(age, 5), np.tile(vm.ACTIONS, n))
        raw = {name: vm.predict_values(model, name, mapped).reshape(n, 5)
               for name, model in self.models.items()}
        normalized = np.clip((x - self.neural.mean) / self.neural.scale, -8, 8)
        obs = torch.tensor(np.column_stack([normalized, current, np.full(n, cash), current > 0]),
                           dtype=torch.float32)
        eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(restricted).to_numpy()
        upper = torch.tensor(np.where(eligible, .1, np.minimum(current, .1)), dtype=torch.float32)
        with torch.no_grad():
            projected = torch.stack([project(model(obs), upper=upper, max_names=max_names,
                                            max_exposure=max_exposure)
                                     for model in self.neural.models]).mean(dim=0).numpy()
        raw['mlp'] = -((vm.ACTIONS[None, :] - projected[:, None]) / .1)**2
        ranks = np.stack([signed_rank(raw[name] - raw[name][:, :1]) for name in BASE_NAMES], axis=-1)
        qgain = raw['q10'] - raw['q10'][:, :1]
        downside = signed_rank(np.maximum(-qgain, 0.))
        return ranks, downside, raw, projected


def reward_advantages(day, current):
    returns = np.clip(day.y_next_open.to_numpy(float), -.2, .2)
    vol = day.realized_vol_20d.to_numpy(float)
    adv = day.avg_dollar_volume_20d.to_numpy(float)
    rewards = []
    for action in vm.ACTIONS:
        actual = vm.realized_weight(current, float(action), adv)
        rewards.append(actual * returns - vm.COST * np.abs(actual - current)
                       - .5 * vm.RISK_AVERSION * vol**2 * actual**2)
    result = np.column_stack(rewards)
    return result - result[:, :1]


def verify_oof_clock(frame, cutoff):
    signal = pd.to_datetime(frame.signal_date)
    labels = pd.to_datetime(frame.label_end_date)
    base_cutoff = pd.to_datetime(frame.base_fit_cutoff)
    cutoff = pd.Timestamp(cutoff)
    if not (signal.ge(base_cutoff).all() and signal.lt(cutoff).all()
            and labels.lt(cutoff).all() and labels.gt(signal).all()):
        raise ValueError('OOF clock leakage')
    if not base_cutoff.lt(cutoff).all():
        raise ValueError('OOF base fits overlap meta test boundary')


def build_oof(year, frame):
    stage, cutoff = OOF_STAGES[year]
    destination = OUT / f'oof_{year}.parquet'
    receipt_path = OUT / f'OOF_{year}_RECEIPT.json'
    if destination.exists() or receipt_path.exists():
        raise FileExistsError(f'Existing OOF preserved: {year}')
    full_year = frame.loc[frame.signal_date.dt.year.eq(year)].copy()
    mature = vm.mature_rows(full_year, f'{year + 1}-01-01')
    sample, dates = vm.select_dates(mature, maximum_base_rows=MAX_BASE_ROWS)
    selected = {date: set(group.ticker) for date, group in sample.groupby('signal_date')}
    model = BasePredictions(stage)
    contract = {'year': year, 'base_stage': stage, 'base_fit_cutoff_exclusive': cutoff,
        'meta_label_cutoff_exclusive': f'{year + 1}-01-01', 'base_rows': len(sample),
        'sampled_days': len(dates), 'base_artifact_sha256': model.artifact_hashes,
        'input_sha256': sha(vm.DATA), 'ensemble_contract_sha256': sha(CONTRACT),
        'source_rows': len(full_year), 'reads_2026_rows': 0,
        'sample_rule': 'date/ticker SHA256 only; all mature dates represented',
        'cross_section': 'full available day before label-side sampling',
        'created_utc': pd.Timestamp.now(tz='UTC').isoformat()}
    write(OUT / f'OOF_{year}_PRE_BUILD.json', contract)
    pieces = []
    started = time.monotonic()
    for day_index, (date, day) in enumerate(full_year.groupby('signal_date', sort=True)):
        if date not in selected:
            continue
        day = day.sort_values('ticker').reset_index(drop=True)
        ids = np.flatnonzero(day.ticker.isin(selected[date]).to_numpy())
        chosen = day.iloc[ids]
        for state_id, (current, cash, age) in enumerate(vm.STATE_GRID):
            ranks, downside, _, _ = model.predict(day, current, cash, age)
            target = reward_advantages(chosen, current)
            record = pd.DataFrame(ranks[ids].reshape(-1, len(BASE_NAMES)), columns=RANK_COLUMNS)
            record['q10_downside_rank'] = downside[ids].reshape(-1)
            record['target_advantage'] = target.reshape(-1)
            for column in ['signal_date', 'ticker', 'label_end_date']:
                record[column] = np.repeat(chosen[column].to_numpy(), 5)
            record['action'] = np.tile(vm.ACTIONS, len(chosen))
            record['state_id'] = state_id
            record['current_weight'] = current
            record['cash_weight'] = cash
            record['age'] = age
            record['base_stage'] = stage
            record['base_fit_cutoff'] = cutoff
            pieces.append(record)
        if day_index % 50 == 0:
            print(json.dumps({'oof_year': year, 'processed_day': day_index,
                              'date': str(date.date())}), flush=True)
    result = pd.concat(pieces, ignore_index=True)
    verify_oof_clock(result, f'{year + 1}-01-01')
    if len(result) > MAX_BASE_ROWS * 15 or not np.isfinite(result[RANK_COLUMNS + ['target_advantage']]).all().all():
        raise ValueError('Invalid OOF training rows')
    if stage_artifacts(stage) != model.artifact_hashes:
        raise ValueError('Base artifacts changed during OOF')
    result.to_parquet(destination, index=False)
    receipt = {**contract, 'status': 'PASS', 'oof_rows': len(result),
        'signal_first': str(result.signal_date.min().date()),
        'signal_last': str(result.signal_date.max().date()),
        'label_end_max': str(result.label_end_date.max().date()),
        'oof_sha256': sha(destination), 'seconds': time.monotonic() - started,
        'fit_calls': 0, 'base_artifacts_unchanged': True}
    write(receipt_path, receipt)
    return result


def fit_meta(stage, oof):
    cutoff = vm.STAGES[stage]
    verify_oof_clock(oof, cutoff)
    path = OUT / f'{stage}_stacking.joblib'
    receipt_path = OUT / f'{stage}_TRAIN_RECEIPT.json'
    if path.exists() or receipt_path.exists():
        raise FileExistsError(f'Existing stacking preserved: {stage}')
    expected_years = {2024} if stage == 'validation' else {2024, 2025}
    if set(oof.signal_date.dt.year) != expected_years:
        raise ValueError('Invalid meta OOF years')
    contract = {'stage': stage, 'cutoff_exclusive': cutoff, 'parameters': META_PARAMS,
        'input_columns': RANK_COLUMNS, 'rows': len(oof), 'oof_years': sorted(expected_years),
        'signal_last': str(oof.signal_date.max().date()),
        'label_end_max': str(oof.label_end_date.max().date()),
        'oof_input_sha256': {str(OUT / f'oof_{year}.parquet'): sha(OUT / f'oof_{year}.parquet')
                             for year in sorted(expected_years)},
        'ensemble_contract_sha256': sha(CONTRACT), 'code_sha256': sha(__file__),
        'test2026_rows_read': 0, 'hyperparameter_search_trials': 0,
        'created_utc': pd.Timestamp.now(tz='UTC').isoformat()}
    write(OUT / f'{stage}_PRE_FIT.json', contract)
    started = time.monotonic()
    with threadpool_limits(limits=2):
        model = Ridge(**META_PARAMS).fit(oof[RANK_COLUMNS].to_numpy(float),
                                        oof.target_advantage.to_numpy(float))
    if not np.isfinite(model.coef_).all() or (model.coef_ < -1e-12).any():
        raise ValueError('Invalid stacking coefficients')
    joblib.dump(model, path, compress=3)
    receipt = {**contract, 'status': 'PASS', 'fit_calls': 1,
        'fit_seconds': time.monotonic() - started, 'coefficients': dict(zip(BASE_NAMES, model.coef_.tolist())),
        'coefficient_sum': float(model.coef_.sum()), 'intercept': float(model.intercept_),
        'artifact_path': str(path), 'artifact_sha256': sha(path),
        'base_prediction_rule': 'each meta sample strictly after corresponding base fit cutoff',
        'no_in_sample_base_predictions': True}
    write(receipt_path, receipt)
    print(json.dumps({'meta_stage': stage, 'status': 'PASS', 'rows': len(oof),
                      'coefficients': receipt['coefficients']}), flush=True)
    return receipt


class EnsemblePolicy:
    def __init__(self, name, stage='final', operational_events=None):
        if name not in ('ensemble_equal', 'ensemble_disagreement', 'ensemble_stacking'):
            raise ValueError('Unknown ensemble policy')
        if stage not in vm.STAGES:
            raise ValueError('Invalid ensemble inference stage')
        self.name, self.stage = name, stage
        self.base = BasePredictions(stage)
        self.age = {}
        self.operational_events = operational_events
        self.meta = None
        if name == 'ensemble_stacking':
            receipt = json.loads((OUT / f'{stage}_TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
            path = OUT / f'{stage}_stacking.joblib'
            if (receipt['status'] != 'PASS' or receipt['stage'] != stage
                    or receipt['artifact_sha256'] != sha(path)
                    or receipt['label_end_max'] >= vm.STAGES[stage]):
                raise ValueError('Stacking receipt/hash/clock mismatch')
            self.meta = joblib.load(path)

    def __call__(self, day, ctx):
        self.age = {ticker: self.age.get(ticker, 0) + 1
                    for ticker, weight in ctx.current_weights.items() if weight > 0}
        day = day.loc[day.new_buy_eligible.astype(bool)
                      | day.ticker.map(ctx.current_weights).fillna(0).gt(0)]
        day = day.sort_values('ticker', kind='stable').reset_index(drop=True)
        decisions, outputs = {}, {}
        if len(day):
            current = np.array([ctx.current_weights.get(ticker, 0.) for ticker in day.ticker])
            age = np.array([self.age.get(ticker, 0.) for ticker in day.ticker])
            ranks, downside, raw, projected = self.base.predict(day, current, ctx.cash_weight, age,
                max_names=ctx.available_slots, max_exposure=ctx.available_weight,
                restricted=ctx.buy_restricted_tickers)
            scores = fuse(ranks, downside, self.name, self.meta)
            eligible = day.new_buy_eligible.to_numpy(bool) & ~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
            allowed = eligible[:, None] | (vm.ACTIONS[None, :] <= current[:, None] + 1e-10)
            _, chosen = vm.allocate_joint_scores(scores, day.ticker.tolist(),
                max_names=ctx.available_slots,
                max_units=min(38, int(np.floor((ctx.available_weight + 1e-12) / .025))), allowed=allowed)
            decisions = {str(t): float(vm.ACTIONS[a]) for t, a in zip(day.ticker, chosen)}
            outputs = {str(t): {'base_action_values': {name: raw[name][i].tolist() for name in raw},
                'base_rank_advantages': {name: ranks[i, :, j].tolist() for j, name in enumerate(BASE_NAMES)},
                'q10_downside_rank': downside[i].tolist(), 'fused_action_values': scores[i].tolist(),
                'mlp_projected_weight': float(projected[i]), 'chosen_weight': decisions[str(t)]}
                for i, t in enumerate(day.ticker)}
        events = {}
        if self.operational_events is not None:
            for row in self.operational_events.itertuples():
                if (row.ticker in ctx.current_units and row.known_at <= ctx.signal_asof
                        and row.effective_date <= ctx.signal_date):
                    events[str(row.ticker)] = OperationalExit(reason=str(row.reason), known_at=row.known_at,
                                                               source_id=str(row.source_id))
        return HoldingAwareDecision(model_decisions=decisions, operational_exits=events,
                                    raw_model_outputs=outputs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--oof-year', type=int, choices=list(OOF_STAGES))
    parser.add_argument('--fit-meta', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if not CONTRACT.exists():
        raise ValueError('Missing ensemble contract')
    if args.oof_year is not None or not args.fit_meta:
        columns = ['signal_date', 'ticker', 'label_end_date', 'label_available',
                   'new_buy_eligible', 'y_next_open', *vm.FEATURES]
        frame = pd.read_parquet(vm.DATA, columns=columns)
        if not frame.signal_date.lt('2026-01-01').all():
            raise ValueError('2026 source rows forbidden')
        for year in ([args.oof_year] if args.oof_year is not None else list(OOF_STAGES)):
            build_oof(year, frame)
    if args.fit_meta or args.oof_year is None:
        oof24 = pd.read_parquet(OUT / 'oof_2024.parquet')
        oof25 = pd.read_parquet(OUT / 'oof_2025.parquet')
        fit_meta('validation', oof24)
        fit_meta('final', pd.concat([oof24, oof25], ignore_index=True))


if __name__ == '__main__':
    main()
