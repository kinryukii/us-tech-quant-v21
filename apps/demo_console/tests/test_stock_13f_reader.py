import importlib.util
import json
from pathlib import Path
import pandas as pd
import pytest

PATH = Path(__file__).parents[1] / 'adapters/stock_13f_reader.py'
SPEC = importlib.util.spec_from_file_location('stock_13f_test_subject', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def inputs():
    registry = pd.DataFrame([dict(manager_id='manager', manager_name='Institution', notable_person='Registered person',
        cik='123', active_from_quarter='2024Q4', active_to_quarter='')])
    rows = pd.DataFrame([dict(manager_id='manager', quarter='2025Q1', cusip='123456789',
        reported_value_usd=500., shares=10., put_call='', share_type='SH', accession_key='00012325000001')])
    filings = pd.DataFrame([dict(manager_id='manager', quarter='2025Q1', filed_date='2025-05-15',
        accession='000123-25-000001', source_url='https://www.sec.gov/filing')])
    return rows, registry, filings


def query(rows, registry, filings, **kwargs):
    return subject.summarize_holders(rows, registry, filings, cusip='123456789', quarter='2025Q1',
        as_of=kwargs.get('as_of', '2025-05-22'))


def test_exact_cusip_options_filter_and_registry_person():
    rows, registry, filings = inputs()
    rows = pd.concat([rows, rows.assign(cusip='987654321'), rows.assign(put_call='CALL')], ignore_index=True)
    result = query(rows, registry, filings)
    assert len(result) == 1
    assert result[0]['reported_value'] == 500 and result[0]['shares'] == 10
    assert result[0]['notable_person'] == 'Registered person'


def test_future_disclosure_is_not_visible_at_signal():
    assert query(*inputs(), as_of='2025-05-14') == []


def test_later_amendment_does_not_borrow_initial_filing_date():
    rows, registry, filings = inputs()
    rows['accession_key'] = '00012325000002'
    with pytest.raises(ValueError, match='ACCESSION'):
        query(rows, registry, filings)


def test_historical_missing_share_count_stays_unknown():
    rows, registry, filings = inputs()
    rows = rows.drop(columns='shares').assign(filing_date='2025-05-15')
    result = query(rows, registry, filings.iloc[:0])
    assert result[0]['shares'] is None and result[0]['reported_value'] == 500


def test_manager_cannot_appear_before_registered_start():
    rows, registry, filings = inputs()
    registry['active_from_quarter'] = '2025Q2'
    with pytest.raises(ValueError, match='REGISTERED_PERIOD'):
        query(rows, registry, filings)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.])
def test_invalid_rows_cannot_be_hidden_in_an_aggregate(bad):
    rows, registry, filings = inputs()
    rows = pd.concat([rows, rows.assign(reported_value_usd=bad)], ignore_index=True)
    with pytest.raises(ValueError, match='INVALID_HOLDING'):
        query(rows, registry, filings)


def test_historical_source_link_never_points_to_future_amendment():
    rows, registry, filings = inputs()
    rows['filing_date'] = '2025-05-15'
    filings = pd.concat([filings, filings.assign(filed_date='2025-05-25', accession='000123-25-000002',
        source_url='https://www.sec.gov/future')], ignore_index=True)
    assert query(rows, registry, filings)[0]['source_url'] == 'https://www.sec.gov/filing'


def test_amendments_are_filtered_before_replacing_old_holdings(tmp_path, monkeypatch):
    from scripts import daily_recommendation_universe as universe
    report = tmp_path / 'report.json'; report.write_text('{}')
    recovery = tmp_path / 'recovery.json'
    raw = tmp_path / 'raw.txt'; raw.write_text('synthetic')
    filings = [dict(manager_id='manager', manager_name='Institution', manager_weight=1., quarter='2025Q1',
        form=form, accession=accession, filed_date=day, accepted_at=day+'T12:00:00Z',
        source_url='https://www.sec.gov/'+accession, source_sha256=accession)
        for form, accession, day in [('13F-HR', 'initial', '2025-05-15'), ('13F-HR/A', 'amended', '2025-05-20')]]
    (tmp_path / 'filing_evidence.json').write_text(json.dumps({'filings': filings}))
    recovery.write_text(json.dumps({'raw_filings': [dict(url=r['source_url'], path=str(raw), sha256=r['source_sha256'])
        for r in filings[:1]], 'sources': {'xml_parser': {'path': str(raw), 'sha256': 'parser'}}}))
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'raw/request_receipts.json').write_text(json.dumps({'sources': [dict(status=200,
        url=filings[1]['source_url'], raw_path=str(raw), sha256=filings[1]['source_sha256'])]}))
    monkeypatch.setattr(subject, '_checked', lambda ref: Path(ref['path']))
    monkeypatch.setattr(subject, '_readonly_parser', lambda *args: None)
    def inspect(payload, filing, parser):
        return [dict(cusip='123456789', title_of_class='COMMON', put_call='', share_type='SH',
            value_usd=100 if filing['accession']=='initial' else 200)], {
            'amendment_type': '' if filing['accession']=='initial' else 'RESTATEMENT', 'confidential_omitted': ''}
    monkeypatch.setattr(universe, '_inspect_filing', inspect)
    subject._current_holdings.cache_clear()
    before, _, _ = subject._current_holdings(str(report), 'r', str(recovery), 'r', str(tmp_path), str(tmp_path), '2025-05-16')
    after, _, _ = subject._current_holdings(str(report), 'r', str(recovery), 'r', str(tmp_path), str(tmp_path), '2025-05-21')
    assert before.reported_value_usd.tolist() == [100]
    assert after.reported_value_usd.tolist() == [200]


def test_verified_parser_preserves_sec_value_unit_cutover_without_runner_imports():
    import xml.etree.ElementTree as ET
    recovery = subject._json('D:/us-tech-quant-data/13f/recovery_20260913/quarter_manifest.json')
    parser = subject._readonly_parser(recovery['sources']['xml_parser'])
    root = ET.fromstring('<informationTable><infoTable><nameOfIssuer>Example</nameOfIssuer>'
        '<titleOfClass>COMMON</titleOfClass><cusip>123456789</cusip><value>123</value>'
        '<shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>'
        '</shrsOrPrnAmt></infoTable></informationTable>')
    assert parser.parse_holdings(root, '2022-11-15')[0]['value_usd'] == 123000
    assert parser.parse_holdings(root, '2023-02-15')[0]['value_usd'] == 123
