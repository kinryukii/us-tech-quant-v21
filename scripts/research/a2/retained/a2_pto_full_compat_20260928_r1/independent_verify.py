"""Read-only proof of saved A2 accounts, independent of the account/policy code.

No account-engine, optimizer, model, or learning module is imported. Prices and
signal inputs are read from their saved source panels. Cash and price-index
units are rebuilt from initial conditions and fills, then marked independently.
The audit preserves failures, approximate solutions, cash solutions, and drift.
Run again after further immutable batches complete; partial batches are pending.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
FEATURES = ['ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
 'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120','ma10_vs_ma20','ma20_vs_ma50','ma50_vs_ma120',
 'realized_vol_5d','realized_vol_10d','realized_vol_20d','realized_vol_60d','downside_vol_20d','upside_vol_20d',
 'distance_from_high_20d','distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
 'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d','volume_ratio_5d_20d',
 'volume_ratio_20d_60d','avg_dollar_volume_20d']
POINT = ['ridge','elastic','huber','ebm','rf','et','hgb','xgb','lgb','cat','mlp','resnet','ft_transformer']
TABLE_DATES = {'daily':'date', 'trades':'execution_date', 'positions':'date',
 'target_decisions':'signal_date', 'execution_results':'execution_date',
 'raw_model_outputs':'signal_date', 'signal_contexts':'signal_date',
 'diagnostics':'signal_date', 'operational_actions':'signal_date'}
TOL = 1e-10
MONEY_ATOL = 3e-6
UNIT_ATOL = 3e-10
WEIGHT_ATOL = 2e-8
MAX_SAMPLES = 250
CACHE_VERSION = 'ALL_LEDGER_MASK_EXPERT_SOURCE_SHA256_V1'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if pd.isna(value):
        return None
    return value


class Evidence:
    def __init__(self, year, batch):
        self.year, self.batch = int(year), str(batch)
        self.counts, self.samples, self.max_error = Counter(), [], {}
        self.drift_counts, self.drift_samples = Counter(), []
        self.stats = Counter()

    def bad(self, check, condition, rows=None, detail=None):
        mask = np.asarray(condition, dtype=bool)
        count = int(mask.sum())
        if not count:
            return
        self.counts[check] += count
        flat = np.flatnonzero(mask.reshape(-1))
        for ix in flat[:max(0, MAX_SAMPLES-len(self.samples))]:
            record = {'year':self.year, 'batch':self.batch, 'check':check}
            if rows is not None and mask.ndim == 1 and ix < len(rows):
                row = rows.iloc[int(ix)]
                for col in ['strategy_id','ticker','date','signal_date','execution_date','order_id']:
                    if col in row:
                        record[col] = clean(row[col])
            else:
                record['array_index'] = list(np.unravel_index(int(ix), mask.shape)) if mask.ndim else []
            if detail is not None:
                record['detail'] = str(detail)
            self.samples.append(record)

    def equal(self, check, actual, expected, rows=None, atol=MONEY_ATOL, rtol=2e-11):
        a, b = np.asarray(actual, float), np.asarray(expected, float)
        difference = np.abs(a-b)
        finite = np.isfinite(difference)
        if finite.any():
            self.max_error[check] = max(self.max_error.get(check, 0.), float(difference[finite].max()))
        self.bad(check, ~np.isclose(a, b, atol=atol, rtol=rtol, equal_nan=True), rows)

    def drift(self, kind, mask, ids, day, values=None):
        mask = np.asarray(mask, bool)
        self.drift_counts[kind] += int(mask.sum())
        for ix in np.flatnonzero(mask)[:max(0, MAX_SAMPLES-len(self.drift_samples))]:
            row = {'year':self.year,'batch':self.batch,'kind':kind,
                   'strategy_id':str(ids[ix]),'date':str(pd.Timestamp(day).date())}
            if values is not None:
                row['value'] = clean(values[ix])
            self.drift_samples.append(row)

    def result(self):
        return {'status':'PASS' if not self.counts else 'FAIL',
                'failure_count':sum(self.counts.values()), 'failures_by_check':dict(self.counts),
                'failure_samples_saved':len(self.samples), 'max_absolute_errors':self.max_error,
                'drift_or_semantic_counts':dict(self.drift_counts), 'statistics':dict(self.stats)}


class DayTable:
    """One parquet part at a time, in recorder date order; never trusts NAV."""
    def __init__(self, batch, name, evidence):
        self.name, self.column, self.evidence = name, TABLE_DATES[name], evidence
        self.files = sorted((Path(batch)/name).glob('part_*.parquet'))
        self.next_part, self.frame, self.groups = 0, pd.DataFrame(), {}
        self.rows_read = 0
        self.first, self.last = None, None

    def _next(self):
        if self.next_part >= len(self.files):
            self.frame, self.groups, self.first, self.last = pd.DataFrame(), {}, None, None
            return False
        frame = pd.read_parquet(self.files[self.next_part])
        self.next_part += 1
        self.rows_read += len(frame)
        if self.column not in frame:
            self.evidence.bad('missing_table_date_column_'+self.name, True)
            self.frame, self.groups, self.first, self.last = pd.DataFrame(), {}, None, None
            return self._next()
        frame[self.column] = pd.to_datetime(frame[self.column])
        self.evidence.bad('null_table_date_'+self.name, frame[self.column].isna(), frame)
        self.frame = frame
        self.groups = frame.groupby(self.column, sort=False).indices
        self.first, self.last = frame[self.column].min(), frame[self.column].max()
        return True

    def at(self, day):
        day = pd.Timestamp(day)
        if self.first is None and not self._next():
            return self.frame
        while self.last is not None and self.last < day:
            if not self._next():
                return self.frame
        indices = self.groups.get(day)
        return self.frame.iloc[indices].copy() if indices is not None else self.frame.iloc[:0].copy()


class Sources:
    """Only dated source prices and feature rows; no predicted/account NAV input."""
    def __init__(self, root, year):
        self.root, self.year = Path(root), int(year)
        self.stage = 'validation' if year == 2025 else 'final'
        self.prefix = 'pre' if year == 2025 else 'test'
        feature_path = self.root/f'data/{self.prefix}.parquet'
        schema = pq.read_schema(feature_path).names
        columns = ['signal_date','ticker','new_buy_eligible']+FEATURES
        if 'context_only_if_held' in schema:
            columns += ['context_only_if_held']
        frame = pd.read_parquet(feature_path, columns=columns)
        frame['signal_date'] = pd.to_datetime(frame.signal_date)
        end = pd.Timestamp('2025-12-29' if year == 2025 else '2026-09-22')
        self.panel = frame.loc[frame.signal_date.dt.year.eq(year)&frame.signal_date.le(end)].copy()
        self.panel['context_only_if_held'] = self.panel.get('context_only_if_held', False)
        self.panel['new_buy_eligible'] = self.panel.new_buy_eligible.fillna(False).astype(bool)
        self.panel['context_only_if_held'] = self.panel.context_only_if_held.fillna(False).astype(bool)
        self.key_index = pd.MultiIndex.from_frame(self.panel[['signal_date','ticker']])
        self.feature_groups = {pd.Timestamp(d):g.set_index('ticker') for d,g in self.panel.groupby('signal_date',sort=False)}
        cal = pd.read_parquet(self.root/f'data/{self.prefix}_calendar.parquet')
        self.calendar = pd.DatetimeIndex(pd.to_datetime(cal['trade_date'] if 'trade_date' in cal else cal.iloc[:,0]))
        self.calendar = self.calendar[self.calendar.year == year]
        price_path = self.root/f'data/{self.prefix}_prices.parquet'
        pcols = ['trade_date','ticker','open','close']
        if 'price_quality_warning' in pq.read_schema(price_path).names:
            pcols += ['price_quality_warning']
        self.prices = pd.read_parquet(price_path, columns=pcols)
        self.prices['trade_date'] = pd.to_datetime(self.prices.trade_date)
        self.prices['price_quality_warning'] = self.prices.get('price_quality_warning', False)
        self.prices['price_quality_warning'] = self.prices.price_quality_warning.fillna(True).astype(bool)
        for col in ['open','close']:
            self.prices[col] = pd.to_numeric(self.prices[col], errors='coerce')
            valid = np.isfinite(self.prices[col]) & self.prices[col].gt(0) & ~self.prices.price_quality_warning
            self.prices.loc[~valid,col] = np.nan
        self.ops = {}
        if year == 2026:
            path = self.root/'data/test_operational_exit_evidence.csv'
            if path.exists():
                ev = pd.read_csv(path)
                if len(ev):
                    ev['known_at'] = pd.to_datetime(ev.known_at, utc=True)
                    ev['effective_date'] = pd.to_datetime(ev.effective_date)
                    early = {'2026-11-27','2026-12-24'}
                    for day in self.calendar:
                        asof = (day+pd.Timedelta(hours=13 if str(day.date()) in early else 16)).tz_localize('America/New_York').tz_convert('UTC')
                        known = ev.loc[ev.known_at.le(asof)&ev.effective_date.le(day)]
                        self.ops[day] = set(known.ticker.astype(str))
        self.hashes = {str(p.relative_to(self.root)):sha(p) for p in [feature_path,price_path,self.root/f'data/{self.prefix}_calendar.parquet']}

    def arrays(self, names, calendar):
        lookup = {t:i for i,t in enumerate(names)}
        lookup_days = {pd.Timestamp(d):i for i,d in enumerate(calendar)}
        N, T = len(names), len(calendar)
        opens, closes = np.full((T,N),np.nan), np.full((T,N),np.nan)
        prices = self.prices.loc[self.prices.ticker.isin(lookup)]
        chosen = prices.loc[prices.trade_date.isin(lookup_days)]
        ri = chosen.trade_date.map(lookup_days).to_numpy(int)
        ci = chosen.ticker.map(lookup).to_numpy(int)
        opens[ri,ci], closes[ri,ci] = chosen.open.to_numpy(float), chosen.close.to_numpy(float)
        initial = np.full(N,np.nan)
        history = prices.loc[prices.trade_date.lt(calendar[0])&prices.close.notna()].sort_values('trade_date').drop_duplicates('ticker',keep='last')
        initial[history.ticker.map(lookup).to_numpy(int)] = history.close.to_numpy(float)
        present, eligible, held_only = np.zeros((T,N),bool), np.zeros((T,N),bool), np.zeros((T,N),bool)
        adv = np.full((T,N),np.nan)
        for i,day in enumerate(calendar):
            frame = self.feature_groups.get(pd.Timestamp(day))
            if frame is None:
                continue
            frame = frame.loc[frame.index.isin(lookup)]
            c = np.asarray([lookup[t] for t in frame.index],int)
            present[i,c],eligible[i,c],held_only[i,c] = True,frame.new_buy_eligible.to_numpy(bool),frame.context_only_if_held.to_numpy(bool)
            adv[i,c] = frame.avg_dollar_volume_20d.to_numpy(float)
        return opens,closes,initial,present,eligible,held_only,adv


def source_prediction_coverage(root, sources, registry, evidence):
    streams = registry['streams']
    evidence.bad('preregistered_stream_count_is_75', len(streams) != 75)
    evidence.bad('duplicate_source_input_keys', sources.key_index.duplicated())
    evidence.bad('nonfinite_source_input_features', ~np.isfinite(sources.panel[FEATURES].to_numpy(float)).all(axis=1), sources.panel)
    records = []
    for item in streams:
        name = item['stream']
        path = Path(root)/f'predictions/streams/{sources.stage}/{name}.parquet'
        if not path.exists():
            evidence.bad('missing_registered_prediction_stream', True, detail=name)
            records.append({'stream':name,'status':'MISSING'})
            continue
        frame = pd.read_parquet(path, columns=['signal_date','ticker','mu','sigma'])
        frame['signal_date'] = pd.to_datetime(frame.signal_date)
        keys = pd.MultiIndex.from_frame(frame[['signal_date','ticker']])
        duplicate = keys.duplicated()
        evidence.bad('duplicate_prediction_keys', duplicate, frame, name)
        if duplicate.any():
            frame = frame.loc[~duplicate].copy()
            keys = keys[~duplicate]
        loc = keys.get_indexer(sources.key_index)
        missing = loc < 0
        evidence.bad('prediction_missing_source_keys', missing, sources.panel, name)
        valid = ~missing
        selected = frame.iloc[loc[valid]]
        finite = np.isfinite(selected[['mu','sigma']].to_numpy(float)).all(axis=1)
        nonpositive = selected.sigma.to_numpy(float) < 0
        evidence.bad('nonfinite_or_negative_prediction_scale', ~finite|nonpositive, selected, name)
        records.append({'stream':name,'status':'PASS' if not missing.any() and finite.all() and not nonpositive.any() else 'FAIL',
                        'source_keys':len(sources.key_index),'prediction_keys':len(frame),
                        'missing_keys':int(missing.sum()),'nonfinite_or_negative_scale':int((~finite|nonpositive).sum()),'sha256':sha(path)})
    return {'stage':sources.stage,'source_key_scope':'actual saved legal feature panel; formal full-pool certification assessed separately',
            'source_keys':len(sources.key_index),'streams':records,**evidence.result()}


def frame_indices(frame, idmap, namemap, evidence, table):
    if frame.empty:
        return np.empty(0,int),np.empty(0,int)
    unknown = ~frame.strategy_id.isin(idmap)|~frame.ticker.isin(namemap)
    evidence.bad('unknown_strategy_or_ticker_'+table, unknown, frame)
    if unknown.any():
        raise ValueError('cannot reconstruct unknown ledger keys: '+table)
    return frame.strategy_id.map(idmap).to_numpy(int),frame.ticker.map(namemap).to_numpy(int)


def unpack_coverage(path, K, N, evidence):
    with np.load(path, allow_pickle=False) as z:
        evidence.bad('coverage_dimensions', int(z['ticker_count']) != N or int(z['strategy_count']) != K)
        raw = np.asarray(z['targets'],float)
        evidence.bad('coverage_target_shape', raw.shape != (K,N))
        if raw.shape != (K,N):
            raise ValueError('coverage target shape')
        result = {'targets':raw}
        for field in ['decided','decision_mask','reserved_mask','final_reserved_mask','buy_allowed_mask']:
            bits = np.asarray(z[field])
            evidence.bad('coverage_packed_shape_'+field, bits.shape != (K,(N+7)//8) or bits.dtype != np.uint8)
            if bits.shape != (K,(N+7)//8):
                raise ValueError('coverage bit shape '+field)
            expanded = np.unpackbits(bits,axis=1,bitorder='little')
            evidence.bad('coverage_nonzero_padding_'+field, expanded[:,N:] != 0)
            result[field] = expanded[:,:N].astype(bool)
    return result


def shared_bindings(root, sources, registry):
    """Hash all immutable evidence dependencies once per year in this run."""
    root=Path(root)
    result={str(p.relative_to(root)):sha(p) for p in
            [root/'REGISTRY.json',root/'common.py',root/'policy.py',root/'batch_engine.py',
             root/'EXPERIMENT_CONTRACT.md',root/'OPTIMIZATION_IMPLEMENTATION.md'] if p.exists()}
    result.update(sources.hashes)
    for item in registry['streams']:
        relative=f'predictions/streams/{sources.stage}/{item["stream"]}.parquet'
        path=root/relative
        result[relative]=sha(path) if path.exists() else 'MISSING'
    freeze_path=root/'FREEZE.json'
    if freeze_path.exists():
        freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
        result['FREEZE.json']=sha(freeze_path)
        for relative,expected in freeze.get('artifact_sha256',{}).items():
            path=root/relative
            actual=sha(path) if path.exists() else 'MISSING'
            if actual != expected:
                raise ValueError('frozen evidence changed: '+relative)
            result['freeze_artifact/'+relative]=actual
    return result


def ledger_bindings(batch):
    """Full contents, not size/mtime: includes every table and NPZ/expert file."""
    return {p.relative_to(batch).as_posix():sha(p) for p in sorted(Path(batch).rglob('*')) if p.is_file()}


def load_pass_cache(root,batch,year,sources_sha256,code_sha256):
    path=Path(root)/f'audits/verification_cache/{year}_{Path(batch).name}.json'
    if not path.exists():
        return None,'MISSING'
    try:
        cache=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError):
        return None,'UNREADABLE'
    if (cache.get('cache_version') != CACHE_VERSION or cache.get('status') != 'PASS' or
        cache.get('verifier_code_sha256') != code_sha256 or
        cache.get('shared_source_sha256') != sources_sha256 or
        cache.get('ledger_sha256') != ledger_bindings(batch)):
        return None,'HASH_OR_VERSION_CHANGED'
    result=cache['result'].copy()
    result.update(cache_reused=True,cache_file=str(path.relative_to(root)),cache_sha256=sha(path),
                  cache_verification='ALL_SAVED_CONTENT_AND_SOURCE_HASHES_MATCH')
    ev=Evidence(year,Path(batch).name)
    ev.samples=cache.get('failure_samples',[])
    ev.drift_samples=cache.get('drift_samples',[])
    return (result,ev),'PASS_REUSED'


def save_pass_cache(root,batch,year,result,ev,sources_sha256,code_sha256,before_hashes):
    if result.get('status') != 'PASS' or not (Path(batch)/'COMPLETE.json').exists():
        raise ValueError('only complete PASS accounts may be cached')
    after_hashes=ledger_bindings(batch)
    if before_hashes != after_hashes:
        raise ValueError('ledger changed while independent verification was running')
    path=Path(root)/f'audits/verification_cache/{year}_{Path(batch).name}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    record={'cache_version':CACHE_VERSION,'status':'PASS',
            'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'verifier_code_sha256':code_sha256,
            'shared_source_sha256':sources_sha256,'ledger_sha256':after_hashes,'result':result,
            'failure_samples':ev.samples,'drift_samples':ev.drift_samples}
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(clean(record),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)
    return str(path.relative_to(root))


def verify_batch(root, batch, year, sources, registry):
    started = time.time()
    root,batch = Path(root),Path(batch)
    evidence = Evidence(year,batch.name)
    metadata = json.loads((batch/'metadata.json').read_text(encoding='utf-8'))
    complete = json.loads((batch/'COMPLETE.json').read_text(encoding='utf-8'))
    ids,names = np.asarray(metadata['strategy_ids'],str),np.asarray(metadata['tickers'],str)
    K,N = len(ids),len(names)
    idmap,namemap = {s:i for i,s in enumerate(ids)},{t:i for i,t in enumerate(names)}
    strategies = {p['strategy']:p for p in registry['strategies']}
    evidence.bad('duplicate_account_ids', len(idmap) != K)
    evidence.bad('duplicate_ticker_ids', len(namemap) != N)
    evidence.bad('unregistered_account', [s not in strategies for s in ids])
    evidence.bad('complete_account_order', complete.get('strategies') != ids.tolist())
    evidence.bad('complete_metadata_hash', complete.get('metadata_sha256') != sha(batch/'metadata.json'))
    evidence.bad('common_cost_or_account_contract', metadata['cost_bps_one_way'] != 10 or metadata['capacity_fraction'] != .01 or
                 metadata['capacity_on_sells'] or metadata['max_positions'] != 20 or metadata['max_target_weight'] != .1 or
                 metadata['max_target_invested'] != .95 or metadata['terminal_liquidation'])
    if (batch/'SUMMARY.csv').exists() and 'summary_sha256' in complete:
        evidence.bad('complete_summary_hash', complete['summary_sha256'] != sha(batch/'SUMMARY.csv'))
    calendar = sources.calendar[(sources.calendar >= pd.Timestamp(metadata['valuation_first']))&
                                (sources.calendar <= pd.Timestamp(metadata['valuation_last']))]
    evidence.bad('valuation_calendar_coverage', len(calendar) != complete.get('days'))
    opens,closes,marks,present,eligible,held_only,adv = sources.arrays(names,calendar)
    cash,units = np.asarray(metadata['initial_cash'],float),np.asarray(metadata['initial_units'],float)
    evidence.bad('initial_account_shape', cash.shape != (K,) or units.shape != (K,N))
    if cash.shape != (K,) or units.shape != (K,N):
        raise ValueError('initial shape')
    evidence.bad('initial_cash_not_one_million', cash != 1e6)
    evidence.bad('initial_units_nonzero', units != 0.)
    cash,units = cash.copy(),units.copy()
    readers = {name:DayTable(batch,name,evidence) for name in TABLE_DATES}
    counts,statuses,expert_statuses = Counter(),Counter(),Counter()
    solver_diagnostics={}
    pending = pd.DataFrame()
    last_nav,last_cert = np.full(K,np.nan),np.full(K,np.nan)
    initial_cash = cash.copy()
    expected_signals = set(calendar[(calendar >= pd.Timestamp(metadata['signal_start']))&(calendar <= pd.Timestamp(metadata['signal_end']))])
    coverage_files = {pd.Timestamp(p.stem):p for p in (batch/'decision_coverage').glob('*.npz') if not p.stem.endswith('_experts')}
    evidence.bad('decision_coverage_dates', set(coverage_files) != expected_signals)
    for i,day in enumerate(calendar):
        day_frames = {name:reader.at(day) for name,reader in readers.items()}
        for name,frame in day_frames.items():
            counts[name] += len(frame)
        daily,trades,positions = day_frames['daily'],day_frames['trades'],day_frames['positions']
        target,raw_rows,signal_ctx = day_frames['target_decisions'],day_frames['raw_model_outputs'],day_frames['signal_contexts']
        executions,operational = day_frames['execution_results'],day_frames['operational_actions']
        evidence.bad('daily_all_accounts_once', len(daily) != K or daily.strategy_id.duplicated().any() or set(daily.strategy_id) != set(ids))
        if len(daily) != K or set(daily.strategy_id) != set(ids):
            raise ValueError('daily incomplete')
        daily = daily.set_index('strategy_id').loc[ids].reset_index()
        open_ok,close_ok = np.isfinite(opens[i]),np.isfinite(closes[i])
        before = units > TOL
        open_unknown = (before&~open_ok[None,:]&~np.isfinite(marks)[None,:]).sum(axis=1)
        open_stale = (before&~open_ok[None,:]&np.isfinite(marks)[None,:]).sum(axis=1)
        marks[open_ok] = opens[i,open_ok]
        open_marks = marks.copy()
        pre_nav = cash+(units*np.nan_to_num(open_marks)[None,:]).sum(axis=1)
        pre_nav[open_unknown > 0] = np.nan
        evidence.equal('opening_nav_from_prior_units', daily.open_pretrade_nav,pre_nav,daily)
        evidence.equal('pretrade_nav_alias', daily.pretrade_nav,pre_nav,daily)
        evidence.equal('open_stale_count', daily.open_stale_count,open_stale,daily,atol=0,rtol=0)
        evidence.equal('open_unknown_count', daily.open_unknown_count,open_unknown,daily,atol=0,rtol=0)
        cash_before = cash.copy()
        bought,sold,fees = np.zeros(K),np.zeros(K),np.zeros(K)
        if len(trades):
            rr,cc = frame_indices(trades,idmap,namemap,evidence,'trades')
            evidence.bad('multiple_fills_same_order_side', trades.duplicated(['order_id','side']),trades)
            evidence.bad('fill_positive_units_notional', ~np.isfinite(trades[['price','notional','index_units','transaction_cost']].to_numpy(float)).all(axis=1)|
                         trades.price.le(0).to_numpy()|trades.notional.le(0).to_numpy()|trades.index_units.le(0).to_numpy(),trades)
            evidence.equal('fill_price_matches_source_open',trades.price,opens[i,cc],trades,atol=1e-10)
            evidence.equal('fill_quantity_times_price',trades.notional,trades.index_units*trades.price,trades)
            evidence.equal('fill_fee_is_notional_10bps',trades.transaction_cost,trades.notional*.001,trades,atol=1e-9)
            evidence.equal('fill_cost_bps_contract',trades.cost_bps,np.full(len(trades),10.),trades,atol=0,rtol=0)
            evidence.equal('fill_pretrade_nav',trades.pretrade_nav,pre_nav[rr],trades)
            evidence.bad('signal_precedes_execution',pd.to_datetime(trades.signal_date).ge(pd.to_datetime(trades.execution_date)),trades)
            evidence.bad('fill_execution_date_matches_day',pd.to_datetime(trades.execution_date).ne(day),trades)
            if pending.empty:
                evidence.bad('fill_without_previous_signal_order',np.ones(len(trades),bool),trades)
                joined = trades.copy()
            else:
                joined = trades.merge(pending.add_prefix('order_'),left_on='order_id',right_on='order_order_id',how='left',validate='many_to_one')
                evidence.bad('fill_order_link_missing',joined.order_order_id.isna(),joined)
                evidence.bad('hold_units_order_was_traded',joined.order_order_type.eq('HOLD_UNITS'),joined)
                for column in ['strategy_id','ticker','signal_date','execution_date','decision_id','decision_semantic']:
                    if column in ['signal_date','execution_date']:
                        mismatch = pd.to_datetime(joined[column]).ne(pd.to_datetime(joined['order_'+column]))
                    else:
                        mismatch = joined[column].ne(joined['order_'+column])
                    evidence.bad('fill_order_link_'+column,mismatch,joined)
            for side in ['SELL','BUY']:
                mask = trades.side.eq(side).to_numpy()
                tr = trades.loc[mask]
                r,c = rr[mask],cc[mask]
                if not len(tr):
                    continue
                evidence.equal('fill_units_before_'+side,tr.index_units_before,units[r,c],tr,atol=UNIT_ATOL)
                signed = tr.index_units.to_numpy(float)*(1 if side == 'BUY' else -1)
                np.add.at(units,(r,c),signed)
                units[units <= TOL] = 0.
                evidence.equal('fill_units_after_'+side,tr.index_units_after,units[r,c],tr,atol=UNIT_ATOL)
                amount,cost = tr.notional.to_numpy(float),tr.transaction_cost.to_numpy(float)
                np.add.at(cash,r,(amount if side == 'SELL' else -amount)-cost)
                np.add.at(sold if side == 'SELL' else bought,r,amount)
                np.add.at(fees,r,cost)
                evidence.bad('negative_units_after_fill',units < -UNIT_ATOL)
                if side == 'BUY':
                    sig = pd.to_datetime(tr.signal_date)
                    source_keys = pd.MultiIndex.from_arrays([sig,tr.ticker])
                    loc = sources.key_index.get_indexer(source_keys)
                    evidence.bad('buy_without_source_signal_input',loc < 0,tr)
                    ok = loc >= 0
                    flags = np.zeros(len(tr),bool)
                    flags[ok] = sources.panel.iloc[loc[ok]].new_buy_eligible.to_numpy(bool)
                    evidence.bad('buy_without_signal_eligibility',~flags,tr)
                    signal_adv = np.full(len(tr),np.nan)
                    signal_adv[ok] = sources.panel.iloc[loc[ok]].avg_dollar_volume_20d.to_numpy(float)
                    evidence.bad('buy_exceeds_signal_ADV_1pct',~np.isfinite(signal_adv)|(signal_adv <= 0)|(amount > .01*signal_adv+MONEY_ATOL),tr)
                    evidence.equal('buy_reported_signal_ADV',tr.capacity_adv,signal_adv,tr)
                    evidence.bad('buy_capacity_not_enforced',~tr.capacity_enforced.astype(bool),tr)
                    evidence.bad('buy_ADV_future_or_stale',pd.to_datetime(tr.capacity_adv_source_date).ne(sig)|tr.capacity_adv_stale.astype(bool),tr)
            evidence.bad('unknown_fill_side',~trades.side.isin(['BUY','SELL']),trades)
        evidence.bad('negative_cash_from_fills',cash < -np.maximum(MONEY_ATOL,initial_cash*1e-12),daily)
        cash = np.maximum(cash,0.)
        held = units > TOL
        live = held.sum(axis=1)
        evidence.bad('actual_positions_over_20',live > 20,daily)
        open_after = cash+(units*np.nan_to_num(open_marks)[None,:]).sum(axis=1)
        open_after[open_unknown > 0] = np.nan
        evidence.equal('opening_posttrade_nav',daily.open_posttrade_nav,open_after,daily)
        evidence.equal('open_self_financing_including_costs',open_after,pre_nav-fees,daily)
        marks[close_ok] = closes[i,close_ok]
        unknown = held&~np.isfinite(marks)[None,:]
        stale = held&~close_ok[None,:]&np.isfinite(marks)[None,:]
        position_values = units*np.nan_to_num(marks)[None,:]
        known_values = position_values.sum(axis=1)
        nav = cash+known_values
        nav[unknown.any(axis=1)] = np.nan
        certified = np.where(unknown.any(axis=1)|stale.any(axis=1),np.nan,nav)
        weights = np.divide(position_values,nav[:,None],out=np.full((K,N),np.nan),where=np.isfinite(nav[:,None])&(nav[:,None] > 0))
        gross = np.divide(known_values,nav,out=np.full(K,np.nan),where=np.isfinite(nav)&(nav > 0))
        for check,column,expected in [('cash_from_fills','cash',cash),('closing_nav_from_source_prices','nav',nav),
            ('certified_nav_from_source_prices','certified_nav',certified),('known_position_values','known_position_value',known_values),
            ('daily_fees_from_fills','transaction_cost_amount',fees),('daily_buy_notional','buy_notional',bought),
            ('daily_sell_notional','sell_notional',sold),('daily_traded_notional','traded_notional',bought+sold)]:
            evidence.equal(check,daily[column],expected,daily)
        evidence.equal('daily_cash_flow_from_fills',daily.cash-cash_before,sold-bought-fees,daily)
        evidence.equal('daily_fee_rate',fees,(bought+sold)*.001,daily,atol=1e-9)
        evidence.equal('daily_actual_name_count',daily.actual_name_count,live,daily,atol=0,rtol=0)
        evidence.equal('daily_unknown_count',daily.unknown_count,unknown.sum(axis=1),daily,atol=0,rtol=0)
        evidence.equal('daily_stale_count',daily.stale_count,stale.sum(axis=1),daily,atol=0,rtol=0)
        evidence.equal('daily_gross_exposure',daily.gross_exposure,gross,daily,atol=WEIGHT_ATOL)
        cashweight = np.divide(cash,nav,out=np.full(K,np.nan),where=np.isfinite(nav)&(nav > 0))
        evidence.equal('daily_cash_weight',daily.cash_weight,cashweight,daily,atol=WEIGHT_ATOL)
        netret = np.divide(certified,last_cert,out=np.full(K,np.nan),where=np.isfinite(certified)&np.isfinite(last_cert)&(last_cert > 0))-1
        indret = np.divide(nav,last_nav,out=np.full(K,np.nan),where=np.isfinite(nav)&np.isfinite(last_nav)&(last_nav > 0))-1
        evidence.equal('daily_return_link','net_return' in daily and daily.net_return,netret,daily,atol=1e-11)
        evidence.equal('daily_indicative_return_link',daily.indicative_return,indret,daily,atol=1e-11)
        evidence.drift('actual_gross_above_95pct_at_close',gross > .95+WEIGHT_ATOL,ids,day,gross)
        evidence.drift('actual_gross_above_100pct_at_close',gross > 1+WEIGHT_ATOL,ids,day,gross)
        evidence.bad('actual_gross_above_100pct',gross > 1+WEIGHT_ATOL,daily)
        max_single = np.nanmax(np.where(held,weights,0.),axis=1)
        evidence.drift('actual_single_weight_above_10pct_at_close',max_single > .1+WEIGHT_ATOL,ids,day,max_single)
        if len(positions):
            r,c = frame_indices(positions,idmap,namemap,evidence,'positions')
            evidence.bad('duplicate_daily_position_key',positions.duplicated(['strategy_id','ticker']),positions)
            evidence.equal('position_units_from_fills',positions.index_units,units[r,c],positions,atol=UNIT_ATOL)
            evidence.equal('position_mark_from_source',positions.mark,marks[c],positions,atol=1e-10)
            expected_value = np.where(unknown[r,c],np.nan,position_values[r,c])
            evidence.equal('position_market_value_from_source',positions.market_value,expected_value,positions)
            evidence.equal('position_weight_from_source',positions.weight,weights[r,c],positions,atol=WEIGHT_ATOL)
            evidence.bad('position_unknown_flag',positions.unknown.to_numpy(bool) != unknown[r,c],positions)
            evidence.bad('position_stale_flag',positions.stale.to_numpy(bool) != stale[r,c],positions)
            described = np.zeros((K,N),bool);described[r,c] = True
            evidence.bad('held_units_without_position_record',held != described)
        else:
            evidence.bad('held_units_without_position_record',held)
        # Executed HOLD_UNITS remains an omission/reservation, never a zero exit.
        if len(pending):
            holdorders = pending.loc[pending.order_type.eq('HOLD_UNITS')]
            if len(holdorders):
                r,c = frame_indices(holdorders,idmap,namemap,evidence,'pending_holds')
                evidence.equal('omitted_decision_preserves_actual_units',units[r,c],holdorders.current_units,holdorders,atol=UNIT_ATOL)
        if len(executions):
            evidence.bad('execution_live_positions_over_20',executions.actual_names_at_event.gt(20),executions)
            evidence.bad('execution_live_positions_negative',executions.actual_names_at_event.lt(0),executions)
            if len(pending):
                linked = executions.merge(pending[['order_id','strategy_id','ticker','signal_date','execution_date']].add_prefix('order_'),
                                          left_on='order_id',right_on='order_order_id',how='left',validate='many_to_one')
                evidence.bad('execution_without_pending_order',linked.order_order_id.isna(),linked)
            else:
                evidence.bad('execution_without_pending_order',np.ones(len(executions),bool),executions)
            fills = executions.loc[executions.status.eq('FILLED')]
            evidence.bad('trade_execution_fill_count',len(fills) != len(trades))
            if len(fills) or len(trades):
                pair = trades.merge(fills[['order_id','side','notional','index_units','transaction_cost']],on=['order_id','side'],
                                    how='outer',suffixes=('_trade','_outcome'),indicator=True,validate='one_to_one')
                evidence.bad('trade_execution_fill_link',pair['_merge'].ne('both'),pair)
                for col in ['notional','index_units','transaction_cost']:
                    evidence.equal('trade_execution_'+col,pair[col+'_trade'],pair[col+'_outcome'],pair,
                                   atol=UNIT_ATOL if col == 'index_units' else MONEY_ATOL)
        elif len(trades) or len(pending):
            evidence.bad('pending_orders_without_execution_outcomes',True)
        if day in expected_signals:
            if day not in coverage_files:
                raise ValueError('missing complete decision matrix')
            coverage = unpack_coverage(coverage_files[day],K,N,evidence)
            raw,decided = coverage['targets'],coverage['decided']
            decision_mask,reserved,final_reserved,buy_allowed = [coverage[x] for x in ['decision_mask','reserved_mask','final_reserved_mask','buy_allowed_mask']]
            evidence.bad('decided_outside_decision_input',decided&~decision_mask)
            evidence.bad('explicit_target_nonfinite_or_bounds',decided&(~np.isfinite(raw)|(raw < 0)|(raw > .1+1e-7)))
            evidence.bad('omission_matrix_weight_must_be_zero',~decided&(raw != 0))
            signal_present = present[i][None,:]&(~held_only[i][None,:]|held)
            expected_buy = signal_present&eligible[i][None,:]&close_ok[None,:]
            evidence.bad('buy_allowed_mask_from_legal_source',buy_allowed != expected_buy)
            ops = np.asarray([t in sources.ops.get(day,set()) for t in names],bool)
            expected_reserved = held&(~signal_present|~close_ok[None,:])
            expected_reserved &= ~ops[None,:]|~close_ok[None,:]
            expected_reserved |= held&(~np.isfinite(nav)|(nav <= 0))[:,None]
            evidence.bad('reserved_mask_from_legal_source',reserved != expected_reserved)
            expected_mask = signal_present&~expected_reserved&~ops[None,:]&~(~close_ok[None,:]&~held)&np.isfinite(nav[:,None])&(nav[:,None] > 0)
            evidence.bad('decision_input_mask_from_legal_source',decision_mask != expected_mask)
            expected_final = expected_reserved|(held&~decided&~ops[None,:])
            expected_final &= ~ops[None,:]|~close_ok[None,:]
            evidence.bad('omission_requires_final_reservation',final_reserved != expected_final)
            evidence.stats['decision_cells'] += K*N
            evidence.stats['explicit_decision_cells'] += int(decided.sum())
            evidence.stats['explicit_unheld_zero_cells'] += int((decided&~held&(raw == 0)).sum())
            evidence.stats['explicit_held_zero_cells'] += int((decided&held&(raw == 0)).sum())
            evidence.stats['held_omission_cells'] += int((held&~decided).sum())
            evidence.bad('raw_output_all_accounts_once',len(raw_rows) != K or raw_rows.strategy_id.duplicated().any() or set(raw_rows.strategy_id) != set(ids))
            evidence.bad('signal_context_all_accounts_once',len(signal_ctx) != K or signal_ctx.strategy_id.duplicated().any() or set(signal_ctx.strategy_id) != set(ids))
            if len(raw_rows) != K or len(signal_ctx) != K:
                raise ValueError('raw/context rows incomplete')
            raw_rows = raw_rows.set_index('strategy_id').loc[ids].reset_index()
            signal_ctx = signal_ctx.set_index('strategy_id').loc[ids].reset_index()
            evidence.equal('raw_matrix_row_account_link',raw_rows.raw_matrix_strategy_row,np.arange(K),raw_rows,atol=0,rtol=0)
            evidence.equal('raw_decided_count',raw_rows.decided_count,decided.sum(axis=1),raw_rows,atol=0,rtol=0)
            evidence.equal('raw_unheld_zero_count',raw_rows.explicit_unheld_zero_count,(decided&~held&(raw == 0)).sum(axis=1),raw_rows,atol=0,rtol=0)
            evidence.equal('signal_account_cash',signal_ctx.cash,cash,signal_ctx)
            evidence.equal('signal_account_NAV',signal_ctx.nav,nav,signal_ctx)
            evidence.equal('signal_input_count',signal_ctx.input_count,signal_present.sum(axis=1),signal_ctx,atol=0,rtol=0)
            evidence.equal('signal_decision_input_count',signal_ctx.decision_input_count,decision_mask.sum(axis=1),signal_ctx,atol=0,rtol=0)
            finalweight = np.where(final_reserved,weights,0.).sum(axis=1)
            evidence.equal('signal_final_reserved_slots',signal_ctx.final_reserved_slots,final_reserved.sum(axis=1),signal_ctx,atol=0,rtol=0)
            evidence.equal('signal_final_reserved_weight',signal_ctx.final_reserved_weight,finalweight,signal_ctx,atol=WEIGHT_ATOL)
            evidence.drift('retained_signal_weight_above_95pct',finalweight > .95+WEIGHT_ATOL,ids,day,finalweight)
            if len(target):
                r,c = frame_indices(target,idmap,namemap,evidence,'target_decisions')
                evidence.bad('duplicate_signal_order_id',target.order_id.duplicated(),target)
                evidence.bad('target_wrong_decision_id',target.decision_id != target.strategy_id+'|'+str(day.date()),target)
                evidence.bad('target_wrong_order_id',target.order_id != target.decision_id+'|'+target.ticker,target)
                evidence.equal('target_actual_current_units',target.current_units,units[r,c],target,atol=UNIT_ATOL)
                evidence.equal('target_actual_current_weight',target.current_weight,weights[r,c],target,atol=WEIGHT_ATOL)
                evidence.equal('target_signal_close_NAV',target.signal_close_nav,nav[r],target)
                evidence.equal('target_source_signal_ADV',target.signal_day_adv,adv[i,c],target)
                evidence.bad('target_explicit_bit_link',target.explicit_model_decision.to_numpy(bool) != decided[r,c],target)
                evidence.equal('target_raw_weight_link',target.raw_model_weight,np.where(decided[r,c],raw[r,c],np.nan),target,atol=WEIGHT_ATOL)
                evidence.bad('target_final_reservation_link',target.signal_reserved.to_numpy(bool) != final_reserved[r,c],target)
                evidence.bad('target_input_present_link',target.model_input_row_present.to_numpy(bool) != signal_present[r,c],target)
                evidence.bad('target_decision_input_link',target.decision_input_row_present.to_numpy(bool) != decision_mask[r,c],target)
                has_order = np.zeros((K,N),bool);has_order[r,c] = True
                expected_orders = held|(decided&(raw > 0))|ops[None,:]
                evidence.bad('sparse_orders_do_not_match_complete_matrix',has_order != expected_orders)
                hold_mask = target.order_type.eq('HOLD_UNITS').to_numpy()
                evidence.bad('hold_units_type_link',hold_mask != (final_reserved[r,c]&~ops[c]),target)
                evidence.equal('hold_units_quantity_link',target.hold_units,np.where(hold_mask,units[r,c],0),target,atol=UNIT_ATOL)
                evidence.equal('hold_target_is_current_weight',target.loc[hold_mask,'target_weight'],weights[r[hold_mask],c[hold_mask]],target.loc[hold_mask],atol=WEIGHT_ATOL)
                explicit_exit = decided[r,c]&(raw[r,c] == 0)&held[r,c]&~ops[c]
                evidence.bad('explicit_zero_held_exit_semantic',explicit_exit&target.decision_semantic.ne('MODEL_ACTIVE_EXIT').to_numpy(),target)
                evidence.bad('omitted_held_was_zero_exit',(~decided[r,c]&held[r,c]&~ops[c])&target.decision_semantic.eq('MODEL_ACTIVE_EXIT').to_numpy(),target)
                active = np.zeros((K,N));active[r[~hold_mask],c[~hold_mask]] = target.target_weight.to_numpy(float)[~hold_mask]
                evidence.bad('active_adapted_target_outside_bounds',(active < -WEIGHT_ATOL)|(active > .1+1e-7))
                # Signal slot reservations count every strictly positive target;
                # execution/actual holdings separately use the quantity TOL.
                active_sum,active_count = active.sum(axis=1),(active > 0).sum(axis=1)
                slots = np.maximum(0,20-final_reserved.sum(axis=1))
                budget = np.maximum(0,.95-finalweight)
                evidence.max_error['maximum_positive_active_cash_budget_violation']=max(evidence.max_error.get('maximum_positive_active_cash_budget_violation',0.),float(np.maximum(active_sum-budget,0.).max()))
                evidence.max_error['maximum_positive_raw_cash_budget_violation']=max(evidence.max_error.get('maximum_positive_raw_cash_budget_violation',0.),float(np.maximum(raw.sum(axis=1)-budget,0.).max()))
                evidence.bad('raw_targets_exceed_final_reserved_cash',raw.sum(axis=1)>budget+WEIGHT_ATOL,signal_ctx)
                evidence.bad('active_targets_exceed_reserved_slots',active_count > slots,signal_ctx)
                evidence.bad('active_targets_exceed_reserved_cash',active_sum > budget+WEIGHT_ATOL,signal_ctx)
                evidence.equal('signal_active_count',signal_ctx.active_target_count,active_count,signal_ctx,atol=0,rtol=0)
                evidence.equal('signal_active_target_sum',signal_ctx.active_target_weight,active_sum,signal_ctx,atol=WEIGHT_ATOL)
                committed = active_sum+finalweight
                evidence.drift('committed_signal_weight_above_95pct',committed > .95+WEIGHT_ATOL,ids,day,committed)
                evidence.drift('retained_signal_weight_above_100pct',finalweight > 1+WEIGHT_ATOL,ids,day,finalweight)
                evidence.equal('target_total_committed_weight',target.total_signal_committed_weight,committed[r],target,atol=WEIGHT_ATOL)
                next_day = calendar[i+1] if i+1 < len(calendar) else pd.NaT
                evidence.bad('target_execution_clock_next_session',pd.to_datetime(target.execution_date).ne(next_day) if pd.notna(next_day) else target.execution_date.notna(),target)
                if pd.notna(next_day):
                    evidence.bad('target_signal_precedes_execution',pd.to_datetime(target.signal_date).ge(pd.to_datetime(target.execution_date)),target)
            else:
                evidence.bad('held_or_positive_target_without_order',held|(decided&(raw > 0))|ops[None,:])
                evidence.equal('empty_signal_active_count',signal_ctx.active_target_count,np.zeros(K),signal_ctx,atol=0,rtol=0)
            for j,record in enumerate(raw_rows.itertuples()):
                payload = json.loads(record.raw_model_outputs_json)
                if not isinstance(payload,dict):
                    evidence.bad('raw_policy_metadata_missing',True,detail=str(ids[j]));continue
                path_contract = strategies.get(str(ids[j]),{})
                for field in ['stream','risk','optimizer','axis']:
                    evidence.bad('raw_registered_'+field,payload.get(field) != path_contract.get(field),detail=str(ids[j]))
                expected = f'predictions/streams/{sources.stage}/{path_contract.get("stream")}.parquet'
                evidence.bad('raw_prediction_source_link',payload.get('prediction_file') != expected,detail=str(ids[j]))
                status = str(payload.get('solver_status','MISSING'))
                statuses[status] += 1
                residual=payload.get('solver_residual')
                objective=payload.get('objective')
                if status in ['SOLVED_TOLERANCE','SOLVED_CASH_CERTIFICATE','APPROXIMATE_BUDGET']:
                    finite=residual is not None and objective is not None and np.isfinite(residual) and np.isfinite(objective)
                    evidence.bad('solver_diagnostic_nonfinite',not finite,detail=str(ids[j]))
                    if finite:
                        evidence.bad('solver_residual_negative',float(residual)<-1e-12,detail=str(ids[j]))
                        if status in ['SOLVED_TOLERANCE','SOLVED_CASH_CERTIFICATE']:
                            evidence.bad('solved_status_residual_exceeds_1e5',float(residual)>1e-5+1e-10,detail=str(ids[j]))
                        stat=solver_diagnostics.setdefault(status,{'rows':0,'residual_sum':0.,'maximum_residual':0.})
                        stat['rows']+=1;stat['residual_sum']+=float(residual)
                        stat['maximum_residual']=max(stat['maximum_residual'],float(residual))
                if status == 'FAILED_PRESERVE_UNITS':
                    evidence.bad('failed_solver_explicit_decision',decided[j])
                experts = payload.get('expert_solver_statuses',{})
                expert_statuses.update(str(s) for s in experts.values())
                expert_residuals=payload.get('expert_solver_residuals',{})
                for member,expert_status in experts.items():
                    residual=expert_residuals.get(member)
                    if expert_status in ['SOLVED_TOLERANCE','SOLVED_CASH_CERTIFICATE']:
                        evidence.bad('expert_solved_residual_invalid',residual is None or not np.isfinite(residual) or float(residual)>1e-5+1e-10,
                                     detail=str(ids[j])+'|'+member)
                if path_contract.get('target_fusion','none') != 'none':
                    evidence.bad('target_fusion_expert_statuses_missing',set(experts) != set(POINT),detail=str(ids[j]))
                    expected_files = [f'predictions/streams/{sources.stage}/{m}.parquet' for m in POINT]
                    evidence.bad('target_fusion_prediction_source_links',payload.get('prediction_files') != expected_files,detail=str(ids[j]))
                if path_contract.get('axis') in ['buy','sell']:
                    gap = payload.get('gross_gap_vs_reference')
                    if gap is None:
                        evidence.stats['axis_cash_gap_field_missing'] += 1
                    elif abs(float(gap)) > WEIGHT_ATOL:
                        evidence.drift('axis_cash_gap_'+path_contract['axis'],np.arange(K) == j,ids,day,np.full(K,float(gap)))
            fusion_rows = [j for j,s in enumerate(ids) if strategies.get(str(s),{}).get('target_fusion','none') != 'none']
            expert_path = batch/'decision_coverage'/f'{day:%Y%m%d}_experts.npz'
            if fusion_rows:
                evidence.bad('target_expert_matrix_missing',not expert_path.exists())
                if expert_path.exists():
                    with np.load(expert_path,allow_pickle=False) as z:
                        evidence.bad('target_expert_matrix_shape',z['targets'].shape != (len(fusion_rows),13,N))
                        evidence.bad('target_expert_row_links',z['rowindices'].tolist() != fusion_rows)
                        evidence.bad('target_expert_member_names',z['expert_names'].tolist() != POINT)
                        evidence.bad('target_expert_nonfinite',~np.isfinite(z['targets']))
            evidence.stats['signal_dates'] += 1
            evidence.stats['signal_account_rows'] += K
            pending = target.copy()
        else:
            evidence.bad('unexpected_signal_raw_rows',len(raw_rows) != 0)
            evidence.bad('unexpected_signal_context_rows',len(signal_ctx) != 0)
            evidence.bad('unexpected_signal_order_rows',len(target) != 0)
            pending = pd.DataFrame()
        evidence.stats['valuation_account_rows'] += K
        evidence.stats['fills'] += len(trades)
        evidence.stats['positions_records'] += len(positions)
        last_nav,last_cert = nav,certified
    for name,reader in readers.items():
        evidence.bad('table_row_count_'+name,counts[name] != metadata.get('table_rows',{}).get(name,0))
        evidence.bad('table_part_count_'+name,len(reader.files) != metadata.get('table_parts',{}).get(name,0))
    receipt = json.loads((batch/'POLICY_RECEIPT.json').read_text(encoding='utf-8'))
    evidence.bad('policy_solver_count_matches_raw_rows',dict(statuses) != receipt.get('solver_counts'))
    evidence.bad('new_fits_in_frozen_replay',receipt.get('fit_calls') != 0 or complete.get('new_fit_calls') != 0)
    total = sum(statuses.values())
    exact = sum(v for k,v in statuses.items() if k in ['SOLVED_TOLERANCE','SOLVED_CASH_CERTIFICATE'])
    result = {'year':year,'batch':batch.name,'accounts':K,'tickers':N,'calendar_days':len(calendar),
              'scope':complete.get('scope'),'formal_full_pool':complete.get('formal_full_pool'),
              'verification_seconds':round(time.time()-started,3), 'solver_status_counts':dict(statuses),
              'solver_exact_status_fraction':exact/total if total else None,
              'solver_diagnostic_ranges':{status:{**v,'mean_residual':v['residual_sum']/v['rows']} for status,v in solver_diagnostics.items()},
              'target_expert_solver_status_counts':dict(expert_statuses), 'solver_failures_preserved':receipt.get('failures',[]),
              'source_hashes':sources.hashes, 'metadata_sha256':sha(batch/'metadata.json'),
              'source_engine_imported':False,'source_policy_imported':False,**evidence.result()}
    del readers
    gc.collect()
    return result,evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--year',type=int,choices=[2025,2026],action='append')
    parser.add_argument('--batch',type=int,action='append')
    parser.add_argument('--skip-source-coverage',action='store_true',help='ledger-only rerun; report explicitly omits 75-source proof')
    parser.add_argument('--no-cache',action='store_true',help='Ignore PASS cache; still preserve any old evidence')
    args = parser.parse_args()
    root = args.root.resolve()
    registry = json.loads((root/'REGISTRY.json').read_text(encoding='utf-8'))
    years = args.year or [y for y in [2025,2026] if (root/f'results/{y}').exists()]
    started=time.time()
    report = {'verification_version':'INDEPENDENT_CASH_UNITS_SOURCE_MARKS_V1','generated_at_utc':pd.Timestamp.now(tz='UTC').isoformat(),
              'verification_code_sha256':sha(Path(__file__)),'engine_or_policy_imported':False,'learning_or_parameter_updates':0,
              'source_coverage_requested':not args.skip_source_coverage,'years':{},'all_completed_batches_pass':True,
              'incremental_cache_enabled':not args.no_cache,'cache_policy':CACHE_VERSION,
              'formal_full_pool_certified':False,
              'limits':['Accounts use saved affine price-index units; this does not certify physical shareholder total return.',
                        'Certification covers actual saved source panels; UNKNOWN formal candidates remain a separate data block.',
                        'Buy/sell axes can change cash under binding constraints; signed gaps are recorded rather than erased.',
                        'Approximate, failed, exact-cash and target-fusion solver statuses remain separate.'],
              'conformance_evidence':{'file':'test_batch_engine.py','sha256':sha(root/'test_batch_engine.py'),
                                      'existing_test_functions':(root/'test_batch_engine.py').read_text(encoding='utf-8').count('\ndef test_'),
                                      'rerun_by_independent_verifier':False}}
    conformance_path=root/'audits/BATCH_ENGINE_CONFORMANCE.json'
    if conformance_path.exists():
        conformance=json.loads(conformance_path.read_text(encoding='utf-8'))
        report['conformance_evidence']['recorded_tests']=conformance.get('conformance',{})
        report['conformance_evidence']['receipt_sha256']=sha(conformance_path)
    failure_samples,drift_samples=[],[]
    for year in years:
        batches=sorted((root/f'results/{year}').glob('batch_*'))
        if args.batch is not None:
            batches=[p for p in batches if int(p.name.rsplit('_',1)[1]) in args.batch]
        complete=[p for p in batches if (p/'COMPLETE.json').exists()]
        pending=[p.name for p in batches if not (p/'COMPLETE.json').exists() and not (p/'FAILED.json').exists()]
        failed=[{'batch':p.name,**json.loads((p/'FAILED.json').read_text(encoding='utf-8'))} for p in batches if (p/'FAILED.json').exists() and not (p/'COMPLETE.json').exists()]
        year_report={'completed_batches':[],'pending_batches':pending,'failed_replays':failed,
                     'registered_accounts':len(registry['strategies']),'verified_accounts':0}
        report['years'][str(year)]=year_report
        if failed:
            report['all_completed_batches_pass']=False
        if not complete:
            year_report['status']='PENDING_NO_COMPLETE_BATCH';continue
        if year == 2026:
            freeze_path=root/'FREEZE.json'
            if not freeze_path.exists():
                year_report['status']='BLOCKED_MISSING_FULL_FREEZE'
                report['all_completed_batches_pass']=False;continue
            freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
            if freeze.get('status') != 'FROZEN_ALL_LEARNING_PRE2026':
                year_report['status']='BLOCKED_INVALID_FULL_FREEZE'
                report['all_completed_batches_pass']=False;continue
        sources=Sources(root,year)
        sources_sha256=shared_bindings(root,sources,registry)
        if not args.skip_source_coverage:
            ev=Evidence(year,'PREDICTION_SOURCE_KEYS')
            year_report['prediction_source_coverage']=source_prediction_coverage(root,sources,registry,ev)
            failure_samples.extend(ev.samples)
            if ev.counts:report['all_completed_batches_pass']=False
        for batch in complete:
            print('VERIFY',year,batch.name,flush=True)
            try:
                cached,cache_reason=(None,'DISABLED') if args.no_cache else load_pass_cache(root,batch,year,sources_sha256,report['verification_code_sha256'])
                if cached is not None:
                    result,ev=cached
                else:
                    before_hashes=ledger_bindings(batch)
                    result,ev=verify_batch(root,batch,year,sources,registry)
                    result['cache_reused']=False
                    result['cache_reason']=cache_reason
                    if result['status']=='PASS':
                        result['cache_file']=save_pass_cache(root,batch,year,result,ev,sources_sha256,report['verification_code_sha256'],before_hashes)
                year_report['completed_batches'].append(result)
                year_report['verified_accounts']+=result['accounts']
                failure_samples.extend(ev.samples);drift_samples.extend(ev.drift_samples)
                if ev.counts:report['all_completed_batches_pass']=False
                print(result['status'],result['failure_count'],result['verification_seconds'],'cached',result.get('cache_reused',False),flush=True)
            except Exception as exc:
                import traceback
                year_report['completed_batches'].append({'batch':batch.name,'status':'VERIFY_EXCEPTION','reason':str(exc),'traceback':traceback.format_exc()})
                failure_samples.append({'year':year,'batch':batch.name,'check':'verification_exception','detail':str(exc)})
                report['all_completed_batches_pass']=False
        verified={s for batch in complete for s in json.loads((batch/'metadata.json').read_text(encoding='utf-8'))['strategy_ids']}
        expected={p['strategy'] for p in registry['strategies']}
        year_report['missing_registered_strategies']=sorted(expected-verified)
        year_report['unexpected_strategies']=sorted(verified-expected)
        year_report['all_registered_account_paths_complete']=not (expected-verified) and not (verified-expected) and year_report['verified_accounts']==len(expected)
        year_report['status']='PASS_COMPLETE' if year_report['all_registered_account_paths_complete'] and all(r['status']=='PASS' for r in year_report['completed_batches']) else 'PARTIAL_OR_FAILED'
        del sources
        gc.collect()
    report['seconds']=round(time.time()-started,3)
    report['coverage_complete']=bool(years) and all(y.get('all_registered_account_paths_complete',False) for y in report['years'].values())
    report['status']='PASS_COMPLETE' if report['coverage_complete'] and report['all_completed_batches_pass'] and not args.skip_source_coverage else ('PASS_PARTIAL' if report['all_completed_batches_pass'] else 'FAIL')
    report['failure_csv_samples']=len(failure_samples)
    report['drift_csv_samples']=len(drift_samples)
    (root/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    cols=['year','batch','check','strategy_id','ticker','date','signal_date','execution_date','order_id','array_index','detail']
    pd.DataFrame(failure_samples).reindex(columns=cols).to_csv(root/'INDEPENDENT_VERIFICATION_FAILURES.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(drift_samples).reindex(columns=['year','batch','kind','strategy_id','date','value']).to_csv(root/'INDEPENDENT_VERIFICATION_DRIFT.csv',index=False,encoding='utf-8-sig')
    print(report['status'],'coverage_complete',report['coverage_complete'],'seconds',report['seconds'],flush=True)
    return 0 if report['all_completed_batches_pass'] else 1


if __name__=='__main__':
    raise SystemExit(main())
