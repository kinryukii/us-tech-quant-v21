from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import abcde_a2_r3_frozen_ranking_objective_challenger as r3


def _metric_bundle(ic: float, top20: float, spread: float) -> dict:
    delta = {
        "mean_rank_ic": ic,
        "median_rank_ic": ic,
        "positive_ic_day_fraction": float(ic > 0),
        "top5_mean_target": top20,
        "top10_mean_target": top20,
        "top20_mean_target": top20,
        "top_quintile_mean_target": top20,
        "top_bottom_spread": spread,
    }
    return {"lambda_minus_hgb": delta, "models": {}}


def _gate_metrics(ic: float, top20: float, spread: float) -> dict:
    return {
        "2023": _metric_bundle(ic, top20, spread),
        "2024": _metric_bundle(ic, top20, spread),
        "2025": _metric_bundle(ic, top20, spread),
        "POOLED_PRE2026": _metric_bundle(ic, top20, spread),
    }


def test_delta_contract_is_immutable_and_frozen_before_outcome_read():
    witness = json.loads(r3.FREEZE_WITNESS_PATH.read_text(encoding="utf-8"))
    assert witness["status"] == "PASS_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ"
    assert witness["challenger_row_level_outcome_read_count_before_freeze"] == 0
    assert r3.sha256_file(r3.DELTA_CONTRACT_PATH) == r3.EXPECTED_DELTA_CONTRACT_SHA256
    assert r3.freeze_delta_contract()["delta_contract_sha256"] == r3.EXPECTED_DELTA_CONTRACT_SHA256


def test_only_frozen_lambdarank_configuration_is_present():
    contract = r3.delta_preregistration()
    challenger = contract["challenger"]
    config = challenger["constructor_config"]
    assert challenger["model_family"] == "LGBMRanker"
    assert challenger["hyperparameter_search_trial_count"] == 0
    assert challenger["new_model_family_count"] == 1
    assert config["objective"] == "lambdarank"
    assert config["deterministic"] is True
    assert config["force_col_wise"] is True
    assert config["label_gain"] == list(range(20))
    assert config["lambdarank_truncation_level"] == 20


def test_inherited_r1_r2_and_incumbent_artifacts_are_exact():
    _, _, r1_summary, r2_summary, oof, audit = r3.validate_inherited_contracts()
    assert r1_summary["ABCDE_A2_R1_STATUS"] == "PASS"
    assert r2_summary["ABCDE_A2_R2_CLASSIFICATION"] == "M1_STRONG_MECHANISTIC_SUPPORT"
    assert all(audit["checks"].values())
    assert len(oof) == 210445
    assert (oof.signal_date < pd.Timestamp("2026-01-01")).all()


def test_relevance_is_within_date_average_rank_linear_bins():
    frame = pd.DataFrame({
        "signal_date": [pd.Timestamp("2024-01-02")] * 21,
        "target": [0.0, 1.0, 1.0] + list(map(float, range(3, 21))),
    })
    labels = r3.relevance_labels(frame)
    assert labels.min() == 0
    assert labels.max() == 19
    assert labels[1] == labels[2]
    assert labels[-1] == 19


def test_group_row_sum_and_minimum_are_enforced():
    frame = pd.DataFrame({
        "signal_date": [pd.Timestamp("2023-01-03")] * 3 + [pd.Timestamp("2023-01-04")] * 2,
        "target": np.arange(5, dtype=float),
    })
    groups = r3.ranking_groups(frame)
    assert groups.tolist() == [3, 2]
    assert int(groups.sum()) == len(frame)


def test_frozen_gate_produces_a_b_c_and_fail_closed():
    assert r3.classify_challenger(_gate_metrics(0.01, 0.01, 0.0), True)[0] == "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE"
    mixed = _gate_metrics(0.01, 0.01, 0.0)
    mixed["2025"] = _metric_bundle(-0.01, 0.01, 0.0)
    assert r3.classify_challenger(mixed, True)[0] == "B_MIXED_OR_UNSTABLE_RANKING_OBJECTIVE_EDGE"
    assert r3.classify_challenger(_gate_metrics(-0.01, -0.01, -0.01), True)[0] == "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE"
    assert r3.classify_challenger(_gate_metrics(0.01, 0.01, 0.01), False)[0] == "FAIL_CLOSED"


def test_moving_block_bootstrap_is_deterministic():
    pieces = []
    for year in (2023, 2024, 2025):
        pieces.append(pd.DataFrame({
            "signal_date": pd.bdate_range(f"{year}-01-03", periods=30),
            "scope": str(year),
            "delta_ic": np.linspace(-0.02, 0.03, 30),
            "delta_top20": np.linspace(-0.01, 0.02, 30),
        }))
    daily = pd.concat(pieces, ignore_index=True)
    first = r3.circular_block_bootstrap(daily)
    second = r3.circular_block_bootstrap(daily)
    assert first == second
    assert first["2023"]["delta_ic"]["observation_count"] == 30


def test_top20_entry_requires_five_prior_clear_eligible_days():
    dates = pd.bdate_range("2024-01-02", periods=8)
    oof = pd.DataFrame({
        "signal_date": dates,
        "ticker": "AAA",
        "split": "CONFIRMATION",
        "rank": [30, 30, 30, 30, 30, 20, 10, 30],
    })
    events = r3.build_top20_entries(oof, "LAMBDARANK", "rank")
    assert len(events) == 1
    assert events.iloc[0].signal_date == dates[5]


def test_first_legal_business_candidate_is_strictly_after_freeze():
    sunday = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    assert r3._next_business_date_after_freeze(sunday) == "2026-08-17"
    monday = datetime(2026, 8, 17, 16, tzinfo=timezone.utc)
    assert r3._next_business_date_after_freeze(monday) == "2026-08-18"


def test_completed_outputs_have_no_2026_and_reproduce_if_present():
    if not r3.SUMMARY_PATH.is_file():
        return
    summary = json.loads(r3.SUMMARY_PATH.read_text(encoding="utf-8"))
    if summary.get("ABCDE_A2_R3_STATUS") != "PASS":
        return
    assert summary["POST2025_TARGET_READ_COUNT"] == 0
    assert summary["POST2025_OUTCOME_READ_COUNT"] == 0
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    assert summary["INCUMBENT_CHALLENGER_DAILY_UNIVERSE_IDENTITY_STATUS"] == "PASS"
    assert summary["GROUP_ROW_SUM_STATUS"] == "PASS"
    oof = pq.read_table(r3.OOF_PATH).to_pandas()
    assert (pd.to_datetime(oof.signal_date) < pd.Timestamp("2026-01-01")).all()
    assert not oof.duplicated(["signal_date", "ticker"]).any()
    if summary["R3_CLASSIFICATION"] == "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE":
        assert r3.FROZEN_MODEL_PATH.is_file()
        assert r3.PROSPECTIVE_ACTIVATION_PATH.is_file()
    else:
        assert summary["ACTIVATE_PROSPECTIVE_SHADOW"] is False


def test_production_and_post2025_prohibitions_are_frozen():
    contract = r3.delta_preregistration()
    assert contract["prohibitions"]["post2025_outcome_read"] is True
    assert contract["prohibitions"]["production_adoption"] is True
    assert contract["prohibitions"]["portfolio_experiment"] is True
    assert contract["prospective_activation"]["production_adoption"] is False
    assert contract["prospective_activation"]["broker_action_allowed"] is False
