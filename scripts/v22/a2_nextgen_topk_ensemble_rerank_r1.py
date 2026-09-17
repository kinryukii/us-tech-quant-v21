"""Pre-2026-only Top60-to-Top20 reranking research for authoritative Raw A2.

This runner reuses frozen outer-OOF component predictions and the authoritative
R4 portfolio simulator.  It writes only the four artifacts allowed by the task
contract, directly to the external results root.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_NEXTGEN_TOPK_ENSEMBLE_RERANK_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
CACHE = Path(r"D:\us-tech-quant-cache")
BOUNDARY = pd.Timestamp("2026-01-01")
CANDIDATE_TOP_N = 60
FINAL_TOP_N = 20
COST_BPS = 10
SEED = 20260823
OUTER_FOLDS = ("OUTER_2023", "OUTER_2024", "OUTER_2025")

MODEL_FAMILY_OOF = RESULTS / "A2_MODEL_FAMILY_R1A_DATA_COMPLETE" / "outer_oof_predictions.parquet"
M0_OOF = CACHE / "a2_model_family_r1a_data_complete" / "checkpoints" / "M0_oof.parquet"
M0_PATH = CACHE / "a2_model_family_r1a_data_complete" / "checkpoints" / "M0_path.parquet"
NG8_OOF = CACHE / "a2_full_history_synthesis_nextgen_r1" / "ng8_fixed_outer_oof.parquet"
R6_OOF = RESULTS / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
R6_SPEC = RESULTS / "A2_R6_DOMAIN_TRANSPORTABILITY_AND_FIXED_SPEC_REPLAY_R1" / "r6_specification_and_transportability.json"
FOLD_MANIFEST = RESULTS / "A2_MODEL_FAMILY_R1A_DATA_COMPLETE" / "fold_manifest.csv"
MODEL_CONTRACT = RESULTS / "A2_MODEL_FAMILY_R1A_DATA_COMPLETE" / "incumbent_model_contract.json"
NG8_CONTRACT = RESULTS / "A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1" / "ng8_fixed_confirmation_contract.json"
XGB_FOLD_CONTRACT = RESULTS / "A2_XGB_NEXTGEN_FORMAL_CHALLENGER_AND_PROSPECTIVE_R1" / "authoritative_fold_contract.json"
RESEARCH_DATA = CACHE / "a2_model_family_r1a_data_complete" / "research_dataset.parquet"
R4_SOURCE = REPO / "scripts" / "v22" / "abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
COVERAGE_SOURCE = RESULTS / "A2_PIT_DATA_COVERAGE_R1" / "run_coverage.py"
FROZEN_FORWARD = RESULTS / "A2_THREE_ARM_POSTFREEZE_FORWARD_R1"

LINEAR_WEIGHTS = {"a2_rank_pct": 0.55, "ridge_rank_pct": 0.15, "xgb_rank_pct": 0.15, "q90_rank_pct": 0.15}
R6_PENALTY = 0.10
META_FEATURES = [
    "a2_raw_score", "a2_rank_pct", "ridge_oof_pred", "ridge_rank_pct",
    "xgb_oof_pred", "xgb_rank_pct", "q90_oof_pred", "q90_rank_pct",
]
META_PARAMS = {
    "objective": "rank:pairwise", "max_depth": 2, "learning_rate": 0.03,
    "n_estimators": 200, "subsample": 0.80, "colsample_bytree": 1.00,
    "reg_lambda": 10.0, "random_state": SEED, "n_jobs": 1,
    "tree_method": "hist", "verbosity": 0,
}


class ResearchContractError(RuntimeError):
    """A temporal, provenance, or portfolio contract violation."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ResearchContractError(code)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_fingerprint(root: Path) -> str:
    require(root.is_dir(), f"FROZEN_TREE_MISSING:{root}")
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix().lower()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def reject_post_2025_outcomes(frame: pd.DataFrame) -> None:
    require("signal_date" in frame and "target_end_date" in frame, "OUTCOME_DATE_COLUMNS_MISSING")
    signal = pd.to_datetime(frame.signal_date)
    maturity = pd.to_datetime(frame.target_end_date)
    require(signal.lt(BOUNDARY).all(), "POST_2025_SIGNAL_REJECTED")
    require(maturity.lt(BOUNDARY).all(), "POST_2025_OUTCOME_REJECTED")


def stable_rank_pct(frame: pd.DataFrame, column: str, *, higher_is_better: bool = True) -> pd.Series:
    return frame.groupby("signal_date", sort=False)[column].rank(
        method="average", pct=True, ascending=higher_is_better,
    )


def deterministic_rank(frame: pd.DataFrame, score_column: str, output_column: str) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["signal_date", score_column, "ticker"], ascending=[True, False, True], kind="mergesort",
    ).copy()
    ordered[output_column] = ordered.groupby("signal_date", sort=False).cumcount().add(1).astype(np.int16)
    return ordered.sort_index()


def select_raw_top60(raw: pd.DataFrame) -> pd.DataFrame:
    require(not raw.duplicated(["signal_date", "security_id"]).any(), "RAW_DUPLICATE_SECURITY_DATE")
    top = raw.loc[raw.a2_raw_rank.le(CANDIDATE_TOP_N)].copy()
    counts = top.groupby("signal_date", sort=False).size()
    require(len(counts) > 0 and counts.eq(CANDIDATE_TOP_N).all(), "RAW_TOP60_CARDINALITY")
    return top


def assert_date_fold_integrity(frame: pd.DataFrame, fold_column: str = "outer_fold") -> None:
    counts = frame.groupby("signal_date", sort=False)[fold_column].nunique(dropna=False)
    require(counts.eq(1).all(), "SAME_DATE_ROWS_SPLIT_ACROSS_FOLDS")


def fixed_linear_score(frame: pd.DataFrame, r6_available: bool) -> pd.Series:
    score = sum(weight * frame[column].astype(float) for column, weight in LINEAR_WEIGHTS.items())
    if r6_available:
        score = score - R6_PENALTY * (frame.r6_bad_rank_pct.astype(float) - 0.50)
    return score


def assert_selection_contract(panel: pd.DataFrame, rank_column: str, valid_dates: Iterable[pd.Timestamp] | None = None) -> None:
    subset = panel if valid_dates is None else panel.loc[panel.signal_date.isin(set(pd.to_datetime(list(valid_dates))))]
    selected = subset.loc[subset[rank_column].le(FINAL_TOP_N)]
    counts = selected.groupby("signal_date", sort=False).size()
    require(len(counts) == subset.signal_date.nunique(), "FINAL_DATE_COVERAGE")
    require(counts.eq(FINAL_TOP_N).all(), "FINAL_TOP20_CARDINALITY")
    require(selected.a2_raw_rank.le(CANDIDATE_TOP_N).all(), "SELECTION_OUTSIDE_RAW_TOP60")


@dataclass
class PanelBundle:
    panel: pd.DataFrame
    raw_full: pd.DataFrame
    component_status: dict[str, str]
    component_facts: dict[str, Any]


def build_meta_panel() -> PanelBundle:
    required = [MODEL_FAMILY_OOF, NG8_OOF, R6_OOF, R6_SPEC, FOLD_MANIFEST, MODEL_CONTRACT, NG8_CONTRACT, XGB_FOLD_CONTRACT]
    for path in required:
        require(path.is_file(), f"AUTHORITATIVE_INPUT_MISSING:{path}")

    model = pd.read_parquet(MODEL_FAMILY_OOF, columns=[
        "signal_date", "security_id", "ticker", "target", "target_end_date",
        "family_id", "fold_id", "prediction", "rank",
    ])
    model["signal_date"] = pd.to_datetime(model.signal_date)
    model["target_end_date"] = pd.to_datetime(model.target_end_date)
    raw = model.loc[model.family_id.eq("M0_HGB_EXACT")].copy()
    raw = raw.rename(columns={"prediction": "a2_raw_score", "rank": "a2_raw_rank", "fold_id": "outer_fold"})
    reject_post_2025_outcomes(raw)
    require(tuple(raw.outer_fold.drop_duplicates()) == OUTER_FOLDS, "RAW_OUTER_FOLD_IDENTITY")
    assert_date_fold_integrity(raw)
    require(not raw.duplicated(["signal_date", "security_id"]).any(), "RAW_DUPLICATE")

    xgb = model.loc[model.family_id.eq("M2_XGBOOST"), [
        "signal_date", "security_id", "ticker", "target", "target_end_date", "fold_id", "prediction",
    ]].rename(columns={"prediction": "xgb_oof_pred", "target": "xgb_target", "target_end_date": "xgb_target_end", "fold_id": "xgb_fold"})
    ng8 = pd.read_parquet(NG8_OOF, columns=[
        "signal_date", "security_id", "ticker", "target", "target_end_date", "ridge_prediction",
        "quantile_prediction", "outer_fold", "model_family", "selected_config",
    ]).rename(columns={
        "target": "ng8_target", "target_end_date": "ng8_target_end", "outer_fold": "ng8_fold",
        "ridge_prediction": "ridge_oof_pred", "quantile_prediction": "q90_oof_pred",
    })
    ng8["signal_date"] = pd.to_datetime(ng8.signal_date)
    ng8["ng8_target_end"] = pd.to_datetime(ng8.ng8_target_end)
    reject_post_2025_outcomes(ng8.rename(columns={"ng8_target_end": "target_end_date"}))

    top = select_raw_top60(raw)
    panel = top.merge(xgb, on=["signal_date", "security_id", "ticker"], how="left", validate="one_to_one")
    panel = panel.merge(ng8, on=["signal_date", "security_id", "ticker"], how="left", validate="one_to_one")
    for column in ("xgb_oof_pred", "ridge_oof_pred", "q90_oof_pred"):
        require(panel[column].notna().all(), f"TOP60_COMPONENT_COVERAGE:{column}")
    require(panel.outer_fold.eq(panel.xgb_fold).all() and panel.outer_fold.eq(panel.ng8_fold).all(), "COMPONENT_FOLD_MISMATCH")
    require(np.max(np.abs(panel.target - panel.xgb_target)) <= 1e-12, "XGB_TARGET_IDENTITY")
    require(np.max(np.abs(panel.target - panel.ng8_target)) <= 1e-12, "NG8_TARGET_IDENTITY")
    require(pd.to_datetime(panel.target_end_date).eq(pd.to_datetime(panel.xgb_target_end)).all(), "XGB_MATURITY_IDENTITY")
    require(pd.to_datetime(panel.target_end_date).eq(pd.to_datetime(panel.ng8_target_end)).all(), "NG8_MATURITY_IDENTITY")

    panel["a2_rank_pct"] = stable_rank_pct(panel, "a2_raw_score")
    panel["ridge_rank_pct"] = stable_rank_pct(panel, "ridge_oof_pred")
    panel["xgb_rank_pct"] = stable_rank_pct(panel, "xgb_oof_pred")
    panel["q90_rank_pct"] = stable_rank_pct(panel, "q90_oof_pred")

    r6 = pd.read_parquet(R6_OOF, columns=["information_date", "ticker", "candidate_id", "predicted_bad_asymmetry_risk", "fold", "train_max_target_end", "embargo_cutoff"])
    r6 = r6.loc[r6.candidate_id.eq("LGBM_BAD_ASYM_2")].copy()
    r6["information_date"] = pd.to_datetime(r6.information_date)
    r6["train_max_target_end"] = pd.to_datetime(r6.train_max_target_end)
    r6["embargo_cutoff"] = pd.to_datetime(r6.embargo_cutoff)
    require(r6.information_date.lt(BOUNDARY).all(), "R6_POST2025_INFORMATION")
    require(r6.train_max_target_end.lt(r6.embargo_cutoff).all(), "R6_OOF_PROVENANCE_FAILURE")
    r6_join = panel[["signal_date", "ticker"]].merge(
        r6[["information_date", "ticker", "predicted_bad_asymmetry_risk"]],
        left_on=["signal_date", "ticker"], right_on=["information_date", "ticker"], how="left", validate="one_to_one",
    )
    r6_coverage = float(r6_join.predicted_bad_asymmetry_risk.notna().mean())
    r6_date_min = int(r6_join.groupby("signal_date").predicted_bad_asymmetry_risk.count().min())
    r6_available = bool(np.isclose(r6_coverage, 1.0) and r6_date_min == CANDIDATE_TOP_N)
    if r6_available:
        panel["r6_bad_oof_score"] = r6_join.predicted_bad_asymmetry_risk.to_numpy(float)
        panel["r6_bad_rank_pct"] = stable_rank_pct(panel, "r6_bad_oof_score")
    else:
        panel["r6_bad_oof_score"] = np.nan
        panel["r6_bad_rank_pct"] = np.nan

    panel["linear_score"] = fixed_linear_score(panel, r6_available)
    panel = deterministic_rank(panel, "linear_score", "linear_rank")
    assert_selection_contract(panel, "a2_raw_rank")
    assert_selection_contract(panel, "linear_rank")
    component_status = {
        "ridge": "AVAILABLE_STRICT_OUTER_OOF_NG8_FIXED",
        "xgb": "AVAILABLE_STRICT_OUTER_OOF_M2_XGBOOST",
        "q90": "AVAILABLE_STRICT_OUTER_OOF_NG8_Q90",
        "r6_bad": ("AVAILABLE_STRICT_OUTER_OOF" if r6_available else "COMPONENT_UNAVAILABLE_TOP20_CONDITIONED_NOT_TOP60_TRANSPORTABLE"),
    }
    component_facts = {
        "top60_rows": int(len(panel)), "decision_dates": int(panel.signal_date.nunique()),
        "date_min": str(panel.signal_date.min().date()), "date_max": str(panel.signal_date.max().date()),
        "target_maturity_max": str(pd.to_datetime(panel.target_end_date).max().date()),
        "ridge_coverage": float(panel.ridge_oof_pred.notna().mean()),
        "xgb_coverage": float(panel.xgb_oof_pred.notna().mean()),
        "q90_coverage": float(panel.q90_oof_pred.notna().mean()),
        "r6_top60_coverage": r6_coverage, "r6_min_names_per_date": r6_date_min,
        "r6_domain": json.loads(R6_SPEC.read_text(encoding="utf-8"))["domain"]["type"],
    }
    return PanelBundle(panel, raw, component_status, component_facts)


def fit_meta_oof(panel: pd.DataFrame, *, n_estimators: int | None = None) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    from xgboost import XGBRanker

    assert_date_fold_integrity(panel)
    outputs: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    params = dict(META_PARAMS)
    if n_estimators is not None:
        params["n_estimators"] = int(n_estimators)
    for fold in OUTER_FOLDS:
        valid = panel.loc[panel.outer_fold.eq(fold)].copy()
        require(len(valid) > 0, f"EMPTY_META_VALID:{fold}")
        test_start = valid.signal_date.min()
        train = panel.loc[(panel.signal_date < test_start) & (pd.to_datetime(panel.target_end_date) < test_start)].copy()
        if train.empty:
            audits.append({
                "fold_id": fold, "status": "COMPONENT_UNAVAILABLE_NO_PRIOR_STRICT_COMPONENT_OOF",
                "train_rows": 0, "validation_rows": int(len(valid)), "test_start": str(test_start.date()),
            })
            continue
        train = train.sort_values(["signal_date", "ticker"], kind="mergesort")
        valid = valid.sort_values(["signal_date", "ticker"], kind="mergesort")
        require(train.signal_date.max() < valid.signal_date.min(), f"META_NON_CHRONOLOGICAL:{fold}")
        require(pd.to_datetime(train.target_end_date).max() < valid.signal_date.min(), f"META_LABEL_OVERLAP:{fold}")
        assert_date_fold_integrity(train)
        model = XGBRanker(**params)
        groups = train.groupby("signal_date", sort=False).size().to_numpy(dtype=np.uint32)
        model.fit(train[META_FEATURES].to_numpy(np.float32), train.target.to_numpy(np.float32), group=groups, verbose=False)
        scored = valid.copy()
        scored["meta_score"] = model.predict(valid[META_FEATURES].to_numpy(np.float32)).astype(float)
        require(np.isfinite(scored.meta_score).all(), f"META_NONFINITE:{fold}")
        scored = deterministic_rank(scored, "meta_score", "meta_rank")
        outputs.append(scored)
        audits.append({
            "fold_id": fold, "status": "PASS_STRICT_META_OOF", "train_rows": int(len(train)),
            "train_dates": int(train.signal_date.nunique()), "validation_rows": int(len(valid)),
            "validation_dates": int(valid.signal_date.nunique()), "train_max_signal": str(train.signal_date.max().date()),
            "train_max_target_end": str(pd.to_datetime(train.target_end_date).max().date()),
            "test_start": str(valid.signal_date.min().date()), "test_end": str(valid.signal_date.max().date()),
        })
    require(outputs, "NO_VALID_META_OUTER_FOLD")
    result = pd.concat(outputs, ignore_index=True)
    assert_selection_contract(result, "meta_rank")
    return result, audits


def load_portfolio_runtime(raw_full: pd.DataFrame) -> tuple[Any, pd.DataFrame]:
    r4 = import_file("a2_nextgen_r4", R4_SOURCE)
    coverage = import_file("a2_nextgen_coverage", COVERAGE_SOURCE)
    _, _, canonical = coverage.load_inputs()
    overlay = pd.read_parquet(coverage.OVERLAY_PATH)
    prices = coverage.combined_prices(canonical, overlay, set(raw_full.ticker))
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    require(prices.trade_date.lt(BOUNDARY).all(), "POST2025_PRICE_READ")
    return r4, prices


def portfolio_signals(frame: pd.DataFrame, rank_column: str) -> pd.DataFrame:
    out = frame[["signal_date", "ticker", rank_column]].copy().rename(columns={rank_column: "rank"})
    out["a1_rank"] = out["rank"]
    out["a2_rank"] = out["rank"]
    out["universe_size"] = out.groupby("signal_date", sort=False).ticker.transform("size")
    return out


def reconcile_control(raw_full: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    if raw_full is None:
        raw_full = pd.read_parquet(M0_OOF)
        raw_full = raw_full.rename(columns={"prediction": "a2_raw_score", "rank": "a2_raw_rank", "fold_id": "outer_fold"})
    reject_post_2025_outcomes(raw_full)
    r4, prices = load_portfolio_runtime(raw_full)
    got = r4.simulate_portfolio(portfolio_signals(raw_full, "a2_raw_rank"), prices, "C0_RAW_A2", "rank", FINAL_TOP_N, COST_BPS)
    ref = pd.read_parquet(M0_PATH)
    require(got.execution_date.equals(ref.execution_date), "CONTROL_EXECUTION_DATE_MISMATCH")
    numeric = [
        "gross_return", "net_return", "net_nav", "target_turnover", "executed_turnover",
        "transaction_cost_fraction", "transaction_cost_amount", "actual_risky_name_count",
    ]
    errors = {column: float(np.nanmax(np.abs(got[column].to_numpy(float) - ref[column].to_numpy(float)))) for column in numeric}
    require(max(errors.values()) <= np.finfo(float).eps, f"CONTROL_REPLAY_MISMATCH:{errors}")
    return got, {"status": "PASS_EXACT_OR_MACHINE_PRECISION", "rows": int(len(got)), "max_abs_errors": errors}


def simulate_ranked(frame: pd.DataFrame, rank_column: str, model: str, r4: Any, prices: pd.DataFrame) -> pd.DataFrame:
    assert_selection_contract(frame, rank_column)
    return r4.simulate_portfolio(portfolio_signals(frame, rank_column), prices, model, "rank", FINAL_TOP_N, COST_BPS)


def performance_metrics(path: pd.DataFrame) -> dict[str, float]:
    ordered = path.sort_values("execution_date", kind="mergesort")
    returns = ordered.net_return.to_numpy(float)
    nav = np.cumprod(1.0 + returns)
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    cumulative = float(nav[-1] - 1.0)
    volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    annual_mean = float(np.mean(returns) * 252.0)
    negative = returns[returns < 0]
    downside = float(np.std(negative, ddof=0) * np.sqrt(252.0)) if len(negative) else math.nan
    mdd = float(drawdown.min())
    benchmark = ordered.benchmark_return.to_numpy(float)
    beta = float(np.cov(returns, benchmark, ddof=0)[0, 1] / np.var(benchmark)) if np.var(benchmark) > 0 else math.nan
    return {
        "observation_count": int(len(returns)), "cumulative_return": cumulative,
        "cagr": float((1.0 + cumulative) ** (252.0 / len(returns)) - 1.0),
        "annualized_volatility": volatility, "sharpe": annual_mean / volatility if volatility > 0 else math.nan,
        "sortino": annual_mean / downside if downside > 0 else math.nan, "max_drawdown": mdd,
        "calmar": float(((1.0 + cumulative) ** (252.0 / len(returns)) - 1.0) / abs(mdd)) if mdd < 0 else math.nan,
        "turnover": float(ordered.executed_turnover.mean() * 252.0),
        "transaction_cost": float(ordered.transaction_cost_amount.sum()),
        "average_holdings": float(ordered.actual_risky_name_count.mean()), "market_beta": beta,
    }


def topk_diagnostics(selected_source: pd.DataFrame, rank_column: str, raw_full: pd.DataFrame, vol: pd.DataFrame) -> dict[str, float]:
    chosen = selected_source.loc[selected_source[rank_column].le(FINAL_TOP_N), ["signal_date", "security_id", "ticker", "target"]].copy()
    dates = pd.DatetimeIndex(sorted(chosen.signal_date.unique()))
    candidates = selected_source.loc[selected_source.signal_date.isin(dates)].copy()
    raw = candidates.loc[candidates.a2_raw_rank.le(FINAL_TOP_N)]
    oracle = candidates.sort_values(["signal_date", "target", "ticker"], ascending=[True, False, True], kind="mergesort").groupby("signal_date", sort=False).head(FINAL_TOP_N)
    chosen_sets = chosen.groupby("signal_date").security_id.apply(set)
    raw_sets = raw.groupby("signal_date").security_id.apply(set)
    oracle_sets = oracle.groupby("signal_date").security_id.apply(set)
    overlap = np.mean([len(chosen_sets[d] & raw_sets[d]) / FINAL_TOP_N for d in dates])
    recall = np.mean([len(chosen_sets[d] & oracle_sets[d]) / FINAL_TOP_N for d in dates])
    selected_return = chosen.groupby("signal_date").target.mean().reindex(dates)
    raw_return = raw.groupby("signal_date").target.mean().reindex(dates)
    oracle_return = oracle.groupby("signal_date").target.mean().reindex(dates)

    full = raw_full.loc[raw_full.signal_date.isin(dates)]
    extreme_recall: list[float] = []
    for date, day in full.groupby("signal_date", sort=True):
        count = max(1, math.ceil(len(day) * 0.01))
        winners = set(day.nlargest(count, "target", keep="first").security_id)
        extreme_recall.append(len(winners & chosen_sets[pd.Timestamp(date)]) / count)
    vol_selected = chosen[["signal_date", "security_id"]].merge(vol, on=["signal_date", "security_id"], how="left", validate="one_to_one")
    require(vol_selected.realized_vol_20d.notna().all(), "REALIZED_VOL_DIAGNOSTIC_MISSING")
    return {
        "selected_top20_future_return": float(selected_return.mean()),
        "top20_raw_overlap": float(overlap), "top20_replacement_count": float(FINAL_TOP_N * (1.0 - overlap)),
        "top20_boundary_return_delta": float((selected_return - raw_return).mean()),
        "oracle_top20_recall": float(recall), "oracle_regret": float((oracle_return - selected_return).mean()),
        "extreme_winner_capture": float(np.mean(extreme_recall)),
        "average_realized_volatility_20d": float(vol_selected.realized_vol_20d.mean()),
    }


def curve_rows(path: pd.DataFrame, strategy: str) -> pd.DataFrame:
    out = path.sort_values("execution_date", kind="mergesort").copy()
    nav = np.cumprod(1.0 + out.net_return.to_numpy(float))
    return pd.DataFrame({
        "date": out.execution_date.dt.strftime("%Y-%m-%d"), "strategy": strategy,
        "daily_return": out.net_return.to_numpy(float), "nav": nav,
        "drawdown": nav / np.maximum.accumulate(nav) - 1.0,
        "turnover": out.executed_turnover.to_numpy(float), "cost": out.transaction_cost_amount.to_numpy(float),
    })


def metric_row(strategy: str, scope: str, fold_id: str, path: pd.DataFrame, diagnostics: dict[str, float] | None, status: str = "PASS") -> dict[str, Any]:
    metrics = performance_metrics(path) if len(path) else {key: math.nan for key in (
        "observation_count", "cumulative_return", "cagr", "annualized_volatility", "sharpe", "sortino",
        "max_drawdown", "calmar", "turnover", "transaction_cost", "average_holdings", "market_beta",
    )}
    return {"strategy": strategy, "scope": scope, "fold_id": fold_id, "status": status, **metrics, **(diagnostics or {})}


def by_year(path: pd.DataFrame, year: int) -> pd.DataFrame:
    return path.loc[pd.to_datetime(path.execution_date).dt.year.eq(year)].copy()


def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def classification(challenger: dict[str, Any], raw: dict[str, Any], positive: int, valid_folds: int) -> str:
    threshold = math.ceil(0.60 * valid_folds)
    return "PROMISING_PRE2026" if challenger["sharpe"] > raw["sharpe"] and positive >= threshold else "NO_STABLE_INCREMENT"


def run(output_dir: Path, targeted_tests: str, anti_bloat_status: str) -> dict[str, Any]:
    require(output_dir.resolve() == OUT.resolve(), "NONCANONICAL_RESULT_DESTINATION")
    require(not output_dir.is_relative_to(REPO), "ANTI_BLOAT_RESULT_INSIDE_REPOSITORY")
    forward_before = tree_fingerprint(FROZEN_FORWARD)
    bundle = build_meta_panel()
    panel, raw_full = bundle.panel, bundle.raw_full
    meta, meta_audits = fit_meta_oof(panel)
    r4, prices = load_portfolio_runtime(raw_full)
    control, reconciliation = reconcile_control(raw_full)
    linear = simulate_ranked(panel, "linear_rank", "C1_FIXED_LINEAR_RERANK", r4, prices)
    meta_path = simulate_ranked(meta, "meta_rank", "C2_SHALLOW_XGB_RERANK", r4, prices)
    meta_dates = pd.DatetimeIndex(sorted(meta.signal_date.unique()))
    raw_common_frame = panel.loc[panel.signal_date.isin(meta_dates)]
    linear_common_frame = panel.loc[panel.signal_date.isin(meta_dates)]
    raw_common = simulate_ranked(raw_common_frame, "a2_raw_rank", "C0_RAW_A2_C2_COMMON", r4, prices)
    linear_common = simulate_ranked(linear_common_frame, "linear_rank", "C1_LINEAR_C2_COMMON", r4, prices)

    vol = pd.read_parquet(RESEARCH_DATA, columns=["signal_date", "security_id", "realized_vol_20d"])
    vol["signal_date"] = pd.to_datetime(vol.signal_date)
    require(vol.signal_date.lt(BOUNDARY).all(), "POST2025_VOL_FEATURE_READ")
    diag_raw = topk_diagnostics(panel, "a2_raw_rank", raw_full, vol)
    diag_linear = topk_diagnostics(panel, "linear_rank", raw_full, vol)
    diag_meta = topk_diagnostics(meta, "meta_rank", raw_full, vol)
    diag_raw_common = topk_diagnostics(raw_common_frame, "a2_raw_rank", raw_full, vol)

    rows: list[dict[str, Any]] = []
    rows.append(metric_row("C0_RAW_A2", "AGGREGATE_OOF", "ALL_VALID", control, diag_raw))
    rows.append(metric_row("C1_FIXED_LINEAR_RERANK", "AGGREGATE_OOF", "ALL_VALID", linear, diag_linear))
    rows.append(metric_row("C2_SHALLOW_XGB_RERANK", "AGGREGATE_OOF", "OUTER_2024|OUTER_2025", meta_path, diag_meta))
    rows.append(metric_row("C0_RAW_A2", "C2_COMMON_SUPPORT", "OUTER_2024|OUTER_2025", raw_common, diag_raw_common))
    rows.append(metric_row("C1_FIXED_LINEAR_RERANK", "C2_COMMON_SUPPORT", "OUTER_2024|OUTER_2025", linear_common, topk_diagnostics(linear_common_frame, "linear_rank", raw_full, vol)))
    fold_deltas: dict[str, list[float]] = {"C1_FIXED_LINEAR_RERANK": [], "C2_SHALLOW_XGB_RERANK": []}
    for year in (2023, 2024, 2025):
        fold = f"OUTER_{year}"
        raw_fold = by_year(control, year)
        linear_fold = by_year(linear, year)
        raw_diag_fold = topk_diagnostics(panel.loc[panel.outer_fold.eq(fold)], "a2_raw_rank", raw_full, vol)
        linear_diag_fold = topk_diagnostics(panel.loc[panel.outer_fold.eq(fold)], "linear_rank", raw_full, vol)
        raw_row = metric_row("C0_RAW_A2", "OUTER_FOLD", fold, raw_fold, raw_diag_fold)
        linear_row = metric_row("C1_FIXED_LINEAR_RERANK", "OUTER_FOLD", fold, linear_fold, linear_diag_fold)
        rows.extend([raw_row, linear_row])
        fold_deltas["C1_FIXED_LINEAR_RERANK"].append(float(linear_row["sharpe"] - raw_row["sharpe"]))
        if year == 2023:
            rows.append(metric_row("C2_SHALLOW_XGB_RERANK", "OUTER_FOLD", fold, pd.DataFrame(), None, "COMPONENT_UNAVAILABLE_NO_PRIOR_STRICT_COMPONENT_OOF"))
        else:
            raw_c_fold = by_year(raw_common, year)
            meta_fold = by_year(meta_path, year)
            meta_panel_fold = meta.loc[meta.outer_fold.eq(fold)]
            raw_panel_fold = raw_common_frame.loc[raw_common_frame.outer_fold.eq(fold)]
            raw_common_row = metric_row("C0_RAW_A2", "C2_COMMON_OUTER_FOLD", fold, raw_c_fold, topk_diagnostics(raw_panel_fold, "a2_raw_rank", raw_full, vol))
            meta_row = metric_row("C2_SHALLOW_XGB_RERANK", "OUTER_FOLD", fold, meta_fold, topk_diagnostics(meta_panel_fold, "meta_rank", raw_full, vol))
            rows.extend([raw_common_row, meta_row])
            fold_deltas["C2_SHALLOW_XGB_RERANK"].append(float(meta_row["sharpe"] - raw_common_row["sharpe"]))
    metrics = pd.DataFrame(rows)
    aggregate = metrics.loc[metrics.scope.eq("AGGREGATE_OOF")].set_index("strategy")
    common_raw_metrics = performance_metrics(raw_common)
    linear_metrics = aggregate.loc["C1_FIXED_LINEAR_RERANK"].to_dict()
    raw_metrics = aggregate.loc["C0_RAW_A2"].to_dict()
    meta_metrics = aggregate.loc["C2_SHALLOW_XGB_RERANK"].to_dict()
    linear_positive = int(sum(delta > 0 for delta in fold_deltas["C1_FIXED_LINEAR_RERANK"]))
    meta_positive = int(sum(delta > 0 for delta in fold_deltas["C2_SHALLOW_XGB_RERANK"]))
    linear_class = classification(linear_metrics, raw_metrics, linear_positive, 3)
    meta_class = classification(meta_metrics, common_raw_metrics, meta_positive, 2)
    linear_delta_sharpe = float(linear_metrics["sharpe"] - raw_metrics["sharpe"])
    meta_delta_sharpe = float(meta_metrics["sharpe"] - common_raw_metrics["sharpe"])
    best = "C1_FIXED_LINEAR_RERANK" if linear_delta_sharpe >= meta_delta_sharpe else "C2_SHALLOW_XGB_RERANK"
    best_class = linear_class if best.startswith("C1") else meta_class
    best_diag = diag_linear if best.startswith("C1") else diag_meta
    best_raw_diag = diag_raw if best.startswith("C1") else diag_raw_common
    best_beta = float(linear_metrics["market_beta"] if best.startswith("C1") else meta_metrics["market_beta"])
    best_raw_beta = float(raw_metrics["market_beta"] if best.startswith("C1") else common_raw_metrics["market_beta"])
    best_fold_deltas = fold_deltas[best]
    boundary_improved = best_diag["oracle_top20_recall"] > best_raw_diag["oracle_top20_recall"] and best_diag["oracle_regret"] < best_raw_diag["oracle_regret"]
    extreme_improved = best_diag["extreme_winner_capture"] > best_raw_diag["extreme_winner_capture"]
    single_fold = bool(sum(delta > 0 for delta in best_fold_deltas) == 1)
    beta_explanation = "POSSIBLE_HIGHER_BETA" if best_beta > best_raw_beta + 0.05 else "NOT_EXPLAINED_BY_HIGHER_BETA"

    for strategy, comparator_path in (("C1_FIXED_LINEAR_RERANK", control), ("C2_SHALLOW_XGB_RERANK", raw_common)):
        mask = metrics.strategy.eq(strategy) & metrics.scope.eq("AGGREGATE_OOF")
        comparison = performance_metrics(comparator_path)
        metrics.loc[mask, "delta_sharpe_vs_raw"] = metrics.loc[mask, "sharpe"] - comparison["sharpe"]
        metrics.loc[mask, "turnover_delta_vs_raw"] = metrics.loc[mask, "turnover"] - comparison["turnover"]
        metrics.loc[mask, "cost_delta_vs_raw"] = metrics.loc[mask, "transaction_cost"] - comparison["transaction_cost"]
        metrics.loc[mask, "mdd_delta_vs_raw"] = metrics.loc[mask, "max_drawdown"] - comparison["max_drawdown"]
    metrics.loc[metrics.strategy.eq("C1_FIXED_LINEAR_RERANK"), "classification"] = linear_class
    metrics.loc[metrics.strategy.eq("C2_SHALLOW_XGB_RERANK"), "classification"] = meta_class
    metrics.loc[metrics.strategy.eq("C1_FIXED_LINEAR_RERANK") & metrics.scope.eq("AGGREGATE_OOF"), "positive_outer_folds"] = linear_positive
    metrics.loc[metrics.strategy.eq("C2_SHALLOW_XGB_RERANK") & metrics.scope.eq("AGGREGATE_OOF"), "positive_outer_folds"] = meta_positive

    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = {"final_report.md", "strategy_metrics.csv", "daily_curves.csv", "trial_ledger.json"}
    unexpected = {p.name for p in output_dir.iterdir()} - allowed
    require(not unexpected, f"RESULT_ARTIFACT_BUDGET_PREEXISTING:{sorted(unexpected)}")
    metrics.to_csv(output_dir / "strategy_metrics.csv", index=False, lineterminator="\n")
    curves = pd.concat([
        curve_rows(control, "C0_RAW_A2"), curve_rows(linear, "C1_FIXED_LINEAR_RERANK"),
        curve_rows(meta_path, "C2_SHALLOW_XGB_RERANK"),
    ], ignore_index=True)
    curves.to_csv(output_dir / "daily_curves.csv", index=False, lineterminator="\n")

    input_paths = [MODEL_FAMILY_OOF, NG8_OOF, R6_OOF, R6_SPEC, FOLD_MANIFEST, MODEL_CONTRACT, NG8_CONTRACT, XGB_FOLD_CONTRACT, M0_PATH, R4_SOURCE, COVERAGE_SOURCE]
    hash_summary = {str(path): sha256_file(path) for path in input_paths}
    hash_summary[str(Path(__file__).resolve())] = sha256_file(Path(__file__).resolve())
    test_path = REPO / "scripts" / "v22" / "test_a2_nextgen_topk_ensemble_rerank_r1.py"
    if test_path.is_file():
        hash_summary[str(test_path)] = sha256_file(test_path)
    ledger = {
        "task_id": TASK_ID, "research_only": True, "date_boundary": "date<2026-01-01",
        "date_max_used": str(pd.to_datetime(panel.target_end_date).max().date()), "post_2025_outcome_used": False,
        "economic_candidate_count": 3, "hyperparameter_search": False, "candidate_topn_search": False,
        "ensemble_weight_search": False, "candidate_top_n": CANDIDATE_TOP_N, "final_top_n": FINAL_TOP_N,
        "actual_economic_trials": ["C0_RAW_A2", "C1_FIXED_LINEAR_RERANK", "C2_SHALLOW_XGB_RERANK"],
        "fixed_parameters": {"linear_weights": LINEAR_WEIGHTS, "r6_penalty": R6_PENALTY, "meta": META_PARAMS},
        "component_status": bundle.component_status, "component_facts": bundle.component_facts,
        "fold_contract": {"authoritative": list(OUTER_FOLDS), "meta_audits": meta_audits, "same_date_rows_split": False},
        "attempt_history": [
            {"kind": "NON_ECONOMIC_PREFLIGHT", "status": "DEBUG_RETRY", "reason": "DIRECT_YEAR_PARTITIONS_LACKED_COMPLETE_QQQ_CALENDAR;SWITCHED_TO_AUTHORITATIVE_COVERAGE_COMBINED_PRICE_LOADER"},
            {"kind": "NON_ECONOMIC_OUTPUT", "status": "COMPATIBILITY_RETRY", "reason": "FINAL_STDOUT_JSON_REJECTED_NAN_FROM_DECLARED_UNAVAILABLE_FOLD_AFTER_ARTIFACT_COMMIT;SUMMARY_OUTPUT_REDUCED_TO_SCALARS"},
            {"kind": "NON_ECONOMIC_REPORTING", "status": "METRIC_ALIGNMENT_RETRY", "reason": "TURNOVER_AND_SORTINO_LABELS_ALIGNED_TO_EXISTING_AUTHORITATIVE_ECONOMIC_METRICS;C2_MATCHED_RAW_FOLD_ROWS_ADDED"},
            {"kind": "ECONOMIC_RUN", "status": "PASS", "economic_trials": 3, "reason": "PREREGISTERED_FINAL_MATERIALIZATION"},
        ],
        "control_reconciliation": reconciliation, "fold_sharpe_deltas": fold_deltas,
        "classification": {"C1_FIXED_LINEAR_RERANK": linear_class, "C2_SHALLOW_XGB_RERANK": meta_class},
        "hash_summary": hash_summary, "forward_state_modified": False, "canonical_state_modified": False,
        "moomoo_called": False, "targeted_tests": targeted_tests, "anti_bloat_status": anti_bloat_status,
    }
    write_json_atomic(output_dir / "trial_ledger.json", ledger)

    report = build_report(
        bundle, reconciliation, meta_audits, metrics, fold_deltas, linear_class, meta_class, best, best_class,
        boundary_improved, extreme_improved, single_fold, beta_explanation, hash_summary, targeted_tests, anti_bloat_status,
    )
    write_text_atomic(output_dir / "final_report.md", report)
    require({p.name for p in output_dir.iterdir()} == allowed, "RESULT_ARTIFACT_COUNT_OR_NAME")
    forward_after = tree_fingerprint(FROZEN_FORWARD)
    require(forward_after == forward_before, "FROZEN_FORWARD_STATE_MODIFIED")
    return {
        "overall_status": "COMPLETE_RESEARCH_ONLY", "control_replay_status": reconciliation["status"],
        "best": best, "classification": best_class, "result_dir": str(output_dir),
        "metrics": metrics.loc[metrics.scope.eq("AGGREGATE_OOF")].to_dict("records"),
    }


def f(value: Any) -> str:
    return "NOT_AVAILABLE_IN_R1" if value is None or (isinstance(value, float) and not np.isfinite(value)) else f"{float(value):.10f}"


def build_report(
    bundle: PanelBundle, reconciliation: dict[str, Any], meta_audits: list[dict[str, Any]], metrics: pd.DataFrame,
    fold_deltas: dict[str, list[float]], linear_class: str, meta_class: str, best: str, best_class: str,
    boundary_improved: bool, extreme_improved: bool, single_fold: bool, beta_explanation: str,
    hashes: dict[str, str], targeted_tests: str, anti_bloat_status: str,
) -> str:
    agg = metrics.loc[metrics.scope.eq("AGGREGATE_OOF")].set_index("strategy")
    common = metrics.loc[(metrics.strategy.eq("C0_RAW_A2")) & metrics.scope.eq("C2_COMMON_SUPPORT")].iloc[0]
    raw, linear, meta = agg.loc["C0_RAW_A2"], agg.loc["C1_FIXED_LINEAR_RERANK"], agg.loc["C2_SHALLOW_XGB_RERANK"]
    linear_pos = sum(x > 0 for x in fold_deltas["C1_FIXED_LINEAR_RERANK"])
    meta_pos = sum(x > 0 for x in fold_deltas["C2_SHALLOW_XGB_RERANK"])
    lines = [
        f"# {TASK_ID}", "", "## Research status", "",
        "OVERALL_STATUS=COMPLETE_RESEARCH_ONLY", f"CONTROL_REPLAY_STATUS={reconciliation['status']}",
        f"DATE_MAX_USED={bundle.component_facts['target_maturity_max']}", "POST_2025_OUTCOME_USED=false",
        f"CANDIDATE_TOP_N={CANDIDATE_TOP_N}", f"FINAL_TOP_N={FINAL_TOP_N}", "OUTER_FOLD_COUNT=3", "",
        "## Input provenance and fixed contract", "",
        f"- Raw A2: `{MODEL_FAMILY_OOF}` family `M0_HGB_EXACT`; strict folds 2023/2024/2025; natural target maturity ends {bundle.component_facts['target_maturity_max']}.",
        f"- Ridge/Q90: `{NG8_OOF}`; fixed outer-OOF configuration `RIDGE_A1__Q90_D3__W25`.",
        f"- XGBoost: `{MODEL_FAMILY_OOF}` family `M2_XGBOOST`; nested chronological outer OOF.",
        f"- R6 BAD: `{R6_OOF}` candidate `LGBM_BAD_ASYM_2`; strict OOF but Top20-conditioned hybrid domain. Top60 row coverage is {bundle.component_facts['r6_top60_coverage']:.4%}; excluded rather than extrapolated.",
        f"- Portfolio: authoritative R4 next-open, equal-weight Top20, 10 bps, path-wise self-financing engine at `{R4_SOURCE}`. Only rank changed.",
        f"- Linear weights are fixed at {json.dumps(LINEAR_WEIGHTS, sort_keys=True)}. R6 penalty {R6_PENALTY} is inactive because the component is unavailable; all positive components are present, so no positive-weight renormalization was needed.",
        f"- Meta XGB parameters are fixed at `{json.dumps(META_PARAMS, sort_keys=True)}`; no early stopping or search. OUTER_2023 is unavailable because no prior strict component OOF exists; C2 aggregate and Raw comparator therefore use matched OUTER_2024|OUTER_2025 support.", "",
        "## Control reconciliation", "",
        f"The replay has {reconciliation['rows']} execution rows and maximum numeric identity error {max(reconciliation['max_abs_errors'].values()):.3g}; execution dates, returns, NAV, turnover, and costs match the authoritative `M0_path.parquet` exactly.", "",
        "## Headline aggregate metrics", "",
        "| Strategy | Support | Cum return | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Turnover | Cost | Avg holdings | Beta |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in (("C0_RAW_A2", raw), ("C1_FIXED_LINEAR_RERANK", linear), ("C2_SHALLOW_XGB_RERANK", meta)):
        lines.append(f"| {name} | {row.fold_id} | {row.cumulative_return:.6f} | {row.cagr:.6f} | {row.annualized_volatility:.6f} | {row.sharpe:.6f} | {row.sortino:.6f} | {row.max_drawdown:.6f} | {row.calmar:.6f} | {row.turnover:.6f} | {row.transaction_cost:.6f} | {row.average_holdings:.3f} | {row.market_beta:.6f} |")
    lines += [
        "", f"C1_DELTA_SHARPE_VS_RAW={linear.sharpe - raw.sharpe:.10f}",
        f"C2_DELTA_SHARPE_VS_MATCHED_RAW={meta.sharpe - common.sharpe:.10f}",
        f"C1_POSITIVE_OUTER_FOLDS={linear_pos}/3", f"C2_POSITIVE_OUTER_FOLDS={meta_pos}/2",
        f"C1_CLASSIFICATION={linear_class}", f"C2_CLASSIFICATION={meta_class}", "",
        "## Per-fold Sharpe support", "",
        "| Fold | Raw | Linear | Linear delta | C2 matched Raw | Meta | Meta matched-Raw delta |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    folds = metrics.loc[metrics.scope.eq("OUTER_FOLD")]
    for year in (2023, 2024, 2025):
        fold = f"OUTER_{year}"
        r = folds.loc[(folds.strategy.eq("C0_RAW_A2")) & folds.fold_id.eq(fold)].iloc[0]
        l = folds.loc[(folds.strategy.eq("C1_FIXED_LINEAR_RERANK")) & folds.fold_id.eq(fold)].iloc[0]
        m = folds.loc[(folds.strategy.eq("C2_SHALLOW_XGB_RERANK")) & folds.fold_id.eq(fold)].iloc[0]
        md = "N/A" if year == 2023 else f"{fold_deltas['C2_SHALLOW_XGB_RERANK'][year-2024]:+.6f}"
        matched = "N/A" if year == 2023 else f"{metrics.loc[(metrics.strategy.eq('C0_RAW_A2')) & metrics.scope.eq('C2_COMMON_OUTER_FOLD') & metrics.fold_id.eq(fold), 'sharpe'].iloc[0]:.6f}"
        lines.append(f"| {fold} | {r.sharpe:.6f} | {l.sharpe:.6f} | {l.sharpe-r.sharpe:+.6f} | {matched} | {f(m.sharpe)} | {md} |")
    lines += ["", "## Top-K diagnostics", "",
        "| Strategy | Selected future return | Raw overlap | Replacements | Boundary return delta | Oracle recall | Oracle regret | Extreme winner capture |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in (("C0_RAW_A2", raw), ("C1_FIXED_LINEAR_RERANK", linear), ("C2_SHALLOW_XGB_RERANK", meta)):
        lines.append(f"| {name} | {row.selected_top20_future_return:.6f} | {row.top20_raw_overlap:.6f} | {row.top20_replacement_count:.3f} | {row.top20_boundary_return_delta:.6f} | {row.oracle_top20_recall:.6f} | {row.oracle_regret:.6f} | {row.extreme_winner_capture:.6f} |")
    lines += [
        "", "Candidate oracle is post-outcome diagnostic only: Top20 by realized natural-horizon target inside the fixed Raw A2 Top60. Existing extreme-winner definition is reused: per date, recall of the full-universe realized top 1% inside selected Top20.", "",
        "## Risk diagnostics", "",
        "Market beta and average selected 20-day realized volatility are reported in `strategy_metrics.csv`. Full-Top60 PIT FF12 membership was not persisted as a compact authoritative input, so `SECTOR_CONCENTRATION=NOT_AVAILABLE_IN_R1`; no taxonomy rebuild was launched. " + beta_explanation + ".", "",
        "## Conclusion", "",
        f"BEST_PRE2026_CHALLENGER={best}", f"BEST_CLASSIFICATION={best_class}",
        f"TOP20_BOUNDARY_IMPROVED={str(boundary_improved).lower()}", f"EXTREME_WINNER_CAPTURE_IMPROVED={str(extreme_improved).lower()}",
        f"IMPROVEMENT_DEPENDS_ON_SINGLE_FOLD={str(single_fold).lower()}", f"RISK_BETA_EXPLANATION={beta_explanation}",
        "READY_FOR_TARGET_WEIGHT_R2=false", "PROMOTE_TO_FORWARD=false", "PROMOTE_TO_CANONICAL=false", "",
        "## Governance and reproducibility", "",
        "ECONOMIC_CANDIDATE_COUNT=3", "HYPERPARAMETER_SEARCH=false", "CANDIDATE_TOPN_SEARCH=false", "ENSEMBLE_WEIGHT_SEARCH=false",
        "FORWARD_STATE_MODIFIED=false", "CANONICAL_STATE_MODIFIED=false", "MOOMOO_CALLED=false",
        f"TARGETED_TESTS={targeted_tests}", f"ANTI_BLOAT_STATUS={anti_bloat_status}",
        "Artifacts are limited to `final_report.md`, `strategy_metrics.csv`, `daily_curves.csv`, and `trial_ledger.json`.", "",
        "## Relevant SHA-256", "",
    ]
    for path in (MODEL_FAMILY_OOF, NG8_OOF, R6_OOF, M0_PATH, Path(__file__).resolve()):
        lines.append(f"- `{path}`: `{hashes[str(path)]}`")
    lines += ["", "Exact code paths:", f"- `{Path(__file__).resolve()}`", f"- `{REPO / 'scripts/v22/test_a2_nextgen_topk_ensemble_rerank_r1.py'}`", ""]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--targeted-tests", default="NOT_RUN")
    parser.add_argument("--anti-bloat-status", default="TASK_LOCAL_PASS_FORMAL_GUARD_NOT_RUN")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.output_dir, args.targeted_tests, args.anti_bloat_status)
    summary = {key: value for key, value in result.items() if key != "metrics"}
    print(json.dumps(summary, indent=2, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
