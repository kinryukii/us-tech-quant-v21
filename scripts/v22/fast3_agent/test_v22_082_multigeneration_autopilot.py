import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import v22_082_multigeneration_autopilot as subject


def test_schedule_is_strictly_chronological_and_marks_prior_holdouts_consumed(tmp_path):
    common = subject.pd.date_range("2018-07-19", "2026-07-28", freq="B", tz="America/New_York")
    cfg = subject.load_config()
    schedule = subject.build_schedule(common, cfg)
    assert len(schedule["generations"]) == 6
    assert schedule["prior_v22_081_consumed_holdouts"]["validation"]["consumed"] is True
    prior_end = None
    for fold in schedule["generations"]:
        assert fold["development_start"] < fold["validation_start"] < fold["confirmation_start"]
        assert fold["validation_end"] < fold["confirmation_start"]
        if prior_end is not None:
            assert fold["validation_start"] > prior_end
        prior_end = fold["confirmation_end"]


def test_mutation_limits_and_no_broker_contract():
    cfg = subject.load_config()
    root = subject.root_candidate(cfg, 82082)
    child, plan = subject.mutate_candidate(root, "EXCESS_DRAWDOWN", cfg, 82083)
    assert len(child["feature_names"]) <= cfg["max_active_features"]
    assert plan["changes"]["model_family_changes"] <= 1
    assert plan["changes"]["hyperparameter_changes"] <= 3
    assert plan["changes"]["threshold_changes"] <= 2
    assert plan["changes"]["label_horizon_changes"] <= 1
    assert plan["changes"]["exit_rule_changes"] <= 1
    assert subject.SAFETY["broker_action_allowed"] is False
    assert subject.SAFETY["order_generation_allowed"] is False


def test_inner_window_uses_only_feasible_contiguous_lengths():
    cfg = subject.load_config()
    dates = subject.pd.date_range("2018-01-01", periods=366, freq="B", tz="America/New_York")
    sample = subject.pd.DataFrame({"calendar_date": dates.repeat(2), "decision_timestamp": dates.repeat(2) + subject.pd.Timedelta(hours=10)})
    train, test, window = subject._window(sample, 0, cfg)
    assert not train.empty and not test.empty
    assert window["train_end"] < window["embargo_start"] <= window["oos_start"]


def test_retention_uses_nested_candidate_complexity():
    cfg = subject.load_config()
    records = [{"experiment_id": "E1", "trade_count": 30, "hard_drawdown_pass": True, "failure_reason": None, "score": 1.0, "mean_net_10bps_delay1": .001, "mean_net_20bps_delay1": .0005, "candidate": {"complexity": 2}}]
    assert subject._retain(records, cfg) == ["E1"]
