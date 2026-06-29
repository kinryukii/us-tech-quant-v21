from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OUT = Path("outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT")
V148 = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")
V149 = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT")
REQUIRED = [
    "trial_validity_ledger.csv",
    "holding_level_validity_ledger.csv",
    "paired_validity_ledger.csv",
    "clean_replay_summary.csv",
    "invalid_reason_count.csv",
    "invalid_reason_by_date.csv",
    "invalid_reason_by_strategy.csv",
    "invalid_reason_by_horizon.csv",
    "invalid_reason_by_bucket.csv",
    "e_r1_vs_a1_clean_replay_result.csv",
    "V21.154_readable_report.txt",
    "V21.154_machine_summary.json",
]


def test_required_outputs_exist() -> None:
    for name in REQUIRED:
        assert (OUT / name).exists(), name


def test_partial_portfolios_excluded_from_clean_stats() -> None:
    trials = pd.read_csv(OUT / "trial_validity_ledger.csv")
    invalid_partial = trials[trials["valid_holding_count"] < trials["requested_holding_count"]]
    assert (invalid_partial["is_valid_trial"].astype(bool) == False).all()
    clean = pd.read_csv(OUT / "clean_replay_summary.csv")
    assert (clean["valid_paired_trial_count"] >= 0).all()


def test_one_sided_invalid_pairs_excluded() -> None:
    paired = pd.read_csv(OUT / "paired_validity_ledger.csv")
    one_sided = paired[paired["E_R1_valid"].astype(bool) != paired["A1_valid"].astype(bool)]
    if not one_sided.empty:
        assert (~one_sided["paired_valid"].astype(bool)).all()


def test_refill_uses_lower_rank_same_strategy() -> None:
    h = pd.read_csv(OUT / "holding_level_validity_ledger.csv")
    refill = h[h["is_refill"].astype(bool)]
    if not refill.empty:
        assert (refill["refill_source"] == "LOWER_RANK_REFILL_SAME_DATE_STRATEGY").all()
        assert (refill["rank"] > refill["portfolio_bucket"].str.replace("Top", "").astype(int)).all()


def test_distinct_invalid_reasons_present() -> None:
    reasons = set(pd.read_csv(OUT / "invalid_reason_count.csv")["invalid_reason"])
    required = {
        "INVALID_MISSING_ENTRY_PRICE",
        "INVALID_MISSING_EXIT_PRICE",
        "INVALID_INSUFFICIENT_FORWARD_WINDOW",
        "INVALID_INSUFFICIENT_VALID_HOLDINGS",
    }
    assert required.issubset(reasons)


def test_v148_v149_not_overwritten_and_summary_controls() -> None:
    assert (V148 / "V21.148_summary.json").exists()
    assert (V149 / "V21.149_summary.json").exists()
    s = json.loads((OUT / "V21.154_machine_summary.json").read_text(encoding="utf-8"))
    for key in [
        "FINAL_STATUS",
        "DECISION",
        "total_invalid_paired_trial_count",
        "total_valid_paired_trial_count",
        "research_only",
        "official_adoption_allowed",
        "broker_action_allowed",
        "protected_outputs_modified",
    ]:
        assert key in s
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["protected_outputs_modified"] is False
