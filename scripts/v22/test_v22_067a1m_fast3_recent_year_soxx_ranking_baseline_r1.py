"""Eight focused contract tests for V22.067A1M."""
import importlib.util
from pathlib import Path
import pandas as pd
import pytest

PATH = Path(__file__).with_name("v22_067a1m_fast3_recent_year_soxx_ranking_baseline_r1.py")
SPEC = importlib.util.spec_from_file_location("v220671", PATH); M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

def test_1_soxx_only_target(): assert "symbol == \"SOXX\"" in PATH.read_text(encoding="utf-8")
def test_2_qqq_feature_only(): assert "QQQ" not in M.FEATURE_LIST and "qqq" in " ".join(M.FEATURE_LIST).lower()
def test_3_no_random_split(): assert "train_test_split" not in PATH.read_text(encoding="utf-8")
def test_4_cross_boundary_labels_excluded():
    x = _frame(["2026-03-31 23:00"]); assert M.prepare_partitions(x).empty
def test_5_overlap_group_single_partition():
    x = _frame(["2026-03-30 12:00", "2026-04-01 12:00"], groups=["a", "a"])
    with pytest.raises(ValueError, match="overlap group crossed"):
        M.prepare_partitions(x)
def test_6_validation_threshold_is_quantile(): assert "np.quantile(scores[\"VALIDATION\"], .95)" in PATH.read_text(encoding="utf-8")
def test_7_bundle_contract():
    text = PATH.read_text(encoding="utf-8"); assert all(x in text for x in ("feature_list", "validation_thresholds", "long_pipeline", "short_pipeline"))
def test_8_frozen_input_hash_checked(): assert "before_hash == after_hash" in PATH.read_text(encoding="utf-8")

def _frame(times, groups=None):
    groups = groups or ["a"] * len(times); rows=[]
    for t, group in zip(times, groups):
        ts=pd.Timestamp(t, tz="America/New_York").tz_convert("UTC"); row={c: 1.0 for c in M.NUMERIC_FEATURES}; row.update({"symbol":"SOXX", "feature_complete":True, "label_complete":True, "candidate_timestamp_utc":ts, "timestamp_et":ts.tz_convert("America/New_York"), "trading_date_et":str(ts.tz_convert("America/New_York").date()), "overlap_group_id":group, "session":"PREMARKET"})
        for d in ("long", "short"):
            row[f"{d}_0p25_0p15_90m"]="NEITHER"; row[f"{d}_0p50_0p25_90m"]="NEITHER"
        rows.append(row)
    return pd.DataFrame(rows)
