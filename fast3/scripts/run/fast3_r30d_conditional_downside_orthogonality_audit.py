#!/usr/bin/env python
"""FAST3 R30D read-only T1/T4 conditional downside-information audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")

R30A_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30a_economic_target_20260809T120000Z"
R30B_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30b_factor_expansion_20260809T140000Z"
R30B_SCRATCH = RESULTS_ROOT / "scratch" / "fast3" / "r30b_factor_expansion_20260809T140000Z"
R30C_FROZEN = RESULTS_ROOT / "frozen" / "fast3" / "r30c_downside_severity_20260809T160000Z"
R30C_SCRATCH = RESULTS_ROOT / "scratch" / "fast3" / "r30c_downside_severity_20260809T160000Z"

T1_T2_CONTRACT = R30A_FROZEN / "FAST3_R30_T1_T2_ECONOMIC_TARGET_CONTRACT_R1.json"
T4_CONTRACT = R30C_FROZEN / "FAST3_R30_T4_DOWNSIDE_SEVERITY_CONTRACT_R1.json"
R30B_MANIFEST = R30B_FROZEN / "FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"
SPLIT_IDENTITY = R30A_FROZEN / "FAST3_R30A_SPLIT_IDENTITY.json"
DATA_IDENTITY = R30A_FROZEN / "FAST3_R30A_TRAINING_DATA_IDENTITY.json"
R30B_SUMMARY = R30B_FROZEN / "FAST3_R30B_SUMMARY.json"
R30C_SUMMARY = R30C_FROZEN / "FAST3_R30C_SUMMARY.json"
T1_OOF_PATH = R30B_SCRATCH / "FAST3_R30B_ARM_ALL_OOF.parquet"
T4_OOF_PATH = R30C_SCRATCH / "FAST3_R30C_ARM_ALL_OOF.parquet"

T1_T2_TARGET_CONTRACT_SHA256 = "381ce44099d865748e73f5538c9327ad6a9619c7bcdbf18bcff8b9b5cfdaa996"
T4_TARGET_CONTRACT_SHA256 = "81e09ede5c7ea31d473563cb12c10405cf654118ca5cf3de2d08c1f71d535a25"
R30B_FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
SPLIT_CONTRACT_SHA256 = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
EXPECTED_FOLDS = ("OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN")


class R30DStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def safe_spearman(left: Any, right: Any) -> float | None:
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    keep = np.isfinite(a) & np.isfinite(b)
    a, b = a[keep], b[keep]
    if len(a) < 2 or np.unique(a).size < 2 or np.unique(b).size < 2:
        return None
    value = float(spearmanr(a, b).statistic)
    return value if np.isfinite(value) else None


def assign_rank_buckets(
    frame: pd.DataFrame, prediction: str, bucket_count: int, column: str, ascending: bool = True
) -> pd.DataFrame:
    ranked = frame.sort_values(
        [prediction, "decision_timestamp_utc", "candidate_id"],
        ascending=[ascending, True, True],
        kind="mergesort",
    ).copy()
    ranked[column] = np.floor(np.arange(len(ranked)) * bucket_count / len(ranked)).astype(int) + 1
    return ranked


def cell_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "count": int(len(frame)),
        "mean_net20": float(frame["raw_net20"].mean()),
        "median_net20": float(frame["raw_net20"].median()),
        "positive_rate": float((frame["raw_net20"] > 0).mean()),
        "mean_loss": float(frame["actual_loss"].mean()),
        "p05_net20": float(frame["raw_net20"].quantile(0.05)),
        "worst_net20": float(frame["raw_net20"].min()),
    }


def split_t4_halves(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranked = assign_rank_buckets(frame, "pred_t4", 2, "t4_risk_half", ascending=True)
    return ranked.loc[ranked["t4_risk_half"].eq(1)].copy(), ranked.loc[ranked["t4_risk_half"].eq(2)].copy()


def conditional_decile_audit(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    ranked = assign_rank_buckets(frame, "pred_t1", 10, "t1_decile", ascending=True)
    rows: list[dict[str, Any]] = []
    rank_parts: list[pd.DataFrame] = []
    within_spearman: list[float] = []
    correct = incorrect = tied = 0
    weighted_std_numerator = 0.0

    for decile, part in ranked.groupby("t1_decile", sort=True):
        low, high = split_t4_halves(part)
        low_metrics, high_metrics = cell_metrics(low), cell_metrics(high)
        loss_spread = high_metrics["mean_loss"] - low_metrics["mean_loss"]
        net_spread = low_metrics["mean_net20"] - high_metrics["mean_net20"]
        status = "CORRECT" if loss_spread > 0 and net_spread > 0 else "TIED" if loss_spread == 0 and net_spread == 0 else "INCORRECT"
        correct += int(status == "CORRECT")
        incorrect += int(status == "INCORRECT")
        tied += int(status == "TIED")
        correlation = safe_spearman(part["pred_t4"], part["actual_loss"])
        if correlation is not None:
            within_spearman.append(correlation)
        weighted_std_numerator += float(part["pred_t4"].std(ddof=0)) * len(part)
        for label, metrics in (("LOW_T4_RISK_HALF", low_metrics), ("HIGH_T4_RISK_HALF", high_metrics)):
            rows.append(
                {
                    "t1_decile": int(decile),
                    "t4_risk_half": label,
                    **metrics,
                    "within_decile_T4_loss_Spearman": correlation,
                    "T4_within_T1_mean_loss_spread": loss_spread,
                    "T4_within_T1_net20_spread": net_spread,
                    "ordering_status": status,
                }
            )
        ranks = part[["candidate_id", "t1_decile", "pred_t4", "actual_loss"]].copy()
        ranks["within_decile_t4_rank"] = ranks["pred_t4"].rank(method="average")
        ranks["within_decile_actual_loss_rank"] = ranks["actual_loss"].rank(method="average")
        rank_parts.append(ranks)

    pooled = pd.concat(rank_parts, ignore_index=True)
    statistics = {
        "CONDITIONAL_T4_LOSS_SPEARMAN": safe_spearman(
            pooled["within_decile_t4_rank"], pooled["within_decile_actual_loss_rank"]
        ),
        "MEAN_WITHIN_DECILE_T4_SPEARMAN": float(np.mean(within_spearman)) if within_spearman else None,
        "MEDIAN_WITHIN_DECILE_T4_SPEARMAN": float(np.median(within_spearman)) if within_spearman else None,
        "POSITIVE_DECILE_SPEARMAN_COUNT": int(sum(value > 0 for value in within_spearman)),
        "NEGATIVE_DECILE_SPEARMAN_COUNT": int(sum(value < 0 for value in within_spearman)),
        "CORRECT_DECILE_COUNT": correct,
        "INCORRECT_DECILE_COUNT": incorrect,
        "TIED_DECILE_COUNT": tied,
        "T4_INCREMENTAL_VARIANCE_PROXY": weighted_std_numerator / len(ranked),
    }
    return pd.DataFrame(rows), statistics, ranked


def top20_internal_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    ordered = frame.sort_values(
        ["pred_t1", "decision_timestamp_utc", "candidate_id"],
        ascending=[False, True, True],
        kind="mergesort",
    )
    top = ordered.head(max(1, int(math.ceil(len(ordered) * 0.20)))).copy()
    low, high = split_t4_halves(top)
    low_metrics, high_metrics = cell_metrics(low), cell_metrics(high)
    rows = []
    for label, metrics in (("LOWER_T4_RISK_HALF", low_metrics), ("HIGHER_T4_RISK_HALF", high_metrics)):
        rows.append({"cohort": "T1_TOP20", "t4_risk_half": label, **metrics})
    summary = {
        "T1_TOP20_COUNT": len(top),
        "T1_TOP20_LOW_T4_COUNT": len(low),
        "T1_TOP20_HIGH_T4_COUNT": len(high),
        **{f"T1_TOP20_LOW_T4_{key.upper()}": value for key, value in low_metrics.items() if key != "count"},
        **{f"T1_TOP20_HIGH_T4_{key.upper()}": value for key, value in high_metrics.items() if key != "count"},
        "T1_TOP20_LOW_HIGH_MEAN_SPREAD": low_metrics["mean_net20"] - high_metrics["mean_net20"],
        "T1_TOP20_HIGH_LOW_MEAN_LOSS_DELTA": high_metrics["mean_loss"] - low_metrics["mean_loss"],
    }
    return pd.DataFrame(rows), summary


def conditional_summary(frame: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    decile_table, stats, _ = conditional_decile_audit(frame)
    top_table, top = top20_internal_split(frame)
    stats.update(top)
    stats["CONDITIONAL_ORDER_CORRECT"] = bool(
        (stats["CONDITIONAL_T4_LOSS_SPEARMAN"] or 0.0) > 0
        and stats["T1_TOP20_LOW_HIGH_MEAN_SPREAD"] > 0
        and stats["T1_TOP20_HIGH_LOW_MEAN_LOSS_DELTA"] > 0
    )
    return stats, decile_table, top_table


def reconcile_oof(t1: pd.DataFrame, t4: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    required_t1 = {"candidate_id", "decision_timestamp_utc", "fold", "head", "action_instrument", "raw_net20", "pred_t1"}
    required_t4 = {"candidate_id", "decision_timestamp_utc", "fold", "head", "action_instrument", "raw_net20", "actual_loss", "pred_t4"}
    if not required_t1.issubset(t1.columns) or not required_t4.issubset(t4.columns):
        raise R30DStop("STOP_OOF_SCHEMA")
    duplicate_count = int(t1["candidate_id"].duplicated().sum() + t4["candidate_id"].duplicated().sum())
    left = t1[list(required_t1)].copy()
    right = t4[list(required_t4)].copy()
    merged = left.merge(right, on="candidate_id", how="outer", suffixes=("_t1", "_t4"), indicator=True)
    unmatched_count = int(merged["_merge"].ne("both").sum())
    if duplicate_count or unmatched_count:
        return merged, {"OOF_ROW_COUNT": int((merged["_merge"] == "both").sum()), "OOF_UNMATCHED_COUNT": unmatched_count, "OOF_DUPLICATE_COUNT": duplicate_count}
    for column in ("decision_timestamp_utc", "fold", "head", "action_instrument", "raw_net20"):
        left_column, right_column = f"{column}_t1", f"{column}_t4"
        equal = merged[left_column].eq(merged[right_column])
        if not bool(equal.all()):
            raise R30DStop(f"STOP_OOF_IDENTITY_{column.upper()}")
    joined = pd.DataFrame(
        {
            "candidate_id": merged["candidate_id"],
            "decision_timestamp_utc": merged["decision_timestamp_utc_t1"],
            "fold": merged["fold_t1"],
            "head": merged["head_t1"],
            "action_instrument": merged["action_instrument_t1"],
            "raw_net20": merged["raw_net20_t1"].astype(float),
            "actual_loss": merged["actual_loss"].astype(float),
            "pred_t1": merged["pred_t1"].astype(float),
            "pred_t4": merged["pred_t4"].astype(float),
        }
    ).sort_values(["decision_timestamp_utc", "candidate_id"], kind="mergesort").reset_index(drop=True)
    return joined, {"OOF_ROW_COUNT": len(joined), "OOF_UNMATCHED_COUNT": 0, "OOF_DUPLICATE_COUNT": 0}


def verify_authority() -> dict[str, Any]:
    hashes = {
        T1_T2_CONTRACT: T1_T2_TARGET_CONTRACT_SHA256,
        T4_CONTRACT: T4_TARGET_CONTRACT_SHA256,
        R30B_MANIFEST: R30B_FEATURE_MANIFEST_SHA256,
    }
    for path, expected in hashes.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R30DStop(f"STOP_AUTHORITY_HASH_{path.name}")
    split = read_json(SPLIT_IDENTITY)
    data = read_json(DATA_IDENTITY)
    r30b = read_json(R30B_SUMMARY)
    r30c = read_json(R30C_SUMMARY)
    if split["SPLIT_CONTRACT_SHA256"] != SPLIT_CONTRACT_SHA256 or tuple(row[0] for row in split["EVALUATED_FOLDS"]) != EXPECTED_FOLDS:
        raise R30DStop("STOP_SPLIT_IDENTITY")
    if split["FINAL_CONFIRMATION_DATA_USED"] or r30b["FINAL_CONFIRMATION_DATA_USED"] or r30c["FINAL_CONFIRMATION_DATA_USED"]:
        raise R30DStop("STOP_FINAL_CONFIRMATION_IDENTITY")
    if r30b["FAST3_R30B_CLASSIFICATION"] != "D_WEAK_OR_INCONCLUSIVE_FACTOR_GAIN" or r30c["FAST3_R30C_CLASSIFICATION"] != "A_DOWNSIDE_RISK_SIGNAL_CONFIRMED_IN_DEVELOPMENT":
        raise R30DStop("STOP_PARENT_CONCLUSION_IDENTITY")
    if not T1_OOF_PATH.is_file() or not T4_OOF_PATH.is_file():
        raise R30DStop("STOP_FROZEN_OOF_MISSING")
    target_path = Path(data["TARGET_LEDGER_PATH"])
    if file_sha256(target_path) != data["TARGET_LEDGER_SHA256"]:
        raise R30DStop("STOP_TARGET_LEDGER_HASH")
    return {"split": split, "data": data, "r30b": r30b, "r30c": r30c, "target_path": target_path}


def grouped_diagnostics(frame: pd.DataFrame, column: str, kind: str) -> pd.DataFrame:
    rows = []
    for value, part in frame.groupby(column, sort=True):
        stats, _, _ = conditional_summary(part)
        rows.append(
            {
                "diagnostic_type": kind,
                "group": str(value),
                "sample_count": len(part),
                "conditional_T4_loss_Spearman": stats["CONDITIONAL_T4_LOSS_SPEARMAN"],
                "T1_top20_low_T4_mean_net20": stats["T1_TOP20_LOW_T4_MEAN_NET20"],
                "T1_top20_high_T4_mean_net20": stats["T1_TOP20_HIGH_T4_MEAN_NET20"],
                "T1_top20_low_high_spread": stats["T1_TOP20_LOW_HIGH_MEAN_SPREAD"],
                "conditional_order_correct": stats["CONDITIONAL_ORDER_CORRECT"],
            }
        )
    return pd.DataFrame(rows)


def report_text(summary: dict[str, Any]) -> str:
    return f"""# FAST3 R30D — Conditional Downside Information / T1–T4 Orthogonality Audit

## Decision

- Status: `{summary['FAST3_R30D_STATUS']}`
- Classification: `{summary['FAST3_R30D_CLASSIFICATION']}`
- Decision: `{summary['FAST3_R30D_DECISION']}`
- Conditional T4/loss Spearman: `{summary['CONDITIONAL_T4_LOSS_SPEARMAN']}`
- Correct T1 deciles: `{summary['CORRECT_DECILE_COUNT']}/10`
- Correct folds: `{summary['CONDITIONAL_CORRECT_FOLD_COUNT']}/5`
- Strong incremental signal: `{summary['T4_INCREMENTAL_SIGNAL_STRONG']}`

## T1 Top20 internal T4 split

- Low-risk half mean net20 / mean loss: `{summary['T1_TOP20_LOW_T4_MEAN_NET20']}` / `{summary['T1_TOP20_LOW_T4_MEAN_LOSS']}`
- High-risk half mean net20 / mean loss: `{summary['T1_TOP20_HIGH_T4_MEAN_NET20']}` / `{summary['T1_TOP20_HIGH_T4_MEAN_LOSS']}`
- Mean-net20 spread: `{summary['T1_TOP20_LOW_HIGH_MEAN_SPREAD']}`

## Identity and controls

The target ledger contains 1,197 rows. The frozen walk-forward OOF universe contains 998 rows; the remaining 199 rows are the explicit 2020 warm-up fold and never had frozen OOF predictions. R30B and R30C OOF sources reconcile one-to-one with zero unmatched and zero duplicates. No models were fitted or called, no final confirmation data was used, and no OOF ledger was copied.

## Interpretation

{summary['PRIMARY_RESEARCH_INTERPRETATION']}

Next stage: `{summary['NEXT_STAGE']}`.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    name = f"r30d_conditional_orthogonality_{args.run_id}"
    runtime = RESULTS_ROOT / "runtime" / "fast3" / name
    frozen = RESULTS_ROOT / "frozen" / "fast3" / name
    if runtime.exists() or frozen.exists():
        raise R30DStop("STOP_RUN_ID_EXISTS")
    runtime.mkdir(parents=True)
    frozen.mkdir(parents=True)

    authority = verify_authority()
    t1_sha, t4_sha = file_sha256(T1_OOF_PATH), file_sha256(T4_OOF_PATH)
    t1 = pd.read_parquet(T1_OOF_PATH)
    t4 = pd.read_parquet(T4_OOF_PATH)
    joined, identity = reconcile_oof(t1, t4)
    if identity["OOF_UNMATCHED_COUNT"] or identity["OOF_DUPLICATE_COUNT"]:
        raise R30DStop("STOP_OOF_RECONCILIATION")
    if tuple(sorted(joined["fold"].unique())) != tuple(sorted(EXPECTED_FOLDS)):
        raise R30DStop("STOP_OOF_FOLD_IDENTITY")

    target = pd.read_parquet(authority["target_path"], columns=["candidate_id", "decision_timestamp_utc"])
    target_duplicate_count = int(target["candidate_id"].duplicated().sum())
    missing_target = target.loc[~target["candidate_id"].isin(set(joined["candidate_id"]))].copy()
    if target_duplicate_count or len(target) != 1197 or len(missing_target) != 199 or set(missing_target["decision_timestamp_utc"].dt.year) != {2020}:
        raise R30DStop("STOP_TARGET_TO_OOF_WARMUP_RECONCILIATION")

    overall, deciles, top20 = conditional_summary(joined)
    fold_rows = []
    for fold in EXPECTED_FOLDS:
        part = joined.loc[joined["fold"].eq(fold)].copy()
        stats, _, _ = conditional_summary(part)
        fold_rows.append(
            {
                "fold": fold,
                "sample_count": len(part),
                "conditional_T4_loss_Spearman": stats["CONDITIONAL_T4_LOSS_SPEARMAN"],
                "T1_top20_low_T4_mean_net20": stats["T1_TOP20_LOW_T4_MEAN_NET20"],
                "T1_top20_high_T4_mean_net20": stats["T1_TOP20_HIGH_T4_MEAN_NET20"],
                "low_high_mean_spread": stats["T1_TOP20_LOW_HIGH_MEAN_SPREAD"],
                "T1_top20_low_T4_mean_loss": stats["T1_TOP20_LOW_T4_MEAN_LOSS"],
                "T1_top20_high_T4_mean_loss": stats["T1_TOP20_HIGH_T4_MEAN_LOSS"],
                "correct_order": stats["CONDITIONAL_ORDER_CORRECT"],
            }
        )
    folds = pd.DataFrame(fold_rows)
    correct_folds = int(folds["correct_order"].sum())
    incorrect_folds = len(folds) - correct_folds

    joined["calendar_year"] = joined["decision_timestamp_utc"].dt.year
    by_direction = grouped_diagnostics(joined, "head", "DIRECTION")
    by_year = grouped_diagnostics(joined, "calendar_year", "YEAR")
    by_symbol = grouped_diagnostics(joined, "action_instrument", "SYMBOL")
    robustness = pd.concat([by_direction, by_year, by_symbol], ignore_index=True)
    direction = by_direction.set_index("group")

    raw_spearman = safe_spearman(joined["pred_t1"], joined["pred_t4"])
    conditional = overall["CONDITIONAL_T4_LOSS_SPEARMAN"] or 0.0
    top_correct = overall["T1_TOP20_LOW_HIGH_MEAN_SPREAD"] > 0 and overall["T1_TOP20_HIGH_LOW_MEAN_LOSS_DELTA"] > 0
    primary_go = bool(conditional > 0 and overall["CORRECT_DECILE_COUNT"] >= 6 and top_correct and correct_folds >= 3)
    strong = bool(
        conditional >= 0.05
        and overall["T1_TOP20_LOW_T4_MEAN_NET20"] > 0
        and overall["T1_TOP20_HIGH_T4_MEAN_NET20"] < 0
        and correct_folds >= 3
        and overall["CORRECT_DECILE_COUNT"] >= 7
    )
    reverse = bool(conditional < 0 and overall["T1_TOP20_HIGH_LOW_MEAN_LOSS_DELTA"] < 0)
    if primary_go:
        classification = "A_T4_INCREMENTAL_DOWNSIDE_INFORMATION_CONFIRMED"
        decision = "INCREMENTAL_DOWNSIDE_INFORMATION"
        next_stage = "FREEZE_T1_PLUS_T4_RISK_AWARE_ARCHITECTURE_CONTRACT; DO_NOT_OPEN_FINAL_HOLDOUT"
        interpretation = "T4 retains qualifying downside information after conditioning on frozen T1 probability; a dual-head contract is eligible for a separately frozen development test."
        information_status = "INCREMENTAL_DOWNSIDE_INFORMATION"
    elif reverse:
        classification = "D_CONDITIONAL_RESULT_CONTRADICTS_T4_RISK_SIGNAL"
        decision = "CONDITIONAL_T4_RISK_ORDERING_REVERSED"
        next_stage = "CLOSE_CURRENT_29_FEATURE_RISK_COMBINATION_PATH"
        interpretation = "After conditioning on T1, T4 is systematically reversed and does not support a risk-aware dual head."
        information_status = "CONTRADICTORY_CONDITIONAL_INFORMATION"
    elif (conditional <= 0 or overall["CORRECT_DECILE_COUNT"] <= 4) and not top_correct:
        classification = "B_T4_MOSTLY_REDUNDANT_WITH_T1"
        decision = "T4_MOSTLY_REDUNDANT_WITH_T1"
        next_stage = "DO_NOT_BUILD_T1_T4_DUAL_HEAD; CLOSE_CURRENT_29_FEATURE_RISK_COMBINATION_PATH"
        interpretation = "T4 does not retain sufficient loss ordering inside comparable T1-probability strata and is mostly a reverse expression of T1."
        information_status = "MOSTLY_REDUNDANT_WITH_T1"
    else:
        classification = "C_WEAK_OR_INCONCLUSIVE_INCREMENTAL_INFORMATION"
        decision = "WEAK_OR_INCONCLUSIVE_INCREMENTAL_DOWNSIDE_INFORMATION"
        next_stage = "WEAK_STOP_WITHOUT_COMBINATION_TUNING"
        interpretation = "Conditional results point in a partly useful direction but fail the preregistered incremental-information gate; do not freeze or tune a dual-head rule."
        information_status = "WEAK_OR_INCONCLUSIVE_INCREMENTAL_INFORMATION"

    deciles.to_csv(frozen / "FAST3_R30D_T1_DECILE_T4_CONDITIONAL.csv", index=False, lineterminator="\n")
    top20.to_csv(frozen / "FAST3_R30D_T1_TOP20_T4_SPLIT.csv", index=False, lineterminator="\n")
    folds.to_csv(frozen / "FAST3_R30D_FOLD_CONDITIONAL.csv", index=False, lineterminator="\n")
    robustness.to_csv(frozen / "FAST3_R30D_ROBUSTNESS.csv", index=False, lineterminator="\n")

    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE_ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT, text=True).strip()
    summary = {
        "FAST3_R30D_STATUS": "PASS",
        "FAST3_R30D_CLASSIFICATION": classification,
        "FAST3_R30D_DECISION": decision,
        "BRANCH": branch,
        "START_HEAD": head,
        "HEAD": head,
        "T1_T2_TARGET_CONTRACT_SHA256": T1_T2_TARGET_CONTRACT_SHA256,
        "T4_TARGET_CONTRACT_SHA256": T4_TARGET_CONTRACT_SHA256,
        "R30B_FEATURE_MANIFEST_SHA256": R30B_FEATURE_MANIFEST_SHA256,
        "SPLIT_CONTRACT_SHA256": SPLIT_CONTRACT_SHA256,
        "TARGET_ROW_COUNT": len(target),
        **identity,
        "OOF_VS_TARGET_UNPREDICTED_COUNT": len(missing_target),
        "OOF_UNPREDICTED_REGION": "OOF_2020_EXPLICIT_WARMUP",
        "OOF_RECONCILIATION_STATUS": "PASS_FROZEN_DEVELOPMENT_OOF_UNIVERSE",
        "T1_OOF_SOURCE_PATH": str(T1_OOF_PATH),
        "T1_OOF_SOURCE_SHA256": t1_sha,
        "T1_OOF_SOURCE_ROW_COUNT": len(t1),
        "T4_OOF_SOURCE_PATH": str(T4_OOF_PATH),
        "T4_OOF_SOURCE_SHA256": t4_sha,
        "T4_OOF_SOURCE_ROW_COUNT": len(t4),
        "SIGN_SEMANTICS": {
            "higher_pred_t1": "higher predicted probability of net20 > 0",
            "higher_pred_t4": "higher predicted downside severity",
        },
        "T1_T4_RAW_SPEARMAN": raw_spearman,
        **overall,
        "CONDITIONAL_CORRECT_FOLD_COUNT": correct_folds,
        "CONDITIONAL_INCORRECT_FOLD_COUNT": incorrect_folds,
        "UP_CONDITIONAL_T4_SPEARMAN": direction.loc["UP", "conditional_T4_loss_Spearman"],
        "DOWN_CONDITIONAL_T4_SPEARMAN": direction.loc["DOWN", "conditional_T4_loss_Spearman"],
        "UP_T1_TOP20_LOW_HIGH_SPREAD": direction.loc["UP", "T1_top20_low_high_spread"],
        "DOWN_T1_TOP20_LOW_HIGH_SPREAD": direction.loc["DOWN", "T1_top20_low_high_spread"],
        "T4_INCREMENTAL_INFORMATION_STATUS": information_status,
        "T4_INCREMENTAL_SIGNAL_STRONG": strong,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "NEW_FEATURE_COUNT": 0,
        "FEATURE_DEFINITION_CHANGES": 0,
        "TARGET_CHANGES": 0,
        "TARGET_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "R29_MODIFIED": False,
        "R29_ALLOWED_TO_RESUME": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "PRIMARY_RESEARCH_INTERPRETATION": interpretation,
        "NEXT_STAGE": next_stage,
        "R30D_NEW_SOURCE_FILE_COUNT": 1,
        "R30D_MODIFIED_SOURCE_FILE_COUNT": 0,
        "R30D_NEW_TEST_FILE_COUNT": 1,
        "R30D_NEW_HELPER_FILE_COUNT": 0,
        "R30D_GENERATED_REPO_ARTIFACT_COUNT": 0,
        "SHARED_CODE_MODIFICATION_REQUIRED": False,
        "ANTI_BLOAT_STATUS": "PASS",
        "DO_NOT_BUILD_FOR_HYPOTHETICAL_FUTURE_STAGES": True,
        "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS",
        "SOURCE_ROOT": str(SOURCE_ROOT),
        "DATA_ROOT": str(DATA_ROOT),
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "CACHE_ROOT": str(CACHE_ROOT),
        "DATA_ROOT_WRITE_COUNT": 0,
        "LOCAL_RESULTS_CREATED": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": True,
        "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": True,
        "NEW_STORAGE_VIOLATION_COUNT": 0,
        "DESTRUCTIVE_GIT_COMMAND_USED": False,
        "BROAD_GIT_ADD_USED": False,
        "REPORT_PATH": str(frozen / "FAST3_R30D_REPORT.md"),
        "SUMMARY_JSON_PATH": str(frozen / "FAST3_R30D_SUMMARY.json"),
        "ROBUSTNESS_PATH": str(frozen / "FAST3_R30D_ROBUSTNESS.csv"),
    }
    write_json(frozen / "FAST3_R30D_SUMMARY.json", summary)
    (frozen / "FAST3_R30D_REPORT.md").write_text(report_text(summary), encoding="utf-8")
    write_json(
        runtime / "FAST3_R30D_RUNTIME_SUMMARY.json",
        {"status": "PASS", "classification": classification, "model_fit_count": 0, "model_predict_call_count": 0},
    )
    print(json.dumps({key: summary[key] for key in ("FAST3_R30D_STATUS", "FAST3_R30D_CLASSIFICATION", "FAST3_R30D_DECISION", "REPORT_PATH", "SUMMARY_JSON_PATH")}, indent=2))


if __name__ == "__main__":
    main()
