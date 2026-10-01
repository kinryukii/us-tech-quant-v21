"""Commit every candidate and evaluator before any new-batch 2026 outcome read."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    dest = ROOT / "freeze_manifest.json"
    if dest.exists() or (ROOT / "test2026" / "summary.csv").exists():
        raise RuntimeError("BATCH_ALREADY_FROZEN_OR_SCORED")
    supervised = json.loads((ROOT / "supervised_manifest.json").read_text(encoding="utf-8"))
    rl = json.loads((ROOT / "rl_artifacts" / "manifest.json").read_text(encoding="utf-8"))
    risk = json.loads((ROOT / "risk_artifacts" / "diagnostics.json").read_text(encoding="utf-8"))
    table = pd.read_csv(ROOT / "opt_artifacts" / "pre2026_summary.csv")
    expected = {"RAW", "HGB_DIAG_5", "HGB_FACTOR_5", "HGB_FACTOR_20",
                "HGB_Q10_FACTOR_5", "MLP_FACTOR_5"}
    if set(table.candidate) != expected or set(table.year) != {2024, 2025}:
        raise RuntimeError("INCOMPLETE_INTERNAL_VALIDATION")
    if supervised["fit_count"] != 27 or rl["status"] != "PRE2026_FROZEN":
        raise RuntimeError("INCOMPLETE_MODEL_COVERAGE")
    if len(risk["fits"]) != 3:
        raise RuntimeError("INCOMPLETE_RISK_FITS")
    r24 = table.loc[table.year.eq(2024)].set_index("candidate")
    r25 = table.loc[table.year.eq(2025)].set_index("candidate")
    qualified = [x for x in expected - {"RAW"} if
                 r24.loc[x, "end_nav"] > r24.loc["RAW", "end_nav"] and
                 r25.loc[x, "end_nav"] > r25.loc["RAW", "end_nav"] and
                 r24.loc[x, "max_drawdown"] >= r24.loc["RAW", "max_drawdown"] - .05]
    primary = max(qualified, key=lambda x: r25.loc[x, "end_nav"]) if qualified else "RAW"
    representative = max(expected - {"RAW"}, key=lambda x: r25.loc[x, "end_nav"])
    rl_tests = {f"RL_SEED_{s}": int(s) for s in rl["seeds"]}
    if rl.get("ensemble_validation"):
        rl_tests["RL_ENSEMBLE"] = None
    files = ["PLAN.md", "BUDGET_DEVIATIONS.md", "prepare.py", "fit_supervised.py", "risk_aux.py",
             "optimize_route.py", "rl_policy.py", "batch2026.py", "trade_detail.py",
             "pre2026_panel.parquet", "pre2026_manifest.json", "pre2026_oof.parquet",
             "supervised_trials.csv", "supervised_manifest.json", "opt_artifacts/pre2026_summary.csv",
             "opt_artifacts/specs.json", "risk_artifacts/diagnostics.json",
             "risk_artifacts/final_aux_revision.json", "risk_artifacts/trials.csv",
             "rl_artifacts/manifest.json", "rl_artifacts/trials.csv",
             "rl_artifacts/normalization.npz",
             "rl_artifacts/trials_uncapped_pretest.csv",
             "rl_artifacts/trials_label_truncated_pretest.csv",
             "rl_artifacts/validation_ensemble_daily.parquet",
             "rl_artifacts/validation_ensemble_trades.parquet",
             "rl_artifacts/validation_ensemble_targets.parquet"]
    files.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "models").glob("*.joblib")))
    files.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "risk_artifacts").glob("*.joblib")))
    files.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "rl_artifacts").glob("checkpoint_*.pt")))
    record = {"status": "PRE2026_ALL_CANDIDATES_FROZEN",
              "test_asof_utc": "2026-09-25T15:34:48Z",
              "test_last_completed_session_et": "2026-09-24",
              "train_cutoff_exclusive": "2026-01-01",
              "primary_pre2026_selection": primary,
              "supervised_representative": representative,
              "qualification_rule": "2025 net NAV beats Raw; 2024 same positive sign; 2024 max drawdown no worse by >5pp",
              "qualified_candidates": sorted(qualified),
              "rl_test_policies": rl_tests,
              "source_2026_exposure": "Earlier batch exposed some 2026 results; new batch never uses them to fit/select",
              "budget_deviation": "RL two superseded implementation pretests add 48 episodes per seed to the final 24; see BUDGET_DEVIATIONS.md",
              "artifacts_sha256": {name: sha(ROOT / name) for name in sorted(set(files))}}
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"FROZEN primary={primary} representative={representative} candidates={len(expected)} rl={list(rl_tests)}")


if __name__ == "__main__":
    main()
