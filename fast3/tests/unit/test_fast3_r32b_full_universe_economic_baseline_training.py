from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r32b_full_universe_economic_baseline_training.py"
spec = importlib.util.spec_from_file_location("r32b", RUNNER)
r32b = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r32b)


def sample() -> pd.DataFrame:
    x = pd.DataFrame({
        "candidate_id": [f"c{i}" for i in range(20)],
        "decision_timestamp_utc": pd.date_range("2024-01-02T14:00:00Z", periods=20, freq="h"),
        "pred_t1": np.arange(20, dtype=float), "pred_t2": np.arange(20, dtype=float),
        "T1_POSITIVE_NET20": [0, 1] * 10, "T2_ROBUST_NET20": np.linspace(-.02, .02, 20),
        "raw_net20": np.linspace(-.02, .02, 20), "t1_baseline_constant": .5,
        "t2_baseline_mean": 0.0, "t2_baseline_median": 0.0,
    })
    x["trading_date"] = x.decision_timestamp_utc.dt.tz_convert(r32b.NY).dt.date.astype(str)
    return x


def test_r32a_authority_and_exact_29_features() -> None:
    summary, manifest, features = r32b.guard_authority()
    assert summary["FULL_VALID_LABEL_COUNT"] == r32b.FULL_VALID == 1_456_595
    assert manifest["candidate_universe_sha256"] == r32b.UNIVERSE_SHA
    assert manifest["FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER"] == 0
    assert len(features) == 29 and tuple(features) == tuple(r32b.read_json(r32b.FEATURE_MANIFEST)["arms"]["ARM_ALL"])
    assert not any("DOLLAR_VOLUME" in name or "ILLIQUIDITY" in name or "TURNOVER_PROFILE" in name for name in features)


def test_top_k_and_deciles_are_deterministic() -> None:
    x = sample(); first = r32b.ranking(x, "pred_t1", "T1"); second = r32b.ranking(x.sample(frac=1, random_state=4), "pred_t1", "T1")
    pd.testing.assert_frame_equal(first, second)
    assert first.loc[first.bucket_percent.eq(20), "row_count"].item() == 4
    dec = r32b.deciles(x, "pred_t1", "T1")
    assert dec.decile.tolist() == list(range(1, 11)) and dec.row_count.eq(2).all()


def test_date_balance_and_cluster_bootstrap_are_fixed_and_deterministic() -> None:
    x = sample(); ids = r32b.cohort_ids(x)
    table, metrics = r32b.date_balanced(x, ids)
    assert len(table) == x.trading_date.nunique() and np.isfinite(metrics[("T1", 20)])
    one, ci1 = r32b.cluster_bootstrap(x, ids); two, ci2 = r32b.cluster_bootstrap(x, ids)
    pd.testing.assert_frame_equal(one, two); assert ci1 == ci2
    assert len(one) == 2 * 2 * 500


def test_weighted_bootstrap_exactly_matches_materialized_date_blocks() -> None:
    assert r32b.weighted_bootstrap_equivalence_test()
    assert r32b.BOOTSTRAP_REPLICATES == 500 and r32b.BOOTSTRAP_SEED == 3201
    source = inspect.getsource(r32b.cluster_bootstrap)
    assert "np.bincount" in source and "weighted_topk_from_sorted" in source
    assert "pd.concat" not in source and "fit(" not in source and "predict(" not in source


def test_split_purge_and_overlap_isolation() -> None:
    x = pd.DataFrame({"decision_timestamp_utc": pd.to_datetime(["2020-01-01","2020-01-02","2021-01-01","2021-01-02"],utc=True),
                      "label_information_end_utc": pd.to_datetime(["2020-01-01","2020-12-31","2021-01-01","2021-01-03"],utc=True)})
    train, valid, audit = r32b.fold_masks(x, ("TEST","2021-01-01","2021-12-31 23:59:59"))
    assert valid.sum() == 2 and train.sum() == 1 and audit["overlap_count"] == 0
    assert audit["train_label_information_end_max"] < audit["information_cutoff"]


def test_no_selection_feature_sampling_search_or_repo_results() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "sample(" not in source and "GridSearch" not in source and "RandomizedSearch" not in source and "Optuna" not in source
    build = inspect.getsource(r32b.construct_dataset)
    assert "label_valid" in build and "dropna" not in build and "old_r28_probability" in build
    tree = ast.parse(source)
    fit_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fit"]
    predict_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"predict","predict_proba"}]
    assert len(fit_calls) == 2 and len(predict_calls) == 2
    assert r32b.DATA_ROOT == Path(r"D:\us-tech-quant-data")
    assert r32b.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert not any(RUNNER.parent.glob("*r32b*helper*.py"))
