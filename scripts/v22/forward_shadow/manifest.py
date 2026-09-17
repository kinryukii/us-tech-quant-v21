"""Daily manifest construction and lightweight predecessor hash-chain validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .schemas import ComponentResult, RunIdentity, RUNNER_VERSION, canonical_sha256


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_daily_manifest(
    identity: RunIdentity,
    results: Mapping[str, ComponentResult],
    output_hashes: Mapping[str, str],
    reconciliation_sha256: str,
    previous_daily_manifest_sha256: str | None,
    *,
    created_at: str,
    committed_at: str | None = None,
) -> dict[str, Any]:
    alpha, risk, execution = (identity.components[role] for role in ("ALPHA", "RISK", "EXECUTION"))
    return {
        "schema_version": "1.0.0", "runner_version": RUNNER_VERSION,
        "run_id": identity.run_id, "shadow_key": identity.shadow_key,
        "target_date": identity.target_date, "created_at": created_at,
        "committed_at": committed_at or utc_now(),
        "canonical_manifest": "REFERENCE_ONLY_FROM_PREFLIGHT",
        "canonical_sha256": identity.canonical_manifest_sha256,
        "universe_id": identity.universe_id,
        "trading_calendar_id": identity.trading_calendar_id,
        "trading_calendar_sha256": identity.trading_calendar_sha256,
        "alpha_model_id": alpha.model_id, "alpha_freeze_id": alpha.freeze_id,
        "alpha_artifact_sha256": alpha.artifact_sha256,
        "risk_model_id": risk.model_id, "risk_freeze_id": risk.freeze_id,
        "risk_artifact_sha256": risk.artifact_sha256,
        "execution_model_id": execution.model_id, "execution_freeze_id": execution.freeze_id,
        "execution_config_sha256": execution.artifact_sha256,
        "alpha_output_sha256": output_hashes["ALPHA"],
        "risk_output_sha256": output_hashes["RISK"],
        "execution_output_sha256": output_hashes["EXECUTION"],
        "reconciliation_sha256": reconciliation_sha256,
        "previous_daily_manifest_sha256": previous_daily_manifest_sha256,
        "history_position": "GENESIS_MANIFEST" if previous_daily_manifest_sha256 is None else "CHAINED_MANIFEST",
        "status": "COMMITTED", "output_state": "AUTHORITATIVE_COMMITTED",
        "research_feedback_allowed": False, "model_selection_allowed": False,
        "training_allowed": False, "parameter_search_allowed": False,
        "threshold_search_allowed": False, "broker_action_allowed": False,
        "attribution_compatible_run_id": identity.run_id,
        "component_status": {role: result.status for role, result in sorted(results.items())},
    }


def validate_history_chain(manifest_paths: Iterable[Path]) -> dict[str, Any]:
    rows = []
    reasons: list[str] = []
    for path in manifest_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reasons.append(f"UNREADABLE_MANIFEST:{path}")
            continue
        rows.append((str(payload.get("target_date")), path, payload, file_sha256(path)))
    rows.sort(key=lambda item: (item[0], str(item[1])))
    dates = [item[0] for item in rows]
    if len(dates) != len(set(dates)):
        reasons.append("DUPLICATE_TARGET_DATE")
    previous_hash = None
    for index, (target_date, path, payload, observed_hash) in enumerate(rows):
        expected = payload.get("previous_daily_manifest_sha256")
        if index == 0:
            if expected is not None or payload.get("history_position") != "GENESIS_MANIFEST":
                reasons.append(f"INVALID_GENESIS:{target_date}")
        elif expected != previous_hash:
            reasons.append(f"PREDECESSOR_HASH_MISMATCH:{target_date}")
        if payload.get("status") != "COMMITTED":
            reasons.append(f"MANIFEST_NOT_COMMITTED:{target_date}")
        previous_hash = observed_hash
    return {
        "status": "PASS" if not reasons else "FAIL", "history_chain_status": "PASS" if not reasons else "FAIL",
        "manifest_count": len(rows), "latest_committed_date": dates[-1] if dates else None,
        "latest_manifest_sha256": rows[-1][3] if rows else None,
        "reasons": sorted(set(reasons)),
    }


def synthetic_chain_manifest(target_date: str, previous_hash: str | None, payload_tag: str) -> dict[str, Any]:
    """Tiny deterministic manifest used only by tests; no production identity claim."""
    return {
        "schema_version": "1.0.0", "runner_version": RUNNER_VERSION,
        "run_id": f"SYNTHETIC_{target_date}", "target_date": target_date,
        "previous_daily_manifest_sha256": previous_hash,
        "history_position": "GENESIS_MANIFEST" if previous_hash is None else "CHAINED_MANIFEST",
        "status": "COMMITTED", "payload_tag": payload_tag,
        "synthetic_payload_hash": canonical_sha256({"target_date": target_date, "tag": payload_tag}),
    }
