from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest


SOURCE = Path(__file__).parents[1] / "scripts" / "storage" / "restore_sec_data.py"
spec = importlib.util.spec_from_file_location("restore_sec_data_test_source", SOURCE)
sec = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sec
spec.loader.exec_module(sec)


def test_current_facts_retain_taxonomy_unit_and_accession():
    document = {"facts": {"ifrs-full": {"Revenue": {"units": {"EUR": [
        {"accn": "a", "filed": "2025-12-31", "val": 1},
        {"accn": "b", "filed": "2026-09-04", "val": 2},
        {"accn": "c", "filed": "2026-09-05", "val": 3},
    ]}}}}}
    rows = sec.fact_rows(document, 42, "2026-01-01", "2026-09-04", {"source_member": "CIK42.json"})
    assert len(rows) == 1
    assert rows[0]["unit"] == "EUR"
    assert rows[0]["taxonomy"] == "ifrs-full"
    assert rows[0]["accession"] == "b"


def test_acceptance_uses_et_day_boundary_and_preserves_missing():
    document = {"accessionNumber": ["a", "b", "c"], "filingDate": ["2026-09-04"] * 3,
                "acceptanceDateTime": ["2026-09-05T03:59:59Z", "2026-09-05T04:00:00Z", None],
                "form": ["10-Q", "10-Q/A", "13F-HR"]}
    rows = sec.disclosure_rows(document, 42, "2026-01-01", "2026-09-04", {})
    assert [row["accession"] for row in rows] == ["a", "c"]
    assert rows[1]["acceptance_status"] == "MISSING_ACCEPTANCE"


def test_mixed_ledger_reads_only_mapping_ciks(tmp_path):
    path = tmp_path / "ledger.parquet"
    pd.DataFrame({"record_type": ["CIK_MAPPING", "OUTCOME"], "cik": [42, 99],
                  "prohibited_result": [None, "DO_NOT_READ"]}).to_parquet(path)
    assert sec.read_ciks(path) == [42]


def write_zip(path, documents):
    with zipfile.ZipFile(path, "w") as archive:
        for name, document in documents.items():
            archive.writestr(name, json.dumps(document))


def test_offline_run_lineage_missing_history_idempotence_and_no_research(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text("cik\n42\n99\n", encoding="utf-8")
    parser = tmp_path / "parser.py"
    parser.write_text("raise RuntimeError('research module must not load in current-only mode')\n", encoding="utf-8")
    sub_zip = tmp_path / "submissions.zip"
    fact_zip = tmp_path / "companyfacts.zip"
    write_zip(sub_zip, {"CIK0000000042.json": {"filings": {
        "recent": {"accessionNumber": ["a"], "filingDate": ["2026-08-15"],
                   "acceptanceDateTime": ["2026-08-15T20:15:00Z"], "form": ["10-Q"]},
        "files": [{"name": "missing.json", "filingFrom": "2026-01-01", "filingTo": "2026-02-01"}]}}})
    write_zip(fact_zip, {"CIK0000000042.json": {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"accn": "a", "filed": "2026-08-15", "val": 123},
        {"accn": "unresolved", "filed": "2026-08-15", "val": 999},
    ]}}}}}})
    args = sec.parse_args(["--parser-source", str(parser), "--companyfacts-zip", str(fact_zip),
                          "--submissions-zip", str(sub_zip), "--mapping-file", str(mapping),
                          "--output-root", str(tmp_path / "output"), "--skip-historical"])
    result = sec.run(args)
    assert result["missing_entries"] == 3
    assert result["facts_missing_acceptance"] == 1
    facts = pd.read_parquet(result["files"]["current/companyfacts"]["path"])
    assert facts.source_archive_sha256.eq(sec.sha256_file(fact_zip)).all()
    assert facts.loc[facts.accession.eq("a"), "accepted_at"].notna().all()
    assert sec.run(args)["created_at"] == result["created_at"]
    args.as_of = "2026-09-05"
    with pytest.raises(FileExistsError, match="Different restoration contract"):
        sec.run(args)


def test_conflicting_accession_acceptance_stops(tmp_path):
    sub_zip, fact_zip = tmp_path / "sub.zip", tmp_path / "facts.zip"
    write_zip(sub_zip, {"CIK0000000042.json": {"filings": {"recent": {
        "accessionNumber": ["a", "a"], "filingDate": ["2026-08-15", "2026-08-16"],
        "acceptanceDateTime": ["2026-08-15T20:15:00Z", "2026-08-16T20:15:00Z"]}}}})
    write_zip(fact_zip, {})
    with pytest.raises(ValueError, match="Conflicting acceptance"):
        sec.parse_current(fact_zip, sub_zip, [42], "2026-01-01", "2026-09-04",
                          {"submissions": sec.file_identity(sub_zip), "companyfacts": sec.file_identity(fact_zip)})


def test_historical_delegation_uses_data_functions_only(tmp_path):
    calls = []

    class Parser:
        def read_relevant_bulk_submissions(self, path, ciks):
            calls.append("submissions")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        def read_relevant_bulk_companyfacts(self, path, ciks):
            calls.append("facts")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        def build_feature_states(self, facts, submissions, sessions):
            calls.append("states")
            assert sessions.max() <= pd.Timestamp("2025-12-31")
            return pd.DataFrame(), {"guard": "synthetic"}

        def main(self):
            raise AssertionError("Research execution forbidden")

    frames, metadata = sec.historical_frames(Parser(), tmp_path / "f.zip", tmp_path / "s.zip", [42], None)
    assert calls == ["submissions", "facts", "states"]
    assert len(frames) == 5
    assert metadata["state_lineage"] == {"guard": "synthetic"}


@pytest.mark.parametrize("manifest_kind", ["missing", "wrong_hash"])
def test_existing_states_reject_missing_manifest_or_wrong_hash(tmp_path, manifest_kind):
    states = tmp_path / "states.parquet"
    pd.DataFrame({"cik": [42]}).to_parquet(states, index=False)
    manifest = None
    if manifest_kind == "wrong_hash":
        manifest = tmp_path / "states.json"
        manifest.write_text(json.dumps({"state_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="requires|SHA256"):
        sec.historical_frames(None, tmp_path / "f.zip", tmp_path / "s.zip", [42], None, states, manifest)


def test_existing_states_reuses_only_verified_states_and_keeps_parsers(tmp_path, monkeypatch):
    calls = []

    class Parser:
        def read_relevant_bulk_submissions(self, path, ciks):
            calls.append("submissions")
            return pd.DataFrame({"cik": ciks}), pd.DataFrame({"role": ["submissions"]}), pd.DataFrame({"role": ["submissions"]})

        def read_relevant_bulk_companyfacts(self, path, ciks):
            calls.append("facts")
            return pd.DataFrame({"cik": ciks}), pd.DataFrame({"role": ["facts"]}), pd.DataFrame({"role": ["facts"]})

        def build_feature_states(self, *args):
            raise AssertionError("Hash-verified states must skip only state computation")

    states = tmp_path / "states.parquet"
    expected_frame = pd.DataFrame({"cik": [42], "accession": ["a"], "previous_revenue_yoy": [0.5]})
    expected_frame.to_parquet(states, index=False, compression="zstd")
    manifest = tmp_path / "states.json"
    manifest.write_text(json.dumps({"state_path": str(tmp_path / "original" / "fundamental_feature_states.parquet"), "state_sha256": sec.sha256_file(states),
                                    "state_rows": 1, "lineage_facts": {"guard": "frozen"}}), encoding="utf-8")
    mapping = tmp_path / "mapping.csv"
    mapping.write_text("cik\n42\n", encoding="utf-8")
    parser_source = tmp_path / "parser.py"
    parser_source.write_text("# synthetic pure parser\n", encoding="utf-8")
    facts, submissions = tmp_path / "facts.zip", tmp_path / "submissions.zip"
    write_zip(facts, {})
    write_zip(submissions, {})
    monkeypatch.setattr(sec, "load_parser", lambda path: Parser())
    args = sec.parse_args(["--parser-source", str(parser_source), "--companyfacts-zip", str(facts),
                          "--submissions-zip", str(submissions), "--mapping-file", str(mapping),
                          "--output-root", str(tmp_path / "output"), "--states-file", str(states),
                          "--expected-states-manifest", str(manifest)])
    result = sec.run(args)
    assert calls == ["submissions", "facts"]
    assert result["contract"]["states_file"]["sha256"] == sec.sha256_file(states)
    assert result["historical"]["state_lineage"] == {"guard": "frozen"}
    assert result["historical"]["calendar"]["status"] == "PRESERVED_IN_HASH_VERIFIED_STATES"
    assert result["files"]["historical/fundamental_feature_states"]["frozen_hash_match"] is True
    recovered = pd.read_parquet(result["files"]["historical/fundamental_feature_states"]["path"])
    pd.testing.assert_frame_equal(recovered, expected_frame)
    assert result["files"]["historical/bulk_read_audit"]["rows"] == 2
    assert result["files"]["historical/relevant_zip_index"]["rows"] == 2



def test_disclosure_mixed_formats_and_short_acceptance_array_preserve_window():
    document = {"accessionNumber": ["before", "utc", "offset", "naive", "bad", "absent"],
                "filingDate": ["2026-08-22"] * 6,
                "acceptanceDateTime": ["2026-08-22T03:59:59Z", "2026-08-22T04:00:00Z",
                                       "2026-08-22T00:00:00-04:00", "2026-08-22 04:00:00",
                                       "invalid"]}
    rows = sec.disclosure_rows(document, 42, "2026-08-22", "2026-09-11", {})
    assert [row["accession"] for row in rows] == ["utc", "offset", "naive", "bad", "absent"]
    assert all(row["accepted_at"] == pd.Timestamp("2026-08-22T04:00:00Z") for row in rows[:3])
    assert [row["acceptance_status"] for row in rows[3:]] == ["MISSING_ACCEPTANCE"] * 2
