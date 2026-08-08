"""Focused contract tests for the forward-only Clean-Room R2 shadow."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_cleanroom_r2_prospective_shadow_r1.py"
SPEC = importlib.util.spec_from_file_location("cleanroom_r2_shadow_r1", SOURCE)
SHADOW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SHADOW)


def identity():
    return {"models": {"UP_HGB": {"path": "up"}, "DOWN_HGB": {"path": "down"}},
            "thresholds": dict(SHADOW.EXPECTED_THRESHOLDS)}


def signal(timestamp, decision="UP"):
    timestamp = pd.Timestamp(timestamp, tz="UTC")
    return {"candidate_id": SHADOW.candidate_id("QQQ", timestamp), "candidate_timestamp_utc": timestamp,
            "candidate_timestamp_et": timestamp.tz_convert(SHADOW.ET), "underlying": "QQQ",
            "decision": decision, "payoff_maturity_timestamp_utc": timestamp + pd.Timedelta(hours=24)}


def test_registration_boundary_is_immutable_and_strictly_forward(tmp_path):
    frozen = tmp_path / "frozen"
    first = pd.Timestamp("2026-08-08T10:02:01Z")
    registration = SHADOW.ensure_registration(frozen, identity(), first)
    again = SHADOW.ensure_registration(frozen, identity(), first - pd.Timedelta(days=1))
    assert SHADOW.utc(registration["shadow_start_candidate_time_utc"]) == pd.Timestamp("2026-08-08T10:05:00Z")
    assert SHADOW.utc(again["shadow_start_candidate_time_utc"]) == SHADOW.utc(registration["shadow_start_candidate_time_utc"])


def test_historical_candidate_in_prospective_ledger_fails_closed(tmp_path):
    root = tmp_path / "signals"
    old = signal("2026-08-08T10:00:00Z")
    SHADOW.append_immutable_rows(root, [old], "signal_row_sha256", pd.Timestamp("2026-08-08T10:01:00Z"))
    rows = SHADOW.read_immutable_ledger(root, "signal_row_sha256", "candidate_id")
    assert SHADOW.utc(rows[0]["candidate_timestamp_utc"]) < pd.Timestamp("2026-08-08T10:05:00Z")


def test_frozen_model_threshold_and_execution_contract_identity():
    verified = SHADOW.verify_frozen_identity()
    assert verified["model_identity_verified"] is True
    assert verified["thresholds_verified"] is True
    assert verified["execution_contract_verified"] is True


def test_immature_signal_cannot_open_payoff(monkeypatch):
    item = signal("2026-08-08T10:00:00Z")
    monkeypatch.setattr(SHADOW, "R2", object())
    result = SHADOW.mature_signals([item], [], SHADOW.CANONICAL_ROOT, pd.Timestamp("2026-08-09T09:59:00Z"))
    assert result == []


def test_matured_signal_can_enter_payoff_path(monkeypatch):
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as payoff

    item = signal("2026-08-08T10:00:00Z")
    fields = {"up_payoff_valid": True, "up_action_instrument": "TQQQ", "up_entry_timestamp_et": pd.Timestamp("2026-08-08T10:01:00Z"),
              "up_actual_exit_timestamp_et": pd.Timestamp("2026-08-09T10:01:00Z"), "up_entry_price": 10.0,
              "up_exit_price": 11.0, "up_action_net_return_20bps": .098, "up_invalid_reason": None,
              "payoff_row_hash": "payoff-hash"}
    called = []
    def fake_construct(candidates, canonical):
        called.append(candidates)
        return pd.DataFrame([fields]), {}
    monkeypatch.setattr(payoff, "construct_payoffs", fake_construct)
    result = SHADOW.mature_signals([item], [], SHADOW.CANONICAL_ROOT, pd.Timestamp("2026-08-09T10:00:00Z"))
    assert len(called) == 1
    assert result[0]["maturity_status"] == "EXECUTED_TRADE"


def test_duplicate_rerun_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("FAST3_SHADOW_TEST_MODE", "1")
    monkeypatch.setattr(SHADOW, "verify_frozen_identity", identity)
    candidate = pd.DataFrame({"candidate_id": [SHADOW.candidate_id("QQQ", pd.Timestamp("2026-08-08T10:05:00Z"))]})
    monkeypatch.setattr(SHADOW, "available_candidates", lambda *_: (candidate, "2026-08-08T10:06:00+00:00"))
    row = signal("2026-08-08T10:05:00Z"); row.update({"up_hgb_score": .9, "down_hgb_score": .1, "up_selected": True,
                                                        "down_selected": False, "feature_values": {}, "feature_asof_timestamp_utc": row["candidate_timestamp_utc"],
                                                        "model_hashes": SHADOW.EXPECTED_MODELS, "thresholds": SHADOW.EXPECTED_THRESHOLDS,
                                                        "execution_contract_sha256": SHADOW.COMPLETED_CONTRACT_SHA256,
                                                        "signal_registration_timestamp_utc": pd.Timestamp("2026-08-08T10:00:00Z"), "payoff_opened": False})
    monkeypatch.setattr(SHADOW, "score_and_resolve", lambda frame, *_: [row] if not frame.empty else [])
    monkeypatch.setattr(SHADOW, "mature_signals", lambda *_: [])
    root = tmp_path / "external"
    now = pd.Timestamp("2026-08-08T10:00:00Z")
    first = SHADOW.run(root / "runtime", root / "scratch", root / "frozen", tmp_path / "cache", SHADOW.CANONICAL_ROOT, now, now)
    second = SHADOW.run(root / "runtime", root / "scratch", root / "frozen", tmp_path / "cache", SHADOW.CANONICAL_ROOT, now, now)
    assert first["NEW_PROSPECTIVE_CANDIDATES"] == 1
    assert second["NEW_PROSPECTIVE_CANDIDATES"] == 0
    assert second["DUPLICATE_SIGNAL_REGISTRATION_COUNT"] == 0


class _Model:
    def __init__(self, values): self.values = values
    def predict_proba(self, frame): return np.c_[1 - np.asarray(self.values[:len(frame)]), self.values[:len(frame)]]


def candidate_frame():
    timestamp = pd.Timestamp("2026-08-08T10:05:00Z")
    rows = []
    for underlying in ("QQQ", "SOXX"):
        row = {name: 0.0 for name in SHADOW.R1.FEATURES}
        row.update({"candidate_id": SHADOW.candidate_id(underlying, timestamp), "underlying_symbol": underlying,
                    "decision_timestamp_utc": timestamp, "max_feature_timestamp_utc": timestamp, "direction_code_down": -1})
        rows.append(row)
    return pd.DataFrame(rows)


def test_simultaneous_opposite_direction_abstains(monkeypatch):
    models = iter([_Model([.9, .1]), _Model([.1, .9])])
    monkeypatch.setattr(SHADOW.joblib, "load", lambda _: next(models))
    decisions = SHADOW.score_and_resolve(candidate_frame(), identity()["models"], {"UP_HGB_THRESHOLD": .5, "DOWN_HGB_THRESHOLD": .5}, pd.Timestamp("2026-08-08T10:06:00Z"))
    assert {row["decision"] for row in decisions} == {"OPPOSITE_DIRECTION_TIE_ABSTAIN"}


def test_simultaneous_same_direction_cross_underlying_abstains(monkeypatch):
    models = iter([_Model([.9, .9]), _Model([.1, .1])])
    monkeypatch.setattr(SHADOW.joblib, "load", lambda _: next(models))
    decisions = SHADOW.score_and_resolve(candidate_frame(), identity()["models"], {"UP_HGB_THRESHOLD": .5, "DOWN_HGB_THRESHOLD": .5}, pd.Timestamp("2026-08-08T10:06:00Z"))
    assert {row["decision"] for row in decisions} == {"SAME_DIRECTION_CROSS_UNDERLYING_TIE_ABSTAIN"}


def test_no_repository_local_cache_or_temp_is_created():
    before = {path for path in (Path(__file__).parents[2]).rglob("*") if path.name in {"__pycache__", ".pytest_cache", ".local_results"}}
    assert SHADOW.next_five_minute(pd.Timestamp("2026-08-08T10:00:01Z")) == pd.Timestamp("2026-08-08T10:05:00Z")
    after = {path for path in (Path(__file__).parents[2]).rglob("*") if path.name in {"__pycache__", ".pytest_cache", ".local_results"}}
    assert after == before
