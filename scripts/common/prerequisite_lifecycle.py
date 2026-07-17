"""Authoritative V21 bootstrap prerequisite lifecycle.

Bundles are immutable-in-content, but their *location* is a fixed external
``daily/prerequisites/v21`` path.  Legacy trees are read-only migration inputs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.storage_paths import get_daily_root, get_python_executable

V230 = "V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
R1 = "V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE"
REQUIRED = {
    V230: ["v21_230_summary.json", "moomoo_refetch_dry_run_plan.csv", "ticker_universe_resolution.csv", "moomoo_frequency_plan.csv", "moomoo_adjustment_plan.csv", "moomoo_cache_target_plan.csv", "moomoo_canonical_target_plan.csv", "dram_intraday_refetch_plan.csv", "abcde_daily_refetch_plan.csv", "failed_or_missing_ticker_plan.csv", "v21_231_execution_prerequisites.csv", "dry_run_policy_gate.json"],
    R1: ["v21_230_r1_summary.json", "opend_connection_probe.csv", "moomoo_import_probe.csv", "moomoo_api_capability_probe.csv", "ticker_symbol_probe.csv", "permission_probe.csv", "v21_231_go_no_go_gate.csv", "opend_probe_policy_gate.json"],
}

def prerequisite_root() -> Path:
    return get_daily_root() / "prerequisites" / "v21"

def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}

def validate_bundle(stage: str, path: Path) -> tuple[bool, str]:
    missing = [name for name in REQUIRED[stage] if not (path / name).is_file() or not (path / name).stat().st_size]
    if missing:
        return False, "MISSING_REQUIRED_FILES:" + ",".join(missing)
    summary = _json(path / REQUIRED[stage][0])
    if not summary:
        return False, "INVALID_SUMMARY_JSON"
    if summary.get("broker_action_allowed") is not False or summary.get("official_adoption_allowed") is not False or summary.get("research_only") is not True:
        return False, "UNSAFE_POLICY_FLAGS"
    if stage == R1 and not (summary.get("v21_231_ready") is True and summary.get("final_status") == "PASS_V21_230_R1_MOOMOO_OPEND_READY_FOR_V21_231"):
        return False, "R1_NOT_READY:" + str(summary.get("final_status", ""))
    if str(summary.get("final_status", "")).startswith("FAIL"):
        return False, "FAILED_SUMMARY:" + str(summary.get("final_status"))
    return True, "VALID"

def _mark(path: Path) -> None:
    metadata = {"retention_class": "BOOTSTRAP_PREREQUISITE", "protected": True, "deletion_allowed": False}
    tmp = path / ".lifecycle.json.tmp"
    tmp.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path / ".lifecycle.json")

def promote(stage: str, source: Path) -> Path:
    ok, why = validate_bundle(stage, source)
    if not ok:
        raise RuntimeError(f"INVALID_PREREQUISITE_BUNDLE:{stage}:{why}")
    target = prerequisite_root() / stage
    existing, _ = validate_bundle(stage, target)
    if existing:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / ("." + stage + ".staging-" + uuid.uuid4().hex)
    shutil.copytree(source, staging)
    _mark(staging)
    ok, why = validate_bundle(stage, staging)
    if not ok:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"STAGED_PREREQUISITE_INVALID:{stage}:{why}")
    # Never replace a valid protected asset.  An invalid target is moved aside
    # only within the same external root, then bounded to one diagnostic copy.
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    return target

def resolve(stage: str, repo_root: Path) -> Path | None:
    candidates = [prerequisite_root() / stage,
                  get_daily_root() / "current" / stage,
                  get_daily_root() / "migrated_from_repo" / "outputs" / "v21" / stage,
                  repo_root / "outputs" / "v21" / stage]
    for candidate in candidates:
        ok, _ = validate_bundle(stage, candidate)
        if ok:
            return candidate if candidate == candidates[0] else promote(stage, candidate)
    return None

def ensure(repo_root: Path) -> tuple[Path, Path]:
    """Reuse validated assets or bootstrap both bundles once into prerequisites."""
    a, b = resolve(V230, repo_root), resolve(R1, repo_root)
    if a and b:
        return a, b
    py = get_python_executable()
    if not py.is_file():
        raise RuntimeError(f"MISSING_EXTERNAL_PYTHON:{py}")
    staging_root = get_daily_root() / "prerequisites" / ".bootstrap-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    a_stage = staging_root / (V230 + "-" + uuid.uuid4().hex)
    b_stage = staging_root / (R1 + "-" + uuid.uuid4().hex)
    commands = [
        [str(py), str(repo_root / "scripts/v21/v21_230_moomoo_only_historical_refetch_dry_run.py"), "--repo-root", str(repo_root), "--output-dir", str(a_stage)],
        [str(py), str(repo_root / "scripts/v21/v21_230_r1_moomoo_opend_readiness_and_permission_probe.py"), "--repo-root", str(repo_root), "--output-dir", str(b_stage), "--v21-230-output-dir", str(a_stage)],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=str(repo_root), text=True, capture_output=True)
        if completed.returncode:
            summary_name = "v21_230_summary.json" if V230 in command[1] else "v21_230_r1_summary.json"
            failed_summary = _json((a_stage if V230 in command[1] else b_stage) / summary_name)
            shutil.rmtree(a_stage, ignore_errors=True)
            shutil.rmtree(b_stage, ignore_errors=True)
            detail = failed_summary.get("final_status") or (completed.stderr or completed.stdout)[-500:]
            raise RuntimeError("BOOTSTRAP_CHILD_FAILED:" + Path(command[1]).name + ":" + str(detail))
    return promote(V230, a_stage), promote(R1, b_stage)

def live_preflight() -> dict[str, Any]:
    """Bounded daily OpenD reachability check; never alters protected bundles."""
    checked = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {"checked_at_utc": checked, "probe_symbols": ["US.SPY"], "opend_tcp_ready": False, "quote_context_ready": False, "history_capability_ready": False, "permission_ready": False, "error_type": "", "error_message": "", "live_preflight_status": "BLOCKED_EXTERNAL_OPEND_CONNECTION", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True}
    try:
        with socket.create_connection(("127.0.0.1", 18441), timeout=3):
            payload["opend_tcp_ready"] = True
        try:
            module = __import__("moomoo")
        except ModuleNotFoundError:
            module = __import__("futu")
        ctx = module.OpenQuoteContext(host="127.0.0.1", port=18441)
        try:
            payload["quote_context_ready"] = True
            payload["history_capability_ready"] = hasattr(ctx, "request_history_kline")
            payload["permission_ready"] = payload["history_capability_ready"]
            payload["live_preflight_status"] = "PASS_V21_230_R1_LIVE_PREFLIGHT"
        finally:
            ctx.close()
    except ModuleNotFoundError as exc:
        payload["live_preflight_status"] = "BLOCKED_EXTERNAL_MOOMOO_SDK"
        payload["error_type"], payload["error_message"] = type(exc).__name__, str(exc)
    except Exception as exc:
        payload["error_type"], payload["error_message"] = type(exc).__name__, str(exc)
    path = get_daily_root() / "current" / "V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE" / "live_preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8"); os.replace(tmp, path)
    return payload
