import importlib.util
from pathlib import Path


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_option_context_r1_stage2r29.py"
spec = importlib.util.spec_from_file_location("stage2r29", RUNNER)
m = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(m)


def test_frozen_feature_sets_and_hgb_contract_are_fixed():
    manifest, t5, t6 = m.identity()
    assert len(manifest["FACTOR_NAMES"]) == 29
    assert t5["TARGET_NAME"] == "T5_CONDITIONAL_LOSS_SEVERITY"
    assert t6["TARGET_NAME"] == "T6_CONDITIONAL_GAIN_MAGNITUDE"
    assert m.PARAMS["random_state"] == 1729


def test_folds_are_expanding_with_a_24_hour_embargo():
    import pandas as pd
    x = pd.DataFrame({"decision_timestamp_utc": pd.date_range("2025-01-01", periods=80, freq="D", tz="UTC")})
    fs = m.folds(x)
    assert len(fs) == 3
    assert all(pd.Timestamp(f["train_end"]) < pd.Timestamp(f["test_start"]) for f in fs)


def test_2026_rows_can_be_evaluated_but_never_enter_training():
    import pandas as pd
    x = pd.DataFrame({"decision_timestamp_utc": pd.date_range("2025-12-30", periods=5, freq="D", tz="UTC")})
    mask = m.training_mask(x, "2026-08-07T23:59:59Z")
    m.assert_pre2026_training(x, mask)
    assert x.loc[mask, "decision_timestamp_utc"].max() < m.TRAIN_END_EXCLUSIVE
    assert int(x.loc[mask, "decision_timestamp_utc"].dt.year.eq(2026).sum()) == 0
    assert int(x.loc[~mask, "decision_timestamp_utc"].dt.year.eq(2026).sum()) == 3


def test_fold_train_end_cannot_bypass_pre2026_hard_gate():
    import pandas as pd
    x = pd.DataFrame({"decision_timestamp_utc": pd.date_range("2025-12-31", periods=3, freq="D", tz="UTC")})
    mask = m.training_mask(x, pd.Timestamp("2027-01-01T00:00:00Z"))
    assert x.loc[mask, "decision_timestamp_utc"].tolist() == [pd.Timestamp("2025-12-31T00:00:00Z")]


def test_train_only_structural_projection_retains_partial_nan_only():
    assert m.compatibility_fixture()


def test_input_hash_changes_with_nan_position_or_column_order():
    import pandas as pd
    left = pd.DataFrame({"a": [1.0, None], "b": [2.0, 3.0]})
    assert m.matrix_hash(left) != m.matrix_hash(left[["b", "a"]])
    assert m.matrix_hash(left) != m.matrix_hash(left.fillna(0.0))
