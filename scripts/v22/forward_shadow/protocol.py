"""Append-only staging, lock, duplicate, commit, recovery, and status protocol."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .manifest import build_daily_manifest, file_sha256, utc_now, validate_history_chain
from .schemas import ComponentResult, RunIdentity, canonical_json


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class ProtocolError(RuntimeError):
    pass


class ProtocolStore:
    def __init__(self, staging_root: Path, authoritative_root: Path):
        self.staging_root = staging_root.resolve()
        self.authoritative_root = authoritative_root.resolve()
        if os.path.splitdrive(str(self.staging_root))[0].lower() != os.path.splitdrive(str(self.authoritative_root))[0].lower():
            raise ProtocolError("staging and authoritative roots must be on the same volume")
        self.transactions_root = self.authoritative_root / "transactions"
        self.locks_root = self.authoritative_root / "locks"

    def stage_path(self, run_id: str) -> Path:
        return self.staging_root / run_id

    def transaction_path(self, run_id: str) -> Path:
        return self.transactions_root / run_id

    def _lock_path(self, target_date: str) -> Path:
        return self.locks_root / f"{target_date}.lock"

    def acquire_lock(self, identity: RunIdentity) -> dict[str, Any]:
        path = self._lock_path(identity.target_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "target_date": identity.target_date, "run_id": identity.run_id,
            "pid": os.getpid(), "created_at": utc_now(), "owner_status": "ACTIVE",
        }
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"status": "STALE_LOCK_REVIEW_REQUIRED", "path": str(path), "owner": None}
            status = "ACTIVE_LOCK_DENIED" if existing.get("pid") == os.getpid() and existing.get("owner_status") == "ACTIVE" else "STALE_LOCK_REVIEW_REQUIRED"
            return {"status": status, "path": str(path), "owner": existing}
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"status": "LOCK_ACQUIRED", "path": str(path), "owner": payload}

    def release_lock(self, identity: RunIdentity) -> bool:
        path = self._lock_path(identity.target_date)
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if payload.get("run_id") != identity.run_id or payload.get("pid") != os.getpid():
            return False
        path.unlink()
        return True

    def committed_transactions(self) -> list[tuple[Path, dict[str, Any], str]]:
        if not self.transactions_root.is_dir():
            return []
        rows = []
        for transaction in sorted(self.transactions_root.iterdir()):
            manifest, marker = transaction / "daily_manifest.json", transaction / "COMMIT.json"
            if not manifest.is_file() or not marker.is_file():
                continue
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                mark = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            observed = file_sha256(manifest)
            if mark.get("manifest_sha256") == observed and mark.get("status") == "COMMITTED":
                rows.append((transaction, payload, observed))
        return rows

    def partial_transactions(self) -> list[Path]:
        if not self.transactions_root.is_dir():
            return []
        valid_paths = {path.resolve() for path, _, _ in self.committed_transactions()}
        return [path for path in sorted(self.transactions_root.iterdir()) if path.is_dir() and path.resolve() not in valid_paths]

    def check_duplicate(self, identity: RunIdentity) -> dict[str, Any]:
        for _, manifest, manifest_hash in self.committed_transactions():
            if manifest.get("target_date") != identity.target_date:
                continue
            if manifest.get("shadow_key") == identity.shadow_key:
                return {
                    "status": "ALREADY_COMMITTED_IDENTICAL", "new_rows_appended": 0,
                    "manifest_sha256": manifest_hash,
                }
            return {"status": "CONFLICT_EXISTING_COMMIT", "new_rows_appended": 0, "manifest_sha256": manifest_hash}
        for path in self.partial_transactions():
            identity_path = path / "run_identity.json"
            if identity_path.is_file() and json.loads(identity_path.read_text(encoding="utf-8")).get("target_date") == identity.target_date:
                return {"status": "RECOVERY_REQUIRED", "new_rows_appended": 0, "path": str(path)}
        if self.staging_root.is_dir():
            for path in self.staging_root.iterdir():
                identity_path = path / "run_identity.json"
                if path.is_dir() and identity_path.is_file():
                    staged = json.loads(identity_path.read_text(encoding="utf-8"))
                    if staged.get("target_date") == identity.target_date:
                        return {"status": "RECOVERY_REQUIRED", "new_rows_appended": 0, "path": str(path)}
        return {"status": "CLEAR", "new_rows_appended": 0}

    def prepare_stage(self, identity: RunIdentity, *, mode: str, resume: bool = False) -> Path:
        stage = self.stage_path(identity.run_id)
        if stage.exists() and not resume:
            raise ProtocolError("RECOVERY_REQUIRED")
        stage.mkdir(parents=True, exist_ok=True)
        identity_path = stage / "run_identity.json"
        if identity_path.is_file():
            observed = json.loads(identity_path.read_text(encoding="utf-8"))
            if canonical_json(observed) != canonical_json(identity.to_dict()):
                raise ProtocolError("RESUME_FORBIDDEN_INPUT_CHANGED")
        else:
            atomic_json(identity_path, identity.to_dict())
        atomic_json(stage / "state.json", {
            "run_id": identity.run_id, "target_date": identity.target_date,
            "state": "PREPARED", "mode": mode, "updated_at": utc_now(),
            "output_state": "STAGING",
        })
        return stage

    def stage_component(self, stage: Path, role: str, payload: Mapping[str, Any]) -> Path:
        path = stage / f"{role.lower()}_stage.json"
        atomic_json(path, dict(payload))
        return path

    def fail_stage(self, stage: Path, identity: RunIdentity, failure_code: str, reason: str) -> dict[str, Any]:
        payload = {
            "status": "FAILED", "state": "FAILED_PRE_COMMIT", "output_state": "FAILED",
            "run_id": identity.run_id, "target_date": identity.target_date,
            "failure_code": failure_code, "failure_reason": reason, "failed_at": utc_now(),
            "authoritative_append_count": 0,
        }
        atomic_json(stage / "failure_manifest.json", payload)
        atomic_json(stage / "state.json", payload)
        return payload

    def assess_resume(self, identity: RunIdentity) -> dict[str, Any]:
        exact = self.stage_path(identity.run_id)
        candidates = [exact] if exact.is_dir() else []
        if not candidates and self.staging_root.is_dir():
            candidates = [path for path in self.staging_root.iterdir() if path.is_dir() and (path / "run_identity.json").is_file()]
            candidates = [path for path in candidates if json.loads((path / "run_identity.json").read_text(encoding="utf-8")).get("target_date") == identity.target_date]
        if not candidates:
            return {"status": "NO_RESUMABLE_STAGE"}
        staged = json.loads((candidates[0] / "run_identity.json").read_text(encoding="utf-8"))
        if canonical_json(staged) != canonical_json(identity.to_dict()):
            return {"status": "RESUME_FORBIDDEN_INPUT_CHANGED", "path": str(candidates[0])}
        if not (candidates[0] / "failure_manifest.json").is_file():
            return {"status": "RECOVERY_REQUIRED", "path": str(candidates[0])}
        return {"status": "RESUME_ALLOWED", "path": str(candidates[0])}

    def _previous_manifest_hash(self) -> str | None:
        committed = self.committed_transactions()
        if not committed:
            return None
        committed.sort(key=lambda item: (str(item[1].get("target_date")), str(item[0])))
        return committed[-1][2]

    def commit(
        self,
        stage: Path,
        identity: RunIdentity,
        results: Mapping[str, ComponentResult],
        reconciliation_path: Path,
        *,
        created_at: str,
        overwrite: bool = False,
        crash_after_publish: bool = False,
    ) -> dict[str, Any]:
        if overwrite:
            raise ProtocolError("FAIL_CLOSED_OVERWRITE_FORBIDDEN")
        duplicate = self.check_duplicate(identity)
        if duplicate["status"] != "RECOVERY_REQUIRED" and duplicate["status"] != "CLEAR":
            return {**duplicate, "commit_status": "NOT_COMMITTED"}
        if duplicate["status"] == "RECOVERY_REQUIRED" and Path(duplicate.get("path", "")).resolve() != stage.resolve():
            return {**duplicate, "commit_status": "NOT_COMMITTED"}
        output_paths = {role: stage / f"{role.lower()}_stage.json" for role in ("ALPHA", "RISK", "EXECUTION")}
        required = [*output_paths.values(), reconciliation_path, stage / "run_identity.json"]
        if any(not path.is_file() for path in required):
            raise ProtocolError("FAIL_COMMIT_REQUIRED_STAGE_FILE_MISSING")
        output_hashes = {role: file_sha256(path) for role, path in output_paths.items()}
        reconciliation_hash = file_sha256(reconciliation_path)
        manifest = build_daily_manifest(
            identity, results, output_hashes, reconciliation_hash, self._previous_manifest_hash(),
            created_at=created_at, committed_at=utc_now(),
        )
        atomic_json(stage / "daily_manifest.json", manifest)
        atomic_json(stage / "state.json", {
            "run_id": identity.run_id, "target_date": identity.target_date,
            "state": "COMMITTING", "output_state": "STAGING", "updated_at": utc_now(),
        })
        transaction = self.transaction_path(identity.run_id)
        transaction.parent.mkdir(parents=True, exist_ok=True)
        if transaction.exists():
            return {"commit_status": "RECOVERY_REQUIRED", "status": "RECOVERY_REQUIRED", "new_rows_appended": 0}
        os.replace(stage, transaction)
        if crash_after_publish:
            return {"commit_status": "COMMIT_NOT_COMPLETE", "status": "RECOVERY_REQUIRED", "new_rows_appended": 0}
        final_manifest = transaction / "daily_manifest.json"
        manifest_hash = file_sha256(final_manifest)
        for role, expected in output_hashes.items():
            if file_sha256(transaction / f"{role.lower()}_stage.json") != expected:
                return {"commit_status": "COMMIT_NOT_COMPLETE", "status": "RECOVERY_REQUIRED", "new_rows_appended": 0}
        marker = {
            "schema_version": "1.0.0", "status": "COMMITTED", "output_state": "AUTHORITATIVE_COMMITTED",
            "run_id": identity.run_id, "target_date": identity.target_date,
            "manifest_sha256": manifest_hash, "committed_at": manifest["committed_at"],
        }
        atomic_json(transaction / "run_status.json", {
            "status": "COMMITTED", "run_id": identity.run_id, "target_date": identity.target_date,
            "failure_code": None, "failure_reason": None, "commit_status": "COMMITTED",
            "manifest_sha256": manifest_hash, "new_rows_appended": sum(len(result.records) for result in results.values()),
        })
        atomic_json(transaction / "COMMIT.json", marker)
        return {
            "status": "COMMITTED", "commit_status": "COMMITTED", "new_rows_appended": sum(len(result.records) for result in results.values()),
            "manifest_sha256": manifest_hash, "manifest_path": str(final_manifest), "transaction_path": str(transaction),
        }

    def resolve_authoritative(self, target_date: str) -> dict[str, Any] | None:
        matches = [item for item in self.committed_transactions() if item[1].get("target_date") == target_date]
        if len(matches) != 1:
            return None
        transaction, manifest, observed_hash = matches[0]
        return {"transaction_path": str(transaction), "manifest": manifest, "manifest_sha256": observed_hash}

    def history_status(self) -> dict[str, Any]:
        committed = self.committed_transactions()
        chain = validate_history_chain([transaction / "daily_manifest.json" for transaction, _, _ in committed])
        pending = [str(path) for path in self.partial_transactions()]
        failed = []
        if self.staging_root.is_dir():
            failed = [str(path) for path in self.staging_root.iterdir() if (path / "failure_manifest.json").is_file()]
        if pending:
            chain = {
                **chain, "status": "FAIL", "history_chain_status": "FAIL",
                "reasons": sorted(set(chain["reasons"] + ["INCOMPLETE_OR_INVALID_TRANSACTION"])),
            }
        return {
            **chain, "pending_staging_runs": pending,
            "failed_runs": failed, "read_only": True,
        }
