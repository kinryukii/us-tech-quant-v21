import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.storage import refresh_massive_market as m


def payload():
    return {"status": "OK", "adjusted": False, "resultsCount": 2, "results": [
        {"T": "ABC", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100.25,
         "vw": 10.5, "n": 5, "t": 1789171200000},
        {"T": "OTHER", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100, "t": 1789171200000}]}


def norm(data):
    return m.normalize_grouped(data, "2026-09-11", m.provider_mapping(["ABC", "MISSING"]),
                               "a" * 64, "2026-09-12T18:00:00Z")


def test_raw_scope_requested_day_and_original_fields():
    frame, rejected = norm(payload())
    assert rejected == [] and frame.ticker.tolist() == ["ABC"]
    assert frame.date.tolist() == ["2026-09-11"]  # source t is 9/12 UTC
    assert frame.source_timestamp_ms.iloc[0] == payload()["results"][0]["t"]
    assert frame.volume.iloc[0] == 100.25 and frame.vwap.iloc[0] == 10.5
    assert frame.transactions.iloc[0] == 5 and frame.turnover.isna().all()
    assert set(m.PRICE_COLUMNS) <= set(frame.columns)
    assert frame.source.iloc[0] == "MASSIVE_GROUPED" and frame.adjustment.iloc[0] == "raw"


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p.update(adjusted=True), "RAW_ADJUSTMENT"),
    (lambda p: p.update(status="NOT_AUTHORIZED"), "STATUS_NOT_OK"),
    (lambda p: p.update(resultsCount=3), "RESULT_COUNT"),
    (lambda p: p.update(next_url="https://api.massive.com/other"), "PAGINATION"),
    (lambda p: p["results"][1].update(T="ABC"), "DUPLICATE"),
])
def test_response_contract_fails_closed(mutate, match):
    data = payload(); mutate(data)
    with pytest.raises(ValueError, match=match): norm(data)


def test_invalid_selected_row_reported_without_filling():
    data = payload(); data["results"][0]["h"] = 1
    frame, rejected = norm(data)
    assert frame.empty and rejected[0]["ticker"] == "ABC"


def test_explicit_mapping_evidence_and_collision():
    with pytest.raises(ValueError, match="EVIDENCE"):
        m.provider_mapping(["SQ"], {"SQ": {"provider_symbol": "XYZ"}})
    mapping = m.provider_mapping(["SQ"], {"SQ": {"provider_symbol": "XYZ", "evidence_url": "https://issuer.example/rename"}})
    data = payload(); data["results"][0]["T"] = "XYZ"
    frame, _ = m.normalize_grouped(data, "2026-09-11", mapping, "a" * 64, "2026-09-12T18:00:00Z")
    assert frame.ticker.tolist() == ["SQ"] and frame.provider_code.tolist() == ["XYZ"]
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        m.provider_mapping(["SQ", "XYZ"], {"SQ": mapping["SQ"]})


class Response:
    def __init__(self, data=None, status=200):
        self.content = json.dumps(payload() if data is None else data).encode()
        self.status_code = status
        self.headers = {"Date": "Sat, 12 Sep 2026 18:00:00 GMT"}


def test_checkpoint_resume_exact_raw_hash_and_immutable_manifest(tmp_path):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    summary = m.acquire(["2026-09-11"], ["ABC", "MISSING"], "synthetic-secret", tmp_path,
                        request_get=get, gate=lambda root: None)
    assert summary["normalized_rows"] == 1 and summary["missing_ticker_days"] == 1
    assert "apiKey" not in calls[0][0] and calls[0][1]["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert calls[0][1]["params"] == {"adjusted": "false", "include_otc": "false"}
    assert calls[0][1]["allow_redirects"] is False
    manifest_path = Path(summary["manifest_path"])
    before = manifest_path.read_bytes()
    again = m.acquire(["2026-09-11"], ["ABC", "MISSING"], "synthetic-secret", tmp_path,
                      request_get=get, gate=lambda root: None)
    assert len(calls) == 1 and again["network_requests_this_run"] == 0
    assert before == manifest_path.read_bytes()
    manifest = json.loads(before)
    record = manifest["catalog_records"][0]
    frame = pd.read_parquet(record["path"])
    assert set(frame.source_id) == {v["sha256"] for v in record["lineage"]["inputs"]}
    source = Path(record["lineage"]["inputs"][0]["path"])
    assert source.read_bytes() == Response().content
    for path in tmp_path.rglob("*.json"):
        assert b"synthetic-secret" not in path.read_bytes()
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="RAW_CHANGED"):
        m.acquire(["2026-09-11"], ["ABC"], "synthetic-secret", tmp_path, request_get=get, gate=lambda root: None)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_denial_stops_after_one_request(tmp_path, status):
    calls = []
    def get(*args, **kwargs):
        calls.append(1); return Response({}, status)
    result = m.acquire(["2026-09-10", "2026-09-11"], ["ABC"], "synthetic-secret", tmp_path,
                       request_get=get, gate=lambda root: None)
    assert len(calls) == 1 and result["status"] == "STOPPED_PARTIAL"
    assert result["completed_days"] == 0 and result["missing_ticker_days"] == 2


def test_three_network_failures_stop_and_no_exception_secret(tmp_path):
    calls = []
    def get(*args, **kwargs):
        calls.append(1); raise requests.ConnectionError("synthetic-secret")
    result = m.acquire(["2026-09-11"], ["ABC"], "synthetic-secret", tmp_path,
                       request_get=get, gate=lambda root: None)
    assert len(calls) == 3 and result["status"] == "STOPPED_PARTIAL"
    assert all(b"synthetic-secret" not in p.read_bytes() for p in tmp_path.rglob("*.json"))


def test_credential_echo_body_never_written(tmp_path):
    result = m.acquire(["2026-09-11"], ["ABC"], "synthetic-secret", tmp_path,
        request_get=lambda *a, **kw: Response({"echo": "synthetic-secret"}), gate=lambda root: None)
    assert result["status"] == "STOPPED_PARTIAL"
    assert not list(tmp_path.rglob("response_*.json"))


def test_one_writer_lock_and_gate_persisted_spacing(tmp_path, monkeypatch):
    (tmp_path / ".writer.lock").touch()
    with pytest.raises(FileExistsError):
        m.acquire(["2026-09-11"], ["ABC"], "synthetic-secret", tmp_path)
    assert (tmp_path / ".writer.lock").exists()
    sleeps = []
    monkeypatch.setattr(m.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(m.time, "time", lambda: 200.0)
    monkeypatch.setattr(m.time, "sleep", sleeps.append)
    monkeypatch.setattr(m, "_LAST_REQUEST", 0.0)
    m.wait_request(tmp_path)
    m.wait_request(tmp_path)
    assert sleeps == [12.5]


def test_wrapper_uses_current_catalog_scope_calendar_and_roots(tmp_path, monkeypatch):
    class Paths:
        cache_root = tmp_path
        data_root = tmp_path / "data"
    calendar = tmp_path / "calendar.parquet"; calendar.write_bytes(b"calendar")
    class Store:
        catalog_path = tmp_path / "catalog.sqlite3"
        def __init__(self, paths): pass
        def list_tickers(self, dataset):
            assert dataset == "prices_daily"; return ["ABC"]
        def metadata(self, dataset):
            return {"path": str(calendar), "source_sha256": m.sha256(calendar), "min_date": "2024-01-01", "max_date": "2026-12-31"}
        def read(self, *args, **kwargs): return pd.DataFrame({"trade_date": ["2026-09-11"]})
    monkeypatch.setattr(m, "resolve_storage_paths", lambda repo: Paths())
    monkeypatch.setattr(m, "DataStore", Store)
    monkeypatch.setattr(m, "acquisition_tickers", lambda store: ["ABC"])
    monkeypatch.setattr(m, "acquire", lambda days, tickers, key, root, **kwargs: {"days": days, "tickers": tickers, "root": root})
    result = m.run_acquisition(api_key="synthetic-secret", start_date="2026-09-11", end_date="2026-09-11", work_root=tmp_path / "run")
    assert result["days"] == ["2026-09-11"] and result["tickers"] == ["ABC"]


def alias_source(tmp_path):
    data = payload()
    data["results"][0]["T"] = "XYZ"
    data["results"][1]["T"] = "BRK.B"
    root = tmp_path / "source"
    result = m.acquire(["2026-09-10", "2026-09-11"], ["SQ", "BRK/B"], "synthetic-secret", root,
        request_get=lambda *a, **kw: Response(data), gate=lambda root: None)
    mapping = {"SQ": {"provider_symbol": "XYZ", "evidence_url": "https://issuer.example/rename", "effective_from": "2025-01-21"},
               "BRK/B": {"provider_symbol": "BRK.B", "evidence_url": "https://issuer.example/class-b"}}
    return root, Path(result["manifest_path"]), mapping


def test_cached_aliases_no_network_preserve_source_and_times(tmp_path, monkeypatch):
    root, original, mapping = alias_source(tmp_path)
    old_manifest, old_summary = original.read_bytes(), (root / "acquisition_summary.json").read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError("NETWORK_PATH_FORBIDDEN")
    monkeypatch.setattr(m, "acquire_day", forbidden)
    monkeypatch.setattr(m.requests, "get", forbidden)
    monkeypatch.setattr(m.requests.sessions.Session, "request", forbidden)
    result = m.normalize_cached(acquisition_manifest=original, checkpoint_root=root,
                                symbol_map=mapping, output_root=tmp_path / "aliases")
    assert result["normalized_rows"] == 4 and result["missing_ticker_days"] == 0
    assert result["network_requests_this_run"] == 0
    supplement = json.loads(Path(result["manifest_path"]).read_bytes())
    assert supplement["contract"]["scope_source"]["mode"] == "VERIFIED_CACHE_ONLY_ALIAS_SUPPLEMENT"
    assert {r["ticker"] for r in supplement["catalog_records"]} == {"SQ", "BRK/B"}
    assert supplement["contract"]["scope_source"]["acquisition_manifest"]["sha256"] == hashlib.sha256(old_manifest).hexdigest()
    for record in supplement["catalog_records"]:
        frame = pd.read_parquet(record["path"])
        assert set(frame.provider_code) == {mapping[record["ticker"]]["provider_symbol"]}
        for row in frame.to_dict("records"):
            cp = json.loads((root / "days" / row["date"] / "checkpoint.json").read_bytes())
            assert row["observed_at"] == cp["observed_at"] and row["source_id"] == cp["raw"]["sha256"]
    assert original.read_bytes() == old_manifest
    assert (root / "acquisition_summary.json").read_bytes() == old_summary


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("damage", ["missing_day", "changed_raw", "failed_day", "changed_manifest_ref"])
def test_cached_preflight_all_days_before_any_output(tmp_path, monkeypatch, damage, explicit):
    root, original, mapping = alias_source(tmp_path)
    cp = root / "days/2026-09-11/checkpoint.json"
    content = json.loads(cp.read_bytes())
    if damage == "missing_day": cp.unlink()
    elif damage == "changed_raw": Path(content["raw"]["path"]).write_bytes(b"damaged")
    elif damage == "failed_day":
        content["status"] = "FAILED"; m.write_json(cp, content)
    else:
        manifest = json.loads(original.read_bytes()); manifest["contract"]["inputs"][1]["observed_at"] = "2026-09-12T19:00:00Z"
        m.write_json(original, manifest)
    monkeypatch.setattr(m, "acquire_day", lambda *a, **kw: pytest.fail("network fallback forbidden"))
    with pytest.raises((ValueError, FileNotFoundError)):
        if explicit:
            m.normalize_cached_tickers(original, root, ["UNKNOWN"], output_root=tmp_path / "aliases")
        else:
            m.normalize_cached(acquisition_manifest=original, checkpoint_root=root,
                               symbol_map=mapping, output_root=tmp_path / "aliases")
    assert not (tmp_path / "aliases").exists()


def test_cached_scope_output_and_effective_date_restrictions(tmp_path):
    root, original, mapping = alias_source(tmp_path)
    with pytest.raises(ValueError, match="OUTSIDE_ORIGINAL_SCOPE"):
        m.normalize_cached(acquisition_manifest=original, checkpoint_root=root,
            symbol_map={"UNKNOWN": {"provider_symbol": "UNKNOWN"}}, output_root=tmp_path / "aliases")
    with pytest.raises(ValueError, match="SEPARATE_FROM_SOURCE"):
        m.normalize_cached(acquisition_manifest=original, checkpoint_root=root,
            symbol_map=mapping, output_root=root / "aliases")
    mapping["SQ"]["effective_from"] = "2026-09-11"
    with pytest.raises(ValueError, match="EFFECTIVE_DATES"):
        m.normalize_cached(acquisition_manifest=original, checkpoint_root=root,
            symbol_map=mapping, output_root=tmp_path / "aliases")


def test_cached_alias_does_not_duplicate_existing_provider_owner(tmp_path):
    data = payload(); data["results"][0]["T"] = "XYZ"
    root = tmp_path / "source"
    result = m.acquire(["2026-09-11"], ["SQ", "XYZ"], "synthetic-secret", root,
        request_get=lambda *a, **kw: Response(data), gate=lambda root: None)
    with pytest.raises(ValueError, match="ALREADY_OWNED"):
        m.normalize_cached(acquisition_manifest=result["manifest_path"], checkpoint_root=root,
            symbol_map={"SQ": {"provider_symbol": "XYZ", "evidence_url": "https://issuer.example/rename"}},
            output_root=tmp_path / "aliases")
    assert not (tmp_path / "aliases").exists()


def explicit_source(tmp_path):
    days = ["2025-11-07", "2025-11-10", "2025-11-11"]
    def get(url, **kwargs):
        day = url.rsplit("/", 1)[1]
        data = payload()
        data["results"].append({**data["results"][0], "T": "FI"})
        for row in data["results"]:
            row["t"] = int(pd.Timestamp(day, tz="America/New_York").timestamp() * 1000)
        data["resultsCount"] = len(data["results"])
        return Response(data)
    root = tmp_path / "source"
    result = m.acquire(days, ["ABC", "RESERVED"], "synthetic-secret", root,
        request_get=get, gate=lambda root: None)
    return root, Path(result["manifest_path"])


def test_cached_explicit_new_symbol_no_network_exact_lineage_and_idempotence(tmp_path, monkeypatch):
    root, original = explicit_source(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    def forbidden(*args, **kwargs): raise AssertionError("NETWORK_FORBIDDEN")
    monkeypatch.setattr(m, "acquire_day", forbidden)
    monkeypatch.setattr(m.requests.sessions.Session, "request", forbidden)
    result = m.normalize_cached_tickers(original, root, ["OTHER"], output_root=tmp_path / "explicit")
    assert result["normalized_rows"] == 3 and result["network_requests_this_run"] == 0
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    assert manifest["contract"]["scope_source"]["mode"] == "EXPLICIT_SYMBOLS"
    assert "NO_IDENTITY_CERTIFICATION_OR_STRATEGY_MEMBERSHIP" in manifest["contract"]["scope_source"]["selection_semantics"]
    old = json.loads(original.read_bytes())
    assert manifest["contract"]["days"] == old["contract"]["days"]
    assert manifest["contract"]["inputs"] == old["contract"]["inputs"]
    assert "OTHER" not in old["contract"]["mapping"]
    frame = pd.read_parquet(manifest["catalog_records"][0]["path"])
    for row in frame.to_dict("records"):
        cp = json.loads((root / "days" / row["date"] / "checkpoint.json").read_bytes())
        raw = next(r for r in json.loads(Path(cp["raw"]["path"]).read_bytes())["results"] if r["T"] == "OTHER")
        assert row["ticker"] == row["provider_code"] == "OTHER"
        assert [row[k] for k in ("open", "high", "low", "close", "volume", "source_timestamp_ms")] == [raw[k] for k in ("o", "h", "l", "c", "v", "t")]
        assert row["source_id"] == cp["raw"]["sha256"] and row["observed_at"] == cp["observed_at"]
    first_bytes = {p: p.read_bytes() for p in (tmp_path / "explicit").rglob("*") if p.is_file()}
    assert m.normalize_cached_tickers(original, root, ["OTHER"], output_root=tmp_path / "explicit") == result
    assert all(p.read_bytes() == raw for p, raw in {**before, **first_bytes}.items())


def test_cached_explicit_transport_window_never_relabels_or_fills(tmp_path):
    root, original = explicit_source(tmp_path)
    mapping = {"FI": {"provider_symbol": "FI", "effective_to": "2025-11-10",
                       "evidence_url": "https://issuer.example/same-cusip-rename"}}
    result = m.normalize_cached_tickers(original, root, ["FI", "ABSENT"], mapping, output_root=tmp_path / "explicit")
    manifest = json.loads(Path(result["manifest_path"]).read_bytes())
    frame = pd.read_parquet(manifest["catalog_records"][0]["path"])
    assert manifest["catalog_records"][0]["lineage"]["provider_mapping"]["effective_to"] == "2025-11-10"
    assert frame.date.tolist() == ["2025-11-07", "2025-11-10"]
    assert frame.ticker.eq("FI").all() and frame.provider_code.eq("FI").all()
    assert set(manifest["contract"]["mapping"]) == {"FI", "ABSENT"}
    coverage = {r["ticker"]: r for r in manifest["coverage"]}
    assert coverage["FI"]["missing_dates"] == ["2025-11-11"] and coverage["ABSENT"]["rows"] == 0
    assert result["completed_days"] == 3 and result["normalized_rows"] == 2


def test_manifest_publication_preserves_legacy_bytes_instead_of_metadata_migration(tmp_path):
    root, original = explicit_source(tmp_path)
    manifest = json.loads(original.read_bytes())
    # Simulate the original completed 51-day main's older lineage schema.
    for record in manifest["catalog_records"]:
        record["lineage"].pop("provider_mapping")
    m.write_json(original, manifest)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError, match="Preserving a different existing manifest"):
        m.acquire(manifest["contract"]["days"], list(manifest["contract"]["mapping"]),
            "synthetic-secret", root, request_get=lambda *a, **kw: pytest.fail("network forbidden"),
            gate=lambda root: None)
    assert original.read_bytes() == before[original]
    assert (root / "acquisition_summary.json").read_bytes() == before[root / "acquisition_summary.json"]
    for record in manifest["catalog_records"]:
        assert Path(record["path"]).read_bytes() == before[Path(record["path"])]


def test_immutable_json_guard_matches_established_platform_bytes(tmp_path):
    target = tmp_path / "manifest.json"
    value = {"escaped": "new\nline", "rows": [1, 2]}
    target.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    before = target.read_bytes()
    m.write_json(target, value, immutable=True)
    assert target.read_bytes() == before
    with pytest.raises(FileExistsError):
        m.write_json(target, {"rows": [2]}, immutable=True)
    assert target.read_bytes() == before


@pytest.mark.parametrize("tickers", [[], (), None, "FI", [None], ["../FI"]])
def test_cached_explicit_rejects_empty_or_invalid_ticker_scope(tmp_path, tickers):
    root, original = explicit_source(tmp_path)
    with pytest.raises(ValueError):
        m.normalize_cached_tickers(original, root, tickers, output_root=tmp_path / "explicit")
    assert not (tmp_path / "explicit").exists()


@pytest.mark.parametrize("owner", ["ABC", "RESERVED"])
def test_cached_explicit_cannot_take_original_transport_even_without_rows(tmp_path, owner):
    root, original = explicit_source(tmp_path)
    with pytest.raises(ValueError, match="ALREADY_OWNED"):
        m.normalize_cached_tickers(original, root, ["NEW"], {"NEW": {
            "provider_symbol": owner, "evidence_url": "https://issuer.example/mapping"}}, output_root=tmp_path / "explicit")
    assert not (tmp_path / "explicit").exists()


@pytest.mark.parametrize("damage", ["output", "raw", "attempt", "reversed_window", "incomplete"])
def test_cached_explicit_preflight_path_and_contract_rejection(tmp_path, damage):
    root, original = explicit_source(tmp_path)
    manifest = json.loads(original.read_bytes())
    cp_path = root / "days/2025-11-11/checkpoint.json"
    cp = json.loads(cp_path.read_bytes())
    output = tmp_path / "explicit"
    mapping = None
    if damage == "output": output = root / "new"
    elif damage in {"raw", "attempt"}:
        outside = tmp_path / "outside.json"
        outside.write_bytes(Path(cp["raw"]["path"]).read_bytes())
        ref = m.file_identity(outside)
        if damage == "raw":
            cp["raw"] = ref
            manifest["contract"]["inputs"][-1].update(ref)
            m.write_json(original, manifest)
        else:
            cp["attempts"].append({"raw": ref})
        m.write_json(cp_path, cp)
    elif damage == "incomplete":
        manifest["summary"]["status"] = "STOPPED_PARTIAL"; m.write_json(original, manifest)
    else:
        mapping = {"FI": {"provider_symbol": "FI", "effective_from": "2025-11-11", "effective_to": "2025-11-10"}}
    with pytest.raises(ValueError):
        m.normalize_cached_tickers(original, root, ["FI"], mapping, output_root=output)
    assert not output.exists()


def compact_source(tmp_path):
    def get(url, **kwargs):
        day = url.rsplit('/', 1)[1]
        data = payload()
        data['results'] = [data['results'][0]]
        data['results'][0]['t'] = int(pd.Timestamp(day, tz='UTC').timestamp() * 1000)
        if day == '2026-09-11':
            data['results'].append({**data['results'][0], 'T': 'PART'})
        data['resultsCount'] = len(data['results'])
        return Response(data)
    result = m.acquire(['2026-09-10', '2026-09-11'], ['ABC', 'PART'], 'synthetic-secret', tmp_path / 'source',
                       request_get=get, gate=lambda root: None)
    return Path(result['manifest_path'])


def test_compact_shared_reference_subset_and_price_bytes_unchanged(tmp_path, monkeypatch):
    source = compact_source(tmp_path)
    original_bytes = source.read_bytes()
    original = json.loads(original_bytes)
    prices_before = {row['path']: Path(row['path']).read_bytes() for row in original['catalog_records']}
    def forbidden(*args, **kwargs): raise AssertionError('NETWORK_FORBIDDEN')
    monkeypatch.setattr(m.requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(m, 'acquire_day', forbidden)
    result = m.compact_acquisition_manifest(source, tmp_path / 'compact')
    manifest = json.loads(Path(result['manifest']['path']).read_bytes())
    shared = json.loads(Path(result['shared_inputs']['path']).read_bytes())
    assert set(shared) == {'schema_version', 'role', 'provider', 'inputs'}
    assert shared['role'] == 'RAW_INPUT_MANIFEST' and shared['provider'] == 'MASSIVE_GROUPED'
    assert all(set(item) == {'path', 'sha256', 'date', 'observed_at'} for item in shared['inputs'])
    records = {row['ticker']: row for row in manifest['catalog_records']}
    assert all('inputs' not in row['lineage'] for row in records.values())
    assert 'indexes' not in records['ABC']['lineage']['inputs_manifest']
    assert records['PART']['lineage']['inputs_manifest']['indexes'] == [1]
    for row in records.values():
        ref = row['lineage']['inputs_manifest']
        selected = [shared['inputs'][i] for i in ref.get('indexes', range(len(shared['inputs'])))]
        assert set(pd.read_parquet(row['path']).source_id) == {item['sha256'] for item in selected}
        assert Path(row['path']).read_bytes() == prices_before[row['path']]
        assert ref['sha256'] == m.sha256(ref['path'])
    assert source.read_bytes() == original_bytes and not list((tmp_path / 'compact').rglob('*.parquet'))
    assert result['parquet_files_written'] == 0 and result['network_requests'] == 0
    assert m.compact_acquisition_manifest(source, tmp_path / 'compact') == result


@pytest.mark.parametrize('damage,match', [
    ('raw', 'RAW_HASH'), ('price', 'PRICE_HASH'), ('provider', 'MIXED_SOURCE'),
    ('raw_provider', 'MIXED_SOURCE'), ('incomplete', 'COMPLETED_MASSIVE'),
    ('inline_mismatch', 'RAW_LINEAGE'), ('duplicate_raw', 'DUPLICATE_OR_INCOMPLETE'),
])
def test_compact_rejects_bad_hash_mixed_source_and_incomplete_before_write(tmp_path, damage, match):
    source = compact_source(tmp_path)
    original = json.loads(source.read_bytes())
    if damage == 'raw':
        Path(original['contract']['inputs'][0]['path']).write_bytes(b'changed')
    elif damage == 'price':
        Path(original['catalog_records'][0]['path']).write_bytes(b'changed')
    elif damage == 'provider':
        original['catalog_records'][0]['source'] = 'YAHOO_CHART'
    elif damage == 'raw_provider':
        original['contract']['inputs'][0]['provider'] = 'YAHOO_CHART'
    elif damage == 'incomplete':
        original['summary']['status'] = 'STOPPED_PARTIAL'
    elif damage == 'inline_mismatch':
        original['catalog_records'][0]['lineage']['inputs'][0]['observed_at'] = '2026-01-01T00:00:00Z'
    else:
        original['contract']['inputs'].append(original['contract']['inputs'][0])
    m.write_json(source, original)
    with pytest.raises(ValueError, match=match):
        m.compact_acquisition_manifest(source, tmp_path / 'compact')
    assert not (tmp_path / 'compact').exists()


def test_compact_row_availability_must_equal_its_selected_raw_day(tmp_path):
    source = compact_source(tmp_path)
    original = json.loads(source.read_bytes())
    record = original['catalog_records'][0]
    frame = pd.read_parquet(record['path'])
    frame.loc[0, 'observed_at'] = '2026-01-01T00:00:00Z'
    frame.to_parquet(record['path'], index=False)
    record['source_sha256'] = m.sha256(record['path'])
    m.write_json(source, original)
    with pytest.raises(ValueError, match='DATE_OR_OBSERVED_TIME'):
        m.compact_acquisition_manifest(source, tmp_path / 'compact')
    assert not (tmp_path / 'compact').exists()
