import json

import pandas as pd

import v22_085_aggressive_bounded_search as engine


def test_safety_and_bounded_contract():
    c = engine.cfg()
    assert engine.SAFETY["broker_action_allowed"] is False
    assert engine.SAFETY["official_adoption_allowed"] is False
    assert c["max_generations"] == 8 and c["max_total_experiments"] == 320
    assert len(c["label_horizons_minutes"]) == 4 and len(engine.FEATURES) <= c["max_active_features"]
    assert c["max_active_candidates"] == 3 and c["max_model_families"] == 3


def test_consumed_holdouts_exclude_new_unseen_folds():
    folds = engine.frozen_manifest.__name__  # keep test independent of canonical source metadata
    assert folds == "frozen_manifest"
    names = {x[0] for x in engine.consumed_ranges()}
    assert "V22.084_VALIDATION" in names and "V22.081_CONFIRMATION" in names
    new = [("2022-06-01", "2022-06-28"), ("2022-12-01", "2022-12-28"), ("2023-01-01", "2023-01-28")]
    for start, end in new:
        assert not any(pd.Timestamp(start) <= pd.Timestamp(old_end) and pd.Timestamp(end) >= pd.Timestamp(old_start) for _, old_start, old_end in engine.consumed_ranges())


def test_power_audit_rejects_forced_daily_cap_solution():
    dates = pd.date_range("2022-06-01", periods=21, freq="D", tz="America/New_York").append(pd.date_range("2022-12-01", periods=21, freq="D", tz="America/New_York")).append(pd.date_range("2023-01-01", periods=20, freq="D", tz="America/New_York"))
    samples = pd.DataFrame({"decision_timestamp": dates, "calendar_date": dates.normalize()})
    manifest = {"folds": [
        {"fold_id": "v1", "role": "GENERATION_VALIDATION", "start": "2022-06-01", "end": "2022-06-28 23:59:59.999999"},
        {"fold_id": "v2", "role": "GENERATION_VALIDATION", "start": "2022-12-01", "end": "2022-12-28 23:59:59.999999"},
        {"fold_id": "c", "role": "GENERATION_CONFIRMATION", "start": "2023-01-01", "end": "2023-01-28 23:59:59.999999"},
    ]}
    audit = engine.power_audit(samples, manifest)
    assert audit["aggregate_validation_max_possible_trades"] >= 60
    assert audit["aggregate_validation_expected_trades"] == 40
    assert audit["power_target_feasible"] is False


def test_costs_delay_paths_and_side_separation():
    assert abs(engine.net_after_cost(.012, 5) - .0115) < 1e-12
    assert abs(engine.net_after_cost(.012, 30) - .009) < 1e-12
    decision = pd.date_range("2022-06-01 09:30", periods=3, freq="min", tz="America/New_York")
    bars = pd.DataFrame({"timestamp_utc": decision.tz_convert("UTC"), "open": [10.0, 10.2, 10.4]})
    frame = pd.DataFrame({"entry_timestamp": [decision[0]]})
    paths = engine.attach_execution_paths(frame, {"SOXL": bars, "SOXS": bars.assign(open=[20.0, 19.8, 19.6])}, [1], [1])
    assert paths.loc[0, "soxl_1m_d1_entry_price"] == 10.2
    assert paths.loc[0, "soxl_1m_d1_exit_price"] == 10.4
    assert paths.loc[0, "soxs_1m_d1_entry_price"] == 19.8
    assert paths.loc[0, "soxl_1m_d1_gross"] > 0 and paths.loc[0, "soxs_1m_d1_gross"] < 0


def test_eligibility_excludes_incomplete_path_and_retains_no_nonfinite_input():
    f = pd.DataFrame({name: [1.0, 1.0] for name in engine.FEATURES})
    f["decision_timestamp"] = pd.date_range("2022-06-01 10:00", periods=2, freq="min", tz="America/New_York")
    for side in ("soxl", "soxs"):
        for horizon in engine.cfg()["label_horizons_minutes"]:
            for delay in engine.cfg()["delay_minutes"]:
                stem = f"{side}_{horizon}m_d{delay}"
                f[stem + "_entry_price"] = [10.0, 10.0]
                f[stem + "_exit_price"] = [10.1, float("nan")]
                f[stem + "_gross"] = [.01, float("nan")]
    kept, contract = engine.eligible_decisions(f, engine.cfg()["label_horizons_minutes"], engine.cfg()["delay_minutes"])
    assert len(kept) == 1 and contract["FUTURE_PATH_INCOMPLETE_RETAINED_COUNT"] == 0


def test_minimum_commitment_only_allows_power_exception():
    assert engine.minimum_search_commitment_satisfied(0, 0, power_infeasible=True)
    assert not engine.minimum_search_commitment_satisfied(3, 119)
    assert engine.minimum_search_commitment_satisfied(4, 120)


def test_atomic_holdout_consumption_is_idempotent(tmp_path):
    engine.checkpoint(tmp_path)
    engine.consume_holdout(tmp_path, "v1", "VALIDATION")
    engine.consume_holdout(tmp_path, "v1", "VALIDATION")
    state = json.loads((tmp_path / "v22_085_checkpoint.json").read_text())
    assert state["validation_read_count"] == 1 and state["consumed_holdouts"] == ["v1"]


def test_terminal_output_contract(tmp_path):
    audit = {"aggregate_validation_expected_trades": 40, "aggregate_validation_unique_days": 41, "untouched_trading_days_available": 61, "status": "INSUFFICIENT_UNTOUCHED_HISTORY_FOR_POWER", "reason": "test"}
    manifest = {"split_sha256": "x", "source_data_hash": "y"}
    eligibility = {"FEATURE_NAN_COUNT": 0, "LABEL_NAN_COUNT": 0, "ENTRY_PRICE_NAN_COUNT": 0, "EXIT_PRICE_NAN_COUNT": 0, "METRIC_INPUT_NAN_COUNT": 0, "NONFINITE_COUNT": 0, "TIMESTAMP_ALIGNMENT_ERROR_COUNT": 0, "DUPLICATE_DECISION_KEY_COUNT": 0, "FUTURE_PATH_INCOMPLETE_RETAINED_COUNT": 0}
    engine.write_terminal(tmp_path, manifest, eligibility, audit)
    assert engine.validate_output_contract(tmp_path)


def test_terminal_resume_is_idempotent(tmp_path, monkeypatch):
    summary = {"FINAL_STATUS": "PASS_INSUFFICIENT_UNTOUCHED_HISTORY_FOR_POWER", "FINAL_DECISION": "NO_TRADE", "POWER_TARGET_FEASIBLE": False, "VALIDATION_READ_COUNT": 0, "BROKER_ACTION_ALLOWED": False, "OFFICIAL_ADOPTION_ALLOWED": False, "RECOMMENDED_NEXT_COMMAND": "NONE"}
    (tmp_path / "V22_085_GLOBAL_DONE.flag").write_text("done\n")
    (tmp_path / "v22_085_summary.json").write_text(json.dumps(summary))
    for name in ("frozen_split_manifest.json", "statistical_power_feasibility_audit.json", "candidate_funnel_summary.json", "champion_config.json", "experiment_registry.jsonl", "generation_registry.jsonl", "v22_085_checkpoint.json", "v22_085_summary.txt", "v22_085_report.md"):
        (tmp_path / name).write_text("{}" if name.endswith(".json") else "")
    monkeypatch.setattr(engine, "validate_output_contract", lambda _: True)
    assert engine.audit(tmp_path, tmp_path) == summary
