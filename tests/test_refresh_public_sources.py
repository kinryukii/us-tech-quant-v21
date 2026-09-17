import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

SOURCE = Path(__file__).parents[1] / "scripts/storage/refresh_public_sources.py"
SPEC = importlib.util.spec_from_file_location("refresh_public_sources", SOURCE)
public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public)
sys.path.insert(0, "D:/us-tech-quant/fast6/src")


def nfci_fixture(tmp_path, change=None):
    from scripts.storage.restore_sec_data import file_identity
    from scripts.storage.refresh_official_research_data import save_json
    paths = SimpleNamespace(repo_root=Path('D:/us-tech-quant'), results_root=tmp_path/'results',
                            cache_root=tmp_path/'cache', data_root=tmp_path/'data')
    for path in (paths.results_root, paths.cache_root, paths.data_root): path.mkdir()
    root = paths.results_root/'official_research_intake/nfci_test/nfci'
    raw_root = paths.cache_root/'official_research_intake/nfci_test/nfci/raw/nfci'
    raw_root.mkdir(parents=True)
    header = ','.join(public.NFCI_COLUMNS)
    csv_bytes = (header+'\n08/28/2026,-0.5000,-0.4,-0.3,-0.2,0.1,\n'
                 '09/04/2026,-0.6,-0.5,-0.4,-0.3,0.2,0.1\n'
                 '09/11/2026,-0.7,-0.6,-0.5,-0.4,0.3,0.2\n').encode()
    bodies = {name:b'synthetic documentation' for name in public.NFCI_URLS}
    bodies['page'] = public.NFCI_URLS['provider'].encode()
    bodies['provider'] = json.dumps({'data':{'nfciDataSeriesCsvCsv':public.NFCI_URLS['csv'],
        **{key:url for key,url in public.NFCI_URLS.items() if key not in {'page','provider','terms','csv'}}}}).encode()
    bodies['csv'] = csv_bytes
    if change == 'missing_link': bodies['provider'] = bodies['provider'].replace(b'nfci-data-series-csv.csv',b'wrong.csv')
    inputs = {}
    for name,url in public.NFCI_URLS.items():
        key=hashlib.sha256(url.encode()).hexdigest(); path=raw_root/(key+'.source'); path.write_bytes(bodies[name])
        raw={'local_path':str(path),'sha256':hashlib.sha256(bodies[name]).hexdigest(),'source_reference':url,
             'event_family':'nfci','document_kind':'NFCI_ORIGINAL_SOURCE','source':'CHICAGO_FED_OFFICIAL',
             'status':'DOWNLOADED','retrieval_timestamp_utc':'2026-09-14T14:30:00Z'}
        if change == 'timezone' and name == 'csv': raw['retrieval_timestamp_utc']='2026-09-14T14:30:00'
        sidecar={**raw,'byte_count':len(bodies[name])}
        if change == 'sidecar' and name == 'csv': sidecar['source_reference']='https://example.invalid/source.csv'
        save_json(path.with_suffix('.json'),sidecar)
        parent=None if name in {'page','terms'} else inputs['page' if name=='provider' else 'provider']
        if change == 'parent' and name == 'csv': parent=inputs['page']
        response={'status':503 if change=='http' and name=='csv' else 200,'final_url':url,'bytes':len(bodies[name])}
        if change == 'url' and name == 'csv': raw['source_reference']='https://example.invalid/source.csv'
        receipt=root/'requests'/(key+'.json')
        save_json(receipt,{'raw':raw,'http_response':response,'parent':parent})
        inputs[name]=file_identity(receipt)
    acquisition=root/'acquisition.json'
    save_json(acquisition,{'role':'CHICAGO_FED_NFCI_RAW_INTAKE','run_id':'nfci_test','inputs':inputs})
    return paths,acquisition,csv_bytes


def test_nfci_offline_wide_source_precision_null_cutoff_and_resume(tmp_path,monkeypatch):
    import urllib.request
    import pyarrow.parquet as pq
    from decimal import Decimal
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('offline only'))
    paths,acquisition,raw=nfci_fixture(tmp_path)
    result=public.normalize_nfci(acquisition,'2026-09-04',paths=paths)
    assert result['outputs'][0]['row_count']==2 and result['qc']['source_max_date']=='2026-09-11'
    assert result['index_not_contribution'] and not result['historical_pit_certified']
    rows=pq.read_table(result['outputs'][0]['path']).to_pylist()
    assert rows[0]['raw_NFCI']=='-0.5000' and rows[0]['nfci']==Decimal('-0.5')
    assert rows[0]['nonfinancial_leverage'] is None and rows[0]['raw_Nonfinancial_Leverage']==''
    assert all(r['available_at_utc'] is None for r in rows)
    assert rows[0]['source_row_number']==2 and rows[-1]['date']=='2026-09-04'
    monkeypatch.setattr(public,'parse_nfci',lambda *a:pytest.fail('completed snapshot must not reparse'))
    assert public.normalize_nfci(acquisition,'2026-09-04',paths=paths)==result
    with pytest.raises(ValueError,match='CONTRACT_CHANGED'):
        public.normalize_nfci(acquisition,'2026-09-11',paths=paths)


@pytest.mark.parametrize('change',['missing_link','timezone','sidecar','parent','http','url'])
def test_nfci_wrong_lineage_rejected_before_output(tmp_path,change):
    paths,acquisition,_=nfci_fixture(tmp_path,change)
    with pytest.raises(ValueError): public.normalize_nfci(acquisition,'2026-09-14',paths=paths)
    assert not list(paths.data_root.rglob('*.parquet'))


@pytest.mark.parametrize('replacement',[
    (b'09/04/2026',b'09/03/2026'),
    (b'09/04/2026',b'09/11/2026'),
    (b'-0.5000',b'NaN'),
    (b'-0.5000',b'EXTRA,-0.5000'),
    (b'Friday_of_Week',b'DATE'),
])
def test_nfci_date_schema_and_number_fail_closed(tmp_path,replacement):
    _,_,raw=nfci_fixture(tmp_path)
    with pytest.raises(ValueError): public.parse_nfci(raw.replace(*replacement),'2026-09-14')


def test_nfci_existing_source_mutation_is_not_reused(tmp_path):
    paths,acquisition,_=nfci_fixture(tmp_path)
    public.normalize_nfci(acquisition,'2026-09-14',paths=paths)
    key=hashlib.sha256(public.NFCI_URLS['csv'].encode()).hexdigest()
    path=paths.cache_root/'official_research_intake/nfci_test/nfci/raw/nfci'/(key+'.source')
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='RAW_SOURCE'): public.normalize_nfci(acquisition,'2026-09-14',paths=paths)


def test_cboe_single_close_preserves_lexical_value_and_row_identity():
    raw = b'DATE,VVIX\n01/02/2025,90.1000\n09/11/2026,88.0\n09/14/2026,89.0\n'
    frame, last = public.parse_cboe_index(raw, 'VVIX', '2026-09-11')
    assert last == '2026-09-14' and frame.date.tolist() == ['2025-01-02', '2026-09-11']
    assert frame.raw_VVIX.tolist() == ['90.1000', '88.0']
    assert frame.source_row_number.tolist() == [2, 3]
    assert frame.close.tolist() == [90.1, 88.0]


@pytest.mark.parametrize('raw', [
    b'DATE,VVIX\n01/02/2025,90\n01/02/2025,90\n',
    b'DATE,VVIX\n01/03/2025,90\n01/02/2025,90\n',
    b'DATE,VVIX\n01/02/2025,inf\n',
    b'DATE,VVIX\n01/02/2025,-1\n',
    b'DATE,WRONG\n01/02/2025,90\n',
])
def test_cboe_bad_identity_dates_and_values_fail(raw):
    with pytest.raises(ValueError):
        public.parse_cboe_index(raw, 'VVIX', '2026-09-14')


def test_cboe_published_ohlc_exceptions_are_visible_not_rewritten():
    frame, _ = public.parse_cboe_index(
        b'DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2025,20,15,10,12\n', 'VIX9D', '2026-09-14')
    assert frame.official_ohlc_range_exception.tolist() == [True]
    assert frame.raw_OPEN.iloc[0] == '20' and frame.open.iloc[0] == 20


def test_cboe_extra_field_cannot_be_silently_converted_into_index():
    with pytest.raises(ValueError, match='ROW_WIDTH'):
        public.parse_cboe_index(b'DATE,OPEN,HIGH,LOW,CLOSE\nEXTRA,01/02/2025,2,3,1,2\n', 'VIX9D', '2026-09-14')


@pytest.mark.parametrize('corruption', ['none', 'swap', 'timestamp', 'sidecar', 'page'])
def test_cboe_recovery_rebinds_index_url_sidecar_and_official_page(tmp_path, corruption):
    from fast6.acquisition import LinkParser, cache_key
    capture = SimpleNamespace(LinkParser=LinkParser, cache_key=cache_key)
    urls = [f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{x}_History.csv'
            for x in public.CBOE_INDICES]
    def raw(url, value):
        folder = tmp_path / 'cboe_indices'; folder.mkdir(exist_ok=True)
        path = folder / (cache_key(url) + '.source'); path.write_bytes(value)
        item = {'local_path': str(path), 'source_reference': url,
                'source': 'CBOE_OFFICIAL', 'status': 'CACHED',
                'sha256': public.digest(path), 'retrieval_timestamp_utc': '2026-09-14T10:00:00Z'}
        path.with_suffix('.json').write_text(json.dumps(item))
        return item
    page = ''.join(f'<a href="{url}">history</a>' for url in urls if corruption != 'page').encode()
    acquisition = {'target': '2026-09-14', 'page': raw(public.CBOE_HISTORY_PAGE, page), 'items': [
        {'symbol': symbol, 'raw': raw(url, f'DATE,{symbol}\n01/02/2025,10\n'.encode())}
        for symbol, url in zip(public.CBOE_INDICES, urls)]}
    if corruption == 'swap':
        acquisition['items'][0]['raw'], acquisition['items'][1]['raw'] = acquisition['items'][1]['raw'], acquisition['items'][0]['raw']
    if corruption in {'timestamp', 'sidecar'}:
        item = acquisition['items'][0]['raw']
        meta_path = Path(item['local_path']).with_suffix('.json')
        meta = json.loads(meta_path.read_text())
        if corruption == 'timestamp':
            item['retrieval_timestamp_utc'] = meta['retrieval_timestamp_utc'] = '2026-09-14'
        else:
            meta['source_reference'] = 'https://example.invalid/wrong'
        meta_path.write_text(json.dumps(meta))
    if corruption == 'none':
        public.validate_cboe_acquisition(acquisition, capture, tmp_path, '2026-09-14')
    else:
        with pytest.raises(ValueError):
            public.validate_cboe_acquisition(acquisition, capture, tmp_path, '2026-09-14')


def test_bls_schedule_keeps_dst_correct_and_schedule_only():
    raw = b"""<table><tr><th>Date</th><th>Time</th><th>Release</th></tr>
    <tr><td>Friday, January 9, 2026</td><td>08:30 AM</td><td>Employment Situation for December 2025</td></tr>
    <tr><td>Friday, July 10, 2026</td><td>08:30 AM</td><td>Producer Price Index for June 2026</td></tr></table>"""
    frame = public.parse_bls_schedule(raw, 2026)
    assert list(frame.scheduled_time_utc) == ["2026-01-09T13:30:00Z", "2026-07-10T12:30:00Z"]
    assert "actual_release_time_utc" not in frame
    assert "value" not in frame


def test_bls_fails_on_unparsed_dated_row():
    raw = b"<table><tr><td>2026-09-11</td><td>TBD</td><td>Future schedule</td></tr></table>"
    with pytest.raises(ValueError, match="Unparsed dated"):
        public.parse_bls_schedule(raw, 2026)


def test_bls_rejects_duplicate_release_key():
    row = b"<tr><td>2026-09-11</td><td>08:30 AM</td><td>Release</td></tr>"
    with pytest.raises(ValueError, match="Duplicate"):
        public.parse_bls_schedule(b"<table>" + row + row + b"</table>", 2026)


def fake_vix(monkeypatch, frame):
    module = SimpleNamespace(SOURCE_URL="https://example.invalid/synthetic.csv",
                             download_official_csv=lambda: b"synthetic fixture",
                             normalize_vix_csv=lambda raw: frame.copy())
    monkeypatch.setattr(public, "load_vix", lambda repo: module)


def test_vix_target_truncation_retains_raw_and_current_vintage(tmp_path, monkeypatch):
    frame = pd.DataFrame({"DATE": pd.to_datetime(["2026-09-11", "2026-09-14"]),
                          "OPEN": [10, 11], "HIGH": [12, 13], "LOW": [9, 10], "CLOSE": [11, 12]})
    fake_vix(monkeypatch, frame)
    result = public.acquire_vix(tmp_path, tmp_path, "2026-09-11")
    assert result["output"]["row_count"] == 1
    assert result["source_max_date"] == "2026-09-14"
    assert result["target_reached"] is True
    assert result["vintage_semantics"] == "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"
    assert Path(result["raw_path"]).read_bytes() == b"synthetic fixture"
    assert public.digest(result["raw_path"]) == result["raw_sha256"]


def test_vix_nonfinite_value_never_publishes_parquet(tmp_path, monkeypatch):
    frame = pd.DataFrame({"DATE": pd.to_datetime(["2026-09-11"]),
                          "OPEN": [10], "HIGH": [float("inf")], "LOW": [9], "CLOSE": [11]})
    fake_vix(monkeypatch, frame)
    with pytest.raises(ValueError, match="non-finite"):
        public.acquire_vix(tmp_path, tmp_path, "2026-09-11")
    assert not (tmp_path / "vix_daily.parquet").exists()


def test_dry_run_does_not_write_or_load_source(tmp_path, monkeypatch):
    monkeypatch.setattr(public, "load_vix", lambda repo: pytest.fail("source loaded"))
    root = tmp_path / "unused"
    assert public.main(["--work-root", str(root), "--target-date", "2026-09-11"]) == 0
    assert not root.exists()


def test_official_holiday_and_open_exception_are_retained_and_flagged():
    frame = pd.DataFrame({"DATE": pd.to_datetime(["2026-09-04", "2026-09-07", "2026-09-08"]),
                          "OPEN": [10., 8., 10.], "HIGH": [12.] * 3,
                          "LOW": [9.] * 3, "CLOSE": [11.] * 3})
    annotated, metadata = public.annotate_vix_calendar(frame)
    pd.testing.assert_frame_equal(annotated[frame.columns], frame)
    assert len(annotated) == 3
    assert list(annotated.is_xnys_session) == [True, False, True]
    assert annotated.loc[1, "calendar_alignment_status"] == "OFFICIAL_ROW_OUTSIDE_XNYS_SESSION"
    assert list(annotated.official_open_outside_high_low) == [False, True, False]
    assert metadata["library_version"]
    assert metadata["semantics"] == "CROSS_MARKET_ALIGNMENT_REFERENCE_NOT_CBOE_CALENDAR_AUTHORITY"


def fred_html(rows=None, rid=50, label="Employment Situation", count=None, year=2026):
    rows = rows if rows is not None else [("Friday January 09, 2026", "7:30 am", True),
                                         ("Thursday July 02, 2026", "7:30 am", False)]
    parts = [f'<title>{year} Economic Release Calendar - {label} | FRED | St. Louis Fed</title>',
        f'<link rel="canonical" href="https://fred.stlouisfed.org/releases/calendar?rid={rid}&amp;view=year&amp;vs={year}-01-01&amp;ve={year}-12-31">',
        f'<meta name="description" content="{len(rows) if count is None else count} economic release dates for release: {label}. FRED: Download data.">',
        '<div id="release-dates-pager"><div><table><tr><th></th><th>Sort By: Date Name</th></tr>']
    for day, time, updated in rows:
        parts.extend([f'<tr><td colspan="2"><span>{day}</span> <span>{"Updated" if updated else ""}</span></td></tr>',
                      f'<tr><td>{time}</td><td><a href="/release?rid={rid}">{label}</a></td></tr>'])
    parts.append(f'<tr><td>Releases 1 - {len(rows)} of {len(rows)}</td></tr></table></div></div><p>All times are US Central Time. Note that release dates do not necessarily represent data availability.</p>')
    return ''.join(parts).encode()


def test_fred_central_timezone_dst_and_updated_marker_are_explicit():
    frame = public.parse_fred_schedule(fred_html(), 2026, 50, "Employment Situation")
    assert frame.scheduled_time_utc.tolist() == ["2026-01-09T13:30:00Z", "2026-07-02T12:30:00Z"]
    assert frame.release_time_et.tolist() == ["08:30", "08:30"]
    assert frame.source_timezone.tolist() == ["America/Chicago"] * 2
    assert frame.source_updated_marker.tolist() == [True, False]
    assert "actual_release_time_utc" not in frame and "value" not in frame


@pytest.mark.parametrize("change", [
    lambda raw: raw.replace(b"2026 Economic", b"2025 Economic"),
    lambda raw: raw.replace(b"rid=50&amp;view", b"rid=10&amp;view"),
    lambda raw: raw.replace(b'2026-12-31', b'2026-06-30'),
    lambda raw: raw.replace(b'US Central Time', b'Eastern Time'),
    lambda raw: raw.replace(b'/release?rid=50', b'/release?rid=10'),
    lambda raw: raw.replace(b'2 economic release dates', b'3 economic release dates'),
])
def test_fred_wrong_identity_or_truncated_page_rejected(change):
    with pytest.raises(ValueError):
        public.parse_fred_schedule(change(fred_html()), 2026, 50, "Employment Situation")


def test_fred_duplicate_empty_and_unknown_times():
    row = ("Friday January 09, 2026", "7:30 am", False)
    with pytest.raises(ValueError, match="Duplicate"):
        public.parse_fred_schedule(fred_html([row, row]), 2026, 50, "Employment Situation")
    with pytest.raises(ValueError, match="Empty"):
        public.parse_fred_schedule(fred_html([]), 2026, 50, "Employment Situation")
    frame = public.parse_fred_schedule(fred_html([("Friday January 09, 2026", "N/A", False)]), 2026, 50, "Employment Situation")
    assert frame.scheduled_time_utc.isna().all() and frame.release_time_et.isna().all()
    assert frame.schedule_time_status.tolist() == ["UNKNOWN_SOURCE_TIME"]


def fred_download_manifest(tmp_path):
    raw = fred_html()
    path = tmp_path / "source.html"; path.write_bytes(raw)
    item = {"release_id": 50, "expected_label": "Employment Situation", "http_status": 200,
        "source_url": "https://fred.stlouisfed.org/releases/calendar?rid=50&y=2026",
        "observed_at": "2026-09-12T19:00:00Z", "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
    manifest = tmp_path / "download_manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "provider": "FRED_ST_LOUIS_FED", "items": [item]}))
    return manifest, path


def test_fred_cached_normalization_cutoff_hash_lineage_and_immutable_sources(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **kw: pytest.fail("network forbidden"))
    manifest, raw = fred_download_manifest(tmp_path)
    source_before = (manifest.read_bytes(), raw.read_bytes())
    report = public.normalize_fred_calendar(manifest, tmp_path / "output", "2026-02-01")
    assert report["rows"] == 1 and report["source_audits"][0]["full_year_rows"] == 2
    stored = json.loads(Path(report["manifest"]["path"]).read_bytes())
    frame = pd.read_parquet(stored["output"]["path"])
    assert frame.source_id.tolist() == [public.digest(raw)]
    assert frame.observed_at.tolist() == ["2026-09-12T19:00:00Z"]
    assert stored["catalog_record"]["dataset"] == "fred_release_calendar"
    assert stored["catalog_record"]["lineage"]["source_timezone"] == "America/Chicago"
    assert "source_years" not in stored["contract"] and "source_years" not in stored["catalog_record"]["lineage"]
    assert "source_year" not in stored["source_audits"][0]
    assert "NOT_COMPLETE_BLS_CALENDAR" in stored["contract"]["scope"]
    assert (manifest.read_bytes(), raw.read_bytes()) == source_before
    assert public.normalize_fred_calendar(manifest, tmp_path / "output", "2026-02-01") == report


def test_fred_changed_raw_fails_before_output(tmp_path):
    manifest, raw = fred_download_manifest(tmp_path)
    raw.write_bytes(raw.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash/size"):
        public.normalize_fred_calendar(manifest, tmp_path / "output", "2026-09-11")
    assert not (tmp_path / "output").exists()


def multi_year_fred_manifest(tmp_path):
    labels = {50: "Employment Situation", 10: "Consumer Price Index",
              192: "Job Openings and Labor Turnover Survey", 11: "Employment Cost Index", 46: "Producer Price Index"}
    items = []
    for year in (2025, 2026):
        rows = [("Friday January 10, 2025", "7:30 am", True), ("Thursday July 03, 2025", "7:30 am", True)] if year == 2025 else None
        for rid, label in labels.items():
            raw = fred_html(rows, rid, label, year=year)
            path = tmp_path / f"{year}_{rid}.html"; path.write_bytes(raw)
            items.append({"release_id": rid, "expected_label": label, "http_status": 200,
                "source_url": f"https://fred.stlouisfed.org/releases/calendar?rid={rid}&y={year}",
                "observed_at": f"2026-09-1{2 if year == 2025 else 3}T19:00:00Z", "path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
    path = tmp_path / "combined_download_manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "provider": "FRED_ST_LOUIS_FED", "source_years": [2025, 2026], "items": items}))
    return path


def test_fred_two_years_share_parser_keep_true_observation_and_cutoff(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **kw: pytest.fail("offline only"))
    source = multi_year_fred_manifest(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = public.normalize_fred_calendar(source, tmp_path / "output", "2026-02-01")
    stored = json.loads(Path(result["manifest"]["path"]).read_bytes())
    frame = pd.read_parquet(stored["output"]["path"])
    assert frame.groupby("source_year").size().to_dict() == {2025: 10, 2026: 5}
    assert stored["contract"]["source_years"] == stored["catalog_record"]["lineage"]["source_years"] == [2025, 2026]
    assert stored["contract"]["release_ids"] == [10, 11, 46, 50, 192]
    assert not frame.duplicated(["release_id", "release_date"]).any()
    sources = {item["sha256"]: item for item in json.loads(source.read_bytes())["items"]}
    assert frame.observed_at.eq(frame.source_id.map({key: item["observed_at"] for key, item in sources.items()})).all()
    assert {r["source_year"] for r in stored["source_audits"]} == {2025, 2026}
    assert len(stored["contract"]["inputs"]) == 10 and frame.release_date.max() == "2026-01-09"
    assert public.normalize_fred_calendar(source, tmp_path / "output", "2026-02-01") == result
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize("change", [
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50&y=2025&y=2025"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50&y=2025.0"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50&y=2027"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50&rid=50&y=2025"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=10&y=2025"),
    lambda doc: doc["items"][0].update(source_url="https://fred.stlouisfed.org/releases/calendar?rid=50&y=2026"),
    lambda doc: doc["items"].append(doc["items"][0]),
    lambda doc: doc["items"].pop(0),
    lambda doc: doc.update(source_years=[2026]),
    lambda doc: doc.update(source_years=[2025, 2025, 2026]),
])
def test_fred_multi_year_identity_completeness_and_duplicates_fail_closed(tmp_path, change):
    source = multi_year_fred_manifest(tmp_path)
    doc = json.loads(source.read_bytes()); change(doc); source.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        public.normalize_fred_calendar(source, tmp_path / "output", "2026-09-11")
    assert not (tmp_path / "output").exists()
