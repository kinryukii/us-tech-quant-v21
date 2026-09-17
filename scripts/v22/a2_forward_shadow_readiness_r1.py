#!/usr/bin/env python3
"""Read-only exact-date readiness generator for unified A2 forward shadow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from forward_shadow.production_binding import sha256_file, validate_binding_manifest
from forward_shadow.trading_calendar import ForwardShadowTradingCalendarProvider, TradingCalendarError


DEFAULT_CONFIG = REPO_ROOT / "config" / "research_governance" / "a2_forward_shadow_unified_r1.json"
APPROVED_RESULTS_ROOT = Path(r"D:\us-tech-quant-results")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def _under(path: Path, root: Path) -> bool:
    resolved, parent = path.resolve(), root.resolve()
    return resolved == parent or parent in resolved.parents


def generate_readiness(
    target_date: str,
    config_path: Path = DEFAULT_CONFIG,
    *,
    generated_at: str | None = None,
    as_of_timestamp: str | None = None,
    timezone_name: str = "Asia/Tokyo",
    component_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = date.fromisoformat(target_date)
    config = read_json(config_path)
    binding_path = Path(config["production_binding_manifest"])
    binding = read_json(binding_path)
    binding_report = validate_binding_manifest(binding_path, config["production_binding_sha256"])
    reasons = list(binding_report["reasons"])

    pointer_path = Path(binding["readiness_sources"]["canonical_pointer"]["path"])
    pointer = read_json(pointer_path)
    canonical_manifest_path = Path(pointer.get("canonical_manifest_path", ""))
    canonical_manifest = read_json(canonical_manifest_path) if canonical_manifest_path.is_file() else {}
    pointer_latest = str(pointer.get("canonical_complete_universe_date", "UNKNOWN"))
    manifest_latest = str(canonical_manifest.get("latest_date", "UNKNOWN"))
    canonical_exact = pointer_latest == target_date and manifest_latest == target_date
    if not canonical_exact:
        reasons.append("FAIL_CANONICAL_NOT_READY")
    if pointer.get("source_policy") != "MOOMOO_ONLY" or pointer.get("external_fallback_used") is not False:
        reasons.append("CANONICAL_SOURCE_POLICY_INVALID")
    canonical_hash = sha256_file(canonical_manifest_path) if canonical_manifest_path.is_file() else "UNKNOWN"

    calendar_ref = binding["readiness_sources"]["trading_calendar"]
    calendar_path = Path(calendar_ref["path"])
    trading_status, eligible = "UNKNOWN", False
    calendar_latest, calendar_id, calendar_sha = "UNKNOWN", "UNKNOWN", "UNKNOWN"
    as_of = as_of_timestamp or datetime.now(timezone.utc).isoformat()
    completion: dict[str, Any] = {
        "latest_completed_us_session": None, "target_session_completed": False,
        "as_of_timestamp": as_of, "as_of_timezone": timezone_name,
    }
    try:
        if not calendar_path.is_file() or sha256_file(calendar_path) != calendar_ref["sha256"]:
            raise TradingCalendarError("TRADING_CALENDAR_CONTRACT_SHA256_MISMATCH")
        provider = ForwardShadowTradingCalendarProvider(calendar_path)
        calendar_latest, calendar_id, calendar_sha = str(provider.end), provider.calendar_id, provider.calendar_sha256
        eligible = provider.is_session(target_date)
        trading_status = "PASS" if eligible else "NOT_TRADING_DAY"
        completion = provider.completed_session_metadata(target_date, as_of, timezone_name)
        canonical_lag = provider.lag_sessions(pointer_latest, completion["latest_completed_us_session"])
    except (OSError, ValueError, TradingCalendarError) as exc:
        trading_status = f"FAIL_CALENDAR_BINDING:{exc}"
        canonical_lag = None
    if trading_status != "PASS":
        reasons.append(f"TRADING_DATE_{trading_status}")

    universe_ref = binding["readiness_sources"]["universe_manifest"]
    members_ref = binding["readiness_sources"]["universe_members"]
    universe_path, members_path = Path(universe_ref["path"]), Path(members_ref["path"])
    universe_hash_ok = universe_path.is_file() and sha256_file(universe_path) == universe_ref["sha256"]
    members_hash_ok = members_path.is_file() and sha256_file(members_path) == members_ref["sha256"]
    universe_id, active_quarter = "UNKNOWN", "UNKNOWN"
    universe_ready = False
    if universe_hash_ok and members_hash_ok:
        schedule = pd.read_parquet(universe_path)
        schedule["effective_date"] = pd.to_datetime(schedule["effective_date"], errors="coerce")
        active = schedule.loc[schedule["effective_date"].dt.date <= target].sort_values("effective_date")
        if not active.empty:
            row = active.iloc[-1]
            universe_id = str(row["universe_fingerprint"])
            active_quarter = str(row["quarter"])
            universe_ready = str(row.get("institution_count")) == "24"
    if not universe_ready:
        reasons.append("UNIVERSE_SNAPSHOT_NOT_READY")

    alpha_pre_final = next(
        Path(row["path"]) for row in binding["components"]["ALPHA"]["artifacts"]
        if row["artifact_id"] == "pre_final_freeze"
    )
    alpha_contract = read_json(alpha_pre_final)
    feature_schema_id = str(alpha_contract.get("contracts", {}).get("A2_CONFIG_FINGERPRINT", "UNKNOWN"))
    input_refs = dict(component_inputs or {})
    input_reasons = []
    for role in ("ALPHA", "RISK", "EXECUTION"):
        reference = input_refs.get(role)
        if not isinstance(reference, dict):
            input_reasons.append(f"{role}_EXACT_DATE_INPUT_REFERENCE_MISSING")
            continue
        path = Path(str(reference.get("path", "")))
        if not path.is_file() or sha256_file(path) != reference.get("sha256"):
            input_reasons.append(f"{role}_EXACT_DATE_INPUT_SHA256_MISMATCH")
            continue
        try:
            if read_json(path).get("target_date") != target_date:
                input_reasons.append(f"{role}_EXACT_DATE_INPUT_TARGET_MISMATCH")
        except (OSError, ValueError):
            input_reasons.append(f"{role}_EXACT_DATE_INPUT_INVALID")
    reasons.extend(input_reasons)
    features_ready = canonical_exact and universe_ready and feature_schema_id != "UNKNOWN" and not input_reasons
    if not features_ready:
        reasons.append("FEATURE_INPUT_NOT_READY")

    component_ready = {
        role: binding_report.get("components", {}).get(role, {}).get("status") == "PASS"
        for role in ("ALPHA", "RISK", "EXECUTION")
    }
    if not all(component_ready.values()):
        reasons.append("COMPONENT_BINDING_NOT_READY")
    execute_ready = all(
        binding["components"][role].get("execute_binding_status") == "BOUND_SAFE_EXACT_DATE_ENTRYPOINT"
        for role in ("ALPHA", "RISK", "EXECUTION")
    )
    if not execute_ready:
        reasons.append("PRODUCTION_EXECUTE_ENTRYPOINTS_NOT_BOUND")

    generated = generated_at or datetime.now(timezone.utc).isoformat()
    passed = not reasons
    available_dates = [target_date] if canonical_exact else []
    eligible_dates = [target_date] if eligible else []
    feature_dates = [target_date] if features_ready else []
    universe_dates = [target_date] if universe_ready else []
    return {
        "schema_version": "1.0.0",
        "readiness_version": "A2_FORWARD_SHADOW_READINESS_R1",
        "target_date": target_date,
        "generated_at": generated,
        "canonical_date_present": canonical_exact,
        "canonical_latest_date": pointer_latest,
        "canonical_manifest_latest_date": manifest_latest,
        "exact_target_date_match": canonical_exact,
        "trading_date_status": trading_status,
        "trading_calendar_latest_date": calendar_latest,
        "trading_calendar_id": calendar_id,
        "trading_calendar_sha256": calendar_sha,
        "latest_completed_us_session": completion["latest_completed_us_session"],
        "target_session_completed": completion["target_session_completed"],
        "as_of_timestamp": completion["as_of_timestamp"],
        "as_of_timezone": completion["as_of_timezone"],
        "canonical_lag_sessions": canonical_lag,
        "universe_snapshot_available": universe_ready,
        "universe_id": universe_id,
        "active_13f_quarter": active_quarter,
        "universe_manifest": str(universe_path),
        "universe_sha256": universe_ref["sha256"],
        "feature_input_available": features_ready,
        "feature_schema_id": feature_schema_id,
        "feature_input_manifest": str(canonical_manifest_path),
        "feature_input_sha256": canonical_hash,
        "alpha_binding_ready": component_ready["ALPHA"],
        "risk_binding_ready": component_ready["RISK"],
        "execution_binding_ready": component_ready["EXECUTION"],
        "production_execute_entrypoints_ready": execute_ready,
        "alpha_freeze_id": binding["components"]["ALPHA"]["freeze_id"],
        "risk_freeze_id": binding["components"]["RISK"]["freeze_id"],
        "execution_freeze_id": binding["components"]["EXECUTION"]["freeze_id"],
        "alpha_sha256": binding["components"]["ALPHA"]["composite_sha256"],
        "risk_sha256": binding["components"]["RISK"]["composite_sha256"],
        "execution_sha256": binding["components"]["EXECUTION"]["composite_sha256"],
        "canonical_pointer": str(pointer_path),
        "canonical_pointer_sha256": sha256_file(pointer_path),
        "canonical_manifest": str(canonical_manifest_path),
        "canonical_manifest_sha256": canonical_hash,
        "binding_manifest": str(binding_path),
        "binding_manifest_sha256": config["production_binding_sha256"],
        "2026_inference_only": target.year == 2026,
        "training_allowed": False,
        "parameter_search_allowed": False,
        "threshold_search_allowed": False,
        "model_selection_allowed": False,
        "broker_action_allowed": False,
        "read_only": True,
        "canonical_write_count": 0,
        "model_execute_count": 0,
        "component_inputs": input_refs,
        "readiness_status": "PASS" if passed else "FAIL",
        "failure_reasons": sorted(set(reasons)),
        "canonical_readiness": {
            "target_date": target_date,
            "as_of_date": str(date.today()),
            "canonical_manifest": str(canonical_manifest_path),
            "canonical_manifest_sha256": canonical_hash,
            "universe_id": universe_id,
            "available_dates": available_dates,
            "eligible_trading_dates": eligible_dates,
            "feature_ready_dates": feature_dates,
            "universe_ready_dates": universe_dates,
            "partial_dates": [] if canonical_exact else [target_date],
            "trading_calendar_id": calendar_id,
            "trading_calendar_sha256": calendar_sha,
        },
    }


def write_immutable_readiness(payload: dict[str, Any], output_root: Path) -> tuple[Path, str]:
    root = output_root.resolve()
    if not _under(root, APPROVED_RESULTS_ROOT) or _under(root, REPO_ROOT):
        raise ValueError("READINESS_OUTPUT_MUST_BE_APPROVED_EXTERNAL_RESULTS_PATH")
    root.mkdir(parents=True, exist_ok=True)
    stamp = payload["generated_at"].replace("-", "").replace(":", "").replace("+", "_").replace(".", "_")
    path = root / f"readiness_{payload['target_date']}_{stamp}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    digest = sha256_file(path)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    with sidecar.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"{digest}  {path.name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--as-of-timestamp")
    parser.add_argument("--timezone", default="Asia/Tokyo")
    parser.add_argument("--component-inputs-json", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    component_inputs = read_json(args.component_inputs_json.resolve()) if args.component_inputs_json else None
    payload = generate_readiness(
        args.target_date, args.config.resolve(), as_of_timestamp=args.as_of_timestamp,
        timezone_name=args.timezone, component_inputs=component_inputs,
    )
    if args.validate_only:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        config = read_json(args.config.resolve())
        output_root = args.output_root or Path(config["readiness_root"])
        path, digest = write_immutable_readiness(payload, output_root)
        print(f"READINESS_STATUS={payload['readiness_status']}")
        print(f"READINESS_PATH={path}")
        print(f"READINESS_SHA256={digest}")
        print(f"FAILURE_REASONS={','.join(payload['failure_reasons']) or 'NONE'}")
    return 0 if payload["readiness_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
