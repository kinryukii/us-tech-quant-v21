#!/usr/bin/env python3
"""CLI for A2 Forward Shadow Unified Runner R1.

Production identity and roots may be bound to an immutable binding manifest.
Preflight validates adapters and plans only; it never invokes model or broker code.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from forward_shadow.components import ShadowComponent, SyntheticComponent
from forward_shadow.manifest import file_sha256
from forward_shadow.preflight import run_preflight
from forward_shadow.protocol import ProtocolStore
from forward_shadow.reconcile import reconcile_components
from forward_shadow.registry_resolver import resolve_components
from forward_shadow.runner import EXIT_CODES, UnifiedShadowRunner
from forward_shadow.schemas import CanonicalReadiness, ROLES, RunIdentity, RunnerConfig, canonical_sha256


DEFAULT_CONFIG = REPO_ROOT / "config" / "research_governance" / "a2_forward_shadow_unified_r1.json"
DEFAULT_FIXTURE = SCRIPT_DIR / "fixtures" / "forward_shadow" / "tiny_unified_shadow_fixture.json"
A2_PORTFOLIO_POLICY_DEFAULT_ENABLED = False


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_config(path: Path) -> RunnerConfig:
    payload = _read_json(path)
    binding_value = str(payload.get("production_binding_manifest", "REQUIRED_AT_PRODUCTION"))
    if binding_value != "REQUIRED_AT_PRODUCTION":
        binding_path = Path(binding_value)
        if not binding_path.is_absolute():
            binding_path = (REPO_ROOT / binding_path).resolve()
        binding = _read_json(binding_path)
        contract_payload = dict(payload)
        contract_payload["production_binding_sha256"] = "SELF_REFERENCE_EXCLUDED"
        if canonical_sha256(contract_payload) != binding.get("unified_runner_config_contract_sha256"):
            raise ValueError("UNIFIED_RUNNER_CONFIG_CONTRACT_SHA256_MISMATCH")
    paths = payload.get("registry_paths", {})
    payload["registry_paths"] = {
        role: str((REPO_ROOT / value).resolve()) if not Path(value).is_absolute() else value
        for role, value in paths.items()
    }
    return RunnerConfig.from_dict(payload)


def _identity_and_readiness(
    config_path: Path,
    config: RunnerConfig,
    readiness_payload: Mapping[str, Any],
    target_date: str,
    synthetic_overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[RunIdentity, CanonicalReadiness]:
    readiness = CanonicalReadiness.from_dict(readiness_payload)
    if target_date != readiness.target_date:
        raise ValueError("requested target_date does not match exact fixture date; fallback is forbidden")
    components = resolve_components(
        config.registry_paths,
        synthetic_overrides=synthetic_overrides,
    )
    identity = RunIdentity(
        target_date=target_date,
        canonical_manifest_sha256=readiness.canonical_manifest_sha256,
        universe_id=readiness.universe_id,
        config_sha256=file_sha256(config_path),
        components=components,
        trading_calendar_id=readiness.trading_calendar_id,
        trading_calendar_sha256=readiness.trading_calendar_sha256,
    )
    return identity, readiness


def _synthetic_adapters(fixture: Mapping[str, Any]) -> dict[str, ShadowComponent]:
    component_payloads = fixture.get("components", {})
    return {role: SyntheticComponent(role, component_payloads[role]) for role in ROLES}


def _run_a2_portfolio_policy_hook(
    alpha_records: tuple[Mapping[str, Any], ...],
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None or payload.get("enabled", A2_PORTFOLIO_POLICY_DEFAULT_ENABLED) is not True:
        return None
    current_portfolio = payload.get("current_portfolio")
    if current_portfolio is None:
        raise ValueError("A2_POLICY_EXPLICIT_CURRENT_PORTFOLIO_REQUIRED")
    market_prices = payload.get("market_prices")
    if not isinstance(market_prices, Mapping):
        raise ValueError("A2_POLICY_MARKET_PRICES_REQUIRED")
    policy = importlib.import_module("a2_autonomous_buy_sell_and_sizing_policy_r1")
    safety = importlib.import_module("v22_047_r1b_auto_trading_control_component")
    plan = policy.build_operational_policy_plan(alpha_records, current_portfolio)
    safety_plan = safety.build_a2_shadow_order_intents(plan, market_prices)
    return {
        "status": "PASS",
        "policy_enabled": True,
        "policy_plan": plan,
        "safety_plan": safety_plan,
        "broker_action_run": False,
    }


def _production_adapters(
    config: RunnerConfig,
    readiness_record: Mapping[str, Any] | None = None,
) -> dict[str, ShadowComponent]:
    adapters: dict[str, ShadowComponent] = {}
    shared_context: dict[str, Any] = {}
    for role in ROLES:
        locator = config.production_adapters.get(role, "REQUIRED_AT_PRODUCTION")
        if locator == "REQUIRED_AT_PRODUCTION" or ":" not in locator:
            raise ValueError(f"{role} production adapter is REQUIRED_AT_PRODUCTION")
        module_name, factory_name = locator.split(":", 1)
        factory = getattr(importlib.import_module(module_name), factory_name)
        adapter = factory(
            role=role, config=config, readiness=readiness_record,
            shared_context=shared_context,
        )
        if not isinstance(adapter, ShadowComponent):
            raise TypeError(f"{role} factory did not return ShadowComponent")
        adapters[role] = adapter
    return adapters


def _pure_fixture_validation(
    identity: RunIdentity,
    readiness: CanonicalReadiness,
    config: RunnerConfig,
    adapters: Mapping[str, ShadowComponent],
    mode: str,
    policy_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    preflight = run_preflight(identity.target_date, readiness, identity.components, config, mode=mode)
    if preflight["status"] != "PASS":
        return {"status": "FAIL", "preflight_status": "FAIL", "exit_code": EXIT_CODES["PREFLIGHT"], "reasons": preflight["reasons"]}
    results = {}
    for role in ROLES:
        adapter = adapters[role]
        adapter.prepare(identity)
        adapter.validate_inputs(identity)
        result = adapter.execute(identity)
        adapter.validate_output(result, identity)
        results[role] = result
    reconciliation = reconcile_components(results, identity, config)
    exit_code = EXIT_CODES["SUCCESS"] if reconciliation["status"] == "PASS" else EXIT_CODES["RECONCILIATION"]
    status = {
        "status": "PASS" if exit_code == 0 else "FAIL",
        "run_id": identity.run_id,
        "target_date": identity.target_date,
        "preflight_status": "PASS",
        "reconciliation_status": reconciliation["status"],
        "cross_shadow_date_status": reconciliation["cross_shadow_date_status"],
        "cross_component_lineage_status": reconciliation["cross_component_lineage_status"],
        "security_alignment_status": reconciliation["security_alignment_status"],
        "governance_status": reconciliation["governance_status"],
        "commit_status": "NOT_COMMITTED_FIXTURE_VALIDATION",
        "exit_code": exit_code,
        "training_run": False,
        "parameter_search_run": False,
        "model_selection_run": False,
        "broker_action_run": False,
    }
    if policy_payload is not None and policy_payload.get("enabled") is True:
        try:
            policy_status = _run_a2_portfolio_policy_hook(results["ALPHA"].records, policy_payload)
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            status.update({
                "status": "FAIL",
                "exit_code": EXIT_CODES["PREFLIGHT"],
                "a2_portfolio_policy_status": "FAIL_CLOSED",
                "a2_portfolio_policy_failure_reason": str(exc),
                "commit_status": "NOT_COMMITTED_FIXTURE_VALIDATION",
            })
        else:
            status["a2_portfolio_policy_status"] = "PASS"
            status["a2_portfolio_policy"] = policy_status
    return status


def _preflight_only(
    identity: RunIdentity,
    readiness: CanonicalReadiness,
    config: RunnerConfig,
    *,
    production_bound: bool,
    readiness_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = run_preflight(
        identity.target_date, readiness, identity.components, config,
        mode="production" if production_bound else "preflight",
    )
    reasons = list(result["reasons"])
    if production_bound:
        reasons.extend(
            f"{role}_PRODUCTION_ADAPTER_REQUIRED"
            for role in ROLES
            if config.production_adapters.get(role) == "REQUIRED_AT_PRODUCTION"
        )
        if "REQUIRED_AT_PRODUCTION" in (config.staging_root, config.authoritative_shadow_root):
            reasons.append("PRODUCTION_OUTPUT_ROOTS_REQUIRED")
    adapter_reports: dict[str, Any] = {}
    execution_plans: dict[str, Any] = {}
    if production_bound and not any(reason.endswith("PRODUCTION_ADAPTER_REQUIRED") for reason in reasons):
        for role, adapter in _production_adapters(config, readiness_record).items():
            binding_report = adapter.validate_binding()
            runtime_report = adapter.validate_runtime()
            input_report = adapter.validate_target_date_inputs(readiness_record or {}, identity.target_date)
            plan = adapter.build_execution_plan(identity.target_date)
            adapter_reports[role] = {
                "binding": binding_report,
                "runtime": runtime_report,
                "target_date_inputs": input_report,
            }
            execution_plans[role] = plan
            if binding_report.get("status") != "PASS":
                reasons.append(f"{role}_PRODUCTION_BINDING_INVALID")
            if runtime_report.get("status") != "PASS":
                reasons.append(f"{role}_PRODUCTION_RUNTIME_INVALID")
            if input_report.get("status") != "PASS":
                reasons.append(f"{role}_TARGET_DATE_INPUTS_NOT_READY")
            if plan.get("execution_capability") != "BOUND_SAFE_EXACT_DATE_ENTRYPOINT":
                reasons.append(f"{role}_SAFE_EXACT_DATE_EXECUTE_ENTRYPOINT_UNBOUND")
    passed = not reasons
    return {
        "status": "PASS" if passed else "FAIL",
        "run_id": identity.run_id,
        "target_date": identity.target_date,
        "preflight_status": "PASS" if passed else "FAIL_CLOSED",
        "reasons": sorted(set(reasons)),
        "adapter_reports": adapter_reports,
        "execution_plans": execution_plans,
        "production_execution_planned": False,
        "production_execution_run": False,
        "commit_status": "NOT_COMMITTED_PREFLIGHT",
        "exit_code": EXIT_CODES["SUCCESS"] if passed else EXIT_CODES["PREFLIGHT"],
        "training_run": False,
        "parameter_search_run": False,
        "model_selection_run": False,
        "broker_action_run": False,
    }


def _write_status(path: Path, status: Mapping[str, Any]) -> str:
    resolved = path.resolve()
    approved = Path(r"D:\us-tech-quant-results").resolve()
    if approved != resolved.parent and approved not in resolved.parents:
        raise ValueError("STATUS_OUTPUT_MUST_BE_UNDER_APPROVED_EXTERNAL_RESULTS_ROOT")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(status, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return file_sha256(resolved)


def _store(config: RunnerConfig, workspace_root: str | None) -> ProtocolStore:
    if workspace_root:
        root = Path(workspace_root).resolve()
        return ProtocolStore(root / "staging", root / "authoritative")
    if "REQUIRED_AT_PRODUCTION" in (config.staging_root, config.authoritative_shadow_root):
        raise ValueError("production staging/authoritative roots are REQUIRED_AT_PRODUCTION")
    return ProtocolStore(Path(config.staging_root), Path(config.authoritative_shadow_root))


def _summary(status: Mapping[str, Any]) -> str:
    lines = [
        "=" * 60,
        "A2 FORWARD SHADOW UNIFIED RUNNER R1",
        "=" * 60,
        f"RUN_ID={status.get('run_id', 'NOT_APPLICABLE')}",
        f"TARGET_DATE={status.get('target_date', 'NOT_APPLICABLE')}",
        f"PREFLIGHT_STATUS={status.get('preflight_status', 'NOT_EVALUATED')}",
        f"CROSS_SHADOW_DATE_STATUS={status.get('cross_shadow_date_status', 'NOT_EVALUATED')}",
        f"CROSS_COMPONENT_LINEAGE_STATUS={status.get('cross_component_lineage_status', 'NOT_EVALUATED')}",
        f"SECURITY_ALIGNMENT_STATUS={status.get('security_alignment_status', 'NOT_EVALUATED')}",
        f"GOVERNANCE_STATUS={status.get('governance_status', 'NOT_EVALUATED')}",
        f"DUPLICATE_STATUS={status.get('duplicate_status', 'NOT_EVALUATED')}",
        f"STAGING_STATUS={status.get('staging_status', 'NOT_STAGED')}",
        f"COMMIT_STATUS={status.get('commit_status', 'NOT_COMMITTED')}",
        f"FINAL_MANIFEST_SHA256={status.get('manifest_sha256') or 'NONE'}",
        "TRAINING_RUN=FALSE",
        "PARAMETER_SEARCH_RUN=FALSE",
        "MODEL_SELECTION_RUN=FALSE",
        "BROKER_ACTION_RUN=FALSE",
        "=" * 60,
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "dry-run", "validate-fixture", "production", "resume", "status", "validate-history-chain"))
    parser.add_argument("--target-date")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--readiness-json", type=Path, help="Authoritative exact-date readiness record for production/resume")
    parser.add_argument("--readiness-sha256", help="Required expected SHA-256 for an immutable readiness record")
    parser.add_argument("--status-output", type=Path, help="Exclusive-create external JSON status record")
    parser.add_argument("--workspace-root", help="Synthetic-only protocol root; never treated as production history")
    parser.add_argument("--status-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config_path = args.config.resolve()
        config = _load_config(config_path)
        if args.mode in ("status", "validate-history-chain"):
            status = _store(config, args.workspace_root).history_status()
            status["exit_code"] = 0 if status.get("status") == "PASS" else EXIT_CODES["RECONCILIATION"]
        else:
            production_bound = args.mode == "production" or (
                args.mode in ("preflight", "resume") and args.readiness_json is not None
            )
            fixture = None if production_bound else _read_json(args.fixture.resolve())
            if production_bound:
                if args.readiness_json is None:
                    raise ValueError("--readiness-json is required for production; no canonical fallback is allowed")
                if not args.readiness_sha256:
                    raise ValueError("--readiness-sha256 is required for immutable readiness verification")
                readiness_path = args.readiness_json.resolve()
                if file_sha256(readiness_path) != args.readiness_sha256.lower():
                    raise ValueError("READINESS_SHA256_MISMATCH")
                readiness_record = _read_json(readiness_path)
                readiness_payload = readiness_record.get("canonical_readiness", readiness_record)
            else:
                readiness_payload = fixture["canonical_readiness"]
            target_date = args.target_date or str(readiness_payload.get("target_date", ""))
            if not target_date:
                raise ValueError("--target-date is required")
            identity, readiness = _identity_and_readiness(
                config_path, config, readiness_payload, target_date,
                synthetic_overrides=None if production_bound else fixture.get("synthetic_component_overrides"),
            )
            if args.mode == "preflight":
                status = _preflight_only(
                    identity, readiness, config, production_bound=production_bound,
                    readiness_record=readiness_record if production_bound else None,
                )
            elif args.mode == "validate-fixture":
                adapters = _synthetic_adapters(fixture)
                status = _pure_fixture_validation(
                    identity, readiness, config, adapters, args.mode,
                    policy_payload=fixture.get("a2_portfolio_policy"),
                )
            else:
                adapters = _production_adapters(config, readiness_record) if production_bound else _synthetic_adapters(fixture)
                commit = args.mode in ("production", "resume")
                status = UnifiedShadowRunner(config, _store(config, args.workspace_root)).run(
                    identity, readiness, adapters, mode=args.mode,
                    commit=commit, resume=args.mode == "resume",
                )
        if args.status_output:
            status["status_output"] = str(args.status_output.resolve())
            status["status_output_sha256"] = _write_status(args.status_output, status)
        print(json.dumps(status, indent=2, sort_keys=True) if args.status_json else _summary(status))
        return int(status.get("exit_code", 1))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, ImportError) as exc:
        status = {"status": "FAIL", "failure_code": "FAIL_PREFLIGHT", "failure_reason": str(exc), "exit_code": EXIT_CODES["PREFLIGHT"]}
        print(json.dumps(status, indent=2, sort_keys=True) if args.status_json else _summary(status), file=sys.stderr)
        return EXIT_CODES["PREFLIGHT"]


if __name__ == "__main__":
    raise SystemExit(main())
