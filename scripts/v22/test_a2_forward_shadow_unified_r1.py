"""Targeted synthetic tests for the unified forward-shadow protocol."""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from forward_shadow.components import SyntheticComponent
from forward_shadow.manifest import file_sha256, synthetic_chain_manifest, validate_history_chain
from forward_shadow.preflight import run_preflight
from forward_shadow.protocol import ProtocolError, ProtocolStore, atomic_json
from forward_shadow.registry_resolver import resolve_components
from forward_shadow.runner import UnifiedShadowRunner
from forward_shadow.schemas import CanonicalReadiness, ComponentResult, RunIdentity, RunnerConfig
from a2_forward_shadow_unified_r1 import (
    A2_PORTFOLIO_POLICY_DEFAULT_ENABLED,
    _pure_fixture_validation,
    main as cli_main,
)


FIXTURE_PATH = HERE / "fixtures" / "forward_shadow" / "tiny_unified_shadow_fixture.json"
CONFIG_PATH = REPO / "config" / "research_governance" / "a2_forward_shadow_unified_r1.json"
_CASE_NUMBER = 0


@pytest.fixture
def tmp_path() -> Path:
    """Use a pre-created root; pytest's Windows 0o700 basetemp is unreadable here."""
    global _CASE_NUMBER
    root_value = os.environ.get("A2_FORWARD_SHADOW_SYNTHETIC_TEST_ROOT")
    if not root_value:
        pytest.fail("A2_FORWARD_SHADOW_SYNTHETIC_TEST_ROOT is required")
    root = Path(root_value).resolve()
    if "forward_shadow_synthetic" not in root.name:
        pytest.fail("refusing non-synthetic test root")
    _CASE_NUMBER += 1
    path = root / f"case_{_CASE_NUMBER:03d}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def a2_policy_fixture() -> dict:
    data = fixture_payload()
    data["components"]["ALPHA"]["records"] = [
        {
            "target_date": data["target_date"], "security_id": f"S{index:02d}",
            "ticker": f"T{index:02d}", "rank": index, "score": float(100 - index),
            "raw_target_weight": 0.05, "model_id": "A2_HGB",
            "universe_id": "SYNTHETIC_TOP20_UNIVERSE", "vintage_id": "V_SYNTHETIC",
        }
        for index in range(1, 21)
    ]
    data["components"]["RISK"]["records"] = [
        {
            "target_date": data["target_date"], "security_id": f"S{index:02d}",
            "risk_model_id": "R6_BAD_ASYMMETRY",
        }
        for index in range(1, 3)
    ]
    data["components"]["EXECUTION"]["records"] = [
        {
            "target_date": data["target_date"], "security_id": f"S{index:02d}",
            "pre_execution_weight": 0.0, "post_execution_weight": 0.05,
            "execution_action": "ENTER", "execution_overlay_id": "E5_COMBINED_CONSERVATIVE",
        }
        for index in range(1, 3)
    ]
    data["components"]["EXECUTION"]["security_alignment_reason"] = "SYNTHETIC_SUBSET_FOR_POLICY_INTEGRATION"
    data["a2_portfolio_policy"] = {
        "enabled": True,
        "current_portfolio": {"as_of": data["target_date"], "cash": 2000.0, "positions": []},
        "market_prices": {f"US.T{index:02d}": 100.0 for index in range(1, 21)},
    }
    return data


def config() -> RunnerConfig:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["registry_paths"] = {role: str(REPO / path) for role, path in payload["registry_paths"].items()}
    return RunnerConfig.from_dict(payload)


def context(tmp_path: Path, payload: dict | None = None, canonical_hash: str | None = None):
    data = copy.deepcopy(payload or fixture_payload())
    readiness = CanonicalReadiness.from_dict(data["canonical_readiness"])
    components = resolve_components(
        config().registry_paths, synthetic_overrides=data["synthetic_component_overrides"]
    )
    identity = RunIdentity(
        target_date=data["target_date"],
        canonical_manifest_sha256=canonical_hash or readiness.canonical_manifest_sha256,
        universe_id=readiness.universe_id,
        config_sha256="f" * 64,
        components=components,
    )
    adapters = {role: SyntheticComponent(role, data["components"][role]) for role in ("ALPHA", "RISK", "EXECUTION")}
    store = ProtocolStore(tmp_path / "staging", tmp_path / "authoritative")
    return data, readiness, identity, adapters, store


def run_synthetic(tmp_path: Path, payload: dict | None = None, **kwargs):
    _, readiness, identity, adapters, store = context(tmp_path, payload)
    status = UnifiedShadowRunner(config(), store).run(
        identity, readiness, adapters, mode=kwargs.pop("mode", "synthetic"),
        commit=kwargs.pop("commit", True), **kwargs,
    )
    return status, identity, store


def test_clean_successful_daily_transaction(tmp_path):
    status, identity, store = run_synthetic(tmp_path)
    assert (status["staging_status"], status["reconciliation_status"], status["commit_status"]) == ("PASS", "PASS", "COMMITTED")
    assert store.resolve_authoritative(identity.target_date) is not None


def test_same_target_date_required(tmp_path):
    data = fixture_payload()
    data["components"]["RISK"]["target_date"] = "2026-08-20"
    for row in data["components"]["RISK"]["records"]:
        row["target_date"] = "2026-08-20"
    status, _, store = run_synthetic(tmp_path, data)
    assert status["cross_shadow_date_status"] == "FAIL"
    assert status["commit_status"] == "NOT_COMMITTED"
    assert not store.committed_transactions()


def test_lineage_mismatch(tmp_path):
    data = fixture_payload()
    data["components"]["EXECUTION"]["input_alpha_run_id"] = "WRONG_ALPHA"
    status, _, _ = run_synthetic(tmp_path, data)
    assert status["cross_component_lineage_status"] == "FAIL"
    assert status["failure_code"] == "FAIL_LINEAGE"


@pytest.mark.parametrize("failed_role", ["RISK", "EXECUTION"])
def test_downstream_failure_has_no_authoritative_partial_commit(tmp_path, failed_role):
    data = fixture_payload()
    data["components"][failed_role]["status"] = "FAIL"
    data["components"][failed_role]["failure_reason"] = "synthetic failure"
    status, _, store = run_synthetic(tmp_path, data)
    assert status["failure_code"] == f"FAIL_COMPONENT_{failed_role}"
    assert not store.committed_transactions()
    assert not (store.authoritative_root / "transactions").exists()


def test_duplicate_identical_date_is_idempotent(tmp_path):
    first, _, _ = run_synthetic(tmp_path)
    second, _, _ = run_synthetic(tmp_path)
    assert first["commit_status"] == "COMMITTED"
    assert second["commit_status"] == "ALREADY_COMMITTED_IDENTICAL"
    assert second["new_rows_appended"] == 0


def test_conflicting_duplicate_date(tmp_path):
    run_synthetic(tmp_path)
    data, readiness, identity, adapters, store = context(tmp_path, canonical_hash="d" * 64)
    readiness = replace(readiness, canonical_manifest_sha256="d" * 64)
    status = UnifiedShadowRunner(config(), store).run(identity, readiness, adapters, mode="synthetic", commit=True)
    assert status["duplicate_status"] == "CONFLICT_EXISTING_COMMIT"
    assert status["failure_code"] == "FAIL_DUPLICATE_CONFLICT"


def test_overwrite_forbidden(tmp_path):
    _, readiness, identity, adapters, store = context(tmp_path)
    status = UnifiedShadowRunner(config(), store).run(
        identity, readiness, adapters, mode="synthetic", commit=True, overwrite=True
    )
    assert status["failure_code"] == "FAIL_COMMIT"
    assert not store.committed_transactions()


def test_unknown_frozen_hash_blocks_production(tmp_path):
    _, readiness, identity, _, _ = context(tmp_path)
    components = dict(identity.components)
    components["RISK"] = replace(components["RISK"], artifact_sha256="UNKNOWN")
    identity = replace(identity, components=components)
    result = run_preflight(identity.target_date, readiness, components, config(), mode="production")
    assert result["status"] == "FAIL_CLOSED"
    assert "RISK_HASH_NOT_YET_MATERIALIZED" in result["reasons"]


def test_2026_inference_allowed(tmp_path):
    _, readiness, identity, _, _ = context(tmp_path)
    result = run_preflight(identity.target_date, readiness, identity.components, config(), mode="synthetic")
    assert result["status"] == "PASS"
    assert result["2026_inference_allowed"] is True


@pytest.mark.parametrize(
    "field,value",
    [("fit_called", True), ("model_selection_run", True), ("broker_action", True)],
)
def test_inference_only_governance_violations_fail(tmp_path, field, value):
    data = fixture_payload()
    data["components"]["ALPHA"][field] = value
    status, _, store = run_synthetic(tmp_path, data)
    assert status["governance_status"] == "FAIL"
    assert status["failure_code"] == "FAIL_GOVERNANCE"
    assert not store.committed_transactions()


def write_chain(root: Path, count: int = 3) -> list[Path]:
    paths, previous = [], None
    for index in range(count):
        path = root / f"day{index + 1}.json"
        atomic_json(path, synthetic_chain_manifest(f"2026-08-{18 + index:02d}", previous, f"D{index + 1}"))
        previous = file_sha256(path)
        paths.append(path)
    return paths


def test_manifest_hash_chain_three_days(tmp_path):
    paths = write_chain(tmp_path)
    assert validate_history_chain(paths)["history_chain_status"] == "PASS"


def test_tampered_historical_manifest_fails_chain(tmp_path):
    paths = write_chain(tmp_path)
    payload = json.loads(paths[1].read_text(encoding="utf-8"))
    payload["payload_tag"] = "TAMPERED"
    atomic_json(paths[1], payload)
    result = validate_history_chain(paths)
    assert result["history_chain_status"] == "FAIL"
    assert any(reason.startswith("PREDECESSOR_HASH_MISMATCH") for reason in result["reasons"])


def test_tampered_committed_transaction_is_not_hidden(tmp_path):
    _, identity, store = run_synthetic(tmp_path)
    transaction = store.transaction_path(identity.run_id)
    manifest_path = transaction / "daily_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["universe_id"] = "TAMPERED"
    atomic_json(manifest_path, payload)
    status = store.history_status()
    assert status["history_chain_status"] == "FAIL"
    assert "INCOMPLETE_OR_INVALID_TRANSACTION" in status["reasons"]
    assert store.resolve_authoritative(identity.target_date) is None


def test_resume_identical_inputs(tmp_path):
    data = fixture_payload()
    data["components"]["RISK"]["status"] = "FAIL"
    run_synthetic(tmp_path, data)
    _, readiness, identity, adapters, store = context(tmp_path)
    assessment = store.assess_resume(identity)
    assert assessment["status"] == "RESUME_ALLOWED"
    status = UnifiedShadowRunner(config(), store).run(identity, readiness, adapters, mode="resume", commit=True, resume=True)
    assert status["commit_status"] == "COMMITTED"


def test_resume_changed_canonical_hash_forbidden(tmp_path):
    data = fixture_payload()
    data["components"]["RISK"]["status"] = "FAIL"
    run_synthetic(tmp_path, data)
    _, _, changed, _, store = context(tmp_path, canonical_hash="d" * 64)
    assert store.assess_resume(changed)["status"] == "RESUME_FORBIDDEN_INPUT_CHANGED"


def test_staging_is_not_authoritative(tmp_path):
    status, identity, store = run_synthetic(tmp_path, commit=False)
    assert status["commit_status"] == "NOT_COMMITTED_DRY_RUN"
    assert store.resolve_authoritative(identity.target_date) is None


def test_missing_canonical_date_fails_closed(tmp_path):
    _, readiness, identity, _, _ = context(tmp_path)
    readiness = replace(readiness, available_dates=())
    result = run_preflight(identity.target_date, readiness, identity.components, config(), mode="synthetic")
    assert result["status"] == "FAIL_CLOSED"
    assert "TARGET_DATE_MISSING_CANONICAL" in result["reasons"]


def test_security_alignment_anomaly(tmp_path):
    data = fixture_payload()
    row = copy.deepcopy(data["components"]["RISK"]["records"][0])
    row["security_id"] = "NOT_ALPHA"
    data["components"]["RISK"]["records"].append(row)
    status, _, _ = run_synthetic(tmp_path, data)
    assert status["security_alignment_status"] == "FAIL"
    assert status["failure_code"] == "FAIL_SECURITY_ALIGNMENT"


def test_execution_subset_requires_explicit_reason(tmp_path):
    data = fixture_payload()
    data["components"]["EXECUTION"]["records"].pop()
    status, _, _ = run_synthetic(tmp_path, data)
    assert status["security_alignment_status"] == "FAIL"
    data["components"]["EXECUTION"]["security_alignment_reason"] = "E5_ZERO_WEIGHT_FILTERING"
    status, _, _ = run_synthetic(tmp_path / "with_reason", data)
    assert status["security_alignment_status"] == "PASS"


def test_active_lock_denies_second_run(tmp_path):
    _, _, identity, _, store = context(tmp_path)
    assert store.acquire_lock(identity)["status"] == "LOCK_ACQUIRED"
    try:
        assert store.acquire_lock(identity)["status"] == "ACTIVE_LOCK_DENIED"
    finally:
        assert store.release_lock(identity)


def test_unknown_lock_requires_review_and_is_preserved(tmp_path):
    _, _, identity, _, store = context(tmp_path)
    lock = store._lock_path(identity.target_date)
    atomic_json(lock, {"run_id": "UNKNOWN", "pid": -1, "owner_status": "ACTIVE"})
    assert store.acquire_lock(identity)["status"] == "STALE_LOCK_REVIEW_REQUIRED"
    assert lock.is_file()


def test_lock_released_after_successful_commit(tmp_path):
    status, identity, store = run_synthetic(tmp_path)
    assert status["commit_status"] == "COMMITTED"
    assert not store._lock_path(identity.target_date).exists()


def test_crash_during_commit_requires_recovery(tmp_path):
    status, identity, store = run_synthetic(tmp_path, crash_after_publish=True)
    assert status["commit_status"] == "COMMIT_NOT_COMPLETE"
    assert store.resolve_authoritative(identity.target_date) is None
    assert store.check_duplicate(identity)["status"] == "RECOVERY_REQUIRED"


def test_production_config_has_fail_closed_defaults():
    cfg = config()
    assert cfg.append_only and cfg.require_frozen_hashes and cfg.history_hash_chain_enabled
    assert not any((cfg.allow_overwrite, cfg.auto_canonical_refresh, cfg.broker_action_allowed, cfg.training_allowed, cfg.parameter_search_allowed, cfg.model_selection_allowed))
    assert cfg.production_adapters == {
        "ALPHA": "forward_shadow.production_binding:create_alpha_adapter",
        "RISK": "forward_shadow.production_binding:create_risk_adapter",
        "EXECUTION": "forward_shadow.production_binding:create_execution_adapter",
    }
    binding = json.loads(Path(cfg.production_binding_manifest).read_text(encoding="utf-8"))
    assert {
        binding["components"][role]["execute_binding_status"]
        for role in ("ALPHA", "RISK", "EXECUTION")
    } == {"BOUND_SAFE_EXACT_DATE_ENTRYPOINT"}


def test_fixture_is_tiny_and_not_live_research_path():
    payload = fixture_payload()
    rows = sum(len(part["records"]) for part in payload["components"].values())
    assert rows < 1000
    assert "A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1" not in FIXTURE_PATH.as_posix()
    assert "A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1" not in json.dumps(payload)


def test_production_cli_never_falls_back_to_synthetic_fixture(capsys):
    exit_code = cli_main(["production", "--target-date", "2026-08-21", "--status-json"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--readiness-json is required" in captured.err


def test_policy_disabled_preserves_fixture_validation_output_exactly(tmp_path):
    assert A2_PORTFOLIO_POLICY_DEFAULT_ENABLED is False
    data, readiness, identity, adapters, _ = context(tmp_path, fixture_payload())
    baseline = _pure_fixture_validation(identity, readiness, config(), adapters, "validate-fixture")
    disabled = _pure_fixture_validation(
        identity, readiness, config(), adapters, "validate-fixture",
        policy_payload={"enabled": False},
    )
    assert disabled == baseline
    assert "a2_portfolio_policy" not in disabled


def test_policy_enabled_without_explicit_current_state_fails_closed(tmp_path):
    data = a2_policy_fixture()
    data["a2_portfolio_policy"].pop("current_portfolio")
    _, readiness, identity, adapters, _ = context(tmp_path, data)
    status = _pure_fixture_validation(
        identity, readiness, config(), adapters, "validate-fixture",
        policy_payload=data["a2_portfolio_policy"],
    )
    assert status["status"] == "FAIL"
    assert status["a2_portfolio_policy_status"] == "FAIL_CLOSED"
    assert status["commit_status"] == "NOT_COMMITTED_FIXTURE_VALIDATION"
    assert "EXPLICIT_CURRENT_PORTFOLIO_REQUIRED" in status["a2_portfolio_policy_failure_reason"]


def test_raw_a2_to_multi_position_safety_to_runner_shadow_end_to_end(tmp_path):
    data = a2_policy_fixture()
    _, readiness, identity, adapters, _ = context(tmp_path, data)
    status = _pure_fixture_validation(
        identity, readiness, config(), adapters, "validate-fixture",
        policy_payload=data["a2_portfolio_policy"],
    )
    assert status["status"] == "PASS"
    assert status["a2_portfolio_policy_status"] == "PASS"
    policy = status["a2_portfolio_policy"]
    assert policy["policy_plan"]["current_portfolio"]["cash_weight"] == 1.0
    assert len(policy["policy_plan"]["target_weights"]) == 20
    assert {row["action"] for row in policy["policy_plan"]["actions"]} == {"BUY"}
    assert policy["safety_plan"]["profile_id"] == "A2_MULTI_POSITION_SHADOW"
    assert len(policy["safety_plan"]["order_intents"]) == 20
    assert not policy["safety_plan"]["broker_submission_allowed"]
    assert not status["broker_action_run"]
