"""Pure synthetic proof of risk IO caching equivalence; no evaluation reads."""
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import cached_replay
from fast_account import MarketArrays, OperationalEvidence, run_many
from portfolio_policy import PortfolioPolicy
from shared import RISKS, OPTIMIZERS, TARGET_FUSIONS


LEDGERS = ["daily", "positions", "orders", "fills", "execution_results",
           "contexts", "operational_actions"]


def assert_float64_bits_equal(left, right):
    left = np.asarray(left)
    right = np.asarray(right)
    assert left.dtype == right.dtype == np.dtype("float64")
    assert left.shape == right.shape
    np.testing.assert_array_equal(np.ascontiguousarray(left).view(np.uint64),
                                  np.ascontiguousarray(right).view(np.uint64))


def assert_frame_bits_equal(left, right):
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    for name in left.columns:
        if left[name].dtype == np.dtype("float64"):
            assert_float64_bits_equal(left[name].to_numpy(), right[name].to_numpy())
        elif left[name].dtype == object:
            for a, b in zip(left[name], right[name]):
                if isinstance(a, (list, tuple, np.ndarray)):
                    a, b = np.asarray(a), np.asarray(b)
                    if a.dtype == np.dtype("float64"):
                        assert_float64_bits_equal(a, b)


def synthetic_sources(tmp_path):
    rng = np.random.default_rng(20260928)
    days, n = 6, 25
    dates = pd.bdate_range("2025-06-02", periods=days)
    tickers = np.array([f"T{i:02}" for i in range(n)])
    opening = 80. + np.arange(n)[None, :] * 2. + np.arange(days)[:, None] * .25
    closing = opening * (1. + rng.uniform(-.004, .004, (days, n)))
    quality = np.zeros((days, n), bool)
    quality[3, 23] = True
    present = np.ones((days, n), bool)
    present[0, 0] = False  # An initial holding reserves units, capital and a slot.
    market = MarketArrays(dates, tickers, opening, closing, quality=quality,
                          adv=np.full((days, n), 2e7), input_present=present,
                          signal_mask=[True, True, True, True, True, False],
                          initial_marks=opening[0],
                          initial_mark_dates=np.repeat(np.datetime64("2025-05-30"), n),
                          operational_exits={dates[2]: {"T24": OperationalEvidence(
                              "SYNTHETIC_KNOWN_EXIT", dates[2], "synthetic_fixture")}})
    mu = np.linspace(.009, .048, n)[None, :] + rng.uniform(-.012, .012, (days, n))
    mu[1, 20:] = -.02  # Explicit sales and changing full-candidate TOP20.
    mu[2, 1:8] = .052
    forecast = {"mu": mu[:, None, :], "stream_ids": np.array(["ridge__identity"]),
                "tickers": tickers, "dates": dates.to_numpy()}
    correlation = np.full((n, n), .18)
    np.fill_diagonal(correlation, 1.)
    z = rng.normal(size=(32, n))
    # Extra float payload proves preservation of negative zero and a NaN payload.
    payload = np.array([0x8000000000000000, 0x7ff8000000000017], dtype=np.uint64).view(np.float64)
    risk = {"corr_diagonal": np.eye(n), "scenario_diagonal": z,
            "corr_ledoit_wolf": correlation,
            "scenario_ledoit_wolf": z @ np.linalg.cholesky(correlation).T,
            "scales": rng.uniform(.008, .018, (days, len(RISKS), n)),
            "byte_payload": payload}
    forecast_path, risk_path = tmp_path / "forecast_cube.npz", tmp_path / "risk_cache.npz"
    np.savez_compressed(forecast_path, **forecast)
    np.savez_compressed(risk_path, **risk)
    roster = pd.DataFrame([dict(path_id=f"{risk_name}_{method}", group="ridge",
                               fusion="identity", risk=risk_name, optimizer=method)
                          for risk_name in RISKS
                          for method in [*OPTIMIZERS, *TARGET_FUSIONS]])
    return market, roster, forecast_path, risk_path


def replay_sources(market, roster, forecast, risk):
    diagnostics, targets, states = [], [], []
    actor = PortfolioPolicy(roster, forecast, risk, diagnostic_callback=diagnostics.append)

    def policy(day, context):
        decision = actor(day, context)
        targets.append((decision.weights.copy(), decision.explicit_mask.copy(),
                        decision.raw_evidence_id.copy()))
        states.append((context.current_units.copy(), context.cash.copy()))
        return decision

    initial = np.zeros((len(roster), len(market.tickers)))
    initial[:, 0] = np.arange(len(roster)) + 3.
    with threadpool_limits(limits=2):
        result = run_many(market, roster.path_id.tolist(), policy,
                          initial_units=initial, initial_cash=1e6)
    return result, targets, states, pd.concat(diagnostics, ignore_index=True)


def test_six_optimizers_thirteen_risks_all_ledgers_targets_and_account_bits_equal(tmp_path, monkeypatch):
    market, roster, forecast_path, risk_path = synthetic_sources(tmp_path)
    original_load = np.load
    with original_load(forecast_path) as forecast, original_load(risk_path) as risk:
        expected_bytes = {key: (risk[key].dtype, risk[key].shape, risk[key].tobytes()) for key in risk.files}
        baseline, base_targets, base_states, base_diagnostics = replay_sources(market, roster, forecast, risk)

    decompressions = Counter()
    original_getitem = np.lib.npyio.NpzFile.__getitem__

    def counted_getitem(archive, key):
        if Path(str(archive.zip.filename)).name == "risk_cache.npz":
            decompressions[key] += 1
        return original_getitem(archive, key)

    monkeypatch.setattr(np.lib.npyio.NpzFile, "__getitem__", counted_getitem)
    with cached_replay.eager_risk_load() as loaded:
        with np.load(forecast_path) as forecast:
            risk = np.load(risk_path)
            assert isinstance(forecast, np.lib.npyio.NpzFile)
            assert isinstance(risk, cached_replay.EagerRiskArchive)
            cached, cache_targets, cache_states, cache_diagnostics = replay_sources(market, roster, forecast, risk)
            for key, (dtype, shape, raw_bytes) in expected_bytes.items():
                for _ in range(10):
                    value = risk[key]
                    assert value.dtype == dtype and value.shape == shape and value.tobytes() == raw_bytes
                    assert not value.flags.writeable
                    assert risk[key + ".npy"] is value
                with pytest.raises(ValueError):
                    value.flat[0] = 123.
            assert len(loaded) == 1 and loaded[0] is risk
            assert dict(risk.decompression_counts) == {key: 1 for key in expected_bytes}
    assert np.load is original_load
    assert dict(decompressions) == {key: 1 for key in expected_bytes}
    assert len(roster) == 78
    for name in LEDGERS:
        left, right = getattr(baseline, name), getattr(cached, name)
        assert len(left) > 0, f"unexercised ledger: {name}"
        assert_frame_bits_equal(left, right)
    assert baseline.metadata == cached.metadata
    assert baseline.audit == cached.audit
    assert_float64_bits_equal(baseline.final_units, cached.final_units)
    assert_float64_bits_equal(baseline.final_cash, cached.final_cash)
    for before, after in zip(base_targets, cache_targets):
        assert_float64_bits_equal(before[0], after[0])
        np.testing.assert_array_equal(before[1], after[1])
        np.testing.assert_array_equal(before[2], after[2])
    for before, after in zip(base_states, cache_states):
        assert_float64_bits_equal(before[0], after[0])
        assert_float64_bits_equal(before[1], after[1])
    assert_frame_bits_equal(base_diagnostics, cache_diagnostics)


def test_other_np_load_inputs_and_arguments_are_delegated_unchanged(tmp_path, monkeypatch):
    original = np.load
    array = np.arange(7, dtype=np.float64)
    npy_path, other_path = tmp_path / "plain.npy", tmp_path / "other_cache.npz"
    np.save(npy_path, array)
    np.savez_compressed(other_path, array=array)
    calls, objects = [], []

    def tracked(file, *args, **kwargs):
        result = original(file, *args, **kwargs)
        calls.append((file, args, kwargs))
        objects.append(result)
        return result

    monkeypatch.setattr(np, "load", tracked)
    with cached_replay.eager_risk_load() as archives:
        memory_map = np.load(npy_path, mmap_mode="r", allow_pickle=False)
        assert memory_map is objects[-1] and isinstance(memory_map, np.memmap)
        with np.load(other_path, allow_pickle=False) as archive:
            assert archive is objects[-1] and isinstance(archive, np.lib.npyio.NpzFile)
        with other_path.open("rb") as handle:
            with np.load(handle, allow_pickle=False) as archive:
                assert archive is objects[-1]
        assert not archives
    assert np.load is tracked
    assert calls[0] == (npy_path, (), {"mmap_mode": "r", "allow_pickle": False})
    assert calls[1] == (other_path, (), {"allow_pickle": False})


def test_run_year_cli_adapter_restores_np_load_after_runner_failure(tmp_path, monkeypatch):
    import run_suite
    path = tmp_path / "risk_cache.npz"
    np.savez_compressed(path, scales=np.array([1.], dtype=np.float64))
    original = np.load

    def failing_runner(year):
        assert year == 2025
        archive = np.load(path)
        assert isinstance(archive, cached_replay.EagerRiskArchive)
        raise RuntimeError("SYNTHETIC_RUNNER_FAILURE")

    monkeypatch.setattr(run_suite, "run_year", failing_runner)
    with pytest.raises(RuntimeError, match="SYNTHETIC_RUNNER_FAILURE"):
        cached_replay.run_cached_year(2025)
    assert np.load is original


def test_failed_archive_decode_restores_np_load_and_preserves_original_error(tmp_path):
    path = tmp_path / "risk_cache.npz"
    np.savez_compressed(path, requires_pickle=np.array([{"v": 1}], dtype=object))
    original = np.load
    with pytest.raises(ValueError, match="Object arrays cannot be loaded"):
        with cached_replay.eager_risk_load():
            np.load(path, allow_pickle=False)
    assert np.load is original
