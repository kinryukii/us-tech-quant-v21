"""Component adapter protocol; no model implementation lives here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .schemas import ComponentIdentity, ComponentResult, RunIdentity


class ShadowComponent(ABC):
    role: str

    @abstractmethod
    def prepare(self, identity: RunIdentity) -> None: ...

    @abstractmethod
    def validate_inputs(self, identity: RunIdentity) -> None: ...

    @abstractmethod
    def execute(self, identity: RunIdentity) -> ComponentResult: ...

    @abstractmethod
    def validate_output(self, result: ComponentResult, identity: RunIdentity) -> None: ...

    def stage_payload(self, result: ComponentResult) -> dict[str, Any]:
        return result.to_dict()


OUTPUT_REQUIRED_FIELDS = {
    "ALPHA": {"target_date", "security_id", "ticker", "rank", "score", "raw_target_weight", "model_id", "universe_id", "vintage_id"},
    "RISK": {"target_date", "security_id", "risk_model_id"},
    "EXECUTION": {"target_date", "security_id", "pre_execution_weight", "post_execution_weight", "execution_action", "execution_overlay_id"},
}


def validate_component_output_contract(result: ComponentResult, identity: RunIdentity) -> None:
    required = OUTPUT_REQUIRED_FIELDS[result.role]
    for index, row in enumerate(result.records):
        missing = required - set(row)
        if missing:
            raise ValueError(f"{result.role} output row {index} missing fields: {sorted(missing)}")
        if str(row.get("target_date")) != result.target_date:
            raise ValueError(f"{result.role} row target_date mismatch")
        identity_field = {"ALPHA": "model_id", "RISK": "risk_model_id", "EXECUTION": "execution_overlay_id"}[result.role]
        if str(row.get(identity_field)) != identity.components[result.role].model_id:
            raise ValueError(f"{result.role} row model identity mismatch")
    if result.target_date != identity.target_date and result.status == "PASS":
        # Cross reconciliation reports the mismatch; this validator preserves the component output for audit.
        return


class SyntheticComponent(ShadowComponent):
    def __init__(self, role: str, payload: Mapping[str, Any]):
        self.role = role
        self.payload = dict(payload)

    def prepare(self, identity: RunIdentity) -> None:
        if self.role not in identity.components:
            raise ValueError(f"component role absent from run identity: {self.role}")

    def validate_inputs(self, identity: RunIdentity) -> None:
        if self.payload.get("prepare_fail"):
            raise ValueError(str(self.payload.get("failure_reason") or "synthetic prepare failure"))

    def execute(self, identity: RunIdentity) -> ComponentResult:
        component: ComponentIdentity = identity.components[self.role]
        values = {
            "role": self.role, "status": self.payload.get("status", "PASS"),
            "target_date": self.payload.get("target_date", identity.target_date),
            "run_id": self.payload.get("run_id", identity.run_id), "model_id": component.model_id,
            "records": tuple(self.payload.get("records", ())),
            "input_alpha_run_id": self.payload.get("input_alpha_run_id"),
            "input_risk_run_id": self.payload.get("input_risk_run_id"),
            "fit_called": bool(self.payload.get("fit_called", False)),
            "training_rows_2026": int(self.payload.get("training_rows_2026", 0)),
            "parameter_search_run": bool(self.payload.get("parameter_search_run", False)),
            "threshold_search_run": bool(self.payload.get("threshold_search_run", False)),
            "model_selection_run": bool(self.payload.get("model_selection_run", False)),
            "broker_action": bool(self.payload.get("broker_action", False)),
            "security_alignment_reason": self.payload.get("security_alignment_reason"),
            "failure_reason": self.payload.get("failure_reason"),
        }
        if self.role == "RISK" and values["input_alpha_run_id"] is None:
            values["input_alpha_run_id"] = identity.run_id
        if self.role == "EXECUTION":
            values["input_alpha_run_id"] = values["input_alpha_run_id"] or identity.run_id
            values["input_risk_run_id"] = values["input_risk_run_id"] or identity.run_id
        return ComponentResult(**values)

    def validate_output(self, result: ComponentResult, identity: RunIdentity) -> None:
        if result.role != self.role or result.model_id != identity.components[self.role].model_id:
            raise ValueError("synthetic component identity mismatch")
        validate_component_output_contract(result, identity)


class UnboundProductionComponent(ShadowComponent):
    def __init__(self, role: str):
        self.role = role

    def prepare(self, identity: RunIdentity) -> None:
        raise RuntimeError(f"{self.role} production adapter is REQUIRED_AT_PRODUCTION")

    def validate_inputs(self, identity: RunIdentity) -> None:  # pragma: no cover
        raise RuntimeError("unreachable unbound adapter")

    def execute(self, identity: RunIdentity) -> ComponentResult:  # pragma: no cover
        raise RuntimeError("unreachable unbound adapter")

    def validate_output(self, result: ComponentResult, identity: RunIdentity) -> None:  # pragma: no cover
        raise RuntimeError("unreachable unbound adapter")
