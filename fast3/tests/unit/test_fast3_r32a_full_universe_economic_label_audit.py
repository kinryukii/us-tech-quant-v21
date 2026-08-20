from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r32a_full_universe_economic_label_audit.py"
spec = importlib.util.spec_from_file_location("r32a", RUNNER)
r32a = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r32a)


def test_identity_and_target_formulas_are_exact_and_candidate_level() -> None:
    decision = pd.Timestamp("2024-01-02T14:00:00Z")
    anchor = decision + pd.Timedelta(minutes=1)
    universe = pd.DataFrame([
        {"candidate_id": f"QQQ|{head}|2024-01-02 14:00:00+00:00", "anchor_candidate_id": "QQQ|2024-01-02 14:00:00+00:00",
         "decision_timestamp_utc": decision, "underlying_symbol": "QQQ", "head": head, "instrument": instrument,
         "canonical_partition_manifest_hash": "source", "authoritative_anchor_timestamp_et": anchor}
        for head, instrument in (("UP", "TQQQ"), ("DOWN", "SQQQ"))
    ])
    touches = pd.DataFrame({"anchor_candidate_id": ["QQQ|2024-01-02 14:00:00+00:00"], "frozen_label": ["NO_EVENT"],
                            "touch_timestamp": [pd.NaT], "underlying_entry_timestamp": [anchor],
                            "underlying_horizon_timestamp": [anchor + pd.Timedelta(hours=24)]})
    bars = {}
    for instrument, exit_price in (("TQQQ", 101.0), ("SQQQ", 99.0)):
        entry = anchor + pd.Timedelta(minutes=1)
        bars[instrument] = pd.DataFrame({"timestamp_utc": [entry, entry + pd.Timedelta(hours=24)],
            "open": [100.0, exit_price], "partition_key": ["p", "p"]})
    labels = r32a.construct_labels(universe, touches, bars, [])
    assert len(labels) == 2  # overlapping candidate horizons are not portfolio-deduplicated
    assert labels.label_valid.all()
    expected = np.array([101 / 100 - 1 - .002, 99 / 100 - 1 - .002])
    np.testing.assert_allclose(labels.sort_values("head").net20, expected[[1, 0]])
    assert labels.set_index("head").loc["UP", "T1"] == 1
    assert labels.set_index("head").loc["DOWN", "T1"] == 0
    np.testing.assert_allclose(labels.T2, np.sign(labels.net20) * np.log1p(np.abs(labels.net20)))


def test_preentry_and_ambiguous_are_explicit_not_silently_dropped() -> None:
    source = inspect.getsource(r32a.construct_labels)
    assert "PRE_ENTRY_EVENT_NOT_CAPTURABLE" in source
    assert "OTHER_EXPLICIT_INVALID" in source
    assert "dropna" not in source


def test_selection_severity_is_outcome_blind_and_compression_is_high() -> None:
    audit = pd.DataFrame({"standardized_mean_difference": [0.0], "ks_statistic": [0.0]})
    year = pd.DataFrame({"selection_rate": [.001, .001]})
    direction = pd.DataFrame({"selection_rate": [.001, .001]})
    assert r32a.selection_severity(.001, audit, year, direction) == "HIGH"
    source = inspect.getsource(r32a.feature_range_audit)
    assert "net20" not in source and "T1" not in source and "T2" not in source


def test_no_training_prediction_or_final_outcome_path() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    forbidden = {"fit", "predict", "predict_proba"}
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert forbidden.isdisjoint(calls)
    identity_source = inspect.getsource(r32a.freeze_universe_identity)
    assert "label" not in identity_source.lower()
    assert "gross_return" not in identity_source and "net20" not in identity_source
    assert r32a.TRUE_HOLDOUT_START == pd.Timestamp("2025-02-01T05:00:00Z")


def test_storage_and_anti_bloat_contract() -> None:
    assert r32a.DATA_ROOT == Path(r"D:\us-tech-quant-data")
    assert r32a.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert r32a.SCRATCH_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert not any(RUNNER.parent.glob("*r32a*helper*.py"))
