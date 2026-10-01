"""Strict bitwise synthetic proof for optional row-subset proximal work."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import optimization
from fast_numeric import prox_budget_subset
from fast_cvar_numeric import smooth_cvar_buffered
from fast_account import MarketArrays, OperationalEvidence, run_many
from portfolio_policy import PortfolioPolicy
from shared import RISKS

ORIGINAL_PROX = optimization._prox_budget
ORIGINAL_CVAR = optimization._smooth_cvar
RESULT_FIELDS = ["weights", "status", "iterations", "residual", "objective", "cvar_eta",
                 "exact_fixed_point", "gradient_evaluations"]
CORE = ["optimization.py", "fast_account.py", "portfolio_policy.py"]


def assert_bits(a, b):
    assert a.shape == b.shape and a.dtype == b.dtype
    if np.issubdtype(a.dtype, np.floating):
        assert a.dtype == np.dtype("float64")
        np.testing.assert_array_equal(a.view(np.uint64), b.view(np.uint64))
    else:
        np.testing.assert_array_equal(a, b)


@contextmanager
def use_prox(function, smooth=None):
    before, old_smooth = optimization._prox_budget, optimization._smooth_cvar
    optimization._prox_budget = function
    if smooth is not None:
        optimization._smooth_cvar = smooth
    try:
        yield
    finally:
        optimization._prox_budget, optimization._smooth_cvar = before, old_smooth


def prox_case(shape, layout="C", special=False):
    rng = np.random.default_rng(20250928)
    s, n = shape
    center = rng.uniform(0., .10, (s, n))
    y = center + rng.normal(.02, .07, (s, n))
    threshold = rng.uniform(0., .04, s)
    upper = rng.uniform(0., .1, (s, n))
    budget = rng.uniform(0., .95, s)
    budget[::3] = 0.
    budget[1::3] = .95
    upper[::7] = 0.
    threshold[::5] = 0.
    if special:
        y[::4] = center[::4]
        y[1::4] = -0.
        center[1::4] = 0.
        upper[2::4, ::2] = 0.
        # Exactly-on-budget rows must take the same strict > branch.
        direct = np.clip(center + optimization._soft(y-center-np.zeros(s)[:, None],
                                                     threshold[:, None]), 0., upper)
        budget[3::4] = direct[3::4].sum(axis=1)
    if layout == "F":
        y, center, upper = map(np.asfortranarray, (y, center, upper))
    elif layout == "strided":
        def make_stride(x):
            padded = np.empty((s, n*2)); padded[:, ::2] = x
            return padded[:, ::2]
        y, center, upper = map(make_stride, (y, center, upper))
    return y, center, threshold, budget, upper


@pytest.mark.parametrize("shape", [(1, 1), (1, 20), (2, 3), (8, 20), (127, 20),
                                   (128, 20), (257, 1), (1677, 20)])
@pytest.mark.parametrize("layout", ["C", "F", "strided"])
def test_subset_prox_has_identical_float64_bits_for_mixed_constraints(shape, layout):
    args = prox_case(shape, layout, special=True)
    assert_bits(ORIGINAL_PROX(*args), prox_budget_subset(*args))


@pytest.mark.parametrize("upper", [0., .1, np.array([.03, 0., .08])])
def test_broadcast_caps_and_exact_cash_lock_keep_bits(upper):
    y = np.array([[.08, .03, .09], [-0., 0., 0.], [.2, .1, .3]])
    center = np.array([[.02, .03, .01], [0., 0., 0.], [.06, .01, .04]])
    args = y, center, np.array([.005, 0., .01]), np.array([0., .95, .08]), upper
    assert_bits(ORIGINAL_PROX(*args), prox_budget_subset(*args))


def optimizer_case(n):
    rng = np.random.default_rng(20250928)
    s, h = 8, 12
    mu = rng.normal(.005, .005, (s, n))
    current = rng.uniform(0., .045, (s, n))
    base = rng.normal(size=(s, n, n))
    cov = (base @ base.transpose(0, 2, 1)) * (.002 / max(n, 1))
    scale = rng.uniform(.002, .018, (s, n))
    budget = np.array([0., .01, .05, .10, .20, .40, .70, .95])
    slots = np.array([0, 1, 2, 3, 4, 10, 19, 20])
    upper = np.full((s, n), .1); upper[:, ::3] = 0.
    upper[-1] = 0.
    scenarios = rng.normal(size=(s, h, n))
    linear = rng.normal(0., .00001, (s, n))
    locked = rng.normal(0., .0005, (s, h))
    return (mu, cov, current, budget, slots), dict(uncertainty=scale, scenarios=scenarios,
                                                upper=upper, risk_linear=linear,
                                                reserved_joint_loss=locked)


def compare_result(before, after):
    evidence = {}
    for field in RESULT_FIELDS:
        a, b = getattr(before, field), getattr(after, field)
        if a is None:
            assert b is None
        else:
            assert_bits(a, b)
        evidence[field] = "EXACT_BITS" if a is not None else "BOTH_NONE"
    assert before.residual_kind == after.residual_kind
    return evidence


@pytest.mark.parametrize("n", [1, 3, 20])
@pytest.mark.parametrize("kind", ["positive_equal", "mean_variance", "robust_mv", "cvar"])
def test_all_frozen_optimizer_outputs_equal_under_process_local_patch(n, kind):
    args, kwargs = optimizer_case(n)
    with threadpool_limits(limits=1), use_prox(ORIGINAL_PROX):
        before = optimization.optimize(kind, *args, **kwargs)
    with threadpool_limits(limits=1), use_prox(prox_budget_subset):
        after = optimization.optimize(kind, *args, **kwargs)
    compare_result(before, after)


@pytest.mark.parametrize("n", [1, 3, 20])
@pytest.mark.parametrize("prox", [ORIGINAL_PROX, prox_budget_subset])
def test_cvar_buffer_keeps_complete_optimizer_diagnostics_exact(n, prox):
    args, kwargs = optimizer_case(n)
    with threadpool_limits(limits=1), use_prox(ORIGINAL_PROX):
        before = optimization.optimize("cvar", *args, **kwargs)
    with threadpool_limits(limits=1), use_prox(prox, smooth_cvar_buffered):
        after = optimization.optimize("cvar", *args, **kwargs)
    compare_result(before, after)


class RiskCache(dict):
    @property
    def files(self):
        return list(self.keys())


def account_case(prox, *, smooth=None):
    rng = np.random.default_rng(20250928)
    dates = pd.bdate_range("2025-06-02", periods=5)
    names = np.array([f"T{i:02}" for i in range(25)])
    price = 100.*np.exp(rng.normal(0., .015, (5, 25)))
    close = price*np.exp(rng.normal(0., .007, (5, 25)))
    present = np.ones_like(price, dtype=bool); present[:, 0] = False
    quality = np.zeros_like(price, dtype=bool); quality[3, 11] = True
    adv = np.full_like(price, 1e8); adv[:, 5] = 2e6
    price[2, 5] = np.nan
    market = MarketArrays(dates, names, price, close, input_present=present, quality=quality,
                          adv=adv, operational_exits={dates[2]: {
                              "T24": OperationalEvidence("synthetic known exit", dates[2], "synthetic:exit")}})
    correlation = np.full((25, 25), .2); np.fill_diagonal(correlation, 1.)
    z = rng.normal(size=(32, 25)) @ np.linalg.cholesky(correlation).T
    scales = np.full((5, len(RISKS), 25), .008)
    risk = RiskCache(corr_diagonal=correlation, scenario_diagonal=z,
                     corr_ledoit_wolf=correlation, scenario_ledoit_wolf=z, scales=scales)
    mu = np.tile(np.linspace(.008, .025, 25), (5, 1, 1))
    mu[1, 0, -3:] = -.01; mu[3, 0, 3:9] = -.008
    forecast = dict(stream_ids=np.array(["ridge__identity"]), mu=mu)
    methods = ["positive_equal", "mean_variance", "robust_mv", "cvar", "target_equal", "target_median"]
    roster = pd.DataFrame([dict(path_id=method, group="ridge", fusion="identity", risk="diagonal",
                                optimizer=method, layer="target_fusion" if method.startswith("target_") else "pto")
                           for method in methods])
    diagnostics = []
    actor = PortfolioPolicy(roster, forecast, risk, diagnostic_callback=diagnostics.append)
    initial = np.zeros((len(methods), 25)); initial[:, 0] = np.arange(1, len(methods)+1)
    with threadpool_limits(limits=1), use_prox(prox, smooth):
        replay = run_many(market, methods, actor, initial_units=initial)
    return replay, pd.concat(diagnostics, ignore_index=True)


def frame_equal_bits(before, after):
    a, b = before.copy(), after.copy()
    for name in a:
        if pd.api.types.is_datetime64_any_dtype(a[name].dtype):
            a[name] = a[name].astype("datetime64[ns]")
            b[name] = b[name].astype("datetime64[ns]")
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    for name in a.select_dtypes(include=[np.floating]):
        assert_bits(a[name].to_numpy(), b[name].to_numpy())


def compare_accounts(before, after, diagnostics_before, diagnostics_after):
    proof = {}
    for name in ["daily", "positions", "orders", "fills", "execution_results", "contexts", "operational_actions"]:
        a, b = getattr(before, name), getattr(after, name)
        frame_equal_bits(a, b)
        proof[name] = dict(rows=len(a), all_columns_exact=True, float64_bits_exact=True)
    frame_equal_bits(diagnostics_before, diagnostics_after)
    assert len(before.operational_actions) > 0
    assert_bits(before.final_cash, after.final_cash)
    assert_bits(before.final_units, after.final_units)
    assert before.metadata == after.metadata and before.audit == after.audit
    return dict(tables=proof, diagnostics_rows=len(diagnostics_before), optimizer_diagnostics_exact=True,
                final_cash_units_bits_exact=True, metadata_audit_exact=True)


@pytest.mark.parametrize("variant", ["prox", "buffer", "both"])
def test_four_methods_and_two_target_fusions_produce_identical_seven_account_tables(variant):
    before, d_before = account_case(ORIGINAL_PROX)
    after, d_after = account_case(ORIGINAL_PROX if variant=="buffer" else prox_budget_subset,
                                smooth=smooth_cvar_buffered if variant!="prox" else None)
    compare_accounts(before, after, d_before, d_after)


def benchmark_case(s, n, fraction):
    rng = np.random.default_rng(20250928)
    center = rng.uniform(.012, .025, (s, n))
    y = center + rng.uniform(-.001, .004, (s, n))
    threshold = rng.uniform(0., .001, s)
    cap = np.full((s, n), .1)
    budget = np.full(s, .95)
    budget[:round(s*fraction)] = .005
    return y, center, threshold, budget, cap


def timed_pair(before, after, args, repetitions):
    # Alternate execution order to reduce bias from concurrent CPU activity.
    samples = {"before": [], "after": []}
    functions = {"before": before, "after": after}
    for sample in range(3):
        order = ["before", "after"] if sample%2==0 else ["after", "before"]
        for name in order:
            start = time.perf_counter()
            for _ in range(repetitions):
                functions[name](*args)
            samples[name].append((time.perf_counter()-start)/repetitions)
    return float(np.median(samples["before"])), float(np.median(samples["after"]))


def make_receipt():
    root = Path(__file__).resolve().parent
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in CORE}
    direct_cases = []
    for shape in [(1, 1), (1, 20), (2, 3), (8, 20), (127, 20), (128, 20), (257, 1), (1677, 20)]:
        for layout in ["C", "F", "strided"]:
            args = prox_case(shape, layout, special=True)
            assert_bits(ORIGINAL_PROX(*args), prox_budget_subset(*args))
            direct_cases.append(dict(shape=list(shape), layout=layout, exact_uint64_bits=True))
    optimizers = []
    with threadpool_limits(limits=1):
        for n in [1, 3, 20]:
            args, kwargs = optimizer_case(n)
            for kind in ["positive_equal", "mean_variance", "robust_mv", "cvar"]:
                with use_prox(ORIGINAL_PROX):
                    before = optimization.optimize(kind, *args, **kwargs)
                with use_prox(prox_budget_subset):
                    after = optimization.optimize(kind, *args, **kwargs)
                optimizers.append(dict(names=n, optimizer=kind, fields=compare_result(before, after)))
        before, db = account_case(ORIGINAL_PROX)
        accounts = {}
        buffer_optimizers = []
        for variant, prox, smooth in [("prox_subset_only", prox_budget_subset, None),
                                      ("cvar_buffer_only", ORIGINAL_PROX, smooth_cvar_buffered),
                                      ("combined", prox_budget_subset, smooth_cvar_buffered)]:
            after, da = account_case(prox, smooth=smooth)
            accounts[variant] = compare_accounts(before, after, db, da)
            if smooth is not None:
                for n in [1, 3, 20]:
                    args, kwargs = optimizer_case(n)
                    with use_prox(ORIGINAL_PROX):
                        a = optimization.optimize("cvar", *args, **kwargs)
                    with use_prox(prox, smooth):
                        b = optimization.optimize("cvar", *args, **kwargs)
                    buffer_optimizers.append(dict(variant=variant, names=n, optimizer="cvar", fields=compare_result(a, b)))
        benchmarks = []
        for s in [128, 1677]:
            for fraction in [0., .01, .10, .50, 1.]:
                args = benchmark_case(s, 20, fraction)
                assert_bits(ORIGINAL_PROX(*args), prox_budget_subset(*args))
                old, new = timed_pair(ORIGINAL_PROX, prox_budget_subset, args, 12)
                benchmarks.append(dict(rows=s, names=20, constrained_rows=round(s*fraction),
                                       old_seconds_per_call=old, subset_seconds_per_call=new,
                                       speedup=old/new, repeats_per_sample=12, timing_samples=3,
                                       alternating_timing_order=True, numpy_threads=1,
                                       exact_bits=True))
    for name, digest in hashes.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest
    receipt = dict(status="PASS_STRICT_BITWISE_SYNTHETIC_COMPATIBILITY", checked_at_utc=datetime.now(timezone.utc).isoformat(),
                   synthetic_only=True, production_or_2026_outcomes_read=False,
                   core_files_unchanged=True, original_core_sha256=hashes,
                   candidate_sha256=hashlib.sha256((root/"fast_numeric.py").read_bytes()).hexdigest(),
                   direct_cases=direct_cases, optimizer_cases=optimizers, buffer_optimizer_cases=buffer_optimizers,
                   independent_accounts=accounts,
                   cvar_buffer_candidate_sha256=hashlib.sha256((root/"fast_cvar_numeric.py").read_bytes()).hexdigest(),
                   cvar_buffer_direct_receipt=str((root/"audits/CVAR_BUFFER_NUMERIC_RECEIPT.json").resolve()),
                   benchmark=benchmarks, specification_unchanged=dict(optimization.SPEC),
                   fixed_iteration_counts={"prox_bisection":36,"eta_bisection":24,"maximum_optimize":512},
                   proof="Every prox row is independent. For C-contiguous y/center/2Dupper, the same direct expression and strict budget test are evaluated for all rows; constrained rows keep their original per-row operand order, reduction width and all 36 bisection comparisons. Unconstrained rows return identical direct array values. Fortran or strided operands explicitly call the captured original function to preserve row-sum reduction behavior.",
                   rejected_initial_candidate=dict(reason="Fortran-to-C row copy changed one element in a 1677x20 stress case", adopted=False,
                                                   resolution="Explicit non-C layout fallback to unmodified reference function; all layouts retested."),
                   adoption="Not activated. The helper must be explicitly imported/installed only after root review; tests patch module globals in their own process and restore them.",
                   reproduce="python -B test_fast_numeric.py --receipt")
    target = root/"audits/NUMERIC_PROX_SUBSET_COMPATIBILITY.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(receipt_path=str(target.resolve()), **receipt)


if __name__ == "__main__":
    assert "--receipt" in sys.argv
    receipt = make_receipt()
    print(json.dumps({"status": receipt["status"], "receipt_path": receipt["receipt_path"],
                      "benchmarks": receipt["benchmark"]}, ensure_ascii=False, indent=2), flush=True)
