"""Targeted temporal and partial-input checks; no research runner imports."""
import hashlib

import numpy as np
import pandas as pd
import pytest

import pit_inputs as p


def samples(days):
    f = pd.DataFrame({"ticker": "TEST", "date": days})
    f["prediction_at_utc"] = (pd.to_datetime(f.date) + pd.Timedelta(hours=9, minutes=25)).dt.tz_localize(p.ET).dt.tz_convert("UTC")
    return f


def inputs():
    intervals = pd.DataFrame([dict(ticker="TEST", effective_start=pd.Timestamp("2024-01-01"),
                                  effective_end=pd.Timestamp("2024-12-31"), security_id="123", cusip="123",
                                  issuer_name="TEST", mapping_status="RESOLVED", institution_support_count=5,
                                  artifact_label="AUTHORITATIVE_PIT_INVESTABLE_UNIVERSE")])
    evidence = pd.DataFrame([dict(cik=1, identity_name_key="TEST", accepted_timestamp_utc=pd.Timestamp("2024-03-08 13:00", tz="UTC"), adsh="first", name_role="CURRENT_LEGAL_NAME")])
    events = pd.DataFrame([dict(cik=1, assigned_sic=3674, sic_available_at=pd.Timestamp("2024-03-08 13:05", tz="UTC"), acceptance_datetime=pd.Timestamp("2024-03-08 13:00", tz="UTC"), accession_number="first")])
    state = dict(cik=1, accession="first", accepted_datetime=pd.Timestamp("2024-03-08 13:00", tz="UTC"),
                 feature_effective_date=pd.Timestamp("2024-03-11"), lineage_hash="a" * 64, accepted_source_sha256="b" * 64,
                 **{field: 1.0 for field in p.FUNDAMENTAL_FIELDS})
    return intervals, evidence, events, pd.DataFrame([state])


def test_same_day_forbidden_next_session_allowed_across_dst():
    f = p._enrich(samples(["2024-03-08", "2024-03-11"]), *inputs(), str)
    assert f.eligible.tolist() == [False, True]
    assert pd.isna(f.loc[0, "pit_revenue_yoy"])
    assert f.loc[1, "pit_revenue_yoy"] == 1
    assert (f.loc[f.pit_sec_available_at.notna(), "pit_sec_available_at"] <=
            f.loc[f.pit_sec_available_at.notna(), "prediction_at_utc"]).all()


def test_future_identity_and_filing_cannot_change_earlier_rows():
    intervals, evidence, events, states = inputs()
    baseline = p._enrich(samples(["2024-03-11"]), intervals, evidence, events, states, str)
    extra = evidence.iloc[0].copy()
    extra["cik"] = 2
    extra["accepted_timestamp_utc"] = pd.Timestamp("2024-03-12", tz="UTC")
    future = states.iloc[0].copy()
    future["accession"] = "later"
    future["feature_effective_date"] = pd.Timestamp("2024-04-01")
    future["accepted_datetime"] = pd.Timestamp("2024-03-29", tz="UTC")
    future["revenue_yoy"] = 999
    extended = p._enrich(samples(["2024-03-11"]), intervals, pd.concat([evidence, extra.to_frame().T]),
                         events, pd.concat([states, future.to_frame().T]), str)
    pd.testing.assert_frame_equal(baseline, extended)


def test_effective_date_and_acceptance_both_constrain_fundamentals():
    intervals, evidence, events, states = inputs()
    states.loc[0, "feature_effective_date"] = pd.Timestamp("2024-04-01")
    f = p._enrich(samples(["2024-03-11"]), intervals, evidence, events, states, str)
    assert f.eligible.iloc[0]
    assert f.pit_revenue_yoy.isna().all()
    states.loc[0, "feature_effective_date"] = pd.Timestamp("2024-03-11")
    states.loc[0, "accepted_datetime"] = pd.Timestamp("2024-04-01", tz="UTC")
    f = p._enrich(samples(["2024-03-11"]), intervals, evidence, events, states, str)
    assert f.pit_revenue_yoy.isna().all()


def test_optional_fundamentals_missing_preserves_qualified_samples():
    intervals, evidence, events, _ = inputs()
    f = p._enrich(samples(["2024-03-11"]), intervals, evidence, events, None, str)
    assert len(f) == 1 and f.eligible.iloc[0]
    assert f.pit_revenue_yoy.isna().all()


def test_ended_and_ambiguous_intervals_do_not_admit_rows():
    intervals, evidence, events, states = inputs()
    intervals.loc[0, "effective_end"] = pd.Timestamp("2024-03-08")
    f = p._enrich(samples(["2024-03-11"]), intervals, evidence, events, states, str)
    assert not f.eligible.iloc[0]
    intervals.loc[0, "effective_end"] = pd.Timestamp("2024-12-31")
    f = p._enrich(samples(["2024-03-11"]), pd.concat([intervals, intervals]), evidence, events, states, str)
    assert not f.eligible.iloc[0]
    assert f.eligibility_reason.iloc[0] == "AMBIGUOUS_HISTORICAL_INTERVAL"


def test_reader_filters_pre2026_before_materialization_and_verifies_hash(tmp_path, monkeypatch):
    path = tmp_path / "source.parquet"
    pd.DataFrame({"date": ["2025-12-31", "2026-01-01"], "value": [1, 999]}).to_parquet(path, index=False)
    monkeypatch.setitem(p.HASHES, path.name, hashlib.sha256(path.read_bytes()).hexdigest())
    f = p._read(path, ["date", "value"], "date", {"sources": {}})
    assert f.value.tolist() == [1]
    monkeypatch.setitem(p.HASHES, path.name, "0" * 64)
    with pytest.raises(p.SourceContractError, match="SOURCE_HASH_CHANGED"):
        p._read(path, ["date", "value"], "date", {"sources": {}})


def test_2026_and_wrong_prediction_clock_rejected():
    with pytest.raises(ValueError, match="PRE2026"):
        p._validate_samples(samples(["2026-01-02"]))
    f = samples(["2025-12-31"])
    f["prediction_at_utc"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="0925"):
        p._validate_samples(f)


def test_download_union_includes_pre2023_exit_without_reading_later_surface(monkeypatch):
    intervals, evidence, events, _ = inputs()
    intervals["ticker"] = "EXITED"
    intervals["effective_start"] = pd.Timestamp("2021-01-01")
    intervals["effective_end"] = pd.Timestamp("2021-12-31")
    evidence["accepted_timestamp_utc"] = pd.Timestamp("2021-02-01 20:00", tz="UTC")
    events["sic_available_at"] = pd.Timestamp("2021-02-01 20:05", tz="UTC")
    events["acceptance_datetime"] = pd.Timestamp("2021-02-01 20:00", tz="UTC")
    monkeypatch.setattr(p, "_foundation_contract", lambda m: {})
    monkeypatch.setattr(p, "_normalizer", lambda m, f: str)
    monkeypatch.setattr(p, "_load_intervals", lambda m: intervals.copy())
    def read(path, columns, date_column, manifest):
        if path.name == "sec_identity_evidence.parquet":
            return evidence.copy()
        if path.name == "sec_as_filed_sic_events.parquet":
            return events.copy()
        if path == p.CALENDAR:
            return pd.DataFrame({"trade_date": ["2021-05-03"], "is_session": [True]})
        raise AssertionError("Unexpected source, including any later daily surface: " + str(path))
    monkeypatch.setattr(p, "_read", read)
    plan = p.universe_download_plan()
    assert plan["symbols"] == ["EXITED"]
    assert plan["qualification_keys"][0]["date"] == "2021-05-03"
