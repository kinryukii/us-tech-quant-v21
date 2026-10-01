"""Synthetic-only, bit-for-bit acceptance tests and a fixed microbenchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from fast_cvar_numeric import smooth_cvar_buffered
from optimization import SPEC, _smooth_cvar


SHAPES = ((1, 1, 2), (2, 3, 7), (7, 20, 32), (128, 20, 64))
MODES = ("mixed", "positive", "zero", "negative", "signed_zero", "large")
LAYOUTS = ("C", "F", "strided")


def synthetic_case(shape, mode="mixed", locked=True, layout="C"):
    s, n, h = shape
    rng = np.random.default_rng(902800 + s * 101 + n * 11 + h)
    weights = rng.uniform(0.0, 0.1, (s, n))
    returns = rng.normal(0.002, 0.02, (s, h, n))
    reserved = rng.normal(0.0, 0.003, (s, h)) if locked else None
    if mode == "positive":
        returns = np.abs(returns)
        if reserved is not None:
            reserved = np.abs(reserved)
    elif mode == "negative":
        returns = -np.abs(returns)
        if reserved is not None:
            reserved = -np.abs(reserved)
    elif mode == "zero":
        weights.fill(0.0)
        returns.fill(0.0)
        if reserved is not None:
            reserved.fill(0.0)
    elif mode == "signed_zero":
        weights.fill(-0.0)
        returns.fill(0.0)
        returns[..., ::2] = -0.0
        if reserved is not None:
            reserved.fill(-0.0)
            reserved[..., ::2] = 0.0
    elif mode == "large":
        returns *= 2500.0
        if reserved is not None:
            reserved *= 2500.0
    elif mode != "mixed":
        raise ValueError(mode)
    if layout == "F":
        weights = np.asfortranarray(weights)
        returns = np.asfortranarray(returns)
        if reserved is not None:
            reserved = np.asfortranarray(reserved)
    elif layout == "strided":
        def strided(value):
            expanded = np.empty((*value.shape[:-1], value.shape[-1] * 2))
            expanded[..., ::2] = value
            expanded[..., 1::2] = np.nan
            return expanded[..., ::2]
        weights, returns = strided(weights), strided(returns)
        if reserved is not None:
            reserved = strided(reserved)
    elif layout != "C":
        raise ValueError(layout)
    return weights, returns, reserved


def assert_float64_bits_equal(actual, expected, name="output"):
    assert actual.shape == expected.shape, name
    assert actual.dtype == expected.dtype == np.float64, name
    np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("locked", (False, True))
@pytest.mark.parametrize("layout", LAYOUTS)
def test_direct_outputs_are_bitwise_identical(shape, mode, locked, layout):
    args = synthetic_case(shape, mode, locked, layout)
    snapshots = [None if item is None else item.copy() for item in args]
    expected = _smooth_cvar(*args)
    actual = smooth_cvar_buffered(*args)
    for name, output, reference in zip(("cvar", "gradient", "eta"), actual, expected):
        assert_float64_bits_equal(output, reference, name)
    for value, original in zip(args, snapshots):
        if value is not None:
            assert_float64_bits_equal(value, original, "input remains unchanged")


def test_call_outputs_are_independent_and_safe_for_repeated_calls():
    args = synthetic_case((7, 20, 32))
    original = smooth_cvar_buffered(*args)
    saved = tuple(value.copy() for value in original)
    another = smooth_cvar_buffered(*synthetic_case((7, 20, 32), "negative"))
    for actual, expected in zip(original, saved):
        assert_float64_bits_equal(actual, expected)
    for left in original:
        for right in another:
            assert not np.shares_memory(left, right)


def _hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _time_function(function, args, repetitions):
    start = time.perf_counter()
    for _ in range(repetitions):
        function(*args)
    return (time.perf_counter() - start) / repetitions


def make_receipt(output):
    cases = 0
    mismatches = []
    for shape in SHAPES:
        for mode in MODES:
            for locked in (False, True):
                for layout in LAYOUTS:
                    cases += 1
                    args = synthetic_case(shape, mode, locked, layout)
                    reference, buffered = _smooth_cvar(*args), smooth_cvar_buffered(*args)
                    for name, value, expected in zip(("cvar", "gradient", "eta"), buffered, reference):
                        unequal = value.view(np.uint64) != expected.view(np.uint64)
                        if np.any(unequal):
                            mismatches.append(dict(shape=shape, mode=mode, locked=locked,
                                                   layout=layout, output=name,
                                                   different_values=int(np.count_nonzero(unequal))))
    benchmarks = []
    with threadpool_limits(limits=2):
        for shape, repetitions in (((1, 20, 32), 120), ((128, 20, 32), 40),
                                   ((128, 20, 64), 25), ((512, 20, 64), 10)):
            args = synthetic_case(shape)
            for _ in range(3):
                _smooth_cvar(*args)
                smooth_cvar_buffered(*args)
            reference_seconds, buffered_seconds = [], []
            for round_index in range(5):
                order = ((_smooth_cvar, reference_seconds), (smooth_cvar_buffered, buffered_seconds))
                if round_index % 2:
                    order = tuple(reversed(order))
                for function, timings in order:
                    timings.append(_time_function(function, args, repetitions))
            reference_median = float(np.median(reference_seconds))
            buffered_median = float(np.median(buffered_seconds))
            benchmarks.append(dict(shape_S_N_H=shape, repetitions_each_round=repetitions, rounds=5,
                                   reference_seconds_per_call=reference_seconds,
                                   buffered_seconds_per_call=buffered_seconds,
                                   reference_median_seconds=reference_median,
                                   buffered_median_seconds=buffered_median,
                                   measured_speed_ratio=reference_median / buffered_median))
    folder = Path(__file__).resolve().parent
    receipt = dict(status="PASS" if not mismatches else "REJECTED_NUMERIC_DIFFERENCE",
                   scope="SYNTHETIC_ONLY_ALLOCATION_CHANGE_NO_PARAMETER_OR_MODEL_SEARCH",
                   candidate="fast_cvar_numeric.smooth_cvar_buffered",
                   numeric_cases=cases, checked_outputs=["cvar", "gradient", "eta"],
                   comparison="float64 uint64 bit patterns, including signed zeros",
                   shapes_S_N_H=SHAPES, modes=MODES, layouts=LAYOUTS,
                   reserved_joint_loss_checked=[False, True],
                   mismatches=mismatches, benchmark=benchmarks,
                   core_source_sha256=_hash_file(folder / "optimization.py"),
                   candidate_source_sha256=_hash_file(folder / "fast_cvar_numeric.py"),
                   test_source_sha256=_hash_file(folder / "test_fast_cvar_numeric.py"),
                   frozen_settings={key: SPEC[key] for key in
                                    ["cvar_alpha", "cvar_softplus_epsilon", "eta_bisections"]},
                   environment=dict(python=sys.version, numpy=np.__version__,
                                    platform=platform.platform(), benchmark_threads=2),
                   production_results_read=False, optimization_installed=False,
                   limitation="Direct numeric equivalence only; optimizer and account end-to-end equivalence is a separate prerequisite.")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(dict(status=receipt["status"], numeric_cases=cases,
                          mismatches=len(mismatches),
                          benchmark=[{key: value for key, value in row.items()
                                      if key in ["shape_S_N_H", "reference_median_seconds", "buffered_median_seconds", "measured_speed_ratio"]}
                                     for row in benchmarks], output=str(output)), indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", default=str(Path(__file__).resolve().parent / "audits" / "CVAR_BUFFER_NUMERIC_RECEIPT.json"))
    arguments = parser.parse_args()
    raise SystemExit(0 if make_receipt(arguments.receipt)["status"] == "PASS" else 1)
