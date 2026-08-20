import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(r"D:\us-tech-quant\fast3\scripts\run\fast3_overnight_factor_lab_r1.py")
SPEC = importlib.util.spec_from_file_location("fast3_overnight_factor_lab_r1", SOURCE)
M = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def test_authoritative_hashes_and_exact_frozen_universe():
    prereg, universe = M.verify_contracts()
    registry = M.registry_from_universe(universe)
    assert M.sha256(M.PREREG) == M.PREREG_SHA
    assert M.sha256(M.UNIVERSE) == M.UNIVERSE_SHA
    assert len(registry) == len({row.name for row in registry}) == 72
    assert prereg["max_combination_order"] == 2
    assert prereg["model"]["parameter_search"] is False


def test_formula_contracts_are_deterministic_and_directional():
    close = np.arange(1.0, 31.0)
    rsi = M.rolling_rsi_wilder(close)
    assert np.isnan(rsi[:14]).all()
    assert np.allclose(rsi[14:], 100.0)
    packed = M.td_counts(close)
    assert M.unpack_td(packed[-1], 1) == 9
    assert M.unpack_td(packed[-1], -1) == 0
    high, low = close + 1, close - 1
    k1, d1, j1 = M.kdj_continuous(close, high, low)
    k2, d2, j2 = M.kdj_continuous(close, high, low)
    assert np.allclose(k1, k2, equal_nan=True)
    assert np.allclose(d1, d2, equal_nan=True)
    assert np.allclose(j1, j2, equal_nan=True)


def test_stable_quintiles_and_ordering_contract():
    frame = pd.DataFrame({
        "candidate_id": [f"c{i}" for i in range(10)],
        "decision_timestamp_utc": pd.date_range("2024-01-01", periods=10, tz="UTC"),
        "predicted_y_econ": np.zeros(10),
    })
    q1 = M.stable_quintiles(frame)
    q2 = M.stable_quintiles(frame.sample(frac=1, random_state=9))
    assert q1.sort_index().tolist() == q2.sort_index().tolist()
    assert q1.value_counts().to_dict() == {q: 2 for q in M.QUINTILES}
    assert M.ordering([1, 2, 3, 4, 5]) == "MONOTONIC_POSITIVE"
    assert M.ordering([5, 4, 3, 2, 1]) == "MONOTONIC_NEGATIVE"


def test_pair_ids_and_pair_universe_are_stable_and_order_two():
    _, universe = M.verify_contracts()
    registry = M.registry_from_universe(universe)[:4]
    specs1 = M.build_specs(registry, "pairs")
    specs2 = M.build_specs(registry, "pairs")
    assert specs1 == specs2
    assert all(len(row[2]) == 2 for row in specs1)
    assert len({row[0] for row in specs1}) == len(specs1)
    assert all(M.spec_stem(row[0]) == M.spec_stem(row[0]) for row in specs1)


def test_relationship_thresholds_are_frozen():
    a = {"DELTA_SPEARMAN": .02, "DELTA_Q5_Q1": .0005}
    b = {"DELTA_SPEARMAN": .01, "DELTA_Q5_Q1": .0004}
    pair = {"DELTA_SPEARMAN": .031, "DELTA_Q5_Q1": .00076}
    label, ds, dq = M.relationship_class(pair, a, b)
    assert label == "SYNERGISTIC"
    assert ds >= .01 and dq >= .00025


def test_resampling_batch_is_reproducible_and_paired():
    n = 60
    timestamp = pd.date_range("2021-01-01", periods=n, freq="12h", tz="UTC")
    base = pd.DataFrame({"candidate_id": [f"x{i}" for i in range(n)], "decision_timestamp_utc": timestamp,
                         "validation_slice": "OOF_2021", "realized_y_econ": np.sin(np.arange(n)),
                         "predicted_y_econ": np.linspace(-1, 1, n)})
    candidate = base.copy(); candidate["predicted_y_econ"] = candidate.realized_y_econ + .1
    ds1, dq1 = M.bootstrap_batch("SINGLE|UP|f", 3, candidate, base)
    ds2, dq2 = M.bootstrap_batch("SINGLE|UP|f", 3, candidate, base)
    assert len(ds1) == M.BATCH_SIZE == 250
    assert np.array_equal(ds1, ds2) and np.array_equal(dq1, dq2)


def test_oof_and_storage_identities():
    _, oof, path_oof = M.load_base_frame()
    assert len(oof) == len(path_oof) == 998
    assert set(oof.validation_slice) == set(M.VALIDATION_FOLDS)
    assert str(M.SCRATCH).startswith(r"D:\us-tech-quant-results\scratch")
    assert str(M.FROZEN).startswith(r"D:\us-tech-quant-results\frozen")
    assert M.REPO not in M.SCRATCH.parents


def test_wrapper_is_thin_and_forbids_research_mutation_commands():
    wrapper = Path(r"D:\us-tech-quant\scripts\fast3\agent\run_fast3_overnight_factor_lab_r1.ps1").read_text(encoding="utf-8")
    assert "--verify-only" in wrapper and "--execute-all" in wrapper
    for forbidden in ("git add -A", "git add .", "git clean", "git reset", "git stash"):
        assert forbidden not in wrapper


def test_markdown_fallback_has_no_optional_tabulate_dependency():
    table = pd.DataFrame({"direction": ["UP"], "features": ["x|y"], "OOF_SPEARMAN": [.125]})
    rendered = M.top_table_markdown(table)
    assert "| direction |" in rendered
    assert "x\\|y" in rendered
    assert "0.125" in rendered
