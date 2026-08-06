from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from fast3.common.contracts import ContractViolation
from fast3.models.two_stage_pipeline import TwoStageResearchPipeline, load_fast3_004_config, validate_pit_features


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "fast3" / "configs" / "models" / "FAST3_004_TWO_STAGE_RESEARCH.json"
RUNNER_PATH = ROOT / "fast3" / "scripts" / "run" / "fast3_004_two_stage_smoke.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("fast3_004_two_stage_smoke", RUNNER_PATH)
runner = importlib.util.module_from_spec(RUNNER_SPEC); assert RUNNER_SPEC.loader is not None; RUNNER_SPEC.loader.exec_module(runner)
synthetic_events = runner.synthetic_events


@pytest.fixture
def config():
    return load_fast3_004_config(CONFIG)


def test_01_frozen_contract_hash(config):
    assert config["frozen_executable_contract_sha256"] == "72186180b40e0c4b866d482fd35033597334c89ba3ef2bca33da5ad2d637eead"


def test_02_future_feature_rejected(config):
    x = synthetic_events(); x.loc[0, "feature_available_at_et"] = x.loc[0, "decision_timestamp_et"] + pd.Timedelta(minutes=1)
    with pytest.raises(ContractViolation, match="PIT_FEATURE_NOT_AVAILABLE"):
        validate_pit_features(x, config)


def test_03_confirmation_rejected(config):
    x = synthetic_events(); x.loc[0, "decision_timestamp_et"] = pd.Timestamp("2025-02-08", tz="America/New_York")
    with pytest.raises(ContractViolation, match="CONFIRMATION"):
        validate_pit_features(x, config)


def test_04_outer_test_has_no_selection_fit(config):
    pipeline = TwoStageResearchPipeline(config); scored, _ = pipeline.run_nested(synthetic_events())
    assert not scored.empty
    assert all(entry["role"] in {"scaler.fit", "model.fit"} for entry in pipeline.ledger.entries)
    assert all("outer_test" not in entry["fold"] for entry in pipeline.ledger.entries if "selection" in entry["stage"])


def test_05_gate_is_frozen_and_direction_abstains(config):
    pipeline = TwoStageResearchPipeline(config); scored, _ = pipeline.run_nested(synthetic_events())
    assert (scored.loc[~scored.opportunity_eligible, "predicted_direction"] == "ABSTAIN").all()
    assert pipeline.gate_threshold == 0.6


def test_06_fit_ledger_and_concentration(config):
    pipeline = TwoStageResearchPipeline(config); scored, _ = pipeline.run_nested(synthetic_events())
    assert pipeline.ledger.entries
    assert set(pipeline.concentration_diagnostics(scored)) == {"symbol", "month", "regime", "side"}


def test_07_no_random_kfold_and_fixed_candidate_budget(config):
    config = load_fast3_004_config(CONFIG)
    assert config["validation"]["random_kfold_forbidden"]
    assert len(config["opportunity"]["candidates"] + config["direction"]["candidates"]) == 6


def test_08_single_account_adapter_and_cost_surfaces(config):
    pipeline = TwoStageResearchPipeline(config)
    t = pd.Timestamp("2024-01-02 09:30", tz="America/New_York")
    labels = pd.DataFrame([
        {"event_id": "a", "decision_timestamp_et": t, "exit_timestamp_et": t + pd.Timedelta(hours=1), "direction": "UP", "net_return": 0.01, "priority": 0, "cost_scenario_bps_round_trip": 10},
        {"event_id": "b", "decision_timestamp_et": t + pd.Timedelta(minutes=1), "exit_timestamp_et": t + pd.Timedelta(hours=1), "direction": "UP", "net_return": 0.01, "priority": 0, "cost_scenario_bps_round_trip": 20},
    ])
    portfolio, counts = pipeline.enforce_single_account(labels)
    metrics = pipeline.cost_surface_metrics(portfolio)
    assert counts["REJECTED_OVERLAP_COUNT"] == 1
    assert metrics[10]["accepted_trade_count"] == 1 and metrics[20]["accepted_trade_count"] == 0
