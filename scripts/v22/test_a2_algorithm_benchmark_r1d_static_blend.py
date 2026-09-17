from __future__ import annotations

import ast
import runpy
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name("a2_algorithm_benchmark_r1d_static_blend.py")
MODULE = runpy.run_path(str(SCRIPT))


class RankHelper:
    @staticmethod
    def rank_scores(frame: pd.DataFrame, column: str, ticker_ascending: bool) -> pd.Series:
        result = pd.Series(index=frame.index, dtype="int32")
        for _, day in frame.groupby("signal_date", sort=True):
            ordered = day.sort_values(
                [column, "ticker"], ascending=[False, ticker_ascending], kind="mergesort"
            )
            result.loc[ordered.index] = np.arange(1, len(ordered) + 1)
        return result.astype("int32")


def test_contract_has_only_three_preregistered_interior_weights() -> None:
    contract = MODULE["static_contract"]()
    assert contract["weights"] == {
        "W00": 0.0,
        "W25": 0.25,
        "W50": 0.5,
        "W75": 0.75,
        "W100": 1.0,
    }
    assert contract["interior_candidates"] == ["W25", "W50", "W75"]
    assert contract["pre2026_blend_candidate_count"] == 3
    assert contract["pre2026_blend_selection_count"] == 1
    assert contract["rank_space"]["raw_score_blending_allowed"] is False
    assert contract["selection"]["cagr_is_not_a_selection_key"] is True


def test_runner_has_no_fit_call_and_routes_results_external() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    fit_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fit"
    ]
    assert fit_calls == []
    assert str(MODULE["OUT_ROOT"]).startswith(r"D:\us-tech-quant-results")


def test_rank_space_blend_reproduces_both_frozen_endpoints() -> None:
    rows = []
    for date in pd.to_datetime(["2025-01-02", "2025-01-03"]):
        for rank in range(1, 26):
            rows.append(
                {
                    "prediction_date": date,
                    "security_id": f"S{rank:02d}",
                    "ticker_a2": f"T{rank:02d}",
                    "realized_forward_target_a2": rank / 100,
                    "target_end_date_a2": date + pd.Timedelta(days=20),
                    "fold_id_a2": "OUTER_2025",
                    "13f_vintage_a2": "2024Q3",
                    "13f_effective_date_a2": date - pd.Timedelta(days=10),
                    "eligible_universe_count_a2": 25,
                    "cross_sectional_rank_a2": rank,
                    "cross_sectional_rank_xgb": 26 - rank,
                    "raw_score_a2": float(26 - rank),
                    "raw_score_xgb": float(rank),
                    "selected_top20_a2": rank <= 20,
                    "selected_top20_xgb": 26 - rank <= 20,
                }
            )
    merged = pd.DataFrame(rows)
    blends = MODULE["build_blends"](merged, RankHelper)
    assert blends["W00"]["selected_top20"].tolist() == merged["selected_top20_a2"].tolist()
    assert blends["W100"]["selected_top20"].tolist() == merged["selected_top20_xgb"].tolist()
    expected = 0.75 * blends["W00"]["hgb_percentile_rank"] + 0.25 * blends["W00"]["xgb_percentile_rank"]
    np.testing.assert_allclose(blends["W25"]["prediction"], expected)


def test_selection_prefers_lower_xgb_weight_when_all_are_robust() -> None:
    models = list(MODULE["WEIGHTS"])
    pooled_rows = []
    fold_rows = []
    for model in models:
        interior = model in MODULE["INTERIOR"]
        pooled_rows.append(
            {
                "model": model,
                "scope": "POOLED_OOF",
                "sharpe": 1.1 if interior else 1.0,
                "calmar": 1.1 if interior else 1.0,
                "turnover": 51.0 if interior else 50.0,
                "max_drawdown": -0.2,
            }
        )
        for fold in MODULE["FOLDS"]:
            fold_rows.append(
                {
                    "model": model,
                    "scope": fold,
                    "sharpe": 1.1 if interior else 1.0,
                    "total_return": 0.11 if interior else 0.10,
                }
            )
    economics = pd.DataFrame(pooled_rows + fold_rows)
    predictive = pd.DataFrame(
        {
            "model": models,
            "scope": "POOLED_OOF",
            "rank_ic": [0.01, 0.02, 0.02, 0.02, 0.03],
        }
    )
    leaveout = pd.DataFrame(
        {
            "model": models,
            "delta_sharpe_vs_a2": [0.0, 0.1, 0.1, 0.1, 0.2],
            "delta_cumulative_return_vs_a2": [0.0, 0.1, 0.1, 0.1, 0.2],
        }
    )
    evaluation, classification, selected = MODULE["candidate_evaluation"](
        economics, predictive, leaveout
    )
    assert classification == "A_ROBUST_STATIC_BLEND"
    assert selected == "W25"
    assert evaluation["robustness_gate_pass_count"].eq(7).all()


def test_2026_rows_are_rejected() -> None:
    MODULE["assert_pre2026"](pd.DataFrame({"date": ["2025-12-31"]}), ["date"])
    try:
        MODULE["assert_pre2026"](pd.DataFrame({"date": ["2026-01-01"]}), ["date"])
    except RuntimeError as error:
        assert "POST2025_ROW_READ" in str(error)
    else:
        raise AssertionError("2026 row was accepted")
