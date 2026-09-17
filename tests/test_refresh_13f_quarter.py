from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "scripts" / "storage"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location("refresh_13f_quarter_test", SCRIPT_DIR / "refresh_13f_quarter.py")
quarter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quarter)


def managers():
    return pd.DataFrame([{"manager_id": "pershing_square", "manager_name": "Pershing", "cik": "1336528",
                          "enabled": "True", "active_from_quarter": "2020Q1", "active_to_quarter": "",
                          "top_n": "100", "protected_top_n": "20", "manager_weight": "1", "required_for_gate": "True"}])


def test_manager_activation_and_fixed_selection_contract():
    registry = managers()
    assert len(quarter.active_managers(registry, "2026Q2")) == 1
    registry.loc[0, "active_to_quarter"] = "2026Q1"
    assert quarter.active_managers(registry, "2026Q2").empty
    registry.loc[0, "active_to_quarter"] = ""
    registry.loc[0, "top_n"] = "50"
    with pytest.raises(ValueError, match="Top100"):
        quarter.active_managers(registry, "2026Q2")


def test_pershing_alias_is_forward_only_and_filters_amendments(tmp_path):
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for cik, quarter_end in ((1336528, "2026-03-31"), (2026053, "2026-06-30")):
            recent = {"form": ["13F-HR/A", "13F-HR"], "reportDate": [quarter_end] * 2,
                      "accessionNumber": ["amendment", "initial"], "filingDate": ["2026-08-16", "2026-08-14"],
                      "acceptanceDateTime": ["2026-08-16T20:27:06Z", "2026-08-14T20:27:06Z"]}
            archive.writestr(f"CIK{cik:010d}.json", json.dumps({"filings": {"recent": recent}}))
    cohort = quarter.active_managers(managers(), "2026Q2")
    q2 = quarter.filing_plan(path, cohort, "2026Q2", "2026-09-04")
    assert q2.cik.tolist() == [2026053]
    assert q2.accession.tolist() == ["initial"]
    assert q2.identity_evidence_url.iloc[0] == quarter.PERSHING_NOTICE
    q1 = quarter.filing_plan(path, cohort, "2026Q1", "2026-09-04")
    assert q1.cik.tolist() == [1336528]
    early = quarter.filing_plan(path, cohort, "2026Q2", "2026-08-13")
    assert early.status.tolist() == ["MISSING_INITIAL_FILING"]


@pytest.fixture
def real_package():
    path = Path("D:/us-tech-quant-results/13f_pit_v1")
    if not path.exists():
        pytest.skip("External package source required for integration regression")
    parser = quarter.import_source(path / "scripts/build_13f_history.py", "test_13f_xml_source")
    selection = quarter.import_source(path / "scripts/v17b/integrity_rebuild_v17b.py", "test_13f_selection_source")
    return parser, selection


def filing_text(value=1234, count=1):
    return f'''<SEC-DOCUMENT>test
<ACCEPTANCE-DATETIME>20260814162706
ACCESSION NUMBER: 0001172661-26-003790
<XML><edgarSubmission><tableEntryTotal>{count}</tableEntryTotal></edgarSubmission></XML>
<XML><informationTable><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>{value}</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable></informationTable></XML>
'''.encode()


def filing():
    return {"accession": "0001172661-26-003790", "accepted_at": pd.Timestamp("2026-08-14T20:27:06Z"),
            "filed_date": "2026-08-14"}


def test_sec_txt_acceptance_count_and_dollar_scale(real_package):
    parser, _ = real_package
    rows = quarter.parse_sec_txt(filing_text(), filing(), parser)
    assert rows[0]["value_usd"] == 1234
    with pytest.raises(ValueError, match="count mismatch"):
        quarter.parse_sec_txt(filing_text(count=2), filing(), parser)
    bad = filing()
    bad["accepted_at"] = pd.Timestamp("2026-08-14T20:00:00Z")
    with pytest.raises(ValueError, match="disagrees"):
        quarter.parse_sec_txt(filing_text(), bad, parser)


def test_selection_reuses_v17b_and_quarter_gate(real_package):
    parser, selection = real_package
    raw = pd.DataFrame([{"quarter": "2026Q2", "manager_id": "m", "manager_name": "Manager", "manager_weight": 1.0,
                         "accession_key": "a", "cusip": "037833100", "issuer_name": "APPLE INC", "title_of_class": "COM",
                         "reported_value_usd": 1234, "ssh_prnamt_type": "SH", "put_call": ""},
                        {"quarter": "2026Q2", "manager_id": "m", "manager_name": "Manager", "manager_weight": 1.0,
                         "accession_key": "a", "cusip": "037833100", "issuer_name": "APPLE INC", "title_of_class": "COM",
                         "reported_value_usd": 1000, "ssh_prnamt_type": "SH", "put_call": "CALL"}])
    filings = pd.DataFrame([{"quarter": "2026Q2", "filed_date": "2026-08-14", "report_date": "2026-06-30", "required_for_gate": True}])
    selected, universe = quarter.build_quarter(raw, filings, selection, parser)
    assert selected.reported_value_usd.tolist() == [1234]
    assert universe.effective_date.tolist() == ["2026-08-21"]


def test_merge_closes_previous_interval_in_new_copy():
    old = pd.DataFrame([{"quarter": "2026Q1", "cusip": "a", "report_date": "2026-03-31", "effective_date": "2026-05-22", "expiry_date": "", "universe_rank": 1}])
    new = pd.DataFrame([{"quarter": "2026Q2", "cusip": "b", "report_date": "2026-06-30", "effective_date": "2026-08-21", "expiry_date": "", "universe_rank": 1}])
    merged = quarter.merge_history(old, new)
    assert old.expiry_date.iloc[0] == ""
    assert merged.expiry_date.iloc[0] == pd.Timestamp("2026-08-20")
    with pytest.raises(ValueError, match="already exists"):
        quarter.merge_history(old, old)


def test_value_units_follow_filing_date_and_unverified_values_are_null():
    base = pd.DataFrame([{"quarter": "2022Q4", "manager_id": "m", "accession_key": key,
                          "cusip": key, "reported_value_usd": value}
                         for key, value in (("old", 5000.0), ("new", 5000.0), ("bad", 9999.0))])
    raw = base[["quarter", "manager_id", "accession_key", "cusip"]].copy()
    raw["source_reported_value"] = 5.0
    dates = base[["quarter", "manager_id", "accession_key"]].copy()
    dates["filing_date"] = ["2022-12-30", "2023-01-03", "2023-02-15"]
    fixed = quarter.verify_historical_values(base, raw, dates)
    assert fixed.reported_value_usd.iloc[:2].tolist() == [5000.0, 5.0]
    assert pd.isna(fixed.reported_value_usd.iloc[2])
    assert fixed.unit_status.iloc[2] == "UNVERIFIED"
    assert fixed.legacy_reported_value_usd.tolist() == [5000.0, 5000.0, 9999.0]
