"""Pure generated-input packaging checks; no readers and no risk fit calls."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.data.shared_risk_inputs_r3 import assemble_risk_inputs, STORED_LABEL_COORDINATE
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt, COORDINATE, BENCHMARK_PROXY_COORDINATE

NY = "America/New_York"


def close(day):
    return (pd.Timestamp(day)+pd.Timedelta(hours=16)).tz_localize(NY).tz_convert("UTC")


class UnreadableValue:
    def __float__(self):
        raise AssertionError("VALUE_MUST_NOT_BE_ACCESSED")


@pytest.fixture
def package():
    days = pd.bdate_range("2024-03-01", "2024-04-19")
    cutoff = close("2024-04-15")
    epoch = "GENERATED_CURRENT_UID_EPOCH"
    receipt = SourceReceipt("GENERATED_STOCK_LABELS", "GENERATED_V1", "a"*64, close("2023-01-03"),
        synthetic=False, mechanism=True, identity_epoch=epoch,
        status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND", scientific_contract_identity="GENERATED_CONTRACT",
        scientific_contract_sha256="d"*64, actual_snapshot_timestamp=pd.Timestamp("2026-10-03T06:00:00Z"),
        observation_time_assumed=True)
    qreceipt = replace(receipt, source_identity="GENERATED_QQQ_OPENS", source_sha256="b"*64,
                       return_coordinate=BENCHMARK_PROXY_COORDINATE, benchmark_proxy_allowed=True,
                       identity_epoch="GENERATED_QQQ_EPOCH")
    ireceipt = replace(receipt, source_identity="GENERATED_FF48", source_sha256="c"*64)
    names = ("A", "B")
    uids = {a:"CUSIP:"+a for a in names}
    history = pd.DataFrame([dict(ticker=a, signal_date=d, security_id=uids[a], available_at=close(d))
                            for a in names for d in days])
    labels = pd.DataFrame([dict(ticker=a, signal_date=days[i], security_id=uids[a],
        execution_date=days[i+1], label_end_date=days[i+6], label_mature_date=days[i+6],
        label_coordinate=STORED_LABEL_COORDINATE, label_available=True,
        label_unsupported_common_event=False, endpoint_pair_available=True, y_open5=i/1000)
        for a in names for i in range(len(days)-6)]).astype({"y_open5":object,"label_available":object,"label_unsupported_common_event":object})
    quotes = pd.DataFrame(dict(ticker="QQQ", trade_date=days, open=100+np.arange(len(days)), close=999.)).astype({"open":object})
    groups = pd.DataFrame([dict(asset=a, uid=uids[a], group=i+1,
                                available_at=close("2024-03-01"), effective_at=close("2024-03-01"))
                           for i,a in enumerate(names)])
    return dict(stored_labels=labels, calendar_sessions=days, assets=names, asset_uids=uids,
                identity_epoch=epoch, source_receipt=receipt, cutoff=cutoff, identity_history=history,
                qqq_opens=quotes, qqq_receipt=qreceipt, industry_mapping=groups, industry_receipt=ireceipt)


def build(package, **updates):
    return assemble_risk_inputs(**{**package, **updates})


def test_stored_h5_clock_dst_and_independent_open_proxy(package):
    result = build(package)
    inputs, declaration = result.risk_input, result.support_declarations
    assert inputs.assets == package["assets"] and inputs.source_receipt.return_coordinate == COORDINATE
    assert inputs.observations.horizon.unique().tolist() == [5]
    before = inputs.observations.loc[inputs.observations.origin_at.eq(close("2024-03-08"))].iloc[0]
    assert before.origin_at.hour == 21  # NY16 before DST.
    assert before.entry_at.hour == 13 and before.entry_at.minute == 30  # Monday NY09:30 after DST.
    assert before.endpoint_at.hour == 13 and before.matured_at.hour == 20
    for c in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        assert inputs.observations[c].lt(package["cutoff"]).all()
    q = inputs.qqq_observations
    first = q.loc[q.horizon.eq(5)].iloc[0]
    assert first.return_value == pytest.approx(106/101-1)
    assert set(q.horizon) == {1, 5} and q.available_at.eq(q.matured_at).all()
    assert declaration["method_block_reasons"]["RM"] == ["BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20"]
    assert declaration["method_block_reasons"]["RB"] == []
    assert not declaration["numeric_fit_executed"] and not declaration["strict_PIT_promotion_eligible"]


def test_label_missing_unsupported_and_unknown_flags_remain_nan(package):
    labels = package["stored_labels"].copy()
    labels.loc[0, "y_open5"] = np.nan
    labels.loc[1, "label_unsupported_common_event"] = True
    labels.loc[1, "y_open5"] = UnreadableValue()
    labels.loc[2, "label_available"] = False
    labels.loc[2, "y_open5"] = UnreadableValue()
    labels.loc[3, "label_unsupported_common_event"] = None
    labels.loc[3, "y_open5"] = UnreadableValue()
    result = build(package, stored_labels=labels)
    a = result.risk_input.observations.loc[lambda x: x.asset.eq("A")]
    assert a.iloc[:4].return_value.isna().all()
    assert result.support_declarations["inference_support"] == {"A":True,"B":True}


def test_inference_support_is_unchanged_by_future_or_complete_labels(package):
    baseline = build(package)
    labels = package["stored_labels"].copy()
    labels["label_available"] = False
    labels["y_open5"] = [UnreadableValue() for _ in range(len(labels))]
    labels["label_complete"] = False  # Deliberately forbidden inference-support input.
    changed = build(package, stored_labels=labels)
    assert changed.support_declarations["inference_support"] == baseline.support_declarations["inference_support"]
    assert changed.risk_input.assets == baseline.risk_input.assets
    assert changed.risk_input.observations.return_value.isna().all()


def test_current_uid_segment_never_stitches_old_uid_or_membership_gap(package):
    history = package["identity_history"].copy()
    swap_date = pd.Timestamp("2024-03-12")
    history.loc[history.ticker.eq("A") & history.signal_date.eq(swap_date), "security_id"] = "OLD_UID"
    history = history.loc[~(history.ticker.eq("B") & history.signal_date.eq(swap_date))]
    result = build(package, identity_history=history)
    for asset in package["assets"]:
        segment = result.support_declarations["observed_current_segments"][asset]
        assert segment["start_date"] == "2024-03-13"
        assert result.risk_input.observations.loc[lambda x: x.asset.eq(asset)].origin_at.ge(close("2024-03-13")).all()


def test_current_uid_unproven_asset_retained_and_all_directions_blocked(package):
    history = package["identity_history"].copy()
    history.loc[history.ticker.eq("B") & history.signal_date.eq(pd.Timestamp("2024-04-15")), "security_id"] = "OTHER_UID"
    result = build(package, identity_history=history)
    assert result.risk_input.assets == ("A", "B")
    assert result.support_declarations["inference_support"] == {"A":True,"B":False}
    assert not result.risk_input.observations.asset.eq("B").any()
    assert all("BLOCK_REQUESTED_ASSET_IDENTITY_SUPPORT" in v for v in result.support_declarations["method_block_reasons"].values())


def test_label_uid_swap_cannot_borrow_other_security_return(package):
    labels = package["stored_labels"].copy()
    labels.loc[0, "security_id"] = "OTHER_UID"
    labels.loc[0, "y_open5"] = UnreadableValue()
    result = build(package, stored_labels=labels)
    assert not ((result.risk_input.observations.asset == "A") & result.risk_input.observations.origin_at.eq(close("2024-03-01"))).any()


@pytest.mark.parametrize("field", ["signal_date", "execution_date", "label_end_date", "label_mature_date"])
def test_no_2026_metadata_precedes_label_numeric_access(package, field):
    labels = package["stored_labels"].copy()
    labels.loc[0, field] = pd.Timestamp("2026-01-02")
    labels.loc[0, "y_open5"] = UnreadableValue()
    with pytest.raises(ValueError, match="PRE2026"):
        build(package, stored_labels=labels)


@pytest.mark.parametrize("change", ["bad_maturity", "bad_entry", "bad_horizon", "missing_maturity"])
def test_bad_stored_clock_fails_before_value_read(package, change):
    labels = package["stored_labels"].copy()
    labels.loc[0, "y_open5"] = UnreadableValue()
    if change == "bad_maturity": labels.loc[0, "label_mature_date"] = labels.loc[0, "execution_date"]
    elif change == "bad_entry": labels.loc[0, "execution_date"] = labels.loc[0, "signal_date"]
    elif change == "bad_horizon": labels.loc[0, "label_end_date"] = package["calendar_sessions"][5]
    else: labels.loc[0, "label_mature_date"] = pd.NaT
    with pytest.raises(ValueError, match="MATURITY|H5_CLOCK"):
        build(package, stored_labels=labels)


def test_immature_stored_values_are_not_accessed(package):
    labels = package["stored_labels"].copy()
    immature = labels.label_mature_date.ge(pd.Timestamp("2024-04-15"))
    labels.loc[immature, "y_open5"] = [UnreadableValue() for _ in range(int(immature.sum()))]
    result = build(package, stored_labels=labels)
    assert result.risk_input.observations.matured_at.lt(package["cutoff"]).all()


def test_missing_qqq_open_blocks_dependents_without_close_fallback(package):
    result = build(package, qqq_opens=package["qqq_opens"].drop(columns="open"))
    assert result.risk_input.qqq_observations is None
    assert "NO_CLOSE_SUBSTITUTION" in result.support_declarations["qqq_binding_reason"]
    assert result.support_declarations["method_block_reasons"]["R0"] == []
    for method in ("RB", "RH", "RR", "RE"):
        assert result.support_declarations["method_block_reasons"][method]


def test_qqq_missing_quotes_remain_nan_no_interpolation(package):
    opens = package["qqq_opens"].copy()
    opens.loc[1, "open"] = np.nan
    result = build(package, qqq_opens=opens)
    assert result.risk_input.qqq_observations.loc[lambda x: x.origin_at.eq(close("2024-03-01"))].return_value.isna().all()


def test_future_qqq_numeric_not_read_and_close_proxy_contract_rejected(package):
    opens = package["qqq_opens"].copy()
    opens.loc[0, "trade_date"] = pd.Timestamp("2026-01-02")
    opens.loc[0, "open"] = UnreadableValue()
    result = build(package, qqq_opens=opens)
    assert "PRE2026" in result.support_declarations["qqq_binding_reason"]
    assert result.risk_input.qqq_observations is None
    receipt = replace(package["qqq_receipt"], return_coordinate="frozen_qfq_close_return_proxy")
    result = build(package, qqq_receipt=receipt)
    assert result.risk_input.qqq_observations is None


def test_ff48_is_asof_and_uid_bound_not_latest_backfill(package):
    groups = package["industry_mapping"].copy()
    future = groups.iloc[:1].copy()
    future["group"] = 48
    future["effective_at"] = future["available_at"] = close("2024-04-16")
    groups = pd.concat([groups, future], ignore_index=True)
    result = build(package, industry_mapping=groups)
    assert result.risk_input.industry_mapping.set_index("asset").loc["A", "group"] == 1
    groups.loc[1, "uid"] = "OTHER_UID"
    result = build(package, industry_mapping=groups)
    assert result.support_declarations["method_block_reasons"]["RH"]
    assert not result.risk_input.industry_mapping.asset.eq("B").any()


def test_calendar_explicit_ny_close_and_no_2026(package):
    close_calendar = pd.DatetimeIndex([close(d) for d in package["calendar_sessions"]])
    assert build(package, calendar_sessions=close_calendar).risk_input.sessions.equals(close_calendar)
    with pytest.raises(ValueError, match="PRE2026"):
        build(package, calendar_sessions=[*package["calendar_sessions"], pd.Timestamp("2026-01-02")])
    with pytest.raises(ValueError, match="NY1600"):
        build(package, calendar_sessions=close_calendar-pd.Timedelta(hours=1))


def test_explicit_epoch_change_breaks_continuity_without_uid_change(package):
    history = package["identity_history"].copy()
    history["identity_epoch"] = package["identity_epoch"]
    old = history.ticker.eq("A") & history.signal_date.le(pd.Timestamp("2024-03-12"))
    history.loc[old, "identity_epoch"] = "OLD_EPOCH_SAME_UID"
    result = build(package, identity_history=history)
    assert result.support_declarations["observed_current_segments"]["A"]["start_date"] == "2024-03-13"
    assert result.risk_input.observations.loc[lambda x: x.asset.eq("A")].origin_at.ge(close("2024-03-13")).all()
    history.loc[history.ticker.eq("A") & history.signal_date.eq(pd.Timestamp("2024-04-15")), "identity_epoch"] = "UNKNOWN_CURRENT_EPOCH"
    result = build(package, identity_history=history)
    assert not result.support_declarations["inference_support"]["A"]


def test_explicit_per_asset_epoch_and_stale_label_are_not_stitched(package):
    history = package["identity_history"].copy()
    history["identity_epoch"] = history.ticker.map({"A":"EPOCH_A", "B":"EPOCH_B"})
    labels = package["stored_labels"].copy()
    labels["identity_epoch"] = labels.ticker.map({"A":"EPOCH_A", "B":"EPOCH_B"})
    labels.loc[0, "identity_epoch"] = "STALE_EPOCH"
    labels.loc[0, "y_open5"] = UnreadableValue()
    result = build(package, identity_history=history, stored_labels=labels,
                   asset_epochs={"A":"EPOCH_A", "B":"EPOCH_B"})
    assert result.risk_input.observations.identity_epoch.eq(package["identity_epoch"]).all()
    assert result.support_declarations["current_asset_epochs"] == {"A":"EPOCH_A", "B":"EPOCH_B"}
    assert not ((result.risk_input.observations.asset == "A") & result.risk_input.observations.origin_at.eq(close("2024-03-01"))).any()


def test_explicit_row_availability_is_honored_before_label_value_access(package):
    labels = package["stored_labels"].copy()
    labels["available_at"] = labels.label_mature_date.map(close)
    labels.loc[0, "available_at"] = close("2024-04-16")
    labels.loc[0, "y_open5"] = UnreadableValue()
    result = build(package, stored_labels=labels)
    assert not ((result.risk_input.observations.asset == "A") & result.risk_input.observations.origin_at.eq(close("2024-03-01"))).any()
    assert result.support_declarations["inference_support"] == {"A":True,"B":True}
    labels.loc[0, "available_at"] = close("2024-03-01")
    with pytest.raises(ValueError, match="PRECEDES_MATURITY"):
        build(package, stored_labels=labels)


@pytest.fixture
def rr_range_case(package, monkeypatch):
    from scripts.research.a2.data.shared_risk_inputs_r3 import _qqq_observations, _clock
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskInput
    from scripts.research.a2.risk.shared_risk_budget_r2 import StateCache
    monkeypatch.setattr(StateCache, "learn", lambda *args, **kwargs:
        (_ for _ in ()).throw(AssertionError("LEARN_FORBIDDEN_IN_SOURCE_RANGE_CHECK")))
    days = pd.bdate_range("2020-01-02", periods=1000)
    closes = pd.DatetimeIndex([_clock(d) for d in days])
    stop_position = 900
    start_position = stop_position - 360
    opens = pd.DataFrame(dict(ticker="QQQ", trade_date=days[start_position:stop_position],
                              open=100.+np.arange(360)))
    cutoff = closes[stop_position]
    frame = _qqq_observations(opens, days, closes, package["qqq_receipt"],
                              package["source_receipt"], cutoff)
    inputs = RiskInput(package["assets"], closes,
        pd.DataFrame({"return_value": [UnreadableValue()]}), package["source_receipt"],
        package["asset_uids"], package["identity_epoch"],
        qqq_observations=frame, qqq_receipt=package["qqq_receipt"],
        industry_mapping=package["industry_mapping"], industry_receipt=package["industry_receipt"])
    kwargs = dict(cutoff=cutoff, open_start_date=days[start_position],
                  open_stop_date_exclusive=days[stop_position])
    return inputs, kwargs, opens, days, closes


def corrected(case, **updates):
    from scripts.research.a2.data.shared_risk_inputs_r3 import correct_rr_qqq_source_range
    inputs, kwargs, *_ = case
    return correct_rr_qqq_source_range(inputs, **{**kwargs, **updates})


def test_rr_source_range_complete_clocks_immutable_inputs_and_zero_fit(rr_range_case):
    inputs, kwargs, _, days, closes = rr_range_case
    original = inputs.qqq_observations.copy(deep=True)
    result = corrected(rr_range_case)
    assert result is not inputs and result.qqq_observations is not inputs.qqq_observations
    for name in ("assets", "sessions", "observations", "source_receipt", "asset_uids",
                 "qqq_receipt", "industry_mapping", "industry_receipt"):
        assert getattr(result, name) is getattr(inputs, name)
    pd.testing.assert_frame_equal(inputs.qqq_observations, original)
    bounded = result.qqq_observations
    daily = bounded.loc[bounded.horizon.eq(1)]
    assert len(daily) == 359 and len(bounded.loc[bounded.horizon.eq(5)]) == 355
    assert np.isfinite(daily.return_value).all() and original.return_value.isna().any()
    pd.testing.assert_frame_equal(bounded, original.loc[bounded.index])
    finite = np.isfinite(daily.return_value.to_numpy())
    valid20 = np.array([i >= 19 and finite[i-19:i+1].all() for i in range(len(finite))])
    assert valid20.sum() == 340  # Metadata support count; no std, threshold or mean fit.
    stock_origins = closes[900-258:900-6]
    prior = pd.DatetimeIndex(daily.available_at).searchsorted(stock_origins, side="left")-1
    assert len(stock_origins) == 252 and valid20[prior].all()
    assert bounded.attrs["rr_qqq_source_range"]["projected_open_sessions"] == 360


@pytest.mark.parametrize("position,missing", [(0, 1), (180, 2), (359, 1)])
def test_rr_source_range_preserves_missing_edge_and_interior_open_slots(rr_range_case, position, missing):
    from scripts.research.a2.data.shared_risk_inputs_r3 import _qqq_observations
    inputs, kwargs, opens, days, closes = rr_range_case
    broken = opens.drop(opens.index[position])
    frame = _qqq_observations(broken, days, closes, inputs.qqq_receipt, inputs.source_receipt, kwargs["cutoff"])
    case = (replace(inputs, qqq_observations=frame), kwargs, opens, days, closes)
    bounded = corrected(case).qqq_observations
    daily = bounded.loc[bounded.horizon.eq(1)]
    assert len(daily) == 359 and daily.return_value.isna().sum() == missing


def test_rr_source_range_does_not_access_return_or_stock_values(rr_range_case):
    inputs, kwargs, *_ = rr_range_case
    frame = inputs.qqq_observations.astype({"return_value": object})
    mask = frame.horizon.eq(1) & frame.entry_at.ge(close(kwargs["open_start_date"]))
    index = frame.loc[mask].index[0]
    token = UnreadableValue()
    frame.at[index, "return_value"] = token
    result = corrected((replace(inputs, qqq_observations=frame), kwargs))
    assert result.qqq_observations.at[index, "return_value"] is token


@pytest.mark.parametrize("field,delta", [("open_start_date", -1), ("open_stop_date_exclusive", -1)])
def test_rr_source_range_rejects_changed_declared_projection(rr_range_case, field, delta):
    inputs, kwargs, _, days, closes = rr_range_case
    value = days[days.get_loc(kwargs[field])+delta]
    with pytest.raises(ValueError, match="DIFFERS_FROM_DECLARED_PRIOR360"):
        corrected(rr_range_case, **{field: value})


@pytest.mark.parametrize("field", ["entry_at", "endpoint_at", "matured_at", "available_at"])
def test_rr_source_range_rejects_original_clock_tampering(rr_range_case, field):
    inputs, kwargs, *_ = rr_range_case
    frame = inputs.qqq_observations.copy()
    frame.at[frame.index[0], field] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="OBSERVATION_CLOCK_MISMATCH"):
        corrected((replace(inputs, qqq_observations=frame), kwargs))


@pytest.mark.parametrize("field", ["uid", "identity_epoch", "source_identity"])
def test_rr_source_range_rejects_uid_epoch_or_source_swap(rr_range_case, field):
    inputs, kwargs, *_ = rr_range_case
    frame = inputs.qqq_observations.copy()
    frame.at[frame.index[0], field] = "FOREIGN_GENERATED_METADATA"
    with pytest.raises(ValueError, match="IDENTITY_OR_SOURCE_MISMATCH"):
        corrected((replace(inputs, qqq_observations=frame), kwargs))


def test_rr_source_range_rejects_missing_slot_instead_of_compressing_sessions(rr_range_case):
    inputs, kwargs, *_ = rr_range_case
    bounded = corrected(rr_range_case).qqq_observations
    removed = bounded.loc[bounded.horizon.eq(1)].index[20]
    frame = inputs.qqq_observations.drop(removed)
    with pytest.raises(ValueError, match="OBSERVATION_SLOTS_MISSING"):
        corrected((replace(inputs, qqq_observations=frame), kwargs))


@pytest.mark.parametrize("cutoff", [pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2024-07-01")])
def test_rr_source_range_rejects_2026_or_naive_cutoff(rr_range_case, cutoff):
    with pytest.raises(ValueError, match="PRE2026|EXPLICIT_TIMEZONE"):
        corrected(rr_range_case, cutoff=cutoff)


def test_rr_source_range_rejects_non_close_cutoff(rr_range_case):
    with pytest.raises(ValueError, match="LEGAL_PRIOR_CLOSE"):
        corrected(rr_range_case, cutoff=rr_range_case[1]["cutoff"]-pd.Timedelta(minutes=1))


def test_rr_source_range_rejects_duplicate_slots(rr_range_case):
    inputs, kwargs, *_ = rr_range_case
    frame = pd.concat([inputs.qqq_observations, inputs.qqq_observations.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="DUPLICATE_OBSERVATION_SLOT"):
        corrected((replace(inputs, qqq_observations=frame), kwargs))
