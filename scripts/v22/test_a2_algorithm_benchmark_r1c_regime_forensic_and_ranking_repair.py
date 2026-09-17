from __future__ import annotations

import ast
import runpy
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name(
    "a2_algorithm_benchmark_r1c_regime_forensic_and_ranking_repair.py"
)
MODULE = runpy.run_path(str(SCRIPT))


def test_runner_has_no_model_fit_call_and_keeps_outputs_external() -> None:
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
    assert not str(MODULE["OUT_ROOT"]).startswith(r"D:\us-tech-quant\results")


def test_ranking_contract_is_symmetric_and_absolute() -> None:
    raw, ranks, composites, contract, sensitivity, status = MODULE[
        "build_symmetric_ranking"
    ]()
    assert set(raw["model"]) == set(MODULE["COMPETITIVE_MODELS"])
    assert len(contract) == 11
    assert np.isclose(contract["balanced_weight"].sum(), 1.0)
    assert not any("beat" in name.lower() for name in raw.columns)
    assert not any("baseline" in name.lower() for name in raw.columns)
    assert ranks.filter(like="_rank").notna().all().all()
    assert composites.filter(like="_composite").notna().all().all()
    assert set(sensitivity["scenario"]) == set(MODULE["WEIGHT_SCENARIOS"])
    assert status.startswith("MODEL_RANKING_")


def test_market_state_never_uses_return_after_prediction_date() -> None:
    dates = pd.date_range("2025-01-01", periods=65, freq="D")
    base = pd.DataFrame(
        {
            "execution_date": np.repeat(dates, 2),
            "model": ["A", "B"] * len(dates),
            "benchmark_return": np.repeat(np.linspace(-0.01, 0.01, len(dates)), 2),
        }
    )
    prediction_date = pd.Series([dates[59]])
    before = MODULE["market_state_by_prediction_date"](base, prediction_date)
    future = pd.DataFrame(
        {
            "execution_date": [dates[64], dates[64]],
            "model": ["A", "B"],
            "benchmark_return": [9.0, 9.0],
        }
    )
    changed = pd.concat([base[base["execution_date"] < dates[64]], future], ignore_index=True)
    after = MODULE["market_state_by_prediction_date"](changed, prediction_date)
    pd.testing.assert_frame_equal(before, after)
    assert before.loc[0, "market_information_max_date"] <= prediction_date.iloc[0]


def test_market_state_uses_canonical_pooled_path_at_fold_boundary() -> None:
    frame = pd.DataFrame(
        {
            "execution_date": pd.to_datetime(["2025-01-03"] * 4),
            "model": ["A", "B", "A", "B"],
            "benchmark_return": [0.0, 0.0, -0.01, -0.01],
            "scope": ["OUTER_2025", "OUTER_2025", "POOLED_OOF", "POOLED_OOF"],
        }
    )
    result = MODULE["market_state_by_prediction_date"](
        frame, pd.Series(pd.to_datetime(["2025-01-03"]))
    )
    assert result.loc[0, "market_drawdown_state"] == 0.0


def test_fixed_terciles_are_predefined_rank_groups() -> None:
    series = pd.Series(range(1, 10), dtype=float)
    labels, cuts = MODULE["assign_fixed_terciles"](series)
    assert labels.tolist() == ["LOW"] * 3 + ["MID"] * 3 + ["HIGH"] * 3
    assert cuts == {"q33": 3.6666666666666665, "q67": 6.333333333333333}


def test_conditional_output_includes_pooled_and_each_fold_without_refitting() -> None:
    rows = []
    for year in (2023, 2024, 2025):
        for index in range(6):
            rows.append(
                {
                    "fold_id": f"OUTER_{year}",
                    "market_realized_vol_20d": year + index / 10,
                    "xgb_minus_a2_net_return": index / 1000,
                    "xgb_replacement_spread": index / 100,
                    "top20_overlap": 0.75,
                }
            )
    frame = pd.DataFrame(rows)
    function = MODULE["relative_pnl_by_tercile"]
    original = function.__globals__["TERCILE_VARIABLES"]
    function.__globals__["TERCILE_VARIABLES"] = ["market_realized_vol_20d"]
    try:
        table, _ = function(frame)
    finally:
        function.__globals__["TERCILE_VARIABLES"] = original
    assert set(table["scope"]) == {
        "POOLED_PRE2026",
        "OUTER_2023",
        "OUTER_2024",
        "OUTER_2025",
    }


def test_pre2026_guard_rejects_2026_dates() -> None:
    ok = pd.DataFrame({"date": ["2025-12-31"]})
    MODULE["assert_pre2026_dates"](ok, ["date"])
    bad = pd.DataFrame({"date": ["2026-01-01"]})
    try:
        MODULE["assert_pre2026_dates"](bad, ["date"])
    except RuntimeError as error:
        assert "2026 date encountered" in str(error)
    else:
        raise AssertionError("2026 input was not rejected")


def test_regime_classification_never_emits_a_deployable_rule() -> None:
    allowed = {
        "R1_NO_CLEAR_REGIME_PATTERN",
        "R2_DESCRIPTIVE_REGIME_DEPENDENCE",
        "R3_STRONG_PRE2026_REGIME_DEPENDENCE_BUT_NOT_DEPLOYABLE",
    }
    source = SCRIPT.read_text(encoding="utf-8")
    assert "regime_gate_created\": False" in source
    assert "dynamic weight" not in source.lower()
    assert all(value in source for value in allowed)
