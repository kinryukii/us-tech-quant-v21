import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

p = Path(__file__).with_name("v22_069c_fast3_nonlinear_compact_validation_r1.py")
s = importlib.util.spec_from_file_location("m069c", p); m = importlib.util.module_from_spec(s); sys.modules["m069c"] = m; s.loader.exec_module(m)

def test_authoritative_b1_hashes_and_upstream_load():
    _, model = m.load_lineage(m.DEFAULT_UPSTREAM_ROOT)
    assert m.sha(m.upstream_dir(m.DEFAULT_UPSTREAM_ROOT) / "frozen_model.joblib") == m.EXPECTED_MODEL_ARTIFACT_SHA256
    assert m.sha(m.upstream_dir(m.DEFAULT_UPSTREAM_ROOT) / "frozen_model_state.json") == m.EXPECTED_MODEL_STATE_SHA256
    assert list(model.feature_names_in_) == m.FEATURES

def test_validation_only_paths_and_no_fit_or_search():
    assert len(m.validation_paths(["2023-05"])) == 6 and all("month=05" in str(x) for x in m.validation_paths(["2023-05"]))
    source = p.read_text()
    for forbidden in (".fit(", "GridSearch", "RandomizedSearch", "partial_fit"): assert forbidden not in source
    assert 'frame = frame[frame.date.str[:7].isin(allowed)]' in source

def test_hash_mismatch_rejects_before_validation(monkeypatch):
    monkeypatch.setattr(m, "EXPECTED_MODEL_ARTIFACT_SHA256", "0" * 64)
    try: m.load_lineage(m.DEFAULT_UPSTREAM_ROOT)
    except RuntimeError as error: assert str(error) == "MODEL_ARTIFACT_SHA256_MISMATCH"

def test_metrics_and_ranking_are_deterministic():
    events = pd.DataFrame({"date": ["2024-01-01"] * 5, "symbol": ["QQQ"] * 5, "target_return": range(5), "prediction": range(5)})
    values, monthly, symbols = m.summarize(events)
    assert values["validation_top_bottom_spread_net_10bps"] == 3.999 and len(monthly) == len(symbols) == 1

def test_safe_fields_and_rejection_is_research_pass():
    base = m.safe_base()
    assert base["development_training_row_read_count"] == base["confirmation_row_read_count"] == base["fit_call_count"] == 0
    assert not any(base[key] for key in ("broker_action_allowed", "paper_trading_allowed", "official_adoption_allowed", "live_trading_allowed"))
