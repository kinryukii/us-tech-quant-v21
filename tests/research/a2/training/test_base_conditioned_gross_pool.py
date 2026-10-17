"""Synthetic boundary and source-access tests; no real holdings or fitting."""
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.research.a2.training import base_conditioned_gross_pool as pool


def package(tmp_path, label="2024_sep_nov", dates=("16-SEP-2024", "15-NOV-2024")):
    filename = ("01sep2024-30nov2024_form13f.zip" if label == "2024_sep_nov"
                else "01jun2024-31aug2024_form13f.zip")
    n = len(dates)
    table = pa.table(dict(ACCESSION_NUMBER=["past" if i == 0 else "future" for i in range(n)],
        FILING_DATE=list(dates), SUBMISSIONTYPE=["13F-HR/A"] * n, CIK=["0001603466"] * n,
        PERIODOFREPORT=["30-JUN-2024"] * n))
    pq.write_table(table, tmp_path / (label + "_submission.parquet"))
    pq.write_table(pa.table({c: ["NO_HOLDING_ACCESS"] for c in pool.inputs.INFO_COLUMNS}),
                   tmp_path / (label + "_infotable.parquet"))
    path = tmp_path / (label + "_meta.json")
    path.write_text(json.dumps(dict(label=label, filename=filename,
        url="https://www.sec.gov/files/structureddata/data/form-13f-data-sets/" + filename,
        submission_rows=n, infotable_rows=1)), encoding="utf-8")
    return path


def test_mixed_archive_pushes_clock_filter_before_metadata_read_and_never_reads_holdings(tmp_path, monkeypatch):
    path = package(tmp_path)
    original = pq.read_table
    calls = []
    def guarded(source, *args, **kwargs):
        assert "_submission.parquet" in str(source)
        assert kwargs["columns"] == pool.inputs.SUB_COLUMNS
        assert kwargs["filters"][0][:2] == ("FILING_DATE", "in")
        assert "16-SEP-2024" in kwargs["filters"][0][2]
        assert "15-NOV-2024" not in kwargs["filters"][0][2]
        calls.append(str(source))
        return original(source, *args, **kwargs)
    monkeypatch.setattr(pq, "read_table", guarded)
    frame, receipt = pool.submission_metadata(path)
    assert frame.ACCESSION_NUMBER.tolist() == ["past"]
    assert frame.accepted_at.isna().all()
    assert len(calls) == 1 and not receipt["holding_values_read"]
    assert not receipt["acceptance_certified"]
    assert receipt["infotable_footer"]["hash_deferred_until_holdings_authorization"]


def test_finite_package_unknown_encoding_cannot_silently_drop_a_filing(tmp_path):
    path = package(tmp_path, "2024_jun_aug", dates=("2024/08/19",))
    with pytest.raises(ValueError, match="DATE_PREDICATE_LOST_FINITE_METADATA"):
        pool.submission_metadata(path)


def test_future_package_rejected_before_parquet_open(tmp_path, monkeypatch):
    path = tmp_path / "future_meta.json"
    path.write_text(json.dumps(dict(label="future", filename="2025q1_form13f.zip")), encoding="utf-8")
    monkeypatch.setattr(pq, "ParquetFile", lambda *_: pytest.fail("future source opened"))
    with pytest.raises(ValueError, match="PACKAGE_OUTSIDE_HISTORY"):
        pool.submission_metadata(path)


@pytest.mark.parametrize("accepted,reason", [(None, "ACTUAL_ACCEPTANCE"),
    ("2024-10-07T04:00:00Z", "FUTURE_FILING"),
    ("2024-09-16T20:00:00Z", "LOCAL_SOURCE_AND_COVER")])
def test_qualification_blocks_holdings_callback_before_access(accepted, reason):
    frame = pd.DataFrame([dict(accepted_at=accepted, filed_date="2024-09-16")])
    with pytest.raises(ValueError, match=reason):
        pool.load_records(frame, lambda *_: pytest.fail("holdings loader invoked"))


def test_historical_projection_rejects_exposed_window_before_owner_call(monkeypatch):
    monkeypatch.setattr(pool.projection, "project_universe", lambda *_args, **_kwargs:
                        pytest.fail("projection owner invoked for forbidden dates"))
    with pytest.raises(ValueError, match="HISTORICAL_CONTROLLER_WINDOW"):
        pool.project_history(None, None, None, ["2026-01-02"])

@pytest.mark.parametrize("accepted", ["2024-09-16T20:00:00", "not-a-clock"])
def test_naive_or_invalid_clock_cannot_be_promoted_to_actual_utc(accepted):
    frame = pd.DataFrame([dict(accepted_at=accepted, filed_date="2024-09-16")])
    with pytest.raises(ValueError):
        pool.load_records(frame, lambda *_: pytest.fail("holdings loader invoked"))


def test_isolated_projector_revokes_invalid_revision_and_selects_latest_complete_quarter():
    rows = [dict(snapshot_id="q3bad", quarter="2023Q3", effective_at="2023-11-24T14:30:00Z", revision=1,
                 institution_count=24, source_status="UNQUALIFIED", error="CONFIDENTIAL"),
            dict(snapshot_id="q4", quarter="2023Q4", effective_at="2024-02-22T14:30:00Z", revision=0,
                 institution_count=24, source_status="QUALIFIED_RESEARCH_SOURCE", error=None),
            dict(snapshot_id="q1", quarter="2024Q1", effective_at="2024-05-22T13:30:00Z", revision=0,
                 institution_count=24, source_status="QUALIFIED_RESEARCH_SOURCE", error=None),
            dict(snapshot_id="q3late", quarter="2023Q3", effective_at="2024-05-22T13:30:00Z", revision=2,
                 institution_count=24, source_status="UNQUALIFIED", error="CONFIDENTIAL"),
            dict(snapshot_id="q1bad", quarter="2024Q1", effective_at="2024-05-31T13:30:00Z", revision=1,
                 institution_count=24, source_status="UNQUALIFIED", error="COLLISION"),
            dict(snapshot_id="q2", quarter="2024Q2", effective_at="2024-08-21T13:30:00Z", revision=0,
                 institution_count=24, source_status="QUALIFIED_RESEARCH_SOURCE", error=None)]
    states = pd.DataFrame(rows)
    states.effective_at = pd.to_datetime(states.effective_at)
    members = pd.DataFrame([dict(snapshot_id=sid, cusip=f"{i:09d}", consensus_rank=i,
        manager_count=3, holding_weight_sum_exact="1/24")
        for sid in ("q4", "q1", "q2") for i in range(1, 101)])
    dates = pd.to_datetime(["2024-01-02", "2024-02-22", "2024-05-23", "2024-05-31", "2024-08-21"])
    identity = pd.DataFrame(dict(signal_date=pd.Series([], dtype="datetime64[ns]"),
                                cusip=pd.Series([], dtype=object), ticker=pd.Series([], dtype=object),
                                security_id=pd.Series([], dtype=object)))
    receipt = dict(task_id=pool.TASK, status="QUALIFIED_RESEARCH_SOURCE_WITH_EXPLICIT_REJECTIONS",
        policy="LATEST_COMPLETE_PUBLIC_EFFECTIVE_QUARTER_WITH_ASOF_AMENDMENTS",
        cutoff_exclusive="2024-10-07", strict_apply_unchanged=True,
        state_census_sha256=pool.frame_sha(states), members_sha256=pool.frame_sha(members))
    old_fn = pool.projection.project_universe
    old_authority = old_fn.__globals__["authority"]
    output = pool.project_history(states, members, identity, dates, source_receipt=receipt)
    selected = output["schedule"].set_index("effective_date").quarter.to_dict()
    assert selected == {"2024-02-22":"2023Q4", "2024-05-23":"2024Q1",
                        "2024-05-31":"2023Q4", "2024-08-21":"2024Q2"}
    assert output["source_daily_ledger"].iloc[0].source_status == "SOURCE_UNQUALIFIED"
    assert output["schedule"].universe_id.eq(pool.TASK).all()
    assert pool.projection.project_universe is old_fn
    assert old_fn.__globals__["authority"] is old_authority
    assert output["projector_routing"]["code_sha256"] == pool.PROJECTOR_CODE_SHA
    broken = members.copy(); broken.loc[0, "manager_count"] = 5
    with pytest.raises(ValueError, match="SOURCE_CONTENT_CHANGED"):
        pool.project_history(states, broken, identity, dates, source_receipt=receipt)
