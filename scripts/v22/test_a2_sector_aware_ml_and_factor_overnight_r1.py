from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import a2_sector_aware_ml_and_factor_overnight_r1 as research


def test_taxonomy_and_dataset_hashes_are_exact() -> None:
    assert research.sha256_file(research.TAXONOMY_PATH) == research.EXPECTED_TAXONOMY_FILE_SHA256
    assert research.sha256_file(research.DATASET) == research.EXPECTED_DATASET_SHA256
    metadata = json.loads(research.PRIOR_METADATA.read_text(encoding="utf-8"))
    assert metadata["taxonomy_hash"] == research.EXPECTED_TAXONOMY_HASH


def test_bounded_search_contract() -> None:
    specs = research.fixed_model_specs()
    assert len(specs) == 28
    assert len({row["model_spec_id"] for row in specs}) == len(specs)
    assert len(specs) <= research.MAX_UNIQUE_SPECS
    assert len(research.TRANSPORT_BRANCHES) * 8 <= research.MAX_STAGE_B_SPECS
    assert research.MAX_TOTAL_FITS == 6000


def test_stage_a_dates_and_temporal_purge() -> None:
    assert max(end for _, _, end in research.STAGE_A_FOLDS) == pd.Timestamp("2023-01-01")
    frame = pd.DataFrame({
        "signal_date": pd.to_datetime(["2021-01-04", "2021-12-01", "2022-01-03"]),
        "target_end_date": pd.to_datetime(["2021-02-03", "2021-12-30", "2022-02-01"]),
        "target": [0.1, 0.2, 0.3],
    })
    train = research.temporal_train(frame, pd.Timestamp("2022-01-01"))
    assert train.signal_date.max() < pd.Timestamp("2022-01-01")
    assert train.target_end_date.max() < pd.Timestamp("2022-01-01")


def _day() -> pd.DataFrame:
    tickers = [f"T{i:02d}" for i in range(20)]
    return pd.DataFrame({
        "ticker": tickers,
        "a2_prediction": np.linspace(-1, 1, 20),
        "ml_prediction": np.linspace(1, -1, 20),
        "ff12": ["A"] * 8 + ["B"] * 6 + ["C"] * 6,
        "ff48": ["A1"] * 4 + ["A2"] * 4 + ["B1"] * 3 + ["B2"] * 3 + ["C1"] * 3 + ["C2"] * 3,
    })


@pytest.mark.parametrize("branch", research.TRANSPORT_BRANCHES)
def test_transport_weights_are_long_only_top20_and_sum_to_one(branch: dict) -> None:
    weights = research.build_weights(_day(), branch)
    assert len(weights) == 20
    assert min(weights.values()) > 0
    assert abs(sum(weights.values()) - 1.0) <= 1e-12


def test_s1_sector_budget_identity() -> None:
    day = _day()
    weights = research.build_weights(day, research.TRANSPORT_BRANCHES[0])
    joined = day.assign(weight=day.ticker.map(weights))
    observed = joined.groupby("ff12").weight.sum().sort_index()
    counts = day.groupby("ff12").ticker.count().astype(float)
    expected = (counts / counts.sum()).pow(0.75)
    expected /= expected.sum()
    np.testing.assert_allclose(observed.to_numpy(), expected.sort_index().to_numpy(), atol=1e-12, rtol=0)


def test_no_full_universe_or_future_taxonomy_backfill() -> None:
    taxonomy = pd.read_parquet(research.TAXONOMY_PATH, columns=["signal_date", "ticker"])
    assert pd.to_datetime(taxonomy.signal_date).min() == research.SOURCE_TAXONOMY_MIN
    assert pd.to_datetime(taxonomy.signal_date).max() == research.SOURCE_TAXONOMY_MAX
    assert len(taxonomy) == 15000
    assert research.fixed_model_specs()[0]["target"] == "T0_ORIGINAL_20D"


def test_2026_and_2025_firewall_constants() -> None:
    assert research.SOURCE_TAXONOMY_MAX < pd.Timestamp("2026-01-01")
    assert all(end <= pd.Timestamp("2023-01-01") for _, _, end in research.STAGE_A_FOLDS)
    assert research.PRIMARY_BETA_SCALE == 1.3915046223476935


def test_multi_year_support_has_no_artificial_year_end_liquidation() -> None:
    dates = pd.to_datetime(["2023-12-28", "2023-12-29", "2024-12-27", "2024-12-30", "2024-12-31"])
    prices = pd.DataFrame({"ticker": "QQQ", "trade_date": dates, "open": np.arange(len(dates)) + 1.0})
    top20 = pd.DataFrame({"signal_date": pd.to_datetime(["2023-12-28", "2023-12-29", "2024-12-27", "2024-12-30"]), "ticker": ["A", "A", "A", "A"]})
    selected = research.selection_signal_dates(top20, prices, {2023, 2024})
    assert pd.Timestamp("2023-12-28") in selected
    assert pd.Timestamp("2023-12-29") in selected
    assert pd.Timestamp("2024-12-27") in selected
    assert pd.Timestamp("2024-12-30") not in selected


def test_final_artifact_budget_contract() -> None:
    expected = {
        "final_report.md", "trial_ledger.parquet", "stage_a_pareto.csv", "stage_b_outer_results.csv",
        "finalist_freeze.json", "finalist_summary.csv", "primary_forward_model_manifest.json",
        "research_metadata.json", "hash_manifest.json",
    }
    assert len(expected) <= 10


def test_completed_authoritative_and_control_reconciliation() -> None:
    context = research.preflight()
    assert context["raw"]["cagr"] == pytest.approx(0.5070421599044499, abs=1e-12)
    assert context["raw"]["sharpe"] == pytest.approx(1.2353699802070324, abs=1e-12)
    assert context["raw"]["max_drawdown"] == pytest.approx(-0.370671641329821, abs=1e-12)
    metadata = json.loads((research.OUT / "research_metadata.json").read_text(encoding="utf-8"))
    assert metadata["raw_a2_reconciliation"] == "PASS_EXACT_1E-12"
    assert metadata["s1_reconciliation"] == "PASS_EXACT_1E-12"
    assert metadata["s2_reconciliation"] == "PASS_EXACT_1E-12"


def test_completed_freeze_and_final_refit_firewall() -> None:
    freeze = json.loads((research.OUT / "finalist_freeze.json").read_text(encoding="utf-8"))
    model = json.loads((research.OUT / "primary_forward_model_manifest.json").read_text(encoding="utf-8"))
    assert freeze["primary_fixed_before_2025_candidate_outcome_read"] is True
    assert freeze["candidate_2025_outcome_read_count_at_freeze"] == 0
    assert freeze["2026_outcome_read_count"] == 0
    assert model["primary_candidate_id"] == freeze["primary_challenger_id"]
    assert model["max_selection_date"] <= "2024-12-31"
    assert model["max_final_refit_label_date"] <= "2025-12-31"
    assert model["2025_used_for_specification_selection"] is False
    assert model["2026_training_rows"] == 0


def test_completed_ledger_budgets_and_artifact_surface() -> None:
    ledger = pd.read_parquet(research.OUT / "trial_ledger.parquet")
    metadata = json.loads((research.OUT / "research_metadata.json").read_text(encoding="utf-8"))
    assert metadata["unique_candidate_specs"] <= research.MAX_UNIQUE_SPECS
    assert metadata["total_model_fits"] <= research.MAX_TOTAL_FITS
    assert metadata["2026_outcome_used"] is False
    assert metadata["2026_leakage_count"] == 0
    assert set(ledger.loc[ledger.phase.eq("STAGE_A"), "seed"].astype(int)) <= set(research.SEEDS)
    assert len(list(research.OUT.iterdir())) <= 10
    binaries = [path.name for path in research.OUT.iterdir() if path.suffix in {".joblib", ".pkl", ".pickle"}]
    assert binaries == ["primary_forward_model.joblib"]
