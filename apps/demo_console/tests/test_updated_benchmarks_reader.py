"""Synthetic contracts for hash-bound, full-calendar RAW ETF references."""
from dataclasses import replace
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import benchmarks_reader as reader

DATES = ('2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05')


@pytest.fixture
def updated_config(artifact_dir):
    def create(mutate_rows=None, mutate_manifest=None):
        artifacts = []
        for symbol in ('QQQ', 'SPY'):
            rows = [dict(date=day, ticker=symbol, open=price,
                         source='MOOMOO_OPEND' if i < 2 else 'MASSIVE_GROUPED', adjustment='raw')
                    for i, (day, price) in enumerate(zip(DATES, (100., 110., 99., 101.)))]
            if symbol == 'QQQ' and mutate_rows:
                mutate_rows(rows)
            path = artifact_dir / f'{symbol}.parquet'
            pq.write_table(pa.Table.from_pylist(rows), path)
            artifacts.append(dict(symbol=symbol, path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), start_date=DATES[0],
                end_date=DATES[-1], row_count=len(rows),
                source_refs=[dict(path='X:/NEVER_OPEN/source.csv', sha256='a'*64)]))
        manifest = dict(schema_version=1, provider='MOOMOO_OPEND_AND_MASSIVE', adjustment='RAW',
                        basis='OPEN_TO_OPEN_PRICE_RETURN', artifacts=artifacts)
        if mutate_manifest:
            mutate_manifest(manifest)
        path = artifact_dir / 'updated_manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        return reader.UpdatedBenchmarkConfig(path, hashlib.sha256(path.read_bytes()).hexdigest())
    return create


def test_arbitrary_sample_window_uses_shared_math_and_explicit_prior_open(updated_config):
    config = updated_config()
    history = reader.read_updated_benchmarks(DATES[2:], DATES[1], config=config)
    assert history.error is None and len(history.series) == 2
    for series in history.series:
        assert series.error is None
        assert series.adjustment == 'RAW' and series.basis == 'OPEN_TO_OPEN_PRICE_RETURN'
        assert series.provider == 'MOOMOO_OPEND_AND_MASSIVE'
        assert series.points[0].date == '2026-01-02'
        assert series.points[0].equity == pytest.approx(.9)
        assert series.total_return == pytest.approx(101/110-1)
        assert series.max_drawdown == pytest.approx(-.1)
    standalone = reader.read_updated_benchmarks(DATES[2:], config=config).series[0]
    assert standalone.points[0].equity == 1 and standalone.points[0].daily_return == 0
    assert standalone.total_return == pytest.approx(101/99-1)


@pytest.mark.parametrize('mutation', [
    lambda rows: rows[1].update(open=float('nan')),
    lambda rows: rows[1].update(open=0.),
    lambda rows: rows[1].update(ticker='OTHER'),
    lambda rows: rows[1].update(source='UNKNOWN'),
    lambda rows: rows[1].update(adjustment='qfq'),
    lambda rows: rows[1].update(date=DATES[0]),
    lambda rows: rows.reverse(),
])
def test_invalid_projection_fails_independently_without_changing_other_etf(updated_config, mutation):
    history = reader.read_updated_benchmarks(DATES, config=updated_config(mutate_rows=mutation))
    assert history.error is None
    assert history.series[0].error and not history.series[0].points
    assert history.series[1].error is None and len(history.series[1].points) == 4


@pytest.mark.parametrize('dates,baseline', [
    (DATES[::2], None), (DATES[2:], DATES[0]), (('2026-01-06',), None),
])
def test_missing_or_noncontiguous_dates_do_not_shorten_the_requested_window(updated_config, dates, baseline):
    history = reader.read_updated_benchmarks(dates, baseline, config=updated_config())
    assert history.error is None
    assert history.start_date == dates[0] and history.end_date == dates[-1]
    assert all(series.error and not series.points for series in history.series)


def test_manifest_and_projection_hashes_are_enforced(updated_config):
    config = updated_config()
    assert reader.read_updated_benchmarks(DATES, config=replace(config, manifest_sha256='f'*64)).error
    manifest = json.loads(config.manifest_path.read_text())
    from pathlib import Path
    with Path(manifest['artifacts'][0]['path']).open('ab') as handle:
        handle.write(b'tampered')
    history = reader.read_updated_benchmarks(DATES, config=config)
    assert history.series[0].error and history.series[1].error is None


@pytest.mark.parametrize('mutate', [
    lambda m: m.update(adjustment='QFQ'),
    lambda m: m.update(provider='MASSIVE'),
    lambda m: m.update(basis='TOTAL_RETURN'),
    lambda m: m['artifacts'][0].update(source_refs=[]),
    lambda m: m['artifacts'][0].update(row_count=100),
])
def test_source_contract_cannot_silently_change(updated_config, mutate):
    history = reader.read_updated_benchmarks(DATES, config=updated_config(mutate_manifest=mutate))
    assert history.error or history.series[0].error
