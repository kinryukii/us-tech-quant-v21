"""Focused tests of joint allocation, frozen inference, costs and date purge."""
import itertools
import json
import numpy as np
import pandas as pd
import joint_linear_tree as joint


def main():
    rng = np.random.default_rng(8)
    scores = rng.normal(size=(4, 5))
    _, actions = joint.allocate_joint_scores(scores, list("ABCD"), max_names=2, max_units=5)
    exhaustive = max(sum(scores[i, x]-scores[i, 0] for i, x in enumerate(c))
                     for c in itertools.product(range(5), repeat=4)
                     if sum(x > 0 for x in c) <= 2 and sum(c) <= 5)
    assert abs(sum(scores[i, x]-scores[i, 0] for i, x in enumerate(actions))-exhaustive) < 1e-10
    scores = np.zeros((30, 5))
    scores[-1, 4] = 99
    weights, _ = joint.allocate_joint_scores(scores, [str(x) for x in range(30)])
    assert "29" in weights
    mask = np.ones(scores.shape, bool)
    mask[-1, 1:] = False
    weights, _ = joint.allocate_joint_scores(scores, [str(x) for x in range(30)], allowed=mask)
    assert "29" not in weights
    receipt = json.loads((joint.OUT / "FIT_RECEIPT.json").read_text(encoding="utf-8"))
    assert receipt["fit_calls"] == 14 and receipt["test_rows_read"] == 0
    assert joint.COST == .001
    for fit in receipt["fits"]:
        cutoff = "2025-01-01" if fit["stage"] == "validation" else "2026-01-01"
        assert pd.Timestamp(fit["train_label_end_max"]) < pd.Timestamp(cutoff)
    frame = pd.read_parquet(joint.HERE / "data/pre2026_joint.parquet")
    day = frame.loc[frame.signal_date.eq(pd.Timestamp("2025-12-29"))]
    assert len(day) >= 20
    checks = []
    for name in (*joint.NAMES, "quantile_risk"):
        policy = joint.load_policy(name)
        result = policy(day, {}, 1.)
        assert len(result) <= 20 and sum(result.values()) <= .95 + 1e-12
        assert all(any(abs(w-a)<1e-10 for a in joint.ACTIONS) for w in result.values())
        changed = day.copy()
        changed["y_next_open"] = 999
        changed["target"] = -999
        changed["next_open"] = 1e9
        assert policy(changed, {}, 1.) == result
        # With no existing holding, an ineligible pool may never be bought.
        forbidden = day.copy()
        forbidden["new_buy_eligible"] = False
        assert policy(forbidden, {}, 1.) == {}
        checks.append({"name": name, "stock_count": len(result), "gross": sum(result.values()),
                       "outcome_perturbation_invariant": True, "new_buy_gate": True})
    output = {"status": "PASS", "test_data_read": 0, "fit_calls": 0, "sample_date": "2025-12-29",
              "sample_is_training_period_smoke_only": True, "exact_knapsack_vs_bruteforce": True,
              "all_candidates_considered": True, "single_side_cost": .001, "label_maturity_purge": True, "policies": checks}
    joint.write(joint.OUT / "TECHNICAL_VERIFICATION.json", output)
    print(json.dumps(output))


if __name__ == "__main__":
    main()
