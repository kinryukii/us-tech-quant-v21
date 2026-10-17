"""Synthetic amendment/source adapter checks; no real source files read."""
import pandas as pd
import pytest
from scripts.research.a2.inference.aggregate_13f_source_replay import construct_snapshot


def registry():
    return pd.DataFrame([{"manager_id": manager, "manager_name": manager, "cik": str(index + 1),
        "enabled": True, "active_from_quarter": "2020Q1", "active_to_quarter": "", "top_n": 100,
        "protected_top_n": 20, "manager_weight": 1.0, "required_for_gate": True}
        for index, manager in enumerate(("m1", "m2"))])


def record(manager, cusip, amount, form="13F-HR", amendment="", accepted="2025-11-14T21:00:00Z"):
    filing = {"manager_id": manager, "manager_name": manager, "manager_weight": 1.0,
        "quarter": "2025Q3", "accession": manager + form, "form": form, "accepted_at": accepted}
    row = {"issuer_name": "Synthetic", "title_of_class": "COM", "cusip": cusip,
        "value_usd": str(amount), "share_type": "SH", "put_call": "",
        "original_source_row_id": "1", "original_accession": filing["accession"]}
    return filing, [row], {"amendment_type": amendment, "confidential_omitted": "false"}


def build(records):
    return construct_snapshot(records, registry(), "2025Q3", "s1",
        pd.Timestamp("2025-11-24T14:30:00Z"), pd.Timestamp("2025-11-25T21:00:00Z"),
        lambda *_: (True, "synthetic"), {"sha256": "a" * 64})


def test_restated_whole_table_replaces_initial_then_cross_manager_sum():
    records = [record("m1", "000000001", 50), record("m2", "000000002", 100),
        record("m1", "000000002", 25, "13F-HR/A", "RESTATEMENT", "2025-11-17T21:00:00Z")]
    full, evidence, result, qualification = build(records)
    assert len(full) == 2 and len(evidence) == 2
    assert result["members"].cusip.tolist() == ["000000002"]
    assert str(result["members"].iloc[0].aggregate_value_usd) == "125"
    assert len(qualification[0]["contributing_filings"]) == 2


def test_additional_holdings_keep_initial_and_collision_fails():
    initial = [record("m1", "000000001", 50), record("m2", "000000002", 100)]
    new = record("m1", "000000003", 40, "13F-HR/A", "NEW HOLDINGS", "2025-11-17T21:00:00Z")
    assert len(build(initial + [new])[0]) == 3
    collision = record("m1", "000000001", 40, "13F-HR/A", "NEW HOLDINGS", "2025-11-17T21:00:00Z")
    with pytest.raises(ValueError, match="COLLISION"):
        build(initial + [collision])


def test_missing_initial_and_future_amendment_do_not_enter_snapshot():
    with pytest.raises(ValueError, match="WITHOUT_INITIAL"):
        build([record("m1", "000000001", 50, "13F-HR/A", "RESTATEMENT"), record("m2", "000000002", 100)])
    future = record("m1", "000000003", 50, "13F-HR/A", "RESTATEMENT", "2025-12-01T21:00:00Z")
    with pytest.raises(ValueError, match="FUTURE"):
        build([record("m1", "000000001", 50), record("m2", "000000002", 100), future])


def test_confidential_omission_is_not_asserted_complete():
    records = [record("m1", "000000001", 50), record("m2", "000000002", 100)]
    records[0][2]["confidential_omitted"] = "true"
    with pytest.raises(ValueError, match="CONFIDENTIAL"):
        build(records)


def test_raw_cover_amount_discrepancy_is_preserved_without_rewriting_source(monkeypatch):
    import scripts.research.a2.inference.aggregate_13f_source_replay as source
    filing, rows, _ = record("m1", "000000001", 50)
    details = {"source_value_total_reconciled": False, "detail_minus_cover": "-4"}
    monkeypatch.setattr(source, "load_verified", lambda ref: b"synthetic")
    monkeypatch.setattr(source, "_inspect_filing", lambda *args: (rows, details))
    _, returned_rows, returned_details = source.raw_record(filing, {"path": "synthetic", "sha256": "a" * 64}, None, None, pd.Timestamp("2025-11-25T21:00:00Z"))
    assert returned_rows[0]["value_usd"] == "50"
    assert returned_details["detail_minus_cover"] == "-4"
    assert returned_details["source_value_total_reconciled"] is False