from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

import v22_049_finalize_known_soxx_bad_tick_r1 as mod


def make_fixture(tmp_path: Path, *, wrong_close: bool = False):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    results = tmp_path / "results"
    repo.mkdir()

    raw_file = (
        data / "raw" / "symbol=SOXX" / "request_start=2020-03-14"
        / "20260725T081527.parquet"
    )
    raw_file.parent.mkdir(parents=True)
    raw = pd.DataFrame(
        {
            "code": ["US.SOXX"],
            "time_key": ["2020-03-16 09:31:00"],
            "open": [188.0],
            "high": [188.0],
            "low": [188.0],
            "close": [200.0 if wrong_close else 209.42],
            "volume": [7],
            "turnover": [1311.40],
            "change_rate": [11.911505],
            "last_close": [187.13],
        }
    )
    raw.to_parquet(raw_file, index=False)

    canonical = (
        data / "canonical" / "symbol=SOXX" / "year=2020" / "month=03"
        / "data.parquet"
    )
    canonical.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "code": ["US.SOXX", "US.SOXX", "US.SOXX"],
            "timestamp_utc": pd.to_datetime(
                [
                    "2020-03-16T13:30:00Z",
                    "2020-03-16T13:31:00Z",
                    "2020-03-16T13:32:00Z",
                ],
                utc=True,
            ),
            "timestamp_et": pd.to_datetime(
                [
                    "2020-03-16T09:30:00-04:00",
                    "2020-03-16T09:31:00-04:00",
                    "2020-03-16T09:32:00-04:00",
                ],
                utc=True,
            ).tz_convert("America/New_York"),
            "session": ["RTH", "RTH", "RTH"],
            "open": [187.0, 188.0, 209.42],
            "high": [188.0, 188.0, 210.0],
            "low": [186.5, 188.0, 209.0],
            "close": [187.5, 209.42, 209.5],
            "volume": [100, 7, 100],
        }
    )
    frame.to_parquet(canonical, index=False)

    paths = mod.build_paths(repo, data, results)
    return paths


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_target_row_is_removed(tmp_path: Path):
    paths = make_fixture(tmp_path)
    result = mod.quarantine_known_bad_tick(paths)
    final = pd.read_parquet(paths.canonical_partition)
    timestamps = pd.to_datetime(final["timestamp_utc"], utc=True)
    assert mod.TARGET_TIMESTAMP not in set(timestamps)
    assert len(final) == 2
    assert result["canonical_row_count_delta"] == -1


def test_field_mismatch_refuses_modification(tmp_path: Path):
    paths = make_fixture(tmp_path, wrong_close=True)
    before = file_hash(paths.canonical_partition)
    with pytest.raises(mod.MaintenanceError):
        mod.quarantine_known_bad_tick(paths)
    after = file_hash(paths.canonical_partition)
    assert before == after
    assert not paths.quarantine_csv.exists()


def test_quarantine_is_idempotent(tmp_path: Path):
    paths = make_fixture(tmp_path)
    mod.quarantine_known_bad_tick(paths)
    frame = pd.read_csv(paths.quarantine_csv)
    record = frame.iloc[0].to_dict()
    count = mod.append_quarantine_record_idempotent(paths.quarantine_csv, record)
    final = pd.read_csv(paths.quarantine_csv)
    assert count == 1
    assert len(final) == 1


def test_raw_hash_is_unchanged(tmp_path: Path):
    paths = make_fixture(tmp_path)
    before = file_hash(paths.raw_file)
    result = mod.quarantine_known_bad_tick(paths)
    after = file_hash(paths.raw_file)
    assert before == after
    assert result["raw_files_modified"] is False
