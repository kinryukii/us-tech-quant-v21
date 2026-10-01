"""Reuse one threadpool controller and exact-input supervised risk results.

Call ``enable(bank)`` only after all inference libraries and fitting guards
have been imported. The original RiskBank predictor performs every cache miss
on the same small support. It retains its two-thread context and mathematics.
No fitting, parameter update or full-pool prediction is performed here.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import os

import numpy as np
import pandas as pd
from threadpoolctl import ThreadpoolController

import risk_models

_CONTROLLER = None
_CONTROLLER_PID = None


def _controller():
    global _CONTROLLER, _CONTROLLER_PID
    if _CONTROLLER is None or _CONTROLLER_PID != os.getpid():
        # One module enumeration per process, after the caller's imports/guards.
        _CONTROLLER = ThreadpoolController()
        _CONTROLLER_PID = os.getpid()
    return _CONTROLLER


class CachedRiskInference:
    MAX_ENTRIES = 4096

    def __init__(self, bank, controller):
        self.bank = bank
        self.controller = controller
        self.original_predict = bank.predict_signal_vol
        self.cache = OrderedDict()
        self.hits = self.misses = self.raw_predict_calls = 0
        self.fit_attempts = 0

    def __call__(self, features, risk_name=None):
        name = self.bank.risk_name if risk_name is None else risk_name
        if name not in {"lw_hgb_vol", "lw_mlp_vol"}:
            return self.original_predict(features, risk_name)
        x = (features[self.bank.features].to_numpy(float)
             if isinstance(features, pd.DataFrame) else np.asarray(features, float))
        if x.ndim != 2 or x.shape[1] != len(self.bank.features) or not np.isfinite(x).all():
            raise ValueError("INVALID_SUPERVISED_SIGNAL_RISK_FEATURES")
        member = "hgbvol" if name == "lw_hgb_vol" else "mlpvol"
        # Preserve exact logical float64 values, order and shape. Layout and
        # writeability additionally prevent reuse across different BLAS input
        # layouts or masking an original readonly-input exception.
        digest = hashlib.sha256(x.tobytes(order="C")).digest()
        key = (name, x.shape, digest, x.strides, bool(x.flags.writeable),
               tuple(self.bank.features), id(self.bank.vol_models[member]))
        if key in self.cache:
            self.hits += 1
            result = self.cache[key]
            self.cache.move_to_end(key)
            return result.copy()
        self.misses += 1
        self.raw_predict_calls += 1
        # Call the original on the actual supplied support and input type.
        # The module's context now delegates to controller.limit(limits=2).
        result = self.original_predict(features, risk_name)
        self.cache[key] = np.array(result, copy=True)
        if len(self.cache) > self.MAX_ENTRIES:
            self.cache.popitem(last=False)
        return np.array(result, copy=True)

    def stats(self):
        return dict(hits=self.hits, misses=self.misses,
                    original_prediction_calls=self.raw_predict_calls,
                    cache_entries=len(self.cache), max_entries=self.MAX_ENTRIES,
                    fit_attempts=self.fit_attempts, thread_limit=2,
                    controller_pid=_CONTROLLER_PID,
                    exact_input_and_original_support=True)


def enable(risk_bank):
    """Enable this frozen bank in place; return the callable/cache statistics.

    Invoke after ``forbid_fitting()`` and library imports. The controller is
    shared by banks in this process, while output caches remain bank-local.
    Repeated invocation is idempotent. Existing model objects are preserved.
    """
    existing = getattr(risk_bank, "_pto_cached_risk_inference", None)
    if existing is not None:
        return existing
    controller = _controller()
    risk_models.threadpool_limits = controller.limit
    inference = CachedRiskInference(risk_bank, controller)
    risk_bank.predict_signal_vol = inference
    risk_bank._pto_cached_risk_inference = inference
    return inference
