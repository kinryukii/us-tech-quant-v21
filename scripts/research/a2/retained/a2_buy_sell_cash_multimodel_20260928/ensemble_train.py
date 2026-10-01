"""Fixed convex ensemble meta-learning from pre-2026 out-of-sample base ledgers."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
OUT = HERE / "ensemble_artifacts"
BASE = HERE / "evaluation_2025/cost_10"
METHODS = ["joint_ridge", "joint_elastic_net", "joint_logistic", "joint_hgb",
           "joint_quantile_risk", "joint_mlp"]
STAGES = {"validation": "2025-07-01", "final": "2026-01-01"}
RISK_PENALTY = 5.
EQUAL_WEIGHT_PENALTY = .001
LOWER, UPPER = .05, .35


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "META_DESIGN_CONTRACT.json"
    design = {"methods": METHODS, "stages_cutoff_exclusive": STAGES,
              "train_start_inclusive": "2025-01-01", "base_stage": "validation",
              "base_training_labels_before": "2025-01-01", "base_cost_bps": 10,
              "objective": "mean_net @ w - 5 * w.T @ covariance @ w - .001 * sum((w - 1/6)**2)",
              "covariance": "sample daily covariance, ddof=1, exact complete-case OOS net returns",
              "weight_sum": 1., "weight_bounds": [LOWER, UPPER],
              "solver": "SLSQP", "solver_maxiter": 500, "solver_ftol": 1e-12,
              "initial_weights": [1 / len(METHODS)] * len(METHODS),
              "fits": 2, "hyperparameter_searches": 0,
              "unknown_handling": "exclude entire date if any base return is missing/nonfinite or uncertified; no fill",
              "validation_use": "H1 weights only valid for subsequent H2 evaluation; H1 replay is training-window diagnostic",
              "final_use": "2025 weights frozen before 2026 inference; no 2026 fit or model selection",
              "target_limitation": "learns a convex combination of standalone portfolio returns; combined target execution is nonlinear and separately replayed",
              "data_limitation": "2025 previously observed; prospective blind-test status is not restored",
              "producer_sha256": sha(Path(__file__))}
    if path.exists():
        prior = read(path)
        assert {k: v for k, v in prior.items() if k != "created_utc"} == design, "META_DESIGN_CHANGED"
        return prior
    design["created_utc"] = datetime.now(timezone.utc).isoformat()
    write(path, design)
    return design


def complete_case_returns(frames, cutoff):
    returns, validity, counts = {}, {}, {}
    for name in METHODS:
        frame = frames[name].copy().sort_values("date")
        frame = frame.loc[frame.date.ge("2025-01-01") & frame.date.lt(cutoff)]
        assert not frame.date.duplicated().any() and len(frame) > 0
        assert frame.date.dt.year.eq(2025).all()
        nav = frame.certified_nav.to_numpy(float)
        value = frame.net_return.to_numpy(float)
        certified = frame.valuation_status.eq("certified").to_numpy() & np.isfinite(nav) & (nav > 0)
        previous = np.r_[False, certified[:-1]]
        expected = frame.certified_nav.pct_change(fill_method=None).to_numpy(float)
        finite_pair = np.isfinite(value) & np.isfinite(expected)
        np.testing.assert_allclose(value[finite_pair], expected[finite_pair], rtol=1e-9, atol=1e-12)
        valid = certified & previous & np.isfinite(value)
        returns[name] = pd.Series(value, index=frame.date, name=name)
        validity[name] = pd.Series(valid, index=frame.date, name=name)
        counts[name] = {"rows": len(frame), "uncertified_nav_rows": int((~certified).sum()),
                        "nonfinite_return_rows": int((~np.isfinite(value)).sum()),
                        "invalid_return_rows": int((~valid).sum())}
    panel = pd.concat(returns.values(), axis=1).sort_index()
    valid = pd.concat(validity.values(), axis=1).reindex(panel.index).fillna(False).all(axis=1)
    good = valid & np.isfinite(panel.to_numpy(float)).all(axis=1)
    selected = panel.loc[good, METHODS].copy()
    if len(selected) < 2:
        raise ValueError("INSUFFICIENT_CERTIFIED_META_RETURNS")
    exclusions = pd.DataFrame({"date": panel.index, "included": good.to_numpy()})
    report = {"union_dates": len(panel), "included_dates": len(selected),
              "excluded_entire_dates": int((~good).sum()), "per_method": counts,
              "first_return": str(selected.index.min().date()), "last_return": str(selected.index.max().date())}
    return selected, exclusions, report


def solve_weights(values):
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(METHODS) or len(x) < 2 or not np.isfinite(x).all():
        raise ValueError("INVALID_META_RETURN_MATRIX")
    mean = x.mean(axis=0)
    covariance = np.cov(x, rowvar=False, ddof=1)
    equal = np.full(len(METHODS), 1 / len(METHODS))
    def objective(w):
        return float(-mean @ w + RISK_PENALTY * w @ covariance @ w
                     + EQUAL_WEIGHT_PENALTY * np.square(w - equal).sum())
    def gradient(w):
        return -mean + 2 * RISK_PENALTY * covariance @ w + 2 * EQUAL_WEIGHT_PENALTY * (w - equal)
    solution = minimize(objective, equal, jac=gradient, method="SLSQP",
                        bounds=[(LOWER, UPPER)] * len(METHODS),
                        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.,
                                      "jac": lambda w: np.ones(len(METHODS))}],
                        options={"maxiter": 500, "ftol": 1e-12})
    w = solution.x
    feasible = np.isfinite(w).all() and abs(w.sum() - 1) < 1e-8 and w.min() >= LOWER - 1e-8 and w.max() <= UPPER + 1e-8
    if not solution.success or not feasible:
        raise RuntimeError(f"META_OPTIMIZER_FAILED: {solution.message}")
    assert objective(w) <= objective(equal) + 1e-10
    # Strict concavity comes from the fixed L2 term, so this is a unique convex minimizer.
    free = (w > LOWER + 1e-7) & (w < UPPER - 1e-7)
    g = gradient(w)
    multiplier = float(np.mean(g[free])) if free.any() else float(np.median(g))
    kkt = np.where(free, np.abs(g - multiplier),
                   np.where(w <= LOWER + 1e-7, np.maximum(0, multiplier - g), np.maximum(0, g - multiplier)))
    report = {"status": "PASS", "iterations": int(solution.nit), "message": str(solution.message),
              "objective_utility": -objective(w), "equal_weight_utility": -objective(equal),
              "maximum_kkt_error": float(kkt.max()), "mean_daily_net_returns": mean.tolist(),
              "return_covariance": covariance.tolist()}
    return w, report


def bind_sources():
    binding_path = BASE / "FROZEN_BEFORE_REPLAY.json"
    binding = read(binding_path)
    assert binding["stage"] == "validation" and binding["year"] == 2025 and binding["cost_bps"] == 10
    assert set(METHODS).issubset(binding["roster"])
    linear_path = HERE / "linear_artifacts/FIT_RECEIPT.json"
    neural_path = HERE / "neural_artifacts/TRAIN_RECEIPT.json"
    linear, neural = read(linear_path), read(neural_path)
    assert linear["status"] == neural["status"] == "PASS"
    assert linear["stages"]["validation"]["cutoff_exclusive"] == "2025-01-01"
    assert linear["stages"]["validation"]["selected_label_end_max"] < "2025-01-01"
    direct = [x for x in neural["artifacts"] if x["stage"] == "validation" and x["method"] == "direct"]
    assert len(direct) == 1 and direct[0]["reward_end_before"] == "2025-01-01"
    for path in [linear_path, neural_path]:
        assert binding["source_sha256"][str(path.resolve())] == sha(path)
    sources = {str(p.resolve()): sha(p) for p in [binding_path, linear_path, neural_path]}
    for name in METHODS:
        path = BASE / name / "PATH_COMPLETE.json"
        receipt = read(path)
        assert receipt["audit"]["status"] == "PASS"
        assert receipt["metrics"]["policy"] == name and receipt["metrics"]["year"] == 2025
        assert receipt["metrics"]["cost_bps"] == 10
        daily = BASE / name / "daily.parquet"
        assert sha(daily) == receipt["ledger_sha256"]["daily"]
        sources[str(path.resolve())] = sha(path)
        sources[str(daily.resolve())] = sha(daily)
    return sources


def train():
    design = prepare()
    sources = bind_sources()
    if (OUT / "PRE_FIT_CONTRACT.json").exists():
        raise RuntimeError("META_EXISTING_FIT_PRESERVED")
    panels, exclusions, selection = {}, {}, {}
    for stage, cutoff in STAGES.items():
        frames = {name: pd.read_parquet(BASE / name / "daily.parquet",
                  columns=["date", "certified_nav", "valuation_status", "net_return"],
                  filters=[("date", ">=", pd.Timestamp("2025-01-01")), ("date", "<", pd.Timestamp(cutoff))])
                  for name in METHODS}
        panels[stage], exclusions[stage], selection[stage] = complete_case_returns(frames, cutoff)
    contract = {"created_utc": datetime.now(timezone.utc).isoformat(), "design_sha256": sha(OUT / "META_DESIGN_CONTRACT.json"),
                "source_sha256": sources, "producer_sha256": sha(Path(__file__)),
                "selection": selection, "planned_fit_calls": 2, "fit_2026_rows": 0,
                "base_returns_out_of_sample": True, "base_fit_end_exclusive": "2025-01-01"}
    assert design["producer_sha256"] == contract["producer_sha256"]
    write(OUT / "PRE_FIT_CONTRACT.json", contract)
    started = time.monotonic()
    fits = []
    for stage in STAGES:
        panel = panels[stage]
        panel.to_parquet(OUT / f"{stage}_training_returns.parquet", index=True)
        exclusions[stage].to_csv(OUT / f"{stage}_date_inclusion.csv", index=False)
        weights, diagnostics = solve_weights(panel.to_numpy(float))
        artifact = {"stage": stage, "methods": METHODS, "weights": dict(zip(METHODS, map(float, weights))),
                    "training_cutoff_exclusive": STAGES[stage], "base_stage": "validation",
                    "selection": selection[stage], "solver": diagnostics,
                    "producer_sha256": contract["producer_sha256"], "meta_design_sha256": contract["design_sha256"]}
        path = OUT / f"{stage}_weights.json"
        write(path, artifact)
        fits.append({"stage": stage, "cutoff_exclusive": STAGES[stage], "artifact": str(path),
                     "artifact_sha256": sha(path), "training_returns_sha256": sha(OUT / f"{stage}_training_returns.parquet"),
                     "date_inclusion_sha256": sha(OUT / f"{stage}_date_inclusion.csv"),
                     "rows": len(panel), "maximum_return_date": selection[stage]["last_return"],
                     "optimizer_iterations": diagnostics["iterations"], "maximum_kkt_error": diagnostics["maximum_kkt_error"]})
        print(json.dumps({"stage": stage, "status": "PASS", "rows": len(panel), "weights": artifact["weights"]}), flush=True)
    assert all(sha(path) == expected for path, expected in sources.items()), "META_SOURCE_CHANGED"
    write(OUT / "TRAIN_RECEIPT.json", {"status": "PASS", "fit_calls": 2, "fits": fits,
          "fit_seconds": time.monotonic() - started, "pre_fit_contract_sha256": sha(OUT / "PRE_FIT_CONTRACT.json"),
          "source_hashes_unchanged": True, "fit_2026_rows": 0, "2026_outcomes_read": False,
          "base_stage": "validation", "combination_target": "standalone portfolio-return proxy; separately executed ensemble differs"})


def load_weights(stage="final"):
    if stage not in STAGES:
        raise ValueError(f"UNKNOWN_META_STAGE: {stage}")
    receipt = read(OUT / "TRAIN_RECEIPT.json")
    assert receipt["status"] == "PASS" and receipt["fit_calls"] == 2
    fit = next(x for x in receipt["fits"] if x["stage"] == stage)
    path = OUT / f"{stage}_weights.json"
    if sha(path) != fit["artifact_sha256"]:
        raise ValueError("META_ARTIFACT_HASH_MISMATCH")
    artifact = read(path)
    assert artifact["methods"] == METHODS and artifact["training_cutoff_exclusive"] == STAGES[stage]
    weights = {name: float(artifact["weights"][name]) for name in METHODS}
    w = np.array(list(weights.values()))
    assert abs(w.sum() - 1) < 1e-8 and w.min() >= LOWER - 1e-8 and w.max() <= UPPER + 1e-8
    return weights


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
        print("META_DESIGN_LOCKED; no return data read and no fit performed")
    else:
        train()
