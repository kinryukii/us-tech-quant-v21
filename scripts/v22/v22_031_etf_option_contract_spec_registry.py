#!/usr/bin/env python
"""V22.031 ETF option contract specification registry.

Static contract-spec registry derived from V22.030 ETF option universe rows.
This module does not verify live broker availability, fetch option chains,
fetch market data, execute chains, mutate caches or historical outputs, or
generate trade plans/orders.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.031"
MODULE_NAME = "ETF_OPTION_CONTRACT_SPEC_REGISTRY"
STAGE = "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 6).isoformat()

UNIVERSE_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_registry.csv"
UNIVERSE_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_summary.json"

PASS_STATUS = "PASS_V22_031_ETF_OPTION_CONTRACT_SPEC_REGISTRY_READY"
FAIL_STATUS = "FAIL_V22_031_ETF_OPTION_CONTRACT_SPEC_REGISTRY_MISSING_REQUIRED_INPUTS"
READY_DECISION = "ETF_OPTION_CONTRACT_SPEC_REGISTRY_READY_RESEARCH_ONLY"
FAIL_DECISION = "ETF_OPTION_CONTRACT_SPEC_REGISTRY_BLOCKED_MISSING_REQUIRED_INPUTS"

INITIAL_STRATEGIES = ["LONG_CALL", "LONG_PUT", "DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"]
LATER_RESEARCH_STRATEGIES = [
    "LONG_STRADDLE",
    "LONG_STRANGLE",
    "CALL_BUTTERFLY_DEBIT",
    "PUT_BUTTERFLY_DEBIT",
    "CALENDAR_DEBIT_SPREAD",
    "DIAGONAL_DEBIT_SPREAD",
]
BLOCKED_STRATEGIES = [
    "NAKED_SHORT_CALL",
    "NAKED_SHORT_PUT",
    "SHORT_STRADDLE",
    "SHORT_STRANGLE",
    "UNCOVERED_RATIO_SPREAD",
    "SHORT_PREMIUM_0DTE",
    "AUTO_CREDIT_SPREAD",
    "AUTO_IRON_CONDOR",
    "AUTO_TRADE",
]

RISK_RULES = [
    ("STANDARD_100_SHARE_CONTRACT", "CONTRACT_SIZE", "ALL", "STANDARD", "Assume standard 100-share listed ETF option contract.", "Verify contract multiplier before candidate generation."),
    ("AMERICAN_STYLE_EARLY_EXERCISE_RISK", "EXERCISE_STYLE", "ALL", "HIGH", "American-style options can be exercised early.", "Manual review before any future broker workflow."),
    ("PHYSICAL_DELIVERY_ASSIGNMENT_RISK", "SETTLEMENT", "ALL", "HIGH", "Physical-delivery assignment risk applies to ETF options.", "Avoid uncovered short exposure; verify deliverable."),
    ("DIVIDEND_ASSIGNMENT_RISK", "ASSIGNMENT", "ALL", "HIGH", "Dividend timing can increase early assignment risk.", "Review ex-dividend calendar in a future verified module."),
    ("LEVERAGED_ETF_DAILY_RESET_RISK", "LEVERAGED_ETF", "LEVERAGED", "HIGH", "Leveraged ETFs have daily reset/path effects.", "Require stronger signal, liquidity, spread, and manual review."),
    ("INVERSE_LEVERAGED_PATH_DEPENDENCY_RISK", "INVERSE_LEVERAGED_ETF", "INVERSE", "HIGH", "Inverse leveraged ETFs add inverse exposure and path dependency.", "Require inverse exposure review."),
    ("HIGH_RISK_SECONDARY_MANUAL_REVIEW_REQUIRED", "SECONDARY_UNIVERSE", "HIGH_RISK_SECONDARY", "HIGH", "Secondary leveraged ETF options are high-risk research only.", "Manual review required."),
    ("LIQUIDITY_CHECK_REQUIRED", "LIQUIDITY", "ALL", "HIGH", "Live liquidity is not verified in V22.031.", "Require future option chain liquidity audit."),
    ("SPREAD_CHECK_REQUIRED", "SPREAD", "ALL", "HIGH", "Live bid/ask spread is not verified in V22.031.", "Require future spread audit."),
    ("NO_NAKED_SHORT_OPTION_ALLOWED", "SHORT_EXPOSURE", "ALL", "BLOCKING", "Naked short option exposure is prohibited.", "Keep naked short strategies blocked."),
    ("NO_AUTO_TRADE_ALLOWED", "AUTOMATION", "ALL", "BLOCKING", "Automated option trading is prohibited.", "Keep broker and trade gates closed."),
]

NO_ACTION_GATES = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

NEXT_RECOMMENDED_MODULES = [
    "V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT",
    "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
    "V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR",
]

SPEC_FIELDNAMES = [
    "ticker",
    "theme_bucket",
    "universe_group",
    "universe_tier",
    "option_product_type",
    "underlying_type",
    "leveraged_flag",
    "inverse_flag",
    "leverage_multiple",
    "standard_contract_share_count",
    "exercise_style_assumption",
    "settlement_type_assumption",
    "cash_settled_index_option",
    "early_exercise_risk",
    "assignment_risk",
    "dividend_assignment_risk",
    "broker_support_status",
    "live_option_chain_verified",
    "option_chain_fetch_allowed_in_v22_031",
    "contract_spec_source_mode",
    "contract_spec_verification_status",
    "requires_manual_broker_verification_later",
    "high_risk_secondary_flag",
    "requires_stronger_signal_than_core",
    "requires_liquidity_check",
    "requires_spread_check",
    "requires_inverse_exposure_review",
    "manual_review_required",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "research_only",
    "reason",
]

RISK_FIELDNAMES = [
    "ticker",
    "risk_rule_name",
    "risk_group",
    "risk_applies",
    "risk_severity",
    "risk_description",
    "required_mitigation",
    "broker_action_allowed",
    "trade_allowed",
    "reason",
]

STRATEGY_FIELDNAMES = [
    "ticker",
    "universe_group",
    "strategy_name",
    "permission_status",
    "initial_phase_allowed",
    "later_research_allowed",
    "blocked",
    "single_long_allowed",
    "short_leg_allowed_only_if_covered",
    "naked_short_exposure_allowed",
    "defined_risk_required",
    "max_loss_required",
    "option_chain_required_before_candidate_generation",
    "broker_action_allowed",
    "trade_allowed",
    "reason",
]

GROUP_FIELDNAMES = [
    "group_name",
    "ticker_count",
    "core_count",
    "leveraged_count",
    "inverse_count",
    "high_risk_secondary_count",
    "standard_100_share_contract_count",
    "american_style_assumption_count",
    "physical_delivery_assumption_count",
    "cash_settled_count",
    "early_exercise_risk_count",
    "assignment_risk_count",
    "dividend_assignment_risk_count",
    "live_option_chain_verified_count",
    "broker_action_allowed_count",
    "official_adoption_allowed_count",
    "trade_allowed_count",
    "group_recommendation",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.031 output directory must be {expected}, got {output_dir.resolve()}")


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def spec_rows(universe: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in universe:
        inverse = bool_from_text(row.get("inverse_flag", ""))
        leveraged = bool_from_text(row.get("leveraged_flag", ""))
        high_risk = bool_from_text(row.get("high_risk_secondary_flag", ""))
        rows.append(
            {
                "ticker": row.get("ticker", ""),
                "theme_bucket": row.get("theme_bucket", ""),
                "universe_group": row.get("universe_group", ""),
                "universe_tier": row.get("universe_tier", ""),
                "option_product_type": "ETF_OPTION",
                "underlying_type": "ETF",
                "leveraged_flag": leveraged,
                "inverse_flag": inverse,
                "leverage_multiple": row.get("leverage_multiple", ""),
                "standard_contract_share_count": 100,
                "exercise_style_assumption": "AMERICAN_STYLE",
                "settlement_type_assumption": "PHYSICAL_DELIVERY",
                "cash_settled_index_option": False,
                "early_exercise_risk": True,
                "assignment_risk": True,
                "dividend_assignment_risk": True,
                "broker_support_status": "NOT_VERIFIED_STATIC_REGISTRY",
                "live_option_chain_verified": False,
                "option_chain_fetch_allowed_in_v22_031": False,
                "contract_spec_source_mode": "STATIC_REGISTRY_ASSUMPTION",
                "contract_spec_verification_status": "REQUIRES_FUTURE_BROKER_OR_OCC_VERIFICATION",
                "requires_manual_broker_verification_later": True,
                "high_risk_secondary_flag": high_risk,
                "requires_stronger_signal_than_core": high_risk,
                "requires_liquidity_check": True,
                "requires_spread_check": True,
                "requires_inverse_exposure_review": inverse,
                "manual_review_required": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "reason": "Static ETF option contract assumption requiring future broker/OCC verification; no live option chain was fetched.",
            }
        )
        _ = leveraged
    return rows


def risk_applies(rule_scope: str, row: dict[str, Any]) -> bool:
    if rule_scope == "ALL":
        return True
    if rule_scope == "LEVERAGED":
        return row["leveraged_flag"] is True
    if rule_scope == "INVERSE":
        return row["inverse_flag"] is True
    if rule_scope == "HIGH_RISK_SECONDARY":
        return row["high_risk_secondary_flag"] is True
    return False


def risk_rows(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        for rule_name, group, scope, severity, description, mitigation in RISK_RULES:
            applies = risk_applies(scope, spec)
            rows.append(
                {
                    "ticker": spec["ticker"],
                    "risk_rule_name": rule_name,
                    "risk_group": group,
                    "risk_applies": applies,
                    "risk_severity": severity if applies else "NOT_APPLICABLE",
                    "risk_description": description,
                    "required_mitigation": mitigation,
                    "broker_action_allowed": False,
                    "trade_allowed": False,
                    "reason": "Static contract risk rule; no broker or trade permission is granted.",
                }
            )
    return rows


def strategy_rows(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        for strategy in INITIAL_STRATEGIES:
            rows.append(strategy_row(spec, strategy, "ALLOWED_INITIAL_RESEARCH"))
        for strategy in LATER_RESEARCH_STRATEGIES:
            rows.append(strategy_row(spec, strategy, "ALLOWED_LATER_RESEARCH"))
        for strategy in BLOCKED_STRATEGIES:
            rows.append(strategy_row(spec, strategy, "BLOCKED"))
    return rows


def strategy_row(spec: dict[str, Any], strategy: str, permission: str) -> dict[str, Any]:
    blocked = permission == "BLOCKED"
    initial = permission == "ALLOWED_INITIAL_RESEARCH"
    later = permission == "ALLOWED_LATER_RESEARCH"
    return {
        "ticker": spec["ticker"],
        "universe_group": spec["universe_group"],
        "strategy_name": strategy,
        "permission_status": permission,
        "initial_phase_allowed": initial,
        "later_research_allowed": later,
        "blocked": blocked,
        "single_long_allowed": strategy in {"LONG_CALL", "LONG_PUT"},
        "short_leg_allowed_only_if_covered": (not blocked) and strategy not in {"LONG_CALL", "LONG_PUT"},
        "naked_short_exposure_allowed": False,
        "defined_risk_required": True,
        "max_loss_required": True,
        "option_chain_required_before_candidate_generation": True,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "reason": "Strategy scope is research-only and requires future option chain checks before candidate generation.",
    }


def group_summary_rows(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in sorted({row["universe_group"] for row in specs}):
        members = [row for row in specs if row["universe_group"] == group]
        rows.append(
            {
                "group_name": group,
                "ticker_count": len(members),
                "core_count": sum(1 for row in members if row["universe_tier"] == "CORE"),
                "leveraged_count": sum(1 for row in members if row["leveraged_flag"] is True),
                "inverse_count": sum(1 for row in members if row["inverse_flag"] is True),
                "high_risk_secondary_count": sum(1 for row in members if row["high_risk_secondary_flag"] is True),
                "standard_100_share_contract_count": sum(1 for row in members if row["standard_contract_share_count"] == 100),
                "american_style_assumption_count": sum(1 for row in members if row["exercise_style_assumption"] == "AMERICAN_STYLE"),
                "physical_delivery_assumption_count": sum(1 for row in members if row["settlement_type_assumption"] == "PHYSICAL_DELIVERY"),
                "cash_settled_count": sum(1 for row in members if row["cash_settled_index_option"] is True),
                "early_exercise_risk_count": sum(1 for row in members if row["early_exercise_risk"] is True),
                "assignment_risk_count": sum(1 for row in members if row["assignment_risk"] is True),
                "dividend_assignment_risk_count": sum(1 for row in members if row["dividend_assignment_risk"] is True),
                "live_option_chain_verified_count": 0,
                "broker_action_allowed_count": 0,
                "official_adoption_allowed_count": 0,
                "trade_allowed_count": 0,
                "group_recommendation": "Research-only static contract assumptions; require future broker/OCC and option-chain verification.",
            }
        )
    return rows


def summary_payload(repo_root: Path, specs: list[dict[str, Any]], risks: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> dict[str, Any]:
    input_exists = (repo_root / UNIVERSE_INPUT).exists()
    summary_exists = (repo_root / UNIVERSE_SUMMARY_INPUT).exists()
    pass_ready = input_exists and summary_exists and len(specs) == 13
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": PASS_STATUS if pass_ready else FAIL_STATUS,
        "final_decision": READY_DECISION if pass_ready else FAIL_DECISION,
        "v22_030_universe_input_exists": input_exists,
        "v22_030_summary_input_exists": summary_exists,
        "contract_spec_row_count": len(specs),
        "contract_risk_row_count": len(risks),
        "contract_strategy_scope_row_count": len(strategies),
        "core_etf_count": sum(1 for row in specs if row["universe_group"] == "CORE_ETF"),
        "secondary_leveraged_long_count": sum(1 for row in specs if row["universe_group"] == "SECONDARY_LEVERAGED_LONG"),
        "secondary_leveraged_inverse_count": sum(1 for row in specs if row["universe_group"] == "SECONDARY_LEVERAGED_INVERSE"),
        "leveraged_etf_count": sum(1 for row in specs if row["leveraged_flag"] is True),
        "inverse_leveraged_etf_count": sum(1 for row in specs if row["inverse_flag"] is True),
        "high_risk_secondary_count": sum(1 for row in specs if row["high_risk_secondary_flag"] is True),
        "standard_100_share_contract_count": sum(1 for row in specs if row["standard_contract_share_count"] == 100),
        "american_style_assumption_count": sum(1 for row in specs if row["exercise_style_assumption"] == "AMERICAN_STYLE"),
        "physical_delivery_assumption_count": sum(1 for row in specs if row["settlement_type_assumption"] == "PHYSICAL_DELIVERY"),
        "cash_settled_index_option_count": 0,
        "early_exercise_risk_count": sum(1 for row in specs if row["early_exercise_risk"] is True),
        "assignment_risk_count": sum(1 for row in specs if row["assignment_risk"] is True),
        "dividend_assignment_risk_count": sum(1 for row in specs if row["dividend_assignment_risk"] is True),
        "live_option_chain_verified_count": 0,
        "option_chain_fetch_allowed_count": 0,
        "broker_action_allowed_count": 0,
        "official_adoption_allowed_count": 0,
        "trade_allowed_count": 0,
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_031_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
            "promote_factor",
            "promote_strategy",
            "change_factor_weight",
        ],
        **{key: value for key, value in NO_ACTION_GATES.items() if key != "research_only"},
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.031 ETF Option Contract Spec Registry",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"contract_spec_row_count={summary['contract_spec_row_count']}",
        f"standard_100_share_contract_count={summary['standard_100_share_contract_count']}",
        "live_option_chain_verified_count=0",
        "option_chain_fetch_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "protected_outputs_modified=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    required_ok = (repo_root / UNIVERSE_INPUT).exists() and (repo_root / UNIVERSE_SUMMARY_INPUT).exists()
    universe = read_csv_rows(repo_root / UNIVERSE_INPUT) if required_ok else []
    specs = spec_rows(universe)
    risks = risk_rows(specs)
    strategies = strategy_rows(specs)
    groups = group_summary_rows(specs)
    summary = summary_payload(repo_root, specs, risks, strategies)

    write_csv(output_dir / "v22_etf_option_contract_spec_registry.csv", SPEC_FIELDNAMES, specs)
    write_csv(output_dir / "v22_etf_option_contract_risk_registry.csv", RISK_FIELDNAMES, risks)
    write_csv(output_dir / "v22_etf_option_contract_strategy_scope.csv", STRATEGY_FIELDNAMES, strategies)
    write_csv(output_dir / "v22_etf_option_contract_spec_group_summary.csv", GROUP_FIELDNAMES, groups)
    write_json(output_dir / "v22_etf_option_contract_spec_summary.json", summary)
    write_json(output_dir / "v22_etf_option_contract_spec_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.031_etf_option_contract_spec_registry_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_etf_option_contract_spec_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
