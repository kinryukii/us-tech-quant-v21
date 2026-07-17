#!/usr/bin/env python
"""V22.000 charter, scope, and risk policy freeze.

This module is registry-only. It creates the V22 charter artifacts without
fetching market data, connecting to broker APIs, generating orders, or mutating
existing V21 outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.000"
MODULE_NAME = "V22_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE"
STAGE = "V22.000_V22_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

FINAL_STATUS = "PASS_V22_000_CHARTER_SCOPE_AND_RISK_POLICY_FROZEN"
FINAL_DECISION = "V22_READY_FOR_CONSOLIDATION_FACTOR_VALIDITY_AND_ETF_OPTION_RESEARCH_ONLY"

V22_TRACKS = [
    "V21_CONSOLIDATION",
    "FACTOR_VALIDITY_RESEARCH",
    "ETF_OPTIONS_RESEARCH_EXTENSION",
]

CORE_ETF_UNIVERSE = ["SMH", "SOXX", "QQQ", "SPY", "DIA"]
SECONDARY_LEVERAGED_ETF_UNIVERSE = ["SOXL", "TQQQ", "SPXL", "UDOW"]
EXCLUDED_CASH_SETTLED_INDEX_OPTIONS = ["SPX", "XSP", "NDX", "XND", "RUT", "RUTW"]

ALLOWED_INITIAL_STRATEGIES = [
    "LONG_CALL",
    "LONG_PUT",
    "DEBIT_CALL_SPREAD",
    "DEBIT_PUT_SPREAD",
]

ALLOWED_RESEARCH_LATER_STRATEGIES = [
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

NEXT_RECOMMENDED_MODULES = [
    "V22.001_V21_CANONICAL_DAILY_ENTRYPOINT_FREEZE",
    "V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST",
    "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
]

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "research_only": True,
}

ROADMAP_ROWS = [
    ("V22.000_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE", "CHARTER", "Freeze V22 tracks, option scope, and no-action risk policy.", "COMPLETE_IN_THIS_MODULE"),
    ("V22.001_V21_CANONICAL_DAILY_ENTRYPOINT_FREEZE", "V21_CONSOLIDATION", "Freeze one canonical V21 daily research entrypoint.", "NEXT_RECOMMENDED"),
    ("V22.002_V21_ACTIVE_DEPRECATED_OUTPUT_MANIFEST", "V21_CONSOLIDATION", "Classify active, deprecated, and historical outputs.", "NEXT_RECOMMENDED"),
    ("V22.003_SYSTEM_MAP_AND_README_REFRESH", "V21_CONSOLIDATION", "Refresh README and system map after consolidation manifests.", "PLANNED"),
    ("V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY", "FACTOR_VALIDITY_RESEARCH", "Define factor evidence levels and promotion blockers.", "NEXT_RECOMMENDED"),
    ("V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT", "FACTOR_VALIDITY_RESEARCH", "Audit factor coverage and missingness.", "PLANNED"),
    ("V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL", "FACTOR_VALIDITY_RESEARCH", "Measure predictive validity by horizon and regime.", "PLANNED"),
    ("V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT", "FACTOR_VALIDITY_RESEARCH", "Identify redundant factor clusters.", "PLANNED"),
    ("V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT", "FACTOR_VALIDITY_RESEARCH", "Track multiple-testing and false-discovery risk.", "PLANNED"),
    ("V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD", "FACTOR_VALIDITY_RESEARCH", "Confirm factor behavior forward-only before any adoption review.", "PLANNED"),
    ("V22.020_DRAM_DAILY_DECISION_PANEL_R2", "V21_CONSOLIDATION", "Refresh DRAM decision panel as research-only.", "PLANNED"),
    ("V22.021_DRAM_SIGNAL_TO_ACTION_TRANSLATOR", "V21_CONSOLIDATION", "Translate signals for manual review only.", "PLANNED"),
    ("V22.022_DRAM_MANUAL_TRADE_JOURNAL_SCHEMA", "V21_CONSOLIDATION", "Define manual journal schema without broker execution.", "PLANNED"),
    ("V22.030_ETF_OPTION_UNIVERSE_REGISTRY", "ETF_OPTIONS_RESEARCH_EXTENSION", "Formalize ETF-only option universe.", "NEXT_RECOMMENDED"),
    ("V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY", "ETF_OPTIONS_RESEARCH_EXTENSION", "Define option contract spec schema.", "PLANNED"),
    ("V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT", "ETF_OPTIONS_RESEARCH_EXTENSION", "Future option-chain snapshot stage; blocked in V22.000.", "FUTURE_RESEARCH_ONLY"),
    ("V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT", "ETF_OPTIONS_RESEARCH_EXTENSION", "Audit option chain liquidity and coverage.", "PLANNED"),
    ("V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA", "ETF_OPTIONS_RESEARCH_EXTENSION", "Define package accounting schema.", "PLANNED"),
    ("V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR", "ETF_OPTIONS_RESEARCH_EXTENSION", "Generate long call/put research candidates.", "PLANNED"),
    ("V22.041_DEBIT_CALL_PUT_SPREAD_BUILDER", "ETF_OPTIONS_RESEARCH_EXTENSION", "Build debit call/put spread research packages.", "PLANNED"),
    ("V22.042_STRADDLE_STRANGLE_RESEARCH_BUILDER", "ETF_OPTIONS_RESEARCH_EXTENSION", "Research-only straddle/strangle builder after initial phase.", "LATER_RESEARCH_ONLY"),
    ("V22.043_OPTION_RISK_AND_CAPITAL_FIT_GATE", "ETF_OPTIONS_RESEARCH_EXTENSION", "Gate package risk and capital fit.", "PLANNED"),
    ("V22.044_OPTION_PAPER_PLAN_GENERATOR", "ETF_OPTIONS_RESEARCH_EXTENSION", "Generate paper plans only.", "PLANNED"),
    ("V22.045_OPTION_FORWARD_OUTCOME_LEDGER", "ETF_OPTIONS_RESEARCH_EXTENSION", "Track forward outcomes without execution.", "PLANNED"),
    ("V22.050_DAILY_RESEARCH_CHAIN_WITH_ETF_OPTIONS_EXTENSION", "ETF_OPTIONS_RESEARCH_EXTENSION", "Daily research chain extension after prior gates.", "PLANNED"),
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


def strategy_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in ALLOWED_INITIAL_STRATEGIES:
        rows.append(
            {
                "strategy_name": strategy,
                "strategy_group": "INITIAL_DEFINED_RISK_OR_LONG_PREMIUM",
                "permission_status": "ALLOWED_INITIAL_RESEARCH_ONLY",
                "option_leg_profile": "LONG_PREMIUM_OR_DEBIT_SPREAD",
                "max_loss_required": True,
                "naked_short_exposure_allowed": False,
                "leveraged_etf_allowed": True,
                "initial_phase_allowed": True,
                "research_only": True,
                "block_reason": "",
            }
        )
    for strategy in ALLOWED_RESEARCH_LATER_STRATEGIES:
        rows.append(
            {
                "strategy_name": strategy,
                "strategy_group": "LATER_DEFINED_RISK_RESEARCH_ONLY",
                "permission_status": "ALLOWED_LATER_RESEARCH_ONLY",
                "option_leg_profile": "DEFINED_RISK_MULTI_LEG_DEBIT",
                "max_loss_required": True,
                "naked_short_exposure_allowed": False,
                "leveraged_etf_allowed": True,
                "initial_phase_allowed": False,
                "research_only": True,
                "block_reason": "Not part of the V22.000 initial strategy phase.",
            }
        )
    for strategy in BLOCKED_STRATEGIES:
        rows.append(
            {
                "strategy_name": strategy,
                "strategy_group": "BLOCKED_UNCONTROLLED_OR_AUTOMATED_RISK",
                "permission_status": "BLOCKED",
                "option_leg_profile": "SHORT_PREMIUM_OR_AUTO_EXECUTION_RISK",
                "max_loss_required": True,
                "naked_short_exposure_allowed": False,
                "leveraged_etf_allowed": False,
                "initial_phase_allowed": False,
                "research_only": True,
                "block_reason": "Blocked by V22.000 scope freeze: no naked short, uncovered short, short premium 0DTE, auto credit, auto iron condor, or auto trade.",
            }
        )
    return rows


def etf_universe_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    themes = {
        "SMH": "SEMICONDUCTOR",
        "SOXX": "SEMICONDUCTOR",
        "QQQ": "NASDAQ_100",
        "SPY": "S_AND_P_500",
        "DIA": "DOW_30",
        "SOXL": "SEMICONDUCTOR_LEVERAGED",
        "TQQQ": "NASDAQ_100_LEVERAGED",
        "SPXL": "S_AND_P_500_LEVERAGED",
        "UDOW": "DOW_30_LEVERAGED",
    }
    for ticker in CORE_ETF_UNIVERSE:
        rows.append(
            {
                "ticker": ticker,
                "theme_bucket": themes[ticker],
                "universe_tier": "CORE_ETF",
                "leveraged_flag": False,
                "option_research_allowed": True,
                "option_chain_fetch_allowed_in_v22_000": False,
                "allowed_initial_strategy_scope": "LONG_CALL;LONG_PUT;DEBIT_CALL_SPREAD;DEBIT_PUT_SPREAD",
                "trade_allowed": False,
                "reason": "Core ETF universe; research-only option scope, no chain fetch in V22.000.",
            }
        )
    for ticker in SECONDARY_LEVERAGED_ETF_UNIVERSE:
        rows.append(
            {
                "ticker": ticker,
                "theme_bucket": themes[ticker],
                "universe_tier": "SECONDARY_HIGH_RISK_LEVERAGED_ETF",
                "leveraged_flag": True,
                "option_research_allowed": True,
                "option_chain_fetch_allowed_in_v22_000": False,
                "allowed_initial_strategy_scope": "LONG_CALL;LONG_PUT;DEBIT_CALL_SPREAD;DEBIT_PUT_SPREAD_WITH_EXTRA_RISK_REVIEW",
                "trade_allowed": False,
                "reason": "Secondary leveraged ETF universe; high-risk research-only scope.",
            }
        )
    for ticker in EXCLUDED_CASH_SETTLED_INDEX_OPTIONS:
        rows.append(
            {
                "ticker": ticker,
                "theme_bucket": "CASH_SETTLED_INDEX_OPTION",
                "universe_tier": "EXCLUDED_CASH_SETTLED_INDEX_OPTION",
                "leveraged_flag": False,
                "option_research_allowed": False,
                "option_chain_fetch_allowed_in_v22_000": False,
                "allowed_initial_strategy_scope": "EXCLUDED",
                "trade_allowed": False,
                "reason": "Cash-settled index options are excluded from V22 ETF options research scope.",
            }
        )
    return rows


def roadmap_rows() -> list[dict[str, Any]]:
    return [
        {
            "module_key": module_key,
            "track": track,
            "module_purpose": purpose,
            "v22_000_status": status,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "trade_allowed": False,
            "research_only": True,
        }
        for module_key, track, purpose, status in ROADMAP_ROWS
    ]


def risk_policy() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "max_open_strategy_packages_default": 1,
        "single_long_call_allowed": True,
        "single_long_put_allowed": True,
        "debit_spread_allowed": True,
        "naked_short_allowed": False,
        "uncovered_short_allowed": False,
        "short_premium_0dte_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "manual_execution_only": True,
        "paper_plan_only": True,
        "option_stop_loss_pct_reference": -30,
        "premarket_plan_required": True,
        "no_first_day_breakout_chase": True,
        "multi_timeframe_confirmation_required": True,
        "confirmation_order": ["1h", "15m", "1m"],
        "trade_allowed": False,
        "market_data_fetch_allowed": False,
        "moomoo_connection_allowed": False,
        "option_chain_fetch_allowed": False,
        "cache_mutation_allowed": False,
        "historical_outputs_mutation_allowed": False,
        "research_only": True,
    }


def summary(output_dir: Path) -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "charter_freeze_date": FREEZE_DATE,
        "final_status": FINAL_STATUS,
        "final_decision": FINAL_DECISION,
        "v22_tracks": V22_TRACKS,
        "core_etf_universe": CORE_ETF_UNIVERSE,
        "secondary_leveraged_etf_universe": SECONDARY_LEVERAGED_ETF_UNIVERSE,
        "excluded_cash_settled_index_options": EXCLUDED_CASH_SETTLED_INDEX_OPTIONS,
        "allowed_initial_strategies": ALLOWED_INITIAL_STRATEGIES,
        "allowed_research_later_strategies": ALLOWED_RESEARCH_LATER_STRATEGIES,
        "blocked_strategies": BLOCKED_STRATEGIES,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def report_text(payload: dict[str, Any]) -> str:
    lines = [
        "V22.000 V22 Charter Scope and Risk Policy Freeze",
        f"module_id={payload['module_id']}",
        f"module_name={payload['module_name']}",
        f"final_status={payload['final_status']}",
        f"final_decision={payload['final_decision']}",
        "tracks=" + ";".join(payload["v22_tracks"]),
        "core_etf_universe=" + ";".join(payload["core_etf_universe"]),
        "secondary_leveraged_etf_universe=" + ";".join(payload["secondary_leveraged_etf_universe"]),
        "excluded_cash_settled_index_options=" + ";".join(payload["excluded_cash_settled_index_options"]),
        "allowed_initial_strategies=" + ";".join(payload["allowed_initial_strategies"]),
        "blocked_strategies=" + ";".join(payload["blocked_strategies"]),
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "historical_outputs_mutation_allowed=False",
        "cache_mutation_allowed=False",
        "research_only=True",
        "module_scope=charter_and_scope_freeze_only",
    ]
    return "\n".join(lines) + "\n"


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    observed = output_dir.resolve()
    if observed != expected:
        raise ValueError(f"V22.000 output directory must be {expected}, got {observed}")


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = summary(output_dir)
    write_json(output_dir / "v22_charter_scope_freeze.json", payload)
    write_csv(
        output_dir / "v22_module_roadmap.csv",
        ["module_key", "track", "module_purpose", "v22_000_status", "broker_action_allowed", "official_adoption_allowed", "trade_allowed", "research_only"],
        roadmap_rows(),
    )
    write_csv(
        output_dir / "v22_allowed_blocked_strategy_registry.csv",
        [
            "strategy_name",
            "strategy_group",
            "permission_status",
            "option_leg_profile",
            "max_loss_required",
            "naked_short_exposure_allowed",
            "leveraged_etf_allowed",
            "initial_phase_allowed",
            "research_only",
            "block_reason",
        ],
        strategy_rows(),
    )
    write_csv(
        output_dir / "v22_etf_universe_scope_registry.csv",
        [
            "ticker",
            "theme_bucket",
            "universe_tier",
            "leveraged_flag",
            "option_research_allowed",
            "option_chain_fetch_allowed_in_v22_000",
            "allowed_initial_strategy_scope",
            "trade_allowed",
            "reason",
        ],
        etf_universe_rows(),
    )
    write_json(output_dir / "v22_risk_policy_freeze.json", risk_policy())
    (output_dir / "V22.000_v22_charter_scope_and_risk_policy_freeze_report.txt").write_text(report_text(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_charter_scope_freeze.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    print("option_chain_fetch_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
