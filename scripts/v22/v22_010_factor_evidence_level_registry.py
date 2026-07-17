#!/usr/bin/env python
"""V22.010 factor evidence level registry.

This module creates a research-only registry of factor, strategy, technical,
DRAM, and ETF option-extension evidence levels. It does not fetch data, execute
chains, connect to brokers, mutate cache, or modify historical outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.010"
MODULE_NAME = "FACTOR_EVIDENCE_LEVEL_REGISTRY"
STAGE = "V22.010_FACTOR_EVIDENCE_LEVEL_REGISTRY"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 5).isoformat()

FINAL_STATUS = "PASS_V22_010_FACTOR_EVIDENCE_LEVEL_REGISTRY_READY"
FINAL_DECISION = "FACTOR_EVIDENCE_LEVEL_REGISTRY_READY_RESEARCH_ONLY"

NEXT_RECOMMENDED_MODULES = [
    "V22.011_FACTOR_COVERAGE_AND_MISSINGNESS_AUDIT",
    "V22.012_FACTOR_PREDICTIVE_VALIDITY_PANEL",
    "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT",
    "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT",
    "V22.020_DRAM_DAILY_DECISION_PANEL_R2",
    "V22.030_ETF_OPTION_UNIVERSE_REGISTRY",
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
}

DEFINITION_FIELDNAMES = [
    "evidence_level",
    "evidence_level_label",
    "description",
    "minimum_required_evidence",
    "adoption_implication",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
]

REGISTRY_FIELDNAMES = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "current_evidence_level",
    "evidence_level_label",
    "evidence_source_modules",
    "current_status",
    "forward_maturity_status",
    "regime_robustness_status",
    "coverage_status",
    "multiple_testing_risk",
    "redundancy_risk",
    "adoption_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]

STRATEGY_SUMMARY_FIELDNAMES = [
    "strategy_name",
    "strategy_group",
    "current_evidence_level",
    "current_status",
    "active_research_allowed",
    "role_review_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "primary_risk",
    "next_required_validation",
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


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    observed = output_dir.resolve()
    if observed != expected:
        raise ValueError(f"V22.010 output directory must be {expected}, got {observed}")


def evidence_definitions() -> list[dict[str, Any]]:
    rows = [
        (
            0,
            "LEVEL_0_RAW_DIAGNOSTIC",
            "Raw diagnostic, audit, or exploratory item.",
            "Item exists as a diagnostic, placeholder, or exploratory observation only.",
            "Not enough evidence for strategy use.",
        ),
        (
            1,
            "LEVEL_1_HISTORICAL_CORRELATION",
            "Historical relationship observed.",
            "Historical association or retrospective comparison exists.",
            "Research-only; no adoption eligibility.",
        ),
        (
            2,
            "LEVEL_2_PIT_LITE_BACKTEST",
            "PIT-lite or as-of constrained backtest exists.",
            "Point-in-time-lite or as-of constrained backtest evidence exists.",
            "Research-only; still not enough for official adoption.",
        ),
        (
            3,
            "LEVEL_3_RANDOM_ASOF_CONFIRMED",
            "Random as-of or random-start validation exists.",
            "Random as-of or random-start validation supports the item.",
            "Research-only; not official adoption.",
        ),
        (
            4,
            "LEVEL_4_FORWARD_5D_CONFIRMED",
            "5D forward observations matured and supportive.",
            "Supportive matured 5D forward observations exist.",
            "Research-only; requires longer forward maturity.",
        ),
        (
            5,
            "LEVEL_5_FORWARD_10D_20D_CONFIRMED",
            "10D/20D forward observations matured and supportive.",
            "Supportive matured 10D and 20D forward observations exist.",
            "Research-only; requires regime robustness.",
        ),
        (
            6,
            "LEVEL_6_REGIME_ROBUST_CONFIRMED",
            "Evidence holds across multiple regimes.",
            "Evidence remains supportive across multiple market regimes.",
            "Research-only; can be prepared for role review.",
        ),
        (
            7,
            "LEVEL_7_ROLE_REVIEW_ELIGIBLE",
            "Eligible for role review, not official adoption.",
            "Prior evidence levels plus documented role fit and risk controls.",
            "Role review eligible only; explicit future approval still required.",
        ),
        (
            8,
            "LEVEL_8_OFFICIAL_ADOPTION_CANDIDATE",
            "Candidate only; official adoption still requires explicit future approval.",
            "Role review evidence supports candidate status.",
            "Candidate only; official adoption remains blocked in V22.010.",
        ),
    ]
    return [
        {
            "evidence_level": level,
            "evidence_level_label": label,
            "description": description,
            "minimum_required_evidence": minimum,
            "adoption_implication": implication,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "trade_allowed": False,
        }
        for level, label, description, minimum, implication in rows
    ]


def level_label(level: int) -> str:
    labels = {int(row["evidence_level"]): str(row["evidence_level_label"]) for row in evidence_definitions()}
    return labels[level]


def registry_row(
    item_id: str,
    item_name: str,
    item_type: str,
    family: str,
    level: int,
    evidence_source_modules: str,
    current_status: str,
    forward_maturity_status: str,
    regime_robustness_status: str,
    coverage_status: str,
    multiple_testing_risk: str,
    redundancy_risk: str,
    adoption_eligible: bool,
    next_required_validation: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "item_name": item_name,
        "item_type": item_type,
        "family": family,
        "current_evidence_level": level,
        "evidence_level_label": level_label(level),
        "evidence_source_modules": evidence_source_modules,
        "current_status": current_status,
        "forward_maturity_status": forward_maturity_status,
        "regime_robustness_status": regime_robustness_status,
        "coverage_status": coverage_status,
        "multiple_testing_risk": multiple_testing_risk,
        "redundancy_risk": redundancy_risk,
        "adoption_eligible": adoption_eligible,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": next_required_validation,
        "reason": reason,
    }


def registry_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(strategy_rows())
    rows.extend(dram_rows())
    rows.extend(factor_family_rows())
    rows.extend(technical_subfactor_rows())
    rows.extend(etf_option_placeholder_rows())
    return rows


def strategy_rows() -> list[dict[str, Any]]:
    specs = [
        ("A1_CONTROL", "A1 Control", 1, "BASELINE_CONTROL", "Historical baseline/control reference; not an adoption candidate.", "LOW", "LOW", False),
        ("B_STATIC_MOMENTUM_BLEND", "B Static Momentum Blend", 2, "ACTIVE_RESEARCH", "PIT-lite evidence exists, but forward and regime confirmation remain incomplete.", "MEDIUM", "MEDIUM", False),
        ("C_DYNAMIC_MOMENTUM_BLEND", "C Dynamic Momentum Blend", 2, "ACTIVE_RESEARCH", "PIT-lite evidence exists with dynamic blend complexity; more validation required.", "MEDIUM", "HIGH", False),
        ("D_WEIGHT_OPTIMIZED_R1", "D Weight Optimized R1", 3, "ACTIVE_RESEARCH", "Random/as-of style validation is stronger than raw backtest but remains research-only.", "HIGH", "HIGH", False),
        ("E_R1", "E R1", 3, "ACTIVE_RESEARCH", "Strategy variant has research support but lacks matured forward and regime robustness.", "MEDIUM", "MEDIUM", False),
        ("E_R2_CONSERVATIVE_DEFENSIVE_RETURN", "E R2 Conservative Defensive Return", 3, "ACTIVE_RESEARCH", "Conservative defensive return variant remains research-only pending forward confirmation.", "MEDIUM", "MEDIUM", False),
        ("E_R3_QUALITY_RISK_REPAIR_BASE", "E R3 Quality Risk Repair Base", 4, "PROMISING_RESEARCH", "Quality/risk repair base is stronger than raw diagnostic but not eligible for official adoption.", "MEDIUM", "MEDIUM", False),
        ("NEW_FACTOR_LITE", "New Factor Lite", 2, "PROMISING_RESEARCH_HIGH_FDR_RISK", "Promising factor-lite item, but multiple-testing risk remains high until forward-only confirmation matures.", "HIGH", "MEDIUM", False),
        ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "New Factor Lite Repeated Loser Left Tail", 2, "PROMISING_RESEARCH_HIGH_FDR_RISK", "Promising left-tail repair concept; high multiple-testing risk blocks adoption eligibility.", "HIGH", "MEDIUM", False),
        ("ABCDE_MOOMOO_ONLY_RERUN", "ABCDE Moomoo-only Rerun", 1, "HISTORICAL_ARCHIVE_REFERENCE", "Historical rerun/reference only; not active official adoption.", "MEDIUM", "MEDIUM", False),
    ]
    return [
        registry_row(
            item_id=item_id,
            item_name=item_name,
            item_type="STRATEGY_RANKING_SYSTEM",
            family="STRATEGY",
            level=level,
            evidence_source_modules="V21.233;V21.234;V21.255;V22.002",
            current_status=status,
            forward_maturity_status="PARTIAL_OR_PENDING",
            regime_robustness_status="NOT_CONFIRMED",
            coverage_status="V21_OUTPUT_REFERENCE_ONLY",
            multiple_testing_risk=multiple_testing_risk,
            redundancy_risk=redundancy_risk,
            adoption_eligible=adoption_eligible,
            next_required_validation="V22.012 predictive validity panel plus V22.014 false-discovery audit.",
            reason=reason,
        )
        for item_id, item_name, level, status, reason, multiple_testing_risk, redundancy_risk, adoption_eligible in specs
    ]


def dram_rows() -> list[dict[str, Any]]:
    specs = [
        ("DRAM_DAILY_PLAN", "DRAM Daily Plan", 2, "ACTIVE_RESEARCH", "Daily plan is active research only; broker action and trading remain blocked."),
        ("DRAM_INTRADAY_TRIGGER", "DRAM Intraday Trigger", 1, "RAW_TRIGGER_RESEARCH", "Intraday trigger research lacks sufficient forward and regime confirmation."),
        ("DRAM_NO_TRADE_GATE", "DRAM No Trade Gate", 2, "RISK_GATE_RESEARCH", "No-trade gate is useful research governance but not an execution approval."),
        ("DRAM_FORWARD_OUTCOME_TRACKING", "DRAM Forward Outcome Tracking", 3, "FORWARD_TRACKING_RESEARCH", "Forward tracking supports research review but remains insufficient for adoption."),
    ]
    return [
        registry_row(
            item_id=item_id,
            item_name=item_name,
            item_type="DRAM_SYSTEM",
            family="DRAM",
            level=level,
            evidence_source_modules="V21.201;V21.232;V22.002",
            current_status=status,
            forward_maturity_status="PARTIAL_OR_PENDING",
            regime_robustness_status="NOT_CONFIRMED",
            coverage_status="DRAM_OUTPUT_REFERENCE_ONLY",
            multiple_testing_risk="MEDIUM",
            redundancy_risk="MEDIUM",
            adoption_eligible=False,
            next_required_validation="V22.020 DRAM daily decision panel R2 and forward outcome audit.",
            reason=reason,
        )
        for item_id, item_name, level, status, reason in specs
    ]


def factor_family_rows() -> list[dict[str, Any]]:
    specs = [
        ("FUNDAMENTAL", "Fundamental", 1, "FAMILY_RESEARCH"),
        ("TECHNICAL", "Technical", 2, "MIXED_SIGNAL"),
        ("STRATEGY", "Strategy", 2, "FAMILY_RESEARCH"),
        ("RISK", "Risk", 2, "RISK_RESEARCH"),
        ("MARKET_REGIME", "Market Regime", 1, "REGIME_RESEARCH_INCOMPLETE"),
        ("DATA_TRUST", "Data Trust", 2, "GOVERNANCE_RESEARCH"),
    ]
    return [
        registry_row(
            item_id=item_id,
            item_name=item_name,
            item_type="FACTOR_FAMILY",
            family=item_id,
            level=level,
            evidence_source_modules="V21.246;V21.247;V21.255;V22.002",
            current_status=status,
            forward_maturity_status="PENDING",
            regime_robustness_status="NOT_CONFIRMED",
            coverage_status="FAMILY_LEVEL_REFERENCE",
            multiple_testing_risk="MEDIUM",
            redundancy_risk="MEDIUM",
            adoption_eligible=False,
            next_required_validation="V22.011 coverage audit and V22.013 redundancy cluster audit.",
            reason="Family-level registry item; adoption requires subfactor coverage, predictive validity, and redundancy review.",
        )
        for item_id, item_name, level, status in specs
    ]


def technical_subfactor_rows() -> list[dict[str, Any]]:
    item_ids = [
        "RSI",
        "KDJ",
        "MACD",
        "BOLLINGER_BAND_7_LINE",
        "MA20",
        "MA50",
        "EMA",
        "VOLUME",
        "VOLATILITY",
        "MOMENTUM",
        "RELATIVE_STRENGTH",
        "BREAKOUT",
        "PULLBACK",
    ]
    return [
        registry_row(
            item_id=item_id,
            item_name=item_id.title().replace("_", " "),
            item_type="TECHNICAL_SUBFACTOR",
            family="TECHNICAL",
            level=2,
            evidence_source_modules="V21.247_TECHNICAL_SUBFACTOR_EFFECTIVENESS_PIT_LITE_AUDIT;V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1",
            current_status="MIXED_SIGNAL",
            forward_maturity_status="INSUFFICIENT_OR_MIXED",
            regime_robustness_status="NOT_CONFIRMED",
            coverage_status="PIT_LITE_REFERENCE_PRESENT",
            multiple_testing_risk="HIGH",
            redundancy_risk="HIGH",
            adoption_eligible=False,
            next_required_validation="V22.012 predictive validity panel plus V22.013 redundancy and V22.014 false-discovery audits.",
            reason="V21.247 technical subfactor effectiveness was mixed; not adoption eligible in V22.010.",
        )
        for item_id in item_ids
    ]


def etf_option_placeholder_rows() -> list[dict[str, Any]]:
    specs = [
        ("ETF_OPTION_LONG_CALL", "ETF Option Long Call"),
        ("ETF_OPTION_LONG_PUT", "ETF Option Long Put"),
        ("ETF_OPTION_DEBIT_CALL_SPREAD", "ETF Option Debit Call Spread"),
        ("ETF_OPTION_DEBIT_PUT_SPREAD", "ETF Option Debit Put Spread"),
        ("ETF_OPTION_LONG_STRADDLE_RESEARCH", "ETF Option Long Straddle Research"),
        ("ETF_OPTION_LONG_STRANGLE_RESEARCH", "ETF Option Long Strangle Research"),
    ]
    return [
        registry_row(
            item_id=item_id,
            item_name=item_name,
            item_type="ETF_OPTION_PLACEHOLDER",
            family="ETF_OPTIONS",
            level=0,
            evidence_source_modules="V22.000_SCOPE_ONLY",
            current_status="PLACEHOLDER_NO_CHAIN_INGESTION",
            forward_maturity_status="NO_FORWARD_EVIDENCE",
            regime_robustness_status="NOT_TESTED",
            coverage_status="NO_OPTION_CHAIN_COVERAGE_IN_V22_010",
            multiple_testing_risk="HIGH",
            redundancy_risk="UNKNOWN",
            adoption_eligible=False,
            next_required_validation="V22.030 universe registry and later option-chain coverage audit before any evidence promotion.",
            reason="ETF option research placeholder only; no option-chain ingestion or forward evidence exists yet.",
        )
        for item_id, item_name in specs
    ]


def strategy_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_types = {"STRATEGY_RANKING_SYSTEM", "DRAM_SYSTEM", "ETF_OPTION_PLACEHOLDER"}
    summary_rows: list[dict[str, Any]] = []
    for row in rows:
        if row["item_type"] not in strategy_types:
            continue
        summary_rows.append(
            {
                "strategy_name": row["item_id"],
                "strategy_group": row["item_type"],
                "current_evidence_level": row["current_evidence_level"],
                "current_status": row["current_status"],
                "active_research_allowed": True,
                "role_review_eligible": int(row["current_evidence_level"]) >= 7,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "primary_risk": row["multiple_testing_risk"],
                "next_required_validation": row["next_required_validation"],
            }
        )
    return summary_rows


def summary_payload(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "stage": STAGE,
        "freeze_date": FREEZE_DATE,
        "final_status": FINAL_STATUS,
        "final_decision": FINAL_DECISION,
        "evidence_level_count": len(evidence_definitions()),
        "registered_item_count": len(rows),
        "strategy_item_count": sum(1 for row in rows if row["item_type"] == "STRATEGY_RANKING_SYSTEM"),
        "factor_family_item_count": sum(1 for row in rows if row["item_type"] == "FACTOR_FAMILY"),
        "technical_subfactor_item_count": sum(1 for row in rows if row["item_type"] == "TECHNICAL_SUBFACTOR"),
        "dram_item_count": sum(1 for row in rows if row["item_type"] == "DRAM_SYSTEM"),
        "etf_option_placeholder_count": sum(1 for row in rows if row["item_type"] == "ETF_OPTION_PLACEHOLDER"),
        "adoption_eligible_count": sum(1 for row in rows if row["adoption_eligible"] is True),
        "official_adoption_allowed_count": sum(1 for row in rows if row["official_adoption_allowed"] is True),
        "broker_action_allowed_count": sum(1 for row in rows if row["broker_action_allowed"] is True),
        "trade_allowed_count": sum(1 for row in rows if row["trade_allowed"] is True),
        "protected_outputs_modified": False,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        "output_dir": str(output_dir),
        **NO_ACTION_GATES,
    }


def risk_gate_payload() -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "allowed_side_effects": ["create_outputs_v22_010_only"],
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
        "V22.010 Factor Evidence Level Registry",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        "evidence_levels=" + ";".join(row["evidence_level_label"] for row in evidence_definitions()),
        f"registered_item_count={summary['registered_item_count']}",
        f"strategy_item_count={summary['strategy_item_count']}",
        f"factor_family_item_count={summary['factor_family_item_count']}",
        f"technical_subfactor_item_count={summary['technical_subfactor_item_count']}",
        f"dram_item_count={summary['dram_item_count']}",
        f"etf_option_placeholder_count={summary['etf_option_placeholder_count']}",
        f"adoption_eligible_count={summary['adoption_eligible_count']}",
        "official_adoption_blocked_reason=V22.010 is a research-only registry; even LEVEL_8 remains candidate-only pending explicit future approval.",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
        "market_data_fetch_allowed=False",
        "moomoo_connection_allowed=False",
        "option_chain_fetch_allowed=False",
        "daily_chain_execution_allowed=False",
        "historical_outputs_mutation_allowed=False",
        "cache_mutation_allowed=False",
        "protected_outputs_modified=False",
        "next_recommended_modules=" + ";".join(summary["next_recommended_modules"]),
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    definitions = evidence_definitions()
    rows = registry_rows()
    summary = summary_payload(output_dir, rows)

    write_csv(output_dir / "v22_factor_evidence_level_registry.csv", REGISTRY_FIELDNAMES, rows)
    write_csv(output_dir / "v22_factor_evidence_level_definitions.csv", DEFINITION_FIELDNAMES, definitions)
    write_csv(output_dir / "v22_strategy_evidence_summary.csv", STRATEGY_SUMMARY_FIELDNAMES, strategy_summary_rows(rows))
    write_json(output_dir / "v22_factor_evidence_registry_summary.json", summary)
    write_json(output_dir / "v22_factor_evidence_registry_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.010_factor_evidence_level_registry_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_factor_evidence_registry_summary.json'}")
    print("official_adoption_allowed_count=0")
    print("broker_action_allowed_count=0")
    print("trade_allowed_count=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
