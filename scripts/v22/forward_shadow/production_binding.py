"""Production identity binding and exact-date, staging-only adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .components import ShadowComponent, validate_component_output_contract
from .exact_date_components import (
    read_exact_date_input,
    run_alpha_single_date,
    run_execution_single_date,
    run_risk_single_date,
)
from .schemas import ComponentResult, RunIdentity, RunnerConfig, canonical_sha256, valid_sha256


EXPECTED = {
    "ALPHA": ("A2_HGB", "ALPHA_CHAMPION", "ALPHA"),
    "RISK": ("R6_BAD_ASYMMETRY", "RISK_CHAMPION", "RISK"),
    "EXECUTION": ("E5_COMBINED_CONSERVATIVE", "EXECUTION_CHAMPION", "EXECUTION"),
}


class ProductionBindingError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProductionBindingError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def component_composite_sha256(artifacts: list[Mapping[str, Any]]) -> str:
    identity = [
        {"artifact_id": row["artifact_id"], "path": Path(row["path"]).as_posix(), "sha256": row["sha256"]}
        for row in sorted(artifacts, key=lambda value: str(value["artifact_id"]))
    ]
    return canonical_sha256(identity)


def _registry_champion(path: Path, role: str) -> dict[str, Any]:
    registry = _read_json(path)
    model_id, registry_role, family = EXPECTED[role]
    matches = [row for row in registry.get("models", []) if row.get("role") == registry_role]
    if len(matches) != 1:
        raise ProductionBindingError(f"{role}_REGISTRY_CHAMPION_COUNT_INVALID")
    champion = matches[0]
    if champion.get("model_id") != model_id:
        raise ProductionBindingError(f"{role}_REGISTRY_CHAMPION_MISMATCH")
    if champion.get("model_family") != family:
        raise ProductionBindingError(f"{role}_REGISTRY_FAMILY_MISMATCH")
    return champion


def _inside(path: Path, root: Path) -> bool:
    resolved, parent = path.resolve(), root.resolve()
    return resolved == parent or parent in resolved.parents


def validate_binding_manifest(
    path: Path,
    expected_sha256: str,
    *,
    repo_root: Path = Path(r"D:\us-tech-quant"),
    results_root: Path = Path(r"D:\us-tech-quant-results"),
) -> dict[str, Any]:
    reasons: list[str] = []
    if not path.is_file():
        return {"status": "FAIL_CLOSED", "reasons": ["BINDING_MANIFEST_MISSING"]}
    observed_binding_sha = sha256_file(path)
    if observed_binding_sha != expected_sha256:
        reasons.append("BINDING_MANIFEST_SHA256_MISMATCH")
    payload = _read_json(path)
    if payload.get("binding_version") != "A2_FORWARD_SHADOW_PRODUCTION_BINDING_R1":
        reasons.append("BINDING_VERSION_INVALID")
    if payload.get("unified_runner_config_hash_definition") != (
        "CANONICAL_JSON_WITH_PRODUCTION_BINDING_SHA256_SET_TO_SELF_REFERENCE_EXCLUDED"
    ) or not valid_sha256(payload.get("unified_runner_config_contract_sha256")):
        reasons.append("UNIFIED_RUNNER_CONFIG_CONTRACT_IDENTITY_INVALID")
    if (
        payload.get("training_allowed") is not False
        or payload.get("parameter_search_allowed") is not False
        or payload.get("threshold_search_allowed") is not False
    ):
        reasons.append("TRAINING_OR_PARAMETER_SEARCH_NOT_FORBIDDEN")
    if payload.get("model_selection_allowed") is not False or payload.get("broker_action_allowed") is not False:
        reasons.append("MODEL_SELECTION_OR_BROKER_NOT_FORBIDDEN")

    roots = payload.get("roots", {})
    for name in ("unified_staging_root", "unified_authoritative_root", "readiness_root"):
        value = Path(str(roots.get(name, "")))
        if not value.is_absolute() or _inside(value, repo_root) or not _inside(value, results_root):
            reasons.append(f"{name.upper()}_NOT_APPROVED_EXTERNAL_RESULTS_PATH")
    if roots.get("unified_staging_root") == roots.get("unified_authoritative_root"):
        reasons.append("STAGING_AND_AUTHORITATIVE_ROOT_COLLISION")

    registry_paths = payload.get("registries", {})
    champions: dict[str, dict[str, Any]] = {}
    for role in EXPECTED:
        registry = registry_paths.get(role, {})
        registry_path = Path(str(registry.get("path", "")))
        try:
            if sha256_file(registry_path) != registry.get("sha256"):
                reasons.append(f"{role}_REGISTRY_SHA256_MISMATCH")
            champions[role] = _registry_champion(registry_path, role)
        except (OSError, ValueError, ProductionBindingError):
            reasons.append(f"{role}_REGISTRY_INVALID")

    component_reports: dict[str, Any] = {}
    components = payload.get("components", {})
    for role, expected in EXPECTED.items():
        model_id, registry_role, family = expected
        item = components.get(role, {})
        component_reasons: list[str] = []
        if item.get("model_id") != model_id or item.get("role") != registry_role or item.get("model_family") != family:
            component_reasons.append("COMPONENT_REGISTRY_IDENTITY_MISMATCH")
        champion = champions.get(role, {})
        if champion and (
            champion.get("model_id") != item.get("model_id")
            or champion.get("role") != item.get("role")
            or champion.get("benchmark_id") != item.get("freeze_id")
        ):
            component_reasons.append("COMPONENT_DOES_NOT_MATCH_REGISTRY_CHAMPION")
        artifacts = item.get("artifacts", [])
        for artifact in artifacts:
            artifact_path = Path(str(artifact.get("path", "")))
            if not artifact_path.is_file():
                component_reasons.append(f"ARTIFACT_MISSING:{artifact.get('artifact_id')}")
            elif sha256_file(artifact_path) != artifact.get("sha256"):
                component_reasons.append(f"ARTIFACT_SHA256_MISMATCH:{artifact.get('artifact_id')}")
        if artifacts and component_composite_sha256(artifacts) != item.get("composite_sha256"):
            component_reasons.append("COMPONENT_COMPOSITE_SHA256_MISMATCH")
        if item.get("uses_2026_training") is not False or item.get("uses_2026_model_selection") is not False:
            component_reasons.append("2026_GOVERNANCE_VIOLATION")
        if role in {"RISK", "EXECUTION"} and item.get("selection_source") != "PRE2026_ONLY":
            component_reasons.append("POST2026_SELECTION_ARTIFACT_FORBIDDEN")
        component_reports[role] = {
            "status": "PASS" if not component_reasons else "FAIL_CLOSED",
            "reasons": component_reasons,
            "model_id": item.get("model_id"),
            "freeze_id": item.get("freeze_id"),
            "composite_sha256": item.get("composite_sha256"),
            "execute_binding_status": item.get("execute_binding_status", "UNKNOWN"),
        }
        reasons.extend(f"{role}:{reason}" for reason in component_reasons)
    return {
        "status": "PASS" if not reasons else "FAIL_CLOSED",
        "reasons": sorted(set(reasons)),
        "binding_manifest_sha256": observed_binding_sha,
        "components": component_reports,
        "roots": roots,
    }


class ExistingFrozenProductionAdapter(ShadowComponent):
    """Thin identity/plan adapter. No strategy mathematics is duplicated."""

    def __init__(
        self,
        role: str,
        config: RunnerConfig,
        *,
        readiness: Mapping[str, Any] | None = None,
        shared_context: dict[str, ComponentResult] | None = None,
    ):
        self.role = role
        self.config = config
        self.binding_path = Path(config.production_binding_manifest)
        self.binding = _read_json(self.binding_path)
        self.component = self.binding["components"][role]
        self.readiness = dict(readiness or {})
        self.shared_context = shared_context if shared_context is not None else {}

    @property
    def component_id(self) -> str:
        return str(self.component["model_id"])

    @property
    def component_role(self) -> str:
        return self.role

    @property
    def freeze_id(self) -> str:
        return str(self.component["freeze_id"])

    @property
    def artifact_identity(self) -> Mapping[str, Any]:
        return {"artifacts": self.component["artifacts"], "composite_sha256": self.component["composite_sha256"]}

    def validate_binding(self) -> dict[str, Any]:
        report = validate_binding_manifest(self.binding_path, self.config.production_binding_sha256)
        component = report.get("components", {}).get(self.role, {})
        return {"status": component.get("status", "FAIL_CLOSED"), "binding_status": report["status"], **component}

    def validate_runtime(self) -> dict[str, Any]:
        reasons = []
        python = Path(str(self.binding["runtime"]["canonical_python"]))
        if not python.is_file():
            reasons.append("CANONICAL_PYTHON_MISSING")
        for entrypoint in self.component.get("entrypoints", []):
            path = Path(str(entrypoint["path"]))
            if not path.is_file():
                reasons.append(f"ENTRYPOINT_MISSING:{entrypoint['entrypoint_id']}")
            elif sha256_file(path) != entrypoint["sha256"]:
                reasons.append(f"ENTRYPOINT_SHA256_MISMATCH:{entrypoint['entrypoint_id']}")
        return {"status": "PASS" if not reasons else "FAIL_CLOSED", "reasons": reasons}

    def validate_target_date_inputs(self, readiness: Mapping[str, Any], target_date: str) -> dict[str, Any]:
        reasons = []
        if readiness.get("readiness_status") != "PASS":
            reasons.append("READINESS_NOT_PASS")
        if readiness.get("target_date") != target_date:
            reasons.append("READINESS_TARGET_DATE_MISMATCH")
        reference = readiness.get("component_inputs", {}).get(self.role)
        if not isinstance(reference, Mapping):
            reasons.append(f"{self.role}_EXACT_DATE_INPUT_REFERENCE_MISSING")
        else:
            try:
                read_exact_date_input(reference, target_date)
            except (OSError, ValueError, ProductionBindingError, RuntimeError):
                reasons.append(f"{self.role}_EXACT_DATE_INPUT_INVALID")
        return {
            "status": "PASS" if not reasons else "FAIL_CLOSED",
            "target_date": readiness.get("target_date"),
            "reasons": reasons,
        }

    def build_execution_plan(self, target_date: str) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_role": self.component_role,
            "freeze_id": self.freeze_id,
            "target_date": target_date,
            "entrypoints": self.component.get("entrypoints", []),
            "execution_capability": self.component.get("execute_binding_status"),
            "production_execution_planned": False,
            "broker_action_allowed": False,
            "output_scope": "UNIFIED_TRANSACTION_STAGING_ONLY",
            "authoritative_append_allowed": False,
        }

    def prepare(self, identity: RunIdentity) -> None:
        if self.validate_binding()["status"] != "PASS":
            raise ProductionBindingError(f"{self.role}_BINDING_INVALID")

    def validate_inputs(self, identity: RunIdentity) -> None:
        if self.validate_runtime()["status"] != "PASS":
            raise ProductionBindingError(f"{self.role}_RUNTIME_INVALID")
        if self.validate_target_date_inputs(self.readiness, identity.target_date)["status"] != "PASS":
            raise ProductionBindingError(f"{self.role}_EXACT_DATE_INPUT_INVALID")

    def execute(self, identity: RunIdentity) -> ComponentResult:
        reference = self.readiness["component_inputs"][self.role]
        payload = read_exact_date_input(reference, identity.target_date)
        if self.role == "ALPHA":
            records = run_alpha_single_date(identity.target_date, payload, self.component)
        elif self.role == "RISK":
            alpha = self.shared_context.get("ALPHA")
            if alpha is None:
                raise ProductionBindingError("RISK_ALPHA_RESULT_UNAVAILABLE")
            records = run_risk_single_date(
                identity.target_date, payload, self.component, alpha.records, identity.run_id,
            )
        else:
            alpha, risk = self.shared_context.get("ALPHA"), self.shared_context.get("RISK")
            if alpha is None or risk is None:
                raise ProductionBindingError("EXECUTION_UPSTREAM_RESULT_UNAVAILABLE")
            records = run_execution_single_date(
                identity.target_date, payload, self.component, alpha.records, identity.run_id,
            )
        result = ComponentResult(
            role=self.role, status="PASS", target_date=identity.target_date,
            run_id=identity.run_id, model_id=self.component_id, records=records,
            input_alpha_run_id=identity.run_id if self.role in {"RISK", "EXECUTION"} else None,
            input_risk_run_id=identity.run_id if self.role == "EXECUTION" else None,
            fit_called=False, training_rows_2026=0, parameter_search_run=False,
            threshold_search_run=False, model_selection_run=False, broker_action=False,
        )
        self.shared_context[self.role] = result
        return result

    def validate_output(self, result: ComponentResult, identity: RunIdentity) -> None:
        validate_component_output_contract(result, identity)


def create_alpha_adapter(
    *, role: str, config: RunnerConfig, readiness: Mapping[str, Any] | None = None,
    shared_context: dict[str, ComponentResult] | None = None,
) -> ExistingFrozenProductionAdapter:
    if role != "ALPHA":
        raise ProductionBindingError("ALPHA_FACTORY_ROLE_MISMATCH")
    return ExistingFrozenProductionAdapter(role, config, readiness=readiness, shared_context=shared_context)


def create_risk_adapter(
    *, role: str, config: RunnerConfig, readiness: Mapping[str, Any] | None = None,
    shared_context: dict[str, ComponentResult] | None = None,
) -> ExistingFrozenProductionAdapter:
    if role != "RISK":
        raise ProductionBindingError("RISK_FACTORY_ROLE_MISMATCH")
    return ExistingFrozenProductionAdapter(role, config, readiness=readiness, shared_context=shared_context)


def create_execution_adapter(
    *, role: str, config: RunnerConfig, readiness: Mapping[str, Any] | None = None,
    shared_context: dict[str, ComponentResult] | None = None,
) -> ExistingFrozenProductionAdapter:
    if role != "EXECUTION":
        raise ProductionBindingError("EXECUTION_FACTORY_ROLE_MISMATCH")
    return ExistingFrozenProductionAdapter(role, config, readiness=readiness, shared_context=shared_context)
