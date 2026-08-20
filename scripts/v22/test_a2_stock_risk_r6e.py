from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_stock_risk_r6e.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_r6e", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_frozen_r6_identity_and_formal_classification() -> None:
    assert MODULE.R3.R1.sha256_file(MODULE.R6_OOF_PATH) == MODULE.R6_OOF_SHA256
    assert MODULE.REFERENCE_MODEL == "LGBM_BAD_ASYM_2"
    assert MODULE.FORMAL_R6_CLASSIFICATION == "C"


def test_only_preregistered_sparse_rule_is_reused() -> None:
    p = np.array([0.0, 0.899999, 0.90, 1.0])
    multiplier = np.where(p >= MODULE.R6.R6_INTERVENTION_PERCENTILE, MODULE.R6.R6_INTERVENTION_MULTIPLIER, 1.0)
    assert np.array_equal(multiplier, [1.0, 1.0, 0.5, 0.5])


def test_exploratory_diagnostic_never_changes_r6_classification() -> None:
    values = {
        "RETURN_RETENTION_VS_RAW": 0.95, "MDD_REDUCTION_VS_RAW": 0.20, "ES5_IMPROVEMENT_VS_RAW": 0.20,
        "MATERIALLY_BEATS_CONSTANT": True, "SHARPE_VALUE_OVER_CONSTANT": 0.2,
        "MDD_VALUE_OVER_CONSTANT": 0.1, "ES_VALUE_OVER_CONSTANT": 0.1, "RETURN_VALUE_OVER_CONSTANT": 0.1,
    }
    assert MODULE.diagnostic(values, 4) == "STRONG"
    assert MODULE.FORMAL_R6_CLASSIFICATION == "C"


def test_partial_and_none_diagnostics_are_fixed() -> None:
    partial = {
        "RETURN_RETENTION_VS_RAW": 0.88, "MDD_REDUCTION_VS_RAW": 0.02, "ES5_IMPROVEMENT_VS_RAW": 0.0,
        "MATERIALLY_BEATS_CONSTANT": False, "SHARPE_VALUE_OVER_CONSTANT": 0.01,
        "MDD_VALUE_OVER_CONSTANT": 0.0, "ES_VALUE_OVER_CONSTANT": 0.0, "RETURN_VALUE_OVER_CONSTANT": 0.0,
    }
    assert MODULE.diagnostic(partial, 1) == "PARTIAL"
    none = dict(partial, RETURN_RETENTION_VS_RAW=0.80)
    assert MODULE.diagnostic(none, 5) == "NONE"
