from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


STAGE = "V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST"
OUT = Path("outputs/v21/V21.147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST")
PRICE_PANEL = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "strategy_adoption_allowed": False,
    "replay_execution_allowed": False,
    "pit_strict_claim_allowed": False,
}


def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mtime(path: Path) -> str:
    if not path.exists():
        return ""
    return pd.Timestamp(path.stat().st_mtime, unit="s").isoformat()


def input_row(path: str, role: str, usage: str, leakage: str, survivorship: str, notes: str) -> dict:
    p = Path(path)
    return {
        "path": path,
        "input_role": role,
        "exists": p.exists(),
        "sha256": sha256(p),
        "latest_timestamp": mtime(p),
        "allowed_usage": usage,
        "leakage_risk": leakage,
        "survivorship_risk": survivorship,
        "notes": notes,
    }


def date_rules() -> tuple[pd.DataFrame, dict]:
    prices = pd.read_csv(PRICE_PANEL, usecols=["date"])
    dates = pd.to_datetime(prices["date"]).sort_values().drop_duplicates().reset_index(drop=True)
    earliest = str(dates.iloc[0].date())
    latest = {}
    for h in [5, 10, 20]:
        latest[f"latest_possible_asof_date_{h}D"] = str(dates.iloc[-(h + 1)].date())
    rows = []
    for h in [5, 10, 20]:
        rows.append(
            {
                "rule_name": f"{h}D_sampling",
                "earliest_possible_asof_date": earliest,
                "latest_possible_asof_date": latest[f"latest_possible_asof_date_{h}D"],
                "required_future_price_buffer_trading_days": h,
                "allowed_horizon": f"{h}D",
                "allowed_portfolio_sizes": "Top20|Top50",
                "minimum_valid_holdings_top20": 15,
                "minimum_valid_holdings_top50": 35,
                "regime_buckets_available": "2020|2021|2022|2023-2024|2025-2026",
                "regime_labels_source": "CALENDAR_PROXY_ONLY",
            }
        )
    return pd.DataFrame(rows), {"earliest": earliest, **latest}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scope = pd.DataFrame(
        [
            {
                "replay_target": "E_R1_REPAIRED vs A1_BASELINE_CONTROL",
                "bridge_level": "PIT_LITE_CURRENT_UNIVERSE",
                "replay_purpose": "diagnostic-only comparable replay",
                "adoption_eligibility": False,
                "PIT_STRICT_eligibility": False,
                "allowed_interpretation": "same-limitation diagnostic comparison only",
            }
        ]
    )
    allowed = pd.DataFrame(
        [
            input_row("outputs/v21/V21.146_E_R1_PIT_MISSING_INPUTS_DECOMPOSITION/V21.146_summary.json", "REQUIRED", "bridge constraints and comparability decision", "LOW", "DOCUMENTED_HIGH", "Defines highest available bridge level"),
            input_row("outputs/v21/V21.145_E_R1_FORWARD_MATURITY_AND_PIT_BRIDGE/V21.145_summary.json", "AUDIT_ONLY", "forward maturity and PIT blocker status", "LOW", "NONE", "Carry blocker context"),
            input_row("outputs/v21/V21.144_FAIR_BASELINE_EXTENDED_STRATEGY_RETEST/V21.144_summary.json", "AUDIT_ONLY", "fair-baseline diagnostic evidence", "LOW", "DOCUMENTED_HIGH", "Historical support only"),
            input_row("outputs/v21/V21.143_RANDOM_UNIVERSE_AND_SURVIVORSHIP_ARTIFACT_AUDIT/V21.143_summary.json", "AUDIT_ONLY", "survivorship and fair-baseline warning context", "LOW", "DOCUMENTED_HIGH", "Do not treat as adoption grade"),
            input_row("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv", "REQUIRED", "close-to-close returns and price-derived factors only", "MEDIUM_IF_USED_FOR_RANKING_WITH_FUTURE_VALUES", "HIGH_CURRENT_UNIVERSE_ONLY", "Use only values <= replay as-of date for ranking"),
            input_row("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv", "REQUIRED", "current E_R1 formula/component schema and latest membership reference only", "HIGH_IF_USED_AS_HISTORICAL_RANKING", "HIGH_CURRENT_SNAPSHOT", "Must not be used as historical membership"),
            input_row("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv", "REQUIRED", "A1 component schema and latest control reference only", "HIGH_IF_USED_AS_HISTORICAL_RANKING", "HIGH_CURRENT_SNAPSHOT", "Must not be used as historical ranking"),
            input_row("outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT/consolidated_sector_industry_metadata_bridge.csv", "METADATA_ONLY", "current metadata labels for diagnostics only", "MEDIUM_CURRENT_METADATA_LOOKAHEAD", "HIGH_CURRENT_SNAPSHOT", "Do not present as historical metadata"),
            input_row("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_benchmark_coverage_report.csv", "BENCHMARK_ONLY", "benchmark coverage validation", "LOW", "NONE", "QQQ/SOXX/SPY/SMH/XLK coverage"),
        ]
    )
    forbidden = pd.DataFrame(
        [
            {"forbidden_input": "future ranking outputs after replay as-of date", "reason": "ranking leakage", "enforcement": "reject from replay ranking construction"},
            {"forbidden_input": "future factor values", "reason": "factor leakage", "enforcement": "use only rows <= as-of date"},
            {"forbidden_input": "future benchmark returns for ranking", "reason": "outcome leakage", "enforcement": "benchmark returns only evaluation columns"},
            {"forbidden_input": "future price exits when constructing rankings", "reason": "forward return leakage", "enforcement": "exit prices evaluation only"},
            {"forbidden_input": "current metadata as historical metadata", "reason": "metadata lookahead", "enforcement": "label current metadata diagnostic-only"},
            {"forbidden_input": "current universe as historical universe", "reason": "survivorship bias", "enforcement": "PIT_LITE label required"},
            {"forbidden_input": "delisted ticker assumptions not present in data", "reason": "fabrication risk", "enforcement": "do not synthesize delisted rows"},
            {"forbidden_input": "broker/action files", "reason": "research-only stage", "enforcement": "read/write forbidden"},
            {"forbidden_input": "official adoption decision files", "reason": "no adoption authority", "enforcement": "read-only audit context at most"},
        ]
    )
    dates, date_meta = date_rules()
    assumptions = pd.DataFrame(
        [
            {"strategy": "A1_BASELINE_CONTROL", "formula_or_weights": "A1 current baseline formula from V21.128", "factor_families_used": "baseline score components", "historically_reconstructable_factors": "price-derived technical/momentum proxies", "pit_lite_approximations": "current universe; current formula schema", "snapshot_only_factors": "current metadata/data trust if used", "identical_limitations": True, "missing_factor_handling": "neutral or exclude with audit", "exclusion_rules": "minimum valid price history; no future data", "stale_price_rules": "as-of close must exist", "missing_ticker_rules": "exclude and log"},
            {"strategy": "E_R1_REPAIRED", "formula_or_weights": "80% A1 baseline + 12% context momentum + 4% technical + 4% risk guardrail", "factor_families_used": "A1 baseline|context momentum|technical entry|risk guardrail", "historically_reconstructable_factors": "price-derived momentum/technical/risk proxies", "pit_lite_approximations": "current universe; current E_R1 formula schema; current metadata diagnostics", "snapshot_only_factors": "current repaired metadata/data trust", "identical_limitations": True, "missing_factor_handling": "neutral or exclude with audit", "exclusion_rules": "minimum valid price history; no future data", "stale_price_rules": "as-of close must exist", "missing_ticker_rules": "exclude and log"},
        ]
    )
    output_schema = pd.DataFrame(
        [
            {"required_output": "strategy_date_horizon_portfolio_returns.csv", "required_columns": "strategy|as_of_date|horizon|portfolio_size|return|valid_holding_count"},
            {"required_output": "e_r1_vs_a1_pairwise_comparison.csv", "required_columns": "as_of_date|horizon|portfolio_size|E_R1_return|A1_return|excess|win_flag"},
            {"required_output": "e_r1_vs_benchmarks.csv", "required_columns": "benchmark|as_of_date|horizon|return|excess|win_flag"},
            {"required_output": "left_tail_comparison.csv", "required_columns": "strategy|horizon|portfolio_size|p05|expected_shortfall|worst_return"},
            {"required_output": "invalid_trial_log.csv", "required_columns": "as_of_date|strategy|ticker|reason"},
            {"required_output": "leakage_audit_log.csv", "required_columns": "check|status|evidence"},
            {"required_output": "pit_lite_limitation_log.csv", "required_columns": "limitation|impact|required_label"},
            {"required_output": "maturity_forward_compatibility_table.csv", "required_columns": "as_of_date|horizon|compatible_with_forward_review"},
            {"required_output": "readable_report.txt", "required_columns": "FINAL_STATUS|DECISION|controls"},
        ]
    )
    boundaries = pd.DataFrame(
        [
            {"decision_rule": "may_support_E_R1_diagnostic_status", "allowed": True},
            {"decision_rule": "may_authorize_adoption", "allowed": False},
            {"decision_rule": "may_claim_PIT_STRICT", "allowed": False},
            {"decision_rule": "may_replace_A1", "allowed": False},
            {"decision_rule": "may_recommend_continued_forward_maturity_wait", "allowed": True},
            {"decision_rule": "may_recommend_stopping_E_R1_if_underperforms_A1", "allowed": True},
        ]
    )
    blockers = pd.DataFrame(
        [
            {"blocker": "NO_PIT_STRICT_RECONSTRUCTION", "status": "ACTIVE"},
            {"blocker": "CURRENT_UNIVERSE_SURVIVORSHIP_BIAS", "status": "ACTIVE"},
            {"blocker": "MISSING_DELISTED_TICKERS", "status": "ACTIVE"},
            {"blocker": "FORWARD_MATURITY_REQUIRED", "status": "ACTIVE"},
            {"blocker": "RESEARCH_ONLY_STAGE", "status": "ACTIVE"},
        ]
    )

    required_inputs = allowed[allowed["input_role"].eq("REQUIRED")]
    missing_required = int((~required_inputs["exists"]).sum())
    comparable = True
    manifest_complete = missing_required == 0 and comparable
    if manifest_complete:
        final_status = "PASS_V21_147_E_R1_A1_PIT_LITE_REPLAY_MANIFEST_READY"
        decision = "PROCEED_TO_V21_148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY"
    elif comparable:
        final_status = "PARTIAL_PASS_V21_147_MANIFEST_READY_WITH_INPUT_WARNINGS"
        decision = "V21_148_ALLOWED_DIAGNOSTIC_ONLY_WITH_INPUT_WARNINGS"
    else:
        final_status = "BLOCKED_V21_147_E_R1_A1_NOT_COMPARABLE"
        decision = "DO_NOT_RUN_V21_148_REPLAY"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "replay_target": "E_R1_REPAIRED vs A1_BASELINE_CONTROL",
        "bridge_level": "PIT_LITE_CURRENT_UNIVERSE",
        "manifest_complete": manifest_complete,
        "E_R1_A1_same_limitation_comparable": comparable,
        "earliest_possible_asof_date": date_meta["earliest"],
        "latest_possible_asof_date_20D": date_meta["latest_possible_asof_date_20D"],
        "allowed_horizons": "5D|10D|20D",
        "allowed_portfolio_sizes": "Top20|Top50",
        "required_input_count": int(len(required_inputs)),
        "missing_required_input_count": missing_required,
        "remaining_blockers": "|".join(blockers["blocker"]),
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    scope.to_csv(OUT / "V21.147_manifest_scope.csv", index=False)
    allowed.to_csv(OUT / "V21.147_allowed_inputs_manifest.csv", index=False)
    forbidden.to_csv(OUT / "V21.147_forbidden_inputs_manifest.csv", index=False)
    dates.to_csv(OUT / "V21.147_date_sampling_rules.csv", index=False)
    assumptions.to_csv(OUT / "V21.147_ranking_reconstruction_assumptions.csv", index=False)
    output_schema.to_csv(OUT / "V21.147_v21_148_required_output_schema.csv", index=False)
    boundaries.to_csv(OUT / "V21.147_v21_148_decision_boundaries.csv", index=False)
    blockers.to_csv(OUT / "V21.147_remaining_blockers.csv", index=False)
    (OUT / "V21.147_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "replay_target=E_R1_REPAIRED vs A1_BASELINE_CONTROL",
        "bridge_level=PIT_LITE_CURRENT_UNIVERSE",
        f"manifest_complete={str(manifest_complete).lower()}",
        f"E_R1_A1_same_limitation_comparable={str(comparable).lower()}",
        "replay_execution_allowed=false",
        "pit_strict_claim_allowed=false",
        f"earliest_possible_asof_date={date_meta['earliest']}",
        f"latest_possible_asof_date_20D={date_meta['latest_possible_asof_date_20D']}",
        "allowed_horizons=5D|10D|20D",
        "allowed_portfolio_sizes=Top20|Top50",
        f"required_input_count={len(required_inputs)}",
        f"missing_required_input_count={missing_required}",
        f"remaining_blockers={summary['remaining_blockers']}",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "strategy_adoption_allowed=false",
    ]
    (OUT / "V21.147_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for line in report[:16]:
        print(line)
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
