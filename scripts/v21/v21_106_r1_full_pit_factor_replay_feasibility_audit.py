#!/usr/bin/env python
"""V21.106-R1 full PIT factor replay feasibility audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


STAGE = "V21.106-R1_FULL_PIT_FACTOR_REPLAY_FEASIBILITY_AUDIT"
SOURCE_V106_RUN_ID = "20260623_142922"
OUTPUT_REL = Path("outputs/v21/v21_106_r1_full_pit_factor_replay_feasibility_audit")

CONFIG = "v21_106_r1_config.json"
REQUIRED = "v21_106_r1_required_factor_inventory.csv"
AVAILABLE = "v21_106_r1_available_historical_inputs.csv"
FAMILY = "v21_106_r1_factor_family_feasibility.csv"
GAP = "v21_106_r1_pit_lite_vs_full_factor_gap.csv"
TIMESTAMP = "v21_106_r1_timestamp_safety_audit.csv"
DECISION = "v21_106_r1_replay_feasibility_decision.csv"
WARNING = "v21_106_r1_warning_audit.csv"
README = "v21_106_r1_decision_readme.md"

PASS = "PASS_V21_106_R1_FULL_REPLAY_FEASIBLE"
PARTIAL = "PARTIAL_PASS_V21_106_R1_PARTIAL_REPLAY_FEASIBLE_WITH_WARNINGS"
BLOCKED = "PARTIAL_PASS_V21_106_R1_FULL_REPLAY_BLOCKED_USE_LIVE_FORWARD"
FAIL = "FAIL_V21_106_R1_DATA_INVENTORY_OR_TIMESTAMP_BLOCKER"

SOURCE_GUARDS = {
    "V21.104": (
        Path("outputs/v21/v21_104_abcd_random_252d_hold_full_run/20260623_163856"),
        ("v21_104_abcd_252d_hold_decision_readme.md", "v21_104_abcd_252d_hold_summary.csv"),
    ),
    "V21.104-R1": (
        Path("outputs/v21/v21_104_r1_d_long_horizon_edge_decomposition/20260623_165210"),
        ("v21_104_r1_decision_readme.md", "v21_104_r1_warning_audit.csv"),
    ),
    "V21.104-R2": (
        Path("outputs/v21/v21_104_r2_holdings_persistence_and_ticker_contribution/20260623_170358"),
        ("v21_104_r2_decision_readme.md", "v21_104_r2_warning_audit.csv"),
    ),
    "V21.105": (
        Path("outputs/v21/v21_105_abcd_random_252d_monthly_rebalance/20260623_122740"),
        ("v21_105_decision_readme.md", "v21_105_monthly_rebalance_summary.csv"),
    ),
    "V21.105-R1": (
        Path("outputs/v21/v21_105_r1_rebalance_failure_and_turnover_decomposition/20260623_125503"),
        ("v21_105_r1_decision_readme.md", "v21_105_r1_warning_audit.csv"),
    ),
    "V21.105-R2": (
        Path("outputs/v21/v21_105_r2_rebalance_gate_backtest/20260623_135252"),
        ("v21_105_r2_decision_readme.md", "v21_105_r2_data_quality_warnings.csv"),
    ),
    "V21.106": (
        Path("outputs/v21/v21_106_long_horizon_and_rebalance_decision_report/20260623_142922"),
        ("v21_106_decision_readme.md", "v21_106_config.json", "v21_106_warning_and_blocker_audit.csv"),
    ),
}


def load_v103(root: Path):
    path = root / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
    spec = importlib.util.spec_from_file_location("v21_103_shared_for_v106_r1", path)
    if not spec or not spec.loader:
        raise RuntimeError("V21.103 shared implementation unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else ["status"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def immutable_output(root: Path, override: Path | None, run_id: str | None) -> tuple[Path, str]:
    identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = (override if override and override.is_absolute() else root / (override or OUTPUT_REL / identifier)).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Immutable output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output, identifier


def guard_hashes(root: Path) -> dict[str, dict[str, str]]:
    result = {}
    for stage, (relative, names) in SOURCE_GUARDS.items():
        base = root / relative
        missing = [name for name in names if not (base / name).is_file()]
        if missing:
            raise RuntimeError(f"Missing guarded {stage} files: {missing}")
        result[stage] = {name: sha256(base / name) for name in names}
    return result


def required_inventory() -> list[dict[str, object]]:
    rows = [
        ("FUNDAMENTAL", "Historical valuation, profitability, growth, balance-sheet and quality metrics", "ticker;reporting_date;publication_date;as_of_date;raw_metric;normalized_score", "Quarterly/event timestamp with publication lag", True),
        ("TECHNICAL", "Historical OHLCV-derived trend, RSI, KDJ, MACD, Bollinger, moving-average, volume and volatility signals", "ticker;as_of_date;OHLCV;subfactor_scores;family_score", "Daily", True),
        ("STRATEGY", "Historical setup/rule outputs and cross-sectional strategy score", "ticker;as_of_date;rule_inputs;rule_outputs;strategy_score", "Daily or decision-date", True),
        ("RISK", "Historical volatility, drawdown, liquidity and gate/penalty state", "ticker;as_of_date;risk_inputs;risk_gate;risk_penalty", "Daily or decision-date", False),
        ("MARKET_REGIME", "Historical benchmark regime state and ticker exposure mapping", "as_of_date;benchmark_inputs;regime_label;ticker_exposure", "Daily", False),
        ("DATA_TRUST", "Historical direct PASS/FAIL/UNKNOWN readiness and freshness gate", "ticker;as_of_date;source_timestamp;quality_status;freshness_status;direct_gate", "Daily/run-date", False),
        ("MOMENTUM", "Historical absolute/relative momentum, acceleration, persistence and exhaustion state used by B/C/D", "ticker;as_of_date;benchmark_returns;momentum_components;momentum_score", "Daily", True),
        ("BENCHMARK", "QQQ, SPY and SOXX historical OHLCV and regime inputs", "symbol;date;OHLCV;source_timestamp", "Daily", False),
        ("UNIVERSE_MEMBERSHIP", "Historical eligible ticker membership at each ranking date", "ticker;as_of_date;membership_status;source_lineage", "Daily or ranking-date", False),
    ]
    return [
        {
            "factor_family": family, "full_replay_requirement": requirement,
            "minimum_required_fields": fields, "required_timestamp_granularity": granularity,
            "alpha_bearing": str(alpha).upper(), "required_for_exact_historical_ranking": "TRUE",
            "neutral_fill_allowed": "FALSE", "research_only": "TRUE",
        }
        for family, requirement, fields, granularity, alpha in rows
    ]


def inspect_csv(root: Path, family: str, relative: str, role: str, date_column: str | None,
                repaired: str, safety: str, reproduction: str, notes: str) -> dict[str, object]:
    path = root / relative
    row = {
        "factor_family": family, "source_artifact": relative,
        "source_role": role, "artifact_exists": str(path.is_file()).upper(),
        "row_count": 0, "available_date_start": "", "available_date_end": "",
        "distinct_dates": 0, "timestamp_granularity": "NONE",
        "as_of_safety": safety, "repaired_or_backfilled": repaired,
        "future_leakage_risk": "LOW" if safety == "SAFE" else "HIGH" if "UNSAFE" in safety or "UNKNOWN" in safety else "MEDIUM",
        "can_reproduce_historical_abcd": reproduction, "notes": notes,
    }
    if not path.is_file():
        return row
    frame = pd.read_csv(path, low_memory=False)
    row["row_count"] = len(frame)
    if date_column and date_column in frame.columns:
        dates = frame[date_column].dropna().astype(str).str.slice(0, 10)
        if len(dates):
            row["available_date_start"] = dates.min()
            row["available_date_end"] = dates.max()
            row["distinct_dates"] = dates.nunique()
            row["timestamp_granularity"] = "DAILY_OR_ASOF_DATE"
    return row


def available_inputs(root: Path) -> list[dict[str, object]]:
    specs = [
        ("TECHNICAL", "outputs/v21/factors/V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv", "Dated historical technical subfactor panel", "as_of_date", "BACKFILLED_FROM_HISTORICAL_OHLCV", "SAFE", "PARTIAL", "PIT-safe but covers only a limited 2023-2024 interval."),
        ("TECHNICAL", "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "Canonical candidate OHLCV for recomputation", "date", "REPAIRED_AND_REFRESHED", "SAFE_FOR_PRICE_DERIVED_FACTORS", "PARTIAL", "Supports price/volume recomputation, not exact non-price full-factor A1 history."),
        ("BENCHMARK", "outputs/v20/price_history/V20_199D_CANONICAL_BENCHMARK_OHLCV.csv", "QQQ/SPY/SOXX benchmark history", "date", "REPAIRED_AND_REFRESHED", "SAFE_FOR_PRICE_DERIVED_FACTORS", "YES", "Daily benchmark history supports return and PIT-lite regime calculations."),
        ("FUNDAMENTAL", "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv", "Current six-family score table", None, "MATERIALIZED_CURRENT_STATE", "TIMESTAMP_UNSAFE_FOR_HISTORY", "NO", "No historical as-of/reporting/publication dates."),
        ("STRATEGY", "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv", "Current strategy candidate score", None, "MATERIALIZED_CURRENT_STATE", "TIMESTAMP_UNSAFE_FOR_HISTORY", "NO", "Current score lacks historical factor-date lineage."),
        ("RISK", "outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv", "Current risk score/gate context", None, "MATERIALIZED_CURRENT_STATE", "TIMESTAMP_UNSAFE_FOR_HISTORY", "NO", "Historical dates and gate-only semantics are not replayable."),
        ("MARKET_REGIME", "outputs/v20/consolidation/V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv", "Current ticker regime contribution", None, "MATERIALIZED_CURRENT_STATE", "TIMESTAMP_UNSAFE_FOR_HISTORY", "NO", "Historical market dates and exposure lineage absent."),
        ("DATA_TRUST", "outputs/v20/backtest_snapshots/V20_194_RECOMPUTABLE_FACTOR_SNAPSHOT_LEDGER.csv", "Append-only current/future six-family snapshot ledger", "as_of_date", "APPEND_ONLY_FORWARD_SNAPSHOTS", "SAFE_FROM_CAPTURE_DATE_FORWARD", "FUTURE_ONLY", "Only three June 2026 as-of dates; cannot backfill historical samples."),
        ("MOMENTUM", "outputs/v21/momentum/V21_058_R2_REPAIRED_UNIFIED_MOMENTUM_LEDGER.csv", "Unified momentum ledger", "as_of_date", "REPAIRED_CURRENT_FORWARD_LEDGER", "SAFE_FROM_CAPTURE_DATE_FORWARD", "FUTURE_ONLY", "Only three June 2026 as-of dates; historical score lineage absent."),
        ("UNIVERSE_MEMBERSHIP", "outputs/v18/universe/V18_CURRENT_UNIVERSE_ROLLING_STATE.csv", "Current rolling universe state", "latest_price_date", "CURRENT_STATE_REPAIRED", "TIMESTAMP_UNSAFE_FOR_HISTORICAL_MEMBERSHIP", "NO", "Current membership cannot be projected backward."),
        ("UNIVERSE_MEMBERSHIP", "outputs/v20/consolidation/V20_214_MEMBERSHIP_STAGING_CERTIFICATION.csv", "Historical membership certification audit", None, "PLAN_ONLY", "SAFE_BLOCKER_AUDIT", "NO", "Explicitly certifies zero historical baseline/shadow membership rows."),
        ("ALL_FULL_FAMILIES", "outputs/v20/backtest/V20_193_HISTORICAL_RECOMPUTABLE_FACTOR_SNAPSHOT.csv", "Historical full-family recomputable snapshot attempt", "as_of_date", "AUDIT_ONLY_NO_BACKFILL", "SAFE_EMPTY_BLOCKER", "NO", "Zero rows; V20.193 found no usable historical full-family inputs."),
    ]
    return [inspect_csv(root, *spec) for spec in specs]


def family_feasibility() -> list[dict[str, object]]:
    rows = [
        ("FUNDAMENTAL", "PIT_REPLAY_BLOCKED_MISSING_HISTORY", "Current values exist, but historical reporting/publication dates do not.", "HIGH", "Build filing-aware historical metric panel."),
        ("TECHNICAL", "PARTIAL_PIT_REPLAY_READY", "Daily OHLCV is available and technical history is partially materialized; exact full technical panel does not span all required dates.", "HIGH", "Recompute exact technical specification across canonical OHLCV and validate against materialized overlap."),
        ("STRATEGY", "PIT_REPLAY_BLOCKED_MISSING_HISTORY", "Current strategy scores lack historical rule-output and factor-date lineage.", "HIGH", "Materialize dated rule inputs/outputs without forward labels."),
        ("RISK", "PIT_REPLAY_BLOCKED_TIMESTAMP_UNSAFE", "Current risk context is undated for historical replay and is gate/penalty-only.", "MEDIUM", "Build dated risk gate/penalty observations with alpha disabled."),
        ("MARKET_REGIME", "PARTIAL_PIT_REPLAY_READY", "Benchmark history can reproduce PIT-lite regime, but exact historical regime/exposure contribution is unavailable.", "MEDIUM", "Materialize dated market regime state and ticker exposure separately."),
        ("DATA_TRUST", "PIT_REPLAY_BLOCKED_MISSING_HISTORY", "Only current/forward snapshots exist; historical direct gate status is absent.", "MEDIUM", "Continue append-only snapshots and define historical source reconstruction if possible."),
        ("MOMENTUM", "PARTIAL_PIT_REPLAY_READY", "Canonical OHLCV/benchmarks allow recomputation, but exact unified momentum ledger exists only for June 2026.", "HIGH", "Back-compute documented momentum components from PIT-safe prices and reconcile to forward ledger."),
        ("BENCHMARK", "FULL_PIT_REPLAY_READY", "QQQ/SPY/SOXX daily history is available with explicit dates.", "HIGH", "Retain canonical benchmark certification and row hashes."),
        ("UNIVERSE_MEMBERSHIP", "PIT_REPLAY_BLOCKED_MISSING_HISTORY", "No certified historical membership source exists; current universe is survivorship-biased.", "HIGH", "Execute survivorship-bias repair plan before historical full replay."),
    ]
    return [
        {
            "factor_family": family, "feasibility_classification": classification,
            "evidence": evidence, "likely_materiality": materiality,
            "required_repair": repair, "exact_abcd_ranking_reproduction_ready": str(classification == "FULL_PIT_REPLAY_READY").upper(),
            "research_only": "TRUE",
        }
        for family, classification, evidence, materiality, repair in rows
    ]


def pit_gap() -> list[dict[str, object]]:
    rows = [
        ("PRICE_TREND", "TECHNICAL", "INCLUDED", "OHLCV returns, MA trend, highs and volatility", "LOW", "Core PIT-lite evidence is directly supported."),
        ("VOLUME", "TECHNICAL", "INCLUDED", "Volume ratio and volume trend", "LOW", "Core PIT-lite evidence is directly supported."),
        ("MARKET_REGIME_PRICE_PROXY", "MARKET_REGIME", "INCLUDED", "QQQ/SPY trend and 20-day return proxy", "MEDIUM", "Captures broad regime direction but not full regime/exposure model."),
        ("SHORT_HORIZON_MOMENTUM", "MOMENTUM", "INCLUDED", "5/10/20-day cross-sectional returns plus technical score", "MEDIUM", "Captures D's intended momentum tilt but not the complete unified momentum state."),
        ("FUNDAMENTALS", "FUNDAMENTAL", "MISSING", "Valuation, growth, profitability, balance-sheet and quality", "HIGH", "Likely material to A1 baseline ranks and therefore A1/B/C/D relative comparisons."),
        ("FULL_STRATEGY_RULES", "STRATEGY", "MISSING", "Historical setup/rule outputs beyond price-derived proxy", "HIGH", "Could materially alter cross-sectional ranks."),
        ("RISK_GATES_AND_PENALTIES", "RISK", "MISSING", "Historical direct risk gate/penalty state", "MEDIUM", "May change eligibility and downside behavior even if not alpha-bearing."),
        ("FULL_MARKET_REGIME_EXPOSURE", "MARKET_REGIME", "MISSING", "Dated market state plus ticker/sector exposure", "MEDIUM", "May affect conditional ranks and regime robustness."),
        ("DATA_TRUST_GATE", "DATA_TRUST", "MISSING", "Historical direct PASS/FAIL/UNKNOWN quality/freshness gate", "MEDIUM", "May exclude stale or unsafe inputs; important for official reproducibility."),
        ("FULL_MOMENTUM_STATE", "MOMENTUM", "MISSING", "Relative momentum, acceleration, persistence, exhaustion and chase state", "HIGH", "Likely material to B/C/D differences."),
        ("HISTORICAL_UNIVERSE", "UNIVERSE_MEMBERSHIP", "MISSING", "Dated eligible universe membership", "HIGH", "Direct survivorship-bias driver affecting all historical ranks."),
    ]
    return [
        {
            "factor_or_input": name, "factor_family": family, "pit_lite_status": status,
            "coverage_or_gap": detail, "likely_materiality": materiality,
            "impact_on_v21_104_to_v21_106": impact,
            "conclusion_robustness": "DIRECTIONALLY_SUPPORTED_BUT_INCOMPLETE" if status == "MISSING" else "SUPPORTED_WITHIN_PIT_LITE_SCOPE",
            "research_only": "TRUE",
        }
        for name, family, status, detail, materiality, impact in rows
    ]


def timestamp_audit(available: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    for index, row in enumerate(available, start=1):
        safe = row["as_of_safety"] in {"SAFE", "SAFE_FOR_PRICE_DERIVED_FACTORS", "SAFE_FROM_CAPTURE_DATE_FORWARD"}
        output.append({
            "audit_id": f"V21_106_R1_TS_{index:03d}", "factor_family": row["factor_family"],
            "source_artifact": row["source_artifact"], "date_start": row["available_date_start"],
            "date_end": row["available_date_end"], "timestamp_granularity": row["timestamp_granularity"],
            "explicit_as_of_date": str(bool(row["available_date_start"])).upper(),
            "publication_lag_available": "FALSE" if row["factor_family"] == "FUNDAMENTAL" else "NOT_APPLICABLE_OR_DERIVED",
            "current_state_backfilled_into_history": "FALSE",
            "as_of_safe_for_historical_replay": str(safe and row["can_reproduce_historical_abcd"] in {"YES", "PARTIAL"}).upper(),
            "future_leakage_risk": row["future_leakage_risk"],
            "timestamp_decision": row["as_of_safety"], "research_only": "TRUE",
        })
    return output


def render_readme(output: Path, run_id: str, status: str, source_modified: bool, protected_modified: bool) -> None:
    text = f"""# V21.106-R1 Full PIT Factor Replay Feasibility Audit

FINAL_STATUS: `{status}`  
DECISION: `FULL_REPLAY_BLOCKED_USE_LIVE_FORWARD`  
run_id: `{run_id}`  
source V21.106 run_id: `{SOURCE_V106_RUN_ID}`  
official_adoption_allowed: `false`  
broker_action_allowed: `false`

## Feasibility decision

- Full PIT replay feasible: `NO`.
- Overall feasibility: `FULL_REPLAY_BLOCKED_USE_LIVE_FORWARD`.
- Replay-ready family: `BENCHMARK`.
- Partially replay-ready families: `TECHNICAL`, `MARKET_REGIME`, `MOMENTUM`.
- Blocked families: `FUNDAMENTAL`, `STRATEGY`, `RISK`, `DATA_TRUST`, `UNIVERSE_MEMBERSHIP`.
- PIT-factor approximation warning can be removed: `NO`.
- Survivorship bias warning remains: `YES`.
- Prior V21.104-V21.106 outputs modified: `{'TRUE' if source_modified else 'FALSE'}`.
- Protected outputs modified: `{'TRUE' if protected_modified else 'FALSE'}`.

## Evidence

- V21.044-R4 materialized 219,649 technical rows but explicitly blocked the other five full-weight families.
- V20.193 inspected 690 candidate artifacts and found zero usable historical full-family sources.
- V20.194 provides append-only six-family snapshots only from June 12-16, 2026; these are suitable for future observation, not historical backfill.
- Fundamental, strategy, risk, regime-exposure, and data-trust current tables lack the historical factor timestamps required for safe replay.
- Historical universe membership is not certified; V20.214 explicitly reports zero staged baseline/shadow membership rows.

## Interpretation

V21.104-V21.106 conclusions remain directionally supported within the documented PIT-lite price/volume framework, but they are incomplete as claims about the full A1/B/C/D factor model. Missing fundamentals, full momentum state, strategy rules, risk gates, data-trust gates, and historical universe membership are likely material to exact ranks.

## Recommended next step

Proceed with `V21.106-R2_SURVIVORSHIP_BIAS_REPAIR_PLAN`, while continuing append-only full-family snapshots and `V21.107_LIVE_FORWARD_TRACKING_FOR_D_TOP20_HOLD_AND_D_TOP50_QUARTERLY`. Do not fabricate historical factor dates or backfill current scores.

This audit does not change rankings, weights, protected outputs, or broker state.
"""
    (output / README).write_text(text, encoding="utf-8")


def run_stage(root: Path, output: Path, run_id: str) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    before = guard_hashes(root)
    v103 = load_v103(root)
    protected = v103.protected_files(root, output)
    protected_before = {path: sha256(path) for path in protected}
    try:
        required = required_inventory()
        available = available_inputs(root)
        families = family_feasibility()
        gap = pit_gap()
        timestamps = timestamp_audit(available)
        after = guard_hashes(root)
        protected_after = {path: sha256(path) for path in protected}
        source_modified = before != after
        protected_modified = any(protected_before[path] != protected_after[path] for path in protected)
        inventory_complete = len(required) == 9 and len(families) == 9
        overall = "FULL_REPLAY_BLOCKED_USE_LIVE_FORWARD"
        status = FAIL if source_modified or protected_modified or not inventory_complete else BLOCKED
        decision_rows = [{
            "overall_feasibility": overall, "full_replay_feasible": "FALSE",
            "partial_replay_feasible": "TRUE_FOR_PRICE_DERIVED_DIAGNOSTICS_ONLY",
            "full_replay_ready_family_count": sum(row["feasibility_classification"] == "FULL_PIT_REPLAY_READY" for row in families),
            "partial_replay_ready_family_count": sum(row["feasibility_classification"] == "PARTIAL_PIT_REPLAY_READY" for row in families),
            "blocked_family_count": sum(row["feasibility_classification"].startswith("PIT_REPLAY_BLOCKED") for row in families),
            "pit_factor_approximation_warning_removable": "FALSE",
            "survivorship_bias_warning_remains": "TRUE",
            "v21_104_to_v21_106_robustness": "DIRECTIONALLY_SUPPORTED_WITHIN_PIT_LITE_SCOPE_BUT_FULL_FACTOR_CONCLUSIONS_INCOMPLETE",
            "recommended_next_step": "V21.106-R2_SURVIVORSHIP_BIAS_REPAIR_PLAN_AND_V21.107_LIVE_FORWARD_TRACKING",
            "source_outputs_modified": str(source_modified).upper(),
            "protected_outputs_modified": str(protected_modified).upper(),
            "official_adoption_allowed": "FALSE", "broker_action_allowed": "FALSE",
            "research_only": "TRUE",
        }]
        warning_rows = [
            {"warning_code": "SURVIVORSHIP_BIAS_WARN", "status": "ACTIVE", "severity": "HIGH",
             "details": "Historical eligible universe membership is unavailable.", "removable_now": "FALSE"},
            {"warning_code": "PIT_FACTOR_APPROXIMATION_WARN", "status": "ACTIVE", "severity": "HIGH",
             "details": "Five full-weight families lack compatible historical materialization; momentum is only partially replayable.", "removable_now": "FALSE"},
            {"warning_code": "FULL_HISTORICAL_A1_REPLAY_BLOCKED", "status": "ACTIVE", "severity": "HIGH",
             "details": "Exact A1/B/C/D ranks cannot be reproduced from current historical inputs.", "removable_now": "FALSE"},
            {"warning_code": "CURRENT_STATE_BACKFILL_PROHIBITED", "status": "ENFORCED", "severity": "HIGH",
             "details": "Current factor scores and file timestamps must not be projected backward.", "removable_now": "FALSE"},
            {"warning_code": "SOURCE_OUTPUTS_MODIFIED", "status": str(source_modified).upper(), "severity": "HIGH" if source_modified else "INFO",
             "details": "V21.104-V21.106 guarded source hash audit.", "removable_now": "NOT_APPLICABLE"},
            {"warning_code": "PROTECTED_OUTPUTS_MODIFIED", "status": str(protected_modified).upper(), "severity": "HIGH" if protected_modified else "INFO",
             "details": "Protected-output hash audit.", "removable_now": "NOT_APPLICABLE"},
        ]
        config = {
            "stage": STAGE, "run_id": run_id, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_v21_106_run_id": SOURCE_V106_RUN_ID, "guarded_source_hashes": before,
            "audit_only": True, "overall_feasibility": overall,
            "official_adoption_allowed": False, "broker_action_allowed": False,
            "research_only": True,
        }
        write_json(output / CONFIG, config)
        write_csv(output / REQUIRED, required)
        write_csv(output / AVAILABLE, available)
        write_csv(output / FAMILY, families)
        write_csv(output / GAP, gap)
        write_csv(output / TIMESTAMP, timestamps)
        write_csv(output / DECISION, decision_rows)
        write_csv(output / WARNING, warning_rows)
        render_readme(output, run_id, status, source_modified, protected_modified)
    except Exception as exc:
        status, overall, source_modified, protected_modified = FAIL, "AUDIT_FAILED_DATA_INVENTORY_INCOMPLETE", False, False
        write_json(output / CONFIG, {
            "stage": STAGE, "run_id": run_id, "execution_error": str(exc),
            "official_adoption_allowed": False, "broker_action_allowed": False,
        })
        for name in (REQUIRED, AVAILABLE, FAMILY, GAP, TIMESTAMP, DECISION, WARNING):
            write_csv(output / name, [], ["status"])
        (output / README).write_text(
            f"# V21.106-R1\n\nFINAL_STATUS: `{FAIL}`  \nDECISION: `{overall}`  \n"
            f"source V21.106 run_id: `{SOURCE_V106_RUN_ID}`  \nofficial_adoption_allowed: `false`  \n"
            f"broker_action_allowed: `false`\n\nBlocking error: {exc}\n", encoding="utf-8"
        )
    result = {
        "FINAL_STATUS": status, "DECISION": overall, "RUN_ID": run_id,
        "SOURCE_V21_106_RUN_ID": SOURCE_V106_RUN_ID,
        "SOURCE_OUTPUTS_MODIFIED": source_modified, "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OUTPUT_DIR": output.as_posix(), "OFFICIAL_ADOPTION_ALLOWED": False,
        "BROKER_ACTION_ALLOWED": False,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    output, run_id = immutable_output(args.root.resolve(), args.output_dir, args.run_id)
    result = run_stage(args.root, output, run_id)
    return 1 if str(result["FINAL_STATUS"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
