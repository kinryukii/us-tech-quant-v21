import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


MODULE_PATH = Path(__file__).with_name("fast_a2_r1_alpha_reliability_and_risk_budget.py")
SPEC = importlib.util.spec_from_file_location("fast_a2_r1_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_trailing_percentile_is_strictly_prior_and_has_fixed_warmup():
    values = np.arange(130, dtype=float)
    percentile, counts = mod.trailing_prior_percentile(values, lookback=252, minimum_history=126)
    assert np.isnan(percentile[:126]).all()
    assert counts[125] == 125
    assert percentile[126] == 1.0
    changed = values.copy()
    changed[127:] = 1e9
    changed_percentile, _ = mod.trailing_prior_percentile(changed, lookback=252, minimum_history=126)
    assert changed_percentile[126] == percentile[126]


def test_tie_policy_is_average_empirical_percentile():
    percentile, _ = mod.trailing_prior_percentile(np.ones(6), lookback=5, minimum_history=5)
    assert percentile[5] == 0.5


def test_frozen_contract_and_witness_are_hash_consistent_and_outcome_blind():
    contract_bytes = mod.CONTRACT_PATH.read_bytes()
    witness = json.loads(mod.WITNESS_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(contract_bytes).hexdigest() == witness["FAST_A2_R1_CONTRACT_SHA256"]
    assert witness["CONTRACT_FROZEN_BEFORE_A2_OUTCOME_READ"] is True
    assert witness["A2_PORTFOLIO_OUTCOME_READ_COUNT_BEFORE_FREEZE"] == 0


def test_daily_risk_state_is_pit_and_budget_is_binary():
    frame = pd.read_parquet(mod.DAILY_RISK_PATH)
    assert (frame["feature_information_cutoff"] < frame["trade_date"]).all()
    assert set(frame["risk_budget"].unique()) <= {0.5, 1.0}
    assert not (frame.loc[frame["insufficient_fast_history"], "risk_budget"] != 1.0).any()
    assert (frame["trade_date"] < pd.Timestamp("2026-01-01")).all()


def test_portfolio_identity_and_no_post2025_rows():
    frame = pd.read_parquet(mod.DAILY_PORTFOLIO_PATH)
    counts = frame.groupby("portfolio")["execution_date"].nunique()
    assert counts.nunique() == 1
    assert set(frame["portfolio"]) == {"A2_HGB_TOP20_1X", "FAST_GATED_A2_HGB_TOP20"}
    assert (frame["execution_date"] < pd.Timestamp("2026-01-01")).all()
    assert set(frame["cost_bps"]) == {10}


def test_summary_freezes_models_and_reproducibility():
    summary = json.loads(mod.SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["FAST_MODEL_FIT_COUNT"] == 0
    assert summary["FAST_MODEL_SELECTION_COUNT"] == 0
    assert summary["HYPERPARAMETER_SEARCH_TRIAL_COUNT"] == 0
    assert summary["POST2025_OUTCOME_READ_COUNT"] == 0
    assert summary["2026_A2_OUTCOME_READ_COUNT"] == 0
    assert summary["RUN1_FINGERPRINT"] == summary["RUN2_FINGERPRINT"]
    assert summary["REPRODUCIBILITY_STATUS"] == "PASS"
    assert summary["R4_EXECUTION_POLICY_SHA256"] == mod.EXPECTED_R4_POLICY_SHA256


def test_expected_artifact_schema():
    risk_names = set(pq.ParquetFile(mod.DAILY_RISK_PATH).schema_arrow.names)
    portfolio_names = set(pq.ParquetFile(mod.DAILY_PORTFOLIO_PATH).schema_arrow.names)
    assert {"trade_date", "fast_risk_score", "fast_risk_percentile", "high_risk", "risk_budget"} <= risk_names
    assert {"execution_date", "signal_date_used", "portfolio", "net_return", "gross_exposure", "risk_budget"} <= portfolio_names
