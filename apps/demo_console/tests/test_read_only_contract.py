"""Execute readers under I/O interception, including the footer-only boundary."""
from __future__ import annotations

import builtins
import hashlib
import io
import os
import struct
from datetime import date
from pathlib import Path

import pytest

from apps.demo_console.adapters import artifact_reader


def test_authoritative_input_never_opened_for_write(make_artifact, monkeypatch):
    spec = make_artifact([{"decision_date": date(2025, 12, 1), "ticker": "SYNTH"}])
    before = spec.path.read_bytes()
    input_path = spec.path.resolve()
    reads = []

    def guarded_open(original):
        def call(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and Path(file).resolve() == input_path:
                assert not any(flag in mode for flag in "wax+"), "Authoritative input write attempted"
                reads.append(mode)
            return original(file, mode, *args, **kwargs)
        return call

    monkeypatch.setattr(builtins, "open", guarded_open(builtins.open))
    monkeypatch.setattr(io, "open", guarded_open(io.open))
    original_os_open = os.open

    def guarded_os_open(file, flags, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)) and Path(file).resolve() == input_path:
            forbidden = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
            assert flags & forbidden == 0, "Authoritative input OS write attempted"
        return original_os_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_os_open)
    table = artifact_reader.read_frozen_parquet(spec, ("ticker",))
    assert table.to_pylist() == [{"ticker": "SYNTH"}]
    assert reads and all(mode == "rb" for mode in reads)
    assert spec.path.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == spec.sha256


class _ReadWatch:
    def __init__(self, handle, spans):
        self._handle = handle
        self._spans = spans

    def read(self, size=-1):
        start = self._handle.tell()
        result = self._handle.read(size)
        self._spans.append((start, start + len(result)))
        return result

    def readinto(self, buffer):
        start = self._handle.tell()
        count = self._handle.readinto(buffer)
        self._spans.append((start, start + count))
        return count

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self._handle.__exit__(*args)


@pytest.mark.parametrize("case", [
    "mixed_group", "mixed_row_groups", "later_execution", "no_statistics",
    "null_date", "missing_date_column",
])
def test_unproven_or_post2025_artifact_reads_footer_only(case, make_artifact, monkeypatch):
    rows = [{"decision_date": date(2025, 12, 31), "ticker": "SYNTH_A"}]
    kwargs = {}
    if case in {"mixed_group", "mixed_row_groups"}:
        rows.append({"decision_date": date(2026, 1, 2), "ticker": "SYNTH_FUTURE"})
        if case == "mixed_row_groups":
            kwargs["row_group_size"] = 1
    elif case == "later_execution":
        rows[0]["execution_date"] = date(2026, 1, 2)
        kwargs["date_columns"] = ("decision_date", "execution_date")
    elif case == "no_statistics":
        kwargs["statistics"] = False
    elif case == "null_date":
        rows.append({"decision_date": None, "ticker": "SYNTH_NULL"})
    else:
        kwargs["date_columns"] = ("unexposed_date",)
    spec = make_artifact(rows, **kwargs)
    raw = spec.path.read_bytes()  # Synthetic fixture only, before interception.
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans = []
    original_open = Path.open

    def watch_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        if path.resolve() == spec.path.resolve():
            assert mode == "rb"
            return _ReadWatch(handle, spans)
        return handle

    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected source reached full-file hashing or Parquet data reader")

    monkeypatch.setattr(Path, "open", watch_open)
    monkeypatch.setattr(artifact_reader.hashlib, "file_digest", forbidden)
    monkeypatch.setattr(artifact_reader.pq, "ParquetFile", forbidden)
    monkeypatch.setattr(artifact_reader.pq, "read_table", forbidden)
    with pytest.raises(artifact_reader.ArtifactError):
        artifact_reader.read_frozen_parquet(spec, ("ticker",))
    assert spans, "Expected actual metadata reads to be observed"
    assert all(footer_start <= start <= end <= len(raw) for start, end in spans), spans
