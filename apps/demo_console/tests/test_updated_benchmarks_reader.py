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
    def create(mutate_rows=None, mutate_manifest=None, mutate_all_rows=None):
        artifacts = []
        for symbol in ('QQQ', 'SPY'):
            rows = [dict(date=day, ticker=symbol, open=price,
                         source='MOOMOO_OPEND' if i < 2 else 'MASSIVE_GROUPED', adjustment='raw')
                    for i, (day, price) in enumerate(zip(DATES, (100., 110., 99., 101.)))]
            if mutate_all_rows:
                mutate_all_rows(rows)
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


def fallback_manifest(manifest):
    from scripts.storage.refresh_demo_benchmarks import CUTOVER, FALLBACK_POLICY, ETF_IDENTITIES
    manifest.update(fixed_source_cutover=CUTOVER, end_date=DATES[-1])
    source = {"path": "X:/NEVER_OPEN/original_raw.csv", "sha256": "a" * 64}
    proofs = {symbol: {**identity, "source": "MOOMOO_OPEND", "adjustment": "raw", "comparison": "EXACT_FLOAT_EQUALITY",
        "overlap_days": 5, "exact_equal_count": 5, "latest_five_dates": ["2025-12-26", "2025-12-29", *DATES[:3]],
        "all_overlap_exact": True, "source_refs": [source]} for symbol, identity in ETF_IDENTITIES.items()}
    manifest["source_fallbacks"] = [{"schema": FALLBACK_POLICY, "dates": [DATES[-1]], "previous_end_date": DATES[-2],
        "previous_manifest": source, "massive_failures": [{"date": DATES[-1], "status": "FAILED", "error": "HTTP_403", "reference": source, "origin_reference": source}],
        "qualifications": proofs}]


def fallback_rows(rows):
    for row in rows:
        row['source'] = 'MASSIVE_GROUPED'
    rows[-1]['source'] = 'MOOMOO_OPEND'


def test_explicit_bound_source_fallback_uses_original_return_math(updated_config):
    config = updated_config(mutate_all_rows=fallback_rows, mutate_manifest=fallback_manifest)
    history = reader.read_updated_benchmarks(DATES, config=config)
    assert not history.error and all(not series.error and len(series.points) == 4 for series in history.series)
    assert history.series[0].total_return == pytest.approx(.01)


@pytest.mark.parametrize('problem', ['unknown_policy', 'no_qualifications', 'false_exact', 'wrong_cusip', 'unknown_currency', 'not_failed', 'duplicate_dates', 'unbound_ref', 'silent_source'])
def test_fallback_protocol_or_silent_source_mutation_is_rejected(updated_config, problem):
    def mutation(manifest):
        fallback_manifest(manifest)
        record = manifest['source_fallbacks'][0]
        if problem == 'unknown_policy': record['schema'] = 'UNREVIEWED'
        elif problem == 'no_qualifications': record['qualifications'] = {}
        elif problem == 'false_exact': record['qualifications']['SPY']['all_overlap_exact'] = False
        elif problem == 'wrong_cusip': record['qualifications']['SPY']['security_id'] = '000000000'
        elif problem == 'unknown_currency': record['qualifications']['QQQ']['currency'] = 'HKD'
        elif problem == 'not_failed': record['massive_failures'][0]['status'] = 'SUCCESS'
        elif problem == 'duplicate_dates': record['dates'] = [DATES[-1], DATES[-1]]
        elif problem == 'unbound_ref': record['previous_manifest']['sha256'] = 'NOT_A_HASH'
        elif problem == 'silent_source': manifest['source_fallbacks'] = []
    history = reader.read_updated_benchmarks(DATES, config=updated_config(mutate_all_rows=fallback_rows, mutate_manifest=mutation))
    assert history.error or all(series.error and not series.points for series in history.series)
