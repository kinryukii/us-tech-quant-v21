"""Tiny fail-closed tests for Forward Shadow Production Binding R1."""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import a2_forward_shadow_unified_r1 as unified
from a2_forward_shadow_readiness_r1 import generate_readiness
from forward_shadow.production_binding import (
    ProductionBindingError,
    component_composite_sha256,
    create_alpha_adapter,
    sha256_file,
    validate_binding_manifest,
)
from forward_shadow.schemas import CanonicalReadiness, ComponentIdentity, RunIdentity, RunnerConfig
from forward_shadow.schemas import canonical_sha256


REAL_CONFIG = REPO / "config" / "research_governance" / "a2_forward_shadow_unified_r1.json"
CALENDAR_CONTRACT = REPO / "config" / "research_governance" / "a2_forward_shadow_trading_calendar_r1.json"
_CASE_NUMBER = 0


@pytest.fixture
def tmp_path() -> Path:
    """Avoid pytest's inaccessible Windows basetemp behavior."""
    global _CASE_NUMBER
    root_value = os.environ.get("A2_FORWARD_BINDING_SYNTHETIC_TEST_ROOT")
    if not root_value:
        pytest.fail("A2_FORWARD_BINDING_SYNTHETIC_TEST_ROOT is required")
    root = Path(root_value).resolve()
    if "forward_binding_synthetic" not in root.name:
        pytest.fail("refusing non-synthetic test root")
    _CASE_NUMBER += 1
    case = root / f"case_{_CASE_NUMBER:03d}"
    case.mkdir(parents=True, exist_ok=False)
    return case


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def registry_row(role: str) -> dict:
    values = {
        "ALPHA": ("A2_HGB", "ALPHA_CHAMPION", "ALPHA", "A_FREEZE"),
        "RISK": ("R6_BAD_ASYMMETRY", "RISK_CHAMPION", "RISK", "R_FREEZE"),
        "EXECUTION": ("E5_COMBINED_CONSERVATIVE", "EXECUTION_CHAMPION", "EXECUTION", "E_FREEZE"),
    }[role]
    return {"model_id": values[0], "role": values[1], "model_family": values[2], "benchmark_id": values[3]}


def make_binding(tmp_path: Path, *, exact_date: str = "2026-07-13") -> tuple[Path, Path]:
    registries: dict[str, dict] = {}
    components: dict[str, dict] = {}
    for role in ("ALPHA", "RISK", "EXECUTION"):
        row = registry_row(role)
        registry_path = tmp_path / f"{role.lower()}_registry.json"
        write_json(registry_path, {"models": [row]})
        registries[role] = {"path": str(registry_path), "sha256": sha256_file(registry_path)}
        artifact = tmp_path / f"{role.lower()}_artifact.bin"
        artifact.write_bytes(f"immutable-{role}".encode())
        artifacts = [{"artifact_id": "model", "path": str(artifact), "sha256": sha256_file(artifact)}]
        if role == "ALPHA":
            contract = tmp_path / "alpha_contract.json"
            write_json(contract, {"contracts": {"A2_CONFIG_FINGERPRINT": "TINY_FEATURE_SCHEMA"}})
            artifacts.append({"artifact_id": "pre_final_freeze", "path": str(contract), "sha256": sha256_file(contract)})
        components[role] = {
            **row,
            "freeze_id": row["benchmark_id"],
            "status": "TEST_FROZEN",
            "selection_source": "PRE2026_ONLY",
            "uses_2026_training": False,
            "uses_2026_parameter_search": False,
            "uses_2026_model_selection": False,
            "artifacts": artifacts,
            "composite_sha256": component_composite_sha256(artifacts),
            "entrypoints": [],
            "execute_binding_status": "BOUND_SAFE_EXACT_DATE_ENTRYPOINT",
        }

    canonical_manifest = tmp_path / "canonical_manifest.json"
    write_json(canonical_manifest, {"latest_date": exact_date})
    pointer = tmp_path / "canonical_pointer.json"
    write_json(pointer, {
        "canonical_manifest_path": str(canonical_manifest),
        "canonical_complete_universe_date": exact_date,
        "source_policy": "MOOMOO_ONLY",
        "external_fallback_used": False,
    })
    universe = tmp_path / "universe.parquet"
    pd.DataFrame([{
        "effective_date": "2026-05-22", "universe_fingerprint": "TINY_UNIVERSE",
        "quarter": "2026Q1", "institution_count": 24,
    }]).to_parquet(universe, index=False)
    members = tmp_path / "members.parquet"
    pd.DataFrame([{"security_id": "AAA"}]).to_parquet(members, index=False)

    results = Path(r"D:\us-tech-quant-results")
    payload = {
        "binding_version": "A2_FORWARD_SHADOW_PRODUCTION_BINDING_R1",
        "training_allowed": False,
        "parameter_search_allowed": False,
        "threshold_search_allowed": False,
        "model_selection_allowed": False,
        "broker_action_allowed": False,
        "registries": registries,
        "components": components,
        "roots": {
            "unified_staging_root": str(results / "binding-test-staging"),
            "unified_authoritative_root": str(results / "binding-test-authoritative"),
            "readiness_root": str(results / "binding-test-readiness"),
        },
        "readiness_sources": {
            "canonical_pointer": {"path": str(pointer)},
            "trading_calendar": {"path": str(CALENDAR_CONTRACT), "sha256": sha256_file(CALENDAR_CONTRACT)},
            "universe_manifest": {"path": str(universe), "sha256": sha256_file(universe)},
            "universe_members": {"path": str(members), "sha256": sha256_file(members)},
        },
        "runtime": {"canonical_python": sys.executable},
    }
    binding = tmp_path / "binding.json"
    config = tmp_path / "config.json"
    config_payload = {
        "schema_version": "1.0.0",
        "runner_id": "A2_FORWARD_SHADOW_UNIFIED_RUNNER_R1",
        "require_frozen_hashes": True,
        "append_only": True,
        "allow_overwrite": False,
        "allow_duplicate_identical": False,
        "require_same_target_date": True,
        "require_lineage_match": True,
        "auto_canonical_refresh": False,
        "broker_action_allowed": False,
        "training_allowed": False,
        "parameter_search_allowed": False,
        "model_selection_allowed": False,
        "staging_root": payload["roots"]["unified_staging_root"],
        "authoritative_shadow_root": payload["roots"]["unified_authoritative_root"],
        "readiness_root": payload["roots"]["readiness_root"],
        "production_binding_manifest": str(binding),
        "production_binding_sha256": "PENDING_BINDING_SHA256",
        "history_hash_chain_enabled": True,
        "retain_failed_staging": True,
        "risk_must_be_subset_of_alpha": True,
        "require_risk_for_every_alpha": False,
        "execution_must_be_subset_of_alpha": True,
        "allow_execution_subset_with_reason": True,
        "registry_paths": {role: value["path"] for role, value in registries.items()},
        "production_adapters": {
            "ALPHA": "forward_shadow.production_binding:create_alpha_adapter",
            "RISK": "forward_shadow.production_binding:create_risk_adapter",
            "EXECUTION": "forward_shadow.production_binding:create_execution_adapter",
        },
    }
    contract_payload = dict(config_payload)
    contract_payload["production_binding_sha256"] = "SELF_REFERENCE_EXCLUDED"
    payload["unified_runner_config_contract_sha256"] = canonical_sha256(contract_payload)
    payload["unified_runner_config_hash_definition"] = "CANONICAL_JSON_WITH_PRODUCTION_BINDING_SHA256_SET_TO_SELF_REFERENCE_EXCLUDED"
    write_json(binding, payload)
    config_payload["production_binding_sha256"] = sha256_file(binding)
    write_json(config, config_payload)
    return binding, config


def component_input_refs(tmp_path: Path, target_date: str = "2026-07-13") -> dict[str, dict[str, str]]:
    refs = {}
    for role in ("ALPHA", "RISK", "EXECUTION"):
        path = tmp_path / f"{role.lower()}_input.json"
        write_json(path, {"target_date": target_date, "role": role})
        refs[role] = {"path": str(path), "sha256": sha256_file(path)}
    return refs


def validation(binding: Path) -> dict:
    return validate_binding_manifest(binding, sha256_file(binding))


def test_01_verified_alpha_binding(tmp_path):
    binding, _ = make_binding(tmp_path)
    assert validation(binding)["components"]["ALPHA"]["status"] == "PASS"


def test_02_alpha_hash_mismatch_fails_closed(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    Path(payload["components"]["ALPHA"]["artifacts"][0]["path"]).write_bytes(b"tampered")
    assert validation(binding)["components"]["ALPHA"]["status"] == "FAIL_CLOSED"


def test_03_verified_r6_binding(tmp_path):
    binding, _ = make_binding(tmp_path)
    assert validation(binding)["components"]["RISK"]["status"] == "PASS"


def test_04_r6_post2026_selection_fails(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    payload["components"]["RISK"]["selection_source"] = "POST2026_SELECTED"
    write_json(binding, payload)
    assert "RISK:POST2026_SELECTION_ARTIFACT_FORBIDDEN" in validation(binding)["reasons"]


def test_05_verified_e5_composite_identity(tmp_path):
    binding, _ = make_binding(tmp_path)
    assert validation(binding)["components"]["EXECUTION"]["status"] == "PASS"


def test_06_e5_config_change_fails_hash(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    Path(payload["components"]["EXECUTION"]["artifacts"][0]["path"]).write_bytes(b"changed")
    assert validation(binding)["components"]["EXECUTION"]["status"] == "FAIL_CLOSED"


def test_07_wrong_registry_champion_fails(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    registry = Path(payload["registries"]["ALPHA"]["path"])
    write_json(registry, {"models": [{**registry_row("ALPHA"), "model_id": "NOT_A2"}]})
    payload["registries"]["ALPHA"]["sha256"] = sha256_file(registry)
    write_json(binding, payload)
    assert validation(binding)["status"] == "FAIL_CLOSED"


def test_08_wrong_role_fails(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    payload["components"]["ALPHA"]["role"] = "RISK_CHAMPION"
    write_json(binding, payload)
    assert validation(binding)["components"]["ALPHA"]["status"] == "FAIL_CLOSED"


def test_09_readiness_exact_date_pass(tmp_path):
    _, config = make_binding(tmp_path)
    result = generate_readiness(
        "2026-07-13", config, generated_at="2026-08-21T00:00:00+00:00",
        as_of_timestamp="2026-07-14T18:00:00-04:00", component_inputs=component_input_refs(tmp_path),
    )
    assert result["readiness_status"] == "PASS"
    assert result["exact_target_date_match"] is True


def test_10_missing_target_date_fails(tmp_path):
    _, config = make_binding(tmp_path, exact_date="2026-07-12")
    result = generate_readiness(
        "2026-07-13", config, generated_at="2026-08-21T00:00:00+00:00",
        component_inputs=component_input_refs(tmp_path),
    )
    assert "FAIL_CANONICAL_NOT_READY" in result["failure_reasons"]


def test_11_previous_date_fallback_forbidden(tmp_path):
    _, config = make_binding(tmp_path, exact_date="2026-07-12")
    result = generate_readiness(
        "2026-07-13", config, generated_at="2026-08-21T00:00:00+00:00",
        component_inputs=component_input_refs(tmp_path),
    )
    assert result["canonical_latest_date"] == "2026-07-12"
    assert result["canonical_readiness"]["available_dates"] == []


def test_12_readiness_generator_is_read_only(tmp_path):
    binding, config = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    paths = [Path(payload["readiness_sources"][name]["path"]) for name in payload["readiness_sources"]]
    before = [(sha256_file(path), path.stat().st_mtime_ns) for path in paths]
    result = generate_readiness(
        "2026-07-13", config, generated_at="2026-08-21T00:00:00+00:00",
        component_inputs=component_input_refs(tmp_path),
    )
    assert before == [(sha256_file(path), path.stat().st_mtime_ns) for path in paths]
    assert result["canonical_write_count"] == result["model_execute_count"] == 0


def test_13_production_root_must_be_external(tmp_path):
    binding, _ = make_binding(tmp_path)
    payload = json.loads(binding.read_text())
    payload["roots"]["unified_staging_root"] = str(REPO / "forbidden-production")
    write_json(binding, payload)
    assert "UNIFIED_STAGING_ROOT_NOT_APPROVED_EXTERNAL_RESULTS_PATH" in validation(binding)["reasons"]


def test_14_preflight_never_calls_execute(tmp_path, monkeypatch):
    _, config_path = make_binding(tmp_path)
    config = unified._load_config(config_path)
    component = ComponentIdentity("ALPHA", "x", "x", "x", "f", "p", "a" * 64, "2025-12-01", False, False, False)
    components = {role: replace(component, role=role, model_id=role) for role in ("ALPHA", "RISK", "EXECUTION")}
    readiness = CanonicalReadiness("2026-07-13", "2026-08-21", "m", "b" * 64, "u", ("2026-07-13",), ("2026-07-13",), ("2026-07-13",), ("2026-07-13",))
    identity = RunIdentity("2026-07-13", "b" * 64, "u", "c" * 64, components)

    class NoExecute:
        def validate_binding(self): return {"status": "PASS"}
        def validate_runtime(self): return {"status": "PASS"}
        def validate_target_date_inputs(self, record, target): return {"status": "PASS"}
        def build_execution_plan(self, target): return {"execution_capability": "BOUND_SAFE_EXACT_DATE_ENTRYPOINT"}
        def execute(self, identity): raise AssertionError("execute must never be called")

    monkeypatch.setattr(unified, "_production_adapters", lambda unused, readiness=None: {role: NoExecute() for role in components})
    status = unified._preflight_only(identity, readiness, config, production_bound=True, readiness_record={"readiness_status": "PASS", "target_date": "2026-07-13"})
    assert status["status"] == "PASS"
    assert status["production_execution_run"] is False


def test_15_broker_action_impossible(tmp_path):
    _, config_path = make_binding(tmp_path)
    payload = json.loads(config_path.read_text())
    payload["broker_action_allowed"] = True
    with pytest.raises(ValueError, match="unsafe runner capability"):
        RunnerConfig.from_dict(payload)


def test_16_training_search_selection_impossible(tmp_path):
    _, config_path = make_binding(tmp_path)
    base = json.loads(config_path.read_text())
    for name in ("training_allowed", "parameter_search_allowed", "model_selection_allowed"):
        payload = {**base, name: True}
        with pytest.raises(ValueError, match="unsafe runner capability"):
            RunnerConfig.from_dict(payload)


def test_17_readiness_hash_mismatch_fails_before_preflight(tmp_path):
    readiness = tmp_path / "readiness.json"
    write_json(readiness, {"target_date": "2026-08-21"})
    code = unified.main(["preflight", "--target-date", "2026-08-21", "--config", str(REAL_CONFIG), "--readiness-json", str(readiness), "--readiness-sha256", "0" * 64])
    assert code == 2


def test_18_binding_manifest_tamper_detected(tmp_path):
    binding, _ = make_binding(tmp_path)
    expected = sha256_file(binding)
    binding.write_text(binding.read_text() + " ", encoding="utf-8")
    assert "BINDING_MANIFEST_SHA256_MISMATCH" in validate_binding_manifest(binding, expected)["reasons"]


def test_19_unknown_adapter_fails(tmp_path):
    _, config_path = make_binding(tmp_path)
    config = unified._load_config(config_path)
    config = replace(config, production_adapters={**config.production_adapters, "ALPHA": "no_such_module:no_factory"})
    with pytest.raises(ImportError):
        unified._production_adapters(config)


def test_20_real_path_config_schema_loads():
    config = unified._load_config(REAL_CONFIG)
    assert config.require_frozen_hashes is True
    assert config.broker_action_allowed is False


def test_21_wrong_factory_role_rejected(tmp_path):
    _, config_path = make_binding(tmp_path)
    with pytest.raises(ProductionBindingError, match="ALPHA_FACTORY_ROLE_MISMATCH"):
        create_alpha_adapter(role="RISK", config=unified._load_config(config_path))
