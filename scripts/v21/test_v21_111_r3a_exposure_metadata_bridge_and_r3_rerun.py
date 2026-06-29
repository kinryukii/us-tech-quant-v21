#!/usr/bin/env python
"""Tests for V21.111-R3A exposure metadata bridge and R3 rerun."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/v21"))

import v21_111_r3a_exposure_metadata_bridge_and_r3_rerun as r3a


OUT_REL = Path("outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN")
SUMMARY_NAME = "V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN_summary.json"


def raw_frame(n: int = 80) -> pd.DataFrame:
    return pd.DataFrame({
        "strategy": ["D_WEIGHT_OPTIMIZED_R1"] * n,
        "rank": list(range(1, n + 1)),
        "ticker": [f"T{i:03d}" for i in range(1, n + 1)],
        "final_score": [100 - i * 0.5 for i in range(1, n + 1)],
        "eligible_flag": [True] * n,
    })


def metadata_frame(n: int = 80, ticker_col: str = "ticker", sector_col: str = "sector", industry_col: str = "industry") -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        if i <= 18:
            sector, industry = "Technology", "Semiconductor Equipment & Materials" if i <= 8 else "Software"
        elif i <= 50:
            sector, industry = ("Technology", "Software") if i % 2 == 0 else ("Industrials", "Machinery")
        else:
            sector, industry = ("Healthcare", "Biotech") if i % 2 == 0 else ("Financials", "Banks")
        rows.append({ticker_col: f"T{i:03d}", sector_col: sector, industry_col: industry})
    return pd.DataFrame(rows)


def write_raw(root: Path, frame: pd.DataFrame | None = None) -> Path:
    path = root / r3a.RAW_D_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    (frame if frame is not None else raw_frame()).to_csv(path, index=False)
    return path


def write_metadata(root: Path, name: str, frame: pd.DataFrame) -> Path:
    path = root / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def test_metadata_discovery_finds_usable_synthetic_metadata_source(tmp_path: Path) -> None:
    raw = raw_frame()
    write_raw(tmp_path, raw)
    source = write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    rows, selected = r3a.discover_metadata(tmp_path, raw, tmp_path / OUT_REL)
    assert selected is not None
    assert selected["file_path"] == r3a.rel(tmp_path, source)
    assert any(row["usable"] for row in rows)


def test_best_metadata_source_selection_prefers_higher_ticker_overlap(tmp_path: Path) -> None:
    raw = raw_frame()
    write_raw(tmp_path, raw)
    low = metadata_frame(60)
    high = metadata_frame(80)
    write_metadata(tmp_path, "low_company_metadata.csv", low)
    high_path = write_metadata(tmp_path, "high_company_metadata.csv", high)
    _, selected = r3a.discover_metadata(tmp_path, raw, tmp_path / OUT_REL)
    assert selected is not None
    assert selected["file_path"] == r3a.rel(tmp_path, high_path)


def test_sector_industry_alias_columns_are_recognized(tmp_path: Path) -> None:
    raw = raw_frame()
    write_raw(tmp_path, raw)
    source = write_metadata(tmp_path, "alias_company_snapshot.csv", metadata_frame(80, "Symbol", "GICS Sector", "industry_name"))
    row = r3a.inspect_candidate(source, set(raw["ticker"]), tmp_path)
    assert row["available_ticker_column"] == "Symbol"
    assert row["available_sector_column"] == "GICS Sector"
    assert row["available_industry_column"] == "industry_name"
    assert row["usable"] is True


def test_insufficient_metadata_coverage_returns_partial_pass_instead_of_crashing(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "small_metadata.csv", metadata_frame(10))
    summary = r3a.run(tmp_path)
    assert summary["final_status"] == "PARTIAL_PASS_V21_111_R3A_METADATA_BRIDGE_INSUFFICIENT"
    assert summary["decision"] == "R3_RERUN_BLOCKED_METADATA_COVERAGE_INSUFFICIENT"


def test_bridged_output_contains_required_columns(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    r3a.run(tmp_path)
    bridge = pd.read_csv(tmp_path / OUT_REL / "bridged_raw_d_with_exposure.csv")
    for column in ["ticker", "raw_rank", "raw_final_score", "sector", "industry"]:
        assert column in bridge.columns


def test_r3_rerun_executes_when_metadata_coverage_is_sufficient(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    summary = r3a.run(tmp_path)
    assert summary["variants_tested"] == 1620
    assert (tmp_path / OUT_REL / "r3_rerun" / "exposure_adjustment_grid_results.csv").is_file()


def test_official_adoption_allowed_is_always_false(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    assert r3a.run(tmp_path)["official_adoption_allowed"] is False


def test_broker_action_allowed_is_always_false(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    assert r3a.run(tmp_path)["broker_action_allowed"] is False


def test_protected_paths_are_not_written(tmp_path: Path) -> None:
    protected = tmp_path / "outputs/v21/V21.111_R3_EXPOSURE_ADJUSTED_ALPHA_RETENTION_DIAGNOSTIC/marker.txt"
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("keep\n", encoding="utf-8")
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    summary = r3a.run(tmp_path)
    assert protected.read_text(encoding="utf-8") == "keep\n"
    assert summary["protected_outputs_modified"] is False


def test_summary_json_contains_all_required_fields(tmp_path: Path) -> None:
    write_raw(tmp_path)
    write_metadata(tmp_path, "company_metadata.csv", metadata_frame())
    r3a.run(tmp_path)
    summary = json.loads((tmp_path / OUT_REL / SUMMARY_NAME).read_text(encoding="utf-8"))
    for field in r3a.SUMMARY_FIELDS:
        assert field in summary
