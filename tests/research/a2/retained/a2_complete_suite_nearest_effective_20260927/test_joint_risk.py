"""Independent synthetic review; no market outcomes, model fits or root edits."""
from __future__ import annotations
import ast
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import joint_risk
import run_suite
from joint_linear_tree import ACTIONS, FEATURES, allocate_joint_scores

ROOT = Path(__file__).resolve().parent


def synthetic_risk_case(seed=9, factor=False):
    rng = np.random.default_rng(seed)
    count = 27
    names = [f"T{i:02}" for i in range(count)]
    day = pd.DataFrame(np.zeros((count, len(FEATURES))), columns=FEATURES)
    day["signal_date"] = pd.Timestamp("2024-07-01")
    day["ticker"] = names
    day["new_buy_eligible"] = True
    day.loc[0, "new_buy_eligible"] = False
    old = {names[0]: .05, names[1]: .075}
    q = rng.normal(0, .00008, (count, 5))
    q[0, 4] = 999.  # Must never increase a former-quarter holding.
    allowed = day.new_buy_eligible.to_numpy(bool)[:, None] | (ACTIONS[None, :] <= np.array([old.get(t, 0) for t in names])[:, None]+1e-10)
    initial, _ = allocate_joint_scores(q, names, allowed=allowed)
    loadings = rng.normal(0, .003, (count, 3))
    covariance = loadings @ loadings.T + np.eye(count) * .004

    class Base:
        models = {"hgb": object()}
        def __call__(self, *args, **kwargs):
            return initial

    class Risk:
        lookup = {name: i for i, name in enumerate(names)}
        def covariance_for(self, provided, factor=False):
            assert provided == names
            return covariance * (1.25 if factor else 1)

    with patch.object(joint_risk, "load_policy", return_value=Base()) as model_loader, \
         patch.object(joint_risk, "FrozenRisk", Risk), \
         patch.object(joint_risk, "predict_values", return_value=q.reshape(-1)):
        policy = joint_risk.JointRiskPolicy(factor=factor)
        weights = policy(day, old, .875)
        assert model_loader.call_args.args == ("hgb",)
    w = np.array([weights.get(t, 0) for t in names])
    c = covariance * (1.25 if factor else 1)
    final_value = float(q[np.arange(count), np.rint(w/.025).astype(int)].sum() - 5*w@c@w)
    diagnostic = policy.last_diagnostic
    assert abs(final_value-diagnostic["final_utility"]) < 1e-10
    assert abs(float(w@c@w)-diagnostic["predicted_daily_variance"]) < 1e-12
    assert len(weights) <= 20 and w.sum() <= .95000001
    assert weights.get(names[0], 0) <= old[names[0]]+1e-10
    assert all(any(abs(v-a)<1e-10 for a in ACTIONS) for v in weights.values())
    assert diagnostic["final_utility"] >= diagnostic["initial_utility"]-1e-10
    return {"factor": factor, "stock_count": len(weights), "gross": float(w.sum()),
            "utility_improvement": diagnostic["final_utility"]-diagnostic["initial_utility"],
            "variance_is_one_day": True, "former_quarter_add_blocked": True}


def stage_tests():
    rows = []
    for stage in ("validation", "final"):
        with patch.object(run_suite, "load_policy", return_value=object()) as linear, \
             patch.object(run_suite, "NeuralAdapter", return_value=object()) as neural:
            for name in run_suite.NAMES:
                run_suite.Stateful(name, stage)
                if name in ("joint_mlp", "joint_rl_ensemble", "joint_rl_zero_control"):
                    assert neural.call_args.kwargs["stage"] == stage
                elif name != "hgb_return_baseline":
                    assert linear.call_args.kwargs["stage"] == stage
        rows.append({"stage": stage, "all_joint_model_adapters_forward_requested_stage": True})
    assert "joint_hgb_lw" not in run_suite.NAMES and "joint_hgb_pca" not in run_suite.NAMES
    assert {"joint_hgb_lw", "joint_hgb_pca"}.issubset(run_suite.TEST_NAMES)
    source = (ROOT / "run_suite.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    branch = next(n for n in main.body if isinstance(n, ast.If) and ast.unparse(n.test) == "year == 2026")
    final_branch = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    validation_branch = ast.unparse(ast.Module(body=branch.orelse, type_ignores=[]))
    assert "stage = 'final'" in final_branch
    assert "stage = 'validation'" in validation_branch
    assert "pre2026_oof.parquet" in validation_branch and "score.signal_date.dt.year.eq(2025)" in validation_branch
    assert "predict_panel(" not in validation_branch
    return rows


def main():
    cases = [synthetic_risk_case(seed, factor) for seed in (9, 51) for factor in (False, True)]
    assert any(row["utility_improvement"] > 1e-10 for row in cases)
    stages = stage_tests()
    receipt = {"status": "PASS", "synthetic_only": True, "market_test_rows_read": 0, "fit_calls": 0,
        "risk_cases": cases, "stage_tests": stages,
        "risk_scope": "Only test roster; risk estimator and HGB are frozen through 2025. Adding it to 2025 requires fold-specific risk and model parameters.",
        "utility_units": "sum of one-session learned net contribution minus 5 times one-day portfolio covariance quadratic; no extra multiplication of learned Q by target weights",
        "solver_scope": "four passes of coordinate ascent, feasibility and non-decreasing utility verified; global optimum not claimed"}
    (ROOT / "audit/JOINT_RISK_STAGE_REVIEW.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
