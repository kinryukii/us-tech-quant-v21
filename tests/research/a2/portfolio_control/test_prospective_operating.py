"""Outcome-free checks of the thin monitor and reused transaction mechanics.

These tests do not certify RX recorder integration or global access control.
No real registry, session, economic state or outcome fixture is loaded.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from forward_shadow.components import SyntheticComponent, validate_component_output_contract
from forward_shadow.protocol import ProtocolStore
from forward_shadow.runner import UnifiedShadowRunner
from forward_shadow.schemas import (
    CanonicalReadiness, ComponentIdentity, ComponentResult, ROLES, RunIdentity,
    RunnerConfig,
)
from scripts.research.a2.portfolio_control import prospective_operating as monitor


@pytest.fixture
def tmp_path():
    from scripts.common.storage_paths import resolve

    roots = resolve()
    base = Path(os.environ["PROSPECTIVE_OPERATING_TEST_ROOT"]).resolve()
    assert roots.cache_root in base.parents
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        assert path.resolve().parent == base and roots.cache_root in path.resolve().parents
        shutil.rmtree(path)


def context(tmp_path):
    day = "2026-09-09"  # Synthetic clock, never a real-result read.
    components = {
        role: ComponentIdentity(role, "SYNTHETIC_" + role, role + "_CHAMPION",
                                "FROZEN", "FIXTURE_FREEZE", "unused", "a" * 64,
                                "2025-12-31", False, False, False, "2026-09-08")
        for role in ROLES
    }
    identity = RunIdentity(day, "b" * 64, "SYNTHETIC", "c" * 64, components)
    readiness = CanonicalReadiness(day, day, "unused", "b" * 64, "SYNTHETIC",
                                   (day,), (day,), (day,), (day,))
    config = RunnerConfig(registry_paths={r: "UNUSED" for r in ROLES},
                          production_adapters={r: "UNUSED" for r in ROLES})
    records = {
        "ALPHA": {"target_date": day, "security_id": "S0", "ticker": "FIXTURE",
                  "rank": 1, "score": 0.2, "raw_target_weight": 1.0,
                  "model_id": "SYNTHETIC_ALPHA", "universe_id": "SYNTHETIC",
                  "vintage_id": "FIXTURE"},
        "RISK": {"target_date": day, "security_id": "S0", "risk_model_id": "SYNTHETIC_RISK"},
        "EXECUTION": {"target_date": day, "security_id": "S0", "pre_execution_weight": 0,
                      "post_execution_weight": 1.0, "execution_action": "ENTER",
                      "execution_overlay_id": "SYNTHETIC_EXECUTION"},
    }
    adapters = {r: SyntheticComponent(r, {"records": [records[r]]}) for r in ROLES}
    store = ProtocolStore(tmp_path / "staging", tmp_path / "authoritative")
    return identity, readiness, config, adapters, store


def test_existing_commit_rerun_and_changed_authority(tmp_path):
    identity, readiness, config, adapters, store = context(tmp_path)
    original = copy.deepcopy(identity.to_dict())
    runner = UnifiedShadowRunner(config, store)
    first = runner.run(identity, readiness, adapters, mode="synthetic", commit=True)
    assert first["commit_status"] == "COMMITTED"
    repeat = runner.run(identity, readiness, adapters, mode="synthetic", commit=True)
    assert repeat["commit_status"] == "ALREADY_COMMITTED_IDENTICAL"
    assert repeat["new_rows_appended"] == 0
    assert len(store.committed_transactions()) == 1
    changed = replace(identity, canonical_manifest_sha256="d" * 64)
    assert store.check_duplicate(changed)["status"] == "CONFLICT_EXISTING_COMMIT"
    changed_components = dict(identity.components)
    changed_components["ALPHA"] = replace(changed_components["ALPHA"], artifact_sha256="e" * 64)
    assert store.check_duplicate(replace(identity, components=changed_components))["status"] == "CONFLICT_EXISTING_COMMIT"
    assert identity.to_dict() == original
    with pytest.raises(FrozenInstanceError):
        identity.components["ALPHA"].model_id = "OTHER"


def test_existing_failure_recovery_counts_once_and_rejects_drift(tmp_path):
    identity, readiness, config, adapters, store = context(tmp_path)
    runner = UnifiedShadowRunner(config, store)
    failing = dict(adapters)
    failing["ALPHA"] = SyntheticComponent("ALPHA", {"prepare_fail": True})
    result = runner.run(identity, readiness, failing, mode="synthetic", commit=True)
    assert result["new_rows_appended"] == 0
    assert not store.committed_transactions()
    assert store.assess_resume(replace(identity, config_sha256="d" * 64))["status"] == "RESUME_FORBIDDEN_INPUT_CHANGED"
    recovered = runner.run(identity, readiness, adapters, mode="synthetic", commit=True, resume=True)
    assert recovered["commit_status"] == "COMMITTED"
    assert len(store.committed_transactions()) == 1
    assert (store.transaction_path(identity.run_id) / "failure_manifest.json").is_file()
    assert runner.run(identity, readiness, adapters, mode="synthetic", commit=True)["new_rows_appended"] == 0


def test_existing_incomplete_commit_is_not_observation(tmp_path):
    identity, readiness, config, adapters, store = context(tmp_path)
    runner = UnifiedShadowRunner(config, store)
    result = runner.run(identity, readiness, adapters, mode="synthetic", commit=True, crash_after_publish=True)
    assert result["commit_status"] != "COMMITTED"
    assert result["new_rows_appended"] == 0
    assert not store.committed_transactions()
    assert store.check_duplicate(identity)["status"] == "RECOVERY_REQUIRED"


def test_existing_output_authority_and_policy_mutation_rejected(tmp_path):
    identity, _, config, adapters, _ = context(tmp_path)
    output = adapters["ALPHA"].execute(identity)
    wrong = dict(output.records[0], model_id="OTHER_AUTHORITY")
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_component_output_contract(replace(output, records=(wrong,)), identity)
    for flag in ("training_allowed", "parameter_search_allowed", "model_selection_allowed", "broker_action_allowed"):
        with pytest.raises(ValueError, match="unsafe runner capability"):
            replace(config, **{flag: True}).validate()


def monitor_fixture(tmp_path, monkeypatch):
    paths = SimpleNamespace(repo_root=tmp_path / "repo", results_root=tmp_path / "results",
                            daily_root=tmp_path / "daily")
    root = paths.results_root / monitor.RAW_TASK
    root.mkdir(parents=True)
    source = paths.repo_root / "scripts/v22/a2_three_arm_postfreeze_forward_r1.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic source; never execute\n", encoding="utf-8")
    contract = {
        "frozen_identities": {key: "a" * 64 for key in (
            "raw_model_hash", "raw_portfolio_hash", "taxonomy_hash", "calendar_contract_sha256")},
        "forward_contract_hash": "b" * 64, "milestones": monitor.RAW_MILESTONES,
        "forward_freeze_timestamp_utc": "2026-09-01T00:00:00Z",
        "first_eligible_forward_session": "2026-09-02",
    }
    contract_path = root / "forward_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    monkeypatch.setattr(monitor, "RAW_CONTRACT_SHA256", hashlib.sha256(contract_path.read_bytes()).hexdigest())
    monkeypatch.setattr(monitor, "RAW_SOURCE_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(monitor, "resolve", lambda: paths)
    return paths, root, contract_path


def issued_fixture():
    return {
        "status": "PASS", "authority_status": "VALID_ISSUED_PROSPECTIVE_AUTHORITY",
        "committed": True, "registration_id": monitor.RX_REGISTRATION_ID,
        "entity_id": monitor.RX_ENTITY_ID, "manifest_id": "c" * 64,
        "issuance_authority_sha256": "d" * 64,
        "first_legal_epoch": {"signal_information_eligible_utc": "2026-09-08T21:00:00Z",
                              "decision_eligible_utc": "2026-09-08T21:00:00Z",
                              "epoch_completion_utc": "2026-09-09T13:30:00Z"},
    }


def test_monitor_never_opens_economic_state_or_session_input(tmp_path, monkeypatch):
    paths, root, _ = monitor_fixture(tmp_path, monkeypatch)
    pointer = paths.daily_root / "current" / monitor.RAW_TASK / "session_input.json"
    pointer.parent.mkdir(parents=True)
    forbidden = {root / "forward_state.json", root / "forward_ledger.csv", pointer}
    for path in forbidden:
        path.write_text("SEALED_SYNTHETIC_PNL_92817", encoding="utf-8")
    original_open = Path.open
    opened = []

    def intercept(path, *args, **kwargs):
        opened.append(path)
        assert path not in forbidden, "economic body must not be opened even for hashing"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", intercept)
    result = monitor.raw_status(paths)
    assert result["identity_status"] == "PASS_HASH_PINNED_FROZEN_CONTRACT"
    assert result["current_observation_count"] == "UNKNOWN"
    assert result["session_input_exists"] is True
    assert result["data_authority_identity"] == "UNKNOWN"
    assert "SEALED_SYNTHETIC" not in json.dumps(result)
    assert not forbidden.intersection(opened)


def test_monitor_rejects_frozen_contract_drift(tmp_path, monkeypatch):
    paths, _, contract_path = monitor_fixture(tmp_path, monkeypatch)
    contract_path.write_text('{"model":"changed"}', encoding="utf-8")
    result = monitor.raw_status(paths)
    assert result["identity_status"] == "FAIL_CLOSED"
    assert result["error_category"] == "METADATA_VALIDATION_FAILED"
    assert "model_identity" not in result


@pytest.mark.parametrize("field,value", [("committed", False), ("entity_id", "WRONG"),
                                         ("registration_id", "e" * 64), ("status", "UNKNOWN")])
def test_monitor_rejects_unissued_or_wrong_authority(monkeypatch, field, value):
    authority = issued_fixture()
    authority[field] = value
    monkeypatch.setattr(monitor, "_rx_activation", lambda: authority)
    result = monitor.rx_status()
    assert result["identity_status"] == "FAIL_CLOSED"
    assert "activation_manifest_id" not in result


def test_monitor_drops_economics_and_never_promotes_activation_to_observation(monkeypatch):
    authority = issued_fixture()
    authority.update({"pnl": 92817, "winner": "SEALED_SYNTHETIC", "events": [{"return": 18.2}],
                      "observation_count": 99, "zero_observation_attestation": {"observation_count": 0}})
    monkeypatch.setattr(monitor, "_rx_activation", lambda: authority)
    result = monitor.rx_status()
    assert result["identity_status"] == "VALID_ISSUED_PROSPECTIVE_AUTHORITY"
    assert result["current_observation_count"] == "UNKNOWN"
    assert result["operational_status"] == "BLOCKED_RECORDER_BINDING_UNKNOWN"
    assert result["reveal_policy"] == "OWNER_APPROVAL_REQUIRED_BEFORE_ECONOMIC_REVEAL"
    assert result["automatic_reveal"] is False
    assert not {"pnl", "events", "winner", "observation_count"}.intersection(result)
    assert "92817" not in json.dumps(result)


@pytest.mark.parametrize("exception", [PermissionError("SEALED_PNL_92817"), ValueError("SEALED_PNL_92817")])
def test_monitor_failure_never_emits_exception_text(monkeypatch, exception):
    def fail():
        raise exception

    monkeypatch.setattr(monitor, "_rx_activation", fail)
    result = monitor.rx_status()
    assert result["identity_status"] == "FAIL_CLOSED"
    assert "SEALED" not in json.dumps(result)
    assert set(result).isdisjoint({"failure_reason", "events", "traceback"})


def test_monitor_has_no_economic_reader_or_recorder_command(monkeypatch, capsys):
    monkeypatch.setattr(monitor, "operational_status", lambda: pytest.fail("must reject before any read"))
    for command in ("reveal", "economic", "record", "run"):
        with pytest.raises(SystemExit) as error:
            monitor.main([command])
        assert error.value.code == 2
    capsys.readouterr()


def test_monitor_reruns_are_identical_and_read_only(tmp_path, monkeypatch, capsys):
    paths, root, _ = monitor_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(monitor, "_rx_activation", issued_fixture)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    first = monitor.operational_status()
    assert monitor.main(["status"]) == 2
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["status"] == "BLOCKED_PROSPECTIVE_PROGRAM_INCOMPLETE"
    assert first["economic_reveal_allowed"] is False
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_monitor_routing_drift_rejected_before_loading_validator(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "RX_SOURCE_ROOT", tmp_path)
    # A corrupt route must not reach the callable that would read its destination.
    original = monitor._pinned_bytes
    calls = []

    def pins(path, expected, *args):
        calls.append(path.name)
        if path.name == "research_registry.json":
            raise ValueError("UNAUTHORIZED_DESTINATION")
        return b"raise AssertionError('validator must not be loaded')"

    monkeypatch.setattr(monitor, "_pinned_bytes", pins)
    assert monitor.rx_status()["identity_status"] == "FAIL_CLOSED"
    assert "research_registry.json" in calls
