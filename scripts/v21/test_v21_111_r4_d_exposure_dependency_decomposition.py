#!/usr/bin/env python
"""Tests for V21.111-R4 D exposure dependency decomposition."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/v21"))

import v21_111_r4_d_exposure_dependency_decomposition as r4


OUT_REL = Path("outputs/v21/V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION")
SUMMARY_NAME = "V21.111_R4_D_EXPOSURE_DEPENDENCY_DECOMPOSITION_summary.json"


def synthetic_frame(n: int = 80) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        if i <= 20:
            sector, industry = "Technology", "Semiconductor Equipment & Materials" if i <= 8 else "Software"
        elif i <= 50:
            sector, industry = ("Technology", "Software") if i % 2 == 0 else ("Industrials", "Machinery")
        else:
            sector, industry = ("Healthcare", "Biotech") if i % 2 == 0 else ("Financials", "Banks")
        rows.append({
            "ticker": f"T{i:03d}",
            "raw_rank": i,
            "raw_final_score": 100 - i,
            "sector": sector,
            "industry": industry,
        })
    return pd.DataFrame(rows)


def write_inputs(root: Path, frame: pd.DataFrame | None = None) -> None:
    data = frame if frame is not None else synthetic_frame()
    raw = root / r4.RAW_D_REL
    raw.parent.mkdir(parents=True, exist_ok=True)
    data.rename(columns={"raw_rank": "rank", "raw_final_score": "final_score"}).drop(columns=["sector", "industry"]).to_csv(raw, index=False)
    bridge = root / r4.BRIDGED_REL
    bridge.parent.mkdir(parents=True, exist_ok=True)
    data.assign(metadata_source_path="synthetic", metadata_join_status="JOINED").to_csv(bridge, index=False)


def test_sector_industry_dependency_summary_computes_correct_top_weights() -> None:
    frame = synthetic_frame()
    sector = r4.dependency_summary(frame, "sector")
    tech = next(row for row in sector if row["sector"] == "Technology")
    assert tech["top20_weight"] == 1.0
    industry = r4.dependency_summary(frame, "industry")
    semi = next(row for row in industry if row["industry"] == "Semiconductor Equipment & Materials")
    assert semi["top20_weight"] == 0.4


def test_within_sector_percentile_ranks_are_computed_correctly() -> None:
    detail = r4.add_within_ranks(synthetic_frame(), "sector", 5, "within_sector_rank", "within_sector_percentile")
    top = detail[(detail["sector"] == "Technology") & (detail["ticker"] == "T001")].iloc[0]
    assert top["within_sector_rank"] == 1
    assert top["within_sector_percentile"] == 1.0


def test_within_industry_percentile_ranks_are_computed_correctly() -> None:
    detail = r4.add_within_ranks(synthetic_frame(), "industry", 3, "within_industry_rank", "within_industry_percentile")
    top = detail[(detail["industry"] == "Semiconductor Equipment & Materials") & (detail["ticker"] == "T001")].iloc[0]
    assert top["within_industry_rank"] == 1
    assert top["within_industry_percentile"] == 1.0


def test_exposure_only_baseline_overlap_calculation() -> None:
    frame = synthetic_frame()
    ranked = r4.exposure_only_rankings(frame)["combined_exposure_score"]
    comparison = r4.compare_ranking(frame, ranked, "combined_exposure_score")
    assert comparison["top20_overlap"] >= 14
    assert comparison["top50_overlap"] >= 35


def test_residual_score_calculation_removes_sector_industry_mean_effect() -> None:
    frame = synthetic_frame()
    residual = r4.residual_rankings(frame)
    assert np.isclose(residual.groupby("sector")["sector_residual"].mean().abs().max(), 0.0)
    assert np.isclose(residual.groupby("industry")["industry_residual"].mean().abs().max(), 0.0)


def test_dependency_classification_exposure_dominated() -> None:
    assert r4.classify_dependency(14, 0.1, 0.1, 0.1) == "EXPOSURE_DOMINATED"
    assert r4.classify_dependency(1, 0.85, 0.1, 0.1) == "EXPOSURE_DOMINATED"


def test_dependency_classification_mixed_exposure_and_selection() -> None:
    assert r4.classify_dependency(10, 0.5, 0.75, 0.70) == "MIXED_EXPOSURE_AND_SELECTION"


def test_dependency_classification_selection_within_concentrated_exposure() -> None:
    assert r4.classify_dependency(7, 0.5, 0.80, 0.75) == "SELECTION_WITHIN_CONCENTRATED_EXPOSURE"


def test_missing_required_inputs_returns_partial_pass_instead_of_crashing(tmp_path: Path) -> None:
    summary = r4.run(tmp_path)
    assert summary["final_status"] == "PARTIAL_PASS_V21_111_R4_BLOCKED_MISSING_REQUIRED_INPUT"
    assert summary["decision"] == "D_EXPOSURE_DEPENDENCY_BLOCKED_INPUT_MISSING"


def test_official_adoption_allowed_is_always_false(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    assert r4.run(tmp_path)["official_adoption_allowed"] is False


def test_broker_action_allowed_is_always_false(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    assert r4.run(tmp_path)["broker_action_allowed"] is False


def test_protected_paths_are_not_written(tmp_path: Path) -> None:
    protected = tmp_path / "outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN/marker.txt"
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("keep\n", encoding="utf-8")
    write_inputs(tmp_path)
    summary = r4.run(tmp_path)
    assert protected.read_text(encoding="utf-8") == "keep\n"
    assert summary["protected_outputs_modified"] is False


def test_summary_json_contains_all_required_fields(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    r4.run(tmp_path)
    summary = json.loads((tmp_path / OUT_REL / SUMMARY_NAME).read_text(encoding="utf-8"))
    for field in r4.SUMMARY_FIELDS:
        assert field in summary
