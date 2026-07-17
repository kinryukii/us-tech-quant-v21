"""Small, offline fixtures for the resumable legacy-forward overlap comparator."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compare_legacy_forward_overlap_r1 import run_compare


def _qfq(root: Path, ticker: str, dates: list[str], closes: list[float]) -> None:
    path = root / ticker
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": dates, "close": np.asarray(closes, dtype="float64")}).to_parquet(path / "daily_qfq.parquet", index=False)


def _run(tmp_path: Path, rows: list[dict], *, horizon: int = 1, chunk: int = 2, resume: bool = False) -> dict:
    panel = tmp_path / "legacy.csv"
    if not panel.exists():
        pd.DataFrame(rows).to_csv(panel, index=False)
    stock = tmp_path / "stocks"
    _qfq(stock, "AAA", ["2026-07-03", "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"], [100, 101, 102, 106, 108, 110])
    output = tmp_path / "outside_repo_output"
    args = ["--legacy-panel-path", str(panel), "--stock-data-root", str(stock), "--output-dir", str(output),
            "--horizon", str(horizon), "--chunk-size", str(chunk)]
    if resume:
        args.append("--resume")
    return run_compare(args)


def _one(date: str = "2026-07-03", value: float = .01) -> list[dict]:
    return [{"ticker": "AAA", "research_date": date, "forward_return_1d": value}]


def test_shift_minus_one(tmp_path):
    result = _run(tmp_path, _one(value=.01))
    assert result["comparable_row_count"] == 1 and result["strict_equivalence_pass"]


def test_shift_minus_five(tmp_path):
    result = _run(tmp_path, [{"ticker": "AAA", "research_date": "2026-07-03", "forward_return_5d": .10}], horizon=5)
    assert result["comparable_row_count"] == 1


def test_weekend_uses_trading_rows(tmp_path):
    result = _run(tmp_path, _one("2026-07-03", .01))
    assert result["finite_mismatch_count"] == 0


def test_exact_date_required(tmp_path):
    result = _run(tmp_path, _one("2026-07-04", .01))
    assert result["excluded_row_count"] == 1


def test_missing_ticker_classified(tmp_path):
    result = _run(tmp_path, [{"ticker": "MISS", "research_date": "2026-07-03", "forward_return_1d": .1}])
    assert result["comparable_row_count"] == 0


def test_immature_tail_classified(tmp_path):
    result = _run(tmp_path, _one("2026-07-10", .01))
    assert result["excluded_row_count"] == 1


def test_identical_duplicate_does_not_crash(tmp_path):
    result = _run(tmp_path, _one() + _one())
    assert result["unique_legacy_key_count"] == 1


def test_conflicting_duplicate_is_recorded(tmp_path):
    result = _run(tmp_path, _one(value=.01) + _one(value=.02))
    differences = pd.read_parquet(tmp_path / "outside_repo_output" / "horizon_1_difference_rows.parquet")
    assert "DUPLICATE_LEGACY_KEY_CONFLICT" in set(differences["classification"])


def test_chunk_boundaries_do_not_lose_rows(tmp_path):
    rows = [_one("2026-07-03", .01)[0], _one("2026-07-06", 102 / 101 - 1)[0], _one("2026-07-07", 106 / 102 - 1)[0]]
    result = _run(tmp_path, rows, chunk=1)
    assert result["legacy_rows_scanned"] == 3


def test_resume_completed_does_not_duplicate_counts(tmp_path):
    first = _run(tmp_path, _one())
    second = _run(tmp_path, _one(), resume=True)
    assert first["legacy_rows_scanned"] == second["legacy_rows_scanned"] == 1


def test_resume_parameter_mismatch_rejected(tmp_path):
    _run(tmp_path, _one())
    panel = tmp_path / "legacy.csv"; stock = tmp_path / "stocks"; output = tmp_path / "outside_repo_output"
    with pytest.raises(ValueError, match="RESUME_MISMATCH"):
        run_compare(["--legacy-panel-path", str(panel), "--stock-data-root", str(stock), "--output-dir", str(output), "--horizon", "1", "--chunk-size", "3", "--resume"])


def test_float64_calculation(tmp_path):
    _run(tmp_path, _one())
    difference = pd.read_parquet(tmp_path / "outside_repo_output" / "horizon_1_difference_rows.parquet")
    assert difference.empty or difference.get("compact_value", pd.Series(dtype="float64")).dtype == "float64"


def test_output_is_outside_repo(tmp_path):
    result = _run(tmp_path, _one())
    assert result["scan_completed"]


def test_market_data_not_copied(tmp_path):
    _run(tmp_path, _one())
    assert not list((tmp_path / "outside_repo_output").rglob("daily_qfq.parquet"))


def test_invalid_horizon_rejected(tmp_path):
    with pytest.raises(SystemExit):
        _run(tmp_path, _one(), horizon=3)


def test_schema_mapping_written(tmp_path):
    _run(tmp_path, _one())
    mapping = json.loads((tmp_path / "outside_repo_output" / "schema_mapping.json").read_text())
    assert mapping["forward"] == "forward_return_1d"


def test_required_reports_written(tmp_path):
    _run(tmp_path, _one())
    output = tmp_path / "outside_repo_output"
    expected = {"summary.json", "checkpoint.json", "execution_journal.jsonl", "serialization_precision_analysis.json",
                "horizon_1_equivalence.parquet", "horizon_1_exclusion_summary.parquet", "horizon_1_difference_rows.parquet", "horizon_1_ticker_summary.parquet"}
    assert expected <= {path.name for path in output.iterdir()}


def test_27_identical_rows_are_canonicalized_and_compared(tmp_path):
    result = _run(tmp_path, _one() * 27, chunk=5)
    assert result["legacy_rows_scanned"] == 27
    assert result["unique_legacy_key_count"] == 1
    assert result["identical_duplicate_key_count"] == 1
    assert result["identical_duplicate_extra_row_count"] == 26
    assert result["canonical_unique_key_count"] == result["comparable_key_count"] == 1


def test_valid_duplicates_plus_invalid_value_remain_comparable(tmp_path):
    rows = _one() * 26 + [{"ticker": "AAA", "research_date": "2026-07-03", "forward_return_1d": "bad"}]
    result = _run(tmp_path, rows, chunk=7)
    assert result["comparable_key_count"] == 1 and result["invalid_legacy_row_count"] == 1


def test_duplicate_conflict_excludes_canonical_key(tmp_path):
    result = _run(tmp_path, _one() * 26 + _one(value=.02), chunk=8)
    assert result["conflicting_duplicate_key_count"] == 1 and result["comparable_key_count"] == 0


def test_identical_duplicates_are_not_difference_rows(tmp_path):
    _run(tmp_path, _one() * 27, chunk=4)
    differences = pd.read_parquet(tmp_path / "outside_repo_output" / "horizon_1_difference_rows.parquet")
    assert differences.empty or "DUPLICATE_LEGACY_KEY_IDENTICAL" not in set(differences["classification"])


def test_resume_preserves_duplicate_and_comparable_counts(tmp_path):
    first = _run(tmp_path, _one() * 27, chunk=6)
    second = _run(tmp_path, _one() * 27, chunk=6, resume=True)
    assert first["identical_duplicate_extra_row_count"] == second["identical_duplicate_extra_row_count"] == 26
    assert first["comparable_key_count"] == second["comparable_key_count"] == 1


def test_duplicate_group_across_chunk_boundary(tmp_path):
    result = _run(tmp_path, _one() * 27, chunk=13)
    assert result["identical_duplicate_key_count"] == 1 and result["comparable_key_count"] == 1
