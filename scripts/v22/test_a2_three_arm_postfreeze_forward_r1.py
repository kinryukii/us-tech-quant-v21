from __future__ import annotations

import copy
import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest


SOURCE = Path(__file__).with_name("a2_three_arm_postfreeze_forward_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_three_arm_forward_tested", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def initialized():
    result = MODULE.initialize()
    return result["contract"], result["state"]


def test_01_frozen_identity_and_cutoff(initialized):
    contract, state = initialized
    frozen = contract["frozen_identities"]
    assert frozen["raw_model_hash"] == MODULE.EXPECTED_MODEL_SHA256
    assert frozen["raw_training_cutoff"] <= "2025-12-31"
    assert frozen["gross_scaler_contract_hash"] == MODULE.EXPECTED_GROSS_CONTRACT_HASH
    assert frozen["taxonomy_hash"] == MODULE.EXPECTED_TAXONOMY_LOGICAL_HASH
    assert contract["top_n"] == 20
    assert state["forward_session_count"] == 0


def test_02_freeze_timestamp_immutable_and_calendar_derived(initialized):
    contract, _ = initialized
    first = MODULE.load_contract()
    second = MODULE.load_contract()
    assert first["forward_freeze_timestamp_utc"] == second["forward_freeze_timestamp_utc"]
    provider = MODULE.ForwardShadowTradingCalendarProvider(MODULE.CALENDAR_CONTRACT)
    assert provider.is_session(contract["first_eligible_forward_session"])
    freeze = MODULE.parse_timestamp(contract["forward_freeze_timestamp_utc"])
    first_open = MODULE.datetime.combine(
        MODULE.datetime.fromisoformat(contract["first_eligible_forward_session"]).date(), MODULE.OPEN_TIME, MODULE.MARKET_TZ
    ).astimezone(MODULE.timezone.utc)
    assert first_open > freeze


def test_03_four_arm_arithmetic_and_no_mutation(initialized):
    contract, state = initialized
    payload, now = MODULE.synthetic_payload(contract)
    ledger_hash = MODULE.sha256_file(MODULE.FORWARD_LEDGER)
    row, candidate = MODULE.process_session(payload, contract, copy.deepcopy(state), verify_refs=False, now=now)
    assert abs(float(row["raw_scaled_gross"]) - float(row["s1_scaled_gross"])) <= 1e-12
    assert abs(float(row["raw_scaled_gross"]) + float(row["raw_scaled_cash"]) - 1.0) <= 1e-12
    assert abs(float(row["s1_minus_raw_return"]) - (float(row["s1_return"]) - float(row["raw_return"]))) <= 1e-12
    assert candidate["forward_session_count"] == 1
    assert MODULE.sha256_file(MODULE.FORWARD_LEDGER) == ledger_hash
    assert MODULE.read_json(MODULE.FORWARD_STATE)["forward_session_count"] == 0


def test_04_normalized_hhi_invariance_and_cost_accounting(initialized):
    contract, state = initialized
    payload, now = MODULE.synthetic_payload(contract)
    checked = MODULE.validate_session_input(payload, contract, state, verify_refs=False, now=now)
    targets, mechanics = MODULE.arm_targets(checked["targets"], contract)
    raw_scaled = MODULE.concentration(targets[MODULE.ARM3], checked["targets"])
    s1_scaled = MODULE.concentration(targets[MODULE.ARM2], checked["targets"])
    assert abs(raw_scaled["ff12_hhi"] - mechanics["raw"]["ff12_hhi"]) <= 1e-12
    assert abs(s1_scaled["ff48_hhi"] - mechanics["s1"]["ff48_hhi"]) <= 1e-12
    entry = {row["ticker"]: row["entry_open"] for row in payload["price_rows"]}
    outcome = {row["ticker"]: row["outcome_open"] for row in payload["price_rows"]}
    _, result = MODULE.rebalance_and_mark(MODULE.initial_arm_state(), targets[MODULE.ARM0], entry, outcome)
    assert result["turnover"] > 0
    assert result["cost"] > 0
    assert abs(result["cost"] - result["turnover"] * MODULE.COST_RATE) <= 2e-7


def test_05_pre_freeze_duplicate_out_of_order_and_lock(initialized):
    contract, state = initialized
    payload, now = MODULE.synthetic_payload(contract)
    row, _ = MODULE.process_session(payload, contract, state, verify_refs=False, now=now)
    ledger = MODULE.OUT / ".focused_test_ledger.csv"
    assert not ledger.exists()
    try:
        MODULE.ensure_ledger(ledger)
        MODULE.append_ledger_row(ledger, row, contract)
        with pytest.raises(MODULE.ForwardGateError, match="DUPLICATE_SESSION_REJECTED"):
            MODULE.append_ledger_row(ledger, row, contract)
        earlier = dict(row)
        earlier["session_date"] = MODULE.previous_session(
            MODULE.ForwardShadowTradingCalendarProvider(MODULE.CALENDAR_CONTRACT), row["session_date"]
        )
        with pytest.raises(MODULE.ForwardGateError, match="OUT_OF_ORDER|PRE_FREEZE"):
            MODULE.append_ledger_row(ledger, earlier, contract)
        with MODULE.LedgerLock(ledger):
            with pytest.raises(MODULE.ForwardGateError, match="LOCK_ALREADY_HELD"):
                with MODULE.LedgerLock(ledger):
                    pass
        invalid = copy.deepcopy(payload)
        invalid["decision_timestamp"] = (
            MODULE.parse_timestamp(contract["forward_freeze_timestamp_utc"]) - timedelta(seconds=1)
        ).isoformat()
        with pytest.raises(MODULE.ForwardGateError, match="DECISION_NOT_POSTFREEZE_EXANTE"):
            MODULE.process_session(invalid, contract, state, verify_refs=False, now=now)
        assert MODULE.validate_hash_chain(ledger)["status"] == "PASS"
    finally:
        ledger.unlink(missing_ok=True)


def test_06_daily_missing_input_is_zero_mutation(initialized):
    before_ledger = MODULE.sha256_file(MODULE.FORWARD_LEDGER)
    before_state = MODULE.sha256_file(MODULE.FORWARD_STATE)
    result = MODULE.daily(MODULE.OUT / ".does_not_exist.json")
    assert result["status"] == "SESSION_DATA_BLOCKED"
    assert result["ledger_mutated"] is False
    assert MODULE.sha256_file(MODULE.FORWARD_LEDGER) == before_ledger
    assert MODULE.sha256_file(MODULE.FORWARD_STATE) == before_state


def test_07_hash_manifest_and_artifact_budget(initialized):
    contract, state = initialized
    chain = MODULE.verify_state(contract, MODULE.read_json(MODULE.FORWARD_STATE))
    assert chain["status"] == "PASS" and chain["row_count"] == 0
    manifest = MODULE.read_json(MODULE.HASH_MANIFEST)
    assert manifest["status"] == "PASS_HASH_VERIFIED"
    assert manifest["artifact_count_including_manifest"] == 4
    assert len(list(MODULE.OUT.iterdir())) == 4
    for row in manifest["artifacts"]:
        assert MODULE.sha256_file(MODULE.OUT / row["name"]) == row["sha256"]
