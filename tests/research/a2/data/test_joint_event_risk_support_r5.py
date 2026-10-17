"""Pure metadata temporal/UID/event tests; no actual source or outcome reader."""
import copy
import pandas as pd
import pytest
from scripts.research.a2.data import joint_event_risk_support_r5 as m


def fixtures():
    days = pd.bdate_range("2022-12-01", "2023-01-13")
    frame = pd.DataFrame([dict(ticker=a, signal_date=d, security_id="UID_"+a, feature_available=True, all_features_finite=True, feature_source=m.old.FEATURE_TAGS[0]) for d in days for a in ("A", "B")])
    raw = pd.DataFrame([dict(ticker=a, trade_date=d, code="US."+a) for d in days for a in ("A", "B", "OFF")])
    return days, frame, raw


@pytest.mark.parametrize("case", ["stable", "uid_change", "gap", "duplicate", "offpool_unknown", "offpool_duplicate", "eligible_unknown", "unknown_eligible_later"])
def test_streaming_suffix_is_exact_original_helper(case):
    days, frame, raw = fixtures(); d = pd.Timestamp("2023-01-04")
    if case == "uid_change": frame.loc[frame.ticker.eq("B") & frame.signal_date.ge(d), "security_id"] = "NEW_B"
    if case == "gap": frame = frame.loc[~(frame.ticker.eq("B") & frame.signal_date.eq(d))]
    if case == "duplicate": frame = pd.concat([frame, frame.loc[frame.ticker.eq("B") & frame.signal_date.eq(d)]], ignore_index=True)
    if case == "eligible_unknown": frame.loc[frame.ticker.eq("B") & frame.signal_date.eq(d), "security_id"] = None
    if case in {"offpool_unknown", "offpool_duplicate", "unknown_eligible_later"}:
        added = frame.loc[frame.ticker.eq("A")].copy(); added["ticker"] = "OFF"; added["security_id"] = None
        added["feature_available"] = added.signal_date.ge(d) if case == "unknown_eligible_later" else False
        frame = pd.concat([frame, added, added if case == "offpool_duplicate" else added.iloc[:0]], ignore_index=True)
    cursor = m.MetadataPoolCursor(days)
    for day in days:
        today, r = frame.loc[frame.signal_date.eq(day)], raw.loc[raw.trade_date.eq(day)]
        actual = cursor.step(day, today, r)
        expected = m.old.current_pool(frame.loc[frame.signal_date.le(day)], r, days, m._clock(day))
        assert m.content_hash(m.pool_identity(actual)) == m.content_hash(m.pool_identity(expected))


def label_fixture(days, uid="UID_A"):
    labels = pd.DataFrame([dict(ticker="A", signal_date=days[i], execution_date=days[i+1], label_end_date=days[i+6], label_mature_date=days[i+6], label_coordinate=m.STORED_LABEL_COORDINATE, label_available=True, endpoint_pair_available=True, label_unsupported_common_event=False) for i in range(len(days)-6)])
    base = labels.loc[:, ["ticker", "signal_date"]].copy(); base["security_id"] = uid
    return labels, base


def test_current_uid_clock_is_separate_from_prior_maturity_and_no_stitch():
    days, frame, raw = fixtures(); labels, base = label_fixture(days)
    day = pd.Timestamp("2023-01-04"); cutoff_index = days.get_loc(day)-1
    prior_pool = m.old.current_pool(frame, raw.loc[raw.trade_date.eq(day)], days, m._clock(day))
    idx = m.HistoryMetadataIndex(labels, base, days)
    support = idx.qualify(prior_pool, cutoff_index)
    # An observation whose mature date equals the prior cutoff is excluded.
    assert support["nominal_n"]["A"] == cutoff_index-6
    new_pool = copy.deepcopy(prior_pool); new_pool["asset_uids"]["A"] = "NEW_A"; new_pool["segment_starts"]["A"] = str(day.date())
    cold = idx.qualify(new_pool, cutoff_index)
    assert cold["nominal_n"]["A"] == 0 and "A" in cold["short0"]
    assert cold["observations_fabricated"] == 0 and cold["prior_predictive_activation"] == "REQUIRES_EXPLICIT_R5_SCIENTIFIC_FREEZE"


def test_support_flags_duplicates_and_coordinates_block_without_values():
    days, frame, raw = fixtures(); labels, base = label_fixture(days)
    pool = m.old.current_pool(frame, raw.loc[raw.trade_date.eq(days[-1])], days, m._clock(days[-1]))
    cutoff = len(days)-2
    good = m.HistoryMetadataIndex(labels, base, days).qualify(pool, cutoff)
    labels.loc[0, "label_available"] = False
    reduced = m.HistoryMetadataIndex(labels, base, days).qualify(pool, cutoff)
    assert reduced["nominal_n"]["A"] == good["nominal_n"]["A"]-1
    labels.loc[1, "label_coordinate"] = "WRONG"
    bad = m.HistoryMetadataIndex(labels, base, days).qualify(pool, cutoff)
    assert bad["source_metadata_blockers"]["A"] == "WRONG_REQUIRED_STORED_LABEL_COORDINATE"
    with pytest.raises(ValueError, match="NUMERIC_OR_SCORE"):
        m.HistoryMetadataIndex(labels.assign(y_open5=0.), base, days)
    duplicate = pd.concat([base, base.iloc[:1]], ignore_index=True)
    dup = m.HistoryMetadataIndex(labels, duplicate, days).qualify(pool, cutoff)
    assert "A" in dup["source_metadata_blockers"]


def test_structural_trigger_ignores_normal_clock_and_label_append():
    days, frame, raw = fixtures(); pool = m.old.current_pool(frame, raw.loc[raw.trade_date.eq(days[10])], days, m._clock(days[10]))
    signature = m.structural_signature(pool, source_identity={"coordinate":"H5"}, coordinates={"A":"SHARES"}, ff48={"A":None}, feature_tags={"A":"RAW"})
    assert m.reasons(signature, copy.deepcopy(signature)) == []
    updated = copy.deepcopy(signature); updated["asset_uids"]["A"] = "NEW_A"
    assert m.reasons(signature, updated) == ["CURRENT_UID_CHANGE"]
    updated = copy.deepcopy(signature); updated["security_coordinates"]["A"] = "ADS"
    assert m.reasons(signature, updated) == ["SECURITY_COORDINATE_CHANGE"]
    assert not any(k in signature for k in ("cutoff", "nominal_n", "matured_origins", "y_open5"))


def test_ff48_fast_lookup_exact_reference_and_no_future_backfill():
    rows = pd.DataFrame([dict(decision_date="2023-01-03", canonical_security_id="UID_A", ticker_at_date="A", sic_available_at="2023-01-04T21:00:00Z", ff48_code=12, identity_status="AUTHORITATIVE", taxonomy_status="STRICT_PIT_SIC_FF12_FF48_MAPPED", sic_source_sha256="a"*64, source_fingerprints="SIC_META")])
    rows["_decision"] = pd.to_datetime(rows.decision_date); rows["_available"] = pd.to_datetime(rows.sic_available_at, utc=True)
    pool = {"assets":("A",), "asset_uids":{"A":"UID_A"}}
    idx = m.FF48MetadataIndex(rows)
    for date in ("2023-01-03", "2023-01-04", "2023-01-05"):
        cutoff = m._clock(date)
        assert idx.lookup(pool, cutoff) == m.ff48_lookup_reference(rows, pool, cutoff)
    assert idx.lookup(pool, m._clock("2023-01-03"))["A"] is None


def test_coordinate_fast_lookup_exact_reference_at_inclusive_interval_boundary():
    rows = pd.DataFrame([dict(effective_start="2023-01-03", effective_end="2023-01-06", ticker="A", security_id="UID_A", security_id_type="CUSIP", cusip="CUSIP_A", title_of_class="COMMON", moomoo_transport_code="US.A", mapping_status="MAPPED")])
    rows["_start"] = pd.to_datetime(rows.effective_start); rows["_end"] = pd.to_datetime(rows.effective_end)
    raw = pd.DataFrame({"ticker":["A"],"code":["US.A"]}); pool={"assets":("A",),"asset_uids":{"A":"UID_A"}}
    idx = m.CoordinateMetadataIndex(rows)
    for date in ("2023-01-02", "2023-01-03", "2023-01-06", "2023-01-09"):
        day=pd.Timestamp(date)
        assert idx.lookup(pool,day,raw)==m.coordinate_lookup_reference(rows,pool,day,raw)