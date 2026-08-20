import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_r28_3a_frozen_economic_attribution.py"
SPEC = importlib.util.spec_from_file_location("r28_3a_audit", SOURCE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def economic_frame(values, symbol="QQQ"):
    count = len(values)
    frame = pd.DataFrame({"underlying_symbol": [symbol] * count, "net20": values})
    frame["gross"] = frame.net20 + .002
    frame["net10"] = frame.net20 + .001
    return frame


def matching_frame(rows):
    frame = pd.DataFrame(rows)
    frame["candidate_id"] = [f"c{i}" for i in range(len(frame))]
    frame["net20"] = np.arange(len(frame), dtype=float) / 100
    frame["net10"] = frame.net20 + .001
    frame["gross"] = frame.net20 + .002
    frame["outcome_path"] = frame.candidate_id
    return frame


def test_identity_mismatch_stops():
    with pytest.raises(AUDIT.AuditStop, match="STOPPED_IDENTITY_MISMATCH"):
        AUDIT.assert_identity({})


def test_baseline_reproduction_contract():
    values = np.full(1198, AUDIT.BASELINE["mean_net20"])
    values[:585] = .02
    values[585:] = (AUDIT.BASELINE["mean_net20"] * 1198 - values[:585].sum()) / 613
    real = economic_frame(values)
    reverse = economic_frame([AUDIT.BASELINE["reverse"]] * 2)
    shifts = {name: economic_frame([value] * 2) for name, value in (("minus1", AUDIT.BASELINE["minus1"]), ("plus1", AUDIT.BASELINE["plus1"]), ("plus2", AUDIT.BASELINE["plus2"]))}
    AUDIT.validate_baseline(real, reverse, shifts)


def test_no_model_fit_or_rescoring_and_data_root_is_not_output():
    source = SOURCE.read_text(encoding="utf-8")
    assert ".fit(" not in source and "predict_proba" not in source
    assert AUDIT.DATA_ROOT not in AUDIT.OUT.parents


def test_prospective_data_and_missing_score_fail_closed():
    with pytest.raises(AUDIT.AuditStop, match="PHASE3"):
        AUDIT.assert_no_prospective(pd.Series(["2025-02-02T00:00:00Z"]))
    missing = pd.DataFrame({"head": ["UP"], "selected": [True], "target_first": [1], "underlying_symbol": ["QQQ"], "decision_timestamp_utc": ["2024-01-01T00:00:00Z"]})
    with pytest.raises(AUDIT.AuditStop, match="FROZEN_SCORE_MISSING"):
        AUDIT.validate_frozen_scores(missing, "UP")


def test_matched_strata_relaxation_seed_and_cardinality_are_deterministic():
    source = matching_frame([
        {"underlying_symbol": "QQQ", "head": "UP", "year_month": "2024-01", "weekday": "Monday", "session": "RTH"},
        {"underlying_symbol": "QQQ", "head": "UP", "year_month": "2024-01", "weekday": "Monday", "session": "RTH"},
    ])
    eligible = matching_frame([
        {"underlying_symbol": "QQQ", "head": "UP", "year_month": "2024-01", "weekday": "Monday", "session": "RTH"},
        {"underlying_symbol": "QQQ", "head": "UP", "year_month": "2024-01", "weekday": "Tuesday", "session": "RTH"},
    ])
    first, levels = AUDIT.matched_once(source, eligible, np.random.default_rng(28301))
    second, levels_again = AUDIT.matched_once(source, eligible, np.random.default_rng(28301))
    assert levels == levels_again == [1, 1]
    assert len(first) == len(source) == len(second)
    pd.testing.assert_frame_equal(first, second)


def test_empirical_p_and_leave_one_out_calculation():
    assert AUDIT.empirical_p([.1, .2, .3], .2) == .75
    real = pd.concat([economic_frame([.10, .10], "QQQ"), economic_frame([.01, .01], "SOXX")], ignore_index=True)
    table, overall = AUDIT.leave_one_out(real)
    qqq = table.loc[table.removed_symbol.eq("QQQ")].iloc[0]
    assert overall["mean_net20"] == pytest.approx(.055)
    assert qqq["trade_count"] == 2 and qqq["mean_net20"] == pytest.approx(.01)


def test_plus2_attribution_totals_reconcile():
    real = pd.concat([economic_frame([.01, .02], "QQQ"), economic_frame([.03], "SOXX")], ignore_index=True)
    plus2 = pd.concat([economic_frame([.02, .03], "QQQ"), economic_frame([.04], "SOXX")], ignore_index=True)
    for frame in (real, plus2):
        frame["head"] = "UP"; frame["calendar_month"] = "2024-01"; frame["weekday"] = "Monday"; frame["session"] = "RTH"
    _, summary = AUDIT.plus2_attribution(real, plus2)
    assert summary["reconciliation"] == pytest.approx(summary["plus2_minus_real_net20"])
    assert summary["classification"] == "E_MIXED"
