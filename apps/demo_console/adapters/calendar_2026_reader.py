"""Read the explicitly authorized calendar replay, separately from the June run.

Reuse the recorded reader's strict date/footer/hash and arithmetic validation.
This adapter never loads a model, reads its research inputs or launches a run.
"""
from dataclasses import dataclass

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date
from apps.demo_console.adapters.recorded_2026_reader import (
    Recorded2026Config, Recorded2026History, _bound_config, _equal, _json,
    _number, _points, _read_daily, _series, _subperiods,
)
from apps.demo_console.adapters.benchmarks_reader import (
    BenchmarkHistory, BenchmarkPoint, BenchmarkSeries,
)
from apps.demo_console.config.demo_config import BASELINE_ID
from scripts.common.storage_paths import resolve

_STATUS = 'RECORDED_DESCRIPTIVE_REPLAY_WITH_COVERAGE_LIMITS'
_MODEL = '4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b'
_SOURCES = '21d246c614ca71ae713f49904066b43647e2f9d0b2d6deea0c39230a2a8f8f76'
_INPUTS = '4c979486b983108d41631f93244cbb2d991d730e6c707c23b7986a24f9d034f3'
_EXTRA = ('SPY_equity', 'SPY_daily_return', 'SPY_drawdown', 'SPY_open')


@dataclass(frozen=True)
class Calendar2026Coverage:
    date: str
    quarter: str
    candidates: int
    with_prices: int
    eligible: int


@dataclass(frozen=True)
class Calendar2026History(Recorded2026History):
    spy_points: tuple[BenchmarkPoint, ...] = ()
    coverage: tuple[Calendar2026Coverage, ...] = ()
    original_source_status: str | None = None
    model_sha256: str | None = None


def default_calendar_2026_config():
    root = resolve().backtest_root / 'research/a2/demo_2026_calendar_replay'
    return Recorded2026Config(root / 'summary.json',
        'fbc3185942d13cc3313b6cba898829503abf1393493ebe94c312a56bcfdbab5a',
        root / 'audit.json', 'aab73bdd7088a980a30dc6ea5729b51c73fc9523ec8509f59e6d7c5cbdc42904',
        root / 'daily.parquet', '7844b1d2e00ef08589aa3bc478bad83adf82ab1dc1d4ca86c4c67f2002359a5d',
        '2026-01-02', '2026-08-13', 154)


def _spy(rows, metrics):
    points = []
    previous, peak, first_price = 1.0, 1.0, None
    for index, row in enumerate(rows):
        equity = _number(row['SPY_equity'], 'SPY_equity') / 100
        change = _number(row['SPY_daily_return'], 'SPY_daily_return')
        drawdown = _number(row['SPY_drawdown'], 'SPY_drawdown')
        price = _number(row['SPY_open'], 'SPY_open')
        if equity <= 0 or price <= 0 or change <= -1 or not -1 < drawdown <= 0:
            raise ArtifactError('CALENDAR2026_INVALID_SPY')
        if index == 0:
            first_price = price
            _equal(equity, 1, 'CALENDAR2026_SPY_INITIAL')
        _equal(change, equity / previous - 1, 'CALENDAR2026_SPY_RETURN')
        _equal(equity, price / first_price, 'CALENDAR2026_SPY_PRICE')
        peak = max(peak, equity)
        _equal(drawdown, equity / peak - 1, 'CALENDAR2026_SPY_DRAWDOWN')
        points.append(BenchmarkPoint(iso_date(row['date']), price, change, equity, drawdown))
        previous = equity
    returns = [p.daily_return for p in points[1:]]
    for name, value in {
        'total_return': points[-1].equity - 1, 'final_equity': points[-1].equity * 100,
        'maximum_drawdown': min(p.drawdown for p in points),
        'worst_day': min(returns), 'best_day': max(returns),
        'positive_day_pct': sum(r > 0 for r in returns) / len(returns),
    }.items():
        _equal(_number(metrics.get(name), name), value, 'CALENDAR2026_SPY_SUMMARY')
    return tuple(points)


def _coverage(rows, points):
    result = []
    for row in rows:
        stamp = row['signal_date']
        # The producer serializes pandas midnight timestamps as ISO datetimes.
        # Accept exactly midnight, not arbitrary timestamp truncation.
        if isinstance(stamp, str) and len(stamp) == 19 and stamp[10:] == 'T00:00:00':
            stamp = stamp[:10]
        day = iso_date(stamp)
        counts = [row[key] for key in ('raw_13f_count', 'price_eligible_count', 'final_U_t_count')]
        if any(type(value) is not int for value in counts) or not 20 <= counts[2] <= counts[1] <= counts[0] <= 900:
            raise ArtifactError('CALENDAR2026_COVERAGE_COUNTS')
        quarter = '2025Q3' if day < '2026-02-25' else ('2025Q4' if day < '2026-05-22' else '2026Q1')
        if row['active_quarter'] != quarter:
            raise ArtifactError('CALENDAR2026_PIT_QUARTER')
        result.append(Calendar2026Coverage(day, row['active_quarter'], *counts))
    if tuple(row.date for row in result) != tuple(p.date for p in points):
        raise ArtifactError('CALENDAR2026_COVERAGE_DATES')
    return tuple(result)


def _audit(record, expected_points):
    zero_counts = ('model_fit_count', 'parameter_search_count', 'risk_overlay_count',
        'history_download_count', 'network_request_count', 'source_files_changed',
        'forward_contracts_changed', 'missing_price_event_count',
        'held_corporate_action_exception_count', 'pit_violation_count',
        'lookahead_violation_count', 'training_data_after_2025_12_31_count')
    if any(type(record.get(key)) is not int or record[key] != 0 for key in zero_counts):
        raise ArtifactError('CALENDAR2026_AUDIT_VIOLATION')
    if (record.get('headline_eligible') is not True
            or type(record.get('model_predict_count')) is not int or record['model_predict_count'] != 1
            or record.get('missing_price_events') != [] or record.get('held_corporate_action_exceptions') != []
            or record.get('failures') != [] or record.get('source_verification_before_and_after') != '46_RESOLVED_MATCHES'
            or record.get('model_artifact_sha256') != _MODEL
            or record.get('source_resolution_sha256') != _SOURCES
            or record.get('input_coverage_sha256') != _INPUTS):
        raise ArtifactError('CALENDAR2026_AUDIT_NOT_ACCEPTED')
    accounting = record.get('accounting_results', {})
    residual = _number(accounting.get('max_absolute_residual'), 'accounting_residual')
    if (accounting.get('status') != 'VERIFIED_ACCOUNTING_IDENTITIES' or not 0 <= residual <= 1e-9
            or set(accounting.get('models', {})) != {'A', 'A2'}):
        raise ArtifactError('CALENDAR2026_ACCOUNTING_FAILURE')
    for counts in accounting['models'].values():
        if (any(type(counts.get(key)) is not int or counts[key] < 0
                for key in ('daily_rows', 'position_rows', 'trade_rows'))
                or counts['daily_rows'] != expected_points):
            raise ArtifactError('CALENDAR2026_ACCOUNTING_COUNTS')


def read_calendar_2026(config=None):
    try:
        config = config or default_calendar_2026_config()
        _bound_config(config)
        rows = _read_daily(config, extra_columns=_EXTRA)
        summary = _json(config.summary_path, config.summary_sha256)
        audit = _json(config.audit_path, config.audit_sha256)
        if (summary.get('schema') != 'DEMO_2026_CALENDAR_REPLAY_V1'
                or summary.get('status') != _STATUS or summary.get('headline_eligible') is not True
                or summary.get('baseline_name') != BASELINE_ID or summary.get('model_sha256') != _MODEL
                or summary.get('cost_bps_round_trip') != 10 or summary.get('top_n') != 20
                or summary.get('research_acceptance') != 'NOT_REASSESSED'
                or summary.get('historical_identity_status_upgraded') is not False
                or summary.get('source_status') != 'FAIL_CLOSED_ANTI_BLOAT_HARD_GATE'
                or summary.get('requested_start_date') != '2026-01-01'):
            raise ArtifactError('CALENDAR2026_IDENTITY_OR_SCOPE')
        if (summary.get('start_date'), summary.get('end_date'), summary.get('point_count'),
                summary.get('return_observation_count')) != (
                config.start_date, config.end_date, config.expected_points, config.expected_points - 1):
            raise ArtifactError('CALENDAR2026_WINDOW')
        bindings = summary.get('artifact_sha256', {})
        if bindings.get('daily.parquet') != config.daily_sha256 or bindings.get('audit.json') != config.audit_sha256:
            raise ArtifactError('CALENDAR2026_ARTIFACT_BINDING')
        _audit(audit, config.expected_points)
        points = _points(rows, config)
        return Calendar2026History(
            points=points, series=_series(summary, points),
            subperiods=_subperiods(summary, points, config), start_date=config.start_date,
            end_date=config.end_date, source_status=summary['status'], classification='DESCRIPTIVE_ONLY',
            anti_bloat_status='NOT_REASSESSED', accounting_complete=False,
            return_observations=len(points)-1,
            source_refs=tuple((str(path), digest) for path, digest in (
                (config.summary_path, config.summary_sha256), (config.audit_path, config.audit_sha256),
                (config.daily_path, config.daily_sha256))),
            spy_points=_spy(rows, summary['metrics']['SPY']),
            coverage=_coverage(summary['coverage'], points),
            original_source_status=summary['source_status'], model_sha256=_MODEL,
        )
    except Exception as exc:
        return Calendar2026History(error='The calendar replay is unavailable. Its source, accounting or coverage could not be verified.',
                                    debug_error=f'{type(exc).__name__}: {exc}')


def calendar_market_window(history, window):
    """Rebase the verified SPY curve to the exact same interval as A/A2/QQQ."""
    if history.error or window.error or not window.points:
        return BenchmarkHistory(error='No recorded observations fall within the selected dates.')
    index = {point.date: point for point in history.spy_points}
    baseline = index[window.baseline_date].equity
    peak, points = 1.0, []
    for observation in window.points:
        point = index[observation.date]
        equity = point.equity / baseline
        peak = max(peak, equity)
        points.append(BenchmarkPoint(point.date, point.price, point.daily_return, equity, equity / peak - 1))
    series = BenchmarkSeries('SPY', 'SPY · S&P 500 ETF', points=tuple(points),
        total_return=points[-1].equity-1, max_drawdown=min(p.drawdown for p in points),
        source_refs=history.source_refs)
    return BenchmarkHistory((series,), window.start_date, window.end_date,
        None if window.baseline_is_archive_start else window.baseline_date)
