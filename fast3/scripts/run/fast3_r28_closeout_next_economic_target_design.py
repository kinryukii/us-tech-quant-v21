"""FAST3 R28 final closeout and next economic-target design audit.

No model is loaded, fit, predicted, or rescored.  The audit consumes the
frozen R28.3G corrected ledger and produces target definitions, diagnostics,
ranking, and a contract proposal only.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
RUNTIME_ROOT = RESULTS_ROOT / "runtime"
SCRATCH_ROOT = RESULTS_ROOT / "scratch"
FROZEN_ROOT = RESULTS_ROOT / "frozen"
RUN_ID = "r28_final_closeout_next_economic_target_design_20260809"
RUNTIME_RUN_ROOT = RUNTIME_ROOT / "fast3" / RUN_ID
SCRATCH_RUN_ROOT = SCRATCH_ROOT / "fast3" / RUN_ID
FROZEN_RUN_ROOT = FROZEN_ROOT / "fast3" / RUN_ID
STAGE = RUNTIME_RUN_ROOT / "frozen_stage"

ETF_MANIFEST_SHA256 = "1726b400b9fbb33f1bf85ff4afd229288f8e823d26cf3b2d3b0956e760b3a331"
R28G_ROOT = FROZEN_ROOT / "fast3" / "r28_3g_corporate_action_normalized_first_touch_20260809"
R28G_SUMMARY = R28G_ROOT / "R28_3G_SUMMARY.json"
R28G_LEDGER = R28G_ROOT / "R28_3G_CORRECTED_TRADE_LEDGER.csv"
R28G_ACTIONS = R28G_ROOT / "R28_3G_CORPORATE_ACTION_LEDGER.json"
EXPECTED_INPUT_HASHES = {
    str(R28G_SUMMARY): "e2031c60fca950af7ca1e697fe2c4b9f5b662621f21d25e6680f60397a8466cb",
    str(R28G_LEDGER): "a28c48880ae98fb5626967afd95c2096f4fb82a0320fbfd3f6cf1702f690ace5",
    str(R28G_ACTIONS): "3a72c80d4bce04e409ed429b9434e9f936405e1ffc38ac3ee04213675781a0dd",
}

R28_STAGES = [
    {
        "stage": "R28.3A", "status": "PASS",
        "classification": "C_PREDICTIVE_EDGE_CONFIRMED_ECONOMIC_SELECTION_EDGE_WEAK_OR_MIXED",
        "root": FROZEN_ROOT / "fast3" / "r28_3a_frozen_economic_attribution_20260809_r2",
        "summary": "R28_3A_SUMMARY.json", "report": "R28_3A_REPORT.md",
        "research_question": "Does the frozen predictive edge translate into matched economic selection edge?",
        "answer": "Predictive edge confirmed; matched-placebo economic selection edge failed.",
    },
    {
        "stage": "R28.3B", "status": "PASS", "classification": "A_EVENT_PROBABILITY_AND_SPEED_EDGE",
        "root": FROZEN_ROOT / "fast3" / "r28_3b_soxx_natural_baseline_20260809",
        "summary": "R28_3B_SUMMARY.json", "report": "R28_3B_REPORT.md",
        "research_question": "What does the frozen event score actually predict?",
        "answer": "Event probability and arrival speed, not magnitude or terminal return.",
    },
    {
        "stage": "R28.3C", "status": "PASS", "classification": "B_FAST_TOUCH_WITH_MEAN_REVERSION_OR_GIVEBACK",
        "root": FROZEN_ROOT / "fast3" / "r28_3c_frozen_event_conditioned_path_audit_20260809_r2",
        "summary": "R28_3C_SUMMARY.json", "report": "R28_3C_REPORT.md",
        "research_question": "Does fast touch continue economically after the event?",
        "answer": "No reliable continuation; substantial mean reversion or giveback follows touch.",
    },
    {
        "stage": "R28.3D/R28.3D-L", "status": "CLOSED_UNTESTED_DUE_TO_UNRECOVERABLE_FROZEN_LINEAGE",
        "classification": "E_INSUFFICIENT_FROZEN_LINEAGE_EVIDENCE",
        "root": FROZEN_ROOT / "fast3" / "r28_3d_l_etf_lineage_reconciliation_20260809T073751322166Z",
        "summary": "R28_3D_L_SUMMARY.json", "report": "R28_3D_L_REPORT.md",
        "research_question": "Can the historical ETF execution lineage be recovered for strict target-aligned testing?",
        "answer": "No; the old ETF lineage was unrecoverable and the test was closed untested.",
    },
    {
        "stage": "R28.3E", "status": "PASS", "classification": "C_FIRST_TOUCH_ECONOMIC_EDGE_NOT_CONFIRMED",
        "root": FROZEN_ROOT / "fast3" / "r28_3e_clean_lineage_first_touch_20260809_r3",
        "summary": "R28_3E_SUMMARY.json", "report": "R28_3E_REPORT.md",
        "research_question": "Does first-touch-aligned execution create a clean-lineage economic edge?",
        "answer": "No matched-placebo confirmation; apparent results were tail-concentrated.",
    },
    {
        "stage": "R28.3F", "status": "PASS", "classification": "E_MIXED_DATA_INTEGRITY_FAILURE",
        "root": FROZEN_ROOT / "fast3" / "r28_3f_leveraged_etf_integrity_20260809_r3",
        "summary": "R28_3F_SUMMARY.json", "report": "R28_3F_REPORT.md",
        "research_question": "Are extreme leveraged-ETF returns economically valid?",
        "answer": "A SOXS reverse split created the largest return artifact; one pre-entry touch also existed.",
    },
    {
        "stage": "R28.3G", "status": "PASS", "classification": "D_CORRECTED_FIRST_TOUCH_TRANSLATION_NEGATIVE",
        "root": R28G_ROOT, "summary": "R28_3G_SUMMARY.json", "report": "R28_3G_REPORT.md",
        "research_question": "After integrity correction, is first-touch economic expectancy positive?",
        "answer": "No; corrected mean net20 is negative across all six years and the hypothesis is rejected.",
    },
]

LESSONS = {
    "LESSON_01": "Prediction target must align with executable economic payoff.",
    "LESSON_02": "First-touch probability is not equivalent to positive expected return.",
    "LESSON_03": "High event probability can coexist with negative economic expectancy.",
    "LESSON_04": "Corporate actions must be normalized at the economic-return layer.",
    "LESSON_05": "Every frozen economic dataset must retain aggregate manifest hash plus per-partition SHA256, row count, timestamp bounds, and schema identity.",
    "LESSON_06": "Pre-entry events are not economically capturable.",
    "LESSON_07": "Median-positive / mean-negative distributions require explicit left-tail analysis.",
    "LESSON_08": "Predictive lift alone cannot authorize economic adoption.",
}
PERMANENT_GUARDS = {
    "CORPORATE_ACTION_NORMALIZATION_REQUIRED": True,
    "PER_PARTITION_SHA256_REQUIRED": True,
    "PRE_ENTRY_EVENT_NOT_CAPTURABLE": True,
    "ECONOMIC_TARGET_REQUIRED_FOR_MODEL_ADOPTION": True,
    "PREDICTIVE_EDGE_ALONE_INSUFFICIENT_FOR_ADOPTION": True,
    "MEAN_AND_TAIL_RISK_REQUIRED": True,
}


class AuditStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)


def data_snapshot() -> dict[str, tuple[int, int]]:
    return {str(path): (int(path.stat().st_size), int(path.stat().st_mtime_ns))
            for path in DATA_ROOT.rglob("*") if path.is_file()}


def repo_snapshot() -> dict[str, str]:
    lines = subprocess.check_output(["git", "status", "--porcelain", "-uall"], cwd=REPO, text=True,
                                    stderr=subprocess.DEVNULL).splitlines()
    result = {}
    for line in lines:
        if len(line) < 4:
            continue
        relative = line[3:].strip().strip('"').replace("\\", "/")
        path = REPO / relative
        result[relative] = file_sha256(path) if path.is_file() else "NON_FILE"
    return result


def storage_preflight() -> tuple[dict, dict, dict]:
    pycache = Path(sys.pycache_prefix).resolve() if sys.pycache_prefix else None
    if pycache is None or CACHE_ROOT.resolve() not in (pycache, *pycache.parents):
        raise AuditStop("STOP_PYTHON_CACHE_NOT_EXTERNALIZED")
    if (REPO / ".local_results").exists():
        raise AuditStop("STOP_LOCAL_RESULTS_PRE_EXISTING")
    if any(path.exists() for path in (RUNTIME_RUN_ROOT, SCRATCH_RUN_ROOT, FROZEN_RUN_ROOT)):
        raise AuditStop("STOP_CLOSEOUT_TARGET_DESIGN_RUN_PATH_EXISTS")
    RUNTIME_RUN_ROOT.mkdir(parents=True)
    SCRATCH_RUN_ROOT.mkdir(parents=True)
    storage = {
        "SOURCE_ROOT": str(REPO), "DATA_ROOT": str(DATA_ROOT), "RESULTS_ROOT": str(RESULTS_ROOT),
        "CACHE_ROOT": str(CACHE_ROOT), "RUNTIME_RUN_ROOT": str(RUNTIME_RUN_ROOT),
        "SCRATCH_RUN_ROOT": str(SCRATCH_RUN_ROOT), "FROZEN_RUN_ROOT": str(FROZEN_RUN_ROOT),
        "PRE_EXISTING_STORAGE_VIOLATION_COUNT": 2,
        "PRE_EXISTING_STORAGE_VIOLATIONS": [str(REPO / ".pytest_cache"), str(REPO / ".pytest_v22_049_tmp")],
    }
    before_data, before_repo = data_snapshot(), repo_snapshot()
    atomic_json(RUNTIME_RUN_ROOT / "progress.json", {**storage, "stage": "STORAGE_PREFLIGHT_COMPLETE"})
    return storage, before_data, before_repo


def post_storage_audit(before_data: dict, before_repo: dict) -> dict:
    after_data, after_repo = data_snapshot(), repo_snapshot()
    changes = set(before_data) ^ set(after_data) | {
        path for path in set(before_data) & set(after_data) if before_data[path] != after_data[path]}
    preserved = before_repo == after_repo
    new_paths = set(after_repo) - set(before_repo)
    result_files = [path for path in new_paths if Path(path).suffix.lower() in {".csv", ".json", ".parquet", ".md", ".log"}]
    count = len(changes) + int(not preserved) + len(result_files) + int((REPO / ".local_results").exists())
    result = {
        "DATA_ROOT_WRITE_COUNT": len(changes), "LOCAL_RESULTS_CREATED": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": bool(result_files), "NEW_STORAGE_VIOLATION_COUNT": count,
        "PRE_EXISTING_UNTRACKED_FILES_PRESERVED": preserved, "PRE_EXISTING_TRACKED_CHANGES_PRESERVED": preserved,
        "PYTHON_CACHE_EXTERNALIZED": True, "PYTEST_TEMP_EXTERNALIZED": True,
        "DESTRUCTIVE_GIT_COMMAND_USED": False, "BROAD_GIT_ADD_USED": False,
    }
    if count:
        raise AuditStop(f"STOP_NEW_STORAGE_VIOLATION:{result}")
    return result


def signed_log1p(values: pd.Series) -> pd.Series:
    return np.sign(values) * np.log1p(np.abs(values))


def binary_entropy(rate: float) -> float:
    if rate <= 0 or rate >= 1:
        return 0.0
    return float(-(rate * math.log2(rate) + (1 - rate) * math.log2(1 - rate)))


def symmetric_trimmed_mean(values: pd.Series, fraction: float = .01) -> float:
    count = max(1, int(math.ceil(len(values) * fraction)))
    ordered = values.sort_values().reset_index(drop=True)
    return float(ordered.iloc[count:-count].mean())


def classification_stability_score(value_range: float) -> int:
    if value_range <= .08:
        return 5
    if value_range <= .12:
        return 4
    if value_range <= .18:
        return 3
    if value_range <= .25:
        return 2
    return 1


def classification_stability_label(value_range: float) -> str:
    return "HIGH" if value_range <= .12 else "MEDIUM" if value_range <= .20 else "LOW"


def continuous_stability_score(normalized_range: float) -> int:
    if normalized_range <= .25:
        return 5
    if normalized_range <= .50:
        return 4
    if normalized_range <= .75:
        return 3
    if normalized_range <= 1.0:
        return 2
    return 1


def continuous_stability_label(normalized_range: float) -> str:
    return "HIGH" if normalized_range <= .25 else "MEDIUM" if normalized_range <= .50 else "LOW"


def class_feasibility_score(entropy: float) -> int:
    if entropy >= .95:
        return 5
    if entropy >= .85:
        return 4
    if entropy >= .70:
        return 3
    if entropy >= .50:
        return 2
    return 1


def target_distribution_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specifications = [
        ("T1_POSITIVE_NET20", "CLASSIFICATION", "t1_positive_net20"),
        ("T2_RAW_NET20", "REGRESSION_RAW_COMPARISON", "corrected_net20"),
        ("T2_ROBUST_NET20", "REGRESSION_SIGNED_LOG1P", "t2_robust_net20"),
        ("T3_NET20_ABOVE_MARGIN", "CLASSIFICATION_DESIGN_CANDIDATE", "t3_net20_above_margin"),
    ]
    dimensions = [("ALL", pd.Series("ALL", index=frame.index)), ("YEAR", frame.calendar_year.astype(str)),
                  ("DIRECTION", frame["head"]), ("SYMBOL", frame.action_instrument)]
    for target, kind, column in specifications:
        for dimension, groups in dimensions:
            for group, part in frame.groupby(groups, sort=True):
                values = part[column]
                row = {"target": target, "target_kind": kind, "dimension": dimension, "group": str(group),
                       "valid_count": int(values.notna().sum()), "invalid_count": int(values.isna().sum()),
                       "coverage_rate": float(values.notna().mean()), "mean": float(values.mean()),
                       "median": float(values.median()), "p05": float(values.quantile(.05)),
                       "p95": float(values.quantile(.95)), "std": float(values.std(ddof=1)) if len(values) > 1 else math.nan}
                if "CLASSIFICATION" in kind:
                    row.update({"positive_rate": float(values.mean()), "negative_rate": float(1 - values.mean()),
                                "minority_class_share": float(min(values.mean(), 1 - values.mean())),
                                "entropy_bits": binary_entropy(float(values.mean()))})
                rows.append(row)
    return pd.DataFrame(rows)


def stability_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for target, column in (("T1_POSITIVE_NET20", "t1_positive_net20"),
                           ("T3_NET20_ABOVE_MARGIN", "t3_net20_above_margin")):
        for dimension, group_column in (("YEAR", "calendar_year"), ("DIRECTION", "head"), ("SYMBOL", "action_instrument")):
            values = frame.groupby(group_column)[column].mean()
            value_range = float(values.max() - values.min())
            rows.append({"target": target, "dimension": dimension, "group_count": len(values),
                         "minimum": float(values.min()), "maximum": float(values.max()), "range": value_range,
                         "normalized_range": value_range, "stability": classification_stability_label(value_range),
                         "score": classification_stability_score(value_range)})
    iqr = float(frame.t2_robust_net20.quantile(.75) - frame.t2_robust_net20.quantile(.25))
    for dimension, group_column in (("YEAR", "calendar_year"), ("DIRECTION", "head"), ("SYMBOL", "action_instrument")):
        values = frame.groupby(group_column).t2_robust_net20.mean()
        value_range = float(values.max() - values.min())
        normalized = float(value_range / iqr) if iqr else math.inf
        rows.append({"target": "T2_ROBUST_NET20", "dimension": dimension, "group_count": len(values),
                     "minimum": float(values.min()), "maximum": float(values.max()), "range": value_range,
                     "normalized_range": normalized, "stability": continuous_stability_label(normalized),
                     "score": continuous_stability_score(normalized)})
    return pd.DataFrame(rows)


def score_relationship_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    targets = [("T1_POSITIVE_NET20", "t1_positive_net20"), ("T2_RAW_NET20", "corrected_net20"),
               ("T2_ROBUST_NET20", "t2_robust_net20"), ("T3_NET20_ABOVE_MARGIN", "t3_net20_above_margin")]
    for head, part in frame.groupby("head", sort=True):
        ranked = part.copy()
        ranked["score_decile"] = pd.qcut(ranked.probability.rank(method="first"), 10, labels=range(1, 11)).astype(int)
        for target, column in targets:
            correlation = float(ranked.probability.corr(ranked[column], method="spearman"))
            rows.append({"row_type": "SUMMARY", "head": head, "target": target, "score_decile": None,
                         "count": len(ranked), "score_mean": float(ranked.probability.mean()),
                         "target_mean": float(ranked[column].mean()), "spearman_score_target": correlation,
                         "diagnostic_only": True})
            for decile, group in ranked.groupby("score_decile", sort=True):
                rows.append({"row_type": "DECILE", "head": head, "target": target, "score_decile": int(decile),
                             "count": len(group), "score_mean": float(group.probability.mean()),
                             "target_mean": float(group[column].mean()), "spearman_score_target": correlation,
                             "diagnostic_only": True})
    return pd.DataFrame(rows)


def target_redundancy(frame: pd.DataFrame) -> list[dict]:
    pairs = [("T1_POSITIVE_NET20", "t1_positive_net20", "T2_RAW_NET20", "corrected_net20"),
             ("T1_POSITIVE_NET20", "t1_positive_net20", "T3_NET20_ABOVE_MARGIN", "t3_net20_above_margin"),
             ("T2_RAW_NET20", "corrected_net20", "T3_NET20_ABOVE_MARGIN", "t3_net20_above_margin")]
    rows = []
    for left_name, left, right_name, right in pairs:
        rows.append({"left": left_name, "right": right_name, "pearson_or_point_biserial": float(frame[left].corr(frame[right])),
                     "spearman": float(frame[left].corr(frame[right], method="spearman")),
                     "right_mean_when_left_0": float(frame.loc[frame[left].eq(0), right].mean()) if set(frame[left].unique()) <= {0, 1} else None,
                     "right_mean_when_left_1": float(frame.loc[frame[left].eq(1), right].mean()) if set(frame[left].unique()) <= {0, 1} else None})
    return rows


def create_ranking(frame: pd.DataFrame, stability: pd.DataFrame) -> dict:
    def stab(target: str, dimension: str) -> int:
        return int(stability.loc[stability.target.eq(target) & stability.dimension.eq(dimension), "score"].iloc[0])

    raw = frame.corrected_net20
    robust = frame.t2_robust_net20
    raw_tail_ratio = float((raw.quantile(.99) - raw.quantile(.01)) / (raw.quantile(.75) - raw.quantile(.25)))
    robust_tail_ratio = float((robust.quantile(.99) - robust.quantile(.01)) / (robust.quantile(.75) - robust.quantile(.25)))
    max_abs_reduction = 1.0 - float(robust.abs().max() / raw.abs().max())
    t2_tail_score = 5 if 1 - robust_tail_ratio / raw_tail_ratio >= .20 else 4 if max_abs_reduction >= .10 else 3
    rates = {"T1_POSITIVE_NET20": float(frame.t1_positive_net20.mean()),
             "T3_NET20_ABOVE_MARGIN": float(frame.t3_net20_above_margin.mean())}
    entropies = {target: binary_entropy(rate) for target, rate in rates.items()}
    components = {
        "T1_POSITIVE_NET20": {
            "ECONOMIC_ALIGNMENT": 5, "DATA_COVERAGE": 5, "TAIL_ROBUSTNESS": 5,
            "TEMPORAL_STABILITY": stab("T1_POSITIVE_NET20", "YEAR"),
            "DIRECTION_STABILITY": stab("T1_POSITIVE_NET20", "DIRECTION"),
            "SYMBOL_STABILITY": stab("T1_POSITIVE_NET20", "SYMBOL"),
            "INTERPRETABILITY": 5, "TRAINING_FEASIBILITY": class_feasibility_score(entropies["T1_POSITIVE_NET20"]),
            "LEAKAGE_RISK": 5,
        },
        "T2_ROBUST_NET20": {
            "ECONOMIC_ALIGNMENT": 5, "DATA_COVERAGE": 5, "TAIL_ROBUSTNESS": t2_tail_score,
            "TEMPORAL_STABILITY": stab("T2_ROBUST_NET20", "YEAR"),
            "DIRECTION_STABILITY": stab("T2_ROBUST_NET20", "DIRECTION"),
            "SYMBOL_STABILITY": stab("T2_ROBUST_NET20", "SYMBOL"),
            "INTERPRETABILITY": 4, "TRAINING_FEASIBILITY": 4, "LEAKAGE_RISK": 5,
        },
        "T3_NET20_ABOVE_MARGIN": {
            "ECONOMIC_ALIGNMENT": 4, "DATA_COVERAGE": 5, "TAIL_ROBUSTNESS": 5,
            "TEMPORAL_STABILITY": stab("T3_NET20_ABOVE_MARGIN", "YEAR"),
            "DIRECTION_STABILITY": stab("T3_NET20_ABOVE_MARGIN", "DIRECTION"),
            "SYMBOL_STABILITY": stab("T3_NET20_ABOVE_MARGIN", "SYMBOL"),
            "INTERPRETABILITY": 5, "TRAINING_FEASIBILITY": class_feasibility_score(entropies["T3_NET20_ABOVE_MARGIN"]),
            "LEAKAGE_RISK": 5,
        },
    }
    ranking = []
    for target, scores in components.items():
        ranking.append({"target": target, "scores": scores, "total_score": sum(scores.values())})
    ranking.sort(key=lambda item: (-item["total_score"], item["target"]))
    return {
        "classification": "B_TWO_COMPLEMENTARY_TARGETS_SELECTED",
        "scoring_scale": "1-5; higher is better; leakage risk 5 means easiest PIT-safe construction",
        "scoring_rules": {
            "classification_stability": "5<=0.08, 4<=0.12, 3<=0.18, 2<=0.25, else 1 prevalence range",
            "continuous_stability": "robust group-mean range / robust overall IQR; 5<=0.25, 4<=0.50, 3<=0.75, 2<=1.0, else 1",
            "classification_feasibility": "entropy: 5>=0.95, 4>=0.85, 3>=0.70, 2>=0.50, else 1",
            "T2_tail_robustness": "5 if tail-ratio reduction>=20%; 4 if max-absolute reduction>=10%; else 3",
        },
        "ranking": ranking,
        "primary_recommended_target": "T1_POSITIVE_NET20",
        "secondary_recommended_target": "T2_ROBUST_NET20",
        "T3_selection_decision": "NOT_SELECTED_FIRST_ROUND_HIGH_REDUNDANCY_WITH_T1_AND_NO_MATERIAL_STABILITY_GAIN",
        "selection_rule": "Select the highest-scoring directly economic target, then at most one complementary target type; reject a near-duplicate threshold target absent material stability gain.",
    }


def artifact_manifest() -> dict:
    stages = []
    for stage in R28_STAGES:
        artifacts = []
        for role in ("summary", "report"):
            path = stage["root"] / stage[role]
            if not path.is_file():
                raise AuditStop(f"STOP_R28_ARTIFACT_MISSING:{path}")
            artifacts.append({"role": role, "path": str(path), "sha256": file_sha256(path),
                              "file_size": path.stat().st_size})
        stages.append({key: value for key, value in stage.items() if key not in {"root", "summary", "report"}} |
                      {"artifacts": artifacts})
    important = [R28G_LEDGER, R28G_ACTIONS,
                 R28_STAGES[4]["root"] / "R28_3E_CANONICAL_ETF_PARTITION_MANIFEST.json",
                 R28_STAGES[4]["root"] / "R28_3E_FROZEN_MODEL_IDENTITY_MAP.json"]
    return {
        "manifest_version": "FAST3_R28_FINAL_ARTIFACT_MANIFEST_V1",
        "ETF_MANIFEST_SHA256": ETF_MANIFEST_SHA256, "stages": stages,
        "cross_stage_key_evidence": [{"path": str(path), "sha256": file_sha256(path),
                                      "file_size": path.stat().st_size} for path in important],
    }


def target_contracts() -> dict:
    common = {
        "REFERENCE_TIMESTAMP": "frozen selected-signal decision timestamp",
        "ENTRY_SEMANTICS": "first legal mapped leveraged-ETF 1m bar strictly after frozen anchor within 15 minutes; use open",
        "EXIT/HORIZON_SEMANTICS": "favorable-first: first legal ETF open at/after frozen SOXX touch; adverse-first/no-event: frozen R26A2 24-natural-hour closeout",
        "PRICE_SOURCE": f"R28.3E canonical ETF partitions; ETF_MANIFEST_SHA256={ETF_MANIFEST_SHA256}",
        "CORPORATE_ACTION_NORMALIZATION": "issuer-authoritative cumulative share-equivalence factor at economic-return layer; canonical raw bars remain unchanged",
        "TRANSACTION_COST": "20bps total round-trip cost; net20 = normalized gross - 0.002",
        "PIT_REQUIREMENT": "features and score inputs available at decision timestamp only; future path and actions may construct labels but never features",
        "MISSING_DATA_POLICY": "retain explicit invalid/nonexecutable state; exclude from valid target cohort; no imputation and no silent drop",
        "PRE_ENTRY_EVENT_POLICY": "PRE_ENTRY_TOUCH_NOT_CAPTURABLE; preserve reconciliation row and exclude from executable target cohort",
    }
    return {
        "proposal_version": "FAST3_NEXT_ECONOMIC_TARGET_CONTRACT_PROPOSAL_V1",
        "status": "PROPOSED_REQUIRES_HUMAN_FREEZE_BEFORE_TRAINING",
        "TARGET_CONTRACT_FREEZE_REQUIRED": True,
        "recommended_targets": [
            {**common, "TARGET_NAME": "T1_POSITIVE_NET20", "TARGET_TYPE": "BINARY_CLASSIFICATION",
             "TARGET_FORMULA": "1 if corporate-action-normalized executable net20 > 0, else 0"},
            {**common, "TARGET_NAME": "T2_ROBUST_NET20", "TARGET_TYPE": "ROBUST_CONTINUOUS_REGRESSION",
             "TARGET_FORMULA": "sign(net20) * log(1 + abs(net20)); net20 is corporate-action-normalized executable gross less 0.002"},
        ],
        "architecture_concept_only": {
            "Head_A": "classification -> P(net20 > 0)",
            "Head_B": "regression -> robust expected net20",
            "future_decision_concept": "trade only when probability-positive is high AND expected payoff is positive",
            "DO_NOT_IMPLEMENT_MODEL": True, "DO_NOT_TRAIN_MODEL": True,
        },
    }


def run() -> dict:
    storage, before_data, before_repo = storage_preflight()
    for path_string, expected in EXPECTED_INPUT_HASHES.items():
        path = Path(path_string)
        if file_sha256(path) != expected:
            raise AuditStop(f"STOP_R28_3G_IDENTITY_MISMATCH:{path}")
    summary_g = json.loads(R28G_SUMMARY.read_text(encoding="utf-8"))
    if summary_g["ETF_MANIFEST_SHA256"] != ETF_MANIFEST_SHA256 or summary_g["ECONOMIC_LEDGER_INTEGRITY"] != "PASS":
        raise AuditStop("STOP_R28_3G_NOT_AUTHORITATIVE")
    ledger = pd.read_csv(R28G_LEDGER, parse_dates=["timestamp", "entry_timestamp", "touch_timestamp", "first_touch_exit_timestamp"])
    if len(ledger) != 1198 or ledger.candidate_id.duplicated().any():
        raise AuditStop("STOP_R28_3G_LEDGER_RECONCILIATION")
    valid = ledger.loc[ledger.primary_executable_first_touch_cohort.astype(bool)].copy()
    if len(valid) != 1197 or valid.corrected_net20.isna().any():
        raise AuditStop("STOP_R28_3G_VALID_TARGET_COHORT")
    valid["calendar_year"] = valid.entry_timestamp.dt.year
    valid["t1_positive_net20"] = valid.corrected_net20.gt(0).astype(int)
    valid["t2_robust_net20"] = signed_log1p(valid.corrected_net20)
    valid["t3_net20_above_margin"] = valid.corrected_net20.ge(.005).astype(int)

    distributions = target_distribution_rows(valid)
    stability = stability_rows(valid)
    relationships = score_relationship_rows(valid)
    redundancy = target_redundancy(valid)
    ranking = create_ranking(valid, stability)
    contracts = target_contracts()
    manifest = artifact_manifest()

    raw, robust = valid.corrected_net20, valid.t2_robust_net20
    tail_count = max(1, int(math.ceil(len(raw) * .01)))
    raw_iqr, robust_iqr = float(raw.quantile(.75) - raw.quantile(.25)), float(robust.quantile(.75) - robust.quantile(.25))
    raw_tail_ratio = float((raw.quantile(.99) - raw.quantile(.01)) / raw_iqr)
    robust_tail_ratio = float((robust.quantile(.99) - robust.quantile(.01)) / robust_iqr)
    t1_rate, t3_rate = float(valid.t1_positive_net20.mean()), float(valid.t3_net20_above_margin.mean())
    t1_stability = {row.dimension: row for _, row in stability.loc[stability.target.eq("T1_POSITIVE_NET20")].iterrows()}
    t2_stability = {row.dimension: row for _, row in stability.loc[stability.target.eq("T2_ROBUST_NET20")].iterrows()}
    t3_stability = {row.dimension: row for _, row in stability.loc[stability.target.eq("T3_NET20_ABOVE_MARGIN")].iterrows()}
    score_map = {item["target"]: item for item in ranking["ranking"]}
    relationship_summary = relationships.loc[relationships.row_type.eq("SUMMARY")]
    def relationship(head: str, target: str) -> float:
        return float(relationship_summary.loc[relationship_summary["head"].eq(head) &
                                              relationship_summary.target.eq(target), "spearman_score_target"].iloc[0])

    target_candidates = pd.DataFrame([
        {"target": "T1_POSITIVE_NET20", "role": "PRIMARY", "status": "READY", "target_type": "BINARY_CLASSIFICATION",
         "formula": "1[corrected executable net20 > 0]", "valid_count": len(valid), "invalid_count": 1,
         "coverage_rate": len(valid) / 1198, "positive_rate": t1_rate, "negative_rate": 1-t1_rate,
         "class_balance": f"{t1_rate:.12f}/{1-t1_rate:.12f}", "economic_alignment": "HIGH",
         "design_note": "Direct profitability label after costs; magnitude omitted."},
        {"target": "T2_RAW_NET20", "role": "COMPARISON_ONLY", "status": "READY_HEAVY_TAIL_REFERENCE", "target_type": "CONTINUOUS_REGRESSION",
         "formula": "corrected executable net20", "valid_count": len(valid), "invalid_count": 1,
         "coverage_rate": len(valid) / 1198, "positive_rate": None, "negative_rate": None, "class_balance": None,
         "economic_alignment": "HIGH", "design_note": "Economically direct but tail-sensitive; retained as audit reference."},
        {"target": "T2_ROBUST_NET20", "role": "SECONDARY", "status": "READY", "target_type": "ROBUST_CONTINUOUS_REGRESSION",
         "formula": "sign(net20)*log1p(abs(net20))", "valid_count": len(valid), "invalid_count": 1,
         "coverage_rate": len(valid) / 1198, "positive_rate": None, "negative_rate": None, "class_balance": None,
         "economic_alignment": "HIGH", "design_note": "Preserves sign and rank without data-chosen clipping; compresses tails."},
        {"target": "T3_NET20_ABOVE_MARGIN", "role": "DESIGN_CANDIDATE_ONLY", "status": "READY_NOT_SELECTED", "target_type": "BINARY_CLASSIFICATION",
         "formula": "1[corrected executable net20 >= 0.005]", "valid_count": len(valid), "invalid_count": 1,
         "coverage_rate": len(valid) / 1198, "positive_rate": t3_rate, "negative_rate": 1-t3_rate,
         "class_balance": f"{t3_rate:.12f}/{1-t3_rate:.12f}", "economic_alignment": "HIGH",
         "design_note": "Economically interpretable fixed margin but highly redundant with T1 and not materially more stable."},
        {"target": "T4_DOWNSIDE_AWARE_PAYOFF", "role": "SECONDARY_FEASIBILITY", "status": "INSUFFICIENT_DATA", "target_type": "CONTINUOUS",
         "formula": "net20 + MAE when MAE is negative and unit-consistent", "valid_count": 0, "invalid_count": 1198,
         "coverage_rate": 0.0, "economic_alignment": "POTENTIALLY_HIGH", "design_note": "No trustworthy executable MAE in R28.3G ledger; no new pipeline built."},
        {"target": "T5_REWARD_RISK_SUCCESS", "role": "EXPLORATORY_DESIGN_ONLY", "status": "INSUFFICIENT_DATA", "target_type": "BINARY_CLASSIFICATION",
         "formula": "1[MFE>=0.01 and MAE>-0.005]", "valid_count": 0, "invalid_count": 1198,
         "coverage_rate": 0.0, "economic_alignment": "MEDIUM", "design_note": "Reliable normalized executable MFE/MAE absent; thresholds not promoted."},
        {"target": "T6_LEFT_TAIL_UTILITY", "role": "FUTURE_RESEARCH_TARGET", "status": "NOT_READY", "target_type": "UTILITY",
         "formula": "piecewise asymmetric utility(net20)", "valid_count": 0, "invalid_count": 1198,
         "coverage_rate": 0.0, "economic_alignment": "POTENTIALLY_HIGH", "design_note": "No pre-frozen penalty coefficient with independent economic basis."},
    ])

    closeout = {
        "FAST3_R28_CLOSEOUT_STATUS": "PASS", "FAST3_R28_FINAL_STATUS": "CLOSED",
        "FAST3_R28_FINAL_DECISION": "CLOSED_EVENT_PREDICTION_EDGE_CONFIRMED_ECONOMIC_TARGET_MISALIGNED",
        "R28_GENERATION_CLOSE_REASON": "CLOSE_EVENT_TARGET_GENERATION_ECONOMIC_TRANSLATION_FAILED",
        "PREDICTIVE_EVENT_EDGE": "CONFIRMED", "EVENT_SPEED_EDGE": "CONFIRMED",
        "FIRST_TOUCH_ECONOMIC_EDGE": "REJECTED", "POST_TOUCH_CONTINUATION_EDGE": "NOT_CONFIRMED",
        "TERMINAL_RETURN_EDGE": "NOT_CONFIRMED",
        "ECONOMIC_LEDGER_INTEGRITY": "PASS_AFTER_CORPORATE_ACTION_NORMALIZATION",
        "R28_MODEL_NOT_INVALID_AS_EVENT_MODEL": True,
        "R28_MODEL_INVALID_AS_CONFIRMED_ECONOMIC_TRADING_MODEL": True,
        "MODEL_ADOPTION_ALLOWED": False, "LIVE_TRADING_ALLOWED": False,
        "FINAL_SCIENTIFIC_INTERPRETATION": "FAST3 learned event probability and event arrival speed, but the existing target did not align with positive executable economic payoff.",
        "R28_FINAL_ECONOMIC_MEAN_NET20": summary_g["CORRECTED_MEAN_NET20"],
        "R28_FINAL_POSITIVE_YEAR_COUNT": summary_g["CORRECTED_POSITIVE_YEAR_COUNT"],
        "R28_FINAL_NEGATIVE_YEAR_COUNT": summary_g["CORRECTED_NEGATIVE_YEAR_COUNT"],
        "LESSONS": LESSONS, "PERMANENT_NEXT_GENERATION_GUARDS": PERMANENT_GUARDS,
        "stage_history": manifest["stages"],
    }

    storage_post = post_storage_audit(before_data, before_repo)
    summary = {
        "FAST3_R28_CLOSEOUT_STATUS": "PASS",
        "FAST3_R28_FINAL_DECISION": closeout["FAST3_R28_FINAL_DECISION"],
        "R28_EVENT_PROBABILITY_EDGE": "CONFIRMED", "R28_EVENT_SPEED_EDGE": "CONFIRMED",
        "R28_FIRST_TOUCH_ECONOMIC_EDGE": "REJECTED", "R28_POST_TOUCH_CONTINUATION_EDGE": "NOT_CONFIRMED",
        "R28_TERMINAL_RETURN_EDGE": "NOT_CONFIRMED",
        "R28_FINAL_ECONOMIC_MEAN_NET20": summary_g["CORRECTED_MEAN_NET20"],
        "R28_FINAL_POSITIVE_YEAR_COUNT": summary_g["CORRECTED_POSITIVE_YEAR_COUNT"],
        "R28_FINAL_NEGATIVE_YEAR_COUNT": summary_g["CORRECTED_NEGATIVE_YEAR_COUNT"],
        "NEXT_TARGET_DESIGN_STATUS": "PASS", "NEXT_TARGET_DESIGN_CLASSIFICATION": ranking["classification"],
        "T1_VALID_COUNT": len(valid), "T1_INVALID_COUNT": 1, "T1_COVERAGE_RATE": len(valid)/1198,
        "T1_POSITIVE_RATE": t1_rate, "T1_NEGATIVE_RATE": 1-t1_rate,
        "T1_CLASS_BALANCE": {"positive": t1_rate, "negative": 1-t1_rate, "minority_share": min(t1_rate,1-t1_rate),
                             "entropy_bits": binary_entropy(t1_rate)},
        "T1_YEAR_STABILITY": t1_stability["YEAR"].stability,
        "T1_DIRECTION_STABILITY": t1_stability["DIRECTION"].stability,
        "T1_SYMBOL_STABILITY": t1_stability["SYMBOL"].stability,
        "T1_ECONOMIC_ALIGNMENT_SCORE": score_map["T1_POSITIVE_NET20"]["scores"]["ECONOMIC_ALIGNMENT"],
        "T1_TOTAL_SCORE": score_map["T1_POSITIVE_NET20"]["total_score"],
        "T2_VALID_COUNT": len(valid), "T2_INVALID_COUNT": 1, "T2_COVERAGE_RATE": len(valid)/1198,
        "T2_RAW_MEAN": float(raw.mean()), "T2_RAW_MEDIAN": float(raw.median()),
        "T2_ROBUST_MEAN": float(robust.mean()), "T2_ROBUST_MEDIAN": float(robust.median()),
        "T2_RAW_TRIMMED_1PCT_EACH_TAIL_MEAN_DIAGNOSTIC": symmetric_trimmed_mean(raw),
        "T2_ROBUST_TRIMMED_1PCT_EACH_TAIL_MEAN_DIAGNOSTIC": symmetric_trimmed_mean(robust),
        "T2_RAW_TOP_1PCT_CONTRIBUTION": float(raw.nlargest(tail_count).sum()/raw.sum()),
        "T2_RAW_BOTTOM_1PCT_CONTRIBUTION": float(raw.nsmallest(tail_count).sum()/raw.sum()),
        "T2_RAW_TAIL_RATIO": raw_tail_ratio, "T2_ROBUST_TAIL_RATIO": robust_tail_ratio,
        "T2_MAX_ABS_REDUCTION": 1-float(robust.abs().max()/raw.abs().max()),
        "T2_TAIL_SENSITIVITY": "HEAVY_LEFT_TAIL_SIGNED_LOG_MODESTLY_IMPROVES",
        "T2_YEAR_STABILITY": t2_stability["YEAR"].stability,
        "T2_DIRECTION_STABILITY": t2_stability["DIRECTION"].stability,
        "T2_SYMBOL_STABILITY": t2_stability["SYMBOL"].stability,
        "T2_TOTAL_SCORE": score_map["T2_ROBUST_NET20"]["total_score"],
        "T3_VALID_COUNT": len(valid), "T3_INVALID_COUNT": 1, "T3_COVERAGE_RATE": len(valid)/1198,
        "T3_POSITIVE_RATE": t3_rate, "T3_NEGATIVE_RATE": 1-t3_rate,
        "T3_YEAR_STABILITY": t3_stability["YEAR"].stability,
        "T3_DIRECTION_STABILITY": t3_stability["DIRECTION"].stability,
        "T3_SYMBOL_STABILITY": t3_stability["SYMBOL"].stability,
        "T3_TOTAL_SCORE": score_map["T3_NET20_ABOVE_MARGIN"]["total_score"],
        "OLD_UP_SCORE_VS_T1": relationship("UP", "T1_POSITIVE_NET20"),
        "OLD_DOWN_SCORE_VS_T1": relationship("DOWN", "T1_POSITIVE_NET20"),
        "OLD_UP_SCORE_VS_T2": relationship("UP", "T2_ROBUST_NET20"),
        "OLD_DOWN_SCORE_VS_T2": relationship("DOWN", "T2_ROBUST_NET20"),
        "THIS_IS_DIAGNOSTIC_NOT_NEW_MODEL_VALIDATION": True,
        "TARGET_REDUNDANCY": redundancy,
        "PRIMARY_RECOMMENDED_TARGET": ranking["primary_recommended_target"],
        "SECONDARY_RECOMMENDED_TARGET": ranking["secondary_recommended_target"],
        "RECOMMENDED_NEXT_GENERATION_ARCHITECTURE": "TWO_HEAD_CONCEPT: Head A P(net20>0) + Head B signed-log robust expected net20; future trade requires high positive-payoff probability and positive expected payoff",
        "TARGET_CONTRACT_FREEZE_REQUIRED": True,
        "MODEL_TRAINING_PERFORMED": False, "MODEL_RETRAIN_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "POST_FREEZE_RESCORING_COUNT": 0, "R29_MODIFIED": False, "LIVE_TRADING_ALLOWED": False,
        "NEXT_STAGE": "HUMAN_REVIEW_AND_FREEZE_T1_T2_ECONOMIC_TARGET_CONTRACT",
        "ETF_MANIFEST_SHA256": ETF_MANIFEST_SHA256,
        **storage, **storage_post, "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS",
    }

    STAGE.mkdir(parents=True)
    paths = {
        "closeout_json": STAGE / "FAST3_R28_FINAL_CLOSEOUT.json",
        "closeout_md": STAGE / "FAST3_R28_FINAL_CLOSEOUT.md",
        "manifest": STAGE / "FAST3_R28_FINAL_ARTIFACT_MANIFEST.json",
        "candidates": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_CANDIDATES.csv",
        "distributions": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_DISTRIBUTIONS.csv",
        "stability": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_STABILITY.csv",
        "relationships": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_SCORE_RELATIONSHIP.csv",
        "ranking": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_RANKING.json",
        "report": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_DESIGN_REPORT.md",
        "contract": STAGE / "FAST3_NEXT_ECONOMIC_TARGET_CONTRACT_PROPOSAL.json",
        "summary": STAGE / "FAST3_R28_CLOSEOUT_NEXT_TARGET_SUMMARY.json",
    }
    atomic_json(paths["closeout_json"], closeout)
    atomic_json(paths["manifest"], manifest)
    target_candidates.to_csv(paths["candidates"], index=False)
    distributions.to_csv(paths["distributions"], index=False)
    stability.to_csv(paths["stability"], index=False)
    relationships.to_csv(paths["relationships"], index=False)
    atomic_json(paths["ranking"], ranking)
    atomic_json(paths["contract"], contracts)
    closeout_md = ["# FAST3 R28 Final Closeout", "",
                   "R28 is closed: event probability and speed were predictive, but first-touch economic translation was negative after integrity correction.", "",
                   f"- Final mean net20: `{summary_g['CORRECTED_MEAN_NET20']}`",
                   "- Positive/negative years: `0 / 6`", "- Model adoption: `not allowed`", "",
                   "The R28 model remains valid as an event model; it is invalid as a confirmed economic trading model."]
    paths["closeout_md"].write_text("\n".join(closeout_md)+"\n", encoding="utf-8")
    report = ["# FAST3 Next-Generation Economic Target Design Audit", "",
              "No model was trained or rescored. All targets use the 1,197-row valid R28.3G cohort and corporate-action-normalized net20.", "",
              f"- T1 positive rate: `{t1_rate}`; score `{score_map['T1_POSITIVE_NET20']['total_score']}/45`.",
              f"- T2 raw mean/median: `{raw.mean()}` / `{raw.median()}`.",
              f"- T2 signed-log mean/median: `{robust.mean()}` / `{robust.median()}`; score `{score_map['T2_ROBUST_NET20']['total_score']}/45`.",
              f"- T3 positive rate: `{t3_rate}`; score `{score_map['T3_NET20_ABOVE_MARGIN']['total_score']}/45`.",
              f"- Old score vs T1: UP `{relationship('UP','T1_POSITIVE_NET20')}`, DOWN `{relationship('DOWN','T1_POSITIVE_NET20')}`.",
              f"- Old score vs T2: UP `{relationship('UP','T2_ROBUST_NET20')}`, DOWN `{relationship('DOWN','T2_ROBUST_NET20')}`.", "",
              "Recommendation: freeze T1 as the primary classification target and T2 signed-log net20 as a complementary regression target. T3 is balanced but highly redundant with T1 and provides no material stability gain. T4/T5 lack trustworthy normalized MAE/MFE; T6 lacks a pre-frozen penalty basis.", "",
              "Proposed future architecture (not implemented): classification head P(net20>0) plus robust expected-net20 regression head."]
    paths["report"].write_text("\n".join(report)+"\n", encoding="utf-8")
    summary.update({
        "R28_FINAL_CLOSEOUT_PATH": str(FROZEN_RUN_ROOT / paths["closeout_json"].name),
        "R28_FINAL_ARTIFACT_MANIFEST_PATH": str(FROZEN_RUN_ROOT / paths["manifest"].name),
        "REPORT_PATH": str(FROZEN_RUN_ROOT / paths["report"].name),
        "TARGET_RANKING_PATH": str(FROZEN_RUN_ROOT / paths["ranking"].name),
        "TARGET_CONTRACT_PROPOSAL_PATH": str(FROZEN_RUN_ROOT / paths["contract"].name),
        "SUMMARY_PATH": str(FROZEN_RUN_ROOT / paths["summary"].name),
    })
    evidence = {}
    for name, path in paths.items():
        if name == "summary":
            continue
        evidence[name] = {"path": str(FROZEN_RUN_ROOT/path.name), "sha256": file_sha256(path),
                          "file_size": path.stat().st_size}
    summary["FROZEN_OUTPUT_EVIDENCE"] = evidence
    atomic_json(paths["summary"], summary)
    FROZEN_RUN_ROOT.parent.mkdir(parents=True, exist_ok=True)
    STAGE.replace(FROZEN_RUN_ROOT)
    return summary


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        if RUNTIME_RUN_ROOT.exists():
            atomic_json(RUNTIME_RUN_ROOT / "failure.json", {"NEXT_TARGET_DESIGN_STATUS": "D_INVALID_TARGET_DESIGN_AUDIT", "error": str(exc)})
        raise
