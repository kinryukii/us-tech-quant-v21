from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RUN_ID = "A2_ALGORITHM_BENCHMARK_R1D_STATIC_BLEND"
REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R1A_ROOT = RESULTS_ROOT / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION"
OUT_ROOT = RESULTS_ROOT / RUN_ID
WORK_ROOT = RESULTS_ROOT / f"{RUN_ID}__WORKING"
SCRIPT_PATH = REPO_ROOT / "scripts" / "v22" / Path(__file__).name
R4_SOURCE = REPO_ROOT / "scripts" / "v22" / "abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py"
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
COVERAGE_ROOT = RESULTS_ROOT / "A2_PIT_DATA_COVERAGE_R1"
BOUNDARY = pd.Timestamp("2026-01-01")

A2_MODEL = "M0_A2_HGB_AUTH_TEMPORAL"
XGB_MODEL = "M2_XGB_REG"
FOLDS = ("OUTER_2023", "OUTER_2024", "OUTER_2025")
WEIGHTS = {"W00": 0.00, "W25": 0.25, "W50": 0.50, "W75": 0.75, "W100": 1.00}
INTERIOR = ("W25", "W50", "W75")
CANONICAL_COST_BPS = 10
COST_MULTIPLES = {"1X": 10, "2X": 20, "3X": 30}
EXPECTED_R4_SHA256 = "2d578741df90ba1bd78381ad768fbe0f8cfa34e124ae2712d3c4dfb09dbaa12e"
EXPECTED_COVERAGE_FREEZE_SHA256 = "709ef4840736d8e6b59183591cd5ffb427bfad11683e34ab12957e53fa1e1da3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILURE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def artifact_hashes(root: Path) -> dict[str, str]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {str(Path(row["path"])): row["sha256"] for row in manifest["artifacts"]}


def verify(path: Path, expected: str, audit: list[dict[str, Any]]) -> None:
    actual = sha256(path)
    audit.append(
        {"path": str(path), "expected_sha256": expected, "actual_sha256": actual, "match": actual == expected}
    )
    if actual != expected:
        raise RuntimeError(f"FROZEN_INPUT_HASH_MISMATCH:{path}")


def preflight() -> tuple[Any, Any, list[dict[str, Any]]]:
    hashes = artifact_hashes(R1A_ROOT)
    audit: list[dict[str, Any]] = []
    required = [
        "status.json",
        "a2_temporal_lineage.json",
        "run_r1a.py",
        "oos_predictions.parquet",
        "oof_portfolio_paths.parquet",
        "predictive_metrics_by_fold.csv",
        "economic_metrics_by_fold.csv",
    ]
    for name in required:
        path = R1A_ROOT / name
        verify(path, hashes[str(path)], audit)
    verify(R4_SOURCE, EXPECTED_R4_SHA256, audit)
    coverage_freeze_path = COVERAGE_ROOT / "freeze_manifest.json"
    verify(coverage_freeze_path, EXPECTED_COVERAGE_FREEZE_SHA256, audit)
    coverage_freeze = json.loads(coverage_freeze_path.read_text(encoding="utf-8"))
    coverage_artifacts = {str(Path(row["path"])): row["sha256"] for row in coverage_freeze["artifacts"]}
    coverage_source_path = COVERAGE_ROOT / "source_hash_manifest.json"
    verify(coverage_source_path, coverage_artifacts[str(coverage_source_path)], audit)
    coverage_sources = json.loads(coverage_source_path.read_text(encoding="utf-8"))["inputs_and_overlay"]
    for path_text, identity in coverage_sources.items():
        verify(Path(path_text), identity["sha256"], audit)

    status = json.loads((R1A_ROOT / "status.json").read_text(encoding="utf-8"))
    if status["A2_ALGORITHM_BENCHMARK_R1A_STATUS"] != "PASS_PRE2026_TEMPORAL_ALGORITHM_BENCHMARK_COMPLETE":
        raise RuntimeError("R1A_NOT_AUTHORITATIVE_PASS")
    for key in ("2026_TRAINING_ROWS", "2026_PARAMETER_SEARCH_COUNT", "2026_MODEL_SELECTION_COUNT"):
        if status[key] != 0:
            raise RuntimeError(f"R1A_2026_CONTRACT_FAILURE:{key}")
    r1a = load_module("r1d_frozen_r1a", R1A_ROOT / "run_r1a.py")
    r4 = load_module("r1d_frozen_r4", R4_SOURCE)
    return r1a, r4, audit


def static_contract() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "input": {
            "models": [A2_MODEL, XGB_MODEL],
            "prediction_source": str(R1A_ROOT / "oos_predictions.parquet"),
            "folds": list(FOLDS),
            "shared_pit_universe_required": True,
            "shared_feature_target_execution_cost_contract": True,
            "execution_price_surface": "R1A_FROZEN_2019_2025_CANONICAL_QFQ_PLUS_FROZEN_BACKFILL_OVERLAY",
        },
        "rank_space": {
            "higher_percentile_rank_is_better": True,
            "percentile_rank_method": "WITHIN_DATE_AVERAGE_RANK_OF_FROZEN_RAW_SCORE_PRESERVES_SCORE_TIES",
            "equation": "(1-w)*HGB_PERCENTILE_RANK+w*XGB_PERCENTILE_RANK",
            "raw_score_blending_allowed": False,
            "tie_break": "DESCENDING_BLEND_SCORE_THEN_ASCENDING_TICKER",
        },
        "weights": WEIGHTS,
        "interior_candidates": list(INTERIOR),
        "pre2026_blend_candidate_count": 3,
        "pre2026_blend_selection_count": 1,
        "underlying_model_parameter_search_count": 0,
        "canonical_cost_bps": CANONICAL_COST_BPS,
        "cost_stress_bps": COST_MULTIPLES,
        "selection": {
            "eligible_models": list(INTERIOR),
            "uses_only_canonical_10bps_pre2026_metrics": True,
            "A_ROBUST_STATIC_BLEND": [
                "pooled_sharpe>A2",
                "pooled_calmar>=A2",
                "rank_ic>A2",
                "fold_sharpe_not_below_A2_count>=2",
                "excluding_2023_delta_sharpe>=0",
                "excluding_2023_delta_return>=0",
                "turnover<=1.10*A2",
                "temporal_and_universe_violations=0",
            ],
            "B_PROMISING_BUT_NOT_ROBUST": "pooled Sharpe, Calmar, and Rank IC improve but one or more robustness gates fail",
            "C_NO_CLEAR_INCREMENTAL_VALUE": "neither robust nor uniformly pooled-improving, without uniform material degradation",
            "D_BLEND_DEGRADES_BASELINE": "every interior candidate has Sharpe<=A2, Calmar<A2, and Rank IC<=A2",
            "selection_order": "highest robustness gate pass count, then lower XGB weight; A-class candidates take priority",
            "cagr_is_not_a_selection_key": True,
            "cost_stress_is_post_selection_and_never_reselects_weight": True,
        },
        "best_fold_contribution_share": "largest positive fold cumulative-return delta divided by sum of positive fold cumulative-return deltas",
        "leave_2023_out": "concatenate authoritative OUTER_2024 and OUTER_2025 paths with fold-boundary resets",
        "prohibitions": [
            "regime_gate", "dynamic_weights", "date_dependent_weights", "feature_engineering",
            "underlying_model_refit", "underlying_parameter_search", "2026_read", "new_algorithm",
        ],
    }


def assert_pre2026(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        dates = pd.to_datetime(frame[column], errors="coerce")
        if dates.dropna().ge(BOUNDARY).any():
            raise RuntimeError(f"POST2025_ROW_READ:{column}")


def load_common_predictions() -> tuple[pd.DataFrame, int, int]:
    columns = [
        "prediction_date", "ticker", "security_id", "13f_vintage", "13f_effective_date",
        "authoritative_13f_universe_count", "eligible_universe_count", "model", "raw_score",
        "cross_sectional_rank", "selected_top20", "realized_forward_target", "target_end_date", "fold_id",
    ]
    predictions = pd.read_parquet(
        R1A_ROOT / "oos_predictions.parquet",
        columns=columns,
        filters=[("model", "in", [A2_MODEL, XGB_MODEL])],
    )
    predictions["prediction_date"] = pd.to_datetime(predictions["prediction_date"])
    predictions["13f_effective_date"] = pd.to_datetime(predictions["13f_effective_date"])
    predictions["target_end_date"] = pd.to_datetime(predictions["target_end_date"])
    assert_pre2026(predictions, ["prediction_date"])
    if predictions.duplicated(["model", "prediction_date", "security_id"]).any():
        raise RuntimeError("DUPLICATE_SECURITY_DATE_MODEL")

    base = predictions[predictions["model"] == A2_MODEL].copy()
    xgb = predictions[predictions["model"] == XGB_MODEL].copy()
    keys = ["prediction_date", "security_id"]
    merged = base.merge(xgb, on=keys, how="outer", suffixes=("_a2", "_xgb"), indicator=True, validate="one_to_one")
    universe_mismatch_count = int((merged["_merge"] != "both").sum())
    if universe_mismatch_count:
        raise RuntimeError("A2_XGB_UNIVERSE_KEY_MISMATCH")
    identity_columns = [
        "ticker", "13f_vintage", "13f_effective_date", "authoritative_13f_universe_count",
        "eligible_universe_count", "realized_forward_target", "target_end_date", "fold_id",
    ]
    for column in identity_columns:
        left = merged[f"{column}_a2"]
        right = merged[f"{column}_xgb"]
        equal = left.eq(right) | (left.isna() & right.isna())
        universe_mismatch_count += int((~equal).sum())
    temporal_violation_count = int(
        (merged["13f_effective_date_a2"] > merged["prediction_date"]).sum()
        + (merged["prediction_date"].dt.year.astype(str).radd("OUTER_") != merged["fold_id_a2"]).sum()
    )
    if universe_mismatch_count or temporal_violation_count:
        raise RuntimeError("PIT_TEMPORAL_OR_UNIVERSE_IDENTITY_FAILURE")
    return merged, temporal_violation_count, universe_mismatch_count


def build_blends(merged: pd.DataFrame, r1a: Any) -> dict[str, pd.DataFrame]:
    hgb_percentile = merged.groupby("prediction_date")["raw_score_a2"].rank(
        method="average", ascending=True, pct=True
    )
    xgb_percentile = merged.groupby("prediction_date")["raw_score_xgb"].rank(
        method="average", ascending=True, pct=True
    )
    common = pd.DataFrame(
        {
            "signal_date": merged["prediction_date"],
            "ticker": merged["ticker_a2"].astype(str),
            "security_id": merged["security_id"],
            "target": merged["realized_forward_target_a2"].astype(float),
            "target_end_date": merged["target_end_date_a2"],
            "fold_id": merged["fold_id_a2"],
            "13f_vintage": merged["13f_vintage_a2"],
            "13f_effective_date": merged["13f_effective_date_a2"],
            "eligible_universe_count": merged["eligible_universe_count_a2"].astype(int),
            "hgb_percentile_rank": hgb_percentile,
            "xgb_percentile_rank": xgb_percentile,
        }
    ).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    blends = {}
    for weight_id, weight in WEIGHTS.items():
        frame = common.copy()
        frame["prediction"] = (1 - weight) * frame["hgb_percentile_rank"] + weight * frame["xgb_percentile_rank"]
        frame["rank"] = r1a.rank_scores(frame, column="prediction", ticker_ascending=True)
        frame["selected_top20"] = frame["rank"] <= 20
        frame["model"] = weight_id
        if not frame.groupby("signal_date")["selected_top20"].sum().eq(20).all():
            raise RuntimeError(f"INCOMPLETE_TOP20:{weight_id}")
        blends[weight_id] = frame

    endpoint_a2 = merged["selected_top20_a2"].to_numpy(bool)
    endpoint_xgb = merged["selected_top20_xgb"].to_numpy(bool)
    original_order = pd.DataFrame({"signal_date": merged["prediction_date"], "ticker": merged["ticker_a2"]}).sort_values(
        ["signal_date", "ticker"], kind="mergesort"
    ).index
    if not np.array_equal(blends["W00"]["selected_top20"].to_numpy(), endpoint_a2[original_order]):
        raise RuntimeError("W00_TOP20_NOT_A2_IDENTITY")
    if not np.array_equal(blends["W100"]["selected_top20"].to_numpy(), endpoint_xgb[original_order]):
        raise RuntimeError("W100_TOP20_NOT_XGB_IDENTITY")
    return blends


def predictive_rows(blends: dict[str, pd.DataFrame], r1a: Any) -> pd.DataFrame:
    rows = []
    for weight_id, frame in blends.items():
        scopes = [("POOLED_OOF", frame)] + [(fold, frame[frame["fold_id"] == fold]) for fold in FOLDS]
        for scope, part in scopes:
            summary = r1a.predictive_summary(part, weight_id, scope)
            rows.append(
                {key: summary[key] for key in [
                    "model", "scope", "observation_count", "date_count", "rank_ic", "median_rank_ic",
                    "pearson_ic", "ic_std", "icir", "ndcg_at_20", "top20_forward_return",
                    "top20_vs_universe_spread",
                ]}
            )
    result = pd.DataFrame(rows)
    frozen = pd.read_csv(R1A_ROOT / "predictive_metrics_by_fold.csv")
    for weight_id, model in (("W00", A2_MODEL), ("W100", XGB_MODEL)):
        actual = result[result["model"] == weight_id].set_index("scope")
        expected = frozen[frozen["model"] == model].set_index("scope")
        for metric in ("rank_ic", "ndcg_at_20", "top20_forward_return", "top20_vs_universe_spread"):
            if not np.allclose(actual.loc[list(actual.index), metric], expected.loc[list(actual.index), metric], atol=1e-12, rtol=0):
                raise RuntimeError(f"ENDPOINT_PREDICTIVE_IDENTITY_FAILURE:{weight_id}:{metric}")
    return result


def portfolio_signals(frame: pd.DataFrame) -> pd.DataFrame:
    signals = frame[["signal_date", "ticker", "rank"]].copy()
    signals["a1_rank"] = signals["rank"]
    signals["a2_rank"] = signals["rank"]
    signals["universe_size"] = signals.groupby("signal_date")["ticker"].transform("size")
    return signals


def persistence(frame: pd.DataFrame) -> float:
    sets = frame[frame["selected_top20"]].groupby("signal_date", sort=True)["ticker"].agg(set)
    if len(sets) < 2:
        return np.nan
    return float(np.mean([len(sets.iloc[index - 1] & sets.iloc[index]) / 20 for index in range(1, len(sets))]))


def economic_row(path: pd.DataFrame, prediction: pd.DataFrame, weight_id: str, scope: str, cost_bps: int, r4: Any) -> dict[str, Any]:
    metrics = r4.portfolio_metrics(path)
    returns = path["net_return"].to_numpy(float)
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=0)) if len(downside) else np.nan
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    return {
        "model": weight_id,
        "weight": WEIGHTS[weight_id],
        "scope": scope,
        "cost_bps": cost_bps,
        "total_return": metrics["cumulative_return"],
        "cagr": metrics["cagr"],
        "annualized_return": metrics["annualized_mean_return"],
        "volatility": metrics["annualized_volatility"],
        "sharpe": metrics["sharpe_rf0"],
        "sortino": float(np.mean(returns) / downside_std * math.sqrt(252)) if downside_std > 0 else np.nan,
        "calmar": metrics["calmar"],
        "max_drawdown": metrics["max_drawdown"],
        "profit_factor": float(gains / losses) if losses else np.nan,
        "turnover": metrics["annualized_turnover"],
        "total_transaction_cost": metrics["total_transaction_cost"],
        "average_holding_persistence": persistence(prediction),
        "rebalance_count": metrics["observation_count"],
    }


def simulate_all(
    blends: dict[str, pd.DataFrame], prices: pd.DataFrame, r4: Any
) -> tuple[pd.DataFrame, pd.DataFrame, dict[tuple[str, str, int], pd.DataFrame]]:
    canonical_rows = []
    cost_rows = []
    paths: dict[tuple[str, str, int], pd.DataFrame] = {}
    for weight_id, frame in blends.items():
        scopes = [("POOLED_OOF", frame)] + [(fold, frame[frame["fold_id"] == fold]) for fold in FOLDS]
        for scope, part in scopes:
            path = r4.simulate_portfolio(
                portfolio_signals(part), prices, weight_id, "rank", 20, CANONICAL_COST_BPS
            )
            paths[(weight_id, scope, CANONICAL_COST_BPS)] = path
            canonical_rows.append(economic_row(path, part, weight_id, scope, CANONICAL_COST_BPS, r4))
    for weight_id in ("W00",) + INTERIOR:
        frame = blends[weight_id]
        for multiple, cost_bps in COST_MULTIPLES.items():
            key = (weight_id, "POOLED_OOF", cost_bps)
            if key not in paths:
                paths[key] = r4.simulate_portfolio(
                    portfolio_signals(frame), prices, weight_id, "rank", 20, cost_bps
                )
            row = economic_row(paths[key], frame, weight_id, "POOLED_OOF", cost_bps, r4)
            row["cost_multiple"] = multiple
            cost_rows.append(row)
    return pd.DataFrame(canonical_rows), pd.DataFrame(cost_rows), paths


def validate_endpoint_paths(paths: dict[tuple[str, str, int], pd.DataFrame]) -> dict[str, Any]:
    frozen = pd.read_parquet(R1A_ROOT / "oof_portfolio_paths.parquet")
    audit = {}
    for weight_id, model in (("W00", A2_MODEL), ("W100", XGB_MODEL)):
        for scope in ("POOLED_OOF",) + FOLDS:
            actual = paths[(weight_id, scope, CANONICAL_COST_BPS)].sort_values("execution_date").reset_index(drop=True)
            expected = frozen[(frozen["model"] == model) & (frozen["scope"] == scope)].sort_values("execution_date").reset_index(drop=True)
            date_identity = actual["execution_date"].equals(expected["execution_date"])
            max_errors = {}
            for column in ("gross_return", "net_return", "turnover", "transaction_cost_amount"):
                max_errors[column] = float(np.max(np.abs(actual[column].to_numpy() - expected[column].to_numpy())))
            passed = date_identity and all(value <= 1e-14 for value in max_errors.values())
            audit[f"{weight_id}:{scope}"] = {
                "date_identity": date_identity,
                "max_abs_errors": max_errors,
                "pass": passed,
            }
            if not passed:
                raise RuntimeError(f"ENDPOINT_ECONOMIC_PATH_IDENTITY_FAILURE:{weight_id}:{scope}")
    return audit


def top20_forensic(blends: dict[str, pd.DataFrame], economics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = blends["W00"]
    base_sets = base[base["selected_top20"]].groupby("signal_date")["ticker"].agg(set)
    target_map = base.set_index(["signal_date", "ticker"])["target"]
    date_rows = []
    for weight_id, frame in blends.items():
        sets = frame[frame["selected_top20"]].groupby("signal_date")["ticker"].agg(set)
        fold_map = frame.groupby("signal_date")["fold_id"].first()
        for date in base_sets.index:
            a2_set = base_sets.loc[date]
            blend_set = sets.loc[date]
            added = blend_set - a2_set
            removed = a2_set - blend_set
            spread = 0.0
            if added and removed:
                added_return = np.mean([target_map.loc[(date, ticker)] for ticker in added])
                removed_return = np.mean([target_map.loc[(date, ticker)] for ticker in removed])
                spread = float(added_return - removed_return)
            date_rows.append(
                {
                    "prediction_date": date,
                    "fold_id": fold_map.loc[date],
                    "model": weight_id,
                    "weight": WEIGHTS[weight_id],
                    "top20_overlap_vs_a2": len(a2_set & blend_set) / 20,
                    "replacement_count": len(added),
                    "replacement_spread": spread,
                }
            )
    by_date = pd.DataFrame(date_rows)
    pooled_econ = economics[economics["scope"] == "POOLED_OOF"].set_index("model")
    rows = []
    for weight_id in WEIGHTS:
        model_dates = by_date[by_date["model"] == weight_id]
        for scope, part in [("POOLED_OOF", model_dates)] + [
            (fold, model_dates[model_dates["fold_id"] == fold]) for fold in FOLDS
        ]:
            rows.append(
                {
                    "model": weight_id,
                    "weight": WEIGHTS[weight_id],
                    "scope": scope,
                    "date_count": len(part),
                    "top20_overlap_vs_a2": part["top20_overlap_vs_a2"].mean(),
                    "replacement_count": part["replacement_count"].mean(),
                    "replacement_spread": part["replacement_spread"].mean(),
                    "pooled_turnover": pooled_econ.at[weight_id, "turnover"],
                    "pooled_turnover_change_vs_a2": pooled_econ.at[weight_id, "turnover"] - pooled_econ.at["W00", "turnover"],
                }
            )
    return pd.DataFrame(rows), by_date


def leave_2023_out(
    paths: dict[tuple[str, str, int], pd.DataFrame], r4: Any
) -> pd.DataFrame:
    rows = []
    for weight_id in WEIGHTS:
        combined = pd.concat(
            [paths[(weight_id, fold, CANONICAL_COST_BPS)] for fold in ("OUTER_2024", "OUTER_2025")],
            ignore_index=True,
        )
        metrics = r4.portfolio_metrics(combined)
        rows.append(
            {
                "model": weight_id,
                "weight": WEIGHTS[weight_id],
                "excluding_fold": "OUTER_2023",
                "boundary_policy": "CONCATENATED_AUTHORITATIVE_FOLD_PATHS_WITH_FOLD_BOUNDARY_RESETS",
                "cumulative_return": metrics["cumulative_return"],
                "sharpe": metrics["sharpe_rf0"],
                "calmar": metrics["calmar"],
                "max_drawdown": metrics["max_drawdown"],
            }
        )
    result = pd.DataFrame(rows)
    base = result[result["model"] == "W00"].iloc[0]
    for metric in ("cumulative_return", "sharpe", "calmar", "max_drawdown"):
        result[f"delta_{metric}_vs_a2"] = result[metric] - base[metric]
    return result


def candidate_evaluation(
    economics: pd.DataFrame, predictive: pd.DataFrame, leaveout: pd.DataFrame
) -> tuple[pd.DataFrame, str, str]:
    pooled_e = economics[economics["scope"] == "POOLED_OOF"].set_index("model")
    fold_e = economics[economics["scope"].isin(FOLDS)].set_index(["model", "scope"])
    pooled_p = predictive[predictive["scope"] == "POOLED_OOF"].set_index("model")
    leave = leaveout.set_index("model")
    rows = []
    for weight_id in INTERIOR:
        fold_deltas = [
            fold_e.at[(weight_id, fold), "total_return"] - fold_e.at[("W00", fold), "total_return"]
            for fold in FOLDS
        ]
        positive = [value for value in fold_deltas if value > 0]
        fold_sharpe_count = sum(
            fold_e.at[(weight_id, fold), "sharpe"] >= fold_e.at[("W00", fold), "sharpe"]
            for fold in FOLDS
        )
        gates = {
            "pooled_sharpe": pooled_e.at[weight_id, "sharpe"] > pooled_e.at["W00", "sharpe"],
            "pooled_calmar": pooled_e.at[weight_id, "calmar"] >= pooled_e.at["W00", "calmar"],
            "rank_ic": pooled_p.at[weight_id, "rank_ic"] > pooled_p.at["W00", "rank_ic"],
            "fold_sharpe_2of3": fold_sharpe_count >= 2,
            "excluding_2023_sharpe": leave.at[weight_id, "delta_sharpe_vs_a2"] >= 0,
            "excluding_2023_return": leave.at[weight_id, "delta_cumulative_return_vs_a2"] >= 0,
            "turnover": pooled_e.at[weight_id, "turnover"] <= 1.10 * pooled_e.at["W00", "turnover"],
        }
        all_robust = all(gates.values())
        pooled_uniform = gates["pooled_sharpe"] and gates["pooled_calmar"] and gates["rank_ic"]
        classification = (
            "A_ROBUST_STATIC_BLEND" if all_robust else
            "B_PROMISING_BUT_NOT_ROBUST" if pooled_uniform else
            "C_NO_CLEAR_INCREMENTAL_VALUE"
        )
        rows.append(
            {
                "model": weight_id,
                "weight": WEIGHTS[weight_id],
                "classification": classification,
                "robustness_gate_pass_count": sum(gates.values()),
                **{f"gate_{key}": value for key, value in gates.items()},
                "fold_sharpe_not_below_a2_count": fold_sharpe_count,
                "best_fold_contribution_share": max(positive) / sum(positive) if positive else np.nan,
                "pooled_delta_sharpe_vs_a2": pooled_e.at[weight_id, "sharpe"] - pooled_e.at["W00", "sharpe"],
                "pooled_delta_calmar_vs_a2": pooled_e.at[weight_id, "calmar"] - pooled_e.at["W00", "calmar"],
                "pooled_delta_rank_ic_vs_a2": pooled_p.at[weight_id, "rank_ic"] - pooled_p.at["W00", "rank_ic"],
                "pooled_delta_max_drawdown_vs_a2": pooled_e.at[weight_id, "max_drawdown"] - pooled_e.at["W00", "max_drawdown"],
                "turnover_ratio_vs_a2": pooled_e.at[weight_id, "turnover"] / pooled_e.at["W00", "turnover"],
                "excluding_2023_delta_sharpe": leave.at[weight_id, "delta_sharpe_vs_a2"],
                "excluding_2023_delta_return": leave.at[weight_id, "delta_cumulative_return_vs_a2"],
            }
        )
    evaluation = pd.DataFrame(rows)
    a_candidates = evaluation[evaluation["classification"] == "A_ROBUST_STATIC_BLEND"]
    if not a_candidates.empty:
        classification = "A_ROBUST_STATIC_BLEND"
        eligible = a_candidates
    else:
        b_candidates = evaluation[evaluation["classification"] == "B_PROMISING_BUT_NOT_ROBUST"]
        if not b_candidates.empty:
            classification = "B_PROMISING_BUT_NOT_ROBUST"
            eligible = b_candidates
        elif (
            (evaluation["pooled_delta_sharpe_vs_a2"] <= 0).all()
            and (evaluation["pooled_delta_calmar_vs_a2"] < 0).all()
            and (evaluation["pooled_delta_rank_ic_vs_a2"] <= 0).all()
        ):
            classification = "D_BLEND_DEGRADES_BASELINE"
            eligible = evaluation
        else:
            classification = "C_NO_CLEAR_INCREMENTAL_VALUE"
            eligible = evaluation
    selected = eligible.sort_values(
        ["robustness_gate_pass_count", "weight"], ascending=[False, True], kind="mergesort"
    ).iloc[0]["model"]
    return evaluation, classification, str(selected)


def add_cost_deltas(costs: pd.DataFrame) -> pd.DataFrame:
    result = costs.copy()
    for cost_bps in sorted(result["cost_bps"].unique()):
        base = result[(result["model"] == "W00") & (result["cost_bps"] == cost_bps)].iloc[0]
        mask = result["cost_bps"] == cost_bps
        for metric in ("total_return", "sharpe", "calmar", "max_drawdown", "turnover", "total_transaction_cost"):
            result.loc[mask, f"delta_{metric}_vs_a2"] = result.loc[mask, metric] - base[metric]
    statuses = {}
    for weight_id in INTERIOR:
        part = result[result["model"] == weight_id]
        statuses[weight_id] = bool(
            (part["delta_sharpe_vs_a2"] >= 0).all() and (part["delta_total_return_vs_a2"] >= 0).all()
        )
    result["cost_robust_all_1x_2x_3x"] = result["model"].map(statuses).fillna(True)
    return result


def main() -> None:
    if OUT_ROOT.exists():
        raise RuntimeError("R1D_OUTPUT_EXISTS_PRESERVE_FROZEN_EVIDENCE")
    if WORK_ROOT.exists():
        if any(WORK_ROOT.iterdir()):
            raise RuntimeError("R1D_WORKING_EVIDENCE_EXISTS_PRESERVE")
    else:
        WORK_ROOT.mkdir(parents=False)

    r1a, r4, input_audit = preflight()
    contract = static_contract()
    write_json(WORK_ROOT / "static_blend_contract.json", contract)
    witness = {
        "contract_sha256": sha256(WORK_ROOT / "static_blend_contract.json"),
        "runner_sha256": sha256(SCRIPT_PATH),
        "frozen_before_outcome_read": True,
        "candidate_count": 3,
        "selection_count": 1,
    }
    write_json(WORK_ROOT / "preregistration_witness.json", witness)

    merged, temporal_violations, universe_mismatches = load_common_predictions()
    blends = build_blends(merged, r1a)
    predictive = predictive_rows(blends, r1a)
    prices = r1a.load_prices()
    assert_pre2026(prices, ["trade_date"])
    price_audit = {
        "loader": "FROZEN_R1A_LOAD_PRICES",
        "price_rows_read": len(prices),
        "price_start": prices["trade_date"].min(),
        "price_end": prices["trade_date"].max(),
        "ticker_count": prices["ticker"].nunique(),
        "post2025_price_rows": int((prices["trade_date"] >= BOUNDARY).sum()),
        "coverage_freeze_sha256": EXPECTED_COVERAGE_FREEZE_SHA256,
    }
    economics, costs, paths = simulate_all(blends, prices, r4)
    path_identity = validate_endpoint_paths(paths)
    top20, top20_by_date = top20_forensic(blends, economics)
    leaveout = leave_2023_out(paths, r4)
    evaluation, classification, selected = candidate_evaluation(economics, predictive, leaveout)
    costs = add_cost_deltas(costs)

    pooled = economics[economics["scope"] == "POOLED_OOF"].copy()
    by_fold = economics[economics["scope"].isin(FOLDS)].copy()
    pooled.to_csv(WORK_ROOT / "blend_metrics_pooled.csv", index=False)
    by_fold.to_csv(WORK_ROOT / "blend_metrics_by_fold.csv", index=False)
    predictive.to_csv(WORK_ROOT / "blend_predictive_metrics.csv", index=False)
    top20.to_csv(WORK_ROOT / "blend_top20_overlap.csv", index=False)
    top20_by_date.to_csv(WORK_ROOT / "blend_top20_overlap_by_date.csv", index=False)
    leaveout.to_csv(WORK_ROOT / "blend_leave_2023_out.csv", index=False)
    costs.to_csv(WORK_ROOT / "blend_cost_sensitivity.csv", index=False)
    evaluation.to_csv(WORK_ROOT / "blend_candidate_evaluation.csv", index=False)
    write_json(WORK_ROOT / "endpoint_path_identity_audit.json", path_identity)
    write_json(WORK_ROOT / "safe_read_audit.json", input_audit)
    write_json(WORK_ROOT / "price_read_audit.json", price_audit)

    pooled_i = pooled.set_index("model")
    leave_i = leaveout.set_index("model")
    top_i = top20[top20["scope"] == "POOLED_OOF"].set_index("model")
    eval_i = evaluation.set_index("model")
    status = {
        "A2_ALGORITHM_BENCHMARK_R1D_STATUS": "PASS_PRE2026_STATIC_RANK_BLEND_COMPLETE",
        "STATIC_BLEND_CLASSIFICATION": classification,
        "PRE2026_BLEND_CANDIDATE_COUNT": 3,
        "PRE2026_BLEND_SELECTION_COUNT": 1,
        "BEST_PRE2026_STATIC_WEIGHT": selected,
        "W25_DELTA_SHARPE_VS_A2": eval_i.at["W25", "pooled_delta_sharpe_vs_a2"],
        "W50_DELTA_SHARPE_VS_A2": eval_i.at["W50", "pooled_delta_sharpe_vs_a2"],
        "W75_DELTA_SHARPE_VS_A2": eval_i.at["W75", "pooled_delta_sharpe_vs_a2"],
        "BEST_BLEND_EXCLUDING_2023_DELTA_SHARPE": leave_i.at[selected, "delta_sharpe_vs_a2"],
        "BEST_BLEND_EXCLUDING_2023_DELTA_RETURN": leave_i.at[selected, "delta_cumulative_return_vs_a2"],
        "BEST_BLEND_TOP20_OVERLAP_VS_A2": top_i.at[selected, "top20_overlap_vs_a2"],
        "BEST_BLEND_TURNOVER_RATIO_VS_A2": pooled_i.at[selected, "turnover"] / pooled_i.at["W00", "turnover"],
        "BEST_BLEND_BEST_FOLD_CONTRIBUTION_SHARE": eval_i.at[selected, "best_fold_contribution_share"],
        "BEST_BLEND_COST_ROBUST_1X_2X_3X": bool(costs[costs["model"] == selected]["cost_robust_all_1x_2x_3x"].all()),
        "TEMPORAL_VIOLATION_COUNT": temporal_violations,
        "UNIVERSE_MISMATCH_COUNT": universe_mismatches,
        "MODEL_FIT_COUNT": 0,
        "UNDERLYING_MODEL_PARAMETER_SEARCH_COUNT": 0,
        "REGIME_GATE_COUNT": 0,
        "DYNAMIC_WEIGHT_COUNT": 0,
        "2026_ARTIFACT_READ_COUNT": 0,
        "2026_TRAINING_ROWS": 0,
        "2026_UNDERLYING_MODEL_PARAMETER_SEARCH_COUNT": 0,
        "2026_BLEND_SELECTION_COUNT": 0,
        "2026_MODEL_SELECTION_COUNT": 0,
        "2026_HOLDOUT_STATUS": "SEALED_NOT_USED",
        "A2_AUTHORITATIVE_BASELINE_STATUS": "UNCHANGED",
        "BLEND_DEPLOYMENT_STATUS": "NOT_DEPLOYED_REVIEW_REQUIRED",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_R1D",
    }
    if temporal_violations or universe_mismatches:
        raise RuntimeError("FINAL_TEMPORAL_OR_UNIVERSE_FAILURE")
    write_json(WORK_ROOT / "status.json", status)

    w25_gain = (
        predictive[(predictive["model"] == "W25") & (predictive["scope"] == "POOLED_OOF")]["rank_ic"].iloc[0]
        - predictive[(predictive["model"] == "W00") & (predictive["scope"] == "POOLED_OOF")]["rank_ic"].iloc[0]
    )
    full_gain = (
        predictive[(predictive["model"] == "W100") & (predictive["scope"] == "POOLED_OOF")]["rank_ic"].iloc[0]
        - predictive[(predictive["model"] == "W00") & (predictive["scope"] == "POOLED_OOF")]["rank_ic"].iloc[0]
    )
    report = [
        f"# {RUN_ID}", "",
        "This run compares three preregistered interior static rank-space blends. It does not refit either underlying model and does not use 2026.", "",
        f"- Classification: `{classification}`",
        f"- Selected pre-2026 review candidate: `{selected}` (not deployed)",
        f"- W25 share of W100 pooled Rank-IC gain: `{w25_gain / full_gain if full_gain else np.nan:.6f}`",
        f"- Selected Top20 overlap versus A2: `{top_i.at[selected, 'top20_overlap_vs_a2']:.6f}`",
        f"- Selected turnover ratio versus A2: `{status['BEST_BLEND_TURNOVER_RATIO_VS_A2']:.6f}`", "",
        "## Governance", "",
        "Selection uses only the three fixed interior weights at canonical 10 bps. Cost stress is evaluated after selection and never changes the weight. CAGR is not a selection key. No regime gate, dynamic weight, feature engineering, new algorithm, underlying fit, or 2026 read occurred.", "",
        "## Candidate gate summary", "",
        "| Weight | Class | Gates passed | Delta Sharpe | Ex-2023 delta Sharpe | Ex-2023 delta return | Turnover ratio |", "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in evaluation.itertuples(index=False):
        report.append(
            f"| {row.model} | {row.classification} | {row.robustness_gate_pass_count}/7 | "
            f"{row.pooled_delta_sharpe_vs_a2:.6f} | {row.excluding_2023_delta_sharpe:.6f} | "
            f"{row.excluding_2023_delta_return:.6f} | {row.turnover_ratio_vs_a2:.6f} |"
        )
    (WORK_ROOT / "blend_selection_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    source_hashes = {row["path"]: row["actual_sha256"] for row in input_audit}
    source_hashes[str(SCRIPT_PATH)] = sha256(SCRIPT_PATH)
    write_json(WORK_ROOT / "source_hash_manifest.json", source_hashes)
    artifacts = []
    for path in sorted(WORK_ROOT.iterdir(), key=lambda item: item.name):
        if path.name in {"manifest.json", "sha256_manifest.txt"}:
            continue
        artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "run_id": RUN_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "STATIC_PRE2026_BLEND_RESEARCH_NOT_DEPLOYED",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "source_hashes": source_hashes,
        "status": status,
    }
    write_json(WORK_ROOT / "manifest.json", manifest)
    lines = [
        f"{sha256(path)}  {path.name}"
        for path in sorted(WORK_ROOT.iterdir(), key=lambda item: item.name)
        if path.name != "sha256_manifest.txt"
    ]
    (WORK_ROOT / "sha256_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    WORK_ROOT.rename(OUT_ROOT)
    for key, value in status.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
