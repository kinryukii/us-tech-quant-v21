#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

VERSION = 'V22.064T_FAST3_CROSS_SESSION_TRANSITION_RETURN_ATLAS_R1'
SYMBOLS = ('QQQ', 'SOXX')
ALL_CANONICAL_SYMBOLS = ('QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS')
TRANSITIONS = (
    ('RTH', 'AFTER_HOURS', 'RTH_TO_AFTER_HOURS'),
    ('AFTER_HOURS', 'OVERNIGHT', 'AFTER_HOURS_TO_OVERNIGHT'),
    ('OVERNIGHT', 'PREMARKET', 'OVERNIGHT_TO_PREMARKET'),
    ('PREMARKET', 'RTH', 'PREMARKET_TO_RTH'),
)
PERIODS = (
    '2018-2022_DEVELOPMENT',
    '2023-2024_VALIDATION',
    '2025-2026_YTD_CONFIRMATION',
)
EXPECTED_V22_064_DECISION = (
    'SOLE_HISTORICAL_CANDIDATE_FORWARD_PENDING_'
    'MULTI_SESSION_STATE_MACHINE_BLOCKED'
)
EXPECTED_NEXT_STAGE = 'V22.064T_FAST3_CROSS_SESSION_TRANSITION_RETURN_ATLAS_R1'

JUMP_THRESHOLD = 0.20
FACTOR_TOLERANCE = 0.03
ALLOWED_SPLIT_FACTORS = (2.,3.,4.,5.,6.,8.,10.,15.,20.,25.,30.,40.,50.,100.)
BOOTSTRAP_REPETITIONS = 1000
MASTER_SEED = 2026072701
MIN_PERIOD_SAMPLE = 100
MIN_DIRECTION_SAMPLE = 30
MAX_TRANSITION_GAP_HOURS = 96

class AtlasError(RuntimeError):
    pass


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return '2018-2022_DEVELOPMENT'
    if 2023 <= year <= 2024:
        return '2023-2024_VALIDATION'
    if 2025 <= year <= 2026:
        return '2025-2026_YTD_CONFIRMATION'
    return 'OUTSIDE_STUDY'


def validate_v22_064(summary: Mapping[str, Any]) -> None:
    expected = {
        'final_status': 'PASS',
        'final_decision': EXPECTED_V22_064_DECISION,
        'next_stage': EXPECTED_NEXT_STAGE,
        'historical_candidate_architecture_count': 1,
        'historically_rejected_architecture_count': 5,
        'inconclusive_architecture_count': 1,
        'forward_replication_pending': True,
        'forward_replication_passed': False,
        'multi_session_state_machine_allowed': False,
        'premarket_forward_chain_modified': False,
        'market_data_read': False,
        'strategy_backtest_executed': False,
        'signal_regeneration_executed': False,
        'parameter_sweep_executed': False,
        'threshold_optimization_executed': False,
        'canonical_files_modified': False,
        'raw_files_modified': False,
        'new_market_data_cache_created': False,
        'broker_action_allowed': False,
        'paper_trading_allowed': False,
        'official_adoption_allowed': False,
    }
    failures = [
        f'{key}: expected {value!r}, got {summary.get(key)!r}'
        for key, value in expected.items()
        if summary.get(key) != value
    ]
    if failures:
        raise AtlasError('V22.064 lineage validation failed: ' + '; '.join(failures))


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        match = re.fullmatch(r'symbol=(.+)', part, re.I)
        if match:
            symbol = match.group(1).upper().replace('US.', '')
        match = re.fullmatch(r'year=(\d{4})', part, re.I)
        if match:
            year = match.group(1)
        match = re.fullmatch(r'month=(\d{1,2})', part, re.I)
        if match:
            month = f'{int(match.group(1)):02d}'
    if not all((symbol, year, month)):
        raise AtlasError(f'Cannot parse Canonical path: {path}')
    return symbol, year, month


def index_canonical(root: Path) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob('*.parquet')):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_CANONICAL_SYMBOLS:
            continue
        if key in result:
            raise AtlasError(f'Duplicate Canonical partition: {key}')
        result[key] = path
    counts = {
        symbol: sum(1 for current, _, _ in result if current == symbol)
        for symbol in ALL_CANONICAL_SYMBOLS
    }
    if len(result) != 582 or len(set(counts.values())) != 1:
        raise AtlasError(f'Expected balanced 582 partitions; got {len(result)}, {counts}')
    return result


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {str(c).strip().lower(): str(c) for c in frame.columns}
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise AtlasError(f'Missing column from aliases={tuple(aliases)}')


def load_symbol(symbol: str, canonical: Mapping[tuple[str,str,str], Path]) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    paths_read: list[str] = []
    for (current, _, _), path in sorted(canonical.items()):
        if current != symbol:
            continue
        raw = pd.read_parquet(path)
        paths_read.append(str(path))
        if raw.empty:
            continue
        timestamp = pd.to_datetime(raw[find_column(raw, ('timestamp_utc',))], errors='raise', utc=True)
        frame = pd.DataFrame({
            'timestamp_utc': timestamp,
            'open': pd.to_numeric(raw[find_column(raw, ('open',))], errors='coerce'),
            'high': pd.to_numeric(raw[find_column(raw, ('high',))], errors='coerce'),
            'low': pd.to_numeric(raw[find_column(raw, ('low',))], errors='coerce'),
            'close': pd.to_numeric(raw[find_column(raw, ('close',))], errors='coerce'),
            'volume': pd.to_numeric(raw[find_column(raw, ('volume',))], errors='coerce').fillna(0.0),
        }).dropna(subset=['timestamp_utc','open','high','low','close'])
        frames.append(frame)
    if not frames:
        return pd.DataFrame(), paths_read
    combined = (pd.concat(frames, ignore_index=True)
        .sort_values('timestamp_utc', kind='mergesort')
        .drop_duplicates('timestamp_utc', keep='last')
        .reset_index(drop=True))
    if ((combined['low'] > combined['high']).any()
        or (combined['close'] < combined['low']).any()
        or (combined['close'] > combined['high']).any()):
        raise AtlasError(f'Invalid OHLC for {symbol}')
    return combined, paths_read


def split_candidates() -> np.ndarray:
    values = set(ALLOWED_SPLIT_FACTORS)
    values.update(1.0 / x for x in ALLOWED_SPLIT_FACTORS)
    return np.array(sorted(values), dtype=float)


def snap_split_factor(raw_ratio: float) -> tuple[float, float] | None:
    if not np.isfinite(raw_ratio) or raw_ratio <= 0:
        return None
    factors = split_candidates()
    errors = np.abs(factors / raw_ratio - 1.0)
    idx = int(np.argmin(errors))
    factor, error = float(factors[idx]), float(errors[idx])
    return (factor, error) if error <= FACTOR_TOLERANCE else None


def normalize_scale(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), pd.DataFrame(), pd.DataFrame()
    result = frame.sort_values('timestamp_utc', kind='mergesort').reset_index(drop=True).copy()
    multiplier = 1.0
    multipliers: list[float] = []
    recognized: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    previous_close: float | None = None
    previous_timestamp: pd.Timestamp | None = None
    for _, row in result.iterrows():
        timestamp = pd.Timestamp(row['timestamp_utc'])
        current_open = float(row['open'])
        if previous_close is not None and previous_close > 0 and current_open > 0:
            change = current_open / previous_close - 1.0
            if abs(change) >= JUMP_THRESHOLD:
                ratio = previous_close / current_open
                snapped = snap_split_factor(ratio)
                record = {
                    'timestamp_utc': timestamp,
                    'previous_timestamp_utc': previous_timestamp,
                    'raw_change': change,
                    'raw_ratio': ratio,
                }
                if snapped is None:
                    unresolved.append(record)
                else:
                    factor, error = snapped
                    multiplier *= factor
                    recognized.append({**record, 'recognized_factor': factor, 'relative_error': error})
        multipliers.append(multiplier)
        previous_close = float(row['close'])
        previous_timestamp = timestamp
    result['scale_multiplier'] = multipliers
    for col in ('open','high','low','close'):
        result[f'normalized_{col}'] = result[col] * result['scale_multiplier']
    local = result['timestamp_utc'].dt.tz_convert('America/New_York')
    result['local_date'] = local.dt.strftime('%Y-%m-%d')
    result['minute_et'] = (local.dt.hour * 60 + local.dt.minute).astype(int)
    return result, pd.DataFrame(recognized), pd.DataFrame(unresolved)


def unresolved_in_window(unresolved: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if unresolved.empty:
        return False
    ts = pd.to_datetime(unresolved['timestamp_utc'], utc=True)
    return bool(((ts >= start) & (ts <= end)).any())


def exact_row(frame: pd.DataFrame, local_date: str, minute_et: int) -> pd.Series | None:
    rows = frame.loc[(frame['local_date'] == local_date) & (frame['minute_et'] == minute_et)]
    if rows.empty:
        return None
    return rows.sort_values('timestamp_utc', kind='mergesort').iloc[-1]


def build_standard_session(frame: pd.DataFrame, unresolved: pd.DataFrame, symbol: str,
                           session_name: str, start_minute: int, end_minute: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for local_date in sorted(frame['local_date'].unique()):
        start = exact_row(frame, local_date, start_minute)
        end = exact_row(frame, local_date, end_minute)
        if start is None or end is None:
            continue
        start_ts, end_ts = pd.Timestamp(start['timestamp_utc']), pd.Timestamp(end['timestamp_utc'])
        if end_ts <= start_ts or unresolved_in_window(unresolved, start_ts, end_ts):
            continue
        value = float(end['normalized_close']) / float(start['normalized_open']) - 1.0
        rows.append({
            'symbol': symbol,
            'session': session_name,
            'session_date': local_date,
            'calendar_year': int(local_date[:4]),
            'study_period': study_period(int(local_date[:4])),
            'start_timestamp_utc': start_ts,
            'end_timestamp_utc': end_ts,
            'start_price': float(start['normalized_open']),
            'end_price': float(end['normalized_close']),
            'session_return': value,
        })
    return pd.DataFrame(rows)


def build_overnight_session(frame: pd.DataFrame, unresolved: pd.DataFrame, symbol: str) -> pd.DataFrame:
    starts = frame.loc[frame['minute_et'] == 20 * 60, ['timestamp_utc','normalized_open','local_date']].copy()
    ends = frame.loc[frame['minute_et'] == 3 * 60 + 59, ['timestamp_utc','normalized_close','local_date']].copy()
    if starts.empty or ends.empty:
        return pd.DataFrame()
    starts = starts.rename(columns={'timestamp_utc':'start_timestamp_utc','normalized_open':'start_price','local_date':'start_local_date'}).sort_values('start_timestamp_utc')
    ends = ends.rename(columns={'timestamp_utc':'end_timestamp_utc','normalized_close':'end_price','local_date':'session_date'}).sort_values('end_timestamp_utc')
    paired = pd.merge_asof(
        starts,
        ends,
        left_on='start_timestamp_utc',
        right_on='end_timestamp_utc',
        direction='forward',
        allow_exact_matches=False,
    ).dropna(subset=['end_timestamp_utc']).copy()
    paired['gap_hours'] = (
        pd.to_datetime(paired['end_timestamp_utc'], utc=True)
        - pd.to_datetime(paired['start_timestamp_utc'], utc=True)
    ).dt.total_seconds() / 3600.0
    paired = paired.loc[(paired['gap_hours'] > 0) & (paired['gap_hours'] <= 12)].copy()
    rows: list[dict[str, Any]] = []
    for _, row in paired.iterrows():
        start_ts, end_ts = pd.Timestamp(row['start_timestamp_utc']), pd.Timestamp(row['end_timestamp_utc'])
        if unresolved_in_window(unresolved, start_ts, end_ts):
            continue
        session_date = str(row['session_date'])
        rows.append({
            'symbol': symbol,
            'session': 'OVERNIGHT',
            'session_date': session_date,
            'calendar_year': int(session_date[:4]),
            'study_period': study_period(int(session_date[:4])),
            'start_timestamp_utc': start_ts,
            'end_timestamp_utc': end_ts,
            'start_price': float(row['start_price']),
            'end_price': float(row['end_price']),
            'session_return': float(row['end_price']) / float(row['start_price']) - 1.0,
        })
    return pd.DataFrame(rows)


def build_sessions_for_symbol(frame: pd.DataFrame, unresolved: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frames = [
        build_standard_session(frame, unresolved, symbol, 'RTH', 9*60+30, 15*60+59),
        build_standard_session(frame, unresolved, symbol, 'AFTER_HOURS', 16*60, 19*60+59),
        build_overnight_session(frame, unresolved, symbol),
        build_standard_session(frame, unresolved, symbol, 'PREMARKET', 4*60, 9*60+29),
    ]
    frames = [x for x in frames if not x.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(['start_timestamp_utc','session'], kind='mergesort').reset_index(drop=True)


def pair_transition_for_symbol(sessions: pd.DataFrame, symbol: str, source_session: str,
                               target_session: str, transition_name: str) -> pd.DataFrame:
    source = sessions.loc[(sessions['symbol'] == symbol) & (sessions['session'] == source_session)].sort_values('end_timestamp_utc')
    target = sessions.loc[(sessions['symbol'] == symbol) & (sessions['session'] == target_session)].sort_values('start_timestamp_utc')
    if source.empty or target.empty:
        return pd.DataFrame()
    paired = pd.merge_asof(
        source,
        target,
        left_on='end_timestamp_utc',
        right_on='start_timestamp_utc',
        direction='forward',
        allow_exact_matches=False,
        suffixes=('_source','_target'),
    ).dropna(subset=['start_timestamp_utc_target']).copy()
    paired['transition_gap_hours'] = (
        pd.to_datetime(paired['start_timestamp_utc_target'], utc=True)
        - pd.to_datetime(paired['end_timestamp_utc_source'], utc=True)
    ).dt.total_seconds() / 3600.0
    paired = paired.loc[paired['transition_gap_hours'] <= MAX_TRANSITION_GAP_HOURS].copy()
    return pd.DataFrame({
        'transition': transition_name,
        'symbol': symbol,
        'source_session': source_session,
        'target_session': target_session,
        'source_session_date': paired['session_date_source'],
        'target_session_date': paired['session_date_target'],
        'target_calendar_year': paired['calendar_year_target'],
        'study_period': paired['study_period_target'],
        'source_start_timestamp_utc': paired['start_timestamp_utc_source'],
        'source_end_timestamp_utc': paired['end_timestamp_utc_source'],
        'target_start_timestamp_utc': paired['start_timestamp_utc_target'],
        'target_end_timestamp_utc': paired['end_timestamp_utc_target'],
        'transition_gap_hours': paired['transition_gap_hours'],
        'source_return': paired['session_return_source'],
        'target_return': paired['session_return_target'],
    })


def combine_symbol_pairs(pairs: pd.DataFrame) -> pd.DataFrame:
    qqq = pairs.loc[pairs['symbol'] == 'QQQ'].copy()
    soxx = pairs.loc[pairs['symbol'] == 'SOXX'].copy()
    keys = [
        'transition','source_session','target_session',
        'source_start_timestamp_utc','target_start_timestamp_utc','study_period'
    ]
    combined = qqq.merge(soxx, on=keys, how='inner', suffixes=('_qqq','_soxx'))
    q_source, s_source = np.sign(combined['source_return_qqq']), np.sign(combined['source_return_soxx'])
    q_target, s_target = np.sign(combined['target_return_qqq']), np.sign(combined['target_return_soxx'])
    combined['source_consensus'] = np.where((q_source>0)&(s_source>0),'UP',np.where((q_source<0)&(s_source<0),'DOWN','MIXED'))
    combined['target_consensus'] = np.where((q_target>0)&(s_target>0),'UP',np.where((q_target<0)&(s_target<0),'DOWN','MIXED'))
    combined['directional_persistence'] = (
        combined['source_consensus'].isin(['UP','DOWN'])
        & (combined['source_consensus'] == combined['target_consensus'])
    )
    return combined


def pearson_correlation(x: pd.Series, y: pd.Series) -> float:
    frame = pd.DataFrame({'x':pd.to_numeric(x, errors='coerce'),'y':pd.to_numeric(y, errors='coerce')}).dropna()
    if len(frame) < 3 or frame['x'].std(ddof=1) == 0 or frame['y'].std(ddof=1) == 0:
        return math.nan
    return float(frame['x'].corr(frame['y']))


def bootstrap_difference(up: np.ndarray, down: np.ndarray, seed: int) -> tuple[float,float]:
    if len(up) < 2 or len(down) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    values = np.empty(BOOTSTRAP_REPETITIONS, dtype=float)
    for i in range(BOOTSTRAP_REPETITIONS):
        values[i] = float(rng.choice(up, len(up), replace=True).mean() - rng.choice(down, len(down), replace=True).mean())
    low, high = np.quantile(values, [0.025, 0.975])
    return float(low), float(high)


def summarize_period_atlas(combined: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for transition_index, (_, _, transition) in enumerate(TRANSITIONS):
        for period_index, period in enumerate(PERIODS):
            group = combined.loc[(combined['transition'] == transition) & (combined['study_period'] == period)].copy()
            if group.empty:
                continue
            up = group.loc[group['source_consensus'] == 'UP']
            down = group.loc[group['source_consensus'] == 'DOWN']
            directional = group.loc[group['source_consensus'].isin(['UP','DOWN'])]
            seed = MASTER_SEED + transition_index * 100 + period_index * 10
            q_low, q_high = bootstrap_difference(up['target_return_qqq'].to_numpy(float), down['target_return_qqq'].to_numpy(float), seed+1)
            s_low, s_high = bootstrap_difference(up['target_return_soxx'].to_numpy(float), down['target_return_soxx'].to_numpy(float), seed+2)
            q_up = float(up['target_return_qqq'].mean()) if len(up) else math.nan
            q_down = float(down['target_return_qqq'].mean()) if len(down) else math.nan
            s_up = float(up['target_return_soxx'].mean()) if len(up) else math.nan
            s_down = float(down['target_return_soxx'].mean()) if len(down) else math.nan
            rows.append({
                'transition': transition,
                'study_period': period,
                'sample_count': int(len(group)),
                'source_up_count': int(len(up)),
                'source_down_count': int(len(down)),
                'source_mixed_count': int((group['source_consensus']=='MIXED').sum()),
                'qqq_source_target_correlation': pearson_correlation(group['source_return_qqq'], group['target_return_qqq']),
                'soxx_source_target_correlation': pearson_correlation(group['source_return_soxx'], group['target_return_soxx']),
                'qqq_target_mean_after_source_up': q_up,
                'qqq_target_mean_after_source_down': q_down,
                'qqq_up_minus_down_target_mean': q_up-q_down if np.isfinite(q_up) and np.isfinite(q_down) else math.nan,
                'qqq_difference_ci_low': q_low,
                'qqq_difference_ci_high': q_high,
                'soxx_target_mean_after_source_up': s_up,
                'soxx_target_mean_after_source_down': s_down,
                'soxx_up_minus_down_target_mean': s_up-s_down if np.isfinite(s_up) and np.isfinite(s_down) else math.nan,
                'soxx_difference_ci_low': s_low,
                'soxx_difference_ci_high': s_high,
                'directional_source_count': int(len(directional)),
                'directional_persistence_rate': float(directional['directional_persistence'].mean()) if len(directional) else math.nan,
            })
    return pd.DataFrame(rows)


def period_row(atlas: pd.DataFrame, transition: str, period: str) -> pd.Series | None:
    rows = atlas.loc[(atlas['transition']==transition) & (atlas['study_period']==period)]
    return None if rows.empty else rows.iloc[0]


def ci_excludes_zero(low: float, high: float) -> bool:
    return bool(np.isfinite(low) and np.isfinite(high) and (low > 0 or high < 0))


def same_nonzero_sign(a: float, b: float) -> bool:
    return bool(np.isfinite(a) and np.isfinite(b) and a != 0 and b != 0 and np.sign(a) == np.sign(b))


def build_qualification(atlas: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, _, transition in TRANSITIONS:
        val = period_row(atlas, transition, '2023-2024_VALIDATION')
        conf = period_row(atlas, transition, '2025-2026_YTD_CONFIRMATION')
        if val is None or conf is None:
            rows.append({'transition':transition,'sample_pass':False,'direction_sample_pass':False,'qqq_difference_sign_stable':False,'soxx_difference_sign_stable':False,'qqq_ci_excludes_zero_both_periods':False,'soxx_ci_excludes_zero_both_periods':False,'correlation_sign_stable_both_symbols':False,'diagnostic_transition_for_frozen_followup':False})
            continue
        sample_pass = int(val['sample_count']) >= MIN_PERIOD_SAMPLE and int(conf['sample_count']) >= MIN_PERIOD_SAMPLE
        direction_pass = all([
            int(val['source_up_count']) >= MIN_DIRECTION_SAMPLE,
            int(val['source_down_count']) >= MIN_DIRECTION_SAMPLE,
            int(conf['source_up_count']) >= MIN_DIRECTION_SAMPLE,
            int(conf['source_down_count']) >= MIN_DIRECTION_SAMPLE,
        ])
        q_sign = same_nonzero_sign(float(val['qqq_up_minus_down_target_mean']), float(conf['qqq_up_minus_down_target_mean']))
        s_sign = same_nonzero_sign(float(val['soxx_up_minus_down_target_mean']), float(conf['soxx_up_minus_down_target_mean']))
        q_ci = ci_excludes_zero(float(val['qqq_difference_ci_low']), float(val['qqq_difference_ci_high'])) and ci_excludes_zero(float(conf['qqq_difference_ci_low']), float(conf['qqq_difference_ci_high']))
        s_ci = ci_excludes_zero(float(val['soxx_difference_ci_low']), float(val['soxx_difference_ci_high'])) and ci_excludes_zero(float(conf['soxx_difference_ci_low']), float(conf['soxx_difference_ci_high']))
        corr = same_nonzero_sign(float(val['qqq_source_target_correlation']), float(conf['qqq_source_target_correlation'])) and same_nonzero_sign(float(val['soxx_source_target_correlation']), float(conf['soxx_source_target_correlation']))
        diagnostic = bool(sample_pass and direction_pass and q_sign and s_sign and q_ci and s_ci and corr)
        rows.append({
            'transition': transition,
            'validation_sample_count': int(val['sample_count']),
            'confirmation_sample_count': int(conf['sample_count']),
            'validation_source_up_count': int(val['source_up_count']),
            'validation_source_down_count': int(val['source_down_count']),
            'confirmation_source_up_count': int(conf['source_up_count']),
            'confirmation_source_down_count': int(conf['source_down_count']),
            'sample_pass': sample_pass,
            'direction_sample_pass': direction_pass,
            'qqq_difference_sign_stable': q_sign,
            'soxx_difference_sign_stable': s_sign,
            'qqq_ci_excludes_zero_both_periods': q_ci,
            'soxx_ci_excludes_zero_both_periods': s_ci,
            'correlation_sign_stable_both_symbols': corr,
            'diagnostic_transition_for_frozen_followup': diagnostic,
        })
    return pd.DataFrame(rows)


def choose_decision(qualification: pd.DataFrame) -> tuple[str,list[str],str]:
    survivors = qualification.loc[qualification['diagnostic_transition_for_frozen_followup'],'transition'].astype(str).tolist()
    if survivors:
        return ('CROSS_SESSION_TRANSITION_STRUCTURE_DETECTED_REQUIRES_SEPARATE_FROZEN_BASELINE', survivors, 'V22.064T1_FAST3_SELECTED_TRANSITION_FROZEN_BASELINE_R1')
    return ('NO_CROSS_SESSION_TRANSITION_STRUCTURE_DETECTED', [], 'WAIT_FOR_V22.062PR_FORWARD_SAMPLE_AND_STOP_FAST3_EXECUTION_EXPANSION')


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(f'Cannot serialize {type(value)!r}')


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)+'\n', encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def print_table(title: str, frame: pd.DataFrame) -> None:
    print('\n========== ' + title + ' ==========')
    if frame.empty:
        print('NO_ROWS')
        return
    print(frame.to_string(index=False))


def run_atlas(v22_064_summary_path: Path, canonical_root: Path, result_dir: Path) -> dict[str, Any]:
    if not v22_064_summary_path.exists():
        raise AtlasError(f'Missing V22.064 summary: {v22_064_summary_path}')
    if not canonical_root.exists():
        raise AtlasError(f'Missing Canonical root: {canonical_root}')
    summary_064 = json.loads(v22_064_summary_path.read_text(encoding='utf-8-sig'))
    validate_v22_064(summary_064)
    canonical = index_canonical(canonical_root)

    session_frames: list[pd.DataFrame] = []
    recognized_frames: list[pd.DataFrame] = []
    unresolved_frames: list[pd.DataFrame] = []
    paths_read: set[str] = set()

    for symbol in SYMBOLS:
        raw, symbol_paths = load_symbol(symbol, canonical)
        paths_read.update(symbol_paths)
        normalized, recognized, unresolved = normalize_scale(raw)
        session_frames.append(build_sessions_for_symbol(normalized, unresolved, symbol))
        if not recognized.empty:
            recognized_frames.append(recognized.assign(symbol=symbol))
        if not unresolved.empty:
            unresolved_frames.append(unresolved.assign(symbol=symbol))

    sessions_all = pd.concat(session_frames, ignore_index=True)
    pair_frames: list[pd.DataFrame] = []
    for source_session, target_session, transition in TRANSITIONS:
        for symbol in SYMBOLS:
            current = pair_transition_for_symbol(sessions_all, symbol, source_session, target_session, transition)
            if not current.empty:
                pair_frames.append(current)
    if not pair_frames:
        raise AtlasError('No transition pairs generated')
    pairs = pd.concat(pair_frames, ignore_index=True)
    combined = combine_symbol_pairs(pairs)
    if combined.empty:
        raise AtlasError('No synchronized transition pairs generated')

    atlas = summarize_period_atlas(combined)
    qualification = build_qualification(atlas)
    final_decision, survivors, next_stage = choose_decision(qualification)

    recognized_all = pd.concat(recognized_frames, ignore_index=True) if recognized_frames else pd.DataFrame()
    unresolved_all = pd.concat(unresolved_frames, ignore_index=True) if unresolved_frames else pd.DataFrame()

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        'session_returns': result_dir/'v22_064t_session_returns.csv',
        'transition_pairs': result_dir/'v22_064t_transition_pairs.csv',
        'period_atlas': result_dir/'v22_064t_period_atlas.csv',
        'qualification': result_dir/'v22_064t_diagnostic_qualification.csv',
        'recognized_events': result_dir/'v22_064t_recognized_scale_events.csv',
        'unresolved_events': result_dir/'v22_064t_unresolved_scale_events.csv',
        'summary': result_dir/'v22_064t_summary.json',
    }
    sessions_all.to_csv(outputs['session_returns'], index=False, encoding='utf-8-sig')
    combined.to_csv(outputs['transition_pairs'], index=False, encoding='utf-8-sig')
    atlas.to_csv(outputs['period_atlas'], index=False, encoding='utf-8-sig')
    qualification.to_csv(outputs['qualification'], index=False, encoding='utf-8-sig')
    recognized_all.to_csv(outputs['recognized_events'], index=False, encoding='utf-8-sig')
    unresolved_all.to_csv(outputs['unresolved_events'], index=False, encoding='utf-8-sig')

    summary = {
        'version': VERSION,
        'final_status': 'PASS',
        'final_decision': final_decision,
        'v22_064_validated': True,
        'premarket_forward_chain_modified': False,
        'transition_count': len(TRANSITIONS),
        'symbol_count': len(SYMBOLS),
        'session_return_row_count': int(len(sessions_all)),
        'synchronized_transition_pair_count': int(len(combined)),
        'diagnostic_surviving_transitions': survivors,
        'bootstrap_repetitions': BOOTSTRAP_REPETITIONS,
        'master_seed': MASTER_SEED,
        'strategy_backtest_executed': False,
        'execution_signal_generated': False,
        'execution_policy_created': False,
        'multi_session_state_machine_allowed': False,
        'parameter_sweep_executed': False,
        'threshold_optimization_executed': False,
        'canonical_partition_count_indexed': int(len(canonical)),
        'canonical_partition_count_read': int(len(paths_read)),
        'canonical_files_modified': False,
        'raw_files_modified': False,
        'new_market_data_cache_created': False,
        'broker_action_allowed': False,
        'paper_trading_allowed': False,
        'official_adoption_allowed': False,
        'next_stage': next_stage,
        'outputs': {k:str(v) for k,v in outputs.items()},
    }
    atomic_json(outputs['summary'], summary)

    print('==============================================')
    print(' V22.064T cross-session transition atlas')
    print('==============================================')
    print_table('Validation / Confirmation atlas', atlas.loc[atlas['study_period'].isin(['2023-2024_VALIDATION','2025-2026_YTD_CONFIRMATION'])])
    print_table('Diagnostic qualification', qualification)
    print('\nFINAL_STATUS=PASS')
    print(f'FINAL_DECISION={final_decision}')
    print('V22_064_VALIDATED=True')
    print('PREMARKET_FORWARD_CHAIN_MODIFIED=False')
    print(f'SESSION_RETURN_ROW_COUNT={len(sessions_all)}')
    print(f'SYNCHRONIZED_TRANSITION_PAIR_COUNT={len(combined)}')
    print(f'DIAGNOSTIC_SURVIVING_TRANSITIONS={survivors}')
    print(f'BOOTSTRAP_REPETITIONS={BOOTSTRAP_REPETITIONS}')
    print(f'MASTER_SEED={MASTER_SEED}')
    print('STRATEGY_BACKTEST_EXECUTED=False')
    print('EXECUTION_SIGNAL_GENERATED=False')
    print('EXECUTION_POLICY_CREATED=False')
    print('MULTI_SESSION_STATE_MACHINE_ALLOWED=False')
    print('PARAMETER_SWEEP_EXECUTED=False')
    print('THRESHOLD_OPTIMIZATION_EXECUTED=False')
    print(f'CANONICAL_PARTITION_COUNT_READ={len(paths_read)}')
    print('CANONICAL_FILES_MODIFIED=False')
    print('RAW_FILES_MODIFIED=False')
    print('NEW_MARKET_DATA_CACHE_CREATED=False')
    print('BROKER_ACTION_ALLOWED=False')
    print('PAPER_TRADING_ALLOWED=False')
    print('OFFICIAL_ADOPTION_ALLOWED=False')
    print(f'NEXT_STAGE={next_stage}')
    print(f'SUMMARY_PATH={outputs["summary"]}')
    print(f'RESULT_DIRECTORY={result_dir}')
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--v22-064-summary', default=(r'D:\us-tech-quant-results\v22'
        r'\V22.064_FAST3_FOUR_SESSION_EVIDENCE_AND_COMPARABILITY_REPORT_R1'
        r'\v22_064_summary.json'))
    parser.add_argument('--canonical-root', default=(r'D:\us-tech-quant-data\fast3'
        r'\moomoo_24h_1m\canonical'))
    parser.add_argument('--result-dir', default=(r'D:\us-tech-quant-results\v22'
        r'\V22.064T_FAST3_CROSS_SESSION_TRANSITION_RETURN_ATLAS_R1'))
    parser.add_argument('--execute', action='store_true')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print('FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED')
        return 2
    try:
        run_atlas(Path(args.v22_064_summary), Path(args.canonical_root), Path(args.result_dir))
        return 0
    except Exception as exc:
        print('FINAL_STATUS=FAIL')
        print(f'ERROR_TYPE={type(exc).__name__}')
        print(f'ERROR={exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
