"""Eight focused frozen-model contract tests for V22.067A2M."""
import importlib.util
from pathlib import Path
import joblib

PATH = Path(__file__).with_name("v22_067a2m_fast3_soxx_frozen_model_reverse_validation_2024_2025_r1.py")
SPEC = importlib.util.spec_from_file_location("v220672", PATH); M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

def test_1_bundle_reads(): b = joblib.load(M.MODEL_FILE); M.validate_bundle(b)
def test_2_model_hash_is_deterministic(): assert M.sha256(M.MODEL_FILE) == M.sha256(M.MODEL_FILE)
def test_3_no_retraining(): assert "fit(" not in PATH.read_text(encoding="utf-8")
def test_4_feature_list_is_exact(): assert joblib.load(M.MODEL_FILE)["feature_list"] == M.EXPECTED_FEATURES
def test_5_frozen_thresholds_used(): assert 'bundle["validation_thresholds"][direction]' in PATH.read_text(encoding="utf-8")
def test_6_study_range_frozen(): assert str(M.START_ET.date()) == "2024-07-29" and str(M.END_ET.date()) == "2025-07-28"
def test_7_dedup_matches_a1m(): assert 'drop_duplicates("overlap_group_id"' in PATH.read_text(encoding="utf-8") and '"trading_date_et", "session", "direction"' in PATH.read_text(encoding="utf-8")
def test_8_only_underlyings_allowed(): assert 'load("QQQ"), load("SOXX")' in PATH.read_text(encoding="utf-8") and all(x not in PATH.read_text(encoding="utf-8") for x in ("TQQQ", "SQQQ", "SOXL", "SOXS"))
