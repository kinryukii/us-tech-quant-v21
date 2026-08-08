import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_prospective_shadow_launcher.py"
SPEC = importlib.util.spec_from_file_location("r28_shadow", SOURCE)
SHADOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHADOW)
REGISTRATION = "2026-08-08T13:18:00.4750706Z"


def rows(model_id, timestamp="2026-08-08T13:20:00Z"):
    base = pd.DataFrame({"candidate_id": ["QQQ|UP|" + timestamp, "QQQ|DOWN|" + timestamp], "head": ["UP", "DOWN"],
                         "timestamp": [timestamp, timestamp], "symbol": ["QQQ", "QQQ"], "model_id": model_id,
                         "research_identity": model_id, "model_role": "CHAMPION" if model_id == "FAST3_CLEANROOM_R2" else "CHALLENGER",
                         "model_sha256": "a" * 64, "feature_snapshot_hash": "b" * 64, "probability": [.6, .4],
                         "threshold": [.5, .5], "selected": [True, False], "execution_eligible": [True, True]})
    return base


def test_same_timestamp_common_universe_creates_two_model_rows_per_candidate():
    ledger = SHADOW.immutable_shadow_ledger(rows("FAST3_CLEANROOM_R2"), rows("FAST3_R28_3_CROSS_ASSET_FLOW"), REGISTRATION, "2026-08-08T13:19:00Z")
    assert len(ledger) == 4 and ledger.ledger_row_hash.nunique() == 4


def test_common_universe_mismatch_is_rejected():
    challenger = rows("FAST3_R28_3_CROSS_ASSET_FLOW").iloc[:1]
    with pytest.raises(ValueError, match="COMMON_UNIVERSE_MISMATCH"):
        SHADOW.immutable_shadow_ledger(rows("FAST3_CLEANROOM_R2"), challenger, REGISTRATION, "2026-08-08T13:19:00Z")


def test_duplicate_candidate_is_rejected():
    duplicate = pd.concat([rows("FAST3_CLEANROOM_R2"), rows("FAST3_CLEANROOM_R2").iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="DUPLICATE_CANDIDATE"):
        SHADOW.immutable_shadow_ledger(duplicate, rows("FAST3_R28_3_CROSS_ASSET_FLOW"), REGISTRATION, "2026-08-08T13:19:00Z")


def test_historical_backfill_is_rejected():
    with pytest.raises(ValueError, match="HISTORICAL_BACKFILL_FORBIDDEN"):
        SHADOW.immutable_shadow_ledger(rows("FAST3_CLEANROOM_R2", "2026-08-08T13:15:00Z"), rows("FAST3_R28_3_CROSS_ASSET_FLOW", "2026-08-08T13:15:00Z"), REGISTRATION, "2026-08-08T13:19:00Z")


def test_outcome_columns_are_rejected_before_freeze():
    bad = rows("FAST3_CLEANROOM_R2").assign(outcome=1)
    with pytest.raises(ValueError, match="OUTCOME_FIELD_FORBIDDEN"):
        SHADOW.immutable_shadow_ledger(bad, rows("FAST3_R28_3_CROSS_ASSET_FLOW"), REGISTRATION, "2026-08-08T13:19:00Z")


def test_maturity_guard_refuses_unmatured_signal():
    ledger = SHADOW.immutable_shadow_ledger(rows("FAST3_CLEANROOM_R2"), rows("FAST3_R28_3_CROSS_ASSET_FLOW"), REGISTRATION, "2026-08-08T13:19:00Z")
    assert not SHADOW.maturity_ready(ledger, "2026-08-09T13:19:59Z").any()
    assert SHADOW.maturity_ready(ledger, "2026-08-09T13:20:00Z").all()


class FixedModel:
    def predict_proba(self, frame):
        return __import__("numpy").column_stack([__import__("numpy").full(len(frame), .4), __import__("numpy").full(len(frame), .6)])


def test_dual_scorer_emits_same_candidate_head_universe():
    feature_names = ("return_5m", "return_15m", "return_60m", "realized_vol_15m", "realized_vol_60m",
                     "relative_volume", "range_position", "symbol_code", "direction_code", "session_code",
                     "volume_zscore_60m", "signed_volume_pressure_15m", "peer_return_15m", "relative_return_15m")
    common = pd.DataFrame([{**{name: 1.0 for name in feature_names}, "direction": "UP", "candidate_id": "QQQ|UP|2026-08-10",
                            "decision_timestamp_utc": "2026-08-10T13:30:00Z", "underlying_symbol": "QQQ"},
                           {**{name: 1.0 for name in feature_names}, "direction": "DOWN", "candidate_id": "QQQ|DOWN|2026-08-10",
                            "decision_timestamp_utc": "2026-08-10T13:30:00Z", "underlying_symbol": "QQQ"}])
    identity = {"baseline_features": feature_names[:10], "r28_features": feature_names,
                "r2": {head: {"path": None, "sha256": "r2" + head, "threshold": .5} for head in ("UP", "DOWN")},
                "r28": {head: {"path": None, "sha256": "r28" + head, "threshold": .5} for head in ("UP", "DOWN")}}
    original = SHADOW.joblib.load
    SHADOW.joblib.load = lambda _: FixedModel()
    try:
        r2, r28 = SHADOW._score_rows(common, identity)
    finally:
        SHADOW.joblib.load = original
    assert set(zip(r2["candidate_id"], r2["head"])) == set(zip(r28["candidate_id"], r28["head"]))
    assert len(r2) == len(r28) == 2 and r2.selected.all() and r28.selected.all()


def test_seal_writes_hash_and_immutable_manifest(tmp_path):
    original = SHADOW.RUNTIME, SHADOW.SCRATCH, SHADOW.SEALED
    SHADOW.RUNTIME, SHADOW.SCRATCH, SHADOW.SEALED = tmp_path / "runtime", tmp_path / "scratch", tmp_path / "frozen"
    try:
        ledger = SHADOW.immutable_shadow_ledger(rows("FAST3_CLEANROOM_R2"), rows("FAST3_R28_3_CROSS_ASSET_FLOW"), REGISTRATION, "2026-08-08T13:19:00Z")
        manifest = SHADOW.seal_prediction_ledger(ledger)
    finally:
        SHADOW.RUNTIME, SHADOW.SCRATCH, SHADOW.SEALED = original
    assert manifest["row_count"] == 4 and Path(manifest["ledger_path"]).is_file()
    assert Path(manifest["ledger_path"] + ".sha256").is_file()
