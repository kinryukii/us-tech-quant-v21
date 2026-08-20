import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3e_clean_lineage_first_touch.py"
SPEC = importlib.util.spec_from_file_location("r28_3e", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_frozen_constants_storage_roots_and_no_model_calls():
    text = SOURCE.read_text(encoding="utf-8")
    assert (AUDIT.SEED, AUDIT.RUNS) == (28305, 1000)
    assert AUDIT.OUT.is_relative_to(AUDIT.FROZEN_ROOT)
    assert AUDIT.STAGE.is_relative_to(AUDIT.RUNTIME_ROOT)
    assert AUDIT.SCRATCH_RUN_ROOT.is_relative_to(AUDIT.SCRATCH_ROOT)
    assert not AUDIT.OUT.is_relative_to(AUDIT.REPO)
    assert not (AUDIT.REPO / ".local_results").exists()
    assert ".fit(" not in text and ".predict(" not in text and "predict_proba" not in text
    assert "git clean" not in text and "git reset" not in text and "git stash" not in text


def test_partition_manifest_is_deterministic_and_complete(tmp_path, monkeypatch):
    root = tmp_path / "canonical"
    part = root / "symbol=X" / "year=2020" / "month=01"
    part.mkdir(parents=True)
    frame = pd.DataFrame({
        "symbol": ["X", "X"], "timestamp_et": pd.to_datetime(["2020-01-01T00:00Z", "2020-01-01T00:01Z"]),
        "open": [1.0, 1.1], "high": [1.1, 1.2], "low": [.9, 1.0], "close": [1.0, 1.1],
        "volume": [1.0, 2.0], "source": ["test", "test"],
    })
    frame.to_parquet(part / "data.parquet", index=False)
    monkeypatch.setattr(AUDIT, "CANONICAL", root)
    monkeypatch.setattr(AUDIT, "SYMBOLS", ("X",))
    monkeypatch.setattr(AUDIT, "EXPECTED_PARTITIONS_PER_SYMBOL", 1)
    first = AUDIT.build_partition_manifest()
    second = AUDIT.build_partition_manifest()
    assert first[2] == second[2] and first[3] == second[3]
    row = first[0].iloc[0]
    assert row.file_sha256 and row.row_count == 2 and row.min_timestamp and row.max_timestamp
    assert row.schema_fingerprint and "timestamp_et" in json.loads(row.column_names)


def test_first_touch_uses_first_legal_real_etf_open_and_frozen_fallback():
    econ = pd.DataFrame({
        "candidate_id": ["u", "d", "n"], "payoff_candidate_id": ["pu", "pd", "pn"],
        "underlying_symbol": ["SOXX"] * 3, "head": ["UP", "UP", "UP"],
        "valid": [True] * 3, "exit": pd.to_datetime(["2020-01-02T00:00Z"] * 3),
        "exit_price": [102.0, 102.0, 102.0], "action_instrument": ["SOXL"] * 3,
        "entry_timestamp": pd.to_datetime(["2020-01-01T00:01Z"] * 3), "entry_price": [100.0] * 3,
    })
    touches = pd.DataFrame({
        "candidate_id": ["pu", "pd", "pn"], "underlying_symbol": ["SOXX"] * 3,
        "frozen_label": ["UP_FIRST", "DOWN_FIRST", "NO_EVENT"],
        "touch_timestamp": pd.to_datetime(["2020-01-01T00:02:30Z", "2020-01-01T00:02:00Z", None]),
        "reference_price": [1.0] * 3,
    })
    bars = {"SOXL": pd.DataFrame({"timestamp_et": pd.to_datetime(["2020-01-01T00:02Z", "2020-01-01T00:03Z"]),
                                    "open": [103.0, 104.0]})}
    out = AUDIT.attach_first_touch(econ, touches, bars, AUDIT.canonical_hash).set_index("candidate_id")
    assert out.loc["u", "first_touch_exit_timestamp"] == pd.Timestamp("2020-01-01T00:03Z")
    assert out.loc["u", "first_touch_exit_price"] == 104.0
    assert out.loc["d", "first_touch_exit_price"] == 102.0 and out.loc["d", "event_state"] == "ADVERSE_FIRST"
    assert out.loc["n", "first_touch_exit_price"] == 102.0 and out.loc["n", "event_state"] == "NO_EVENT"
    assert np.isclose(out.loc["u", "first_touch_net20"], .038)


def _matching_frames():
    common = {"underlying_symbol": "SOXX", "head": "UP", "year_month": "2020-01",
              "weekday": "Monday", "session": "RTH", "first_touch_executable": True}
    real = pd.DataFrame([{**common, "candidate_id": f"r{i}", "first_touch_gross": .01,
                          "first_touch_net10": .009, "first_touch_net20": .008,
                          "first_touch_outcome_path": f"rp{i}"} for i in range(2)])
    eligible = pd.DataFrame([{**common, "candidate_id": f"e{i}", "first_touch_gross": i / 1000,
                              "first_touch_net10": i / 1000 - .001, "first_touch_net20": i / 1000 - .002,
                              "first_touch_outcome_path": f"ep{i}"} for i in range(10)])
    return real, eligible


def test_matched_placebo_same_translation_seed_and_p_value_are_deterministic():
    a = AUDIT.load_module(AUDIT.A_SOURCE, "r28_3e_test_a")
    real, eligible = _matching_frames()
    one_runs, one = AUDIT.matched_placebo(a, real, eligible)
    two_runs, two = AUDIT.matched_placebo(a, real, eligible)
    pd.testing.assert_frame_equal(one_runs, two_runs)
    assert one == two and one["random_seed"] == 28305 and one["random_run_count"] == 1000
    expected = (int((one_runs.mean_net20.to_numpy() >= real.first_touch_net20.mean()).sum()) + 1) / 1001
    assert one["real_net20_p"] == expected and one["signal_cardinality_conserved"]


def test_group_aggregation_cost_tail_and_classification():
    frame = pd.DataFrame({
        "year": [2020, 2020, 2021], "action_instrument": ["SOXL", "SOXL", "SOXS"],
        "first_touch_executable": [True] * 3, "first_touch_gross": [.012, -.008, .022],
        "first_touch_net10": [.011, -.009, .021], "first_touch_net20": [.010, -.010, .020],
    })
    by_year = AUDIT.grouped(frame, "year")
    by_symbol = AUDIT.grouped(frame, "action_instrument")
    assert by_year.trade_count.sum() == 3 and by_symbol.trade_count.sum() == 3
    assert np.isclose(AUDIT.stats(frame)["mean_net20"], .02 / 3)
    share, flag = AUDIT.extreme_outlier_audit(pd.Series([1.0] + [.001] * 99))
    assert share > .50 and flag
    assert AUDIT.classify(.001, .95, .05)[0].startswith("A_")
    assert AUDIT.classify(.001, .90, .10)[0].startswith("B_")
    assert AUDIT.classify(.001, .89, .11)[0].startswith("C_")
    assert AUDIT.classify(-.001, 1.0, .001)[0].startswith("D_")


def test_no_silent_drop_contract_and_external_cache_contract():
    text = SOURCE.read_text(encoding="utf-8")
    for state in ("FAVORABLE_FIRST_EXECUTED", "ADVERSE_FIRST_EXECUTED", "NO_EVENT_EXECUTED", "NONEXECUTABLE"):
        assert state in text
    assert "sum(state_counts.values()) != len(selected_audit)" in text
    assert AUDIT.DATA_ROOT not in AUDIT.OUT.parents
    assert AUDIT.DATA_ROOT not in AUDIT.RUNTIME_RUN_ROOT.parents


def _fold_ledger(heads=("UP",), folds=3):
    rows = []
    for head in heads:
        for fold in range(folds):
            rows.append({"candidate_id": f"{head}_{fold}", "head": head,
                         "validation_slice": f"OOF_{2020 + fold}",
                         "model_sha256": f"{head}_model_{fold}",
                         "feature_manifest_sha256": "shared_feature"})
    return pd.DataFrame(rows)


def test_single_head_multiple_valid_fold_models_pass_and_differing_sha_is_expected():
    ledger = _fold_ledger(folds=3)
    result = AUDIT.reconcile_fold_model_identities(ledger, ledger.copy())
    assert result["heads"]["UP"]["authoritative_identity_record_count"] == 3
    assert result["heads"]["UP"]["feature_identity_shared_across_folds"]
    assert result["selected_signal_mapping_reconciliation"]["status"] == "PASS"


def test_up_six_folds_and_down_six_folds_pass_with_correct_selected_mapping():
    ledger = _fold_ledger(heads=("UP", "DOWN"), folds=6)
    selected = ledger.iloc[[0, 2, 6, 11]].copy()
    result = AUDIT.reconcile_fold_model_identities(ledger, selected)
    assert result["heads"]["UP"]["authoritative_identity_record_count"] == 6
    assert result["heads"]["DOWN"]["authoritative_identity_record_count"] == 6
    reconciliation = result["selected_signal_mapping_reconciliation"]
    assert reconciliation["selected_signal_unknown_model_count"] == 0
    assert reconciliation["selected_signal_ambiguous_model_count"] == 0
    assert reconciliation["selected_signal_feature_identity_mismatch_count"] == 0


def test_unknown_fold_model_identity_stops():
    ledger = _fold_ledger()
    selected = ledger.iloc[[0]].copy()
    selected.loc[:, "model_sha256"] = "unknown_model"
    with pytest.raises(AUDIT.AuditStop, match="STOP_FOLD_MODEL_IDENTITY_RECONCILIATION"):
        AUDIT.reconcile_fold_model_identities(ledger, selected)


def test_same_signal_mapping_to_two_fold_identities_stops():
    ledger = _fold_ledger()
    selected = ledger.iloc[[0, 1]].copy()
    selected.loc[selected.index[1], "candidate_id"] = selected.iloc[0].candidate_id
    with pytest.raises(AUDIT.AuditStop, match="STOP_FOLD_MODEL_IDENTITY_RECONCILIATION"):
        AUDIT.reconcile_fold_model_identities(ledger, selected)


def test_feature_identity_mismatch_within_fold_stops():
    ledger = _fold_ledger()
    conflicting = ledger.iloc[[0]].copy()
    conflicting.loc[:, "feature_manifest_sha256"] = "conflicting_feature"
    authoritative = pd.concat([ledger, conflicting], ignore_index=True)
    with pytest.raises(AUDIT.AuditStop, match="STOP_FOLD_MODEL_IDENTITY_RECONCILIATION"):
        AUDIT.reconcile_fold_model_identities(authoritative, ledger.iloc[[0]].copy())


def test_aggregate_fold_identity_hash_is_deterministic():
    ledger = _fold_ledger(heads=("UP", "DOWN"), folds=6)
    forward = AUDIT.reconcile_fold_model_identities(ledger, ledger.copy())
    reverse = AUDIT.reconcile_fold_model_identities(ledger.iloc[::-1].reset_index(drop=True),
                                                     ledger.iloc[::-1].reset_index(drop=True))
    for head in ("UP", "DOWN"):
        assert forward["heads"][head]["fold_model_identity_set_sha256"] == reverse["heads"][head]["fold_model_identity_set_sha256"]
