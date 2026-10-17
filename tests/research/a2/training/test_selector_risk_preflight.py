"""Synthetic-only C R3 clock/identity/coverage checks; zero estimations or I/O."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.risk import joint_risk_estimators as risk
from scripts.research.a2.training import selector_risk_preflight as preflight


def fixture_history():
    calendar = pd.bdate_range("2022-08-01", "2023-03-31")
    cutoff = pd.Timestamp("2023-02-01")
    rows = []
    for i, day in enumerate(calendar):
        for name in ("A", "B"):
            rows.append({"signal_date": day, "security_uid": "UID:" + name,
                         "ticker": name, "identity_epoch": "E0", "ret_1d": (i % 9 - 4) * .001,
                         "available_at": day.tz_localize("America/New_York") + pd.Timedelta(hours=16),
                         "source_hash": "a" * 64, "return_unit": preflight.UNIT,
                         "predecessor_uid": "UID:" + name,
                         "predecessor_date": calendar[i - 1] if i else pd.NaT})
    universe = pd.DataFrame({"security_uid": ["UID:A", "UID:B", "UID:NEW"],
                             "ticker": ["A", "B", "NEW"]}, index=[7, 3, 9])
    return pd.DataFrame(rows), calendar, cutoff, universe


def qualify(frame=None, calendar=None, cutoff=None, universe=None, **kwargs):
    base, sessions, cut, keys = fixture_history()
    return preflight.qualify_monthly_history(
        base if frame is None else frame, sessions if calendar is None else calendar,
        cut if cutoff is None else cutoff, keys if universe is None else universe, **kwargs)


def test_clock_first_month_session_and_future_append_invariance():
    _, calendar, _, _ = fixture_history()
    earlier = preflight.monthly_cutoffs(calendar)
    appended = calendar.append(pd.bdate_range("2026-01-01", "2026-01-30"))
    assert preflight.monthly_cutoffs(appended) == earlier
    assert pd.Timestamp("2023-01-02") in earlier
    assert pd.Timestamp("2023-01-03") not in earlier
    with pytest.raises(ValueError, match="REGISTERED_YEARS"):
        preflight.monthly_cutoffs(calendar, years=(2023, 2024, 2025))
    with pytest.raises(ValueError, match="SEQUENCE_INVALID"):
        preflight.monthly_cutoffs(calendar[::-1])


def test_future_rows_returns_and_known_epoch_edges_cannot_change_past_qualification():
    frame, calendar, cutoff, universe = fixture_history()
    before = frame.loc[frame.signal_date.lt(cutoff)].copy()
    expected, metadata = qualify(before)
    future = frame.loc[frame.signal_date.ge(cutoff)].copy()
    future["ret_1d"] = "INVALID FUTURE NUMERIC VALUE"
    future["identity_epoch"] = "FUTURE_EPOCH"
    future["source_hash"] = "f" * 64
    extended = pd.concat([before, future], ignore_index=True)
    actual, receipt = qualify(extended)
    pd.testing.assert_frame_equal(actual, expected)
    assert receipt == metadata
    # A later-published historical revision must not replace the known old epoch.
    revision = before.iloc[[-2]].copy()
    revision["available_at"] = pd.Timestamp("2024-01-01T00:00:00Z")
    revision["epoch_available_at"] = pd.Timestamp("2024-01-01T00:00:00Z")
    revision["identity_epoch"] = "LATE_REVISION"
    revision["ret_1d"] = 999.
    actual, receipt = qualify(pd.concat([before, revision], ignore_index=True))
    pd.testing.assert_frame_equal(actual, expected)
    assert receipt == metadata


def test_strict_mature_label_dates_and_missing_maturity():
    mask = preflight.mature_label_mask(
        ["2023-01-30", "2023-01-30", "2023-02-01", "2023-01-30"],
        ["2023-01-31", "2023-02-01", "2023-01-31", None], "2023-02-01")
    assert mask.tolist() == [True, False, False, False]
    with pytest.raises(ValueError, match="AFTER_PRE2026"):
        preflight.mature_label_mask(["2025-12-30"], ["2026-01-01"], "2026-01-02")


def test_all_U_t_keys_preserved_with_ge30_lt30_nohistory_and_unknown():
    frame, calendar, cutoff, universe = fixture_history()
    past = calendar[calendar < cutoff][-63:]
    frame.loc[frame.security_uid.eq("UID:B") & frame.signal_date.isin(past[:34]), "ret_1d"] = np.nan
    unknown = frame.loc[frame.security_uid.eq("UID:A")].copy()
    unknown["security_uid"] = "UID:UNKNOWN"
    unknown["ticker"] = "UNKNOWN"
    unknown["predecessor_uid"] = "UID:UNKNOWN"
    unknown["available_at"] = pd.NaT
    universe = pd.concat([universe, pd.DataFrame({"security_uid": ["UID:UNKNOWN"], "ticker": ["UNKNOWN"]})])
    out, receipt = qualify(pd.concat([frame, unknown], ignore_index=True), universe=universe)
    assert out.security_uid.tolist() == universe.security_uid.tolist()
    assert out.status.tolist() == ["FINITE_GE30", "FINITE_LT30", "NO_HISTORY", "UNKNOWN"]
    assert out.qualified_finite.tolist() == [63, 29, 0, 0]
    assert out.potential_finite.tolist() == [63, 29, 0, 63]
    assert not out.eligibility_upgraded.any()
    assert receipt["source_accepted"] is False and receipt["full_U_t_preserved"]
    assert receipt["potential_finite_observations"] > receipt["qualified_finite_observations"]


@pytest.mark.parametrize("field", preflight.PROOF_FIELDS)
def test_missing_proof_keeps_potential_and_never_becomes_source_pass(field):
    frame, _, _, _ = fixture_history()
    frame = frame.drop(columns=field)
    out, receipt = qualify(frame)
    assert out.loc[0, "potential_finite"] == 63
    assert out.loc[0, "qualified_finite"] == 0
    assert not out.history_qualified_for_estimation.any()
    assert receipt["source_accepted"] is False


def test_available_at_strict_cutoff_and_naive_clock_are_unqualified():
    frame, calendar, cutoff, _ = fixture_history()
    dates = calendar[calendar < cutoff][-63:]
    at_limit = cutoff.tz_localize("America/New_York")
    frame.loc[frame.security_uid.eq("UID:A") & frame.signal_date.isin(dates), "available_at"] = at_limit
    out, _ = qualify(frame)
    assert out.loc[0, "qualified_finite"] == out.loc[0, "potential_finite"] == 0
    frame, _, _, _ = fixture_history()
    frame["available_at"] = frame.signal_date + pd.Timedelta(hours=16)
    out, _ = qualify(frame)
    assert out.loc[0, "potential_finite"] == 63 and out.loc[0, "qualified_finite"] == 0


def reset_history():
    frame, calendar, cutoff, universe = fixture_history()
    dates = calendar[calendar < cutoff][-63:]
    first = dates[31]
    frame.loc[frame.security_uid.eq("UID:A") & frame.signal_date.ge(first), "identity_epoch"] = "E1"
    edge = pd.DataFrame([{
        "from_uid": "UID:A", "from_epoch": "E0", "from_source_hash": "a" * 64,
        "to_uid": "UID:A", "to_epoch": "E1", "to_source_hash": "a" * 64,
        "predecessor_date": dates[30], "first_date": first,
        "available_at": first.tz_localize("America/New_York") + pd.Timedelta(hours=9),
        "return_unit": preflight.UNIT, "authorized": True, "authority_hash": "c" * 64,
    }])
    return frame, calendar, cutoff, universe, edge


def test_epoch_reset_quarantines_first_crossing_return_even_with_same_uid():
    frame, _, _, _, _ = reset_history()
    out, receipt = qualify(frame)
    row = out.iloc[0]
    assert row.status == "RESET_AND_QUARANTINE" and row.reset_flag
    assert row.potential_finite == row.qualified_finite == 31
    assert row.quarantined_finite == 1 and not row.authorized_continuity_flag
    assert row.history_qualified_for_estimation
    assert receipt["source_accepted"] is False


def test_authorized_complete_nonfuture_edge_preserves_earlier_epoch():
    frame, _, _, _, edge = reset_history()
    out, _ = qualify(frame, continuity_edges=edge, identity_policy=preflight.AUTHORIZED_CONTINUITY)
    row = out.iloc[0]
    assert row.status == "AUTHORIZED_CONTINUITY" and row.authorized_continuity_flag
    assert row.qualified_finite == row.potential_finite == 63
    assert not row.reset_flag and row.quarantined_finite == 0


@pytest.mark.parametrize("defect", ["late", "incomplete", "unauthorized", "wrong_unit", "wrong_predecessor"])
def test_late_or_incomplete_edge_cannot_authorize_continuity(defect):
    frame, _, cutoff, _, edge = reset_history()
    if defect == "late":
        edge["available_at"] = cutoff.tz_localize("America/New_York")
    elif defect == "incomplete":
        edge = edge.drop(columns="authority_hash")
    elif defect == "unauthorized":
        edge["authorized"] = False
    elif defect == "wrong_unit":
        edge["return_unit"] = "DIFFERENT_UNIT"
    else:
        edge["predecessor_date"] = edge.predecessor_date - pd.Timedelta(days=1)
    out, receipt = qualify(frame, continuity_edges=edge, identity_policy=preflight.AUTHORIZED_CONTINUITY)
    expected, expected_receipt = qualify(frame, identity_policy=preflight.AUTHORIZED_CONTINUITY)
    pd.testing.assert_frame_equal(out, expected)
    assert receipt == expected_receipt


def test_identity_first_return_is_not_proved_by_first_member_observation():
    frame, calendar, cutoff, universe = fixture_history()
    dates = calendar[calendar < cutoff][-63:]
    frame = frame.loc[~frame.security_uid.eq("UID:A") | frame.signal_date.ge(dates[0])].copy()
    out, _ = qualify(frame)
    row = out.iloc[0]
    assert row.status == "RESET_AND_QUARANTINE"
    assert row.potential_finite == row.qualified_finite == 62
    assert row.quarantined_finite == 1 and row.unknown_proof_flag


def test_identity_swap_and_source_hash_change_bind_digest():
    frame, _, _, universe = fixture_history()
    _, before = qualify(frame)
    changed = frame.copy()
    changed.loc[changed.security_uid.eq("UID:A"), "security_uid"] = "UID:REPLACEMENT"
    changed.loc[changed.predecessor_uid.eq("UID:A"), "predecessor_uid"] = "UID:REPLACEMENT"
    keys = universe.copy()
    keys.loc[keys.security_uid.eq("UID:A"), "security_uid"] = "UID:REPLACEMENT"
    _, swapped = qualify(changed, universe=keys)
    assert swapped["qualification_sha256"] != before["qualification_sha256"]
    changed = frame.copy()
    changed.loc[changed.security_uid.eq("UID:A"), "source_hash"] = "b" * 64
    _, other_source = qualify(changed)
    assert other_source["qualification_sha256"] != before["qualification_sha256"]


def test_63_global_sessions_are_not_shortened_or_asset_specific():
    frame, calendar, cutoff, universe = fixture_history()
    short = calendar[calendar < cutoff][-62:].append(calendar[calendar >= cutoff])
    out, receipt = qualify(frame, calendar=short)
    assert out.status.eq("BLOCKED_WINDOW").all()
    assert receipt["calendar_sessions"] == 62 and receipt["required_sessions"] == 63
    assert out.security_uid.tolist() == universe.security_uid.tolist()
    missing_asset_dates = frame.loc[~frame.security_uid.eq("UID:A") | frame.signal_date.ge(calendar[calendar < cutoff][-30])]
    out, receipt = qualify(missing_asset_dates)
    assert receipt["calendar_sessions"] == 63
    assert out.loc[0, "qualified_finite"] == 29  # first observed return has no predecessor proof


def test_future_universe_membership_rejected_before_return_inspection():
    frame, _, cutoff, universe = fixture_history()
    universe = universe.assign(membership_available_at=pd.Timestamp("2024-01-01T00:00:00Z"))
    frame["ret_1d"] = "MUST NOT INSPECT"
    with pytest.raises(ValueError, match="FUTURE_UNIVERSE"):
        qualify(frame, universe=universe)


def test_core_dependency_and_exact_four_role_contract_no_substitutes():
    assert preflight.assert_fixed_family(preflight.ROLES)["fit_units"] == 0
    status = preflight.core_dependency_status(dict.fromkeys(preflight.CORE, True))
    assert status["status"] == "CORE_DEPENDENCIES_PRESENT"
    dependencies = dict.fromkeys(preflight.CORE, True)
    dependencies.pop("LW")
    dependencies["FA"] = True
    assert preflight.core_dependency_status(dependencies)["missing_core"] == ["LW"]
    with pytest.raises(ValueError, match="FOUR_ROLE"):
        preflight.assert_fixed_family(preflight.ROLES[:3])
    for changed in ({"seed": 1}, {"cadence": "ANNUAL"}, {"window_sessions": 126},
                    {"min_observations": 29}, {"target": "OTHER_TARGET"}):
        with pytest.raises(ValueError, match="FIXED_SEED"):
            preflight.assert_fixed_family(preflight.ROLES, **changed)


def test_preflight_cannot_call_any_fit_prepare_covariance_or_outcome_reader(monkeypatch):
    from scripts.research.a2.training import selector_risk_features as annual
    from scripts.research.a2.training import selector_risk_challenge as runner
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import HistGradientBoostingRegressor

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight called a forbidden estimation or body reader")

    for name in ("fit_risk_estimator", "_prepare", "validate_covariance", "risk_matrix"):
        monkeypatch.setattr(risk, name, forbidden)
    for name in ("project", "frame_features"):
        monkeypatch.setattr(annual, name, forbidden)
    monkeypatch.setattr(runner, "bounded_risk_fit", forbidden)
    for cls in (StandardScaler, Ridge, HistGradientBoostingRegressor):
        monkeypatch.setattr(cls, "fit", forbidden)
    for name in ("cov", "var", "nanvar", "mean", "nanmean"):
        monkeypatch.setattr(np, name, forbidden)
    monkeypatch.setattr(pd, "read_parquet", forbidden)
    monkeypatch.setattr(pd, "read_csv", forbidden)
    out, receipt = qualify()
    assert receipt["fit_units"] == receipt["covariance_estimates"] == receipt["outcome_rows_read"] == 0
    assert out.history_qualified_for_estimation.tolist() == [True, True, False]



def test_same_ticker_new_uid_cannot_inherit_old_history_without_authorized_edge():
    frame, calendar, cutoff, universe, edge = reset_history()
    first = edge.first_date.iloc[0]
    current = frame.security_uid.eq("UID:A") & frame.signal_date.ge(first)
    frame.loc[current, "security_uid"] = "UID:REPLACEMENT"
    frame.loc[current & frame.signal_date.gt(first), "predecessor_uid"] = "UID:REPLACEMENT"
    universe.loc[universe.security_uid.eq("UID:A"), "security_uid"] = "UID:REPLACEMENT"
    out, _ = qualify(frame, universe=universe)
    assert out.loc[0, "status"] == "RESET_AND_QUARANTINE"
    assert out.loc[0, "qualified_finite"] == 31
    assert out.loc[0, "legacy_ticker_finite_diagnostic"] == 63
    edge["to_uid"] = "UID:REPLACEMENT"
    out, _ = qualify(frame, universe=universe, continuity_edges=edge, identity_policy=preflight.AUTHORIZED_CONTINUITY)
    assert out.loc[0, "status"] == "AUTHORIZED_CONTINUITY"
    assert out.loc[0, "qualified_finite"] == 63


def test_source_transition_resets_and_first_window_predecessor_is_digest_bound():
    frame, calendar, cutoff, _, edge = reset_history()
    first = edge.first_date.iloc[0]
    frame["identity_epoch"] = "E0"
    frame.loc[frame.security_uid.eq("UID:A") & frame.signal_date.ge(first), "source_hash"] = "b" * 64
    out, _ = qualify(frame)
    assert out.loc[0, "status"] == "RESET_AND_QUARANTINE" and out.loc[0, "qualified_finite"] == 31
    frame, calendar, cutoff, _ = fixture_history()
    out, before = qualify(frame)
    prior = calendar[calendar < cutoff][-64]
    frame.loc[frame.security_uid.eq("UID:A") & frame.signal_date.eq(prior), "source_hash"] = "b" * 64
    out, after = qualify(frame)
    assert out.loc[0, "qualified_finite"] == 62
    assert after["qualification_sha256"] != before["qualification_sha256"]


def test_nonfinite_returns_are_missing_without_imputation_or_bad_digest():
    frame, calendar, cutoff, _ = fixture_history()
    dates = calendar[calendar < cutoff][-63:]
    frame.loc[frame.security_uid.eq("UID:A") & frame.signal_date.isin(dates[:34]), "ret_1d"] = np.inf
    out, receipt = qualify(frame)
    assert out.loc[0, "qualified_finite"] == 29 and out.loc[0, "status"] == "FINITE_LT30"
    assert len(receipt["qualification_sha256"]) == 64


def test_duplicate_past_UID_keys_fail_and_future_duplicates_are_ignored():
    frame, _, cutoff, _ = fixture_history()
    duplicate = frame.loc[frame.signal_date.lt(cutoff)].iloc[[-1]]
    with pytest.raises(ValueError, match="AMBIGUOUS_PAST"):
        qualify(pd.concat([frame, duplicate], ignore_index=True))
    future = frame.loc[frame.signal_date.ge(cutoff)].iloc[[0]]
    out, receipt = qualify(pd.concat([frame, future], ignore_index=True))
    expected, metadata = qualify(frame)
    pd.testing.assert_frame_equal(out, expected)
    assert receipt == metadata



def test_unrelated_outcome_columns_are_not_part_of_projection_or_identity():
    frame, _, _, universe = fixture_history()
    out, receipt = qualify(frame, universe=universe)
    frame["target"] = np.inf
    frame["economic_score"] = "UNREAD OUTCOME SENTINEL"
    universe["target"] = -np.inf
    actual, metadata = qualify(frame, universe=universe)
    pd.testing.assert_frame_equal(actual, out)
    assert metadata == receipt



@pytest.mark.parametrize("field,value", [("identity_epoch", "NEW_EPOCH"), ("source_hash", "b" * 64)])
def test_current_universe_boundary_without_new_history_is_explicit_cold_reset(field, value):
    frame, _, _, universe = fixture_history()
    universe[field] = None
    universe.loc[universe.security_uid.eq("UID:A"), field] = value
    out, receipt = qualify(frame, universe=universe)
    row = out.iloc[0]
    assert row.status == "RESET_AND_QUARANTINE"
    assert row.reset_flag and row.cold_start_flag and row.unknown_proof_flag
    assert not row.authorized_continuity_flag
    assert row.potential_finite == row.qualified_finite == 0
    assert row.legacy_ticker_finite_diagnostic == 63
    assert out.security_uid.tolist() == universe.security_uid.tolist()
    assert receipt["source_accepted"] is False
    # The older known source remains bound even when the new epoch has no rows.
    changed = frame.copy()
    changed.loc[changed.security_uid.eq("UID:A"), "source_hash"] = "c" * 64
    _, other = qualify(changed, universe=universe)
    assert other["qualification_sha256"] != receipt["qualification_sha256"]


def test_label_end_before_signal_is_ineligible():
    assert preflight.mature_label_mask(["2023-01-30"], ["2023-01-27"], "2023-02-01").tolist() == [False]


@pytest.mark.parametrize("value,expected", [("0.001", True), (" -0.2 ", True),
    ("INVALID", False), ("NaN", False), (None, False), (pd.NA, False),
    (np.inf, False), ("1e999", False), (np.float64(.01), True)])
def test_scalar_finite_coercion_preserves_numeric_strings_and_invalid_absence(value, expected):
    assert preflight._finite(value) is expected


def test_qualification_does_not_use_per_return_numeric_series_coercion(monkeypatch):
    frame, calendar, cutoff, universe = fixture_history()
    expected, receipt = qualify(frame, calendar, cutoff, universe)
    def forbidden(*args, **kwargs):
        pytest.fail("Per-return Series numeric coercion must not be used")
    monkeypatch.setattr(preflight.pd, "to_numeric", forbidden)
    actual, metadata = qualify(frame, calendar, cutoff, universe)
    pd.testing.assert_frame_equal(actual, expected)
    assert metadata == receipt



def _shared_authority(row, *, cutoff, decision_at):
    assert row["signal_date"] < cutoff
    assert preflight._instant(row["available_at"]) < decision_at
    return row.get("source_hash") == "a" * 64


def panel(frame=None, calendar=None, cutoff=None, universe=None, **kwargs):
    base, sessions, cut, keys = fixture_history()
    cut = cut if cutoff is None else cutoff
    return preflight.canonical_uid_return_panel(
        base if frame is None else frame, sessions if calendar is None else calendar,
        cut, keys if universe is None else universe, cadence=kwargs.pop("cadence", "MONTHLY"),
        decision_at=kwargs.pop("decision_at", cut.tz_localize("America/New_York") + pd.Timedelta(hours=16)),
        source_authority=kwargs.pop("source_authority", _shared_authority), **kwargs)


def test_exact_registered_jan1_annual_and_matched_monthly_policy():
    frame, calendar, _, universe = fixture_history()
    annual_cut = pd.Timestamp("2023-01-01")  # Sunday, never moved to Jan 2.
    monthly_cut = pd.Timestamp("2023-01-02")
    annual, annual_coverage, annual_receipt = panel(frame, calendar, annual_cut, universe,
        cadence="ANNUAL", decision_at=annual_cut.tz_localize("America/New_York"))
    monthly, monthly_coverage, monthly_receipt = panel(frame, calendar, monthly_cut, universe)
    pd.testing.assert_frame_equal(annual, monthly)
    pd.testing.assert_frame_equal(annual_coverage, monthly_coverage)
    assert annual_receipt["cutoff_exclusive"] == "2023-01-01T00:00:00"
    assert annual_receipt["decision_at_exclusive"] == "2023-01-01T05:00:00+00:00"
    assert annual_receipt["identity_policy"] == monthly_receipt["identity_policy"] == preflight.NO_CROSS_IDENTITY_STITCHING
    assert annual_receipt["returns_sha256"] == monthly_receipt["returns_sha256"]
    assert preflight.annual_cutoffs() == tuple(pd.Timestamp(f"{y}-01-01") for y in preflight.YEARS)
    with pytest.raises(ValueError, match="EXACT_REGISTERED_JAN1"):
        panel(frame, calendar, monthly_cut, universe, cadence="ANNUAL")
    with pytest.raises(ValueError, match="EXACT_JAN1_MIDNIGHT"):
        panel(frame, calendar, annual_cut, universe, cadence="ANNUAL")
    with pytest.raises(ValueError, match="REGISTERED_YEARS"):
        preflight.annual_cutoffs((2021, 2022, 2023, 2024))


@pytest.mark.parametrize("year", preflight.YEARS)
def test_annual_supports_every_registered_year_and_preserves_full_UID_pool(year):
    calendar = pd.bdate_range(f"{year-1}-08-01", f"{year}-01-10")
    rows = []
    for i, day in enumerate(calendar):
        rows.append({"signal_date": day, "security_uid": "UID:A", "ticker": "A",
            "identity_epoch": "E0", "ret_1d": (i % 9 - 4) * .001,
            "available_at": day.tz_localize("America/New_York") + pd.Timedelta(hours=16),
            "source_hash": "a" * 64, "return_unit": preflight.UNIT,
            "predecessor_uid": "UID:A", "predecessor_date": calendar[i-1] if i else pd.NaT})
    universe = pd.DataFrame({"security_uid": ["UID:A", "UID:NEW"], "ticker": ["A", "NEW"]})
    cutoff = pd.Timestamp(f"{year}-01-01")
    table, coverage, receipt = panel(pd.DataFrame(rows), calendar, cutoff, universe,
        cadence="ANNUAL", decision_at=cutoff.tz_localize("America/New_York"))
    assert table.shape == (63, 2) and table.columns.tolist() == universe.security_uid.tolist()
    assert (table.index < cutoff).all() and coverage.qualified_finite.tolist() == [63, 0]
    assert coverage.risk_unknown_fallback.tolist() == [False, True]
    assert receipt["fit_units"] == receipt["covariance_estimates"] == receipt["outcome_rows_read"] == 0
    assert receipt["source_accepted"] is False


def test_no_cross_identity_stitching_masks_old_epoch_and_ignores_even_authorized_edges():
    frame, calendar, cutoff, universe, edge = reset_history()
    kwargs = dict(decision_at=cutoff.tz_localize("America/New_York") + pd.Timedelta(hours=16),
                  identity_policy=preflight.NO_CROSS_IDENTITY_STITCHING)
    coverage, receipt = preflight.qualify_history(frame, calendar, cutoff, universe,
        continuity_edges=edge, **kwargs)
    expected, expected_receipt = preflight.qualify_history(frame, calendar, cutoff, universe, **kwargs)
    pd.testing.assert_frame_equal(coverage, expected)
    assert receipt == expected_receipt
    assert coverage.loc[0, "qualified_finite"] == 31
    assert not coverage.authorized_continuity_flag.any()
    table, flags, metadata = panel(frame, calendar, cutoff, universe)
    assert table.loc[:edge.first_date.iloc[0], "UID:A"].isna().all()
    assert table["UID:A"].notna().sum() == 31
    assert metadata["identity_policy"] == preflight.NO_CROSS_IDENTITY_STITCHING
    assert not flags.loc[0, "risk_unknown_fallback"]


def test_missing_shared_source_authority_masks_all_history_and_keeps_full_U_t():
    table, coverage, receipt = panel(source_authority=None)
    assert table.isna().all().all() and table.shape == (63, 3)
    assert coverage.security_uid.tolist() == table.columns.tolist()
    assert coverage.qualified_finite.eq(0).all() and coverage.risk_unknown_fallback.all()
    assert receipt["status"] == "BLOCKED_SOURCE_AUTHORITY"
    assert receipt["full_U_t_preserved"] and not receipt["source_authority_supplied"]
    assert receipt["source_accepted"] is False
    with pytest.raises(ValueError, match="EXPLICIT_PANEL"):
        panel(decision_at=None)


def test_shared_authority_failure_and_missing_timestamp_never_invent_availability():
    frame, calendar, cutoff, universe = fixture_history()
    frame.loc[frame.security_uid.eq("UID:B"), "source_hash"] = "b" * 64
    frame.loc[frame.security_uid.eq("UID:A"), "available_at"] = None
    table, coverage, _ = panel(frame, calendar, cutoff, universe)
    assert table.isna().all().all() and coverage.risk_unknown_fallback.all()
    called = []
    def authority(row, **clock):
        called.append(row)
        return True
    row = frame.iloc[0].to_dict()
    assert not preflight.past_only_source_authority(row, cutoff=cutoff,
        decision_at=cutoff.tz_localize("America/New_York"), source_authority=authority)
    assert called == []


def test_monthly_explicit_close_uses_strict_availability_and_binds_timestamp():
    frame, calendar, cutoff, universe = fixture_history()
    last = calendar[calendar < cutoff][-1]
    closing = cutoff.tz_localize("America/New_York") + pd.Timedelta(hours=16)
    affected = frame.security_uid.eq("UID:A") & frame.signal_date.eq(last)
    frame.loc[affected, "available_at"] = closing - pd.Timedelta(seconds=1)
    table, _, receipt = panel(frame, calendar, cutoff, universe, decision_at=closing)
    assert table.loc[last, "UID:A"] == float(frame.loc[affected, "ret_1d"].iloc[0])
    assert receipt["decision_at_exclusive"] == closing.tz_convert("UTC").isoformat()
    frame.loc[affected, "available_at"] = closing
    late, _, _ = panel(frame, calendar, cutoff, universe, decision_at=closing)
    assert pd.isna(late.loc[last, "UID:A"])
    with pytest.raises(ValueError, match="AWARE_ON_CUTOFF"):
        panel(decision_at=cutoff + pd.Timedelta(hours=16))


def test_panel_and_authority_are_future_append_invariant_no_future_ticker_blacklist():
    frame, calendar, cutoff, universe = fixture_history()
    before = frame.loc[frame.signal_date.lt(cutoff)].copy()
    expected, flags, metadata = panel(before, calendar, cutoff, universe)
    future = before.iloc[[-2]].copy()
    future["signal_date"] = pd.Timestamp("2025-01-02")
    future["identity_epoch"] = "FUTURE_CUSIP_CHANGE"
    future["ret_1d"] = "MUST NOT INSPECT FUTURE VALUE"
    future["source_hash"] = "f" * 64
    extra_calendar = calendar.append(pd.DatetimeIndex(["2025-01-02"]))
    seen = []
    def authority(row, **clock):
        seen.append(row["signal_date"])
        return _shared_authority(row, **clock)
    actual, actual_flags, actual_meta = panel(pd.concat([before, future], ignore_index=True),
        extra_calendar, cutoff, universe, source_authority=authority)
    pd.testing.assert_frame_equal(actual, expected)
    pd.testing.assert_frame_equal(actual_flags, flags)
    assert actual_meta == metadata and all(day < cutoff for day in seen)
    assert actual["UID:A"].notna().sum() == 63


def test_same_ticker_new_uid_panel_never_receives_predecessor_identity_history():
    frame, calendar, cutoff, universe, edge = reset_history()
    first = edge.first_date.iloc[0]
    current = frame.security_uid.eq("UID:A") & frame.signal_date.ge(first)
    frame.loc[current, "security_uid"] = "UID:REPLACEMENT"
    frame.loc[current & frame.signal_date.gt(first), "predecessor_uid"] = "UID:REPLACEMENT"
    universe.loc[universe.security_uid.eq("UID:A"), "security_uid"] = "UID:REPLACEMENT"
    table, coverage, _ = panel(frame, calendar, cutoff, universe)
    assert table.columns.tolist() == universe.security_uid.tolist()
    assert table.loc[:first, "UID:REPLACEMENT"].isna().all()
    assert table["UID:REPLACEMENT"].notna().sum() == coverage.loc[0, "qualified_finite"] == 31
    assert coverage.loc[0, "legacy_ticker_finite_diagnostic"] == 63


def test_UID_panel_does_not_fit_prepare_or_project(monkeypatch):
    from scripts.research.a2.training import selector_risk_features as annual
    def forbidden(*args, **kwargs):
        pytest.fail("UID-return adapter called an estimator or projection")
    for name in ("fit_risk_estimator", "_prepare", "validate_covariance", "risk_matrix"):
        monkeypatch.setattr(risk, name, forbidden)
    for name in ("project", "frame_features", "annual_returns"):
        monkeypatch.setattr(annual, name, forbidden)
    for name in ("cov", "var", "nanvar", "mean", "nanmean"):
        monkeypatch.setattr(np, name, forbidden)
    for name in ("read_parquet", "read_csv"):
        monkeypatch.setattr(pd, name, forbidden)
    table, coverage, receipt = panel()
    assert table.notna().sum().tolist() == [63, 63, 0]
    assert coverage.risk_coverage_flag.tolist() == [False, False, True]
    assert receipt["fit_units"] == receipt["covariance_estimates"] == receipt["outcome_rows_read"] == 0



@pytest.mark.parametrize("field,value", [("identity_epoch", "E1"), ("source_hash", "b" * 64)])
def test_repeated_old_signature_does_not_reconnect_across_intermediate_epoch(field, value):
    frame, calendar, cutoff, universe = fixture_history()
    dates = calendar[calendar < cutoff][-63:]
    middle = frame.security_uid.eq("UID:A") & frame.signal_date.between(dates[10], dates[30])
    frame.loc[middle, field] = value
    table, coverage, _ = panel(frame, calendar, cutoff, universe)
    assert table.loc[:dates[31], "UID:A"].isna().all()
    assert table["UID:A"].notna().sum() == coverage.loc[0, "qualified_finite"] == 31
    assert coverage.loc[0, "reset_flag"]



def test_availability_proof_metadata_is_digest_bound_without_guessed_timestamps():
    frame, calendar, cutoff, universe = fixture_history()
    frame["epoch_available_at"] = frame.available_at
    universe["membership_available_at"] = pd.Timestamp("2022-07-01T00:00:00Z")
    universe["identity_available_at"] = pd.Timestamp("2022-07-01T00:00:00Z")
    expected, flags, receipt = panel(frame, calendar, cutoff, universe)
    changed = frame.copy()
    changed["epoch_available_at"] = changed.epoch_available_at - pd.Timedelta(minutes=1)
    actual, actual_flags, metadata = panel(changed, calendar, cutoff, universe)
    pd.testing.assert_frame_equal(actual, expected)
    pd.testing.assert_frame_equal(actual_flags, flags)
    assert metadata["qualification_sha256"] != receipt["qualification_sha256"]
    changed_keys = universe.copy()
    changed_keys["identity_available_at"] = pd.Timestamp("2022-07-02T00:00:00Z")
    _, _, metadata = panel(frame, calendar, cutoff, changed_keys)
    assert metadata["qualification_sha256"] != receipt["qualification_sha256"]



def test_monthly_default_is_conservative_even_when_edge_is_supplied():
    frame, _, _, _, edge = reset_history()
    out, receipt = qualify(frame, continuity_edges=edge)
    assert out.loc[0, "qualified_finite"] == 31
    assert receipt["identity_policy"] == preflight.NO_CROSS_IDENTITY_STITCHING
    assert not out.authorized_continuity_flag.any()


@pytest.mark.parametrize("source_authority", [_shared_authority, None])
def test_UID_panel_preserves_short_window_blocker(source_authority):
    frame, calendar, cutoff, universe = fixture_history()
    short = calendar[calendar < cutoff][-62:].append(calendar[calendar >= cutoff])
    table, coverage, receipt = panel(frame, short, cutoff, universe, source_authority=source_authority)
    assert table.shape == (62, 3) and table.isna().all().all()
    assert receipt["status"] == "BLOCKED_WINDOW" and receipt["calendar_sessions"] == 62
    assert not receipt["coverage_count_performed"] and coverage.risk_unknown_fallback.all()
    assert receipt["full_U_t_preserved"]


def test_annual_fit_pool_cannot_use_future_first_session_membership():
    frame, calendar, _, universe = fixture_history()
    cutoff = pd.Timestamp("2023-01-01")
    universe["membership_date"] = pd.Timestamp("2023-01-02")
    frame["ret_1d"] = "MUST NOT INSPECT BODY BEFORE UNIVERSE GATE"
    with pytest.raises(ValueError, match="FUTURE_OR_INVALID_UNIVERSE_MEMBERSHIP"):
        panel(frame, calendar, cutoff, universe, cadence="ANNUAL",
              decision_at=cutoff.tz_localize("America/New_York"))


@pytest.mark.parametrize("cadence,cutoff", [("MONTHLY", "2023-02-01"), ("ANNUAL", "2023-01-01")])
@pytest.mark.parametrize("missing_intermediate", [False, True])
def test_UID_reversion_resets_even_with_reused_epoch_source_and_CIK(cadence, cutoff, missing_intermediate):
    frame, calendar, _, universe = fixture_history()
    cutoff = pd.Timestamp(cutoff)
    dates = calendar[calendar < cutoff][-63:]
    frame["cik"] = "SAME_CIK_DOES_NOT_PROVE_CONTINUITY"
    middle = frame.security_uid.eq("UID:A") & frame.signal_date.between(dates[10], dates[30])
    frame.loc[middle, "security_uid"] = "UID:INTERMEDIATE"
    frame.loc[middle, "predecessor_uid"] = "UID:INTERMEDIATE"
    first_middle = frame.security_uid.eq("UID:INTERMEDIATE") & frame.signal_date.eq(dates[10])
    frame.loc[first_middle, "predecessor_uid"] = "UID:A"
    first_return = frame.security_uid.eq("UID:A") & frame.signal_date.eq(dates[31])
    frame.loc[first_return, "predecessor_uid"] = "UID:INTERMEDIATE"
    if missing_intermediate:
        frame = frame.loc[~frame.security_uid.eq("UID:INTERMEDIATE")].copy()
    table, coverage, metadata = panel(frame, calendar, cutoff, universe,
        cadence=cadence, decision_at=cutoff.tz_localize("America/New_York"))
    assert table.loc[:dates[31], "UID:A"].isna().all()
    assert table["UID:A"].notna().sum() == coverage.loc[0, "qualified_finite"] == 31
    assert coverage.loc[0, "reset_flag"]
    assert table.columns.tolist() == universe.security_uid.tolist()
    assert metadata["identity_policy"] == preflight.NO_CROSS_IDENTITY_STITCHING


def test_same_CIK_and_ticker_never_authorize_continuity():
    frame, calendar, cutoff, universe, edge = reset_history()
    frame["cik"] = universe["cik"] = "SAME_CIK"
    first = pd.Timestamp(edge.iloc[0]["first_date"])
    new = frame.security_uid.eq("UID:A") & frame.signal_date.ge(first)
    frame.loc[new, "security_uid"] = "UID:NEW_A"
    frame.loc[new, "predecessor_uid"] = "UID:NEW_A"
    frame.loc[new & frame.signal_date.eq(first), "predecessor_uid"] = "UID:A"
    universe.loc[universe.index[0], "security_uid"] = "UID:NEW_A"
    table, coverage, _ = panel(frame, calendar, cutoff, universe)
    assert table["UID:NEW_A"].notna().sum() == coverage.loc[0, "qualified_finite"] == 31
    assert table.loc[:first, "UID:NEW_A"].isna().all()
    assert not coverage.authorized_continuity_flag.any()


@pytest.mark.parametrize("cadence,cutoff", [("MONTHLY", "2023-02-01"), ("ANNUAL", "2023-01-01")])
def test_known_intermediate_UID_resets_reversion_without_declared_predecessor(cadence, cutoff):
    frame, calendar, _, universe = fixture_history()
    cutoff = pd.Timestamp(cutoff)
    dates = calendar[calendar < cutoff][-63:]
    middle = frame.security_uid.eq("UID:A") & frame.signal_date.between(dates[10], dates[30])
    frame.loc[middle, "security_uid"] = "UID:INTERMEDIATE"
    frame.loc[middle, "predecessor_uid"] = "UID:INTERMEDIATE"
    first_return = frame.security_uid.eq("UID:A") & frame.signal_date.eq(dates[31])
    frame.loc[first_return, "predecessor_uid"] = None
    frame.loc[first_return, "predecessor_date"] = pd.NaT
    table, coverage, receipt = panel(frame, calendar, cutoff, universe,
        cadence=cadence, decision_at=cutoff.tz_localize("America/New_York"))
    assert table.loc[:dates[31], "UID:A"].isna().all()
    assert table["UID:A"].notna().sum() == coverage.loc[0, "qualified_finite"] == 31
    assert coverage.loc[0, "reset_flag"]
    assert not coverage.authorized_continuity_flag.any()
    assert receipt["full_U_t_preserved"]


@pytest.mark.parametrize("cadence,cutoff", [("MONTHLY", "2023-02-01"), ("ANNUAL", "2023-01-01")])
def test_current_roster_UID_reversion_without_new_history_cannot_reuse_old_segment(cadence, cutoff):
    frame, calendar, _, universe = fixture_history()
    cutoff = pd.Timestamp(cutoff)
    dates = calendar[calendar < cutoff][-63:]
    middle = frame.security_uid.eq("UID:A") & frame.signal_date.ge(dates[10])
    frame.loc[middle, "security_uid"] = "UID:INTERMEDIATE"
    frame.loc[middle, "predecessor_uid"] = "UID:INTERMEDIATE"
    table, coverage, receipt = panel(frame, calendar, cutoff, universe,
        cadence=cadence, decision_at=cutoff.tz_localize("America/New_York"))
    assert table["UID:A"].isna().all()
    assert coverage.loc[0, "qualified_finite"] == 0
    assert coverage.loc[0, "reset_flag"] and coverage.loc[0, "risk_unknown_fallback"]
    assert table.columns.tolist() == universe.security_uid.tolist()
    assert receipt["full_U_t_preserved"]
