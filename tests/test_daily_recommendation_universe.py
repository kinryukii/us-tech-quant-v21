"""Bounded synthetic tests for current 13F intake and identity gating."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append("D:/us-tech-quant")
SPEC = importlib.util.spec_from_file_location("current_13f_under_test", ROOT / "scripts/daily_recommendation_universe.py")
u = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(u)


def holding(cusip, value=10):
    return {"cusip": cusip, "issuer_name": cusip, "title_of_class": "COM", "put_call": "",
            "value_usd": value, "share_type": "SH"}


def filing(accession, form="13F-HR", accepted="2026-08-14T20:00:00+00:00"):
    return {"accession": accession, "manager_id": "manager", "manager_name": "Manager", "manager_weight": 1,
            "quarter": "2026Q2", "form": form, "accepted_at": accepted}


def identity(cusip, ticker, **changes):
    return {"cusip": cusip, "ticker": ticker, "moomoo_transport_code": f"US.{ticker}",
            "mapping_status": "RESOLVED", "transport_static_validated": True,
            "transport_alias_status": "VALIDATED", "transport_interval_status": "VALIDATED",
            "mapping_source": "EXISTING_VALIDATED_CUSIP", **changes}


class CurrentUniverseTests(unittest.TestCase):
    def test_primary_identity_requires_exact_security_declaration(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(u, "configured_user_agent", return_value="test-contact"), patch.object(u.time, "sleep"), patch.object(u.requests, "get") as get:
            get.return_value = Mock(status_code=200, content=b"unrelated", text="TEL is a ticker, without the required CUSIP")
            paths = SimpleNamespace(repo_root=Path(temporary))
            self.assertFalse(u._primary_identity_candidates(paths, ["G87052109"], Path(temporary)))

    def test_exact_us_mapping_rejects_multiple_share_classes(self):
        base = {"exchCode": "US", "marketSector": "Equity", "securityType": "Common Stock",
                "ticker": "AAA", "compositeFIGI": "COMPOSITE1", "shareClassFIGI": "CLASS1"}
        accepted = u._exact_us_composite({"response": {"data": [base]}}, lambda x: True)
        self.assertEqual(accepted, base)
        self.assertIsNone(u._exact_us_composite({"response": {"data": [base, {**base, "shareClassFIGI": "CLASS2"}]}}, lambda x: True))

    def test_exact_mapping_never_infers_us_from_missing_exchange(self):
        record = {"response": {"data": [{"exchCode": "", "marketSector": "Equity", "ticker": "AAA",
                                           "compositeFIGI": "F1", "shareClassFIGI": "C1"}]}}
        self.assertIsNone(u._exact_us_composite(record, lambda x: True))

    def test_restatement_replaces_old_holdings(self):
        records = [(filing("initial"), [holding("OLD")], {}),
                   (filing("amended", "13F-HR/A", "2026-09-01T20:00:00+00:00"),
                    [holding("NEW")], {"amendment_type": "RESTATEMENT"})]
        raw, latest = u._apply_filings(records)
        self.assertEqual(raw.cusip.tolist(), ["NEW"])
        self.assertEqual(latest.accession.tolist(), ["amended"])

    def test_add_new_holdings_cannot_silently_overlap(self):
        records = [(filing("initial"), [holding("OLD")], {}),
                   (filing("amended", "13F-HR/A", "2026-09-01T20:00:00+00:00"),
                    [holding("OLD")], {"amendment_type": "NEW HOLDINGS"})]
        with self.assertRaisesRegex(ValueError, "COLLISION"):
            u._apply_filings(records)

    def test_amendment_without_initial_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "WITHOUT_INITIAL"):
            u._apply_filings([(filing("amended", "13F-HR/A"), [holding("NEW")], {"amendment_type": "RESTATEMENT"})])

    def test_omitted_confidential_holdings_are_incomplete(self):
        with self.assertRaisesRegex(ValueError, "CONFIDENTIAL"):
            u._apply_filings([(filing("initial"), [holding("NEW")], {"confidential_omitted": "true"})])

    def test_mapping_requires_existing_validated_transport_and_reports_unknown(self):
        pool = pd.DataFrame([{"cusip": "ONE"}, {"cusip": "TWO"}, {"cusip": "NEW"}])
        identities = pd.DataFrame([identity("ONE", "AAA"), identity("TWO", "BBB", transport_static_validated=False)])
        members, gaps = u._map_universe(pool, identities)
        self.assertEqual([row["ticker"] for row in members], ["AAA"])
        self.assertEqual({row["cusip"] for row in gaps}, {"TWO", "NEW"})

    def test_all_simultaneous_symbol_collisions_are_quarantined(self):
        pool = pd.DataFrame([{"cusip": "ONE"}, {"cusip": "TWO"}])
        members, gaps = u._map_universe(pool, pd.DataFrame([identity("ONE", "AAA"), identity("TWO", "AAA")]))
        self.assertFalse(members)
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(row["reason"] == "SIMULTANEOUS_IDENTITY_COLLISION" for row in gaps))

    def test_rejected_identity_cannot_pass_static_validation(self):
        pool = pd.DataFrame([{"cusip": "ONE"}])
        members, gaps = u._map_universe(pool, pd.DataFrame([identity("ONE", "AAA", transport_interval_status="QUARANTINE")]))
        self.assertFalse(members)
        self.assertEqual(len(gaps), 1)

    def test_missing_registry_returns_waiting_never_a_stale_pool(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = SimpleNamespace(data_root=Path(temporary), cache_root=Path(temporary), repo_root=Path(temporary))
            result = u.refresh_universe(paths, "2026-09-22", Path(temporary) / "run", execute=False)
            self.assertFalse(result["current"])
            self.assertFalse(result["members"])
            self.assertEqual(result["status"], "WAITING_DATA")
            self.assertIn("13F_REFRESH_FAILED", result["reason"])
            self.assertTrue(Path(result["report_path"]).exists())

    def test_submissions_include_amendments_and_skip_future_acceptance(self):
        manager = {"manager_id": "manager", "manager_name": "Manager", "manager_weight": 1,
                   "required_for_gate": True, "cik": 1}
        document = {"cik": 1, "filings": {"recent": {
            "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002", "0000000001-26-000003"],
            "form": ["13F-HR", "13F-HR/A", "13F-HR/A"], "reportDate": ["2026-06-30"] * 3,
            "filingDate": ["2026-08-14", "2026-09-01", "2026-09-25"],
            "acceptanceDateTime": ["2026-08-14T20:00:00Z", "2026-09-01T20:00:00Z", "2026-09-25T20:00:00Z"]}}}
        reader = Mock()
        records = u._submission_records(manager, document, reader, "2026-06-30", pd.Timestamp("2026-09-23T00:00:00Z"))
        self.assertEqual([row["form"] for row in records], ["13F-HR", "13F-HR/A"])
        reader.get.assert_not_called()

    def test_sec_denial_stops_without_alternative_hosts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(u.requests, "Session") as session, patch.object(u.time, "sleep"):
            response = Mock(status_code=403, content=b"denied")
            session.return_value.get.return_value = response
            reader = u._SecReader(Path(temporary), "synthetic-contact")
            with self.assertRaisesRegex(ValueError, "13F_SEC_HTTP_403"):
                reader.get("https://data.sec.gov/submissions/CIK0000000001.json")
            session.return_value.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()


@pytest.fixture
def identity_evidence(tmp_path):
    paths = SimpleNamespace(daily_root=tmp_path / "daily", cache_root=tmp_path / "cache")
    refs = {}
    for name in ("registry", "identity_source"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        refs[name] = {"path": str(path), "sha256": u._hash(path)}
    context = {**refs, "quarter": "2026Q2", "target_date": "2026-09-22",
               "latest_disclosures_checked_at": "2026-09-23T09:30:00+00:00"}
    pool = pd.DataFrame([{"cusip": value, "issuer_name": value, "effective_date": "2026-09-10"}
                         for value in ("CUSIP0001", "CUSIP0002", "CUSIP0003")])
    def make_run(name, values, *, failed=(), observed="2026-09-23T08:55:00+00:00"):
        root = paths.daily_root / name / "universe_refresh"
        root.mkdir(parents=True)
        cache, rows, members, static = {}, [], [], []
        for cusip, ticker in values.items():
            exact = {"ticker": ticker, "figi": "FIGI" + cusip, "compositeFIGI": "COMP" + cusip,
                     "shareClassFIGI": "CLASS" + cusip, "exchCode": "US", "marketSector": "Equity", "securityType": "Common Stock"}
            cache[cusip] = {"query": {"idType": "ID_CUSIP", "idValue": cusip}, "status": "PASS", "response": {"data": [exact]}}
            rows.append(identity(cusip, ticker, composite_figi=exact["compositeFIGI"], share_class_figi=exact["shareClassFIGI"],
                                 identity_observed_at=observed, mapping_source="OPENFIGI_ID_CUSIP_CURRENT_US_COMPOSITE_PLUS_MOOMOO_STATIC"))
            members.append({"security_id": cusip, "ticker": ticker, "moomoo_symbol": "US." + ticker,
                            "moomoo_transport_code": "US." + ticker, "mapping_source": "VERIFIED_TEST"})
            static.append({"moomoo_transport_code": "US." + ticker, "request_status": "PASS", "direct_static_hit": True, "request_error": ""})
        for cusip in failed:
            cache[cusip] = {"query": {"idType": "ID_CUSIP", "idValue": cusip}, "status": "NETWORK_FAILED", "response": {}, "error": "connect timeout"}
        u._save(root / "openfigi_exact_cusip.json", cache)
        pd.DataFrame(rows).to_parquet(root / "identity_overlay.parquet", index=False)
        pd.DataFrame(members).to_parquet(root / "mapped_members.parquet", index=False)
        pd.DataFrame(static).to_parquet(root / "identity_transport_validation.parquet", index=False)
        pool.to_parquet(root / "quarter_universe.parquet", index=False)
        gaps = [{"cusip": value, "reason": "NO_EXISTING_CUSIP_MAPPING"} for value in pool.cusip if value not in values]
        report = {**context, "latest_disclosures_checked_at": observed, "status": "READY", "current": True,
                  "inference_ready": True, "report_path": str(root / "universe_report.json"), "members": members,
                  "universe_member_count": len(pool), "mapped_member_count": len(members), "mapping_gaps": gaps,
                  "mapping_gap_count": len(gaps), "universe_manifest_sha256": u._hash(root / "quarter_universe.parquet"),
                  "universe_members_sha256": u._hash(root / "mapped_members.parquet"),
                  "identity_completion": {"raw_evidence_sha256": u._hash(root / "openfigi_exact_cusip.json")}}
        u._save(root / "universe_report.json", report)
        return root, report
    old, report = make_run("old", {"CUSIP0001": "AAA", "CUSIP0002": "NEWCODE", "CUSIP0003": "CCC"})
    return SimpleNamespace(paths=paths, context=context, pool=pool, old=old, report=report, make_run=make_run)


def test_network_failure_reuses_bound_positive_identity_without_network(identity_evidence, monkeypatch):
    e = identity_evidence
    current, _ = e.make_run("current", {"CUSIP0001": "AAA", "CUSIP0002": "OLDCODE"},
                            failed=("CUSIP0002", "CUSIP0003"), observed=e.context["latest_disclosures_checked_at"])
    monkeypatch.setattr(u.requests, "get", lambda *a, **kw: pytest.fail("offline reuse must not request"))
    result = u._prior_identity_evidence(e.paths, e.pool, current, e.context, prior_reports=[e.old / "universe_report.json"])
    assert result["overlay"]["CUSIP0002"]["ticker"] == "NEWCODE"
    assert result["overlay"]["CUSIP0003"]["ticker"] == "CCC"
    assert result["sources"][0]["report"]["sha256"] == u._hash(e.old / "universe_report.json")
    assert result["issues"] == []


@pytest.mark.parametrize("kind", ["contradiction", "negative_response", "static_rejection"])
def test_current_success_conflict_or_rejection_is_never_overwritten(identity_evidence, kind):
    e = identity_evidence
    current, _ = e.make_run("current", {"CUSIP0001": "AAA"}, observed=e.context["latest_disclosures_checked_at"])
    path = current / "openfigi_exact_cusip.json"
    cache = json.loads(path.read_text())
    if kind == "contradiction": cache["CUSIP0001"]["response"]["data"][0]["ticker"] = "DIFFERENT"
    elif kind == "negative_response": cache["CUSIP0001"]["response"] = {"error": "No identifier found"}
    else:
        frame = pd.read_parquet(current / "identity_transport_validation.parquet")
        frame["direct_static_hit"] = False
        frame.to_parquet(current / "identity_transport_validation.parquet", index=False)
    u._save(path, cache)
    result = u._prior_identity_evidence(e.paths, e.pool, current, e.context, prior_reports=[e.old / "universe_report.json"])
    assert "CUSIP0001" not in result["openfigi"] and "CUSIP0001" not in result["overlay"]


def test_changed_base_registry_and_historical_target_are_not_reused(identity_evidence):
    e = identity_evidence
    current = e.paths.daily_root / "new"
    changed = {**e.context, "identity_source": {**e.context["identity_source"], "sha256": "f" * 64}}
    assert not u._prior_identity_evidence(e.paths, e.pool, current, changed, prior_reports=[e.old / "universe_report.json"])["overlay"]
    historical = {**e.context, "latest_disclosures_checked_at": "2026-09-01T00:00:00+00:00", "target_date": "2026-08-31"}
    assert not u._prior_identity_evidence(e.paths, e.pool, current, historical, prior_reports=[e.old / "universe_report.json"])["openfigi"]


def test_next_day_seeds_exact_identity_but_requires_fresh_transport_validation(identity_evidence):
    e = identity_evidence
    later = {**e.context, "latest_disclosures_checked_at": "2026-09-24T09:30:00+00:00", "target_date": "2026-09-23"}
    result = u._prior_identity_evidence(e.paths, e.pool, e.paths.daily_root / "new", later, prior_reports=[e.old / "universe_report.json"])
    assert len(result["openfigi"]) == 3 and result["overlay"] == {} and result["validation"] == {}


@pytest.mark.parametrize("artifact", ["openfigi_exact_cusip.json", "mapped_members.parquet"])
def test_changed_prior_bound_artifact_is_rejected(identity_evidence, artifact):
    e = identity_evidence
    (e.old / artifact).write_bytes(b"tampered")
    result = u._prior_identity_evidence(e.paths, e.pool, e.paths.daily_root / "new", e.context, prior_reports=[e.old / "universe_report.json"])
    assert result["openfigi"] == {} and result["issues"]


def test_only_current_pool_members_enter_reused_identity(identity_evidence):
    e = identity_evidence
    result = u._prior_identity_evidence(e.paths, e.pool.iloc[:1], e.paths.daily_root / "new", e.context, prior_reports=[e.old / "universe_report.json"])
    assert set(result["overlay"]) == {"CUSIP0001"}


def test_shared_report_reference_cache_pins_hash_and_detects_later_report_change(identity_evidence):
    e = identity_evidence
    u._remember_identity_report(e.paths, e.old / "universe_report.json")
    assert len(u._identity_report_references(e.paths, e.paths.daily_root / "new")) == 1
    (e.old / "universe_report.json").write_text("{}")
    result = u._prior_identity_evidence(e.paths, e.pool, e.paths.daily_root / "new", e.context)
    assert result["overlay"] == {} and result["issues"]


def test_offline_recovery_preserves_source_runs_and_corrects_only_failed_identities(identity_evidence, monkeypatch):
    e = identity_evidence
    current, report = e.make_run("current", {"CUSIP0001": "AAA", "CUSIP0002": "OLDCODE"},
                                failed=("CUSIP0002", "CUSIP0003"), observed=e.context["latest_disclosures_checked_at"])
    catalog = e.paths.cache_root / "derived/data_catalog/catalog.sqlite3"
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as conn:
        conn.execute("CREATE TABLE data_files(dataset TEXT,path TEXT,source_sha256 TEXT,is_current INTEGER)")
        conn.execute("INSERT INTO data_files VALUES('13f_identity',?,?,1)", (report["identity_source"]["path"], report["identity_source"]["sha256"]))
    before = {str(path): path.read_bytes() for path in list(current.iterdir()) + list(e.old.iterdir()) if path.is_file()}
    monkeypatch.setattr(u.requests, "get", lambda *a, **kw: pytest.fail("No network in recovery"))
    monkeypatch.setattr(u.requests, "post", lambda *a, **kw: pytest.fail("No network in recovery"))
    result = u.recover_current_identity(e.paths, current / "universe_report.json", [e.old / "universe_report.json"], e.paths.daily_root / "recovery")
    assert result["mapped_member_count"] == 3 and result["mapping_gap_count"] == 0
    assert result["identity_recovery"]["added_cusips"] == ["CUSIP0003"]
    assert result["identity_recovery"]["corrected_cusips"] == ["CUSIP0002"]
    assert result["identity_recovery"]["reused_cusips"] == ["CUSIP0002", "CUSIP0003"]
    assert all(Path(path).read_bytes() == content for path, content in before.items())
    assert result["identity_recovery"]["network_requests"] == 0
    assert not (e.paths.daily_root / "A2_today_recommendation/current_universe.json").exists()


def test_complete_same_day_all_cached_members_needs_no_live_enrichment(identity_evidence, monkeypatch):
    e = identity_evidence
    u._remember_identity_report(e.paths, e.old / "universe_report.json")
    root = e.paths.daily_root / "new"
    root.mkdir()
    monkeypatch.setattr(u, "import_source", lambda *a, **kw: pytest.fail("Fully verified same-day pool needs no helper/network"))
    base = pd.DataFrame([identity("UNRELATED", "OUTSIDE")])
    completed, summary = u.complete_identity_mapping(e.paths, e.pool, base, root, context=e.context)
    members, gaps = u._map_universe(e.pool, completed)
    assert len(members) == 3 and not gaps and summary["requested"] == 0
    assert summary["reused_verified_same_day"] == 3 and summary["prior_evidence_sources"]
    assert (root / "identity_overlay.parquet").exists() and (root / "identity_transport_validation.parquet").exists()


def test_bad_reference_index_does_not_hide_a_separately_verified_last_run(identity_evidence):
    e = identity_evidence
    index = u._identity_cache_path(e.paths)
    index.parent.mkdir(parents=True)
    index.write_text("invalid json")
    pointer = e.paths.daily_root / "A2_today_recommendation/current_universe.json"
    pointer.parent.mkdir(parents=True)
    u._save(pointer, e.report)
    result = u._prior_identity_evidence(e.paths, e.pool, e.paths.daily_root / "new", e.context)
    assert len(result["overlay"]) == 3 and result["issues"]
    u._remember_identity_report(e.paths, e.old / "universe_report.json")
    assert index.read_text() == "invalid json"


def test_verified_interval_requires_asof_and_is_propagated():
    pool = pd.DataFrame([holding("NEWCUSIP")])
    mapped = pd.DataFrame([identity("NEWCUSIP", "NEW", identity_valid_from="2026-09-22", identity_valid_to="2026-12-31")])
    for day in (None, "2026-09-21", "2027-01-01"):
        rows, gaps = u._map_universe(pool, mapped, as_of=day)
        assert not rows and gaps[0]["reason"] == "IDENTITY_OUTSIDE_VERIFIED_INTERVAL"
    rows, gaps = u._map_universe(pool, mapped, as_of="2026-09-22")
    assert not gaps and rows[0]["identity_valid_from"] == "2026-09-22"
    mapped.loc[0, "identity_valid_from"] = "2026-99-99"
    assert u._map_universe(pool, mapped, as_of="2026-09-22")[1][0]["reason"] == "INVALID_IDENTITY_INTERVAL"


def test_alphabet_preferred_cusips_never_use_common_stock_alias():
    pool = pd.DataFrame([holding("02079K404"), holding("02079K602")])
    mapped = pd.DataFrame([identity("02079K404", "GOOGL"), identity("02079K602", "GOOG")])
    rows, gaps = u._map_universe(pool, mapped, as_of="2026-09-22")
    assert not rows and len(gaps) == 2
    assert {row["reason"] for row in gaps} == {"NON_COMMON_STOCK_PREFERRED_DEPOSITARY_SHARES"}


def test_primary_multidocument_receipts_reuse_and_tamper_rejection(tmp_path, monkeypatch):
    spec = {"ticker": "TEST", "identity_valid_from": "2026-09-22", "documents": [
        {"url": "https://www.sec.gov/example-cusip", "required": ["TESTCUSIP", "Ordinary shares"]},
        {"url": "https://www.sec.gov/example-ticker", "required": ["TEST", "Nasdaq"]}]}
    monkeypatch.setitem(u._PRIMARY_IDENTITY, "TESTCUSIP", spec)
    receipts=[]
    for index, doc in enumerate(spec["documents"]):
        raw=tmp_path/f"source{index}.html"; raw.write_text(" ".join(doc["required"]),encoding="utf8")
        receipts.append({"cusip":"TESTCUSIP","url":doc["url"],"status":200,"raw_path":str(raw),"sha256":u._hash(raw)})
    receipt=tmp_path/"primary_identity_evidence.json"; u._save(receipt,{"sources":receipts})
    sha=u._hash(receipt)
    result=u._verified_primary_candidate("TESTCUSIP",receipt,sha)
    assert result["ticker"] == "TEST" and result["identity_valid_from"] == "2026-09-22"
    monkeypatch.setattr(u,"configured_user_agent",lambda *_:"test-contact")
    monkeypatch.setattr(u.requests,"get",lambda *a,**k:pytest.fail("verified documents should be reused"))
    assert u._primary_identity_candidates(SimpleNamespace(repo_root=tmp_path),["TESTCUSIP"],tmp_path)
    (tmp_path/"source1.html").write_text("changed",encoding="utf8")
    with pytest.raises(ValueError,match="HASH_MISMATCH"):
        u._verified_primary_candidate("TESTCUSIP",receipt,sha)


def test_primary_positive_reuse_still_requires_static_hit(identity_evidence, monkeypatch):
    e=identity_evidence
    cusip="CUSIP0001"
    doc=e.old/"primary.html";doc.write_text("CUSIP0001 AAA Ordinary shares",encoding="utf8")
    spec={"ticker":"AAA","identity_valid_from":"2026-09-22","url":"https://www.sec.gov/test","required":[cusip,"AAA","Ordinary shares"]}
    monkeypatch.setitem(u._PRIMARY_IDENTITY,cusip,spec)
    receipt=e.old/"primary_identity_evidence.json"
    u._save(receipt,{"sources":[{"cusip":cusip,"url":spec["url"],"status":200,"raw_path":str(doc),"sha256":u._hash(doc)}]})
    overlay=pd.read_parquet(e.old/"identity_overlay.parquet")
    for key,value in {"mapping_source":"PRIMARY_CUSIP_ORDINARY_SHARE_TICKER_PLUS_MOOMOO_STATIC","identity_evidence_path":str(receipt),"identity_evidence_sha256":u._hash(receipt),"identity_valid_from":"2026-09-22"}.items():
        overlay.loc[overlay.cusip.eq(cusip),key]=value
    overlay.to_parquet(e.old/"identity_overlay.parquet",index=False)
    target=e.paths.daily_root/"new";target.mkdir()
    result=u._prior_identity_evidence(e.paths,e.pool,target,e.context,prior_reports=[e.old/"universe_report.json"])
    assert cusip in result["overlay"]
    pd.DataFrame([{"moomoo_transport_code":"US.AAA","request_status":"PASS","direct_static_hit":False}]).to_parquet(target/"identity_transport_validation.parquet",index=False)
    result=u._prior_identity_evidence(e.paths,e.pool,target,e.context,prior_reports=[e.old/"universe_report.json"])
    assert cusip not in result["overlay"]


def test_primary_candidate_does_not_bypass_static_requirement(tmp_path):
    pool=pd.DataFrame([holding("G2004J103")])
    row=identity("G2004J103","CCL",identity_valid_from="2026-09-22",transport_static_validated=False,
                 mapping_source="PRIMARY_CUSIP_ORDINARY_SHARE_TICKER_PLUS_MOOMOO_STATIC")
    accepted,gaps=u._map_universe(pool,pd.DataFrame([row]),as_of="2026-09-22")
    assert not accepted and gaps[0]["reason"] == "UNVERIFIED_OR_REJECTED_TRANSPORT_MAPPING"



def synthetic_quarter_managers(core_count=23):
    rows = [{"manager_id": f"core{i:02}", "manager_name": f"Core {i}", "cik": str(i+1),
             "enabled": "True", "active_from_quarter": "2020Q1", "active_to_quarter": "",
             "top_n": "100", "protected_top_n": "20", "manager_weight": "1", "required_for_gate": "True"}
            for i in range(core_count)]
    rows.append({**rows[0], "manager_id": "situational_awareness", "cik": "99999", "active_from_quarter": "2024Q4"})
    return pd.DataFrame(rows)


def test_complete_periods_use_own_quarter_roster_not_today_count():
    registry = synthetic_quarter_managers()
    core = registry.manager_id.iloc[:23].tolist()
    initial = pd.DataFrame([{"report_date": "2024-09-30", "manager_id": mid} for mid in core]
                          + [{"report_date": "2024-12-31", "manager_id": mid} for mid in core])
    assert u._complete_reporting_periods(initial, registry) == ["2024-09-30"]
    initial = pd.concat([initial, pd.DataFrame([{"report_date": "2024-12-31", "manager_id": "situational_awareness"}])])
    assert u._complete_reporting_periods(initial, registry) == ["2024-09-30", "2024-12-31"]


def test_same_count_wrong_manager_cannot_activate_and_partial_is_not_hybrid():
    registry = synthetic_quarter_managers()
    initial = pd.DataFrame([{"report_date": "2024-09-30", "manager_id": mid}
                            for mid in registry.manager_id.iloc[:23]])
    initial.loc[0, "manager_id"] = "unregistered_manager"
    assert u._complete_reporting_periods(initial, registry) == []
    assert u._complete_reporting_periods(initial.iloc[1:], registry) == []


def test_future_registry_append_does_not_change_previous_complete_periods():
    registry = synthetic_quarter_managers()
    initial = pd.DataFrame([{"report_date": "2024-09-30", "manager_id": mid}
                            for mid in registry.manager_id.iloc[:23]])
    before = u._complete_reporting_periods(initial, registry)
    later = {**registry.iloc[0].to_dict(), "manager_id": "future_manager", "cik": "88888", "active_from_quarter": "2025Q1"}
    appended = pd.concat([registry, pd.DataFrame([later])], ignore_index=True)
    assert u._complete_reporting_periods(initial, appended) == before


def test_non_quarter_end_cannot_activate_complete_manager_set():
    registry = synthetic_quarter_managers()
    initial = pd.DataFrame([{"report_date": "2024-09-01", "manager_id": mid}
                            for mid in registry.manager_id.iloc[:23]])
    with pytest.raises(ValueError, match="REPORT_DATE_NOT_QUARTER_END"):
        u._complete_reporting_periods(initial, registry)


@pytest.fixture
def transport_evidence(tmp_path, monkeypatch):
    from scripts.research.a2.inference.current_native_prices import REVIEWED_TRANSPORT_ALIASES
    from scripts.storage import refresh_market_data
    aliases = {ticker: REVIEWED_TRANSPORT_ALIASES[ticker] for ticker in ("BGNE", "BLDE", "BSIG")}
    paths = SimpleNamespace(daily_root=tmp_path / "daily", cache_root=tmp_path / "cache",
        results_root=tmp_path / "results", repo_root=tmp_path / "repo")
    old = paths.daily_root / "old"; old.mkdir(parents=True)
    refs = {}
    for name in ("registry", "identity_source"):
        file = tmp_path / name; file.write_text(name)
        refs[name] = {"path": str(file), "sha256": u._hash(file)}
    observed = pd.Timestamp.now(tz="UTC") + pd.Timedelta(seconds=10)
    context = {**refs, "quarter": "2026Q2", "target_date": "2026-10-02",
        "latest_disclosures_checked_at": "2026-10-02T20:01:00+00:00", "identity_checked_at": observed.isoformat()}
    members = [{"security_id": a["security_id"], "ticker": ticker, "moomoo_symbol": "US." + ticker,
        "moomoo_transport_code": "US." + ticker, "mapping_source": "TEST_EXACT_CUSIP"} for ticker,a in aliases.items()]
    pd.DataFrame(members).to_parquet(old / "mapped_members.parquet",index=False)
    report = {**context, "status":"READY", "current":True, "universe_members_sha256":u._hash(old / "mapped_members.parquet")}
    u._save(old / "universe_report.json",report)
    proof = {"schema":"USTQ_EXISTING_CUSIP_RENAMED_TRANSPORT_PRIMARY_PROOF_V1", "model_fit_calls":0,
        "universe_mutations":0, "observation_as_of":observed.date().isoformat(),
        "old_universe":{"path":str(old / "universe_report.json"),"sha256":u._hash(old / "universe_report.json")},
        "old_member_rows":{r["ticker"]:r for r in members},
        "aliases":[{"ticker":ticker,"provider_symbol":a["source_ticker"],"security_id":a["security_id"],
            "symbol_effective_from":a["symbol_effective_from"],"kind":"SAME_CUSIP_RENAMED_TRANSPORT",
            "urls":[a["evidence_url"],a["identity_evidence_url"]]} for ticker,a in aliases.items()]}
    proof_file=tmp_path / "primary_transport_proof.json";u._save(proof_file,proof)
    reference={"path":str(proof_file),"sha256":u._hash(proof_file)}
    pool=pd.DataFrame([{"cusip":r["security_id"]} for r in members])
    base=pd.DataFrame([identity(r["security_id"],r["ticker"]) for r in members])
    helper_file=paths.results_root / "13f_pit_v1/scripts/v17c/two_gap_closeout_v17c.py"
    helper_file.parent.mkdir(parents=True);helper_file.write_text("synthetic helper")
    calls=[]; rejected=set()
    def validate(codes,*args):
        calls.append(codes)
        return pd.DataFrame([{"moomoo_transport_code":code,"request_status":"PASS",
            "direct_static_hit":code not in rejected,"request_error":""} for code in codes]),1
    helper=SimpleNamespace(validate_transport_codes=validate,
        query_openfigi_exact=lambda *a:pytest.fail("Three transport repairs need no OpenFIGI"),valid_ticker=lambda v:True)
    monkeypatch.setattr(u,"import_source",lambda *a:helper)
    profile=SimpleNamespace(host="127.0.0.1",port=18441)
    monkeypatch.setattr(refresh_market_data,"load_module",lambda *a:SimpleNamespace(load_profile=lambda *a:profile,tcp_probe=lambda *a:(True,"")))
    monkeypatch.setattr(u.requests,"get",lambda *a,**k:pytest.fail("No primary HTTP for reviewed immutable proof"))
    root=paths.daily_root / "new";root.mkdir()
    return SimpleNamespace(paths=paths,old=old,root=root,context=context,pool=pool,base=base,
        proof=proof,reference=reference,aliases=aliases,calls=calls,rejected=rejected)


def test_reviewed_transport_repairs_resolved_old_codes_without_changing_logical_members(transport_evidence):
    e=transport_evidence
    before=e.base.copy(deep=True)
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    members,gaps=u._map_universe(e.pool,completed,as_of=e.context["target_date"])
    assert not gaps and len(members)==3
    assert {r["ticker"]:r["moomoo_symbol"] for r in members}=={t:a["provider_code"] for t,a in e.aliases.items()}
    assert set(completed.cusip)==set(e.base.cusip) and e.base.equals(before)
    assert summary["static_requests"]==1 and summary["openfigi_requests"]==0
    assert summary["transport_repairs_requested"]==3 and summary["unresolved_transport_repairs"]==[]
    assert len(e.calls)==1 and len(e.calls[0])==3


@pytest.mark.parametrize("change",["cusip","code","url","effective","base","old_member","future_observation","future_same_day_datetime"])
def test_reviewed_transport_proof_drift_is_rejected(transport_evidence,change):
    e=transport_evidence
    ticker="BGNE";a=e.aliases[ticker];cid=a["security_id"];code=a["provider_code"]
    proof=json.loads(Path(e.reference["path"]).read_text())
    if change=="cusip":cid="WRONG_CID"
    elif change=="code":code="US.WRONG"
    elif change=="url":proof["aliases"][0]["urls"][0]="https://example.invalid"
    elif change=="effective":proof["aliases"][0]["symbol_effective_from"]="2025-02-02"
    elif change=="base":e.context["quarter"]="2026Q3"
    elif change=="old_member":proof["old_member_rows"][ticker]["security_id"]="WRONG_CID"
    elif change=="future_observation":proof["observation_as_of"]=(pd.Timestamp(e.context["identity_checked_at"])+pd.Timedelta(days=1)).date().isoformat()
    else:proof["observation_as_of"]=(pd.Timestamp(e.context["identity_checked_at"])+pd.Timedelta(minutes=1)).isoformat()
    u._save(Path(e.reference["path"]),proof);e.reference["sha256"]=u._hash(Path(e.reference["path"]))
    with pytest.raises(ValueError):u._reviewed_transport_alias(cid,ticker,code,e.reference,e.context)
    assert not e.calls


def test_reviewed_transport_static_failure_keeps_original_mapping(transport_evidence):
    e=transport_evidence;e.rejected.add("US.ONC")
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    bgne=completed.loc[completed.ticker.eq("BGNE")].iloc[0]
    assert bgne.moomoo_transport_code=="US.BGNE"
    assert summary["unresolved_transport_repairs"]==["07725L102"]


def _finish_transport_report(e,completed,summary):
    members,_=u._map_universe(e.pool,completed,as_of=e.context["target_date"])
    pd.DataFrame(members).to_parquet(e.root/"mapped_members.parquet",index=False)
    report={**e.context,"status":"READY","current":True,"members":members,
        "universe_members_sha256":u._hash(e.root/"mapped_members.parquet"),"identity_completion":summary,
        "identity_artifacts":{key:{"path":str(e.root/name),"sha256":u._hash(e.root/name)}
            for key,name in (("openfigi","openfigi_exact_cusip.json"),("overlay","identity_overlay.parquet"),("validation","identity_transport_validation.parquet"))}}
    u._save(e.root/"universe_report.json",report)


def test_reviewed_transport_next_target_requires_fresh_static_but_no_new_primary_or_figi(transport_evidence):
    e=transport_evidence
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    _finish_transport_report(e,completed,summary)
    same=u._prior_identity_evidence(e.paths,e.pool,e.paths.daily_root/"same",e.context,prior_reports=[e.root/"universe_report.json"])
    assert len(same["overlay"])==3 and len(same["transport_aliases"])==3
    later={**e.context,"target_date":"2026-10-05","identity_checked_at":(pd.Timestamp(e.context["identity_checked_at"])+pd.Timedelta(days=1)).isoformat()}
    newroot=e.paths.daily_root/"later";newroot.mkdir()
    prior=u._prior_identity_evidence(e.paths,e.pool,newroot,later,prior_reports=[e.root/"universe_report.json"])
    assert prior["overlay"]=={} and prior["validation"]=={} and len(prior["transport_aliases"])==3
    u.complete_identity_mapping(e.paths,e.pool,e.base,newroot,context=later,reusable_evidence=prior)
    assert len(e.calls)==2


def test_reviewed_transport_prior_current_static_rejection_is_not_overridden(transport_evidence):
    e=transport_evidence
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    _finish_transport_report(e,completed,summary)
    current=e.paths.daily_root/"reject";current.mkdir()
    pd.DataFrame([{"moomoo_transport_code":"US.ONC","request_status":"PASS","direct_static_hit":False}]).to_parquet(current/"identity_transport_validation.parquet",index=False)
    prior=u._prior_identity_evidence(e.paths,e.pool,current,e.context,prior_reports=[e.root/"universe_report.json"])
    assert "07725L102" not in prior["overlay"] and "07725L102" not in prior["transport_aliases"]


@pytest.mark.parametrize("artifact",["overlay","validation"])
def test_reviewed_transport_prior_requires_explicit_immutable_artifact_refs(transport_evidence,artifact):
    e=transport_evidence
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    _finish_transport_report(e,completed,summary)
    file=e.root/"universe_report.json";report=json.loads(file.read_text());del report["identity_artifacts"][artifact];u._save(file,report)
    prior=u._prior_identity_evidence(e.paths,e.pool,e.paths.daily_root/"later",e.context,prior_reports=[file])
    assert not prior["transport_aliases"] and any("ARTIFACTS_UNBOUND" in r["reason"] for r in prior["issues"])


@pytest.mark.parametrize("artifact",["overlay","validation"])
def test_reviewed_transport_prior_artifact_changed_after_report_is_rejected(transport_evidence,artifact):
    e=transport_evidence
    completed,summary=u.complete_identity_mapping(e.paths,e.pool,e.base,e.root,context=e.context,transport_alias_evidence=e.reference)
    _finish_transport_report(e,completed,summary)
    file=e.root/("identity_overlay.parquet" if artifact=="overlay" else "identity_transport_validation.parquet")
    file.write_bytes(b"altered")
    prior=u._prior_identity_evidence(e.paths,e.pool,e.paths.daily_root/"later",e.context,prior_reports=[e.root/"universe_report.json"])
    assert not prior["transport_aliases"] and any("HASH_MISMATCH" in r["reason"] for r in prior["issues"])


def _clock_fixture(root, *, header_time="20260814160504"):
    accepted = pd.Timestamp(pd.to_datetime(header_time, format="%Y%m%d%H%M%S")).tz_localize("America/New_York").tz_convert("UTC")
    new = accepted.tz_localize(None).tz_localize("America/New_York").tz_convert("UTC")
    accession = "0000000001-26-000001"
    filed = accepted.tz_convert("America/New_York").date().isoformat()
    item = {"manager_id": "manager", "manager_name": "Manager", "cik": 1,
            "accession": accession, "form": "13F-HR", "report_date": "2026-06-30",
            "filed_date": filed, "accepted_at": new.isoformat(),
            "source_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession.replace('-', '')}/{accession}.txt"}
    payload = (f"<SEC-DOCUMENT>\n<SEC-HEADER>\nACCESSION NUMBER: {accession}\n"
               f"<ACCEPTANCE-DATETIME>{header_time}\nCONFORMED SUBMISSION TYPE: 13F-HR\n"
               f"CONFORMED PERIOD OF REPORT: 20260630\nFILED AS OF DATE: {filed.replace('-', '')}\n"
               "CENTRAL INDEX KEY: 1\n</SEC-HEADER>\n<XML><edgarSubmission>"
               "<submissionType>13F-HR</submissionType><periodOfReport>06-30-2026</periodOfReport>"
               "<tableEntryTotal>0</tableEntryTotal><tableValueTotal>0</tableValueTotal>"
               "<isAmendment>false</isAmendment></edgarSubmission></XML>\n</SEC-DOCUMENT>").encode()
    raw = root / "original.txt"; raw.write_bytes(payload)
    observed = "2026-09-14T09:37:55+00:00"
    old = {**item, "accepted_at": accepted.isoformat(), "raw_path": str(raw),
           "source_sha256": u._hash(raw), "observed_at_utc": observed}
    source = {"url": item["source_url"], "http_status": 200, "sha256": u._hash(raw),
              "raw_path": str(raw), "observed_at_utc": observed}
    document = {"verified_filings": [old], "sources": [source]}
    prior = root / "acquisition.json"; prior.write_text(json.dumps(document))
    recent = {"accessionNumber": [accession], "form": [item["form"]],
              "reportDate": [item["report_date"]], "filingDate": [filed],
              "acceptanceDateTime": [new.isoformat()]}
    metadata = root / "current.json"; metadata.write_text(json.dumps({"cik": 1, "filings": {"recent": recent}}))
    current = {"path": str(metadata), "sha256": u._hash(metadata), "url": "https://data.sec.gov/submissions/CIK0000000001.json",
               "status": 200, "observed_at": u.datetime.now(u.timezone.utc).isoformat()}
    return payload, item, {"path": str(prior), "sha256": u._hash(prior)}, current, document


@pytest.mark.parametrize("header_time", ["20260814160504", "20260114160504"])
def test_exact_clock_vintage_reconciliation_keeps_raw_parser_strict(tmp_path, header_time):
    payload, item, prior, current, _ = _clock_fixture(tmp_path, header_time=header_time)
    parser = SimpleNamespace(localname=lambda tag: tag.rsplit("}", 1)[-1].lower(),
                             text_at=lambda root, name: u._xml_field(root, name, False))
    with pytest.raises(ValueError, match="acceptance header disagrees"):
        u._inspect_filing(payload, item, parser)
    corrected, proof = u._reconcile_acceptance(payload, item, prior, current, pd.Timestamp("2026-10-05T20:00:00Z"))
    rows, _ = u._inspect_filing(payload, corrected, parser)
    assert rows == [] and proof["raw_bytes_unchanged"] is True
    assert corrected["accepted_at"] == proof["accepted_at_preserved"]
    assert proof["ordinary_discovery_asof_changed"] is False
    assert proof["prior_acquisition"] == prior and proof["current_submission_metadata"] == current
    assert (pd.Timestamp(item["accepted_at"]) - pd.Timestamp(corrected["accepted_at"])).total_seconds() == (14400 if header_time.startswith("202608") else 18000)


@pytest.mark.parametrize("mutation", ["source_url", "accession", "cik", "manager_id", "manager_name", "form", "report_date", "filed_date",
    "raw_sha", "raw_bytes", "prior_sha", "prior_time", "prior_observed", "prior_request", "missing_prior", "duplicate_prior",
    "time_tolerance", "current_sha", "current_bytes", "current_url", "current_cik", "current_form", "current_time", "missing_current",
    "naive_time", "future_observation", "mtime_is_not_evidence"])
def test_clock_vintage_reconciliation_rejects_unbound_or_changed_evidence(tmp_path, mutation):
    payload, item, prior, current, document = _clock_fixture(tmp_path)
    old = document["verified_filings"][0]
    if mutation in {"source_url", "accession", "manager_id", "manager_name", "form", "report_date", "filed_date"}:
        old[mutation] = "CHANGED"
    elif mutation == "cik": old["cik"] = 2
    elif mutation == "raw_sha": old["source_sha256"] = "0" * 64
    elif mutation == "raw_bytes": Path(old["raw_path"]).write_bytes(payload + b"changed")
    elif mutation == "prior_sha": prior["sha256"] = "0" * 64
    elif mutation == "prior_time": old["accepted_at"] = "2026-08-14T20:05:05Z"
    elif mutation == "prior_observed":
        old["observed_at_utc"] = "2026-10-05T20:00:01Z"; document["sources"][0]["observed_at_utc"] = old["observed_at_utc"]
    elif mutation == "prior_request": document["sources"][0]["sha256"] = "0" * 64
    elif mutation == "missing_prior": document["verified_filings"] = []
    elif mutation == "duplicate_prior": document["verified_filings"].append(dict(old))
    elif mutation == "time_tolerance": item["accepted_at"] = "2026-08-15T00:05:05Z"
    elif mutation == "current_sha": current["sha256"] = "0" * 64
    elif mutation == "current_bytes": Path(current["path"]).write_text("{}")
    elif mutation == "current_url": current["url"] = "https://example.com/current.json"
    elif mutation in {"current_cik", "current_form", "current_time"}:
        metadata = json.loads(Path(current["path"]).read_text())
        if mutation == "current_cik": metadata["cik"] = 2
        elif mutation == "current_form": metadata["filings"]["recent"]["form"][0] = "13F-HR/A"
        else: metadata["filings"]["recent"]["acceptanceDateTime"][0] = "2026-08-15T00:05:05Z"
        Path(current["path"]).write_text(json.dumps(metadata)); current["sha256"] = u._hash(Path(current["path"]))
    elif mutation == "missing_current": current = None
    elif mutation == "naive_time": item["accepted_at"] = "2026-08-15T00:05:04"
    elif mutation == "future_observation": current["observed_at"] = "2030-01-01T00:00:00Z"
    elif mutation == "mtime_is_not_evidence":
        del old["observed_at_utc"]
    Path(prior["path"]).write_text(json.dumps(document))
    if mutation != "prior_sha": prior["sha256"] = u._hash(Path(prior["path"]))
    with pytest.raises((ValueError, KeyError)):
        u._reconcile_acceptance(payload, item, prior, current, pd.Timestamp("2026-10-05T20:00:00Z"))


def test_clock_vintage_correct_time_requires_no_repair(tmp_path):
    payload, item, prior, current, document = _clock_fixture(tmp_path)
    item["accepted_at"] = document["verified_filings"][0]["accepted_at"]
    assert u._reconcile_acceptance(payload, item, prior, None, pd.Timestamp("2026-10-05T20:00:00Z")) == (item, None)


def test_submissions_bind_current_immutable_raw_metadata(tmp_path):
    payload, item, prior, current, _ = _clock_fixture(tmp_path)
    reader = SimpleNamespace(receipts=[{"url": current["url"], "raw_path": current["path"], **{key: current[key] for key in ("sha256", "observed_at", "status")}}])
    manager = {"manager_id": "manager", "manager_name": "Manager", "manager_weight": 1, "required_for_gate": True, "cik": 1}
    records = u._submission_records(manager, json.loads(Path(current["path"]).read_text()), reader, "2026-06-30", pd.Timestamp("2026-10-06T10:00:00Z"))
    assert records[0]["submission_metadata_reference"] == current


def test_clock_vintage_rejects_acceptance_beyond_signal_cutoff(tmp_path):
    payload, item, prior, current, _ = _clock_fixture(tmp_path)
    with pytest.raises(ValueError, match="AFTER_CUTOFF"):
        u._reconcile_acceptance(payload, item, prior, current, pd.Timestamp("2026-08-14T20:05:04Z"))


def test_clock_vintage_rejects_history_response_with_wrong_cik_url(tmp_path):
    payload, item, prior, current, _ = _clock_fixture(tmp_path)
    metadata = json.loads(Path(current["path"]).read_text())
    Path(current["path"]).write_text(json.dumps(metadata["filings"]["recent"]))
    current["sha256"] = u._hash(Path(current["path"]))
    current["url"] = "https://data.sec.gov/submissions/CIK0000000002-submissions-001.json"
    with pytest.raises(ValueError, match="URL_INVALID"):
        u._reconcile_acceptance(payload, item, prior, current, pd.Timestamp("2026-10-05T20:00:00Z"))
