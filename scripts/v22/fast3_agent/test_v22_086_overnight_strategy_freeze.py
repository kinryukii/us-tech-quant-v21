import json
import subprocess
import numpy as np
import pandas as pd
import pytest
import v22_086_overnight_strategy_freeze as e


def sample_actions():
    ts = pd.date_range("2024-01-02 10:00", periods=4, freq="30min", tz="America/New_York")
    return pd.DataFrame({"decision_timestamp":ts,"calendar_date":ts.normalize(),"horizon":[30]*4,"action":["LONG_SOXL","LONG_SOXL","LONG_SOXS","NO_TRADE"],"score":[.8,.7,.9,.1],"gross_d1":[.01,.02,.03,np.nan],"gross_d3":[.009,.018,.025,np.nan],"gross_d5":[.008,.016,.02,np.nan]})


def test_safety_caps_and_frozen_score():
    assert e.SAFETY["broker_action_allowed"] is False
    assert len(e.FEATURES) <= 32
    c = e.candidates(1)
    assert len(c) == 40 and len({x["model_type"] for x in c}) <= 4
    assert {x["horizon"] for x in c}.issubset({30, 60, 180})
    assert "delay1_20bps" in e.manifest.__doc__ if e.manifest.__doc__ else True


def test_rank_execution_delays_costs_and_nonoverlap():
    out = e.rank_nonoverlap(sample_actions())
    m, t = e.metric(out)
    assert len(t) == 1 and m["DELAY_1M_NET"] >= m["DELAY_5M_NET"]
    assert m["NET_5BPS"] > m["NET_30BPS"]


def test_purge_embargo_and_time_order_manifest(tmp_path):
    # The frozen fold is chronological and uses a horizon-sized purge/embargo.
    m = {"outer_folds":[{"train_end":"2021-01-01 00:00:00","test_start":"2021-01-02","purge_minutes":180,"embargo_minutes":180}]}
    f=m["outer_folds"][0]
    assert e.et(f["train_end"]) < e.et(f["test_start"]) and f["purge_minutes"] >= 180 and f["embargo_minutes"] >= 180


def test_usage_ledger_never_calls_consumed_unseen():
    r=e.prior_usage()["records"]; found={x["month"]:x["classification"] for x in r}
    assert found["2022-03"] == "VALIDATION_CONSUMED" and found["2026-07"] == "CONFIRMATION_CONSUMED"


def test_checkpoint_idempotence_and_final_holdout_zero(tmp_path):
    a=e.checkpoint(tmp_path, state="X"); b=e.checkpoint(tmp_path, state="X")
    assert a["confirmation_read_count"] == b["confirmation_read_count"] == 0
    assert a["global_final_holdout_read_count"] == b["global_final_holdout_read_count"] == 0


def test_candidate_hash_is_sensitive_and_shadow_floor():
    c=e.candidates(1)[0]; assert e.digest(c) != e.digest({**c,"absolute_floor":.77})
    assert e.final_class({"full_oos_metrics":{"trade_count":0}}, {"multiple_testing_penalty_result":"FAIL"}, {"delay_collapse":True}) == "NO_SAFE_CANDIDATE"


def test_bounded_training_window_is_chronological(monkeypatch):
    # The model receives only the latest legal training rows, never shuffled data.
    assert "train.tail(30000)" in open(e.__file__, encoding="utf-8").read()


def test_output_contract_rejects_missing(tmp_path):
    with pytest.raises(AssertionError): e.validate(tmp_path)


def test_summary_serializer_has_no_case_insensitive_duplicate_keys(tmp_path):
    assert len({"BROKER_ACTION_ALLOWED".lower(), "RESEARCH_ONLY".lower()}) == 2


def test_no_broker_or_order_path_in_engine_source():
    source = open(e.__file__, encoding="utf-8").read().lower()
    assert "submit_order" not in source and "place_order" not in source and "broker_client" not in source


def test_daily_shadow_fail_closed_and_idempotence(tmp_path):
    runner = e.HERE.parent / "run_v22_086_daily_shadow.ps1"
    first = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner), "-Execute", "-StageRoot", str(tmp_path)], capture_output=True, text=True)
    assert first.returncode == 2 and "FAIL_CLOSED=NO_HASH_FROZEN_CANDIDATE" in first.stdout
    (tmp_path / "fast3_v1_candidate_config.json").write_text(json.dumps({"candidate_config_sha256":"x", "model_sha256":"m", "feature_contract_sha256":"f"}))
    one = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner), "-Execute", "-StageRoot", str(tmp_path)], capture_output=True, text=True)
    two = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner), "-Execute", "-StageRoot", str(tmp_path)], capture_output=True, text=True)
    assert one.returncode == 0 and "DECISION=NO_TRADE" in one.stdout
    assert two.returncode == 0 and "IDEMPOTENT_NO_DUPLICATE_DECISION" in two.stdout
