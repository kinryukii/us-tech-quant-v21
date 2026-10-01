"""Synthetic PIT membership versions and forward-only identity evidence."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("historical_universe_under_test",
    ROOT / "scripts/research/a2/inference/historical_top40_universe.py")
u = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(u)


@pytest.fixture
def calendar():
    return pd.bdate_range("2026-01-01", "2026-09-30").difference(pd.to_datetime([
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07"]))


@pytest.fixture
def inputs():
    frozen_schedule = pd.DataFrame([
        {"quarter": "2025Q4", "effective_date": "2026-02-25", "institution_count": 24,
         "post_cap_universe_count": 1, "universe_fingerprint": "old"},
        {"quarter": "2026Q1", "effective_date": "2026-05-22", "institution_count": 24,
         "post_cap_universe_count": 1, "universe_fingerprint": "new"}])
    frozen = pd.DataFrame([
        {"quarter": "2025Q4", "cusip": "A", "ticker": "AAA", "moomoo_transport_code": "US.AAA",
         "effective_date": "2026-02-25", "expiry_date": "2026-05-21", "quarter_universe_fingerprint": "old"},
        {"quarter": "2026Q1", "cusip": "B", "ticker": "BBB", "moomoo_transport_code": "US.BBB",
         "effective_date": "2026-05-22", "expiry_date": None, "quarter_universe_fingerprint": "new"}])
    managers = [f"m{i:02}" for i in range(24)] + [u.SA_MANAGER]
    registry = pd.DataFrame([{"manager_id": name, "enabled": True,
        "active_from_quarter": "2024Q4" if name == u.SA_MANAGER else "2020Q1",
        "active_to_quarter": ""} for name in managers])
    dynamic, filings = [], []
    for quarter, effective, filed in [("2025Q4", "2026-02-25", "2026-02-18"),
            ("2026Q1", "2026-05-26", "2026-05-18"), ("2026Q2", "2026-08-21", "2026-08-14")]:
        for security in "ABU":
            dynamic.append({"quarter": quarter, "cusip": security, "issuer_name": security,
                "effective_date": effective, "manager_ids": u.SA_MANAGER if security == "U" else "m00"})
        for name in managers:
            filings.append({"quarter": quarter, "manager_id": name, "filed_date": filed,
                            "accession": f"{quarter}-{name}"})
    dynamic = pd.DataFrame(dynamic)
    all_filings = pd.DataFrame(filings)
    revision = dynamic.loc[dynamic.quarter.eq("2026Q2")].copy()
    revision["effective_date"] = "2026-09-10"
    revision_filings = all_filings.loc[all_filings.quarter.eq("2026Q2")].copy()
    amended = revision_filings.iloc[0].to_dict() | {"filed_date": "2026-09-02", "accession": "amendment"}
    revision_filings = pd.concat([revision_filings, pd.DataFrame([amended])], ignore_index=True)
    return {"frozen_schedule": frozen_schedule, "frozen_members": frozen, "dynamic": dynamic,
        "registry": registry, "historical_selected": all_filings.loc[all_filings.quarter.ne("2026Q2")].rename(
            columns={"filed_date": "filing_date", "accession": "accession_key"}),
        "initial_filings": all_filings.loc[all_filings.quarter.eq("2026Q2")],
        "revision": revision, "revision_filings": revision_filings,
        "current_report": {"quarter": "2026Q2", "effective_date": "2026-09-10", "target_date": "2026-09-22"},
        "current_members": pd.DataFrame([{"security_id": code, "ticker": ticker, "moomoo_symbol": f"US.{ticker}"}
            for code, ticker in [("A", "AAA"), ("B", "BBB"), ("U", "UUU")]]),
        "lineage": {key: {"path": key, "sha256": key} for key in [
            "frozen_members", "dynamic_universe", "revision", "current_members"]}}


def build(monkeypatch, inputs, calendar, start="2026-08-20", end="2026-09-22", mode="registry25",
          cohort_policy="ALL_APPLICABLE"):
    monkeypatch.setattr(u, "_load_inputs", lambda *_: copy.deepcopy(inputs))
    return u.build_universe_schedule(None, start, end, calendar, "report.json", mode, cohort_policy)


def test_initial_and_revision_do_not_leak_backward(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar)
    ledger = result["ledger"].set_index("target_date")
    assert ledger.loc["2026-08-20", "quarter"] == "2026Q1"
    assert ledger.loc["2026-08-21", "effective_date"] == pd.Timestamp("2026-08-21")
    assert ledger.loc["2026-09-09", "effective_date"] == pd.Timestamp("2026-08-21")
    assert ledger.loc["2026-09-10", "effective_date"] == pd.Timestamp("2026-09-10")
    assert ledger.loc["2026-09-09", "snapshot_id"] != ledger.loc["2026-09-10", "snapshot_id"]
    assert set(result["schedule"].version_kind) == {"INITIAL", "REVISION", "CURRENT_IDENTITY_ASOF"}


def test_current_identity_is_target_only(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar)
    ledger = result["ledger"].set_index("target_date")
    assert ledger.loc["2026-09-21", "mapped_count"] == 2
    assert ledger.loc["2026-09-22", "mapped_count"] == 3
    assert ledger.loc["2026-09-22", "effective_date"] == pd.Timestamp("2026-09-10")
    assert ledger.loc["2026-09-22", "snapshot_effective_date"] == pd.Timestamp("2026-09-22")
    assert ledger.loc["2026-09-21", "status"] == "PARTIAL_IDENTITY_COVERAGE"
    assert ledger.loc["2026-09-22", "status"] == "READY"


def test_report_for_other_target_does_not_resolve_history(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar, end="2026-09-21")
    assert not result["members"].ticker.eq("UUU").any()
    assert result["ledger"].mapped_count.eq(2).all()


def test_carry_forward_ignores_membership_expiry(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar, start="2026-05-26", end="2026-05-27")
    carried = result["members"].query("security_id == 'A'").iloc[0]
    assert carried.ticker == "AAA"
    assert carried.mapping_status == "VERIFIED_PRIOR_CUSIP_CARRIED_FORWARD"
    assert carried.identity_evidence_quarter == "2025Q4"


def test_no_future_identity_backfill(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar, start="2026-03-02", end="2026-03-03")
    later = result["members"].query("security_id == 'B'").iloc[0]
    assert pd.isna(later.ticker)
    assert result["ledger"].mapped_count.eq(1).all()
    assert result["ledger"].universe_member_count.eq(3).all()


def test_sa_config_without_actual_filing_never_invents_sa(monkeypatch, inputs, calendar):
    history = inputs["historical_selected"]
    inputs["historical_selected"] = history.loc[~(history.quarter.eq("2025Q4") & history.manager_id.eq(u.SA_MANAGER))]
    inputs["dynamic"].loc[inputs["dynamic"].quarter.eq("2025Q4"), "manager_ids"] = "m00"
    result = build(monkeypatch, inputs, calendar, start="2026-03-02", end="2026-03-03")
    assert result["ledger"].institution_count.eq(24).all()
    assert not result["schedule"].manager_ids.str.contains(u.SA_MANAGER).any()


def test_holding_cannot_claim_manager_without_filing(monkeypatch, inputs, calendar):
    history = inputs["historical_selected"]
    inputs["historical_selected"] = history.loc[~(history.quarter.eq("2025Q4") & history.manager_id.eq(u.SA_MANAGER))]
    with pytest.raises(ValueError, match="HOLDING_WITHOUT_FILING"):
        build(monkeypatch, inputs, calendar)


def test_missing_required_manager_fails_closed_by_default(monkeypatch, inputs, calendar):
    inputs["historical_selected"] = inputs["historical_selected"].loc[lambda frame: frame.manager_id.ne("m01")]
    with pytest.raises(ValueError, match="ACTUAL_FILERS_INCOMPLETE"):
        build(monkeypatch, inputs, calendar)


def test_missing_registered_manager_uses_only_actual_filings_when_explicit(monkeypatch, inputs, calendar):
    inputs["historical_selected"] = inputs["historical_selected"].loc[lambda frame: frame.manager_id.ne("m01")]
    result = build(monkeypatch, inputs, calendar, cohort_policy="DISCLOSED_ONLY")
    historical = result["schedule"].loc[lambda frame: frame.quarter.eq("2026Q1")]
    assert historical.institution_count.eq(24).all()
    assert not historical.manager_ids.str.split(";").map(lambda names: "m01" in names).any()


def test_five_sessions_use_calendar_not_weekdays(monkeypatch, inputs, calendar):
    inputs["dynamic"].loc[lambda frame: frame.quarter.eq("2026Q1"), "effective_date"] = "2026-05-25"
    with pytest.raises(ValueError, match="FIVE_SESSION_RULE"):
        build(monkeypatch, inputs, calendar)


def test_collision_stops_old_carry_preserving_same_quarter_evidence(monkeypatch, inputs, calendar):
    inputs["frozen_members"].loc[lambda frame: frame.cusip.eq("B"), ["ticker", "moomoo_transport_code"]] = ["AAA", "US.AAA"]
    result = build(monkeypatch, inputs, calendar, start="2026-05-26", end="2026-05-27")
    assert result["ledger"].mapped_count.eq(1).all()
    reasons = {row["security_id"]: row["reason"] for row in result["gaps"]}
    assert reasons["A"] == "PIT_IDENTITY_PROVIDER_COLLISION"
    assert "B" not in reasons


def test_two_prior_carries_with_same_symbol_stay_unresolved(monkeypatch, inputs, calendar):
    inputs["frozen_members"].loc[lambda frame: frame.cusip.eq("B"), ["ticker", "moomoo_transport_code"]] = ["AAA", "US.AAA"]
    result = build(monkeypatch, inputs, calendar, start="2026-08-21", end="2026-09-21")
    assert result["ledger"].mapped_count.eq(0).all()
    reasons = {row["security_id"]: row["reason"] for row in result["gaps"]}
    assert reasons["A"] == reasons["B"] == "PIT_IDENTITY_PROVIDER_COLLISION"


def test_current_gap_does_not_reuse_conflicting_prior_mapping(monkeypatch, inputs, calendar):
    inputs["current_members"] = inputs["current_members"].loc[lambda frame: frame.security_id.ne("A")]
    result = build(monkeypatch, inputs, calendar)
    snapshot = result["ledger"].iloc[-1].snapshot_id
    record = result["members"].loc[lambda frame: frame.snapshot_id.eq(snapshot) & frame.security_id.eq("A")].iloc[0]
    assert pd.isna(record.ticker)
    assert record.mapping_reason == "CURRENT_REPORT_IDENTITY_GAP"


def test_original24_mode_stays_on_frozen_pool(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar, start="2026-05-22", end="2026-05-26", mode="original24")
    assert result["ledger"].institution_count.eq(24).all()
    assert result["ledger"].universe_id.eq("new").all()
    assert result["members"].security_id.tolist() == ["B"]


def test_duplicate_initial_filing_is_not_silently_collapsed(monkeypatch, inputs, calendar):
    extra = inputs["initial_filings"].iloc[0].to_dict() | {"accession": "second"}
    inputs["initial_filings"] = pd.concat([inputs["initial_filings"], pd.DataFrame([extra])])
    with pytest.raises(ValueError, match="INITIAL_FILING_AMBIGUOUS"):
        build(monkeypatch, inputs, calendar)


def test_source_hash_is_verified(tmp_path):
    path = tmp_path / "frame.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(path)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        u._frame({"path": str(path), "sha256": "0" * 64})


def test_frozen_fingerprint_mismatch_fails(monkeypatch, inputs, calendar):
    inputs["frozen_members"].loc[0, "quarter_universe_fingerprint"] = "tampered"
    with pytest.raises(ValueError, match="FROZEN_MANIFEST_MISMATCH"):
        build(monkeypatch, inputs, calendar)


def test_no_effective_pool_is_explicit(monkeypatch, inputs, calendar):
    result = build(monkeypatch, inputs, calendar, start="2026-01-02", end="2026-01-05")
    assert result["ledger"].status.eq("NO_EFFECTIVE_UNIVERSE").all()
    assert result["schedule"].empty and result["members"].empty


def test_same_quarter_cannot_activate_during_reporting_quarter(monkeypatch, inputs, calendar):
    inputs["dynamic"].loc[lambda frame: frame.quarter.eq("2026Q1"), "effective_date"] = "2026-03-09"
    inputs["historical_selected"].loc[lambda frame: frame.quarter.eq("2026Q1"), "filing_date"] = "2026-03-02"
    with pytest.raises(ValueError, match="SAME_OR_FUTURE_QUARTER"):
        build(monkeypatch, inputs, calendar, start="2026-03-10", end="2026-03-11")


def test_input_frames_are_not_mutated(monkeypatch, inputs, calendar):
    before = inputs["dynamic"].copy(deep=True)
    build(monkeypatch, inputs, calendar)
    pd.testing.assert_frame_equal(before, inputs["dynamic"])


def test_mixed_source_dates_are_parquet_serializable(monkeypatch, inputs, calendar, tmp_path):
    inputs["dynamic"]["report_date"] = pd.Timestamp("2026-01-01")
    inputs["revision"]["report_date"] = "2026-06-30"
    result = build(monkeypatch, inputs, calendar)
    for name in ("schedule", "members", "ledger"):
        path = tmp_path / f"{name}.parquet"
        result[name].to_parquet(path, index=False)
        assert len(pd.read_parquet(path)) == len(result[name])


@pytest.mark.parametrize("mode", ["registry", "guess", "today_pool"])
def test_unknown_mode_rejected(inputs, calendar, mode):
    with pytest.raises(ValueError, match="MODE_INVALID"):
        u.build_universe_schedule(None, "2026-03-02", "2026-03-03", calendar, mode=mode)


@pytest.mark.parametrize("valid_from,valid_to,verified", [
    ("2026-09-22", "2026-09-22", True), ("2026-09-23", None, False), ("2026-04-01", "2026-09-21", False)])
def test_current_identity_interval_applies_only_at_report_target(monkeypatch, inputs, calendar, valid_from, valid_to, verified):
    mask=inputs["current_members"].security_id.eq("U")
    inputs["current_members"].loc[mask,"identity_valid_from"]=valid_from
    inputs["current_members"].loc[mask,"identity_valid_to"]=valid_to
    result=build(monkeypatch,inputs,calendar,start="2026-09-21",end="2026-09-22")
    final=result["ledger"].iloc[-1].snapshot_id
    row=result["members"].loc[lambda f:f.snapshot_id.eq(final)&f.security_id.eq("U")].iloc[0]
    assert bool(row.mapping_verified) is verified
    if not verified: assert row.mapping_reason == "IDENTITY_OUTSIDE_VERIFIED_INTERVAL"
    earlier=result["ledger"].iloc[0].snapshot_id
    prior=result["members"].loc[lambda f:f.snapshot_id.eq(earlier)&f.security_id.eq("U")].iloc[0]
    assert not bool(prior.mapping_verified)

@pytest.mark.parametrize('ticker,code', [('DTP','US.DTP'),('DTE','US.DTP'),('DTP','US.DTE')])
def test_dte_common_never_uses_dtp_units_keeps_holding(monkeypatch,inputs,calendar,ticker,code):
    for key in ('frozen_members','dynamic','revision'):
        inputs[key].loc[inputs[key].cusip.eq('A'),'cusip']='233331107'
    inputs['frozen_members'].loc[inputs['frozen_members'].cusip.eq('233331107'),['ticker','moomoo_transport_code']]=[ticker,code]
    inputs['current_members'].loc[inputs['current_members'].security_id.eq('A'),['security_id','ticker','moomoo_symbol']]=['233331107',ticker,code]
    before=copy.deepcopy(inputs)
    result=build(monkeypatch,inputs,calendar)
    blocked=result['members'].loc[result['members'].cusip.eq('233331107')]
    assert not blocked.empty
    assert blocked.ticker.isna().all() and blocked.moomoo_symbol.isna().all()
    assert not blocked.mapping_verified.any()
    assert blocked.mapping_reason.eq('IDENTITY_MISMATCH_DTE_COMMON_VS_DTP_UNITS').all()
    assert blocked.identity_source_sha256.notna().all()
    assert blocked.identity_rejection_evidence.str.contains('DTE_COMMON_VS_DTP_UNITS_V1').all()
    ledger=result['ledger'].set_index('target_date')
    assert ledger.loc['2026-09-22','universe_member_count']==3
    assert ledger.loc['2026-09-22','mapped_count']==2
    assert ledger.loc['2026-09-22','mapping_gap_count']==1
    pd.testing.assert_frame_equal(inputs['frozen_members'],before['frozen_members'])


def test_unrelated_cusip_is_not_rejected_by_dtp_rule(monkeypatch,inputs,calendar):
    inputs['frozen_members'].loc[inputs['frozen_members'].cusip.eq('A'),['ticker','moomoo_transport_code']]=['DTP','US.DTP']
    result=build(monkeypatch,inputs,calendar,end='2026-09-21')
    assert result['members'].loc[result['members'].cusip.eq('A')].mapping_verified.all()


def _whole_snapshot_inputs():
    cohorts = {"2024Q4": ["m00", "m01", "m02"],
        "2025Q1": ["m00", "m01", "m02", u.SA_MANAGER],
        "2025Q2": ["m00", "m01", "m02", u.SA_MANAGER],
        "2025Q3": ["m00", "m01", "m02"]}
    specifications = [
        ("old", "2024Q4", "2025-02-21T14:00:00Z", ["m00", "m01"], "AAA"),
        ("sa1", "2025Q1", "2025-05-23T13:00:00Z", ["m00", u.SA_MANAGER], "BBB"),
        ("sa2", "2025Q2", "2025-08-22T13:00:00Z", ["m00", u.SA_MANAGER], "CCC"),
        ("latest", "2025Q3", "2025-11-25T14:00:00Z", ["m00"], "DDD")]
    schedule, members = [], []
    for snapshot, quarter, effective, managers, ticker in specifications:
        schedule.append({"snapshot_id": snapshot, "quarter": quarter, "revision": 0,
            "effective_at": effective, "qualification_available_at": effective,
            "qualification_status": "COMPLETE_AND_QUALIFIED", "manager_ids": managers,
            "universe_member_count": 1, "mapping_qualified": True, "pit_qualified": True})
        members.append({"snapshot_id": snapshot, "quarter": quarter, "security_id": "sec-" + snapshot,
            "ticker": ticker, "moomoo_transport_code": "US." + ticker,
            "mapping_verified": True, "pit_qualified": True})
    return pd.DataFrame(schedule), pd.DataFrame(members), cohorts


def _select_whole(schedule, members, cohorts, decision="2025-12-01T14:00:00Z",
                  cohort_policy="DISCLOSED_ONLY"):
    return u.select_whole_qualified_snapshot(schedule, members, decision, cohorts, cohort_policy)


def test_whole_snapshot_disclosed_only_does_not_wait_for_registered_managers(monkeypatch):
    schedule, members, cohorts = _whole_snapshot_inputs()
    before_schedule, before_members = schedule.copy(deep=True), members.copy(deep=True)
    monkeypatch.setattr(u, "_load_inputs", lambda *_: pytest.fail("Pure selector performed file loading"))
    result = _select_whole(schedule, members, cohorts)
    assert result["snapshot"]["snapshot_id"] == "latest"
    assert result["snapshot"]["manager_ids"] == ("m00",)
    assert result["members"].security_id.tolist() == ["sec-latest"]
    assert not result["fallback_used"]
    assert "NOT_AUTHORITY_ESTABLISHMENT" in result["cohort_validation_scope"]
    pd.testing.assert_frame_equal(schedule, before_schedule)
    pd.testing.assert_frame_equal(members, before_members)


@pytest.mark.parametrize("decision,snapshot,has_sa", [
    ("2025-03-03T14:00:00Z", "old", False),
    ("2025-06-02T13:00:00Z", "sa1", True),
    ("2025-09-02T13:00:00Z", "sa2", True),
    ("2025-12-01T14:00:00Z", "latest", False)])
def test_whole_snapshot_sa_exists_only_in_two_disclosed_quarters(decision, snapshot, has_sa):
    schedule, members, cohorts = _whole_snapshot_inputs()
    result = _select_whole(schedule, members, cohorts, decision)
    assert result["snapshot"]["snapshot_id"] == snapshot
    assert (u.SA_MANAGER in result["snapshot"]["manager_ids"]) is has_sa


def test_whole_snapshot_fallback_retains_only_previous_whole_members():
    schedule, members, cohorts = _whole_snapshot_inputs()
    members.loc[members.snapshot_id.eq("latest"), "mapping_verified"] = False
    result = _select_whole(schedule, members, cohorts)
    assert result["snapshot"]["snapshot_id"] == "sa2"
    assert result["members"].snapshot_id.eq("sa2").all()
    assert result["members"].security_id.tolist() == ["sec-sa2"]
    assert result["fallback_used"]
    assert result["fallback_reasons"] == [{"snapshot_id": "latest", "quarter": "2025Q3", "revision": 0,
        "reasons": ["WHOLE_MEMBER_MAPPING_OR_PIT_UNQUALIFIED"]}]


@pytest.mark.parametrize("field,value,reason", [
    ("qualification_status", "MAPPING_PENDING", "SNAPSHOT_NOT_COMPLETE_AND_QUALIFIED"),
    ("mapping_qualified", False, "SNAPSHOT_MAPPING_OR_PIT_UNQUALIFIED"),
    ("pit_qualified", False, "SNAPSHOT_MAPPING_OR_PIT_UNQUALIFIED"),
    ("universe_member_count", 2, "WHOLE_MEMBER_COUNT_MISMATCH"),
    ("qualification_available_at", "2025-12-02T14:00:00Z", "QUALIFICATION_NOT_AVAILABLE"),
    ("effective_at", "2025-12-02T14:00:00Z", "SNAPSHOT_NOT_EFFECTIVE")])
def test_whole_snapshot_newer_unqualified_versions_fall_back(field, value, reason):
    schedule, members, cohorts = _whole_snapshot_inputs()
    schedule.loc[schedule.snapshot_id.eq("latest"), field] = value
    result = _select_whole(schedule, members, cohorts)
    assert result["snapshot"]["snapshot_id"] == "sa2"
    assert reason in result["fallback_reasons"][0]["reasons"]


def test_whole_snapshot_exact_activation_and_qualification_boundary():
    schedule, members, cohorts = _whole_snapshot_inputs()
    assert _select_whole(schedule, members, cohorts, "2025-11-25T13:59:59Z")["snapshot"]["snapshot_id"] == "sa2"
    assert _select_whole(schedule, members, cohorts, "2025-11-25T14:00:00Z")["snapshot"]["snapshot_id"] == "latest"


def test_whole_snapshot_future_append_cannot_change_selected_members():
    schedule, members, cohorts = _whole_snapshot_inputs()
    before = _select_whole(schedule, members, cohorts)
    revision = schedule.iloc[-1].to_dict() | {"snapshot_id": "future", "revision": 1,
        "effective_at": "2025-12-03T14:00:00Z", "qualification_available_at": "2025-12-02T14:00:00Z"}
    future_member = members.iloc[-1].to_dict() | {"snapshot_id": "future", "security_id": "future-sec"}
    after = _select_whole(pd.concat([schedule, pd.DataFrame([revision])], ignore_index=True),
        pd.concat([members, pd.DataFrame([future_member])], ignore_index=True), cohorts)
    assert before["snapshot"] == after["snapshot"]
    pd.testing.assert_frame_equal(before["members"], after["members"])


def test_whole_snapshot_same_or_future_report_quarter_never_activates():
    schedule, members, cohorts = _whole_snapshot_inputs()
    schedule.loc[schedule.snapshot_id.eq("latest"), "quarter"] = "2025Q4"
    members.loc[members.snapshot_id.eq("latest"), "quarter"] = "2025Q4"
    cohorts["2025Q4"] = cohorts["2025Q3"]
    result = _select_whole(schedule, members, cohorts)
    assert result["snapshot"]["snapshot_id"] == "sa2"
    assert "SAME_OR_FUTURE_REPORT_QUARTER" in result["fallback_reasons"][0]["reasons"]


@pytest.mark.parametrize("field", ["effective_at", "qualification_available_at"])
def test_whole_snapshot_visible_revision_cannot_move_time_backward(field):
    schedule, members, cohorts = _whole_snapshot_inputs()
    revision = schedule.iloc[-1].to_dict() | {"snapshot_id": "revision", "revision": 1,
        "effective_at": "2025-11-26T14:00:00Z", "qualification_available_at": "2025-11-26T14:00:00Z"}
    revision[field] = "2025-11-24T14:00:00Z"
    added = members.iloc[-1].to_dict() | {"snapshot_id": "revision"}
    with pytest.raises(u.WholeSnapshotQualificationError, match="REVISION_TIME_REGRESSION"):
        _select_whole(pd.concat([schedule, pd.DataFrame([revision])], ignore_index=True),
            pd.concat([members, pd.DataFrame([added])], ignore_index=True), cohorts)


@pytest.mark.parametrize("case,reason", [
    ("missing_column", "REQUIRED_COLUMNS_MISSING"), ("naive_decision", "TIMEZONE_REQUIRED"),
    ("naive_qualification", "TIMEZONE_REQUIRED"), ("duplicate_security", "DUPLICATE_SECURITY_IDENTITY"),
    ("duplicate_manager", "DUPLICATE_MANAGER"), ("unknown_manager", "UNREGISTERED_OR_INACTIVE_ACTUAL_FILER"),
    ("member_quarter", "MEMBER_QUARTER_CONFLICT"), ("missing_cohort", "COHORT_AUTHORITY_MISSING"),
    ("empty_actual", "EXPLICIT_MANAGER_SEQUENCE_REQUIRED"), ("duplicate_version", "DUPLICATE_VERSION")])
def test_whole_snapshot_missing_or_ambiguous_authority_fails_closed(case, reason):
    schedule, members, cohorts = _whole_snapshot_inputs()
    decision = "2025-12-01T14:00:00Z"
    index = schedule.index[-1]
    if case == "missing_column": schedule = schedule.drop(columns="qualification_available_at")
    elif case == "naive_decision": decision = "2025-12-01 14:00:00"
    elif case == "naive_qualification": schedule.loc[index, "qualification_available_at"] = "2025-11-25 14:00:00"
    elif case == "duplicate_security": members = pd.concat([members, members.iloc[[-1]]], ignore_index=True)
    elif case == "duplicate_manager": schedule.at[index, "manager_ids"] = ["m00", "m00"]
    elif case == "unknown_manager": schedule.at[index, "manager_ids"] = ["unregistered"]
    elif case == "member_quarter": members.loc[members.snapshot_id.eq("latest"), "quarter"] = "2025Q2"
    elif case == "missing_cohort": del cohorts["2025Q3"]
    elif case == "empty_actual": schedule.at[index, "manager_ids"] = []
    elif case == "duplicate_version": schedule = pd.concat([schedule, schedule.iloc[[-1]]], ignore_index=True)
    with pytest.raises(u.WholeSnapshotQualificationError, match=reason):
        _select_whole(schedule, members, cohorts, decision)


def test_whole_snapshot_no_qualified_previous_fails_closed():
    schedule, members, cohorts = _whole_snapshot_inputs()
    schedule["qualification_status"] = "PENDING"
    with pytest.raises(u.WholeSnapshotQualificationError, match="NO_PREVIOUS_COMPLETE_AND_QUALIFIED"):
        _select_whole(schedule, members, cohorts)


@pytest.mark.parametrize("kind", ["unknown", "disabled", "out_of_interval"])
def test_disclosed_manager_must_be_registered_enabled_and_active(kind):
    registry = pd.DataFrame([{"manager_id": "known", "enabled": kind != "disabled",
        "active_from_quarter": "2025Q2" if kind == "out_of_interval" else "2020Q1",
        "active_to_quarter": ""}])
    with pytest.raises(ValueError, match="UNREGISTERED_OR_INACTIVE_ACTUAL_FILER"):
        u._registered_managers(registry, "2025Q1", ["other" if kind == "unknown" else "known"])


def test_disclosed_filing_plan_ignores_missing_rows_downstream(monkeypatch, inputs, calendar):
    inputs["initial_filings"]["status"] = "INITIAL_FILING_IDENTIFIED"
    missing = inputs["initial_filings"].manager_id.eq("m01")
    inputs["initial_filings"].loc[missing, ["status", "filed_date", "accession"]] = ["MISSING", None, None]
    result = build(monkeypatch, inputs, calendar, cohort_policy="DISCLOSED_ONLY")
    initial = result["schedule"].loc[lambda frame: frame.quarter.eq("2026Q2") & frame.version_kind.eq("INITIAL")]
    assert initial.institution_count.eq(24).all()
    assert not initial.manager_ids.str.split(";").map(lambda names: "m01" in names).any()


def test_identified_filing_with_missing_evidence_still_fails_closed(monkeypatch, inputs, calendar):
    inputs["initial_filings"]["status"] = "INITIAL_FILING_IDENTIFIED"
    inputs["initial_filings"].loc[inputs["initial_filings"].manager_id.eq("m01"), "accession"] = None
    with pytest.raises(ValueError, match="FILING_EVIDENCE_INCOMPLETE"):
        build(monkeypatch, inputs, calendar)


def test_revision_holding_requires_an_actual_disclosed_manager(monkeypatch, inputs, calendar):
    inputs["revision"].loc[inputs["revision"].cusip.eq("A"), "manager_ids"] = "not_disclosed"
    with pytest.raises(ValueError, match="HOLDING_WITHOUT_FILING"):
        build(monkeypatch, inputs, calendar)


def test_whole_snapshot_default_requires_complete_applicable_cohort():
    schedule, members, cohorts = _whole_snapshot_inputs()
    with pytest.raises(u.WholeSnapshotQualificationError, match="NO_PREVIOUS_COMPLETE_AND_QUALIFIED"):
        u.select_whole_qualified_snapshot(schedule, members, "2025-12-01T14:00:00Z", cohorts)
    assert _select_whole(schedule, members, cohorts)["snapshot"]["snapshot_id"] == "latest"


def test_whole_snapshot_strict_partial_cohort_falls_back_whole():
    schedule, members, cohorts = _whole_snapshot_inputs()
    for index, row in schedule.iterrows():
        schedule.at[index, "manager_ids"] = list(cohorts[row.quarter])
    schedule.at[schedule.index[-1], "manager_ids"] = ["m00"]
    result = u.select_whole_qualified_snapshot(schedule, members, "2025-12-01T14:00:00Z", cohorts)
    assert result["snapshot"]["snapshot_id"] == "sa2"
    assert result["members"].snapshot_id.eq("sa2").all()
    assert result["cohort_policy"] == "ALL_APPLICABLE"
    assert result["cohort_coverage"] == "COMPLETE_SUPPLIED_APPLICABLE_COHORT"
    assert "APPLICABLE_MANAGER_COHORT_INCOMPLETE" in result["fallback_reasons"][0]["reasons"]


def test_whole_snapshot_strict_sa_absent_when_not_applicable():
    schedule, members, cohorts = _whole_snapshot_inputs()
    schedule.at[schedule.index[0], "manager_ids"] = list(cohorts["2024Q4"])
    result = u.select_whole_qualified_snapshot(schedule, members, "2025-03-03T14:00:00Z", cohorts)
    assert result["snapshot"]["snapshot_id"] == "old"
    assert u.SA_MANAGER not in result["snapshot"]["manager_ids"]


@pytest.mark.parametrize("cohort_policy", ["ALL_APPLICABLE", "DISCLOSED_ONLY"])
def test_unknown_whole_snapshot_manager_fails_under_both_policies(cohort_policy):
    schedule, members, cohorts = _whole_snapshot_inputs()
    schedule.at[schedule.index[-1], "manager_ids"] = ["unregistered"]
    with pytest.raises(u.WholeSnapshotQualificationError, match="UNREGISTERED_OR_INACTIVE_ACTUAL_FILER"):
        _select_whole(schedule, members, cohorts, cohort_policy=cohort_policy)


@pytest.mark.parametrize("cohort_policy", ["ALL_APPLICABLE", "DISCLOSED_ONLY"])
def test_unknown_registered_filer_fails_under_both_policies(cohort_policy):
    registry = pd.DataFrame([{"manager_id": "known", "enabled": True,
        "active_from_quarter": "2020Q1", "active_to_quarter": ""}])
    with pytest.raises(ValueError, match="UNREGISTERED_OR_INACTIVE_ACTUAL_FILER"):
        u._registered_managers(registry, "2025Q1", ["unknown"], cohort_policy)


@pytest.mark.parametrize("cohort_policy,coverage", [
    ("ALL_APPLICABLE", "COMPLETE_APPLICABLE_ROSTER_SA_REQUIRES_ACTUAL_FILING"),
    ("DISCLOSED_ONLY", "NONEMPTY_DISCLOSED_REGISTERED_SUBSET_NO_OLD_QUARTER_FILL")])
def test_universe_lineage_records_cohort_policy_and_coverage(monkeypatch, inputs, calendar, cohort_policy, coverage):
    result = build(monkeypatch, inputs, calendar, cohort_policy=cohort_policy)
    assert result["lineage"]["cohort_policy"] == cohort_policy
    assert result["lineage"]["cohort_coverage"] == coverage


def test_invalid_cohort_policy_fails_before_loading_any_source(monkeypatch, inputs, calendar):
    monkeypatch.setattr(u, "_load_inputs", lambda *_: pytest.fail("Invalid policy reached file loader"))
    with pytest.raises(ValueError, match="COHORT_POLICY_INVALID"):
        u.build_universe_schedule(None, "2026-08-20", "2026-09-22", calendar, cohort_policy="ambiguous")
    schedule, members, cohorts = _whole_snapshot_inputs()
    with pytest.raises(u.WholeSnapshotQualificationError, match="COHORT_POLICY_INVALID"):
        _select_whole(schedule, members, cohorts, cohort_policy="ambiguous")
