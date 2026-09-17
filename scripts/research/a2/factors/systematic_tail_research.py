"""Bounded exploratory adapter over frozen A2 inputs, ledger and simulator.

This module owns only the current joint-tail hypothesis experiment. It imports
the existing model/ledger/statistical helpers and R4 accounting unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(name, "1")

import numpy as np
import pandas as pd

REPO = Path("D:/us-tech-quant")
WORK = Path("C:/Users/Lenovo/Documents/CODING开发/strategy-lab-20260913")
SOURCE = Path(__file__).resolve().parent
RESULT = Path("D:/us-tech-quant-results/A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913")
CACHE = Path("D:/us-tech-quant-cache/a2_systematic_tail_dependence_20260913")
YEARS = (2023, 2024, 2025)
SEED = 20260913
CANDIDATES = {
    "CONTROL": (),
    "SEMIBETA": ("semibeta_n", "semibeta_m_minus"),
    "COSKEWNESS": ("market_coskewness",),
    "COMBINED": ("semibeta_n", "semibeta_m_minus", "market_coskewness"),
}


def import_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def encode(value):
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=encode, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def announce(stage: str, **fields) -> None:
    print(json.dumps({"stage": stage, "utc": datetime.now(timezone.utc).isoformat(), **fields}, default=encode), flush=True)


def chronological_masks(panel: pd.DataFrame, year: int, calendar: pd.DatetimeIndex, embargo: int = 5):
    validation = panel.signal_date.dt.year.eq(year)
    if not validation.any():
        raise RuntimeError(f"EMPTY_VALIDATION:{year}")
    start = panel.loc[validation, "signal_date"].min()
    position = calendar.get_indexer([start])[0]
    if position < embargo or embargo < 0:
        raise RuntimeError("EMBARGO_CALENDAR_UNAVAILABLE")
    maturity_limit = calendar[position - embargo]
    train = panel.signal_date.lt(start) & panel.target_end_date.lt(maturity_limit) & panel.target.notna()
    if not train.any() or panel.loc[train, "target_end_date"].max() >= maturity_limit:
        raise RuntimeError("TRAIN_LABEL_MATURITY_FAILURE")
    if panel.loc[train, "signal_date"].max() >= start:
        raise RuntimeError("TRAIN_SIGNAL_ORDER_FAILURE")
    return train, validation, {
        "train_start": panel.loc[train, "signal_date"].min(),
        "train_end": panel.loc[train, "signal_date"].max(),
        "max_train_label_maturity": panel.loc[train, "target_end_date"].max(),
        "maturity_limit_exclusive": maturity_limit,
        "validation_start": start,
        "validation_end": panel.loc[validation, "signal_date"].max(),
        "train_rows": int(train.sum()), "validation_rows": int(validation.sum()),
    }


def holm(pvalues: list[float]) -> np.ndarray:
    """Holm familywise adjustment; unlike BH, valid at arbitrary dependence."""
    values = np.asarray(pvalues, dtype=float)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("INVALID_PVALUES")
    order = np.argsort(values, kind="stable")
    adjusted = np.maximum.accumulate(values[order] * np.arange(len(values), 0, -1)).clip(0, 1)
    result = np.empty_like(values)
    result[order] = adjusted
    return result


def selection_from_scores(panel: pd.DataFrame, values: np.ndarray, engine, candidate: str):
    selected = panel[["signal_date", "ticker", "raw_rank"]].copy()
    if len(values) != len(selected) or not np.isfinite(values).all():
        raise ValueError("INCOMPLETE_PREDICTIONS")
    selected["prediction"] = values
    selected["candidate_rank"] = engine.stable_rank(selected)
    selected = selected.loc[selected.candidate_rank.le(20)].copy()
    if not selected.groupby("signal_date").size().eq(20).all():
        raise ValueError("TOP20_CARDINALITY_FAILURE")
    selected["candidate_id"] = candidate
    return selected


def create_freeze():
    files = [Path(__file__), SOURCE / "systematic_tail_features.py", SOURCE / "tail_research_inputs.py",
             WORK / "research_spec.json", WORK / "preregistration.json", WORK / "start_gate.json",
             REPO / "scripts/v22/a2_open_research_engine.py"]
    identity = {str(path): sha(path) for path in files}
    freeze_path = RESULT / "experiment_freeze.json"
    if freeze_path.exists():
        prior = json.loads(freeze_path.read_text(encoding="utf-8"))
        if prior["files"] != identity:
            raise RuntimeError("FROZEN_EXPERIMENT_IDENTITY_CHANGED")
        return prior
    gate = json.loads((WORK / "start_gate.json").read_text(encoding="utf-8"))
    if gate["decision"]["decision"] != "ALLOW_NEW_RESEARCH":
        raise RuntimeError("RESEARCH_START_NOT_ALLOWED")
    review_path = WORK / "audits/prereg_review.md"
    if not review_path.exists():
        raise RuntimeError("INDEPENDENT_PREREG_REVIEW_MISSING")
    source_review = WORK / "audits/source_review.md"
    if not source_review.exists():
        raise RuntimeError("INDEPENDENT_SOURCE_REVIEW_MISSING")
    freeze = {"created_utc": datetime.now(timezone.utc).isoformat(), "files": identity,
              "review_sha256": sha(review_path), "candidate_ids": list(CANDIDATES),
              "source_review_sha256": sha(source_review),
              "candidate_performance_evaluation_count_before_freeze": 0,
              "data_preflight_loaded_label_rows": True,
              "evidence_role": "REUSED_HISTORICAL_EXPLORATION",
              "input_source_reuse": "SAME_PROVIDER_RAW_DATA_NEW_JOINT_MOMENTS_NOT_NEW_PROVIDER"}
    write_json(freeze_path, freeze)
    write_json(RESULT / "research_spec.json", json.loads((WORK / "research_spec.json").read_text(encoding="utf-8")))
    write_json(RESULT / "preregistration.json", json.loads((WORK / "preregistration.json").read_text(encoding="utf-8")))
    return freeze


def run() -> None:
    RESULT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    freeze = create_freeze()
    announce("FROZEN", timestamp=freeze["created_utc"])
    engine = import_path("tail_existing_engine", REPO / "scripts/v22/a2_open_research_engine.py")
    inputs = import_path("tail_inputs", SOURCE / "tail_research_inputs.py")
    features = import_path("tail_features", SOURCE / "systematic_tail_features.py")
    panel, prices, r4, lineage = inputs.load_inputs()
    r5, _, _ = inputs.load_sources()
    write_json(RESULT / "data_lineage.json", lineage)
    announce("INPUTS_VERIFIED", rows=len(panel), price_rows=len(prices))
    full_selection = r5.raw_selection(inputs.load_full_checkpoint())
    _, identity = r5.baseline_replay(full_selection, prices, r4)
    write_json(RESULT / "baseline_reconciliation.json", identity)
    announce("BASELINE_RECONCILED", sessions=identity["sessions"])
    factor_frame = features.build_systematic_tail_features(prices[["ticker", "trade_date", "close"]])
    panel = panel.merge(factor_frame.rename(columns={"trade_date": "signal_date"}), on=["signal_date", "ticker"], how="left", validate="one_to_one")
    if not panel.groupby("signal_date").size().eq(40).all():
        raise RuntimeError("COMMON_TOP40_SUPPORT_CHANGED")
    base_features = list(r5.BASE_FEATURES) + ["raw_rank_strength", "beta_centered", "beta_uncentered", "own_skewness"]
    for column in ("signal_date", "target_end_date"):
        if panel[column].ge(pd.Timestamp("2026-01-01")).any():
            raise RuntimeError("POST_CUTOFF_PANEL")
    panel["target"] = panel.groupby("signal_date", sort=False).target.rank(method="average", pct=True)
    evaluation = panel.loc[panel.signal_date.dt.year.isin(YEARS)].copy()
    coverage = {name: float(evaluation[name].notna().mean()) for name in features.FACTOR_COLUMNS}
    write_json(RESULT / "feature_coverage.json", {"fractions": coverage, "min_pairs": int(evaluation.matched_observations.min()),
        "rows": len(evaluation), "dates": int(evaluation.signal_date.nunique()),
        "decision_start": evaluation.signal_date.min(), "decision_end": evaluation.signal_date.max()})
    if any(coverage[name] < 0.90 for name in ("semibeta_n", "semibeta_m_minus", "market_coskewness")):
        raise RuntimeError("INSUFFICIENT_PREREGISTERED_FACTOR_COVERAGE")
    panel.to_parquet(CACHE / "feature_panel.parquet", index=False)
    calendar = pd.DatetimeIndex(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].sort_values().unique())
    ledger = engine.TrialLedger(RESULT / "research_trial_ledger.parquet")
    predictions = evaluation[["signal_date", "ticker", "target"]].copy()
    coefficient_rows, fold_rows = [], []
    input_hash = sha(CACHE / "feature_panel.parquet")
    code_hash = sha(Path(__file__))
    for candidate, additions in CANDIDATES.items():
        columns = base_features + list(additions)
        scores = pd.Series(np.nan, index=panel.index, dtype=float)
        for year in YEARS:
            train_mask, valid_mask, audit = chronological_masks(panel, year, calendar)
            trial_id = f"{candidate}_{year}"
            spec = {"feature_set_id": candidate, "parameters": {"alpha": 10.0}, "seed": SEED}
            common = dict(parent="A2_SYSTEMATIC_TAIL_DEPENDENCE_20260913", family="RIDGE", spec=spec,
                threshold=20, outer_fold=str(year), inner_fold="NO_SEARCH", audit=audit,
                row_count=int(train_mask.sum()), feature_count=len(columns), runtime=0.0,
                predictive={}, economic={}, complexity={}, input_hash=input_hash, code_hash=code_hash)
            if (ledger.frame.trial_id == trial_id + "_COMPLETE").any():
                prior = ledger.frame.loc[ledger.frame.trial_id.eq(trial_id + "_COMPLETE")].iloc[0]
                integrity = json.loads(prior.complexity_metrics)
                prediction_path = CACHE / (trial_id + ".parquet")
                details_path = CACHE / (trial_id + ".json")
                if prior.input_hash != input_hash or prior.code_hash != code_hash:
                    raise RuntimeError("RESUME_INPUT_OR_CODE_CHANGED")
                if sha(prediction_path) != integrity["prediction_sha256"] or sha(details_path) != integrity["details_sha256"]:
                    raise RuntimeError("RESUME_CACHE_HASH_CHANGED")
                saved = pd.read_parquet(prediction_path)
                expected = panel.loc[valid_mask, ["signal_date", "ticker"]].reset_index(drop=True)
                if not saved[["signal_date", "ticker"]].equals(expected):
                    raise RuntimeError("RESUME_PREDICTION_KEYS_CHANGED")
                scores.loc[valid_mask] = saved.prediction.to_numpy()
                details = json.loads(details_path.read_text(encoding="utf-8"))
                coefficient_rows.extend(details["coefficients"])
                fold_rows.append(details["fold_audit"])
                continue
            if (ledger.frame.trial_id == trial_id + "_START").any():
                raise RuntimeError("UNFINISHED_TRIAL_REQUIRES_RECORDED_RETRY")
            ledger.append([engine.trial_row(identifier=trial_id + "_START", status="STARTED", failure="", **common)])
            try:
                train, valid = panel.loc[train_mask].copy(), panel.loc[valid_mask].copy()
                if train[columns].notna().sum().eq(0).any():
                    raise RuntimeError("ALL_MISSING_TRAINING_PREDICTOR")
                model, pred, elapsed = engine.fit_predict("RIDGE", {"alpha": 10.0}, train, valid, columns, SEED, 1, False)
                scores.loc[valid_mask] = pred
                saved = valid[["signal_date", "ticker"]].copy()
                saved["prediction"] = pred
                saved.to_parquet(CACHE / (trial_id + ".parquet"), index=False)
                coefficients = [{"candidate": candidate, "year": year, "feature": name, "coefficient": float(coefficient)}
                    for name, coefficient in zip(columns, model.named_steps["model"].coef_)]
                coefficient_rows.extend(coefficients)
                fold = {"candidate": candidate, "year": year, **audit}
                details_path = CACHE / (trial_id + ".json")
                write_json(details_path, {"coefficients": coefficients, "fold_audit": fold})
                common["runtime"] = elapsed
                common["complexity"] = {"prediction_sha256": sha(CACHE / (trial_id + ".parquet")), "details_sha256": sha(details_path)}
                ledger.append([engine.trial_row(identifier=trial_id + "_COMPLETE", status="COMPLETED", failure="", **common)])
                fold_rows.append(fold)
                announce("FIT_COMPLETE", candidate=candidate, year=year, seconds=round(elapsed, 3))
            except Exception as exc:
                ledger.append([engine.trial_row(identifier=trial_id + "_FAILED", status="FAILED", failure=repr(exc), **common)])
                raise
        predictions[candidate] = scores.loc[evaluation.index].to_numpy()
    if not np.isfinite(predictions[list(CANDIDATES)].to_numpy()).all():
        raise RuntimeError("OOF_PREDICTIONS_INCOMPLETE")
    predictions.to_parquet(RESULT / "oof_predictions.parquet", index=False)
    pd.DataFrame(coefficient_rows).to_csv(RESULT / "coefficients.csv", index=False)
    pd.DataFrame(fold_rows).to_csv(RESULT / "fold_audit.csv", index=False)
    assess(evaluation, predictions, prices, r4, r5, engine)


def assess(evaluation, predictions, prices, r4, r5, engine):
    ics = {candidate: r5.daily_spearman(predictions, candidate, "target") for candidate in CANDIDATES}
    ic_frame = pd.DataFrame(ics)
    if ic_frame.isna().any().any() or len(ic_frame) != evaluation.signal_date.nunique():
        raise RuntimeError("IC_DATE_SUPPORT_MISMATCH")
    ic_frame.to_parquet(RESULT / "daily_rank_ic.parquet")
    selections = {"RAW_A2": r5.raw_selection(evaluation)}
    for candidate in CANDIDATES:
        selections[candidate] = selection_from_scores(evaluation, predictions[candidate].to_numpy(), engine, candidate)
    paths, economics = [], []
    for cost in (10, 20):
        for candidate, selection in selections.items():
            path = r4.simulate_portfolio(r5.simulator_signals(selection), prices, candidate, "a2_rank", 20, cost)
            paths.append(path)
            for year in (0, *YEARS):
                part = path if year == 0 else path.loc[path.execution_date.dt.year.eq(year)]
                stats = r5.metrics(part, r4)
                economics.append({"candidate": candidate, "cost_bps_half_L1": cost, "year": year,
                    "sessions": len(part), **stats})
            announce("ECONOMICS_COMPLETE", candidate=candidate, cost=cost)
    all_paths = pd.concat(paths, ignore_index=True)
    all_paths.to_parquet(RESULT / "daily_portfolio_paths.parquet", index=False)
    pd.DataFrame(economics).to_csv(RESULT / "economic_metrics.csv", index=False)
    statistics = []
    names = [name for name in CANDIDATES if name != "CONTROL"]
    for block in (20, 40, 60):
        raw_p = [r5.block_bootstrap_pvalue((ic_frame[name] - ic_frame.CONTROL).to_numpy(), repetitions=5000, block=block, seed=SEED) for name in names]
        adjusted = holm(raw_p)
        for name, pvalue, adjusted_pvalue in zip(names, raw_p, adjusted):
            delta = ic_frame[name] - ic_frame.CONTROL
            low, high = r5.block_bootstrap_mean_interval(delta.to_numpy(), repetitions=5000, block=block, seed=SEED)
            row = {"candidate": name, "block": block, "ic_delta": float(delta.mean()),
                   "p_one_sided": pvalue, "p_holm": float(adjusted_pvalue), "ci_low": low, "ci_high": high}
            for year in YEARS:
                row[f"ic_delta_{year}"] = float(delta.loc[delta.index.year == year].mean())
            for cost in (10, 20):
                wide = all_paths.loc[all_paths.cost_bps.eq(cost)].pivot(index="execution_date", columns="model", values="net_return")
                if wide.isna().any().any():
                    raise RuntimeError("ECONOMIC_DATE_SUPPORT_MISMATCH")
                for control in ("RAW_A2", "CONTROL"):
                    economic_delta = np.log1p(wide[name]) - np.log1p(wide[control])
                    row[f"net_log_delta_{cost}_vs_{control}"] = float(economic_delta.mean())
                    for year in YEARS:
                        row[f"net_log_delta_{cost}_vs_{control}_{year}"] = float(economic_delta.loc[economic_delta.index.year == year].mean())
            positive_ic_years = all(row[f"ic_delta_{year}"] > 0 for year in YEARS)
            positive_economics = all(row[f"net_log_delta_{cost}_vs_{control}_{year}"] > 0 for cost in (10, 20) for control in ("RAW_A2", "CONTROL") for year in YEARS)
            row["advance"] = bool(positive_ic_years and positive_economics and adjusted_pvalue <= 0.05)
            statistics.append(row)
    stats_frame = pd.DataFrame(statistics)
    stats_frame.to_csv(RESULT / "paired_comparisons.csv", index=False)
    summary = {"status": "EXPLORATORY_EVALUATION_COMPLETE", "primary_advancing_candidates": stats_frame.loc[stats_frame.block.eq(20) & stats_frame.advance, "candidate"].tolist(),
        "model_fits": 12, "candidate_comparisons": 3, "hypothesis_families": 2,
        "post_2025_model_or_selection_rows": 0, "historical_effective_trial_count": "UNKNOWN",
        "evidence_role": "REUSED_EXPLORATORY_WALK_FORWARD_NOT_CONFIRMATION",
        "completed_utc": datetime.now(timezone.utc).isoformat()}
    write_json(RESULT / "summary.json", summary)
    announce("EVALUATION_COMPLETE", **summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    run()
