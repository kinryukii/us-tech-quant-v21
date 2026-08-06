from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from fast3.common.contracts import ContractViolation
from fast3.models.abstention_policy import apply_abstention_policy, load_abstention_policy, safety_summary


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "fast3" / "configs" / "models" / "FAST3_005_ABSTENTION_POLICY.json"
RUNNER_PATH = ROOT / "fast3" / "scripts" / "run" / "fast3_005_abstention_smoke.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("fast3_005_abstention_smoke", RUNNER_PATH)
runner = importlib.util.module_from_spec(RUNNER_SPEC); assert RUNNER_SPEC.loader is not None; RUNNER_SPEC.loader.exec_module(runner)
synthetic_scored_events = runner.synthetic_scored_events


@pytest.fixture
def policy(): return load_abstention_policy(POLICY)


def decisions(policy): return apply_abstention_policy(synthetic_scored_events(), policy)


def test_01_frozen_opportunity_gate(policy): assert policy["frozen_fast3_004_opportunity_threshold"] == .6
def test_02_priority_order(policy): assert decisions(policy).abstention_reason.tolist()[0] == "DATA_TRUST_FAILED"
def test_03_opportunity_abstention(policy): assert decisions(policy).abstention_reason.tolist()[1] == "OPPORTUNITY_BELOW_FROZEN_GATE"
def test_04_direction_confidence_abstention(policy): assert decisions(policy).abstention_reason.tolist()[2] == "DIRECTION_CONFIDENCE_BELOW_FLOOR"
def test_05_disagreement_abstention(policy): assert decisions(policy).abstention_reason.tolist()[3] == "MODEL_DISAGREEMENT_EXCEEDS_LIMIT"
def test_06_cost_surfaces_abstain(policy): assert decisions(policy).abstention_reason.tolist()[4:6] == ["COST_EXPECTANCY_NON_POSITIVE_10BPS", "COST_EXPECTANCY_NON_POSITIVE_20BPS"]
def test_07_eligible_is_not_position(policy):
    x=decisions(policy); assert x.decision.iat[-1] == "ELIGIBLE_FOR_FAST3_002" and x.proposed_position_count.sum() == x.orders_emitted.sum() == 0
def test_08_confirmation_rejected(policy):
    x=synthetic_scored_events(); x["decision_timestamp_et"]=pd.Timestamp("2025-02-08",tz="America/New_York")
    with pytest.raises(ContractViolation, match="CONFIRMATION"): apply_abstention_policy(x,policy)
def test_09_single_account_safety(policy): assert safety_summary(decisions(policy))["single_account_max_concurrent_positions"] == 1
