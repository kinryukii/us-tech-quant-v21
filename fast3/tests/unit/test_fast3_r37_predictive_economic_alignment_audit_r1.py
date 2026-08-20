from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r37_predictive_economic_alignment_audit_r1.py"
SPEC = importlib.util.spec_from_file_location("r37", SCRIPT)
R = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(R)


def test_frozen_authoritative_lineage_hashes():
    assert R.sha256(R.PHASE2_DECISION) == R.EXPECTED["PHASE2_DECISION"]
    assert R.sha256(R.PHASE2_LINEAGE) == R.EXPECTED["PHASE2_LINEAGE"]
    assert R.sha256(R.R28_LEDGER) == R.EXPECTED["R28_LEDGER"]
    assert R.sha256(R.R36_LEDGER) == R.EXPECTED["R36_LEDGER"]


def test_real_exact_join_is_1197_unique_and_schema_is_unambiguous():
    frame, audit = R.verify_and_join()
    assert audit["ALIGNMENT_JOIN_MATCHED_COUNT"] == 1197
    assert audit["ALIGNMENT_JOIN_RATIO"] == 1.0
    assert frame.candidate_id.is_unique and frame.columns.is_unique
    assert set(frame.direction) == {"UP", "DOWN"}


def test_preregistration_freezes_five_direction_specific_buckets_and_zero_models():
    contract = R.preregistration("fixed")
    assert contract["SCORE_BUCKET_COUNT"] == 5
    assert "direction-specific" in contract["SCORE_BUCKET_METHOD"]
    assert contract["MODEL_FIT_ALLOWED"] is contract["MODEL_PREDICT_ALLOWED"] is False
    assert contract["MAX_NEW_FEATURE_COUNT"] == contract["MAX_NEW_MODEL_COUNT"] == 0


def test_quintiles_are_direction_specific_and_exact():
    frame = pd.DataFrame({"direction": ["UP"] * 10 + ["DOWN"] * 10,
                          "score": list(range(10)) + list(range(100, 110))})
    out = R.assign_quintiles(frame)
    for _, part in out.groupby("direction"):
        assert part.score_quintile.value_counts().sort_index().to_dict() == {q: 2 for q in R.QUINTILES}


def test_payoff_metrics_are_economic_not_predictive_accuracy():
    metrics = R.payoff_metrics(pd.Series([.02, .01, -.01, -.03]))
    assert metrics["count"] == 4 and metrics["win_rate_net20"] == .5
    assert np.isclose(metrics["mean_net20"], -.0025)
    assert np.isclose(metrics["profit_factor_net20"], .75)
    assert metrics["large_loss_2pct_rate"] == .25


def synthetic_tables(predictive=(True, True), economic=(False, False), target_aligned=True):
    target_rows = []
    for target in (0, 1):
        good = target == 1 and target_aligned
        target_rows.append({"direction": "ALL", "target_first": target, "mean_net20": .01 if good else -.01,
                            "win_rate_net20": .7 if good else .3, "profit_factor_net20": 2 if good else .5})
    qrows, crows, top_rows = [], [], []
    for i, direction in enumerate(R.HEADS):
        for n, q in enumerate(R.QUINTILES, 1):
            qrows.append({"direction": direction, "quintile": q,
                          "target_event_rate": n / 10 if predictive[i] else .3,
                          "mean_net20": n / 100 if economic[i] else -n / 100})
        crows.append({"direction": direction, "score_vs_target_spearman": .2 if predictive[i] else -.1,
                      "score_vs_net20_spearman": .2 if economic[i] else -.1})
        top_rows += [{"direction": direction, "score_group": "Q5", "mean_net20": .02 if economic[i] else -.02,
                      "profit_factor_net20": 1.2 if economic[i] else .7},
                     {"direction": direction, "score_group": "REST", "mean_net20": 0, "profit_factor_net20": 1.0}]
    return map(pd.DataFrame, (target_rows, qrows, crows, top_rows))


def test_classification_b_is_predictive_but_not_economic():
    flags, classification = R.alignment_flags(*synthetic_tables())
    assert classification == "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED"
    assert flags["UP_PREDICTIVE_ALIGNMENT"] and not flags["UP_ECONOMIC_ALIGNMENT"]


def test_classification_a_requires_both_directions_economic():
    _, classification = R.alignment_flags(*synthetic_tables(economic=(True, True)))
    assert classification == "A_PREDICTIVE_AND_ECONOMIC_ALIGNMENT_CONFIRMED"


def test_partial_direction_is_c_not_forced_combined():
    _, classification = R.alignment_flags(*synthetic_tables(predictive=(True, False), economic=(True, False)))
    assert classification == "C_WEAK_PARTIAL_ECONOMIC_ALIGNMENT"


def test_no_training_rescoring_search_or_final_prospective_paths():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("sklearn", ".fit(", ".predict(", "GridSearchCV", "RandomizedSearchCV", "FINAL_HOLDOUT", "prospective_ledger"):
        assert forbidden not in source
    assert '"MODEL_FIT_COUNT": 0' in source and '"MODEL_PREDICT_CALL_COUNT": 0' in source
    assert '"R28_REFIT_COUNT": 0' in source and '"R28_THRESHOLD_CHANGE_COUNT": 0' in source


def test_external_storage_and_allowed_classification_enum():
    assert R.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert R.CLASSIFICATIONS == {
        "A_PREDICTIVE_AND_ECONOMIC_ALIGNMENT_CONFIRMED", "B_PREDICTIVE_TARGET_REAL_BUT_ECONOMICALLY_MISALIGNED",
        "C_WEAK_PARTIAL_ECONOMIC_ALIGNMENT", "D_NO_MEANINGFUL_PREDICTIVE_ECONOMIC_RELATION", "E_INVALID_ALIGNMENT_IDENTITY"}
