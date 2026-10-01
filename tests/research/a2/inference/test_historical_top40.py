from pathlib import Path
from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference.historical_top40 import digest, ranked_predictions
from scripts.research.a2.inference import historical_top40 as runner


class ScoreModel:
    def predict(self, values):
        return values[:, 0]


def sample(tmp_path):
    model = tmp_path / 'model.bin'
    model.write_bytes(b'fixed synthetic model')
    models = {'artifacts': {'2023': {'path': str(model), 'sha256': digest(model), 'labelmax': '2022-12-30'}}}
    schedule = pd.DataFrame([
        {'snapshot_id': 'old', 'quarter': '2022Q3', 'effective_date': '2022-11-22', 'institution_count': 24,
         'universe_id': 'old-pool', 'universe_member_count': 2, 'mapped_count': 2},
        {'snapshot_id': 'new', 'quarter': '2022Q4', 'effective_date': '2023-02-22', 'institution_count': 24,
         'universe_id': 'new-pool', 'universe_member_count': 2, 'mapped_count': 2},
    ])
    members = pd.DataFrame([
        {'snapshot_id': 'old', 'security_id': '1', 'ticker': 'OLD'},
        {'snapshot_id': 'old', 'security_id': '2', 'ticker': 'KEEP'},
        {'snapshot_id': 'new', 'security_id': '3', 'ticker': 'NEW'},
        {'snapshot_id': 'new', 'security_id': '2', 'ticker': 'KEEP'},
    ])
    ledger = pd.DataFrame([{'target_date': '2023-02-21', 'snapshot_id': 'old'},
                           {'target_date': '2023-02-22', 'snapshot_id': 'new'}])
    features = pd.DataFrame([{'trade_date': day, 'ticker': ticker, 'signal': score}
        for day in ledger.target_date for ticker, score in [('OLD', 1.), ('KEEP', 2.), ('NEW', 100.)]])
    return features, schedule, members, ledger, models


def run(data):
    return ranked_predictions(*data, ['signal'], model_loader=lambda _: ScoreModel())


def test_pool_changes_only_on_actual_effective_day(tmp_path):
    ranked, coverage = run(sample(tmp_path))
    assert ranked.loc[ranked.target_date.eq('2023-02-21'), 'ticker'].tolist() == ['KEEP', 'OLD']
    assert ranked.loc[ranked.target_date.eq('2023-02-22'), 'ticker'].tolist() == ['NEW', 'KEEP']
    assert set(coverage.status) == {'PARTIAL'}  # Fewer than 40, never invent rows.


def test_future_13f_activation_fails_closed(tmp_path):
    data = sample(tmp_path)
    data[3].loc[0, 'snapshot_id'] = 'new'
    with pytest.raises(ValueError, match='FUTURE_13F_DISCLOSURE_USED'):
        run(data)


def test_same_reporting_quarter_is_not_previous_disclosed_pool(tmp_path):
    data = sample(tmp_path)
    data[1].loc[0, 'quarter'] = '2023Q1'
    with pytest.raises(ValueError, match='SAME_OR_FUTURE_REPORTING_QUARTER_USED'):
        run(data)


def test_current_model_cannot_be_used_for_earlier_year(tmp_path):
    data = sample(tmp_path)
    data[4]['artifacts']['2023']['labelmax'] = '2025-12-31'
    with pytest.raises(ValueError, match='MODEL_LABEL_CUTOFF_OVERLAPS'):
        run(data)


def test_missing_features_are_excluded_without_narrowing_declared_pool(tmp_path):
    data = sample(tmp_path)
    data[0].loc[data[0].ticker.eq('KEEP'), 'signal'] = np.nan
    ranked, coverage = run(data)
    assert ranked.ticker.tolist() == ['OLD', 'NEW']
    assert coverage.eligible_count.tolist() == [1, 1]
    assert coverage.universe_member_count.tolist() == [2, 2]
    assert coverage.excluded_count.tolist() == [1, 1]


def test_ties_follow_original_ticker_tiebreak(tmp_path):
    data = sample(tmp_path)
    data[0].loc[:, 'signal'] = 1.
    ranked, _ = run(data)
    assert ranked.loc[ranked.target_date.eq('2023-02-22'), 'ticker'].tolist() == ['KEEP', 'NEW']


def test_no_disclosed_pool_has_explicit_waiting_day(tmp_path):
    data = sample(tmp_path)
    data[3].loc[0, 'snapshot_id'] = None
    ranked, coverage = run(data)
    assert not ranked.target_date.eq('2023-02-21').any()
    assert coverage.iloc[0].status == 'WAITING_DATA'
    assert coverage.iloc[0].reason == 'NO_DISCLOSED_EFFECTIVE_POOL'


def test_duplicate_member_or_changed_binary_is_rejected(tmp_path):
    data = sample(tmp_path)
    data[2].loc[1, 'ticker'] = 'OLD'
    with pytest.raises(ValueError, match='SIMULTANEOUS_SECURITY_OR_TICKER_COLLISION'):
        run(data)
    data = sample(tmp_path)
    Path(data[4]['artifacts']['2023']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='MODEL_BINARY_HASH_CHANGED'):
        run(data)


@pytest.fixture
def calendar_fixture(tmp_path, monkeypatch):
    paths = SimpleNamespace(data_root=tmp_path/'data', repo_root=tmp_path/'repo', daily_root=tmp_path/'daily')
    source = paths.data_root/'moomoo/source/prices_qfq/year=2022/prices.parquet'
    source.parent.mkdir(parents=True)
    pd.DataFrame({'ticker':['QQQ','SPY'], 'trade_date':pd.to_datetime(['2022-12-30','2022-12-29']),
                  'close':[1.,2.]}).to_parquet(source,index=False)
    rules = tmp_path/'rules.py'
    rules.write_text('# fixed synthetic calendar rules',encoding='utf-8')
    sessions = ['2023-01-03','2023-01-04']
    generated_sha = hashlib.sha256(json.dumps(sessions,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    contract = tmp_path/'calendar.json'
    contract.write_text(json.dumps({'rules_source':str(rules),'rules_source_sha256':digest(rules),
        'sessions_sha256':generated_sha,'session_count':2,'start_date':sessions[0],'end_date':sessions[-1]}),encoding='utf-8')
    binding = {'readiness_sources':{'trading_calendar':{'path':str(contract),'sha256':digest(contract)}}}
    current = {'sessions':sessions,'calendar_sha256':digest(contract),'calendar_id':'synthetic-fixed',
               'target_date':sessions[-1],'as_of_utc':'2023-01-05T01:00:00+00:00'}
    monkeypatch.setattr(runner,'QQQ_CALENDAR_HASHES',{2022:digest(source)})
    monkeypatch.setattr(runner,'load_frozen_binding',lambda _:binding)
    monkeypatch.setattr(runner,'latest_completed_session',lambda _:current)
    return SimpleNamespace(paths=paths,source=source,rules=rules,contract=contract,current=current)


def test_calendar_lineage_binds_sources_and_stays_stable_across_observation_times(calendar_fixture):
    value = calendar_fixture
    days, calendar = runner.load_sessions(value.paths)
    assert days == ['2022-12-30','2023-01-03','2023-01-04']  # QQQ dates only.
    lineage = calendar['lineage']
    assert lineage['historical_qqq'][0]['sha256'] == digest(value.source)
    assert lineage['exchange_calendar']['sha256'] == digest(value.contract)
    assert lineage['exchange_calendar']['rules_source']['sha256'] == digest(value.rules)
    assert lineage['merged_sessions_sha256'] == hashlib.sha256('\n'.join(days).encode()).hexdigest()
    value.current['as_of_utc'] = '2023-01-05T02:00:00+00:00'
    assert runner.load_sessions(value.paths)[1]['lineage'] == lineage
    assert 'as_of_utc' not in json.dumps(lineage)


def test_changed_calendar_rules_are_rejected(calendar_fixture):
    calendar_fixture.rules.write_text('# changed',encoding='utf-8')
    with pytest.raises(ValueError,match='BOUND_CALENDAR_RULES_CHANGED'):
        runner.load_sessions(calendar_fixture.paths)


def test_plan_contract_retains_calendar_lineage_and_rejects_unbound_dates(calendar_fixture,tmp_path,monkeypatch):
    from scripts.research.a2.inference import historical_top40_models, historical_top40_universe
    value = calendar_fixture
    days, calendar = runner.load_sessions(value.paths)
    report, universe = tmp_path/'report.json', tmp_path/'universe.json'
    universe.write_text('{}',encoding='utf-8')
    report.write_text(json.dumps({'status':'READY','data_date':'2023-01-04',
        'universe':{'report_path':str(universe)}}),encoding='utf-8')
    monkeypatch.setattr(runner,'single_update',lambda _:nullcontext())
    monkeypatch.setattr(historical_top40_universe,'build_universe_schedule',lambda *a,**k:{
        'ledger':pd.DataFrame({'target_date':['2023-01-03','2023-01-04']})})
    monkeypatch.setattr(historical_top40_models,'build_models',lambda *a,**k:{'status':'PLANNED'})
    options = {'start':'2023-01-03','end':'2023-01-04','source_report':report,'execute':False}
    result = runner.run_rebuild(value.paths,sessions=days,calendar_lineage=calendar['lineage'],**options)
    assert result['contract']['calendar_lineage'] == calendar['lineage']
    assert result['status'] == 'PLANNED'
    assert not value.paths.daily_root.exists()
    with pytest.raises(ValueError,match='SUPPLIED_SESSIONS_DIFFER'):
        runner.run_rebuild(value.paths,sessions=days+['2023-01-07'],**options)
    with pytest.raises(ValueError,match='SUPPLIED_CALENDAR_LINEAGE_MISMATCH'):
        runner.run_rebuild(value.paths,sessions=days,calendar_lineage={},**options)
