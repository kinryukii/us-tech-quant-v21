"""Synthetic parquet fixtures only; no real research inputs, fits or covariance."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.data import selector_frozen_history as fh
from scripts.research.a2.training import selector_risk_preflight as preflight


def _frames(end="2022-06-30"):
    dates = pd.bdate_range("2021-09-01", end)
    features = pd.DataFrame([{"signal_date": day, "ticker": name, "ret_1d": .001}
                            for day in dates for name in ("AAA", "BBB")])
    members = features[["signal_date", "ticker"]].copy()
    members["cusip"] = members.ticker.map({"AAA": "000000001", "BBB": "000000002"})
    return features, members


def _reader(tmp_path, features=None, members=None, mutate=None):
    if features is None:
        features, members = _frames()
    inputs = {}
    for kind, frame in (("features", features), ("members", members)):
        path = tmp_path / (kind + ".parquet")
        frame.to_parquet(path, index=False)
        inputs[kind] = {"path": str(path), "sha256": fh.sha256(path)}
    auth = tmp_path / "human.txt"
    auth.write_text("synthetic declared frozen-history authorization", encoding="utf-8")
    contract = fh.build_source_contract(inputs, research_id=fh.RESEARCH_ID,
                                      human_authorization_ref={"path": str(auth), "sha256": fh.sha256(auth)})
    if mutate:
        mutate(contract)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return fh.FrozenHistoryReader(path, fh.sha256(path))


def _panel(reader, cutoff="2022-04-01", cadence="MONTHLY"):
    data = reader({"cutoff": cutoff, "cadence": cadence})
    panel, coverage, metadata = preflight.canonical_uid_return_panel(
        data["history"], data["accepted_sessions"], cutoff, data["universe"],
        cadence=cadence, decision_at=data["decision_at"], source_authority=data["source_authority"])
    return data, panel, coverage, metadata


def test_mechanism_only_real_projection_and_full_ut(tmp_path):
    reader = _reader(tmp_path)
    data, panel, coverage, metadata = _panel(reader)
    assert reader.contract["strict_PIT_promotion_eligible"] is False
    assert reader.contract["historical_available_at_proved"] is False
    assert list(panel.columns) == ["CUSIP:000000001", "CUSIP:000000002"]
    assert panel.shape == (63, 2) and panel.notna().all().all()
    assert coverage.history_qualified_for_estimation.all()
    assert metadata["source_accepted"] is False  # mechanical helper never promotes authority
    assert data["source_authority"](data["universe"], cutoff="2022-04-01",
        decision_at=data["decision_at"], proof_kind="CUTOFF_KNOWN_UNIVERSE",
        source_proof_sha256=data["source_proof_sha256"])


def test_exact_jan1_not_january_first_session_and_no_future_roster(tmp_path):
    features, members = _frames()
    entrant = pd.DataFrame([{"signal_date": pd.Timestamp("2022-01-03"), "ticker": "NEW", "ret_1d": .4}])
    features = pd.concat([features, entrant], ignore_index=True)
    new_members = entrant[["signal_date", "ticker"]].assign(cusip="000000003")
    members = pd.concat([members, new_members], ignore_index=True)
    reader = _reader(tmp_path, features, members)
    a, annual, _, _ = _panel(reader, "2022-01-01", "ANNUAL")
    m, monthly, _, _ = _panel(reader, "2022-01-03", "MONTHLY")
    pd.testing.assert_frame_equal(annual, monthly)
    assert a["decision_at"] == pd.Timestamp("2022-01-01", tz="America/New_York").tz_convert("UTC")
    assert a["roster_date"].startswith("2021-12-31")
    assert "CUSIP:000000003" not in a["universe"].security_uid.tolist()
    assert "CUSIP:000000003" not in m["universe"].security_uid.tolist()
    with pytest.raises(ValueError, match="EXACT_REGISTERED_JAN1"):
        reader({"cutoff": "2022-01-03", "cadence": "ANNUAL"})


def test_observed_uid_change_and_first_return_quarantine(tmp_path):
    features, members = _frames()
    members.loc[members.ticker.eq("AAA") & members.signal_date.ge("2022-03-01"), "cusip"] = "000000009"
    reader = _reader(tmp_path, features, members)
    _, panel, coverage, _ = _panel(reader)
    assert panel["CUSIP:000000009"].loc[pd.Timestamp("2022-03-01"):] .iloc[0] != .001
    assert panel["CUSIP:000000009"].loc[:"2022-03-01"].isna().all()
    assert coverage.loc[coverage.ticker.eq("AAA"), "reset_flag"].item()
    assert coverage.loc[coverage.ticker.eq("AAA"), "risk_unknown_fallback"].item()


def test_uid_reversion_and_gap_create_distinct_daily_epoch(tmp_path):
    features, members = _frames()
    change = members.ticker.eq("AAA") & members.signal_date.between("2022-02-01", "2022-02-28")
    members.loc[change, "cusip"] = "000000009"
    gap = features.ticker.eq("BBB") & features.signal_date.eq("2022-03-01")
    features, members = features.loc[~gap].reset_index(drop=True), members.loc[~gap].reset_index(drop=True)
    reader = _reader(tmp_path, features, members)
    keys = pd.DataFrame({"signal_date": pd.to_datetime(["2022-01-31", "2022-03-01", "2022-02-28", "2022-03-02"]),
                         "security_uid": ["CUSIP:000000001", "CUSIP:000000001", "CUSIP:000000002", "CUSIP:000000002"]})
    epochs = reader.epoch_keys(keys)
    assert epochs[0] != epochs[1] and epochs[2] != epochs[3]
    _, panel, _, _ = _panel(reader)
    assert panel["CUSIP:000000001"].loc[:"2022-03-01"].isna().all()
    assert panel["CUSIP:000000002"].loc[:"2022-03-02"].isna().all()


def test_declared_local_clock_dst_is_not_receipt_available_at(tmp_path):
    reader = _reader(tmp_path)
    history = reader.history
    for day in ("2022-03-11", "2022-03-14"):
        actual = history.loc[history.signal_date.eq(day), "available_at"].iloc[0]
        assert actual.tz_convert("America/New_York").hour == 16
    assert reader.contract["observation_clock"] == fh.POLICY_CLOCK
    assert reader.contract["historical_revision_vintage_proved"] is False


def test_source_authority_rejects_tampered_return_universe_or_clock(tmp_path):
    reader = _reader(tmp_path)
    data = reader({"cutoff": "2022-04-01", "cadence": "MONTHLY"})
    row = data["history"].iloc[-1].to_dict()
    predicate = data["source_authority"]
    assert predicate(row, cutoff="2022-04-01", decision_at=data["decision_at"])
    for field, bad in [("ret_1d", .9), ("identity_epoch", "fake"), ("source_hash", "0"*64),
                       ("predecessor_uid", "CUSIP:WRONG"), ("return_unit", "percentage")]:
        altered = dict(row, **{field: bad})
        assert not predicate(altered, cutoff="2022-04-01", decision_at=data["decision_at"])
    data["universe"].loc[0, "ticker"] = "TAMPERED"
    assert not predicate(data["universe"], cutoff="2022-04-01", decision_at=data["decision_at"],
        proof_kind="CUTOFF_KNOWN_UNIVERSE", source_proof_sha256=data["source_proof_sha256"])
    assert not predicate(row, cutoff="2022-05-02", decision_at=data["decision_at"])


@pytest.mark.parametrize("field,value", [("strict_PIT_promotion_eligible", True),
    ("historical_available_at_proved", True), ("historical_revision_vintage_proved", True),
    ("identity_policy", "AUTHORIZED_CONTINUITY"), ("session_timezone", "UTC"),
    ("observation_clock", "PROVED_AVAILABLE"), ("accepted_calendar_sha256", "0"*64),
    ("return_coordinate", "TOTAL_RETURN"), ("return_horizon_sessions", 5)])
def test_unlawful_authority_upgrades_rejected(tmp_path, field, value):
    with pytest.raises(ValueError, match="SEMANTICS_INVALID"):
        _reader(tmp_path, mutate=lambda c: c.update({field: value}))


def test_mixed2026_rejected_before_any_body(monkeypatch, tmp_path):
    features, members = _frames("2026-01-02")
    from pyarrow.parquet import ParquetFile
    monkeypatch.setattr(ParquetFile, "read", lambda *a, **k: pytest.fail("BODY BEFORE BOUNDARY"))
    with pytest.raises(ValueError, match="Forbidden mixed/test input"):
        _reader(tmp_path, features, members)


def test_projection_does_not_read_outcomes_or_unrelated_prices(monkeypatch, tmp_path):
    features, members = _frames()
    features["close"] = "NEVER READ"
    features["target"] = "NEVER READ"
    features["a1_rank"] = "NEVER READ"
    from pyarrow.parquet import ParquetFile
    original = ParquetFile.read
    calls = []
    def read(file, columns=None, **kwargs):
        assert columns is not None
        assert not {"close", "target", "a1_rank"}.intersection(columns)
        calls.append(columns)
        return original(file, columns=columns, **kwargs)
    monkeypatch.setattr(ParquetFile, "read", read)
    reader = _reader(tmp_path, features, members)
    assert calls == [["signal_date"], fh.PROJECTIONS["features"], fh.PROJECTIONS["members"]]
    assert len(reader.history) == len(features)


def test_full_ut_key_or_identity_ambiguity_blocked(tmp_path):
    features, members = _frames()
    members = members.iloc[1:].copy()
    with pytest.raises(ValueError, match="FULL_U_INPUT_KEYS_DIFFER"):
        _reader(tmp_path, features, members)


def test_future_append_does_not_change_prior_values_or_epoch(tmp_path):
    features, members = _frames()
    contract = {"accepted_sessions": [pd.Timestamp(day).isoformat() for day in sorted(features.signal_date.unique())],
                "sources": {"features": {"sha256": "a"*64}}}
    base = fh._records(features, members, contract)
    more_features, more_members = _frames("2022-08-31")
    more_members.loc[more_members.ticker.eq("AAA") & more_members.signal_date.ge("2022-07-01"), "cusip"] = "000000009"
    contract2 = copy.deepcopy(contract)
    contract2["accepted_sessions"] = [pd.Timestamp(day).isoformat() for day in sorted(more_features.signal_date.unique())]
    extended = fh._records(more_features, more_members, contract2)
    pd.testing.assert_frame_equal(base, extended.loc[extended.signal_date.le("2022-06-30")].reset_index(drop=True))


def test_external_mutation_cannot_change_cached_authority(tmp_path):
    reader = _reader(tmp_path)
    external_history = reader.history
    external_history.loc[:, "ret_1d"] = .9
    reader.contract["strict_PIT_promotion_eligible"] = True
    _, panel, _, _ = _panel(reader)
    assert np.allclose(panel, .001)
    assert reader.contract["strict_PIT_promotion_eligible"] is False
    reader.path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="CHANGED_AFTER_LOAD"):
        reader({"cutoff": "2022-04-01", "cadence": "MONTHLY"})


def test_epoch_lookup_rejects2026_and_unknown_identity(tmp_path):
    reader = _reader(tmp_path)
    with pytest.raises(ValueError, match="2026_EPOCH_LOOKUP_LOCKED"):
        reader.epoch_keys(pd.DataFrame({"signal_date": ["2026-01-02"], "security_uid": ["CUSIP:000000001"]}))
    with pytest.raises(ValueError, match="DAILY_FULL_U_IDENTITY_MISSING"):
        reader.epoch_keys(pd.DataFrame({"signal_date": ["2022-01-03"], "security_uid": ["CUSIP:UNKNOWN"]}))
