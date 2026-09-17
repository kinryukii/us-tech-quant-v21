from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import time
import zlib
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "scripts" / "storage"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("refresh_sec_disclosures_test", SCRIPT_DIR / "refresh_sec_disclosures.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class FakeCache:
    def __init__(self, root, payloads):
        self.database = root / "cache.sqlite"
        self.payloads = payloads
        self.requests = []
        self.request_count = 0
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE responses (url TEXT, status INTEGER, fetched_utc TEXT, sha256 TEXT)")

    def request(self, url, timeout):
        assert timeout == 20
        self.requests.append(url)
        self.request_count += 1
        payload = self.payloads[url]
        if isinstance(payload, Exception):
            raise payload
        raw = json.dumps(payload).encode()
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO responses VALUES (?,?,?,?)", (url, 200, "2026-09-13T00:00:00Z", hashlib.sha256(raw).hexdigest()))
        return raw


def sub_url(cik):
    return f"https://data.sec.gov/submissions/CIK{cik:010d}.json"


def fact_url(cik):
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def document(form, accession):
    return {"filings": {"recent": {"form": [form], "accessionNumber": [accession],
                                    "filingDate": ["2026-09-11"], "acceptanceDateTime": ["2026-09-11T20:00:00Z"]}}}


def test_only_recent_financial_filings_trigger_facts_and_keep_lineage(tmp_path):
    cache = FakeCache(tmp_path, {sub_url(1): document("8-K", "a"), sub_url(2): document("13F-HR", "b"),
                                fact_url(1): {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
                                    {"accn": "a", "filed": "2026-09-11", "val": 12},
                                    {"accn": "outside", "filed": "2026-09-12", "val": 999}]}}}}}})
    facts, disclosures, statuses, reason = refresh.collect(cache, [1, 2], "2026-08-22", "2026-09-11", 60)
    assert reason == "COMPLETE_CIK_SCAN"
    assert cache.requests == [sub_url(1), fact_url(1), sub_url(2)]
    assert len(disclosures) == 2 and len(facts) == 1
    assert facts.acceptance_status.tolist() == ["KNOWN"]
    assert facts.source_cache_database.tolist() == [str(cache.database.resolve())]
    assert statuses.facts_status.tolist() == ["PARSED", "NOT_REQUIRED"]


def test_three_global_failures_stop_remaining_ciks(tmp_path):
    cache = FakeCache(tmp_path, {sub_url(cik): RuntimeError("SEC_REQUEST_FAILED:connection") for cik in range(1, 6)})
    facts, disclosures, statuses, reason = refresh.collect(cache, [1, 2, 3, 4, 5], "2026-08-22", "2026-09-11", 60)
    assert reason == "STOP_THREE_CONSECUTIVE_NETWORK_FAILURES"
    assert len(cache.requests) == 3
    assert statuses.submissions_status.tolist() == ["FETCH_FAILED"] * 3 + ["NOT_PROCESSED"] * 2
    assert facts.empty and disclosures.empty


def test_time_budget_and_unrequested_history_are_explicit(tmp_path):
    cache = FakeCache(tmp_path, {})
    _, _, statuses, reason = refresh.collect(cache, [1, 2], "2026-08-22", "2026-09-11", 0)
    assert reason == "STOP_TIME_BUDGET"
    assert not cache.requests
    assert statuses.submissions_status.eq("NOT_PROCESSED").all()
    assert refresh.needs_history({"filings": {"files": [{"filingFrom": "2026-01-01", "filingTo": "2026-08-25"}]}}, "2026-08-22", "2026-09-11")
    assert not refresh.needs_history({"filings": {"files": [{"filingFrom": "2020-01-01", "filingTo": "2025-12-31"}]}}, "2026-08-22", "2026-09-11")


def test_master_index_filters_exact_cik_dates_and_records_coverage():
    payload = b'''SEC master index
CIK|Company Name|Form Type|Date Filed|Filename
-----------------------------------------
1|EXAMPLE|8-K|2026-08-21|edgar/data/1/a.txt
1|EXAMPLE|8-K|2026-09-11|edgar/data/1/b.txt
99|UNMAPPED|10-K|2026-09-11|edgar/data/99/c.txt
'''
    candidates, filings, metadata = refresh.index_candidates(payload, [1, 2], "2026-08-22", "2026-09-11")
    assert candidates == [1]
    assert filings.accession.tolist() == ["b"]
    assert metadata["index_rows"] == 3
    with pytest.raises(ValueError, match="not yet current"):
        refresh.index_candidates(payload, [1], "2026-08-22", "2026-09-12")
    with pytest.raises(ValueError, match="header"):
        refresh.index_candidates(b"blocked", [1], "2026-08-22", "2026-09-11")


def test_shared_failure_gate_stops_at_three():
    gate = refresh.SharedRequestGate()
    gate.record(False)
    gate.record(True)
    assert gate.consecutive_failures == 0
    for _ in range(3):
        gate.record(False)
    assert gate.stopped.is_set()
    with pytest.raises(RuntimeError, match="STOPPED"):
        gate.wait()


def test_index_filed_vs_acceptance_boundary_is_explained(tmp_path):
    import pandas as pd
    database = tmp_path / "source.sqlite"
    doc = document("424B2", "a")
    doc["filings"]["recent"]["acceptanceDateTime"] = ["2026-08-21T21:42:53Z"]
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE responses (url TEXT,status INTEGER,body_zlib BLOB)")
        connection.execute("INSERT INTO responses VALUES (?,?,?)", (sub_url(1), 200, zlib.compress(json.dumps(doc).encode())))
    frame, counts = refresh.audit_index_window(pd.DataFrame([{"cik": 1, "accession": "a", "filed_date": "2026-08-24"}]),
                                                pd.DataFrame(), database, "2026-08-22", "2026-09-11")
    assert counts == {"ACCEPTED_BEFORE_WINDOW": 1}
    assert frame.outside_window_accepted_at.iloc[0] == pd.Timestamp("2026-08-21T21:42:53Z")


def test_parallel_reuses_seccache_global_limit_and_parse_checkpoints(tmp_path, monkeypatch):
    source = Path("D:/us-tech-quant/scripts/v22/a2_pit_sec_fundamental_acceleration_alpha_r1.py")
    if not source.exists():
        pytest.skip("Existing SecCache implementation is required for integration regression")
    parser = refresh.load_parser(source)
    calls = []

    class Response:
        status = 200

        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(document("13F-HR", self.url.split("/")[-1])).encode()

    def urlopen(request, timeout):
        assert timeout == 20
        calls.append(time.monotonic())
        return Response(request.full_url)

    monkeypatch.setattr(parser.urllib.request, "urlopen", urlopen)
    cache = parser.SecCache(tmp_path / "raw", "synthetic test contact")
    facts, disclosures, statuses, reason, execution = refresh.collect_parallel(
        parser, cache, [1, 2, 3, 4], "2026-08-22", "2026-09-11", 30, 4)
    assert reason == "COMPLETE_CIK_SCAN"
    assert len(calls) == 4
    assert all(second - first >= 0.19 for first, second in zip(calls, calls[1:]))
    assert statuses.submissions_status.eq("PARSED").all()
    assert len(disclosures) == 4 and facts.empty
    _, _, _, _, resumed = refresh.collect_parallel(parser, cache, [1, 2, 3, 4], "2026-08-22", "2026-09-11", 30, 4)
    assert resumed["parsed_checkpoint_hits"] == 4
    assert len(calls) == 4
    seeded = {cik: (facts, disclosures.loc[disclosures.cik.eq(cik)], statuses.loc[statuses.cik.eq(cik)]) for cik in [1, 2, 3, 4]}
    def forbidden_cache(*args):
        raise AssertionError("Previously parsed CIKs must not initialize a cache worker or decode JSON again")
    monkeypatch.setattr(parser, "SecCache", forbidden_cache)
    _, _, _, _, reused = refresh.collect_parallel(parser, cache, [1, 2, 3, 4], "2026-08-22", "2026-09-11", 30, 4, seeded=seeded)
    assert reused["parsed_checkpoint_hits"] == 4



def test_acceptance_exception_supplement_preserves_timestamp_source_and_window(tmp_path):
    import pandas as pd
    import hashlib
    database = tmp_path / "source.sqlite"
    doc = document("424B2", "a")
    doc["filings"]["recent"]["filingDate"] = ["2026-08-24"]
    doc["filings"]["recent"]["acceptanceDateTime"] = ["2026-08-21T21:42:53Z"]
    payload = json.dumps(doc).encode()
    digest = hashlib.sha256(payload).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE responses (url TEXT,status INTEGER,body_zlib BLOB,sha256 TEXT,fetched_utc TEXT)")
        connection.execute("INSERT INTO responses VALUES (?,?,?,?,?)", (sub_url(1), 200, zlib.compress(payload), digest, "2026-09-13T00:00:00Z"))
    index = pd.DataFrame([{"cik": 1, "accession": "a", "filed_date": "2026-08-24"}])
    window_rows = refresh.disclosure_rows(doc, 1, "2026-08-22", "2026-09-11", {})
    assert window_rows == []
    audited, _ = refresh.audit_index_window(index, pd.DataFrame(), database, "2026-08-22", "2026-09-11")
    result, manifest_identity = refresh.save_acceptance_exceptions(audited, database, tmp_path, "2026-08-22", "2026-09-11")
    frame = pd.read_parquet(result["path"])
    assert len(frame) == 1
    assert frame.accepted_at.iloc[0] == pd.Timestamp("2026-08-21T21:42:53Z")
    assert frame.source_sha256.iloc[0] == digest
    assert frame.source_url.iloc[0] == sub_url(1)
    assert frame.exception_reason.iloc[0] == "INDEXED_IN_WINDOW_ACCEPTED_BEFORE_WINDOW"
    manifest = json.loads(Path(manifest_identity["path"]).read_text(encoding="utf-8"))
    assert manifest["files"]["submissions"]["sha256"] == result["sha256"]
    assert manifest["no_new_network_requests"] is True
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE responses SET sha256=?", ("0" * 64,))
    with pytest.raises(ValueError, match="source hash mismatch"):
        refresh.acceptance_exceptions(audited, database, "2026-08-22", "2026-09-11")
