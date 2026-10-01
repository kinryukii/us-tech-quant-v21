"""Replay qualified close inputs; no provider acquisition or model calls."""
import importlib.util
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[4] / "scripts/research/a2/portfolio/selected_hgb.py"
spec = importlib.util.spec_from_file_location("selected_hgb_close_test_backend", MODULE_PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


@pytest.fixture
def inputs(monkeypatch, tmp_path):
    from scripts import daily_recommendation_prices as prices
    from scripts.storage import storage_r2a
    from scripts.storage.refresh_massive_market import ENDPOINT
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Network forbidden"))
    monkeypatch.setattr(backend, "_runtime", lambda *a, **k: pytest.fail("No inference or fit"))
    days = pd.bdate_range(end="2026-09-25", periods=126)
    sessions, target = days.strftime("%Y-%m-%d").tolist(), "2026-09-25"
    original = pd.DataFrame({"trade_date": days[:-5], "ticker": "TEST", "provider_code": "US.TEST",
        "source": "MOOMOO_OPEND", "adjustment": "raw", "open": 100 + np.arange(121) * .25,
        "close": 100.1 + np.arange(121) * .25, "high": 100.2 + np.arange(121) * .25,
        "low": 99.9 + np.arange(121) * .25, "volume": 1000 + np.arange(121)})
    raw_path = tmp_path / "moomoo.parquet"
    original.to_parquet(raw_path, index=False)
    massive_rows, references = [], []
    # Include enough earlier source bars to test an internal real-session gap.
    for index in range(95, 126):
        day = sessions[index]
        stamp = int(days[index].tz_localize("UTC").timestamp() * 1000)
        values = {"T": "TEST", "o": 100 + index * .25, "c": 100.1 + index * .25,
                  "h": 100.2 + index * .25, "l": 99.9 + index * .25, "v": 1000 + index + .375, "t": stamp}
        leaf = tmp_path / "days" / day / "response.json"
        leaf.parent.mkdir(parents=True)
        leaf.write_text(json.dumps({"status": "OK", "adjusted": False, "resultsCount": 1, "results": [values]}), encoding="utf-8")
        observed = day + "T22:00:00Z"
        ref = {"path": str(leaf), "sha256": backend.digest(leaf), "date": day, "observed_at": observed}
        checkpoint = leaf.parent / "checkpoint.json"
        checkpoint.write_text(json.dumps({"status": "SUCCESS", "contract": {"date": day, "url": ENDPOINT + day,
            "params": {"adjusted": "false", "include_otc": "false"}},
            "raw": {"path": str(leaf), "sha256": ref["sha256"]}, "observed_at": observed}), encoding="utf-8")
        references.append(ref)
        massive_rows.append({"ticker": "TEST", "date": day, "source": "MASSIVE_GROUPED", "adjustment": "raw",
            "provider_code": "TEST", "source_id": ref["sha256"], "observed_at": observed,
            "source_timestamp_ms": stamp, "currency": "USD", "open": values["o"], "close": values["c"],
            "high": values["h"], "low": values["l"], "volume": values["v"]})
    normalized = tmp_path / "massive.parquet"
    pd.DataFrame(massive_rows).to_parquet(normalized, index=False)
    record = {"dataset": "prices_daily_massive", "source": "MASSIVE_GROUPED", "ticker": "TEST",
        "adjustment": "raw", "format": "parquet", "max_date": target,
        "path": str(normalized), "source_sha256": backend.digest(normalized),
        "lineage": {"provider": "MASSIVE_GROUPED", "price_basis": "RAW", "currency": "USD",
            "exchange_timezone": "America/New_York", "provider_symbol": "TEST",
            "provider_mapping": {"provider_symbol": "TEST", "evidence_url": None}, "inputs": references}}

    class Store:
        def resolve_price_inputs(self, value, *, verify_raw):
            assert verify_raw is False
            return value["lineage"]["inputs"]

        def metadata(self, *args):
            pytest.fail("A mutable catalog pointer must not replace the saved snapshot")

    store = Store()
    monkeypatch.setattr(storage_r2a, "DataStore", lambda: store)
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"adjustment": {"wolf_event_date": "2026-06-15", "wolf_new_shares_per_old_share": 1}}), encoding="utf-8")
    monkeypatch.setattr(prices, "COVERAGE_PATH", coverage)
    monkeypatch.setattr(prices, "COVERAGE_SHA", backend.digest(coverage))
    rehab = tmp_path / "rehab.parquet"
    pd.DataFrame(columns=["code", "forward_adj_factorA", "forward_adj_factorB"]).to_parquet(rehab, index=False)
    adjust_calls = []

    class Adapter:
        @staticmethod
        def adjusted_price_frame(code, ticker, raw, factors, wolf):
            adjust_calls.append(raw.copy())
            adjusted = raw.copy()
            adjusted["ticker"] = ticker
            adjusted["close"] = adjusted.close / float(adjusted.close.iloc[0])
            return adjusted, []

    monkeypatch.setattr(prices, "_adapter", lambda day: Adapter)
    _, proof = prices._qualified_massive_tail(record, prices._raw_frame(original, "US.TEST"), "TEST", target, store)
    saved = {"ticker": "TEST", "code": "US.TEST", "anchor_date": sessions[0],
        "raw_sources": [{"path": str(raw_path), "sha256": backend.digest(raw_path)}],
        "alternate_bridge": proof, "rehab": {"path": str(rehab), "sha256": backend.digest(rehab)}}
    return {"prices": prices, "saved": saved, "record": record, "original": original, "store": store,
            "sessions": sessions, "days": days, "target": target, "adjust_calls": adjust_calls,
            "raw_path": raw_path, "normalized": normalized}


def complete(value):
    return backend.complete_close_inputs(pd.DataFrame(columns=["ticker", "trade_date", "close", "volume"]),
        [value["saved"]], ["TEST"], value["target"], value["sessions"])


def test_qualified_massive_replays_original_anchor_all_121_sessions_and_ten_lags(inputs):
    result = complete(inputs)
    assert len(result) == 121
    assert pd.to_datetime(result.trade_date).dt.strftime("%Y-%m-%d").tolist() == inputs["sessions"][-121:]
    full = inputs["adjust_calls"][0]
    assert len(full) == 126 and full.trade_date.iloc[0] == inputs["days"][0]
    assert np.equal(result.volume, np.floor(result.volume)).all()
    expected = pd.Series(100.1 + np.arange(115, 126) * .25).pct_change(fill_method=None).iloc[1:].to_numpy()
    actual = result.close.astype(float).iloc[-11:].pct_change(fill_method=None).iloc[1:].to_numpy()
    np.testing.assert_allclose(actual, expected, rtol=0, atol=3e-16)


def test_unknown_provider_or_transport_alias_remains_explicitly_blocked(inputs):
    inputs["saved"]["alternate_bridge"]["provider"] = "YAHOO_CHART"
    with pytest.raises(backend.SelectedStrategyError, match="BRIDGE_UNSUPPORTED"):
        complete(inputs)
    inputs["saved"]["alternate_bridge"]["provider"] = "MASSIVE_GROUPED"
    inputs["saved"]["alternate_bridge"]["transport_alias_proof"] = {"source_ticker": "OTHER"}
    with pytest.raises(backend.SelectedStrategyError, match="BRIDGE_UNSUPPORTED"):
        complete(inputs)
    assert not inputs["adjust_calls"]


@pytest.mark.parametrize("kind", ["normalized", "raw_leaf", "checkpoint"])
def test_changed_immutable_source_or_checkpoint_rejected_before_adjustment(inputs, kind):
    bridge = inputs["saved"]["alternate_bridge"]
    if kind == "normalized":
        bridge["normalized_sha256"] = "0" * 64
    elif kind == "raw_leaf":
        leaf = Path(bridge["raw_inputs"][-1]["path"])
        leaf.write_text("{}", encoding="utf-8")
    else:
        path = Path(bridge["raw_inputs"][-1]["checkpoint_path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["note"] = "bytes changed after qualification"
        path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="HASH_MISMATCH|BRIDGE_PROOF_MISMATCH"):
        complete(inputs)
    assert not inputs["adjust_calls"]


@pytest.mark.parametrize("field", ["close", "volume"])
def test_five_session_ohlcv_and_integer_volume_gate_not_relaxed(inputs, field):
    frame = inputs["original"].copy()
    frame[field] = frame[field].astype(float)
    frame.loc[frame.index[-1], field] += .125
    frame.to_parquet(inputs["raw_path"], index=False)
    inputs["saved"]["raw_sources"][0]["sha256"] = backend.digest(inputs["raw_path"])
    with pytest.raises(ValueError, match="OVERLAP_MISMATCH:close|VOLUME_NOT_NONNEGATIVE_WHOLE_SHARES"):
        complete(inputs)
    assert not inputs["adjust_calls"]


def test_missing_real_tail_session_is_rejected_not_shifted_or_filled(inputs):
    frame = pd.read_parquet(inputs["normalized"])
    frame = frame.loc[frame.date.ne(inputs["sessions"][-3])]
    frame.to_parquet(inputs["normalized"], index=False)
    inputs["saved"]["alternate_bridge"]["normalized_sha256"] = backend.digest(inputs["normalized"])
    inputs["record"]["source_sha256"] = backend.digest(inputs["normalized"])
    raw = inputs["prices"]._raw_frame(inputs["original"], "US.TEST")
    _, proof = inputs["prices"]._qualified_massive_tail(inputs["record"], raw, "TEST", inputs["target"], inputs["store"])
    inputs["saved"]["alternate_bridge"] = proof
    with pytest.raises(ValueError, match="NEW_RAW_TAIL_SESSION_GAP"):
        complete(inputs)
    assert not inputs["adjust_calls"]


def test_existing_verified_internal_gap_uses_the_original_five_session_prefix_gate(inputs):
    missing = inputs["sessions"][100]
    original = inputs["original"].loc[inputs["original"].trade_date.ne(pd.Timestamp(missing))]
    original.to_parquet(inputs["raw_path"], index=False)
    inputs["saved"]["raw_sources"][0]["sha256"] = backend.digest(inputs["raw_path"])
    raw = inputs["prices"]._raw_frame(original, "US.TEST")
    _, proof = inputs["prices"]._qualified_massive_tail(inputs["record"], raw, "TEST", inputs["target"],
                                                    inputs["store"], gap_dates=[missing])
    inputs["saved"]["alternate_bridge"] = proof
    result = complete(inputs)
    assert len(result) == 121 and result.trade_date.is_unique
    assert missing in set(pd.to_datetime(result.trade_date).dt.strftime("%Y-%m-%d"))


def test_saved_bridge_qualification_is_not_trusted_without_replayed_proof(inputs):
    inputs["saved"]["alternate_bridge"]["overlap_sessions"] = 99
    with pytest.raises(backend.SelectedStrategyError, match="BRIDGE_PROOF_MISMATCH"):
        complete(inputs)
    assert not inputs["adjust_calls"]
