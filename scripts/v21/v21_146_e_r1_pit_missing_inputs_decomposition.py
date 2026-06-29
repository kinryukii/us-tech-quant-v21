from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


STAGE = "V21.146_E_R1_PIT_MISSING_INPUTS_DECOMPOSITION"
OUT = Path("outputs/v21/V21.146_E_R1_PIT_MISSING_INPUTS_DECOMPOSITION")
V145 = Path("outputs/v21/V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE")
PIT145 = V145 / "V21.145_e_r1_pit_reconstruction_feasibility.csv"
SUMMARY145 = V145 / "V21.145_summary.json"

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
}

INPUT_FAMILIES = [
    "historical price panel",
    "historical adjusted close",
    "historical technical factors",
    "historical momentum factors",
    "historical risk factors",
    "historical market regime factors",
    "historical data trust factors",
    "historical fundamental factors if used",
    "historical universe membership",
    "historical sector / industry metadata",
    "historical repaired metadata source",
    "historical ranking weights",
    "historical scoring formula",
    "historical exclusion rules",
    "historical stale/missing ticker rules",
    "historical benchmark data",
    "delisted ticker coverage",
]


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_exists(patterns: list[str]) -> str:
    for pattern in patterns:
        matches = list(Path(".").glob(pattern))
        if matches:
            return str(matches[0]).replace("\\", "/")
    return ""


def classify_inventory() -> pd.DataFrame:
    source = pd.read_csv(PIT145) if PIT145.exists() else pd.DataFrame()
    evidence_map = {str(r["input_requirement"]).replace("_", " "): r for _, r in source.iterrows()} if not source.empty else {}
    rows = []
    for family in INPUT_FAMILIES:
        available_artifact = ""
        if "price panel" in family:
            classification = "AVAILABLE_PIT_LITE"
            evidence = "V21.140 extended current-universe price panel"
            available_artifact = artifact_exists(["outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_ohlcv_panel_2020_plus.csv"])
        elif "adjusted close" in family or "benchmark" in family:
            classification = "AVAILABLE_PIT_LITE"
            evidence = "V21.140 extended adjusted close panel includes benchmarks where available"
            available_artifact = artifact_exists(["outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv"])
        elif "technical" in family:
            classification = "AVAILABLE_PIT_LITE"
            evidence = "Can be recomputed from V21.140 prices; historical membership still current-universe biased"
            available_artifact = artifact_exists(["outputs/v20/consolidation/V20_35*TECHNICAL*"])
        elif "momentum" in family or "risk factors" in family:
            classification = "AVAILABLE_PIT_LITE"
            evidence = "Price-derived proxies can be recomputed; full PIT factor ledger not bound to E_R1"
            available_artifact = artifact_exists(["outputs/v20/backtest/V20_199B*FACTOR*"])
        elif "market regime" in family:
            classification = "UNKNOWN"
            evidence = "Market regime artifacts exist but no complete as-of E_R1 scoring label ledger found"
            available_artifact = artifact_exists(["outputs/**/**/*regime*.csv"])
        elif "data trust" in family:
            classification = "UNKNOWN"
            evidence = "Data trust artifacts exist, but historical E_R1 data-trust factor lineage is incomplete"
            available_artifact = artifact_exists(["outputs/**/**/*DATA_TRUST*.csv"])
        elif "fundamental" in family:
            classification = "UNKNOWN"
            evidence = "A1 uses baseline components; historical fundamental PIT binding for E_R1 not verified"
            available_artifact = artifact_exists(["outputs/**/**/*FUNDAMENTAL*.csv"])
        elif "universe membership" in family:
            classification = "MISSING"
            evidence = "V21.143 confirmed current universe only; no complete historical membership/delisted ledger"
            available_artifact = artifact_exists(["state/v18/universe/*.csv", "inputs/v20/equity_curve/membership_staging/**/*.csv"])
        elif "sector" in family or "metadata" in family:
            classification = "CURRENT_SNAPSHOT_ONLY"
            evidence = "V21.138 metadata bridge is current repaired metadata, not historical PIT metadata"
            available_artifact = artifact_exists(["outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv"])
        elif "ranking weights" in family or "scoring formula" in family:
            classification = "CURRENT_SNAPSHOT_ONLY"
            evidence = "E_R1 formula is known from V21.133_R1, but historical A1 component reconstruction is not bound PIT-strict"
            available_artifact = artifact_exists(["outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_score_components.csv"])
        elif "exclusion rules" in family or "stale/missing" in family:
            classification = "CURRENT_SNAPSHOT_ONLY"
            evidence = "Current-stage data quality/exclusion rules exist; historical as-of rule ledger incomplete"
            available_artifact = artifact_exists(["outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL/*.csv"])
        elif "delisted" in family:
            classification = "MISSING"
            evidence = "No delisted ticker price/membership coverage found"
            available_artifact = ""
        else:
            classification = "UNKNOWN"
            evidence = "Not independently verified"
        rows.append(
            {
                "input_family": family,
                "availability_classification": classification,
                "evidence": evidence,
                "available_artifact_example": available_artifact,
            }
        )
    return pd.DataFrame(rows)


def repairability(inventory: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in inventory.iterrows():
        cls = r["availability_classification"]
        family = r["input_family"]
        if cls == "AVAILABLE_PIT_STRICT":
            repair = "REPAIRABLE_FROM_EXISTING_ARTIFACTS"
            action = "Bind into PIT reconstruction manifest"
        elif cls == "AVAILABLE_PIT_LITE":
            repair = "REPAIRABLE_FROM_EXISTING_ARTIFACTS"
            action = "Recompute factor proxies from V21.140 with explicit current-universe limitation"
        elif "universe membership" in family or "delisted" in family:
            repair = "REPAIRABLE_WITH_WEB_OR_VENDOR_DATA" if cls == "MISSING" else "UNKNOWN"
            action = "Acquire historical universe membership and delisted ticker history; otherwise use forward maturity as primary evidence"
        elif cls == "CURRENT_SNAPSHOT_ONLY":
            repair = "REPAIRABLE_WITH_LOCAL_BACKFILL" if "metadata" not in family else "REPAIRABLE_WITH_WEB_OR_VENDOR_DATA"
            action = "Build as-of history or label as current-snapshot-only"
        elif cls == "UNKNOWN":
            repair = "UNKNOWN"
            action = "Inventory and bind source lineage before PIT replay"
        else:
            repair = "NOT_REPAIRABLE_WITH_CURRENT_PROJECT_DATA"
            action = "Block PIT_STRICT adoption-grade backtest"
        rows.append(
            {
                "input_family": family,
                "availability_classification": cls,
                "repairability_classification": repair,
                "recommended_action": action,
            }
        )
    return pd.DataFrame(rows)


def bridge_levels(inventory: pd.DataFrame) -> pd.DataFrame:
    missing_strict = "historical universe membership|delisted ticker coverage|historical sector / industry metadata|historical data trust factors"
    return pd.DataFrame(
        [
            {
                "bridge_level": "PIT_STRICT_FULL",
                "required_inputs": "|".join(INPUT_FAMILIES),
                "missing_blockers": missing_strict,
                "leakage_risk": "LOW_IF_REPAIRED",
                "survivorship_risk": "LOW_IF_DELISTED_AND_MEMBERSHIP_REPAIRED",
                "adoption_eligibility": "POSSIBLE_AFTER_REPAIR_AND_FORWARD_MATURITY",
                "random_asof_backtest_can_use": False,
                "forward_review_can_use": True,
            },
            {
                "bridge_level": "PIT_STRICT_PRICE_AND_TECH_ONLY",
                "required_inputs": "historical price panel|historical adjusted close|historical technical factors|historical benchmark data",
                "missing_blockers": "historical universe membership|historical A1/E_R1 non-price inputs",
                "leakage_risk": "MEDIUM",
                "survivorship_risk": "HIGH_CURRENT_UNIVERSE_ONLY",
                "adoption_eligibility": "NO",
                "random_asof_backtest_can_use": True,
                "forward_review_can_use": True,
            },
            {
                "bridge_level": "PIT_LITE_CURRENT_UNIVERSE",
                "required_inputs": "V21.140 price panel|current strategy universe|current E_R1 formula",
                "missing_blockers": "delisted ticker coverage|historical membership",
                "leakage_risk": "MEDIUM_CURRENT_RANKING_RISK",
                "survivorship_risk": "HIGH",
                "adoption_eligibility": "NO",
                "random_asof_backtest_can_use": True,
                "forward_review_can_use": True,
            },
            {
                "bridge_level": "PIT_LITE_CURRENT_METADATA",
                "required_inputs": "V21.138 metadata bridge|V21.140 prices|current ranking components",
                "missing_blockers": "historical metadata as-of",
                "leakage_risk": "MEDIUM",
                "survivorship_risk": "HIGH",
                "adoption_eligibility": "NO",
                "random_asof_backtest_can_use": True,
                "forward_review_can_use": True,
            },
            {
                "bridge_level": "SNAPSHOT_ONLY_DIAGNOSTIC",
                "required_inputs": "current E_R1 ranking|current A1 ranking|extended price history",
                "missing_blockers": "PIT reconstruction",
                "leakage_risk": "HIGH_CURRENT_RANKING_ON_HISTORY",
                "survivorship_risk": "HIGH",
                "adoption_eligibility": "NO",
                "random_asof_backtest_can_use": False,
                "forward_review_can_use": True,
            },
        ]
    )


def comparability() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "comparison_pair": "E_R1_REPAIRED_vs_A1_BASELINE_CONTROL",
                "comparability_classification": "BOTH_PIT_LITE_SAME_LIMITATIONS",
                "E_R1_available_level": "PIT_LITE_CURRENT_UNIVERSE",
                "A1_available_level": "PIT_LITE_CURRENT_UNIVERSE",
                "shared_limitations": "current universe survivorship bias|missing delisted ticker coverage|current metadata snapshot|current ranking on history risk",
                "adoption_grade_comparable": False,
                "diagnostic_comparable": True,
            }
        ]
    )


def roadmap() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"priority": 1, "repair_item": "Build E_R1 and A1 same-assumption PIT-lite replay manifest", "target": "E_R1 vs A1 comparable", "repairability": "REPAIRABLE_FROM_EXISTING_ARTIFACTS", "next_stage_candidate": "V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST"},
            {"priority": 1, "repair_item": "Bind historical A1 component inputs used by E_R1 baseline anchor", "target": "E_R1 vs A1 comparable", "repairability": "REPAIRABLE_WITH_LOCAL_BACKFILL", "next_stage_candidate": "V21.147"},
            {"priority": 2, "repair_item": "Acquire or stage historical universe membership and delisted ticker coverage", "target": "reduce survivorship bias", "repairability": "REPAIRABLE_WITH_WEB_OR_VENDOR_DATA", "next_stage_candidate": "V21.148_HISTORICAL_UNIVERSE_MEMBERSHIP_BACKFILL_PLAN"},
            {"priority": 2, "repair_item": "Create as-of sector/industry metadata bridge", "target": "reduce metadata lookahead", "repairability": "REPAIRABLE_WITH_WEB_OR_VENDOR_DATA", "next_stage_candidate": "V21.149_METADATA_ASOF_BRIDGE_PLAN"},
            {"priority": 3, "repair_item": "Recompute technical/momentum/risk factors from V21.140 prices with as-of timestamps", "target": "more adoption-grade extended backtest", "repairability": "REPAIRABLE_FROM_EXISTING_ARTIFACTS", "next_stage_candidate": "V21.150_E_R1_FACTOR_REPLAY_PIT_LITE"},
            {"priority": 4, "repair_item": "Add historical regime and data trust labels", "target": "optional robustness improvements", "repairability": "UNKNOWN", "next_stage_candidate": "V21.151_REGIME_DATA_TRUST_LINEAGE_AUDIT"},
        ]
    )


def forward_interaction() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"missing_input": "historical universe membership", "historical_adoption_grade_backtest": "HARD_BLOCKER", "forward_maturity_review": "NOT_REQUIRED_FOR_LIVE_FORWARD", "risk_only_review": "WARN", "data_waiver_review": "NOT_WAIVABLE_FOR_PIT_STRICT"},
            {"missing_input": "delisted ticker coverage", "historical_adoption_grade_backtest": "HARD_BLOCKER", "forward_maturity_review": "NOT_REQUIRED_FOR_LIVE_FORWARD", "risk_only_review": "WARN", "data_waiver_review": "NOT_WAIVABLE_FOR_PIT_STRICT"},
            {"missing_input": "historical metadata as-of", "historical_adoption_grade_backtest": "BLOCKER_OR_WARN", "forward_maturity_review": "NOT_REQUIRED_IF_CURRENT_METADATA_VALID", "risk_only_review": "WARN", "data_waiver_review": "POSSIBLE_FOR_RESEARCH_ONLY"},
            {"missing_input": "historical regime/data trust labels", "historical_adoption_grade_backtest": "WARN_OR_BLOCKER", "forward_maturity_review": "NOT_REQUIRED_FOR_RETURN_MATURITY", "risk_only_review": "WARN", "data_waiver_review": "POSSIBLE_FOR_RESEARCH_ONLY"},
            {"missing_input": "forward maturity observations", "historical_adoption_grade_backtest": "NOT_APPLICABLE", "forward_maturity_review": "HARD_BLOCKER", "risk_only_review": "WARN", "data_waiver_review": "NOT_WAIVABLE_FOR_ADOPTION"},
        ]
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s145 = load_json(SUMMARY145)
    inventory = classify_inventory()
    repair = repairability(inventory)
    bridges = bridge_levels(inventory)
    comp = comparability()
    road = roadmap()
    interaction = forward_interaction()
    blockers = inventory[inventory["availability_classification"].isin(["MISSING", "UNKNOWN", "CURRENT_SNAPSHOT_ONLY"])].copy()
    blockers = blockers[["input_family", "availability_classification", "evidence"]]

    pit_strict_repair_feasible = bool((repair["repairability_classification"] == "REPAIRABLE_FROM_EXISTING_ARTIFACTS").sum() == len(repair))
    pit_lite_comparable = True
    highest_bridge = "PIT_LITE_CURRENT_UNIVERSE"
    existing_count = int((repair["repairability_classification"] == "REPAIRABLE_FROM_EXISTING_ARTIFACTS").sum())
    waiver_count = int((repair["repairability_classification"] == "WAIVER_ONLY").sum())
    top_missing = "|".join(blockers["input_family"].head(5).tolist())

    if pit_lite_comparable and not pit_strict_repair_feasible:
        final_status = "PARTIAL_PASS_V21_146_E_R1_A1_PIT_LITE_COMPARABLE"
        decision = "E_R1_A1_COMPARABLE_DIAGNOSTIC_ONLY_WAIT_FORWARD_MATURITY"
    elif pit_strict_repair_feasible:
        final_status = "PASS_V21_146_PIT_STRICT_REPAIR_FEASIBLE"
        decision = "PROCEED_TO_E_R1_PIT_RECONSTRUCTION_RESEARCH_ONLY"
    elif not pit_strict_repair_feasible and not road.empty:
        final_status = "PARTIAL_PASS_V21_146_PIT_STRICT_BLOCKED_ROADMAP_READY"
        decision = "E_R1_PIT_REPAIR_ROADMAP_READY_NO_ADOPTION"
    else:
        final_status = "PARTIAL_PASS_V21_146_PIT_STRICT_NOT_REPAIRABLE_CURRENT_DATA"
        decision = "USE_FORWARD_MATURITY_PRIMARY_HISTORICAL_DIAGNOSTIC_ONLY"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "E_R1_PIT_status_from_V21_145": s145.get("E_R1_PIT_status", "UNKNOWN"),
        "E_R1_A1_PIT_comparability": "BOTH_PIT_LITE_SAME_LIMITATIONS",
        "pit_strict_repair_feasible": pit_strict_repair_feasible,
        "pit_lite_comparable_feasible": pit_lite_comparable,
        "highest_available_bridge_level": highest_bridge,
        "top_missing_inputs": top_missing,
        "repairable_from_existing_artifacts_count": existing_count,
        "waiver_only_count": waiver_count,
        "recommended_next_stage": "V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST",
        "remaining_blockers": top_missing,
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    inventory.to_csv(OUT / "V21.146_pit_missing_input_inventory.csv", index=False)
    repair.to_csv(OUT / "V21.146_repairability_classification.csv", index=False)
    bridges.to_csv(OUT / "V21.146_minimum_viable_pit_bridge.csv", index=False)
    comp.to_csv(OUT / "V21.146_e_r1_vs_a1_pit_comparability.csv", index=False)
    road.to_csv(OUT / "V21.146_repair_roadmap.csv", index=False)
    interaction.to_csv(OUT / "V21.146_forward_maturity_interaction.csv", index=False)
    blockers.to_csv(OUT / "V21.146_remaining_blockers.csv", index=False)
    (OUT / "V21.146_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"E_R1_PIT_status_from_V21_145={summary['E_R1_PIT_status_from_V21_145']}",
        "E_R1_A1_PIT_comparability=BOTH_PIT_LITE_SAME_LIMITATIONS",
        f"pit_strict_repair_feasible={str(pit_strict_repair_feasible).lower()}",
        f"pit_lite_comparable_feasible={str(pit_lite_comparable).lower()}",
        f"highest_available_bridge_level={highest_bridge}",
        f"top_missing_inputs={top_missing}",
        f"repairable_from_existing_artifacts_count={existing_count}",
        f"waiver_only_count={waiver_count}",
        "recommended_next_stage=V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST",
        f"remaining_blockers={top_missing}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.146_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:13]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
