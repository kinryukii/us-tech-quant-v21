import importlib.util
import sys
from pathlib import Path
import numpy as np
import pandas as pd

P = Path(__file__).with_name("v22_071a_fast3_symbol_segmented_research_r1.py")
S = importlib.util.spec_from_file_location("v071a", P); M = importlib.util.module_from_spec(S); sys.modules["v071a"] = M; S.loader.exec_module(M)

def events(days=60):
    ds = pd.date_range("2024-01-01", periods=days, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame([{"date": d, "symbol": s, **{f: i / 100 for i, f in enumerate(M.FEATURES)}, "target_return": (j - 2) / 1000} for d in ds for j, s in enumerate(M.SYMS)])

def test_confirmation_is_unread_and_old_roles_are_research():
    source = P.read_text(encoding="utf-8")
    assert 'contract["split"]["confirmation_months"]' not in source
    assert "former_development_role\": \"RESEARCH_DATA" in source and "confirmation_row_read_count\": 0" in source

def test_strict_expanding_time_folds():
    folds = M.expanding_folds(pd.date_range("2024-01-01", periods=36, freq="B").strftime("%Y-%m-%d"))
    assert len(folds) == 5 and all(max(x["train_dates"]) < min(x["test_dates"]) for x in folds)

def test_no_random_kfold_or_search():
    source = P.read_text(encoding="utf-8")
    assert "KFold" not in source and "GridSearch" not in source and "RandomizedSearch" not in source

def test_exact_three_fixed_models():
    assert list(M.MODEL_SPECS) == ["RIDGE", "SHALLOW_TREE", "CONSTRAINED_RANDOM_FOREST"]
    assert M.MODEL_SPECS["SHALLOW_TREE"]["max_depth"] == 2 and M.MODEL_SPECS["CONSTRAINED_RANDOM_FOREST"]["n_estimators"] == 200

def test_pooled_and_segmented_evaluate():
    d = events(); a, sa, _ = M.evaluate(d, "POOLED", "RIDGE"); b, sb, _ = M.evaluate(d, "PER_SYMBOL", "RIDGE")
    assert a["event_count"] > 0 and b["event_count"] > 0 and len(sa) == len(sb) == 6

def test_segmented_gate_blocks_single_symbol_winner():
    row = {"structure": "PER_SYMBOL", "oof_spearman_ic": .1, "top_bottom_spread_net_10bps": .01, "positive_fold_ratio": 1, "median_fold_ic": .1, "positive_month_ratio": 1, "top5_date_concentration": .2}
    syms = [{"top_bottom_spread_net_10bps": .01}] + [{"top_bottom_spread_net_10bps": -.01}] * 5
    assert M.qualifies(row, syms)[0] is False

def test_negative_research_is_pass_not_failure():
    row = {"structure": "POOLED", "oof_spearman_ic": -.1, "top_bottom_spread_net_10bps": -.01, "positive_fold_ratio": 0, "median_fold_ic": -.1, "positive_month_ratio": 0, "top5_date_concentration": .2}
    assert M.qualifies(row, [])[0] is False

def test_metric_nulls_not_zero_and_safety_fields_present():
    got = M.metrics(pd.DataFrame(columns=["target_return", "prediction", "date"]), [])
    assert got["oof_spearman_ic"] is None and got["event_count"] == 0
    source = P.read_text(encoding="utf-8")
    for field in ("final_frozen_model_output_count", "order_output_count", "broker_connection_count"): assert field in source

def test_summary_output_shape():
    source = P.read_text(encoding="utf-8")
    for name in ("v22_071a_summary.json", "model_scorecard.csv", "symbol_scorecard.csv", "fold_scorecard.csv", "research_contract.json"): assert name in source
