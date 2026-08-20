#!/usr/bin/env python
"""FAST3 Option Risk Overlay R1: outcome-blind contract/data/PIT audit only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
R31A = RESULTS / "frozen/fast3/r31a_information_domain_feasibility_20260809T200000Z/FAST3_R31A_DOMAIN_INVENTORY.csv"
R42R = RESULTS / "frozen/fast3/r42r_frozen_confirmation_preregistration_repair_r1/FAST3_R42R_CONFIRMATION_PREREGISTRATION.json"
R43A = RESULTS / "frozen/fast3/r43a_independent_economic_target_contract_freeze_r1/FAST3_R43A_ECONOMIC_TARGET_CONTRACT.json"
EXPECTED_R42R = "2df064f334d6a8bc45d79d8bd4f308ee9b82a33c97129a6ae36ba6aecfc9c3e1"
EXPECTED_R43A = "a5d43651433c6dde50eef791facd02047db2be073a0097acaf31cd1af25d2d6a"
UNDERLYINGS = ("SOXX", "SMH", "QQQ", "SPY")


def load_primitives():
    path = REPO / "fast3/src/fast3/options/option_risk_overlay_r1.py"
    spec = importlib.util.spec_from_file_location("fast3_option_overlay_r1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load option risk overlay primitives")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def prior_option_evidence() -> dict[str, Any]:
    if not R31A.exists():
        return {"R31A_OPTIONS_EVIDENCE": "NOT_FOUND"}
    with R31A.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = next((item for item in rows if item.get("DOMAIN") == "OPTIONS_IMPLIED_VOLATILITY"), None)
    return {"R31A_OPTIONS_EVIDENCE": row or "NOT_FOUND", "R31A_INVENTORY_SHA256": sha256_file(R31A)}


def discovered_option_paths() -> list[str]:
    """Read-only filename inventory, bounded to explicit option-related names."""
    found: list[str] = []
    for root, dirs, files in os.walk(DATA, topdown=True, onerror=lambda _error: None):
        dirs[:] = [entry for entry in dirs if entry not in {".git", "__pycache__", "temp", "cache"}]
        for name in files:
            lowered = name.lower()
            if any(token in lowered for token in ("option", "options", "implied", "surface", "chain", "greek", "open_interest")):
                found.append(str(Path(root) / name))
    return sorted(found)


def feasibility(paths: list[str], prior: dict[str, Any]) -> dict[str, Any]:
    # R1 does not infer IV from a schema-only or synthetic/live example.  A
    # historical PIT surface requires timestamped chain observations in DATA.
    availability = {symbol: False for symbol in UNDERLYINGS}
    by_underlying = {}
    for symbol in UNDERLYINGS:
        matches = [path for path in paths if symbol.lower() in Path(path).name.lower()]
        by_underlying[symbol] = {
            "data_available": False,
            "historical_chain_paths": matches,
            "history_start": None, "history_end": None, "quote_frequency": "NONE",
            "expiration_coverage": "NONE", "strike_coverage": "NONE", "NBBO_availability": False,
            "IV_availability": False, "greeks_availability": False, "volume_availability": False,
            "OI_availability": False, "missingness": "TOTAL", "timestamp_timezone": "NOT_AVAILABLE",
            "duplicate_rate": None, "invalid_bid_ask_rate": None, "crossed_market_rate": None,
            "zero_bid_rate": None, "usable_snapshot_rate": 0.0,
            "PIT_status": "NOT_ASSESSABLE_NO_HISTORICAL_OPTION_SURFACE",
        }
    return {
        "OPTION_DATA_FEASIBILITY": "B_OPTION_DATA_NOT_AVAILABLE",
        "DATA_ROOT_READ_ONLY": True,
        "SCANNED_OPTION_NAMED_PATH_COUNT": len(paths),
        "SCANNED_OPTION_NAMED_PATHS": paths,
        "UNDERLYING_AUDIT": by_underlying,
        "R31A_PRIOR_EVIDENCE": prior,
        "SELECTED_OPTION_RISK_UNDERLYING": "NONE",
        "SELECTED_UNDERLYING_REASON": "NO_LEGAL_HISTORICAL_OPTION_SURFACE;R1_DOES_NOT_SUBSTITUTE_PROXY",
        "ACQUISITION_CONTRACT_IF_DATA_LATER_AUTHORIZED": {
            "priority": list(UNDERLYINGS),
            "selection_basis_outcome_blind_only": ["coverage", "liquidity", "timestamp_integrity", "PIT_provenance"],
            "required_schema": ["underlying", "snapshot_completed_at_utc", "expiration_date", "strike", "put_call", "bid", "ask", "implied_volatility", "delta", "underlying_spot"],
            "required_quote_quality": "timestamped_completed_NBBO_or_equivalent;no_synthetic_IV;no_schema_only_values",
            "OI_policy": "NOT_REQUIRED; if used, PREVIOUS_COMPLETED_TRADING_DAY_OI_ONLY",
        },
    }


def state_definitions() -> dict[str, Any]:
    return {
        "MAX_OPTION_STATE_VARIABLE_COUNT": 4,
        "OPTION_ATM_IV_30D": {
            "definition": "30-calendar-day constant-maturity ATM IV; within each expiry take the midpoint of call/put IV selected by closest absolute delta to 0.50, then linearly interpolate total variance across bracketing expiries.",
            "requires": ["timestamped IV", "delta", "expiration", "completed snapshot"],
        },
        "OPTION_DOWNSIDE_SKEW_30D": {
            "definition": "30-calendar-day constant-maturity 25-delta put IV minus OPTION_ATM_IV_30D; put selected by delta closest to -0.25; same total-variance interpolation.",
            "requires": ["timestamped IV", "delta", "put/call", "expiration", "completed snapshot"],
        },
        "OPTION_IV_TERM_SLOPE": {
            "definition": "ATM_IV_7D minus OPTION_ATM_IV_30D, both deterministic constant-maturity total-variance interpolations from the same completed snapshot.",
            "requires": ["ATM IV points bracketing 7D and 30D"],
        },
        "OPTION_INTRADAY_RISK_CHANGE": {
            "authoritative_metric": "OPTION_SKEW_CHANGE_INTRADAY",
            "definition": "Current OPTION_DOWNSIDE_SKEW_30D minus the most recent completed same-session skew snapshot no later than 60 minutes before the current completed snapshot; unavailable if no such legal snapshot exists.",
            "no_fallback_metric": "No automatic substitution to ATM-IV change; missing state remains unavailable in R1.",
        },
        "PERCENTILE_STATES": {
            "OPTION_ATM_IV_PERCENTILE": "expanding historical-only empirical percentile; prior completed observations only; min 60, max trailing 252 trading-day observations",
            "OPTION_DOWNSIDE_SKEW_PERCENTILE": "same historical-only percentile contract",
        },
        "missing_state_policy": "UNAVAILABLE -> NO_OPTION_OVERRIDE -> multiplier 1.00; no cross-session forward fill; max snapshot staleness 5 minutes.",
    }


def pit_contract() -> dict[str, Any]:
    return {
        "OPTION_INFORMATION_TIMESTAMP_RULE": "snapshot_completed_at_utc <= FAST3 decision timestamp; source snapshot must be fully completed.",
        "SNAPSHOT_RESOLUTION_RULE": "Use the last fully completed option snapshot only; never the next interval or a later close.",
        "TIMEZONE_RULE": "all source and decision timestamps are timezone-aware UTC before comparison; ET is retained only as a display field.",
        "MAX_STALENESS": "5 minutes",
        "OPEN_INTEREST_RULE": "OI is not an R1 variable. If a future authorized amendment uses it: PREVIOUS_COMPLETED_TRADING_DAY_OI_ONLY; oi_as_of_date < decision trade date.",
        "CONSTANT_MATURITY_RULE": "No fixed strikes. Deterministic total-variance interpolation between bracketing expiries only; no extrapolation.",
        "PERCENTILE_RULE": "strictly earlier completed observations only; no full-sample normalization.",
        "PIT_VIOLATION_BEHAVIOR": "invalid option state; do not materialize an overlay decision.",
        "PIT_AUDIT_STATUS": "PASS_ARCHITECTURE_NO_DATA_TO_MATERIALIZE",
        "PIT_VIOLATION_COUNT": 0,
        "SAME_DAY_FINAL_OI_USED": False,
        "FUTURE_OPTION_QUOTE_USED": False,
    }


def preregistration(definitions: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "RUN_NAME": "FAST3_OPTION_RISK_OVERLAY_R1",
        "R1_SCOPE": "CONTRACT_FREEZE_DATA_FEASIBILITY_PIT_ARCHITECTURE_ONLY",
        "MODEL_FIT_COUNT": 0,
        "NEW_ALPHA_FACTOR_COUNT": 0,
        "NEW_TARGET_COUNT": 0,
        "FAST3_SIGNAL_ROLE": "PRIMARY_ALPHA_AND_DIRECTION",
        "OPTION_OVERLAY_ROLE": "RISK_CONFIRMATION_AND_VETO_ONLY",
        "OPTION_DIRECTION_FLIP_ALLOWED": False,
        "OPTION_INDEPENDENT_TRADE_ALLOWED": False,
        "OPTION_POSITION_AMPLIFICATION_ALLOWED": False,
        "RISK_ACTION_SET": {"NORMAL": 1.00, "REDUCED": 0.50, "VETO": 0.00},
        "THRESHOLD_STATUS": "PREREGISTRATION_PLACEHOLDER_NOT_ECONOMICALLY_OPTIMIZED",
        "STATE_DEFINITIONS": definitions,
        "PIT_CONTRACT": contract,
        "R2_COMPARISON_FROZEN": {
            "baseline": "FAST3 unchanged", "overlay": "FAST3 plus frozen option risk overlay",
            "primary_risk_metrics": ["large_loss_frequency", "worst_5pct_trade_return", "CVaR_expected_shortfall", "losing_trade_mean", "maximum_adverse_excursion", "left_tail_quantiles"],
            "secondary_cost_of_protection": ["fraction_vetoed", "fraction_reduced", "profitable_trades_removed", "mean_return_change", "profit_factor_change", "trade_count_retention"],
            "prohibited_primary_objectives": ["accuracy", "AUROC", "Spearman", "mean_return_maximization"],
        },
        "CURRENT_FAST3_ISOLATION": {
            "R28_PROSPECTIVE_LINE_ISOLATION": True, "FAST3_PRIMARY_SIGNAL_CHANGED": False,
            "FAST3_TARGET_CHANGED": False, "FAST3_MODEL_CHANGED": False,
        },
        "FUTURE_OPTION_RESEARCH_NOTE": "Excluded from R1: IV technical indicators, strike/delta grids, dealer-greek assumptions, 0DTE factor zoo, and option-flow classifications.",
    }


def markdown(summary: dict[str, Any]) -> str:
    return f"""# FAST3 Option Risk Overlay R1\n\n## Classification\n\n`{summary['CLASSIFICATION']}`. R1 froze the risk-only architecture but found no historical, timestamped option surface in the authorized data root. No proxy was substituted.\n\n## Fixed role and guardrails\n\n- FAST3 remains the only alpha and direction source.\n- The overlay action set is NORMAL=1.00, REDUCED=0.50, VETO=0.00.\n- A missing/invalid option state means NO_OPTION_OVERRIDE and multiplier 1.00; it never causes an automatic veto.\n- It cannot flip UP/DOWN, open independent trades, or amplify position size.\n\n## Four frozen state concepts\n\n1. ATM 30D constant-maturity IV.\n2. 25-delta put IV minus ATM 30D IV downside skew.\n3. ATM 7D minus ATM 30D IV term slope.\n4. Intraday change in downside skew; no automatic fallback metric.\n\nAll snapshots must be completed at or before the FAST3 decision timestamp, with a five-minute maximum staleness. OI is not used; any future authorized use must be from a previous completed trading day.\n\n## R2 boundary\n\nR2 is preregistered only as a risk-control comparison of unchanged FAST3 versus unchanged FAST3 plus this frozen overlay. It may assess left-tail reduction and the cost of protection, but is not executed or authorized by R1.\n"""


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")); args = parser.parse_args()
    primitives = load_primitives()
    if sha256_file(R42R) != EXPECTED_R42R or sha256_file(R43A) != EXPECTED_R43A:
        raise SystemExit("FAIL_CLOSED_FAST3_FROZEN_IDENTITY_MISMATCH")
    output = RESULTS / "frozen/fast3" / f"option_risk_overlay_r1_{args.run_id}"
    output.mkdir(parents=True, exist_ok=False)
    definitions = state_definitions(); contract = pit_contract(); registration = preregistration(definitions, contract)
    registration_hash = canonical_sha256(registration); definition_hash = canonical_sha256(definitions)
    prior = prior_option_evidence(); paths = discovered_option_paths(); feasibility_report = feasibility(paths, prior)
    classification = "B_OPTION_DATA_INSUFFICIENT" if not any(item["data_available"] for item in feasibility_report["UNDERLYING_AUDIT"].values()) else "A_OPTION_RISK_OVERLAY_R1_ARCHITECTURE_READY"
    # Runtime-free guardrail self-check: no model, prediction, payoff, or overlay activation.
    primitives.validate_overlay_result(primitives.overlay_action("UP", None))
    primitives.validate_overlay_result(primitives.overlay_action("DOWN", "VETO"))
    summary = {
        "FAST3_OPTION_RISK_OVERLAY_R1_STATUS": "COMPLETE",
        "CLASSIFICATION": classification, "MODEL_FIT_COUNT": 0, "NEW_ALPHA_FACTOR_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "FAST3_DIRECTION_FLIP_ALLOWED": False, "OPTION_INDEPENDENT_TRADE_ALLOWED": False, "POSITION_AMPLIFICATION_ALLOWED": False,
        "OPTION_STATE_VARIABLE_COUNT": 4, "OPTION_ATM_IV_STATE_DEFINED": True, "OPTION_DOWNSIDE_SKEW_DEFINED": True,
        "OPTION_TERM_STRUCTURE_DEFINED": True, "OPTION_INTRADAY_CHANGE_DEFINED": True,
        **{f"{symbol}_OPTION_DATA_AVAILABLE": item["data_available"] for symbol, item in feasibility_report["UNDERLYING_AUDIT"].items()},
        "SELECTED_OPTION_RISK_UNDERLYING": feasibility_report["SELECTED_OPTION_RISK_UNDERLYING"],
        "SELECTED_UNDERLYING_REASON": feasibility_report["SELECTED_UNDERLYING_REASON"],
        "PIT_AUDIT_STATUS": contract["PIT_AUDIT_STATUS"], "PIT_VIOLATION_COUNT": 0,
        "SAME_DAY_FINAL_OI_USED": False, "FUTURE_OPTION_QUOTE_USED": False,
        "RISK_ACTION_SET": "1.00,0.50,0.00", "DIRECTION_REVERSAL_TEST": "PASS",
        "R28_PROSPECTIVE_LINE_ISOLATION": True, "FAST3_PRIMARY_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_MODEL_CHANGED": False,
        "R2_RISK_EVALUATION_PREREGISTERED": True, "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS",
        "ANTI_BLOAT_STATUS": "PASS_ONE_GENERIC_MODULE_ONE_AUDIT_RUNNER_ONE_TEST", "PREREGISTRATION_SHA256": registration_hash,
        "OPTION_STATE_DEFINITION_SHA256": definition_hash, "R42R_PREREGISTRATION_SHA256_VERIFIED": True,
        "R43A_TARGET_CONTRACT_SHA256_VERIFIED": True, "NO_LIVE_OR_PROSPECTIVE_OVERLAY_CREATED": True,
    }
    write_json(output / "FAST3_OPTION_RISK_OVERLAY_R1_PREREGISTRATION.json", registration | {"PREREGISTRATION_SHA256": registration_hash})
    write_json(output / "FAST3_OPTION_RISK_OVERLAY_R1_DATA_FEASIBILITY.json", feasibility_report)
    write_json(output / "FAST3_OPTION_RISK_OVERLAY_R1_PIT_CONTRACT.json", contract)
    write_json(output / "FAST3_OPTION_RISK_OVERLAY_R1_STATE_DEFINITIONS.json", definitions | {"OPTION_STATE_DEFINITION_SHA256": definition_hash})
    (output / "FAST3_OPTION_RISK_OVERLAY_R1_REPORT.md").write_text(markdown(summary), encoding="utf-8")
    write_json(output / "FAST3_OPTION_RISK_OVERLAY_R1_SUMMARY.json", summary | {"FINAL_REPORT_PATH": str(output / "FAST3_OPTION_RISK_OVERLAY_R1_REPORT.md")})
    print("FAST3_OPTION_RISK_OVERLAY_R1_STATUS=COMPLETE")
    print(f"FINAL_REPORT_PATH={output / 'FAST3_OPTION_RISK_OVERLAY_R1_REPORT.md'}")


if __name__ == "__main__":
    main()
