"""Unified orchestration over frozen component adapters and transactional protocol."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .components import ShadowComponent
from .preflight import run_preflight
from .protocol import ProtocolError, ProtocolStore, atomic_json
from .reconcile import reconcile_components
from .schemas import CanonicalReadiness, ComponentResult, ROLES, RunIdentity, RunnerConfig


EXIT_CODES = {
    "SUCCESS": 0, "PREFLIGHT": 2, "GOVERNANCE": 3, "COMPONENT": 4,
    "RECONCILIATION": 5, "DUPLICATE": 6, "RECOVERY": 7, "COMMIT": 8,
}


class UnifiedShadowRunner:
    def __init__(self, config: RunnerConfig, store: ProtocolStore):
        self.config, self.store = config, store

    @staticmethod
    def _event(run_id: str, step: str, status: str, reason: str | None = None) -> dict[str, Any]:
        return {
            "run_id": run_id, "step": step,
            "timestamp": datetime.now(timezone.utc).isoformat(), "status": status, "reason": reason,
        }

    def run(
        self,
        identity: RunIdentity,
        readiness: CanonicalReadiness,
        adapters: Mapping[str, ShadowComponent],
        *,
        mode: str,
        commit: bool,
        resume: bool = False,
        overwrite: bool = False,
        crash_after_publish: bool = False,
    ) -> dict[str, Any]:
        events = [self._event(identity.run_id, "START", "PASS")]
        preflight = run_preflight(identity.target_date, readiness, identity.components, self.config, mode=mode)
        events.append(self._event(identity.run_id, "PREFLIGHT", preflight["status"], ",".join(preflight["reasons"])))
        if preflight["status"] != "PASS":
            return self._status(identity, preflight, events, "FAIL_PREFLIGHT", "NOT_COMMITTED", 0, exit_code=EXIT_CODES["PREFLIGHT"])

        duplicate = self.store.check_duplicate(identity)
        if duplicate["status"] == "ALREADY_COMMITTED_IDENTICAL":
            return self._status(
                identity, preflight, events, None, "ALREADY_COMMITTED_IDENTICAL", 0,
                exit_code=EXIT_CODES["SUCCESS"], duplicate_status=duplicate["status"],
                manifest_sha256=duplicate.get("manifest_sha256"),
            )
        if duplicate["status"] == "CONFLICT_EXISTING_COMMIT":
            return self._status(
                identity, preflight, events, "FAIL_DUPLICATE_CONFLICT", "NOT_COMMITTED", 0,
                exit_code=EXIT_CODES["DUPLICATE"], duplicate_status=duplicate["status"],
            )
        if resume:
            resume_status = self.store.assess_resume(identity)
            if resume_status["status"] != "RESUME_ALLOWED":
                return self._status(
                    identity, preflight, events,
                    "RECOVERY_REQUIRED" if resume_status["status"] != "RESUME_FORBIDDEN_INPUT_CHANGED" else "RESUME_FORBIDDEN_INPUT_CHANGED",
                    "NOT_COMMITTED", 0, exit_code=EXIT_CODES["RECOVERY"], recovery_status=resume_status["status"],
                )
        elif duplicate["status"] == "RECOVERY_REQUIRED":
            return self._status(
                identity, preflight, events, "RECOVERY_REQUIRED", "NOT_COMMITTED", 0,
                exit_code=EXIT_CODES["RECOVERY"], duplicate_status=duplicate["status"], recovery_status="RECOVERY_REQUIRED",
            )

        lock = self.store.acquire_lock(identity)
        if lock["status"] != "LOCK_ACQUIRED":
            return self._status(
                identity, preflight, events, "RECOVERY_REQUIRED", "NOT_COMMITTED", 0,
                exit_code=EXIT_CODES["RECOVERY"], lock_status=lock["status"],
            )
        created_at = datetime.now(timezone.utc).isoformat()
        stage = None
        try:
            try:
                stage = self.store.prepare_stage(identity, mode=mode, resume=resume)
            except ProtocolError as exc:
                return self._status(identity, preflight, events, str(exc), "NOT_COMMITTED", 0, exit_code=EXIT_CODES["RECOVERY"])
            results: dict[str, ComponentResult] = {}
            for role in ROLES:
                adapter = adapters.get(role)
                if adapter is None:
                    failure = self.store.fail_stage(stage, identity, f"FAIL_COMPONENT_{role}", "adapter missing")
                    return self._status(identity, preflight, events, failure["failure_code"], "NOT_COMMITTED", 0, exit_code=EXIT_CODES["COMPONENT"], staging_status="FAILED")
                try:
                    adapter.prepare(identity)
                    adapter.validate_inputs(identity)
                    result = adapter.execute(identity)
                    adapter.validate_output(result, identity)
                    results[role] = result
                    self.store.stage_component(stage, role, adapter.stage_payload(result))
                except Exception as exc:
                    failure = self.store.fail_stage(stage, identity, f"FAIL_COMPONENT_{role}", str(exc))
                    return self._status(identity, preflight, events, failure["failure_code"], "NOT_COMMITTED", 0, exit_code=EXIT_CODES["COMPONENT"], staging_status="FAILED")
                events.append(self._event(identity.run_id, f"COMPONENT_{role}", result.status, result.failure_reason))
                if result.status != "PASS":
                    failure = self.store.fail_stage(stage, identity, f"FAIL_COMPONENT_{role}", result.failure_reason or "component status failed")
                    return self._status(identity, preflight, events, failure["failure_code"], "NOT_COMMITTED", 0, exit_code=EXIT_CODES["COMPONENT"], staging_status="FAILED")

            reconciliation = reconcile_components(results, identity, self.config)
            reconciliation_path = stage / "reconciliation.json"
            atomic_json(reconciliation_path, reconciliation)
            events.append(self._event(identity.run_id, "RECONCILIATION", reconciliation["status"], ",".join(reconciliation["reasons"])))
            if reconciliation["status"] != "PASS":
                failure_code = self._reconciliation_failure(reconciliation)
                self.store.fail_stage(stage, identity, failure_code, ",".join(reconciliation["reasons"]))
                return self._status(
                    identity, preflight, events, failure_code, "NOT_COMMITTED", 0,
                    exit_code=EXIT_CODES["GOVERNANCE"] if reconciliation["governance_status"] == "FAIL" else EXIT_CODES["RECONCILIATION"],
                    reconciliation=reconciliation, staging_status="FAILED",
                )
            atomic_json(stage / "run_status.json", {
                "status": "VALIDATED", "run_id": identity.run_id, "target_date": identity.target_date,
                "failure_code": None, "failure_reason": None,
                "commit_status": "NOT_COMMITTED_DRY_RUN" if not commit else "PENDING_COMMIT",
                "manifest_sha256": None,
            })
            if not commit:
                return self._status(
                    identity, preflight, events, None, "NOT_COMMITTED_DRY_RUN", 0,
                    exit_code=EXIT_CODES["SUCCESS"], reconciliation=reconciliation,
                    staging_status="PASS",
                )
            try:
                committed = self.store.commit(
                    stage, identity, results, reconciliation_path, created_at=created_at,
                    overwrite=overwrite, crash_after_publish=crash_after_publish,
                )
            except (OSError, ProtocolError) as exc:
                if stage.exists():
                    self.store.fail_stage(stage, identity, "FAIL_COMMIT", str(exc))
                return self._status(identity, preflight, events, "FAIL_COMMIT", "COMMIT_NOT_COMPLETE", 0, exit_code=EXIT_CODES["COMMIT"], staging_status="FAILED")
            if committed["commit_status"] != "COMMITTED":
                return self._status(
                    identity, preflight, events, committed.get("status", "RECOVERY_REQUIRED"), committed["commit_status"], 0,
                    exit_code=EXIT_CODES["RECOVERY"], reconciliation=reconciliation, recovery_status="RECOVERY_REQUIRED",
                    staging_status="PUBLISHED_INCOMPLETE",
                )
            return self._status(
                identity, preflight, events, None, "COMMITTED", committed["new_rows_appended"],
                exit_code=EXIT_CODES["SUCCESS"], reconciliation=reconciliation,
                manifest_sha256=committed["manifest_sha256"], staging_status="PASS",
            )
        finally:
            self.store.release_lock(identity)

    @staticmethod
    def _reconciliation_failure(reconciliation: Mapping[str, Any]) -> str:
        if reconciliation["governance_status"] == "FAIL":
            return "FAIL_GOVERNANCE"
        if reconciliation["cross_shadow_date_status"] == "FAIL":
            return "FAIL_DATE_ALIGNMENT"
        if reconciliation["cross_component_lineage_status"] == "FAIL":
            return "FAIL_LINEAGE"
        if reconciliation["security_alignment_status"] == "FAIL":
            return "FAIL_SECURITY_ALIGNMENT"
        return "FAIL_COMPONENT_EXECUTION"

    def _status(
        self, identity: RunIdentity, preflight: Mapping[str, Any], events: list[dict[str, Any]],
        failure_code: str | None, commit_status: str, new_rows: int, *, exit_code: int,
        reconciliation: Mapping[str, Any] | None = None, duplicate_status: str = "CLEAR",
        recovery_status: str = "NOT_REQUIRED", lock_status: str = "RELEASED_OR_NOT_ACQUIRED",
        manifest_sha256: str | None = None, staging_status: str = "NOT_STAGED",
    ) -> dict[str, Any]:
        return {
            "status": "PASS" if exit_code == 0 else "FAIL",
            "runner": identity.runner_version, "run_id": identity.run_id, "target_date": identity.target_date,
            "preflight_status": preflight["status"], "failure_code": failure_code,
            "failure_reason": failure_code, "staging_status": staging_status,
            "reconciliation_status": reconciliation["status"] if reconciliation else "NOT_EVALUATED",
            "cross_shadow_date_status": reconciliation["cross_shadow_date_status"] if reconciliation else "NOT_EVALUATED",
            "cross_component_lineage_status": reconciliation["cross_component_lineage_status"] if reconciliation else "NOT_EVALUATED",
            "security_alignment_status": reconciliation["security_alignment_status"] if reconciliation else "NOT_EVALUATED",
            "governance_status": reconciliation["governance_status"] if reconciliation else ("PASS" if preflight["status"] == "PASS" else "NOT_EVALUATED"),
            "duplicate_status": duplicate_status, "append_only_status": "ENABLED_FAIL_CLOSED",
            "commit_status": commit_status, "new_rows_appended": new_rows,
            "recovery_status": recovery_status, "lock_status": lock_status,
            "manifest_sha256": manifest_sha256, "exit_code": exit_code, "events": events,
            "training_run": False, "parameter_search_run": False, "model_selection_run": False,
            "broker_action_run": False, "canonical_refresh_run": False,
            "production_execution_run": commit_status == "COMMITTED" and preflight.get("mode") == "production",
        }
