"""PDS parser rejects silent coercion, regime ambiguity and truncated releases."""
from dataclasses import dataclass
from decimal import Decimal
import json
from types import SimpleNamespace
import urllib.error

import pytest

from scripts.storage import refresh_nyfed_primary_dealer as m


def encoded(key, rows):
    return json.dumps({'pd':{key:rows}}).encode()


def observation(key=None, day='2024-07-03', value='100'):
    return {'asofdate':day,'keyid':key or m.POSITIONS[0],'value':value}


@pytest.fixture
def metadata():
    definitions=[{'seriesbreak':'SBN2024','keyid':key,'description':'Current '+key} for key in m.SERIES]
    breaks=[{'seriesbreak':'SBN2022','label':'Prior','startdate':'2022-01-05','enddate':'2024-07-02'},
            {'seriesbreak':'SBN2024','label':'Current','startdate':'2024-07-03','enddate':'9999-12-31'}]
    dates=[{'asof':'2024-06-26','seriesbreak':'SBN2022'}, {'asof':'2024-07-03','seriesbreak':'SBN2024'}]
    return definitions,breaks,dates


def meta_parse(metadata):
    return m.parse_metadata(*(encoded(k,v) for k,v in zip(('timeseries','seriesbreaks','asofdates'),metadata)),
                            '2026-09-14')


def parse(rows, expected=None):
    return m.parse_history(encoded('timeseries',rows),expected or [m.POSITIONS[0]],
        {'2024-06-26':'SBN2022','2024-07-03':'SBN2024'},'2026-09-14')


def test_net_position_exact_integer_and_raw_marker():
    rows=parse([observation(day='2024-06-26',value='-9007199254740993'),observation(value='*')])
    assert rows[0]['value']==Decimal('-9007199254740993')
    assert rows[0]['seriesbreak']=='SBN2022'
    assert rows[1]['value'] is None and rows[1]['provider_value_text']=='*'
    assert rows[1]['value_status']=='PROVIDER_ASTERISK_MEANING_UNVERIFIED'
    assert json.loads(rows[0]['source_record_json'])['value']=='-9007199254740993'
    assert [r['source_row'] for r in rows]==[1,2]
    assert all(r['unit']=='USD_millions' for r in rows)


@pytest.mark.parametrize('value',['NaN','nan','Infinity','NA','','1.5','1e3',True,None,1,'9'*39])
def test_reject_unverified_numeric_or_missing_coercions(value):
    with pytest.raises(ValueError): parse([observation(value=value)])


@pytest.mark.parametrize('key',[m.FINANCING[0],m.FAILS[0]])
def test_financing_and_fails_cannot_be_negative(key):
    with pytest.raises(ValueError,match='NEGATIVE'):
        parse([observation(key,value='-1')],[key])


def test_duplicate_field_and_observation_are_rejected():
    with pytest.raises(ValueError,match='DUPLICATE_JSON_KEY'):
        m.records(b'{"pd":{"timeseries":[{"keyid":"a","keyid":"b"}]}}','timeseries')
    with pytest.raises(ValueError,match='DUPLICATE_SERIES_DATE'):
        parse([observation(),observation()])


def test_unexpected_field_requires_explicit_review():
    row=observation();row['revision']='R'
    with pytest.raises(ValueError,match='SCHEMA'): parse([row])


def test_truncated_series_set_and_unlisted_dates_fail():
    with pytest.raises(ValueError,match='REQUESTED_SERIES_MISSING'):
        parse([observation()],[m.POSITIONS[0],m.POSITIONS[1]])
    with pytest.raises(ValueError,match='SERIES_OR_DATE'):
        parse([observation(day='2024-07-04')])


def test_source_breaks_must_match_dates_and_not_overlap(metadata):
    regimes,dates,definitions=meta_parse(metadata)
    assert dates['2024-06-26']=='SBN2022' and dates['2024-07-03']=='SBN2024'
    assert len(definitions)==28 and len(regimes)==2
    metadata[1][0]['enddate']='2024-07-03'
    with pytest.raises(ValueError,match='OVERLAPPING'):meta_parse(metadata)


def test_wrong_date_regime_is_rejected(metadata):
    metadata[2][0]['seriesbreak']='SBN2024'
    with pytest.raises(ValueError,match='DATE_OUTSIDE'):meta_parse(metadata)


def test_unreviewed_definition_regime_is_rejected(metadata):
    metadata[0][0]['seriesbreak']='SBN2030'
    with pytest.raises(ValueError,match='DEFINITION_REGIME'):meta_parse(metadata)


@pytest.fixture
def complete_release():
    history=[observation(k,d) for k in m.SERIES for d in ['2024-06-26','2024-07-03']]
    parsed=parse(history,m.SERIES)
    latest=[observation(k) for k in m.SERIES]
    return parsed,latest,{'2024-06-26':'SBN2022','2024-07-03':'SBN2024'}


def test_latest_exact_all_series_and_key_order_independence(complete_release):
    rows,latest,dates=complete_release
    latest=[dict(reversed(list(r.items()))) for r in latest]
    assert len(m.validate_latest(rows,encoded('timeseries',latest),dates,'2026-09-14'))==28


@pytest.mark.parametrize('change',['value','date','missing'])
def test_latest_revision_staleness_and_truncation_fail(complete_release,change):
    rows,latest,dates=complete_release
    if change=='value':latest[0]['value']='*'
    elif change=='date':latest[0]['asofdate']='2024-06-26'
    else:latest.pop()
    with pytest.raises(ValueError):m.validate_latest(rows,encoded('timeseries',latest),dates,'2026-09-14')


def test_internal_date_missing_does_not_silently_shorten(complete_release):
    rows,latest,dates=complete_release
    for row in list(rows):
        if row['series_id']==m.SERIES[0]:
            prior=dict(row,date='2024-06-19');rows.append(prior);break
    rows=[r for r in rows if not(r['series_id']==m.SERIES[0] and r['date']=='2024-06-26')]
    with pytest.raises(ValueError,match='INTERNAL_DATE_GAPS'):
        m.validate_latest(rows,encoded('timeseries',latest),dates,'2026-09-14')


def test_network_failure_stops_persistently_without_retry(tmp_path,monkeypatch):
    @dataclass
    class Failed:
        status:str='FAILED'
        error:str='HTTP 403'
    archive=SimpleNamespace()
    calls=[]
    def acquire(url,*args):
        assert args[-2]==0
        calls.append(url)
        return Failed()
    archive.acquire_url=acquire
    monkeypatch.setattr(m.common,'archive_module',lambda _:archive)
    monkeypatch.setattr(m,'check_budget',lambda *a:0)
    paths=SimpleNamespace(results_root=tmp_path/'results',cache_root=tmp_path/'cache',repo_root=tmp_path,
                          data_root=tmp_path/'data')
    with pytest.raises(RuntimeError,match='403'):m.acquire(paths,'synthetic','2026-09-14')
    with pytest.raises(ValueError,match='PRIOR_SOURCE_FAILURE'):m.acquire(paths,'synthetic','2026-09-14')
    assert len(calls)==1
