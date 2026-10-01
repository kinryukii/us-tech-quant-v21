"""Replay helper: decompress the immutable risk NPZ once, without arithmetic.

Only ``risk_cache.npz`` is eager. All other ``numpy.load`` calls retain the
original arguments, implementation and return object. The account and policy
code are unchanged; the loader is restored even when replay raises.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import contextmanager
import os
from pathlib import Path
from types import MappingProxyType

import numpy as np


class EagerRiskArchive(Mapping):
    """Read-only, byte-preserving subset of the NpzFile mapping interface."""

    def __init__(self, archive, *, source=None):
        self.source = source
        self._files = tuple(archive.files)
        arrays, counts = {}, {}
        for key in self._files:
            value = archive[key]
            if not isinstance(value, np.ndarray):
                raise TypeError("RISK_ARCHIVE_MEMBER_NOT_ARRAY:" + key)
            # This changes a permission flag only: no cast, copy or calculation.
            value.setflags(write=False)
            arrays[key] = value
            counts[key] = 1
        self._arrays = MappingProxyType(arrays)
        self.decompression_counts = MappingProxyType(counts)

    @property
    def files(self):
        # NpzFile returns a list. A fresh list cannot alter this archive's keys.
        return list(self._files)

    def __getitem__(self, key):
        if key in self._arrays:
            return self._arrays[key]
        if isinstance(key, str) and key.endswith(".npy") and key[:-4] in self._arrays:
            return self._arrays[key[:-4]]
        raise KeyError(f"{key} is not a file in the archive")

    def __iter__(self):
        return iter(self._files)

    def __len__(self):
        return len(self._files)

    def close(self):
        # The underlying ZIP was already closed by the load adapter. Cached
        # arrays live as long as this eager mapping, like a normal in-memory dict.
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _is_risk_archive(file):
    try:
        return Path(os.fsdecode(os.fspath(file))).name.casefold() == "risk_cache.npz"
    except TypeError:
        # File handles and all other supported NumPy inputs remain untouched.
        return False


@contextmanager
def eager_risk_load():
    """Temporarily cache risk archive members; yield the loaded eager mappings."""
    original_load = np.load
    loaded_archives = []

    def load(file, *args, **kwargs):
        result = original_load(file, *args, **kwargs)
        if not _is_risk_archive(file) or not isinstance(result, np.lib.npyio.NpzFile):
            return result
        try:
            eager = EagerRiskArchive(result, source=os.fsdecode(os.fspath(file)))
        finally:
            result.close()
        loaded_archives.append(eager)
        return eager

    np.load = load
    try:
        yield loaded_archives
    finally:
        np.load = original_load


def run_cached_year(year):
    from run_suite import run_year
    with eager_risk_load():
        return run_year(year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = parser.parse_args()
    print(run_cached_year(args.year)["status"], flush=True)
