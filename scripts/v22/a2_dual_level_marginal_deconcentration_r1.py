"""Fail-closed audit for the proposed S1 plus marginal FF48 overlay.

The frozen taxonomy and A2 Top20 path both begin in 2023.  S1 is a target
reweighting rule over that already-selected Top20, not a sequential selector.
This runner verifies those identities and refuses to select r48 without the
pre-2023, outcome-free calibration support required by the task contract.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_DUAL_LEVEL_MARGINAL_DECONCENTRATION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
UPSTREAM = RESULTS / "A2_SECTOR_AWARE_ML_AND_FACTOR_OVERNIGHT_R1"
TAXONOMY_UPSTREAM = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
TAXONOMY = TAXONOMY_UPSTREAM / "pit_ff12_ff48_taxonomy.parquet"
TOP20 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "top20_selections.parquet"
PORTFOLIO = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
UPSTREAM_MODEL = UPSTREAM / "primary_forward_model.joblib"
UPSTREAM_MODEL_MANIFEST = UPSTREAM / "primary_forward_model_manifest.json"
UPSTREAM_FREEZE = UPSTREAM / "finalist_freeze.json"
UPSTREAM_HASH_MANIFEST = UPSTREAM / "hash_manifest.json"
UPSTREAM_METADATA = UPSTREAM / "research_metadata.json"
TAXONOMY_METADATA = TAXONOMY_UPSTREAM / "research_metadata.json"
TAXONOMY_HASH_MANIFEST = TAXONOMY_UPSTREAM / "hash_manifest.json"

EXPECTED_TAXONOMY_LOGICAL_HASH = "0f0b48772c09dadb1b93d783a623a896a3a18ef307b75fa253ef2f08ee9208e1"
EXPECTED_TAXONOMY_FILE_SHA256 = "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f"
EXPECTED_RIDGE_ID = "A2_SECTOR_CORRECTION_C_b574abb336ca78aa06a6"
EXPECTED_RIDGE_CANDIDATE = "C_b574abb336ca78aa06a6"
EXPECTED_RIDGE_SHA256 = "c1ca77f8d935127606c25581f8af5a399a41dc22fe1c6f40b29ab0012bc1ae04"
R48_CANDIDATES = (0.10, 0.20, 0.30)
FORBIDDEN_SELECTION_COLUMNS = {
    "return", "returns", "cagr", "sharpe", "maxdd", "max_drawdown", "alpha",
    "residual_sharpe", "active_ir", "future_return", "label", "outcome",
}


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = None) -> None:
    if not condition:
        suffix = "" if detail is None else f":{detail}"
        raise GateFailure(f"{code}{suffix}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def s1_independent_weights(day: pd.DataFrame) -> dict[str, float]:
    """Independent implementation of frozen S1_SOFT_025 target weights."""
    require(len(day) == 20 and day.ticker.nunique() == 20, "S1_TOP20_CARDINALITY")
    counts = day.groupby("ff12").ticker.count().astype(float)
    raw_group_weight = counts / counts.sum()
    group_budget = raw_group_weight.pow(0.75)
    group_budget /= group_budget.sum()
    result = {
        str(ticker): float(group_budget.loc[label] / len(members))
        for label, members in day.groupby("ff12", sort=True)
        for ticker in members.ticker
    }
    require(len(result) == 20 and abs(sum(result.values()) - 1.0) <= 1e-12, "S1_WEIGHT_IDENTITY")
    return result


def delta_hhi48(current_weight: float, delta_weight: float) -> float:
    require(current_weight >= 0 and delta_weight > 0, "DELTA_HHI_INPUT")
    return (current_weight + delta_weight) ** 2 - current_weight**2


def sequential_order(
    candidates: pd.DataFrame,
    target_count: int,
    r48: float,
    delta_weights: dict[str, float],
) -> list[str]:
    """Dynamic reference implementation; never used to bypass support gates."""
    forbidden = FORBIDDEN_SELECTION_COLUMNS.intersection({str(c).lower() for c in candidates.columns})
    require(not forbidden, "ECONOMIC_COLUMN_VISIBLE_TO_R48_SELECTION", sorted(forbidden))
    require({"ticker", "base_utility", "ff48"}.issubset(candidates.columns), "SEQUENTIAL_SCHEMA")
    require(0 <= target_count <= len(candidates), "SEQUENTIAL_TARGET_COUNT")
    remaining = candidates.copy()
    selected: list[str] = []
    industry_weight: dict[str, float] = {}
    while len(selected) < target_count:
        work = remaining.copy()
        work["base_rank_pct"] = work.base_utility.rank(method="average", pct=True)
        work["delta_hhi48"] = [
            delta_hhi48(industry_weight.get(str(group), 0.0), float(delta_weights[str(ticker)]))
            for ticker, group in zip(work.ticker, work.ff48)
        ]
        work["ff48_crowding_pct"] = work.delta_hhi48.rank(method="average", pct=True)
        work["dual_utility"] = work.base_rank_pct - float(r48) * work.ff48_crowding_pct
        chosen = work.sort_values(["dual_utility", "base_rank_pct", "ticker"], ascending=[False, False, True], kind="mergesort").iloc[0]
        ticker, group = str(chosen.ticker), str(chosen.ff48)
        selected.append(ticker)
        industry_weight[group] = industry_weight.get(group, 0.0) + float(delta_weights[ticker])
        remaining = remaining.loc[remaining.ticker.astype(str).ne(ticker)].copy()
    return selected


def concentration_only_selection(calibration: pd.DataFrame) -> tuple[float | None, pd.DataFrame]:
    """Select the smallest r48 using concentration columns only."""
    forbidden = FORBIDDEN_SELECTION_COLUMNS.intersection({str(c).lower() for c in calibration.columns})
    require(not forbidden, "ECONOMIC_COLUMN_VISIBLE_TO_R48_SELECTION", sorted(forbidden))
    required = {"session_date", "r48", "ff12_hhi", "ff48_hhi", "ff48_max_weight", "feasible_top20"}
    require(required.issubset(calibration.columns), "CALIBRATION_SCHEMA", sorted(required - set(calibration.columns)))
    if calibration.empty:
        rows = [{
            "r48": r48, "support_session_count": 0, "mean_ff12_hhi": math.nan,
            "mean_ff48_hhi": math.nan, "ff48_hhi_reduction_vs_s1": math.nan,
            "max_ff48_weight": math.nan, "all_sessions_feasible_top20": False,
            "selection_used_economic_outcomes": False,
            "status": "NOT_EVALUATED:NO_PRE2023_FROZEN_TAXONOMY_OR_TOP20_SUPPORT",
        } for r48 in (0.0, *R48_CANDIDATES)]
        return None, pd.DataFrame(rows)
    dates = pd.to_datetime(calibration.session_date)
    require(dates.max() <= pd.Timestamp("2022-12-31"), "CALIBRATION_AFTER_2022", dates.max())
    summaries = []
    for r48, group in calibration.groupby("r48", sort=True):
        summaries.append({
            "r48": float(r48), "support_session_count": len(group),
            "mean_ff12_hhi": float(group.ff12_hhi.mean()), "mean_ff48_hhi": float(group.ff48_hhi.mean()),
            "max_ff48_weight": float(group.ff48_max_weight.max()),
            "all_sessions_feasible_top20": bool(group.feasible_top20.all()),
            "selection_used_economic_outcomes": False, "status": "EVALUATED_CONCENTRATION_ONLY",
        })
    table = pd.DataFrame(summaries).sort_values("r48")
    base = table.loc[table.r48.eq(0.0)].iloc[0]
    table["ff48_hhi_reduction_vs_s1"] = (base.mean_ff48_hhi - table.mean_ff48_hhi) / base.mean_ff48_hhi
    eligible = table.loc[
        table.r48.isin(R48_CANDIDATES)
        & table.ff48_hhi_reduction_vs_s1.ge(0.05)
        & table.mean_ff12_hhi.le(base.mean_ff12_hhi * 1.01)
        & table.max_ff48_weight.lt(base.max_ff48_weight)
        & table.all_sessions_feasible_top20
    ]
    return (None if eligible.empty else float(eligible.r48.min())), table


def verify_inputs() -> dict[str, Any]:
    paths = [TAXONOMY, TOP20, PORTFOLIO, BASE_SOURCE, UPSTREAM_MODEL, UPSTREAM_MODEL_MANIFEST,
             UPSTREAM_FREEZE, UPSTREAM_HASH_MANIFEST, UPSTREAM_METADATA, TAXONOMY_METADATA, TAXONOMY_HASH_MANIFEST]
    for path in paths:
        require(path.is_file(), "INPUT_MISSING", path)
    taxonomy_meta = json.loads(TAXONOMY_METADATA.read_text(encoding="utf-8"))
    taxonomy_manifest = json.loads(TAXONOMY_HASH_MANIFEST.read_text(encoding="utf-8"))
    require(taxonomy_meta["taxonomy_hash"] == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_LOGICAL_HASH")
    require(taxonomy_manifest["taxonomy_hash"] == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_MANIFEST_LOGICAL_HASH")
    require(sha256_file(TAXONOMY) == EXPECTED_TAXONOMY_FILE_SHA256, "TAXONOMY_FILE_HASH")
    upstream_manifest = json.loads(UPSTREAM_HASH_MANIFEST.read_text(encoding="utf-8"))
    manifest_hash = next(item["sha256"] for item in upstream_manifest["artifacts"] if item["name"] == UPSTREAM_MODEL.name)
    ridge_manifest = json.loads(UPSTREAM_MODEL_MANIFEST.read_text(encoding="utf-8"))
    ridge_freeze = json.loads(UPSTREAM_FREEZE.read_text(encoding="utf-8"))
    upstream_metadata = json.loads(UPSTREAM_METADATA.read_text(encoding="utf-8"))
    actual_model_hash = sha256_file(UPSTREAM_MODEL)
    require(actual_model_hash == manifest_hash == ridge_manifest["model_sha256"] == EXPECTED_RIDGE_SHA256, "RIDGE_HASH")
    require(ridge_manifest["model_id"] == EXPECTED_RIDGE_ID, "RIDGE_ID")
    require(ridge_manifest["primary_candidate_id"] == ridge_freeze["primary_challenger_id"] == EXPECTED_RIDGE_CANDIDATE, "RIDGE_CANDIDATE")
    require(ridge_freeze["primary_fixed_before_2025_candidate_outcome_read"], "RIDGE_NOT_FROZEN")
    require(not ridge_manifest["2025_used_for_specification_selection"] and ridge_manifest["2026_training_rows"] == 0, "RIDGE_TEMPORAL_IDENTITY")

    base = import_file("a2_dual_level_base", BASE_SOURCE)
    top20, portfolio, raw = base.verify_inputs()
    taxonomy = pd.read_parquet(TAXONOMY)
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    require(top20.groupby("signal_date").ticker.nunique().eq(20).all(), "TOP20_CARDINALITY")
    require(len(top20) == len(taxonomy) == 15000, "FROZEN_SUPPORT_ROWS")
    require(top20.signal_date.min() == taxonomy.signal_date.min() == pd.Timestamp("2023-01-03"), "FROZEN_SUPPORT_START")
    require(int((top20.signal_date <= pd.Timestamp("2022-12-31")).sum()) == 0, "UNEXPECTED_PRE2023_TOP20")
    require(int((taxonomy.signal_date <= pd.Timestamp("2022-12-31")).sum()) == 0, "UNEXPECTED_PRE2023_TAXONOMY")

    s1 = next(item for item in base.candidates() if item.trial_id == "S1_SOFT_025")
    authoritative_targets = base.candidate_target(s1, top20, taxonomy)
    joined = top20.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], validate="one_to_one")
    max_error = 0.0
    r0_set_mismatch = 0
    for date, day in joined.groupby("signal_date", sort=True):
        independent = s1_independent_weights(day)
        frozen = authoritative_targets[pd.Timestamp(date)]
        max_error = max(max_error, max(abs(independent[t] - frozen[t]) for t in frozen))
        order = sequential_order(
            day.assign(base_utility=day.a2_prediction)[["ticker", "base_utility", "ff48"]],
            target_count=20, r48=0.0, delta_weights=independent,
        )
        r0_set_mismatch += int(set(order) != set(frozen))
    require(max_error <= 1e-15 and r0_set_mismatch == 0, "S1_R0_WEIGHT_REPLAY", (max_error, r0_set_mismatch))
    return {
        "base": base, "raw": raw, "top20": top20, "taxonomy": taxonomy,
        "s1_target_count": len(authoritative_targets), "s1_max_weight_error": max_error,
        "r0_set_mismatch_count": r0_set_mismatch, "ridge_manifest": ridge_manifest,
        "ridge_freeze": ridge_freeze, "taxonomy_meta": taxonomy_meta,
        "s1_reference": upstream_metadata["s1"], "ridge_reference": upstream_metadata["primary"],
    }


def render_terminal(result: dict[str, Any]) -> str:
    na = "NOT_APPLICABLE:NO_R48_SELECTED"
    lines = ["=" * 60, "A2_DUAL_LEVEL_MARGINAL_DECONCENTRATION_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={result['task_status']}", "", "2026_OUTCOME_USED=FALSE", "2026_LEAKAGE_COUNT=0", "",
        "IDENTITY", "-" * 60, f"RAW_RECONCILIATION={result['raw_reconciliation']}",
        f"S1_RECONCILIATION={result['s1_reconciliation']}", f"RIDGE_IDENTITY_STATUS={result['ridge_identity_status']}",
        f"TAXONOMY_HASH_STATUS={result['taxonomy_hash_status']}", "", "DUAL OVERLAY", "-" * 60,
        f"S1_LOGIC_RECOVERED={result['s1_logic_recovered']}", f"S1_R0_EXACT_REPLAY={result['s1_r0_exact_replay']}",
        "R48_CANDIDATES=0.10|0.20|0.30", "R48_SELECTION_PERIOD_MAX_DATE=2022-12-31",
        "R48_SELECTION_USED_ECONOMIC_OUTCOMES=FALSE", "R48_SELECTED=NONE",
        "R48_MECHANICAL_TARGET_MET=FALSE:NO_PRE2023_FROZEN_SUPPORT",
        "DUAL_OVERLAY_FREEZE_HASH=NOT_CREATED_NO_SELECTED_R48", "", "S1", "-" * 60,
        f"S1_SHARPE={result['s1_reference']['sharpe']}", f"S1_CAGR={result['s1_reference']['cagr']}",
        f"S1_MAXDD={result['s1_reference']['max_drawdown']}", f"S1_FF12_HHI={result['s1_reference']['ff12_hhi']}",
        f"S1_FF48_HHI={result['s1_reference']['ff48_hhi']}",
        f"S1_FF48_MAX_WEIGHT={result['s1_reference']['ff48_max_weight']}", "", "S1 DUAL", "-" * 60,
        f"DUAL_S1_SHARPE={na}", f"DUAL_S1_CAGR={na}", f"DUAL_S1_MAXDD={na}",
        f"DUAL_S1_FF12_HHI={na}", f"DUAL_S1_FF48_HHI={na}",
        f"DUAL_S1_FF48_HHI_REDUCTION_VS_S1={na}", f"DUAL_S1_FF48_MAX_WEIGHT_DELTA={na}",
        f"DUAL_S1_EFFECTIVE_FF48_COUNT={na}", f"DUAL_S1_TURNOVER_DELTA={na}", f"DUAL_S1_COST_DELTA={na}", "",
        "RIDGE S1", "-" * 60, f"RIDGE_S1_SHARPE={result['ridge_reference']['sharpe']}",
        f"RIDGE_S1_CAGR={result['ridge_reference']['cagr']}",
        f"RIDGE_S1_MAXDD={result['ridge_reference']['max_drawdown']}",
        f"RIDGE_S1_FF12_HHI={result['ridge_reference']['ff12_hhi']}",
        f"RIDGE_S1_FF48_HHI={result['ridge_reference']['ff48_hhi']}", "", "RIDGE DUAL", "-" * 60,
        f"RIDGE_DUAL_SHARPE={na}", f"RIDGE_DUAL_CAGR={na}", f"RIDGE_DUAL_MAXDD={na}",
        f"RIDGE_DUAL_FF12_HHI={na}", f"RIDGE_DUAL_FF48_HHI={na}",
        f"RIDGE_DUAL_FF48_HHI_REDUCTION_VS_RIDGE={na}", f"RIDGE_DUAL_FF48_HHI_VS_SIMPLE_S1={na}",
        f"RIDGE_DUAL_RESIDUAL_SHARPE={na}", f"RIDGE_DUAL_DOWNSIDE_CAPTURE={na}",
        f"RIDGE_DUAL_TURNOVER_DELTA={na}", "", "EXPOSED HISTORY DIAGNOSTICS", "-" * 60,
        "2023_DUAL_S1=NOT_EXECUTED_NO_R48_FREEZE", "2023_RIDGE_DUAL=NOT_EXECUTED_NO_R48_FREEZE",
        "2024_DUAL_S1=NOT_EXECUTED_NO_R48_FREEZE", "2024_RIDGE_DUAL=NOT_EXECUTED_NO_R48_FREEZE",
        "2025_DUAL_S1=NOT_EXECUTED_NO_R48_FREEZE", "2025_RIDGE_DUAL=NOT_EXECUTED_NO_R48_FREEZE",
        "PARAMETER_NEEDLE_WARNING=NOT_APPLICABLE:NO_SELECTED_R48", "", "VERDICT", "-" * 60,
        f"DUAL_OVERLAY_CLASSIFICATION={result['dual_overlay_classification']}",
        "DOES_FF48_MARGINAL_LAYER_FIX_RECONCENTRATION=NOT_TESTABLE_UNDER_FROZEN_SUPPORT",
        "DOES_DUAL_S1_RETAIN_ECONOMIC_VALUE=NOT_APPLICABLE:NO_R48_FREEZE",
        "DOES_RIDGE_RETAIN_INCREMENT_UNDER_SAME_DUAL_BUDGET=NOT_APPLICABLE:NO_R48_FREEZE",
        f"STRONGEST_SUPPORTING_EVIDENCE={result['strongest_supporting_evidence']}",
        f"MOST_DAMAGING_EVIDENCE={result['most_damaging_evidence']}",
        "RECOMMENDED_FORWARD_ARMS=RAW_A2|S1_SOFT_025|RIDGE_S1;NO_DUAL_ARM",
        "ANTI_OVERFIT_STATUS=PASS_FAIL_CLOSED_BEFORE_R48_OR_NEW_ECONOMIC_READ",
        "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS", "PREEXISTING_ACL_EXCEPTION_COUNT=2", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={result['final_artifact_count']}",
        "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "", "=" * 60]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    if OUT.exists():
        expected = {"final_report.md", "dual_overlay_contract.json", "concentration_only_r48_selection.csv", "classification.json", "hash_manifest.json"}
        require({path.name for path in OUT.iterdir() if path.is_file()} <= expected, "OUTPUT_ALREADY_EXISTS_UNEXPECTED_SURFACE")
    context = verify_inputs()
    # The concentration-only selector receives an empty, schema-valid frame.
    # No 2023-2025 candidate economics are calculated or exposed to it.
    empty = pd.DataFrame(columns=["session_date", "r48", "ff12_hhi", "ff48_hhi", "ff48_max_weight", "feasible_top20"])
    selected, selection = concentration_only_selection(empty)
    require(selected is None, "R48_SELECTED_WITHOUT_CALIBRATION_SUPPORT")

    s1_contract = {
        "s1_input_score": "NONE_AT_OVERLAY_LAYER;RAW_A2_MEMBERSHIP_AND_A2_PREDICTION_ALREADY_FROZEN",
        "s1_ff12_state": "DAILY_FF12_COUNTS_WITHIN_FROZEN_RAW_A2_TOP20",
        "s1_penalty_formula": "normalize((group_count/20) ** (1-0.25));equal_weight_within_group",
        "s1_penalty_strength": 0.25, "s1_budget_power": 0.75,
        "s1_selection_order": "NONE:REWEIGHT_ONLY_AFTER_RAW_TOP20_SELECTION",
        "s1_target_weight_rule": "group_budget/number_of_group_members",
        "s1_rebalance_rule": "FROZEN_DAILY_RAW_A2_TOP20_TARGET_MAP;10_BPS_BASE_COST_CONTRACT",
        "top_n": 20,
    }
    selection_rule = {
        "candidates": list(R48_CANDIDATES), "period_max_date": "2022-12-31",
        "rule": "SMALLEST_R48_WITH_MEAN_FF48_HHI_REDUCTION_GTE_5PCT;FF12_HHI_LTE_S1_X_1.01;MAX_FF48_LT_S1;ALL_TOP20_FEASIBLE",
        "economic_outcomes_allowed": False,
    }
    contract = {
        "task_id": TASK_ID, "status": "DUAL_OVERLAY_MECHANICAL_GATE_FAIL",
        "s1_contract": s1_contract, "s1_contract_hash": stable_hash(s1_contract),
        "r48_selection_rule": selection_rule, "r48_selection_rule_hash": stable_hash(selection_rule),
        "r48_selected": None, "dual_overlay_spec_hash": None, "dual_overlay_freeze_timestamp_utc": None,
        "s1_r0_exact_target_weight_replay": True,
        "s1_r0_max_weight_error": context["s1_max_weight_error"],
        "pre2023_top20_rows": 0, "pre2023_taxonomy_rows": 0,
        "frozen_candidate_count_per_session": 20, "required_selected_count": 20,
        "sequential_membership_change_possible": False,
        "failure_reasons": [
            "NO_PRE2023_FROZEN_TOP20_OR_TAXONOMY_SUPPORT_FOR_CONCENTRATION_ONLY_R48_SELECTION",
            "S1_IS_REWEIGHT_ONLY_AND_HAS_NO_SEQUENTIAL_SELECTION_UTILITY",
            "FROZEN_AVAILABLE_CANDIDATE_SET_EQUALS_REQUIRED_TOP20_SO_20_OF_20_SELECTION_CANNOT_CHANGE_MEMBERSHIP",
            "RIDGE_HISTORICAL_DAILY_OOF_SCORE_PATH_NOT_PERSISTED;FULL_PRE2026_MODEL_CANNOT_BACKCAST_2023_2025",
        ],
        "candidate_r48_economic_outcome_read_count": 0, "outcome_2026_read_count": 0,
        "taxonomy_hash": EXPECTED_TAXONOMY_LOGICAL_HASH,
        "ridge_model_id": context["ridge_manifest"]["model_id"], "ridge_model_sha256": EXPECTED_RIDGE_SHA256,
    }
    result = {
        "task_id": TASK_ID, "task_status": "DUAL_OVERLAY_MECHANICAL_GATE_FAIL",
        "2026_outcome_used": False, "2026_leakage_count": 0,
        "raw_reconciliation": "PASS_EXACT_1E-12",
        "raw_authoritative": context["raw"],
        "control_reference_role": "FROZEN_EXPOSED_2023_2024_REFERENCE_ONLY_NOT_USED_FOR_R48_SELECTION",
        "s1_reference": context["s1_reference"], "ridge_reference": context["ridge_reference"],
        "s1_reconciliation": "PASS_EXACT_TARGET_WEIGHTS",
        "ridge_identity_status": "PASS_HASH_VERIFIED_FROZEN_SPEC_NO_REFIT",
        "taxonomy_hash_status": "PASS_LOGICAL_AND_FILE_HASH_VERIFIED",
        "s1_logic_recovered": "PASS_REWEIGHT_ONLY_NO_SEQUENTIAL_SELECTION_UTILITY",
        "s1_r0_exact_replay": "PASS_EXACT_TARGET_WEIGHTS_TRIVIAL_20_OF_20_MEMBERSHIP",
        "r48_selected": None, "r48_mechanical_target_met": False,
        "dual_overlay_classification": "DUAL_OVERLAY_MECHANICAL_GATE_FAIL",
        "economic_diagnostics_executed": False, "model_fit_count": 0, "broker_action_count": 0,
        "canonical_mutation_count": 0, "taxonomy_mutation_count": 0,
        "strongest_supporting_evidence": "S1_FORMULA_AND_R0_TARGET_WEIGHTS_REPRODUCED_EXACTLY;RAW_RIDGE_TAXONOMY_IDENTITIES_PASS",
        "most_damaging_evidence": "PRE2023_CALIBRATION_SUPPORT_0;S1_HAS_NO_SELECTION_UTILITY;AVAILABLE_UNIVERSE_IS_EXACTLY_20_OF_20",
        "anti_overfit_status": "PASS_FAIL_CLOSED_BEFORE_R48_OR_NEW_ECONOMIC_READ",
        "task_local_anti_bloat_status": "PASS", "repository_anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_ACCOUNTING_INCOMPLETE_2",
        "preexisting_acl_exception_count": 2,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "dual_overlay_contract.json", contract)
    selection.to_csv(OUT / "concentration_only_r48_selection.csv", index=False)
    atomic_json(OUT / "classification.json", result)
    report = f"""# A2 dual-level marginal deconcentration R1

TASK_STATUS={result['task_status']}

2026_OUTCOME_USED=FALSE
2026_LEAKAGE_COUNT=0

## Executive verdict

`r48` could not be selected under the preregistered, concentration-only rule.
The frozen A2 Top20 and FF12/FF48 taxonomy both start on 2023-01-03, leaving
zero sessions through 2022-12-31.  No taxonomy was backfilled and no exposed
2023-2025 candidate economics were substituted for calibration.

S1 was recovered exactly, but its actual mechanism is target reweighting after
Raw A2 has already selected 20 names.  It has no sequential candidate utility:
the FF12 group budget is `normalize((group_count/20)^0.75)`, followed by equal
weight within each group.  The independent implementation matched all 750
frozen S1 target maps with maximum error {context['s1_max_weight_error']:.3g}.

The only taxonomy-covered candidate set contains those same final 20 names.
Sequentially selecting 20 of 20 cannot change membership; applying S1 weights
afterward leaves FF48 concentration unchanged for every r48.  A non-trivial
test would require a larger PIT candidate universe and pre-2023 frozen
taxonomy, which this task explicitly forbids constructing.

## Identity

- Authoritative Raw A2 exact replay: CAGR {context['raw']['cagr']:.16f}, Sharpe {context['raw']['sharpe']:.16f}, MaxDD {context['raw']['max_drawdown']:.15f}.
- Ridge model SHA256: `{EXPECTED_RIDGE_SHA256}`; no fit or backcast executed.
- Taxonomy logical hash: `{EXPECTED_TAXONOMY_LOGICAL_HASH}`; file SHA256 `{EXPECTED_TAXONOMY_FILE_SHA256}`.
- Candidate-r48 economic outcome reads: 0. 2026 outcome reads: 0.

The S1 and Ridge numbers in the terminal summary are hash-verified frozen
2023--2024 references only.  They were not made visible to the r48 selector;
no dual-arm return was calculated.

## Verdict

DUAL_OVERLAY_CLASSIFICATION=DUAL_OVERLAY_MECHANICAL_GATE_FAIL

The failure is structural, not an adverse historical performance result.  No
dual arm was frozen, no 2023-2025 dual economics were calculated, and the
recommended forward arms remain `RAW_A2|S1_SOFT_025|RIDGE_S1`.

Task-local Anti-Bloat passes.  The repository-wide hard gate remains failed by
the two registered pre-existing managed-ACL accounting objects; this task did
not retry or mutate them.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    require(len(files) + 1 <= 7, "ARTIFACT_BUDGET", len(files) + 1)
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
        "inputs": {
            "taxonomy": {"path": str(TAXONOMY), "sha256": sha256_file(TAXONOMY), "logical_hash": EXPECTED_TAXONOMY_LOGICAL_HASH},
            "top20": {"path": str(TOP20), "sha256": sha256_file(TOP20)},
            "portfolio": {"path": str(PORTFOLIO), "sha256": sha256_file(PORTFOLIO)},
            "ridge_model": {"path": str(UPSTREAM_MODEL), "sha256": sha256_file(UPSTREAM_MODEL)},
            "s1_source": {"path": str(BASE_SOURCE), "sha256": sha256_file(BASE_SOURCE)},
            "task_source": {"path": str(Path(__file__)), "sha256": sha256_file(Path(__file__))},
            "upstream_metadata": {"path": str(UPSTREAM_METADATA), "sha256": sha256_file(UPSTREAM_METADATA)},
        },
        "model_fit_count": 0, "candidate_r48_economic_outcome_read_count": 0,
        "2026_outcome_used": False, "2026_leakage_count": 0, "canonical_read_only": True,
    }
    atomic_json(OUT / "hash_manifest.json", manifest)
    result["final_artifact_count"] = len(list(OUT.iterdir()))
    atomic_json(OUT / "classification.json", result)
    # Re-sign classification after adding the count.
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest["artifacts"] = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files]
    atomic_json(OUT / "hash_manifest.json", manifest)
    print(render_terminal(result), flush=True)
    return result


def main() -> None:
    try:
        run()
    except Exception as exc:
        print(f"{TASK_ID}_FAIL={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
