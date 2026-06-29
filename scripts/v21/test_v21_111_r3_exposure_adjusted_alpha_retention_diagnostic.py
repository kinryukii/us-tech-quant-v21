#!/usr/bin/env python
"""Tests for V21.111-R3 exposure-adjusted alpha retention diagnostic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_111_r3_exposure_adjusted_alpha_retention_diagnostic as r3

OUT_REL = Path("outputs/v21/V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC")
SUMMARY_NAME = "V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC_summary.json"


def synthetic_frame(n: int = 80) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        if i <= 18:
            sector, industry = "Technology", "Semiconductor Equipment & Materials" if i <= 8 else "Software"
        elif i <= 50:
            sector, industry = ("Technology", "Software") if i % 2 == 0 else ("Industrials", "Machinery")
        else:
            sector, industry = ("Healthcare", "Biotech") if i % 2 == 0 else ("Financials", "Banks")
        rows.append({
            "strategy": "D_WEIGHT_OPTIMIZED_R1",
            "rank": i,
            "ticker": f"T{i:03d}",
            "final_score": 100 - i * 0.5,
            "sector": sector,
            "industry": industry,
            "eligible_flag": True,
        })
    return pd.DataFrame(rows)


def write_temp_raw(root: Path, frame: pd.DataFrame) -> Path:
    path = root / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.drop(columns=[c for c in ["sector", "industry"] if c in frame], errors="ignore").to_csv(path, index=False)
    meta = root / "outputs/v21/v21_078/V21_078_R4_REPAIRED_CLASSIFICATION_MASTER_FOR_LEDGER.csv"
    meta.parent.mkdir(parents=True, exist_ok=True)
    frame[["ticker", "sector", "industry"]].to_csv(meta, index=False)
    return path


def test_soft_exposure_adjustment_reduces_concentration_on_synthetic_data() -> None:
    frame = synthetic_frame()
    raw20 = frame.head(20)
    raw50 = frame.head(50)
    params = {
        "sector_top20_target": 0.60,
        "sector_top50_target": 0.45,
        "industry_top20_target": 0.20,
        "industry_top50_target": 0.15,
        "sector_lambda": 0.30,
        "industry_lambda": 0.20,
    }
    adjusted = r3.build_adjusted(
        frame,
        params,
        r3.bucket_weights(raw20, "sector"),
        r3.bucket_weights(raw50, "sector"),
        r3.bucket_weights(raw20, "industry"),
        r3.bucket_weights(raw50, "industry"),
    )
    raw_stats = r3.exposure_stats(frame, 20, "raw_top20")
    adjusted_stats = r3.exposure_stats(r3.adjusted_rank_view(adjusted), 20, "adjusted_top20")
    assert adjusted_stats["largest_sector_weight"] < raw_stats["largest_sector_weight"]


def test_raw_score_retention_ratio_is_computed_correctly() -> None:
    assert r3.raw_score_retention_ratio(pd.Series([10, 20]), pd.Series([9, 18])) == 0.9


def test_classification_strong_useful_too_destructive() -> None:
    assert r3.classify_variant(14, 35, 0.95, 0.90, 0.15, 0.10) == "STRONG"
    assert r3.classify_variant(12, 30, 0.90, 0.85, 0.10, 0.05) == "USEFUL_DIAGNOSTIC"
    assert r3.classify_variant(9, 40, 0.95, 0.95, 0.20, 0.20) == "TOO_DESTRUCTIVE"


def test_missing_sector_industry_metadata_gives_partial_pass_instead_of_crashing(tmp_path: Path) -> None:
    raw_path = tmp_path / "outputs/v21/V21.108_latest_data_multi_strategy_rerun/R2_archived_latest_strategy_rankings/D_WEIGHT_OPTIMIZED_R1/full_ranking.csv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    synthetic_frame().drop(columns=["sector", "industry"]).to_csv(raw_path, index=False)
    summary = r3.run(tmp_path)
    assert summary["final_status"] == "PARTIAL_PASS_V21_111_R3_BLOCKED_MISSING_EXPOSURE_METADATA"
    assert summary["decision"] == "EXPOSURE_ADJUSTED_ALPHA_RETENTION_BLOCKED_METADATA"


def test_output_directory_isolation(tmp_path: Path) -> None:
    write_temp_raw(tmp_path, synthetic_frame())
    summary = r3.run(tmp_path)
    assert summary["output_dir"].endswith("V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC")
    out = tmp_path / OUT_REL
    assert out.is_dir()
    assert all(OUT_REL.as_posix() in p.relative_to(tmp_path).as_posix() for p in out.iterdir() if p.is_file())


def test_official_adoption_allowed_is_always_false(tmp_path: Path) -> None:
    write_temp_raw(tmp_path, synthetic_frame())
    assert r3.run(tmp_path)["official_adoption_allowed"] is False


def test_broker_action_allowed_is_always_false(tmp_path: Path) -> None:
    write_temp_raw(tmp_path, synthetic_frame())
    assert r3.run(tmp_path)["broker_action_allowed"] is False


def test_protected_paths_are_not_written(tmp_path: Path) -> None:
    protected = tmp_path / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/marker.txt"
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("keep\n", encoding="utf-8")
    before = protected.read_text(encoding="utf-8")
    write_temp_raw(tmp_path, synthetic_frame())
    summary = r3.run(tmp_path)
    assert protected.read_text(encoding="utf-8") == before
    assert summary["protected_outputs_modified"] is False


def test_best_variant_is_never_selected_from_too_destructive_variants() -> None:
    results = [
        {"variant_id": "bad", "classification": "TOO_DESTRUCTIVE", "alpha_retention_score": 999, "top20_largest_sector_reduction": 1, "top20_largest_industry_reduction": 1},
        {"variant_id": "weak", "classification": "WEAK_OR_AMBIGUOUS", "alpha_retention_score": 0.1, "top20_largest_sector_reduction": 0, "top20_largest_industry_reduction": 0},
    ]
    assert r3.choose_best(results)["variant_id"] == "weak"


def test_summary_json_contains_all_required_fields(tmp_path: Path) -> None:
    write_temp_raw(tmp_path, synthetic_frame())
    r3.run(tmp_path)
    summary = json.loads((tmp_path / OUT_REL / SUMMARY_NAME).read_text(encoding="utf-8"))
    for field in r3.SUMMARY_FIELDS:
        assert field in summary


def test_live_stage_controls_when_available() -> None:
    summary_path = ROOT / OUT_REL / SUMMARY_NAME
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["official_adoption_allowed"] is False
        assert summary["broker_action_allowed"] is False
        assert summary["research_only"] is True
