"""Read-only metadata view; canonical prospective recorders retain all ownership.

The frozen Raw status command reads mixed economic state. This thin adapter
opens its pinned governance contract only, and reuses RX's issued-authority
validator. It cannot record observations, execute policies, or reveal outcomes.
Run from the repository: python -B -m scripts.research.a2.portfolio_control.prospective_operating status
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.common.storage_paths import resolve


RAW_TASK = "A2_THREE_ARM_POSTFREEZE_FORWARD_R1"
RAW_CONTRACT_SHA256 = "4e3a76b00efc095856672b49f185c5aa89773257b4e97de18311ec31fac5abd2"
RAW_SOURCE_SHA256 = "5d90a9db3e363e3523ec0bdffedcf5d7f52d9a0049cddd21539e0c5d8a52f21a"
RX_SOURCE_ROOT = Path(r"D:\us-tech-quant-worktrees\rx-margin-r1-prospective-activation-r1")
RX_SOURCE_SHA256 = "e8edfc54e58ddc5d7c59acf173f3c7a8f59bc70c4897aa28c0099983db7136bf"
RX_REGISTRY_SOURCE_SHA256 = "d3014e59ad0ae877545cf160e780778b9335b69653387765629485afa3760158"
RX_CALENDAR_SHA256 = "7b9e8b4f8ef2391dd167f6fa321e0fc0e8b9bebb9fd1777013fa9ce8049dd9a6"
RX_METADATA_PINS = {
    "research_registry.json": "37efd55cc10a0db7ff013c02809e462097efc50df3a521e84c88807dbbd784b4",
    "storage_paths.json": "e0983df05980d31ca0b44ddc808a9bd7545b65608bc1a6fe686086518a4c9cce",
    "prospective_activation_profiles.json": "9c89b0bf57ac4de6ca27f27e45e6736cbcbc560097dd4f4377a86af5e48cd111",
    "prospective_activation_store.json": "d01c475e93e20e1f3017c149432be4db43ca24c93805f5eb1550594dc3290680",
}
RX_REGISTRATION_ID = "2323f9fb713243c773febbd2df9e05ec7d543495e8948d2aa9bdf19d82e29c31"
RX_ENTITY_ID = "RX_MARGIN_RANGE_EXHAUSTION_LINEAGE"
RAW_MILESTONES = {"20": "OPERATIONAL_ONLY", "60": "EARLY_ECONOMIC", "120": "FORMAL_FORWARD_REVIEW", "250": "ANNUAL_SCALE_REVIEW"}


def _pinned_bytes(path: Path, expected: str, maximum_bytes: int = 524_288) -> bytes:
    if path.stat().st_size > maximum_bytes:
        raise ValueError("METADATA_SIZE_INVALID")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("METADATA_IDENTITY_MISMATCH")
    return content


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("METADATA_SCHEMA_INVALID")
    return value


def _utc(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("METADATA_SCHEMA_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("METADATA_SCHEMA_INVALID")
    return parsed.astimezone(timezone.utc).isoformat()


def _failure(result: dict[str, Any], error: Exception) -> dict[str, Any]:
    # Never copy exception text, component diagnostics, or unknown fields.
    return {**result, "identity_status": "FAIL_CLOSED", "error_category": "METADATA_ACCESS_FAILED" if isinstance(error, OSError) else "METADATA_VALIDATION_FAILED"}


def raw_status(paths: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "policy_identity": "RAW_A2", "identity_status": "UNKNOWN",
        "activation_status": "FROZEN_CONTRACT_ONLY",
        "operational_status": "BLOCKED_NO_SAFE_OBSERVATION_RECEIPT",
        "current_observation_count": "UNKNOWN",
        "evidence_path_identity": "RAW_THREE_ARM_FORWARD_LEDGER",
        "economic_body_access": False, "automatic_reveal": False,
        "reveal_policy": "FROZEN_MILESTONES_NO_AUTOMATIC_REVEAL",
        "milestones": dict(RAW_MILESTONES),
    }
    try:
        root = paths.results_root / RAW_TASK
        content = _pinned_bytes(root / "forward_contract.json", RAW_CONTRACT_SHA256)
        _pinned_bytes(paths.repo_root / "scripts/v22/a2_three_arm_postfreeze_forward_r1.py", RAW_SOURCE_SHA256)
        contract = json.loads(content)
        identities = contract["frozen_identities"]
        if contract["milestones"] != RAW_MILESTONES:
            raise ValueError("METADATA_SCHEMA_INVALID")
        metadata = {
            "contract_file_sha256": RAW_CONTRACT_SHA256,
            "contract_identity": _sha(contract["forward_contract_hash"]),
            "model_identity": _sha(identities["raw_model_hash"]),
            "config_identity": _sha(identities["raw_portfolio_hash"]),
            "taxonomy_identity": _sha(identities["taxonomy_hash"]),
            "data_authority_identity": "UNKNOWN",
            "calendar_identity": _sha(identities["calendar_contract_sha256"]),
            "frozen_at_utc": _utc(contract["forward_freeze_timestamp_utc"]),
            "first_eligible_session": date.fromisoformat(contract["first_eligible_forward_session"]).isoformat(),
            "economic_record_exists": (root / "forward_ledger.csv").is_file(),
            "accounting_state_exists": (root / "forward_state.json").is_file(),
            "session_input_exists": (paths.daily_root / "current" / RAW_TASK / "session_input.json").is_file(),
        }
        return {**result, **metadata, "identity_status": "PASS_HASH_PINNED_FROZEN_CONTRACT"}
    except Exception as error:
        return _failure(result, error)


def _load_rx_lifecycle():
    source = RX_SOURCE_ROOT / "prospective_research_lifecycle.py"
    source_bytes = _pinned_bytes(source, RX_SOURCE_SHA256)
    _pinned_bytes(RX_SOURCE_ROOT / "research_registry.py", RX_REGISTRY_SOURCE_SHA256)
    for name, expected in RX_METADATA_PINS.items():
        _pinned_bytes(RX_SOURCE_ROOT / "config" / name, expected)
    spec = importlib.util.spec_from_file_location("ustq_issued_prospective_lifecycle", source)
    if spec is None or spec.loader is None:
        raise ValueError("METADATA_AUTHORITY_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    # Execute exactly the verified source; do not select cached bytecode.
    exec(compile(source_bytes, str(source), "exec"), module.__dict__)
    return module


def _rx_activation() -> dict[str, Any]:
    lifecycle = _load_rx_lifecycle()
    calendar_path = RX_SOURCE_ROOT / "config/qqq_canonical_trading_dates_2026q4_r1.json"
    _pinned_bytes(calendar_path, RX_CALENDAR_SHA256)
    return lifecycle.validate_prospective_activation(
        repo=RX_SOURCE_ROOT, registration_id=RX_REGISTRATION_ID,
        authoritative_session_calendar=lifecycle.load_small_json(calendar_path),
    )


def rx_status() -> dict[str, Any]:
    result: dict[str, Any] = {
        "policy_identity": "RX_1SIGMA", "identity_status": "UNKNOWN",
        "registration_id": RX_REGISTRATION_ID,
        "operational_status": "BLOCKED_RECORDER_BINDING_UNKNOWN",
        "recorder_binding": "UNKNOWN", "observation_path_identity": "UNKNOWN",
        "current_observation_count": "UNKNOWN",
        "economic_body_access": False, "automatic_reveal": False,
        "reveal_policy": "OWNER_APPROVAL_REQUIRED_BEFORE_ECONOMIC_REVEAL",
    }
    try:
        authority = _rx_activation()
        if (authority.get("status") != "PASS" or authority.get("authority_status") != "VALID_ISSUED_PROSPECTIVE_AUTHORITY"
                or authority.get("committed") is not True or authority.get("registration_id") != RX_REGISTRATION_ID
                or authority.get("entity_id") != RX_ENTITY_ID):
            raise ValueError("METADATA_AUTHORITY_INVALID")
        epoch = authority["first_legal_epoch"]
        metadata = {
            "activation_manifest_id": _sha(authority["manifest_id"]),
            "issuance_authority_sha256": _sha(authority["issuance_authority_sha256"]),
            "signal_information_eligible_utc": _utc(epoch["signal_information_eligible_utc"]),
            "decision_eligible_utc": _utc(epoch["decision_eligible_utc"]),
            "epoch_completion_utc": _utc(epoch["epoch_completion_utc"]),
        }
        return {**result, **metadata, "identity_status": "VALID_ISSUED_PROSPECTIVE_AUTHORITY"}
    except Exception as error:
        return _failure(result, error)


def operational_status() -> dict[str, Any]:
    try:
        raw = raw_status(resolve())
    except Exception as error:
        raw = _failure({"policy_identity": "RAW_A2", "current_observation_count": "UNKNOWN"}, error)
    return {
        "schema_version": 1, "status": "BLOCKED_PROSPECTIVE_PROGRAM_INCOMPLETE",
        "read_only": True, "economic_reveal_allowed": False,
        "raw_a2": raw, "rx_1sigma": rx_status(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status",))
    parser.parse_args(argv)
    print(json.dumps(operational_status(), sort_keys=True, indent=2, allow_nan=False))
    return 2  # Authority may pass while the complete operating program is blocked.


if __name__ == "__main__":
    raise SystemExit(main())
